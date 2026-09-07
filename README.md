# Quant — Papers With Backtest workspace

Local environment for running [Papers With Backtest](https://paperswithbacktest.com/) strategies.
Data and code come from PWB; **execution runs on this machine** — no run endpoint, no per-run limit.

## Strategy dashboard

The React/Redux/Mantine dashboard includes a local, allowlisted Python runner. Install once, then
start the web UI and API together:

```bash
npm install
.venv/bin/pip install -r requirements-dashboard.txt
npm run dev:full
```

Open `http://127.0.0.1:5173` and choose **Run analysis**. The form supports date windows,
chart timeframes, costs, risk settings, and strategy-specific parameters. Runs execute in the
existing `.venv` and write isolated outputs under `reports/dashboard_runs/<run-id>/`; they do not
overwrite the canonical report directories. CSV output can be inspected as a table or line chart,
while JSON, text, images, and generated HTML are previewed in the same workspace.

Strategies and charts are separate inputs. The chart catalog currently reads the normalized,
timezone-aware Databento one-minute archives for MNQ, NQ, ES, YM, and CL, together with their
prepared 5m/30m/1h/4h/1d bars. Contract tick size and dollar point value come from the chart
catalog, not from strategy code. Every run saves a reproducibility record containing the chart,
dataset identity, contract economics, strategy parameters, and calculation time. TradingView
exports are not inputs to this runner.

The API only accepts workflows and parameters declared in `dashboard_api/main.py`; browser input
is never interpreted as a shell command. The local API listens on `127.0.0.1:8000` and is not meant
to be exposed directly to the internet.

## Layout

- `.venv/` — Python 3.10 virtual environment (gitignored)
- `.env` — `PWB_API_KEY` data key, secret, expires 2026-08-16 (gitignored)
- `scripts/` — all backtests/fetchers/reports, grouped by instrument or theme
  (`cme/`, `mnq/`, `mgc/`, `es_nq/`, `orb/`, `overnight/`, `spy_qqq_intraday/`,
  `lucid/`, `misc/`). Every script still resolves `data/`, `reports/`, and
  `.env` at the repo root regardless of which subfolder it lives in.
- `pine/` — TradingView Pine Script indicators/strategies
- `ninjatrader/` — NinjaScript ports of the Carver-vetted backtests
- `reports/` — generated CSV/PNG/HTML output (gitignored contents vary by script)
- `scripts/misc/smoke_test.py` — verifies data access + metrics

## Use

Activate the venv:

```bash
source .venv/Scripts/activate   # git bash on Windows
```

Run anything:

```bash
python scripts/misc/smoke_test.py
```

## CME time-series momentum

Run the readable four-market trend strategy on a $100,000 balance from 2024:

```powershell
.\.venv\Scripts\python.exe .\scripts\cme\cme_time_series_momentum_backtest.py
```

Export its daily signals, positions, returns, and equity curve:

```powershell
.\.venv\Scripts\python.exe .\scripts\cme\cme_time_series_momentum_backtest.py `
  --export .\cme_tsmom_results.csv
```

The model combines 20/60/120/252-session momentum, targets equal risk per
market, lags every position by one session, and applies exposure-based costs.
ES/NQ use SPX/NDX cash-index proxies; GC/CL use PWB continuous daily series.

### TradingView manual indicator

Copy `pine/cme_tsmom_manual_indicator.pine` into TradingView's Pine Editor and add
it to a chart. It calculates the same model from completed daily bars, displays
the four-market dashboard, estimates rounded micro-contract quantities, and
provides next-session long, short, flat, and resize alerts. The indicator does
not submit orders or model futures rolls. For dated-contract charts, choose the
matching continuous dashboard series as the marker source; optional L/S/F
session markers make the active daily state visible during Bar Replay.

### TradingView backtest strategy

Copy `pine/cme_tsmom_single_market_strategy.pine` into TradingView's Pine Editor to
run a one-market Strategy Tester simulation. The strategy is fixed to a
15-minute execution chart, set to $25,000 initial capital and one standalone
sleeve. Its daily-data and date-window flow mirrors the working overnight-drift
strategy: daily values are requested with `lookahead_off`, confirmed outside
the request, and acted on at the first 15-minute close of the next session. It
holds overnight and rebalances whole contracts once per exchange session. Its
other default Properties are $1.25 commission per contract per order, one tick
of slippage, and 10% simulated margin.

For an MNQ historical or Deep Backtest, put the strategy on the 15-minute
`CME_MINI:MNQ1!` continuous chart and use `CME_MINI:NQ1!` as the signal. Leave
the chart multiplier on automatic (`syminfo.pointvalue`, normally $2 per
point). Dated contracts such as MNQU2026 are suitable for current execution but
do not contain older custom-date history. Its broad 1990-2099 internal safety
window contains normal Strategy Report selections, including Deep Backtesting
dates. Model-sized trading can still correctly round to zero contracts on a
$25,000 account. Fixed-contract mode is useful for inspecting signal behavior,
but it does not preserve the tested volatility target.
For notifications, create a TradingView strategy alert on order-fill events and
put `{{strategy.order.alert_message}}` in the alert's Message field.

### Experimental intraday TSMOM setup

`pine/cme_tsmom_intraday_orb_strategy.pine` uses the completed daily TSMOM score only
as a direction filter, then trades a confirmed 5-minute close outside the first
15 minutes' opening range. It takes at most one trade per New York RTH session, skips
the setup when a whole micro contract exceeds its default $75 stop-risk cap,
places an opposite-range stop and 2R target, and force-closes by 16:00 ET. This
is a separate experimental strategy, not an intraday-equivalent reproduction of
the daily TSMOM backtest. Use `MNQ1!` with `NQ1!` as its signal, or `MES1!` with
`ES1!`, and enable TradingView Bar Magnifier/Deep Backtesting when available.

## Load data

```python
import pwb_toolbox.datasets as pwb_ds
df = pwb_ds.load_dataset("Stocks-Daily-Price", symbols=["AAPL", "MSFT"])  # ALWAYS pass symbols=
```

Omitting `symbols=` materializes the whole dataset (1-min prices ~75 GB). Filter is pushed into parquet reads.

## MNQ New York-close to Asia-fill study

Test whether the 18:00 ET MNQ reopen revisits the completed New York close by
00:00 ET, with separate probabilities and one-contract P&L for gap-down longs
and gap-up shorts:

```powershell
.\.venv\Scripts\python.exe .\scripts\mnq\mnq_ny_close_asia_fill_backtest.py
```

The default run compares the 16:00 cash close with the 17:00 futures close,
uses one tick of round-trip cost, and excludes weekend/holiday reopens whose
reference close is stale. It writes event-level data, point and BPS gap buckets,
long/short comparisons, split-sample results, cost sensitivity, and a Markdown
report to `reports/mnq_ny_close_asia_fill/`.

```powershell
# Futures close only, two-tick round-trip cost, recent sample
.\.venv\Scripts\python.exe .\scripts\mnq\mnq_ny_close_asia_fill_backtest.py `
  --close-times 17:00 --cost-ticks 2 --start 2023-01-01
```

### Trading the study

The fill study measures probabilities. `scripts/mnq/mnq_asia_fill_strategy_backtest.py`
trades them: market entry at the reopen, a resting limit at the reference
close, a flat exit at the deadline, and an equity curve on the full session
calendar.

```powershell
.\.venv\Scripts\python.exe .\scripts\mnq\mnq_asia_fill_strategy_backtest.py
```

The default headline rule is the study's selection (17:00 close, short, gap
below 3 bps), priced at one tick of entry slippage, one tick on market exits,
and $1.00 commission per round trip. It writes trades, a daily equity curve,
calendar years, and sweeps over cost, protective stop, fill buffer, and
deadline to `reports/mnq_asia_fill_strategy/`.

