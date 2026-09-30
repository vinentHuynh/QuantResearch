# SND opposing-zone exit research

`snd-zone-exit` is a separate workbench adapter. The existing `snd` adapter and
preserved runs retain their original rules. Configure **SND - Opposing zone exit
experiment** in New Run on the 1m chart with the full trading-day session.

The entry variants are unchanged. The `zone_exit` parameter compares:

- `baseline`: original stops, fixed targets and scheduled closes.
- `touch`: a completed minute reaches or passes the proximal edge of an opposing
  zone; exit at the next available minute open.
- `close-inside`: a completed one-minute candle closes within the inclusive
  proximal/distal boundaries of an opposing zone; exit next minute open.

Supply zones oppose long positions; demand zones oppose short positions. All
active 1h/4h/daily context zones can trigger an exit, even when the entry variant
trades only 1h zones. Zones must already be available at the signal minute open.
The exit check retains zones that this minute subsequently invalidates. A close
beyond the distal edge is not a close inside the zone. Touch includes gaps beyond
the edge. Neither signal fills retrospectively at the boundary price.

Existing brackets execute before these completed-bar signals. Scheduled closes
take priority over a next-open zone exit. Fixed size and all other entry rules
are preserved. Earlier exits alter future opportunities, so comparisons use
fresh stateful simulations.

The initial campaign freezes MNQ, prior-1m RVOL, one contract, $100,000 reference
capital, January 2024–August 2026, 60-day warmup, $1.25 commission per side and one
tick slippage on market/stop fills. Limit exits charge commission only. The
campaign reports every mode, annual results, exit reasons and an exact arithmetic
doubling of recorded costs. It makes no untouched-holdout or live-readiness claim.

Run `node scripts/backtest-snd-zone-exit.mjs`, then
`.venv/Scripts/python.exe scripts/analyze-snd-zone-exit.py`. The first script
previews and launches native workbench runs and resumes the existing campaign;
it does not launch duplicate completed runs. Run a new campaign directory for
different settings. Source and dataset identities remain linked to native run
artifacts. Reports are in `reports/snd-zone-exit-2026-09-17/`.

Tests: `.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_snd*.py' -v`.
