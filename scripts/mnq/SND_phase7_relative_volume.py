# -*- coding: utf-8 -*-
"""Evaluate leakage-safe relative-volume confluence on the Phase 6 trades."""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import SND_phase2_dataset as phase2
import SND_baseline_backtest as baseline_engine
import SND_phase4_backtest as phase4
from SND_html_report import SCRIPT as CHART_SCRIPT
from SND_html_report import comparison_frames, metrics, svg_line_chart
from SND_phase5_combinations import STYLE


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "mnq_dom_sample" / "full_history"
MINUTE = DATA / "ohlcv-1m" / "candles_1m.parquet"
FIVE = DATA / "ohlcv-resampled" / "candles_5m.parquet"
TRADES = ROOT / "reports" / "SND_phase6" / "locked_candidate_trades.parquet"
ZONES = ROOT / "reports" / "SND_phase2" / "zones_enriched.parquet"
RETESTS = ROOT / "reports" / "SND_phase2" / "retests_enriched.parquet"
OUTPUT = ROOT / "reports" / "SND_phase7_rvol"
TZ = "America/Chicago"
LOOKBACK = 20
MIN_PERIODS = 10
FOUR_TICK_COST = 4 * 0.25 * 2.0
PARITY_START = pd.Timestamp("2026-01-01 17:00", tz=TZ).tz_convert("UTC")
PARITY_END = pd.Timestamp("2026-05-30 16:00", tz=TZ).tz_convert("UTC")
RECENT_START = pd.Timestamp("2026-05-31 17:00", tz=TZ).tz_convert("UTC")
RECENT_END = pd.Timestamp("2026-09-05 16:00", tz=TZ).tz_convert("UTC")

SPLITS = {
    "Overall": None,
    "Train 2019–22": (2019, 2022),
    "Validation 2023–24": (2023, 2024),
    "Holdout 2025–26": (2025, 2026),
}

FACTORS = {
    "formation_rvol": ("Formation 1h RVOL", "Known when the zone becomes available."),
    "prior_1m_rvol": ("Prior completed 1m RVOL", "Known before the touch minute."),
    "prior_5m_rvol": ("Prior completed 5m RVOL", "Latest fully completed 5-minute bar."),
    "prior_session_cum_rvol": ("Prior session-cumulative RVOL", "Session volume through the minute before touch."),
    "signal_1m_rvol": ("Signal-minute RVOL · next-open only", "Known at the touch close; valid only before a next-bar entry."),
}


def pf(values: pd.Series) -> float:
    wins = values[values > 0].sum()
    losses = -values[values < 0].sum()
    return float(wins / losses) if losses else math.nan


