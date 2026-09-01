# Quant Research — Findings & Handoff

Consolidated notes for a future agent. Read this before proposing or building
anything. It records what's been tried, what works, what doesn't, the data
gotchas, and the methodology lessons that cost real time to learn.

**One-line summary:** the only durable edges found are *overnight index drift*
and *cross-sectional equity factor momentum*. Both are real but modest, and
nearly every intraday signal fails net of costs.

---

## 1. Context

- **Workspace:** the repository root. Python venv at `.venv`
  (`pwb-toolbox`, pandas/numpy, `databento`, `duckdb`). Run scripts with
  `./.venv/Scripts/python.exe`.
- **Primary markets:** ES/NQ and their micro contracts, MES/MNQ.
- **User goal:** robust, low-drawdown futures strategies, ideally intraday.
- Judge strategies on per-trade tails and drawdown paths as well as Sharpe.

## 2. Data

Two data sources. **Prefer Databento for anything futures/intraday.**

### PWB (`pwb-toolbox`, key `PWB_API_KEY` in `.env`)
- Daily datasets: `Indices-Daily-Price` (SPX, NDX — ES/NQ cash proxies, has
  O/H/L/C), `Commodities-Daily-Price` (**front-month only**, e.g. CL1/GC1, NO
  CL2 → no term-structure carry), `Stocks-Daily-Price`,
  `Stocks-Quarterly-FactorSignals` (22k symbols incl. delisted, factor
  percentiles 1998-2026).
- **GOTCHA — never `load_dataset("Stocks-1Min-Price", symbols=[...])`.** The
  loader downloads the WHOLE ~75GB set then filters in pandas (no pushdown) → ate
  18GB RAM, killed. The 1-min endpoint has 199 date-partitioned shards
  (~260MB each), ignores HTTP Range, blocks HEAD. To pull a few symbols: stream
  needed shards to disk + `pyarrow.read_table(filters=[("symbol","in",[...])])`
  (see `build_intraday.py`). Cached result: `data/{SPY,QQQ}_5min.parquet` (RTH
  only, 2024-01→2026-06).
- **GOTCHA — `Stocks-Quarterly-FactorSignals.returns` column is dirty:** ~50%
  are exactly 0.0 (illiquid filled as zero) + junk outliers (max +89900%). The
  "market" shows an impossible 10% MaxDD through 2008. Factor RANKINGS are usable
  but P&L from that column is NOT — recompute from real prices.

### Databento (key `DATABENTO_API_KEY` in `.env`, format `db-` + 32 chars)
- Dataset `GLBX.MDP3` (CME Globex). `databento_fetch.py` pulls continuous
  front-month (`ES.c.0` = calendar roll = TV's ES1!), schema `ohlcv-1m`,
  resamples to any bar size, saves tz-aware **US/Eastern**.
- **GOTCHA — GC calendar roll (`GC.c.0`) lands on illiquid serial months** (~24
  bars/day). Use **volume roll `GC.v.0`** → 140k bars. For ES/NQ/CL calendar
  roll is fine.
- Cost: ~$7.67 for 4 syms 5-min 2y; ~$17 for MES+MNQ 5-min 2020-2026. Use
  `--dry-run` (free `metadata.get_cost`) before every pull.
- **Cached now:** `data/{MES,MNQ,CL,GC}_5min_databento.parquet`. MES/MNQ go back
  to **2020-01-01**; CL/GC to 2024-08. Full ~23h Globex session, tz-aware ET.
  Continuous is **unadjusted** → roll-day return spikes; winsorize daily returns
  (0.1-0.5%/tail) before stats.

## 3. Bottom-line verdicts

| Strategy family | Verdict | Best number (honest) |
|---|---|---|
| Intraday day-trades (ORB, VWAP, gap-fade, last-hour, PDH/PDL) | **Fail net of costs** | all ≤0 net; buy&hold beats them |
| SPY-QQQ intraday pairs (market-neutral) | **Null** — gross edge ≈0, HFT-arbitraged | −0.3 to −5 net |
| Short-horizon 1d-1wk (XS reversal, NR7, Donchian, ToM, FOMC) | **All null** once fills honest | NR7 1.20→0.14 on honest fills |
| Commodity x-sec / TS momentum | **Failed** (roll-contam + decay) | −0.31 / −0.04 |
| Commodity long-only basket | **Real diversifier** | Sharpe 0.67, corr 0.09 to SPX |
| Equity factor L/S (market-neutral) | **Real, low-DD** (data caveats) | Momentum 0.86 Sharpe / 7.6% DD |
| **Overnight index drift (MES/MNQ)** | **The one real futures edge** | see §4 |

## 4. The overnight drift edge (main thread)

**What it is:** long the Globex overnight (RTH close 16:00 ET → next RTH open
09:30 ET), flat during the day. Always LONG — it's a structural, one-directional
premium (mean-reversion bounce). Intraday (open→close) earns ~0; the whole equity
premium is overnight.

**Validated on REAL futures** (`futures_overnight_backtest.py`, Databento):
- 2024-26: MES Sharpe 1.32, MNQ 1.49 — beat buy&hold. **Cost-robust** (MNQ
  1.50→1.35 even at 8-tick round trip). Charge costs in **TICKS not bps** (a
  1-tick MNQ RT ≈ 0.12bp; the old "1bp" default over-charged ~8×).
- **Full 2020-26 deflates it: MES 0.43 / MNQ 0.71 Sharpe, 28-31% MaxDD.** The
  2024-26 window was regime luck. This is the honest number.

**Direction is settled — shorting is dead.** Tested green/red, close-zone,
regime, gap, prior-night, day-of-week (`overnight_conditional_backtest.py`): the
drift is positive in ~every bucket. Every short rule loses; "long green/short
red" and "long hi-close/short lo" are −0.5 to −1.2 (backwards — the edge is a
bounce, strongest AFTER weakness). Never short the overnight.

