"""Screen intraday strategies with fixed per-trade risk and whole micros.

The signal data are Papers With Backtest SPY/QQQ 5-minute bars.  SPY is used
as an MES signal proxy and QQQ as an MNQ signal proxy.  PWB daily SPX/NDX
levels translate each proxy's percentage stop/return into approximate futures
points.  This is a strategy screen, not an execution-grade futures backtest:
it does not contain the futures basis, Globex session, contract rolls, or an
actual bid/ask feed.

All candidates:
  * make at most one trade per day;
  * form signals on 15-minute regular-session bars;
  * use a hard stop and target;
  * close by the final RTH bar;
  * use only information known at entry.

Example:
    .venv\\Scripts\\python.exe intraday_strategy_screen.py
    .venv\\Scripts\\python.exe intraday_strategy_screen.py --risk 100 --cost 6
"""

from __future__ import annotations

import argparse
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
BASE_EQUITY = 100_000.0
MAX_MICROS = 20

MARKETS = {
    "MES": {"etf": "SPY", "index": "SPX", "multiplier": 5.0},
    "MNQ": {"etf": "QQQ", "index": "NDX", "multiplier": 2.0},
}


@dataclass
class Trade:
    date: pd.Timestamp
    strategy: str
    market: str
    direction: int
    entry: float
    stop: float
    target: float
    exit: float
    reason: str
    gross_r: float
    mae_r: float
    stop_pct: float


def load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            key, value = raw.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def load_intraday(symbol: str) -> pd.DataFrame:
    frame = pd.read_parquet(DATA / f"{symbol}_5min.parquet")
    frame.index = pd.to_datetime(frame.index)
    if frame.index.tz is not None:
        frame.index = frame.index.tz_convert("America/New_York").tz_localize(None)
    return frame.sort_index().between_time("09:30", "15:59")


def to_15min(frame: pd.DataFrame) -> pd.DataFrame:
    bars = frame.resample(
        "15min", origin="start_day", offset="9h30min", label="left", closed="left"
    ).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum")
    )
    return bars.dropna(subset=["open", "high", "low", "close"]).between_time(
        "09:30", "15:59"
    )


def daily_context(frame: pd.DataFrame) -> pd.DataFrame:
    grouped = frame.groupby(frame.index.normalize())
    daily = pd.DataFrame(
        {
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
        }
    )
    daily["pdh"] = daily["high"].shift(1)
    daily["pdl"] = daily["low"].shift(1)
    daily["pclose"] = daily["close"].shift(1)
    daily["sma20_known"] = daily["close"].rolling(20, min_periods=20).mean().shift(1)
    daily["prange"] = daily["pdh"] - daily["pdl"]
    daily["prange_pct"] = daily["prange"] / daily["pclose"]
    # Yesterday's range is known before today's open.  Including that known
    # observation in today's rolling quantile introduces no look-ahead.
    daily["q33"] = daily["prange_pct"].rolling(40, min_periods=20).quantile(0.33)
    daily["q66"] = daily["prange_pct"].rolling(40, min_periods=20).quantile(0.66)
    daily["compressed"] = daily["prange_pct"] <= daily["q33"]
    daily["wide"] = daily["prange_pct"] >= daily["q66"]
    daily["gap"] = daily["open"] / daily["pclose"] - 1.0
    return daily


def walk_trade(
    bars: pd.DataFrame,
    direction: int,
    entry: float,
    stop: float,
    target: float,
) -> tuple[float, str, float]:
    """Walk forward conservatively; a bar touching stop and target loses."""
    risk = abs(entry - stop)
    if risk <= 0:
        raise ValueError("non-positive trade risk")
    worst_r = 0.0
    for _, bar in bars.iterrows():
        if direction > 0:
            adverse = min(0.0, (float(bar["low"]) - entry) / risk)
            stop_hit = float(bar["low"]) <= stop
            target_hit = float(bar["high"]) >= target
        else:
            adverse = min(0.0, (entry - float(bar["high"])) / risk)
            stop_hit = float(bar["high"]) >= stop
            target_hit = float(bar["low"]) <= target
        worst_r = max(-1.0, min(worst_r, adverse))
        if stop_hit:
            return stop, "stop", -1.0
        if target_hit:
            return target, "target", worst_r
    final = float(bars["close"].iloc[-1])
    return final, "eod", worst_r


