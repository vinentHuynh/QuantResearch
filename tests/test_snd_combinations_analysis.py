"""Causal censoring, deterministic training selection, and family uncertainty."""
import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


analysis = load("snd_combinations_analysis", "scripts/analyze-snd-combinations.py")


def open_trade(side=1, entry=100., future_exit=110.):
    return pd.DataFrame([dict(entry_time="2024-12-30T10:00:00Z", side=side,
        quantity=side, entry=entry, stop=entry - side * 2, target=entry + side * 10,
        risk=2., risk_cash=4., exit_time="2025-01-02T10:00:00Z", exit=future_exit,
        exit_reason="target", gross_pnl=20., cost=3., net_pnl=17., net_r=4.25,
        future_peak=999., execution_minutes=1)])


def censor(frame, raw_close=103., **options):
    return analysis.causal_training_trades(
        frame, "2024-01-01", "2025-01-01", last_source_open="2024-12-31T23:59:00Z",
        last_source_close=raw_close, point_value=2., tick_size=.25, fee=1.,
        slippage_ticks=2, **options)


class CausalPrefixTests(unittest.TestCase):
    def test_future_outcomes_cannot_affect_training_liquidation(self):
        original = open_trade()
        changed = original.copy()
        changed.loc[0, ["exit", "gross_pnl", "net_pnl", "net_r", "cost", "future_peak"]] = [-999., -1e6, 1e6, 1e7, 1e8, -500.]
        first, second = censor(original), censor(changed)
        pd.testing.assert_frame_equal(first, second)
        self.assertNotIn("future_peak", first.columns)
        self.assertEqual(first.iloc[0].exit_reason, "training-cutoff")
        self.assertEqual(first.iloc[0].exit, 103.)
        self.assertEqual(first.iloc[0].net_pnl, 2.)
        self.assertEqual(first.iloc[0].net_r, .5)

    def test_short_and_price_slippage_recompute_only_known_costs(self):
        for side in (1, -1):
            raw_close = 100 + side * 3
            for mode in ("cash", "price"):
                entry = 100 + side * .5 if mode == "price" else 100.
                result = censor(open_trade(side, entry), raw_close, slippage_model=mode).iloc[0]
                self.assertEqual(result.net_pnl, 2.)
                self.assertEqual(result.cost, 2. if mode == "price" else 4.)
                self.assertEqual(result.exit, raw_close - side * .5 if mode == "price" else raw_close)

    def test_incomplete_source_or_overlapping_position_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "More than one"):
            censor(pd.concat([open_trade(), open_trade()], ignore_index=True))
        with self.assertRaisesRegex(ValueError, "complete"):
            analysis.causal_training_trades(open_trade(), "2024-01-01", "2025-01-01",
                last_source_open="2025-01-01T00:00:00Z", last_source_close=103.,
                point_value=2., tick_size=.25, fee=1.)

    def test_ordinary_boundary_exit_is_censored_but_forced_close_is_known(self):
        ordinary = open_trade()
        ordinary["exit_time"] = "2025-01-01T00:00:00Z"
        self.assertEqual(censor(ordinary).iloc[0].exit_reason, "training-cutoff")
        forced = ordinary.copy()
        forced["exit_reason"] = "end-of-test"
        self.assertEqual(censor(forced).iloc[0].exit_reason, "end-of-test")

    def test_censored_result_matches_reference_engine_prefix(self):
        # A real stop-entry fixture stays open across the requested cutoff.
        fixture = load("quality_fixture_for_prefix", "tests/test_snd_zone_quality.py")
        rows = fixture.HISTORY + fixture.BASE + [fixture.FILL,
                (104.5, 106, 104, 105.5), (105.5, 107, 105, 106.5)]
        frame = fixture.source_frame(rows, minute=True)
        prepared = fixture.prepare(frame, execution_minutes=1)
        cutoff = frame.index[(len(fixture.HISTORY) + len(fixture.BASE) + 1) * 5]
        full = fixture.run(prepared, rr=10.)
        prefix = fixture.run(prepared, rr=10., end=cutoff)
        self.assertEqual(len(full["trades"]), 1)
        self.assertGreater(pd.Timestamp(full["trades"].iloc[0].exit_time), cutoff)
        raw = frame.loc[frame.index + pd.Timedelta(minutes=1) <= cutoff]
        rebuilt = analysis.causal_training_trades(full["trades"], frame.index[0], cutoff,
            last_source_open=raw.index[-1], last_source_close=raw.iloc[-1].close,
            point_value=2., tick_size=.25, fee=1., slippage_ticks=1)
        fields = ["entry_time", "entry", "stop", "target", "risk", "risk_cash",
                  "exit_time", "exit", "gross_pnl", "cost", "net_pnl", "net_r"]
        pd.testing.assert_frame_equal(rebuilt[fields], prefix["trades"][fields], check_dtype=False)
        self.assertAlmostEqual(rebuilt.net_pnl.sum(), prefix["equity"].equity.iloc[-1] - 100000.)

    def test_roll_discovered_after_gap_does_not_leak_its_backdated_exit_reason(self):
        fixture = load("quality_fixture_for_roll_prefix", "tests/test_snd_zone_quality.py")
        from strategies import _snd_combination_reference as reference
        frame = fixture.source_frame(fixture.HISTORY + fixture.BASE + [fixture.FILL, (104.5, 106, 104, 105.5)], minute=True)
        frame["instrument_id"] = 10
        next_contract = fixture.source_frame([(205, 207, 204, 206)], minute=True)
        next_contract.index = pd.date_range(frame.index[-1] + pd.Timedelta(minutes=61), periods=5, freq="1min")
        next_contract["instrument_id"] = 20
        full_raw = pd.concat([frame, next_contract])
        full_data = fixture.prepare(full_raw, model=reference, execution_minutes=1)
        full = fixture.run(full_data, model=reference, rr=10.)
        self.assertEqual(full["trades"].iloc[0].exit_reason, "contract-roll")
        self.assertEqual(full["trades"].iloc[0].exit_time, frame.index[-1] + pd.Timedelta(minutes=1))
        for cutoff, expected_reason in ((frame.index[-1] + pd.Timedelta(minutes=31), "training-cutoff"),
                                        (next_contract.index[0] + pd.Timedelta(minutes=1), "contract-roll")):
            raw = full_raw.loc[full_raw.index + pd.Timedelta(minutes=1) <= cutoff]
            prefix_data = fixture.prepare(raw, model=reference, execution_minutes=1)
            prefix = fixture.run(prefix_data, model=reference, rr=10., end=cutoff)
            rebuilt = analysis.causal_training_trades(full["trades"], frame.index[0], cutoff,
                last_source_open=raw.index[-1], last_source_close=raw.iloc[-1].close,
                point_value=2., tick_size=.25, fee=1., slippage_ticks=1)
            self.assertEqual(rebuilt.iloc[0].exit_reason, expected_reason)
            rebuilt.loc[rebuilt.exit_reason == "training-cutoff", "exit_reason"] = "end-of-test"
            pd.testing.assert_frame_equal(rebuilt[prefix["trades"].columns], prefix["trades"], check_dtype=False, check_exact=True)


