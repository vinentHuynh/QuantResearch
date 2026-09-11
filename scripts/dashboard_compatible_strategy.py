"""Run migrated strategy families on the dashboard's normalized Databento bars.

This is the stable execution contract for older research scripts.  A strategy is
selected by id; market data, contract economics, parameters, and the output
directory are injected by the dashboard.  No strategy in this module owns a
symbol-specific path.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


TREND = {"multi-speed-momentum", "moving-average-trend"}
RELATIVE = {"cross-sectional-momentum", "pairs-mean-reversion"}
LEVEL = {"prior-range-fill"}
ORB = {"opening-range-breakout"}
OVERNIGHT = {"overnight-session"}
TIMEFRAME_RULES = {
    "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1h": "1h", "4h": "4h", "1d": "1D",
}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Normalized Databento strategy runner")
    ap.add_argument("--strategy-id", required=True)
    ap.add_argument("--one-minute", type=Path, required=True)
    ap.add_argument("--timeframe", choices=tuple(TIMEFRAME_RULES), required=True)
    ap.add_argument("--peer-data", default="", help="CSV of SYMBOL=one-minute-path peers")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--tick-size", type=float, required=True)
    ap.add_argument("--point-value", type=float, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--capital", type=float, default=100_000)
    ap.add_argument("--lookback", type=int, default=60)
    ap.add_argument("--opening-range-minutes", type=int, default=15)
    ap.add_argument("--session", choices=("RTH", "Asia"), default="RTH")
    ap.add_argument("--entry-time", default="18:00")
    ap.add_argument("--exit-time", default="06:00")
    ap.add_argument("--stop-multiple", type=float, default=1.0)
    ap.add_argument("--target-multiple", type=float, default=2.0)
    ap.add_argument("--direction-model", choices=("Long", "Prior trend"), default="Long")
    ap.add_argument("--bracket-exit", action="store_true")
    ap.add_argument("--max-prior-range-pct", type=float, default=0.0)
    ap.add_argument("--cost-ticks", type=float, default=1.0)
    return ap.parse_args()


def load_bars(path: Path, start: str | None, end: str | None, timeframe: str = "1m") -> pd.DataFrame:
    frame = pd.read_parquet(path)
    if not isinstance(frame.index, pd.DatetimeIndex):
        timestamp = next((name for name in ("ts_event", "timestamp", "datetime", "date") if name in frame), None)
        if timestamp is None:
            raise ValueError(f"{path} has no DatetimeIndex or timestamp column")
        frame = frame.set_index(pd.to_datetime(frame.pop(timestamp), utc=True))
    elif frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")
    else:
        frame.index = frame.index.tz_convert("UTC")
    frame.columns = [str(column).lower() for column in frame.columns]
    required = {"open", "high", "low", "close"}
    if not required.issubset(frame.columns):
        raise ValueError(f"{path} is missing OHLC columns: {sorted(required - set(frame.columns))}")
    frame = frame.sort_index()[~frame.index.duplicated(keep="last")]
    if start:
        frame = frame.loc[frame.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        frame = frame.loc[frame.index < pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)]
    if timeframe != "1m":
        aggregation = {"open": "first", "high": "max", "low": "min", "close": "last"}
        if "volume" in frame.columns:
            aggregation["volume"] = "sum"
        frame = frame.resample(TIMEFRAME_RULES[timeframe]).agg(aggregation).dropna(subset=["open", "high", "low", "close"])
    if frame.empty:
        raise ValueError("No bars remain in the selected date window")
    return frame


def bar_close(path: Path, start: str | None, end: str | None, timeframe: str) -> pd.Series:
    return load_bars(path, start, end, timeframe)["close"]


def peer_paths(raw: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for item in filter(None, raw.split(",")):
        symbol, value = item.split("=", 1)
        result[symbol] = Path(value)
    return result


def trade_frame(pnls: list[dict[str, object]]) -> pd.DataFrame:
    columns = ["entry_time", "exit_time", "side", "entry", "exit", "gross_pnl", "cost", "net_pnl", "reason"]
    return pd.DataFrame(pnls, columns=columns)


def run_trend(args: argparse.Namespace) -> tuple[pd.DataFrame, str]:
    close = bar_close(args.one_minute, args.start, args.end, args.timeframe)
    if args.strategy_id == "multi-speed-momentum":
        windows = sorted({max(5, args.lookback // 3), args.lookback, args.lookback * 2, args.lookback * 4})
        signal = sum(np.sign(close.pct_change(window)) for window in windows) / len(windows)
        method = f"four-speed time-series momentum ({windows})"
    else:
        signal = (close > close.rolling(args.lookback).mean()).astype(float)
        method = f"long/flat {args.lookback}-session moving-average trend"
    position = signal.shift(1).fillna(0)
    point_move = close.diff().fillna(0)
    gross = position * point_move * args.point_value
    cost = position.diff().abs().fillna(position.abs()) * args.cost_ticks * args.tick_size * args.point_value
    rows = []
    for ts in close.index[position != 0]:
        rows.append({"entry_time": ts.isoformat(), "exit_time": ts.isoformat(), "side": "long" if position.loc[ts] > 0 else "short", "entry": close.shift(1).loc[ts], "exit": close.loc[ts], "gross_pnl": gross.loc[ts], "cost": cost.loc[ts], "net_pnl": gross.loc[ts] - cost.loc[ts], "reason": "daily_mark"})
    return trade_frame(rows), method


def run_relative(args: argparse.Namespace) -> tuple[pd.DataFrame, str]:
    paths = peer_paths(args.peer_data)
    paths[args.symbol] = args.one_minute
    panel = pd.concat({symbol: bar_close(path, args.start, args.end, args.timeframe) for symbol, path in paths.items()}, axis=1).dropna(how="all")
    returns = panel.pct_change()
    score = panel.pct_change(args.lookback).shift(1)
    if args.strategy_id == "pairs-mean-reversion":
        peer = next((name for name in panel if name != args.symbol), None)
        if peer is None:
            raise ValueError("Relative-value strategy needs at least two Databento charts")
        ratio = np.log(panel[args.symbol]) - np.log(panel[peer])
        z = (ratio - ratio.rolling(args.lookback).mean()) / ratio.rolling(args.lookback).std()
        position = -np.sign(z.shift(1)).where(z.shift(1).abs() >= 1, 0)
        net_return = .5 * position * (returns[args.symbol] - returns[peer])
        method = f"market-neutral {args.symbol}/{peer} rolling-z-score pairs"
    else:
        ranks = score.rank(axis=1, pct=True)
        weights = (ranks >= .67).astype(float) - (ranks <= .33).astype(float)
        weights = weights.div(weights.abs().sum(axis=1), axis=0).fillna(0)
        net_return = (weights * returns).sum(axis=1)
        method = f"cross-sectional momentum across {', '.join(panel.columns)}"
    gross = net_return.fillna(0) * args.capital
    turnover = net_return.notna().astype(float)
    cost = turnover * args.cost_ticks * args.tick_size * args.point_value
    rows = [{"entry_time": ts.isoformat(), "exit_time": ts.isoformat(), "side": "spread", "entry": math.nan, "exit": math.nan, "gross_pnl": gross.loc[ts], "cost": cost.loc[ts], "net_pnl": gross.loc[ts] - cost.loc[ts], "reason": "portfolio_mark"} for ts in gross.index if gross.loc[ts] != 0]
    return trade_frame(rows), method


def run_orb(args: argparse.Namespace) -> tuple[pd.DataFrame, str]:
    bars = load_bars(args.one_minute, args.start, args.end, args.timeframe).tz_convert("America/New_York")
    asia = args.session == "Asia"
    session = bars.between_time("18:00", "02:55") if asia else bars.between_time("09:30", "15:59")
    session_dates = (session.index - pd.Timedelta(hours=18)).date if asia else session.index.date
    rows: list[dict[str, object]] = []
    for _, day in session.groupby(session_dates):
        range_end = day.index[0] + pd.Timedelta(minutes=args.opening_range_minutes)
        opening, later = day[day.index < range_end], day[day.index >= range_end]
        if opening.empty or later.empty:
            continue
        high, low = float(opening.high.max()), float(opening.low.min())
        candidates = later[(later.close > high) | (later.close < low)]
        if candidates.empty:
            continue
        entry_ts = candidates.index[0]
        entry = float(candidates.iloc[0].close)
        side = 1 if entry > high else -1
        risk = max(high - low, args.tick_size)
        stop = entry - side * risk * args.stop_multiple
        target = entry + side * risk * args.target_multiple
        after = later.loc[entry_ts:]
        exit_price, exit_ts, reason = float(after.iloc[-1].close), after.index[-1], "session_close"
        for ts, bar in after.iloc[1:].iterrows():
            stop_hit = bar.low <= stop if side > 0 else bar.high >= stop
            target_hit = bar.high >= target if side > 0 else bar.low <= target
            if stop_hit or target_hit:
                exit_price, exit_ts, reason = (stop, ts, "stop") if stop_hit else (target, ts, "target")
                break
        gross = side * (exit_price - entry) * args.point_value
        cost = args.cost_ticks * args.tick_size * args.point_value
        rows.append({"entry_time": entry_ts.isoformat(), "exit_time": exit_ts.isoformat(), "side": "long" if side > 0 else "short", "entry": entry, "exit": exit_price, "gross_pnl": gross, "cost": cost, "net_pnl": gross - cost, "reason": reason})
    market = "Asia" if asia else "RTH"
    return trade_frame(rows), f"{market} {args.opening_range_minutes}-minute breakout with {args.stop_multiple:g}R stop and {args.target_multiple:g}R target"


def run_level(args: argparse.Namespace) -> tuple[pd.DataFrame, str]:
    bars = load_bars(args.one_minute, args.start, args.end, args.timeframe).tz_convert("America/New_York").between_time("09:30", "15:59")
    daily = bars.groupby(bars.index.date).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
    rows: list[dict[str, object]] = []
    for index in range(1, len(daily)):
        prior, today = daily.iloc[index - 1], daily.iloc[index]
        if today.open < prior.low and today.high >= prior.low:
            side, entry = -1, float(prior.low)
        elif today.open > prior.high and today.low <= prior.high:
            side, entry = 1, float(prior.high)
        else:
            continue
        exit_price = float(today.close)
        gross = side * (exit_price - entry) * args.point_value
        cost = args.cost_ticks * args.tick_size * args.point_value
        ts = pd.Timestamp(daily.index[index], tz="America/New_York")
        rows.append({"entry_time": ts.isoformat(), "exit_time": ts.isoformat(), "side": "long" if side > 0 else "short", "entry": entry, "exit": exit_price, "gross_pnl": gross, "cost": cost, "net_pnl": gross - cost, "reason": "rth_close"})
    return trade_frame(rows), "prior-day range backfill with close exit"


def run_overnight(args: argparse.Namespace) -> tuple[pd.DataFrame, str]:
    bars = load_bars(args.one_minute, args.start, args.end, args.timeframe).tz_convert("America/New_York")
    shifted_date = (bars.index - pd.Timedelta(hours=18)).date
    rows: list[dict[str, object]] = []
    for _, group in bars.groupby(shifted_date):
        window = group.between_time(args.entry_time, args.exit_time, inclusive="both")
        if len(window) < 2:
            continue
        entry_ts, exit_ts = window.index[0], window.index[-1]
        entry, exit_price = float(window.iloc[0].open), float(window.iloc[-1].close)
        prior = bars[bars.index < entry_ts].tail(288)
        side = 1
        if args.direction_model == "Prior trend" and len(prior) > 3:
            side = 1 if float(prior.iloc[-1].close) >= float(prior.iloc[0].open) else -1
        prior_range = float(prior.high.max() - prior.low.min()) if not prior.empty else math.nan
        if args.max_prior_range_pct > 0:
            if not np.isfinite(prior_range) or prior_range > entry * args.max_prior_range_pct / 100:
                continue
        if args.bracket_exit:
            if prior.empty:
                continue
            risk = max(prior_range * .25, args.tick_size)
            stop = entry - side * risk * args.stop_multiple
            target = entry + side * risk * args.target_multiple
            for ts, bar in window.iloc[1:].iterrows():
                stop_hit = bar.low <= stop if side > 0 else bar.high >= stop
                target_hit = bar.high >= target if side > 0 else bar.low <= target
                if stop_hit or target_hit:
                    exit_price, exit_ts = (stop, ts) if stop_hit else (target, ts)
                    break
        gross = side * (exit_price - entry) * args.point_value
        cost = args.cost_ticks * args.tick_size * args.point_value
        rows.append({"entry_time": entry_ts.isoformat(), "exit_time": exit_ts.isoformat(), "side": "long" if side > 0 else "short", "entry": entry, "exit": exit_price, "gross_pnl": gross, "cost": cost, "net_pnl": gross - cost, "reason": "overnight_exit"})
    return trade_frame(rows), f"normalized Databento overnight block {args.entry_time}-{args.exit_time} ET"


def metrics(trades: pd.DataFrame, capital: float) -> dict[str, float | int]:
    pnl = trades.net_pnl.astype(float) if not trades.empty else pd.Series(dtype=float)
    equity = capital + pnl.cumsum()
    high_water = pd.concat([pd.Series([capital]), equity], ignore_index=True).cummax().iloc[1:].set_axis(equity.index)
    drawdown = equity - high_water
    wins, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    sharpe = float(pnl.mean() / pnl.std(ddof=1) * np.sqrt(252)) if len(pnl) > 1 and pnl.std(ddof=1) > 0 else 0.0
    return {
        "sessions": int(len(trades)), "trades": int(len(trades)), "net_dollars": float(pnl.sum()),
        "gross_dollars": float(trades.gross_pnl.sum()) if not trades.empty else 0.0,
        "cost_dollars": float(trades.cost.sum()) if not trades.empty else 0.0,
        "profit_factor": float(wins / losses) if losses > 0 else (999.0 if wins > 0 else 0.0),
        "sharpe": sharpe, "win_rate": float((pnl > 0).mean()) if len(pnl) else 0.0,
        "max_drawdown_dollars": float(drawdown.min()) if len(drawdown) else 0.0,
    }


def main() -> None:
    args = parse_args()
    if args.strategy_id in TREND:
        trades, method = run_trend(args)
    elif args.strategy_id in RELATIVE:
        trades, method = run_relative(args)
    elif args.strategy_id in LEVEL:
        trades, method = run_level(args)
    elif args.strategy_id in ORB:
        trades, method = run_orb(args)
    elif args.strategy_id in OVERNIGHT:
        trades, method = run_overnight(args)
    else:
        raise ValueError(f"Unsupported migrated strategy: {args.strategy_id}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stats = metrics(trades, args.capital)
    trades.to_csv(args.output_dir / "trades.csv", index=False)
    equity = pd.DataFrame({
        "event_time": trades.exit_time if not trades.empty else [],
        "net_pnl": trades.net_pnl if not trades.empty else [],
        "equity": args.capital + (trades.net_pnl.cumsum() if not trades.empty else pd.Series(dtype=float)),
    })
    equity.to_csv(args.output_dir / "equity.csv", index=False)
    summary = {
        "strategy_id": args.strategy_id, "symbol": args.symbol, "timeframe": args.timeframe, "methodology": method,
        "statistics": stats,
        "costs": {"round_trip_ticks": args.cost_ticks, "tick_size": args.tick_size, "point_value": args.point_value},
        "evaluation_period": {"start": args.start, "end": args.end},
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
