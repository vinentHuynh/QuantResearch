import assert from 'node:assert/strict';
import { test } from 'node:test';
import { bestPortfolioPreview, exactPortfolioItemForRun, portfolioRiskDetails, portfolioScriptCandidates, portfolioScriptGroups, selectPortfolioHistory } from '../../shared/ts/portfolioScriptCandidates.ts';
import { lifecycleStatus } from '../../shared/ts/strategyLifecycle.ts';
import { strategyStageStatuses } from '../../shared/ts/stageStatus.ts';

const script = (id = 'example', overrides = {}) => ({ id, name: `Script ${id}`, file_hash: 'current', parameters: {}, timeframes: ['5m'], ...overrides });
const run = (id, overrides = {}) => ({ id, status: 'Succeeded', created_at: '2026-09-30T12:00:00Z',
  input: { strategy: script(), source_hash: 'current', dataset: { symbol: 'NQ' }, timeframe: '5m', session: 'rth',
    capital: 100000, parameters: {}, start: '2024-01-01', end: '2026-01-01', ...overrides.input },
  result: { metrics: { net_pnl: 100, net_return: .1, max_drawdown: -.02, trades: 40, monthly: [{ month: '2025-01', return: .1 }], ...overrides.metrics } },
  ...Object.fromEntries(Object.entries(overrides).filter(([key]) => !['input', 'metrics'].includes(key))) });
const item = (id, source, overrides = {}) => ({ id, key: `${source.input.strategy.id}__NQ`, name: 'Imported label',
  symbol: source.input.dataset.symbol, timeframe: source.input.timeframe, session: source.input.session,
  parameters: source.input.parameters, start: source.input.start, end: source.input.end,
  coverage: [{ start: source.input.start, end: source.input.end }], capital: source.input.capital,
  trades: 40, net_pnl: source.result?.metrics.net_pnl ?? 0,
  chart_points: [0, 100], source_run_ids: [source.id], ...overrides });
const catalog = (items = []) => ({ items });
const stage = (kind, stageNumber = 1, extra = {}) => ({ ...lifecycleStatus(kind, stageNumber, kind), ...extra });
const statuses = (runs, statusById = {}) => ({ byRun: new Map(runs.map(run => [run.id, statusById[run.id] || stage('validation-pending')])), byEvaluation: new Map(), configurations: new Map() });
const candidates = (runs, items = [], statusById = {}, filters = {}, strategies = [script()]) => portfolioScriptCandidates(strategies, catalog(items), runs, statuses(runs, statusById), filters);

test('each script appears once across parameter, market and date variants', () => {
  const records = [run('old'), run('params', { input: { parameters: { lookback: 20 } }, metrics: { net_return: .3 } }),
    run('market', { input: { dataset: { symbol: 'ES' } }, metrics: { net_return: .2 } }),
    run('recent', { created_at: '2026-10-01', metrics: { net_return: .3 }, input: { end: '2026-09-01' } })];
  const rows = candidates(records);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].run.id, 'recent');
  assert.equal(rows[0].name, 'Script example');
  assert.deepEqual(rows[0].chart, [0, 10000.000000000015]);
  assert.equal(rows[0].pnl, 100);
  assert.equal(records.length, 4);
});

test('research validity outranks a failed configuration with much greater P&L and score', () => {
  const records = [run('failed', { metrics: { net_pnl: 900000, net_return: 9 } }), run('pass')];
  const rows = candidates(records, [], { failed: stage('failed-checks', 4, { failedStage: 5 }), pass: stage('evaluation-passed', 2) });
  assert.equal(rows[0].run.id, 'pass');
});

test('practical readiness, completed forward test, active forward test, robustness and historical pass rank in order', () => {
  const order = [['practical-ready', 5], ['forward-tested', 4], ['forward-testing', 4], ['robustness-validated', 3], ['evaluation-passed', 2]];
  const records = order.map(([kind], index) => run(kind, { metrics: { net_return: index + 1 } }));
  const states = Object.fromEntries(order.map(([kind, rank]) => [kind, stage(kind, rank)]));
  for (let index = 0; index < records.length; index++) {
    assert.equal(candidates(records.slice(index), [], states)[0].run.id, order[index][0]);
  }
});

