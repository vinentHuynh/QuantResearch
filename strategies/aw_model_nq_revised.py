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
from strategies._aw_news_calendar import news_gate


CT = 'America/Chicago'
ONE_MINUTE = pd.Timedelta(minutes=1)
THREE_MINUTES = pd.Timedelta(minutes=3)
TWO_HOURS = pd.Timedelta(hours=2)


STRATEGY = {
    'schema_version': 2,
    'source_files': [
        'strategies/aw_model_nq_revised.py',
        'strategies/_aw_news_calendar.py',
        'strategies/_cme_index_calendar.py',
    ],
    'id': 'aw-model-nq-revised',
    'name': 'AW Reversal - NQ revised exploratory research',
    'version': '0.3.2',
    'description': 'AW Reversal research with explicit bias policies, 1m or 3m signal candles, FVG limit variants, fixed $500 structural risk, news gate, and roll-segment resets.',
    'migration_scope': 'Post-inspection revision of the AW Model PDF interpretation. The prior 2022-August 2026 results are development data, not final out-of-sample evidence. The model uses causal confirmed bars, selected NQ volume-rolled contract segments, NQ OHLC as an MNQ execution-price proxy, conservative resting-limit fills, premarked PDH/PDL/ONH/ONL only, and frozen objective reward/location gates. Contract-specific overlap data, true MNQ limit fills, discretionary equal-high liquidity and flip-candle close foresight remain unavailable. Full method and tested variants are recorded in the revised protocol.',
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
                             'description': 'MSS directional body divided by the median of the preceding 60 minutes of completed signal candles.'},
        'signal_timeframe': {'type': 'enum', 'default': '3m', 'choices': ['1m', '3m'],
                             'description': 'Completed candle size for sweep, neckline, displacement, and FVG.'},
        'entry_style': {'type': 'enum', 'default': 'first-touch',
                        'choices': ['first-touch', 'half-gap', 'fvg-confirmation-open'],
                        'description': 'Two resting FVG limits; the third enters at the next open after FVG confirmation as a causal flip-entry proxy.'},
        'management': {'type': 'enum', 'default': 'be-only', 'choices': ['be-only', 'pivot-trail'],
                       'description': 'BE+2 after first internal pivot, then hold; optional subsequent confirmed-pivot trail.'},
        'risk_budget': {'type': 'number', 'default': 500.0, 'minimum': 1.0, 'maximum': 10000.0,
                        'description': 'Maximum planned structural dollars per trade, using NQ/MNQ contract equivalents.'},
        'news_filter': {'type': 'boolean', 'default': True,
                        'description': 'No new AW reversal before the listed FOMC, CPI, or NFP release.'},
        'min_rr_primary': {'type': 'number', 'default': 1.5, 'minimum': 0.0, 'maximum': 10.0,
                           'description': 'Minimum planned ERL reward / structural risk from 09:00 to 10:30 CT.'},
        'min_rr_early': {'type': 'number', 'default': 2.0, 'minimum': 0.0, 'maximum': 10.0,
                         'description': 'Minimum planned R:R during the selective 08:30-09:00 CT window.'},
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
                 'bull_votes', 'bear_votes', 'eligible', 'htf_mid')

    def __init__(self, date, pdh, pdl, onh, onl, bias,
                 bull_votes, bear_votes, eligible, htf_mid=None):
        self.date = date
        self.pdh = pdh
        self.pdl = pdl
        self.onh = onh
        self.onl = onl
        self.bias = bias
        self.bull_votes = bull_votes
        self.bear_votes = bear_votes
        self.eligible = eligible
        self.htf_mid = htf_mid

    def price(self, name):
        return {'PDH': self.pdh, 'PDL': self.pdl,
                'ONH': self.onh, 'ONL': self.onl}[name]


