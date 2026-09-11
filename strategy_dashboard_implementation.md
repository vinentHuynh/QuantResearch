# Strategy Health and Allocation Dashboard — implementation record

Implemented 7 September 2026 from `strategy_dashboard_gap_plan.md`.

Canonical runner continuation completed 9 September 2026.

## Delivered

- Independent, exact research eligibility (`Qualified`, `Provisional`, `Rejected`, `Retired`), current health (`Normal`, `Watch`, `Breached`, `Unknown`), and allocation (`Base`, `Reduced`, `Paused`, `No current proposal`) states.
- Immutable strategy-version registration plus append-only eligibility assessments with reviewer, evidence strength, selection date, acceptance objective, evidence references, limitations, and cutoff-aware history. Rejected and retired records remain available.
- CSV or JSON-compatible observation ingestion with event and availability times, source identity, currency, typed backtest/reference/paper/live histories, append-only corrections, duplicate detection, and missing-versus-zero preservation.
- Cash-flow-adjusted equity returns; current and maximum drawdown; drawdown duration; MTD and completed-month returns; trailing 1/3/6/12-month returns; realized volatility; Sharpe; live/reference curves and gap; coverage and feature-availability records.
- Fill and position diagnostics for fees, slippage, fill rate, rejected orders, execution delay, gross/net exposure, margin, and liquidity usage when supplied.
- Versioned portfolio configuration with explicit incomplete fields, policy lifecycle, staleness, cadence, outage handling, owner, volatility/gross/margin constraints, and no invented investment defaults.
- Deterministic cutoff-aware allocation engine with emergency constraints first, missing-data gate, eligibility gate, fixed or volatility-scaled sleeves, floors/caps, portfolio gross/margin/volatility constraints, covariance and risk contributions, unallocated capital, and explicit null targets.
- Hedge-sensitive what-if recalculation, including cases where removing a hedge raises risk.
- Immutable decision records with input material, calculation/policy versions, effective time, reason codes, and reproducible snapshot hashes. Reproduction restores the sealed inputs into an isolated database, reruns the allocation calculation, and compares the resulting output hash.
- Grouped alert episodes with acknowledgment and resolution, manual overrides with owner/reason/expiry, and separate original recommendations.
- Allocation research experiments with a fixed universe, declared mechanism, chronological dates, costs, four required comparators, correct transition costs, deterministic aligned block-bootstrap uncertainty, failed/inconclusive preservation, and policy states. Append-only reviews require untouched evaluation evidence for paper approval and forward paper evidence for allocation approval.
- Scheduled review status derived from the configured cadence, the previous sealed decision cutoff, and hard-risk events. The browser refreshes monitoring state every minute and reassesses immediately after an import.
- JSON/CSV exports, paginated backtest-run access, immutable run-analysis revisions, verified provenance hashes/artifacts, and timestamped compatibility equity exports.
- Portfolio, Health, Risk, Decisions, Allocation Lab, and Registry screens, alongside the existing Backtests, Run History, Run Analysis, and Chart Data screens.
- A consolidated runnable-backtest catalog with one entry per implemented mechanism. Chart and supported timeframe are independent run inputs, generic strategies resample from normalized one-minute data, and every folded legacy script remains recorded in run provenance.
- A shared canonical engine for opening-range breakout, prior-range fill, session drift, multi-speed time-series momentum, moving-average trend, cross-sectional momentum, and pairs mean reversion. The two portfolio strategies receive an explicit chart universe with per-leg contract economics; no strategy discovers peer data implicitly.
- Named timezone-aware New York RTH, Globex overnight, full trading day, London, and Asia sessions. The catalog audit now maps all 23 identified legacy strategy scripts to canonical implementations pending frozen-data parity, with zero compatibility adapters and zero unmapped strategies.
- Hash-bound frozen parity evidence for the first two legacy calculations. Moving-average trend has exact sleeve-level signal and daily-return parity; multi-speed momentum has exact score and direction parity. Both remain explicitly partial because legacy portfolio, sizing, and feed differences have not been reconciled.
- A normalized accounting layer separates closed exposure episodes from mark-to-market P&L observations; derives actual orders and fills from target-position changes; preserves zero-P&L sessions in equity and Sharpe; and reconciles gross P&L, round-trip turnover costs, net P&L, and session equity. Close-driven signals use explicit bar-availability timestamps, and intraday session variants flatten before excluded-session gaps.
- Automated run analysis reports closed trades, active sessions, orders, and P&L observations independently. A date range alone is no longer described as credible chronology: that check remains Unknown until both bounded development and evaluation periods, or recognized out-of-sample evidence, are supplied.
- Position-based canonical strategies expose an explicit fractional research mode and a whole-contract execution mode. Whole-contract targets truncate toward zero, never increase requested absolute exposure, flow through the same turnover-cost and accounting ledgers, and are recorded with their sizing contract in `run_spec.json` and `summary.json`.

## Safe initial state

The 26 runner strategies are registered as Provisional with Unknown health and No current proposal. No live, paper, or reference observations were inferred from backtest artifacts. Portfolio settings have deliberately blank investment fields. This means the product is operational while capital-changing recommendations remain disabled.

To enable a real proposal, register an exact Qualified version with its recorded acceptance evidence, import reference and live or paper observations, configure the owner-approved limits and outage behavior, and approve that exact policy version for allocation proposals. Brokerage execution and external notifications remain outside the product scope.

## Verification

Run:

```bash
npm test
npm run build
npm run lint
```

The automated suite covers unknown versus zero, hard-risk containment, future-data isolation, cash-flow accounting, separate live/reference histories, append-only versions and eligibility decisions, hedge removal, scheduled reviews, effective-time chronology, sealed decision re-execution, experiment promotion gates, consolidated runner identity, chart-count/session/timeframe validation, lagged canonical signals, explicit close availability, intraday session flattening, closed-exposure accounting, zero-session Sharpe inputs, multi-chart dataset hashes, run revisions, fake hashes, missing artifacts, empty chronology, overlapping trade counts, and zero coverage.

The application remains on the repository's existing React/TypeScript and Python/FastAPI/SQLite stack. Calculation and persistence code is in `dashboard_api/portfolio.py`; PostgreSQL and a durable external worker queue are deployment-scale substitutions, not requirements for this local single-owner implementation. The calculation version and all input snapshots are stored so those components can be replaced without rewriting historical decisions.
