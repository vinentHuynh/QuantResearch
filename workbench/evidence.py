"""Checksum-verified access to external Workbench research evidence.

The registry is intentionally small and tracked in Git.  Raw research output
stays below ``WORKBENCH_ARTIFACTS`` (``<repo>/artifacts`` by default), while
the manifests in ``evidence/manifests`` declare the files an application is
allowed to consume.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Dict, Iterable, Optional, Tuple

from .layout import load_layout


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CAMPAIGN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,199}$")
_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


class EvidenceRegistryError(RuntimeError):
    """Raised when declared evidence is unavailable, unsafe, or corrupt."""


@dataclass(frozen=True)
class EvidenceFile:
    role: str
    artifact_path: str
    bytes: int
    sha256: str
    path: Path


@dataclass(frozen=True)
class EvidenceCampaign:
    campaign_id: str
    schema_version: int
    root: Path
    protocol_path: Path
    summary_path: Path
    consumers: Tuple[str, ...]
    files: Tuple[EvidenceFile, ...]
    summary_paths: Tuple[Path, ...] = ()

    def file(self, role: str) -> Path:
        """Return a verified file by its manifest role."""
        for item in self.files:
            if item.role == role:
                return item.path
        raise EvidenceRegistryError(
            f"Evidence campaign {self.campaign_id!r} does not declare role {role!r}"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvidenceRegistryError(f"Missing {label}: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceRegistryError(f"Cannot read {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise EvidenceRegistryError(f"Invalid {label} {path}: expected a JSON object")
    return payload


class EvidenceRegistry:
    """Load tracked manifests and resolve them against the local artifact store."""

    def __init__(
        self,
        repo_root: Path,
        *,
        registry_path: Optional[Path] = None,
        artifacts_root: Optional[Path] = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        layout = load_layout(self.repo_root)
        self.registry_path = Path(
            registry_path or layout.evidence_root / "registry.json"
        ).resolve()
        configured = artifacts_root or layout.artifacts_root
        configured = Path(configured)
        if not configured.is_absolute():
            configured = self.repo_root / configured
        self.artifacts_root = configured.resolve()
        self._entries = self._load_catalog()

    def _load_catalog(self) -> Dict[str, Path]:
        catalog = _load_json(self.registry_path, "evidence registry")
        if catalog.get("schema_version") != 1:
            raise EvidenceRegistryError(
                f"Unsupported evidence registry schema in {self.registry_path}: "
                f"{catalog.get('schema_version')!r}"
            )
        campaigns = catalog.get("campaigns")
        if not isinstance(campaigns, list) or not campaigns:
            raise EvidenceRegistryError(
                f"Invalid evidence registry {self.registry_path}: campaigns must be a non-empty list"
            )
        entries: Dict[str, Path] = {}
        for entry in campaigns:
            if not isinstance(entry, dict):
                raise EvidenceRegistryError("Invalid evidence registry campaign entry")
            campaign_id = entry.get("campaign_id")
            manifest = entry.get("manifest")
            if not isinstance(campaign_id, str) or not campaign_id:
                raise EvidenceRegistryError("Evidence registry campaign_id must be non-empty")
            if campaign_id in entries:
                raise EvidenceRegistryError(f"Duplicate evidence campaign: {campaign_id}")
            relative = self._safe_relative(manifest, "manifest")
            manifest_path = (self.registry_path.parent / Path(*relative.parts)).resolve()
            try:
                manifest_path.relative_to(self.registry_path.parent)
            except ValueError as exc:
                raise EvidenceRegistryError(
                    f"Evidence manifest escapes the registry directory: {manifest!r}"
                ) from exc
            entries[campaign_id] = manifest_path
        return entries

    @staticmethod
    def _safe_relative(value: Any, label: str) -> PurePosixPath:
        if (
            not isinstance(value, str)
            or not value
            or "\\" in value
            or value.startswith("/")
            or re.match(r"^[A-Za-z]:", value)
            or any(part in ("", ".", "..") for part in value.split("/"))
        ):
            raise EvidenceRegistryError(f"Invalid artifact-relative {label}: {value!r}")
        path = PurePosixPath(value)
        return path

    def _artifact_path(self, value: Any, label: str) -> Path:
        relative = self._safe_relative(value, label)
        candidate = (self.artifacts_root / Path(*relative.parts)).resolve()
        try:
            candidate.relative_to(self.artifacts_root)
        except ValueError as exc:
            raise EvidenceRegistryError(
                f"Artifact path escapes WORKBENCH_ARTIFACTS: {value!r}"
            ) from exc
        return candidate

    def campaign(
        self,
        campaign_id: str,
        *,
        consumer: Optional[str] = None,
        verify: bool = True,
    ) -> EvidenceCampaign:
        """Return a campaign after validating its manifest and declared files."""
        manifest_path = self._entries.get(campaign_id)
        if manifest_path is None:
            raise EvidenceRegistryError(f"Unknown evidence campaign: {campaign_id}")
        manifest = _load_json(manifest_path, f"manifest for {campaign_id}")
        schema_version = manifest.get("schema_version")
        if schema_version not in (1, 2):
            raise EvidenceRegistryError(
                f"Unsupported evidence manifest schema for {campaign_id}: "
                f"{manifest.get('schema_version')!r}"
            )
        if manifest.get("campaign_id") != campaign_id:
            raise EvidenceRegistryError(
                f"Evidence manifest campaign mismatch: expected {campaign_id!r}, "
                f"found {manifest.get('campaign_id')!r}"
            )
        if schema_version == 2:
            required = {
                "schema_version", "campaign_id", "created_at", "protocol_path",
                "summary_paths", "artifacts", "consumers",
            }
            if set(manifest) != required or not _CAMPAIGN_ID.fullmatch(campaign_id):
                raise EvidenceRegistryError(
                    f"Invalid protocol-v2 evidence manifest for {campaign_id}"
                )
            created_at = manifest.get("created_at")
            try:
                parsed_at = datetime.fromisoformat(
                    created_at.replace("Z", "+00:00")
                    if isinstance(created_at, str) else ""
                )
            except ValueError as exc:
                raise EvidenceRegistryError(
                    f"Invalid created_at for evidence campaign {campaign_id!r}"
                ) from exc
            if (
                not isinstance(created_at, str)
                or not _TIMESTAMP.fullmatch(created_at)
                or parsed_at.tzinfo is None
            ):
                raise EvidenceRegistryError(
                    f"Invalid created_at for evidence campaign {campaign_id!r}"
                )
        consumers = manifest.get("consumers")
        if (
            not isinstance(consumers, list)
            or not consumers
            or any(
                not isinstance(item, str) or not item or len(item) > 200
                for item in consumers
            )
            or len(consumers) != len(set(consumers))
        ):
            raise EvidenceRegistryError(
                f"Evidence campaign {campaign_id!r} has invalid declared consumers"
            )
        if consumer is not None and consumer not in consumers:
            raise EvidenceRegistryError(
                f"Evidence campaign {campaign_id!r} is not declared for consumer {consumer!r}"
            )
        protocol_relative = self._safe_relative(manifest.get("protocol_path"), "protocol_path")
        root_value = (manifest.get("artifact_root") if schema_version == 1
                      else protocol_relative.parent.as_posix())
        root_relative = self._safe_relative(root_value, "artifact_root")
        root = self._artifact_path(root_relative.as_posix(), "artifact_root")
        if verify and not self.artifacts_root.is_dir():
            raise EvidenceRegistryError(
                f"Artifact store is missing: {self.artifacts_root} "
                "(set WORKBENCH_ARTIFACTS to the copied artifact store)"
            )
        if verify and not root.is_dir():
            raise EvidenceRegistryError(
                f"Evidence campaign directory is missing for {campaign_id}: {root}"
            )

        raw_files = manifest.get("files" if schema_version == 1 else "artifacts")
        if not isinstance(raw_files, list) or not raw_files:
            raise EvidenceRegistryError(
                f"Evidence campaign {campaign_id!r} must declare at least one file"
            )
        files = []
        roles = set()
        paths = set()
        root_prefix = root_relative.parts
        for entry in raw_files:
            if not isinstance(entry, dict):
                raise EvidenceRegistryError(f"Invalid file entry in {campaign_id}")
            if schema_version == 2 and set(entry) != {
                "role", "relative_path", "bytes", "sha256"
            }:
                raise EvidenceRegistryError(
                    f"Invalid protocol-v2 artifact entry in {campaign_id}"
                )
            role = entry.get("role")
            relative = self._safe_relative(
                entry.get("artifact_path" if schema_version == 1 else "relative_path"),
                "file path",
            )
            expected_bytes = entry.get("bytes")
            expected_sha = entry.get("sha256")
            if (
                not isinstance(role, str)
                or not role
                or len(role) > 100
                or role in roles
            ):
                raise EvidenceRegistryError(
                    f"Invalid or duplicate evidence role in {campaign_id}: {role!r}"
                )
            if relative.parts[: len(root_prefix)] != root_prefix:
                raise EvidenceRegistryError(
                    f"Evidence file is outside campaign root {root_relative}: {relative}"
                )
            if relative.as_posix() in paths:
                raise EvidenceRegistryError(
                    f"Duplicate evidence file in {campaign_id}: {relative}"
                )
            if not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool) or expected_bytes < 0:
                raise EvidenceRegistryError(
                    f"Invalid byte size for {campaign_id}/{role}: {expected_bytes!r}"
                )
            if not isinstance(expected_sha, str) or not _SHA256.fullmatch(expected_sha):
                raise EvidenceRegistryError(
                    f"Invalid SHA-256 for {campaign_id}/{role}: {expected_sha!r}"
                )
            file_path = self._artifact_path(relative.as_posix(), "file path")
            if verify:
                if not file_path.is_file():
                    raise EvidenceRegistryError(
                        f"Declared evidence file is missing for {campaign_id}/{role}: {file_path}"
                    )
                actual_bytes = file_path.stat().st_size
                if actual_bytes != expected_bytes:
                    raise EvidenceRegistryError(
                        f"Evidence size mismatch for {campaign_id}/{role}: {file_path} "
                        f"(expected {expected_bytes}, found {actual_bytes})"
                    )
                actual_sha = _sha256(file_path)
                if actual_sha != expected_sha:
                    raise EvidenceRegistryError(
                        f"Evidence checksum mismatch for {campaign_id}/{role}: {file_path} "
                        f"(expected {expected_sha}, found {actual_sha})"
                    )
            files.append(
                EvidenceFile(role, relative.as_posix(), expected_bytes, expected_sha, file_path)
            )
            roles.add(role)
            paths.add(relative.as_posix())

        summary_values = ([manifest.get("summary_path")] if schema_version == 1
                          else manifest.get("summary_paths"))
        if (not isinstance(summary_values, list) or not summary_values or
                any(not isinstance(value, str) for value in summary_values)):
            raise EvidenceRegistryError(
                f"Evidence campaign {campaign_id!r} has invalid summary_paths"
            )
        summary_relatives = tuple(
            self._safe_relative(value, "summary_path") for value in summary_values
        )
        if protocol_relative.as_posix() not in paths:
            raise EvidenceRegistryError(
                f"Evidence protocol_path is not declared in files for {campaign_id}"
            )
        for summary_relative in summary_relatives:
            if summary_relative.as_posix() not in paths:
                raise EvidenceRegistryError(
                    f"Evidence summary_path is not declared in files for {campaign_id}"
                )
        return EvidenceCampaign(
            campaign_id=campaign_id,
            schema_version=schema_version,
            root=root,
            protocol_path=self._artifact_path(protocol_relative.as_posix(), "protocol_path"),
            summary_path=self._artifact_path(summary_relatives[0].as_posix(), "summary_path"),
            summary_paths=tuple(
                self._artifact_path(path.as_posix(), "summary_path")
                for path in summary_relatives
            ),
            consumers=tuple(consumers),
            files=tuple(files),
        )

    def validate(self, campaign_ids: Iterable[str], *, consumer: Optional[str] = None) -> None:
        """Validate several campaigns, raising on the first explicit failure."""
        for campaign_id in campaign_ids:
            self.campaign(campaign_id, consumer=consumer, verify=True)
