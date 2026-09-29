# SND Fresh Retest — zone creation indicator

Paste [snd_fresh_retest_zones.pine](snd_fresh_retest_zones.pine) into TradingView's
Pine Editor, save, and select **Add to chart**. Use **standard 5-minute candles**.

- **Bright green:** a demand zone aligned with the five-minute and hourly trend.
- **Bright red:** an aligned supply zone.
- **Thick, solid border:** fresh. The first later touch softens the fill and makes its border dashed.
- **Dotted, stopped box:** invalidated, expired, or removed by the display cap. It keeps its green/red color and shows its status in the text.
- **D / S marker:** the candle that confirmed the new zone.

Zone fills default to **45% opacity when fresh**, **32% after a touch**, and
**24% when retired**. Adjust these under **Settings → Inputs → Display**;
higher opacity means stronger color. Larger labels use the chart's foreground
color for contrast. If TradingView retains your previous color inputs after
updating the script, reset the indicator settings to defaults.

The box appears only when the third formation candle **closes**. Its left edge
is that closing timestamp, not the earlier base candle. The hourly direction
uses the hour already completed at the five-minute candle's open. For example,
a 09:55–10:00 formation uses the hourly state known at 09:55.

Default settings match the new strategy's formation rules: two-bar strict
swings, three consecutive formation candles, FVG qualification, both timeframe
directions aligned, and a 288-chart-bar zone lifetime. The third candle's color
does not matter. Demand spans the base high to the lowest of the three lows;
supply spans the highest of the three highs to the base low.

Enable **Also show unaligned context zones** to see additional dotted formations
used as opposing context. Those are distinct from aligned strategy zones, and
creation alerts are only for the aligned zones. Separate 100-zone queues keep
context from displacing aligned zones. By default, up to 150 retired boxes are
also kept so you can inspect where zones appeared previously.

To get notifications, create a TradingView alert, select this indicator, choose
**New demand zone**, **New supply zone**, or **Any new strategy zone**, and set
the frequency to **Once Per Bar Close**. Messages include the zone boundaries.

This indicator shows **zone formation**, not trade entries. The strategy's 2R
room check, first-touch entry window, position blocking, stop and target apply
after a zone exists; they do not suppress its creation drawing. A touched zone
can remain visible as a level even though it is no longer fresh. No trade fills
or performance are reconstructed.

Native TradingView aggregation/session settings, missing source minutes and
continuous-contract rolls can differ from the Python research. The indicator
does not replicate the Python minute-completeness or contract-ID reset logic.
Use comparable symbols and full-session candles when comparing formations.

The Pine source was checked against the Python formation rules and reviewed
for confirmation timing, object limits and alert definitions. The color update
changes display settings only. **TradingView compilation and chart execution
of this revision remain unverified** because the available browser connection
failed during initialization.

The completed-hour request follows [TradingView's higher-timeframe guidance](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/).
Timestamped drawing behavior follows [TradingView's box documentation](https://www.tradingview.com/pine-script-docs/visuals/lines-and-boxes/).
