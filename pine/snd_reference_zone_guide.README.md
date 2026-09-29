# SND Reference — Zones and First Retest

[Copy the Pine Script](snd_reference_zone_guide.pine) into TradingView's **Pine Editor**, save it, and choose **Add to chart**. Use a **standard 5-minute MNQ candle chart** with the full trading session if you want the closest comparison with the research. On another chart interval or synthetic candle type, the indicator displays a prompt and suppresses zone signals. Its settings control the display; the research rules are fixed in the code.

## Reading the chart

| Display | Meaning |
| --- | --- |
| Green / red thick solid box | Fresh, direction-aligned demand / supply zone. The zone appears when the third formation candle closes. |
| **D** / **S** triangle | Candle that confirmed a new aligned zone. |
| Dashed box | The zone has had its first physical touch. That touch consumes its freshness even when no candidate qualifies. |
| **WATCH D*** / **WATCH S*** | First touch closed with direction and opposing-room checks satisfied. Inspect the **next 5-minute bar only** for a stop-entry trigger. This is a geometric candidate; check whether a position or order already blocks entry. |
| Yellow / red / green horizontal guides | Reference entry / stop / 1R target for that one-bar window. The 12 most recent sets remain visible for chart review. |
| Thin dotted “Context” box | Optional unaligned formation used only to measure opposing room. Enable **Also show unaligned context zones** to see it. |
| Faded dotted, stopped box | Invalidated, expired, or removed by the display cap; toggle **Keep invalidated / expired zones** to retain these. |

The top-right checklist shows the 5-minute and **previous completed hourly** direction, number of fresh aligned zones, latest first-touch decision, and any active reference prices. The active prices clear after the one-bar window or if the newly completed hour changes direction. **No known opposing zone** means the script did not observe one in its retained context; it is not a guarantee of clear price space. Turn on **Mark rejected first touches** to see orange **SKIP** marks. A wick through the far edge invalidates a zone before a same-bar touch can produce a candidate.

## Frozen setup shown by this guide

1. Two strict pivot bars on each side establish structural direction. The 5-minute and previous completed hourly directions must agree with the zone at creation **and** at first touch.
2. Three consecutive 5-minute candles form a zone. Demand requires a bearish first candle, bullish middle candle, and third **close above the first high**. Supply reverses those conditions and requires the third **close below the first low**. This is the tested *relaxed FVG* condition; the wicks need not leave a full gap. The third candle's color is unrestricted.
3. Demand spans the first candle's high down to the lowest low of the three. Supply spans the highest high of the three down to the first candle's low. A zone expires after 288 observed chart bars or is invalidated by a wick through its far boundary.
4. Only the first later physical overlap is eligible. At that candle's close, the demand entry reference is one tick above its high; the supply reference is one tick below its low. The stop is one tick beyond the zone's far edge. The reference target is 1R from entry. The nearest known opposing zone must leave at least 2R, or there must be no known opposing zone.
5. The stop-entry reference is valid for **one following 5-minute interval**, unless the newly completed hour changes direction at its start. The **WATCH** mark reports a geometric candidate, not an entry or fill. The script cannot know whether another open position or pending order would block the backtest's setup.

These are the visual parts of the [frozen MNQ prospective protocol](../SND_FORWARD_TEST.md). Its primary stream is one MNQ contract; a separate $100 estimated-risk shadow stream is **not sized by this indicator**.

## Alerts

In TradingView, create an alert with this indicator as the condition, select **New demand zone**, **New supply zone**, **Demand geometric candidate**, or **Supply geometric candidate**, and choose **Once Per Bar Close**. Zone alerts include upper and lower bounds; candidate alerts include the reference entry, stop, and target. A candidate alert calls for watching the next 5-minute interval, checking position/order blocking, and rechecking room after any fill. It does not report whether the trigger filled. TradingView requires you to create and enable each alert in its UI; Pine `alertcondition()` only defines available alert events. [TradingView alert documentation](https://www.tradingview.com/pine-script-docs/concepts/alerts/)

## What the guide does not replicate

The Python test uses source **one-minute OHLC** to decide entries, gaps, stops, targets, adverse ticks, commissions, whole-contract sizing, position blocking, pending-order cancellation, contract rolls, session and incomplete-bar handling. This Pine **indicator** does not simulate those decisions, reconstruct P&L, or issue broker orders. Its 1R line is based on the signal reference; the Python model recalculates risk, target, and opposing room after an actual simulated fill. A historical WATCH mark stays on the chart even if an order would have been blocked or canceled. TradingView data, continuous-contract rolls, and session settings can also change which zones appear. The 288-bar age here counts observed chart bars; missing or closed-session intervals are not equivalent to the Python model's elapsed-bucket treatment.

The historical research did **not** establish a robust edge, and the frozen prospective test has no new outcome sample yet. Treat the chart as a paper-trading checklist, not a validated live signal. See [research conclusions](../SND_RESEARCH_CONCLUSIONS.md).

The script uses confirmed chart bars and the last completed hourly value using TradingView's [higher-timeframe, non-repainting pattern](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/). Zone boxes follow TradingView's [drawing-object rules and limits](https://www.tradingview.com/pine-script-docs/visuals/lines-and-boxes/). TradingView compilation and live-chart rendering should be checked in Pine Editor before relying on alerts.
