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

**Research → Pattern event studies** tests supply/demand, order blocks, FVGs and
support/resistance using shared causal outcomes, matched controls and a frozen
60/20/20 chronological protocol. It includes visual detection review, clustered
uncertainty, complete event exports and replication on another instrument.
See [the event-study guide](docs/workbench/EVENT_STUDIES.md) for definitions, lifecycle and checks.

1. **Datasets → Import data ZIPs** (sidebar, Sources) scans `data/` recursively. The supplied NQ,
   ES, YM, and CL Databento archives have already been registered locally.
   Imports report progress and errors. Reimporting the same archive reuses its
   version; replacing an archive creates a new version.
2. **Scripts & library → Configure run** (or **New run** on any page)
   selects a discovered strategy. New run is a four-step flow: script &
   dataset, parameters, assumptions & record, preview & launch. Seventeen adapters
   form the tracked baseline; discovery also includes local adapters. Their cards
   and run results state the migration scope; see [the Pine audit](docs/workbench/PINE_AUDIT.md).
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

The closing-window momentum adapter is documented in
[the intraday-momentum research note](docs/research/MARKET_INTRADAY_MOMENTUM.md). It includes the
Baltussen rest-of-day and Gao opening-half-hour signals, scheduled intraday
execution, market presets, and a reproducible 28-case historical regression
campaign for ES, NQ, MNQ and CL.

### Existing Python strategies

**Scripts & library → Library** indexes 150 Python sources
and 21 Pine sources (171 total), grouped by family and role. Search by filename,
description, or function; inspect original Python, command-line declarations,
requirements, and links to signal adapters. Discovery parses source without
importing or running it. Original files remain in place to preserve sibling imports.

[The strategy library](docs/workbench/STRATEGY_LIBRARY.md) contains the exportable inventory.
Regenerate it with:

```powershell
.venv/Scripts/python.exe -m workbench.library --output docs/workbench/STRATEGY_LIBRARY.md
```

Catalogued does not mean executable in the new runner. Unported intrabar rules,
multi-leg portfolios, factor panels, and research sweeps require their respective
adapters or inputs; these entries are marked **Adapter required**. An available
signal adapter covers only its stated rules, not every variant in its source file.
Signal decisions were checked against the original pure functions/canonical engine;
the workbench uses its own fixed-contract, next-open execution and accounting.

### New strategies

**Runnable scripts**, **Library**, run history, evaluations, scorecards and the
portfolio picker share current configuration stages: **Not backtested**, **Backtest
in progress**, **Backtested · awaiting evaluation**, **Evaluation in progress**,
**Failed checks · revise strategy**, **Retest required**, **Needs review**, and
**Historical evaluation passed**, **Robustness and execution validated**,
**Forward testing**, **Forward testing complete · readiness review needed**, and
**Ready for practical use**. A completed backtest establishes execution; evaluation requires all
declared current-source scenarios to pass with no unresolved matching failures.
**Passed**, **In progress**, **Failed**, and **All** organize the Portfolio Add picker;
Passed opens first. Each registered script has an expandable group of exact saved
histories and eligible baseline runs. The collapsed group previews the history with
the highest saved-window net P&L divided by maximum daily dollar drawdown, across
all research statuses, using a compact net P&L, drawdown, trades, and Return/DD
summary. Expanded histories show centered P&L, daily drawdown and that score;
dates, source status, warnings, parameters and starting capital remain visible
there. The collapsed plus action selects the displayed best history, importing
an exact raw run first if needed. Scores use end-of-day equity for raw and
imported histories. All shows
every option, including benchmarks. Run IDs remain internal for exact selection
and evidence links, while the picker and Combination rail use short Inspect run
links without displaying UUIDs.
**Benchmark** is a comparison category. Neither
advances a strategy. Scripts appear in Add even before portfolio import;
unimported completed baselines can be imported as exact single-run histories.
Any intact imported history can be added regardless of validation outcome.
Adding another history for the same script, market, and timeframe replaces that
selection while preserving other markets and timeframes. **Add shown** skips
strategy, market, and timeframe pairs already selected. An eligible saved run can
also be added directly from Runs. The portfolio Add picker links back to source runs.
Research retains source changes, failed checks and the five-stage progression:
**Development backtest → Historical evaluation passed → Robustness and execution
validated → Forward testing → Ready for practical use**. Earlier evaluated histories can be combined for historical portfolio
research; only stage 5 represents a recorded practical-readiness acceptance.
Imported `working`/`feasible` flags never advance this lifecycle.

