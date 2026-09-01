# Diversification, Weights, and Minimum Capital

Adding instruments is the largest genuine improvement available to a retail
system. It is also the one gated by capital.

## 1. Minimum capital

A position must round to a whole contract. Rounding error is ±0.5 contracts, so
the average position has to be large enough for that to be tolerable.

```
capital_for_N_contracts = (N × price × multiplier × fx × σ_ann) / τ
```

- `N = 1` → absolute floor; risk error up to ±50%. Only acceptable as a start.
- `N = 4` → **recommended minimum**; risk error ≤ ±12.5%.

In a portfolio, apply this per instrument using that instrument's share:

```
min_capital_i = (4 × price_i × mult_i × fx_i × σ_ann,i) / (τ × IDM × w_i)
```

Portfolio minimum capital is the largest `min_capital_i`. If one instrument
forces the number up, replace it with a micro contract or drop it — do not raise
the risk target to make it fit.

Trade-offs when capital is short, in order of preference: use micro contracts →
drop the most expensive instrument → accept N=2 rounding → **not** raise τ.

## 2. Instrument diversification multiplier (IDM)

Sizing each instrument to τ individually gives a portfolio well below τ, because
they aren't perfectly correlated. IDM scales the whole book back up.

```
IDM = 1 / √(w' C w)          # w = instrument weights, C = return correlations
IDM = min(IDM, 2.5)
```

Rules:

- Cap at **2.5**. Estimated correlations are unstable and underestimate crisis
  correlation; the cap is a safety margin, not a limitation.
- Use long-window correlations of *returns*, not of forecasts.
- **IDM = 1.0 for a single instrument.** Applying an IDM > 1 to one market is
  simply trading above your risk target.
- Correlations rise in a crisis. The IDM you estimated in calm markets will
  overstate diversification exactly when it matters.

Rule-of-thumb values for a reasonably diversified set:

| Instruments | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 15 | 25+ |
|-------------|---|---|---|---|---|---|---|---|----|-----|
| IDM | 1.00 | 1.20 | 1.48 | 1.56 | 1.70 | 1.90 | 2.10 | 2.20 | 2.30 | 2.50 |

These assume genuinely different markets. Five equity index futures are one
instrument wearing five hats — count effective bets, not tickers.

## 3. Instrument weights

Default: **equal weight**, adjusted by handcrafting for obvious similarity.

**Handcrafting** — group instruments into a tree by similarity, equal-weight
within each group, then equal-weight the groups:

```
Portfolio
├── Equities        (33%)  ES, NKD, FESX      → 11.1% each
├── Bonds / Rates   (33%)  ZN, ZB, BTP        → 11.1% each
└── Commodities     (33%)  GC, CL, ZC         → 11.1% each
```

Do not use mean-variance optimisation on estimated returns. It concentrates into
whatever asset happened to do best in-sample. If you must optimise, bootstrap and
shrink heavily toward equal weights.

Rebalance weights rarely — annually, or when the instrument set changes.

## 4. Forecast diversification multiplier (FDM)

Same idea, one level down: combining imperfectly correlated forecasts shrinks the
average absolute forecast below 10, so scale it back up.

```
FDM = 1 / √(w' C w)        # w = rule weights, C = forecast correlations
FDM = min(FDM, 2.5)
```

Trend speeds are highly correlated (FDM ≈ 1.1–1.4 across a trend family). Adding
carry to trend gives a much bigger lift than adding a sixth trend speed.

## 5. Diminishing returns

Sharpe improves quickly to ~5–10 instruments, then slowly. Beyond ~15–20 you are
mostly adding cost, operational load, and correlation you didn't measure. Pick
instruments that are cheap, liquid, affordable, and genuinely different — in that
order.
