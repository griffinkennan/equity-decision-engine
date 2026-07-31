"""Shared fixtures: a synthetic, fully-offline company snapshot.

`make_snap()` builds the same dict shape `data.fetch_snapshot` produces, with
plausible numbers for a profitable large-cap. Tests override pieces to create
banks, cash-burners, etc. No network access anywhere in the suite.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _series(*vals, start_year=2022, scale=1.0):
    return [{"date": f"{start_year + i}-12-31", "value": v * scale}
            for i, v in enumerate(vals)]


def build_snap(**overrides):
    rev = _series(80, 90, 100, 115, scale=1e9)
    snap = {
        "ticker": "TEST", "name": "Test Corp", "sector": "Technology",
        "industry": "Software - Application", "industry_key": None,
        "currency": "USD", "summary": "", "price": 100.0,
        "last_statement_date": "2025-12-31",
        "series": {
            "revenue": rev,
            "gross_profit": _series(32, 37, 42, 48, scale=1e9),
            "operating_income": _series(16, 19, 22, 26, scale=1e9),
            "ebitda": _series(20, 23, 27, 31, scale=1e9),
            "ebit": _series(16, 19, 22, 26, scale=1e9),
            "net_income": _series(12, 14, 16, 19, scale=1e9),
            "eps": _series(2.4, 2.85, 3.3, 4.0),
            "diluted_eps": _series(2.35, 2.8, 3.25, 3.95),
            "ocf": _series(15, 18, 21, 25, scale=1e9),
            "capex": _series(-3, -3.5, -4, -4.5, scale=1e9),
            "fcf": _series(12, 14.5, 17, 20.5, scale=1e9),
            "cash": _series(20, 24, 28, 33, scale=1e9),
            "total_debt": _series(15, 14, 13, 12, scale=1e9),
            "long_term_debt": _series(13, 12, 11, 10, scale=1e9),
            "total_assets": _series(120, 135, 150, 170, scale=1e9),
            "total_liabilities": _series(50, 52, 54, 56, scale=1e9),
            "current_assets": _series(45, 50, 56, 63, scale=1e9),
            "current_liabilities": _series(25, 27, 29, 31, scale=1e9),
            "equity": _series(70, 83, 96, 114, scale=1e9),
            "retained_earnings": _series(40, 50, 61, 74, scale=1e9),
            "shares": _series(5.1, 5.05, 5.0, 4.95, scale=1e9),
            "sbc": _series(1.0, 1.1, 1.2, 1.3, scale=1e9),
            "buybacks": _series(-4, -5, -6, -7, scale=1e9),
            "dividends_paid": _series(-2, -2.2, -2.4, -2.6, scale=1e9),
            "interest_expense": _series(0.6, 0.55, 0.5, 0.45, scale=1e9),
            "receivables": _series(10, 11, 12.2, 13.8, scale=1e9),
            "inventory": _series(4, 4.4, 4.8, 5.4, scale=1e9),
            "dna": _series(4, 4.3, 4.7, 5.1, scale=1e9),
            "tangible_book": _series(55, 66, 78, 94, scale=1e9),
            "invested_capital": _series(85, 97, 109, 126, scale=1e9),
        },
        "qseries": {},
        "metrics": {
            "ttm_revenue": 115e9, "ttm_net_income": 19e9, "ttm_ocf": 25e9,
            "ttm_fcf": 20.5e9, "ttm_ebitda": 31e9,
            "market_cap": 495e9, "enterprise_value": 474e9,
            "shares_outstanding": 4.95e9, "cash": 33e9, "total_debt": 12e9,
            "net_debt": -21e9, "equity": 114e9,
            "gross_margin": 0.417, "operating_margin": 0.226,
            "ebitda_margin": 0.27, "net_margin": 0.165, "fcf_margin": 0.178,
            "rev_growth_1y": 0.15, "rev_cagr_3y": 0.129, "rev_cagr_5y": None,
            "eps_growth": 0.215, "ni_growth": 0.187, "ebitda_growth": 0.148,
            "opinc_growth": 0.18, "fcf_growth": 0.206, "rev_growth_prior": 0.111,
            "roe": 0.18, "roa": 0.12, "roic": 0.206,
            "current_ratio": 2.03, "quick_ratio": 1.6, "debt_to_equity": 0.105,
            "net_debt_to_ebitda": -0.68, "interest_coverage": 57.8,
            "pe": 25.3, "forward_pe": 22.0, "ps": 4.3, "ev_revenue": 4.12,
            "ev_ebitda": 15.3, "p_fcf": 24.1, "fcf_yield": 0.041,
            "peg": 1.2, "pb": 4.34, "dividend_yield": 0.0052,
            "payout_ratio": 0.14, "beta": 1.1,
            "sbc_pct_revenue": 0.0113, "sbc_pct_fcf": 0.063,
            "dilution_1y": -0.01, "dilution_3y": -0.0099,
            "buybacks_ttm": -7e9, "dividends_ttm": -2.6e9,
            "receivables_growth": 0.131, "inventory_growth": 0.125,
            "ocf_to_ni": 1.32, "fcf_to_ni": 1.08, "cash_runway_years": None,
            "valuation_history": {"points": [], "years": 4,
                                  "pe_percentile": 0.5, "pe_range": [18.0, 28.0],
                                  "pe_current": 25.3},
        },
        "momentum": {
            "price": 100.0, "ma50": 96.0, "ma200": 90.0,
            "above_ma50": True, "above_ma200": True,
            "perf_1m": 0.03, "perf_3m": 0.08, "perf_6m": 0.12, "perf_12m": 0.22,
            "rel_spy_3m": 0.02, "rel_spy_12m": 0.07,
            "rel_sector_3m": 0.01, "rel_sector_12m": 0.04,
            "sector_etf": "XLK", "etf_above_ma200": True, "etf_perf_3m": 0.05,
            "volatility_annualized": 0.28, "volume_trend": 0.05,
            "high_52w": 110.0, "low_52w": 70.0,
            "drawdown_from_high": -0.09, "above_low": 0.43,
        },
        "estimates": {
            "earnings_estimate": {"0y": {"avg": 4.3, "growth": 0.09},
                                  "+1y": {"avg": 4.8, "growth": 0.116}},
            "revenue_estimate": {"+1y": {"growth": 0.10}},
            "price_targets": {"current": 100.0, "mean": 118.0,
                              "high": 140.0, "low": 95.0},
            "eps_beat_rate": 0.75,
            "eps_revisions_90d": {"0y": 0.02, "+1y": 0.03},
        },
        "holders": {"insider_pct": 0.04, "institution_pct": 0.7,
                    "insider_buys": 3, "insider_sells": 5,
                    "insider_net_shares": -100000},
        "calendar": {}, "news": [],
        "info_subset": {"forwardEps": 4.55, "trailingEps": 3.95,
                        "numberOfAnalystOpinions": 30,
                        "recommendationKey": "buy", "recommendationMean": 2.1},
        "data_quality": {"score": 85, "checks": [], "missing": [], "note": ""},
        "_sentiment": {
            "news": {"count": 8, "bullish": 4, "bearish": 1, "neutral": 3,
                     "net_score": 0.375, "label": "Bullish", "items": []},
            "market": {"regime": "Neutral", "points": 0, "reasons": ["test"]},
            "industry": {"trend": "Uptrend", "etf": "XLK", "points": 2,
                         "reasons": ["test"]},
        },
        "sector_specific": {},
    }
    for key, val in overrides.items():
        if isinstance(val, dict) and isinstance(snap.get(key), dict):
            snap[key] = {**snap[key], **val}
        else:
            snap[key] = val
    return snap


@pytest.fixture
def snap():
    return build_snap()
