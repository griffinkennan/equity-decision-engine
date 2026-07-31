"""Plain-English explanation layer: everything the UI shows as text."""
from __future__ import annotations

import datetime as dt


def fmt_pct(v, signed=False):
    if v is None:
        return "n/a"
    return f"{v:+.1%}" if signed else f"{v:.1%}"


def fmt_x(v):
    return "n/a" if v is None else f"{v:.1f}x"


def fmt_usd(v):
    if v is None:
        return "n/a"
    a = abs(v)
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if a >= div:
            return f"${v / div:,.1f}{unit}"
    return f"${v:,.0f}"


def timing_rating(snap, valn):
    """Good Entry / Wait / Avoid, with reasons."""
    mom, m = snap["momentum"], snap["metrics"]
    reasons, points = [], 0
    if mom.get("above_ma200") is True:
        points += 2; reasons.append("price is above the 200-day moving average (uptrend)")
    elif mom.get("above_ma200") is False:
        points -= 2; reasons.append("price is below the 200-day moving average (downtrend)")
    if mom.get("above_ma50") is True:
        points += 1
    elif mom.get("above_ma50") is False:
        points -= 1; reasons.append("price is below the 50-day moving average")
    rel = mom.get("rel_spy_3m")
    if rel is not None:
        if rel > 0.03:
            points += 1; reasons.append("outperforming the S&P 500 over 3 months")
        elif rel < -0.05:
            points -= 1; reasons.append("lagging the S&P 500 over 3 months")
    ned = snap.get("calendar", {}).get("next_earnings_date")
    if ned:
        try:
            days = (dt.date.fromisoformat(str(ned)[:10]) - dt.date.today()).days
            if 0 <= days <= 14:
                points -= 1; reasons.append(f"earnings report in {days} days adds event risk")
        except ValueError:
            pass
    if (mom.get("volatility_annualized") or 0) > 0.65:
        points -= 1; reasons.append("volatility is very high")
    regime = (snap.get("_sentiment") or {}).get("market", {}).get("regime")
    if regime == "Risk-off":
        points -= 1; reasons.append("broad market is in a risk-off regime")
    elif regime == "Risk-on":
        points += 1
    up = valn["scenarios"]["base"]["upside"] if valn else None
    if up is not None:
        if up > 0.20:
            points += 1; reasons.append(f"base-case upside of {up:.0%} provides valuation support")
        elif up < -0.05:
            points -= 2; reasons.append("the stock trades above its base-case fair value")
    dd = mom.get("drawdown_from_high")
    if dd is not None and dd < -0.4 and mom.get("above_ma50") is True:
        points += 1; reasons.append("deep drawdown with price starting to recover")

    rating = "Good Entry" if points >= 2 else "Wait" if points >= -2 else "Avoid"
    return rating, "; ".join(reasons[:4]).capitalize() + "." if reasons else "Limited timing signals available."


def confidence_level(dq_score, snap, ctype, imputed_weight):
    m = snap["metrics"]
    years = len(snap["series"].get("revenue") or [])
    reasons = []
    if dq_score < 60:
        return "Low", ["Data Quality Score below 60."]
    lows = 0
    if years < 3:
        lows += 1; reasons.append("limited public financial history")
    if (m.get("ttm_net_income") or 0) < 0:
        lows += 1; reasons.append("company is unprofitable, so value depends on uncertain assumptions")
    if imputed_weight > 15:
        lows += 1; reasons.append(f"{imputed_weight:.0f}% of the score weight lacked data and was imputed")
    if ctype in ("Biotech or Clinical-Stage Company", "Early-Stage Speculative Company"):
        lows += 1; reasons.append("outcome hinges on binary catalysts")
    if (snap["momentum"].get("volatility_annualized") or 0) > 0.6:
        lows += 1; reasons.append("earnings and price are highly volatile")
    if not snap["estimates"].get("earnings_estimate"):
        reasons.append("no forward analyst estimates available")
        lows += 0.5
    if lows >= 2:
        return "Low", reasons
    if lows >= 0.5 or dq_score < 80:
        if not reasons:
            reasons.append("some inputs rely on forward assumptions")
        return "Medium", reasons
    return "High", ["Complete financials, multi-year history, stable metrics and available estimates."]


