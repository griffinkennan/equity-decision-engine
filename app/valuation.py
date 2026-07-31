"""Bull / Base / Bear fair-value scenarios (engine v2, model 1.3.0).

Three-year scenario framework instead of the old one-year shortcut:

  1. Project the per-share fundamental (EPS, or revenue/share for
     pre-profit companies) three years out with *decaying* growth —
     year-1 growth fades 20%/yr toward maturity.
  2. Apply a scenario terminal multiple (anchored to a blend of the
     current multiple and a growth-justified "fair" multiple).
  3. Discount the year-3 value back to today at a required return that
     scales with the stock's risk (volatility, leverage, size).

Cross-checks layered on top:
  - DCF anchor (5y FCF + Gordon terminal value) for FCF-positive companies;
    the base case blends multiple-FV / DCF / analyst mean target.
  - Scenario probabilities start at 25/50/25 and shift with observable
    evidence (trend, valuation percentile, estimate revisions).
  - Monte Carlo pass (4,000 draws over growth/multiple uncertainty) yields a
    P10-P90 fair-value band and "% of draws above the current price".

Every assumption is surfaced in the output. These are estimates of what the
business could be worth under stated assumptions — not price predictions.
"""
from __future__ import annotations

import numpy as np


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def required_return(snap):
    """Discount rate: 9% baseline, scaled up for risk factors."""
    m, mom = snap["metrics"], snap["momentum"]
    r, why = 0.09, ["9.0% baseline equity return"]
    vol = mom.get("volatility_annualized")
    if vol is not None and vol > 0.45:
        r += 0.02; why.append("+2.0% high volatility")
    elif vol is not None and vol > 0.30:
        r += 0.01; why.append("+1.0% elevated volatility")
    if (m.get("net_debt_to_ebitda") or 0) > 3 or (m.get("debt_to_equity") or 0) > 2:
        r += 0.01; why.append("+1.0% balance-sheet leverage")
    mcap = m.get("market_cap") or 0
    if mcap > 200e9:
        r -= 0.01; why.append("-1.0% mega-cap stability")
    elif mcap < 2e9:
        r += 0.01; why.append("+1.0% small-cap risk")
    if (m.get("ttm_fcf") or 0) <= 0:
        r += 0.02; why.append("+2.0% negative free cash flow")
    return round(_clamp(r, 0.07, 0.16), 4), why


def _growth_anchor(snap):
    """Base-case year-1 growth and where it came from."""
    m, est = snap["metrics"], snap["estimates"]
    re_ = (est.get("revenue_estimate") or {}).get("+1y") or {}
    if re_.get("growth") is not None:
        return _clamp(re_["growth"], -0.25, 0.60), "consensus next-FY revenue estimate"
    parts = [g for g in (m.get("rev_growth_1y"), m.get("rev_cagr_3y")) if g is not None]
    if parts:
        return _clamp(sum(parts) / len(parts), -0.25, 0.60), \
            "average of trailing 1y growth and 3y CAGR (no consensus estimate available)"
    return 0.04, "default 4% (no growth data — treat with caution)"


def _project(base_value, g1, years=3, decay=0.8, margin_drift=1.0):
    """Compound with decaying growth; returns list of per-year values."""
    path, v, g = [], base_value, g1
    for _ in range(years):
        v = v * (1 + _clamp(g, -0.5, 0.9)) * margin_drift
        path.append(v)
        g *= decay
    return path


