"""Independent ordered-path oracle plus reconciliation of attempted development ledgers.

Does not run new historical configurations or examine later strategy outcomes.
"""
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "reports/mnq-open-fade-2026-10-28"
sys.path.insert(0, str(HERE))
from replay import simulate_day


def ordered_path_net(path, mode, distance, horizon, delay):
    """Independent execution on known, sequential linear intraminute segments."""
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
    trigger_minute, side, component, level = trigger
    if mode == "touch" and delay == 0:
        entry_minute, entry, intrabar = trigger_minute, level, component > 0
    elif mode == "touch":
        entry_minute = trigger_minute+delay
        if entry_minute >= 15:
            return 0.
        entry, intrabar, component = path[entry_minute][0], False, 0
    else:
        confirmation = next((j for j in range(trigger_minute, 15)
                             if side*(path[j][-1]-level) > 0), None)
        if confirmation is None:
            return 0.
        entry_minute = confirmation+1+delay
        if entry_minute >= 15:
            return 0.
        entry, intrabar, component = path[entry_minute][0], False, 0
    stop, target = entry-side*distance/2, entry+side*distance/2

    def opening_exit(price):
        if side*(price-stop) <= 0:
            return price
        if side*(price-target) >= 0:
            return target
        return None

    def segment_exit(a, b):
        # Before an exit, the path starts between the two boundaries.
        if min(a, b) <= stop <= max(a, b):
            return stop
        if min(a, b) <= target <= max(a, b):
            return target
        return None

    for minute in range(entry_minute, entry_minute+horizon+1):
        points = path[minute]
        if minute == entry_minute and intrabar:
            points = [entry]+points[component:]
        else:
            exit_price = opening_exit(points[0])
            if exit_price is not None:
                return side*(exit_price-entry)-1.12
            if minute == entry_minute+horizon:
                return side*(points[0]-entry)-1.12
        for a, b in zip(points[:-1], points[1:]):
            exit_price = segment_exit(a, b)
            if exit_price is not None:
                return side*(exit_price-entry)-1.12
    raise AssertionError("Unclosed ordered-path trade")


def verify_synthetic_bounds():
    rng = np.random.default_rng(912847)
    checks = 0
    for case in range(300):
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
        for mode in ["touch", "confirm"]:
            for distance in [40, 60, 80]:
                for horizon in [60, 120]:
                    for delay in [0, 1]:
                        actual = ordered_path_net(path, mode, distance, horizon, delay)
                        lower = simulate_day(ohlc, mode=mode, trigger=distance, horizon=horizon,
                                             policy="conservative", delay_bars=delay)["net_points"]
                        upper = simulate_day(ohlc, mode=mode, trigger=distance, horizon=horizon,
                                             policy="favorable", delay_bars=delay)["net_points"]
                        assert lower-1e-8 <= actual <= upper+1e-8, (case, mode, distance, horizon, delay, lower, actual, upper)
                        checks += 1
    return checks


