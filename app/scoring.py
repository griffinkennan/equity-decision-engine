"""The 0-100 investment scoring engine.

Each factor scorer returns (score_0_100, [detail rows]). Detail rows expose the
exact metric, value, threshold logic and contribution so the UI can show *why*.
Weights follow the spec and are re-normalized after company-type emphasis.
"""
from __future__ import annotations

from .classify import type_weight_adjustments

BASE_WEIGHTS = {
    "revenue_growth": 8, "earnings_growth": 8, "fcf": 12, "profitability": 10,
    "balance_sheet": 12, "valuation": 15, "industry": 8, "forward": 7,
    "shareholder": 5, "management": 5, "moat": 5, "momentum": 5,
    "sentiment": 4,  # news + market/industry regime — a tilt, never a driver
}
FACTOR_LABELS = {
    "revenue_growth": "Revenue Growth", "earnings_growth": "Earnings Growth",
    "fcf": "Free Cash Flow", "profitability": "Profitability",
    "balance_sheet": "Balance Sheet", "valuation": "Valuation",
    "industry": "Industry-Relative", "forward": "Forward Outlook",
    "shareholder": "Shareholder Quality", "management": "Management Quality",
    "moat": "Moat / Business Quality", "momentum": "Momentum & Timing",
    "sentiment": "News & Sentiment",
}


def scale(value, bands):
    """Map value onto [(threshold, score)...] sorted best-first. None -> None."""
    if value is None:
        return None
    for threshold, score in bands:
        if value >= threshold:
            return score
    return bands[-1][1]


def scale_low(value, bands):
    """Like scale() but lower is better: bands sorted ascending threshold."""
    if value is None:
        return None
    for threshold, score in bands:
        if value <= threshold:
            return score
    return bands[-1][1]


class Factor:
    def __init__(self):
        self.rows = []

    def add(self, metric, value, score, weight=1.0, note="", fmt="pct"):
        if score is not None:
            self.rows.append({"metric": metric, "value": value, "score": round(score, 1),
                              "weight": weight, "note": note, "format": fmt})

    def result(self, default=50.0):
        if not self.rows:
            return default, [], True   # True = imputed (no data)
        tw = sum(r["weight"] for r in self.rows)
        score = sum(r["score"] * r["weight"] for r in self.rows) / tw
        return round(score, 1), self.rows, False


def score_revenue_growth(m, ctype):
    f = Factor()
    g = [(0.30, 95), (0.20, 85), (0.12, 72), (0.06, 60), (0.02, 48), (0.0, 40), (-0.05, 28), (-1, 12)]
    f.add("Revenue growth (1y)", m.get("rev_growth_1y"), scale(m.get("rev_growth_1y"), g), 1.2)
    f.add("Revenue CAGR (3y)", m.get("rev_cagr_3y"), scale(m.get("rev_cagr_3y"), g), 1.0)
    f.add("Revenue CAGR (5y)", m.get("rev_cagr_5y"), scale(m.get("rev_cagr_5y"), g), 0.7)
    cur, prior = m.get("rev_growth_1y"), m.get("rev_growth_prior")
    if cur is not None and prior is not None:
        accel = cur - prior
        f.add("Growth acceleration (1y vs prior)", accel,
              scale(accel, [(0.05, 85), (0.0, 65), (-0.05, 45), (-1, 25)]), 0.6,
              "Accelerating growth scores higher than decelerating.")
    return f.result()


def score_earnings_growth(m, ctype):
    f = Factor()
    g = [(0.25, 92), (0.15, 80), (0.08, 66), (0.02, 55), (0.0, 45), (-0.10, 32), (-1, 15)]
    f.add("EPS growth", m.get("eps_growth"), scale(m.get("eps_growth"), g), 1.1)
    f.add("Net income growth", m.get("ni_growth"), scale(m.get("ni_growth"), g), 1.0)
    f.add("EBITDA growth", m.get("ebitda_growth"), scale(m.get("ebitda_growth"), g), 0.8)
    f.add("Operating income growth", m.get("opinc_growth"), scale(m.get("opinc_growth"), g), 0.8)
    if (m.get("ttm_net_income") or 0) < 0:
        f.add("Currently unprofitable", None if m.get("ttm_net_income") is None else 1,
              30 if ctype not in ("Unprofitable High-Growth Company",
                                  "Biotech or Clinical-Stage Company") else 45,
              0.8, "Negative net income; weight of this factor is reduced for growth/biotech types.", "flag")
    return f.result()


