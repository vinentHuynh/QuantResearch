import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, utimesSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { createHash } from 'node:crypto';
import { strategyStageStatuses, portfolioStageStatus, scorecardLifecycle } from '../../shared/ts/stageStatus.ts';
import { filterCollectiveItems } from '../../shared/ts/collective.ts';
import { createCollective } from '../../server/features/portfolio/collective.ts';

const strategy = { id: 'example', file_hash: 'current', execution_source_hash: 'runtime-current' };
const run = (id, changes = {}) => ({ id, created_at: '2026-09-30', status: 'Succeeded', tags: '',
  input: { protocol: 2, strategy, execution_source_hash: 'runtime-current', dataset: { symbol: 'NQ' }, timeframe: '5m', session: 'rth', parameters: { lookback: 20 }, research: { scenario: id === 'base' ? 'Baseline' : 'Higher costs' }, ...changes.input },
  result: { metrics: { net_pnl: 100, net_return: .1, max_drawdown: -.02, trades: 40, ...changes.metrics } }, ...Object.fromEntries(Object.entries(changes).filter(([key]) => !['input', 'metrics'].includes(key))) });
const children = () => [run('base'), run('cost')];
const evaluation = (changes = {}) => ({ id: 'eval', created_at: '2026-09-30', status: 'Succeeded', folds: [{ training: [], tests: ['base', 'cost'] }], scenarios: ['Baseline', 'Higher costs'], result: { scenarios: ['Baseline', 'Higher costs'].map(name => ({ name, outcome: 'Meets criteria', metrics: run('base').result.metrics })) }, ...changes });
const item = (changes = {}) => ({ id: 'book', symbol: 'NQ', timeframe: '5m', session: 'rth', parameters: { lookback: 20 }, source_run_ids: ['base'], working: true, feasible: true, benchmark: false, ...changes });

test('Research, scorecards and portfolio share the same exact-configuration pass and failures', () => {
  let runs = children();
  let statuses = strategyStageStatuses([strategy], runs, [evaluation()]);
  const portfolio = portfolioStageStatus(item(), runs, statuses);
  assert.equal(portfolio.kind, 'evaluation-passed');
  assert.deepEqual(portfolio, statuses.byRun.get('base'));
  assert.equal(scorecardLifecycle({ evaluation_id: 'eval' }, statuses).kind, portfolio.kind);
  runs = [...runs, run('later-failure', { tags: 'checks-failed', input: { research: undefined } })];
  statuses = strategyStageStatuses([strategy], runs, [evaluation()]);
  assert.equal(portfolioStageStatus(item(), runs, statuses).kind, 'failed-checks');
  assert.equal(scorecardLifecycle({ evaluation_id: 'eval' }, statuses).kind, 'failed-checks');
  assert(statuses.byRun.get('base').checks.some(check => check.includes('Recorded checks failed')));
});

test('missing stress results and failed criteria are separate; partial success cannot promote', () => {
  const partial = evaluation({ result: { scenarios: evaluation().result.scenarios.slice(0, 1) } });
  const pending = strategyStageStatuses([strategy], children(), [partial]).byRun.get('base');
  assert.equal(pending.kind, 'validation-pending');
  assert.equal(pending.action.kind, 'open-evaluation');
  assert(pending.checks.length > 0);
  const failed = evaluation({ result: { scenarios: [{ ...evaluation().result.scenarios[0], outcome: 'Does not meet criteria' }, evaluation().result.scenarios[1]] } });
  assert.equal(strategyStageStatuses([strategy], children(), [failed]).byRun.get('base').kind, 'failed-checks');
});

test('legacy imported flags, changed helpers, missing links and mixed settings cannot award stages', () => {
  const old = run('base', { input: { execution_source_hash: 'runtime-old' } });
  const statuses = strategyStageStatuses([strategy], [old], []);
  assert.equal(portfolioStageStatus(item(), [old], statuses).kind, 'retest-required');
  assert.equal(portfolioStageStatus(item({ source_run_ids: [] }), [old], statuses).kind, 'needs-review');
  assert.equal(portfolioStageStatus(item({ source_run_ids: ['missing'] }), [old], statuses).kind, 'needs-review');
  assert.equal(portfolioStageStatus(item({ parameters: { lookback: 30 } }), [old], statuses).kind, 'needs-review');
  assert.equal(portfolioStageStatus(item({ benchmark: true }), [old], statuses).kind, 'benchmark');
});

test('evaluation actions preserve the seed and zero-trade runs require review', () => {
  const standalone = run('seed', { input: { research: undefined } });
  const statuses = strategyStageStatuses([strategy], [standalone, run('zero', { metrics: { trades: 0 }, input: { parameters: { lookback: 40 } } })], []);
  assert.deepEqual(statuses.byRun.get('seed').action, { kind: 'plan-evaluation', label: 'Plan evaluation', runId: 'seed' });
  assert.equal(statuses.byRun.get('zero').kind, 'needs-review');
});

test('stage filters are mutually exclusive and do not remove selected histories', () => {
  const runs = children();
  const statuses = strategyStageStatuses([strategy], runs, [evaluation()]);
  const passing = { ...item(), name: 'Example', source: 'Workbench', research_status: portfolioStageStatus(item(), runs, statuses) };
  const unknown = { ...passing, id: 'unknown', research_status: portfolioStageStatus(item({ source_run_ids: [] }), runs, statuses) };
  const catalog = { items: [passing, unknown] };
  const filter = kind => filterCollectiveItems(catalog, { milestone: kind, markets: [], timeframe: 'all', search: '' });
  assert.deepEqual(filter('evaluation-passed').map(row => row.id), ['book']);
  assert.deepEqual(filter('needs-review').map(row => row.id), ['unknown']);
  assert.equal(filter('all').length, 2);
});

test('catalog derives lineage from verified histories, updates after evaluation, and rejects tampering', () => {
  const folder = mkdtempSync(join(tmpdir(), 'strategy-lifecycle-'));
  try {
    const collectiveFolder = join(folder, 'collective');
    mkdirSync(collectiveFolder);
    const id = 'a'.repeat(20);
    const bytes = Buffer.from(JSON.stringify({ id, trades: [{ source_run: 'base' }] }));
    const checksum = createHash('sha256').update(bytes).digest('hex');
    const filename = `${id}-${checksum.slice(0, 16)}.json`;
    const book = { ...item({ source_run_ids: undefined }), id, series_file: filename, checksum };
    writeFileSync(join(collectiveFolder, filename), bytes);
    writeFileSync(join(collectiveFolder, 'index.json'), JSON.stringify({ items: [book] }));
    const runs = children();
    let evaluations = [];
    const api = createCollective(folder, folder, 'unused-python', () => '', () => ({ strategies: [strategy], runs, evaluations }));
    assert.equal(api.catalog().items[0].research_status.kind, 'validation-pending');
    evaluations = [evaluation()];
    assert.equal(api.catalog().items[0].research_status.kind, 'evaluation-passed');
    assert.deepEqual(api.catalog().items[0].source_run_ids, ['base']);
    writeFileSync(join(collectiveFolder, filename), Buffer.from('corrupt'));
    utimesSync(join(collectiveFolder, filename), new Date(), new Date(Date.now() + 1000));
    const corrupt = api.catalog().items[0];
    assert.equal(corrupt.research_status.kind, 'needs-review');
    assert.equal(portfolioStageStatus(corrupt, runs, strategyStageStatuses([strategy], runs, evaluations)).kind, 'needs-review');
    assert.throws(() => api.series([id]), /history changed/);
  } finally { rmSync(folder, { recursive: true, force: true }); }
});