test('current supported configurations beat failures, and failures beat stale or unlinked histories', () => {
  const records = [run('current'), run('failed'), run('stale', { input: { source_hash: 'old', strategy: script('example', { file_hash: 'old' }) } })];
  const states = { current: stage('validation-pending'), failed: stage('failed-checks', 1, { failedStage: 2 }), stale: stage('retest-required', 0) };
  const legacy = item('legacy', records[0], { source_run_ids: [], net_pnl: 1000000, research_status: stage('practical-ready', 5) });
  assert.equal(candidates(records, [legacy], states)[0].run.id, 'current');
  assert.equal(candidates(records.slice(1), [legacy], states)[0].run.id, 'failed');
});

test('missing, zero-drawdown and nonfinite metrics rank after usable scores without using P&L', () => {
  const records = [run('usable', { metrics: { net_return: -.01, net_pnl: -10 } }),
    run('zero', { metrics: { max_drawdown: 0, net_pnl: 999999, net_return: 999 } }),
    run('missing', { metrics: { max_drawdown: undefined } }), run('nonfinite', { metrics: { net_return: Infinity } })];
  assert.equal(candidates(records)[0].run.id, 'usable');
  assert.equal(candidates([run('ratio-overflow', { metrics: { net_return: Number.MAX_VALUE, max_drawdown: Number.MIN_VALUE } }), records[0]])[0].run.id, 'usable');
  assert.equal(candidates([run('zero-trades', { metrics: { trades: 0, net_return: 100 } }),
    run('missing-trades', { metrics: { trades: null, net_return: 200 } }), records[0]])[0].run.id, 'usable');
  assert.equal(candidates([run('a'), run('b', { metrics: { trades: 80 } })])[0].run.id, 'b');
});

test('only exact identities in the current Scripts registry appear, including empty scripts', () => {
  const registered = script('example');
  const other = script('other', { name: registered.name });
  const records = [run('known'), run('removed', { input: { strategy: script('removed', { name: registered.name }) } })];
  const imports = [item('legacy', records[1], { key: 'removed__NQ', source_run_ids: [] }),
    item('prefix-lookalike', records[0], { key: 'example-copy__NQ', source_run_ids: [] })];
  const rows = candidates(records, imports, {}, {}, [registered, other]);
  assert.deepEqual(new Set(rows.map(row => row.strategyId)), new Set(['example', 'other']));
  const empty = rows.find(row => row.strategyId === 'other');
  assert.equal(empty.status.kind, 'not-tested');
  assert.deepEqual(empty.status.action, { kind: 'configure-run', label: 'Start research', strategyId: 'other' });
  assert.equal(empty.pnl, null);
  assert.deepEqual(empty.chart, []);
  assert.equal(empty.item, undefined);
});

test('market, timeframe and search filters choose the best matching option before collapsing scripts', () => {
  const records = [run('nq', { metrics: { net_return: 10 } }), run('es', { input: { dataset: { symbol: 'ES' }, timeframe: '1h' } }),
    run('es-better', { input: { dataset: { symbol: 'ES' }, timeframe: '1h' }, metrics: { net_return: .2 } })];
  assert.equal(candidates(records)[0].run.id, 'nq');
  assert.equal(candidates(records, [], {}, { markets: ['ES'] })[0].run.id, 'es-better');
  assert.equal(candidates(records, [], {}, { timeframe: '1h' })[0].run.id, 'es-better');
  assert.equal(candidates(records, [], {}, { search: 'ES' })[0].run.id, 'es-better');
  assert.equal(candidates(records, [], {}, { search: 'missing' }).length, 0);
  assert.equal(candidates(records, [], {}, { markets: ['YM'] }).length, 0);
});

