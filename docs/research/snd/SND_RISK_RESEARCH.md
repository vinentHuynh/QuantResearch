# MNQ fixed-risk research

This campaign tests position sizing while holding the preferred SND signal rules fixed: relaxed three-candle formation, wick zone boundaries, confirmed five-minute/hourly structure, first physical touch, a five-minute stop-entry lifetime, one tick beyond the zone for the stop, a 1R target and 2R opposing room.

## Results

The fixed-risk economic test failed. All 12 risk-budget/execution combinations lost money over the full January 2022–July 2026 history. The four one-contract controls stayed profitable and exactly matched the preceding campaign. All 16 cases verified; the independent audit passed 1,569 checks with zero failures. The separate engine and forward-workflow suites passed 12 and 14 focused tests.

The price-fill model below matches the frozen prospective setup: one adverse tick on entry and non-limit exits, commissions included, integer quantities and a ten-contract cap.

| Sizing | Full net | January 2025–July 2026 net | Full max drawdown | Full trades |
| --- | ---: | ---: | ---: | ---: |
| One contract | $6,153.50 | $4,668.00 | $1,689.75 | 1,101 |
| $50 planned risk | -$1,737.50 | -$499.00 | $1,752.75 | 459 |
| $100 planned risk | -$3,713.00 | -$1,288.00 | $3,907.00 | 845 |
| $200 planned risk | -$4,170.00 | -$335.50 | $7,155.00 | 1,057 |

Under the original cash-cost model, $100 planned risk lost $2,738.50 full-history. Under adverse two-tick price fills plus doubled commissions, it lost $7,824. The result therefore is not caused only by the new price-fill assumption.

Fixed budgets increase quantity for narrow stops and skip setups too wide for one contract. In the $100/one-tick case, 826 eligible sizing attempts were rejected for insufficient budget; the median executed size was two contracts. The strategy's one-contract profit does not carry over to these fixed-dollar-risk policies. This is a finding about the complete policies, including rounding, skips and changed later trade availability; it does not establish a universal rule against risk budgeting.

The planned budget is not a hard loss ceiling. The largest loss in the $100/one-tick case was $408 after the December 2022 holiday/weekend gap through its stop, despite only $93 planned all-in stop risk. The inherited strategy can hold positions overnight and over weekends. These gap outcomes are retained, not clipped to the budget.

The forward protocol was frozen before these outcomes were generated. It keeps both the one-contract reference and $100-risk comparison. Daily checks are active, but the initial state has zero forward observations because local data stops September 3. New current warmup and poststart MNQ minute data are required; no completed forward-test result is claimed. See [the forward status and input instructions](SND_FORWARD_TEST.md).

## Declared experiment

The [frozen protocol](../../../artifacts/research/snd-risk-research-2026-09-25/protocol.json) declares 16 MNQ cases: one contract and $50/$100/$200 planned risk budgets, each under original cash costs, doubled cash costs, one-tick adverse price fills, and two-tick adverse price fills plus doubled commissions. The primary budget is $100 with a ten-contract cap. These are research assumptions, not personalized account limits. None is automatically promoted based on its outcome.

At order arming:

```
planned_loss_per_contract = abs(trigger - stop) * point_value
                          + 2 * slippage_ticks * tick_size * point_value
                          + 2 * commission_per_side
quantity = min(contract_cap, floor(risk_budget / planned_loss_per_contract))
```

This quantity stays fixed through the next candle. Entry and stop gaps can produce losses above the planned budget. A quantity below one skips the setup; that zone's first touch remains consumed. Other eligible zones at that same candle close can still be considered. Complete simulator reruns preserve the resulting changes in position availability and later trades. Costs and marked exposure scale by actual integer quantity.

The cost allowance is included in the sizing budget. The existing reported net-R definition continues to divide net P&L by actual fill-to-stop price risk times point value times quantity, excluding fees from the denominator. Planned all-in stop-risk returns and realized budget overruns are also recorded. Fractional constant-R diagnostics are clearly separate from executable whole-contract sizing.

Historical scoring is January 2022–July 2026 with 30 preceding calendar days of warmup. All that history was previously inspected. The original sources and campaigns are preserved; this isolated simulator retains a stop-entry lifecycle not supported by the native Workbench event adapter.

## Artifacts

- [Complete sizing report](../../../artifacts/research/snd-risk-research-2026-09-25/REPORT.md)
- [All case-period metrics](../../../artifacts/research/snd-risk-research-2026-09-25/all-results.csv)
- [Independent audit](../../../artifacts/research/snd-risk-research-2026-09-25/independent-audit.json)
- [Frozen source manifest](../../../artifacts/research/snd-risk-research-2026-09-25/source-manifest.json)
- [Prospective collection workflow](SND_FORWARD_TEST.md)

Each case retains its input, result, trade ledger, marked-equity ledger and every eligible sizing decision, including zero-contract rejections. Four one-contract controls must exactly match the preceding campaign. The independent auditor reconstructs raw geometry, quantities, costs, risk and every equity mark without importing the strategy implementation.

The prospective workflow separately freezes one-contract and $100-risk simulations before the new historical sizing outcomes are reviewed. It starts on a future UTC five-minute boundary, uses only local new data with ingestion receipts, and keeps open positions across checks. Delayed replay is explicitly distinct from timely OHLC observation and actual broker fills. There is no automatic trade execution.

## Commands

For this existing campaign, preserve all recorded attempts and frozen files:

```powershell
.venv/Scripts/python.exe scripts/audit-snd-risk-research.py
.venv/Scripts/python.exe scripts/report-snd-risk-research.py --require-complete
```

A new research campaign requires a new output directory and explicit declaration/preview/freeze before execution. Do not overwrite failed, interrupted or unfavorable outcomes. Source changes after freeze require separate evidence, not silent replacement.
