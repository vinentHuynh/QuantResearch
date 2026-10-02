import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { createCollective, isArchivedCollectiveItem } from "../../server/features/portfolio/collective.ts";

const item = (key, source = "Workbench", source_run_ids = []) => ({
  id: key,
  key,
  source,
  source_run_ids,
  series_file: "00000000000000000000-0000000000000000.json",
});

test("portfolio archive matching uses exact script identity and preserved run lineage", () => {
  const archived = new Set(["snd", "short-term-reversal"]);
  const runs = new Map([["run-1", "short-term-reversal"]]);
  assert.equal(isArchivedCollectiveItem(item("short-term-reversal__ES__1m"), archived, runs), true);
  assert.equal(isArchivedCollectiveItem(item("MNQ__original_multi_tf", "SND"), archived, runs), true);
  assert.equal(isArchivedCollectiveItem(item("legacy-key", "Workbench", ["run-1"]), archived, runs), true);
  assert.equal(isArchivedCollectiveItem(item("short-term-reversal-minute__ES__1m"), archived, runs), false);
});

test("archived portfolio histories are absent from catalog and cannot be loaded", (t) => {
  const root = mkdtempSync(join(tmpdir(), "archived-collective-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const state = join(root, "state");
  mkdirSync(join(state, "collective"), { recursive: true });
  writeFileSync(join(state, "collective", "index.json"), JSON.stringify({
    version: 1,
    generated_at: "2026-09-30T00:00:00Z",
    items: [item("snd__NQ__1m")],
    errors: [],
    definitions: { working: "", feasible: "", pnl: "" },
  }));
  const collective = createCollective(root, state, "unused", () => "", undefined, () => new Set(["snd"]));
  assert.deepEqual(collective.catalog().items, []);
  assert.throws(() => collective.series(["snd__NQ__1m"]), /Unknown strategy configuration/);
});

test("legacy portfolio histories are hidden when only the verified ledger links the archived script", (t) => {
  const root = mkdtempSync(join(tmpdir(), "archived-legacy-collective-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const state = join(root, "state");
  const folder = join(state, "collective");
  mkdirSync(folder, { recursive: true });
  const id = "a".repeat(20);
  const bytes = Buffer.from(JSON.stringify({ trades: [{ source_run: "run-1" }], daily: [] }));
  const checksum = createHash("sha256").update(bytes).digest("hex");
  const series_file = `${id}-${checksum.slice(0, 16)}.json`;
  writeFileSync(join(folder, series_file), bytes);
  writeFileSync(join(folder, "index.json"), JSON.stringify({
    version: 1,
    generated_at: "2026-09-30T00:00:00Z",
    items: [{ ...item("legacy-book"), id, series_file, checksum, source_run_ids: undefined }],
    errors: [],
    definitions: { working: "", feasible: "", pnl: "" },
  }));
  const runs = [{ id: "run-1", input: { strategy: { id: "snd" } } }];
  const collective = createCollective(root, state, "unused", () => "", () => ({ strategies: [], runs, evaluations: [] }), () => new Set(["snd"]));
  assert.deepEqual(collective.catalog().items, []);
  assert.throws(() => collective.series([id]), /Unknown strategy configuration/);
});