class TrainingSelectionTests(unittest.TestCase):
    def test_trade_weighted_cluster_se_and_empty_weeks(self):
        self.assertAlmostEqual(analysis.weekly_cluster_se([3, -1, 0, 0], [3, 1, 0, 0]), np.sqrt(6) / 4)
        self.assertIsNone(analysis.weekly_cluster_se([3, 0], [3, 0]))
        self.assertIsNone(analysis.weekly_cluster_se([0, 0], [0, 0]))

    def test_partial_master_week_does_not_leak_earlier_trades(self):
        frame = pd.DataFrame({"exit_time": pd.to_datetime(["2024-12-31", "2025-01-02"], utc=True),
                              "exit_reason": ["target", "target"], "net_r": [100., 1.]})
        result = analysis.calendar_week_arrays(frame, "2025-01-01", "2025-01-06",
            master_start="2024-12-30", master_end="2025-01-13")
        np.testing.assert_array_equal(result["sum_r"], [1., 0.])
        np.testing.assert_array_equal(result["counts"], [1., 0.])

    def test_selection_gates_tie_breaking_and_no_positive_lcb_requirement(self):
        base = dict(trades=200, recent_trades=50, mean_net_r=.1,
                    double_cost_closed_net=1., weekly_cluster_se=1., enabled_filters=2)
        rows = [dict(base, config_id="b"), dict(base, config_id="a"),
                dict(base, config_id="simpler", enabled_filters=1),
                dict(base, config_id="invalid", trades=199, mean_net_r=100.)]
        result = analysis.select_candidate(rows)
        self.assertEqual(result["selected_id"], "simpler")
        self.assertLess(result["selected"]["selection_score"], 0.)
        self.assertEqual(analysis.select_candidate(rows[:2])["selected_id"], "a")
        self.assertEqual(analysis.select_candidate(list(reversed(rows)))["selected_id"], "simpler")
        rejected = analysis.select_candidate([dict(base, config_id="bad", double_cost_closed_net=0.)])
        self.assertIsNone(rejected["selected_id"])
        self.assertEqual(rejected["decision"], "cash")

    def test_training_metrics_refuse_future_exit(self):
        with self.assertRaisesRegex(ValueError, "out-of-period"):
            analysis.training_metrics(open_trade(), "2024-01-01", "2025-01-01")
        result = analysis.training_metrics(censor(open_trade()), "2024-01-01", "2025-01-01")
        self.assertEqual(result["trades"], 1)
        self.assertEqual(result["recent_trades"], 1)
        self.assertEqual(result["double_cost_closed_net"], -2.)


