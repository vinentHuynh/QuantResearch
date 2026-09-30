import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join, relative, resolve, sep } from "node:path";
import type { Dataset } from "../../core/contracts.ts";
import { logicalReference } from "../../core/validation.ts";

export type DatasetImportJob = {
  status: string;
  log: string;
  error?: string;
};

type Dependencies = {
  root: string;
  state: string;
  python: string;
  cleanEnvironment: () => NodeJS.ProcessEnv;
  put: (kind: string, id: string, body: unknown) => void;
  raw: (kind: string, id: string) => string | undefined;
};

type DatasetCatalog = {
  datasets: Dataset[];
  errors: unknown[];
};

export function createDatasets(dependencies: Dependencies) {
  const { root, state, python, cleanEnvironment, put, raw } = dependencies;
  let importJob: DatasetImportJob = { status: "Idle", log: "" };

  function register() {
    const catalogFile = join(state, "datasets/catalog.json");
    if (!existsSync(catalogFile)) return;
    const imported = JSON.parse(
      readFileSync(catalogFile, "utf8"),
    ) as DatasetCatalog;
    for (const dataset of imported.datasets)
      // A catalog refresh must never rewrite an existing protocol-v1 row.
      if (raw("dataset", dataset.id) === undefined)
        put("dataset", dataset.id, dataset);
    if (imported.errors.length)
      importJob.error = JSON.stringify(imported.errors);
  }

  function file(dataset: Dataset): string {
    if (dataset.schema_version === 2)
      logicalReference(dataset.path, "Protocol-v2 dataset path");
    const absolute =
      dataset.schema_version === 2
        ? resolve(state, dataset.path)
        : resolve(dataset.path);
    const path = relative(state, absolute);
    if (
      !path ||
      path === ".." ||
      path.startsWith(`..${sep}`) ||
      resolve(state, path) !== absolute
    )
      throw new Error("Registered dataset path is outside WORKBENCH_HOME");
    return absolute;
  }

  function protocol(dataset: Dataset): Dataset {
    const absolute = file(dataset);
    const path = relative(state, absolute);
    return {
      ...dataset,
      schema_version: 2,
      path: path.split(sep).join("/"),
      ...(typeof dataset.archive === "string"
        ? { archive: dataset.archive.split("\\").join("/") }
        : {}),
    };
  }

  function legacy(dataset: Dataset): Dataset {
    const value = { ...dataset };
    delete value.schema_version;
    return { ...value, path: file(dataset) };
  }

  function importLocal(): DatasetImportJob {
    if (importJob.status === "Running") return importJob;
    importJob = {
      status: "Running",
      log: "Scanning local data ZIP archives…\n",
    };
    const child = spawn(
      python,
      ["-m", "workbench.datasets", root, join(state, "datasets")],
      { cwd: root, env: cleanEnvironment(), windowsHide: true },
    );
    child.stdout.on("data", (chunk) => {
      importJob.log = (importJob.log + chunk).slice(-30000);
    });
    child.stderr.on("data", (chunk) => {
      importJob.log = (importJob.log + chunk).slice(-30000);
    });
    child.on("error", (error) => {
      importJob.error = error.message;
    });
    child.on("close", (code) => {
      register();
      importJob.status =
        code === 0 && !importJob.error ? "Succeeded" : "Failed";
    });
    return importJob;
  }

  register();

  return {
    file,
    importLocal,
    job: () => importJob,
    legacy,
    protocol,
    register,
  };
}
