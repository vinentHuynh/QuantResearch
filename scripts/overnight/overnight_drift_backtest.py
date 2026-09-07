"""Backtest the overnight-drift edge on CME index proxies, auditable end-to-end.

The equity risk premium is earned mostly *overnight*: buy the index at the
session close, sell it at the next open, sit flat all day. This harvests that
gap and skips intraday risk. It is a long-only carry, not a trend model.

Sizing mirrors cme_time_series_momentum_backtest.py so an overnight sleeve is
directly comparable to (and combinable with) the TSMOM sleeves:

1. Overnight point move  = open[t] - close[t-1]   (realized during night t).
2. Size each sleeve to a fixed annual risk using the *point* volatility of the
   overnight move, so a market can trade through zero without blowing up.
3. Everything that scales the position is known at close[t-1] (vol and price are
   lagged), so the overnight-t return uses no data from night t itself.
4. Cost: entering at the close and exiting at the open is one round trip per
   session, charged on the deployed notional (leverage).

Data note: PWB serves SPX/NDX cash indices (ES/NQ proxies) and GC1/CL1
continuous series. This evaluates the signal; it does not model futures rolls,
multipliers, margin, funding, or exchange fees. Overnight drift is an equity
phenomenon — GC/CL are offered for completeness, not because the same rationale
holds.

    python overnight_drift_backtest.py --assets indices --start 2010-01-01
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

_env = (Path(__file__).resolve().parents[2] / ".env")
if _env.exists():
    for _l in _env.read_text(encoding="utf-8").splitlines():
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            _k, _v = _l.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

import pwb_toolbox.datasets as pwb_ds
from pwb_toolbox.performance.metrics import (
    annualized_volatility, cagr, max_drawdown, sharpe_ratio,
)

# Reuse the TSMOM market map + model so the correlation check is apples-to-apples.
from cme_time_series_momentum_backtest import (
    MARKETS, ASSET_GROUPS, load_closes, build_market_model,
)


def load_ohlc(names: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    """Load open+close per market (one dataset read per source)."""
    grouped: dict[str, list[str]] = {}
    for n in names:
        grouped.setdefault(MARKETS[n].dataset, []).append(n)
    out: dict[str, pd.DataFrame] = {}
    for dataset, ns in grouped.items():
        syms = [MARKETS[n].symbol for n in ns]
        raw = pwb_ds.load_dataset(dataset, symbols=syms).copy()
        raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
        for c in ("open", "high", "low", "close"):
            if c in raw.columns:
                raw[c] = pd.to_numeric(raw[c], errors="coerce")
        raw = raw.dropna(subset=["symbol", "date", "open", "close"])
        for n in ns:
            cols = [c for c in ("open", "high", "low", "close") if c in raw.columns]
            d = (raw.loc[raw["symbol"].eq(MARKETS[n].symbol)]
                 .drop_duplicates("date", keep="last")
                 .sort_values("date").set_index("date")[cols]
                 .astype(float))
            if d.empty:
                raise ValueError(f"no data for {n}")
            out[n] = d
    return out


def session_direction(d: pd.DataFrame, rule: str, strong_thr: float) -> pd.Series:
    """Per-night direction (-1/0/+1) from the PRIOR regular session's close.

    The overnight of day t (open[t] vs close[t-1]) is decided by the session of
    day t-1, so the raw daily signal is shifted forward one day: nothing used is
    realized after close[t-1].
    """
    move = d["close"] - d["open"]                  # session close vs session open
    if {"high", "low"}.issubset(d.columns):
        rng = (d["high"] - d["low"]).replace(0.0, np.nan)
        loc = (d["close"] - d["low"]) / rng        # 0..1, 1 = closed at the high
    else:
        loc = pd.Series(0.5, index=d.index)
    if rule == "always":
        raw = pd.Series(1.0, index=d.index)
    elif rule == "up_long":
        raw = (move > 0).astype(float)
    elif rule == "down_long":
        raw = (move < 0).astype(float)
    elif rule == "long_short":
        raw = np.sign(move)
    elif rule == "strong_long":
        raw = (loc >= strong_thr).astype(float)
    else:
        raise ValueError(f"unknown rule {rule}")
    return raw.shift(1).fillna(0.0)                 # apply to the NEXT night


def sleeve_returns(d: pd.DataFrame, point_move: pd.Series, vol_window: int,
                   asset_vol: float, max_lev: float, round_trip_bps: float,
                   direction: pd.Series | None = None):
    """Vol-targeted sleeve for a daily point-move series, optionally directional.

    point_move is the P&L series being harvested (overnight, intraday, or full
    day). Sizing uses the *lagged* volatility of that series and lagged price, so
    the return on day t uses nothing realized on day t. `direction` (-1/0/+1,
    already lagged) scales the position; None means always long (the original).
    """
    close = d["close"]
    pvol = point_move.rolling(vol_window, min_periods=vol_window).std(ddof=0)
    pvol_known = pvol.shift(1)                      # known at close[t-1]
    prev_abs = close.shift(1).abs()
    daily_risk = asset_vol / np.sqrt(252)

    magnitude = daily_risk / pvol_known            # positive sizing (>=0)
    notional = (magnitude * prev_abs).clip(0.0, max_lev)
    exposure_capped = (notional / prev_abs.replace(0.0, np.nan)).where(
        prev_abs.ne(0.0), magnitude)

    if direction is None:
        direction = pd.Series(1.0, index=d.index)
    direction = direction.reindex(close.index).fillna(0.0)
    active = direction.ne(0.0)

    gross = (exposure_capped * direction * point_move).fillna(0.0)
    deployed = (notional * active.astype(float)).fillna(0.0)
    cost = deployed * (round_trip_bps / 1e4)        # round trip per traded night
    net = gross - cost
    return gross, net, deployed


def perf(returns: pd.Series, bal: float) -> dict:
    nav = (bal * (1 + returns.fillna(0.0)).cumprod())
    norm = (nav / bal).tolist()
    depth, _ = max_drawdown(norm)
    return {"end": nav.iloc[-1], "ret": nav.iloc[-1] / bal - 1,
            "cagr": cagr(norm), "sharpe": sharpe_ratio(norm),
            "vol": annualized_volatility(norm), "maxdd": abs(depth)}


def line(name, s):
    return (f"{name:<22} end=${s['end']:>11,.0f}  ret={s['ret']*100:>7.1f}%  "
            f"CAGR={s['cagr']*100:>6.2f}%  Sharpe={s['sharpe']:>5.2f}  "
            f"Vol={s['vol']*100:>5.1f}%  MaxDD={s['maxdd']*100:>5.1f}%")


def portfolio(models: dict, key: str, start, end) -> pd.Series:
    r = pd.concat({n: m[key] for n, m in models.items()}, axis=1).mean(axis=1)
    r = r[r.index >= start]
    if end is not None:
        r = r[r.index <= end]
    return r


def main() -> None:
    ap = argparse.ArgumentParser(description="Overnight-drift harvest on CME proxies.")
    ap.add_argument("--assets", choices=ASSET_GROUPS, default="indices")
    ap.add_argument("--balance", type=float, default=100_000.0)
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--vol-window", type=int, default=60)
    ap.add_argument("--asset-vol", type=float, default=0.20)
    ap.add_argument("--max-leverage", type=float, default=2.0)
    ap.add_argument("--round-trip-cost-bps", type=float, default=1.0)
    ap.add_argument("--strong-threshold", type=float, default=0.6,
                    help="close-in-range cutoff for the 'strong close' rule")
    args = ap.parse_args()

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end) if args.end else None
    names = ASSET_GROUPS[args.assets]
    ohlc = load_ohlc(names)

    # three point-move definitions, same sizing/cost basis
    models = {}
    for n in names:
        d = ohlc[n]
        on = d["open"] - d["close"].shift(1)          # overnight
        idr = d["close"] - d["open"]                   # intraday
        full = d["close"].diff()                       # full day (buy & hold)
        g_on, n_on, notl = sleeve_returns(d, on, args.vol_window, args.asset_vol,
                                          args.max_leverage, args.round_trip_cost_bps)
        g_id, n_id, _ = sleeve_returns(d, idr, args.vol_window, args.asset_vol,
                                       args.max_leverage, args.round_trip_cost_bps)
        g_bh, n_bh, _ = sleeve_returns(d, full, args.vol_window, args.asset_vol,
                                       args.max_leverage, args.round_trip_cost_bps)
        models[n] = {"on_net": n_on, "on_gross": g_on, "id_net": n_id,
                     "bh_net": n_bh, "notional": notl}

    on_net = portfolio(models, "on_net", start, end)
    on_gross = portfolio(models, "on_gross", start, end)
    id_net = portfolio(models, "id_net", start, end)
    bh_net = portfolio(models, "bh_net", start, end)

    print("\nOVERNIGHT DRIFT | CME INDEX PROXIES (vol-targeted, long-only)")
    print("=" * 78)
    print(f"Period: {on_net.index[0].date()} -> {on_net.index[-1].date()} "
          f"({len(on_net):,} sessions) | markets: {', '.join(names)}")
    print(f"Vol target {args.asset_vol:.0%} | max {args.max_leverage:.1f}x | "
          f"vol window {args.vol_window} | round-trip cost {args.round_trip_cost_bps} bps\n")
    print(line("Overnight (net)", perf(on_net, args.balance)))
    print(line("Overnight (gross)", perf(on_gross, args.balance)))
    print(line("Full-day buy&hold", perf(bh_net, args.balance)))
    print(line("Intraday only", perf(id_net, args.balance)))

    print("\nPER-SLEEVE (overnight, net)")
    for n in names:
        s = models[n]["on_net"]
        s = s[s.index >= start]
        if end is not None:
            s = s[s.index <= end]
        print("  " + line(n, perf(s, args.balance)))

    print("\nCALENDAR RETURNS (%)")
    cal = pd.DataFrame({"Overnight": on_net, "Buy&hold": bh_net, "Intraday": id_net})
    cal = cal.groupby(lambda x: x.year).apply(lambda f: (1 + f).prod() - 1)
    print((cal * 100).round(2).to_string())

    print("\nNY-CLOSE CONDITIONAL RULES (overnight portfolio, net, same sizing/cost)")
    print(f"{'rule':<24}{'Sharpe':>8}{'CAGR':>8}{'Vol':>7}{'MaxDD':>8}{'%nights':>9}")
    RULES = {
        "always (baseline)": "always",
        "long after up close": "up_long",
        "long after down close": "down_long",
        "long up / short down": "long_short",
        "strong close only": "strong_long",
    }
    for label, rule in RULES.items():
        rr, active_frac = [], []
        for n in names:
            d = ohlc[n]
            on = d["open"] - d["close"].shift(1)
            direction = session_direction(d, rule, args.strong_threshold)
            _, net, _ = sleeve_returns(d, on, args.vol_window, args.asset_vol,
                                       args.max_leverage, args.round_trip_cost_bps,
                                       direction)
            rr.append(net)
            active_frac.append(direction.ne(0.0))
        p = pd.concat(rr, axis=1).mean(axis=1)
        act = pd.concat(active_frac, axis=1).any(axis=1)
        p = p[p.index >= start]
        act = act.reindex(p.index).fillna(False)
        if end is not None:
            p = p[p.index <= end]; act = act[act.index <= end]
        s = perf(p, args.balance)
        print(f"{label:<24}{s['sharpe']:>8.2f}{s['cagr']*100:>7.1f}%"
              f"{s['vol']*100:>6.1f}%{s['maxdd']*100:>7.1f}%{act.mean()*100:>8.0f}%")

    print("\nCOST SENSITIVITY (overnight portfolio Sharpe / CAGR)")
    print(f"{'round-trip bps':<16}{'Sharpe':>8}{'CAGR':>8}")
    for bps in (0.0, 0.5, 1.0, 2.0, 5.0):
        rr = []
        for n in names:
            d = ohlc[n]
            on = d["open"] - d["close"].shift(1)
            _, net, _ = sleeve_returns(d, on, args.vol_window, args.asset_vol,
                                       args.max_leverage, bps)
            rr.append(net)
        p = pd.concat(rr, axis=1).mean(axis=1)
        p = p[p.index >= start]
        if end is not None:
            p = p[p.index <= end]
        s = perf(p, args.balance)
        print(f"{bps:<16.1f}{s['sharpe']:>8.2f}{s['cagr']*100:>7.1f}%")

    # correlation vs TSMOM (same markets), to prove diversification
    try:
        closes = load_closes(names)
        tsm = {n: build_market_model(closes[n], (20, 60, 120, 252), 60, 0.20, 2.0)
               for n in names}
        tsm_ret = pd.concat(
            {n: (tsm[n]["held_point_exposure"] * tsm[n]["price_change"])
             for n in names}, axis=1).mean(axis=1)
        joined = pd.concat({"on": on_net, "tsmom": tsm_ret}, axis=1).dropna()
        corr = joined["on"].corr(joined["tsmom"])
        blend = 0.5 * joined["on"] + 0.5 * joined["tsmom"]
        print(f"\nDIVERSIFICATION vs TSMOM (same markets, {len(joined):,} shared days)")
        print(f"  correlation(overnight, TSMOM) = {corr:+.2f}")
        print("  " + line("50/50 blend", perf(blend, args.balance)))
        print("  " + line("TSMOM alone", perf(joined['tsmom'], args.balance)))
    except Exception as e:  # keep the core report even if TSMOM reuse fails
        print(f"\n(TSMOM correlation skipped: {type(e).__name__}: {e})")


if __name__ == "__main__":
    main()
