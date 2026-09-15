# Pine strategy audit and Python ports

## Result

Reviewed all **17 Pine files: 5 strategies and 12 indicators**. Four Pine-specific
execution variants now have Python scripts and workbench registrations. The fifth
strategy already has Python supply/demand, release, RVOL, and comparison tooling;
that engine was retained. None of these new ports has certified TradingView
trade-export parity.

| Pine strategy | Python implementation | Finding |
| --- | --- | --- |
| [Overnight block](pine/overnight_block_strategy.pine) | [pine_overnight_block.py](strategies/pine_overnight_block.py) | Existing Python clock studies; new port preserves Pine's close-timestamp transitions and next-open orders. |
| [Daily TSMOM](pine/cme_tsmom_single_market_strategy.pine) | [pine_daily_tsmom.py](strategies/pine_daily_tsmom.py) | Existing daily proxy model; new port implements its daily 20/60/120/252 inputs, population point volatility, whole-contract equity sizing, and first-15-minute-close rebalance. |
| [Filtered overnight drift](pine/overnight_drift_strategy.pine) | [pine_overnight_drift.py](strategies/pine_overnight_drift.py) | Existing proxy-return research; new port implements Pine's session filter, actual close-fill timing, and volatility/equity sizing. |
| [TSMOM intraday ORB](pine/cme_tsmom_intraday_orb_strategy.pine) | [pine_tsmom_orb.py](strategies/pine_tsmom_orb.py) | Existing related ORB research; new port implements configurable windows, risk-rejected attempts, close entries, working brackets, and force-flat behavior. |
| [SND Phase 6/7](SND_phase6_strategy.pine) | [SND_baseline_backtest.py](scripts/mnq/SND_baseline_backtest.py), [SND_phase6_release.py](scripts/mnq/SND_phase6_release.py), [SND_phase7_relative_volume.py](scripts/mnq/SND_phase7_relative_volume.py), [SND_phase6_strategy_parity.py](scripts/mnq/SND_phase6_strategy_parity.py) | Existing stateful engine and RVOL/TradingView reference workflows. No duplicate engine created; full workbench integration remains pending. Existing research code is not proof of every Pine sizing option's parity. |

## Run the new ports

Open **Scripts** and select a card beginning **Pine ·**. Selecting the card sets
**Full Globex day**, the required session so that overnight bars and the completed
daily model are available. Daily TSMOM uses 15-minute bars; ORB uses 5-minute bars.
The two overnight ports support 5 and 15 minutes. The daily models default to
600 warmup calendar days.

- Capital, commissions, slippage, dates, and contract point/tick values come from
  the run configuration. They do not silently inherit TradingView Properties.
- The signal and execution instrument are the selected dataset. No alternate
  TradingView signal ticker or manual point-value override is substituted.
- The supplied NQ archive is the full-size contract ($20/point), not MNQ
  ($2/point). The ORB's original $75 risk budget can correctly yield no trades
  on full-size NQ. A different risk budget is a different saved experiment.
- Session-window integers are minutes after midnight in the selected timezone:
  09:30 = 570, 15:45 = 945, 16:00 = 960. Overnight block uses separate hour/minute
  fields. Windows and warmup are checked before execution.
- Ordinary runs, parameter/cost sweeps, result artifacts, historical replay,
  chronological evaluation, and regime studies work. Pine evaluations run
  baseline and higher-cost scenarios with additional delay set to zero;
  execution-delay stress remains unsupported and explicitly reported. Aligned
  comparison rejects mixing event and next-open signal execution models.

## Timing and execution findings

1. **Overnight block:** default entry hour 17 arms on the bar ending at 17:00.
   The pending order fills at the next available open, normally the 18:00 reopen.
   The position is flat during the halt. A Friday pending order can fill Sunday.
   Window transitions, rather than continuous desired exposure, trigger entries.
2. **Overnight drift:** the code identifies the first outside-RTH bar and fills
   at its close. On a five-minute chart, normal entry is 16:05 and exit 09:35,
   rather than the idealized 16:00/09:30 described in its comments.
3. **Daily models:** only the previously completed 18:00–17:00 New York session
   is published to a later chart bar. Partial final days cannot affect earlier
   decisions. This implements historical confirmed-data behavior; the Pine
   scripts' realtime `request.security` behavior can differ after reload.
4. **ORB:** the 15:45–16:00 force-flat window closes an existing position at the
   first qualifying five-minute close, normally 15:50. A qualified breakout that
   exceeds the risk budget still consumes the day's attempt. A bracket created
   at a signal close cannot exit against the earlier high/low of that signal bar.

The shared [event simulator](workbench/events.py) marks equity at every chart-bar
close and reconciles trade P&L and costs. Brackets are walked through the original
one-minute OHLC bars in order. A gap through a level fills at the minute open;
if both levels are touched within one minute, the stop wins. Touch timestamps
are recorded at minute completion because the exact intraminute time is unknown.
Slippage is a cash cost on market and stop executions; resting limit exits pay
commission only. Reported fill prices are reference prices before that cash cost.

TradingView's broker emulator, lower-timeframe Bar Magnifier, order-fill
recalculations, daily settlement data, and margin liquidations are not reproduced
exactly. These choices follow the source's decision timing but do **not** certify
matching TradingView trades or P&L. Reviewed official references:
[strategy order processing](https://www.tradingview.com/pine-script-docs/concepts/strategies/)
and [higher-timeframe data availability](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/).

## Indicators

| Pine indicator | Treatment |
| --- | --- |
| `SND.pine` | Existing supply/demand Python research; preserve it. |
| `orb_carver.pine` | Existing `scripts/orb/orb_carver_backtest.py`; preserve it. |
| `orb.pine` | Related canonical opening-range engine already exists. |
| `overnight_block_indicator.pine` | Companion to the new overnight-block port. |
| `cme_tsmom_manual_indicator.pine` | Related CME trend Python research already exists. |
| `factor_score_indicator.pine` | Single-symbol factor display; not the multi-stock factor long/short strategy. No entry/exit rules invented. |
| `gap_fill.pine` | Gap/fill display; no complete order/sizing strategy specified. |
| `ib.pine` | Initial-balance session levels; no complete order/sizing strategy specified. |
| `market_sessions.pine` | Session drawings. |
| `overnight_hl.pine` | Overnight reference levels. |
| `prior_levels.pine` | Prior-session/week reference levels. |
| `vwap_bands.pine` | VWAP/band display; not automatically equivalent to the existing VWAP reversion strategy. |

The source library now displays every Pine file, its inputs, original source hash,
existing Python counterparts, and new port links. Pine sources are included in
immutable run snapshots and exports alongside their Python ports.

## Validation

`npm run test:pine` covers timing, daily publication/causality, clock boundaries,
equity sizing, one-attempt rules, one-minute stop/target ordering, gap fills, costs,
and ledger reconciliation. `npm run test:pine-browser` checks discovery, Pine
source inspection, form defaults, and real ZIP-data runs. Evidence is saved under
`reports/workbench-validation/`. A future matching TradingView trade-list export
is needed for platform parity certification.
