"""Asia-session opening-range breakout on MNQ -- Globex and Tokyo tested as two
SEPARATE studies, each with its own session boundary, control, null and stress.

They are not the same session and pooling them was hiding that:

    Globex   open 18:00 ET (the CME reopen), flat 02:55 -- the last bar before
             the London open at 03:00. A ~9 hour session.
    Tokyo    open 20:00 ET (09:00 JST), flat 01:55 -- Tokyo cash closes at
             15:00 JST = 02:00 ET. A ~6 hour session.

Each gets its own 18-cell grid (3 range lengths x 3 exits x 2 filters), its own
best-of-18 sign-flip permutation null, its own stress panel, and its own
speed-limit verdict computed on its own turnover.

THE CONFOUND, and the control for it. This workspace has already established
that MNQ carries real positive drift in the 18:00-06:00 Globex block. An opening
-range breakout anchored inside that block is trading in a window that pays you
for simply being long. A long-biased breakout rule will therefore look
profitable even if the breakout signal carries no information whatsoever.

So each anchor's cells are scored against a PASSIVE LONG of that anchor's exact
window, vol-scaled to the same risk target. Beating zero is not the bar; beating
the drift is. The long/short P&L split is reported for the same reason -- profit
that lives entirely on the long side in a session with known long drift has
demonstrated nothing.

COSTS. Asia bars carry ~8.8% of RTH volume (881 vs 10,705 contracts per 5-min
bar), so the spread is wider more often. Default charge is 3 ticks round trip
against RTH's 2; the stress panel sweeps to 12.

    .venv\\Scripts\\python.exe orb_asia_carver_backtest.py
    .venv\\Scripts\\python.exe orb_asia_carver_backtest.py --ticks 4 --draws 2000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "overnight"))
from overnight_drift_carver_backtest import (
    ANNUALISE, INSTRUMENTS, REPORTS, SPEED_LIMIT_PRECOST_SR, TAU,
    carver_vol, cost_per_side, daily_closes, load_5m, session_key, stats,
)

# Each session stands on its own clock. Cutoff leaves the trade room to work.
SESSIONS = {
    "GLOBEX": dict(anchor="18:00", flat="02:55", cutoff="01:00",
                   note="CME reopen 18:00 ET -> last bar before the London open"),
    "TOKYO": dict(anchor="20:00", flat="01:55", cutoff="00:00",
                  note="Tokyo cash 09:00-15:00 JST = 20:00-02:00 ET"),
}
OR_MINUTES = (5, 10, 15, 20, 30, 45, 60, 90, 120)
EXITS = ("close", "or_stop", "or_stop_2r")
FILTERS = ("both", "trend")


# ------------------------------------------------------------------ data ------
def window_liquid_start(d, anchor, flat, min_bars=50, min_volume=12_000, run=21):
    """First session after which this window NEVER drops back below tradeable."""
    w = d.between_time(anchor, flat)
    g = w.groupby(session_key(w.index))
    bars, vol = g.size(), g["volume"].sum()
    ok = ((bars.rolling(run, min_periods=run).median() >= min_bars) &
          (vol.rolling(run, min_periods=run).median() >= min_volume))
    failing = ok[~ok]
    if failing.empty:
        return bars.index[0]
    after = ok[ok.index > failing.index[-1]]
    return after.index[0] if len(after) else bars.index[-1]


# ------------------------------------------------------------------ ORB -------
def orb_trades(d, vol, mac, dpp, cfg, or_min, exit_style, filt, capital,
               side_cost, tau=TAU):
    """ORB over a window that crosses midnight. Signal on a close, fill next open.

    pandas between_time wraps past midnight, and the CME session key assigns the
    18:00 bar on date D to session D+1, so one session's window is a single
    contiguous slice and the roll seam never falls inside it.
    """
    anchor, flat, cutoff = cfg["anchor"], cfg["flat"], cfg["cutoff"]
    or_end = (pd.Timestamp("2000-01-01 " + anchor) +
              pd.Timedelta(minutes=or_min)).strftime("%H:%M")
    win = d.between_time(anchor, flat)
    out = []
    for date, s in win.groupby(session_key(win.index)):
        s = s.sort_index()
        sd, sig = vol.get(date, np.nan), mac.get(date, np.nan)
        if not np.isfinite(sd) or sd <= 0:
            continue
        opening = s.between_time(anchor, or_end, inclusive="left")
        if len(opening) < max(1, or_min // 5):
            continue
        hi, lo = opening["high"].max(), opening["low"].min()
        if not np.isfinite(hi) or not np.isfinite(lo) or hi <= lo:
            continue
        rest = s[s.index > opening.index[-1]]
        if rest.empty:
            continue
        allow_long = allow_short = True
        if filt == "trend":
            if not np.isfinite(sig) or sig == 0:
                continue
            allow_long, allow_short = sig > 0, sig < 0

        hit = None
        for ts, b in rest.between_time(anchor, cutoff).iterrows():
            if b["close"] > hi and allow_long:
                hit = (ts, 1)
                break
            if b["close"] < lo and allow_short:
                hit = (ts, -1)
                break
        if hit is None:
            continue
        sig_ts, side = hit
        nxt = rest[rest.index > sig_ts]
        if nxt.empty:
            continue
        entry = float(nxt.iloc[0]["open"])
        stop = lo if side > 0 else hi
        risk = abs(entry - stop)
        target = entry + side * 2.0 * risk
        exit_px, why = float(nxt.iloc[-1]["close"]), "close"
        if exit_style != "close" and risk > 0:
            for ts, b in nxt.iterrows():
                stopped = (b["low"] <= stop) if side > 0 else (b["high"] >= stop)
                tgt = (b["high"] >= target) if side > 0 else (b["low"] <= target)
                if stopped:                       # stop wins ties: conservative
                    o = float(b["open"])          # gap-aware: a stop is a market
                    exit_px = min(stop, o) if side > 0 else max(stop, o)
                    why = "stop" if exit_px == stop else "stop_gap"
                    break
                if tgt and exit_style == "or_stop_2r":
                    exit_px, why = target, "target"
                    break
        out.append({"date": date, "side": side, "entry": entry, "exit": exit_px,
                    "why": why, "or_width": hi - lo, "ann_vol": sd,
                    "pts": side * (exit_px - entry)})
    tr = pd.DataFrame(out)
    if tr.empty:
        return tr
    tr["contracts"] = (capital * tau / (tr.ann_vol * tr.entry * dpp)).round()
    tr = tr[tr.contracts > 0].copy()
    tr["gross_$"] = tr.pts * dpp * tr.contracts
    tr["cost_$"] = 2.0 * side_cost * tr.contracts
    tr["net_$"] = tr["gross_$"] - tr["cost_$"]
    return tr


def passive_long(d, vol, dpp, cfg, capital, side_cost, tau=TAU):
    """Hold this exact window long, vol-scaled. The control that matters.

    First open -> last close INSIDE the window, so no roll seam is ever held.
    """
    win = d.between_time(cfg["anchor"], cfg["flat"])
    g = win.groupby(session_key(win.index))
    df = pd.DataFrame({"entry": g["open"].first(), "exit": g["close"].last(),
                       "bars": g.size()})
    df = df[df.bars >= 12]
    df["ann_vol"] = vol.reindex(df.index)
    df = df.dropna(subset=["ann_vol"])
    df = df[df.ann_vol > 0]
    df["contracts"] = (capital * tau / (df.ann_vol * df.entry * dpp)).round()
    df = df[df.contracts > 0].copy()
    df["gross_$"] = (df.exit - df.entry) * dpp * df.contracts
    df["cost_$"] = 2.0 * side_cost * df.contracts
    df["net_$"] = df["gross_$"] - df["cost_$"]
    df.index.name = "date"
    return df.reset_index()


def to_returns(tr, index, capital, col="net_$"):
    if tr is None or tr.empty:
        return pd.Series(0.0, index=index)
    return (tr.groupby("date")[col].sum() / capital).reindex(index).fillna(0.0)


def sr_of(tr, idx, capital, dpp, tick, commission_rt, ticks_rt):
    if tr is None or tr.empty:
        return np.nan
    net = tr["gross_$"] - tr.contracts * (commission_rt + ticks_rt * tick * dpp)
    r = (net.groupby(tr.date).sum() / capital).reindex(idx).fillna(0.0)
    return (r.mean() * 252) / (r.std() * ANNUALISE) if r.std() else np.nan


def permutation_max_sr(panel, draws, seed):
    """Best-of-N null: flip whole sessions, identically across every cell, so the
    cells' correlation -- the real difficulty of the search -- is preserved."""
    rng = np.random.default_rng(seed)
    x = panel.values
    sd0 = x.std(0)
    obs = np.nanmax(np.where(sd0 > 0, x.mean(0) * 252 / (sd0 * ANNUALISE), np.nan))
    null = np.empty(draws)
    for k in range(draws):
        y = x * rng.choice([-1.0, 1.0], size=len(x))[:, None]
        sd = y.std(0)
        null[k] = np.nanmax(np.where(sd > 0, y.mean(0) * 252 / (sd * ANNUALISE), np.nan))
    return obs, null


