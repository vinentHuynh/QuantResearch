import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { createCollective } from '../../server/features/portfolio/collective.ts';

test('import reuses a verified exact single-run history without rebuilding', (t) => {
  const root = mkdtempSync(join(tmpdir(), 'collective-import-reuse-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const folder = join(root, 'collective');
  mkdirSync(folder);
  const runId = '11111111-1111-4111-8111-111111111111';
  const run = {
    id: runId,
    status: 'Succeeded',
    tags: '',
    input: {
      strategy: { id: 'fixture', file_hash: 'old' },
      dataset: { symbol: 'NQ' },
      start: '2024-01-01', end: '2024-01-10', timeframe: '1d', session: 'rth',
      parameters: { contracts: 1 },
      research: { evaluation_id: 'evaluation', role: 'Test', scenario: 'Baseline' },
    },
  };
  const trackingId = '22222222-2222-4222-8222-222222222222';
  const trackingRun = {
    ...run,
    id: trackingId,
    input: {
      ...run.input,
      portfolio_replay: {
        item_id: 'a'.repeat(20),
        source_run_id: runId,
        anchor_start: run.input.start,
      },
    },
  };
  const id = 'a'.repeat(20);
  const bytes = Buffer.from(JSON.stringify({
    id, trades: [{ source_run: runId }, { source_run: trackingId }],
    daily: [{ date: '2024-01-10', pnl: 20 }],
    coverage: [{ start: run.input.start, end: run.input.end }],
  }));
  const checksum = createHash('sha256').update(bytes).digest('hex');
  const series_file = `${id}-${checksum.slice(0, 16)}.json`;
  writeFileSync(join(folder, series_file), bytes);
  writeFileSync(join(folder, 'index.json'), JSON.stringify({
    version: 1,
    generated_at: '2026-09-30T00:00:00Z',
    items: [{
      id, key: 'fixture__NQ__1d', name: 'Fixture', symbol: 'NQ', timeframe: '1d',
      session: 'rth', source: 'Current workbench', source_run_ids: [runId],
      start: run.input.start, end: run.input.end,
      coverage: [{ start: run.input.start, end: run.input.end }],
      parameters: run.input.parameters, capital: 1000, benchmark: false,
      series_file, checksum,
    }],
    errors: [],
    definitions: { working: '', feasible: '', pnl: '' },
  }));
  const api = createCollective(root, root, 'unused-python', () => '',
    () => ({ strategies: [], runs: [run, trackingRun], evaluations: [] }));
  assert.equal(api.importRun(runId).running, false);
  assert.equal(api.status().error, '');
  assert.equal(existsSync(join(folder, 'pinned-runs.json')), false);
  assert.deepEqual(api.catalog().items.map(item => item.id), [id]);
  assert.deepEqual(api.catalog().items[0].source_run_ids, [runId]);
  assert.throws(() => api.importRun(trackingId), /cannot be imported as research baselines/);
});

test('failed asynchronous import removes only its new pin', async (t) => {
  const root = mkdtempSync(join(tmpdir(), 'collective-import-rollback-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const folder = join(root, 'collective');
  mkdirSync(folder);
  const runId = '11111111-1111-4111-8111-111111111111';
  const priorPin = '22222222-2222-4222-8222-222222222222';
  const pinsFile = join(folder, 'pinned-runs.json');
  const run = {
    id: runId, status: 'Succeeded', tags: '',
    input: { strategy: { id: 'fixture' }, dataset: { symbol: 'NQ' },
      start: '2024-01-01', end: '2024-01-10', timeframe: '1d', session: 'rth',
      parameters: {}, research: { role: 'Test', scenario: 'Baseline' } },
  };
  const api = createCollective(root, root, process.execPath, () => '',
    () => ({ strategies: [], runs: [run], evaluations: [] }));
  const awaitFailure = async () => {
    for (let attempt = 0; attempt < 200 && api.status().running; attempt++)
      await new Promise(resolve => setTimeout(resolve, 10));
    assert.equal(api.status().running, false);
    assert.notEqual(api.status().error, '');
  };

  writeFileSync(pinsFile, JSON.stringify([priorPin]));
  assert.equal(api.importRun(runId).running, true);
  await awaitFailure();
  assert.deepEqual(JSON.parse(readFileSync(pinsFile, 'utf8')), [priorPin]);

  // A pin that existed before a failed retry belongs to the user and stays.
  writeFileSync(pinsFile, JSON.stringify([priorPin, runId]));
  assert.equal(api.importRun(runId).running, true);
  await awaitFailure();
  assert.deepEqual(JSON.parse(readFileSync(pinsFile, 'utf8')), [priorPin, runId]);
});

test('pinned import bypasses unrelated campaign gate while full refresh remains gated', async (t) => {
  const root = mkdtempSync(join(tmpdir(), 'collective-import-gate-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  mkdirSync(join(root, 'scripts'));
  writeFileSync(join(root, 'scripts', 'build-collective.py'), 'process.exit(0);\n');
  const runId = '11111111-1111-4111-8111-111111111111';
  const run = {
    id: runId, status: 'Succeeded', tags: '',
    input: { strategy: { id: 'fixture' }, dataset: { symbol: 'NQ' },
      start: '2024-01-01', end: '2024-01-10', timeframe: '1d', session: 'rth',
      parameters: {}, research: { role: 'Test', scenario: 'Baseline' } },
  };
  const api = createCollective(root, root, process.execPath,
    () => 'Unrelated campaign evidence is unavailable',
    () => ({ strategies: [], runs: [run], evaluations: [] }));
  assert.equal(api.rebuild().running, false);
  assert.equal(api.status().error, 'Unrelated campaign evidence is unavailable');

  assert.equal(api.importRun(runId).running, true);
  for (let attempt = 0; attempt < 200 && api.status().running; attempt++)
    await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(api.status().running, false);
  assert.equal(api.status().error, '');
  assert.equal(api.status().evidence_error, '');
  assert.deepEqual(JSON.parse(readFileSync(join(root, 'collective', 'pinned-runs.json'), 'utf8')), [runId]);
});
