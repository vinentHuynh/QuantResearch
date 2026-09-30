# Evidence registry

This directory tracks compact manifests for research evidence consumed by the
Strategy Workbench. Raw output is intentionally excluded from Git and lives
under `WORKBENCH_ARTIFACTS`, which defaults to `<repo>/artifacts`.

`campaigns/` contains the selected protocol and readable summary for each
registered campaign. These are byte-identical, tracked snapshots of the files
declared by the manifests; larger ledgers, charts, and intermediate outputs
remain only in the artifact store.

Every declared file has an artifact-relative path, byte size, and SHA-256.
Application consumers name themselves when resolving a campaign (maintenance
inspection may omit the consumer). Missing stores,
missing files, unexpected sizes, and checksum mismatches are fatal errors; no
consumer may silently omit a campaign whose evidence is unavailable.

The copied research store currently uses `artifacts/research/<campaign-id>`.
Changing `WORKBENCH_ARTIFACTS` moves the store boundary without changing the
tracked manifests or historical campaign IDs.

`historical-reports-26b50a43.manifest.json` records the complete migration of
the former tracked `reports/**` tree from the pre-reorganization unpublished
head. Its source commit applies to every file entry; destinations, worktree byte
sizes, and SHA-256 values make the ignored artifact copy independently
verifiable. A report that later changed is retained separately under a
commit-qualified `historical/` artifact path so neither version is overwritten.
