# Prior-day and overnight extremes: failure-test backtests

Both baseline backtests succeeded and their preserved trade, cost and marked-equity ledgers reconcile. Neither detector qualifies to advance under the criteria frozen before launch. Prior-day extremes show a positive but sparse development result; overnight extremes are sparse and fail the yearly consistency gate. No 2025 evaluation, 2026 extension, parameter sweep or transfer test was launched.

## Results

NQ, January 1, 2022 through December 31, 2024; 15-minute full-trading-day bars with regular-session entry eligibility, one contract and $100,000 initial capital. All profit figures include $2.50 commission and one tick slippage per side ($15 per completed trade).

| Measure | Prior-day extremes | Overnight extremes |
| --- | ---: | ---: |
| Closed trades | 42 | 61 |
| Net P&L | +$17,010 | +$7,830 |
| Net profit factor | 2.88 | 1.41 |
| Average net P&L per trade | +$405.00 | +$128.36 |
| Win rate | 23.8% | 13.1% |
| Maximum marked drawdown | 2.77% | 9.20% |
| Maximum marked drawdown, dollars | $3,187.50 | $10,580.00 |
| Total costs | $630 | $915 |
| Stop exits | 32 | 53 |
| 20-bar exits | 10 | 8 |
| 2022 net P&L | +$10,195 | +$10,590 |
| 2023 net P&L | +$3,305 | -$1,135 |
| 2024 net P&L | +$3,510 | -$1,625 |

Drawdown percentage is measured relative to the running marked-equity peak; dollar drawdown is independently measured from the equity ledger, so it is not simply the percentage multiplied by starting capital. Years use trade exit dates in Chicago time.

## Stage decisions

- **Prior-day: Backtested; insufficient sample for advancement.** All three years were profitable and the other development gates passed, but 42 trades missed the prespecified minimum of 100. Profit is concentrated in ten winning trades; the April 21, 2022 short gained $9,790, or 57.6% of total net profit. This requires more evidence before interpreting the high profit factor as stable.
- **Overnight: Backtested; development criteria failed.** The 61 trades missed the 100-trade gate, and only one of three years was profitable versus the required two. Eight winning trades supplied all winning P&L. The positive cumulative result does not offset the failed consistency criterion.

The sample threshold was proposed for this campaign because no numeric user threshold was supplied, and was preserved before scored outcomes were inspected. It was not relaxed after seeing these results. A separately declared longer-history study is a possible next step for the sparse prior-day result; it would be a new retrospective experiment, not a continuation that changes this campaign's gates.

## Tested rules

Prior-day levels are the previous scheduled 08:30-15:00 Chicago regular-session high and low, capped at the frozen exchange-calendar close. Overnight levels are the previous calendar day 17:00 through current 08:30 high and low. Each source window must contain all expected 15-minute candles, and the pre-open candle must be available.

At 08:30, freeze a zone around each level with half-width 0.10 pre-open ATR(14). Preserve the existing arming and first-visit policy: after arming from the expected approach side, any first physical touch retires that zone. A qualifying bar opens on the approach side, sweeps at least one tick beyond the far edge and closes **inside the zone**. This is not the stronger close entirely beyond the near edge. Submit one contract for the next 15-minute open in the reversal direction, expiring if that exact opening bar is missing. Set the stop one tick beyond the sweep extreme; retain the original 20 entry-inclusive chart-bar exit. New entries must occur before the calendar-adjusted regular close; existing positions can continue afterward. Both tests used the same rules and source snapshot.

Comparison with the older cluster run is descriptive: these detectors also introduce regular-hour entry eligibility, daily level expiry and a single-price zone width. It is not a controlled claim that replacing the old detector alone caused the difference.

## Verification and limitations

- Seven focused tests passed: separate prior-day/overnight references, long/short symmetry, shallow-first-touch retirement, missing-source rejection, future-price and prefix causality, holiday closes and DST wall clocks. The production build passed with its bundle-size advisory.
- For each run, all five listed artifact checksums and byte counts were checked. Independent calculations match the Workbench P&L, trade count, costs, marked drawdown and observation count. Trade P&L reconciles to ending equity. Every recorded entry is on a 15-minute regular-session opening before the calendar-adjusted close, and each trade pays the expected $15 friction. Both runs submitted and filled exactly their recorded trade counts; no pending entry expired.
- Thirty warmup days were requested. Workbench reports warmup coverage as **undeclared**, because this adapter has no declarative `warmup_bars` parameter. The adapter requires finite pre-open ATR and completed reference windows before activating levels; this is not a Workbench-certified warmup milestone.
- The data use unadjusted continuous-contract rolls; a contract transition can distort a prior-day/overnight comparison. A complete 15-minute source window does not guarantee that every minute traded or was captured. No source minute is forward-filled.
- Stops use one-minute OHLC with conservative ordering; no tick-level execution, historical order book, margin or live execution is modeled. Additional event-entry delay stress is unavailable. Higher-cost and later-period tests were not run because both patterns stopped at development.
- Previously inspected history is retrospective evidence. No matched generic sweep/reclaim control was run, so these results do not isolate the incremental value of either level location.

## Preserved identity

- Prior-day run: `739faf2a-dd89-4bcf-80f5-5884ba3e942a`.
- Overnight run: `c9062cba-e171-48e6-bf6d-1a9009a8446c`.
- Dataset: `3b9114199a2f6f0e51b70a63edc43de00940ae5df8d047b3aaa6aa8424aac9f1-v1`.
- Dataset SHA-256: `67092a9b6201747c46ae08029068fd03b42c5def68339ac2434dba78a77386c7`.
- Execution source hash (both runs): `914cef2a17853f36cb67b1b0acc6f962fb48450d6b8afa30c38ea673b3e5d113`.
- Adapter: `session-extremes-failure` version `1.0.0`, with preserved dependencies on the original cluster trigger and frozen CME index calendar.

The [frozen protocol](PROTOCOL.md), [campaign ledger](campaign.json), [independent summary](summary.json), previews and requests are saved beside this report. Complete verified local copies of each run's artifacts are under `runs/<run-id>/`; the primary Workbench records and original artifacts remain available through the app API.
