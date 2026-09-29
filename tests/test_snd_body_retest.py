"""Boundary-only experiment: explicit geometry, execution and control parity."""
import unittest

import numpy as np
import pandas as pd

from strategies import _snd_body_retest as body
from strategies import _snd_fresh_retest as fresh


BASE = [(100, 101, 99, 99.5), (99.5, 104, 99.5, 103),
        (103, 104, 102, 103.5), (102, 103, 100, 102)]
FILL = [(104, 105, 103.5, 104.5)]


def prepared(rows, mirror=False, minute=False):
    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    if minute:
        frame = frame.loc[frame.index.repeat(5)].reset_index(drop=True)
    frame.index = pd.date_range("2026-01-05 12:00:00+00:00", periods=len(frame),
                                freq="1min" if minute else "5min")
    if mirror:
        old = frame.copy()
        frame["open"], frame["close"] = 250 - old.open, 250 - old.close
        frame["high"], frame["low"] = 250 - old.low, 250 - old.high
    result = body.prepare_data(frame, pivot_len=1, execution_minutes=1 if minute else 5)
    result["chart"]["bias"] = result["chart"]["hourly_bias"] = -1 if mirror else 1
    return result


def run(data, model=body, end=None, **options):
    params = dict(pivot_len=1, execution_minutes=data["execution_minutes"])
    params.update(options)
    return model.run_model(data, params, data["source"].index[0],
                           end or data["source"].index[-1] + pd.Timedelta(minutes=data["execution_minutes"]),
                           tick_size=.25, point_value=2, fee=1, slippage_ticks=1)


