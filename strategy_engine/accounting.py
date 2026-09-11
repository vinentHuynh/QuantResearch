from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


TRADE_COLUMNS = [
    "entry_time", "exit_time", "session_id", "session_date", "symbol", "side",
    "entry", "exit", "quantity", "gross_pnl", "cost", "net_pnl", "reason",
]
SIGNAL_COLUMNS = [
    "event_time", "session_id", "session_date", "symbol", "side", "level", "reason",
]
POSITION_COLUMNS = [
    "event_time", "session_id", "session_date", "symbol", "quantity", "price",
]
PNL_COLUMNS = [
    "period_start", "period_end", "availability_time", "session_id", "session_date",
    "symbol", "quantity", "gross_pnl", "cost", "net_pnl",
]


def bar_availability(bars: pd.DataFrame) -> pd.Series:
    if "availability_time" in bars:
        values = pd.to_datetime(bars.availability_time, utc=True)
        return pd.Series(values.array, index=bars.index)
    return pd.Series(bars.index.tz_convert("UTC"), index=bars.index)


def pnl_from_closed_trades(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for trade in trades.to_dict("records"):
        signed_quantity = float(trade["quantity"]) * (1 if trade["side"] == "long" else -1)
        rows.append({
            "period_start": trade["entry_time"],
            "period_end": trade["exit_time"],
            "availability_time": trade["exit_time"],
            "session_id": trade["session_id"],
            "session_date": trade["session_date"],
            "symbol": trade["symbol"],
            "quantity": signed_quantity,
            "gross_pnl": float(trade["gross_pnl"]),
            "cost": float(trade["cost"]),
            "net_pnl": float(trade["net_pnl"]),
        })
    return pd.DataFrame(rows, columns=PNL_COLUMNS)


def closed_trade_ledgers(trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    order_rows: list[dict[str, Any]] = []
    fill_rows: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []
    for trade in trades.to_dict("records"):
        is_long = trade["side"] == "long"
        signed_quantity = float(trade["quantity"]) * (1 if is_long else -1)
        entry_side, exit_side = ("buy", "sell") if is_long else ("sell", "buy")
        for event_time, side, price, reason in (
            (trade["entry_time"], entry_side, trade["entry"], "entry"),
            (trade["exit_time"], exit_side, trade["exit"], "exit"),
        ):
            common = {
                "event_time": event_time,
                "session_id": trade["session_id"],
                "session_date": trade["session_date"],
                "symbol": trade["symbol"],
                "side": side,
                "quantity": float(trade["quantity"]),
                "reason": reason,
            }
            order_rows.append({**common, "limit_price": float(price)})
            fill_rows.append({
                **common,
                "fill_price": float(price),
                "cost": float(trade["cost"]) / 2.0,
            })
        position_rows.extend([
            {
                "event_time": trade["entry_time"], "session_id": trade["session_id"],
                "session_date": trade["session_date"], "symbol": trade["symbol"],
                "quantity": signed_quantity, "price": float(trade["entry"]),
            },
            {
                "event_time": trade["exit_time"], "session_id": trade["session_id"],
                "session_date": trade["session_date"], "symbol": trade["symbol"],
                "quantity": 0.0, "price": float(trade["exit"]),
            },
        ])
    orders = pd.DataFrame(order_rows, columns=[
        "event_time", "session_id", "session_date", "symbol", "side", "quantity",
        "limit_price", "reason",
    ])
    fills = pd.DataFrame(fill_rows, columns=[
        "event_time", "session_id", "session_date", "symbol", "side", "quantity",
        "fill_price", "cost", "reason",
    ])
    positions = pd.DataFrame(position_rows, columns=POSITION_COLUMNS)
    return orders, fills, positions


def position_ledgers(
    positions: pd.DataFrame,
    pnl: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    positions = positions.copy()
    positions["event_timestamp"] = pd.to_datetime(positions.event_time, utc=True)
    positions = positions.sort_values(["symbol", "event_timestamp"]).reset_index(drop=True)
    positions["quantity_change"] = positions.groupby("symbol").quantity.diff().fillna(positions.quantity)
    changes = positions.loc[positions.quantity_change.abs() > 1e-12].copy()
    changes["side"] = np.where(changes.quantity_change > 0, "buy", "sell")
    changes["order_quantity"] = changes.quantity_change.abs()

    cost_by_fill: dict[tuple[str, pd.Timestamp], float] = {}
    if not pnl.empty:
        cost_frame = pnl.assign(period_timestamp=pd.to_datetime(pnl.period_end, utc=True))
        cost_by_fill = cost_frame.groupby(["symbol", "period_timestamp"]).cost.sum().to_dict()
    changes["cost"] = [
        float(cost_by_fill.get((str(row.symbol), row.event_timestamp), 0.0))
        for row in changes.itertuples()
    ]
    orders = changes[[
        "event_time", "session_id", "session_date", "symbol", "side", "order_quantity", "price",
    ]].rename(columns={"order_quantity": "quantity", "price": "limit_price"})
    orders["reason"] = "target_position_change"
    fills = changes[[
        "event_time", "session_id", "session_date", "symbol", "side", "order_quantity", "price", "cost",
    ]].rename(columns={"order_quantity": "quantity", "price": "fill_price"})
    fills["reason"] = "target_position_change"
    trades = _position_episodes(positions, pnl)
    return trades, orders, fills


def _position_episodes(positions: pd.DataFrame, pnl: pd.DataFrame) -> pd.DataFrame:
    pnl_frame = pnl.copy()
    if not pnl_frame.empty:
        pnl_frame["period_timestamp"] = pd.to_datetime(pnl_frame.period_end, utc=True)
    completed: list[dict[str, Any]] = []
    for symbol, symbol_positions in positions.groupby("symbol", sort=False):
        marks = pnl_frame.loc[pnl_frame.symbol == symbol] if not pnl_frame.empty else pnl_frame
        mark_by_time = {
            row.period_timestamp: row for row in marks.itertuples()
        }
        active: dict[str, Any] | None = None
        prior_quantity = 0.0
        for row in symbol_positions.itertuples():
            quantity = float(row.quantity)
            prior_sign = int(np.sign(prior_quantity))
            next_sign = int(np.sign(quantity))
            mark = mark_by_time.get(row.event_timestamp)
            gross = float(mark.gross_pnl) if mark is not None else 0.0
            cost = float(mark.cost) if mark is not None else 0.0
            if active is not None:
                active["gross_pnl"] += gross

            if prior_sign == next_sign:
                if active is not None:
                    active["cost"] += cost
            elif prior_sign == 0 and next_sign != 0:
                active = _open_episode(row, quantity)
                active["cost"] += cost
            elif prior_sign != 0 and next_sign == 0:
                if active is not None:
                    active["cost"] += cost
                    completed.append(_close_episode(active, row, "position_flattened"))
                active = None
            else:
                total_turnover = abs(prior_quantity) + abs(quantity)
                close_share = abs(prior_quantity) / total_turnover if total_turnover else 0.5
                if active is not None:
                    active["cost"] += cost * close_share
                    completed.append(_close_episode(active, row, "position_reversed"))
                active = _open_episode(row, quantity)
                active["cost"] += cost * (1.0 - close_share)
            prior_quantity = quantity
    return pd.DataFrame(completed, columns=TRADE_COLUMNS)


def _open_episode(row: Any, quantity: float) -> dict[str, Any]:
    return {
        "entry_time": row.event_time,
        "session_id": row.session_id,
        "session_date": row.session_date,
        "symbol": row.symbol,
        "side": "long" if quantity > 0 else "short",
        "entry": float(row.price),
        "quantity": abs(quantity),
        "gross_pnl": 0.0,
        "cost": 0.0,
    }


def _close_episode(active: dict[str, Any], row: Any, reason: str) -> dict[str, Any]:
    return {
        **active,
        "exit_time": row.event_time,
        "exit": float(row.price),
        "net_pnl": float(active["gross_pnl"] - active["cost"]),
        "reason": reason,
    }


def session_equity(bars: pd.DataFrame, pnl: pd.DataFrame, capital: float) -> pd.DataFrame:
    availability = bar_availability(bars)
    session_ends = pd.Series(
        {
            session_date: availability.loc[day.index[-1]]
            for session_date, day in bars.groupby("session_date", sort=True)
        },
        name="event_time",
    )
    session_net = pnl.groupby("session_date").net_pnl.sum() if not pnl.empty else pd.Series(dtype=float)
    session_gross = pnl.groupby("session_date").gross_pnl.sum() if not pnl.empty else pd.Series(dtype=float)
    session_cost = pnl.groupby("session_date").cost.sum() if not pnl.empty else pd.Series(dtype=float)
    equity = pd.DataFrame({
        "session_date": session_ends.index,
        "event_time": [timestamp.isoformat() for timestamp in session_ends],
        "availability_time": [timestamp.isoformat() for timestamp in session_ends],
        "history_type": "backtest",
        "gross_pnl": session_gross.reindex(session_ends.index).fillna(0.0).to_numpy(),
        "cost": session_cost.reindex(session_ends.index).fillna(0.0).to_numpy(),
        "net_pnl": session_net.reindex(session_ends.index).fillna(0.0).to_numpy(),
    })
    equity["equity"] = capital + equity.net_pnl.cumsum()
    return equity


def performance_metrics(
    *,
    equity: pd.DataFrame,
    trades: pd.DataFrame,
    pnl: pd.DataFrame,
    positions: pd.DataFrame,
    orders: pd.DataFrame,
    capital: float,
) -> dict[str, float | int | str | None]:
    session_pnl = equity.net_pnl.astype(float)
    high_water = pd.concat([pd.Series([capital]), equity.equity], ignore_index=True).cummax().iloc[1:].set_axis(equity.index)
    drawdown = equity.equity - high_water
    deviation = float((session_pnl / capital).std(ddof=1)) if len(session_pnl) > 1 else 0.0
    trade_pnl = trades.net_pnl.astype(float) if not trades.empty else pd.Series(dtype=float)
    wins = float(trade_pnl.loc[trade_pnl > 0].sum())
    losses = float(-trade_pnl.loc[trade_pnl < 0].sum())
    final_positions = positions.sort_values("event_time").groupby("symbol").tail(1) if not positions.empty else positions
    active_sessions = int(pnl.loc[(pnl.quantity.abs() > 1e-12) | (pnl.cost.abs() > 1e-12), "session_date"].nunique()) if not pnl.empty else 0
    return {
        "sessions": int(len(equity)),
        "active_sessions": active_sessions,
        "trades": int(len(trades)),
        "open_positions": int((final_positions.quantity.abs() > 1e-12).sum()) if not final_positions.empty else 0,
        "orders": int(len(orders)),
        "pnl_observations": int(len(pnl)),
        "net_dollars": float(session_pnl.sum()),
        "gross_dollars": float(pnl.gross_pnl.sum()) if not pnl.empty else 0.0,
        "cost_dollars": float(pnl.cost.sum()) if not pnl.empty else 0.0,
        "return_pct_initial": float(session_pnl.sum() / capital * 100.0),
        "profit_factor": wins / losses if losses > 0 else (999.0 if wins > 0 else None),
        "sharpe": float((session_pnl / capital).mean() / deviation * np.sqrt(252)) if deviation > 0 else 0.0,
        "win_rate": float((trade_pnl > 0).mean()) if len(trade_pnl) else None,
        "winning_session_rate": float((session_pnl > 0).mean()) if len(session_pnl) else None,
        "max_drawdown_dollars": float(drawdown.min()) if len(drawdown) else 0.0,
        "max_drawdown_pct_initial": float(drawdown.min() / capital * 100.0) if len(drawdown) else 0.0,
        "pnl_frequency": "session",
        "annualization_sessions": 252,
    }
