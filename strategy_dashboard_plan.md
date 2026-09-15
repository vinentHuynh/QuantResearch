# Strategy Research Workbench

Updated product specification and implementation plan | 14 September 2026

## 1. Purpose

Build a local application that runs the owner's Python strategy scripts against separately acquired market datasets, exposes their parameters through a UI, and collects reproducible results for comparison. Use those results to investigate which configurations have worked across different markets and conditions, then track selected configurations on newly arriving data.

The primary workflow is:

1. Register a Python strategy script.
2. Select a dataset, timeframe, date range, and execution assumptions.
3. Set parameters or define a bounded parameter sweep.
4. Run the experiment and inspect progress, errors, and outputs.
5. Compare configurations on consistent assumptions and evaluation periods.
6. Evaluate selected configurations on data excluded from their selection.
7. Freeze promising configurations in a watchlist and rerun them as new data become available.

The application describes results and records evidence. A successful script execution, profitable recent month, or high backtest Sharpe does not automatically establish trading eligibility or predict next month's performance.

Implementation now uses the existing canonical moving-average signal and the four local Databento ZIP archives (NQ, ES, YM, CL). See [WORKBENCH_IMPLEMENTATION.md](WORKBENCH_IMPLEMENTATION.md) for implementation and validation status, and [WORKBENCH.md](WORKBENCH.md) for usage. Workflow validation makes no claim about strategy performance.

## 2. What changes from the previous plan

| Area | Updated decision |
| --- | --- |
| Primary product | Python strategy runner and experiment manager. |
| First screen | Runs and experiments, with progress and saved comparisons. |
| Strategy configuration | UI forms generated from a registered parameter schema. |
| Market data | Acquired separately; the application catalogs and validates local dataset versions. |
| Strategy computation | Python subprocesses, launched and supervised by a TypeScript application backend. |
| Evidence tracking | Distinguish exploration, evaluation, and frozen forward tracking. |
| Recent performance | A descriptive watchlist, with sample size, drawdown, and data coverage. |
| Regime research | A later research module that tests predefined market-state hypotheses. |
| Allocation, risk parity, and contract proposals | Deferred until the experiment and tracking foundation works. |
| Brokerage execution | Outside the initial scope; the runner produces research artifacts, not orders. |

Retain the previous plan's requirements for versioned evidence, honest data chronology, realistic costs, continuous drawdown histories, and fair comparisons. Its capital-changing rules become future work rather than dependencies of the first release.

## 3. Core concepts and statuses

Use distinct records so that similar-looking results remain traceable.

| Record | Meaning |
| --- | --- |
| Strategy | The named trading method, its description, and intended mechanism. |
| Strategy version | A preserved code snapshot and its parameter/output schema. |
| Configuration | One strategy version with fixed parameter values and declared instrument/timeframe settings. |
| Dataset version | An immutable market-data snapshot and metadata. |
| Experiment | A question and a group of related runs, including its evaluation rules. |
| Run | One execution with exact inputs, accounting assumptions, logs, and outputs. |
| Evaluation record | Results for a selected configuration under a recorded chronological evaluation protocol. |
| Watchlist entry | A frozen configuration and its ongoing data/update policy. |
| Tracking snapshot | An append-only record of what was known and computed at a particular time. |

Keep three status fields separate:

- **Execution:** Queued, Running, Succeeded, Failed, Canceled, Interrupted.
- **Research stage:** Exploratory, Evaluation, Tracking, Archived. Record evaluation outcomes separately as Meets criteria, Inconclusive, or Does not meet criteria.
- **Tracking/data status:** Current, Stale, Incomplete, Error, or No new data.

A run can succeed technically while failing research criteria. An archived configuration remains available in historical comparisons. Missing metrics remain null with a reason, rather than becoming zero.

Do not introduce an opaque 0–100 strategy score or automatic Eligible/Ineligible trading verdict in the MVP.

## 4. User interface

### Scripts

