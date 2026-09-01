# Risk Target, Leverage, Stops, and Behaviour

## 1. Choosing the risk target τ

τ is the annualised standard deviation of returns you are aiming for. Take the
**minimum** of three constraints:

```
τ = min( SR_expected / 2 ,          # half Kelly
         prudent_leverage_cap ,     # gap / margin survival
         personal_tolerance )       # what you can hold through
```

**Half Kelly.** Full Kelly for a continuously-rebalanced system is
`τ_full = SR`. Full Kelly is unhedged against estimation error and produces
drawdowns most people cannot survive; a wrong SR estimate above full Kelly loses
money with certainty. Use **half Kelly or less**. If you expect SR 0.5, τ ≤ 25%.

Practical anchors:

| System | Expected SR | τ |
|--------|-------------|---|
| Starter System, 1 instrument | ~0.24 | 12% |
| Few instruments, few rules | ~0.4 | ~15–20% |
| Well-diversified futures book | ~0.6–1.0 | 20–25% (hard cap 25%) |

Cap τ at 25% regardless of what Kelly says. Anyone whose estimate justifies more
has overestimated their Sharpe.

**Adjust downward for negative skew.** Trend following is positively skewed
(many small losses, rare large gains) and can carry full τ. Short-vol, carry,
mean-reversion, and anything with a bounded gain and unbounded loss are negative
skew — halve τ, and never assume the historical worst case is the worst case.

## 2. Leverage and prudent limits

```
leverage = τ / σ_ann
```

Low-vol instruments demand high leverage for the same risk. A 12% target on a
5%-vol bond future is 2.4× notional; on a 60%-vol crypto it is 0.2×.

Constraints:

- **Gap risk.** Ask: what is the worst overnight move this instrument has ever
  made, and what does it do to the account at this leverage? If a plausible bad
  gap costs more than ~1/3 of capital, cut the risk target.
- **Margin.** Keep margin usage well under 50% of capital. Margin requirements
  rise in volatile markets — exactly when you least want a forced liquidation.
- **Vol is not the whole risk.** Fat tails mean the 1-day 5σ move happens far more
  often than a normal distribution says. Size for the tail, not the variance.

## 3. Stop losses

Only for binary systems where the position cannot shrink.

```
stop_gap = stop_fraction × price × σ_ann        # stop_fraction = 0.5 default
```

Trailing: for a long, the stop ratchets up with the highest price since entry and
never moves down. Exit on close through the stop.

- The stop fraction sets the **holding period**. 0.5 with MAC(16,64) gives roughly
  a month. Tighter stops = more trades = more cost, not more safety.
- Vol-scaled, so the stop is in the same risk units as the position size.
- With continuous forecasts, remove the stop entirely (rules.md §5).
- Never widen a stop after entry. Never average down.

## 4. Drawdown expectations

Set these before starting, so the drawdown you get isn't evidence of anything.

- Annual return standard deviation = τ. A losing year is normal.
- Expect a peak-to-trough drawdown of **at least 2×τ**, and plan for 3×τ.
  At τ=12%, that means a 24–36% drawdown is an ordinary event, not a failure.
- Drawdowns last longer than they feel like they should — years, not months, for
  a Sharpe below 0.5.
- Drawdown does not by itself mean the system is broken. Nor does profit mean it
  works.

## 5. You cannot evaluate your own track record

Standard error of an estimated Sharpe over N years:

```
SE(SR) ≈ √((1 + SR²/2) / N)
```

Distinguishing SR 0.24 from zero at 95% confidence needs on the order of
**70 years** of data. For SR 0.5, ~30 years. You will not accumulate that.

Consequences:

- Do not change the system because of a year of results, good or bad.
- Do measure the things that *are* estimable in months, not decades: realised
  volatility vs τ, realised costs vs modelled costs, execution slippage, and
  whether the system was actually followed.
- Only stop for a structural reason (the edge is arbitraged, the instrument
  changed, costs rose), not a P&L reason.

## 6. Behaviour rules

- Write the rules down before trading. Follow them.
- Permitted override: **reduce** risk. Never increase it, never override an exit.
- No discretionary entries in a systematic account; if you want discretion, run
  the semi-automatic model — your entry, the system's sizing, stop, and limits.
- Keep a diary of every deviation. Deviations are the main failure mode, not the
  model.
- Never add capital during a drawdown to "make it back".
- Check positions on a fixed schedule. Watching intraday makes overriding likely
  and improves nothing.

## 7. The semi-automatic trader

For discretionary traders who want the risk framework without the signals:

- You choose direction and instrument.
- The system chooses **size** (vol-scaled to τ), the **stop** (0.5 × σ_ann), and
  enforces the **instrument limits, leverage cap, and cost budget**.
- Same expectation math applies: unless your entries are better than a coin flip
  by a measurable margin, the framework is what's producing the returns.