Codex can record a stage judgment through `POST /api/workbench/runs/:id/stage-assessments`.
The body supplies `attemptedStage` (1–5), `outcome` (`passed`, `failed`, or
`blocked`), `criteria`, `findings`, `evidence` references, and `reviewer`.
The server supplies the ID, time, source/configuration identity, and evidence
snapshot. A judgment cannot award a pass before the workbench's evaluation or
readiness prerequisite exists. The research workspace shows the last completed
stage separately from a failed or blocked attempted stage. A new attempt or changed
evidence makes an older judgment stale without deleting it. An evidence-linked
failed or blocked judgment on the same stage can supersede an aggregate evaluation
pass when a stricter frozen per-fold or sample rule was not met; the display
retains the prior completed stage until that issue is resolved.

Open a configuration's **Development and practical readiness** panel from its
next-step action or run evidence. After evaluation passes, record a named review
with evidence references and findings for nearby parameters/selection,
market/regime coverage, execution/fills/costs and risk/capital. Next freeze a
prospective paper-test plan: future start, minimum calendar days and trades,
minimum net return, and maximum drawdown. The start must follow all inspected
historical windows. Record its actual external paper observations and
reconciliation; failed results remain saved and block readiness. Passing the
frozen criteria enables a separate acceptance of the operating/execution plan,
risk/stop controls, monitoring and incident/rollback procedures.

These later stages are named reviews of external evidence, not an automatically
connected paper account or broker. The server assigns timestamps, validates
prerequisites and chronology, and appends immutable review events to the seed
run's `readiness_reviews`. Notes and tags remain separate. Every event is tied
to an exact source/market/timeframe/session/parameter configuration and snapshot
of its run/evaluation facts, including capital, costs and results. Changed source,
changed evidence or additional attempts invalidate the later milestones until
reviewed again. Historical replays never establish paper performance.
Readiness acceptance records the reviewed operating scope; it does not execute
trades. Tests: `tests/node/strategy-readiness.test.mjs` and the isolated fixture
browser smoke test cover progression, skipped stages, invalidation and persistence.
The run form's **Run purpose** records intent and never awards a milestone.

Progress belongs to a source snapshot, symbol, timeframe, session and parameter
configuration. Scripts and library sources are sorted by their most promising
recorded result: validation strength, then return/drawdown and trade count.
Runnable script cards show the stage and best qualifying run's market/chart,
net P&L, drawdown, trade count and Return/DD; **Inspect best run** opens its
record. **Research history** holds the runnable script's configuration evidence
and findings. Library sources retain **Testing details** for full evidence,
reviews and job progress, and the source drawer shows implementation information.
Use **Archive script** on a runnable card to move its adapter into
`strategies_archive/`. The **Archive** tab shows where it is stored and offers
**Restore script**. Archived scripts and their saved runs, evaluations, and
portfolio histories are hidden from active workbench pages; the source and
historical records remain available for restoration. A script used as a source
dependency by another runnable adapter must be archived after its dependents.
Expand **Results and next steps by configuration** there for exact settings,
findings and linked runs. A failed
ES case cannot invalidate a passing NQ configuration. Matching unresolved checks
remain attached across dates and cost settings. Incomplete evaluations are
distinct from unmet criteria; completed, queued and summarizing jobs are separate
from milestone attainment. Older adapter evidence remains visible as requiring
a current-source retest. An unlinked library source shows its adapter blocker.

Review completion is separate from passing the tests, with the
saved adapter-wide verdict, next step and reviewed issue count. Failed evidence
stays visible under **Failure reasons and evidence**, with its market and chart.
The structured `Testing review:` line in saved run notes records the adapter
checksum, reviewed run IDs and issue fingerprints. New runs, changed failures,
or a changed adapter require another review; a tag alone does not complete it.
Market filtering retains the explicitly labeled adapter-wide review summary.
The shared status calculation supersedes imported eligibility flags for current
stage display and filtering without rewriting those historical flags or histories.
Portfolio histories are linked through exact preserved baseline run IDs and their
verified ledgers. Unlinked, missing or mixed configurations require review; changed
execution sources require retesting. Each row exposes missing checks and a matching
action: configure a backtest, plan an evaluation with exact saved settings, inspect
failed checks, or refresh portfolio evidence after a pass. Planning does not launch
jobs. Refreshing imports histories and does not award a pass. Scorecards
explicitly describe the latest evaluated configuration on the chosen market;
script/library summaries include all recorded current-adapter configurations.
Run/evaluation, scorecard and portfolio views share the same evidence calculation.