Register trusted local Python entrypoints and inspect their available versions. Show description, parameter fields, accepted datasets, output capabilities, environment profile, and the last successful run.

An adapter can wrap an existing script. The owner should not have to rewrite every strategy into a new trading engine just to use the application.

### Datasets

Catalog the files produced by the separate data-pulling process. A chart selection resolves to instrument or instrument set, source/venue, timeframe, session/calendar, timezone, and dataset version.

Show coverage, row count, data quality, last market timestamp, and acquisition time. Let the owner register a newer version after pulling data. Keep the original dataset versions used by earlier runs.

### New Run

Choose script version, dataset, date range, research stage, parameters, costs, and sizing/accounting settings. Load a saved preset or a previous run's settings.

Support a single run and a grid of selected parameter values. Preview the number of jobs and require an explicit launch action before starting a batch. Provide a configurable maximum batch size and concurrency limit.

Example: one strategy across three instruments, two timeframes, and four lookbacks creates 24 runs. Each run remains individually inspectable within the same experiment.

### Runs & Compare — default landing page

Show recent experiments and the job queue. Useful columns include strategy version, instrument, timeframe, date range, stage, execution status, net return, drawdown, trade count, runtime, and tags.

Allow filtering, sorting, saved views, notes, reruns, and side-by-side comparisons. Do not default to ranking every run by full-history Sharpe; show the evaluation period and research stage prominently.

A run-detail drawer or page contains:

- Exact inputs and a difference view against another run.
- Equity, drawdown, monthly returns, and trade records where available.
- Metrics, accounting definitions, costs, and data coverage.
- Logs, warnings, execution environment, and downloadable artifacts.
- Development/evaluation boundaries and selection history.

### Watchlist

Show frozen configurations on recent data: MTD, last completed month, trailing 3/6/12 months when available, continuous drawdown, time underwater, trade count, and last covered timestamp.

Include a manual **Run on latest data** action. “Latest” is resolved to a specific dataset version when the job is created. Previous tracking snapshots remain unchanged.

Use readable body text, compact reasons, and details on demand. Place tables before large charts. Label units, date windows, missing values, and source types directly in the UI.

## 5. Python script interface

### Input contract

Each registered script supplies a machine-readable parameter schema. Support numeric, integer, Boolean, enum, and string parameters; descriptions; defaults; permitted ranges; and conditional requirements where needed.

The run request records:

| Field group | Required information |
| --- | --- |
| Identity | Run ID, experiment ID, strategy version, and configuration ID. |
| Data | Dataset version IDs, instruments, timeframe, session, timezone, and date bounds. |
| Parameters | Resolved values, including defaults; never just fields changed in the UI. |
| Simulation | Initial capital, sizing method, fees, spread/slippage, relevant funding, execution timing, and currency conventions. |
| Chronology | Warmup, development, validation, and evaluation boundaries; as-of cutoff where applicable. |
| Reproducibility | Code snapshot/hash, dependency/environment identity, and random seed if used. |
| Execution | Output directory, timeout, and resource/concurrency settings. |

Validate the request before queuing and again at the Python boundary. Unsupported parameter/dataset combinations should fail preflight with a useful explanation.

### Output contract

Use a small versioned protocol: an input JSON file, an output manifest, and standardized artifact files. JSON and CSV are sufficient for the first adapter; allow Parquet for larger series.

For full result comparison, require dated marked-to-market equity or returns, with defined treatment of initial capital, open P&L, fees, and cash flows. Include a final validation step before a run becomes Succeeded.

Optional artifacts include trades, fills, positions, signals, exposures, and custom diagnostics. Record capabilities so the UI can disable unsupported features. A summary-only script may be imported, but cannot supply an invented equity curve, intraperiod drawdown, or execution analysis.

Compute common comparison metrics through one versioned Python metrics module. Retain script-provided metrics as separately labeled diagnostics. Record the accounting and sampling basis of every metric; distinguish CAGR from arithmetic annualized return and define the Sharpe risk-free-rate assumption.

