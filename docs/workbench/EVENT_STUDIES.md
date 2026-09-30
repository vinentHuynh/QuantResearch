# Pattern event studies

Open **Research → Pattern event studies** (`#/event-studies`). This is a price-behaviour event study, separate from strategy execution, profit accounting and scorecard promotion.

Results open on **Summary**, showing each pattern's observed expected-bounce
percentage and the exact success/sample counts. The percentage is rejections
divided by measurable post-touch reactions (rejection, failure or unresolved);
ambiguous and incomplete reactions are excluded. Zero observations show no
percentage. Sparse samples remain labelled as insufficient evidence, including
100% results from a single observation. This is not a probability that a pattern
is valid or a trading win rate. **Details & charts** retains the comparisons,
fill measurements, full statistics and examples.

## Workflow

1. **New study**: choose a registered dataset, UTC interval, session and chart (default 15m). Record a hypothesis and previous exposure to the history. The advanced settings expose all detection, outcome, matching and uncertainty parameters.
2. **Validate & preview** verifies the immutable dataset checksum and partitions completed session candles chronologically, 60/20/20. No pattern outcomes are computed. Each split must have at least 100 candles or the return/reaction horizons plus 30, whichever is larger.
3. **Save study protocol** preserves the rules, split boundaries, dataset, source snapshot and hashes. Run development and inspect the random charts. Record a visual-review note before validation.
4. Run the one declared validation comparison per family (four families). Successful phases cannot be rerun. Failed, cancelled and interrupted attempts remain visible and can be retried under the same rules.
5. **Freeze protocol**, then explicitly open the final test. Its first opening is recorded. The final window cannot be queried as a result before it runs. Detection charts and event windows never cross a split's right boundary.
6. After the final test, **Replicate on another instrument** copies the frozen source, rules, timeframe and session. Select the other instrument and interval before inspecting results. It follows the same review/validation/final workflow.

Rule changes require a new immutable study. Earlier studies overlapping the instrument and interval remain linked. A reserved historical window cannot be certified untouched: the prior-exposure declaration and earlier studies remain visible. The app does not certify institutional order flow or profitability.

## Exact initial definitions

The engine exposes eight named methods on `PatternRecognizers`: `demand_zone`,
`supply_zone`, `bullish_order_block`, `bearish_order_block`, `bullish_fvg`,
`bearish_fvg`, `support`, and `resistance`. Each uses only its own required
lookback and completed ATR; an unrelated family's lookback never delays it.
Every detected event includes its `pattern` key and the numerical `recognition`
evidence (base compactness/departure, breakout/anchor candle, gap width, or
swing confirmation). CSV exports flatten those fields into recognition columns.
The results show all eight recognizers separately, with per-pattern chart
filtering and **Why this pattern was recognized** evidence. Directional
comparisons are descriptive breakdowns of the four primary family comparisons.
New source snapshots sample up to two detections per recognizer. Earlier saved
studies preserve their original code, sample policy and results.

`npm run test:pattern-recognition` checks positive and negative fixtures for
all eight patterns, inclusive thresholds and deadlines, first-confirmation
deduplication, prefix causality and bullish/bearish symmetry.

The recorded NQ check uses **NQ - all eight pattern recognizers** in the app.
`scripts/test-pattern-recognition-market.mjs` runs development (or `validation`
after the recorded visual review); it never opens the final split.
`scripts/audit-pattern-recognition.py` independently enumerates formations and
reconciles the full development detection set, bounds, ATR and first confirmations.
`scripts/validate-pattern-recognition-browser.mjs` checks the eight chart filters
and saves the reviewed images. `scripts/report-pattern-recognition.mjs` writes
the development/validation report under `reports/pattern-recognition/`.

- ATR is the simple average of 14 completed true ranges. Outcome distances freeze ATR at confirmation. No touch at or before confirmation counts.
- Supply/demand: three base candles spanning at most 1 base-close ATR, followed in the next three candles by a close at least 1.5 base-close ATR above/below the range. First qualifying confirmation per base/direction; full base range.
- Order block: the last opposite-colour candle in the preceding five candles; confirmation closes beyond the preceding 20-candle high/low and at least 1.5 confirmation ATR from that candle's close. First confirmation per anchor/direction; full anchor range.
- FVG: candle one's high below candle three's low, or the bearish mirror. Confirmed only at candle three's close; zone is the intervening interval.
- Support/resistance: strict swing high/low with two candles each side, confirmed after the right candles close. Zone full width is 0.25 confirmation ATR, centered on the swing.

