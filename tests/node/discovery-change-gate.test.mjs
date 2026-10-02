import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import { createDiscoveryChangeGate } from "../../server/features/scripts/discoveryChangeGate.ts";

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), "discovery-change-gate-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const layout = {
    schema_version: 1,
    protocol_version: 2,
    paths: {
      state: "data/workbench",
      artifacts: "artifacts",
      evidence: "evidence",
      contracts: "shared/contracts",
    },
    source_roots: ["workbench"],
    source_aliases: {},
    discovery_paths: {
      strategy_adapters: ["strategies"],
      python_library: [".", "scripts"],
      pine_library: [".", "pine"],
    },
  };
  const put = (name, value) => {
    const filename = join(root, ...name.split("/"));
    mkdirSync(join(filename, ".."), { recursive: true });
    writeFileSync(filename, value);
  };
  const saveLayout = () => put("config/workbench-layout.json", JSON.stringify(layout));
  saveLayout();
  return { root, layout, put, saveLayout, gate: createDiscoveryChangeGate(root) };
}

test("discovery gate tracks additions, changes, and removals in configured source folders", (t) => {
  const { root, put, gate } = fixture(t);
  const initial = gate.snapshot();
  assert.equal(gate.needsScan(initial), true);
  gate.markScanned(initial);
  assert.equal(gate.needsScan(gate.snapshot()), false);

  put("strategies/alpha.py", "VALUE = 1\n");
  const added = gate.snapshot();
  assert.equal(gate.needsScan(added), true);
  gate.markScanned(added);

  put("strategies/alpha.py", "VALUE = 12345\n");
  const modified = gate.snapshot();
  assert.equal(gate.needsScan(modified), true);
  gate.markScanned(modified);

  put("strategies/alpha.py", "VALUE = 54321\n");
  utimesSync(join(root, "strategies/alpha.py"), new Date("2030-01-01"), new Date("2030-01-01"));
  const sameSizeEdit = gate.snapshot();
  assert.equal(gate.needsScan(sameSizeEdit), true);
  gate.markScanned(sameSizeEdit);

  rmSync(join(root, "strategies/alpha.py"));
  assert.equal(gate.needsScan(gate.snapshot()), true);
});

test("discovery gate mirrors top-level and recursive Python and Pine matching", (t) => {
  const { root, put, gate } = fixture(t);
  const original = gate.snapshot();
  gate.markScanned(original);

  put("strategies/nested/ignored.py", "VALUE = 1\n");
  put("research/ignored.py", "VALUE = 1\n");
  put("research/ignored.pine", "indicator('Ignored')\n");
  put("scripts/note.txt", "Not a source\n");
  assert.equal(gate.needsScan(gate.snapshot()), false);

  for (const name of [
    "root.py",
    "root.pine",
    "strategies/adapter.py",
    "scripts/nested/library.py",
    "pine/nested/indicator.pine",
  ]) {
    put(name, "source\n");
    const changed = gate.snapshot();
    assert.equal(gate.needsScan(changed), true, name);
    gate.markScanned(changed);
    assert.equal(gate.needsScan(gate.snapshot()), false, name);
  }

  // A new source under a missing configured folder also changes the snapshot.
  rmSync(join(root, "scripts"), { recursive: true });
  gate.markScanned(gate.snapshot());
  put("scripts/new/added.py", "source\n");
  assert.equal(gate.needsScan(gate.snapshot()), true);
});

test("discovery gate follows layout changes and retains edits made during a scan", (t) => {
  const { layout, put, saveLayout, gate } = fixture(t);
  const beforeScan = gate.snapshot();
  put("scripts/late.py", "VALUE = 1\n");
  gate.markScanned(beforeScan);
  assert.equal(gate.needsScan(gate.snapshot()), true);

  layout.discovery_paths.python_library = [".", "research"];
  saveLayout();
  const changedLayout = gate.snapshot();
  gate.markScanned(changedLayout);
  put("research/nested/new.py", "VALUE = 2\n");
  assert.equal(gate.needsScan(gate.snapshot()), true);
});

test("discovery gate observes Python execution dependencies outside library folders", (t) => {
  const { put, gate } = fixture(t);
  gate.markScanned(gate.snapshot());
  put("workbench/worker.py", "# runtime changed\n");
  const runtimeChanged = gate.snapshot();
  assert.equal(gate.needsScan(runtimeChanged), true);
  gate.markScanned(runtimeChanged);
  put("workbench/__pycache__/ignored.py", "# cache only\n");
  put("workbench/worker.ts", "// TypeScript edit\n");
  assert.equal(gate.needsScan(gate.snapshot()), false);
});