class FamilyInferenceTests(unittest.TestCase):
    def test_chunked_nested_joint_family_matches_hand_calculated_draws(self):
        sums = np.column_stack([np.zeros(8), np.arange(8), np.ones(8), np.zeros(8)])
        counts = np.ones((8, 4)); counts[:, 3] = 0
        later_sums, later_counts = sums.copy(), counts.copy()
        later_sums[:4], later_counts[:4] = 0, 0
        periods = {"all": (sums, counts), "later": (later_sums, later_counts)}
        comparisons = [dict(id="all", period="all", candidate=1, baseline=0),
                       dict(id="later", period="later", candidate=1, baseline=0),
                       dict(id="degenerate", period="all", candidate=2, baseline=0),
                       dict(id="empty", period="all", candidate=3, baseline=0)]
        weights = np.array([[1, 1, 1, 1, 1, 1, 1, 1], [2, 2, 0, 0, 1, 1, 1, 1],
                            [1, 1, 1, 1, 2, 2, 0, 0], [0, 0, 2, 2, 0, 0, 2, 2]], dtype=float)
        small = analysis.family_bootstrap(periods, comparisons, replicates=4, weights=weights, chunk_size=1)
        large = analysis.family_bootstrap(periods, comparisons, replicates=4, weights=weights, chunk_size=100)
        self.assertEqual(small["records"], large["records"])
        self.assertEqual(small["critical_value"], large["critical_value"])
        first, later, degenerate, empty = small["records"]
        self.assertEqual(first["estimate"], 3.5)
        self.assertEqual(later["estimate"], 5.5)
        self.assertAlmostEqual(first["standard_error"], np.sqrt(.5))
        self.assertAlmostEqual(later["standard_error"], np.sqrt(2 / 3))
        self.assertFalse(degenerate["estimable"])
        self.assertIsNone(degenerate["ci_low"])
        self.assertIsNone(empty["estimate"])
        json.dumps(small, allow_nan=False)

    def test_all_empty_family_is_unavailable_not_a_failure(self):
        result = analysis.family_bootstrap({"all": (np.zeros((8, 2)), np.zeros((8, 2)))},
            [dict(id="empty", period="all", candidate=1, baseline=0)], replicates=100)
        self.assertFalse(result["calibrated"])
        self.assertIsNone(result["records"][0]["ci_low"])
        json.dumps(result, allow_nan=False)

    def test_uncalibrated_family_reports_zero_estimable_intervals(self):
        counts = np.zeros((12, 6))
        sums = np.zeros((12, 6))
        for col in range(6):
            counts[2 * col:2 * col + 2, col] = 1.
            sums[2 * col:2 * col + 2, col] = [1., 3.]
        weights = np.ones((100, 12))
        weights[::2, 1::2] = 2.
        for col in range(6):
            weights[col, 2 * col:2 * col + 2] = 0.
        result = analysis.family_bootstrap({"all": (sums, counts)},
            [dict(id=str(col), period="all", candidate=col, baseline=None) for col in range(6)],
            weights=weights, replicates=100)
        self.assertFalse(result["calibrated"])
        self.assertEqual(result["jointly_usable"], 94)
        self.assertEqual(result["individually_usable_comparisons"], 6)
        self.assertEqual(result["estimable_comparisons"], 0)
        self.assertTrue(all(not row["estimable"] and row["ci_low"] is None for row in result["records"]))

    def test_shared_weights_have_full_calendar_size(self):
        first = analysis.moving_block_weights(13, 20)
        second = analysis.moving_block_weights(13, 20)
        np.testing.assert_array_equal(first, second)
        np.testing.assert_array_equal(first.sum(axis=1), np.full(20, 13.))


