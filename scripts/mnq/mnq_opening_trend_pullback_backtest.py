"""Mechanical MNQ backtest of the Opening Trend-Pullback plan.

Signals use completed 5-minute bars; bracket fills use 1-minute bars. The source
plan contains discretionary language, so exact research definitions are saved
with every run.

    .venv/bin/python scripts/mnq/mnq_opening_trend_pullback_backtest.py
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = (ROOT / "data" / "mnq_dom_sample" / "full_history" /
                "ohlcv-1m" / "candles_1m.parquet")
DEFAULT_OUTPUT = ROOT / "reports" / "mnq_opening_trend_pullback"
TZ = "America/New_York"
OHLCV = ["open", "high", "low", "close", "volume"]
TICK = 0.25
DOLLARS_PER_POINT = 2.0


@dataclass(frozen=True)
class Config:
    symbol: str = "MNQ"
    tick_size: float = 0.25
    point_value: float = 2.0
    account: float = 25_000.0
    risk_dollars: float = 100.0
    atr_period: int = 14
    zone_atr: float = 0.10
    stop_buffer_ticks: int = 2
    minimum_rr: float = 1.0
    maximum_trades: int = 3
    daily_goal_points: float = 10.0
    daily_stop_r: float = -2.0
    commission_rt: float = 1.24
    slippage_ticks_rt: float = 2.0
    bias_flip_exit: bool = False


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--symbol", default="MNQ", help="chart/instrument label")
    parser.add_argument("--tick-size", type=float, default=0.25)
    parser.add_argument("--point-value", type=float, default=2.0)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--account", type=float, default=25_000)
    parser.add_argument("--risk-dollars", type=float, default=100)
    parser.add_argument("--minimum-rr", type=float, default=1.0)
    parser.add_argument("--zone-atr", type=float, default=0.10)
    parser.add_argument("--commission-rt", type=float, default=1.24)
    parser.add_argument("--slippage-ticks-rt", type=float, default=2.0)
    parser.add_argument("--bias-flip-exit", action="store_true")
    parser.add_argument("--no-roll-adjust", action="store_true")
    return parser.parse_args()


def load_minutes(path: Path, roll_adjust: bool = True) -> tuple[pd.DataFrame, int]:
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_parquet(path, columns=OHLCV + ["instrument_id"]).sort_index()
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("Input must have a timezone-aware DatetimeIndex")
    if frame.index.has_duplicates or frame[OHLCV].isna().any().any():
        raise ValueError("Input has duplicate timestamps or missing OHLCV values")
    ids = frame["instrument_id"].to_numpy()
    changes = np.flatnonzero(ids[1:] != ids[:-1]) + 1
    if roll_adjust:
        close = frame["close"].to_numpy()
        adjustment = np.zeros(len(frame), dtype=float)
        for pos in changes:
            gap = round((close[pos] - close[pos - 1]) / TICK) * TICK
            adjustment[:pos] += gap
        for column in ("open", "high", "low", "close"):
            frame[column] = frame[column].to_numpy() + adjustment
    return frame.tz_convert(TZ), len(changes)


def session_date(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Calendar date in New York; suitable for this RTH-only strategy."""
    return index.normalize().tz_localize(None)


def make_five_minute(minutes: pd.DataFrame) -> pd.DataFrame:
    bars = minutes[OHLCV].resample("5min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last",
         "volume": "sum"}).dropna(subset=["open"])
    bars["date"] = session_date(bars.index)
    typical = (bars.high + bars.low + bars.close) / 3.0
    rth = ((bars.index.time >= pd.Timestamp("09:30").time()) &
           (bars.index.time < pd.Timestamp("16:00").time()))
    bars["vwap_num"] = (typical * bars.volume).where(rth, 0.0)
    bars["rth_volume"] = bars.volume.where(rth, 0.0)
    bars["vwap"] = (bars.groupby("date").vwap_num.cumsum() /
                    bars.groupby("date").rth_volume.cumsum().replace(0, np.nan))
    previous = bars.close.shift(1)
    bars["tr"] = pd.concat([(bars.high - bars.low), (bars.high - previous).abs(),
                            (bars.low - previous).abs()], axis=1).max(axis=1)
    return bars