def score_fcf(m, ctype):
    f = Factor()
    fcf = m.get("ttm_fcf")
    if fcf is not None:
        if fcf > 0:
            f.add("FCF margin", m.get("fcf_margin"),
                  scale(m.get("fcf_margin"), [(0.25, 95), (0.15, 82), (0.08, 68), (0.03, 55), (0.0, 45)]), 1.2)
            f.add("FCF yield", m.get("fcf_yield"),
                  scale(m.get("fcf_yield"), [(0.07, 92), (0.05, 80), (0.03, 62), (0.015, 50), (0.0, 38)]), 1.0)
            f.add("FCF growth", m.get("fcf_growth"),
                  scale(m.get("fcf_growth"), [(0.20, 90), (0.08, 75), (0.0, 58), (-0.15, 40), (-1, 25)]), 0.8)
            f.add("Cash conversion (FCF / net income)", m.get("fcf_to_ni"),
                  scale(m.get("fcf_to_ni"), [(0.9, 88), (0.7, 70), (0.5, 55), (0.0, 38)]), 0.7,
                  "FCF near or above net income indicates high-quality earnings.")
        else:
            runway = m.get("cash_runway_years")
            base = 25
            if ctype in ("Unprofitable High-Growth Company", "Biotech or Clinical-Stage Company",
                         "Early-Stage Speculative Company"):
                base = 40 if (runway or 0) >= 2 else 22
            f.add("Free cash flow negative", fcf, base, 1.5,
                  "Negative FCF penalized unless growth + runway justify the burn.", "usd")
            if runway is not None:
                f.add("Cash runway (years at current burn)", runway,
                      scale(runway, [(4, 85), (2.5, 68), (1.5, 45), (0.75, 25), (0, 10)]), 1.2,
                      "", "x")
    f.add("Operating cash flow positive", m.get("ttm_ocf"),
          70 if (m.get("ttm_ocf") or 0) > 0 else 25, 0.6, "", "usd")
    return f.result()


def score_profitability(m, ctype, ss=None):
    f = Factor()
    ss = ss or {}
    if ctype == "Bank or Financial Company":
        if ss.get("nim_proxy") is not None:
            f.add("Net interest margin (NII / assets)", ss["nim_proxy"],
                  scale(ss["nim_proxy"], [(0.035, 90), (0.028, 75), (0.02, 60), (0.012, 45), (0, 30)]), 1.2,
                  "Approximated as net interest income over total assets.")
        if ss.get("nii_growth") is not None:
            f.add("Net interest income growth", ss["nii_growth"],
                  scale(ss["nii_growth"], [(0.10, 85), (0.04, 70), (0.0, 55), (-0.05, 40), (-1, 25)]), 0.9)
        if ss.get("efficiency_ratio") is not None:
            f.add("Efficiency ratio (opex / revenue, approx.)", ss["efficiency_ratio"],
                  scale_low(ss["efficiency_ratio"], [(0.50, 88), (0.60, 72), (0.70, 55), (0.85, 38), (9, 22)]), 0.8,
                  "Lower is better; approximated from SG&A.")
    f.add("Gross margin", m.get("gross_margin"),
          scale(m.get("gross_margin"), [(0.60, 92), (0.45, 78), (0.30, 62), (0.18, 48), (0.0, 35)]), 0.9)
    f.add("Operating margin", m.get("operating_margin"),
          scale(m.get("operating_margin"), [(0.25, 92), (0.15, 78), (0.08, 62), (0.02, 48), (0.0, 40), (-1, 20)]), 1.1)
    f.add("Net margin", m.get("net_margin"),
          scale(m.get("net_margin"), [(0.20, 92), (0.12, 78), (0.06, 62), (0.01, 48), (-1, 25)]), 1.0)
    f.add("Return on equity", m.get("roe"),
          scale(m.get("roe"), [(0.25, 92), (0.15, 78), (0.10, 64), (0.05, 50), (0.0, 38), (-1, 22)]), 1.0)
    f.add("Return on assets", m.get("roa"),
          scale(m.get("roa"), [(0.12, 90), (0.07, 75), (0.04, 60), (0.01, 45), (-1, 25)]), 0.7)
    f.add("ROIC (EBIT / invested capital)", m.get("roic"),
          scale(m.get("roic"), [(0.20, 92), (0.12, 78), (0.08, 62), (0.04, 48), (-1, 28)]), 0.9)
    return f.result()


