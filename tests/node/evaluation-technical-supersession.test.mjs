import assert from 'node:assert/strict';
import { test } from 'node:test';
import { strategyStageStatuses } from '../../shared/ts/stageStatus.ts';
import { runConfigurationKey, testingEvidence } from '../../shared/ts/evidence.ts';
import { readinessEvidenceSnapshot } from '../../shared/ts/readiness.ts';

const strategy = { id: 'example', file_hash: 'adapter-current', execution_source_hash: 'source-current' };
const metrics = { net_pnl: 1000, net_return: .1, max_drawdown: -.05, trades: 40 };
const run = (id, created_at, scenario, changes = {}) => ({
  id, created_at, status: 'Succeeded', tags: '',
  input: { protocol: 2, strategy, execution_source_hash: 'source-current', dataset: { symbol: 'ES' },
    timeframe: '5m', session: 'full-trading-day', parameters: { entry_hour: 17, exit_hour: 6 },
    research: { scenario } },
  result: { metrics }, ...changes,
});
const scenario = (name, outcome = 'Meets criteria') => ({ name, outcome, metrics });
const evaluation = (id, created_at, folds, result, status = 'Succeeded') => ({
  id, created_at, status, folds, scenarios: ['Baseline', 'Higher costs'], result,
});

function fixture() {
  const oldTrain = run('old-train', '2026-10-01T10:01:00Z', 'Training',
    { status: 'Failed', error: 'Python exited 75', result: undefined });
  const oldBase = run('old-base', '2026-10-01T10:02:00Z', 'Baseline');
  const newTrain = run('new-train', '2026-10-01T11:01:00Z', 'Training');
  const newBase = run('new-base', '2026-10-01T11:02:00Z', 'Baseline');
  const newCosts = run('new-costs', '2026-10-01T11:03:00Z', 'Higher costs');
  const interrupted = evaluation('old-eval', '2026-10-01T10:00:00Z',
    [{ training: ['old-train'], tests: ['old-base'] }], undefined, 'Failed');
  interrupted.error = 'A training candidate did not succeed';
  const complete = evaluation('new-eval', '2026-10-01T11:00:00Z',
    [{ training: ['new-train'], tests: ['new-base', 'new-costs'] }],
    { scenarios: [scenario('Baseline'), scenario('Higher costs')] });
  return { runs: [oldTrain, oldBase, newTrain, newBase, newCosts], evaluations: [interrupted, complete] };
}

test('new complete same-source evaluation supersedes old technical interruption while retaining its history', () => {
  const { runs, evaluations } = fixture();
  const evidence = strategyStageStatuses([strategy], runs, evaluations);
  const current = evidence.byRun.get('new-base');
  assert.equal(current.kind, 'evaluation-passed');
  assert.equal(current.stage, 2);
  assert.match(current.finding, /Declared historical evaluation checks passed/);
  assert(!current.checks.some(check => /exited 75|training candidate did not succeed/i.test(check)));
  assert.equal(evidence.byRun.get('old-base').kind, 'evaluation-passed');
  // The superseded attempt is still present for inspection, not discarded.
  assert.equal(evidence.byRun.get('old-train').kind, 'evaluation-passed');
  assert(testingEvidence(strategy, runs, evaluations).issues.some(issue => issue.runId === 'old-train'));
  assert(testingEvidence(strategy, runs, evaluations).issues.some(issue => issue.evaluationId === 'old-eval'));
});

test('an economic scenario failure remains adverse after a newer passing replay', () => {
  const { runs, evaluations } = fixture();
  const failedBase = run('failed-base', '2026-10-01T09:02:00Z', 'Baseline');
  const failedCosts = run('failed-costs', '2026-10-01T09:03:00Z', 'Higher costs');
  const economic = evaluation('economic-eval', '2026-10-01T09:00:00Z',
    [{ training: [], tests: ['failed-base', 'failed-costs'] }],
    { scenarios: [scenario('Baseline'), scenario('Higher costs', 'Does not meet criteria')] });
  const status = strategyStageStatuses([strategy], [...runs, failedBase, failedCosts], [...evaluations, economic]).byRun.get('new-base');
  assert.equal(status.kind, 'failed-checks');
  assert.equal(status.failedStage, 2);
  assert(status.checks.some(check => check.includes('Higher costs: Does not meet criteria')));
});

test('a later technical interruption is not hidden by an earlier pass', () => {
  const { runs, evaluations } = fixture();
  runs.find(candidate => candidate.id === 'old-train').created_at = '2026-10-01T12:01:00Z';
  runs.find(candidate => candidate.id === 'old-base').created_at = '2026-10-01T12:02:00Z';
  evaluations[0].created_at = '2026-10-01T12:00:00Z';
  const status = strategyStageStatuses([strategy], runs, evaluations).byRun.get('new-base');
  assert.equal(status.kind, 'needs-review');
  assert(status.checks.some(check => /exited 75|training candidate did not succeed/i.test(check)));
});

test('a recorded stage assessment still blocks the automatic pass', () => {
  const { runs, evaluations } = fixture();
  const seed = runs.find(candidate => candidate.id === 'new-base');
  seed.stage_assessments = [{ version: 1, id: 'manual-review', runId: seed.id,
    configurationKey: runConfigurationKey(seed), sourceHash: 'source-current',
    attemptedStage: 2, outcome: 'blocked', criteria: ['Fresh-start fold drawdown is too high'],
    findings: 'Timing sensitivity requires review', evidence: ['new-eval'], reviewer: 'Research',
    evidenceSnapshot: readinessEvidenceSnapshot(runs, evaluations), recordedAt: '2026-10-01T12:00:00Z' }];
  const status = strategyStageStatuses([strategy], runs, evaluations).byRun.get('new-base');
  assert.equal(status.kind, 'needs-review');
  assert.equal(status.stage, 1);
  assert.equal(status.finding, 'Timing sensitivity requires review');
  assert.equal(status.blockedStage, 2);
});
