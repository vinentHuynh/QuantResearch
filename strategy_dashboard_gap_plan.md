# Strategy dashboard: implementation audit and completion plan

> Implementation update: the local product described by this audit was implemented on 7 September 2026. See [strategy_dashboard_implementation.md](strategy_dashboard_implementation.md) for delivered behavior, safe initial state, and verification. Items whose completion depends on real owner configuration, qualified evidence, forward paper observations, or broker data remain unavailable by design rather than being filled with sample claims.

Audit date: 7 September 2026. Source: the supplied **Strategy Health and Allocation Dashboard** specification, also recorded in [strategy_dashboard_plan.md](strategy_dashboard_plan.md).

## Finding

**The specification is not fully implemented.** The current application is a working research-run browser and local Python backtest runner. It has reusable catalog, result, provenance, and validation infrastructure, but does not yet implement the specified portfolio health and allocation product. No build phase meets all of its acceptance conditions.

This audit covers the current working tree, including existing uncommitted implementation changes. Application code and existing work were left intact; this document is the deliverable. Historical scripts and static examples are not counted as dashboard features unless connected to the required records, calculations, API, and interface.

The README and Overview explicitly exclude allocation and live-health views until approved strategies and broker data exist. That is narrower than the supplied specification: historical imports and paper observations can support development and proposals; brokerage order execution is a later integration. Missing live inputs should make affected features unavailable rather than prevent building the product.

## What was verified

| Check | Result | Limit of this evidence |
| --- | --- | --- |
| `npm run build` | Passed TypeScript compilation and Vite production build | Does not establish calculation correctness or browser interaction correctness. |
| `npm run lint` | Passed | No dedicated dashboard test command is defined in `package.json`. |
| Python syntax parsing | All `dashboard_api/*.py` files parsed successfully | Does not execute every API or backtest path. |
| Existing local API, read-only HTTP requests | `/api/health`, `/api/strategies`, `/api/charts`, `/api/runs` returned HTTP 200; catalogs returned 26 strategies, 5 charts, and 8 runs | Existing process may differ from current files; strategy results were not independently reproduced. |
| Temporary SQLite repository | Save/load worked; another save with the same ID replaced the previous payload | Run persistence exists, but this is not immutable decision/evidence storage. |
| Synthetic validation/analysis probes | Reproduced the issues in the next section | Used temporary files and imported helper modules; did not modify the real run registry. |
| Dashboard test inventory | No dedicated dashboard unit, integration, or browser test suite found | Backtest scripts and research robustness routines are not product acceptance tests. |

No new full backtest, visual browser walkthrough, historical allocation replay, or source-to-ledger reconciliation was performed. Consequently, existing screens are implementation evidence, not certification that every interaction or strategy works correctly.

## Defects and limitations to address first