def strengths_weaknesses(snap, factors):
    m = snap["metrics"]
    strengths, weaknesses = [], []

    def s(cond, text):
        if cond: strengths.append(text)

    def w(cond, text):
        if cond: weaknesses.append(text)

    s((m.get("rev_growth_1y") or 0) > 0.15, f"Strong revenue growth ({fmt_pct(m.get('rev_growth_1y'))} last year)")
    s((m.get("fcf_margin") or 0) > 0.15, f"Excellent free-cash-flow margin ({fmt_pct(m.get('fcf_margin'))})")
    s((m.get("gross_margin") or 0) > 0.55, f"High gross margin ({fmt_pct(m.get('gross_margin'))}) suggests pricing power")
    s((m.get("roe") or 0) > 0.20, f"High return on equity ({fmt_pct(m.get('roe'))})")
    s((m.get("roic") or 0) > 0.15, f"Strong return on invested capital ({fmt_pct(m.get('roic'))})")
    s((m.get("net_debt") or 1) < 0, f"Net cash balance sheet ({fmt_usd(-m['net_debt'])} more cash than debt)")
    s((m.get("dilution_1y") or 1) < -0.01, "Share count shrinking via buybacks")
    s((m.get("fcf_yield") or 0) > 0.05, f"Attractive FCF yield ({fmt_pct(m.get('fcf_yield'))})")
    s((m.get("dividend_yield") or 0) > 0.025 and (m.get("payout_ratio") or 1) < 0.7,
      f"Well-covered dividend ({fmt_pct(m.get('dividend_yield'))} yield)")

    w((m.get("rev_growth_1y") or 1) < 0, f"Revenue declining ({fmt_pct(m.get('rev_growth_1y'))})")
    w((m.get("ttm_fcf") or 1) < 0, "Business burns cash (negative free cash flow)")
    w((m.get("net_debt_to_ebitda") or 0) > 3, f"Elevated leverage ({fmt_x(m.get('net_debt_to_ebitda'))} net debt/EBITDA)")
    w((m.get("dilution_1y") or 0) > 0.04, f"Meaningful dilution ({fmt_pct(m.get('dilution_1y'))} share growth)")
    w((m.get("sbc_pct_revenue") or 0) > 0.08, f"Heavy stock-based compensation ({fmt_pct(m.get('sbc_pct_revenue'))} of revenue)")
    w((m.get("pe") or 0) > 45, f"Rich earnings multiple ({fmt_x(m.get('pe'))} trailing P/E)")
    w((m.get("operating_margin") or 1) < 0, "Operating losses at the current scale")
    w((m.get("current_ratio") or 2) < 1, f"Tight liquidity (current ratio {m.get('current_ratio'):.2f})" if m.get("current_ratio") else "")
    w((m.get("ocf_to_ni") or 1) < 0.7, "Earnings quality concern: cash flow lags reported income")

    # ensure at least something
    if not strengths:
        top = max(factors.values(), key=lambda f: f["score"])
        strengths.append(f"Best factor: {top['label']} (score {top['score']:.0f}/100)")
    if not weaknesses:
        bot = min(factors.values(), key=lambda f: f["score"])
        weaknesses.append(f"Weakest factor: {bot['label']} (score {bot['score']:.0f}/100)")
    return strengths[:6], [x for x in weaknesses if x][:6]


