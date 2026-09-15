# Strategy Workbench

## Start the app

Requires Node 24+ and Python 3.12. From the repository root on Windows:

```powershell
npm install
.venv/Scripts/python.exe -m pip install -r requirements-workbench.txt
npm run dev:full
```

Open **http://127.0.0.1:5173**. The TypeScript API listens on loopback port
8001. `npm run build` checks frontend and backend types and builds the UI;
`npm start` then serves the built app and API at **http://127.0.0.1:8001**.
On macOS/Linux, use `.venv/bin/python` for installation. The npm commands choose
the platform's virtual environment automatically.

## Run an experiment

1. **Datasets → Import data ZIPs** scans `data/` recursively. The supplied NQ,
   ES, YM, and CL Databento archives have already been registered locally.
   Imports report progress and errors. Reimporting the same archive reuses its
   version; replacing an archive creates a new version.
2. **Scripts → Configure run** selects a discovered strategy. Nine adapters are
   included: five signal strategies and four Pine event strategies. Their cards
   and run results state the migration scope; see [PINE_AUDIT.md](PINE_AUDIT.md).
3. Select a dataset version, timeframe, session, UTC date interval, parameters,
   capital, fees, slippage, and warmup. Every resolved default is saved.
4. For a grid, select additional dataset versions/timeframes and enter parameter
   arrays, for example `{"lookback": [10, 20, 40]}`. All dimensions form a Cartesian
   product. The default limit is 24 jobs, with two concurrent Python workers.
5. **Validate & preview**, then explicitly **Launch**. Runs continue while the
   browser reloads or closes. Inspect individual jobs to see logs, notes, CSV
   artifacts, exact inputs, and results. Canceling keeps a cancellation record;
   rerunning creates a new attempt with the original inputs and source.

Run tables never filter away failed variants automatically. Saved views, tags,
presets, hypothesis text, and experiment IDs help retain the selection history.
Evaluation requires a development boundary before the scored interval and
criteria recorded before launch. The label does not certify that the user has
never inspected that data; evaluation outcomes remain a research judgment.

## Add a strategy automatically

### Existing Python strategies

**Scripts → Consolidated strategy library** indexes 91 original Python sources
and 17 Pine sources, grouped by family and role. Search by filename,
description, or function; inspect original Python, command-line declarations,
requirements, and links to signal adapters. Discovery parses source without
importing or running it. Original files remain in place to preserve sibling imports.

[STRATEGY_LIBRARY.md](STRATEGY_LIBRARY.md) contains the exportable inventory.
Regenerate it with:

```powershell
.venv/Scripts/python.exe -m workbench.library --output STRATEGY_LIBRARY.md
```

Catalogued does not mean executable in the new runner. Unported intrabar rules,
multi-leg portfolios, factor panels, and research sweeps require their respective
adapters or inputs; these entries are marked **Adapter required**. An available
signal adapter covers only its stated rules, not every variant in its source file.
Signal decisions were checked against the original pure functions/canonical engine;
the workbench uses its own fixed-contract, next-open execution and accounting.

### New strategies

```powershell
Copy-Item strategies/_template.py strategies/my_strategy.py
```

Edit `STRATEGY['id']`, its name/description, parameter schema, and `signals()`.
The file appears in **Scripts** within five seconds, or immediately after
**Scan scripts**. No registry or UI edits are needed. Filenames beginning with
`_` are helpers/templates and are skipped. Duplicate IDs and invalid metadata
appear as discovery errors.

Optional `legacy_sources` lists original repository-relative Python paths and
automatically links your adapter from those library entries. Use `migration_scope`
to describe exactly which rules it covers and execution differences. Set
`default_warmup_days` when the form should start with a longer warmup. RSI(2), for
example, defaults to 400 calendar days for its 200-bar daily trend filter.

Validation commands: `npm run test:library` checks inventory coverage, source
discovery, indicator parity, and causality. `npm run test:library-browser` exercises
source inspection, adapter forms, and real-data runs for the five signal adapters.
`npm run test:pine` and `npm run test:pine-browser` cover the four Pine event ports.
Screenshots and run IDs are saved in `reports/workbench-validation/`.

