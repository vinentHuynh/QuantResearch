Fresh SND stateful backtest — September 16, 2026

40 fresh simulations completed; 320 period/cost rows. 0 of 20 market/variant combinations pass every 2024–2026 next-open base/double-cost check.

These are 40 fresh state-machine simulations: five markets × four SND variants × two execution models. Each rebuilds zones, tracks first physical touches, applies its filter before trade selection, and updates the one-position state through every source minute. RVOL uses the prior 20 observations in the same Chicago time slot, at least 10 observations, and a frozen 0.75 inclusive to 1.25 exclusive band at the first touch. No old trade ledger is used to produce the new runs.

NQ, ES, YM and CL score January 2018–August 2026, with 2017 warmup. MNQ scores from its May 2019 archive inception. The reports separate the earlier period, calendar 2024, calendar 2025, and January–August 2026. September data is replayed only to reconcile the complete old MNQ references and is excluded from scored results. These periods have been inspected in prior research; they are not untouched holdouts.

**No SND variant passes the complete recent-period screen**

All 40 fresh stateful runs completed. None of the 20 market/variant combinations meets positive marked profit, drawdown no worse than 35%, and at least 10 closed trades in each of 2024, 2025 and January-August 2026 under both base and doubled costs. This screen is descriptive rather than statistical. The tests support retaining SND as research; they do not support promoting any tested configuration to live trading.

**The primary MNQ/NQ tests do not show consistent recent performance**

Every MNQ and NQ variant has at least one losing recent period with next-open execution. All eight lose in 2024. Earlier pooled gains or a strong 2026 therefore do not establish a stable edge. The recent periods were already inspected in prior research, so they should not be described as untouched out-of-sample evidence.

**MNQ prior-5m RVOL has almost no 2025 cost headroom**

The prior-5m RVOL variant earns $14.50 in 2025 from 185 trades: $662 gross against $647.50 in costs. Doubling costs turns that into a $633 loss. Removing its five best trades leaves a $1,043 loss at base costs. It also loses $2,757 in 2024, before recovering $1,620.50 in January-August 2026. This is too weak to promote on the pooled result.

**MNQ prior-1m RVOL is a recent observation to track, not a validated winner**

In January-August 2026 it earns $2,552.50, with a 1.43 closed-trade profit factor, 123 trades and approximately 0.60% marked drawdown at the stated $100,000 benchmark. It remains $1,421 positive after removing its five best trades. However, it loses $1,555.50 in 2024 and $2,046 in 2025, and the corresponding NQ variant loses $5,635 in 2026. That lack of consistency across years and feeds limits the inference. MNQ and NQ use separate OHLC and volume histories, so their RVOL signals are not expected to be identical or related by simple tenfold P&L scaling.

**Execution assumptions materially change the answer**

For MNQ original SND, 2026 changes from a $1,332.50 loss with the old touch-reference fills to a $5,033.50 gain with next-open execution. Next-open fills can improve or worsen performance; they are not a universal haircut. They can change entry prices, gap treatment and entry-bar exits. Both complete paths are retained so their differences can be reviewed against actual orders. Neither is certified as exact TradingView parity.

**NQ exposes substantial dollar risk**

With one NQ contract, Phase 6 next-open earns $46,710 in 2026, but loses $12,592.50 in 2024 and $21,785 in 2025. Its 2024 marked drawdown is about 29.55% of the stated benchmark path. Original SND's earlier NQ next-open path falls below zero equity at $100,000 starting capital; that path is infeasible without additional capital, and the simulator does not model margin liquidation. Percentage-risk sizing could produce a different path and has not been tested here.

**Daily-zone attribution is weak on both primary markets**

Within the original shared-position next-open strategy, daily-zone trades lose in each of 2024, 2025 and 2026 on both MNQ and NQ. Their combined recent losses are $5,410.50 on MNQ and $59,515 on NQ. The 4h contribution is positive across the combined recent period but negative in 2025 on both markets. These are closed-trade attributions inside the combined state machine, not independent timeframe-only backtests. Removing a timeframe would be a new experiment because it changes which positions can be taken.

