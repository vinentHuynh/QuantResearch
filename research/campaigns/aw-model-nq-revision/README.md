# AW model NQ revision source

This directory contains the reusable launch and audit programs for the frozen
AW revision campaign. The preregistered plan, receipts, numerical reports,
signal ledgers, and charts remain raw artifacts under:

```text
<WORKBENCH_ARTIFACTS>/research/aw-model-nq-2026-09-29/revision/
```

`WORKBENCH_ARTIFACTS` defaults to `<repo>/artifacts`. The commands also honor
`WORKBENCH_HOME`, so they can inspect a copied Workbench state without changing
the production store.

From the repository root:

```powershell
node research/campaigns/aw-model-nq-revision/run_workbench.mjs status inspected_development
.venv/Scripts/python.exe research/campaigns/aw-model-nq-revision/analyze_runs.py
.venv/Scripts/python.exe research/campaigns/aw-model-nq-revision/signal-audit/build_revised_audit.py <run-id>
.venv/Scripts/python.exe research/campaigns/aw-model-nq-revision/signal-audit/apply_reviews.py
```

Use `--campaign-dir` and `--output-dir` with `analyze_runs.py`, `--output-dir`
with `build_revised_audit.py`, and `--artifact-dir` with `apply_reviews.py` to
operate on an explicit copy. The launcher accepts `AW_REVISION_CAMPAIGN_DIR` for
the same purpose. None of these programs treats a completed historical run as
live-trading approval.