Retain stdout/stderr and structured warnings. Failure should identify the stage, error, and log location. Partial outputs are available for diagnosis but excluded from successful-run comparisons by default.

## 6. Execution and reproducibility

Use a persistent job queue supervised by the TypeScript backend. Run each job in a separate Python process using a registered environment and a dedicated output directory. The UI should remain responsive during long backtests.

Required behavior:

- Bound concurrent jobs, capture start/end times, and enforce configured timeouts.
- Cancel the job and its child processes; preserve the cancellation record.
- Persist queued/running state. After restart, reconcile worker liveness and mark lost jobs Interrupted rather than pretending they completed.
- Retry as a new attempt linked to the original run; retain failed attempt logs.
- Write artifacts to a temporary location and publish a complete manifest only after validation.
- Record immutable inputs at enqueue time, including for jobs waiting in the queue.
- Allow deliberate reruns with identical inputs. Deduplication may flag an existing match but must not silently replace it.

A Git commit alone is insufficient if a run used uncommitted changes. Preserve the actual relevant source snapshot, configuration, dependency lock/environment description, and local imports. Record sources of nondeterminism when exact replay is not possible.

Only registered trusted local scripts can execute in the MVP. Pass validated arguments without constructing a shell command from UI text. Separate subprocesses provide job isolation but are not a security sandbox for untrusted code. Keep the local service bound to the local machine by default and credentials outside run manifests and exports.

## 7. Dataset management

Market-data fetching remains a separate process. Register its outputs through one repeat-safe catalog/validation path; future automation can call the same path.

Each dataset version stores source, instrument mapping, timeframe, timezone, session/calendar, currency, coverage, acquisition time, content checksum, schema, and relevant preprocessing rules. Record adjustments, resampling, and futures rollover conventions when applicable.

Never identify a historical run solely by a mutable filename. Preserve an immutable copy or enforce immutable source versions. A changed file becomes a new dataset version.

Validate timestamp ordering, duplicates, expected session gaps, missing fields, and basic price/volume consistency. Distinguish market closures, legitimate no-trade periods, and missing observations.

Multi-timeframe strategies must declare all dependencies. Align observations by their availability and bar completion time. A bar's closing price cannot support an earlier fill. For data without historical publication/revision information, disclose the limitation instead of claiming point-in-time validity.

Warmup observations may initialize indicators but are excluded from scored returns. Specify how open positions and overlapping holding periods are handled at evaluation boundaries. When OHLC data cannot determine intrabar fill ordering, apply a declared assumption and flag sensitive results.

Do not silently forward-fill missing returns, mix calendars, or reinterpret timestamps to make comparisons line up.

## 8. Experiments, comparison, and evaluation

### Fair comparison

Provide two explicit comparison modes:

- **As run:** display each run's original window and assumptions, with differences highlighted.
- **Aligned comparison:** use a stated common evaluation interval and compatible accounting, costs, sizing, and currencies. Recompute displayed metrics on that interval using a declared boundary convention.

Aligned metrics are derived views, not silent changes to saved runs. If a valid comparison requires different simulation assumptions or position initialization, launch new runs.

Show net return, drawdown depth/duration, volatility, trade count, time invested, turnover, and costs where supported. Report uncertainty for research claims when the implemented method supports it. Undefined Sharpe or zero-trade statistics must not appear as successful zero-risk outcomes.

### Robustness and selection history

Group parameter sweeps by hypothesis. Include sensitivity tables or heatmaps that expose neighboring results and retain failures and losing configurations. Save the number of attempted variants, not only the chosen winner.

Add cost stress and implementation-delay scenarios before relying on a result. Different symbols and timeframes provide useful comparisons but are not automatically independent evidence.

Repeated selection among many trials can inflate apparent performance; trial history is therefore part of the product's evidence record. [Bailey and López de Prado, The Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)

### Chronological evaluation

