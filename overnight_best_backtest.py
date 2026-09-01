"""Best-case overnight: TP=PDH exit + optional PDL stop + night selectivity.

Stacks the two things that worked: take profit at the prior-day high (locks the
overnight bounce), an optional stop at the prior-day low (caps the loss), and
FILTERS that sit out low-edge / high-tail nights. The goal is to reduce the
per-contract loss tail while retaining usable risk-adjusted performance.

Real Databento MES/MNQ 5-min, 2020->now. No look-ahead: every filter uses the
just-closed day's stats (known at entry). Stops fill at the level in-sample; a
real news gap can blow through, so treat $worst as optimistic.

    python overnight_best_backtest.py --symbols MES,MNQ --ticks 1
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from pwb_toolbox.performance.metrics import sharpe_ratio, cagr, max_drawdown

DATA = Path(__file__).with_name("data")
SPECS = {"MES": (0.25, 5.0), "MNQ": (0.25, 2.0)}
RTH = ("09:30", "15:59")


def build(sym, start):
    df = pd.read_parquet(DATA / f"{sym}_5min_databento.parquet")
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df = df[df.index >= pd.Timestamp(start).tz_localize(df.index.tz)]
    rth = df.between_time(*RTH)
    day = rth.index.normalize()
    idx = pd.Series(rth.index, index=rth.index)
    d = pd.DataFrame({
        "first_ts": idx.groupby(day).first(), "last_ts": idx.groupby(day).last(),
        "open": rth["open"].groupby(day).first(), "high": rth["high"].groupby(day).max(),
        "low": rth["low"].groupby(day).min(), "close": rth["close"].groupby(day).last(),
    }).dropna()
    # features known at the close (entry)
    d["green"] = d["close"] > d["open"]
    rng = (d["high"] - d["low"])
    d["loc"] = (d["close"] - d["low"]) / rng.replace(0, np.nan)
    d["range"] = rng / d["open"]
    d["above_sma"] = d["close"] > d["close"].rolling(20).mean()
    d["wild80"] = d["range"] > d["range"].rolling(60, min_periods=20).quantile(0.80)
    d["wild90"] = d["range"] > d["range"].rolling(60, min_periods=20).quantile(0.90)
    return df, d


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


# night filters: given the just-closed day's row, return True to TRADE
FILTERS = {
    "all": lambda r: True,
    "skip wild80": lambda r: not bool(r["wild80"]),
    "skip wild90": lambda r: not bool(r["wild90"]),
    "strong only": lambda r: (not bool(r["green"])) or (r["loc"] < 0.5) or (not bool(r["above_sma"])),
    "skip weak": lambda r: not (bool(r["green"]) and r["loc"] > 0.5),
}


def run(sym, ticks, start, use_stop, filt):
    tick, dpp = SPECS[sym]
    df, d = build(sym, start)
    days = d.index
    fn = FILTERS[filt]
    rows = []
    for i in range(1, len(days)):
        D, Dn = days[i - 1], days[i]
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
    return t, dpp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="MES,MNQ")
    ap.add_argument("--ticks", type=float, default=1.0)
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--balance", type=float, default=100_000)
    args = ap.parse_args()

    configs = [
        ("TP=PDH", False, "all"),
        ("TP=PDH | skip wild80", False, "skip wild80"),
        ("TP=PDH | strong only", False, "strong only"),
        ("TP+PDLstop", True, "all"),
        ("TP+PDLstop | skip wild80", True, "skip wild80"),
        ("TP+PDLstop | skip wild90", True, "skip wild90"),
        ("TP+PDLstop | strong only", True, "strong only"),
        ("TP+PDLstop | skip weak", True, "skip weak"),
    ]
    for sym in [s.strip().upper() for s in args.symbols.split(",")]:
        print("=" * 84)
        print(f"{sym}  |  2020->now  |  cost {args.ticks} tick  |  tail-controlled overnight")
        hdr = (f"{'config':<28}{'Sharpe':>8}{'CAGR':>8}{'MaxDD':>8}{'%trade':>7}"
               f"{'$worst':>9}{'<-500':>7}")
        print(hdr); print("-" * len(hdr))
        for name, stop, filt in configs:
            t, dpp = run(sym, args.ticks, args.start, stop, filt)
            r = t["ret"].clip(-0.2, 0.2)
            nav = (args.balance * (1 + r).cumprod()).tolist()
            depth, _ = max_drawdown(nav)
            usd = t["usd"].dropna()
            pct_trade = t["traded"].mean() * 100
            print(f"{name:<28}{sharpe_ratio(nav):>8.2f}{cagr(nav)*100:>7.1f}%"
                  f"{abs(depth)*100:>7.1f}%{pct_trade:>6.0f}%"
                  f"{usd.min():>9.0f}{(usd<-500).mean()*100:>6.1f}%")
        print()


if __name__ == "__main__":
    main()
