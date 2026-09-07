"""Full MNQ one-minute history plus three DOM sample weeks, estimated before purchase.

Run from any directory with the repository .venv/bin/python:
    scripts/mnq/fetch_dom_sample.py estimate
    scripts/mnq/fetch_dom_sample.py download --max-cost-usd APPROVED_AMOUNT

Prices are estimates, not a provider-enforced billing limit. Batch job IDs are
saved before download so interrupted downloads reuse already purchased jobs.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import time
import threading
from zoneinfo import ZoneInfo

import databento as db
from dotenv import dotenv_values
import pandas as pd
import requests as http

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "data" / "mnq_dom_sample"
SEED = 2026082025
ADDITIONAL_SEED = 2026082024
# Fixed reviewable interval: launch-session open through September 3, 2026 UTC.
# Keeping the end fixed also makes interrupted batch downloads reproducible.
CANDLE_START = "2019-05-05T22:00:00+00:00"
CANDLE_END = "2026-09-04T00:00:00+00:00"


def random_week(year, seed):
    candidates = []
    day = date(year, 1, 1)
    while day.year == year:
        if day.weekday() == 0 and (day + timedelta(days=4)).year == year:
            candidates.append(day)
        day += timedelta(days=1)
    return random.Random(seed).choice(candidates)


def requests():
    selected = [random_week(2025, SEED), date(2026, 8, 17),
                random_week(2024, ADDITIONAL_SEED)]
    result = [{
        "week": "full_history",
        "request": {"dataset": "GLBX.MDP3", "symbols": ["MNQ.v.0"],
                    "stype_in": "continuous", "schema": "ohlcv-1m",
                    "start": CANDLE_START, "end": CANDLE_END},
    }]
    for monday in selected:
        start = datetime.combine(monday - timedelta(days=1), datetime.min.time())
        start = start.replace(hour=18, tzinfo=ZoneInfo("America/New_York"))
        end = datetime.combine(monday + timedelta(days=4), datetime.min.time())
        end = end.replace(hour=17, tzinfo=ZoneInfo("America/New_York"))
        result.append({
            "week": str(monday),
            "request": {"dataset": "GLBX.MDP3", "symbols": ["MNQ.v.0"],
                        "stype_in": "continuous", "schema": "mbp-10",
                        "start": start.astimezone(timezone.utc).isoformat(),
                        "end": end.astimezone(timezone.utc).isoformat()},
        })
    return result


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def retry_api(call, description, attempts=6):
    """Retry idempotent Databento metadata calls after transient network errors."""
    for attempt in range(attempts):
        try:
            return call()
        except Exception:
            if attempt == attempts - 1:
                raise
            delay = min(2 ** attempt, 30)
            print(f"Transient error during {description}; retrying in {delay}s", flush=True)
            time.sleep(delay)


def estimate(client):
    entries = requests()
    for entry in entries:
        req = entry["request"]
        entry["estimated_cost_usd"] = retry_api(
            lambda: client.metadata.get_cost(**req), "cost estimate")
        entry["billable_uncompressed_bytes"] = retry_api(
            lambda: client.metadata.get_billable_size(**req), "size estimate")
        mapping = retry_api(lambda: client.symbology.resolve(
            dataset=req["dataset"], symbols=req["symbols"], stype_in="continuous",
            stype_out="instrument_id", start_date=req["start"][:10],
            end_date=str(date.fromisoformat(req["end"][:10]) +
                         (timedelta(0) if datetime.fromisoformat(req["end"]).hour == 0
                          else timedelta(days=1))),
        ), "symbol mapping")
        if mapping.get("not_found") or mapping.get("partial"):
            raise RuntimeError(f"Incomplete symbol mapping for {entry['week']}")
        entry["instrument_mapping"] = mapping
        print(f"{entry['week']} {req['schema']}: "
              f"${entry['estimated_cost_usd']:.4f}, "
              f"{entry['billable_uncompressed_bytes'] / 1e9:.3f} GB uncompressed",
              flush=True)
    report = {"random_seeds": {"2025": SEED, "2024": ADDITIONAL_SEED},
              "selection": "Uniform choice among calendar-complete Mon-Fri weeks in each of 2025 and 2024; August 17, 2026 fixed",
              "suggested_holdout_week": str(random_week(2024, ADDITIONAL_SEED)),
              "estimated_at": datetime.now(timezone.utc).isoformat(),
              "entries": entries,
              "total_estimated_cost_usd": sum(e["estimated_cost_usd"] for e in entries)}
    save(OUTPUT / "estimate.json", report)
    return report


def export_candles(directory):
    files = sorted(directory.glob("*.dbn.zst")) + sorted(directory.glob("*.dbn"))
    if not files:
        raise RuntimeError(f"No DBN candle files found in {directory}")
    frame = pd.concat([db.DBNStore.from_file(p).to_df() for p in files]).sort_index()
    if frame.empty or frame.index.tz is None:
        raise RuntimeError("Empty or timezone-naive candle data")
    keys = frame.reset_index()
    if keys.duplicated([keys.columns[0], "instrument_id"]).any():
        raise RuntimeError("Duplicate candle timestamp/instrument pairs")
    if ((frame.high < frame[["open", "close", "low"]].max(axis=1)) |
            (frame.low > frame[["open", "close", "high"]].min(axis=1))).any():
        raise RuntimeError("Invalid candle OHLC ordering")
    frame.index = frame.index.tz_convert("UTC")
    frame.to_parquet(directory.parent / "candles_1m.parquet")
    return {"rows": len(frame), "first": str(frame.index.min()),
            "last": str(frame.index.max()), "instrument_ids": frame.instrument_id.unique().tolist()}


def download_files(client, job_id, folder):
    """Fetch the prepared files directly, avoiding slow on-demand ZIP assembly."""
    manifest = client.batch.list_files(job_id)
    if not manifest:
        raise RuntimeError(f"Empty batch manifest for {job_id}")
    save(folder / "file_manifest.json",
         [{k: f[k] for k in ("filename", "size", "hash")} for f in manifest])
    directory = folder / job_id
    directory.mkdir(parents=True, exist_ok=True)
    local = threading.local()

    def checksum(path):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(block)
        return "sha256:" + digest.hexdigest()

    def fetch(file):
        name = file["filename"]
        if Path(name).name != name:
            raise RuntimeError("Unexpected nested batch filename")
        target = directory / name
        partial = target.with_name(name + ".part")
        if target.exists() and target.stat().st_size == file["size"] and checksum(target) == file["hash"]:
            return target
        if not hasattr(local, "session"):
            local.session = http.Session()
            local.session.auth = (client.key, "")
        for attempt in range(5):
            try:
                offset = partial.stat().st_size if partial.exists() else 0
                if offset >= file["size"]:
                    if offset == file["size"] and checksum(partial) == file["hash"]:
                        partial.replace(target)
                        return target
                    partial.unlink()
                    offset = 0
                headers = {"Range": f"bytes={offset}-"} if offset else {}
                with local.session.get(file["urls"]["https"], headers=headers,
                                       stream=True, timeout=(15, 60)) as response:
                    if response.status_code == 429:
                        time.sleep(min(30, int(response.headers.get("Retry-After", "5"))))
                        continue
                    if response.status_code not in (200, 206):
                        raise RuntimeError(f"HTTP {response.status_code} downloading {name}")
                    append = offset > 0 and response.status_code == 206
                    if response.status_code == 206 and not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                        raise RuntimeError(f"Unexpected range response downloading {name}")
                    with partial.open("ab" if append else "wb") as stream:
                        for block in response.iter_content(chunk_size=1024 * 1024):
                            stream.write(block)
                if partial.stat().st_size != file["size"] or checksum(partial) != file["hash"]:
                    partial.unlink()
                    raise RuntimeError(f"Size or checksum mismatch downloading {name}")
                partial.replace(target)
                return target
            except (http.RequestException, RuntimeError):
                if attempt == 4:
                    raise RuntimeError(f"Download failed after retries: {name}") from None
                time.sleep(min(2 ** attempt, 15))
        raise RuntimeError(f"Repeated throttling downloading {name}")

    files = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch, file) for file in manifest]
        for future in as_completed(futures):
            files.append(future.result())
            if len(files) % 100 == 0 or len(manifest) < 25 or len(files) == len(manifest):
                print(f"{job_id}: verified {len(files)}/{len(manifest)} files", flush=True)
    return files


def download(client, report, cap):
    total = report["total_estimated_cost_usd"]
    if not math.isfinite(cap) or cap < 0 or total > cap:
        raise RuntimeError(f"Estimate ${total:.4f} exceeds valid cap ${cap}")
    required = sum(e["billable_uncompressed_bytes"] for e in report["entries"])
    if shutil.disk_usage(OUTPUT).free < required + 5 * 2**30:
        raise RuntimeError("Insufficient disk space using conservative uncompressed-size estimate")
    pending = []
    for entry in report["entries"]:
        req = entry["request"]
        folder = OUTPUT / entry["week"] / req["schema"]
        state_path = folder / "job.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else None
        if state and state["request"] != req:
            raise RuntimeError("Existing job has different request parameters")
        if state and not state.get("job_id"):
            raise RuntimeError(f"Submission uncertain: reconcile {state_path} with Databento Download center before retrying")
        if not state:
            state = {"request": req, "status": "submitting"}
            save(state_path, state)
            job = client.batch.submit_job(**req, encoding="dbn", compression="zstd",
                                          split_duration="day", delivery="download")
            state.update(job_id=job["id"], status="submitted")
            save(state_path, state)
            print(f"Submitted {entry['week']} {req['schema']}: {state['job_id']}", flush=True)
        if state.get("status") == "downloaded":
            if all((folder / p).exists() for p in state["files"]):
                print(f"Already downloaded: {entry['week']} {req['schema']}", flush=True)
                continue
        pending.append((entry, folder, state_path, state))
    while pending:
        jobs = retry_api(
            lambda: client.batch.list_jobs(states="queued,processing,done,expired"),
            "batch status")
        for item in pending[:]:
            entry, folder, state_path, state = item
            req = entry["request"]
            job_id = state["job_id"]
            job = next((j for j in jobs if j["id"] == job_id), None)
            if job is None or job["state"] == "expired":
                raise RuntimeError(f"Job {job_id} unavailable; inspect Download center, do not resubmit automatically")
            if job["state"] != "done":
                print(f"{job_id}: {job['state']}", flush=True)
                continue
            print(f"Downloading {entry['week']} {req['schema']}", flush=True)
            files = download_files(client, job_id, folder)
            state["files"] = [str(Path(p).relative_to(folder)) for p in files]
            if req["schema"] == "ohlcv-1m":
                state["candles"] = export_candles(folder / job_id)
            state["status"] = "downloaded"
            save(state_path, state)
            pending.remove(item)
            print(f"Downloaded {entry['week']} {req['schema']} to {folder}", flush=True)
        if pending:
            time.sleep(15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["estimate", "download"])
    parser.add_argument("--max-cost-usd", type=float)
    args = parser.parse_args()
    if args.action == "download" and args.max_cost_usd is None:
        parser.error("download requires --max-cost-usd after reviewing the estimate")
    config = {**dotenv_values(ROOT / ".env"), **dotenv_values(ROOT / ".env.local"), **os.environ}
    key = config.get("DATABENTO_APIKEY") or config.get("DATABENTO_API_KEY")
    if not key:
        raise SystemExit("No Databento key configured in environment or .env.local")
    client = db.Historical(key)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    lock = OUTPUT / ".running"
    try:
        with lock.open("x") as handle:
            handle.write(str(os.getpid()))
    except FileExistsError:
        raise SystemExit(f"Another run may be active. Check the PID in {lock} before removing a stale lock.")
    try:
        report = estimate(client)
        print(f"Total estimate: ${report['total_estimated_cost_usd']:.4f}", flush=True)
        if args.action == "download":
            download(client, report, args.max_cost_usd)
    except Exception as exc:
        raise SystemExit(f"{type(exc).__name__}: {str(exc).replace(key, '[REDACTED]')}") from None
    finally:
        lock.unlink()


if __name__ == "__main__":
    main()
