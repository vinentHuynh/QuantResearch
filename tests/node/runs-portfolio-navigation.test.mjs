import assert from 'node:assert/strict';
import { test } from 'node:test';
import { canAddRunToPortfolio } from '../../src/features/runs/model.ts';

const run = (overrides = {}) => ({
  status: 'Succeeded',
  input: { delay_bars: 0, ...overrides.input },
  result: { metrics: {}, ...overrides.result },
  ...Object.fromEntries(Object.entries(overrides).filter(([key]) => !['input', 'result'].includes(key))),
});

test('Add this run is offered only for completed importable baseline runs', () => {
  assert.equal(canAddRunToPortfolio(run()), true);
  assert.equal(canAddRunToPortfolio(run({ input: { research: { role: 'Test', scenario: 'Baseline' } } })), true);
  assert.equal(canAddRunToPortfolio(run({ status: 'Failed' })), false);
  assert.equal(canAddRunToPortfolio(run({ result: { metrics: undefined } })), false);
  assert.equal(canAddRunToPortfolio(run({ input: { research: { role: 'Training', scenario: 'Baseline' } } })), false);
  assert.equal(canAddRunToPortfolio(run({ input: { research: { role: 'Test', scenario: 'Higher costs' } } })), false);
  assert.equal(canAddRunToPortfolio(run({ input: { delay_bars: 1 } })), false);
  assert.equal(canAddRunToPortfolio(run({ tags: 'parameter-sensitivity' })), false);
  assert.equal(canAddRunToPortfolio(run({ tags: 'benchmark' })), false);
});
