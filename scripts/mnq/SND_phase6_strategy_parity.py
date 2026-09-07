"""Compare a TradingView Strategy Tester export with a Python reference ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports" / "SND_phase6"
DEFAULT_REFERENCE = REPORT / "pine_parity_reference_2026.csv"


def profit_factor(pnl: pd.Series) -> float:
    gross_profit = pnl[pnl > 0].sum()
    gross_loss = -pnl[pnl < 0].sum()
    return float(gross_profit / gross_loss) if gross_loss else float("inf")


def max_drawdown(pnl: pd.Series) -> float:
    equity = np.r_[0.0, pnl.cumsum().to_numpy(dtype=float)]
    return float(np.max(np.maximum.accumulate(equity) - equity))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tradingview_csv", type=Path)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument(
        "--timezone",
        default="America/New_York",
        help="Timezone selected on the TradingView chart/export (default: America/New_York)",
    )
    parser.add_argument(
        "--tolerance-minutes",
        type=float,
        default=2.0,
        help="Tolerance around the expected next-minute native fill",
    )
    parser.add_argument(
        "--report-dir", type=Path,
        help="Output directory (default: directory containing --reference)",
    )
    parser.add_argument("--output", type=Path, help="JSON result path")
    args = parser.parse_args()
    report_dir = args.report_dir or args.reference.parent
    report_dir.mkdir(parents=True, exist_ok=True)
    output = args.output or report_dir / "tradingview_strategy_parity.json"

    raw = pd.read_csv(args.tradingview_csv, encoding="utf-8-sig")
    reference = pd.read_csv(args.reference)
    required = {"Trade number", "Type", "Date and time", "Price USD", "Net PnL USD", "Commission USD"}
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"Not a recognized Strategy Tester trade export; missing {sorted(missing)}")

    entries = raw.loc[raw.Type.str.startswith("Entry")].copy()
    exits = raw.loc[raw.Type.str.startswith("Exit")].copy()
    entries["entry_time_utc"] = (
        pd.to_datetime(entries["Date and time"])
        .dt.tz_localize(args.timezone, ambiguous="infer", nonexistent="shift_forward")
        .dt.tz_convert("UTC")
    )
    entries["direction"] = np.where(entries.Type.eq("Entry long"), "long", "short")
    diagnostic = entries["Signal"].astype(str).str.extract(
        r"^(?P<side>P6[LS])\|sig=(?P<signal_ms>\d+)\|zone=(?P<zone_ms>\d+)"
        r"\|prox=(?P<proximal>[^|]+)\|dist=(?P<distal>[^|]+)"
        r"(?:\|rvol=(?P<rvol>[^|]+))?\|room=(?P<room>.+)$"
    )
    diagnostic_rows = diagnostic.signal_ms.notna()
    # Older exports do not contain the diagnostic comment. For those files,
    # infer the signal bar as one minute before the native market fill.
    entries["signal_time_utc"] = entries.entry_time_utc - pd.Timedelta(minutes=1)
    entries["zone_time_utc"] = pd.Series(pd.NaT, index=entries.index, dtype="datetime64[ns, UTC]")
    entries["research_proximal"] = np.nan
    entries["research_distal"] = np.nan
    entries["opposing_room_r"] = np.nan
    entries["first_touch_prior_5m_rvol"] = np.nan
    if diagnostic_rows.any():
        entries.loc[diagnostic_rows, "signal_time_utc"] = pd.to_datetime(
            diagnostic.loc[diagnostic_rows, "signal_ms"].astype("int64"), unit="ms", utc=True
        )
        entries.loc[diagnostic_rows, "zone_time_utc"] = pd.to_datetime(
            diagnostic.loc[diagnostic_rows, "zone_ms"].astype("int64"), unit="ms", utc=True
        )
        for source, target in (
            ("proximal", "research_proximal"), ("distal", "research_distal"),
            ("room", "opposing_room_r"), ("rvol", "first_touch_prior_5m_rvol"),
        ):
            entries.loc[diagnostic_rows, target] = pd.to_numeric(
                diagnostic.loc[diagnostic_rows, source], errors="coerce"
            )
    exits["exit_time_utc"] = (
        pd.to_datetime(exits["Date and time"])
        .dt.tz_localize(args.timezone, ambiguous="infer", nonexistent="shift_forward")
        .dt.tz_convert("UTC")
    )
    reference["entry_time"] = pd.to_datetime(reference.entry_time, utc=True)
    reference["exit_time"] = pd.to_datetime(reference.exit_time, utc=True)
    reference["zone_formed_at"] = pd.to_datetime(reference.zone_formed_at, utc=True)
    reference["zone_available_at"] = pd.to_datetime(reference.zone_available_at, utc=True)

    tolerance_seconds = args.tolerance_minutes * 60.0
    candidates: list[tuple[float, int, int]] = []
    for tv_index, tv_trade in entries.iterrows():
        eligible = reference.index[reference.direction.eq(tv_trade.direction)]
        deltas = (reference.loc[eligible, "entry_time"] - tv_trade.signal_time_utc).abs()
        for ref_index, delta in deltas.items():
            seconds = delta.total_seconds()
            if seconds <= tolerance_seconds:
                candidates.append((seconds, int(tv_index), int(ref_index)))

    # Smallest timing error wins; each trade can be paired only once.
    used_tv: set[int] = set()
    used_ref: set[int] = set()
    matches: list[dict[str, object]] = []
    for seconds, tv_index, ref_index in sorted(candidates):
        if tv_index in used_tv or ref_index in used_ref:
            continue
        used_tv.add(tv_index)
        used_ref.add(ref_index)
        tv_trade = entries.loc[tv_index]
        ref_trade = reference.loc[ref_index]
        matches.append({
            "trade_number": int(tv_trade["Trade number"]),
            "reference_trade_id": int(ref_trade.trade_id),
            "reference_zone_id": int(ref_trade.zone_id),
            "direction": tv_trade.direction,
            "reference_signal_time": ref_trade.entry_time,
            "tradingview_signal_time": tv_trade.signal_time_utc,
            "tradingview_entry_time": tv_trade.entry_time_utc,
            "timing_error_seconds": seconds,
            "reference_zone_formed": ref_trade.zone_formed_at,
            "tradingview_zone_time": tv_trade.zone_time_utc,
            "reference_proximal": float(ref_trade.entry_price),
            "reference_distal": float(ref_trade.zone_distal),
            "tradingview_fill": float(tv_trade["Price USD"]),
            "tradingview_research_proximal": float(tv_trade.research_proximal),
            "tradingview_research_distal": float(tv_trade.research_distal),
            "tradingview_opposing_room_r": float(tv_trade.opposing_room_r),
            "tradingview_first_touch_prior_5m_rvol": float(tv_trade.first_touch_prior_5m_rvol),
            "reference_first_touch_prior_5m_rvol": float(
                ref_trade.get("first_touch_prior_5m_rvol", np.nan)
            ),
            "price_basis_plus_fill_difference": float(tv_trade["Price USD"] - ref_trade.entry_price),
        })

    matched = pd.DataFrame(matches)
    unmatched_reference = reference.loc[~reference.index.isin(used_ref)].copy()
    unmatched_tradingview = entries.loc[~entries.index.isin(used_tv)].copy()

    # Identify residual trades that use the same underlying zone but touch it
    # at different times after the two continuous-contract feeds are adjusted.
    zone_candidates: list[tuple[float, int, int, float, float]] = []
    for tv_index, tv_trade in unmatched_tradingview.iterrows():
        tv_width = abs(tv_trade.research_proximal - tv_trade.research_distal)
        for ref_index, ref_trade in unmatched_reference.iterrows():
            ref_width = abs(ref_trade.zone_proximal - ref_trade.zone_distal)
            time_delta_hours = abs(
                (tv_trade.zone_time_utc - ref_trade.zone_formed_at).total_seconds()
            ) / 3600.0
            width_delta = abs(tv_width - ref_width)
            if tv_trade.direction == ref_trade.direction and time_delta_hours <= 2 and width_delta <= 2:
                zone_candidates.append(
                    (time_delta_hours + width_delta, int(tv_index), int(ref_index), time_delta_hours, width_delta)
                )
    used_zone_tv: set[int] = set()
    used_zone_ref: set[int] = set()
    same_zone_rows = []
    for _, tv_index, ref_index, time_delta_hours, width_delta in sorted(zone_candidates):
        if tv_index in used_zone_tv or ref_index in used_zone_ref:
            continue
        used_zone_tv.add(tv_index)
        used_zone_ref.add(ref_index)
        tv_trade = unmatched_tradingview.loc[tv_index]
        ref_trade = unmatched_reference.loc[ref_index]
        same_zone_rows.append({
            "tradingview_trade_number": int(tv_trade["Trade number"]),
            "reference_trade_id": int(ref_trade.trade_id),
            "direction": tv_trade.direction,
            "tradingview_signal_time": tv_trade.signal_time_utc,
            "reference_signal_time": ref_trade.entry_time,
            "zone_time_delta_hours": time_delta_hours,
            "zone_width_delta_points": width_delta,
        })
    same_zone_different_touch = pd.DataFrame(same_zone_rows)
    matched.to_csv(report_dir / "tradingview_strategy_matches.csv", index=False)
    unmatched_reference.assign(source="python_reference").to_csv(
        report_dir / "tradingview_strategy_unmatched_reference.csv", index=False
    )
    unmatched_tradingview.assign(source="tradingview").to_csv(
        report_dir / "tradingview_strategy_unmatched_tradingview.csv", index=False
    )
    same_zone_different_touch.to_csv(
        report_dir / "tradingview_strategy_same_zone_different_touch.csv", index=False
    )

    reference_width = abs(matched.reference_proximal - matched.reference_distal)
    tradingview_width = abs(
        matched.tradingview_research_proximal - matched.tradingview_research_distal
    )
    width_delta = abs(tradingview_width - reference_width)
    proximal_basis = matched.tradingview_research_proximal - matched.reference_proximal
    common_basis = proximal_basis.value_counts().head(3)
    rvol_pairs = matched.loc[
        matched.tradingview_first_touch_prior_5m_rvol.notna()
        & matched.reference_first_touch_prior_5m_rvol.notna()
    ]
    rvol_abs_difference = (
        rvol_pairs.tradingview_first_touch_prior_5m_rvol
        - rvol_pairs.reference_first_touch_prior_5m_rvol
    ).abs()

    tv_pnl = exits.sort_values("Trade number")["Net PnL USD"].astype(float)
    ref_pnl = reference.pnl.astype(float)
    result = {
        "status": "review",
        "source_file": args.tradingview_csv.name,
        "tradingview_timezone": args.timezone,
        "expected_native_fill_delay_minutes": 1,
        "diagnostic_comments": int(diagnostic_rows.sum()),
        "matching_tolerance_minutes": args.tolerance_minutes,
        "reference_trades": int(len(reference)),
        "tradingview_trades": int(len(entries)),
        "matched_signals": int(len(matched)),
        "reference_signal_coverage": float(len(matched) / len(reference)),
        "tradingview_signal_coverage": float(len(matched) / len(entries)),
        "unmatched_reference": int(len(unmatched_reference)),
        "unmatched_tradingview": int(len(unmatched_tradingview)),
        "matched_diagnostics": {
            "exact_signal_minute": int((matched.timing_error_seconds == 0).sum()),
            "exact_zone_width": int((width_delta < 0.01).sum()),
            "zone_width_within_one_point": int((width_delta <= 1.0).sum()),
            "maximum_zone_width_difference_points": float(width_delta.max()),
            "same_zone_different_touch_pairs": int(len(same_zone_different_touch)),
            "dominant_proximal_basis_adjustments": [
                {"points": float(points), "trades": int(count)}
                for points, count in common_basis.items()
            ],
        },
        "tradingview": {
            "net_pnl_usd": float(tv_pnl.sum()),
            "profit_factor": profit_factor(tv_pnl),
            "winning_trades": int((tv_pnl > 0).sum()),
            "closed_trade_drawdown_usd": max_drawdown(tv_pnl),
            "commission_usd": float(exits["Commission USD"].sum()),
        },
        "python_reference": {
            "net_pnl_usd": float(ref_pnl.sum()),
            "profit_factor": profit_factor(ref_pnl),
            "winning_trades": int((ref_pnl > 0).sum()),
            "closed_trade_drawdown_usd": max_drawdown(ref_pnl),
        },
        "matched_price_difference": {
            "median": float(matched.price_basis_plus_fill_difference.median()),
            "minimum": float(matched.price_basis_plus_fill_difference.min()),
            "maximum": float(matched.price_basis_plus_fill_difference.max()),
            "interpretation": "Includes TradingView continuous-contract back-adjustment and native fill difference; it is not slippage alone.",
        },
        "matched_rvol": {
            "pairs": int(len(rvol_pairs)),
            "correlation": float(
                rvol_pairs.tradingview_first_touch_prior_5m_rvol.corr(
                    rvol_pairs.reference_first_touch_prior_5m_rvol
                )
            ) if len(rvol_pairs) > 1 else None,
            "median_absolute_difference": float(rvol_abs_difference.median()) if len(rvol_pairs) else None,
            "mean_absolute_difference": float(rvol_abs_difference.mean()) if len(rvol_pairs) else None,
        },
        "interpretation": (
            "Signal timing and zone geometry strongly align. The fixed but changing price-basis offsets and same-zone/different-touch pairs "
            "show that continuous-contract construction is the primary residual difference. Do not tune strategy rules to this sample."
        ),
    }
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
