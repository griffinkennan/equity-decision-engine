"""Finnhub provider (free tier) — insider transactions and analyst
recommendation trends.

Activates when FINNHUB_API_KEY is present (free key: finnhub.io/register).
Free tier: 60 calls/min. Fails soft like every other provider.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://finnhub.io/api/v1"


def api_key():
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        env = Path(__file__).resolve().parent.parent / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.strip().startswith("FINNHUB_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    return key or None


def enabled() -> bool:
    return bool(api_key())


def _get(path: str, **params):
    try:
        params["token"] = api_key()
        url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "equity-decision-engine"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def insider_summary(ticker: str) -> dict | None:
    """Aggregate last-12-month insider transactions with share counts."""
    if not enabled():
        return None
    frm = (dt.date.today() - dt.timedelta(days=365)).isoformat()
    data = _get("stock/insider-transactions", symbol=ticker, **{"from": frm})
    rows = (data or {}).get("data") or []
    if not rows:
        return None
    buys = sells = 0
    buy_shares = sell_shares = 0.0
    for r in rows:
        change = r.get("change") or 0
        if change > 0:
            buys += 1
            buy_shares += change
        elif change < 0:
            sells += 1
            sell_shares += -change
    return {
        "source": "Finnhub", "window": "12 months",
        "buy_transactions": buys, "sell_transactions": sells,
        "shares_bought": buy_shares, "shares_sold": sell_shares,
        "net_shares": buy_shares - sell_shares,
    }


def recommendation_trend(ticker: str) -> dict | None:
    """Most recent month's analyst recommendation counts + 3-month drift."""
    if not enabled():
        return None
    rows = _get("stock/recommendation", symbol=ticker)
    if not isinstance(rows, list) or not rows:
        return None
    cur = rows[0]

    def bull_ratio(r):
        buys = (r.get("strongBuy") or 0) + (r.get("buy") or 0)
        total = buys + (r.get("hold") or 0) + (r.get("sell") or 0) + (r.get("strongSell") or 0)
        return buys / total if total else None

    out = {
        "source": "Finnhub", "period": cur.get("period"),
        "strong_buy": cur.get("strongBuy"), "buy": cur.get("buy"),
        "hold": cur.get("hold"), "sell": cur.get("sell"),
        "strong_sell": cur.get("strongSell"),
        "bullish_ratio": round(bull_ratio(cur), 3) if bull_ratio(cur) is not None else None,
    }
    if len(rows) > 3:
        prev = bull_ratio(rows[3])
        if prev is not None and out["bullish_ratio"] is not None:
            drift = out["bullish_ratio"] - prev
            out["drift_3m"] = round(drift, 3)
            out["drift_label"] = ("improving" if drift > 0.03
                                  else "deteriorating" if drift < -0.03 else "stable")
    return out
