"""Frozen, causal NQ research interpretation of the AW Reversal PDF.

This is an event-v1 strategy, not a claim that discretionary chart reading can be
replicated exactly. All features consumed by on_close are released no earlier
than their source candle's completion. Entry plans are logged for risk audits.
"""

from __future__ import annotations

from collections import Counter
import json
import math

import numpy as np
import pandas as pd

from strategies._cme_index_calendar import session_close_et


CT = 'America/Chicago'
ONE_MINUTE = pd.Timedelta(minutes=1)
THREE_MINUTES = pd.Timedelta(minutes=3)
TWO_HOURS = pd.Timedelta(hours=2)


STRATEGY = {
    'schema_version': 2,
    'source_files': ['strategies/aw_model_nq.py', 'strategies/_cme_index_calendar.py'],
    'id': 'aw-model-nq',
    'name': 'AW Reversal - NQ frozen research interpretation',
    'version': '0.2.0',
    'description': 'NQ-only completed-bar AW Reversal: pre-open 2H bias, premarked ERL sweep, 3m MSS/FVG, and first later 1m retrace.',
    'migration_scope': 'One fixed, causal interpretation of chapters 5, 6, 9-11 of the AW Model PDF, not author-verified rules. Pre-08:30 CT five 2H proxies are: (1) latest 2H failure to make a lower low/higher high; (2) premarked eligible external high/low still beyond price; (3) position below/above midpoint of the last five completed 2H bars; (4) an untouched strict 2H FVG wholly above/below price; (5) latest two completed 2H bars have higher highs/lows or lower highs/lows. A strict 3-of-5 directional vote is required by default. Prior day means the prior complete 08:30-to-calendar-declared-close CT cash session, including shortened valid sessions; overnight means prior 17:00-08:30 CT. Each 3m neckline is a strict pivot with two left and two right candles confirmed before a completed 3m wick-through/close-back sweep; the last two confirmed pivot highs and lows must both rise for shorts or fall for longs. The first strong 3m close through it within five subsequent completed 3m bars must be the middle candle of a strict 3-bar FVG. First later 1m physical gap touch schedules one NQ contract at the immediately following minute open, expiring if that minute is missing; event-v1 cannot model a resting limit entry. Stop is one tick beyond the swept extreme, target the nearest premarked opposing level still untaken at entry, with no discretionary R:R floor. A confirmed, still-untaken 3m pivot more than two points beyond planned entry and strictly before the target is frozen as a proxy first internal level; a later completed 1m close beyond it moves the stop to actual fill plus/minus two NQ points. If none exists, no BE move; subsequent discretionary trailing is omitted. Two submitted entries maximum per CT day; CME daytime calendar closes positions by 15:00 CT or earlier declared close. Intraminute fills, gaps, stop-first collisions, costs and final liquidation follow event-v1. Unadjusted continuous-contract roll gaps can contaminate 2H/3m structures because the workbench 1m selected bars omit instrument_id. No CPI/NFP/FOMC exclusion, equal-high/low pools, IFVG preference, manual significance, dollar-risk sizing, daily loss cap, or flip-candle entry. One contract can exceed the PDF risk ceiling. Historical execution is not live-trading validation.',
    'execution_model': 'event-v1',
    'timeframes': ['1m'],
    'default_session': 'full-trading-day',
    'required_session': 'full-trading-day',
    'default_warmup_days': 60,
    'capabilities': ['equity', 'trades', 'positions'],
    'parameters': {
        'bias_policy': {'type': 'enum', 'default': 'aligned-only',
                        'choices': ['aligned-only', 'mixed-flex', 'unrestricted'],
                        'description': 'Aligned-only requires the frozen 2H majority; mixed-flex trades the majority when clear and allows either reversal on NONE/mixed days; unrestricted ignores the vote.'},
        'bias_required': {'type': 'boolean', 'default': True,
                          'description': 'Legacy compatibility: false with aligned-only selects unrestricted, preserving earlier no-bias run inputs.'},
        'impulse_multiple': {'type': 'number', 'default': 1.25, 'minimum': 1.0, 'maximum': 3.0,
                             'description': 'MSS directional body divided by median of the preceding 20 complete 3m bodies.'},
    },
}


