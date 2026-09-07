"""Cross-check: rerun the baseline block in backtesting.py and diff it trade-by-trade.

Everything in this workspace is hand-rolled numpy/pandas. This script reruns the exact
same trade -- long the 18:00 ET reopen, flat at the 06:00 ET open, one contract -- inside
kernc/backtesting.py and compares the two, night by night, to see whether the hand-rolled
engine agrees with an independent implementation.

How the fill is expressed in each engine:

    hand-rolled          entry = open of the 18:00 bar, exit = open of the 06:00 bar
    backtesting.py       orders execute at the NEXT bar's open, so the entry order is
                         submitted on the last bar before 18:00 and the close is
                         submitted on the 05:55 bar -- which lands on the same two prints

Costs are applied OUTSIDE the framework (commission=0, then $0.50 subtracted per night by
hand). backtesting.py's commission is a fraction of trade value, which on a $24,000
notional cannot express "one tick = $0.50" without drifting as price changes -- and this
comparison is about fill semantics, not about who can model a tick better.

Part 2 reruns the +$200 take-profit with the framework's native limit handling. That one
is expected to DISAGREE, and by how much is the point: backtesting.py closes a TP when the
bar's high merely touches the level, while mnq_takeprofit_backtest.py requires a tick
THROUGH it (queue risk). Same data, same rule, two fill assumptions.

    python mnq_backtesting_py_crosscheck.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy

from mnq_exit_time_backtest import DPP, COST, sessions, pnl

DATA = (Path(__file__).resolve().parents[2] / "data")
TZ = "US/Eastern"
HOLD = 12
TP_DOLLARS = 200


def frame() -> pd.DataFrame:
    """5-min MNQ with the columns backtesting.py wants, RTH dropped for speed.

    Keeping 16:00-17:00 matters: the entry order has to be submitted on the last bar
    before the 18:00 reopen, and the 06:00 bar has to exist for the exit to fill there.
    """
    d = pd.read_parquet(DATA / "MNQ_5min_databento.parquet").sort_index()
    keep = d.index.hour.isin([16, 18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6])
    d = d[keep]
    d = d.rename(columns={"open": "Open", "high": "High", "low": "Low",
                          "close": "Close", "volume": "Volume"})
    return d[["Open", "High", "Low", "Close", "Volume"]]


def flags(idx: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """arm[i]: bar i is the last bar before an 18:00 open (order fills at 18:00).
    exit[i]: bar i is the last bar before the 06:00 boundary (close fills at 06:00)."""
    nxt_h = np.roll(idx.hour.to_numpy(), -1)
    nxt_m = np.roll(idx.minute.to_numpy(), -1)
    nxt_t = np.roll(idx.to_numpy(), -1)
    gap = nxt_t - idx.to_numpy()
    # The entry order must ride the weekend: for a Sunday 18:00 reopen the preceding bar
    # is Friday 16:55. Requiring a small gap here silently drops every Sunday night --
    # 339 of them -- which is how a framework's bar-to-bar order model quietly changes
    # the strategy. Allow up to 3 days for the arm, keep the tight check on the exit.
    arm = (nxt_h == 18) & (nxt_m == 0) & (gap <= np.timedelta64(3, "D"))
    ext = (nxt_h == 6) & (nxt_m == 0) & (gap <= np.timedelta64(125, "m"))
    arm[-1] = ext[-1] = False
    return arm, ext


class Block(Strategy):
    """Time-based only: no signal, no level, the clock is the whole strategy."""
    arm_sig: np.ndarray = None
    exit_sig: np.ndarray = None

    def init(self):
        self.arm = self.I(lambda: self.arm_sig.astype(float), name="arm", plot=False)
        self.ex = self.I(lambda: self.exit_sig.astype(float), name="exit", plot=False)

    def next(self):
        if self.ex[-1] and self.position:
            self.position.close()
        elif self.arm[-1] and not self.position:
            self.buy(size=1)


class BlockTP(Block):
    """Same, plus the framework's own limit exit at entry + TP (fills on touch)."""
    tp_points: float = TP_DOLLARS / DPP

    def next(self):
        if self.ex[-1] and self.position:
            self.position.close()
        elif self.arm[-1] and not self.position:
            self.buy(size=1)
        for t in self.trades:                    # set the TP once, on the entry bar
            if t.tp is None:
                t.tp = t.entry_price + self.tp_points


