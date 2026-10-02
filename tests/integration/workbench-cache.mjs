import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { basename, dirname, join, resolve, sep } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { test } from "node:test";

const repository = resolve(import.meta.dirname, "../..");
const cacheParent = repository;
const python = process.env.WORKBENCH_PYTHON || join(repository,
  process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
const adapter = `STRATEGY = {
    'schema_version': 2,
    'source_files': ['strategies/cache_probe.py'],
    'id': 'cache-probe', 'name': 'Cache probe',
    'description': 'Isolated cache test adapter',
    'timeframes': ['1h'], 'parameters': {},
    'migration_scope': 'Isolated API test only.',
}

def signals(bars, parameters):
    return 0
`;

async function freePort() {
  const probe = createServer();
  await new Promise((done) => probe.listen(0, "127.0.0.1", done));
  const address = probe.address();
  const port = typeof address === "object" && address ? address.port : 0;
  await new Promise((done) => probe.close(done));
  return port;
}

const delay = (ms) => new Promise((done) => setTimeout(done, ms));

async function fixture() {
  const root = resolve(await mkdtemp(join(cacheParent, ".workbench-cache-")));
  const home = join(root, "state");
  const included = (path) => !path.split(/[\\/]/).some((part) =>
    ["__pycache__", "node_modules", ".venv", "dist"].includes(part));
  for (const name of ["server", "shared", "workbench", "strategy_engine"])
    await cp(join(repository, name), join(root, name), { recursive: true, filter: included });
  const contractPath = join(root, "workbench/contract.py");
  const contract = await readFile(contractPath, "utf8");
  const originalEntry = "    print(json.dumps(discover(Path(sys.argv[1]).resolve())))";
  assert(contract.includes(originalEntry));
  await writeFile(contractPath, contract.replace(originalEntry, `    root = Path(sys.argv[1]).resolve()
    with (root / 'scan.attempts').open('a') as attempts:
        attempts.write('scan\\n')
    result = discover(root)
    if (root / 'scan.hold').is_file():
        (root / 'scan.ready').write_text('ready')
        import time
        time.sleep(1.5)
    print(json.dumps(result))`));
  await mkdir(join(root, "config"), { recursive: true });
  await mkdir(join(root, "strategies"), { recursive: true });
  await mkdir(home, { recursive: true });
  await writeFile(join(root, "strategies/cache_probe.py"), adapter);
  await writeFile(join(root, "config/workbench-layout.json"), JSON.stringify({
    schema_version: 1,
    protocol_version: 2,
    paths: {
      state: "state", artifacts: "artifacts", evidence: "evidence", contracts: "shared/contracts",
    },
    source_roots: ["strategies", "workbench", "strategy_engine", "server", "shared"],
    source_aliases: {},
    discovery_paths: {
      strategy_adapters: ["strategies"],
      python_library: [".", "strategies"],
      pine_library: [".", "pine"],
    },
  }));
  return { root, home };
}

test("summary cache invalidates for SQLite writes, discovery, archive, restore, and import", { timeout: 45_000 }, async () => {
  const { root, home } = await fixture();
  const port = await freePort();
  const base = `http://127.0.0.1:${port}/api/workbench`;
  let log = "";
  const server = spawn(process.execPath, ["server/workbench.ts"], {
    cwd: root,
    env: {
      ...process.env,
      WORKBENCH_HOME: home,
      WORKBENCH_ARTIFACTS: join(root, "artifacts"),
      WORKBENCH_PYTHON: python,
      WORKBENCH_PORT: String(port),
      PYTHONDONTWRITEBYTECODE: "1",
    },
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  for (const stream of [server.stdout, server.stderr])
    stream.on("data", (chunk) => { log = (log + chunk).slice(-12_000); });

  async function state(previousEtag) {
    const response = await fetch(`${base}/state?view=summary`, {
      headers: previousEtag ? { "If-None-Match": previousEtag } : {},
    });
    const body = await response.text();
    return { status: response.status, etag: response.headers.get("etag"),
      value: body ? JSON.parse(body) : null };
  }
  async function post(path, payload = {}) {
    const response = await fetch(base + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json();
    assert.equal(response.status, path === "/import" ? 202 : 200, JSON.stringify(body));
    return body;
  }
  async function changed(previous, check, timeoutMs = 8_000) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const next = await state(previous.etag);
      if (next.status === 200 && check(next.value)) {
        assert.notEqual(next.etag, previous.etag);
        return next;
      }
      await delay(100);
    }
    assert.fail(`Cached summary did not change as expected. API log:\n${log}`);
  }

  try {
    let initial;
    for (let attempt = 0; attempt < 150; attempt += 1) {
      if (server.exitCode !== null) throw new Error(`API exited:\n${log}`);
      try {
        initial = await state();
        if (initial.status === 200 && initial.value.strategies.some((item) => item.id === "cache-probe")) break;
      } catch { /* Wait for startup. */ }
      await delay(100);
    }
    assert.equal(initial?.status, 200, `API startup timed out:\n${log}`);
    assert(initial.value.strategies.some((item) => item.id === "cache-probe"), log);
    assert.equal((await state(initial.etag)).status, 304);

    // An external SQLite connection must invalidate the projected runs and ETag.
    const db = new DatabaseSync(join(home, "workbench.sqlite3"));
    db.prepare("INSERT INTO records(kind,id,body) VALUES(?,?,?)").run("run", "cache-run", JSON.stringify({
      id: "cache-run", status: "Succeeded", input: { strategy: { id: "cache-probe" } },
      result: { equity_preview: [1, 2], trade_preview: [] }, log: "large detail",
    }));
    db.close();
    const withRun = await changed(initial, (value) => value.runs.some((run) => run.id === "cache-run"));
    assert.equal(withRun.value.runs[0].result.equity_preview, undefined);
    assert.equal((await state(withRun.etag)).status, 304);

    // Evaluation writes must invalidate state even when no run changed.
    const evaluationDb = new DatabaseSync(join(home, "workbench.sqlite3"));
    evaluationDb.prepare("INSERT INTO records(kind,id,body) VALUES(?,?,?)").run(
      "evaluation", "cache-evaluation", JSON.stringify({
        id: "cache-evaluation", status: "Succeeded", candidates: [], folds: [],
      }),
    );
    evaluationDb.close();
    const withEvaluation = await changed(withRun, (value) =>
      value.evaluations.some((evaluation) => evaluation.id === "cache-evaluation"));
    assert.equal((await state(withEvaluation.etag)).status, 304);

    const patched = await fetch(`${base}/runs/cache-run`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes: "updated" }),
    });
    assert.equal(patched.status, 200, await patched.text());
    const withEdit = await changed(withEvaluation, (value) => value.runs[0].notes === "updated");

    // The periodic gate should discover source edits without an explicit request.
    await writeFile(join(root, "strategies/cache_probe.py"), `${adapter}\n# periodic edit\n`);
    const periodic = await changed(withEdit, (value) =>
      value.strategies[0]?.file_hash !== withEdit.value.strategies[0]?.file_hash, 12_000);

    await writeFile(join(root, "strategies/cache_probe.py"), `${adapter}\n# explicit edit\n`);
    await post("/discover");
    const explicit = await changed(periodic, (value) =>
      value.strategies[0]?.file_hash !== periodic.value.strategies[0]?.file_hash);

    // A manual scan made after an active scan's snapshot must return the newer source.
    await writeFile(join(root, "scan.hold"), "");
    await writeFile(join(root, "strategies/cache_probe.py"), `${adapter}\n# first in-flight edit\n`);
    for (let attempt = 0; attempt < 100 && !existsSync(join(root, "scan.ready")); attempt += 1)
      await delay(100);
    assert(existsSync(join(root, "scan.ready")), `Periodic discovery did not start:\n${log}`);
    const latestAdapter = `${adapter}\n# second in-flight edit\n`;
    await writeFile(join(root, "strategies/cache_probe.py"), latestAdapter);
    const overlappingScan = await post("/discover");
    const latestHash = createHash("sha256").update(latestAdapter).digest("hex");
    assert.equal(overlappingScan.strategies.find((item) => item.id === "cache-probe")?.file_hash, latestHash);
    await rm(join(root, "scan.hold"));
    const afterOverlap = await changed(explicit, (value) => value.strategies[0]?.file_hash === latestHash);

    await post("/scripts/archive", { id: "cache-probe" });
    const archived = await changed(afterOverlap, (value) =>
      value.strategies.length === 0 && value.runs.length === 0 && value.archived_scripts.length === 1);
    await post("/scripts/restore", { id: "cache-probe" });
    const restored = await changed(archived, (value) =>
      value.strategies.some((item) => item.id === "cache-probe") && value.archived_scripts.length === 0);

    await post("/import");
    const importing = await changed(restored, (value) => value.import.status !== "Idle");
    assert(["Running", "Succeeded"].includes(importing.value.import.status));
    assert.equal((await state(importing.etag)).status, 304);

    // A persistent source error should be retried on edit or manual scan only.
    await mkdir(join(root, "pine"), { recursive: true });
    await writeFile(join(root, "pine/invalid.pine"), "invalid declaration\n");
    const failedScan = await post("/discover");
    assert(failedScan.errors.some((item) => /Cannot classify Pine declaration/.test(item.error)));
    const attemptsBefore = (await readFile(join(root, "scan.attempts"), "utf8")).trim().split("\n").length;
    await delay(5_500);
    const attemptsAfter = (await readFile(join(root, "scan.attempts"), "utf8")).trim().split("\n").length;
    assert.equal(attemptsAfter, attemptsBefore, "Unchanged failed discovery retried on the idle timer");
  } finally {
    if (server.exitCode === null) {
      const exited = new Promise((done) => server.once("exit", done));
      server.kill("SIGTERM");
      let timeout;
      await Promise.race([
        exited,
        new Promise((done) => {
          timeout = setTimeout(done, 5_000);
          timeout.unref();
        }),
      ]);
      clearTimeout(timeout);
      if (server.exitCode === null) server.kill("SIGKILL");
    }
    // The fixture is the only recursive deletion target.
    assert.equal(dirname(root), cacheParent);
    assert(basename(root).startsWith(".workbench-cache-"));
    assert(root.startsWith(cacheParent + sep));
    await rm(root, { recursive: true, force: true });
  }
});
