# Trading Rules and Forecasts

Rules are the least important leg. Use published defaults; do not search for
parameters. The purpose of this file is to give you rules that are known to work
approximately, so you can stop thinking about entries and go do sizing properly.

## 1. Rules with real evidence

**Trend following (momentum).** Works across almost every liquid asset class,
documented since the 1900s, positive skew. The default family.

**Carry.** Long the high-yielding / backwardated instrument, short the opposite.
Works, but negative skew — pairs well with trend, which is positive skew.

Everything else — mean reversion, patterns, indicators, seasonality — is either
unproven, capacity-limited, negative skew, or too fast to survive costs. Treat
with suspicion and demand a much higher evidential bar.

## 2. Binary rules (Starter System)

```
MAC(16, 64): long if MA16 > MA64, short if MA16 < MA64
```

Position is full size long or full size short, sized at open and held. Exit via
trailing stop (risk-management.md), not via the crossover, so the stop defines
the holding period.

Alternative binary rule: N-day breakout — long on a new N-day high, short on a
new N-day low.

## 3. Continuous forecasts

A forecast is a signed number proportional to expected risk-adjusted return.
Convention: **average absolute value 10**, **capped at ±20**, 0 = flat.

### EWMAC (trend)

```
raw_i     = EWMA(price, fast) - EWMA(price, slow)
scaled_i  = raw_i / σ_price_daily          # σ in price units, not %
forecast  = scaled_i × forecast_scalar
forecast  = clip(forecast, -20, +20)
```

Carver's published forecast scalars:

| Rule | fast/slow | Scalar |
|------|-----------|--------|
| EWMAC2  | 2/8    | 12.1 |
| EWMAC4  | 4/16   | 8.53 |
| EWMAC8  | 8/32   | 5.95 |
| EWMAC16 | 16/64  | 4.10 |
| EWMAC32 | 32/128 | 2.79 |
| EWMAC64 | 64/256 | 1.91 |

Faster variants are more expensive. Only include a speed whose turnover clears
the speed limit for that instrument (costs.md).

### Carry

```
raw      = (price_near - price_far) / (years_between) / σ_price_annual
forecast = raw × ~30, capped ±20
```

Carry needs a second contract price. If your data source is front-month only,
you cannot compute carry — do not fake it with a proxy.

### Scalar estimation, if you must

Run the raw forecast over a long history and many instruments, take
`scalar = 10 / mean(|raw|)`. Estimate it pooled across instruments, never per
instrument (that is fitting).

## 4. Combining rules

```
combined = FDM × Σ (rule_weight_j × forecast_j)
combined = clip(combined, -20, +20)
```

- Rule weights: equal weight within a family unless you have strong reason
  otherwise. Slower and faster trend speeds are highly correlated; carry is not.
- FDM = forecast diversification multiplier = `1 / √(w' C w)` on the correlation
  matrix of the rules' forecasts. Cap at 2.5.
- Cap **after** applying the FDM, and cap each individual forecast first.

## 5. Stop losses vs continuous forecasts

- Binary system ⇒ you need a stop, because the position can't shrink.
- Continuous forecast ⇒ **drop the stop**. The forecast decaying toward zero is a
  smoother, cheaper exit, and a stop on top of it just adds cost and truncates
  the positive skew you were paid for.

## 6. What not to do

- Don't parameter-sweep and pick the peak. The peak is noise; expect it to halve
  out of sample at best.
- Don't add a rule because it improved the backtest by 0.1 Sharpe. Sampling error
  on Sharpe over 10 years is larger than that.
- Don't use a rule you can't explain economically in one sentence.
- Don't mix timeframes to "confirm" signals — that is an undeclared, unweighted
  forecast combination.