class Candidate(_Record):
    __slots__ = ('side', 'level_name', 'level', 'neckline', 'extreme',
                 'sweep_ready', 'phase', 'mss_bars', 'mss_index',
                 'gap_low', 'gap_high', 'gap_ready', 'setup_id')

    def __init__(self, side, level_name, level, neckline, extreme, sweep_ready,
                 phase='swept', mss_bars=0, mss_index=None,
                 gap_low=None, gap_high=None, gap_ready=None, setup_id=None):
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
        self.setup_id = setup_id


class EntryPlan(_Record):
    __slots__ = ('side', 'stop', 'target', 'internal', 'order_id', 'setup_id',
                 'armed_at', 'actual_entry', 'be_moved', 'current_stop',
                 'trailed_levels')

    def __init__(self, side, stop, target, internal, order_id, setup_id, armed_at):
        self.side = side
        self.stop = stop
        self.target = target
        self.internal = internal
        self.order_id = order_id
        self.setup_id = setup_id
        self.armed_at = armed_at
        self.actual_entry = None
        self.be_moved = False
        self.current_stop = stop
        self.trailed_levels = set()


def _complete_resample(bars, interval, offset='0min'):
    """Use only contiguous minute candles whose nominal HTF end is known."""
    frame = bars[['open', 'high', 'low', 'close']].copy()
    local = bars.index.tz_convert(CT)
    # Pandas' fixed 2H bins on a timezone-aware multiyear index stay anchored
    # in elapsed time and drift one wall-clock hour across DST. The AW 2H vote
    # is explicitly anchored to Chicago 01:00/03:00/05:00, so bin on local
    # wall time and restore the timezone after checking complete candles.
    wall_clock_two_hour = interval == '2h'
    frame.index = local.tz_localize(None) if wall_clock_two_hour else local
    frame['_timestamp_ns'] = frame.index.asi8
    frame['_contract'] = (bars['instrument_id'].to_numpy()
                          if 'instrument_id' in bars else np.zeros(len(bars), dtype=np.int64))
    grouped = frame.resample(interval, label='left', closed='left',
                             origin='start_day', offset=offset)
    candles = grouped.agg({'open': 'first', 'high': 'max',
                           'low': 'min', 'close': 'last',
                           '_timestamp_ns': ['size', 'first', 'last'],
                           '_contract': ['first', 'nunique']})
    candles.columns = ['open', 'high', 'low', 'close', 'n', 'first_ns',
                       'last_ns', 'instrument_id', 'contract_count']
    width = pd.Timedelta(interval)
    expected = int(width / ONE_MINUTE)
    valid = ((candles.n == expected).to_numpy() &
             (candles.first_ns.to_numpy() == candles.index.asi8) &
             (candles.last_ns.to_numpy() == (candles.index + width - ONE_MINUTE).asi8) &
             (candles.contract_count.to_numpy() == 1))
    candles = candles.loc[valid, ['open', 'high', 'low', 'close', 'instrument_id']].copy()
    if wall_clock_two_hour:
        ready = (candles.index + width).tz_localize(CT)
        candles.index = candles.index.tz_localize(CT)
        candles['ready'] = ready
    else:
        candles['ready'] = candles.index + width
    return candles


