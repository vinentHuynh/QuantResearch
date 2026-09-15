# Strategy potential: 2025 evaluations and regimes

## Protocol

- **calibration:** 2024-01-01 to 2024-12-31
- **test:** 2025-01-01 to 2025-12-31
- **parameters:** Frozen 2022 selections; one candidate per strategy, no retuning or exclusion based on 2024 profitability.
- **sizing:** Same one-contract settings, $100000 starting capital, $1.25 fee and one tick per side. ORB stop-risk cap $2500.
- **protocol:** One chronological fold: 366 training days, 365 test days. Training eligibility: finite net P&L, zero minimum trades so every fixed configuration is evaluated. Test: nonnegative net return, drawdown <=35%, original strategy-specific minimum trade count.
- **scenarios:** Baseline and doubled costs for all nine; one additional chart-bar delay for five signal strategies. Event-order delay unavailable.
- **regimes:** {"features":["volatility","trend"],"lookback_bars":20,"training_quantile":0.5,"seed":42}
- **interpretation:** Descriptive historical potential at tested sizing. Later history, not certified untouched data. Regime attribution does not simulate trading only in a selected state.

## Every strategy

| Strategy | 2025 net P&L | Max drawdown | Trades | Doubled-cost P&L | Delayed P&L | Historical assessment |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| buy-hold | $83,302.50 | -95.51% | 1 | $83,290.00 | $83,302.50 | Passive benchmark; assess drawdown separately |
| moving-average | $88,640.00 | -38.31% | 124 | $87,090.00 | $39,135.00 | Did not meet 2025 return/risk/trade criteria |
| multi-speed-momentum | $18,870.00 | -36.65% | 290 | $15,245.00 | -$3,790.00 | Did not meet 2025 return/risk/trade criteria |
| rsi2-reversion | $59,687.50 | -49.59% | 17 | $59,475.00 | $14,902.50 | Did not meet 2025 return/risk/trade criteria |
| vwap-reversion | -$69,730.00 | -86.65% | 306 | -$73,555.00 | -$101,465.00 | Did not meet 2025 return/risk/trade criteria |
| pine-overnight-block | $18,292.50 | -23.54% | 257 | $15,080.00 | Unavailable for event orders | 2025 checks pass; earlier weaknesses remain |
| pine-daily-tsmom | $66,117.50 | -51.14% | 9 | $66,005.00 | Unavailable for event orders | Did not meet 2025 return/risk/trade criteria |
| pine-overnight-drift | $13,212.50 | -27.51% | 93 | $12,050.00 | Unavailable for event orders | 2025 checks pass; earlier weaknesses remain |
| pine-tsmom-orb | $8,265.00 | -10.10% | 104 | $7,020.00 | Unavailable for event orders | Passed prior and 2025 checks; further research candidate |

## Regime attribution

Higher/Lower means above/below the **2024 training median**, not necessarily bull/bear or positive/negative trend. Features use 20 bars of each strategy's native timeframe, lagged one completed bar; horizons differ between strategies. Net P&L comes from the original continuous path, including costs. These are not separate state-only trading backtests. Unequal exposure, time in each state, and dependent episodes limit comparisons.

### buy-hold

Passive benchmark; assess drawdown separately.

Evaluation: a16f153c-b3f2-4aa5-b7ea-509b2d396466. Parameters: `{"contracts":1}`.

| Feature | State | Bars | Episodes | Net P&L | P&L/bar | Invested bars | Entries | Mean episode P&L (95% bootstrap interval) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| volatility | Higher | 3385 | 101 | $61,138.75 | $18.06 | 100.00% | 1 | $605.33 (-$559.75 to $1,704.75) |
| volatility | Lower | 2495 | 101 | $22,163.75 | $8.88 | 100.00% | 0 | $219.44 (-$474.26 to $1,023.11) |
| trend | Higher | 2950 | 334 | $65,390.00 | $22.17 | 100.00% | 0 | $195.78 (-$151.28 to $559.34) |
| trend | Lower | 2930 | 335 | $17,912.50 | $6.11 | 100.00% | 1 | $53.47 (-$320.40 to $391.33) |

### moving-average

Did not meet 2025 return/risk/trade criteria.

Evaluation: cae2ad70-e18e-4340-ac98-8e2ce353c93d. Parameters: `{"lookback":80,"contracts":1}`.

