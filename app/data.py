"""Data layer: fetch and normalize everything the scoring engine needs.

All values come from Yahoo Finance via yfinance. Every accessor is wrapped so a
missing field becomes None instead of an exception; the Data Quality score
counts what is missing.
"""
from __future__ import annotations

import math
import time
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import yfinance as yf

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
CACHE_TTL = 15 * 60  # seconds


def _num(x):
    """Coerce to a plain float, or None."""
    try:
        if x is None:
            return None
        f = float(x)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _row(df: pd.DataFrame | None, *labels) -> list[dict] | None:
    """Extract a statement row as [{date, value}] oldest->newest, trying label variants."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    for label in labels:
        if label in df.index:
            s = df.loc[label]
            if isinstance(s, pd.DataFrame):  # duplicated label
                s = s.iloc[0]
            out = []
            for date, val in s.items():
                v = _num(val)
                if v is not None:
                    out.append({"date": str(pd.Timestamp(date).date()), "value": v})
            out.sort(key=lambda d: d["date"])
            return out or None
    return None


def latest(series, n_back=0):
    """Latest (or n-back) value of a [{date,value}] series."""
    if not series or len(series) <= n_back:
        return None
    return series[-(1 + n_back)]["value"]


def cagr(series, years):
    """CAGR over `years` using annual series; None if insufficient data."""
    if not series or len(series) < years + 1:
        return None
    end, start = series[-1]["value"], series[-(years + 1)]["value"]
    if start is None or end is None or start <= 0 or end <= 0:
        return None
    return (end / start) ** (1 / years) - 1


def yoy(series):
    if not series or len(series) < 2:
        return None
    prev, cur = series[-2]["value"], series[-1]["value"]
    if prev is None or cur is None or prev == 0:
        return None
    if prev < 0:
        # negative base: report sign-aware change (improvement positive)
        return (cur - prev) / abs(prev)
    return cur / prev - 1


def safe_div(a, b):
    a, b = _num(a), _num(b)
    if a is None or b is None or b == 0:
        return None
    return a / b


def _get(info: dict, *keys):
    for k in keys:
        v = _num(info.get(k))
        if v is not None:
            return v
    return None


def _df_records(df, cols=None, max_rows=20):
    """DataFrame -> list of dicts (JSON-safe), or None."""
    try:
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return None
        d = df if cols is None else df[[c for c in cols if c in df.columns]]
        d = d.head(max_rows).copy()
        for c in d.columns:
            if pd.api.types.is_datetime64_any_dtype(d[c]):
                d[c] = d[c].astype(str)
        d = d.replace({np.nan: None})
        recs = []
        for r in d.to_dict("records"):
            recs.append({str(k): (v.item() if hasattr(v, "item") else v) for k, v in r.items()})
        return recs
    except Exception:
        return None


_HIST_CACHE: dict[tuple, tuple[float, object]] = {}
_HIST_LOCK = threading.Lock()
_BENCHMARKS = {"SPY", "^VIX", "XLK", "XLF", "XLV", "XLE", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC"}


def fetch_price_history(ticker: str, period="2y"):
    # benchmarks (SPY, sector ETFs) are requested on every analysis — cache them
    cacheable = ticker.upper() in _BENCHMARKS
    key = (ticker.upper(), period)
    if cacheable:
        with _HIST_LOCK:
            hit = _HIST_CACHE.get(key)
            if hit and time.time() - hit[0] < CACHE_TTL:
                return hit[1]
    try:
        h = yf.Ticker(ticker).history(period=period, auto_adjust=True)
        if h is None or h.empty:
            return None
        if cacheable:
            with _HIST_LOCK:
                _HIST_CACHE[key] = (time.time(), h)
        return h
    except Exception:
        return None


SECTOR_ETF = {
    "Technology": "XLK", "Financial Services": "XLF", "Healthcare": "XLV",
    "Energy": "XLE", "Consumer Cyclical": "XLY", "Consumer Defensive": "XLP",
    "Industrials": "XLI", "Utilities": "XLU", "Real Estate": "XLRE",
    "Basic Materials": "XLB", "Communication Services": "XLC",
}


def compute_momentum(hist: pd.DataFrame | None, spy: pd.DataFrame | None,
                     sector_etf: pd.DataFrame | None = None, etf_symbol: str | None = None):
    """Momentum/technical block from a daily price history DataFrame."""
    if hist is None or hist.empty or "Close" not in hist:
        return {}
    close = hist["Close"].dropna()
    if close.empty:
        return {}
    price = float(close.iloc[-1])

    def perf(days):
        if len(close) <= days:
            return None
        return float(close.iloc[-1] / close.iloc[-1 - days] - 1)

    ma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
    ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None
    ret = close.pct_change().dropna()
    vol_ann = float(ret.tail(126).std() * math.sqrt(252)) if len(ret) >= 30 else None
    hi52 = float(close.tail(252).max()) if len(close) >= 20 else None
    lo52 = float(close.tail(252).min()) if len(close) >= 20 else None

    vol_trend = None
    if "Volume" in hist and hist["Volume"].dropna().shape[0] >= 60:
        v = hist["Volume"].dropna()
        recent, prior = v.tail(20).mean(), v.tail(60).head(40).mean()
        if prior and prior > 0:
            vol_trend = float(recent / prior - 1)

    def rel(days, benchmark=None):
        bench = spy if benchmark is None else benchmark
        if bench is None or bench.empty or "Close" not in bench:
            return None
        s = bench["Close"].dropna()
        p = perf(days)
        if p is None or len(s) <= days:
            return None
        return p - float(s.iloc[-1] / s.iloc[-1 - days] - 1)

    ma50_series = close.rolling(50).mean().dropna()
    ma200_series = close.rolling(200).mean().dropna()
    return {
        "price": price,
        "ma50": ma50,
        "ma200": ma200,
        "above_ma50": (price > ma50) if ma50 else None,
        "above_ma200": (price > ma200) if ma200 else None,
        "perf_1m": perf(21), "perf_3m": perf(63),
        "perf_6m": perf(126), "perf_12m": perf(252),
        "rel_spy_3m": rel(63), "rel_spy_12m": rel(252),
        "rel_sector_3m": rel(63, sector_etf), "rel_sector_12m": rel(252, sector_etf),
        "sector_etf": etf_symbol,
        "etf_above_ma200": _etf_above_ma200(sector_etf),
        "etf_perf_3m": _etf_perf(sector_etf, 63),
        "volatility_annualized": vol_ann,
        "volume_trend": vol_trend,
        "high_52w": hi52, "low_52w": lo52,
        "drawdown_from_high": (price / hi52 - 1) if hi52 else None,
        "above_low": (price / lo52 - 1) if lo52 else None,
        "price_series": [
            {"date": str(pd.Timestamp(d).date()), "close": float(c)}
            for d, c in close.tail(504).items()
        ],
        "ma50_series": [
            {"date": str(pd.Timestamp(d).date()), "value": float(c)}
            for d, c in ma50_series.tail(504).items()
        ],
        "ma200_series": [
            {"date": str(pd.Timestamp(d).date()), "value": float(c)}
            for d, c in ma200_series.tail(504).items()
        ],
    }


def _etf_above_ma200(etf_hist):
    if etf_hist is None or etf_hist.empty or "Close" not in etf_hist:
        return None
    close = etf_hist["Close"].dropna()
    if len(close) < 200:
        return None
    return bool(float(close.iloc[-1]) > float(close.rolling(200).mean().iloc[-1]))


def _etf_perf(etf_hist, days):
    if etf_hist is None or etf_hist.empty or "Close" not in etf_hist:
        return None
    close = etf_hist["Close"].dropna()
    if len(close) <= days:
        return None
    return float(close.iloc[-1] / close.iloc[-1 - days] - 1)


def _fetch_estimates(t: yf.Ticker):
    est = {}
    try:
        rev = t.revenue_estimate
        if rev is not None and not rev.empty:
            est["revenue_estimate"] = {str(i): {k: _num(v) for k, v in row.items()}
                                       for i, row in rev.iterrows()}
    except Exception:
        pass
    try:
        eps = t.earnings_estimate
        if eps is not None and not eps.empty:
            est["earnings_estimate"] = {str(i): {k: _num(v) for k, v in row.items()}
                                        for i, row in eps.iterrows()}
    except Exception:
        pass
    try:
        g = t.growth_estimates
        if g is not None and not g.empty:
            col = "stockTrend" if "stockTrend" in g.columns else g.columns[0]
            est["growth_estimates"] = {str(i): _num(v) for i, v in g[col].items()}
    except Exception:
        pass
    try:
        pt = t.analyst_price_targets
        if isinstance(pt, dict):
            est["price_targets"] = {k: _num(v) for k, v in pt.items()}
    except Exception:
        pass
    try:
        tr = t.eps_trend
        if tr is not None and not tr.empty:
            revs = {}
            for period in ("0y", "+1y"):
                if period in tr.index:
                    row = tr.loc[period]
                    cur, ago = _num(row.get("current")), _num(row.get("90daysAgo") or row.get("60daysAgo"))
                    if cur is not None and ago not in (None, 0):
                        revs[period] = cur / ago - 1
            if revs:
                est["eps_revisions_90d"] = revs
    except Exception:
        pass
    try:
        eh = t.earnings_history
        if eh is not None and not eh.empty:
            beats = eh.dropna(subset=["epsActual", "epsEstimate"])
            if not beats.empty:
                est["eps_beat_rate"] = float((beats["epsActual"] >= beats["epsEstimate"]).mean())
                est["recent_surprises"] = [
                    {"quarter": str(pd.Timestamp(i).date()) if not isinstance(i, str) else i,
                     "actual": _num(r.get("epsActual")), "estimate": _num(r.get("epsEstimate")),
                     "surprise_pct": _num(r.get("surprisePercent"))}
                    for i, r in beats.tail(4).iterrows()]
    except Exception:
        pass
    try:
        ud = t.upgrades_downgrades
        if ud is not None and not ud.empty:
            recent = ud.head(10).reset_index()
            est["recent_rating_changes"] = _df_records(recent, max_rows=10)
    except Exception:
        pass
    return est


def _fetch_holders(t: yf.Ticker, info: dict):
    h = {
        "insider_pct": _get(info, "heldPercentInsiders"),
        "institution_pct": _get(info, "heldPercentInstitutions"),
        "insider_buys": None, "insider_sells": None, "insider_net_shares": None,
    }
    try:
        it = t.insider_transactions
        if it is not None and not it.empty:
            cutoff = pd.Timestamp.now() - pd.Timedelta(days=365)
            if "Start Date" in it.columns:
                it = it[pd.to_datetime(it["Start Date"], errors="coerce") >= cutoff]
            txt = it.get("Text", pd.Series(dtype=str)).astype(str).str.lower()
            buys = txt.str.contains("purchase|buy", regex=True)
            sells = txt.str.contains("sale|sell", regex=True)
            h["insider_buys"] = int(buys.sum())
            h["insider_sells"] = int(sells.sum())
            if "Shares" in it.columns:
                sh = pd.to_numeric(it["Shares"], errors="coerce").fillna(0)
                h["insider_net_shares"] = float(sh[buys].sum() - sh[sells].sum())
    except Exception:
        pass
    return h


def fetch_snapshot(ticker: str, use_cache=True) -> dict:
    """Fetch and normalize all data for one ticker. Raises ValueError if unknown."""
    ticker = ticker.strip().upper()
    if use_cache:
        with _CACHE_LOCK:
            hit = _CACHE.get(ticker)
            if hit and time.time() - hit[0] < CACHE_TTL:
                return hit[1]

    t = yf.Ticker(ticker)
    info = {}
    for attempt in range(3):  # Yahoo intermittently returns empty info under rate limiting
        try:
            info = t.info or {}
        except Exception:
            info = {}
        if info.get("regularMarketPrice") is not None or info.get("currentPrice") is not None \
                or info.get("previousClose") is not None:
            break
        time.sleep(1.5 * (attempt + 1))
        t = yf.Ticker(ticker)  # fresh session for the retry
    else:
        raise ValueError(f"No data found for ticker '{ticker}'. Check the symbol "
                         "(or Yahoo may be rate-limiting — try again in a minute).")

    with ThreadPoolExecutor(max_workers=6) as ex:
        f_inc = ex.submit(lambda: t.income_stmt)
        f_bal = ex.submit(lambda: t.balance_sheet)
        f_cf = ex.submit(lambda: t.cashflow)
        f_qinc = ex.submit(lambda: t.quarterly_income_stmt)
        f_qcf = ex.submit(lambda: t.quarterly_cashflow)
        f_qbal = ex.submit(lambda: t.quarterly_balance_sheet)
        f_hist = ex.submit(fetch_price_history, ticker, "5y")
        f_spy = ex.submit(fetch_price_history, "SPY", "5y")
        etf_symbol = SECTOR_ETF.get(info.get("sector") or "")
        f_etf = ex.submit(fetch_price_history, etf_symbol, "5y") if etf_symbol else None
        f_est = ex.submit(_fetch_estimates, t)
        inc = _safe_result(f_inc); bal = _safe_result(f_bal); cf = _safe_result(f_cf)
        qinc = _safe_result(f_qinc); qcf = _safe_result(f_qcf); qbal = _safe_result(f_qbal)
        hist = _safe_result(f_hist); spy = _safe_result(f_spy)
        etf = _safe_result(f_etf) if f_etf else None
        estimates = _safe_result(f_est) or {}

    holders = _fetch_holders(t, info)

    calendar = {}
    try:
        cal = t.calendar
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if ed:
                calendar["next_earnings_date"] = str(ed[0]) if isinstance(ed, (list, tuple)) else str(ed)
            for k in ("Ex-Dividend Date", "Dividend Date"):
                if cal.get(k):
                    calendar[k.lower().replace(" ", "_").replace("-", "_")] = str(cal[k])
    except Exception:
        pass

    news = []
    try:
        for item in (t.news or [])[:15]:
            c = item.get("content", item)
            title = c.get("title")
            if not title:
                continue
            url = None
            for key in ("canonicalUrl", "clickThroughUrl"):
                u = c.get(key)
                if isinstance(u, dict) and u.get("url"):
                    url = u["url"]
                    break
            news.append({"title": title,
                         "summary": (c.get("summary") or "")[:400],
                         "url": url,
                         "date": str(c.get("pubDate", ""))[:10],
                         "publisher": (c.get("provider") or {}).get("displayName")
                         if isinstance(c.get("provider"), dict) else c.get("publisher")})
    except Exception:
        pass

    series = _build_series(inc, bal, cf)
    qseries = _build_series(qinc, qbal, qcf, prefix="q_")

    # optional FMP enrichment: longer history + earnings-call transcripts
    from . import fmp
    data_source = "Yahoo Finance (via yfinance)"
    transcript = None
    if fmp.enabled():
        try:
            if fmp.extend_annual_series(ticker, series):
                data_source = "Yahoo Finance + Financial Modeling Prep (extended history)"
        except Exception:
            pass
        try:
            transcript = fmp.transcript_analysis(ticker)
        except Exception:
            transcript = None

    momentum = compute_momentum(hist, spy, etf, etf_symbol)
    price = momentum.get("price") or _get(info, "currentPrice", "regularMarketPrice", "previousClose")
    metrics = _build_metrics(info, series, qseries, price)
    metrics["valuation_history"] = _valuation_history(hist, series, metrics)
    dq = _data_quality(info, series, metrics, estimates, momentum,
                       has_transcript=transcript is not None,
                       fmp_active=fmp.enabled())

    snap = {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName") or ticker,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "industry_key": info.get("industryKey"),
        "currency": info.get("currency", "USD"),
        "summary": (info.get("longBusinessSummary") or "")[:1200],
        "price": price,
        "data_source": data_source,
        "transcript_analysis": transcript,
        "last_statement_date": series["revenue"][-1]["date"] if series.get("revenue") else None,
        "fetched_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        "series": series,
        "qseries": qseries,
        "metrics": metrics,
        "momentum": momentum,
        "estimates": estimates,
        "holders": holders,
        "calendar": calendar,
        "news": news,
        "data_quality": dq,
        "info_subset": {k: info.get(k) for k in (
            "marketCap", "enterpriseValue", "trailingPE", "forwardPE", "pegRatio",
            "priceToSalesTrailing12Months", "enterpriseToRevenue", "enterpriseToEbitda",
            "priceToBook", "dividendYield", "payoutRatio", "beta", "trailingEps",
            "forwardEps", "sharesOutstanding", "totalCash", "totalDebt", "debtToEquity",
            "currentRatio", "quickRatio", "returnOnAssets", "returnOnEquity",
            "freeCashflow", "operatingCashflow", "revenueGrowth", "earningsGrowth",
            "grossMargins", "operatingMargins", "ebitdaMargins", "profitMargins",
            "targetMeanPrice", "targetHighPrice", "targetLowPrice",
            "recommendationKey", "recommendationMean", "numberOfAnalystOpinions",
            "fullTimeEmployees", "auditRisk", "boardRisk", "overallRisk",
        )},
    }
    with _CACHE_LOCK:
        _CACHE[ticker] = (time.time(), snap)
    return snap


def _safe_result(future):
    try:
        return future.result()
    except Exception:
        return None


def _build_series(inc, bal, cf, prefix=""):
    s = {
        "revenue": _row(inc, "Total Revenue", "Operating Revenue"),
        "gross_profit": _row(inc, "Gross Profit"),
        "operating_income": _row(inc, "Operating Income", "Total Operating Income As Reported"),
        "ebitda": _row(inc, "EBITDA", "Normalized EBITDA"),
        "ebit": _row(inc, "EBIT"),
        "net_income": _row(inc, "Net Income", "Net Income Common Stockholders"),
        "eps": _row(inc, "Basic EPS"),
        "diluted_eps": _row(inc, "Diluted EPS"),
        "rnd": _row(inc, "Research And Development"),
        "sgna": _row(inc, "Selling General And Administration",
                     "Selling General And Administrative Expense"),
        "interest_expense": _row(inc, "Interest Expense",
                                 "Interest Expense Non Operating"),
        "tax_expense": _row(inc, "Tax Provision"),
        "net_interest_income": _row(inc, "Net Interest Income"),
        "interest_income": _row(inc, "Interest Income"),
        "dna": _row(cf, "Depreciation And Amortization",
                    "Depreciation Amortization Depletion"),
        "cash": _row(bal, "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"),
        "short_term_investments": _row(bal, "Other Short Term Investments"),
        "total_assets": _row(bal, "Total Assets"),
        "total_liabilities": _row(bal, "Total Liabilities Net Minority Interest"),
        "total_debt": _row(bal, "Total Debt"),
        "short_term_debt": _row(bal, "Current Debt", "Current Debt And Capital Lease Obligation"),
        "long_term_debt": _row(bal, "Long Term Debt", "Long Term Debt And Capital Lease Obligation"),
        "net_debt": _row(bal, "Net Debt"),
        "current_assets": _row(bal, "Current Assets"),
        "current_liabilities": _row(bal, "Current Liabilities"),
        "equity": _row(bal, "Stockholders Equity", "Common Stock Equity"),
        "retained_earnings": _row(bal, "Retained Earnings"),
        "retained_earnings": _row(bal, "Retained Earnings"),
        "tangible_book": _row(bal, "Tangible Book Value"),
        "shares": _row(bal, "Ordinary Shares Number", "Share Issued"),
        "invested_capital": _row(bal, "Invested Capital"),
        "receivables": _row(bal, "Accounts Receivable", "Receivables"),
        "inventory": _row(bal, "Inventory"),
        "ocf": _row(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities"),
        "capex": _row(cf, "Capital Expenditure"),
        "fcf": _row(cf, "Free Cash Flow"),
        "sbc": _row(cf, "Stock Based Compensation"),
        "buybacks": _row(cf, "Repurchase Of Capital Stock"),
        "dividends_paid": _row(cf, "Cash Dividends Paid", "Common Stock Dividend Paid"),
        "debt_issued": _row(cf, "Issuance Of Debt", "Long Term Debt Issuance"),
        "debt_repaid": _row(cf, "Repayment Of Debt", "Long Term Debt Payments"),
        "acquisitions": _row(cf, "Purchase Of Business", "Net Business Purchase And Sale"),
    }
    # derive FCF if missing
    if not s["fcf"] and s["ocf"] and s["capex"]:
        capex_by_date = {d["date"]: d["value"] for d in s["capex"]}
        fcf = [{"date": d["date"], "value": d["value"] + capex_by_date[d["date"]]}
               for d in s["ocf"] if d["date"] in capex_by_date]  # capex negative in yf
        s["fcf"] = fcf or None
    return {prefix + k: v for k, v in s.items()} if prefix else s


def _ttm(qseries, key, n=4):
    q = qseries.get("q_" + key)
    if not q or len(q) < n:
        return None
    return sum(d["value"] for d in q[-n:])


def _ttm_growth(qseries, key):
    """Trailing-12-month value vs the prior-year TTM (needs 8 quarters)."""
    q = qseries.get("q_" + key)
    if not q or len(q) < 8:
        return None
    cur = sum(d["value"] for d in q[-4:])
    prev = sum(d["value"] for d in q[-8:-4])
    if prev <= 0:
        return None
    return cur / prev - 1


def _build_metrics(info, s, qs, price):
    rev, ni, fcf = s.get("revenue"), s.get("net_income"), s.get("fcf")
    ttm_rev = _ttm(qs, "revenue") or latest(rev)
    ttm_ni = _ttm(qs, "net_income") or latest(ni)
    ttm_ocf = _ttm(qs, "ocf") or latest(s.get("ocf"))
    ttm_fcf = _ttm(qs, "fcf") or latest(fcf)
    ttm_ebitda = _ttm(qs, "ebitda") or latest(s.get("ebitda"))

    mcap = _get(info, "marketCap")
    ev = _get(info, "enterpriseValue")
    shares = _get(info, "sharesOutstanding") or latest(s.get("shares"))
    cash_now = _get(info, "totalCash") or latest(s.get("cash"))
    debt_now = _get(info, "totalDebt") or latest(s.get("total_debt"))
    equity_now = latest(s.get("equity"))

    m = {
        "ttm_revenue": ttm_rev, "ttm_net_income": ttm_ni, "ttm_ocf": ttm_ocf,
        "ttm_fcf": ttm_fcf, "ttm_ebitda": ttm_ebitda,
        "market_cap": mcap, "enterprise_value": ev, "shares_outstanding": shares,
        "cash": cash_now, "total_debt": debt_now,
        "net_debt": (debt_now - cash_now) if (debt_now is not None and cash_now is not None) else None,
        "equity": equity_now,
        # margins — derived from statements first (TTM, then annual) so the
        # snapshot always agrees with the margin charts; Yahoo's info fields
        # use different cost buckets for some sectors (e.g. energy) and are
        # kept only as a last resort
        "gross_margin": safe_div(_ttm(qs, "gross_profit"), ttm_rev)
                        or safe_div(latest(s.get("gross_profit")), latest(rev))
                        or _get(info, "grossMargins"),
        "operating_margin": safe_div(_ttm(qs, "operating_income"), ttm_rev)
                            or safe_div(latest(s.get("operating_income")), latest(rev))
                            or _get(info, "operatingMargins"),
        "ebitda_margin": safe_div(ttm_ebitda, ttm_rev) or _get(info, "ebitdaMargins"),
        "net_margin": safe_div(ttm_ni, ttm_rev) or _get(info, "profitMargins"),
        "fcf_margin": safe_div(ttm_fcf, ttm_rev),
        # growth — prefer values computed from annual statements: Yahoo's
        # info["revenueGrowth"]/["earningsGrowth"] are *latest-quarter YoY*,
        # which mislabels as 1-year growth (kept only as last-resort fallback)
        "rev_growth_1y": _ttm_growth(qs, "revenue") or yoy(rev) or _get(info, "revenueGrowth"),
        "rev_growth_quarterly_yoy": _get(info, "revenueGrowth"),
        "rev_cagr_3y": cagr(rev, 3), "rev_cagr_5y": cagr(rev, 5) or cagr(rev, 4),
        "eps_growth": yoy(s.get("diluted_eps") or s.get("eps")) or _get(info, "earningsGrowth"),
        "ni_growth": yoy(ni), "ebitda_growth": yoy(s.get("ebitda")),
        "opinc_growth": yoy(s.get("operating_income")), "fcf_growth": yoy(fcf),
        "rev_growth_prior": (yoy(rev[:-1]) if rev and len(rev) >= 3 else None),
        # returns
        "roe": _get(info, "returnOnEquity") or safe_div(ttm_ni, equity_now),
        "roa": _get(info, "returnOnAssets") or safe_div(ttm_ni, latest(s.get("total_assets"))),
        "roic": safe_div(latest(s.get("ebit")), latest(s.get("invested_capital"))),
        # balance sheet
        "current_ratio": _get(info, "currentRatio") or safe_div(latest(s.get("current_assets")), latest(s.get("current_liabilities"))),
        "quick_ratio": _get(info, "quickRatio"),
        "debt_to_equity": safe_div(debt_now, equity_now),
        "net_debt_to_ebitda": None, "interest_coverage": None,
        # valuation
        "pe": _get(info, "trailingPE"), "forward_pe": _get(info, "forwardPE"),
        "ps": _get(info, "priceToSalesTrailing12Months") or safe_div(mcap, ttm_rev),
        "ev_revenue": _get(info, "enterpriseToRevenue") or safe_div(ev, ttm_rev),
        "ev_ebitda": _get(info, "enterpriseToEbitda") or safe_div(ev, ttm_ebitda),
        "p_fcf": safe_div(mcap, ttm_fcf),
        "fcf_yield": safe_div(ttm_fcf, mcap),
        "peg": _get(info, "pegRatio"),
        "pb": _get(info, "priceToBook") or safe_div(mcap, equity_now),
        "dividend_yield": _norm_div_yield(_get(info, "dividendYield")),
        "payout_ratio": _get(info, "payoutRatio"),
        "beta": _get(info, "beta"),
        # shareholder
        "sbc_pct_revenue": safe_div(latest(s.get("sbc")), latest(rev)),
        "sbc_pct_fcf": safe_div(latest(s.get("sbc")), ttm_fcf) if ttm_fcf and ttm_fcf > 0 else None,
        "dilution_1y": yoy(s.get("shares")),
        "dilution_3y": cagr(s.get("shares"), 3) or cagr(s.get("shares"), 2),
        "buybacks_ttm": latest(s.get("buybacks")),
        "dividends_ttm": latest(s.get("dividends_paid")),
        # accounting inputs
        "receivables_growth": yoy(s.get("receivables")),
        "inventory_growth": yoy(s.get("inventory")),
        "ocf_to_ni": safe_div(ttm_ocf, ttm_ni) if ttm_ni and ttm_ni > 0 else None,
        "fcf_to_ni": safe_div(ttm_fcf, ttm_ni) if ttm_ni and ttm_ni > 0 else None,
    }
    nd, ie, ebit = m["net_debt"], latest(s.get("interest_expense")), latest(s.get("ebit"))
    if nd is not None and ttm_ebitda and ttm_ebitda > 0:
        m["net_debt_to_ebitda"] = nd / ttm_ebitda
    if ie and ie > 0 and ebit is not None:
        m["interest_coverage"] = ebit / ie
    # cash runway for burners
    if ttm_fcf is not None and ttm_fcf < 0 and cash_now:
        m["cash_runway_years"] = cash_now / abs(ttm_fcf)
    else:
        m["cash_runway_years"] = None
    # PEG fallback
    if m["peg"] is None and m["pe"] and m["eps_growth"] and m["eps_growth"] > 0.02:
        m["peg"] = m["pe"] / (m["eps_growth"] * 100)
    return m


def _valuation_history(hist, series, metrics):
    """Fiscal-year-end P/E and P/S from annual statements + the price on that
    date, plus the current multiple's percentile within that history. Coarse
    with Yahoo's ~4-5 years; deeper with the FMP extension."""
    if hist is None or hist.empty or "Close" not in hist:
        return None
    close = hist["Close"].dropna()
    try:
        close.index = close.index.tz_localize(None)
    except TypeError:
        pass
    eps_s = series.get("diluted_eps") or series.get("eps") or []
    rev_s, sh_s = series.get("revenue") or [], series.get("shares") or []
    eps_by = {x["date"]: x["value"] for x in eps_s}
    sh_by = {x["date"]: x["value"] for x in sh_s}
    points = []
    for d in rev_s:
        px = close[close.index <= pd.Timestamp(d["date"])]
        if px.empty:
            continue
        p = float(px.iloc[-1])
        entry = {"date": d["date"], "price": round(p, 2)}
        eps = eps_by.get(d["date"])
        if eps and eps > 0:
            entry["pe"] = round(p / eps, 1)
        sh = sh_by.get(d["date"])
        if sh and d["value"] > 0:
            entry["ps"] = round(p * sh / d["value"], 2)
        if len(entry) > 2:
            points.append(entry)
    if not points:
        return None
    out = {"points": points, "years": len(points)}
    for key, cur in (("pe", metrics.get("pe")), ("ps", metrics.get("ps"))):
        vals = [pt[key] for pt in points if pt.get(key)]
        if cur and len(vals) >= 2:
            out[key + "_percentile"] = round(sum(1 for v in vals if v <= cur) / (len(vals) + 1), 2)
            out[key + "_range"] = [min(vals), max(vals)]
            out[key + "_current"] = round(cur, 1)
    return out


