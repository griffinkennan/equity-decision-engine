"""EDGAR XBRL parsing (synthetic facts) and provider fail-soft behavior."""
from app.edgar import _annual_points, extend_annual_series
import app.finnhub as finnhub
import app.macro_data as macro_data


def _fact(end, val, start=None, form="10-K", filed="2026-01-01"):
    row = {"end": end, "val": val, "form": form, "filed": filed}
    if start:
        row["start"] = start
    return row


def test_annual_points_filters_full_fiscal_years():
    gaap = {"Revenues": {"units": {"USD": [
        _fact("2025-12-31", 100, start="2025-01-01"),          # full year
        _fact("2025-12-31", 25, start="2025-10-01"),           # Q4 — rejected
        _fact("2024-12-31", 90, start="2024-01-01"),
        _fact("2024-06-30", 45, start="2024-01-01", form="10-Q"),  # 10-Q — rejected
    ]}}}
    pts = _annual_points(gaap, ("Revenues",), "duration")
    assert [(p["date"], p["value"]) for p in pts] == [("2024-12-31", 90.0), ("2025-12-31", 100.0)]


def test_annual_points_merges_tag_aliases():
    gaap = {
        "Revenues": {"units": {"USD": [_fact("2025-12-31", 100, start="2025-01-01")]}},
        "SalesRevenueNet": {"units": {"USD": [
            _fact("2018-12-31", 40, start="2018-01-01"),
            _fact("2025-12-31", 999, start="2025-01-01"),   # loses to Revenues (priority)
        ]}},
    }
    pts = _annual_points(gaap, ("Revenues", "SalesRevenueNet"), "duration")
    assert [(p["date"], p["value"]) for p in pts] == [("2018-12-31", 40.0), ("2025-12-31", 100.0)]


def test_annual_points_prefers_latest_filing():
    gaap = {"Assets": {"units": {"USD": [
        _fact("2024-12-31", 500, filed="2025-02-01"),
        _fact("2024-12-31", 510, filed="2026-02-01"),   # restated later — wins
    ]}}}
    pts = _annual_points(gaap, ("Assets",), "instant")
    assert pts == [{"date": "2024-12-31", "value": 510.0}]


def test_extend_respects_duplicate_year_guard(monkeypatch):
    import app.edgar as edgar
    monkeypatch.setattr(edgar, "_cik_for", lambda t: "0000000001")
    monkeypatch.setattr(edgar, "_company_facts", lambda cik: {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            _fact("2022-12-28", 70, start="2022-01-01"),   # ~same FY as existing — rejected
            _fact("2020-12-31", 60, start="2020-01-01"),   # genuinely older — kept
        ]}}}}})
    series = {"revenue": [{"date": "2022-12-31", "value": 71e9},
                          {"date": "2023-12-31", "value": 80e9}]}
    assert extend_annual_series("TEST", series) is True
    assert [d["date"] for d in series["revenue"]] == ["2020-12-31", "2022-12-31", "2023-12-31"]


def test_keyless_providers_fail_soft(monkeypatch):
    monkeypatch.setattr(finnhub, "api_key", lambda: None)
    assert finnhub.enabled() is False
    assert finnhub.insider_summary("MSFT") is None
    assert finnhub.recommendation_trend("MSFT") is None
    monkeypatch.setattr(macro_data, "api_key", lambda: None)
    assert macro_data.enabled() is False
    assert macro_data.current_readings() is None