Return means OHLC overlaps the zone in the next 50 chart candles. Reaction starts at the first touch and includes that candle in the 20-candle horizon. Rejection is 1 ATR beyond the near edge before reaching 0.25 ATR past the far edge; failure reverses that order. Neither is unresolved; insufficient observation is incomplete. A known earlier boundary hit can be classified before a truncated horizon, but truncated excursions are excluded from distributions. Return/fill rates require the entire return horizon; reaction rates exclude ambiguous and incomplete outcomes, with their counts shown alongside the denominator.

One-minute prices resolve chart-candle collisions chronologically. Unknown order inside a minute remains ambiguous. Any boundary reached in the touch minute is conservatively ambiguous because the extrema may precede contact. A later minute opening beyond a boundary establishes which was first; otherwise simultaneous minute extrema are ambiguous. Excursions omit the touch minute, use complete reaction horizons, and are lower-bound observations relative to the near edge.

FVG near-edge, midpoint and full-fill rates are distinct from rejection. An edge can be passed by a price gap without a traded overlap; this counts as reaching/passing that fill level, not as a touch. Repeated visits require an entire chart candle outside the zone between contacts. Later visits and their overlapping windows are descriptive, not additional independent trials.

## Controls and uncertainty

Selection never reads future outcomes. Supply/demand and S/R controls use earlier timestamps in the same split, matching normalized zone width/distance exactly by placement. Candidate conditions use the same four-hour local-session bucket and calipers on log ATR ratio, 20-candle trend divided by ATR, and three-candle movement divided by ATR. The latter two differences are scaled by two. Candidates are the preceding 2,000 chart candles; nearest total difference wins, with chronological tie breaking. Timestamp/direction combinations with the same detected family are excluded.

FVG controls additionally require a same-direction three-candle move of at least 1.5 ATR without a same-direction FVG at that timestamp. Order-block controls use the same confirmation and breakout but another pre-move candle, chosen by the smallest combined normalized width/distance discrepancy within the caliper. Identical rectangles and candles on the wrong side of the confirming price are excluded. Unmatched events remain in overall rates but are excluded from pattern-minus-control comparisons. Controls may be reused. Matching scores and pair IDs are exported.

The default uncertainty block is 100 consecutive chart candles, at least the combined return/reaction horizon. Both arms are resampled using the same occupied chronological blocks, retaining reused controls and local clustering. The 95% percentile interval uses 1,000 seeded repetitions; at least 10 occupied blocks and 20 eligible observations per arm are required. These are pointwise exploratory intervals, not multiple-comparison-adjusted or proof against longer dependence. Overlapping rectangles are flagged. Reports include direction, zone age, monthly periods, repeated visits and favourable/adverse 10th/50th/90th percentiles.

## Storage and verification

`data/workbench/event-studies/` stores immutable protocol inputs, copied Python/session code, phase attempts, logs, complete event ledgers, CSV exports, result JSON and checksummed manifests. Workers use the saved source and recheck dataset/source/protocol identity. Results survive browser reload and API restart; jobs interrupted by restart are retained as Interrupted. Two event-study workers may run at once, with a 30-minute timeout. They are separate from strategy workers. Final results never promote strategy research milestones.

Run focused checks:

```powershell
node scripts/python-command.mjs -m unittest discover -s tests -p test_event_study.py -v
node scripts/test-event-studies.mjs
node scripts/validate-event-studies-browser.mjs
npm run build
```

The lifecycle and browser tests use isolated synthetic data below
`$env:WORKBENCH_ARTIFACTS/test-runs/event-studies-validation-*` and publish
`event-studies-latest.json`, including synthetic final-test openings. They do
not open real-data final holdouts or modify strategy runs. The browser test
requires the lifecycle test first and an installed Edge browser.
