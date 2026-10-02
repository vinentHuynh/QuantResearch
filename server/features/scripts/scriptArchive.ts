import { createHash, randomUUID } from "node:crypto";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { isAbsolute, join, relative, resolve, sep } from "node:path";
import type { Strategy } from "../../core/contracts.ts";

const SCHEMA_VERSION = 1;
const ID_PATTERN = /^[a-z][a-z0-9-]{1,80}$/;
const HASH_PATTERN = /^[a-f0-9]{64}$/;

export type ArchivedScript = {
  id: string;
  name: string;
  archived_at: string;
  original_path: string;
  archive_path: string;
  file_hash: string;
  strategy: Strategy;
};

type Manifest = {
  schema_version: typeof SCHEMA_VERSION;
  scripts: ArchivedScript[];
};

type ArchiveOptions = {
  /** Dependency injection for testing a failed manifest write and rollback. */
  manifestWriter?: (path: string, contents: string) => void;
  now?: () => string;
};

function atomicManifestWrite(path: string, contents: string) {
  const temporary = `${path}.${randomUUID()}.tmp`;
  try {
    writeFileSync(temporary, contents, { encoding: "utf8", flag: "wx" });
    renameSync(temporary, path);
  } finally {
    if (existsSync(temporary)) rmSync(temporary);
  }
}

function sourcePath(file: string) {
  if (typeof file !== "string" || !file.startsWith("strategies/") || file.includes("\\"))
    throw new Error("Only discovered top-level strategy adapters can be archived");
  const name = file.slice("strategies/".length);
  if (!name || name.includes("/") || !name.endsWith(".py") || name.startsWith("_"))
    throw new Error("Only discovered top-level strategy adapters can be archived");
  return name;
}

function archivePath(id: string, file: string) {
  if (!ID_PATTERN.test(id)) throw new Error("Invalid strategy id");
  return `strategies_archive/${id}/${sourcePath(file)}`;
}

function regularFile(path: string, label: string) {
  if (!existsSync(path) || !lstatSync(path).isFile())
    throw new Error(`${label} is missing or is not a regular file`);
}

function safeDirectory(path: string, label: string) {
  if (existsSync(path) && !lstatSync(path).isDirectory())
    throw new Error(`${label} is not a regular directory`);
}

function checksum(path: string) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function checkedDependency(root: string, file: string) {
  if (typeof file !== "string" || file.includes("\\") || isAbsolute(file))
    throw new Error("Invalid archived source dependency");
  const path = resolve(root, file);
  const fromRoot = relative(root, path);
  if (fromRoot === ".." || fromRoot.startsWith(`..${sep}`) || isAbsolute(fromRoot))
    throw new Error("Archived source dependency escapes the workspace");
  return path;
}

function validateEntry(value: unknown): ArchivedScript {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Invalid archived script manifest entry");
  const entry = value as ArchivedScript;
  if (
    typeof entry.id !== "string" ||
    !ID_PATTERN.test(entry.id) ||
    typeof entry.name !== "string" ||
    !entry.name ||
    typeof entry.archived_at !== "string" ||
    !Number.isFinite(Date.parse(entry.archived_at)) ||
    typeof entry.original_path !== "string" ||
    typeof entry.archive_path !== "string" ||
    typeof entry.file_hash !== "string" ||
    !HASH_PATTERN.test(entry.file_hash) ||
    !entry.strategy ||
    typeof entry.strategy !== "object" ||
    Array.isArray(entry.strategy) ||
    entry.strategy.id !== entry.id ||
    entry.strategy.file !== entry.original_path ||
    entry.strategy.file_hash !== entry.file_hash ||
    entry.archive_path !== archivePath(entry.id, entry.original_path)
  ) throw new Error("Invalid archived script manifest entry");
  return entry;
}