def score_balance_sheet(m, ctype):
    f = Factor()
    f.add("Current ratio", m.get("current_ratio"),
          scale(m.get("current_ratio"), [(2.0, 88), (1.5, 75), (1.2, 62), (1.0, 48), (0.8, 32), (0, 15)]), 0.9, "", "x")
    de = m.get("debt_to_equity")
    if de is not None and de < 0:
        f.add("Negative shareholder equity", de, 15, 1.2,
              "Liabilities exceed assets — a structural balance-sheet risk.", "x")
    else:
        f.add("Debt / equity", de,
              scale_low(de, [(0.3, 90), (0.7, 75), (1.2, 60), (2.0, 42), (3.5, 25), (99, 12)]), 1.0, "", "x")
    nde = m.get("net_debt_to_ebitda")
    if nde is not None:
        f.add("Net debt / EBITDA", nde,
              scale_low(nde, [(0.0, 92), (1.0, 82), (2.0, 68), (3.0, 52), (4.5, 32), (99, 15)]), 1.2, "", "x")
    f.add("Interest coverage (EBIT / interest)", m.get("interest_coverage"),
          scale(m.get("interest_coverage"), [(12, 90), (7, 78), (4, 60), (2, 40), (-99, 18)]), 0.9, "", "x")
    if m.get("cash_runway_years") is not None:
        f.add("Cash runway", m.get("cash_runway_years"),
              scale(m.get("cash_runway_years"), [(4, 85), (2.5, 65), (1.5, 42), (0, 15)]), 1.3, "", "x")
    nd = m.get("net_debt")
    if nd is not None and nd < 0:
        f.add("Net cash position", nd, 90, 0.8, "More cash than debt.", "usd")
    return f.result()


# Typical sector multiples used to normalize valuation before banding, so a
# utility and a software company are judged against their own sector's norms.
# Calibrated to long-run US sector medians (approximate; part of model v1.1.0).
SECTOR_NORMS = {
    "Technology": {"pe": 28, "ev_ebitda": 18},
    "Communication Services": {"pe": 20, "ev_ebitda": 11},
    "Consumer Cyclical": {"pe": 22, "ev_ebitda": 13},
    "Consumer Defensive": {"pe": 21, "ev_ebitda": 14},
    "Healthcare": {"pe": 22, "ev_ebitda": 14},
    "Financial Services": {"pe": 13, "ev_ebitda": None},
    "Industrials": {"pe": 21, "ev_ebitda": 12},
    "Energy": {"pe": 12, "ev_ebitda": 6},
    "Utilities": {"pe": 18, "ev_ebitda": 11},
    "Real Estate": {"pe": 30, "ev_ebitda": 16},
    "Basic Materials": {"pe": 15, "ev_ebitda": 8},
}
VALUATION_BASELINE = {"pe": 19, "ev_ebitda": 12}


def _sector_adjust(value, key, sector):
    """Rescale a multiple onto the market baseline using the sector norm."""
    norm = (SECTOR_NORMS.get(sector or "") or {}).get(key)
    if value is None or not norm:
        return value, ""
    adj = value * VALUATION_BASELINE[key] / norm
    return adj, f"Sector-adjusted: raw {value:.1f}x vs {sector} norm ~{norm}x."


