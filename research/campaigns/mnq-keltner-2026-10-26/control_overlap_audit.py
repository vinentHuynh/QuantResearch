"""Post-protocol overlap diagnostic: exclude existing pairs; never rematch.

An earlier control's outcome window can contain the later selected signal
candle. Exclude that window from this sensitivity, without changing either
original matching or the confirmatory results. This is not new validation.
"""
from pathlib import Path
import hashlib
import json
import shutil

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "artifacts/mnq-keltner-2026-10-26"
SEED, REPS = 261026, 2000


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def contrast(pairs, lookup, weights):
    events = pairs.outcome_05_60.eq("reversion").astype(float)
    controls = pairs.control_outcome_05_60.eq("reversion").astype(float)
    draws = []
    for dates, values in ((pairs.day, events), (pairs.control_day, controls)):
        codes = [lookup[str(d)[:10]] for d in dates]
        n = np.bincount(codes, minlength=weights.shape[1])
        y = np.bincount(codes, weights=values, minlength=weights.shape[1])
        denominator = weights @ n
        draws.append(np.divide(weights @ y, denominator,
                     out=np.full(REPS, np.nan), where=denominator > 0))
    low, high = np.nanquantile(draws[0] - draws[1], [.025, .975])
    return {"paired_decisive_n": len(pairs),
            "unique_controls": pairs.control_id.nunique(),
            "unique_control_candles": pairs.control_bar_index.nunique(),
            "event_reversion_rate": events.mean(),
            "control_reversion_rate": controls.mean(),
            "difference": events.mean() - controls.mean(),
            "difference_ci_low": low, "difference_ci_high": high}


def main():
    calendar = json.loads((OUT / "calendar.json").read_text(encoding="utf-8"))
    rows = []
    for timeframe in (5, 15):
        data = pd.read_parquet(OUT / f"events_{timeframe}m.parquet")
        data = data.loc[data.episode_start]
        for split in ("test", "all"):
            selected = data if split == "all" else data.loc[data.split.eq(split)]
            days = (sorted(set(d for part in calendar.values() for d in part))
                    if split == "all" else sorted(set(calendar[split])))
            lookup = {d: i // 5 for i, d in enumerate(days)}
            groups = max(lookup.values()) + 1
            weights = np.random.default_rng(SEED).multinomial(
                groups, np.ones(groups) / groups, size=REPS).astype(float)
            for event_type in ("wick_only", "close_outside"):
                matched = selected.loc[selected.type.eq(event_type) & selected.control_matched]
                overlap = matched.control_decision_time + pd.Timedelta(minutes=60) > matched.timestamp
                joint = matched.loc[matched.outcome_05_60.isin(["reversion", "continuation"])
                                    & matched.control_outcome_05_60.isin(["reversion", "continuation"])]
                retained = joint.loc[joint.control_decision_time + pd.Timedelta(minutes=60)
                                     <= joint.timestamp]
                row = {"timeframe": timeframe, "split": split, "type": event_type,
                       "classification": "post-protocol diagnostic; same matches; no rematching",
                       "original_matched_n": len(matched), "overlap_n": int(overlap.sum()),
                       "overlap_rate": overlap.mean(),
                       **{"original_" + k: v for k, v in contrast(joint, lookup, weights).items()},
                       **{"nonoverlap_" + k: v for k, v in contrast(retained, lookup, weights).items()}}
                rows.append(row)
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT / "control_overlap_sensitivity.csv", index=False)
    audit_path = OUT / "independent_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else {}
    audit["control_overlap_diagnostic"] = {
        "classification": "Post-protocol diagnostic exclusion of SAME frozen matches; not validation or rematching",
        "reason": "Controls ending after the signal candle opens can include the later selected breach, biasing their continuation frequency by construction.",
        "exclusion": "Retain only control_decision_time + 60 clock minutes <= event timestamp (signal candle open).",
        "denominator": "Only original matched pairs with decisive 0.5-ATR outcomes in BOTH arms, followed by the temporal exclusion.",
        "inference": "Shared 2,000 seeded nonoverlapping five-observed-trading-day block draws across arms; each reused control keeps its own original-date weight. Pointwise percentile intervals; exploratory diagnostic.",
        "source_sha256": digest(Path(__file__)),
        "input_sha256": {name: digest(OUT / name) for name in
                         ("events_5m.parquet", "events_15m.parquet", "calendar.json", "protocol.json")},
        "csv_sha256": digest(OUT / "control_overlap_sensitivity.csv"),
        "rows": rows}
    audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    shutil.copy2(Path(__file__), OUT / "control_overlap_audit.py")
    print(frame.loc[frame.split.eq("test"), ["timeframe", "type", "overlap_rate",
          "nonoverlap_paired_decisive_n", "nonoverlap_difference",
          "nonoverlap_difference_ci_low", "nonoverlap_difference_ci_high"]].to_string(index=False))


if __name__ == "__main__":
    main()
