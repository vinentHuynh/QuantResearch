# MNQ Asia gap-fade strategy backtests

## What this adds to the fill study

The fill study measured how often the New York close is revisited. This run trades that observation: a market order at the 18:00 ET reopen, a resting limit at the reference close, and a flat exit at the deadline, priced with separate slippage and commission and stressed for stops, deadlines, queue position, and selection bias.

Headline rule: **17:00 reference close, Short, gap < 3 bps**.
Period: 2020-01-02 to 2026-08-06. Costs: 1 tick entry slippage, 1 tick slippage on stop and deadline exits, $1.00 commission per round trip ($2.00 all-in when both legs are market orders). Stop: none. Size: one MNQ contract, $2 per point.

## Headline rule versus passive overnight length

| rule | trades | trades_per_year | fill_rate | win_rate | avg_net_pnl_dollars | per_trade_tstat | total_net_pnl_dollars | pnl_per_year_dollars | profit_factor | sharpe_ratio | max_drawdown_dollars | worst_trade_dollars |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 17:00 reference close, Short, gap < 3 bps | 395 | 76 | 98.2% | 70.9% | 1.49 | 2.52 | 590 | 113 | 2.12 | 1.10 | 178 | -178 |
| Long the reopen to the deadline | 1311 | 252 | 0.0% | 51.6% | 1.95 | 0.48 | 2558 | 492 | 1.04 | 0.21 | 4570 | -766 |

Sharpe uses daily P&L over every session the rule could have traded, so days the filter stands aside count as zeros.

## Calendar years

| year | trades | trades_per_year | fill_rate | win_rate | avg_net_pnl_dollars | per_trade_tstat | total_net_pnl_dollars | pnl_per_year_dollars | profit_factor | sharpe_ratio | max_drawdown_dollars | worst_trade_dollars |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2020 | 40 | 50 | 97.5% | 72.5% | 0.57 | 0.45 | 23 | 29 | 1.45 | 0.50 | 48 | -48 |
| 2021 | 78 | 98 | 97.4% | 75.6% | 1.28 | 1.57 | 100 | 125 | 2.10 | 1.74 | 41 | -41 |
| 2022 | 59 | 75 | 100.0% | 59.3% | 1.65 | 5.43 | 98 | 123 | 9.12 | 5.28 | 2 | -1 |
| 2023 | 63 | 80 | 98.4% | 61.9% | 0.80 | 0.84 | 50 | 64 | 1.75 | 0.94 | 56 | -56 |
| 2024 | 64 | 82 | 96.9% | 73.4% | 1.34 | 0.88 | 86 | 110 | 1.73 | 1.00 | 88 | -88 |
| 2025 | 60 | 77 | 100.0% | 75.0% | 3.94 | 7.04 | 236 | 304 | 34.79 | 6.38 | 2 | -1 |
| 2026 | 31 | 65 | 96.8% | 83.9% | -0.13 | -0.02 | -4 | -8 | 0.98 | -0.03 | 178 | -178 |

## Cost sensitivity

Slippage is split evenly between the two legs; only market exits pay the exit leg, so the all-in figure is an upper bound that the mostly-limit exits do not reach.

| slippage_ticks_rt | all_in_cost_dollars | trades | avg_net_pnl_dollars | per_trade_tstat | total_net_pnl_dollars | profit_factor | sharpe_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.0 | 1.00 | 395 | 2.00 | 3.39 | 790 | 2.63 | 1.47 |
| 1.0 | 1.50 | 395 | 1.75 | 2.96 | 690 | 2.36 | 1.29 |
| 2.0 | 2.00 | 395 | 1.49 | 2.52 | 590 | 2.12 | 1.10 |
| 3.0 | 2.50 | 395 | 1.24 | 2.09 | 489 | 1.88 | 0.91 |
| 4.0 | 3.00 | 395 | 0.98 | 1.65 | 388 | 1.66 | 0.72 |
| 6.0 | 4.00 | 395 | 0.47 | 0.79 | 188 | 1.28 | 0.35 |
| 8.0 | 5.00 | 395 | -0.03 | -0.06 | -14 | 0.98 | -0.02 |

## Protective stop

A stop caps the rare non-fill tail but converts near-misses into realized losses. When a bar touches both levels the stop is assumed to trade first.

