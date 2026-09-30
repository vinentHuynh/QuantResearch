# Test layout

The active Strategy Workbench gate separates tests by the state they may touch:

- `unit/`: hermetic launchers and focused TypeScript/Python tests;
- `integration/`: isolated API and domain lifecycles, plus explicitly opt-in
  real-data validation;
- `browser/`: fixture-backed browser smoke tests against built assets; and
- `fixtures/`: small reviewed source fixtures, never generated run output.

Root `test_*.py` files and `node/*.test.mjs` remain in place so the existing
unittest and Node globs have exactly one discovery path. New `scripts/` gate
files are compatibility shims; their maintained implementations live in the
level-specific directories and are not discovered a second time.

Fixture-backed output respects `WORKBENCH_ARTIFACTS` and defaults to
`artifacts/test-runs/`. The default gate does not write to `data/workbench/` or
`reports/`.
