"""Live macro readings from FRED (Federal Reserve Economic Data).

Activates when FRED_API_KEY is present (free key: fred.stlouisfed.org →
My Account → API Keys). Turns the static sector→macro-risk mapping into
current readings with 3-month direction. Fails soft; cached 6 hours.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

_SERIES = [
    ("DFF", "Fed funds rate", "pct", "Interest rates"),
    ("DGS10", "10-year Treasury yield", "pct", "Interest rates"),
    ("CPIAUCSL", "CPI (index)", "yoy", "Inflation"),
    ("BAMLH0A0HYM2", "High-yield credit spread", "pct", "Credit markets"),
    ("UNRATE", "Unemployment rate", "pct", "Consumer spending"),
    ("HOUST", "Housing starts (thous.)", "level", "Housing market"),
]

_CACHE: dict = {}
_LOCK = threading.Lock()
TTL = 6 * 3600


def api_key():
    key = os.environ.get("FRED_API_KEY")
    if not key:
        env = Path(__file__).resolve().parent.parent / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.strip().startswith("FRED_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    return key or None


def enabled() -> bool:
    return bool(api_key())


def _observations(series_id: str, limit=400):
    params = urllib.parse.urlencode({
        "series_id": series_id, "api_key": api_key(), "file_type": "json",
        "sort_order": "desc", "limit": limit})
    url = f"https://api.stlouisfed.org/fred/series/observations?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "equity-decision-engine"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        rows = json.loads(resp.read().decode()).get("observations", [])
    vals = [(r["date"], float(r["value"])) for r in rows if r.get("value") not in (".", None)]
    return vals  # newest first


def current_readings() -> dict | None:
    """{rows: [{indicator, value, change_3m, direction, maps_to}], as_of} or None."""
    if not enabled():
        return None
    with _LOCK:
        hit = _CACHE.get("readings")
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
    rows = []
    for series_id, label, kind, maps_to in _SERIES:
        try:
            obs = _observations(series_id)
            if not obs:
                continue
            latest_date, latest = obs[0]
            if kind == "yoy":
                # CPI index -> year-over-year inflation rate
                year_ago = next((v for d, v in obs if d <= _shift_year(latest_date)), None)
                if not year_ago:
                    continue
                value = (latest / year_ago - 1) * 100
                prior = None
                obs3 = next((v for d, v in obs if d <= _shift_months(latest_date, 3)), None)
                obs15 = next((v for d, v in obs if d <= _shift_months(latest_date, 15)), None)
                if obs3 and obs15:
                    prior = (obs3 / obs15 - 1) * 100
            else:
                value = latest
                prior = next((v for d, v in obs if d <= _shift_months(latest_date, 3)), None)
            change = (value - prior) if prior is not None else None
            direction = ("rising" if change > 0.05 else "falling" if change < -0.05
                         else "flat") if change is not None else "n/a"
            rows.append({"indicator": label, "series": series_id,
                         "value": round(value, 2), "unit": "%" if kind != "level" else "",
                         "change_3m": round(change, 2) if change is not None else None,
                         "direction": direction, "maps_to": maps_to,
                         "as_of": latest_date})
        except Exception:
            continue
    if not rows:
        return None
    out = {"rows": rows,
           "source": "FRED (Federal Reserve Economic Data)",
           "note": "Live macro readings with 3-month direction; matched to the "
                   "macro-sensitivity factors above."}
    with _LOCK:
        _CACHE["readings"] = (time.time(), out)
    return out


def _shift_months(date_str: str, months: int) -> str:
    y, m, d = int(date_str[:4]), int(date_str[5:7]), date_str[8:10]
    m -= months
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}-{d}"


def _shift_year(date_str: str) -> str:
    return f"{int(date_str[:4]) - 1}{date_str[4:]}"
