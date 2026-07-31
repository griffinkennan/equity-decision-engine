"""Optional Financial Modeling Prep provider.

Activates automatically when an API key is present (FMP_API_KEY env var, or a
line `FMP_API_KEY=...` in the project-root .env file). Adds:
  - up to 10 years of annual statements (extends Yahoo's ~4-5 years)
  - earnings-call transcript tone analysis (vs. the prior quarter)
Every FMP call fails soft: on any error the app simply keeps Yahoo-only data.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

# FMP retired its /api/v3 endpoints for new accounts (they 403 as "Legacy");
# the /stable API is the supported surface. Free tier: statements capped at
# limit=5 (annual), transcripts require a paid tier (fail soft to None).
BASE = "https://financialmodelingprep.com/stable"
_KEY_CACHE: list = []  # [key_or_None] once resolved


def api_key():
    if _KEY_CACHE:
        return _KEY_CACHE[0]
    key = os.environ.get("FMP_API_KEY")
    if not key:
        env = Path(__file__).resolve().parent.parent / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.strip().startswith("FMP_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    _KEY_CACHE.append(key or None)
    return _KEY_CACHE[0]


def enabled() -> bool:
    return bool(api_key())


def _get(path, **params):
    try:
        params["apikey"] = api_key()
        url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "equity-decision-engine"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        if isinstance(data, dict) and data.get("Error Message"):
            return None
        return data
    except Exception:
        return None


# FMP /stable field -> our series key (sign conventions verified identical to
# yfinance: capex/dividends/buybacks negative, OCF/SBC positive)
_INCOME_MAP = {
    "revenue": "revenue", "grossProfit": "gross_profit",
    "operatingIncome": "operating_income", "ebitda": "ebitda", "ebit": "ebit",
    "netIncome": "net_income", "eps": "eps", "epsDiluted": "diluted_eps",
    "researchAndDevelopmentExpenses": "rnd",
    "sellingGeneralAndAdministrativeExpenses": "sgna",
    "interestExpense": "interest_expense", "incomeTaxExpense": "tax_expense",
    "weightedAverageShsOut": "shares",
    "netInterestIncome": "net_interest_income", "interestIncome": "interest_income",
}
_BALANCE_MAP = {
    "cashAndCashEquivalents": "cash", "shortTermInvestments": "short_term_investments",
    "totalAssets": "total_assets", "totalLiabilities": "total_liabilities",
    "totalDebt": "total_debt", "shortTermDebt": "short_term_debt",
    "longTermDebt": "long_term_debt", "netDebt": "net_debt",
    "totalCurrentAssets": "current_assets", "totalCurrentLiabilities": "current_liabilities",
    "totalStockholdersEquity": "equity", "retainedEarnings": "retained_earnings",
    "netReceivables": "receivables", "inventory": "inventory",
}
_CASHFLOW_MAP = {
    "operatingCashFlow": "ocf", "capitalExpenditure": "capex",
    "freeCashFlow": "fcf", "stockBasedCompensation": "sbc",
    "commonStockRepurchased": "buybacks", "commonDividendsPaid": "dividends_paid",
    "depreciationAndAmortization": "dna", "acquisitionsNet": "acquisitions",
}


def extend_annual_series(ticker: str, series: dict) -> bool:
    """Prepend older FMP annual data to Yahoo-derived series. Returns True if extended."""
    import datetime as dt
    extended = False
    for path, mapping in (("income-statement", _INCOME_MAP),
                          ("balance-sheet-statement", _BALANCE_MAP),
                          ("cash-flow-statement", _CASHFLOW_MAP)):
        rows = _get(path, symbol=ticker, period="annual", limit=5)
        if not isinstance(rows, list) or not rows:
            continue
        for fmp_field, key in mapping.items():
            existing = series.get(key) or []
            if existing:
                # only accept years clearly older than Yahoo's earliest —
                # FMP/Yahoo fiscal year-end dates can differ by a few days,
                # and a near-duplicate year would distort every growth trend
                cutoff = (dt.date.fromisoformat(existing[0]["date"][:10])
                          - dt.timedelta(days=90)).isoformat()
            else:
                cutoff = "9999-12-31"
            older = []
            for r in rows:  # FMP returns newest first
                date, val = r.get("date"), r.get(fmp_field)
                if date and val is not None and date < cutoff:
                    try:
                        v = float(val)
                    except (TypeError, ValueError):
                        continue
                    if v != 0:
                        older.append({"date": date, "value": v})
            if older:
                older.sort(key=lambda d: d["date"])
                series[key] = older + existing
                extended = True
    return extended


# --- transcript tone analysis -------------------------------------------------

_BULLISH = ["strong demand", "record", "raised guidance", "raising guidance", "exceeded",
            "momentum", "acceleration", "accelerating", "confident", "robust", "strength",
            "outperform", "ahead of plan", "better than expected", "tailwind", "expansion"]
_CAUTIOUS = ["headwind", "softness", "soft demand", "slowdown", "uncertain", "uncertainty",
             "challenging", "decline", "pressure", "cautious", "weakness", "lowered guidance",
             "below expectations", "delayed", "pushout", "macro environment", "difficult"]
_TOPICS = ["ai", "artificial intelligence", "cloud", "data center", "cost cutting",
           "cost reduction", "pricing", "competition", "backlog", "margin", "demand",
           "supply chain", "restructuring", "buyback", "capital return"]


def _tone_counts(text: str):
    t = text.lower()
    bull = sum(t.count(k) for k in _BULLISH)
    bear = sum(t.count(k) for k in _CAUTIOUS)
    topics = {k: t.count(k) for k in _TOPICS}
    topics = {k: v for k, v in sorted(topics.items(), key=lambda kv: -kv[1]) if v > 0}
    return bull, bear, topics


def _tone_label(bull, bear):
    total = bull + bear
    if total < 4:
        return "Neutral"
    ratio = bull / total
    if ratio >= 0.70:
        return "Bullish"
    if ratio >= 0.55:
        return "Neutral"
    if ratio >= 0.40:
        return "Cautious"
    return "Bearish"


def _guidance_excerpts(text: str, limit=3):
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        s = sent.strip()
        low = s.lower()
        if any(k in low for k in ("we expect", "guidance", "outlook for", "we anticipate",
                                  "we are raising", "we are lowering")):
            if 40 < len(s) < 320:
                out.append(s)
        if len(out) >= limit:
            break
    return out


def transcript_analysis(ticker: str):
    """Analyze the two most recent earnings-call transcripts.

    Returns None when unavailable — on FMP's free tier the transcript
    endpoints answer 402 (paid feature), which fails soft here.
    """
    rows = _get("earning-call-transcript-latest", symbol=ticker, limit=2)
    if not isinstance(rows, list) or not rows or not rows[0].get("content"):
        return None
    cur = rows[0]

    def _fmt_q(row):
        q = str(row.get("quarter") or row.get("period") or "?").lstrip("Q")
        return f"Q{q} {row.get('year', '')}".strip()

    bull, bear, topics = _tone_counts(cur["content"])
    tone = _tone_label(bull, bear)
    result = {
        "available": True,
        "source": "Financial Modeling Prep earnings-call transcript",
        "quarter": _fmt_q(cur),
        "date": str(cur.get("date", ""))[:10],
        "tone": tone,
        "bullish_signals": bull,
        "cautious_signals": bear,
        "topics": topics,
        "guidance_excerpts": _guidance_excerpts(cur["content"]),
        "note": "Tone is a keyword-frequency heuristic over the full call transcript "
                "(management remarks + Q&A) — a screening aid, not a substitute for reading the call.",
    }
    if len(rows) > 1 and rows[1].get("content"):
        pb, pbear, _ = _tone_counts(rows[1]["content"])
        prev_tone = _tone_label(pb, pbear)
        order = ["Bearish", "Cautious", "Neutral", "Bullish"]
        delta = order.index(tone) - order.index(prev_tone)
        result["prior_quarter"] = _fmt_q(rows[1])
        result["prior_tone"] = prev_tone
        result["tone_change"] = ("improved" if delta > 0 else "deteriorated" if delta < 0
                                 else "unchanged") + f" vs {result['prior_quarter']} ({prev_tone})"
    return result
