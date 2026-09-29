"""Stateful sizing parity, rejection lifecycle and frozen gap quantities."""
import itertools
import unittest

import numpy as np
import pandas as pd

from strategies import _snd_combination_reference as reference
from strategies import _snd_combination_risk as risk
from test_snd_zone_quality import BASE, FILL, HISTORY, NO_TOUCH, source_frame


QUALITY = dict(max_zone_width_atr=1, min_departure_atr=1,
               min_departure_rvol=2, max_touch_age_hours=1)


def prepare(rows=None, mirror=False, minute=True):
    rows = HISTORY + BASE + [FILL] if rows is None else rows
    volumes = np.full(len(rows), 10.)
    volumes[len(HISTORY) + 1] = 40.
    data = risk.prepare_data(source_frame(rows, mirror, minute, volumes), 1, 1 if minute else 5)
    # These lifecycle fixtures supply a controlled prior structure state.
    data['chart']['bias'] = data['chart']['hourly_bias'] = -1 if mirror else 1
    return data


def run(data, model=risk, end=None, **options):
    return model.run_model(data, dict(pivot_len=1, execution_minutes=data['execution_minutes'], **options),
        data['source'].index[0], end or data['source'].index[-1] + pd.Timedelta(minutes=data['execution_minutes']),
        tick_size=.25, point_value=2, fee=1, slippage_ticks=1)


