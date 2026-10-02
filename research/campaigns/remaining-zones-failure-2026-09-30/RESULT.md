# Remaining support/resistance detectors: completed failure-test screen

**No candidate survived the full declared sequence.** All seven remaining families were screened under common mechanics. Fixed 100-point round numbers were the only development survivor and passed the 2025 baseline/doubled-cost evaluation, but the unchanged 2026 continuation lost money and failed the profit-factor gate. Stop advancement; no 2026 cost-stress or nearby-width search was launched after that decisive failure.

## Initial development screen

NQ, January 1, 2022 through December 31, 2024; 15-minute bars, regular-hour entries, one contract, $100,000 initial capital. Figures include $2.50 commission and one tick of slippage per side ($15 per completed trade). Nine detector candidates across seven families plus one descriptive benchmark were declared before inspecting outcomes.

| Candidate | Trades | Net P&L | Net PF | Marked drawdown | Development disposition |
| --- | ---: | ---: | ---: | ---: | --- |
| 1-hour confirmed swing | 97 | -$4,410 | 0.81 | 10.04% | Sparse / inconclusive |
| 4-hour confirmed swing | 11 | -$165 | 0.94 | 2.98% | Sparse / inconclusive |
| 15-minute opening range | 79 | -$9,205 | 0.63 | 14.85% | Sparse / inconclusive |
| 30-minute opening range | 83 | +$2,385 | 1.10 | 11.35% | Sparse / inconclusive |
| Strong-departure swing | 309 | -$7,460 | 0.91 | 28.48% | Tested configuration failed |
| Support/resistance flip | 350 | +$3,875 | 1.04 | 14.10% | Tested configuration failed |
| 20-bar range extremes | 801 | -$47,355 | 0.77 | 61.06% | Tested configuration failed |
| 100-point round numbers | 837 | +$25,905 | 1.11 | 24.25% | Passed; advanced unchanged |
| Classic daily S1/R1 pivots | 52 | -$12,540 | 0.26 | 13.52% | Sparse / inconclusive |
| Previous-bar sweep benchmark | 2288 | -$36,985 | 0.94 | 66.11% | Descriptive benchmark |

Sparse means below the frozen operational floor of 100 trades, not proof of no edge. Negative economics remain visible for sparse candidates. Support/resistance flips were positive cumulatively but missed PF>=1.05 and had only one profitable year. Strong-departure swings and 20-bar extremes failed with larger samples; the latter also exceeded the 35% drawdown ceiling.

All initial attempts were retained. Prior-day extremes (42 trades, +$17,010), overnight extremes (61, +$7,830), and the consolidation box (159, -$13,200) remain preserved in their separate preceding campaigns. Their daily lifetimes, visit policies or cluster widths differ; they are descriptive historical comparisons, not members of this common-engine batch.

## Round-number candidate: stage progression

| Stage | Trades | Net P&L | Net PF | Marked drawdown | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| 2022-2024 development | 837 | +$25,905 | 1.11 | 24.25% | Passed stage gates |
| 2025 baseline | 311 | +$20,920 | 1.17 | 31.01% | Passed stage gates |
| 2025 doubled costs | 311 | +$16,255 | 1.13 | 32.08% | Passed stage gates |
| 2026 Jan 1-Sep 28 baseline | 291 | -$12,705 | 0.91 | 33.09% | Failed; stop |

Development annual net P&L was +$8,230 in 2022, +$9,270 in 2023 and +$8,405 in 2024. The Workbench evaluation used one unchanged candidate, 366 training days in 2024 followed by 365 test days in 2025. Its record succeeded with outcome **Meets criteria**; independent checks also passed the campaign's stricter positive-P&L and PF>1 requirements for both scenarios.

The 2026 baseline failed positive net P&L and PF>1. Its 33.09% drawdown was below the 35% ceiling, but that does not offset the profit failures. Doubled 2026 costs and nearby widths were deliberately not launched. The later loss does not prove that all round-number strategies fail; it stops this fixed candidate under this protocol.

The latest dataset extends into a partial September 29 session. September 28 was selected before outcomes as the last complete calendar day; no partial tail was scored.

![Separate round-number stage equity curves](C:/Users/vince/OneDrive/Desktop/Quant/research/campaigns/remaining-zones-failure-2026-09-30/round-number-equity.png)

## Uncertainty and comparison limits

The round-number development expectancy was $30.95 per trade. Its seeded day-cluster 95% interval was approximately $-52 to $122; it includes zero. The largest winner was +$10,910, about 42% of net development profit, and the ten largest winners supplied 28.4% of winning P&L. Positive yearly totals did not establish stable expectancy.

Intervals are 5,000 seeded resamples of whole occupied Chicago entry days, recalculating net P&L divided by trade count. They are pointwise exploratory estimates, not adjusted for searching ten candidates and not protection against dependence across days. Intervals, occupied-day counts and concentration are retained for every run in summary.json. Later-period intervals also span zero.

The previous-bar benchmark lost $36,985 on 2,288 trades, net PF 0.94. It is an executable descriptive reference, not a matched-location control: trade populations, occupancy and market conditions differ. No claim that the round-number location causally adds value is established by comparing these totals.

