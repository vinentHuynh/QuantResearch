"""Statistical report suite over the cached CME Group daily panel.

Reads `data/cme_daily.parquet` (produced by `fetch_cme_data.py`) and writes a
set of CSVs plus a readable markdown report to `reports/`.

Sections
--------
1. coverage      rows, span, gaps, and data-quality flags per market
2. moments       annualized return/vol/Sharpe, skew, kurtosis, VaR/CVaR, drawdown
3. dependence    ADF, lag-1 autocorrelation, Ljung-Box on returns and squared
                 returns, variance ratios with Lo-MacKinlay z-stats, Hurst
4. correlation   daily-return correlation matrix on the common window
5. seasonality   day-of-week and month-of-year mean returns with t-stats
6. regimes       annualized volatility by calendar year, current vol percentile
7. tails         worst days and the deepest drawdowns per market

Returns are simple (P_t / P_{t-1} - 1) and are set to NaN whenever either price
is non-positive, so April 2020 negative WTI does not poison the sample. That
gap is reported rather than silently filled.

Usage
-----
    python cme_stats_report.py                          # everything, full history
    python cme_stats_report.py --start 2005-01-01
    python cme_stats_report.py --markets ES,NQ,CL,GC,ZN
    python cme_stats_report.py --sectors energy,metals --min-years 10
    python cme_stats_report.py --include-reference --plots
"""

from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.stattools import adfuller

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

PANEL_PATH = (Path(__file__).resolve().parents[2] / "data") / "cme_daily.parquet"
REPORT_DIR = (Path(__file__).resolve().parents[2] / "reports")
TRADING_DAYS = 252


# --------------------------------------------------------------------------
# panel handling
# --------------------------------------------------------------------------
def load_panel(path: Path, args: argparse.Namespace) -> pd.DataFrame:
    if not path.exists():
        raise SystemExit(f"{path} not found — run: python fetch_cme_data.py --include-reference")
    panel = pd.read_parquet(path)
    panel["date"] = pd.to_datetime(panel["date"])

    if not args.include_reference:
        panel = panel.loc[~panel["is_reference"].astype(bool)]
    if args.sectors:
        wanted = {s.strip() for s in args.sectors.split(",")}
        panel = panel.loc[panel["sector"].isin(wanted)]
    if args.markets:
        wanted = {m.strip().upper() for m in args.markets.split(",")}
        panel = panel.loc[panel["market"].str.upper().isin(wanted)]
    if args.start:
        panel = panel.loc[panel["date"] >= pd.Timestamp(args.start)]
    if args.end:
        panel = panel.loc[panel["date"] <= pd.Timestamp(args.end)]
    if panel.empty:
        raise SystemExit("no rows survived the filters")

    if args.min_years:
        span = panel.groupby("market")["date"].agg(lambda s: (s.max() - s.min()).days / 365.25)
        keep = span[span >= args.min_years].index
        dropped = sorted(set(span.index) - set(keep))
        if dropped:
            print(f"[filter] dropped for <{args.min_years}y history: {', '.join(dropped)}")
        panel = panel.loc[panel["market"].isin(keep)]
    if panel.empty:
        raise SystemExit("no markets cleared --min-years")
    return panel.sort_values(["market", "date"]).reset_index(drop=True)


def close_matrix(panel: pd.DataFrame) -> pd.DataFrame:
    return panel.pivot_table(index="date", columns="market", values="close", aggfunc="last").sort_index()


def return_matrix(closes: pd.DataFrame) -> pd.DataFrame:
    """Simple returns, blanked wherever either endpoint is non-positive."""
    positive = closes.where(closes > 0)
    return positive.pct_change().where(positive.notna() & positive.shift().notna())


