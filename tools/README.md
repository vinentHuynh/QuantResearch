# Repository tools

This directory contains data preparation, validation, migration, runtime-support, and repository-maintenance utilities. Repository checks live in `maintenance/`; shared command-launch support lives in `runtime/`. Tools may inspect or transform Workbench inputs, but they must not become strategy adapters or contain domain execution logic.

During the compatibility release, documented entry points under `scripts/` remain as thin wrappers for implementations moved here. Utilities must treat `data/workbench/` as durable state, place generated output beneath `WORKBENCH_ARTIFACTS`, and avoid rewriting historical records.

## Maintained utilities

- `maintenance/check-repo-hygiene.mjs` backs
  `node scripts/check-repo-hygiene.mjs` and the existing import surface.
- `maintenance/doctor.mjs` backs `node scripts/doctor.mjs` and only reports
  environment drift; it never installs or upgrades packages.
- `runtime/python-command.mjs` preserves `WORKBENCH_PYTHON` and the repository
  virtual-environment selection used by npm commands.

Legacy Python fetchers and validators stay in `scripts/` while their library
paths, sibling imports, or frozen checksums remain active. Do not duplicate them
here: each future move should leave one shim and one maintained implementation.
