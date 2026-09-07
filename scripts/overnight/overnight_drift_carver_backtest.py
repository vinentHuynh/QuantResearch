"""Overnight drift (Globex 18:00->06:00 ET) vetted under Carver's *Leveraged
Trading* framework: cost in Sharpe units, vol-scaled sizing, skew-adjusted risk
target, and -- the part this workspace has never done -- a real multi-instrument
book with a measured IDM.

This workspace has already established the SIGNAL (see FINDINGS.md and the
mnq_* scripts): the equity premium is earned overnight, the edge localises to
the 18:00-06:00 block, and the hour-by-hour window scan is pure overfitting.
None of that is re-litigated and NO window is searched here. The two windows
tested are both inherited, pre-specified:

    18:00 -> 06:00   the block chosen by the earlier 6h grid
    23:00 -> 04:00   the thin-tail variant chosen by the prop-account work

What Carver adds that per-contract-dollar backtests cannot answer:

  1. COST IN SR UNITS, NOT TICKS. cost_SR = cost_ccy / (price x mult x sigma_ann).
     An overnight block trades ~504 times a year -- the same turnover that killed
     the MGC opening-range breakout. The interesting question is whether it is
     the FREQUENCY or the INSTRUMENT that kills a strategy, and only this unit
     answers it: a tick is a fixed number of dollars, but the risk it buys
     differs by an order of magnitude across MNQ, MES, MGC and MCL.
  2. IS BEING FLAT IN THE DAY SESSION WORTH 504 TRADES/YEAR? Holding the same
     instrument 24h costs ~4 roll trades a year instead of 504. The overnight
     block has to beat 24h buy-and-hold by MORE than the cost difference, or
     going flat every morning is an expensive superstition. This is the single
     most important comparison in the script.
  3. SKEW-ADJUSTED RISK TARGET. Carver halves tau for negative-skew payoffs.
     Holding a gap over a closed market is the textbook case, so the skew is
     measured and the haircut applied rather than assumed.
  4. IDM, MEASURED. Sizing four instruments to tau each gives a book well below
     tau. IDM = 1/sqrt(w'Cw), capped at 2.5, on handcrafted weights.
  5. MINIMUM CAPITAL. What account can actually hold this book at 4 contracts.

Mechanics that protect the result:
  * Block P&L runs first-open -> last-close INSIDE the block, so the Sunday
    reopen and every roll seam fall BETWEEN blocks and are never held. This is
    what stops a continuous series booking the roll gap as fake profit.
  * Vol is the Carver default (25-day stdev of daily returns x 16) lagged one
    session, so a night is never sized with its own outcome.
  * Sizing at 18:00 uses only closes through the prior 17:00 settlement.
  * Fixed capital, no compounding. Every headline is net of modelled costs.

    .venv\\Scripts\\python.exe overnight_drift_carver_backtest.py
    .venv\\Scripts\\python.exe overnight_drift_carver_backtest.py --capital 250000
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parents[2]
DATA = HERE / "data"
REPORTS = HERE / "reports"

ANNUALISE = 16.0                 # sqrt(256 business days)
VOL_WINDOW = 25                  # business days, Carver default
TAU = 0.12                       # Starter System risk target
SPEED_LIMIT_PRECOST_SR = 0.30    # single-instrument assumption; /3 = the limit
IDM_CAP = 2.5

# name -> (file, $/point, tick size, group). Micros only: the quantisation
# error on a full-size contract is what forces minimum capital through the roof.
INSTRUMENTS = {
    "MNQ": ("MNQ_5min_databento.parquet", 2.0, 0.25, "equity"),
    "MES": ("MES_5min_databento.parquet", 5.0, 0.25, "equity"),
    "MGC": ("MGC_5min_databento.parquet", 10.0, 0.10, "commodity"),
    "MCL": ("MCL_5min_databento.parquet", 100.0, 0.01, "commodity"),
}

# Pre-specified, inherited from prior work in this repo. Not searched here.
WINDOWS = {
    "ON 18-06": ("18:00", "05:55"),
    "ON 23-04": ("23:00", "03:55"),
}


# ------------------------------------------------------------------ data ------
def load_5m(fname, end):
    d = pd.read_parquet(DATA / fname).sort_index()
    d.index = d.index.tz_convert("US/Eastern")
    d = d[d.index < end]
    return d[["open", "high", "low", "close", "volume"]].astype(float)


def session_key(idx):
    """CME 18:00->17:00 clock. The 18:00 bar on date D belongs to session D+1."""
    return (idx + pd.Timedelta(hours=6)).normalize()


def liquid_start(d, min_bars=200, min_volume=2_000, run=21):
    """First session after which liquidity NEVER drops back below tradeable.

    The last *failing* window sets the boundary; taking the first passing one
    lets a single busy fortnight unlock years of unfillable history.
    """
    g = d.groupby(session_key(d.index))
    bars, vol = g.size(), g["volume"].sum()
    ok = ((bars.rolling(run, min_periods=run).median() >= min_bars) &
          (vol.rolling(run, min_periods=run).median() >= min_volume))
    failing = ok[~ok]
    if failing.empty:
        return bars.index[0]
    after = ok[ok.index > failing.index[-1]]
    return after.index[0] if len(after) else bars.index[-1]


def daily_closes(d):
    return d["close"].groupby(session_key(d.index)).last()


def carver_vol(closes, window=VOL_WINDOW):
    """Annualised vol, lagged one session so a night never sees its own return."""
    return closes.pct_change().rolling(window).std().mul(ANNUALISE).shift(1)


def seam_free_vol(d):
    """Same vol from within-session 5-min returns -- immune to roll-seam jumps.

    Agreement with the close-to-close estimate is the evidence that the .v.0
    continuous series is not fabricating variance where contracts change.
    """
    keys = session_key(d.index)
    r = d["close"].pct_change().mask(~pd.Series(keys, index=d.index).duplicated())
    n = r.groupby(keys).count()
    return r.groupby(keys).std().mul(np.sqrt(n)).mul(ANNUALISE)


# ----------------------------------------------------------------- costs ------
def cost_per_side(commission_rt, slip_ticks_rt, tick, dpp):
    """Dollars per contract per side. Both arguments are round-trip."""
    return (commission_rt + slip_ticks_rt * tick * dpp) / 2.0


def cost_table(closes, vol, dpp, side_cost, trades_per_year):
    """Risk-adjusted cost by year. Carver's screen, run before any signal."""
    df = pd.DataFrame({"px": closes, "vol": vol}).dropna()
    rows = []
    for yr, g in df.groupby(df.index.year):
        px, sd = g.px.median(), g.vol.median()
        ann_vol_ccy = px * dpp * sd
        c = side_cost / ann_vol_ccy
        rows.append({"year": yr, "median_px": px, "contract_$": px * dpp,
                     "ann_vol": sd, "ann_vol_$": ann_vol_ccy,
                     "cost_SR_trade": c, "annual_cost_SR": c * trades_per_year,
                     "min_cap_1ct": dpp * px * sd / TAU,
                     "min_cap_4ct": 4 * dpp * px * sd / TAU})
    return pd.DataFrame(rows).set_index("year")


