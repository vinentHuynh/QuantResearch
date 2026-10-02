import assert from 'node:assert/strict';
import { test } from 'node:test';
import { strategyStageStatuses } from '../../shared/ts/stageStatus.ts';

const strategy = { id: 'example', file_hash: 'current' };
const run = (id, overrides = {}) => ({ id, created_at: '2026-09-30', status: 'Succeeded',
  input: { strategy, source_hash: 'snapshot', dataset: { symbol: 'NQ' }, timeframe: '5m', session: 'rth', parameters: {}, stage: 'Evaluation', ...overrides.input },
  result: { metrics: { net_pnl: 100, net_return: .1, max_drawdown: -.02, trades: 40 } }, ...overrides,
});

test('declaring an Evaluation purpose or completing a run does not award a pass', () => {
  const runs = [run('one')];
  const status = strategyStageStatuses([strategy], runs, []).byRun.get('one');
  assert.equal(status.label, 'Backtested · awaiting evaluation');
  assert.equal(status.finding, 'Validation pending');
});

test('same settings share their stage across attempts; failures stay scoped to those settings', () => {
  const base = run('base', { input: { strategy, source_hash: 'snapshot', dataset: { symbol: 'NQ' }, timeframe: '5m', session: 'rth', parameters: {}, research: { scenario: 'Baseline' } } });
  const evaluation = { id: 'eval', created_at: '2026-09-30', status: 'Succeeded', folds: [{ training: [], tests: ['base'] }], scenarios: ['Baseline'], result: { scenarios: [{ name: 'Baseline', outcome: 'Meets criteria', metrics: base.result.metrics }] } };
  const es = run('es', { input: { ...base.input, dataset: { symbol: 'ES' } }, tags: 'checks-failed' });
  let statuses = strategyStageStatuses([strategy], [base, run('later'), es], [evaluation]).byRun;
  assert.equal(statuses.get('base').label, 'Historical evaluation passed');
  assert.equal(statuses.get('later').label, 'Historical evaluation passed');
  assert.equal(statuses.get('es').label, 'Failed checks · revise strategy');
  statuses = strategyStageStatuses([strategy], [base, run('failure', { tags: 'checks-failed' })], [evaluation]).byRun;
  assert.equal(statuses.get('base').label, 'Failed checks · revise strategy');
  assert.equal(statuses.get('base').finding, 'Criteria not met');
});

test('an old source cannot inherit the current configuration stage', () => {
  const old = run('old', { input: { ...run('current').input, strategy: { ...strategy, file_hash: 'old' } } });
  const statuses = strategyStageStatuses([strategy], [old, run('current')], []).byRun;
  assert.equal(statuses.get('old').label, 'Retest required');
  assert.equal(statuses.get('current').label, 'Backtested · awaiting evaluation');
});

test('portfolio tracking runs do not change research milestones', () => {
  const baseline = run('baseline');
  const tracking = run('tracking', {
    status: 'Failed',
    input: { ...baseline.input, stage: 'Tracking', portfolio_replay: {
      item_id: 'portfolio-book', source_run_id: 'baseline', anchor_start: '2026-01-01',
    } },
    error: 'New dataset is incomplete',
  });
  const statuses = strategyStageStatuses([strategy], [baseline, tracking], []);
  assert.equal(statuses.byRun.get('baseline').kind, 'validation-pending');
  assert.equal(statuses.byRun.get('tracking').kind, 'needs-review');
  assert.equal(statuses.configurations.size, 1);
  assert.equal([...statuses.configurations.values()][0].kind, 'validation-pending');
});
