"""Why do overnight nights lose? Loss attribution on real MES/MNQ (2020-now).

Baseline long overnight (RTH close -> next RTH open). For each night we tag the
just-closed day / week context (all known at entry, no look-ahead) and profile
WINNERS vs LOSERS across: prior-day range size, prior-day behavior (color, close
location, gap), prior-week behavior (up/down week, week range, position vs PWH/
PWL), day of week, and prior night. Each bucket shows n, win%, mean bps, and the
TOTAL $ P&L it contributed per 1 contract (the number that says "this bucket is
where money is made / lost"). Plus the 12 worst nights with their full context.

Overnight returns winsorized lightly (0.1/99.9%) to drop obvious roll-day spikes
while keeping real news gaps.

    python overnight_loss_profile.py --symbols MES,MNQ
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA = (Path(__file__).resolve().parents[2] / "data")
SPECS = {"MES": (0.25, 5.0), "MNQ": (0.25, 2.0)}
RTH = ("09:30", "15:59")
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri"]


def build(sym, start):
    df = pd.read_parquet(DATA / f"{sym}_5min_databento.parquet")
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df = df[df.index >= pd.Timestamp(start).tz_localize(df.index.tz)]
    rth = df.between_time(*RTH)
    day = rth.index.normalize()
    d = pd.DataFrame({
        "open": rth["open"].groupby(day).first(), "high": rth["high"].groupby(day).max(),
        "low": rth["low"].groupby(day).min(), "close": rth["close"].groupby(day).last(),
    }).dropna()
    prevc = d["close"].shift(1)
    on = (d["open"].shift(-1) / d["close"] - 1)          # overnight AFTER day D
    on = on.clip(on.quantile(0.001), on.quantile(0.999))
    f = pd.DataFrame(index=d.index)
    f["on"] = on
    f["usd"] = on * d["close"] * SPECS[sym][1]           # $ per 1 contract
    # prior-day behavior (day D)
    f["range_pct"] = (d["high"] - d["low"]) / d["open"]
    f["range_tercile"] = pd.qcut(f["range_pct"], 3, labels=["calm", "mid", "wild"])
    f["color"] = np.where(d["close"] > d["open"], "green", "red")
    loc = (d["close"] - d["low"]) / (d["high"] - d["low"]).replace(0, np.nan)
    f["close_zone"] = pd.cut(loc, [-0.01, 0.33, 0.67, 1.01], labels=["low", "mid", "high"])
    f["gap"] = np.where(d["open"] / prevc - 1 > 0.002, "gap up",
                np.where(d["open"] / prevc - 1 < -0.002, "gap dn", "flat"))
    f["dow"] = pd.Categorical([DOW[x] for x in d.index.dayofweek], categories=DOW, ordered=True)
    # prior-week behavior
    wcl = d["close"].groupby(d.index.to_period("W")).last()
    wret = wcl.pct_change().shift(1)                      # prior completed week return
    whi = d["high"].groupby(d.index.to_period("W")).max().shift(1)
    wlo = d["low"].groupby(d.index.to_period("W")).min().shift(1)
    per = pd.Series(d.index.to_period("W"), index=d.index)
    f["prev_week"] = np.where(per.map(wret) > 0, "up week", "down week")
    wrng = ((d["high"].groupby(d.index.to_period("W")).max()
             - d["low"].groupby(d.index.to_period("W")).min())
            / d["open"].groupby(d.index.to_period("W")).first()).shift(1)
    wr_med = wrng.median()
    f["prev_week_range"] = np.where(per.map(wrng) > wr_med, "wide wk", "calm wk")
    pwh = per.map(whi); pwl = per.map(wlo)
    f["vs_prevwk"] = np.where(d["close"] > pwh, "above PWH",
                     np.where(d["close"] < pwl, "below PWL", "inside"))
    f["prev_night"] = np.where(on.shift(1) > 0, "prev up", "prev dn")
    return f.dropna(subset=["on"])


def profile(f, col):
    g = f.groupby(col, observed=True)
    out = pd.DataFrame({
        "n": g.size(),
        "win%": g["on"].apply(lambda x: (x > 0).mean() * 100),
        "mean_bps": g["on"].mean() * 1e4,
        "total$": g["usd"].sum(),
        "avgLoss$": g["usd"].apply(lambda x: x[x < 0].mean()),
    })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="MES,MNQ")
    ap.add_argument("--start", default="2020-01-01")
    args = ap.parse_args()

    for sym in [s.strip().upper() for s in args.symbols.split(",")]:
        f = build(sym, args.start)
        print("=" * 76)
        print(f"{sym}  |  {len(f)} nights  |  {args.start}->now  |  overnight long, $/1 contract")
        print(f"  overall: win {int((f['on']>0).mean()*100)}%  "
              f"mean {f['on'].mean()*1e4:.1f} bps  total ${f['usd'].sum():,.0f}  "
              f"avg loss ${f['usd'][f['usd']<0].mean():.0f}")
        for col, title in [("range_tercile", "PRIOR-DAY RANGE SIZE"),
                           ("color", "PRIOR-DAY COLOR"),
                           ("close_zone", "PRIOR-DAY CLOSE ZONE"),
                           ("gap", "PRIOR-DAY OPEN GAP"),
                           ("prev_week", "PRIOR-WEEK DIRECTION"),
                           ("prev_week_range", "PRIOR-WEEK RANGE"),
                           ("vs_prevwk", "CLOSE vs PRIOR-WEEK H/L"),
                           ("prev_night", "PRIOR NIGHT"),
                           ("dow", "DAY OF WEEK (close->next open)")]:
            p = profile(f, col)
            print(f"\n  {title}")
            print(f"    {'bucket':<12}{'n':>5}{'win%':>7}{'mean bps':>10}{'total$':>10}{'avgLoss$':>10}")
            for b, r in p.iterrows():
                print(f"    {str(b):<12}{int(r['n']):>5}{r['win%']:>6.0f}%{r['mean_bps']:>10.1f}"
                      f"{r['total$']:>10,.0f}{r['avgLoss$']:>10.0f}")

        # worst nights with context
        w = f.nsmallest(12, "usd")
        print(f"\n  12 WORST NIGHTS ($/1 contract)")
        print(f"    {'date':<12}{'$loss':>8}{'range':>7}{'color':>7}{'zone':>6}{'gap':>7}"
              f"{'prevWk':>10}{'vsWk':>11}{'dow':>5}")
        for dt, r in w.iterrows():
            print(f"    {str(dt.date()):<12}{r['usd']:>8.0f}{r['range_pct']*100:>6.1f}%"
                  f"{r['color']:>7}{str(r['close_zone']):>6}{r['gap']:>7}"
                  f"{r['prev_week']:>10}{r['vs_prevwk']:>11}{str(r['dow']):>5}")
        print()


if __name__ == "__main__":
    main()