# -------------------------------------------------------------- strategy ------
def block_trades(d, vol, dpp, start, end, capital, side_cost, tau=TAU):
    """Long the clock block, sized by vol, one round trip per session.

    P&L runs the block's FIRST OPEN to its LAST CLOSE. The Sunday reopen and
    every roll seam sit between blocks and are never held -- the single most
    important detail in an overnight backtest on a continuous series.
    """
    blk = d.between_time(start, end)                 # pandas wraps past midnight
    g = blk.groupby(session_key(blk.index))
    df = pd.DataFrame({"entry": g["open"].first(), "exit": g["close"].last(),
                       "bars": g.size()})
    df = df[df.bars >= 12]                           # a real block, not a holiday
    df["ann_vol"] = vol.reindex(df.index)
    df = df.dropna(subset=["ann_vol"])
    df = df[df.ann_vol > 0]
    df["contracts_raw"] = capital * tau / (df.ann_vol * df.entry * dpp)
    df["contracts"] = df.contracts_raw.round()
    skipped = int((df.contracts == 0).sum())         # too big for the account
    df = df[df.contracts > 0].copy()
    df.attrs["skipped_zero_lot"] = skipped
    df["pts"] = df.exit - df.entry
    df["gross_$"] = df.pts * dpp * df.contracts
    df["cost_$"] = 2.0 * side_cost * df.contracts
    df["net_$"] = df["gross_$"] - df["cost_$"]
    return df


