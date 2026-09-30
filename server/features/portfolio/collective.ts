import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import type { CollectiveCatalog } from "../../../shared/ts/portfolio.ts";

export function createCollective(
  root: string,
  state: string,
  python: string,
  evidenceStatus: () => string = () => "",
) {
  const folder = join(state, "collective");
  let refresh = { running: false, error: "", started_at: "", completed_at: "" };
  function catalog(): CollectiveCatalog {
    if (!existsSync(join(folder, "index.json")))
      throw new Error(
        "No collective catalog yet. Refresh evidence to import completed research.",
      );
    return JSON.parse(readFileSync(join(folder, "index.json"), "utf8"));
  }
  return {
    catalog: () => ({
      ...catalog(),
      refresh,
      evidence_error: evidenceStatus(),
    }),
    status: () => ({ ...refresh, evidence_error: evidenceStatus() }),
    series: (ids: unknown) => {
      if (
        !Array.isArray(ids) ||
        ids.length > 100 ||
        ids.some((id) => typeof id !== "string") ||
        new Set(ids).size !== ids.length
      )
        throw new Error("Choose up to 100 unique strategy configurations.");
      const index = catalog();
      return ids.map((id) => {
        const item = index.items.find((i) => i.id === id);
        if (
          !item ||
          !/^[a-f0-9]{20}-[a-f0-9]{16}\.json$/.test(item.series_file)
        )
          throw new Error(
            "Unknown strategy configuration. Refresh the catalog.",
          );
        const bytes = readFileSync(join(folder, item.series_file));
        if (createHash("sha256").update(bytes).digest("hex") !== item.checksum)
          throw new Error(
            "Saved portfolio history changed. Refresh evidence before combining it.",
          );
        return JSON.parse(bytes.toString("utf8"));
      });
    },
    rebuild: () => {
      if (refresh.running) return refresh;
      const evidenceError = evidenceStatus();
      if (evidenceError) {
        const now = new Date().toISOString();
        refresh = {
          running: false,
          error: evidenceError,
          started_at: now,
          completed_at: now,
        };
        return refresh;
      }
      refresh = {
        running: true,
        error: "",
        started_at: new Date().toISOString(),
        completed_at: "",
      };
      const child = spawn(python, [join(root, "scripts/build-collective.py")], {
        cwd: root,
        windowsHide: true,
        env: { ...process.env, WORKBENCH_HOME: state },
      });
      let output = "";
      child.stdout.on("data", (data) => {
        output = (output + data).slice(-12000);
      });
      child.stderr.on("data", (data) => {
        output = (output + data).slice(-12000);
      });
      child.on("error", (error) => {
        refresh = { ...refresh, running: false, error: error.message };
      });
      child.on("close", (code) => {
        refresh = {
          ...refresh,
          running: false,
          error: code === 0 ? "" : output || "Evidence import failed",
          completed_at: new Date().toISOString(),
        };
      });
      return refresh;
    },
  };
}