def _dcf_anchor(snap, g1, r):
    """5-year FCF DCF with Gordon terminal value. None if not applicable."""
    m = snap["metrics"]
    fcf = m.get("ttm_fcf")
    shares = m.get("shares_outstanding")
    if not fcf or fcf <= 0 or not shares:
        return None
    g_term = 0.03
    if r <= g_term + 0.015:
        return None
    pv, v, g = 0.0, fcf, _clamp(g1, -0.10, 0.35)
    for yr in range(1, 6):
        v = v * (1 + g)
        pv += v / (1 + r) ** yr
        g = max(g_term, g * 0.75)
    terminal = v * (1 + g_term) / (r - g_term)
    pv += terminal / (1 + r) ** 5
    equity = pv - (m.get("net_debt") or 0)
    fv = equity / shares
    if fv <= 0:
        return None
    return {
        "fair_value": round(fv, 2),
        "assumptions": (f"TTM FCF grown at {g1:.0%} (fading 25%/yr to 3% terminal), "
                        f"discounted at {r:.1%}; terminal value = Gordon growth at 3%."),
    }


def _adjusted_probs(snap):
    """Start 25/50/25; shift with observable evidence. Returns (probs, reasons)."""
    probs = {"bear": 0.25, "base": 0.50, "bull": 0.25}
    reasons = []
    mom, m, est = snap["momentum"], snap["metrics"], snap["estimates"]

    def shift(frm, to, amt, why):
        moved = min(amt, probs[frm] - 0.10)  # never push a scenario below 10%
        if moved <= 0:
            return
        probs[frm] -= moved
        probs[to] += moved
        reasons.append(why)

    if mom.get("above_ma200") is False:
        shift("bull", "bear", 0.05, "price below 200-day trend (+5% bear)")
    elif mom.get("above_ma200") is True and (mom.get("rel_spy_3m") or 0) > 0.02:
        shift("bear", "bull", 0.05, "uptrend outpacing the S&P 500 (+5% bull)")
    vh = m.get("valuation_history") or {}
    pct = vh.get("pe_percentile", vh.get("ps_percentile"))
    if pct is not None:
        if pct > 0.85:
            shift("bull", "bear", 0.05, "valuation near the top of its own history (+5% bear)")
        elif pct < 0.30:
            shift("bear", "bull", 0.05, "valuation near the bottom of its own history (+5% bull)")
    revs = (est.get("eps_revisions_90d") or {})
    rev90 = revs.get("+1y", revs.get("0y"))
    if rev90 is not None:
        if rev90 > 0.02:
            shift("bear", "bull", 0.05, "analysts revising estimates up (+5% bull)")
        elif rev90 < -0.02:
            shift("bull", "bear", 0.05, "analysts revising estimates down (+5% bear)")
    return {k: round(v, 3) for k, v in probs.items()}, reasons


def _monte_carlo(kind, base_input, g1, mult_base, r, net_debt, shares, price,
                 scenario_mults, n=4000):
    """Fair-value distribution over growth/multiple uncertainty."""
    rng = np.random.default_rng(42)  # fixed seed: same inputs -> same band
    g = rng.normal(g1, 0.045, n)
    mult = rng.normal(mult_base, mult_base * 0.16, n)
    mult = np.clip(mult, mult_base * 0.4, mult_base * 2.0)
    drift = rng.normal(1.0, 0.015, n)
    # 3-year compounding with the same 20%/yr growth decay as the scenarios
    growth_factor = (1 + np.clip(g, -0.5, 0.9)) * (1 + np.clip(g * 0.8, -0.5, 0.9)) \
        * (1 + np.clip(g * 0.64, -0.5, 0.9))
    v3 = base_input * growth_factor * drift ** 3
    if kind == "eps":
        fv = (v3 * mult) / (1 + r) ** 3
    else:  # revenue -> equity value
        fv = (v3 * mult - net_debt) / shares / (1 + r) ** 3
    fv = np.maximum(fv, 0.01)
    pcts = np.percentile(fv, [10, 25, 50, 75, 90])
    return {
        "p10": round(float(pcts[0]), 2), "p25": round(float(pcts[1]), 2),
        "p50": round(float(pcts[2]), 2), "p75": round(float(pcts[3]), 2),
        "p90": round(float(pcts[4]), 2),
        "prob_above_price": round(float((fv > price).mean()), 3),
        "n": n,
        "note": ("Distribution of fair-value estimates when growth (±4.5pp), the exit "
                 "multiple (±16%) and margins (±1.5%/yr) are drawn randomly around the "
                 "base case — it quantifies assumption uncertainty, not market prices."),
    }