class FoldGateTests(unittest.TestCase):
    def test_missing_stress_or_missing_fold_never_counts_as_a_pass(self):
        folds = [dict(name="2024", trades=100, net_r_sum=10., closed_net=100., double_cost_closed_net=50.),
                 dict(name="2025", trades=100, net_r_sum=10., closed_net=100., double_cost_closed_net=50.)]
        stress = [dict(name="price_2ticks", status="succeeded", mean_net_r=.05, closed_net=20.)]
        ok = analysis.fold_gates(folds, ci_low=.01, stress_results=stress,
                                 min_trades_by_fold={"2024": 50, "2025": 50})
        self.assertTrue(ok["passed"])
        self.assertEqual(ok["evidence_label"], "retrospective_candidate")
        self.assertFalse(analysis.fold_gates(folds, ci_low=.01)["passed"])
        self.assertFalse(analysis.fold_gates(folds, ci_low=.01, stress_results=stress,
                         min_trades_by_fold={"2026": 25})["passed"])
        self.assertFalse(analysis.fold_gates(folds, ci_low=None, stress_results=stress)["passed"])

    def test_exact_protocol_does_not_invent_per_fold_r_or_double_cost_gates(self):
        protocol = dict(folds=[{"id": "2024"}, {"id": "2025"}, {"id": "2026_jan_jul"}],
            validation_scenarios=[{"id": name} for name in
                ("cash_base", "cash_double", "price_1", "price_2_double_fee")],
            validation_neighbors=[{}] * 6)
        # First fold has negative mean R but positive fixed-contract cash. The
        # protocol requires pooled R positive and cash positive in every fold.
        base = [dict(fold_id=name, trades=count, net_r_sum=r, closed_net=10., status="succeeded")
                for name, count, r in (("2024", 80, -1.), ("2025", 80, 5.), ("2026_jan_jul", 40, 5.))]
        stressed = [dict(row, closed_net=(-2. if row["fold_id"] == "2024" else 5.)) for row in base]
        scenarios = {name["id"]: base if name["id"] == "cash_base" else stressed
                     for name in protocol["validation_scenarios"]}
        neighbors = {f"neighbor-{i}": base for i in range(5)}
        neighbors["neighbor-5"] = [dict(row, closed_net=-10.) for row in base]
        result = analysis.protocol_validation_gates(protocol, scenarios,
            conditional_mean_r_ci_low=.01, neighbor_folds=neighbors)
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["positive_neighbor_paths"]), 5)
        self.assertIn("conditional", result["note"].lower())
        scenarios.pop("price_1")
        self.assertFalse(analysis.protocol_validation_gates(protocol, scenarios,
            conditional_mean_r_ci_low=.01, neighbor_folds=neighbors)["passed"])


