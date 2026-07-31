"""Classic academic quant health checks: Piotroski F-Score and Altman Z-Score.

Both are computed strictly from the annual statement series and shown with
per-component detail so the user can see exactly which checks passed. They act
as cross-checks on the main model: Z-Score distress and very low F-Scores also
surface as red flags.
"""
from __future__ import annotations

from .data import latest, safe_div


def _pair(series):
    """(current, prior) annual values, or (None, None)."""
    if not series or len(series) < 2:
        return (latest(series), None) if series else (None, None)
    return series[-1]["value"], series[-2]["value"]


def piotroski(snap: dict) -> dict | None:
    """F-Score 0-9. Requires two consecutive annual statements."""
    s = snap["series"]
    ni, ni_p = _pair(s.get("net_income"))
    ta, ta_p = _pair(s.get("total_assets"))
    ocf = latest(s.get("ocf"))
    ltd, ltd_p = _pair(s.get("long_term_debt") or s.get("total_debt"))
    ca, ca_p = _pair(s.get("current_assets"))
    cl, cl_p = _pair(s.get("current_liabilities"))
    sh, sh_p = _pair(s.get("shares"))
    gp, gp_p = _pair(s.get("gross_profit"))
    rev, rev_p = _pair(s.get("revenue"))

    checks = []

    def check(name, cond, group):
        if cond is None:
            return
        checks.append({"check": name, "pass": bool(cond), "group": group})

    roa = safe_div(ni, ta)
    roa_p = safe_div(ni_p, ta_p)
    check("Positive return on assets", None if roa is None else roa > 0, "Profitability")
    check("Positive operating cash flow", None if ocf is None else ocf > 0, "Profitability")
    check("ROA improved vs prior year",
          None if (roa is None or roa_p is None) else roa > roa_p, "Profitability")
    check("Cash flow exceeds net income (low accruals)",
          None if (ocf is None or ni is None) else ocf > ni, "Profitability")

    lev = safe_div(ltd, ta)
    lev_p = safe_div(ltd_p, ta_p)
    check("Leverage (LT debt / assets) decreased",
          None if (lev is None or lev_p is None) else lev <= lev_p, "Leverage & liquidity")
    cr = safe_div(ca, cl)
    cr_p = safe_div(ca_p, cl_p)
    check("Current ratio improved",
          None if (cr is None or cr_p is None) else cr > cr_p, "Leverage & liquidity")
    check("No new shares issued",
          None if (sh is None or sh_p is None) else sh <= sh_p * 1.005, "Leverage & liquidity")

    gm = safe_div(gp, rev)
    gm_p = safe_div(gp_p, rev_p)
    check("Gross margin improved",
          None if (gm is None or gm_p is None) else gm > gm_p, "Operating efficiency")
    at = safe_div(rev, ta)
    at_p = safe_div(rev_p, ta_p)
    check("Asset turnover improved",
          None if (at is None or at_p is None) else at > at_p, "Operating efficiency")

    if len(checks) < 5:
        return None
    score = sum(1 for c in checks if c["pass"])
    verdict = ("Strong" if score >= 7 else "Solid" if score >= 5
               else "Weak" if score >= 3 else "Very weak")
    return {
        "score": score, "out_of": len(checks), "verdict": verdict, "checks": checks,
        "note": (f"F-Score counts {len(checks)} binary fundamental-health signals "
                 "(9 when data is complete). 7+ historically identifies improving "
                 "businesses; 0-2 flags deteriorating ones."),
    }


def altman_z(snap: dict, ctype: str) -> dict | None:
    """Classic Altman Z-Score. Not meaningful for financials — skipped there."""
    if ctype in ("Bank or Financial Company", "REIT"):
        return {"skipped": True,
                "note": "Altman Z-Score is not meaningful for financial companies and "
                        "REITs (their balance sheets break the model's ratios)."}
    s, m = snap["series"], snap["metrics"]
    ta = latest(s.get("total_assets"))
    if not ta:
        return None
    wc = None
    ca, cl = latest(s.get("current_assets")), latest(s.get("current_liabilities"))
    if ca is not None and cl is not None:
        wc = ca - cl
    re_ = latest(s.get("retained_earnings"))
    ebit = latest(s.get("ebit"))
    tl = latest(s.get("total_liabilities"))
    mcap = m.get("market_cap")
    rev = latest(s.get("revenue"))

    comps, z = [], 0.0

    def add(label, coef, value):
        nonlocal z
        if value is None:
            comps.append({"component": label, "value": None, "weighted": None})
            return False
        z += coef * value
        comps.append({"component": label, "value": round(value, 3),
                      "weighted": round(coef * value, 3)})
        return True

    have = 0
    have += add("Working capital / total assets (x1.2)", 1.2, safe_div(wc, ta))
    have += add("Retained earnings / total assets (x1.4)", 1.4, safe_div(re_, ta))
    have += add("EBIT / total assets (x3.3)", 3.3, safe_div(ebit, ta))
    have += add("Market cap / total liabilities (x0.6)", 0.6, safe_div(mcap, tl))
    have += add("Revenue / total assets (x1.0)", 1.0, safe_div(rev, ta))
    if have < 4:
        return None
    zone = "Safe" if z > 2.99 else "Grey" if z >= 1.81 else "Distress"
    return {
        "score": round(z, 2), "zone": zone, "components": comps,
        "partial": have < 5,
        "note": ("Z > 2.99 = safe zone, 1.81-2.99 = grey zone, < 1.81 = distress zone "
                 "(elevated bankruptcy risk within ~2 years, per Altman's original model)."
                 + (" One component was unavailable; treat the score as approximate."
                    if have < 5 else "")),
    }