test('an intact exact imported history represents its raw configuration without forcing import again', () => {
  const records = [run('linked'), run('later', { created_at: '2026-10-01', metrics: { net_return: 50 } })];
  const imported = item('history', records[0]);
  const rows = candidates(records, [imported]);
  assert.equal(rows[0].item.id, 'history');
  assert.equal(rows[0].run.id, 'linked');
  assert.equal(rows[0].name, script().name);
});

test('mismatched, conflicting and corrupt histories do not hide exact research configurations', () => {
  const records = [run('base'), run('other-script', { input: { strategy: script('other') } })];
  const imports = [item('mismatch', records[0], { parameters: { lookback: 99 }, research_status: stage('practical-ready', 5) }),
    item('conflict', records[0], { source_run_ids: ['base', 'other-script'] }),
    item('corrupt', records[0], { research_integrity_error: 'checksum mismatch' })];
  const rows = candidates(records, imports, { base: stage('evaluation-passed', 2) });
  assert.equal(rows[0].run.id, 'base');
  assert.equal(rows[0].item, undefined);
  const mismatchedOnly = candidates([records[0]], [imports[0]], {}, { search: '' });
  assert.equal(mismatchedOnly[0].item, undefined);
});

test('catalog comparison uses recorded baseline drawdown, never estimated downsampled chart drawdown', () => {
  const records = [run('good', { metrics: { net_return: .1, max_drawdown: -.01 }, input: { parameters: { option: 1 } } }),
    run('bad', { metrics: { net_return: .1, max_drawdown: -.5 }, input: { parameters: { option: 2 } } })];
  const imports = [item('good-history', records[0], { chart_points: [0, 100, -1000, 100], net_pnl: 100 }),
    item('bad-history', records[1], { chart_points: [0, 100000], net_pnl: 100000 })];
  assert.equal(candidates(records, imports)[0].item.id, 'good-history');
});

test('training and stress runs and histories are excluded from representative portfolio choices', () => {
  const records = [run('base'), run('training', { input: { research: { role: 'Training', scenario: 'Baseline' } }, metrics: { net_return: 100 } }),
    run('stress', { input: { research: { role: 'Test', scenario: 'Higher costs' } }, metrics: { net_return: 100 } })];
  const imports = records.slice(1).map(record => item(record.id, record));
  assert.equal(candidates(records, imports)[0].run.id, 'base');
  const empty = candidates(records.slice(1), imports)[0];
  assert.equal(empty.status.kind, 'not-tested');
  assert.equal(empty.run, undefined);
});

test('portfolio tracking runs are excluded from research configuration choices', () => {
  const base = run('base');
  const tracking = run('tracking', { input: { stage: 'Tracking', portfolio_replay: {
    item_id: 'history', source_run_id: 'base', anchor_start: '2024-01-01',
  } }, metrics: { net_return: 100 } });
  assert.equal(candidates([base, tracking])[0].run.id, 'base');
});

test('unimported runs follow the history importer baseline rules for tags and delay', () => {
  const records = [run('base'), run('tagged-stress', { tags: 'cost-stress', metrics: { net_return: 100 } }),
    run('tagged-sensitivity', { tags: 'parameter-sensitivity', metrics: { net_return: 100 } }),
    run('tagged-benchmark', { tags: 'benchmark', metrics: { net_return: 100 } }),
    run('delay', { input: { delay_bars: 1 }, metrics: { net_return: 100 } }),
    run('incomplete-research', { input: { research: { scenario: 'Baseline' } }, metrics: { net_return: 100 } })];
  assert.equal(candidates(records)[0].run.id, 'base');
  const benchmarkRun = run('benchmark', { input: { strategy: script('buy-hold') }, tags: 'benchmark' });
  const benchmark = item('benchmark-history', benchmarkRun, { benchmark: true });
  const rows = candidates([benchmarkRun], [benchmark], {}, {}, [script('buy-hold')]);
  assert.equal(rows[0].item.id, 'benchmark-history');
  assert.equal(rows[0].status.kind, 'benchmark');
});

