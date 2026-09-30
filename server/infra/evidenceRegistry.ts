import { createHash } from "node:crypto";
import { existsSync, readFileSync, statSync } from "node:fs";
import { isAbsolute, join, relative, resolve, sep } from "node:path";

type RegistryEntry = { campaign_id: string; manifest: string };
type EvidenceArtifact = {
  role: string;
  relative_path: string;
  bytes: number;
  sha256: string;
};
type EvidenceManifest = {
  schema_version: 2;
  campaign_id: string;
  created_at: string;
  protocol_path: string;
  summary_paths: string[];
  consumers: string[];
  artifacts: EvidenceArtifact[];
};

const exactKeys = (value: Record<string, unknown>, expected: readonly string[]) => {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return actual.length === wanted.length && actual.every((key, index) => key === wanted[index]);
};

function validateManifest(
  value: Record<string, unknown>,
  campaignId: string,
  manifestPath: string,
): EvidenceManifest {
  if (
    !exactKeys(value, [
      "schema_version",
      "campaign_id",
      "created_at",
      "protocol_path",
      "summary_paths",
      "artifacts",
      "consumers",
    ]) ||
    value.schema_version !== 2 ||
    value.campaign_id !== campaignId ||
    !/^[a-z0-9][a-z0-9._-]{1,199}$/.test(campaignId) ||
    typeof value.created_at !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value.created_at) ||
    !Number.isFinite(Date.parse(value.created_at))
  )
    throw new Error(`Invalid protocol-v2 evidence manifest: ${manifestPath}`);

  const protocolPath = safeRelative(value.protocol_path, "protocol_path");
  if (
    !Array.isArray(value.summary_paths) ||
    value.summary_paths.length === 0 ||
    value.summary_paths.some((path) => typeof path !== "string")
  )
    throw new Error(`Invalid evidence summary_paths in ${campaignId}`);
  const summaryPaths = value.summary_paths.map((path) =>
    safeRelative(path, "summary_path"),
  );
  if (new Set(summaryPaths).size !== summaryPaths.length)
    throw new Error(`Duplicate evidence summary_path in ${campaignId}`);

  if (
    !Array.isArray(value.consumers) ||
    value.consumers.length === 0 ||
    value.consumers.some(
      (consumer) =>
        typeof consumer !== "string" ||
        consumer.length === 0 ||
        consumer.length > 200,
    ) ||
    new Set(value.consumers).size !== value.consumers.length
  )
    throw new Error(`Invalid evidence consumers in ${campaignId}`);
  if (!Array.isArray(value.artifacts) || value.artifacts.length === 0)
    throw new Error(`Evidence campaign ${campaignId} declares no artifacts`);

  const roles = new Set<string>();
  const paths = new Set<string>();
  const campaignRoot = protocolPath.split("/").slice(0, -1).join("/");
  const artifacts: EvidenceArtifact[] = value.artifacts.map((raw) => {
    if (!raw || typeof raw !== "object" || Array.isArray(raw))
      throw new Error(`Invalid evidence artifact in ${campaignId}`);
    const artifact = raw as Record<string, unknown>;
    const relativePath = safeRelative(artifact.relative_path, "evidence artifact");
    if (
      !exactKeys(artifact, ["role", "relative_path", "bytes", "sha256"]) ||
      typeof artifact.role !== "string" ||
      artifact.role.length === 0 ||
      artifact.role.length > 100 ||
      roles.has(artifact.role) ||
      paths.has(relativePath) ||
      !Number.isSafeInteger(artifact.bytes) ||
      (artifact.bytes as number) < 0 ||
      typeof artifact.sha256 !== "string" ||
      !/^[a-f0-9]{64}$/.test(artifact.sha256) ||
      (campaignRoot && !relativePath.startsWith(`${campaignRoot}/`))
    )
      throw new Error(`Invalid evidence artifact in ${campaignId}`);
    roles.add(artifact.role);
    paths.add(relativePath);
    return {
      role: artifact.role,
      relative_path: relativePath,
      bytes: artifact.bytes as number,
      sha256: artifact.sha256,
    };
  });
  if (!paths.has(protocolPath) || summaryPaths.some((path) => !paths.has(path)))
    throw new Error(
      `Evidence protocol_path and summary_paths must be declared artifacts in ${campaignId}`,
    );
  return {
    schema_version: 2,
    campaign_id: campaignId,
    created_at: value.created_at,
    protocol_path: protocolPath,
    summary_paths: summaryPaths,
    consumers: value.consumers as string[],
    artifacts,
  };
}

