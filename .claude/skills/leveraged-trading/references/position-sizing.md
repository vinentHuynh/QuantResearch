# Position Sizing

The most important leg. Everything here is mechanical — no judgement.

## 1. Estimate volatility

Carver's default: **standard deviation of the last 25 business days of daily
percentage returns, annualised by ×16** (√256 business days).

```
r_t   = price_t / price_{t-1} - 1
σ_day = stdev(r_{t-24..t})
σ_ann = σ_day × 16
```

Refinements (use when you have the data):

- **EWMA instead of flat window.** 32-day span EWMA ≈ 25-day flat window.
- **Blended estimate.** `σ = 0.7 × σ_recent + 0.3 × σ_10yr_average`. Pure recent
  vol under-sizes after a calm stretch and over-reacts to a single spike.
- **Price-difference vol.** For instruments that can go through zero or trade
  negative (spreads, some rates, 2020 crude), use differences not returns.
- Never use implied vol, and never use a vol number from a regime unlike now.

Vol is the only forecast in the system that is genuinely predictable — vol
clusters, returns don't. Spend effort here, not on entry signals.

## 2. Size the position

### Single instrument, binary (Starter System)

```
notional_exposure = (Capital × τ) / σ_ann
contracts         = notional_exposure / (price × multiplier × fx)
```

- `τ` = annualised risk target as a decimal (0.12 for the Starter System)
- `multiplier` = contract point value (ES 50, MES 5, MNQ 2, GC 100, CL 1000)
- `fx` = rate converting instrument currency to account currency (1.0 if same)
- For spread bets, `contracts` becomes stake per point; `multiplier = 1`.

Round to the nearest whole contract. If the answer rounds to 0, **do not trade** —
the instrument is too big for the account (see minimum capital).

Starter System holds this size for the life of the trade. Re-sizing daily on a
single binary position adds cost without adding much risk control.

### Full portfolio, continuous forecasts

```
contracts_i = (Capital × IDM × w_i × τ × (forecast_i / 10))
              / (σ_ann,i × price_i × multiplier_i × fx_i)
```

- `w_i` = instrument weight, Σw = 1 (see diversification.md)
- `IDM` = instrument diversification multiplier (see diversification.md)
- `forecast_i` = combined, scaled, capped forecast; average |forecast| = 10,
  cap ±20 (see rules.md). Forecast 10 ⇒ average-sized position.

The term `(Capital × IDM × w_i × τ) / (σ_ann,i × price_i × mult_i × fx_i)` is the
**average position** for that instrument. Cache it; the forecast just scales it.

## 3. Buffering (avoid churn)

Recomputing daily produces constant small trades that pay costs for nothing.

```
buffer      = 0.10 × average_position          # 10% of average, not of optimal
lower, upper = optimal - buffer, optimal + buffer
if current < lower:  trade up to lower
if current > upper:  trade down to upper
else:                do nothing
```

Buffering cuts turnover roughly in half with negligible tracking error. It is
the cheapest cost reduction available — apply it before dropping a trading rule.

## 4. Rounding and quantisation

Rounding to whole contracts injects risk error of up to ±0.5 contracts. That
error is ±50% when the average position is 1 contract, ±12.5% at 4 contracts.
Hence the 4-contract minimum capital rule (diversification.md).

If a market is too large, look for the micro/mini version (MES/MNQ/MGC) before
abandoning it — same exposure, one-tenth the quantisation error.

## 5. Capital, and what to do with profits

`Capital` in the formulas is **trading capital**: money you can lose entirely
without changing your life. Not net worth, not including a house.

Three policies:

| Policy | Rule | Effect |
|--------|------|--------|
| Fixed | Capital constant; withdraw/add nothing | Risk drifts as account moves |
| Full compounding | Capital = start + all P&L | Fastest growth, deepest drawdowns |
| Half compounding | Capital = start + 0.5 × cumulative profit; full effect on losses | Carver's compromise |

Losses always reduce position size immediately. Profits raise it slowly, or only
from a new high-water mark. Never add capital to recover a drawdown — that is
increasing risk exactly when the evidence says reduce.

## 6. Sanity checks

- `leverage = τ / σ_ann`. Bonds and FX produce large leverage from small vol —
  check margin usage and gap risk (risk-management.md).
- Sum of notional exposures ÷ capital = gross leverage. Keep margin usage well
  under 50% of capital so a vol spike can't force liquidation.
- Realised portfolio vol should track τ within roughly ±25% over a year. If it
  doesn't, the vol estimator or the correlation assumption in the IDM is wrong.
