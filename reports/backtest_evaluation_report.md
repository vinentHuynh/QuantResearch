# Consolidated Backtest Evaluation

**Prepared:** 2026-08-09  
**Workspace:** repository root  
**Market-data cutoffs:** daily panel through 2026-07-02/03; cached SPY/QQQ intraday data through 2026-06-08; MNQ 6-hour futures data through 2026-08-06.

## Executive conclusion

The workspace contains several well-implemented research ideas, but no strategy is ready for live deployment from this evidence alone. The best candidates for a second-stage, real-futures validation are:

1. **ES/NQ SMA200 long/flat trend** — the cleanest long-sample result and the only strategy with a clearly reported 2015 holdout. Full-period Sharpe is 0.74; post-2015 Sharpe is 0.87. It reduces drawdown versus buy-and-hold, although it also gives up return.
2. **Four-market multi-speed TSMOM** — credible as a diversifier. The attractive 2024-2026 Sharpe of 1.31 falls to 0.64 over 1990-2026, and long-only risk-weighting beats it on both Sharpe and CAGR. The implementation is careful, but the data are not executable futures series.
3. **Overnight index drift** — independently positive in long SPX/NDX proxy history and in a shorter real-MNQ sample. Net Sharpe is 0.59 on proxies since 2010 and 0.75 on MNQ since 2022 at the optimistic default cost. The edge is cost- and regime-sensitive.
4. **ES/NQ RSI(2) mean reversion** — long-sample gross Sharpe is 0.90 from 2013 and recent gross Sharpe is 1.53. A 1 bp-per-side reconstruction leaves the recent Sharpe near 1.50. This is promising, but it was selected in a multi-strategy bake-off and has no untouched holdout.

The **prior-week NQ gap-backfill fade** is a watchlist idea, not a lead candidate. The **factor composite is invalid pending data repair**. The commodity cross-sectional momentum, SPY/QQQ pairs, intraday ORB/PDH screens, TSMOM-filtered ORB, and most short-horizon strategies should be retired in their current form.

## Overall ranking

| Rank | Backtest family | Representative result | Evaluation | Decision |
|---:|---|---|---|---|
| 1 | ES/NQ SMA200 long/flat | 1990-2026: Sharpe 0.74, CAGR 9.7%, MaxDD 44.2%; post-2015 Sharpe 0.87, MaxDD 19.5% | Simple, lagged, long history, useful holdout; still uses cash-index proxies and omits explicit costs | Advance to actual-futures validation |
| 2 | Multi-speed CME TSMOM | 1990-2026: Sharpe 0.64, CAGR 6.1%, MaxDD 17.7%; 2024-2026 Sharpe 1.31 | Strong implementation and diversification; recent result is gold-driven and benchmarked long-only portfolio is better | Advance as diversifier |
| 3 | Overnight ES/NQ / MNQ | Proxy 2010-2026: Sharpe 0.59, CAGR 8.0%, MaxDD 32.8%; real MNQ 2022-2026: Sharpe 0.75, CAGR 11.1%, MaxDD 19.8% | Two datasets corroborate the direction, but the MNQ sample is short and costs are optimistic | Advance with conservative costs |
| 4 | RSI(2) ES/NQ | 2013-2026 gross: Sharpe 0.90, CAGR 9.5%, MaxDD 16.6%; 2024-2026 gross Sharpe 1.53 | Good result and low modeled turnover; no independent holdout and selected among several strategies | Freeze rules, then validate |
| 5 | Prior-week gap-backfill fade | 2015-2026 at 2 bps: Sharpe 0.49, CAGR 1.8%, MaxDD 5.0%; at 10 bps Sharpe 0.13 | Edge is almost entirely NQ and is cost-sensitive; no true futures fills | Watchlist only |
| 6 | Factor composite L/S | Reported net Sharpe 0.53; raw-return rerun Sharpe -0.02 | Result depends on ex-post forward-return clipping; dataset contains a duplicated factor column | Invalid pending data repair |
| 7+ | Remaining intraday, short-horizon, pairs, commodity, and evaluation screens | Mostly negative or untradeable after costs/fill corrections | No durable executable edge | Retire or redesign |

