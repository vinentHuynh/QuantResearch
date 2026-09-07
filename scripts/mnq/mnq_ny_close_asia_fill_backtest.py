"""Test whether MNQ revisits the New York close during the Asia session.

The tradeable event is defined without look-ahead:

* reference level: the completed 16:00 ET (cash) or 17:00 ET (futures) close;
* entry: the 18:00 ET Globex reopen;
* direction: short an up-gap, long a down-gap;
* target: the selected New York close;
* deadline: 00:00 ET (the end of the workspace's Asia block);
* non-fill exit: the close of the last available bar before 00:00 ET.

The source is the workspace's Databento 5-minute, unadjusted continuous MNQ
series.  By default, the reference close must be no more than four hours old,
which excludes Sunday and holiday reopens.  Those stale-close events can be
included for a separate weekend study with --max-reference-age-hours 100.

Examples:

    python mnq_ny_close_asia_fill_backtest.py
    python mnq_ny_close_asia_fill_backtest.py --close-times 17:00
    python mnq_ny_close_asia_fill_backtest.py --cost-ticks 2 --start 2023-01-01
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
DEFAULT_DATA = ROOT / "data" / "MNQ_5min_databento.parquet"
DEFAULT_OUT = ROOT / "reports" / "mnq_ny_close_asia_fill"
TICK_SIZE = 0.25
DOLLARS_PER_POINT = 2.0
DEFAULT_POINT_BINS = "0,1,2,3,5,10,15,20,30,50,75,100,150,250,inf"
DEFAULT_BPS_BINS = "0,0.5,1,2,3,5,7.5,10,15,25,40,60,100,inf"
DEFAULT_BPS_THRESHOLDS = (0.5, 1, 2, 3, 5, 7.5, 10, 15, 25, 40, 60, 100)


def parse_clock(value: str) -> tuple[int, int]:
    """Parse HH:MM using a strict 24-hour clock."""
    try:
        hour, minute = (int(part) for part in value.split(":"))
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"invalid clock time: {value!r}") from None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise argparse.ArgumentTypeError(f"invalid clock time: {value!r}")
    return hour, minute


def parse_bins(value: str) -> list[float]:
    """Parse increasing comma-separated bin edges; final edge may be inf."""
    try:
        result = [float(part.strip()) for part in value.split(",")]
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid bin edges: {value!r}") from None
    if len(result) < 2 or result[0] < 0:
        raise argparse.ArgumentTypeError("bins need at least two non-negative edges")
    if any(not left < right for left, right in zip(result, result[1:])):
        raise argparse.ArgumentTypeError("bin edges must be strictly increasing")
    if not math.isinf(result[-1]):
        raise argparse.ArgumentTypeError("the final bin edge must be inf")
    return result


def load_bars(path: Path) -> tuple[pd.DataFrame, pd.Timedelta]:
    """Load and validate timezone-aware OHLC data, returning its bar interval."""
    if not path.exists():
        raise FileNotFoundError(f"MNQ data not found: {path}")
    df = pd.read_parquet(path).sort_index()
    required = {"open", "high", "low", "close"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"missing OHLC columns: {sorted(missing)}")
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.tz is None:
        raise ValueError("the bar index must be a timezone-aware DatetimeIndex")
    if df.index.has_duplicates:
        raise ValueError("the bar index contains duplicate timestamps")
    df = df[["open", "high", "low", "close"]].astype(float)
    if df.isna().any().any():
        raise ValueError("OHLC data contains missing values")
    if not ((df["low"] <= df[["open", "close"]].min(axis=1)) &
            (df["high"] >= df[["open", "close"]].max(axis=1))).all():
        raise ValueError("one or more bars violate OHLC bounds")

    # The median is robust to the daily maintenance break and weekends.
    bar_delta = df.index.to_series().diff().median()
    if bar_delta <= pd.Timedelta(0):
        raise ValueError("could not infer a positive bar interval")
    return df, bar_delta


def clock_mask(index: pd.DatetimeIndex, clock: tuple[int, int]) -> np.ndarray:
    return (index.hour == clock[0]) & (index.minute == clock[1])


def reference_closes(
    bars: pd.DataFrame,
    close_time: str,
    bar_delta: pd.Timedelta,
) -> pd.DataFrame:
    """Return completed close levels stamped at their effective close time."""
    close_clock = parse_clock(close_time)
    close_minutes = close_clock[0] * 60 + close_clock[1]
    bar_minutes = int(bar_delta.total_seconds() // 60)
    stamp_minutes = (close_minutes - bar_minutes) % (24 * 60)
    stamp_clock = divmod(stamp_minutes, 60)
    selected = bars.loc[clock_mask(bars.index, stamp_clock), ["close"]].copy()
    selected = selected.rename(columns={"close": "ny_close"})
    selected["close_bar_ts"] = selected.index
    selected["reference_ts"] = selected.index + bar_delta
    selected["reference_close"] = close_time
    return selected.reset_index(drop=True)


def build_events(
    bars: pd.DataFrame,
    close_time: str,
    asia_start: str,
    asia_end: str,
    bar_delta: pd.Timedelta,
    max_reference_age_hours: float,
    min_asia_bars: int,
    min_gap_points: float,
    cost_ticks: float,
) -> pd.DataFrame:
    """Build one close-to-Asia-fill observation per eligible trading session."""
    asia_start_clock = parse_clock(asia_start)
    asia_end_clock = parse_clock(asia_end)
    starts = bars.loc[clock_mask(bars.index, asia_start_clock), ["open"]].copy()
    starts = starts.rename(columns={"open": "entry_price"})
    starts["asia_start_ts"] = starts.index
    starts = starts.reset_index(drop=True).sort_values("asia_start_ts")

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

    records: list[dict] = []
    cost_points = cost_ticks * TICK_SIZE
    for row in paired.itertuples(index=False):
        start_ts = row.asia_start_ts
        # Construct the next local occurrence of the Asia end clock.  Using a
        # local DateOffset preserves the intended wall-clock boundary over DST.
        end_ts = start_ts.normalize() + pd.DateOffset(
            hours=asia_end_clock[0], minutes=asia_end_clock[1]
        )
        if end_ts <= start_ts:
            end_ts += pd.DateOffset(days=1)
        session = bars.loc[(bars.index >= start_ts) & (bars.index < end_ts)]
        if len(session) < min_asia_bars:
            continue

        raw_gap = float(row.entry_price - row.ny_close)
        gap_points = abs(raw_gap)
        if gap_points < min_gap_points or raw_gap == 0:
            continue
        side = "Short" if raw_gap > 0 else "Long"
        side_sign = -1.0 if side == "Short" else 1.0
        if side == "Short":
            fill_mask = session["low"] <= row.ny_close
        else:
            fill_mask = session["high"] >= row.ny_close

        filled = bool(fill_mask.any())
        if filled:
            fill_bar_ts = fill_mask[fill_mask].index[0]
            exit_ts = fill_bar_ts + bar_delta
            exit_price = float(row.ny_close)
            bars_to_exit = session.loc[:fill_bar_ts]
            fill_minutes = (exit_ts - start_ts).total_seconds() / 60
        else:
            fill_bar_ts = pd.NaT
            exit_ts = session.index[-1] + bar_delta
            exit_price = float(session["close"].iloc[-1])
            bars_to_exit = session
            fill_minutes = np.nan

        if side == "Long":
            mae_points = max(0.0, float(row.entry_price - bars_to_exit["low"].min()))
            mfe_points = max(0.0, float(bars_to_exit["high"].max() - row.entry_price))
        else:
            mae_points = max(0.0, float(bars_to_exit["high"].max() - row.entry_price))
            mfe_points = max(0.0, float(row.entry_price - bars_to_exit["low"].min()))

        gross_points = side_sign * (exit_price - float(row.entry_price))
        net_points = gross_points - cost_points
        records.append(
            {
                "reference_close": close_time,
                "reference_ts": row.reference_ts,
                "reference_age_hours": row.reference_age_hours,
                "asia_start_ts": start_ts,
                "asia_end_ts": end_ts,
                "side": side,
                "ny_close": row.ny_close,
                "entry_price": row.entry_price,
                "raw_gap_points": raw_gap,
                "gap_points": gap_points,
                "gap_bps": gap_points / row.ny_close * 10_000,
                "filled": filled,
                "fill_bar_ts": fill_bar_ts,
                "fill_minutes_upper_bound": fill_minutes,
                "exit_ts": exit_ts,
                "exit_price": exit_price,
                "gross_points": gross_points,
                "net_points": net_points,
                "gross_pnl_dollars": gross_points * DOLLARS_PER_POINT,
                "net_pnl_dollars": net_points * DOLLARS_PER_POINT,
                "mae_points_bar_based": mae_points,
                "mfe_points_bar_based": mfe_points,
                "asia_bars": len(session),
            }
        )
    return pd.DataFrame.from_records(records)


def wilson_interval(successes: int, total: int, z: float = 1.959964) -> tuple[float, float]:
    if total == 0:
        return np.nan, np.nan
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z / denominator * math.sqrt(
        p * (1 - p) / total + z * z / (4 * total * total)
    )
    return center - margin, center + margin


def max_drawdown_dollars(pnl: pd.Series) -> float:
    curve = pnl.cumsum()
    drawdown = curve - curve.cummax().clip(lower=0)
    return abs(float(drawdown.min())) if not drawdown.empty else np.nan


def summarize_group(frame: pd.DataFrame) -> dict:
    n = len(frame)
    fills = int(frame["filled"].sum())
    ci_low, ci_high = wilson_interval(fills, n)
    positive = frame.loc[frame["net_pnl_dollars"] > 0, "net_pnl_dollars"].sum()
    negative = frame.loc[frame["net_pnl_dollars"] < 0, "net_pnl_dollars"].sum()
    profit_factor = positive / abs(negative) if negative != 0 else np.inf
    pnl_mean = frame["net_pnl_dollars"].mean()
    pnl_se = frame["net_pnl_dollars"].std(ddof=1) / math.sqrt(n) if n > 1 else np.nan
    return {
        "trades": n,
        "fills": fills,
        "fill_rate": fills / n if n else np.nan,
        "fill_ci95_low": ci_low,
        "fill_ci95_high": ci_high,
        "median_gap_points": frame["gap_points"].median(),
        "mean_gap_points": frame["gap_points"].mean(),
        "mean_gap_bps": frame["gap_bps"].mean(),
        "median_fill_minutes": frame.loc[frame["filled"], "fill_minutes_upper_bound"].median(),
        "avg_gross_pnl_dollars": frame["gross_pnl_dollars"].mean(),
        "avg_net_pnl_dollars": pnl_mean,
        "avg_net_pnl_ci95_low": pnl_mean - 1.959964 * pnl_se,
        "avg_net_pnl_ci95_high": pnl_mean + 1.959964 * pnl_se,
        "net_pnl_tstat": pnl_mean / pnl_se if pnl_se and np.isfinite(pnl_se) else np.nan,
        "total_net_pnl_dollars": frame["net_pnl_dollars"].sum(),
        "net_win_rate": (frame["net_pnl_dollars"] > 0).mean(),
        "profit_factor": profit_factor,
        "max_drawdown_dollars": max_drawdown_dollars(frame["net_pnl_dollars"]),
        "avg_mae_points": frame["mae_points_bar_based"].mean(),
    }


def grouped_summary(events: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    rows: list[dict] = []
    for keys, frame in events.groupby(group_columns, observed=True, sort=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        rows.append(dict(zip(group_columns, keys)) | summarize_group(frame.sort_values("asia_start_ts")))
    return pd.DataFrame(rows)


def add_all_sides(events: pd.DataFrame) -> pd.DataFrame:
    combined = events.copy()
    combined["side"] = "All"
    return pd.concat([combined, events], ignore_index=True)


def bin_labels(edges: Iterable[float], unit: str) -> list[str]:
    edges = list(edges)
    labels = []
    for left, right in zip(edges, edges[1:]):
        right_label = "+" if math.isinf(right) else f"-{right:g}"
        labels.append(f"{left:g}{right_label} {unit}")
    return labels


def bucket_summary(events: pd.DataFrame, value_column: str, edges: list[float], unit: str) -> pd.DataFrame:
    work = add_all_sides(events)
    work["gap_bucket"] = pd.cut(
        work[value_column],
        bins=edges,
        labels=bin_labels(edges, unit),
        right=False,
        include_lowest=True,
    )
    result = grouped_summary(work.dropna(subset=["gap_bucket"]), ["reference_close", "side", "gap_bucket"])
    result.insert(1, "bucket_unit", unit)
    order = {label: number for number, label in enumerate(bin_labels(edges, unit))}
    result["_bucket_order"] = result["gap_bucket"].map(order)
    return result.sort_values(
        ["reference_close", "side", "_bucket_order"]
    ).drop(columns="_bucket_order").reset_index(drop=True)


def threshold_summary(
    events: pd.DataFrame,
    thresholds: Iterable[float] = DEFAULT_BPS_THRESHOLDS,
) -> pd.DataFrame:
    """Summarize cumulative filters of the form absolute gap < N bps."""
    rows = []
    for threshold in thresholds:
        work = add_all_sides(events[events["gap_bps"] < threshold])
        for keys, frame in work.groupby(["reference_close", "side"], sort=False):
            rows.append(
                {"reference_close": keys[0], "side": keys[1], "max_gap_bps": threshold}
                | summarize_group(frame.sort_values("asia_start_ts"))
            )
    return pd.DataFrame(rows).sort_values(
        ["reference_close", "side", "max_gap_bps"]
    ).reset_index(drop=True)


def threshold_stability_summary(
    events: pd.DataFrame,
    thresholds: Iterable[float] = DEFAULT_BPS_THRESHOLDS,
) -> pd.DataFrame:
    """Apply every cumulative threshold separately to two chronological halves."""
    pieces = []
    for close_time, close_frame in events.groupby("reference_close", sort=False):
        dates = close_frame["asia_start_ts"].sort_values()
        split_ts = dates.iloc[len(dates) // 2]
        for threshold in thresholds:
            work = close_frame[close_frame["gap_bps"] < threshold].copy()
            work["sample"] = np.where(
                work["asia_start_ts"] < split_ts, "First half", "Second half"
            )
            work = add_all_sides(work)
            summary = grouped_summary(
                work, ["reference_close", "sample", "side"]
            )
            summary.insert(2, "split_ts", split_ts)
            summary.insert(3, "max_gap_bps", threshold)
            pieces.append(summary)
    return pd.concat(pieces, ignore_index=True)


def threshold_annual_summary(
    events: pd.DataFrame,
    thresholds: Iterable[float] = DEFAULT_BPS_THRESHOLDS,
) -> pd.DataFrame:
    """Calendar-year diagnostics for each overlapping cumulative filter."""
    pieces = []
    for threshold in thresholds:
        work = events[events["gap_bps"] < threshold].copy()
        work["year"] = work["asia_start_ts"].dt.year
        work = add_all_sides(work)
        summary = grouped_summary(
            work, ["reference_close", "year", "side"]
        )
        summary.insert(2, "max_gap_bps", threshold)
        pieces.append(summary)
    return pd.concat(pieces, ignore_index=True)


def side_comparison(events: pd.DataFrame) -> pd.DataFrame:
    """Long-minus-short fill-rate comparison with an unpooled 95% interval."""
    rows = []
    for close_time, frame in events.groupby("reference_close", sort=False):
        long = frame[frame["side"] == "Long"]
        short = frame[frame["side"] == "Short"]
        p_long, p_short = long["filled"].mean(), short["filled"].mean()
        se = math.sqrt(
            p_long * (1 - p_long) / len(long)
            + p_short * (1 - p_short) / len(short)
        )
        difference = p_long - p_short
        z_score = difference / se if se else np.nan
        p_value = math.erfc(abs(z_score) / math.sqrt(2)) if np.isfinite(z_score) else np.nan
        rows.append(
            {
                "reference_close": close_time,
                "long_trades": len(long),
                "short_trades": len(short),
                "long_fill_rate": p_long,
                "short_fill_rate": p_short,
                "long_minus_short_fill_rate": difference,
                "difference_ci95_low": difference - 1.959964 * se,
                "difference_ci95_high": difference + 1.959964 * se,
                "two_sided_p_value": p_value,
                "long_avg_net_pnl_dollars": long["net_pnl_dollars"].mean(),
                "short_avg_net_pnl_dollars": short["net_pnl_dollars"].mean(),
                "long_minus_short_avg_net_pnl_dollars": (
                    long["net_pnl_dollars"].mean() - short["net_pnl_dollars"].mean()
                ),
            }
        )
    return pd.DataFrame(rows)


def stability_summary(events: pd.DataFrame) -> pd.DataFrame:
    pieces = []
    for close_time, frame in events.groupby("reference_close", sort=False):
        dates = frame["asia_start_ts"].sort_values()
        split_ts = dates.iloc[len(dates) // 2]
        work = frame.copy()
        work["sample"] = np.where(work["asia_start_ts"] < split_ts, "First half", "Second half")
        work = add_all_sides(work)
        summary = grouped_summary(work, ["reference_close", "sample", "side"])
        summary.insert(2, "split_ts", split_ts)
        pieces.append(summary)
    return pd.concat(pieces, ignore_index=True)


def annual_summary(events: pd.DataFrame) -> pd.DataFrame:
    work = events.copy()
    work["year"] = work["asia_start_ts"].dt.year
    work = add_all_sides(work)
    return grouped_summary(work, ["reference_close", "year", "side"])


def cost_sensitivity(events: pd.DataFrame, tick_costs: Iterable[float] = (0, 1, 2, 4)) -> pd.DataFrame:
    rows = []
    for ticks in tick_costs:
        work = events.copy()
        work["net_pnl_dollars"] = (
            work["gross_pnl_dollars"] - ticks * TICK_SIZE * DOLLARS_PER_POINT
        )
        work = add_all_sides(work)
        for keys, frame in work.groupby(["reference_close", "side"], sort=False):
            positive = frame.loc[frame["net_pnl_dollars"] > 0, "net_pnl_dollars"].sum()
            negative = frame.loc[frame["net_pnl_dollars"] < 0, "net_pnl_dollars"].sum()
            rows.append(
                {
                    "reference_close": keys[0],
                    "side": keys[1],
                    "cost_ticks": ticks,
                    "trades": len(frame),
                    "avg_net_pnl_dollars": frame["net_pnl_dollars"].mean(),
                    "total_net_pnl_dollars": frame["net_pnl_dollars"].sum(),
                    "profit_factor": positive / abs(negative) if negative != 0 else np.inf,
                    "max_drawdown_dollars": max_drawdown_dollars(frame["net_pnl_dollars"]),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["reference_close", "side", "cost_ticks"]
    ).reset_index(drop=True)


def pct(value: float) -> str:
    return "n/a" if pd.isna(value) else f"{value:.1%}"


def markdown_table(frame: pd.DataFrame, columns: list[str], formats: dict[str, str] | None = None) -> str:
    formats = formats or {}
    view = frame[columns].copy()
    for column, format_spec in formats.items():
        view[column] = view[column].map(lambda value: "n/a" if pd.isna(value) else format(value, format_spec))
    headers = "| " + " | ".join(columns) + " |"
    rule = "| " + " | ".join(["---"] * len(columns)) + " |"
    rows = ["| " + " | ".join(map(str, row)) + " |" for row in view.itertuples(index=False, name=None)]
    return "\n".join([headers, rule, *rows])


def write_report(
    path: Path,
    events: pd.DataFrame,
    overview: pd.DataFrame,
    buckets_bps: pd.DataFrame,
    comparison: pd.DataFrame,
    thresholds: pd.DataFrame,
    threshold_stability: pd.DataFrame,
    threshold_annual: pd.DataFrame,
    stability: pd.DataFrame,
    costs: pd.DataFrame,
    args: argparse.Namespace,
) -> None:
    overview_view = overview.copy()
    overview_view["reference_close"] = overview_view["reference_close"].map(
        {"16:00": "16:00 cash", "17:00": "17:00 futures"}
    ).fillna(overview_view["reference_close"])
    overview_table = markdown_table(
        overview_view,
        ["reference_close", "side", "trades", "fill_rate", "fill_ci95_low", "fill_ci95_high",
         "avg_net_pnl_dollars", "avg_net_pnl_ci95_low", "avg_net_pnl_ci95_high",
         "profit_factor", "max_drawdown_dollars"],
        {"fill_rate": ".1%", "fill_ci95_low": ".1%", "fill_ci95_high": ".1%",
         "avg_net_pnl_dollars": ".2f", "avg_net_pnl_ci95_low": ".2f",
         "avg_net_pnl_ci95_high": ".2f", "profit_factor": ".2f",
         "max_drawdown_dollars": ".0f"},
    )

    reliable = buckets_bps[(buckets_bps["side"] != "All") & (buckets_bps["trades"] >= 30)].copy()
    bucket_table = markdown_table(
        reliable,
        ["reference_close", "side", "gap_bucket", "trades", "fill_rate", "avg_net_pnl_dollars"],
        {"fill_rate": ".1%", "avg_net_pnl_dollars": ".2f"},
    ) if not reliable.empty else "No side/bucket combination had at least 30 observations."

    comparisons = markdown_table(
        comparison,
        ["reference_close", "long_fill_rate", "short_fill_rate", "long_minus_short_fill_rate",
         "difference_ci95_low", "difference_ci95_high", "two_sided_p_value"],
        {"long_fill_rate": ".1%", "short_fill_rate": ".1%",
         "long_minus_short_fill_rate": ".1%", "difference_ci95_low": ".1%",
         "difference_ci95_high": ".1%", "two_sided_p_value": ".3f"},
    )

    stability_view = stability[stability["side"] == "All"].copy()
    stability_table = markdown_table(
        stability_view,
        ["reference_close", "sample", "split_ts", "trades", "fill_rate",
         "avg_net_pnl_dollars", "profit_factor"],
        {"fill_rate": ".1%", "avg_net_pnl_dollars": ".2f", "profit_factor": ".2f"},
    )
    cost_view = costs[costs["side"] == "All"].copy()
    cost_table = markdown_table(
        cost_view,
        ["reference_close", "cost_ticks", "avg_net_pnl_dollars", "profit_factor",
         "max_drawdown_dollars"],
        {"cost_ticks": ".0f", "avg_net_pnl_dollars": ".2f", "profit_factor": ".2f",
         "max_drawdown_dollars": ".0f"},
    )

    threshold_view = thresholds[
        (thresholds["side"] != "All")
        & (thresholds["trades"] >= 100)
        & (thresholds["max_gap_bps"].isin([2, 3, 5, 7.5, 10, 15, 25]))
    ].copy()
    threshold_table = markdown_table(
        threshold_view,
        ["reference_close", "side", "max_gap_bps", "trades", "fill_rate",
         "avg_net_pnl_dollars", "avg_net_pnl_ci95_low", "avg_net_pnl_ci95_high",
         "profit_factor", "max_drawdown_dollars"],
        {"max_gap_bps": ".1f", "fill_rate": ".1%", "avg_net_pnl_dollars": ".2f",
         "avg_net_pnl_ci95_low": ".2f", "avg_net_pnl_ci95_high": ".2f",
         "profit_factor": ".2f", "max_drawdown_dollars": ".0f"},
    )

    all_rows = overview[overview["side"] == "All"].set_index("reference_close")
    cash = all_rows.loc["16:00"] if "16:00" in all_rows.index else None
    futures = all_rows.loc["17:00"] if "17:00" in all_rows.index else None
    key_lines = []
    if futures is not None:
        futures_pnl = f"-${abs(futures.avg_net_pnl_dollars):.2f}" if futures.avg_net_pnl_dollars < 0 else f"${futures.avg_net_pnl_dollars:.2f}"
        key_lines.append(
            f"- The 17:00 futures-close level filled {futures.fill_rate:.1%} of non-zero gaps, "
            f"but averaged {futures_pnl} per one-contract event after cost."
        )
    if cash is not None:
        cash_pnl = f"-${abs(cash.avg_net_pnl_dollars):.2f}" if cash.avg_net_pnl_dollars < 0 else f"${cash.avg_net_pnl_dollars:.2f}"
        key_lines.append(
            f"- The 16:00 cash-close level filled {cash.fill_rate:.1%} and averaged "
            f"{cash_pnl} per event after cost."
        )
    key_lines.append(
        "- Fill probability falls materially as the normalized gap grows; the high headline hit rate is concentrated in small gaps."
    )
    key_lines.append(
        "- Rare non-fills can overwhelm many small target wins, so fill rate and trading expectancy must be evaluated separately."
    )
    candidates = thresholds[(thresholds["side"] != "All") & (thresholds["trades"] >= 200)]
    if not candidates.empty:
        best = candidates.loc[candidates["net_pnl_tstat"].idxmax()]
        halves = threshold_stability[
            (threshold_stability["reference_close"] == best.reference_close)
            & (threshold_stability["side"] == best.side)
            & (threshold_stability["max_gap_bps"] == best.max_gap_bps)
        ].set_index("sample")
        half_text = ""
        if {"First half", "Second half"}.issubset(halves.index):
            half_text = (
                "Its first/second-half averages were "
                f"${halves.loc['First half', 'avg_net_pnl_dollars']:.2f} and "
                f"${halves.loc['Second half', 'avg_net_pnl_dollars']:.2f}."
            )
        years = threshold_annual[
            (threshold_annual["reference_close"] == best.reference_close)
            & (threshold_annual["side"] == best.side)
            & (threshold_annual["max_gap_bps"] == best.max_gap_bps)
        ]
        positive_years = int((years["avg_net_pnl_dollars"] > 0).sum())
        annual_text = (
            f" {positive_years} of {len(years)} calendar samples were positive."
            if len(years) else ""
        )
        break_even_ticks = best.avg_gross_pnl_dollars / (TICK_SIZE * DOLLARS_PER_POINT)
        key_lines.append(
            f"- The highest P&L t-stat among the coded cumulative filters with at least 200 events was {best.reference_close} "
            f"{best.side.lower()} with gaps below {best.max_gap_bps:g} bps: "
            f"{best.fill_rate:.1%} fills and ${best.avg_net_pnl_dollars:.2f} average net P&L. "
            f"{half_text}{annual_text} Its in-sample gross edge breaks even near {break_even_ticks:.1f} "
            "ticks of total cost. This is an in-sample selection and needs a fresh out-of-sample test."
        )
    key_findings = "\n".join(key_lines)

    start = events["asia_start_ts"].min()
    end = events["asia_start_ts"].max()
    text = f"""# MNQ New York close -> Asia fill study

