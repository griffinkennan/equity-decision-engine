"""Company-type classification on synthetic profiles."""
from app.classify import classify
from tests.conftest import build_snap


def test_mature_profitable_default(snap):
    assert classify(snap)["type"] == "Mature Profitable Company"


def test_bank_by_sector():
    snap = build_snap(sector="Financial Services", industry="Banks - Diversified")
    assert classify(snap)["type"] == "Bank or Financial Company"


def test_reit_by_industry():
    snap = build_snap(sector="Real Estate", industry="REIT - Diversified")
    assert classify(snap)["type"] == "REIT"


def test_unprofitable_high_growth():
    snap = build_snap(metrics={"ttm_net_income": -2e9, "ttm_fcf": -1.5e9,
                               "rev_growth_1y": 0.45})
    assert classify(snap)["type"] == "Unprofitable High-Growth Company"


def test_early_stage_speculative():
    snap = build_snap(metrics={"ttm_revenue": 30e6, "ttm_net_income": -50e6})
    assert classify(snap)["type"] == "Early-Stage Speculative Company"


def test_high_growth_profitable():
    snap = build_snap(metrics={"rev_growth_1y": 0.32, "rev_cagr_3y": 0.28})
    assert classify(snap)["type"] == "High-Growth Company"


def test_turnaround_on_revenue_decline():
    snap = build_snap(metrics={"rev_growth_1y": -0.12})
    assert classify(snap)["type"] == "Turnaround Company"


def test_energy_is_commodity():
    snap = build_snap(sector="Energy", industry="Oil & Gas E&P")
    assert classify(snap)["type"] == "Commodity or Energy Company"


def test_semiconductor_is_cyclical():
    snap = build_snap(industry="Semiconductors",
                      metrics={"rev_growth_1y": 0.10, "rev_cagr_3y": 0.09})
    assert classify(snap)["type"] == "Cyclical Company"