**Literal transfer to ES, YM and CL does not rescue the rules**

Every ES variant loses in 2024 and 2025. YM prior-5m RVOL gains $4,750 in 2024, then loses $3,860 in 2025 and $4,195 in 2026. CL original SND gains only $237.50 in 2024 and $1,845 in 2025, then loses $46,283.75 in 2026. Neither CL RVOL variant reaches 10 closed trades in 2025. No CL next-open trade reaches a profit target during these three recent periods: all exits are stops, gap stops or timed closes. The original 100/200/400 price-point targets and one-point buffer are unsuitable as an assumed equal-risk market translation; any normalized alternative must be declared and tested as a new strategy.

**Next steps, in order**

First reconcile same-feed TradingView signals and orders against these timestamped ledgers, including first-touch eligibility, prior-5m availability, next-open fills and timed closes. Then simulate the actual intended percentage-risk or fixed-dollar sizing preset with contract rounding and capital/margin limits. Only after those match should one frozen configuration be tracked prospectively on new data. The MNQ prior-1m RVOL version has an interesting 2026 profile, but its failed 2024/2025 results remain part of the evidence. Treat timeframe isolation, roll handling and tick/volatility-normalized cross-market parameters as new experiments; preserve these failed baselines and do not relabel inspected years as untouched holdouts.

| Market | Variant | 2024 next-open net | 2025 next-open net | 2026 Jan–Aug next-open net | Later decision |
| --- | --- | ---: | ---: | ---: | --- |
| MNQ | Original SND · 1h/4h/daily | $-2,502.00 | $-8,495.50 | $5,033.50 | Fails later checks |
| MNQ | Phase 6 · first touch + room | $-2,185.50 | $-4,101.00 | $4,155.00 | Fails later checks |
| MNQ | Phase 7 · prior 1m RVOL | $-1,555.50 | $-2,046.00 | $2,552.50 | Fails later checks |
| MNQ | Phase 7 · prior 5m RVOL | $-2,757.00 | $14.50 | $1,620.50 | Fails later checks |
| NQ | Original SND · 1h/4h/daily | $-12,737.50 | $-33,755.00 | $81,240.00 | Fails later checks |
| NQ | Phase 6 · first touch + room | $-12,592.50 | $-21,785.00 | $46,710.00 | Fails later checks |
| NQ | Phase 7 · prior 1m RVOL | $-1,340.00 | $2,137.50 | $-5,635.00 | Fails later checks |
| NQ | Phase 7 · prior 5m RVOL | $-26,887.50 | $-11,772.50 | $16,552.50 | Fails later checks |
| ES | Original SND · 1h/4h/daily | $-46,632.50 | $-22,587.50 | $-42,430.00 | Fails later checks |
| ES | Phase 6 · first touch + room | $-34,775.00 | $-6,787.50 | $9,875.00 | Fails later checks |
| ES | Phase 7 · prior 1m RVOL | $-8,972.50 | $-25,220.00 | $-9,520.00 | Fails later checks |
| ES | Phase 7 · prior 5m RVOL | $-30,577.50 | $-11,707.50 | $10,235.00 | Fails later checks |
| YM | Original SND · 1h/4h/daily | $-12,140.00 | $2,020.00 | $-21,347.50 | Fails later checks |
| YM | Phase 6 · first touch + room | $-142.50 | $-11,762.50 | $-8,890.00 | Fails later checks |
| YM | Phase 7 · prior 1m RVOL | $-1,400.00 | $-1,842.50 | $-965.00 | Fails later checks |
| YM | Phase 7 · prior 5m RVOL | $4,750.00 | $-3,860.00 | $-4,195.00 | Fails later checks |
| CL | Original SND · 1h/4h/daily | $237.50 | $1,845.00 | $-46,283.75 | Fails later checks |
| CL | Phase 6 · first touch + room | $-7,797.50 | $-12,287.50 | $-31,152.50 | Fails later checks |
| CL | Phase 7 · prior 1m RVOL | $-3,085.00 | $-2,425.00 | $-4,695.00 | Fails later checks |
| CL | Phase 7 · prior 5m RVOL | $-3,290.00 | $-2,970.00 | $-3,187.50 | Fails later checks |