| ID | Evidence | Required correction and acceptance check |
| --- | --- | --- |
| F01 | `dashboard_api/validation.py:12`: `extract_sample({'sessions': 0, 'trades': 0})` returns `(None, 0)` because coverage uses truthiness. `dashboard_api/analysis.py:122` displays `0 sessions; zero trades` when sessions are missing. | Preserve missing versus zero at every boundary. Fixtures must distinguish unknown sessions, an observed zero, and a legitimate session without trades. |
| F02 | `dashboard_api/analysis.py:77` recognizes chronology by field names. A summary containing `evaluation_period: null` produced a `CHRON` result of `pass`. | Require typed evidence, actual period boundaries, selection/registration timestamps, and data split validation. A field name alone cannot pass chronology. Retrospective evidence remains explicitly exploratory. |
| F03 | `dashboard_api/analysis.py:107` sums trade counts from every discovered performance section. Two overlapping 50-trade summaries displayed 100 reported trades. | Use a declared primary population or unique trade IDs. Keep alternative variants and subperiods separate; do not imply independent observations. |
| F04 | `dashboard_api/analysis.py:59` combines percent and dollar drawdowns into one untyped field, then `:171` takes their minimum. A fixture returned `-5` percent and `-500` dollars without units. `src/App.tsx:118` also labels fallback drawdown metrics `Max DD %`. | Store metric value, unit, denominator, sign convention, source, and window. Compare only compatible metrics; verify percent, dollar, positive-depth, and negative-return conventions. |
| F05 | `dashboard_api/validation.py:23` accepted 64-character non-hex strings as hashes and an artifact-list entry whose file did not exist, returning `data_validated`. | Validate actual artifact existence/content, provenance structure, and referenced inputs. Separate recorded fingerprints from verified reproducibility; do not claim source reconciliation from metadata checks. |
| F06 | `dashboard_api/repository.py:43` upserts run payloads and replaces validation/artifact rows. `dashboard_api/main.py:432` may regenerate analysis on startup when the analysis version changes and persist it over the old result. | Keep operational run lifecycle updates, but append immutable analysis revisions and sealed evidence snapshots. Old evidence and decisions must remain retrievable after calculation upgrades and corrections. |
| F07 | `dashboard_api/main.py:555` returns only the newest 50 runs; repository loading defaults to 100. The UI has no history pagination. | Add persistent pagination and filters so failed, retired, and older experiments remain visible. Test beyond both current limits and after restart. |
| F08 | `scripts/dashboard_compatible_strategy.py:268` writes cumulative trade P&L as `equity.csv`, without event timestamps in that output. This alone is not daily marked-to-market equity including open positions. | Treat compatibility outputs as research artifacts until a typed adapter proves accounting and strategy-definition fidelity. Import daily valuations, open positions, costs, and timestamps separately. |
| F09 | `src/data.ts` contains hardcoded portfolio statuses, exposures, correlations, and research claims. No imports from it were found in the active app. | Quarantine as clearly labeled demo fixtures or remove when implementing the real views. Never reuse these values as observed data, acceptance criteria, or approved policy defaults. |

These probes demonstrate specific failures; they do not establish that all stored runs have those failures. F02 and F05 are especially important because a passing label currently overstates what the underlying check establishes. Automated analysis still correctly leaves research status `not_reviewed`; keep that separation.

## Specification coverage

Legend: **Partial** means reusable implementation exists but the full requirement is unmet. **Missing** means no connected product implementation was found. **Present, limited** identifies an existing supporting feature, not a completed specification phase.

