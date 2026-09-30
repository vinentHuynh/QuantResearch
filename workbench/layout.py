"""Shared repository layout for the TypeScript API and Python workers.

Configuration paths are repository-relative and may not escape the workspace.
Only the mutable state and raw-artifact roots have environment overrides.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


LAYOUT_SCHEMA_VERSION = 1
PROTOCOL_VERSION = 2
_DRIVE_PATH = re.compile(r"^[A-Za-z]:")


class LayoutError(ValueError):
    """Raised when the checked-in workbench layout is malformed."""


@dataclass(frozen=True)
class WorkbenchLayout:
    schema_version: int
    protocol_version: int
    workspace_root: Path
    config_path: Path
    state_root: Path
    artifacts_root: Path
    evidence_root: Path
    contracts_root: Path
    source_roots: tuple[Path, ...]
    source_aliases: Mapping[str, tuple[str, ...]]
    discovery_paths: Mapping[str, tuple[Path, ...]]


def _object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise LayoutError(f"{label} must be an object")
    return value


def _version(value: object, expected: int, label: str) -> int:
    if type(value) is not int or value != expected:
        raise LayoutError(f"{label} must be {expected}")
    return value


def _relative_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LayoutError(f"{label} must be a nonempty string")
    if "\\" in value or value.startswith("/") or _DRIVE_PATH.match(value):
        raise LayoutError(f"{label} must be repository-relative with forward slashes")
    if value != "." and any(part in ("", ".", "..") for part in value.split("/")):
        raise LayoutError(f"{label} must be a normalized repository-relative path")
    return value


def _repo_path(root: Path, value: object, label: str) -> Path:
    relative = _relative_path(value, label)
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise LayoutError(f"{label} escapes the workspace") from exc
    return resolved


def _path_list(root: Path, value: object, label: str) -> tuple[Path, ...]:
    if not isinstance(value, list) or not value:
        raise LayoutError(f"{label} must be a nonempty array")
    paths = tuple(_repo_path(root, item, f"{label}[{index}]") for index, item in enumerate(value))
    if len(set(paths)) != len(paths):
        raise LayoutError(f"{label} must not contain duplicates")
    return paths


def _source_aliases(value: object) -> Mapping[str, tuple[str, ...]]:
    aliases = _object(value, "source_aliases")
    result: dict[str, tuple[str, ...]] = {}
    for source_id, raw_paths in aliases.items():
        if not isinstance(source_id, str) or not re.fullmatch(
            r"(?:python|pine):[A-Za-z0-9_.-]+", source_id
        ):
            raise LayoutError(f"Invalid source alias id: {source_id!r}")
        if not isinstance(raw_paths, list) or not raw_paths:
            raise LayoutError(f"source_aliases.{source_id} must be a nonempty array")
        paths = tuple(
            _relative_path(path, f"source_aliases.{source_id}[{index}]")
            for index, path in enumerate(raw_paths)
        )
        if len(set(paths)) != len(paths):
            raise LayoutError(f"source_aliases.{source_id} must not contain duplicates")
        result[source_id] = paths
    return result


def _override(root: Path, value: str | None, fallback: Path) -> Path:
    if not value:
        return fallback
    candidate = Path(value).expanduser()
    return (candidate if candidate.is_absolute() else root / candidate).resolve()


def load_layout(
    workspace_root: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> WorkbenchLayout:
    """Load and validate ``config/workbench-layout.json``.

    ``WORKBENCH_HOME`` and ``WORKBENCH_ARTIFACTS`` may be absolute or relative
    to the workspace. Checked-in paths are always constrained to the workspace.
    """

    root = Path(workspace_root or Path(__file__).resolve().parents[1]).resolve()
    config_path = root / "config" / "workbench-layout.json"
    try:
        payload = _object(json.loads(config_path.read_text(encoding="utf-8")), "layout")
    except (OSError, json.JSONDecodeError) as exc:
        raise LayoutError(f"Unable to read {config_path}: {exc}") from exc

    schema_version = _version(payload.get("schema_version"), LAYOUT_SCHEMA_VERSION, "schema_version")
    protocol_version = _version(payload.get("protocol_version"), PROTOCOL_VERSION, "protocol_version")
    paths = _object(payload.get("paths"), "paths")
    required_paths = ("state", "artifacts", "evidence", "contracts")
    missing = [name for name in required_paths if name not in paths]
    if missing:
        raise LayoutError(f"paths is missing: {', '.join(missing)}")

    state_default = _repo_path(root, paths["state"], "paths.state")
    artifacts_default = _repo_path(root, paths["artifacts"], "paths.artifacts")
    evidence_root = _repo_path(root, paths["evidence"], "paths.evidence")
    contracts_root = _repo_path(root, paths["contracts"], "paths.contracts")
    source_roots = _path_list(root, payload.get("source_roots"), "source_roots")
    source_aliases = _source_aliases(payload.get("source_aliases"))

    discovery = _object(payload.get("discovery_paths"), "discovery_paths")
    required_discovery = ("strategy_adapters", "python_library", "pine_library")
    missing = [name for name in required_discovery if name not in discovery]
    if missing:
        raise LayoutError(f"discovery_paths is missing: {', '.join(missing)}")
    discovery_paths = {
        name: _path_list(root, discovery[name], f"discovery_paths.{name}")
        for name in required_discovery
    }

    environment = os.environ if environ is None else environ
    return WorkbenchLayout(
        schema_version=schema_version,
        protocol_version=protocol_version,
        workspace_root=root,
        config_path=config_path,
        state_root=_override(root, environment.get("WORKBENCH_HOME"), state_default),
        artifacts_root=_override(root, environment.get("WORKBENCH_ARTIFACTS"), artifacts_default),
        evidence_root=evidence_root,
        contracts_root=contracts_root,
        source_roots=source_roots,
        source_aliases=source_aliases,
        discovery_paths=discovery_paths,
    )
