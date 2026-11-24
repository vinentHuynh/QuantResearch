"""Read one UTC chart day from saved market data and execution evidence."""
import json
import math
import os
import sys
from pathlib import Path
from uuid import UUID

import pandas as pd

from .contract import checksum
from .dataset_reference import resolve_dataset_path
from .evidence import EvidenceRegistry, EvidenceRegistryError


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def price(row, *names):
    for name in names:
        value = row.get(name)
        if pd.notna(value) and math.isfinite(float(value)):
            return float(value)
    return None


def load_ledger(folder, artifacts, name="trades.csv"):
    hashes = {a["name"]: a["checksum"] for a in artifacts} if isinstance(artifacts, list) else artifacts
    path = folder / name
    if not hashes.get(name) or checksum(path) != hashes[name]:
        raise ValueError("Trade ledger checksum mismatch")
    return pd.read_csv(path) if name.endswith(".csv") else pd.read_parquet(path)


def attach_fills(trades, ledger, signals=None):
    if ledger.empty:
        return
    # Match both timestamps and the unsized ledger outcome. Ambiguous rows
    # stay timing-only so an unrelated fill cannot be attached to a trade.
    groups = ledger.groupby([pd.to_datetime(ledger["entry_time"], utc=True),
                             pd.to_datetime(ledger["exit_time"], utc=True)]).indices
    changes = {}
    if signals is not None and not signals.empty and "new_stop" in signals:
        updates = signals[signals.event == "bracket_updated"]
        for order_id, rows in updates.groupby("order_id"):
            changes[order_id] = [
                {"time": int(pd.Timestamp(row.event_time).timestamp() * 1000),
                 "stop": float(row.new_stop), "target": float(row.new_target)}
                for row in rows.itertuples() if pd.notna(row.new_stop) and pd.notna(row.new_target)
            ]
    for trade in trades:
        key = pd.Timestamp(trade["entry"]), pd.Timestamp(trade["exit"])
        candidates = ledger.iloc[groups.get(key, [])]
        pnl = "net_pnl" if "net_pnl" in candidates else "pnl"
        matches = candidates[(candidates[pnl] - trade["pnl"]).abs() < 0.00001]
        if len(matches) != 1:
            continue
        row = matches.iloc[0]
        fields = {"entryPrice": price(row, "entry", "entry_price"), "exitPrice": price(row, "exit", "exit_price"),
                  "stop": price(row, "original_stop", "stop_price", "stop"),
                  "target": price(row, "original_target", "target_price", "tp", "take_profit")}
        trade.update({key: value for key, value in fields.items() if value is not None})
        side = str(row.get("side", row.get("direction", ""))).lower()
        quantity = price(row, "quantity")
        if side in ("long", "short"):
            trade["side"] = side
        elif "side" not in row and quantity:
            trade["side"] = "long" if quantity > 0 else "short"
        if quantity is not None and "quantity" not in trade:
            trade["quantity"] = abs(quantity)
        if row.get("order_id") in changes:
            entry_ms, exit_ms = (int(stamp.timestamp() * 1000) for stamp in key)
            trade["changes"] = [level for level in changes[row.order_id] if entry_ms <= level["time"] <= exit_ms]


def campaign_ledgers(item, day):
    """Resolve original non-workbench imports using their campaign identity."""
    registry = EvidenceRegistry(Path(__file__).resolve().parents[1])
    def campaign(name):
        return registry.campaign(name, consumer="collective-catalog")
    extension = item.get("latest_replay", {})
    if extension and extension["start"] <= day <= extension["end"]:
        root = campaign("combined-es-nq-refresh-2026-09-29").root
        for file in root.rglob("extension.json"):
            if checksum(file) == extension["extension_sha256"] and read_json(file)["catalog_id"] == item["id"]:
                yield file.parent, "trades.csv"
                return
    if item["source"] == "SND":
        evidence = campaign("snd-fresh-backtest-2026-09-16")
        yield evidence.root / "runs" / (item["key"] + "__next_open"), "trades.parquet"
    if item["source"] == "Expanded":
        evidence = campaign("expanded-search-2026-09-16")
        screen = read_json(evidence.file("screen-results"))
        follow = read_json(evidence.file("follow-results"))
        for row in screen + [r for r in follow if r["scenario"] == "baseline"]:
            if row["key"] == item["key"] and row["start"] <= day <= row["end"]:
                folder = (evidence.root / "runs" / row["run"]).resolve()
                folder.relative_to(evidence.root.resolve())
                yield folder, "trades.csv"


