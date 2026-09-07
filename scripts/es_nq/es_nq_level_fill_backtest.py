"""Backtest prior-range and all-time-high/low level fills.

The ES/NQ group uses SPX and NDX cash-index signal proxies. The gold/crude
group uses PWB's GC1 and CL1 continuous commodity series. Results do not model
contract rolls, multipliers, margin, funding, or instrument-specific costs.

Example: fade a 0.25-1.00 ATR backfill of the previous completed week's range.

    python es_nq_level_fill_backtest.py --level prior-week \
        --setup gap-backfill --style fade --min-atr 0.25 --max-atr 1.0
"""

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd


# Load the workspace's PWB dataset key without requiring python-dotenv.
_env = Path(__file__).with_name(".env")
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _value = _line.split("=", 1)
            os.environ.setdefault(_key.strip(), _value.strip())

import pwb_toolbox.datasets as pwb_ds
from pwb_toolbox.performance.metrics import (
    annualized_volatility,
    cagr,
    max_drawdown,
    sharpe_ratio,
)


ASSET_GROUPS = {
    "es-nq": {
        "dataset": "Indices-Daily-Price",
        "symbols": {"ES": "SPX", "NQ": "NDX"},
        "description": "SPX/NDX 50/50 cash-index proxies",
    },
    "gold-crude": {
        "dataset": "Commodities-Daily-Price",
        "symbols": {"Gold": "GC1", "Crude": "CL1"},
        "description": "GC1/CL1 50/50 continuous-series proxies",
    },
}
LEVEL_COLUMNS = {
    "prior-day": ("prior_day_high", "prior_day_low"),
    "prior-week": ("prior_week_high", "prior_week_low"),
    "ath": ("ath", None),
    "atl": (None, "atl"),
}


def prepare(raw: pd.DataFrame) -> pd.DataFrame:
    """Calculate lagged levels and ATR using the full available history."""
    df = (
        raw.sort_values("date")
        .set_index("date")[["open", "high", "low", "close"]]
        .astype(float)
    )

    previous_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr20"] = true_range.rolling(20).mean()

    df["prior_day_high"] = df["high"].shift(1)
    df["prior_day_low"] = df["low"].shift(1)

    week = df.index.to_period("W-FRI")
    completed_week = (
        df.groupby(week)
        .agg(high=("high", "max"), low=("low", "min"))
        .shift(1)
    )
    df["prior_week_high"] = week.map(completed_week["high"])
    df["prior_week_low"] = week.map(completed_week["low"])
    df["week"] = week

    # Shift expanding extrema so today's high/low cannot define today's level.
    df["ath"] = df["high"].cummax().shift(1)
    df["atl"] = df["low"].cummin().shift(1)
    return df