| Feature | State | Bars | Episodes | Net P&L | P&L/bar | Invested bars | Entries | Mean episode P&L (95% bootstrap interval) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| volatility | Higher | 3385 | 101 | $56,538.75 | $16.70 | 45.73% | 84 | $559.79 (-$162.15 to $1,341.94) |
| volatility | Lower | 2495 | 101 | $32,101.25 | $12.87 | 80.04% | 40 | $317.83 (-$213.80 to $953.04) |
| trend | Higher | 2950 | 334 | $16,130.00 | $5.47 | 81.49% | 85 | $48.29 (-$245.92 to $367.94) |
| trend | Lower | 2930 | 335 | $72,510.00 | $24.75 | 38.94% | 39 | $216.45 ($39.37 to $389.39) |

### multi-speed-momentum

Did not meet 2025 return/risk/trade criteria.

Evaluation: f67b999b-346b-462b-8625-c71aaec24241. Parameters: `{"lookback":60,"contracts":1}`.

| Feature | State | Bars | Episodes | Net P&L | P&L/bar | Invested bars | Entries | Mean episode P&L (95% bootstrap interval) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| volatility | Higher | 3385 | 101 | $18,771.25 | $5.55 | 80.03% | 191 | $185.85 (-$1,052.95 to $1,594.70) |
| volatility | Lower | 2495 | 101 | $98.75 | $0.04 | 87.41% | 99 | $0.98 (-$672.33 to $644.71) |
| trend | Higher | 2950 | 334 | -$61,181.25 | -$20.74 | 86.24% | 124 | -$183.18 (-$477.82 to $141.92) |
| trend | Lower | 2930 | 335 | $80,051.25 | $27.32 | 80.07% | 166 | $238.96 (-$75.18 to $580.08) |

### rsi2-reversion

Did not meet 2025 return/risk/trade criteria.

Evaluation: f2800155-a603-4cf8-9992-6184f0e2f080. Parameters: `{"trend_lookback":100,"entry_rsi":10,"exit_rsi":70,"contracts":1}`.

| Feature | State | Bars | Episodes | Net P&L | P&L/bar | Invested bars | Entries | Mean episode P&L (95% bootstrap interval) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| volatility | Higher | 166 | 5 | $5,438.75 | $32.76 | 43.98% | 10 | $1,087.75 (unavailable: sparse) |
| volatility | Lower | 92 | 5 | $54,248.75 | $589.66 | 56.52% | 7 | $10,849.75 (unavailable: sparse) |
| trend | Higher | 117 | 18 | $22,642.50 | $193.53 | 43.59% | 7 | $1,257.92 (-$1,925.95 to $5,503.24) |
| trend | Lower | 141 | 19 | $37,045.00 | $262.73 | 52.48% | 10 | $1,949.74 (-$4,355.75 to $6,401.95) |

### vwap-reversion

Did not meet 2025 return/risk/trade criteria.

Evaluation: bd9a3a87-ff60-4258-a84d-c5481b98592e. Parameters: `{"band":0.004,"contracts":1}`.

| Feature | State | Bars | Episodes | Net P&L | P&L/bar | Invested bars | Entries | Mean episode P&L (95% bootstrap interval) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| volatility | Higher | 10241 | 251 | -$55,207.50 | -$5.39 | 50.01% | 253 | -$219.95 (-$631.52 to $148.92) |
| volatility | Lower | 9454 | 251 | -$14,522.50 | -$1.54 | 26.33% | 53 | -$57.86 (-$300.50 to $185.49) |
| trend | Higher | 9837 | 1204 | -$36,015.00 | -$3.66 | 34.93% | 138 | -$29.91 (-$113.84 to $51.77) |
| trend | Lower | 9858 | 1205 | -$33,715.00 | -$3.42 | 42.35% | 168 | -$27.98 (-$120.98 to $64.60) |

### pine-overnight-block

2025 checks pass; earlier weaknesses remain.

Evaluation: a73b8f4c-45de-4f28-b06d-907fc6b00209. Parameters: `{"entry_hour":23,"entry_minute":0,"exit_hour":6,"exit_minute":0,"contracts":1,"timezone":"America/New_York"}`.

| Feature | State | Bars | Episodes | Net P&L | P&L/bar | Invested bars | Entries | Mean episode P&L (95% bootstrap interval) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| volatility | Higher | 39356 | 814 | $4,705.00 | $0.12 | 18.47% | 67 | $5.78 (-$54.18 to $53.51) |
| volatility | Lower | 31162 | 813 | $13,587.50 | $0.44 | 45.94% | 190 | $16.71 (-$23.34 to $53.67) |
| trend | Higher | 35492 | 4311 | $27,343.75 | $0.77 | 29.74% | 113 | $6.34 (-$2.33 to $15.03) |
| trend | Lower | 35026 | 4312 | -$9,051.25 | -$0.26 | 31.50% | 144 | -$2.10 (-$14.34 to $7.29) |

