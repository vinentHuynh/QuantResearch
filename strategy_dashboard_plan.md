# Strategy Health and Allocation Dashboard

Product specification and implementation plan | 6 September 2026

## 1. Purpose and initial scope

Help the owner of a portfolio of systematic strategies answer four questions:

1. Which strategy versions have credible evidence supporting their use?
2. Are their current results, execution, and exposures consistent with that evidence?
3. How much risk should each eligible strategy receive under the chosen portfolio policy?
4. Does adapting allocations improve outcomes compared with simpler alternatives?

“Currently valid” means eligible for allocation under a declared policy using information available now. It does not mean the next trade or month is predicted to be profitable. A strategy can remain valid during an ordinary drawdown, and a profitable strategy can become ineligible because of broken data or excessive risk.

The initial product is a decision-support dashboard with reproducible allocation proposals and exports. Brokerage order execution is a later integration. No user strategy data has been supplied, so this specification makes no judgments about any existing strategy.

Initial assumptions:

- One portfolio owner, multiple strategy versions, and one reporting currency.
- Daily marked-to-market returns are the preferred minimum for current-health analysis. Trade and position records unlock execution and exposure analysis.
- Monitoring updates after each completed trading day. Data and operational checks run whenever new data arrive; the interface states the actual monitoring frequency.
- Regular performance-allocation reviews occur at month-end and take effect at the next feasible trading time. Risk-limit checks can generate earlier proposals. Review cadence is configurable and versioned.
- Month-to-date, previous months, and rolling periods are visible. Performance history and drawdowns continue across calendar boundaries.
- TypeScript is used for application and calculation code.

## 2. The three independent assessments

Avoid one opaque score that combines profitability, data integrity, and portfolio risk. Store and display these dimensions separately.

| Dimension | States | Meaning |
| --- | --- | --- |
| Research eligibility | Qualified, Provisional, Rejected, Retired | Whether this exact strategy version meets its declared research acceptance criteria. |
| Current health | Normal, Watch, Breached, Unknown | Whether current operations and behavior meet the applicable checks, and whether those checks can be evaluated. |
| Allocation | Base, Reduced, Paused, No current proposal | The proposed exposure after approved policy rules and portfolio constraints. |

Every status has an assessment time, data coverage, evidence strength, reason codes, relevant metric values, and the policy version that produced it. Unknown fields remain unknown rather than becoming zeros.

Examples of the resulting user-facing combinations:

| Situation | Display | Allocation implication |
| --- | --- | --- |
| Qualified strategy, normal execution, one losing month inside expected variation | Qualified / Normal | Base policy remains applicable. A negative month alone does not trigger a pause. |
| Qualified strategy, unusually deep drawdown, no hard limit breach | Qualified / Watch | Review the evidence; apply existing risk limits. No automatic P&L penalty without an approved rule. |
| Qualified strategy whose volatility or shared exposure consumes too much portfolio risk | Qualified / Normal or Watch / Reduced | Strategy remains eligible, with less exposure because of the portfolio budget. |
| New strategy with an impressive but insufficiently validated backtest | Provisional | Research and paper trading; no new live allocation recommendation. |
| Stale prices or missing positions prevent a reliable assessment | Unknown / No current proposal | Suppress new size increases, display existing exposure and its stale timestamp, and invoke the configured data-outage procedure. |
| Known execution failure or hard risk breach | Breached / Paused or Reduced | Recommend the predefined containment action and show remaining actual exposure until resolved. |
| An approved timing policy calls for no exposure | Qualified / Paused | A temporary allocation state; the strategy continues in simulation. |

“No current proposal” is a null result, not an instruction to liquidate. “Paused” does not imply that existing positions have already been closed.

## 3. How a strategy becomes eligible

Qualification is attached to an immutable strategy version and a versioned acceptance profile. It is a research decision supported by recorded evidence; the dashboard does not automatically certify a strategy because its Sharpe is positive.

The acceptance profile records the intended economic edge, holding horizon, assets, trading calendar, minimum economically useful net performance, evidence requirements, permitted risk, and stress assumptions. Those investment thresholds must be chosen before examining the evaluation results.

The qualification checklist requires:

