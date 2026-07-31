"""Point-in-time backtest of a simplified version of the scoring model.

Honesty notes (surfaced in the UI):
- Yahoo Finance provides ~4-5 annual and ~5-6 quarterly statements, so the
  backtest window is limited (typically 1-3 years of signal dates).
- Historical analyst estimates are NOT available, so the historical score uses
  only fundamentals + momentum that existed at each date (no forward factor).
- Statements are assumed public 75 days after fiscal period end (10-K/10-Q lag),
  which avoids lookahead on fundamentals.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import yfinance as yf

from .data import fetch_price_history, safe_div
from .scoring import rating_from_score, scale, scale_low

REPORT_LAG_DAYS = 75
HORIZONS = {"1m": 21, "3m": 63, "6m": 126, "1y": 252}


def _annual_statements(t):
    try:
        inc, bal, cf = t.income_stmt, t.balance_sheet, t.cashflow
        return inc, bal, cf
    except Exception:
        return None, None, None


def _val_at(df, label_options, col):
    if df is None or df.empty:
        return None
    for label in label_options:
        if label in df.index:
            try:
                v = df.loc[label, col]
                v = float(v)
                if v == v:  # not NaN
                    return v
            except Exception:
                continue
    return None


def _historical_score(fund, mom_block):
    """Reduced-form score (fundamentals + momentum only), same band logic as live model."""
    parts = []  # (score, weight)

    def add(score, weight):
        if score is not None:
            parts.append((score, weight))

    add(scale(fund.get("rev_growth"), [(0.30, 95), (0.20, 85), (0.12, 72), (0.06, 60),
                                       (0.02, 48), (0.0, 40), (-0.05, 28), (-1, 12)]), 14)
    add(scale(fund.get("ni_growth"), [(0.25, 92), (0.15, 80), (0.08, 66), (0.02, 55),
                                      (0.0, 45), (-0.10, 32), (-1, 15)]), 10)
    add(scale(fund.get("fcf_margin"), [(0.25, 95), (0.15, 82), (0.08, 68), (0.03, 55),
                                       (0.0, 45), (-1, 22)]), 16)
    add(scale(fund.get("net_margin"), [(0.20, 92), (0.12, 78), (0.06, 62), (0.01, 48), (-1, 25)]), 12)
    add(scale_low(fund.get("debt_to_equity"), [(0.3, 90), (0.7, 75), (1.2, 60),
                                               (2.0, 42), (3.5, 25), (99, 12)]), 12)
    add(scale_low(fund.get("ps"), [(2, 85), (4, 70), (8, 55), (15, 38), (999, 22)]), 16)
    add(scale(mom_block.get("perf_6m"), [(0.15, 80), (0.0, 60), (-0.15, 40), (-1, 22)]), 10)
    add(70 if mom_block.get("above_ma200") else 35, 10)
    if not parts:
        return None
    tw = sum(w for _, w in parts)
    return round(sum(s * w for s, w in parts) / tw, 1)


def run_backtest(ticker: str):
    ticker = ticker.strip().upper()
    t = yf.Ticker(ticker)
    inc, bal, cf = _annual_statements(t)
    if inc is None or inc.empty:
        return {"error": "No historical statements available for backtesting."}

    hist = fetch_price_history(ticker, period="6y")
    spy = fetch_price_history("SPY", period="6y")
    if hist is None or hist.empty:
        return {"error": "No price history available."}
    close = hist["Close"].dropna()
    close.index = close.index.tz_localize(None)
    spy_close = spy["Close"].dropna() if spy is not None else None
    if spy_close is not None:
        spy_close.index = spy_close.index.tz_localize(None)

    cols = sorted(inc.columns.tolist())  # fiscal year ends, oldest first
    results = []
    today = pd.Timestamp.today().normalize()

    for i, col in enumerate(cols):
        as_of = pd.Timestamp(col) + pd.Timedelta(days=REPORT_LAG_DAYS)
        if as_of >= today - pd.Timedelta(days=30):
            continue
        px = close[close.index <= as_of]
        if len(px) < 210:
            continue
        price = float(px.iloc[-1])
        prev_col = cols[i - 1] if i > 0 else None

        rev = _val_at(inc, ["Total Revenue", "Operating Revenue"], col)
        rev_prev = _val_at(inc, ["Total Revenue", "Operating Revenue"], prev_col) if prev_col else None
        ni = _val_at(inc, ["Net Income", "Net Income Common Stockholders"], col)
        ni_prev = _val_at(inc, ["Net Income", "Net Income Common Stockholders"], prev_col) if prev_col else None
        fcf = _val_at(cf, ["Free Cash Flow"], col)
        debt = _val_at(bal, ["Total Debt"], col)
        eq = _val_at(bal, ["Stockholders Equity", "Common Stock Equity"], col)
        shares = _val_at(bal, ["Ordinary Shares Number", "Share Issued"], col)
        mcap = price * shares if shares else None

        fund = {
            "rev_growth": safe_div(rev - rev_prev, abs(rev_prev)) if (rev and rev_prev) else None,
            "ni_growth": safe_div(ni - ni_prev, abs(ni_prev)) if (ni is not None and ni_prev) else None,
            "fcf_margin": safe_div(fcf, rev),
            "net_margin": safe_div(ni, rev),
            "debt_to_equity": safe_div(debt, eq) if (eq or 0) > 0 else None,
            "ps": safe_div(mcap, rev),
        }
        ma200 = float(px.rolling(200).mean().iloc[-1])
        perf_6m = float(px.iloc[-1] / px.iloc[-126] - 1) if len(px) > 126 else None
        score = _historical_score(fund, {"above_ma200": price > ma200, "perf_6m": perf_6m})
        if score is None:
            continue

        fwd = {}
        mdd_1y = None
        for label, days in HORIZONS.items():
            fut = close[close.index > as_of]
            sp_fut = spy_close[spy_close.index > as_of] if spy_close is not None else None
            if len(fut) > days:
                r = float(fut.iloc[days] / price - 1)
                fwd[label] = r
                if sp_fut is not None and len(sp_fut) > days:
                    sp0 = float(spy_close[spy_close.index <= as_of].iloc[-1])
                    fwd[label + "_vs_spy"] = r - (float(sp_fut.iloc[days]) / sp0 - 1)
                if label == "1y":
                    window = fut.iloc[:days + 1]
                    mdd_1y = float((window / window.cummax() - 1).min())
        results.append({
            "max_drawdown_1y": round(mdd_1y, 4) if mdd_1y is not None else None,
            "as_of": str(as_of.date()),
            "statement_date": str(pd.Timestamp(col).date()),
            "score": score,
            "rating": rating_from_score(score),
            "price": round(price, 2),
            "forward_returns": {k: round(v, 4) for k, v in fwd.items()},
        })

    if not results:
        return {"error": "Not enough overlapping statement + price history to backtest this ticker."}

    # aggregate stats
    buys = [r for r in results if r["rating"] in ("Buy", "Strong Buy")]
    sells = [r for r in results if r["rating"] in ("Sell", "Strong Sell")]

    def agg(group, key="1y_vs_spy", fallback="1y"):
        vals = [r["forward_returns"].get(key, r["forward_returns"].get(fallback))
                for r in group]
        vals = [v for v in vals if v is not None]
        if not vals:
            return None
        vals.sort()
        return {"n": len(vals), "avg": round(sum(vals) / len(vals), 4),
                "median": round(vals[len(vals) // 2], 4),
                "win_rate": round(sum(1 for v in vals if v > 0) / len(vals), 3)}

    false_buys = sum(1 for r in buys
                     if (r["forward_returns"].get("1y_vs_spy") or 0) < -0.05)
    false_sells = sum(1 for r in sells
                      if (r["forward_returns"].get("1y_vs_spy") or 0) > 0.05)

    buy_mdds = [r["max_drawdown_1y"] for r in buys if r.get("max_drawdown_1y") is not None]
    avg_buy_drawdown = round(sum(buy_mdds) / len(buy_mdds), 4) if buy_mdds else None
    all_mdds = [r["max_drawdown_1y"] for r in results if r.get("max_drawdown_1y") is not None]
    worst_drawdown = round(min(all_mdds), 4) if all_mdds else None

    return {
        "avg_buy_drawdown_1y": avg_buy_drawdown,
        "worst_drawdown_1y": worst_drawdown,
        "ticker": ticker,
        "signals": results,
        "buy_stats_vs_spy": agg(buys),
        "sell_stats_vs_spy": agg(sells),
        "all_stats_vs_spy": agg(results),
        "false_buy_signals": false_buys,
        "false_sell_signals": false_sells,
        "methodology": {
            "report_lag_days": REPORT_LAG_DAYS,
            "notes": [
                "Historical scores use ONLY annual statements assumed public 75 days after "
                "fiscal year end, plus price data up to each signal date — no lookahead.",
                "Historical analyst estimates are unavailable, so the forward-outlook factor "
                "is excluded from historical scores (a reduced-form model).",
                "Yahoo Finance keeps ~4-5 annual statements, so sample sizes are small; "
                "treat statistics as illustrative.",
                "Results are a historical simulation, not a guarantee of future performance.",
            ],
        },
    }
