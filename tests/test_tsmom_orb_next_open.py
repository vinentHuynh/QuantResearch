"""Calendar ORB next-open orders must not survive their known deadlines."""
import contextlib
import io
import unittest

import pandas as pd

from strategies._pine_models import IntradayORB
from test_pine_ports import REQUEST, bars, params
from workbench.events import simulate_events


class OrbNextOpenTests(unittest.TestCase):
    def model(self, data):
        parameters = params('tsmom_orb', risk_budget=250, maximum_contracts=1,
                            execution_timing='next-open')
        model = IntradayORB(data, parameters, REQUEST)
        model.known.loc[:, 'score'] = 1.0
        return model

    def replay(self, data):
        # Expiration is expected in several cases; assertions inspect behavior.
        with contextlib.redirect_stdout(io.StringIO()):
            return simulate_events(data, self.model(data), REQUEST)

    def test_regular_entry_and_exit_use_successor_open_prices_and_times(self):
        data = bars(['2026-01-20 09:30', '2026-01-20 09:35', '2026-01-20 09:40',
                     '2026-01-20 09:45', '2026-01-20 09:50', '2026-01-20 15:45',
                     '2026-01-20 15:50', '2026-01-20 16:00'],
                    opens=[100, 100, 100, 100, 103, 104, 105, 105],
                    closes=[100, 100, 100, 102, 103, 104, 105, 105])
        _, trades, _ = self.replay(data)
        self.assertEqual(len(trades), 1)
        trade = trades.iloc[0]
        self.assertEqual(pd.Timestamp(trade.entry_time), data.index[4])
        self.assertEqual(pd.Timestamp(trade.exit_time), data.index[6])
        self.assertEqual(trade.entry, 103)
        self.assertEqual(trade.exit, 105)
        self.assertEqual(trade.exit_reason, 'calendar force-flat')

    def test_pending_entry_expires_when_next_quote_arrives_after_deadline(self):
        data = bars(['2026-01-19 09:30', '2026-01-19 09:35', '2026-01-19 09:40',
                     '2026-01-19 12:45', '2026-01-19 13:00'],
                    closes=[100, 100, 100, 102, 103])
        _, trades, positions = self.replay(data)
        self.assertTrue(trades.empty)
        self.assertFalse(positions.contracts.any())
        self.assertFalse(positions.intrabar_contracts.any())

    def test_pending_entry_cannot_fill_exactly_at_no_entry_deadline(self):
        data = bars(['2026-01-19 09:30', '2026-01-19 09:35', '2026-01-19 09:40',
                     '2026-01-19 12:45', '2026-01-19 12:55'],
                    opens=[100, 100, 100, 100, 103],
                    closes=[100, 100, 100, 102, 103])
        _, trades, positions = self.replay(data)
        self.assertTrue(trades.empty)
        self.assertFalse(positions.intrabar_contracts.any())

    def early_exit_gap(self, next_quote):
        return bars(['2026-01-19 09:30', '2026-01-19 09:35', '2026-01-19 09:40',
                     '2026-01-19 09:45', '2026-01-19 09:50', '2026-01-19 12:50',
                     next_quote],
                    opens=[100, 100, 100, 100, 102, 103, 80],
                    closes=[100, 100, 100, 102, 102, 103, 80])

    def test_pending_exit_expires_across_halt_and_gap_bracket_cannot_hide_failure(self):
        with self.assertRaisesRegex(ValueError, 'missed scheduled session exit'):
            self.replay(self.early_exit_gap('2026-01-19 18:00'))

    def test_pending_exit_cannot_fill_on_quote_at_exclusive_session_close(self):
        with self.assertRaisesRegex(ValueError, 'missed scheduled session exit'):
            self.replay(self.early_exit_gap('2026-01-19 13:00'))


if __name__ == '__main__':
    unittest.main()
