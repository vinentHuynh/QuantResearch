# When does NQ break the previous week's high or low?

**Monday made the most first breaks. Friday traded outside the prior range most often.** Of the 90 weeks that broke the prior high, 50 first broke it on Monday (55.6%). Of the 69 weeks that broke the prior low, 28 first broke it on Monday (40.6%).

The sample covers **156 completed weeks and 772 NQ futures sessions**, November 27, 2023 through November 20, 2026. Both reference levels are fixed before the week opens.

## How often did each day trade beyond last week's range?

Each percentage uses the number of observed sessions for that weekday. A high break requires trading at least one tick above the previous week's high. A low break requires trading at least one tick below its low. A day can break both levels. “Neither” means the entire session stayed within the prior week's range.

| Trading day | Sessions | Higher high | No higher high | Lower low | No lower low | Neither |
|---|---:|---:|---:|---:|---:|---:|
| Monday | 154 | 32.5% | 67.5% | 18.2% | 81.8% | 49.4% |
| Tuesday | 156 | 36.5% | 63.5% | 27.6% | 72.4% | 35.9% |
| Wednesday | 154 | 43.5% | 56.5% | 26.6% | 73.4% | 30.5% |
| Thursday | 154 | 42.9% | 57.1% | 24.0% | 76.0% | 33.1% |
| Friday | 154 | 44.8% | 55.2% | 30.5% | 69.5% | 25.3% |

Across the 156 weeks, **74 broke only the high** (47.4%), **53 broke only the low** (34.0%), **16 broke both** (10.3%), and **13 broke neither** (8.3%).

## If the level was still intact, how often did it break that day?

Each fraction counts first breaks out of sessions that began with that side of the prior range still intact. An opening price already beyond the level counts as a break on that trading day.

| Trading day | First break above prior high | First break below prior low |
|---|---:|---:|
| Monday | 50/154 (32.5%) | 28/154 (18.2%) |
| Tuesday | 12/106 (11.3%) | 19/128 (14.8%) |
| Wednesday | 15/92 (16.3%) | 7/108 (6.5%) |
| Thursday | 8/78 (10.3%) | 3/101 (3.0%) |
| Friday | 5/69 (7.2%) | 12/97 (12.4%) |

For example, **69 Fridays traded above the prior high**. In 64 of those weeks, an earlier session had already broken it. Of the 69 Fridays that began with the prior high intact, only five went on to break it.

**Session convention.** The study uses roll-adjusted NQ one-minute bars and includes overnight trading. The session starting at 5 p.m. Chicago time belongs to the following trading day, so Sunday evening counts toward Monday. Early-close sessions count. Full holiday closures and the final partial week are excluded. A contract switch is adjusted by aligning the incoming open to the outgoing close. The local series ends during the November 24, 2026 session. [Daily observations](../../artifacts/research/prior-period-extremes/nq-weekdays.csv) · [Study script](../../research/campaigns/prior-period-extremes/nq_weekdays.py)
