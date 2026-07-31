"""Sentiment lexicon, industry trend, demo-cache fallback, data helpers."""
import json

import app.demo_cache as demo_cache
from app.data import cagr, latest, safe_div, yoy, _norm_div_yield
from app.sentiment import _score_text, analyze_news, industry_sentiment


def test_score_text_directions():
    assert _score_text("Company beats estimates and raises guidance")[0] == "Bullish"
    assert _score_text("Shares plunge after SEC investigation and layoffs")[0] == "Bearish"
    assert _score_text("Company schedules annual meeting")[0] == "Neutral"


def test_analyze_news_aggregates():
    items = [{"title": "Beats estimates, raises guidance", "summary": ""},
             {"title": "Record revenue and strong demand", "summary": ""},
             {"title": "Analyst downgrade after weak demand warning", "summary": ""},
             {"title": "Quarterly report scheduled", "summary": ""}]
    out = analyze_news(items)
    assert out["count"] == 4 and out["bullish"] == 2 and out["bearish"] == 1
    assert -1 <= out["net_score"] <= 1
    assert out["items"][0]["sentiment"] == "Bullish"


def test_analyze_news_insufficient():
    assert analyze_news([{"title": "One story", "summary": ""}])["label"] == "Insufficient news"


def test_industry_sentiment_trends():
    up = industry_sentiment({"sector_etf": "XLK", "etf_above_ma200": True, "etf_perf_3m": 0.06})
    down = industry_sentiment({"sector_etf": "XLE", "etf_above_ma200": False, "etf_perf_3m": -0.08})
    assert up["trend"] == "Uptrend" and down["trend"] == "Downtrend"
    assert industry_sentiment({})["trend"] == "Unknown"


def test_demo_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(demo_cache, "CACHE_DIR", tmp_path)
    assert demo_cache.load("MSFT") is None
    (tmp_path / "MSFT.json").write_text(json.dumps(
        {"ticker": "MSFT", "final_rating": "Buy", "generated_at": "2026-07-01",
         "model_version": "1.4.0"}), encoding="utf-8")
    r = demo_cache.load("msft")
    assert r["offline_snapshot"] is True
    assert "2026-07-01" in r["offline_note"]


def test_data_helpers():
    s = [{"date": "2023-12-31", "value": 100.0}, {"date": "2024-12-31", "value": 110.0},
         {"date": "2025-12-31", "value": 121.0}]
    assert latest(s) == 121.0
    assert abs(yoy(s) - 0.10) < 1e-9
    assert abs(cagr(s, 2) - 0.10) < 1e-9
    assert cagr(s, 5) is None
    assert safe_div(1, 0) is None and safe_div(None, 2) is None
    assert _norm_div_yield(0.44) == 0.0044  # percent-style input
    assert _norm_div_yield(0.0044) == 0.0044
