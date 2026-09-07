# MNQ Market Profile folklore: the 80% rule and naked POCs

MNQ one-minute data, 2019-05-06 to 2026-09-03, 1,893 sessions (1,823 full-length RTH sessions used for profiles). RTH is 08:30-15:00 America/Chicago. Value area is 70% at a 1-point row. Prices are back-adjusted across 29 contract rolls. Round-trip cost is 1.75 points ($3.50).

## 1. The 80% rule

Setup: RTH opens outside the prior session's value area, price re-enters, and two consecutive 30-minute brackets accept inside it. Success is price reaching the far value-area edge before the same session's close.

| Value area / acceptance | Signals | Traverse | 95% Wilson | Excl. early | Rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| volume / close | 400 | 46.8% | 41.9% - 51.6% | 305 | 39.3% |
| volume / range | 189 | 38.1% | 31.5% - 45.2% | 150 | 37.3% |
| tpo / close | 407 | 47.9% | 43.1% - 52.8% | 304 | 40.8% |
| tpo / range | 194 | 39.7% | 33.1% - 46.7% | 155 | 36.8% |

*Excl. early* drops sessions that had already reached the far edge before the signal completed.

### Against matched controls

Two things have to be separated from the rule. First, price sitting inside a balance area tends to reach an edge before the bell whatever the setup: the control set is sessions that opened *inside* the prior value area, sampled at every bracket close, in both directions (5,324 observations). Second, the rule's distinguishing ingredient is the two-period confirmation, so the same scan is run requiring only one accepting bracket. Control rates are re-weighted to each setup's own mix of trigger bracket, direction, and quartile of distance-to-target, so the comparison is not a restatement of how far the far edge happened to be. Control rows are clustered by session, so the control arm is scored at the treatment's sample size and the p-values are conservative.

| Setup | Signals | Matched | Traverse | Matched control | Lift | p |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Two accepting brackets (the rule) | 400 | 400 | 46.8% | 39.7% | +7.1 pp | 0.046 |
| One accepting bracket (no confirmation) | 554 | 554 | 49.5% | 39.1% | +10.4 pp | 0.001 |

### Traded, with costs

Enter at the close of the second accepting bracket, target the far value-area edge, stop 5 points beyond the edge price re-entered through, flat at the RTH close. A bar spanning both levels is booked as a stop.

| Metric | Result |
| --- | ---: |
| Trades | 400 |
| Trades per year | 54.97 |
| Win rate | 43.5% |
| Avg points | -2.80 |
| Total points | -1,120.00 |
| Total dollars | -2,240.00 |
| Profit factor | 0.88 |
| Max drawdown dollars | -4,329.00 |
| T statistic | -0.98 |

### By year

| Year | Signals | Traverse | Win rate | Net points |
| --- | ---: | ---: | ---: | ---: |
| 2019 | 35 | 40.0% | 37.1% | -116.2 |
| 2020 | 58 | 50.0% | 44.8% | -0.2 |
| 2021 | 58 | 46.6% | 39.7% | -225.5 |
| 2022 | 55 | 49.1% | 50.9% | +104.0 |
| 2023 | 53 | 56.6% | 54.7% | +533.0 |
| 2024 | 47 | 44.7% | 40.4% | -308.0 |
| 2025 | 66 | 37.9% | 30.3% | -1,535.0 |
| 2026 | 28 | 50.0% | 57.1% | +428.0 |

## 2. Naked POC revisits

Each full-length RTH session contributes one POC. A level is revisited when a later session actually trades it (full scope), scanning up to 60 sessions -- holiday sessions count toward the lag and can themselves revisit a level -- and right-censoring at the end of the sample. The control levels come from the same sessions: the value-area edges, the range midpoint, a uniform draw from the range, and the POC reflected through the session close, which holds distance-from-close fixed.

| Level | Count | Median dist. from close | <= 1 | <= 2 | <= 3 | <= 5 | <= 10 | <= 20 | <= 50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| poc | 1,823 | 39 | 73.7% | 80.4% | 83.7% | 87.4% | 90.1% | 93.0% | 95.5% |
| vah | 1,823 | 46 | 70.9% | 77.9% | 82.5% | 86.3% | 90.7% | 93.7% | 96.5% |
| val | 1,823 | 63 | 62.7% | 72.1% | 76.9% | 81.8% | 86.2% | 89.6% | 92.6% |
| range_mid | 1,823 | 58 | 69.4% | 77.3% | 81.2% | 85.7% | 89.6% | 92.1% | 94.7% |
| close_mirror | 1,823 | 39 | 71.8% | 78.3% | 82.3% | 85.7% | 90.1% | 92.5% | 95.4% |
| random_in_range | 1,823 | 63 | 63.3% | 73.7% | 78.2% | 83.0% | 88.3% | 92.1% | 94.8% |

### Traded, with costs

At each RTH open, if the nearest untouched prior POC is within 100 points, enter toward it, target the level, stop 1x the distance the other way, flat at the RTH close.

| Metric | Result |
| --- | ---: |
| Trades | 1,183 |
| Trades per year | 161.53 |
| Win rate | 47.3% |
| Avg points | -0.02 |
| Total points | -27.50 |
| Total dollars | -55.00 |
| Profit factor | 1.00 |
| Max drawdown dollars | -4,010.00 |
| T statistic | -0.02 |

## Method notes and limits

- Value areas are built from one-minute OHLCV, spreading each bar's volume evenly across the rows it spans; true tick or bid/ask volume would move the POC by a row or two on some days.
- The prior session is the previous full-length RTH session; holiday and half sessions are excluded from profile formation and from trading.
- Levels are compared across contract rolls using a back-adjusted series. Re-run with `--no-roll-adjust` to see the sensitivity.
- One sample, one instrument, one venue era. The controls, not the headline rate, are the part of this worth trusting.
- Low-volume-node acceleration is not tested here.
