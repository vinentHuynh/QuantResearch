# Transcript Supply / Demand indicator

This Pine v6 indicator expresses a testable interpretation of the supplied video transcript. It is a research tool; the indicator does not establish a profitable edge or calculate trading performance.

## Install and use

1. Open a standard **five-minute** TradingView chart with the sessions you intend to examine.
2. Paste `transcript_supply_demand_indicator.pine` into Pine Editor, save, and add it to the chart.
3. Keep the baseline settings for comparison: **2** pivot bars on each side, **zone boundary** stop, **1R** target, and **288** five-minute bars of zone lifetime. The indicator uses completed **one-hour** structure and all available sessions.
4. Review the status panel and any next-bar plan: yellow is the entry reference; dashed red and green are stop and target references.

For alerts, select **Next-bar plan updated** to receive rolling levels each completed candle, or **New next-bar setup armed** for the first plan on a zone. Include **Prior setup cancelled** when following plans. Alternatively, enable **Send detailed plan / cancel / trigger alerts** and create an alert for **Any alert() function call**; these messages include changing levels and cancellations. Plans replace earlier levels. Confirmed long/short trigger alerts serve a different purpose: they annotate a trigger detected after the bar finishes.

## Model and timing

A swing is recognized only after its right-side confirmation bars finish; equal highs/lows are excluded. A close beyond an unused swing determines direction. New zones and armed plans require aligned five-minute and one-hour directions. The one-hour request uses a one-bar offset with `lookahead_on` to return completed hourly state.

Demand requires a bearish base, an immediately bullish departure, then a bullish three-candle wick gap; supply reverses these conditions. The final candle can have either color. All three candles must be consecutive, so the gap cannot span a session or weekend break. Zone boundaries include the departure's extreme wick. Zones start displaying when recognized, never on an earlier base candle.

After a later candle touches a zone, the next bar's long entry reference is one tick above the completed candle's high; shorts use one tick below its low. The reference rolls each completed candle. Default stops sit one tick beyond the zone, with a previous-candle stop option. The most recent eligible zone takes priority; each zone can produce one signal. Touch state survives temporary bias disagreement, but a wick strictly beyond the distal zone edge invalidates the zone.

**A confirmed trigger marker is retrospective, not an executable fill at the closing price.** It appears only after the five-minute candle closes, if that candle crossed an already published entry reference. The displayed historical reference is also not an assumed gap-adjusted fill. No live intrabar trigger alerts are emitted.

## Relationship to the Python research

The Python results do **not** certify Pine parity:

- Pine rejects an entire five-minute bar if its wick breaches the zone's distal edge. With the candle-stop option, it also rejects a bar reaching both entry and stop. A one-minute simulation can resolve some of that sequence, enter, and subsequently stop out.
- Pine has no simulated position, trade management, or position blocking. It can arm another eligible zone after a signal; Python trading rules can suppress trades while a position is open. Signal counts therefore differ from trade counts.
- For one-minute sources, Python requires five observed one-minute bars to construct a complete five-minute candle and 60 to construct a complete hourly candle. TradingView uses its native feed candles and does not apply the identical completeness filter here. Session boundaries and missing observations can change zones and bias.
- Continuous-contract roll metadata and roll handling in Python may differ from TradingView's symbol feed and adjustment settings.
- Pine target guides omit fees, slippage, gap-fill assumptions, and execution costs. They are planning references, not performance estimates.

The source has received manual/static review. It has **not yet been compiled or run in TradingView**; a successful TradingView compile, visual replay, and signal comparison are still needed before claiming runtime validation or parity.
