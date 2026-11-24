"""Read-only Databento cost quotes for preselected MNQ development mornings.

Only metadata.get_cost is called. No market data is requested or purchased.
Selection uses the existing 1-minute source solely to identify first-15-minute
reachability of either 40-point band from the 09:30 open, not any later outcome.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import deque
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import threading
import time

import databento as db
from dotenv import dotenv_values
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / "reports/mnq-ny-open-2026-10-28"
OUTPUT = HERE / "opening_windows_quote.json"
WORKERS = 20
MAX_STARTS_PER_SECOND = 8
MAX_ATTEMPTS = 5


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def save(value):
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(OUTPUT)


def prepare_requests():
    meta = json.loads((BASE / "summary.json").read_text())["metadata"]
    source = Path(meta["data_path"])
    source_hash = sha(source)
    if source_hash != meta["sha256"]:
        raise ValueError("Registered source checksum mismatch")
    frame = pd.read_parquet(source, columns=["open", "high", "low", "close", "instrument_id"])
    assert frame.index.is_monotonic_increasing and not frame.index.has_duplicates
    frame = frame.tz_convert("America/New_York").between_time("09:30", "11:44").copy()
    frame["date"] = frame.index.strftime("%Y-%m-%d")
    groups = dict(tuple(frame.groupby("date")))
    inclusion = pd.read_csv(BASE / "opening_sessions.csv", usecols=["date", "window", "open", "high", "low"])
    prior_dates = sorted(inclusion.date.unique())
    assert len(prior_dates) == meta["included_sessions"] == 1841
    development_dates = [date for date in prior_dates if "2019-05-06" <= date <= "2023-12-31"]
    selected, entries = [], []
    for date in development_dates:
        group = groups[date]
        expected = pd.date_range(date + " 09:30", periods=135, freq="min", tz="America/New_York")
        assert group.index.equals(expected.rename(group.index.name))
        assert group.instrument_id.nunique() == 1
        initial = group.iloc[:15]
        origin = float(initial.open.iloc[0])
        reachable = bool(initial.high.max() >= origin + 40 or initial.low.min() <= origin - 40)
        if not reachable:
            continue
        selected.append(date)
        start = pd.Timestamp(date + " 09:30:00", tz="America/New_York").tz_convert("UTC")
        end = pd.Timestamp(date + " 11:46:00", tz="America/New_York").tz_convert("UTC")
        entries.append({"date": date, "selection": "Either 40-point band reached during the first 15 minutes",
                        "request": {"dataset": "GLBX.MDP3", "symbols": ["MNQ.v.0"],
                                    "stype_in": "continuous", "schema": "trades",
                                    "start": start.isoformat().replace("+00:00", "Z"),
                                    "end": end.isoformat().replace("+00:00", "Z")},
                        "status": "pending", "estimated_cost_usd": None, "attempts": 0, "errors": []})
    crosscheck = inclusion[(inclusion.window == 15) & (inclusion.date >= "2019-05-06") &
                          (inclusion.date <= "2023-12-31")]
    crosscheck = crosscheck[(crosscheck.high - crosscheck.open >= 40) | (crosscheck.open - crosscheck.low >= 40)]
    assert selected == sorted(crosscheck.date.tolist())
    assert len(selected) == 724, f"Unexpected selected development sample: {len(selected)}"
    return entries, {"data_version": meta["data_version"], "data_path": str(source),
                     "data_sha256": source_hash, "prior_summary_sha256": sha(BASE / "summary.json"),
                     "prior_inclusion_file": str(BASE / "opening_sessions.csv"),
                     "prior_inclusion_sha256": sha(BASE / "opening_sessions.csv"),
                     "prior_calendar_sha256": sha(BASE / "cash_calendar.csv"),
                     "development_complete_sessions": len(development_dates),
                     "selection_dates_sha256": json_sha(selected), "selected_dates": selected,
                     "request_list_sha256": json_sha([entry["request"] for entry in entries])}


def main():
    entries, manifest = prepare_requests()
    config = {**dotenv_values(ROOT / ".env"), **dotenv_values(ROOT / ".env.local"), **os.environ}
    key = config.get("DATABENTO_APIKEY") or config.get("DATABENTO_API_KEY")
    if not key:
        raise SystemExit("No configured Databento key is available")
    report = {"purpose": "Metadata cost quotes only; no market-data purchase, download, or order",
              "status": "quoting", "started_at_utc": now(), "updated_at_utc": now(),
              "scope": "Development only: complete cash sessions from2019-05-06 through2023-12-31 on which either40-point band from09:30open is reached before09:45; all larger threshold cohorts are subsets",
              "window": "09:30:00 inclusive to11:46:00 exclusive America/New_York on each selected date, converted individually to UTC with DST",
              "selection_excludes_outcome_information": True,
              "estimate_is_not_provider_enforced_spending_cap": True,
              "method": "metadata.get_cost only,20 concurrent workers,global sliding-window limit of8 request starts/second,up to five attempts,respect429/Retry-After,graceful interrupt checkpoints",
              "rate_limit_reference": "https://databento.com/docs/api-historical/basics/rate-limits",
              "source_sha256": sha(__file__), "databento_version": db.__version__,
              "manifest": manifest, "selected_request_count": len(entries),
              "entries": entries}
    if OUTPUT.exists():
        old = json.loads(OUTPUT.read_text())
        if old["manifest"]["request_list_sha256"] != manifest["request_list_sha256"]:
            raise ValueError("Existing quote has a different selected request list")
        if old["manifest"]["data_sha256"] != manifest["data_sha256"]:
            raise ValueError("Existing quote has a different source dataset")
        prior = {entry["date"]: entry for entry in old["entries"]}
        for index, entry in enumerate(entries):
            previous = prior.get(entry["date"])
            if previous and previous["status"] == "quoted" and previous["request"] == entry["request"]:
                entries[index] = previous
        report["resumed_from_started_at_utc"] = old.get("started_at_utc")
    local = threading.local()
    stop = threading.Event()
    starts = deque()
    rate_lock = threading.Lock()

    def request_stop(signum, frame):
        stop.set()
        print("Interrupt received; retaining completed quotes and waiting for active metadata calls to finish.", flush=True)

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, request_stop)

    def permit():
        while not stop.is_set():
            with rate_lock:
                clock = time.monotonic()
                while starts and starts[0] <= clock - 1:
                    starts.popleft()
                if len(starts) < MAX_STARTS_PER_SECOND:
                    starts.append(clock)
                    return True
                delay = max(0.001, starts[0] + 1 - clock)
            stop.wait(min(delay, 0.25))
        return False

    def retry_after(exc):
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None) or getattr(exc, "headers", None) or {}
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if not raw:
            return None
        try:
            return max(0., float(raw))
        except (ValueError, TypeError):
            try:
                value = parsedate_to_datetime(raw)
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                return max(0., (value - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                return None

    def quote(entry):
        result = dict(entry, errors=list(entry["errors"]))
        if not hasattr(local, "client"):
            local.client = db.Historical(key)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if not permit():
                result.update(status="pending", estimated_cost_usd=None)
                return result
            result["attempts"] = attempt
            try:
                # This is the sole network endpoint used by this script.
                cost = float(local.client.metadata.get_cost(**entry["request"]))
                if not math.isfinite(cost) or cost < 0:
                    raise ValueError("Metadata returned an invalid cost")
                result.update(status="quoted", estimated_cost_usd=cost, quoted_at_utc=now())
                return result
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                if status_code is None:
                    status_code = getattr(getattr(exc, "response", None), "status_code", None)
                # Persist only type/status; exception strings can contain URLs
                # or credentials and are deliberately never logged.
                result["errors"].append({"attempt": attempt, "error_type": type(exc).__name__,
                                         "http_status": status_code if isinstance(status_code, int) else None,
                                         "at_utc": now()})
                if status_code in (400, 401, 403, 404, 422) or attempt == MAX_ATTEMPTS:
                    break
                delay = max(min(2 ** (attempt - 1), 8), retry_after(exc) or 0)
                if stop.wait(delay):
                    result.update(status="pending", estimated_cost_usd=None)
                    return result
        result.update(status="error", estimated_cost_usd=None)
        return result

    def checkpoint(final=False):
        completed = [entry for entry in entries if entry["status"] == "quoted"]
        errors = [entry for entry in entries if entry["status"] == "error"]
        pending = [entry for entry in entries if entry["status"] == "pending"]
        report.update(updated_at_utc=now(), quoted_request_count=len(completed),
                      failed_request_count=len(errors), pending_request_count=len(pending),
                      partial_estimated_cost_usd=sum(entry["estimated_cost_usd"] for entry in completed),
                      total_estimated_cost_usd=(sum(entry["estimated_cost_usd"] for entry in completed)
                                                if len(completed) == len(entries) else None))
        if final:
            report["status"] = "complete" if len(completed) == len(entries) else "incomplete"
            report["finished_at_utc"] = now()
            report["interrupted"] = stop.is_set()
        save(report)
        print(json.dumps({"status": report["status"], "quoted": len(completed), "errors": len(errors),
                          "pending": len(pending), "requests": len(entries),
                          "estimated_sum_usd": report["partial_estimated_cost_usd"]}), flush=True)

    checkpoint()
    pending_indices = [i for i, entry in enumerate(entries) if entry["status"] != "quoted"]
    if pending_indices:
        first = pending_indices.pop(0)
        entries[first] = quote(entries[first])
        if entries[first]["status"] != "quoted":
            checkpoint(final=True)
            raise SystemExit("Initial metadata quote failed; further calls were not launched")
        checkpoint()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(quote, entries[i]): i for i in pending_indices}
        completed_since_save = 0
        for future in as_completed(futures):
            index = futures[future]
            entries[index] = future.result()
            completed_since_save += 1
            if completed_since_save >= 10:
                checkpoint()
                completed_since_save = 0
    checkpoint(final=True)


if __name__ == "__main__":
    main()
