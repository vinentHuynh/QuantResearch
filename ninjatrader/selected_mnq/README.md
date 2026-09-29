# Selected MNQ strategies — 2026-09-29

Use **Overnight Block** for the overnight strategy. Its matched MNQ replay was more profitable than the installed Overnight Session variant. TSMOM ORB now has the calendar-aware exit repair described below.

| Strategy | Chart | Default size and key settings |
|---|---|---|
| `WorkbenchMnqOvernightBlock` | 15 Minute | 1 MNQ; normal entry around 18:00 ET and exit around 06:00 ET; no stop or target. |
| `WorkbenchMnqMinuteReversal` | 1 Minute | 1 MNQ; >1.25% prior RTH decline above SMA200; scheduled 09:35 ET entry/exit; intentionally holds overnight, no stop or target. |
| `WorkbenchMnqTsmomOrb` | 5 Minute | Maximum 1 MNQ; $250 stop-risk budget; 20/60/120/252-day trend votes; 09:30–09:45 ET opening range; stop at opposite range edge; signal-close 2R target. |

All require an **MNQ contract** and **CME US Index Futures ETH** trading hours. The platform can remain in Central time: the code converts to Eastern with DST. The reversal and ORB need **600+ calendar days of actual history** (at least 201 RTH closes and 253 ETH closes respectively). Chart history availability matters; a day-count setting alone does not create missing data.

## Installation

1. Run `install_sources.ps1`, or copy all six files in `Strategies/` into `Documents/NinjaTrader 8/bin/Custom/Strategies/`. The installer resolves OneDrive Documents correctly and backs up any different same-name file.
2. Open **NinjaTrader → New → NinjaScript Editor → F5**. The external API compile check has passed; this step compiles the complete native custom-script library.
3. In Strategy Analyzer choose the exact bar interval and ETH template above, and keep **Calculate = On bar close**. For reversal and ORB, begin the loaded test range about 600 calendar days before the period you want to evaluate, then inspect trades after warmup. The cores do not automatically fetch daily history before the Analyzer From date. Use an MNQ commission template and explicit slippage; the historical reports use $0.62 commission plus one tick per side as research assumptions.
4. Check the results and order behavior in Playback/Sim101. No strategy has been enabled and no orders were placed by this work.

The ZIP is a source bundle, not a NinjaTrader Export NinjaScript archive. Use the installer rather than the archive importer. The previously installed `WorkbenchMnqOvernightSession` is left intact as an alternate, but it is **not selected or included here**. Running both overnight variants would mostly double the same exposure.

## Why Overnight Block

Matched MNQ data, January 2020–August 2026, one micro and identical $2.24 round-trip costs:

| Version | Net profit | Minute-close maximum drawdown |
|---|---:|---:|
| **Overnight Block** | **$25,499.48** | **−$3,961.06** |
| Overnight Session, conservative 18:01 entry | $24,429.96 | −$4,298.98 |

Block remains ahead with doubled costs and after excluding trades that cross recorded continuous-contract changes. The comparison executes the actual compiled C# clock rules. These are historical simulations on already inspected data, not prospective results or verified broker fills. See `overnight-comparison.md` and `overnight-comparison.json` for the full assumptions.

## What changed in ORB

The old 15:45–16:00 exit window was absent on nine holiday/short-session trades, leaving positions open overnight. The repaired Python adapter is version 1.1.0; original runs remain preserved.

- Normal completed-bar flatten time stays **15:50 ET**.
- On a shortened session, flatten **five minutes before the scheduled session close** if that is earlier. A 13:00 close means a 12:55 decision; a 13:15 close means 13:10.
- Entry stops at the deadline, and the flatten condition remains active afterward. Each session starts with a fresh opening range.
- Research uses a frozen copy of NinjaTrader's CME ETH calendar, version 5119, covering 2016–2026. It never derives the close from a future observed price bar. Histories missing held exit quotes through the known close fail validation.
- NinjaTrader reads the actual configured session end and also keeps its native **60-second-before-session-close** safety enabled. Historical native fallback and real-time timer behavior are different; the primary scheduled five-minute lead is what the regression checks cover.
- Late/partial entry fills retain an exit request, pending entries are cancelled when flattening is requested, and rejected orders use `StopCancelClose`. These controls cannot guarantee a fill during a closed market or lost connection.

The MNQ $250 budget preserves the original NQ $2,500 budget's **125-point, one-contract cutoff**. It does not divide price distances by ten or automatically trade ten micros. Budget excludes fees, gaps and slippage.

`orb-results.md` and `orb-results.json` contain every replay, costs, drawdowns, source IDs and carry checks. `validation.json` records compilation and code checks. The compiled C# signal tests and Python backtests do **not** substitute for a native NinjaTrader backtest or Playback test.

All nine current historical cases passed with zero overnight carries. On one MNQ over January 2024–August 2026, net profit was $5,139.82 at baseline costs, $4,529.64 at doubled costs, and $5,188.82 with strict next-open execution (282 trades each). The C# core matched 151,025 Python decisions in the separate actual-data comparison; see `orb-core-realdata.json` for its scope.

The targeted calendar, next-open and C# checks and the application build passed. The broader Pine suite still has its pre-existing inventory assertion failure: it expects 17 Pine files while this workspace contains 21. Its other 11 tests passed; no Pine files were added by this repair.

## Limits that remain

The MNQ ports use MNQ prices. Python's original ORB baseline fills at the signal close; the new next-open scenario tests the transfer assumption. NinjaTrader submits market orders for the next quote and uses native stop/limit fills; these can differ from Python's one-minute stop-first model. Brackets remain anchored to the signal close.

The session calendar is a current vendor snapshot, not proof of what was published on every historical date. Future holiday schedules need current NinjaTrader Trading Hours definitions. Unadjusted continuous-roll prices, sparse data, fees and fills remain material research limits. None of this enables a strategy or certifies live profitability.

These are separate strategy positions with no shared-account risk controller. The reversal deliberately holds across the maintenance break and may hold weekends. Prop-account holding limits, liquidation times and drawdown rules are not enforced by this package.
