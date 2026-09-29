import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { DatabaseSync } from 'node:sqlite';
import { randomUUID } from 'node:crypto';
import { mkdirSync, writeFileSync, createWriteStream } from 'node:fs';
import { resolve, join } from 'node:path';
import { chromium, expect as baseExpect } from '@playwright/test';

const report = resolve('reports/workbench-continuation-2026-09-16');
mkdirSync(report, { recursive: true });
const original = await (await fetch('http://127.0.0.1:8001/api/workbench/state')).json();
assert.equal(original.runs.filter(r => ['Running', 'Queued'].includes(r.status)).length, 0);
const reuse = process.env.WORKBENCH_VALIDATION_HOME;
const home = reuse ? resolve(reuse) : resolve('data', `wbtest-summary-${randomUUID().slice(0, 8)}`);
mkdirSync(join(home, 'datasets'), { recursive: true });
writeFileSync(join(home, 'datasets/catalog.json'), JSON.stringify({ datasets: original.datasets, errors: [] }));
const db = new DatabaseSync(join(home, 'workbench.sqlite3'));
db.exec('CREATE TABLE IF NOT EXISTS records(kind TEXT,id TEXT,body TEXT,PRIMARY KEY(kind,id))');
for (const [field, kind] of Object.entries({ runs: 'run', evaluations: 'evaluation', regimes: 'regime',
  experiments: 'experiment', presets: 'preset', watchlist: 'watch', views: 'view' })) {
  for (const record of reuse ? [] : [...(original[field] || [])].reverse()) {
    assert.ok(!['Running', 'Queued'].includes(record.status), 'Only completed records may be copied');
    db.prepare('INSERT INTO records VALUES(?,?,?)').run(kind, record.id, JSON.stringify(record));
  }
}
db.close();
const output = createWriteStream(join(report, 'isolated-api.log'));
const server = spawn(process.execPath, ['server/workbench.ts'], {
  windowsHide: true, env: { ...process.env, WORKBENCH_HOME: home, WORKBENCH_PORT: '8003' },
});
server.stdout.pipe(output, { end: false });
server.stderr.pipe(output, { end: false });
const origin = 'http://127.0.0.1:8003';
const base = origin + '/api/workbench';
const delay = ms => new Promise(done => setTimeout(done, ms));
const checks = { home, production_runs_before: original.runs.length };
let browser;
async function api(path, body) {
  const response = await fetch(base + path, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const value = await response.json();
  assert.ok(response.ok, JSON.stringify(value));
  return value;
}
try {
  for (let i = 0; ; i++) {
    try { await api('/state?view=summary'); break; }
    catch (error) { if (i >= 30 || server.exitCode !== null) throw error; await delay(1000); }
  }
  let started = performance.now();
  const full = await (await fetch(base + '/state')).text();
  checks.full = { bytes: Buffer.byteLength(full), ms: performance.now() - started };
  started = performance.now();
  const response = await fetch(base + '/state?view=summary');
  const summaryText = await response.text();
  const summary = JSON.parse(summaryText);
  checks.summary = { bytes: Buffer.byteLength(summaryText), ms: performance.now() - started };
  assert.ok(checks.summary.bytes < checks.full.bytes * 0.2);
  assert.deepEqual(summary.runs.map(r => r.id), JSON.parse(full).runs.map(r => r.id));
  assert.equal(summary.runs[0].result.equity_preview, undefined);
  assert.ok((await api('/runs/' + summary.runs[0].id)).result.equity_preview.length);
  const unchanged = await fetch(base + '/state?view=summary', { headers: { 'If-None-Match': response.headers.get('etag') } });
  assert.equal(unchanged.status, 304);
  assert.equal((await unchanged.text()).length, 0);
  checks.conditional_refresh = 304;
  console.log('Summary response:', checks);

  const dataset = original.datasets.find(d => d.symbol === 'MNQ');
  const input = { strategy_id: 'multi-speed-momentum', dataset_id: dataset.id, timeframe: '1d',
    session: 'full-trading-day', parameters: { lookback: 60, contracts: 1 },
    start: '2026-08-03', end: '2026-08-14', capital: 100000, fee: 1.25, slippage: 1,
    timeout: 300, stage: 'Exploratory', hypothesis: 'Isolated application validation of measured warmup coverage; not strategy selection.' };
  checks.warmup = [];
  for (const days of [30, 600]) {
    const preview = await api('/preview', { ...input, warmup_days: days });
    assert.equal(preview.jobs, 1);
    assert.equal(preview.warmup[0].required_bars, 241);
    assert.equal(preview.warmup[0].status, days === 30 ? 'insufficient' : 'sufficient');
    const existing = reuse && summary.runs.find(r => r.input.hypothesis === input.hypothesis && r.input.warmup_days === days);
    const run = existing || (await api('/runs', { ...input, warmup_days: days }))[0];
    checks.warmup.push({ days, preview: preview.warmup[0], run_id: run.id });
    console.log('Preview and launch:', days, preview.warmup[0]);
  }
  const changed = await fetch(base + '/state?view=summary', { headers: { 'If-None-Match': response.headers.get('etag') } });
  if (!reuse) {
    assert.equal(changed.status, 200);
    assert.notEqual(changed.headers.get('etag'), response.headers.get('etag'));
  }
  for (const check of checks.warmup) {
    for (let attempt = 0; ; attempt++) {
      const run = await api('/runs/' + check.run_id);
      if (run.status === 'Succeeded') {
        assert.equal(run.result.warmup.available_bars, check.preview.available_bars);
        assert.equal(run.result.warmup.status, check.preview.status);
        assert.equal(run.result.warnings.some(w => w.startsWith('Insufficient warmup:')), check.days === 30);
        assert.ok(run.result.equity_preview.length);
        check.result = run.result.warmup;
        break;
      }
      assert.ok(['Running', 'Queued'].includes(run.status), JSON.stringify(run));
      assert.ok(attempt < 180, 'Worker timed out');
      await delay(2000);
    }
  }

  browser = await chromium.launch({ channel: 'msedge' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(60000);
  const expect = baseExpect.configure({ timeout: 60000 });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const requests = [];
  page.on('request', request => requests.push(request.url()));
  await page.goto(origin + '/#/runs');
  const row = page.locator('.wb-run-row').filter({ has: page.getByRole('checkbox', { name: `Compare ${checks.warmup[0].run_id}`, exact: true }) });
  await row.click();
  await expect(page.getByRole('alert').getByText(/Insufficient warmup: .*241 required/)).toBeVisible();
  assert.ok(requests.some(url => url.endsWith('/runs/' + checks.warmup[0].run_id)));
  await page.getByRole('alert').getByText(/Insufficient warmup: .*241 required/).scrollIntoViewIfNeeded();
  await page.screenshot({ path: join(report, 'warmup-run-detail.png'), animations: 'disabled' });
  await page.keyboard.press('Escape');
  await page.goto(origin + '/#/new-run');
  const select = async (label, value) => {
    await page.getByRole('textbox', { name: label, exact: true }).click();
    await page.getByRole('option', { name: value, exact: true }).click();
  };
  await select('Strategy', 'Multi-speed momentum');
  await page.getByRole('textbox', { name: 'Dataset version', exact: true }).click();
  await page.getByRole('option', { name: /^MNQ / }).first().click();
  await select('Timeframe', '1d');
  await page.getByLabel('Start date (UTC)', { exact: true }).fill(input.start);
  await page.getByLabel('End date (UTC, inclusive)', { exact: true }).fill(input.end);
  await page.getByRole('button', { name: /Assumptions & record/ }).click();
  await expect(page.getByLabel('Warmup calendar days', { exact: true })).toHaveValue('600');
  await page.getByLabel('Warmup calendar days', { exact: true }).fill('30');
  await page.getByRole('button', { name: /Preview & launch/ }).click();
  await page.getByRole('button', { name: 'Validate & preview', exact: true }).click();
  await expect(page.getByText('MNQ 1d: warmup insufficient', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Launch 1 run', exact: true })).toBeEnabled();
  await page.screenshot({ path: join(report, 'warmup-preview.png'), fullPage: true, animations: 'disabled' });
  assert.ok(requests.some(url => url.endsWith('/state?view=summary')));
  assert.ok(!requests.some(url => url.endsWith('/state')));
  await page.waitForResponse(r => r.url().endsWith('/state?view=summary') && r.status() === 304);
  assert.deepEqual(errors, []);
  checks.browser = 'PASS: summary polling, full detail, default warmup, and measured preview warnings';

  const after = await (await fetch('http://127.0.0.1:8001/api/workbench/state')).json();
  assert.deepEqual(after.runs, original.runs, 'Production runs must remain unchanged');
  checks.production_runs_after = after.runs.length;
  checks.status = 'PASS';
  writeFileSync(join(report, 'validation.json'), JSON.stringify(checks, null, 2));
  console.log(JSON.stringify(checks, null, 2));
} finally {
  if (browser) await browser.close();
  server.kill();
  output.end();
}
