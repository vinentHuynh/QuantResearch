import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, unlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { createCollective } from '../../server/features/portfolio/collective.ts';
import { createPortfolioRisk, dailyPnlRisk } from '../../server/features/portfolio/portfolioRisk.ts';

const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const runId = '11111111-1111-4111-8111-111111111111';

function fixtureRun(state, csv, expectedPnl) {
  const folder = join(state, 'runs', runId);
  mkdirSync(folder, { recursive: true });
  const checksum = sha(csv);
  writeFileSync(join(folder, 'equity.csv'), csv);
  writeFileSync(join(folder, 'manifest.json'), JSON.stringify({
    artifacts: [{ name: 'equity.csv', checksum }],
  }));
  return {
    id: runId, status: 'Succeeded', tags: '',
    input: {
      strategy: { id: 'fixture' }, dataset: { symbol: 'NQ' },
      research: { role: 'Test', scenario: 'Baseline' }, capital: 100,
      start: '2024-01-01', end: '2024-01-03',
    },
    result: { artifacts: [{ name: 'equity.csv', checksum }], metrics: { net_pnl: expectedPnl } },
  };
}

async function settled(api, ids = [runId]) {
  for (let attempt = 0; attempt < 200; attempt++) {
    const response = api.risk(ids);
    if (!response.pending.length) return response;
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  throw new Error('Risk task did not finish');
}

test('daily history risk uses the full ordered daily series and initial capital', () => {
  assert.deepEqual(dailyPnlRisk([
    { date: '2024-01-01', pnl: 20 },
    { date: '2024-01-02', pnl: -30 },
    { date: '2024-01-03', pnl: 20 },
  ], 100), { net_pnl: 10, max_drawdown_dollars: 30, max_drawdown: -0.25 });
  assert.deepEqual(dailyPnlRisk([{ date: '2024-01-01', pnl: 10 }], 100),
    { net_pnl: 10, max_drawdown_dollars: 0, max_drawdown: 0 });
  assert.throws(() => dailyPnlRisk([{ date: '2024-01-01', pnl: NaN }], 100), /invalid/);
});

test('catalog derives composite risk from checksum-verified full daily history', t => {
  const state = mkdtempSync(join(tmpdir(), 'portfolio-risk-catalog-'));
  t.after(() => rmSync(state, { recursive: true, force: true }));
  const folder = join(state, 'collective');
  mkdirSync(folder);
  const id = 'a'.repeat(20);
  const history = {
    trades: [{ source_run: runId }],
    daily: [
      { date: '2024-01-01', pnl: 20 },
      { date: '2024-01-02', pnl: -30 },
      { date: '2025-01-01', pnl: 20 },
    ],
  };
  const bytes = Buffer.from(JSON.stringify(history));
  const checksum = sha(bytes);
  const series_file = `${id}-${checksum.slice(0, 16)}.json`;
  writeFileSync(join(folder, series_file), bytes);
  writeFileSync(join(folder, 'index.json'), JSON.stringify({
    version: 1, generated_at: '2026-09-30T00:00:00Z',
    items: [{ id, key: 'fixture__NQ__1d', name: 'Fixture', symbol: 'NQ', timeframe: '1d',
      session: 'rth', source: 'Workbench', start: '2024-01-01', end: '2025-01-01',
      capital: 100, net_pnl: 10, coverage: [{ start: '2024-01-01', end: '2024-01-02' },
        { start: '2025-01-01', end: '2025-01-01' }], series_file, checksum }],
    errors: [], definitions: { working: '', feasible: '', pnl: '' },
  }));
  const api = createCollective(state, state, '', () => '',
    () => ({ strategies: [], runs: [], evaluations: [] }));
  const item = api.catalog().items[0];
  assert.equal(item.research_integrity_error, undefined);
  assert.equal(item.max_drawdown_dollars, 30);
  assert.equal(item.max_drawdown, -0.25);
  assert.equal(item.net_pnl, 10);
  writeFileSync(join(folder, series_file), 'corrupt');
  assert.match(api.catalog().items[0].research_integrity_error, /checksum/);
});

test('raw risk streams UTC daily closes, persists cache, invalidates changes and reports corrupt or missing files', async t => {
  const state = mkdtempSync(join(tmpdir(), 'portfolio-risk-run-'));
  t.after(() => rmSync(state, { recursive: true, force: true }));
  let csv = 'timestamp,equity\n' +
    '2024-01-01T12:00:00Z,110\n2024-01-01T23:00:00Z,105\n' +
    '2024-01-02T12:00:00Z,130\n2024-01-02T23:00:00Z,120\n' +
    '2024-01-03T23:00:00Z,115\n';
  const run = fixtureRun(state, csv, 15);
  const api = createPortfolioRisk(state, () => [run]);
  assert.deepEqual(api.risk([runId]).pending, [runId]);
  const first = await settled(api);
  assert.deepEqual(first.pending, []);
  assert.equal(first.ready[runId].net_pnl, 15);
  assert.equal(first.ready[runId].max_drawdown_dollars, 5);
  assert.equal(first.ready[runId].max_drawdown, 115 / 120 - 1);
  assert.deepEqual(JSON.parse(readFileSync(join(state, 'collective', 'run-risk-cache.json'), 'utf8')).entries[runId].risk,
    first.ready[runId]);
  const restarted = createPortfolioRisk(state, () => [run]);
  assert.deepEqual(restarted.risk([runId]).ready[runId], first.ready[runId]);

  csv = 'timestamp,equity\n2024-01-01T23:00:00Z,90\n2024-01-02T23:00:00Z,120\n';
  const changed = fixtureRun(state, csv, 20);
  const changedApi = createPortfolioRisk(state, () => [changed]);
  assert.deepEqual(changedApi.risk([runId]).pending, [runId]);
  const second = await settled(changedApi);
  assert.equal(second.ready[runId].max_drawdown_dollars, 10);
  assert.ok(Math.abs(second.ready[runId].max_drawdown + 0.1) < 1e-12);

  writeFileSync(join(state, 'runs', runId, 'equity.csv'), `${csv}2024-01-03T23:00:00Z,140\n`);
  const corrupt = await settled(changedApi);
  assert.match(corrupt.errors[runId], /checksum changed/);
  unlinkSync(join(state, 'runs', runId, 'equity.csv'));
  assert.match(changedApi.risk([runId]).errors[runId], /artifact is missing/);
  assert.match(changedApi.risk(['bad-id']).errors['bad-id'], /Invalid saved run ID/);
});