def make_trade(
    date: pd.Timestamp,
    strategy: str,
    market: str,
    direction: int,
    entry: float,
    stop: float,
    target: float,
    path: pd.DataFrame,
) -> Trade | None:
    if path.empty or direction * (target - entry) <= 0 or direction * (entry - stop) <= 0:
        return None
    exit_price, reason, mae_r = walk_trade(path, direction, entry, stop, target)
    risk = abs(entry - stop)
    return Trade(
        date=date,
        strategy=strategy,
        market=market,
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        exit=exit_price,
        reason=reason,
        gross_r=direction * (exit_price - entry) / risk,
        mae_r=mae_r,
        stop_pct=risk / entry,
    )


def level_strategy(
    day: pd.Timestamp,
    bars: pd.DataFrame,
    row: pd.Series,
    market: str,
    mode: str,
) -> Trade | None:
    pdh, pdl, prior_range = row["pdh"], row["pdl"], row["prange"]
    if not np.isfinite(pdh) or not np.isfinite(pdl) or prior_range <= 0:
        return None
    # An opening gap outside yesterday's range is a different setup.
    if not (pdl < float(bars["open"].iloc[0]) < pdh):
        return None
    if mode == "pdh_fade_wide" and not bool(row["wide"]):
        return None
    if mode == "pdh_breakout_comp" and not bool(row["compressed"]):
        return None

    rest = bars.iloc[1:]
    for i, (_, bar) in enumerate(rest.iterrows()):
        upper = float(bar["high"]) >= pdh
        lower = float(bar["low"]) <= pdl
        if upper and lower:  # sequence cannot be known from a 15-minute bar
            return None
        if not upper and not lower:
            continue
        path = rest.iloc[i:]
        if mode.startswith("pdh_fade"):
            mid = (pdh + pdl) / 2.0
            if upper:
                return make_trade(day, mode, market, -1, pdh,
                                  pdh + 0.25 * prior_range, mid, path)
            return make_trade(day, mode, market, 1, pdl,
                              pdl - 0.25 * prior_range, mid, path)
        if upper:
            entry = max(pdh, float(bar["open"]))
            risk = entry - (pdh - 0.25 * prior_range)
            return make_trade(day, mode, market, 1, entry, entry - risk,
                              entry + 2.0 * risk, path)
        entry = min(pdl, float(bar["open"]))
        risk = (pdl + 0.25 * prior_range) - entry
        return make_trade(day, mode, market, -1, entry, entry + risk,
                          entry - 2.0 * risk, path)
    return None


