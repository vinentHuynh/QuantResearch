# ORB exit analysis

Full, checksum-verified baseline trade ledgers. Existing exits and parameters are unchanged.

Initial risk is the signal-close entry distance to the opposite opening-range edge, multiplied by contract size and point value. Gross/net R divide each trade by that initial dollar risk; costs are excluded from the risk denominator. Dollar payoff ratio instead compares average winning and losing dollar amounts. These are different measures.

The force-flat window begins with the 15:45 New York five-minute bar and normally executes at its 15:50 close. Stops and targets may exit earlier. September is an independent run starting flat, not a continuation of August.

## 2025

Run `9f4a4794-67dc-4be0-a14c-95085b4e9654`. 104 trades; net $8,265.00; costs $1,245.00; average win 1507.778, average loss 1463.100; realized dollar payoff 1.031:1; profit factor 1.113; mean net R 0.062.

| Exit | Trades | Wins | Net P&L | Average net P&L | Average initial risk | Mean gross R | Mean net R | Median minutes held |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| force-flat window | 50 | 42 | $45,340.00 | $906.80 | $1,751.60 | 0.544 | 0.536 | 332.5 |
| limit | 11 | 11 | $33,107.50 | $3,009.77 | $1,508.64 | 2.000 | 1.994 | 140.0 |
| overnight safety | 1 | 1 | $92.50 | $92.50 | $1,050.00 | 0.100 | 0.088 | 1350.0 |
| stop | 42 | 0 | $-70,275.00 | $-1,673.21 | $1,660.71 | -1.000 | -1.008 | 96.5 |

Best 5 trades contributed $19,957.50; removing those trades arithmetically leaves $-11,692.50. This is a concentration diagnostic, not a simulated rule or an estimate of expected performance.

| Exit month | Trades | Closed-trade net P&L |
| --- | ---: | ---: |
| 2025-01 | 7 | $-3,937.50 |
| 2025-02 | 8 | $1,135.00 |
| 2025-03 | 1 | $4,072.50 |
| 2025-04 | 3 | $-162.50 |
| 2025-05 | 8 | $-335.00 |
| 2025-06 | 14 | $-3,090.00 |
| 2025-07 | 14 | $15.00 |
| 2025-08 | 11 | $2,452.50 |
| 2025-09 | 13 | $-3,372.50 |
| 2025-10 | 12 | $4,320.00 |
| 2025-11 | 5 | $942.50 |
| 2025-12 | 8 | $6,225.00 |

### Positions carried beyond the entry date

| Entry | Exit | Reason | Net P&L | Source minutes in entry-day flatten window |
| --- | --- | --- | ---: | ---: |
| 2025-02-17T11:05:00-05:00 | 2025-02-18T09:35:00-05:00 | overnight safety | $92.50 | 0 |
| 2025-07-03T09:55:00-04:00 | 2025-07-04T08:16:00+00:00 | stop | $-1,287.50 | 0 |
| 2025-07-04T09:55:00-04:00 | 2025-07-06T22:02:00+00:00 | limit | $1,682.50 | 0 |
| 2025-11-28T11:10:00-05:00 | 2025-12-01T00:46:00+00:00 | stop | $-2,087.50 | 0 |
| 2025-12-24T10:15:00-05:00 | 2025-12-26T13:41:00+00:00 | limit | $1,762.50 | 0 |

Dates are compared in the strategy timezone. A stop or target exit can also occur after an overnight hold; the exit-reason label alone does not identify every overnight position.

## 2026-Jan-Aug

Run `02fdc136-7166-4213-8d4e-67cf1fdadd7d`. 29 trades; net $11,552.50; costs $332.50; average win 2300.938, average loss 1943.269; realized dollar payoff 1.184:1; profit factor 1.457; mean net R 0.203.

| Exit | Trades | Wins | Net P&L | Average net P&L | Average initial risk | Mean gross R | Mean net R | Median minutes held |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| force-flat window | 11 | 10 | $14,947.50 | $1,358.86 | $2,100.00 | 0.649 | 0.643 | 350.0 |
| limit | 6 | 6 | $21,215.00 | $3,535.83 | $1,771.67 | 2.000 | 1.996 | 163.0 |
| stop | 12 | 0 | $-24,610.00 | $-2,050.83 | $1,947.08 | -1.090 | -1.098 | 51.0 |

Best 5 trades contributed $18,622.50; removing those trades arithmetically leaves $-7,070.00. This is a concentration diagnostic, not a simulated rule or an estimate of expected performance.

| Exit month | Trades | Closed-trade net P&L |
| --- | ---: | ---: |
| 2026-01 | 5 | $-912.50 |
| 2026-03 | 3 | $8,542.50 |
| 2026-04 | 11 | $16,252.50 |
| 2026-05 | 6 | $-3,610.00 |
| 2026-06 | 2 | $-4,350.00 |
| 2026-08 | 2 | $-4,370.00 |

### Positions carried beyond the entry date

| Entry | Exit | Reason | Net P&L | Source minutes in entry-day flatten window |
| --- | --- | --- | ---: | ---: |
| 2026-01-19T10:00:00-05:00 | 2026-01-20T08:07:00+00:00 | stop | $-1,527.50 | 0 |
| 2026-06-19T10:00:00-04:00 | 2026-06-21T22:00:00+00:00 | stop | $-2,117.50 | 0 |

Dates are compared in the strategy timezone. A stop or target exit can also occur after an overnight hold; the exit-reason label alone does not identify every overnight position.

## 2026-Sep-partial

Run `5447bf71-862c-4a2e-883c-a7a72dbfef1a`. 1 trades; net $-2,072.50; costs $12.50; average win undefined, average loss 2072.500; realized dollar payoff undefined:1; profit factor 0.000; mean net R -1.006.

| Exit | Trades | Wins | Net P&L | Average net P&L | Average initial risk | Mean gross R | Mean net R | Median minutes held |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| stop | 1 | 0 | $-2,072.50 | $-2,072.50 | $2,060.00 | -1.000 | -1.006 | 293.0 |

Best 1 trades contributed $-2,072.50; removing those trades arithmetically leaves $0.00. This is a concentration diagnostic, not a simulated rule or an estimate of expected performance.

| Exit month | Trades | Closed-trade net P&L |
| --- | ---: | ---: |
| 2026-09 | 1 | $-2,072.50 |

## Interpretation and limits

A 2R target applies only when a target fills. Scheduled exits can close winners below 2R and losses before -1R. Different opening-range widths mean trades have different dollar risks even at one contract; average winner/loser dollars therefore need not equal the target multiple. Costs reduce realized payoff further.

Exit-group outcomes describe trades that reached each exit. They do not show what would have happened if timed exits were removed or changed. No alternative exit rule was selected using 2026 results.

Monthly values attribute full trade P&L to exit month; dashboard monthly returns use marked equity and can differ. Initial stops/targets are reconstructed from unchanged opening-range rules and original minute bars. Intraminute path, margin liquidation and roll-neutral returns remain unmodeled.