def _untouched_fvg_votes(htf, price, partial):
    """Any strict completed 2H gap, wholly above/below price and untouched."""
    above = below = False
    first = max(2, len(htf) - 20)
    for j in range(first, len(htf)):
        if (htf.index[j] - htf.index[j - 1] != TWO_HOURS or
                htf.index[j - 1] - htf.index[j - 2] != TWO_HOURS):
            continue
        a, c = htf.iloc[j - 2], htf.iloc[j]
        gap = None
        if float(c.low) > float(a.high):
            gap = (float(a.high), float(c.low))
        elif float(c.high) < float(a.low):
            gap = (float(c.high), float(a.low))
        if gap is None:
            continue
        # An incomplete later 2H candle could have touched this gap without
        # appearing in the completed-candle frame. Do not count it as intact.
        if any(htf.index[k] - htf.index[k - 1] != TWO_HOURS
               for k in range(j + 1, len(htf))):
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
    contracts = (bars['instrument_id'] if 'instrument_id' in bars
                 else pd.Series(np.zeros(len(bars), dtype=np.int64), index=bars.index))
    rth = bars.loc[(minutes >= 510) & (minutes < 900), ['high', 'low']]
    rth_days = dates[(minutes >= 510) & (minutes < 900)]
    rth_summary = rth.groupby(rth_days).agg({'high': 'max', 'low': 'min'})
    rth_summary['n'] = rth.groupby(rth_days).size()
    rth_summary['instrument_id'] = contracts.loc[rth.index].groupby(rth_days).first()
    rth_summary['contract_count'] = contracts.loc[rth.index].groupby(rth_days).nunique()
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
        current_contract = contracts.iloc[end - 1]
        if (not bool(previous.complete) or previous.contract_count != 1 or
                previous.instrument_id != current_contract):
            continue
        overnight_start = date - pd.Timedelta(days=1) + pd.Timedelta(hours=17)
        begin = local.searchsorted(overnight_start, side='left')
        overnight = bars.iloc[begin:end]
        if (len(overnight) < 925 or local[begin] != overnight_start or
                local[end - 1] != last_preopen or
                contracts.iloc[begin:end].nunique() != 1 or
                contracts.iloc[begin] != current_contract):
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
        known = htf.iloc[:htf_end]
        known = known.loc[known.instrument_id == current_contract].tail(25)
        # The five most recent 2H candles must be the scheduled sequence
        # ending at 07:00 CT. A missing minute must not silently substitute
        # an older candle in the frozen preopen vote or location midpoint.
        last_five = known.tail(5)
        expected_last_ready = date + pd.Timedelta(hours=7)
        if (len(last_five) < 5 or last_five.ready.iloc[-1] != expected_last_ready or
                not bool((last_five.index.to_series().diff().iloc[1:] == TWO_HOURS).all())):
            continue
        htf_mid = ((float(known.iloc[-5:].high.max()) +
                    float(known.iloc[-5:].low.min())) / 2.0 if len(known) >= 5 else None)
        price = float(bars.close.iloc[end - 1])
        partial_begin = local.searchsorted(known.ready.iloc[-1], side='left') if len(known) else end
        partial = bars.iloc[partial_begin:end][['high', 'low']]
        bull, bear = _bias_votes(known, stub, price, partial)
        bull_count, bear_count = sum(bull), sum(bear)
        bias = 1 if bull_count >= 3 and bear_count < 3 else -1 if bear_count >= 3 and bull_count < 3 else 0
        result[date.date()] = DayLevels(date.date(), pdh, pdl, onh, onl,
                                        bias, bull, bear, frozenset(eligible), htf_mid)
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
        self.signal_width = (ONE_MINUTE if parameters['signal_timeframe'] == '1m'
                             else THREE_MINUTES)
        self.signal_minutes = int(self.signal_width / ONE_MINUTE)
        self.body_lookback = 60 // self.signal_minutes
        self.local_start = bars.index.tz_convert(CT)
        self.ready = pd.DatetimeIndex(pd.to_datetime(bars.availability_time, utc=True)).tz_convert(CT)
        self.contracts = (bars['instrument_id'].to_numpy()
                          if 'instrument_id' in bars else np.zeros(len(bars), dtype=np.int64))
        self.three = _complete_resample(bars, '1min' if self.signal_minutes == 1 else '3min')
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
        self.contract3 = self.three.instrument_id.to_numpy()
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
        self.setup_seq = 0
        self.roll_transitions = 0
        self.filled_order_ids = set()

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
        self.filled_order_ids = set()
        self.taken = set()
        self.taken_at_three_start = set()
        # Keep prior-evening confirmed 3m structure across CT midnight.
        self.plan = None
        if day in self.days:
            self.funnel['prepared_days'] += 1
            if self.parameters['news_filter'] and not news_gate(day, self.day_morning)[0]:
                self.funnel['news_blocked_prepared_days'] += 1
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
        lookback = self.body_lookback
        if (k < lookback or
                self.start3[k] - self.start3[k - lookback] != pd.Timedelta(minutes=60) or
                not np.all(self.contract3[k - lookback:k + 1] == self.contract3[k])):
            return False
        body = self.bodies3[k]
        median = float(np.median(self.bodies3[k - lookback:k]))
        width = self.high3[k] - self.low3[k]
        if median <= 0 or width <= 0:
            return False
        side = candidate.side
        directional = self.close3[k] > self.open3[k] if side > 0 else self.close3[k] < self.open3[k]
        edge = self.close3[k] >= self.high3[k] - 0.25 * width if side > 0 else self.close3[k] <= self.low3[k] + 0.25 * width
        return (directional and body >= self.parameters['impulse_multiple'] * median and
                body / width >= 0.60 and edge)

    def _mss_crossed(self, k, candidate):
        if k == 0 or self.start3[k] - self.start3[k - 1] != self.signal_width:
            return False
        if candidate.side > 0:
            return self.close3[k] > candidate.neckline and self.close3[k - 1] <= candidate.neckline
        return self.close3[k] < candidate.neckline and self.close3[k - 1] >= candidate.neckline

    def _fvg(self, k, candidate):
        middle = candidate.mss_index
        if middle is None or k != middle + 1 or middle < 1:
            return None
        if (self.start3[k] - self.start3[middle] != self.signal_width or
                self.start3[middle] - self.start3[middle - 1] != self.signal_width or
                not np.all(self.contract3[middle - 1:k + 1] == self.contract3[k])):
            return None
        if candidate.side > 0 and self.low3[k] > self.high3[middle - 1]:
            return float(self.high3[middle - 1]), float(self.low3[k])
        if candidate.side < 0 and self.high3[k] < self.low3[middle - 1]:
            return float(self.high3[k]), float(self.low3[middle - 1])
        return None

    def _try_sweep(self, k, state):
        if (not state['tradable'] or self.entries_today >= self._entry_limit() or
                state['position'] or state.get('position_at_open', 0) or
                state.get('working_order_id')):
            return
        date = self.start3[k].date()
        levels = self.days.get(date)
        if levels is None:
            return
        if self.parameters['news_filter'] and not news_gate(date, self.ready3[k])[0]:
            return
        opening = self.start3[k]
        ready = self.ready3[k]
        open_clock = opening.hour * 60 + opening.minute
        ready_clock = ready.hour * 60 + ready.minute
        if not (510 <= open_clock and ready_clock < 630 and opening.date() == ready.date()) or ready >= self.day_cutoff:
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
        self.setup_seq += 1
        setup_id = f'AW-{date}-{self.parameters["signal_timeframe"]}-{self.setup_seq:04d}-{side:+d}-{name}'
        candidate = Candidate(side, name, level, neckline, extreme, ready, setup_id=setup_id)
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
        if (k < 4 or self.start3[k] - self.start3[k - 4] != 4 * self.signal_width or
                not np.all(self.contract3[k - 4:k + 1] == self.contract3[k])):
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
        if (candidate.phase in ('swept', 'mss_pending') and
                self.start3[k] >= candidate.sweep_ready):
            # A second grab before FVG confirmation belongs to the same
            # reversal swing; its furthest extreme defines structural risk.
            candidate.extreme = (min(candidate.extreme, float(self.low3[k]))
                                 if candidate.side > 0 else
                                 max(candidate.extreme, float(self.high3[k])))
        if candidate.phase == 'swept' and self.start3[k] >= candidate.sweep_ready:
            candidate.mss_bars += 1
            crossed = self._mss_crossed(k, candidate)
            if (self.ready3[k].hour * 60 + self.ready3[k].minute >= 630 or
                    self.ready3[k] >= self.day_cutoff):
                self.funnel['expired_at_entry_window'] += 1
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

    def _consume_candidates(self, consumed):
        remaining = [candidate for candidate in
                     ([self.candidate] if self.candidate is not None else []) + self.other_candidates
                     if all(candidate is not other for other in consumed)]
        self.candidate = remaining[0] if remaining else None
        self.other_candidates = remaining[1:]

    def _entry_reference(self, candidate, bar):
        style = self.parameters['entry_style']
        if style == 'fvg-confirmation-open':
            return float(bar.close)
        if style == 'first-touch':
            return candidate.gap_high if candidate.side > 0 else candidate.gap_low
        midpoint = (candidate.gap_low + candidate.gap_high) / 2.0
        # An odd-tick gap has a half-tick midpoint. Require a deeper retrace.
        ticks = midpoint / self.tick
        return (math.floor(ticks) if candidate.side > 0 else math.ceil(ticks)) * self.tick

    def _order_for_gap(self, candidate, bar, ready):
        if ready.hour * 60 + ready.minute >= 630 or ready >= self.day_cutoff:
            self.funnel['gap_after_entry_window'] += 1
            return None
        if self.parameters['news_filter'] and not news_gate(self.day, ready)[0]:
            self.funnel['gap_before_news_release'] += 1
            return None
        side = candidate.side
        stop = candidate.extreme - self.tick if side > 0 else candidate.extreme + self.tick
        if (float(bar.low) <= stop if side > 0 else float(bar.high) >= stop):
            self.funnel['gap_confirmation_hit_structural_stop'] += 1
            return None
        reference = self._entry_reference(candidate, bar)
        choice = self._opposing_target(side, reference)
        if choice is None:
            self.funnel['no_untaken_opposing_target'] += 1
            return None
        target, target_name = choice
        risk_points = side * (reference - stop)
        reward_points = side * (target - reference)
        if risk_points <= 0 or reward_points <= 0:
            self.funnel['nonpositive_planned_risk_or_reward'] += 1
            return None
        minimum_rr = (self.parameters['min_rr_early'] if ready.hour < 9
                      else self.parameters['min_rr_primary'])
        planned_rr = reward_points / risk_points
        if planned_rr < minimum_rr:
            self.funnel['reward_gate_rejections'] += 1
            return None
        levels = self.days[self.day]
        midpoint = levels.htf_mid
        if midpoint is None or (reference > midpoint if side > 0 else reference < midpoint):
            self.funnel['location_gate_rejections'] += 1
            return None
        # A micro-equivalent contributes $2/point. Decompose whole units
        # into NQ first, then MNQ; the engine values every unit at $2/point.
        units = min(100, math.floor(self.parameters['risk_budget'] /
                                    (risk_points * 2.0)))
        if units < 1:
            self.funnel['minimum_mnq_exceeds_risk_budget'] += 1
            return None
        nq_contracts, mnq_contracts = divmod(units, 10)
        one_way_fee = (nq_contracts * float(self.request['fee']) +
                       mnq_contracts * float(self.request['fee']) / 2.0)
        fee_per_unit = one_way_fee / units
        internal = self._internal_level(side, reference, target)
        setup_id = candidate.setup_id or f'AW-{self.day}-{ready:%H%M}-{side:+d}-{candidate.level_name}'
        order_id = f'{setup_id}-{self.parameters["entry_style"]}'
        self.plan = EntryPlan(side, stop, target, internal, order_id, setup_id, ready)
        self.funnel['submitted_entries'] += 1
        print('AW_ENTRY ' + json.dumps({
            'signal_id': setup_id, 'order_id': order_id,
            'signal_time': ready.isoformat(), 'side': side, 'stop': stop,
            'target': target, 'requested_price': reference,
            'risk_points': risk_points, 'planned_rr': planned_rr,
            'risk_budget_cash': self.parameters['risk_budget'],
            'planned_risk_cash': units * risk_points * 2.0,
            'nq_contracts': nq_contracts, 'mnq_contracts': mnq_contracts,
            'swept_level': candidate.level_name, 'target_level': target_name,
            'neckline': candidate.neckline, 'fvg_low': candidate.gap_low,
            'fvg_high': candidate.gap_high, 'internal_level': internal,
            'bias': levels.bias, 'bias_policy': self.bias_policy,
            'signal_timeframe': self.parameters['signal_timeframe'],
            'entry_style': self.parameters['entry_style'],
        }, sort_keys=True), flush=True)
        order = {'target': side * units, 'bracket': (stop, target),
                 'signal_id': setup_id, 'order_id': order_id,
                 'point_value': 2.0, 'fee': fee_per_unit,
                 'nq_contracts': nq_contracts,
                 'mnq_contracts': mnq_contracts,
                 'contract_label': 'NQ+MNQ-micro-equivalents',
                 'reason': f'aw-{self.parameters["entry_style"]}'}
        if self.parameters['entry_style'] == 'fvg-confirmation-open':
            order.update(timing='next-open', expires_at=ready.isoformat(),
                         max_structural_risk_cash=self.parameters['risk_budget'])
        else:
            deadline = pd.Timestamp(self.day).tz_localize(CT) + pd.Timedelta(hours=10, minutes=29)
            order.update(timing='limit', limit_price=reference,
                         expires_at=deadline.isoformat())
        return order

    def _arm_entry(self, bar, state, ready):
        active = ([self.candidate] if self.candidate is not None else []) + self.other_candidates
        gaps = [candidate for candidate in active
                if candidate.phase == 'gap' and candidate.gap_ready is not None and
                candidate.gap_ready <= ready]
        if not gaps:
            return None
        if (state['position'] or state.get('position_at_open', 0) or
                state.get('working_order_id') or self.plan is not None or
                self.entries_today >= self._entry_limit() or not state['tradable']):
            self.funnel['gap_while_busy'] += len(gaps)
            self._consume_candidates(gaps)
            return None
        gaps.sort(key=lambda candidate: (candidate.gap_ready, candidate.sweep_ready))
        if (len(gaps) > 1 and gaps[0].gap_ready == gaps[1].gap_ready and
                gaps[0].side != gaps[1].side):
            self.funnel['ambiguous_simultaneous_gap_confirmations'] += 1
            self._consume_candidates(gaps[:2])
            return None
        for candidate in gaps:
            self._consume_candidates((candidate,))
            order = self._order_for_gap(candidate, bar, ready)
            if order is not None:
                # One resting entry is supported. On NONE days the first
                # confirmed valid gap gets priority; later gaps are ignored.
                if self.mixed_day:
                    self.candidate = None
                    self.other_candidates = []
                return order
        return None

    def _manage_position(self, bar, state, ready):
        position = int(state['position'])
        opened = int(state.get('position_at_open', position))
        if not position:
            if opened:
                self.plan = None
            return None
        if self.plan is not None and self.plan.actual_entry is None:
            self.plan.actual_entry = float(state.get('entry_price') or bar.open)
        if ready >= self.day_cutoff:
            self.plan = None
            return {'target': 0, 'timing': 'close',
                    'reason': 'aw-1500-or-early-close',
                    'order_id': state.get('order_id'),
                    'signal_id': state.get('signal_id')}
        plan = self.plan
        if plan is None or plan.actual_entry is None:
            return None
        side = 1 if position > 0 else -1
        entry = plan.actual_entry
        internal = plan.internal
        if not plan.be_moved:
            if internal is None or not (entry < internal < plan.target if side > 0
                                        else plan.target < internal < entry):
                return None
            be_stop = entry + side * 2.0
            if not (plan.current_stop < be_stop < plan.target if side > 0
                    else plan.target < be_stop < plan.current_stop):
                return None
            reached = float(bar.close) >= internal if side > 0 else float(bar.close) <= internal
            if not reached:
                return None
            plan.be_moved = True
            plan.current_stop = be_stop
            self.funnel['be_updates'] += 1
            return {'target': position, 'timing': 'close',
                    'bracket': (be_stop, plan.target), 'order_id': plan.order_id,
                    'signal_id': plan.setup_id, 'reason': 'aw-be-plus-two'}
        if self.parameters['management'] != 'pivot-trail':
            return None
        favorable = self.pivot_highs if side > 0 else self.pivot_lows
        opposing = self.pivot_lows if side > 0 else self.pivot_highs
        cleared = [(price, when) for price, when in favorable
                   if plan.armed_at < when < ready and
                   (float(bar.open) <= price < float(bar.close) if side > 0
                    else float(bar.close) < price <= float(bar.open)) and
                   (price, when) not in plan.trailed_levels]
        if not cleared:
            return None
        plan.trailed_levels.update(cleared)
        behind = [(price, when) for price, when in opposing
                  if plan.armed_at < when < ready and
                  (price < float(bar.close) if side > 0 else price > float(bar.close))]
        if not behind:
            return None
        structure = behind[-1][0]
        new_stop = structure - self.tick if side > 0 else structure + self.tick
        if not (plan.current_stop < new_stop < float(bar.close) if side > 0
                else float(bar.close) < new_stop < plan.current_stop):
            return None
        plan.current_stop = new_stop
        self.funnel['pivot_trail_updates'] += 1
        return {'target': position, 'timing': 'close',
                'bracket': (new_stop, plan.target), 'order_id': plan.order_id,
                'signal_id': plan.setup_id, 'reason': 'aw-confirmed-pivot-trail'}

    def _step(self, i, bar, state):
        day = self.local_start[i].date()
        ready = self.ready[i]
        if i and self.contracts[i] != self.contracts[i - 1]:
            if state['position'] or state.get('working_order_id'):
                raise ValueError('AW contract roll occurred with a working trade or order')
            self.roll_transitions += 1
            self.funnel['contract_roll_resets'] += 1
            self.candidate = None
            self.other_candidates = []
            self.plan = None
            self.taken = set()
            self.taken_at_three_start = set()
            self.last_pivot_high = self.last_pivot_low = None
            self.pivot_highs = []
            self.pivot_lows = []
            self.open_pivot_highs = []
            self.open_pivot_lows = []
        if day != self.day:
            self._new_day(day, state)
        filled = state.get('entry_filled_this_bar')
        if filled and filled['order_id'] not in self.filled_order_ids:
            self.filled_order_ids.add(filled['order_id'])
            self.entries_today += 1
            self.funnel['filled_entries'] += 1
        if (self.plan is not None and not state['position'] and
                state.get('working_order_id') != self.plan.order_id and
                ready > self.plan.armed_at):
            self.plan = None
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
        if (self.plan is not None and not state['position'] and
                state.get('working_order_id') == self.plan.order_id):
            side = self.plan.side
            invalid = (ready.hour * 60 + ready.minute >= 630 or
                       ready >= self.day_cutoff or
                       (high >= self.plan.target if side > 0 else low <= self.plan.target) or
                       (low <= self.plan.stop if side > 0 else high >= self.plan.stop))
            if invalid:
                order_id = self.plan.order_id
                self.plan = None
                self.funnel['canceled_unfilled_orders'] += 1
                return {'timing': 'cancel', 'order_id': order_id,
                        'reason': 'aw-unfilled-plan-invalid'}
        managed = self._manage_position(bar, state, ready)
        if managed is not None:
            return managed
        if state['position'] or state.get('position_at_open', 0):
            return None
        return self._arm_entry(bar, state, ready)

    def on_close(self, i, bar, state):
        decision = self._step(i, bar, state)
        if i == self.last_called:
            print('AW_FUNNEL ' + json.dumps(dict(sorted(self.funnel.items())), sort_keys=True), flush=True)
        return decision


def create_strategy(bars, parameters, request):
    return AWModelNQ(bars, parameters, request)
