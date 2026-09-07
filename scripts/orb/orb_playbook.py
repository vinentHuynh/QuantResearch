"""Data behind the "how to trade it" page: real annotated MNQ sessions.

Every example is an actual trade the backtest took, pulled straight out of
orb_trades() with its own opening range, entry, stop, target and exit -- not a
drawn illustration. If a chart on the playbook page shows a fill, the backtest
took that fill at that price on that date.

The three sessions are chosen to be TYPICAL of their outcome, not dramatic:
each sits near the median P&L for its exit type, so the page teaches the
ordinary case rather than a highlight reel. That matters for this strategy in
particular -- it loses on 54% of trades, and a page that only showed winners
would misrepresent what trading it actually feels like.
"""
from __future__ import annotations

import functools

import numpy as np
import pandas as pd

from overnight_drift_carver_backtest import (
    INSTRUMENTS, TAU, carver_vol, cost_per_side, daily_closes, load_5m,
)
from orb_carver_backtest import RTH_LAST, RTH_OPEN, orb_trades, rth_liquid_start

# (session date, group, what it teaches). Each sits near the median P&L for its
# exit type, so the page teaches the ordinary case rather than a highlight reel.
EXAMPLES = [
    ("2025-09-22", "long", "The 2R day the whole strategy is paid for"),
    ("2026-03-17", "long", "The ordinary loss — 43% of trades end here"),
    ("2026-02-25", "long", "No resolution: flat at 16:00 for a small gain"),
    ("2025-12-17", "short", "Shorts are the mirror image, not an afterthought — "
                            "a clean break below the range that ran to 2R"),
    ("2026-04-16", "short", "A short that broke down, reversed, and paid the "
                            "range high"),
    ("2025-11-03", "short", "Short, no follow-through, flat at 16:00"),
    ("2025-10-29", "chop", "The whipsaw archetype: a tight 38-point range on a "
                           "day that crossed it 16 times"),
    ("2025-05-14", "chop", "A short caught the same way — chop is indifferent to "
                           "which side you took"),
]

GROUPS = {
    "long": ("The three ways a long ends",
             "Break above the range. Whatever happens next, one of these three "
             "outcomes closes the trade."),
    "short": ("The same rules, downside",
              "There is no directional opinion in this system. A close below the "
              "range low is a short, the stop goes at the range HIGH, and the 2R "
              "target sits below. Shorts are 48% of all trades."),
    "chop": ("When the range does not hold",
             "These are the days that hurt. Price breaks out, drags you in, then "
             "falls back through the range and takes the stop. You cannot avoid "
             "them — see the table below for why."),
}

CAPITAL, COMMISSION_RT, TICKS_RT = 100_000.0, 1.24, 2.0


@functools.lru_cache(maxsize=1)
def _load():
    fname, dpp, tick, _ = INSTRUMENTS["MNQ"]
    d = load_5m(fname, "2026-08-08")
    d = d[d.index >= rth_liquid_start(d)]
    closes = daily_closes(d)
    vol = carver_vol(closes)
    mac = np.sign(closes.rolling(16).mean() - closes.rolling(64).mean()).shift(1)
    side_cost = cost_per_side(COMMISSION_RT, TICKS_RT, tick, dpp)
    tr = orb_trades(d, vol, mac, dpp, 15, "or_stop_2r", "both", CAPITAL, side_cost)
    return d, tr, dpp, tick, side_cost


@functools.lru_cache(maxsize=1)
def _crossings():
    """How many times each session's close flipped in or out of its own range.

    This is the honest measure of "chop" for a breakout system: not how far
    price travelled, but how many times it changed its mind about the level you
    are trading. Unlike a path/net ratio it cannot blow up when the net move is
    near zero.
    """
    d, tr, _, _, _ = _load()
    rth = d.between_time(RTH_OPEN, RTH_LAST).copy()
    rth["day"] = rth.index.normalize()
    lv = tr.assign(day=tr.date.dt.normalize()).set_index("day")[["or_hi", "or_lo"]]
    j = rth.join(lv, on="day").dropna(subset=["or_hi"])
    side = np.sign((j.close > j.or_hi).astype(int) - (j.close < j.or_lo).astype(int))
    return side.groupby(j["day"]).apply(lambda s: int(s.diff().abs().gt(0).sum()))