Three checks sit alongside the P&L, because the headline rule was chosen after
seeing the whole sample:

- a block bootstrap of the rule on its own, since per-session P&L has skewness
  near -19 and the ordinary t-statistic does not apply;
- a White-style reality check over all 54 side/threshold/close rules, which
  prices the search rather than one hypothesis;
- a walk-forward that re-picks the rule each year from prior data only.

```powershell
# Long gap-downs instead, with a protective stop and no commission
.\.venv\Scripts\python.exe .\scripts\mnq\mnq_asia_fill_strategy_backtest.py `
  --rule-side Long --rule-max-gap-bps 5 --stop-points 50 --commission-rt 0
```

## MNQ Market Profile: the 80% rule and naked POCs

Two Market Profile "rules" circulate widely without a published dataset behind
them: that price re-entering the prior value area and holding for two 30-minute
periods traverses the whole area about 80% of the time, and that roughly 80% of
naked POCs are revisited within 10 sessions. This tests both on the local
one-minute MNQ archive:

```powershell
.\.venv\Scripts\python.exe .\scripts\mnq\mnq_market_profile_backtest.py
```

Profiles are built per RTH session (08:30-15:00 America/Chicago) under both
volume and TPO definitions, so the answer does not depend on one vendor's
value-area convention. Prices are back-adjusted across the 29 contract rolls,
and holiday/half sessions are excluded from profile formation.

Every headline number is run against a matched control, which is the part worth
keeping:

- the 80% rule is compared with sessions that opened *inside* the prior value
  area, re-weighted to the signal's own mix of trigger bracket, direction, and
  distance-to-target, so the comparison is not a restatement of how far the far
  edge happened to be;
- the same scan is run requiring only one accepting bracket, which isolates what
  the two-period confirmation is actually worth;
- naked POCs are compared with the value-area edges, the range midpoint, a
  uniform draw from the session range, and the POC reflected through the session
  close, which holds distance-from-close fixed.

Both claims are also converted into costed trade ledgers. Output goes to
`reports/mnq_market_profile/`.

```powershell
# TPO value areas, whole-bracket acceptance, coarser rows, day-session revisits only
.\.venv\Scripts\python.exe .\scripts\mnq\mnq_market_profile_backtest.py `
  --profile-mode tpo --accept-mode range --price-step 4 --npoc-touch-scope rth
```

