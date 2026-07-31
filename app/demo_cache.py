"""Offline demo fallback.

`python -m app.demo_cache MSFT JPM RIVN` saves complete reports to
demo_cache/*.json. If a live analysis later fails (no internet, Yahoo rate
limit), the API serves the cached snapshot instead — clearly labeled with its
capture date — so a live demo can never dead-end on a network error.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / "demo_cache"


def save(ticker: str) -> str:
    from .engine import analyze
    CACHE_DIR.mkdir(exist_ok=True)
    report = analyze(ticker)
    path = CACHE_DIR / f"{report['ticker']}.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return str(path)


def load(ticker: str) -> dict | None:
    path = CACHE_DIR / f"{ticker.strip().upper()}.json"
    if not path.exists():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    report["offline_snapshot"] = True
    report["offline_note"] = (
        f"Live data was unavailable — showing a cached snapshot generated "
        f"{report.get('generated_at', 'earlier')} (model {report.get('model_version', '?')}). "
        "Prices and ratings are not current.")
    return report


def main(tickers):
    if not tickers:
        print("Usage: python -m app.demo_cache TICKER [TICKER ...]")
        return 1
    for tk in tickers:
        try:
            print(f"{tk}: saved -> {save(tk)}")
        except Exception as e:
            print(f"{tk}: FAILED ({e})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
