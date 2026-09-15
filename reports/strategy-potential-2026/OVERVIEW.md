# Strategy analysis: January–August 2026

## Main findings

- **ORB remains the strongest candidate across the declared historical checks:** $11,552.50 net profit, 11.81% maximum drawdown, 29 trades, 55.17% win rate, 1.46 profit factor and 1.18:1 realized dollar payoff. Doubled costs leave $11,220.00. This is a small sample, not a live-readiness conclusion.
- **Overnight block improved in this period:** $45,175.00, 13.86% drawdown and $43,025.00 under doubled costs. It remains conditional because earlier failures still count.
- **Overnight drift remains conditional:** $13,082.50 and 25.14% drawdown. Its earlier drawdown failure has not disappeared.
- **RSI2 passes the 2026 checks but has only 12 trades**, a 32.2% drawdown, and earlier training/evaluation weaknesses. It moves into the conditional category, not the strongest candidate category.
- **Moving-average and VWAP fail the 35% drawdown ceiling.** VWAP improves sharply from 2025 losses but reaches 35.6% drawdown. The benchmark also exceeds the ceiling.
- **Multi-speed momentum and daily TSMOM crossed below zero simulated equity.** Their drawdowns exceed 100%; the simulator continues without margin liquidation, so later recovery does not make those paths feasible at this capital level.

## All strategies

NQ futures; $100,000 starting capital per strategy, fixed one contract, existing fees and slippage. Each row is a separate run, not a combined portfolio. Drawdown is measured from marked-equity peaks including starting capital.

| Strategy | Net profit | Max drawdown | Trades | Win rate | Profit factor | Realized payoff | Doubled-cost profit | Added-delay profit | Dashboard status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| buy-hold | $80,287.50 | 56.04% | 1 | 100.00% | Undefined | Undefined | $80,275.00 | $80,287.50 | Benchmark |
| moving-average | $33,087.50 | 60.18% | 93 | 24.73% | 1.22 | 3.72 | $31,925.00 | $38,827.50 | Needs review |
| multi-speed-momentum | -$55,890.00 | 101.53% | 236 | 34.32% | 0.84 | 1.60 | -$58,840.00 | -$15,725.00 | Needs review |
| rsi2-reversion | $43,980.00 | 32.21% | 12 | 58.33% | 2.87 | 2.05 | $43,830.00 | $52,560.00 | Conditional |
| vwap-reversion | $47,772.50 | 35.59% | 209 | 67.94% | 1.16 | 0.55 | $45,160.00 | $23,897.50 | Needs review |
| pine-overnight-block | $45,175.00 | 13.86% | 172 | 56.40% | 1.30 | 1.01 | $43,025.00 | Unavailable | Conditional |
| pine-daily-tsmom | -$39,127.50 | 104.16% | 17 | 41.18% | 0.66 | 0.94 | -$39,340.00 | Unavailable | Needs review |
| pine-overnight-drift | $13,082.50 | 25.14% | 69 | 55.07% | 1.10 | 0.90 | $12,220.00 | Unavailable | Conditional |
| pine-tsmom-orb | $11,552.50 | 11.81% | 29 | 55.17% | 1.46 | 1.18 | $11,220.00 | Unavailable | Research candidate |

Pine event strategies have no added execution-delay simulation. A single winning benchmark trade has no defined average loss, payoff ratio, or profit factor.

## ORB exits: why a 2R target does not produce a 2:1 average payoff

| Period | Target exits | Scheduled exits | Stop exits | Other exits | Net profit | Realized payoff | Mean net R per trade |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2025 | 11 | 50 | 42 | 1 | $8,265.00 | 1.03:1 | 0.06 |
| 2026-Jan-Aug | 6 | 11 | 12 | 0 | $11,552.50 | 1.18:1 | 0.20 |
| 2026-Sep-partial | 0 | 0 | 1 | 0 | -$2,072.50 | Undefined:1 | -1.01 |

The 2R target is only one exit path. Most winning trades in 2025 closed at the scheduled time before reaching that target. Trades also have different initial dollar risks because opening ranges differ. Fees and slippage further reduce realized payoff.

2025: the five best trades contributed **$19,957.50**. Removing them arithmetically leaves **-$11,692.50**. This shows profit concentration; it is not a simulated filter or a prediction.
2026-Jan-Aug: the five best trades contributed **$18,622.50**. Removing them arithmetically leaves **-$7,070.00**. This shows profit concentration; it is not a simulated filter or a prediction.

**Exit scheduling issue:** five 2025 trades and two January–August 2026 trades crossed into a later local date. All seven entry dates have no source bars in the 15:45–16:00 flattening window, so that scheduled exit could not run. Six ultimately closed at a stop or target; one used the next-morning safety exit. Exit-reason labels alone therefore undercount overnight exposure. A fixed wall-clock exit needs explicit handling for sessions without that window. The historical rules were preserved for this comparison.

The June 19, 2026 trade carried over the weekend and exited at the June 21 reopening below its stop: initial risk $1,010, gross loss $2,105 (2.084R), net loss $2,117.50. A stop does not cap losses at 1R when prices gap. Across the twelve 2026 stop exits, mean gross loss was 1.09R.

ORB also weakened after April: May, June and August closed-trade P&L were negative, and February and July had no completed trades. The positive eight-month total should not be read as uniformly strong recent performance.

See [ORB_EXITS.md](ORB_EXITS.md), [exit contribution chart](orb-exit-contributions.png), and the full `orb-exits-*.csv` ledgers for exit P&L, normalized risk, holding times, monthly concentration, and long/short attribution.

