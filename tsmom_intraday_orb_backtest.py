"""Dedicated Python backtest for cme_tsmom_intraday_orb_strategy.pine.

The available Papers With Backtest intraday cache contains SPY and QQQ rather
than contract-level MES/MNQ futures. SPY supplies MES intraday signals and QQQ
supplies MNQ signals; PWB daily SPX/NDX history supplies the four-speed TSMOM
filter and translates percentage moves into approximate futures dollars.

Rules reproduced from the Pine strategy:
  * prior completed daily 20/60/120/252 TSMOM score;
  * trade only when score >= +0.50 or <= -0.50;
  * first 15 RTH minutes form the opening range;
  * enter at the close of the first later execution bar closing beyond the
    range in the permitted direction;
  * stop at the opposite opening-range boundary, target 2R;
  * whole micro contracts with no more than the dollar risk cap;
  * skip if one micro exceeds the cap, one attempt per day, flat by RTH close.

This tests the signal logic but remains a proxy. Actual futures validation must
use contract-mapped CME data because ETF/cash-index sessions do not include the
futures basis, Globex price discovery, rolls, or actual fills.

Usage:
  .venv\\Scripts\\python.exe tsmom_intraday_orb_backtest.py
  .venv\\Scripts\\python.exe tsmom_intraday_orb_backtest.py --risk 75
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from intraday_strategy_screen import (
    BASE_EQUITY,
    DATA,
    MARKETS,
    REPORTS,
    daily_track,
    load_index_data,
    load_intraday,
    make_trade,
    max_drawdown_dollars,
    profit_factor,
    size_trades,
    to_15min,
)


STRATEGY = "orb15_tsmom_confirm"


def generate_exact_trades(market: str, five: pd.DataFrame, daily_score: pd.Series,
                          bar_minutes: int, opening_range_minutes: int):
    """Generate the Pine strategy's trades on either 5- or 15-minute bars."""
    bars = five if bar_minutes == 5 else to_15min(five)
    opening_bar_count = opening_range_minutes // bar_minutes
    if opening_bar_count < 1 or opening_range_minutes % bar_minutes:
        raise ValueError("opening range must be a positive multiple of bar minutes")
    strategy_name = f"orb{opening_range_minutes}_tsmom_{bar_minutes}m"
    records = []
    calendar = pd.DatetimeIndex(sorted(five.index.normalize().unique()))
    for day, session in bars.groupby(bars.index.normalize()):
        session = session.sort_index()
        if len(session) <= opening_bar_count + 1:
            continue
        score = daily_score.get(day, np.nan)
        direction = 1 if score >= 0.50 else (-1 if score <= -0.50 else 0)
        if direction == 0:
            continue
        opening = session.iloc[:opening_bar_count]
        opening_high = float(opening["high"].max())
        opening_low = float(opening["low"].min())
        rest = session.iloc[opening_bar_count:]
        entry_bars = rest.between_time("09:45", "14:59")
        for timestamp, bar in entry_bars.iterrows():
            close = float(bar["close"])
            if not ((direction > 0 and close > opening_high) or
                    (direction < 0 and close < opening_low)):
                continue
            path = rest[rest.index > timestamp]
            if path.empty:
                break
            if direction > 0:
                risk = close - opening_low
                trade = make_trade(day, strategy_name, market, 1, close,
                                   opening_low, close + 2.0 * risk, path)
            else:
                risk = opening_high - close
                trade = make_trade(day, strategy_name, market, -1, close,
                                   opening_high, close - 2.0 * risk, path)
            if trade is not None:
                records.append(trade.__dict__)
            break
    trades = pd.DataFrame(records)
    if not trades.empty:
        trades["date"] = pd.to_datetime(trades["date"])
    return trades, calendar


def longest_losing_streak(values: pd.Series) -> int:
    longest = current = 0
    for value in values:
        if value < 0:
            current += 1
            longest = max(longest, current)
        elif value != 0:
            current = 0
    return longest