def _norm_div_yield(v):
    """yfinance sometimes returns 0.44 (=0.44%) and sometimes 0.0044."""
    if v is None:
        return None
    return v / 100 if v > 0.25 else v


def _data_quality(info, series, metrics, estimates, momentum, has_transcript=False,
                  fmp_active=False):
    """0-100 completeness/reliability score with per-check detail."""
    checks = []

    def check(name, ok, weight):
        checks.append({"check": name, "ok": bool(ok), "weight": weight})

    core = ["revenue", "net_income", "total_assets", "equity", "ocf"]
    have_core = sum(1 for k in core if series.get(k))
    check("Core financial statements present", have_core >= 4, 25)
    years = len(series.get("revenue") or [])
    check("3+ years of history", years >= 3, 15)
    check("5+ years of history", years >= 5, 5)
    key_metrics = ["gross_margin", "net_margin", "pe", "ps", "market_cap",
                   "current_ratio", "fcf_yield", "roe"]
    have = sum(1 for k in key_metrics if metrics.get(k) is not None)
    check("Key ratios computable (>=6 of 8)", have >= 6, 15)
    check("Price/momentum data available", bool(momentum.get("price")), 10)
    check("200-day trend available", momentum.get("ma200") is not None, 5)
    check("Forward analyst estimates available",
          bool(estimates.get("earnings_estimate") or estimates.get("revenue_estimate")), 10)
    check("Analyst price targets available", bool(estimates.get("price_targets")), 5)
    check("Sector/industry classification", bool(info.get("sector")), 5)
    check("Earnings transcript data", has_transcript, 5)

    score = sum(c["weight"] for c in checks if c["ok"])
    missing = [c["check"] for c in checks if not c["ok"]]
    if has_transcript:
        note = "Earnings-call transcripts provided by Financial Modeling Prep."
    elif fmp_active:
        note = ("FMP key active (extended statement history in use), but earnings-call "
                "transcripts require a paid FMP tier — commentary analysis is skipped.")
    else:
        note = ("Earnings-call transcripts are not available from Yahoo Finance; add an "
                "FMP_API_KEY (financialmodelingprep.com) to extend statement history.")
    return {"score": score, "checks": checks, "missing": missing, "note": note}