def value_area(rth: pd.DataFrame) -> tuple[float, float, float]:
    """70% close-volume profile at MNQ's tick size (POC, VAH, VAL)."""
    ticks = np.rint(rth.close.to_numpy() / TICK).astype(np.int64)
    base, top = int(ticks.min()), int(ticks.max())
    counts = np.bincount(ticks - base, weights=rth.volume.to_numpy(),
                         minlength=top - base + 1)
    poc = int(np.flatnonzero(counts == counts.max())[0])
    lo = hi = poc
    running, target = counts[poc], counts.sum() * 0.70
    while running < target and (lo > 0 or hi < len(counts) - 1):
        below = counts[lo - 1] if lo > 0 else -1
        above = counts[hi + 1] if hi < len(counts) - 1 else -1
        if above >= below:
            hi += 1
            running += counts[hi]
        else:
            lo -= 1
            running += counts[lo]
    return (base + poc) * TICK, (base + hi) * TICK, (base + lo) * TICK


def contexts(minutes: pd.DataFrame, bars: pd.DataFrame) -> dict[pd.Timestamp, dict[str, float]]:
    dates = sorted(session_date(minutes.index).unique())
    rth = minutes.between_time("09:30", "15:59").copy()
    rth["date"] = session_date(rth.index)
    completed: dict[pd.Timestamp, dict[str, float]] = {}
    for date, group in rth.groupby("date"):
        if len(group) >= 300:
            poc, vah, val = value_area(group)
            completed[pd.Timestamp(date)] = {
                "pdh": float(group.high.max()), "pdl": float(group.low.min()),
                "pdc": float(group.close.iloc[-1]), "poc": poc, "vah": vah,
                "val": val,
            }
    ordered = sorted(completed)
    prior_for = {ordered[i]: completed[ordered[i - 1]] for i in range(1, len(ordered))}
    result: dict[pd.Timestamp, dict[str, float]] = {}
    local_dates = session_date(minutes.index)
    for date_value in dates:
        date = pd.Timestamp(date_value)
        if date not in prior_for:
            continue
        day = minutes[local_dates == date]
        prior_date = date - pd.Timedelta(days=1)
        evening = minutes[local_dates == prior_date].between_time("18:00", "23:59")
        overnight = pd.concat([evening, day.between_time("00:00", "09:29")]).sort_index()
        premarket = day.between_time("04:00", "09:29")
        opening = day.between_time("09:30", "09:44")
        boundary = date.tz_localize(TZ) + pd.Timedelta(hours=9, minutes=30)
        pre_bars = bars[bars.index < boundary]
        if (len(overnight) < 60 or len(premarket) < 30 or len(opening) < 10 or
                len(pre_bars) < 14):
            continue
        ctx = dict(prior_for[date])
        ctx.update({
            "onh": float(overnight.high.max()), "onl": float(overnight.low.min()),
            "pmh": float(premarket.high.max()), "pml": float(premarket.low.min()),
            "orh": float(opening.high.max()), "orl": float(opening.low.min()),
            "atr": float(pre_bars.tr.iloc[-14:].mean()),
        })
        result[date] = ctx
    return result


def trend_features(day: pd.DataFrame, ctx: dict[str, float]) -> pd.DataFrame:
    """Online 1-left/1-right confirmed pivots and the plan's three-part bias."""
    out = day.copy()
    bias, swing_low, swing_high = [], [], []
    highs: list[tuple[pd.Timestamp, float]] = []
    lows: list[tuple[pd.Timestamp, float]] = []
    values = out.reset_index()
    timestamp_column = values.columns[0]
    for i, row in values.iterrows():
        if i >= 2:
            a, b, c = values.iloc[i - 2], values.iloc[i - 1], row
            if b.high > a.high and b.high >= c.high:
                highs.append((b[timestamp_column], float(b.high)))
            if b.low < a.low and b.low <= c.low:
                lows.append((b[timestamp_column], float(b.low)))
        structure_long = (len(highs) >= 2 and len(lows) >= 2 and
                          highs[-1][1] > highs[-2][1] and lows[-1][1] > lows[-2][1])
        structure_short = (len(highs) >= 2 and len(lows) >= 2 and
                           highs[-1][1] < highs[-2][1] and lows[-1][1] < lows[-2][1])
        long = structure_long and row.close > row.vwap and row.close >= ctx["orh"]
        short = structure_short and row.close < row.vwap and row.close <= ctx["orl"]
        bias.append(1 if long else (-1 if short else 0))
        prior_time = values.iloc[i - 1][timestamp_column] if i else None
        swing_low.append(lows[-2][1] if len(lows) >= 2 and lows[-1][0] == prior_time
                         else (lows[-1][1] if lows else np.nan))
        swing_high.append(highs[-2][1] if len(highs) >= 2 and highs[-1][0] == prior_time
                          else (highs[-1][1] if highs else np.nan))
    out["bias"] = bias
    out["prior_swing_low"] = swing_low
    out["prior_swing_high"] = swing_high
    return out


