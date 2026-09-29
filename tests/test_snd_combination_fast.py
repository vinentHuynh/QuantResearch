"""Exact accelerator parity on execution hazards and mutable-input boundaries.

Controlled-bias fixtures isolate lifecycle behavior; a separate random-price
fixture uses naturally confirmed structure. These are implementation checks,
not historical performance or complete price-path coverage claims.
"""
from copy import deepcopy
import itertools
import unittest

import numpy as np
import pandas as pd

from strategies import _snd_combination_reference as reference
from strategies import _snd_combination_fast as fast
from test_snd_zone_quality import BASE, FILL, HISTORY, NO_TOUCH, source_frame

RETOUCH = (102, 102.5, 100, 102)


def prepare(rows=None, mirror=False, resolution=1, source=None, controlled=True):
    if source is None:
        rows = HISTORY + BASE + [FILL] if rows is None else rows
        volumes = np.full(len(rows), 10.)
        volumes[len(HISTORY) + 1] = 40.
        source = source_frame(rows, mirror=mirror, minute=resolution == 1, volumes=volumes)
    data = reference.prepare_data(source, pivot_len=1, execution_minutes=resolution)
    if controlled:
        data['chart']['bias'] = data['chart']['hourly_bias'] = -1 if mirror else 1
    return data


def run(engine, data, *, start=None, end=None, fee=1., ticks=1, tick_size=.25, point_value=2., **options):
    return engine.run_model(data, dict(pivot_len=1, execution_minutes=data['execution_minutes'], **options),
        data['source'].index[0] if start is None else start,
        data['source'].index[-1] + pd.Timedelta(minutes=data['execution_minutes']) if end is None else end,
        tick_size=tick_size, point_value=point_value, fee=fee, slippage_ticks=ticks)