| stop_points | trades | fill_rate | stop_rate | avg_net_pnl_dollars | per_trade_tstat | total_net_pnl_dollars | profit_factor | max_drawdown_dollars | worst_trade_dollars |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| n/a | 395 | 98.2% | 0.0% | 1.49 | 2.52 | 590 | 2.12 | 178 | -178 |
| 10 | 395 | 64.6% | 35.4% | -6.19 | -10.29 | -2446 | 0.22 | 2452 | -22 |
| 20 | 395 | 86.3% | 13.7% | -3.58 | -4.57 | -1414 | 0.39 | 1443 | -42 |
| 30 | 395 | 92.7% | 6.8% | -1.99 | -2.37 | -786 | 0.56 | 840 | -62 |
| 50 | 395 | 97.0% | 1.8% | 0.18 | 0.24 | 73 | 1.07 | 246 | -102 |
| 80 | 395 | 98.0% | 0.5% | 1.09 | 1.56 | 430 | 1.64 | 324 | -162 |

## Queue position at the target

A touch of the limit price is not a fill. Each buffer tick requires the market to trade that much further through the level before the trade is counted as filled.

| fill_buffer_ticks | trades | fill_rate | avg_net_pnl_dollars | per_trade_tstat | total_net_pnl_dollars | profit_factor | max_drawdown_dollars |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 395 | 98.2% | 1.49 | 2.52 | 590 | 2.12 | 178 |
| 1 | 395 | 97.0% | -0.24 | -0.23 | -96 | 0.92 | 372 |
| 4 | 395 | 96.7% | -0.35 | -0.34 | -139 | 0.89 | 372 |
| 8 | 395 | 95.7% | -1.46 | -1.21 | -576 | 0.65 | 658 |

Every buffer removes the same 5 sessions (1.3% of trades), because on a 0.25-point grid a session either stops exactly at the target tick or runs well past it. Those sessions are the entire result: filled they contribute $24, missed they cost $-661, a $685 swing against a $590 total. The dates are 2020-02-18, 2022-05-04, 2024-07-25, 2024-07-31, 2026-01-27.

Reality sits between the two rows. A limit resting since 18:00 has hours of queue priority and often does fill on an exact touch, but the strategy's whole margin rides on that handful of nights, which is a thin place for an edge to live.

## Deadline

| asia_end | trades | fill_rate | avg_net_pnl_dollars | per_trade_tstat | total_net_pnl_dollars | profit_factor | max_drawdown_dollars | avg_minutes_held |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 21:00 | 395 | 97.2% | 1.12 | 1.90 | 444 | 1.68 | 223 | 15 |
| 23:00 | 395 | 98.2% | 1.52 | 2.77 | 600 | 2.16 | 145 | 17 |
| 00:00 | 395 | 98.2% | 1.49 | 2.52 | 590 | 2.12 | 178 | 18 |
| 02:00 | 395 | 98.2% | 1.35 | 1.91 | 532 | 1.91 | 204 | 20 |
| 04:00 | 395 | 99.0% | 1.63 | 2.43 | 644 | 2.33 | 298 | 22 |
| 09:30 | 395 | 99.2% | 1.63 | 1.99 | 642 | 2.32 | 380 | 25 |

## Is the edge real?

### The rule on its own terms

Per-session P&L is not remotely normal, so the ordinary t-statistic is the wrong yardstick. A circular block bootstrap of the demeaned series measures the same statistic against the shape the data actually has.

- Per-session skewness -18.8, excess kurtosis 465: many small target wins, rare large non-fill losses.
- Observed t-statistic 2.51; normal-theory p-value 0.0061.
- Block bootstrap p-value **0.0010** over 4000 resamples, with the null 95th percentile at t = 1.52.

The left skew cuts both ways. It compresses the upper tail of the null, so a positive mean of this size is harder to fake than normal theory implies, but it also means the loss distribution is where the risk lives: the average is safe long before any single night is.

## Every competing rule

The headline rule was chosen after seeing this whole surface, so its statistics are the maximum of a search rather than a clean test.

