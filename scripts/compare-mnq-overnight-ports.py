"""Compare the actual C# overnight clocks on the same MNQ bars and costs.

This is a deterministic next-open research replay, not a NinjaTrader fill test.
The C# driver executes the unchanged shared clock core and emits decision rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from strategy_engine.data import session_bars
from strategy_engine.sessions import get_session

DRIVER = r'''using System;
using System.Globalization;
using NinjaTrader.NinjaScript.Strategies;
class ClockReplay {
  static void Main(string[] args) {
    var rules = new WorkbenchMnqOvernightRules();
    bool held=false; int pending=0; int row=0; string line;
    while ((line=Console.ReadLine()) != null) {
      if (pending != 0) held = pending > 0;
      DateTime close=DateTime.ParseExact(line,"yyyyMMdd HHmmss",CultureInfo.InvariantCulture);
      int signal=args[0]=="block" ? rules.BlockSignal(close,held) : rules.SessionSignal(close,held);
      if(signal!=0) Console.WriteLine(row.ToString()+","+signal.ToString());
      pending=signal; row++;
    }
  }
}'''


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False, default=str), encoding="utf-8")


def get(endpoint):
    with urllib.request.urlopen("http://127.0.0.1:8001/api/workbench/" + endpoint, timeout=60) as response:
        return json.load(response)


def aggregate_fifteen(minutes):
    # Full ETH is already filtered and labelled by the canonical minute path.
    # Every session opens at an integer quarter-hour, including DST weeks.
    grouper = minutes.index.floor("15min", ambiguous="infer", nonexistent="shift_forward")
    bars = minutes.groupby(grouper).agg(open=("open", "first"), high=("high", "max"),
                                        low=("low", "min"), close=("close", "last"), volume=("volume", "sum"),
                                        session_date=("session_date", "first"))
    bars["availability_time"] = bars.index + pd.Timedelta(minutes=15)
    bars["session_id"] = "full-trading-day"
    return bars


def replay(exe, mode, bars, raw, start, end, point, commission, slip):
    times = pd.DatetimeIndex(bars.availability_time).strftime("%Y%m%d %H%M%S")
    completed = subprocess.run([str(exe), mode], input="\n".join(times) + "\n", text=True,
                               capture_output=True, check=True)
    entries, rows = None, []
    for decision in completed.stdout.splitlines():
        signal_i, action = map(int, decision.split(","))
        fill_i = signal_i + 1
        if fill_i >= len(bars):
            continue
        fill = bars.iloc[fill_i]
        # The nominal 15m open can precede its first observed underlying quote.
        raw_i = int(raw.index.searchsorted(bars.index[fill_i]))
        actual_time = raw.index[raw_i]
        assert float(fill.open) == float(raw.open.iloc[raw_i])
        if action == 1:
            assert entries is None
            entries = (actual_time, float(fill.open), raw_i, str(fill.session_date))
        else:
            assert entries is not None
            entry_time, entry, first, session_date = entries
            gross = (float(fill.open) - entry) * point
            if start <= session_date <= end:
                held = raw.iloc[first:raw_i]
                rows.append(dict(strategy=mode, session_date=session_date,
                    entry_time=entry_time.isoformat(), exit_time=actual_time.isoformat(),
                    entry=entry, exit=float(fill.open), quantity=1, gross_pnl=gross,
                    commission=2 * commission, slippage=2 * slip * .25 * point,
                    net_pnl=gross - 2 * commission - 2 * slip * .25 * point,
                    maximum_adverse_excursion_usd=float((held.low.min() - entry) * point),
                    duration_minutes=(actual_time - entry_time).total_seconds() / 60,
                    crosses_contract_change=bool(raw.instrument_id.iloc[first:raw_i + 1].nunique() > 1),
                    entry_row=first, exit_row=raw_i))
            entries = None
    return pd.DataFrame(rows)


def metrics(trades, raw, start, end, point, commission, slip):
    per_side = commission + slip * .25 * point
    cash_events = np.zeros(len(raw))
    held = np.zeros(len(raw), dtype=bool)
    basis = np.zeros(len(raw))
    for t in trades.itertuples():
        cash_events[t.entry_row] -= per_side
        cash_events[t.exit_row] += t.gross_pnl - per_side
        held[t.entry_row:t.exit_row] = True
        basis[t.entry_row:t.exit_row] = t.entry
    pnl = np.cumsum(cash_events) + np.where(held, (raw.close.to_numpy() - basis) * point, 0)
    valid = (raw.session_date.to_numpy() >= start) & (raw.session_date.to_numpy() <= end)
    pnl_window = pnl[valid]
    peak = np.maximum.accumulate(np.r_[0., pnl_window])
    marked_dd = float(np.min(np.r_[0., pnl_window] - peak))
    realized = np.r_[0., trades.net_pnl.cumsum().to_numpy()]
    realized_dd = float(np.min(realized - np.maximum.accumulate(realized)))
    daily = pd.DataFrame({"session_date": raw.session_date.to_numpy()[valid], "cumulative_net_pnl": pnl_window})
    daily = daily.groupby("session_date", sort=True).last()
    daily["net_pnl"] = daily.cumulative_net_pnl.diff().fillna(daily.cumulative_net_pnl.iloc[0])
    assert abs(float(pnl[-1]) - float(trades.net_pnl.sum())) < 1e-7
    yearly = trades.groupby(trades.session_date.str[:4]).net_pnl.sum().to_dict()
    positives = trades.loc[trades.net_pnl > 0, "net_pnl"].sum()
    negatives = -trades.loc[trades.net_pnl < 0, "net_pnl"].sum()
    result = dict(net_pnl=float(trades.net_pnl.sum()), gross_pnl=float(trades.gross_pnl.sum()),
                  commission=float(trades.commission.sum()), slippage=float(trades.slippage.sum()),
                  trades=len(trades), win_rate=float((trades.net_pnl > 0).mean()),
                  profit_factor=float(positives / negatives),
                  minute_close_marked_max_drawdown_usd=marked_dd,
                  closed_trade_max_drawdown_usd=realized_dd,
                  worst_trade_mae_usd=float(trades.maximum_adverse_excursion_usd.min()),
                  net_2024_onward=float(trades.loc[trades.session_date >= "2024-01-01", "net_pnl"].sum()),
                  yearly_net_pnl=yearly,
                  contract_change_trades=int(trades.crosses_contract_change.sum()),
                  net_excluding_contract_change_trades=float(trades.loc[~trades.crosses_contract_change, "net_pnl"].sum()),
                  doubled_cost_net_pnl=float(trades.gross_pnl.sum() - 2 * (trades.commission.sum() + trades.slippage.sum())))
    return result, daily, held


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2026-08-31")
    ap.add_argument("--commission-per-side", type=float, default=.62)
    ap.add_argument("--slippage-ticks-per-side", type=float, default=1.)
    ap.add_argument("--output", default="reports/overnight-comparison-2026-09-29")
    args = ap.parse_args()
    folder = ROOT / args.output
    folder.mkdir(parents=True, exist_ok=True)
    state, catalog = get("state?view=summary"), get("collective")
    dataset = next(d for d in state["datasets"] if d["symbol"] == "MNQ")
    keys = {"pine-overnight-block__NQ__15m", "overnight-session__NQ__1m__globex-overnight"}
    saved = [d for d in catalog["items"] if d["key"] in keys]
    dump(folder / "live-evidence.json", dict(dataset=dataset, catalog_generated_at=catalog["generated_at"], saved_nq=saved))
    actual_hash = sha(dataset["path"])
    assert actual_hash == dataset["checksum"]
    raw = pd.read_parquet(dataset["path"])
    lo = pd.Timestamp(args.start, tz="UTC") - pd.Timedelta(days=15)
    hi = pd.Timestamp(args.end, tz="UTC") + pd.Timedelta(days=3)
    raw = raw.loc[(raw.index >= lo) & (raw.index < hi)]
    ids = raw.instrument_id
    minutes = session_bars(raw, get_session("full-trading-day"), "1m")
    minutes["instrument_id"] = ids.reindex(minutes.index).to_numpy()
    quarter = aggregate_fifteen(minutes)
    # The faster quarter-hour aggregation must match the canonical implementation.
    sample = raw.loc["2024-03-08":"2024-03-12"]
    expected = session_bars(sample, get_session("full-trading-day"), "15m")
    actual = aggregate_fifteen(session_bars(sample, get_session("full-trading-day"), "1m"))
    pd.testing.assert_frame_equal(actual[expected.columns], expected, check_freq=False, check_names=False)
    (folder / "ClockReplay.cs").write_text(DRIVER, encoding="utf-8")
    core = ROOT / "ninjatrader/WorkbenchMnqOvernightRules.cs"
    (folder / core.name).write_bytes(core.read_bytes())
    (folder / Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    result = dict(schema_version=1, symbol="MNQ", point_value=2, tick_size=.25, contracts=1,
                  start_session_date=args.start, end_session_date=args.end,
                  commission_per_side=args.commission_per_side,
                  slippage_ticks_per_side=args.slippage_ticks_per_side,
                  round_turn_cost_usd=2 * args.commission_per_side + args.slippage_ticks_per_side,
                  dataset=dataset, core_sha256=sha(core), script_sha256=sha(__file__),
                  execution="Unchanged compiled C# clock decisions; market orders fill next observed primary-bar open; minute-close marked equity on the same underlying MNQ feed.",
                  results={})
    held_vectors = []
    with tempfile.TemporaryDirectory(prefix="overnight-compare-") as temp:
        exe = Path(temp) / "clock.exe"
        subprocess.run(["C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe", "/nologo", "/langversion:5",
                        "/target:exe", f"/out:{exe}", str(core), str(folder / "ClockReplay.cs")],
                       check=True, capture_output=True, text=True)
        for mode, bars in [("block", quarter), ("session", minutes)]:
            print(f"Replaying {mode}: {len(bars):,} bars", flush=True)
            trades = replay(exe, mode, bars, minutes, args.start, args.end, 2,
                            args.commission_per_side, args.slippage_ticks_per_side)
            summary, daily, held = metrics(trades, minutes, args.start, args.end, 2,
                                           args.commission_per_side, args.slippage_ticks_per_side)
            trades.to_csv(folder / f"{mode}-trades.csv", index=False)
            daily.to_csv(folder / f"{mode}-daily.csv")
            result["results"][mode] = summary
            held_vectors.append(held)
            print(json.dumps({mode: summary}, indent=2), flush=True)
    result["winner_by_net_pnl"] = max(result["results"], key=lambda key: result["results"][key]["net_pnl"])
    result["net_difference_block_minus_session"] = result["results"]["block"]["net_pnl"] - result["results"]["session"]["net_pnl"]
    result["winner_excluding_contract_change_trades"] = max(result["results"], key=lambda key: result["results"][key]["net_excluding_contract_change_trades"])
    result["winner_doubled_costs"] = max(result["results"], key=lambda key: result["results"][key]["doubled_cost_net_pnl"])
    common = held_vectors[0] & held_vectors[1]
    result["overlap"] = dict(shared_observed_minutes=int(common.sum()),
                             share_of_block_minutes=float(common.sum() / held_vectors[0].sum()),
                             share_of_session_minutes=float(common.sum() / held_vectors[1].sum()))
    result["limitations"] = [
        "These dates were already available and reviewed; this comparison is historical selection, not an untouched holdout or profitability guarantee.",
        "No NinjaTrader runtime/Playback fill test is implied; provider bars, holidays, connectivity and actual fills can differ.",
        "MNQ cache has unverified original vendor request provenance, missing minutes and unadjusted continuous-contract rolls.",
        "Calendar uses canonical weekday ETH filtering, not an authoritative CME holiday schedule. Next available quotes are used across gaps.",
        "Drawdown is marked on observed one-minute closes, not every tick; worst trade low is also shown. Neither strategy has a stop.",
        "Costs are matched research assumptions, not verified brokerage rates; default commission is $0.62 per side plus one tick per side.",
        "Trading session dates determine the common window, not UTC calendar entry dates. Only closed trades with entry session in the window are scored.",
    ]
    result["artifacts"] = {p.name: sha(p) for p in sorted(folder.glob("*.csv"))}
    dump(folder / "comparison.json", result)
    table = "| MNQ port | Net P&L | Trades | Minute-close max DD | Gross P&L | Costs |\n|---|---:|---:|---:|---:|---:|\n"
    for key, row in result["results"].items():
        table += f"| {key} | ${row['net_pnl']:,.2f} | {row['trades']:,} | ${row['minute_close_marked_max_drawdown_usd']:,.2f} | ${row['gross_pnl']:,.2f} | ${row['commission'] + row['slippage']:,.2f} |\n"
    (folder / "README.md").write_text(
        f"# Matched MNQ overnight comparison\n\nMore profitable in this replay: **{result['winner_by_net_pnl']}**. "
        f"Block minus Session: **${result['net_difference_block_minus_session']:,.2f}**.\n\n"
        f"{args.start} through {args.end} trading session dates; one MNQ; identical ${result['round_turn_cost_usd']:.2f} round-turn costs. "
        "Actual unchanged C# clock decisions were executed on the same MNQ data, with next-open fills. "
        "Block uses 15-minute clock transitions; Session uses the installed conservative 18:01 entry.\n\n" + table +
        "\nThe catalog's larger NQ Session baseline total uses the 18:00 entry and does not describe the installed 18:01 port. "
        "The strategies hold almost the same overnight long exposure; running both largely doubles it.\n\n" +
        f"The winner remains **{result['winner_excluding_contract_change_trades']}** after excluding trades crossing recorded contract changes "
        f"(Block ${result['results']['block']['net_excluding_contract_change_trades']:,.2f}; Session ${result['results']['session']['net_excluding_contract_change_trades']:,.2f}) "
        f"and **{result['winner_doubled_costs']}** with doubled costs.\n\n" +
        "\n".join("- " + x for x in result["limitations"]) +
        "\n\nReproduce: `.venv/Scripts/python.exe scripts/compare-mnq-overnight-ports.py`\n", encoding="utf-8")
    print(f"Winner: {result['winner_by_net_pnl']}; block minus session ${result['net_difference_block_minus_session']:,.2f}", flush=True)


if __name__ == "__main__":
    main()