def make_signals(
    df: pd.DataFrame,
    level_name: str,
    setup: str,
    first_touch: bool,
) -> pd.DataFrame:
    """Create one pre-open target and determine whether the daily bar filled it."""
    high_column, low_column = LEVEL_COLUMNS[level_name]
    signal = pd.DataFrame(index=df.index)
    signal["eligible"] = False
    signal["filled"] = False
    signal["side"] = ""
    signal["level"] = np.nan

    if setup == "approach":
        if high_column and low_column:
            inside = (df["open"] < df[high_column]) & (
                df["open"] > df[low_column]
            )
            upper_distance = df[high_column] - df["open"]
            lower_distance = df["open"] - df[low_column]
            choose_upper = inside & (upper_distance <= lower_distance)
            choose_lower = inside & (lower_distance < upper_distance)

            signal.loc[inside, "eligible"] = True
            signal.loc[choose_upper, "side"] = "upper"
            signal.loc[choose_upper, "level"] = df.loc[choose_upper, high_column]
            signal.loc[choose_lower, "side"] = "lower"
            signal.loc[choose_lower, "level"] = df.loc[choose_lower, low_column]
            signal.loc[
                choose_upper & (df["high"] >= df[high_column]), "filled"
            ] = True
            signal.loc[
                choose_lower & (df["low"] <= df[low_column]), "filled"
            ] = True
        elif high_column:
            eligible = df["open"] < df[high_column]
            signal.loc[eligible, ["eligible", "side"]] = [True, "upper"]
            signal.loc[eligible, "level"] = df.loc[eligible, high_column]
            signal.loc[
                eligible & (df["high"] >= df[high_column]), "filled"
            ] = True
        else:
            eligible = df["open"] > df[low_column]
            signal.loc[eligible, ["eligible", "side"]] = [True, "lower"]
            signal.loc[eligible, "level"] = df.loc[eligible, low_column]
            signal.loc[
                eligible & (df["low"] <= df[low_column]), "filled"
            ] = True
    else:
        upper_gap = (
            pd.Series(False, index=df.index)
            if high_column is None
            else df["open"] > df[high_column]
        )
        lower_gap = (
            pd.Series(False, index=df.index)
            if low_column is None
            else df["open"] < df[low_column]
        )
        signal.loc[upper_gap | lower_gap, "eligible"] = True

        if high_column:
            signal.loc[upper_gap, "side"] = "upper"
            signal.loc[upper_gap, "level"] = df.loc[upper_gap, high_column]
            signal.loc[
                upper_gap & (df["low"] <= df[high_column]), "filled"
            ] = True
        if low_column:
            signal.loc[lower_gap, "side"] = "lower"
            signal.loc[lower_gap, "level"] = df.loc[lower_gap, low_column]
            signal.loc[
                lower_gap & (df["high"] >= df[low_column]), "filled"
            ] = True

    signal["size_bps"] = (
        (df["open"] - signal["level"]).abs() / df["open"] * 10_000
    )
    signal["size_atr"] = (
        (df["open"] - signal["level"]).abs() / df["atr20"]
    )

    if first_touch:
        if level_name == "prior-week":
            group = df["week"]
        elif level_name == "prior-day":
            group = pd.Series(df.index, index=df.index)
        else:
            # A new expanding extreme starts a new level lifecycle.
            group = signal["level"]

        seen_before = pd.Series(False, index=df.index)
        for side in ("upper", "lower"):
            side_fill = signal["filled"] & signal["side"].eq(side)
            prior_fill = side_fill.groupby(group).transform(
                lambda values: values.cummax().shift(1, fill_value=False)
            )
            seen_before |= signal["side"].eq(side) & prior_fill
        signal.loc[seen_before, "filled"] = False

    return signal


