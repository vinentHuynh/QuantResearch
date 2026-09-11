"""Turn the MNQ New York close -> Asia fill study into tradeable strategy backtests.

`mnq_ny_close_asia_fill_backtest.py` answers a statistical question: how often
does MNQ revisit the New York close during Asia, and what is the average
one-contract outcome?  This script answers the trading question that follows:
if the report's selected rule is traded as a strategy, what does the equity
curve look like once execution, stops, deadlines, and selection bias are
modelled?

Differences from the study:

* Costs are split into their real components.  Entry is a market order at the
  18:00 ET reopen and pays slippage; the target is a resting limit at the
  reference close and pays none; stop and deadline exits are market orders and
  pay slippage again.  Commission is a separate dollar figure per round trip.
* An optional protective stop bounds the non-fill tail.  When a 5-minute bar
  touches both the stop and the target, the stop is assumed to trade first.
* An optional fill buffer requires the market to trade *through* the target,
  which stands in for queue position on the limit order.
* Performance is reported per session (a trading calendar with zeros on days
  the filter stands aside), not only per trade, so Sharpe and drawdown mean
  what they normally mean.
* The report's headline rule was chosen after seeing the whole sample.  The
  grid mode re-runs every competing rule and prices that search with a
  White-style reality check; the walk-forward mode re-selects the rule from
  past data only and trades the year that follows.

Examples:

    python mnq_asia_fill_strategy_backtest.py
    python mnq_asia_fill_strategy_backtest.py --rule-side Long --rule-max-gap-bps 5
    python mnq_asia_fill_strategy_backtest.py --commission-rt 0 --entry-slippage-ticks 0
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from mnq_ny_close_asia_fill_backtest import (
    DOLLARS_PER_POINT,
    TICK_SIZE,
    load_bars,
    markdown_table,
    max_drawdown_dollars,
    parse_clock,
    reference_closes,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "data" / "MNQ_5min_databento.parquet"
DEFAULT_OUT = ROOT / "reports" / "mnq_asia_fill_strategy"
TRADING_DAYS = 252
Z95 = 1.959964

GRID_THRESHOLDS = (1.0, 2.0, 3.0, 5.0, 7.5, 10.0, 15.0, 25.0, float("inf"))
GRID_SIDES = ("Long", "Short", "Both")
STOP_SWEEP = (None, 10.0, 20.0, 30.0, 50.0, 80.0)
DEADLINE_SWEEP = ("21:00", "23:00", "00:00", "02:00", "04:00", "09:30")
COST_SWEEP_TICKS = (0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0)


# --------------------------------------------------------------------------
# Session construction
# --------------------------------------------------------------------------
def build_sessions(
    bars: pd.DataFrame,
    close_time: str,
    asia_start: str,
    asia_end: str,
    bar_delta: pd.Timedelta,
    max_reference_age_hours: float,
    min_asia_bars: int,
) -> pd.DataFrame:
    """Pair every Asia reopen with the most recent completed reference close.

    The result carries the half-open bar slice ``[start_row, end_row)`` for the
    Asia window so the simulator can walk sessions without re-scanning the
    whole frame.  Sessions are kept even when the gap is zero or tiny; gap
    filters belong to the strategy layer, not to the calendar.
    """
    asia_start_clock = parse_clock(asia_start)
    asia_end_clock = parse_clock(asia_end)

    index = bars.index
    start_mask = (index.hour == asia_start_clock[0]) & (index.minute == asia_start_clock[1])
    starts = pd.DataFrame(
        {
            "asia_start_ts": index[start_mask],
            "entry_price": bars.loc[start_mask, "open"].to_numpy(),
        }
    ).sort_values("asia_start_ts")

    refs = reference_closes(bars, close_time, bar_delta).sort_values("reference_ts")
    paired = pd.merge_asof(
        starts,
        refs,
        left_on="asia_start_ts",
        right_on="reference_ts",
        direction="backward",
        allow_exact_matches=False,
    )
    paired["reference_age_hours"] = (
        paired["asia_start_ts"] - paired["reference_ts"]
    ).dt.total_seconds() / 3600
    paired = paired[
        paired["ny_close"].notna()
        & paired["reference_age_hours"].between(0, max_reference_age_hours)
    ].copy()

    # A local DateOffset keeps the intended wall-clock deadline across DST.
    end_ts = paired["asia_start_ts"].dt.normalize() + pd.DateOffset(
        hours=asia_end_clock[0], minutes=asia_end_clock[1]
    )
    end_ts = end_ts.where(end_ts > paired["asia_start_ts"], end_ts + pd.DateOffset(days=1))
    paired["asia_end_ts"] = end_ts

    values = index.values
    paired["start_row"] = np.searchsorted(values, paired["asia_start_ts"].values, side="left")
    paired["end_row"] = np.searchsorted(values, paired["asia_end_ts"].values, side="left")
    paired["asia_bars"] = paired["end_row"] - paired["start_row"]
    paired = paired[paired["asia_bars"] >= min_asia_bars].copy()

    paired["raw_gap_points"] = paired["entry_price"] - paired["ny_close"]
    paired["gap_points"] = paired["raw_gap_points"].abs()
    paired["gap_bps"] = paired["gap_points"] / paired["ny_close"] * 10_000
    paired["side"] = np.where(paired["raw_gap_points"] > 0, "Short", "Long")
    paired["session_date"] = paired["asia_start_ts"].dt.normalize().dt.tz_localize(None)
    return paired.reset_index(drop=True)


# --------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------
def simulate(
    bars: pd.DataFrame,
    sessions: pd.DataFrame,
    bar_delta: pd.Timedelta,
    min_gap_points: float,
    stop_points: float | None = None,
    stop_gap_multiple: float | None = None,
    fill_buffer_ticks: float = 0.0,
) -> pd.DataFrame:
    """Walk each Asia session bar by bar and record one gap-fade trade.

    Gross points are recorded without costs so that cost assumptions can be
    swept afterwards without re-simulating.  Within a bar that touches both the
    protective stop and the target, the stop is taken first: 5-minute bars do
    not reveal the order of the two touches, and the pessimistic reading is the
    one that cannot flatter the strategy.
    """
    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()
    close = bars["close"].to_numpy()
    index = bars.index
    buffer_points = fill_buffer_ticks * TICK_SIZE

    tradeable = sessions[sessions["gap_points"] >= min_gap_points]
    tradeable = tradeable[tradeable["raw_gap_points"] != 0]

    records: list[dict] = []
    for row in tradeable.itertuples(index=False):
        sign = -1.0 if row.side == "Short" else 1.0
        entry = float(row.entry_price)
        target = float(row.ny_close)

        stop_distance = np.inf
        if stop_points is not None:
            stop_distance = min(stop_distance, float(stop_points))
        if stop_gap_multiple is not None:
            stop_distance = min(stop_distance, float(stop_gap_multiple) * row.gap_points)
        stop_level = entry - sign * stop_distance if np.isfinite(stop_distance) else np.nan

        start_row, end_row = int(row.start_row), int(row.end_row)
        session_high = high[start_row:end_row]
        session_low = low[start_row:end_row]

        if sign > 0:
            target_hits = session_high >= target + buffer_points
            stop_hits = session_low <= stop_level if np.isfinite(stop_distance) else None
        else:
            target_hits = session_low <= target - buffer_points
            stop_hits = session_high >= stop_level if np.isfinite(stop_distance) else None

        target_row = int(np.argmax(target_hits)) if target_hits.any() else None
        stop_row = None
        if stop_hits is not None and stop_hits.any():
            stop_row = int(np.argmax(stop_hits))

        # The stop wins ties inside a bar, and any earlier stop pre-empts the target.
        if stop_row is not None and (target_row is None or stop_row <= target_row):
            exit_offset = stop_row
            exit_reason = "stop"
            exit_price = stop_level
        elif target_row is not None:
            exit_offset = target_row
            exit_reason = "target"
            exit_price = target
        else:
            exit_offset = end_row - start_row - 1
            exit_reason = "deadline"
            exit_price = float(close[end_row - 1])

        exit_ts = index[start_row + exit_offset] + bar_delta
        walked_high = session_high[: exit_offset + 1]
        walked_low = session_low[: exit_offset + 1]
        if sign > 0:
            mae = max(0.0, entry - float(walked_low.min()))
            mfe = max(0.0, float(walked_high.max()) - entry)
        else:
            mae = max(0.0, float(walked_high.max()) - entry)
            mfe = max(0.0, entry - float(walked_low.min()))

        records.append(
            {
                "session_date": row.session_date,
                "asia_start_ts": row.asia_start_ts,
                "reference_ts": row.reference_ts,
                "side": row.side,
                "ny_close": target,
                "entry_price": entry,
                "gap_points": row.gap_points,
                "gap_bps": row.gap_bps,
                "exit_ts": exit_ts,
                "exit_price": float(exit_price),
                "exit_reason": exit_reason,
                "filled": exit_reason == "target",
                "minutes_held": (exit_ts - row.asia_start_ts).total_seconds() / 60,
                "gross_points": sign * (float(exit_price) - entry),
                "mae_points": mae,
                "mfe_points": mfe,
                "asia_bars": row.asia_bars,
            }
        )
    return pd.DataFrame.from_records(records)


def apply_costs(
    trades: pd.DataFrame,
    entry_slippage_ticks: float,
    exit_slippage_ticks: float,
    commission_rt: float,
    contracts: int = 1,
) -> pd.DataFrame:
    """Charge entry slippage on every trade and exit slippage on market exits."""
    if trades.empty:
        return trades.assign(cost_points=[], net_points=[], net_pnl_dollars=[])
    work = trades.copy()
    market_exit = work["exit_reason"].ne("target").astype(float)
    work["cost_points"] = (
        entry_slippage_ticks * TICK_SIZE
        + market_exit * exit_slippage_ticks * TICK_SIZE
        + commission_rt / DOLLARS_PER_POINT
    )
    work["net_points"] = work["gross_points"] - work["cost_points"]
    work["gross_pnl_dollars"] = work["gross_points"] * DOLLARS_PER_POINT * contracts
    work["net_pnl_dollars"] = work["net_points"] * DOLLARS_PER_POINT * contracts
    return work


def select(trades: pd.DataFrame, side: str, max_gap_bps: float) -> pd.DataFrame:
    """Apply a rule: one side (or both) and a maximum normalized gap."""
    work = trades[trades["gap_bps"] < max_gap_bps]
    if side != "Both":
        work = work[work["side"] == side]
    return work


# --------------------------------------------------------------------------
# Performance measurement
# --------------------------------------------------------------------------
def session_pnl(trades: pd.DataFrame, calendar: pd.Series) -> pd.Series:
    """Map trades onto the full session calendar, with zeros when standing aside."""
    if trades.empty:
        return pd.Series(0.0, index=calendar)
    daily = trades.groupby("session_date")["net_pnl_dollars"].sum()
    return daily.reindex(calendar).fillna(0.0)


def performance(trades: pd.DataFrame, calendar: pd.Series) -> dict:
    """One-contract statistics, measured per trade and per available session."""
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    net = trades["net_pnl_dollars"]
    per_trade_se = net.std(ddof=1) / math.sqrt(n) if n > 1 else np.nan
    wins = net[net > 0].sum()
    losses = net[net < 0].sum()

    daily = session_pnl(trades, calendar)
    sessions = len(daily)
    daily_std = daily.std(ddof=1)
    sharpe = (daily.mean() / daily_std * math.sqrt(TRADING_DAYS)) if daily_std else np.nan
    daily_se = daily_std / math.sqrt(sessions) if sessions > 1 else np.nan
    years = sessions / TRADING_DAYS if sessions else np.nan
    max_dd = max_drawdown_dollars(daily)

    return {
        "trades": n,
        "sessions": sessions,
        "trades_per_year": n / years if years else np.nan,
        "fill_rate": float(trades["filled"].mean()),
        "stop_rate": float(trades["exit_reason"].eq("stop").mean()),
        "deadline_rate": float(trades["exit_reason"].eq("deadline").mean()),
        "win_rate": float((net > 0).mean()),
        "avg_net_pnl_dollars": float(net.mean()),
        "avg_net_pnl_ci95_low": float(net.mean() - Z95 * per_trade_se) if n > 1 else np.nan,
        "avg_net_pnl_ci95_high": float(net.mean() + Z95 * per_trade_se) if n > 1 else np.nan,
        "per_trade_tstat": float(net.mean() / per_trade_se) if per_trade_se else np.nan,
        "per_session_tstat": float(daily.mean() / daily_se) if daily_se else np.nan,
        "total_net_pnl_dollars": float(net.sum()),
        "pnl_per_year_dollars": float(net.sum() / years) if years else np.nan,
        "profit_factor": float(wins / abs(losses)) if losses else np.inf,
        "sharpe_ratio": float(sharpe),
        "max_drawdown_dollars": float(max_dd),
        "return_over_max_dd": float(net.sum() / max_dd) if max_dd else np.nan,
        "worst_trade_dollars": float(net.min()),
        "best_trade_dollars": float(net.max()),
        "avg_mae_points": float(trades["mae_points"].mean()),
        "avg_minutes_held": float(trades["minutes_held"].mean()),
    }


def annual_table(trades: pd.DataFrame, calendar: pd.Series) -> pd.DataFrame:
    rows = []
    for year, frame in trades.groupby(trades["session_date"].dt.year):
        year_calendar = calendar[calendar.dt.year == year]
        rows.append({"year": int(year)} | performance(frame, year_calendar))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Selection-bias controls
# --------------------------------------------------------------------------
def grid_table(
    trades: pd.DataFrame,
    calendar: pd.Series,
    close_time: str,
    sides: Sequence[str] = GRID_SIDES,
    thresholds: Sequence[float] = GRID_THRESHOLDS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Evaluate every side/threshold rule and return stats plus a P&L matrix.

    The matrix has one row per session and one column per rule, which is what
    the reality check resamples.  Overlapping thresholds make the columns
    strongly dependent; resampling whole sessions preserves that dependence.
    """
    rows, columns = [], {}
    for side in sides:
        for threshold in thresholds:
            subset = select(trades, side, threshold)
            if subset.empty:
                continue
            name = f"{close_time}|{side}|{threshold:g}"
            rows.append(
                {"reference_close": close_time, "side": side, "max_gap_bps": threshold}
                | performance(subset, calendar)
            )
            columns[name] = session_pnl(subset, calendar)
    matrix = pd.DataFrame(columns, index=calendar.to_numpy()) if columns else pd.DataFrame()
    return pd.DataFrame(rows), matrix