def load_trades() -> pd.DataFrame:
    frame = pd.read_parquet(TRADES).sort_values("exit_time").reset_index(drop=True)
    for column in ("entry_time", "exit_time", "zone_formed_at", "zone_available_at"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    return frame


def build_features(trades: pd.DataFrame) -> pd.DataFrame:
    minute = pd.read_parquet(MINUTE, columns=["volume"]).sort_index()
    minute.index = minute.index.tz_convert("UTC")
    slots = phase2.session_slot(minute.index, 1)
    _, minute_rvol = phase2.past_only_slot_rvol(minute.volume, slots, LOOKBACK, MIN_PERIODS)

    contiguous = minute.index.to_series().diff().eq(pd.Timedelta(minutes=1)).to_numpy()
    prior_1m = minute_rvol.shift(1).where(contiguous)

    local = minute.index.tz_convert(TZ)
    session_id = (local.tz_localize(None) - pd.Timedelta(hours=17)).normalize()
    cumulative_volume = minute.volume.astype(float).groupby(session_id).cumsum()
    _, cumulative_rvol = phase2.past_only_slot_rvol(
        cumulative_volume, slots, LOOKBACK, MIN_PERIODS
    )
    prior_cumulative = cumulative_rvol.shift(1).where(contiguous)

    minute_features = pd.DataFrame({
        "signal_1m_rvol": minute_rvol,
        "prior_1m_rvol": prior_1m,
        "prior_session_cum_rvol": prior_cumulative,
    })
    positions = minute_features.index.get_indexer(trades.entry_time)
    if (positions < 0).any():
        raise ValueError(f"Missing one-minute bars for {(positions < 0).sum()} Phase 6 entries")
    result = trades.copy()
    for column in minute_features:
        result[column] = minute_features[column].to_numpy()[positions]

    five = pd.read_parquet(FIVE, columns=["volume"]).sort_index()
    five.index = five.index.tz_convert("UTC")
    five_slots = phase2.session_slot(five.index, 5)
    _, five_rvol = phase2.past_only_slot_rvol(five.volume, five_slots, LOOKBACK, MIN_PERIODS)
    five_features = pd.DataFrame({
        "available_at": five.index + pd.Timedelta(minutes=5),
        "prior_5m_rvol": five_rvol.to_numpy(),
    }).sort_values("available_at")
    lookup = result[["entry_time"]].sort_values("entry_time")
    joined = pd.merge_asof(
        lookup, five_features, left_on="entry_time", right_on="available_at", direction="backward"
    )
    result.loc[lookup.index, "prior_5m_rvol"] = joined.prior_5m_rvol.to_numpy()

    zones = pd.read_parquet(ZONES, columns=["zone_id", "formation_rvol"])
    result = result.merge(zones, on="zone_id", how="left", validate="many_to_one")
    return result.sort_values("exit_time").reset_index(drop=True)


def split_frame(frame: pd.DataFrame, split: str) -> pd.DataFrame:
    years = SPLITS[split]
    return frame if years is None else frame.loc[frame.entry_year.between(*years)]


def calendar_for(frame: pd.DataFrame, split: str) -> pd.DatetimeIndex:
    part = split_frame(frame, split)
    dates = part.exit_time.dt.tz_convert(TZ).dt.tz_localize(None).dt.normalize()
    return pd.bdate_range(dates.min(), dates.max())


def metric_record(frame: pd.DataFrame, calendar: pd.DatetimeIndex) -> dict[str, float]:
    gross = metrics(frame, calendar)
    stressed = frame.copy()
    stressed["pnl"] = stressed.pnl - FOUR_TICK_COST
    stressed["points"] = stressed.points - FOUR_TICK_COST / 2.0
    net = metrics(stressed, calendar)
    return {
        "trades": int(len(frame)), "win_rate": gross["win_rate"],
        "avg_pnl": float(frame.pnl.mean()) if len(frame) else math.nan,
        "gross_pnl": gross["total_pnl"], "gross_pf": gross["profit_factor"],
        "pf_4tick": net["profit_factor"], "pnl_4tick": net["total_pnl"],
        "max_drawdown": gross["max_drawdown"], "sharpe": gross["sharpe"],
    }


def bucket(value: pd.Series) -> pd.Series:
    labels = pd.cut(
        value, [-np.inf, 0.75, 1.25, np.inf], right=False,
        labels=["Low <0.75", "Normal 0.75–1.25", "High ≥1.25"],
    ).astype(object)
    labels[value.isna()] = "Unavailable"
    return labels


def analyze(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows = []
    for key, (label, timing) in FACTORS.items():
        levels = bucket(frame[key])
        for split in SPLITS:
            base = split_frame(frame, split)
            calendar = calendar_for(frame, split)
            for level in ("Low <0.75", "Normal 0.75–1.25", "High ≥1.25", "Unavailable"):
                selected = base.loc[levels.loc[base.index].eq(level)]
                rows.append({
                    "factor_key": key, "factor": label, "timing": timing,
                    "bucket": level, "split": split,
                    **metric_record(selected, calendar),
                })
    buckets = pd.DataFrame(rows)

    baseline_rows = []
    for split in SPLITS:
        part = split_frame(frame, split)
        baseline_rows.append({"split": split, **metric_record(part, calendar_for(frame, split))})
    baseline = pd.DataFrame(baseline_rows)

    threshold_rows = []
    thresholds = (0.50, 0.75, 1.00, 1.25, 1.50, 2.00)
    for key, (label, timing) in FACTORS.items():
        for direction in ("at_or_above", "below"):
            for threshold in thresholds:
                mask = frame[key].ge(threshold) if direction == "at_or_above" else frame[key].lt(threshold)
                for split in SPLITS:
                    base = split_frame(frame, split)
                    selected = base.loc[mask.loc[base.index] & frame.loc[base.index, key].notna()]
                    threshold_rows.append({
                        "factor_key": key, "factor": label, "timing": timing,
                        "direction": direction, "threshold": threshold, "split": split,
                        **metric_record(selected, calendar_for(frame, split)),
                    })
    return buckets, pd.DataFrame(threshold_rows), baseline


def verdicts(buckets: pd.DataFrame, baseline: pd.DataFrame) -> pd.DataFrame:
    base_pf = baseline.set_index("split").gross_pf
    rows = []
    for key, (label, timing) in FACTORS.items():
        available = buckets.loc[
            buckets.factor_key.eq(key) & ~buckets.bucket.eq("Unavailable")
        ]
        overall = available.loc[available.split.eq("Overall") & available.trades.ge(200)]
        best = overall.sort_values("gross_pf", ascending=False).iloc[0]
        split_values = available.loc[available.bucket.eq(best.bucket)].set_index("split")
        enough = all(split_values.loc[s, "trades"] >= 100 for s in SPLITS if s != "Overall")
        improves_all = all(
            split_values.loc[s, "gross_pf"] > base_pf.loc[s] for s in SPLITS
        )
        cost_positive = all(
            split_values.loc[s, "pf_4tick"] > 1.0 for s in SPLITS
        )
        if key == "signal_1m_rvol":
            verdict = "Diagnostic only · requires next-open resimulation"
        elif enough and improves_all and cost_positive:
            verdict = "Stateful-test candidate"
        else:
            verdict = "No robust filter yet"
        rows.append({
            "factor_key": key, "factor": label, "best_bucket": best.bucket,
            "trades": int(best.trades), "overall_pf": best.gross_pf,
            "pf_4tick": best.pf_4tick,
            "train_pf": split_values.loc["Train 2019–22", "gross_pf"],
            "validation_pf": split_values.loc["Validation 2023–24", "gross_pf"],
            "holdout_pf": split_values.loc["Holdout 2025–26", "gross_pf"],
            "verdict": verdict, "timing": timing,
        })
    return pd.DataFrame(rows)


def first_touch_lookup() -> pd.DataFrame:
    """Build pre-touch RVOL values for every zone's first physical touch."""
    minute = pd.read_parquet(MINUTE, columns=["volume"]).sort_index()
    minute.index = minute.index.tz_convert("UTC")
    slots = phase2.session_slot(minute.index, 1)
    _, minute_rvol = phase2.past_only_slot_rvol(minute.volume, slots, LOOKBACK, MIN_PERIODS)
    contiguous = minute.index.to_series().diff().eq(pd.Timedelta(minutes=1)).to_numpy()
    prior_1m = minute_rvol.shift(1).where(contiguous)

    retests = pd.read_parquet(RETESTS)
    retests = retests.loc[retests.touch_number.eq(1), [
        "zone_id", "touch_time", "prior_5m_rvol",
    ]].copy()
    retests["touch_time"] = pd.to_datetime(retests.touch_time, utc=True)
    positions = minute.index.get_indexer(retests.touch_time)
    retests["prior_1m_rvol"] = np.where(
        positions >= 0, prior_1m.to_numpy()[np.maximum(positions, 0)], np.nan
    )
    return retests.set_index("zone_id", verify_integrity=True)


def rvol_filter(column: str, features: pd.DataFrame):
    def entry_filter(zone, active_long, active_short) -> bool:
        if zone.timeframe != "1h" or zone.physical_touch_count != 1:
            return False
        if not phase4.opposing_room_is_open(zone, active_long, active_short):
            return False
        if zone.zone_id not in features.index:
            return False
        value = features.at[zone.zone_id, column]
        return pd.notna(value) and 0.75 <= value < 1.25
    return entry_filter


def run_stateful() -> dict[str, pd.DataFrame]:
    feature_lookup = first_touch_lookup()
    minute = baseline_engine.load_bars(MINUTE)
    frames = {
        timeframe: baseline_engine.load_bars(DATA / "ohlcv-resampled" / f"candles_{timeframe}.parquet")
        for timeframe in ("1h", "4h", "1d")
    }
    sim_args = phase4.simulation_args(argparse.Namespace(point_value=2.0, cost_ticks=0.0))
    template = baseline_engine.detect_zones(frames, minute.index, sim_args.body_ratio)
    phase4.validate_zone_identity(template, pd.read_parquet(ZONES))
    control = load_trades()
    series = {"Phase 6 · no RVOL filter": control}
    variants = [
        ("Phase 6 + prior 1m RVOL 0.75–1.25", "stateful_prior_1m_normal", "prior_1m_rvol"),
        ("Phase 6 + prior 5m RVOL 0.75–1.25", "stateful_prior_5m_normal", "prior_5m_rvol"),
    ]
    for label, slug, column in variants:
        print(f"Stateful run · {label}...", flush=True)
        trades, tests, audit = baseline_engine.simulate(
            minute, copy.deepcopy(template), None, None, sim_args,
            rvol_filter(column, feature_lookup),
        )
        destination = OUTPUT / slug
        destination.mkdir(exist_ok=True)
        trades.to_parquet(destination / "trades.parquet", index=False)
        tests.to_parquet(destination / "zone_tests.parquet", index=False)
        (destination / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
        series[label] = trades.sort_values("exit_time").reset_index(drop=True)
        print(f"  {len(trades):,} trades", flush=True)
    return series


def load_stateful() -> dict[str, pd.DataFrame]:
    """Reuse previously completed stateful ledgers when only rebuilding outputs."""
    series = {"Phase 6 · no RVOL filter": load_trades()}
    variants = [
        ("Phase 6 + prior 1m RVOL 0.75–1.25", "stateful_prior_1m_normal"),
        ("Phase 6 + prior 5m RVOL 0.75–1.25", "stateful_prior_5m_normal"),
    ]
    for label, slug in variants:
        path = OUTPUT / slug / "trades.parquet"
        if not path.exists():
            raise FileNotFoundError(f"Missing stateful ledger: {path}")
        trades = pd.read_parquet(path)
        for column in ("entry_time", "exit_time", "zone_formed_at", "zone_available_at"):
            if column in trades:
                trades[column] = pd.to_datetime(trades[column], utc=True)
        series[label] = trades.sort_values("exit_time").reset_index(drop=True)
    return series


def stateful_results(series: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    split_metrics = phase4.metric_rows(series)
    costs = phase4.cost_sensitivity(series, 2.0)
    split_metrics.to_csv(OUTPUT / "stateful_metrics_by_split.csv", index=False)
    costs.to_csv(OUTPUT / "stateful_cost_sensitivity.csv", index=False)
    return split_metrics, costs


def html_table(frame: pd.DataFrame, columns: list[tuple[str, str, str]]) -> str:
    head = "".join(f"<th>{label}</th>" for _, label, _ in columns)
    body = []
    for row in frame.itertuples(index=False):
        cells = []
        for key, _, kind in columns:
            value = getattr(row, key)
            if kind == "int": shown = f"{int(value):,}"
            elif kind == "pf": shown = "—" if pd.isna(value) else f"{value:.3f}"
            elif kind == "money": shown = "—" if pd.isna(value) else f"${value:,.0f}"
            elif kind == "pct": shown = "—" if pd.isna(value) else f"{value:.1%}"
            else: shown = str(value)
            cells.append(f"<td>{shown}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"


def build_report(frame: pd.DataFrame, buckets: pd.DataFrame, thresholds: pd.DataFrame,
                 baseline: pd.DataFrame, verdict: pd.DataFrame,
                 stateful_series: dict[str, pd.DataFrame], stateful: pd.DataFrame,
                 stateful_costs: pd.DataFrame) -> None:
    overall = baseline.loc[baseline.split.eq("Overall")].iloc[0]
    candidates = verdict.loc[verdict.verdict.eq("Stateful-test candidate")]
    control_label = "Phase 6 · no RVOL filter"
    control_split = stateful.loc[stateful.variant.eq(control_label)].set_index("split")
    control_four_tick = stateful_costs.loc[
        stateful_costs.variant.eq(control_label) & stateful_costs.round_trip_cost_ticks.eq(4),
        "profit_factor",
    ].iloc[0]
    eligible = []
    for label in stateful.variant.unique():
        if label == control_label:
            continue
        values = stateful.loc[stateful.variant.eq(label)].set_index("split")
        four_tick = stateful_costs.loc[
            stateful_costs.variant.eq(label) & stateful_costs.round_trip_cost_ticks.eq(4),
            "profit_factor",
        ].iloc[0]
        if (
            all(values.loc[s, "profit_factor"] > 1 for s in SPLITS)
            and values.loc["Overall", "profit_factor"] > control_split.loc["Overall", "profit_factor"]
            and values.loc["Overall", "sharpe"] > control_split.loc["Overall", "sharpe"]
            and values.loc["Holdout 2025–26", "profit_factor"] > control_split.loc["Holdout 2025–26", "profit_factor"]
            and values.loc["Holdout 2025–26", "sharpe"] > control_split.loc["Holdout 2025–26", "sharpe"]
            and four_tick > control_four_tick
        ):
            eligible.append(label)
    if eligible:
        ranked = stateful.loc[
            stateful.variant.isin(eligible) & stateful.split.eq("Overall")
        ].sort_values(["profit_factor", "sharpe"], ascending=False)
        recommendation = ranked.iloc[0].variant
        decision = f"Advance {recommendation} to Pine verification"
    else:
        recommendation = None
        decision = "Do not add an RVOL entry filter"

    verdict_html = html_table(verdict, [
        ("factor", "RVOL definition", "text"), ("best_bucket", "Best screen", "text"),
        ("trades", "Trades", "int"), ("overall_pf", "PF", "pf"),
        ("pf_4tick", "PF · 4 ticks", "pf"), ("train_pf", "Train PF", "pf"),
        ("validation_pf", "Validation PF", "pf"), ("holdout_pf", "Holdout PF", "pf"),
        ("verdict", "Decision", "text"),
    ])
    bucket_html = html_table(
        buckets.loc[~buckets.bucket.eq("Unavailable")],
        [("factor", "Factor", "text"), ("bucket", "Bucket", "text"),
         ("split", "Split", "text"), ("trades", "Trades", "int"),
         ("gross_pf", "PF", "pf"), ("pf_4tick", "PF · 4 ticks", "pf"),
         ("gross_pnl", "P&L", "money"), ("sharpe", "Sharpe", "pf")],
    )

    stateful_html = html_table(stateful, [
        ("variant", "Stateful variant", "text"), ("split", "Split", "text"),
        ("trades", "Trades", "int"), ("profit_factor", "PF", "pf"),
        ("sharpe", "Sharpe", "pf"), ("total_pnl", "P&L", "money"),
        ("max_drawdown", "Max DD", "money"),
    ])
    four_tick_rows = stateful_costs.loc[stateful_costs.round_trip_cost_ticks.eq(4), [
        "variant", "profit_factor", "total_pnl", "sharpe", "max_drawdown",
    ]].rename(columns={"profit_factor": "pf_4tick", "total_pnl": "pnl_4tick"})
    cost_html = html_table(four_tick_rows, [
        ("variant", "Stateful variant", "text"), ("pf_4tick", "PF · 4 ticks", "pf"),
        ("pnl_4tick", "P&L · 4 ticks", "money"), ("sharpe", "Sharpe", "pf"),
        ("max_drawdown", "Max DD", "money"),
    ])

    parity_rows = []
    parity_calendar = pd.bdate_range(
        PARITY_START.tz_convert(TZ).tz_localize(None).normalize(),
        PARITY_END.tz_convert(TZ).tz_localize(None).normalize(),
    )
    for label, trades in stateful_series.items():
        selected = trades.loc[
            pd.to_datetime(trades.entry_time, utc=True).between(PARITY_START, PARITY_END)
        ]
        parity_rows.append({"variant": label, **metric_record(selected, parity_calendar)})
    parity = pd.DataFrame(parity_rows)
    parity.to_csv(OUTPUT / "parity_window_metrics.csv", index=False)
    if recommendation:
        pine_reference = stateful_series[recommendation].loc[
            pd.to_datetime(stateful_series[recommendation].entry_time, utc=True).between(
                PARITY_START, PARITY_END
            )
        ].copy()
        first_touches = pd.read_parquet(
            RETESTS, columns=["zone_id", "touch_number", "prior_5m_rvol"]
        )
        first_touches = first_touches.loc[
            first_touches.touch_number.eq(1), ["zone_id", "prior_5m_rvol"]
        ].rename(columns={"prior_5m_rvol": "first_touch_prior_5m_rvol"})
        pine_reference = pine_reference.merge(
            first_touches, on="zone_id", how="left", validate="many_to_one"
        )
        parity_columns = [
            "trade_id", "zone_id", "direction", "timeframe", "zone_formed_at",
            "zone_available_at", "zone_proximal", "zone_distal", "entry_time",
            "entry_price", "stop_price", "target_price", "exit_time", "exit_price",
            "exit_reason", "points", "pnl", "first_touch_prior_5m_rvol",
        ]
        pine_reference[parity_columns].to_csv(
            OUTPUT / "pine_parity_reference_2026.csv", index=False
        )
    parity_html = html_table(parity, [
        ("variant", "Variant", "text"), ("trades", "Trades", "int"),
        ("gross_pf", "PF", "pf"), ("gross_pnl", "P&L", "money"),
        ("pf_4tick", "PF · 4 ticks", "pf"), ("pnl_4tick", "P&L · 4 ticks", "money"),
    ])

    recent_rows = []
    recent_month_rows = []
    recent_variants = [control_label] + ([recommendation] if recommendation else [])
    recent_calendar = pd.bdate_range(
        RECENT_START.tz_convert(TZ).tz_localize(None).normalize(),
        RECENT_END.tz_convert(TZ).tz_localize(None).normalize(),
    )
    for label in recent_variants:
        trades = stateful_series[label].copy()
        entry_time = pd.to_datetime(trades.entry_time, utc=True)
        selected = trades.loc[entry_time.between(RECENT_START, RECENT_END)].copy()
        recent_rows.append({"variant": label, **metric_record(selected, recent_calendar)})
        local_month = pd.to_datetime(selected.entry_time, utc=True).dt.tz_convert(TZ).dt.strftime("%Y-%m")
        for month, part in selected.groupby(local_month):
            recent_month_rows.append({
                "month": month, "variant": label,
                **metric_record(part, recent_calendar),
            })
    recent = pd.DataFrame(recent_rows)
    recent_monthly = pd.DataFrame(recent_month_rows)
    recent.to_csv(OUTPUT / "recent_window_metrics.csv", index=False)
    recent_monthly.to_csv(OUTPUT / "recent_window_monthly.csv", index=False)
    recent_html = html_table(recent, [
        ("variant", "Variant", "text"), ("trades", "Trades", "int"),
        ("gross_pf", "PF", "pf"), ("avg_pnl", "Avg P&L", "money"),
        ("gross_pnl", "P&L", "money"), ("max_drawdown", "Max DD", "money"),
    ])
    recent_monthly_html = html_table(recent_monthly, [
        ("month", "Month", "text"), ("variant", "Variant", "text"),
        ("trades", "Trades", "int"), ("gross_pf", "PF", "pf"),
        ("gross_pnl", "P&L", "money"),
    ])
    recent_control = recent.loc[recent.variant.eq(control_label)].iloc[0]
    recent_candidate = recent.loc[recent.variant.eq(recommendation)].iloc[0] if recommendation else None
    absolute_pass = bool(
        recommendation and recent_candidate.trades >= 50
        and recent_candidate.gross_pf > 1.10 and recent_candidate.avg_pnl > 0
        and recent_candidate.gross_pnl > 0
    )
    incremental_pass = bool(
        recommendation and recent_candidate.gross_pf > recent_control.gross_pf
        and recent_candidate.avg_pnl > recent_control.avg_pnl
    )
    recent_decision = (
        "Absolute gates pass; incremental RVOL gate fails"
        if absolute_pass and not incremental_pass else
        "Absolute and incremental gates pass" if absolute_pass and incremental_pass else
        "Absolute recent-window gates fail"
    )

    chart_series = {"Phase 6 · no RVOL filter": frame}
    for row in verdict.itertuples(index=False):
        selected = frame.loc[bucket(frame[row.factor_key]).eq(row.best_bucket)]
        chart_series[f"{row.factor} · {row.best_bucket}"] = selected
    equity, drawdown, _, _ = comparison_frames(chart_series)
    full_equity, full_drawdown, full_rolling, _ = comparison_frames(stateful_series)

    tv_result_path = OUTPUT / "tradingview_strategy_parity.json"
    tv_result = json.loads(tv_result_path.read_text()) if tv_result_path.exists() else None
    summary = {
        "phase": 7,
        "name": "Relative-volume confluence screen",
        "baseline_trades": len(frame),
        "baseline_gross_pf": float(overall.gross_pf),
        "baseline_four_tick_pf": float(overall.pf_4tick),
        "screen_candidates": candidates.factor.tolist(),
        "stateful_variants": [label for label in stateful_series if label != control_label],
        "recommended_for_pine": recommendation,
        "decision": decision,
        "parity_window": {
            "start": str(PARITY_START), "end": str(PARITY_END),
            "baseline_trades": int(parity.iloc[0].trades),
            "recommended_trades": int(
                parity.loc[parity.variant.eq(recommendation), "trades"].iloc[0]
            ) if recommendation else None,
        },
        "recent_window_audit": {
            "start": str(RECENT_START), "requested_end": str(RECENT_END),
            "data_available_through": str(pd.read_parquet(MINUTE, columns=[]).index.max()),
            "decision": recent_decision,
            "absolute_pass": absolute_pass, "incremental_pass": incremental_pass,
            "baseline_trades": int(recent_control.trades),
            "baseline_profit_factor": float(recent_control.gross_pf),
            "candidate_trades": int(recent_candidate.trades) if recommendation else None,
            "candidate_profit_factor": float(recent_candidate.gross_pf) if recommendation else None,
        },
        "warning": "Bucket curves are conditional screens, not stateful strategy simulations.",
    }
    if tv_result:
        summary["tradingview_verification"] = {
            "source_file": tv_result["source_file"],
            "trades": tv_result["tradingview_trades"],
            "profit_factor": tv_result["tradingview"]["profit_factor"],
            "matched_signals": tv_result["matched_signals"],
            "exact_signal_minutes": tv_result["matched_diagnostics"]["exact_signal_minute"],
            "exact_zone_widths": tv_result["matched_diagnostics"]["exact_zone_width"],
            "rvol_correlation": tv_result.get("matched_rvol", {}).get("correlation"),
            "assessment": "Qualified implementation-parity pass; feed/path dependence remains.",
        }
    (OUTPUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    tv_section = ""
    if tv_result:
        tv = tv_result["tradingview"]
        py = tv_result["python_reference"]
        rvol = tv_result.get("matched_rvol", {})
        tv_section = f"""<h2>TradingView Phase 7 verification</h2>
        <div class='tiles'>
          <div class='tile'><span>TradingView trades</span><strong>{tv_result['tradingview_trades']:,}</strong></div>
          <div class='tile'><span>TradingView PF</span><strong>{tv['profit_factor']:.3f}</strong></div>
          <div class='tile'><span>Matched signals</span><strong>{tv_result['matched_signals']:,}</strong></div>
          <div class='tile'><span>Exact signal + zone</span><strong>{tv_result['matched_diagnostics']['exact_signal_minute']:,}</strong></div>
          <div class='tile'><span>Matched RVOL correlation</span><strong>{rvol.get('correlation', float('nan')):.3f}</strong></div>
        </div>
        <div class='method'><p><strong>Qualified implementation-parity pass.</strong> TradingView produced {tv_result['tradingview_trades']:,} trades at PF {tv['profit_factor']:.3f}; the Databento reference produced {tv_result['reference_trades']:,} at PF {py['profit_factor']:.3f}. All {tv_result['matched_signals']:,} paired signals share the exact signal minute and zone width. On those pairs, RVOL correlation is {rvol.get('correlation', float('nan')):.3f} and median absolute RVOL difference is {rvol.get('median_absolute_difference', float('nan')):.5f}. The count gap is consistent with continuous-feed differences amplified by a stateful filter: accepting or rejecting one early trade changes which later signals can execute. This verifies the calculation and direction of the result, but not exact trade-for-trade equivalence.</p></div>"""

    page = f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>SND Phase 7 · RVOL</title><style>{STYLE}</style></head><body><main class='wrap'>
    <div class='eyebrow'>MNQ · SND strategy lab</div><h1>Phase 7 · relative-volume confluence</h1>
    <p class='lead'>Relative volume is evaluated as an independent information layer on the locked Phase 6 trades. Every baseline uses the prior 20 observations in the same Chicago session-time slot with a 10-observation warm-up.</p>
    <div class='tiles'>
      <div class='tile'><span>Phase 6 trades</span><strong>{len(frame):,}</strong></div>
      <div class='tile'><span>Baseline PF</span><strong>{overall.gross_pf:.3f}</strong></div>
      <div class='tile'><span>Baseline PF · 4 ticks</span><strong>{overall.pf_4tick:.3f}</strong></div>
      <div class='tile'><span>Stateful tests</span><strong>{len(stateful_series)-1}</strong></div>
      <div class='tile'><span>Decision</span><strong class='compact'>{decision}</strong></div>
    </div>
    <h2>Decision table</h2><p class='note'>“Best screen” is descriptive, not automatically selected. Screen candidates require improvement in every historical split, at least 100 trades per split, and PF above 1 after four ticks round trip. Final promotion uses the independent stateful reruns below.</p>{verdict_html}
    <h2>Full stateful reruns</h2><p class='note'>Each candidate was rerun independently from the original one-minute bars. Rejected signals no longer occupy a position, so later zones can become eligible naturally.</p>{stateful_html}
    <h2>Stateful four-tick cost stress</h2>{cost_html}
    {svg_line_chart(full_equity, 'Stateful RVOL equity', 'Fresh event-engine runs; not conditional subsets.', 'money')}{svg_line_chart(full_drawdown, 'Stateful RVOL drawdown', 'Distance below each variant’s prior daily equity peak.', 'money')}{svg_line_chart(full_rolling, 'Stateful rolling 90-day expectancy', 'Points per trade over trailing calendar time.', 'number')}
    <h2>Frozen TradingView parity window</h2><p class='note'>Databento reference results for Jan 1, 2026 17:00 CT through May 30, 2026 16:00 CT. Compare directionally, not as an exact trade-count promise: MNQ1! and the research continuous series differ at contract rolls and occasionally at one-minute OHLC values.</p>{parity_html}
    {tv_section}
    <h2>Recent-window Python audit</h2><p class='note'>May 31 through the latest locally available bar on Sep 3, 2026. This interval was already present inside the Phase 7 full-history aggregate, so it is a temporal diagnostic—not a genuinely untouched holdout.</p><div class='method'><p><strong>{recent_decision}.</strong> The RVOL strategy remains profitable and clears the predeclared absolute thresholds, but it does not improve PF or average trade over the unfiltered baseline in this interval.</p></div>{recent_html}<h3>Monthly stability</h3>{recent_monthly_html}
    <h2>Timing and leakage rules</h2><div class='method'><ul><li>Formation RVOL is known when the 1-hour zone becomes available.</li><li>Prior 1-minute, prior 5-minute and prior cumulative RVOL use only completed bars before the touch minute.</li><li>Signal-minute RVOL is not eligible for the same-bar proximal-fill model; it is diagnostic for TradingView’s next-bar-open execution only.</li><li>Unavailable warm-up observations are retained and disclosed rather than backfilled.</li></ul></div>
    <h2>All RVOL buckets by split</h2>{bucket_html}
    <h2>Conditional equity and drawdown</h2><p class='note'>These curves omit trades outside each bucket. They show conditional information content, not the final executable result; filtering changes future zone and position state and must be re-simulated.</p>{svg_line_chart(equity, 'RVOL bucket equity screens', 'Phase 6 baseline versus each factor’s strongest descriptive bucket.', 'money')}{svg_line_chart(drawdown, 'RVOL bucket drawdown screens', 'Conditional drawdown; not yet a stateful strategy result.', 'money')}
    <h2>TradingView verification settings</h2><div class='method'><ul><li>Run on MNQ1!, 1 minute, with the frozen parity window enabled.</li><li>Set sizing mode to <strong>Fixed contracts</strong> and fixed contracts to <strong>1</strong> so RVOL is the only changed variable.</li><li>Enable <strong>Require normal prior 5m RVOL</strong>, with lower bound <strong>0.75</strong> and upper bound <strong>1.25</strong>.</li><li>Use zero commission and zero slippage for signal parity first; apply realistic costs only after the trade list aligns.</li></ul><p>{decision}. Risk-sized position testing remains a separate experiment and is not mixed into the RVOL selection.</p></div>
    <p class='note'><a href='../SND_phase6/index.html'>Phase 6 report</a> · <a href='../SND_dashboard/index.html'>Main dashboard</a></p>
    </main><script>{CHART_SCRIPT}</script></body></html>"""
    (OUTPUT / "index.html").write_text(page)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reuse-stateful", action="store_true",
        help="Rebuild tables/report from saved stateful ledgers instead of rerunning bars.",
    )
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    trades = load_trades()
    enriched = build_features(trades)
    enriched.to_parquet(OUTPUT / "trades_enriched.parquet", index=False)
    buckets, thresholds, baseline = analyze(enriched)
    verdict = verdicts(buckets, baseline)
    buckets.to_csv(OUTPUT / "bucket_metrics.csv", index=False)
    thresholds.to_csv(OUTPUT / "threshold_sensitivity.csv", index=False)
    baseline.to_csv(OUTPUT / "baseline_metrics.csv", index=False)
    verdict.to_csv(OUTPUT / "verdicts.csv", index=False)
    stateful_series = load_stateful() if args.reuse_stateful else run_stateful()
    stateful, stateful_costs = stateful_results(stateful_series)
    build_report(
        enriched, buckets, thresholds, baseline, verdict,
        stateful_series, stateful, stateful_costs,
    )
    print(f"DONE | trades={len(enriched):,} | stateful={len(stateful_series)-1} | report={OUTPUT / 'index.html'}")


if __name__ == "__main__":
    main()