**Best exit refinement: TP=PDH** (take profit at prior-day high). Cuts MaxDD ~40%
(MES 31→17%, MNQ 28→19%), hit rate 67-69% — the bounce runs to the day high, lock
it vs giving back to the open. TP=PWH useless (too far).

**Tail control** (`overnight_bracket_backtest.py`,
`overnight_best_backtest.py`): PDL stop + skip-wild-days reduces the worst night
to roughly −$330 to −$720 from −$1,998 on MNQ. Return collapses to ~2-3%/yr,
and stops fill at PDL in the backtest while real news gaps can blow through
between bars.

**Why nights lose** (`overnight_loss_profile.py`): edge is dead/negative when
prior day **closed near high**, is **inside prior-week range**, or is **calm** —
no dislocation to bounce from (~half of all nights). Big losses **cluster in
vol events** (Mar-2020, Aug-2024, Apr-2025), are gap-downs, and are NOT
filterable from prior-day features. Best long buckets: closed-low, **below prior-
week low (oversold, +13bps)**, red days, high-vol.

**Filtered version** (`overnight_filtered_backtest.py`, WITH train/test): skip
closed-high/inside-week + PDL stop → single-night safe (worst −$442-608). But
train/test shows honest Sharpe ~0.2-0.5 (the 1.2-2.0 test numbers are 2024-26
regime, not skill); without the stop the Apr-2025 cluster still leaks a −$1,570
MNQ night.

**FINAL VERDICT on overnight:** the edge is real but modest over the full
history (~0.4-0.7 Sharpe). A stop can reduce the single-night tail, but it cuts
return to ~2%/yr and losses still cluster during crash weeks. It is best treated
as a risk-budgeted portfolio sleeve rather than judged on headline Sharpe alone.

### 4b. Does the overnight block exist in GOLD? (MGC) — mostly no

`mgc_overnight_block_backtest.py`, Databento MGC.v.0 5-min 2019-10→2026-08
(1,715 nights, in-sample) + GC.v.0 2015-2020 priced at micro $10/pt and rescaled
to today's notional (1,233 nights, out-of-sample). MGC = 10 oz, $10/point,
0.10 tick = $1.00. Costs 1 tick RT.

**The shape replicates, the significance does not.** 18:00→06:00 on MGC pays
**$7.55/night net, Sharpe 0.53, PF 1.13, hit 53.3%, t = 1.38**; OOS $4.30/night,
t = 1.03; **pooled t = 1.71** — under the ~2.0 bar and far under MNQ's 3.58. The
*structure* is the same as equities though: overnight $7.55 vs DAY 06-18 $0.83
vs **NY am 06-12 −$1.37** (negative again), so the overnight block captures 86%
of gold's whole-session return while on risk 52% of the time. Six-hour blocks:
Asia 18-00 $6.59 (t 1.68) carries nearly all of it, London 00-06 $0.27, NY pm
$0.53. The hour-window scan agrees the action is at the reopen — every top-10
window starts at 18:00, best is 18:00→21:00 Sharpe 0.95 — but the **sign-flip
best-of-208 null gives p = 0.225**, i.e. entirely explainable by search.

