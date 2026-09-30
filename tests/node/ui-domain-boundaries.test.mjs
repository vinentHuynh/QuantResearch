import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  latestRunsByConfiguration,
  runConfigurationKey,
} from "../../src/features/runs/model.ts";
import { parseSweep } from "../../src/features/new-run/model.ts";

const root = new URL("../../", import.meta.url);

function filesUnder(directory, extensions) {
  const result = [];
  const visit = (path) => {
    for (const entry of readdirSync(path, { withFileTypes: true })) {
      const child = join(path, entry.name);
      if (entry.isDirectory()) visit(child);
      else if (extensions.some((extension) => entry.name.endsWith(extension))) {
        result.push(child);
      }
    }
  };
  visit(fileURLToPath(new URL(directory, root)));
  return result;
}

test("server and scripts do not import frontend source modules", () => {
  const files = [
    ...filesUnder("server/", [".ts"]),
    ...filesUnder("scripts/", [".mjs"]),
  ];
  const offenders = files.filter((file) =>
    /(?:\.\.\/)+src\//.test(readFileSync(file, "utf8")),
  );
  assert.deepEqual(offenders, []);
});

test("shared TypeScript has no dependency on the React application", () => {
  const offenders = filesUnder("shared/ts/", [".ts"]).filter((file) =>
    /(?:\.\.\/)+src\//.test(readFileSync(file, "utf8")),
  );
  assert.deepEqual(offenders, []);
});

test("new-run sweep parsing remains strict", () => {
  assert.deepEqual(parseSweep('{"lookback":[10,20]}'), {
    lookback: [10, 20],
  });
  assert.equal(parseSweep("[]"), null);
  assert.equal(parseSweep("not json"), null);
});

test("run grouping keeps the newest valid record per configuration", () => {
  const makeRun = (id, end, created_at, status = "Succeeded", metrics = {}) => ({
    id,
    status,
    created_at,
    input: {
      configuration_id: "stable-config",
      end,
      strategy: { id: "demo", name: "Demo" },
      dataset: { symbol: "NQ" },
      timeframe: "1h",
      session: "new-york-rth",
      parameters: {},
    },
    result: metrics === null ? {} : { metrics },
  });
  const older = makeRun("older", "2025-12-31", "2026-01-01T00:00:00Z");
  const newer = makeRun("newer", "2026-06-30", "2026-07-01T00:00:00Z");
  const corrupt = makeRun(
    "corrupt",
    "2026-09-01",
    "2026-09-02T00:00:00Z",
    "Succeeded",
    null,
  );
  assert.equal(runConfigurationKey(older), "stable-config");
  assert.deepEqual(latestRunsByConfiguration([older, corrupt, newer]), [newer]);
});
