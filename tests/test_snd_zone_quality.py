"""Causal zone measurements, unchanged lifecycle, and no-filter parity fixtures."""
import unittest

import numpy as np
import pandas as pd

from strategies import _snd_entry_research as baseline
from strategies import _snd_zone_quality as quality


BASE = [(100, 101, 99, 99.5), (99.5, 104, 99.5, 103),
        (103, 104, 102, 103.5), (102, 103, 100, 102)]
FILL = (104, 105, 103.5, 104.5)
NO_TOUCH = (102, 103, 101.25, 102)
HISTORY = [(100, 101, 99, 100)] * 21


def source_frame(rows, mirror=False, minute=False, volumes=None):
    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    frame["volume"] = 10.0 if volumes is None else volumes
    if mirror:
        old = frame.copy()
        frame["open"], frame["close"] = 250 - old.open, 250 - old.close
        frame["high"], frame["low"] = 250 - old.low, 250 - old.high
    if minute:
        frame = frame.loc[frame.index.repeat(5)].reset_index(drop=True)
        frame["volume"] /= 5
    frame.index = pd.date_range("2026-01-05 12:00:00+00:00", periods=len(frame),
                                freq="1min" if minute else "5min")
    return frame


def prepare(frame, model=quality, execution_minutes=5, bias=1):
    data = model.prepare_data(frame, 1, execution_minutes)
    data["chart"]["bias"] = data["chart"]["hourly_bias"] = bias
    return data


def fixture(mirror=False, minute=False, rows=None):
    rows = HISTORY + BASE + [FILL] if rows is None else rows
    volumes = np.full(len(rows), 10.0)
    volumes[len(HISTORY) + 1] = 40
    return prepare(source_frame(rows, mirror, minute, volumes),
                   execution_minutes=1 if minute else 5, bias=-1 if mirror else 1)


def run(data, model=quality, end=None, **options):
    return model.run_model(data, dict(pivot_len=1, **options), data["source"].index[0],
                           end or data["source"].index[-1] + pd.Timedelta(minutes=data["execution_minutes"]),
                           tick_size=.25, point_value=2, fee=1, slippage_ticks=1)


