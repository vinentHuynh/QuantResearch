import assert from 'node:assert/strict';
import { test } from 'node:test';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { completeUtcThrough, createPortfolioTracking } from '../../server/features/portfolio/portfolioTracking.ts';

function fixture() {
  const state = mkdtempSync(join(tmpdir(), 'portfolio-tracking-'));
  const bars = join(state, 'bars.parquet');
  writeFileSync(bars, 'fixture');
  const source = {
    id: 'source-run', status: 'Succeeded', created_at: '2026-09-29T12:00:00Z',
    input: {
      protocol: 2, id: 'source-run', experiment_id: 'experiment',
      strategy: { id: 'example', name: 'Example', file: 'strategies/example.py' },
      dataset: { id: 'older-data', symbol: 'NQ', first: '2020-01-01', last: '2026-09-28T23:59:00Z' },
      parameters: { contracts: 1 }, start: '2026-01-01', end: '2026-09-28',
      timeframe: '1m', session: 'full-trading-day', stage: 'Evaluation',
      capital: 100000, fee: 1.25, slippage: 1, warmup_days: 60, timeout: 300,
      source_snapshot: 'sources/frozen', source_hash: 'source-hash',
      configuration_id: 'configuration', development_end: '2025-12-31',
      selection_time: '2026-01-01T00:00:00Z', hypothesis: 'test', criteria: 'test',
      research: { evaluation_id: 'evaluation', fold: 0, role: 'Test', candidate: 0, scenario: 'Baseline' },
    },
  };
  const book = {
    id: 'book', key: 'example__NQ__1m', source: 'Current workbench',
    name: 'Example', symbol: 'NQ', timeframe: '1m', session: 'full-trading-day',
    start: '2026-01-01', end: '2026-09-28', coverage: [{ start: '2026-01-01', end: '2026-09-28' }],
    source_run_ids: [source.id], parameters: { contracts: 1 },
  };
  const dataset = {
    id: 'newer-data', symbol: 'NQ', first: '2020-01-01T00:00:00Z',
    last: '2026-09-30T10:00:00Z', registered_at: '2026-09-30T12:00:00Z',
    checksum: 'new-data-checksum', path: bars,
  };
  const catalog = { items: [book] };
  const runs = [source];
  const datasets = [dataset];
  const enqueued = [];
  const dependencies = {
    root: state, state, python: 'python', cleanEnvironment: () => ({}),
    catalog: () => catalog, datasets: () => datasets, runs: () => runs,
    datasetFile: candidate => candidate.path,
    runDataset: candidate => candidate,
    sourceAvailable: () => true,
    enqueue: input => {
      const run = { id: `tracking-${enqueued.length + 1}`, status: 'Queued', created_at: '2026-09-30T12:00:00Z', input };
      enqueued.push(run);
      runs.push(run);
      return run;
    },
    pump: () => {}, now: () => '2026-09-30T12:00:00Z',
  };
  return { state, book, dataset, catalog, runs, enqueued, dependencies,
    close: () => { if (existsSync(state)) rmSync(state, { recursive: true, force: true }); } };
}

test('a partial final UTC day is excluded from automatic replay', () => {
  assert.equal(completeUtcThrough('2026-09-30T10:00:00Z'), '2026-09-29');
  assert.equal(completeUtcThrough('2026-09-30T23:59:00Z'), '2026-09-30');
});

test('an incomplete newer day waits without queuing a replay', () => {
  const f = fixture();
  try {
    f.book.end = '2026-09-30';
    f.book.coverage[0].end = f.book.end;
    const tracking = createPortfolioTracking(f.dependencies);
    assert.equal(tracking.selection(['book']).items.book.status, 'waiting-for-data');
    assert.equal(f.enqueued.length, 0);
  } finally { f.close(); }
});

test('selected run-backed book is queued once with frozen settings across restart', () => {
  const f = fixture();
  try {
    const tracking = createPortfolioTracking(f.dependencies);
    const first = tracking.selection(['book']);
    assert.equal(first.items.book.status, 'queued');
    assert.equal(first.items.book.target_end, '2026-09-29');
    assert.equal(f.enqueued.length, 1);
    const replay = f.enqueued[0].input;
    assert.equal(replay.portfolio_replay.item_id, 'book');
    assert.equal(replay.portfolio_replay.source_run_id, 'source-run');
    assert.equal(replay.start, '2026-01-01');
    assert.equal(replay.end, '2026-09-29');
    assert.equal(replay.stage, 'Tracking');
    assert.equal(replay.research, undefined);
    assert.equal(replay.source_snapshot, f.runs[0].input.source_snapshot);
    tracking.reconcile();
    const recovered = createPortfolioTracking(f.dependencies);
    assert.deepEqual(recovered.reconcile().selection, ['book']);
    assert.equal(f.enqueued.length, 1);
  } finally { f.close(); }
});