def score_valuation(m, ctype, peer_stats=None, sector=None, ss=None):
    f = Factor()
    pe_adj, pe_note = _sector_adjust(m.get("pe"), "pe", sector)
    f.add("P/E (trailing)", pe_adj,
          scale_low(pe_adj, [(12, 88), (18, 75), (25, 62), (35, 48), (50, 32), (9999, 18)]), 0.9, pe_note, "x")
    fpe_adj, fpe_note = _sector_adjust(m.get("forward_pe"), "pe", sector)
    f.add("Forward P/E", fpe_adj,
          scale_low(fpe_adj, [(12, 90), (18, 78), (25, 64), (35, 48), (50, 32), (9999, 18)]), 1.0, fpe_note, "x")
    ev_adj, ev_note = _sector_adjust(m.get("ev_ebitda"), "ev_ebitda", sector)
    f.add("EV / EBITDA", ev_adj,
          scale_low(ev_adj, [(8, 88), (12, 74), (16, 60), (22, 45), (30, 30), (9999, 16)]), 0.9, ev_note, "x")
    ss = ss or {}
    if ctype == "REIT" and ss.get("p_ffo") is not None:
        f.add("Price / FFO", ss["p_ffo"],
              scale_low(ss["p_ffo"], [(12, 88), (16, 72), (20, 55), (26, 38), (999, 22)]), 1.3,
              "FFO (net income + D&A) is the REIT earnings measure; P/FFO replaces P/E emphasis.", "x")
    if ctype == "Bank or Financial Company" and ss.get("p_tangible_book") is not None:
        f.add("Price / tangible book", ss["p_tangible_book"],
              scale_low(ss["p_tangible_book"], [(1.0, 88), (1.5, 72), (2.2, 55), (3.5, 38), (99, 22)]), 1.2,
              "Tangible book value is the anchor valuation metric for banks.", "x")
    # P/S judged relative to growth
    ps, g = m.get("ps"), m.get("rev_growth_1y")
    if ps is not None:
        allowance = 2 + max(0.0, (g or 0)) * 25  # 20% grower "deserves" ~7x
        rel = ps / allowance
        f.add("P/S vs growth-justified level", rel,
              scale_low(rel, [(0.6, 88), (1.0, 70), (1.5, 52), (2.5, 34), (99, 15)]), 1.0,
              f"P/S {ps:.1f}x vs ~{allowance:.1f}x justified by growth.", "x")
    f.add("PEG ratio", m.get("peg"),
          scale_low(m.get("peg"), [(1.0, 88), (1.5, 72), (2.0, 58), (3.0, 42), (99, 25)]), 0.8, "", "x")
    f.add("FCF yield", m.get("fcf_yield"),
          scale(m.get("fcf_yield"), [(0.06, 90), (0.04, 75), (0.025, 60), (0.01, 45), (-99, 28)]), 1.0)
    if ctype in ("Bank or Financial Company", "REIT"):
        f.add("Price / book", m.get("pb"),
              scale_low(m.get("pb"), [(1.0, 88), (1.5, 72), (2.5, 55), (4.0, 38), (99, 22)]), 1.2, "", "x")
    vh = m.get("valuation_history") or {}
    for key, label in (("pe", "P/E"), ("ps", "P/S")):
        pct = vh.get(key + "_percentile")
        if pct is not None:
            lo, hi = vh.get(key + "_range", [None, None])
            f.add(f"{label} vs own {vh.get('years', 0)}-year history", pct,
                  scale_low(pct, [(0.25, 88), (0.45, 72), (0.65, 58), (0.85, 42), (1.01, 25)]), 0.8,
                  f"Current {label} sits at the {pct:.0%} percentile of its historical "
                  f"range ({lo}–{hi}). Lower percentile = cheaper vs its own past.", "x")
            break  # score whichever multiple is available first, P/E preferred
    if peer_stats and peer_stats.get("valuation_premium") is not None:
        prem = peer_stats["valuation_premium"]
        f.add("Valuation premium vs peers", prem,
              scale_low(prem, [(-0.2, 85), (0.0, 70), (0.25, 55), (0.6, 38), (99, 22)]), 0.9,
              "Blended multiple vs peer median.")
    return f.result()


def score_industry(peer_comparison, m):
    """Score from the peer comparison table: fraction of metrics where company beats peer median."""
    f = Factor()
    if not peer_comparison or not peer_comparison.get("rows"):
        return f.result()  # imputed 50
    wins, total = 0, 0
    for row in peer_comparison["rows"]:
        if row.get("company") is None or row.get("peer_median") is None:
            continue
        total += 1
        if row.get("better") is True:
            wins += 1
    if total >= 4:
        ratio = wins / total
        f.add(f"Beats peer median on {wins}/{total} metrics", ratio,
              scale(ratio, [(0.75, 90), (0.6, 75), (0.45, 60), (0.3, 45), (0, 28)]), 1.0, "", "x")
    return f.result()