def crossed_level(history: pd.DataFrame, level: float, side: int) -> bool:
    closes = history.close.to_numpy()
    if len(closes) < 2:
        return False
    if side > 0:
        return bool(np.any((closes[:-1] <= level) & (closes[1:] > level)))
    return bool(np.any((closes[:-1] >= level) & (closes[1:] < level)))


def find_zone(feature: pd.DataFrame, i: int, ctx: dict[str, float], side: int,
              tolerance: float) -> tuple[str, float] | None:
    previous, current = feature.iloc[i - 1], feature.iloc[i]
    lo, hi = min(previous.low, current.low), max(previous.high, current.high)
    zones: list[tuple[str, float]] = [
        ("vwap", float(previous.vwap)),
        ("opening_range", ctx["orh" if side > 0 else "orl"]),
    ]
    swing = current.prior_swing_low if side > 0 else current.prior_swing_high
    if pd.notna(swing):
        zones.append(("prior_swing", float(swing)))
    history = feature.iloc[:i]
    for name in ("pdh", "pdl", "pdc", "poc", "vah", "val", "onh", "onl", "pmh", "pml"):
        level = ctx[name]
        if crossed_level(history, level, side):
            zones.append((name, level))
    touched = [(name, level) for name, level in zones
               if lo - tolerance <= level <= hi + tolerance]
    if not touched:
        return None
    midpoint = (previous.close + current.close) / 2.0
    return min(touched, key=lambda item: abs(item[1] - midpoint))


def candidates(feature: pd.DataFrame, ctx: dict[str, float], cfg: Config) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    tolerance = cfg.zone_atr * ctx["atr"]
    for i in range(4, len(feature)):
        current, previous = feature.iloc[i], feature.iloc[i - 1]
        if (current.name.time() < pd.Timestamp("09:45").time() or
                current.name.time() >= pd.Timestamp("10:55").time()):
            continue
        side = int(current.bias)
        if (not side or side * (previous.close - previous.open) >= 0 or
                side * (current.close - current.open) <= 0):
            continue
        impulse = feature.iloc[max(0, i - 4):i - 1]
        mean_body = (impulse.close - impulse.open).abs().mean()
        if impulse.empty or abs(previous.close - previous.open) >= mean_body:
            continue
        if previous.volume >= impulse.volume.mean():
            continue
        structural = current.prior_swing_low if side > 0 else current.prior_swing_high
        if (pd.isna(structural) or
                (side > 0 and min(previous.low, current.low) <= structural) or
                (side < 0 and max(previous.high, current.high) >= structural)):
            continue
        zone = find_zone(feature, i, ctx, side, tolerance)
        if zone is None:
            continue
        result.append({
            "bar_time": current.name,
            "entry_time": current.name + pd.Timedelta(minutes=5),
            "side": side, "entry": float(current.close), "zone": zone[0],
            "zone_level": zone[1],
            "pullback_low": float(min(previous.low, current.low)),
            "pullback_high": float(max(previous.high, current.high)),
        })
    return result


def fixed_levels(ctx: dict[str, float]) -> list[tuple[str, float]]:
    names = ("pdh", "pdl", "pdc", "poc", "vah", "val", "onh", "onl",
             "pmh", "pml", "orh", "orl")
    return [(name, ctx[name]) for name in names]


def plan_trade(signal: dict[str, Any], ctx: dict[str, float], cfg: Config) -> dict[str, Any] | None:
    side, entry = signal["side"], signal["entry"]
    buffer = cfg.stop_buffer_ticks * TICK
    stop_map = {
        "key": signal["zone_level"] - side * buffer,
        "atr": entry - side * ctx["atr"],
        "swing": (signal["pullback_low"] - buffer if side > 0
                  else signal["pullback_high"] + buffer),
    }
    stop = min(stop_map.values()) if side > 0 else max(stop_map.values())
    risk = side * (entry - stop)
    if risk <= 0:
        return None
    targets = [(name, value) for name, value in fixed_levels(ctx)
               if side * (value - entry) >= TICK]
    if not targets:
        return None
    target_name, target = min(targets, key=lambda item: side * (item[1] - entry))
    reward = side * (target - entry)
    rr = reward / risk
    contracts = int(np.floor(cfg.risk_dollars / (risk * DOLLARS_PER_POINT)))
    if rr < cfg.minimum_rr or contracts < 1:
        return None
    furthest = min(stop_map.values()) if side > 0 else max(stop_map.values())
    winners = "+".join(name for name, value in stop_map.items()
                       if abs(value - furthest) < 1e-9)
    return {**signal, "stop": stop, "stop_points": risk, "stop_winner": winners,
            "target": target, "target_level": target_name, "target_points": reward,
            "planned_rr": rr, "contracts": contracts, "atr": ctx["atr"]}