test('the frozen NQ 1h momentum book can replay while other unextended Workbench books stay manual', () => {
  const f = fixture();
  try {
    const id = 'f095fc8e4b66ac71d82d';
    const sourceId = '0e7f5f5c-37e1-4fc4-9619-8d999ba3fcdd';
    f.book.id = id;
    f.book.key = 'multi-speed-momentum__NQ__1h';
    f.book.source = 'Workbench';
    f.book.timeframe = '1h';
    f.book.source_run_ids = [sourceId];
    f.runs[0].id = sourceId;
    f.runs[0].input.id = sourceId;
    f.runs[0].input.strategy.id = 'multi-speed-momentum';
    f.runs[0].input.timeframe = '1h';
    const tracking = createPortfolioTracking(f.dependencies);
    const state = tracking.selection([id]);
    assert.equal(state.items[id].status, 'queued');
    assert.equal(f.enqueued.length, 1);
    assert.equal(f.enqueued[0].input.portfolio_replay.source_run_id, sourceId);
    assert.equal(f.enqueued[0].input.end, '2026-09-29');
  } finally { f.close(); }

  const other = fixture();
  try {
    other.book.source = 'Workbench';
    other.book.key = 'multi-speed-momentum__NQ__1h';
    const tracking = createPortfolioTracking(other.dependencies);
    assert.equal(tracking.selection(['book']).items.book.status, 'manual-update-required');
    assert.equal(other.enqueued.length, 0);
  } finally { other.close(); }
});

test('duplicate registration does not queue twice and a short dataset requires manual update', () => {
  const f = fixture();
  try {
    f.dependencies.datasets().push({ ...f.dataset, id: 'duplicate-registration' });
    const tracking = createPortfolioTracking(f.dependencies);
    tracking.selection(['book']);
    tracking.reconcile();
    assert.equal(f.enqueued.length, 1);
    const short = fixture();
    try {
      short.dataset.first = '2026-09-20T00:00:00Z';
      const shortTracking = createPortfolioTracking(short.dependencies);
      const state = shortTracking.selection(['book']).items.book;
      assert.equal(state.status, 'manual-update-required');
      assert.match(state.error, /preserved replay start/);
      assert.equal(short.enqueued.length, 0);
    } finally { short.close(); }
  } finally { f.close(); }
});

test('failed replay remains visible and retry queues a new attempt', () => {
  const f = fixture();
  try {
    const tracking = createPortfolioTracking(f.dependencies);
    tracking.selection(['book']);
    const failed = f.enqueued[0];
    failed.status = 'Failed';
    failed.error = 'source checksum mismatch';
    tracking.onRunTerminal(failed);
    assert.equal(tracking.reconcile().items.book.status, 'failed');
    assert.equal(f.enqueued.length, 1);
    assert.equal(tracking.retry('book').items.book.status, 'queued');
    assert.equal(f.enqueued.length, 2);
  } finally { f.close(); }
});

test('unsupported campaign and exact pinned histories are clearly reported', () => {
  const f = fixture();
  try {
    f.catalog.items.push({ ...f.book, id: 'expanded', key: 'other-campaign__NQ', source: 'Expanded', source_run_ids: [] });
    f.catalog.items.push({ ...f.book, id: 'pinned', key: 'example__NQ__pinned', source: 'Pinned workbench' });
    const tracking = createPortfolioTracking(f.dependencies);
    const state = tracking.selection(['expanded', 'pinned']);
    assert.equal(state.items.expanded.status, 'manual-update-required');
    assert.equal(state.items.pinned.status, 'manual-update-required');
    assert.equal(f.enqueued.length, 0);
  } finally { f.close(); }
});

test('a complete day without a new overnight session is remembered without publishing', async () => {
  const f = fixture();
  try {
    f.book.key = 'overnight-session__NQ__1m__globex-overnight';
    f.book.source = 'Expanded';
    f.book.latest_replay = { start: '2026-09-01', end: f.book.end, dataset_id: 'older-data', extension_sha256: 'frozen' };
    f.book.source_run_ids = [];
    const scripts = join(f.state, 'scripts');
    mkdirSync(scripts);
    const invocations = join(f.state, 'helper-calls.txt');
    writeFileSync(join(scripts, 'portfolio-replay.py'),
      `require('node:fs').appendFileSync(${JSON.stringify(invocations)}, 'called\\n');\n` +
      `console.log(JSON.stringify({item_id:'book',no_new_session:true,end:'2026-09-28',dataset_id:'newer-data'}));\n`);
    f.dependencies.python = process.execPath;
    const tracking = createPortfolioTracking(f.dependencies);
    tracking.selection(['book']);
    let state;
    for (let attempt = 0; attempt < 100; attempt++) {
      state = tracking.reconcile().items.book;
      if (state.status === 'waiting-for-data') break;
      await new Promise(resolve => setTimeout(resolve, 20));
    }
    assert.equal(state.status, 'waiting-for-data');
    assert.equal(state.simulated_through, '2026-09-28');
    assert.equal(readFileSync(invocations, 'utf8'), 'called\n');
    tracking.reconcile();
    await new Promise(resolve => setTimeout(resolve, 60));
    assert.equal(readFileSync(invocations, 'utf8'), 'called\n');
  } finally { f.close(); }
});
