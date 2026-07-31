"""FastAPI app: JSON API + static dashboard."""
from __future__ import annotations

import csv
import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import MODEL_VERSION
from . import db, demo_cache
from .engine import analyze
from .backtest import run_backtest

app = FastAPI(title="Equity Decision Engine", version=MODEL_VERSION)
db.init()

STATIC = Path(__file__).resolve().parent.parent / "static"


@app.get("/api/config")
def api_config():
    from . import fmp
    return {"model_version": MODEL_VERSION, "fmp_enabled": fmp.enabled()}


@app.get("/api/search")
def api_search(q: str):
    """Ticker/company-name lookup for the search box."""
    q = q.strip()
    if len(q) < 2:
        return {"results": []}
    try:
        import yfinance as yf
        s = yf.Search(q, max_results=10)
        out = []
        for r in s.quotes:
            if r.get("quoteType") not in ("EQUITY", "ETF"):
                continue
            out.append({"symbol": r.get("symbol"),
                        "name": r.get("longname") or r.get("shortname") or "",
                        "exchange": r.get("exchDisp") or "",
                        "type": r.get("quoteType")})
            if len(out) >= 6:
                break
        return {"results": out}
    except Exception:
        return {"results": []}


@app.get("/api/analyze/{ticker}")
def api_analyze(ticker: str):
    try:
        report = analyze(ticker)
    except ValueError as e:
        # unknown ticker — but if we have a demo snapshot, Yahoo may just be
        # rate-limiting; prefer stale-but-labeled data over a dead end
        cached = demo_cache.load(ticker)
        if cached:
            return cached
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        cached = demo_cache.load(ticker)
        if cached:
            return cached
        raise HTTPException(status_code=502, detail=f"Data fetch/analysis failed: {e}")
    db.record_rating(report)
    return report


@app.get("/api/backtest/{ticker}")
def api_backtest(ticker: str):
    try:
        return run_backtest(ticker)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Backtest failed: {e}")


@app.get("/api/history/{ticker}")
def api_history(ticker: str):
    return {"ticker": ticker.upper(), "history": db.history(ticker.upper())}


@app.get("/api/compare")
def api_compare(tickers: str):
    syms = [s.strip().upper() for s in tickers.split(",") if s.strip()][:5]
    if len(syms) < 2:
        raise HTTPException(status_code=400, detail="Provide 2-5 comma-separated tickers.")
    out, errors = [], {}

    def one(s):
        try:
            return s, analyze(s)
        except Exception as e:
            return s, e

    # 2 workers: each analyze fans out its own requests; more parallelism here
    # just trips Yahoo's rate limiting and produces spurious ticker failures
    with ThreadPoolExecutor(max_workers=2) as ex:
        for s, res in ex.map(one, syms):
            if isinstance(res, Exception):
                errors[s] = str(res)
            else:
                db.record_rating(res)
                out.append({k: res.get(k) for k in (
                    "ticker", "name", "final_rating", "total_score", "confidence",
                    "fundamental_rating", "timing_rating", "risk_reward_grade",
                    "company_type", "price", "position_suitability")}
                    | {"expected_upside": (res.get("valuation") or {}).get("expected_upside"),
                       "metrics": {k2: res["metrics"].get(k2) for k2 in (
                           "rev_growth_1y", "fcf_yield", "pe", "forward_pe", "ps",
                           "ev_ebitda", "net_debt_to_ebitda", "gross_margin",
                           "operating_margin", "roe", "dividend_yield")},
                       "momentum_12m": res["momentum"].get("perf_12m")})
    return {"results": out, "errors": errors}


class NoteBody(BaseModel):
    note: str = ""


@app.get("/api/watchlist")
def api_watchlist():
    return {"watchlist": db.watchlist_all()}


@app.post("/api/watchlist/{ticker}")
def api_watchlist_add(ticker: str):
    db.watchlist_add(ticker)
    return {"ok": True}


@app.delete("/api/watchlist/{ticker}")
def api_watchlist_remove(ticker: str):
    db.watchlist_remove(ticker)
    return {"ok": True}


@app.put("/api/watchlist/{ticker}/note")
def api_watchlist_note(ticker: str, body: NoteBody):
    db.watchlist_note(ticker, body.note)
    return {"ok": True}


@app.get("/api/export/{ticker}.csv")
def api_export_csv(ticker: str):
    try:
        r = analyze(ticker)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Equity Decision Engine export", r["ticker"], r["generated_at"],
                f"model {r['model_version']}"])
    w.writerow([])
    w.writerow(["Final rating", r["final_rating"]])
    w.writerow(["Total score", r["total_score"]])
    w.writerow(["Confidence", r["confidence"]])
    w.writerow(["Fundamental rating", r["fundamental_rating"]])
    w.writerow(["Timing rating", r["timing_rating"]])
    w.writerow(["Risk/reward", r["risk_reward_grade"]])
    w.writerow(["Company type", r["company_type"]])
    w.writerow([])
    w.writerow(["Factor", "Score", "Weight %", "Contribution"])
    for f in r["factors"].values():
        w.writerow([f["label"], f["score"], f["weight"], f["contribution"]])
    w.writerow([])
    w.writerow(["Metric", "Value"])
    for row in r["financial_snapshot"]:
        w.writerow([row["label"], row["value"]])
    w.writerow([])
    w.writerow(["Red flag", "Severity", "Explanation"])
    for fl in r["red_flags"]:
        w.writerow([fl["flag"], fl["severity"], fl["explanation"]])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition":
                                      f"attachment; filename={r['ticker']}_analysis.csv"})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