def scrub_glitches(closes: pd.DataFrame, threshold: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Blank isolated bad prints: a huge move that fully reverses the next day.

    PWB's vendor feed carries occasional single-day corruptions (cocoa printed
    0.91 between two 5000-handle closes on 2025-11-25). A real crash does not
    round-trip in one session, so requiring the reversal keeps genuine gap moves
    such as April 2020 WTI intact. Returns the cleaned closes and a scrub log.
    """
    cleaned = closes.copy()
    log = []
    for market in closes.columns:
        series = closes[market].dropna()
        if len(series) < 3:
            continue
        ret = series.pct_change()
        nxt = ret.shift(-1)
        # Big move, opposite-signed big move next day, and the pair nets to ~0.
        round_trip = (
            (ret.abs() > threshold)
            & (nxt.abs() > threshold)
            & (np.sign(ret) != np.sign(nxt))
            & (((1 + ret) * (1 + nxt) - 1).abs() < threshold / 2)
        )
        for date in ret.index[round_trip.fillna(False)]:
            log.append(
                {
                    "market": market,
                    "date": date.date(),
                    "bad_close": round(float(series.loc[date]), 4),
                    "prev_close": round(float(series.shift().loc[date]), 4),
                    "next_close": round(float(series.shift(-1).loc[date]), 4),
                    "move_pct": round(100 * float(ret.loc[date]), 1),
                }
            )
            cleaned.loc[date, market] = np.nan
    return cleaned, pd.DataFrame(log)


def suspect_table(rets: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Markets still carrying implausible moves after scrubbing."""
    rows = []
    for market in rets.columns:
        ret = rets[market].dropna()
        if ret.empty:
            continue
        worst = float(ret.abs().max())
        if worst > threshold:
            date = ret.abs().idxmax()
            rows.append(
                {
                    "market": market,
                    "max_abs_move_pct": round(100 * worst, 1),
                    "on": date.date(),
                    "moves_gt_threshold": int((ret.abs() > threshold).sum()),
                }
            )
    return pd.DataFrame(rows).sort_values("max_abs_move_pct", ascending=False).reset_index(drop=True)


def meta_of(panel: pd.DataFrame) -> pd.DataFrame:
    cols = ["market", "name", "exchange", "sector", "symbol", "proxy", "is_reference"]
    return panel[cols].drop_duplicates("market").set_index("market")


# --------------------------------------------------------------------------
# 1. coverage and data quality
# --------------------------------------------------------------------------
def coverage_table(panel: pd.DataFrame, closes: pd.DataFrame, rets: pd.DataFrame) -> pd.DataFrame:
    meta = meta_of(panel)
    rows = []
    for market in rets.columns:
        close = closes[market].dropna()  # post-scrub, so the flags describe what the stats saw
        if close.empty:
            continue
        span_years = max((close.index[-1] - close.index[0]).days / 365.25, 1e-9)
        ret = rets[market].dropna()
        gaps = close.index.to_series().diff().dt.days
        flat = (close.diff() == 0).sum()
        jumps = (ret.abs() > 0.25).sum()
        rows.append(
            {
                "market": market,
                "name": meta.at[market, "name"],
                "exchange": meta.at[market, "exchange"],
                "sector": meta.at[market, "sector"],
                "proxy": meta.at[market, "symbol"],
                "obs": len(close),
                "start": close.index[0].date(),
                "end": close.index[-1].date(),
                "years": round(span_years, 1),
                "obs_per_year": round(len(close) / span_years, 1),
                "gaps_gt_5d": int((gaps > 5).sum()),
                "max_gap_d": int(gaps.max() or 0),
                "flat_closes": int(flat),
                "flat_pct": round(100 * flat / max(len(close) - 1, 1), 2),
                "nonpos_closes": int((close <= 0).sum()),
                "returns_usable": len(ret),
                "abs_move_gt_25pct": int(jumps),
            }
        )
    return pd.DataFrame(rows).sort_values(["sector", "market"]).reset_index(drop=True)


# --------------------------------------------------------------------------
# 2. distribution moments and risk
# --------------------------------------------------------------------------
def max_drawdown(equity: pd.Series) -> tuple[float, pd.Timestamp | None, int]:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    trough = dd.idxmin() if len(dd) else None
    depth = float(dd.min()) if len(dd) else np.nan
    underwater = int((dd < 0).sum())
    return depth, trough, underwater


