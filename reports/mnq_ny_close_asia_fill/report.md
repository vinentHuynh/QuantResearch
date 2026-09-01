# MNQ New York close -> Asia fill study

## Definition

The test fades the gap from the selected completed New York close to the 18:00 ET Globex reopen. A gap down is a long; a gap up is a short. The target is the selected close and the deadline is 00:00 ET. A 5-minute bar fills when its high/low reaches the target. The fill time is therefore reported as the end of the first touching bar (an upper bound). If the level is not touched, the trade exits at the last Asia bar's close.

Period: 2020-01-02 through 2026-08-06. Cost: 1 MNQ ticks round trip ($0.50 per contract). Minimum absolute gap: 0.25 points. The reference close may be at most 4 hours old, so the default study excludes weekend and holiday reopens. The 16:00 and 17:00 results are alternative definitions, not simultaneous trades.

## Key read

- The 17:00 futures-close level filled 89.3% of non-zero gaps, but averaged -$3.99 per one-contract event after cost.
- The 16:00 cash-close level filled 66.2% and averaged -$4.06 per event after cost.
- Fill probability falls materially as the normalized gap grows; the high headline hit rate is concentrated in small gaps.
- Rare non-fills can overwhelm many small target wins, so fill rate and trading expectancy must be evaluated separately.
- The highest P&L t-stat among the coded cumulative filters with at least 200 events was 17:00 short with gaps below 3 bps: 98.2% fills and $2.50 average net P&L. Its first/second-half averages were $2.23 and $2.76. 7 of 7 calendar samples were positive. Its in-sample gross edge breaks even near 6.0 ticks of total cost. This is an in-sample selection and needs a fresh out-of-sample test.

## Overall results

| reference_close | side | trades | fill_rate | fill_ci95_low | fill_ci95_high | avg_net_pnl_dollars | avg_net_pnl_ci95_low | avg_net_pnl_ci95_high | profit_factor | max_drawdown_dollars |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 16:00 cash | All | 1303 | 66.2% | 63.5% | 68.7% | -4.06 | -8.85 | 0.73 | 0.85 | 6997 |
| 16:00 cash | Long | 581 | 70.2% | 66.4% | 73.8% | 2.81 | -4.95 | 10.57 | 1.11 | 1612 |
| 16:00 cash | Short | 722 | 62.9% | 59.3% | 66.3% | -9.59 | -15.55 | -3.63 | 0.68 | 7604 |
| 17:00 futures | All | 1217 | 89.3% | 87.5% | 90.9% | -3.99 | -7.48 | -0.50 | 0.72 | 5469 |
| 17:00 futures | Long | 532 | 88.0% | 84.9% | 90.5% | -4.11 | -9.73 | 1.50 | 0.73 | 2810 |
| 17:00 futures | Short | 685 | 90.4% | 87.9% | 92.4% | -3.90 | -8.31 | 0.52 | 0.71 | 2908 |

Profit factor and P&L assume one MNQ contract per event. A target fill can still be a small net loss when the gap is smaller than the round-trip cost.

## Long versus short fill rates

Positive differences favor longs. The interval and p-value are unadjusted exploratory statistics.

| reference_close | long_fill_rate | short_fill_rate | long_minus_short_fill_rate | difference_ci95_low | difference_ci95_high | two_sided_p_value |
| --- | --- | --- | --- | --- | --- | --- |
| 16:00 | 70.2% | 62.9% | 7.3% | 2.2% | 12.5% | 0.005 |
| 17:00 | 88.0% | 90.4% | -2.4% | -5.9% | 1.1% | 0.185 |

## Fill probability by normalized gap size

The following table only shows side/bucket cells with at least 30 events. BPS buckets make early and late MNQ price levels comparable. See the CSVs for all buckets and point-size buckets.