## Detailed evaluations

### 1. CME multi-speed time-series momentum

**Files:** `cme_time_series_momentum_backtest.py`, `cme_tsmom_single_market_strategy.pine`, and the saved MNQ/25K CSVs.

The Python implementation is one of the strongest in the workspace. It uses point changes rather than percentage returns, lags the complete target by one session, uses only lagged positions for P&L, handles negative oil prices, and charges costs on exposure changes.

| Window | Sharpe | CAGR | Volatility | MaxDD | Comment |
|---|---:|---:|---:|---:|---|
| 2024-01 to 2026-07, ES/NQ/GC/CL | 1.31 | 15.2% | 11.3% | 8.9% | Short, favorable sample; GC sleeve Sharpe 1.68 and drives much of the result |
| 2010-01 to 2026-07, same rules | 0.72 | 7.1% | 10.3% | 13.0% | More realistic expectation |
| 1990-01 to 2026-07, same rules | 0.64 | 6.1% | 9.9% | 17.7% | Credible long-run diversifier, not a high-Sharpe standalone engine |
| 1990-01 to 2026-07, ES/NQ only | 0.58 | 7.8% | 15.0% | 25.1% | Confirms the four-market benefit |
| Long-only risk-weighted benchmark, 1990-2026 | 0.80 | 10.1% | 13.1% | 27.8% | Higher Sharpe and return, but larger drawdown |

The saved whole-contract MNQ artifact is materially less attractive than the smooth proxy portfolio: 2020-2026 Sharpe 0.52, CAGR 7.9%, MaxDD 28.1%. The recent dynamically sized MNQ run ended near $20,241 from a roughly $25K start, with Sharpe -1.27 and MaxDD 27.8%. It was flat 127 of 191 sessions because a model-sized contract rounded to zero. Individual daily losses exceeded 6%, and one historical day exceeded 10%, making this unsuitable for a 25K prop evaluation without an explicit stop/risk overlay. The recent fixed-one-contract artifact performed very differently, but it lacks a generator or metadata trail and is not comparable to the volatility-targeted rule.

**Verdict:** preserve the Python model; validate on properly ratio-adjusted or individual-contract futures with roll costs and whole-contract sizing. Treat the 2024-2026 headline as an upper-end outcome, not the expected Sharpe.

### 2. ES/NQ SMA200 trend and the strategy bake-off

**Files:** `es_nq_backtest.py`, `es_nq_strategies.py`, and `es_nq_terms.py`.

The standalone SMA200 test is simple and avoids look-ahead. From 1990-2026 it earns Sharpe 0.74, CAGR 9.7%, and MaxDD 44.2%, versus buy-and-hold Sharpe 0.63, CAGR 11.7%, and MaxDD 69.2%. The post-2015 segment improves to Sharpe 0.87 with MaxDD 19.5%. This is the cleanest evidence in the workspace, although SPX/NDX cash indices are not tradable instruments and explicit trading costs are omitted.

The broader bake-off looks much better over 2024-2026 than over a longer sample:

| Strategy | 2013-2026 gross Sharpe | 2024-2026 gross Sharpe | Main interpretation |
|---|---:|---:|---|
| SMA200 trend | 0.97 | 1.31 | Most stable candidate; low turnover |
| Overnight | 0.94 | 1.42 | High daily turnover; recent net result falls materially with costs |
| RSI(2) mean reversion | 0.90 | 1.53 | Promising and relatively cost-tolerant, but selected in-sample |
| Buy-and-hold | 0.89 | 1.24 | Highest long-run/recent raw return, with larger drawdown |
| Vol-targeted trend | 0.85 | 1.07 | Lower-risk trend variant; credible but not superior |
| Intraday open-to-close | 0.50 | 0.47 | Weak after costs |
| Turn-of-month | 0.41 | -0.33 | Unstable; implementation also shifts the calendar mask one session |