def campaign_fixture(output, *, complete=True, later_value=10.):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    configs = [dict(config_id=f"c{i:05d}", parameter_hash=f"hash-{i}", parameters={
        "max_zone_width_atr": None, "min_departure_atr": 1. if i else None,
        "min_departure_rvol": None, "max_touch_age_hours": None}) for i in range(2)]
    analysis.save_json(output / "configurations.json", configs)
    p = dict(configurations_file="configurations.json", configurations_checksum=analysis.checksum(output / "configurations.json"),
        expected_configurations=2, expected_market_cases=2, markets=["A"],
        datasets=[dict(symbol="A", start="2024-01-01", end="2025-03-01")],
        folds=[dict(id="2025", training_start="2024-01-01", cutoff="2025-01-01", test_end="2025-03-01")])
    analysis.save_json(output / "protocol.json", p)
    source_path = "scripts/analyze-snd-combinations.py"
    frozen = output / "source" / source_path
    frozen.parent.mkdir(parents=True)
    shutil.copy2(ROOT / source_path, frozen)
    files = [dict(path=source_path, checksum=analysis.checksum(frozen))]
    identity = dict(protocol_checksum=analysis.checksum(output / "protocol.json"),
        configurations_checksum=p["configurations_checksum"],
        source_hash=hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest())
    analysis.save_json(output / "source-manifest.json", dict(identity, files=files))
    attempt = output / "sweep/A/shard-0000/attempt-000"
    active = configs if complete else configs[:1]
    ids = [row["config_id"] for row in active]
    analysis.save_json(attempt / "input.json", dict(identity, symbol="A", config_ids=ids))
    analysis.save_json(attempt / "status.json", {"status": "succeeded"})
    analysis.save_json(attempt / "cases.json", [dict(config_id=row["config_id"], status="succeeded",
        diagnostics={}, summary=dict(trades=200, net_pnl=later_value)) for row in active])
    pd.DataFrame({"config_id": np.repeat(ids, 200)}).to_parquet(attempt / "trades.parquet", index=False)
    pd.DataFrame(dict(config_id=ids, equity=[100000 + later_value] * len(ids))).to_parquet(attempt / "equity-daily.parquet", index=False)
    pd.DataFrame(dict(config_id=ids, period=["later"] * len(ids), net_pnl=[later_value] * len(ids))).to_parquet(attempt / "periods.parquet", index=False)
    training = [dict(config_id=row["config_id"], fold_id="2025", trades=200, recent_trades=200,
        mean_net_r=.1 + i * .1, double_cost_closed_net=20., weekly_cluster_se=.01,
        enabled_filters=i, cutoff="2025-01-01", start="2024-01-01") for i, row in enumerate(active)]
    pd.DataFrame(training).to_parquet(attempt / "training.parquet", index=False)
    first, end = pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2025-03-01", tz="UTC")
    n = int(((end - pd.Timedelta(nanoseconds=1)) - first).days // 7) + 1
    rows = []
    for i, config in enumerate(active):
        for period in ("all", "later"):
            for j, week in enumerate(pd.date_range(first, periods=n, freq="7D")):
                scored = period == "all" or week + pd.Timedelta(days=7) > pd.Timestamp("2025-01-01", tz="UTC")
                rows.append(dict(config_id=config["config_id"], period=period, week=week,
                    net_r_sum=(np.sin(j) + i * .1) if scored else 0., trades=1 if scored else 0))
    pd.DataFrame(rows).to_parquet(attempt / "weekly.parquet", index=False)
    analysis.save_json(attempt / "result.json", dict(identity, status="succeeded", config_ids=ids,
        artifacts=[dict(name=name, checksum=analysis.checksum(attempt / name)) for name in analysis.SHARD_ARTIFACTS]))
    return attempt


class ShardAnalysisCLITests(unittest.TestCase):
    def test_executing_and_retained_analysis_source_must_match_freeze(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            campaign_fixture(output)
            campaign = analysis.verify_campaign(output)
            changed = output / "different-analysis.py"
            changed.write_text("# Different helper implementation\n", encoding="utf-8")
            with patch.object(analysis, "__file__", str(changed)):
                with self.assertRaisesRegex(ValueError, "analysis source preserved"):
                    analysis.verify_campaign(output)
            with self.assertRaisesRegex(ValueError, "Retained output script identity"):
                analysis._verify_output_script_identity(campaign, {"analysis_source_checksum": "changed"},
                    "scripts/analyze-snd-combinations.py", "analysis_source_checksum")

    def test_cli_verifies_full_grid_selects_training_and_writes_complete_family(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            campaign_fixture(output)
            result = subprocess.run([sys.executable, str(ROOT / "scripts/analyze-snd-combinations.py"),
                "--output", str(output), "--selection", "--family", "--report-partial", "--replicates", "2000"],
                capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            selected = analysis.read_json(output / "selection.json")
            self.assertEqual(selected["selections"][0]["selected_id"], "c00001")
            self.assertEqual(selected["audit_counts"]["accounted"], 2)
            family = analysis.read_json(output / "family-bootstrap-r2000.json")
            self.assertEqual(family["family_size"], 8)
            self.assertEqual(family["minimum_empirical_tail_step"], .0005)
            self.assertTrue((output / "GRID-PROGRESS.md").is_file())

    def test_partial_grid_and_modified_artifact_block_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            attempt = campaign_fixture(output, complete=False)
            campaign = analysis.verify_campaign(output, require_complete=False)
            self.assertEqual(campaign["coverage"]["missing"], 1)
            with self.assertRaisesRegex(ValueError, "Grid incomplete"):
                analysis.verify_campaign(output)
            with self.assertRaisesRegex(ValueError, "Complete verified"):
                analysis.write_selections(campaign)
            with (attempt / "training.parquet").open("ab") as stream:
                stream.write(b"tampered")
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                analysis.verify_campaign(output, require_complete=False)
            self.assertFalse((output / "selection.json").exists())

    def test_later_results_cannot_change_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / "a", Path(directory) / "b"
            campaign_fixture(a, later_value=1e9)
            campaign_fixture(b, later_value=-1e9)
            first = analysis.write_selections(analysis.verify_campaign(a))
            second = analysis.write_selections(analysis.verify_campaign(b))
            self.assertEqual(first, second)
            # Deterministic repeat reuses the same preserved selection.
            self.assertEqual(first, analysis.write_selections(analysis.verify_campaign(a)))

    def test_prior_failed_attempt_remains_in_audit_counts_after_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            attempt = campaign_fixture(output)
            retry = attempt.with_name("attempt-001")
            attempt.rename(retry)
            analysis.save_json(attempt / "result.json", dict(status="failed", config_ids=["c00000", "c00001"]))
            analysis.save_json(attempt / "cases.json", [dict(config_id="c00000", status="succeeded"),
                dict(config_id="c00001", status="failed")])
            campaign = analysis.verify_campaign(output)
            self.assertTrue(campaign["coverage"]["complete"])
            selected = analysis.write_selections(campaign)
            self.assertEqual(selected["audit_counts"]["historical_failed_attempts"], 1)
            self.assertEqual(selected["audit_counts"]["historical_failed_case_attempts"], 1)


def validation_fixture(output):
    output = Path(output)
    attempt = campaign_fixture(output)
    protocol = analysis.read_json(output / "protocol.json")
    protocol.update(capital=100000., grid={"max_zone_width_atr": [None, .5]},
        validation_scenarios=[dict(id=name, slippage_model="cash" if name.startswith("cash") else "price",
            fee_multiple=2 if name in ("cash_double", "price_2_double_fee") else 1,
            slippage_ticks=2 if name in ("cash_double", "price_2_double_fee") else 1)
            for name in ("cash_base", "cash_double", "price_1", "price_2_double_fee")],
        validation_neighbors=[{"rr": .75}, {"rr": 1.25}, {"rr": 2.}, {"rr": 3.}, {"pivot_len": 1}, {"pivot_len": 3}])
    analysis.save_json(output / "protocol.json", protocol)
    manifest = analysis.read_json(output / "source-manifest.json")
    manifest["protocol_checksum"] = analysis.checksum(output / "protocol.json")
    analysis.save_json(output / "source-manifest.json", manifest)
    for name in ("input.json", "result.json"):
        row = analysis.read_json(attempt / name)
        row["protocol_checksum"] = manifest["protocol_checksum"]
        analysis.save_json(attempt / name, row)
    campaign = analysis.verify_campaign(output)
    selection = analysis.write_selections(campaign)
    analysis.write_family_analysis(campaign, replicates=2000)
    identity = {key: manifest[key] for key in ("protocol_checksum", "source_hash", "configurations_checksum")}
    identity["selection_checksum"] = analysis.checksum(output / "selection.json")
    configs = {row["config_id"]: row for row in campaign["configs"]}
    planned, results = [], []
    choice = selection["selections"][0]
    roles = ["selected", "reference", "risk-50", "risk-100", "risk-200"] + [f"neighbor-{i}" for i in range(6)]
    for role in roles:
        scenarios = protocol["validation_scenarios"][:1] if role.startswith("neighbor-") else protocol["validation_scenarios"]
        for scenario in scenarios:
            cid = "c00000" if role == "reference" else choice["selected_id"]
            case = dict(symbol="A", fold_id="2025", role=role, scenario=scenario["id"], config_id=cid,
                decision="selected", start="2025-01-01", end="2025-03-01", parameters=configs[cid]["parameters"],
                fee_multiple=scenario["fee_multiple"], slippage_ticks=scenario["slippage_ticks"])
            planned.append(case)
            times = pd.date_range("2025-01-02", periods=200, freq="6h", tz="UTC")
            # All fixed-contract economics pass. One adverse risk100 path fails.
            level = -.2 if role == "risk-100" and scenario["id"] == "price_2_double_fee" else (.1 if role == "reference" else .2)
            r = level + .01 * np.sin(np.arange(200) / 9)
            net = r * 100
            t = pd.DataFrame(dict(entry_time=times - pd.Timedelta(minutes=1), exit_time=times,
                exit_reason="target", execution_minutes=1, net_r=r, risk_cash=100., cost=2.,
                gross_pnl=net + 2., net_pnl=net))
            values = 100000. + np.cumsum(net)
            equity = pd.DataFrame(dict(timestamp=times + pd.Timedelta(minutes=1), equity=values,
                balance=values, unrealized_pnl=0., net_pnl=net, contracts=0))
            path = np.r_[100000., values]
            summary = dict(trades=200, closed_net=float(net.sum()), net_r_sum=float(r.sum()),
                max_drawdown=float((np.maximum.accumulate(path) - path).max()), max_trade_loss=max(0., float(-net.min())))
            folder = output / "validation/A/2025" / role / scenario["id"]
            analysis.save_json(folder / "input.json", dict(case, **identity))
            analysis.save_json(folder / "status.json", {"status": "succeeded"})
            t.to_parquet(folder / "trades.parquet", index=False)
            equity.to_parquet(folder / "equity.parquet", index=False)
            record = dict(case, **identity, status="succeeded", summary=summary, diagnostics={},
                artifacts=[dict(name=name, checksum=analysis.checksum(folder / name)) for name in ("trades.parquet", "equity.parquet")])
            analysis.save_json(folder / "result.json", record)
            results.append(record)
    analysis.save_json(output / "validation-plan.json", dict(identity, expected_cases=len(planned), cases=planned))
    analysis.save_json(output / "validation-results.json", dict(identity, status="succeeded", expected_cases=len(planned), completed_cases=len(results), cases=results))
    detail = dict(status="passed", symbol="A", records=[dict(kind=kind, status="passed") for kind in
        ("frozen_full_history_control", "crossed_reference", "causal_prefix")])
    detail_path = output / "preflight/A-fixed-id.json"
    analysis.save_json(detail_path, detail)
    analysis.save_json(output / "preflight.json", dict(status="passed", protocol_checksum=identity["protocol_checksum"],
        source_files={row["path"]: row["checksum"] for row in manifest["files"]},
        markets=[dict(symbol="A", status="passed", checks=3, artifact="preflight/A-fixed-id.json", artifact_checksum=analysis.checksum(detail_path))]))
    analysis.save_json(output / "independent-sweep-audit.json", dict(identity, status="passed", complete_sweep=True,
        audited_cases=2, exhaustive_accounting_trades=400, raw_sampled_trades=6))
    analysis.save_json(output / "independent-validation-audit.json", dict(identity, status="passed", complete_validation=True,
        audited_cases=len(planned), expected_cases=len(planned), total_checks=100, failures=[]))
    supplemental = dict(protocol_checksum=identity["protocol_checksum"], configurations_checksum=identity["configurations_checksum"],
        source_files={row["path"]: row["checksum"] for row in manifest["files"]}, status="passed")
    analysis.save_json(output / "synthetic-grid-parity.json", dict(supplemental, complete_grid=True,
        declared_configurations=2, completed_configurations=2, expected_comparisons=4, completed_comparisons=4,
        passed_comparisons=4, nonzero_configurations=2, failures=[]))
    analysis.save_json(output / "risk-reference-parity.json", dict(supplemental, source_unchanged=True,
        records=[dict(symbol="A", variant=variant, status="passed", trades=1, equity_rows=2)
                 for variant in ("wick_baseline", "body_strict")]))
    factors = [dict(symbol="A", period=period, rule="max_zone_width_atr", baseline_level=None, changed_level=.5,
        minimum_trades_each=n, median_delta_mean_net_r=.01, both_meet_trade_minimum=2)
        for period in ("all", "later") for n in (1, 100)]
    pd.DataFrame(factors).to_csv(output / "factor-effects.csv", index=False)
    analysis.save_json(output / "factor-effects.json", dict(identity, status="succeeded", rows=len(factors), records=factors,
        artifact_checksum=analysis.checksum(output / "factor-effects.csv")))
    return campaign


class ValidationReportTests(unittest.TestCase):
    def test_stitched_drawdown_carries_losses_across_flat_start_folds(self):
        first = pd.DataFrame(dict(timestamp=pd.to_datetime(["2024-06-01", "2025-01-01"], utc=True), equity=[90., 95.], contracts=0))
        second = pd.DataFrame(dict(timestamp=pd.to_datetime(["2025-06-01", "2026-01-01"], utc=True), equity=[90., 100.], contracts=0))
        result = analysis.stitched_equity_metrics([
            dict(start="2024-01-01", end="2025-01-01", equity=first),
            dict(start="2025-01-01", end="2026-01-01", equity=second)], capital=100.)
        self.assertEqual(result["max_drawdown"], 15.)
        self.assertEqual(result["net_pnl"], -5.)

    def test_complete_report_separates_frozen_gates_from_failed_adverse_risk(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign = validation_fixture(directory)
            summary = analysis.write_validation_report(campaign)
            self.assertTrue(summary["audits_passed"])
            self.assertEqual(summary["validation_cases"], 26)
            self.assertEqual(summary["historical_candidates"], 1)
            saved = analysis.read_json(Path(directory) / "validation-analysis.json")
            market = saved["validation"]["markets"][0]
            self.assertTrue(market["economic_gates"]["passed"])
            self.assertTrue(market["historical_candidate"])
            self.assertTrue(market["implementation_checks_passed"])
            self.assertFalse(market["risk100_adverse_cash_pass"])
            report = (Path(directory) / "REPORT.md").read_text(encoding="utf-8")
            self.assertIn("1/1 full-history controls", report)
            self.assertNotIn("52 full-history controls", report)
            self.assertIn("not selection-adjusted", report)
            self.assertIn("factor-effects.csv", report)
            self.assertIn("an economic pass can still fail that sizing stress", report)
            self.assertEqual(report, (Path(directory) / "RESULTS.md").read_text(encoding="utf-8"))

    def test_missing_audit_or_changed_validation_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign = validation_fixture(directory)
            audit = Path(directory) / "independent-validation-audit.json"
            audit.rename(audit.with_suffix(".waiting"))
            with self.assertRaises(FileNotFoundError):
                analysis.write_validation_report(campaign)
            audit.with_suffix(".waiting").rename(audit)
            target = Path(directory) / "validation/A/2025/selected/cash_base/trades.parquet"
            with target.open("ab") as stream:
                stream.write(b"tamper")
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                analysis.read_validation_cases(campaign)


if __name__ == "__main__":
    unittest.main()