def strategy_returns(
    df: pd.DataFrame,
    signal: pd.DataFrame,
    style: str,
    min_atr: float,
    max_atr: float,
    cost_bps: float,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return daily sleeve returns plus eligible and traded masks."""
    in_bucket = (signal["size_atr"] >= min_atr) & (
        signal["size_atr"] < max_atr
    )
    eligible = signal["eligible"] & in_bucket
    traded = signal["filled"] & in_bucket

    upper_fade = (signal["level"] - df["close"]) / signal["level"]
    lower_fade = (df["close"] - signal["level"]) / signal["level"]
    fade_return = upper_fade.where(signal["side"].eq("upper"), lower_fade)
    gross_return = fade_return if style == "fade" else -fade_return

    returns = pd.Series(0.0, index=df.index)
    returns.loc[traded] = gross_return.loc[traded] - cost_bps / 10_000
    return returns, eligible, traded


def performance(returns: pd.Series) -> dict[str, float]:
    nav = (1 + returns).cumprod()
    depth, _ = max_drawdown(nav.tolist())
    return {
        "sharpe": sharpe_ratio(nav.tolist()),
        "cagr": cagr(nav.tolist()),
        "vol": annualized_volatility(nav.tolist()),
        "maxdd": abs(depth),
        "growth": nav.iloc[-1],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", choices=ASSET_GROUPS, default="es-nq")
    parser.add_argument("--level", choices=LEVEL_COLUMNS, default="prior-week")
    parser.add_argument(
        "--setup", choices=("approach", "gap-backfill"), default="gap-backfill"
    )
    parser.add_argument("--style", choices=("fade", "continuation"), default="fade")
    parser.add_argument("--min-atr", type=float, default=0.25)
    parser.add_argument("--max-atr", type=float, default=1.0)
    parser.add_argument("--cost-bps", type=float, default=2.0)
    parser.add_argument("--balance", type=float, default=100_000)
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument(
        "--first-touch",
        action="store_true",
        help="trade only the first fill of each side of a level lifecycle",
    )
    args = parser.parse_args()

    if args.min_atr < 0 or args.max_atr <= args.min_atr:
        parser.error("require 0 <= --min-atr < --max-atr")

    group = ASSET_GROUPS[args.assets]
    symbols = group["symbols"]

    # One download, no unnecessary FX conversion. Filtering happens after the
    # PWB parquet is loaded in the installed toolbox version.
    raw = pwb_ds.load_dataset(
        group["dataset"],
        symbols=list(symbols.values()),
        to_usd=False,
    )
    raw["date"] = pd.to_datetime(raw["date"])
    data = {
        instrument: prepare(raw[raw["symbol"] == proxy].drop(columns="symbol"))
        for instrument, proxy in symbols.items()
    }
    instrument_names = list(symbols)
    common_index = data[instrument_names[0]].index
    for name in instrument_names[1:]:
        common_index = common_index.intersection(data[name].index)
    data = {name: frame.reindex(common_index) for name, frame in data.items()}

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end) if args.end else common_index.max()
    evaluation = (common_index >= start) & (common_index <= end)
    if not evaluation.any():
        parser.error("the requested date range has no observations")

    sleeve_returns = {}
    eligible_masks = {}
    traded_masks = {}
    for name, frame in data.items():
        signal = make_signals(frame, args.level, args.setup, args.first_touch)
        returns, eligible, traded = strategy_returns(
            frame,
            signal,
            args.style,
            args.min_atr,
            args.max_atr,
            args.cost_bps,
        )
        sleeve_returns[name] = returns.loc[evaluation]
        eligible_masks[name] = eligible.loc[evaluation]
        traded_masks[name] = traded.loc[evaluation]

    portfolio = pd.DataFrame(sleeve_returns).mean(axis=1)
    stats = performance(portfolio)
    final_balance = args.balance * stats["growth"]

    print(
        f"\n{args.level} {args.setup} {args.style} | "
        f"{args.min_atr:g}-{args.max_atr:g} ATR20 | cost={args.cost_bps:g} bps"
    )
    print(
        f"{group['description']} | "
        f"{portfolio.index[0].date()} -> {portfolio.index[-1].date()}"
    )
    print(
        f"Portfolio: end=${final_balance:,.0f}  Sharpe={stats['sharpe']:.2f}  "
        f"CAGR={stats['cagr'] * 100:.2f}%  Vol={stats['vol'] * 100:.2f}%  "
        f"MaxDD={stats['maxdd'] * 100:.2f}%"
    )

    print(
        "\nInstrument  Eligible  Fills  Fill rate  Win rate  Avg trade"
        "       End $  Sharpe   MaxDD"
    )
    for name in symbols:
        eligible = eligible_masks[name]
        traded = traded_masks[name]
        event_returns = sleeve_returns[name].loc[traded]
        fill_rate = traded.sum() / eligible.sum() if eligible.sum() else np.nan
        win_rate = (event_returns > 0).mean() if len(event_returns) else np.nan
        average_bps = event_returns.mean() * 10_000 if len(event_returns) else np.nan
        instrument_stats = performance(sleeve_returns[name])
        instrument_end = args.balance * instrument_stats["growth"]
        print(
            f"{name:<10}{eligible.sum():>9}{traded.sum():>7}"
            f"{fill_rate * 100:>10.1f}%{win_rate * 100:>10.1f}%"
            f"{average_bps:>10.2f} bp{instrument_end:>12,.0f}"
            f"{instrument_stats['sharpe']:>8.2f}"
            f"{instrument_stats['maxdd'] * 100:>8.2f}%"
        )


if __name__ == "__main__":
    main()
