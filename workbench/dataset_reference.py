"""Resolve legacy absolute and protocol-v2 logical dataset references."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any, Mapping


def resolve_dataset_path(
    dataset: Mapping[str, Any],
    workbench_home: str | os.PathLike[str] | None = None,
) -> Path:
    path_value = dataset.get("path")
    if not isinstance(path_value, str) or not path_value:
        raise ValueError("Dataset path must be a nonempty string")
    path = Path(path_value)
    if dataset.get("schema_version") == 2:
        configured = workbench_home or os.environ.get("WORKBENCH_HOME")
        if not configured:
            raise ValueError(
                "Protocol v2 requires a logical dataset path and WORKBENCH_HOME"
            )
        if (
            path.is_absolute()
            or "\\" in path_value
            or re.match(r"^[A-Za-z]:", path_value)
            or any(part in ("", ".", "..") for part in path_value.split("/"))
        ):
            raise ValueError("Protocol v2 requires a logical dataset path")
        home = Path(configured).resolve()
        resolved = (home / path).resolve()
        try:
            resolved.relative_to(home)
        except ValueError as exc:
            raise ValueError("Dataset reference escapes WORKBENCH_HOME") from exc
        if resolved == home:
            raise ValueError("Dataset reference must name a file below WORKBENCH_HOME")
        return resolved
    return path.expanduser().resolve()