def _effective_bias_policy(parameters):
    """Retain old ``bias_required=False`` reruns without changing saved snapshots."""
    policy = parameters.get('bias_policy', 'aligned-only')
    if policy == 'aligned-only' and not parameters.get('bias_required', True):
        return 'unrestricted'
    return policy


def _allowed_sides(policy, bias):
    """Return (short, long) from the bias frozen before the cash open."""
    if policy == 'unrestricted' or (policy == 'mixed-flex' and bias == 0):
        return True, True
    # Bearish bias: take buy-side liquidity then short toward sell-side ERL.
    # Bullish bias: take sell-side liquidity then long toward buy-side ERL.
    return bias == -1, bias == 1


def validate(parameters, request):
    if request['dataset']['symbol'] != 'NQ':
        raise ValueError('AW Reversal research requires full-size NQ')
    if request['timeframe'] != '1m' or request['session'] != 'full-trading-day':
        raise ValueError('AW Reversal research requires 1m full-trading-day bars')
    if request.get('delay_bars', 0):
        raise ValueError('Event strategies do not support additional execution delay')
    if float(request['dataset']['tick_size']) <= 0:
        raise ValueError('NQ tick size must be positive')


class _Record:
    """Small record that also loads under Workbench's unregistered module loader."""

    __slots__ = ()

    def __eq__(self, other):
        return (type(self) is type(other) and
                all(getattr(self, name) == getattr(other, name)
                    for name in self.__slots__))

    def __repr__(self):
        fields = ', '.join(f'{name}={getattr(self, name)!r}' for name in self.__slots__)
        return f'{type(self).__name__}({fields})'


class DayLevels(_Record):
    __slots__ = ('date', 'pdh', 'pdl', 'onh', 'onl', 'bias',
                 'bull_votes', 'bear_votes', 'eligible')

    def __init__(self, date, pdh, pdl, onh, onl, bias,
                 bull_votes, bear_votes, eligible):
        self.date = date
        self.pdh = pdh
        self.pdl = pdl
        self.onh = onh
        self.onl = onl
        self.bias = bias
        self.bull_votes = bull_votes
        self.bear_votes = bear_votes
        self.eligible = eligible

    def price(self, name):
        return {'PDH': self.pdh, 'PDL': self.pdl,
                'ONH': self.onh, 'ONL': self.onl}[name]


class Candidate(_Record):
    __slots__ = ('side', 'level_name', 'level', 'neckline', 'extreme',
                 'sweep_ready', 'phase', 'mss_bars', 'mss_index',
                 'gap_low', 'gap_high', 'gap_ready')

    def __init__(self, side, level_name, level, neckline, extreme, sweep_ready,
                 phase='swept', mss_bars=0, mss_index=None,
                 gap_low=None, gap_high=None, gap_ready=None):
        self.side = side
        self.level_name = level_name
        self.level = level
        self.neckline = neckline
        self.extreme = extreme
        self.sweep_ready = sweep_ready
        self.phase = phase
        self.mss_bars = mss_bars
        self.mss_index = mss_index
        self.gap_low = gap_low
        self.gap_high = gap_high
        self.gap_ready = gap_ready


class EntryPlan(_Record):
    __slots__ = ('side', 'stop', 'target', 'internal', 'actual_entry', 'be_moved')

    def __init__(self, side, stop, target, internal, actual_entry=None, be_moved=False):
        self.side = side
        self.stop = stop
        self.target = target
        self.internal = internal
        self.actual_entry = actual_entry
        self.be_moved = be_moved