### pine-daily-tsmom

Did not meet 2025 return/risk/trade criteria.

Evaluation: 84099fab-02d9-43f6-8d5a-8ee5e7de5ed0. Parameters: `{"fast_length":10,"medium_length":60,"slow_length":90,"annual_length":252,"sizing_mode":"Fixed contracts","contracts":1,"annual_risk":0.2,"maximum_leverage":2,"volatility_length":60,"sleeve_count":1,"rounding":"Nearest"}`.

| Feature | State | Bars | Episodes | Net P&L | P&L/bar | Invested bars | Entries | Mean episode P&L (95% bootstrap interval) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| volatility | Higher | 13003 | 321 | $31,208.75 | $2.40 | 84.01% | 9 | $97.22 (-$257.55 to $447.20) |
| volatility | Lower | 10503 | 320 | $34,908.75 | $3.32 | 95.26% | 0 | $109.09 (-$105.07 to $327.12) |
| trend | Higher | 11979 | 1377 | $56,898.75 | $4.75 | 89.13% | 5 | $41.32 (-$43.59 to $120.07) |
| trend | Lower | 11527 | 1378 | $9,218.75 | $0.80 | 88.94% | 4 | $6.69 (-$86.80 to $92.28) |

### pine-overnight-drift

2025 checks pass; earlier weaknesses remain.

Evaluation: 67918bee-816a-4513-a66b-a649f7f9e142. Parameters: `{"sizing_mode":"Fixed contracts","contracts":1,"annual_risk":0.2,"maximum_leverage":2,"volatility_length":60,"sleeve_count":4,"timezone":"America/New_York","rth_start":570,"rth_end":960,"trade_weekend":false,"close_rule":"Long after down close","strong_threshold":0.6}`.

| Feature | State | Bars | Episodes | Net P&L | P&L/bar | Invested bars | Entries | Mean episode P&L (95% bootstrap interval) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| volatility | Higher | 39356 | 814 | $24,267.50 | $0.62 | 23.77% | 80 | $29.81 (-$45.87 to $100.72) |
| volatility | Lower | 31162 | 813 | -$11,055.00 | -$0.35 | 28.32% | 13 | -$13.60 (-$46.41 to $19.81) |
| trend | Higher | 35492 | 4311 | $17,566.25 | $0.49 | 25.47% | 36 | $4.07 (-$6.86 to $15.78) |
| trend | Lower | 35026 | 4312 | -$4,353.75 | -$0.12 | 26.09% | 57 | -$1.01 (-$13.24 to $9.35) |

### pine-tsmom-orb

Passed prior and 2025 checks; further research candidate.

Evaluation: 58d0b3e3-9c92-4601-84b3-370732a88e02. Parameters: `{"fast_length":20,"medium_length":60,"slow_length":120,"annual_length":252,"timezone":"America/New_York","minimum_score":0.5,"opening_start":570,"opening_end":585,"entry_start":585,"entry_end":900,"flatten_start":945,"flatten_end":960,"risk_budget":2500,"maximum_contracts":1,"reward_risk":2,"require_close_break":true}`.

| Feature | State | Bars | Episodes | Net P&L | P&L/bar | Invested bars | Entries | Mean episode P&L (95% bootstrap interval) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| volatility | Higher | 39356 | 814 | $4,490.00 | $0.11 | 7.88% | 91 | $5.52 (-$34.51 to $49.37) |
| volatility | Lower | 31162 | 813 | $3,775.00 | $0.12 | 5.37% | 13 | $4.64 (-$9.84 to $19.77) |
| trend | Higher | 35492 | 4311 | $10,725.00 | $0.30 | 8.86% | 85 | $2.49 (-$3.58 to $8.71) |
| trend | Lower | 35026 | 4312 | -$2,460.00 | -$0.07 | 4.67% | 19 | -$0.57 (-$7.02 to $5.69) |

## Limits

These descriptive findings do not establish future returns, a trading switch, or live readiness. The previous campaign already inspected 2022–2024; this evaluation does not erase earlier failures. Unadjusted continuous futures include roll gaps. No margin liquidation is simulated. Event fills use existing one-minute bracket assumptions; event execution-delay sensitivity remains untested. The new snapshot adds evaluation support and event-entry bar metadata without changing strategy rules.

Completed 2026-09-15T03:23:41.144Z: nine evaluations, 32 child runs, and 18 regime investigations. Every prior run and unsuccessful result remains in the app. Exact IDs, thresholds, scenarios, inputs and warnings are in campaign.json and per-strategy JSON files.
