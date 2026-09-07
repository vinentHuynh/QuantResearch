"""Screen SND confluence variables one at a time without changing trade mechanics.

Phase 3 is a cohort screen, not a replacement-strategy simulation. It attaches
point-in-time Phase 2 features to the exact Phase 1 trades, then asks how the
already-observed trades behaved when one condition was present. Rejected trades
are treated as "do nothing"; the screen does not invent replacement entries.

Run from the repository root:

    .venv/bin/python scripts/mnq/SND_phase3_screen.py
"""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
import zlib

import numpy as np
import pandas as pd

from SND_html_report import SCRIPT as CHART_SCRIPT
from SND_html_report import comparison_frames, svg_line_chart


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PHASE1 = ROOT / "reports" / "SND_baseline"
DEFAULT_PHASE2 = ROOT / "reports" / "SND_phase2"
DEFAULT_OUTPUT = ROOT / "reports" / "SND_phase3"
TIMEZONE = "America/Chicago"
SPLITS = {
    "Train 2019–22": (2019, 2022),
    "Validation 2023–24": (2023, 2024),
    "Holdout 2025–26": (2025, 2026),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase1-dir", type=Path, default=DEFAULT_PHASE1)
    parser.add_argument("--phase2-dir", type=Path, default=DEFAULT_PHASE2)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bootstrap-samples", type=int, default=2_000)
    return parser.parse_args()


def maximum_drawdown(pnl: pd.Series) -> float:
    equity = pnl.cumsum()
    return float((equity - equity.cummax().clip(lower=0.0)).min()) if len(equity) else 0.0


def month_block_interval(
    frame: pd.DataFrame,
    samples: int,
    seed_label: str,
) -> tuple[float, float]:
    if frame.empty:
        return math.nan, math.nan
    local = frame["entry_time"].dt.tz_convert(TIMEZONE).dt.tz_localize(None)
    monthly = frame.assign(month=local.dt.to_period("M")).groupby("month").agg(
        points=("points", "sum"), trades=("points", "size")
    )
    if len(monthly) < 2:
        return math.nan, math.nan
    rng = np.random.default_rng(zlib.crc32(seed_label.encode("utf-8")))
    positions = rng.integers(0, len(monthly), size=(samples, len(monthly)))
    point_values = monthly["points"].to_numpy(dtype=float)[positions].sum(axis=1)
    trade_values = monthly["trades"].to_numpy(dtype=float)[positions].sum(axis=1)
    expectancy = point_values / trade_values
    return tuple(float(value) for value in np.quantile(expectancy, [0.025, 0.975]))


def evaluation_calendars(frame: pd.DataFrame) -> dict[str, pd.DatetimeIndex]:
    local_dates = frame["exit_time"].dt.tz_convert(TIMEZONE).dt.tz_localize(None).dt.normalize()
    complete = pd.bdate_range(local_dates.min(), local_dates.max())
    calendars = {"Overall": complete}
    for label, (start_year, end_year) in SPLITS.items():
        calendars[label] = complete[(complete.year >= start_year) & (complete.year <= end_year)]
    return calendars


def daily_risk_metrics(
    frame: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> dict[str, float]:
    if not len(calendar):
        return {
            "sharpe": math.nan, "sortino": math.nan, "pnl_calmar": math.nan,
            "annualized_volatility": math.nan, "profitable_months": math.nan,
        }
    if frame.empty:
        daily = pd.Series(0.0, index=calendar)
    else:
        local_dates = frame["exit_time"].dt.tz_convert(TIMEZONE).dt.tz_localize(None).dt.normalize()
        daily = frame.assign(session_date=local_dates).groupby("session_date")["pnl"].sum()
        daily = daily.reindex(calendar, fill_value=0.0).astype(float)
    mean = float(daily.mean())
    volatility = float(daily.std(ddof=1))
    downside = float(np.sqrt(np.mean(np.minimum(daily.to_numpy(), 0.0) ** 2)))
    annualized_pnl = mean * 252.0
    annualized_volatility = volatility * math.sqrt(252.0)
    drawdown = abs(maximum_drawdown(daily))
    monthly = daily.resample("ME").sum()
    return {
        "sharpe": mean / volatility * math.sqrt(252.0) if volatility > 0 else math.nan,
        "sortino": mean / downside * math.sqrt(252.0) if downside > 0 else math.nan,
        # With a fixed contract count, capital scales out of this additive-P&L analogue.
        "pnl_calmar": annualized_pnl / drawdown if drawdown > 0 else math.nan,
        "annualized_volatility": annualized_volatility,
        "profitable_months": float((monthly > 0).mean()) if len(monthly) else math.nan,
    }


def metrics(
    frame: pd.DataFrame,
    samples: int,
    seed_label: str,
    calendar: pd.DatetimeIndex,
) -> dict[str, float]:
    ordered = frame.sort_values("exit_time")
    gross_wins = float(ordered.loc[ordered.pnl > 0, "pnl"].sum())
    gross_losses = float(-ordered.loc[ordered.pnl < 0, "pnl"].sum())
    ci_low, ci_high = month_block_interval(ordered, samples, seed_label)
    return {
        "trades": len(ordered),
        "win_rate": float((ordered.pnl >= 0).mean()) if len(ordered) else math.nan,
        "avg_points": float(ordered.points.mean()) if len(ordered) else math.nan,
        "avg_points_ci_low": ci_low,
        "avg_points_ci_high": ci_high,
        "avg_r": float(ordered.r_multiple.mean()) if len(ordered) else math.nan,
        "total_pnl": float(ordered.pnl.sum()),
        "profit_factor": gross_wins / gross_losses if gross_losses else math.nan,
        "max_drawdown": maximum_drawdown(ordered.pnl),
        **daily_risk_metrics(ordered, calendar),
    }


def attach_features(
    trades: pd.DataFrame,
    zones: pd.DataFrame,
    retests: pd.DataFrame,
) -> pd.DataFrame:
    zone_columns = [
        "zone_id", "zone_width_atr", "impulse_body_atr", "impulse_body_fraction",
        "impulse_close_strength", "formation_rvol", "bos", "fvg",
        "nested_htf_count", "opposing_room_at_formation_r", "formation_volume",
        "prior_volume",
    ]
    result = trades.merge(
        zones[zone_columns], on="zone_id", how="left", validate="many_to_one"
    )

    executed = retests.loc[retests.SND_trade_executed].copy()
    pairs = result[["trade_id", "zone_id", "entry_time"]].merge(
        executed,
        on="zone_id",
        how="left",
        validate="many_to_many",
        suffixes=("", "_episode"),
    )
    inside = pairs.loc[
        (pairs.entry_time >= pairs.touch_time)
        & (pairs.entry_time < pairs.episode_end_time)
    ].copy()
    counts = inside.groupby("trade_id").size()
    if len(counts) != len(result) or not counts.eq(1).all():
        raise ValueError("Each Phase 1 trade must map to exactly one executed touch episode")
    inside = inside.sort_values("trade_id").set_index("trade_id")
    result = result.sort_values("trade_id").reset_index(drop=True)
    touch_columns = [
        "touch_number", "departure_before_touch_zone_widths", "age_minutes",
        "prior_5m_rvol", "opposing_room_at_touch_r",
    ]
    for column in touch_columns:
        result[column] = inside.loc[result.trade_id, column].to_numpy()
    result["formation_prior_volume_ratio"] = (
        result.formation_volume / result.prior_volume.replace(0, np.nan)
    )
    if result["formation_rvol"].isna().all():
        raise ValueError("Formation features failed to attach")
    return result


def split_mask(frame: pd.DataFrame, split: str) -> pd.Series:
    if split == "Overall":
        return pd.Series(True, index=frame.index)
    start, end = SPLITS[split]
    return frame.entry_year.between(start, end)


def candidate_masks(frame: pd.DataFrame) -> dict[str, tuple[str, pd.Series]]:
    one_hour = frame.timeframe.eq("1h")
    room_open = frame.opposing_room_at_touch_r.isna() | frame.opposing_room_at_touch_r.ge(2.0)
    return {
        "SND baseline": ("All trades", pd.Series(True, index=frame.index)),
        "1h reference": ("All trades", one_hour),
        "1h · BOS": ("1h", one_hour & frame.bos),
        "1h · no BOS": ("1h", one_hour & ~frame.bos),
        "1h · RVOL <0.75": ("1h", one_hour & frame.formation_rvol.lt(0.75)),
        "1h · RVOL 0.75–1.25": (
            "1h", one_hour & frame.formation_rvol.ge(0.75) & frame.formation_rvol.lt(1.25)
        ),
        "1h · RVOL ≥1.25": ("1h", one_hour & frame.formation_rvol.ge(1.25)),
        "1h · prior 5m RVOL <0.75": ("1h", one_hour & frame.prior_5m_rvol.lt(0.75)),
        "1h · prior 5m RVOL 0.75–1.25": (
            "1h", one_hour & frame.prior_5m_rvol.ge(0.75) & frame.prior_5m_rvol.lt(1.25)
        ),
        "1h · prior 5m RVOL ≥1.25": ("1h", one_hour & frame.prior_5m_rvol.ge(1.25)),
        "1h · impulse/prior volume <0.75": (
            "1h", one_hour & frame.formation_prior_volume_ratio.lt(0.75)
        ),
        "1h · impulse/prior volume 0.75–1.25": (
            "1h", one_hour & frame.formation_prior_volume_ratio.ge(0.75)
            & frame.formation_prior_volume_ratio.lt(1.25)
        ),
        "1h · impulse/prior volume ≥1.25": (
            "1h", one_hour & frame.formation_prior_volume_ratio.ge(1.25)
        ),
        "1h · first SND test": ("1h", one_hour & frame.test_number.eq(1)),
        "1h · first physical touch": ("1h", one_hour & frame.touch_number.eq(1)),
        "1h · HTF nested": ("1h", one_hour & frame.nested_htf_count.gt(0)),
        "1h · width ≤0.5 ATR": ("1h", one_hour & frame.zone_width_atr.le(0.5)),
        "1h · impulse ≥0.75 ATR": ("1h", one_hour & frame.impulse_body_atr.ge(0.75)),
        "1h · opposing room ≥2R/open": ("1h", one_hour & room_open),
        "1h · departure ≥1 width": (
            "1h", one_hour & frame.departure_before_touch_zone_widths.ge(1.0)
        ),
    }


def experiment_table(frame: pd.DataFrame, samples: int) -> pd.DataFrame:
    masks = candidate_masks(frame)
    calendars = evaluation_calendars(frame)
    reference_masks = {
        "All trades": pd.Series(True, index=frame.index),
        "1h": frame.timeframe.eq("1h"),
    }
    rows: list[dict[str, object]] = []
    for experiment, (universe, candidate) in masks.items():
        for split in ["Overall", *SPLITS]:
            period = split_mask(frame, split)
            selected = frame.loc[candidate & period]
            reference = frame.loc[reference_masks[universe] & period]
            values = metrics(selected, samples, f"{experiment}|{split}", calendars[split])
            reference_values = metrics(
                reference, samples, f"reference|{universe}|{split}", calendars[split]
            )
            rows.append({
                "experiment": experiment,
                "reference_universe": universe,
                "split": split,
                "retention": len(selected) / len(reference) if len(reference) else math.nan,
                "avg_points_uplift": values["avg_points"] - reference_values["avg_points"],
                "profit_factor_uplift": values["profit_factor"] - reference_values["profit_factor"],
                **values,
            })
    return pd.DataFrame(rows)


def bucket_definitions(frame: pd.DataFrame) -> dict[str, pd.Series]:
    room = frame.opposing_room_at_touch_r
    return {
        "BOS | yes": frame.bos,
        "BOS | no": ~frame.bos,
        "Formation RVOL | <0.75": frame.formation_rvol.lt(0.75),
        "Formation RVOL | 0.75–1.25": frame.formation_rvol.ge(0.75) & frame.formation_rvol.lt(1.25),
        "Formation RVOL | ≥1.25": frame.formation_rvol.ge(1.25),
        "Formation RVOL | unavailable": frame.formation_rvol.isna(),
        "Prior 5m RVOL | <0.75": frame.prior_5m_rvol.lt(0.75),
        "Prior 5m RVOL | 0.75–1.25": frame.prior_5m_rvol.ge(0.75) & frame.prior_5m_rvol.lt(1.25),
        "Prior 5m RVOL | ≥1.25": frame.prior_5m_rvol.ge(1.25),
        "Prior 5m RVOL | unavailable": frame.prior_5m_rvol.isna(),
        "Impulse/prior volume | <0.75": frame.formation_prior_volume_ratio.lt(0.75),
        "Impulse/prior volume | 0.75–1.25": (
            frame.formation_prior_volume_ratio.ge(0.75)
            & frame.formation_prior_volume_ratio.lt(1.25)
        ),
        "Impulse/prior volume | ≥1.25": frame.formation_prior_volume_ratio.ge(1.25),
        "SND test | first": frame.test_number.eq(1),
        "SND test | second": frame.test_number.eq(2),
        "Physical touch | first": frame.touch_number.eq(1),
        "Physical touch | later": frame.touch_number.gt(1),
        "HTF nesting | nested": frame.nested_htf_count.gt(0),
        "HTF nesting | standalone": frame.nested_htf_count.eq(0),
        "Zone width | ≤0.5 ATR": frame.zone_width_atr.le(0.5),
        "Zone width | 0.5–1 ATR": frame.zone_width_atr.gt(0.5) & frame.zone_width_atr.le(1.0),
        "Zone width | >1 ATR": frame.zone_width_atr.gt(1.0),
        "Impulse body | <0.5 ATR": frame.impulse_body_atr.lt(0.5),
        "Impulse body | 0.5–0.75 ATR": frame.impulse_body_atr.ge(0.5) & frame.impulse_body_atr.lt(0.75),
        "Impulse body | ≥0.75 ATR": frame.impulse_body_atr.ge(0.75),
        "Opposing room | <1R": room.lt(1.0),
        "Opposing room | 1–2R": room.ge(1.0) & room.lt(2.0),
        "Opposing room | ≥2R": room.ge(2.0),
        "Opposing room | open": room.isna(),
        "Prior departure | <1 width": frame.departure_before_touch_zone_widths.lt(1.0),
        "Prior departure | ≥1 width": frame.departure_before_touch_zone_widths.ge(1.0),
        "FVG | yes": frame.fvg,
        "FVG | no": ~frame.fvg,
    }


def bucket_table(frame: pd.DataFrame, samples: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    calendars = evaluation_calendars(frame)
    universes = {"All trades": pd.Series(True, index=frame.index), "1h": frame.timeframe.eq("1h")}
    for key, bucket in bucket_definitions(frame).items():
        variable, level = key.split(" | ", 1)
        for universe, universe_mask in universes.items():
            for split in ["Overall", *SPLITS]:
                selected = frame.loc[bucket & universe_mask & split_mask(frame, split)]
                values = metrics(
                    selected, samples, f"bucket|{key}|{universe}|{split}", calendars[split]
                )
                rows.append({
                    "variable": variable,
                    "level": level,
                    "universe": universe,
                    "split": split,
                    **values,
                })
    return pd.DataFrame(rows)


def classify_experiments(table: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for experiment, group in table.groupby("experiment", sort=False):
        values = group.set_index("split")
        validation = values.loc["Validation 2023–24"]
        holdout = values.loc["Holdout 2025–26"]
        train = values.loc["Train 2019–22"]
        enough = min(validation.trades, holdout.trades) >= 100
        validation_positive = validation.avg_points > 0 and validation.profit_factor > 1
        holdout_positive = holdout.avg_points > 0 and holdout.profit_factor > 1
        train_positive = train.avg_points > 0 and train.profit_factor > 1
        validation_improves = (
            validation.avg_points_uplift > 0 and validation.profit_factor_uplift > 0
        )
        holdout_improves = holdout.avg_points_uplift > 0 and holdout.profit_factor_uplift > 0
        uncertainty_clears_zero = (
            validation.avg_points_ci_low > 0 and holdout.avg_points_ci_low > 0
        )
        if experiment in {"SND baseline", "1h reference"}:
            status = "reference"
        elif not enough:
            status = "limited sample"
        elif (
            validation_positive and holdout_positive and validation_improves
            and holdout_improves and train_positive and uncertainty_clears_zero
        ):
            status = "validated screen"
        elif validation_positive and holdout_positive and validation_improves and holdout_improves:
            status = "promising; uncertainty remains"
        elif validation_positive and holdout_positive:
            status = "positive, but no uplift"
        elif holdout_positive:
            status = "mixed; holdout positive"
        else:
            status = "not supported"
        overall = values.loc["Overall"]
        rows.append({
            "experiment": experiment,
            "status": status,
            "overall_trades": int(overall.trades),
            "overall_avg_points": overall.avg_points,
            "overall_profit_factor": overall.profit_factor,
            "train_profit_factor": train.profit_factor,
            "validation_profit_factor": validation.profit_factor,
            "holdout_profit_factor": holdout.profit_factor,
            "holdout_avg_points": holdout.avg_points,
            "holdout_ci_low": holdout.avg_points_ci_low,
            "holdout_ci_high": holdout.avg_points_ci_high,
            "holdout_trades": int(holdout.trades),
            "overall_sharpe": overall.sharpe,
            "holdout_sharpe": holdout.sharpe,
            "holdout_sortino": holdout.sortino,
            "holdout_pnl_calmar": holdout.pnl_calmar,
            "holdout_annualized_volatility": holdout.annualized_volatility,
            "holdout_profitable_months": holdout.profitable_months,
        })
    return pd.DataFrame(rows)


def format_value(value: object, kind: str = "number") -> str:
    if pd.isna(value):
        return "n/a"
    number = float(value)
    if kind == "integer":
        return f"{int(number):,}"
    if kind == "percent":
        return f"{number:.1%}"
    return f"{number:.2f}"


def verdict_table(verdicts: pd.DataFrame) -> str:
    body = []
    for row in verdicts.itertuples(index=False):
        interval = f"{row.holdout_ci_low:.2f} to {row.holdout_ci_high:.2f}"
        body.append(
            f"<tr><th>{html.escape(row.experiment)}</th><td>{html.escape(row.status)}</td>"
            f"<td>{row.overall_trades:,}</td><td>{row.overall_profit_factor:.2f}</td>"
            f"<td>{row.train_profit_factor:.2f}</td><td>{row.validation_profit_factor:.2f}</td>"
            f"<td>{row.holdout_profit_factor:.2f}</td><td>{row.holdout_avg_points:.2f}</td>"
            f"<td>{interval}</td><td>{row.holdout_trades:,}</td>"
            f"<td>{row.overall_sharpe:.2f}</td><td>{row.holdout_sharpe:.2f}</td>"
            f"<td>{row.holdout_sortino:.2f}</td><td>{row.holdout_pnl_calmar:.2f}</td>"
            f"<td>${row.holdout_annualized_volatility:,.0f}</td>"
            f"<td>{row.holdout_profitable_months:.1%}</td></tr>"
        )
    return """<div class='table-wrap'><table><thead><tr><th>Experiment</th><th>Status</th>
    <th>Overall trades</th><th>Overall PF</th><th>Train PF</th><th>Validation PF</th>
    <th>Holdout PF</th><th>Holdout avg pts</th><th>95% interval</th><th>Holdout trades</th>
    <th>Overall Sharpe</th><th>Holdout Sharpe</th><th>Holdout Sortino</th>
    <th>Holdout P&amp;L Calmar</th><th>Holdout ann. vol</th><th>Holdout profitable months</th>
    </tr></thead><tbody>""" + "".join(body) + "</tbody></table></div>"


def bucket_html(table: pd.DataFrame) -> str:
    selected = table.loc[(table.universe == "1h") & table.split.isin(["Overall", "Holdout 2025–26"])]
    pivot = selected.pivot(index=["variable", "level"], columns="split", values=["trades", "avg_points", "profit_factor"])
    body = []
    for (variable, level), row in pivot.iterrows():
        def get(metric: str, split: str) -> float:
            return row.get((metric, split), math.nan)
        body.append(
            f"<tr><th>{html.escape(variable)}</th><td>{html.escape(level)}</td>"
            f"<td>{format_value(get('trades', 'Overall'), 'integer')}</td>"
            f"<td>{format_value(get('avg_points', 'Overall'))}</td>"
            f"<td>{format_value(get('profit_factor', 'Overall'))}</td>"
            f"<td>{format_value(get('trades', 'Holdout 2025–26'), 'integer')}</td>"
            f"<td>{format_value(get('avg_points', 'Holdout 2025–26'))}</td>"
            f"<td>{format_value(get('profit_factor', 'Holdout 2025–26'))}</td></tr>"
        )
    return """<div class='table-wrap'><table><thead><tr><th>Variable</th><th>Bucket</th>
    <th>All trades</th><th>All avg pts</th><th>All PF</th><th>Holdout trades</th>
    <th>Holdout avg pts</th><th>Holdout PF</th></tr></thead><tbody>""" + "".join(body) + "</tbody></table></div>"


STYLE = """
:root{color-scheme:light;--bg:#f5f6f8;--panel:#fff;--panel2:#f0f2f5;--text:#111827;--muted:#687386;--border:#dfe3e8;--accent:#4c8bf5}
@media(prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#101216;--panel:#181b21;--panel2:#22262e;--text:#f4f6f8;--muted:#9aa4b2;--border:#303640;--accent:#70a4ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.wrap{max-width:1280px;margin:auto;padding:36px 22px 80px}
.eyebrow{text-transform:uppercase;letter-spacing:.11em;font-size:11px;font-weight:700;color:var(--accent)}h1{font-size:32px;letter-spacing:-.035em;margin:6px 0}h2{margin:38px 0 4px;font-size:21px}h3{margin:0;font-size:15px}.lead,.note{color:var(--muted);max-width:920px}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:10px;margin:20px 0}.tile,.method,.figure{background:var(--panel);border:1px solid var(--border);border-radius:11px;padding:14px 16px}.tile span{display:block;color:var(--muted);font-size:11px;text-transform:uppercase}.tile strong{font-size:22px;display:block;margin-top:3px}.table-wrap{overflow:auto;border:1px solid var(--border);border-radius:10px;background:var(--panel);margin:12px 0}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{padding:8px 11px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}thead th{background:var(--panel2);color:var(--muted);font-size:10px;text-transform:uppercase}thead th:first-child,tbody th{text-align:left}tbody tr:last-child>*{border-bottom:0}.figure{margin:12px 0}.figure figcaption p{color:var(--muted);font-size:12px;margin:3px 0}.legend{display:flex;gap:16px;flex-wrap:wrap;margin:10px 0;color:var(--muted);font-size:12px}.legend span{display:flex;align-items:center;gap:6px}.legend i{width:18px;height:3px}.plot{position:relative;overflow:auto}.chart{width:100%;min-width:720px;display:block}.grid{stroke:var(--border)}.zero{stroke:var(--muted);stroke-dasharray:4 4}.tick{fill:var(--muted);font-size:11px}.series-line{stroke-width:2.1}.hitbox{fill:transparent;pointer-events:all}.crosshair{stroke:var(--muted);stroke-dasharray:3 3}.tooltip{position:absolute;pointer-events:none;background:var(--text);color:var(--bg);font-size:12px;padding:8px 10px;border-radius:7px;white-space:nowrap}.method li{margin:7px 0}code{background:var(--panel2);padding:2px 5px;border-radius:4px}a{color:var(--accent)}
"""


def write_outputs(
    frame: pd.DataFrame,
    experiments: pd.DataFrame,
    buckets: pd.DataFrame,
    verdicts: pd.DataFrame,
    args: argparse.Namespace,
) -> None:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    series_dir = args.output_dir / "series"
    series_dir.mkdir(exist_ok=True)
    frame.to_parquet(args.output_dir / "trade_features.parquet", index=False)
    experiments.to_csv(args.output_dir / "experiment_metrics.csv", index=False)
    buckets.to_csv(args.output_dir / "bucket_metrics.csv", index=False)
    verdicts.to_csv(args.output_dir / "verdicts.csv", index=False)

    masks = candidate_masks(frame)
    chart_names = [
        "SND baseline", "1h reference", "1h · first SND test",
        "1h · width ≤0.5 ATR", "1h · opposing room ≥2R/open",
        "1h · no BOS", "1h · RVOL 0.75–1.25", "1h · prior 5m RVOL 0.75–1.25",
    ]
    chart_series: dict[str, pd.DataFrame] = {}
    series_registry: dict[str, str] = {}
    for number, name in enumerate(chart_names):
        selected = frame.loc[masks[name][1]].sort_values("exit_time").copy()
        filename = f"screen_{number:02d}.parquet"
        selected.to_parquet(series_dir / filename, index=False)
        chart_series[name] = selected
        series_registry[name] = str(Path("series") / filename)
    (args.output_dir / "series.json").write_text(json.dumps(series_registry, indent=2) + "\n")
    equity, _, rolling, _ = comparison_frames(chart_series)

    status_counts = verdicts.status.value_counts()
    promising = int(status_counts.get("promising; uncertainty remains", 0))
    validated = int(status_counts.get("validated screen", 0))
    baseline_pf = experiments.loc[
        (experiments.experiment == "SND baseline") & (experiments.split == "Overall"),
        "profit_factor",
    ].iloc[0]
    one_hour_pf = experiments.loc[
        (experiments.experiment == "1h reference") & (experiments.split == "Overall"),
        "profit_factor",
    ].iloc[0]
    summary = {
        "trades_screened": len(frame),
        "experiments": len(verdicts) - 2,
        "validated_screens": validated,
        "promising_screens": promising,
        "baseline_profit_factor": float(baseline_pf),
        "one_hour_profit_factor": float(one_hour_pf),
        "bootstrap_samples": args.bootstrap_samples,
        "method": "Univariate cohort screen of unchanged Phase 1 trades",
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    tiles = "".join(
        f"<div class='tile'><span>{label}</span><strong>{value}</strong></div>"
        for label, value in [
            ("Trades screened", f"{len(frame):,}"),
            ("Variables/rules", f"{len(verdicts)-2:,}"),
            ("Validated screens", str(validated)),
            ("Promising screens", str(promising)),
            ("Baseline PF", f"{baseline_pf:.2f}"),
            ("1h reference PF", f"{one_hour_pf:.2f}"),
        ]
    )
    page = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
    <title>SND Phase 3 confluence screen</title><style>{STYLE}</style></head><body><main class='wrap'>
    <div class='eyebrow'>MNQ · SND strategy lab</div><h1>Phase 3 confluence screen</h1>
    <p class='lead'>Each condition is tested separately on SND's unchanged baseline trades. Results are split chronologically and uncertainty is estimated by resampling calendar months.</p>
    <div class='tiles'>{tiles}</div>
    <h2>Experiment verdicts</h2><p class='note'>“Promising” means positive point estimates in both validation and holdout. “Validated screen” additionally requires positive train results and a 95% month-block interval above zero in validation and holdout.</p>
    {verdict_table(verdicts)}
    <h2>Cohort equity paths</h2><p class='note'>These lines show retained baseline trades only. They are diagnostic screens, not full replacement-strategy backtests.</p>
    {svg_line_chart(equity, 'Cumulative screened P&L', 'MNQ dollars, before costs.', 'money')}
    {svg_line_chart(rolling, 'Rolling 90-day expectancy', 'Points per retained trade over trailing calendar time.', 'number')}
    <h2>One-hour bucket detail</h2><p class='note'>Exact predefined buckets; no threshold was optimized on the holdout period.</p>
    {bucket_html(buckets)}
    <h2>Interpretation contract</h2><div class='method'><ul>
    <li>Formation and pre-touch features existed before each original entry.</li>
    <li>Touch-candle reclaim/rejection is excluded because using it requires a later, realistically priced entry.</li>
    <li>Skipping a baseline trade can expose replacement signals; this screen intentionally does not model them.</li>
    <li>Repeated trades and zones are correlated. Month-block intervals reduce, but do not eliminate, that dependence.</li>
    <li>Phase 4 must re-simulate promising rules before any Pine implementation.</li>
    </ul></div>
    <p class='note'><a href='../SND_dashboard/index.html'>Main baseline dashboard</a> · <a href='../SND_phase2/index.html'>Phase 2 feature report</a></p>
    </main><script>{CHART_SCRIPT}</script></body></html>"""
    (args.output_dir / "index.html").write_text(page)


def main() -> None:
    args = parse_args()
    if args.bootstrap_samples < 100:
        raise ValueError("--bootstrap-samples must be at least 100")
    print("Loading Phase 1 trades and Phase 2 features...", flush=True)
    trades = pd.read_parquet(args.phase1_dir / "trades.parquet")
    zones = pd.read_parquet(args.phase2_dir / "zones_enriched.parquet")
    retests = pd.read_parquet(args.phase2_dir / "retests_enriched.parquet")
    for column in ("entry_time", "exit_time"):
        trades[column] = pd.to_datetime(trades[column], utc=True)
    frame = attach_features(trades, zones, retests)
    print(f"Screening {len(frame):,} mapped trades across predefined buckets...", flush=True)
    experiments = experiment_table(frame, args.bootstrap_samples)
    buckets = bucket_table(frame, args.bootstrap_samples)
    verdicts = classify_experiments(experiments)
    print("Writing Phase 3 HTML report and supporting ledgers...", flush=True)
    write_outputs(frame, experiments, buckets, verdicts, args)
    print(
        f"DONE | experiments={len(verdicts)-2} | "
        f"promising={(verdicts.status == 'promising; uncertainty remains').sum()} | "
        f"validated={(verdicts.status == 'validated screen').sum()} -> {args.output_dir}"
    )


if __name__ == "__main__":
    main()