def moments_table(panel: pd.DataFrame, rets: pd.DataFrame, rf: float) -> pd.DataFrame:
    meta = meta_of(panel)
    daily_rf = rf / TRADING_DAYS
    rows = []
    for market in rets.columns:
        ret = rets[market].dropna()
        if len(ret) < 60:
            continue
        equity = (1 + ret).cumprod()
        years = len(ret) / TRADING_DAYS
        cagr = equity.iloc[-1] ** (1 / years) - 1 if equity.iloc[-1] > 0 else np.nan
        vol = ret.std(ddof=1) * np.sqrt(TRADING_DAYS)
        downside = ret[ret < 0].std(ddof=1) * np.sqrt(TRADING_DAYS)
        sharpe = (ret.mean() - daily_rf) / ret.std(ddof=1) * np.sqrt(TRADING_DAYS)
        depth, trough, underwater = max_drawdown(equity)
        jb_stat, jb_p = stats.jarque_bera(ret)
        var95 = float(np.percentile(ret, 5))
        rows.append(
            {
                "market": market,
                "name": meta.at[market, "name"],
                "sector": meta.at[market, "sector"],
                "obs": len(ret),
                "cagr_pct": round(100 * cagr, 2),
                "ann_vol_pct": round(100 * vol, 2),
                "sharpe": round(sharpe, 3),
                "sortino": round((ret.mean() - daily_rf) * TRADING_DAYS / downside, 3) if downside > 0 else np.nan,
                "max_dd_pct": round(100 * depth, 1),
                "calmar": round(cagr / abs(depth), 3) if depth and not np.isnan(cagr) else np.nan,
                "dd_trough": trough.date() if trough is not None else None,
                "pct_days_underwater": round(100 * underwater / len(ret), 1),
                "skew": round(float(stats.skew(ret)), 3),
                "excess_kurt": round(float(stats.kurtosis(ret)), 2),
                "jarque_bera_p": f"{jb_p:.2e}",
                "hit_rate_pct": round(100 * float((ret > 0).mean()), 2),
                "best_day_pct": round(100 * float(ret.max()), 2),
                "worst_day_pct": round(100 * float(ret.min()), 2),
                "var95_pct": round(100 * var95, 2),
                "cvar95_pct": round(100 * float(ret[ret <= var95].mean()), 2),
            }
        )
    return pd.DataFrame(rows).sort_values("sharpe", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------
# 3. dependence structure: memory, mean reversion, vol clustering
# --------------------------------------------------------------------------
def variance_ratio(ret: np.ndarray, q: int) -> tuple[float, float]:
    """Lo-MacKinlay variance ratio with the heteroskedasticity-robust z-stat.

    VR > 1 means returns trend at horizon q; VR < 1 means they mean-revert.
    """
    n = len(ret)
    if n < q * 10:
        return np.nan, np.nan
    mu = ret.mean()
    var1 = ((ret - mu) ** 2).sum() / (n - 1)
    if var1 <= 0:
        return np.nan, np.nan
    # Overlapping q-period variance with Lo-MacKinlay's small-sample correction.
    agg = np.convolve(ret, np.ones(q), mode="valid")
    m = q * (n - q + 1) * (1 - q / n)
    varq = ((agg - q * mu) ** 2).sum() / m
    vr = varq / var1

    dev2 = (ret - mu) ** 2
    den = dev2.sum() ** 2
    theta = 0.0
    for j in range(1, q):
        num = (dev2[j:] * dev2[: n - j]).sum()
        delta = n * num / den if den > 0 else 0.0
        theta += (2 * (q - j) / q) ** 2 * delta
    z = np.sqrt(n) * (vr - 1) / np.sqrt(theta) if theta > 0 else np.nan
    return vr, z


def hurst_exponent(ret: np.ndarray, max_lag: int = 100) -> float:
    """Hurst via the aggregated-variance slope. 0.5 = random walk."""
    lags = np.unique(np.logspace(0, np.log10(min(max_lag, len(ret) // 10)), 20).astype(int))
    lags = lags[lags >= 2]
    if len(lags) < 5:
        return np.nan
    series = np.cumsum(ret - ret.mean())
    taus = []
    for lag in lags:
        diff = series[lag:] - series[:-lag]
        taus.append(np.sqrt(np.mean(diff**2)))
    taus = np.array(taus)
    ok = taus > 0
    if ok.sum() < 5:
        return np.nan
    slope = np.polyfit(np.log(lags[ok]), np.log(taus[ok]), 1)[0]
    return float(slope)


def dependence_table(panel: pd.DataFrame, closes: pd.DataFrame, rets: pd.DataFrame) -> pd.DataFrame:
    meta = meta_of(panel)
    rows = []
    for market in rets.columns:
        ret = rets[market].dropna()
        if len(ret) < 500:
            continue
        arr = ret.to_numpy()
        price = closes[market].dropna()
        logp = np.log(price[price > 0])

        adf_p_price = adfuller(logp.to_numpy(), maxlag=10, regression="c", autolag=None)[1]
        adf_p_ret = adfuller(arr, maxlag=10, regression="c", autolag=None)[1]
        lb_ret = acorr_ljungbox(arr, lags=[10], return_df=True)["lb_pvalue"].iloc[0]
        lb_sq = acorr_ljungbox(arr**2, lags=[10], return_df=True)["lb_pvalue"].iloc[0]

        row = {
            "market": market,
            "name": meta.at[market, "name"],
            "sector": meta.at[market, "sector"],
            "obs": len(ret),
            "ac1": round(float(pd.Series(arr).autocorr(1)), 4),
            "ac5": round(float(pd.Series(arr).autocorr(5)), 4),
            "ljungbox10_ret_p": f"{lb_ret:.3g}",
            "ljungbox10_sq_p": f"{lb_sq:.3g}",
            "adf_p_logprice": f"{adf_p_price:.3g}",
            "adf_p_return": f"{adf_p_ret:.3g}",
            "hurst": round(hurst_exponent(arr), 3),
        }
        for q in (5, 21, 63):
            vr, z = variance_ratio(arr, q)
            row[f"vr{q}"] = round(vr, 3) if vr == vr else np.nan
            row[f"vr{q}_z"] = round(z, 2) if z == z else np.nan
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["sector", "market"]).reset_index(drop=True)


# --------------------------------------------------------------------------
# 4. correlation
# --------------------------------------------------------------------------
def correlation_tables(rets: pd.DataFrame, min_overlap: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    corr = rets.corr(min_periods=min_overlap)
    overlap = rets.notna().astype(int).T.dot(rets.notna().astype(int))

    pairs = []
    cols = list(corr.columns)
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            value = corr.at[a, b]
            if pd.notna(value):
                pairs.append({"a": a, "b": b, "corr": round(float(value), 3), "overlap_obs": int(overlap.at[a, b])})
    pair_table = pd.DataFrame(pairs).sort_values("corr", ascending=False).reset_index(drop=True)
    return corr.round(3), pair_table, overlap


def rolling_beta_to(rets: pd.DataFrame, anchor: str, window: int) -> pd.DataFrame:
    if anchor not in rets.columns:
        return pd.DataFrame()
    base = rets[anchor]
    out = {}
    for market in rets.columns:
        if market == anchor:
            continue
        out[market] = rets[market].rolling(window, min_periods=window // 2).corr(base)
    return pd.DataFrame(out)


# --------------------------------------------------------------------------
# 5. seasonality
# --------------------------------------------------------------------------
def _mean_with_t(sample: pd.Series) -> tuple[float, float, int]:
    sample = sample.dropna()
    n = len(sample)
    if n < 20:
        return np.nan, np.nan, n
    t = sample.mean() / (sample.std(ddof=1) / np.sqrt(n))
    return float(sample.mean()), float(t), n


def seasonality_tables(rets: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dow_rows, month_rows, tom_rows = [], [], []
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri"]

    for market in rets.columns:
        ret = rets[market].dropna()
        if len(ret) < 500:
            continue
        idx = ret.index

        dow = {"market": market, "obs": len(ret)}
        for code, label in enumerate(day_names):
            mean, t, n = _mean_with_t(ret[idx.dayofweek == code])
            dow[f"{label}_bps"] = round(1e4 * mean, 2) if mean == mean else np.nan
            dow[f"{label}_t"] = round(t, 2) if t == t else np.nan
        dow_rows.append(dow)

        month = {"market": market, "obs": len(ret)}
        for m in range(1, 13):
            mean, t, n = _mean_with_t(ret[idx.month == m])
            label = pd.Timestamp(2000, m, 1).strftime("%b")
            month[f"{label}_bps"] = round(1e4 * mean, 2) if mean == mean else np.nan
            month[f"{label}_t"] = round(t, 2) if t == t else np.nan
        month_rows.append(month)

        # Turn of month: last 1 and first 3 sessions of each calendar month.
        rank_in_month = ret.groupby([idx.year, idx.month]).cumcount()
        size_of_month = ret.groupby([idx.year, idx.month]).transform("size")
        is_tom = (rank_in_month < 3) | (rank_in_month >= size_of_month - 1)
        tom_mean, tom_t, tom_n = _mean_with_t(ret[is_tom])
        rest_mean, rest_t, rest_n = _mean_with_t(ret[~is_tom])
        tom_rows.append(
            {
                "market": market,
                "turn_of_month_bps": round(1e4 * tom_mean, 2) if tom_mean == tom_mean else np.nan,
                "turn_t": round(tom_t, 2) if tom_t == tom_t else np.nan,
                "turn_obs": tom_n,
                "rest_of_month_bps": round(1e4 * rest_mean, 2) if rest_mean == rest_mean else np.nan,
                "rest_t": round(rest_t, 2) if rest_t == rest_t else np.nan,
                "rest_obs": rest_n,
                "spread_bps": round(1e4 * (tom_mean - rest_mean), 2) if tom_mean == tom_mean and rest_mean == rest_mean else np.nan,
            }
        )
    return pd.DataFrame(dow_rows), pd.DataFrame(month_rows), pd.DataFrame(tom_rows)


# --------------------------------------------------------------------------
# 6. volatility regimes
# --------------------------------------------------------------------------
def vol_by_year(rets: pd.DataFrame) -> pd.DataFrame:
    annual = rets.groupby(rets.index.year).apply(
        lambda block: block.std(ddof=1) * np.sqrt(TRADING_DAYS) * 100
    )
    annual.index.name = "year"
    return annual.round(1)


def vol_state(rets: pd.DataFrame, window: int) -> pd.DataFrame:
    rows = []
    for market in rets.columns:
        ret = rets[market].dropna()
        if len(ret) < window * 3:
            continue
        realized = ret.rolling(window).std(ddof=1) * np.sqrt(TRADING_DAYS) * 100
        realized = realized.dropna()
        current = float(realized.iloc[-1])
        rows.append(
            {
                "market": market,
                f"vol{window}d_now_pct": round(current, 1),
                "pctile_vs_history": round(100 * float((realized <= current).mean()), 1),
                "median_pct": round(float(realized.median()), 1),
                "p05_pct": round(float(realized.quantile(0.05)), 1),
                "p95_pct": round(float(realized.quantile(0.95)), 1),
                "vol_of_vol": round(float(realized.pct_change().std(ddof=1) * 100), 1),
                "as_of": realized.index[-1].date(),
            }
        )
    return pd.DataFrame(rows).sort_values("pctile_vs_history", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------
# 7. tails and drawdowns
# --------------------------------------------------------------------------
def worst_days(rets: pd.DataFrame, top: int) -> pd.DataFrame:
    rows = []
    for market in rets.columns:
        ret = rets[market].dropna()
        for date, value in ret.nsmallest(top).items():
            rows.append({"market": market, "date": date.date(), "return_pct": round(100 * value, 2), "rank": "worst"})
        for date, value in ret.nlargest(top).items():
            rows.append({"market": market, "date": date.date(), "return_pct": round(100 * value, 2), "rank": "best"})
    return pd.DataFrame(rows).sort_values(["market", "return_pct"]).reset_index(drop=True)


def drawdown_episodes(rets: pd.DataFrame, top: int) -> pd.DataFrame:
    rows = []
    for market in rets.columns:
        ret = rets[market].dropna()
        if len(ret) < 60:
            continue
        equity = (1 + ret).cumprod()
        dd = equity / equity.cummax() - 1
        in_dd = dd < 0
        # Label each contiguous underwater stretch, then rank by depth.
        episode = (in_dd & ~in_dd.shift(1, fill_value=False)).cumsum().where(in_dd)
        for _, block in dd.groupby(episode):
            if block.empty:
                continue
            trough_date = block.idxmin()
            rows.append(
                {
                    "market": market,
                    "start": block.index[0].date(),
                    "trough": trough_date.date(),
                    "end": block.index[-1].date(),
                    "depth_pct": round(100 * float(block.min()), 1),
                    "length_days": len(block),
                    "recovery_days": int((block.index > trough_date).sum()),
                }
            )
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    return (
        table.sort_values(["market", "depth_pct"])
        .groupby("market", as_index=False)
        .head(top)
        .reset_index(drop=True)
    )


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------
def to_markdown(frame: pd.DataFrame, max_rows: int | None = None, empty: str = "_none_") -> str:
    if frame.empty:
        return empty
    view = frame if max_rows is None else frame.head(max_rows)
    return view.to_markdown(index=False)


def write_report(path: Path, sections: list[tuple[str, str]], header: str) -> None:
    body = [header]
    for title, content in sections:
        body.append(f"\n## {title}\n\n{content}\n")
    path.write_text("\n".join(body), encoding="utf-8")


def make_plots(closes: pd.DataFrame, rets: pd.DataFrame, corr: pd.DataFrame, out_dir: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    normalized = closes.where(closes > 0).ffill()
    normalized = normalized / normalized.bfill().iloc[0]
    fig, ax = plt.subplots(figsize=(13, 7))
    normalized.plot(ax=ax, logy=True, linewidth=0.8)
    ax.set_title("CME proxies — normalized close (log scale)")
    ax.legend(ncol=4, fontsize=6)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "prices_normalized.png", dpi=130)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 9))
    im = ax.imshow(corr.to_numpy(dtype=float), cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr)), corr.columns, rotation=90, fontsize=7)
    ax.set_yticks(range(len(corr)), corr.index, fontsize=7)
    ax.set_title("Daily return correlation")
    fig.colorbar(im, ax=ax, shrink=0.8)
    fig.tight_layout()
    fig.savefig(out_dir / "correlation.png", dpi=130)
    plt.close(fig)

    vol = rets.rolling(63).std(ddof=1) * np.sqrt(TRADING_DAYS) * 100
    fig, ax = plt.subplots(figsize=(13, 7))
    vol.plot(ax=ax, linewidth=0.7)
    ax.set_title("63-day realized volatility (%, annualized)")
    ax.legend(ncol=4, fontsize=6)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "rolling_volatility.png", dpi=130)
    plt.close(fig)
    print(f"[write] plots -> {out_dir}")


# --------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--panel", type=Path, default=PANEL_PATH)
    parser.add_argument("--out-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--start", type=str, default=None)
    parser.add_argument("--end", type=str, default=None)
    parser.add_argument("--markets", type=str, default=None, help="comma-separated CME roots, e.g. ES,NQ,CL")
    parser.add_argument("--sectors", type=str, default=None)
    parser.add_argument("--include-reference", action="store_true", help="keep non-CME comparators (Brent, ICE softs, VIX)")
    parser.add_argument("--min-years", type=float, default=3.0, help="drop markets with a shorter history (default 3)")
    parser.add_argument("--rf", type=float, default=0.0, help="annual risk-free rate for Sharpe, e.g. 0.04")
    parser.add_argument("--vol-window", type=int, default=63)
    parser.add_argument("--corr-window", type=int, default=63)
    parser.add_argument("--min-overlap", type=int, default=250, help="minimum shared observations for a correlation")
    parser.add_argument("--top", type=int, default=5, help="rows per market in the tail and drawdown tables")
    parser.add_argument("--glitch-threshold", type=float, default=0.5, help="scrub one-day round-trip moves larger than this (default 0.50)")
    parser.add_argument("--keep-glitches", action="store_true", help="skip the single-day glitch scrub")
    parser.add_argument("--suspect-threshold", type=float, default=1.0, help="flag markets whose surviving moves exceed this (default 1.00 = 100%%)")
    parser.add_argument("--plots", action="store_true")
    args = parser.parse_args()

    panel = load_panel(args.panel, args)
    closes = close_matrix(panel)
    scrub_log = pd.DataFrame()
    if not args.keep_glitches:
        closes, scrub_log = scrub_glitches(closes, args.glitch_threshold)
        if not scrub_log.empty:
            print(f"[scrub] blanked {len(scrub_log)} single-day glitch print(s): "
                  f"{', '.join(sorted(scrub_log['market'].unique()))}")
    rets = return_matrix(closes)
    suspects = suspect_table(rets, args.suspect_threshold)
    if not suspects.empty:
        print(f"[warn] implausible moves survive in: {', '.join(suspects['market'])} — inspect before trusting their stats")
    args.out_dir.mkdir(exist_ok=True)

    coverage = coverage_table(panel, closes, rets)
    moments = moments_table(panel, rets, args.rf)
    dependence = dependence_table(panel, closes, rets)
    corr, corr_pairs, overlap = correlation_tables(rets, args.min_overlap)
    dow, monthly, tom = seasonality_tables(rets)
    yearly_vol = vol_by_year(rets)
    vol_now = vol_state(rets, args.vol_window)
    tails = worst_days(rets, args.top)
    drawdowns = drawdown_episodes(rets, args.top)
    rolling_corr = rolling_beta_to(rets, "ES", args.corr_window)

    outputs = {
        "00_scrubbed_prints.csv": scrub_log,
        "00_suspect_markets.csv": suspects,
        "01_coverage.csv": coverage,
        "02_moments.csv": moments,
        "03_dependence.csv": dependence,
        "04_correlation_matrix.csv": corr,
        "04_correlation_pairs.csv": corr_pairs,
        "05_seasonality_dayofweek.csv": dow,
        "05_seasonality_month.csv": monthly,
        "05_seasonality_turn_of_month.csv": tom,
        "06_volatility_by_year.csv": yearly_vol,
        "06_volatility_state.csv": vol_now,
        "07_tail_days.csv": tails,
        "07_drawdowns.csv": drawdowns,
    }
    for filename, frame in outputs.items():
        index = filename in {"04_correlation_matrix.csv", "06_volatility_by_year.csv"}
        frame.to_csv(args.out_dir / filename, index=index)
    if not rolling_corr.empty:
        rolling_corr.round(3).to_csv(args.out_dir / f"04_rolling_corr_to_ES_{args.corr_window}d.csv")

    window = f"{closes.index[0].date()} to {closes.index[-1].date()}"
    header = (
        f"# CME Group statistical report\n\n"
        f"- Window: **{window}** · markets: **{len(rets.columns)}** · daily observations: **{int(rets.notna().sum().sum()):,}**\n"
        f"- Source: Papers With Backtest daily proxies (cash indices, spot FX, bond price indices, continuous-front commodities).\n"
        f"- Returns are simple and blanked where a price is non-positive; no roll yield, multipliers, fees, or margin are modeled.\n"
        f"- Risk-free used for Sharpe: {args.rf:.2%} annual.\n"
    )

    corr_view = corr_pairs.copy()
    extremes = pd.concat([corr_view.head(12), corr_view.tail(12)]) if len(corr_view) > 24 else corr_view
    sections = [
        ("0a. Scrubbed vendor glitches (blanked before any statistic)",
         to_markdown(scrub_log, empty="_no single-day round-trip prints detected_")),
        ("0b. Suspect markets (implausible moves survived the scrub)",
         to_markdown(suspects, empty="_none — every surviving daily move is within the plausibility threshold_")),
        ("1. Coverage and data quality", to_markdown(coverage)),
        ("2. Return distribution and risk", to_markdown(moments)),
        ("3. Dependence: memory, mean reversion, volatility clustering", to_markdown(dependence)),
        ("4. Correlation — strongest and weakest pairs", to_markdown(extremes)),
        ("5a. Day-of-week mean return (bps, with t-stat)", to_markdown(dow)),
        ("5b. Month-of-year mean return (bps, with t-stat)", to_markdown(monthly)),
        ("5c. Turn-of-month effect", to_markdown(tom)),
        (f"6a. Annualized volatility by year (%)", to_markdown(yearly_vol.tail(15).reset_index())),
        (f"6b. Current {args.vol_window}-day volatility state", to_markdown(vol_now)),
        ("7a. Deepest drawdowns", to_markdown(drawdowns, 60)),
        ("7b. Largest daily moves", to_markdown(tails, 60)),
    ]
    report_path = args.out_dir / "cme_report.md"
    write_report(report_path, sections, header)

    if args.plots:
        make_plots(closes, rets, corr, args.out_dir)

    print(f"[write] {len(outputs)} CSVs + {report_path}")
    print(f"\nWindow {window} · {len(rets.columns)} markets\n")
    with pd.option_context("display.width", 220, "display.max_columns", 40):
        print(moments.to_string(index=False))


if __name__ == "__main__":
    main()
