"""Focused causal-feature, exact-bin, and paired-bootstrap checks."""
import numpy as np
import pandas as pd


def run_focused_checks(actual_sessions=None):
    from analysis import make_session_context, hit_bucket, relative_bucket, bootstrap_draws
    dates = pd.bdate_range("2023-11-01", periods=60).strftime("%Y-%m-%d")
    synthetic = pd.DataFrame({"date": dates, "window": 15, "range_pts": np.arange(100., 160.)})
    original = make_session_context(synthetic)
    assert original.prior20_median_range_pts.iloc[:20].isna().all()
    assert original.prior20_median_range_pts.iloc[20] == 109.5
    assert original.prior20_median_range_pts.iloc[21] == 110.5
    perturbed = synthetic.copy()
    perturbed.loc[25, "range_pts"] = .25
    perturbed.loc[26:, "range_pts"] += 1000000
    changed = make_session_context(perturbed)
    pd.testing.assert_series_equal(original.prior20_median_range_pts.iloc[:26], changed.prior20_median_range_pts.iloc[:26])
    assert original.prior20_median_range_pts.iloc[26] != changed.prior20_median_range_pts.iloc[26]
    assert [hit_bucket(x) for x in [0, 4, 5, 9, 10, 14]] == ["09:30-09:34"]*2+["09:35-09:39"]*2+["09:40-09:44"]*2
    assert [relative_bucket(x) for x in [.749999, .75, 1.249999, 1.25, np.nan]] == [
        "below_0.75x", "0.75_to_below_1.25x", "0.75_to_below_1.25x", "at_least_1.25x", None]
    for bad in [-1, 15, 4.5]:
        try: hit_bucket(bad)
        except ValueError: pass
        else: raise AssertionError("Invalid hit bucket input accepted")
    toy = pd.DataFrame({"date": ["2024-01-02", "2024-02-01"], "month": ["2024-01", "2024-02"],
                        "continuation_certain": [1, 0], "continuation_possible": [1, 1]})
    plan = {"months": ["2024-01", "2024-02"], "weights": np.array([[2, 0], [1, 1], [0, 2]])}
    rates, valid = bootstrap_draws(toy, plan)
    np.testing.assert_allclose(rates, [[100, 100], [50, 100], [0, 100]])
    assert valid.all()
    missing_month, valid = bootstrap_draws(toy.iloc[:1], plan)
    assert valid.tolist() == [True, True, False]
    assert np.isnan(missing_month[2]).all()
    actual_checked = 0
    first_check = None
    if actual_sessions is not None:
        assert actual_sessions.prior20_median_range_pts.iloc[:20].isna().all()
        for i in range(20, len(actual_sessions)):
            want = float(np.median(actual_sessions.range_pts.iloc[i-20:i].to_numpy()))
            row = actual_sessions.iloc[i]
            assert row.prior20_median_range_pts == want
            assert row.reference_first_date == actual_sessions.date.iloc[i-20]
            assert row.reference_last_date == actual_sessions.date.iloc[i-1] < row.date
            actual_checked += 1
        first_check = actual_sessions[actual_sessions.date >= "2024-01-01"].iloc[0]
        assert first_check.reference_last_date < "2024-01-01"
        assert first_check.reference_session_count == 20
    return {"first_20_sessions_unavailable": True, "current_and_future_sentinel_invariant": True,
            "past_change_can_affect_later_feature": True, "exact_time_boundaries": True,
            "exact_relative_boundaries": True, "paired_bootstrap_weights": True,
            "zero_event_months_retained": True, "direct_prior_20_medians_checked": actual_checked,
            "chronological_split_carries_history": True if first_check is not None else None}


if __name__ == "__main__":
    print(run_focused_checks())