def execute(trade: dict[str, Any], minutes: pd.DataFrame, feature: pd.DataFrame,
            cfg: Config) -> dict[str, Any]:
    side = trade["side"]
    session_end = trade["bar_time"].normalize() + pd.Timedelta(hours=11)
    path = minutes[(minutes.index >= trade["entry_time"]) & (minutes.index < session_end)]
    exit_price, reason, exit_time = None, "time", None
    bias_by_close = {idx + pd.Timedelta(minutes=5): int(row.bias)
                     for idx, row in feature.iterrows()}
    for timestamp, bar in path.iterrows():
        stop_hit = bar.low <= trade["stop"] if side > 0 else bar.high >= trade["stop"]
        target_hit = bar.high >= trade["target"] if side > 0 else bar.low <= trade["target"]
        if stop_hit:  # conservative if both are touched in the same 1-minute bar
            exit_price, reason, exit_time = trade["stop"], "stop", timestamp
            break
        if target_hit:
            exit_price, reason, exit_time = trade["target"], "target", timestamp
            break
        boundary = timestamp.floor("5min") + pd.Timedelta(minutes=5)
        if (cfg.bias_flip_exit and timestamp.minute % 5 == 4 and
                bias_by_close.get(boundary) == -side):
            exit_price, reason, exit_time = float(bar.close), "bias_flip", timestamp
            break
    if exit_price is None:
        if path.empty:
            exit_price, exit_time = trade["entry"], trade["entry_time"]
        else:
            exit_price, exit_time = float(path.close.iloc[-1]), path.index[-1]
    gross_points = side * (exit_price - trade["entry"])
    cost_points = cfg.slippage_ticks_rt * TICK + cfg.commission_rt / DOLLARS_PER_POINT
    net_points = gross_points - cost_points
    return {
        **trade, "exit_time": exit_time, "exit": exit_price, "exit_reason": reason,
        "gross_points": gross_points, "cost_points": cost_points,
        "net_points": net_points, "net_r": net_points / trade["stop_points"],
        "gross_dollars": gross_points * DOLLARS_PER_POINT * trade["contracts"],
        "net_dollars": net_points * DOLLARS_PER_POINT * trade["contracts"],
    }


