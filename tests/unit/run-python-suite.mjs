import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

const suites = Object.freeze({
  core: [
    "test_workbench.py",
    "test_warmup.py",
    "test_workbench_layout.py",
    "test_protocol_v2_metadata.py",
    "test_dataset_protocol.py",
    "test_evidence_registry.py",
    "test_sqlite_record_consumers.py",
    "test_collective_import.py",
    "test_event_study.py",
    "test_pattern_recognition.py",
    "test_research.py",
    "test_strategy_library.py",
  ],
  engine: [
    "test_accounting.py",
    "test_strategy_engine.py",
    "test_parity.py",
    "test_minute_sessions.py",
    "test_event_limit_entry.py",
  ],
  adapters: [
    "test_aw_model_nq.py",
    "test_market_intraday_momentum.py",
    "test_pine_ports.py",
    "test_short_term_reversal.py",
    "test_short_term_reversal_minute.py",
    "test_rsi2_reversion_corrected.py",
    "test_snd_adapter.py",
    "test_tsmom_orb_calendar.py",
    "test_tsmom_orb_next_open.py",
    "test_wyckoff_nq_adapter.py",
    "test_ninjatrader_orb_port.py",
    "test_ninjatrader_overnight_ports.py",
  ],
  research: [
    "test_aw_revision_analyzer.py",
    "test_htf_wick_phases.py",
    "test_prepare_htf_wick_inputs.py",
    "test_transcript_supply_demand.py",
    "test_snd_body_retest.py",
    "test_snd_combination_fast.py",
    "test_snd_combination_fast_io.py",
    "test_snd_combination_grid.py",
    "test_snd_combination_reference.py",
    "test_snd_combination_risk.py",
    "test_snd_combination_validation_audit.py",
    "test_snd_combinations_analysis.py",
    "test_snd_combinations_audit.py",
    "test_snd_combinations_runner.py",
    "test_snd_entry_research.py",
    "test_snd_forward.py",
    "test_snd_fresh_retest.py",
    "test_snd_risk_research.py",
    "test_snd_zone_exit.py",
    "test_snd_zone_quality.py",
    "test_snd_zone_quality_report.py",
  ],
});

const selected = process.argv[2] ?? "all";
const names = selected === "all" ? Object.keys(suites) : [selected];
if (names.some((name) => !(name in suites))) {
  console.error(
    `Unknown Python unit suite: ${selected}. Choose all, ${Object.keys(suites).join(", ")}.`,
  );
  process.exit(2);
}

const python =
  process.env.WORKBENCH_PYTHON ||
  resolve(
    process.platform === "win32"
      ? ".venv/Scripts/python.exe"
      : ".venv/bin/python",
  );
if (!existsSync(python) && !process.env.WORKBENCH_PYTHON) {
  console.error(
    `Workbench Python was not found at ${python}. Set WORKBENCH_PYTHON to the existing interpreter.`,
  );
  process.exit(2);
}

for (const name of names) {
  console.log(`\nPython ${name} unit suite`);
  for (const pattern of suites[name]) {
    const result = spawnSync(
      python,
      ["-m", "unittest", "discover", "-s", "tests", "-p", pattern, "-v"],
      {
        cwd: resolve("."),
        env: {
          ...process.env,
          PYTHONDONTWRITEBYTECODE: "1",
          PYTHONHASHSEED: "0",
        },
        stdio: "inherit",
        windowsHide: true,
      },
    );
    if (result.error) {
      console.error(result.error.message);
      process.exit(1);
    }
    if (result.status !== 0) process.exit(result.status ?? 1);
  }
}

console.log(`\nPython ${selected} unit suite passed.`);
