"""Conditional overnight direction on real CME futures (Databento 5-min).

Question: is the overnight drift positive in ALL prior-day scenarios (=> only
ever long), or are there buckets where it's negative/weak (=> short or go flat)?

For each night we take overnight_ret = RTH_open[t] / RTH_close[t-1] - 1, and
condition on the PRIOR RTH session (known at that close, no look-ahead):
  green/red day, closing zone (close location in range), trend regime (vs SMA20),
  day range (vol), open gap, prior night's result, day of week.

Part 1: per-bucket mean/hit/Sharpe/t-stat — where does the edge live or die?
Part 2: pre-specified direction rules compared net of tick costs (no in-sample
        bucket cherry-picking).

    python overnight_conditional_backtest.py --symbols MES,MNQ --ticks 1
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from pwb_toolbox.performance.metrics import sharpe_ratio, cagr, max_drawdown

DATA = Path(__file__).with_name("data")
SPECS = {"MES": (0.25, 5.0), "MNQ": (0.25, 2.0), "CL": (0.01, 1000.0), "GC": (0.10, 100.0)}
RTH = ("09:30", "15:59")


def features(sym):
    df = pd.read_parquet(DATA / f"{sym}_5min_databento.parquet")
    df.index = pd.to_datetime(df.index)
    rth = df.sort_index().between_time(*RTH)
    g = rth.groupby(rth.index.normalize())
    d = pd.DataFrame({"o": g["open"].first(), "h": g["high"].max(),
                      "l": g["low"].min(), "c": g["close"].last()}).dropna()
    prevc = d["c"].shift(1)
    on = (d["o"] / prevc - 1)
    on = on.clip(on.quantile(0.005), on.quantile(0.995))     # kill roll-day spikes
    f = pd.DataFrame(index=d.index)
    f["on"] = on                                             # target: THIS night
    # conditioning on the just-completed day (t-1), shifted to align with tonight
    day_ret = (d["c"] / d["o"] - 1)
    loc = ((d["c"] - d["l"]) / (d["h"] - d["l"]).replace(0, np.nan))
    rng = ((d["h"] - d["l"]) / d["o"])
    sma = d["c"].rolling(20).mean()
    gap = (d["o"] / prevc - 1)
    f["green"] = (day_ret > 0).shift(1)
    f["dayret"] = day_ret.shift(1)
    f["loc"] = loc.shift(1)
    f["rng"] = rng.shift(1)
    f["above_sma"] = (d["c"] > sma).shift(1)
    f["gap"] = gap.shift(1)
    f["prev_on"] = on.shift(1)
    f["dow"] = pd.Series(d.index.dayofweek, index=d.index).shift(1)
    return f.dropna(subset=["on"])


def bstats(x):
    x = x.dropna()
    if len(x) < 10:
        return len(x), np.nan, np.nan, np.nan, np.nan
    mean, sd = x.mean(), x.std(ddof=0)
    sh = mean / sd * np.sqrt(252) if sd > 0 else np.nan
    t = mean / (sd / np.sqrt(len(x))) if sd > 0 else np.nan
    return len(x), mean * 1e4, (x > 0).mean() * 100, sh, t


def show_buckets(title, groups):
    print(f"\n  {title}")
    print(f"    {'bucket':<16}{'n':>5}{'mean bps':>10}{'hit%':>7}{'Sharpe':>8}{'t':>7}")
    for name, x in groups:
        n, mbps, hit, sh, t = bstats(x)
        print(f"    {name:<16}{n:>5}{mbps:>10.1f}{hit:>7.0f}{sh:>8.2f}{t:>7.2f}")


def strat_stats(dir_series, on, cost, bal=100_000):
    r = (dir_series * on - (dir_series != 0).astype(float) * cost).dropna()
    nav = (bal * (1 + r).cumprod()).tolist()
    depth, _ = max_drawdown(nav)
    return sharpe_ratio(nav), cagr(nav), abs(depth), (dir_series != 0).mean() * 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="MES,MNQ")
    ap.add_argument("--ticks", type=float, default=1.0)
    args = ap.parse_args()
    syms = [s.strip().upper() for s in args.symbols.split(",")]

    for sym in syms:
        tick, _ = SPECS[sym]
        f = features(sym)
        on = f["on"]
        # cost per trade as a return ~= tick size / typical price level
        price_proxy = {"MES": 5500, "MNQ": 20000, "CL": 75, "GC": 3000}[sym]
        cost = args.ticks * tick / price_proxy

        print("=" * 62)
        print(f"{sym}  |  {len(on)} nights  |  cost {args.ticks} tick (~{cost*1e4:.2f} bps)")
        # overall
        n, mbps, hit, sh, t = bstats(on)
        print(f"  ALL nights: mean {mbps:.1f} bps  hit {hit:.0f}%  Sharpe {sh:.2f}  t {t:.2f}")

        show_buckets("By day color", [
            ("green day", on[f["green"] == True]),
            ("red day", on[f["green"] == False])])
        show_buckets("By closing zone", [
            ("closed low 3rd", on[f["loc"] < 0.33]),
            ("closed mid", on[(f["loc"] >= 0.33) & (f["loc"] <= 0.67)]),
            ("closed high 3rd", on[f["loc"] > 0.67])])
        show_buckets("By trend regime", [
            ("above SMA20", on[f["above_sma"] == True]),
            ("below SMA20", on[f["above_sma"] == False])])
        show_buckets("By day range (vol)", [
            ("calm 3rd", on[f["rng"] < f["rng"].quantile(0.33)]),
            ("mid", on[(f["rng"] >= f["rng"].quantile(0.33)) & (f["rng"] <= f["rng"].quantile(0.67))]),
            ("wild 3rd", on[f["rng"] > f["rng"].quantile(0.67)])])
        show_buckets("By open gap", [
            ("gapped up", on[f["gap"] > 0.002]),
            ("flat open", on[(f["gap"] >= -0.002) & (f["gap"] <= 0.002)]),
            ("gapped down", on[f["gap"] < -0.002])])
        show_buckets("By prior night", [
            ("prev night up", on[f["prev_on"] > 0]),
            ("prev night down", on[f["prev_on"] < 0])])
        show_buckets("By day of week (close->next open)", [
            (d, on[f["dow"] == i]) for i, d in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri"])])

        # ---- pre-specified direction rules (net of cost) --------------------
        L = pd.Series(1.0, index=on.index)
        rules = {
            "Always long": L,
            "Long green / short red": np.sign(f["green"].map({True: 1.0, False: -1.0})),
            "Long red / short green": np.sign(f["green"].map({True: -1.0, False: 1.0})),
            "Long hi-close / short lo": pd.Series(np.where(f["loc"] > 0.5, 1.0, -1.0), index=on.index),
            "Long lo-close / short hi": pd.Series(np.where(f["loc"] > 0.5, -1.0, 1.0), index=on.index),
            "Long only above SMA20": pd.Series(np.where(f["above_sma"] == True, 1.0, 0.0), index=on.index),
            "Long, flat if red+lo-close": pd.Series(np.where((f["green"] == False) & (f["loc"] < 0.33), 0.0, 1.0), index=on.index),
            "Long, flat on wild days": pd.Series(np.where(f["rng"] > f["rng"].quantile(0.8), 0.0, 1.0), index=on.index),
        }
        print(f"\n  DIRECTION RULES (net {args.ticks} tick):")
        print(f"    {'rule':<28}{'Sharpe':>8}{'CAGR':>8}{'MaxDD':>8}{'%in':>6}")
        for name, dseries in rules.items():
            d = dseries.reindex(on.index).fillna(0.0)
            shp, cg, dd, pin = strat_stats(d, on, cost)
            print(f"    {name:<28}{shp:>8.2f}{cg*100:>7.1f}%{dd*100:>7.1f}%{pin:>6.0f}")
        print()


if __name__ == "__main__":
    main()
