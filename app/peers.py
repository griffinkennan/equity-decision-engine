"""Peer discovery and comparison.

Peers come from yfinance's industry top-companies list when available, with a
curated sector fallback. Peer fundamentals use the lightweight `info` call only
(fetched in parallel) to keep analysis fast.
"""
from __future__ import annotations

import time
import threading
from concurrent.futures import ThreadPoolExecutor

import yfinance as yf

from .data import _get, _norm_div_yield, safe_div

_PEER_CACHE: dict[str, tuple[float, dict]] = {}
_LOCK = threading.Lock()
TTL = 30 * 60

SECTOR_FALLBACK = {
    "Technology": ["MSFT", "AAPL", "NVDA", "ORCL", "CRM", "ADBE"],
    "Communication Services": ["GOOGL", "META", "NFLX", "DIS", "TMUS"],
    "Consumer Cyclical": ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX"],
    "Consumer Defensive": ["PG", "KO", "PEP", "COST", "WMT", "CL"],
    "Healthcare": ["LLY", "UNH", "JNJ", "ABBV", "MRK", "PFE"],
    "Financial Services": ["JPM", "BAC", "WFC", "GS", "MS", "V"],
    "Industrials": ["CAT", "HON", "UNP", "GE", "BA", "DE"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG"],
    "Utilities": ["NEE", "DUK", "SO", "D", "AEP"],
    "Real Estate": ["PLD", "AMT", "EQIX", "SPG", "O"],
    "Basic Materials": ["LIN", "SHW", "FCX", "NEM", "APD"],
}

COMPARE_METRICS = [
    ("rev_growth", "Revenue growth (1y)", "pct", True),
    ("gross_margin", "Gross margin", "pct", True),
    ("operating_margin", "Operating margin", "pct", True),
    ("net_margin", "Net margin", "pct", True),
    ("fcf_margin", "FCF margin", "pct", True),
    ("roe", "Return on equity", "pct", True),
    ("pe", "P/E (trailing)", "x", False),
    ("forward_pe", "Forward P/E", "x", False),
    ("ps", "Price/sales", "x", False),
    ("ev_ebitda", "EV/EBITDA", "x", False),
    ("debt_to_equity", "Debt/equity", "x", False),
    ("perf_12m", "12-month stock performance", "pct", True),
]


def _peer_metrics(ticker: str):
    try:
        info = yf.Ticker(ticker).info or {}
        if not info.get("marketCap"):
            return None
        fcf, rev = _get(info, "freeCashflow"), _get(info, "totalRevenue")
        return {
            "ticker": ticker,
            "name": info.get("shortName") or ticker,
            "market_cap": _get(info, "marketCap"),
            "rev_growth": _get(info, "revenueGrowth"),
            "gross_margin": _get(info, "grossMargins"),
            "operating_margin": _get(info, "operatingMargins"),
            "net_margin": _get(info, "profitMargins"),
            "fcf_margin": safe_div(fcf, rev),
            "roe": _get(info, "returnOnEquity"),
            "pe": _get(info, "trailingPE"),
            "forward_pe": _get(info, "forwardPE"),
            "ps": _get(info, "priceToSalesTrailing12Months"),
            "ev_ebitda": _get(info, "enterpriseToEbitda"),
            "ev_revenue": _get(info, "enterpriseToRevenue"),
            "debt_to_equity": safe_div(_get(info, "totalDebt"),
                                       safe_div(_get(info, "marketCap"), _get(info, "priceToBook"))),
            "perf_12m": _get(info, "52WeekChange", "fiftyTwoWeekChangePercent"),
            "dividend_yield": _norm_div_yield(_get(info, "dividendYield")),
        }
    except Exception:
        return None


def discover_peers(snap, max_peers=4) -> list[str]:
    ticker = snap["ticker"]
    candidates: list[str] = []
    try:
        key = snap.get("industry_key")
        if key:
            top = yf.Industry(key).top_companies
            if top is not None and not top.empty and "market weight" in top.columns:
                top = top.sort_values("market weight", ascending=False)
                # only accept industry peers that are a meaningful share of the
                # industry — avoids comparing a mega-cap to micro-caps
                top = top[top["market weight"] >= 0.02]
                candidates = [str(s) for s in top.index.tolist()]
    except Exception:
        pass
    peers = [c for c in candidates if c.upper() != ticker.upper()]
    if len(peers) < 2:
        fallback = SECTOR_FALLBACK.get(snap.get("sector") or "", [])
        peers += [c for c in fallback if c.upper() != ticker.upper() and c not in peers]
    return peers[:max_peers]


def peer_comparison(snap):
    ticker = snap["ticker"]
    with _LOCK:
        hit = _PEER_CACHE.get(ticker)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]

    peers = discover_peers(snap)
    if not peers:
        return {"peers": [], "rows": [], "summary": "No peer data available.", "stats": {}}

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = [r for r in ex.map(_peer_metrics, peers) if r]

    m, mom = snap["metrics"], snap["momentum"]
    company = {
        "rev_growth": m.get("rev_growth_1y"), "gross_margin": m.get("gross_margin"),
        "operating_margin": m.get("operating_margin"), "net_margin": m.get("net_margin"),
        "fcf_margin": m.get("fcf_margin"), "roe": m.get("roe"), "pe": m.get("pe"),
        "forward_pe": m.get("forward_pe"), "ps": m.get("ps"), "ev_ebitda": m.get("ev_ebitda"),
        "debt_to_equity": m.get("debt_to_equity"), "perf_12m": mom.get("perf_12m"),
    }

    rows = []
    for key, label, fmt, higher_better in COMPARE_METRICS:
        vals = sorted(v[key] for v in results if v.get(key) is not None)
        median = vals[len(vals) // 2] if vals else None
        cv = company.get(key)
        better = None
        if cv is not None and median is not None:
            better = (cv > median) if higher_better else (cv < median)
        rows.append({"key": key, "label": label, "format": fmt,
                     "higher_is_better": higher_better,
                     "company": cv, "peer_median": median, "better": better,
                     "peer_values": {v["ticker"]: v.get(key) for v in results}})

    # blended valuation premium vs peers (P/S + EV/EBITDA + forward P/E)
    prems = []
    for key in ("ps", "ev_ebitda", "forward_pe"):
        row = next(r for r in rows if r["key"] == key)
        if row["company"] and row["peer_median"] and row["peer_median"] > 0 and row["company"] > 0:
            prems.append(row["company"] / row["peer_median"] - 1)
    premium = sum(prems) / len(prems) if prems else None

    judged = [r for r in rows if r["better"] is not None]
    wins = sum(1 for r in judged if r["better"])
    growth_row = next(r for r in rows if r["key"] == "rev_growth")
    faster = (growth_row["better"] is True)
    parts = []
    if judged:
        parts.append(f"{snap['ticker']} beats the peer median on {wins} of {len(judged)} compared metrics.")
    if growth_row["company"] is not None and growth_row["peer_median"] is not None:
        parts.append(f"It is growing {'faster' if faster else 'slower'} than peers "
                     f"({growth_row['company']:.0%} vs {growth_row['peer_median']:.0%} median).")
    if premium is not None:
        if premium > 0.15:
            parts.append(f"It trades at a ~{premium:.0%} valuation premium to peers"
                         + (", which its superior metrics may justify." if wins / max(1, len(judged)) > 0.6
                            else ", which looks hard to justify on current numbers."))
        elif premium < -0.15:
            parts.append(f"It trades at a ~{abs(premium):.0%} discount to peers"
                         + (" despite comparable or better metrics — a potential opportunity."
                            if wins / max(1, len(judged)) >= 0.5 else ", reflecting weaker fundamentals."))
        else:
            parts.append("Its valuation is roughly in line with peers.")

    out = {
        "peers": [{"ticker": r["ticker"], "name": r["name"], "market_cap": r["market_cap"]}
                  for r in results],
        "rows": rows,
        "summary": " ".join(parts) if parts else "Peer comparison data is limited.",
        "stats": {"valuation_premium": premium, "wins": wins, "total": len(judged)},
    }
    with _LOCK:
        _PEER_CACHE[ticker] = (time.time(), out)
    return out
