"""Overnight long with level-based exits on real CME futures (Databento 5-min).

Enter long at the RTH close; during the Globex overnight, exit on the FIRST of:
  - take-profit at a level above entry: PDH (prior-day RTH high) or PWH (prior-
    week high);
  - stop at a level below entry: PDL (prior-day low) or PWL (prior-week low);
  - fallback: the next RTH open (the original overnight exit).

Walks the actual 5-min overnight path to detect touches. If one bar tags both a
TP and a stop (outside bar), the stop is assumed first (conservative). Levels on
the wrong side of entry are ignored (can't TP below you / stop above you).

Reports Sharpe/CAGR/DD/hit and the per-contract dollar tail, including the
worst night and the share of nights beyond -$500.

    python overnight_bracket_backtest.py --symbols MES,MNQ --ticks 1 --start 2020-01-01
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from pwb_toolbox.performance.metrics import sharpe_ratio, cagr, max_drawdown

DATA = Path(__file__).with_name("data")
SPECS = {"MES": (0.25, 5.0), "MNQ": (0.25, 2.0)}
RTH = ("09:30", "15:59")


def load(sym):
    df = pd.read_parquet(DATA / f"{sym}_5min_databento.parquet")
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def build(sym, start):
    df = load(sym)
    df = df[df.index >= pd.Timestamp(start).tz_localize(df.index.tz)]
    rth = df.between_time(*RTH)
    day = rth.index.normalize()
    idx = pd.Series(rth.index, index=rth.index)
    daily = pd.DataFrame({
        "first_ts": idx.groupby(day).first(),
        "last_ts": idx.groupby(day).last(),
        "open": rth["open"].groupby(day).first(),
        "high": rth["high"].groupby(day).max(),
        "low": rth["low"].groupby(day).min(),
        "close": rth["close"].groupby(day).last(),
    }).dropna()
    # prior completed calendar-week high/low, mapped to each day (no look-ahead)
    wk = daily.index.to_period("W")
    wkH = daily["high"].groupby(wk).max().shift(1)
    wkL = daily["low"].groupby(wk).min().shift(1)
    daily["pwh"] = pd.Series(wk, index=daily.index).map(wkH)
    daily["pwl"] = pd.Series(wk, index=daily.index).map(wkL)
    return df, daily


def sim_night(entry, ov, exit_open, tp, stop):
    """Return exit PRICE. tp above / stop below entry, or None to disable."""
    tp = tp if (tp is not None and tp > entry) else None
    stop = stop if (stop is not None and stop < entry) else None
    if tp is not None or stop is not None:
        for hi, lo in zip(ov["high"].to_numpy(), ov["low"].to_numpy()):
            hit_stop = stop is not None and lo <= stop
            hit_tp = tp is not None and hi >= tp
            if hit_stop:           # conservative: adverse first on ambiguous bars
                return stop
            if hit_tp:
                return tp
    return exit_open


def run(sym, ticks, start):
    tick, dpp = SPECS[sym]
    df, daily = build(sym, start)
    days = daily.index
    cost_pts = ticks * tick
    configs = ["open (baseline)", "TP=PDH", "TP=PWH", "stop=PDL", "stop=PWL",
               "bracket PDH/PDL", "bracket PWH/PWL"]
    pts = {c: [] for c in configs}
    for i in range(1, len(days)):
        D, Dn = days[i - 1], days[i]
        row = daily.loc[D]
        entry = row["close"]
        ov = df.loc[row["last_ts"]:daily.loc[Dn, "first_ts"]].iloc[1:-1]
        if len(ov) == 0:
            continue
        eo = daily.loc[Dn, "open"]
        pdh, pdl, pwh, pwl = row["high"], row["low"], row["pwh"], row["pwl"]
        outs = {
            "open (baseline)": sim_night(entry, ov, eo, None, None),
            "TP=PDH": sim_night(entry, ov, eo, pdh, None),
            "TP=PWH": sim_night(entry, ov, eo, pwh, None),
            "stop=PDL": sim_night(entry, ov, eo, None, pdl),
            "stop=PWL": sim_night(entry, ov, eo, None, pwl),
            "bracket PDH/PDL": sim_night(entry, ov, eo, pdh, pdl),
            "bracket PWH/PWL": sim_night(entry, ov, eo, pwh, pwl),
        }
        for c, ex in outs.items():
            pts[c].append((D, (ex - entry) - cost_pts, entry))
    return {c: pd.DataFrame(v, columns=["d", "pts", "entry"]).set_index("d")
            for c, v in pts.items()}, tick, dpp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="MES,MNQ")
    ap.add_argument("--ticks", type=float, default=1.0)
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--balance", type=float, default=100_000)
    args = ap.parse_args()

    for sym in [s.strip().upper() for s in args.symbols.split(",")]:
        res, tick, dpp = run(sym, args.ticks, args.start)
        n = len(res["open (baseline)"])
        print("=" * 78)
        print(f"{sym}  |  {n} nights  |  {args.start}->now  |  cost {args.ticks} tick  |  $/pt={dpp}")
        hdr = (f"{'exit rule':<20}{'Sharpe':>8}{'CAGR':>8}{'MaxDD':>8}{'hit%':>6}"
               f"{'$mean':>8}{'$worst':>9}{'<-500':>7}")
        print(hdr); print("-" * len(hdr))
        for c, d in res.items():
            r = (d["pts"] / d["entry"]).clip(-0.2, 0.2)      # ret; clip pathological
            nav = (args.balance * (1 + r).cumprod()).tolist()
            depth, _ = max_drawdown(nav)
            usd = d["pts"] * dpp
            print(f"{c:<20}{sharpe_ratio(nav):>8.2f}{cagr(nav)*100:>7.1f}%"
                  f"{abs(depth)*100:>7.1f}%{(d['pts']>0).mean()*100:>6.0f}"
                  f"{usd.mean():>8.0f}{usd.min():>9.0f}"
                  f"{(usd<-500).mean()*100:>6.1f}%")
        print()


if __name__ == "__main__":
    main()
