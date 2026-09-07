"""
Overnight-drift backtest on MES 5-minute bars (Databento), 2020-01 .. 2026-08.

Replicates the core tests of Boyarchenko, Larsen & Whelan, "The Overnight Drift"
(FRB NY Staff Report 917 / RFS 2023) out of sample:

  * hour-of-day return profile around the 24h clock, with HAC t-stats and
    Benjamini-Yekutieli multiple-testing correction across the 24 windows
  * the 02:00-03:00 ET "overnight drift" (OD) window and the 01:30-03:30 (OD+)
    window, gross and net of realistic MES costs
  * a "buy-the-dip" (BtD) conditional variant: OD+ only after a negative
    end-of-day order imbalance, using a bar-level signed-volume proxy
  * benchmarks: close-to-close, close-to-open, open-to-close
  * a start x duration window scan, to see whether 02:00-03:00 is still special

Outputs CSVs and charts to reports/mes_overnight_drift/.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from pathlib import Path

# ----------------------------------------------------------------------------
# config
# ----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "MES_5min_databento.parquet"
OUT = ROOT / "reports" / "mes_overnight_drift"
OUT.mkdir(parents=True, exist_ok=True)

TICK = 0.25            # MES minimum price increment, index points
MULT = 5.0             # MES contract multiplier, $ per index point
SPREAD_TICKS = 1.0     # top-of-book spread, ticks; overnight MES sits at 1 tick
COMMISSION_RT = 1.00   # $ per contract, round turn, all-in (discount broker)

RTH_OPEN = "09:30"
RTH_CLOSE = "16:00"
IMB_WINDOW = ("15:30", "16:00")   # end-of-day imbalance measurement window
TRADING_DAYS = 252

# palette (dataviz reference instance, light mode)
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"   # categorical slots 1-3
POS, NEG = "#2a78d6", "#d03b3b"                # diverging poles
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"],
    "font.size": 10,
    "axes.edgecolor": AXIS,
    "axes.labelcolor": INK2,
    "text.color": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "axes.grid": True,
    "axes.axisbelow": True,
    "legend.frameon": False,
    "figure.dpi": 130,
})


# ----------------------------------------------------------------------------
# data
# ----------------------------------------------------------------------------
def load() -> pd.DataFrame:
    df = pd.read_parquet(DATA).sort_index()
    # CME session runs 18:00 ET -> 17:00 ET next day; stamp each bar with the
    # session (trading day) it belongs to by shifting 6h forward.
    ses = (df.index + pd.Timedelta(hours=6)).normalize()
    df = df.assign(session=ses.tz_localize(None), tod=df.index.strftime("%H:%M"))
    return df


def price_grid(df: pd.DataFrame) -> pd.DataFrame:
    """price at each 5-min clock time, per session.

    A bar stamped t covers [t, t+5m), so its OPEN is the traded price at exactly t.
    The session's final print (16:55 bar close) is carried as a synthetic 17:00
    so the last hour of the session is measurable like every other hour.
    """
    g = df.pivot_table(index="session", columns="tod", values="open", aggfunc="first")
    last = df[df["tod"] == "16:55"].groupby("session")["close"].last()
    g["17:00"] = last
    # drop clock stamps that only exist on a handful of sessions (DST/holiday
    # artefacts); they otherwise contaminate the intraday path
    keep = g.columns[g.notna().sum() >= 0.5 * len(g)]
    return g[sorted(keep)].sort_index()


def imbalance_proxy(df: pd.DataFrame, rule: str = "bar") -> pd.Series:
    """Relative signed volume over the last 30 minutes of RTH.

    True RSV needs trade-level buy/sell classification against the quote. With
    5-min bars the best available substitutes are bar-level tick rules:
      rule="bar"  -> sign(close - open) of each bar
      rule="tick" -> sign(close_t - close_{t-1}), the classic tick test
    Both are coarse proxies for the paper's RSV_close, not substitutes for it.
    """
    w = df[(df["tod"] >= IMB_WINDOW[0]) & (df["tod"] < IMB_WINDOW[1])].copy()
    if rule == "bar":
        s = np.sign(w["close"] - w["open"])
    else:
        s = np.sign(w.groupby("session")["close"].diff()).ffill().fillna(0)
    w["signed"] = s * w["volume"]
    agg = w.groupby("session").agg(signed=("signed", "sum"), gross=("volume", "sum"))
    return (agg["signed"] / agg["gross"]).rename(f"rsv_close_{rule}")


# ----------------------------------------------------------------------------
# stats
# ----------------------------------------------------------------------------
def nw_tstat(x: pd.Series) -> float:
    """Newey-West (HAC) t-stat of the mean."""
    x = x.dropna().to_numpy(float)
    n = len(x)
    if n < 30:
        return np.nan
    e = x - x.mean()
    lag = int(4 * (n / 100.0) ** (2.0 / 9.0))
    s2 = (e @ e) / n
    for L in range(1, lag + 1):
        c = (e[L:] @ e[:-L]) / n
        s2 += 2.0 * (1.0 - L / (lag + 1.0)) * c
    if s2 <= 0:
        return np.nan
    return x.mean() / np.sqrt(s2 / n)


def two_sided_p(t: float) -> float:
    from math import erfc, sqrt
    if not np.isfinite(t):
        return np.nan
    return erfc(abs(t) / sqrt(2.0))


def benjamini_yekutieli(p: np.ndarray, alpha: float = 0.05) -> np.ndarray:
    """BY-adjusted p-values (dependence-robust FDR control)."""
    p = np.asarray(p, float)
    ok = np.isfinite(p)
    out = np.full_like(p, np.nan)
    q = p[ok]
    m = len(q)
    c_m = np.sum(1.0 / np.arange(1, m + 1))
    order = np.argsort(q)
    ranked = q[order]
    adj = ranked * m * c_m / np.arange(1, m + 1)
    adj = np.minimum.accumulate(adj[::-1])[::-1]
    res = np.empty(m)
    res[order] = np.clip(adj, 0, 1)
    out[ok] = res
    return out


def perf(r: pd.Series, name: str, n_trades: pd.Series | None = None) -> dict:
    r = r.dropna()
    n = len(r)
    mean_a = r.mean() * TRADING_DAYS * 100
    vol_a = r.std(ddof=1) * np.sqrt(TRADING_DAYS) * 100
    eq = (1 + r).cumprod()
    dd = (eq / eq.cummax() - 1).min() * 100
    t = nw_tstat(r)
    return {
        "strategy": name,
        "obs": n,
        "days_traded": int(n_trades.sum()) if n_trades is not None else n,
        "mean_ann_pct": mean_a,
        "vol_ann_pct": vol_a,
        "sharpe": mean_a / vol_a if vol_a > 0 else np.nan,
        "t_stat_HAC": t,
        "p_value": two_sided_p(t),
        "hit_rate_pct": (r > 0).mean() * 100,
        "skew": r.skew(),
        "kurtosis": r.kurtosis(),
        "max_dd_pct": dd,
        "total_return_pct": (eq.iloc[-1] - 1) * 100 if n else np.nan,
    }


# ----------------------------------------------------------------------------
# strategy returns
# ----------------------------------------------------------------------------
def leg(grid: pd.DataFrame, t1: str, t2: str) -> pd.Series:
    """simple return from clock time t1 to t2 within the same session"""
    if t1 not in grid.columns or t2 not in grid.columns:
        raise KeyError(f"{t1} or {t2} not in grid")
    return (grid[t2] / grid[t1] - 1).rename(f"{t1}-{t2}")


def cost_ret(entry_px: pd.Series, spread_ticks=SPREAD_TICKS,
             commission=COMMISSION_RT, mult=MULT) -> pd.Series:
    """round-turn cost as a fraction of notional.

    Buy the ask, sell the bid => one full spread per round turn, plus commission.
    """
    dollars = spread_ticks * TICK * mult + commission
    return dollars / (entry_px * mult)


def main() -> None:
    df = load()
    grid = price_grid(df)
    rsv = imbalance_proxy(df, "bar")
    rsv_tick = imbalance_proxy(df, "tick")

    # keep sessions with a full overnight + RTH quote set
    need = ["01:30", "02:00", "03:00", "03:30", RTH_OPEN, RTH_CLOSE]
    grid = grid.dropna(subset=need)
    sess = grid.index
    print(f"sessions: {len(sess)}  {sess.min().date()} .. {sess.max().date()}")

    # ---------------- hour-of-day profile ----------------
    hours = [f"{h:02d}:00" for h in list(range(18, 24)) + list(range(0, 18))]
    rows = []
    for i, h in enumerate(hours):
        nxt = hours[(i + 1) % len(hours)]
        if h not in grid.columns or nxt not in grid.columns:
            continue
        if i == len(hours) - 1:
            # 17:00 -> 18:00 spans the CME maintenance halt into the NEXT session
            r = (grid["18:00"].shift(-1) / grid["17:00"] - 1).dropna()
        else:
            r = leg(grid, h, nxt).dropna()
        t = nw_tstat(r)
        rows.append({
            "hour": f"{h}-{nxt}",
            "start": h,
            "mean_bps": r.mean() * 1e4,
            "mean_ann_pct": r.mean() * TRADING_DAYS * 100,
            "median_bps": r.median() * 1e4,
            "sd_bps": r.std() * 1e4,
            "t_stat": t,
            "p_value": two_sided_p(t),
            "n": len(r),
        })
    hp = pd.DataFrame(rows)
    hp["p_BY"] = benjamini_yekutieli(hp["p_value"].to_numpy())
    hp.to_csv(OUT / "hour_profile.csv", index=False)

    # ---------------- strategies ----------------
    ctc = (grid[RTH_CLOSE] / grid[RTH_CLOSE].shift(1) - 1).rename("CTC")
    cto = (grid[RTH_OPEN] / grid[RTH_CLOSE].shift(1) - 1).rename("CTO")
    otc = leg(grid, RTH_OPEN, RTH_CLOSE).rename("OTC")
    od = leg(grid, "02:00", "03:00").rename("OD")
    odp = leg(grid, "01:30", "03:30").rename("OD+")

    r_ = rsv.reindex(sess)
    btd_mask = (r_.shift(1) < 0).fillna(False)          # prior session's close imbalance
    btd = odp.where(btd_mask, 0.0).rename("BtD")

    c_od = cost_ret(grid["02:00"])
    c_odp = cost_ret(grid["01:30"])
    c_ctc = cost_ret(grid[RTH_CLOSE]) / TRADING_DAYS    # amortise one round turn per year of holding
    c_cto = cost_ret(grid[RTH_CLOSE].shift(1))
    c_otc = cost_ret(grid[RTH_OPEN])

    gross = {"CTC": ctc, "CTO": cto, "OTC": otc, "OD": od, "OD+": odp, "BtD": btd}
    net = {
        "CTC": ctc - c_ctc,
        "CTO": cto - c_cto,
        "OTC": otc - c_otc,
        "OD": od - c_od,
        "OD+": odp - c_odp,
        "BtD": (odp - c_odp).where(btd_mask, 0.0),
    }
    traded = {k: pd.Series(1.0, index=sess) for k in gross}
    traded["BtD"] = btd_mask.astype(float)

    tbl_g = pd.DataFrame([perf(v, k, traded[k]) for k, v in gross.items()])
    tbl_n = pd.DataFrame([perf(v, k, traded[k]) for k, v in net.items()])
    tbl_g["costs"] = "gross"
    tbl_n["costs"] = "net"
    tbl = pd.concat([tbl_g, tbl_n], ignore_index=True)
    tbl.to_csv(OUT / "strategy_stats.csv", index=False)

    # ---------------- subsample split: 2020 vs 2021-2026 ----------------
    split = pd.Timestamp("2021-01-01")
    subs = []
    for tag, mask in (("2020", sess < split), ("2021-2026", sess >= split)):
        for label, book in (("gross", gross), ("net", net)):
            for k in ("CTC", "OD", "OD+", "BtD"):
                d = perf(book[k][mask], k, traded[k][mask])
                d.update(period=tag, costs=label)
                subs.append(d)
    sub_tbl = pd.DataFrame(subs)
    sub_tbl.to_csv(OUT / "subsample_stats.csv", index=False)

    # ---------------- imbalance sort (the paper's central conditional test) ----
    labels = ["Q1 most negative", "Q2", "Q3", "Q4", "Q5 most positive"]
    sorts = {}
    for rule, proxy in (("bar", rsv), ("tick", rsv_tick)):
        cond = pd.DataFrame({"odp": odp, "od": od,
                             "rsv_prev": proxy.reindex(sess).shift(1)}).dropna()
        cond["bucket"] = pd.qcut(cond["rsv_prev"], 5, labels=labels)
        sorts[rule] = cond.groupby("bucket", observed=True).agg(
            n=("odp", "size"),
            rsv_mean=("rsv_prev", "mean"),
            odp_bps=("odp", lambda s: s.mean() * 1e4),
            odp_t=("odp", nw_tstat),
            od_bps=("od", lambda s: s.mean() * 1e4),
            od_t=("od", nw_tstat),
        )
        sorts[rule].to_csv(OUT / f"imbalance_sort_{rule}.csv")
    cq = sorts["bar"]

    # ---------------- per-year OD ----------------
    yr = pd.DataFrame({"od": od, "odp": odp, "ctc": ctc, "btd": btd}).dropna(subset=["od"])
    yr["year"] = yr.index.year
    by_year = yr.groupby("year").agg(
        od_ann_pct=("od", lambda s: s.mean() * TRADING_DAYS * 100),
        od_t=("od", nw_tstat),
        odp_ann_pct=("odp", lambda s: s.mean() * TRADING_DAYS * 100),
        ctc_ann_pct=("ctc", lambda s: s.mean() * TRADING_DAYS * 100),
        n=("od", "size"),
    )
    by_year.to_csv(OUT / "od_by_year.csv")

    # ---------------- window scan ----------------
    starts = [f"{h:02d}:{m:02d}" for h in list(range(18, 24)) + list(range(0, 9))
              for m in (0, 30)]
    durs = [30, 60, 90, 120, 180, 240]
    scan = pd.DataFrame(index=starts, columns=durs, dtype=float)
    scan_net = scan.copy()
    for s in starts:
        if s not in grid.columns:
            continue
        base = pd.Timestamp("2000-01-01 " + s)
        for d in durs:
            e = (base + pd.Timedelta(minutes=d)).strftime("%H:%M")
            if e not in grid.columns:
                continue
            r = (grid[e] / grid[s] - 1).dropna()
            if len(r) < 250:
                continue
            sd = r.std(ddof=1)
            if sd <= 0:
                continue
            scan.loc[s, d] = (r.mean() / sd) * np.sqrt(TRADING_DAYS)
            rn = r - cost_ret(grid[s]).reindex(r.index)
            scan_net.loc[s, d] = (rn.mean() / rn.std(ddof=1)) * np.sqrt(TRADING_DAYS)
    scan.to_csv(OUT / "window_scan_sharpe_gross.csv")
    scan_net.to_csv(OUT / "window_scan_sharpe_net.csv")

    # ---------------- charts ----------------
    charts(grid, hp, gross, net, by_year, scan, scan_net, od, sess, cq)

    # ---------------- console summary ----------------
    cols = ["strategy", "costs", "mean_ann_pct", "vol_ann_pct", "sharpe",
            "t_stat_HAC", "hit_rate_pct", "max_dd_pct"]
    print("\n=== strategy performance ===")
    print(tbl[cols].to_string(index=False, float_format=lambda v: f"{v:8.2f}"))
    print("\n=== hour profile (top by |t|) ===")
    print(hp.reindex(hp["t_stat"].abs().sort_values(ascending=False).index)
            .head(8)[["hour", "mean_bps", "mean_ann_pct", "t_stat", "p_value", "p_BY"]]
            .to_string(index=False, float_format=lambda v: f"{v:8.3f}"))
    print("\n=== OD by year ===")
    print(by_year.to_string(float_format=lambda v: f"{v:8.2f}"))
    print("\n=== 2020 vs 2021-2026 ===")
    print(sub_tbl[["period", "strategy", "costs", "mean_ann_pct", "sharpe", "t_stat_HAC"]]
          .to_string(index=False, float_format=lambda v: f"{v:8.2f}"))
    for rule, t_ in sorts.items():
        print(f"\n=== previous-close imbalance sort, {rule} rule (OD+ return) ===")
        print(t_.to_string(float_format=lambda v: f"{v:8.3f}"))
    print(f"\nwrote csvs + charts to {OUT}")


# ----------------------------------------------------------------------------
# charts
# ----------------------------------------------------------------------------
def _clean(ax, ygrid=True, xgrid=False):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y" if ygrid else "x", visible=ygrid or xgrid)
    ax.grid(axis="x", visible=xgrid)


def charts(grid, hp, gross, net, by_year, scan, scan_net, od, sess, cq):
    # -- 1. hour-of-day profile -------------------------------------------
    fig, ax = plt.subplots(figsize=(11, 4.6))
    colors = [POS if v >= 0 else NEG for v in hp["mean_ann_pct"]]
    ax.bar(range(len(hp)), hp["mean_ann_pct"], color=colors, width=0.72)
    for i, row in hp.reset_index().iterrows():
        if abs(row["t_stat"]) >= 2:
            ax.annotate(f"t={row['t_stat']:.1f}",
                        (i, row["mean_ann_pct"]),
                        textcoords="offset points",
                        xytext=(0, 4 if row["mean_ann_pct"] >= 0 else -13),
                        ha="center", fontsize=8, color=INK2)
    ax.set_xticks(range(len(hp)))
    ax.set_xticklabels([h.split("-")[0] for h in hp["hour"]], rotation=45, fontsize=8)
    ax.axhline(0, color=AXIS, lw=1)
    ax.set_ylabel("annualised return, %")
    ax.set_xlabel("hour start (ET), CME session 18:00 → 17:00")
    ax.set_title("MES returns around the clock, 2020–2026\n"
                 "hourly mean returns, annualised; HAC t-stats labelled where |t| ≥ 2",
                 loc="left", fontsize=12, color=INK)
    _clean(ax)
    fig.tight_layout()
    fig.savefig(OUT / "01_hour_profile.png")
    plt.close(fig)

    # -- 2. cumulative intraday path, full vs subsamples --------------------
    tods = sorted([c for c in grid.columns])
    order = [t for t in tods if t >= "18:00"] + [t for t in tods if t < "18:00"]
    sub = grid[order]
    lr = np.log(sub).diff(axis=1)
    fig, ax = plt.subplots(figsize=(11, 4.8))
    parts = [("2020–2026 (all)", sess, S1),
             ("2020 only", sess[sess.year == 2020], S2),
             ("2021–2026", sess[sess.year >= 2021], S3)]
    x = np.arange(len(order))
    for label, idx, col in parts:
        cum = lr.loc[idx].mean(axis=0).fillna(0).cumsum() * 252 * 100
        ax.plot(x, cum.to_numpy(), color=col, lw=2, label=label)
        ax.annotate(label, (x[-1], cum.to_numpy()[-1]), textcoords="offset points",
                    xytext=(6, 0), color=col, fontsize=9, va="center")
    for t in ("02:00", "03:00"):
        ax.axvline(order.index(t), color=AXIS, lw=1, ls=(0, (3, 3)))
    ax.annotate("02:00–03:00\n(European open)",
                (order.index("02:00"), ax.get_ylim()[1]), textcoords="offset points",
                xytext=(4, -26), fontsize=8, color=INK2)
    ticks = [i for i, t in enumerate(order) if t.endswith(":00") and int(t[:2]) % 2 == 0]
    ax.set_xticks(ticks)
    ax.set_xticklabels([order[i] for i in ticks], fontsize=8)
    ax.set_xlim(0, len(order) + 34)
    ax.axhline(0, color=AXIS, lw=1)
    ax.set_ylabel("cumulative mean return, annualised %")
    ax.set_xlabel("time of day (ET)")
    ax.set_title("Where the return accrues inside the session\n"
                 "cumulative 5-minute mean log return, annualised",
                 loc="left", fontsize=12, color=INK)
    ax.legend(loc="upper left", fontsize=9)
    _clean(ax)
    fig.tight_layout()
    fig.savefig(OUT / "02_intraday_path.png")
    plt.close(fig)

    # -- 3. equity curves, gross | net -------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharey=True)
    series = [("OD 02:00–03:00", "OD", S1), ("OD+ 01:30–03:30", "OD+", S2),
              ("BtD (OD+ after neg. imbalance)", "BtD", S3)]
    for ax, book, tag in ((axes[0], gross, "gross of costs"),
                          (axes[1], net, "net of 1-tick spread + $1 RT commission")):
        ax.plot(sess, (1 + book["CTC"].fillna(0)).cumprod(), color=MUTED, lw=1.6,
                label="buy & hold (CTC)")
        for label, key, col in series:
            ax.plot(sess, (1 + book[key].fillna(0)).cumprod(), color=col, lw=2, label=label)
        ax.axhline(1, color=AXIS, lw=1)
        ax.set_title(tag, loc="left", fontsize=10, color=INK2)
        _clean(ax)
    axes[0].set_ylabel("growth of $1")
    axes[0].legend(loc="upper left", fontsize=8.5)
    fig.suptitle("Overnight-drift strategies vs buy & hold, MES 2020–2026",
                 x=0.008, ha="left", fontsize=12, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(OUT / "03_equity_curves.png")
    plt.close(fig)

    # -- 4. OD by year ------------------------------------------------------
    fig, ax = plt.subplots(figsize=(9, 4.2))
    vals = by_year["od_ann_pct"]
    ax.bar(vals.index.astype(str), vals, color=[POS if v >= 0 else NEG for v in vals],
           width=0.66)
    for xi, (y, v) in enumerate(vals.items()):
        ax.annotate(f"{v:.1f}", (xi, v), textcoords="offset points",
                    xytext=(0, 4 if v >= 0 else -13), ha="center",
                    fontsize=8.5, color=INK2)
    ax.set_ylim(min(vals.min() * 1.45, -1.0), vals.max() * 1.18)
    ax.axhline(0, color=AXIS, lw=1)
    ax.set_ylabel("annualised return, %")
    ax.set_title("The 02:00–03:00 window, year by year (gross)\n"
                 "2026 is a partial year (through 7 Aug)",
                 loc="left", fontsize=12, color=INK)
    _clean(ax)
    fig.tight_layout()
    fig.savefig(OUT / "04_od_by_year.png")
    plt.close(fig)

    # -- 5. window scan heatmap --------------------------------------------
    cmap = LinearSegmentedColormap.from_list(
        "div", [NEG, "#f0efec", POS])
    fig, axes = plt.subplots(1, 2, figsize=(12, 6.4), sharey=True)
    lim = float(np.nanmax([np.nanmax(np.abs(scan.astype(float).to_numpy())),
                           np.nanmax(np.abs(scan_net.astype(float).to_numpy()))])) or 1.0
    norm = TwoSlopeNorm(vcenter=0, vmin=-lim, vmax=lim)
    for ax, mat, tag in ((axes[0], scan, "gross"), (axes[1], scan_net, "net of costs")):
        m = mat.astype(float)
        im = ax.imshow(m.to_numpy(), cmap=cmap, norm=norm,
                       aspect="auto", interpolation="nearest")
        ax.set_xticks(range(len(m.columns)))
        ax.set_xticklabels([f"{c}m" for c in m.columns], fontsize=8)
        ax.set_yticks(range(len(m.index)))
        ax.set_yticklabels(m.index, fontsize=7)
        ax.set_title(f"Sharpe, {tag}", loc="left", fontsize=10, color=INK2)
        ax.grid(False)
        ax.set_xlabel("holding period")
        if "02:00" in m.index and 60 in m.columns:
            ax.add_patch(plt.Rectangle(
                (list(m.columns).index(60) - 0.5, list(m.index).index("02:00") - 0.5),
                1, 1, fill=False, edgecolor=INK, lw=1.8))
    cb = fig.colorbar(im, ax=axes, fraction=0.035, pad=0.02)
    cb.set_label("annualised Sharpe", color=INK2)
    cb.outline.set_visible(False)
    axes[0].set_ylabel("entry time (ET)")
    fig.suptitle("Long-only window scan: annualised Sharpe by entry time and holding period\n"
                 "black box = the paper's 02:00–03:00 window; both panels share one scale",
                 x=0.008, y=0.985, ha="left", va="top", fontsize=12, color=INK)
    fig.savefig(OUT / "05_window_scan.png")
    plt.close(fig)

    # -- 6. rolling 250-day OD ---------------------------------------------
    fig, ax = plt.subplots(figsize=(10, 4.2))
    roll = od.rolling(250).mean() * TRADING_DAYS * 100
    ax.plot(sess, roll, color=S1, lw=2)
    ax.axhline(0, color=AXIS, lw=1)
    ax.axhline(3.7, color=MUTED, lw=1.2, ls=(0, (4, 3)))
    ax.annotate("3.7% — paper's 1998–2020 average", (sess[int(len(sess) * 0.42)], 3.7),
                textcoords="offset points", xytext=(0, 6), fontsize=8.5, color=INK2)
    ax.set_ylabel("annualised return, %")
    ax.set_title("Rolling 250-session mean of the 02:00–03:00 return (gross)",
                 loc="left", fontsize=12, color=INK)
    _clean(ax)
    fig.tight_layout()
    fig.savefig(OUT / "06_rolling_od.png")
    plt.close(fig)

    # -- 7. imbalance sort --------------------------------------------------
    fig, ax = plt.subplots(figsize=(9, 4.4))
    vals = cq["odp_bps"]
    ax.bar(range(len(vals)), vals,
           color=[POS if v >= 0 else NEG for v in vals], width=0.66)
    for i, (lab, v) in enumerate(vals.items()):
        ax.annotate(f"{v:.2f} bps\nt={cq['odp_t'].iloc[i]:.1f}", (i, v),
                    textcoords="offset points",
                    xytext=(0, 5 if v >= 0 else -24), ha="center",
                    fontsize=8.5, color=INK2)
    lo, hi = float(vals.min()), float(vals.max())
    ax.set_ylim(min(lo * 1.9, -0.4), hi * 1.35)
    ax.set_xticks(range(len(vals)))
    ax.set_xticklabels([str(i) for i in vals.index], fontsize=9)
    ax.axhline(0, color=AXIS, lw=1)
    ax.set_ylabel("mean 01:30–03:30 return, bps")
    ax.set_xlabel("quintile of previous session's closing order-imbalance proxy")
    ax.set_title("Does the overnight window still pay for absorbing the close?\n"
                 "the paper predicts a large positive bar on the left and a muted one on the right",
                 loc="left", fontsize=12, color=INK)
    _clean(ax)
    fig.tight_layout()
    fig.savefig(OUT / "07_imbalance_sort.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
