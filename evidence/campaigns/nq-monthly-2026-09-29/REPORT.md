# NQ strategy comparison: January–August 2026

Generated 2026-09-29T20:53:42.274Z from the Workbench state and [campaign ledger](campaign.json). 16 current runnable strategies; 16 succeeded.

## Ranked results

The displayed ratio is **net return ÷ absolute maximum drawdown** for each continuous Jan–Aug run. A rank requires a completed, comparable, traded run with positive equity throughout, nonzero drawdown, and reconciled monthly returns. Infeasible or mismatched rows retain their metrics without a rank. Configuration references are documented below; the rank describes this historical period, not a fresh holdout result.

**Insolvent simulated paths:** Multi-speed momentum. The engine continues through nonpositive equity without margin liquidation. These paths are infeasible at the stated capital; percentage returns after a nonpositive prior month-end equity are N/A. Monthly dollar P&L remains shown.

| Rank | Strategy | Chart | Net return | Net P&L | Max drawdown | Return / drawdown | Trades | Risk flag | Status | Run |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| 1 | Short-term reversal - minute execution | 1m | +63.51% | $63,510 | 14.09% | 4.51 | 18 |  | Succeeded | [12e7e335](http://127.0.0.1:8001/api/workbench/runs/12e7e335-b656-4387-9be9-b70035fbf24d) |
| 2 | Short-term reversal - prior-day selloff | 1d | +47.21% | $47,205 | 12.32% | 3.83 | 16 |  | Succeeded | [4c7d7c1a](http://127.0.0.1:8001/api/workbench/runs/4c7d7c1a-b2d4-4c83-91ce-ea8dd7aa6851) |
| 3 | SND - Supply and demand | 1m | +47.84% | $47,835 | 15.05% | 3.18 | 367 |  | Succeeded | [a423c31a](http://127.0.0.1:8001/api/workbench/runs/a423c31a-8d8f-42a2-8c42-708e8d9f86d5) |
| 4 | RSI(2) reversion - corrected rebound exit | 1d | +77.50% | $77,505 | 26.37% | 2.94 | 22 |  | Succeeded | [53feb3fe](http://127.0.0.1:8001/api/workbench/runs/53feb3fe-cfde-44c8-9521-920555a8032c) |
| 5 | Pine · Overnight block | 15m | +70.95% | $70,950 | 26.21% | 2.71 | 172 |  | Succeeded | [739bff8e](http://127.0.0.1:8001/api/workbench/runs/739bff8e-cba5-48cc-9beb-48c05a9af5a3) |
| 6 | Pine · TSMOM intraday ORB | 5m | +16.31% | $16,310 | 10.31% | 1.58 | 29 |  | Succeeded | [4ccab74c](http://127.0.0.1:8001/api/workbench/runs/4ccab74c-4b3b-406b-8572-ddb99fcd5926) |
| 7 | Buy and hold benchmark | 1d | +80.83% | $80,835 | 54.62% | 1.48 | 1 |  | Succeeded | [9437c4ea](http://127.0.0.1:8001/api/workbench/runs/9437c4ea-fcd0-480e-9eda-c1d2918636a1) |
| 8 | RSI(2) trend-filtered reversion | 1d | +43.56% | $43,555 | 32.75% | 1.33 | 15 |  | Succeeded | [8d90c9d6](http://127.0.0.1:8001/api/workbench/runs/8d90c9d6-09b6-4d3f-aa22-fc8540ad53e6) |
| 9 | Session VWAP reversion | 5m | +47.25% | $47,250 | 35.67% | 1.32 | 209 |  | Succeeded | [4adbcf8e](http://127.0.0.1:8001/api/workbench/runs/4adbcf8e-20fd-44d6-acc8-dd23ab398ca8) |
| 10 | Moving-average trend | 4h | +31.23% | $31,235 | 50.53% | 0.62 | 54 |  | Succeeded | [6e9f7ac8](http://127.0.0.1:8001/api/workbench/runs/6e9f7ac8-2443-4e54-b93f-b39fef28d551) |
| 11 | Pine · Filtered overnight drift | 5m | +13.46% | $13,460 | 31.07% | 0.43 | 70 |  | Succeeded | [2fc42635](http://127.0.0.1:8001/api/workbench/runs/2fc42635-2780-4c36-8095-dd75060ebecd) |
| 12 | Pine · Daily TSMOM rebalance | 15m | -15.21% | -$15,210 | 70.28% | -0.22 | 12 |  | Succeeded | [9ec4401a](http://127.0.0.1:8001/api/workbench/runs/9ec4401a-3721-4329-bd6c-2a385fc7d3de) |
| 13 | Market intraday momentum - last 30 minutes | 5m | -5.72% | -$5,715 | 20.54% | -0.28 | 166 |  | Succeeded | [4e717204](http://127.0.0.1:8001/api/workbench/runs/4e717204-2e54-4ad6-b8aa-a4f0b048967f) |
| 14 | SND - Opposing zone exit experiment | 1m | -4.77% | -$4,770 | 15.86% | -0.30 | 117 |  | Succeeded | [7040c8d5](http://127.0.0.1:8001/api/workbench/runs/7040c8d5-401e-4df8-9b8f-99114f043b67) |
| — | Multi-speed momentum | 4h | -128.59% | -$128,590 | 124.48% | -1.03 | 79 | **INSOLVENT** | Succeeded | [5eeef1b2](http://127.0.0.1:8001/api/workbench/runs/5eeef1b2-ed49-4a2c-8aef-591911f5f519) |
| — | Wyckoff [theUltimator5] - NQ research | 15m | 0.00% | $0 | 0.00% | — | 0 |  | Succeeded | [260249fd](http://127.0.0.1:8001/api/workbench/runs/260249fd-e443-49da-a8bf-d742b22793d6) |

## Monthly returns

Percentages use month-end marked equity, including changes in open-position value. The first month starts from the run’s initial capital. A zero is a recorded zero return; `N/A` means the prior equity was nonpositive or the reported percentage failed equity reconciliation. Missing or failed run results show —. Exact marked monthly dollar P&L and reconciliation are in [monthly-pnl.csv](monthly-pnl.csv).

| Strategy | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Short-term reversal - minute execution | 0.00% | -4.97% | +12.16% | 0.00% | -6.22% | +31.92% | +28.10% | -3.20% |
| Short-term reversal - prior-day selloff | 0.00% | -6.01% | +12.08% | 0.00% | -9.28% | +25.37% | +28.65% | -4.49% |
| SND - Supply and demand | +2.54% | -4.33% | +11.37% | -1.63% | +12.47% | +25.91% | -0.80% | -2.09% |
| RSI(2) reversion - corrected rebound exit | +8.37% | -1.24% | +17.30% | +11.88% | +5.36% | +3.01% | +8.75% | +7.09% |
| Pine · Overnight block | -6.64% | +3.76% | -1.81% | +28.83% | +15.09% | +17.68% | -2.82% | +6.00% |
| Pine · TSMOM intraday ORB | +2.32% | 0.00% | +8.34% | +14.64% | -2.85% | -2.24% | 0.00% | -3.63% |
| Buy and hold benchmark | +3.21% | -13.30% | -23.41% | +107.77% | +39.20% | +1.12% | -22.09% | +15.80% |
| RSI(2) trend-filtered reversion | +1.86% | -3.73% | -3.95% | +15.47% | +24.31% | +13.57% | -13.92% | +8.60% |
| Session VWAP reversion | +10.38% | +1.32% | +15.92% | -17.21% | -2.42% | +24.26% | +22.41% | -7.57% |
| Moving-average trend | -14.11% | -7.70% | -29.09% | +90.39% | +32.10% | -0.36% | -23.49% | +21.76% |
| Pine · Filtered overnight drift | +6.46% | -1.19% | -5.91% | +14.62% | +4.61% | -8.18% | -13.17% | +19.91% |
| Pine · Daily TSMOM rebalance | -11.01% | -28.63% | -8.61% | +53.48% | +64.18% | +0.85% | -34.67% | -12.02% |
| Market intraday momentum - last 30 minutes | -9.06% | +0.26% | -2.84% | -0.31% | -4.39% | +3.62% | +2.85% | +4.77% |
| SND - Opposing zone exit experiment | +0.55% | -7.46% | -3.63% | +5.61% | +0.85% | +8.45% | +0.21% | -8.26% |
| Multi-speed momentum **(INSOLVENT)** | -54.71% | -45.80% | -9.52% | +142.88% | +103.49% | -78.30% | -42.69% | -309.49% |
| Wyckoff [theUltimator5] - NQ research | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |

![Monthly return heatmap](monthly-heatmap.png)

## Configuration selection

A run ending before 2026-01-01 is labeled prior NQ evidence. A reference that includes or may overlap January–August 2026 supplies configuration only; its performance is not shown as prior evidence. The corrected RSI reference falls in this latter category. Adapter versions can differ from the Jan–Aug replay.

| Strategy | Reference run | Reference period | Role | Prior return / drawdown | Configuration and selection reason |
| --- | --- | --- | --- | ---: | --- |
| Buy and hold benchmark | [571a4c3c](http://127.0.0.1:8001/api/workbench/runs/571a4c3c-27ff-4e90-8957-149e0e37149d) | 2024-01-01 to 2024-12-31 | Prior NQ evidence | 2.46 | Benchmark; one trade by design Parameters: {"contracts":1} |
| Market intraday momentum - last 30 minutes | [1388ab56](http://127.0.0.1:8001/api/workbench/runs/1388ab56-704c-47c1-b3fd-73ada622c78e) | 2024-01-01 to 2025-12-31 | Prior NQ evidence | -0.97 | Earlier NQ baseline lost money; diagnostic Parameters: {"signal_mode":"rest-of-day","close_time":"16:00","holding_minutes":"30","entry_delay_minutes":"0","minimum_move_bps":0,"contracts":1} |
| Moving-average trend | [fbbbdb99](http://127.0.0.1:8001/api/workbench/runs/fbbbdb99-cb18-4896-9bcf-2bdfa44c745c) | 2018-01-01 to 2023-12-31 | Prior NQ evidence | 6.59 | 4h lookback 20; positive 2018-2023 evidence Parameters: {"lookback":20,"contracts":1} |
| Multi-speed momentum | [33d05d29](http://127.0.0.1:8001/api/workbench/runs/33d05d29-d1dc-4f91-a875-aa07d4ecf627) | 2018-01-01 to 2023-12-31 | Prior NQ evidence | 9.76 | 4h lookback 60 from prior adapter version; provisional Parameters: {"lookback":60,"contracts":1} |
| Pine · Daily TSMOM rebalance | [4c5cb899](http://127.0.0.1:8001/api/workbench/runs/4c5cb899-3cd1-4052-8cd1-4c4a7cf24971) | 2018-01-01 to 2023-12-31 | Prior NQ evidence | 1.67 | Fixed one-contract earlier configuration Parameters: {"fast_length":20,"medium_length":60,"slow_length":120,"annual_length":252,"sizing_mode":"Fixed contracts","contracts":1,"annual_risk":0.2,"maximum_leverage":2,"volatility_length":60,"sleeve_count":1,"rounding":"Nearest"} |
| Pine · Overnight block | [1fdcd163](http://127.0.0.1:8001/api/workbench/runs/1fdcd163-4157-4d78-babf-f934d5a66a4e) | 2024-01-01 to 2025-12-31 | Prior NQ evidence | 6.39 | 17:00-06:00 NY; positive earlier evidence Parameters: {"entry_hour":17,"entry_minute":0,"exit_hour":6,"exit_minute":0,"contracts":1,"timezone":"America/New_York"} |
| Pine · Filtered overnight drift | [6ade3bf0](http://127.0.0.1:8001/api/workbench/runs/6ade3bf0-8ae7-4d7a-b7c0-ca95b64fe617) | 2024-01-01 to 2024-12-31 | Prior NQ evidence | 7.61 | Long after up close; 2024 strong, 2025 loss Parameters: {"sizing_mode":"Fixed contracts","contracts":1,"annual_risk":0.2,"maximum_leverage":2,"volatility_length":60,"sleeve_count":4,"timezone":"America/New_York","rth_start":570,"rth_end":960,"trade_weekend":false,"close_rule":"Long after up close","strong_threshold":0.6} |
| Pine · TSMOM intraday ORB | [c5acb02e](http://127.0.0.1:8001/api/workbench/runs/c5acb02e-c3e9-4c63-aa04-742d752e4594) | 2024-01-01 to 2024-12-31 | Prior NQ evidence | 2.26 | Risk cap $2,500, one contract; earlier positive evidence Parameters: {"fast_length":20,"medium_length":60,"slow_length":120,"annual_length":252,"timezone":"America/New_York","minimum_score":0.5,"opening_start":570,"opening_end":585,"entry_start":585,"entry_end":900,"flatten_start":945,"flatten_end":960,"risk_budget":2500,"maximum_contracts":1,"reward_risk":2,"require_close_break":true,"execution_timing":"close"} |
| RSI(2) trend-filtered reversion | [06d54926](http://127.0.0.1:8001/api/workbench/runs/06d54926-474c-4705-a804-90a63298f881) | 2018-01-01 to 2023-12-31 | Prior NQ evidence | 2.48 | Trend 200, entry 10, exit 70; earlier positive evidence Parameters: {"trend_lookback":200,"entry_rsi":10,"exit_rsi":70,"contracts":1} |
| RSI(2) reversion - corrected rebound exit | [dcbcfea6](http://127.0.0.1:8001/api/workbench/runs/dcbcfea6-9cd9-48f2-9fb4-9464896c10e3) | 2012-01-01 to 2026-08-31 | Historical configuration reference, includes or may overlap comparison period | — | Default parameters; no separate pre-2026 NQ selection Parameters: {"trend_lookback":200,"entry_rsi":10,"exit_rsi":70,"contracts":1} |
| Short-term reversal - prior-day selloff | [4f040d7a](http://127.0.0.1:8001/api/workbench/runs/4f040d7a-6231-4a7f-9855-cb2296eafb45) | 2024-01-01 to 2025-12-31 | Prior NQ evidence | 1.12 | 1.25% prior decline, trend filter; 2024-2025 selection Parameters: {"decline_pct":1.25,"confluence":"trend","trend_lookback":200,"close_fraction":0.25,"direction":"long-only","max_decline_pct":3,"hold_sessions":1,"renew_on_signal":false,"exit_on_rebound":false,"min_atr_multiple":0,"atr_period":20,"contracts":1} |
| Short-term reversal - minute execution | [29765c05](http://127.0.0.1:8001/api/workbench/runs/29765c05-bcf2-40e3-80c2-ca4387968e88) | 2024-01-01 to 2025-12-31 | Prior NQ evidence | 1.70 | 1.25% prior decline, five-minute open delay; 2024-2025 selection Parameters: {"decline_pct":1.25,"trend_lookback":200,"open_delay_minutes":5,"max_entry_lateness_minutes":5,"contracts":1} |
| SND - Supply and demand | [939f933f](http://127.0.0.1:8001/api/workbench/runs/939f933f-32da-46ef-ac9f-5a569a2f6d03) | 2024-01-01 to 2025-12-31 | Prior NQ evidence | -0.94 | Phase 6; prior NQ variants lost money; diagnostic Parameters: {"variant":"phase6","contracts":1} |
| SND - Opposing zone exit experiment | [e4f6cb8c](http://127.0.0.1:8001/api/workbench/runs/e4f6cb8c-9b98-4117-acb9-34167c73ed44) | 2024-01-01 to 2025-12-31 | Prior NQ evidence | 0.02 | Selected from recorded 2024-2025 12-case NQ screen, if qualified; Highest positive return / absolute maximum drawdown among successful candidates with >=30 trades and positive simulated equity Parameters: {"variant":"phase7_prior_1m","contracts":1,"zone_exit":"baseline"} |
| Session VWAP reversion | [70f658c2](http://127.0.0.1:8001/api/workbench/runs/70f658c2-31a4-4021-bd6e-64ddf427b97f) | 2024-01-01 to 2025-12-31 | Prior NQ evidence | -0.77 | Band 0.004; prior NQ variants lost money; diagnostic Parameters: {"band":0.004,"contracts":1} |
| Wyckoff [theUltimator5] - NQ research | [17341945](http://127.0.0.1:8001/api/workbench/runs/17341945-b8d0-4aff-97d1-ddc637c71543) | 2011-01-01 to 2022-12-31 | Prior NQ evidence | 1.17 | 15m Standard, eight-bar exit; prior signal sample sparse Parameters: {"strictness":"Standard","exit_policy":"fixed_bars","holding_bars":8,"entry_delay_bars":0,"atr_length":14,"stop_atr":1.5,"target_r":2} |

### SND opposing-zone selection record

The exploratory screen covers 2024-01-01 through 2025-12-31 on NQ. Highest positive return / absolute maximum drawdown among successful candidates with >=30 trades and positive simulated equity All attempted variants remain in the [campaign ledger](campaign.json).
The selected setting disables the opposing-zone exit. Every tested opposing-zone exit lost money in the screen. This is a diagnostic adapter setting, not evidence that the added exit improves SND.

| Selected | Variant | Zone exit | Net return | Max drawdown | Return / drawdown | Trades | Status | Run |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
|  | original_multi_tf | baseline | -49.22% | 76.94% | -0.64 | 1783 | Succeeded | [958d00eb](http://127.0.0.1:8001/api/workbench/runs/958d00eb-4ba7-41a4-a709-cb02fee8943f) |
|  | original_multi_tf | touch | -76.02% | 106.88% | -0.71 | 2320 | Succeeded | [45a89874](http://127.0.0.1:8001/api/workbench/runs/45a89874-803b-41d3-9ae9-9b77da540da4) |
|  | original_multi_tf | close-inside | -79.68% | 111.59% | -0.71 | 2287 | Succeeded | [0c7d737a](http://127.0.0.1:8001/api/workbench/runs/0c7d737a-709b-4168-a299-4d42df4594e5) |
|  | phase6 | baseline | -36.05% | 38.40% | -0.94 | 1059 | Succeeded | [8eb6a599](http://127.0.0.1:8001/api/workbench/runs/8eb6a599-43fd-4593-b7f5-9a0b64602712) |
|  | phase6 | touch | -47.36% | 57.51% | -0.82 | 1098 | Succeeded | [5fa691a9](http://127.0.0.1:8001/api/workbench/runs/5fa691a9-88e1-4aad-807e-0e746048e95b) |
|  | phase6 | close-inside | -44.73% | 53.85% | -0.83 | 1096 | Succeeded | [c5707d77](http://127.0.0.1:8001/api/workbench/runs/c5707d77-479b-402e-aac8-fb785ce6639f) |
| Yes | phase7_prior_1m | baseline | +0.29% | 12.93% | 0.02 | 329 | Succeeded | [e4f6cb8c](http://127.0.0.1:8001/api/workbench/runs/e4f6cb8c-9b98-4117-acb9-34167c73ed44) |
|  | phase7_prior_1m | touch | -3.08% | 14.04% | -0.22 | 332 | Succeeded | [2b1f34ae](http://127.0.0.1:8001/api/workbench/runs/2b1f34ae-c48f-4244-b68f-333991301417) |
|  | phase7_prior_1m | close-inside | -2.73% | 13.63% | -0.20 | 331 | Succeeded | [6d2d2390](http://127.0.0.1:8001/api/workbench/runs/6d2d2390-843f-49b1-9627-93ed28290ff7) |
|  | phase7_prior_5m | baseline | -39.35% | 44.18% | -0.89 | 412 | Succeeded | [605fdc91](http://127.0.0.1:8001/api/workbench/runs/605fdc91-4ea1-49bf-ab05-16a2e28e40ef) |
|  | phase7_prior_5m | touch | -46.10% | 50.90% | -0.91 | 420 | Succeeded | [f759c57e](http://127.0.0.1:8001/api/workbench/runs/f759c57e-d683-4f11-8e8a-59383c81b636) |
|  | phase7_prior_5m | close-inside | -45.14% | 51.47% | -0.88 | 419 | Succeeded | [dd8e7a1d](http://127.0.0.1:8001/api/workbench/runs/dd8e7a1d-54a9-400b-b1d3-2f5fc93cffff) |

## Assumptions and coverage

Each row is a separate NQ futures simulation on one continuous January–August window. The rows are not a combined portfolio. The runner starts flat, uses warmup for indicators only, marks equity at every selected-bar close, and liquidates at the final scored close.

- **Dataset version:** 3b9114199a2f6f0e51b70a63edc43de00940ae5df8d047b3aaa6aa8424aac9f1-v1.
- **Starting capital per run:** 100000 USD.
- **Commission per contract per side:** 2.5 USD.
- **Slippage per side:** 1 tick.
- **Common-input check:** every ranked row matches campaign dataset 3b9114199a2f6f0e51b70a63edc43de00940ae5df8d047b3aaa6aa8424aac9f1-v1, $100,000 starting capital, $2.50 commission per contract per side, one tick slippage per side, NQ, and the stated dates. Mismatches remain visible but unranked.
- **Scored interval:** 2026-01-01 through 2026-08-31 UTC; September is a partial month and excluded.
- **Risk measurement:** maximum drawdown comes from marked chart-bar-close equity, including initial capital. Intrabar adverse moves, margin calls, and liquidation are not modeled.
- **Data:** unadjusted volume-rolled continuous futures can contain roll gaps and are not an investable contract-roll return series. Strategy-specific migration and fill assumptions remain in each linked run.
- **Workbench warnings:** 16 runs: Continuous volume-rolled prices are unadjusted; contract rolls can affect signals and P&L.; 16 runs: Old history is preserved byte-for-value from the base dataset; only the tail was freshly acquired.; 16 runs: Gaps include exchange closures and no-trade minutes; no forward filling was performed.; 23 other warning type(s) in linked runs. See linked run details for each warning in full.
- **Evidence:** these dates were already inspected in earlier repository research. Successful execution and a positive score do not establish live feasibility.

## Failures and review flags

- **RSI(2) reversion - corrected rebound exit** ([53feb3fe](http://127.0.0.1:8001/api/workbench/runs/53feb3fe-cfde-44c8-9521-920555a8032c)): Selection reference includes or may overlap Jan–Aug 2026; no prior performance claim.

- **Pine · Daily TSMOM rebalance** ([9ec4401a](http://127.0.0.1:8001/api/workbench/runs/9ec4401a-3721-4329-bd6c-2a385fc7d3de)): Nonpositive net P&L.

- **Market intraday momentum - last 30 minutes** ([4e717204](http://127.0.0.1:8001/api/workbench/runs/4e717204-2e54-4ad6-b8aa-a4f0b048967f)): Nonpositive net P&L.

- **SND - Opposing zone exit experiment** ([7040c8d5](http://127.0.0.1:8001/api/workbench/runs/7040c8d5-401e-4df8-9b8f-99114f043b67)): Nonpositive net P&L.

- **Multi-speed momentum** ([5eeef1b2](http://127.0.0.1:8001/api/workbench/runs/5eeef1b2-ed49-4a2c-8aef-591911f5f519)): Selection used an older adapter version; Nonpositive net P&L; Simulated equity crossed zero; no margin liquidation model.

- **Wyckoff [theUltimator5] - NQ research** ([260249fd](http://127.0.0.1:8001/api/workbench/runs/260249fd-e443-49da-a8bf-d742b22793d6)): Zero trades; Nonpositive net P&L.

Full numeric values, configuration fields, IDs, and issue labels: [report.csv](report.csv). Exact monthly dollars: [monthly-pnl.csv](monthly-pnl.csv). Workbench: [Runs & compare](http://127.0.0.1:8001/#/runs).