def orb_breakout(day: pd.Timestamp, bars: pd.DataFrame, market: str,
                 midpoint_stop: bool = False, allowed_direction: int = 0) -> Trade | None:
    first, rest = bars.iloc[0], bars.iloc[1:]
    high, low = float(first["high"]), float(first["low"])
    if high <= low:
        return None
    for i, (_, bar) in enumerate(rest.iterrows()):
        upper, lower = float(bar["high"]) >= high, float(bar["low"]) <= low
        if upper and lower:
            # Whichever boundary traded first, reaching the other boundary
            # subsequently hits the opposite-range stop.  Counting a loss is
            # conservative and avoids silently deleting whipsaw bars.
            direction = allowed_direction if allowed_direction else 1
            path = rest.iloc[i:]
            entry = (max(high, float(bar["open"])) if direction > 0
                     else min(low, float(bar["open"])))
            stop = ((high + low) / 2.0 if midpoint_stop
                    else (low if direction > 0 else high))
            name = ("orb15_midstop" if midpoint_stop else
                    ("orb15_trend20" if allowed_direction else "orb15_breakout"))
            target = (entry + 2.0 * (entry - stop) if direction > 0
                      else entry - 2.0 * (stop - entry))
            return make_trade(day, name, market, direction, entry, stop, target, path)
        if not upper and not lower:
            continue
        if upper and allowed_direction < 0:
            continue
        if lower and allowed_direction > 0:
            continue
        path = rest.iloc[i:]
        if upper:
            entry = max(high, float(bar["open"]))
            stop = (high + low) / 2.0 if midpoint_stop else low
            name = ("orb15_midstop" if midpoint_stop else
                    ("orb15_trend20" if allowed_direction else "orb15_breakout"))
            return make_trade(day, name, market, 1, entry, stop,
                              entry + 2.0 * (entry - stop), path)
        entry = min(low, float(bar["open"]))
        stop = (high + low) / 2.0 if midpoint_stop else high
        name = ("orb15_midstop" if midpoint_stop else
                ("orb15_trend20" if allowed_direction else "orb15_breakout"))
        return make_trade(day, name, market, -1, entry, stop,
                          entry - 2.0 * (stop - entry), path)
    return None


def orb_failure(day: pd.Timestamp, bars: pd.DataFrame, market: str) -> Trade | None:
    first, rest = bars.iloc[0], bars.iloc[1:]
    high, low = float(first["high"]), float(first["low"])
    width, mid = high - low, (high + low) / 2.0
    if width <= 0:
        return None
    for i, (_, bar) in enumerate(rest.iterrows()):
        up_fail = float(bar["high"]) > high and mid < float(bar["close"]) < high
        dn_fail = float(bar["low"]) < low and low < float(bar["close"]) < mid
        if up_fail and dn_fail:
            return None
        if up_fail:
            entry = float(bar["close"])
            stop = max(float(bar["high"]), high + 0.10 * width)
            return make_trade(day, "orb15_failed_break", market, -1, entry,
                              stop, mid, rest.iloc[i + 1:])
        if dn_fail:
            entry = float(bar["close"])
            stop = min(float(bar["low"]), low - 0.10 * width)
            return make_trade(day, "orb15_failed_break", market, 1, entry,
                              stop, mid, rest.iloc[i + 1:])
    return None


def orb_close_confirmed(day: pd.Timestamp, bars: pd.DataFrame,
                        market: str) -> Trade | None:
    """Enter only after a completed 15-minute bar closes outside the OR."""
    first, rest = bars.iloc[0], bars.iloc[1:]
    high, low = float(first["high"]), float(first["low"])
    if high <= low:
        return None
    for i, (_, bar) in enumerate(rest.iterrows()):
        close = float(bar["close"])
        path = rest.iloc[i + 1:]
        if path.empty:
            return None
        if close > high:
            return make_trade(day, "orb15_close_confirm", market, 1, close, low,
                              close + 2.0 * (close - low), path)
        if close < low:
            return make_trade(day, "orb15_close_confirm", market, -1, close, high,
                              close - 2.0 * (high - close), path)
    return None


def orb_tsmom_confirmed(day: pd.Timestamp, bars: pd.DataFrame, row: pd.Series,
                        market: str, minimum_score: float = 0.50) -> Trade | None:
    """Close-confirmed ORB permitted only in the prior daily TSMOM direction."""
    score = float(row.get("tsmom_score", np.nan))
    direction = 1 if score >= minimum_score else (-1 if score <= -minimum_score else 0)
    if direction == 0:
        return None
    first, rest = bars.iloc[0], bars.iloc[1:]
    high, low = float(first["high"]), float(first["low"])
    if high <= low:
        return None
    for i, (_, bar) in enumerate(rest.iterrows()):
        close = float(bar["close"])
        path = rest.iloc[i + 1:]
        if path.empty:
            return None
        if direction > 0 and close > high:
            return make_trade(day, "orb15_tsmom_confirm", market, 1, close, low,
                              close + 2.0 * (close - low), path)
        if direction < 0 and close < low:
            return make_trade(day, "orb15_tsmom_confirm", market, -1, close, high,
                              close - 2.0 * (high - close), path)
    return None


