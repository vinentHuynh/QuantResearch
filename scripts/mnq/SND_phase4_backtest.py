"""Fully re-simulate SND Phase 3 candidates one rule at a time.

Unlike the Phase 3 cohort screen, every variant runs the one-minute event
engine from scratch. Skipped setups no longer create positions, so subsequent
eligible signals can be selected naturally.

Run from the repository root:

    .venv/bin/python scripts/mnq/SND_phase4_backtest.py
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

import pandas as pd

import SND_baseline_backtest as baseline
from SND_html_report import SCRIPT as CHART_SCRIPT
from SND_html_report import comparison_frames, metrics, svg_line_chart
from SND_phase3_screen import month_block_interval


ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data" / "mnq_dom_sample" / "full_history"
DEFAULT_MINUTE = DATA_ROOT / "ohlcv-1m" / "candles_1m.parquet"
DEFAULT_TF_DIR = DATA_ROOT / "ohlcv-resampled"
DEFAULT_PHASE1 = ROOT / "reports" / "SND_baseline"
DEFAULT_PHASE2 = ROOT / "reports" / "SND_phase2"
DEFAULT_PHASE3 = ROOT / "reports" / "SND_phase3"
DEFAULT_OUTPUT = ROOT / "reports" / "SND_phase4"
TIMEZONE = "America/Chicago"
SPLITS = {
    "Train 2019–22": (2019, 2022),
    "Validation 2023–24": (2023, 2024),
    "Holdout 2025–26": (2025, 2026),
}


@dataclass(frozen=True)
class Variant:
    label: str
    slug: str
    description: str
    rule: str


VARIANTS = [
    Variant("1h reference", "01_1h_reference", "Only 1-hour zones are eligible.", "one_hour"),
    Variant("1h · no BOS", "02_1h_no_bos", "Only 1-hour zones without formation BOS.", "no_bos"),
    Variant(
        "1h · RVOL 0.75–1.25", "03_1h_normal_rvol",
        "Formation RVOL must be at least 0.75 and below 1.25.", "normal_rvol",
    ),
    Variant(
        "1h · impulse/prior volume <0.75", "04_1h_low_impulse_volume",
        "Impulse-candle volume must be below 75% of the preceding source candle.",
        "low_impulse_volume",
    ),
    Variant(
        "1h · first SND test", "05_1h_first_SND_test",
        "A zone is eligible only before its first selected SND test.", "first_SND_test",
    ),
    Variant(
        "1h · first physical touch", "06_1h_first_physical_touch",
        "A zone is eligible only during its first continuous physical overlap episode.",
        "first_physical_touch",
    ),
    Variant(
        "1h · width ≤0.5 ATR", "07_1h_tight_zone",
        "Zone width must be no greater than half the formation ATR.", "tight_zone",
    ),
    Variant(
        "1h · opposing room ≥2R/open", "08_1h_open_room",
        "Nearest active opposing zone must be at least two structural R away, or absent.",
        "open_room",
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--one-minute", type=Path, default=DEFAULT_MINUTE)
    parser.add_argument("--timeframe-dir", type=Path, default=DEFAULT_TF_DIR)
    parser.add_argument("--phase1-dir", type=Path, default=DEFAULT_PHASE1)
    parser.add_argument("--phase2-dir", type=Path, default=DEFAULT_PHASE2)
    parser.add_argument("--phase3-dir", type=Path, default=DEFAULT_PHASE3)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--point-value", type=float, default=2.0)
    parser.add_argument("--cost-ticks", type=float, default=0.0)
    parser.add_argument(
        "--reuse-ledgers", action="store_true",
        help="rebuild metrics/HTML from existing Phase 4 trade ledgers",
    )
    return parser.parse_args()


def simulation_args(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        body_ratio=0.50,
        max_zones=50,
        max_tests=2,
        bounce_points=75.0,
        min_zone_age_bars=1,
        min_bars_between_tests=5,
        min_bars_in_trade=1,
        stop_cap_points=100.0,
        zone_stop_buffer_points=1.0,
        point_value=args.point_value,
        cost_ticks=args.cost_ticks,
    )


def validate_zone_identity(
    zones: list[baseline.Zone],
    features: pd.DataFrame,
) -> pd.DataFrame:
    lookup = features.set_index("zone_id", verify_integrity=True).sort_index()
    if len(zones) != len(lookup):
        raise ValueError(f"Zone count mismatch: detected={len(zones)} Phase2={len(lookup)}")
    labels = {"1h": "1h", "4h": "4h", "1d": "Daily"}
    for zone in zones:
        row = lookup.loc[zone.zone_id]
        same = (
            labels[zone.timeframe] == row.timeframe
            and zone.direction == row.direction
            and zone.formed_at == row.formed_at
            and math.isclose(zone.proximal, row.proximal)
            and math.isclose(zone.distal, row.distal)
        )
        if not same:
            raise ValueError(f"Phase 2 feature identity mismatch for zone {zone.zone_id}")
    return lookup


def opposing_room_is_open(
    zone: baseline.Zone,
    active_long: list[baseline.Zone],
    active_short: list[baseline.Zone],
) -> bool:
    if zone.direction == "long":
        distances = [
            other.proximal - zone.proximal
            for other in active_short
            if other.proximal > zone.proximal
        ]
    else:
        distances = [
            zone.proximal - other.proximal
            for other in active_long
            if other.proximal < zone.proximal
        ]
    if not distances:
        return True
    structural_risk = zone.width + 1.0
    return min(distances) / structural_risk >= 2.0


def make_filter(
    variant: Variant,
    features: pd.DataFrame,
) -> Callable[[baseline.Zone, list[baseline.Zone], list[baseline.Zone]], bool]:
    def entry_filter(
        zone: baseline.Zone,
        active_long: list[baseline.Zone],
        active_short: list[baseline.Zone],
    ) -> bool:
        if zone.timeframe != "1h":
            return False
        row = features.loc[zone.zone_id]
        if variant.rule == "one_hour":
            return True
        if variant.rule == "no_bos":
            return not bool(row.bos)
        if variant.rule == "normal_rvol":
            return pd.notna(row.formation_rvol) and 0.75 <= row.formation_rvol < 1.25
        if variant.rule == "low_impulse_volume":
            return row.prior_volume > 0 and row.formation_volume / row.prior_volume < 0.75
        if variant.rule == "first_SND_test":
            return zone.test_count == 0
        if variant.rule == "first_physical_touch":
            return zone.physical_touch_count == 1
        if variant.rule == "tight_zone":
            return pd.notna(row.zone_width_atr) and row.zone_width_atr <= 0.5
        if variant.rule == "open_room":
            return opposing_room_is_open(zone, active_long, active_short)
        raise ValueError(f"Unknown rule: {variant.rule}")

    return entry_filter


def common_calendar(series: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    starts = []
    ends = []
    for frame in series.values():
        local = frame.exit_time.dt.tz_convert(TIMEZONE).dt.tz_localize(None).dt.normalize()
        starts.append(local.min())
        ends.append(local.max())
    return pd.bdate_range(min(starts), max(ends))


def split_calendar(calendar: pd.DatetimeIndex, split: str) -> pd.DatetimeIndex:
    if split == "Overall":
        return calendar
    start, end = SPLITS[split]
    return calendar[(calendar.year >= start) & (calendar.year <= end)]


def metric_rows(series: dict[str, pd.DataFrame]) -> pd.DataFrame:
    calendar = common_calendar(series)
    rows = []
    for label, frame in series.items():
        for split in ["Overall", *SPLITS]:
            if split == "Overall":
                selected = frame
            else:
                start, end = SPLITS[split]
                selected = frame.loc[frame.entry_year.between(start, end)]
            values = metrics(selected, split_calendar(calendar, split))
            ci_low, ci_high = month_block_interval(
                selected, 2_000, f"phase4|{label}|{split}"
            )
            rows.append({
                "variant": label, "split": split,
                "avg_points_ci_low": ci_low, "avg_points_ci_high": ci_high,
                **values,
            })
    return pd.DataFrame(rows)


def classify(table: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for variant, group in table.groupby("variant", sort=False):
        values = group.set_index("split")
        overall = values.loc["Overall"]
        train = values.loc["Train 2019–22"]
        validation = values.loc["Validation 2023–24"]
        holdout = values.loc["Holdout 2025–26"]
        enough = min(validation.trades, holdout.trades) >= 100
        positive = lambda row: row.profit_factor > 1 and row.sharpe > 0
        if variant == "SND baseline":
            status = "control"
        elif not enough:
            status = "limited sample"
        elif (
            positive(train) and positive(validation) and positive(holdout)
            and train.avg_points_ci_low > 0
            and validation.avg_points_ci_low > 0
            and holdout.avg_points_ci_low > 0
        ):
            status = "validated full simulation"
        elif positive(train) and positive(validation) and positive(holdout):
            status = "positive all periods; uncertainty remains"
        elif positive(validation) and positive(holdout):
            status = "promising full simulation"
        elif positive(holdout):
            status = "mixed; holdout positive"
        else:
            status = "not supported"
        rows.append({
            "variant": variant,
            "status": status,
            "overall_trades": int(overall.trades),
            "overall_profit_factor": overall.profit_factor,
            "overall_sharpe": overall.sharpe,
            "overall_pnl": overall.total_pnl,
            "train_profit_factor": train.profit_factor,
            "validation_profit_factor": validation.profit_factor,
            "holdout_profit_factor": holdout.profit_factor,
            "holdout_sharpe": holdout.sharpe,
            "holdout_sortino": holdout.sortino,
            "holdout_pnl": holdout.total_pnl,
            "holdout_trades": int(holdout.trades),
            "holdout_profitable_months": holdout.profitable_months,
            "train_ci_low": train.avg_points_ci_low,
            "validation_ci_low": validation.avg_points_ci_low,
            "holdout_ci_low": holdout.avg_points_ci_low,
            "holdout_ci_high": holdout.avg_points_ci_high,
        })
    return pd.DataFrame(rows)


def screen_comparison(
    full_metrics: pd.DataFrame,
    phase3_dir: Path,
) -> pd.DataFrame:
    screen = pd.read_csv(phase3_dir / "experiment_metrics.csv")
    screen = screen.loc[screen.split == "Overall", [
        "experiment", "trades", "profit_factor", "sharpe", "total_pnl"
    ]].rename(columns={
        "experiment": "variant", "trades": "screen_trades",
        "profit_factor": "screen_profit_factor", "sharpe": "screen_sharpe",
        "total_pnl": "screen_pnl",
    })
    full = full_metrics.loc[full_metrics.split == "Overall", [
        "variant", "trades", "profit_factor", "sharpe", "total_pnl"
    ]].rename(columns={
        "trades": "full_trades", "profit_factor": "full_profit_factor",
        "sharpe": "full_sharpe", "total_pnl": "full_pnl",
    })
    return full.merge(screen, on="variant", how="left", validate="one_to_one")


def cost_sensitivity(
    series: dict[str, pd.DataFrame],
    point_value: float,
) -> pd.DataFrame:
    calendar = common_calendar(series)
    rows = []
    for label, frame in series.items():
        for ticks in (0, 1, 2, 4):
            adjusted = frame.copy()
            adjusted["pnl"] = (
                adjusted["gross_pnl"] - ticks * baseline.TICK_SIZE * point_value
            )
            values = metrics(adjusted, calendar)
            rows.append({
                "variant": label,
                "round_trip_cost_ticks": ticks,
                "profit_factor": values["profit_factor"],
                "total_pnl": values["total_pnl"],
                "sharpe": values["sharpe"],
                "max_drawdown": values["max_drawdown"],
            })
    return pd.DataFrame(rows)


def fmt(value: float, kind: str = "number") -> str:
    if pd.isna(value):
        return "n/a"
    if kind == "integer":
        return f"{int(value):,}"
    if kind == "money":
        sign = "−" if value < 0 else ""
        return f"{sign}${abs(value):,.0f}"
    if kind == "percent":
        return f"{value:.1%}"
    return f"{value:.2f}"


def verdict_html(verdicts: pd.DataFrame) -> str:
    body = []
    for row in verdicts.itertuples(index=False):
        body.append(
            f"<tr><th>{html.escape(row.variant)}</th><td>{html.escape(row.status)}</td>"
            f"<td>{row.overall_trades:,}</td><td>{row.overall_profit_factor:.2f}</td>"
            f"<td>{row.overall_sharpe:.2f}</td><td>{fmt(row.overall_pnl, 'money')}</td>"
            f"<td>{row.train_profit_factor:.2f}</td><td>{row.validation_profit_factor:.2f}</td>"
            f"<td>{row.holdout_profit_factor:.2f}</td><td>{row.holdout_sharpe:.2f}</td>"
            f"<td>{row.holdout_sortino:.2f}</td><td>{fmt(row.holdout_pnl, 'money')}</td>"
            f"<td>{row.holdout_ci_low:.2f} to {row.holdout_ci_high:.2f}</td>"
            f"<td>{row.holdout_trades:,}</td><td>{row.holdout_profitable_months:.1%}</td></tr>"
        )
    return """<div class='table-wrap'><table><thead><tr><th>Variant</th><th>Status</th>
    <th>Trades</th><th>Overall PF</th><th>Overall Sharpe</th><th>Overall P&amp;L</th>
    <th>Train PF</th><th>Validation PF</th><th>Holdout PF</th><th>Holdout Sharpe</th>
    <th>Holdout Sortino</th><th>Holdout P&amp;L</th><th>Holdout 95% interval</th><th>Holdout trades</th>
    <th>Profitable months</th></tr></thead><tbody>""" + "".join(body) + "</tbody></table></div>"


def comparison_html(comparison: pd.DataFrame) -> str:
    body = []
    for row in comparison.itertuples(index=False):
        body.append(
            f"<tr><th>{html.escape(row.variant)}</th>"
            f"<td>{fmt(row.screen_trades, 'integer')}</td><td>{fmt(row.full_trades, 'integer')}</td>"
            f"<td>{fmt(row.screen_profit_factor)}</td><td>{fmt(row.full_profit_factor)}</td>"
            f"<td>{fmt(row.screen_sharpe)}</td><td>{fmt(row.full_sharpe)}</td>"
            f"<td>{fmt(row.screen_pnl, 'money')}</td><td>{fmt(row.full_pnl, 'money')}</td></tr>"
        )
    return """<div class='table-wrap'><table><thead><tr><th>Variant</th>
    <th>Screen trades</th><th>Full trades</th><th>Screen PF</th><th>Full PF</th>
    <th>Screen Sharpe</th><th>Full Sharpe</th><th>Screen P&amp;L</th><th>Full P&amp;L</th>
    </tr></thead><tbody>""" + "".join(body) + "</tbody></table></div>"


def cost_html(costs: pd.DataFrame) -> str:
    profit_factor = costs.pivot(index="variant", columns="round_trip_cost_ticks", values="profit_factor")
    pnl = costs.loc[costs.round_trip_cost_ticks == 2].set_index("variant")["total_pnl"]
    body = []
    for variant, row in profit_factor.iterrows():
        body.append(
            f"<tr><th>{html.escape(variant)}</th>"
            + "".join(f"<td>{row[ticks]:.2f}</td>" for ticks in (0, 1, 2, 4))
            + f"<td>{fmt(pnl.loc[variant], 'money')}</td></tr>"
        )
    return """<div class='table-wrap'><table><thead><tr><th>Variant</th>
    <th>PF · 0 ticks</th><th>PF · 1 tick</th><th>PF · 2 ticks</th><th>PF · 4 ticks</th>
    <th>P&amp;L · 2 ticks</th></tr></thead><tbody>""" + "".join(body) + "</tbody></table></div>"


STYLE = """
:root{color-scheme:light;--bg:#f5f6f8;--panel:#fff;--panel2:#f0f2f5;--text:#111827;--muted:#687386;--border:#dfe3e8;--accent:#4c8bf5}
@media(prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#101216;--panel:#181b21;--panel2:#22262e;--text:#f4f6f8;--muted:#9aa4b2;--border:#303640;--accent:#70a4ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.wrap{max-width:1320px;margin:auto;padding:36px 22px 80px}.eyebrow{text-transform:uppercase;letter-spacing:.11em;font-size:11px;font-weight:700;color:var(--accent)}h1{font-size:32px;letter-spacing:-.035em;margin:6px 0}h2{font-size:21px;margin:38px 0 4px}h3{font-size:15px;margin:0}.lead,.note{color:var(--muted);max-width:950px}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:10px;margin:20px 0}.tile,.method,.figure{background:var(--panel);border:1px solid var(--border);border-radius:11px;padding:14px 16px}.tile span{display:block;color:var(--muted);font-size:11px;text-transform:uppercase}.tile strong{display:block;font-size:22px;margin-top:3px}.table-wrap{overflow:auto;border:1px solid var(--border);border-radius:10px;background:var(--panel);margin:12px 0}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{padding:8px 11px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}thead th{background:var(--panel2);color:var(--muted);font-size:10px;text-transform:uppercase}thead th:first-child,tbody th{text-align:left}tbody tr:last-child>*{border-bottom:0}.figure{margin:12px 0}.figure figcaption p{color:var(--muted);font-size:12px;margin:3px 0}.legend{display:flex;gap:14px;flex-wrap:wrap;margin:10px 0;color:var(--muted);font-size:12px}.legend span{display:flex;align-items:center;gap:5px}.legend i{width:18px;height:3px}.plot{position:relative;overflow:auto}.chart{width:100%;min-width:760px;display:block}.grid{stroke:var(--border)}.zero{stroke:var(--muted);stroke-dasharray:4 4}.tick{fill:var(--muted);font-size:11px}.series-line{stroke-width:2}.hitbox{fill:transparent;pointer-events:all}.crosshair{stroke:var(--muted);stroke-dasharray:3 3}.tooltip{position:absolute;pointer-events:none;background:var(--text);color:var(--bg);font-size:12px;padding:8px 10px;border-radius:7px;white-space:nowrap}.method li{margin:7px 0}code{background:var(--panel2);padding:2px 5px;border-radius:4px}a{color:var(--accent)}
"""


def write_report(
    series: dict[str, pd.DataFrame],
    full_metrics: pd.DataFrame,
    verdicts: pd.DataFrame,
    comparison: pd.DataFrame,
    costs: pd.DataFrame,
    args: argparse.Namespace,
) -> None:
    equity, drawdown, rolling, annual = comparison_frames(series)
    equity.to_csv(args.output_dir / "daily_equity.csv")
    drawdown.to_csv(args.output_dir / "daily_drawdown.csv")
    rolling.to_csv(args.output_dir / "rolling_90d_expectancy.csv")
    annual.to_csv(args.output_dir / "annual_pnl.csv")
    full_metrics.to_csv(args.output_dir / "metrics_by_split.csv", index=False)
    verdicts.to_csv(args.output_dir / "verdicts.csv", index=False)
    comparison.to_csv(args.output_dir / "screen_vs_full.csv", index=False)
    costs.to_csv(args.output_dir / "cost_sensitivity.csv", index=False)
    validated = int((verdicts.status == "validated full simulation").sum())
    stable = int((verdicts.status == "positive all periods; uncertainty remains").sum())
    promising = int((verdicts.status == "promising full simulation").sum())
    best = verdicts.loc[verdicts.variant != "SND baseline"].sort_values(
        ["holdout_sharpe", "overall_sharpe"], ascending=False
    ).iloc[0]
    summary = {
        "variants": len(series) - 1,
        "validated_full_simulations": validated,
        "positive_all_periods": stable,
        "promising_full_simulations": promising,
        "best_holdout_variant": best.variant,
        "best_holdout_sharpe": float(best.holdout_sharpe),
        "best_holdout_profit_factor": float(best.holdout_profit_factor),
        "cost_ticks": args.cost_ticks,
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    tiles = "".join(
        f"<div class='tile'><span>{label}</span><strong>{value}</strong></div>"
        for label, value in [
            ("Full variants", len(series) - 1), ("Validated", validated),
            ("Positive all periods", stable),
            ("Promising", promising), ("Best holdout", best.variant),
            ("Best holdout PF", f"{best.holdout_profit_factor:.2f}"),
            ("Best holdout Sharpe", f"{best.holdout_sharpe:.2f}"),
        ]
    )
    descriptions = "".join(
        f"<li><strong>{html.escape(item.label)}:</strong> {html.escape(item.description)}</li>"
        for item in VARIANTS
    )
    page = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
    <title>SND Phase 4 full simulations</title><style>{STYLE}</style></head><body><main class='wrap'>
    <div class='eyebrow'>MNQ · SND strategy lab</div><h1>Phase 4 full strategy simulations</h1>
    <p class='lead'>Each Phase 3 candidate is independently re-run through SND's one-minute engine. Zone priority, skipped entries, replacement signals, rearming, stops, targets, and timed closes are recalculated.</p>
    <div class='tiles'>{tiles}</div>
    <h2>Full-simulation verdicts</h2><p class='note'>A validated result must have PF above 1, positive daily Sharpe, and a month-block expectancy interval above zero in train, validation, and holdout. Headline results are before costs.</p>
    {verdict_html(verdicts)}
    <h2>Equity and stability</h2>
    {svg_line_chart(equity, 'Cumulative full-simulation P&L', 'MNQ dollars before costs.', 'money')}
    {svg_line_chart(drawdown, 'Daily drawdown', 'Distance below the prior daily equity peak.', 'money')}
    {svg_line_chart(rolling, 'Rolling 90-day expectancy', 'Points per trade over trailing calendar time.', 'number')}
    <h2>Why the Phase 3 and Phase 4 numbers differ</h2><p class='note'>Phase 3 merely removed trades from the original ledger. Phase 4 recalculates the entire event path after every rejection.</p>
    {comparison_html(comparison)}
    <h2>Cost sensitivity</h2><p class='note'>Round-trip friction is expressed in 0.25-point MNQ ticks and applied to every completed trade. Two ticks equal $1 per contract.</p>
    {cost_html(costs)}
    <h2>Rule definitions</h2><div class='method'><ul>{descriptions}</ul></div>
    <p class='note'><a href='../SND_dashboard/index.html'>Main dashboard</a> · <a href='../SND_phase3/index.html'>Phase 3 screen</a></p>
    </main><script>{CHART_SCRIPT}</script></body></html>"""
    (args.output_dir / "index.html").write_text(page)


def main() -> None:
    args = parse_args()
    sim_args = simulation_args(args)
    control = pd.read_parquet(args.phase1_dir / "trades.parquet").sort_values("exit_time")
    for column in ("entry_time", "exit_time"):
        control[column] = pd.to_datetime(control[column], utc=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    series: dict[str, pd.DataFrame] = {"SND baseline": control}
    audits: dict[str, dict[str, int]] = {}
    if args.reuse_ledgers:
        print("Reusing existing Phase 4 ledgers...", flush=True)
        for variant in VARIANTS:
            trades = pd.read_parquet(args.output_dir / variant.slug / "trades.parquet")
            series[variant.label] = trades.sort_values("exit_time")
    else:
        print("Loading one-minute data and source timeframes...", flush=True)
        minute = baseline.load_bars(args.one_minute)
        frames = {
            timeframe: baseline.load_bars(args.timeframe_dir / f"candles_{timeframe}.parquet")
            for timeframe in ("1h", "4h", "1d")
        }
        print("Detecting and verifying zones against Phase 2...", flush=True)
        template_zones = baseline.detect_zones(frames, minute.index, sim_args.body_ratio)
        phase2 = pd.read_parquet(args.phase2_dir / "zones_enriched.parquet")
        features = validate_zone_identity(template_zones, phase2)
        for number, variant in enumerate(VARIANTS, start=1):
            print(f"[{number}/{len(VARIANTS)}] Simulating {variant.label}...", flush=True)
            zones = copy.deepcopy(template_zones)
            trades, tests, audit = baseline.simulate(
                minute, zones, None, None, sim_args, make_filter(variant, features)
            )
            if trades.empty:
                raise ValueError(f"Variant produced no trades: {variant.label}")
            variant_dir = args.output_dir / variant.slug
            variant_dir.mkdir(exist_ok=True)
            trades.to_parquet(variant_dir / "trades.parquet", index=False)
            tests.to_parquet(variant_dir / "zone_tests.parquet", index=False)
            (variant_dir / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
            series[variant.label] = trades.sort_values("exit_time")
            audits[variant.label] = audit
            print(f"  {len(trades):,} trades", flush=True)
        (args.output_dir / "audits.json").write_text(json.dumps(audits, indent=2) + "\n")
    full_metrics = metric_rows(series)
    verdicts = classify(full_metrics)
    comparison = screen_comparison(full_metrics, args.phase3_dir)
    costs = cost_sensitivity(series, args.point_value)
    print("Writing Phase 4 HTML report...", flush=True)
    write_report(series, full_metrics, verdicts, comparison, costs, args)
    print(
        f"DONE | variants={len(VARIANTS)} | "
        f"validated={(verdicts.status == 'validated full simulation').sum()} | "
        f"positive_all={(verdicts.status == 'positive all periods; uncertainty remains').sum()} | "
        f"promising={(verdicts.status == 'promising full simulation').sum()} "
        f"-> {args.output_dir}"
    )


if __name__ == "__main__":
    main()
