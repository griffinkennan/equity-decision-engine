"""News and market/industry sentiment.

Three layers, each transparent about its inputs:
  1. Stock news tone — finance-specific keyword lexicon over recent headlines.
  2. Market regime — S&P 500 trend + VIX level (risk-on / neutral / risk-off).
  3. Industry trend — the stock's sector ETF trend.

Sentiment feeds the rating through a deliberately small factor weight (~4%):
news should tilt a fundamental rating, never drive it. Keyword scoring is a
heuristic — every matched term is surfaced so the user can judge it.
"""
from __future__ import annotations

from .data import fetch_price_history

BULLISH = [
    "beat", "beats", "tops estimates", "raises guidance", "raised guidance",
    "upgrade", "upgraded", "outperform", "record revenue", "record profit",
    "surge", "soars", "rally", "buyback", "dividend increase", "partnership",
    "contract win", "wins contract", "approval", "approved", "breakthrough",
    "strong demand", "accelerat", "expansion", "all-time high", "better-than-expected",
    "price target raised", "initiated with buy", "momentum", "growth streak",
]
BEARISH = [
    "miss", "misses", "falls short", "cuts guidance", "cut guidance", "lowered guidance",
    "downgrade", "downgraded", "underperform", "plunge", "plunges", "sinks", "slump",
    "layoff", "layoffs", "recall", "lawsuit", "probe", "investigation", "sec inquiry",
    "warning", "warns", "weak demand", "slowdown", "decline", "bankruptcy", "default",
    "dilution", "offering", "short seller", "fraud", "resign", "steps down",
    "price target cut", "disappointing", "headwind", "delisted", "going concern",
]


def _score_text(text: str):
    t = " " + (text or "").lower() + " "
    bull_hits = [w for w in BULLISH if w in t]
    bear_hits = [w for w in BEARISH if w in t]
    if len(bull_hits) > len(bear_hits):
        label = "Bullish"
    elif len(bear_hits) > len(bull_hits):
        label = "Bearish"
    else:
        label = "Neutral"
    return label, bull_hits, bear_hits


def analyze_news(news_items: list[dict]) -> dict:
    """Tag each headline and aggregate a net tone in [-1, 1]."""
    items, bull, bear = [], 0, 0
    for n in news_items or []:
        text = f"{n.get('title', '')} {n.get('summary', '')}"
        label, bh, sh = _score_text(text)
        if label == "Bullish":
            bull += 1
        elif label == "Bearish":
            bear += 1
        items.append({**n, "sentiment": label,
                      "matched": (bh + sh)[:4]})
    n_tot = len(items)
    net = (bull - bear) / n_tot if n_tot else 0.0
    if n_tot < 3:
        label = "Insufficient news"
    elif net > 0.3:
        label = "Bullish"
    elif net > 0.1:
        label = "Leaning bullish"
    elif net < -0.3:
        label = "Bearish"
    elif net < -0.1:
        label = "Leaning bearish"
    else:
        label = "Neutral"
    return {"items": items, "bullish": bull, "bearish": bear,
            "neutral": n_tot - bull - bear, "count": n_tot,
            "net_score": round(net, 3), "label": label,
            "note": "Keyword-lexicon tone over recent headlines — matched terms are "
                    "shown per article so you can judge the tagging yourself."}


def market_sentiment() -> dict:
    """S&P 500 trend + VIX level -> Risk-on / Neutral / Risk-off."""
    reasons, points = [], 0
    spy = fetch_price_history("SPY", "2y")
    if spy is not None and not spy.empty:
        close = spy["Close"].dropna()
        ma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else None
        if ma200 is not None:
            if float(close.iloc[-1]) > float(ma200):
                points += 1; reasons.append("S&P 500 above its 200-day average")
            else:
                points -= 1; reasons.append("S&P 500 below its 200-day average")
        if len(close) > 63:
            p3m = float(close.iloc[-1] / close.iloc[-64] - 1)
            if p3m > 0.03:
                points += 1; reasons.append(f"S&P 500 up {p3m:.0%} over 3 months")
            elif p3m < -0.03:
                points -= 1; reasons.append(f"S&P 500 down {p3m:.0%} over 3 months")
    vix = fetch_price_history("^VIX", "6mo")
    if vix is not None and not vix.empty:
        level = float(vix["Close"].dropna().iloc[-1])
        if level < 15:
            points += 1; reasons.append(f"VIX calm at {level:.0f}")
        elif level > 25:
            points -= 1; reasons.append(f"VIX elevated at {level:.0f}")
        else:
            reasons.append(f"VIX normal at {level:.0f}")
    regime = "Risk-on" if points >= 2 else "Risk-off" if points <= -2 else "Neutral"
    return {"regime": regime, "points": points, "reasons": reasons}


def industry_sentiment(momentum: dict) -> dict:
    """Sector-ETF trend from fields computed during the momentum pass."""
    etf = momentum.get("sector_etf")
    if not etf:
        return {"trend": "Unknown", "reasons": ["No sector ETF mapping for this stock."]}
    reasons, points = [], 0
    if momentum.get("etf_above_ma200") is True:
        points += 1; reasons.append(f"{etf} above its 200-day average")
    elif momentum.get("etf_above_ma200") is False:
        points -= 1; reasons.append(f"{etf} below its 200-day average")
    p3 = momentum.get("etf_perf_3m")
    if p3 is not None:
        if p3 > 0.03:
            points += 1; reasons.append(f"{etf} up {p3:.0%} over 3 months")
        elif p3 < -0.03:
            points -= 1; reasons.append(f"{etf} down {p3:.0%} over 3 months")
    trend = "Uptrend" if points >= 1 else "Downtrend" if points <= -1 else "Sideways"
    return {"trend": trend, "etf": etf, "points": points, "reasons": reasons}


def build_sentiment(snap: dict) -> dict:
    news = analyze_news(snap.get("news"))
    market = market_sentiment()
    industry = industry_sentiment(snap.get("momentum") or {})
    parts = []
    if news["label"] not in ("Insufficient news",):
        parts.append(f"Recent headlines lean {news['label'].lower()} "
                     f"({news['bullish']} bullish / {news['bearish']} bearish / "
                     f"{news['neutral']} neutral).")
    parts.append(f"Market regime: {market['regime'].lower()} — " + "; ".join(market["reasons"][:3]) + ".")
    if industry.get("reasons"):
        parts.append(f"Industry: {industry['trend'].lower()} — " + "; ".join(industry["reasons"][:2]) + ".")
    return {"news": news, "market": market, "industry": industry,
            "summary": " ".join(parts)}
