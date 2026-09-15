# Consolidated strategy library

Generated from local Python and Pine source using static parsing; discovery does not execute scripts.

108 Python and Pine sources; 9 runnable workbench adapters.

## Runnable adapters

| Strategy | Parameters | Migration scope |
| --- | --- | --- |
| [Buy and hold benchmark](strategies/buy_hold.py) | contracts | Consolidates the passive long benchmark only. Fixed futures contracts with explicit entry/exit costs replace the original proxy-return benchmark. |
| [Moving-average trend](strategies/moving_average.py) | lookback, contracts | Consolidates long/flat moving-average decisions. Original cash-index portfolios and notional-return accounting are not reproduced. |
| [Multi-speed momentum](strategies/multi_speed_momentum.py) | lookback, contracts | Uses the canonical engine four-speed signal. Original CME proxy portfolio, lookbacks, volatility sizing, and NAV accounting are not reproduced. |
| [Pine · Daily TSMOM rebalance](strategies/pine_daily_tsmom.py) | fast_length, medium_length, slow_length, annual_length, sizing_mode, contracts, annual_risk, maximum_leverage, volatility_length, sleeve_count, rounding | Historical Pine decision/timing port. Daily bars and signal use the selected futures dataset, not a separate signal symbol or TradingView settlement feed. Whole contracts; no TradingView margin-call emulation. Live request.security repaint behavior is not reproduced. |
| [Pine · Overnight block](strategies/pine_overnight_block.py) | entry_hour, entry_minute, exit_hour, exit_minute, contracts, timezone | Ports the Pine clock/order rules, including boundary-only entries. Scoring starts flat; no entry midway through an existing hold window. Costs and contract economics use the run inputs. |
| [Pine · Filtered overnight drift](strategies/pine_overnight_drift.py) | sizing_mode, contracts, annual_risk, maximum_leverage, volatility_length, sleeve_count, timezone, rth_start, rth_end, trade_weekend, close_rule, strong_threshold | Preserves actual Pine bar-close timing, which differs from the header's ideal RTH-close/RTH-open trades. Uses selected-dataset daily prices and economics; no TradingView margin-call simulation. |
| [Pine · TSMOM intraday ORB](strategies/pine_tsmom_orb.py) | fast_length, medium_length, slow_length, annual_length, timezone, minimum_score, opening_start, opening_end, entry_start, entry_end, flatten_start, flatten_end, risk_budget, maximum_contracts, reward_risk, require_close_break | Pine rules port with one-minute bracket execution. Stop wins ties within a minute; gap fills use the opening price. No TradingView sub-minute Bar Magnifier or order-fill recalculation emulation. A rejected risk-sized attempt still consumes the session. |
| [RSI(2) trend-filtered reversion](strategies/rsi2_reversion.py) | trend_lookback, entry_rsi, exit_rsi, contracts | Ports s_rsi2 decisions, including its zero-loss RSI convention. Uses selected futures, fixed whole contracts and next-open fills; original cash-index NAV differs. |
| [Session VWAP reversion](strategies/vwap_reversion.py) | band, contracts | Ports s_vwap_rev decision state. Uses selected futures and next-open accounting; positions can carry across excluded-session gaps until the next available fill. Original ETF session returns differ. |

## Original source inventory

Adapter links cover only the documented rules. Other variants within the same script still require migration.

