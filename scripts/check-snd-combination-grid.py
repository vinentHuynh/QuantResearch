"""Exhaustive declared-grid engine parity on deterministic synthetic fixtures.

This is an implementation test, not historical performance evidence. Both
engines receive the same reference-prepared candles with explicitly controlled
chart/hourly bias, so the fixtures exercise decision branches without pretending
that a few hours of artificial prices establish natural hourly structure.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import importlib
import itertools
import json
import os
from pathlib import Path
import sys
import time
import traceback

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "reports/snd-combinations-2026-09-26"
sys.path.insert(0, str(ROOT))
from strategies import _snd_combination_reference as reference


def now():
    return datetime.now(timezone.utc).isoformat()


def checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + str(os.getpid()))
    temp.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temp, path)


def declared_grid(out):
    protocol = read(out / "protocol.json")
    path = out / protocol["configurations_file"]
    assert checksum(path) == protocol["configurations_checksum"], "Configuration checksum mismatch"
    configs = read(path)
    assert len(configs) == protocol["expected_configurations"] == 10368
    keys = list(protocol["grid"])
    values = list(itertools.product(*protocol["grid"].values()))
    assert len(values) == len(configs)
    fixed = {k: v for k, v in configs[0]["parameters"].items() if k not in keys}
    for i, (config, levels) in enumerate(zip(configs, values)):
        assert config["config_id"] == f"c{i:05d}"
        expected = fixed | dict(zip(keys, levels))
        assert config["parameters"] == expected, f"Grid differs at {config['config_id']}"
        digest = hashlib.sha256(json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        assert config["parameter_hash"] == digest, f"Parameter hash differs at {config['config_id']}"
    return protocol, configs


def fixture_definitions():
    history = [(100., 102., 98., 100.)] * 21
    formation = [(100., 100.5, 99.5, 99.75), (99.75, 107., 99.5, 106.5),
                 (106.5, 107.5, 106., 107.)]
    touch = (107., 107.25, 99.75, 100.5)
    fill = (107.5, 108., 107.5, 107.75)
    target = (107.75, 118., 107.5, 117.)

    def case(name, rows, *, mirror=False, hourly=1, departure_index=22, departure_volume=100.):
        volumes = [10.] * len(rows)
        volumes[departure_index] = departure_volume
        return dict(name=name, rows=rows, volumes=volumes, mirror=mirror,
                    bias=-1 if mirror else 1, hourly_bias=-hourly if mirror else hourly)

    strong = history + formation + [touch, fill, target]
    stopped = history + formation + [touch, fill, (107.75, 108., 90., 100.)]
    ambiguous = history + formation + [touch, fill, (107.75, 118., 90., 100.)]
    delayed = history + formation + [touch,
        (100.25, 101.25, 99.75, 100.5), (100.5, 101.25, 99.75, 100.75),
        (101.5, 107.75, 101.5, 107.), target]
    relaxed = history + formation[:2] + [(100.25, 107.5, 100.25, 107.)] + [touch, fill, target]
    weak = history + [(100., 101.5, 98.5, 99.75), (99.75, 103., 99.5, 102.25),
        (102.25, 103.5, 102., 103.), (103., 103.25, 99.75, 100.5),
        (103.5, 104., 103.5, 103.75), (103.75, 110., 103.5, 109.)]
    intermediate = history + [(100., 101.5, 98.5, 99.75), (99.75, 105., 99.5, 104.75),
        (104.75, 105.5, 104.5, 105.), (105., 105.25, 99.75, 100.5),
        (105.5, 106., 105.5, 105.75), (105.75, 115., 105.5, 114.)]
    aged = history + formation + [(107., 107.5, 106.5, 107.)] * 14 + [touch, fill, target]
    # Opposing supply is context even though the controlled chart bias is long.
    supply = [(115., 116., 114., 115.5), (115.5, 115.5, 108., 109.), (109., 109.5, 107., 108.)]
    room = history + supply + formation + [touch, fill, target]
    return [case("strong_long", strong), case("strong_short", strong, mirror=True),
            case("stop_long", stopped), case("stop_short", stopped, mirror=True),
            case("ambiguous_exit_long", ambiguous), case("ambiguous_exit_short", ambiguous, mirror=True),
            case("delayed_retouch", delayed), case("hourly_mismatch", strong, hourly=-1),
            case("relaxed_only", relaxed), case("weak_quality", weak, departure_volume=12.5),
            case("intermediate_quality", intermediate, departure_volume=17.5),
            case("aged_touch", aged), case("opposing_room", room, departure_index=25)]


def prepare_fixture(definition):
    frame = pd.DataFrame(definition["rows"], columns=["open", "high", "low", "close"])
    frame["volume"] = definition["volumes"]
    if definition["mirror"]:
        old = frame.copy()
        frame["open"], frame["close"] = 250 - old.open, 250 - old.close
        frame["high"], frame["low"] = 250 - old.low, 250 - old.high
    # Repeated source OHLC is deliberate: valid 1m intervals preserve a compact
    # prescribed 5m pattern. This is not a tick-path or queue simulation.
    frame = frame.loc[frame.index.repeat(5)].reset_index(drop=True)
    frame["volume"] /= 5
    frame.index = pd.date_range("2026-01-05 12:00:00+00:00", periods=len(frame), freq="1min")
    prepared = reference.prepare_data(frame, pivot_len=2, execution_minutes=1)
    prepared["chart"]["bias"] = definition["bias"]
    prepared["chart"]["hourly_bias"] = definition["hourly_bias"]
    return prepared


def run(engine, prepared, parameters):
    source = prepared["source"]
    return engine.run_model(prepared, parameters, source.index[0],
                            source.index[-1] + pd.Timedelta(minutes=1),
                            tick_size=.25, point_value=2., fee=1.25, slippage_ticks=1)


def compare(expected, actual):
    for field in ("trades", "equity"):
        # Every column, every row, order, dtype and numerical value must agree.
        pd.testing.assert_frame_equal(expected[field], actual[field], check_exact=True)


def fixture_checks(configs):
    """Assert intended branches actually occur before calling coverage complete."""
    fixtures = {d["name"]: prepare_fixture(d) for d in fixture_definitions()}
    base = configs[0]["parameters"]
    strongest = base | dict(max_zone_width_atr=.5, min_departure_atr=1.5,
                            min_departure_rvol=2., max_touch_age_hours=1., require_fvg=True)
    checks = []

    def trades(name, **changes):
        return run(reference, fixtures[name], base | changes)["trades"]

    for name in ("strong_long", "strong_short"):
        for boundary, stop in itertools.product(("wick", "body"), ("zone", "candle")):
            result = run(reference, fixtures[name], strongest | dict(zone_boundary=boundary, stop_model=stop))
            assert len(result["trades"]) > 0, (name, boundary, stop, "strong filters must admit trades")
            checks.append(f"{name}/{boundary}/{stop}: all four strongest quality filters admit trades")
    for name in ("stop_long", "stop_short", "ambiguous_exit_long", "ambiguous_exit_short"):
        result = trades(name)
        assert len(result) > 0 and result.exit_reason.eq("stop").all(), name
        assert result.ambiguous_exit.eq(name.startswith("ambiguous_exit")).all(), name
        checks.append(f"{name}: stop exit with expected simultaneous-bracket ambiguity flag")
    assert len(trades("hourly_mismatch")) == 0 and len(trades("hourly_mismatch", use_htf=False)) > 0
    checks.append("hourly mismatch: HTF enabled rejects; disabled admits")
    assert len(trades("relaxed_only")) > 0 and len(trades("relaxed_only", require_fvg=True)) == 0
    checks.append("relaxed-only formation: relaxed admits; strict rejects")
    assert len(trades("aged_touch", max_touch_age_hours=1.)) == 0
    assert len(trades("aged_touch", max_touch_age_hours=4.)) > 0
    checks.append("aged touch: one-hour age rejects; four-hour age admits")
    assert len(trades("opposing_room", min_opposing_room_r=2.)) == 0
    assert len(trades("opposing_room", min_opposing_room_r=0.)) > 0
    checks.append("opposing context: room2 rejects; room0 admits")
    assert len(trades("delayed_retouch")) == 0
    assert len(trades("delayed_retouch", order_lifetime_bars=3)) > 0
    assert len(trades("delayed_retouch", entry_eligibility="any_touch")) > 0
    checks.append("delayed retouch: first/TTL1 rejects; TTL3 and any-touch/TTL1 admit")
    assert len(trades("weak_quality")) > 0
    for changes in (dict(max_zone_width_atr=.5), dict(min_departure_atr=1.), dict(min_departure_rvol=1.5)):
        assert len(trades("weak_quality", **changes)) == 0, changes
    checks.append("weak quality: each width/departure/volume filter rejects independently")
    for lower, higher in ((dict(max_zone_width_atr=1.), dict(max_zone_width_atr=.5)),
                          (dict(min_departure_atr=1.), dict(min_departure_atr=1.5)),
                          (dict(min_departure_rvol=1.5), dict(min_departure_rvol=2.))):
        assert len(trades("intermediate_quality", **lower)) > 0, lower
        assert len(trades("intermediate_quality", **higher)) == 0, higher
    checks.append("intermediate quality: each looser width/departure/volume threshold admits, each stricter threshold rejects")
    return checks


def source_identity(include_fast):
    paths = ["scripts/check-snd-combination-grid.py", "strategies/_snd_combination_reference.py",
             "strategy_engine/sessions.py", "tests/test_snd_combination_grid.py"]
    if include_fast:
        paths.extend(["strategies/_snd_combination_fast.py", "strategies/_snd_combination_fast_io.py"])
    return {name: checksum(ROOT / name) for name in paths}


def fixture_metadata(definitions):
    return [dict(name=d["name"], source_rows=len(d["rows"]) * 5,
                 definition_checksum=hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest(),
                 controlled_chart_bias=d["bias"], controlled_hourly_bias=d["hourly_bias"])
            for d in definitions]


def benchmark(out, configs, count):
    started = time.perf_counter()
    sources = source_identity(False)
    checks = fixture_checks(configs)
    definitions = fixture_definitions()
    # Evenly-spaced deterministic IDs; no outcome-based fixture/config selection.
    indices = np.unique(np.linspace(0, len(configs) - 1, min(count, len(configs)), dtype=int))
    records = []
    for definition in definitions:
        prepared = prepare_fixture(definition)
        begin = time.perf_counter()
        nonzero = total_trades = 0
        for index in indices:
            result = run(reference, prepared, configs[int(index)]["parameters"])
            total_trades += len(result["trades"])
            nonzero += int(len(result["trades"]) > 0)
        seconds = time.perf_counter() - begin
        records.append(dict(fixture=definition["name"], completed=len(indices), nonzero=nonzero,
                            trades=total_trades, reference_seconds=seconds))
        print(f"Benchmark {definition['name']}: {len(indices)} reference cases in {seconds:.2f}s", flush=True)
    assert sources == source_identity(False), "Source changed during benchmark"
    result = dict(status="benchmark_only", checked_at=now(), source_files=sources,
                  protocol_checksum=checksum(out / "protocol.json"),
                  configurations_checksum=checksum(out / "configurations.json"),
                  declared_configurations=len(configs), sampled_configurations=len(indices),
                  sampled_config_ids=[configs[int(i)]["config_id"] for i in indices],
                  fixture_count=len(definitions), reference_comparisons=len(indices) * len(definitions),
                  fixture_checks=checks, fixtures=fixture_metadata(definitions), records=records,
                  estimated_full_reference_serial_seconds=sum(r["reference_seconds"] for r in records) * len(configs) / len(indices),
                  elapsed_seconds=time.perf_counter() - started,
                  interpretation="Reference timing only; fast-engine parity and complete-grid validation are not established by this benchmark.")
    save(out / "synthetic-grid-benchmark.json", result)
    return result


def check_fixture(definition, configs, failure_dir):
    fast = importlib.import_module("strategies._snd_combination_fast")
    prepared = prepare_fixture(definition)
    fast_prepared = prepare_fixture(definition)
    begun = time.perf_counter()
    completed = passed = nonzero = total_trades = 0
    nonzero_ids, failures, exit_counts = [], [], {}
    for config in configs:
        expected = actual = None
        try:
            expected = run(reference, prepared, config["parameters"])
            actual = run(fast, fast_prepared, config["parameters"])
            compare(expected, actual)
            passed += 1
        except Exception:
            failure = dict(fixture=definition["name"], config_id=config["config_id"],
                           parameter_hash=config["parameter_hash"], error=traceback.format_exc())
            # Save every failure without hiding/truncating diagnostics in counts.
            folder = Path(failure_dir) / definition["name"] / config["config_id"]
            for label, result in (("reference", expected), ("fast", actual)):
                if result is not None:
                    for field in ("trades", "equity"):
                        path = folder / f"{label}-{field}.parquet"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        result[field].to_parquet(path, index=True)
            save(folder / "mismatch.json", failure)
            failures.append(failure | dict(artifact=str((folder / "mismatch.json").relative_to(Path(failure_dir).parent))))
        completed += 1
        if expected is not None and len(expected["trades"]):
            nonzero += 1
            total_trades += len(expected["trades"])
            nonzero_ids.append(config["config_id"])
            for reason, count in expected["trades"].exit_reason.value_counts().items():
                exit_counts[reason] = exit_counts.get(reason, 0) + int(count)
        if completed % 1024 == 0:
            print(f"{definition['name']}: {completed}/{len(configs)} comparisons, {len(failures)} failures", flush=True)
    input_failures = []
    pristine = prepare_fixture(definition)
    for label, used in (("reference", prepared), ("fast", fast_prepared)):
        for field in ("source", "chart", "hourly"):
            try:
                pd.testing.assert_frame_equal(pristine[field], used[field], check_exact=True)
            except Exception:
                input_failures.append(dict(fixture=definition["name"], engine=label, field=field,
                                           kind="prepared_input_mutation", error=traceback.format_exc()))
    return dict(fixture=definition["name"], status="passed" if not failures and not input_failures else "failed",
                completed_comparisons=completed, passed_comparisons=passed, nonzero_configurations=nonzero,
                reference_trades=total_trades, elapsed_seconds=time.perf_counter() - begun,
                nonzero_config_ids=nonzero_ids, reference_exit_counts=exit_counts,
                failures=failures, input_failures=input_failures)


def parity(out, configs, workers, new_attempt=False):
    started = time.perf_counter()
    sources = source_identity(True)
    checks = fixture_checks(configs)
    definitions = fixture_definitions()
    identity = dict(protocol_checksum=checksum(out / "protocol.json"),
                    configurations_checksum=checksum(out / "configurations.json"), source_files=sources)
    common = dict(**identity, started_at=now(), declared_configurations=len(configs),
                  fixture_count=len(definitions), expected_comparisons=len(configs) * len(definitions),
                  fixture_checks=checks, fixtures=fixture_metadata(definitions),
                  comparison="All trade and full 5m equity columns, row order, dtypes and values; check_exact=True.",
                  limitations="Synthetic controlled chart/hourly bias tests engine branches, not natural structure discovery, all possible price paths, market edge, omitted-signal completeness, or prospective performance. Real-source and independent-accounting checks remain separate.")
    destination = out / "synthetic-grid-parity.json"
    if destination.exists() and not new_attempt:
        raise ValueError("Existing synthetic attempt preserved; pass --new-attempt to run again without replacing its artifacts")
    attempt = out / "synthetic-grid-parity" / ("attempt-" + now().replace(":", "").replace(".", "") + f"-{os.getpid()}")
    attempt.mkdir(parents=True, exist_ok=False)
    histories = []
    for path in sorted((out / "synthetic-grid-parity").glob("attempt-*/result.json")):
        previous = read(path)
        histories.append(dict(artifact=str(path.relative_to(out)), checksum=checksum(path),
            status=previous["status"], completed_comparisons=previous.get("completed_comparisons", 0),
            failed_comparisons=previous.get("failed_comparisons", 0), failures=len(previous.get("failures", []))))
    for path in sorted((out / "synthetic-grid-parity").glob("attempt-*/status.json")):
        if (path.parent / "result.json").exists():
            continue
        previous = read(path)
        histories.append(dict(artifact=str(path.relative_to(out)), checksum=checksum(path),
            status="unterminated", last_observed_status=previous.get("status"),
            completed_comparisons=previous.get("completed_comparisons", 0),
            failures=len(previous.get("failures", []))))
    # If this version encounters a legacy summary, preserve its bytes as well.
    if destination.exists() and "attempt_artifact" not in read(destination):
        legacy = out / "synthetic-grid-parity" / ("legacy-" + checksum(destination) + ".json")
        if not legacy.exists():
            legacy.write_bytes(destination.read_bytes())
        histories.append(dict(artifact=str(legacy.relative_to(out)), checksum=checksum(legacy), status=read(legacy).get("status")))
    common.update(prior_attempts=histories, attempt_directory=str(attempt.relative_to(out)))

    def publish(payload, terminal=False):
        path = attempt / ("result.json" if terminal else "status.json")
        if terminal and path.exists():
            raise ValueError("Terminal attempt artifacts are immutable")
        save(path, payload)
        save(destination, payload | dict(attempt_artifact=str(path.relative_to(out)), attempt_checksum=checksum(path)))

    publish(common | dict(status="running", completed_comparisons=0, passed_comparisons=0, records=[], failures=[]))
    records, errors = [], []
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(check_fixture, d, configs, str(attempt / "mismatches")): d["name"] for d in definitions}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    records.append(future.result())
                except Exception:
                    errors.append(dict(fixture=name, error=traceback.format_exc()))
                records.sort(key=lambda r: r["fixture"])
                publish(common | dict(status="running", records=records, failures=errors,
                    completed_comparisons=sum(r["completed_comparisons"] for r in records),
                    passed_comparisons=sum(r["passed_comparisons"] for r in records)))
    finally:
        changed = [name for name, digest in sources.items() if not (ROOT / name).exists() or checksum(ROOT / name) != digest]
        if changed:
            errors.append(dict(kind="source_changed", files=changed))
        for name, expected in (("protocol.json", identity["protocol_checksum"]), ("configurations.json", identity["configurations_checksum"])):
            if checksum(out / name) != expected:
                errors.append(dict(kind="declaration_changed", file=name))
        count = sum(r["completed_comparisons"] for r in records)
        passed = sum(r["passed_comparisons"] for r in records)
        failures = errors + [failure for r in records for failure in r["failures"] + r["input_failures"]]
        complete = count == common["expected_comparisons"] and len(records) == len(definitions)
        result = common | dict(status="passed" if complete and not failures else ("failed" if failures else "incomplete"),
            completed_at=now(), elapsed_seconds=time.perf_counter() - started,
            complete_grid=complete, completed_comparisons=count, passed_comparisons=passed,
            failed_comparisons=sum(len(r["failures"]) for r in records), worker_failures=len(errors),
            completed_configurations=len(configs) if complete else None,
            nonzero_configurations=len({cid for r in records for cid in r["nonzero_config_ids"]}),
            records=records, failures=failures)
        publish(result, terminal=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--benchmark-reference", action="store_true")
    group.add_argument("--run", action="store_true")
    parser.add_argument("--benchmark-count", type=int, default=100)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--new-attempt", action="store_true", help="Preserve prior synthetic attempts and start another one")
    args = parser.parse_args()
    assert args.benchmark_count > 0 and args.workers > 0
    out = args.output.resolve()
    _, configs = declared_grid(out)
    result = benchmark(out, configs, args.benchmark_count) if args.benchmark_reference else parity(out, configs, args.workers, args.new_attempt)
    print(json.dumps({k: result[k] for k in ("status", "declared_configurations", "elapsed_seconds")}), flush=True)
    if args.run and result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