def score_forward(est, m, ctype):
    f = Factor()
    ee = (est.get("earnings_estimate") or {}).get("+1y") or {}
    re_ = (est.get("revenue_estimate") or {}).get("+1y") or {}
    fwd_rev_g = re_.get("growth")
    fwd_eps_g = ee.get("growth")
    f.add("Forward revenue growth (next FY)", fwd_rev_g,
          scale(fwd_rev_g, [(0.20, 90), (0.10, 75), (0.05, 62), (0.0, 48), (-1, 30)]), 1.1)
    f.add("Forward EPS growth (next FY)", fwd_eps_g,
          scale(fwd_eps_g, [(0.20, 90), (0.10, 75), (0.05, 62), (0.0, 48), (-1, 30)]), 1.1)
    revs = est.get("eps_revisions_90d") or {}
    rev90 = revs.get("+1y", revs.get("0y"))
    if rev90 is not None:
        f.add("EPS estimate revision (90 days)", rev90,
              scale(rev90, [(0.05, 90), (0.015, 76), (-0.015, 58), (-0.05, 40), (-1, 24)]), 1.2,
              "Direction analysts have moved next-year consensus EPS over the last "
              "quarter — upward revisions are one of the better-documented signals.")
    pt = est.get("price_targets") or {}
    if pt.get("mean") and pt.get("current"):
        upside = pt["mean"] / pt["current"] - 1
        f.add("Analyst target upside (mean)", upside,
              scale(upside, [(0.30, 88), (0.15, 74), (0.05, 60), (-0.05, 45), (-1, 28)]), 0.9)
    br = est.get("eps_beat_rate")
    f.add("EPS beat rate (last 4 quarters)", br,
          scale(br, [(0.99, 85), (0.74, 72), (0.49, 55), (0.0, 35)]), 0.7,
          "Track record of meeting analyst estimates.")
    return f.result()


def score_shareholder(m, holders, ctype=None, ss=None):
    f = Factor()
    ss = ss or {}
    if ctype == "REIT" and ss.get("ffo_payout") is not None:
        f.add("Dividend coverage (payout / FFO)", ss["ffo_payout"],
              scale_low(ss["ffo_payout"], [(0.7, 88), (0.8, 72), (0.9, 55), (1.0, 35), (99, 15)]), 1.3,
              "REIT dividend safety judged against FFO, not EPS.")
    dil = m.get("dilution_1y")
    f.add("Share count change (1y)", dil,
          scale_low(dil, [(-0.03, 92), (0.0, 78), (0.02, 60), (0.05, 42), (0.12, 25), (99, 12)]), 1.2,
          "Negative = buybacks shrinking share count.")
    f.add("SBC as % of revenue", m.get("sbc_pct_revenue"),
          scale_low(m.get("sbc_pct_revenue"), [(0.02, 88), (0.05, 70), (0.10, 50), (0.20, 30), (99, 15)]), 1.0)
    f.add("Insider ownership", holders.get("insider_pct"),
          scale(holders.get("insider_pct"), [(0.10, 85), (0.03, 68), (0.005, 52), (0, 42)]), 0.7)
    buys, sells = holders.get("insider_buys"), holders.get("insider_sells")
    if buys is not None and sells is not None and buys + sells > 0:
        ratio = buys / (buys + sells)
        f.add("Insider buy ratio (12m transactions)", ratio,
              scale(ratio, [(0.6, 85), (0.35, 65), (0.15, 48), (0, 35)]), 0.8,
              f"{buys} buys vs {sells} sells in the last year.")
    if (m.get("buybacks_ttm") or 0) < 0:
        f.add("Active buyback program", m.get("buybacks_ttm"), 80, 0.6, "", "usd")
    dy, payout = m.get("dividend_yield"), m.get("payout_ratio")
    if dy and dy > 0.005 and payout is not None:
        f.add("Dividend payout ratio", payout,
              scale_low(payout, [(0.4, 88), (0.6, 72), (0.8, 52), (1.0, 32), (99, 15)]), 0.7,
              "Sustainability of the dividend.")
    return f.result()


