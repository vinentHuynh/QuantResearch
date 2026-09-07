"""Build an offline HTML dashboard for SND strategy experiments.

The report keeps a small series registry so future strategy variants can be
added as comparison lines without changing the dashboard code.

Create/update the baseline dashboard:

    .venv/bin/python scripts/mnq/SND_html_report.py

Add a future experiment and retain all existing lines:

    .venv/bin/python scripts/mnq/SND_html_report.py \
        --series "BOS filter=reports/SND_bos/trades.parquet"
"""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "reports" / "SND_dashboard"
DEFAULT_BASELINE = ROOT / "reports" / "SND_baseline" / "trades.parquet"
DEFAULT_WINDOW = ROOT / "reports" / "SND_baseline_2026_window" / "trades.parquet"
DEFAULT_PHASE2 = ROOT / "reports" / "SND_phase2" / "summary.json"
DEFAULT_PHASE3 = ROOT / "reports" / "SND_phase3" / "summary.json"
DEFAULT_PHASE4 = ROOT / "reports" / "SND_phase4" / "summary.json"
DEFAULT_PHASE5 = ROOT / "reports" / "SND_phase5" / "summary.json"
DEFAULT_PHASE6 = ROOT / "reports" / "SND_phase6" / "summary.json"
TZ = "America/Chicago"
COLORS = [
    "#4c8bf5", "#16a085", "#f39c12", "#9b59b6", "#e74c3c", "#00a8a8",
    "#7f8c8d", "#d35400", "#2c3e50", "#c0397b", "#6c8e23", "#8e6bbf",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--series",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="add or replace a registered strategy line; may be repeated",
    )
    parser.add_argument(
        "--remove-series",
        action="append",
        default=[],
        metavar="LABEL",
        help="remove a registered strategy line; may be repeated",
    )
    parser.add_argument(
        "--reset-series",
        action="store_true",
        help="reset the registry to the SND baseline before applying --series",
    )
    return parser.parse_args()