**Regime, not edge (so far):** in-sample split is 1st half Sharpe −0.09
(−$0.55/nt) vs 2nd half 0.82 (+$15.66/nt). By year: 2021 −$2.9, 2022 −$6.0,
2023 +$2.9, 2024 +$8.7, **2025 +$27.7, 2026 +$24.9**. This is the gold bull
market being harvested overnight, and 2015-2019 OOS averaged ~+$3-5/nt.

**Tail is worse per dollar of edge than MNQ:** worst night −$2,444, 6 nights
< −$1,000 in 1,715, sd $226/night for a $7.55 mean. Cost-robust though
(breakeven 8.5 ticks RT).

**The one genuinely useful number: correlation to the MNQ overnight sleeve is
only +0.19** over 1,650 shared nights. Running both 1× gives $22.38/night at
Sharpe 1.02 with MaxDD −$6,303 (vs MNQ alone $14.15, Sharpe 1.01, −$3,558). The
blend does not improve Sharpe over MNQ alone and roughly doubles the drawdown,
so **MGC is not yet worth adding** — but it is the least-correlated overnight
sleeve found, and worth revisiting if the pooled t ever clears 2.

**⚠ THE TRAP (see lesson 8): the two best-looking scenarios are carry artifacts.**
`16:00*→06:00` shows $15.87/nt, Sharpe 1.02, pooled t **3.06**, and
`16:00*→09:00` t 2.96 — both would have been the headline. Both hold the
16:00→18:00 session seam. Decomposed, gross:

| segment | IS $/nt | IS t | OOS $/nt | OOS t | verdict |
|---|---|---|---|---|---|
| 16-17 last hour | 2.13 | 1.82 | 0.10 | 0.13 | does not replicate → noise |
| 17-18 seam | 3.25 | **2.73** | 1.98 | **2.36** | replicates, but it is CARRY → unbankable |
| 18-06 overnight | 8.55 | 1.57 | 5.30 | 1.26 | the only segment that is a trade |

Proof it is carry, not alpha: MGC front→next calendar spread measured from
parent-symbology outrights (`data/MGC_outrights_daily.parquet`) annualizes to
2.6% (2019) → 0.8% (2021) → 5.6% (2023-24) → 4.5% (2026), which
**correlates +0.966 with the fed funds rate** and averages **$971/yr per
contract**. Gold is a pure cost-of-carry market (F = S(1+r+storage)^T), so an
unadjusted continuous series rolls up by the funding rate for free, and the roll
jump lands in the seam. Strip it and the 16:00* scenarios collapse back to the
18:00 entry.

## 5. Other strategies — detail

- **Equity factor L/S** (`factor_ls_backtest.py`, quarterly top-vs-bottom
  quintile): Momentum Sharpe 0.86 / 7.6% DD / beta −0.19 / 77% quarterly hit —
  best single factor. Profitability/cash-flow/quality ~0.65, single-digit DD,
  beta~0. Value −0.62 (value winter), price_vol −0.52 (=low-vol anomaly, FLIP),
  reversal −0.71 (flip). Composite gross 0.82 but **borrow-fragile** (0.82→0.53
  at 2%/yr borrow→neg at 8%; short leg is hard-to-borrow junk). **P&L
  untrustworthy — dirty returns column (§2); rerun on real daily prices.** This
  is the honest "low-DD" answer but it's stocks, not intraday futures.
- **Commodities** (`commodity_xsec_momentum_backtest.py`): carry not buildable
  (front-month only). X-sec/TS momentum failed (roll contamination + decay).
  Long-only EW basket = Sharpe 0.67, corr 0.09 to SPX → a real diversifier sleeve.
- **Short-horizon bake-off** (`short_horizon_backtest.py`): all null — XS
  reversal, NR7 (1.20→0.14 on honest fills), Donchian, turn-of-month, FOMC drift
  all inside noise or negative net.
- **Intraday on SPY/QQQ** (`intraday_bakeoff.py`, `orb_backtest.py`,
  `pdh_pdl_range_backtest.py`, `spy_qqq_pairs_backtest.py`): all failed net.

## 6. Methodology lessons (the expensive ones)

1. **Charge futures costs in TICKS, not bps.** bps of notional over-charges
   micros ~8×. A 1-tick MNQ/MES round trip is the realistic unit.
