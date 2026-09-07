"""Filtered overnight: skip no-bounce nights + high-vol regimes (diagnostic-driven).

From overnight_loss_profile.py: the overnight bounce is dead/negative when the
prior day closed near its high or sits inside the prior week's range, and the big
losses cluster in high-vol crash weeks. This tests filters that sit those out,
using the TP=PDH exit + optional PDL stop.

HONESTY: these filters were chosen from this same 2020-2026 data, so the full-
sample numbers are in-sample/optimistic. Section 2 splits train (2020-2023) vs
test (2024-2026) so the out-of-sample degradation is visible.

    python overnight_filtered_backtest.py --symbols MES,MNQ
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from pwb_toolbox.performance.metrics import sharpe_ratio, cagr, max_drawdown

DATA = (Path(__file__).resolve().parents[2] / "data")
SPECS = {"MES": (0.25, 5.0), "MNQ": (0.25, 2.0)}
RTH = ("09:30", "15:59")


def build(sym):
    df = pd.read_parquet(DATA / f"{sym}_5min_databento.parquet")
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    rth = df.between_time(*RTH)
    day = rth.index.normalize()
    idx = pd.Series(rth.index, index=rth.index)
    d = pd.DataFrame({
        "first_ts": idx.groupby(day).first(), "last_ts": idx.groupby(day).last(),
        "open": rth["open"].groupby(day).first(), "high": rth["high"].groupby(day).max(),
        "low": rth["low"].groupby(day).min(), "close": rth["close"].groupby(day).last(),
    }).dropna()
    loc = (d["close"] - d["low"]) / (d["high"] - d["low"]).replace(0, np.nan)
    d["zone"] = pd.cut(loc, [-0.01, 0.33, 0.67, 1.01], labels=["low", "mid", "high"])
    d["red"] = d["close"] < d["open"]
    # prior-week high/low -> position vs range
    whi = d["high"].groupby(d.index.to_period("W")).max().shift(1)
    wlo = d["low"].groupby(d.index.to_period("W")).min().shift(1)
    per = pd.Series(d.index.to_period("W"), index=d.index)
    pwh, pwl = per.map(whi), per.map(wlo)
    d["below_pwl"] = d["close"] < pwl
    d["inside_wk"] = (d["close"] <= pwh) & (d["close"] >= pwl)
    # realized-vol regime (10d daily-return std), high = top quintile of trailing 120d
    ret = d["close"].pct_change()
    rv = ret.rolling(10).std()
    d["vol_high"] = rv > rv.rolling(120, min_periods=40).quantile(0.80)
    return df, d


FILTERS = {
    "baseline (all)": lambda r: True,
    "skip closed-high": lambda r: r["zone"] != "high",
    "skip hi + inside-wk": lambda r: (r["zone"] != "high") and (not bool(r["inside_wk"])),
    "skip hi + vol-guard": lambda r: (r["zone"] != "high") and (not bool(r["vol_high"])),
    "dislocation only": lambda r: (r["zone"] == "low") or bool(r["below_pwl"]),
    "disloc + vol-guard": lambda r: ((r["zone"] == "low") or bool(r["below_pwl"])) and (not bool(r["vol_high"])),
}


def exit_price(entry, ov, eo, tp, stop):
    tp = tp if (tp is not None and tp > entry) else None
    stop = stop if (stop is not None and stop < entry) else None
    if tp is not None or stop is not None:
        for hi, lo in zip(ov["high"].to_numpy(), ov["low"].to_numpy()):
            if stop is not None and lo <= stop:
                return stop
            if tp is not None and hi >= tp:
                return tp
    return eo


def run(sym, filt, use_stop, ticks, start, end):
    tick, dpp = SPECS[sym]
    df, d = build(sym)
    tz = d.index.tz
    lo = pd.Timestamp(start).tz_localize(tz)
    hi = pd.Timestamp(end).tz_localize(tz) if end else d.index.max()
    days = d.index
    fn = FILTERS[filt]
    rows = []
    for i in range(1, len(days)):
        D, Dn = days[i - 1], days[i]
        if D < lo or D > hi:
            continue
        r = d.loc[D]
        if not fn(r):
            rows.append((D, 0.0, np.nan, False)); continue
        entry = r["close"]
        ov = df.loc[r["last_ts"]:d.loc[Dn, "first_ts"]].iloc[1:-1]
        if len(ov) == 0:
            rows.append((D, 0.0, np.nan, False)); continue
        eo = d.loc[Dn, "open"]
        ex = exit_price(entry, ov, eo, r["high"], r["low"] if use_stop else None)
        pts = (ex - entry) - ticks * tick
        rows.append((D, pts / entry, pts * dpp, True))
    t = pd.DataFrame(rows, columns=["d", "ret", "usd", "traded"]).set_index("d")
    return t


def summarize(t, bal=100_000):
    r = t["ret"].clip(-0.2, 0.2)
    nav = (bal * (1 + r).cumprod()).tolist()
    depth, _ = max_drawdown(nav)
    usd = t["usd"].dropna()
    return {"sharpe": sharpe_ratio(nav), "cagr": cagr(nav), "maxdd": abs(depth),
            "pct": t["traded"].mean() * 100, "worst": usd.min() if len(usd) else np.nan,
            "l500": (usd < -500).mean() * 100 if len(usd) else np.nan,
            "total": usd.sum()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="MES,MNQ")
    ap.add_argument("--ticks", type=float, default=1.0)
    args = ap.parse_args()

    for sym in [s.strip().upper() for s in args.symbols.split(",")]:
        print("=" * 88)
        print(f"{sym}  |  full sample 2020->now  |  TP=PDH + PDL stop  |  cost {args.ticks} tick  (IN-SAMPLE)")
        hdr = (f"{'filter':<22}{'Sharpe':>8}{'CAGR':>8}{'MaxDD':>8}{'%trade':>7}"
               f"{'$worst':>8}{'<-500':>7}{'total$':>9}")
        print(hdr); print("-" * len(hdr))
        for name in FILTERS:
            s = summarize(run(sym, name, True, args.ticks, "2020-01-01", None))
            print(f"{name:<22}{s['sharpe']:>8.2f}{s['cagr']*100:>7.1f}%{s['maxdd']*100:>7.1f}%"
                  f"{s['pct']:>6.0f}%{s['worst']:>8.0f}{s['l500']:>6.1f}%{s['total']:>9,.0f}")

        # train/test on two promising filters, with/without stop
        print(f"\n  TRAIN (2020-2023) vs TEST (2024-now) — out-of-sample check")
        print(f"    {'filter / exit':<30}{'Tr Sharpe':>10}{'Tr $worst':>10}{'Te Sharpe':>10}{'Te $worst':>10}{'Te CAGR':>9}")
        for name in ["skip hi + vol-guard", "disloc + vol-guard"]:
            for stop in (True, False):
                tag = f"{name} {'+stop' if stop else 'TP-only'}"
                tr = summarize(run(sym, name, stop, args.ticks, "2020-01-01", "2023-12-31"))
                te = summarize(run(sym, name, stop, args.ticks, "2024-01-01", None))
                print(f"    {tag:<30}{tr['sharpe']:>10.2f}{tr['worst']:>10.0f}"
                      f"{te['sharpe']:>10.2f}{te['worst']:>10.0f}{te['cagr']*100:>8.1f}%")
        print()


if __name__ == "__main__":
    main()