The metadata must be a **literal** Python dictionary so the catalog can inspect
it without running your code. Fields support `integer`, `number`, `boolean`,
`enum`, and `string`, with defaults, descriptions, numeric bounds, and enum
choices. For conditional nonempty strings, use e.g.
`'required_when': {'use_filter': True}`. Unknown parameters are rejected by both
the backend and Python worker. An optional `validate(parameters, request)` hook
can perform strategy-specific checks in the worker before simulation.

```python
def signals(bars, parameters):
    average = bars.close.rolling(parameters['lookback']).mean()
    return (bars.close > average).astype(int) * parameters['contracts']
```

`bars` has a timezone-aware bar-open index in the selected session timezone,
OHLCV, session metadata, and the completion
timestamp in `availability_time`. It includes the requested warmup. Return a
Series with the **same index**, containing signed whole-contract targets in
[-100, 100]. Zero means flat. Use only completed, available observations.
The runner shifts decisions to the next bar open; do not shift them yourself.

Local helpers under `strategies/`, `strategy_engine/`, `workbench/`, and
`scripts/` are snapshotted. Keep imports inside those areas or installed Python
packages. Pass data through `bars` rather than hard-coding mutable dataset
paths. Existing scripts need a small adapter exposing their signal calculation;
the app cannot infer the execution semantics of an arbitrary legacy script.
The signal template supports target-position strategies with full equity.
The Pine ports use `execution_model: 'event-v1'` and
`create_strategy(bars, parameters, request)` for close/next-open decisions and
working brackets. See [PINE_AUDIT.md](PINE_AUDIT.md) and the port modules for that
contract. Summary-only imports and multi-leg accounting are not implemented.

## Accounting and comparisons

The following describes the signal runner. Pine event fills, sizing, bracket
costs, and comparison/evaluation limits are specified in [PINE_AUDIT.md](PINE_AUDIT.md).

- Fixed whole contracts, USD, no cash flows or funding. There is no broker,
  margin, or liquidation simulation. Negative equity remains visible; undefined
  annualized metrics stay null.
- A decision from a completed bar fills at the next available selected bar's
  open. Positions **carry across excluded session gaps, including overnight**.
  Open P&L is marked at every scored bar close. All positions liquidate at the
  final close, including exit costs. Each run starts flat; warmup initializes
  indicators but contributes no scored P&L.
- Fees are USD per contract per side. Slippage is ticks per contract per side.
  Every quantity change is charged. The closed-trade ledger reconciles with
  equity and total costs before a run succeeds.
- Drawdown uses the continuous bar-close equity peak, including initial capital;
  it never resets at month boundaries. It does not measure unknown intrabar
  excursions. Charts are sampled previews; CSVs retain every scored bar.
- Sharpe uses observed UTC daily equity returns, 252 dates/year, sample standard
  deviation, and zero risk-free rate. No-trade or constant-return Sharpe is null.
  CAGR requires at least one elapsed year and positive equity.
- **As run** shows original assumptions and highlights differences. **Aligned**
  requires equal capital, costs, timeframe, session, and currency, then uses a
  shared timestamp interval. Calendars must match exactly; no missing returns
  are filled. It carries original positions and rebases to the prior equity
  mark. Cut-interval trade counts are unavailable. To change simulation or
  initialization assumptions, launch new runs.

## Watchlist

Inspect a successful run and record a reason to **Freeze in watchlist**. Code,
parameters, accounting assumptions, and instrument are frozen. **Run on latest
data** resolves a specific dataset version when queued and performs a full
historical replay. A changed/corrected dataset creates a new snapshot; original
records remain available. No new data leaves the existing snapshot unchanged.

Recent returns are relative to the last covered data month, not the computer's
current month. Partial initial months and unavailable trailing windows are not
presented as full-month performance. Tracking status is relative to registered
datasets. These replays are not prospective paper trading.

## Evaluation and regime research

**Evaluation & Regimes** adds rolling walk-forward selection, complete candidate
sensitivity tables, subsequent baseline/cost/delay tests, and a joined test equity
path. Selection uses only training results and is recorded before test jobs.
Criteria are frozen before launch. Successful execution and research outcome
remain separate; insufficient evidence is Inconclusive.

Completed evaluations support historical volatility/trend investigations. Each
fold's threshold is calibrated on training data, and preceding-bar features
classify subsequent outcomes. Reports include episodes, P&L, costs, exposure,
and seeded episode-bootstrap intervals where the sample supports them.

