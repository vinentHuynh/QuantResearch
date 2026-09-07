"""Backtest a transparent time-series-momentum strategy on CME proxies.

The strategy is deliberately small enough to audit:

1. For each market, calculate price changes over 20, 60, 120, and 252
   sessions (configurable).
2. Convert each lookback to -1, 0, or +1 and average the votes. A market is
   fully long when every lookback is positive and fully short when every
   lookback is negative.
3. Scale point-price P&L by lagged point volatility so each market targets the
   same annualized risk. This remains defined if a futures price reaches or
   crosses zero, as crude oil did in April 2020.
4. Lag the complete target by one session before earning a return. This is
   the important no-look-ahead rule: today's close only affects tomorrow's
   position.
5. Allocate one equal portfolio sleeve to each selected market and subtract
   costs when exposure changes.

PWB provides SPX/NDX cash indices as ES/NQ signal proxies and GC1/CL1 daily
continuous commodity series. This evaluates the strategy signal; it does not
model futures rolls, contract multipliers, margin, funding, or exchange fees.

Default example ($100,000, 2024 onward):

    python cme_time_series_momentum_backtest.py

Change the model or export the daily audit trail:

    python cme_time_series_momentum_backtest.py --lookbacks 20,60,120,252 \
        --vol-window 60 --asset-vol 0.20 --round-trip-cost-bps 2 \
        --export cme_tsmom_results.csv
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


# Load the workspace's dataset-only PWB key without printing it.
_env_path = Path(__file__).with_name(".env")
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
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


@dataclass(frozen=True)
class Market:
    label: str
    dataset: str
    symbol: str
    proxy_note: str


MARKETS = {
    "ES": Market("ES", "Indices-Daily-Price", "SPX", "SPX cash index"),
    "NQ": Market("NQ", "Indices-Daily-Price", "NDX", "NDX cash index"),
    "GC": Market("GC", "Commodities-Daily-Price", "GC1", "GC1 continuous"),
    "CL": Market("CL", "Commodities-Daily-Price", "CL1", "CL1 continuous"),
}
ASSET_GROUPS = {
    "all": ("ES", "NQ", "GC", "CL"),
    "indices": ("ES", "NQ"),
    "commodities": ("GC", "CL"),
}


def parse_lookbacks(value: str) -> tuple[int, ...]:
    try:
        lookbacks = tuple(sorted({int(item) for item in value.split(",")}))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "lookbacks must be comma-separated integers"
        ) from exc
    if not lookbacks or lookbacks[0] < 2:
        raise argparse.ArgumentTypeError("every lookback must be at least 2")
    return lookbacks


def load_closes(market_names: tuple[str, ...]) -> dict[str, pd.Series]:
    """Load each PWB dataset once while retaining full indicator warmup."""
    grouped: dict[str, list[str]] = {}
    for name in market_names:
        grouped.setdefault(MARKETS[name].dataset, []).append(name)

    closes: dict[str, pd.Series] = {}
    for dataset, names in grouped.items():
        symbols = [MARKETS[name].symbol for name in names]
        raw = pwb_ds.load_dataset(dataset, symbols=symbols).copy()
        required = {"symbol", "date", "close"}
        missing = required.difference(raw.columns)
        if missing:
            raise ValueError(f"{dataset} is missing {sorted(missing)}")

        raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
        raw["close"] = pd.to_numeric(raw["close"], errors="coerce")
        raw = raw.dropna(subset=["symbol", "date", "close"])

        for name in names:
            market = MARKETS[name]
            close = (
                raw.loc[raw["symbol"].eq(market.symbol)]
                .drop_duplicates("date", keep="last")
                .sort_values("date")
                .set_index("date")["close"]
                .astype(float)
            )
            close.name = market.label
            if close.empty:
                raise ValueError(f"no usable observations for {market.label}")
            closes[name] = close
    return closes


def build_market_model(
    close: pd.Series,
    lookbacks: tuple[int, ...],
    vol_window: int,
    asset_vol: float,
    max_leverage: float,
) -> pd.DataFrame:
    """Build futures-safe signals and risk positions without future data.

    Classic futures trend models size contracts from the volatility of point
    changes. Using percentage returns is incorrect when a contract can trade
    at or through zero: a move from +18.27 to -37.63 is a -55.90 point move,
    not a reusable -306% return.
    """
    price_change = close.diff()

    votes = pd.concat(
        {
            f"mom_{lookback}": np.sign(close.diff(lookback))
            for lookback in lookbacks
        },
        axis=1,
    )
    # Requiring every lookback avoids treating an incomplete warmup as a vote.
    score = votes.mean(axis=1).where(votes.notna().all(axis=1))

    point_vol = price_change.rolling(
        vol_window, min_periods=vol_window
    ).std(ddof=0)
    daily_risk_target = asset_vol / np.sqrt(252)

    # point_exposure is the fraction of sleeve capital earned per one-point
    # move. Multiplying it by price_change produces a dimensionless return.
    raw_target_point = score * daily_risk_target / point_vol
    absolute_price = close.abs()
    raw_target_notional = raw_target_point * absolute_price
    target_asof_close = raw_target_notional.clip(
        -max_leverage, max_leverage
    )
    target_point_exposure = (
        target_asof_close / absolute_price.replace(0.0, np.nan)
    ).where(absolute_price.ne(0.0), raw_target_point)

    raw_long_point = daily_risk_target / point_vol
    long_target_notional = (raw_long_point * absolute_price).clip(
        0.0, max_leverage
    )
    long_target_point = (
        long_target_notional / absolute_price.replace(0.0, np.nan)
    ).where(absolute_price.ne(0.0), raw_long_point)

    # This percentage-like diagnostic is for display only. P&L never divides
    # by price and therefore remains well-defined through zero.
    realized_vol = (
        point_vol / close.shift(1).abs().replace(0.0, np.nan) * np.sqrt(252)
    )

    # A target calculated with close[t] is held only for return[t+1].
    held_point_exposure = target_point_exposure.shift(1).fillna(0.0)
    held_long_point = long_target_point.shift(1).fillna(0.0)
    held_position = target_asof_close.shift(1).fillna(0.0)

    return pd.DataFrame(
        {
            "close": close,
            "price_change": price_change,
            "score": score,
            "point_vol": point_vol,
            "realized_vol": realized_vol,
            "target_asof_close": target_asof_close,
            "target_point_exposure": target_point_exposure,
            "held_point_exposure": held_point_exposure,
            "held_position": held_position,
            "held_long_point": held_long_point,
            "execution_price": close.shift(1).abs(),
        }
    )


def nav_from_returns(returns: pd.Series, initial_balance: float) -> pd.Series:
    clean = returns.fillna(0.0)
    if clean.le(-1.0).any():
        bad_date = clean.index[clean.le(-1.0)][0]
        raise ValueError(f"portfolio loss exceeds 100% on {bad_date}")
    return initial_balance * (1.0 + clean).cumprod()


def performance(returns: pd.Series, initial_balance: float) -> dict[str, float]:
    nav = nav_from_returns(returns, initial_balance)
    normalized_nav = nav / initial_balance
    depth, _ = max_drawdown(normalized_nav.tolist())
    return {
        "ending_balance": float(nav.iloc[-1]),
        "total_return": float(normalized_nav.iloc[-1] - 1.0),
        "cagr": float(cagr(normalized_nav.tolist())),
        "sharpe": float(sharpe_ratio(normalized_nav.tolist())),
        "vol": float(annualized_volatility(normalized_nav.tolist())),
        "maxdd": float(abs(depth)),
    }


def format_stats(name: str, stats: dict[str, float]) -> str:
    return (
        f"{name:<18} end=${stats['ending_balance']:>11,.0f}  "
        f"return={stats['total_return'] * 100:>7.2f}%  "
        f"CAGR={stats['cagr'] * 100:>6.2f}%  "
        f"Sharpe={stats['sharpe']:>5.2f}  "
        f"Vol={stats['vol'] * 100:>6.2f}%  "
        f"MaxDD={stats['maxdd'] * 100:>6.2f}%"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Equal-risk time-series momentum on CME daily proxies."
    )
    parser.add_argument("--assets", choices=ASSET_GROUPS, default="all")
    parser.add_argument("--balance", type=float, default=100_000.0)
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument(
        "--lookbacks", type=parse_lookbacks, default=parse_lookbacks("20,60,120,252")
    )
    parser.add_argument(
        "--vol-window",
        type=int,
        default=60,
        help="sessions used to estimate annualized realized volatility",
    )
    parser.add_argument(
        "--asset-vol",
        type=float,
        default=0.20,
        help="annual volatility target for each market sleeve (0.20 = 20%%)",
    )
    parser.add_argument(
        "--max-leverage",
        type=float,
        default=2.0,
        help="maximum absolute notional exposure for any one sleeve",
    )
    parser.add_argument(
        "--round-trip-cost-bps",
        type=float,
        default=2.0,
        help="cost of entering and later exiting 1.0x notional exposure",
    )
    parser.add_argument(
        "--export",
        type=Path,
        default=None,
        help="optional CSV path for NAV, signals, positions, and returns",
    )
    args = parser.parse_args()

    if args.balance <= 0:
        parser.error("--balance must be positive")
    if args.vol_window < 2:
        parser.error("--vol-window must be at least 2")
    if args.asset_vol <= 0 or args.max_leverage <= 0:
        parser.error("--asset-vol and --max-leverage must be positive")
    if args.round_trip_cost_bps < 0:
        parser.error("--round-trip-cost-bps cannot be negative")

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end) if args.end else None
    if end is not None and end < start:
        parser.error("--end cannot precede --start")

    selected = ASSET_GROUPS[args.assets]
    closes = load_closes(selected)
    models = {
        name: build_market_model(
            closes[name],
            args.lookbacks,
            args.vol_window,
            args.asset_vol,
            args.max_leverage,
        )
        for name in selected
    }

    # Use the union of trading dates. A closed market earns zero that day and
    # retains its previously computed position until its own next observation.
    price_changes = pd.concat(
        {name: model["price_change"] for name, model in models.items()},
        axis=1,
    ).fillna(0.0)
    point_positions = pd.concat(
        {name: model["held_point_exposure"] for name, model in models.items()},
        axis=1,
    ).ffill().fillna(0.0)
    positions = pd.concat(
        {name: model["held_position"] for name, model in models.items()}, axis=1
    ).ffill().fillna(0.0)
    long_point_positions = pd.concat(
        {name: model["held_long_point"] for name, model in models.items()},
        axis=1,
    ).ffill().fillna(0.0)
    execution_prices = pd.concat(
        {name: model["execution_price"] for name, model in models.items()},
        axis=1,
    ).ffill()

    mask = price_changes.index >= start
    if end is not None:
        mask &= price_changes.index <= end
    price_changes = price_changes.loc[mask]
    point_positions = point_positions.reindex(price_changes.index).ffill().fillna(0.0)
    positions = positions.reindex(price_changes.index).ffill().fillna(0.0)
    long_point_positions = long_point_positions.reindex(
        price_changes.index
    ).ffill().fillna(0.0)
    execution_prices = execution_prices.reindex(price_changes.index).ffill()
    if price_changes.empty:
        raise ValueError("the requested period has no observations")

    # The command-line cost is a full round trip, so each unit of one-way
    # notional turnover pays half. Contract/risk-unit changes are converted to
    # approximate notional turnover using the prior execution price.
    point_turnover = point_positions.diff().abs()
    point_turnover.iloc[0] = point_positions.iloc[0].abs()
    turnover = point_turnover * execution_prices
    long_point_turnover = long_point_positions.diff().abs()
    long_point_turnover.iloc[0] = long_point_positions.iloc[0].abs()
    long_turnover = long_point_turnover * execution_prices
    one_way_cost = args.round_trip_cost_bps / 2.0 / 10_000.0

    gross_sleeve_returns = point_positions * price_changes
    costs = turnover * one_way_cost
    net_sleeve_returns = gross_sleeve_returns - costs
    portfolio_return = net_sleeve_returns.mean(axis=1)
    benchmark_sleeve_returns = (
        long_point_positions * price_changes - long_turnover * one_way_cost
    )
    benchmark_return = benchmark_sleeve_returns.mean(axis=1)

    portfolio_nav = nav_from_returns(portfolio_return, args.balance)
    benchmark_nav = nav_from_returns(benchmark_return, args.balance)
    portfolio_stats = performance(portfolio_return, args.balance)
    benchmark_stats = performance(benchmark_return, args.balance)

    weighted_turnover = turnover.mean(axis=1)
    annual_turnover = weighted_turnover.mean() * 252
    average_gross = positions.abs().mean(axis=1).mean()
    maximum_gross = positions.abs().mean(axis=1).max()

    print("\nCME TIME-SERIES MOMENTUM | PWB DAILY PROXIES")
    print("=" * 78)
    print(
        f"Period: {price_changes.index[0].date()} -> {price_changes.index[-1].date()} "
        f"({len(price_changes):,} portfolio sessions)"
    )
    print(f"Markets: {', '.join(selected)} | initial balance: ${args.balance:,.0f}")
    print(
        f"Lookbacks: {','.join(map(str, args.lookbacks))} | "
        f"vol window: {args.vol_window} | sleeve vol target: {args.asset_vol:.0%}"
    )
    print(
        f"Max sleeve exposure: {args.max_leverage:.2f}x | "
        f"round-trip cost: {args.round_trip_cost_bps:.2f} bps"
    )
    print()
    print(format_stats("Momentum", portfolio_stats))
    print(format_stats("Long-only risk-wt", benchmark_stats))
    print(
        f"Average gross exposure: {average_gross:.2f}x | "
        f"maximum: {maximum_gross:.2f}x | annualized turnover: {annual_turnover:.1f}x"
    )

    print("\nSTANDALONE MARKET SLEEVES")
    for name in selected:
        sleeve_stats = performance(net_sleeve_returns[name], args.balance)
        active_direction = np.sign(positions[name])
        active_direction = active_direction.loc[active_direction.ne(0)]
        changes = max(
            0,
            int(active_direction.ne(active_direction.shift()).sum()) - 1,
        )
        print(
            format_stats(name, sleeve_stats)
            + f"  direction changes={changes}"
        )

    annual = pd.DataFrame(
        {
            "Momentum": portfolio_return,
            "Long-only risk-wt": benchmark_return,
        }
    ).groupby(lambda value: value.year).apply(lambda frame: (1 + frame).prod() - 1)
    print("\nCALENDAR RETURNS")
    print((annual * 100).round(2).to_string())

    print("\nLATEST TARGETS FOR THE NEXT OBSERVED SESSION")
    for name in selected:
        model = models[name]
        available = model.loc[model.index <= price_changes.index[-1]].dropna(
            subset=["target_asof_close"]
        )
        if available.empty:
            print(f"{name}: unavailable (insufficient warmup)")
            continue
        latest = available.iloc[-1]
        target = float(latest["target_asof_close"])
        direction = "LONG" if target > 0 else "SHORT" if target < 0 else "FLAT"
        print(
            f"{name}: {direction:<5} {target:+.2f}x | "
            f"trend score={latest['score']:+.2f} | "
            f"realized vol={latest['realized_vol']:.1%} | "
            f"proxy={MARKETS[name].proxy_note}"
        )

    if args.export is not None:
        export = pd.DataFrame(index=price_changes.index)
        export.index.name = "date"
        export["portfolio_return"] = portfolio_return
        export["portfolio_nav"] = portfolio_nav
        export["benchmark_return"] = benchmark_return
        export["benchmark_nav"] = benchmark_nav
        for name in selected:
            export[f"{name}_price_change"] = price_changes[name]
            export[f"{name}_point_position"] = point_positions[name]
            export[f"{name}_notional_position"] = positions[name]
            export[f"{name}_turnover"] = turnover[name]
            export[f"{name}_net_return"] = net_sleeve_returns[name]
            export[f"{name}_score"] = models[name]["score"].reindex(export.index)
        args.export.parent.mkdir(parents=True, exist_ok=True)
        export.to_csv(args.export)
        print(f"\nExported daily audit trail to {args.export.resolve()}")


if __name__ == "__main__":
    main()