class FormationMeasurementTests(unittest.TestCase):
    def test_expected_formulas_and_mirrored_geometry_at_both_resolutions(self):
        for mirror in (False, True):
            for minute in (False, True):
                with self.subTest(mirror=mirror, minute=minute):
                    data = fixture(mirror, minute)
                    trade = run(data)["trades"].iloc[0]
                    self.assertEqual(trade.prior_atr20, 2)
                    self.assertEqual(trade.prior_volume20, 10)
                    self.assertEqual(trade.zone_width_atr, 1)
                    self.assertEqual(trade.departure_atr, 1.75)
                    self.assertEqual(trade.departure_rvol, 4)
                    self.assertEqual(trade.signal_age_hours, 1 / 12)
                    self.assertEqual(trade.zone_top, 151 if mirror else 101)
                    self.assertEqual(trade.zone_bottom, 149 if mirror else 99)
                    self.assertEqual(trade.zone_time, data["chart"].index[24])

    def test_whole_formation_is_excluded_from_reference_means(self):
        frame = fixture()["source"].copy()
        original = prepare(frame)["chart"].iloc[23]
        # Change base range and close, departure, confirmation and their volume.
        frame.iloc[21:24, frame.columns.get_loc("high")] += 1000
        frame.iloc[21:24, frame.columns.get_loc("volume")] *= 1000
        frame.iloc[21, frame.columns.get_loc("close")] = 999
        changed = prepare(frame)["chart"].iloc[23]
        self.assertEqual(original.prior_atr20, changed.prior_atr20)
        self.assertEqual(original.prior_volume20, changed.prior_volume20)
        self.assertEqual(changed.prior_atr20, 2)
        self.assertEqual(changed.prior_volume20, 10)

    def test_true_range_uses_previous_close_and_requires_twenty_observations(self):
        rows = [(50, 51, 49, 50)] + HISTORY + BASE + [FILL]
        data = prepare(source_frame(rows))
        # At base index 21, the preceding 20 TRs include a 51-point gap TR.
        first = data["chart"].iloc[23]
        self.assertEqual(first.prior_atr20, (51 + 19 * 2) / 20)
        # Once that oldest TR falls out, the actual BASE formation has ATR 2.
        self.assertEqual(data["chart"].iloc[24].prior_atr20, 2)
        short = prepare(source_frame(HISTORY[:-1] + BASE + [FILL]))
        self.assertTrue(np.isnan(short["chart"].iloc[22].prior_atr20))

    def test_incomplete_reference_bucket_is_excluded_not_zero_imputed(self):
        rows = HISTORY + [HISTORY[0]] + BASE + [FILL]
        frame = source_frame(rows, minute=True)
        frame.iloc[50:55, frame.columns.get_loc("high")] = 1000
        frame.iloc[50:55, frame.columns.get_loc("volume")] = 1000
        frame = frame.drop(frame.index[52])
        data = prepare(frame, execution_minutes=1)
        self.assertFalse(data["chart"].complete.iloc[10])
        trade = run(data)["trades"].iloc[0]
        self.assertEqual(trade.prior_atr20, 2)
        self.assertEqual(trade.prior_volume20, 10)

    def test_roll_resets_reference_history_and_old_prices_cannot_contaminate(self):
        old = source_frame(HISTORY + BASE + [FILL])
        new = source_frame(HISTORY + BASE + [FILL])
        new.index += pd.Timedelta(hours=4)
        new.loc[:, ["open", "high", "low", "close"]] += 1000
        old["instrument_id"], new["instrument_id"] = 10, 20
        combined = pd.concat([old, new])
        full = prepare(combined)["chart"]
        separate = prepare(new)["chart"]
        pd.testing.assert_frame_equal(full.loc[new.index, list(quality.FORMATION_FEATURES)],
                                      separate[list(quality.FORMATION_FEATURES)], check_exact=True)
        self.assertTrue(np.isnan(full.loc[new.index[22], "prior_atr20"]))
        self.assertEqual(full.loc[new.index[23], "prior_atr20"], 2)
        combined.loc[old.index, ["open", "high", "low", "close"]] += 10000
        combined.loc[old.index, "volume"] *= 1000
        changed = prepare(combined)["chart"]
        pd.testing.assert_frame_equal(changed.loc[new.index, list(quality.FORMATION_FEATURES)],
                                      full.loc[new.index, list(quality.FORMATION_FEATURES)], check_exact=True)

    def test_missing_or_invalid_volume_never_becomes_an_activity_measure(self):
        for invalid in (None, np.nan, np.inf, -1):
            frame = fixture()["source"].copy()
            if invalid is None:
                frame = frame.drop(columns="volume")
            else:
                frame.iloc[22, frame.columns.get_loc("volume")] = invalid
            preserved = frame.copy(deep=True)
            data = prepare(frame)
            pd.testing.assert_frame_equal(frame, preserved, check_exact=True)
            result = run(data, min_departure_rvol=0)
            self.assertEqual(len(result["trades"]), 0)
            self.assertEqual(result["diagnostics"]["min_departure_rvol_missing_at_signal"], 1)


