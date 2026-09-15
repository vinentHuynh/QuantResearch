# Strategy optimization results

## Scope

All nine enabled strategies; 33 development candidates (including the passive benchmark), selected using 2022 only. Settings frozen before 2023 validation and 2024 holdout/cost/ES checks. No automatic walk-forward engine was used for Pine event ports.

One contract. Pine daily and drift use fixed-contract mode; ORB maximum one contract with a $2500 stop-risk cap. No position-size optimization.

Each run starts with $100,000. Base costs are $1.25 per contract per side plus one tick of slippage per side; stress uses $2.50 and two ticks. No margin liquidation is simulated: negative-equity paths are unusable and fail training eligibility.

Chronological historical checks, not certified untouched out-of-sample evidence: earlier repository research may have inspected these periods.

## Results

| Strategy | 2022 P&L | 2023 P&L | 2024 P&L | 2024 drawdown | Higher-cost 2024 P&L | ES 2024 P&L | Outcome |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| buy-hold | -$106,297.50 | $117,612.50 | $84,292.50 | -37.9% | $84,280.00 | $55,985.00 | Did not pass declared checks |
| moving-average | $11,570.00 | $66,420.00 | $51,950.00 | -33.6% | $50,175.00 | $32,820.00 | Did not pass declared checks |
| multi-speed-momentum | $134,577.50 | $60,395.00 | -$6,467.50 | -62.3% | -$10,455.00 | $11,252.50 | Did not pass declared checks |
| rsi2-reversion | -$63,680.00 | $41,682.50 | $34,755.00 | -24.6% | $34,480.00 | $44,495.00 | Did not pass declared checks |
| vwap-reversion | -$1,205.00 | $11,227.50 | $5,302.50 | -59.3% | $1,740.00 | -$7,880.00 | Did not pass declared checks |
| pine-overnight-block | $30,220.00 | -$3,295.00 | $2,282.50 | -18.2% | -$955.00 | -$1,685.00 | Did not pass declared checks |
| pine-daily-tsmom | -$6,540.00 | $83,212.50 | $34,522.50 | -39.7% | $34,410.00 | $40,675.00 | Did not pass declared checks |
| pine-overnight-drift | $1,102.50 | $22,660.00 | $16,347.50 | -38.9% | $15,085.00 | $12,652.50 | Did not pass declared checks |
| pine-tsmom-orb | $27,010.00 | $19,557.50 | $25,432.50 | -11.2% | $23,715.00 | $3,020.00 | Passed declared historical checks |

## Acceptance checks

1 of nine selected configurations passed every declared historical check. ES transfer is reported separately and did not influence selection.

| Strategy | Failed criteria |
| --- | --- |
| buy-hold | 2022 training eligibility; 2024 drawdown within 35% |
| moving-average | 2022 training eligibility |
| multi-speed-momentum | Positive 2024 net P&L; 2024 drawdown within 35%; Positive higher-cost 2024 P&L |
| rsi2-reversion | 2022 training eligibility |
| vwap-reversion | 2022 training eligibility; 2024 drawdown within 35% |
| pine-overnight-block | Positive 2023 net P&L; Positive higher-cost 2024 P&L |
| pine-daily-tsmom | 2022 training eligibility; 2024 drawdown within 35% |
| pine-overnight-drift | 2024 drawdown within 35% |
| pine-tsmom-orb | None |

See PLAN.json for the predeclared grids, minimum trade counts and selection rule. A profitable later period does not override failed training eligibility.

## Selected parameters

### buy-hold

```json
{
  "contracts": 1
}
```

Training eligibility: false. Holdout run: a6562315-7e23-465b-8b88-7167ab202ee5.

### moving-average

```json
{
  "lookback": 80,
  "contracts": 1
}
```

Training eligibility: false. Holdout run: 2db718c5-35b0-425c-9680-4b92afa93b1e.

### multi-speed-momentum

```json
{
  "lookback": 60,
  "contracts": 1
}
```

Training eligibility: true. Holdout run: 1a85df0c-bbb4-4775-84c9-5705e4e91691.

### rsi2-reversion

```json
{
  "trend_lookback": 100,
  "entry_rsi": 10,
  "exit_rsi": 70,
  "contracts": 1
}
```

Training eligibility: false. Holdout run: 51248938-359a-4829-8cf0-fb8860d1d3a8.

### vwap-reversion

```json
{
  "band": 0.004,
  "contracts": 1
}
```

Training eligibility: false. Holdout run: edd96783-b520-4aa8-bfef-8f210269afba.

### pine-overnight-block

```json
{
  "entry_hour": 23,
  "entry_minute": 0,
  "exit_hour": 6,
  "exit_minute": 0,
  "contracts": 1,
  "timezone": "America/New_York"
}
```

Training eligibility: true. Holdout run: 175b4eb0-942d-4f19-b23d-1c9c2a5b7b69.

### pine-daily-tsmom

```json
{
  "fast_length": 10,
  "medium_length": 60,
  "slow_length": 90,
  "annual_length": 252,
  "sizing_mode": "Fixed contracts",
  "contracts": 1,
  "annual_risk": 0.2,
  "maximum_leverage": 2,
  "volatility_length": 60,
  "sleeve_count": 1,
  "rounding": "Nearest"
}
```

Training eligibility: false. Holdout run: b92c3dc6-ca6c-4c67-aae0-38290f91a8d9.

### pine-overnight-drift

```json
{
  "sizing_mode": "Fixed contracts",
  "contracts": 1,
  "annual_risk": 0.2,
  "maximum_leverage": 2,
  "volatility_length": 60,
  "sleeve_count": 4,
  "timezone": "America/New_York",
  "rth_start": 570,
  "rth_end": 960,
  "trade_weekend": false,
  "close_rule": "Long after down close",
  "strong_threshold": 0.6
}
```

Training eligibility: true. Holdout run: 5c2c2a12-fe29-48f0-97e1-9600f0036feb.

### pine-tsmom-orb

```json
{
  "fast_length": 20,
  "medium_length": 60,
  "slow_length": 120,
  "annual_length": 252,
  "timezone": "America/New_York",
  "minimum_score": 0.5,
  "opening_start": 570,
  "opening_end": 585,
  "entry_start": 585,
  "entry_end": 900,
  "flatten_start": 945,
  "flatten_end": 960,
  "risk_budget": 2500,
  "maximum_contracts": 1,
  "reward_risk": 2,
  "require_close_break": true
}
```

Training eligibility: true. Holdout run: 269c1391-43fa-46da-a29d-b02bc722544e.

## Interpretation

These are the best measured candidates within a small declared grid, not global optima or live-trading approval. Preserve losing trials. Results use unadjusted continuous futures; roll gaps, missing-session classification, execution assumptions and prior research exposure limit inference. ES transfer has different contract economics and is not a risk-normalized comparison.

Completed 2026-09-15T02:51:21.483Z. All 69 completed campaign runs and nine presets remain in the app, plus 2 interrupted attempts retained for audit. See campaign.json and FROZEN_SELECTIONS.json for exact IDs and inputs.