def pdh_rejection_confirmed(day: pd.Timestamp, bars: pd.DataFrame,
                            row: pd.Series, market: str) -> Trade | None:
    """Fade a prior-day level only after a 15-minute close returns inside."""
    pdh, pdl, prior_range = row["pdh"], row["pdl"], row["prange"]
    if not np.isfinite(pdh) or not np.isfinite(pdl) or prior_range <= 0:
        return None
    if not (pdl < float(bars["open"].iloc[0]) < pdh):
        return None
    mid = (pdh + pdl) / 2.0
    rest = bars.iloc[1:]
    for i, (_, bar) in enumerate(rest.iterrows()):
        close = float(bar["close"])
        path = rest.iloc[i + 1:]
        if path.empty:
            return None
        upper_reject = float(bar["high"]) >= pdh and mid < close < pdh
        lower_reject = float(bar["low"]) <= pdl and pdl < close < mid
        if upper_reject:
            stop = max(float(bar["high"]), pdh + 0.10 * prior_range)
            return make_trade(day, "pdh_reject_confirm", market, -1, close,
                              stop, mid, path)
        if lower_reject:
            stop = min(float(bar["low"]), pdl - 0.10 * prior_range)
            return make_trade(day, "pdh_reject_confirm", market, 1, close,
                              stop, mid, path)
    return None


def gap_fade(day: pd.Timestamp, bars: pd.DataFrame, row: pd.Series,
             market: str, gap_threshold: float = 0.003) -> Trade | None:
    gap, previous_close = float(row["gap"]), float(row["pclose"])
    if not np.isfinite(gap) or abs(gap) < gap_threshold or len(bars) < 2:
        return None
    first, path = bars.iloc[0], bars.iloc[1:]
    width = float(first["high"] - first["low"])
    if width <= 0:
        return None
    # Wait for a 15-minute candle against the gap, then enter at its close.
    if gap > 0 and float(first["close"]) < float(first["open"]):
        entry = float(first["close"])
        return make_trade(day, "gap_fade_confirmed", market, -1, entry,
                          float(first["high"]) + 0.10 * width,
                          previous_close, path)
    if gap < 0 and float(first["close"]) > float(first["open"]):
        entry = float(first["close"])
        return make_trade(day, "gap_fade_confirmed", market, 1, entry,
                          float(first["low"]) - 0.10 * width,
                          previous_close, path)
    return None


def generate_trades(market: str, five: pd.DataFrame,
                    daily_score: pd.Series) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    fifteen = to_15min(five)
    context = daily_context(five)
    context["tsmom_score"] = daily_score.reindex(context.index)
    records: list[dict] = []
    for day, bars in fifteen.groupby(fifteen.index.normalize()):
        if len(bars) < 20 or day not in context.index:
            continue
        row = context.loc[day]
        trend_direction = 0
        if np.isfinite(row["sma20_known"]):
            trend_direction = 1 if row["pclose"] > row["sma20_known"] else -1
        trend_trade = (orb_breakout(day, bars, market,
                                    allowed_direction=trend_direction)
                       if trend_direction else None)
        candidates = [
            level_strategy(day, bars, row, market, "pdh_fade_all"),
            level_strategy(day, bars, row, market, "pdh_fade_wide"),
            level_strategy(day, bars, row, market, "pdh_breakout_comp"),
            orb_breakout(day, bars, market),
            orb_breakout(day, bars, market, midpoint_stop=True),
            trend_trade,
            orb_close_confirmed(day, bars, market),
            orb_tsmom_confirmed(day, bars, row, market),
            orb_failure(day, bars, market),
            pdh_rejection_confirmed(day, bars, row, market),
            gap_fade(day, bars, row, market),
        ]
        records.extend(asdict(t) for t in candidates if t is not None)
    trades = pd.DataFrame(records)
    if not trades.empty:
        trades["date"] = pd.to_datetime(trades["date"])
    return trades, pd.DatetimeIndex(sorted(context.index.unique()))


