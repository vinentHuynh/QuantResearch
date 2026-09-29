# Matched MNQ overnight comparison

More profitable in this replay: **block**. Block minus Session: **$1,069.52**.

2020-01-01 through 2026-08-31 trading session dates; one MNQ; identical $2.24 round-turn costs. Actual unchanged C# clock decisions were executed on the same MNQ data, with next-open fills. Block uses 15-minute clock transitions; Session uses the installed conservative 18:01 entry.

| MNQ port | Net P&L | Trades | Minute-close max DD | Gross P&L | Costs |
|---|---:|---:|---:|---:|---:|
| block | $25,499.48 | 1,723 | $-3,961.06 | $29,359.00 | $3,859.52 |
| session | $24,429.96 | 1,721 | $-4,298.98 | $28,285.00 | $3,855.04 |

The catalog's larger NQ Session baseline total uses the 18:00 entry and does not describe the installed 18:01 port. The strategies hold almost the same overnight long exposure; running both largely doubles it.

The winner remains **block** after excluding trades crossing recorded contract changes (Block $16,987.72; Session $16,151.20) and **block** with doubled costs.

- These dates were already available and reviewed; this comparison is historical selection, not an untouched holdout or profitability guarantee.
- No NinjaTrader runtime/Playback fill test is implied; provider bars, holidays, connectivity and actual fills can differ.
- MNQ cache has unverified original vendor request provenance, missing minutes and unadjusted continuous-contract rolls.
- Calendar uses canonical weekday ETH filtering, not an authoritative CME holiday schedule. Next available quotes are used across gaps.
- Drawdown is marked on observed one-minute closes, not every tick; worst trade low is also shown. Neither strategy has a stop.
- Costs are matched research assumptions, not verified brokerage rates; default commission is $0.62 per side plus one tick per side.
- Trading session dates determine the common window, not UTC calendar entry dates. Only closed trades with entry session in the window are scored.

Reproduce: `.venv/Scripts/python.exe scripts/compare-mnq-overnight-ports.py`