def run(df: pd.DataFrame, strat, arm, ext, plot_to: Path | None = None) -> pd.DataFrame:
    strat.arm_sig, strat.exit_sig = arm, ext
    bt = Backtest(df, strat, cash=200_000, commission=0.0, margin=1.0,
                  trade_on_close=False, exclusive_orders=False, finalize_trades=True)
    res = bt.run()
    if plot_to is not None:
        # Bokeh chokes on 284k bars; resample=True downsamples the candles for display
        # only -- the trades and equity plotted are still the full-resolution results.
        bt.plot(filename=str(plot_to), open_browser=False, resample=True,
                plot_drawdown=True, superimpose=False)
        print(f"  interactive chart -> {plot_to}")
        print(res.loc[["Start", "End", "Return [%]", "Sharpe Ratio", "Max. Drawdown [%]",
                       "# Trades", "Win Rate [%]", "Profit Factor", "Avg. Trade [%]",
                       "Max. Trade Duration"]].to_string())
    t = res["_trades"].copy()
    t["sess"] = pd.to_datetime(t["EntryTime"]).dt.tz_localize(None).dt.normalize()
    t["bt_pnl"] = (t["ExitPrice"] - t["EntryPrice"]) * DPP - COST
    return t.set_index("sess")


def strip_tz(s: pd.Series) -> pd.Series:
    s = s.copy()
    if getattr(s.index, "tz", None) is not None:
        s.index = s.index.tz_localize(None)
    return s


def compare(mine: pd.Series, theirs: pd.Series, label: str) -> None:
    mine, theirs = strip_tz(mine), strip_tz(theirs)
    j = pd.concat([mine.rename("hand"), theirs.rename("bt")], axis=1)
    both = j.dropna()
    d = both["bt"] - both["hand"]
    print(f"\n{label}")
    print(f"  nights   hand-rolled {mine.notna().sum():,}   backtesting.py "
          f"{theirs.notna().sum():,}   matched {len(both):,}")
    print(f"  $/night  hand-rolled {both['hand'].mean():>8.4f}   backtesting.py "
          f"{both['bt'].mean():>8.4f}   difference {d.mean():+.4f}")
    print(f"  total $  hand-rolled {both['hand'].sum():>8,.0f}   backtesting.py "
          f"{both['bt'].sum():>8,.0f}   difference {d.sum():+,.0f}")
    print(f"  per-night agreement: max |diff| ${d.abs().max():.4f}, "
          f"nights differing by more than 1 cent: {(d.abs() > 0.01).sum():,}")
    only_mine = mine.index.difference(theirs.index)
    only_bt = theirs.index.difference(mine.index)
    if len(only_mine) or len(only_bt):
        print(f"  unmatched nights: hand-only {len(only_mine)}, bt-only {len(only_bt)}")
        for s in list(only_mine)[:5]:
            print(f"    hand-only {s.date()}  ${mine[s]:,.2f}")
        for s in list(only_bt)[:5]:
            print(f"    bt-only   {s.date()}  ${theirs[s]:,.2f}")
    if (d.abs() > 0.01).any():
        w = d.abs().nlargest(5)
        print("  largest disagreements:")
        for s in w.index:
            print(f"    {s.date()}  hand ${both.loc[s, 'hand']:>9,.2f}   "
                  f"bt ${both.loc[s, 'bt']:>9,.2f}   diff ${d[s]:+,.2f}")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--plot", action="store_true",
                    help="write backtesting.py's own interactive Bokeh chart")
    args = ap.parse_args()

    df = frame()
    arm, ext = flags(df.index)
    print(f"bars fed to backtesting.py: {len(df):,}  |  entry signals: {arm.sum():,}  "
          f"exit signals: {ext.sum():,}")

    s = sessions("MNQ_5min_databento.parquet", [HOLD])
    hand = pnl(s, HOLD, None)

    reports = (Path(__file__).resolve().parents[2] / "reports")
    bt_base = run(df, Block, arm, ext,
                  plot_to=reports / "bt_plot_baseline.html" if args.plot else None)
    compare(hand, bt_base["bt_pnl"], "PART 1 -- BASELINE 18:00 -> 06:00, identical rule")

    # part 2: the same +$200 take profit under each engine's limit-fill assumption
    from mnq_takeprofit_backtest import load_paths, run as tp_run
    paths = load_paths("MNQ_5min_databento.parquet")
    mine_tp = tp_run(paths, TP_DOLLARS, None)[0]
    bt_tp = run(df, BlockTP, arm, ext)
    compare(mine_tp, bt_tp["bt_pnl"],
            f"PART 2 -- +${TP_DOLLARS} TAKE PROFIT (expected to differ: fill-on-touch "
            f"vs tick-through)")
    hit_bt = (bt_tp["ExitPrice"] - bt_tp["EntryPrice"] >= TP_DOLLARS / DPP - 1e-9).mean()
    print(f"  TP fill rate: backtesting.py {hit_bt*100:.1f}% of nights vs hand-rolled "
          f"23.6% (the queue-risk rule refuses the nights that only tag the level)")
    print(f"  headline effect: backtesting.py would report ${bt_tp['bt_pnl'].mean():.2f}"
          f"/night for this TP, the honest fill gives ${mine_tp.mean():.2f}, baseline "
          f"is ${hand.mean():.2f}")


if __name__ == "__main__":
    main()
