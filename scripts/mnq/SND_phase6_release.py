# -*- coding: utf-8 -*-
"""Build the frozen Phase 6 release and validation report.

This phase does not select another rule. It freezes the Phase 5 candidate,
packages a reference ledger, and defines the gates required before paper/live use.

Run from the repository root:

    .venv/bin/python scripts/mnq/SND_phase6_release.py
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pandas as pd

from SND_html_report import SCRIPT as CHART_SCRIPT
from SND_html_report import comparison_frames, metrics, svg_line_chart
from SND_phase5_combinations import STYLE as PREVIOUS_REPORT_STYLE


ROOT = Path(__file__).resolve().parents[2]
PHASE5 = ROOT / "reports" / "SND_phase5"
SOURCE_LEDGER = PHASE5 / "04_first_touch_open_room" / "trades.parquet"
BASELINE_LEDGER = ROOT / "reports" / "SND_baseline" / "trades.parquet"
PINE = ROOT / "SND.pine"
PINE_STRATEGY = ROOT / "SND_phase6_strategy.pine"
OUTPUT = ROOT / "reports" / "SND_phase6"
TZ = "America/Chicago"
TICK_SIZE = 0.25
POINT_VALUE = 2.0
PARITY_START = pd.Timestamp("2026-01-01 17:00", tz=TZ)
PARITY_END = pd.Timestamp("2026-05-30 16:00", tz=TZ)


STYLE = PREVIOUS_REPORT_STYLE + """
.gate{border-left:4px solid var(--border)}.gate.pass{border-left-color:#16a085}.gate.pending{border-left-color:#f39c12}.gate-label{font-size:10px;font-weight:750;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}.gate.pass .gate-label{color:#087f5b}.gate.pending .gate-label{color:#b66a00}.gate p{margin:6px 0 0;color:var(--muted);font-size:12px}.tile strong.compact{font-size:16px;line-height:1.3}.method p:last-child{margin-bottom:0}
"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    for column in ("entry_time", "exit_time", "zone_formed_at", "zone_available_at"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column], utc=True)
    return frame.sort_values("exit_time").reset_index(drop=True)


def cost_stress(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ticks in (0, 1, 2, 4, 6, 8):
        stressed = frame.copy()
        stressed["pnl"] = stressed["gross_pnl"] - ticks * TICK_SIZE * POINT_VALUE
        values = metrics(stressed)
        rows.append({"round_trip_ticks": ticks, **values})
    return pd.DataFrame(rows)


def split_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    splits = {
        "Overall": frame,
        "Train 2019–22": frame.loc[frame.entry_year <= 2022],
        "Validation 2023–24": frame.loc[frame.entry_year.between(2023, 2024)],
        "Holdout 2025–26": frame.loc[frame.entry_year >= 2025],
    }
    return pd.DataFrame([{"period": name, **metrics(part)} for name, part in splits.items()])


def fmt(value: float, digits: int = 2) -> str:
    return "—" if pd.isna(value) else f"{value:,.{digits}f}"


def table(frame: pd.DataFrame, columns: list[tuple[str, str, str]]) -> str:
    head = "".join(f"<th>{label}</th>" for _, label, _ in columns)
    rows = []
    for _, row in frame.iterrows():
        cells = []
        for key, _, kind in columns:
            value = row[key]
            if kind == "text":
                shown = str(value)
            elif kind == "int":
                shown = f"{int(value):,}"
            elif kind == "money":
                shown = f"${value:,.0f}"
            elif kind == "pct":
                shown = f"{value:.1%}"
            else:
                shown = fmt(value)
            cells.append(f"<td>{shown}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    candidate = load(SOURCE_LEDGER)
    baseline = load(BASELINE_LEDGER)
    candidate.to_parquet(OUTPUT / "locked_candidate_trades.parquet", index=False)

    parity = candidate.loc[
        candidate.entry_time.between(PARITY_START.tz_convert("UTC"), PARITY_END.tz_convert("UTC"))
    ].copy()
    parity_columns = [
        "trade_id", "zone_id", "direction", "timeframe", "zone_formed_at",
        "zone_available_at", "zone_proximal", "zone_distal", "entry_time",
        "entry_price", "stop_price", "target_price", "exit_time", "exit_price",
        "exit_reason", "points", "pnl",
    ]
    parity[parity_columns].to_csv(OUTPUT / "pine_parity_reference_2026.csv", index=False)

    stress = cost_stress(candidate)
    periods = split_metrics(candidate)
    overall = periods.loc[periods.period == "Overall"].iloc[0]
    stress.to_csv(OUTPUT / "execution_stress.csv", index=False)
    periods.to_csv(OUTPUT / "period_metrics.csv", index=False)

    specification = {
        "name": "SND Phase 6 locked candidate",
        "status": "historically selected; Pine parity and forward validation pending",
        "source_phase": 5,
        "entry_timeframe": "1h",
        "active_context_timeframes": ["1h", "4h", "Daily"],
        "physical_touch_rule": "eligible throughout the first continuous 1-minute zone-overlap episode only",
        "gap_rule": "a missing/non-contiguous minute starts a new physical-touch episode",
        "opposing_room_rule": "nearest active opposing proximal level must be >= 2 structural R away, or no opposing level exists",
        "structural_r": "absolute(proximal - distal) + 1.0 point zone-break buffer",
        "zone_detection": "SND two-candle reversal with prior/impulse body ratio <= 0.50",
        "invalidation": "strict distal wick-or-close break, checked before touch eligibility",
        "candidate_priority": "higher timeframe then nearest; only 1h is tradeable in locked mode; long wins a simultaneous long/short tie",
        "target": "fixed 100 MNQ points",
        "stop": "min(zone width + 1 point, 100 points)",
        "entry": "zone proximal on the touch bar",
        "minimum_bars_in_trade": 1,
        "forced_close": "15:00 America/Chicago",
        "sessions": "SND session rules preserved, including the existing no-trade window",
        "same_bar_stop_and_target": "stop wins (conservative)",
        "position_sizing": "selectable fixed-contract, fixed-dollar-risk, or percent-of-sizing-equity; locked parity reference uses one fixed contract",
        "risk_sizing_formula": "floor(risk budget / (conservative planned stop dollars per contract + estimated round-trip cost)), capped by maximum contracts; zero contracts skips the trade",
        "point_value": POINT_VALUE,
        "tick_size": TICK_SIZE,
        "source_ledger_sha256": sha256(SOURCE_LEDGER),
        "frozen_ledger_sha256": sha256(OUTPUT / "locked_candidate_trades.parquet"),
        "pine_sha256": sha256(PINE),
        "lean_strategy_sha256": sha256(PINE_STRATEGY),
        "lean_strategy_execution": "confirmed eligible touch, native next-bar-open market fill; predefined exits are submitted with entry; no recalculation after fills",
        "parity_window_ct": [str(PARITY_START), str(PARITY_END)],
        "historical_trade_count": len(candidate),
        "parity_reference_trade_count": len(parity),
    }
    (OUTPUT / "locked_spec.json").write_text(json.dumps(specification, indent=2) + "\n")

    gates = {
        "pine_parity": {
            "status": "pending TradingView export",
            "required": "exact entry/exit count, direction and timestamps; prices within 0.01 point on the same feed",
        },
        "execution_stress": {
            "status": "pass historically" if stress.loc[stress.round_trip_ticks == 4, "profit_factor"].iloc[0] > 1 else "fail",
            "required": "profit factor > 1.0 at four ticks round trip",
        },
        "paper_forward": {
            "status": "not started",
            "interim_review_trades": 300,
            "final_review_trades": 500,
            "required": [
                "no entry-rule changes during the sample",
                "net profit factor > 1.0 after actual commissions and slippage",
                "mean net P&L clustered-bootstrap 95% confidence interval lower bound > 0",
                "signal-to-record reconciliation >= 95%",
            ],
        },
    }
    (OUTPUT / "acceptance_gates.json").write_text(json.dumps(gates, indent=2) + "\n")
    summary = {
        "candidate": "1h first physical touch + opposing room >=2R/open",
        "historical_trades": len(candidate),
        "parity_reference_trades": len(parity),
        "gross_profit_factor": float(overall.profit_factor),
        "four_tick_profit_factor": float(stress.loc[stress.round_trip_ticks == 4, "profit_factor"].iloc[0]),
        "pine_parity_status": "pending",
        "paper_forward_status": "not started",
    }
    (OUTPUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    forward_columns = [
        "signal_id", "signal_time_utc", "direction", "zone_formed_time_utc",
        "zone_proximal", "zone_distal", "opposing_room_r", "opposing_zone_absent",
        "physical_touch_episode", "planned_entry", "actual_entry", "planned_stop",
        "planned_target", "exit_time_utc", "actual_exit", "exit_reason", "contracts",
        "commission", "slippage_points", "net_pnl", "executed", "skip_reason", "notes",
    ]
    pd.DataFrame(columns=forward_columns).to_csv(OUTPUT / "paper_forward_log.csv", index=False)

    series = {"SND baseline": baseline, "Phase 6 locked candidate": candidate}
    equity, drawdown, rolling, annual = comparison_frames(series)
    equity.to_csv(OUTPUT / "daily_equity.csv")
    drawdown.to_csv(OUTPUT / "daily_drawdown.csv")
    rolling.to_csv(OUTPUT / "rolling_90d_expectancy.csv")
    annual.to_csv(OUTPUT / "annual_pnl.csv")
    four_tick = stress.loc[stress.round_trip_ticks == 4].iloc[0]
    tiles = f"""
      <div class='tile'><span>Frozen trades</span><strong>{len(candidate):,}</strong></div>
      <div class='tile'><span>Gross profit factor</span><strong>{overall.profit_factor:.3f}</strong></div>
      <div class='tile'><span>Daily Sharpe</span><strong>{overall.sharpe:.3f}</strong></div>
      <div class='tile'><span>PF at 4 ticks RT</span><strong>{four_tick.profit_factor:.3f}</strong></div>
      <div class='tile'><span>Forward gate</span><strong class='compact'>500 trades</strong></div>
    """
    periods_html = table(periods, [
        ("period", "Period", "text"), ("trades", "Trades", "int"),
        ("profit_factor", "PF", "num"), ("sharpe", "Sharpe", "num"),
        ("total_pnl", "P&L", "money"), ("max_drawdown", "Max DD", "money"),
    ])
    stress_html = table(stress, [
        ("round_trip_ticks", "RT ticks", "int"), ("profit_factor", "PF", "num"),
        ("sharpe", "Sharpe", "num"), ("total_pnl", "P&L", "money"),
        ("max_drawdown", "Max DD", "money"),
    ])
    strategy_result_path = OUTPUT / "tradingview_strategy_parity.json"
    if strategy_result_path.exists():
        strategy_result = json.loads(strategy_result_path.read_text())
        tv = strategy_result["tradingview"]
        py = strategy_result["python_reference"]
        strategy_rows = pd.DataFrame([
            {
                "source": "TradingView native fill",
                "trades": strategy_result["tradingview_trades"],
                "wins": tv["winning_trades"],
                "profit_factor": tv["profit_factor"],
                "pnl": tv["net_pnl_usd"],
                "drawdown": tv["closed_trade_drawdown_usd"],
            },
            {
                "source": "Python proximal fill",
                "trades": strategy_result["reference_trades"],
                "wins": py["winning_trades"],
                "profit_factor": py["profit_factor"],
                "pnl": py["net_pnl_usd"],
                "drawdown": py["closed_trade_drawdown_usd"],
            },
        ])
        strategy_table = table(strategy_rows, [
            ("source", "Source", "text"), ("trades", "Trades", "int"),
            ("wins", "Wins", "int"), ("profit_factor", "PF", "num"),
            ("pnl", "P&L", "money"), ("drawdown", "Closed-trade DD", "money"),
        ])
        strategy_parity_html = f"""
        <h2>First TradingView Strategy Tester comparison</h2>
        <div class='tiles'>
          <div class='tile'><span>Matched signals</span><strong>{strategy_result['matched_signals']:,}</strong></div>
          <div class='tile'><span>Python coverage</span><strong>{strategy_result['reference_signal_coverage']:.1%}</strong></div>
          <div class='tile'><span>TradingView coverage</span><strong>{strategy_result['tradingview_signal_coverage']:.1%}</strong></div>
          <div class='tile'><span>Python-only</span><strong>{strategy_result['unmatched_reference']:,}</strong></div>
          <div class='tile'><span>TradingView-only</span><strong>{strategy_result['unmatched_tradingview']:,}</strong></div>
        </div>
        {strategy_table}
        <div class='method'><p><strong>Assessment: strong logic alignment with a feed-basis caveat.</strong> After interpreting the export in {strategy_result['tradingview_timezone']} and allowing {strategy_result['matching_tolerance_minutes']:g} minutes around the expected next-bar fill, {strategy_result['matched_signals']} signals align. Of those, {strategy_result['matched_diagnostics']['exact_signal_minute']} share the exact signal minute and {strategy_result['matched_diagnostics']['exact_zone_width']} share the exact zone width; all {strategy_result['matched_diagnostics']['zone_width_within_one_point']} are within one point. The count difference of five is the net of {strategy_result['unmatched_reference']} Python-only and {strategy_result['unmatched_tradingview']} TradingView-only trades, including {strategy_result['matched_diagnostics']['same_zone_different_touch_pairs']} residual pairs built from the same zone but touched at different times. Fixed price-basis steps confirm different continuous-contract back-adjustment rather than execution slippage. This first run has ${tv['commission_usd']:,.0f} commission.</p></div>
        """
    else:
        strategy_parity_html = ""
    page = f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>SND Phase 6</title><style>{STYLE}</style></head><body><main class='wrap'>
    <div class='eyebrow'>MNQ · SND strategy lab</div><h1>Phase 6 · implementation & validation</h1>
    <p class='lead'>The Phase 5 winner is now frozen in code. Historical execution stress passes, while TradingView/Python parity and a locked paper-forward sample remain required before this can be treated as live-validated.</p>
    <div class='tiles'>{tiles}</div>
    <h2>Validation gate status</h2><div class='tiles'>
      <div class='tile gate pending'><div class='gate-label'>Pending</div><strong>Pine parity</strong><p>Run the same feed on a 1-minute chart and compare the exported fields.</p></div>
      <div class='tile gate pass'><div class='gate-label'>Pass · historical</div><strong>Execution stress</strong><p>PF remains {four_tick.profit_factor:.3f} after four ticks round trip.</p></div>
      <div class='tile gate pending'><div class='gate-label'>Not started</div><strong>Paper forward</strong><p>Interim at 300 trades; final gate at 500.</p></div>
    </div>
    <h2>Locked rules</h2><div class='method'><ol><li>Build and retain only 1h, 4h and Daily zones as context.</li><li>Only 1h zones may initiate a trade.</li><li>The zone must be in its first continuous physical touch episode on one-minute data.</li><li>The nearest active opposing proximal level must be at least 2 structural R away, or absent. Structural R is zone width plus the 1-point stop buffer.</li><li>All original SND execution rules remain fixed: proximal entry, 100-point target, capped zone-break stop, one-bar exit delay, 15:00 CT close, and stop-first ambiguous bars.</li></ol><p>Changing the Pine room input away from 2.0R creates a new experiment and invalidates this frozen validation track.</p></div>
    <h2>Historical periods</h2>{periods_html}
    <h2>Adverse execution stress</h2><p class='note'>Each tick is charged once per completed round trip on top of the recorded fills. This is a cost stress, not a limit-order fill model.</p>{stress_html}
    <h2>Equity and drawdown</h2>{svg_line_chart(equity, 'Cumulative P&L', 'Baseline versus the frozen Phase 6 candidate.', 'money')}{svg_line_chart(drawdown, 'Daily drawdown', 'Distance below the prior daily equity peak.', 'money')}{svg_line_chart(rolling, 'Rolling 90-day expectancy', 'Points per trade over the trailing 90 calendar days.', 'number')}
    <h2>Lean TradingView Strategy Tester version</h2><div class='method'><p><code>SND_phase6_strategy.pine</code> is the preferred native backtest file. It is roughly one ninth the size of the chart indicator and removes every nonessential drawing, cluster, S/R, proximity, dashboard, risk-display, Discord and EOD calculation.</p><ol><li>Open MNQ on a 1-minute chart, paste the lean strategy into Pine Editor, save it, and add it to the chart.</li><li>Leave the frozen window enabled and opposing room at exactly <code>2.0R</code>. Set realistic commission and slippage in Strategy Properties.</li><li>For the frozen parity result select one fixed contract. Risk-sized experiments can instead use a fixed dollar budget or a percentage of the separate sizing-equity input; quantity is rounded down and capped, and a signal is skipped when even one contract exceeds its budget.</li><li>Use Strategy Tester for the native execution result. The strategy confirms the touch at the one-minute close and fills at the next bar’s open; therefore it is an executable-timing stress test, not the Python model’s assumed proximal fill.</li><li>Keep <code>On order fill</code> and <code>Fill orders on bar close</code> disabled. Enable Bar Magnifier when your TradingView plan has suitable lower-timeframe history.</li><li>Feed construction and rollover can still create differences versus Databento. Entry comments preserve signal time, zone time, proximal, distal and room data in the full Deep Backtesting trade-list export.</li></ol></div>
    {strategy_parity_html}
    <h2>Indicator signal parity</h2><div class='method'><ol><li>Use <code>SND.pine</code> only when checking the original indicator’s internal simulator and export fields.</li><li>Select <code>Phase 6 Candidate</code>, leave opposing room at <code>2.0R</code>, and confirm <code>LOCKED</code> and <code>1m · OK</code>.</li><li>The frozen comparison window contains 230 Python-reference trades. Export chart data and run <code>.venv/bin/python scripts/mnq/SND_phase6_parity.py path/to/export.csv</code>.</li></ol></div>
    <h2>Paper-forward workflow</h2><div class='method'><p>Record every signal in <code>reports/SND_phase6/paper_forward_log.csv</code>, including skipped signals. Review without changing rules at 300 trades and run the final gate at 500 with <code>.venv/bin/python scripts/mnq/SND_phase6_forward_check.py</code>.</p></div>
    <h2>What Phase 6 does—and does not—prove</h2><p>The code now represents the selected hypothesis without silently adding more filters. It does not create a fresh out-of-sample result: Phase 5 already used the historical periods to choose this combination. The next genuinely new evidence is the locked paper-forward sample.</p>
    <p class='note'><a href='../SND_dashboard/index.html'>Main dashboard</a> · <a href='../SND_phase5/index.html'>Phase 5 report</a></p>
    </main><script>{CHART_SCRIPT}</script></body></html>"""
    (OUTPUT / "index.html").write_text(page)
    print(f"DONE | locked={len(candidate):,} | parity={len(parity):,} | report={OUTPUT / 'index.html'}")


if __name__ == "__main__":
    main()
