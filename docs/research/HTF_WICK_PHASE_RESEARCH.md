# Higher-timeframe wick-phase research

This study tests whether repeated lower wicks in a compact range after a decline are followed by a move toward higher prices, and whether repeated upper wicks after a rise are followed by a move toward lower prices. These are **price-pattern proxies** for accumulation and distribution. OHLCV alone cannot identify who traded or whether institutions accumulated inventory.

## Fixed definitions before reading forward outcomes

The primary chart is **4-hour MNQ**. One-hour MNQ and 4-hour ES/CL are supporting market and timeframe checks; daily bars are descriptive because the strict contract and data-coverage gates leave few episodes. Results use the available historical data through September 3, 2026. The repository has inspected parts of this history for other research, so chronological segments are stability checks rather than untouched holdouts.

For a completed candle with open \(O\), high \(H\), low \(L\), close \(C\), and range \(R=H-L>0\):

| Data point | Definition | Reading |
| --- | --- | --- |
| Lower wick | \(\min(O,C)-L\) | Distance below the candle body |
| Upper wick | \(H-\max(O,C)\) | Distance above the candle body |
| Body | \(|C-O|\) | Open-to-close movement |
| Lower/upper share | Each wick divided by \(R\) | Comparable across price levels |
| Wick-to-body ratio | Each wick divided by \(\max(|C-O|,\text{tick size})\) | Wick length relative to the open/close body; the tick floor handles dojis |
| Wick skew | \((\text{lower}-\text{upper})/R\) | Positive means lower-wick dominance |
| Open/close location | \((O-L)/R\), \((C-L)/R\) | 0 is the candle low; 1 is the high |

At a signal candle \(t\), the candidate phase is the six completed candles \(t-5\) through \(t\). A strictly earlier 20-candle context supplies a frozen ATR and trend: \(t-25\) through \(t-6\), with \(t-26\) only for its preceding close. Phase compactness is its high-low span divided by that ATR; it must be at most **2.5**. A preceding decline or rise must span at least **1 ATR**. Aggregate phase wick skew is the sum of lower-minus-upper wicks divided by the sum of ranges. At least **+0.10** after a decline labels an accumulation proxy; at most **−0.10** after a rise labels a distribution proxy. Compact phases in the **same prior trend** with absolute skew below **0.10** are the neutral comparison. The first eligible signal is selected, followed by a six-bar cooldown across all wick groups.

The primary data-quality rule requires at least 90% of expected one-minute observations in every bar used by the context, phase, and scored forward horizon, valid nonzero OHLC ranges, and one contract throughout. Each represented intraday session must contain every expected higher-timeframe bucket, so a phase cannot span an unobserved candle. A 75% minute-coverage threshold is a prespecified sensitivity check for sparse one-minute observations in otherwise complete sessions; it does not admit early-close sessions with missing buckets. Mixed-contract candles and windows crossing rolls are excluded. Signals are only known after candle \(t\) closes.

## Forward measurements

Starting at the completed signal close, symmetric barriers are placed **±1 frozen ATR** away. Over the next **3** and **6** higher-timeframe candles, the study counts upper first, lower first, both touched in one candle (ambiguous), and neither. It also records the largest upward and downward excursion in ATR units, the directional excursion lean \((up-down)/(up+down)\), and where later closes fall within the *previously frozen* phase range. These future readings start after the signal candle. The signal candle's own close location is descriptive because it is partly determined by its wick and body geometry.

No result here is a trading return or an after-cost strategy test. First-hit rates exclude ambiguous and neither cases from their directional denominator while reporting those cases separately. Comparisons should state sample counts, time clustering, and whether effects persist across periods and markets.

## Results

The table uses the conservative **90% minute coverage** rule and a common 2019–2026 interval. The count in each rate is *favorable first hits / decisive first hits*: upside first after a decline, downside first after a rise. Ambiguous, neither, and censored episodes remain in each run's ledger and summary; they are not silently counted as wins. The intervals are exploratory, pointwise 95% calendar-month block intervals for the proxy-minus-same-trend-neutral difference, without a multiple-comparison correction.

| Market, 4h proxy | Selected proxy / neutral episodes | 3-bar favorable first hits: proxy vs neutral | Difference (95% interval) | 6-bar favorable first hits: proxy vs neutral | Difference (95% interval) |
| --- | ---: | ---: | ---: | ---: | ---: |
| MNQ lower wicks after decline | 110 / 160 | 21/60 vs 44/84 | **−17.4 pp** [−31.8, −2.4] | 43/94 vs 69/128 | −8.2 pp [−18.9, 3.2] |
| ES lower wicks after decline | 111 / 154 | 30/64 vs 52/89 | −11.6 pp [−28.2, 4.7] | 49/95 vs 79/134 | −7.4 pp [−20.8, 4.7] |
| CL lower wicks after decline | 84 / 147 | 21/40 vs 36/76 | +5.1 pp [−15.1, 24.8] | 42/68 vs 54/116 | +15.2 pp [−0.4, 30.6] |
| MNQ upper wicks after rise | 69 / 237 | 20/33 vs 53/111 | +12.9 pp [−7.5, 34.5] | 30/54 vs 86/183 | +8.6 pp [−5.8, 21.1] |
| ES upper wicks after rise | 82 / 260 | 23/40 vs 71/129 | +2.5 pp [−17.3, 20.7] | 36/73 vs 96/199 | +1.1 pp [−13.7, 14.5] |
| CL upper wicks after rise | 60 / 192 | 19/36 vs 45/106 | +10.3 pp [−10.3, 30.3] | 27/50 vs 73/156 | +7.2 pp [−6.8, 22.1] |

