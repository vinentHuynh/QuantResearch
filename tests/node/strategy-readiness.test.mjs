import assert from 'node:assert/strict';
import { test } from 'node:test';
import { strategyStageStatuses, portfolioStageStatus, scorecardLifecycle } from '../../shared/ts/stageStatus.ts';
import { runConfigurationKey } from '../../shared/ts/evidence.ts';
import { createReadinessReview, readinessChecks } from '../../shared/ts/readiness.ts';
import { portfolioCandidateShortlists, canAddPortfolioCandidate } from '../../shared/ts/portfolioCandidates.ts';

const strategy = { id: 'example', file_hash: 'current' };
function fixture() {
  const seed = { id: 'base', created_at: '2026-09-01', status: 'Succeeded', notes: 'Preserved note', tags: '',
    input: { strategy, source_hash: 'current', dataset: { symbol: 'NQ' }, timeframe: '5m', session: 'rth', parameters: { length: 20 }, start: '2024-01-01', end: '2026-09-01', capital: 100000, fee: 1, slippage: 1, research: { scenario: 'Baseline' } },
    result: { metrics: { net_pnl: 100, net_return: .1, max_drawdown: -.02, trades: 40 } } };
  const runs = [seed];
  const evaluations = [{ id: 'evaluation', created_at: '2026-09-01', status: 'Succeeded', folds: [{ training: [], tests: ['base'] }], scenarios: ['Baseline'],
    result: { scenarios: [{ name: 'Baseline', outcome: 'Meets criteria', metrics: seed.result.metrics }] } }];
  const statuses = () => strategyStageStatuses([strategy], runs, evaluations);
  const status = () => statuses().byRun.get('base');
  const add = (phase, date, extra = {}) => {
    const review = createReadinessReview({ phase, reviewer: 'Test reviewer', references: Object.fromEntries(readinessChecks[phase].map(c => [c.id, `Synthetic test evidence for ${c.id}`])), ...extra },
      seed, status(), runs, evaluations, runConfigurationKey(seed), date + 'T12:00:00Z', `review-${(seed.readiness_reviews || []).length}`);
    seed.readiness_reviews = [...(seed.readiness_reviews || []), review];
    return review;
  };
  const robust = () => add('robustness', '2026-10-01');
  const plan = () => add('forward-plan', '2026-10-02', { plan: { start: '2026-10-03', minDays: 30, minTrades: 30, minReturn: .01, maxDrawdown: .1 } });
  const complete = (observation = {}) => add('forward-complete', '2026-11-02', { observation: { end: '2026-11-01', trades: 40, netReturn: .03, maxDrawdown: .05, ...observation } });
  return { seed, runs, evaluations, statuses, status, add, robust, plan, complete };
}
test('five-stage lifecycle requires recorded evidence in order, shared across research, scorecards and portfolio', () => {
  const f = fixture();
  assert.equal(f.status().label, 'Historical evaluation passed');
  assert.equal(f.status().action.kind, 'review-readiness');
  f.robust(); assert.equal(f.status().kind, 'robustness-validated'); assert.equal(f.status().stage, 3);
  f.plan(); assert.equal(f.status().kind, 'forward-testing'); assert.equal(f.status().stage, 4);
  f.complete(); assert.equal(f.status().kind, 'forward-tested');
  f.add('practical', '2026-11-03'); assert.equal(f.status().kind, 'practical-ready'); assert.equal(f.status().stage, 5);
  const item = { id: 'book', key: 'example__NQ', name: 'Example', start: '2024-01-01', end: '2026-09-01', symbol: 'NQ', timeframe: '5m', session: 'rth', parameters: f.seed.input.parameters, source_run_ids: ['base'], trades: 40, tested: true };
  item.research_status = portfolioStageStatus(item, f.runs, f.statuses());
  assert.equal(item.research_status.kind, 'practical-ready');
  assert.equal(scorecardLifecycle({ evaluation_id: 'evaluation' }, f.statuses()).kind, 'practical-ready');
  assert.equal(portfolioCandidateShortlists({ items: [item] })['practical-ready'].length, 1);
  assert(canAddPortfolioCandidate(item));
  assert.equal(f.seed.notes, 'Preserved note');
});
test('cannot skip stages or promote with bare flags, incomplete references or malformed reviews', () => {
  const f = fixture();
  assert.throws(() => f.plan(), /preceding stage/);
  assert.throws(() => f.add('practical', '2026-10-01'), /preceding stage/);
  assert.throws(() => f.add('robustness', '2026-10-01', { references: { parameters: 'one note' } }), /every check/);
  f.seed.tags = 'fully-tested,practical-ready,feasible';
  f.seed.readiness_reviews = [{ phase: 'practical', version: 1, id: 'invalid' }];
  assert.equal(f.status().stage, 2);
  f.seed.readiness_reviews = [null];
  assert.equal(f.status().stage, 2);
});
test('forward dates and criteria must be frozen prospectively; failures stay recorded', () => {
  const f = fixture(); f.robust();
  assert.throws(() => f.add('forward-plan', '2026-10-02', { plan: { start: '2026-09-01', minDays: 1, minTrades: 1, minReturn: 0, maxDrawdown: .1 } }), /valid prospective/);
  f.plan();
  assert.throws(() => f.complete({ end: '2026-12-01' }), /valid prospective/);
  assert.throws(() => f.complete({ end: '2026-10-01' }), /on or after/);
  f.complete({ trades: 5, netReturn: -.01, maxDrawdown: .2 });
  assert.equal(f.status().kind, 'failed-checks');
  assert.equal(f.status().stage, 3);
  assert.equal(f.status().checks.length, 3);
  assert.throws(() => f.add('practical', '2026-11-03'), /preceding stage/);
  f.add('forward-plan', '2026-11-04', { plan: { start: '2026-11-05', minDays: 30, minTrades: 30, minReturn: .01, maxDrawdown: .1 } });
  assert.equal(f.status().kind, 'forward-testing');
  assert.equal(f.seed.readiness_reviews.length, 4);
});
test('changed source, costs, result, new attempts or a new failure invalidate later stages', () => {
  for (const mutate of [
    f => { f.seed.input.fee = 2; },
    f => { f.seed.result.metrics.net_pnl = 300; },
    f => { f.runs.push({ ...f.seed, id: 'new', readiness_reviews: undefined }); },
    f => { f.seed.tags = 'checks-failed'; },
  ]) {
    const f = fixture(); f.robust(); f.plan(); f.complete(); f.add('practical', '2026-11-03');
    mutate(f);
    assert(f.status().stage < 3);
    assert.notEqual(f.status().kind, 'practical-ready');
  }
  const f = fixture(); f.robust();
  assert.equal(strategyStageStatuses([{ ...strategy, file_hash: 'changed' }], f.runs, f.evaluations).byRun.get('base').kind, 'retest-required');
});
test('historical tracking and reviews on another market cannot satisfy forward testing', () => {
  const f = fixture(); f.robust();
  f.seed.input.stage = 'Tracking';
  assert.equal(f.status().stage, 2);
  const other = { ...f.seed, id: 'es', input: { ...f.seed.input, dataset: { symbol: 'ES' } }, readiness_reviews: f.seed.readiness_reviews };
  assert.equal(strategyStageStatuses([strategy], [other], []).byRun.get('es').stage, 1);
});
test('editing ordinary notes does not invalidate reviewed evidence, but an active evaluation does', () => {
  const f = fixture(); f.robust();
  f.seed.notes = 'Edited ordinary note';
  assert.equal(f.status().stage, 3);
  f.evaluations.push({ ...f.evaluations[0], id: 'new-evaluation', status: 'Running', result: undefined });
  assert.equal(f.status().kind, 'evaluation-running');
  assert.equal(f.status().stage, 2);
});
test('backdated or out-of-order saved review chains do not advance readiness', () => {
  const f = fixture(); f.robust();
  const plan = f.plan();
  plan.recordedAt = '2026-09-30T12:00:00Z';
  assert.equal(f.status().stage, 3);
});