1. **Reproducible definition.** Code or configuration hash, parameter set, instrument universe, sizing methodology, data versions, and cost model are recorded.
2. **Credible chronology.** Development, validation, and untouched evaluation periods are identified. Document when the strategy was selected. A full-history winner cannot be presented as though it had been selected before that history occurred.
3. **Complete economics.** Returns include fees, spread, realistic slippage, funding or borrowing where applicable, and unrealized P&L. Cost assumptions are also stressed.
4. **Evidence of an economically useful edge.** Net evaluation performance meets the predeclared objective, with uncertainty intervals and dependence-aware inference. Evidence that cannot resolve economically important uncertainty produces Provisional status.
5. **Robustness.** Reasonable neighboring parameters, implementation delays, subperiods, and relevant market conditions do not reveal a result wholly dependent on one fragile assumption. Success in every subperiod is not required.
6. **Known risk behavior.** Drawdowns, time under water, leverage, exposure concentrations, liquidity requirements, and relevant jump or tail scenarios fit the stated risk limits.
7. **Recorded research acceptance.** Store the reviewer, date, evidence snapshot, acceptance profile, and any limitations.

Track all attempted strategy and allocation variants. Selection among many trials can inflate observed performance; a Deflated Sharpe Ratio may be useful when its assumptions and trial-history inputs are defensible. It is not a probability that a strategy is currently safe or will win next month. Unknown trial history must be disclosed. [Bailey and López de Prado, The Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)

Material code, universe, signal, or cost-model changes create a new version requiring review. Preserve the old version and its decisions. Rejected and retired strategies remain in the research record to avoid hiding failures.

## 4. Current-health engine

### 4.1 Data and operational checks come first

Validate timestamps, expected market sessions, duplicate observations, stale prices, missing positions, missing costs, currency conversion, and consistency between fills, P&L, and equity. Reconcile live positions with the strategy ledger when a live source exists.

Missing critical inputs make the affected assessment Unknown. Noncritical missing inputs mark the relevant feature unavailable. An imported monthly return series can support monthly research, but it cannot support an invented intramonth drawdown, slippage report, or daily risk estimate.

Use elapsed market time and expected trading sessions, not a single fixed freshness timeout for every market. Distinguish a legitimate no-trade day from missing data.

### 4.2 Performance and behavior checks

| Check | Metrics | Interpretation |
| --- | --- | --- |
| Recent performance | MTD and trailing 1, 3, 6, and 12 calendar-month net returns; rolling equity; longer-history Sharpe with uncertainty | Describe recent results. Short-window Sharpe is never the sole qualification or pause rule. |
| Evidence coverage | Days observed, closed and open trades, independent exposure episodes where estimable, time invested | Show whether a window contains enough useful information for its intended comparison. A raw trade count is not an independence guarantee. |
| Drawdown | Continuous peak-to-trough loss, duration, recovery progress, distance from risk limit | Compare current behavior with historical and simulated ranges; maintain the same continuous reference history across months. |
| Risk | Realized and forecast volatility, downside variability, exposure, leverage, margin, relevant stress losses | Identify changes in risk even if average returns have not changed. |
| Trading behavior | Hit rate, average win/loss, net expectancy, holding period, turnover, signal frequency | Flag departures from the behavior expected for the strategy and current opportunity set. |
| Execution | Spread and slippage versus model, fees, funding/borrow, fill rate, rejected orders, execution delay | Separate implementation deterioration from the underlying signal’s performance. |