def load_index_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    load_env()
    import pwb_toolbox.datasets as pwb_ds

    raw = pwb_ds.load_dataset(
        "Indices-Daily-Price", symbols=[m["index"] for m in MARKETS.values()],
        to_usd=False,
    )
    raw["date"] = pd.to_datetime(raw["date"])
    for column in ("open", "close"):
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    opens = raw.pivot_table(index="date", columns="symbol", values="open", aggfunc="last")
    closes = raw.pivot_table(index="date", columns="symbol", values="close", aggfunc="last")
    scores = pd.DataFrame(index=closes.index)
    for symbol in closes.columns:
        votes = [np.sign(closes[symbol] - closes[symbol].shift(length))
                 for length in (20, 60, 120, 252)]
        warm = pd.concat(votes, axis=1).notna().all(axis=1)
        scores[symbol] = pd.concat(votes, axis=1).mean(axis=1).where(warm).shift(1)
    return opens, scores


def size_trades(trades: pd.DataFrame, index_open: pd.DataFrame,
                risk_budget: float, cost_per_micro: float) -> pd.DataFrame:
    if trades.empty:
        return trades
    out = trades.copy()
    market_info = out["market"].map(MARKETS)
    out["index_symbol"] = market_info.map(lambda x: x["index"])
    out["multiplier"] = market_info.map(lambda x: x["multiplier"])
    lookup = index_open.stack().rename("index_open")
    key = pd.MultiIndex.from_arrays([out["date"], out["index_symbol"]])
    out["index_open"] = lookup.reindex(key).to_numpy()
    out["risk_1_micro"] = out["stop_pct"] * out["index_open"] * out["multiplier"]
    out["contracts"] = np.floor(risk_budget / out["risk_1_micro"]).clip(
        lower=0, upper=MAX_MICROS
    ).fillna(0).astype(int)
    out["gross_pnl"] = (
        out["gross_r"] * out["risk_1_micro"] * out["contracts"]
    )
    out["cost"] = cost_per_micro * out["contracts"]
    out["net_pnl"] = out["gross_pnl"] - out["cost"]
    out["min_pnl"] = (
        out["mae_r"] * out["risk_1_micro"] * out["contracts"] - out["cost"]
    )
    out["net_r"] = out["net_pnl"] / (
        out["risk_1_micro"] * out["contracts"]
    ).replace(0, np.nan)
    out["tradable"] = out["contracts"] > 0
    return out


def max_drawdown_dollars(pnl: pd.Series) -> float:
    equity = pnl.cumsum()
    return float((equity.cummax() - equity).max()) if len(equity) else 0.0


def profit_factor(values: pd.Series) -> float:
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    return gains / losses if losses > 0 else np.inf


