"""Scoring engine: bands, weights, rating conversion, totals."""
from app.scoring import (BASE_WEIGHTS, compute_scores, moat_class,
                         rating_from_score, scale, scale_low)
from app.classify import TYPES, type_weight_adjustments
from tests.conftest import build_snap


def test_rating_conversion_boundaries():
    assert rating_from_score(100) == "Strong Buy"
    assert rating_from_score(85) == "Strong Buy"
    assert rating_from_score(84.9) == "Buy"
    assert rating_from_score(70) == "Buy"
    assert rating_from_score(69.9) == "Hold"
    assert rating_from_score(50) == "Hold"
    assert rating_from_score(49.9) == "Sell"
    assert rating_from_score(30) == "Sell"
    assert rating_from_score(29.9) == "Strong Sell"
    assert rating_from_score(0) == "Strong Sell"


def test_scale_is_monotonic():
    bands = [(0.30, 95), (0.20, 85), (0.12, 72), (0.06, 60), (0.0, 40), (-1, 12)]
    scores = [scale(v, bands) for v in (0.5, 0.25, 0.15, 0.08, 0.01, -0.5)]
    assert scores == sorted(scores, reverse=True)
    assert scale(None, bands) is None


def test_scale_low_prefers_low_values():
    bands = [(12, 88), (18, 75), (25, 62), (50, 32), (9999, 18)]
    assert scale_low(10, bands) > scale_low(20, bands) > scale_low(60, bands)


def test_base_weights_are_the_spec_plus_sentiment():
    # 12 spec factors sum to 100; sentiment adds 4 and normalization restores
    # an effective 100 in every report (verified in the test below)
    assert sum(BASE_WEIGHTS.values()) == 104
    assert BASE_WEIGHTS["sentiment"] == 4


def test_weights_normalize_to_100_for_every_company_type():
    for ctype in TYPES:
        snap = build_snap()
        total, factors, _ = compute_scores(snap, ctype)
        wsum = sum(f["weight"] for f in factors.values())
        assert abs(wsum - 100) < 0.5, f"{ctype}: weights sum {wsum}"
        assert 0 <= total <= 100


def test_type_adjustments_cover_all_factors():
    for ctype in TYPES:
        mults = type_weight_adjustments(ctype)
        assert set(mults) == set(BASE_WEIGHTS)


def test_total_equals_weighted_contributions(snap):
    total, factors, _ = compute_scores(snap, "Mature Profitable Company")
    # displayed weights are rounded to 0.1 each; 13 of them can drift ~0.5
    recomputed = sum(f["score"] * f["weight"] / 100 for f in factors.values())
    assert abs(total - recomputed) < 0.6


def test_good_company_scores_above_neutral(snap):
    total, factors, imputed = compute_scores(snap, "Mature Profitable Company")
    assert total > 55, "healthy growing net-cash company should beat neutral"
    assert imputed < 20


def test_bank_type_deemphasizes_fcf():
    snap = build_snap()
    _, mature, _ = compute_scores(snap, "Mature Profitable Company")
    _, bank, _ = compute_scores(build_snap(), "Bank or Financial Company")
    assert bank["fcf"]["weight"] < mature["fcf"]["weight"]


def test_moat_class_thresholds():
    assert moat_class(80) == "Strong"
    assert moat_class(60) == "Moderate"
    assert moat_class(40) == "Weak"