| reference_close | side | max_gap_bps | trades | fill_rate | avg_net_pnl_dollars | per_trade_tstat | per_session_tstat | total_net_pnl_dollars | sharpe_ratio | max_drawdown_dollars |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 17:00 | Short | 3.0 | 395 | 98.2% | 1.49 | 2.52 | 2.51 | 590 | 1.10 | 178 |
| 17:00 | Short | 7.5 | 578 | 95.7% | 1.74 | 1.58 | 1.58 | 1006 | 0.69 | 648 |
| 17:00 | Short | 5.0 | 517 | 96.3% | 1.39 | 1.38 | 1.38 | 718 | 0.60 | 502 |
| 16:00 | Short | 2.0 | 86 | 97.7% | 0.83 | 0.81 | 0.81 | 72 | 0.36 | 98 |
| 17:00 | Short | 10.0 | 619 | 94.3% | 0.87 | 0.67 | 0.67 | 540 | 0.29 | 735 |
| 16:00 | Long | inf | 581 | 70.2% | 1.66 | 0.42 | 0.42 | 966 | 0.18 | 1782 |
| 17:00 | Short | 2.0 | 296 | 98.3% | 0.02 | 0.03 | 0.03 | 6 | 0.01 | 178 |
| 17:00 | Both | 7.5 | 1018 | 94.7% | -0.17 | -0.16 | -0.16 | -176 | -0.07 | 1414 |
| 16:00 | Long | 25.0 | 484 | 76.4% | -1.15 | -0.32 | -0.32 | -556 | -0.14 | 2176 |
| 16:00 | Short | 7.5 | 292 | 87.3% | -0.73 | -0.35 | -0.35 | -213 | -0.15 | 660 |
| 16:00 | Short | 5.0 | 198 | 92.9% | -0.97 | -0.41 | -0.41 | -192 | -0.18 | 510 |
| 17:00 | Both | 5.0 | 908 | 95.4% | -0.47 | -0.50 | -0.50 | -430 | -0.22 | 876 |
| 16:00 | Long | 7.5 | 251 | 84.9% | -1.42 | -0.58 | -0.59 | -356 | -0.26 | 980 |
| 17:00 | Short | 15.0 | 654 | 92.8% | -1.07 | -0.62 | -0.62 | -698 | -0.27 | 1655 |
| 16:00 | Both | 7.5 | 543 | 86.2% | -1.05 | -0.66 | -0.66 | -569 | -0.29 | 1176 |
| 16:00 | Short | 1.0 | 46 | 97.8% | -1.08 | -0.67 | -0.67 | -50 | -0.30 | 75 |
| 16:00 | Both | 2.0 | 156 | 97.4% | -1.74 | -0.68 | -0.68 | -272 | -0.30 | 376 |
| 16:00 | Short | 3.0 | 133 | 94.7% | -2.20 | -0.77 | -0.77 | -293 | -0.34 | 395 |
| 16:00 | Long | 1.0 | 36 | 97.2% | -2.86 | -0.84 | -0.84 | -103 | -0.37 | 122 |
| 16:00 | Both | 25.0 | 1069 | 74.5% | -1.77 | -0.86 | -0.86 | -1892 | -0.38 | 3029 |

### Reality check

- Rules searched: 54
- Best rule by per-session t-statistic: `17:00|Short|3` at t = 2.51
- Stationary block bootstrap (2000 resamples, 5-session blocks) under the no-edge null puts the 95th percentile of the best t-statistic at 2.65
- Reality-check p-value: **0.086**

The p-value asks whether the best rule in the search beats what the best of an equally large search would produce on data with no edge.

## Walk-forward selection

Each year's rule is chosen only from earlier data, by in-sample per-trade t-statistic among rules with at least 100 prior trades.

| test_year | chosen_side | chosen_max_gap_bps | train_trades | train_tstat | train_avg_net_pnl_dollars | trades | avg_net_pnl_dollars | total_net_pnl_dollars | profit_factor |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2022 | Short | 3.0 | 118 | 1.50 | 1.04 | 59 | 1.65 | 98 | 9.12 |
| 2023 | Short | 3.0 | 177 | 2.64 | 1.25 | 63 | 0.80 | 50 | 1.75 |
| 2024 | Short | 7.5 | 339 | 2.72 | 2.23 | 95 | -0.08 | -8 | 0.99 |
| 2025 | Short | 3.0 | 304 | 2.53 | 1.17 | 60 | 3.94 | 236 | 34.79 |
| 2026 | Short | 3.0 | 364 | 4.05 | 1.63 | 31 | -0.13 | -4 | 0.98 |

Pooled out-of-sample: 308 trades, $1.21 average, t = 1.12, $373 total, profit factor 1.41, max drawdown $487.

## What the numbers do not cover

- The source is an unadjusted Databento continuous front-month series. A roll switch at the 18:00 reopen cannot be identified or removed here.
- Limit fills are modelled from bar extremes. The buffer sweep bounds the queue-position error but does not replace order-book data.
- Stop and target order inside a bar is unobservable at 5-minute resolution; the stop is always assumed to win.
- One contract throughout. There is no compounding, no margin check, and no position sizing, so Sharpe describes the shape of the P&L rather than the return on an account.
- The walk-forward test validates the selection procedure, not the already-published rule, which no longer has untouched data available.
