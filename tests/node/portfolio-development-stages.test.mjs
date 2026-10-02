import assert from 'node:assert/strict';
import { test } from 'node:test';
import { strategyStageStatuses } from '../../shared/ts/stageStatus.ts';
import { strategyStageLabels } from '../../shared/ts/strategyLifecycle.ts';
import { portfolioCandidateGroup, portfolioCandidateLabels, portfolioCandidateShortlists, portfolioResearchCandidates, canAddPortfolioCandidate, portfolioPickerTab, comparePortfolioCandidates } from '../../shared/ts/portfolioCandidates.ts';

const strategy = { id: 'example', file_hash: 'current' };
const run = (id, overrides = {}) => ({ id, created_at: '2026-09-30', status: 'Succeeded',
  input: { strategy, source_hash: 'current', dataset: { symbol: 'NQ' }, timeframe: '5m', session: 'rth', parameters: {} },
  result: { metrics: { net_pnl: 100, net_return: .1, max_drawdown: -.02, trades: 40 } }, ...overrides });
const item = (id, kind, overrides = {}) => ({ id, key: 'example__NQ', name: 'Example', symbol: 'NQ', timeframe: '5m', session: 'rth',
  parameters: {}, start: '2024-01-01', end: '2026-01-01', trades: 40, net_pnl: 100, tested: true, working: true, feasible: true,
  research_status: { kind, label: strategyStageLabels[kind] }, ...overrides });
const evaluation = (status, tests) => ({ id: 'evaluation', created_at: '2026-09-30', status, jobs: tests.length,
  folds: [{ training: [], tests }], scenarios: ['Baseline'],
  ...(status === 'Succeeded' ? { result: { scenarios: [{ name: 'Baseline', outcome: 'Meets criteria', metrics: run('base').result.metrics }] } } : {}) });

test('configuration moves from development to active evaluation to pass, then a matching failure blocks it', () => {
  const base = run('base', { input: { ...run('base').input, research: { scenario: 'Baseline' } } });
  let runs = [run('queued', { status: 'Queued', result: undefined })];
  const status = (evaluations = []) => strategyStageStatuses([strategy], runs, evaluations).byRun.values().next().value;
  assert.equal(status().kind, 'backtest-running');
  runs = [base];
  assert.equal(status().kind, 'validation-pending');
  assert.equal(status([evaluation('Running', ['base'])]).kind, 'evaluation-running');
  // Summarizing remains active even when every child is already terminal.
  assert.equal(status([evaluation('Summarizing', ['base'])]).kind, 'evaluation-running');
  assert.equal(status([evaluation('Succeeded', ['base'])]).kind, 'evaluation-passed');
  assert.equal(status([evaluation('Succeeded', ['base'])]).stage, 2);
  const reevaluating = status([evaluation('Succeeded', ['base']), { ...evaluation('Running', ['base']), id: 'new-evaluation' }]);
  assert.equal(reevaluating.kind, 'evaluation-running');
  assert.equal(reevaluating.action.kind, 'open-evaluation');
  assert.equal(reevaluating.action.evaluationId, 'new-evaluation');
  runs.push(run('bad', { tags: 'checks-failed' }));
  assert.equal(status([evaluation('Succeeded', ['base'])]).kind, 'failed-checks');
});

test('portfolio stage names exactly match research, never imported eligibility flags', () => {
  assert.deepEqual(portfolioCandidateLabels, strategyStageLabels);
  for (const kind of Object.keys(strategyStageLabels)) assert.equal(portfolioCandidateGroup(item(kind, kind)), kind);
  assert.equal(portfolioCandidateGroup(item('old', 'retest-required')), 'retest-required');
  assert.equal(portfolioCandidateGroup(item('missing', 'evaluation-passed', { research_status: undefined })), 'needs-review');
  assert.equal(portfolioCandidateGroup(item('corrupt', 'evaluation-passed', { research_integrity_error: 'changed' })), 'needs-review');
});

