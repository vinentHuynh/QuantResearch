# Each strategy's historical potential

Completed nine evaluations (32 child runs) and eighteen regime studies. Parameters
were fixed at the selections from the earlier campaign. Each strategy used 2024
for calibration and 2025 for testing, with $100,000 starting capital and one NQ
contract. All calculations include commissions and slippage.

Three strategies met the 2025 baseline and doubled-cost criteria. **Pine TSMOM
ORB is the only configuration that also passed every criterion in the previous
2022–2024 campaign.** This is a historical research distinction, not a forecast
or trading recommendation.

| Strategy | 2025 net P&L | Maximum drawdown | What the evidence suggests |
| --- | ---: | ---: | --- |
| Pine TSMOM ORB | $8,265.00 | 10.10% | Most consistent across these declared checks. $7,020 remains after doubling costs; 104 trades. Event-order delay remains untested. |
| Pine overnight block | $18,292.50 | 23.54% | Passes 2025 checks; earlier 2023 losses and 2024 cost sensitivity remain unresolved. |
| Pine overnight drift | $13,212.50 | 27.51% | Passes 2025 checks; the earlier 2024 drawdown exceeded the 35% cap. |
| Moving-average trend | $88,640.00 | 38.31% | Large profit with drawdown above the cap. One additional bar of delay reduces profit to $39,135. |
| Multi-speed momentum | $18,870.00 | 36.65% | Slightly above the drawdown cap; delayed execution turns profit into a $3,790 loss. |
| RSI2 reversion | $59,687.50 | 49.59% | Profitable but deep drawdown and only 17 trades. Delayed profit falls to $14,902.50. |
| Pine daily TSMOM | $66,117.50 | 51.14% | Profitable with excessive drawdown and only nine trades; limited evidence about repeatability. |
| Session VWAP reversion | -$69,730.00 | 86.65% | Poor evidence for the tested settings. Higher costs and delay worsen the loss. |
| Buy and hold | $83,302.50 | 95.51% | Useful passive benchmark, with an unacceptable drawdown under the declared criteria despite positive year-end P&L. |

## What the regime studies showed

These are contributions to the original strategy's P&L, **not profits from a
new strategy that trades only in the named state**. Higher and Lower are relative
to the 2024 median of each 20-bar feature. They do not mean bull/bear markets;
the feature horizons vary with each strategy's timeframe.

| Strategy | Notable 2025 attribution |
| --- | --- |
| Pine TSMOM ORB | Higher-trend state +$10,725; lower-trend state -$2,460. Both volatility states contributed positive P&L. |
| Pine overnight block | Higher-trend state +$27,343.75; lower-trend state -$9,051.25. |
| Pine overnight drift | Higher-volatility state +$24,267.50; lower-volatility state -$11,055. |
| Moving-average trend | Lower-trend state contributed $72,510 of the $88,640 total. |
| Multi-speed momentum | Lower-trend state +$80,051.25; higher-trend state -$61,181.25. The combined result is much weaker. |
| RSI2 reversion | Lower-volatility state contributed $54,248.75 of the $59,687.50 total. |
| Pine daily TSMOM | Higher-trend state contributed $56,898.75 of the $66,117.50 total. |
| Session VWAP reversion | Lost money in both volatility states and both trend states. |
| Buy and hold | Higher-trend state contributed $65,390 of the $83,302.50 total. |

State exposure and sample sizes differ. The trend episode confidence intervals
for ORB, overnight block, and overnight drift all include zero. Those regime
patterns are hypotheses for separate testing, not established filters or
allocation rules. No margin liquidation is modeled; continuous futures roll
gaps and previously inspected history remain limitations.

## Evidence and app access

Open **Evaluation & Regimes** and choose an evaluation named
`potential-2025-v1 | <strategy>`. Each includes its scenarios, selection chronology,
equity chart, two regime tables, thresholds, uncertainty, and downloads.

- [Full numerical results and per-state statistics](RESULTS.md)
- [Spreadsheet summary](summary.csv)
- [Exact campaign IDs and inputs](campaign.json)
- [Browser and accounting validation](browser-validation.json)

All nine 2024 calibration runs exactly reproduce the previous 2024 runs' P&L,
drawdown, costs, and trade counts. Regime P&L and entry counts reconcile to each
parent evaluation. Build, lint, eight research tests, twelve Pine tests, research
API integration, and the final nine-strategy browser audit passed.