def portable_path(path: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return (ROOT / path).resolve() if not path.is_absolute() else path.resolve()


def update_registry(args: argparse.Namespace) -> dict[str, str]:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    registry_path = args.output_dir / "series.json"
    if args.reset_series or not registry_path.exists():
        registry = {"SND baseline": portable_path(DEFAULT_BASELINE)}
    else:
        registry = json.loads(registry_path.read_text())
        if not isinstance(registry, dict):
            raise ValueError(f"Invalid series registry: {registry_path}")

    for label in args.remove_series:
        registry.pop(label, None)
    for item in args.series:
        if "=" not in item:
            raise ValueError(f"--series must be LABEL=PATH, received: {item!r}")
        label, raw_path = item.split("=", 1)
        label = label.strip()
        if not label or not raw_path.strip():
            raise ValueError(f"--series must be LABEL=PATH, received: {item!r}")
        registry[label] = portable_path(resolve_path(raw_path.strip()))

    if not registry:
        raise ValueError("The report needs at least one registered series")
    if len(registry) > len(COLORS):
        raise ValueError(f"At most {len(COLORS)} strategy lines are supported")
    registry_path.write_text(json.dumps(registry, indent=2) + "\n")
    return registry


def load_trades(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Trade ledger not found: {path}")
    frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    required = {"entry_time", "exit_time", "points", "r_multiple", "pnl"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{path} is missing columns: {missing}")
    for column in ("entry_time", "exit_time"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    frame = frame.sort_values("exit_time").reset_index(drop=True)
    if frame.empty:
        raise ValueError(f"Trade ledger is empty: {path}")
    return frame


def maximum_drawdown(pnl: pd.Series) -> float:
    equity = pnl.cumsum()
    peaks = equity.cummax().clip(lower=0.0)
    return float((equity - peaks).min())


def daily_risk_metrics(
    frame: pd.DataFrame,
    calendar: pd.DatetimeIndex | None = None,
) -> dict[str, float]:
    dates = local_trade_dates(frame)
    if calendar is None:
        calendar = pd.bdate_range(dates.min(), dates.max())
    daily = frame.assign(trade_date=dates).groupby("trade_date")["pnl"].sum()
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
        "pnl_calmar": annualized_pnl / drawdown if drawdown > 0 else math.nan,
        "annualized_volatility": annualized_volatility,
        "profitable_months": float((monthly > 0).mean()) if len(monthly) else math.nan,
    }


def metrics(
    frame: pd.DataFrame,
    calendar: pd.DatetimeIndex | None = None,
) -> dict[str, float]:
    wins = frame["pnl"] >= 0
    gross_win = frame.loc[frame["pnl"] > 0, "pnl"].sum()
    gross_loss = -frame.loc[frame["pnl"] < 0, "pnl"].sum()
    return {
        "trades": float(len(frame)),
        "win_rate": float(wins.mean()),
        "avg_points": float(frame["points"].mean()),
        "total_points": float(frame["points"].sum()),
        "avg_r": float(frame["r_multiple"].mean()),
        "total_pnl": float(frame["pnl"].sum()),
        "profit_factor": float(gross_win / gross_loss) if gross_loss else math.nan,
        "max_drawdown": maximum_drawdown(frame["pnl"]),
        **daily_risk_metrics(frame, calendar),
    }


def local_trade_dates(frame: pd.DataFrame) -> pd.DatetimeIndex:
    local = frame["exit_time"].dt.tz_convert(TZ)
    return pd.DatetimeIndex(local.dt.tz_localize(None).dt.normalize())


def comparison_frames(
    series: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    daily_data: dict[str, pd.DataFrame] = {}
    first = min(local_trade_dates(frame).min() for frame in series.values())
    last = max(local_trade_dates(frame).max() for frame in series.values())
    calendar = pd.date_range(first, last, freq="D")

    equity = pd.DataFrame(index=calendar)
    drawdown = pd.DataFrame(index=calendar)
    rolling = pd.DataFrame(index=calendar)
    annual = pd.DataFrame()

    for label, frame in series.items():
        work = frame.copy()
        work["trade_date"] = local_trade_dates(work)
        daily = work.groupby("trade_date").agg(
            pnl=("pnl", "sum"), points=("points", "sum"), trades=("pnl", "size")
        )
        own_calendar = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
        daily = daily.reindex(own_calendar, fill_value=0)
        curve = daily["pnl"].cumsum()
        dd = curve - curve.cummax().clip(lower=0.0)
        rolling_points = daily["points"].rolling(90, min_periods=20).sum() / daily[
            "trades"
        ].rolling(90, min_periods=20).sum().replace(0, np.nan)
        equity.loc[own_calendar, label] = curve
        drawdown.loc[own_calendar, label] = dd
        rolling.loc[own_calendar, label] = rolling_points

        annual_values = work.groupby(work["exit_time"].dt.tz_convert(TZ).dt.year)["pnl"].sum()
        annual[label] = annual_values
        daily_data[label] = daily

    equity.index.name = drawdown.index.name = rolling.index.name = "date"
    annual.index.name = "year"
    return equity, drawdown, rolling, annual.sort_index()


def fmt(value: float, kind: str = "number") -> str:
    if value is None or not math.isfinite(float(value)):
        return "n/a"
    if kind == "money":
        sign = "-" if value < 0 else ""
        return f"{sign}${abs(value):,.0f}"
    if kind == "percent":
        return f"{value:.1%}"
    if kind == "integer":
        return f"{value:,.0f}"
    if kind == "pf":
        return f"{value:.2f}"
    return f"{value:,.2f}"


def css_class(value: float) -> str:
    return "pos" if value > 0 else "neg" if value < 0 else ""


def svg_line_chart(
    frame: pd.DataFrame,
    title: str,
    subtitle: str,
    value_kind: str,
    zero_line: bool = True,
) -> str:
    data = frame.dropna(how="all")
    columns = [column for column in data.columns if data[column].notna().any()]
    if data.empty or not columns:
        return "<p class='empty'>No chart data.</p>"

    width, height = 1100, 360
    left, right, top, bottom = 78, 170, 18, 42
    plot_width = width - left - right
    plot_height = height - top - bottom
    values = data[columns].to_numpy(dtype=float)
    finite = values[np.isfinite(values)]
    low, high = float(finite.min()), float(finite.max())
    if zero_line:
        low, high = min(low, 0.0), max(high, 0.0)
    if low == high:
        low -= 1.0
        high += 1.0
    pad = (high - low) * 0.07
    low, high = low - pad, high + pad

    def x_at(position: int) -> float:
        return left + plot_width * position / max(len(data) - 1, 1)

    def y_at(value: float) -> float:
        return top + plot_height * (high - value) / (high - low)

    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img" aria-label="{html.escape(title)}">']
    for tick in range(5):
        value = low + (high - low) * tick / 4
        y = y_at(value)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" class="tick">{html.escape(fmt(value, value_kind))}</text>')
    if low < 0 < high:
        y = y_at(0.0)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}" class="zero"/>')

    for tick in range(5):
        position = round((len(data) - 1) * tick / 4)
        label = data.index[position].strftime("%Y-%m")
        parts.append(f'<text x="{x_at(position):.1f}" y="{height - 13}" text-anchor="middle" class="tick">{label}</text>')

    payload_series = []
    for number, column in enumerate(columns):
        color = COLORS[number]
        points = []
        payload_values = []
        for position, value in enumerate(data[column].to_numpy(dtype=float)):
            payload_values.append(None if not math.isfinite(value) else round(float(value), 6))
            if math.isfinite(value):
                points.append(f"{x_at(position):.2f},{y_at(value):.2f}")
        parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" class="series-line"/>')
        last_position = int(np.flatnonzero(data[column].notna().to_numpy())[-1])
        last_value = float(data[column].iloc[last_position])
        parts.append(f'<circle cx="{x_at(last_position):.1f}" cy="{y_at(last_value):.1f}" r="3.5" fill="{color}"/>')
        payload_series.append({"label": column, "values": payload_values, "color": color})
    parts.append(f'<line x1="0" y1="{top}" x2="0" y2="{top + plot_height}" class="crosshair" hidden/>')
    parts.append(f'<rect x="{left}" y="{top}" width="{plot_width}" height="{plot_height}" class="hitbox"/>')
    parts.append("</svg>")

    legend = "".join(
        f'<span><i style="background:{COLORS[i]}"></i>{html.escape(column)}</span>'
        for i, column in enumerate(columns)
    )
    payload = {
        "dates": [value.strftime("%Y-%m-%d") for value in data.index],
        "series": payload_series,
        "left": left,
        "plotWidth": plot_width,
        "kind": value_kind,
    }
    return (
        f'<figure class="figure" data-chart="{html.escape(json.dumps(payload), quote=True)}">'
        f'<figcaption><h3>{html.escape(title)}</h3><p>{html.escape(subtitle)}</p></figcaption>'
        f'<div class="legend">{legend}</div><div class="plot">{"".join(parts)}'
        '<div class="tooltip" hidden></div></div></figure>'
    )


def metrics_table(all_metrics: dict[str, dict[str, float]]) -> str:
    fields = [
        ("trades", "Trades", "integer"),
        ("win_rate", "Win rate", "percent"),
        ("avg_points", "Avg points", "number"),
        ("avg_r", "Avg R", "number"),
        ("total_pnl", "Total P&L", "money"),
        ("profit_factor", "Profit factor", "pf"),
        ("max_drawdown", "Max drawdown", "money"),
        ("sharpe", "Daily Sharpe", "number"),
        ("sortino", "Daily Sortino", "number"),
        ("pnl_calmar", "P&L Calmar", "number"),
        ("annualized_volatility", "Annualized volatility", "money"),
        ("profitable_months", "Profitable months", "percent"),
    ]
    header = "".join(f"<th>{html.escape(label)}</th>" for label in all_metrics)
    rows = []
    for key, title, kind in fields:
        cells = []
        for values in all_metrics.values():
            value = values[key]
            cells.append(f'<td class="{css_class(value) if key in {"avg_points", "avg_r", "total_pnl", "max_drawdown"} else ""}">{fmt(value, kind)}</td>')
        rows.append(f"<tr><th>{title}</th>{''.join(cells)}</tr>")
    return f'<div class="table-wrap"><table><thead><tr><th>Metric</th>{header}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def dataframe_table(frame: pd.DataFrame, money: bool = False) -> str:
    if frame.empty:
        return "<p class='empty'>No data.</p>"
    header = "".join(f"<th>{html.escape(str(column))}</th>" for column in frame.columns)
    rows = []
    for index, row in frame.iterrows():
        cells = []
        for value in row:
            number = float(value) if pd.notna(value) else math.nan
            kind = "money" if money else "number"
            cells.append(f'<td class="{css_class(number) if math.isfinite(number) else ""}">{fmt(number, kind)}</td>')
        rows.append(f"<tr><th>{html.escape(str(index))}</th>{''.join(cells)}</tr>")
    return f'<div class="table-wrap"><table><thead><tr><th>{html.escape(frame.index.name or "Group")}</th>{header}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def breakdown_table(frame: pd.DataFrame, column: str) -> str:
    rows = []
    for label, group in frame.groupby(column, sort=True):
        values = metrics(group)
        rows.append({
            column: label,
            "Trades": int(values["trades"]),
            "Win rate": values["win_rate"],
            "Avg points": values["avg_points"],
            "Avg R": values["avg_r"],
            "PF": values["profit_factor"],
            "P&L": values["total_pnl"],
        })
    data = pd.DataFrame(rows).set_index(column)
    headers = "".join(f"<th>{html.escape(str(value))}</th>" for value in data.columns)
    body = []
    for label, row in data.iterrows():
        cells = [f"<td>{int(row['Trades']):,}</td>", f"<td>{row['Win rate']:.1%}</td>"]
        for key in ("Avg points", "Avg R"):
            cells.append(f'<td class="{css_class(row[key])}">{row[key]:.2f}</td>')
        cells.append(f"<td>{fmt(row['PF'], 'pf')}</td>")
        cells.append(f'<td class="{css_class(row["P&L"])}">{fmt(row["P&L"], "money")}</td>')
        body.append(f"<tr><th>{html.escape(str(label))}</th>{''.join(cells)}</tr>")
    return f'<div class="table-wrap"><table><thead><tr><th>{html.escape(column)}</th>{headers}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def window_panel() -> str:
    if not DEFAULT_WINDOW.exists():
        return ""
    frame = load_trades(DEFAULT_WINDOW)
    values = metrics(frame)
    return f"""
    <section>
      <div class="section-head"><div><div class="eyebrow">Configured Pine window</div>
      <h2>January–May 2026 check</h2></div></div>
      <div class="tiles compact">
        <div class="tile"><span>Trades</span><strong>{fmt(values['trades'], 'integer')}</strong></div>
        <div class="tile"><span>Win rate</span><strong>{fmt(values['win_rate'], 'percent')}</strong></div>
        <div class="tile"><span>Average</span><strong class="{css_class(values['avg_points'])}">{fmt(values['avg_points'])} pts</strong></div>
        <div class="tile"><span>Profit factor</span><strong>{fmt(values['profit_factor'], 'pf')}</strong></div>
        <div class="tile"><span>Total P&amp;L</span><strong class="{css_class(values['total_pnl'])}">{fmt(values['total_pnl'], 'money')}</strong></div>
      </div>
      <p class="note">This short window is shown for comparison with SND's configured date range. It is not used as a separate strategy line.</p>
    </section>"""


def phase2_panel() -> str:
    if not DEFAULT_PHASE2.exists():
        return ""
    values = json.loads(DEFAULT_PHASE2.read_text())
    return f"""
    <section>
      <div class="section-head"><div><div class="eyebrow">Research layer</div>
      <h2>Phase 2 feature dataset</h2></div></div>
      <div class="tiles compact">
        <div class="tile"><span>Zones</span><strong>{values['zones']:,}</strong></div>
        <div class="tile"><span>Touch episodes</span><strong>{values['retests']:,}</strong></div>
        <div class="tile"><span>Zones retested</span><strong>{values['zones_retested']:,}</strong></div>
        <div class="tile"><span>BOS zones</span><strong>{values['bos_zones']:,}</strong></div>
        <div class="tile"><span>FVG zones</span><strong>{values['fvg_zones']:,}</strong></div>
        <div class="tile"><span>HTF nested</span><strong>{values['nested_zones']:,}</strong></div>
      </div>
      <p class="note">This is the point-in-time feature and outcome-label layer, not a new strategy line. <a href="../SND_phase2/index.html">Open the Phase 2 coverage report</a>.</p>
    </section>"""


def phase3_panel() -> str:
    if not DEFAULT_PHASE3.exists():
        return ""
    values = json.loads(DEFAULT_PHASE3.read_text())
    return f"""
    <section>
      <div class="section-head"><div><div class="eyebrow">Univariate research</div>
      <h2>Phase 3 confluence screen</h2></div></div>
      <div class="tiles compact">
        <div class="tile"><span>Trades screened</span><strong>{values['trades_screened']:,}</strong></div>
        <div class="tile"><span>Rules tested</span><strong>{values['experiments']:,}</strong></div>
        <div class="tile"><span>Validated screens</span><strong>{values['validated_screens']:,}</strong></div>
        <div class="tile"><span>Promising screens</span><strong>{values['promising_screens']:,}</strong></div>
        <div class="tile"><span>1h reference PF</span><strong>{values['one_hour_profit_factor']:.2f}</strong></div>
      </div>
      <p class="note">These are one-variable cohort screens, not replacement-strategy backtests. <a href="../SND_phase3/index.html">Open the Phase 3 screen report</a>.</p>
    </section>"""


def phase4_panel() -> str:
    if not DEFAULT_PHASE4.exists():
        return ""
    values = json.loads(DEFAULT_PHASE4.read_text())
    return f"""
    <section>
      <div class="section-head"><div><div class="eyebrow">Full engine reruns</div>
      <h2>Phase 4 strategy simulations</h2></div></div>
      <div class="tiles compact">
        <div class="tile"><span>Variants</span><strong>{values['variants']:,}</strong></div>
        <div class="tile"><span>Validated</span><strong>{values['validated_full_simulations']:,}</strong></div>
        <div class="tile"><span>Positive all periods</span><strong>{values['positive_all_periods']:,}</strong></div>
        <div class="tile"><span>Best holdout</span><strong>{html.escape(values['best_holdout_variant'])}</strong></div>
        <div class="tile"><span>Best holdout PF</span><strong>{values['best_holdout_profit_factor']:.2f}</strong></div>
        <div class="tile"><span>Best holdout Sharpe</span><strong>{values['best_holdout_sharpe']:.2f}</strong></div>
      </div>
      <p class="note">Every line was independently re-simulated through the one-minute strategy engine. <a href="../SND_phase4/index.html">Open the Phase 4 report</a>.</p>
    </section>"""


def phase5_panel() -> str:
    if not DEFAULT_PHASE5.exists():
        return ""
    values = json.loads(DEFAULT_PHASE5.read_text())
    return f"""
    <section>
      <div class="section-head"><div><div class="eyebrow">Controlled combinations</div>
      <h2>Phase 5 robustness research</h2></div></div>
      <div class="tiles compact">
        <div class="tile"><span>Primary combinations</span><strong>{values['primary_combinations']:,}</strong></div>
        <div class="tile"><span>Sensitivity checks</span><strong>{values['sensitivity_checks']:,}</strong></div>
        <div class="tile"><span>Forward candidate</span><strong>{html.escape(values['recommended_for_next_validation'])}</strong></div>
        <div class="tile"><span>Worst-period PF</span><strong>{values['recommendation_worst_period_profit_factor']:.2f}</strong></div>
        <div class="tile"><span>PF at 2 ticks</span><strong>{values['recommendation_two_tick_profit_factor']:.2f}</strong></div>
      </div>
      <p class="note">Combination promotion requires improvement over the first-touch core, not merely positive historical performance. <a href="../SND_phase5/index.html">Open the Phase 5 report</a>.</p>
    </section>"""


def phase6_panel() -> str:
    if not DEFAULT_PHASE6.exists():
        return ""
    values = json.loads(DEFAULT_PHASE6.read_text())
    return f"""
    <section>
      <div class="section-head"><div><div class="eyebrow">Locked implementation</div>
      <h2>Phase 6 validation gates</h2></div></div>
      <div class="tiles compact">
        <div class="tile"><span>Frozen trades</span><strong>{values['historical_trades']:,}</strong></div>
        <div class="tile"><span>Gross PF</span><strong>{values['gross_profit_factor']:.2f}</strong></div>
        <div class="tile"><span>PF at 4 ticks</span><strong>{values['four_tick_profit_factor']:.2f}</strong></div>
        <div class="tile"><span>Pine parity</span><strong>{html.escape(values['pine_parity_status'])}</strong></div>
        <div class="tile"><span>Paper forward</span><strong>{html.escape(values['paper_forward_status'])}</strong></div>
      </div>
      <p class="note">The Phase 5 candidate is frozen; historical stress passes, but code parity and forward evidence are still open. <a href="../SND_phase6/index.html">Open the Phase 6 report</a>.</p>
    </section>"""


STYLE = """
:root{color-scheme:light;--bg:#f5f6f8;--panel:#fff;--panel2:#f0f2f5;--text:#111827;
--muted:#687386;--border:#dfe3e8;--pos:#087f5b;--neg:#cf3b3b;--accent:#4c8bf5}
@media(prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#101216;--panel:#181b21;
--panel2:#22262e;--text:#f4f6f8;--muted:#9aa4b2;--border:#303640;--pos:#42c99a;
--neg:#ff7373;--accent:#70a4ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1280px;margin:auto;padding:36px 22px 80px}.eyebrow{text-transform:uppercase;
letter-spacing:.11em;font-size:11px;font-weight:700;color:var(--accent)}h1{font-size:32px;
line-height:1.15;letter-spacing:-.035em;margin:6px 0}h2{font-size:21px;margin:3px 0}
h3{font-size:15px;margin:0}.lead{max-width:850px;color:var(--muted);font-size:15px;margin:8px 0 0}
.meta{color:var(--muted);font-size:12px;margin-top:8px}.status{display:inline-flex;align-items:center;
gap:7px;margin-top:18px;background:color-mix(in srgb,var(--neg) 10%,var(--panel));color:var(--neg);
border:1px solid color-mix(in srgb,var(--neg) 35%,var(--border));padding:7px 11px;border-radius:999px;font-weight:650}
.status i{width:7px;height:7px;border-radius:50%;background:currentColor}.tiles{display:grid;
grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px;margin:20px 0}.tile{background:var(--panel);
border:1px solid var(--border);border-radius:10px;padding:13px 15px}.tile span{display:block;color:var(--muted);
font-size:11px;text-transform:uppercase;letter-spacing:.06em}.tile strong{display:block;font-size:23px;
letter-spacing:-.025em;margin-top:3px}.tiles.compact .tile strong{font-size:19px}.pos{color:var(--pos)}.neg{color:var(--neg)}
section{margin-top:42px}.section-head{display:flex;align-items:end;justify-content:space-between;margin-bottom:12px}
.figure{margin:12px 0;background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:16px}
.figure figcaption p{color:var(--muted);font-size:12px;margin:3px 0}.legend{display:flex;gap:16px;
flex-wrap:wrap;margin:10px 0 4px;color:var(--muted);font-size:12px}.legend span{display:flex;align-items:center;gap:6px}
.legend i{width:18px;height:3px;border-radius:2px}.plot{position:relative;overflow-x:auto}.chart{width:100%;min-width:720px;height:auto;display:block}
.grid{stroke:var(--border);stroke-width:1}.zero{stroke:var(--muted);stroke-width:1;stroke-dasharray:4 4}
.tick{fill:var(--muted);font-size:11px}.series-line{stroke-width:2.1;vector-effect:non-scaling-stroke}
.hitbox{fill:transparent;pointer-events:all}.crosshair{stroke:var(--muted);stroke-width:1;stroke-dasharray:3 3}
.tooltip{position:absolute;pointer-events:none;background:var(--text);color:var(--bg);font-size:12px;
line-height:1.55;padding:8px 10px;border-radius:7px;box-shadow:0 5px 20px #0003;white-space:nowrap;z-index:3}
.table-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:10px;background:var(--panel);margin:12px 0}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{padding:8px 12px;
border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}thead th{background:var(--panel2);
color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em}thead th:first-child,
tbody th{text-align:left}tbody th{font-weight:550}tbody tr:last-child th,tbody tr:last-child td{border-bottom:0}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}.note{color:var(--muted);font-size:12px;
max-width:900px}.method{background:var(--panel);border:1px solid var(--border);border-radius:10px;
padding:14px 16px;color:var(--muted)}code{background:var(--panel2);padding:2px 5px;border-radius:4px}
footer{margin-top:42px;border-top:1px solid var(--border);padding-top:15px;color:var(--muted);font-size:12px}
@media(max-width:800px){.grid2{grid-template-columns:1fr}.wrap{padding:24px 14px 60px}h1{font-size:27px}}
"""


SCRIPT = r"""
function money(v){const s=v<0?'−':'';return s+'$'+Math.abs(v).toLocaleString(undefined,{maximumFractionDigits:0});}
document.querySelectorAll('[data-chart]').forEach(fig=>{
  const data=JSON.parse(fig.dataset.chart), svg=fig.querySelector('svg'), hit=fig.querySelector('.hitbox');
  const cross=fig.querySelector('.crosshair'), tip=fig.querySelector('.tooltip');
  function localPoint(event){const r=svg.getBoundingClientRect();return (event.clientX-r.left)*1100/r.width;}
  hit.addEventListener('mousemove',event=>{
    const x=localPoint(event), ratio=Math.max(0,Math.min(1,(x-data.left)/data.plotWidth));
    const i=Math.round(ratio*(data.dates.length-1)), px=data.left+data.plotWidth*i/Math.max(data.dates.length-1,1);
    cross.hidden=false;cross.setAttribute('x1',px);cross.setAttribute('x2',px);
    let rows=`<b>${data.dates[i]}</b>`;
    data.series.forEach(s=>{const v=s.values[i];if(v!==null){let out=data.kind==='money'?money(v):v.toFixed(2);rows+=`<br><span style="color:${s.color}">●</span> ${s.label}: ${out}`;}});
    tip.innerHTML=rows;tip.hidden=false;
    const plot=fig.querySelector('.plot'), pr=plot.getBoundingClientRect();
    tip.style.left=Math.min(event.clientX-pr.left+12,pr.width-tip.offsetWidth-8)+'px';
    tip.style.top=Math.max(8,event.clientY-pr.top-tip.offsetHeight-10)+'px';
  });
  hit.addEventListener('mouseleave',()=>{cross.hidden=true;tip.hidden=true;});
});
"""


def build_html(
    registry: dict[str, str],
    series: dict[str, pd.DataFrame],
    all_metrics: dict[str, dict[str, float]],
    equity: pd.DataFrame,
    drawdown: pd.DataFrame,
    rolling: pd.DataFrame,
    annual: pd.DataFrame,
) -> str:
    control_label = next(iter(series))
    control = series[control_label]
    headline = all_metrics[control_label]
    start = control["entry_time"].min().tz_convert(TZ).strftime("%Y-%m-%d")
    end = control["exit_time"].max().tz_convert(TZ).strftime("%Y-%m-%d")
    status_text = "Baseline is below breakeven before trading costs" if headline["profit_factor"] < 1 else "Baseline is above breakeven before trading costs"
    status_class = "neg" if headline["profit_factor"] < 1 else "pos"

    cards = [
        ("Trades", fmt(headline["trades"], "integer"), ""),
        ("Win rate", fmt(headline["win_rate"], "percent"), ""),
        ("Average points", fmt(headline["avg_points"]), css_class(headline["avg_points"])),
        ("Average R", fmt(headline["avg_r"]), css_class(headline["avg_r"])),
        ("Profit factor", fmt(headline["profit_factor"], "pf"), ""),
        ("Total MNQ P&L", fmt(headline["total_pnl"], "money"), css_class(headline["total_pnl"])),
        ("Max drawdown", fmt(headline["max_drawdown"], "money"), "neg"),
    ]
    tiles = "".join(f'<div class="tile"><span>{label}</span><strong class="{klass}">{value}</strong></div>' for label, value, klass in cards)
    paths = " · ".join(f"{html.escape(label)}: <code>{html.escape(path)}</code>" for label, path in registry.items())

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SND strategy lab</title><style>{STYLE}</style></head><body><main class="wrap">
<div class="eyebrow">MNQ · Zone strategy research</div><h1>SND strategy lab</h1>
<p class="lead">A living comparison dashboard. The original SND rules remain the control line; each confluence experiment can be registered beside it using the same trade-ledger schema.</p>
<p class="meta">Control period {start} → {end} · closed 1h/4h/Daily zones · one-minute execution · MNQ $2/point · no costs</p>
<div class="status {status_class}"><i></i>{html.escape(status_text)}</div>
<div class="tiles">{tiles}</div>

<section><div class="section-head"><div><div class="eyebrow">Control versus experiments</div><h2>Performance lines</h2></div></div>
{svg_line_chart(equity, 'Cumulative P&L', 'Calendar-time MNQ dollars; flat days are carried forward.', 'money')}
{svg_line_chart(drawdown, 'Drawdown', 'Daily-close distance below each line’s prior peak; the headline maximum drawdown is measured trade by trade.', 'money')}
{svg_line_chart(rolling, 'Rolling 90-day expectancy', 'Total points divided by trades over the trailing 90 calendar days.', 'number')}
</section>

<section><div class="section-head"><div><div class="eyebrow">Scoreboard</div><h2>Strategy comparison</h2></div></div>
{metrics_table(all_metrics)}
<p class="note">Profit factor and P&amp;L are before commissions and slippage. Sharpe, Sortino, annualized volatility, and profitable months use daily session P&amp;L on one common business-day calendar with zero-trade days included. P&amp;L Calmar is annualized additive P&amp;L divided by daily maximum drawdown.</p></section>

<section><div class="section-head"><div><div class="eyebrow">Stability</div><h2>Annual P&amp;L</h2></div></div>
{dataframe_table(annual, money=True)}</section>

<section><div class="section-head"><div><div class="eyebrow">Control anatomy</div><h2>Where the baseline works and fails</h2></div></div>
<div class="grid2"><div>{breakdown_table(control, 'timeframe')}</div><div>{breakdown_table(control, 'test_number')}</div>
<div>{breakdown_table(control, 'direction')}</div><div>{breakdown_table(control, 'session')}</div></div></section>

{window_panel()}

{phase2_panel()}

{phase3_panel()}

{phase4_panel()}

{phase5_panel()}

{phase6_panel()}

<section><div class="section-head"><div><div class="eyebrow">Method</div><h2>Adding the next line</h2></div></div>
<div class="method"><code>.venv/bin/python scripts/mnq/SND_html_report.py --series "BOS filter=reports/SND_bos/trades.parquet"</code>
<p>The registry is persistent, so later runs retain the baseline and earlier experiments. Registered ledgers: {paths}</p></div></section>

<footer>Generated offline by <code>scripts/mnq/SND_html_report.py</code>. Supporting CSVs and the persistent <code>series.json</code> registry are beside this file.</footer>
</main><script>{SCRIPT}</script></body></html>"""


def main() -> None:
    args = parse_args()
    registry = update_registry(args)
    series = {label: load_trades(resolve_path(path)) for label, path in registry.items()}
    first_date = min(local_trade_dates(frame).min() for frame in series.values())
    last_date = max(local_trade_dates(frame).max() for frame in series.values())
    common_calendar = pd.bdate_range(first_date, last_date)
    all_metrics = {label: metrics(frame, common_calendar) for label, frame in series.items()}
    equity, drawdown, rolling, annual = comparison_frames(series)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    equity.to_csv(args.output_dir / "daily_equity.csv")
    drawdown.to_csv(args.output_dir / "daily_drawdown.csv")
    rolling.to_csv(args.output_dir / "rolling_90d_expectancy.csv")
    annual.to_csv(args.output_dir / "annual_pnl.csv")
    pd.DataFrame(all_metrics).T.to_csv(args.output_dir / "comparison_metrics.csv")
    output = args.output_dir / "index.html"
    output.write_text(build_html(registry, series, all_metrics, equity, drawdown, rolling, annual))
    print(f"SND dashboard: {len(series)} line(s) -> {output}")
    for label, values in all_metrics.items():
        print(
            f"  {label}: {int(values['trades']):,} trades | PF {values['profit_factor']:.2f} | "
            f"{values['total_pnl']:,.0f} MNQ dollars"
        )


if __name__ == "__main__":
    main()
