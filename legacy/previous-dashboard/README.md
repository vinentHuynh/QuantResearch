# Previous Strategy Dashboard

This directory preserves the source of the dashboard that preceded Strategy
Workbench. It is retained for historical reference only and is not part of the
active Vite build, TypeScript checks, lint gate, Python test discovery, or
`npm run dev:full` startup path.

The archive contains:

- `dashboard_api/`: the retired FastAPI runner and portfolio API;
- `src/`: the retired React/Redux entrypoint, store, portfolio UI, and sample data;
- `tests/`: tests that exercise only the retired API;
- `assets/`: the earlier standalone dashboard mockup and its runtime support;
- `requirements-dashboard.txt`: dependencies used by the retired API.

The code retains its original repository-relative assumptions so its historical
behavior remains inspectable. Restoring it as a runnable product would require a
separate entrypoint and explicit path configuration; active Workbench code must
not import from this directory.

## Archived failures

The retired suite is intentionally outside the active gate. Its last known
environment failures are recorded rather than suppressed:

- API collection fails when `fastapi` is absent from the Strategy Workbench
  Python environment; that dependency now belongs only to
  `requirements-dashboard.txt`.
- The legacy SQLite tests can fail cleanup on Windows while a database handle is
  still open (`WinError 32`). The active Workbench repository tests own and close
  isolated databases instead of inheriting that lifecycle.
