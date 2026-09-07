"""Does the overnight drift block exist in GOLD? Full MGC backtest, two eras.

Everything in this workspace that works is an equity-index result: the 18:00->06:00
Globex block on MNQ pays ~$14/night/micro, replicates out of sample (pooled t=3.58)
and is structurally an equity-risk-premium story -- you are paid to hold index risk
while the US is asleep. Gold has no equity premium. If the same clock block pays on
MGC it has to be a different mechanism (Asian physical demand, the London AM fix at
05:30 ET, the dollar's overnight path), so this is a genuine test, not a port.

Method is deliberately identical to the MNQ suite so the numbers are comparable:

  * per-contract dollars, never percent (continuous futures levels are unadjusted)
  * one round trip per night, long only, entry at the block's first open, exit at
    its last close -- roll gaps and the Friday->Sunday reopen fall BETWEEN blocks
    and are never held
  * costs charged in TICKS (MGC: 0.10 tick = $1.00/contract), plus explicit
    commission, swept
  * two eras: MGC 2019-2026 in-sample, GC 2015-2020 out-of-sample priced at the
    micro $10/pt multiplier and rescaled to today's gold notional
  * any clock search is scored against a SIGN-FLIP permutation null (best-of-N),
    the control that killed the MNQ hour scan

Sections: data integrity -> 6h blocks -> named scenarios (both eras) -> cost sweep
-> account tail -> hour-window scan vs permutation null -> stability -> MNQ
correlation (the only reason to own a gold sleeve is that it is not the NQ sleeve).

    python mgc_overnight_block_backtest.py
    python mgc_overnight_block_backtest.py --commission 1.24 --scan
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).with_name("data")

# MGC = 10 troy oz. 1 point ($1 of gold) = $10; min tick 0.10 = $1.00.
DPP, TICK = 10.0, 0.10
IS_FILE = "MGC_5min_databento.parquet"          # 2019-10 -> 2026-08, micro contract
OOS_FILE = "GC_5min_2015_2020_databento.parquet"  # 2015-01 -> 2020-01, big contract

BLOCK_NAMES = {0: "Asia 18-00", 1: "London 00-06", 2: "NY am 06-12", 3: "NY pm 12-18"}

# (label, entry hour, exit hour INCLUSIVE, entry taken from the PRIOR afternoon)
# "16:00*" holds through the 17:00-18:00 CME halt and across weekends.
SCENARIOS = [
    ("18:00 -> 06:00  [MNQ system]", 18, 5, False),
    ("18:00 -> 03:00",               18, 2, False),
    ("18:00 -> 08:00",               18, 7, False),
    ("18:00 -> 17:00  [full 24h]",   18, 16, False),
    ("20:00 -> 06:00",               20, 5, False),
    ("23:00 -> 04:00",               23, 3, False),
    ("00:00 -> 06:00  [London]",      0, 5, False),
    ("02:00 -> 06:00  [AM fix run]",  2, 5, False),
    ("03:00 -> 09:00",                3, 8, False),
    ("06:00 -> 18:00  [day]",         6, 16, False),
    ("16:00* -> 06:00 [NY close]",   16, 5, True),
    ("16:00* -> 09:00 [textbook ON]", 16, 8, True),
]

SESSION_HOURS = [(18 + p) % 24 for p in range(23)]   # 18:00..16:00, 17:00 halt excluded


# ---------------------------------------------------------------- data ----------
def load_cells(fname: str, min_bars: int = 6):
    """(open, close) hour-cell matrices indexed by 18:00-anchored session date."""
    d = pd.read_parquet(DATA / fname).sort_index()
    idx = d.index
    sess = (idx - pd.Timedelta(hours=18)).normalize()
    cell = d.groupby([sess, idx.hour]).agg(o=("open", "first"), c=("close", "last"),
                                           h=("high", "max"), l=("low", "min"),
                                           n=("open", "size"))
    cell = cell[cell["n"] >= min_bars]           # of 12 possible 5-min bars
    o, c = cell["o"].unstack(-1), cell["c"].unstack(-1)
    o.index = pd.DatetimeIndex(o.index).tz_localize(None)
    c.index = pd.DatetimeIndex(c.index).tz_localize(None)
    return o, c


MONTH_CODE = dict(zip("FGHJKMNQUVXZ", range(1, 13)))


def front_next_basis(path: Path) -> pd.DataFrame:
    """Daily front vs next-month MGC outright spread, annualized -- the real carry.

    Built from parent-symbology daily bars (data/MGC_outrights_daily.parquet), so
    this is the observed calendar spread, not a rate assumption.
    """
    d = pd.read_parquet(path)
    d = d[d["symbol"].str.match(r"^MGC[FGHJKMNQUVXZ]\d+$")].copy()
    d["ts"] = pd.to_datetime(d["ts_event"]).dt.tz_localize(None).dt.normalize()

    def expiry(sym: str, ts: pd.Timestamp) -> pd.Timestamp:
        mth, digit = MONTH_CODE[sym[3]], int(sym[4:])
        base = ts.year - ts.year % 10 + digit          # single-digit year code
        for cand in (base - 10, base, base + 10):
            t = pd.Timestamp(year=cand, month=mth, day=1)
            if t >= ts - pd.Timedelta(days=20):
                return t
        return pd.Timestamp(year=base, month=mth, day=1)

    d["expiry"] = [expiry(s, t) for s, t in zip(d["symbol"], d["ts"])]
    d = d[(d["expiry"] >= d["ts"]) & (d["volume"] > 0)]
    rows = []
    for ts, g in d.groupby("ts"):
        g = g.sort_values("expiry")
        if len(g) < 2:
            continue
        f, n = g.iloc[0], g.iloc[1]
        yrs = (n["expiry"] - f["expiry"]).days / 365.25
        if yrs > 0:
            rows.append((ts, f["close"], n["close"] - f["close"],
                         (n["close"] / f["close"] - 1) / yrs * 100))
    return pd.DataFrame(rows, columns=["ts", "front", "spread", "ann"]).set_index("ts")


def integrity(fname: str, label: str) -> None:
    d = pd.read_parquet(DATA / fname).sort_index()
    per_day = d.groupby(d.index.normalize()).size()
    hourly = d.groupby(d.index.hour).size() / d.index.normalize().nunique()
    gaps = d["open"] - d["close"].shift(1)
    big = gaps[gaps.abs() > 5 * d["close"].mean() / 1000]   # >0.5% of level
    at18 = (big.index.hour == 18).mean() * 100 if len(big) else np.nan
    print(f"\n{label}: {len(d):,} bars  {d.index.min().date()} -> {d.index.max().date()}  "
          f"({d.index.normalize().nunique():,} days, median {per_day.median():.0f} bars/day)")
    print(f"  jumps >0.5% between consecutive bars: {len(big)}  "
          f"({at18:.0f}% of them at the 18:00 reopen = roll/weekend seam)")
    thin = hourly[hourly < 9]
    if len(thin):
        print("  thin hours (<9 of 12 bars/day avg): "
              + ", ".join(f"{h:02d}:00={v:.1f}" for h, v in thin.items()))


# ----------------------------------------------------------- backtest ----------
def window_pnl(o, c, eh, xh, prior=False, ref=None, cost=0.0) -> pd.Series:
    """Per-night $ P&L per contract, net. ref set -> rescale old era to today's notional."""
    ent = o[eh].shift(1) if prior else o[eh]
    j = pd.concat([ent, c[xh]], axis=1).dropna()
    entry, exit_ = j.iloc[:, 0].values, j.iloc[:, 1].values
    pts = (exit_ - entry) if ref is None else (exit_ - entry) / entry * ref
    return pd.Series(pts * DPP - cost, index=j.index)


