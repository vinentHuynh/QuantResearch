# Canonical strategy engine

This package is the destination for chart-, timeframe-, and session-independent strategy implementations.
Legacy research scripts remain unchanged until a canonical implementation passes frozen-data parity checks.

## Identity versus run configuration

The strategy catalog lists a specific trading strategy, such as `opening-range-breakout`. Chart, timeframe,
session, date range, costs, and risk settings are inputs to a run; they are not separate strategies. Each run
stores those inputs with the immutable strategy version and data fingerprints.

## Current canonical coverage

| Strategy | Version | Charts | Timeframes | Sessions | Status |
| --- | --- | --- | --- | --- | --- |
| Multi-speed time-series momentum | 2.1.0 | One selected chart | 30m, 1h, 4h, 1d | Full trading day, New York RTH, London, Asia (Tokyo) | Web runner enabled; exact legacy signal parity; sizing/portfolio parity pending |
| Moving-average trend | 2.1.0 | One selected chart | 30m, 1h, 4h, 1d | Full trading day, New York RTH, London, Asia (Tokyo) | Web runner enabled; exact legacy sleeve signal/return parity; portfolio/feed parity pending |
| Cross-sectional momentum | 2.1.0 | 3–20 explicitly selected charts | 1h, 4h, 1d | Full trading day, New York RTH, London, Asia (Tokyo) | Web runner enabled; legacy-family parity pending |
| Pairs mean reversion | 2.1.0 | Two explicitly selected charts | 30m, 1h, 4h, 1d | Full trading day, New York RTH, London, Asia (Tokyo) | Web runner enabled; legacy parity pending |
| Opening-range breakout | 2.0.0 | Dashboard chart registry | 1m, 5m, 15m, 30m | New York RTH, London, Asia (Tokyo) | Web runner enabled; legacy-family parity pending |
| Prior-range fill | 2.0.0 | Dashboard chart registry | 1m, 5m, 15m, 30m, 1h | New York RTH, London, Asia (Tokyo) | Web runner enabled; legacy parity pending |
| Session drift | 2.0.0 | Dashboard chart registry | 1m, 5m, 15m, 30m, 1h | Globex overnight, New York RTH, London, Asia (Tokyo) | Web runner enabled; legacy-family parity pending |

## Package boundaries

- `catalog.py` owns specific strategy identity and supported execution dimensions.
- `sessions.py` owns named timezone-aware session definitions.
- `data.py` normalizes UTC OHLCV, anchors resampling to each local session open, and records the
  close-availability timestamp separately from the bar-start index.
- `strategies/` contains economic trading logic without chart paths or instrument constants.
- `accounting.py` converts closed trades or target-position changes into normalized P&L, order, fill,
  position, closed-exposure, and session-equity ledgers.
- `runner.py` is the common CLI used by the local FastAPI worker.

The runner writes a normalized run specification plus `signals.csv`, `orders.csv`, `fills.csv`, `positions.csv`,
`pnl.csv`, `trades.csv`, and session-level `equity.csv`. A trade is a closed exposure episode, not a mark-to-market
row; P&L observations remain separate. Metrics include every expected session, including zero-P&L sessions, and
annualize session returns with 252 sessions. Signals formed from a bar close become actionable at that bar's
availability time and positions earn P&L only after that point. Intraday session variants flatten at the selected
session close and do not receive excluded-session price changes. Declared cost ticks are round-trip ticks; closed
trades receive the full charge once and target-position turnover receives half on each one-way change. Position-based
strategies expose two explicit sizing conventions: `fractional` preserves normalized research exposure, while
`whole_contracts` truncates toward zero so every order and position is an executable contract quantity without
rounding exposure upward. The selected convention and its executability are stored in each run specification and
summary. Backtest, reference, paper, and live histories remain distinct dashboard inputs.

## Frozen parity evidence

Run `.venv/bin/python -m strategy_engine.parity` to execute exact pure calculation functions extracted from the
legacy source files against the deterministic fixture. `parity_evidence.json` records source and harness hashes,
comparison tolerances, mismatch counts, coverage, and the blockers preventing partial evidence from being called
full parity. Any change to a compared legacy file, canonical implementation, or the harness invalidates the
dashboard's tracked evidence until the suite is rerun and reviewed.