def daily_track(group: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    tradable = group[group["tradable"]].set_index("date").sort_index()
    return pd.DataFrame(
        {
            "pnl": tradable["net_pnl"].reindex(calendar, fill_value=0.0),
            "min_pnl": tradable["min_pnl"].reindex(calendar, fill_value=0.0),
        },
        index=calendar,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--risk", type=float, default=125.0,
                        help="maximum dollars risked per trade before costs")
    parser.add_argument("--cost", type=float, default=5.0,
                        help="all-in round-trip dollars per micro contract")
    parser.add_argument("--holdout", default="2025-07-01")
    args = parser.parse_args()
    if args.risk <= 0 or args.cost < 0:
        parser.error("risk must be positive and cost cannot be negative")

    index_open, daily_scores = load_index_data()
    all_trades, calendars = [], []
    for market, info in MARKETS.items():
        raw, calendar = generate_trades(
            market, load_intraday(info["etf"]), daily_scores[info["index"]]
        )
        all_trades.append(raw)
        calendars.append(calendar)
    trades = pd.concat(all_trades, ignore_index=True)
    trades = size_trades(trades, index_open, args.risk, args.cost)
    calendar = calendars[0].intersection(calendars[1])
    start, end = calendar.min(), calendar.max()
    holdout = pd.Timestamp(args.holdout)

    print("\nINTRADAY STRATEGY SCREEN")
    print("=" * 88)
    print(f"PWB SPY/QQQ 5-minute data -> 15-minute signals | {start.date()} -> {end.date()}")
    print(f"Sizing: <=${args.risk:,.0f} stop risk, whole micros, max {MAX_MICROS}; "
          f"cost ${args.cost:.2f}/micro round trip")
    print("One trade/day | flat by the RTH close")
    print("SPY/MES and QQQ/MNQ are proxies; results are not actual futures fills.\n")

    rows = []
    for (strategy, market), group in trades.groupby(["strategy", "market"]):
        sized = group[group["tradable"]].copy()
        if sized.empty:
            continue
        daily = daily_track(group, calendar)
        recent = sized[sized["date"] >= holdout]
        rows.append(
            {
                "strategy": strategy, "market": market,
                "setups": len(group), "trades": len(sized),
                "skipped": len(group) - len(sized),
                "win_pct": 100 * sized["net_pnl"].gt(0).mean(),
                "avg_pnl": sized["net_pnl"].mean(),
                "profit_factor": profit_factor(sized["net_pnl"]),
                "total_pnl": sized["net_pnl"].sum(),
                "max_dd": max_drawdown_dollars(daily["pnl"]),
                "holdout_trades": len(recent),
                "holdout_avg": recent["net_pnl"].mean() if len(recent) else np.nan,
                "holdout_pf": profit_factor(recent["net_pnl"]) if len(recent) else np.nan,
                "holdout_pnl": recent["net_pnl"].sum(),
            }
        )
    report = pd.DataFrame(rows).sort_values(
        ["holdout_pnl", "profit_factor"], ascending=False
    ).reset_index(drop=True)

    print("TRADE EDGE AND UNSEEN-PERIOD CHECK")
    header = (f"{'Strategy':<24}{'Mkt':<5}{'N':>5}{'Skip':>6}{'Win':>7}"
              f"{'Avg$':>8}{'PF':>7}{'PnL$':>10}{'DD$':>9}"
              f"{'HO N':>6}{'HO Avg$':>9}{'HO PF':>7}{'HO PnL$':>10}")
    print(header)
    print("-" * len(header))
    for row in report.itertuples():
        print(f"{row.strategy:<24}{row.market:<5}{row.trades:>5}{row.skipped:>6}"
              f"{row.win_pct:>6.1f}%{row.avg_pnl:>8.2f}{row.profit_factor:>7.2f}"
              f"{row.total_pnl:>10.0f}{row.max_dd:>9.0f}{row.holdout_trades:>6}"
              f"{row.holdout_avg:>9.2f}{row.holdout_pf:>7.2f}{row.holdout_pnl:>10.0f}")

    REPORTS.mkdir(exist_ok=True)
    out_csv = REPORTS / "intraday_strategy_screen.csv"
    trade_csv = DATA / "intraday_strategy_trades.csv"
    report.to_csv(out_csv, index=False)
    trades.to_csv(trade_csv, index=False)
    print(f"\nSaved summary: {out_csv}")
    print(f"Saved audit trades: {trade_csv}")


if __name__ == "__main__":
    main()