There is no universal minimum of four years, 100 trades, or six months for every check. Estimating long-term return quality and detecting a broken fill feed require different evidence. Sharpe uncertainty depends on the return process and sample; use dependence-aware intervals rather than treating every observation as independent. [Two Sigma, Sharpe Ratio: Estimation, Confidence Intervals, and Hypothesis Testing](https://www.twosigma.com/wp-content/uploads/sharpe-tr-1.pdf)

### 4.3 Build expected ranges without hindsight

- Reference ranges come from data available before the assessment, preferably untouched evaluation history or chronological evaluation paths.
- Compare drawdown depth and duration at comparable horizons and risk exposure. Include ongoing, unrecovered episodes; do not analyze only completed recoveries.
- Where resampling is useful, preserve time dependence and resample the strategies together when estimating portfolio outcomes.
- Display uncertainty and limited tail coverage. A bootstrap cannot establish that historical samples contain every possible future crisis.
- Keep historical anomaly thresholds separate from hard capital, exposure, or liquidity limits. A historically normal drawdown can still exceed the owner’s risk budget.
- Calibrate alert thresholds to an explicit false-alert budget under repeated monitoring. A daily 95th-percentile alert is not automatically a 95% reliable diagnosis of failure.

A configured anomaly crossing creates a Watch alert. It records the observation, comparison range, evidence coverage, first occurrence, duration, and possible causes to investigate. It becomes a capital-changing rule only through an explicit risk limit or an independently validated allocation policy.

### 4.4 Keep live and reference performance separate

Maintain at least two labeled histories:

1. **Live performance:** actual fills, cash-flow-adjusted returns, current positions, and real costs.
2. **Continuous reference simulation:** the frozen strategy and a fixed reference sizing methodology, run whether or not it receives capital.

Use the reference history for performance-based allocation signals so that previous size cuts do not mechanically alter the signal itself. Do not reset its high-water mark when a strategy pauses or a new month starts. Show the live-reference gap and its execution or exposure explanation.

## 5. Decision and allocation rules

### 5.1 Evaluation order

For every scheduled decision, save a point-in-time input snapshot and evaluate in this order:

1. Apply independently observable emergency or hard-risk constraints. An unavailable performance feed must not erase a known margin or position breach.
2. Check critical data integrity. If inputs needed for a new proposal are missing, return No current proposal, block increases, and use the predefined outage procedure.
3. Check research eligibility. Provisional, Rejected, and Retired versions receive no new allocation recommendation. Existing exposure in these versions is explicitly flagged for review.
4. Compute current health and its reasons. Ordinary losses and Watch alerts do not automatically invalidate a Qualified strategy.
5. Apply the base allocation policy and the strategy’s declared risk limits.
6. Apply a performance or regime adjustment only when that specific policy version has passed its own validation. Otherwise its adjustment is neutral.
7. Enforce aggregate portfolio constraints using all proposed positions and their interactions. Recompute risk after changes, including removal of hedges.
8. Produce a recommendation with current exposure, target exposure, effective time, costs, reasons, and the conditions for its next review.

Use the same deterministic evaluation engine in historical replay and current proposals. The engine reads no observation whose availability time is later than the decision cutoff.

### 5.2 Base policy and portfolio constraints

Include both fixed allocations and a volatility-scaled alternative in research. For an initial volatility-scaled proposal:

**Preliminary sleeve exposure = standalone volatility budget × approved adjustment ÷ max(estimated volatility, configured volatility floor).**

The adjustment equals 1 when no performance-timing rule has been approved. The floor and exposure caps prevent an apparently quiet strategy from receiving unbounded exposure. Treat sleeve exposure as a multiplier on the reference strategy; translate it into actual instrument positions and margin requirements.

This construction balances standalone risk budgets. It does not automatically produce equal contributions to portfolio risk, which depend on covariances as well. Estimate portfolio volatility from the proposed exposure vector and covariance matrix, and report each strategy’s contribution alongside gross, net, and shared-factor exposures.

Then constrain proposals against:

- Portfolio volatility budget as an upper bound, not a requirement to spend every unit of risk.
- Per-strategy and per-strategy-family exposure limits.
- Gross and net exposure, leverage, margin, liquidity, and position limits.
- Correlated exposures to the same asset, direction, or economic mechanism.
- Relevant stress scenarios, including gap risk and nonlinear option exposure when applicable.
- Turnover and execution-cost constraints for routine changes.

When a strategy is reduced or paused, the initial policy leaves its released allocation unused. Do not automatically renormalize the remaining winners back to full exposure. Show unallocated capital explicitly. Any later policy that redistributes this allocation requires a separate comparison.

Volatility management is a benchmark to evaluate, not an assumed improvement. Research across 103 equity strategies found mixed outcomes rather than systematic superiority of volatility-managed portfolios. [Cederburg and coauthors, On the Performance of Volatility-Managed Portfolios](https://www.lehigh.edu/~xuy219/research/COWY.pdf)

### 5.3 Performance and regime adjustments

Research candidate rules using each strategy’s own continuous reference returns. Begin with a small declared set: trailing 1, 3, 6, or 12 months; drawdown depth and duration; and a neutral always-on policy. A short lookback can be tested across a long history. Do not assume the sign of the useful adjustment from a strategy label such as trend or mean reversion.

Compare continuous reductions with simple discrete states such as Base, Reduced, and Paused. Any numerical multipliers, thresholds, smoothing, or minimum holding periods are experimental parameters until validated. Keep the search small and log every tried configuration.

Add market-state variables only when a specific mechanism is documented. For example, test whether a particular spread strategy becomes untradeable when spreads and execution costs widen. Store the variable’s actual publication/availability time and revision history. A plausible explanation does not exempt the rule from out-of-sample testing.

### 5.4 Pause and restart behavior

- **Operational pause:** require the root problem to be fixed, reconciliation checks to pass, and the resolution to be recorded.
- **Risk pause or reduction:** use the predefined risk-clearance and re-entry conditions. A higher restart buffer or slower increase can be tested to limit repeated threshold crossings.
- **Performance-policy pause:** keep the reference strategy running, and resume at the next allowed trading time when its approved re-entry rule is met.
- **Research rejection or retirement:** require a new documented acceptance decision, usually for a new version.

Routine smoothing never delays an independently required hard-risk response. Show pending exits, positions that remain open, and any difference between desired and actual exposure. A stop recommendation cannot guarantee execution at a loss threshold.

## 6. Dashboard features and screens

### A. Portfolio overview — default screen

Top row: actual exposure, proposed exposure, portfolio risk estimate, current drawdown, unallocated capital, data freshness, and unresolved critical events.

Strategy table columns:

- Name and version; research eligibility; current health; allocation state.
- MTD and recent completed-month returns; trailing 3- and 12-month returns.
- Current drawdown and duration; comparison with the reference range.
- Volatility; portfolio risk contribution; shared exposure group.
- Current and proposed exposure; reason for the proposed change.
- Evidence coverage, most recent data timestamp, and next review time.

Sorting and filters: actionable issues, research status, health, asset class, strategy family, allocation state, and stale data. Color is accompanied by a text label. A green row means specified checks passed, not guaranteed profitability.

### B. Strategy detail

- Continuous live and reference equity curves, with distinct development, evaluation, and live periods.
- Drawdown chart, time-under-water chart, and historical/reference bands.
- Monthly return heatmap and rolling performance, with coverage and uncertainty.
- Execution-cost and behavior diagnostics.
- Position, asset, direction, and factor exposures where available.
- Qualification evidence and limits for the exact version.
- Timeline of status changes, pauses, restarts, overrides, and code changes.
- Explanation panel: observed metric, applicable rule, resulting state, and what would change that state.

### C. Portfolio risk workspace

- Correlation matrix with window, data coverage, and uncertainty warnings.
- Strategy and exposure-group risk contributions.
- Gross/net exposure, margin, liquidity, and stress scenarios.
- Actual versus proposed risk and unallocated capital.
- What-if reductions and pauses, including the effects of removing hedges.
- A target-versus-actual panel showing constraints that prevent an intended allocation.

### D. Allocation research lab

- Select a fixed strategy universe and evaluation dates.
- Register an experimental rule and its intended mechanism before running it.
- Inspect forward-return and forward-risk buckets for each strategy.
- Run chronological portfolio comparisons with realistic entry, exit, and resizing costs.
- Inspect uncertainty, parameter sensitivity, regime results, and the performance of rejected trades.
- Save every experiment, including failed and inconclusive results.
- Mark a policy Exploratory, In validation, Approved for paper proposals, or Approved for allocation proposals.

### E. Decisions and alerts

- Queue of new issues, grouped to avoid repetitive notifications from one ongoing event.
- Immutable decision record with inputs, policy, previous state, new state, effective time, and explanation.
- Acknowledgment, investigation notes, resolution, and override expiry.
- Manual overrides preserve both the original engine recommendation and the actual action. Do not rewrite the model’s performance to include discretionary decisions silently.
- In-app notifications in the initial version; external delivery channels can be added later.

### F. Data and strategy registry

- CSV/JSON imports, field mapping, calendar and currency settings, and reconciliation reports.
- Strategy version registration and research acceptance profiles.
- Data-source health and missing-field reports.
- Cost models, portfolio limits, policy versions, and review schedule.
- Exports of decisions, metrics, and research results.

## 7. Validation lab: proving the allocation layer adds value

### First diagnostic

For each strategy and candidate rule, use only information available at each historical cutoff to assign a state. Compare the subsequent review-period returns, volatility, severe losses, and portfolio contribution across those states.

Report sample sizes and uncertainty, including dependence between observations. Treat statistically inconclusive results as inconclusive. Equal mean returns do not imply equal risk. Per-strategy results must remain visible even when reporting portfolio aggregates.

This is a research screen. It is followed by a full simulation of allocations and execution.

### Required portfolio comparisons

| Comparator | Question answered |
| --- | --- |
| Always-on fixed allocations across the qualified strategies | What does simple diversification achieve? |
| The same allocations at a consistently lower exposure, calibrated on earlier data | Could simpler exposure reduction achieve the risk objective? |
| Always-on volatility-scaled allocations | Does adjusting to estimated risk explain the improvement? |
| Proposed performance or regime allocation policy | Does the added timing rule improve the trade-off after costs? |

Use the same data, cash return assumptions, accounting, and feasible risk constraints. Set risk targets and benchmark scaling from earlier information; do not use future realized volatility to construct supposedly live weights. Report realized risk differences explicitly.

### Chronological evaluation protocol

1. Establish which strategies and versions would have been known and eligible at each date. If that cannot be reconstructed, label the historical exercise retrospective and exploratory.
2. Select or calibrate strategy and allocation parameters using a training period.
3. Freeze those choices and evaluate subsequent periods. If comparing or tuning candidates, use an inner validation period and keep an outer evaluation period untouched.
4. Prevent training outcomes or labels from extending into evaluation periods. Handle overlapping holding periods, indicator warmup, open positions, and execution delays explicitly.
5. Simulate the next feasible trades after each decision. Do not credit returns earned before the decision could be acted on. Include the cost of entering, exiting, or resizing positions; simple multiplication of an existing P&L series can miss those costs.
6. Repeat chronologically without using a completed evaluation period to rewrite decisions already scored.
7. Preserve failed and retired strategies and all tried policy variants in the research ledger.

### Success criteria

Choose the primary objective before the experiment: for example, improve a specified downside-risk measure while keeping the annualized return reduction within a declared tolerance. Record the minimum economically meaningful improvement, acceptable return sacrifice, cost stress, and risk limits as explicit configuration values.

Evaluate net compound return, Sharpe with uncertainty, downside loss measures, maximum drawdown, recovery duration, turnover, market exposure, and stress behavior. Compare the paired differences between policies. Resample aligned time blocks across strategies and policies where appropriate, rather than treating the portfolios as independent samples.

An allocation policy advances only when the untouched evaluation supports the declared objective, results remain credible under reasonable cost and parameter changes, and a forward paper run confirms that decisions and fills can be reproduced. No fixed calendar duration alone establishes readiness. Insufficient evidence keeps the policy in research or paper mode.

## 8. Data model and calculation architecture

### Required inputs

| Input | Required content | What it enables |
| --- | --- | --- |
| Strategy definition | Identifier, version, selection date, mechanism, universe, parameters, sizing, calendar | Reproducibility and eligibility history. |
| Return/equity history | Event time, availability time, currency, gross/net P&L, fees, equity, cash flows, source type | Performance, drawdown, chronology, and reconciliation. |
| Trades and fills | Signals, orders, fills, side, quantity, price, instrument, time, costs | Execution and behavior diagnostics; accurate replay. |
| Position snapshots | Marked value, notional, direction, instrument exposures, margin when relevant | Portfolio risk, unrealized P&L, and actual-versus-target exposure. |
| Market data | Prices, FX, rates and funding, calendar, any declared regime variables | Valuation, risk, simulation, and regime research. |
| Research metadata | Data split, experiment history, acceptance criteria, results and limitations | Evidence strength and policy promotion. |

Use cash-flow-adjusted returns so deposits and withdrawals do not become trading profits or losses. Define currency conversion, cost timing, and treatment of idle cash consistently. Annualize according to the declared return calendar and inference method. Keep backtest, reference simulation, and live observations visibly separate.

### Suggested TypeScript architecture

- React with TypeScript for the interface.
- Node.js with TypeScript for ingestion, API endpoints, and scheduled calculations.
- PostgreSQL for strategy definitions, observations, versioned evidence, policies, and decision records.
- Background TypeScript workers for replay, resampling, and portfolio calculations; these run outside interactive requests.
- Shared, deterministic calculation modules used by current assessment and historical replay.

Core records: Strategy, StrategyVersion, ResearchEvidence, ReturnObservation, TradeFill, PositionSnapshot, MetricSnapshot, PolicyVersion, DecisionRun, AllocationProposal, Alert, and ExperimentRun.

Each observation stores both when the event happened and when its value was available. Each decision stores its input snapshot identity, strategy and policy versions, calculation version, cutoff, effective time, output, and reasons. Corrections create new revisions; they do not overwrite the evidence used by a prior decision.

Avoid a machine-learning regime classifier in the first implementation. Establish the accounting, baselines, and simple policy evidence first.

## 9. Build phases and acceptance criteria

| Phase | Deliverable | Acceptance condition |
| --- | --- | --- |
| 1. Data foundation | Import, registry, versioning, marked-to-market equity, and continuous reference histories | A sample strategy reconciles to its source; missing inputs and unavailable features are explicit. |
| 2. Monitoring dashboard | Overview, detail, qualification record, health checks, and alert history | Every status has an as-of time and reason; one negative month alone does not pause a qualified strategy. |
| 3. Portfolio risk proposals | Fixed and volatility-based policies, exposure limits, correlation and stress views | Proposed positions satisfy configured constraints; released risk is not automatically reallocated. |
| 4. Research lab | Conditional diagnostics, chronological replay, baseline comparisons, and experiment ledger | Decisions use only available data and include switching costs; failed experiments remain visible. |
| 5. Forward paper operation | Proposals logged before outcomes, reference trading during pauses, restart logic | No retroactive decisions; proposed and realized execution differences can be explained. |
| 6. Validated adaptive proposals | Approved performance or regime adjustments attached to exact policy versions | The policy meets its predeclared evidence and risk criteria; other candidates remain experimental. |

Phases 1–3 form the useful initial dashboard. Phases 4–6 determine whether performance-based allocation deserves a role. The initial product has value even if no timing rule passes validation.

### Important implementation checks

- Changing future observations cannot alter an earlier decision from the same saved snapshot.
- Missing or stale data cannot produce a fresh Normal assessment or be converted into a zero-return day.
- Deposits, FX conversions, financing, and open P&L reconcile correctly.
- A paused strategy continues to generate reference trades and can meet a restart rule.
- Current-month information never affects allocations before it became available.
- Strategy and policy changes do not rewrite their historical versions.
- Portfolio risk is recalculated after reducing a strategy or hedge.
- Unknown proposals cannot be mistaken for target-zero orders.
- Manual intervention is distinguishable from the model’s recommendations in performance attribution.
- Every recommendation can be reproduced from its stored inputs and versions.

## 10. Configuration required before capital-changing use

The dashboard can be built with configuration fields before these investment choices are finalized. They are not to be filled with invented “optimal” defaults:

- Markets, trading calendars, base currency, typical holding periods, and available data granularity.
- Per-strategy and portfolio risk budgets, loss limits, exposure caps, and liquidity assumptions.
- Minimum acceptable net edge, evidence criteria, and permitted performance degradation under stress.
- The downside-risk objective and acceptable return sacrifice for an allocation overlay.
- Staleness limits, review cadence, execution delay, and outage behavior.
- Pause, re-entry, and override rules; responsible decision owner.

The first implementation task is to import one or two representative strategies with daily marked-to-market equity, trade/fill records where available, and their research metadata. That establishes whether the data can support the intended checks before extending the interface to the full strategy portfolio.
