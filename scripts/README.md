# Compatibility commands and historical sources

`scripts/` is the stable command surface during the repository transition. New
maintained orchestration belongs under `research/`, utilities under `tools/`,
and gate implementations under `tests/`; documented `scripts/<name>` commands
remain as thin compatibility shims for one release.

Nested Python strategy and campaign sources are a deliberate holdback. They stay
here until protocol-v2 aliases and golden-ledger replay prove a move cannot alter
library identity, frozen checksums, imports, or historical results. See
[`research/README.md`](../research/README.md) for the current map and criteria.

Generated CSV, Parquet, screenshots, and campaign output do not belong here.
Write them to `WORKBENCH_ARTIFACTS` (default `artifacts/`) and track only compact
evidence manifests under `evidence/`.