At 1 bp per side, a reconstruction of the 2024-2026 strategies produces approximately Sharpe 0.96 for overnight and 1.50 for RSI(2). At 2 bps per side, overnight drops to 0.49 while RSI(2) remains about 1.46. The presidency slices support regime stability for trend, overnight, and RSI(2), but those slices are descriptive, not independent tests.

**Verdict:** advance SMA200 first. Freeze RSI(2) rules and test them on a new holdout with actual ES/NQ futures. Treat overnight as the separate candidate discussed below.

### 3. Overnight drift

**Files:** `overnight_drift_backtest.py`, `mnq_overnight_drift_backtest.py`, and `overnight_drift_strategy.pine`.

The long SPX/NDX proxy test produces net Sharpe 0.59, CAGR 8.0%, and MaxDD 32.8% from 2010-2026 at a 1 bp round-trip cost. Gross Sharpe is 0.90, illustrating the importance of the nightly round trip. At 2 bps, Sharpe falls to 0.28; at 5 bps it becomes -0.65. A 50/50 blend with index TSMOM raises Sharpe from 0.55-0.59 individually to 0.72 and reduces MaxDD to 21.9%, which is the best use case.

The real back-adjusted MNQ 6-hour sample covers only 2022-2026. At one tick round-trip it reports Sharpe 0.75, CAGR 11.1%, and MaxDD 19.8%. At eight ticks, Sharpe falls to 0.49. Returns were negative in 2022 and 2023 and strong in 2024-2026; Wednesday provides the only block/day result with a raw t-stat clearly above two. The loader drops every session missing one of four six-hour blocks, which can omit holiday/truncated sessions.

**Verdict:** promising diversifier, not proven standalone alpha. Re-run with commissions, fees, at least 1-2 ticks of slippage each way, whole-contract sizing, and a complete holiday/session policy.

### 4. Prior-level and gap-fill tests

**Files:** `es_nq_level_fill_backtest.py` and `pdh_pdl_range_backtest.py`.

The daily prior-week gap-backfill fade earns Sharpe 0.49 and CAGR 1.8% from 2015 at a 2 bp round-trip cost. ES is nearly flat (Sharpe 0.15); NQ carries the result (Sharpe 0.66). The portfolio Sharpe is 0.35 at 5 bps and 0.13 at 10 bps. Since 2020 it improves to 0.65, again mostly from NQ. The signal is pre-open and the lagged levels are implemented correctly, but the test has no untouched holdout and uses daily cash-index OHLC rather than futures fills.

The 5-minute PDH/PDL screen is not promising: all reported strategy Sharpes are at or below 0.22 after 1 bp-per-side costs, and the best MaxDD-adjusted returns are economically negligible. Its simulator also fails to test a stop or target on the same 5-minute bar in which an entry occurs, an optimistic path assumption.

**Verdict:** retain only the NQ prior-week gap-backfill idea for a clean futures/OOS test. Retire the current 5-minute PDH/PDL variants.

### 5. Equity factor long/short

**File:** `factor_ls_backtest.py`.

The reported composite is net of 5 bps churn and 2% annual borrow: Sharpe 0.53, annual return 3.4%, volatility 6.9%, and MaxDD 13.2% over 105 quarters. That result is not robust enough to accept:

- Re-running the same composite on the un-winsorized forward returns changes Sharpe from 0.53 to **-0.02**, annual return from 3.4% to **-0.5%**, and MaxDD from 13.2% to **39.1%**.
- `dividend_yield` is an exact duplicate of `price_volatility` for all 763,836 dataset rows. Those two reported single-factor results are therefore not independent and the dividend result is invalid.
- The 1%/99% clipping threshold is determined from the realized forward-return cross-section. It may be reasonable data cleaning, but the strategy's entire edge depends on it, so bad prints must be identified and corrected explicitly rather than clipping realized outcomes after the fact.
- The turnover-cost formula likely understates the economic cost of maintaining both a $1 long and $1 short book, although that is not the main problem here.

