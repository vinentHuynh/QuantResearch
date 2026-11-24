"""Independent hand-built path checks and raw-data checks for the opening study."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "reports/mnq-ny-open-2026-10-28"
spec = importlib.util.spec_from_file_location("ny_open", ROOT / "scripts/mnq/mnq_ny_open_report.py")
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)


def run_case(bars, expected):
    future = pd.DataFrame(bars, columns=["open", "high", "low", "close"])
    result = study.path_metrics(100., 120., future)
    for name, value in expected.items():
        assert result[name] == value, (name, result[name], value)
    # Mirror every price around 100: the same geometry must work for a down push.
    mirrored = pd.DataFrame({
        "open": 200-future.open,
        "high": 200-future.low,
        "low": 200-future.high,
        "close": 200-future.close,
    })
    reflected = study.path_metrics(100., 80., mirrored)
    for name, value in result.items():
        if name == "deadline_close":
            assert reflected[name] == 200-value
        elif isinstance(value, float) and np.isnan(value):
            assert np.isnan(reflected[name])
        else:
            assert reflected[name] == value, ("mirror", name, value, reflected[name])


cases = [
    ([(120, 128, 109, 115)], {"half_retrace": True, "full_retrace": False, "race": "neither"}),
    ([(120, 126, 99, 105), (105, 145, 103, 142)], {"race": "reversion_first", "full_retrace": True, "extension": True, "adverse_before_return_lower_pts": 0., "adverse_before_return_upper_pts": 6.}),
    ([(120, 145, 115, 140), (140, 146, 99, 103)], {"race": "extension_first", "adverse_before_return_lower_pts": 25., "adverse_before_return_upper_pts": 26.}),
    ([(120, 145, 99, 125)], {"race": "ambiguous", "adverse_before_return_lower_pts": 0., "adverse_before_return_upper_pts": 25.}),
    ([(98, 145, 95, 125)], {"race": "reversion_first", "adverse_before_return_lower_pts": 0., "adverse_before_return_upper_pts": 0.}),
    ([(142, 145, 99, 125)], {"race": "extension_first", "adverse_before_return_lower_pts": 22., "adverse_before_return_upper_pts": 25.}),
    ([(120, 145, 111, 141)], {"clean_continuation": True, "half_retrace": False, "extension": True}),
    ([(120, 145, 110, 141)], {"clean_continuation": False, "half_retrace": True}),
    ([(120, 145, 111, 119)], {"clean_continuation": False, "finish_beyond_checkpoint": False}),
    ([(120, 120, 100, 100)], {"race": "reversion_first", "return_minute_upper": 1, "fade_fixed_end_markout_pts": 20.}),
    ([(120, 121, 79, 90)], {"opposite_equal_move": True}),
]
for bars, expected in cases:
    run_case(bars, expected)

# The first bar is included, the cutoff bar is excluded by positional slicing.
boundary = pd.DataFrame([(120, 125, 115, 120)]*61, columns=["open", "high", "low", "close"])
boundary.loc[60] = [120, 140, 100, 120]
assert study.path_metrics(100., 120., boundary.iloc[:60])["race"] == "neither"
assert study.path_metrics(100., 120., boundary)["race"] == "ambiguous"

summary = json.loads((OUT / "summary.json").read_text())
opening = pd.read_csv(OUT / "opening_sessions.csv")
events = pd.read_csv(OUT / "followup_events.csv")
metadata = summary["metadata"]
assert len(opening) == metadata["included_sessions"]*3
assert len(events) == int((opening.net_pts != 0).sum())*2
assert not opening.duplicated(["date", "window"]).any()
assert not events.duplicated(["date", "window", "horizon"]).any()
assert events.race.isin(["reversion_first", "extension_first", "ambiguous", "neither"]).all()
assert (events.no_open_return == ~events.full_retrace).all()
assert (events.opposite_equal_move <= events.full_retrace).all()
assert (events.full_retrace <= events.half_retrace).all()
assert (~events.clean_continuation | (events.extension & ~events.half_retrace & events.finish_beyond_checkpoint)).all()
assert (events.adverse_before_return_lower_pts.dropna() <= events.adverse_before_return_upper_pts.dropna()).all()
assert (events.adverse_before_return_upper_pts.dropna() <= events.loc[events.full_retrace, "fade_adverse_pts"]).all()

raw = pd.read_parquet(metadata["data_path"]).tz_convert("America/New_York")
sample_dates = ["2019-05-06", "2020-03-10", "2024-06-17", "2025-04-09", "2026-09-03"]
checked = 0
for date in sample_dates:
    if date not in set(opening.date):
        continue
    start = pd.Timestamp(date + " 09:30", tz="America/New_York")
    for minutes in [5, 10, 15]:
        checkpoint = start + pd.Timedelta(minutes=minutes)
        first = raw.loc[(raw.index >= start) & (raw.index < checkpoint)]
        rec = opening[(opening.date == date) & (opening.window == minutes)].iloc[0]
        assert len(first) == minutes
        o, e = first.open.iloc[0], first.close.iloc[-1]
        assert rec.range_pts == first.high.max()-first.low.min()
        assert rec.abs_net_pts == abs(e-o)
        assert rec.net_pts == e-o
        assert rec.up_excursion_pts == first.high.max()-o
        assert rec.down_excursion_pts == o-first.low.min()
        for horizon in [60, 120]:
            if e == o:
                continue
            deadline = checkpoint + pd.Timedelta(minutes=horizon)
            later = raw.loc[(raw.index >= checkpoint) & (raw.index < deadline)]
            event = events[(events.date == date) & (events.window == minutes) & (events.horizon == horizon)].iloc[0]
            assert len(later) == horizon
            # Independent direct directional formulas, without invoking path_metrics.
            full = (later.low <= o).any() if e > o else (later.high >= o).any()
            half_level = (o+e)/2
            half = (later.low <= half_level).any() if e > o else (later.high >= half_level).any()
            extension_level = 2*e-o
            extension = (later.high >= extension_level).any() if e > o else (later.low <= extension_level).any()
            mark = float((e-later.close.iloc[-1])*np.sign(e-o))
            assert event.full_retrace == full
            assert event.half_retrace == half
            assert event.extension == extension
            assert event.fade_fixed_end_markout_pts == mark
            assert event.clean_continuation == (extension and not half and mark < 0)
            checked += 1

for row in summary["opening_summary"]:
    subset = opening[opening.window == row["window"]]
    if row["period"] == "2024 onward":
        subset = subset[subset.year >= 2024]
    assert row["n"] == len(subset)
    assert np.isclose(row["range_pts_mean"], subset.range_pts.mean())
    assert row["range_pts_median"] == subset.range_pts.median()
    assert np.isclose(row["abs_net_pts_mean"], subset.abs_net_pts.mean())
    assert row["abs_net_pts_median"] == subset.abs_net_pts.median()
for row in summary["outcome_summary"]:
    subset = events[(events.window == row["window"]) & (events.horizon == row["horizon"])]
    if row["period"] == "2024 onward":
        subset = subset[subset.year >= 2024]
    if row["sample"] == "directional_push":
        subset = subset[subset.directional_push]
    assert row["n"] == len(subset)
    assert sum(row[race + "_n"] for race in study.RACES) == len(subset)
    for flag in study.FLAGS:
        assert row[flag + "_n"] == int(subset[flag].sum())
        assert np.isclose(row[flag + "_pct"], 100*subset[flag].mean())

print(json.dumps({"synthetic_cases_including_mirrors": len(cases)*2+2,
                  "independently_recomputed_actual_event_rows": checked,
                  "opening_rows": len(opening), "event_rows": len(events),
                  "all_export_summary_and_path_checks": "passed"}, indent=2))
