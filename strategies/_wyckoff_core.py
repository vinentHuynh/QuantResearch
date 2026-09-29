"""Chart-timeframe port of Wyckoff [theUltimator5]'s Auto entry engine.

The source is the user-supplied Pine v6 indicator.  This module deliberately
omits its drawings, historical label storage and higher-timeframe *display*
selection.  It emits decisions on the bar that confirms them; Workbench owns
next-open execution and all exits.  Numerical thresholds below are the Pine
constants, not optimized parameters.

The port has not been verified against a TradingView bar-by-bar signal export.
In particular, exact tie handling for ``ta.pivothigh/low`` and differences in
session-adjusted OHLCV can prevent parity.  Never treat drawn pivot timestamps
as decision timestamps.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor, isnan, sqrt

import numpy as np
import pandas as pd


NONE, ACC, DIST = 0, 1, -1
A, B, C, D, E = 1, 2, 3, 4, 5
MARKUP, MARKDOWN = 1, -1


@dataclass
class WS:
    stopSide: int = 0
    outcome: int = 0
    phase: int = 0
    ev: str = ""
    startBar: int | None = None
    pivLen: int | None = None
    birthTrend: float = float("nan")
    ctxBull: bool = False
    ctxBear: bool = False
    climaxBar: int | None = None
    climaxPrice: float = float("nan")
    climaxEff: float = float("nan")
    climaxSpr: float = float("nan")
    climaxATR: float = float("nan")
    absorbed: bool = False
    origHigh: float = float("nan")
    origLow: float = float("nan")
    rangeHigh: float = float("nan")
    rangeLow: float = float("nan")
    arRunPrice: float = float("nan")
    arRunBar: int | None = None
    arOK: bool = False
    arBar: int | None = None
    stCount: int = 0
    stN: int = 0
    stEffSum: float = 0.0
    stSprSum: float = 0.0
    lastGoodEff: float = float("nan")
    lastGoodSpr: float = float("nan")
    stBar: int | None = None
    stPrice: float = float("nan")
    edge1: float = float("nan")
    edge2: float = float("nan")
    edge3: float = float("nan")
    oppCount: int = 0
    opN: int = 0
    opEffSum: float = 0.0
    opSprSum: float = 0.0
    opLastBar: int | None = None
    opLastPrice: float = float("nan")
    travCount: int = 0
    lastZone: int = 0
    lastZoneBar: int | None = None
    lastBadBar: int | None = None
    bStartBar: int | None = None
    cReadyBar: int | None = None
    dStartBar: int | None = None
    eStartBar: int | None = None
    pend: bool = False
    pendEdge: int = 0
    pendStartBar: int | None = None
    pendExtBar: int | None = None
    pendExt: float = float("nan")
    pendEff: float = float("nan")
    pendSpr: float = float("nan")
    pendCoolBar: int | None = None
    provEdge: int = 0
    provBar: int | None = None
    provPrice: float = float("nan")
    provEff: float = float("nan")
    provSpr: float = float("nan")
    provScore: int = 0
    exc: bool = False
    excTested: bool = False
    excBar: int | None = None
    excPrice: float = float("nan")
    excEff: float = float("nan")
    excSpr: float = float("nan")
    testBar: int | None = None
    testPrice: float = float("nan")
    testScore: int = 0
    strBar: int | None = None
    strScore: int = 0
    lpsBar: int | None = None
    lpsScore: int = 0
    entryBar: int | None = None
    entryKind: str = ""
    outCount: int = 0
    lastEventBar: int | None = None
    lastActBar: int | None = None
    cfPrior: bool = False
    cfClimax: bool = False
    cfAR: bool = False
    cfST: bool = False
    cfExc: bool = False
    cfTest: bool = False
    cfStrength: bool = False
    cfLPS: bool = False
    cfAccept: bool = False


def _ok(x: float) -> bool:
    return not isnan(x)


def _nz(x: float, substitute: float = 0.0) -> float:
    return x if _ok(x) else substitute


def _round(x: float) -> int:
    # All uses in this engine are nonnegative; Pine rounds half upward.
    return floor(x + 0.5)


def _prior_trend_score(
    i: int, n: int, end_off: int, atr: np.ndarray, closes: np.ndarray,
    ph_hist: list[float], pl_hist: list[float], long_sma: np.ndarray,
    tick: float,
) -> float:
    e = max(end_off, 0)
    if i - e - n < 0:
        return 0.0
    net = closes[i - e] - closes[i - e - n]
    unit = max(_nz(atr[i - e], atr[i]), tick)
    disp = max(-3.0, min(3.0, net / (unit * sqrt(n)))) * 15.0
    path = 0.0
    hh = ll = lh = hl = 0
    last_ph = last_pl = float("nan")
    for k in range(n - 1, -1, -1):
        j = i - e - k
        path += abs(closes[j] - closes[j - 1])
        p_h, p_l = ph_hist[j], pl_hist[j]
        if _ok(p_h):
            if _ok(last_ph):
                hh += p_h > last_ph
                lh += p_h < last_ph
            last_ph = p_h
        if _ok(p_l):
            if _ok(last_pl):
                hl += p_l > last_pl
                ll += p_l < last_pl
            last_pl = p_l
    er = abs(net) / path if path > 0 else 0.0
    er_part = (1.0 if net >= 0 else -1.0) * er * 25.0
    swings = hh + ll + lh + hl
    swing_part = (hh + hl - lh - ll) / swings * 20.0 if swings else 0.0
    se, ss = long_sma[i - e], long_sma[i - e - n]
    sma_part = 10.0 if _ok(se) and _ok(ss) and se > ss else -10.0 if _ok(se) and _ok(ss) and se < ss else 0.0
    return max(-100.0, min(100.0, disp + er_part + swing_part + sma_part))


def _rma_tr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    tr = np.empty(len(close), dtype=float)
    tr[0] = high[0] - low[0]
    for i in range(1, len(close)):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    result = np.full(len(close), np.nan)
    if len(close) >= period:
        result[period - 1] = float(np.mean(tr[:period]))
        for i in range(period, len(close)):
            result[i] = (result[i - 1] * (period - 1) + tr[i]) / period
    return result


def _pivot(data: np.ndarray, i: int, p: int, high: bool) -> float:
    """Pine style right-confirmed pivot; prefer the latest equal extreme."""
    c = i - p
    if c - p < 0:
        return float("nan")
    v = data[c]
    left, right = data[c - p:c], data[c + 1:i + 1]
    if high:
        return v if v >= max(left) and v > max(right) else float("nan")
    return v if v <= min(left) and v < min(right) else float("nan")


def _phase_b_min_bars(p: int, range_atr: float) -> int:
    return max(30, min(_round(max(p * 6.0, range_atr * p)), 60))


def _phase_idle_limit(phase: int, has_ar: bool, p: int) -> int | None:
    if phase == A:
        return max(45, p * 6) if has_ar else max(30, p * 4)
    if phase == B:
        return max(125, p * 20)
    if phase == C:
        return max(50, p * 8)
    if phase == D:
        return max(100, p * 16)
    return None


def _range_atr(s: WS, current_atr: float, tick: float) -> float:
    return abs(s.rangeHigh - s.rangeLow) / max(_nz(s.climaxATR, current_atr), tick) if _ok(s.rangeHigh) and _ok(s.rangeLow) else 0.0


def _confidence(s: WS) -> int:
    done = s.cfTest or (s.cfExc and s.cfStrength)
    return (10 * s.cfPrior + 15 * s.cfClimax + 10 * s.cfAR + 15 * s.cfST
            + 15 * done + 15 * s.cfStrength + 10 * s.cfLPS + 10 * s.cfAccept)


def _validation(s: WS, i: int, p: int, trend: float, current_atr: float, tick: float) -> int:
    if s.stopSide == NONE:
        return 0
    r_atr = _range_atr(s, current_atr, tick)
    b_age = max(i - s.bStartBar, 0) if s.bStartBar is not None else 0
    bad_age = i - s.lastBadBar if s.lastBadBar is not None else -1
    clean = bad_age < 0 or bad_age >= _round(p * 2.0)
    cause = b_age / max(p * 6.0, 1.0) + s.travCount * 0.5 + (0.5 if r_atr >= 1.5 else 0.0)
    terminal = (s.cfTest and (not s.exc or s.excTested)) or (s.cfExc and s.cfStrength)
    birth = _nz(s.birthTrend, trend)
    score = (10 if abs(birth) >= 35 else 5 if abs(birth) >= 15 else 0)
    score += 15 if s.absorbed else 0
    score += 10 if 1.5 <= r_atr <= 8.0 else 5 if 1.125 <= r_atr <= 12.0 else 0
    score += 15 if s.stCount >= 2 else 8 if s.stCount >= 1 else 0
    score += 15 if s.oppCount >= 1 and s.travCount >= 2 else 8 if s.oppCount >= 1 or s.travCount >= 1 else 0
    score += 10 if clean else 0
    score += 10 if cause >= 3 else 5 if cause >= 1.5 else 0
    score += 10 if terminal else 0
    score += 3 if s.cfStrength else 0
    score += 2 if s.cfLPS else 0
    return min(score, 100)


def _mature(s: WS, i: int, p: int, atr: float, tick: float) -> bool:
    r_atr = _range_atr(s, atr, tick)
    b_age = i - s.bStartBar if s.bStartBar is not None else 0
    bad_age = i - s.lastBadBar if s.lastBadBar is not None else -1
    clean = bad_age < 0 or bad_age >= _round(p * 2.0)
    improving = (s.stN >= 2 and _ok(s.lastGoodEff) and _ok(s.lastGoodSpr)
                 and s.lastGoodEff <= s.stEffSum / s.stN
                 and s.lastGoodSpr <= s.stSprSum / s.stN * 1.05)
    support = int(s.oppCount >= 1) + int(s.travCount >= 2) + int(clean) + int(improving)
    return (s.phase == B and b_age >= _phase_b_min_bars(p, r_atr)
            and s.stCount >= 2 and 1.125 <= r_atr <= 16.0 and support >= 2)


def _hard_level(s: WS, side: int) -> float:
    if side == ACC:
        return s.excPrice if s.exc and s.outcome == ACC and _ok(s.excPrice) else s.rangeLow if not _ok(s.origLow) else min(s.origLow, _nz(s.rangeLow, s.origLow))
    return s.excPrice if s.exc and s.outcome == DIST and _ok(s.excPrice) else s.rangeHigh if not _ok(s.origHigh) else max(s.origHigh, _nz(s.rangeHigh, s.origHigh))


def _robust_edge(e1: float, e2: float, e3: float, orig: float, low_edge: bool) -> float:
    if _ok(e1) and _ok(e2) and _ok(e3):
        med = sorted((e1, e2, e3))[1]
    elif _ok(e1) and _ok(e2):
        med = ((e1 + e2) / 2.0 + orig) / 2.0
    elif _ok(e1):
        med = (e1 + orig) / 2.0
    else:
        med = orig
    return max(orig, med) if low_edge else min(orig, med)


def _event(s: WS, kind: str, i: int) -> None:
    s.ev = kind
    s.lastEventBar = i
    s.lastActBar = i


def _test_class(near: bool, holds: bool, close_ok: bool, effort: float, spread: float, ref_effort: float, ref_spread: float) -> int:
    if not near:
        return 0
    if not holds:
        return 3
    return 1 if close_ok and effort <= ref_effort * 0.9 and spread <= ref_spread * 0.9 else 2


def _register_st(s: WS, i: int, pivot_bar: int, price: float, effort: float, spread: float, score: int, tick: float) -> None:
    s.stCount += 1
    s.stN += 1
    s.stEffSum += effort
    s.stSprSum += spread
    s.lastGoodEff = effort
    s.lastGoodSpr = spread
    s.stBar = pivot_bar
    s.stPrice = price
    s.edge3, s.edge2, s.edge1 = s.edge2, s.edge1, price
    if s.stopSide == ACC:
        s.rangeLow = _robust_edge(s.edge1, s.edge2, s.edge3, s.origLow, True)
    else:
        s.rangeHigh = _robust_edge(s.edge1, s.edge2, s.edge3, s.origHigh, False)
    s.cfST = True
    _event(s, "ST", i)


def _register_opp(s: WS, i: int, pivot_bar: int, price: float, effort: float, spread: float) -> None:
    s.oppCount += 1
    s.opN += 1
    s.opEffSum += effort
    s.opSprSum += spread
    s.opLastBar = pivot_bar
    s.opLastPrice = price
    s.lastActBar = i


def _clear_terminal(s: WS) -> None:
    s.exc = s.excTested = False
    s.excBar = None
    s.excPrice = s.excEff = s.excSpr = float("nan")
    s.testBar = None
    s.testPrice = float("nan")
    s.testScore = 0
    s.cfExc = s.cfTest = False
    s.cReadyBar = None


def _demote(s: WS, i: int) -> None:
    _clear_terminal(s)
    s.outcome = NONE
    s.phase = B
    s.strBar = s.lpsBar = s.dStartBar = None
    s.strScore = s.lpsScore = 0
    s.cfStrength = s.cfLPS = False
    s.provEdge = 0
    s.pend = False
    s.outCount = 0
    s.lastBadBar = s.lastActBar = i


def _promote_d(s: WS, i: int, side: int, score: int) -> None:
    s.outcome = side
    s.phase = D
    s.dStartBar = s.strBar = i
    s.strScore = score
    s.cfStrength = True
    s.pend = False
    s.outCount = 0
    _event(s, "SOS" if side == ACC else "SOW", i)


def _entry_quality(s: WS, i: int, strictness: str, atr: float, trend: float,
                   close: float, event_age_bars: float, tick: float) -> bool:
    min_conf = {"Conservative": 75, "Standard": 60, "Aggressive": 55}[strictness]
    min_ready = {"Conservative": 7, "Standard": 6, "Aggressive": 5}[strictness]
    val_floor = 60 if strictness == "Conservative" else 50
    val = _validation(s, i, s.pivLen or 4, trend, atr, tick)
    conf = _confidence(s)
    bull = s.outcome == ACC
    dist_atr = ((close - s.rangeHigh) if bull else (s.rangeLow - close)) / max(atr, tick) if _ok(s.rangeHigh) and _ok(s.rangeLow) else 99.0
    terminal = (s.exc and s.excTested) or (not s.exc and s.cfTest)
    ready = sum((s.outcome != NONE, s.phase >= C, terminal, s.cfStrength,
                 s.cfLPS, conf >= min_conf, val >= val_floor,
                 dist_atr <= 2.0, event_age_bars <= 50.0))
    return conf >= min_conf and val >= val_floor and ready >= min_ready


def generate_entries(bars: pd.DataFrame, strictness: str = "Standard") -> pd.Series:
    """Return +1/-1/0 Auto entry decisions on completed NQ bars.

    The input is time-ordered, has a timezone-aware bar-open DatetimeIndex and
    ``open/high/low/close/volume`` columns, and includes any warmup bars.  The
    returned index is unchanged.  The caller must apply next-open execution;
    this routine neither shifts decisions nor creates positions.
    """
    if strictness not in ("Aggressive", "Standard", "Conservative"):
        raise ValueError("strictness must be Aggressive, Standard, or Conservative")
    if not isinstance(bars.index, pd.DatetimeIndex) or bars.index.tz is None:
        raise ValueError("bars must have a timezone-aware DatetimeIndex")
    if not bars.index.is_monotonic_increasing or bars.index.has_duplicates:
        raise ValueError("bars index must be strictly increasing")
    required = ("open", "high", "low", "close", "volume")
    if any(name not in bars for name in required):
        raise ValueError("bars requires open/high/low/close/volume")
    if bars.empty:
        return pd.Series(dtype=np.int8, index=bars.index)

    o, h, l, c = (bars[name].to_numpy(dtype=float) for name in required[:4])
    raw_volume = np.nan_to_num(bars.volume.to_numpy(dtype=float), nan=0.0)
    if not np.isfinite(o).all() or not np.isfinite(h).all() or not np.isfinite(l).all() or not np.isfinite(c).all():
        raise ValueError("OHLC must be finite")
    n_bars = len(bars)
    tick = 0.25  # NQ's syminfo.mintick.
    spr = np.maximum(h - l, tick)
    # Pine's effort fallback applies only if no positive volume has appeared
    # yet in the chart history, including the current bar.
    eff = np.where(np.cumsum(raw_volume) <= 0.0, spr, raw_volume)
    a_raw = _rma_tr(h, l, c, 14)
    a_all = np.where(np.isfinite(a_raw), a_raw, spr)
    avg_eff_raw = pd.Series(eff).rolling(50, min_periods=50).mean().to_numpy()
    atr_base = pd.Series(a_all).rolling(50, min_periods=50).mean().to_numpy()
    long_sma = pd.Series(c).rolling(200, min_periods=200).mean().to_numpy()
    recent_eff = pd.Series(eff).rolling(3, min_periods=3).mean().to_numpy()
    times = bars.index.asi8
    if n_bars > 1:
        differences = np.diff(times)
        period_ns = int(pd.Series(differences[differences > 0]).mode().iloc[0])
    else:
        period_ns = 1

    decisions = np.zeros(n_bars, dtype=np.int8)
    s = WS()
    regime = NONE
    regime_bar: int | None = None
    last_pl_bar: int | None = None
    last_ph_bar: int | None = None
    live_lengths: list[int] = []
    ph_hist: list[float] = []
    pl_hist: list[float] = []
    dn_eff_history: list[float] = []
    up_eff_history: list[float] = []

    for i in range(n_bars):
        a = float(a_all[i])
        a_prev = float(_nz(a_raw[i - 1], a)) if i > 0 else a
        unit = max(a, tick)
        avg_eff = float(_nz(avg_eff_raw[i], eff[i]))
        avg_eff_prev = float(_nz(avg_eff_raw[i - 1], avg_eff)) if i > 0 else avg_eff
        c_pos = (c[i] - l[i]) / spr[i]
        rel_e = eff[i] / max(avg_eff, 1e-10)
        spr_atr = spr[i] / unit
        prior_lo = float(np.min(l[max(0, i - 30):i])) if i else float("nan")
        prior_hi = float(np.max(h[max(0, i - 30):i])) if i else float("nan")
        eff_hi_prior = float(np.max(eff[max(0, i - 30):i])) if i else float("nan")
        new_low = _ok(prior_lo) and l[i] <= prior_lo
        new_high = _ok(prior_hi) and h[i] >= prior_hi
        a_ratio = a / atr_base[i] if _ok(atr_base[i]) and atr_base[i] > 0 else 1.0
        live_len = max(2, min(10, _round(4 * a_ratio)))
        pre_len = live_lengths[i - 3] if i >= 3 else live_len
        live_lengths.append(live_len)

        p_len = s.pivLen if s.phase != NONE and s.pivLen is not None else live_len
        ph = _pivot(h, i, p_len, True)
        pl = _pivot(l, i, p_len, False)
        ph_hist.append(ph)
        pl_hist.append(pl)
        piv_bar = i - p_len
        p_a = max(_nz(a_raw[piv_bar], a), tick) if piv_bar >= 0 else a
        p_eff = eff[piv_bar] if piv_bar >= 0 else eff[i]
        p_spr = spr[piv_bar] if piv_bar >= 0 else spr[i]
        p_cpos = (c[piv_bar] - l[piv_bar]) / p_spr if piv_bar >= 0 else c_pos
        p_avg_eff = _nz(avg_eff_raw[piv_bar], avg_eff) if piv_bar >= 0 else avg_eff

        trend_bars = max(25, min(200, _round(live_len * 8.0)))
        trend_end = max(2, min(8, _round(live_len * 0.75)))
        trend_score = _prior_trend_score(i, trend_bars, trend_end, a_all, c, ph_hist, pl_hist, long_sma, tick)
        down_trend = trend_score <= -15.0
        up_trend = trend_score >= 15.0
        strong_trend = abs(trend_score) >= 35.0
        long_bull = (i > 20 and _ok(long_sma[i - 1]) and _ok(long_sma[i - 20])
                     and c[i - 1] > long_sma[i - 1] > long_sma[i - 20])
        long_bear = (i > 20 and _ok(long_sma[i - 1]) and _ok(long_sma[i - 20])
                     and c[i - 1] < long_sma[i - 1] < long_sma[i - 20])

        # Preliminary-support calculations are omitted: they only populate
        # displayed PS/PSY anchors and do not affect campaign or Auto entries.
        effort2 = max(rel_e, 0.01) * max(spr_atr, 0.01)
        dn_eff = max((c[i - 1] if i else c[i]) - c[i], 0.0) / unit / effort2
        up_eff = max(c[i] - (c[i - 1] if i else c[i]), 0.0) / unit / effort2
        dn_eff_history.append(dn_eff)
        up_eff_history.append(up_eff)

        hi_inv = float(np.max(c[max(0, i - 1):i + 1]))
        lo_inv = float(np.min(c[max(0, i - 1):i + 1]))
        hi_dep = float(np.max(c[max(0, i - 2):i + 1]))
        lo_dep = float(np.min(c[max(0, i - 2):i + 1]))
        hi_a = hi_dep
        lo_a = lo_dep
        hi_conf = hi_dep
        lo_conf = lo_dep
        hi_dir = float(np.max(c[max(0, i - 4):i + 1]))
        lo_dir = float(np.min(c[max(0, i - 4):i + 1]))
        hi_fail = hi_dep
        lo_fail = lo_dep
        mb_low = float(np.min(l[max(0, i - 4):i + 1]))
        mb_high = float(np.max(h[max(0, i - 4):i + 1]))
        mb_eff_ratio = float(np.sum(eff[max(0, i - 4):i + 1])) / max(avg_eff * 5.0, 1e-10)
        mb_sos = (c[i] - mb_low) / unit >= 2.0 and mb_eff_ratio >= 1.1 and c_pos >= 0.5
        mb_sow = (mb_high - c[i]) / unit >= 2.0 and mb_eff_ratio >= 1.1 and c_pos <= 0.5
        res3_up = max(c[i] - c[i - 3] if i >= 3 else 0.0, 0.0) / unit
        res3_dn = max(c[i - 3] - c[i] if i >= 3 else 0.0, 0.0) / unit
        sos_score = int(rel_e >= 1.15) + int(spr_atr >= 1.15) + int(c_pos >= 0.65) + int(c[i] > o[i] and c[i] - o[i] >= a * 0.5)
        sow_score = int(rel_e >= 1.15) + int(spr_atr >= 1.15) + int(c_pos <= 0.35) + int(c[i] < o[i] and o[i] - c[i] >= a * 0.5)
        close1 = c[i - 1] if i else c[i]
        close2 = c[i - 2] if i >= 2 else c[i]
        test_bit = strength_bit = lps_bit = False

        # Retire campaigns that failed or aged out, before considering a new
        # climax on the same completed bar (Pine 1181-1276).
        p0 = s.pivLen or live_len
        rk0 = _ok(s.rangeHigh) and _ok(s.rangeLow)
        r_h0, r_l0 = s.rangeHigh, s.rangeLow
        r_ht0 = max(r_h0 - r_l0, tick) if rk0 else float("nan")
        r_mid0 = (r_h0 + r_l0) / 2.0 if rk0 else float("nan")
        struct_age = i - s.startBar if s.startBar is not None else 0
        age_ok_bull = regime != MARKDOWN or struct_age >= 25
        age_ok_bear = regime != MARKUP or struct_age >= 25
        probe_open = s.pend and s.pendStartBar is not None and i - s.pendStartBar <= max(3, _round(p0 * 0.75))
        hard_bull = _hard_level(s, ACC)
        hard_bear = _hard_level(s, DIST)
        reset = False
        if s.phase == A:
            age = i - s.climaxBar
            inv_acc = s.stopSide == ACC and hi_inv < s.climaxPrice - a * 0.5
            inv_dist = s.stopSide == DIST and lo_inv > s.climaxPrice + a * 0.5
            absorb_exp = not s.absorbed and age > 8
            no_ar = not s.arOK and age > 30
            over_ext = s.arOK and _ok(s.arRunPrice) and abs(s.arRunPrice - s.climaxPrice) / max(_nz(s.climaxATR, a), tick) > 15.0
            a_buf = max(r_ht0 * 0.3, a * 0.75) if rk0 else float("nan")
            depart = age > 30 and rk0 and ((s.stopSide == ACC and lo_a > r_h0 + a_buf) or (s.stopSide == DIST and hi_a < r_l0 - a_buf))
            reset = inv_acc or inv_dist or absorb_exp or no_ar or over_ext or depart
        if s.phase == C and not probe_open and not reset:
            reset = ((s.outcome == ACC and _ok(hard_bull) and hi_inv < hard_bull - a * 0.5)
                     or (s.outcome == DIST and _ok(hard_bear) and lo_inv > hard_bear + a * 0.5))
        if s.phase == D and rk0 and not reset:
            if s.outcome == ACC:
                if _ok(hard_bull) and hi_inv < hard_bull - a * 0.5:
                    reset = True
                elif hi_fail < r_mid0:
                    _demote(s, i)
            elif s.outcome == DIST:
                if _ok(hard_bear) and lo_inv > hard_bear + a * 0.5:
                    reset = True
                elif lo_fail > r_mid0:
                    _demote(s, i)
        if s.phase == E and rk0 and not reset:
            failed = hi_fail < r_mid0 if s.outcome == ACC else lo_fail > r_mid0
            old = s.eStartBar is not None and i - s.eStartBar > 300
            reset = failed or old
        idle_limit = _phase_idle_limit(s.phase, s.arOK, p0)
        if not reset and not probe_open and idle_limit is not None and s.lastActBar is not None and i - s.lastActBar > idle_limit:
            reset = True
        if reset:
            s = WS()

        relax_k = 0.8 if strong_trend else 1.0
        vol_hit = eff[i] >= avg_eff_prev * 1.8 * relax_k
        spr_hit = spr[i] >= a_prev * 1.5 * relax_k
        exceptional = (_ok(eff_hi_prior) and eff[i] >= eff_hi_prior) or spr[i] >= a_prev * 1.5 * 1.5
        sc_score = (int(down_trend) + int(new_low) + int(vol_hit) + int(spr_hit)
                    + int(c_pos >= 0.35) + int(exceptional))
        bc_score = (int(up_trend) + int(new_high) + int(vol_hit) + int(spr_hit)
                    + int(c_pos <= 0.65) + int(exceptional))
        seed_open = s.phase in (NONE, E)
        can_sc = seed_open or (s.phase == A and s.stopSide == ACC and l[i] < s.climaxPrice)
        can_bc = seed_open or (s.phase == A and s.stopSide == DIST and h[i] > s.climaxPrice)
        is_sc = can_sc and down_trend and new_low and vol_hit and spr_hit and sc_score >= 5
        is_bc = can_bc and up_trend and new_high and vol_hit and spr_hit and bc_score >= 5
        if is_sc != is_bc:
            side = ACC if is_sc else DIST
            recent_markup = regime == MARKUP and regime_bar is not None and i - regime_bar <= 400
            recent_markdown = regime == MARKDOWN and regime_bar is not None and i - regime_bar <= 400
            s = WS(stopSide=side, phase=A, startBar=i, pivLen=pre_len,
                   birthTrend=trend_score, ctxBull=recent_markup or long_bull,
                   ctxBear=recent_markdown or long_bear, climaxBar=i,
                   climaxPrice=l[i] if side == ACC else h[i],
                   climaxEff=eff[i], climaxSpr=spr[i], climaxATR=a,
                   cfPrior=True)
            if side == ACC:
                s.origLow = s.rangeLow = l[i]
            else:
                s.origHigh = s.rangeHigh = h[i]
            _event(s, "SC" if side == ACC else "BC", i)

        if s.phase == A and not s.absorbed and s.climaxBar is not None:
            abs_age = i - s.climaxBar
            if 3 <= abs_age <= 8:
                r_eff = recent_eff[i]
                effort_ok = _ok(r_eff) and r_eff >= avg_eff * 0.9
                r_low = float(np.min(l[max(0, i - 2):i + 1]))
                r_high = float(np.max(h[max(0, i - 2):i + 1]))
                acc_abs = s.stopSide == ACC and r_low >= s.climaxPrice - s.climaxATR * 0.5 and c[i] >= s.climaxPrice + s.climaxATR * 0.35
                dst_abs = s.stopSide == DIST and r_high <= s.climaxPrice + s.climaxATR * 0.5 and c[i] <= s.climaxPrice - s.climaxATR * 0.35
                if effort_ok and (acc_abs or dst_abs):
                    s.absorbed = s.cfClimax = True
                    s.lastActBar = i

        if s.phase == A and s.arBar is None and s.climaxBar is not None and s.climaxBar < i <= s.climaxBar + 30:
            if s.stopSide == ACC:
                if not _ok(s.arRunPrice) or h[i] > s.arRunPrice:
                    s.arRunPrice = h[i]
                    s.arRunBar = i
                s.arOK = s.arOK or s.arRunPrice - s.climaxPrice >= a * 2.0
            else:
                if not _ok(s.arRunPrice) or l[i] < s.arRunPrice:
                    s.arRunPrice = l[i]
                    s.arRunBar = i
                s.arOK = s.arOK or s.climaxPrice - s.arRunPrice >= a * 2.0
        if s.phase == A and s.arOK and s.absorbed and s.arBar is None:
            if s.stopSide == ACC:
                s.rangeHigh = s.origHigh = s.arRunPrice
            else:
                s.rangeLow = s.origLow = s.arRunPrice

        p1 = s.pivLen or live_len
        rk1 = _ok(s.rangeHigh) and _ok(s.rangeLow)
        r_h1, r_l1 = s.rangeHigh, s.rangeLow
        orig_ht1 = max(_nz(s.origHigh, r_h1) - _nz(s.origLow, r_l1), tick) if rk1 else float("nan")
        mature1 = _mature(s, i, p1, a, tick)
        new_pl = _ok(pl) and (last_pl_bar is None or piv_bar > last_pl_bar)
        new_ph = _ok(ph) and (last_ph_bar is None or piv_bar > last_ph_bar)
        if new_pl:
            last_pl_bar = piv_bar
        if new_ph:
            last_ph_bar = piv_bar
        pl_used = ph_used = False

        # Mature Phase B can promote a right-confirmed terminal pivot directly
        # to Phase C, without a Spring/UTAD (Pine 1328-1369).
        if new_pl and s.phase == B and mature1 and rk1:
            ref_st = s.stopSide == ACC
            ref_n = s.stN if ref_st else s.opN
            ref_bar = s.stBar if ref_st else s.opLastBar
            ref_price = s.stPrice if ref_st else s.opLastPrice
            if ref_n > 0 and ref_bar is not None:
                ref_eff = (s.stEffSum if ref_st else s.opEffSum) / ref_n
                ref_spr = (s.stSprSum if ref_st else s.opSprSum) / ref_n
                later = piv_bar >= ref_bar + 3
                near = pl <= r_l1 + p_a * 1.25
                holds = pl >= min(_nz(s.origLow, r_l1), r_l1) - p_a * 0.15
                higher = not _ok(ref_price) or pl >= ref_price - p_a * 0.15
                qv, qs = p_eff <= ref_eff * 0.85, p_spr <= ref_spr * 0.85
                nv, ns = p_eff <= ref_eff * 1.05, p_spr <= ref_spr * 1.05
                score = int(qv) + int(qs) + int(p_cpos >= 0.5)
                if later and near and holds and higher and ((qv and ns) or (qs and nv)) and score >= 2:
                    s.phase, s.outcome = C, ACC
                    s.cReadyBar = i
                    s.testBar, s.testPrice, s.testScore = piv_bar, pl, score
                    s.cfTest = True
                    s.pend = False
                    _event(s, "CTEST", i)
                    test_bit = pl_used = True
        if new_ph and s.phase == B and mature1 and rk1:
            ref_st = s.stopSide == DIST
            ref_n = s.stN if ref_st else s.opN
            ref_bar = s.stBar if ref_st else s.opLastBar
            ref_price = s.stPrice if ref_st else s.opLastPrice
            if ref_n > 0 and ref_bar is not None:
                ref_eff = (s.stEffSum if ref_st else s.opEffSum) / ref_n
                ref_spr = (s.stSprSum if ref_st else s.opSprSum) / ref_n
                later = piv_bar >= ref_bar + 3
                near = ph >= r_h1 - p_a * 1.25
                holds = ph <= max(_nz(s.origHigh, r_h1), r_h1) + p_a * 0.15
                lower = not _ok(ref_price) or ph <= ref_price + p_a * 0.15
                qv, qs = p_eff <= ref_eff * 0.85, p_spr <= ref_spr * 0.85
                nv, ns = p_eff <= ref_eff * 1.05, p_spr <= ref_spr * 1.05
                score = int(qv) + int(qs) + int(p_cpos <= 0.5)
                if later and near and holds and lower and ((qv and ns) or (qs and nv)) and score >= 2:
                    s.phase, s.outcome = C, DIST
                    s.cReadyBar = i
                    s.testBar, s.testPrice, s.testScore = piv_bar, ph, score
                    s.cfTest = True
                    s.pend = False
                    _event(s, "CTEST", i)
                    test_bit = ph_used = True

        # First ST fixes the AR retroactively and starts Phase B.  Those pivot
        # timestamps are never used as entry execution timestamps.
        if new_pl and not pl_used and s.phase == A and s.stopSide == ACC and s.absorbed and s.arOK and s.arRunBar is not None and piv_bar > s.arRunBar:
            zone_top = s.origLow + (s.arRunPrice - s.origLow) * 0.25
            near = abs(pl - s.origLow) <= p_a * 0.75 or pl <= zone_top
            holds = pl >= s.origLow - p_a * 0.75
            close_ok = p_cpos >= 0.45
            test_class = _test_class(near, holds, close_ok, p_eff, p_spr, s.climaxEff, s.climaxSpr)
            score = (int(near) + int(p_eff <= s.climaxEff * 0.9)
                     + int(p_spr <= s.climaxSpr * 0.9) + int(holds) + int(close_ok) + 1)
            age_ok = piv_bar - s.startBar >= max(6, p1 * 2)
            space_ok = piv_bar - s.arRunBar >= max(2, p1)
            if near:
                s.lastActBar = i
            if test_class == 1 and score >= 4 and age_ok and space_ok:
                s.arBar = s.arRunBar
                s.cfAR = True
                s.origHigh = s.rangeHigh = s.arRunPrice
                _register_st(s, i, piv_bar, pl, p_eff, p_spr, score, tick)
                s.phase, s.bStartBar = B, piv_bar
                pl_used = True
        if new_ph and not ph_used and s.phase == A and s.stopSide == DIST and s.absorbed and s.arOK and s.arRunBar is not None and piv_bar > s.arRunBar:
            zone_bottom = s.origHigh - (s.origHigh - s.arRunPrice) * 0.25
            near = abs(ph - s.origHigh) <= p_a * 0.75 or ph >= zone_bottom
            holds = ph <= s.origHigh + p_a * 0.75
            close_ok = p_cpos <= 0.55
            test_class = _test_class(near, holds, close_ok, p_eff, p_spr, s.climaxEff, s.climaxSpr)
            score = (int(near) + int(p_eff <= s.climaxEff * 0.9)
                     + int(p_spr <= s.climaxSpr * 0.9) + int(holds) + int(close_ok) + 1)
            age_ok = piv_bar - s.startBar >= max(6, p1 * 2)
            space_ok = piv_bar - s.arRunBar >= max(2, p1)
            if near:
                s.lastActBar = i
            if test_class == 1 and score >= 4 and age_ok and space_ok:
                s.arBar = s.arRunBar
                s.cfAR = True
                s.origLow = s.rangeLow = s.arRunPrice
                _register_st(s, i, piv_bar, ph, p_eff, p_spr, score, tick)
                s.phase, s.bStartBar = B, piv_bar
                ph_used = True

        rk1 = _ok(s.rangeHigh) and _ok(s.rangeLow)
        if new_pl and not pl_used and s.phase == B and rk1 and piv_bar > s.bStartBar:
            height = max(s.rangeHigh - s.rangeLow, tick)
            if s.stopSide == ACC:
                near = (abs(pl - s.rangeLow) <= p_a * 0.75
                        or abs(pl - s.origLow) <= p_a * 0.75
                        or pl <= s.rangeLow + height * 0.25)
                holds = pl >= s.origLow - p_a * 0.75
                close_ok = p_cpos >= 0.45
                test_class = _test_class(near, holds, close_ok, p_eff, p_spr, s.climaxEff, s.climaxSpr)
                score = int(near) + int(p_eff <= s.climaxEff * 0.9) + int(p_spr <= s.climaxSpr * 0.9) + int(holds) + int(close_ok) + 1
                is_prov = s.provEdge == ACC and s.provBar is not None and abs(piv_bar - s.provBar) <= p1
                if near:
                    s.lastActBar = i
                if test_class == 3 and not is_prov:
                    s.lastBadBar = piv_bar
                elif test_class == 1 and score >= 4:
                    _register_st(s, i, piv_bar, pl, p_eff, p_spr, score, tick)
            else:
                if pl < s.rangeLow and pl >= _nz(s.origLow, s.rangeLow) - orig_ht1 * 0.15:
                    s.rangeLow = pl
                height = max(s.rangeHigh - s.rangeLow, tick)
                near = pl <= s.rangeLow + p_a * 0.75 or pl <= s.rangeLow + height * 0.25
                inside = pl >= _nz(s.origLow, s.rangeLow) - orig_ht1 * 0.15
                controlled = p_eff <= s.climaxEff * 1.2 and p_spr <= s.climaxSpr * 1.2
                if near and inside and controlled and (s.opLastBar is None or piv_bar > s.opLastBar):
                    _register_opp(s, i, piv_bar, pl, p_eff, p_spr)
        if new_ph and not ph_used and s.phase == B and rk1 and piv_bar > s.bStartBar:
            height = max(s.rangeHigh - s.rangeLow, tick)
            if s.stopSide == DIST:
                near = (abs(ph - s.rangeHigh) <= p_a * 0.75
                        or abs(ph - s.origHigh) <= p_a * 0.75
                        or ph >= s.rangeHigh - height * 0.25)
                holds = ph <= s.origHigh + p_a * 0.75
                close_ok = p_cpos <= 0.55
                test_class = _test_class(near, holds, close_ok, p_eff, p_spr, s.climaxEff, s.climaxSpr)
                score = int(near) + int(p_eff <= s.climaxEff * 0.9) + int(p_spr <= s.climaxSpr * 0.9) + int(holds) + int(close_ok) + 1
                is_prov = s.provEdge == DIST and s.provBar is not None and abs(piv_bar - s.provBar) <= p1
                if near:
                    s.lastActBar = i
                if test_class == 3 and not is_prov:
                    s.lastBadBar = piv_bar
                elif test_class == 1 and score >= 4:
                    _register_st(s, i, piv_bar, ph, p_eff, p_spr, score, tick)
            else:
                if ph > s.rangeHigh and ph <= _nz(s.origHigh, s.rangeHigh) + orig_ht1 * 0.15:
                    s.rangeHigh = ph
                height = max(s.rangeHigh - s.rangeLow, tick)
                near = ph >= s.rangeHigh - p_a * 0.75 or ph >= s.rangeHigh - height * 0.25
                inside = ph <= _nz(s.origHigh, s.rangeHigh) + orig_ht1 * 0.15
                controlled = p_eff <= s.climaxEff * 1.2 and p_spr <= s.climaxSpr * 1.2
                if near and inside and controlled and (s.opLastBar is None or piv_bar > s.opLastBar):
                    _register_opp(s, i, piv_bar, ph, p_eff, p_spr)

        if s.phase == B and _ok(s.rangeHigh) and _ok(s.rangeLow):
            height = max(s.rangeHigh - s.rangeLow, tick)
            lo_zone = new_pl and pl <= s.rangeLow + height * 0.25
            hi_zone = new_ph and ph >= s.rangeHigh - height * 0.25
            zone = (-1 if lo_zone else 1) if lo_zone != hi_zone else 0
            if zone and (s.lastZoneBar is None or piv_bar > s.lastZoneBar):
                if s.lastZone and zone != s.lastZone:
                    s.travCount += 1
                    s.lastActBar = i
                s.lastZone, s.lastZoneBar = zone, piv_bar

        # Right-confirmed pivot tests and LPS/LPSY.  The event is drawn on the
        # pivot in Pine but exists for a decision only here, at bar i.
        if new_pl and s.phase == C and s.outcome == ACC and s.exc and not s.excTested and piv_bar > s.excBar and _ok(s.rangeLow):
            near = pl <= s.rangeLow + p_a * 1.25
            keeps = pl >= s.excPrice - p_a * 0.15
            score = int(p_eff <= s.excEff * 0.8) + int(p_spr <= s.excSpr * 0.8) + int(p_cpos >= 0.5)
            if near and keeps and score >= 2:
                s.excTested = True
                s.cReadyBar = i
                s.testBar, s.testPrice, s.testScore = piv_bar, pl, score
                s.cfTest = True
                _event(s, "TEST", i)
                test_bit = True
        if new_ph and s.phase == C and s.outcome == DIST and s.exc and not s.excTested and piv_bar > s.excBar and _ok(s.rangeHigh):
            near = ph >= s.rangeHigh - p_a * 1.25
            keeps = ph <= s.excPrice + p_a * 0.15
            score = int(p_eff <= s.excEff * 0.8) + int(p_spr <= s.excSpr * 0.8) + int(p_cpos <= 0.5)
            if near and keeps and score >= 2:
                s.excTested = True
                s.cReadyBar = i
                s.testBar, s.testPrice, s.testScore = piv_bar, ph, score
                s.cfTest = True
                _event(s, "TEST", i)
                test_bit = True

        if new_pl and s.phase == D and s.outcome == ACC and s.strBar is not None and piv_bar > s.strBar and _ok(s.rangeHigh):
            hard = _hard_level(s, ACC)
            on_side = _ok(hard) and pl > hard - p_a * 0.15
            creek = pl >= s.rangeHigh - p_a * 1.5
            score = int(p_eff <= p_avg_eff) + int(p_spr <= p_a) + int(p_cpos >= 0.45)
            if on_side and creek and score >= 2:
                s.lpsBar, s.lpsScore = i, score
                s.cfLPS = True
                _event(s, "LPS", i)
                lps_bit = True
        if new_ph and s.phase == D and s.outcome == DIST and s.strBar is not None and piv_bar > s.strBar and _ok(s.rangeLow):
            hard = _hard_level(s, DIST)
            on_side = _ok(hard) and ph < hard + p_a * 0.15
            ice = ph <= s.rangeLow + p_a * 1.5
            score = int(p_eff <= p_avg_eff) + int(p_spr <= p_a) + int(p_cpos <= 0.55)
            if on_side and ice and score >= 2:
                s.lpsBar, s.lpsScore = i, score
                s.cfLPS = True
                _event(s, "LPSY", i)
                lps_bit = True

        p2 = s.pivLen or live_len
        rk2 = _ok(s.rangeHigh) and _ok(s.rangeLow)
        r_h2, r_l2 = s.rangeHigh, s.rangeLow
        rec_limit = max(3, _round(p2 * 0.75))
        mature2 = _mature(s, i, p2, a, tick)
        b_age2 = i - s.bStartBar if s.bStartBar is not None else 0
        probe_b = s.phase == B and s.stCount >= 1 and b_age2 >= max(3, p2 * 2)
        probe_c_lo = s.phase == C and s.outcome == ACC and not s.exc
        probe_c_hi = s.phase == C and s.outcome == DIST and not s.exc
        if rk2 and not s.pend and (s.pendCoolBar is None or i > s.pendCoolBar):
            pen_lo, pen_hi = r_l2 - l[i], h[i] - r_h2
            ok_lo = (probe_b or probe_c_lo) and a * 0.15 <= pen_lo <= a * 2.5
            ok_hi = (probe_b or probe_c_hi) and a * 0.15 <= pen_hi <= a * 2.5
            if ok_lo != ok_hi:
                s.pend = True
                s.pendEdge = ACC if ok_lo else DIST
                s.pendStartBar = s.pendExtBar = i
                s.pendExt = l[i] if ok_lo else h[i]
                s.pendEff, s.pendSpr = eff[i], spr[i]
        if s.pend and rk2 and s.phase in (B, C):
            if s.pendEdge == ACC and l[i] < s.pendExt:
                s.pendExt, s.pendExtBar = l[i], i
                s.pendEff = max(_nz(s.pendEff), eff[i])
                s.pendSpr = max(_nz(s.pendSpr), spr[i])
            elif s.pendEdge == DIST and h[i] > s.pendExt:
                s.pendExt, s.pendExtBar = h[i], i
                s.pendEff = max(_nz(s.pendEff), eff[i])
                s.pendSpr = max(_nz(s.pendSpr), spr[i])
            rec_age = i - s.pendStartBar
            recovered = c[i] > r_l2 if s.pendEdge == ACC else c[i] < r_h2
            depth = (r_l2 - s.pendExt) if s.pendEdge == ACC else (s.pendExt - r_h2)
            depth_ok = a * 0.15 <= depth <= a * 2.5
            if s.pendEdge == ACC:
                rec_score = (int(c_pos >= 0.55) + int(eff[i] <= avg_eff * 1.5)
                             + int(c[i] > o[i]) + int(spr[i] >= a * 0.5))
            else:
                rec_score = (int(c_pos <= 0.45) + int(eff[i] <= avg_eff * 1.5)
                             + int(c[i] < o[i]) + int(spr[i] >= a * 0.5))
            if recovered and depth_ok and rec_age <= rec_limit and rec_score >= 3:
                edge = s.pendEdge
                if s.phase == B and not mature2:
                    s.provEdge = edge
                    s.provBar, s.provPrice = s.pendExtBar, s.pendExt
                    s.provEff, s.provSpr, s.provScore = s.pendEff, s.pendSpr, rec_score
                    s.lastActBar = i
                    s.pend = False
                else:
                    if s.phase == C:
                        _clear_terminal(s)
                    s.exc = True
                    s.excTested = False
                    s.excBar, s.excPrice = s.pendExtBar, s.pendExt
                    s.excEff, s.excSpr = s.pendEff, s.pendSpr
                    s.cfExc = True
                    s.outcome, s.phase = edge, C
                    s.cReadyBar = None
                    s.pend = False
                    s.provEdge = 0
                    _event(s, "SPRING" if edge == ACC else "UTAD", i)
            elif rec_age > rec_limit or (not depth_ok and depth > a * 2.5):
                if s.phase == B:
                    s.lastBadBar = i
                s.pend = False
                s.pendCoolBar = i + p2

        if s.phase == C and s.exc and not s.excTested and rk2:
            if s.outcome == ACC and l[i] < s.excPrice and l[i] >= r_l2 - a * 2.5:
                s.excPrice, s.excBar = l[i], i
                s.excEff = max(_nz(s.excEff), eff[i])
                s.excSpr = max(_nz(s.excSpr), spr[i])
            elif s.outcome == DIST and h[i] > s.excPrice and h[i] <= r_h2 + a * 2.5:
                s.excPrice, s.excBar = h[i], i
                s.excEff = max(_nz(s.excEff), eff[i])
                s.excSpr = max(_nz(s.excSpr), spr[i])

        # Promote a developed Phase C to D on confirmed strength/weakness.
        if s.phase == C and rk2 and not s.pend:
            min_c_to_d = max(3, p2 // 2)
            formal = not s.exc or s.excTested
            anchor = s.cReadyBar if s.cReadyBar is not None else s.excBar
            age_ready = anchor is not None and i - anchor >= min_c_to_d
            c_val = _validation(s, i, p2, trend_score, a, tick)
            c_val_d = c_val if formal else min(100, c_val + 13)
            c_conf = _confidence(s)
            c_conf_d = c_conf if formal else min(100, c_conf + 30)
            height = max(r_h2 - r_l2, tick)
            if age_ready and c_val_d >= 60 and c_conf_d >= 45:
                if s.outcome == ACC and age_ok_bull:
                    dominant = r_l2 + height * 0.65
                    breakout = c[i] > r_h2 + a * 0.15
                    dom_ok = breakout or (c[i] >= dominant and close1 >= dominant and (formal or close2 >= dominant))
                    req = 3 if formal else 2
                    qualified = sos_score >= req or mb_sos or (not formal and res3_up >= 1.0)
                    if dom_ok and qualified:
                        _promote_d(s, i, ACC, sos_score)
                        strength_bit = True
                elif s.outcome == DIST and age_ok_bear:
                    dominant = r_h2 - height * 0.65
                    breakout = c[i] < r_l2 - a * 0.15
                    dom_ok = breakout or (c[i] <= dominant and close1 <= dominant and (formal or close2 <= dominant))
                    req = 3 if formal else 2
                    qualified = sow_score >= req or mb_sow or (not formal and res3_dn >= 1.0)
                    if dom_ok and qualified:
                        _promote_d(s, i, DIST, sow_score)
                        strength_bit = True

        # Phase B can adopt a provisional excursion on a later departure.
        reset_late = False
        if s.phase == B and rk2 and not s.pend:
            height = max(r_h2 - r_l2, tick)
            buffer = max(height * 0.35, a * 0.75)
            up_accept = c[i] > r_h2 + a * 0.15 and close1 > r_h2 + a * 0.15
            dn_accept = c[i] < r_l2 - a * 0.15 and close1 < r_l2 - a * 0.15
            up_sustain = lo_dep > r_h2 + buffer
            dn_sustain = hi_dep < r_l2 - buffer
            up_go = (up_accept and (sos_score >= 3 or mb_sos)) or up_sustain
            dn_go = (dn_accept and (sow_score >= 3 or mb_sow)) or dn_sustain
            prov_limit = max(50, p2 * 8)
            if up_go and not dn_go:
                provisional = s.provEdge == ACC and s.provBar is not None and i - s.provBar <= prov_limit
                if age_ok_bull and provisional and mature2:
                    s.exc = True
                    s.excTested = False
                    s.excBar, s.excPrice = s.provBar, s.provPrice
                    s.excEff, s.excSpr = s.provEff, s.provSpr
                    s.cfExc = True
                    s.outcome = ACC
                    s.provEdge = 0
                    _promote_d(s, i, ACC, sos_score)
                    strength_bit = True
                elif up_sustain and not provisional:
                    reset_late = True
            elif dn_go and not up_go:
                provisional = s.provEdge == DIST and s.provBar is not None and i - s.provBar <= prov_limit
                if age_ok_bear and provisional and mature2:
                    s.exc = True
                    s.excTested = False
                    s.excBar, s.excPrice = s.provBar, s.provPrice
                    s.excEff, s.excSpr = s.provEff, s.provSpr
                    s.cfExc = True
                    s.outcome = DIST
                    s.provEdge = 0
                    _promote_d(s, i, DIST, sow_score)
                    strength_bit = True
                elif dn_sustain and not provisional:
                    reset_late = True
        if reset_late:
            s = WS()

        # A second SOS/SOW can occur after LPS/LPSY, on this same bar.
        if s.phase == D and s.outcome == ACC and s.ev == "LPS" and _ok(s.rangeHigh):
            if c[i] > s.rangeHigh + a * 0.15 and rel_e >= 1.15 and c_pos >= 0.65:
                s.strBar, s.strScore = i, sos_score
                _event(s, "SOS", i)
                strength_bit = True
        if s.phase == D and s.outcome == DIST and s.ev == "LPSY" and _ok(s.rangeLow):
            if c[i] < s.rangeLow - a * 0.15 and rel_e >= 1.15 and c_pos <= 0.35:
                s.strBar, s.strScore = i, sow_score
                _event(s, "SOW", i)
                strength_bit = True

        if s.phase == D and _ok(s.rangeHigh) and _ok(s.rangeLow):
            conf = _confidence(s)
            d_age = i - s.dStartBar if s.dStartBar is not None else 0
            d_min = max(4, s.pivLen or live_len)
            if s.outcome == ACC:
                s.outCount = s.outCount + 1 if c[i] > s.rangeHigh else 0
                opposite_ok = regime != MARKDOWN or s.cfLPS
                standard_e = (s.cfLPS and s.lpsBar is not None and i - s.lpsBar >= 3
                              and d_age >= d_min and lo_conf > s.rangeHigh and conf >= 55)
                direct_e = (not s.cfLPS and d_age >= max(d_min, 5)
                            and lo_dir > s.rangeHigh and conf >= 75)
                if (standard_e or direct_e) and opposite_ok:
                    s.cfAccept, s.phase, s.eStartBar = True, E, i
                    regime, regime_bar = MARKUP, i
                    _event(s, "E", i)
            elif s.outcome == DIST:
                s.outCount = s.outCount + 1 if c[i] < s.rangeLow else 0
                opposite_ok = regime != MARKUP or s.cfLPS
                standard_e = (s.cfLPS and s.lpsBar is not None and i - s.lpsBar >= 3
                              and d_age >= d_min and hi_conf < s.rangeLow and conf >= 55)
                direct_e = (not s.cfLPS and d_age >= max(d_min, 5)
                            and hi_dir < s.rangeLow and conf >= 75)
                if (standard_e or direct_e) and opposite_ok:
                    s.cfAccept, s.phase, s.eStartBar = True, E, i
                    regime, regime_bar = MARKDOWN, i
                    _event(s, "E", i)

        # Pine's Auto entry gate (1729-1747), one entry per campaign.  This is
        # evaluated after all bar-close state changes, never on the pivot bar.
        if s.entryBar is None and s.outcome != NONE:
            event_age = ((times[i] - times[s.lastEventBar]) / period_ns
                         if s.lastEventBar is not None else 999.0)
            quality = _entry_quality(s, i, strictness, a, trend_score, c[i], event_age, tick)
            aggressive_test = strictness == "Aggressive" and test_bit and quality
            aggressive_strength = strictness == "Aggressive" and strength_bit and quality and s.testBar is None
            standard_test = strictness == "Standard" and test_bit and quality and s.testScore >= 2
            standard_lps = strictness == "Standard" and lps_bit and quality
            conservative_lps = strictness == "Conservative" and lps_bit and quality
            if aggressive_test or aggressive_strength or standard_test or standard_lps or conservative_lps:
                s.entryBar = i
                s.entryKind = ("LPS" if standard_lps or conservative_lps
                               else "SOS" if aggressive_strength else "TEST")
                decisions[i] = s.outcome

    return pd.Series(decisions, index=bars.index, dtype=np.int8, name="wyckoff_entry")
