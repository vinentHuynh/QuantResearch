import assert from 'node:assert/strict';
import { test } from 'node:test';
import { lifecycleStatus, statusDisplay, statusFilterLabels, strategyStageLabels } from '../../shared/ts/strategyLifecycle.ts';
import { createStageAssessment } from '../../shared/ts/stageAssessments.ts';
import { firstSentence, outcomeLabel, strategySourceTags, strategyTitle } from '../../shared/ts/formatting.ts';

test('every lifecycle kind gets a stage · state label without changing its stored label', () => {
  const expected = {
    'not-tested': 'Backtest · Next up', 'backtest-running': 'Backtest · Running', 'validation-pending': 'Evaluation · Next up',
    'evaluation-running': 'Evaluation · Running', 'failed-checks': 'Evaluation · Failed', 'retest-required': 'Backtest · Needs rerun',
    'needs-review': 'Backtest · Needs rerun', 'evaluation-passed': 'Robustness · Next up', 'robustness-validated': 'Forward test · Next up',
    'forward-testing': 'Forward test · Running', 'forward-tested': 'Ready · Next up', 'practical-ready': 'Ready', benchmark: 'Benchmark',
  };
  for (const [kind, label] of Object.entries(expected)) {
    const status = lifecycleStatus(kind, 1, 'finding');
    assert.equal(statusDisplay(status).label, label, kind);
    assert.equal(status.label, strategyStageLabels[kind], `${kind} keeps its stored label`);
    assert.ok(statusFilterLabels[kind], `${kind} has filter wording`);
  }
});

test('blocked, failed and tracking statuses use the stage they are stuck on', () => {
  assert.equal(statusDisplay({ ...lifecycleStatus('needs-review', 2, 'x'), blockedStage: 3 }).label, 'Robustness · Blocked');
  assert.equal(statusDisplay({ ...lifecycleStatus('failed-checks', 3, 'x'), failedStage: 4 }).label, 'Forward test · Failed');
  assert.equal(statusDisplay(lifecycleStatus('failed-checks', 1, 'x')).label, 'Evaluation · Failed');
  assert.equal(statusDisplay({ ...lifecycleStatus('needs-review', 1, 'x'), tracking: true }).label, 'Tracking');
  assert.equal(statusDisplay(lifecycleStatus('needs-review', 1, 'x')).color, 'grape');
});

test('display names follow the naming rules and keep source tags separate', () => {
  assert.equal(strategyTitle('Pine · TSMOM intraday ORB'), 'TSMOM intraday ORB');
  assert.deepEqual(strategySourceTags('Pine · TSMOM intraday ORB'), ['Pine']);
  assert.equal(strategyTitle('PineÂ· Overnight block'), 'Overnight block');
  assert.equal(strategyTitle('Overnight Session'), 'Overnight session');
  assert.equal(strategyTitle('Short-term reversal - minute execution'), 'Short-term reversal — minute execution');
  assert.equal(strategyTitle('MNQ · overnight exit clocks'), 'Overnight exit clocks');
  assert.equal(strategyTitle('MNQ · Overnight except red low-close RTH'), strategyTitle('MNQ - Overnight except red low-close RTH'));
  assert.equal(strategyTitle('SND - Supply and demand / phase6'), 'Supply & demand — Phase 6');
  assert.equal(strategyTitle('Wyckoff [theUltimator5] - NQ research'), 'Wyckoff');
  assert.deepEqual(strategySourceTags('Wyckoff [theUltimator5] - NQ research'), ['by theUltimator5']);
  assert.equal(strategyTitle('Moving-average trend'), 'Moving-average trend');
  for (const name of ['Pine · TSMOM intraday ORB', 'Overnight Session', 'MNQ · overnight exit clocks', 'SND - Supply and demand / phase6'])
    assert.equal(strategyTitle(strategyTitle(name)), strategyTitle(name), `${name} is stable when titled twice`);
});

test('outcomes read Passed, Failed or Incomplete; summaries fall back to the first sentence', () => {
  assert.deepEqual(['Meets criteria', 'Does not meet criteria', 'Criteria not met', 'Not scored', undefined].map(outcomeLabel),
    ['Passed', 'Failed', 'Failed', 'Incomplete', 'Incomplete']);
  assert.equal(firstSentence('Drawdowns are 10.24% and 22.87% in 2024. Stage 3 remains blocked.'), 'Drawdowns are 10.24% and 22.87% in 2024.');
  assert.equal(firstSentence('No full stop'), 'No full stop');
});

test('a stage review can carry an optional one-line summary', () => {
  const input = { strategy: { id: 'sample', file_hash: 'current' }, source_hash: 'current', dataset: { symbol: 'NQ' }, timeframe: '5m',
    session: 'rth', parameters: {}, start: '2024-01-01', end: '2024-12-31' };
  const seed = { id: 'one', created_at: '2026-09-30', status: 'Succeeded', input, result: { metrics: { trades: 30 }, warnings: [] } };
  const base = lifecycleStatus('validation-pending', 1, 'Backtest complete');
  const payload = { attemptedStage: 2, outcome: 'blocked', criteria: ['Run 40 trades'], findings: 'Only 30 trades.', evidence: ['one'], reviewer: 'Codex' };
  const without = createStageAssessment(payload, seed, base, [seed], [], '2026-09-30T12:00:00Z', 'a');
  assert.equal('summary' in without, false);
  const withSummary = createStageAssessment({ ...payload, summary: '  Too few   trades to judge. ' }, seed, base, [seed], [], '2026-09-30T12:00:00Z', 'b');
  assert.equal(withSummary.summary, 'Too few trades to judge.');
  assert.throws(() => createStageAssessment({ ...payload, summary: 'x'.repeat(201) }, seed, base, [seed], [], '2026-09-30T12:00:00Z', 'c'), /200 characters/);
});
