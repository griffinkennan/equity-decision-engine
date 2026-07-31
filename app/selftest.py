"""Accuracy self-test: recompute every key reported metric independently from
raw statement data and flag disagreements.

Run:  python -m app.selftest AAPL MSFT JPM ...

Each check recomputes a value from primitive inputs (raw statement rows, price,
share count) and compares it with what the analysis reports, within a stated
tolerance. Tolerances are loose where the two sides legitimately measure
slightly different things (e.g. Yahoo's enterprise value uses intraday data).
"""
from __future__ import annotations

import sys

from .data import fetch_snapshot, latest, safe_div
from .engine import analyze


def _close(a, b, rel_tol=0.10, abs_tol=0.0):
    if a is None or b is None:
        return None
    if abs(a - b) <= abs_tol:
        return True
    denom = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / denom <= rel_tol


def run_checks(ticker: str) -> list[dict]:
    snap = fetch_snapshot(ticker)
    r = analyze(ticker)
    m, s, info = r["metrics"], snap["series"], snap.get("info_subset", {})
    checks = []

    def check(name, reported, recomputed, ok, note=""):
        checks.append({"check": name, "reported": reported, "recomputed": recomputed,
                       "ok": ok, "note": note})

    # --- identity checks (must hold by construction) ---
    px, sh = r.get("price"), m.get("shares_outstanding")
    mc = m.get("market_cap")
    check("Market cap = price x shares", mc, px * sh if px and sh else None,
          _close(mc, px * sh if px and sh else None, 0.10),
          "10% tolerance: share count and quote timestamps differ.")
    ev, nd = m.get("enterprise_value"), m.get("net_debt")
    check("Enterprise value = mcap + net debt", ev,
          (mc + nd) if (mc is not None and nd is not None) else None,
          _close(ev, (mc + nd) if (mc is not None and nd is not None) else None, 0.15),
          "15% tolerance: EV source may include minority interest/preferred.")
    pe, teps = m.get("pe"), info.get("trailingEps")
    check("P/E = price / trailing EPS", pe,
          safe_div(px, teps) if teps and teps > 0 else None,
          _close(pe, safe_div(px, teps) if teps and teps > 0 else None, 0.05))
    ps = m.get("ps")
    check("P/S = mcap / TTM revenue", ps, safe_div(mc, m.get("ttm_revenue")),
          _close(ps, safe_div(mc, m.get("ttm_revenue")), 0.12))
    # --- statement-derived checks ---
    ocf, capex, fcf = latest(s.get("ocf")), latest(s.get("capex")), latest(s.get("fcf"))
    if ocf is not None and capex is not None:
        check("FCF = OCF - capex (last FY)", fcf, ocf + capex,
              _close(fcf, ocf + capex, 0.02),
              "capex is negative in source data.")
    gp, rev = latest(s.get("gross_profit")), latest(s.get("revenue"))
    gm = m.get("gross_margin")
    recomputed_gm = safe_div(gp, rev)
    if recomputed_gm is not None and gm is not None:
        check("Gross margin vs last-FY statement", round(gm, 4), round(recomputed_gm, 4),
              abs(gm - recomputed_gm) < 0.06,
              "6pp tolerance: reported value is TTM, statement is last FY.")
    nd2 = None
    if m.get("total_debt") is not None and m.get("cash") is not None:
        nd2 = m["total_debt"] - m["cash"]
    check("Net debt = total debt - cash", nd, nd2, _close(nd, nd2, 0.001))
    # growth recomputation from raw series
    if rev is not None and s.get("revenue") and len(s["revenue"]) >= 2:
        prev = s["revenue"][-2]["value"]
        annual_g = rev / prev - 1 if prev > 0 else None
        rg = m.get("rev_growth_1y")
        if annual_g is not None and rg is not None:
            check("Revenue growth 1y vs annual statements", round(rg, 4), round(annual_g, 4),
                  abs(rg - annual_g) < 0.08,
                  "8pp tolerance: reported prefers TTM-vs-prior-TTM when 8 quarters exist.")
    # --- range/sanity checks ---
    dy = m.get("dividend_yield")
    check("Dividend yield in sane range (0-15%)", dy, None,
          None if dy is None else 0 <= dy <= 0.15)
    for key in ("gross_margin", "operating_margin", "net_margin", "fcf_margin"):
        v = m.get(key)
        if v is not None:
            check(f"{key} in sane range (-200%..100%)", round(v, 3), None, -2 <= v <= 1)
    vh = m.get("valuation_history") or {}
    for k in ("pe_percentile", "ps_percentile"):
        if vh.get(k) is not None:
            check(f"{k} in [0,1]", vh[k], None, 0 <= vh[k] <= 1)
    # quant checks internal consistency
    q = r.get("quant_checks") or {}
    p = q.get("piotroski")
    if p:
        check("F-Score equals sum of passed checks", p["score"],
              sum(1 for c in p["checks"] if c["pass"]),
              p["score"] == sum(1 for c in p["checks"] if c["pass"]))
    z = q.get("altman")
    if z and not z.get("skipped") and z.get("components"):
        wsum = sum(c["weighted"] for c in z["components"] if c["weighted"] is not None)
        check("Z-Score equals sum of components", z["score"], round(wsum, 2),
              abs(z["score"] - wsum) < 0.02)
        have_re = latest(s.get("retained_earnings")) is not None
        check("Z-Score has retained-earnings input", None, None, have_re,
              "" if have_re else "Retained Earnings row missing from balance sheet data.")
    # factor arithmetic — displayed contributions are rounded to 0.1 each, so
    # summing 12 of them can drift up to ~0.6 from the exact total
    total_contrib = sum(f["contribution"] for f in r["factors"].values())
    pen = sum(x["points"] for x in r.get("score_penalties") or [])
    check("Total score = factor contributions + penalties", r["total_score"],
          round(max(0, min(100, total_contrib + pen)), 1),
          abs(r["total_score"] - max(0, min(100, total_contrib + pen))) < 0.7,
          "0.7 tolerance covers display rounding of 12 contributions.")
    wsum = sum(f["weight"] for f in r["factors"].values())
    check("Factor weights sum to 100%", round(wsum, 1), 100.0, abs(wsum - 100) < 0.5)
    # valuation block consistency
    v = r.get("valuation")
    if v:
        ev_fv = sum(sc["fair_value"] * sc["probability"] for sc in v["scenarios"].values())
        check("Expected value = prob-weighted scenario FVs", v["expected_value"],
              round(ev_fv, 2), abs(v["expected_value"] - ev_fv) < 0.05)
        psum = sum(sc["probability"] for sc in v["scenarios"].values())
        check("Scenario probabilities sum to 1", round(psum, 3), 1.0, abs(psum - 1) < 0.001)
        for name, sc in v["scenarios"].items():
            ok = _close(sc["upside"], sc["fair_value"] / r["price"] - 1, 0.001, abs_tol=0.001)
            check(f"{name} upside = FV/price - 1", sc["upside"],
                  round(sc["fair_value"] / r["price"] - 1, 4), ok)
    return checks


def main(tickers):
    any_fail = False
    for tk in tickers:
        print(f"\n=== {tk} ===")
        try:
            checks = run_checks(tk)
        except Exception as e:
            print(f"  ERROR: {e}")
            any_fail = True
            continue
        for c in checks:
            if c["ok"] is None:
                status = "SKIP"
            elif c["ok"]:
                status = "PASS"
            else:
                status, any_fail = "FAIL", True
            detail = ""
            if c["reported"] is not None and c["recomputed"] is not None and status == "FAIL":
                detail = f"  reported={c['reported']} recomputed={c['recomputed']}"
            print(f"  [{status}] {c['check']}{detail}" + (f"  ({c['note']})" if c["note"] and status == "FAIL" else ""))
        n_pass = sum(1 for c in checks if c["ok"] is True)
        n_fail = sum(1 for c in checks if c["ok"] is False)
        print(f"  -> {n_pass} passed, {n_fail} failed, "
              f"{sum(1 for c in checks if c['ok'] is None)} skipped")
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["AAPL"]))
