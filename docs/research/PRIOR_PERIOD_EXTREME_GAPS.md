# How often do weekly and monthly high and low gaps fill?

**The level closer to the open filled about three times as often as the farther level.** In S&P 500 futures (ES) and Nasdaq-100 futures (NQ), price reached the nearer extreme in **77–78% of weeks** and **75–79% of months**. The farther extreme filled in **23–24% of weeks** and **28% of months**. Each comparison uses the prior period's high and low. One equally distant ES week drops out of this comparison.

## Weekly results

Each market had 564 qualifying weeks, from January 2016 through the week ending November 20, 2026. The fill column uses all weeks. The last three columns use only the fills in that row.

| Market | Prior level | Gap filled by week-end | Extended after fill | Rejected after fill | Unresolved |
|---|---|---:|---:|---:|---:|
| ES | High | 347/564 (61.5%) | 53.0% | 45.5% | 1.4% |
| ES | Low | 223/564 (39.5%) | 57.0% | 43.0% | 0.0% |
| NQ | High | 350/564 (62.1%) | 56.9% | 41.7% | 1.4% |
| NQ | Low | 229/564 (40.6%) | 56.8% | 43.2% | 0.0% |

At least one side filled in **88.7% of ES weeks** and **90.8% of NQ weeks**. Both sides filled in 12.4% and 11.9% of weeks, respectively.

## Monthly results

Each market had 126 qualifying months, from January 2016 through October 2026. The last three columns again use only the fills.

| Market | Prior level | Gap filled by month-end | Extended after fill | Rejected after fill | Unresolved |
|---|---|---:|---:|---:|---:|
| ES | High | 89/126 (70.6%) | 53.9% | 46.1% | 0.0% |
| ES | Low | 41/126 (32.5%) | 48.8% | 48.8% | 2.4% |
| NQ | High | 86/126 (68.3%) | 58.1% | 38.4% | 3.5% |
| NQ | Low | 48/126 (38.1%) | 54.2% | 45.8% | 0.0% |

At least one side filled in **92.1% of ES months** and **95.2% of NQ months**. Both sides filled in 11.1% of months in each market. New months opened closer to the prior high in 71% of ES months and 68% of NQ months.

The monthly low had the smallest reaction samples. Of 41 ES monthly low fills, **20 extended, 20 rejected, and one remained unresolved**.

## What counted

- **Gap and fill.** Start at the first futures price of the new week or month. Measure the distance to each prior extreme separately. A gap fills the first time price reaches or crosses that level from the opening side, including an open exactly on the level. If the period opens above the prior high, it must come back down to fill that gap. Each level can fill once per period.
- **Extension and rejection.** After a fill, use two equal distances from the level, each **10% of the prior high–low range**, rounded up to the next tick when needed. The first one-minute close beyond or at the outside threshold counts as an extension. The first close at least that far back inside counts as a rejection. The fill minute's close counts. If neither happens by period-end, the fill remains unresolved. For example, after a fill at the prior low of a 100-point range, a close 10 points lower extends and a close 10 points higher rejects.
- **Session and data.** The study uses local Databento one-minute ES and NQ futures bars, including overnight trading. The trading day starts at 6 p.m. Eastern the evening before and ends at 5 p.m. Eastern. Weeks and months follow the trading date. The latest unfinished week and month are excluded. Two sessions began more than five minutes late in the available bars. Excluding both the affected periods and the periods using them as references removed four weeks and four months per market. Missing minutes are left unfilled. [Databento bar definitions](https://databento.com/docs/schemas/ohlcv)
- **Contract changes.** At a futures roll, the series aligns the incoming contract's first open with the outgoing contract's last close. This approximates the price difference between contracts. Restricting both periods to a single contract still put the nearer level first in fill frequency in both markets and timeframes. That check covered 478 weeks and 41 months per market.

The period-by-period file includes opening prices, the two prior levels, gap sizes in points, fill times and outcomes. The script recreates it from the pinned local datasets. [Period details](../../artifacts/research/prior-period-extremes/periods.csv) · [Study script](../../research/campaigns/prior-period-extremes/study.py)