def maxdd(p: pd.Series) -> float:
    eq = p.cumsum()
    return float((eq - eq.cummax()).min())


def stats(p: pd.Series) -> dict:
    a = p.values
    w, l = a[a > 0], a[a < 0]
    sd = a.std(ddof=1)
    return {"n": len(a), "mean": a.mean(), "sd": sd,
            "pf": w.sum() / abs(l.sum()) if len(l) else np.inf,
            "hit": (a > 0).mean() * 100,
            "sharpe": a.mean() / sd * np.sqrt(252),
            "t": a.mean() / sd * np.sqrt(len(a)),
            "worst": a.min(), "best": a.max(), "maxdd": maxdd(p),
            "yr": a.mean() * 252,
            "lt500": int((a < -500).sum()), "lt1k": int((a < -1000).sum()),
            "lt2k": int((a < -2000).sum())}


def pooled_t(*series) -> float:
    a = np.concatenate([s.values for s in series])
    return float(a.mean() / a.std(ddof=1) * np.sqrt(len(a)))


# ------------------------------------------------------------- report ----------
def main() -> None:
    ap = argparse.ArgumentParser(description="MGC overnight block backtest, two eras.")
    ap.add_argument("--ticks", type=float, default=1.0, help="round-trip slippage, ticks")
    ap.add_argument("--commission", type=float, default=0.0,
                    help="$ per contract round turn on top of slippage")
    ap.add_argument("--scan", action="store_true",
                    help="hour-window scan + sign-flip permutation null (slow)")
    ap.add_argument("--draws", type=int, default=400)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    cost = args.ticks * TICK * DPP + args.commission

    print("\n" + "=" * 100)
    print("MGC OVERNIGHT DRIFT BLOCK -- does gold pay you to hold it while the US sleeps?")
    print("=" * 100)
    print(f"MGC: ${DPP:.0f}/point, {TICK} tick = ${TICK*DPP:.2f}. "
          f"Cost charged {args.ticks:g} tick + ${args.commission:.2f} comm "
          f"= ${cost:.2f}/contract RT")

    integrity(IS_FILE, "IN-SAMPLE  MGC")
    oos_ok = (DATA / OOS_FILE).exists()
    if oos_ok:
        integrity(OOS_FILE, "OUT-OF-SAMPLE  GC (priced at micro $10/pt)")

    o_is, c_is = load_cells(IS_FILE)
    if oos_ok:
        o_os, c_os = load_cells(OOS_FILE)
        ref = float(o_is[18].loc["2024-01-01":].median())    # today's gold notional
        print(f"\nOOS point moves rescaled to {ref:,.0f} gold "
              f"(2015-19 gold ~{float(o_os[18].median()):,.0f}, so raw point moves "
              f"understate today's dollar risk by ~{ref/float(o_os[18].median()):.1f}x)")

    # ---- carry leakage test ----------------------------------------------------
    # An unadjusted continuous contract rolls UP through contango, so any position
    # held across the 16:00->18:00 session seam books a level gain the real world
    # never pays: at the roll you sell the cheap front and buy the dearer next
    # month. Equity index carry is small; GOLD carry is the whole storage+financing
    # cost of bullion, so this is the first thing to check, not the last. Diagnostic:
    # divide the seam's annual $ by the contract notional. If the answer is the era's
    # policy rate, the "edge" is a money-market yield, not a trade.
    print("\n" + "-" * 100)
    print("0. CARRY-LEAKAGE TEST on the 16:00->18:00 session seam")
    print("-" * 100)
    print(f"{'series':<24}{'n':>6}{'$/night':>9}{'$/yr':>8}{'median':>8}{'t':>7}"
          f"{'notional':>10}{'implied rate':>14}")
    for tag, o_, c_ in ([("MGC 2019-2026", o_is, c_is)]
                        + ([("GC 2015-2020", o_os, c_os)] if oos_ok else [])):
        seam = ((o_[18] - c_[16].shift(1)).dropna() * DPP)
        notional = float(o_[18].median()) * DPP
        per_yr = seam.mean() * 252
        print(f"{tag:<24}{len(seam):>6}{seam.mean():>9.2f}{per_yr:>8,.0f}"
              f"{seam.median():>8.2f}"
              f"{seam.mean()/seam.std(ddof=1)*np.sqrt(len(seam)):>7.2f}"
              f"{notional:>10,.0f}{per_yr/notional*100:>13.2f}%")

    # measured against the REAL calendar spread, not an assumed rate
    basis_f = DATA / "MGC_outrights_daily.parquet"
    if basis_f.exists():
        b = front_next_basis(basis_f)
        yr = b.groupby(b.index.year).agg(basis_pts=("spread", "mean"),
                                         ann=("ann", "mean"), px=("front", "mean"))
        yr["carry_$yr"] = yr["ann"] / 100 * yr["px"] * DPP
        ff = {2019: 2.16, 2020: 0.38, 2021: 0.08, 2022: 1.68,
              2023: 5.02, 2024: 5.15, 2025: 4.10, 2026: 3.60}
        yr["fedfunds%"] = [ff.get(y, np.nan) for y in yr.index]
        print("\nREAL front->next calendar spread on MGC outrights (the thing you "
              "actually pay at every roll):")
        print(yr.round(2).to_string())
        v = yr.dropna()
        print(f"corr(annualized basis, fed funds) = {v['ann'].corr(v['fedfunds%']):+.3f}"
              f"   mean carry ${yr['carry_$yr'].mean():,.0f}/yr per MGC contract")
        print("Gold is a pure cost-of-carry market: F = S*(1+r+storage)^T. The basis "
              "IS the funding rate, so an unadjusted continuous series rolls UP by "
              "that much every year for free.")

    # where does the 16:00* entry's advantage actually come from?
    print("\nDECOMPOSITION of the 16:00* entry's extra hours (gross, 1 contract):")
    print(f"{'segment':<20}{'IS $/nt':>9}{'IS $/yr':>9}{'IS t':>7}"
          + (f"{'OOS $/nt':>10}{'OOS t':>7}" if oos_ok else "") + "  verdict")
    segs = [("16-17 last hour", lambda o_, c_: (c_[16] - o_[16]).dropna()),
            ("17-18 seam", lambda o_, c_: (o_[18] - c_[16].shift(1)).dropna()),
            ("18-06 overnight", lambda o_, c_: (c_[5] - o_[18]).dropna())]
    verdicts = {"16-17 last hour": "does not replicate -> noise",
                "17-18 seam": "replicates, but it is CARRY -> unbankable",
                "18-06 overnight": "the only segment that is a trade"}
    for name, fn in segs:
        a = fn(o_is, c_is) * DPP
        line = (f"{name:<20}{a.mean():>9.2f}{a.mean()*252:>9,.0f}"
                f"{a.mean()/a.std(ddof=1)*np.sqrt(len(a)):>7.2f}")
        if oos_ok:
            raw = fn(o_os, c_os)
            anchor = (o_os[16] if name.startswith("16-17") else o_os[18]).reindex(raw.index)
            bb = (raw / anchor).dropna() * ref * DPP
            line += (f"{bb.mean():>10.2f}"
                     f"{bb.mean()/bb.std(ddof=1)*np.sqrt(len(bb)):>7.2f}")
        print(line + "  " + verdicts[name])
    print("\nAny scenario marked 16:00* crosses the seam and therefore BOOKS THE "
          "FUNDING RATE AS PROFIT. Its excess over the 18:00 entry is an artifact, "
          "and note the seam's t-stat BEATS the real trade's -- a mechanical accrual "
          "has tiny variance, so significance testing rewards it. High t is not edge.")

    # ---- 6h clock blocks -------------------------------------------------------
    print("\n" + "-" * 100)
    print("1. SIX-HOUR CLOCK BLOCKS, 1 MGC CONTRACT (in-sample, net)")
    print("-" * 100)
    blocks = {BLOCK_NAMES[0]: (18, 23), BLOCK_NAMES[1]: (0, 5),
              BLOCK_NAMES[2]: (6, 11), BLOCK_NAMES[3]: (12, 16),
              "OVERNIGHT 18-06": (18, 5), "DAY 06-18": (6, 16), "FULL 24h": (18, 16)}
    print(f"{'block':<16}{'n':>6}{'$/night':>9}{'$/yr':>9}{'sd$':>7}{'Shp':>6}"
          f"{'PF':>7}{'hit%':>7}{'t':>7}{'MaxDD$':>9}{'worst$':>9}")
    blk_pnl = {}
    for k, (eh, xh) in blocks.items():
        p = window_pnl(o_is, c_is, eh, xh, cost=cost)
        blk_pnl[k] = p
        s = stats(p)
        print(f"{k:<16}{s['n']:>6}{s['mean']:>9.2f}{s['yr']:>9,.0f}{s['sd']:>7.0f}"
              f"{s['sharpe']:>6.2f}{s['pf']:>7.3f}{s['hit']:>7.1f}{s['t']:>7.2f}"
              f"{s['maxdd']:>9,.0f}{s['worst']:>9,.0f}")

    # ---- named scenarios, both eras -------------------------------------------
    print("\n" + "-" * 100)
    print("2. NAMED ENTRY/EXIT SCENARIOS  (in-sample MGC | out-of-sample GC | pooled)")
    print("-" * 100)
    print(f"{'scenario':<32}{'hrs':>4}{'$/nt':>8}{'$/yr':>8}{'Shp':>6}{'PF':>7}{'hit%':>6}"
          f"{'MaxDD$':>9}{'worst':>8}{'<-1k':>6}|{'OOS$/nt':>9}{'OOS Shp':>8}{'OOS PF':>8}"
          f"{'OOS t':>7}|{'pool t':>7}")
    rows = []
    for label, eh, xh, prior in SCENARIOS:
        pi = window_pnl(o_is, c_is, eh, xh, prior, cost=cost)
        si = stats(pi)
        hrs = (xh + 1 - eh) % 24
        line = (f"{label:<32}{hrs:>4}{si['mean']:>8.2f}{si['yr']:>8,.0f}{si['sharpe']:>6.2f}"
                f"{si['pf']:>7.3f}{si['hit']:>6.1f}{si['maxdd']:>9,.0f}{si['worst']:>8,.0f}"
                f"{si['lt1k']:>6}")
        if oos_ok:
            po = window_pnl(o_os, c_os, eh, xh, prior, ref=ref, cost=cost)
            so = stats(po)
            line += (f"|{so['mean']:>9.2f}{so['sharpe']:>8.2f}{so['pf']:>8.3f}"
                     f"{so['t']:>7.2f}|{pooled_t(pi, po):>7.2f}")
            rows.append((label, si, so))
        else:
            rows.append((label, si, None))
        print(line)

    print("\nRISK-PER-DRAWDOWN-DOLLAR (in-sample; MaxDD is the account-killing number)")
    print(f"{'scenario':<32}{'$/yr':>8}{'MaxDD$':>9}{'yr/DD':>7}{'sd$':>7}{'<-500':>7}"
          f"{'<-1k':>6}{'<-2k':>6}{'EOD flat?':>11}")
    for (label, eh, xh, prior), (_, si, _) in zip(SCENARIOS, rows):
        print(f"{label:<32}{si['yr']:>8,.0f}{si['maxdd']:>9,.0f}"
              f"{si['yr']/abs(si['maxdd']):>7.2f}{si['sd']:>7.0f}{si['lt500']:>7}"
              f"{si['lt1k']:>6}{si['lt2k']:>6}{'no (holds)' if prior else 'yes':>11}")

    # ---- cost sweep ------------------------------------------------------------
    print("\n" + "-" * 100)
    print("3. COST SWEEP -- $/night by round-trip cost (ticks; 1 MGC tick = $1.00)")
    print("-" * 100)
    sweep = (0, 1, 2, 4, 8)
    print(f"{'scenario':<32}" + "".join(f"{f'{t}tk':>9}" for t in sweep) + f"{'breakeven':>11}")
    for label, eh, xh, prior in SCENARIOS:
        gross = window_pnl(o_is, c_is, eh, xh, prior)
        m = gross.mean()
        row = f"{label:<32}" + "".join(f"{m - t*TICK*DPP:>9.2f}" for t in sweep)
        print(row + f"{m/(TICK*DPP):>10.1f}tk")

    # ---- account tail ----------------------------------------------------------
    print("\n" + "-" * 100)
    print("4. NIGHTLY TAIL, 1 CONTRACT (the number that decides if an account survives)")
    print("-" * 100)
    print(f"{'scenario':<32}{'p5':>8}{'p1':>8}{'worst':>9}{'MAE-ish sd':>12}{'nights<-1k':>12}")
    for label, eh, xh, prior in SCENARIOS:
        p = window_pnl(o_is, c_is, eh, xh, prior, cost=cost)
        print(f"{label:<32}{np.percentile(p, 5):>8.0f}{np.percentile(p, 1):>8.0f}"
              f"{p.min():>9,.0f}{p.std(ddof=1):>12.0f}{(p < -1000).sum():>12}")

    # ---- stability -------------------------------------------------------------
    print("\n" + "-" * 100)
    print("5. STABILITY of the overnight block (18:00 -> 06:00), net")
    print("-" * 100)
    on = window_pnl(o_is, c_is, 18, 5, cost=cost)
    yearly = on.groupby(on.index.year).agg(["count", "sum", "mean"])
    yearly.columns = ["nights", "$total", "$/night"]
    if oos_ok:
        on_os = window_pnl(o_os, c_os, 18, 5, ref=ref, cost=cost)
        y2 = on_os.groupby(on_os.index.year).agg(["count", "sum", "mean"])
        y2.columns = yearly.columns
        yearly = pd.concat([y2, yearly]).sort_index()
    print(yearly.round(1).to_string())
    mid = on.index[len(on) // 2]
    a, b = on[on.index <= mid], on[on.index > mid]
    print(f"\nIn-sample split at {mid.date()}: 1st half Sharpe {stats(a)['sharpe']:.2f} "
          f"(${stats(a)['mean']:.2f}/nt) | 2nd half {stats(b)['sharpe']:.2f} "
          f"(${stats(b)['mean']:.2f}/nt)")
    dow = on.groupby(on.index.dayofweek).mean()
    print("By weekday of ENTRY ($/night): "
          + "  ".join(f"{d}={dow.get(i, np.nan):.2f}"
                      for i, d in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
                      if i in dow.index))

    # ---- correlation to the MNQ sleeve ----------------------------------------
    mnq_path = DATA / "MNQ_5min_databento.parquet"
    if mnq_path.exists():
        print("\n" + "-" * 100)
        print("6. DIVERSIFICATION vs THE MNQ OVERNIGHT SLEEVE (overlapping nights)")
        print("-" * 100)
        o_m, c_m = load_cells("MNQ_5min_databento.parquet")
        mnq_on = pd.Series((c_m[5] - o_m[18]).dropna() * 2.0 - 0.50)
        j = pd.concat([on.rename("MGC"), mnq_on.rename("MNQ")], axis=1).dropna()
        both = j["MGC"] + j["MNQ"]
        print(f"overlap {len(j):,} nights  |  correlation {j['MGC'].corr(j['MNQ']):+.3f}")
        for nm, s in (("MGC 1x", j["MGC"]), ("MNQ 1x", j["MNQ"]), ("both 1x", both)):
            st = stats(s)
            print(f"  {nm:<9}${st['mean']:>7.2f}/nt  Sharpe {st['sharpe']:>5.2f}  "
                  f"MaxDD ${st['maxdd']:>8,.0f}  worst ${st['worst']:>8,.0f}  "
                  f"nights<-1k {st['lt1k']:>3}")

    # ---- hour-window scan vs sign-flip null ------------------------------------
    if args.scan:
        print("\n" + "-" * 100)
        print("7. HOUR-WINDOW SCAN vs SIGN-FLIP PERMUTATION NULL")
        print("-" * 100)
        cols, labels = [], []
        for i in range(len(SESSION_HOURS)):
            for j2 in range(i + 1, min(i + 14, len(SESSION_HOURS))):
                eh, xh = SESSION_HOURS[i], SESSION_HOURS[j2]
                cols.append(window_pnl(o_is, c_is, eh, xh, cost=cost))
                labels.append(f"{eh:02d}:00->{(xh+1)%24:02d}:00")
        M = pd.concat(cols, axis=1).dropna()
        M.columns = labels
        shp = M.mean() / M.std(ddof=1) * np.sqrt(252)
        rng = np.random.default_rng(args.seed)
        X = M.values
        null = np.empty(args.draws)
        for d in range(args.draws):
            f = rng.choice([-1.0, 1.0], size=len(X))[:, None]
            y = X * f
            null[d] = np.nanmax(y.mean(0) / y.std(0, ddof=1) * np.sqrt(252))
        best = shp.max()
        p = float((null >= best).mean())
        print(f"{len(labels)} contiguous windows, {len(M):,} common nights, "
              f"{args.draws} sign-flip draws")
        print(f"best window {shp.idxmax()}  Sharpe {best:.2f}")
        print(f"null best-of-{len(labels)}: median {np.median(null):.2f}  "
              f"95th {np.percentile(null, 95):.2f}  max {null.max():.2f}  -> p = {p:.3f}")
        pre = "18:00->06:00"
        if pre in shp.index:
            single = float((null >= shp[pre]).mean())
            print(f"pre-specified {pre}: Sharpe {shp[pre]:.2f}, rank "
                  f"{int((shp > shp[pre]).sum()) + 1} of {len(shp)}, "
                  f"best-of-N p {single:.3f}")
        print("\ntop 10 scanned windows (in-sample Sharpe, NET):")
        print(shp.sort_values(ascending=False).head(10).round(2).to_string())

    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()