2. **Distrust any clean intraday level Sharpe until fills are honest.** A naive
   "fill at the exact level" bug produced a FAKE Sharpe 3.80 breakout / 3.01 fade
   in `pdh_pdl_range_backtest.py` that both collapsed to ~0 with gap-aware fills
   (pay the open on gap-throughs; don't fade a level the market gapped past).
3. **Winsorize roll-day spikes** on unadjusted continuous futures before stats.
4. **When both a signal and its inverse lose ~equally, gross edge is ~0 and
   costs are eating you** (the SPY-QQQ pairs tell).
5. **In-sample vs out-of-sample matters** — filters chosen from a dataset look
   great on it. Always train/test split. The 2024-26 window specifically
   flatters overnight/long-equity (regime luck) — never conclude from it alone.
6. **Dollar tails and the drawdown path matter alongside Sharpe.** Losses can
   cluster during crash weeks even when each individual loss is survivable.
7. **Buy & hold is the benchmark that keeps winning** on Sharpe in most windows.
   Real systematic edges are Sharpe 0.5-0.8; anyone showing 2+ is curve-fit.
8. **On commodities, check cost-of-carry BEFORE anything else — and never trust
   a high t-stat from a low-variance segment.** An unadjusted continuous contract
   rolls up through contango, so any window spanning the 16:00→18:00 session seam
   books the funding rate as profit. On MGC that is ~$971/yr per contract, and it
   made two scenarios (`16:00*→06:00`, `16:00*→09:00`) look like the best in the
   study at pooled t 3.06 / 2.96. The seam's own t-stat (2.73 IS, 2.36 OOS) is
   *higher* than the real trade's (1.57 / 1.26), because a mechanical accrual has
   almost no variance — significance testing actively rewards artifacts. Diagnostic
   that settles it in one line: divide the seam's annual $ by contract notional and
   compare to the policy rate; confirm against the real front→next spread from
   parent-symbology outrights. Equity index carry is small enough to ignore; gold,
   crude and rates carry are not. `front_next_basis()` in
   `mgc_overnight_block_backtest.py` is reusable.

## 7. Script inventory

**Data pipeline:** `databento_fetch.py` (CME futures → parquet, use this),
`build_intraday.py`/`fetch_intraday.py`/`probe_*.py` (PWB 1-min SPY/QQQ, legacy),
`fetch_cme_data.py`, `smoke_test.py`.

**Overnight (the deep thread, run in this order):**
`futures_overnight_backtest.py` (validate on real futures) →
`overnight_conditional_backtest.py` (direction buckets) →
`overnight_bracket_backtest.py` (PDH/PWH TP, PDL/PWL stop) →
`overnight_best_backtest.py` (TP+stop+selectivity) →
`overnight_loss_profile.py` (why nights lose) →
`overnight_filtered_backtest.py` (filtered + TRAIN/TEST). Also
`overnight_drift_backtest.py` (daily SPX/NDX proxy, has TSMOM-correlation) and
`mnq_overnight_drift_backtest.py` (earlier real-MNQ rerun).
`mgc_overnight_block_backtest.py` (gold, two eras, carry-leakage test + sign-flip
window scan + MNQ correlation — run with `--scan`).

**Other backtests:** `factor_ls_backtest.py`, `commodity_xsec_momentum_backtest.py`,
`cme_time_series_momentum_backtest.py` (daily TSMOM ES/NQ/GC/CL, point-vol sized),
`short_horizon_backtest.py`, `intraday_bakeoff.py`, `orb_backtest.py`,
`pdh_pdl_range_backtest.py`, `spy_qqq_pairs_backtest.py`, `es_nq_*.py`,
`tsmom_intraday_orb_backtest.py`, `intraday_strategy_screen.py`.

## 8. Pine indicators (TradingView, all `//@version=6`, NY sessions)

`ib.pine` (Initial Balance, multi-session fib), `orb.pine`, `prior_levels.pine`
(PDH/PDL/PDC + prior-week), `overnight_hl.pine` (Globex ONH/ONL),
`vwap_bands.pine` (session + Asia VWAP, σ-bands), `gap_fill.pine`,
`market_sessions.pine`. Strategies: `cme_tsmom_single_market_strategy.pine`,
`overnight_drift_strategy.pine` (long RTH close→open), `factor_score_indicator.pine`
(single-symbol factor proxy — stocks only, N/A on futures).

## 9. Open threads / next steps

- **Rerun equity factor L/S on real daily prices** (join FactorSignals ranks to
  `Stocks-Daily-Price` forward returns; bound universe to avoid the no-pushdown
  OOM) — the current P&L is untrustworthy.
- **Overnight risk controls** — the filtered/TP=PDH/PDL-stop configuration is
  ready for further forward testing and Pine implementation.
- **Intraday on real futures** — the ORB/IB/gap setups have only been tested on
  SPY/QQQ proxies; real MES/MNQ Globex data now exists to test them honestly
  (though the "intraday earns ~0" result predicts they'll be flat).