def price_change(d, seam_free=True):
    """Per-session price change used for P&L on a held position.

    seam_free=True  : last close - first open INSIDE the session. Excludes the
                      17:00-18:00 halt gap AND the roll jump.
    seam_free=False : plain close-to-close. Includes both.

    This distinction is not cosmetic. Databento .v.0 continuous series are NOT
    price-adjusted, so at a roll the series steps by the calendar spread. In
    contango that step is POSITIVE and a close-to-close P&L books it as profit
    the trader never earned -- a real roll is executed as a spread trade and
    costs money. Measured over the liquid window: the seam is 29% of MGC's
    total close-to-close move and 119% of MCL's (MCL's within-session total is
    NEGATIVE), with MGC's outlier gaps signed +0.37 on average and clustered on
    the 1st-3rd of the month, which is the contango signature, not news.

    Seam-free is the conservative bound and matches how the block strategies are
    computed, so the comparison is like-for-like. It under-counts by the genuine
    one-hour halt gap, which is why both are reported.
    """
    if not seam_free:
        return daily_closes(d).diff()
    g = d.groupby(session_key(d.index))
    return g["close"].last() - g["open"].first()


def hold_24h(d, vol, dpp, capital, side_cost, tau=TAU, rolls_per_year=4.0,
             buffer_frac=0.10, seam_free=True):
    """Buffered 24h long. The honest alternative to going flat every morning.

    Trades only when the vol-implied size leaves a +/-10%-of-average band, so it
    pays a handful of trades a year plus rolls -- against the overnight block's
    ~504. If the block cannot beat this by more than the cost difference, being
    flat in the day session is an expensive superstition.
    """
    closes = daily_closes(d)
    v = vol.reindex(closes.index)
    target = (capital * tau / (v * closes * dpp))
    avg = target.mean()
    held, trades = [], 0
    cur = 0.0
    for t in target:
        if not np.isfinite(t):
            held.append(cur)
            continue
        lo, hi = t - buffer_frac * avg, t + buffer_frac * avg
        new = round(lo) if cur < lo else (round(hi) if cur > hi else cur)
        if new != cur:
            trades += abs(new - cur)
            cur = new
        held.append(cur)
    held = pd.Series(held, index=closes.index)
    dpx = price_change(d, seam_free).reindex(closes.index)
    # held_t is only known at close_t (the target uses close_t), so the position
    # earning session t's move is always held_{t-1}. Same shift either way.
    pnl = held.shift(1) * dpp * dpx
    pnl -= (held != held.shift(1)).astype(float) * side_cost * (held - held.shift(1)).abs()
    pnl -= held * 2 * side_cost * rolls_per_year / 252.0        # roll cost
    return (pnl / capital).fillna(0.0), trades, held.mean()