function readJson(path: string, label: string): Record<string, unknown> {
  try {
    const value: unknown = JSON.parse(readFileSync(path, "utf8"));
    if (!value || typeof value !== "object" || Array.isArray(value))
      throw new Error("expected a JSON object");
    return value as Record<string, unknown>;
  } catch (error) {
    throw new Error(`Unable to read ${label} ${path}: ${String(error)}`);
  }
}

function safeRelative(value: unknown, label: string) {
  if (
    typeof value !== "string" ||
    !value ||
    value.includes("\\") ||
    value.startsWith("/") ||
    /^[A-Za-z]:/.test(value) ||
    value.split("/").some((part) => !part || part === "." || part === "..")
  )
    throw new Error(`Unsafe ${label}: ${String(value)}`);
  return value;
}

function contained(root: string, path: string, label: string) {
  const target = resolve(root, ...safeRelative(path, label).split("/"));
  const fromRoot = relative(resolve(root), target);
  if (fromRoot === ".." || fromRoot.startsWith(`..${sep}`) || isAbsolute(fromRoot))
    throw new Error(`${label} escapes its configured root`);
  return target;
}

export function createEvidenceRegistry(evidenceRoot: string, artifactsRoot: string) {
  const catalogPath = join(evidenceRoot, "registry.json");

  function manifest(campaignId: string, consumer: string): EvidenceManifest {
    const catalog = readJson(catalogPath, "evidence registry");
    if (catalog.schema_version !== 1 || !Array.isArray(catalog.campaigns))
      throw new Error(`Unsupported evidence registry schema: ${catalogPath}`);
    const entry = (catalog.campaigns as RegistryEntry[]).find(
      (item) => item?.campaign_id === campaignId,
    );
    if (!entry) throw new Error(`Unknown evidence campaign: ${campaignId}`);
    const manifestPath = contained(evidenceRoot, entry.manifest, "evidence manifest");
    const value = readJson(manifestPath, `manifest for ${campaignId}`);
    const declared = validateManifest(value, campaignId, manifestPath);
    if (
      !declared.consumers.includes(consumer)
    )
      throw new Error(
        `Evidence campaign ${campaignId} is not declared for ${consumer}`,
      );
    return declared;
  }

  function campaign(campaignId: string, consumer: string) {
    const declared = manifest(campaignId, consumer);
    if (!existsSync(artifactsRoot) || !statSync(artifactsRoot).isDirectory())
      throw new Error(
        `Artifact store is missing: ${artifactsRoot} (set WORKBENCH_ARTIFACTS)`,
      );
    const roles = new Map<string, string>();
    for (const artifact of declared.artifacts) {
      const path = contained(
        artifactsRoot,
        artifact.relative_path,
        "evidence artifact",
      );
      if (!existsSync(path) || !statSync(path).isFile())
        throw new Error(
          `Declared evidence is missing for ${campaignId}/${artifact.role}: ${path}`,
        );
      const bytes = readFileSync(path);
      if (bytes.length !== artifact.bytes)
        throw new Error(
          `Evidence size mismatch for ${campaignId}/${artifact.role}`,
        );
      const digest = createHash("sha256").update(bytes).digest("hex");
      if (digest !== artifact.sha256)
        throw new Error(
          `Evidence checksum mismatch for ${campaignId}/${artifact.role}`,
        );
      roles.set(artifact.role, path);
    }
    return {
      file(role: string) {
        const path = roles.get(role);
        if (!path)
          throw new Error(
            `Evidence campaign ${campaignId} does not declare role ${role}`,
          );
        return path;
      },
    };
  }

  return { campaign };
}
