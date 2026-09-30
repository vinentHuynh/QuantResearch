import assert from "node:assert/strict";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { mkdtempSync } from "node:fs";

import { loadWorkbenchLayout } from "../server/layout.ts";

const root = resolve(import.meta.dirname, "..");
const layout = loadWorkbenchLayout(root, {});
assert.equal(layout.schemaVersion, 1);
assert.equal(layout.protocolVersion, 2);
assert.equal(layout.stateRoot, join(root, "data", "workbench"));
assert.equal(layout.artifactsRoot, join(root, "artifacts"));
assert.equal(layout.evidenceRoot, join(root, "evidence"));
assert(layout.sourceRoots.includes(join(root, "strategies")));
assert(layout.sourceRoots.includes(join(root, "research")));
assert(layout.sourceRoots.includes(join(root, "tools")));

const overridden = loadWorkbenchLayout(root, {
  WORKBENCH_HOME: "tmp/layout-state",
  WORKBENCH_ARTIFACTS: "tmp/layout-artifacts",
});
assert.equal(overridden.stateRoot, join(root, "tmp", "layout-state"));
assert.equal(overridden.artifactsRoot, join(root, "tmp", "layout-artifacts"));

const temporary = mkdtempSync(join(tmpdir(), "workbench-layout-"));
try {
  mkdirSync(join(temporary, "config"));
  const payload = JSON.parse(
    readFileSync(join(root, "config", "workbench-layout.json"), "utf8"),
  );
  payload.discovery_paths.strategy_adapters = ["../strategies"];
  writeFileSync(
    join(temporary, "config", "workbench-layout.json"),
    JSON.stringify(payload),
  );
  assert.throws(
    () => loadWorkbenchLayout(temporary, {}),
    /repository-relative/,
  );
} finally {
  rmSync(temporary, { recursive: true, force: true });
}

console.log("Workbench layout TypeScript checks passed.");