class BodyBoundaryTests(unittest.TestCase):
    def test_exact_body_boundaries_and_zone_stops_on_both_sides(self):
        # Candle two's body, rather than the base body, sets the distal edge.
        rows = [(100, 101, 99, 99.5), (98, 104, 97, 103),
                (103, 104, 102, 103.5), (102, 103, 99, 102)] + FILL
        for mirror in (False, True):
            data = prepared(rows, mirror=mirror)
            wick = run(data, zone_boundary="wick")["trades"].iloc[0]
            candidate = run(data, zone_boundary="body")["trades"].iloc[0]
            self.assertEqual(candidate.zone_top, 152 if mirror else 100)
            self.assertEqual(candidate.zone_bottom, 150 if mirror else 98)
            self.assertEqual(candidate.stop, 152.25 if mirror else 97.75)
            self.assertLessEqual(candidate.zone_top, wick.zone_top)
            self.assertGreaterEqual(candidate.zone_bottom, wick.zone_bottom)
            self.assertEqual(candidate.entry_reference, wick.entry_reference)
            self.assertEqual(candidate.entry, wick.entry)
            self.assertEqual(candidate.first_touch_time, wick.first_touch_time)
            self.assertEqual(candidate.signal_time, wick.signal_time)
            self.assertEqual(candidate.initial_risk, wick.initial_risk - 1)

    def test_body_gap_does_not_replace_required_wick_gap(self):
        rows = BASE[:2] + [(103, 104, 100.5, 103.5)] + BASE[3:] + FILL
        for mirror in (False, True):
            for boundary in ("wick", "body"):
                result = run(prepared(rows, mirror=mirror), zone_boundary=boundary)
                self.assertEqual(result["diagnostics"]["zones_created"], 0)
                self.assertEqual(result["diagnostics"]["context_zones_created"], 0)
                self.assertEqual(len(result["trades"]), 0)

    def test_wick_zone_touch_without_body_zone_touch_does_not_arm(self):
        rows = BASE[:3] + [(102, 103, 100.5, 102)] + FILL
        for mirror in (False, True):
            data = prepared(rows, mirror=mirror)
            wick = run(data, zone_boundary="wick")
            candidate = run(data, zone_boundary="body")
            self.assertEqual(len(wick["trades"]), 1)
            self.assertEqual(len(candidate["trades"]), 0)
            self.assertEqual(candidate["diagnostics"]["physical_first_touches"], 0)
            self.assertEqual(candidate["diagnostics"]["entry_orders_armed"], 0)

    def test_wick_breach_still_invalidates_when_close_is_inside_body_zone(self):
        rows = BASE[:3] + [(100, 101.5, 99.25, 100), (102, 104, 101.5, 103)]
        for mirror in (False, True):
            data = prepared(rows, mirror=mirror)
            wick = run(data, zone_boundary="wick")
            candidate = run(data, zone_boundary="body")
            self.assertEqual(len(wick["trades"]), 1)
            self.assertEqual(len(candidate["trades"]), 0)
            self.assertEqual(candidate["diagnostics"]["zone_invalidations"], 1)
            self.assertEqual(candidate["diagnostics"]["context_zone_invalidations"], 1)
            self.assertEqual(candidate["diagnostics"]["entry_orders_armed"], 0)

    def test_body_zone_stop_fills_on_wick_even_when_candle_recovers(self):
        rows = BASE + FILL + [(101, 102, 99.25, 101.5)]
        for mirror in (False, True):
            result = run(prepared(rows, mirror=mirror), zone_boundary="body")
            trade = result["trades"].iloc[0]
            self.assertEqual(trade.exit_reason, "stop")
            self.assertEqual(trade.stop, 150.75 if mirror else 99.25)
            self.assertEqual(trade.exit, trade.stop)
            self.assertEqual(trade.gross_pnl, -trade.initial_risk_cash)
            self.assertAlmostEqual(result["diagnostics"]["accounting_error"], 0)
            self.assertAlmostEqual(result["equity"].equity.iloc[-1] - 100000,
                                   result["trades"].net_pnl.sum())

    def test_opposing_context_body_boundary_and_reduced_risk_change_room(self):
        # This unaligned supply is context only; it never forms a short-entry
        # zone. Its proximal moves from wick 112 to body 112.5.
        rows = [(112.5, 114, 112, 113), (113, 113.5, 108, 109),
                (108, 109, 107, 108)] + BASE + [(103, 104, 102, 103.5)]
        for mirror in (False, True):
            data = prepared(rows, mirror=mirror)
            wick = run(data, zone_boundary="wick")
            candidate = run(data, zone_boundary="body")
            self.assertEqual(wick["diagnostics"]["room_rejections_at_signal"], 1)
            self.assertEqual(len(wick["trades"]), 0)
            self.assertEqual(candidate["diagnostics"]["zones_created"], 1)
            self.assertEqual(candidate["diagnostics"]["context_zones_created"], 2)
            self.assertEqual(len(candidate["trades"]), 1)
            trade = candidate["trades"].iloc[0]
            self.assertEqual(trade.opposing_boundary, 137.5 if mirror else 112.5)
            self.assertEqual(trade.initial_risk, 4)
            self.assertEqual(trade.opposing_room_r, 9.25 / 4)

    def test_body_mode_does_not_change_zone_formation_qualification(self):
        rng = np.random.default_rng(91573)
        opened = 100 + rng.normal(0, .8, 800).cumsum()
        closed = opened + rng.normal(0, .5, 800)
        rows = list(zip(opened, np.maximum(opened, closed) + .3,
                        np.minimum(opened, closed) - .4, closed))
        for mirror in (False, True):
            data = prepared(rows, mirror=mirror)
            wick = run(data, zone_boundary="wick")
            candidate = run(data, zone_boundary="body")
            for key in ("zones_created", "context_zones_created"):
                self.assertGreater(wick["diagnostics"][key], 0)
                self.assertEqual(wick["diagnostics"][key], candidate["diagnostics"][key])

    def test_future_source_cannot_change_body_prefix_trades_or_equity(self):
        rows = BASE + FILL + [(110, 111, 109, 110)]
        rows += [(110, 112, 109, 111)] * 5 + BASE + FILL
        for mirror in (False, True):
            full = prepared(rows, minute=True, mirror=mirror)
            for cutoff in (20, 25, 30, 36, 55, 66):
                source = full["source"].iloc[:cutoff]
                prefix = body.prepare_data(source, 1, 1)
                prefix["chart"]["bias"] = prefix["chart"]["hourly_bias"] = -1 if mirror else 1
                end = source.index[-1] + pd.Timedelta(minutes=1)
                result_full = run(full, end=end, zone_boundary="body")
                result_prefix = run(prefix, end=end, zone_boundary="body")
                pd.testing.assert_frame_equal(result_full["trades"], result_prefix["trades"])
                pd.testing.assert_frame_equal(result_full["equity"], result_prefix["equity"])

    def test_default_and_explicit_wick_match_existing_engine_exactly(self):
        rng = np.random.default_rng(40817)
        opened = 100 + rng.normal(0, .7, 800).cumsum()
        closed = opened + rng.normal(0, .5, 800)
        rows = list(zip(opened, np.maximum(opened, closed) + rng.uniform(.1, 1, 800),
                        np.minimum(opened, closed) - rng.uniform(.1, 1, 800), closed))
        for mirror in (False, True):
            data = prepared(rows, mirror=mirror)
            for stop_model in ("zone", "candle"):
                for fvg in (True, False):
                    for first_touch, room in ((True, 2), (False, 0)):
                        options = dict(stop_model=stop_model, require_fvg=fvg,
                                       first_touch_only=first_touch, min_opposing_room_r=room)
                        baseline = run(data, model=fresh, **options)
                        self.assertGreater(len(baseline["trades"]), 0)
                        for boundary in ({}, {"zone_boundary": "wick"}):
                            result = run(data, **boundary, **options)
                            pd.testing.assert_frame_equal(result["trades"], baseline["trades"])
                            pd.testing.assert_frame_equal(result["equity"], baseline["equity"])
                            self.assertEqual(result["diagnostics"], baseline["diagnostics"])
                            self.assertEqual(result["parameters"]["zone_boundary"], "wick")
                            self.assertEqual({key: value for key, value in result["parameters"].items()
                                              if key != "zone_boundary"}, baseline["parameters"])

    def test_invalid_boundary_is_rejected(self):
        for invalid in ("close", "BODY", None, ""):
            with self.assertRaisesRegex(ValueError, "zone_boundary must be wick/body"):
                run(prepared(BASE + FILL), zone_boundary=invalid)


if __name__ == "__main__":
    unittest.main()