def chart_day(request, home):
    day, item, trades = request["day"], request["item"], request["trades"]
    start = pd.Timestamp(day, tz="UTC")
    end = start + pd.Timedelta(days=1)
    result = {"trades": trades, "candles": [], "reference": False, "notes": []}
    runs = list(request["runs"])
    attributed = {t.get("source_run") for t in trades}
    # Earlier campaign imports can retain the recorded artifacts on disk after
    # the corresponding run record has been removed from the SQLite catalog.
    known = {r["id"] for r in runs}
    for run_id in (attributed | set(item.get("source_run_ids", []))) - known - {None}:
        try:
            if str(UUID(run_id)) != run_id:
                continue
            folder = home / "runs" / run_id
            inp = read_json(folder / "input.json")
            if inp["id"] != run_id or inp["dataset"]["symbol"] != item["symbol"] or not inp["start"] <= day <= inp["end"]:
                continue
            manifest = read_json(folder / "manifest.json")
            if manifest.get("run_id") == run_id:
                runs.append({"id": run_id, "dataset": inp["dataset"], "artifacts": manifest["artifacts"]})
        except (OSError, ValueError, KeyError):
            continue
    replay = item.get("verified_replay", {})
    tail = item["coverage"][-1]
    if replay and tail["start"] <= day <= tail["end"]:
        replay_dataset = replay
    else:
        ext = item.get("latest_replay", {})
        replay_dataset = ext if ext and ext["start"] <= day <= ext["end"] else {}
    exact = [r["dataset"] for r in runs if r["id"] in attributed]
    if not exact and replay_dataset:
        exact = [{"id": replay_dataset["dataset_id"], "checksum": replay_dataset.get("dataset_checksum")}]
    if not exact:
        exact = [r["dataset"] for r in runs]
    datasets = request["datasets"]
    dataset = None
    if exact:
        versions = {d["id"] for d in exact}
        if len(versions) == 1:
            dataset = next((d for d in datasets if d["id"] in versions and
                            all(not pin.get("checksum") or pin["checksum"] == d["checksum"] for pin in exact)), None)
            if dataset is None and not any(d["id"] in versions for d in datasets):
                # A preserved run may still have its exact file after the
                # import catalog moves. Require the original bytes below.
                if "path" in exact[0] and exact[0].get("checksum") and all(
                        pin.get("checksum") == exact[0]["checksum"] for pin in exact):
                    dataset = exact[0]
        if dataset is None:
            result["notes"].append("The original candle dataset could not be identified for this day.")
    else:
        covering = [d for d in datasets if pd.Timestamp(d["first"]) < end and pd.Timestamp(d["last"]) >= start]
        dataset = max(covering, key=lambda d: d["registered_at"], default=None)
        result["reference"] = dataset is not None
        if dataset is None:
            result["notes"].append("No registered market data covers this day.")
    if dataset:
        try:
            path = resolve_dataset_path(dataset, home)
            if not path.is_file() and Path(dataset["id"]).name == dataset["id"]:
                path = home / "datasets" / dataset["id"] / "bars.parquet"
            if checksum(path) != dataset["checksum"]:
                raise ValueError("Candle checksum mismatch")
            bars = pd.read_parquet(path, columns=["open", "high", "low", "close"],
                                   filters=[("ts_event", ">=", start), ("ts_event", "<", end)])
            if not bars.index.is_unique or not bars.index.is_monotonic_increasing:
                raise ValueError("Invalid candle timestamps")
            result["candles"] = [dict(time=int(stamp.timestamp() * 1000), **row)
                                 for stamp, row in bars.to_dict("index").items()]
            if bars.empty:
                result["notes"].append("No candles were recorded on this UTC day.")
        except (OSError, ValueError, KeyError):
            result["notes"].append("The registered candle file is missing, unreadable, or has changed.")

    for run in runs:
        rows = [t for t in trades if t.get("source_run") == run["id"] or
                (not t.get("source_run") and len(runs) == 1 and not replay_dataset)]
        if not rows:
            continue
        folder = home / "runs" / run["id"]
        try:
            ledger = load_ledger(folder, run["artifacts"])
            signals = None
            if "original_stop" in ledger and any(a["name"] == "signals.csv" for a in run["artifacts"]):
                try:
                    signals = load_ledger(folder, run["artifacts"], "signals.csv")
                except (OSError, ValueError):
                    result["notes"].append("Bracket updates are unavailable. Only the original levels are shown.")
            attach_fills(rows, ledger, signals)
        except (OSError, ValueError, KeyError):
            result["notes"].append("The source run's execution ledger could not be verified.")
    missing = [t for t in trades if "entryPrice" not in t]
    if missing and (item["source"] in ("Expanded", "SND") or item.get("latest_replay")):
        try:
            for folder, name in campaign_ledgers(item, day):
                manifest = read_json(folder / "manifest.json")
                attach_fills(missing, load_ledger(folder, manifest.get("artifacts", manifest), name))
        except (EvidenceRegistryError, OSError, KeyError, ValueError):
            result["notes"].append("The original campaign's fill ledger is unavailable.")
    result["notes"] = list(dict.fromkeys(result["notes"]))
    return result


if __name__ == "__main__":
    print(json.dumps(chart_day(json.load(sys.stdin), Path(os.environ["WORKBENCH_HOME"])), allow_nan=False))
