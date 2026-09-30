# Consolidated strategy library

Generated from local Python and Pine source using static parsing; discovery does not execute scripts.

171 Python and Pine sources; 17 runnable workbench adapters.

## Runnable adapters

| Strategy | Parameters | Migration scope |
| --- | --- | --- |
| [AW Reversal - NQ frozen research interpretation](../../strategies/aw_model_nq.py) | bias_policy, bias_required, impulse_multiple | One fixed, causal interpretation of chapters 5, 6, 9-11 of the AW Model PDF, not author-verified rules. Pre-08:30 CT five 2H proxies are: (1) latest 2H failure to make a lower low/higher high; (2) premarked eligible external high/low still beyond price; (3) position below/above midpoint of the last five completed 2H bars; (4) an untouched strict 2H FVG wholly above/below price; (5) latest two completed 2H bars have higher highs/lows or lower highs/lows. A strict 3-of-5 directional vote is required by default. Prior day means the prior complete 08:30-to-calendar-declared-close CT cash session, including shortened valid sessions; overnight means prior 17:00-08:30 CT. Each 3m neckline is a strict pivot with two left and two right candles confirmed before a completed 3m wick-through/close-back sweep; the last two confirmed pivot highs and lows must both rise for shorts or fall for longs. The first strong 3m close through it within five subsequent completed 3m bars must be the middle candle of a strict 3-bar FVG. First later 1m physical gap touch schedules one NQ contract at the immediately following minute open, expiring if that minute is missing; event-v1 cannot model a resting limit entry. Stop is one tick beyond the swept extreme, target the nearest premarked opposing level still untaken at entry, with no discretionary R:R floor. A confirmed, still-untaken 3m pivot more than two points beyond planned entry and strictly before the target is frozen as a proxy first internal level; a later completed 1m close beyond it moves the stop to actual fill plus/minus two NQ points. If none exists, no BE move; subsequent discretionary trailing is omitted. Two submitted entries maximum per CT day; CME daytime calendar closes positions by 15:00 CT or earlier declared close. Intraminute fills, gaps, stop-first collisions, costs and final liquidation follow event-v1. Unadjusted continuous-contract roll gaps can contaminate 2H/3m structures because the workbench 1m selected bars omit instrument_id. No CPI/NFP/FOMC exclusion, equal-high/low pools, IFVG preference, manual significance, dollar-risk sizing, daily loss cap, or flip-candle entry. One contract can exceed the PDF risk ceiling. Historical execution is not live-trading validation. |
| [Buy and hold benchmark](../../strategies/buy_hold.py) | contracts | Consolidates the passive long benchmark only. Fixed futures contracts with explicit entry/exit costs replace the original proxy-return benchmark. |
| [Market intraday momentum - last 30 minutes](../../strategies/market_intraday_momentum.py) | signal_mode, close_time, holding_minutes, entry_delay_minutes, minimum_move_bps, contracts | Research adaptation, not paper replication. New York fixed clock: equity close 16:00, CL close 14:30; Gao observation at 10:00 (CL 09:30 open is an explicit adaptation). Signal includes overnight return. Completed signal bar schedules an exact-time next-open entry with expiry; scheduled close-price exit pays fees/slippage. Delay preserves the original signal. No gamma observations, volatility selection, auction/settlement execution, holiday/early-close calendar, roll-neutral prices, or margin model. Missing signal/entry quotes skip entry; missing exit quotes fail the run instead of silently carrying overnight. Stale prior closes older than four calendar days and nonpositive prices suppress entry. Five-minute bars use nominal completion and may contain missing underlying minutes; compare 1m execution checks. Fixed clocks on early-close days are not exchange-calendar replication. |
| [Moving-average trend](../../strategies/moving_average.py) | lookback, contracts | Consolidates long/flat moving-average decisions. Original cash-index portfolios and notional-return accounting are not reproduced. |
| [Multi-speed momentum](../../strategies/multi_speed_momentum.py) | lookback, contracts | Uses the canonical engine four-speed signal. Original CME proxy portfolio, lookbacks, volatility sizing, and NAV accounting are not reproduced. |
| [Pine · Daily TSMOM rebalance](../../strategies/pine_daily_tsmom.py) | fast_length, medium_length, slow_length, annual_length, sizing_mode, contracts, annual_risk, maximum_leverage, volatility_length, sleeve_count, rounding | Historical Pine decision/timing port. Daily bars and signal use the selected futures dataset, not a separate signal symbol or TradingView settlement feed. Whole contracts; no TradingView margin-call emulation. Live request.security repaint behavior is not reproduced. |
| [Pine · Overnight block](../../strategies/pine_overnight_block.py) | entry_hour, entry_minute, exit_hour, exit_minute, contracts, timezone | Ports the Pine clock/order rules, including boundary-only entries. Scoring starts flat; no entry midway through an existing hold window. Costs and contract economics use the run inputs. |
| [Pine · Filtered overnight drift](../../strategies/pine_overnight_drift.py) | sizing_mode, contracts, annual_risk, maximum_leverage, volatility_length, sleeve_count, timezone, rth_start, rth_end, trade_weekend, close_rule, strong_threshold | Preserves actual Pine bar-close timing, which differs from the header's ideal RTH-close/RTH-open trades. Uses selected-dataset daily prices and economics; no TradingView margin-call simulation. |
| [Pine · TSMOM intraday ORB](../../strategies/pine_tsmom_orb.py) | fast_length, medium_length, slow_length, annual_length, timezone, minimum_score, opening_start, opening_end, entry_start, entry_end, flatten_start, flatten_end, risk_budget, maximum_contracts, reward_risk, require_close_break, execution_timing | Pine rules port with one-minute bracket execution. Stop wins ties within a minute; gap fills use the opening price. No TradingView sub-minute Bar Magnifier or order-fill recalculation emulation. A rejected risk-sized attempt still consumes the session. Version 1.1 uses the frozen NinjaTrader CME US Index Futures ETH calendar (2016-2026): close at the earlier of the normal flatten-start bar completion or five minutes before scheduled close; no entries thereafter. Missing held exit quotes fail the replay instead of creating overnight performance. Opening ranges reset every session. Calendar is a current historical snapshot, not a point-in-time exchange archive; NQ/MNQ scope only. Original pre-fix runs remain separate evidence. |
| [RSI(2) trend-filtered reversion](../../strategies/rsi2_reversion.py) | trend_lookback, entry_rsi, exit_rsi, contracts | Ports s_rsi2 decisions, including its zero-loss RSI convention. Uses selected futures, fixed whole contracts and next-open fills; original cash-index NAV differs. |
| [RSI(2) reversion - corrected rebound exit](../../strategies/rsi2_reversion_corrected.py) | trend_lookback, entry_rsi, exit_rsi, contracts | Separate research variant of rsi2-reversion; the legacy adapter and its evidence remain unchanged. Retains simple rolling two-change RSI, strict entry/exit thresholds, long-only trend-filtered entries, fixed whole contracts and next-open fills. Defines RSI as 100 when gains are positive and losses zero, 0 for only losses, and 50 when both are zero. This changes rebound exits and may change later entries. Declared warmup conservatively requires trend_lookback+1 completed daily bars, including at least three closes for RSI. Warmup initializes decision state; scoring starts flat. No maximum holding period, stop, margin model, or continuous-contract roll correction. |
| [Short-term reversal - prior-day selloff](../../strategies/short_term_reversal.py) | decline_pct, confluence, trend_lookback, close_fraction, direction, max_decline_pct, hold_sessions, renew_on_signal, exit_on_rebound, min_atr_multiple, atr_period, contracts | Benchmark-template fixed-contract model. RTH close-to-close signal fills next RTH open. Holding sessions count open-to-open intervals; optional fresh signals reset the holding clock, and a favorable close-to-close day can schedule an early next-open exit. ATR is the simple mean of true ranges through the PREVIOUS session, not including the signal shock. Maximum decline filters entries, not open-position losses. No intraday stop/target; overnight/weekend exposure, continuous roll gaps, daily-close drawdown, and final-close liquidation remain material limitations. |
| [Short-term reversal - minute execution](../../strategies/short_term_reversal_minute.py) | decline_pct, trend_lookback, open_delay_minutes, max_entry_lateness_minutes, contracts | Same long-only daily signal as short-term-reversal v1.1 with trend filter, one-session hold and renewal disabled (one mandatory flat interval). Completed 09:30-16:00 New York RTH bars generate signals; partial current days never contribute. A completed minute at/after 09:30 plus the configured offset schedules a next-open fill. Late new entries are suppressed; entry orders expire after the lateness allowance, exit orders expire at that RTH close and are resubmitted at subsequent opening windows. Warmup never synthesizes a position. Full-trading-day minute marks include overnight but exclude 17:00-18:00 and weekends. Native warmup is undeclared because minute counts cannot prove daily initialization; the model separately requires sufficient completed pre-start RTH days. No authoritative holiday calendar, per-contract roll execution, intraminute stop/target, or margin model. Prior daily-shift failure remains unresolved; not an automatic status promotion. |
| [SND - Supply and demand](../../strategies/snd.py) | variant, contracts | Source-derived next-open research adapter, not certified Pine parity. Fixed contracts; original 100/200/400 PRICE POINT targets, 100-point stop cap and 1-point distal buffer retained on every market. Phase 6/7 require first physical touch and 2 structural R opposing room; Phase 7 freezes prior completed-bar RVOL at first touch (20 slot observations, minimum 10, band 0.75 <= RVOL < 1.25). Warmup consumes eligible zone tests without positions. Workbench session filtering, flat start, final liquidation and commission-only limit exits differ from the standalone research ledger. No Pine percent-risk sizing or touch-price entries. |
| [SND - Opposing zone exit experiment](../../strategies/snd_zone_exit.py) | variant, contracts, zone_exit | Exploratory fixed-contract SND exit experiment. Original stops, targets, scheduled closes and entry rules retained. Zone exits inspect all active 1h/4h/daily opposing zones available at the start of the signal minute, before that minute invalidates zones. Touch includes crossing or gapping beyond the proximal edge; close-inside requires an inclusive close between proximal and distal. Exit fills next available minute open, never retrospectively at the zone price. No Pine percentage-risk sizing, margin liquidation or TradingView parity. |
| [Session VWAP reversion](../../strategies/vwap_reversion.py) | band, contracts | Ports s_vwap_rev decision state. Uses selected futures and next-open accounting; positions can carry across excluded-session gaps until the next available fill. Original ETF session returns differ. |
| [Wyckoff [theUltimator5] - NQ research](../../strategies/wyckoff_nq.py) | strictness, exit_policy, holding_bars, entry_delay_bars, atr_length, stop_atr, target_r | Research port of the indicator Auto entry checks, with one selected chart timeframe and no MTF override. Pivot labels are actionable only on their confirmation bar. One fixed NQ contract per entry. Fixed-bar exits, optional ATR brackets, and optional extra-bar entry delay are workbench research rules, not rules supplied by the Pine indicator. ATR bracket levels are anchored to the signal or delayed-decision close, not the actual next-open fill, so gaps can change realized R; bracket exits require separate qualification. Next-open fills, one-minute bracket execution, fees, slippage, session filtering, and final liquidation follow the workbench simulator. TradingView parity is not certified. |