class EligibilityFilterTests(unittest.TestCase):
    def test_each_threshold_is_inclusive_and_rejects_only_at_arming(self):
        cases = (("max_zone_width_atr", 1, .999),
                 ("min_departure_atr", 1.75, 1.751),
                 ("min_departure_rvol", 4, 4.001),
                 ("max_touch_age_hours", 1 / 12, .08))
        for mirror in (False, True):
            for parameter, accepted, rejected in cases:
                with self.subTest(parameter=parameter, mirror=mirror):
                    data = fixture(mirror)
                    base = run(data)
                    passed = run(data, **{parameter: accepted})
                    failed = run(data, **{parameter: rejected})
                    pd.testing.assert_frame_equal(base["trades"], passed["trades"], check_exact=True)
                    pd.testing.assert_frame_equal(base["equity"], passed["equity"], check_exact=True)
                    self.assertEqual(len(failed["trades"]), 0)
                    self.assertEqual(failed["diagnostics"][f"{parameter}_rejections_at_signal"], 1)
                    self.assertEqual(failed["diagnostics"]["quality_rejections_at_signal"], 1)
                    for key in ("zones_created", "physical_first_touches", "zone_touches",
                                "context_zones_created", "context_zone_invalidations"):
                        self.assertEqual(base["diagnostics"][key], failed["diagnostics"][key])

    def test_each_missing_or_nonfinite_feature_rejects_enabled_rule(self):
        for parameter, feature in (("max_zone_width_atr", "zone_width_atr"),
                                   ("min_departure_atr", "departure_atr"),
                                   ("min_departure_rvol", "departure_rvol")):
            for missing in ("absent", np.nan, np.inf, -np.inf):
                with self.subTest(parameter=parameter, missing=missing):
                    data = fixture()
                    if missing == "absent":
                        data["chart"] = data["chart"].drop(columns=feature)
                    else:
                        data["chart"].loc[:, feature] = missing
                    result = run(data, **{parameter: 0})
                    self.assertEqual(len(result["trades"]), 0)
                    self.assertEqual(result["diagnostics"][f"{parameter}_missing_at_signal"], 1)
                    self.assertEqual(len(run(data)["trades"]), 1)
        self.assertEqual(quality._quality_rejections({}, np.nan,
                         {**quality.DEFAULTS, "max_touch_age_hours": 1}),
                         [("max_touch_age_hours", True)])

    def test_multiple_rule_rejections_count_candidate_once(self):
        result = run(fixture(), max_zone_width_atr=0, min_departure_atr=10,
                     min_departure_rvol=10, max_touch_age_hours=0)
        self.assertEqual(result["diagnostics"]["quality_rejections_at_signal"], 1)
        for parameter in quality.QUALITY_PARAMETERS:
            self.assertEqual(result["diagnostics"][f"{parameter}_rejections_at_signal"], 1)

    def test_elapsed_signal_age_includes_missing_buckets_and_order_delay_is_frozen(self):
        data = fixture(rows=HISTORY + BASE + [NO_TOUCH, FILL])
        source = data["source"].copy()
        stamps = source.index.to_list()
        stamps[24:] = [stamp + pd.Timedelta(hours=2) for stamp in stamps[24:]]
        source.index = pd.DatetimeIndex(stamps)
        data = prepare(source)
        age = 2 + 1 / 12
        accepted = run(data, max_touch_age_hours=age, order_lifetime_bars=3)
        self.assertEqual(len(accepted["trades"]), 1)
        trade = accepted["trades"].iloc[0]
        self.assertEqual(trade.signal_age_hours, age)
        self.assertGreater((trade.entry_time - trade.zone_time).total_seconds() / 3600, age)
        rejected = run(data, max_touch_age_hours=2, order_lifetime_bars=3)
        self.assertEqual(len(rejected["trades"]), 0)
        self.assertEqual(rejected["diagnostics"]["max_touch_age_hours_rejections_at_signal"], 1)

    def test_rejection_preserves_first_touch_consumption_and_any_touch_lifecycle(self):
        data = fixture(rows=HISTORY + BASE + [BASE[3], BASE[3], FILL])
        first = run(data, min_departure_atr=100)
        any_touch = run(data, min_departure_atr=100, entry_eligibility="any_touch")
        self.assertEqual(first["diagnostics"]["physical_first_touches"], 1)
        self.assertEqual(any_touch["diagnostics"]["physical_first_touches"], 1)
        self.assertEqual(first["diagnostics"]["quality_rejections_at_signal"], 1)
        self.assertEqual(any_touch["diagnostics"]["quality_rejections_at_signal"], 3)
        self.assertEqual(first["diagnostics"]["entry_orders_armed"], 0)
        self.assertEqual(any_touch["diagnostics"]["entry_orders_armed"], 0)

    def test_quality_filters_do_not_remove_opposing_context(self):
        b = 112
        context = [(b + .5, b + 2, b, b + 1),
                   (b + 1, b + 1.5, b - 4, b - 3), (b - 4, b - 3, b - 5, b - 4)]
        data = fixture(rows=HISTORY + context + BASE + [FILL])
        # The opposing zone is never eligible with fixed long bias, yet it
        # must obstruct entries even when its quality would fail the new rule.
        result = run(data, min_departure_atr=100)
        original = run(data)
        self.assertEqual(result["diagnostics"]["context_zones_created"], 2)
        self.assertEqual(result["diagnostics"]["room_rejections_at_signal"], 1)
        self.assertEqual(result["diagnostics"]["quality_rejections_at_signal"], 0)
        self.assertEqual(result["diagnostics"]["room_rejections_at_signal"],
                         original["diagnostics"]["room_rejections_at_signal"])
        self.assertEqual(result["diagnostics"]["room_rejections_at_fill"],
                         original["diagnostics"]["room_rejections_at_fill"])

    def test_invalid_parameters_are_rejected(self):
        for name in quality.QUALITY_PARAMETERS:
            for value in (-1, np.nan, np.inf, True, "1"):
                with self.subTest(name=name, value=value):
                    with self.assertRaises(ValueError):
                        run(fixture(), **{name: value})