def starter_system(d, vol, dpp, capital, side_cost, stop_frac=0.5,
                   rolls_per_year=4.0, seam_free=True):
    """MAC(16,64), binary, size fixed at open, trailing stop 0.5 x price x vol.

    Carver's Starter System on the same instrument and cost model. The baseline
    every idea has to beat -- not zero.
    """
    closes = daily_closes(d)
    dpx = price_change(d, seam_free).reindex(closes.index)
    mac = np.sign(closes.rolling(16).mean() - closes.rolling(64).mean()).shift(1)
    pnl = pd.Series(0.0, index=closes.index)
    held = pd.Series(0.0, index=closes.index)
    pos, ct, stop, ext, n = 0, 0.0, np.nan, np.nan, 0
    for i, date in enumerate(closes.index):
        px, sd, sig = closes.iloc[i], vol.get(date, np.nan), mac.get(date, np.nan)
        if not np.isfinite(sd) or sd <= 0 or not np.isfinite(px):
            continue
        if pos != 0:
            # position was set on a previous session, so it earns this session's
            # move; seam-free that move excludes the roll jump.
            pnl.loc[date] += pos * ct * dpp * dpx.iloc[i]
            ext = max(ext, px) if pos > 0 else min(ext, px)
            gap = stop_frac * ext * sd
            stop = max(stop, ext - gap) if pos > 0 else min(stop, ext + gap)
            held.loc[date] = ct
            if (pos > 0 and px < stop) or (pos < 0 and px > stop):
                pnl.loc[date] -= side_cost * ct
                pos, ct = 0, 0.0
        if pos == 0 and np.isfinite(sig) and sig != 0:
            size = round(capital * TAU / (sd * px * dpp))
            if size >= 1:
                pos, ct, ext, n = int(sig), size, px, n + 1
                stop = px - sig * stop_frac * px * sd
                pnl.loc[date] -= side_cost * ct
                held.loc[date] = ct
    pnl -= held * 2 * side_cost * rolls_per_year / 252.0
    return pnl / capital, n


# --------------------------------------------------------------- stats --------
def to_returns(tr, index, capital, col="net_$"):
    if tr.empty:
        return pd.Series(0.0, index=index)
    return (tr[col] / capital).reindex(index).fillna(0.0)


def stats(rets, tr=None, capital=None, trades_per_year=None):
    yrs = len(rets) / 252.0
    mu, sd = rets.mean() * 252, rets.std() * ANNUALISE
    sr = mu / sd if sd > 0 else np.nan
    eq = (1 + rets).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    out = {"ann_ret": mu, "ann_vol": sd, "vol_vs_tau": sd / TAU, "SR_net": sr,
           "maxDD": dd, "DD_in_tau": abs(dd) / TAU, "skew": rets.skew(),
           "t_stat": sr * np.sqrt(yrs) if np.isfinite(sr) else np.nan,
           "worst_day": rets.min(), "years": yrs}
    if tr is not None and not tr.empty:
        gross = to_returns(tr, rets.index, capital, "gross_$")
        gsd = gross.std() * ANNUALISE
        out["SR_gross"] = (gross.mean() * 252) / gsd if gsd > 0 else np.nan
        out["cost_SR"] = out["SR_gross"] - sr
        out["trades_yr"] = 2 * len(tr) / yrs
        out["avg_ct"] = tr.contracts.mean()
        out["net_$"] = tr["net_$"].sum()
        out["win_rate"] = float((tr["net_$"] > 0).mean())
        out["no_lot"] = tr.attrs.get("skipped_zero_lot", 0)
    if trades_per_year is not None:
        out["trades_yr"] = trades_per_year
    return out


def fmt(df, pct=(), sr=(), num=()):
    f = {}
    for c in pct:
        f[c] = "{:.1%}".format
    for c in sr:
        f[c] = "{:+.2f}".format
    for c in num:
        f[c] = "{:,.1f}".format
    return df.to_string(formatters={k: v for k, v in f.items() if k in df.columns})