def build_scenarios(snap, ctype):
    m, est = snap["metrics"], snap["estimates"]
    price = snap.get("price")
    if not price:
        return None
    info = snap.get("info_subset", {})
    r, r_why = required_return(snap)
    g_base, g_src = _growth_anchor(snap)
    probs, prob_reasons = _adjusted_probs(snap)

    # choose per-share fundamental
    eps = None
    ee = (est.get("earnings_estimate") or {}).get("+1y") or {}
    eps_src = None
    if ee.get("avg"):
        eps, eps_src = ee["avg"], "consensus next-FY EPS"
    elif info.get("forwardEps"):
        eps, eps_src = info["forwardEps"], "Yahoo forward EPS"
    elif info.get("trailingEps") and info["trailingEps"] > 0:
        eps, eps_src = info["trailingEps"], "trailing EPS (no forward estimate)"

    scenarios, mc = {}, None
    shares = m.get("shares_outstanding")
    net_debt = m.get("net_debt") or 0

    if eps and eps > 0:
        method = "3-year EPS path x terminal P/E, discounted back"
        pe_now = _clamp(m.get("forward_pe") or m.get("pe") or 18, 5, 60)
        fair_pe = _clamp(10 + max(0.0, g_base) * 90, 8, 45)
        base_pe = 0.5 * pe_now + 0.5 * fair_pe
        cases = {
            "bear": {"g": g_base - 0.08, "mult": base_pe * 0.72, "drift": 0.985,
                     "margin_note": "margins erode ~1.5%/yr"},
            "base": {"g": g_base, "mult": base_pe, "drift": 1.0,
                     "margin_note": "margins stable"},
            "bull": {"g": g_base + 0.06, "mult": base_pe * 1.22, "drift": 1.01,
                     "margin_note": "margins expand ~1%/yr"},
        }
        for k, c in cases.items():
            path = _project(eps, c["g"], margin_drift=c["drift"])
            fv = path[-1] * c["mult"] / (1 + r) ** 3
            scenarios[k] = _case(k, fv, price, c["g"], c["margin_note"],
                                 f"{c['mult']:.1f}x terminal P/E",
                                 [{"year": i + 1, "value": round(v, 2),
                                   "implied_price": round(v * c["mult"] / (1 + r) ** (2 - i), 2)}
                                  for i, v in enumerate(path)], "EPS")
        mc = _monte_carlo("eps", eps, g_base, base_pe, r, net_debt, shares, price,
                          {k: c["mult"] for k, c in cases.items()})
        basis_note = f"EPS basis: {eps_src} (${eps:.2f}); growth anchor: {g_src}."
    else:
        rev = m.get("ttm_revenue")
        if not (rev and shares):
            return None
        method = "3-year revenue path x terminal EV/S, discounted back"
        ev_s_now = _clamp(m.get("ev_revenue") or 3.0, 0.3, 30)
        # a sales dollar is only worth what its margins can become: scale the
        # growth-justified EV/S by gross margin (software ~75% vs autos ~10%)
        gm_eff = _clamp(m.get("gross_margin") if m.get("gross_margin") is not None else 0.30,
                        0.05, 0.90)
        fair_evs = _clamp(gm_eff * (2 + max(0.0, g_base) * 22), 0.4, 12)
        base_mult = 0.5 * ev_s_now + 0.5 * fair_evs
        # cash burners keep printing shares: bake dilution into the share count
        d = _clamp(m.get("dilution_1y") if m.get("dilution_1y") is not None else 0.04, 0.0, 0.15)
        dil = {"bear": min(0.20, d * 1.5 + 0.02), "base": d, "bull": d * 0.5}
        cases = {
            "bear": {"g": max(-0.30, g_base - 0.12), "mult": base_mult * 0.6, "drift": 1.0,
                     "margin_note": f"burn continues; {dil['bear']:.0%}/yr dilution"},
            "base": {"g": g_base, "mult": base_mult, "drift": 1.0,
                     "margin_note": f"progress toward profitability; {dil['base']:.0%}/yr dilution"},
            "bull": {"g": g_base + 0.08, "mult": base_mult * 1.35, "drift": 1.0,
                     "margin_note": f"operating leverage; {dil['bull']:.0%}/yr dilution"},
        }
        for k, c in cases.items():
            sh3 = shares * (1 + dil[k]) ** 3
            path = _project(rev, c["g"])
            fv = max(0.01, (path[-1] * c["mult"] - net_debt) / sh3 / (1 + r) ** 3)
            scenarios[k] = _case(k, fv, price, c["g"], c["margin_note"],
                                 f"{c['mult']:.1f}x terminal EV/S",
                                 [{"year": i + 1, "value": round(v / 1e9, 2),
                                   "implied_price": round(max(0.01, (v * c["mult"] - net_debt)
                                                              / (shares * (1 + dil[k]) ** (i + 1))
                                                              / (1 + r) ** (2 - i)), 2)}
                                  for i, v in enumerate(path)], "Revenue ($B)")
        mc = _monte_carlo("rev", rev, g_base, base_mult, r, net_debt,
                          shares * (1 + dil["base"]) ** 3, price,
                          {k: c["mult"] for k, c in cases.items()})
        basis_note = (f"Revenue basis: TTM ${rev / 1e9:.1f}B; growth anchor: {g_src}. "
                      f"Terminal EV/S scaled by {gm_eff:.0%} gross margin.")

    # base-case anchoring: blend multiple-FV with DCF and analyst mean target
    dcf = _dcf_anchor(snap, g_base, r)
    pt = est.get("price_targets") or {}
    analyst = None
    if pt.get("mean"):
        analyst = {"mean": pt.get("mean"), "high": pt.get("high"), "low": pt.get("low"),
                   "n": (snap.get("info_subset") or {}).get("numberOfAnalystOpinions")}
    anchors = [("scenario model", scenarios["base"]["fair_value"], 0.5)]
    if dcf:
        anchors.append(("DCF", dcf["fair_value"], 0.25))
    if analyst and analyst["mean"]:
        anchors.append(("analyst mean target", analyst["mean"], 0.25))
    tw = sum(w for _, _, w in anchors)
    blended = sum(v * w for _, v, w in anchors) / tw
    if len(anchors) > 1:
        scenarios["base"]["fair_value"] = round(blended, 2)
        scenarios["base"]["upside"] = round(blended / price - 1, 4)
        scenarios["base"]["anchors"] = [
            {"name": n_, "fair_value": round(v, 2), "weight": round(w / tw, 2)}
            for n_, v, w in anchors]

    for k in scenarios:
        scenarios[k]["probability"] = probs[k]

    sanity_note = None
    if analyst and analyst.get("mean"):
        div = scenarios["base"]["fair_value"] / analyst["mean"] - 1
        if abs(div) > 0.40:
            direction = "above" if div > 0 else "below"
            sanity_note = (f"Caution: the model's base case is {abs(div):.0%} {direction} the "
                           f"mean analyst target (${analyst['mean']:.2f}, n={analyst.get('n') or '?'}). "
                           "Large divergence usually means the multiple or growth assumptions "
                           "are doing heavy lifting — trust the range, not the point estimate.")

    ev_fv = sum(scenarios[k]["fair_value"] * probs[k] for k in scenarios)
    return {
        "method": method,
        "sanity_note": sanity_note,
        "basis_note": basis_note,
        "required_return": r, "required_return_reasons": r_why,
        "probability_reasons": prob_reasons,
        "scenarios": scenarios,
        "dcf": dcf,
        "analyst_targets": analyst,
        "monte_carlo": mc,
        "expected_value": round(ev_fv, 2),
        "expected_upside": round(ev_fv / price - 1, 4),
        "fair_value_range": [scenarios["bear"]["fair_value"], scenarios["bull"]["fair_value"]],
        "disclaimer": ("Scenario fair values are estimates built from the stated growth, "
                       "margin and multiple assumptions — not price predictions or "
                       "guarantees. The Monte Carlo band measures assumption "
                       "uncertainty, not market volatility."),
    }


