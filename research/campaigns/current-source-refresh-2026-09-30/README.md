# Current-source research refresh

`RUN.mjs` performs the one-time, resumable refresh through the running Workbench API.
It preserves every historical record and stores its mutable manifest, mappings, comparisons, and
reports in `artifacts/research/current-source-refresh-2026-09-30/`. Keeping that evidence outside
the Workbench source roots prevents campaign bookkeeping from changing the application fingerprint.

Run `node RUN.mjs preflight` to freeze and audit the current state, then `node RUN.mjs launch`
to submit original-window replacements and reconstructed evaluations. `node RUN.mjs continue`
advances status, creates eligible newer-data extensions after the original work is terminal,
and finalizes comparisons and portfolio evidence when all work has completed.

The task uses the existing API queue, frozen batch limit, and two workers. It stops further
submissions if the current execution source, application build, or dependency environment changes.
It never calls the historical-source retry endpoint.