The MVP records development and evaluation periods and configuration selection time. A later phase adds automated walk-forward experiments with training, optional inner validation, and subsequent evaluation folds.

Select parameters using only earlier permitted data. Once evaluation results influence another selection, those observations are no longer untouched for that decision. Show this lineage; do not label a rerun on previously inspected data as fresh evidence.

Walk-forward results should form a chronological evaluation path under a recorded selection rule. Handle indicator warmup, overlapping labels, open positions, and execution delays explicitly. Evaluation criteria are saved before scoring rather than chosen to fit the winner.

Freezing a configuration is an organizational action, not proof of a trading edge. Record the owner's reason for adding it to the watchlist, its evidence limitations, and the date it was frozen.

## 9. Frozen tracking and recent performance

Separate these result sources throughout the interface:

| Source | What it represents |
| --- | --- |
| Historical backtest | A simulation on an identified historical dataset. |
| Updated historical replay | The same frozen configuration recomputed through a newer data endpoint. |
| Forward paper tracking | Signals or decisions recorded before outcomes, with simulated execution. |
| Actual trading | Imported real fills, positions, and costs. |

The first watchlist implementation uses updated historical replays. Do not call them prospective paper trading merely because the job ran recently. Add forward paper tracking only when decisions can be timestamped and preserved before outcomes.

Freeze code, parameters, sizing, and cost assumptions. Extending the dataset is an expected tracking update; changing the trading definition creates a new configuration/version. Preserve corrected-data replays alongside original snapshots.

Start with full deterministic reruns if affordable. Add incremental execution only after its state, indicator warmup, positions, and results are verified against a full replay. Show the newest genuinely out-of-selection interval separately from the older research history.

Track paused or unfunded configurations in simulation so that observation does not disappear when capital is withdrawn. Do not reset equity peaks or drawdowns at month boundaries.

## 10. Regime research — subsequent phase

The first release answers “what has worked recently?” A regime module investigates whether a market condition helps explain and potentially anticipate differences in results.

Begin with a small, explicit set of measurable conditions such as trailing volatility or a defined trend measure. Record feature formula, input window, availability time, and threshold-calibration period. Labels must be computable at the decision time; thresholds chosen using the full future sample are exploratory.

For each frozen configuration, compare subsequent returns, costs, drawdown/risk, trade count, time invested, and the number of distinct regime episodes. Include uncertainty and sparse-sample warnings. Many adjacent observations in one long regime do not equal many independent episodes.

Keep descriptive same-period performance separate from a predictive test where a known state conditions subsequent outcomes. Do not introduce automatic monthly winner rotation or an opaque machine-learning classifier in the first version.

Before a regime signal changes allocations, test its entire switching policy chronologically, including transitions and costs, against always-on configurations and a simpler lower-exposure comparator. Record all candidate rules and their selection history. Inconclusive results remain inconclusive.

## 11. Architecture and storage

| Component | Initial implementation responsibility |
| --- | --- |
| React + TypeScript UI | Forms, datasets, queue, tables, charts, comparisons, and watchlist. |
| Node.js + TypeScript backend | API, registry, schema validation, queue supervision, and database writes. |
| Python strategy processes | Execute existing scripts through adapters and produce standard artifacts. |
| Versioned Python metrics module | Validate accounting and compute shared comparison metrics. |
| SQLite | Experiment metadata, jobs, artifact references, versions, notes, and tracking records. |
| Local artifact storage | Immutable source/data snapshots, large result series, and logs. |

Use the backend as the initial database writer; Python workers produce artifacts and completion messages. This avoids multiple independent script implementations modifying application tables.

Suggested logical repository areas: web application, backend, shared contracts, Python runner/adapters, strategy examples, database migrations, and documentation. This is a suggested organization, not a requirement to move every existing script immediately.

Store application code, adapter code, schemas, migrations, environment lockfiles, configuration templates, and small non-sensitive fixtures in Git. Store large market data, the database, run outputs, and credentials outside tracked Git paths.

