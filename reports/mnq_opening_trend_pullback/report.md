# MNQ Opening Trend-Pullback backtest

## Result

- Period: 2019-05-07 through 2026-09-03 (1,824 sessions)
- Trades: 81; participation: 4.4%
- Net: $110.85; win rate: 39.5%
- Average: -0.15 points / +0.025R per trade
- Profit factor: 1.03; daily Sharpe: +0.04
- Max drawdown: $-1,157.68 (-4.6% of initial account)

## Frozen research definitions

- Trend structure is two confirmed 1-left/1-right 5-minute pivot highs and lows, both rising for long or falling for short. A pivot is only available after the following bar closes.
- The opening range is 09:30-09:44 ET. Entries use the close of a completed 5-minute rejection bar from 09:45 through 10:54 ET.
- A pullback is one counter-trend bar whose body and volume are each below the mean of the preceding three bars, followed by a trend-colored bar. Either bar must overlap a zone within 0.10 ATR.
- Zones are session VWAP, the broken opening-range edge, a previously crossed prior-day/overnight/premarket level, or a confirmed prior swing.
- ATR is mean true range of the 14 completed 5-minute bars immediately before 09:30 and is frozen for the day.
- Prior value uses a 70% close-volume profile at 0.25-point rows. This is an OHLCV approximation, not exchange volume-at-price.
- No historical economic-calendar series is present, so the default trades through releases. Untested 15-minute/hourly discretionary swing levels are not invented; targets use the listed objective session levels only.
- Stop is the furthest of zone plus 2 ticks, 1 ATR, or pullback extreme plus 2 ticks. Target is the nearest fixed key level in the trade direction; setups below 1.0R are skipped.
- Stops win an ambiguous 1-minute bar touching both stop and target. Modeled round-trip friction is 2 ticks plus $1.24 per contract.
- Daily stopping uses per-contract cumulative net points (+10) and cumulative normalized R (-2R), plus a 3-trade cap. Trades flatten before 11:00 ET.
- Bias-flip exits are disabled; contract-roll back-adjustment across 29 rolls is enabled.

This is a mechanical proxy for a discretionary plan, not evidence that the discretionary version has the same results.
