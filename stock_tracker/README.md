# Moat Finder: a Buffett-style stock screener (USA & Canada)

Screens the **S&P 500** and **S&P/TSX Composite**, scores every stock against Warren Buffett's investing
principles, and shows the **top 10 per sector for each country** in a Streamlit dashboard.

The dashboard shows each pick as a card (score badge, price vs. estimated value, cheap/fair/expensive label,
key ratios) with a sortable table view as an alternative. "See why" opens a detail view with a plain-English
explanation of which Buffett rules the stock meets, up to 10 years of financial history, how its value was
estimated, and links to Yahoo, Google Finance and SEC filings. A Guide tab explains every term.

**Ask Moat Finder** is a built-in chat assistant. It's rule-based (no AI model, no API keys, no tokens): it
recognises tickers and company names, comparisons ("Compare AAPL and MSFT"), filtered lists ("Top 5 cheap tech
stocks in the USA", "Low debt utilities"), definitions ("What is ROE?") and counts, and answers from the screen
results. The look (cream palette, serif headings, illustrations in `assets/`) is set in `.streamlit/config.toml`
and the CSS in `app.py`. Light and dark themes are both defined: the app follows the viewer's system setting,
and the "Dark mode" switch at the top right overrides it (switching reloads the page).

## Data sources

| Source | Used for | Method |
|---|---|---|
| Yahoo Finance | Quotes, ratios, ~4 years of statements | `yfinance` |
| SEC EDGAR | 10+ years of official 10-K figures (US only) | Official XBRL API |
| Google Finance | Price & P/E cross-check | HTML scrape |
| Finviz | Price, P/E, ROE, D/E, margin cross-check (US only) | HTML scrape |
| Financial Modeling Prep | Fills history gaps (mostly Canada) — optional | API key |
| Wikipedia | Index constituents and GICS sectors | HTML scrape |

Prices and P/E use the **median** across sources, and disagreements are shown as warnings on the stock.
Responses are cached in `cache/` (quotes for 1 day, fundamentals for 7 days), so re-runs are fast.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # optional: add FMP_API_KEY and SEC_USER_AGENT (your contact email)
```

## Usage

```bash
.venv/bin/streamlit run app.py          # dashboard (use "Run screen" in the sidebar)
.venv/bin/python -m buffett             # or refresh from the command line (handy for cron)
.venv/bin/python -m buffett --countries Canada --limit 3   # quick test run
.venv/bin/python -m pytest              # tests
```

The first full run takes about 10–20 minutes (it's rate-limited to be polite to each site). Later runs use the cache.

## Scoring (0–100)

| Principle | Criterion | Weight |
|---|---|---|
| Durable advantage | Avg ROE ≥ 15%, and ≥ 15% consistently | 12 + 8 |
| Conservative balance sheet | D/E ≤ 0.5 (≤ 1.0 Utilities/Real Estate, ROA for Financials) | 15 |
| Pricing power | Net margin ≥ 15% (3-yr avg) | 14 |
| Predictable earnings | Profitable every year, growth, few down years | 6 + 5 + 4 |
| Owner earnings | Positive and growing free cash flow | 6 + 5 |
| Margin of safety | Price vs. DCF intrinsic value, P/E | 17 + 8 |

The intrinsic value is a 10-year DCF on the 3-year average FCF (net income for financials), growing at the
lower of historical earnings and FCF growth (capped at 12%), fading to 2.5%, discounted at 10%.
These assumptions live in `buffett/config.py`. Criteria without data are skipped and the remaining weights
are rescaled; stocks need ≥ 3 years of history and ≥ 60% data coverage to be ranked.

## Layout

```
app.py                  Streamlit dashboard
assets/                 SVG illustrations (hero, chat, guide, empty state)
.streamlit/config.toml  theme: colours and fonts
buffett/
  chat.py               rule-based chat assistant
  glossary.py           definitions shared by tooltips, Guide and chat
  explain.py            plain-English reasons and verdicts
  formatting.py         money, compact numbers, strength labels
  universe.py           S&P 500 / TSX constituents
  sources/              one module per data provider
  fundamentals.py       merges sources into one view per company
  scoring.py            Buffett criteria + DCF
  pipeline.py           parallel fetch, scoring, ranking, results file
tests/                  scoring, parser, explanation and chat tests
```

## Caveats

- Scrapers break when sites change their HTML; each source degrades gracefully (the stock is still scored from the others).
- Canadian stocks have shorter history (~4 years) unless an FMP key is set and FMP's plan covers TSX symbols.
- Educational tool only — not investment advice.

## Daily refresh with GitHub Actions (free)

`.github/workflows/stock-screen.yml` (at the repository root) re-runs the screen every Tuesday–Saturday and
commits `data/results.csv`. Standard GitHub-hosted runners are free on public repositories.

- **When:** 07:17 UTC for Canada and 07:47 UTC for the USA (about 2–3 a.m. Eastern), after the previous
  close is final and while the data sites are quiet. Odd minutes avoid GitHub's busy top of the hour, and
  the 30-minute gap keeps any one site from seeing all ~720 requests at once.
- **Throttling safeguards:** downloads are cached between runs (fundamentals for 7 days), two workers
  instead of four, a slow second pass for stocks Yahoo rejected, and the run refuses to overwrite good
  results if fewer than 80% of stocks could be scored (`--min-success`).
- **Setup:** the workflow must be on the default branch (`main`). Optionally add repository secrets
  `SEC_USER_AGENT` (e.g. `MoatFinder/1.0 you@example.com`) and `FMP_API_KEY`. Use "Run workflow" on the
  Actions tab for a first manual run.
