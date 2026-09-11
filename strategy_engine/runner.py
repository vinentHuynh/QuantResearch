from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .accounting import (
    closed_trade_ledgers,
    performance_metrics,
    pnl_from_closed_trades,
    position_ledgers,
    session_equity,
)
from .catalog import get_strategy
from .data import load_ohlcv, session_bars
from .sessions import get_session
from .sizing import sizing_contract
from .strategies.opening_range_breakout import OpeningRangeBreakoutConfig, run as run_orb
from .strategies.prior_range_fill import PriorRangeFillConfig, run as run_prior_range
from .strategies.relative_value import LegEconomics, RelativeValueConfig, run as run_relative_value
from .strategies.session_drift import SessionDriftConfig, run as run_session_drift
from .strategies.trend import TrendConfig, run as run_trend


ENGINE_VERSION = "1.2.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Canonical strategy engine")
    parser.add_argument("--strategy-id", required=True)
    parser.add_argument("--one-minute", type=Path)
    parser.add_argument("--leg-json", action="append", default=[])
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--tick-size", type=float, required=True)
    parser.add_argument("--point-value", type=float, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--capital", type=float, default=100_000)
    parser.add_argument("--lookback", type=int, default=60)
    parser.add_argument("--opening-range-minutes", type=int, default=15)
    parser.add_argument("--stop-multiple", type=float, default=1.0)
    parser.add_argument("--target-multiple", type=float, default=2.0)
    parser.add_argument("--cost-ticks", type=float, default=1.0)
    parser.add_argument("--quantity-mode", choices=("fractional", "whole_contracts"), default="fractional")
    parser.add_argument("--direction-model", choices=("Long", "Prior trend"), default="Long")
    parser.add_argument("--bracket-exit", action="store_true")
    parser.add_argument("--max-prior-range-pct", type=float, default=0.0)
    return parser.parse_args()


def parse_legs(args: argparse.Namespace) -> list[dict[str, object]]:
    legs = [json.loads(value) for value in args.leg_json]
    if not legs:
        if args.one_minute is None:
            raise ValueError("At least one chart leg is required")
        legs = [{
            "id": args.symbol,
            "symbol": args.symbol,
            "path": str(args.one_minute),
            "tick_size": args.tick_size,
            "point_value": args.point_value,
        }]
    symbols = [str(leg["symbol"]) for leg in legs]
    if len(symbols) != len(set(symbols)):
        raise ValueError("Chart legs must have unique symbols")
    return legs


def _write_ledgers(
    output_dir: Path,
    pnl: pd.DataFrame,
    signals: pd.DataFrame,
    capital: float,
    bars: pd.DataFrame,
    trades: pd.DataFrame | None = None,
    positions: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    signals.to_csv(output_dir / "signals.csv", index=False)
    if positions is None:
        trades = trades if trades is not None else pd.DataFrame()
        orders, fills, positions = closed_trade_ledgers(trades)
    else:
        trades, orders, fills = position_ledgers(positions, pnl)
    pnl.to_csv(output_dir / "pnl.csv", index=False)
    trades.to_csv(output_dir / "trades.csv", index=False)
    orders.to_csv(output_dir / "orders.csv", index=False)
    fills.to_csv(output_dir / "fills.csv", index=False)
    positions.to_csv(output_dir / "positions.csv", index=False)
    equity = session_equity(bars, pnl, capital)
    equity.to_csv(output_dir / "equity.csv", index=False)
    return trades, positions, orders, equity


def main() -> None:
    args = parse_args()
    manifest = get_strategy(args.strategy_id)
    session = get_session(args.session_id)
    legs = parse_legs(args)
    if not manifest.minimum_legs <= len(legs) <= manifest.maximum_legs:
        raise ValueError(f"{manifest.name} received an invalid number of chart legs")
    if args.timeframe not in manifest.timeframes:
        raise ValueError(f"{manifest.name} does not support {args.timeframe}")
    if session.id not in manifest.sessions:
        raise ValueError(f"{manifest.name} does not support {session.name}")
    sources = {
        str(leg["symbol"]): load_ohlcv(Path(str(leg["path"])), args.start, args.end)
        for leg in legs
    }
    bars_by_symbol = {
        symbol: session_bars(source, session, args.timeframe)
        for symbol, source in sources.items()
    }
    bars = next(iter(bars_by_symbol.values()))
    positions = None
    closed_trades = None
    if manifest.id == "opening-range-breakout":
        one_minute_session_bars = session_bars(next(iter(sources.values())), session, "1m")
        config = OpeningRangeBreakoutConfig(
            opening_range_minutes=args.opening_range_minutes,
            stop_multiple=args.stop_multiple,
            target_multiple=args.target_multiple,
            cost_ticks=args.cost_ticks,
        )
        closed_trades, signals = run_orb(
            bars,
            opening_bars=one_minute_session_bars,
            symbol=args.symbol,
            tick_size=args.tick_size,
            point_value=args.point_value,
            config=config,
        )
    elif manifest.id == "prior-range-fill":
        config = PriorRangeFillConfig(cost_ticks=args.cost_ticks)
        closed_trades, signals = run_prior_range(
            bars,
            symbol=args.symbol,
            tick_size=args.tick_size,
            point_value=args.point_value,
            config=config,
        )
    elif manifest.id == "overnight-session":
        config = SessionDriftConfig(
            direction_model=args.direction_model,
            bracket_exit=args.bracket_exit,
            max_prior_range_pct=args.max_prior_range_pct,
            stop_multiple=args.stop_multiple,
            target_multiple=args.target_multiple,
            cost_ticks=args.cost_ticks,
            quantity_mode=args.quantity_mode,
        )
        closed_trades, signals = run_session_drift(
            bars,
            symbol=args.symbol,
            tick_size=args.tick_size,
            point_value=args.point_value,
            config=config,
        )
    elif manifest.id in {"cross-sectional-momentum", "pairs-mean-reversion"}:
        economics = {
            str(leg["symbol"]): LegEconomics(float(leg["tick_size"]), float(leg["point_value"]))
            for leg in legs
        }
        config = RelativeValueConfig(
            strategy_id=manifest.id,
            lookback=args.lookback,
            capital=args.capital,
            cost_ticks=args.cost_ticks,
            quantity_mode=args.quantity_mode,
        )
        pnl, signals, positions = run_relative_value(bars_by_symbol, economics, config)
    elif manifest.id in {"multi-speed-momentum", "moving-average-trend"}:
        config = TrendConfig(
            strategy_id=manifest.id,
            lookback=args.lookback,
            capital=args.capital,
            cost_ticks=args.cost_ticks,
            quantity_mode=args.quantity_mode,
        )
        pnl, signals, positions = run_trend(
            bars,
            symbol=str(legs[0]["symbol"]),
            economics=LegEconomics(float(legs[0]["tick_size"]), float(legs[0]["point_value"])),
            config=config,
        )
    else:
        raise ValueError(f"No implementation registered for {manifest.id}")
    if closed_trades is not None:
        pnl = pnl_from_closed_trades(closed_trades)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    trades, positions, orders, equity = _write_ledgers(
        args.output_dir, pnl, signals, args.capital, bars, closed_trades, positions,
    )
    statistics = performance_metrics(
        equity=equity, trades=trades, pnl=pnl, positions=positions,
        orders=orders, capital=args.capital,
    )
    strategy_parameters: dict[str, object] = {
        "capital": args.capital,
        "cost_ticks": args.cost_ticks,
    }
    if manifest.id == "opening-range-breakout":
        strategy_parameters.update({
            "opening_range_minutes": args.opening_range_minutes,
            "stop_multiple": args.stop_multiple,
            "target_multiple": args.target_multiple,
        })
    elif manifest.id == "overnight-session":
        strategy_parameters.update({
            "direction_model": args.direction_model,
            "bracket_exit": args.bracket_exit,
            "max_prior_range_pct": args.max_prior_range_pct,
            "stop_multiple": args.stop_multiple,
            "target_multiple": args.target_multiple,
        })
    elif manifest.id in {"cross-sectional-momentum", "pairs-mean-reversion", "multi-speed-momentum", "moving-average-trend"}:
        strategy_parameters["lookback"] = args.lookback
        strategy_parameters["quantity_mode"] = args.quantity_mode
    effective_quantity_mode = (
        args.quantity_mode
        if manifest.id in {"cross-sectional-momentum", "pairs-mean-reversion", "multi-speed-momentum", "moving-average-trend"}
        else "whole_contracts"
    )
    run_spec = {
        "engine_version": ENGINE_VERSION,
        "strategy": {"id": manifest.id, "name": manifest.name, "version": manifest.version},
        "instruments": legs,
        "timeframe": args.timeframe,
        "session": session.public(),
        "evaluation_period": {"start": args.start, "end": args.end},
        "parameters": strategy_parameters,
        "accounting": {
            "pnl_frequency": "session",
            "equity_includes_zero_pnl_sessions": True,
            "trade_definition": "closed exposure episode",
            "position_quantity": sizing_contract(effective_quantity_mode),
        },
    }
    summary = {
        "strategy_id": manifest.id,
        "strategy_name": manifest.name,
        "strategy_version": manifest.version,
        "symbol": "/".join(str(leg["symbol"]) for leg in legs),
        "timeframe": args.timeframe,
        "session_id": session.id,
        "session_name": session.name,
        "methodology": f"{session.name} {manifest.name.lower()}",
        "statistics": statistics,
        "costs": {
            "round_trip_ticks": args.cost_ticks,
            "basis": "round_trip_ticks_per_contract",
            "tick_size": args.tick_size,
            "point_value": args.point_value,
            "legs": {
                str(leg["symbol"]): {
                    "tick_size": float(leg["tick_size"]),
                    "point_value": float(leg["point_value"]),
                }
                for leg in legs
            },
        },
        "sizing": sizing_contract(effective_quantity_mode),
        "evaluation_period": run_spec["evaluation_period"],
    }
    (args.output_dir / "run_spec.json").write_text(json.dumps(run_spec, indent=2))
    (args.output_dir / "metrics.json").write_text(json.dumps(statistics, indent=2))
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