## September 1–3: partial month only

| Strategy | Net profit | Trades |
| --- | ---: | ---: |
| buy-hold | $97.50 | 1 |
| moving-average | $2,590.00 | 2 |
| multi-speed-momentum | -$4,202.50 | 5 |
| rsi2-reversion | $7,302.50 | 1 |
| vwap-reversion | $2,507.50 | 3 |
| pine-overnight-block | -$8,777.50 | 3 |
| pine-daily-tsmom | $6,372.50 | 1 |
| pine-overnight-drift | $0.00 | 0 |
| pine-tsmom-orb | -$2,072.50 | 1 |

These are independent short-window baseline runs starting flat with warmed-up signals and forced final liquidation. They are not appended to August equity and do not change dashboard rankings. The small sample is insufficient to establish a new performance trend. Zero trades, including overnight drift, supplies no trading evidence.

## Regime attribution

Thresholds use 2025 data only: median trailing trend/volatility over 20 preceding bars in each strategy’s native timeframe. Higher and lower are relative to that threshold, not universally bull/bear. Contributions come from existing continuous paths with unequal exposure. No state-only entry or exit rule was tested.

### pine-tsmom-orb

| Feature | State | Net P&L contribution | Entries | Mean episode P&L 95% interval |
| --- | --- | ---: | ---: | --- |
| volatility | Higher | $16,525.00 | 25 | -$9.65 to $58.63 |
| volatility | Lower | -$4,972.50 | 4 | -$19.77 to $3.10 |
| trend | Higher | $12,137.50 | 18 | -$1.74 to $11.15 |
| trend | Lower | -$585.00 | 11 | -$5.53 to $5.27 |

### pine-overnight-block

| Feature | State | Net P&L contribution | Entries | Mean episode P&L 95% interval |
| --- | --- | ---: | ---: | --- |
| volatility | Higher | $35,590.00 | 79 | -$21.71 to $129.38 |
| volatility | Lower | $9,585.00 | 93 | -$39.55 to $66.12 |
| trend | Higher | $37,130.00 | 67 | -$1.66 to $29.09 |
| trend | Lower | $8,045.00 | 105 | -$13.56 to $18.43 |

### pine-overnight-drift

| Feature | State | Net P&L contribution | Entries | Mean episode P&L 95% interval |
| --- | --- | ---: | ---: | --- |
| volatility | Higher | -$15,347.50 | 62 | -$122.90 to $72.54 |
| volatility | Lower | $28,430.00 | 7 | -$5.20 to $93.96 |
| trend | Higher | -$23,987.50 | 30 | -$26.43 to $9.68 |
| trend | Lower | $37,070.00 | 39 | -$8.29 to $33.72 |

## Protocol and validation

- **training:** 2025-01-01 through 2025-12-31, 365 calendar days; exactly one frozen candidate, no parameter selection
- **test:** 2026-01-01 through 2026-08-31, 243 calendar days
- **september:** 2026-09-01 through 2026-09-03; separate baseline runs starting flat, descriptive only, not appended to the main evaluation
- **parameters:** Original frozen 2022 selections for all nine NQ strategies; no retuning
- **criteria:** Positive net P&L for shortlist consideration; evaluation rule return >=0, drawdown <=35%, original minimum trade counts retained conservatively despite shorter period
- **scenarios:** Baseline and doubled fees/slippage; one additional bar delay for signal strategies only
- **sizing:** $100000 capital; fixed one contract; fee $1.25 per side, slippage one tick; ORB risk budget $2500 and maximum one contract
- **regimes:** Trend and volatility, 20 preceding native-timeframe bars, threshold at 2025 median, seed 42. Attribution only, no regime filter.
- **exits:** ORB baseline trade-ledger attribution, opening-range initial risk, exit reasons, gross/net R multiples, holding duration, monthly concentration. No exit-rule optimization.
- **limitations:** Historical carry-forward research; not certified untouched. Unadjusted continuous roll gaps, no margin liquidation, one-minute bracket assumptions, no event delay stress. September is only a partial month.

Completed nine evaluations with 32 child runs, nine separate September runs and 18 regime studies. All 103 earlier runs remain available. Source snapshot: `9cb2ff01e5ac252c51294fbb809f2654c6febba3a3632e018f1b3bc4af5c380f`.

All nine 2025 training replays exactly matched the earlier 2025 baseline P&L, drawdown, trade counts and costs. All parameters remained frozen. Full artifact checksums, trade/equity reconciliation, doubled costs, threshold dates, dashboard values, evaluation charts, downloads and mobile layout were checked. See [browser-validation.json](browser-validation.json).

There were 0 preexisting 2026 runs in the active app ledger when this campaign began. This does not establish that 2026 had never been inspected elsewhere or in deleted/legacy research. Treat it as historical carry-forward evidence, not a certified untouched holdout.

2025 is a full year; the main 2026 period is eight months. Dollar totals are not directly comparable annual rates. This analysis does not resolve continuous-contract roll gaps, exchange-calendar completeness, real execution latency, margin requirements, or future returns.

## Next analysis

Prioritize ORB session-end handling and nearby-parameter/slippage sensitivity. Any exit-rule variants should be declared and developed on earlier data; 2026 is now inspected and must be treated as such. Then assess whether ORB, block and drift diversify each other using simultaneous marked-equity paths and overlapping positions.

Open the local app → **Dashboard** for the January–August results, or **Evaluation & Regimes** and select a `potential-2026-v1` evaluation. September runs remain in **Runs & Compare**. [CSV summary](summary.csv).
