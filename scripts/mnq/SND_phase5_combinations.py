"""Run controlled Phase 5 combinations around SND's first-touch core.

Primary combinations are declared before simulation. Nearby width and volume
thresholds are labeled sensitivity checks and are not eligible to become the
recommended candidate merely because they produce the best historical result.

Run from the repository root:

    .venv/bin/python scripts/mnq/SND_phase5_combinations.py
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
import html
import json
import math
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

import SND_baseline_backtest as baseline
import SND_phase4_backtest as phase4
from SND_html_report import SCRIPT as CHART_SCRIPT
from SND_html_report import comparison_frames, metrics, svg_line_chart


ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data" / "mnq_dom_sample" / "full_history"
DEFAULT_MINUTE = DATA_ROOT / "ohlcv-1m" / "candles_1m.parquet"
DEFAULT_TF_DIR = DATA_ROOT / "ohlcv-resampled"
DEFAULT_PHASE1 = ROOT / "reports" / "SND_baseline"
DEFAULT_PHASE2 = ROOT / "reports" / "SND_phase2"
DEFAULT_PHASE4 = ROOT / "reports" / "SND_phase4"
DEFAULT_OUTPUT = ROOT / "reports" / "SND_phase5"
TIMEZONE = "America/Chicago"


@dataclass(frozen=True)
class Combination:
    label: str
    slug: str
    description: str
    primary: bool = True
    width_max_atr: float | None = None
    impulse_volume_max: float | None = None
    formation_rvol_min: float | None = None
    formation_rvol_max: float | None = None
    require_open_room: bool = False


COMBINATIONS = [
    Combination(
        "First touch + width ≤0.5 ATR", "01_first_touch_tight",
        "First physical touch plus zone width no greater than 0.5 ATR.",
        width_max_atr=0.5,
    ),
    Combination(
        "First touch + impulse volume <0.75", "02_first_touch_low_volume",
        "First physical touch plus impulse volume below 75% of the prior source candle.",
        impulse_volume_max=0.75,
    ),
    Combination(
        "First touch + normal RVOL", "03_first_touch_normal_rvol",
        "First physical touch plus formation RVOL from 0.75 inclusive to 1.25 exclusive.",
        formation_rvol_min=0.75, formation_rvol_max=1.25,
    ),
    Combination(
        "First touch + opposing room", "04_first_touch_open_room",
        "First physical touch plus at least 2 structural R to the nearest opposing zone, or none.",
        require_open_room=True,
    ),
    Combination(
        "First touch + width + low volume", "05_first_touch_tight_low_volume",
        "The only three-factor candidate: first touch, width ≤0.5 ATR, and impulse/prior volume <0.75.",
        width_max_atr=0.5, impulse_volume_max=0.75,
    ),
    Combination(
        "Sensitivity · first touch + width ≤0.4", "06_sensitivity_width_04",
        "Lower neighboring width threshold.", primary=False, width_max_atr=0.4,
    ),
    Combination(
        "Sensitivity · first touch + width ≤0.6", "07_sensitivity_width_06",
        "Upper neighboring width threshold.", primary=False, width_max_atr=0.6,
    ),
    Combination(
        "Sensitivity · first touch + volume <0.5", "08_sensitivity_volume_05",
        "Lower neighboring impulse/prior-volume threshold.",
        primary=False, impulse_volume_max=0.5,
    ),
    Combination(
        "Sensitivity · first touch + volume <1.0", "09_sensitivity_volume_10",
        "Upper neighboring impulse/prior-volume threshold.",
        primary=False, impulse_volume_max=1.0,
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--one-minute", type=Path, default=DEFAULT_MINUTE)
    parser.add_argument("--timeframe-dir", type=Path, default=DEFAULT_TF_DIR)
    parser.add_argument("--phase1-dir", type=Path, default=DEFAULT_PHASE1)
    parser.add_argument("--phase2-dir", type=Path, default=DEFAULT_PHASE2)
    parser.add_argument("--phase4-dir", type=Path, default=DEFAULT_PHASE4)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--point-value", type=float, default=2.0)
    parser.add_argument("--reuse-ledgers", action="store_true")
    return parser.parse_args()


def make_filter(
    combination: Combination,
    features: pd.DataFrame,
) -> Callable[[baseline.Zone, list[baseline.Zone], list[baseline.Zone]], bool]:
    def entry_filter(
        zone: baseline.Zone,
        active_long: list[baseline.Zone],
        active_short: list[baseline.Zone],
    ) -> bool:
        if zone.timeframe != "1h" or zone.physical_touch_count != 1:
            return False
        row = features.loc[zone.zone_id]
        if combination.width_max_atr is not None and (
            pd.isna(row.zone_width_atr) or row.zone_width_atr > combination.width_max_atr
        ):
            return False
        if combination.impulse_volume_max is not None and (
            row.prior_volume <= 0
            or row.formation_volume / row.prior_volume >= combination.impulse_volume_max
        ):
            return False
        if combination.formation_rvol_min is not None and (
            pd.isna(row.formation_rvol)
            or row.formation_rvol < combination.formation_rvol_min
        ):
            return False
        if combination.formation_rvol_max is not None and (
            pd.isna(row.formation_rvol)
            or row.formation_rvol >= combination.formation_rvol_max
        ):
            return False
        if combination.require_open_room and not phase4.opposing_room_is_open(
            zone, active_long, active_short
        ):
            return False
        return True

    return entry_filter


def yearly_metrics(
    series: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    first = min(frame.entry_year.min() for frame in series.values())
    last = max(frame.entry_year.max() for frame in series.values())
    rows = []
    for label, frame in series.items():
        for year in range(int(first), int(last) + 1):
            selected = frame.loc[frame.entry_year == year]
            calendar = pd.bdate_range(f"{year}-01-01", f"{year}-12-31")
            if year == first:
                start = min(
                    item.exit_time.min().tz_convert(TIMEZONE).tz_localize(None).normalize()
                    for item in series.values()
                )
                calendar = calendar[calendar >= start]
            if year == last:
                end = max(
                    item.exit_time.max().tz_convert(TIMEZONE).tz_localize(None).normalize()
                    for item in series.values()
                )
                calendar = calendar[calendar <= end]
            values = metrics(selected, calendar)
            rows.append({"variant": label, "year": year, **values})
    return pd.DataFrame(rows)


def monthly_concentration(series: dict[str, pd.DataFrame]) -> pd.DataFrame:
    first_month = min(
        frame.exit_time.min().tz_convert(TIMEZONE).tz_localize(None).to_period("M")
        for frame in series.values()
    )
    last_month = max(
        frame.exit_time.max().tz_convert(TIMEZONE).tz_localize(None).to_period("M")
        for frame in series.values()
    )
    complete_months = pd.period_range(first_month, last_month, freq="M")
    rows = []
    for label, frame in series.items():
        local = frame.exit_time.dt.tz_convert(TIMEZONE).dt.tz_localize(None)
        monthly = frame.assign(month=local.dt.to_period("M")).groupby("month").pnl.sum()
        monthly = monthly.reindex(complete_months, fill_value=0.0)
        best_three = float(monthly.nlargest(3).sum())
        total = float(monthly.sum())
        rows.append({
            "variant": label,
            "total_pnl": total,
            "best_three_months_pnl": best_three,
            "pnl_without_best_three_months": total - best_three,
            "positive_months": int((monthly > 0).sum()),
            "months": len(monthly),
            "positive_month_rate": float((monthly > 0).mean()),
        })
    return pd.DataFrame(rows)


def classify(metrics_by_split: pd.DataFrame, combinations: list[Combination]) -> pd.DataFrame:
    primary = {item.label: item.primary for item in combinations}
    rows = []
    for variant, group in metrics_by_split.groupby("variant", sort=False):
        values = group.set_index("split")
        overall = values.loc["Overall"]
        train = values.loc["Train 2019–22"]
        validation = values.loc["Validation 2023–24"]
        holdout = values.loc["Holdout 2025–26"]
        positive = lambda row: row.profit_factor > 1 and row.sharpe > 0
        if variant == "SND baseline":
            status = "control"
        elif variant == "First physical touch core":
            status = "core reference"
        elif positive(train) and positive(validation) and positive(holdout):
            status = "positive all periods"
        elif positive(validation) and positive(holdout):
            status = "positive recent periods"
        elif positive(holdout):
            status = "mixed; holdout positive"
        else:
            status = "not supported"
        rows.append({
            "variant": variant,
            "candidate_type": "reference" if variant in {
                "SND baseline", "First physical touch core"
            } else "primary" if primary.get(variant, False) else "sensitivity",
            "status": status,
            "trades": int(overall.trades),
            "overall_profit_factor": overall.profit_factor,
            "overall_sharpe": overall.sharpe,
            "overall_pnl": overall.total_pnl,
            "train_profit_factor": train.profit_factor,
            "validation_profit_factor": validation.profit_factor,
            "holdout_profit_factor": holdout.profit_factor,
            "holdout_sharpe": holdout.sharpe,
            "holdout_pnl": holdout.total_pnl,
            "holdout_trades": int(holdout.trades),
        })
    return pd.DataFrame(rows)


def choose_candidate(
    verdicts: pd.DataFrame,
    costs: pd.DataFrame,
) -> pd.Series:
    candidates = verdicts.copy()
    two_tick = costs.loc[costs.round_trip_cost_ticks == 2, ["variant", "profit_factor"]]
    candidates = candidates.merge(two_tick, on="variant", how="left", validate="one_to_one")
    candidates["worst_period_pf"] = candidates[[
        "train_profit_factor", "validation_profit_factor", "holdout_profit_factor"
    ]].min(axis=1)
    core = candidates.loc[candidates.variant == "First physical touch core"].iloc[0]
    primary = candidates.loc[candidates.candidate_type == "primary"]
    # An added rule must improve both overall and holdout risk-adjusted results
    # while retaining positive PF in every era and after two ticks of friction.
    eligible = primary.loc[
        (primary.profit_factor > core.profit_factor)
        & (primary.overall_sharpe > core.overall_sharpe)
        & (primary.holdout_sharpe > core.holdout_sharpe)
        & (primary.train_profit_factor > 1)
        & (primary.validation_profit_factor > 1)
        & (primary.holdout_profit_factor > 1)
    ]
    if eligible.empty:
        return core
    return eligible.sort_values(["overall_sharpe", "worst_period_pf"], ascending=False).iloc[0]


def fmt(value: float, kind: str = "number") -> str:
    if pd.isna(value):
        return "n/a"
    if kind == "integer":
        return f"{int(value):,}"
    if kind == "money":
        return f"{'−' if value < 0 else ''}${abs(value):,.0f}"
    if kind == "percent":
        return f"{value:.1%}"
    return f"{value:.2f}"


def verdict_html(frame: pd.DataFrame, costs: pd.DataFrame) -> str:
    two_tick = costs.loc[costs.round_trip_cost_ticks == 2].set_index("variant")
    body = []
    for row in frame.itertuples(index=False):
        cost_pf = two_tick.loc[row.variant, "profit_factor"]
        body.append(
            f"<tr><th>{html.escape(row.variant)}</th><td>{row.candidate_type}</td>"
            f"<td>{html.escape(row.status)}</td><td>{row.trades:,}</td>"
            f"<td>{row.overall_profit_factor:.2f}</td><td>{row.overall_sharpe:.2f}</td>"
            f"<td>{fmt(row.overall_pnl, 'money')}</td><td>{row.train_profit_factor:.2f}</td>"
            f"<td>{row.validation_profit_factor:.2f}</td><td>{row.holdout_profit_factor:.2f}</td>"
            f"<td>{row.holdout_sharpe:.2f}</td><td>{fmt(row.holdout_pnl, 'money')}</td>"
            f"<td>{row.holdout_trades:,}</td><td>{cost_pf:.2f}</td></tr>"
        )
    return """<div class='table-wrap'><table><thead><tr><th>Variant</th><th>Type</th>
    <th>Status</th><th>Trades</th><th>PF</th><th>Sharpe</th><th>P&amp;L</th>
    <th>Train PF</th><th>Validation PF</th><th>Holdout PF</th><th>Holdout Sharpe</th>
    <th>Holdout P&amp;L</th><th>Holdout trades</th><th>PF at 2 ticks</th>
    </tr></thead><tbody>""" + "".join(body) + "</tbody></table></div>"


def yearly_html(frame: pd.DataFrame, labels: list[str]) -> str:
    selected = frame.loc[frame.variant.isin(labels)]
    pf = selected.pivot(index="year", columns="variant", values="profit_factor")
    body = []
    for year, row in pf.iterrows():
        body.append(
            f"<tr><th>{year}</th>" + "".join(
                f"<td>{fmt(row.get(label, np.nan))}</td>" for label in labels
            ) + "</tr>"
        )
    headers = "".join(f"<th>{html.escape(label)}</th>" for label in labels)
    return f"<div class='table-wrap'><table><thead><tr><th>Year</th>{headers}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"


def concentration_html(frame: pd.DataFrame) -> str:
    body = []
    for row in frame.itertuples(index=False):
        body.append(
            f"<tr><th>{html.escape(row.variant)}</th><td>{fmt(row.total_pnl, 'money')}</td>"
            f"<td>{fmt(row.best_three_months_pnl, 'money')}</td>"
            f"<td>{fmt(row.pnl_without_best_three_months, 'money')}</td>"
            f"<td>{row.positive_months}/{row.months}</td>"
            f"<td>{row.positive_month_rate:.1%}</td></tr>"
        )
    return """<div class='table-wrap'><table><thead><tr><th>Variant</th><th>Total P&amp;L</th>
    <th>Best 3 months</th><th>Without best 3</th><th>Positive months</th><th>Positive rate</th>
    </tr></thead><tbody>""" + "".join(body) + "</tbody></table></div>"


STYLE = """
:root{color-scheme:light;--bg:#f5f6f8;--panel:#fff;--panel2:#f0f2f5;--text:#111827;--muted:#687386;--border:#dfe3e8;--accent:#4c8bf5}
@media(prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#101216;--panel:#181b21;--panel2:#22262e;--text:#f4f6f8;--muted:#9aa4b2;--border:#303640;--accent:#70a4ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.wrap{max-width:1340px;margin:auto;padding:36px 22px 80px}.eyebrow{text-transform:uppercase;letter-spacing:.11em;font-size:11px;font-weight:700;color:var(--accent)}h1{font-size:32px;letter-spacing:-.035em;margin:6px 0}h2{font-size:21px;margin:38px 0 4px}h3{font-size:15px;margin:0}.lead,.note{color:var(--muted);max-width:950px}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:20px 0}.tile,.method,.figure{background:var(--panel);border:1px solid var(--border);border-radius:11px;padding:14px 16px}.tile span{display:block;color:var(--muted);font-size:11px;text-transform:uppercase}.tile strong{display:block;font-size:21px;margin-top:3px}.table-wrap{overflow:auto;border:1px solid var(--border);border-radius:10px;background:var(--panel);margin:12px 0}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{padding:8px 11px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}thead th{background:var(--panel2);color:var(--muted);font-size:10px;text-transform:uppercase}thead th:first-child,tbody th{text-align:left}tbody tr:last-child>*{border-bottom:0}.figure{margin:12px 0}.figure figcaption p{color:var(--muted);font-size:12px;margin:3px 0}.legend{display:flex;gap:14px;flex-wrap:wrap;margin:10px 0;color:var(--muted);font-size:12px}.legend span{display:flex;align-items:center;gap:5px}.legend i{width:18px;height:3px}.plot{position:relative;overflow:auto}.chart{width:100%;min-width:760px;display:block}.grid{stroke:var(--border)}.zero{stroke:var(--muted);stroke-dasharray:4 4}.tick{fill:var(--muted);font-size:11px}.series-line{stroke-width:2}.hitbox{fill:transparent;pointer-events:all}.crosshair{stroke:var(--muted);stroke-dasharray:3 3}.tooltip{position:absolute;pointer-events:none;background:var(--text);color:var(--bg);font-size:12px;padding:8px 10px;border-radius:7px;white-space:nowrap}.method li{margin:7px 0}code{background:var(--panel2);padding:2px 5px;border-radius:4px}a{color:var(--accent)}
"""


def write_report(
    series: dict[str, pd.DataFrame],
    split_metrics: pd.DataFrame,
    verdicts: pd.DataFrame,
    costs: pd.DataFrame,
    annual: pd.DataFrame,
    concentration: pd.DataFrame,
    recommendation: pd.Series,
    args: argparse.Namespace,
) -> None:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    equity, drawdown, rolling, annual_pnl = comparison_frames(series)
    equity.to_csv(args.output_dir / "daily_equity.csv")
    drawdown.to_csv(args.output_dir / "daily_drawdown.csv")
    rolling.to_csv(args.output_dir / "rolling_90d_expectancy.csv")
    annual_pnl.to_csv(args.output_dir / "annual_pnl.csv")
    split_metrics.to_csv(args.output_dir / "metrics_by_split.csv", index=False)
    verdicts.to_csv(args.output_dir / "verdicts.csv", index=False)
    costs.to_csv(args.output_dir / "cost_sensitivity.csv", index=False)
    annual.to_csv(args.output_dir / "yearly_metrics.csv", index=False)
    concentration.to_csv(args.output_dir / "monthly_concentration.csv", index=False)
    summary = {
        "primary_combinations": sum(item.primary for item in COMBINATIONS),
        "sensitivity_checks": sum(not item.primary for item in COMBINATIONS),
        "recommended_for_next_validation": recommendation.variant,
        "recommendation_worst_period_profit_factor": float(recommendation.worst_period_pf),
        "recommendation_two_tick_profit_factor": float(recommendation.profit_factor),
        "best_primary_challenger_by_sharpe": verdicts.loc[
            verdicts.candidate_type == "primary"
        ].sort_values("overall_sharpe", ascending=False).iloc[0].variant,
        "selection_rule": "Promote an added rule only if it beats the first-touch core at two ticks and on overall and holdout Sharpe, with PF > 1 in every era; otherwise retain the core.",
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    tiles = "".join(
        f"<div class='tile'><span>{label}</span><strong>{value}</strong></div>"
        for label, value in [
            ("Primary combinations", summary["primary_combinations"]),
            ("Sensitivity checks", summary["sensitivity_checks"]),
            ("Next candidate", recommendation.variant),
            ("Worst-period PF", f"{recommendation.worst_period_pf:.2f}"),
            ("PF at 2 ticks", f"{recommendation.profit_factor:.2f}"),
        ]
    )
    definitions = "".join(
        f"<li><strong>{html.escape(item.label)}:</strong> {html.escape(item.description)}</li>"
        for item in COMBINATIONS
    )
    yearly_labels = [
        "First physical touch core", recommendation.variant,
        "First touch + width ≤0.5 ATR", "First touch + impulse volume <0.75",
    ]
    yearly_labels = list(dict.fromkeys(yearly_labels))
    page = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
    <title>SND Phase 5 combinations</title><style>{STYLE}</style></head><body><main class='wrap'>
    <div class='eyebrow'>MNQ · SND strategy lab</div><h1>Phase 5 controlled combinations</h1>
    <p class='lead'>First physical touch is fixed as the core. Each additional factor is tested through a fresh one-minute engine run; sensitivity variants cannot win the recommendation simply by looking best historically.</p>
    <div class='tiles'>{tiles}</div>
    <h2>Combination results</h2><p class='note'>The 2025–26 period is informative but no longer pristine because its component results were already viewed in earlier phases.</p>
    {verdict_html(verdicts, costs)}
    <h2>Equity and drawdown</h2>
    {svg_line_chart(equity, 'Cumulative combination P&L', 'MNQ dollars before costs.', 'money')}
    {svg_line_chart(drawdown, 'Daily drawdown', 'Distance below each line’s prior daily peak.', 'money')}
    {svg_line_chart(rolling, 'Rolling 90-day expectancy', 'Points per trade over trailing calendar time.', 'number')}
    <h2>Year-by-year profit factor</h2><p class='note'>Fixed-rule annual slices show regime stability with no year omitted. They are not pristine out-of-sample tests because earlier phases informed the rules.</p>
    {yearly_html(annual, yearly_labels)}
    <h2>Dependence on exceptional months</h2><p class='note'>A robust candidate should not owe all cumulative profit to only three months.</p>
    {concentration_html(concentration)}
    <h2>Predeclared rules</h2><div class='method'><ul>{definitions}</ul></div>
    <p class='note'><a href='../SND_dashboard/index.html'>Main dashboard</a> · <a href='../SND_phase4/index.html'>Phase 4 report</a></p>
    </main><script>{CHART_SCRIPT}</script></body></html>"""
    (args.output_dir / "index.html").write_text(page)


def main() -> None:
    args = parse_args()
    sim_args = phase4.simulation_args(argparse.Namespace(point_value=args.point_value, cost_ticks=0.0))
    control = pd.read_parquet(args.phase1_dir / "trades.parquet").sort_values("exit_time")
    core = pd.read_parquet(args.phase4_dir / "06_1h_first_physical_touch" / "trades.parquet").sort_values("exit_time")
    for frame in (control, core):
        for column in ("entry_time", "exit_time"):
            frame[column] = pd.to_datetime(frame[column], utc=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    series: dict[str, pd.DataFrame] = {
        "SND baseline": control,
        "First physical touch core": core,
    }
    if args.reuse_ledgers:
        print("Reusing existing Phase 5 ledgers...", flush=True)
        for combination in COMBINATIONS:
            trades = pd.read_parquet(args.output_dir / combination.slug / "trades.parquet")
            series[combination.label] = trades.sort_values("exit_time")
    else:
        print("Loading one-minute data and verifying Phase 2 zone identity...", flush=True)
        minute = baseline.load_bars(args.one_minute)
        frames = {
            timeframe: baseline.load_bars(args.timeframe_dir / f"candles_{timeframe}.parquet")
            for timeframe in ("1h", "4h", "1d")
        }
        template = baseline.detect_zones(frames, minute.index, sim_args.body_ratio)
        feature_frame = pd.read_parquet(args.phase2_dir / "zones_enriched.parquet")
        features = phase4.validate_zone_identity(template, feature_frame)
        for number, combination in enumerate(COMBINATIONS, start=1):
            print(f"[{number}/{len(COMBINATIONS)}] {combination.label}...", flush=True)
            zones = copy.deepcopy(template)
            trades, tests, audit = baseline.simulate(
                minute, zones, None, None, sim_args, make_filter(combination, features)
            )
            if trades.empty:
                raise ValueError(f"Combination produced no trades: {combination.label}")
            output = args.output_dir / combination.slug
            output.mkdir(exist_ok=True)
            trades.to_parquet(output / "trades.parquet", index=False)
            tests.to_parquet(output / "zone_tests.parquet", index=False)
            (output / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
            series[combination.label] = trades.sort_values("exit_time")
            print(f"  {len(trades):,} trades", flush=True)

    split_metrics = phase4.metric_rows(series)
    verdicts = classify(split_metrics, COMBINATIONS)
    costs = phase4.cost_sensitivity(series, args.point_value)
    annual = yearly_metrics(series)
    concentration = monthly_concentration(series)
    recommendation = choose_candidate(verdicts, costs)
    print("Writing Phase 5 research report...", flush=True)
    write_report(
        series, split_metrics, verdicts, costs, annual, concentration,
        recommendation, args,
    )
    print(
        f"DONE | primary={sum(item.primary for item in COMBINATIONS)} | "
        f"sensitivity={sum(not item.primary for item in COMBINATIONS)} | "
        f"next={recommendation.variant} -> {args.output_dir}"
    )


if __name__ == "__main__":
    main()