The active portfolio selection also tracks newer registered market data in the
background. Supported books receive checksum-verified historical replays through
complete UTC dates, while the portfolio keeps its previous P&L until publication.
**Follow latest** controls whether the displayed P&L end date advances with the
selected books' common coverage. Tracking replays are exploratory and do not
change evaluation or practical-readiness milestones. See
`COLLECTIVE_DASHBOARD.md` for supported books, accounting, and status behavior.

**Most viable recorded run** considers positive, traded, non-training results
matching the current adapter checksum. Passing evaluation baselines rank ahead
of individually passing cases, exploratory runs, and failed-check candidates.
Failures follow matching market/timeframe/session/parameters across dates and
cost settings. Within each group, ranking uses net return divided by absolute
maximum drawdown, then trade count and recency; zero-drawdown samples rank last.
The run's dates, market, parameters and assumptions remain inspectable. This
comparison does not promote Working/feasible status or establish a fresh holdout.
Free-text review flags display the recorded criteria and measured results;
structured evaluation failures also show the exact breached thresholds.

Checks: `npm run test:progress` and, with the built app on port 8001,
`npm run test:progress-browser`. The browser check reads saved evidence and uses
a local response fixture for mixed-market results; it launches no backtests.

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

Adapters may declare `warmup_bars`, for example
`{'parameter': 'lookback', 'multiplier': 4, 'offset': 1}` for multi-speed momentum.
The requirement is `lookback * 4 + 1` completed bars: 241 at the default lookback.
Momentum defaults to 600 calendar days, but a day count alone does not prove
coverage. **Validate & preview** reads the selected dataset and counts completed
session bars available before the scored UTC start. It checks every grid variant,
excluding unfinished bars and a partially loaded bar at the left boundary.
The worker repeats the check and preserves its result in `manifest.json` under
`warmup`, with a warning in the run detail if coverage is insufficient.
Exploratory runs remain launchable with that warning; their early signals may be
uninitialized. Strategies without this declaration have `undeclared` coverage,
not a passing warmup check. Saved source snapshots and historical runs are unchanged.

`npm run test:warmup` checks coverage boundaries and metadata;
`npm run test:state-summary` checks record-preserving projections.
With an idle workbench on port 8001, `npm run test:state-warmup` copies completed
records into a new isolated test state, verifies the API and browser on port
8003, and runs two MNQ warmup checks there. It requires MNQ data and Edge,
preserves production runs, and keeps the isolated artifacts for inspection.

Validation commands: `npm run test:library` checks inventory coverage, source
discovery, indicator parity, and causality. `npm run test:library-browser` exercises
source inspection, adapter forms, and real-data runs for the five signal adapters.
`npm run test:pine` and `npm run test:pine-browser` cover the four Pine event ports.
Screenshots and run IDs are saved below
`$env:WORKBENCH_ARTIFACTS/workbench-validation/` (default
`artifacts/workbench-validation/`).

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

Each snapshot contains the selected adapter, its declared `source_files`, and the
fixed workbench runtime needed to execute it. Declare every execution dependency;
unrelated UI and research files do not affect execution identity. Pass data through
`bars` rather than hard-coding mutable dataset
paths. Existing scripts need a small adapter exposing their signal calculation;
the app cannot infer the execution semantics of an arbitrary legacy script.
The signal template supports target-position strategies with full equity.
The Pine ports use `execution_model: 'event-v1'` and
`create_strategy(bars, parameters, request)` for close/next-open decisions and
working brackets. See [the Pine audit](docs/workbench/PINE_AUDIT.md) and the port modules for that
contract. Summary-only imports and multi-leg accounting are not implemented.

## Accounting and comparisons

The dashboard polls `GET /api/workbench/state?view=summary`, which retains inputs,
metrics (including monthly results), warnings and artifact links while omitting
per-run equity/trade preview arrays. Conditional requests use ETags and return
304 when unchanged. Opening a run fetches its complete detail from `/runs/:id`.
The original `/state` endpoint remains complete for research scripts and exports.
Research evaluation previews still travel in the summary; pagination and loading
those previews on demand remain future scaling work.

The following describes the signal runner. Pine event fills, sizing, bracket
costs, and comparison/evaluation limits are specified in [the Pine audit](docs/workbench/PINE_AUDIT.md).

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

## Evaluation and regime research

**Evaluations & regimes** adds rolling walk-forward selection, complete candidate
sensitivity tables, subsequent baseline/cost/delay tests, and a joined test equity
path. Selection uses only training results and is recorded before test jobs.
Criteria are frozen before launch. Successful execution and research outcome
remain separate; insufficient evidence is Inconclusive.

Completed evaluations support historical volatility/trend investigations. Each
fold's threshold is calibrated on training data, and preceding-bar features
classify subsequent outcomes. Reports include episodes, P&L, costs, exposure,
and seeded episode-bootstrap intervals where the sample supports them.