See [PHASES_4_5.md](PHASES_4_5.md) for definitions, limits, usage, and validation.

## Storage, replay, and backup

`data/workbench/` contains:

- `workbench.sqlite3`: experiment, run, dataset, preset, view, and watch records.
- `datasets/<archive-sha256>-v1/`: immutable normalized Parquet and metadata.
- `sources/<sha256>/`: actual Python code, file checksums, dependency inventory,
  and interpreter identity, including uncommitted edits at launch.
- `runs/<uuid>/`: resolved `input.json`, process log, validated manifest, and CSVs.
- `evaluations/<uuid>/`: immutable protocol request, joined scenario equity,
  result, and analysis log; fold selections are also persisted in SQLite.
- `regimes/<uuid>/`: investigation settings, thresholds, state observations,
  uncertainty summaries, and analysis log.

Before execution, workers verify dataset and source checksums and installed
package versions. Changed dependencies must be restored before replaying an
older snapshot. An environment inventory is evidence; it is not an automatically
recreated virtual environment. The API is the only database writer. Workers
write artifacts and publish their final manifest only after validation.

The supervisor persists queue state and uses a heartbeat lease. After a restart,
lost running jobs become Interrupted, queued jobs resume, and workers from the
old supervisor exit. Normal cancellation and timeout terminate process trees.
Trusted scripts run with the local user's privileges; this is not a sandbox.

For a consistent backup, stop the app, copy **all of `data/workbench/` together**,
and retain the project and matching Python environment. Restore to the same
absolute workspace path: stored paths are absolute. Evidence JSON exports include
source and environment metadata, but **do not include the large datasets** and
are not complete backups. Portable restore/path relocation is not automated.

Configuration environment variables: `WORKBENCH_PYTHON`, `WORKBENCH_HOME`,
`WORKBENCH_PORT` (8001), `WORKBENCH_CONCURRENCY` (2, at most 8), and
`WORKBENCH_MAX_BATCH` (24, at most 100). Change the Vite proxy too if changing
the API port during development. Workers receive a minimal environment rather
than inheriting API credentials.

## Dataset limitations

The imported `.v.0` series use the vendor's continuous volume-roll mapping and
unadjusted prices. Roll gaps can affect signals and P&L. Negative crude prices
are legitimate and are retained. Duplicate/unordered timestamps, nonfinite
prices, inconsistent OHLC, and negative volume cause import failure. Gaps are
counted, but an authoritative exchange holiday calendar is not supplied, so
closures and no-trade minutes cannot be fully distinguished from missing bars.
Historical publication/revision timing is unavailable. Acquisition time uses
the ZIP file's local modification timestamp. These limitations appear in the UI
and saved run warnings.

## Strategy dashboard

Open **Dashboard** for the latest evaluation of each strategy in the selected
market. It refreshes automatically every ten seconds and through **Refresh**.
New strategy adapters appear automatically, with **Not evaluated** until an
evaluation exists. Choose a strategy in the profit chart or scorecard to view
its complete evidence; **Open evaluation** and **Inspect baseline run** link
directly to the saved records.

- **Research candidate:** every declared scenario has positive net P&L and meets
  its evaluation criteria; baseline trade ledgers reconcile; the adapter matches;
  no earlier matching research failures/flags remain.
- **Conditional:** latest scenarios pass, but earlier matching evaluations failed
  or earlier saved runs carry a `checks-failed` review flag.
- **Needs review:** a criterion fails, net profit is not positive, the adapter
  changed, or trade evidence is unavailable/corrupt.
- **Benchmark**, **In progress**, **Incomplete**, and **Not evaluated** preserve
  the distinction between execution, research status, and missing evidence.

Latest means the greatest test end date, then the newest attempt for that date.
A newer failed/incomplete attempt is not silently replaced by a passing older
one. Prior checks must match parameters, adapter hash, market, timeframe, session,
capital, costs, warmup, and delay. Adapter identity does not verify every possible
helper/environment change. Deleted evidence no longer contributes to this view.

