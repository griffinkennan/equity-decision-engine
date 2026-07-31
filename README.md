# Equity Decision Engine

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688)
![Tests](https://img.shields.io/badge/tests-45%20passing-brightgreen)
![License](https://img.shields.io/badge/use-research%20%26%20education-lightgrey)

A stock-research dashboard: enter any publicly traded ticker and get a
transparent, explainable investment breakdown — **Strong Buy / Buy / Hold /
Sell / Strong Sell**, a 0–100 score, bull/base/bear fair-value scenarios with
Monte Carlo bands, red flags, peer comparison, news sentiment, and a
no-lookahead backtest.

**Design principle: no black boxes.** Every rating decomposes into visible
metrics, weights, thresholds, and assumptions. The model adapts scoring to
company type (banks aren't judged on EBITDA; REITs are judged on FFO; cash
burners are judged on runway and dilution), gates its own output on data
quality, and enforces a margin-of-safety rule — a great business still isn't
a Buy if the price leaves no upside.

> **Disclaimer:** research and education only — not financial advice. Data may
> be delayed or wrong; assumptions may be incorrect. Do your own research.

## Quick start

```powershell
python -m venv .venv                       # first time only
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --port 8642
```

Open http://localhost:8642 and search a ticker or company name.
Run the test suite with `.venv\Scripts\python -m pytest tests -q`.

**Data source:** Yahoo Finance via `yfinance` — no API key required. The source
is displayed on every report; if a field is unavailable it is counted against
the Data Quality Score rather than silently guessed.

**Optional upgrade:** copy `.env.example` to `.env` and add a
[Financial Modeling Prep](https://financialmodelingprep.com) API key (uses the
`/stable` API). Free tier: extends statement history to 5 fiscal years
(unlocks 5-year CAGRs and deeper valuation percentiles). Paid tiers addit-
ionally unlock 10-year history (raise the `limit` in `app/fmp.py`) and
earnings-call transcript tone analysis (Bullish/Neutral/Cautious/Bearish vs.
the prior quarter, hot topics, guidance excerpts) — the transcript code is
already wired and activates automatically. Every FMP call fails soft — a
missing or invalid key just means Yahoo-only data.

## What a report contains

Final rating with margin-of-safety rules · Total score (0–100) · Confidence
(High/Medium/Low) · Fundamental vs. Timing rating (Good Entry / Wait / Avoid) ·
Risk/Reward grade · Position suitability · Company-type classification (10
types with adjusted scoring weights) · Financial snapshot · 12-factor score
breakdown with every metric, threshold and weight exposed · Bull/Base/Bear fair
values with stated assumptions and probabilities · Peer comparison vs. industry
or sector peers · Red-flag detector (severity + why it matters) · Accounting
Quality score · Moat and Management Quality scores · Data Quality score ·
Catalysts and analyst actions · Macro sensitivity by sector · What would change
the rating · Why this rating could be wrong · Charts (price/MAs, revenue,
margins, FCF, debt, dilution…) · Raw JSON of every input.

## Tests

- `python -m pytest tests -q` — 45 offline unit tests over the scoring bands,
  weight normalization, company-type classification, valuation math (scenario
  ordering, probabilities, dilution and margin effects), red flags,
  Piotroski/Altman arithmetic, sentiment lexicon, and the demo cache. No
  network needed; runs in ~3 seconds.
- `python -m app.selftest AAPL JPM ...` — live accuracy harness: recomputes
  every reported metric independently from raw statements and fails loudly on
  disagreement.

## Offline demo cache

`python -m app.demo_cache MSFT JPM RIVN` snapshots complete reports to
`demo_cache/`. If a live analysis fails (no internet, rate limiting), the API
serves the snapshot instead, clearly labeled with its capture date.

## Docker

`docker build -t equity-engine . && docker run -p 8642:8642 equity-engine`

## Report layout

The report is organized into tabs so the default view stays scannable:
**Overview** (rating, grades, fair-value bar, key stats, strengths/weaknesses,
red-flag summary) with depth in **Valuation**, **Score & Risk**, **Market &
Peers**, **Charts**, and **Data & History**. Printing ignores the tabs and
includes every section.

## Scoring model (v1.4.0)

v1.4.0 — News & Sentiment (SeekingAlpha-style):

- **News & Sentiment factor** (4% base weight, renormalized): recent-headline
  tone from a finance-specific keyword lexicon (matched terms shown per
  article), market regime (S&P 500 trend + VIX → risk-on/neutral/risk-off),
  and the sector-ETF trend. Deliberately small weight — news tilts the rating,
  fundamentals drive it. Risk-off markets also count against the Timing rating.
- **Factor grade strip**: SA-style letter grades (A+…F) for Valuation, Growth,
  Profitability, Momentum, Revisions and Sentiment in the report header.
- **Wall Street comparison pill**: analyst consensus + count next to the
  model's own rating.
- **News feed card**: 10 recent headlines, each tagged Bullish/Bearish/Neutral
  with the matched keywords disclosed, linking out to the source.

## Scoring model (v1.3.1)

v1.3.1 — full audit sprint: margins now derive from statements first so the
snapshot always matches the margin charts (Yahoo's TTM info fields use
different cost buckets for some sectors); the "5+ years of history" data-
quality check actually requires 5 years; dividend-not-covered red flag;
backtest reports average/worst 1-year max drawdown; benchmark price history
(SPY + sector ETFs) is cached instead of re-fetched per analysis; charts
degrade gracefully when the Chart.js CDN is unreachable; valuation-multiples-
over-time chart; recently-viewed ticker chips; clear-search button; deep links
work on cached reloads; mobile layout pass; `.env` (FMP key) git-ignored.

## Scoring model (v1.3.0)

v1.3.0 — accuracy + valuation depth:

- **Accuracy self-test** (`python -m app.selftest AAPL MSFT ...`): recomputes
  every key reported metric independently from raw statements (market cap,
  EV, P/E, P/S, FCF, margins, growth, net debt, F/Z-score arithmetic, factor
  weight sums, scenario math) and fails loudly on disagreement. Fixed by this
  audit: Yahoo's `revenueGrowth`/`earningsGrowth` info fields are latest-
  quarter YoY, not annual (growth now computed from statements, TTM-preferred);
  the Z-Score's retained-earnings input was missing from the data layer.
- **Valuation engine v2**: 3-year scenario paths with decaying growth and a
  risk-scaled discount rate (volatility, leverage, size, FCF); terminal EV/S
  for pre-profit companies is scaled by gross margin and share counts are
  diluted per scenario; base case blends the scenario model with a 5-year DCF
  anchor and the analyst mean target (weights shown); scenario probabilities
  shift with observable evidence (trend, valuation percentile, revisions);
  a 4,000-draw Monte Carlo pass yields a P10–P90 fair-value band and the
  share of draws above the current price; large divergence from analyst
  consensus triggers a visible caution note.
- **UI**: fair-value range bar (bear/base/bull/analyst/price ticks over the
  Monte Carlo band), per-scenario 3-year path tables, anchor blends, and the
  discount-rate build-up, all on the report's valuation card.

## Scoring model (v1.2.0)

v1.1.0 additions: valuation multiples are normalized against sector-typical
levels before banding (a 25x P/E is cheap for software, rich for a utility —
see `SECTOR_NORMS` in `app/scoring.py`); banks are scored on net interest
margin, NII growth, efficiency ratio and price/tangible book; REITs on P/FFO,
FFO growth and dividend-payout-vs-FFO (approximations are labeled in the UI).

v1.2.0 additions (`app/quant_scores.py` + scoring hooks):

- **Piotroski F-Score** (0-9 fundamental-health checks with per-component
  detail; ≤2 becomes a red flag) and **Altman Z-Score** (safe/grey/distress
  zones; distress becomes a high-severity red flag; skipped for financials
  where the model does not apply) — shown in a "Quant health checks" card.
- **Valuation vs own history**: current P/E and P/S as a percentile of the
  stock's own fiscal-year-end multiples (deeper with the FMP key); feeds the
  valuation factor.
- **EPS estimate-revision momentum**: 90-day drift in next-year consensus EPS
  feeds the forward-outlook factor.
- **Sector-ETF relative strength** (XLK/XLF/…) feeds the momentum factor,
  separating stock-specific weakness from sector-wide weakness.

Base weights: Valuation 15 · FCF 12 · Balance Sheet 12 · Profitability 10 ·
Revenue Growth 8 · Earnings Growth 8 · Industry-Relative 8 · Forward Outlook 7 ·
Shareholder 5 · Management 5 · Moat 5 · Momentum 5. Weights are re-normalized
per company type (e.g. biotech emphasizes balance sheet/runway, banks de-emphasize
FCF). Ratings: 85+ Strong Buy, 70+ Buy, 50+ Hold, 30+ Sell, else Strong Sell —
then margin-of-safety rules demote Strong Buy/Buy when base-case upside is
below 30%/15%. Data Quality < 60 forces Low confidence; < 40 withholds the
rating entirely. Every rating records model version, data source, timestamps
and missing-data warnings; bump `MODEL_VERSION` in `app/__init__.py` when the
formula changes so past ratings remain comparable.

## Backtesting

The Backtest button runs a point-in-time simulation: historical scores use only
annual statements assumed public 75 days after fiscal year end plus prices up
to each signal date (no lookahead; historical analyst estimates are unavailable
so the forward factor is excluded). Yahoo keeps ~4–5 annual statements, so
samples are small — results are labeled as illustrative historical simulations.

## Other features

- **Search by name or ticker** — the search box autocompletes company names
  (e.g. "costco" → COST) via `/api/search`.
- **Deep links** — every report gets a `#TICKER` URL; bookmark or share it and
  the back/forward buttons work.
- **Compare** up to 5 tickers side by side, sortable by score, upside, risk,
  valuation, growth, FCF, momentum or confidence.
- **Watchlist screener** with notes, latest rating, score change vs. the prior
  rating (Δ column), growth/FCF-yield/forward-P/E/momentum columns, sortable by
  score, upside, growth, FCF, valuation, risk, momentum or confidence, a
  "Refresh all ratings" button, and rating history over time (SQLite:
  `analyzer.db`).
- **Export** any report to CSV, or print to PDF (print stylesheet switches to
  a clean white layout automatically).

## Layout

```
app/
  data.py       yfinance fetch + normalization + data-quality scoring
  classify.py   company-type classification + weight adjustments
  scoring.py    12-factor scoring engine (all thresholds live here)
  valuation.py  bull/base/bear scenarios, risk/reward, suitability
  redflags.py   red-flag detector + accounting-quality score
  peers.py      peer discovery (industry weight >= 2%, sector fallback)
  narrative.py  plain-English explanations, timing, confidence, macro
  engine.py     assembles the full report
  backtest.py   point-in-time historical simulation
  db.py         SQLite watchlist / notes / rating history
  main.py       FastAPI routes
static/         dashboard (vanilla JS + Chart.js)
```
