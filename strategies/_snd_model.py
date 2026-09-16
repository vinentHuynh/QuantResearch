"""Causal SND decisions; fills and accounting belong to workbench.events.

The original zone helpers and resampler are imported from scripts, which the
workbench preserves and checksums in every run's source snapshot.
"""
from argparse import Namespace

import numpy as np
import pandas as pd

from scripts.mnq import SND_baseline_backtest as source
from scripts.mnq import build_mnq_timeframes as resampler


def slot_rvol(frame, width):
    local = frame.index.tz_convert('America/Chicago')
    slots = ((local.hour * 60 + local.minute - 17 * 60) % 1440) // width
    volume = frame.volume.astype(float)
    baseline = volume.groupby(slots, sort=False).transform(
        lambda values: values.shift(1).rolling(20, min_periods=10).mean())
    return volume / baseline.replace(0., np.nan)


class SND:
    def __init__(self, bars, parameters, request):
        self.index = bars.index.tz_convert('UTC')
        self.variant = parameters['variant']
        self.contracts = parameters['contracts']
        self.args = Namespace(max_zones=50, max_tests=2, bounce_points=75.,
                              min_zone_age_bars=1, min_bars_between_tests=5,
                              stop_cap_points=100., zone_stop_buffer_points=1.,
                              tick_size=1., target_1h_ticks=100.,
                              target_4h_ticks=200., target_1d_ticks=400.)
        frames = {}
        for tf, rule in [('1h', '1h'), ('4h', '4h'), ('1d', '1D')]:
            frame = resampler.aggregate(bars, rule)
            ends = resampler.bar_ends(frame.index, tf)
            # Exclude partial initial/final source candles. Interior exchange
            # closures and missing minutes retain the source's aggregation rules.
            frames[tf] = frame.loc[(frame.index >= self.index[0]) &
                                   (ends <= self.index[-1] + pd.Timedelta(minutes=1))]
        self.events = {}
        for zone in source.detect_zones(frames, self.index, .5):
            self.events.setdefault(zone.activation_pos, []).append(zone)
        self.longs, self.shorts, self.first_rvol = [], [], {}
        self.rvol = np.full(len(bars), np.nan)
        if self.variant == 'phase7_prior_1m':
            self.rvol = slot_rvol(bars, 1).shift(1).where(
                self.index.to_series().diff().eq(pd.Timedelta(minutes=1)).to_numpy()).to_numpy()
        elif self.variant == 'phase7_prior_5m':
            five = resampler.aggregate(bars, '5min')
            five = five.loc[five.index >= self.index[0]]
            values = slot_rvol(five, 5).to_numpy()
            loc = np.searchsorted((five.index + pd.Timedelta(minutes=5)).asi8,
                                  self.index.asi8, side='right') - 1
            if len(values):
                self.rvol = np.where(loc >= 0, values[np.maximum(loc, 0)], np.nan)

    def passes(self, zone):
        if self.variant == 'original_multi_tf':
            return True
        if zone.timeframe != '1h' or zone.physical_touch_count != 1:
            return False
        distances = ([other.proximal - zone.proximal for other in self.shorts
                      if other.proximal > zone.proximal] if zone.direction == 'long' else
                     [zone.proximal - other.proximal for other in self.longs
                      if other.proximal < zone.proximal])
        if distances and min(distances) < 2 * (zone.width + 1.):
            return False
        if self.variant == 'phase6':
            return True
        return .75 <= self.first_rvol.get(zone.zone_id, np.nan) < 1.25

    def on_close(self, i, bar, state):
        timestamp = self.index[i]
        previous = self.index[i - 1] if i else None
        high, low, close = float(bar.high), float(bar.low), float(bar.close)
        for zone in self.events.get(i, ()):
            side = self.longs if zone.direction == 'long' else self.shorts
            side.insert(0, zone)
            del side[self.args.max_zones:]
        # Source invalidation is a strict WICK break, before physical touches.
        self.longs = [zone for zone in self.longs if low >= zone.distal]
        self.shorts = [zone for zone in self.shorts if high <= zone.distal]
        contiguous = previous is not None and timestamp - previous == pd.Timedelta(minutes=1)
        for zone in self.longs + self.shorts:
            touched = (low <= zone.proximal and high >= zone.distal if zone.direction == 'long'
                       else high >= zone.proximal and low <= zone.distal)
            if touched and (not contiguous or not zone.touching_previous_bar):
                zone.physical_touch_count += 1
                if zone.physical_touch_count == 1:
                    self.first_rvol[zone.zone_id] = self.rvol[i]
            zone.touching_previous_bar = touched
        long = source.select_candidate(self.longs, 'long', i, high, low, close, self.args, self.passes)
        short = source.select_candidate(self.shorts, 'short', i, high, low, close, self.args, self.passes)
        # Includes a pending order filled at this open and a position stopped
        # during this minute: neither may consume another setup on its exit bar.
        busy = state.get('position_at_open', state['position']) != 0
        if not busy:
            for zone in (long, short):
                if zone is not None:
                    source.consume_test(zone, i, timestamp)
        if state['position'] and source.forced_close_crossing(timestamp, previous):
            return {'target': 0, 'timing': 'close', 'reason': 'snd-timed-close'}
        if busy or not state['tradable'] or source.no_trade_window(timestamp):
            return None
        chosen = long if long is not None else short
        if chosen is None:
            return None
        stop, target, _ = source.trade_levels(chosen, self.args)
        return {'target': self.contracts * (1 if chosen.direction == 'long' else -1),
                'timing': 'next-open', 'bracket': (stop, target),
                'reason': 'snd-' + self.variant}
