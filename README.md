# Strategy Workbench

A local research application for futures strategies. You register a strategy
adapter, point it at a versioned market-data archive, **declare your pass
criteria and development cutoff before launching**, and the app runs the
backtest under multiple cost and execution scenarios. It refuses to call
anything validated unless every declared scenario passes.

Everything runs on this machine. No accounts, no run quotas, no external
service. The app is the record of what you tried, including what failed.

The point of the application is not the backtester — it is the ledger. A
completed backtest is treated as *execution completed*, never as evidence of
profit. Milestones are earned in order:

```
Backtested  →  Evaluation passed  →  Robustness checked
```

## Quick start

Requires Node 24+ and Python 3.12.

```powershell
npm install
.venv/Scripts/python.exe -m pip install -r requirements-workbench.txt
npm run dev:full
```

Open **http://127.0.0.1:5173**. The API listens on loopback port 8001.

For the built app instead of the dev server:

```powershell
npm run build   # typechecks frontend + backend, then builds
npm start       # serves UI and API together on http://127.0.0.1:8001
```

On macOS/Linux use `.venv/bin/python`; the npm scripts pick the platform's
virtualenv automatically.

See [WORKBENCH.md](WORKBENCH.md) for accounting conventions, protocol details
and the full validation command list.

## The application

Ten pages in three sidebar groups. Every view has its own address (for example
`#/portfolio/calendar`), so any state is linkable. **New run** and **Search**
(Ctrl/Cmd + K) are reachable from every page. Below 900px the sidebar collapses
into a bottom bar.

**Research flow**

| Page | What it is for |
| --- | --- |
| Research workspace | Entry point: recent activity, what needs attention, run cleanup |
| Scripts & library | The 17 tracked runnable adapters plus a searchable index of 171 catalogued sources |
| Runs & compare | The full run ledger with filters, saved views, side-by-side comparison |
| Evaluations & regimes | Walk-forward evaluations, cost/delay stress, parameter sensitivity, regime studies |

**Portfolio**

| Page | What it is for |
| --- | --- |
| Strategy scorecards | Latest evaluated configuration per strategy and market |
| Combined portfolio | Cross-market picker, combined curves, calendar, weights, CSV export |
| Watchlist | Frozen historical replay set |

**Data & studies**

| Page | What it is for |
| --- | --- |
| Pattern event studies | Supply/demand, order blocks, FVGs and S/R tested against matched controls |
| Datasets | Import and version market-data archives |

### Running an experiment

**New run** is a four-step flow that will not let you skip the record-keeping:

1. **Script & dataset** — pick an adapter, a dataset version, timeframe and session.
2. **Parameters** — forms are generated from each adapter's declared parameter schema.
3. **Assumptions & record** — capital, fees, slippage, execution delay, warmup, UTC
   date window, development boundary, plus your **hypothesis and pass criteria**.
4. **Preview & launch** — validate, see the resolved job count and warmup checks,
   then explicitly launch.

Every resolved default is saved with the run. For a grid, add dataset versions
and parameter arrays (`{"lookback": [10, 20, 40]}`); all dimensions form a
Cartesian product, default cap 24 jobs, two concurrent Python workers.

Runs execute server-side and **survive closing the browser**. Cancelling keeps a
cancellation record. Re-running creates a new attempt against the original
inputs and source snapshot.

### What the gate actually enforces

This is the part that is hard to find in other tools:

- **Criteria are recorded before launch.** The run form's *Run purpose* captures
  intent and never awards a milestone by itself.
- **Multi-scenario pass requirement.** A configuration must clear baseline,
  higher-cost and (where supported) delayed-execution scenarios. One passing
  scenario is not a pass.
- **Prior-exposure tracking.** Each evaluation records `inspected_overlap` — the
  earlier successful runs that already touched its test window. The app tells you
  when you have already seen the data you are calling out-of-sample. It does not
  pretend the label makes it clean.
