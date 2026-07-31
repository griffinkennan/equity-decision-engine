"""SQLite persistence: watchlist, notes, and rating history."""
from __future__ import annotations

import json
import sqlite3
import datetime as dt
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "analyzer.db"


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS watchlist (
            ticker TEXT PRIMARY KEY,
            added_at TEXT NOT NULL,
            notes TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS rating_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            model_version TEXT NOT NULL,
            rating TEXT, score REAL, confidence TEXT,
            price REAL, summary_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_hist_ticker ON rating_history(ticker, generated_at);
        """)


def record_rating(report: dict):
    keep = {k: report.get(k) for k in (
        "final_rating", "total_score", "confidence", "fundamental_rating",
        "timing_rating", "risk_reward_grade", "company_type", "price",
        "model_version")}
    if report.get("valuation"):
        keep["expected_upside"] = report["valuation"]["expected_upside"]
    m = report.get("metrics") or {}
    keep["screener"] = {
        "rev_growth": m.get("rev_growth_1y"), "fcf_yield": m.get("fcf_yield"),
        "forward_pe": m.get("forward_pe"), "pe": m.get("pe"),
        "net_debt_to_ebitda": m.get("net_debt_to_ebitda"),
        "dividend_yield": m.get("dividend_yield"),
        "momentum_12m": (report.get("momentum") or {}).get("perf_12m"),
    }
    with _conn() as c:
        # avoid duplicate rows within the same hour
        row = c.execute(
            "SELECT generated_at FROM rating_history WHERE ticker=? "
            "ORDER BY generated_at DESC LIMIT 1", (report["ticker"],)).fetchone()
        if row and row["generated_at"][:13] == report["generated_at"][:13]:
            return
        c.execute(
            "INSERT INTO rating_history (ticker, generated_at, model_version, rating, "
            "score, confidence, price, summary_json) VALUES (?,?,?,?,?,?,?,?)",
            (report["ticker"], report["generated_at"], report["model_version"],
             report["final_rating"], report["total_score"], report["confidence"],
             report.get("price"), json.dumps(keep)))


def history(ticker: str):
    with _conn() as c:
        rows = c.execute(
            "SELECT generated_at, model_version, rating, score, confidence, price "
            "FROM rating_history WHERE ticker=? ORDER BY generated_at", (ticker,)).fetchall()
        return [dict(r) for r in rows]


def watchlist_add(ticker: str):
    with _conn() as c:
        c.execute("INSERT OR IGNORE INTO watchlist (ticker, added_at) VALUES (?,?)",
                  (ticker.upper(), dt.datetime.now().isoformat(timespec="seconds")))


def watchlist_remove(ticker: str):
    with _conn() as c:
        c.execute("DELETE FROM watchlist WHERE ticker=?", (ticker.upper(),))


def watchlist_note(ticker: str, note: str):
    with _conn() as c:
        c.execute("UPDATE watchlist SET notes=? WHERE ticker=?", (note, ticker.upper()))


def watchlist_all():
    with _conn() as c:
        rows = c.execute("SELECT * FROM watchlist ORDER BY added_at").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            hs = c.execute(
                "SELECT rating, score, confidence, price, generated_at, summary_json "
                "FROM rating_history WHERE ticker=? ORDER BY generated_at DESC LIMIT 2",
                (r["ticker"],)).fetchall()
            if hs:
                d["last"] = dict(hs[0])
                try:
                    d["last"]["summary"] = json.loads(hs[0]["summary_json"] or "{}")
                except json.JSONDecodeError:
                    d["last"]["summary"] = {}
                del d["last"]["summary_json"]
                if len(hs) > 1:
                    d["prev"] = {"rating": hs[1]["rating"], "score": hs[1]["score"],
                                 "generated_at": hs[1]["generated_at"]}
            out.append(d)
        return out