test('any intact history can be added regardless of stage or P&L', () => {
  const catalog = { items: [item('passed', 'evaluation-passed'), item('old', 'retest-required'), item('loss', 'validation-pending', { net_pnl: -100 }),
    item('failed', 'failed-checks'), item('zero', 'needs-review', { trades: 0 }), item('duplicate', 'evaluation-passed', { end: '2025-01-01' })] };
  const groups = portfolioCandidateShortlists(catalog);
  assert.deepEqual(groups['evaluation-passed'].map(row => row.id), ['passed']);
  assert.deepEqual(groups['retest-required'].map(row => row.id), ['old']);
  assert.deepEqual(groups['validation-pending'].map(row => row.id), ['loss']);
  assert.deepEqual(groups['failed-checks'].map(row => row.id), ['failed']);
  assert.deepEqual(groups['needs-review'].map(row => row.id), ['zero']);
  for (const candidate of catalog.items) assert.equal(canAddPortfolioCandidate(candidate), true);
  assert.equal(canAddPortfolioCandidate(item('uncertified', 'needs-review', { tested: false, trades: 0 })), true);
  assert.equal(canAddPortfolioCandidate(item('corrupt', 'failed-checks', { research_integrity_error: 'bad checksum' })), false);
  assert.equal(catalog.items.length, 6);
});

test('first queued runs appear before import; importing a baseline removes only its exact configuration', () => {
  const first = run('first', { status: 'Queued', result: undefined });
  const later = run('later', { created_at: '2026-10-01' });
  const other = run('other', { input: { ...first.input, dataset: { symbol: 'ES' } } });
  const old = run('old', { input: { ...first.input, source_hash: 'old', strategy: { ...strategy, file_hash: 'old' } } });
  const runs = [first, later, other, old];
  const statuses = strategyStageStatuses([strategy], runs, []);
  assert.deepEqual(portfolioResearchCandidates({ items: [] }, runs, statuses).map(row => row.id), ['later', 'other', 'old']);
  assert.deepEqual(portfolioResearchCandidates({ items: [{ source_run_ids: ['first'] }] }, runs, statuses).map(row => row.id), ['other', 'old']);
  assert.deepEqual(portfolioResearchCandidates({ items: [] }, [first], strategyStageStatuses([strategy], [first], [])).map(row => row.id), ['first']);
});

test('active evaluation on ES does not change the NQ development stage', () => {
  const nq = run('nq');
  const es = run('es', { input: { ...nq.input, dataset: { symbol: 'ES' } } });
  const statuses = strategyStageStatuses([strategy], [nq, es], [evaluation('Running', ['es'])]);
  assert.equal(statuses.byRun.get('es').kind, 'evaluation-running');
  assert.equal(statuses.byRun.get('nq').kind, 'validation-pending');
});

test('three picker outcomes rank validity, failed stage, then measured quality', () => {
  assert.equal(portfolioPickerTab('practical-ready'), 'passed');
  assert.equal(portfolioPickerTab('validation-pending'), 'progress');
  assert.equal(portfolioPickerTab('failed-checks'), 'failed');
  const row = (kind, stage, score, failedStage) => ({ status: { kind, stage, failedStage }, score, trades: 40, date: '2026-01-01' });
  const passed = [row('evaluation-passed', 2, 10), row('practical-ready', 5, 1), row('robustness-validated', 3, 20)].sort(comparePortfolioCandidates);
  assert.deepEqual(passed.map(value => value.status.kind), ['practical-ready', 'robustness-validated', 'evaluation-passed']);
  const failed = [row('failed-checks', 1, 20, 2), row('failed-checks', 3, 1, 4)].sort(comparePortfolioCandidates);
  assert.deepEqual(failed.map(value => value.status.failedStage), [4, 2]);
  const tied = [row('evaluation-passed', 2, null), row('evaluation-passed', 2, 5)].sort(comparePortfolioCandidates);
  assert.equal(tied[0].score, 5);
});