def _case(name, fv, price, growth, margin_note, multiple_note, path=None, path_label=None):
    out = {
        "name": name.title(),
        "fair_value": round(fv, 2),
        "upside": round(fv / price - 1, 4),
        "assumption_growth": round(growth, 4),
        "assumption_margin": margin_note,
        "assumption_multiple": multiple_note,
    }
    if path:
        out["path"] = path
        out["path_label"] = path_label
    return out


def risk_reward_grade(valn, score, dq_score, mom, m):
    """Excellent / Favorable / Balanced / Unfavorable / Poor."""
    if not valn:
        return "Balanced", "Insufficient data for a full risk/reward assessment."
    up_base = valn["scenarios"]["base"]["upside"]
    down_bear = valn["scenarios"]["bear"]["upside"]
    ratio = None
    if down_bear < -0.01:
        ratio = up_base / abs(down_bear)
    points = 0
    points += 2 if up_base >= 0.30 else 1 if up_base >= 0.15 else 0 if up_base >= 0 else -2
    if ratio is not None:
        points += 2 if ratio >= 2 else 1 if ratio >= 1.2 else 0 if ratio >= 0.7 else -1
    if (m.get("net_debt_to_ebitda") or 0) > 3.5 or (m.get("debt_to_equity") or 0) > 2.5:
        points -= 1
    if (mom.get("volatility_annualized") or 0.3) > 0.6:
        points -= 1
    if dq_score < 60:
        points -= 1
    if score >= 70:
        points += 1
    grade = ("Excellent" if points >= 4 else "Favorable" if points >= 2
             else "Balanced" if points >= 0 else "Unfavorable" if points >= -2 else "Poor")
    expl = (f"Base-case upside {up_base:+.0%}, bear-case downside {down_bear:+.0%}"
            + (f" (reward/risk ~{ratio:.1f}x)." if ratio else "."))
    return grade, expl


