# Multi-touch cluster failure test: frozen research protocol

This study asks whether an objective level formed by two separate confirmed pivot touches can support a costed failure-test reversal strategy. The rules below are fixed before examining this strategy's scored outcomes. Earlier NQ history has been studied elsewhere in this repository, so every period here is retrospective historical evidence.

## Recognition and trade

- Market: NQ continuous volume-rolled one-minute Workbench dataset, resampled to 15-minute candles; full CME trading day. One fixed NQ contract, $100,000 initial capital.
- ATR: simple mean of 14 completed true ranges. A pivot high or low must be strictly beyond the highs or lows of two candles on each side. It becomes available only when the second right-hand candle completes.
- Cluster: pair the new pivot with the nearest preceding same-side pivot separated by 4–40 chart candles and within 0.25 confirmation ATR in price. A resistance zone spans the two high prices plus 0.10 ATR outside each extreme; demand is the mirror at two lows. The zone becomes active after its confirmation close, lasts at most 80 chart candles, and must first be armed by a completed close on the expected approach side.
- First visit: previous close and current open must be outside the zone on the expected side. The bar must physically touch the zone, wick at least one tick beyond its far edge, and close within the zone. Any first touch retires the zone. The sweep bar cannot create the zone it trades.
- Enter at the next 15-minute open in the reversal direction. Cancel an entry that opens through its structural stop. The stop is one tick beyond the sweep extreme. Exit at the close of the 20th entry-inclusive bar if no stop occurs. The event engine needs a bracket target; it is set 1,000 ATR away from the signal close and is only an exceptional-move guard.
- Standard friction: $2.50 commission per contract per side and one tick of slippage per side. Stops use the existing one-minute Workbench execution model, including gap fills and conservative same-minute ambiguity.

## Chronology and decision criteria

- Development baseline: 2022-01-01 through 2024-12-31, 30 calendar days of warmup. This is one fixed configuration, with no parameter sweep.
- Advance to 2025 chronological evaluation only if the development run succeeds and reconciles, has at least 100 closed trades, positive net P&L, profit factor at least 1.05, and at least two of the three calendar years have positive net P&L. These are conservative research gates proposed for this campaign because the user specified no numeric thresholds.
- If development passes, test unchanged on 2025 with baseline and doubled fees/slippage. Require at least 40 trades, positive net P&L and profit factor above 1 on both scenarios. The event engine does not support additional entry-delay evaluation; record that stress as unavailable rather than implying it passed.
- Only if 2025 passes, test unchanged on 2026-01-01 through 2026-09-03 and assess nearby cluster tolerance and width as new, explicitly labeled robustness variants on development history. No inspected period is a fresh holdout.
- A positive trading ledger does not by itself establish that the cluster location adds information. A matched generic failure-test control is required for an incremental zone-edge claim. This first campaign establishes whether the fixed executable strategy is worth that further study.

The existing Workbench source snapshot, immutable dataset, complete trade and equity artifacts, and all failed or zero-trade runs remain part of the record. The continuous contract is unadjusted at rolls, and the engine does not reconstruct sub-minute order flow.
