"""Red-flag detector, accounting quality, Piotroski, Altman."""
from app.redflags import accounting_quality, detect_red_flags
from app.quant_scores import altman_z, piotroski
from tests.conftest import build_snap


def _flags(snap, ctype="Mature Profitable Company"):
    snap.setdefault("_quant", {})
    return {f["flag"] for f in detect_red_flags(snap, ctype)}


def test_clean_company_has_no_high_flags(snap):
    snap["_quant"] = {}
    flags = detect_red_flags(snap, "Mature Profitable Company")
    assert not [f for f in flags if f["severity"] == "High"]


def test_negative_fcf_flagged():
    snap = build_snap(metrics={"ttm_fcf": -2e9})
    assert "Negative free cash flow" in _flags(snap)


def test_revenue_decline_flagged():
    snap = build_snap(metrics={"rev_growth_1y": -0.15})
    assert "Revenue decline" in _flags(snap)


def test_dilution_flagged():
    snap = build_snap(metrics={"dilution_1y": 0.15})
    assert "Heavy share dilution" in _flags(snap)


def test_uncovered_dividend_flagged():
    snap = build_snap(metrics={"payout_ratio": 1.3, "dividend_yield": 0.05})
    assert "Dividend not covered by earnings" in _flags(snap)


def test_receivables_outrunning_revenue_flagged():
    snap = build_snap(metrics={"receivables_growth": 0.40, "rev_growth_1y": 0.10})
    assert "Receivables growing faster than revenue" in _flags(snap)


def test_flags_sorted_high_first():
    snap = build_snap(metrics={"ttm_fcf": -2e9, "net_debt_to_ebitda": 6.0,
                               "rev_growth_1y": -0.15})
    snap["_quant"] = {}
    sevs = [f["severity"] for f in detect_red_flags(snap, "Mature Profitable Company")]
    order = {"High": 0, "Medium": 1, "Low": 2}
    assert sevs == sorted(sevs, key=order.get)


def test_altman_distress_becomes_red_flag():
    snap = build_snap()
    snap["_quant"] = {"altman": {"score": 1.2, "zone": "Distress"}, "piotroski": None}
    flags = detect_red_flags(snap, "Mature Profitable Company")
    hit = [f for f in flags if "Altman" in f["flag"]]
    assert hit and hit[0]["severity"] == "High"


def test_accounting_quality_range(snap):
    aq = accounting_quality(snap)
    assert 0 <= aq["score"] <= 100
    assert aq["verdict"] in ("Clean", "Acceptable", "Questionable", "Poor", "Unknown")


def test_accounting_quality_penalizes_low_cash_conversion():
    good = accounting_quality(build_snap())
    bad = accounting_quality(build_snap(metrics={"ocf_to_ni": 0.4, "fcf_to_ni": 0.2}))
    assert bad["score"] < good["score"]


def test_piotroski_strong_for_improving_company(snap):
    p = piotroski(snap)
    assert p is not None
    assert p["score"] >= 6
    assert p["score"] == sum(1 for c in p["checks"] if c["pass"])


def test_altman_safe_for_strong_company(snap):
    z = altman_z(snap, "Mature Profitable Company")
    assert z is not None and not z.get("skipped")
    assert z["zone"] == "Safe"
    wsum = sum(c["weighted"] for c in z["components"] if c["weighted"] is not None)
    assert abs(z["score"] - wsum) < 0.02


def test_altman_skipped_for_banks(snap):
    z = altman_z(snap, "Bank or Financial Company")
    assert z["skipped"] is True
