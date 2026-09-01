---
name: leveraged-trading
description: Design, size, and vet leveraged trading systems using Robert Carver's "Leveraged Trading" framework — risk targeting, volatility-scaled position sizing, the cost speed limit, trend/carry rules, forecast scaling, diversification multipliers, minimum capital, stop losses, and drawdown expectations. Use when building or reviewing a futures/spread-bet/CFD/FX strategy, choosing position size or leverage, judging whether a strategy survives costs, setting a risk target, adding instruments or rules, or when the user mentions Carver, Starter System, risk target, vol targeting, IDM/FDM, forecast scalar, or speed limit.
---

# Leveraged Trading — Carver Framework

Doctrine for leveraged systematic trading (futures, spread bets, CFDs, margin FX).
Source: Robert Carver, *Leveraged Trading* (2019), with formulas consistent with
*Systematic Trading* and *Advanced Futures Trading Strategies*.

## Prime directives

1. **Position sizing dominates.** Entry signals are the least important leg. A
   mediocre rule sized correctly beats a good rule sized badly.
2. **Target risk, not money.** Every position is scaled so the portfolio's
   expected annualised standard deviation equals a chosen risk target. Never
   size in fixed contracts, fixed dollars, or "conviction".
3. **Costs kill first.** Compute risk-adjusted cost *before* backtesting. If a
   strategy breaches the speed limit, it is dead regardless of gross returns.
4. **Diversify before you optimise.** More instruments is the single largest
   real improvement available. Better parameters is mostly noise.
5. **Don't fit.** Use published default parameters. Backtest to sanity-check
   costs and implementation, not to select parameters.
6. **You will never prove your system works.** Sharpe estimation error is huge.
   Set rules, then leave them alone.

## Three legs

| Leg | Question | Importance |
|-----|----------|------------|
| Instruments | What do I trade? | High (diversification) |
| Trading rules | When do I open/close? | Low |
| Position sizing / risk | How big? | Highest |

## Workflow

Work in this order. Do not skip to step 4.

1. **Capital & risk target** → `references/risk-management.md`
   Trading capital (money you can lose). Risk target τ = min(half-Kelly,
   prudent-leverage cap, personal tolerance). Starter System: **τ = 12%/yr**.
2. **Instrument screen** → `references/costs.md`, `references/diversification.md`
   Cheapest + most liquid instrument you can afford. Check **minimum capital**
   and the **speed limit** before anything else. Reject failures immediately.
3. **Trading rules** → `references/rules.md`
   Default: MAC(16,64) trend. Add carry, then more MAC/breakout speeds — only
   those whose turnover clears the speed limit.
4. **Position sizing** → `references/position-sizing.md`
   Volatility-scaled, forecast-scaled, IDM-scaled, buffered, rounded.
5. **Exits & limits** → `references/risk-management.md`
   Trailing stop (binary systems only), leverage cap, drawdown expectation,
   compounding policy.
6. **Monitor, don't tinker** → `references/risk-management.md`
   Track realised vol vs target and realised costs vs estimate. Those are
   measurable. Sharpe is not.

## Core formula card

```
σ_ann        = stdev(daily % returns, last 25 business days) × 16
notional     = (Capital × τ) / σ_ann                          # single instrument
contracts    = notional / (price × multiplier × fx)

# full portfolio form
contracts_i  = (Capital × IDM × w_i × τ × (forecast_i / 10))
               / (σ_ann,i × price_i × multiplier_i × fx_i)

leverage     = τ / σ_ann
min_capital  = (4 × price × multiplier × fx × σ_ann) / τ       # 4-contract rule
cost_SR      = cost_per_trade_ccy / (price × multiplier × σ_ann)
annual_cost  = cost_SR × trades_per_year   (+ holding costs)
speed_limit  = expected_pre_cost_SR / 3    (≈0.10 SR units/yr single-instrument)
stop_gap     = 0.5 × price × σ_ann                             # binary systems
```

Reference implementation: `scripts/carver.py` (run `--self-test` to verify).

## Starter System (the baseline to beat)

Single instrument, fully systematic, binary position.

- **Risk target:** 12% annualised
- **Vol estimate:** 25-business-day stdev of daily returns × 16
- **Open:** MAC(16,64) — long if MA16 > MA64, short if below
- **Close:** trailing stop, gap = 0.5 × annualised price vol
- **Size:** computed at open, **held constant** for the trade's life
- **Expectation:** SR ≈ 0.24 after costs, ~1 trade/month, max drawdown ≥ 2×τ

Improvements, in descending order of value: more instruments → more rules →
continuous forecasts → drop the stop loss → (last, and only if costs allow)
faster rules.

## Red flags

Say so plainly when a proposal hits one of these:

- Sizing in fixed contracts/dollars, or scaling by "conviction" or recent P&L.
- Risk target chosen for a return goal instead of from Kelly + leverage limits.
- Turnover implying costs above the speed limit — most intraday systems.
- Parameters selected by backtest search; in-sample Sharpe quoted as expectation.
- Negative-skew payoff (short vol, mean reversion, martingale) at full risk target.
- Adding money after a loss, or raising risk to recover a drawdown.
- Vol estimate from a period unlike the present, or no vol estimate at all.
- A single instrument treated as if diversified (IDM > 1 with one market).
- Backtest Sharpe > ~1.5 on a liquid market — assume a bug or lookahead first.

## Provenance

Numbers reproduce Carver's published defaults. Where a figure matters to real
money, verify against the book edition in hand before trading. The formulas are
the durable part; the constants are conventions.

## References

- `references/position-sizing.md` — vol estimation, sizing math, buffering, rounding
- `references/costs.md` — cost model, risk-adjusted costs, speed limit, instrument screen
- `references/rules.md` — trend, carry, forecast scaling/capping, combining rules
- `references/diversification.md` — IDM, FDM, instrument weights, handcrafting, min capital
- `references/risk-management.md` — risk target, Kelly, leverage caps, stops, drawdowns, psychology
- `scripts/carver.py` — executable implementation of every formula above