export function createScriptArchive(rootPath: string, options: ArchiveOptions = {}) {
  const root = realpathSync(resolve(rootPath));
  const activeDirectory = join(root, "strategies");
  const archiveDirectory = join(root, "strategies_archive");
  const manifestPath = join(archiveDirectory, "manifest.json");
  const writeManifest = options.manifestWriter || atomicManifestWrite;
  const now = options.now || (() => new Date().toISOString());

  function load(): Manifest {
    safeDirectory(archiveDirectory, "Strategy archive");
    if (!existsSync(manifestPath)) return { schema_version: SCHEMA_VERSION, scripts: [] };
    regularFile(manifestPath, "Strategy archive manifest");
    let parsed: unknown;
    try {
      parsed = JSON.parse(readFileSync(manifestPath, "utf8"));
    } catch (error) {
      throw new Error(`Unable to read strategy archive manifest: ${String(error)}`);
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
      throw new Error("Invalid strategy archive manifest");
    const manifest = parsed as Manifest;
    if (manifest.schema_version !== SCHEMA_VERSION || !Array.isArray(manifest.scripts))
      throw new Error("Invalid strategy archive manifest");
    const scripts = manifest.scripts.map(validateEntry);
    if (new Set(scripts.map((entry) => entry.id)).size !== scripts.length ||
        new Set(scripts.map((entry) => entry.original_path)).size !== scripts.length)
      throw new Error("Duplicate strategy archive manifest entry");
    for (const entry of scripts) {
      const archived = checkedArchivedPath(entry);
      if (existsSync(archived)) continue;
      // The manifest is written before an archive move. If the process stopped
      // during that move (or a restore stopped before manifest removal), keep
      // the manifest authoritative and finish moving its unchanged source.
      const original = checkedActivePath(entry.original_path);
      regularFile(original, "Interrupted archived strategy source");
      if (checksum(original) !== entry.file_hash)
        throw new Error(`Interrupted archived strategy source changed: ${entry.original_path}`);
      mkdirSync(join(archiveDirectory, entry.id), { recursive: true });
      renameSync(original, archived);
    }
    return { schema_version: SCHEMA_VERSION, scripts };
  }

  function save(manifest: Manifest) {
    mkdirSync(archiveDirectory, { recursive: true });
    safeDirectory(archiveDirectory, "Strategy archive");
    writeManifest(manifestPath, JSON.stringify(manifest, null, 2) + "\n");
  }

  function checkedActivePath(file: string) {
    sourcePath(file);
    safeDirectory(activeDirectory, "Strategy folder");
    if (realpathSync(activeDirectory) !== activeDirectory)
      throw new Error("Strategy folder cannot be a symbolic link");
    return join(root, file);
  }

  function checkedArchivedPath(entry: ArchivedScript) {
    const folder = join(archiveDirectory, entry.id);
    safeDirectory(archiveDirectory, "Strategy archive");
    safeDirectory(folder, "Archived strategy folder");
    if (existsSync(archiveDirectory) && realpathSync(archiveDirectory) !== archiveDirectory)
      throw new Error("Strategy archive cannot be a symbolic link");
    if (existsSync(folder) && realpathSync(folder) !== folder)
      throw new Error("Archived strategy folder cannot be a symbolic link");
    return join(root, entry.archive_path);
  }

  function rollback(from: string, to: string, original: unknown): never {
    try {
      renameSync(from, to);
    } catch (rollbackError) {
      throw new AggregateError([original, rollbackError], "Archive manifest write and file rollback both failed");
    }
    throw original;
  }

  return {
    list(): ArchivedScript[] {
      return load().scripts;
    },
    archivedIds(): Set<string> {
      return new Set(load().scripts.map((entry) => entry.id));
    },
    archive(strategy: Strategy, activeStrategies: Strategy[]): ArchivedScript {
      if (!ID_PATTERN.test(strategy.id) || !HASH_PATTERN.test(strategy.file_hash))
        throw new Error("Invalid discovered strategy metadata");
      const manifest = load();
      if (manifest.scripts.some((entry) => entry.id === strategy.id))
        throw new Error("Strategy is already archived");
      if (!activeStrategies.some((candidate) => candidate.id === strategy.id && candidate.file === strategy.file))
        throw new Error("Strategy is not in the active catalog");
      const dependents = activeStrategies.filter((candidate) =>
        candidate.id !== strategy.id && candidate.source_files?.includes(strategy.file),
      );
      if (dependents.length)
        throw new Error(`Strategy is required by active scripts: ${dependents.map((item) => item.name).join(", ")}`);
      const original = checkedActivePath(strategy.file);
      regularFile(original, "Strategy source");
      if (checksum(original) !== strategy.file_hash)
        throw new Error("Strategy source changed since discovery; scan scripts and retry");
      const entry: ArchivedScript = {
        id: strategy.id,
        name: strategy.name,
        archived_at: now(),
        original_path: strategy.file,
        archive_path: archivePath(strategy.id, strategy.file),
        file_hash: strategy.file_hash,
        strategy: structuredClone(strategy),
      };
      const archived = checkedArchivedPath(entry);
      if (existsSync(archived)) throw new Error("Archived strategy destination already exists");
      const folder = join(archiveDirectory, entry.id);
      mkdirSync(folder, { recursive: true });
      safeDirectory(folder, "Archived strategy folder");
      // Record intent first so a process crash cannot strand an unlisted file.
      save({ schema_version: SCHEMA_VERSION, scripts: [...manifest.scripts, entry] });
      try {
        renameSync(original, archived);
      } catch (error) {
        try {
          save(manifest);
        } catch (rollbackError) {
          throw new AggregateError([error, rollbackError], "Archive move and manifest rollback both failed");
        }
        throw error;
      }
      return entry;
    },
    restore(id: string, validate?: (entry: ArchivedScript) => void): ArchivedScript {
      if (!ID_PATTERN.test(id)) throw new Error("Invalid strategy id");
      const manifest = load();
      const entry = manifest.scripts.find((item) => item.id === id);
      if (!entry) throw new Error("Archived strategy not found");
      const archived = checkedArchivedPath(entry);
      regularFile(archived, "Archived strategy source");
      if (checksum(archived) !== entry.file_hash)
        throw new Error("Archived strategy source changed; restore requires the original archived version");
      for (const dependency of entry.strategy.source_files || []) {
        if (dependency === entry.original_path) continue;
        regularFile(checkedDependency(root, dependency), `Source dependency ${dependency}`);
      }
      const original = checkedActivePath(entry.original_path);
      if (existsSync(original)) throw new Error("Active strategy destination already exists");
      renameSync(archived, original);
      try {
        validate?.(entry);
        save({ schema_version: SCHEMA_VERSION, scripts: manifest.scripts.filter((item) => item.id !== id) });
      } catch (error) {
        rollback(original, archived, error);
      }
      return entry;
    },
  };
}