Realized **reward/risk** is average net winning trade divided by absolute average
net losing trade. **Profit factor** is total positive net trade P&L divided by
absolute total negative net trade P&L. **Win rate** includes breakeven trades in
the denominator; **expectancy** is average net P&L per closed trade. All use
checksum-verified full baseline CSVs across the evaluation folds, never the
100-trade preview. No-loss samples have no finite profit factor; R:R is undefined
without both winners and losers. **Target R:R** is the configured target/stop
distance, when defined and constant across selected folds.

The equity scenario selector compares baseline, costs, and supported delay
tests. Regime bars attribute historical P&L to training-calibrated states; they
are not state-only backtests. The page shows test dates and newer available data,
and makes no live-market or portfolio-allocation claim.

Validate with `npm run test:dashboard`, then `npm run test:dashboard-browser`
with the app running. Browser checks and screenshots are saved under
`reports/workbench-validation/dashboard-*`.

## Removing obsolete runs

Use **Delete run** in run details, **Delete selected** in the ledger, or
**Clear all runs**. Review the affected counts before confirming. Linked
evaluation groups, regime studies, watchlist histories, and downstream retries
are included so research records do not reference missing runs. Active work must
finish or be cancelled before deletion. Changing records invalidates an earlier
deletion preview.

Deletion retains the removed records and artifacts in
`data/workbench/deleted/<deletion-id>/`. This is a local recovery archive; there
is no automatic restore button. Datasets, source snapshots, presets, and saved
views remain available. Partially deleted experiments retain their original
attempt count. Keep losing optimization trials: deleting them would hide how
many candidates were tried.

## Declared optimization campaign

`npm run research:optimize` runs or resumes the nine-strategy campaign with the
app running. The script launches development grids through the browser and
submits frozen checks through the same application API. Its saved campaign
ledger prevents ordinary resumes from repeating completed groups. Do not edit
strategy, engine, server, or environment source during the campaign: frozen
checks require the same source snapshot as the selection.

The plan uses 2022 NQ for parameter selection, then frozen 2023 and 2024 NQ
checks, doubled-cost 2024 NQ checks, and 2024 ES transfer checks. It records
33 development candidates and 36 frozen checks. Every selected configuration
gets a preset labelled with its historical outcome; unsuccessful candidates are
retained as diagnostics. Historical results are not live-trading approval.

Presets restore settings into the new-run form, which snapshots current code
when launched. To replay the preserved historical code and inputs, open the
original run and choose **Rerun identical inputs**.

Plan, exact selections, run IDs, results, and browser screenshots are saved in
[`reports/strategy-optimization-2022-2024/`](reports/strategy-optimization-2022-2024/).

## Validation commands

```powershell
npm run build
npm run lint
npm run test:workbench
npm run test:lifecycle
# With npm run dev:full running:
npx playwright install chromium
npm run test:browser
```

Lifecycle tests use isolated synthetic datasets and temporarily register a
test script. Browser tests use the real registered ZIP datasets and preserve
their validation experiments in the app. Screenshots and machine-readable
results go to `reports/workbench-validation/` (ignored by Git).

The old dashboard's modules remain in the repository. `npm test` also runs its
legacy suite, which currently has unrelated portability, missing legacy data,
and stale stored-parity failures; see `WORKBENCH_IMPLEMENTATION.md`.

Prospective paper trading, optional portfolio allocation, and brokerage execution
remain later integrations. Current regime investigations are historical research.

## 2026 carry-forward analysis

The dashboard now includes the frozen January–August 2026 NQ evaluations for all
nine strategies, with cost/delay checks and 18 regime studies. September 1–3 is
kept in separate baseline runs because it is only a partial month.

Read [the 2026 findings](reports/strategy-potential-2026/OVERVIEW.md) and
[ORB exit analysis](reports/strategy-potential-2026/ORB_EXITS.md). The exit audit
found overnight carries when no bars existed in the configured flattening window;
the historical strategy rules were preserved, and session-end handling remains
an implementation issue to address before treating ORB as strictly intraday.

With both local services running, these commands resume the saved campaign and
regenerate its analysis. Completed campaigns reuse saved run IDs.

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-analysis.txt
node scripts/evaluate-2026.mjs
.venv/Scripts/python.exe scripts/analyze-orb-exits.py
node scripts/validate-2026.mjs
node scripts/report-2026.mjs
```

For a new campaign, install analysis dependencies before launching so every run
captures the same environment. Do not reinterpret an inspected period as a fresh
holdout or silently change the frozen campaign settings.