## Definition

The test fades the gap from the selected completed New York close to the 18:00 ET Globex reopen. A gap down is a long; a gap up is a short. The target is the selected close and the deadline is 00:00 ET. A 5-minute bar fills when its high/low reaches the target. The fill time is therefore reported as the end of the first touching bar (an upper bound). If the level is not touched, the trade exits at the last Asia bar's close.

Period: {start.date()} through {end.date()}. Cost: {args.cost_ticks:g} MNQ ticks round trip (${args.cost_ticks * TICK_SIZE * DOLLARS_PER_POINT:.2f} per contract). Minimum absolute gap: {args.min_gap_points:g} points. The reference close may be at most {args.max_reference_age_hours:g} hours old, so the default study excludes weekend and holiday reopens. The 16:00 and 17:00 results are alternative definitions, not simultaneous trades.

## Key read

{key_findings}

## Overall results

{overview_table}

Profit factor and P&L assume one MNQ contract per event. A target fill can still be a small net loss when the gap is smaller than the round-trip cost.

## Long versus short fill rates

Positive differences favor longs. The interval and p-value are unadjusted exploratory statistics.

{comparisons}

## Fill probability by normalized gap size

The following table only shows side/bucket cells with at least 30 events. BPS buckets make early and late MNQ price levels comparable. See the CSVs for all buckets and point-size buckets.