def sessions(group=None):
    """[(bars, trade-dict)] for each teaching example, optionally one group."""
    d, tr, dpp, tick, side_cost = _load()
    cross = _crossings()
    out = []
    for date, grp, caption in EXAMPLES:
        if group and grp != group:
            continue
        key = pd.Timestamp(date).date()
        row = tr[tr.date.dt.date == key]
        if row.empty:
            continue
        t = row.iloc[0].to_dict()
        bars = d[d.index.normalize().date == key].between_time(RTH_OPEN, RTH_LAST)
        if bars.empty:
            continue
        t["dpp"], t["date_str"], t["caption"], t["group"] = dpp, str(key), caption, grp
        t["risk_pts"] = abs(t["entry"] - t["stop"])
        t["risk_$"] = t["risk_pts"] * dpp * t["contracts"]
        t["cross"] = int(cross.get(pd.Timestamp(key).tz_localize(
            bars.index.tz).normalize(), 0))
        out.append((bars, t))
    return out


def chop_table():
    """P&L by how many times the session crossed its own opening range.

    DESCRIPTIVE ONLY. The crossing count is not known until the session is over,
    so this is not a filter you can trade -- it is an explanation of where the
    money comes from and goes.
    """
    _, tr, _, _, _ = _load()
    t = tr.assign(cross=tr.date.dt.normalize().map(_crossings()))
    t["bucket"] = pd.cut(t.cross, [-1, 2, 5, 9, 10_000],
                         labels=["calm (0-2 crossings)", "normal (3-5)",
                                 "busy (6-9)", "chop (10+)"])
    g = t.groupby("bucket", observed=True)
    return pd.DataFrame({
        "% of days": g.size() / len(t) * 100,
        "win %": g["net_$"].apply(lambda s: (s > 0).mean() * 100),
        "hit 2R %": g["why"].apply(lambda s: (s == "target").mean() * 100),
        "stopped %": g["why"].apply(lambda s: (s == "stop").mean() * 100),
        "avg $": g["net_$"].mean(),
        "total $": g["net_$"].sum()})


def chop_predictability():
    """Can the range width you can SEE at 09:45 predict the chop that follows?"""
    _, tr, dpp, _, _ = _load()
    t = tr.assign(cross=tr.date.dt.normalize().map(_crossings()),
                  ORpct=tr.or_width / tr.entry * 100)
    q = pd.qcut(t.ORpct, 4, labels=["tightest 25%", "q2", "q3", "widest 25%"])
    g = t.groupby(q, observed=True)
    tab = pd.DataFrame({
        "median crossings": g.cross.median(),
        "win %": g["net_$"].apply(lambda s: (s > 0).mean() * 100),
        "avg $": g["net_$"].mean(),
        "total $": g["net_$"].sum()})
    return tab, t.ORpct.corr(t.cross)


def exit_mix():
    """Share of TRADES vs share of PROFIT by exit type.

    Both are percentages of their own total, so they share one axis -- the
    comparison is the entire point and a dual axis would fake it.
    """
    _, tr, _, _, _ = _load()
    n = len(tr)
    g = tr.groupby("why")["net_$"]
    pos = tr[tr["net_$"] > 0].groupby("why")["net_$"].sum()
    df = pd.DataFrame({
        "% of trades": g.size() / n * 100,
        "% of gross profit": pos.reindex(g.size().index).fillna(0.0) /
                             pos.sum() * 100,
    })
    order = [x for x in ("target", "close", "stop", "stop_gap") if x in df.index]
    return df.reindex(order)


def sizing_table():
    """How the vol-scaling turns one risk target into a lot count, by year."""
    _, tr, dpp, _, _ = _load()
    raw = CAPITAL * TAU / (tr.ann_vol * tr.entry * dpp)
    t = tr.assign(raw=raw, one=(tr.contracts == 1).astype(float))
    by = t.groupby(t.date.dt.year).agg(
        MNQ_price=("entry", "median"), ann_vol=("ann_vol", "median"),
        exact_lots=("raw", "median"), traded_lots=("contracts", "median"),
        pct_one_lot=("one", "mean"))
    by["pct_one_lot"] *= 100
    by["min_cap_4_lots"] = t.groupby(t.date.dt.year).apply(
        lambda x: 4 * (x.entry * dpp * x.ann_vol).median() / TAU)
    by.index.name = "year"
    return by


def headline():
    _, tr, _, _, _ = _load()
    net = tr["net_$"]
    w = net > 0
    return {"trades": len(tr), "win_rate": w.mean(),
            "avg_win": net[w].mean(), "avg_loss": net[~w].mean(),
            "payoff": -net[w].mean() / net[~w].mean(),
            "total": net.sum(),
            "median_or_pts": tr.or_width.median(),
            "median_risk": (tr.or_width * tr.dpp.iloc[0] * tr.contracts).median()
            if "dpp" in tr else np.nan}