- **Failures stay visible.** Run tables never silently drop failed variants.
  Matching failures re-attach across dates and cost settings.
- **Source checksums invalidate stale verdicts.** Change an adapter and prior
  reviews for it have to be redone.
- **Progress is scoped.** A milestone belongs to one source snapshot + symbol +
  timeframe + session + parameter set. A failing ES case cannot invalidate a
  passing NQ configuration, and vice versa.

Catalogued is not runnable; backtested is not validated; working is not
approved. The UI states which of these it means everywhere it shows a status.

### Adding a strategy

Copy [`strategies/_template.py`](strategies/_template.py), give it a unique ID,
and implement its signal function. Discovery parses source without importing or
running it, so no frontend or backend catalog edit is needed.

**Scripts & library → Library** indexes 171 sources (150 Python, 21 Pine),
grouped by family and role, searchable by filename, description or rule
function. Entries that need work before they can run are marked **Adapter
required** with the specific blocker. See the
[strategy library](docs/workbench/STRATEGY_LIBRARY.md) and
[Pine audit](docs/workbench/PINE_AUDIT.md).

An available adapter covers only its stated rules, not every variant in its
source file. Signal decisions were checked against the original pure functions;
the workbench applies its own fixed-contract, next-open execution and
accounting.

## Data

The app runs on normalized, timezone-aware Databento one-minute archives
(`GLBX.MDP3`) for **ES, NQ, MNQ, YM and CL** — roughly 4.8M bars per
instrument — with prepared 5m/15m/30m/1h/4h/1d bars derived from them.

**Datasets → Import data ZIPs** scans `data/` recursively. Reimporting the same
archive reuses its version; replacing an archive creates a new one, so a run
always names the exact bytes it used. Contract tick size and dollar point value
come from the dataset catalog, not from strategy code. TradingView exports are
not inputs.

Durable app state lives in `data/workbench/`. Repository cleanup must not move
or rewrite it.

## Standalone studies

Some research runs outside the app as scripts against the same local archives.
These write their own reports and are not part of the app's run ledger.

**MNQ New York close → Asia fill** — does the 18:00 ET reopen revisit the
completed NY close by 00:00 ET?

```powershell
.\.venv\Scripts\python.exe .\scripts\mnq\mnq_ny_close_asia_fill_backtest.py
.\.venv\Scripts\python.exe .\scripts\mnq\mnq_asia_fill_strategy_backtest.py
```

The study measures probabilities; the second script trades them. Because the
headline rule was chosen after seeing the whole sample, three checks sit beside
the P&L: a block bootstrap (per-session P&L skewness near -19, so the ordinary
t-statistic does not apply), a White-style reality check across all 54
side/threshold/close rules, and a walk-forward that re-picks the rule each year
from prior data only.

**MNQ Market Profile** — tests the two widely repeated claims (the 80% rule, and
naked POC revisits within 10 sessions) that circulate without a published
dataset behind them:

```powershell
.\.venv\Scripts\python.exe .\scripts\mnq\mnq_market_profile_backtest.py
```

Profiles are built per RTH session under both volume and TPO definitions, so the
answer does not hinge on one vendor's value-area convention. Prices are
back-adjusted across 29 rolls; holiday and half sessions are excluded. Every
headline number runs against a matched control — that is the part worth keeping.

**MNQ opening trend-pullback** — the mechanical version of a 09:30-11:00 ET
discretionary plan, with every fuzzy term frozen and documented:

```powershell
.\.venv\Scripts\python.exe .\scripts\mnq\mnq_opening_trend_pullback_backtest.py
```

Further reading: [event studies](docs/workbench/EVENT_STUDIES.md),
[intraday momentum](docs/research/MARKET_INTRADAY_MOMENTUM.md),
[SND setup and variants](SND_WORKBENCH.md),
[combined portfolio](COLLECTIVE_DASHBOARD.md),
[evaluation and regime notes](docs/workbench/PHASES_4_5.md).