| Source | Family | Role | Status | Workbench adapters |
| --- | --- | --- | --- | --- |
| [ninjatrader/export_for_nt.py](ninjatrader/export_for_nt.py) | Platform validation | Data utility | Supporting source | — |
| [ninjatrader/prop_fit_check.py](ninjatrader/prop_fit_check.py) | Platform validation | Validation | Supporting source | — |
| [ninjatrader/sizing_check.py](ninjatrader/sizing_check.py) | Platform validation | Validation | Supporting source | — |
| [scripts/cme/cme_stats_report.py](scripts/cme/cme_stats_report.py) | Momentum and portfolios | Report | Supporting source | — |
| [scripts/cme/cme_time_series_momentum_backtest.py](scripts/cme/cme_time_series_momentum_backtest.py) | Momentum and portfolios | Strategy | Workbench adapter available | multi-speed-momentum, pine-daily-tsmom |
| [scripts/cme/commodity_xsec_momentum_backtest.py](scripts/cme/commodity_xsec_momentum_backtest.py) | Momentum and portfolios | Strategy | Adapter required | — |
| [scripts/cme/databento_fetch.py](scripts/cme/databento_fetch.py) | Momentum and portfolios | Data utility | Supporting source | — |
| [scripts/cme/factor_ls_backtest.py](scripts/cme/factor_ls_backtest.py) | Momentum and portfolios | Strategy | Adapter required | — |
| [scripts/cme/fetch_cme_data.py](scripts/cme/fetch_cme_data.py) | Momentum and portfolios | Data utility | Supporting source | — |
| [scripts/cme/short_horizon_backtest.py](scripts/cme/short_horizon_backtest.py) | Momentum and portfolios | Rule collection | Adapter required | — |
| [scripts/cme/trend_overnight_book_backtest.py](scripts/cme/trend_overnight_book_backtest.py) | Momentum and portfolios | Strategy | Adapter required | — |
| [scripts/cme/tsmom_intraday_orb_backtest.py](scripts/cme/tsmom_intraday_orb_backtest.py) | Momentum and portfolios | Strategy | Workbench adapter available | pine-tsmom-orb |
| [scripts/dashboard_compatible_strategy.py](scripts/dashboard_compatible_strategy.py) | Support | Support | Supporting source | — |
| [scripts/es_nq/es_nq_backtest.py](scripts/es_nq/es_nq_backtest.py) | Index signals | Strategy | Workbench adapter available | moving-average |
| [scripts/es_nq/es_nq_level_fill_backtest.py](scripts/es_nq/es_nq_level_fill_backtest.py) | Index signals | Strategy | Adapter required | — |
| [scripts/es_nq/es_nq_strategies.py](scripts/es_nq/es_nq_strategies.py) | Index signals | Rule collection | Workbench adapter available | buy-hold, moving-average, rsi2-reversion |
| [scripts/es_nq/es_nq_terms.py](scripts/es_nq/es_nq_terms.py) | Index signals | Research study | Adapter required | — |
| [scripts/lucid/lucid_container_scan.py](scripts/lucid/lucid_container_scan.py) | Prop account studies | Research study | Adapter required | — |
| [scripts/lucid/lucid_prop_year_sim.py](scripts/lucid/lucid_prop_year_sim.py) | Prop account studies | Research study | Adapter required | — |
| [scripts/mgc/fetch_mgc_mcl_5m.py](scripts/mgc/fetch_mgc_mcl_5m.py) | Gold sessions | Data utility | Supporting source | — |
| [scripts/mgc/mgc_orb_carver_backtest.py](scripts/mgc/mgc_orb_carver_backtest.py) | Gold sessions | Strategy | Adapter required | — |
| [scripts/mgc/mgc_overnight_block_backtest.py](scripts/mgc/mgc_overnight_block_backtest.py) | Gold sessions | Strategy | Adapter required | — |
| [scripts/misc/report_server.py](scripts/misc/report_server.py) | Support | Report | Supporting source | — |
| [scripts/misc/smoke_test.py](scripts/misc/smoke_test.py) | Support | Validation | Supporting source | — |
| [scripts/mnq/build_mnq_timeframes.py](scripts/mnq/build_mnq_timeframes.py) | MNQ overnight variants | Data utility | Supporting source | — |
| [scripts/mnq/fetch_dom_sample.py](scripts/mnq/fetch_dom_sample.py) | MNQ overnight variants | Data utility | Supporting source | — |
| [scripts/mnq/mnq_asia_fill_strategy_backtest.py](scripts/mnq/mnq_asia_fill_strategy_backtest.py) | Asia gap fill | Strategy | Adapter required | — |
| [scripts/mnq/mnq_backtesting_py_crosscheck.py](scripts/mnq/mnq_backtesting_py_crosscheck.py) | MNQ overnight variants | Validation | Supporting source | — |
| [scripts/mnq/mnq_close_location_backtest.py](scripts/mnq/mnq_close_location_backtest.py) | MNQ overnight variants | Strategy | Adapter required | — |
| [scripts/mnq/mnq_exit_time_backtest.py](scripts/mnq/mnq_exit_time_backtest.py) | MNQ overnight variants | Strategy | Adapter required | — |
| [scripts/mnq/mnq_hard_stop_backtest.py](scripts/mnq/mnq_hard_stop_backtest.py) | MNQ overnight variants | Strategy | Adapter required | — |
| [scripts/mnq/mnq_hourly_drift_report.py](scripts/mnq/mnq_hourly_drift_report.py) | MNQ overnight variants | Report | Supporting source | — |
| [scripts/mnq/mnq_losing_nights_report.py](scripts/mnq/mnq_losing_nights_report.py) | MNQ overnight variants | Report | Supporting source | — |
| [scripts/mnq/mnq_market_profile_backtest.py](scripts/mnq/mnq_market_profile_backtest.py) | Market profile | Strategy | Adapter required | — |
| [scripts/mnq/mnq_ny_close_asia_fill_backtest.py](scripts/mnq/mnq_ny_close_asia_fill_backtest.py) | Asia gap fill | Research study | Adapter required | — |
| [scripts/mnq/mnq_oos_2015_backtest.py](scripts/mnq/mnq_oos_2015_backtest.py) | MNQ overnight variants | Strategy | Adapter required | — |
| [scripts/mnq/mnq_opening_trend_pullback_backtest.py](scripts/mnq/mnq_opening_trend_pullback_backtest.py) | Opening range | Strategy | Adapter required | — |
| [scripts/mnq/mnq_optimal_stop_search.py](scripts/mnq/mnq_optimal_stop_search.py) | MNQ overnight variants | Rule collection | Adapter required | — |
| [scripts/mnq/mnq_orb_2026_review.py](scripts/mnq/mnq_orb_2026_review.py) | Opening range | Rule collection | Adapter required | — |
| [scripts/mnq/mnq_orb_recency.py](scripts/mnq/mnq_orb_recency.py) | Opening range | Rule collection | Adapter required | — |
| [scripts/mnq/mnq_orb_stats_report.py](scripts/mnq/mnq_orb_stats_report.py) | Opening range | Report | Supporting source | — |
| [scripts/mnq/mnq_overnight_drift_backtest.py](scripts/mnq/mnq_overnight_drift_backtest.py) | MNQ overnight variants | Strategy | Adapter required | — |
| [scripts/mnq/mnq_overnight_drift_dashboard.py](scripts/mnq/mnq_overnight_drift_dashboard.py) | MNQ overnight variants | Report | Supporting source | — |
| [scripts/mnq/mnq_overnight_giveback_report.py](scripts/mnq/mnq_overnight_giveback_report.py) | MNQ overnight variants | Report | Supporting source | — |
| [scripts/mnq/mnq_rr_stop_backtest.py](scripts/mnq/mnq_rr_stop_backtest.py) | MNQ overnight variants | Strategy | Adapter required | — |
| [scripts/mnq/mnq_scenario_grid.py](scripts/mnq/mnq_scenario_grid.py) | MNQ overnight variants | Rule collection | Adapter required | — |
| [scripts/mnq/mnq_tail_exclusion_report.py](scripts/mnq/mnq_tail_exclusion_report.py) | MNQ overnight variants | Report | Supporting source | — |
| [scripts/mnq/mnq_takeprofit_backtest.py](scripts/mnq/mnq_takeprofit_backtest.py) | MNQ overnight variants | Strategy | Adapter required | — |
| [scripts/mnq/mnq_time_block_backtest.py](scripts/mnq/mnq_time_block_backtest.py) | MNQ overnight variants | Strategy | Workbench adapter available | pine-overnight-block |
| [scripts/mnq/mnq_trailing_stop_backtest.py](scripts/mnq/mnq_trailing_stop_backtest.py) | MNQ overnight variants | Strategy | Adapter required | — |
| [scripts/mnq/mnq_weekday_backtest.py](scripts/mnq/mnq_weekday_backtest.py) | MNQ overnight variants | Strategy | Adapter required | — |
| [scripts/mnq/mnq_window_scan_backtest.py](scripts/mnq/mnq_window_scan_backtest.py) | MNQ overnight variants | Rule collection | Workbench adapter available | pine-overnight-block |
| [scripts/mnq/SND_baseline_backtest.py](scripts/mnq/SND_baseline_backtest.py) | Supply and demand | Strategy | Adapter required | — |
| [scripts/mnq/SND_html_report.py](scripts/mnq/SND_html_report.py) | Supply and demand | Report | Supporting source | — |
| [scripts/mnq/SND_phase2_dataset.py](scripts/mnq/SND_phase2_dataset.py) | Supply and demand | Data utility | Supporting source | — |
| [scripts/mnq/SND_phase3_screen.py](scripts/mnq/SND_phase3_screen.py) | Supply and demand | Research study | Adapter required | — |
| [scripts/mnq/SND_phase4_backtest.py](scripts/mnq/SND_phase4_backtest.py) | Supply and demand | Rule collection | Adapter required | — |
| [scripts/mnq/SND_phase5_combinations.py](scripts/mnq/SND_phase5_combinations.py) | Supply and demand | Rule collection | Adapter required | — |
| [scripts/mnq/SND_phase6_forward_check.py](scripts/mnq/SND_phase6_forward_check.py) | Supply and demand | Validation | Supporting source | — |
| [scripts/mnq/SND_phase6_parity.py](scripts/mnq/SND_phase6_parity.py) | Supply and demand | Validation | Supporting source | — |
| [scripts/mnq/SND_phase6_release.py](scripts/mnq/SND_phase6_release.py) | Supply and demand | Validation | Supporting source | — |
| [scripts/mnq/SND_phase6_strategy_parity.py](scripts/mnq/SND_phase6_strategy_parity.py) | Supply and demand | Validation | Supporting source | — |
| [scripts/mnq/SND_phase7_relative_volume.py](scripts/mnq/SND_phase7_relative_volume.py) | Supply and demand | Rule collection | Adapter required | — |
| [scripts/mnq/verify_dom_sample.py](scripts/mnq/verify_dom_sample.py) | MNQ overnight variants | Validation | Supporting source | — |
| [scripts/orb/orb_asia_carver_backtest.py](scripts/orb/orb_asia_carver_backtest.py) | Opening range | Strategy | Adapter required | — |
| [scripts/orb/orb_backtest.py](scripts/orb/orb_backtest.py) | Opening range | Strategy | Adapter required | — |
| [scripts/orb/orb_carver_backtest.py](scripts/orb/orb_carver_backtest.py) | Opening range | Strategy | Adapter required | — |
| [scripts/orb/orb_playbook.py](scripts/orb/orb_playbook.py) | Opening range | Report | Supporting source | — |
| [scripts/overnight/futures_overnight_backtest.py](scripts/overnight/futures_overnight_backtest.py) | Overnight | Strategy | Adapter required | — |
| [scripts/overnight/mes_overnight_drift_backtest.py](scripts/overnight/mes_overnight_drift_backtest.py) | Overnight | Strategy | Adapter required | — |
| [scripts/overnight/overnight_best_backtest.py](scripts/overnight/overnight_best_backtest.py) | Overnight | Strategy | Adapter required | — |
| [scripts/overnight/overnight_bracket_backtest.py](scripts/overnight/overnight_bracket_backtest.py) | Overnight | Strategy | Adapter required | — |
| [scripts/overnight/overnight_conditional_backtest.py](scripts/overnight/overnight_conditional_backtest.py) | Overnight | Strategy | Adapter required | — |
| [scripts/overnight/overnight_drift_backtest.py](scripts/overnight/overnight_drift_backtest.py) | Overnight | Strategy | Workbench adapter available | pine-overnight-drift |
| [scripts/overnight/overnight_drift_carver_backtest.py](scripts/overnight/overnight_drift_carver_backtest.py) | Overnight | Strategy | Adapter required | — |
| [scripts/overnight/overnight_filtered_backtest.py](scripts/overnight/overnight_filtered_backtest.py) | Overnight | Strategy | Adapter required | — |
| [scripts/overnight/overnight_loss_profile.py](scripts/overnight/overnight_loss_profile.py) | Overnight | Report | Supporting source | — |
| [scripts/spy_qqq_intraday/build_intraday.py](scripts/spy_qqq_intraday/build_intraday.py) | ETF intraday | Data utility | Supporting source | — |
| [scripts/spy_qqq_intraday/fetch_intraday.py](scripts/spy_qqq_intraday/fetch_intraday.py) | ETF intraday | Data utility | Supporting source | — |
| [scripts/spy_qqq_intraday/intraday_bakeoff.py](scripts/spy_qqq_intraday/intraday_bakeoff.py) | ETF intraday | Rule collection | Workbench adapter available | buy-hold, vwap-reversion |
| [scripts/spy_qqq_intraday/intraday_strategy_screen.py](scripts/spy_qqq_intraday/intraday_strategy_screen.py) | ETF intraday | Rule collection | Adapter required | — |
| [scripts/spy_qqq_intraday/pdh_pdl_range_backtest.py](scripts/spy_qqq_intraday/pdh_pdl_range_backtest.py) | ETF intraday | Strategy | Workbench adapter available | buy-hold |
| [scripts/spy_qqq_intraday/probe_map.py](scripts/spy_qqq_intraday/probe_map.py) | ETF intraday | Data utility | Supporting source | — |
| [scripts/spy_qqq_intraday/probe_order.py](scripts/spy_qqq_intraday/probe_order.py) | ETF intraday | Data utility | Supporting source | — |
| [scripts/spy_qqq_intraday/probe_shards.py](scripts/spy_qqq_intraday/probe_shards.py) | ETF intraday | Data utility | Supporting source | — |
| [scripts/spy_qqq_intraday/spy_qqq_pairs_backtest.py](scripts/spy_qqq_intraday/spy_qqq_pairs_backtest.py) | ETF intraday | Strategy | Adapter required | — |
| [strategy_engine/strategies/opening_range_breakout.py](strategy_engine/strategies/opening_range_breakout.py) | Canonical engine | Strategy | Adapter required | — |
| [strategy_engine/strategies/prior_range_fill.py](strategy_engine/strategies/prior_range_fill.py) | Canonical engine | Strategy | Adapter required | — |
| [strategy_engine/strategies/relative_value.py](strategy_engine/strategies/relative_value.py) | Canonical engine | Strategy | Adapter required | — |
| [strategy_engine/strategies/session_drift.py](strategy_engine/strategies/session_drift.py) | Canonical engine | Strategy | Adapter required | — |
| [strategy_engine/strategies/trend.py](strategy_engine/strategies/trend.py) | Canonical engine | Strategy | Workbench adapter available | moving-average, multi-speed-momentum |
| [pine/cme_tsmom_intraday_orb_strategy.pine](pine/cme_tsmom_intraday_orb_strategy.pine) | Pine strategies | Pine strategy | Python port available | pine-tsmom-orb |
| [pine/cme_tsmom_manual_indicator.pine](pine/cme_tsmom_manual_indicator.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/cme_tsmom_single_market_strategy.pine](pine/cme_tsmom_single_market_strategy.pine) | Pine strategies | Pine strategy | Python port available | pine-daily-tsmom |
| [pine/factor_score_indicator.pine](pine/factor_score_indicator.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/gap_fill.pine](pine/gap_fill.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/ib.pine](pine/ib.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/market_sessions.pine](pine/market_sessions.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/orb.pine](pine/orb.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/orb_carver.pine](pine/orb_carver.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/overnight_block_indicator.pine](pine/overnight_block_indicator.pine) | Pine indicators | Pine indicator | Python port available | pine-overnight-block |
| [pine/overnight_block_strategy.pine](pine/overnight_block_strategy.pine) | Pine strategies | Pine strategy | Python port available | pine-overnight-block |
| [pine/overnight_drift_strategy.pine](pine/overnight_drift_strategy.pine) | Pine strategies | Pine strategy | Python port available | pine-overnight-drift |
| [pine/overnight_hl.pine](pine/overnight_hl.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/prior_levels.pine](pine/prior_levels.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [pine/vwap_bands.pine](pine/vwap_bands.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [SND.pine](SND.pine) | Pine indicators | Pine indicator | Indicator only | — |
| [SND_phase6_strategy.pine](SND_phase6_strategy.pine) | Pine strategies | Pine strategy | Existing Python engine | — |

## Remaining execution contracts

- Intrabar strategies: preserve stop/limit ordering, gap handling, deadlines, and sizing; the current signal runner only fills at the next bar open.
- Multi-instrument strategies: require synchronized legs and portfolio accounting.
- Factor and ETF strategies: require their original inputs. The four normalized futures ZIP datasets are not substitutes.
- Research studies: require their original selection, resampling, and report workflows in addition to signal rules.

The Scripts page shows per-source requirements, source hashes, original documentation, functions, and CLI declarations.
Refresh this report with `python -m workbench.library --output STRATEGY_LIBRARY.md`.