| Requirement | Status | Current evidence and remaining work |
| --- | --- | --- |
| §1 daily monitoring, configurable/versioned review cadence, next feasible effective time | Missing | Current refresh polls runs; there is no market-session assessment/review scheduler. |
| §2 three independent assessments and exact state sets | Missing | `src/store.ts:55` models technical run validation and heuristic research analysis. It lacks research eligibility, current health, and nullable allocation proposals as independent domain records. |
| §2 assessment timestamps, coverage, evidence strength, metric reasons, policy identity | Partial | Runs have lifecycle timestamps; checks have messages/evidence. No complete assessment envelope or policy version association. |
| §3 immutable exact strategy version and acceptance profile | Partial | Hardcoded frozen Python definitions and run hashes exist; no persistent version registry, selection date, predeclared acceptance profile, or material-change workflow. |
| §3 reproducibility, chronology, economics, useful edge, robustness, known risk, reviewer acceptance | Partial | `dashboard_api/analysis.py:98` extracts heuristic checks. It does not verify the qualification checklist or record reviewer acceptance and limitations. |
| §3 all strategy/allocation attempts, lineage, failed and retired versions, trial-history disclosure | Partial | Runner history preserves individual jobs; no comprehensive variant/research ledger, lineage, retirement, or defensible trial-history inference. |
| §4.1 imports, session-aware validation, duplicates, stale marks, positions, costs, FX, reconciliation | Partial | Chart metadata and post-run artifact checks exist in `charts.py` and `validation.py`. No observation-level ingestion/reconciliation or critical-input health engine. |
| §4.1 monthly-only data and feature availability | Missing | No granular capability model preventing daily-risk, intramonth drawdown, or execution claims from unsupported inputs. |
| §4.2 MTD, completed months, trailing 1/3/6/12 calendar months, equity, Sharpe uncertainty | Partial | Research page displays reported summary metrics and generic artifact charts. No shared calendar-aware metric engine or dependence-aware intervals. |
| §4.2 evidence coverage, exposure episodes, invested time, open/closed trades | Partial | Heuristic session/trade extraction only; F01 and F03 apply. |
| §4.2 continuous drawdown, duration, recovery, limit distance | Partial | Some scripts report drawdown; no continuous portfolio/live/reference history or corresponding dashboard diagnostics. |
| §4.2 realized/forecast risk, downside variation, leverage, margin, stress | Missing | No connected current-risk assessment engine. |
| §4.2 behavior and actual execution diagnostics | Partial | Some reported trade statistics and assumed cost inputs are displayed. No measured/model slippage, spread, funding, rejected-order, fill-rate, delay, or behavioral comparison pipeline. |
| §4.3 historical ranges without hindsight, ongoing episodes, joint dependent resampling | Missing | Script-specific research routines are not integrated assessment ranges with cutoff and coverage metadata. |
| §4.3 false-alert budget, anomaly versus hard-limit distinction, Watch episode tracking | Missing | No calibrated monitoring policy or alert-episode lifecycle. |
| §4.4 separate live and continuous frozen reference histories | Missing | No continuously running reference ledger or live/reference attribution. |
| §5.1 deterministic ordered decision engine shared by current/replay, cutoff snapshots | Missing | No allocation decision engine, input-availability filtering, snapshot contract, or recommendation record. |
| §5.2 fixed and volatility-scaled policies, floors/caps, instrument translation | Missing | Individual backtests may implement sizing; no dashboard proposal engine enforcing this specification. |
| §5.2 covariance, contributions, portfolio/family/asset limits, stress, costs, liquidity | Missing | No portfolio-level constraint evaluation or actual-versus-proposed risk calculation. |
| §5.2 unused released allocation, no automatic redistribution | Missing | No proposal engine; unused capital must be implemented explicitly. |
| §5.3 small registered timing candidates, regime publication/revision times, approved-version gating | Missing | Runner parameters are not a validated allocation-policy registry. |
| §5.4 operational/risk/performance pause and restart, remaining actual exposure | Missing | No pause lifecycle, clearance record, pending exit, or reference continuation. |
| §6A portfolio Overview and specified columns, sorting, filters | Missing | `src/App.tsx:77` is a research overview with catalog/run counts, not the specified portfolio overview. Text accompanies status colors, which can be reused. |
| §6B strategy detail charts, heatmap, exposure, evidence, timeline, explanation | Partial | `src/App.tsx:90` lists strategy definitions/runs; the runner shows analysis explanations and artifact previews. Most specified detail features are absent. |
| §6C portfolio risk workspace and hedge-aware what-if | Missing | Not in navigation or application state (`src/store.ts:4`, `src/App.tsx:195`). |
| §6D allocation research lab, forward buckets, sensitivity, rejected trades, promotion | Partial | `src/App.tsx:115` compares saved scalar run summaries. No allocation experiments or promotion workflow. |
| §6E decisions, grouped alerts, acknowledgments, notes, resolution, expiring overrides | Missing | Overview counts validation warnings; this is not an issue queue or immutable decision history. No in-app notification lifecycle. |
| §6F CSV/JSON import with mapping; currency/calendar/settings; acceptance/limits/policy registry | Partial | `src/App.tsx:121` displays predefined Databento datasets. No general import wizard or configuration editor. |
| §6F exports | Present, limited | Existing artifacts can be downloaded; decisions, metric snapshots, and allocation-research exports do not exist. |
| §7 conditional forward-return/risk diagnostics and per-strategy uncertainty | Missing | No dashboard implementation. |
| §7 four required portfolio comparators under consistent accounting/feasible constraints | Missing | No integrated fixed, lower-fixed, volatility-scaled, and candidate-policy replay comparison. |
| §7 nested chronological protocol, eligibility at time, overlap/warmup/delay handling | Partial | Some standalone scripts perform chronological research; no common auditable portfolio evaluator. |
| §7 predeclared success criteria, paired intervals, stressed costs/parameters, paper gate | Missing | No objective registry or evidence-based promotion gate. |
| §8 typed observations, event/availability times, revision history, cash-flow accounting | Missing | SQLite stores run payloads, checks, and artifacts, not the required financial observation/decision records. |
| §8 React/TypeScript app and calculation architecture | Partial | React/TypeScript interface exists. Backend/calculations are Python/FastAPI with SQLite, rather than the specified TypeScript calculation system and suggested Node/PostgreSQL services. |
| §8 background calculations outside interactive requests | Partial | `ThreadPoolExecutor` runs Python jobs in the API process; no durable worker queue or market-session scheduler. Input hashing still happens in run creation. |
| §9 acceptance tests and ten important implementation invariants | Missing | No dedicated automated product acceptance suite found; see required tests below. |
| §10 explicit owner configuration before capital-changing use | Missing | Backtest parameter forms do not cover portfolio limits, evidence objectives, outage/re-entry rules, or responsible decision owner. |

