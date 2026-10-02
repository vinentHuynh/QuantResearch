# Consolidation-box boundaries with the failure-test strategy

**Backtested; development criteria failed.** The frozen eight-bar consolidation detector produced 159 completed trades, clearing the 100-trade sample floor. It lost $13,200 after costs, with net profit factor 0.66 and only one profitable calendar year. No 2025 evaluation, 2026 extension, cost-stress run or nearby-parameter search was launched after this decisive development failure.

## Tested configuration and results

NQ, January 1, 2022 through December 31, 2024, 15-minute full-trading-day bars, regular-hour entries, one fixed contract, $100,000 initial capital and 30 calendar warmup days. Costs are $2.50 commission and one tick slippage per side, or $15 per completed trade.

| Measure | Result |
| --- | ---: |
| Closed trades | 159 |
| Net P&L | -$13,200 |
| Net profit factor | 0.655 |
| Average net P&L per trade | -$83.02 |
| Maximum marked drawdown | 17.98% |
| Maximum marked drawdown, dollars | $18,842.50 |
| Total costs | $2,385 |
| Gross P&L before costs | -$10,815 |
| 2022 net P&L | -$7,625 |
| 2023 net P&L | -$5,900 |
| 2024 net P&L | +$325 |

Years use trade exit dates in Chicago time. Drawdown percentage uses the running marked-equity peak; dollar drawdown is independently calculated from the full equity ledger. The percentage is not multiplied by initial capital to derive the dollar figure.

The frozen development gates required at least 100 trades, positive net profit, profit factor >=1.05, at least two profitable years, marked drawdown <=35%, sufficient declared warmup and successful ledger reconciliation. Sample size, drawdown, initialization and execution gates passed. Net profit, profit factor and yearly consistency failed. Clearing the trade-count floor alone is not statistical validation.

## Exact box and failure rules

Eight consecutive completed 15-minute candles must have a total maximum-high to minimum-low span no greater than two completed ATR(14), calculated as the simple average of true ranges. Candle gaps reject formation. Freeze one box when the rolling window first becomes compact; another box requires an intervening noncompact window. This avoids redrawing a duplicate box on every compact candle. Different episodes can overlap and are not assumed to be independent evidence.

Freeze support and resistance zones at the two edges, each +/-0.10 formation ATR, for 80 subsequent selected candles. Formation can occur throughout the full trading day. A completed close on the expected approach side arms each edge. No formation-bar trade is allowed. The first armed physical visit consumes the edge even if it is shallow, occurs overnight or cannot be traded because a position is already open.

A qualifying bar opens outside the zone on the approach side, sweeps at least one tick beyond the far edge and closes inside the zone. Submit the reversal at the immediately following contiguous 15-minute open, with order expiry at that timestamp. The stop remains one tick beyond the sweep extreme. Keep the original 20 entry-inclusive chart-bar time exit and the exceptional-move target 1,000 signal ATR away. One open position maximum.

New entries are limited to 08:30-15:00 Chicago, capped by the preserved calendar's holiday/shortened-session close. Signal completion and next open must precede that close. Existing positions can continue outside regular hours. This retains the previous tests' regular-hour entry policy, but full-day first visits and 80-bar edge lifetimes differ from their session-only visits and daily expiry, so comparisons are descriptive.

The detector's scored funnel recorded 3,298 boxes, 5,872 consumed edges, 724 expired edges and 159 submitted entries. Many formations do not produce a qualifying, tradable first-visit failure signal; the box count is not the trade count or an independent sample count.

## Verification and limitations

- Eight focused tests passed: frozen first box/no sliding duplicates, long/short symmetry, shallow-first-touch retirement, rejection of trending windows, missing formation candles, future-price and prefix causality, nonregular first-touch consumption and warmup trading exclusion.
- Validate & preview passed for one baseline job. Declared warmup requires 22 completed bars; 1,928 were available before scoring. The worker independently reports sufficient warmup.
- The production build passed, with its bundle-size advisory. Existing unrelated workspace edits were preserved.
- All five published artifact checksums and byte counts were checked. Independent metrics match the recorded net P&L, costs, trade count, observation count and drawdown. Trades reconcile to ending marked equity; all entries are on 15-minute regular-session openings before the adjusted close; every trade pays the expected $15 friction.
- Continuous-contract rolls are unadjusted and can distort range/ATR detection and P&L. Observed 15-minute continuity does not guarantee every source minute is present. Stops use one-minute OHLC and conservative ordering, not tick-level or order-book execution. No source prices are forward-filled.
- This is previously inspected retrospective history. No matched generic sweep/reclaim baseline isolates the incremental value of box location. Additional event-entry-delay stress is unavailable; increased-cost and later-period checks were not attempted because the frozen baseline failed.

This result rejects advancement of this specific detector and execution definition under the frozen criteria. It does not establish that every consolidation-based strategy fails. The next detector in the original starting batch is confirmed higher-timeframe swing zones; it has not been launched in this campaign.

## Preserved record

- Run: `7df959e6-c519-4001-b8f5-4a33e082f12d` (Succeeded).
- Adapter: `consolidation-box-failure`, version `1.0.0`.
- Parameters: `box_bars=8`, `max_range_atr=2.0`, `zone_half_width_atr=0.10`.
- Dataset: `3b9114199a2f6f0e51b70a63edc43de00940ae5df8d047b3aaa6aa8424aac9f1-v1`.
- Dataset SHA-256: `67092a9b6201747c46ae08029068fd03b42c5def68339ac2434dba78a77386c7`.
- Execution source hash: `8ef52cf3d558be32cb091605c7a2422b059d5dc9928ebcdae33d8fee18c6081f`.

The [frozen protocol](PROTOCOL.md), [campaign ledger](campaign.json), [independent summary](summary.json), request and preview are saved beside this report. Complete verified copies are under `runs/<run-id>/`; primary records and artifacts remain accessible in Workbench.
