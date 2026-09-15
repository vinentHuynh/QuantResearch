# Strategy workbench implementation

## Scope

Implement the September 14 specification's initial release (phases 1–2) and
frozen historical replay watchlist (phase 3). Phase 4 evaluation and the historical
research portion of phase 5 are now implemented; see [PHASES_4_5.md](PHASES_4_5.md).
Prospective decision capture and the optional portfolio phase remain deferred.

## Implementation sequence

1. Inspect the supplied Databento ZIP metadata and normalize each instrument to
   an immutable, content-addressed dataset. Preserve source checksums, coverage,
   quality findings, and preprocessing conventions.
2. Define a JSON/Python contract and a copyable `strategies/_template.py`.
   Discover literal metadata automatically; preserve actual source on enqueue.
   Adapt the existing moving-average calculation as the representative script.
3. Add a local TypeScript API and SQLite queue with bounded concurrency,
   cancellation, timeout, retry, restart reconciliation, and artifact validation.
4. Make Runs & Compare the landing page; add generated parameter forms, bounded
   sweeps, dataset inventory, presets, logs, exports, and frozen replay tracking.
5. Verify accounting on deterministic fixtures, lifecycle failures and replay,
   then exercise the running application in a real browser using local ZIP data.

## Decisions

- Keep existing research modules and the previous dashboard available as source;
  the new workbench has its own API and database.
- `strategies/*.py` is the trusted registration directory. A literal `STRATEGY`
  dictionary supplies metadata without executing a module during discovery.
- One local Python environment; dependencies and interpreter identity are saved
  per source snapshot. No credentials are exported.
- ZIP ingestion runs out of process, with progress and repeat-safe registration.
- Tracking is explicitly an updated historical replay, not prospective paper
  trading. No scores or trading eligibility labels.

## Validation record

Validated September 14, 2026 (America/Chicago).

| Check | Result |
| --- | --- |
| TypeScript frontend + backend checks and Vite production build | Pass |
| ESLint | Pass |
| Workbench Python fixtures | Pass: execution timing, fees, resizing/reversal reconciliation, no-trade statistics, continuous drawdown, schema/discovery, aligned-calendar rejection, and causal template/adapter signals |
| Isolated lifecycle integration | Pass: discovery, invalid inputs, bounded queue, cancellation, timeout, failure logs, restart recovery, identical replay, source edits, corrected-data tracking, evidence export |
| Chromium application walkthrough | Pass: eight runs across NQ/ES/YM/CL and two lookbacks, all succeeded; refresh persistence, comparisons, equity/drawdown, notes, artifacts, watchlist, and mobile layout |
| Browser runtime errors | None in the completed walkthrough |
| Frozen update against latest endpoint | Succeeded; original configuration and earlier snapshots retained |
| Full legacy + new Python suite | Legacy failures remain: 3 assertion failures and 15 errors in the earlier 53-test run; see below |

### Imported data

| Archive instrument | Registered one-minute bars |
| --- | ---: |
| NQ | 4,812,017 |
| ES | 4,924,584 |
| YM | 4,782,024 |
| CL | 4,788,547 |

Total: **19,307,172 bars**, with actual coverage saved per version. The archives
query June 2010 through September 2026. Import did not fetch market data or
alter the original ZIPs.

### Validation artifacts

`reports/workbench-validation/browser-results.json` records the eight real-data
run IDs. `lifecycle-results.json` records isolated lifecycle checks. The same
directory contains desktop, mobile, dataset, new-run, comparison, detail, and
watchlist screenshots, plus `legacy-suite.log`. These generated files are
excluded from Git. Those original validation runs were subsequently cleared at
the user's request; their records and artifacts are retained in the deletion
backup documented below.

### Run cleanup and new optimization campaign

The 35 previous runs, 14 experiment records, one evaluation, one regime study,
and two watchlist records were cleared through the application. The local backup
is `data/workbench/deleted/73dad7e8-d63b-4edc-918f-98aa28463aad/`.
All four datasets and nine strategy adapters were preserved.

The ledger now supports individual deletion, selected deletion, and clearing
all runs, with dependency previews, active-job guards, stale-preview checks,
and local archives. Partial experiment deletion preserves the original number
of attempted variants. Failed and interrupted runs can be selected for deletion;
comparisons still require successful runs.

The replacement research campaign and its results are documented in
[`reports/strategy-optimization-2022-2024/`](reports/strategy-optimization-2022-2024/).
It completed 69 successful runs (33 development candidates and 36 frozen
checks), retained two interrupted attempts with successful retries, and saved
nine presets. Pine TSMOM intraday ORB passed all declared historical criteria;
the other eight selections remain labelled as diagnostics.

Validation passed: production build, lint, deletion dependency/archive checks,
11 workbench tests, and 12 Pine-port tests. The final browser audit opened every
strategy's holdout evidence, verified charts and artifact downloads, loaded and
validated all nine presets, exercised both comparison modes, and cancelled
individual and bulk deletion previews. It also verified frozen source/parameter
identity and doubled-cost P&L reconciliation for all nine strategies. The audit
record is `reports/strategy-optimization-2022-2024/browser-validation.json`.

### Evaluation dashboard

The **Dashboard** tab reads current persisted evaluations, regimes, strategy
discovery, and complete trade artifacts through `GET /api/workbench/dashboard`.
It provides candidate/review status, scorecards, selectable profit/equity charts,
execution stress, regime attribution, and direct links to the exact evidence.
R:R, profit factor, win rate and expectancy use all closed trades and reconcile
to evaluation totals. Undefined ratios and missing/invalid evidence remain
explicit. The initial NQ view shows one research candidate (Pine TSMOM ORB), two
conditional candidates (overnight block/drift), five needing review, and one
benchmark. These statuses derive from records; no strategy results are hardcoded.

Validation covers ratio edge cases, more than 100 trades, CSV quoting, checksum
changes, incomplete latest attempts, prior flags, changed adapters, and new or
unevaluated strategies. The browser audit checks all nine strategies, filters,
charts, evidence navigation, market isolation, and mobile layout. Build and lint
pass. Screenshots and results are in `reports/workbench-validation/dashboard-*`.

### Remaining limitations

- The legacy suite reports Windows SQLite file-handle cleanup errors, absent
  `data/root_charts/NQ` and `ES` legacy paths, and stale stored parity fingerprints
  (which also affect its expected catalog counts). The old Python API and engine
  modules were not modified to conceal those failures. The new workbench uses
  its own database and immutable imported dataset paths.
- Full snapshot backup/restore has documented same-path instructions; an
  automated portable restore tool has not been implemented or tested.
- The consolidated library indexes 91 Python and 17 Pine sources and exposes
  five signal adapters plus four Pine event ports. See [PINE_AUDIT.md](PINE_AUDIT.md)
  and [STRATEGY_LIBRARY.md](STRATEGY_LIBRARY.md)
  for exact scope and remaining execution/data requirements. New target-position
  strategies use the automatic template.
- Signal and Pine event protocols require complete marked equity. Pine event
  ports support close/next-open orders and one-minute brackets. Summary-only
  imports, other strategy-specific fill rules, historical environment recreation,
  event-order delay stress, and multi-leg strategies need further adapters.
- Dataset gaps are counted but not fully classified against an exchange holiday
  calendar. Continuous futures roll gaps remain a disclosed performance caveat.
- Walk-forward selection and historical regime analysis are covered in the next
  increment, [PHASES_4_5.md](PHASES_4_5.md). Prospective paper tracking and optional
  portfolio allocation remain later integrations.

See [WORKBENCH.md](WORKBENCH.md) for commands and precise accounting conventions.
