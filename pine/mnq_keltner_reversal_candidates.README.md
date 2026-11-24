# MNQ Keltner reversal candidates

Paste `mnq_keltner_reversal_candidates.pine` into TradingView's Pine Editor, save it, and add it to a standard 5-minute MNQ chart with the full futures session enabled. The script uses Pine v6.

## Markers

| Marker | Condition |
| --- | --- |
| R-W | Fresh close outside the channel with a full outer wick at least 0.5 ATR and less than 1 ATR |
| R-T | Fresh close outside the channel with aligned prior EMA slope at least zero and less than 0.5 prior ATR |
| R-WT | Both enabled conditions qualify on the same candle; this combination was not independently validated |

Green labels below candles mark possible upward reversals following a lower-band breach. Red labels above candles mark possible downward reversals following an upper-band breach. These are candidates, not confirmations. Neither rule requires the close to return inside the band.

The two conditions are alternatives, not a required combination. Switch either one off independently in settings. Markers and alert conditions activate only when the signal candle closes. Channels themselves continue updating during an open candle.

## Exact defaults

- EMA of close: 20.
- ATR: simple mean of 20 true ranges, including the completed signal candle.
- Bands: EMA plus/minus 2.25 ATR.
- Upper outer wick: `high - max(open, close)`.
- Lower outer wick: `min(open, close) - low`.
- Prior slope: `(EMA[1] - EMA[6]) / ATR[1]`, multiplied by +1 for an upper breach or -1 for a lower breach. The weak aligned range is `[0, 0.5)`, not the absolute value of the slope.
- A fresh upper episode requires the previous high to be at or below its own previous upper band. A fresh lower episode requires the previous low to be at or above its own previous lower band. A previous wick breach therefore disqualifies a new signal even if the previous close was inside.
- Candles breaching both bands are excluded.
- Defaults allow markers only on 5-minute charts, after 101 prior chart bars. No session subset is imposed; use all-session chart data. Changing chart hours changes the indicator.

Create an alert using **Any reversal candidate** and choose **Once Per Bar Close**. Individual directional and W/T alert choices are also available. Creating several overlapping alert types can send several notifications for one candle. Changing indicator inputs requires recreating existing TradingView alerts.

The Data Window shows ATR in points, candle range, both outer wicks, extreme extension, close extension and aligned prior slope. W measures the whole outer wick, not only the part beyond the band. Both patterns are close-outside events, not wick-only rejection events.

## Evidence and limitations

These are exploratory reversal slices from the 2026-10-26 MNQ study. They are not the opening-session continuation setup. No successful reversal, target hit or probability is inferred from a marker; signal-only logic never consults future price or future data completeness.

The research excluded incomplete minute windows and reset EMA/ATR at known contract changes. This indicator works with the chart's supplied candles and cannot reproduce the research cache's minute completeness or contract IDs. Continuous-contract adjustment, roll history, session settings and data-feed differences can change signals. It has no automatic contract-roll reset. Use standard OHLC candles, not Heikin Ashi/Renko. Changing defaults or enabling other timeframes creates an unvalidated variant.

Validation: independently reviewed signal definitions and local numerical checks against the saved study ledger. Local checks do not replace compilation in TradingView's Pine Editor.

References: [TradingView confirmed-bar behavior](https://www.tradingview.com/pine-script-docs/concepts/bar-states/), [TradingView alert behavior](https://www.tradingview.com/pine-script-docs/concepts/alerts/), [Grimes channel settings](https://www.adamhgrimes.com/indicators/).
