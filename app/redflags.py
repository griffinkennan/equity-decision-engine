"""Red-flag detector and Accounting Quality score."""
from __future__ import annotations

from .data import latest, yoy, safe_div


def detect_red_flags(snap, ctype):
    m, s, mom = snap["metrics"], snap["series"], snap["momentum"]
    est, holders = snap["estimates"], snap["holders"]
    flags = []

    def flag(name, severity, explanation, why, affects=True):
        flags.append({"flag": name, "severity": severity, "explanation": explanation,
                      "why_it_matters": why, "affects_rating": affects})

    g = m.get("rev_growth_1y")
    if g is not None and g < -0.03:
        flag("Revenue decline", "High" if g < -0.12 else "Medium",
             f"Revenue fell {g:.0%} over the last year.",
             "Shrinking sales usually compress margins and multiples together.")
    prior = m.get("rev_growth_prior")
    if g is not None and prior is not None and prior - g > 0.10 and g < 0.15:
        flag("Slowing growth", "Medium",
             f"Growth decelerated from {prior:.0%} to {g:.0%}.",
             "Decelerating growth often triggers multiple compression.")
    fcf = m.get("ttm_fcf")
    if fcf is not None and fcf < 0:
        sev = "Medium" if ctype in ("Unprofitable High-Growth Company",
                                    "Biotech or Clinical-Stage Company") else "High"
        flag("Negative free cash flow", sev,
             "The business consumes cash after capital spending.",
             "Persistent burn forces dilution or debt unless growth fixes it.")
    fcf_series = s.get("fcf")
    if fcf_series and len(fcf_series) >= 2 and fcf_series[-1]["value"] < fcf_series[-2]["value"] < 0:
        flag("Worsening free cash flow", "High", "FCF is negative and deteriorating year over year.",
             "Accelerating burn shortens the runway quickly.")
    ni_g, fcf_g = m.get("ni_growth"), m.get("fcf_growth")
    if ni_g is not None and fcf_g is not None and ni_g > 0.05 and fcf_g < -0.05:
        flag("Net income rising while FCF falls", "Medium",
             f"Net income grew {ni_g:.0%} while FCF fell {fcf_g:.0%}.",
             "A widening earnings/cash gap can signal aggressive accounting.")
    nde = m.get("net_debt_to_ebitda")
    if nde is not None and nde > 3.5:
        flag("High debt load", "High" if nde > 5 else "Medium",
             f"Net debt is {nde:.1f}x EBITDA.",
             "High leverage magnifies downturns and refinancing risk.")
    cr = m.get("current_ratio")
    if cr is not None and cr < 1.0:
        flag("Weak current ratio", "Medium" if cr > 0.8 else "High",
             f"Current ratio of {cr:.2f} — short-term liabilities exceed short-term assets.",
             "Liquidity stress can force dilutive financing at the worst time.")
    runway = m.get("cash_runway_years")
    if runway is not None and runway < 1.5:
        flag("Short cash runway", "High",
             f"~{runway:.1f} years of cash at the current burn rate.",
             "The company will likely need to raise capital within 12-18 months.")
    ie = s.get("interest_expense")
    if ie and len(ie) >= 2 and ie[-1]["value"] > ie[-2]["value"] * 1.25 and ie[-1]["value"] > 0:
        flag("Rising interest expense", "Low",
             "Interest expense rose more than 25% year over year.",
             "Higher debt costs eat into earnings, especially when rates stay high.")
    gm = s.get("gross_profit")
    rev_s = s.get("revenue")
    if gm and rev_s and len(gm) >= 2 and len(rev_s) >= 2:
        gm_now = safe_div(gm[-1]["value"], rev_s[-1]["value"])
        gm_prev = safe_div(gm[-2]["value"], rev_s[-2]["value"])
        if gm_now and gm_prev and gm_prev - gm_now > 0.03:
            flag("Declining gross margin", "Medium",
                 f"Gross margin fell from {gm_prev:.0%} to {gm_now:.0%}.",
                 "Margin erosion suggests pricing pressure or rising costs.")
    dil = m.get("dilution_1y")
    if dil is not None and dil > 0.05:
        flag("Heavy share dilution", "High" if dil > 0.12 else "Medium",
             f"Share count grew {dil:.1%} in the last year.",
             "Dilution transfers value from existing shareholders.")
    sbc = m.get("sbc_pct_revenue")
    if sbc is not None and sbc > 0.10:
        flag("High stock-based compensation", "Medium",
             f"SBC is {sbc:.0%} of revenue.",
             "Large SBC understates true compensation cost and drives dilution.")
    buys, sells = holders.get("insider_buys"), holders.get("insider_sells")
    if sells and sells >= 5 and (buys or 0) == 0:
        flag("Insider selling", "Low",
             f"{sells} insider sale transactions and no purchases in the last year.",
             "Insiders sell for many reasons, but zero buying removes a bullish signal.", affects=False)
    pe = m.get("pe")
    ps = m.get("ps")
    if (pe and pe > 60) or (ps and ps > 20 and (g or 0) < 0.30):
        flag("Excessive valuation", "Medium",
             f"Valuation is stretched (P/E {pe:.0f}x)" if pe and pe > 60
             else f"Valuation is stretched (P/S {ps:.0f}x vs {0 if g is None else g:.0%} growth).",
             "Very high multiples leave no room for execution slip-ups.")
    if mom.get("above_ma200") is False:
        flag("Price below 200-day moving average", "Low",
             "The stock is trading in a technical downtrend.",
             "Fighting the trend raises timing risk even for good businesses.")
    ned = snap.get("calendar", {}).get("next_earnings_date")
    if ned:
        import datetime as _dt
        try:
            d = _dt.date.fromisoformat(str(ned)[:10])
            days = (d - _dt.date.today()).days
            if 0 <= days <= 21:
                flag("Earnings report within 3 weeks", "Low",
                     f"Next earnings date: {d.isoformat()} ({days} days away).",
                     "Earnings events cause outsized moves in either direction.", affects=False)
        except ValueError:
            pass
    ar_g, inv_g = m.get("receivables_growth"), m.get("inventory_growth")
    if ar_g is not None and g is not None and ar_g > g + 0.15:
        flag("Receivables growing faster than revenue", "Medium",
             f"Receivables grew {ar_g:.0%} vs revenue {g:.0%}.",
             "Can indicate channel stuffing or deteriorating collection quality.")
    if inv_g is not None and g is not None and inv_g > g + 0.20:
        flag("Inventory growing faster than revenue", "Medium",
             f"Inventory grew {inv_g:.0%} vs revenue {g:.0%}.",
             "Bloated inventory often precedes write-downs and margin hits.")
    payout = m.get("payout_ratio")
    dy = m.get("dividend_yield")
    if dy and dy > 0.005 and payout is not None and payout > 1.0:
        flag("Dividend not covered by earnings", "Medium",
             f"Payout ratio is {payout:.0%} — the dividend exceeds net income.",
             "Uncovered dividends get funded by debt or cut; either hurts the stock.")
    ocf_ni = m.get("ocf_to_ni")
    if ocf_ni is not None and ocf_ni < 0.6:
        flag("High accruals (OCF well below net income)", "Medium",
             f"Operating cash flow is only {ocf_ni:.0%} of net income.",
             "Earnings not backed by cash are lower quality and more easily manipulated.")
    quant = snap.get("_quant") or {}
    z = quant.get("altman") or {}
    if z.get("zone") == "Distress":
        flag("Altman Z-Score in distress zone", "High",
             f"Z-Score of {z['score']} is below 1.81" + (" (approximate — one input missing)"
                                                         if z.get("partial") else "") + ".",
             "Scores in this zone have historically preceded a meaningful share of "
             "bankruptcies within two years.")
    elif z.get("zone") == "Grey":
        flag("Altman Z-Score in grey zone", "Low",
             f"Z-Score of {z['score']} sits between the safe (>2.99) and distress (<1.81) thresholds.",
             "Financial strength is ambiguous by this classic measure.", affects=False)
    f_sc = quant.get("piotroski") or {}
    if f_sc.get("score") is not None and f_sc["score"] <= 2 and f_sc.get("out_of", 0) >= 7:
        flag("Very low Piotroski F-Score", "Medium",
             f"Only {f_sc['score']} of {f_sc['out_of']} fundamental-health checks pass.",
             "Low F-Scores historically identify deteriorating businesses.")
    audit = snap.get("info_subset", {}).get("auditRisk")
    if isinstance(audit, (int, float)) and audit >= 8:
        flag("Elevated governance/audit risk score", "Low",
             f"ISS audit-risk percentile {audit}/10 (higher = riskier).",
             "Weak audit governance correlates with restatements.", affects=False)

    order = {"High": 0, "Medium": 1, "Low": 2}
    flags.sort(key=lambda f: order[f["severity"]])
    return flags