def score_management(m, holders, est):
    f = Factor()
    f.add("ROIC (capital allocation outcome)", m.get("roic"),
          scale(m.get("roic"), [(0.18, 90), (0.11, 75), (0.06, 58), (0.02, 42), (-1, 25)]), 1.1)
    f.add("Dilution discipline (3y share CAGR)", m.get("dilution_3y"),
          scale_low(m.get("dilution_3y"), [(-0.02, 90), (0.005, 75), (0.03, 55), (0.08, 35), (99, 15)]), 1.0)
    f.add("Guidance execution (EPS beat rate)", est.get("eps_beat_rate"),
          scale(est.get("eps_beat_rate"), [(0.99, 88), (0.74, 74), (0.49, 55), (0.0, 32)]), 0.9)
    f.add("Insider ownership (alignment)", holders.get("insider_pct"),
          scale(holders.get("insider_pct"), [(0.10, 85), (0.03, 66), (0.005, 52), (0, 42)]), 0.7)
    de = m.get("debt_to_equity")
    if de is not None and de >= 0:
        f.add("Debt management (D/E)", de,
              scale_low(de, [(0.5, 85), (1.0, 70), (2.0, 50), (99, 28)]), 0.7, "", "x")
    return f.result()


def score_moat(m, snap):
    """Quantitative moat proxies: margins, returns, scale, consistency."""
    f = Factor()
    f.add("Gross margin (pricing power proxy)", m.get("gross_margin"),
          scale(m.get("gross_margin"), [(0.60, 90), (0.45, 75), (0.30, 58), (0.15, 42), (0, 30)]), 1.0)
    f.add("ROIC persistence proxy", m.get("roic"),
          scale(m.get("roic"), [(0.18, 92), (0.11, 76), (0.06, 58), (0.0, 40), (-1, 25)]), 1.1,
          "Sustained high returns on capital usually indicate a moat.")
    f.add("Operating margin vs 10% baseline", m.get("operating_margin"),
          scale(m.get("operating_margin"), [(0.25, 88), (0.15, 72), (0.08, 55), (0.0, 40), (-1, 25)]), 0.9)
    mcap = m.get("market_cap")
    f.add("Scale advantage (market cap)", mcap,
          scale(mcap, [(200e9, 85), (20e9, 72), (2e9, 58), (300e6, 45), (0, 35)]), 0.6, "", "usd")
    rev = snap["series"].get("revenue") or []
    if len(rev) >= 4:
        growth_years = sum(1 for i in range(1, len(rev)) if rev[i]["value"] > rev[i - 1]["value"])
        consistency = growth_years / (len(rev) - 1)
        f.add("Revenue consistency (years growing)", consistency,
              scale(consistency, [(0.99, 88), (0.74, 72), (0.5, 55), (0, 38)]), 0.8)
    return f.result()


def moat_class(moat_score):
    if moat_score >= 72:
        return "Strong"
    if moat_score >= 52:
        return "Moderate"
    return "Weak"


def score_momentum(mom, calendar):
    f = Factor()
    f.add("Price vs 200-day MA", 1 if mom.get("above_ma200") else 0,
          None if mom.get("above_ma200") is None else (75 if mom["above_ma200"] else 32), 1.2,
          "Above the 200-day average = established uptrend.", "flag")
    f.add("Price vs 50-day MA", 1 if mom.get("above_ma50") else 0,
          None if mom.get("above_ma50") is None else (70 if mom["above_ma50"] else 40), 0.8, "", "flag")
    f.add("12-month performance", mom.get("perf_12m"),
          scale(mom.get("perf_12m"), [(0.30, 85), (0.10, 70), (0.0, 55), (-0.15, 40), (-1, 22)]), 0.9)
    f.add("Relative strength vs S&P 500 (12m)", mom.get("rel_spy_12m"),
          scale(mom.get("rel_spy_12m"), [(0.15, 85), (0.0, 65), (-0.10, 48), (-1, 28)]), 1.0)
    if mom.get("rel_sector_12m") is not None:
        f.add(f"Relative strength vs sector ETF ({mom.get('sector_etf')}, 12m)",
              mom.get("rel_sector_12m"),
              scale(mom.get("rel_sector_12m"), [(0.12, 84), (0.0, 64), (-0.10, 46), (-1, 28)]), 0.8,
              "Separates stock-specific weakness from sector-wide weakness.")
    f.add("Drawdown from 52-week high", mom.get("drawdown_from_high"),
          scale(mom.get("drawdown_from_high"), [(-0.05, 80), (-0.15, 65), (-0.30, 48), (-0.5, 32), (-1, 20)]), 0.7)
    f.add("Annualized volatility", mom.get("volatility_annualized"),
          scale_low(mom.get("volatility_annualized"), [(0.25, 82), (0.35, 68), (0.5, 52), (0.75, 35), (99, 20)]), 0.6)
    return f.result()