The lower-wick accumulation proxy **did not produce a stable bounce toward the highs**: it was weaker than same-trend neutral phases in MNQ and ES at three and six bars, but stronger in CL at six bars. The MNQ three-bar interval excludes zero in this single exploratory comparison, while the broader pattern changes by market and horizon. Upper-wick distribution proxies leaned toward a downside first hit at three bars in all three markets, but each 4-hour interval includes zero and the contrast weakens by six bars. This is a short-horizon association to investigate, not a confirmed distribution signal.

Later **closes** give a second view of "toward the highs/lows." The table is the mean change from the signal close to the close three bars later, divided by the frozen six-bar phase range. Positive means toward higher prices; negative means toward lower prices. It includes every episode with a complete three-bar horizon, even if neither ATR barrier was touched. These descriptive means have no uncertainty interval.

| Market, 4h context | Proxy mean (complete episodes) | Same-trend neutral mean (complete episodes) |
| --- | ---: | ---: |
| MNQ, lower wicks after decline | −0.082 (106) | +0.048 (157) |
| ES, lower wicks after decline | −0.008 (107) | +0.042 (151) |
| CL, lower wicks after decline | +0.079 (77) | −0.016 (136) |
| MNQ, upper wicks after rise | −0.063 (67) | +0.043 (225) |
| ES, upper wicks after rise | +0.031 (81) | +0.028 (249) |
| CL, upper wicks after rise | +0.027 (58) | +0.037 (179) |

The anatomy metrics confirm the labels represent different wick geometry. In MNQ 4h selected accumulation-proxy episodes, median **lower-wick/body** was **0.90** versus **0.55** in downtrend-neutral phases; median upper-wick/body was **0.45** versus **0.55**. Yet their mean next-three-bar close movement relative to the *frozen phase range* was **−0.082** versus **+0.048** from the signal close. In MNQ distribution-proxy episodes, median **upper-wick/body** was **0.86** versus **0.54** in uptrend-neutral phases. Current-candle close locations are included in the ledgers as descriptive data, but cannot by themselves establish later movement.

Supporting checks: On MNQ **1h**, the three-bar accumulation contrast was **−5.7 pp** (95% interval [−15.4, 5.1]); distribution was **+11.9 pp** ([1.2, 24.0]). The latter is one of several tested comparisons and was not reproduced as a clear 4h advantage in ES or CL. MNQ **daily** had only **2** selected accumulation and **1** distribution episodes under the strict gate, so daily percentages are not interpretable. Chronological 60/20/20 breakdowns in each run's `summary.md` are mixed; they are retrospective stability checks, not untouched holdouts. Under the prespecified **75% minute coverage** sensitivity, the MNQ 4h three-bar accumulation difference remains negative (−16.3 pp), ES remains −11.6 pp, and CL is −1.6 pp; no cross-market accumulation advantage emerges.

## Artifacts and reproduction

Each result directory contains the frozen protocol, exact source snapshot, SHA-256 manifest, candidate/event ledger, machine-readable summary, and readable tables. The main 90% runs are [MNQ](../../artifacts/research/htf-wick-phases/MNQ-q90-20260928T064642Z-86f58244/summary.md), [ES](../../artifacts/research/htf-wick-phases/ES-q90-20260928T064642Z-75c83dff/summary.md), and [CL](../../artifacts/research/htf-wick-phases/CL-q90-20260928T064643Z-a12355b3/summary.md). The 75% sensitivity runs are [MNQ](../../artifacts/research/htf-wick-phases/MNQ-q75-20260928T064643Z-1a4930cf/summary.md), [ES](../../artifacts/research/htf-wick-phases/ES-q75-20260928T064643Z-01077f53/summary.md), and [CL](../../artifacts/research/htf-wick-phases/CL-q75-20260928T064643Z-bcfcf7fc/summary.md). ES and CL higher-timeframe files were built from registered one-minute data by [the resampling helper](../../scripts/prepare-htf-wick-inputs.py), with source/output checksums in [ES](../../artifacts/research/htf-wick-phases/inputs/ES/resample_manifest.json) and [CL](../../artifacts/research/htf-wick-phases/inputs/CL/resample_manifest.json) manifests. The study code is [research-htf-wick-phases.py](../../scripts/research-htf-wick-phases.py). An [independent auditor](../../scripts/audit-htf-wick-results.py) recomputed the selected-event features and outcomes; [verification.json](../../artifacts/research/htf-wick-phases/verification.json) records zero mismatches across all six final runs.

These are historical price-behaviour measurements, not a tested trading strategy. The futures series are continuous and unadjusted; contract-change windows were excluded, while missing minutes and shortened sessions were handled with the stated gates. MNQ and ES are related equity-index markets, so they are not independent transfers. The prior repository research has inspected parts of the same history, and this campaign tests multiple directions, horizons, timeframes, and markets. A prospective sample would be needed to assess persistence. Research on technical-rule testing also documents how broad historical searches can make isolated patterns look stronger than they are ([Sermpinis et al., 2018](https://arxiv.org/abs/1811.06766)).
