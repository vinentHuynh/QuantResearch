# TSMOM ORB calendar repair: recorded results

Current campaign cases pass declared historical checks.

Updated 2026-09-29T16:46:37.061580+00:00. 10 attempts; 9 current cases. Statuses: Succeeded: 10.

The original 20/60/120/252 momentum, 0.5 threshold, 15-minute opening range, 2R target and one-contract cap were retained. NQ uses a $2,500 planned-risk filter and MNQ $250: both allow at most 125 points of planned stop distance for one contract. This is not a maximum-loss guarantee.

| Case | Status | Net P&L | Trades | Marked DD | After close | Check |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| NQ-2024-baseline | Succeeded | $25,317.50 | 149 | -11.22% | 0 | passed |
| NQ-2024-double-cost | Succeeded | $23,595.00 | 149 | -11.57% | 0 | passed |
| NQ-2025-baseline | Succeeded | $11,080.00 | 104 | -10.12% | 0 | passed |
| NQ-2025-double-cost | Succeeded | $9,825.00 | 104 | -10.33% | 0 | passed |
| NQ-2026-baseline | Succeeded | $16,382.50 | 29 | -10.29% | 0 | passed |
| NQ-2026-double-cost | Succeeded | $16,050.00 | 29 | -10.37% | 0 | passed |
| MNQ-baseline | Succeeded | $5,139.82 | 282 | -1.26% | 0 | passed |
| MNQ-double-cost | Succeeded | $4,529.64 | 282 | -1.32% | 0 | passed |
| MNQ-next-open | Succeeded | $5,188.82 | 282 | -1.26% | 0 | passed |
| MNQ-next-open-strict-expiry | Succeeded | $5,188.82 | 282 | -1.26% | 0 | passed |

`MNQ-next-open` is the earlier inclusive-expiry attempt. `MNQ-next-open-strict-expiry` is the current confirmation; the earlier result remains visible. Close-mode cases use the earlier snapshot, which differs only in expiry expressions that close fills do not evaluate.

Baseline per-side fees/slippage: NQ $1.25 + one 0.25-point tick; MNQ $0.62 + one 0.25-point tick. Double-cost cases double both. Limit exits pay commission only. Equity drawdown uses recorded bar-close marks, not intrabar extrema.

## Original NQ baselines versus repaired baselines

| Year | Original net | Repaired net | Difference | Original carries | Repaired carries |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2024 | $25,432.50 | $25,317.50 | -$115.00 | 2 | 0 |
| 2025 | $8,265.00 | $11,080.00 | $2,815.00 | 5 | 0 |
| 2026 | $11,552.50 | $16,382.50 | $4,830.00 | 2 | 0 |

## The nine previously carried trades

| Entry ET | Original exit ET | Repaired exit ET | Resolution |
| --- | --- | --- | --- |
| 2024-05-27T11:05:00-04:00 | 2024-05-28T09:35:00-04:00 | 2024-05-27T12:55:00-04:00 | exited before scheduled close |
| 2024-11-29T09:55:00-05:00 | 2024-12-02T09:32:00-05:00 | 2024-11-29T13:10:00-05:00 | exited before scheduled close |
| 2025-02-17T11:05:00-05:00 | 2025-02-18T09:35:00-05:00 | 2025-02-17T12:55:00-05:00 | exited before scheduled close |
| 2025-07-03T09:55:00-04:00 | 2025-07-04T04:16:00-04:00 | 2025-07-03T13:10:00-04:00 | exited before scheduled close |
| 2025-07-04T09:55:00-04:00 | 2025-07-06T18:02:00-04:00 | 2025-07-04T12:55:00-04:00 | exited before scheduled close |
| 2025-11-28T11:10:00-05:00 | 2025-11-30T19:46:00-05:00 | 2025-11-28T13:10:00-05:00 | exited before scheduled close |
| 2025-12-24T10:15:00-05:00 | 2025-12-26T08:41:00-05:00 | 2025-12-24T13:10:00-05:00 | exited before scheduled close |
| 2026-01-19T10:00:00-05:00 | 2026-01-20T03:07:00-05:00 | 2026-01-19T12:55:00-05:00 | exited before scheduled close |
| 2026-06-19T10:00:00-04:00 | 2026-06-21T18:00:00-04:00 | 2026-06-19T12:55:00-04:00 | exited before scheduled close |

All attempt IDs, exact source and artifact hashes, reconciliation results and calendar checks are in [results.json](orb-results.json). Original selection provenance remains in [selection.json](source-selection-original.json).

These are historical regression results from previously inspected data. They do not establish untouched holdout performance or NinjaTrader live execution parity. No original runs were retagged or modified.
