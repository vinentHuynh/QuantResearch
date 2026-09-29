"""Append-only local prospective SND evidence; never downloads or sends orders.

Commands: init freezes source/rules/time, check ingests local files, verify
audits preserved hashes. Checks use frozen code; importable helpers support tests.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import traceback

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "reports/snd-forward-2026-09-25"
CATALOG = ROOT / "data/workbench/datasets/catalog.json"
PRICE = ["open", "high", "low", "close"]
BAR_COLUMNS = PRICE + ["volume", "instrument_id"]


def utc_now():
    return pd.Timestamp(datetime.now(timezone.utc))


def utc(value):
    stamp = pd.Timestamp(value)
    if stamp.tz is None:
        raise ValueError("Explicit timezone required")
    return stamp.tz_convert("UTC")


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def jsonable(value):
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, np.generic):
        return jsonable(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(jsonable(value), stream, indent=2, allow_nan=False)


@contextmanager
def locked(out):
    lock = Path(out) / ".check.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(utc_now().isoformat())
    try:
        yield
    finally:
        lock.unlink()


def normalize(frame):
    frame = frame.copy()
    frame.columns = [str(c).lower() for c in frame.columns]
    if not isinstance(frame.index, pd.DatetimeIndex):
        key = next((c for c in ["ts_event", "timestamp"] if c in frame), None)
        if key is None:
            raise ValueError("Require UTC ts_event/timestamp or timezone-aware index")
        parsed = pd.to_datetime(frame.pop(key))
        if parsed.dt.tz is None:
            raise ValueError("Naive timestamps forbidden; provide explicit UTC")
        frame.index = pd.DatetimeIndex(parsed)
    if frame.index.tz is None:
        raise ValueError("Naive timestamps forbidden")
    frame.index = frame.index.tz_convert("UTC")
    frame.index.name = "ts_event"
    if frame.empty or frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError("Require nonempty, ordered, unique minute bars")
    if (frame.index.as_unit("ns").asi8 % 60_000_000_000).any():
        raise ValueError("Timestamps must be minute opens")
    if "instrument_id" not in frame and "contract" in frame:
        frame["instrument_id"] = frame["contract"]
    if any(c not in frame for c in BAR_COLUMNS):
        raise ValueError("Require OHLC, volume and instrument_id (or contract)")
    if frame.instrument_id.isna().any() or (frame.instrument_id.astype(str).str.strip() == "").any():
        raise ValueError("Every minute requires contract identity")
    frame["instrument_id"] = frame.instrument_id.astype(str)
    for c in PRICE + ["volume"]:
        frame[c] = pd.to_numeric(frame[c], errors="raise").astype(float)
    numbers = frame[PRICE + ["volume"]].to_numpy(float)
    if not np.isfinite(numbers).all() or (frame.volume < 0).any():
        raise ValueError("Invalid numeric values")
    if (frame.high < frame[PRICE].max(axis=1)).any() or (frame.low > frame[PRICE].min(axis=1)).any():
        raise ValueError("Invalid OHLC geometry")
    return frame[BAR_COLUMNS]


def load_bars(path):
    path = Path(path)
    return normalize(pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path))


def capture_class(index, received_at, start, max_delay_seconds):
    close = index + pd.Timedelta(minutes=1)
    return np.where(index < start, "prestart_context", np.where(
        (received_at - close).total_seconds() <= max_delay_seconds,
        "timely_ohlc_simulation", "delayed_replay"))


def merge_append(accepted, incoming, received_at, protocol, allow_context_backfill=False):
    """Exact overlaps are allowed; revisions and late insertions are rejected."""
    start = utc(protocol["start"])
    lower = start - pd.Timedelta(days=protocol["warmup_days"])
    incoming = incoming.loc[(incoming.index >= lower) &
                            (incoming.index + pd.Timedelta(minutes=1) <= received_at)].copy()
    if incoming.empty:
        return accepted, incoming, 0
    overlap = incoming.index.intersection(accepted.index)
    if len(overlap):
        old, new = accepted.loc[overlap, BAR_COLUMNS], incoming.loc[overlap, BAR_COLUMNS]
        changed = (old != new).any(axis=1)
        if changed.any():
            raise ValueError(f"Revision quarantined: {int(changed.sum())} accepted bars differ; first {overlap[changed][0]}")
    added = incoming.loc[~incoming.index.isin(accepted.index)].copy()
    late = added.loc[added.index <= accepted.index.max()] if len(accepted) else added.iloc[:0]
    if len(late) and not (allow_context_backfill and (late.index < start).all()):
        raise ValueError("Late insertion quarantined: would rewrite the accepted historical path")
    added["received_at"] = received_at.isoformat()
    added["capture_class"] = capture_class(added.index, received_at, start, protocol["max_delay_seconds"])
    combined = pd.concat([accepted, added]).sort_index() if len(accepted) else added.copy()
    return combined, added, len(overlap)


def warmup_status(accepted, protocol):
    start = utc(protocol["start"])
    lower = start - pd.Timedelta(days=protocol["warmup_days"])
    context = accepted.loc[(accepted.index >= lower) & (accepted.index < start)]
    if context.empty:
        return {"ready": False, "reasons": ["No prestart warmup bars"]}
    first, last = context.index[0], context.index[-1] + pd.Timedelta(minutes=1)
    gaps = context.index.to_series().diff().dt.total_seconds().div(3600)
    largest = float(gaps.max()) if len(context) > 1 else 0.
    reasons = []
    if first > lower + pd.Timedelta(hours=72):
        reasons.append("Warmup starts more than 72 hours after requested 30-day boundary")
    if last < start - pd.Timedelta(minutes=protocol["max_prestart_gap_minutes"]):
        reasons.append("Latest prestart bar is stale; require missing context before simulation")
    if largest > 80:
        reasons.append("Warmup has a gap larger than 80 hours")
    if len(context.index.normalize().unique()) < 15:
        reasons.append("Warmup covers fewer than 15 UTC dates")
    return dict(ready=not reasons, reasons=reasons, first=first, last_closed=last,
                rows=len(context), largest_gap_hours=largest,
                limitation="Coverage gate only; no exchange-holiday/minute-completeness certification")


def discover(protocol):
    candidates, errors = [], []
    catalog = Path(protocol["catalog"])
    if catalog.exists():
        for record in read(catalog).get("datasets", []):
            if record.get("symbol") == "MNQ" and record.get("timeframe") == "1m":
                candidates.append(dict(path=record["path"], expected_checksum=record["checksum"],
                                       origin="registered_immutable_dataset", dataset_id=record["id"]))
    else:
        errors.append("Dataset catalog unavailable")
    for path in sorted(Path(protocol["inbox"]).glob("*")):
        if path.is_file() and path.suffix.lower() in {".csv", ".parquet"}:
            candidates.append(dict(path=str(path.resolve()), origin="local_inbox"))
    return candidates, errors


def init(out, review_days=90, min_trades=100, max_delay_seconds=120, clock=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError("Init requires a new empty directory; never resets a frozen experiment")
    frozen_at = utc_now() if clock is None else utc(clock)
    start = frozen_at.ceil("5min")
    if start == frozen_at:
        start += pd.Timedelta(minutes=5)
    if review_days < 1 or min_trades < 1 or max_delay_seconds < 0:
        raise ValueError("Positive review/sample criteria and nonnegative delay required")
    baseline = read(ROOT / "reports/snd-entry-research-2026-09-25/MNQ/relaxed_first_1/input.json")
    base = baseline["parameters"] | dict(slippage_model="price", finalize=False, record_events=True)
    variants = {
        "fixed_one": base | dict(sizing_mode="fixed_contracts", contracts=1, risk_budget=100., max_contracts=10),
        "risk_100_max10": base | dict(sizing_mode="fixed_risk", contracts=1, risk_budget=100., max_contracts=10),
    }
    inbox = out / "inbox"
    inbox.mkdir()
    protocol = dict(schema_version=1, frozen_at=frozen_at, start=start, symbol="MNQ", variants=variants,
        tick_size=.25, point_value=2., fee=1.25, slippage_ticks=1, warmup_days=30,
        review_after=start + pd.Timedelta(days=review_days), review_days=review_days,
        min_closed_trades=min_trades, max_delay_seconds=max_delay_seconds,
        max_prestart_gap_minutes=72*60, catalog=str(CATALOG.resolve()), inbox=str(inbox.resolve()),
        primary="fixed_one", shadow="risk_100_max10",
        decision_rule=f"First formal review requires {review_days} calendar days AND {min_trades} closed primary trades, with data through the review boundary. The count includes delayed prospective replays and timely OHLC simulations, reported separately; it does not establish real-time fill validation. Each shadow reports its own sample. Continue unchanged until both primary criteria met. No automatic strategy promotion, tuning or live-trading decision.",
        review_metrics=["marked net PnL", "closed trades", "mean net R", "profit factor", "marked maximum drawdown", "risk budget overshoots", "timely versus delayed evidence", "missing/revised data"],
        evidence_policy=f"All bars before start are context, never prospective performance. Poststart bars received more than {max_delay_seconds} seconds after close are delayed replay. Timely OHLC simulation is not actual paper/broker fill evidence. Missing/revised/out-of-order data remains visible. No future data manufactured.",
        price_model="One adverse tick on gap-aware entry and nonlimit exit; target limit exact; commissions1.25per contract per side. Quantity frozen at signal;100dollar all-in estimated stop risk, whole contracts, cap10; gap risk can exceed budget.",
        data_policy="Local inbox and registered immutable MNQ1m versions only. No feed subscription, download, secret access or orders. Changed bars and poststart late insertions quarantined. Missing prestart context may be added only before the first simulation, with receipts retained. After simulation starts, every late insertion requires a separately documented corrected replay; never overwrite this primary path.",
        previous_exposure="Existing history and previous campaigns were inspected. The freeze time establishes a prospective boundary only for newly arriving bars.")
    save_new(out / "protocol.json", protocol)
    paths = ["scripts/forward-snd-frozen.py", "tests/test_snd_forward.py", "strategies/_snd_risk_research.py"]
    paths += [p.relative_to(ROOT).as_posix() for p in (ROOT / "strategy_engine").glob("*.py")]
    files = []
    for relative in paths:
        src, target = ROOT / relative, out / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        files.append(dict(path=relative, checksum=digest(target)))
    save_new(out / "environment.json", dict(python=sys.version, pandas=pd.__version__, numpy=np.__version__))
    save_new(out / "source-manifest.json", dict(protocol_checksum=digest(out / "protocol.json"),
                                               environment_checksum=digest(out / "environment.json"),
                                               files=files, frozen_at=frozen_at))
    return protocol


def verify(out):
    out = Path(out)
    manifest = read(out / "source-manifest.json")
    driver = next(e for e in manifest["files"] if e["path"] == "scripts/forward-snd-frozen.py")
    if digest(Path(__file__)) != driver["checksum"]:
        raise ValueError("Executing driver differs from frozen source; run source/scripts/forward-snd-frozen.py check with explicit --out")
    if manifest["protocol_checksum"] != digest(out / "protocol.json"):
        raise ValueError("Frozen protocol changed")
    if manifest["environment_checksum"] != digest(out / "environment.json"):
        raise ValueError("Frozen environment record changed")
    environment = dict(python=sys.version, pandas=pd.__version__, numpy=np.__version__)
    if read(out / "environment.json") != environment:
        raise ValueError("Python/pandas/numpy differs from frozen environment; preserve this campaign and investigate")
    for entry in manifest["files"]:
        if digest(out / "source" / entry["path"]) != entry["checksum"]:
            raise ValueError("Frozen source changed: " + entry["path"])
    previous = None
    records = []
    for path in sorted((out / "checks").glob("*/check.json")):
        if read(path.with_name("check-checksum.json"))["checksum"] != digest(path):
            raise ValueError("Check content changed")
        record = read(path)
        if record["previous_check_checksum"] != previous:
            raise ValueError("Check chain changed")
        for item in record["artifacts"]:
            if digest(out / item["path"]) != item["checksum"]:
                raise ValueError("Evidence artifact changed: " + item["path"])
        previous = digest(path)
        records.append(record)
    return records


def accepted_bars(out, records):
    paths = [out / item["path"] for record in records for item in record["artifacts"]
             if item.get("role") == "accepted_bars"]
    if not paths:
        return pd.DataFrame(columns=BAR_COLUMNS + ["received_at", "capture_class"], index=pd.DatetimeIndex([], tz="UTC", name="ts_event"))
    frame = pd.concat([pd.read_parquet(path) for path in paths]).sort_index()
    if not frame.index.is_unique:
        raise ValueError("Accepted chain contains duplicated bars")
    return frame


def frozen_model(out):
    source = out / "source"
    sys.path.insert(0, str(source))
    spec = importlib.util.spec_from_file_location("snd_forward_frozen_model", source / "strategies/_snd_risk_research.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    loaded_session = Path(sys.modules["strategy_engine.sessions"].__file__)
    if digest(loaded_session) != digest(source / "strategy_engine/sessions.py"):
        raise ValueError("Loaded session dependency differs from frozen source")
    return module


def annotate_events(events, received, start, delay):
    events = events.copy()
    if events.empty:
        return events
    observed = pd.to_datetime(events.observed_time, utc=True)
    events["first_recorded_at"] = received.isoformat()
    events["evidence_class"] = np.where(observed < start, "prestart_context",
        np.where((received - observed).dt.total_seconds() <= delay, "timely_ohlc_simulation", "delayed_replay"))
    return events


def replay(out, folder, accepted, protocol, received_at, previous_records):
    model = frozen_model(out)
    start = utc(protocol["start"])
    end = min(received_at.floor("5min"), (accepted.index[-1] + pd.Timedelta(minutes=1)).floor("5min"))
    source = accepted.loc[accepted.index < end, BAR_COLUMNS]
    if end <= start or source.empty or not (source.index >= start).any():
        return {"status": "waiting_for_poststart_data", "variants": {}}, []
    # A partial current5m bucket cannot be mistaken for a completed decision.
    data = model.prepare_data(source, pivot_len=2, execution_minutes=1)
    results, outputs = {}, []
    for name, parameters in protocol["variants"].items():
        dest = folder / name
        dest.mkdir()
        result = model.run_model(data, parameters, start, end, protocol["tick_size"],
                                 protocol["point_value"], protocol["fee"], protocol["slippage_ticks"])
        events = result["events"].copy()
        prior_events = []
        for record in previous_records:
            event_file = next((i for i in record["artifacts"] if i.get("role") == "events_new" and i.get("variant") == name), None)
            if event_file:
                prior_events += read(out / event_file["path"])
        known = {e["event_id"]: e for e in prior_events}
        current = {e["event_id"]: jsonable(e) for e in events.to_dict("records")}
        if not set(known).issubset(current):
            raise ValueError("Replay removed a prior event; preserve this attempt and investigate")
        for event_id, old in known.items():
            fields = {k: v for k, v in old.items() if k not in {"first_recorded_at", "evidence_class"}}
            if fields != current[event_id]:
                raise ValueError("Replay changed prior event: " + event_id)
        added = annotate_events(events.loc[~events.event_id.isin(known)], received_at, start, protocol["max_delay_seconds"])
        all_events = prior_events + jsonable(added.to_dict("records"))
        save_new(dest / "events-new.json", added.to_dict("records"))
        save_new(dest / "events-snapshot.json", all_events)
        trades = result["trades"].copy()
        if len(trades):
            classes = []
            for trade in trades.itertuples():
                related = [e for e in all_events if e.get("order_id") == trade.order_id and e["event_type"] in {"order_armed", "entry", "exit"}]
                path_bars = accepted.loc[(accepted.index >= utc(trade.signal_time)-pd.Timedelta(minutes=5)) &
                                         (accepted.index <= utc(trade.exit_time))]
                path_timely = len(path_bars) > 0 and (path_bars.capture_class == "timely_ohlc_simulation").all()
                classes.append("timely_ohlc_simulation" if len(related) >= 3 and path_timely and all(e["evidence_class"] == "timely_ohlc_simulation" for e in related) else "delayed_replay")
            trades["evidence_class"] = classes
        trades.to_csv(dest / "trades.csv", index=False)
        result["sizing_decisions"].to_csv(dest / "sizing-decisions.csv", index=False)
        result["equity"].to_parquet(dest / "equity.parquet", index=False)
        save_new(dest / "open-state.json", result["open_state"])
        save_new(dest / "diagnostics.json", result["diagnostics"])
        equity = result["equity"]
        net = float(equity.equity.iloc[-1] - parameters["capital"]) if len(equity) else 0.
        count = len(trades)
        marked = np.r_[parameters["capital"], equity.equity.to_numpy(float)]
        drawdown = float(np.max(np.maximum.accumulate(marked) - marked))
        wins = float(trades.loc[trades.net_pnl > 0, "net_pnl"].sum()) if count else 0.
        losses = float(-trades.loc[trades.net_pnl < 0, "net_pnl"].sum()) if count else 0.
        active = result["open_state"].get("active")
        results[name] = dict(closed_trades=count, marked_net_pnl=net,
            closed_net_pnl=float(trades.net_pnl.sum()) if count else 0.,
            mean_net_r=float(trades.net_r.mean()) if count else None,
            profit_factor=wins/losses if losses else None,
            profit_factor_note="No losing trades" if count and not losses else ("No closed trades" if not count else None),
            marked_maximum_drawdown=drawdown,
            risk_budget_overshoot_trades=int((trades.risk_budget_overshoot_cash > 1e-9).sum()) if count else 0,
            risk_budget_overshoot_cash=float(trades.risk_budget_overshoot_cash.clip(lower=0).sum()) if count else 0.,
            open_position_quantity=active.get("quantity", 0) if active else 0,
            pending_orders=int(result["open_state"].get("pending") is not None),
            new_events=len(added), total_events=len(all_events),
            delayed_closed_trades=int((trades.evidence_class == "delayed_replay").sum()) if count else 0,
            timely_closed_trades=int((trades.evidence_class == "timely_ohlc_simulation").sum()) if count else 0,
            sample_met=count >= protocol["min_closed_trades"],
            calendar_met=received_at >= utc(protocol["review_after"]),
            coverage_through_review=end >= utc(protocol["review_after"]),
            review_due=count >= protocol["min_closed_trades"] and received_at >= utc(protocol["review_after"]) and end >= utc(protocol["review_after"]))
        for path in dest.iterdir():
            role = "events_new" if path.name == "events-new.json" else "simulation_artifact"
            outputs.append(dict(path=path.relative_to(out).as_posix(), checksum=digest(path), role=role, variant=name))
    return dict(status="prospective_simulation_updated", through=end, variants=results), outputs


def check(out, clock=None):
    out = Path(out)
    with locked(out):
        records = verify(out)
        protocol = read(out / "protocol.json")
        received_at = utc_now() if clock is None else utc(clock)
        if received_at < utc(protocol["frozen_at"]):
            raise ValueError("Clock precedes protocol freeze")
        if records and received_at < utc(records[-1]["checked_at"]):
            raise ValueError("Clock regressed behind the previous check")
        folder = out / "checks" / f"{len(records)+1:06d}"
        folder.mkdir(parents=True, exist_ok=False)
        accepted = accepted_bars(out, records)
        candidates, errors = discover(protocol)
        artifacts, ingestions = [], []
        for number, candidate in enumerate(candidates):
            source = Path(candidate["path"])
            receipt = dict(**candidate, received_at=received_at)
            try:
                h = digest(source)
                receipt["source_checksum"] = h
                raw = out / "inputs" / (h + source.suffix.lower())
                if not raw.exists():
                    raw.parent.mkdir(exist_ok=True)
                    shutil.copyfile(source, raw)
                if digest(raw) != h or digest(source) != h:
                    raise ValueError("Source changed during snapshot")
                artifacts.append(dict(path=raw.relative_to(out).as_posix(), checksum=h, role="raw_source"))
                if candidate.get("expected_checksum", h) != h:
                    raise ValueError("Registered checksum mismatch; source quarantined")
                incoming = load_bars(raw)
                context_unlocked = not any(r["simulation"]["status"] in {"prospective_simulation_updated", "replay_failed_preserved"} for r in records)
                prior_watermark = accepted.index.max() if len(accepted) else None
                combined, added, overlap = merge_append(accepted, incoming, received_at, protocol, allow_context_backfill=context_unlocked)
                if len(added):
                    destination = folder / f"accepted-{number:03d}.parquet"
                    added.to_parquet(destination)
                    artifacts.append(dict(path=destination.relative_to(out).as_posix(), checksum=digest(destination), role="accepted_bars"))
                accepted = combined
                receipt.update(status="accepted" if len(added) else "unchanged_or_no_closed_bars",
                               added_rows=len(added), exact_overlap_rows=overlap,
                               late_context_rows=int(((added.index < utc(protocol["start"])) & (added.index <= prior_watermark)).sum()) if len(added) and prior_watermark is not None else 0,
                               source_first=incoming.index[0], source_last=incoming.index[-1])
            except Exception as exc:
                receipt.update(status="quarantined", error=str(exc))
                errors.append(str(source) + ": " + str(exc))
            ingestions.append(receipt)
        warmup = warmup_status(accepted, protocol)
        summary = dict(status="waiting_for_complete_warmup", variants={})
        if warmup["ready"]:
            try:
                summary, new_artifacts = replay(out, folder, accepted, protocol, received_at, records)
                artifacts += new_artifacts
            except Exception as exc:
                summary = dict(status="replay_failed_preserved", error=str(exc), variants={})
                errors.append(traceback.format_exc())
                # Keep every partial artifact from a failed simulation attempt visible.
                for path in folder.rglob("*"):
                    if path.is_file() and path.relative_to(out).as_posix() not in {i["path"] for i in artifacts}:
                        artifacts.append(dict(path=path.relative_to(out).as_posix(), checksum=digest(path), role="failed_attempt_artifact"))
        latest = accepted.index[-1] if len(accepted) else None
        post = accepted.loc[accepted.index >= utc(protocol["start"])]
        record = dict(sequence=len(records)+1, checked_at=received_at,
            previous_check_checksum=digest(out / "checks" / f"{len(records):06d}" / "check.json") if records else None,
            protocol_checksum=digest(out / "protocol.json"), ingestions=ingestions,
            source_latest_bar=latest, source_age_hours=float((received_at-latest-pd.Timedelta(minutes=1)).total_seconds()/3600) if latest is not None else None,
            accepted_rows=len(accepted), poststart_rows=len(post),
            poststart_capture_classes=post.capture_class.value_counts().to_dict() if len(post) else {},
            warmup=warmup, errors=errors, simulation=summary, artifacts=artifacts)
        save_new(folder / "check.json", record)
        save_new(folder / "check-checksum.json", dict(checksum=digest(folder / "check.json")))
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "check", "verify", "status"])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--review-days", type=int, default=90)
    parser.add_argument("--min-trades", type=int, default=100)
    args = parser.parse_args()
    if args.command == "init":
        result = init(args.out, args.review_days, args.min_trades)
    elif args.command == "check":
        result = check(args.out)
    else:
        records = verify(args.out)
        result = dict(verification="passed", checks=len(records), latest=records[-1] if records else None)
    if "artifacts" in result:
        result = {k: v for k, v in result.items() if k not in {"artifacts", "ingestions"}}
    print(json.dumps(jsonable(result), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
