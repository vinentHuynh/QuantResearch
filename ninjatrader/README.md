# NinjaTrader 8 ports of the two Carver-vetted backtests

Two self-contained NinjaScript strategies. Each is a direct port of one
backtest in this workspace, with Carver's *Leveraged Trading* sizing,
risk-target and cost machinery built in rather than bolted on.

| File | Source backtest | Tested cell | SR_net | Clock |
|---|---|---|---|---|
| `OrbCarver.cs` | `orb_carver_backtest.py` | MNQ, OR15, stop + 2R, both directions, tau 12% | **+1.04** | RTH 09:30–16:00 ET |
| `OvernightDriftCarver.cs` | `overnight_drift_carver_backtest.py` | MNQ, 18:00→06:00 ET, long only, tau 6% | **+0.88** | Globex 18:00–06:00 ET |

The two clocks are disjoint, so they can run on the same instrument
simultaneously without netting each other. In the workspace's multi-rule book
the overnight rule is the leg that lifted measured IDM to ~1.61.

---

## Install

1. Copy both `.cs` files to
   `Documents\NinjaTrader 8\bin\Custom\Strategies\`
2. In NinjaTrader: **New → NinjaScript Editor → Compile** (F5).
3. Set the platform time zone to **(UTC-05:00) Eastern** — *Tools → Options →
   General → Time zone*. Every time input in both strategies is Eastern. If you
   run another zone you must shift the inputs by hand.
4. Chart setup, both strategies:
   - Instrument: **MNQ** (front month or a back-adjusted continuous contract)
   - Bars: **5 Minute**
   - Session template: **CME US Index Futures ETH** (18:00–17:00 ET)
   - Days to load: **≥ 120** — each strategy needs 26 completed sessions of
     closes before it can size a position, and the trend-filter option needs 65
   - Order Fill Resolution: **High / 1 Minute** for `OrbCarver` (it has intrabar
     stop and target orders); **Standard** is fine for `OvernightDriftCarver`

Do not run either on a non-adjusted continuous series priced close-to-close.
Databento `.v.0`-style series step by the calendar spread at each roll; in
contango that step is positive and a naive P&L books it as profit nobody
earned. Both strategies are flat across the roll seam by construction, but your
NinjaTrader chart's own merge policy still needs to be back-adjusted.

---

## What each strategy actually does

### OrbCarver

1. Freeze the high/low of the first 15 minutes of RTH (bars stamped 09:35,
   09:40, 09:45).
2. First bar that **closes** beyond that range arms a trade; the market order
   fills at the **next bar's open**. One attempt per session, either direction,
   whichever breaks first. No re-entry.
3. Stop = **stop market** at the opposite edge. Gap-aware: through the level you
   fill at the open, not the level.
4. Target = **limit at 2R**, where R = |fill − stop| — measured from the fill,
   not the range width, so it runs ~1.14× the range.
5. No new entry after 14:35. Flat at the RTH close regardless — 42% of trades
   end there, so it is a core exit, not a fallback.
6. Size = `Capital × IDM × weight × tau / (σ_ann × price × multiplier)`, rounded,
   held constant for the trade's life.

### OvernightDriftCarver

1. At 18:00 ET, long the block, sized by the same formula with **tau = 6%**.
2. Flat at 06:00 ET. One round trip per session, ~504 sides a year.
3. No stop, by design (see below).

Entry and exit each hit the same price in backtest and live, by two different
routes — the CME 17:00–18:00 halt means no bar *ends* at 18:00, so historically
the entry is submitted on the 17:00 bar and fills at the 18:00 open, while live
it goes in on the session's first tick. Same for the 06:00 exit. This is the one
piece of machinery in either file that exists purely to keep the two modes
honest with each other.

---

## The parts you are not allowed to skip

**Both strategies breach Carver's speed limit on measured drag.**
ORB: 0.156 SR/yr. Overnight: 0.147 SR/yr. The limit is 0.30 / 3 = 0.100. Both
log this at startup. The limit is set from a *prior*, not from each backtest's
own gross Sharpe, because using a backtest to justify its own costs is how an
overfit result launders itself. Read "BREACH" as: *this only works if the gross
edge is real, and the gross edge is the part you cannot verify.*

Note also that the a-priori cost formula understates the true drag by 1.4–1.7×
for the ORB and 3.5× for the overnight block. Both rules pay a full ticket for a
fraction of a day's risk. Measured drag is the verdict; the formula is a lower
bound.

**Minimum capital is the binding constraint, not the signal.**
Carver's floor is 4 contracts (rounding error ≤ 12.5%). MNQ has roughly tripled
since 2020 while a $100k account has not: the ORB's 4-lot floor is now ~$338,000,
and at $100k about 84% of 2026 trades round to exactly **one** lot — a fixed-size
system wearing a vol-target's clothes. Both strategies print the floor and warn
when you are under it. Fix it with capital or a smaller contract. **Never by
raising tau.**

**The overnight tau is halved and that is not a typo.**
Nightly skew is −0.35. Carver halves the risk target for negative-skew payoffs,
and holding a gap over a closed market is the textbook case. `OvernightDriftCarver`
defaults to 6% and logs a warning if you raise it. The ORB's trade skew is
**+0.84**, positive, so it runs the full 12%.

**The overnight benchmark is not zero — it is 24h buy-and-hold.**
Same MNQ, buffered vol-targeting, ~8 trades a year instead of 504, seam-free
SR +0.71. The block wins by **+0.17 SR**. That is the entire case for going flat
every morning, and it is thin. On MES the block *loses* (+0.39 vs +0.73); on MCL
it is negative outright. Do not port this to those instruments without re-reading
the backtest.

**No stop on the overnight rule, by design.** The risk carried is a gap over a
closed market — precisely the risk a stop cannot stop, because you fill through
it. A disaster stop is exposed and defaults to `0` (off); switching it on means
you are no longer trading the rule that was tested.

**Drawdown expectations, set now so a drawdown is not evidence later.**

| | tau | ordinary (2×tau) | planned for (3×tau) | backtested maxDD |
|---|---|---|---|---|
| ORB | 12% | 24% | 36% | −8.2% |
| Overnight | 6% | 12% | 18% | −6.0% |

Realised drawdowns are far below plan only because each rule is flat most of the
day and therefore realises 0.48–0.57 × tau of risk. That is a feature of the
clock, not a promise.

**Recent performance is negative and it means nothing.** MNQ ORB 2026 YTD:
SR −0.18 over 156 sessions, the 7th percentile of history — 11% of prior windows
that long were also negative. SE(SR) over one year is ~1.0, so a one-year Sharpe
carries a ±2 band. Detecting SR 0.5 from zero at 95% confidence needs ~30 years.
You will never prove either system works. Watch the two things that *are*
measurable — realised vol against tau, and realised cost against the model — and
leave the rules alone.

---

## Inputs worth knowing about

Both strategies expose `IDM` and `Instrument weight` so they compose into a
multi-instrument book: set `IDM` to the **measured** value from the backtest
(~1.6 for the handcrafted four) and `weight` to that instrument's share (0.25).
Leave both at 1.0 for a single instrument — raising IDM above 1.0 on one market
is fictional diversification and both files log a warning if you do. MES and MNQ
correlate ~+0.9: two equity index futures are one bet wearing two tickers.

`Commission` and `Slippage ticks` affect **diagnostics only** — they set the cost
figures in the log, not the orders. Defaults match the backtests: $1.24 round
turn plus 2 ticks for the ORB (breakouts cross the spread) and 1 tick for the
overnight block. Modelling either at zero is how you get a backtest that cannot
happen.
