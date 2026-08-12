# 1.1.0: sector-relative valuation bands, bank/REIT metrics, optional FMP provider
# 1.2.0: Piotroski F-Score, Altman Z-Score, valuation-vs-own-history percentile,
#        EPS estimate-revision momentum, sector-ETF relative strength
# 1.3.0: valuation engine v2 — 3-year scenario paths with decaying growth,
#        risk-scaled discount rate, DCF anchor, evidence-adjusted probabilities,
#        Monte Carlo fair-value band; accuracy self-test (app/selftest.py);
#        growth metrics recomputed from statements (Yahoo info fields are
#        quarterly YoY); Z-Score retained-earnings input fixed
# 1.3.1: audit sprint — DQ 5-year check corrected, dividend-coverage red flag,
#        backtest max-drawdown stats, benchmark caching, offline chart fallback
# 1.4.0: News & Sentiment factor (4% base weight) — headline tone lexicon,
#        market regime (S&P trend + VIX), sector-ETF trend; market regime also
#        informs the Timing rating
# 1.5.0: SEC EDGAR official 10-K history (10-20y, no key needed), options-
#        implied expected move (feeds Timing), FRED live macro readings,
#        Finnhub insider/recommendation enrichment (key-gated, fail-soft)
MODEL_VERSION = "1.5.0"
DATA_SOURCE = "Yahoo Finance (via yfinance)"