class CombinationFastTests(unittest.TestCase):
    def exact(self, data, **options):
        expected_data, actual_data = deepcopy(data), deepcopy(data)
        expected, actual = run(reference, expected_data, **options), run(fast, actual_data, **options)
        for name in ('trades', 'equity'):
            pd.testing.assert_frame_equal(expected[name], actual[name], check_exact=True, check_dtype=True)
        for name, value in expected['diagnostics'].items():
            self.assertEqual(actual['diagnostics'][name], value, name)
        self.assertEqual(actual['parameters'], expected['parameters'])
        for candidate in (expected_data, actual_data):
            self.assertEqual(set(candidate), set(data))
            for name in ('source', 'chart', 'hourly'):
                pd.testing.assert_frame_equal(data[name], candidate[name], check_exact=True, check_dtype=True)
            self.assertEqual(candidate['diagnostics'], data['diagnostics'])
        return actual

    def test_full_schemas_cross_geometry_stops_side_resolution_and_price_mode(self):
        quality = dict(max_zone_width_atr=1, min_departure_atr=1.75, min_departure_rvol=4, max_touch_age_hours=1/12)
        for mirror, resolution in itertools.product((False, True), (1, 5)):
            data = prepare(mirror=mirror, resolution=resolution)
            for boundary, stop, mode in itertools.product(('wick', 'body'), ('zone', 'candle'), ('cash', 'price')):
                with self.subTest(mirror=mirror, resolution=resolution, boundary=boundary, stop=stop, mode=mode):
                    result = self.exact(data, zone_boundary=boundary, stop_model=stop, slippage_model=mode, **quality)
                    self.assertEqual(len(result['trades']), 1)
                    t = result['trades'].iloc[0]
                    self.assertEqual(t.zone_width_atr, (t.zone_top-t.zone_bottom)/t.prior_atr20)
                    self.assertEqual(t.exit_reason, 'end-of-test')

    def test_intrabar_entry_stop_first_and_ambiguous_exit(self):
        for mirror, mode, resolution in itertools.product((False, True), ('cash', 'price'), (1, 5)):
            data = prepare(HISTORY + BASE + [(102, 111, 98, 104)], mirror, resolution)
            # Keep only the first entry source candle for 1m, making the final
            # chart bucket incomplete while observed adverse execution remains.
            if resolution == 1:
                data = prepare(mirror=mirror, source=data['source'].iloc[:-4])
            result = self.exact(data, slippage_model=mode)
            t = result['trades'].iloc[0]
            self.assertEqual(t.exit_reason, 'stop')
            self.assertTrue(t.ambiguous_entry)
            self.assertTrue(t.ambiguous_exit)
            self.assertTrue(t.entry_bar_target_ignored)
            self.assertEqual(t.exit_price_before_slippage, t.stop)

    def test_entry_bar_target_suppression_depends_on_raw_open_not_shifted_fill(self):
        for mirror, mode in itertools.product((False, True), ('cash', 'price')):
            for opened, expected in ((102, 'end-of-test'), (103.25, 'target')):
                data = prepare(HISTORY + BASE + [(opened, 111, 101, 106)], mirror)
                data = prepare(mirror=mirror, source=data['source'].iloc[:-4])
                result = self.exact(data, slippage_model=mode)
                t = result['trades'].iloc[0]
                self.assertEqual(t.exit_reason, expected)
                self.assertEqual(t.entry_bar_target_ignored, opened < 103.25)

    def test_marketable_target_at_open_precedes_adverse_extreme_and_stop_gap(self):
        for mirror, mode in itertools.product((False, True), ('cash', 'price')):
            for tail, reason, raw_exit in (((112, 113, 90, 100), 'target', None),
                                           ((97, 112, 96, 100), 'stop', 97)):
                data = prepare(HISTORY + BASE + [FILL, tail], mirror)
                t = self.exact(data, slippage_model=mode, ticks=2, fee=2.)['trades'].iloc[0]
                self.assertEqual(t.exit_reason, reason)
                self.assertFalse(t.ambiguous_exit)
                self.assertEqual(t.exit_price_before_slippage, t.target if raw_exit is None else 250-raw_exit if mirror else raw_exit)

    def test_first_any_touch_ttl_and_missing_bucket_elapsed_expiry(self):
        data = prepare(HISTORY + BASE + [NO_TOUCH, FILL])
        for eligibility in ('first_touch', 'any_touch'):
            self.assertTrue(self.exact(data, entry_eligibility=eligibility, order_lifetime_bars=1)['trades'].empty)
            self.assertEqual(len(self.exact(data, entry_eligibility=eligibility, order_lifetime_bars=3)['trades']), 1)
        retouch = prepare(HISTORY + BASE + [RETOUCH, (102.75, 103, 102, 102.75)])
        self.assertTrue(self.exact(retouch)['trades'].empty)
        result = self.exact(retouch, entry_eligibility='any_touch')
        self.assertEqual(len(result['trades']), 1)
        self.assertEqual(result['trades'].entry_reference.iloc[0], 102.75)
        frozen = prepare(HISTORY + BASE + [RETOUCH, BASE[3], FILL])
        t = self.exact(frozen, entry_eligibility='any_touch', order_lifetime_bars=3)['trades'].iloc[0]
        self.assertEqual(t.entry_reference, 103.25)
        self.assertEqual(t.order_expiry_time-t.signal_time, pd.Timedelta(minutes=15))
        for minutes, expected in ((10, 1), (15, 0)):
            original = prepare(resolution=5)
            source = original['source'].copy()
            index = source.index.to_list(); index[-1] += pd.Timedelta(minutes=minutes)
            source.index = pd.DatetimeIndex(index)
            result = self.exact(prepare(source=source, resolution=5), order_lifetime_bars=3)
            self.assertEqual(len(result['trades']), expected)

    def test_incomplete_or_warmup_touch_consumed_and_pending_hourly_cancellation(self):
        data = prepare(HISTORY + BASE + [RETOUCH, FILL])
        source = data['source'].drop(data['source'].index[(len(HISTORY)+3)*5+2])
        incomplete = prepare(source=source)
        first = self.exact(incomplete)
        self.assertTrue(first['trades'].empty)
        self.assertEqual(first['diagnostics']['first_touches_incomplete'], 1)
        self.assertEqual(len(self.exact(incomplete, entry_eligibility='any_touch')['trades']), 1)
        start = data['chart'].index[len(HISTORY)+4]
        self.assertTrue(self.exact(data, start=start)['trades'].empty)
        self.assertEqual(len(self.exact(data, start=start, entry_eligibility='any_touch')['trades']), 1)
        for field, n in (('hourly_bias', 0), ('bias', 1)):
            waiting = prepare(HISTORY + BASE + [NO_TOUCH, FILL])
            waiting['chart'].iloc[-1, waiting['chart'].columns.get_loc(field)] = -1
            result = self.exact(waiting, order_lifetime_bars=3)
            self.assertEqual(len(result['trades']), n)
            self.assertEqual(result['diagnostics']['orders_cancelled_bias'], 1-n)

    def test_opposing_context_survives_quality_rejection_and_room_rechecked_after_slippage(self):
        b = 112.5
        context = [(b+.5, b+2, b, b+1), (b+1, b+1.5, b-4, b-3), (b-4, b-3, b-5, b-4)]
        for mirror in (False, True):
            data = prepare(HISTORY + context + BASE + [(103, 104, 102, 103.5)], mirror)
            self.assertEqual(len(self.exact(data)['trades']), 1)
            rejected = self.exact(data, slippage_model='price')
            self.assertTrue(rejected['trades'].empty)
            self.assertEqual(rejected['diagnostics']['room_rejections_at_fill'], 1)
        b = 112
        context = [(b+.5, b+2, b, b+1), (b+1, b+1.5, b-4, b-3), (b-4, b-3, b-5, b-4)]
        result = self.exact(prepare(HISTORY + context + BASE + [FILL]), min_departure_atr=100)
        self.assertEqual(result['diagnostics']['room_rejections_at_signal'], 1)
        self.assertEqual(result['diagnostics']['quality_rejections_at_signal'], 0)

    def test_contract_roll_closes_at_old_source_and_cancels_pending(self):
        for mode in ('cash', 'price'):
            data = prepare(HISTORY + BASE + [FILL, (150, 160, 149, 155)])
            source = data['source'].copy()
            source['instrument_id'] = 10
            source.iloc[-7:, source.columns.get_loc('instrument_id')] = 20
            result = self.exact(prepare(source=source), slippage_model=mode)
            self.assertEqual(result['trades'].exit_reason.iloc[0], 'contract-roll')
            self.assertEqual(result['trades'].exit_price_before_slippage.iloc[0], 104.5)
            self.assertEqual(result['diagnostics']['bars_crossing_roll'], 1)
            data = prepare(HISTORY + BASE + [NO_TOUCH, FILL])
            source = data['source'].copy()
            source['instrument_id'] = 10
            source.iloc[-5:, source.columns.get_loc('instrument_id')] = 20
            result = self.exact(prepare(source=source), order_lifetime_bars=3, slippage_model=mode)
            self.assertTrue(result['trades'].empty)

    def test_quality_missing_features_union_counts_and_body_width_cache(self):
        data = prepare()
        failed = self.exact(data, max_zone_width_atr=0, min_departure_atr=100, min_departure_rvol=100, max_touch_age_hours=0)
        self.assertTrue(failed['trades'].empty)
        self.assertEqual(failed['diagnostics']['quality_rejections_at_signal'], 1)
        for name in reference.QUALITY_PARAMETERS:
            self.assertEqual(failed['diagnostics'][name+'_rejections_at_signal'], 1)
        for feature, parameter in (('zone_width_atr', 'max_zone_width_atr'), ('departure_atr', 'min_departure_atr'), ('departure_rvol', 'min_departure_rvol')):
            for unavailable in ('absent', np.nan, np.inf):
                broken = deepcopy(data)
                if unavailable == 'absent':
                    broken['chart'] = broken['chart'].drop(columns=feature)
                else:
                    broken['chart'][feature] = unavailable
                self.assertEqual(len(self.exact(broken)['trades']), 1)
                result = self.exact(broken, **{parameter: 0})
                self.assertTrue(result['trades'].empty)
                self.assertEqual(result['diagnostics'][parameter+'_missing_at_signal'], 1)
        for boundary, count in (('wick', 0), ('body', 1), ('wick', 0)):
            result = self.exact(data, zone_boundary=boundary, max_zone_width_atr=.5)
            self.assertEqual(len(result['trades']), count)

    def test_repeated_calls_honor_changed_prepared_bias_without_input_mutation(self):
        data = prepare()
        preserved = deepcopy(data)
        first = run(fast, data)
        self.assertEqual(len(first['trades']), 1)
        data['chart']['hourly_bias'] = -1
        self.assertTrue(run(fast, data)['trades'].empty)
        data['chart']['hourly_bias'] = 1
        again = run(fast, data)
        pd.testing.assert_frame_equal(first['trades'], again['trades'], check_exact=True)
        for name in ('source', 'chart', 'hourly'):
            pd.testing.assert_frame_equal(data[name], preserved[name], check_exact=True)
        self.exact(data, max_zone_width_atr=0)
        pd.testing.assert_frame_equal(run(fast, data)['trades'], first['trades'], check_exact=True)

    def test_prefix_extension_future_mutation_and_incomplete_final_buckets(self):
        data = prepare(HISTORY + BASE + [NO_TOUCH, FILL, (110, 111, 109, 110)] + HISTORY + BASE + [FILL])
        for cutoff in (117, 123, 126, 133, 139):
            raw = data['source'].iloc[:cutoff]
            prefix = prepare(source=raw)
            end = raw.index[-1] + pd.Timedelta(minutes=1)
            future = data['source'].copy()
            future.iloc[cutoff:, future.columns.get_indexer(['open', 'high', 'low', 'close'])] += 1000
            future.iloc[cutoff:, future.columns.get_loc('volume')] *= 1000
            options = dict(end=end, zone_boundary='body', entry_eligibility='any_touch', order_lifetime_bars=3,
                slippage_model='price', max_zone_width_atr=1, min_departure_atr=1, min_departure_rvol=1, max_touch_age_hours=2)
            expected = self.exact(prefix, **options)
            for extended in (data, prepare(source=future)):
                actual = self.exact(extended, **options)
                for name in ('trades', 'equity'):
                    pd.testing.assert_frame_equal(expected[name], actual[name], check_exact=True)

    def test_real_structure_multi_trade_roll_capacity_and_decimal_tick_parity(self):
        rng = np.random.default_rng(9283)
        opened = 100 + rng.normal(0, .7, 900).cumsum()
        closed = opened + rng.normal(0, .6, 900)
        source = source_frame(list(zip(opened, np.maximum(opened, closed)+rng.uniform(.1, .8, 900),
            np.minimum(opened, closed)-rng.uniform(.1, .8, 900), closed)), volumes=rng.integers(1, 100, 900))
        source['instrument_id'] = np.repeat([10, 20, 30], 300)
        data = prepare(source=source, resolution=5, controlled=False)
        for boundary, mode, rr in itertools.product(('wick', 'body'), ('cash', 'price'), (.75, 1.25)):
            result = self.exact(data, use_htf=False, zone_boundary=boundary, require_fvg=False, slippage_model=mode,
                stop_model='candle', entry_eligibility='any_touch', order_lifetime_bars=3, min_opposing_room_r=0,
                max_active=1, max_age=25, rr=rr, tick_size=.1, point_value=10)
            self.assertGreater(len(result['trades']), 1)
            self.assertGreater(result['diagnostics']['context_zones_discarded_capacity'], 0)
            self.assertEqual(result['diagnostics']['detected_rolls'], 2)

    def test_raw_api_preparation_pivot_change_and_rejected_parameters(self):
        frame = prepare()['source'].drop(columns='segment')
        expected = reference.prepare_data(frame, pivot_len=2, execution_minutes=1)
        actual = fast.prepare_data(frame, pivot_len=2, execution_minutes=1)
        for name in ('source', 'chart', 'hourly'):
            pd.testing.assert_frame_equal(expected[name], actual[name], check_exact=True)
        options = dict(pivot_len=2, execution_minutes=1, use_htf=False, require_fvg=False, zone_boundary='body')
        args = (frame, options, frame.index[0], frame.index[-1]+pd.Timedelta(minutes=1), .25, 2, 1, 1)
        old, new = reference.run_model(*args), fast.run_model(*args)
        for name in ('trades', 'equity'):
            pd.testing.assert_frame_equal(old[name], new[name], check_exact=True)
        # A dictionary prepared with pivot1 must be rebuilt when pivot2 is
        # requested, rather than reusing prior bias/feature arrays.
        p1 = prepare()
        old = reference.run_model(deepcopy(p1), *args[1:])
        new = fast.run_model(deepcopy(p1), *args[1:])
        for name in ('trades', 'equity'):
            pd.testing.assert_frame_equal(old[name], new[name], check_exact=True)
        for options in (dict(zone_boundary='close'), dict(order_lifetime_bars=True), dict(order_lifetime_bars=0),
                        dict(min_departure_atr=-1), dict(min_departure_rvol='2'), dict(max_touch_age_hours=np.inf),
                        dict(entry_eligibility='rolling'), dict(slippage_model='both')):
            with self.assertRaises(ValueError):
                run(fast, prepare(), **options)


if __name__ == '__main__':
    unittest.main()
