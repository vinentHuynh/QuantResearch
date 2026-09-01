"""Short-holding-period (1 day to 1 week) strategy bake-off on the CME panel.

Everything here is deliberately restricted to holds of <= ~2 weeks, which is the
regime where cost drag decides the answer. Five candidates plus benchmarks:

1. XS-REVERSAL   cross-sectional short-term reversal: rank markets by trailing
                 N-day risk-adjusted return, long losers / short winners,
                 inverse-vol weighted, weekly rebalance, 5-day hold.
2. SPREAD-REV    z-score reversion on 8 classic futures spreads (crack, gold-
                 silver, ES/NQ, curve, grains), enter |z|>2, exit |z|<0.5 or
                 15-day time stop.
3. NR7-BREAK     narrowest-range-of-7 compression breakout, 5-day time exit.
4. DONCH-20      20-day Donchian break with a 5-day time exit, versus the same
                 break held to the opposite signal (to price what the time
                 exit costs).
5. TOM / DOW     turn-of-month and day-of-week calendar effects on the index
                 sleeve, plus an FOMC pre-announcement drift event study.

Fill realism: breakout entries are gap-aware. If the session opens through the
trigger the fill is the open, never the level. A naive fill-at-the-level bug
manufactures Sharpe out of nothing on daily bars (see pdh_pdl_range_backtest).

Costs are swept 0/1/2/5 bps per side against actual weight turnover, including
the leverage multiplier, because at 5-day holds the cost line is the result.

Data is the local panel built by fetch_cme_data.py. Proxies are cash indices,
bond price indices, spot FX, and UNADJUSTED continuous commodity fronts -- roll
gaps in those fronts look like real 1-day moves and will feed the reversal and
breakout signals false positives. Treat commodity-heavy results as an upper
bound on what is real.

    python short_horizon_backtest.py                      # 2024-01-01 -> end
    python short_horizon_backtest.py --start 2005-01-01   # regime-luck check
    python short_horizon_backtest.py --export runs.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).with_name("data") / "cme_daily.parquet"

TRADING_DAYS = 252

# Markets excluded from the cross-sectional book.
#   VX  - vol index, not a normal tradable asset; its reversal dominates any rank
#   DC  - Class III milk proxy DL1 does not track the real contract
EXCLUDE = {"VX", "DC"}

# Spread pairs: (long leg, short leg, label). Equal-notional on the log ratio.
SPREAD_PAIRS = [
    ("GC", "SI", "gold / silver"),
    ("CL", "BZ", "WTI / Brent"),
    ("CL", "HO", "crude / heating oil"),
    ("HO", "RB", "heating oil / gasoline"),
    ("ES", "NQ", "S&P / Nasdaq"),
    ("ZN", "ZB", "10y / 30y curve"),
    ("ZC", "ZW", "corn / wheat"),
    ("LE", "GF", "live / feeder cattle"),
]

# FOMC announcement days (second day of each meeting). 2026 from the published
# schedule; the panel ends mid-2026 so later dates simply never match.
FOMC_DATES = [
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
]

INDEX_SLEEVE = ["ES", "NQ", "RTY", "YM"]


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------
def load_panel(start: str, min_coverage: float = 0.95):
    """Wide open/high/low/close frames, restricted to markets that actually
    trade over the whole window (drops the ~240-day PWB FX series)."""
    df = pd.read_parquet(DATA)
    df = df[~df["market"].isin(EXCLUDE)]
    df["date"] = pd.to_datetime(df["date"])

    frames = {}
    for field in ("open", "high", "low", "close"):
        wide = (
            df.pivot_table(index="date", columns="market", values=field, aggfunc="last")
            .sort_index()
        )
        frames[field] = wide

    # A shared calendar: days where the equity index sleeve prints.
    close = frames["close"]
    close = close[close.index >= pd.Timestamp(start) - pd.Timedelta(days=400)]
    window = close[close.index >= pd.Timestamp(start)]
    coverage = window.notna().mean()
    keep = sorted(coverage[coverage >= min_coverage].index)

    out = {f: frames[f].loc[close.index, keep] for f in frames}
    dropped = sorted(set(coverage.index) - set(keep))
    out, scrubbed = scrub_glitches(out)
    return out, keep, dropped, scrubbed


def scrub_glitches(frames: dict, threshold: float = 0.5):
    """Blank single-day vendor glitch prints across all four OHLC fields.

    A glitch is a day whose close jumps more than `threshold` and reverses by
    more than `threshold` the next day -- e.g. cocoa printing 0.91 on
    2025-11-25 between two 5000-handle closes. Clipping the RETURN is not
    enough: any engine reading raw prices (breakout levels, spread ratios)
    still sees the bad print, which is what produced a 3945% book vol here.
    """
    close = frames["close"]
    r = close.pct_change(fill_method=None)
    nxt = r.shift(-1)
    glitch = (r.abs() > threshold) & (nxt.abs() > threshold) & (np.sign(r) != np.sign(nxt))
    n = int(glitch.sum().sum())
    if n:
        out = {}
        for field, wide in frames.items():
            out[field] = wide.mask(glitch)
        # Restore close continuity so returns bridge the hole instead of
        # spanning it; leave high/low blank so no breakout can trigger there.
        out["close"] = out["close"].ffill(limit=3)
        frames = out
    hits = [(str(close.index[i].date()), close.columns[j])
            for i, j in zip(*np.where(glitch.to_numpy()))]
    return frames, hits


def pct_returns(close: pd.DataFrame, clip: float = 0.50):
    """Close-to-close returns, clipped to kill vendor glitch prints.

    Anything past +/-50% in a day on these markets is a data error or an
    unadjusted roll gap, not a tradable move. Clipping is the conservative
    direction: it removes fake profit, it cannot create any.
    """
    ret = close.pct_change(fill_method=None)
    n_clipped = int(((ret.abs() > clip) & ret.notna()).sum().sum())
    return ret.clip(-clip, clip), n_clipped


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------
def stats(ret: pd.Series, label: str, turnover: pd.Series | None = None,
          bench: pd.Series | None = None):
    ret = ret.dropna()
    if len(ret) < 30:
        return None
    beta = np.nan
    if bench is not None:
        j = pd.concat({"a": ret, "b": bench}, axis=1).dropna()
        if len(j) > 30 and j["b"].std() > 0:
            beta = float(j["a"].cov(j["b"]) / j["b"].var())
    mu, sd = ret.mean(), ret.std(ddof=0)
    sharpe = mu / sd * np.sqrt(TRADING_DAYS) if sd > 0 else np.nan
    nav = (1 + ret).cumprod()
    years = len(ret) / TRADING_DAYS
    # A book that touches -100% is ruined; do not report a complex-number CAGR.
    cagr = nav.iloc[-1] ** (1 / years) - 1 if nav.min() > 0 else float("nan")
    dd = float((nav / nav.cummax() - 1).min())
    # Standard error of an annualized Sharpe over this sample length.
    se = np.sqrt((1 + 0.5 * sharpe**2) / years) if np.isfinite(sharpe) else np.nan
    ann_turnover = float(turnover.sum() / years) if turnover is not None else np.nan
    return {
        "strategy": label,
        "sharpe": sharpe,
        "se": se,
        "tstat": sharpe / se if se and np.isfinite(se) else np.nan,
        "cagr": cagr,
        "vol": sd * np.sqrt(TRADING_DAYS),
        "maxdd": dd,
        # Hit rate over days actually holding risk; sparse calendar strategies
        # sit flat most of the year and an all-days hit rate just measures that.
        "hit": float((ret[ret != 0] > 0).mean()) if (ret != 0).any() else np.nan,
        "exposure": float((ret != 0).mean()),
        "days": len(ret),
        "turnover": ann_turnover,
        "beta": beta,
    }


def apply_costs(gross: pd.Series, turnover: pd.Series, bps: float):
    """Costs charged per side against gross weight turnover."""
    return gross - turnover.reindex(gross.index).fillna(0.0) * (bps / 1e4)


def vol_target(weights: pd.DataFrame, ret: pd.DataFrame, target=0.10,
               window=60, cap=4.0):
    """Lag weights one day, then lever the book toward a vol target using a
    trailing realized-vol estimate that only uses information already known.

    Returns (net-of-nothing return series, gross weight turnover series).
    """
    w = weights.shift(1)
    raw = (w * ret).sum(axis=1, min_count=1)
    realized = raw.rolling(window, min_periods=20).std().shift(1) * np.sqrt(TRADING_DAYS)
    lev = (target / realized).replace([np.inf, -np.inf], np.nan).clip(upper=cap)
    lev = lev.fillna(0.0)
    levered_w = w.mul(lev, axis=0)
    out = (levered_w * ret).sum(axis=1, min_count=1)
    turnover = levered_w.diff().abs().sum(axis=1)
    return out, turnover


# --------------------------------------------------------------------------
# 1. cross-sectional short-term reversal
# --------------------------------------------------------------------------
def xs_reversal(close, ret, lookback=5, hold=5, frac=0.33, vol_window=60):
    """Rank on trailing risk-adjusted N-day return; fade the extremes."""
    vol = ret.rolling(vol_window, min_periods=30).std()
    signal = (close / close.shift(lookback) - 1.0) / vol
    signal = signal.replace([np.inf, -np.inf], np.nan)

    weights = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    positions = pd.Series(0.0, index=close.columns)
    rebalance_days = close.index[::hold]

    for date in close.index:
        if date in rebalance_days:
            sig = signal.loc[date].dropna()
            sig = sig[vol.loc[date].reindex(sig.index).gt(0)]
            if len(sig) >= 10:
                k = max(1, int(len(sig) * frac))
                ranked = sig.sort_values()
                longs, shorts = ranked.index[:k], ranked.index[-k:]  # fade
                inv = (1.0 / vol.loc[date]).replace([np.inf, -np.inf], np.nan)
                positions = pd.Series(0.0, index=close.columns)
                for side, names in ((+1, longs), (-1, shorts)):
                    w = inv[names].dropna()
                    if w.sum() > 0:
                        positions[w.index] += side * 0.5 * w / w.sum()
        weights.loc[date] = positions
    return weights


# --------------------------------------------------------------------------
# 2. spread z-score reversion
# --------------------------------------------------------------------------
def spread_reversion(close, ret, pairs, window=60, entry=2.0, exit_z=0.5,
                     max_hold=15):
    legs, per_pair = {}, {}
    for a, b, label in pairs:
        if a not in close.columns or b not in close.columns:
            continue
        logratio = np.log(close[a].abs().clip(lower=1e-9)) - np.log(close[b].abs().clip(lower=1e-9))
        z = (logratio - logratio.rolling(window, min_periods=30).mean()) / \
            logratio.rolling(window, min_periods=30).std()
        z = z.replace([np.inf, -np.inf], np.nan)

        pos = pd.Series(0.0, index=close.index)
        state, held = 0.0, 0
        for i, date in enumerate(close.index):
            zi = z.iloc[i]
            if state != 0.0:
                held += 1
                if not np.isfinite(zi) or abs(zi) < exit_z or held >= max_hold:
                    state, held = 0.0, 0
            elif np.isfinite(zi) and abs(zi) > entry:
                state, held = -np.sign(zi), 0  # fade the stretch
            pos.iloc[i] = state

        spread_ret = (ret[a] - ret[b]) / 2.0  # half notional per leg
        legs[label] = pos.shift(1) * spread_ret
        per_pair[label] = (pos, spread_ret)

    book = pd.DataFrame(legs)
    turnover = sum(
        p.shift(1).diff().abs() for p, _ in per_pair.values()
    ) if per_pair else pd.Series(0.0, index=close.index)
    return book, turnover, per_pair


# --------------------------------------------------------------------------
# 3/4. gap-aware breakout engine
# --------------------------------------------------------------------------
def breakout(op, hi, lo, close, upper, lower, hold, both_sides=True,
             ambiguous_policy="coin", seed=7):
    """Enter on a break of the given levels with honest fills, exit after
    `hold` sessions. `upper`/`lower` are levels known at the prior close.

    Fill rule: gap through the level -> pay the open. Otherwise pay the level.

    When a session touches BOTH levels, daily bars cannot say which came
    first. The tempting move is to skip those days -- but you only learn a day
    was two-sided at its close, so skipping quietly deletes exactly the whipsaw
    sessions and inflates the result. Policies:
      "coin"    seeded 50/50 draw. Unbiased in expectation. Default.
      "adverse" always take the side that loses on the day. Lower bound.
      "skip"    the biased version, kept only to measure the bias.
    An open that gapped through one level resolves the order regardless: that
    level was touched at the bell.
    """
    rng = np.random.default_rng(seed)
    pnl = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    turn = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    ambiguous = 0

    for market in close.columns:
        o, h, l, c = op[market], hi[market], lo[market], close[market]
        up, dn = upper[market], lower[market]
        entry_price, direction, held = np.nan, 0, 0

        for i in range(1, len(c)):
            date = c.index[i]
            if direction != 0:
                held += 1
                prev = c.iloc[i - 1]
                if np.isfinite(prev) and prev != 0:
                    pnl.at[date, market] = direction * (c.iloc[i] - prev) / abs(prev)
                if held >= hold:
                    direction, held = 0, 0
                    turn.at[date, market] += 1.0
                continue

            u, d = up.iloc[i - 1], dn.iloc[i - 1]
            oi, ci = o.iloc[i], c.iloc[i]
            if not (np.isfinite(u) and np.isfinite(d) and np.isfinite(oi)
                    and np.isfinite(ci)):
                continue
            hit_up = np.isfinite(h.iloc[i]) and h.iloc[i] >= u
            hit_dn = both_sides and np.isfinite(l.iloc[i]) and l.iloc[i] <= d

            if hit_up and hit_dn:
                ambiguous += 1
                if oi > u:                      # gapped through the top first
                    direction, entry_price = 1, oi
                elif oi < d:                    # gapped through the bottom first
                    direction, entry_price = -1, oi
                elif ambiguous_policy == "skip":
                    continue
                elif ambiguous_policy == "adverse":
                    direction = -1 if ci > u else 1
                    entry_price = u if direction == 1 else d
                else:                           # coin
                    direction = 1 if rng.random() < 0.5 else -1
                    entry_price = u if direction == 1 else d
            elif hit_up:
                entry_price = oi if oi > u else u
                direction = 1
            elif hit_dn:
                entry_price = oi if oi < d else d
                direction = -1
            else:
                continue

            held = 0
            turn.at[date, market] += 1.0
            if np.isfinite(entry_price) and entry_price != 0:
                pnl.at[date, market] = direction * (ci - entry_price) / abs(entry_price)

    return pnl, turn, ambiguous


def equal_risk_book(pnl, turn, ret, vol_window=60, target=0.10, cap=4.0):
    """Inverse-vol weight the per-market breakout P&L into one book."""
    vol = ret.rolling(vol_window, min_periods=30).std().shift(1)
    inv = (1.0 / vol).replace([np.inf, -np.inf], np.nan)
    inv = inv.where(pnl.ne(0.0) | inv.isna())
    norm = inv.div(inv.abs().sum(axis=1), axis=0).fillna(0.0)
    raw = (norm * pnl).sum(axis=1, min_count=1)
    realized = raw.rolling(60, min_periods=20).std().shift(1) * np.sqrt(TRADING_DAYS)
    lev = (target / realized).replace([np.inf, -np.inf], np.nan).clip(upper=cap).fillna(0.0)
    return raw * lev, (norm * turn).sum(axis=1) * lev


# --------------------------------------------------------------------------
# 5. calendar / event studies
# --------------------------------------------------------------------------
def calendar_studies(ret, sleeve, start):
    index_ret = ret[[m for m in sleeve if m in ret.columns]].mean(axis=1)
    index_ret = index_ret[index_ret.index >= pd.Timestamp(start)].dropna()

    dow = index_ret.groupby(index_ret.index.dayofweek).agg(["mean", "count"])
    dow.index = ["Mon", "Tue", "Wed", "Thu", "Fri"][: len(dow)]

    # Turn of month: long from the close 2 sessions before month end through
    # the 3rd session of the new month.
    month_id = index_ret.index.to_period("M")
    pos = pd.Series(0.0, index=index_ret.index)
    idx_in_month = index_ret.groupby(month_id).cumcount()
    size = index_ret.groupby(month_id).transform("size")
    from_end = size - idx_in_month - 1
    in_window = (from_end <= 1) | (idx_in_month <= 2)
    pos[in_window.values] = 1.0
    tom = pos.shift(1).fillna(0.0) * index_ret

    fomc = pd.to_datetime([d for d in FOMC_DATES])
    rows = []
    for d in fomc:
        loc = index_ret.index.searchsorted(d)
        if loc <= 3 or loc >= len(index_ret) - 1:
            continue
        if abs((index_ret.index[loc] - d).days) > 4:
            continue
        rows.append({
            "date": index_ret.index[loc].date(),
            "pre_2d": float(index_ret.iloc[loc - 2:loc].sum()),
            "day_of": float(index_ret.iloc[loc]),
            "next_day": float(index_ret.iloc[loc + 1]),
        })
    return dow, tom, index_ret, pd.DataFrame(rows)


def tradability_check(per_pair, op, close, ret, cut):
    """Close-execution versus open-execution for the spread book.

    A signal computed from settlement prices cannot also be filled at that
    same settlement. Charging the position from the NEXT open is the honest
    version. If a reversion edge is economic convergence it survives the one
    extra session; if it is a stale or noisy closing print correcting itself
    overnight, the whole edge sits in the close->open gap and open execution
    prints zero. That is the difference between a trade and an artifact.
    """
    ropen = op.pct_change(fill_method=None).clip(-0.5, 0.5)

    def sharpe(s):
        s = cut(s).dropna()
        if len(s) < 30 or s.std() == 0:
            return np.nan
        return s.mean() / s.std(ddof=0) * np.sqrt(TRADING_DAYS)

    rows, legs_c, legs_o = [], {}, {}
    for a, b, label in SPREAD_PAIRS:
        if label not in per_pair:
            continue
        pos, sr = per_pair[label]
        legs_c[label] = pos.shift(1) * sr                       # fill at signal close
        legs_o[label] = pos.shift(2) * ((ropen[a] - ropen[b]) / 2)  # fill at next open
        rows.append((label, sharpe(legs_c[label]), sharpe(legs_o[label]),
                     int(pos.diff().abs().gt(0).sum()),
                     cut((ret[a] - ret[b]) / 2).dropna().autocorr(1)))

    bc = sharpe(pd.DataFrame(legs_c).mean(axis=1))
    bo = sharpe(pd.DataFrame(legs_o).mean(axis=1))
    hdr = f"{'Spread pair':<26}{'CloseExec':>10}{'OpenExec':>10}{'Trades':>8}{'AC(1)':>8}"
    print("\n" + "=" * len(hdr))
    print("SPREAD REVERSION: TRADABILITY")
    print(hdr)
    print("-" * len(hdr))
    for label, sc_, so_, n, ac in rows:
        print(f"  {label:<24}{sc_:>10.2f}{so_:>10.2f}{n:>8}{ac:>8.3f}")
    print("-" * len(hdr))
    print(f"  {'BASKET (equal weight)':<24}{bc:>10.2f}{bo:>10.2f}")
    if np.isfinite(bc) and np.isfinite(bo) and bc > 0.5 and bo < 0.5 * bc:
        print("  => edge lives in the close->open gap, not in convergence:"
              " NOT TRADABLE as specified.")


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--target-vol", type=float, default=0.10)
    ap.add_argument("--export", default=None)
    args = ap.parse_args()

    frames, markets, dropped, scrubbed = load_panel(args.start)
    op, hi, lo, close = frames["open"], frames["high"], frames["low"], frames["close"]
    ret, n_clipped = pct_returns(close)
    start = pd.Timestamp(args.start)

    def cut(s):
        return s[s.index >= start]

    print(f"\nSHORT-HORIZON BAKE-OFF | {len(markets)} markets | "
          f"{cut(close).index.min().date()} -> {cut(close).index.max().date()} | "
          f"target vol {args.target_vol:.0%}")
    print(f"dropped for coverage: {', '.join(dropped) if dropped else 'none'}")
    print(f"glitch prints scrubbed: {len(scrubbed)}"
          + (f"  {scrubbed[:6]}" if scrubbed else ""))
    print(f"residual returns clipped at +/-50%: {n_clipped}")

    results, cost_rows = [], []
    bench = cut(ret["ES"]) if "ES" in ret.columns else None

    def record(label, gross, turnover, hold_note):
        g, t = cut(gross), cut(turnover)
        base = stats(g, label, t, bench=bench)
        if base is None:
            return
        base["hold"] = hold_note
        results.append(base)
        row = {"strategy": label}
        for bps in (0, 1, 2, 5):
            s = stats(apply_costs(g, t, bps), label)
            row[f"{bps}bps"] = s["sharpe"] if s else np.nan
        cost_rows.append(row)

    # 1. cross-sectional reversal, several lookbacks
    for lb in (3, 5, 10, 21):
        w = xs_reversal(close, ret, lookback=lb, hold=5)
        r, t = vol_target(w, ret, target=args.target_vol)
        record(f"XS reversal {lb}d rank", r, t, "5d")

    # momentum-signed version of the same book, as a control
    w = xs_reversal(close, ret, lookback=5, hold=5)
    r, t = vol_target(-w, ret, target=args.target_vol)
    record("XS momentum 5d (control)", r, t, "5d")

    # 2. spreads
    book, sp_turn, per_pair = spread_reversion(close, ret, SPREAD_PAIRS)
    if not book.empty:
        eq = book.mean(axis=1)
        realized = eq.rolling(60, min_periods=20).std().shift(1) * np.sqrt(TRADING_DAYS)
        lev = (args.target_vol / realized).replace([np.inf, -np.inf], np.nan).clip(upper=4.0).fillna(0.0)
        record("Spread reversion (8 pairs)", eq * lev, sp_turn * lev / len(book.columns), "<=15d")

    # 3. NR7 compression breakout
    rng = hi - lo
    is_nr7 = rng.eq(rng.rolling(7, min_periods=7).min())
    nr7_up = hi.where(is_nr7)
    nr7_dn = lo.where(is_nr7)
    n_signals = int(is_nr7[is_nr7.index >= start].sum().sum())
    for policy, tag in (("coin", ""), ("adverse", " [adverse fills]"),
                        ("skip", " [skip-ambig, BIASED]")):
        pnl, turn, amb = breakout(op, hi, lo, close, nr7_up, nr7_dn, hold=5,
                                  ambiguous_policy=policy)
        r, t = equal_risk_book(pnl, turn, ret, target=args.target_vol)
        record(f"NR7 breakout{tag}", r, t, "5d")
    print(f"NR7 signals: {n_signals} | two-sided sessions (fill order unknowable "
          f"on daily bars): {amb} ({100*amb/max(n_signals,1):.0f}%)")

    # 4. Donchian 20 with a 5-day exit, and a 20-day exit for contrast
    up20 = hi.rolling(20, min_periods=20).max()
    dn20 = lo.rolling(20, min_periods=20).min()
    for hold in (5, 20):
        pnl, turn, _ = breakout(op, hi, lo, close, up20, dn20, hold=hold)
        r, t = equal_risk_book(pnl, turn, ret, target=args.target_vol)
        record(f"Donchian-20 break, {hold}d exit", r, t, f"{hold}d")

    # 5. calendar and event
    dow, tom, index_ret, fomc = calendar_studies(ret, INDEX_SLEEVE, args.start)
    tom_turn = tom.ne(0).astype(float).diff().abs().fillna(0.0)
    record("Turn-of-month (index sleeve)", tom, tom_turn, "5d")

    # benchmarks
    bh = cut(ret["ES"]) if "ES" in ret.columns else None
    if bh is not None:
        record("Benchmark: ES buy & hold", ret["ES"], pd.Series(0.0, index=ret.index), "hold")
    ew = ret.mean(axis=1)
    record("Benchmark: EW panel long", ew, pd.Series(0.0, index=ret.index), "hold")

    # ---------------- output ----------------
    res = pd.DataFrame(results)
    hdr = (f"{'Strategy':<34}{'Sharpe':>8}{'+/-SE':>7}{'t':>6}{'CAGR':>8}"
           f"{'Vol':>7}{'MaxDD':>8}{'Hit':>7}{'Beta':>7}{'Turn/yr':>9}")
    print("\n" + "=" * len(hdr))
    print("GROSS OF COSTS")
    print(hdr)
    print("-" * len(hdr))
    for _, r_ in res.iterrows():
        print(f"{r_['strategy']:<34}{r_['sharpe']:>8.2f}{r_['se']:>7.2f}"
              f"{r_['tstat']:>6.1f}{r_['cagr']*100:>7.1f}%{r_['vol']*100:>6.1f}%"
              f"{r_['maxdd']*100:>7.1f}%{r_['hit']*100:>6.1f}%{r_['beta']:>7.2f}"
              f"{r_['turnover']:>9.1f}")

    costs = pd.DataFrame(cost_rows)
    hdr2 = f"{'Strategy':<34}{'0bps':>8}{'1bps':>8}{'2bps':>8}{'5bps':>8}"
    print("\n" + "=" * len(hdr2))
    print("NET SHARPE BY COST PER SIDE")
    print(hdr2)
    print("-" * len(hdr2))
    for _, r_ in costs.iterrows():
        print(f"{r_['strategy']:<34}{r_['0bps']:>8.2f}{r_['1bps']:>8.2f}"
              f"{r_['2bps']:>8.2f}{r_['5bps']:>8.2f}")

    print("\nDAY OF WEEK (index sleeve, mean daily bps)")
    for name, row in dow.iterrows():
        print(f"  {name}  {row['mean']*1e4:>7.2f} bps   n={int(row['count'])}")

    if not fomc.empty:
        print(f"\nFOMC EVENT STUDY (index sleeve, {len(fomc)} meetings, bps)")
        print(f"  pre-announcement 2-day drift : {fomc['pre_2d'].mean()*1e4:>7.1f} "
              f"(hit {100*(fomc['pre_2d']>0).mean():.0f}%)")
        print(f"  announcement day             : {fomc['day_of'].mean()*1e4:>7.1f} "
              f"(hit {100*(fomc['day_of']>0).mean():.0f}%)")
        print(f"  day after                    : {fomc['next_day'].mean()*1e4:>7.1f} "
              f"(hit {100*(fomc['next_day']>0).mean():.0f}%)")

    tradability_check(per_pair, op, close, ret, cut)

    years = len(cut(close)) / TRADING_DAYS
    print(f"\nSample = {years:.1f} years. Sharpe standard error ~ "
          f"{np.sqrt(1/years):.2f}, so anything inside +/-{2*np.sqrt(1/years):.2f} "
          f"is statistically indistinguishable from zero.")

    if args.export:
        res.to_csv(args.export, index=False)
        print(f"wrote {args.export}")


if __name__ == "__main__":
    main()
