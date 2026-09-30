"""Replay the frozen corrected AW baseline for a signal-only chart audit.

The stateful gate is reconstructed from the preserved non-P&L position and
signal ledgers. No equity, trade return, or manifest metric is loaded. All
outputs here are classifications, source checks, and chart images.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import random
import sys
import argparse
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
from workbench.dataset_reference import resolve_dataset_path
from workbench.layout import load_layout


LAYOUT = load_layout(ROOT)
STATE_ROOT = LAYOUT.state_root
ARTIFACTS_ROOT = LAYOUT.artifacts_root
DEFAULT_OUTPUT = (ARTIFACTS_ROOT / "research" / "aw-model-nq-2026-09-29" /
                  "revision" / "signal-audit")
PARSER = argparse.ArgumentParser(description="Audit a frozen corrected AW baseline run")
PARSER.add_argument("run_id", help="Workbench run ID for the final development baseline")
PARSER.add_argument("--charts-only", action="store_true", help="Rerender saved sample without replay")
PARSER.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT,
                    help="Raw signal-audit artifact directory")
OPTIONS = PARSER.parse_args()
RUN_ID = OPTIONS.run_id
OUTPUT_DIR = OPTIONS.output_dir.resolve()
RUN = STATE_ROOT / "runs" / RUN_ID
SEED = 20260929
SAMPLE_DAYS = 60

REQUEST = json.loads((RUN / "input.json").read_text(encoding="utf-8"))
EXECUTION_SOURCE_HASH = REQUEST.get("execution_source_hash") or REQUEST["source_hash"]
SNAPSHOT_HASH = REQUEST.get("snapshot_hash") or REQUEST["source_hash"]
SOURCE_ROOT = Path(REQUEST["source_dir"])
if not SOURCE_ROOT.is_absolute():
    SOURCE_ROOT = STATE_ROOT / SOURCE_ROOT
SOURCE = SOURCE_ROOT / "strategies/aw_model_nq_revised.py"
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == REQUEST["strategy"]["file_hash"]
assert SNAPSHOT_HASH == SOURCE_ROOT.name
assert REQUEST["parameters"]["signal_timeframe"] == "3m"
assert REQUEST["parameters"]["bias_policy"] == "aligned-only"

sys.path.insert(0, str(SOURCE_ROOT))
from strategy_engine.data import session_bars  # noqa: E402
from strategy_engine.sessions import get_session  # noqa: E402

module_spec = importlib.util.spec_from_file_location("frozen_revised_aw", SOURCE)
assert module_spec and module_spec.loader
aw = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(aw)


def _stats(model, k, candidate):
    width = float(model.high3[k] - model.low3[k])
    body = float(model.bodies3[k])
    lookback = model.body_lookback
    median = float(np.median(model.bodies3[k - lookback:k])) if k >= lookback else 0.0
    edge = ((model.high3[k] - model.close3[k]) / width if candidate.side > 0
            else (model.close3[k] - model.low3[k]) / width) if width else None
    return {
        "mss_ready_ct": model.ready3[k].isoformat(),
        "mss_index": int(k),
        "mss_open": float(model.open3[k]),
        "mss_high": float(model.high3[k]),
        "mss_low": float(model.low3[k]),
        "mss_close": float(model.close3[k]),
        "body_over_median": body / median if median else None,
        "body_over_range": body / width if width else None,
        "close_fraction_from_edge": edge,
        "directional_body": bool(model.close3[k] > model.open3[k] if candidate.side > 0
                                 else model.close3[k] < model.open3[k]),
        "pass_body_multiple": bool(median and body >= model.parameters["impulse_multiple"] * median),
        "pass_body_fraction": bool(width and body / width >= 0.60),
        "pass_outer_quarter": bool(edge is not None and edge <= 0.25),
    }


class TracingAW(aw.AWModelNQ):
    def __init__(self, bars, parameters, request):
        super().__init__(bars, parameters, request)
        self.audit = []
        self.by_setup = {}

    def _try_sweep(self, k, state):
        old_seq = self.setup_seq
        super()._try_sweep(k, state)
        if self.setup_seq == old_seq:
            return
        candidates = ([self.candidate] if self.candidate else []) + self.other_candidates
        candidate = next(c for c in candidates if c.setup_id.endswith(f"-{self.setup_seq:04d}-{c.side:+d}-{c.level_name}"))
        levels = self.days[self.start3[k].date()]
        row = {
            "candidate_id": candidate.setup_id,
            "day_ct": self.start3[k].date().isoformat(),
            "sweep_ready_ct": candidate.sweep_ready.isoformat(),
            "sweep_index": int(k),
            "direction": "long" if candidate.side > 0 else "short",
            "swept_level_name": candidate.level_name,
            "swept_level_price": float(candidate.level),
            "neckline_price": float(candidate.neckline),
            "initial_sweep_extreme": float(candidate.extreme),
            "sweep_open": float(self.open3[k]),
            "sweep_high": float(self.high3[k]),
            "sweep_low": float(self.low3[k]),
            "sweep_close": float(self.close3[k]),
            "sweep_already_beyond_neckline": bool(
                self.close3[k] > candidate.neckline if candidate.side > 0
                else self.close3[k] < candidate.neckline),
            "bias": int(levels.bias),
            "bull_votes": int(sum(levels.bull_votes)),
            "bear_votes": int(sum(levels.bear_votes)),
            "pdh": float(levels.pdh), "pdl": float(levels.pdl),
            "onh": float(levels.onh), "onl": float(levels.onl),
            "eligible_levels": sorted(levels.eligible),
            "prior_pivot_highs": [float(v[0]) for v in self.pivot_highs[-2:]],
            "prior_pivot_lows": [float(v[0]) for v in self.pivot_lows[-2:]],
            "contract_id": str(self.contract3[k]),
            "program_stage": "swept_with_neckline",
        }
        self.audit.append(row)
        self.by_setup[candidate.setup_id] = row

    def _advance_candidate(self, candidate, k):
        row = self.by_setup.get(candidate.setup_id)
        old_phase = candidate.phase
        crossed = (old_phase == "swept" and self.start3[k] >= candidate.sweep_ready
                   and self._mss_crossed(k, candidate))
        if row is not None and crossed:
            row.update(_stats(self, k, candidate))
            row["cross_strength_pass"] = bool(self._strong_mss(k, candidate))
            row["signal_bars_after_sweep"] = candidate.mss_bars + 1
        old_funnel = self.funnel.copy()
        keep = super()._advance_candidate(candidate, k)
        if row is None:
            return keep
        if old_phase == "swept":
            if self.funnel["strong_mss"] > old_funnel["strong_mss"]:
                row["program_stage"] = "strong_mss"
            elif self.funnel["weak_first_break"] > old_funnel["weak_first_break"]:
                row["program_stage"] = "weak_first_break"
            elif self.funnel["expired_at_entry_window"] > old_funnel["expired_at_entry_window"]:
                row["program_stage"] = "expired_at_entry_window"
        elif old_phase == "mss_pending":
            if self.funnel["confirmed_gap"] > old_funnel["confirmed_gap"]:
                row["program_stage"] = "confirmed_gap"
                row["fvg_low"] = float(candidate.gap_low)
                row["fvg_high"] = float(candidate.gap_high)
                row["fvg_ready_ct"] = candidate.gap_ready.isoformat()
                row["final_sweep_extreme"] = float(candidate.extreme)
            elif self.funnel["mss_without_strict_fvg"] > old_funnel["mss_without_strict_fvg"]:
                row["program_stage"] = "mss_without_strict_fvg"
        return keep

    def _order_for_gap(self, candidate, bar, ready):
        row = self.by_setup.get(candidate.setup_id)
        if row is not None:
            reference = self._entry_reference(candidate, bar)
            choice = self._opposing_target(candidate.side, reference)
            row["entry_reference"] = float(reference)
            row["taken_at_gate"] = sorted(self.taken)
            row["opposing_target_price"] = float(choice[0]) if choice else None
            row["target_level_name"] = choice[1] if choice else None
        old_funnel = self.funnel.copy()
        order = super()._order_for_gap(candidate, bar, ready)
        if row is not None:
            row["gate_ready_ct"] = ready.isoformat()
            row["gate_reason"] = "submitted" if order else next(
                (key for key, value in self.funnel.items() if value > old_funnel[key]), "unknown")
            if order:
                row["program_stage"] = "entry_submitted"
                assert abs(row["entry_reference"] - float(order["limit_price"])) < 1e-9
                row["initial_stop_price"] = float(order["bracket"][0])
                assert abs(row["opposing_target_price"] - float(order["bracket"][1])) < 1e-9
        return order


def _draw(model, row, path):
    sweep = pd.Timestamp(row["sweep_ready_ct"]) - pd.Timedelta(minutes=3)
    left = sweep - pd.Timedelta(minutes=66)
    # Revised candidates remain live until 10:30 CT; shorter windows can
    # falsely hide a later neckline close or strict FVG.
    right = pd.Timestamp(row["day_ct"]).tz_localize(aw.CT) + pd.Timedelta(hours=10, minutes=33)
    candles = model.three.loc[(model.three.index >= left) & (model.three.index <= right)]
    if candles.empty:
        raise ValueError(f"No candles for {row['candidate_id']}")
    fig, ax = plt.subplots(figsize=(14, 4.5), dpi=130)
    x = np.arange(len(candles))
    for j, (_, candle) in enumerate(candles.iterrows()):
        color = "#19734a" if candle.close >= candle.open else "#b53a3a"
        ax.vlines(j, candle.low, candle.high, color=color, linewidth=1)
        lower = min(candle.open, candle.close)
        ax.add_patch(plt.Rectangle((j - 0.34, lower), 0.68,
                                   max(abs(candle.close - candle.open), 0.15),
                                   color=color, alpha=0.85))
    ax.axhline(row["swept_level_price"], color="#6744aa", linestyle="--",
               linewidth=1.2, label=f"{row['swept_level_name']} {row['swept_level_price']:.2f}")
    ax.axhline(row["neckline_price"], color="#1478a4", linestyle="--",
               linewidth=1.2, label=f"neckline {row['neckline_price']:.2f}")
    if row.get("fvg_low") is not None:
        start = pd.Timestamp(row["fvg_ready_ct"])
        j = int(candles.index.searchsorted(start))
        if j < len(candles):
            ax.add_patch(plt.Rectangle((j - .5, row["fvg_low"]), len(candles) - j,
                                       row["fvg_high"] - row["fvg_low"],
                                       color="#ecb33e", alpha=.18, label="strict FVG"))
    s = candles.index.get_indexer([sweep])[0]
    if s >= 0:
        ax.axvline(s, color="black", alpha=.55, label="sweep")
    if row.get("mss_ready_ct"):
        mss_start = pd.Timestamp(row["mss_ready_ct"]) - pd.Timedelta(minutes=3)
        j = candles.index.get_indexer([mss_start])[0]
        if j >= 0:
            ax.axvline(j, color="#f07819", linewidth=1.3, label="first neckline cross")
    ticks = np.arange(0, len(candles), max(1, len(candles) // 14))
    ax.set_xticks(ticks, [candles.index[t].strftime("%H:%M") for t in ticks])
    ax.set_xlabel("Chicago time, completed 3-minute candles")
    ax.set_ylabel("NQ index points")
    ax.set_title(f"{row['day_ct']} {row['direction']} {row['program_stage']} | {row['candidate_id']}")
    ax.grid(alpha=.14)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _check_levels_and_structure(bars, model, rows):
    """Recompute marked ERLs, sweep geometry, gap geometry, and target state."""
    local = bars.index.tz_convert(aw.CT)
    clock = local.hour * 60 + local.minute
    regular = (clock >= 510) & (clock < 900)
    rth_index = local[regular].normalize()
    rth = bars.loc[regular, ["high", "low"]].groupby(rth_index).agg(
        {"high": "max", "low": "min"})
    checked = []
    for row in rows:
        day = pd.Timestamp(row["day_ct"]).tz_localize(aw.CT)
        prior = rth.loc[rth.index < day].iloc[-1]
        overnight_start = day - pd.Timedelta(days=1) + pd.Timedelta(hours=17)
        open_ct = day + pd.Timedelta(hours=8, minutes=30)
        begin = int(local.searchsorted(overnight_start))
        end = int(local.searchsorted(open_ct))
        overnight = bars.iloc[begin:end]
        prices = {"PDH": float(prior.high), "PDL": float(prior.low),
                  "ONH": float(overnight.high.max()), "ONL": float(overnight.low.min())}
        external_match = all(abs(prices[name] - row[name.lower()]) < 1e-9 for name in prices)
        eligible = {"ONH", "ONL"}
        if prices["ONH"] < prices["PDH"]:
            eligible.add("PDH")
        if prices["ONL"] > prices["PDL"]:
            eligible.add("PDL")
        eligibility_match = eligible == set(row["eligible_levels"])
        level = prices[row["swept_level_name"]]
        sweep_match = ((row["sweep_low"] <= level - 0.25 and row["sweep_close"] > level)
                       if row["direction"] == "long" else
                       (row["sweep_high"] >= level + 0.25 and row["sweep_close"] < level))
        gap_match = None
        if row.get("fvg_low") is not None:
            middle = row["mss_index"]
            after = middle + 1
            before = middle - 1
            if row["direction"] == "long":
                gap_match = (model.low3[after] > model.high3[before] and
                             abs(row["fvg_low"] - model.high3[before]) < 1e-9 and
                             abs(row["fvg_high"] - model.low3[after]) < 1e-9)
            else:
                gap_match = (model.high3[after] < model.low3[before] and
                             abs(row["fvg_low"] - model.high3[after]) < 1e-9 and
                             abs(row["fvg_high"] - model.low3[before]) < 1e-9)
        taken_match = target_match = None
        independent_target_name = independent_target_price = None
        if row.get("gate_ready_ct"):
            gate_ready = pd.Timestamp(row["gate_ready_ct"])
            through = int(local.searchsorted(gate_ready))
            observed = bars.iloc[end:through]
            taken = {name for name in eligible if
                     ((float(observed.high.max()) >= prices[name]) if name.endswith("H") else
                      (float(observed.low.min()) <= prices[name]))}
            taken_match = taken == set(row["taken_at_gate"])
            side = 1 if row["direction"] == "long" else -1
            opposing = ("PDH", "ONH") if side > 0 else ("PDL", "ONL")
            reference = row["entry_reference"]
            candidates = [(prices[name], name) for name in opposing
                          if name in eligible and name not in taken and
                          (prices[name] > reference if side > 0 else prices[name] < reference)]
            choice = (min(candidates) if side > 0 else max(candidates)) if candidates else None
            if choice:
                independent_target_price, independent_target_name = choice
            target_match = (row.get("opposing_target_price") == independent_target_price and
                            row.get("target_level_name") == independent_target_name)
        checked.append({
            "candidate_id": row["candidate_id"], "day_ct": row["day_ct"],
            "program_stage": row["program_stage"],
            "external_prices_match": bool(external_match),
            "eligible_levels_match": bool(eligibility_match),
            "sweep_geometry_match": bool(sweep_match),
            "strict_fvg_geometry_match": gap_match,
            "taken_levels_match": taken_match,
            "nearest_untaken_target_match": target_match,
            "independent_target_name": independent_target_name,
            "independent_target_price": independent_target_price,
        })
    assert all(c["external_prices_match"] and c["eligible_levels_match"] and
               c["sweep_geometry_match"] and c["strict_fvg_geometry_match"] is not False and
               c["taken_levels_match"] is not False and
               c["nearest_untaken_target_match"] is not False for c in checked)
    pd.DataFrame(checked).to_csv(OUTPUT_DIR / "level_checks.csv", index=False)
    return checked


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(REQUEST["start"], tz="UTC") - pd.Timedelta(days=REQUEST["warmup_days"])
    end = pd.Timestamp(REQUEST["end"], tz="UTC") + pd.Timedelta(days=1)
    dataset_path = resolve_dataset_path(REQUEST["dataset"], STATE_ROOT)
    frame = pd.read_parquet(dataset_path,
                            filters=[("ts_event", ">=", start), ("ts_event", "<", end)])
    bars = session_bars(frame, get_session(REQUEST["session"]), REQUEST["timeframe"])
    del frame
    if OPTIONS.charts_only:
        ledger = json.loads((OUTPUT_DIR / "candidate_ledger.json").read_text(encoding="utf-8"))
        assert ledger["baseline_run_id"] == RUN_ID and ledger["source_hash"] == EXECUTION_SOURCE_HASH
        sampled_ids = set(pd.read_csv(OUTPUT_DIR / "sampled_candidates.csv").candidate_id)
        rows = [row for row in ledger["candidates"] if row["candidate_id"] in sampled_ids]
        assert len(rows) == len(sampled_ids)
        render_model = SimpleNamespace(three=aw._complete_resample(bars, "3min"))
        for row in rows:
            _draw(render_model, row, OUTPUT_DIR / "charts" / f"{row['candidate_id']}.png")
        print(f"rerendered {len(rows)} full-window charts through 10:33 CT")
        return
    model = TracingAW(bars, REQUEST["parameters"], REQUEST)
    position_ledger = pd.read_csv(RUN / "positions.csv", usecols=["timestamp", "contracts"])
    signal_ledger = pd.read_csv(
        RUN / "signals.csv", usecols=["event_time", "event", "order_id", "signal_id",
                                      "fill_price", "reason"])
    ready = pd.DatetimeIndex(pd.to_datetime(bars.availability_time, utc=True))
    scored = np.asarray((bars.index >= pd.Timestamp(REQUEST["start"], tz="UTC")) &
                        (ready < end))
    assert len(position_ledger) == int(scored.sum())
    assert (pd.DatetimeIndex(pd.to_datetime(position_ledger.timestamp, utc=True)).asi8 ==
            ready[scored].asi8).all()
    positions = position_ledger.contracts.to_numpy(dtype=int)
    signal_ledger["event_time"] = pd.to_datetime(signal_ledger.event_time, utc=True)
    submitted = signal_ledger.loc[(signal_ledger.event == "submitted") &
                                  (signal_ledger.reason == "aw-first-touch")]
    filled = signal_ledger.loc[signal_ledger.event == "filled"]
    closed = signal_ledger.loc[signal_ledger.event == "closed"]
    order_spans = []
    for order in submitted.itertuples(index=False):
        end_events = signal_ledger.loc[(signal_ledger.order_id == order.order_id) &
                                       signal_ledger.event.isin(["filled", "cancelled", "expired", "rejected"])]
        assert len(end_events) == 1
        order_spans.append((order.event_time, end_events.iloc[0].event_time, order.order_id))
    fill_intervals = []
    for fill in filled.itertuples(index=False):
        matching_close = closed.loc[(closed.order_id == fill.order_id) &
                                    (closed.event_time >= fill.event_time)]
        assert len(matching_close) == 1
        fill_intervals.append((fill.event_time, matching_close.iloc[0].event_time,
                               fill.order_id, fill.signal_id, float(fill.fill_price)))
    trace_log = io.StringIO()
    with contextlib.redirect_stdout(trace_log):
        scored_i = 0
        last_scored_i = int(np.flatnonzero(scored)[-1])
        for i, bar in enumerate(bars.itertuples(index=False, name="Bar")):
            if i > last_scored_i:
                break
            if not scored[i]:
                model.on_close(i, bar, {"position": 0, "equity": REQUEST["capital"],
                                        "tradable": False, "entry_filled_this_bar": None})
                continue
            event = ready[i]
            opening = bars.index[i]
            position = int(positions[scored_i])
            position_at_open = int(positions[scored_i - 1]) if scored_i else 0
            scored_i += 1
            work = next((order_id for begin, stop, order_id in order_spans
                         if begin < event < stop), None)
            live = next(((order_id, signal_id, price) for begin, stop, order_id, signal_id, price
                         in fill_intervals if begin <= event < stop), None)
            notice = next(({"order_id": order_id, "signal_id": signal_id}
                           for begin, _, order_id, signal_id, _ in fill_intervals
                           if opening <= begin <= event), None)
            model.on_close(i, bar, {
                "position": position, "position_at_open": position_at_open,
                "equity": REQUEST["capital"], "tradable": True,
                "entry_price": live[2] if live else None,
                "order_id": live[0] if live else None,
                "signal_id": live[1] if live else None,
                "working_order_id": work,
                "entry_filled_this_bar": notice,
            })
    trace_lines = [line for line in trace_log.getvalue().splitlines() if line.startswith(("AW_ENTRY ", "AW_FUNNEL "))]
    (OUTPUT_DIR / "signal_trace.log").write_text("\n".join(trace_lines) + "\n", encoding="utf-8")
    trace_funnel = dict(model.funnel)
    original_log = (RUN / "process.log").read_text(encoding="utf-8")
    original_funnel = json.loads(next(line[10:] for line in original_log.splitlines()
                                      if line.startswith("AW_FUNNEL ")))
    assert trace_funnel == original_funnel, (trace_funnel, original_funnel)
    rows = model.audit
    assert len(rows) == trace_funnel["neckline_sweeps"]
    checked = _check_levels_and_structure(bars, model, rows)
    days = sorted({row["day_ct"] for row in rows})
    assert len(days) >= 50, f"Only {len(days)} distinct candidate days"
    rng = random.Random(SEED)
    sampled_days = sorted(rng.sample(days, min(SAMPLE_DAYS, len(days))))
    by_day = defaultdict(list)
    for row in rows:
        by_day[row["day_ct"]].append(row)
    sampled = [rng.choice(by_day[day]) for day in sampled_days]
    charts = OUTPUT_DIR / "charts"
    charts.mkdir(exist_ok=True)
    for row in sampled:
        row["chart_path"] = f"charts/{row['candidate_id']}.png"
        _draw(model, row, charts / f"{row['candidate_id']}.png")
    (OUTPUT_DIR / "candidate_ledger.json").write_text(json.dumps({
        "source_hash": EXECUTION_SOURCE_HASH,
        "strategy_file_hash": REQUEST["strategy"]["file_hash"],
        "dataset_checksum": REQUEST["dataset"]["checksum"],
        "baseline_run_id": REQUEST["id"],
        "seed": SEED,
        "funnel_matches_corrected_run": True,
        "funnel": trace_funnel,
        "candidates": rows,
    }, indent=2), encoding="utf-8")
    pd.DataFrame(sampled).to_csv(OUTPUT_DIR / "sampled_candidates.csv", index=False)
    print(json.dumps({
        "candidates": len(rows), "candidate_days": len(days),
        "sampled_days": len(sampled_days), "sampled_charts": len(sampled),
        "stages": dict(Counter(row["program_stage"] for row in rows)),
        "level_and_structure_checks": len(checked),
        "target_checks": sum(c["nearest_untaken_target_match"] is not None for c in checked),
        "funnel_matches_corrected_run": True,
    }, indent=2))


if __name__ == "__main__":
    main()