Back up the database and referenced immutable artifacts together; a repository backup alone cannot reproduce the experiment history. Defer PostgreSQL, remote workers, and distributed queues until actual concurrency or deployment needs justify them.

## 12. Build sequence and acceptance criteria

| Phase | Deliverable | Acceptance criteria |
| --- | --- | --- |
| 1. One-script vertical slice | Register one existing Python strategy and one dataset; launch through UI; save one result. | Inputs, code, data, logs, and outputs are traceable; displayed metrics reconcile with a known fixture. |
| 2. Useful MVP | Parameter forms, dataset versions, queue/cancel/retry, presets, saved runs, bounded sweeps, comparisons, and export. | A batch survives UI refresh; failures remain visible; assumptions and date-window differences are explicit; previous runs cannot be overwritten. |
| 3. Frozen watchlist | Pin configurations, run on newer dataset versions, show recent and continuous performance. | Original snapshots remain reproducible; code/parameter changes create new configurations; result source labels are accurate. |
| 4. Evaluation tools | Walk-forward orchestration, sensitivity views, cost stress, and research lineage. | Training cannot access later evaluation data; all attempted variants and selection decisions remain visible. |
| 5. Regime investigation | Declared state features, historical conditional comparisons, and prospective tracking. | State labels use available information; episode counts and uncertainty are shown; descriptive and predictive claims are separated. |
| 6. Optional portfolio layer | Combined strategy exposures, risk monitoring, and manual allocation proposals. | Proposals meet separately declared accounting, risk, and validation requirements. |

Phases 1–2 are the initial release. Phase 3 makes the application useful for continuing observation. The product remains useful if no regime-timing policy proves beneficial.

## 13. Checks that matter before relying on results

- A rerun from the same preserved inputs reproduces results within declared numerical tolerance.
- Editing a script or replacing a data file creates new lineage rather than rewriting history.
- Parameter validation and dataset capability checks reject invalid combinations before execution.
- Queue restart, cancellation, timeout, and retry behavior cannot mislabel partial output as success.
- Known fixtures cover fees, open P&L, no-trade runs, missing data, and continuous drawdowns.
- Common metrics reconcile with the stored series and their stated date/currency/sizing basis.
- Changing future observations cannot alter an earlier decision in a strategy's claimed point-in-time replay; test representative adapters and disclose limitations.
- Sweeps and comparisons preserve evaluation boundaries and selection history.
- Corrected data do not silently replace the original tracking record.
- A database-and-artifact backup can restore a representative experiment.

These are targeted implementation gates. Add further tests when a new engine, adapter, or feature introduces a concrete additional risk.

## 14. Deferred portfolio requirements

If allocation tools are added, preserve the safeguards from the earlier plan:

- Separate research evidence, current health, and allocation state.
- Treat ordinary losses as observations; apply only explicit, evaluated timing rules or declared risk constraints.
- Compare adaptive policies with fixed/always-on and lower-exposure alternatives after realistic costs.
- Use paired resampling of policy returns when estimating differences: sample identical time blocks, recompute each metric, then subtract.
- Define denominators for budget shares, deployed exposure, and covariance-based risk contribution.
- Reconcile allocated, reserved, and unused budget, while distinguishing that bookkeeping from estimated portfolio volatility.
- Separate current positions, ideal targets, rounded feasible targets, and orders; recalculate portfolio constraints after rounding.
- Do not claim that proportional downsizing fixes cost drag in Sharpe units without a supporting size-dependent cost model.
- Preserve actual execution separately from simulations and manual overrides separately from model recommendations.

## 15. Immediate next implementation task

Take one representative existing Python strategy and one locally pulled dataset. Document the script's parameters, dependencies, data format, simulation assumptions, and current outputs. Implement the smallest adapter that can run it from a validated JSON request and return a standardized result manifest with equity/returns and logs.

Only then extend the UI and batch engine to additional strategies. This establishes the contract around real scripts before building a larger application around assumed outputs.