def score_sentiment(sent):
    """News tone + market regime + industry trend. Small weight by design."""
    f = Factor()
    if not sent:
        return f.result()
    news = sent.get("news") or {}
    if news.get("count", 0) >= 3:
        f.add("Stock news tone (recent headlines)", news.get("net_score"),
              scale(news.get("net_score"), [(0.4, 85), (0.15, 70), (-0.15, 55), (-0.4, 38), (-2, 25)]),
              1.2, f"{news.get('bullish')} bullish / {news.get('bearish')} bearish / "
                   f"{news.get('neutral')} neutral of {news.get('count')} headlines.", "x")
    market = sent.get("market") or {}
    if market.get("regime"):
        f.add("Market regime (S&P trend + VIX)", market.get("points"),
              {"Risk-on": 70, "Neutral": 55, "Risk-off": 38}[market["regime"]],
              0.8, "; ".join(market.get("reasons", [])[:3]), "x")
    ind = sent.get("industry") or {}
    if ind.get("trend") and ind["trend"] != "Unknown":
        f.add(f"Industry trend ({ind.get('etf')})", ind.get("points"),
              {"Uptrend": 72, "Sideways": 55, "Downtrend": 38}[ind["trend"]],
              0.8, "; ".join(ind.get("reasons", [])[:2]), "x")
    return f.result()


def compute_scores(snap, ctype, peer_comparison=None, peer_stats=None):
    m, est, holders, mom = snap["metrics"], snap["estimates"], snap["holders"], snap["momentum"]
    ss = snap.get("sector_specific") or {}
    raw = {
        "revenue_growth": score_revenue_growth(m, ctype),
        "earnings_growth": score_earnings_growth(m, ctype),
        "fcf": score_fcf(m, ctype),
        "profitability": score_profitability(m, ctype, ss),
        "balance_sheet": score_balance_sheet(m, ctype),
        "valuation": score_valuation(m, ctype, peer_stats, snap.get("sector"), ss),
        "industry": score_industry(peer_comparison, m),
        "forward": score_forward(est, m, ctype),
        "shareholder": score_shareholder(m, holders, ctype, ss),
        "management": score_management(m, holders, est),
        "moat": score_moat(m, snap),
        "momentum": score_momentum(mom, snap.get("calendar", {})),
        "sentiment": score_sentiment(snap.get("_sentiment")),
    }
    mults = type_weight_adjustments(ctype)
    weights = {k: BASE_WEIGHTS[k] * mults[k] for k in BASE_WEIGHTS}
    total_w = sum(weights.values())
    weights = {k: w * 100 / total_w for k, w in weights.items()}

    factors, total, imputed_weight = {}, 0.0, 0.0
    for k, (score, rows, imputed) in raw.items():
        contribution = score * weights[k] / 100
        total += contribution
        if imputed:
            imputed_weight += weights[k]
        factors[k] = {
            "key": k, "label": FACTOR_LABELS[k], "score": score,
            "base_weight": BASE_WEIGHTS[k], "weight": round(weights[k], 1),
            "contribution": round(contribution, 1), "details": rows,
            "imputed": imputed,
        }
    return round(total, 1), factors, round(imputed_weight, 1)


def rating_from_score(score):
    if score >= 85: return "Strong Buy"
    if score >= 70: return "Buy"
    if score >= 50: return "Hold"
    if score >= 30: return "Sell"
    return "Strong Sell"
