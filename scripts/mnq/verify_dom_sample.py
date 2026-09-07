"""Verify the purchased MNQ archive; only free Databento metadata calls are used.

Checks every downloaded file against provider SHA-256 hashes, scans every DOM
record for coverage and instrument IDs, and validates the exported candles.
Writes data/mnq_dom_sample/validation.json and daily coverage CSVs.
"""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import warnings

import databento as db
from dotenv import dotenv_values
import numpy as np
import pandas as pd

from fetch_dom_sample import OUTPUT, ROOT, save


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def scan_dom(path, request):
    store = db.DBNStore.from_file(path)
    if str(store.schema) != "mbp-10":
        raise ValueError(f"Wrong schema in {path}")
    start = pd.Timestamp(request["start"]).value
    end = pd.Timestamp(request["end"]).value
    result = {"file": path.name, "records": 0, "first_ts_recv_ns": None,
              "last_ts_recv_ns": None, "out_of_range": 0,
              "sampled_quotes": 0, "sampled_crossed_quotes": 0}
    instruments = Counter()
    flags = Counter()
    day_counts = Counter()
    for rows in store.to_ndarray(count=200_000):
        rows = rows.reshape(-1)
        if not len(rows):
            continue
        if not np.all(rows["rtype"] == 10):
            raise ValueError(f"Unexpected record type in {path}")
        ts = rows["ts_recv"]
        lo, hi = int(ts.min()), int(ts.max())
        result["records"] += len(rows)
        result["first_ts_recv_ns"] = min(result["first_ts_recv_ns"] or lo, lo)
        result["last_ts_recv_ns"] = max(result["last_ts_recv_ns"] or hi, hi)
        result["out_of_range"] += int(np.count_nonzero((ts < start) | (ts >= end)))
        for name, counts in [("instrument_id", instruments), ("flags", flags)]:
            values, totals = np.unique(rows[name], return_counts=True)
            counts.update({int(k): int(v) for k, v in zip(values, totals)})
        values, totals = np.unique(ts // 86_400_000_000_000, return_counts=True)
        day_counts.update({int(k): int(v) for k, v in zip(values, totals)})
        # Sample quote consistency; intermediate event states can be crossed.
        sample = rows[::max(1, len(rows) // 1000)]
        valid = ((sample["bid_sz_00"] > 0) & (sample["ask_sz_00"] > 0) &
                 (sample["bid_px_00"] != np.iinfo(np.int64).max) &
                 (sample["ask_px_00"] != np.iinfo(np.int64).max))
        result["sampled_quotes"] += int(valid.sum())
        result["sampled_crossed_quotes"] += int(np.count_nonzero(
            valid & (sample["bid_px_00"] > sample["ask_px_00"])))
    result["instrument_records"] = dict(instruments)
    result["flag_records"] = dict(flags)
    result["records_by_utc_date"] = {
        str(pd.Timestamp(day, unit="D").date()): count
        for day, count in sorted(day_counts.items())}
    if result["out_of_range"]:
        raise ValueError(f"DOM timestamps outside requested interval: {path}")
    return result


def validate(client):
    estimate = json.loads((OUTPUT / "estimate.json").read_text())
    jobs = {j["id"]: j for j in client.batch.list_jobs(states="done")}
    previous_path = OUTPUT / "validation.json"
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
    cached = {entry["job_id"]: entry for entry in previous.get("entries", [])}
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "entries": []}
    bars_entry = next(e for e in estimate["entries"] if e["request"]["schema"] == "ohlcv-1m")
    bar_path = OUTPUT / bars_entry["week"] / "ohlcv-1m" / "candles_1m.parquet"
    bars = pd.read_parquet(bar_path)
    if bars.empty or bars.index.tz is None or not bars.index.is_monotonic_increasing:
        raise ValueError("Candles are empty, timezone-naive, or not sorted")
    keys = bars.reset_index()
    if keys.duplicated([keys.columns[0], "instrument_id"]).any():
        raise ValueError("Duplicate candle timestamp/instrument pairs")
    if bars[["open", "high", "low", "close", "volume"]].isna().any().any():
        raise ValueError("Missing candle values")
    if ((bars.high < bars[["open", "close", "low"]].max(axis=1)) |
            (bars.low > bars[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("Invalid candle OHLC ordering")
    if ((bars.index < pd.Timestamp(bars_entry["request"]["start"])) |
            (bars.index >= pd.Timestamp(bars_entry["request"]["end"]))).any():
        raise ValueError("Candles outside requested interval")
    bars.groupby(bars.index.year).size().rename("bars").to_csv(OUTPUT / "candles_by_year.csv")
    report["candles"] = {"rows": len(bars), "first": str(bars.index.min()),
                         "last": str(bars.index.max()), "path": str(bar_path.relative_to(ROOT))}
    for entry in estimate["entries"]:
        req = entry["request"]
        folder = OUTPUT / entry["week"] / req["schema"]
        state = json.loads((folder / "job.json").read_text())
        if state["status"] != "downloaded":
            print(f"Pending download: {entry['week']}", flush=True)
            continue
        job_id = state["job_id"]
        fingerprint = [{"path": name, "size": (folder / name).stat().st_size,
                        "mtime_ns": (folder / name).stat().st_mtime_ns}
                       for name in state["files"]]
        if job_id in cached and cached[job_id].get("file_fingerprint") == fingerprint:
            report["entries"].append(cached[job_id])
            print(f"Previously verified and unchanged: {entry['week']}", flush=True)
            continue
        remote = client.batch.list_files(job_id)
        manifests = [{k: f[k] for k in ("filename", "size", "hash")} for f in remote]
        save(folder / "file_manifest.json", manifests)
        result = {"week": entry["week"], "schema": req["schema"], "job_id": job_id,
                  "provider_cost_usd": jobs[job_id].get("cost_usd"),
                  "provider_record_count": jobs[job_id].get("record_count"),
                  "file_fingerprint": fingerprint,
                  "verified_files": 0, "downloaded_bytes": 0, "dom_files": []}
        for manifest in manifests:
            path = folder / job_id / manifest["filename"]
            if path.stat().st_size != manifest["size"] or file_hash(path) != manifest["hash"]:
                raise ValueError(f"Checksum or size mismatch: {path}")
            result["verified_files"] += 1
            result["downloaded_bytes"] += path.stat().st_size
            if req["schema"] == "mbp-10" and ".dbn" in path.name:
                print(f"Scanning {entry['week']} {path.name}", flush=True)
                result["dom_files"].append(scan_dom(path, req))
        if req["schema"] == "mbp-10":
            records = sum(f["records"] for f in result["dom_files"])
            if not records:
                raise ValueError(f"Empty DOM week: {entry['week']}")
            provider_count = result["provider_record_count"]
            if provider_count is not None and records != provider_count:
                raise ValueError(f"DOM record count mismatch: {entry['week']}: {records} != {provider_count}")
            result["records"] = records
            matching = bars.loc[(bars.index >= pd.Timestamp(req["start"])) &
                                (bars.index < pd.Timestamp(req["end"]))]
            observed_ids = {int(i) for f in result["dom_files"] for i in f["instrument_records"]}
            if not observed_ids.issubset(set(matching.instrument_id.unique())):
                raise ValueError("DOM instrument missing from matching candles")
            session_dates = (matching.index.tz_convert("America/New_York").tz_localize(None) +
                             pd.Timedelta(hours=6)).date
            counts = matching.groupby(session_dates).size()
            expected = set(pd.date_range(entry["week"], periods=5).date)
            if set(counts.index) != expected:
                raise ValueError("Missing candle trading session in DOM sample")
            counts.rename("bars").to_csv(folder / "matching_candles_by_session.csv")
            result["matching_candles"] = len(matching)
        elif result["provider_record_count"] is not None and len(bars) != result["provider_record_count"]:
            raise ValueError("Exported candle count differs from provider record count")
        report["entries"].append(result)
        save(OUTPUT / "validation.json", report)
        print(f"Verified {entry['week']} {req['schema']}: {result['verified_files']} files", flush=True)
    report["complete"] = len(report["entries"]) == len(estimate["entries"])
    save(OUTPUT / "validation.json", report)
    print("Validation complete" if report["complete"] else "Available files verified; other downloads pending", flush=True)


if __name__ == "__main__":
    config = {**dotenv_values(ROOT / ".env"), **dotenv_values(ROOT / ".env.local"), **os.environ}
    key = config.get("DATABENTO_APIKEY") or config.get("DATABENTO_API_KEY")
    if not key:
        raise SystemExit("No Databento key configured")
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("error", message=".*truncated.*")
            validate(db.Historical(key))
    except Exception as exc:
        raise SystemExit(f"{type(exc).__name__}: {str(exc).replace(key, '[REDACTED]')}") from None
