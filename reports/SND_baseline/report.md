# SND MNQ baseline

This is SND's default 1h/4h/Daily two-candle zone logic executed on the MNQ
one-minute path. It is a research baseline, not a claim of tradable performance.

## Headline

| Metric | Result |
| --- | ---: |
| Zones formed | 8,647 |
| Tests consumed | 6,953 |
| Trades | 6,475 |
| Win rate | 27.4% |
| Average points | -2.66 |
| Average R | -0.01 |
| Total points | -17,244.50 |
| Total P&L | $-34,489.00 |
| Profit factor | 0.91 |
| Max drawdown | $-38,797.50 |

P&L uses MNQ at $2/point and 0 round-trip cost ticks.

## Baseline caveats retained from SND

- A zone needs only the two-candle body pattern; it does not require BOS, an order
  block, relative volume, displacement/ATR, FVG, or swing confirmation.
- Entries fill at the proximal line whenever a one-minute range overlaps the zone.
- The stop is capped at 100 points and may therefore sit inside a wide zone.
- A test can be consumed outside the enabled date/no-trade window.
- If both sides qualify on one bar, SND consumes both tests and prioritizes the long.
- If stop and target occur in the same one-minute bar, the stop wins.
- Continuous-contract roll formations are retained but flagged.

## Engine audit

```json
{
  "capacity_removed": 219,
  "invalidated": 8395,
  "tests_consumed": 6953,
  "tests_outside_entry_period": 0,
  "tests_in_no_trade_window": 476,
  "opposite_side_tests_consumed": 2,
  "range_end_trade_cancellations": 0,
  "both_stop_and_target_hit": 2,
  "open_trade_at_data_end": 0
}
```

CSV summaries and Parquet zone/test/trade ledgers are in this directory.
