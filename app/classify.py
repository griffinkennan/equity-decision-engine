"""Company type classification — determines which scoring emphasis applies."""
from __future__ import annotations

TYPES = [
    "Mature Profitable Company", "High-Growth Company",
    "Unprofitable High-Growth Company", "Turnaround Company",
    "Cyclical Company", "Bank or Financial Company", "REIT",
    "Biotech or Clinical-Stage Company", "Commodity or Energy Company",
    "Early-Stage Speculative Company",
]

CYCLICAL_INDUSTRIES = ("auto", "airline", "semiconductor", "steel", "chemical",
                       "homebuild", "machinery", "shipping", "aluminum", "paper",
                       "travel", "lodging", "cruise")


def classify(snap: dict) -> dict:
    m, s = snap["metrics"], snap["series"]
    sector = (snap.get("sector") or "").lower()
    industry = (snap.get("industry") or "").lower()
    rev = m.get("ttm_revenue")
    ni = m.get("ttm_net_income")
    fcf = m.get("ttm_fcf")
    growth = m.get("rev_growth_1y")
    years = len(s.get("revenue") or [])
    reasons = []

    def result(ctype, why):
        reasons.append(why)
        return {"type": ctype, "reasons": reasons}

    if "reit" in industry or "reit" in sector:
        return result("REIT", "Classified in a REIT industry; FFO/dividend metrics matter more than EPS.")
    if sector == "financial services" or any(k in industry for k in ("bank", "insurance", "capital markets", "credit")):
        return result("Bank or Financial Company",
                      "Financial-sector company; ROE, book value and credit quality matter more than EBITDA/FCF.")
    if "biotech" in industry or ("healthcare" in sector and (rev is None or rev < 100e6) and (ni or 0) < 0):
        return result("Biotech or Clinical-Stage Company",
                      "Biotech / pre-revenue healthcare; cash runway and pipeline catalysts dominate.")
    if sector in ("energy", "basic materials") or any(k in industry for k in ("oil", "gas", "mining", "gold", "coal")):
        return result("Commodity or Energy Company",
                      "Commodity-linked business; earnings must be judged across the price cycle.")
    if rev is not None and rev < 50e6 and (ni or -1) < 0:
        return result("Early-Stage Speculative Company",
                      "Minimal revenue and no profits; outcome depends on execution, not current financials.")

    profitable = (ni or 0) > 0 and (fcf if fcf is not None else ni or 0) > 0
    high_growth = (growth or 0) > 0.20 or (m.get("rev_cagr_3y") or 0) > 0.20

    if not profitable and high_growth:
        return result("Unprofitable High-Growth Company",
                      "Revenue growing >20% but not yet profitable; judged on growth quality, burn and runway.")
    # turnaround: revenue declined recently but margins/FCF improving
    if (growth or 0) < -0.05 or ((m.get("ni_growth") or 0) < -0.30 and (growth or 0) < 0.02):
        return result("Turnaround Company",
                      "Revenue or earnings recently declined materially; judged on stabilization evidence.")
    if any(k in industry for k in CYCLICAL_INDUSTRIES):
        return result("Cyclical Company",
                      "Industry with pronounced demand cycles; earnings normalized across the cycle.")
    if high_growth and profitable:
        return result("High-Growth Company",
                      "Revenue growing >20% with profits; valuation judged relative to growth.")
    if not profitable:
        return result("Turnaround Company",
                      "Currently unprofitable with modest growth; treated as a show-me story.")
    if years < 3:
        reasons.append("Limited public history (<3 years) lowers confidence.")
    return result("Mature Profitable Company",
                  "Established, profitable business; earnings, FCF, valuation and capital returns dominate.")


def type_weight_adjustments(ctype: str) -> dict:
    """Multiplicative emphasis per factor; weights are re-normalized to 100 after."""
    base = {k: 1.0 for k in ("revenue_growth", "earnings_growth", "fcf", "profitability",
                             "balance_sheet", "valuation", "industry", "forward",
                             "shareholder", "management", "moat", "momentum", "sentiment")}
    adj = {
        "High-Growth Company": {"revenue_growth": 1.6, "forward": 1.4, "valuation": 1.1,
                                "earnings_growth": 0.8, "profitability": 0.8},
        "Unprofitable High-Growth Company": {"revenue_growth": 1.8, "balance_sheet": 1.4,
                                             "forward": 1.5, "earnings_growth": 0.4,
                                             "profitability": 0.6, "shareholder": 1.3},
        "Turnaround Company": {"balance_sheet": 1.6, "fcf": 1.3, "management": 1.3,
                               "revenue_growth": 0.8, "momentum": 1.2},
        "Cyclical Company": {"balance_sheet": 1.3, "valuation": 1.2, "earnings_growth": 0.7},
        "Bank or Financial Company": {"fcf": 0.3, "profitability": 1.6, "balance_sheet": 1.5,
                                      "valuation": 1.2},
        "REIT": {"fcf": 1.3, "shareholder": 1.5, "balance_sheet": 1.4,
                 "earnings_growth": 0.6, "revenue_growth": 0.8},
        "Biotech or Clinical-Stage Company": {"balance_sheet": 1.8, "forward": 1.6,
                                              "earnings_growth": 0.2, "profitability": 0.3,
                                              "fcf": 0.5, "revenue_growth": 0.7,
                                              "sentiment": 1.3},
        "Commodity or Energy Company": {"balance_sheet": 1.4, "fcf": 1.3, "valuation": 1.2,
                                        "earnings_growth": 0.6},
        "Early-Stage Speculative Company": {"balance_sheet": 1.8, "forward": 1.4,
                                            "earnings_growth": 0.3, "profitability": 0.4,
                                            "shareholder": 1.4, "sentiment": 1.3},
    }
    mults = adj.get(ctype, {})
    return {k: base[k] * mults.get(k, 1.0) for k in base}