def backtest(minutes: pd.DataFrame, bars: pd.DataFrame,
             ctxs: dict[pd.Timestamp, dict[str, float]], cfg: Config,
             start: str | None, end: str | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    days: list[dict[str, Any]] = []
    dates = sorted(ctxs)
    if start:
        dates = [date for date in dates if date >= pd.Timestamp(start)]
    if end:
        dates = [date for date in dates if date <= pd.Timestamp(end)]
    minute_dates, bar_dates = session_date(minutes.index), session_date(bars.index)
    for date in dates:
        one = minutes[minute_dates == date]
        five = bars[bar_dates == date].between_time("09:30", "10:59").copy()
        if len(one.between_time("09:30", "10:59")) < 80 or len(five) < 17:
            continue
        feature = trend_features(five, ctxs[date])
        signals = candidates(feature, ctxs[date], cfg)
        last_exit = date.tz_localize(TZ)
        cumulative_points = cumulative_r = cumulative_dollars = 0.0
        trades_today = 0
        for signal in signals:
            stopped = (trades_today >= cfg.maximum_trades or
                       cumulative_points >= cfg.daily_goal_points or
                       cumulative_r <= cfg.daily_stop_r)
            if signal["entry_time"] <= last_exit or stopped:
                continue
            planned = plan_trade(signal, ctxs[date], cfg)
            if planned is None:
                continue
            result = execute(planned, one, feature, cfg)
            trades_today += 1
            cumulative_points += result["net_points"]
            cumulative_r += result["net_r"]
            cumulative_dollars += result["net_dollars"]
            result.update({"date": date, "trade_number": trades_today,
                           "cumulative_points": cumulative_points,
                           "cumulative_r": cumulative_r,
                           "cumulative_dollars": cumulative_dollars})
            rows.append(result)
            last_exit = result["exit_time"]
        days.append({"date": date, "trades": trades_today,
                     "net_points": cumulative_points, "net_r": cumulative_r,
                     "net_dollars": cumulative_dollars})
    return pd.DataFrame(rows), pd.DataFrame(days)


def statistics(trades: pd.DataFrame, daily: pd.DataFrame, cfg: Config) -> dict[str, Any]:
    if daily.empty:
        return {"sessions": 0, "trades": 0}
    pnl = daily.set_index("date").net_dollars
    equity = cfg.account + pnl.cumsum()
    drawdown = equity - equity.cummax().clip(lower=cfg.account)
    returns = pnl / cfg.account
    years = max((daily.date.max() - daily.date.min()).days / 365.25, 1 / 252)
    wins = trades.net_dollars > 0 if not trades.empty else pd.Series(dtype=bool)
    losses = -trades.loc[trades.net_dollars < 0, "net_dollars"].sum() if not trades.empty else 0
    profit_factor = (trades.loc[trades.net_dollars > 0, "net_dollars"].sum() / losses
                     if losses else None)
    standard_deviation = returns.std(ddof=1)
    return {
        "start": str(daily.date.min().date()), "end": str(daily.date.max().date()),
        "sessions": len(daily), "trades": len(trades),
        "trades_per_year": len(trades) / years,
        "participation": float((daily.trades > 0).mean()),
        "win_rate": float(wins.mean()) if len(wins) else None,
        "average_net_points": float(trades.net_points.mean()) if len(trades) else None,
        "average_net_r": float(trades.net_r.mean()) if len(trades) else None,
        "profit_factor": float(profit_factor) if profit_factor is not None else None,
        "net_dollars": float(pnl.sum()), "ending_equity": float(equity.iloc[-1]),
        "cagr": float((equity.iloc[-1] / cfg.account) ** (1 / years) - 1)
                if equity.iloc[-1] > 0 else -1.0,
        "annual_volatility": float(standard_deviation * np.sqrt(252)),
        "sharpe": float(returns.mean() / standard_deviation * np.sqrt(252))
                  if standard_deviation else None,
        "max_drawdown_dollars": float(drawdown.min()),
        "max_drawdown_pct_initial": float(drawdown.min() / cfg.account),
    }


def write_report(output: Path, trades: pd.DataFrame, daily: pd.DataFrame,
                 stats: dict[str, Any], cfg: Config, rolls: int,
                 roll_adjusted: bool) -> None:
    output.mkdir(parents=True, exist_ok=True)
    trades.to_csv(output / "trades.csv", index=False)
    daily.to_csv(output / "daily.csv", index=False)
    if daily.empty:
        annual = pd.DataFrame(columns=["sessions", "trades", "net_dollars", "net_points"])
    else:
        annual = daily.assign(year=pd.to_datetime(daily.date).dt.year).groupby("year").agg(
            sessions=("date", "size"), trades=("trades", "sum"),
            net_dollars=("net_dollars", "sum"), net_points=("net_points", "sum"))
    annual.to_csv(output / "annual.csv")
    payload = {"config": asdict(cfg), "statistics": stats, "rolls": rolls,
               "roll_adjusted": roll_adjusted}
    (output / "summary.json").write_text(json.dumps(payload, indent=2,
                                                     allow_nan=False) + "\n")

    def fmt(value: Any, pattern: str) -> str:
        return "n/a" if value is None else pattern.format(value)

    report = f"""# {cfg.symbol} Opening Trend-Pullback backtest

## Result

- Period: {stats.get('start', 'n/a')} through {stats.get('end', 'n/a')} ({stats.get('sessions', 0):,} sessions)
- Trades: {stats.get('trades', 0):,}; participation: {fmt(stats.get('participation'), '{:.1%}')}
- Net: {fmt(stats.get('net_dollars'), '${:,.2f}')}; win rate: {fmt(stats.get('win_rate'), '{:.1%}')}
- Average: {fmt(stats.get('average_net_points'), '{:+.2f} points')} / {fmt(stats.get('average_net_r'), '{:+.3f}R')} per trade
- Profit factor: {fmt(stats.get('profit_factor'), '{:.2f}')}; daily Sharpe: {fmt(stats.get('sharpe'), '{:+.2f}')}
- Max drawdown: {fmt(stats.get('max_drawdown_dollars'), '${:,.2f}')} ({fmt(stats.get('max_drawdown_pct_initial'), '{:.1%}')} of initial account)

## Frozen research definitions

- Trend structure is two confirmed 1-left/1-right 5-minute pivot highs and lows, both rising for long or falling for short. A pivot is only available after the following bar closes.
- The opening range is 09:30-09:44 ET. Entries use the close of a completed 5-minute rejection bar from 09:45 through 10:54 ET.
- A pullback is one counter-trend bar whose body and volume are each below the mean of the preceding three bars, followed by a trend-colored bar. Either bar must overlap a zone within {cfg.zone_atr:.2f} ATR.
- Zones are session VWAP, the broken opening-range edge, a previously crossed prior-day/overnight/premarket level, or a confirmed prior swing.
- ATR is mean true range of the 14 completed 5-minute bars immediately before 09:30 and is frozen for the day.
- Prior value uses a 70% close-volume profile at {cfg.tick_size:g}-point rows. This is an OHLCV approximation, not exchange volume-at-price.
- No historical economic-calendar series is present, so the default trades through releases. Untested 15-minute/hourly discretionary swing levels are not invented; targets use the listed objective session levels only.
- Stop is the furthest of zone plus {cfg.stop_buffer_ticks} ticks, 1 ATR, or pullback extreme plus {cfg.stop_buffer_ticks} ticks. Target is the nearest fixed key level in the trade direction; setups below {cfg.minimum_rr:.1f}R are skipped.
- Stops win an ambiguous 1-minute bar touching both stop and target. Modeled round-trip friction is {cfg.slippage_ticks_rt:g} ticks plus ${cfg.commission_rt:.2f} per contract.
- Daily stopping uses per-contract cumulative net points (+{cfg.daily_goal_points:g}) and cumulative normalized R ({cfg.daily_stop_r:g}R), plus a {cfg.maximum_trades}-trade cap. Trades flatten before 11:00 ET.
- Bias-flip exits are {'enabled' if cfg.bias_flip_exit else 'disabled'}; contract-roll back-adjustment across {rolls} rolls is {'enabled' if roll_adjusted else 'disabled'}.

This is a mechanical proxy for a discretionary plan, not evidence that the discretionary version has the same results.
"""
    (output / "report.md").write_text(report)


def main() -> None:
    global TICK, DOLLARS_PER_POINT
    args = arguments()
    if args.tick_size <= 0 or args.point_value <= 0:
        raise SystemExit("Tick size and point value must be positive")
    TICK, DOLLARS_PER_POINT = args.tick_size, args.point_value
    cfg = Config(symbol=args.symbol, tick_size=args.tick_size, point_value=args.point_value,
                 account=args.account, risk_dollars=args.risk_dollars,
                 minimum_rr=args.minimum_rr, zone_atr=args.zone_atr,
                 commission_rt=args.commission_rt,
                 slippage_ticks_rt=args.slippage_ticks_rt,
                 bias_flip_exit=args.bias_flip_exit)
    if cfg.risk_dollars <= 0 or cfg.minimum_rr < 0 or cfg.zone_atr < 0:
        raise SystemExit("Risk must be positive; R:R and zone tolerance cannot be negative")
    minutes, rolls = load_minutes(args.data, not args.no_roll_adjust)
    bars = make_five_minute(minutes)
    ctxs = contexts(minutes, bars)
    trades, daily = backtest(minutes, bars, ctxs, cfg, args.start, args.end)
    stats = statistics(trades, daily, cfg)
    write_report(args.output_dir, trades, daily, stats, cfg, rolls,
                 not args.no_roll_adjust)
    print(f"{args.symbol} Opening Trend-Pullback | {stats.get('start', 'n/a')} -> {stats.get('end', 'n/a')}")
    print(f"sessions {stats.get('sessions', 0):,} | trades {stats.get('trades', 0):,} | "
          f"participation {stats.get('participation', 0):.1%}")
    if stats.get("trades"):
        pf = "n/a" if stats["profit_factor"] is None else f"{stats['profit_factor']:.2f}"
        sharpe = "n/a" if stats["sharpe"] is None else f"{stats['sharpe']:+.2f}"
        print(f"win {stats['win_rate']:.1%} | avg {stats['average_net_points']:+.2f} pts / "
              f"{stats['average_net_r']:+.3f}R | PF {pf}")
        print(f"net ${stats['net_dollars']:,.2f} | Sharpe {sharpe} | "
              f"max DD ${stats['max_drawdown_dollars']:,.2f}")
    print(f"written -> {args.output_dir}")


if __name__ == "__main__":
    main()
