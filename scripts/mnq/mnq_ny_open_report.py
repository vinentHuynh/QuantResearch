"""Reproducible descriptive MNQ cash-open study; see frozen protocol.json."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tmp/ny_open_dependencies"))
import exchange_calendars as xcals
import numpy as np
import pandas as pd

CAMPAIGN = ROOT / "research/campaigns/mnq-ny-open-2026-10-28"
OUT = ROOT / "reports/mnq-ny-open-2026-10-28"
TZ = "America/New_York"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def path_metrics(o, e, future):
    """Use oriented prices; + means continuation, - means recovery/fade."""
    a, s = abs(e-o), np.sign(e-o)
    assert a > 0
    op = s*(future.open.to_numpy()-e)
    lo = s*((future.low if s > 0 else future.high).to_numpy()-e)
    hi = s*((future.high if s > 0 else future.low).to_numpy()-e)
    cl = s*(future.close.to_numpy()-e)
    hit_r = np.flatnonzero(lo <= -a)
    hit_x = np.flatnonzero(hi >= a)
    ir = int(hit_r[0]) if len(hit_r) else None
    ix = int(hit_x[0]) if len(hit_x) else None
    if ir is None and ix is None:
        race = "neither"
    elif ix is None or (ir is not None and ir < ix):
        race = "reversion_first"
    elif ir is None or ix < ir:
        race = "extension_first"
    elif op[ir] <= -a:
        race = "reversion_first"
    elif op[ir] >= a:
        race = "extension_first"
    else:
        race = "ambiguous"
    if ir is not None:
        lower = max(0., float(hi[:ir].max()) if ir else 0., float(op[ir]))
        upper = lower if op[ir] <= -a else max(lower, float(hi[ir]))
    else:
        lower = upper = np.nan
    half = bool(np.any(lo <= -a/2))
    return {
        "half_retrace": half, "full_retrace": ir is not None,
        "opposite_equal_move": bool(np.any(lo <= -2*a)),
        "extension": ix is not None,
        "no_open_return": ir is None,
        "finish_beyond_checkpoint": bool(cl[-1] > 0),
        "clean_continuation": bool(ix is not None and not half and cl[-1] > 0),
        "race": race,
        "return_minute_upper": ir+1 if ir is not None else np.nan,
        "fade_adverse_pts": max(0., float(hi.max())),
        "fade_favorable_pts": max(0., float(-lo.min())),
        "adverse_before_return_lower_pts": lower,
        "adverse_before_return_upper_pts": upper,
        "fade_fixed_end_markout_pts": float(-cl[-1]),
        "continuation_fixed_end_markout_pts": float(cl[-1]),
        "deadline_close": float(future.close.iloc[-1]),
    }


FLAGS = ["half_retrace", "full_retrace", "opposite_equal_move", "extension", "no_open_return", "finish_beyond_checkpoint", "clean_continuation"]
RACES = ["reversion_first", "extension_first", "ambiguous", "neither"]


def block_ci(g, col):
    monthly = g.groupby("month")[col].agg(["sum", "count"])
    rng = np.random.default_rng(20261028)
    idx = rng.integers(0, len(monthly), size=(2000, len(monthly)))
    ratios = monthly["sum"].to_numpy()[idx].sum(axis=1)/monthly["count"].to_numpy()[idx].sum(axis=1)
    return np.quantile(ratios*100, [.025, .975]).tolist()


def summarize(g, meta, ci=False):
    row = dict(meta, n=len(g))
    for flag in FLAGS:
        row[flag+"_n"] = int(g[flag].sum())
        row[flag+"_pct"] = float(g[flag].mean()*100)
    for race in RACES:
        row[race+"_n"] = int((g.race == race).sum())
        row[race+"_pct"] = float((g.race == race).mean()*100)
    for col in ["abs_net_pts", "range_pts", "fade_adverse_pts", "fade_favorable_pts", "adverse_before_return_lower_pts", "adverse_before_return_upper_pts", "fade_fixed_end_markout_pts", "return_minute_upper"]:
        vals = g[col].dropna()
        for stat in ["mean", "median", "p90"]:
            row[col+"_"+stat] = float(vals.quantile(.9) if stat == "p90" else getattr(vals, stat)()) if len(vals) else None
    if ci:
        for col in ["full_retrace", "extension", "clean_continuation"]:
            row[col+"_ci95"] = block_ci(g, col)
    recovered = g[g.full_retrace]
    failed = g[~g.full_retrace]
    row["recovered_n"] = len(recovered)
    row["failed_n"] = len(failed)
    for label, sub in [("recovered", recovered), ("failed", failed), ("clean", g[g.clean_continuation])]:
        for metric in ["fade_adverse_pts", "fade_favorable_pts", "continuation_fixed_end_markout_pts"]:
            row[label+"_"+metric+"_median"] = float(sub[metric].median()) if len(sub) else None
            row[label+"_"+metric+"_p90"] = float(sub[metric].quantile(.9)) if len(sub) else None
    return row


def stats_open(g, meta):
    row = dict(meta, n=len(g), up_n=int((g.net_pts > 0).sum()), down_n=int((g.net_pts < 0).sum()), flat_n=int((g.net_pts == 0).sum()))
    for col in ["range_pts", "abs_net_pts", "up_excursion_pts", "down_excursion_pts", "net_pts", "range_bps", "abs_net_bps"]:
        for stat in ["mean", "median", "p25", "p75", "p90"]:
            row[col+"_"+stat] = float(g[col].quantile({"p25":.25, "p75":.75, "p90":.9}[stat]) if stat.startswith("p") else getattr(g[col], stat)())
    return row


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    protocol = json.loads((CAMPAIGN/"protocol.json").read_text())
    folder = ROOT / "data/workbench/datasets" / protocol["data_version"]
    manifest = json.loads((folder/"dataset.json").read_text())
    path = folder/"bars.parquet"
    actual = digest(path)
    assert actual == manifest["checksum"]
    raw = pd.read_parquet(path)
    assert raw.index.is_monotonic_increasing and not raw.index.has_duplicates
    assert raw.symbol.nunique() == 1 and raw.symbol.iloc[0] == "MNQ.v.0"
    prices = raw[["open", "high", "low", "close"]]
    assert np.isfinite(prices.to_numpy()).all()
    assert (raw.high >= prices.max(axis=1)).all() and (raw.low <= prices.min(axis=1)).all()
    frame = raw.tz_convert(TZ).between_time("09:30", "11:44")
    frame["date"] = frame.index.strftime("%Y-%m-%d")
    calendar = xcals.get_calendar("XNYS", start=frame.date.min(), end=frame.date.max())
    assert not calendar.is_session("2025-01-09")
    dates = calendar.sessions.strftime("%Y-%m-%d").tolist()
    pd.DataFrame({"cash_session":dates}).to_csv(OUT/"cash_calendar.csv", index=False)
    grouped = {d:g for d,g in frame.groupby("date")}
    excluded, complete, opening, events = [], [], [], []
    for date in dates:
        start = pd.Timestamp(date+" 09:30", tz=TZ)
        expected = pd.date_range(start, periods=135, freq="min")
        g = grouped.get(date, frame.iloc[:0])
        missing = expected.difference(g.index)
        if len(missing) or g.instrument_id.nunique() != 1:
            excluded.append({"date":date, "missing_minutes":len(missing), "missing_times":";".join(missing.strftime("%H:%M")), "reason":"missing minutes" if len(missing) else "contract change"})
            continue
        complete.append(date)
        for window in [5,10,15]:
            early = g.iloc[:window]
            o,e = float(early.open.iloc[0]),float(early.close.iloc[-1])
            hi,lo = float(early.high.max()),float(early.low.min())
            a, span = abs(e-o), hi-lo
            row = {"date":date, "year":int(date[:4]), "month":date[:7], "window":window,
                "open":o, "checkpoint_close":e, "high":hi, "low":lo,
                "range_pts":span, "abs_net_pts":a, "net_pts":e-o,
                "up_excursion_pts":hi-o, "down_excursion_pts":o-lo,
                "range_bps":span/o*10000, "abs_net_bps":a/o*10000,
                "efficiency":a/span if span else 0., "direction":"up" if e>o else "down" if e<o else "flat",
                "directional_push":bool(a>=20 and span and a/span>=.6)}
            opening.append(row)
            if not a:
                continue
            for horizon in [60,120]:
                future = g.iloc[window:window+horizon]
                assert len(future) == horizon
                assert future.index[0] == start+pd.Timedelta(minutes=window)
                result = path_metrics(o,e,future)
                events.append(dict(row, horizon=horizon, deadline=(start+pd.Timedelta(minutes=window+horizon)).strftime("%H:%M"), **result))
    opening = pd.DataFrame(opening)
    events = pd.DataFrame(events)
    events["size_bin"] = pd.cut(events.abs_net_pts, [0,10,20,40,80,np.inf], right=False, labels=["0-<10", "10-<20", "20-<40", "40-<80", "80+"]).astype(str)
    opening.to_csv(OUT/"opening_sessions.csv", index=False)
    events.to_csv(OUT/"followup_events.csv", index=False)
    pd.DataFrame(excluded).to_csv(OUT/"excluded_sessions.csv", index=False)
    opening_summary, outcomes, directions, sizes, years, yearly_opening = [],[],[],[],[],[]
    for period, mask in [("all", opening.year>=0), ("2024 onward", opening.year>=2024)]:
        for w,g in opening[mask].groupby("window"):
            opening_summary.append(stats_open(g,{"period":period,"window":int(w)}))
    for (yr,w),g in opening.groupby(["year","window"]):
        yearly_opening.append(stats_open(g,{"year":int(yr),"window":int(w)}))
    for period, mask in [("all", events.year>=0), ("2024 onward", events.year>=2024)]:
        for sample, condition in [("all_nonflat", np.ones(len(events),dtype=bool)), ("directional_push", events.directional_push)]:
            selected = events[mask & condition]
            for (w,h),g in selected.groupby(["window","horizon"]):
                meta = {"period":period,"sample":sample,"window":int(w),"horizon":int(h)}
                outcomes.append(summarize(g,meta,ci=True))
                for direction, sub in g.groupby("direction"):
                    directions.append(summarize(sub,dict(meta,direction=direction)))
            if period == "all":
                for (yr,w,h),g in selected.groupby(["year","window","horizon"]):
                    years.append(summarize(g,{"year":int(yr),"sample":sample,"window":int(w),"horizon":int(h)}))
        for (w,h,b),g in events[mask].groupby(["window","horizon","size_bin"]):
            sizes.append(summarize(g,{"period":period,"window":int(w),"horizon":int(h),"size_bin":b}))
    tables = {"opening_summary":opening_summary,"outcome_summary":outcomes,"direction_summary":directions,"size_summary":sizes,"yearly_outcomes":years,"yearly_opening":yearly_opening}
    for name, rows in tables.items():
        pd.DataFrame(rows).to_csv(OUT/(name+".csv"),index=False)
    assert len(opening) == len(complete)*3
    assert len(events) == (len(opening)-int((opening.net_pts==0).sum()))*2
    assert (events.full_retrace <= events.half_retrace).all()
    assert (events.clean_continuation <= events.extension).all()
    for w in [5,10,15]:
        e1=events[(events.window==w)&(events.horizon==60)].set_index("date")
        e2=events[(events.window==w)&(events.horizon==120)].set_index("date")
        for col in ["half_retrace","full_retrace","extension"]:
            assert (e1[col] <= e2[col]).all()
    metadata = {"report_date":"2026-10-28","data_version":manifest["id"],"data_path":str(path),"sha256":actual,
        "source_symbol":str(raw.symbol.iloc[0]),"raw_rows":len(raw),"raw_first_utc":raw.index[0].isoformat(),"raw_last_utc":raw.index[-1].isoformat(),
        "first_session":complete[0],"last_session":complete[-1],"calendar_sessions":len(dates),"included_sessions":len(complete),
        "excluded_sessions":excluded,"non_cash_dates_with_morning_data":sorted(set(grouped)-set(dates)),
        "calendar_version":xcals.__version__,"common_complete_span":"09:30 inclusive to 11:45 exclusive America/New_York",
        "no_contract_changes_within_included_windows":True,"dataset_warnings":manifest["warnings"],
        "protocol_sha256":digest(CAMPAIGN/"protocol.json"),"script_sha256":digest(__file__),"python_version":sys.version,"numpy_version":np.__version__,"pandas_version":pd.__version__,
        "study_type":protocol["type"],"protocol":protocol}
    (OUT/"summary.json").write_text(json.dumps(dict(metadata=metadata,**tables),indent=2,allow_nan=False),encoding="utf-8")
    (OUT/"data_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    (OUT/"protocol.json").write_text(json.dumps(protocol,indent=2),encoding="utf-8")
    print(json.dumps({k:metadata[k] for k in ["first_session","last_session","calendar_sessions","included_sessions","excluded_sessions"]},indent=2))
    print(pd.DataFrame(opening_summary)[["period","window","n","range_pts_mean","range_pts_median","abs_net_pts_mean","abs_net_pts_median"]].to_string(index=False))
    print(pd.DataFrame(outcomes).query("period == 'all'")[["sample","window","horizon","n","full_retrace_pct","extension_pct","clean_continuation_pct","reversion_first_pct","extension_first_pct","ambiguous_pct","neither_pct"]].to_string(index=False))


if __name__ == "__main__":
    main()
