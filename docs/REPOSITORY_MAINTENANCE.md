# Repository maintenance checks

These checks are read-only. They inspect the repository and local toolchain but
do not install packages, rewrite data, or alter a workbench run.

## Repository hygiene

Run:

```powershell
node scripts/check-repo-hygiene.mjs
```

The check exits with status `1` when Git tracks generated output or an
unapproved file larger than 5 MiB. Generated output includes the top-level
`reports/`, `artifacts/`, `tmp/`, `.codex-skill-staging/`, `build/`, `coverage/`,
`dist/`, and `node_modules/` directories, conventional Python/tool caches,
compiled Python files, and TypeScript build-info files. Only the six named parquet files
that make up the committed `data/mnq_dom_sample/full_history` fixture are on the
large-file allowlist; another file in the same directory is not implicitly
allowed.

Failures list at most 50 paths per category and include the total count. Use
`--json` for machine-readable output. `--root <path>` checks another worktree,
which is useful while validating a history cleanup.

## Environment doctor

Run:

```powershell
node scripts/doctor.mjs
```

The doctor compares the active Node runtime and installed key Node packages to
`WORKBENCH.md` and `package.json`. It first uses the workbench interpreter
selection—`WORKBENCH_PYTHON`, then the repository `.venv`—and uses a PATH
fallback only so it can still diagnose a missing virtual environment. It
compares that runtime and its core packages to `WORKBENCH.md` and
`requirements-workbench.txt`.

Each line is marked `ok`, `mismatch`, or `missing`. Exit status `0` means every
check matches; status `1` means the environment needs attention; status `2`
means the diagnostic itself could not run. A mismatch is informational about
the current machine: the doctor never upgrades or replaces the environment.
Use `--json` for automation.

The scripts' focused unit tests run without starting the workbench:

```powershell
node --test tests/node/maintenance-scripts.test.mjs
```