def valuation_summary(snap, valn, peer_stats):
    m = snap["metrics"]
    bits = []
    if m.get("pe"):
        bits.append(f"trades at {fmt_x(m['pe'])} trailing earnings"
                    + (f" ({fmt_x(m['forward_pe'])} forward)" if m.get("forward_pe") else ""))
    elif m.get("ps"):
        bits.append(f"trades at {fmt_x(m['ps'])} sales (not yet profitable)")
    if m.get("fcf_yield"):
        bits.append(f"a {fmt_pct(m['fcf_yield'])} free-cash-flow yield")
    prem = (peer_stats or {}).get("valuation_premium")
    if prem is not None:
        bits.append(f"{'a ' + fmt_pct(abs(prem)) + ' premium to' if prem > 0.05 else 'a ' + fmt_pct(abs(prem)) + ' discount to' if prem < -0.05 else 'roughly in line with'} peers")
    text = f"The stock {', '.join(bits)}." if bits else "Valuation data is limited."
    if valn:
        up = valn["expected_upside"]
        verdict = ("looks undervalued" if up > 0.15 else "looks roughly fairly valued"
                   if up > -0.10 else "looks expensive")
        text += (f" Against a probability-weighted fair value of ${valn['expected_value']:.2f}, "
                 f"it {verdict} ({fmt_pct(up, signed=True)} expected).")
    return text


def risk_summary(snap, flags, ctype):
    high = [f["flag"] for f in flags if f["severity"] == "High"]
    med = [f["flag"] for f in flags if f["severity"] == "Medium"]
    vol = snap["momentum"].get("volatility_annualized")
    beta = snap["metrics"].get("beta")
    parts = []
    if high:
        parts.append("Primary risks: " + "; ".join(high[:3]) + ".")
    if med:
        parts.append("Secondary concerns: " + "; ".join(med[:3]) + ".")
    if not high and not med:
        parts.append("No high-severity red flags detected in the available data.")
    if vol:
        lvl = "very high" if vol > 0.6 else "high" if vol > 0.4 else "moderate" if vol > 0.25 else "low"
        parts.append(f"Price volatility is {lvl} ({fmt_pct(vol)} annualized"
                     + (f", beta {beta:.2f}" if beta else "") + ").")
    parts.append({"Biotech or Clinical-Stage Company": "As a clinical-stage company, a single trial result can reprice the stock dramatically.",
                  "Cyclical Company": "As a cyclical business, current earnings may overstate or understate mid-cycle earning power.",
                  "Commodity or Energy Company": "Earnings are hostage to commodity prices management does not control.",
                  "Unprofitable High-Growth Company": "Until free cash flow turns positive, the company depends on capital markets remaining open.",
                  }.get(ctype, ""))
    return " ".join(p for p in parts if p)


def catalysts(snap):
    out = []
    ned = snap.get("calendar", {}).get("next_earnings_date")
    if ned:
        try:
            d = dt.date.fromisoformat(str(ned)[:10])
            days = (d - dt.date.today()).days
            out.append({"catalyst": f"Earnings report ({d.isoformat()})",
                        "direction": "Unknown",
                        "risk": "High" if 0 <= days <= 14 else "Medium",
                        "note": "Quarterly results and guidance are the most reliable near-term price mover."})
        except ValueError:
            pass
    if snap.get("calendar", {}).get("ex_dividend_date"):
        out.append({"catalyst": f"Ex-dividend date ({snap['calendar']['ex_dividend_date'][:10]})",
                    "direction": "Neutral", "risk": "Low", "note": "Matters for income investors."})
    changes = (snap["estimates"].get("recent_rating_changes") or [])[:3]
    for c in changes:
        firm = c.get("Firm") or "Analyst"
        action = (c.get("Action") or "").lower()
        to = c.get("ToGrade") or ""
        direction = "Positive" if action in ("up", "init", "reit") and to in ("Buy", "Outperform", "Overweight", "Strong Buy") \
            else "Negative" if action == "down" else "Neutral"
        out.append({"catalyst": f"{firm}: {action or 'update'} to {to or 'n/a'}",
                    "direction": direction, "risk": "Low",
                    "note": "Recent analyst rating action."})
    # headlines live in the dedicated News & Sentiment card, not here
    if not out:
        out.append({"catalyst": "No specific catalysts identified from available data",
                    "direction": "Unknown", "risk": "Medium",
                    "note": "Check the company's IR page for investor days and product events."})
    return out


