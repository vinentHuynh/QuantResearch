"""Independent asymmetric path oracle, original-default parity, and export audit."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = HERE.parent / "mnq-open-fade-2026-10-28"
OUT = ROOT / "reports/mnq-open-fade-small-targets-2026-10-28"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


old_replay = load("original_fade_replay", OLD / "replay.py")
new_replay = load("small_target_replay", HERE / "replay.py")


def exact(path, mode, distance, horizon, delay, target_distance, stop_distance):
    """Execute independent linear segments whose intraminute ordering is known."""
    origin = path[0][0]
    upper, lower = origin+distance, origin-distance
    trigger = None
    for minute in range(15):
        points = path[minute]
        if points[0] >= upper:
            trigger = (minute, -1, 0, upper)
            break
        if points[0] <= lower:
            trigger = (minute, 1, 0, lower)
            break
        for k in range(1, len(points)):
            if points[k] >= upper and points[k-1] < upper:
                trigger = (minute, -1, k, upper)
                break
            if points[k] <= lower and points[k-1] > lower:
                trigger = (minute, 1, k, lower)
                break
        if trigger is not None:
            break
    if trigger is None:
        return 0.
    ti, side, component, level = trigger
    if mode == "touch" and delay == 0:
        entry_minute, entry, intrabar = ti, level, component > 0
    elif mode == "touch":
        entry_minute = ti+delay
        if entry_minute >= 15:
            return 0.
        entry, intrabar, component = path[entry_minute][0], False, 0
    else:
        confirmation = next((j for j in range(ti, 15)
                             if side*(path[j][-1]-level) > 0), None)
        if confirmation is None:
            return 0.
        entry_minute = confirmation+1+delay
        if entry_minute >= 15:
            return 0.
        entry, intrabar, component = path[entry_minute][0], False, 0
    stop, target = entry-side*stop_distance, entry+side*target_distance
    for minute in range(entry_minute, entry_minute+horizon+1):
        points = path[minute]
        if minute == entry_minute and intrabar:
            points = [entry]+points[component:]
        else:
            if side*(points[0]-stop) <= 0:
                return side*(points[0]-entry)-1.12
            if side*(points[0]-target) >= 0:
                return side*(target-entry)-1.12
            if minute == entry_minute+horizon:
                return side*(points[0]-entry)-1.12
        for a, b in zip(points[:-1], points[1:]):
            if min(a, b) <= stop <= max(a, b):
                return side*(stop-entry)-1.12
            if min(a, b) <= target <= max(a, b):
                return side*(target-entry)-1.12
    raise AssertionError("Unclosed exact-path trade")


def old_fields(value):
    if isinstance(value, dict):
        return {k: old_fields(v) for k, v in value.items() if k not in ("target_points", "stop_points")}
    if isinstance(value, list):
        return [old_fields(v) for v in value]
    return value


def synthetic_checks():
    rng = np.random.default_rng(912847)
    bounds, parity, custom = 0, 0, 0
    for case in range(75):
        path, price = [], 1000.
        scale = [3., 10., 30., 60.][case % 4]
        for minute in range(135):
            opening = price if minute == 0 else price+float(rng.choice([0, 0, 0, 0, -1, 1]))*scale
            points = [opening]
            for _ in range(4):
                points.append(points[-1]+float(rng.integers(-4, 5))*scale)
            path.append(points)
            price = points[-1]
        ohlc = np.array([[p[0], max(p), min(p), p[-1]] for p in path])
        for mode in ("touch", "confirm"):
            for distance in (40, 60, 80):
                for horizon in (60, 120):
                    for delay in (0, 1):
                        base = dict(mode=mode, trigger=distance, horizon=horizon, delay_bars=delay)
                        for policy in ("conservative", "favorable"):
                            original = old_replay.simulate_day(ohlc, **base, policy=policy)
                            current = new_replay.simulate_day(ohlc, **base, policy=policy)
                            assert old_fields(current) == original
                            parity += 1
                        distances = [(t, distance/2) for t in (5, 10, 15, distance/2)]
                        if case < 10:
                            distances += [(distance*2+20, distance*3), (10, 5), (15, 60)]
                        for target_distance, stop_distance in distances:
                            actual = exact(path, mode, distance, horizon, delay, target_distance, stop_distance)
                            kwargs = dict(base, target_points=target_distance, stop_points=stop_distance)
                            lower = new_replay.simulate_day(ohlc, **kwargs, policy="conservative")["net_points"]
                            upper = new_replay.simulate_day(ohlc, **kwargs, policy="favorable")["net_points"]
                            assert lower-1e-8 <= actual <= upper+1e-8, (case, kwargs, lower, actual, upper)
                            if (target_distance, stop_distance) in distances[:4]:
                                bounds += 1
                            else:
                                custom += 1
    return {"asymmetric_authorized_grid_path_bounds": bounds,
            "additional_custom_distance_path_bounds": custom,
            "original_default_full_record_parity": parity}


def continuation_checks():
    events_path = OUT / "continuation_events.csv"
    if not events_path.exists():
        return {"continuation_export_audit": "not yet available"}
    events = pd.read_csv(events_path)
    summary = pd.read_csv(OUT / "continuation_summary.csv")
    assert not events.duplicated(["date", "threshold_points", "horizon_minutes", "barrier_definition"]).any()
    assert set(events.threshold_points) == {40, 60, 80, 100, 120, 160}
    assert set(events.horizon_minutes) == {60, 120}
    assert (events.continuation_certain <= events.continuation_possible).all()
    assert (events.retracement_certain <= events.retracement_possible).all()
    assert (events[["continuation_certain", "retracement_certain", "neither_certain", "outcome_ambiguous"]].sum(axis=1) == 1).all()
    assert (events.continuation_certain == events.favorable_fade_exit_reason.str.startswith("stop")).all()
    assert (events.continuation_possible == events.conservative_fade_exit_reason.str.startswith("stop")).all()
    assert (events.retracement_certain == events.conservative_fade_exit_reason.str.startswith("target")).all()
    assert (events.retracement_possible == events.favorable_fade_exit_reason.str.startswith("target")).all()
    assert (events.conservative_fade_gross_points <= events.favorable_fade_gross_points+1e-8).all()
    for r in summary.itertuples():
        g = events[(events.threshold_points == r.threshold_points)
                   & (events.horizon_minutes == r.horizon_minutes)
                   & (events.barrier_definition == r.barrier_definition)
                   & (events.date >= r.start) & (events.date <= r.end)]
        assert len(g) == r.n
        assert g.month.nunique() == r.occupied_event_months
        sparse = len(g) < 100 or g.month.nunique() < 10
        assert r.sparse_evidence == sparse
        if sparse:
            assert np.isnan(r.continuation_certain_ci_low_pct)
            assert np.isnan(r.continuation_possible_ci_high_pct)
            assert not r.primary_continuation_evidence_flag
        for indicator in ["continuation_certain", "continuation_possible", "retracement_certain", "retracement_possible", "neither_certain", "outcome_ambiguous"]:
            assert g[indicator].sum() == getattr(r, indicator+"_n")
            if len(g):
                assert np.isclose(100*g[indicator].mean(), getattr(r, indicator+"_pct"))
        expected_flag = (r.barrier_definition == "balanced_20" and not sparse
                         and r.continuation_certain_ci_low_pct > 50)
        assert r.primary_continuation_evidence_flag == expected_flag
    return {"continuation_event_rows_audited": len(events),
            "continuation_summary_rows_reconciled": len(summary),
            "continuation_fixed_denominators_bounds_sparse_cis": "passed"}


def strategy_checks():
    if not (OUT / "summary.json").exists():
        return {"strategy_export_audit": "not yet available"}
    summary = json.loads((OUT / "summary.json").read_text())
    attempts = pd.read_csv(OUT / "all_attempts.csv")
    development = attempts[(attempts.stage == "development") & (attempts.scenario == "baseline")]
    assert len(development) == 48
    assert int(development.original_control.sum()) == 12
    assert len(development[~development.original_control]) == 36
    assert not development.duplicated(["mode", "trigger", "target", "stop", "horizon"]).any()
    ledgers, controls = {}, 0
    for r in attempts.itertuples():
        daily = pd.read_csv(OUT / "ledgers" / (r.case_id+".csv"))
        ledgers[r.case_id] = daily
        trades = daily[daily.filled]
        assert len(daily) == r.sessions and len(trades) == r.trades
        assert np.allclose(trades.gross_points, trades.side*(trades.exit_price-trades.entry_price))
        assert np.allclose(daily.net_dollars, daily.gross_points*2-daily.cost_dollars)
        assert np.allclose(daily.net_dollars, daily.net_points*2)
        assert np.allclose(trades.cost_dollars, r.cost_dollars)
        assert daily.loc[~daily.filled, ["gross_points", "net_points", "cost_dollars", "net_dollars"]].eq(0).all().all()
        net = daily.net_dollars.to_numpy()
        assert np.isclose(net.sum(), r.net_profit)
        assert np.isclose(trades.cost_dollars.sum(), r.costs_dollars)
        positive, negative = net[net > 0].sum(), -net[net < 0].sum()
        pf = positive/negative if negative else np.inf if positive else 0.
        assert np.isclose(pf, r.profit_factor)
        equity = np.concatenate(([0.], np.cumsum(net)))
        drawdown = np.max(np.maximum.accumulate(equity)-equity)
        assert np.isclose(drawdown, r.max_daily_closed_drawdown)
        assert np.allclose(daily.equity_dollars, np.cumsum(net))
        assert np.allclose(abs(trades.entry_price-trades.target_price), r.target)
        assert np.allclose(abs(trades.entry_price-trades.stop_price), r.stop)
        assert np.isclose(r.two_exit_breakeven_win_pct, 100*(r.stop+r.cost_dollars/2)/(r.stop+r.target))
        if r.stage == "development" and r.scenario == "baseline":
            assert r.eligible == (len(trades) >= 150 and net.sum() > 0 and pf >= 1.10)
        if r.stage == "development" and r.original_control:
            old = pd.read_csv(ROOT / "reports/mnq-open-fade-2026-10-28/ledgers" /
                              f"development_{r.mode}_D{int(r.trigger)}_H{r.horizon}_{r.scenario}.csv")
            assert old.date.tolist() == daily.date.tolist()
            for column in ("gross_points", "net_dollars", "entry_idx", "exit_idx", "entry_price", "exit_price"):
                assert np.allclose(old[column], daily[column], equal_nan=True)
            for column in ("filled", "side", "exit_reason"):
                assert old[column].equals(daily[column])
            controls += 1
    for decision in summary["decisions"]:
        if decision["stage"] == "development" or decision["stage"].startswith("training_for_"):
            group = attempts[(attempts.stage == decision["stage"]) &
                             (attempts["mode"] == decision["mode"]) & (attempts.scenario == "baseline")]
            eligible = group[(group.trades >= 150) & (group.net_profit > 0) & (group.profit_factor >= 1.10)]
            expected = max(eligible.itertuples(), key=lambda x:(x.net_to_drawdown, x.net_profit, -x.trigger, -x.horizon, x.target)).case_id if len(eligible) else None
            assert decision["selected_case"] == expected
    for disposition in summary["dispositions"]:
        group = attempts[attempts["mode"] == disposition["mode"]]
        if disposition["stage"] == "development":
            assert group.stage.eq("development").all()
        assert (group.end <= disposition["tested_through"]).all()
    evaluation_cases = 0
    for decision in summary["decisions"]:
        if not decision["stage"].startswith("evaluation_"):
            continue
        group = attempts[(attempts.stage == decision["stage"]) & (attempts["mode"] == decision["mode"])]
        assert set(group.scenario) == {"baseline", "double_cost", "entry_delay_1m", "favorable_order"}
        source = attempts[attempts.case_id == decision["selected_training_case"]].iloc[0]
        assert source.end < group.start.min()
        for column in ("trigger", "target", "stop", "horizon"):
            assert group[column].eq(source[column]).all()
        failed = {r.scenario for r in group.itertuples()
                  if r.scenario != "favorable_order" and
                  (r.trades < 30 or r.net_profit <= 0 or r.profit_factor < 1.05)}
        assert failed == {x["scenario"] for x in decision["failures"]}
        assert (decision["outcome"] == "failed") == bool(failed)
        evaluation_cases += len(group)
    for r in development.itertuples():
        low = ledgers[r.case_id].set_index("date")
        high = ledgers[r.case_id.replace("_baseline", "_favorable_order")].set_index("date")
        assert (low.net_dollars <= high.net_dollars+1e-8).all()
    raw = pd.read_parquet(summary["data"]["path"]).tz_convert("America/New_York")
    raw_checks = 0
    for r in development[~development.original_control].itertuples():
        trades = ledgers[r.case_id].query("filled")
        if not len(trades):
            continue
        t = trades.iloc[len(trades)//2]
        start = pd.Timestamp(t.date+" 09:30", tz="America/New_York")
        day = raw.loc[(raw.index >= start) & (raw.index < start+pd.Timedelta(minutes=135))]
        assert len(day) == 135
        upper, lower = day.open.iloc[0]+r.trigger, day.open.iloc[0]-r.trigger
        for i in range(15):
            b = day.iloc[i]
            possible = [-1] if b.open >= upper else [1] if b.open <= lower else ([-1] if b.high >= upper else [])+([1] if b.low <= lower else [])
            if possible:
                break
        assert i == t.trigger_idx and t.side in possible
        level = upper if t.side == -1 else lower
        if r.mode == "touch":
            assert t.entry_idx == i and t.entry_price == level
        else:
            confirm = next(j for j in range(i, 15) if t.side*(day.close.iloc[j]-level) > 0)
            assert t.confirmation_idx == confirm and t.entry_idx == confirm+1
            assert t.entry_price == day.open.iloc[confirm+1]
        assert t.target_price == t.entry_price+t.side*r.target
        assert t.stop_price == t.entry_price-t.side*r.stop
        raw_checks += 1
    raw_evaluation_checks = 0
    for r in attempts[attempts.stage.str.startswith("evaluation_")].itertuples():
        trades = ledgers[r.case_id].query("filled")
        for position in sorted(set([0, len(trades)//2, len(trades)-1])):
            t = trades.iloc[position]
            start = pd.Timestamp(t.date+" 09:30", tz="America/New_York")
            day = raw.loc[(raw.index >= start) & (raw.index < start+pd.Timedelta(minutes=135))]
            upper, lower = day.open.iloc[0]+r.trigger, day.open.iloc[0]-r.trigger
            for i in range(15):
                b = day.iloc[i]
                possible = [-1] if b.open >= upper else [1] if b.open <= lower else ([-1] if b.high >= upper else [])+([1] if b.low <= lower else [])
                if possible:
                    break
            assert i == t.trigger_idx and t.side in possible
            level = upper if t.side == -1 else lower
            if r.mode == "confirm":
                confirm = next(j for j in range(i, 15) if t.side*(day.close.iloc[j]-level) > 0)
                assert t.confirmation_idx == confirm
                assert t.entry_idx == confirm+1+r.delay_bars
                assert t.entry_price == day.open.iloc[int(t.entry_idx)]
            elif r.delay_bars:
                assert t.entry_idx == i+r.delay_bars
                assert t.entry_price == day.open.iloc[int(t.entry_idx)]
            else:
                assert t.entry_idx == i and t.entry_price == level
            assert 0 <= t.entry_idx < 15
            assert t.target_price == t.entry_price+t.side*r.target
            assert t.stop_price == t.entry_price-t.side*r.stop
            exit_bar = day.iloc[int(t.exit_idx)]
            if "target" in t.exit_reason:
                assert t.exit_price == t.target_price
                assert exit_bar.high >= t.target_price if t.side == 1 else exit_bar.low <= t.target_price
            elif "stop" in t.exit_reason:
                if t.exit_at_open:
                    assert t.exit_price == exit_bar.open
                    assert t.side*(exit_bar.open-t.stop_price) <= 0
                else:
                    assert t.exit_price == t.stop_price
                    assert exit_bar.low <= t.stop_price if t.side == 1 else exit_bar.high >= t.stop_price
            else:
                assert t.exit_reason == "time_exit"
                assert t.exit_idx == t.entry_idx+r.horizon and t.exit_price == exit_bar.open
            raw_evaluation_checks += 1
    return {"strategy_configuration_count": 48, "new_smaller_target_cases": 36,
            "reconciled_strategy_ledgers": len(ledgers), "prior_control_daily_parity_ledgers": controls,
            "raw_smaller_target_signal_and_bracket_checks": raw_checks,
            "evaluation_scenario_gates_reconciled": evaluation_cases,
            "raw_evaluation_including_delay_checks": raw_evaluation_checks,
            "latest_scored_strategy_date_boundary": attempts.end.max(),
            "accounting_selection_stop_gates": "passed"}


if __name__ == "__main__":
    result = {"status": "passed", **synthetic_checks(), **continuation_checks(), **strategy_checks()}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "independent_review_checks.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, indent=2))