def verify_actual_exports():
    summary = json.loads((OUT / "summary.json").read_text())
    attempts = pd.read_csv(OUT / "all_attempts.csv")
    assert len(attempts) == 24
    assert set(attempts.stage) == {"development"}
    assert set(attempts.scenario) == {"baseline", "favorable_order"}
    assert attempts.end.eq("2023-12-31").all()
    assert all(d["stage"] == "development" and d["outcome"] == "failed" for d in summary["dispositions"])
    ledger_files = sorted((OUT / "ledgers").glob("*.csv"))
    assert len(ledger_files) == 24
    assert all(p.name.startswith("development_") for p in ledger_files)
    ledgers = {}
    for row in attempts.itertuples():
        daily = pd.read_csv(OUT / "ledgers" / (row.case_id+".csv"))
        ledgers[row.case_id] = daily
        assert daily.date.max() <= "2023-12-31"
        trades = daily[daily.filled]
        assert len(daily) == row.sessions and len(trades) == row.trades
        assert np.allclose(trades.gross_points, trades.side*(trades.exit_price-trades.entry_price))
        assert np.allclose(daily.net_dollars, daily.gross_points*2-daily.cost_dollars)
        assert np.allclose(daily.net_dollars, daily.net_points*2)
        assert np.allclose(trades.cost_dollars, 2.24)
        assert daily.loc[~daily.filled, ["gross_points", "net_points", "cost_dollars", "net_dollars"]].eq(0).all().all()
        net = daily.net_dollars.to_numpy()
        assert np.isclose(net.sum(), row.net_profit)
        assert np.isclose(trades.gross_points.sum(), row.gross_points)
        assert np.isclose(trades.cost_dollars.sum(), row.costs_dollars)
        pf = net[net > 0].sum() / -net[net < 0].sum()
        assert np.isclose(pf, row.profit_factor)
        equity = np.concatenate(([0.], np.cumsum(net)))
        drawdown = np.max(np.maximum.accumulate(equity)-equity)
        assert np.isclose(drawdown, row.max_daily_closed_drawdown)
        assert np.allclose(daily.equity_dollars, np.cumsum(net))
        assert ((trades.entry_idx >= 0) & (trades.entry_idx < 15)).all()
        assert (trades.exit_idx <= trades.entry_idx+trades.horizon).all()
        assert np.allclose(abs(trades.entry_price-trades.target_price), trades.trigger/2)
        assert np.allclose(abs(trades.entry_price-trades.stop_price), trades.trigger/2)
        if row.scenario == "baseline":
            eligible = len(trades) >= 150 and net.sum() > 0 and pf >= 1.10
            assert row.eligible == eligible
            assert not eligible
    daily_bound_checks = 0
    for row in attempts[attempts.scenario == "baseline"].itertuples():
        low = ledgers[row.case_id].set_index("date")
        high = ledgers[row.case_id.replace("_baseline", "_favorable_order")].set_index("date")
        assert low.index.equals(high.index)
        assert (low.net_dollars <= high.net_dollars+1e-8).all()
        daily_bound_checks += len(low)

    raw = pd.read_parquet(summary["data"]["path"]).tz_convert("America/New_York")
    raw_checks = 0
    raw_dates = []
    for row in attempts[attempts.scenario == "baseline"].itertuples():
        trades = ledgers[row.case_id].query("filled")
        for pos in sorted(set([0, len(trades)//2, len(trades)-1])):
            t = trades.iloc[pos]
            start = pd.Timestamp(t.date+" 09:30", tz="America/New_York")
            day = raw.loc[(raw.index >= start) & (raw.index < start+pd.Timedelta(minutes=135))]
            assert len(day) == 135
            upper, lower = day.open.iloc[0]+t.trigger, day.open.iloc[0]-t.trigger
            trigger_minute = None
            possible_sides = []
            for i in range(15):
                bar = day.iloc[i]
                if bar.open >= upper:
                    possible_sides = [-1]
                elif bar.open <= lower:
                    possible_sides = [1]
                else:
                    possible_sides = ([-1] if bar.high >= upper else []) + ([1] if bar.low <= lower else [])
                if possible_sides:
                    trigger_minute = i
                    break
            assert trigger_minute == t.trigger_idx and t.side in possible_sides
            side = int(t.side)
            level = upper if side == -1 else lower
            if t["mode"] == "touch":
                assert t.entry_idx == trigger_minute and t.entry_price == level
            else:
                confirmation = next(i for i in range(trigger_minute, 15)
                                    if side*(day.close.iloc[i]-level) > 0)
                assert t.confirmation_idx == confirmation and t.entry_idx == confirmation+1
                assert t.entry_price == day.open.iloc[confirmation+1]
            assert t.target_price == t.entry_price+side*t.trigger/2
            assert t.stop_price == t.entry_price-side*t.trigger/2
            ex = day.iloc[int(t.exit_idx)]
            if "target" in t.exit_reason:
                assert t.exit_price == t.target_price
                assert ex.high >= t.target_price if side == 1 else ex.low <= t.target_price
                if t.exit_at_open:
                    assert side*(ex.open-t.target_price) >= 0
            elif "stop" in t.exit_reason:
                if t.exit_at_open:
                    assert t.exit_price == ex.open and side*(ex.open-t.stop_price) <= 0
                else:
                    assert t.exit_price == t.stop_price
                    assert ex.low <= t.stop_price if side == 1 else ex.high >= t.stop_price
            else:
                assert t.exit_reason == "time_exit"
                assert t.exit_idx == t.entry_idx+t.horizon and t.exit_price == ex.open
            raw_checks += 1
            raw_dates.append(t.date)
    return {"reconciled_development_ledgers": len(ledgers),
            "daily_conservative_favorable_bound_checks": daily_bound_checks,
            "raw_mnq_signal_entry_bracket_checks": raw_checks,
            "raw_check_latest_date": max(raw_dates),
            "all_baseline_eligibility_failures_verified": True,
            "no_evaluation_or_later_outcome_ledgers": True,
            "cost_gross_net_pf_drawdown_counts": "passed"}


if __name__ == "__main__":
    result = {"status": "passed", "synthetic_ordered_path_bound_checks": verify_synthetic_bounds(),
              **verify_actual_exports()}
    (OUT / "independent_review_checks.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, indent=2))