def _complete_resample(bars, interval, offset='0min'):
    """Use only contiguous minute candles whose nominal HTF end is known."""
    frame = bars[['open', 'high', 'low', 'close']].copy()
    frame.index = bars.index.tz_convert(CT)
    frame['_timestamp_ns'] = frame.index.asi8
    grouped = frame.resample(interval, label='left', closed='left',
                             origin='start_day', offset=offset)
    candles = grouped.agg({'open': 'first', 'high': 'max',
                           'low': 'min', 'close': 'last',
                           '_timestamp_ns': ['size', 'first', 'last']})
    candles.columns = ['open', 'high', 'low', 'close', 'n', 'first_ns', 'last_ns']
    width = pd.Timedelta(interval)
    expected = int(width / ONE_MINUTE)
    valid = ((candles.n == expected).to_numpy() &
             (candles.first_ns.to_numpy() == candles.index.asi8) &
             (candles.last_ns.to_numpy() == (candles.index + width - ONE_MINUTE).asi8))
    candles = candles.loc[valid, ['open', 'high', 'low', 'close']].copy()
    candles['ready'] = candles.index + width
    return candles


def _untouched_fvg_votes(htf, price, partial):
    """Any strict completed 2H gap, wholly above/below price and untouched."""
    above = below = False
    first = max(2, len(htf) - 20)
    for j in range(first, len(htf)):
        a, c = htf.iloc[j - 2], htf.iloc[j]
        gap = None
        if float(c.low) > float(a.high):
            gap = (float(a.high), float(c.low))
        elif float(c.high) < float(a.low):
            gap = (float(c.high), float(a.low))
        if gap is None:
            continue
        low, high = gap
        later = htf.iloc[j + 1:]
        if not later.empty and bool(((later.low <= high) & (later.high >= low)).any()):
            continue
        # The 2H candle containing 08:30 is unfinished, but its observed
        # 1m portion can already have filled an otherwise untouched HTF gap.
        if not partial.empty and bool(((partial.low <= high) & (partial.high >= low)).any()):
            continue
        above |= low > price
        below |= high < price
    return above, below


def _bias_votes(htf, levels, price, partial):
    if len(htf) < 5:
        return (False,) * 5, (False,) * 5
    previous, latest = htf.iloc[-2], htf.iloc[-1]
    high_range = float(htf.iloc[-5:].high.max())
    low_range = float(htf.iloc[-5:].low.min())
    midpoint = (high_range + low_range) / 2
    gap_above, gap_below = _untouched_fvg_votes(htf, price, partial)
    higher_flow = float(latest.high) > float(previous.high) and float(latest.low) > float(previous.low)
    lower_flow = float(latest.high) < float(previous.high) and float(latest.low) < float(previous.low)
    upper = any(levels.price(name) > price for name in ('PDH', 'ONH') if name in levels.eligible)
    lower = any(levels.price(name) < price for name in ('PDL', 'ONL') if name in levels.eligible)
    bull = (float(latest.low) >= float(previous.low), upper,
            price < midpoint, gap_above, higher_flow)
    bear = (float(latest.high) <= float(previous.high), lower,
            price > midpoint, gap_below, lower_flow)
    return bull, bear


