# Costs and the Speed Limit

Compute costs **first**. A strategy that fails here cannot be rescued by a
better signal, and backtesting it is wasted time.

## 1. Cost components

Per trade (one side, one contract):

```
cost_ccy = commission
         + (bid_ask_spread_in_points / 2) × multiplier      # half-spread
         + slippage_points × multiplier                     # market impact
```

Use the spread you actually get at your size and time of day, not the tightest
quote in the book. For spread bets the spread *is* the whole cost.

Holding costs, charged per year regardless of trading:

- Futures: roll cost = round-trip cost × rolls per year (4 for quarterly).
- CFDs / spread bets: financing spread over the reference rate.
- Borrow fees on shorts.

## 2. Risk-adjusted cost

Currency costs are not comparable across instruments. Divide by the risk being
bought, which converts cost into **Sharpe ratio units**:

```
cost_SR_per_trade = cost_ccy / (price × multiplier × fx × σ_ann)
```

Denominator = annualised currency volatility of one contract. A cost of 0.01 SR
units means that trade consumes 1% of a Sharpe point per year, per unit of risk.

```
annual_cost_SR = cost_SR_per_trade × trades_per_year + holding_cost_SR
```

Count a round trip as 2 trades. A rule that opens and closes monthly does ~24
trades/year.

## 3. The speed limit

```
speed_limit = expected_pre_cost_SR / 3
```

Never spend more than a third of your expected gross Sharpe on costs.

- Single-instrument trend system: pre-cost SR ≈ 0.30 ⇒ **limit ≈ 0.10 SR/yr**
  (the Starter System's ~0.24 after-cost SR is what remains).
- Diversified multi-instrument, multi-rule system: pre-cost SR ≈ 0.5–1.0 ⇒
  limit ≈ 0.17–0.33 SR/yr.

Apply the limit **per trading rule**, not just to the portfolio. A fast rule that
breaches it gets dropped for that instrument, even if slower rules on the same
instrument are fine. Cheap instruments can run faster rules than expensive ones.

## 4. Instrument screen

Reject an instrument if any of these fail:

1. `annual_cost_SR` at your intended turnover exceeds the speed limit.
2. `min_capital` (diversification.md) exceeds your capital.
3. Liquidity too thin — your order is a meaningful share of typical volume.
4. Data is unreliable, or the continuous series is stitched in a way that
   fabricates P&L at the roll seam.

Prefer: high liquidity, low spread relative to vol, small contract size, a micro
version available, and a clean roll convention.

## 5. Why intraday almost always fails

Turnover scales cost linearly, but edge does not scale with frequency. A rule
trading 500 times a year at 0.001 SR/trade spends 0.50 SR units — more than the
entire realistic gross Sharpe of most trend or reversion signals. This is the
single most common reason a promising backtest dies, and the reason gross-of-cost
results should never be quoted as a result.

Before writing a backtest, do this arithmetic on the back of an envelope. If the
cost budget is already blown, stop.

## 6. Reporting costs honestly

- Always state results **net** of modelled costs; label gross figures as gross.
- Model the spread you cross, not the mid.
- Include roll costs and financing, not just commissions.
- Assume next-bar execution; a signal computed on a close cannot trade that close.

## 7. Worked example (MES, micro E-mini S&P)

```
price 5000, multiplier 5, ann_vol 16%, all-in cost per side $1.50
contract value      = 5000 x 5          = $25,000
annual vol per lot  = 25,000 x 0.16     = $4,000
cost_SR_per_trade   = 1.50 / 4,000      = 0.000375

monthly trend rule  (24 trades/yr)      = 0.009 SR   -> fine
weekly rule        (104 trades/yr)      = 0.039 SR   -> fine
daily-ish rule     (500 trades/yr)      = 0.188 SR   -> BREACH (limit 0.10)
```

The full-size ES contract has ten times the risk per lot for roughly four times
the cost, so it is far cheaper in SR units — but it needs ten times the capital
to size correctly. That trade-off, not commission alone, is the real cost of
trading a small account.

Run `scripts/carver.py` for the same arithmetic on your own instruments.
