"""PDH/PDL + prior-day range-size study on SPY/QQQ 5-min (RTH, 2024->now).

Tests the KERNEL of the "Asia open off PDH/PDL and range size" idea, but at the
NEW YORK open, because there is no Asia-session data in this workspace (SPY/QQQ
don't trade Asia hours; PWB has no intraday futures). If an edge shows up here it
is worth porting to ES/NQ Globex in Pine; if it doesn't, the Asia version won't
save it.

Definitions (all known at the RTH open, no look-ahead):
  PDH / PDL      = prior day's RTH high / low.
  prior range%   = (PDH - PDL) / prior close.
  regime         = where prior range% sits vs its own trailing distribution:
                   COMPRESSED = bottom third, WIDE = top third (rolling window).

Strategies (one trade/day max, flat by close, cost per side):
  ORB all / ORB compressed / ORB wide
      first 5-min bar sets the range; trade its breakout (both ways), stop the
      opposite extreme, exit EOD. Gated versions only trade in that regime.
  PDH/PDL breakout (all / compressed)
      first cross above PDH -> long; below PDL -> short; stop other level; EOD.
  PDH/PDL fade (all / wide)
      first touch of PDH -> short back toward the midpoint; PDL -> long; stop
      beyond the level; target = (PDH+PDL)/2 or EOD.

Usage: python pdh_pdl_range_backtest.py --cost-bps 1.0 --start 2024-01-01
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from pwb_toolbox.performance.metrics import (
    sharpe_ratio, annualized_volatility, cagr, max_drawdown,
)

DATA = (Path(__file__).resolve().parents[2] / "data")
SYMS = ["SPY", "QQQ"]


def load(sym):
    df = pd.read_parquet(DATA / f"{sym}_5min.parquet")
    df.index = pd.to_datetime(df.index)
    return df.sort_index().between_time("09:30", "15:59")


def day_levels(df, q_lo=0.33, q_hi=0.66, win=40):
    """Per-day PDH/PDL/prior-close and compression/wide regime flags."""
    g = df.groupby(df.index.normalize())
    daily = pd.DataFrame({
        "high": g["high"].max(), "low": g["low"].min(),
        "open": g["open"].first(), "close": g["close"].last(),
    })
    pdh, pdl = daily["high"].shift(1), daily["low"].shift(1)
    pclose = daily["close"].shift(1)
    prange_pct = (pdh - pdl) / pclose
    q33 = prange_pct.rolling(win, min_periods=win // 2).quantile(q_lo)
    q66 = prange_pct.rolling(win, min_periods=win // 2).quantile(q_hi)
    comp = prange_pct <= q33
    wide = prange_pct >= q66
    return pd.DataFrame({"PDH": pdh, "PDL": pdl, "pclose": pclose,
                         "prange_pct": prange_pct, "comp": comp, "wide": wide})


def simulate(df, lv, mode, cost):
    """Return (daily_ret Series, n_trades, wins) for one symbol/mode."""
    rows = []
    for day, g in df.groupby(df.index.normalize()):
        g = g.sort_index()
        if len(g) < 4 or day not in lv.index:
            continue
        row = lv.loc[day]
        pdh, pdl = row["PDH"], row["PDL"]
        if np.isnan(pdh) or np.isnan(pdl) or pdh <= pdl:
            rows.append((day, 0.0, False, False)); continue
        mid = (pdh + pdl) / 2
        comp, wide = bool(row["comp"]), bool(row["wide"])
        ret, traded, win = 0.0, False, False

        if mode.startswith("orb"):
            if mode == "orb_comp" and not comp:
                rows.append((day, 0.0, False, False)); continue
            if mode == "orb_wide" and not wide:
                rows.append((day, 0.0, False, False)); continue
            first, rest = g.iloc[0], g.iloc[1:]
            or_hi, or_lo = first["high"], first["low"]
            direction, entry, stop = 0, np.nan, np.nan
            exit_px = rest["close"].iloc[-1]
            for _, b in rest.iterrows():
                if direction == 0:
                    if b["high"] >= or_hi:
                        direction, stop = 1, or_lo
                        entry = or_hi if b["open"] <= or_hi else b["open"]  # gap-aware fill
                    elif b["low"] <= or_lo:
                        direction, stop = -1, or_hi
                        entry = or_lo if b["open"] >= or_lo else b["open"]
                else:
                    if direction > 0 and b["low"] <= stop:
                        exit_px = stop; break
                    if direction < 0 and b["high"] >= stop:
                        exit_px = stop; break
            if direction != 0:
                ret = direction * (exit_px / entry - 1) - 2 * cost
                traded, win = True, (direction * (exit_px / entry - 1)) > 0

        elif mode.startswith("brk"):   # PDH/PDL breakout
            if mode == "brk_comp" and not comp:
                rows.append((day, 0.0, False, False)); continue
            direction, entry, stop, exit_px = 0, np.nan, np.nan, g["close"].iloc[-1]
            for _, b in g.iloc[1:].iterrows():
                if direction == 0:
                    if b["high"] >= pdh:
                        direction, stop = 1, pdl
                        entry = pdh if b["open"] <= pdh else b["open"]  # gap-aware fill
                    elif b["low"] <= pdl:
                        direction, stop = -1, pdh
                        entry = pdl if b["open"] >= pdl else b["open"]
                else:
                    if direction > 0 and b["low"] <= stop:
                        exit_px = stop; break
                    if direction < 0 and b["high"] >= stop:
                        exit_px = stop; break
            if direction != 0:
                ret = direction * (exit_px / entry - 1) - 2 * cost
                traded, win = True, (direction * (exit_px / entry - 1)) > 0

        elif mode.startswith("fade"):  # PDH/PDL fade back to midpoint
            if mode == "fade_wide" and not wide:
                rows.append((day, 0.0, False, False)); continue
            buf = (pdh - pdl) * 0.25
            direction, entry, stop, target, exit_px = 0, np.nan, np.nan, mid, g["close"].iloc[-1]
            for _, b in g.iloc[1:].iterrows():
                if direction == 0:
                    # fade only a level touched from INSIDE the range; a gap past
                    # the level is not a fadeable fill (you never got the entry).
                    if b["high"] >= pdh and b["open"] <= pdh:
                        direction, entry, stop, target = -1, pdh, pdh + buf, mid
                    elif b["low"] <= pdl and b["open"] >= pdl:
                        direction, entry, stop, target = 1, pdl, pdl - buf, mid
                else:
                    if direction > 0:
                        if b["low"] <= stop:
                            exit_px = stop; break
                        if b["high"] >= target:
                            exit_px = target; break
                    else:
                        if b["high"] >= stop:
                            exit_px = stop; break
                        if b["low"] <= target:
                            exit_px = target; break
            if direction != 0:
                ret = direction * (exit_px / entry - 1) - 2 * cost
                traded, win = True, (direction * (exit_px / entry - 1)) > 0

        rows.append((day, ret, traded, win))

    s = pd.DataFrame(rows, columns=["day", "ret", "t", "w"]).set_index("day")
    return s["ret"], int(s["t"].sum()), int(s["w"].sum())


def s_buyhold(df, cost):
    g = df.groupby(df.index.normalize())["close"].last()
    return g.pct_change().fillna(0.0), 0, 0


def stats(nav):
    depth, _ = max_drawdown(nav)
    return sharpe_ratio(nav), cagr(nav), annualized_volatility(nav), abs(depth)


MODES = {
    "Buy & hold": None,
    "ORB all": "orb_all",
    "ORB compressed-only": "orb_comp",
    "ORB wide-only": "orb_wide",
    "PDH/PDL breakout all": "brk_all",
    "PDH/PDL breakout comp": "brk_comp",
    "PDH/PDL fade all": "fade_all",
    "PDH/PDL fade wide": "fade_wide",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--balance", type=float, default=100_000)
    ap.add_argument("--start", type=str, default="2024-01-01")
    ap.add_argument("--cost-bps", type=float, default=1.0)
    args = ap.parse_args()
    cost = args.cost_bps / 1e4
    start = pd.Timestamp(args.start)

    data = {s: load(s) for s in SYMS}
    levels = {s: day_levels(data[s]) for s in SYMS}
    rng = data["SPY"].index
    print(f"\nPDH/PDL + range-regime | SPY+QQQ 5-min 50/50 (NY-open proxy for Asia) | "
          f"{rng.min().date()}->{rng.max().date()} | cost {args.cost_bps}bps/side\n")
    hdr = (f"{'Strategy':<24}{'Trades':>7}{'Win%':>7}{'Sharpe':>8}"
           f"{'CAGR':>8}{'Vol':>7}{'MaxDD':>8}{'End$':>12}")
    print(hdr); print("-" * len(hdr))

    rows = []
    for name, mode in MODES.items():
        per_sym, trades, wins = [], 0, 0
        for s in SYMS:
            if mode is None:
                r, nt, nw = s_buyhold(data[s], cost)
            else:
                r, nt, nw = simulate(data[s], levels[s], mode, cost)
            per_sym.append(r); trades += nt; wins += nw
        r = pd.concat(per_sym, axis=1).fillna(0.0)
        r = r[r.index >= start].mean(axis=1)
        nav = args.balance * (1 + r).cumprod()
        sh, cg, vol, dd = stats(nav.tolist())
        winpct = (wins / trades * 100) if trades else float("nan")
        rows.append((name, trades, winpct, sh, cg, vol, dd, nav.iloc[-1]))

    for name, tr, wp, sh, cg, vol, dd, end in rows:
        wp_s = f"{wp:.0f}%" if not np.isnan(wp) else "  -"
        print(f"{name:<24}{tr:>7}{wp_s:>7}{sh:>8.2f}{cg*100:>7.1f}%"
              f"{vol*100:>6.1f}%{dd*100:>7.1f}%{end:>12,.0f}")


if __name__ == "__main__":
    main()