class ParityAndCausalityTests(unittest.TestCase):
    def test_all_disabled_preserve_original_trade_equity_and_diagnostics(self):
        rng = np.random.default_rng(40817)
        opened = 100 + rng.normal(0, .7, 600).cumsum()
        closed = opened + rng.normal(0, .5, 600)
        rows = list(zip(opened, np.maximum(opened, closed) + rng.uniform(.1, 1, 600),
                        np.minimum(opened, closed) - rng.uniform(.1, 1, 600), closed))
        settings = ({}, dict(entry_eligibility="any_touch", order_lifetime_bars=3),
                    dict(slippage_model="price", require_fvg=False,
                         min_opposing_room_r=0, use_htf=False, rr=1.5))
        for mirror in (False, True):
            for minute in (False, True):
                source = source_frame(rows, mirror=mirror, minute=minute)
                old = prepare(source, baseline, 1 if minute else 5, -1 if mirror else 1)
                new = prepare(source, quality, 1 if minute else 5, -1 if mirror else 1)
                for settings_ in settings:
                    with self.subTest(mirror=mirror, minute=minute, settings=settings_):
                        expected = run(old, model=baseline, **settings_)
                        result = run(new, **settings_)
                        self.assertGreater(len(expected["trades"]), 0)
                        pd.testing.assert_frame_equal(result["trades"][baseline.TRADE_COLUMNS],
                                                      expected["trades"], check_exact=True)
                        pd.testing.assert_frame_equal(result["equity"], expected["equity"], check_exact=True)
                        for key, value in expected["diagnostics"].items():
                            self.assertEqual(result["diagnostics"][key], value, key)
                        for key, value in expected["parameters"].items():
                            self.assertEqual(result["parameters"][key], value, key)

    def test_prefix_extension_and_future_mutation_leave_features_and_results_unchanged(self):
        data = fixture(minute=True, rows=HISTORY + BASE + [FILL, (110, 111, 109, 110)]
                       + HISTORY + BASE + [FILL])
        full_source = data["source"]
        for cutoff in (110, 117, 120, 125, 126, 130, 136, 250):
            with self.subTest(cutoff=cutoff):
                prefix = prepare(full_source.iloc[:cutoff], execution_minutes=1)
                end = prefix["source"].index[-1] + pd.Timedelta(minutes=1)
                future = full_source.copy()
                future.iloc[cutoff:, future.columns.get_indexer(["open", "high", "low", "close"])] += 1000
                future.iloc[cutoff:, future.columns.get_loc("volume")] *= 1000
                mutated = prepare(future, execution_minutes=1)
                complete_prefix = prefix["chart"].loc[prefix["chart"].complete]
                for candidate in (data, mutated):
                    pd.testing.assert_frame_equal(
                        complete_prefix[list(quality.FORMATION_FEATURES)],
                        candidate["chart"].loc[complete_prefix.index, list(quality.FORMATION_FEATURES)],
                        check_exact=True)
                    options = dict(end=end, max_zone_width_atr=2, min_departure_atr=1,
                                   min_departure_rvol=1, max_touch_age_hours=2,
                                   order_lifetime_bars=3, slippage_model="price")
                    expected, result = run(prefix, **options), run(candidate, **options)
                    pd.testing.assert_frame_equal(result["trades"], expected["trades"], check_exact=True)
                    pd.testing.assert_frame_equal(result["equity"], expected["equity"], check_exact=True)


if __name__ == "__main__":
    unittest.main()