**Verdict:** invalidate the current result. Repair/verify the factor columns, identify specific bad return records, use predeclared cleaning rules, and rerun both raw and cleaned variants.

### 6. Commodity cross-sectional momentum

**File:** `commodity_xsec_momentum_backtest.py`.

From 2000-2026, cross-sectional L/S momentum reports Sharpe -0.31, CAGR -7.3%, and MaxDD 92.7%. The time-series variant is also negative (Sharpe -0.04). The long-only commodity basket is the only positive result. Approximate churn costs, winsorized monthly outcomes, and unadjusted front-month roll gaps further reduce confidence.

**Verdict:** reject the current strategy. A new test would need investable excess-return futures series and explicit roll/carry decomposition.

### 7. Intraday SPY/QQQ bake-off, ORB, and pairs

**Files:** `intraday_bakeoff.py`, `orb_backtest.py`, and `spy_qqq_pairs_backtest.py`.

The 2024-2026 intraday bake-off is dominated by buy-and-hold (Sharpe 1.31). Overnight drift is the only positive active idea after 1 bp-per-side costs (Sharpe 1.04); open-to-close, gap fade, and long-only ORB are near zero, while VWAP reversion and last-hour momentum are strongly negative. The VWAP simulator also omits the closing transaction cost when a position remains open at the final bar.

The standalone “ORB” is actually an opening-bar direction trade: it sets direction from the opening-range candle and enters at the next bar's open without requiring a break of the range. The 50/50 result is Sharpe -0.21 after costs. The true 15-minute breakout logic is tested more conservatively in the intraday strategy screen.

Every SPY/QQQ pairs parameterization fails. Reversion Sharpes range from roughly -4 to -8, and the flipped momentum variants are also deeply negative after costs.

**Verdict:** keep the overnight result only as corroborating evidence for the longer overnight study. Retire the other intraday and pairs variants.

### 8. Short-horizon futures bake-off

**File:** `short_horizon_backtest.py`.

The 2005-2026 run is the more informative one:

- Cross-sectional reversal, the momentum control, Donchian breaks, and turn-of-month all have gross Sharpe of 0.21 or less and deteriorate after costs.
- Spread reversion reports gross Sharpe 1.03 and Sharpe 0.99 at 1 bp per side, but the tradability diagnostic reduces the basket to Sharpe 0.00 when the signal is executed at the next open. The apparent edge occurs in the close-to-open gap before the model can trade it.
- NR7 breakout reports gross Sharpe 0.60 and 0.44 at 1 bp per side, but 14% of signals touch both breakout levels on the same daily bar. Under adverse ordering its 1 bp Sharpe is -0.04. The skip-ambiguous result is correctly labeled biased.
- The breakout holding counter includes the entry session plus the labeled number of later sessions, so a “5d” hold is effectively six sessions.
- The FOMC event study contains only 20 manually listed meetings even when the main backtest begins in 2005; it is not a 2005-2026 event sample.

**Verdict:** no executable edge survives. Retire the current set; any NR7 follow-up requires intraday data to resolve order.

### 9. Intraday strategy screen and TSMOM-filtered ORB

**Files/results:** `intraday_strategy_screen.py`, `reports/intraday_strategy_screen.csv`, `tsmom_intraday_orb_backtest.py`, and `reports/tsmom_intraday_orb_backtest.csv`.

The screen tests 21 market-strategy rows with whole micros, fixed per-trade risk, per-contract costs, and conservative stop-before-target bar ordering. No candidate is acceptable:

- MES 15-minute ORB has a full-sample profit factor of 0.99 and net P&L of -$94.
- MES close-confirmed ORB loses in the holdout.
- Several MNQ variants rarely trade because a single micro exceeds the risk cap.

The dedicated TSMOM-filtered ORB confirms the failure: MES has 160 trades, profit factor 0.94, net P&L -$357, and holdout P&L -$431. MNQ has only three tradable trades.

**Verdict:** reject the intraday set in its current form.

