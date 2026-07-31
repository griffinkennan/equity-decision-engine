"""Assembles the full analysis report for one ticker."""
from __future__ import annotations

import datetime as dt

from . import MODEL_VERSION, DATA_SOURCE
from .data import fetch_snapshot
from .classify import classify
from .scoring import compute_scores, rating_from_score
from .valuation import build_scenarios, risk_reward_grade, position_suitability
from .redflags import detect_red_flags, accounting_quality
from .peers import peer_comparison
from . import narrative as nar
from .scoring import moat_class


def analyze(ticker: str) -> dict:
    snap = fetch_snapshot(ticker)
    cls = classify(snap)
    ctype = cls["type"]

    from .sector_metrics import sector_specific, snapshot_rows
    snap["sector_specific"] = sector_specific(snap, ctype)

    from .quant_scores import piotroski, altman_z
    snap["_quant"] = {"piotroski": piotroski(snap), "altman": altman_z(snap, ctype)}

    from .sentiment import build_sentiment
    snap["_sentiment"] = build_sentiment(snap)

    peers = peer_comparison(snap)
    flags = detect_red_flags(snap, ctype)
    snap["_flags"] = flags
    acct = accounting_quality(snap)

    total, factors, imputed_weight = compute_scores(
        snap, ctype, peer_comparison=peers, peer_stats=peers.get("stats"))

    # safeguards: penalties applied after factor scoring, shown explicitly
    penalties = []
    high_flags = [f for f in flags if f["severity"] == "High" and f["affects_rating"]]
    if high_flags:
        p = min(12, 4 * len(high_flags))
        penalties.append({"reason": f"{len(high_flags)} high-severity red flag(s)", "points": -p})
    if acct["score"] < 45:
        penalties.append({"reason": "Weak accounting quality", "points": -6})
    dq = snap["data_quality"]["score"]
    if dq < 60:
        penalties.append({"reason": "Poor data quality", "points": -4})
    total = max(0.0, min(100.0, total + sum(p["points"] for p in penalties)))

    valn = build_scenarios(snap, ctype)

    # margin-of-safety rules
    fundamental_score = total
    rating = rating_from_score(total)
    ms_note = None
    if valn:
        base_up = valn["scenarios"]["base"]["upside"]
        if rating == "Strong Buy" and base_up < 0.30:
            rating, ms_note = "Buy", ("Score qualified for Strong Buy but base-case upside is "
                                      f"{base_up:.0%} (<30% margin-of-safety requirement).")
        if rating == "Buy" and base_up < 0.15:
            rating, ms_note = "Hold", ("Score qualified for Buy but base-case upside is only "
                                       f"{base_up:.0%} (<15% required) — good business, not enough "
                                       "margin of safety at this price.")

    timing = nar.timing_rating(snap, valn)
    confidence, conf_reasons = nar.confidence_level(dq, snap, ctype, imputed_weight)
    if dq < 60 and confidence != "Low":
        confidence, conf_reasons = "Low", ["Data Quality Score below 60."]

    insufficient = dq < 40
    if insufficient:
        rating = "No Rating"
        ms_note = ("Data Quality Score is below 40 — there is not enough reliable data "
                   "to responsibly rate this stock.")

    rr_grade, rr_expl = risk_reward_grade(valn, total, dq, snap["momentum"], snap["metrics"])
    suit, suit_expl = position_suitability(ctype, total, valn, snap["metrics"],
                                           snap["momentum"], dq)
    strengths, weaknesses = nar.strengths_weaknesses(snap, factors)

    # fundamental vs timing: fundamental rating excludes momentum factor
    fund_no_mom = sum(f["contribution"] for k, f in factors.items() if k != "momentum")
    mom_weight = factors["momentum"]["weight"]
    fund_rating = rating_from_score(
        max(0, min(100, fund_no_mom * 100 / max(1e-9, 100 - mom_weight)
                   + sum(p["points"] for p in penalties))))
    if insufficient:
        fund_rating = "No Rating"

    m = snap["metrics"]
    report = {
        "ticker": snap["ticker"], "name": snap["name"],
        "sector": snap["sector"], "industry": snap["industry"],
        "price": snap["price"], "currency": snap["currency"],
        "summary": snap["summary"],
        # headline
        "final_rating": rating,
        "total_score": round(total, 1),
        "confidence": confidence, "confidence_reasons": conf_reasons,
        "fundamental_rating": fund_rating,
        "timing_rating": timing[0], "timing_reason": timing[1],
        "risk_reward_grade": rr_grade, "risk_reward_explanation": rr_expl,
        "position_suitability": suit, "position_suitability_explanation": suit_expl,
        "company_type": ctype, "company_type_reasons": cls["reasons"],
        "margin_of_safety_note": ms_note,
        "insufficient_data": insufficient,
        "score_penalties": penalties,
        # scores
        "factors": factors,
        "imputed_weight": imputed_weight,
        "accounting_quality": acct,
        "moat": {"score": factors["moat"]["score"],
                 "class": moat_class(factors["moat"]["score"]),
                 "details": factors["moat"]["details"],
                 "reasoning": _moat_reasoning(factors["moat"]["score"], m)},
        "management_quality": {"score": factors["management"]["score"],
                               "details": factors["management"]["details"]},
        "data_quality": snap["data_quality"],
        # valuation
        "valuation": valn,
        "valuation_summary": nar.valuation_summary(snap, valn, peers.get("stats")),
        # narrative
        "strengths": strengths, "weaknesses": weaknesses,
        "red_flags": flags,
        "risk_summary": nar.risk_summary(snap, flags, ctype),
        "catalysts": nar.catalysts(snap),
        "catalyst_summary": _catalyst_summary(snap),
        "macro": nar.macro_sensitivity(snap),
        "earnings_commentary": snap.get("transcript_analysis") or {
            "available": False,
            "note": _commentary_fallback_note(),
        },
        "sector_specific": {**snap["sector_specific"],
                            "rows": snapshot_rows(snap["sector_specific"])}
                           if snap["sector_specific"] else None,
        "quant_checks": {**snap["_quant"],
                         "valuation_history": snap["metrics"].get("valuation_history")},
        "sentiment": snap["_sentiment"],
        "wall_street": {
            "consensus": (snap.get("info_subset") or {}).get("recommendationKey"),
            "mean_score": (snap.get("info_subset") or {}).get("recommendationMean"),
            "analysts": (snap.get("info_subset") or {}).get("numberOfAnalystOpinions"),
        },
        "peer_comparison": peers,
        "what_would_change": nar.what_would_change(snap, ctype, rating),
        "why_wrong": nar.why_wrong(snap, ctype, rating, total),
        "final_explanation": nar.final_explanation(snap, rating, total, confidence,
                                                   ctype, timing, valn, flags),
        # data for charts / raw view
        "financial_snapshot": _snapshot_table(snap) + snapshot_rows(snap["sector_specific"]),
        "series": snap["series"], "qseries": {k: v for k, v in snap["qseries"].items()
                                              if k in ("q_revenue", "q_net_income", "q_fcf", "q_ocf")},
        "momentum": {k: v for k, v in snap["momentum"].items()},
        "metrics": m,
        "estimates": snap["estimates"],
        "holders": snap["holders"],
        "calendar": snap["calendar"],
        "news": snap["news"],
        # provenance
        "model_version": MODEL_VERSION,
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "data_source": snap.get("data_source") or DATA_SOURCE,
        "last_statement_date": snap["last_statement_date"],
        "scoring_formula": {k: f"{v['weight']}%" for k, v in factors.items()},
        "missing_data_warnings": snap["data_quality"]["missing"],
        "disclaimer": ("This tool is for research and education only. It is not financial advice. "
                       "The model may be wrong, financial data may be delayed or inaccurate, "
                       "assumptions may be incorrect, and users should do their own research "
                       "before making investment decisions."),
    }
    return report