def _daily_levels(bars, htf):
    local = bars.index.tz_convert(CT)
    dates = local.normalize()
    minutes = local.hour * 60 + local.minute
    rth = bars.loc[(minutes >= 510) & (minutes < 900), ['high', 'low']]
    rth_days = dates[(minutes >= 510) & (minutes < 900)]
    rth_summary = rth.groupby(rth_days).agg({'high': 'max', 'low': 'min'})
    rth_summary['n'] = rth.groupby(rth_days).size()
    expected = []
    for date in rth_summary.index:
        declared = session_close_et(date)
        regular = date + pd.Timedelta(hours=15)
        close = min(regular, declared.tz_convert(CT)) if declared is not None else date
        expected.append(max(0, int((close - (date + pd.Timedelta(hours=8, minutes=30))) / ONE_MINUTE)))
    rth_summary['complete'] = ((rth_summary.n.to_numpy() == np.asarray(expected)) &
                               (np.asarray(expected) > 0))
    result = {}
    for date in dates.unique():
        cutoff = date + pd.Timedelta(hours=8, minutes=30)
        last_preopen = cutoff - ONE_MINUTE
        end = local.searchsorted(cutoff, side='left')
        if end == 0 or local[end - 1] != last_preopen:
            continue
        prior = rth_summary.index.searchsorted(date, side='left') - 1
        if prior < 0 or date - rth_summary.index[prior] > pd.Timedelta(days=7):
            continue
        previous = rth_summary.iloc[prior]
        if not bool(previous.complete):
            continue
        overnight_start = date - pd.Timedelta(days=1) + pd.Timedelta(hours=17)
        begin = local.searchsorted(overnight_start, side='left')
        overnight = bars.iloc[begin:end]
        if len(overnight) < 750 or local[begin] != overnight_start:
            continue
        onh = float(overnight.high.max())
        onl = float(overnight.low.min())
        eligible = {'ONH', 'ONL'}
        pdh, pdl = float(previous.high), float(previous.low)
        if onh < pdh:
            eligible.add('PDH')
        if onl > pdl:
            eligible.add('PDL')
        stub = DayLevels(date.date(), pdh, pdl, onh, onl, 0,
                         (False,) * 5, (False,) * 5, frozenset(eligible))
        htf_end = htf.ready.searchsorted(cutoff, side='right')
        known = htf.iloc[:htf_end].tail(25)
        price = float(bars.close.iloc[end - 1])
        partial_begin = local.searchsorted(known.ready.iloc[-1], side='left') if len(known) else end
        partial = bars.iloc[partial_begin:end][['high', 'low']]
        bull, bear = _bias_votes(known, stub, price, partial)
        bull_count, bear_count = sum(bull), sum(bear)
        bias = 1 if bull_count >= 3 and bear_count < 3 else -1 if bear_count >= 3 and bull_count < 3 else 0
        result[date.date()] = DayLevels(date.date(), pdh, pdl, onh, onl,
                                        bias, bull, bear, frozenset(eligible))
    return result