| reference_close | side | gap_bucket | trades | fill_rate | avg_net_pnl_dollars |
| --- | --- | --- | --- | --- | --- |
| 16:00 | Long | 1-2 bps | 34 | 97.1% | -6.06 |
| 16:00 | Long | 2-3 bps | 40 | 82.5% | -2.25 |
| 16:00 | Long | 3-5 bps | 67 | 83.6% | -2.82 |
| 16:00 | Long | 5-7.5 bps | 74 | 75.7% | 6.29 |
| 16:00 | Long | 7.5-10 bps | 55 | 69.1% | -28.18 |
| 16:00 | Long | 10-15 bps | 94 | 70.2% | 6.61 |
| 16:00 | Long | 15-25 bps | 84 | 63.1% | 11.89 |
| 16:00 | Long | 25-40 bps | 39 | 43.6% | -8.53 |
| 16:00 | Long | 40-60 bps | 31 | 51.6% | 70.16 |
| 16:00 | Short | 1-2 bps | 40 | 97.5% | 4.04 |
| 16:00 | Short | 2-3 bps | 47 | 89.4% | -6.70 |
| 16:00 | Short | 3-5 bps | 65 | 89.2% | 2.61 |
| 16:00 | Short | 5-7.5 bps | 94 | 75.5% | 0.90 |
| 16:00 | Short | 7.5-10 bps | 74 | 60.8% | -14.48 |
| 16:00 | Short | 10-15 bps | 111 | 53.2% | -6.13 |
| 16:00 | Short | 15-25 bps | 108 | 62.0% | 9.11 |
| 16:00 | Short | 25-40 bps | 75 | 32.0% | -25.59 |
| 17:00 | Long | 0-0.5 bps | 88 | 94.3% | -2.09 |
| 17:00 | Long | 0.5-1 bps | 66 | 98.5% | 0.08 |
| 17:00 | Long | 1-2 bps | 99 | 94.9% | -1.65 |
| 17:00 | Long | 2-3 bps | 58 | 87.9% | -8.58 |
| 17:00 | Long | 3-5 bps | 80 | 93.8% | 1.18 |
| 17:00 | Long | 5-7.5 bps | 49 | 87.8% | 0.36 |
| 17:00 | Short | 0-0.5 bps | 95 | 98.9% | -0.43 |
| 17:00 | Short | 0.5-1 bps | 88 | 97.7% | 1.11 |
| 17:00 | Short | 1-2 bps | 113 | 98.2% | 2.19 |
| 17:00 | Short | 2-3 bps | 99 | 98.0% | 6.91 |
| 17:00 | Short | 3-5 bps | 122 | 90.2% | 2.10 |
| 17:00 | Short | 5-7.5 bps | 61 | 90.2% | 5.79 |
| 17:00 | Short | 7.5-10 bps | 41 | 75.6% | -10.24 |
| 17:00 | Short | 10-15 bps | 35 | 65.7% | -34.23 |

## Cumulative maximum-gap filters

These rows answer the trade-selection question "what if I only take gaps smaller than this threshold?" The filters overlap, so the table is exploratory rather than a set of independent tests.