## Completion plan

Use the existing React/Mantine interface and runner as a research-artifact source. Build the new domain and financial calculation engine in TypeScript, as the specification requires. Retain Python research scripts behind an explicitly versioned adapter boundary; their outputs must not inherit research approval merely because they run successfully.

Suggested new layout: `packages/domain/` for schemas and state contracts; `packages/calculations/` for deterministic accounting, health, allocation, and replay; `server/` for Node API and PostgreSQL persistence; `workers/` for ingestion, assessments, replay, and reference simulation; `src/features/` for the six product workspaces; `tests/fixtures/` for reproducible acceptance datasets. These are proposed paths, not existing implementation.

### Milestone 0 — trustworthy inputs and contracts

Dependencies: none. This is the first implementation work.

- Address F01–F09 with focused regression checks where behavior is affected. Expose metric units and preserve raw source summaries.
- Inventory one or two representative strategy datasets and their metadata. Prefer one strategy with positions spanning sessions and one with intraday fills so unrealized P&L and legitimate flat sessions are both exercised. Existing backtests remain labeled backtest sources.
- Define typed records for Strategy, StrategyVersion, AcceptanceProfile, ResearchEvidence, ReturnObservation, TradeFill, PositionSnapshot, MarketObservation, MetricSnapshot, PolicyVersion, InputSnapshot, DecisionRun, AllocationProposal, Alert, Override, and ExperimentRun.
- Record event time, availability time, ingestion time, source type, currency, units, source identifier, and revision ancestry. Separate lifecycle events from immutable finalized evidence.
- Make unknown values nullable; use explicit `No current proposal` with a null target. Define `Paused` as a target recommendation with independently tracked actual positions.
- Record per-feature input requirements. Treat legacy history with unknown availability or selection dates as retrospective/exploratory; do not fabricate those timestamps.

Exit condition: representative data and all missing fields are documented; schema fixtures distinguish unknown from zero and research findings from eligibility. The current runner still builds and its artifacts remain accessible.

### Milestone 1 — data foundation and versioned registry (spec phase 1)

Dependencies: milestone 0.