class AWModelNQ:
    def __init__(self, bars, parameters, request):
        validate(parameters, request)
        if bars.empty or bars.index.tz is None or not bars.index.is_monotonic_increasing:
            raise ValueError('AW Reversal requires sorted timezone-aware 1m bars')
        self.parameters = parameters
        self.bias_policy = _effective_bias_policy(parameters)
        self.request = request
        self.tick = float(request['dataset']['tick_size'])
        self.local_start = bars.index.tz_convert(CT)
        self.ready = pd.DatetimeIndex(pd.to_datetime(bars.availability_time, utc=True)).tz_convert(CT)
        self.three = _complete_resample(bars, '3min')
        self.two = _complete_resample(bars, '2h', '1h')
        self.days = _daily_levels(bars, self.two)
        locations = np.searchsorted(self.ready.asi8, self.three.ready.array.asi8)
        self.three_at_minute = np.full(len(bars), -1, dtype=np.int32)
        inside = locations < len(bars)
        locations = locations[inside]
        known_indices = np.flatnonzero(inside)
        exact = self.ready.asi8[locations] == self.three.ready.array.asi8[known_indices]
        self.three_at_minute[locations[exact]] = known_indices[exact]
        self.high3 = self.three.high.to_numpy(dtype=float)
        self.low3 = self.three.low.to_numpy(dtype=float)
        self.open3 = self.three.open.to_numpy(dtype=float)
        self.close3 = self.three.close.to_numpy(dtype=float)
        self.start3 = self.three.index
        self.ready3 = pd.DatetimeIndex(self.three.ready)
        self.bodies3 = np.abs(self.close3 - self.open3)
        start = pd.Timestamp(request['start'], tz='UTC')
        end = pd.Timestamp(request['end'], tz='UTC') + pd.Timedelta(days=1)
        scored = np.asarray((bars.index >= start) & (self.ready.tz_convert('UTC') < end))
        self.last_called = int(np.flatnonzero(scored)[-1]) if scored.any() else len(bars) - 1
        self.day = None
        self.day_cutoff = None
        self.day_morning = None
        self.plan = None
        self.candidate = None
        self.other_candidates = []
        self.mixed_day = False
        self.entries_today = 0
        self.taken = set()
        self.taken_at_three_start = set()
        self.last_pivot_high = None
        self.last_pivot_low = None
        self.pivot_highs = []
        self.pivot_lows = []
        self.open_pivot_highs = []
        self.open_pivot_lows = []
        self.funnel = Counter()

    def _new_day(self, day, state):
        if self.day is not None and int(state['position']):
            raise ValueError('AW position carried across a CT calendar day; missing scheduled close')
        self.day = day
        self.day_cutoff = self._cutoff(day)
        self.day_morning = pd.Timestamp(day).tz_localize(CT) + pd.Timedelta(hours=8, minutes=30)
        self.candidate = None
        self.other_candidates = []
        self.mixed_day = (self.bias_policy == 'mixed-flex' and
                          day in self.days and self.days[day].bias == 0)
        self.entries_today = 0
        self.taken = set()
        self.taken_at_three_start = set()
        # Keep prior-evening confirmed 3m structure across CT midnight.
        self.plan = None
        if day in self.days:
            self.funnel['prepared_days'] += 1
            if self.days[day].bias:
                self.funnel['majority_bias_days'] += 1
            else:
                self.funnel['none_or_mixed_bias_days'] += 1

    def _entry_limit(self):
        # The mixed-day diagnostic takes the first valid reversal only.
        return 1 if self.mixed_day else 2

    def _cutoff(self, day):
        exchange = session_close_et(day)
        regular = pd.Timestamp(day).tz_localize(CT) + pd.Timedelta(hours=15)
        return min(regular, exchange.tz_convert(CT)) if exchange is not None else regular

    def _strong_mss(self, k, candidate):
        if k < 20 or self.start3[k] - self.start3[k - 20] != pd.Timedelta(minutes=60):
            return False
        body = self.bodies3[k]
        median = float(np.median(self.bodies3[k - 20:k]))
        width = self.high3[k] - self.low3[k]
        if median <= 0 or width <= 0:
            return False
        side = candidate.side
        directional = self.close3[k] > self.open3[k] if side > 0 else self.close3[k] < self.open3[k]
        edge = self.close3[k] >= self.high3[k] - 0.25 * width if side > 0 else self.close3[k] <= self.low3[k] + 0.25 * width
        return (directional and body >= self.parameters['impulse_multiple'] * median and
                body / width >= 0.60 and edge)

    def _mss_crossed(self, k, candidate):
        if k == 0 or self.start3[k] - self.start3[k - 1] != THREE_MINUTES:
            return False
        if candidate.side > 0:
            return self.close3[k] > candidate.neckline and self.close3[k - 1] <= candidate.neckline
        return self.close3[k] < candidate.neckline and self.close3[k - 1] >= candidate.neckline

    def _fvg(self, k, candidate):
        middle = candidate.mss_index
        if middle is None or k != middle + 1 or middle < 1:
            return None
        if self.start3[k] - self.start3[middle] != THREE_MINUTES or self.start3[middle] - self.start3[middle - 1] != THREE_MINUTES:
            return None
        if candidate.side > 0 and self.low3[k] > self.high3[middle - 1]:
            return float(self.high3[middle - 1]), float(self.low3[k])
        if candidate.side < 0 and self.high3[k] < self.low3[middle - 1]:
            return float(self.high3[k]), float(self.low3[middle - 1])
        return None

    def _try_sweep(self, k, state):
        if (not state['tradable'] or self.entries_today >= self._entry_limit() or
                state['position'] or state.get('position_at_open', 0)):
            return
        date = self.start3[k].date()
        levels = self.days.get(date)
        if levels is None:
            return
        opening = self.start3[k]
        ready = self.ready3[k]
        open_clock = opening.hour * 60 + opening.minute
        ready_clock = ready.hour * 60 + ready.minute
        if not (510 <= open_clock and ready_clock <= 630 and opening.date() == ready.date()) or ready >= self.day_cutoff:
            return
        allow_short, allow_long = _allowed_sides(self.bias_policy, levels.bias)
        matches = []
        for name in ('PDH', 'ONH'):
            level = levels.price(name)
            if (allow_short and name in levels.eligible and name not in self.taken_at_three_start and
                    self.high3[k] >= level + self.tick and self.close3[k] < level):
                matches.append((-1, name, level))
        for name in ('PDL', 'ONL'):
            level = levels.price(name)
            if (allow_long and name in levels.eligible and name not in self.taken_at_three_start and
                    self.low3[k] <= level - self.tick and self.close3[k] > level):
                matches.append((1, name, level))
        if not matches:
            return
        self.funnel['sweep_bar_matches'] += 1
        sides = {side for side, _, _ in matches}
        if len(sides) > 1:
            self.funnel['ambiguous_both_sides'] += 1
            return
        side, name, level = matches[0]
        overnight_start = pd.Timestamp(date).tz_localize(CT) - pd.Timedelta(days=1) + pd.Timedelta(hours=17)
        recent_highs = [value for value in self.pivot_highs if overnight_start <= value[1] < ready]
        recent_lows = [value for value in self.pivot_lows if overnight_start <= value[1] < ready]
        trend = (len(recent_highs) >= 2 and len(recent_lows) >= 2 and
                 ((recent_highs[-1][0] < recent_highs[-2][0] and
                   recent_lows[-1][0] < recent_lows[-2][0]) if side > 0 else
                  (recent_highs[-1][0] > recent_highs[-2][0] and
                   recent_lows[-1][0] > recent_lows[-2][0])))
        if not trend:
            self.funnel['sweep_without_prior_trend'] += 1
            return
        pivot = recent_highs[-1] if side > 0 else recent_lows[-1]
        if pivot is None:
            self.funnel['sweep_without_prior_neckline'] += 1
            return
        neckline, confirmed_at = pivot
        if (confirmed_at < overnight_start or confirmed_at >= ready or
                (side > 0 and neckline <= level) or (side < 0 and neckline >= level)):
            self.funnel['sweep_invalid_neckline'] += 1
            return
        extreme = float(self.low3[k] if side > 0 else self.high3[k])
        candidate = Candidate(side, name, level, neckline, extreme, ready)
        if self.candidate is None:
            self.candidate = candidate
        else:
            # NONE/mixed days can have independent buy- and sell-side sweeps
            # before either setup resolves. Track both until the first valid
            # chronological touch; aligned-only days keep their old behavior.
            self.other_candidates.append(candidate)
        self.funnel['neckline_sweeps'] += 1

    def _update_pivots(self, k):
        high, low = self.high3[k], self.low3[k]
        self.open_pivot_highs = [(p, t) for p, t in self.open_pivot_highs if high < p]
        self.open_pivot_lows = [(p, t) for p, t in self.open_pivot_lows if low > p]
        if k < 4 or self.start3[k] - self.start3[k - 4] != pd.Timedelta(minutes=12):
            return
        c = k - 2
        high_center, low_center = self.high3[c], self.low3[c]
        other_high = np.concatenate((self.high3[k - 4:c], self.high3[c + 1:k + 1]))
        other_low = np.concatenate((self.low3[k - 4:c], self.low3[c + 1:k + 1]))
        if high_center > float(other_high.max()):
            value = (float(high_center), self.ready3[k])
            self.last_pivot_high = value
            self.pivot_highs.append(value)
            self.pivot_highs = self.pivot_highs[-100:]
            self.open_pivot_highs.append(value)
            self.open_pivot_highs = self.open_pivot_highs[-100:]
        if low_center < float(other_low.min()):
            value = (float(low_center), self.ready3[k])
            self.last_pivot_low = value
            self.pivot_lows.append(value)
            self.pivot_lows = self.pivot_lows[-100:]
            self.open_pivot_lows.append(value)
            self.open_pivot_lows = self.open_pivot_lows[-100:]

    def _advance_candidate(self, candidate, k):
        """Advance one setup using this newly completed three-minute candle."""
        if candidate.phase == 'swept' and self.start3[k] >= candidate.sweep_ready:
            candidate.mss_bars += 1
            crossed = self._mss_crossed(k, candidate)
            if candidate.mss_bars > 5:
                self.funnel['expired_before_mss'] += 1
                return False
            elif crossed:
                if self._strong_mss(k, candidate):
                    candidate.phase = 'mss_pending'
                    candidate.mss_index = k
                    self.funnel['strong_mss'] += 1
                else:
                    self.funnel['weak_first_break'] += 1
                    return False
        elif candidate.phase == 'mss_pending':
            gap = self._fvg(k, candidate)
            if gap is None:
                self.funnel['mss_without_strict_fvg'] += 1
                return False
            else:
                candidate.gap_low, candidate.gap_high = gap
                candidate.gap_ready = self.ready3[k]
                candidate.phase = 'gap'
                self.funnel['confirmed_gap'] += 1
        return True

    def _on_three_close(self, k, state):
        active = ([self.candidate] if self.candidate is not None else []) + self.other_candidates
        survivors = [candidate for candidate in active if self._advance_candidate(candidate, k)]
        self.candidate = survivors[0] if survivors else None
        self.other_candidates = survivors[1:]
        # A level can be swept by a wick in this very candle; only previous
        # completed 3m bars disqualify it before the sweep decision.
        if self.candidate is None or self.mixed_day:
            self._try_sweep(k, state)
        self._update_pivots(k)
        self.taken_at_three_start = self.taken.copy()

    def _mark_external_touches(self, bar, ready):
        levels = self.days.get(self.day)
        start = ready - ONE_MINUTE
        if levels is None or start < self.day_morning or start >= self.day_cutoff:
            return
        for name in levels.eligible:
            price = levels.price(name)
            if ((name.endswith('H') and float(bar.high) >= price) or
                    (name.endswith('L') and float(bar.low) <= price)):
                self.taken.add(name)

    def _opposing_target(self, side, reference):
        levels = self.days.get(self.day)
        if levels is None:
            return None
        # Longs after a sell-side sweep aim at the nearest untaken buy-side
        # level; shorts after a buy-side sweep aim at sell-side liquidity.
        names = ('PDH', 'ONH') if side > 0 else ('PDL', 'ONL')
        values = [(levels.price(name), name) for name in names
                  if name in levels.eligible and name not in self.taken and
                  (levels.price(name) > reference if side > 0 else levels.price(name) < reference)]
        if not values:
            return None
        return min(values) if side > 0 else max(values)

    def _internal_level(self, side, entry_reference, target):
        pivots = self.open_pivot_highs if side > 0 else self.open_pivot_lows
        values = [price for price, _ in pivots
                  if (entry_reference + 2 < price < target if side > 0
                      else target < price < entry_reference - 2)]
        if not values:
            return None
        return min(values) if side > 0 else max(values)

    def _entry_on_touch(self, bar, state, ready):
        if ready.hour * 60 + ready.minute > 630 or ready >= self.day_cutoff or not state['tradable']:
            self.candidate = None
            self.other_candidates = []
            return None
        active = ([self.candidate] if self.candidate is not None else []) + self.other_candidates
        touched = [candidate for candidate in active
                   if candidate.phase == 'gap' and candidate.gap_ready is not None and
                   ready > candidate.gap_ready and
                   float(bar.high) >= candidate.gap_low and float(bar.low) <= candidate.gap_high]
        if not touched:
            return None
        if len({candidate.side for candidate in touched}) > 1:
            # A one-minute OHLC candle cannot reveal which opposing gap was
            # touched first. Do not choose the profitable direction afterward.
            self.funnel['ambiguous_opposing_gap_touches'] += 1
            self._consume_candidates(touched)
            return None
        for candidate in touched:
            self._consume_candidates((candidate,))
            self.funnel['first_gap_touches'] += 1
            order = self._entry_for_touched_candidate(candidate, bar, state, ready)
            if order is not None:
                if self.mixed_day:
                    self.candidate = None
                    self.other_candidates = []
                return order
        return None

    def _consume_candidates(self, consumed):
        remaining = [candidate for candidate in
                     ([self.candidate] if self.candidate is not None else []) + self.other_candidates
                     if all(candidate is not other for other in consumed)]
        self.candidate = remaining[0] if remaining else None
        self.other_candidates = remaining[1:]

    def _entry_for_touched_candidate(self, candidate, bar, state, ready):
        if (state['position'] or state.get('position_at_open', 0) or
                self.entries_today >= self._entry_limit()):
            self.funnel['touch_while_busy'] += 1
            return None
        side = candidate.side
        stop = candidate.extreme - self.tick if side > 0 else candidate.extreme + self.tick
        # The trigger candle can cross the stop before the next-open order.
        if (float(bar.low) <= stop if side > 0 else float(bar.high) >= stop):
            self.funnel['touch_hit_structural_stop'] += 1
            return None
        reference = float(bar.close)
        choice = self._opposing_target(side, reference)
        if choice is None:
            self.funnel['no_untaken_opposing_target'] += 1
            return None
        target, target_name = choice
        if not (stop < reference < target if side > 0 else target < reference < stop):
            self.funnel['nonpositive_planned_risk_or_reward'] += 1
            return None
        internal = self._internal_level(side, reference, target)
        self.plan = EntryPlan(side, stop, target, internal)
        self.entries_today += 1
        self.funnel['submitted_entries'] += 1
        risk = (reference - stop) if side > 0 else (stop - reference)
        print('AW_ENTRY ' + json.dumps({
            'signal_time': ready.isoformat(), 'side': side, 'stop': stop,
            'target': target, 'risk_points': risk, 'swept_level': candidate.level_name,
            'target_level': target_name, 'neckline': candidate.neckline,
            'fvg_low': candidate.gap_low, 'fvg_high': candidate.gap_high,
            'internal_level': internal,
            'bias': self.days[self.day].bias, 'bias_policy': self.bias_policy,
        }, sort_keys=True), flush=True)
        return {'target': side, 'timing': 'next-open',
                'expires_at': ready.isoformat(), 'bracket': (stop, target),
                'reason': 'aw-first-fvg-touch'}

    def _manage_position(self, bar, state, ready):
        position = int(state['position'])
        opened = int(state.get('position_at_open', position))
        if not position:
            if opened:
                self.plan = None
            return None
        if self.plan is not None and self.plan.actual_entry is None:
            self.plan.actual_entry = float(bar.open)
        if ready >= self.day_cutoff:
            self.plan = None
            return {'target': 0, 'timing': 'close', 'reason': 'aw-1500-or-early-close'}
        plan = self.plan
        if plan is None or plan.be_moved or plan.internal is None or plan.actual_entry is None:
            return None
        internal = plan.internal
        entry = plan.actual_entry
        if not (entry < internal < plan.target if position > 0 else plan.target < internal < entry):
            return None
        be_stop = entry + 2.0 if position > 0 else entry - 2.0
        if not (plan.stop < be_stop < plan.target if position > 0 else plan.target < be_stop < plan.stop):
            return None
        if not (internal > be_stop if position > 0 else internal < be_stop):
            return None
        reached = float(bar.close) >= internal if position > 0 else float(bar.close) <= internal
        if not reached:
            return None
        plan.be_moved = True
        self.funnel['be_updates'] += 1
        return {'target': position, 'timing': 'close',
                'bracket': (be_stop, plan.target), 'reason': 'aw-be-internal-pivot'}

    def _step(self, i, bar, state):
        day = self.local_start[i].date()
        ready = self.ready[i]
        if day != self.day:
            self._new_day(day, state)
        if ready >= self.day_cutoff:
            self.candidate = None
            self.other_candidates = []
        # A first-touch minute can arrive before its containing 3m candle
        # closes. Previously confirmed internal pivots can be taken meanwhile.
        high, low = float(bar.high), float(bar.low)
        self.open_pivot_highs = [(price, confirmed) for price, confirmed in self.open_pivot_highs
                                 if high < price]
        self.open_pivot_lows = [(price, confirmed) for price, confirmed in self.open_pivot_lows
                                if low > price]
        self._mark_external_touches(bar, ready)
        k = int(self.three_at_minute[i])
        if k >= 0:
            self._on_three_close(k, state)
        managed = self._manage_position(bar, state, ready)
        if managed is not None:
            return managed
        if state['position'] or state.get('position_at_open', 0):
            return None
        return self._entry_on_touch(bar, state, ready)

    def on_close(self, i, bar, state):
        decision = self._step(i, bar, state)
        if i == self.last_called:
            print('AW_FUNNEL ' + json.dumps(dict(sorted(self.funnel.items())), sort_keys=True), flush=True)
        return decision


def create_strategy(bars, parameters, request):
    return AWModelNQ(bars, parameters, request)
