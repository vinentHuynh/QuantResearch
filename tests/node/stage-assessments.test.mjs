import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DatabaseSync } from 'node:sqlite';
import { createRecordRepository } from '../../server/infra/recordRepository.ts';
import { applyStageAssessments, createStageAssessment } from '../../shared/ts/stageAssessments.ts';
import { lifecycleStatus } from '../../shared/ts/strategyLifecycle.ts';

const input = (symbol = 'NQ') => ({ strategy: { id: 'sample', file_hash: 'current' }, source_hash: 'current',
  dataset: { symbol }, timeframe: '5m', session: 'rth', parameters: { lookback: 10 }, start: '2024-01-01', end: '2024-12-31' });
const run = (id, symbol = 'NQ') => ({ id, created_at: '2026-09-30', status: 'Succeeded', input: input(symbol),
  result: { metrics: { net_return: .1, max_drawdown: -.05, trades: 30 }, warnings: [] } });
const base = lifecycleStatus('validation-pending', 1, 'Backtest complete');
const payload = { attemptedStage: 2, outcome: 'failed', criteria: ['At least 40 trades; observed 30'],
  findings: 'Historical trade minimum failed: 30 observed against 40 required.', evidence: ['one'], reviewer: 'Codex' };

test('assessment records a failed stage without promoting the completed stage', () => {
  const seed = run('one');
  const record = createStageAssessment(payload, seed, base, [seed], [], '2026-09-30T12:00:00Z', 'assessment-1');
  assert.equal(record.configurationKey.length > 0, true);
  seed.stage_assessments = [record];
  const status = applyStageAssessments(base, seed, [seed], []);
  assert.equal(status.kind, 'failed-checks');
  assert.equal(status.stage, 1);
  assert.equal(status.failedStage, 2);
  assert.match(status.finding, /30 observed/);
});

test('stale evidence and a different configuration do not inherit a judgment', () => {
  const seed = run('one');
  seed.stage_assessments = [createStageAssessment(payload, seed, base, [seed], [], '2026-09-30T12:00:00Z', 'assessment-1')];
  assert.equal(applyStageAssessments(base, seed, [seed, run('new')], []).kind, 'validation-pending');
  const other = run('other', 'ES');
  assert.equal(applyStageAssessments(base, other, [other], []).kind, 'validation-pending');
});

test('missing evidence is blocked at the attempted stage rather than failed', () => {
  const seed = run('one');
  seed.stage_assessments = [createStageAssessment({ ...payload, outcome: 'blocked' }, seed, base, [seed], [], '2026-09-30T12:00:00Z', 'assessment-1')];
  const status = applyStageAssessments(base, seed, [seed], []);
  assert.equal(status.kind, 'needs-review');
  assert.equal(status.stage, 1);
  assert.equal(status.blockedStage, 2);
  assert.equal(status.failedStage, undefined);
});

test('a same-stage review can reject an aggregate evaluation pass under stricter frozen criteria', () => {
  const seed = run('one');
  const automatic = lifecycleStatus('evaluation-passed', 2, 'Aggregate evaluation passed');
  seed.stage_assessments = [createStageAssessment({ ...payload, outcome: 'blocked',
    criteria: ['Every fold has at least ten trades'],
    findings: 'A frozen calendar fold has only two trades despite an aggregate pass.' },
    seed, automatic, [seed], [], '2026-09-30T12:00:00Z', 'assessment-1')];
  const status = applyStageAssessments(automatic, seed, [seed], []);
  assert.equal(status.kind, 'needs-review');
  assert.equal(status.stage, 1);
  assert.equal(status.blockedStage, 2);
});

test('a subsequent higher milestone supersedes a same-stage failure', () => {
  const seed = run('one');
  const automatic = lifecycleStatus('evaluation-passed', 2, 'Aggregate evaluation passed');
  seed.stage_assessments = [createStageAssessment(payload, seed, automatic, [seed], [],
    '2026-09-30T12:00:00Z', 'assessment-1')];
  const status = applyStageAssessments(lifecycleStatus('robustness-validated', 3, 'Execution review passed'), seed, [seed], []);
  assert.equal(status.stage, 3);
  assert.equal(status.kind, 'robustness-validated');
});

test('a judgment cannot bypass an authoritative milestone or cite unrelated evidence', () => {
  const seed = run('one');
  assert.throws(() => createStageAssessment({ ...payload, outcome: 'passed' }, seed, base, [seed], [], '2026-09-30T12:00:00Z', 'a'), /prerequisite/);
  assert.throws(() => createStageAssessment({ ...payload, evidence: ['unknown'] }, seed, base, [seed], [], '2026-09-30T12:00:00Z', 'a'), /Reference linked/);
  assert.throws(() => createStageAssessment({ ...payload, attemptedStage: 4 }, seed, base, [seed], [], '2026-09-30T12:00:00Z', 'a'), /preceding/);
});

test('assessment persists on a run record without changing its result', () => {
  const db = new DatabaseSync(':memory:');
  const records = createRecordRepository(db);
  const seed = run('one');
  const originalResult = structuredClone(seed.result);
  seed.stage_assessments = [createStageAssessment(payload, seed, base, [seed], [], '2026-09-30T12:00:00Z', 'assessment-1')];
  records.put('run', seed.id, seed);
  const saved = records.get('run', seed.id);
  assert.deepEqual(saved.stage_assessments, seed.stage_assessments);
  assert.deepEqual(saved.result, originalResult);
  db.close();
});