The descriptive screen requires positive marked profit, no more than 35% marked drawdown, and at least 10 closed trades in each recent period under both base and doubled costs. It is not a statistical proof of an edge.

**Exactly what was tested**

Execution uses one-minute bars. The inherited engine blocks new signals from 15:00 to 16:00 Chicago time and uses its 15:00 crossing rule for timed closes, after checking stop/target exits; next-open orders already submitted can fill at that boundary. Original SND permits 1h, 4h and daily zones with shared-position priority. Phase 6 and both Phase 7 variants trade only 1h zones while retaining all three context timeframes. Phase 6 requires the first physical-touch episode and at least two structural R to an opposing zone, or no opposing zone. Phase 7 adds frozen prior-1m or prior-5m RVOL. This tests SND’s intended timeframe structure; it does not invent hourly execution for a one-minute strategy.

Touch-reference execution preserves the existing research engine, including its same-bar proximal entry assumptions. The source-derived next-open version confirms the touch first, fills at the next available minute open, preserves the submitted zone-based stop and target, and permits exits on the entry bar. Gap stops fill at the opening price. Known marketable targets at the open precede unknown later intrabar events; otherwise ambiguous stop/target bars resolve stop-first. This is an explicit execution variant, not certified TradingView runtime parity.

Every primary simulation uses one fixed contract. Each reported window measures marked P&L against $100,000 starting equity; no risk-based resizing is applied. Base costs are $1.25 commission per side plus one tick of slippage per side: $3.50 round trip for MNQ, $12.50 for NQ/YM, $27.50 for ES, and $22.50 for CL. Double-cost paths are exact arithmetic accounting stresses of the same fixed-size trades, not additional state-machine simulations. The Pine file’s percentage-of-sizing-equity mode is not tested here.

Original price-point distances are preserved: 100/200/400-point targets by zone timeframe, a 100-point stop cap, one-point distal buffer, and 75-point rearming distance. Thus ES/YM/CL are literal rule-transfer diagnostics, not calibrated or equal-risk substitutions for MNQ/NQ. A distant target may make timed exits dominate, especially in CL. No cross-market parameter optimization was performed.

Equity includes open P&L at one-minute closes and half the round-trip cost while a position is open. Trade timestamps follow source-minute conventions; equity is stamped at minute close. Period marked P&L can differ from closed-trade P&L around boundaries, and both are reported. Sharpe uses UTC calendar-day close marks and a square-root-of-252 annualization; it is an approximate descriptive statistic, not a significance test. Unknown intraminute excursions, unadjusted contract rolls, session gaps, margin liquidation, funding and queue priority remain unmodeled. Negative-equity paths are infeasible at the stated capital. TradingView same-feed/order-size parity remains unresolved.

**Checks and reference reconciliation**

- MNQ Phase 6 · first touch + room: PASS; 3915 fresh versus 3915 reference trades; mismatches {'entry_time': 0, 'exit_time': 0, 'direction': 0, 'entry_price': 0, 'exit_price': 0, 'zone_id': 0, 'gross_pnl': 0}.
- MNQ Original SND · 1h/4h/daily: PASS; 6475 fresh versus 6475 reference trades; mismatches {'entry_time': 0, 'exit_time': 0, 'direction': 0, 'entry_price': 0, 'exit_price': 0, 'zone_id': 0, 'gross_pnl': 0}.
- MNQ Phase 7 · prior 1m RVOL: PASS; 1173 fresh versus 1173 reference trades; mismatches {'entry_time': 0, 'exit_time': 0, 'direction': 0, 'entry_price': 0, 'exit_price': 0, 'zone_id': 0, 'gross_pnl': 0}.
- MNQ Phase 7 · prior 5m RVOL: PASS; 1483 fresh versus 1483 reference trades; mismatches {'entry_time': 0, 'exit_time': 0, 'direction': 0, 'entry_price': 0, 'exit_price': 0, 'zone_id': 0, 'gross_pnl': 0}.