MACRO_MAP = {
    "Technology": [("Interest rates", "hurt", "Long-duration cash flows are discounted harder when rates rise."),
                   ("AI/data-center capex", "help", "Enterprise AI budgets are a demand tailwind for much of the sector."),
                   ("Currency movements", "mixed", "Large overseas revenue exposes results to a strong dollar.")],
    "Consumer Cyclical": [("Consumer spending", "hurt", "Discretionary demand falls first in a slowdown."),
                          ("Recession risk", "hurt", "Highly sensitive to the economic cycle."),
                          ("Labor costs", "hurt", "Wage inflation squeezes retail/service margins.")],
    "Consumer Defensive": [("Inflation", "mixed", "Input costs rise but staples can pass prices through."),
                           ("Recession risk", "help", "Defensive demand holds up in downturns.")],
    "Financial Services": [("Interest rates", "mixed", "Higher rates lift net interest margins but raise credit losses."),
                           ("Credit markets", "hurt", "Widening spreads and defaults hit loan books."),
                           ("Recession risk", "hurt", "Charge-offs climb in downturns.")],
    "Healthcare": [("Government regulation", "hurt", "Drug-pricing policy and approval timelines drive outcomes."),
                   ("Recession risk", "help", "Healthcare demand is largely non-discretionary.")],
    "Energy": [("Commodity prices", "mixed", "Oil and gas prices dominate earnings in both directions."),
               ("Geopolitical risk", "mixed", "Supply shocks can spike or crush realized prices."),
               ("Interest rates", "hurt", "Capital-intensive projects cost more to finance.")],
    "Industrials": [("Recession risk", "hurt", "Orders are tied to capex cycles."),
                    ("Supply chain disruption", "hurt", "Component shortages delay deliveries."),
                    ("Government regulation", "mixed", "Infrastructure and defense budgets can be tailwinds.")],
    "Utilities": [("Interest rates", "hurt", "Bond-proxy valuations compress when yields rise."),
                  ("Government regulation", "mixed", "Allowed returns are set by regulators.")],
    "Real Estate": [("Interest rates", "hurt", "Cap rates and refinancing costs track rates."),
                    ("Housing market conditions", "mixed", "Occupancy and rents follow the property cycle.")],
    "Basic Materials": [("Commodity prices", "mixed", "Realized prices drive margins directly."),
                        ("Recession risk", "hurt", "Volumes fall with industrial activity.")],
    "Communication Services": [("Consumer spending", "hurt", "Advertising budgets are cyclical."),
                               ("Interest rates", "hurt", "Growth valuations compress with higher rates.")],
}


def macro_sensitivity(snap):
    sector = snap.get("sector")
    rows = [{"factor": f, "direction": d, "note": n}
            for f, d, n in MACRO_MAP.get(sector or "", [])]
    m = snap["metrics"]
    if (m.get("net_debt_to_ebitda") or 0) > 2.5:
        rows.append({"factor": "Interest rates (leverage)", "direction": "hurt",
                     "note": "Elevated debt means refinancing at higher rates directly cuts earnings."})
    if (m.get("beta") or 1) > 1.4:
        rows.append({"factor": "Overall market risk", "direction": "hurt",
                     "note": f"Beta of {m['beta']:.1f}: the stock amplifies market swings."})
    if not rows:
        rows.append({"factor": "General macro", "direction": "mixed",
                     "note": "No sector mapping available; treat macro exposure as average."})
    helps = [r["factor"] for r in rows if r["direction"] == "help"]
    hurts = [r["factor"] for r in rows if r["direction"] == "hurt"]
    summary = ""
    if hurts:
        summary += "Most exposed to: " + ", ".join(hurts[:3]) + ". "
    if helps:
        summary += "Potential tailwinds: " + ", ".join(helps[:2]) + "."
    return {"rows": rows, "summary": summary or "Macro exposure appears average."}


