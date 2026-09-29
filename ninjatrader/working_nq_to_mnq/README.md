# Tested NQ configurations converted to MNQ — NinjaTrader 8

**Superseded later on 2026-09-29:** the [selected MNQ package](../selected_mnq/README.md)
keeps Overnight Block, retains Minute Reversal, and adds the repaired/retested
TSMOM ORB. This folder preserves the original selection and evidence snapshot.

Three separate strategies, selected from the current workbench's **NQ Working + tested** records and checked against its review notes. Default size is **one MNQ contract**, with MNQ prices driving the signals. No NQ secondary data series is required. MNQ is $2 per point and $0.50 per 0.25-point tick; the point and percentage thresholds are not divided by ten.

| NinjaTrader strategy | Chart | Rules and normal Eastern times |
|---|---|---|
| `WorkbenchMnqOvernightBlock` | 15 Minute | Long on transition into the 17:00–06:00 completed-bar clock window. A normal 17:00 signal fills after the 18:00 reopen; exit after the 06:00 completion. |
| `WorkbenchMnqOvernightSession` | 1 Minute | Long after the opening minute completes at 18:01; exit after 06:00. Uses the source's **tested conservative entry**, rather than its baseline 18:00 first-open assumption. |
| `WorkbenchMnqMinuteReversal` | 1 Minute | Prior completed RTH close falls strictly more than 1.25%, while remaining above its 200-day RTH SMA. Long at the next 09:35 opening window, exit at the following qualifying 09:35 window, and remain flat for one interval. Entries more than five minutes late are skipped. |

All require **MNQ** and the **CME US Index Futures ETH** trading-hours template. They reject NQ, other instruments, the wrong bar interval, and the wrong session template. Eastern time is converted from NinjaTrader's configured platform time zone, including DST; the platform itself can remain on Central time. The reversal requires at least **201 completed RTH days** before entries; load **600 or more calendar days** and ensure sufficient actual data. The overnight strategies need history spanning the prior boundary; loading 10 days is a practical starting point.

## Install and open

1. Run `install_sources.ps1` in this folder. It copies the three strategies and two required helper files to your actual Documents/NinjaTrader 8/bin/Custom/Strategies directory. An existing different file is backed up before replacement. It does not launch NinjaTrader, select an account, or enable strategies.
2. In NinjaTrader, open **New → NinjaScript Editor** and press **F5**. Native compilation includes every custom script on your machine; unrelated script errors can still block this step.
3. Open **Strategy Analyzer**, choose one strategy and an MNQ contract with historical data, then use the exact chart interval and ETH template above. Set an MNQ commission template and explicit slippage. The `Contracts` input defaults to 1; increasing it changes the tested exposure.
4. Inspect entries/exits in historical results, then use Playback or Sim101 to check actual order handling before using an external account. No strategy has been enabled by this conversion.

This directory is a **source bundle**, not a NinjaTrader Export NinjaScript archive. Use the installer or copy all five `.cs` files from `Strategies/`. Do not import the ZIP through NinjaTrader's archive importer.

## Evidence and exclusions

The exact NQ inputs, source hashes, run/evaluation IDs, artifact checksums, and selection reasoning are preserved in `selection.json`. The selected configurations have historical **Working** evidence; none carries the stronger **feasible** label.

**TSMOM ORB is excluded.** Its catalog still showed Working, but the same-configuration review records nine unintended overnight holds caused by absent holiday/short-session flatten bars. Run `ab520bd4-b1bd-4b68-9e7b-98feb2edea32` is tagged `checks-failed`; its review requires fixing missing flatten windows before promotion. No ORB strategy is included in this package.

Other markets, screened strategies, failed variants, and older unrelated Carver scripts are not part of this conversion.

## What was verified

- C# compiles against the locally installed NinjaTrader 8.1.8.2 Core, GUI and Custom assemblies; details are in `validation.json`.
- The compiled reversal core matched every Python scheduling decision on **2,585,939 preserved MNQ minute bars**: 1,893 daily decisions, including 149 long targets. Synthetic checks cover DST/weekends, incomplete and partial days, sparse early closes, late quotes, and the strict threshold. See `reversal-validation.json`.
- The compiled overnight clock logic is tested against the original Python block and the frozen conservative session execution scenario, plus DST, gaps, duplicate callbacks and missing exit bars. See `overnight-tests.log`.

These are source-selection, compilation and decision checks. **NinjaTrader historical fills, Playback fills and MNQ profitability have not been validated.** They are not implied by the original NQ results. The test suite and source files live in the workspace's `ninjatrader/` and `tests/` directories; `validation.json` records commands and hashes.

## Execution details that affect results

- The two overnight strategies substantially overlap. Enabling both doubles overlapping long exposure; they are separate configurations, not independent diversification. All three can overlap on the same MNQ account; this package does not manage shared positions or account risk.
- All three intentionally have **no stop/target**, as in their selected source rules. The reversal holds across the daily maintenance break and can hold weekends. No prop-firm liquidation, news, drawdown, or contract-limit controller was added. Changing those rules requires another test.
- Bar-close market orders fill on the next available quote. Python's final-close marking for Overnight Session cannot be guaranteed in NinjaTrader; its exit submits after the 06:00 completed minute. Its entry follows the tested conservative 18:01 scenario.
- Overnight Block preserves the source's clock-window transitions, including transitions first observed after gaps or early-close holidays. It does not manufacture a 17:00 bar or chase a missed signal with a timer. A delayed live callback can still produce a later actual fill.
- Reversal's source gives next-open entries a 09:40 expiry and exits a 16:00 expiry. NinjaTrader market orders cannot guarantee cancellation before a future quote gap. The wrapper rejects stale entry callbacks using the live/Playback clock and retains an exit intent while an earlier order finishes, but this is not a broker-side good-till-time guarantee.
- Defaults use `WaitUntilFlat` and `StopCancelClose` error handling. A historical open position can keep the strategy waiting until it becomes flat. Disabling a strategy or losing a connection is not equivalent to proving that the account is flat.
- Broker history, settlement/session definitions, holiday schedules, contract rolls, fees and liquidity differ from the research dataset. One MNQ has one tenth of NQ's point exposure; after costs, returns are not a simple one-tenth copy of NQ performance.

Contract references: [CME MNQ specifications](https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.html), [NinjaTrader bar-close timing](https://ninjatrader.com/support/helpguides/nt8/isfirsttickofbar.htm).
