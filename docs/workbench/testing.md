# Strategy Workbench test levels

The default acceptance gate is hermetic: it reads checked-in sources, builds synthetic fixtures in the operating-system temporary directory, and never opens `data/workbench/` or launches a real-market research job.

```text
npm run test:workbench:all
```

That command checks repository hygiene, builds and lints the active product, runs pure TypeScript/Node logic, runs the Python core/engine/adapter suites, exercises an isolated API lifecycle, and opens every workbench route against fixture-backed state in headless Chromium.

The levels can also be run separately:

```text
npm run test:unit:ts
npm run test:unit:python
npm run test:api:isolated
npm run test:browser:fixture
npm run test:maintenance
npm run check:hygiene
npm run doctor
```

`npm run doctor` is diagnostic. It exits nonzero when the installed Node, Python, or package versions differ from the targets documented for the workbench; it never installs or upgrades anything.

Existing focused commands remain available for compatibility. Commands that exercise the durable workbench or archived market datasets are excluded from the default gate. To run the curated real-data sequence, first stop or finish active research, start the workbench, and opt in explicitly:

```powershell
$env:WORKBENCH_REAL_DATA = "1"
npm run test:real-data
```

Those validations may create durable run records. Unset `WORKBENCH_REAL_DATA` after the session.