def accounting_quality(snap):
    """0-100 accounting quality score with detail rows."""
    m = snap["metrics"]
    rows, score, weight_sum = [], 0.0, 0.0

    def add(name, value, points, weight, note=""):
        nonlocal score, weight_sum
        if points is None:
            return
        rows.append({"metric": name, "value": value, "score": points, "note": note})
        score += points * weight
        weight_sum += weight

    ocf_ni = m.get("ocf_to_ni")
    add("Operating cash flow / net income", ocf_ni,
        None if ocf_ni is None else (90 if ocf_ni >= 1.1 else 75 if ocf_ni >= 0.9
                                     else 55 if ocf_ni >= 0.7 else 30),
        1.3, "Cash backing of reported earnings.")
    fcf_ni = m.get("fcf_to_ni")
    add("Free cash flow / net income", fcf_ni,
        None if fcf_ni is None else (88 if fcf_ni >= 0.9 else 70 if fcf_ni >= 0.6
                                     else 50 if fcf_ni >= 0.3 else 28), 1.1)
    g = m.get("rev_growth_1y")
    ar = m.get("receivables_growth")
    if ar is not None and g is not None:
        gap = ar - g
        add("Receivables growth minus revenue growth", gap,
            85 if gap <= 0.02 else 65 if gap <= 0.10 else 40 if gap <= 0.25 else 20, 0.9)
    inv = m.get("inventory_growth")
    if inv is not None and g is not None:
        gap = inv - g
        add("Inventory growth minus revenue growth", gap,
            85 if gap <= 0.02 else 65 if gap <= 0.12 else 40 if gap <= 0.30 else 20, 0.7)
    sbc = m.get("sbc_pct_revenue")
    add("Stock-based comp as % of revenue", sbc,
        None if sbc is None else (88 if sbc <= 0.02 else 70 if sbc <= 0.05
                                  else 45 if sbc <= 0.12 else 22), 0.8,
        "High SBC widens the GAAP vs non-GAAP gap.")
    if not rows:
        return {"score": 50, "rows": [], "verdict": "Unknown",
                "note": "Insufficient data to judge accounting quality; treated as neutral."}
    final = round(score / weight_sum, 0)
    verdict = ("Clean" if final >= 75 else "Acceptable" if final >= 55
               else "Questionable" if final >= 40 else "Poor")
    note = ""
    if (ocf_ni is not None and ocf_ni < 0.7) or (fcf_ni is not None and fcf_ni < 0.4):
        note = "Reported earnings look materially stronger than cash flow — treat EPS with caution."
    return {"score": final, "rows": rows, "verdict": verdict, "note": note}
