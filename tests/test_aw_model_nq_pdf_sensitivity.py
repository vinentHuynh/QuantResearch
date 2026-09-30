"""Focused checks for the exploratory AW PDF rule switches."""

from contextlib import redirect_stdout
import io
import unittest

import numpy as np
import pandas as pd

from strategies import aw_model_nq_pdf_sensitivity as aw
from strategies import aw_model_nq_revised as frozen
from test_aw_model_nq import CT, fixture, request
from workbench.contract import metadata, resolve_parameters
from workbench.events import simulate_events


def parameters(**changes):
    return resolve_parameters(aw.STRATEGY, changes)


class AWPDFSensitivityTests(unittest.TestCase):
    def test_adapter_is_discoverable_and_defaults_match_frozen_switches(self):
        spec = metadata('strategies/aw_model_nq_pdf_sensitivity.py')
        self.assertEqual(spec['id'], 'aw-model-nq-pdf-sensitivity')
        self.assertEqual(parameters()['trend_proxy'], 'strict')
        self.assertEqual(parameters()['fvg_window'], 'immediate')
        self.assertTrue(parameters()['location_gate'])

    def test_default_switches_replay_the_frozen_fixture(self):
        bars = fixture()
        changes = {'bias_policy': 'unrestricted', 'min_rr_early': 0.0,
                   'min_rr_primary': 0.0}
        original = frozen.create_strategy(
            bars, resolve_parameters(frozen.STRATEGY, changes), request())
        sensitivity = aw.create_strategy(bars, parameters(**changes), request())
        day = pd.Timestamp('2024-03-12').date()
        original.days[day].htf_mid = 0.0
        sensitivity.days[day].htf_mid = 0.0
        with redirect_stdout(io.StringIO()):
            original_equity, original_trades, _, original_signals = simulate_events(
                bars, original, request(), return_signals=True)
            sensitivity_equity, sensitivity_trades, _, sensitivity_signals = simulate_events(
                bars, sensitivity, request(), return_signals=True)
        pd.testing.assert_frame_equal(original_equity, sensitivity_equity)
        pd.testing.assert_frame_equal(original_trades, sensitivity_trades)
        pd.testing.assert_frame_equal(original_signals, sensitivity_signals)
        self.assertEqual(original.funnel, sensitivity.funnel)

    def test_one_sided_trend_uses_two_swept_side_pivots_and_opposite_neckline(self):
        bars = fixture()
        model = aw.create_strategy(bars, parameters(bias_policy='unrestricted'), request())
        day = pd.Timestamp('2024-03-12').date()
        state = {'tradable': True, 'position': 0, 'position_at_open': 0,
                 'working_order_id': None}
        model._new_day(day, state)
        model.pivot_highs = [(100.5, pd.Timestamp('2024-03-12 07:30', tz=CT)),
                             (101.0, pd.Timestamp('2024-03-12 08:00', tz=CT))]
        model.pivot_lows = [(99.0, pd.Timestamp('2024-03-12 08:09', tz=CT))]
        k = model.start3.get_loc(pd.Timestamp('2024-03-12 08:30', tz=CT))
        model._try_sweep(k, state)
        self.assertIsNone(model.candidate)
        model.parameters['trend_proxy'] = 'one-sided'
        model._try_sweep(k, state)
        self.assertIsNotNone(model.candidate)
        self.assertEqual(model.candidate.side, -1)
        self.assertEqual(model.candidate.neckline, 99.0)

        model.candidate = None
        model.pivot_lows = []
        model._try_sweep(k, state)
        self.assertIsNone(model.candidate)

    def test_leg_window_accepts_mss_as_third_or_first_only_on_contiguous_bars(self):
        model = object.__new__(aw.AWModelNQ)
        model.parameters = {'fvg_window': 'leg-2'}
        model.signal_width = pd.Timedelta(minutes=3)
        model.start3 = pd.date_range('2024-03-12 08:30', periods=5,
                                     freq='3min', tz=CT)
        model.contract3 = np.ones(5, dtype=int)
        model.high3 = np.array([102., 101., 99., 100., 99.])
        model.low3 = np.array([101., 100., 98., 99., 98.])
        model.close3 = np.array([101.5, 100.5, 99., 98.5, 98.])
        candidate = aw.Candidate(-1, 'ONH', 102., 100., 103.,
                                 pd.Timestamp('2024-03-12 08:30', tz=CT),
                                 mss_index=2)
        self.assertEqual(model._fvg(2, candidate), (99., 101.))
        model.parameters['fvg_window'] = 'immediate'
        self.assertIsNone(model._fvg(2, candidate))

        model.parameters['fvg_window'] = 'leg-2'
        model.high3[2] = 101.
        model.high3[3] = 100.
        model.high3[4] = 97.
        self.assertIsNone(model._fvg(2, candidate))
        self.assertIsNone(model._fvg(3, candidate))
        self.assertEqual(model._fvg(4, candidate), (97., 98.))
        model.contract3[3] = 2
        self.assertIsNone(model._fvg(4, candidate))
        model.contract3[3] = 1
        model.close3[3] = 100.25
        self.assertIsNone(model._fvg(4, candidate))

    def test_location_switch_only_removes_midpoint_rejection(self):
        bars = fixture()
        model = aw.create_strategy(bars, parameters(
            bias_policy='unrestricted', min_rr_early=0.0,
            min_rr_primary=0.0), request())
        day = pd.Timestamp('2024-03-12').date()
        model._new_day(day, {'position': 0})
        model.days[day].htf_mid = 200.0
        candidate = aw.Candidate(-1, 'ONH', 101.25, 99.0, 101.75,
                                 pd.Timestamp('2024-03-12 08:33', tz=CT),
                                 gap_low=99.25, gap_high=99.75,
                                 setup_id='AW-test-location')
        ready = pd.Timestamp('2024-03-12 08:42', tz=CT)
        bar = pd.Series({'open': 99.0, 'high': 99.5,
                         'low': 98.75, 'close': 99.0})
        with redirect_stdout(io.StringIO()):
            self.assertIsNone(model._order_for_gap(candidate, bar, ready))
            model.parameters['location_gate'] = False
            order = model._order_for_gap(candidate, bar, ready)
        self.assertIsNotNone(order)
        self.assertEqual(order['timing'], 'limit')
        self.assertEqual(order['signal_id'], 'AW-test-location')
        self.assertLessEqual(abs(order['target']) *
                             (candidate.extreme + model.tick - 99.25) * 2,
                             500.0)


if __name__ == '__main__':
    unittest.main()