## Methodology audit

### What is done well

- The main TSMOM, trend, pairs, factor, and close-confirmed intraday models generally lag signals correctly.
- The TSMOM and overnight code use point P&L, avoiding percentage-return failure around negative oil prices.
- The short-horizon report explicitly measures ambiguous fills, gap-aware entries, costs, and non-tradable close-to-open effects.
- The local panel has coverage checks and a known cocoa print scrub; the 2005+ sample avoids the known pre-1987 rough-rice error.
- Several tests include cost sensitivity, regime slices, or holdouts rather than reporting only one headline number.

### Main weaknesses across the workspace

1. **Proxy risk:** SPX/NDX cash indices and SPY/QQQ ETFs are repeatedly treated as ES/NQ signals or P&L proxies. They omit futures basis, rolls, exchange fees, margin, financing, and contract rounding. Commodity fronts are unadjusted and can turn roll gaps into signals and P&L.
2. **Multiple testing:** the workspace contains at least dozens of strategy/market/parameter variants, but no experiment registry, deflated Sharpe, false-discovery correction, or untouched global holdout. The best observed Sharpe is therefore upward-biased.
3. **Inconsistent costs:** assumptions range from gross-of-costs to 1 tick round-trip, 1-2 bps, or flat dollars per micro. Commission, half-spread, slippage, roll, and market impact are not standardized.
4. **Fractional sizing:** most daily tests assume smooth fractional notional. The saved MNQ results show that a $25K account behaves very differently when the target rounds to whole contracts.
5. **No common benchmark/risk budget:** some tests target 10% volatility, some 20%, and some are unscaled. CAGR and MaxDD should not be compared without normalizing risk.
6. **Selection and overlapping validation:** the same 2025 holdout is reused across many ideas, and the ES/NQ bake-off ranks strategies on the displayed sample.
7. **Artifact provenance:** several saved CSVs, especially the fixed-one-contract TSMOM result, have no script, parameters, or immutable run manifest that can reproduce them.

## Recommended next research sequence

1. Freeze four candidates now: ES/NQ SMA200, four-market TSMOM, MNQ overnight, and ES/NQ RSI(2). Do not tune them on data after 2026-07-03.
2. Rebuild them on actual futures: dated-contract or well-documented ratio-adjusted continuous series, explicit roll dates, and session-accurate settlement/open definitions.
3. Use one cost model per contract: commissions + exchange/NFA fees + half-spread each side + configurable slippage + roll cost. Report at base, 2x-base, and stressed costs.
4. Simulate whole contracts and account constraints at the intended balance. Include maximum daily loss, intraday drawdown, margin, and forced-liquidation logic.
5. Use walk-forward evaluation with non-overlapping test folds. Report probabilistic/deflated Sharpe, bootstrap confidence intervals, parameter stability surfaces, and performance by market/regime.
6. Add an experiment manifest for every run: strategy ID, parent/lineage, data hash, code hash, parameters, train/test dates, number of variants tried, costs, and output path.
7. Fix the factor dataset and PDH same-bar execution bug before any further interpretation. Rename the standalone ORB tests to “opening-bar direction” unless they add a genuine range-break trigger.

## Scope and reproducibility notes

This evaluation covers every Python strategy/backtest entry point in the workspace, the saved result CSVs, and the three Pine strategy files through their closest Python analogs. `cme_stats_report.py`, fetch/build/probe utilities, smoke tests, and Pine indicators are not backtests and were not ranked. No TradingView Strategy Tester export exists for the Pine strategies, so Pine/Python execution parity is not independently verified.

Default runs were reproduced where useful. PWB-backed daily runs were reproduced against the cached `data/cme_daily.parquet` panel to avoid repeated remote materialization; the factor test was rerun from the PWB quarterly factor dataset. Additional checks included 1990/2010 TSMOM windows, a 2013 ES/NQ bake-off window, level-fill cost stress, 2005 short-horizon history, whole-contract MNQ artifact metrics, and raw-versus-winsorized factor outcomes.