## Original source inventory

Adapter links cover only the documented rules. Other variants within the same script still require migration.

| Source | Family | Role | Status | Workbench adapters |
| --- | --- | --- | --- | --- |
| [ninjatrader/build_selected_bundle.py](../../ninjatrader/build_selected_bundle.py) | Platform validation | Data utility | Supporting source | — |
| [ninjatrader/export_for_nt.py](../../ninjatrader/export_for_nt.py) | Platform validation | Data utility | Supporting source | — |
| [ninjatrader/prop_fit_check.py](../../ninjatrader/prop_fit_check.py) | Platform validation | Validation | Supporting source | — |
| [ninjatrader/sizing_check.py](../../ninjatrader/sizing_check.py) | Platform validation | Validation | Supporting source | — |
| [ninjatrader/tests/validate_orb_real_data.py](../../ninjatrader/tests/validate_orb_real_data.py) | Support | Support | Supporting source | — |
| [ninjatrader/tests/validate_reversal.py](../../ninjatrader/tests/validate_reversal.py) | Support | Support | Supporting source | — |
| [scripts/analyze-market-intraday-momentum.py](../../scripts/analyze-market-intraday-momentum.py) | Support | Support | Supporting source | — |
| [scripts/analyze-orb-exits.py](../../scripts/analyze-orb-exits.py) | Support | Support | Supporting source | — |
| [scripts/analyze-snd-combinations.py](../../scripts/analyze-snd-combinations.py) | Support | Support | Supporting source | — |
| [scripts/analyze-snd-zone-exit.py](../../scripts/analyze-snd-zone-exit.py) | Support | Support | Supporting source | — |
| [scripts/analyze-transcript-supply-demand.py](../../scripts/analyze-transcript-supply-demand.py) | Support | Support | Supporting source | — |
| [scripts/analyze-vwap-full.py](../../scripts/analyze-vwap-full.py) | Support | Support | Supporting source | — |
| [scripts/analyze-vwap-inverse.py](../../scripts/analyze-vwap-inverse.py) | Support | Support | Supporting source | — |
| [scripts/audit-htf-wick-results.py](../../scripts/audit-htf-wick-results.py) | Support | Support | Supporting source | — |
| [scripts/audit-nq-reversal-candidate.py](../../scripts/audit-nq-reversal-candidate.py) | Support | Support | Supporting source | — |
| [scripts/audit-pattern-recognition.py](../../scripts/audit-pattern-recognition.py) | Support | Support | Supporting source | — |
| [scripts/audit-snd-body-retest.py](../../scripts/audit-snd-body-retest.py) | Support | Support | Supporting source | — |
| [scripts/audit-snd-combination-validation.py](../../scripts/audit-snd-combination-validation.py) | Support | Support | Supporting source | — |
| [scripts/audit-snd-combinations.py](../../scripts/audit-snd-combinations.py) | Support | Support | Supporting source | — |
| [scripts/audit-snd-entry-research.py](../../scripts/audit-snd-entry-research.py) | Support | Support | Supporting source | — |
| [scripts/audit-snd-risk-research.py](../../scripts/audit-snd-risk-research.py) | Support | Support | Supporting source | — |
| [scripts/audit-snd-zone-quality.py](../../scripts/audit-snd-zone-quality.py) | Support | Support | Supporting source | — |
| [scripts/audit-tsmom-orb-calendar-results.py](../../scripts/audit-tsmom-orb-calendar-results.py) | Support | Support | Supporting source | — |
| [scripts/audit-workbench.py](../../scripts/audit-workbench.py) | Support | Support | Supporting source | — |
| [scripts/build-collective.py](../../scripts/build-collective.py) | Support | Data utility | Supporting source | — |
| [scripts/build-workbench-review.py](../../scripts/build-workbench-review.py) | Support | Data utility | Supporting source | — |
| [scripts/check-snd-combination-grid.py](../../scripts/check-snd-combination-grid.py) | Support | Support | Supporting source | — |
| [scripts/check-snd-combination-risk.py](../../scripts/check-snd-combination-risk.py) | Support | Support | Supporting source | — |
| [scripts/check-snd-combinations.py](../../scripts/check-snd-combinations.py) | Support | Support | Supporting source | — |
| [scripts/cme/cme_stats_report.py](../../scripts/cme/cme_stats_report.py) | Momentum and portfolios | Report | Supporting source | — |
| [scripts/cme/cme_time_series_momentum_backtest.py](../../scripts/cme/cme_time_series_momentum_backtest.py) | Momentum and portfolios | Strategy | Workbench adapter available | multi-speed-momentum, pine-daily-tsmom |
| [scripts/cme/commodity_xsec_momentum_backtest.py](../../scripts/cme/commodity_xsec_momentum_backtest.py) | Momentum and portfolios | Strategy | Adapter required | — |
| [scripts/cme/databento_fetch.py](../../scripts/cme/databento_fetch.py) | Momentum and portfolios | Data utility | Supporting source | — |
| [scripts/cme/factor_ls_backtest.py](../../scripts/cme/factor_ls_backtest.py) | Momentum and portfolios | Strategy | Adapter required | — |
| [scripts/cme/fetch_cme_data.py](../../scripts/cme/fetch_cme_data.py) | Momentum and portfolios | Data utility | Supporting source | — |
| [scripts/cme/short_horizon_backtest.py](../../scripts/cme/short_horizon_backtest.py) | Momentum and portfolios | Rule collection | Adapter required | — |
| [scripts/cme/trend_overnight_book_backtest.py](../../scripts/cme/trend_overnight_book_backtest.py) | Momentum and portfolios | Strategy | Adapter required | — |
| [scripts/cme/tsmom_intraday_orb_backtest.py](../../scripts/cme/tsmom_intraday_orb_backtest.py) | Momentum and portfolios | Strategy | Workbench adapter available | pine-tsmom-orb |
| [scripts/compare-mnq-overnight-ports.py](../../scripts/compare-mnq-overnight-ports.py) | Support | Support | Supporting source | — |
| [scripts/dashboard_compatible_strategy.py](../../scripts/dashboard_compatible_strategy.py) | Support | Support | Supporting source | — |
| [scripts/es_nq/es_nq_backtest.py](../../scripts/es_nq/es_nq_backtest.py) | Index signals | Strategy | Workbench adapter available | moving-average |
| [scripts/es_nq/es_nq_level_fill_backtest.py](../../scripts/es_nq/es_nq_level_fill_backtest.py) | Index signals | Strategy | Adapter required | — |
| [scripts/es_nq/es_nq_strategies.py](../../scripts/es_nq/es_nq_strategies.py) | Index signals | Rule collection | Workbench adapter available | buy-hold, moving-average, rsi2-reversion, rsi2-reversion-corrected |
| [scripts/es_nq/es_nq_terms.py](../../scripts/es_nq/es_nq_terms.py) | Index signals | Research study | Adapter required | — |
| [scripts/forward-snd-frozen.py](../../scripts/forward-snd-frozen.py) | Support | Support | Supporting source | — |
| [scripts/lucid/lucid_container_scan.py](../../scripts/lucid/lucid_container_scan.py) | Prop account studies | Research study | Adapter required | — |
| [scripts/lucid/lucid_prop_year_sim.py](../../scripts/lucid/lucid_prop_year_sim.py) | Prop account studies | Research study | Adapter required | — |
| [scripts/mgc/fetch_mgc_mcl_5m.py](../../scripts/mgc/fetch_mgc_mcl_5m.py) | Gold sessions | Data utility | Supporting source | — |
| [scripts/mgc/mgc_orb_carver_backtest.py](../../scripts/mgc/mgc_orb_carver_backtest.py) | Gold sessions | Strategy | Adapter required | — |
| [scripts/mgc/mgc_overnight_block_backtest.py](../../scripts/mgc/mgc_overnight_block_backtest.py) | Gold sessions | Strategy | Adapter required | — |
| [scripts/misc/report_server.py](../../scripts/misc/report_server.py) | Support | Report | Supporting source | — |
| [scripts/misc/smoke_test.py](../../scripts/misc/smoke_test.py) | Support | Validation | Supporting source | — |
| [scripts/mnq/build_mnq_timeframes.py](../../scripts/mnq/build_mnq_timeframes.py) | MNQ overnight variants | Data utility | Supporting source | — |
| [scripts/mnq/fetch_dom_sample.py](../../scripts/mnq/fetch_dom_sample.py) | MNQ overnight variants | Data utility | Supporting source | — |
| [scripts/mnq/mnq_asia_fill_strategy_backtest.py](../../scripts/mnq/mnq_asia_fill_strategy_backtest.py) | Asia gap fill | Strategy | Adapter required | — |
| [scripts/mnq/mnq_backtesting_py_crosscheck.py](../../scripts/mnq/mnq_backtesting_py_crosscheck.py) | MNQ overnight variants | Validation | Supporting source | — |
| [scripts/mnq/mnq_close_location_backtest.py](../../scripts/mnq/mnq_close_location_backtest.py) | MNQ overnight variants | Strategy | Adapter required | — |
| [scripts/mnq/mnq_exit_time_backtest.py](../../scripts/mnq/mnq_exit_time_backtest.py) | MNQ overnight variants | Strategy | Adapter required | — |
| [scripts/mnq/mnq_hard_stop_backtest.py](../../scripts/mnq/mnq_hard_stop_backtest.py) | MNQ overnight variants | Strategy | Adapter required | — |
| [scripts/mnq/mnq_hourly_drift_report.py](../../scripts/mnq/mnq_hourly_drift_report.py) | MNQ overnight variants | Report | Supporting source | — |
| [scripts/mnq/mnq_losing_nights_report.py](../../scripts/mnq/mnq_losing_nights_report.py) | MNQ overnight variants | Report | Supporting source | — |
| [scripts/mnq/mnq_market_profile_backtest.py](../../scripts/mnq/mnq_market_profile_backtest.py) | Market profile | Strategy | Adapter required | — |
| [scripts/mnq/mnq_ny_close_asia_fill_backtest.py](../../scripts/mnq/mnq_ny_close_asia_fill_backtest.py) | Asia gap fill | Research study | Adapter required | — |
| [scripts/mnq/mnq_oos_2015_backtest.py](../../scripts/mnq/mnq_oos_2015_backtest.py) | MNQ overnight variants | Strategy | Adapter required | — |
| [scripts/mnq/mnq_opening_trend_pullback_backtest.py](../../scripts/mnq/mnq_opening_trend_pullback_backtest.py) | Opening range | Strategy | Adapter required | — |
| [scripts/mnq/mnq_optimal_stop_search.py](../../scripts/mnq/mnq_optimal_stop_search.py) | MNQ overnight variants | Rule collection | Adapter required | — |
| [scripts/mnq/mnq_orb_2026_review.py](../../scripts/mnq/mnq_orb_2026_review.py) | Opening range | Rule collection | Adapter required | — |
| [scripts/mnq/mnq_orb_recency.py](../../scripts/mnq/mnq_orb_recency.py) | Opening range | Rule collection | Adapter required | — |
| [scripts/mnq/mnq_orb_stats_report.py](../../scripts/mnq/mnq_orb_stats_report.py) | Opening range | Report | Supporting source | — |
| [scripts/mnq/mnq_overnight_drift_backtest.py](../../scripts/mnq/mnq_overnight_drift_backtest.py) | MNQ overnight variants | Strategy | Adapter required | — |
| [scripts/mnq/mnq_overnight_drift_dashboard.py](../../scripts/mnq/mnq_overnight_drift_dashboard.py) | MNQ overnight variants | Report | Supporting source | — |
| [scripts/mnq/mnq_overnight_giveback_report.py](../../scripts/mnq/mnq_overnight_giveback_report.py) | MNQ overnight variants | Report | Supporting source | — |
| [scripts/mnq/mnq_rr_stop_backtest.py](../../scripts/mnq/mnq_rr_stop_backtest.py) | MNQ overnight variants | Strategy | Adapter required | — |
| [scripts/mnq/mnq_scenario_grid.py](../../scripts/mnq/mnq_scenario_grid.py) | MNQ overnight variants | Rule collection | Adapter required | — |
| [scripts/mnq/mnq_tail_exclusion_report.py](../../scripts/mnq/mnq_tail_exclusion_report.py) | MNQ overnight variants | Report | Supporting source | — |
| [scripts/mnq/mnq_takeprofit_backtest.py](../../scripts/mnq/mnq_takeprofit_backtest.py) | MNQ overnight variants | Strategy | Adapter required | — |
| [scripts/mnq/mnq_time_block_backtest.py](../../scripts/mnq/mnq_time_block_backtest.py) | MNQ overnight variants | Strategy | Workbench adapter available | pine-overnight-block |
| [scripts/mnq/mnq_trailing_stop_backtest.py](../../scripts/mnq/mnq_trailing_stop_backtest.py) | MNQ overnight variants | Strategy | Adapter required | — |
| [scripts/mnq/mnq_weekday_backtest.py](../../scripts/mnq/mnq_weekday_backtest.py) | MNQ overnight variants | Strategy | Adapter required | — |
| [scripts/mnq/mnq_window_scan_backtest.py](../../scripts/mnq/mnq_window_scan_backtest.py) | MNQ overnight variants | Rule collection | Workbench adapter available | pine-overnight-block |
| [scripts/mnq/SND_baseline_backtest.py](../../scripts/mnq/SND_baseline_backtest.py) | Supply and demand | Strategy | Workbench adapter available | snd |
| [scripts/mnq/SND_html_report.py](../../scripts/mnq/SND_html_report.py) | Supply and demand | Report | Supporting source | — |
| [scripts/mnq/SND_phase2_dataset.py](../../scripts/mnq/SND_phase2_dataset.py) | Supply and demand | Data utility | Supporting source | — |
| [scripts/mnq/SND_phase3_screen.py](../../scripts/mnq/SND_phase3_screen.py) | Supply and demand | Research study | Adapter required | — |
| [scripts/mnq/SND_phase4_backtest.py](../../scripts/mnq/SND_phase4_backtest.py) | Supply and demand | Rule collection | Workbench adapter available | snd |
| [scripts/mnq/SND_phase5_combinations.py](../../scripts/mnq/SND_phase5_combinations.py) | Supply and demand | Rule collection | Adapter required | — |
| [scripts/mnq/SND_phase6_forward_check.py](../../scripts/mnq/SND_phase6_forward_check.py) | Supply and demand | Validation | Supporting source | — |
| [scripts/mnq/SND_phase6_parity.py](../../scripts/mnq/SND_phase6_parity.py) | Supply and demand | Validation | Supporting source | — |
| [scripts/mnq/SND_phase6_release.py](../../scripts/mnq/SND_phase6_release.py) | Supply and demand | Validation | Supporting source | — |
| [scripts/mnq/SND_phase6_strategy_parity.py](../../scripts/mnq/SND_phase6_strategy_parity.py) | Supply and demand | Validation | Supporting source | — |
| [scripts/mnq/SND_phase7_relative_volume.py](../../scripts/mnq/SND_phase7_relative_volume.py) | Supply and demand | Rule collection | Workbench adapter available | snd |
| [scripts/mnq/verify_dom_sample.py](../../scripts/mnq/verify_dom_sample.py) | MNQ overnight variants | Validation | Supporting source | — |
| [scripts/orb/orb_asia_carver_backtest.py](../../scripts/orb/orb_asia_carver_backtest.py) | Opening range | Strategy | Adapter required | — |
| [scripts/orb/orb_backtest.py](../../scripts/orb/orb_backtest.py) | Opening range | Strategy | Adapter required | — |
| [scripts/orb/orb_carver_backtest.py](../../scripts/orb/orb_carver_backtest.py) | Opening range | Strategy | Adapter required | — |
| [scripts/orb/orb_playbook.py](../../scripts/orb/orb_playbook.py) | Opening range | Report | Supporting source | — |
| [scripts/overnight/futures_overnight_backtest.py](../../scripts/overnight/futures_overnight_backtest.py) | Overnight | Strategy | Adapter required | — |
| [scripts/overnight/mes_overnight_drift_backtest.py](../../scripts/overnight/mes_overnight_drift_backtest.py) | Overnight | Strategy | Adapter required | — |
| [scripts/overnight/overnight_best_backtest.py](../../scripts/overnight/overnight_best_backtest.py) | Overnight | Strategy | Adapter required | — |
| [scripts/overnight/overnight_bracket_backtest.py](../../scripts/overnight/overnight_bracket_backtest.py) | Overnight | Strategy | Adapter required | — |
| [scripts/overnight/overnight_conditional_backtest.py](../../scripts/overnight/overnight_conditional_backtest.py) | Overnight | Strategy | Adapter required | — |
| [scripts/overnight/overnight_drift_backtest.py](../../scripts/overnight/overnight_drift_backtest.py) | Overnight | Strategy | Workbench adapter available | pine-overnight-drift |
| [scripts/overnight/overnight_drift_carver_backtest.py](../../scripts/overnight/overnight_drift_carver_backtest.py) | Overnight | Strategy | Adapter required | — |
| [scripts/overnight/overnight_filtered_backtest.py](../../scripts/overnight/overnight_filtered_backtest.py) | Overnight | Strategy | Adapter required | — |
| [scripts/overnight/overnight_loss_profile.py](../../scripts/overnight/overnight_loss_profile.py) | Overnight | Report | Supporting source | — |
| [scripts/plot-transcript-supply-demand.py](../../scripts/plot-transcript-supply-demand.py) | Support | Support | Supporting source | — |
| [scripts/preflight-nq-reversal-minute.py](../../scripts/preflight-nq-reversal-minute.py) | Support | Support | Supporting source | — |
| [scripts/prepare-htf-wick-inputs.py](../../scripts/prepare-htf-wick-inputs.py) | Support | Support | Supporting source | — |
| [scripts/refresh-expanded-overnight-es-nq.py](../../scripts/refresh-expanded-overnight-es-nq.py) | Support | Support | Supporting source | — |
| [scripts/refresh-workbench-es-nq.py](../../scripts/refresh-workbench-es-nq.py) | Support | Support | Supporting source | — |
| [scripts/register-mnq-workbench.py](../../scripts/register-mnq-workbench.py) | Support | Support | Supporting source | — |
| [scripts/replay-vwap-recent.py](../../scripts/replay-vwap-recent.py) | Support | Support | Supporting source | — |
| [scripts/report-snd-body-retest.py](../../scripts/report-snd-body-retest.py) | Support | Report | Supporting source | — |
| [scripts/report-snd-entry-research.py](../../scripts/report-snd-entry-research.py) | Support | Report | Supporting source | — |
| [scripts/report-snd-fresh-retest.py](../../scripts/report-snd-fresh-retest.py) | Support | Report | Supporting source | — |
| [scripts/report-snd-risk-research.py](../../scripts/report-snd-risk-research.py) | Support | Report | Supporting source | — |
| [scripts/report-snd-zone-quality.py](../../scripts/report-snd-zone-quality.py) | Support | Report | Supporting source | — |
| [scripts/report-transcript-supply-demand.py](../../scripts/report-transcript-supply-demand.py) | Support | Report | Supporting source | — |
| [scripts/research-htf-wick-phases.py](../../scripts/research-htf-wick-phases.py) | Support | Support | Supporting source | — |
| [scripts/research-snd-body-retest.py](../../scripts/research-snd-body-retest.py) | Support | Support | Supporting source | — |
| [scripts/research-snd-combinations.py](../../scripts/research-snd-combinations.py) | Support | Support | Supporting source | — |
| [scripts/research-snd-entry-research.py](../../scripts/research-snd-entry-research.py) | Support | Support | Supporting source | — |
| [scripts/research-snd-fresh-retest.py](../../scripts/research-snd-fresh-retest.py) | Support | Support | Supporting source | — |
| [scripts/research-snd-risk-research.py](../../scripts/research-snd-risk-research.py) | Support | Support | Supporting source | — |
| [scripts/research-snd-zone-quality.py](../../scripts/research-snd-zone-quality.py) | Support | Support | Supporting source | — |
| [scripts/spy_qqq_intraday/build_intraday.py](../../scripts/spy_qqq_intraday/build_intraday.py) | ETF intraday | Data utility | Supporting source | — |
| [scripts/spy_qqq_intraday/fetch_intraday.py](../../scripts/spy_qqq_intraday/fetch_intraday.py) | ETF intraday | Data utility | Supporting source | — |
| [scripts/spy_qqq_intraday/intraday_bakeoff.py](../../scripts/spy_qqq_intraday/intraday_bakeoff.py) | ETF intraday | Rule collection | Workbench adapter available | buy-hold, vwap-reversion |
| [scripts/spy_qqq_intraday/intraday_strategy_screen.py](../../scripts/spy_qqq_intraday/intraday_strategy_screen.py) | ETF intraday | Rule collection | Adapter required | — |
| [scripts/spy_qqq_intraday/pdh_pdl_range_backtest.py](../../scripts/spy_qqq_intraday/pdh_pdl_range_backtest.py) | ETF intraday | Strategy | Workbench adapter available | buy-hold |
| [scripts/spy_qqq_intraday/probe_map.py](../../scripts/spy_qqq_intraday/probe_map.py) | ETF intraday | Data utility | Supporting source | — |
| [scripts/spy_qqq_intraday/probe_order.py](../../scripts/spy_qqq_intraday/probe_order.py) | ETF intraday | Data utility | Supporting source | — |
| [scripts/spy_qqq_intraday/probe_shards.py](../../scripts/spy_qqq_intraday/probe_shards.py) | ETF intraday | Data utility | Supporting source | — |
| [scripts/spy_qqq_intraday/spy_qqq_pairs_backtest.py](../../scripts/spy_qqq_intraday/spy_qqq_pairs_backtest.py) | ETF intraday | Strategy | Adapter required | — |
| [scripts/summarize-snd-combination-factors.py](../../scripts/summarize-snd-combination-factors.py) | Support | Support | Supporting source | — |
| [scripts/supplement-snd-combination-zero-trade-audit.py](../../scripts/supplement-snd-combination-zero-trade-audit.py) | Support | Support | Supporting source | — |
| [scripts/update-es-databento.py](../../scripts/update-es-databento.py) | Support | Support | Supporting source | — |
| [scripts/update-nq-databento.py](../../scripts/update-nq-databento.py) | Support | Support | Supporting source | — |
| [scripts/validate-snd-combinations.py](../../scripts/validate-snd-combinations.py) | Support | Support | Supporting source | — |
| [scripts/validate-snd-reference.py](../../scripts/validate-snd-reference.py) | Support | Support | Supporting source | — |
| [scripts/verify-vwap-inverse.py](../../scripts/verify-vwap-inverse.py) | Support | Validation | Supporting source | — |
| [scripts/wyckoff_matched_control.py](../../scripts/wyckoff_matched_control.py) | Support | Support | Supporting source | — |
| [scripts/wyckoff_nq_campaign.py](../../scripts/wyckoff_nq_campaign.py) | Support | Support | Supporting source | — |
| [scripts/wyckoff_nq_expansion.py](../../scripts/wyckoff_nq_expansion.py) | Support | Support | Supporting source | — |
| [scripts/wyckoff_nq_followup.py](../../scripts/wyckoff_nq_followup.py) | Support | Support | Supporting source | — |
| [strategy_engine/strategies/opening_range_breakout.py](../../strategy_engine/strategies/opening_range_breakout.py) | Canonical engine | Strategy | Adapter required | — |
| [strategy_engine/strategies/prior_range_fill.py](../../strategy_engine/strategies/prior_range_fill.py) | Canonical engine | Strategy | Adapter required | — |
| [strategy_engine/strategies/relative_value.py](../../strategy_engine/strategies/relative_value.py) | Canonical engine | Strategy | Adapter required | — |
| [strategy_engine/strategies/session_drift.py](../../strategy_engine/strategies/session_drift.py) | Canonical engine | Strategy | Adapter required | — |
| [strategy_engine/strategies/trend.py](../../strategy_engine/strategies/trend.py) | Canonical engine | Strategy | Workbench adapter available | moving-average, multi-speed-momentum |
| [pine/cme_tsmom_intraday_orb_strategy.pine](../../pine/cme_tsmom_intraday_orb_strategy.pine) | Pine strategies | Pine strategy | Python port available | pine-tsmom-orb |
| [pine/cme_tsmom_manual_indicator.pine](../../pine/cme_tsmom_manual_indicator.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/cme_tsmom_single_market_strategy.pine](../../pine/cme_tsmom_single_market_strategy.pine) | Pine strategies | Pine strategy | Python port available | pine-daily-tsmom |
| [pine/factor_score_indicator.pine](../../pine/factor_score_indicator.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/gap_fill.pine](../../pine/gap_fill.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/ib.pine](../../pine/ib.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/market_sessions.pine](../../pine/market_sessions.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/orb.pine](../../pine/orb.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/orb_carver.pine](../../pine/orb_carver.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/overnight_block_indicator.pine](../../pine/overnight_block_indicator.pine) | Pine indicators | Pine indicator | Python port available | pine-overnight-block |
| [pine/overnight_block_strategy.pine](../../pine/overnight_block_strategy.pine) | Pine strategies | Pine strategy | Python port available | pine-overnight-block |
| [pine/overnight_drift_strategy.pine](../../pine/overnight_drift_strategy.pine) | Pine strategies | Pine strategy | Python port available | pine-overnight-drift |
| [pine/overnight_hl.pine](../../pine/overnight_hl.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/prior_levels.pine](../../pine/prior_levels.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/snd_fresh_retest_zones.pine](../../pine/snd_fresh_retest_zones.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/snd_reference_zone_guide.pine](../../pine/snd_reference_zone_guide.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/transcript_supply_demand_indicator.pine](../../pine/transcript_supply_demand_indicator.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/vwap_bands.pine](../../pine/vwap_bands.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/wyckoff_theultimator5.pine](../../pine/wyckoff_theultimator5.pine) | Pine indicators | Pine indicator | Python port available | wyckoff-nq |
| [SND.pine](../../SND.pine) | Pine indicators | Pine indicator | Python port available | snd |
| [SND_phase6_strategy.pine](../../SND_phase6_strategy.pine) | Pine strategies | Pine strategy | Python port available | snd |

## Remaining execution contracts

- Intrabar strategies: preserve stop/limit ordering, gap handling, deadlines, and sizing; the current signal runner only fills at the next bar open.
- Multi-instrument strategies: require synchronized legs and portfolio accounting.
- Factor and ETF strategies: require their original inputs. The four normalized futures ZIP datasets are not substitutes.
- Research studies: require their original selection, resampling, and report workflows in addition to signal rules.

The Scripts page shows per-source requirements, source hashes, original documentation, functions, and CLI declarations.
Refresh this report with `python -m workbench.library --output docs/workbench/STRATEGY_LIBRARY.md`.