class CombinationRiskTests(unittest.TestCase):
    def accounting(self, result):
        t, e = result['trades'], result['equity']
        np.testing.assert_allclose(t.gross_pnl - t.cost, t.net_pnl)
        np.testing.assert_allclose(t.net_pnl / t.risk_cash, t.net_r)
        self.assertAlmostEqual(e.net_pnl.sum(), e.equity.iloc[-1] - 100000)
        self.assertAlmostEqual(result['diagnostics']['accounting_error'], 0)
        if result['parameters']['finalize']:
            self.assertAlmostEqual(t.net_pnl.sum(), e.equity.iloc[-1] - 100000)

    def test_fixed_one_exact_reference_parity_crossed_geometry_rules_and_quality(self):
        for mirror, minute in itertools.product([False, True], repeat=2):
            data = prepare(mirror=mirror, minute=minute)
            for boundary, stop, mode, eligibility, ttl, strict in itertools.product(
                    ['wick', 'body'], ['zone', 'candle'], ['cash', 'price'],
                    ['first_touch', 'any_touch'], [1, 3], [False, True]):
                p = dict(QUALITY, zone_boundary=boundary, stop_model=stop, slippage_model=mode,
                         entry_eligibility=eligibility, order_lifetime_bars=ttl, require_fvg=strict)
                with self.subTest(mirror=mirror, minute=minute, **p):
                    old, new = run(data, reference, **p), run(data, **p)
                    self.assertGreater(len(old['trades']), 0)
                    pd.testing.assert_frame_equal(old['trades'], new['trades'][reference.TRADE_COLUMNS], check_exact=True)
                    pd.testing.assert_frame_equal(old['equity'], new['equity'], check_exact=True)
                    self.accounting(new)

    def test_fixed_one_reference_parity_with_real_structure_and_multiple_trades(self):
        rng = np.random.default_rng(739)
        opened = 100 + rng.normal(0, .7, 1200).cumsum()
        closed = opened + rng.normal(0, .6, 1200)
        rows = list(zip(opened, np.maximum(opened, closed) + rng.uniform(.1, .8, 1200),
                        np.minimum(opened, closed) - rng.uniform(.1, .8, 1200), closed))
        source = source_frame(rows, volumes=rng.integers(1, 100, 1200))
        data = risk.prepare_data(source, 1, 5)
        for boundary, stop, mode in itertools.product(['wick', 'body'], ['zone', 'candle'], ['cash', 'price']):
            p = dict(zone_boundary=boundary, stop_model=stop, slippage_model=mode, use_htf=False,
                     require_fvg=False, entry_eligibility='any_touch', order_lifetime_bars=3,
                     min_opposing_room_r=0, min_departure_atr=.1, max_zone_width_atr=5,
                     min_departure_rvol=.1, max_touch_age_hours=24)
            old, new = run(data, reference, **p), run(data, **p)
            self.assertGreater(len(old['trades']), 1)
            pd.testing.assert_frame_equal(old['trades'], new['trades'][reference.TRADE_COLUMNS], check_exact=True)
            pd.testing.assert_frame_equal(old['equity'], new['equity'], check_exact=True)

    def test_quality_rejection_precedes_sizing_and_body_width_is_selected_geometry(self):
        data = prepare()
        for boundary in ('wick', 'body'):
            accepted = run(data, zone_boundary=boundary, **QUALITY)
            t = accepted['trades'].iloc[0]
            self.assertEqual(t.zone_width_atr, (t.zone_top - t.zone_bottom) / t.prior_atr20)
            rejected = run(data, zone_boundary=boundary, sizing_mode='fixed_risk', risk_budget=.01,
                           **(QUALITY | {'max_zone_width_atr': t.zone_width_atr - .01}))
            self.assertTrue(rejected['trades'].empty)
            self.assertTrue(rejected['sizing_decisions'].empty)
            self.assertEqual(rejected['diagnostics']['quality_rejections_at_signal'], 1)
            self.assertEqual(rejected['diagnostics']['sizing_rejections'], 0)
            self.assertEqual(rejected['diagnostics']['entry_orders_armed'], 0)

    def test_whole_contract_floor_cap_cost_reserve_and_quantity_scaling(self):
        for boundary, stop, mode, mirror in itertools.product(
                ['wick', 'body'], ['zone', 'candle'], ['cash', 'price'], [False, True]):
            data = prepare(mirror=mirror)
            options = dict(QUALITY, zone_boundary=boundary, stop_model=stop, slippage_model=mode)
            one = run(data, **options)
            planned = abs(one['trades'].entry_reference.iloc[0] - one['trades'].stop.iloc[0]) * 2 + 3
            for budget, cap, quantity, capped in ((planned * 3 - .01, 10, 2, False),
                    (planned * 3, 10, 3, False), (planned * 4, 2, 2, True)):
                result = run(data, **options, sizing_mode='fixed_risk', risk_budget=budget, max_contracts=cap)
                t = result['trades'].iloc[0]
                self.assertEqual(t.contracts_abs, quantity)
                self.assertEqual(t.quantity, (-1 if mirror else 1) * quantity)
                self.assertEqual(t.quantity_capped, capped)
                self.assertEqual(t.planned_stop_risk_per_contract, planned)
                self.assertEqual(t.planned_stop_risk_cash, planned * quantity)
                for column in ('risk_cash', 'initial_risk_cash', 'gross_pnl', 'cost', 'net_pnl'):
                    self.assertEqual(t[column], one['trades'].iloc[0][column] * quantity)
                self.assertEqual(t.net_r, one['trades'].net_r.iloc[0])
                self.accounting(result)

    def test_rejected_large_zone_changes_stateful_trade_selection(self):
        rows = HISTORY + BASE + [FILL, (103.5, 104, 102.75, 103), (103, 105.5, 103, 105),
            (105, 105.5, 104.5, 105), (104.5, 104.75, 103.5, 104), (105, 105.5, 104.75, 105.25)]
        data = prepare(rows, minute=False)
        options = dict(max_zone_width_atr=1, min_departure_atr=.1, min_departure_rvol=.1, max_touch_age_hours=1)
        one, sized = run(data, **options), run(data, **options, sizing_mode='fixed_risk', risk_budget=10)
        self.assertEqual(len(one['trades']), 1)
        self.assertEqual(len(sized['trades']), 1)
        self.assertNotEqual(one['trades'].zone_time.iloc[0], sized['trades'].zone_time.iloc[0])
        self.assertEqual(sized['diagnostics']['sizing_rejections'], 1)
        self.assertEqual(sized['sizing_decisions'].quantity_selected.to_list(), [0, 1])
        self.accounting(sized)

    def test_gap_never_resizes_pending_quantity_and_reports_budget_overshoot(self):
        for boundary, mode, mirror in itertools.product(['wick', 'body'], ['cash', 'price'], [False, True]):
            data = prepare(HISTORY + BASE + [NO_TOUCH, (110, 111, 109, 110)], mirror=mirror)
            options = dict(QUALITY, zone_boundary=boundary, slippage_model=mode, order_lifetime_bars=3)
            one = run(data, **options)['trades'].iloc[0]
            planned = abs(one.entry_reference - one.stop) * 2 + 3
            r = run(data, **options, sizing_mode='fixed_risk', risk_budget=planned * 3)
            t = r['trades'].iloc[0]
            self.assertEqual(t.contracts_abs, 3)
            self.assertEqual(t.planned_stop_risk_cash, planned * 3)
            expected = (abs(t.entry - t.stop) * 2 + 2 + (1 if mode == 'cash' else .5)) * 3
            self.assertEqual(t.actual_stop_risk_cash, expected)
            self.assertEqual(t.risk_budget_overshoot_cash, expected - planned * 3)
            self.assertEqual(r['diagnostics']['risk_budget_overshoot_entries'], 1)
            self.accounting(r)

    def test_future_extension_does_not_change_as_of_risk_state_or_features(self):
        data = prepare(HISTORY + BASE + [NO_TOUCH, FILL, (111, 112, 110, 111)] + [FILL] * 4)
        options = dict(QUALITY, zone_boundary='body', sizing_mode='fixed_risk', risk_budget=36,
                       order_lifetime_bars=3, record_events=True, finalize=False)
        for count in (123, 126, 128, 134, 143):
            source = data['source'].iloc[:count]
            prefix = risk.prepare_data(source, 1, 1)
            prefix['chart']['bias'] = prefix['chart']['hourly_bias'] = 1
            end = source.index[-1] + pd.Timedelta(minutes=1)
            a, b = run(prefix, end=end, **options), run(data, end=end, **options)
            for name in ('trades', 'equity', 'events', 'sizing_decisions'):
                pd.testing.assert_frame_equal(a[name], b[name], check_exact=True)
            self.assertEqual(a['open_state'], b['open_state'])

    def test_invalid_sizing_and_quality_inputs_reject(self):
        data = prepare()
        for p in (dict(zone_boundary='close'), dict(max_zone_width_atr=-1), dict(contracts=0),
                  dict(contracts=True), dict(max_contracts=1.2), dict(risk_budget=0),
                  dict(risk_budget=np.inf), dict(sizing_mode='fractional')):
            with self.assertRaises(ValueError):
                run(data, **p)


if __name__ == '__main__':
    unittest.main()