See [the evaluation and regime implementation notes](docs/workbench/PHASES_4_5.md) for definitions, limits, usage, and validation.

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
absolute workspace path when protocol-v1 runs are present: those historical
records retain their original absolute paths. Protocol-v2 records use logical
dataset and snapshot references resolved below `WORKBENCH_HOME`; existing v1
rows are never rewritten during restore. Evidence JSON exports include source
and environment metadata, but **do not include the large datasets** and are not
complete backups.

Configuration environment variables: `WORKBENCH_PYTHON`, `WORKBENCH_HOME`,
`WORKBENCH_ARTIFACTS` (defaults to `<repo>/artifacts`), `WORKBENCH_PORT` (8001),
`WORKBENCH_CONCURRENCY` (2, at most 8), and `WORKBENCH_MAX_BATCH` (24, at most
100). Change the Vite proxy too if changing the API port during development.
Workers receive a minimal environment rather than inheriting API credentials.

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
- **Failed criteria:** a declared criterion fails or net profit is not positive.
- **Retest required:** the adapter changed or is no longer registered.
- **Evidence repair needed:** the trade evidence is unavailable or fails verification.
- **Further testing needed:** a declared scenario is missing. The portfolio picker
  also uses this label for tested configurations without Working eligibility.
  These are next-action labels, independent of whether a review is complete.
  The scorecard's **Action needed** filter includes these states and incomplete evaluations.
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
with the app running. Browser checks and screenshots are saved below
`$env:WORKBENCH_ARTIFACTS/workbench-validation/dashboard-*` (default
`artifacts/workbench-validation/dashboard-*`).

## Archiving runs and configurations

**Runs & compare** has an **Archive** action on each finished run and
**Archive selected** for a selection. The **Archive** tab keeps archived runs
inspectable and offers **Restore**. The active latest-history view selects from
unarchived attempts.

In **Research**, select a configuration and choose **Archive configuration**.
This hides that exact source, strategy, market, timeframe, session, and parameter
group from active configurations and runs. Matching future attempts stay archived
until the configuration is restored. Its **Archive** tab offers
**Restore configuration**; runs archived individually remain archived.

Archiving preserves inputs, results, artifacts, evaluations, and stage evidence.
Active work must finish before it can be archived. Archive metadata is saved in
the workbench database, separately from the research records. The API actions are
`POST /api/workbench/runs/archive` and `/runs/unarchive` with `{"ids":["<run-id>"]}`,
and `/configurations/archive` and `/configurations/unarchive` with
`{"run_id":"<run-id>"}`.

## Removing obsolete runs

Use **Delete run** in run details, **Delete selected** in the ledger, or
**Clear all runs**. Review the affected counts before confirming. Linked
evaluation groups, regime studies, watchlist histories, and downstream retries
are included so research records do not reference missing runs. Active work must
finish or be cancelled before deletion. Changing records invalidates an earlier
deletion preview.

Deletion retains the removed records and artifacts in
`data/workbench/deleted/<deletion-id>/`. This is a local recovery archive; there
is no automatic restore button. Recover an untouched archive with
`POST /api/workbench/runs/restore` and body
`{"deletion_id":"<deletion-id>"}`. Recovery refuses record, artifact, or
post-deletion experiment conflicts and restores byte-exact SQLite bodies from
new archives. Datasets, source snapshots, presets, and saved views remain
available. Partially deleted experiments retain their original attempt count.
Keep losing optimization trials: deleting them would hide how many candidates
were tried.

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
[`artifacts/research/strategy-optimization-2022-2024/`](artifacts/research/strategy-optimization-2022-2024/).

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
results go below `$env:WORKBENCH_ARTIFACTS/workbench-validation/` (default
`artifacts/workbench-validation/`, ignored by Git).

The old dashboard's modules and legacy-only tests are preserved under
`legacy/previous-dashboard/` as source-only reference material. They are not
part of the active build, lint, or default Python test discovery.

Prospective paper trading, optional portfolio allocation, and brokerage execution
remain later integrations. Current regime investigations are historical research.

## 2026 carry-forward analysis

The dashboard now includes the frozen January–August 2026 NQ evaluations for all
nine strategies, with cost/delay checks and 18 regime studies. September 1–3 is
kept in separate baseline runs because it is only a partial month.

Read [the 2026 findings](artifacts/research/strategy-potential-2026/OVERVIEW.md) and
[ORB exit analysis](artifacts/research/strategy-potential-2026/ORB_EXITS.md). The exit audit
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
