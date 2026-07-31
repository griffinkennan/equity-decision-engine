"""Valuation engine v2: scenario ordering, probabilities, dilution, DCF."""
from app.valuation import build_scenarios, required_return, risk_reward_grade
from tests.conftest import build_snap


def test_scenarios_ordered_and_consistent(snap):
    v = build_scenarios(snap, "Mature Profitable Company")
    assert v is not None
    s = v["scenarios"]
    assert s["bear"]["fair_value"] < s["base"]["fair_value"] < s["bull"]["fair_value"]
    psum = sum(sc["probability"] for sc in s.values())
    assert abs(psum - 1.0) < 0.001
    for sc in s.values():
        assert sc["probability"] >= 0.10  # floor: no scenario written off
        assert abs(sc["upside"] - (sc["fair_value"] / snap["price"] - 1)) < 0.002
    ev = sum(sc["fair_value"] * sc["probability"] for sc in s.values())
    assert abs(v["expected_value"] - ev) < 0.05


def test_monte_carlo_band_ordered(snap):
    mc = build_scenarios(snap, "Mature Profitable Company")["monte_carlo"]
    assert mc["p10"] < mc["p25"] < mc["p50"] < mc["p75"] < mc["p90"]
    assert 0 <= mc["prob_above_price"] <= 1


def test_dcf_present_for_fcf_positive(snap):
    v = build_scenarios(snap, "Mature Profitable Company")
    assert v["dcf"] is not None and v["dcf"]["fair_value"] > 0


def test_required_return_bounds_and_risk_premium():
    base, _ = required_return(build_snap())
    risky, _ = required_return(build_snap(
        metrics={"ttm_fcf": -2e9, "net_debt_to_ebitda": 4.0, "market_cap": 1e9},
        momentum={"volatility_annualized": 0.7}))
    assert 0.07 <= base < risky <= 0.16


def test_dilution_lowers_preprofit_fair_value():
    def burner(dilution):
        return build_snap(
            metrics={"ttm_net_income": -1e9, "ttm_fcf": -1e9,
                     "dilution_1y": dilution, "ev_revenue": 3.0,
                     "gross_margin": 0.55},
            info_subset={"forwardEps": None, "trailingEps": -1.2},
            estimates={"earnings_estimate": {}})
    fv_low = build_scenarios(burner(0.0), "Unprofitable High-Growth Company")
    fv_high = build_scenarios(burner(0.12), "Unprofitable High-Growth Company")
    assert fv_low["method"].startswith("3-year revenue")
    # heavier dilution must not raise the base-case fair value
    assert fv_high["scenarios"]["base"]["fair_value"] < fv_low["scenarios"]["base"]["fair_value"]


def test_gross_margin_scales_sales_multiple():
    def burner(gm):
        return build_snap(
            metrics={"ttm_net_income": -1e9, "ttm_fcf": -1e9, "gross_margin": gm,
                     "ev_revenue": 3.0},
            info_subset={"forwardEps": None, "trailingEps": -1.2},
            estimates={"earnings_estimate": {}})
    lo = build_scenarios(burner(0.10), "Unprofitable High-Growth Company")
    hi = build_scenarios(burner(0.80), "Unprofitable High-Growth Company")
    assert hi["scenarios"]["base"]["fair_value"] > lo["scenarios"]["base"]["fair_value"]


def test_risk_reward_grade_range(snap):
    v = build_scenarios(snap, "Mature Profitable Company")
    grade, _ = risk_reward_grade(v, 70, 85, snap["momentum"], snap["metrics"])
    assert grade in ("Excellent", "Favorable", "Balanced", "Unfavorable", "Poor")