| reference_close | side | max_gap_bps | trades | fill_rate | avg_net_pnl_dollars | avg_net_pnl_ci95_low | avg_net_pnl_ci95_high | profit_factor | max_drawdown_dollars |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 16:00 | Long | 3.0 | 110 | 91.8% | -3.30 | -10.80 | 4.21 | 0.58 | 670 |
| 16:00 | Long | 5.0 | 177 | 88.7% | -3.12 | -9.03 | 2.79 | 0.68 | 854 |
| 16:00 | Long | 7.5 | 251 | 84.9% | -0.34 | -5.08 | 4.40 | 0.97 | 854 |
| 16:00 | Long | 10.0 | 306 | 82.0% | -5.35 | -13.06 | 2.36 | 0.69 | 2282 |
| 16:00 | Long | 15.0 | 400 | 79.2% | -2.54 | -9.77 | 4.70 | 0.86 | 2308 |
| 16:00 | Long | 25.0 | 484 | 76.4% | -0.03 | -7.09 | 7.02 | 1.00 | 1742 |
| 16:00 | Short | 3.0 | 133 | 94.7% | -1.18 | -6.77 | 4.41 | 0.80 | 352 |
| 16:00 | Short | 5.0 | 198 | 92.9% | 0.07 | -4.57 | 4.70 | 1.01 | 456 |
| 16:00 | Short | 7.5 | 292 | 87.3% | 0.33 | -3.79 | 4.46 | 1.04 | 600 |
| 16:00 | Short | 10.0 | 366 | 82.0% | -2.66 | -7.05 | 1.72 | 0.80 | 1246 |
| 16:00 | Short | 15.0 | 477 | 75.3% | -3.47 | -7.77 | 0.83 | 0.79 | 2068 |
| 16:00 | Short | 25.0 | 585 | 72.8% | -1.15 | -5.58 | 3.29 | 0.94 | 1826 |
| 17:00 | Long | 2.0 | 253 | 95.7% | -1.35 | -4.56 | 1.86 | 0.62 | 538 |
| 17:00 | Long | 3.0 | 311 | 94.2% | -2.70 | -6.22 | 0.83 | 0.52 | 948 |
| 17:00 | Long | 5.0 | 391 | 94.1% | -1.91 | -5.36 | 1.55 | 0.70 | 1018 |
| 17:00 | Long | 7.5 | 440 | 93.4% | -1.65 | -5.60 | 2.30 | 0.78 | 1319 |
| 17:00 | Long | 10.0 | 463 | 92.0% | -4.25 | -9.09 | 0.59 | 0.60 | 2336 |
| 17:00 | Long | 15.0 | 489 | 91.2% | -4.57 | -9.78 | 0.65 | 0.63 | 2658 |
| 17:00 | Long | 25.0 | 514 | 89.9% | -3.42 | -8.71 | 1.87 | 0.74 | 2500 |
| 17:00 | Short | 2.0 | 296 | 98.3% | 1.03 | -0.40 | 2.46 | 1.79 | 176 |
| 17:00 | Short | 3.0 | 395 | 98.2% | 2.50 | 1.35 | 3.66 | 3.14 | 176 |
| 17:00 | Short | 5.0 | 517 | 96.3% | 2.41 | 0.44 | 4.38 | 1.76 | 490 |
| 17:00 | Short | 7.5 | 578 | 95.7% | 2.76 | 0.61 | 4.91 | 1.67 | 625 |
| 17:00 | Short | 10.0 | 619 | 94.3% | 1.90 | -0.66 | 4.46 | 1.33 | 627 |
| 17:00 | Short | 15.0 | 654 | 92.8% | -0.03 | -3.40 | 3.33 | 1.00 | 1374 |
| 17:00 | Short | 25.0 | 674 | 91.5% | -2.48 | -6.59 | 1.64 | 0.79 | 2375 |

## Split-sample stability

| reference_close | sample | split_ts | trades | fill_rate | avg_net_pnl_dollars | profit_factor |
| --- | --- | --- | --- | --- | --- | --- |
| 16:00 | First half | 2023-04-17 18:00:00-04:00 | 651 | 67.9% | -3.70 | 0.85 |
| 16:00 | Second half | 2023-04-17 18:00:00-04:00 | 652 | 64.4% | -4.42 | 0.86 |
| 17:00 | First half | 2023-04-10 18:00:00-04:00 | 608 | 91.3% | -4.59 | 0.62 |
| 17:00 | Second half | 2023-04-10 18:00:00-04:00 | 609 | 87.4% | -3.39 | 0.79 |

## Cost sensitivity

| reference_close | cost_ticks | avg_net_pnl_dollars | profit_factor | max_drawdown_dollars |
| --- | --- | --- | --- | --- |
| 16:00 | 0 | -3.56 | 0.87 | 6398 |
| 16:00 | 1 | -4.06 | 0.85 | 6997 |
| 16:00 | 2 | -4.56 | 0.84 | 7622 |
| 16:00 | 4 | -5.56 | 0.80 | 8874 |
| 17:00 | 0 | -3.49 | 0.75 | 4902 |
| 17:00 | 1 | -3.99 | 0.72 | 5469 |
| 17:00 | 2 | -4.49 | 0.68 | 6036 |
| 17:00 | 4 | -5.49 | 0.62 | 7172 |

## Important limitations

- The source is an unadjusted Databento continuous front-month series. Default same-day close filtering avoids weekend/stale-close distortions, but the data does not expose contract identifiers here, so an occasional roll switch at 18:00 cannot be proven or removed.
- A bar touch is not a guaranteed live fill at the exact level, and the cost input is a simple round-trip deduction. Commissions, queue position, and slippage beyond that input are not modeled.
- The fixed Asia deadline is 00:00 ET. Extending Asia to another clock changes both fill rates and non-fill P&L.
- Bucket results are exploratory. Small samples and multiple comparisons can make individual buckets look stronger than they are.