# ------------------------------------------------------------------ main ------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=100_000)
    ap.add_argument("--commission", type=float, default=1.24,
                    help="$/contract ROUND TURN")
    ap.add_argument("--ticks", type=float, default=1.0,
                    help="round-trip slippage in ticks")
    ap.add_argument("--end", default="2026-08-01", help="exclusive; drops partial tails")
    args = ap.parse_args()

    REPORTS.mkdir(exist_ok=True)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 40)
    print("=" * 100)
    print("OVERNIGHT DRIFT  --  Carver Leveraged Trading vetting")
    print("=" * 100)

    # -- 1. data -----------------------------------------------------------
    print("\n[1] DATA  (windows are pre-specified from prior work; nothing searched here)")
    book, meta = {}, []
    for name, (fname, dpp, tick, group) in INSTRUMENTS.items():
        d = load_5m(fname, args.end)
        start = liquid_start(d)
        d = d[d.index >= start]
        closes = daily_closes(d)
        vol = carver_vol(closes)
        seam = seam_free_vol(d).shift(1)
        cmp_ = pd.concat([vol.rename("c2c"), seam.rename("intra")], axis=1).dropna()
        sc = cost_per_side(args.commission, args.ticks, tick, dpp)
        book[name] = dict(d=d, closes=closes, vol=vol, dpp=dpp, tick=tick,
                          group=group, side_cost=sc)
        meta.append({"inst": name, "start": start.date(), "end": d.index[-1].date(),
                     "sessions": len(closes), "$/pt": dpp, "tick_$": tick * dpp,
                     "cost_side_$": sc, "vol_c2c": cmp_.c2c.median(),
                     "vol_seamfree": cmp_.intra.median(),
                     "ratio": cmp_.c2c.median() / cmp_.intra.median()})
    md = pd.DataFrame(meta).set_index("inst")
    print(fmt(md, pct=("vol_c2c", "vol_seamfree"), num=("cost_side_$", "ratio")))
    print("    vol_c2c vs vol_seamfree: close-to-close includes roll seams, "
          "seam-free does not.\n    Ratios near 1.0 mean the .v.0 continuous series "
          "is not fabricating variance at the roll.")

    # -- 2. COST FIRST -----------------------------------------------------
    limit = SPEED_LIMIT_PRECOST_SR / 3.0
    print("\n[2] COST SCREEN  (before any signal). Overnight = ~504 trades/yr.")
    print("    speed limit = pre-cost SR %.2f / 3 = %.3f SR/yr"
          % (SPEED_LIMIT_PRECOST_SR, limit))
    rows = []
    for name, b in book.items():
        t = cost_table(b["closes"], b["vol"], b["dpp"], b["side_cost"], 504)
        latest = t.iloc[-1]
        rows.append({"inst": name, "contract_$": latest["contract_$"],
                     "ann_vol": latest.ann_vol, "ann_vol_$": latest["ann_vol_$"],
                     "cost_SR_trade": latest.cost_SR_trade,
                     "cost@504": latest.annual_cost_SR,
                     "cost@24 (24h hold)": latest.cost_SR_trade * 24,
                     "verdict@504": "pass" if latest.annual_cost_SR <= limit else "BREACH",
                     "min_cap_1ct": latest.min_cap_1ct,
                     "min_cap_4ct": latest.min_cap_4ct})
        t.to_csv(REPORTS / ("overnight_cost_screen_%s.csv" % name))
    cs = pd.DataFrame(rows).set_index("inst")
    print(cs.to_string(formatters={
        "contract_$": "{:,.0f}".format, "ann_vol": "{:.1%}".format,
        "ann_vol_$": "{:,.0f}".format, "cost_SR_trade": "{:.6f}".format,
        "cost@504": "{:.3f}".format, "cost@24 (24h hold)": "{:.3f}".format,
        "min_cap_1ct": "{:,.0f}".format, "min_cap_4ct": "{:,.0f}".format}))
    print("    Same 504 trades/yr that killed the MGC opening-range breakout "
          "(0.34-0.61 SR/yr).\n    What changed is the instrument, not the "
          "frequency: a tick is a fixed number of\n    dollars, but the risk it "
          "buys differs ~10x across these four contracts.")

    # -- 3. single-instrument results --------------------------------------
    print("\n[3] SINGLE INSTRUMENT -- long the block, vol-scaled to tau=%.0f%%, net"
          % (TAU * 100))
    res, series, trades = [], {}, {}
    for name, b in book.items():
        for wname, (s, e) in WINDOWS.items():
            tr = block_trades(b["d"], b["vol"], b["dpp"], s, e,
                              args.capital, b["side_cost"])
            idx = b["closes"].loc[b["vol"].dropna().index[0]:].index
            r = to_returns(tr, idx, args.capital)
            key = "%s %s" % (name, wname)
            series[key], trades[key] = r, tr
            st = stats(r, tr, args.capital)
            st["strategy"] = key
            res.append(st)
        # The alternative to going flat every morning, and the Starter System.
        # Both hold across roll seams, so both are run seam-free (headline) and
        # close-to-close (the contaminated upper bound) -- see price_change().
        for sf, tag in ((True, ""), (False, " [c2c]")):
            r24, n24, avg24 = hold_24h(b["d"], b["vol"], b["dpp"], args.capital,
                                       b["side_cost"], seam_free=sf)
            key = "%s 24h hold%s" % (name, tag)
            series[key] = r24
            st = stats(r24, trades_per_year=n24 / (len(r24) / 252.0))
            st.update({"strategy": key, "avg_ct": avg24,
                       "net_$": (r24 * args.capital).sum()})
            res.append(st)
            rss, nss = starter_system(b["d"], b["vol"], b["dpp"], args.capital,
                                      b["side_cost"], seam_free=sf)
            key = "%s MAC(16,64)%s" % (name, tag)
            series[key] = rss
            st = stats(rss, trades_per_year=2 * nss / (len(rss) / 252.0))
            st.update({"strategy": key, "net_$": (rss * args.capital).sum()})
            res.append(st)
    R = pd.DataFrame(res).set_index("strategy")
    cols = ["years", "trades_yr", "SR_gross", "cost_SR", "SR_net", "ann_vol",
            "vol_vs_tau", "maxDD", "skew", "worst_day", "win_rate", "avg_ct", "net_$"]
    print(R.reindex(columns=cols).to_string(formatters={
        "years": "{:.1f}".format, "trades_yr": "{:,.0f}".format,
        "SR_gross": "{:+.2f}".format, "cost_SR": "{:.3f}".format,
        "SR_net": "{:+.2f}".format, "ann_vol": "{:.1%}".format,
        "vol_vs_tau": "{:.2f}".format, "maxDD": "{:.1%}".format,
        "skew": "{:+.2f}".format, "worst_day": "{:.2%}".format,
        "win_rate": "{:.1%}".format, "avg_ct": "{:.1f}".format,
        "net_$": "{:,.0f}".format}))

    # -- 4. is being flat in the day session worth 504 trades/yr? ----------
    print("\n[4] THE REAL QUESTION -- overnight block vs 24h hold, same instrument")
    comp = []
    for name in INSTRUMENTS:
        h = R.loc["%s 24h hold" % name]
        hc = R.loc["%s 24h hold [c2c]" % name]
        for wname in WINDOWS:
            o = R.loc["%s %s" % (name, wname)]
            comp.append({"inst": name, "window": wname, "SR_block": o.SR_net,
                         "SR_24h": h.SR_net, "SR_24h_c2c": hc.SR_net,
                         "edge": o.SR_net - h.SR_net,
                         "extra_cost_SR": o.cost_SR,
                         "verdict": "worth it" if o.SR_net > h.SR_net else "not worth it"})
    cp = pd.DataFrame(comp).set_index(["inst", "window"])
    print(cp.to_string(formatters={"SR_block": "{:+.2f}".format,
                                   "SR_24h": "{:+.2f}".format,
                                   "SR_24h_c2c": "{:+.2f}".format,
                                   "edge": "{:+.2f}".format,
                                   "extra_cost_SR": "{:.3f}".format}))
    print("    Going flat every morning buys a lower-vol, shorter-exposure book. "
          "It has to pay\n    for ~504 trades/yr of turnover to be worth doing.")
    print("    SR_24h is SEAM-FREE and is the number to use. SR_24h_c2c is the same "
          "book priced\n    close-to-close, which books the contango roll step as "
          "profit -- that is the version\n    a naive backtest produces, and the gap "
          "between the two columns is the size of the\n    trap. The block "
          "strategies never cross a seam, so they need no such correction.")

    # -- 5. skew and the risk target ---------------------------------------
    print("\n[5] RISK TARGET -- Carver halves tau for negative-skew payoffs")
    sk = []
    for name in INSTRUMENTS:
        for wname in WINDOWS:
            k = "%s %s" % (name, wname)
            r = series[k]
            neg = r.skew() < 0
            sk.append({"strategy": k, "skew": r.skew(),
                       "worst_night": r.min(), "p1": r.quantile(0.01),
                       "neg_skew": neg,
                       "tau_advised": TAU / 2 if neg else TAU})
    sd_ = pd.DataFrame(sk).set_index("strategy")
    print(sd_.to_string(formatters={"skew": "{:+.2f}".format,
                                    "worst_night": "{:.2%}".format,
                                    "p1": "{:.2%}".format,
                                    "tau_advised": "{:.1%}".format}))

    # -- 6. the book -------------------------------------------------------
    print("\n[6] PORTFOLIO -- handcrafted weights, measured IDM (the biggest real lever)")

    def build_book(cols, label, C, tag):
        """Equal weight across groups, equal within. IDM = 1/sqrt(w'Cw), capped."""
        members = list(cols)
        groups = {}
        for m in members:
            groups.setdefault(INSTRUMENTS[m][3], []).append(m)
        w = {m: (1.0 / len(groups)) / len(g) for g in groups.values() for m in g}
        wv = np.array([w[m] for m in members])
        idm = min(1.0 / np.sqrt(float(wv @ C.loc[members, members].values @ wv)),
                  IDM_CAP)
        port = sum(cols[m] * w[m] for m in members) * idm
        st = stats(port)
        print("    %-10s %-22s IDM %.2f  weights %s"
              % (tag, label, idm, {k: round(v, 3) for k, v in w.items()}))
        print("               SR_net %+.2f   ann_vol %.1f%% (%.2f x tau)   "
              "maxDD %.1f%% (%.1f x tau)   skew %+.2f   worst %.2f%%"
              % (st["SR_net"], st["ann_vol"] * 100, st["vol_vs_tau"],
                 st["maxDD"] * 100, st["DD_in_tau"], st["skew"],
                 st["worst_day"] * 100))
        return port, idm, st

    idms, idm4 = [], None
    for wname in WINDOWS:
        P = pd.DataFrame({n: series["%s %s" % (n, wname)]
                          for n in INSTRUMENTS}).fillna(0.0)
        C = P[P.index >= max(series["%s %s" % (n, wname)].index[0]
                             for n in INSTRUMENTS)].corr()
        for label, members in [("equity only (MES+MNQ)", ["MES", "MNQ"]),
                               ("handcrafted 4", list(INSTRUMENTS))]:
            port, idm, _ = build_book(P[members], label, C, wname)
            series["BOOK %s %s" % (wname, label)] = port
            idms.append(idm)
            if len(members) == len(INSTRUMENTS):
                idm4 = idm
        print("    correlation of nightly returns (%s):" % wname)
        print(C.to_string(float_format=lambda x: "%+.2f" % x))

    # the same book construction applied to the 24h alternative
    H = pd.DataFrame({n: series["%s 24h hold" % n] for n in INSTRUMENTS}).fillna(0.0)
    Ch = H[H.index >= max(series["%s 24h hold" % n].index[0]
                          for n in INSTRUMENTS)].corr()
    print("    --- the same four instruments held 24h, ~8-17 trades/yr instead of 504 ---")
    for label, members in [("equity only (MES+MNQ)", ["MES", "MNQ"]),
                           ("handcrafted 4", list(INSTRUMENTS))]:
        port, idm, _ = build_book(H[members], label, Ch, "24h hold")
        series["BOOK 24h %s" % label] = port
        idms.append(idm)
    print("    correlation of 24h returns:")
    print(Ch.to_string(float_format=lambda x: "%+.2f" % x))
    print("    The 24h book is LONG-ONLY BETA over a decade in which gold went "
          "1,150 -> 4,600\n    and equities ran hard. Its Sharpe is one bull regime, "
          "not an edge, and it carries\n    the full drawdown at 0.95 x tau. The "
          "overnight block at least has an economic\n    story. Weigh [4] and [6] "
          "with that in mind.")
    print("    MES/MNQ correlate ~+0.9: two equity index futures are ONE bet wearing\n"
          "    two tickers, and the IDM of ~1.0 says so. The commodity legs are what\n"
          "    actually diversify -- which is why they earn a place despite weak\n"
          "    standalone overnight numbers.")

    # -- 7. capital --------------------------------------------------------
    print("\n[7] MINIMUM CAPITAL -- per instrument, at its share of the book")
    idm_used = idm4          # the 4-instrument book these rows describe
    w_each = 1.0 / len(INSTRUMENTS)
    mc = cs[["min_cap_1ct", "min_cap_4ct"]].copy()
    mc["book_4ct"] = cs.min_cap_4ct / (idm_used * w_each)
    print(mc.to_string(float_format=lambda x: "{:,.0f}".format(x)))
    print("    book_4ct = 4-contract floor for that instrument at w=%.0f%%, "
          "measured IDM %.2f.\n    Portfolio minimum capital is the LARGEST of "
          "these: $%s." % (w_each * 100, idm_used, format(mc.book_4ct.max(), ",.0f")))
    if args.capital < mc.book_4ct.max():
        print("    -> $%s does not clear it. Carver's order of preference: micros "
              "(already used),\n       then drop the most expensive instrument, "
              "then accept 2-contract rounding.\n       Never raise tau to make it fit."
              % format(args.capital, ",.0f"))

    # -- 8. verdict --------------------------------------------------------
    print("\n[8] DRAWDOWN EXPECTATION -- set before trading, so a drawdown is not evidence")
    print("    At tau=%.0f%%: a %.0f%% peak-to-trough is ORDINARY (2x tau), "
          "%.0f%% is planned for (3x tau)." % (TAU * 100, 2 * TAU * 100, 3 * TAU * 100))
    print("    Detecting SR 0.5 from zero at 95% needs ~30 years; SR 0.24 needs ~70.")
    print("    This test has %.1f years on the shortest leg, %.1f on the longest. "
          "Nothing here is\n    proven -- the measurable things are realised vol vs "
          "tau and realised cost vs model."
          % (R.years.min(), R.years.max()))
    print("    Data caveat: MGC before ~2019 traded a few thousand lots a session, so "
          "its real\n    spread was wider than the 1-tick cost model assumes; treat "
          "MGC's early years as\n    optimistic rather than as clean out-of-sample.")

    # -- 9. artefacts ------------------------------------------------------
    R.to_csv(REPORTS / "overnight_carver_summary.csv")
    pd.DataFrame(series).to_csv(REPORTS / "overnight_carver_daily_returns.csv")
    cs.to_csv(REPORTS / "overnight_carver_cost_screen.csv")
    print("\n[9] written -> reports/overnight_carver_summary.csv, "
          "overnight_carver_daily_returns.csv,\n    overnight_carver_cost_screen.csv, "
          "overnight_cost_screen_<INST>.csv")


if __name__ == "__main__":
    main()