All original data, source and artifact checksums were checked. Full minute-by-minute closed P&L, position quantities and open-equity marks reconcile independently to trade events and source closes. Seven focused execution/state tests and two native-engine sample parity comparisons passed. RVOL eligibility is verified against saved first-touch features for every filtered trade.

**MNQ / Original SND · 1h/4h/daily**

Fails later checks. 2024 base_cost: nonpositive marked profit; 2025 base_cost: nonpositive marked profit; 2024 double_cost: nonpositive marked profit; 2025 double_cost: nonpositive marked profit

**MNQ / Phase 6 · first touch + room**

Fails later checks. 2024 base_cost: nonpositive marked profit; 2025 base_cost: nonpositive marked profit; 2024 double_cost: nonpositive marked profit; 2025 double_cost: nonpositive marked profit

**MNQ / Phase 7 · prior 1m RVOL**

Fails later checks. 2024 base_cost: nonpositive marked profit; 2025 base_cost: nonpositive marked profit; 2024 double_cost: nonpositive marked profit; 2025 double_cost: nonpositive marked profit

**MNQ / Phase 7 · prior 5m RVOL**

Fails later checks. 2024 base_cost: nonpositive marked profit; 2024 double_cost: nonpositive marked profit; 2025 double_cost: nonpositive marked profit

**NQ / Original SND · 1h/4h/daily**

Fails later checks. 2024 base_cost: nonpositive marked profit, drawdown above 35%; 2025 base_cost: nonpositive marked profit, drawdown above 35%; 2024 double_cost: nonpositive marked profit, drawdown above 35%; 2025 double_cost: nonpositive marked profit, drawdown above 35%

**NQ / Phase 6 · first touch + room**

Fails later checks. 2024 base_cost: nonpositive marked profit; 2025 base_cost: nonpositive marked profit; 2024 double_cost: nonpositive marked profit; 2025 double_cost: nonpositive marked profit

**NQ / Phase 7 · prior 1m RVOL**

Fails later checks. 2024 base_cost: nonpositive marked profit; 2026 base_cost: nonpositive marked profit; 2024 double_cost: nonpositive marked profit; 2026 double_cost: nonpositive marked profit

**NQ / Phase 7 · prior 5m RVOL**

Fails later checks. 2024 base_cost: nonpositive marked profit; 2025 base_cost: nonpositive marked profit; 2024 double_cost: nonpositive marked profit; 2025 double_cost: nonpositive marked profit

**ES / Original SND · 1h/4h/daily**

Fails later checks. 2024 base_cost: nonpositive marked profit, drawdown above 35%; 2025 base_cost: nonpositive marked profit, drawdown above 35%; 2026 base_cost: nonpositive marked profit, drawdown above 35%; 2024 double_cost: nonpositive marked profit, drawdown above 35%; 2025 double_cost: nonpositive marked profit, drawdown above 35%; 2026 double_cost: nonpositive marked profit, drawdown above 35%

**ES / Phase 6 · first touch + room**

Fails later checks. 2024 base_cost: nonpositive marked profit, drawdown above 35%; 2025 base_cost: nonpositive marked profit; 2024 double_cost: nonpositive marked profit, drawdown above 35%; 2025 double_cost: nonpositive marked profit, drawdown above 35%

**ES / Phase 7 · prior 1m RVOL**

Fails later checks. 2024 base_cost: nonpositive marked profit; 2025 base_cost: nonpositive marked profit; 2026 base_cost: nonpositive marked profit; 2024 double_cost: nonpositive marked profit; 2025 double_cost: nonpositive marked profit; 2026 double_cost: nonpositive marked profit

**ES / Phase 7 · prior 5m RVOL**

