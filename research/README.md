# Research source

This directory contains reproducible study and campaign code that investigates a hypothesis but is not a runnable Strategy Workbench adapter. Campaign drivers live in `campaigns/`, and portfolio research lives in `portfolio/`. Keep stable adapters directly under `strategies/`, shared execution and accounting in `strategy_engine/`, and Workbench orchestration in `workbench/`.

During the compatibility release, documented entry points under `scripts/` remain as thin wrappers for implementations moved here. Write raw outputs beneath `WORKBENCH_ARTIFACTS` (by default `artifacts/`) and commit only compact protocols, conclusions, and checksum manifests under `evidence/` or `docs/research/`.

## Implementation map

| Maintained implementation | Stable command |
| --- | --- |
| `campaigns/strategy-optimization-2022-2024.mjs` | `node scripts/optimize-workbench.mjs` / `npm run research:optimize` |
| `campaigns/strategy-potential-2025.mjs` | `node scripts/evaluate-potential.mjs` |
| `campaigns/strategy-potential-2026.mjs` | `node scripts/evaluate-2026.mjs` |
| `campaigns/report-strategy-potential-2026.mjs` | `node scripts/report-2026.mjs` |
| `campaigns/aw-model-nq-revision/` | Direct launch and independent audit commands documented in its README |
| `campaigns/expanded-search-2026-09-16/expanded.py` | Direct historical campaign command documented in its README |
| `portfolio/risk-sizing-study.mjs` | `node scripts/research-risk-sizing.mjs` |

## Compatibility holdbacks

Historical Python studies remain under `scripts/` when moving them would change
strategy-library paths and aliases, break sibling imports, invalidate declared
snapshot dependencies, or change a frozen script checksum. This includes the
nested `mnq`, `cme`, `es_nq`, `orb`, and `overnight` strategy sources and the SND
research/audit/validation drivers. `scripts/calibrate-strategy-condition.mjs`
also remains because its protocol intentionally hashes that exact path. Move a
held source only after old-path resolution and golden-ledger replay cover it.