### TradingView reference implementations

`pine/` holds Pine ports used to cross-check adapter behaviour on TradingView —
a manual multi-market TSMOM dashboard, a single-market Strategy Tester version,
an experimental intraday ORB variant, and the supply/demand indicators. They
request daily values with `lookahead_off`, confirm outside the request, and act
at the next session's first completed bar. None submit orders or model futures
rolls. `ninjatrader/` holds the equivalent NinjaTrader ports.

## Layout

- `src/app/`, `src/features/`, `src/shared/` — shell, vertical feature slices, browser-only shared code
- `server/http/`, `server/features/`, `server/core/`, `server/infra/` — HTTP boundary, domain services, supervision, persistence
- `shared/contracts/`, `shared/ts/` — versioned cross-runtime schemas and pure calculations
- `workbench/`, `strategy_engine/`, `strategies/` — Python orchestration, shared execution/accounting, runnable adapters
- `research/` — reproducible campaigns and studies that are not runnable adapters
- `tools/` — data, validation, migration and maintenance utilities
- `scripts/` — standalone studies and compatibility entry points awaiting a parity-backed move
- `tests/` — unit, isolated API, browser, fixture and opt-in real-data suites
- `evidence/` — tracked protocols, conclusions, manifests and checksums
- `artifacts/` — ignored raw research output; override the root with `WORKBENCH_ARTIFACTS`
- `data/workbench/` — durable app state
- `dataset-archives/` — compressed market datasets, checksums, and [restore instructions](dataset-archives/README.md)
- `docs/workbench/`, `docs/research/` — implementation history, inventories, research notes
- `pine/`, `ninjatrader/` — platform-specific reference ports
- `legacy/previous-dashboard/` — source-only archive of the retired dashboard API and UI, excluded from the build and test gates

Some compatibility commands still write ignored output under `reports/`. New
integrations should resolve artifact storage through the workbench layout rather
than adding another hard-coded report path.

## Tests

```bash
npm run test:workbench:all   # hermetic product gate: hygiene, build, lint, TS + Python units
npm run test:browser         # Playwright smoke over the running app
npm run doctor               # reports toolchain drift, installs nothing
```

The Python suites include parity checks against the original strategy sources
([tests/test_parity.py](tests/test_parity.py)) and accounting invariants
([tests/test_accounting.py](tests/test_accounting.py)). Real-data validation is
opt in: `npm run test:real-data` with `WORKBENCH_REAL_DATA=1`.

## Current limits

Stated plainly so they are not discovered the hard way:

- **No price chart.** Equity and drawdown render as simple SVG polylines; there
  is no candlestick view and no way to inspect a trade on the chart. This is the
  largest functional gap in the app.
- **The state endpoint is heavy.** `GET /api/workbench/state?view=summary`
  returns the whole catalog — currently ~13.9 MB — and the UI polls it every 10
  seconds. The ETag saves bandwidth but not server CPU, because the payload is
  serialized before the ETag is compared.
- **No table virtualization.** The runs ledger renders every filtered row.
- **Single JS bundle.** No route-level code splitting.
- **Fixed-contract sizing only.** `strategy_engine/sizing.py` rounds contracts;
  there is no volatility targeting, so risk drifts with the volatility regime.
- **Independent strategy books.** The combined portfolio does not net positions,
  share margin, resize, or account for correlation between books. Several
  correlated index-futures configurations will look like separate bets.
- **Evaluation labels are research judgments, not certifications.** They record
  that declared criteria were met on declared data. They do not establish that
  the data was never inspected, correct for the number of variants tried, or
  imply live-trading eligibility. Brokerage execution is outside this
  application.
- **Desktop-first.** The bottom-bar layout works, but the app is built for a wide
  screen.

The local API binds `127.0.0.1` and is not intended to be exposed to a network.