def block_indices(n_rows: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """Draw a circular block bootstrap index of length ``n_rows``."""
    starts = rng.integers(0, n_rows, size=math.ceil(n_rows / block))
    offsets = (starts[:, None] + np.arange(block)[None, :]) % n_rows
    return offsets.ravel()[:n_rows]


def bootstrap_pvalue(
    series: pd.Series,
    iterations: int = 5000,
    block: int = 5,
    seed: int = 7,
) -> dict:
    """One-sided block bootstrap p-value for a single pre-specified rule.

    The per-session P&L of a limit-target strategy is extremely left-skewed: a
    long file of small target wins punctuated by rare large non-fill losses.
    The usual t-statistic assumes away exactly that shape, so its p-value is
    optimistic.  Resampling blocks of the demeaned series prices the skew.
    """
    values = series.to_numpy(dtype=float)
    n = len(values)
    std = values.std(ddof=1)
    if n < 2 or std == 0 or iterations <= 0:
        return {}
    observed = values.mean() / std * math.sqrt(n)
    centered = values - values.mean()
    rng = np.random.default_rng(seed)
    # A fixed denominator keeps the statistic comparable across resamples.
    stats = np.array(
        [centered[block_indices(n, block, rng)].mean() for _ in range(iterations)]
    ) / std * math.sqrt(n)
    return {
        "observed_tstat": float(observed),
        "normal_p_value": float(0.5 * math.erfc(observed / math.sqrt(2))),
        "bootstrap_p_value": float(((stats >= observed).sum() + 1) / (iterations + 1)),
        "null_tstat_p95": float(np.quantile(stats, 0.95)),
        "skewness": float(pd.Series(values).skew()),
        "excess_kurtosis": float(pd.Series(values).kurt()),
        "iterations": iterations,
    }


def reality_check(
    matrix: pd.DataFrame,
    iterations: int = 2000,
    block: int = 5,
    seed: int = 7,
    min_trades: pd.Series | None = None,
) -> dict:
    """White-style reality check on the best rule in the search.

    Each column is demeaned to impose the null of no edge, then whole blocks of
    sessions are resampled so that serial dependence and the heavy overlap
    between nested rules survive into the null.  Following White (2000) and
    Hansen (2005) the statistic is standardized by each rule's *original*
    sample deviation rather than the deviation of each resample: a sparse rule
    can otherwise draw a near-constant resample whose own deviation collapses
    and whose t-statistic explodes, which inflates the null maximum and buries
    any real result.  The p-value is the share of resamples whose best rule
    beats the observed best, so it prices the search, not one hypothesis.
    """
    if matrix.empty or iterations <= 0:
        return {}
    values = matrix.to_numpy(dtype=float)
    n_rows, n_cols = values.shape
    scale = math.sqrt(n_rows)
    deviation = values.std(axis=0, ddof=1)
    usable = deviation > 0
    if not usable.any():
        return {}
    values, deviation = values[:, usable], deviation[usable]
    names = matrix.columns[usable]

    observed_t = values.mean(axis=0) / deviation * scale
    best_column = int(np.argmax(observed_t))
    best_t = float(observed_t[best_column])

    centered = values - values.mean(axis=0)
    rng = np.random.default_rng(seed)
    max_stats = np.empty(iterations)
    for i in range(iterations):
        sample = centered[block_indices(n_rows, block, rng)]
        max_stats[i] = np.max(sample.mean(axis=0) / deviation * scale)
    return {
        "best_rule": names[best_column],
        "best_per_session_tstat": best_t,
        "rules_searched": int(usable.sum()),
        "reality_check_p_value": float(((max_stats >= best_t).sum() + 1) / (iterations + 1)),
        "null_max_tstat_p95": float(np.quantile(max_stats, 0.95)),
        "iterations": iterations,
    }


def walk_forward(
    trades: pd.DataFrame,
    calendar: pd.Series,
    sides: Sequence[str] = GRID_SIDES,
    thresholds: Sequence[float] = GRID_THRESHOLDS,
    min_train_trades: int = 100,
    first_test_year: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Re-select the rule each year from prior data only, then trade it forward.

    Selection maximizes the in-sample per-trade t-statistic among rules with
    enough history.  This cannot recover a true out-of-sample test of a rule
    that was already chosen on the full sample, but it does measure whether the
    selection procedure itself would have paid.
    """
    years = sorted(trades["session_date"].dt.year.unique())
    if len(years) < 3:
        return pd.DataFrame(), pd.DataFrame()
    start_year = first_test_year or years[2]

    picks, oos_parts = [], []
    for year in [y for y in years if y >= start_year]:
        train = trades[trades["session_date"].dt.year < year]
        test = trades[trades["session_date"].dt.year == year]
        if train.empty or test.empty:
            continue
        best, best_t = None, -np.inf
        for side in sides:
            for threshold in thresholds:
                subset = select(train, side, threshold)
                if len(subset) < min_train_trades:
                    continue
                net = subset["net_pnl_dollars"]
                se = net.std(ddof=1) / math.sqrt(len(net))
                t_stat = net.mean() / se if se else -np.inf
                if t_stat > best_t:
                    best, best_t = (side, threshold), t_stat
        if best is None:
            continue
        side, threshold = best
        traded = select(test, side, threshold)
        year_calendar = calendar[calendar.dt.year == year]
        picks.append(
            {
                "test_year": int(year),
                "chosen_side": side,
                "chosen_max_gap_bps": threshold,
                "train_trades": len(select(train, side, threshold)),
                "train_tstat": float(best_t),
                "train_avg_net_pnl_dollars": float(
                    select(train, side, threshold)["net_pnl_dollars"].mean()
                ),
            }
            | performance(traded, year_calendar)
        )
        oos_parts.append(traded)

    oos = pd.concat(oos_parts, ignore_index=True) if oos_parts else pd.DataFrame()
    return pd.DataFrame(picks), oos


# --------------------------------------------------------------------------
# Sweeps
# --------------------------------------------------------------------------
def cost_sweep(
    trades_gross: pd.DataFrame,
    calendar: pd.Series,
    side: str,
    max_gap_bps: float,
    commission_rt: float,
    tick_grid: Iterable[float] = COST_SWEEP_TICKS,
) -> pd.DataFrame:
    """Vary round-trip slippage while holding the commission assumption fixed."""
    rows = []
    for ticks in tick_grid:
        priced = apply_costs(trades_gross, ticks / 2, ticks / 2, commission_rt)
        subset = select(priced, side, max_gap_bps)
        rows.append(
            {
                "slippage_ticks_rt": ticks,
                "commission_rt_dollars": commission_rt,
                "all_in_cost_dollars": ticks * TICK_SIZE * DOLLARS_PER_POINT + commission_rt,
            }
            | performance(subset, calendar)
        )
    return pd.DataFrame(rows)


def stop_sweep(
    bars: pd.DataFrame,
    sessions: pd.DataFrame,
    bar_delta: pd.Timedelta,
    calendar: pd.Series,
    args: argparse.Namespace,
    side: str,
    max_gap_bps: float,
    stops: Iterable[float | None] = STOP_SWEEP,
) -> pd.DataFrame:
    rows = []
    for stop in stops:
        raw = simulate(
            bars, sessions, bar_delta, args.min_gap_points,
            stop_points=stop, fill_buffer_ticks=args.fill_buffer_ticks,
        )
        priced = apply_costs(
            raw, args.entry_slippage_ticks, args.exit_slippage_ticks, args.commission_rt
        )
        subset = select(priced, side, max_gap_bps)
        rows.append({"stop_points": stop if stop is not None else np.nan} | performance(subset, calendar))
    return pd.DataFrame(rows)


def deadline_sweep(
    bars: pd.DataFrame,
    bar_delta: pd.Timedelta,
    args: argparse.Namespace,
    close_time: str,
    side: str,
    max_gap_bps: float,
    deadlines: Iterable[str] = DEADLINE_SWEEP,
) -> pd.DataFrame:
    rows = []
    for deadline in deadlines:
        sessions = build_sessions(
            bars, close_time, args.asia_start, deadline, bar_delta,
            args.max_reference_age_hours, args.min_asia_bars,
        )
        sessions = clip_range(sessions, args.start, args.end, bars.index.tz)
        if sessions.empty:
            continue
        calendar = sessions["session_date"].drop_duplicates().sort_values().reset_index(drop=True)
        raw = simulate(
            bars, sessions, bar_delta, args.min_gap_points,
            stop_points=args.stop_points, fill_buffer_ticks=args.fill_buffer_ticks,
        )
        priced = apply_costs(
            raw, args.entry_slippage_ticks, args.exit_slippage_ticks, args.commission_rt
        )
        subset = select(priced, side, max_gap_bps)
        rows.append({"asia_end": deadline} | performance(subset, calendar))
    return pd.DataFrame(rows)


def buffer_sweep(
    bars: pd.DataFrame,
    sessions: pd.DataFrame,
    bar_delta: pd.Timedelta,
    calendar: pd.Series,
    args: argparse.Namespace,
    side: str,
    max_gap_bps: float,
    buffers: Iterable[float] = (0.0, 1.0, 4.0, 8.0),
) -> tuple[pd.DataFrame, dict]:
    """Stress the limit-order assumption by requiring the market to trade through.

    Also isolates the sessions whose low (or high) stopped exactly at the target
    tick.  Those are the only sessions where queue position decides the trade,
    and on a 0.25-point grid every buffer between half a tick and several ticks
    removes the same handful of them.
    """
    rows, touch_only = [], {}
    baseline = None
    for buffer_ticks in buffers:
        raw = simulate(
            bars, sessions, bar_delta, args.min_gap_points,
            stop_points=args.stop_points, fill_buffer_ticks=buffer_ticks,
        )
        priced = apply_costs(
            raw, args.entry_slippage_ticks, args.exit_slippage_ticks, args.commission_rt
        )
        subset = select(priced, side, max_gap_bps).set_index("session_date")
        rows.append({"fill_buffer_ticks": buffer_ticks} | performance(subset.reset_index(), calendar))
        if buffer_ticks == 0.0:
            baseline = subset
        elif buffer_ticks == 1.0 and baseline is not None:
            lost = baseline.index[baseline["filled"] & ~subset["filled"].reindex(baseline.index, fill_value=False)]
            touch_only = {
                "sessions": len(lost),
                "share_of_trades": len(lost) / len(baseline) if len(baseline) else np.nan,
                "pnl_if_filled": float(baseline.loc[lost, "net_pnl_dollars"].sum()),
                "pnl_if_missed": float(subset.loc[lost, "net_pnl_dollars"].sum()),
                "total_net_pnl_dollars": float(baseline["net_pnl_dollars"].sum()),
                "dates": ", ".join(str(date.date()) for date in lost),
            }
    return pd.DataFrame(rows), touch_only


def overnight_benchmark(
    bars: pd.DataFrame,
    sessions: pd.DataFrame,
    calendar: pd.Series,
    args: argparse.Namespace,
) -> dict:
    """Hold one long contract from the reopen to the deadline, same sessions."""
    close = bars["close"].to_numpy()
    frame = sessions.copy()
    exit_price = close[frame["end_row"].to_numpy() - 1]
    gross = exit_price - frame["entry_price"].to_numpy()
    cost = (
        args.entry_slippage_ticks + args.exit_slippage_ticks
    ) * TICK_SIZE + args.commission_rt / DOLLARS_PER_POINT
    trades = pd.DataFrame(
        {
            "session_date": frame["session_date"],
            "exit_reason": "deadline",
            "filled": False,
            "gross_points": gross,
            "net_pnl_dollars": (gross - cost) * DOLLARS_PER_POINT,
            "mae_points": 0.0,
            "minutes_held": np.nan,
        }
    )
    return performance(trades, calendar)


# --------------------------------------------------------------------------
# Plumbing
# --------------------------------------------------------------------------
def clip_range(frame: pd.DataFrame, start: str, end: str | None, tz) -> pd.DataFrame:
    start_ts = pd.Timestamp(start)
    start_ts = start_ts.tz_localize(tz) if start_ts.tzinfo is None else start_ts.tz_convert(tz)
    work = frame[frame["asia_start_ts"] >= start_ts]
    if end:
        end_ts = pd.Timestamp(end)
        end_ts = end_ts.tz_localize(tz) if end_ts.tzinfo is None else end_ts.tz_convert(tz)
        work = work[work["asia_start_ts"] < end_ts + pd.DateOffset(days=1)]
    return work.reset_index(drop=True)


def optional_float(value: str) -> float | None:
    if value.strip().lower() in {"none", "off", ""}:
        return None
    return float(value)


PERF_COLUMNS = [
    "trades", "trades_per_year", "fill_rate", "win_rate", "avg_net_pnl_dollars",
    "per_trade_tstat", "total_net_pnl_dollars", "pnl_per_year_dollars",
    "profit_factor", "sharpe_ratio", "max_drawdown_dollars", "worst_trade_dollars",
]
PERF_FORMATS = {
    "trades_per_year": ".0f", "fill_rate": ".1%", "win_rate": ".1%",
    "avg_net_pnl_dollars": ".2f", "per_trade_tstat": ".2f",
    "total_net_pnl_dollars": ".0f", "pnl_per_year_dollars": ".0f",
    "profit_factor": ".2f", "sharpe_ratio": ".2f",
    "max_drawdown_dollars": ".0f", "worst_trade_dollars": ".0f",
}


def perf_frame(records: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(records)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--symbol", default="MNQ", help="chart/instrument label")
    parser.add_argument("--tick-size", type=float, default=0.25)
    parser.add_argument("--point-value", type=float, default=2.0)
    parser.add_argument("--start", default="2020-01-02")
    parser.add_argument("--end", default=None)
    parser.add_argument("--close-times", default="16:00,17:00")
    parser.add_argument("--asia-start", default="18:00")
    parser.add_argument("--asia-end", default="00:00")
    parser.add_argument("--max-reference-age-hours", type=float, default=4.0)
    parser.add_argument("--min-asia-bars", type=int, default=12)
    parser.add_argument("--min-gap-points", type=float, default=0.25)

    parser.add_argument("--rule-close", default="17:00", help="reference close for the headline rule")
    parser.add_argument("--rule-side", default="Short", choices=["Long", "Short", "Both"])
    parser.add_argument("--rule-max-gap-bps", type=float, default=3.0)

    parser.add_argument("--commission-rt", type=float, default=1.00,
                        help="commission in dollars per round trip per contract")
    parser.add_argument("--entry-slippage-ticks", type=float, default=1.0,
                        help="adverse ticks on the market entry at the reopen")
    parser.add_argument("--exit-slippage-ticks", type=float, default=1.0,
                        help="adverse ticks on stop and deadline market exits")
    parser.add_argument("--fill-buffer-ticks", type=float, default=0.0,
                        help="ticks the market must trade through the target to fill the limit")
    parser.add_argument("--stop-points", type=optional_float, default=None,
                        help="protective stop in MNQ points, or none")

    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--block", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    return parser


def main() -> None:
    global TICK_SIZE, DOLLARS_PER_POINT
    parser = build_parser()
    args = parser.parse_args()
    if args.tick_size <= 0 or args.point_value <= 0:
        raise ValueError("Tick size and point value must be positive")
    TICK_SIZE, DOLLARS_PER_POINT = args.tick_size, args.point_value
    close_times = [item.strip() for item in args.close_times.split(",") if item.strip()]
    for close_time in close_times:
        parse_clock(close_time)
    if args.rule_close not in close_times:
        close_times.append(args.rule_close)

    bars, bar_delta = load_bars(args.data)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    sessions_by_close, trades_by_close, calendars = {}, {}, {}
    grid_rows, matrices = [], []
    for close_time in close_times:
        sessions = build_sessions(
            bars, close_time, args.asia_start, args.asia_end, bar_delta,
            args.max_reference_age_hours, args.min_asia_bars,
        )
        sessions = clip_range(sessions, args.start, args.end, bars.index.tz)
        if sessions.empty:
            parser.error(f"no eligible sessions for the {close_time} reference close")
        calendar = sessions["session_date"].drop_duplicates().sort_values().reset_index(drop=True)
        raw = simulate(
            bars, sessions, bar_delta, args.min_gap_points,
            stop_points=args.stop_points, fill_buffer_ticks=args.fill_buffer_ticks,
        )
        priced = apply_costs(
            raw, args.entry_slippage_ticks, args.exit_slippage_ticks, args.commission_rt
        )
        sessions_by_close[close_time] = sessions
        trades_by_close[close_time] = priced
        calendars[close_time] = calendar

        table, matrix = grid_table(priced, calendar, close_time)
        grid_rows.append(table)
        matrices.append(matrix)

    grid = pd.concat(grid_rows, ignore_index=True).sort_values(
        "per_session_tstat", ascending=False
    ).reset_index(drop=True)
    combined_matrix = pd.concat(matrices, axis=1).fillna(0.0)
    check = reality_check(combined_matrix, args.bootstrap, args.block, args.seed)

    rule_trades = trades_by_close[args.rule_close]
    rule_calendar = calendars[args.rule_close]
    rule_sessions = sessions_by_close[args.rule_close]
    headline = select(rule_trades, args.rule_side, args.rule_max_gap_bps)
    headline_stats = performance(headline, rule_calendar)
    annual = annual_table(headline, rule_calendar)
    single = bootstrap_pvalue(
        session_pnl(headline, rule_calendar), max(args.bootstrap, 1) * 2, args.block, args.seed
    )

    picks, oos = walk_forward(rule_trades, rule_calendar)
    oos_stats = performance(oos, rule_calendar[rule_calendar.dt.year >= picks["test_year"].min()]) if not picks.empty else {}

    raw_gross = simulate(
        bars, rule_sessions, bar_delta, args.min_gap_points,
        stop_points=args.stop_points, fill_buffer_ticks=args.fill_buffer_ticks,
    )
    costs = cost_sweep(
        raw_gross, rule_calendar, args.rule_side, args.rule_max_gap_bps, args.commission_rt
    )
    stops = stop_sweep(
        bars, rule_sessions, bar_delta, rule_calendar, args, args.rule_side, args.rule_max_gap_bps
    )
    buffers, touch_only = buffer_sweep(
        bars, rule_sessions, bar_delta, rule_calendar, args, args.rule_side, args.rule_max_gap_bps
    )
    deadlines = deadline_sweep(
        bars, bar_delta, args, args.rule_close, args.rule_side, args.rule_max_gap_bps
    )
    benchmark = overnight_benchmark(bars, rule_sessions, rule_calendar, args)

    equity = session_pnl(headline, rule_calendar).rename("net_pnl_dollars").to_frame()
    equity["equity_dollars"] = equity["net_pnl_dollars"].cumsum()

    headline.to_csv(args.out_dir / "headline_trades.csv", index=False)
    equity.to_csv(args.out_dir / "headline_equity.csv")
    annual.to_csv(args.out_dir / "headline_annual.csv", index=False)
    grid.to_csv(args.out_dir / "rule_grid.csv", index=False)
    costs.to_csv(args.out_dir / "cost_sweep.csv", index=False)
    stops.to_csv(args.out_dir / "stop_sweep.csv", index=False)
    buffers.to_csv(args.out_dir / "fill_buffer_sweep.csv", index=False)
    deadlines.to_csv(args.out_dir / "deadline_sweep.csv", index=False)
    if not picks.empty:
        picks.to_csv(args.out_dir / "walk_forward.csv", index=False)

    summary = {
        "config": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in vars(args).items()
        },
        "statistics": {
            "start": str(rule_calendar.min()),
            "end": str(rule_calendar.max()),
            "sessions": int(len(rule_calendar)),
        },
        "performance": headline_stats,
        "bootstrap": single,
        "reality_check": check,
        "out_of_sample": {
            "selection": "walk_forward",
            "test_years": int(len(picks)),
            "performance": oos_stats,
        },
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(
            summary,
            indent=2,
            default=lambda value: value.item() if isinstance(value, np.generic) else str(value),
        ),
        encoding="utf-8",
    )

    write_report(
        args.out_dir / "report.md", args, headline_stats, annual, grid, check, single,
        picks, oos_stats, costs, stops, buffers, touch_only, deadlines, benchmark, equity,
    )

    label = f"{args.rule_close} {args.rule_side} <{args.rule_max_gap_bps:g}bps"
    print(f"Headline rule: {label}")
    print(
        f"  trades={headline_stats['trades']} fill={headline_stats['fill_rate']:.1%} "
        f"avg=${headline_stats['avg_net_pnl_dollars']:.2f} t={headline_stats['per_trade_tstat']:.2f} "
        f"total=${headline_stats['total_net_pnl_dollars']:.0f} "
        f"sharpe={headline_stats['sharpe_ratio']:.2f} maxDD=${headline_stats['max_drawdown_dollars']:.0f}"
    )
    if single:
        print(
            f"  pre-specified bootstrap p={single['bootstrap_p_value']:.4f} "
            f"(normal p={single['normal_p_value']:.4f}, skew={single['skewness']:.1f})"
        )
    if check:
        print(
            f"  reality check over {check['rules_searched']} rules: "
            f"best={check['best_rule']} p={check['reality_check_p_value']:.3f}"
        )
    if oos_stats.get("trades"):
        print(
            f"  walk-forward OOS: trades={oos_stats['trades']} "
            f"avg=${oos_stats['avg_net_pnl_dollars']:.2f} total=${oos_stats['total_net_pnl_dollars']:.0f}"
        )
    print(f"Outputs: {args.out_dir}")


def write_report(
    path: Path,
    args: argparse.Namespace,
    headline: dict,
    annual: pd.DataFrame,
    grid: pd.DataFrame,
    check: dict,
    single: dict,
    picks: pd.DataFrame,
    oos_stats: dict,
    costs: pd.DataFrame,
    stops: pd.DataFrame,
    buffers: pd.DataFrame,
    touch_only: dict,
    deadlines: pd.DataFrame,
    benchmark: dict,
    equity: pd.DataFrame,
) -> None:
    label = f"{args.rule_close} reference close, {args.rule_side}, gap < {args.rule_max_gap_bps:g} bps"
    all_in = (
        (args.entry_slippage_ticks + args.exit_slippage_ticks) * TICK_SIZE * DOLLARS_PER_POINT
        + args.commission_rt
    )
    headline_frame = pd.DataFrame([{"rule": label} | headline])
    benchmark_frame = pd.DataFrame([{"rule": "Long the reopen to the deadline"} | benchmark])
    comparison = pd.concat([headline_frame, benchmark_frame], ignore_index=True)

    lines = [
        f"# {args.symbol} Asia gap-fade strategy backtests",
        "",
        "## What this adds to the fill study",
        "",
        "The fill study measured how often the New York close is revisited. This "
        "run trades that observation: a market order at the 18:00 ET reopen, a "
        "resting limit at the reference close, and a flat exit at the deadline, "
        "priced with separate slippage and commission and stressed for stops, "
        "deadlines, queue position, and selection bias.",
        "",
        f"Headline rule: **{label}**.",
        f"Period: {equity.index.min().date()} to {equity.index.max().date()}. "
        f"Costs: {args.entry_slippage_ticks:g} tick entry slippage, "
        f"{args.exit_slippage_ticks:g} tick slippage on stop and deadline exits, "
        f"${args.commission_rt:.2f} commission per round trip "
        f"(${all_in:.2f} all-in when both legs are market orders). "
        f"Stop: {'none' if args.stop_points is None else f'{args.stop_points:g} points'}. "
        f"Size: one {args.symbol} contract, ${DOLLARS_PER_POINT:g} per point and {TICK_SIZE:g} tick size.",
        "",
        "## Headline rule versus passive overnight length",
        "",
        markdown_table(comparison, ["rule"] + PERF_COLUMNS, PERF_FORMATS),
        "",
        "Sharpe uses daily P&L over every session the rule could have traded, so "
        "days the filter stands aside count as zeros.",
        "",
        "## Calendar years",
        "",
        markdown_table(
            annual, ["year"] + PERF_COLUMNS,
            {"year": ".0f"} | PERF_FORMATS,
        ) if not annual.empty else "No calendar-year sample was available.",
        "",
        "## Cost sensitivity",
        "",
        "Slippage is split evenly between the two legs; only market exits pay the "
        "exit leg, so the all-in figure is an upper bound that the mostly-limit "
        "exits do not reach.",
        "",
        markdown_table(
            costs,
            ["slippage_ticks_rt", "all_in_cost_dollars", "trades", "avg_net_pnl_dollars",
             "per_trade_tstat", "total_net_pnl_dollars", "profit_factor", "sharpe_ratio"],
            {"slippage_ticks_rt": ".1f", "all_in_cost_dollars": ".2f",
             "avg_net_pnl_dollars": ".2f", "per_trade_tstat": ".2f",
             "total_net_pnl_dollars": ".0f", "profit_factor": ".2f", "sharpe_ratio": ".2f"},
        ),
        "",
        "## Protective stop",
        "",
        "A stop caps the rare non-fill tail but converts near-misses into realized "
        "losses. When a bar touches both levels the stop is assumed to trade first.",
        "",
        markdown_table(
            stops,
            ["stop_points", "trades", "fill_rate", "stop_rate", "avg_net_pnl_dollars",
             "per_trade_tstat", "total_net_pnl_dollars", "profit_factor",
             "max_drawdown_dollars", "worst_trade_dollars"],
            {"stop_points": ".0f", "fill_rate": ".1%", "stop_rate": ".1%",
             "avg_net_pnl_dollars": ".2f", "per_trade_tstat": ".2f",
             "total_net_pnl_dollars": ".0f", "profit_factor": ".2f",
             "max_drawdown_dollars": ".0f", "worst_trade_dollars": ".0f"},
        ),
        "",
        "## Queue position at the target",
        "",
        "A touch of the limit price is not a fill. Each buffer tick requires the "
        "market to trade that much further through the level before the trade is "
        "counted as filled.",
        "",
        markdown_table(
            buffers,
            ["fill_buffer_ticks", "trades", "fill_rate", "avg_net_pnl_dollars",
             "per_trade_tstat", "total_net_pnl_dollars", "profit_factor", "max_drawdown_dollars"],
            {"fill_buffer_ticks": ".0f", "fill_rate": ".1%", "avg_net_pnl_dollars": ".2f",
             "per_trade_tstat": ".2f", "total_net_pnl_dollars": ".0f",
             "profit_factor": ".2f", "max_drawdown_dollars": ".0f"},
        ),
        "",
    ]
    if touch_only.get("sessions"):
        swing = touch_only["pnl_if_filled"] - touch_only["pnl_if_missed"]
        lines += [
            f"Every buffer removes the same {touch_only['sessions']} sessions "
            f"({touch_only['share_of_trades']:.1%} of trades), because on a "
            "0.25-point grid a session either stops exactly at the target tick or "
            "runs well past it. Those sessions are the entire result: filled they "
            f"contribute ${touch_only['pnl_if_filled']:.0f}, missed they cost "
            f"${touch_only['pnl_if_missed']:.0f}, a ${swing:.0f} swing against a "
            f"${touch_only['total_net_pnl_dollars']:.0f} total. The dates are "
            f"{touch_only['dates']}.",
            "",
            "Reality sits between the two rows. A limit resting since 18:00 has "
            "hours of queue priority and often does fill on an exact touch, but "
            "the strategy's whole margin rides on that handful of nights, which "
            "is a thin place for an edge to live.",
            "",
        ]
    lines += [
        "## Deadline",
        "",
        markdown_table(
            deadlines,
            ["asia_end", "trades", "fill_rate", "avg_net_pnl_dollars", "per_trade_tstat",
             "total_net_pnl_dollars", "profit_factor", "max_drawdown_dollars", "avg_minutes_held"],
            {"fill_rate": ".1%", "avg_net_pnl_dollars": ".2f", "per_trade_tstat": ".2f",
             "total_net_pnl_dollars": ".0f", "profit_factor": ".2f",
             "max_drawdown_dollars": ".0f", "avg_minutes_held": ".0f"},
        ),
        "",
        "## Is the edge real?",
        "",
    ]
    if single:
        lines += [
            "### The rule on its own terms",
            "",
            "Per-session P&L is not remotely normal, so the ordinary t-statistic "
            "is the wrong yardstick. A circular block bootstrap of the demeaned "
            "series measures the same statistic against the shape the data "
            "actually has.",
            "",
            f"- Per-session skewness {single['skewness']:.1f}, excess kurtosis "
            f"{single['excess_kurtosis']:.0f}: many small target wins, rare large "
            "non-fill losses.",
            f"- Observed t-statistic {single['observed_tstat']:.2f}; normal-theory "
            f"p-value {single['normal_p_value']:.4f}.",
            f"- Block bootstrap p-value **{single['bootstrap_p_value']:.4f}** over "
            f"{single['iterations']} resamples, with the null 95th percentile at "
            f"t = {single['null_tstat_p95']:.2f}.",
            "",
            "The left skew cuts both ways. It compresses the upper tail of the "
            "null, so a positive mean of this size is harder to fake than normal "
            "theory implies, but it also means the loss distribution is where the "
            "risk lives: the average is safe long before any single night is.",
            "",
        ]
    lines += [
        "## Every competing rule",
        "",
        "The headline rule was chosen after seeing this whole surface, so its "
        "statistics are the maximum of a search rather than a clean test.",
        "",
        markdown_table(
            grid.head(20),
            ["reference_close", "side", "max_gap_bps", "trades", "fill_rate",
             "avg_net_pnl_dollars", "per_trade_tstat", "per_session_tstat",
             "total_net_pnl_dollars", "sharpe_ratio", "max_drawdown_dollars"],
            {"max_gap_bps": ".1f", "fill_rate": ".1%", "avg_net_pnl_dollars": ".2f",
             "per_trade_tstat": ".2f", "per_session_tstat": ".2f",
             "total_net_pnl_dollars": ".0f", "sharpe_ratio": ".2f",
             "max_drawdown_dollars": ".0f"},
        ),
        "",
    ]
    if check:
        lines += [
            "### Reality check",
            "",
            f"- Rules searched: {check['rules_searched']}",
            f"- Best rule by per-session t-statistic: `{check['best_rule']}` at "
            f"t = {check['best_per_session_tstat']:.2f}",
            f"- Stationary block bootstrap ({check['iterations']} resamples, "
            f"{args.block}-session blocks) under the no-edge null puts the 95th "
            f"percentile of the best t-statistic at {check['null_max_tstat_p95']:.2f}",
            f"- Reality-check p-value: **{check['reality_check_p_value']:.3f}**",
            "",
            "The p-value asks whether the best rule in the search beats what the "
            "best of an equally large search would produce on data with no edge.",
            "",
        ]
    if not picks.empty:
        lines += [
            "## Walk-forward selection",
            "",
            "Each year's rule is chosen only from earlier data, by in-sample "
            "per-trade t-statistic among rules with at least 100 prior trades.",
            "",
            markdown_table(
                picks,
                ["test_year", "chosen_side", "chosen_max_gap_bps", "train_trades",
                 "train_tstat", "train_avg_net_pnl_dollars", "trades",
                 "avg_net_pnl_dollars", "total_net_pnl_dollars", "profit_factor"],
                {"test_year": ".0f", "chosen_max_gap_bps": ".1f", "train_tstat": ".2f",
                 "train_avg_net_pnl_dollars": ".2f", "avg_net_pnl_dollars": ".2f",
                 "total_net_pnl_dollars": ".0f", "profit_factor": ".2f"},
            ),
            "",
        ]
        if oos_stats.get("trades"):
            lines += [
                f"Pooled out-of-sample: {oos_stats['trades']} trades, "
                f"${oos_stats['avg_net_pnl_dollars']:.2f} average, "
                f"t = {oos_stats['per_trade_tstat']:.2f}, "
                f"${oos_stats['total_net_pnl_dollars']:.0f} total, "
                f"profit factor {oos_stats['profit_factor']:.2f}, "
                f"max drawdown ${oos_stats['max_drawdown_dollars']:.0f}.",
                "",
            ]
    lines += [
        "## What the numbers do not cover",
        "",
        "- The source is an unadjusted Databento continuous front-month series. A "
        "roll switch at the 18:00 reopen cannot be identified or removed here.",
        "- Limit fills are modelled from bar extremes. The buffer sweep bounds the "
        "queue-position error but does not replace order-book data.",
        "- Stop and target order inside a bar is unobservable at 5-minute "
        "resolution; the stop is always assumed to win.",
        "- One contract throughout. There is no compounding, no margin check, and "
        "no position sizing, so Sharpe describes the shape of the P&L rather than "
        "the return on an account.",
        "- The walk-forward test validates the selection procedure, not the "
        "already-published rule, which no longer has untouched data available.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