- Add PostgreSQL migrations and append-only observation/evidence revisions. Import existing run metadata without inventing acceptance decisions or historical eligibility.
- Build CSV/JSON upload, preview, field mapping, timezone/calendar/currency configuration, row validation, duplicate handling, and reconciliation reports. Preserve original files and content identities.
- Implement cash-flow-adjusted daily marked-to-market returns, unrealized P&L, fees/spread/slippage, financing/borrow, FX conversion, cost timing, and idle-cash accounting under declared conventions.
- Register exact strategy definitions, code/config/dependency/data/cost-model versions, sizing, universe, selection date, mechanism, holding horizon, and reference sizing. Compatibility implementations receive distinct versions; validate fidelity before associating original research evidence.
- Build acceptance profiles and reviewer decisions with predeclared objectives, periods, evidence, stress/risk limits, uncertainty, limitations, and attempted-variant lineage. Preserve Rejected and Retired versions.
- Add explicit calendar-session coverage, legitimate no-trade markers, stale-source information, and monthly-only capability restrictions.
- Initialize separately labeled backtest, reference, paper, and live histories; add complete exports and paginated access.

Exit condition: one or two imported strategies reconcile to their source under a documented tolerance, including deposits, FX, open positions, and costs. Corrections preserve prior revisions. Unsupported metrics remain unavailable.

### Milestone 2 — monitoring and explanations (spec phase 2)

Dependencies: milestone 1.

- Implement versioned research eligibility and independent current-health assessments with exact specified states, assessment times, coverage, evidence strength, metric values, reasons, and policy versions.
- Run input/operational checks on arrival and assessments after completed expected trading sessions. Store actual run frequency, holiday/timezone behavior, retry state, and data cutoffs.
- Calculate MTD, completed months, trailing 1/3/6/12 calendar-month returns, continuous equity/drawdown/duration/recovery, realized/forecast volatility, downside variation, and evidence coverage.
- Add behavior and execution diagnostics when supported: hit rate, average win/loss, expectancy, holding period, turnover, signal rate, measured versus modeled spread/slippage/costs, funding, fill rates, rejected orders, and delays.
- Build expected ranges from earlier evidence at comparable horizon/exposure. Include unresolved drawdowns, dependence-aware uncertainty, tail-coverage warnings, and a declared repeated-monitoring false-alert budget.
- Keep Watch anomalies separate from hard constraints. A negative month or Watch alone must not impose an unapproved performance penalty.
- Build portfolio Overview and strategy Detail: specified metrics/filters, live/reference curves and period labels, drawdown/time-under-water bands, monthly heatmap, execution/exposure panels, qualification evidence, and explanation timeline. Allocation fields remain unavailable until milestone 3.
- Introduce grouped in-app alert episodes with first occurrence, duration, evidence, acknowledgment, investigation, resolution, and ongoing-event deduplication.

Exit condition: every status has provenance and an as-of time; missing/stale critical inputs yield Unknown; ordinary monthly losses do not pause a Qualified strategy; continuous histories survive month boundaries.

### Milestone 3 — portfolio risk and reproducible proposals (spec phase 3)

Dependencies: milestones 1–2. This completes the initial useful product only after its acceptance tests pass.

- Implement one deterministic evaluation function accepting a sealed input snapshot, decision cutoff, calculation version, policy version, and effective time. It must have no implicit current-time or latest-data reads.
- Enforce the specified order: observable emergency/hard constraints; critical-data gate; research eligibility; health; base limits; approved timing adjustment; aggregate constraints; explained proposal. Preserve known breaches even when a performance feed is unavailable.
- Implement fixed exposure and volatility-scaled sleeves using the configured volatility floor and caps. Unapproved performance adjustments equal 1. Leave released allocation unused.
- Translate sleeve multipliers to instrument targets using current reference positions, contract economics, lot rounding, and margin. Recalculate all portfolio constraints after rounding and every reduction or hedge removal.
- Compute aligned covariance, portfolio volatility, risk contributions, and gross/net/shared exposures with coverage/uncertainty metadata. Enforce portfolio volatility, strategy/family, asset/direction/factor, leverage, margin, liquidity, position, and stress limits; include gap/nonlinear scenarios where relevant.
- Apply routine turnover/cost constraints without delaying hard-risk responses. When a feasible proposal cannot be established, show the binding issue and explicit outage/containment outcome; do not silently emit unconstrained targets.
- Store current and target exposure, pending exits, effective time, estimated costs, reason codes, next review, owner, and original recommendation. Keep remaining actual exposure visible when a target is zero or null.
- Build Risk workspace, hedge-aware what-if, target-versus-actual constraints, unallocated capital, and portfolio Overview proposal columns.
- Add immutable decision snapshots, reproduction/export endpoints, versioned month-end review cadence, next feasible execution timing, and earlier risk-triggered proposals.
- Implement operational/risk pause clearance, recorded resolutions, re-entry conditions, override owner/reason/expiry, and separate original-model versus manual-action attribution.

