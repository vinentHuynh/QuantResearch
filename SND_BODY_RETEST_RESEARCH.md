# Candle-body versus wick supply/demand zones

This experiment answers the user's confirmed request for **candle-body
boundaries only**. It preserves the existing strategy and Pine indicator.

The isolated model is [strategies/_snd_body_retest.py](strategies/_snd_body_retest.py).
Its `zone_boundary` parameter is `wick` for the original control and `body`
for open/close boundaries. It is not close-only invalidation.

| Boundary | Wick control | Candle-body variant |
| --- | --- | --- |
| Demand top | Base high | Maximum of base open and close |
| Demand bottom | Lowest low of all three candles | Lowest open or close of all three |
| Supply top | Highest high of all three candles | Highest open or close of all three |
| Supply bottom | Base low | Minimum of base open and close |

Both aligned entry zones and independent opposing context zones use the
selected definition. The formation test still requires the original
three-candle wick gap and candle directions, so changing the boundaries does
not add formations. Physical wick overlap, wick invalidation, swing structure,
hourly alignment, first-touch-only entry, next-candle order expiry and
one-tick stop buffers retain their original rules. Wick touches and stops
are evaluated against the newly selected boundaries.

The 1R target, at least 2R opposing room, full session, one fixed contract,
30-day warmup, zone age/cap, one-minute execution and cost assumptions remain
unchanged. Smaller body zones can alter touch times, invalidations, stop risk,
opposing room and subsequent trade availability. Cash changes are therefore
not isolated per-trade causal effects, and fixed contracts are not equal-risk
position sizing.

## Frozen comparison

The [protocol](reports/snd-body-retest-2026-09-24/protocol.json) declares 16
cases before inspecting any new strategy results:

- Wick and body on MNQ, MGC, NQ, ES, YM and CL.
- Actual doubled-commission-and-slippage reruns of both definitions on MNQ
  and MGC.
- Identical checked data and January 2022 through July 2026 scoring as the
  prior fresh-retest campaign. Compare 2024, 2025, January–July 2026 and
  pooled later history separately as well as full history.

The eight wick controls must reproduce the prior candidate and doubled-cost
trade/equity ledgers exactly. Reports preserve all declared cases, including
failure, missing-data or zero-trade outcomes. Source snapshots and data hashes
tie every result to its inputs.

This is a focused comparison on already inspected historical data, not a new
untouched holdout. No parameter or market is selected after seeing outcomes,
and no Working/feasibility promotion is made. Native Workbench event-v1 lacks
the stop-entry type, so the separate preserved simulator is used.

## Results and reproduction

All 16 declared cases completed. The change did **not** produce a consistent
improvement: average net R declined on all six markets, and the body variant
lost money on five. These are fixed-contract, after-cost historical results:

| Market | Wick net P&L | Body net P&L |
| --- | ---: | ---: |
| MNQ | $1,097.50 | -$316.50 |
| MGC | -$1,194.50 | -$789.50 |
| NQ | $26,245.00 | $13,140.00 |
| ES | -$12,825.00 | -$17,290.00 |
| YM | -$16,030.00 | -$8,730.00 |
| CL | -$14,305.00 | -$11,015.00 |

Body zones produced fewer trades and smaller median initial price risk on all
six markets. Drawdown decreased on five, but some dollar losses improved
without improving profit factor or average net R. Under doubled costs the
body results were -$1,582 on MNQ and -$2,207 on MGC.

See [the full comparison report](reports/snd-body-retest-2026-09-24/REPORT.md)
for chronology, risk, costs and exact baseline parity. The
[independent raw-source audit](reports/snd-body-retest-2026-09-24/independent-audit.json)
passed all 672 grouped checks across all 16 cases. That audit reconstructs
zone geometry and execution conditions; it does not independently replay
every trend decision or exit path.

```powershell
.venv/Scripts/python.exe scripts/research-snd-body-retest.py --declare --preview
.venv/Scripts/python.exe -m unittest discover -s tests -p test_snd_body_retest.py -v
.venv/Scripts/python.exe scripts/research-snd-body-retest.py --freeze
.venv/Scripts/python.exe scripts/research-snd-body-retest.py --run --workers 2
.venv/Scripts/python.exe scripts/report-snd-body-retest.py --require-complete
.venv/Scripts/python.exe scripts/audit-snd-body-retest.py
```

Each existing attempt is retained. Incomplete attempts require a new output
directory. Data-feed differences, continuous-contract gaps, missing minutes,
idealized roll liquidation and gap-order cancellation, conservative
intraminute ordering, fees and unmodeled queue effects remain limitations.
No broker trades or TradingView changes are part of this comparison.