Fails later checks. 2024 base_cost: nonpositive marked profit, drawdown above 35%; 2025 base_cost: nonpositive marked profit; 2024 double_cost: nonpositive marked profit, drawdown above 35%; 2025 double_cost: nonpositive marked profit

**YM / Original SND · 1h/4h/daily**

Fails later checks. 2024 base_cost: nonpositive marked profit; 2026 base_cost: nonpositive marked profit; 2024 double_cost: nonpositive marked profit; 2025 double_cost: nonpositive marked profit; 2026 double_cost: nonpositive marked profit, drawdown above 35%

**YM / Phase 6 · first touch + room**

Fails later checks. 2024 base_cost: nonpositive marked profit; 2025 base_cost: nonpositive marked profit; 2026 base_cost: nonpositive marked profit; 2024 double_cost: nonpositive marked profit; 2025 double_cost: nonpositive marked profit; 2026 double_cost: nonpositive marked profit

**YM / Phase 7 · prior 1m RVOL**

Fails later checks. 2024 base_cost: nonpositive marked profit; 2025 base_cost: nonpositive marked profit; 2026 base_cost: nonpositive marked profit; 2024 double_cost: nonpositive marked profit; 2025 double_cost: nonpositive marked profit; 2026 double_cost: nonpositive marked profit

**YM / Phase 7 · prior 5m RVOL**

Fails later checks. 2025 base_cost: nonpositive marked profit; 2026 base_cost: nonpositive marked profit; 2025 double_cost: nonpositive marked profit; 2026 double_cost: nonpositive marked profit

**CL / Original SND · 1h/4h/daily**

Fails later checks. 2026 base_cost: nonpositive marked profit, drawdown above 35%; 2024 double_cost: nonpositive marked profit; 2025 double_cost: nonpositive marked profit; 2026 double_cost: nonpositive marked profit, drawdown above 35%

**CL / Phase 6 · first touch + room**

Fails later checks. 2024 base_cost: nonpositive marked profit; 2025 base_cost: nonpositive marked profit; 2026 base_cost: nonpositive marked profit, drawdown above 35%; 2024 double_cost: nonpositive marked profit; 2025 double_cost: nonpositive marked profit; 2026 double_cost: nonpositive marked profit, drawdown above 35%

**CL / Phase 7 · prior 1m RVOL**

Fails later checks. 2024 base_cost: nonpositive marked profit, fewer than 10 closed trades; 2025 base_cost: nonpositive marked profit, fewer than 10 closed trades; 2026 base_cost: nonpositive marked profit; 2024 double_cost: nonpositive marked profit, fewer than 10 closed trades; 2025 double_cost: nonpositive marked profit, fewer than 10 closed trades; 2026 double_cost: nonpositive marked profit

**CL / Phase 7 · prior 5m RVOL**

Fails later checks. 2024 base_cost: nonpositive marked profit; 2025 base_cost: nonpositive marked profit, fewer than 10 closed trades; 2026 base_cost: nonpositive marked profit; 2024 double_cost: nonpositive marked profit; 2025 double_cost: nonpositive marked profit, fewer than 10 closed trades; 2026 double_cost: nonpositive marked profit

**Next steps**

Use the next-open results to decide which fixed rule, if any, deserves prospective paper tracking. Preserve the failed years. Reconcile same-feed TradingView orders before deployment, test the actual intended position-sizing preset separately, and use explicit roll/calendar handling before treating transfer-market results as investable. Parameter changes would be new experiments on already inspected data.

Files: [all period results](period-results.csv), [decisions](decisions.csv), [execution diagnostics](execution-quality.csv), [execution and concentration comparison](execution-comparison.csv), [direction/exit/timeframe breakdowns](trade-breakdowns.csv), [drawdown dollars](risk-dollars.csv), [zone-timeframe attribution](zone-timeframe-attribution.csv), [frozen plan](PLAN.json), [reference reconciliation](reference-reconciliation.json), [validation](validation.json).
