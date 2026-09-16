# SND in the workbench

Open **Scripts**, search **SND**, inspect the baseline or Phase 6/7 source,
and click **Configure SND - Supply and demand**. You can also select SND in
**New Run**. Choose a dataset, dates and variant, then validate and launch.

- `original_multi_tf`: 1h, 4h and daily zone retests, higher-timeframe priority.
- `phase6`: 1h trades, first physical touch, at least 2 structural R opposing room (or no opposing zone).
- `phase7_prior_1m`: Phase 6 plus first-touch RVOL from the prior completed minute.
- `phase7_prior_5m` (default): Phase 6 plus first-touch RVOL from the latest completed five-minute bar.

Execution uses a **1m chart**, the **full trading day**, and **60 calendar days
of warmup**. Higher-timeframe candles are built internally at the source's
18:00 New York session anchor. Completed candles only can create zones.
Phase 7 requires at least 30 requested warmup days; absent RVOL history rejects
setups until sufficient observations exist. The default is one fixed contract.

MNQ, NQ, ES, YM and CL are selectable. The existing MNQ cache is registered with
its checksum, $2 point value and 0.25 tick size. To register that cache again,
run `.venv/Scripts/python.exe scripts/register-mnq-workbench.py`.

The adapter reuses the original zone detection, test selection, rearming,
bracket-level and clock helpers. Workbench snapshots preserve these dependencies
under `scripts/` along with the adapter, simulator and environment.

Entries fill at the next available minute open; working brackets can exit on
that entry minute. Gap fills use the opening price, and stops win ambiguous
intraminute collisions. A position present at the open blocks another setup
on its exit minute. First-touch RVOL remains frozen even when a different trade
was open at the touch.

The original point distances remain unchanged across markets: 100/200/400 point
targets, 100-point stop cap, 1-point distal buffer, and 75-point rearm distance.
These are transfer experiments on ES, YM and CL, without instrument calibration.

This is the **source-derived next-open research variant**. It does not implement
Pine percentage-risk sizing or certify TradingView parity. Workbench session
filtering, partial boundary candle exclusion, flat scoring start, warmup test
consumption and final liquidation can differ from an uninterrupted standalone
research run. Workbench limit exits pay commission without slippage; the fresh
standalone report charged slippage on both sides. The run's warnings preserve
these distinctions.

Completed runs publish native trades, positions, marked equity and metrics.
Refresh the collective dashboard and select **All tested** to find them by SND,
market and variant. A successful run establishes execution, not eligibility for
the **Working** or **Fully tested & feasible** filters. Use only dates covered
by each selected run when comparing combinations.

Adapter regression tests: `.venv/Scripts/python.exe -m unittest discover -s tests -p test_snd_adapter.py -v`.
Browser and five-market/four-variant January 2026 integration campaign:
`node scripts/validate-snd.mjs` (creates 20 workbench runs).