def summarize_period(trades: pd.DataFrame) -> dict[str, float]:
    if trades.empty:
        return {
            "trades": 0, "win_pct": np.nan, "avg_pnl": np.nan,
            "profit_factor": np.nan, "net_pnl": 0.0,
        }
    return {
        "trades": len(trades),
        "win_pct": 100.0 * trades["net_pnl"].gt(0).mean(),
        "avg_pnl": float(trades["net_pnl"].mean()),
        "profit_factor": profit_factor(trades["net_pnl"]),
        "net_pnl": float(trades["net_pnl"].sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="TSMOM-filtered intraday ORB backtest")
    parser.add_argument("--bar-minutes", type=int, choices=(5, 15), default=5,
                        help="execution bar timeframe")
    parser.add_argument("--opening-range-minutes", type=int, choices=(5, 15, 30), default=15,
                        help="minutes used to form the RTH opening range")
    parser.add_argument("--risk", type=float, default=75.0,
                        help="maximum stop risk per trade before costs")
    parser.add_argument("--mes-cost", type=float, default=5.0,
                        help="MES all-in round-trip cost per contract")
    parser.add_argument("--mnq-cost", type=float, default=3.5,
                        help="MNQ all-in round-trip cost per contract")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--holdout", default="2025-07-01")
    args = parser.parse_args()
    if args.risk <= 0 or args.mes_cost < 0 or args.mnq_cost < 0:
        parser.error("risk must be positive and costs cannot be negative")
    if args.opening_range_minutes % args.bar_minutes:
        parser.error("opening range must be a multiple of bar timeframe")

    start = pd.Timestamp(args.start)
    holdout = pd.Timestamp(args.holdout)
    index_open, daily_scores = load_index_data()
    cost_by_market = {"MES": args.mes_cost, "MNQ": args.mnq_cost}

    reports: list[dict] = []
    print(f"\nTSMOM-FILTERED ORB | {args.bar_minutes}-MINUTE EXECUTION")
    print("=" * 88)
    print(f"PWB proxies | start {start.date()} | holdout {holdout.date()} | "
          f"risk <= ${args.risk:.0f} | target 2R")
    print("SPY + SPX -> MES approximation; QQQ + NDX -> MNQ approximation\n")

    for market, info in MARKETS.items():
        raw, calendar = generate_exact_trades(
            market, load_intraday(info["etf"]), daily_scores[info["index"]],
            args.bar_minutes, args.opening_range_minutes,
        )
        raw = raw[raw["date"] >= start]
        sized = size_trades(raw, index_open, args.risk, cost_by_market[market])
        calendar = calendar[calendar >= start]
        daily = daily_track(sized, calendar)
        tradable = sized[sized["tradable"]].copy()
        recent = tradable[tradable["date"] >= holdout]
        full_stats = summarize_period(tradable)
        holdout_stats = summarize_period(recent)
        average_winner = tradable.loc[tradable["net_pnl"] > 0, "net_pnl"].mean()
        average_loser = tradable.loc[tradable["net_pnl"] < 0, "net_pnl"].mean()
        average_risk = (tradable["risk_1_micro"] * tradable["contracts"]).mean()
        maximum_risk = (tradable["risk_1_micro"] * tradable["contracts"]).max()
        max_dd = max_drawdown_dollars(daily["pnl"])

        report = {
            "market": market,
            "proxy": info["etf"],
            "start": calendar.min(),
            "end": calendar.max(),
            "raw_setups": len(sized),
            "tradable_setups": len(tradable),
            "risk_skips": int((~sized["tradable"]).sum()),
            **full_stats,
            "average_winner": average_winner,
            "average_loser": average_loser,
            "average_stop_risk": average_risk,
            "maximum_stop_risk": maximum_risk,
            "max_drawdown": max_dd,
            "longest_losing_streak": longest_losing_streak(tradable["net_pnl"]),
            "holdout_trades": holdout_stats["trades"],
            "holdout_win_pct": holdout_stats["win_pct"],
            "holdout_avg_pnl": holdout_stats["avg_pnl"],
            "holdout_profit_factor": holdout_stats["profit_factor"],
            "holdout_net_pnl": holdout_stats["net_pnl"],
        }
        reports.append(report)

        print(f"{market} ({info['etf']} proxy)")
        print(f"  setup signals {len(sized):>4} | tradable {len(tradable):>4} | "
              f"risk skips {int((~sized['tradable']).sum()):>4}")
        print(f"  win {full_stats['win_pct']:>5.1f}% | avg ${full_stats['avg_pnl']:>7.2f} | "
              f"PF {full_stats['profit_factor']:>5.2f} | net ${full_stats['net_pnl']:>8.0f} | "
              f"max DD ${max_dd:>7.0f}")
        print(f"  holdout N {holdout_stats['trades']:>3} | avg ${holdout_stats['avg_pnl']:>7.2f} | "
              f"PF {holdout_stats['profit_factor']:>5.2f} | net ${holdout_stats['net_pnl']:>7.0f}")
        print()

        annual = tradable.assign(year=tradable["date"].dt.year).groupby("year").agg(
            trades=("net_pnl", "size"),
            win_pct=("net_pnl", lambda x: 100.0 * x.gt(0).mean()),
            average_pnl=("net_pnl", "mean"),
            net_pnl=("net_pnl", "sum"),
        )
        suffix = f"{args.bar_minutes}m"
        annual.to_csv(REPORTS / f"tsmom_intraday_orb_{market.lower()}_{suffix}_annual.csv")
        sized.to_csv(DATA / f"tsmom_intraday_orb_{market.lower()}_{suffix}_trades.csv", index=False)
        daily.assign(equity=BASE_EQUITY + daily["pnl"].cumsum()).to_csv(
            DATA / f"tsmom_intraday_orb_{market.lower()}_{suffix}_daily.csv", index_label="date"
        )

    REPORTS.mkdir(exist_ok=True)
    summary_path = REPORTS / f"tsmom_intraday_orb_{args.bar_minutes}m_backtest.csv"
    pd.DataFrame(reports).to_csv(summary_path, index=False)
    print(f"Saved summary: {summary_path}")
    print(f"Saved per-market trades and daily equity under: {DATA}")


if __name__ == "__main__":
    main()
