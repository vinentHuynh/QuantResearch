"""Fetch an estimated ES tail and register an immutable full-history dataset.

Requires reports/es-data-update-2026-09-29/estimate.json and availability.json.
The existing ES dataset and vendor archive remain unchanged. This is historical
Databento data; the request is billed and does not start a live subscription.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import urllib.request
import zipfile

import databento as db
from dotenv import dotenv_values
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/es-data-update-2026-09-29"
OUT = ROOT / "data/databento_updates/es-2026-09-29"
DATASETS = ROOT / "data/workbench/datasets"
BASE_ID = "dc30057c7601b72a17c66457345d743a805087cdd43f2acb0488344dbed104f9-v1"
COLS = ["open", "high", "low", "close", "volume", "instrument_id"]


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(2**20), b""):
            digest.update(block)
    return digest.hexdigest()


def save(path, value):
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def quality(frame):
    assert not frame.empty and str(frame.index.tz) == "UTC"
    assert frame.index.is_monotonic_increasing and not frame.index.has_duplicates
    assert (frame.index.asi8 % 60_000_000_000 == 0).all()
    prices = frame[["open", "high", "low", "close"]]
    assert np.isfinite(prices.to_numpy()).all()
    assert np.isfinite(frame.volume).all() and (frame.volume >= 0).all()
    assert (frame.high >= prices.max(axis=1)).all()
    assert (frame.low <= prices.min(axis=1)).all()
    return {
        "duplicates": 0,
        "unordered": 0,
        "invalid_ohlc": 0,
        "gaps_over_one_minute": int((frame.index.to_series().diff() > pd.Timedelta(minutes=1)).sum()),
        "contract_changes": int((frame.instrument_id.diff().iloc[1:] != 0).sum()),
    }


def workbench_verification(version, last):
    """Report whether a running Workbench sees the new and original datasets."""
    try:
        with socket.create_connection(("127.0.0.1", 8001), timeout=2):
            pass
    except OSError:
        return {"workbench_api_available": False, "workbench_registration_verified": False}

    result = {"workbench_api_available": True, "workbench_registration_verified": False}
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8001/api/workbench/state?view=summary", timeout=15
        ) as response:
            state = json.load(response)
        datasets = state["datasets"]
        result["workbench_registration_verified"] = (
            any(d["id"] == version and d["last"] == last for d in datasets)
            and any(d["id"] == BASE_ID for d in datasets)
        )
        if not result["workbench_registration_verified"]:
            result["workbench_api_error"] = "Updated or original ES dataset absent from Workbench response"
    except Exception as exc:
        result["workbench_api_error"] = str(exc)
    return result


def main(max_cost):
    estimate = json.loads((REPORT / "estimate.json").read_text(encoding="utf-8"))
    availability = json.loads((REPORT / "availability.json").read_text(encoding="utf-8"))
    req = estimate["request"]
    assert req["dataset"] == "GLBX.MDP3"
    assert req["symbols"] == ["ES.v.0"]
    assert req["stype_in"] == "continuous" and req["schema"] == "ohlcv-1m"
    cost = float(estimate["estimated_cost_usd"])
    assert math.isfinite(cost) and 0 <= cost <= max_cost
    start, end = pd.Timestamp(req["start"]), pd.Timestamp(req["end"])
    assert str(start.tz) == str(end.tz) == "UTC"
    assert start < end and end == end.floor("min")
    available_end = pd.Timestamp(availability["schema"]["ohlcv-1m"]["end"]).floor("min")
    assert end <= available_end

    catalog_path = DATASETS / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    base = next(d for d in catalog["datasets"] if d["id"] == BASE_ID)
    assert base["symbol"] == "ES" and base["query"]["symbols"] == ["ES.v.0"]
    assert base["query"]["schema"] == "ohlcv-1m" and base["query"]["dataset"] == "GLBX.MDP3"
    assert start == pd.Timestamp(base["last"]) + pd.Timedelta(minutes=1)
    assert sha(base["path"]) == base["checksum"]
    source_archive = ROOT / base["archive"]
    assert sha(source_archive) == base["archive_checksum"]

    OUT.mkdir(parents=True, exist_ok=True)
    start_tag = start.strftime("%Y%m%d")
    end_tag = end.strftime("%Y%m%dT%H%MZ")
    raw = OUT / f"glbx-mdp3-{start_tag}-{end_tag}.ohlcv-1m.dbn.zst"
    receipt_path = OUT / "download.json"
    if not raw.exists():
        if receipt_path.exists():
            raise RuntimeError("Prior download receipt exists without the raw file; reconcile before another billed request")
        partial = raw.with_name(raw.name + ".partial")
        if partial.exists():
            raise RuntimeError("Partial download exists; inspect it before another billed request")
        config = {**dotenv_values(ROOT / ".env"), **dotenv_values(ROOT / ".env.local"), **os.environ}
        key = config.get("DATABENTO_APIKEY") or config.get("DATABENTO_API_KEY")
        if not key:
            raise RuntimeError("Databento key is not configured")
        receipt = {
            "request": req,
            "estimated_cost_usd": cost,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "requesting",
        }
        save(receipt_path, receipt)
        try:
            db.Historical(key).timeseries.get_range(**req, stype_out="instrument_id", path=partial)
        except Exception as exc:
            receipt.update(status="failed", error=str(exc).replace(key, "[REDACTED]"))
            save(receipt_path, receipt)
            raise RuntimeError(receipt["error"]) from None
        os.replace(partial, raw)
        receipt.update(
            status="downloaded",
            finished_at_utc=datetime.now(timezone.utc).isoformat(),
            sha256=sha(raw),
            bytes=raw.stat().st_size,
        )
        save(receipt_path, receipt)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["request"] == req and receipt["sha256"] == sha(raw)
    tail = db.DBNStore.from_file(raw).to_df()[COLS]
    tail_quality = quality(tail)
    assert tail.index[0] >= start and tail.index[-1] < end
    tail.to_parquet(OUT / "ES_1m_update.parquet", compression="zstd")
    tail.to_csv(OUT / "ES_1m_update_UTC.csv", index_label="ts_event")
    print(f"Downloaded and validated {len(tail):,} ES minute bars; latest {tail.index[-1]}", flush=True)

    archive = OUT / f"ES-full-history-through-{end_tag}.zip"
    provenance = {
        "kind": "local_composite_databento_archive",
        "base_dataset_id": base["id"],
        "base_archive": base["archive"],
        "base_archive_sha256": base["archive_checksum"],
        "tail_file": raw.name,
        "tail_sha256": sha(raw),
        "download": receipt,
        "availability": availability,
        "old_bars_preserved": True,
    }
    if not archive.exists():
        partial_archive = archive.with_suffix(".partial.zip")
        if partial_archive.exists():
            raise RuntimeError("Partial composite archive exists; inspect it before rebuilding")
        with zipfile.ZipFile(source_archive) as old, zipfile.ZipFile(
            partial_archive, "w", zipfile.ZIP_STORED
        ) as new:
            metadata = json.loads(old.read("metadata.json"))
            assert metadata["query"]["symbols"] == ["ES.v.0"]
            metadata["job_id"] = f"LOCAL-COMPOSITE-ES-{end_tag}"
            metadata["query"]["end"] = int(end.value)
            metadata["customizations"] = {"packaging": "local-composite", "split_duration": "mixed"}
            metadata["provenance_file"] = "provenance.json"
            for name in sorted(n for n in old.namelist() if n.endswith(".dbn.zst")):
                new.writestr(name, old.read(name))
            new.write(raw, raw.name)
            new.writestr("metadata.json", json.dumps(metadata, indent=2))
            new.writestr("provenance.json", json.dumps(provenance, indent=2))
        os.replace(partial_archive, archive)
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        assert hashlib.sha256(zipped.read(raw.name)).hexdigest() == sha(raw)
        metadata = json.loads(zipped.read("metadata.json"))
        assert metadata["query"]["symbols"] == ["ES.v.0"]
        assert metadata["query"]["end"] == end.value
    digest = sha(archive)
    version = digest + "-v1"
    folder = DATASETS / version
    folder.mkdir(exist_ok=True)
    history = pd.read_parquet(base["path"])[COLS]
    assert len(history) == base["rows"] and history.index[-1] < tail.index[0]
    combined = pd.concat([history, tail])
    combined_quality = quality(combined)
    pd.testing.assert_frame_equal(combined.iloc[: len(history)], history)
    final = folder / "bars.parquet"
    if not final.exists():
        temporary = folder / "bars.partial.parquet"
        combined.to_parquet(temporary, compression="zstd")
        os.replace(temporary, final)
    pd.testing.assert_frame_equal(pd.read_parquet(final), combined)
    assert sha(base["path"]) == base["checksum"]
    assert sha(source_archive) == base["archive_checksum"]

    record = {
        **base,
        "id": version,
        "path": str(final.resolve()),
        "checksum": sha(final),
        "archive": archive.relative_to(ROOT).as_posix(),
        "archive_checksum": digest,
        "rows": len(combined),
        "first": combined.index[0].isoformat(),
        "last": combined.index[-1].isoformat(),
        "query": metadata["query"],
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "acquired_at": receipt["finished_at_utc"],
        "quality": combined_quality,
        "provenance": provenance,
        "warnings": [
            "Continuous volume-rolled prices are unadjusted; contract rolls can affect signals and P&L.",
            "Old history is preserved byte-for-value from the base dataset; only the tail was freshly acquired.",
            "Gaps include exchange closures and no-trade minutes; no forward filling was performed.",
            "Latest trading session may be partial. Historical availability is not a live subscription.",
        ],
    }
    save(folder / "dataset.json", record)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["datasets"] = [d for d in catalog["datasets"] if d["id"] != version] + [record]
    save(catalog_path, catalog)

    verification = workbench_verification(version, record["last"])
    report = {
        "status": "complete",
        "base_dataset_id": base["id"],
        "updated_dataset_id": version,
        "old_last_utc": base["last"],
        "added_bars": len(tail),
        "total_bars": len(combined),
        "first_utc": record["first"],
        "last_bar_open_utc": record["last"],
        "last_bar_open_chicago": tail.index[-1].tz_convert("America/Chicago").isoformat(),
        "last_bar_close_utc": (tail.index[-1] + pd.Timedelta(minutes=1)).isoformat(),
        "request": req,
        "estimated_cost_usd": cost,
        "tail_quality": tail_quality,
        "combined_quality": combined_quality,
        "historical_prefix_unchanged": True,
        "original_dataset_preserved": True,
        **verification,
        "dataset_path": str(final.resolve()),
        "tail_csv": str((OUT / "ES_1m_update_UTC.csv").resolve()),
        "archive": str(archive.resolve()),
        "availability": availability,
    }
    save(REPORT / "result.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "availability"}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-cost-usd", type=float, required=True)
    args = parser.parse_args()
    main(args.max_cost_usd)