# ------------------------------------------------------------------- run ------
def run_session(name, cfg, d_all, dpp, tick, args, side_cost, limit):
    """One complete, self-contained study for one session."""
    print("\n" + "=" * 100)
    print("%s   %s -> %s ET   (%s)" % (name, cfg["anchor"], cfg["flat"], cfg["note"]))
    print("=" * 100)

    start = window_liquid_start(d_all, cfg["anchor"], cfg["flat"])
    d = d_all[d_all.index >= start]
    closes = daily_closes(d)
    vol = carver_vol(closes)
    mac = np.sign(closes.rolling(16).mean() - closes.rolling(64).mean()).shift(1)
    idx = closes.loc[vol.dropna().index[0]:].index
    yrs = len(idx) / 252.0

    w = d.between_time(cfg["anchor"], cfg["flat"])
    gw = w.groupby(session_key(w.index))
    print("  [data] %s -> %s   %d sessions (%.1f yr)   median %d bars, "
          "%s contracts/session"
          % (start.date(), d.index[-1].date(), len(idx), yrs,
             gw.size().median(), format(gw["volume"].sum().median(), ",.0f")))

    pl = passive_long(d, vol, dpp, cfg, args.capital, side_cost)
    pr = to_returns(pl, idx, args.capital)
    pst = stats(pr)
    print("  [control] PASSIVE LONG this window: SR_net %+.2f, ann_vol %.1f%%, "
          "maxDD %.1f%%, net $%s"
          % (pst["SR_net"], pst["ann_vol"] * 100, pst["maxDD"] * 100,
             format(pl["net_$"].sum(), ",.0f")))
    print("            That is the bar. Beating zero here means nothing.")

    rows, panel, store = [], {}, {}
    for om in OR_MINUTES:
        for ex in EXITS:
            for fl in FILTERS:
                tr = orb_trades(d, vol, mac, dpp, cfg, om, ex, fl,
                                args.capital, side_cost)
                key = "OR%02d|%-10s|%s" % (om, ex, fl)
                r = to_returns(tr, idx, args.capital)
                g = to_returns(tr, idx, args.capital, "gross_$")
                panel[key], store[key] = r, tr
                srn = (r.mean() * 252) / (r.std() * ANNUALISE) if r.std() else np.nan
                srg = (g.mean() * 252) / (g.std() * ANNUALISE) if g.std() else np.nan
                n = len(tr)
                st = stats(r)
                rows.append({"cell": key, "trades": n, "trades_yr": 2 * n / yrs,
                             "SR_gross": srg, "cost_SR": srg - srn, "SR_net": srn,
                             "vs_passive": srn - pst["SR_net"],
                             "ann_vol": st["ann_vol"], "maxDD": st["maxDD"],
                             "skew": st["skew"],
                             "long_$": tr[tr.side > 0]["net_$"].sum() if n else 0.0,
                             "short_$": tr[tr.side < 0]["net_$"].sum() if n else 0.0,
                             "net_$": tr["net_$"].sum() if n else 0.0})
    G = pd.DataFrame(rows).set_index("cell").sort_values("SR_net", ascending=False)
    print("\n  [grid] all %d cells; vs_passive is the column that decides" % len(G))
    print(G.to_string(formatters={
        "trades_yr": "{:,.0f}".format, "SR_gross": "{:+.2f}".format,
        "cost_SR": "{:.3f}".format, "SR_net": "{:+.2f}".format,
        "vs_passive": "{:+.2f}".format, "ann_vol": "{:.1%}".format,
        "maxDD": "{:.1%}".format, "skew": "{:+.2f}".format,
        "long_$": "{:,.0f}".format, "short_$": "{:,.0f}".format,
        "net_$": "{:,.0f}".format}))

    best = G.index[0]
    bt = store[best]
    obs, null = permutation_max_sr(pd.DataFrame(panel), args.draws, args.seed)
    p = float((null >= obs).mean())
    beat = int((G.vs_passive > 0).sum())
    print("\n  [verdict] best %s  SR_net %+.3f  (passive %+.3f)"
          % (best, G.SR_net.iloc[0], pst["SR_net"]))
    print("            beats passive long: %d/%d cells" % (beat, len(G)))
    print("            best-of-%d null: median %+.3f, 95th %+.3f -> p = %.3f  %s"
          % (len(G), np.median(null), np.percentile(null, 95), p,
             "(search noise)" if p > 0.05 else "(survives)"))
    print("            speed limit: %d/%d cells breach (limit %.3f)"
          % (int((G.cost_SR > limit).sum()), len(G), limit))
    lg, sh = bt[bt.side > 0]["net_$"].sum(), bt[bt.side < 0]["net_$"].sum()
    print("            long/short:  $%s long (%d) / $%s short (%d)"
          % (format(lg, ",.0f"), int((bt.side > 0).sum()),
             format(sh, ",.0f"), int((bt.side < 0).sum())))

    print("\n  [stress] %s" % best)
    sweep = [sr_of(bt, idx, args.capital, dpp, tick, args.commission, t)
             for t in (1, 2, 3, 4, 6, 8, 12)]
    print("    cost sweep ticks RT  1:%+.2f 2:%+.2f 3:%+.2f 4:%+.2f 6:%+.2f "
          "8:%+.2f 12:%+.2f" % tuple(sweep))
    half = idx[len(idx) // 2]
    print("    split sample         1st %+.2f / 2nd %+.2f"
          % (sr_of(bt[bt.date < half], idx[idx < half], args.capital, dpp, tick,
                   args.commission, args.ticks),
             sr_of(bt[bt.date >= half], idx[idx >= half], args.capital, dpp, tick,
                   args.commission, args.ticks)))
    cov = (bt.date >= "2020-02-15") & (bt.date <= "2020-04-30")
    keep = idx[(idx < "2020-02-15") | (idx > "2020-04-30")]
    print("    ex-COVID             %+.2f"
          % sr_of(bt[~cov], keep, args.capital, dpp, tick, args.commission,
                  args.ticks))
    daily = bt.groupby("date")["net_$"].sum().sort_values(ascending=False)
    for k in (5, 20):
        drop = daily.index[:k]
        print("    drop best %2d nights  %+.2f   [%.0f%% of P&L]"
              % (k, sr_of(bt[~bt.date.isin(drop)], idx.difference(drop),
                          args.capital, dpp, tick, args.commission, args.ticks),
                 100 * daily.iloc[:k].sum() / daily.sum() if daily.sum() else np.nan))

    piv = G.reset_index()
    piv["or_min"] = piv.cell.str.extract(r"OR(\d+)").astype(int)
    piv["variant"] = piv.cell.str.split("|").str[1:].str.join("|").str.replace(
        r"\s+", "", regex=True)
    m = piv.pivot(index="or_min", columns="variant", values="SR_net")
    print("\n  [matrix] net Sharpe by opening-range length (rows) x exit|filter")
    print("           passive long this window = %+.2f -- every cell must beat it"
          % pst["SR_net"])
    print(m.to_string(float_format=lambda v: "%+.2f" % v))
    per_or = piv.groupby("or_min").agg(
        best_SR=("SR_net", "max"), worst_SR=("SR_net", "min"),
        median_SR=("SR_net", "median"), trades_yr=("trades_yr", "median"),
        cost_SR=("cost_SR", "median"))
    per_or["vs_passive"] = per_or.best_SR - pst["SR_net"]
    per_or["beats_passive"] = piv.groupby("or_min").vs_passive.apply(
        lambda s: int((s > 0).sum()))
    print("\n  [by range length] best/median/worst across the 6 exit|filter "
          "variants at each length")
    print(per_or.to_string(formatters={
        "best_SR": "{:+.2f}".format, "worst_SR": "{:+.2f}".format,
        "median_SR": "{:+.2f}".format, "trades_yr": "{:,.0f}".format,
        "cost_SR": "{:.3f}".format, "vs_passive": "{:+.2f}".format}))
    m.to_csv(REPORTS / ("orb_asia_matrix_%s.csv" % name))
    per_or.to_csv(REPORTS / ("orb_asia_by_range_%s.csv" % name))
    G.to_csv(REPORTS / ("orb_asia_grid_%s.csv" % name))
    pd.DataFrame(panel).to_csv(REPORTS / ("orb_asia_returns_%s.csv" % name))
    return {"session": name, "sessions": len(idx), "years": yrs,
            "passive_SR": pst["SR_net"], "best_cell": best,
            "best_SR": G.SR_net.iloc[0], "vs_passive": G.vs_passive.iloc[0],
            "p_best": p, "cells_beating_passive": beat,
            "cells_breaching": int((G.cost_SR > limit).sum()),
            "long_$": lg, "short_$": sh}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=100_000)
    ap.add_argument("--commission", type=float, default=1.24)
    ap.add_argument("--ticks", type=float, default=3.0,
                    help="round-trip slippage+spread, ticks (Asia is thinner "
                         "than RTH so the default is 3, not 2)")
    ap.add_argument("--draws", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--end", default="2026-08-08")
    ap.add_argument("--only", default=None,
                    help="run just one session, e.g. GLOBEX")
    ap.add_argument("--or-minutes", default=None,
                    help="comma-separated opening-range lengths to sweep")
    args = ap.parse_args()
    global OR_MINUTES
    if args.or_minutes:
        OR_MINUTES = tuple(int(x) for x in args.or_minutes.split(","))

    REPORTS.mkdir(exist_ok=True)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 40)
    limit = SPEED_LIMIT_PRECOST_SR / 3.0
    fname, dpp, tick, _ = INSTRUMENTS["MNQ"]
    side_cost = cost_per_side(args.commission, args.ticks, tick, dpp)

    print("=" * 100)
    print("MNQ ASIA ORB  --  Globex and Tokyo as SEPARATE studies")
    print("=" * 100)
    print("cost/side $%.2f  ($%.2f comm + %g tk x $%.2f), round trip $%.2f"
          % (side_cost, args.commission, args.ticks, tick * dpp, 2 * side_cost))
    print("speed limit %.3f SR/yr; every verdict below uses MEASURED drag." % limit)

    d_all = load_5m(fname, args.end)
    todo = {k: v for k, v in SESSIONS.items()
            if args.only is None or k == args.only.upper()}
    out = [run_session(n, c, d_all, dpp, tick, args, side_cost, limit)
           for n, c in todo.items()]

    S = pd.DataFrame(out).set_index("session")
    print("\n" + "=" * 100)
    print("SIDE BY SIDE")
    print("=" * 100)
    print(S.to_string(formatters={
        "years": "{:.1f}".format, "passive_SR": "{:+.2f}".format,
        "best_SR": "{:+.2f}".format, "vs_passive": "{:+.2f}".format,
        "p_best": "{:.3f}".format, "long_$": "{:,.0f}".format,
        "short_$": "{:,.0f}".format}))
    S.to_csv(REPORTS / "orb_asia_side_by_side.csv")
    print("\nwritten -> reports/orb_asia_grid_<SESSION>.csv, "
          "orb_asia_returns_<SESSION>.csv, orb_asia_side_by_side.csv")


if __name__ == "__main__":
    main()