def _commentary_fallback_note():
    from . import fmp
    if fmp.enabled():
        return ("Your FMP key is active (it extends statement history), but earnings-call "
                "transcripts require a paid FMP tier, so tone analysis is unavailable. "
                "The News & Sentiment section covers headline tone instead.")
    return ("Earnings-call transcripts require a Financial Modeling Prep API key — add "
            "FMP_API_KEY to stock-analyzer/.env. The News & Sentiment section covers "
            "headline tone in the meantime.")


def _moat_reasoning(score, m):
    cls = moat_class(score)
    bits = []
    if (m.get("gross_margin") or 0) > 0.5:
        bits.append("high gross margins point to pricing power")
    if (m.get("roic") or 0) > 0.15:
        bits.append("sustained high returns on invested capital suggest durable advantages")
    if (m.get("market_cap") or 0) > 100e9:
        bits.append("scale itself is a cost and distribution advantage")
    if not bits:
        bits.append("margins and returns on capital do not yet demonstrate a durable advantage")
    return (f"Moat assessed as {cls} ({score:.0f}/100): " + "; ".join(bits) +
            ". Note: this is a quantitative proxy — brand, network effects and switching costs "
            "need qualitative judgment.")


def _catalyst_summary(snap):
    ned = snap.get("calendar", {}).get("next_earnings_date")
    n = len(snap.get("news") or [])
    parts = []
    if ned:
        parts.append(f"Next earnings: {str(ned)[:10]}.")
    changes = snap["estimates"].get("recent_rating_changes")
    if changes:
        parts.append(f"{len(changes)} recent analyst rating action(s).")
    if n:
        parts.append(f"{n} recent headlines tracked.")
    return " ".join(parts) or "No upcoming catalysts identified from available data."


def _snapshot_table(snap):
    from .narrative import fmt_usd, fmt_pct, fmt_x
    m = snap["metrics"]
    mom = snap["momentum"]
    rows = [
        ("Price", f"${snap['price']:.2f}" if snap.get("price") else "n/a"),
        ("Market cap", fmt_usd(m.get("market_cap"))),
        ("Enterprise value", fmt_usd(m.get("enterprise_value"))),
        ("Revenue (TTM)", fmt_usd(m.get("ttm_revenue"))),
        ("Net income (TTM)", fmt_usd(m.get("ttm_net_income"))),
        ("Free cash flow (TTM)", fmt_usd(m.get("ttm_fcf"))),
        ("Gross margin", fmt_pct(m.get("gross_margin"))),
        ("Operating margin", fmt_pct(m.get("operating_margin"))),
        ("Net margin", fmt_pct(m.get("net_margin"))),
        ("Revenue growth (1y)", fmt_pct(m.get("rev_growth_1y"))),
        ("P/E (trailing / forward)", f"{fmt_x(m.get('pe'))} / {fmt_x(m.get('forward_pe'))}"),
        ("EV/EBITDA", fmt_x(m.get("ev_ebitda"))),
        ("P/S", fmt_x(m.get("ps"))),
        ("FCF yield", fmt_pct(m.get("fcf_yield"))),
        ("Dividend yield", fmt_pct(m.get("dividend_yield"))),
        ("Net debt", fmt_usd(m.get("net_debt"))),
        ("Net debt / EBITDA", fmt_x(m.get("net_debt_to_ebitda"))),
        ("Current ratio", fmt_x(m.get("current_ratio"))),
        ("ROE", fmt_pct(m.get("roe"))),
        ("52-week range position", fmt_pct(mom.get("drawdown_from_high"), signed=True) + " from high"),
    ]
    return [{"label": a, "value": b} for a, b in rows]
