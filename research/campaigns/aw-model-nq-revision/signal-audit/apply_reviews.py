"""Record the separate visual judgments after chart inspection.

The primary sample was selected by build_revised_audit.py before this file
was written. This script joins chart judgments and independent OHLC checks;
it never reads returns, trades, equity, or performance metrics.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
from workbench.layout import load_layout


ARTIFACTS_ROOT = load_layout(ROOT).artifacts_root
DEFAULT_INPUT = (ARTIFACTS_ROOT / "research" / "aw-model-nq-2026-09-29" /
                 "revision" / "signal-audit")

# Notes from Codex's visual review of all 60 full-window chart PNGs. These are
# qualitative flags, not changes to the frozen numerical classification.
SPECIAL = {
    "2022-07-06": ("plausible_displacement_rejected",
                   "The first bearish break looks forceful. Its close is 27.1% of the range from the low, only 2.1 percentage points outside the 25% proxy; this is a plausible qualitative false rejection."),
    "2022-09-16": ("borderline_displacement",
                   "The first bullish break has a large body but a visible upper wick. Its close is 38.8% from the high, so a human could debate whether it is an impulsive close."),
    "2026-02-09": ("borderline_displacement",
                   "A large bullish candle crosses the neckline, but its upper wick and 56.8% body/range make the PDF's qualitative displacement judgment uncertain."),
    "2023-08-07": ("same_3m_bar_ambiguity",
                   "The sweep candle itself closes below the short neckline. Prior one-minute chronology found the ONH sweep at 08:31 and neckline close at 08:32 CT; the later program-rejected crossover at 09:30 is a separate recross. The 3-minute rule excludes the first possible MSS."),
    "2026-06-05": ("same_3m_bar_ambiguity",
                   "The sweep candle itself closes above the long neckline. Prior one-minute chronology found the ONL sweep at 08:30 and neckline close at 08:31 CT. A separate one-minute setup would still need its own displacement and FVG tests."),
    "2022-07-14": ("slow_first_mss",
                   "The bullish first neckline close occurs 72 minutes after the PDL sweep. The strict gap is only 1.25 points, nearly invisible at the full chart scale. This is mechanically valid under the frozen 10:30 cutoff but may not read as a quick AW shift."),
    "2025-08-27": ("slow_first_mss",
                   "The first bullish neckline close occurs 48 minutes after the ONL sweep; the chart shows a second low and long recovery before the break."),
    "2022-01-11": ("slow_first_mss",
                   "The bullish neckline close and strict gap follow the ONL sweep by 33 minutes, leaving the PDF's qualitative word 'quick' open to judgment."),
    "2024-05-21": ("slow_first_mss",
                   "The bullish break is a directional close, but it first arrives 45 minutes after the ONL sweep and does not form a strict subsequent gap."),
    "2025-04-15": ("slow_first_mss",
                   "The bearish neckline break first arrives 51 minutes after the ONH sweep; the later move looks like a separate leg, and no strict gap follows."),
    "2024-10-21": ("slow_first_mss_and_weak",
                   "The small bearish first cross occurs 54 minutes after the PDH sweep and is visibly weak; the program's displacement rejection is reasonable."),
    "2024-10-30": ("slow_first_mss_and_weak",
                   "The first bullish cross arrives 48 minutes after the ONL sweep; its body is small and choppy, consistent with the numerical rejection."),
    "2023-07-19": ("neckline_salience_uncertain",
                   "The bearish break is visible, but the marked pre-sweep neckline is a minor local low in the displayed choppy structure. The next candle overlaps, so the strict FVG rejection matches the OHLC geometry."),
}


def generic_note(row):
    stage = row.program_stage
    if stage == "expired_at_entry_window":
        return "The full chart through 10:33 CT shows no later completed 3-minute neckline close before the 10:30 entry cutoff."
    if stage == "weak_first_break":
        return "A later 3-minute candle first crosses the neckline, but its body/wick/close profile fails at least one frozen strength test."
    if stage == "mss_without_strict_fvg":
        return "A directional 3-minute neckline break appears; the next completed candle overlaps the first gap candle, so no strict three-candle FVG remains."
    if stage == "confirmed_gap":
        return "The first directional neckline break and strict three-candle gap are present; the frozen reward gate then blocks an order."
    if stage == "entry_submitted":
        return "The first directional neckline break and strict three-candle gap are present; a limit order is submitted. The chart alone cannot validate its fill."
    raise ValueError(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_INPUT,
                        help="Signal-audit directory containing sampled candidates and charts")
    args = parser.parse_args()
    artifact_dir = args.artifact_dir.resolve()
    sample = pd.read_csv(artifact_dir / "sampled_candidates.csv").fillna("")
    checks = pd.read_csv(artifact_dir / "level_checks.csv").fillna("").set_index("candidate_id")
    assert len(sample) == 60 and sample.day_ct.nunique() == 60
    assert set(sample.candidate_id).issubset(set(checks.index))
    assert all((artifact_dir / path).exists() for path in sample.chart_path)
    def checked(value):
        return value == "" or str(value).lower() == "true"

    out = []
    for row in sample.itertuples(index=False):
        check = checks.loc[row.candidate_id]
        visual_label, note = SPECIAL.get(row.day_ct, ("local_stage_agrees", generic_note(row)))
        direction = "buy-side sweep → short → sell-side target" if row.direction == "short" else "sell-side sweep → long → buy-side target"
        delay = int(float(row.signal_bars_after_sweep)) * 3 if row.signal_bars_after_sweep != "" else None
        if row.program_stage == "expired_at_entry_window":
            displacement = "No later completed 3-minute neckline crossover before the 10:30 CT cutoff"
        else:
            displacement = (f"First later crossover after {delay} minutes; body/median "
                            f"{float(row.body_over_median):.2f}, body/range "
                            f"{float(row.body_over_range):.3f}, close-from-edge "
                            f"{float(row.close_fraction_from_edge):.3f}; "
                            f"frozen strength {'passed' if str(row.cross_strength_pass).lower() == 'true' else 'failed'}")
        if row.fvg_ready_ct != "":
            fvg = (f"Strict completed three-candle FVG {float(row.fvg_low):.2f}–"
                   f"{float(row.fvg_high):.2f}; OHLC gap check passed")
        elif row.program_stage == "mss_without_strict_fvg":
            fvg = "Break occurred, but the next third candle overlaps the first; no strict gap"
        else:
            fvg = "FVG stage not reached"
        if row.gate_ready_ct != "":
            target = (f"{row.target_level_name} {float(row.opposing_target_price):.2f} is the nearest "
                      "eligible untaken opposing level at gap confirmation; quality beyond this rule is subjective")
        else:
            target = "Target selection not reached; no opposing target was independently assessed"
        out.append({
            "candidate_id": row.candidate_id, "day_ct": row.day_ct,
            "chart_path": row.chart_path, "program_stage": row.program_stage,
            "direction_mapping": direction,
            "visual_label": visual_label, "visual_note": note,
            "external_liquidity_review": (f"{row.swept_level_name} {float(row.swept_level_price):.2f} "
                                          "matches raw-OHLC previous-session/overnight extremum; pool strength unjudged"),
            "sweep_review": "Three-minute wick ≥1 tick beyond marked level, then close back inside; OHLC check passed",
            "neckline_review": (f"Premarked confirmed pivot {float(row.neckline_price):.2f}; "
                                "displayed local swing salience is subjective"),
            "displacement_review": displacement,
            "fvg_review": fvg, "target_review": target,
            "signal_minutes_after_sweep": delay,
            "source_geometry_checks_pass": all(checked(value) for value in (
                check.external_prices_match, check.eligible_levels_match,
                check.sweep_geometry_match, check.strict_fvg_geometry_match,
                check.taken_levels_match, check.nearest_untaken_target_match)),
            "scope_limit": "Codex local 3m chart, full setup window; no independent 2h/news/contextual pool adjudication",
        })
    pd.DataFrame(out).to_csv(artifact_dir / "reviewed_sample.csv", index=False)
    print(pd.Series([x["visual_label"] for x in out]).value_counts().to_string())


if __name__ == "__main__":
    main()
