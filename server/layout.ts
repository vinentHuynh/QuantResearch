import { readFileSync } from "node:fs";
import { isAbsolute, relative, resolve, sep, win32 } from "node:path";

export const LAYOUT_SCHEMA_VERSION = 1;
export const PROTOCOL_VERSION = 2;

type JsonObject = Record<string, unknown>;

export type WorkbenchLayout = {
  schemaVersion: number;
  protocolVersion: number;
  workspaceRoot: string;
  configPath: string;
  stateRoot: string;
  artifactsRoot: string;
  evidenceRoot: string;
  contractsRoot: string;
  sourceRoots: readonly string[];
  sourceAliases: Readonly<Record<string, readonly string[]>>;
  discoveryPaths: Readonly<Record<string, readonly string[]>>;
};

export type LayoutEnvironment = Partial<Pick<
  NodeJS.ProcessEnv,
  "WORKBENCH_HOME" | "WORKBENCH_ARTIFACTS"
>>;

const object = (value: unknown, label: string): JsonObject => {
  if (value === null || typeof value !== "object" || Array.isArray(value))
    throw new Error(`${label} must be an object`);
  return value as JsonObject;
};

const version = (value: unknown, expected: number, label: string) => {
  if (!Number.isInteger(value) || value !== expected)
    throw new Error(`${label} must be ${expected}`);
  return value as number;
};

const relativePath = (value: unknown, label: string) => {
  if (typeof value !== "string" || value.length === 0)
    throw new Error(`${label} must be a nonempty string`);
  if (
    value.includes("\\") ||
    value.startsWith("/") ||
    win32.isAbsolute(value) ||
    /^[A-Za-z]:/.test(value)
  )
    throw new Error(
      `${label} must be repository-relative with forward slashes`,
    );
  if (
    value !== "." &&
    value.split("/").some((part) => part === "" || part === "." || part === "..")
  )
    throw new Error(
      `${label} must be a normalized repository-relative path`,
    );
  return value;
};

const repoPath = (root: string, value: unknown, label: string) => {
  const result = resolve(root, relativePath(value, label));
  const fromRoot = relative(root, result);
  if (fromRoot === ".." || fromRoot.startsWith(`..${sep}`) || isAbsolute(fromRoot))
    throw new Error(`${label} escapes the workspace`);
  return result;
};

const pathList = (root: string, value: unknown, label: string) => {
  if (!Array.isArray(value) || value.length === 0)
    throw new Error(`${label} must be a nonempty array`);
  const paths = value.map((item, index) =>
    repoPath(root, item, `${label}[${index}]`),
  );
  if (new Set(paths).size !== paths.length)
    throw new Error(`${label} must not contain duplicates`);
  return Object.freeze(paths);
};

const sourceAliases = (value: unknown) => {
  const aliases = object(value, "source_aliases");
  const result: Record<string, readonly string[]> = {};
  for (const [sourceId, rawPaths] of Object.entries(aliases)) {
    if (!/^(?:python|pine):[A-Za-z0-9_.-]+$/.test(sourceId))
      throw new Error(`Invalid source alias id: ${sourceId}`);
    if (!Array.isArray(rawPaths) || rawPaths.length === 0)
      throw new Error(`source_aliases.${sourceId} must be a nonempty array`);
    const paths = rawPaths.map((path, index) =>
      relativePath(path, `source_aliases.${sourceId}[${index}]`),
    );
    if (new Set(paths).size !== paths.length)
      throw new Error(`source_aliases.${sourceId} must not contain duplicates`);
    result[sourceId] = Object.freeze(paths);
  }
  return Object.freeze(result);
};

const override = (root: string, value: string | undefined, fallback: string) =>
  value ? resolve(root, value) : fallback;

export function loadWorkbenchLayout(
  workspaceRoot = resolve(import.meta.dirname, ".."),
  environment: LayoutEnvironment = process.env,
): WorkbenchLayout {
  const root = resolve(workspaceRoot);
  const configPath = resolve(root, "config/workbench-layout.json");
  let payload: JsonObject;
  try {
    payload = object(JSON.parse(readFileSync(configPath, "utf8")), "layout");
  } catch (error) {
    throw new Error(`Unable to read ${configPath}: ${String(error)}`);
  }

  const schemaVersion = version(
    payload.schema_version,
    LAYOUT_SCHEMA_VERSION,
    "schema_version",
  );
  const protocolVersion = version(
    payload.protocol_version,
    PROTOCOL_VERSION,
    "protocol_version",
  );
  const paths = object(payload.paths, "paths");
  for (const name of ["state", "artifacts", "evidence", "contracts"])
    if (!(name in paths)) throw new Error(`paths is missing: ${name}`);

  const stateDefault = repoPath(root, paths.state, "paths.state");
  const artifactsDefault = repoPath(root, paths.artifacts, "paths.artifacts");
  const evidenceRoot = repoPath(root, paths.evidence, "paths.evidence");
  const contractsRoot = repoPath(root, paths.contracts, "paths.contracts");
  const sourceRoots = pathList(root, payload.source_roots, "source_roots");
  const aliases = sourceAliases(payload.source_aliases);

  const discovery = object(payload.discovery_paths, "discovery_paths");
  const discoveryPaths: Record<string, readonly string[]> = {};
  for (const name of ["strategy_adapters", "python_library", "pine_library"]) {
    if (!(name in discovery))
      throw new Error(`discovery_paths is missing: ${name}`);
    discoveryPaths[name] = pathList(
      root,
      discovery[name],
      `discovery_paths.${name}`,
    );
  }

  return Object.freeze({
    schemaVersion,
    protocolVersion,
    workspaceRoot: root,
    configPath,
    stateRoot: override(root, environment.WORKBENCH_HOME, stateDefault),
    artifactsRoot: override(
      root,
      environment.WORKBENCH_ARTIFACTS,
      artifactsDefault,
    ),
    evidenceRoot,
    contractsRoot,
    sourceRoots,
    sourceAliases: aliases,
    discoveryPaths: Object.freeze(discoveryPaths),
  });
}
