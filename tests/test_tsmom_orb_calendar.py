"""Regression tests for the ORB missing holiday exit, without future-bar lookahead."""
import unittest

import pandas as pd

from strategies._pine_models import IntradayORB
from strategies._cme_index_calendar import session_close_et
from test_pine_ports import bars, params, REQUEST
from workbench.events import simulate_events


class OrbCalendarTests(unittest.TestCase):
    def model(self, data):
        model = IntradayORB(data, params('tsmom_orb', risk_budget=250, maximum_contracts=1), REQUEST)
        model.known.loc[:, 'score'] = 1.
        return model

    def test_all_nine_original_carry_dates_have_known_preclose_deadlines(self):
        closes = {'2024-05-27': '13:00', '2024-11-29': '13:15', '2025-02-17': '13:00',
                  '2025-07-03': '13:15', '2025-07-04': '13:00', '2025-11-28': '13:15',
                  '2025-12-24': '13:15', '2026-01-19': '13:00', '2026-06-19': '13:00'}
        for day, close in closes.items():
            with self.subTest(day=day):
                self.assertEqual(session_close_et(day).strftime('%H:%M'), close)
                data = bars([day + ' 09:30'])
                model = self.model(data)
                self.assertEqual(model.deadlines[day], session_close_et(day) - pd.Timedelta(minutes=5))

    def test_early_close_flattens_before_halt_and_cannot_reenter(self):
        data = bars(['2026-01-19 09:30', '2026-01-19 09:35', '2026-01-19 09:40',
                     '2026-01-19 09:45', '2026-01-19 12:50', '2026-01-19 12:55'],
                    opens=[100, 100, 100, 102, 103, 103], closes=[100, 100, 100, 102, 103, 103])
        _, trades, _ = simulate_events(data, self.model(data), REQUEST)
        self.assertEqual(len(trades), 1)
        self.assertEqual(pd.Timestamp(trades.iloc[0].exit_time).strftime('%H:%M'), '12:55')
        self.assertEqual(trades.iloc[0].exit_reason, 'calendar force-flat')

    def test_normal_exit_remains_1550_and_missing_window_exits_after_1600(self):
        data = bars(['2026-01-20 09:30', '2026-01-20 09:35', '2026-01-20 09:40',
                     '2026-01-20 09:45', '2026-01-20 15:45', '2026-01-20 16:00'],
                    opens=[100, 100, 100, 102, 103, 103], closes=[100, 100, 100, 102, 103, 103])
        for omit, expected in [(False, '15:50'), (True, '16:05')]:
            frame = data.drop(data.index[4]) if omit else data
            _, trades, _ = simulate_events(frame, self.model(frame), REQUEST)
            self.assertEqual(pd.Timestamp(trades.iloc[0].exit_time).strftime('%H:%M'), expected)
            self.assertEqual(trades.iloc[0].exit_reason, 'calendar force-flat')

    def test_unobserved_early_close_exit_fails_even_if_gap_bracket_fills(self):
        data = bars(['2026-01-19 09:30', '2026-01-19 09:35', '2026-01-19 09:40',
                     '2026-01-19 09:45', '2026-01-19 18:00'],
                    opens=[100, 100, 100, 100, 80], closes=[100, 100, 100, 102, 80])
        with self.assertRaisesRegex(ValueError, 'missed scheduled session exit'):
            simulate_events(data, self.model(data), REQUEST)

    def test_missing_new_session_opening_range_cannot_reuse_yesterday(self):
        data = bars(['2026-01-20 09:30', '2026-01-20 09:35', '2026-01-20 09:40',
                     '2026-01-21 10:00'], closes=[100, 100, 100, 105])
        model = self.model(data)
        state = dict(position=0, equity=1000, tradable=True)
        for i in range(len(data)):
            self.assertIsNone(model.on_close(i, data.iloc[i], state))

    def test_deadline_is_prefix_causal_and_unknown_calendar_year_fails(self):
        data = bars(['2026-01-19 09:30', '2026-01-19 12:50', '2026-01-19 12:55'])
        self.assertEqual(self.model(data.iloc[:1]).deadlines, self.model(data).deadlines)
        with self.assertRaises(ValueError):
            session_close_et('2027-01-04')

    def test_good_friday_closed_before_orb_and_full_holiday_no_entry(self):
        self.assertEqual(session_close_et('2026-04-03').strftime('%H:%M'), '09:15')
        self.assertIsNone(session_close_et('2026-12-25'))
        for day in ['2026-04-03', '2026-12-25']:
            data = bars([day + ' 09:30', day + ' 09:35', day + ' 09:40', day + ' 09:45'],
                        closes=[100, 100, 100, 102])
            _, trades, _ = simulate_events(data, self.model(data), REQUEST)
            self.assertTrue(trades.empty)


if __name__ == '__main__':
    unittest.main()