## MNQ opening trend-pullback

Run the mechanical version of the 09:30-11:00 ET trend/pullback plan against
the local one-minute MNQ archive:

```powershell
.\.venv\Scripts\python.exe .\scripts\mnq\mnq_opening_trend_pullback_backtest.py
```

It uses completed five-minute bars for structure, VWAP, pullback and rejection
signals, then one-minute bars for conservative bracket fills. Fuzzy terms from
the discretionary plan are frozen and documented in
`reports/mnq_opening_trend_pullback/report.md`; the trade ledger, daily series,
annual totals, and machine-readable configuration are written beside it.

```powershell
# Different account risk, date window, and the optional bias-flip exit
.\.venv\Scripts\python.exe .\scripts\mnq\mnq_opening_trend_pullback_backtest.py `
  --start 2023-01-01 --risk-dollars 200 --bias-flip-exit
```

## CME Group data + statistical reports

PWB has no dataset named "CME". The CME Group complex is assembled from four daily datasets by
`scripts/cme/fetch_cme_data.py`: 38 CME/CBOT/NYMEX/COMEX roots plus 7 non-CME comparators (Brent, ICE softs, VIX).

```powershell
python scripts/cme/fetch_cme_data.py --include-reference        # -> data/cme_daily.parquet, data/cme_universe.csv
python scripts/cme/fetch_cme_data.py --refresh                  # repull; otherwise the parquet cache is reused
python scripts/cme/cme_stats_report.py --include-reference --plots           # full history -> reports/
python scripts/cme/cme_stats_report.py --start 2005-01-01 --out-dir reports/2005plus
python scripts/cme/cme_stats_report.py --markets ES,NQ,CL,GC,ZN --rf 0.04
```

`reports/` gets 14 CSVs plus `cme_report.md`: coverage/quality, moments and risk, dependence
(ADF, Ljung-Box, Lo-MacKinlay variance ratios, Hurst), correlation, day-of-week / month /
turn-of-month seasonality, volatility regimes, tails and drawdowns.

Proxies, not futures — cash indices for the equity contracts, bond **price** indices for ZT/ZF/ZN/ZB
(they rise as yields fall), spot FX, continuous fronts for commodities. No roll yield, multipliers,
fees, or margin. Momentum, vol, and correlation statistics survive this; carry and term-structure
statistics do not.

Known data traps, all surfaced by the report's section 0:

- `CC` (cocoa) printed 0.91 between two 5000-handle closes on 2025-11-25 — auto-scrubbed as a
  one-day round trip. Genuine gaps like April 2020 WTI (which goes negative) are kept, and returns
  are blanked rather than log-transformed across non-positive prices.
- `ZR` (rough rice) has bad pre-1987 prints (0.80 -> 3.96 on 1986-08-20). Use `--start 1990-01-01`.
- `6J 6C 6S 6M 6L 6Z CNH` carry only ~240 days of PWB history and are dropped by `--min-years 3`.
  Deep FX history exists only for EURUSD, GBPUSD, AUDUSD, NZDUSD.
- `DC` proxy `DL1` trades at 0.8-4.25, not Class III milk's $/cwt — treat its levels as unverified.
- `VX` legitimately trips the implausible-move flag (VIX +115.6% on 2018-02-05).

## Metrics (match the catalog)

```python
from pwb_toolbox.performance.metrics import sharpe_ratio, annualized_volatility, cagr, max_drawdown
```

- `sharpe_ratio`, `annualized_volatility` — exact match (population var, ×√252, no risk-free rate)
- `max_drawdown` — returns `(depth, duration)`, depth **negative** → use `abs(depth)`
- `cagr` — off by ~1e-5 vs catalog (annualizes over `len-1` not `len`)

## Replay a paper

`get_paper` returns a `code` string. **Read it before running — arbitrary Python, runs with your permissions.**

```python
ns = {"__name__": "__main__"}
exec(paper_code, ns)
strat = ns["strategy"]
nav = strat.log_data                      # [{"date","value"}, ...]
pos = strat.get_latest_positions()
```

## Save a run

MCP tools: `create_strategy` (register with hypothesis + cutoff, **before** the run), `update_strategy`,
`list_my_strategies`, `delete_strategy`. Strategies are private to the account.

- Set `parentSlug` on every variant — lineage is what makes a Sharpe ratio readable.
- NAV is too big for a tool call (~130k tokens for 36y daily). POST it directly:
  `POST /api/v1/me/strategies/{slug}/results` with `x-api-key: $PWB_API_KEY`.
- Pick the in-sample/out-of-sample split **before** looking at results; keep it fixed.

## Keep count

Variants are free locally — that is how noise becomes a fake edge. Log every variant tested,
including discards. Read `deflatedSharpeRatio` (via `get_strategy_lineage`): <0.5 means the search
explains the result, not the strategy.
