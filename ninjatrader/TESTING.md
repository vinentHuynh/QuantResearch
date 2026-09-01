# Getting both strategies into NinjaTrader 8 and validating them

NinjaTrader 8.1.8.2 is installed at `C:\Program Files\NinjaTrader 8`. The user
folder may be **OneDrive-redirected**. Resolve it dynamically with:

```powershell
Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'NinjaTrader 8'
```

Anything resolving Documents must use `[Environment]::GetFolderPath('MyDocuments')`
— a hardcoded `%USERPROFILE%\Documents` points at a folder that does not exist
here and will silently report "not installed".

Menu paths below are from NinjaTrader's documented layout. If your UI differs,
say what you actually see rather than hunting for a close match — a wrong guess
here is silent, not loud.

---

## 1. First launch — DONE

The user folder is fully seeded and `NinjaTrader.Custom.dll` was last compiled
2026-08-30 19:07, so NinjaTrader has been run and has compiled successfully.

## 2. Install and compile the strategies — COPIED, AWAITING F5

Both files are now in
`OneDrive\Documents\NinjaTrader 8\bin\Custom\Strategies\`:

- `OrbCarver.cs`
- `OvernightDriftCarver.cs`

No collisions: the folder already held `3wick.cs`, `MyCustomStrategy.cs`,
`SupplyDemandZones.cs` V1–V4 and the stock `@Sample*` strategies, and neither
the class names nor the `OrbExitStyle` / `OrbDirectionMode` enums clash with
anything in `bin\Custom`.

Both compile clean (zero errors, zero warnings) against your live
`NinjaTrader.Custom.dll`, not just the seed copy — run `build_check.ps1` to
repeat that any time.

**Remaining: New → NinjaScript Editor → F5.** NinjaTrader compiles every file in
`bin\Custom` as one assembly, so if F5 fails, read the error carefully: a fault
in `3wick.cs` or a `SupplyDemandZones` variant will block these two as well, and
the message will name that file rather than mine.

## 3. Create a custom instrument

**Tools → Instruments → New**

| Field | Value |
|---|---|
| Name | `MNQCONT` |
| Instrument type | Future |
| Exchange | CME |
| Tick size | `0.25` |
| Point value | `2` |
| Currency | USD |
| Trading hours | **CME US Index Futures ETH** |

A *custom* instrument, not a real contract month, because the Databento series
is volume-rolled continuous and not back-adjusted. Importing it onto a real
contract invites NinjaTrader to roll a series that has already been rolled.

`Point value 2` is load-bearing: the strategies read
`Instrument.MasterInstrument.PointValue` for position sizing. Wrong here and
every order size is wrong.

## 4. Import the sample and settle the time zone

This is the step that silently ruins everything if skipped.

The parquet is stored US/Eastern. NinjaTrader's documented convention is the
instrument's **exchange** time zone — US/Central for CME, one hour behind. If
that assumption is wrong, both strategies' clocks shift by an hour: the opening
range would build from 08:30–08:45 bars and the overnight block would run
17:00–05:00. Nothing errors. The results are just wrong.

One week is already exported in both zones:

```
ninjatrader\nt_import\sample_US-Central\MNQCONT.Last.txt
ninjatrader\nt_import\sample_US-Eastern\MNQCONT.Last.txt
```

1. Set the platform to Eastern: **Tools → Options → General → Time zone →
   (UTC-05:00) Eastern**.
2. **Tools → Historical Data → Import**, select the **US-Central** file.
3. Chart `MNQCONT`, 5 Minute, session template CME US Index Futures ETH.
4. Look at 2026-06-01 to 2026-06-05. **Where does the RTH volume jump land?**
   - at **09:30** → Central was right, continue
   - at **10:30** → NinjaTrader wanted Eastern; wipe the instrument's data
     (**Tools → Historical Data → Edit**) and import the US-Eastern file instead

## 5. Full import

Once the zone is confirmed:

```
.venv\Scripts\python.exe ninjatrader\export_for_nt.py --tz US/Central
```

(or `--tz US/Eastern`). Writes 464,212 bars, 2020-01-01 → 2026-08-07, to
`ninjatrader\nt_import\MNQCONT.Last.txt`. Import the same way. It takes a while.

## 6. Strategy Analyzer — OrbCarver

**New → Strategy Analyzer**, right-click → **Backtest**.

| Setting | Value | Why |
|---|---|---|
| Instrument | `MNQCONT` | |
| Strategy | `OrbCarver` | |
| Bars | 5 Minute | the tested resolution |
| From / To | 2020-01-01 → 2026-08-07 | see the warm-up note below |
| Trading hours | CME US Index Futures ETH | 18:00–17:00 session boundary |
| Order Fill Resolution | Standard | High needs 1-minute bars we have not imported |
| Slippage | **1 tick** | applied per fill = 2 ticks round turn, matching the model |
| Commission | $0.62 per contract per side | = $1.24 round turn |

Strategy inputs: Capital `100000`, Tau `0.12`, IDM `1.0`, weight `1.0`,
OR minutes `15`, Exit style `OrStopTarget`, Direction `Both`, Target R `2.0`,
times `93000` / `143500` / `160000`.

**Warm-up.** The strategy needs 26 completed sessions before it can size
anything, so start the run at 2020-01-01 and compare only trades from
**2020-03-06** onward — that is where the Python backtest's liquidity gate
opens. Starting the run at 2020-03-06 instead would push the first NinjaTrader
trade to roughly 2020-04-13 and quietly drop ~26 sessions.

**On Standard fill resolution:** ORB carries a stop and a 2R limit at the same
time, and inside one 5-minute bar NinjaTrader cannot know which came first. It
resolves that with a fixed rule. The Python backtest makes the same assumption
deliberately (stop wins ties, the conservative choice), so Standard is
defensible — but it is a modelling assumption you are inheriting, not a
measurement.

### What it should produce

MNQ, $100,000, 2020-03-06 → 2026-08-07:

| | Python |
|---|---|
| Trades | 1,626 |
| Win rate | 46.3% |
| Net P&L | $47,920 |
| Sharpe (net) | +1.07 |
| Annualised vol | 6.8% |
| Max drawdown | −8.2% |
| Mean contracts | 1.92 |
| Exit mix | 42.6% stopped / 15.5% hit 2R / 41.9% flat at close |
| Long share | 52.2% |

The **exit mix is the most diagnostic row.** It stabilises on hundreds of trades
and it pins down the mechanics: get the bar timestamps or the bracket wrong and
that mix moves long before the P&L does.

## 7. Strategy Analyzer — OvernightDriftCarver

Same instrument, bars, dates, session template. Order Fill Resolution
**Standard** is genuinely fine here — there are no intrabar orders.

> **Set Tau to `0.12`, not the default `0.06`.**
> The strategy ships at 6% because Carver halves the risk target for the −0.35
> nightly skew. The *backtest* ran at 12%. Leave it at 6% and every size halves,
> ~28% of 2026 nights round to zero contracts and get skipped, and nothing will
> reconcile. Validate at 12%, then set it back to 6% before trading anything.

Slippage: the model is **1 tick round turn**, and NinjaTrader applies slippage
per fill in whole ticks — so it cannot express half a tick per side. Run it at
`0` (understates cost by 1 tick round turn) or `1` (overstates by 1 tick) and
read the result knowing which way it leans. Do not average them and call it
right.

### What it should produce

MNQ, $100,000, **Tau 0.12**, 18:00→06:00:

| | Python |
|---|---|
| Round turns | ~1,656 (504 sides/yr) |
| Win rate | 54.7% |
| Net P&L | $33,339 |
| Sharpe (net) | +0.88 |
| Annualised vol | 5.74% |
| Max drawdown | −5.97% |
| Skew | −0.35 |
| Mean contracts | 1.93 |

**Strategy Analyzer only exercises half this strategy.** Everything runs as
`State.Historical`, so it validates the backtest path — entry submitted on the
17:00 bar, filled at the 18:00 open — and never touches the realtime path that
fires on the session's first tick. That branch is only reachable through Market
Replay or Sim101, and it is the piece most likely to hold a bug.

## 8. Reading the result

This is a **port check, not evidence.** Same data, same rules — agreement means
the NinjaScript reproduces the Python, nothing more. It says nothing about
whether either edge is real.

Divergence is the finding, and roughly:

| Symptom | Look at |
|---|---|
| Trade count off by a constant | warm-up window / start date alignment |
| Every timestamp off by an hour | step 4, wrong import time zone |
| Exit mix shifted, P&L roughly right | bar timestamp convention (NT stamps close, pandas stamps start) |
| Sizes off by a constant factor | Point value on the custom instrument, or Tau |
| Sizes occasionally 0 | expected — see `sizing_check.py`; 28% of 2026 nights at Tau 6% |
| Overnight P&L too good | a roll seam landing inside 18:00–06:00 |

Export the trade list (**right-click the results grid → Export**) and I will diff
it against `reports/mnq_orb_all_trades.csv` trade by trade. That finds the cause
in one pass; eyeballing summary rows will not.