def position_suitability(ctype, score, valn, m, mom, dq_score):
    dy = m.get("dividend_yield") or 0
    vol = mom.get("volatility_annualized") or 0.35
    if dq_score < 40:
        return "Watchlist only", "Data quality is too low to size a position responsibly."
    if score < 30:
        return "Avoid", "Weak fundamentals and poor risk/reward — not suitable for most investors."
    if ctype in ("Biotech or Clinical-Stage Company", "Early-Stage Speculative Company"):
        return "High-risk/high-reward stock", ("Binary outcomes and heavy dilution risk; only suitable "
                                               "as a small speculative allocation for risk-tolerant investors.")
    if ctype == "Unprofitable High-Growth Company":
        return "Speculative growth stock", ("Suits growth investors who can tolerate drawdowns and dilution; "
                                            "not appropriate as a core holding until FCF turns positive.")
    if ctype == "Turnaround Company":
        return "Turnaround stock", "Requires evidence of stabilization; suits patient contrarian investors."
    if dy > 0.03 and (m.get("payout_ratio") or 0) < 0.85 and score >= 50:
        return "Income/dividend stock", "Meaningful, covered dividend; suits income-oriented investors."
    if score >= 70 and vol < 0.45 and ctype in ("Mature Profitable Company", "High-Growth Company"):
        return "Core long-term holding", ("Strong fundamentals with acceptable volatility; can anchor "
                                          "a diversified long-term portfolio.")
    if score >= 50:
        return "Watchlist only", ("Mixed signals — worth monitoring for a better price or improving "
                                  "fundamentals before committing capital.")
    return "Trade only", "Fundamentals do not support a long-term position at this price."