Exit condition: configured constraints hold after instrument translation; removed allocation is not redistributed; null proposals never become zero-position instructions; saved recommendations reproduce from exact inputs and versions. No brokerage order placement is required.

### Milestone 4 — allocation validation lab (spec phase 4)

Dependencies: milestones 1–3, especially the shared deterministic decision engine.

- Register the fixed strategy universe, mechanism, candidate parameters, objective, minimum meaningful improvement, acceptable return sacrifice, limits, cost stress, and training/validation/untouched evaluation periods before running an experiment.
- Start with neutral always-on, trailing 1/3/6/12-month reference-return and drawdown-depth/duration candidates. Log discrete/continuous multipliers, smoothing, re-entry buffers, and every attempted configuration. Regime variables require a documented mechanism plus publication and revision times.
- Show per-strategy forward-return/risk buckets, sample sizes, dependent uncertainty, severe losses, and contribution. Preserve inconclusive outcomes and evaluate rejected trades.
- Replay current decisions with the same engine, historical eligibility, and availability cutoffs. Handle warmup, overlapping labels/holdings, purging at split boundaries, open positions, next feasible execution, and entry/exit/resizing costs explicitly.
- Compare all four required policies: always-on fixed; lower fixed exposure calibrated on earlier data; always-on volatility-scaled; candidate timing policy. Use shared accounting, cash returns, data, cost assumptions, and feasible constraints; report realized risk differences.
- Report net compound return, uncertain Sharpe, downside measures, maximum drawdown/recovery, turnover, exposure, stress, parameter sensitivity, regime/subperiod results, and paired differences using aligned joint time blocks where appropriate.
- Persist all successful, failed, rejected, and inconclusive experiments. Use durable background jobs with progress, cancellation, retries, and reproducible random seeds.
- Build Research Lab and exports with Exploratory, In validation, Approved for paper proposals, and Approved for allocation proposals states, backed by evidence gates rather than a cosmetic status selector.

Exit condition: changing later observations cannot change prior decisions; switching costs are included; all comparators and failed trials remain inspectable; insufficient evidence cannot pass the declared objective.

### Milestone 5 — forward paper operation (spec phase 5)

Dependencies: milestones 1–4. Reference-ledger foundations start in milestones 1–2; this milestone proves continuous operation.

- Freeze a paper-approved policy and log proposals before outcomes and before their effective time. Record missed runs without generating retroactive decisions.
- Keep the frozen reference simulation running through allocation pauses with its original high-water mark and sizing methodology.
- Simulate feasible fills/resizing and retain differences between desired positions, paper fills, actual observations where available, and reference trades.
- Exercise operational, risk, and approved performance-policy pause/restart paths; require recorded reconciliation and clearance where applicable.
- Prove scheduler recovery, idempotence, outage handling, alert lifecycle, override expiry, and model/manual attribution across restarts.

Exit condition: forward decisions and fills can be reproduced; paused reference strategies can meet re-entry rules; execution/exposure differences can be explained without rewriting prior recommendations.

### Milestone 6 — evidence-gated adaptive proposals (spec phase 6)

Dependencies: milestones 4–5 and actual qualifying evidence.

- Evaluate untouched results against the exact predeclared objective, risk limits, permissible return sacrifice, cost/parameter stresses, and forward-paper reproducibility record.
- Store reviewer, evidence snapshot, limitations, and promotion for the exact policy version. Material changes require a new version and review.
- Enable performance/regime adjustments only for allocation-approved versions, with their configured effective times, pauses, and re-entry rules. All other candidates remain neutral for allocation proposals.
- Monitor ongoing policy evidence and preserve rejection, retirement, overrides, and historical decisions.