test('source freshness and configuration-specific failures come from the shared research derivation', () => {
  const records = [run('old', { input: { source_hash: 'old', strategy: script('example', { file_hash: 'old' }) }, metrics: { net_pnl: 900000 } }),
    run('bad', { tags: 'checks-failed', input: { parameters: { option: 'bad' } } }), run('good', { input: { parameters: { option: 'good' } } })];
  const states = strategyStageStatuses([script()], records, []);
  assert.equal(states.byRun.get('old').kind, 'retest-required');
  assert.equal(states.byRun.get('bad').kind, 'failed-checks');
  assert.equal(states.byRun.get('good').kind, 'validation-pending');
  assert.equal(portfolioScriptCandidates([script()], catalog(records.map(record => item(record.id, record))), records, states)[0].run.id, 'good');
});

test('expanded portfolio group keeps the older $177,625 run alongside the current $18,270 baseline', () => {
  const old = run('312436e7-05eb-4e89-9a43-a98c74646fb7', {
    input: { strategy: script('example', { file_hash: 'old', version: '1.0.0' }), source_hash: 'old',
      start: '2010-06-07', end: '2026-09-03', parameters: { decline_pct: 1 } },
    metrics: { net_pnl: 177625, net_return: 1.77625, trades: 302, max_drawdown: -.1324 },
    result: { metrics: { net_pnl: 177625, net_return: 1.77625, trades: 302, max_drawdown: -.1324 },
      warnings: ['Warmup insufficient: 0 of 201 bars.'] },
  });
  const current = run('d43e22d3-f37d-4daf-9d9f-9c4d6ef6e109', {
    input: { strategy: script('example', { version: '1.1.0' }), source_hash: 'current',
      start: '2025-01-01', end: '2025-12-31', parameters: { decline_pct: 1, hold_sessions: 1 } },
    metrics: { net_pnl: 18270, net_return: .1827, trades: 21, max_drawdown: -.2136 },
  });
  const histories = [item('old-history', old), item('current-history', current)];
  const evidence = statuses([old, current], {
    [old.id]: stage('retest-required', 0), [current.id]: stage('failed-checks', 1, { failedStage: 2 }),
  });
  const groups = portfolioScriptGroups([script()], catalog(histories), [old, current], evidence);
  assert.equal(groups.length, 1);
  assert.deepEqual(groups[0].options.map(option => option.item.id), ['current-history', 'old-history']);
  assert.deepEqual(groups[0].options.map(option => option.pnl), [18270, 177625]);
  assert.deepEqual(groups[0].options.map(option => option.status.kind), ['failed-checks', 'retest-required']);
  assert.equal(portfolioScriptGroups([script()], catalog(histories), [old, current], evidence, { search: old.id.slice(0, 8) })[0].options[0].item.id, 'old-history');
  assert.equal(exactPortfolioItemForRun(catalog(histories), old).id, 'old-history');
  assert.equal(old.result.warnings[0].includes('Warmup insufficient'), true);
});

test('exact run selection replaces same strategy and market without removing other markets', () => {
  const old = run('old');
  const newer = run('newer', { input: { end: '2026-09-01' } });
  const es = run('es', { input: { dataset: { symbol: 'ES' } } });
  const histories = [item('old-history', old), item('new-history', newer), item('es-history', es)];
  assert.deepEqual(selectPortfolioHistory({ 'old-history': 1, 'es-history': 2 }, catalog(histories), [old, newer, es], histories[1], 'example'),
    { 'es-history': 2, 'new-history': 1 });
  const composite = item('folds', newer, { source_run_ids: [old.id, newer.id],
    coverage: [{ start: old.input.start, end: old.input.end }, { start: newer.input.start, end: newer.input.end }] });
  assert.equal(exactPortfolioItemForRun(catalog([composite]), old), undefined);
  assert.equal(exactPortfolioItemForRun(catalog([item('extended', old, { latest_replay: { start: '2026-09-04' } })]), old), undefined);
});

