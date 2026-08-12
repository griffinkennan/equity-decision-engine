"""SEC EDGAR provider — official filed fundamentals, no API key required.

Uses the SEC's XBRL "company facts" API to extend annual statement series with
10+ years of as-filed data. The SEC asks for a descriptive User-Agent with
contact info and ~10 req/sec max; we send one facts request per ticker and
cache aggressively. Everything fails soft — no EDGAR, no harm.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
import urllib.request

USER_AGENT = "EquityDecisionEngine/1.5 (personal research tool; griffinkennan@gmail.com)"

_TICKER_MAP: dict[str, str] = {}          # "AAPL" -> zero-padded CIK
_FACTS_CACHE: dict[str, tuple[float, dict]] = {}
_LOCK = threading.Lock()
FACTS_TTL = 24 * 3600

# XBRL us-gaap tag(s) -> our series key. First tag with data wins.
# "neg" flips sign to match our (yfinance) conventions.
_TAG_MAP = [
    (("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
      "SalesRevenueNet"), "revenue", False, "duration"),
    (("GrossProfit",), "gross_profit", False, "duration"),
    (("OperatingIncomeLoss",), "operating_income", False, "duration"),
    (("NetIncomeLoss",), "net_income", False, "duration"),
    (("EarningsPerShareDiluted",), "diluted_eps", False, "duration"),
    (("EarningsPerShareBasic",), "eps", False, "duration"),
    (("ResearchAndDevelopmentExpense",), "rnd", False, "duration"),
    (("InterestExpense", "InterestExpenseDebt"), "interest_expense", False, "duration"),
    (("IncomeTaxExpenseBenefit",), "tax_expense", False, "duration"),
    (("NetCashProvidedByUsedInOperatingActivities",), "ocf", False, "duration"),
    (("PaymentsToAcquirePropertyPlantAndEquipment",), "capex", True, "duration"),
    (("ShareBasedCompensation",), "sbc", False, "duration"),
    (("PaymentsOfDividends", "PaymentsOfDividendsCommonStock"), "dividends_paid", True, "duration"),
    (("PaymentsForRepurchaseOfCommonStock",), "buybacks", True, "duration"),
    (("DepreciationDepletionAndAmortization", "DepreciationAndAmortization"),
     "dna", False, "duration"),
    (("WeightedAverageNumberOfDilutedSharesOutstanding",), "shares", False, "duration"),
    (("Assets",), "total_assets", False, "instant"),
    (("Liabilities",), "total_liabilities", False, "instant"),
    (("StockholdersEquity",), "equity", False, "instant"),
    (("RetainedEarningsAccumulatedDeficit",), "retained_earnings", False, "instant"),
    (("CashAndCashEquivalentsAtCarryingValue",), "cash", False, "instant"),
    (("AssetsCurrent",), "current_assets", False, "instant"),
    (("LiabilitiesCurrent",), "current_liabilities", False, "instant"),
    (("LongTermDebtNoncurrent", "LongTermDebt"), "long_term_debt", False, "instant"),
    (("InventoryNet",), "inventory", False, "instant"),
    (("AccountsReceivableNetCurrent",), "receivables", False, "instant"),
]


def _get_json(url: str, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept-Encoding": "gzip, deflate"})
    import gzip
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return json.loads(raw.decode())


def _cik_for(ticker: str) -> str | None:
    with _LOCK:
        if _TICKER_MAP:
            return _TICKER_MAP.get(ticker.upper())
    try:
        data = _get_json("https://www.sec.gov/files/company_tickers.json")
        mapping = {row["ticker"].upper(): f"{row['cik_str']:010d}"
                   for row in data.values()}
        with _LOCK:
            _TICKER_MAP.update(mapping)
        return mapping.get(ticker.upper())
    except Exception:
        return None


def _company_facts(cik: str) -> dict | None:
    with _LOCK:
        hit = _FACTS_CACHE.get(cik)
        if hit and time.time() - hit[0] < FACTS_TTL:
            return hit[1]
    try:
        facts = _get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    except Exception:
        return None
    with _LOCK:
        _FACTS_CACHE[cik] = (time.time(), facts)
    return facts


def _annual_points(gaap: dict, tags, kind: str) -> list[dict]:
    """[{date, value}] of fiscal-year (10-K) observations, oldest first.

    Merges across tag aliases: companies switch tags over the years (e.g.
    SalesRevenueNet -> Revenues), so one alias rarely covers the whole
    history. Earlier tags in the list win on conflicts.
    """
    by_end: dict[str, dict] = {}
    for priority, tag in enumerate(tags):
        node = gaap.get(tag)
        if not node:
            continue
        units = node.get("units", {})
        rows = units.get("USD") or units.get("USD/shares") or units.get("shares") or []
        for r in rows:
            if r.get("form") != "10-K" or r.get("val") is None or not r.get("end"):
                continue
            if kind == "duration":
                start = r.get("start")
                if not start:
                    continue
                try:
                    days = (dt.date.fromisoformat(r["end"]) - dt.date.fromisoformat(start)).days
                except ValueError:
                    continue
                if not 300 <= days <= 400:      # full fiscal years only
                    continue
            prev = by_end.get(r["end"])
            # a higher-priority tag beats a lower one; within a tag, the most
            # recently filed value wins (captures restatements)
            if prev is None or priority < prev["_prio"] or (
                    priority == prev["_prio"]
                    and (r.get("filed") or "") >= (prev.get("filed") or "")):
                by_end[r["end"]] = {**r, "_prio": priority}
    return sorted(({"date": end, "value": float(r["val"])}
                   for end, r in by_end.items()), key=lambda d: d["date"])


def extend_annual_series(ticker: str, series: dict, max_years=15) -> bool:
    """Prepend official EDGAR history older than what we already have."""
    cik = _cik_for(ticker)
    if not cik:
        return False
    facts = _company_facts(cik)
    gaap = (facts or {}).get("facts", {}).get("us-gaap")
    if not gaap:
        return False
    extended = False
    for tags, key, neg, kind in _TAG_MAP:
        existing = series.get(key) or []
        if existing:
            cutoff = (dt.date.fromisoformat(existing[0]["date"][:10])
                      - dt.timedelta(days=90)).isoformat()
        else:
            cutoff = "9999-12-31"
        points = _annual_points(gaap, tags, kind)
        older = [{"date": p["date"], "value": -p["value"] if neg else p["value"]}
                 for p in points if p["date"] < cutoff][-max_years:]
        if older:
            series[key] = older + existing
            extended = True
    return extended
