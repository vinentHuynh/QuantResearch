import assert from "node:assert/strict";
import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { test } from "node:test";
import { createHash } from "node:crypto";

import { createEvidenceRegistry } from "../../server/infra/evidenceRegistry.ts";

test("the NQ API resolves checksum-verified evidence outside reports", () => {
  const root = resolve(import.meta.dirname, "../..");
  const folder = mkdtempSync(join(tmpdir(), "workbench-nq-evidence-"));
  try {
    const evidence = join(folder, "evidence");
    const manifests = join(evidence, "manifests");
    const artifacts = join(folder, "artifacts");
    const relative = "research/nq-monthly-2026-09-29/campaign.json";
    const bytes = readFileSync(
      join(root, "evidence", "campaigns", "nq-monthly-2026-09-29", "campaign.json"),
    );
    mkdirSync(manifests, { recursive: true });
    mkdirSync(join(artifacts, "research", "nq-monthly-2026-09-29"), {
      recursive: true,
    });
    writeFileSync(
      join(evidence, "registry.json"),
      JSON.stringify({
        schema_version: 1,
        campaigns: [
          {
            campaign_id: "nq-monthly-2026-09-29",
            manifest: "manifests/nq-monthly-2026-09-29.json",
          },
        ],
      }),
    );
    writeFileSync(
      join(manifests, "nq-monthly-2026-09-29.json"),
      JSON.stringify({
        schema_version: 2,
        campaign_id: "nq-monthly-2026-09-29",
        created_at: "2026-09-29T00:00:00Z",
        protocol_path: relative,
        summary_paths: [relative],
        consumers: ["workbench-nq-monthly-api"],
        artifacts: [
          {
            role: "protocol",
            relative_path: relative,
            bytes: bytes.length,
            sha256: createHash("sha256").update(bytes).digest("hex"),
          },
        ],
      }),
    );
    writeFileSync(join(artifacts, ...relative.split("/")), bytes);
    const campaign = createEvidenceRegistry(evidence, artifacts).campaign(
      "nq-monthly-2026-09-29",
      "workbench-nq-monthly-api",
    );
    assert.match(campaign.file("protocol"), /artifacts[\\/]research/);
    assert.equal(campaign.file("protocol").includes(join(root, "reports")), false);
  } finally {
    rmSync(folder, { recursive: true, force: true });
  }
});

test("missing and corrupt artifact stores fail explicitly", () => {
  const folder = mkdtempSync(join(tmpdir(), "workbench-evidence-"));
  try {
    const evidence = join(folder, "evidence");
    const manifests = join(evidence, "manifests");
    const artifacts = join(folder, "artifacts");
    mkdirSync(manifests, { recursive: true });
    writeFileSync(
      join(evidence, "registry.json"),
      JSON.stringify({
        schema_version: 1,
        campaigns: [{ campaign_id: "fixture", manifest: "manifests/fixture.json" }],
      }),
    );
    const bytes = Buffer.from("expected");
    writeFileSync(
      join(manifests, "fixture.json"),
      JSON.stringify({
        schema_version: 2,
        campaign_id: "fixture",
        created_at: "2026-09-29T00:00:00Z",
        protocol_path: "research/fixture/data.json",
        summary_paths: ["research/fixture/data.json"],
        consumers: ["test"],
        artifacts: [
          {
            role: "data",
            relative_path: "research/fixture/data.json",
            bytes: bytes.length,
            sha256: createHash("sha256").update(bytes).digest("hex"),
          },
        ],
      }),
    );
    const registry = createEvidenceRegistry(evidence, artifacts);
    assert.throws(() => registry.campaign("fixture", "test"), /store is missing/);
    mkdirSync(join(artifacts, "research", "fixture"), { recursive: true });
    writeFileSync(join(artifacts, "research", "fixture", "data.json"), "corrupt!");
    assert.throws(() => registry.campaign("fixture", "test"), /checksum mismatch/);
  } finally {
    rmSync(folder, { recursive: true, force: true });
  }
});

test("protocol-v2 manifests require the complete closed contract", () => {
  const folder = mkdtempSync(join(tmpdir(), "workbench-evidence-contract-"));
  try {
    const evidence = join(folder, "evidence");
    const manifests = join(evidence, "manifests");
    const artifacts = join(folder, "artifacts");
    mkdirSync(manifests, { recursive: true });
    mkdirSync(join(artifacts, "research", "fixture"), { recursive: true });
    writeFileSync(
      join(evidence, "registry.json"),
      JSON.stringify({
        schema_version: 1,
        campaigns: [{ campaign_id: "fixture", manifest: "manifests/fixture.json" }],
      }),
    );
    writeFileSync(
      join(manifests, "fixture.json"),
      JSON.stringify({
        schema_version: 2,
        campaign_id: "fixture",
        consumers: ["test"],
        artifacts: [],
      }),
    );
    assert.throws(
      () => createEvidenceRegistry(evidence, artifacts).campaign("fixture", "test"),
      /Invalid protocol-v2 evidence manifest/,
    );
  } finally {
    rmSync(folder, { recursive: true, force: true });
  }
});