test('collapsed preview ranks full daily P&L divided by dollar drawdown across research statuses', () => {
  const failed = run('failed', { metrics: { net_pnl: 200, max_drawdown: -.95 } });
  const passed = run('passed', { metrics: { net_pnl: 1000, max_drawdown: -.01 } });
  const histories = [item('failed-history', failed, { net_pnl: 200, max_drawdown: -.2, max_drawdown_dollars: 10 }),
    item('passed-history', passed, { net_pnl: 1000, max_drawdown: -.01, max_drawdown_dollars: 500 })];
  const evidence = statuses([failed, passed], { failed: stage('failed-checks'), passed: stage('evaluation-passed') });
  const options = portfolioScriptGroups([script()], catalog(histories), [failed, passed], evidence)[0].options;
  assert.equal(options[0].item.id, 'passed-history');
  assert.equal(bestPortfolioPreview(options).item.id, 'failed-history');
  assert.deepEqual(portfolioRiskDetails(options[1]), { maxDrawdownPercent: 20, maxDrawdownDollars: 10, score: 20 });
  assert.equal(bestPortfolioPreview(options.filter(option => option.symbol === 'NQ' && option.item.id === 'passed-history')).item.id,
    'passed-history');
});

test('raw preview waits for daily risk and ignores the intraday run drawdown metric', () => {
  const record = run('raw', { metrics: { net_pnl: 500, max_drawdown: -.99 } });
  const option = portfolioScriptGroups([script()], catalog(), [record], statuses([record]))[0].options[0];
  assert.equal(portfolioRiskDetails(option).score, null);
  const details = portfolioRiskDetails(option, { raw: { max_drawdown: -.05, max_drawdown_dollars: 25 } });
  assert.deepEqual(details, { maxDrawdownPercent: 5, maxDrawdownDollars: 25, score: 20 });
});

test('zero drawdown and unscored cases sort deterministically', () => {
  const winner = run('winner', { metrics: { net_pnl: 100 } });
  const ordinary = run('ordinary', { metrics: { net_pnl: 1000 } });
  const flat = run('flat', { metrics: { net_pnl: 0 } });
  const records = [winner, ordinary, flat];
  const options = portfolioScriptGroups([script()], catalog(), records, statuses(records)).at(0).options;
  const risk = { winner: { max_drawdown: 0, max_drawdown_dollars: 0 },
    ordinary: { max_drawdown: -.1, max_drawdown_dollars: 100 },
    flat: { max_drawdown: 0, max_drawdown_dollars: 0 } };
  assert.equal(bestPortfolioPreview(options, risk).run.id, 'winner');
  assert.equal(portfolioRiskDetails(options.find(option => option.run.id === 'winner'), risk).score, Infinity);
  assert.equal(portfolioRiskDetails(options.find(option => option.run.id === 'flat'), risk).score, null);
  assert.equal(bestPortfolioPreview(options.filter(option => option.run.id !== 'winner'), risk).run.id, 'ordinary');
  const unscored = options.filter(option => option.run.id !== 'winner' && option.run.id !== 'ordinary');
  assert.equal(bestPortfolioPreview(unscored, risk).run.id, 'flat');
});

test('equal preview scores use research status, recency, then stable identity', () => {
  const older = run('older', { created_at: '2026-01-01', metrics: { net_pnl: 100 } });
  const newer = run('newer', { created_at: '2026-02-01', metrics: { net_pnl: 100 } });
  const betterEvidence = run('better', { created_at: '2025-01-01', metrics: { net_pnl: 100 } });
  const records = [older, newer, betterEvidence];
  const evidence = statuses(records, { better: stage('evaluation-passed'), older: stage('failed-checks'), newer: stage('failed-checks') });
  const options = portfolioScriptGroups([script()], catalog(), records, evidence)[0].options;
  const risk = Object.fromEntries(records.map(record => [record.id, { max_drawdown: -.01, max_drawdown_dollars: 10 }]));
  assert.equal(bestPortfolioPreview(options, risk).run.id, 'better');
  assert.equal(bestPortfolioPreview(options.filter(option => option.run.id !== 'better'), risk).run.id, 'newer');
  const stable = options.filter(option => option.run.id !== 'better').map(option => ({ ...option, date: 'same' }));
  assert.equal(bestPortfolioPreview(stable, risk).run.id, 'newer');
});