Every date is previously inspected retrospective history. The Workbench evaluation preserves earlier overlapping runs. The 2025 sequence is chronological later history, not certified untouched data, and the 2026 extension remains historical research.

## Common mechanical interpretation

All ten candidates used the same frozen +/-0.10 formation ATR zones, 80 subsequent selected-bar lifetime, formation-close arming, no formation-bar entry, first armed physical-touch retirement (including shallow and overnight touches), and deterministic active-price deduplication. Overlapping distinct levels are retained; at most one entry per bar and one position are permitted.

The signal must open on the approach side, wick one tick beyond the far edge and close inside the small zone. A stronger reclaim that closes entirely beyond the near edge is excluded. Entry is the next contiguous 15-minute open and expires if absent. Stop is one tick beyond the sweep extreme; the preserved exit is the 20th entry-inclusive chart-bar close, with the exceptional-move target unchanged. New entries occur 08:30-15:00 Chicago, capped by the frozen holiday calendar; positions can continue afterward.

Higher-timeframe candles require all expected observed 15-minute candles and activate only after strict two-left/two-right pivot confirmation. Opening ranges activate after their completed window. Departure requires 1.5 confirmation ATR; flips require a later break of the original far edge by one tick. Rolling levels use only preceding completed candles. Classic daily S1/R1 uses the previous complete scheduled regular session. The complete frozen definitions are in PROTOCOL.md.

## Verification, provenance and retained limitations

- Ten focused detector tests passed. The first deterministic December 2021 formation per candidate was visually inspected before scored launch; all source-release checks passed. No preview selection used strategy P&L.
- Validate & preview ran before every launch. Development warmup required 142 completed bars and had 1,928; workers reported sufficient coverage. The production build passed with its bundle-size advisory. Unrelated workspace edits were preserved.
- All 14 runs succeeded. All five artifact checksums and byte counts per run were independently checked; full trade P&L and costs reconcile to marked equity. Independently recalculated P&L, trade count, observations and drawdown match Workbench. Entry hours and expected per-trade friction were checked.
- Source prices are unadjusted continuous contracts; rolls can alter detector structure and P&L. No minute or tick completeness claim follows from observed 15-minute continuity. No forward fill, historical order-book replay or margin model is used. Stops use one-minute OHLC with conservative ordering.
- Additional event-entry delay is unavailable. No market transfer, live approval, automatic Watchlist promotion or matched generic-location study was performed.

Evaluation ID: `be9fa51a-f5e3-4b91-ad48-934c165af475`. Dataset: `3b9114199a2f6f0e51b70a63edc43de00940ae5df8d047b3aaa6aa8424aac9f1-v1`; SHA-256 `67092a9b6201747c46ae08029068fd03b42c5def68339ac2434dba78a77386c7`.

## Complete run ledger

| Detector | Stage | Run ID |
| --- | --- | --- |
| 1-hour confirmed swing | development | `7c1a40bf-7054-4ebd-94de-72f5901cb68e` |
| 4-hour confirmed swing | development | `ae22148d-2a94-415f-a38c-d5c0cb64fcb9` |
| 15-minute opening range | development | `4d35b4a4-a1e6-4793-bc14-f10b64c8a65f` |
| 30-minute opening range | development | `d1004334-6522-465b-8029-e0803bf5c263` |
| Strong-departure swing | development | `e3f4200f-9d5d-40a9-a739-0e3b417e5500` |
| Support/resistance flip | development | `c49b4493-a2fe-413e-8876-a6eae7c5781d` |
| 20-bar range extremes | development | `33bdddd0-5ab8-4686-82d2-b1188ba4c86a` |
| 100-point round numbers | development | `2cfb9cbd-596d-416c-98c5-219a23a9f0ad` |
| Classic daily S1/R1 pivots | development | `be50ea13-5ee1-46de-9d3c-db373519c4d2` |
| Previous-bar sweep benchmark | development | `84cb4684-f2ae-41e0-93e9-b12c401c6660` |
| 100-point round numbers | evaluation-Training | `ee80bcfd-2287-4846-8d66-9bcc4a95bcd0` |
| 100-point round numbers | evaluation-Test | `e2afada6-c5da-4a51-9d4b-c54e6b8e20c1` |
| 100-point round numbers | evaluation-Test | `65ec3e8a-37b3-4338-b047-c7c04e616fa1` |
| 100-point round numbers | later-round-100 | `64f737fb-22df-46b2-8dfe-eaf2ed09a913` |

Execution source hashes: `ebb4b3bc751a603a18a344210f15dacb3d17401f5b011fd15b4b9e8f4d72165c`.

Saved beside this report: PROTOCOL.md, REVIEW.md, detection-review.json, campaign.json, summary.json, launch requests and previews, and the completed evaluation record. Complete verified copies live in runs/<run-id>/; primary Workbench records remain available.

The next useful research step is a formation/trigger diagnostic and matched-event comparison, if further research is requested. Any broader reclaim or repeat-touch interpretation needs a new bounded protocol; the failed 2026 result must remain visible rather than being tuned away.
