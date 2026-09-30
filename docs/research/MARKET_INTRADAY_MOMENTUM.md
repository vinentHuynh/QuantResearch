# Market intraday momentum: closing 30 minutes

The workbench discovers `strategies/market_intraday_momentum.py` automatically as
**Market intraday momentum - last 30 minutes**. Four saved market presets select
ES, NQ, MNQ or CL. Open **Scripts & library → Runnable scripts → Configure run**.

The default signal is the direction of the return from the previous closing
price to the start of the final 30 minutes (Baltussen). The optional Gao signal
uses the previous close to 10:00 New York return, including the overnight move.
Positive signals buy; negative signals sell short; zero signals stay flat.
The default size is one contract. No gamma or volatility filter is applied.

Use `new-york-rth` and a `1m` or `5m` chart. ES/MES/NQ/MNQ/YM use a 16:00
New York close; CL requires `close_time=14:30`. CL's Gao observation at 10:00
is an explicit adaptation to the selected 09:30-start session. ZN and 6E are
rejected until their market clocks and datasets are specified. MES is supported
by the adapter but has no registered local dataset.

A completed observation schedules an entry at the next open exactly at the
deadline. An absent entry quote expires the order; it cannot fill late or
overnight. The five-minute delay stress preserves the original signal and
changes entry timing only. The scheduled closing bar exits at its close and
pays both fees and slippage. If a held position encounters a missing closing
bar, the run fails instead of silently carrying into another session. Whole
contracts, equity marks and trade ledgers use the shared event simulator.

Ten warmup calendar days are requested by default. A valid preceding close
must actually be observed; at the left edge there may be no trade. Closes
older than four calendar days and nonpositive reference/observation prices
suppress entry. This is strategy-specific initialization, not a declaration
that a minute-bar count proves daily warmup.

This is a fixed-clock research adaptation, not an exact paper reproduction:
there is no holiday/early-close exchange calendar, gamma exposure data,
settlement auction model, margin model or roll-neutral continuous series.
Five-minute aggregation can mask missing underlying minute endpoints; the
campaign compares raw minute prices and recent one-minute trade ledgers.

Run the targeted checks and saved campaign with:

```powershell
node scripts/python-command.mjs -m unittest discover -s tests -p test_market_intraday_momentum.py -v
node scripts/backtest-market-intraday-momentum.mjs
node scripts/python-command.mjs scripts/analyze-market-intraday-momentum.py
node scripts/validate-market-intraday-momentum.mjs
```

The campaign is resumable and preserves all 28 planned final-source attempts,
plus one full-history CL one-minute confirmation added after three missing raw
minute endpoints were found in the five-minute baseline. The earlier 28 queued
v1.0.0 attempts remain as canceled records. Its frozen protocol,
run IDs, software regression logs, full-history results and minute comparisons
are in [the research artifact folder](../../artifacts/research/market-intraday-momentum-2026-09-17/).
These exploratory runs do not award evaluation or robustness milestones.

Sources: [Gao et al. (2018)](https://profiles.wustl.edu/en/publications/market-intraday-momentum/)
and [Baltussen et al. (2021)](https://pure.eur.nl/en/publications/hedging-demand-and-market-intraday-momentum/).
