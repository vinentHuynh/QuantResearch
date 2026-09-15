# Evaluation and regime research implementation

## Phase 4 — chronological evaluation

- Use a successful run's settings as a starting point, with a newly preserved
  current source snapshot and an explicit candidate parameter grid.
- Freeze a rolling chronological plan before any jobs launch: training length,
  test length, fold count, selection metric, minimum training trades, and
  numeric evaluation criteria.
- Run every training candidate through the existing supervised queue. Select
  using training results only; ties use candidate order. Failures and undefined
  metrics remain visible and cannot silently disappear from selection history.
- Save each selection before enqueueing its subsequent test. Test baseline,
  increased costs, and delayed execution on the same selected configuration.
- Join nonoverlapping test P&L with continuous equity/drawdowns. Each fold starts
  flat and closes flat; capital for fixed sizing is unchanged between folds.
- Expose sensitivity tables, fold lineage, logs, and downloadable results.

## Phase 5 — historical regime investigation

- On completed walk-forward evaluations, investigate a predefined trailing
  volatility or trend feature. Calibrate each fold's state threshold using its
  training period only, then classify subsequent test observations using a
  feature already available at the preceding completed bar.
- Report episodes, observations, net P&L, costs, exposure, and uncertainty using
  episode-level resampling with a preserved seed. Label sparse evidence.
- Keep descriptive attribution separate from claims about switching or trading.
  Preserve every investigation's settings and result. No automatic allocation.
- Prospective decision capture remains a separate later integration; historical
  runs must never be relabeled as forward paper records.

## Validation

Implemented and validated September 14, 2026 (America/Chicago).

| Check | Evidence |
| --- | --- |
| Python research fixtures | Six tests: future-price perturbations, lagged features, nonpositive prices, costs/delay, continuous fold accounting, episode counts and seeded uncertainty |
| Existing workbench fixtures | Eleven tests continue to pass |
| Research API integration | Synthetic rising-training/falling-test fixture proves selection precedes adverse test outcomes; all candidates retained; failed grids stop; no eligible candidate gives Inconclusive; cancellation/restart preserve earlier selections |
| Regime API integration | Training thresholds saved for each fold; state P&L sums to the baseline test P&L; sparse intervals remain unavailable |
| Real Chromium walkthrough | Ten NQ jobs across two folds; page-refresh persistence, sensitivity, selection lineage, three test scenarios, historical volatility analysis, CSV downloads, mobile layout; no browser runtime errors |
| Build and lint | Frontend/backend TypeScript checks, production bundle, and ESLint pass |

Machine-readable results and screenshots are in
`reports/workbench-validation/research-*-results.json` and `research-*.png`.
The real evaluation and its investigation remain in the application's ledger.
The fixture's outcome labels validate the research protocol; they do not
establish a trading edge.

## Running the new workflow

1. Open **Evaluation & Regimes** and select a successful run to reuse its
   settings. A new current source snapshot is preserved at launch, including
   the TypeScript selection code and package lock.
2. Set the research interval, rolling training days, subsequent test days,
   fold count, and candidate grid. Training ends strictly before each test;
   test intervals never overlap. The implementation supports rolling windows,
   one dataset/timeframe per evaluation, at most 12 candidates, and at most
   100 total planned jobs. Inner validation and expanding windows are not yet
   implemented.
3. Declare the selection metric, minimum training trades, baseline test-return,
   drawdown and trade-count criteria, plus cost and execution-delay stress.
   Preview the schedule and launch explicitly. Criteria and all settings are
   frozen before the first job. The highest finite training score wins;
   candidate order breaks ties. A negative winner can still be selected if
   that is what the declared rule chooses.
4. Inspect the fold sensitivity tables. Every selection lists its training
   cutoff, timestamp, candidate scores, and linked runs. Selection is stored
   before the subsequent test jobs are created. Candidate failures interrupt
   the protocol; successful grids with no qualifying candidate are Inconclusive.
5. Inspect the joined baseline, cost-stress, and delayed-execution paths.
   Fixed sizing capital is unchanged; dollar P&L is joined with continuous
   equity peaks. Each fold starts/ends flat and pays liquidation costs. Baseline
   outcome and stress outcomes are separate. A prior-overlap list records
   successful older runs on the same market/test dates.
6. On a complete evaluation, choose trailing volatility or trend, its bar
   lookback, and the training quantile. Each investigation is a new saved
   record. Repeated feature choices remain visible and are exploratory.

### Regime definitions and limits

Pine event ports now support baseline and higher-cost evaluations and regime
studies. Their additional execution delay is fixed at zero because delaying
event orders is not implemented; the result warns that delay robustness is
untested. Signal strategies retain optional delay stress (zero omits it).
Event trade ledgers record the exact execution bar for entry attribution,
including orders filled at a bar's close.

The nine-strategy 2025 campaign uses the previously selected parameters without
retuning, a full 2024 calibration year, and a full 2025 test year. Run or resume
it with `node scripts/evaluate-potential.mjs` while the app is running. Results
are saved in [reports/strategy-potential-2025/](reports/strategy-potential-2025/).
The completed campaign contains nine evaluations, 32 successful child runs,
and eighteen successful regime studies. See the
[potential overview](reports/strategy-potential-2025/OVERVIEW.md) for each
strategy's results and limits. `node scripts/validate-potential.mjs` verifies
the accounting, unchanged 2024 economics, charts, regime tables and downloads.

- Volatility: sample standard deviation of trailing positive-price bar returns.
- Trend: close divided by trailing mean close, minus one.
- Both features are lagged one completed bar; an availability check prevents
  using a bar that was not complete at the next bar's opening.
- Each fold computes its threshold from finite training observations only
  (at least 20). Values at/below the threshold are Lower; values above it are
  Higher. Nonpositive-price/undefined windows are Unknown and remain reported.
- Consecutive same-state bars form an episode; fold boundaries break episodes.
  Confidence intervals resample whole episode dollar P&L, 1,000 times with a
  preserved seed. Fewer than ten episodes gives no interval. Episodes may still
  be dependent: these intervals are descriptive, not a predictive test.
- Entry counts belong to opening-bar states. Trades can cross states; this is
  not a closed-trade performance partition. Costs, invested bars, and P&L are
  attributed from the saved bar-level ledgers. Disconnected state subsets do
  not receive misleading drawdown curves.
- Regime studies are specified after inspecting evaluation results. There is
  no trading switch, allocation recommendation, or prospective performance
  claim. Prospective signal capture is still unimplemented.

### Reproducibility and recovery

The existing queue bounds all strategy jobs. Scheduling reuses already-created
fold jobs after a partial scheduling interruption. Running jobs lost on backend
restart remain Interrupted and prevent incomplete-grid selection; start a new
evaluation to repeat a failed protocol. Completed selections are never replaced
by manually rerunning one of their child jobs. Research summarization is bounded
to one subprocess, captures logs, has a timeout, and uses a supervisor lease.
Source and input artifact checksums and dependency versions are checked before
analysis. As with the original workbench, trusted local scripts are not sandboxed:
the data supplied to their signal function excludes later evaluation prices,
but arbitrary malicious Python is outside the isolation guarantee.

```powershell
npm run test:research
npm run test:research-api
# With npm run dev:full running:
npm run test:research-browser
```

Phase 6 is explicitly optional in the specification and is not part of this
evaluation/research increment.