{bucket_table}

## Cumulative maximum-gap filters

These rows answer the trade-selection question "what if I only take gaps smaller than this threshold?" The filters overlap, so the table is exploratory rather than a set of independent tests.

{threshold_table}

## Split-sample stability

{stability_table}

## Cost sensitivity

{cost_table}

## Important limitations

- The source is an unadjusted Databento continuous front-month series. Default same-day close filtering avoids weekend/stale-close distortions, but the data does not expose contract identifiers here, so an occasional roll switch at 18:00 cannot be proven or removed.
- A bar touch is not a guaranteed live fill at the exact level, and the cost input is a simple round-trip deduction. Commissions, queue position, and slippage beyond that input are not modeled.
- The fixed Asia deadline is 00:00 ET. Extending Asia to another clock changes both fill rates and non-fill P&L.
- Bucket results are exploratory. Small samples and multiple comparisons can make individual buckets look stronger than they are.
"""
    path.write_text(text, encoding="utf-8")


def print_overview(overview: pd.DataFrame, comparison: pd.DataFrame) -> None:
    print("\nMNQ NEW YORK CLOSE -> ASIA FILL (18:00-00:00 ET)")
    print("=" * 99)
    print(f"{'close':<8}{'side':<7}{'n':>6}{'fill':>9}{'95% CI':>18}{'avg net $':>12}"
          f"{'PF':>8}{'max DD $':>12}{'med fill':>11}")
    for row in overview.itertuples(index=False):
        interval = f"{row.fill_ci95_low:.1%}-{row.fill_ci95_high:.1%}"
        minutes = "n/a" if pd.isna(row.median_fill_minutes) else f"{row.median_fill_minutes:.0f}m"
        print(f"{row.reference_close:<8}{row.side:<7}{row.trades:>6}{row.fill_rate:>9.1%}"
              f"{interval:>18}{row.avg_net_pnl_dollars:>12.2f}{row.profit_factor:>8.2f}"
              f"{row.max_drawdown_dollars:>12.0f}{minutes:>11}")
    print("\nLONG - SHORT FILL-RATE DIFFERENCE")
    for row in comparison.itertuples(index=False):
        print(f"  {row.reference_close}: {row.long_minus_short_fill_rate:+.1%} "
              f"(95% CI {row.difference_ci95_low:+.1%} to {row.difference_ci95_high:+.1%}, "
              f"p={row.two_sided_p_value:.3f})")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--close-times", default="16:00,17:00",
                        help="comma-separated completed NY close definitions")
    parser.add_argument("--asia-start", default="18:00")
    parser.add_argument("--asia-end", default="00:00")
    parser.add_argument("--max-reference-age-hours", type=float, default=4.0,
                        help="default excludes weekend and holiday reopens")
    parser.add_argument("--min-asia-bars", type=int, default=60,
                        help="minimum bars required out of 72 expected 5-minute bars")
    parser.add_argument("--min-gap-points", type=float, default=TICK_SIZE)
    parser.add_argument("--cost-ticks", type=float, default=1.0,
                        help="total round-trip trading cost in MNQ ticks")
    parser.add_argument("--point-bins", default=DEFAULT_POINT_BINS)
    parser.add_argument("--bps-bins", default=DEFAULT_BPS_BINS)
    return parser


def main() -> None:
    parser = make_parser()
    args = parser.parse_args()
    try:
        close_times = [value.strip() for value in args.close_times.split(",") if value.strip()]
        if not close_times:
            parser.error("--close-times cannot be empty")
        for value in [*close_times, args.asia_start, args.asia_end]:
            parse_clock(value)
        point_bins = parse_bins(args.point_bins)
        bps_bins = parse_bins(args.bps_bins)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if args.max_reference_age_hours <= 0:
        parser.error("--max-reference-age-hours must be positive")
    if args.min_asia_bars <= 0 or args.min_gap_points < 0 or args.cost_ticks < 0:
        parser.error("bar count, gap, and cost inputs must be non-negative")

    bars, bar_delta = load_bars(args.data)
    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end) if args.end else None
    if start.tzinfo is None:
        start = start.tz_localize(bars.index.tz)
    else:
        start = start.tz_convert(bars.index.tz)
    if end is not None:
        if end.tzinfo is None:
            end = end.tz_localize(bars.index.tz)
        else:
            end = end.tz_convert(bars.index.tz)

    pieces = []
    for close_time in close_times:
        events = build_events(
            bars=bars,
            close_time=close_time,
            asia_start=args.asia_start,
            asia_end=args.asia_end,
            bar_delta=bar_delta,
            max_reference_age_hours=args.max_reference_age_hours,
            min_asia_bars=args.min_asia_bars,
            min_gap_points=args.min_gap_points,
            cost_ticks=args.cost_ticks,
        )
        events = events[events["asia_start_ts"] >= start]
        if end is not None:
            # An end date includes that calendar day's Asia start.
            events = events[events["asia_start_ts"] < end + pd.DateOffset(days=1)]
        pieces.append(events)
    events = pd.concat(pieces, ignore_index=True).sort_values(
        ["reference_close", "asia_start_ts"]
    ).reset_index(drop=True)
    if events.empty:
        parser.error("no eligible events in the requested range")

    overview = grouped_summary(add_all_sides(events), ["reference_close", "side"])
    side_order = pd.Categorical(overview["side"], categories=["All", "Long", "Short"], ordered=True)
    overview = overview.assign(_side_order=side_order).sort_values(
        ["reference_close", "_side_order"]
    ).drop(columns="_side_order").reset_index(drop=True)
    points = bucket_summary(events, "gap_points", point_bins, "points")
    bps = bucket_summary(events, "gap_bps", bps_bins, "bps")
    thresholds = threshold_summary(events)
    threshold_stability = threshold_stability_summary(events)
    threshold_annual = threshold_annual_summary(events)
    comparison = side_comparison(events)
    stability = stability_summary(events)
    annual = annual_summary(events)
    costs = cost_sensitivity(events)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    events.to_csv(args.out_dir / "events.csv", index=False)
    overview.to_csv(args.out_dir / "overview.csv", index=False)
    points.to_csv(args.out_dir / "gap_buckets_points.csv", index=False)
    bps.to_csv(args.out_dir / "gap_buckets_bps.csv", index=False)
    thresholds.to_csv(args.out_dir / "gap_max_thresholds_bps.csv", index=False)
    threshold_stability.to_csv(
        args.out_dir / "gap_max_thresholds_stability.csv", index=False
    )
    threshold_annual.to_csv(
        args.out_dir / "gap_max_thresholds_annual.csv", index=False
    )
    comparison.to_csv(args.out_dir / "long_short_comparison.csv", index=False)
    stability.to_csv(args.out_dir / "sample_stability.csv", index=False)
    annual.to_csv(args.out_dir / "annual.csv", index=False)
    costs.to_csv(args.out_dir / "cost_sensitivity.csv", index=False)
    write_report(
        args.out_dir / "report.md", events, overview, bps, comparison, thresholds,
        threshold_stability, threshold_annual, stability, costs, args,
    )

    print_overview(overview, comparison)
    print(f"\nPeriod: {events['asia_start_ts'].min().date()} -> {events['asia_start_ts'].max().date()} | "
          f"bar={bar_delta} | cost={args.cost_ticks:g} tick RT")
    print(f"Outputs: {args.out_dir}")


if __name__ == "__main__":
    main()