Exit condition: promotion is supported by the declared evidence and forward checks. Software completion does not imply that any timing rule will qualify; an inconclusive or unsuccessful candidate remains in research/paper mode. Fixed and volatility-based decision support remain useful independently.

## Required automated acceptance tests

Add focused calculation tests, database/API integration tests, and browser workflow tests. The following maps all ten important implementation checks in specification §9 to concrete acceptance cases.

| Test | Required scenario | First milestone |
| --- | --- | --- |
| T01 — future isolation | Change observations available after a saved cutoff; replay returns the same earlier decision and snapshot identity. Include late data revisions and future regime publications. | 3, then replay in 4 |
| T02 — missing and stale inputs | Delete a price/position; cross session-aware freshness limits; check Unknown/null proposal without a manufactured zero return. Holidays/no-trade sessions stay distinct. A known margin breach still produces its predefined containment outcome. | 1–3 |
| T03 — accounting | Deposits/withdrawals do not create profits; FX, fees, financing, unrealized P&L, and idle cash reconcile to a fixture ledger. Monthly-only inputs do not unlock daily metrics. | 1 |
| T04 — reference during pause | Pause a funded strategy; reference trades/equity/high-water mark continue across months; a permitted re-entry becomes possible from reference signals. | 2, completed in 5 |
| T05 — feasible timing | Month-to-date observations and month-end signals affect only later feasible targets/fills; no pre-decision returns are credited; entry/exit/resizing costs are charged. | 3–4 |
| T06 — immutable versions | Revise code, universe, cost model, profile, or policy; previous evidence and decisions retain their original versions after restart and recalculation. | 1, 3 |
| T07 — hedge removal and constraints | Reduce a negatively correlated hedge; verify recomputed total risk can increase, then enforce constraints after all changes and lot rounding. Released risk remains unused. | 3 |
| T08 — null versus zero | Round-trip API/DB/export/UI with null target and target zero; null never becomes a liquidation instruction, and both retain actual exposure. | 0, 3 |
| T09 — manual attribution | Apply and expire an override; original recommendation, manual action, owner/reason, actual execution, and performance attribution remain separate. | 3, 5 |
| T10 — reproducibility | Re-run a saved recommendation from frozen observation revisions, strategy/policy/calculation versions, and seeds; compare output, reasons, costs, and effective time. | 3–5 |

Additional gates: F01–F05 regression fixtures; one negative month and Watch do not automatically pause; unapproved policies cannot change sizing; evidence thresholds are profile-specific; failed experiments remain visible beyond 100 records; ongoing drawdowns are included in reference ranges; approval fails when chronology or uncertainty is insufficient. Browser tests cover import/reconciliation, version acceptance, Overview filters, Detail, what-if proposals, experiment history, alert resolution, override expiry, and exports using real test APIs.

## Configuration and completion boundaries

Build editable, versioned configuration now; leave unchosen investment values unset. Capital-changing proposals require an identified decision owner and explicit markets/calendar/base currency, holding horizon/granularity, risk and loss budgets, exposure/liquidity limits, minimum net edge/evidence criteria, stress assumptions, overlay objective/return sacrifice, freshness/outage procedures, cadence/delay, pause/re-entry rules, and override policy. Missing required configuration produces an explained unavailable proposal.

Development and testing can proceed with clearly labeled fixture policies. User-approved investment settings and actual evidence are required before a policy receives allocation approval; they are not prerequisites for building imports, monitoring, or research workflows.

The immediate next deliverable is **milestone 0 followed by the milestone 1 import/reconciliation slice for one or two representative strategies**. Finish phases 1–3 before describing this as the specified initial portfolio dashboard. Phases 4–6 establish whether adaptive allocation adds value; brokerage execution and external notifications remain later integrations as the specification states.