def what_would_change(snap, ctype, rating, m=None):
    m = m or snap["metrics"]
    growing = (m.get("rev_growth_1y") or 0) > 0.05
    profitable = (m.get("ttm_fcf") or 0) > 0
    upgrade, downgrade = [], []
    upgrade.append("Revenue growth accelerates versus the last reported year"
                   if growing else "Revenue returns to sustained growth")
    upgrade.append("Free cash flow margin expands" if profitable
                   else "Free cash flow turns positive")
    upgrade.append("Valuation multiple compresses to leave 25%+ base-case upside")
    upgrade.append("Estimate revisions turn positive and guidance is raised")
    downgrade.append("Revenue growth decelerates for two consecutive quarters")
    downgrade.append("Gross or operating margins contract")
    downgrade.append("Leverage rises or dilution accelerates")
    downgrade.append("Management cuts guidance or misses estimates")
    return {
        "upgrade_if": upgrade,
        "downgrade_if": downgrade,
        "sell_if": ["Free cash flow deteriorates while debt grows",
                    "Accounting red flags multiply (receivables/inventory outrunning sales)",
                    "The valuation premium expands without fundamental improvement"],
        "strong_buy_if": ["Fundamentals hold while the price falls to leave 30%+ base-case upside",
                          "Growth re-accelerates with expanding margins and positive revisions"],
        "monitor_metrics": ["Revenue growth", "Gross margin", "Free cash flow",
                            "Share count", "Guidance vs. consensus"],
        "monitor_risks": [f["flag"] for f in snap.get("_flags", [])][:4] or ["Valuation", "Execution"],
        "monitor_catalysts": ["Next earnings report", "Analyst estimate revisions"],
    }


def why_wrong(snap, ctype, rating, score):
    reasons = []
    m = snap["metrics"]
    bullish = score >= 70
    if bullish:
        reasons.append("The model may be too bullish if recent growth or margins prove unsustainable — "
                       "trailing numbers can flatter a business at a cyclical or product-cycle peak.")
        reasons.append("Analyst estimates feed the forward score; if estimates are stale or too optimistic, "
                       "the rating inherits that error.")
    else:
        reasons.append("The model may be too bearish if the company is deliberately depressing current "
                       "profits to invest in growth — heavy R&D and expansion spending look like "
                       "weakness in the numbers but can create long-term value.")
        reasons.append("A major upcoming catalyst (product launch, approval, contract) is not fully "
                       "visible in historical financials and could reprice the stock.")
    reasons.append("Quantitative scores cannot fully capture qualitative edges: brand, engineering "
                   "culture, network effects, or a founder with skin in the game.")
    if ctype in ("Cyclical Company", "Commodity or Energy Company"):
        reasons.append("Cycle timing dominates: the model normalizes imperfectly, and a turn in the "
                       "cycle would swamp every other factor.")
    if (m.get("ttm_net_income") or 0) < 0:
        reasons.append("For unprofitable companies, small changes in growth/margin assumptions move "
                       "fair value enormously — the error bars are wide.")
    reasons.append("Regulatory, legal and geopolitical shocks are outside the dataset entirely.")
    return reasons


def final_explanation(snap, rating, score, confidence, ctype, timing, valn, flags):
    m = snap["metrics"]
    name = snap["name"]
    lines = [f"{name} scores {score:.0f}/100, which maps to a {rating} rating with {confidence} confidence."]
    g = m.get("rev_growth_1y")
    prof = (m.get("ttm_fcf") or 0) > 0
    lines.append(f"It is classified as a {ctype.lower()}"
                 + (f" growing revenue at {fmt_pct(g)}" if g is not None else "")
                 + (" while generating positive free cash flow." if prof
                    else " but it does not yet generate free cash flow."))
    if valn:
        lines.append(f"The probability-weighted fair value estimate is ${valn['expected_value']:.2f} "
                     f"({fmt_pct(valn['expected_upside'], signed=True)} vs. the current price), with a "
                     f"bear-to-bull range of ${valn['fair_value_range'][0]:.2f}–${valn['fair_value_range'][1]:.2f}.")
    high_flags = [f["flag"] for f in flags if f["severity"] == "High"]
    if high_flags:
        lines.append("The rating is held back by: " + "; ".join(high_flags[:3]) + ".")
    lines.append(f"Entry timing: {timing[0]} — {timing[1]}")
    return " ".join(lines)
