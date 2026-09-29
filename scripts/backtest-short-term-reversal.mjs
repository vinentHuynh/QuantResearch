import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';

const folder = resolve('reports/short-term-reversal-2026-09-17');
mkdirSync(folder, { recursive: true });
const api = 'http://127.0.0.1:8001/api/workbench';
const save = (name, value) => writeFileSync(join(folder, name), JSON.stringify(value, null, 2));
async function call(path, body) {
  const response = await fetch(api + path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : undefined);
  const result = await response.json();
  assert(response.ok, JSON.stringify(result));
  return result;
}
const campaignFile = join(folder, 'campaign.json');
const campaign = existsSync(campaignFile) ? JSON.parse(readFileSync(campaignFile, 'utf8')) : {
  declared_at: new Date().toISOString(),
  protocol: 'Use every registered market and its entire available history. Fixed long-only 1% close-to-close decline; compare none, weak-close, trend, and both filters without selecting a winner for a holdout. Freeze default both filters before outcomes. SMA=200, weak close=bottom 25%, one contract, RTH daily, next-open to following-open with renewal on consecutive signals, $100000 capital, $2.50 per side and 1 tick per side. All variants share 200-bar initialization. Baseline and passive reference on every market; doubled fees/slippage for default on every market; 0.75% and 1.25% threshold diagnostics on NQ. 32 total attempts. All periods are historical exploratory evidence; no prospective or untouched holdout claim. Negative/nonpositive prices suppress percentage signals. No parameter selection or short-side search.',
  groups: {}, presets: {},
};
save('campaign.json', campaign);
const catalog = await call('/discover', {});
assert(catalog.strategies.some(s => s.id === 'short-term-reversal'));
const state = await call('/state?view=summary');
const datasets = state.datasets;
assert.equal(datasets.length, 5, 'Review protocol if the available market set changes');
const modes = ['none', 'weak-close', 'trend', 'trend-and-weak-close'];
const base = d => ({ strategy_id: 'short-term-reversal', dataset_id: d.id,
  timeframe: '1d', session: 'new-york-rth', start: d.first.slice(0, 10), end: d.last.slice(0, 10),
  capital: 100000, fee: 2.5, slippage: 1, warmup_days: 600, timeout: 1800, stage: 'Exploratory',
  parameters: { decline_pct: 1, confluence: 'trend-and-weak-close', trend_lookback: 200, close_fraction: .25, direction: 'long-only', contracts: 1 },
  criteria: 'Descriptive historical research: positive net P&L, cost resilience, yearly consistency and adequate trade count are reported, not used to relabel inspected history as holdout.' });
async function launch(key, request) {
  if (campaign.groups[key]) return;
  request.hypothesis = `short-term-reversal-2026-09-17 | ${key} | ${campaign.protocol}`;
  const preview = await call('/preview', request);
  save(`preview-${key}.json`, preview);
  assert(preview.jobs > 0);
  const existing = state.runs.filter(r => r.input.hypothesis === request.hypothesis);
  const runs = existing.length ? existing : await call('/runs', request);
  campaign.groups[key] = { request, ids: runs.map(r => r.id) };
  save('campaign.json', campaign);
  console.log(`Queued ${key}: ${runs.length} runs; preview preserved`);
}
for (const d of datasets) {
  await launch(`${d.symbol}-filters`, { ...base(d), sweep: { confluence: modes } });
  await launch(`${d.symbol}-cost-stress`, { ...base(d), fee: 5, slippage: 2 });
  await launch(`${d.symbol}-benchmark`, { ...base(d), strategy_id: 'buy-hold', parameters: { contracts: 1 } });
}
const nq = datasets.find(d => d.symbol === 'NQ');
await launch('NQ-threshold-neighbors', { ...base(nq), sweep: { decline_pct: [.75, 1.25] } });
const ids = Object.values(campaign.groups).flatMap(g => g.ids);
assert.equal(ids.length, 32);
const completed = new Map();
while (completed.size < ids.length) {
  for (const id of ids.filter(id => !completed.has(id))) {
    const detail = await call(`/runs/${id}`);
    if (!['Queued', 'Running'].includes(detail.status)) completed.set(id, detail);
  }
  console.log(`${completed.size}/${ids.length} terminal`);
  if (completed.size < ids.length) await new Promise(r => setTimeout(r, 10000));
}
const readCsv = filename => {
  const [header, ...lines] = readFileSync(filename, 'utf8').trim().split(/\r?\n/);
  const keys = header.split(',');
  return lines.filter(Boolean).map(line => Object.fromEntries(line.split(',').map((value, i) => [keys[i], value])));
};
const results = [];
for (const [group, entry] of Object.entries(campaign.groups)) for (const id of entry.ids) {
  const run = completed.get(id);
  save(`run-${id}.json`, run);
  const row = { group, id, status: run.status, symbol: run.input.dataset.symbol, parameters: run.input.parameters, start: run.input.start, end: run.input.end };
  if (run.status === 'Succeeded') {
    const dir = resolve('data/workbench/runs', id);
    const manifest = JSON.parse(readFileSync(join(dir, 'manifest.json'), 'utf8'));
    for (const artifact of manifest.artifacts) {
      assert.equal(createHash('sha256').update(readFileSync(join(dir, artifact.name))).digest('hex'), artifact.checksum);
    }
    const equity = readCsv(join(dir, 'equity.csv'));
    const trades = readCsv(join(dir, 'trades.csv'));
    const positions = readCsv(join(dir, 'positions.csv'));
    let peak = run.input.capital, dd = 0;
    const years = {};
    for (const e of equity) {
      peak = Math.max(peak, +e.equity); dd = Math.max(dd, peak - +e.equity);
      const year = e.timestamp.slice(0, 4); years[year] = (years[year] || 0) + +e.net_pnl;
    }
    const pnl = trades.reduce((s, t) => s + +t.net_pnl, 0);
    assert(Math.abs(pnl - manifest.metrics.net_pnl) < 1e-5, 'Ledger reconciliation');
    const wins = trades.filter(t => +t.net_pnl > 0), losses = trades.filter(t => +t.net_pnl < 0);
    const gain = wins.reduce((s,t) => s + +t.net_pnl, 0), loss = losses.reduce((s,t) => s - +t.net_pnl, 0);
    Object.assign(row, { metrics: manifest.metrics, warmup: manifest.warmup, max_drawdown_dollars: dd,
      profit_factor: loss ? gain / loss : null, win_rate: trades.length ? wins.length / trades.length : null,
      expectancy: trades.length ? pnl / trades.length : null, yearly_net_pnl: years,
      first_exposure: positions.find(p => +p.intrabar_contracts !== 0)?.timestamp ?? null,
      warnings: manifest.warnings, source_hash: run.input.source_hash });
  } else row.error = run.error ?? run;
  results.push(row);
}
save('results.json', results);
for (const d of datasets) {
  if (campaign.presets[d.symbol]) continue;
  const r = results.find(r => r.group === `${d.symbol}-filters` && r.parameters.confluence === 'trend-and-weak-close');
  const outcome = r.status === 'Succeeded' ? r.metrics.net_pnl > 0 ? 'historically positive' : 'historically negative' : r.status;
  const preset = await call('/presets', { name: `Short-term reversal | ${d.symbol} | 1% + trend + weak close | ${outcome}`, input: { ...base(d), hypothesis: campaign.protocol } });
  campaign.presets[d.symbol] = preset.id;
  save('campaign.json', campaign);
}
const cash = x => x == null ? 'n/a' : x.toLocaleString('en-US', { maximumFractionDigits: 0 });
const num = x => x == null ? 'n/a' : x.toFixed(2);
const lines = ['# Short-term reversal research', '', campaign.protocol, '',
  'Strategy: `strategies/short_term_reversal.py`. Saved in the workbench with five market presets. All full CSV artifacts were checksum-verified and trade P&L reconciled to marked equity.', '',
  '## All attempts', '', '| Market / test | Threshold | Filter | Status | Net P&L | Max DD ($) | Trades | PF | Win rate |', '|---|---:|---|---|---:|---:|---:|---:|---:|'];
for (const r of results) lines.push(`| ${r.group} | ${r.parameters.decline_pct ?? '-'} | ${r.parameters.confluence ?? 'passive'} | ${r.status} | ${cash(r.metrics?.net_pnl)} | ${cash(r.max_drawdown_dollars)} | ${r.metrics?.trades ?? '-'} | ${num(r.profit_factor)} | ${r.win_rate == null ? '-' : (r.win_rate * 100).toFixed(1) + '%'} |`);
lines.push('', '## Default strategy by year', '', '| Market | Year | Net P&L |', '|---|---|---:|');
for (const r of results.filter(r => r.group.endsWith('-filters') && r.parameters.confluence === 'trend-and-weak-close'))
  for (const [year, pnl] of Object.entries(r.yearly_net_pnl ?? {})) lines.push(`| ${r.symbol} | ${year} | ${cash(pnl)} |`);
lines.push('', '## Interpretation and limitations', '',
  '- No configuration was chosen using these results. Default both-filter settings were declared before launch; all 32 attempts, including losses or failures, remain visible.',
  '- Daily decline means RTH close-to-close, not open-to-close. Entries fill next RTH open; exit at the following RTH open. Repeated qualifying signals renew the position, so one ledger trade can last several days. No intraday stop, profit target, margin or liquidation model.',
  '- The 200-day startup uses the beginning of each dataset; preview correctly flags insufficient pre-start history. All reversal variants have the same initialization, while passive buy-and-hold starts immediately. Early sample data initializes the strategy and produces no reversal exposure. End-of-test exits use the final daily close.',
  '- Dataset history ends September 3, 2026; 2026 and the first year are partial. NQ/ES/YM/CL start June 7, 2010; MNQ starts May 5, 2019. Holidays, missing bars and unadjusted rolls can distort daily returns. CL nonpositive prices suppress percentage-based signals; dollar P&L remains subject to price gaps.',
  '- Drawdown is measured at daily closes and can miss intraday extremes. Fixed one-contract dollar results have different economic exposure across markets; MNQ and NQ are strongly related histories, not independent confirmations.',
  '- Cost stress doubles commissions and slippage. Higher costs alone do not test execution timing, roll adjustment or structural regime change. The optional short-side setting has synthetic execution/causality coverage but was not backtested in this long-only campaign.',
  '- These are exploratory runs, not a walk-forward evaluation or live-trading approval. Presets recreate settings with current source; use original run IDs to replay preserved source.', '',
  'Full parameters, warnings, checksums, dates and run IDs: [results.json](results.json), [campaign.json](campaign.json).');
writeFileSync(join(folder, 'REPORT.md'), lines.join('\n') + '\n');
campaign.completed_at = new Date().toISOString();
save('campaign.json', campaign);
console.log(JSON.stringify(results.map(r => ({ group: r.group, filter: r.parameters.confluence, threshold: r.parameters.decline_pct, status: r.status, pnl: r.metrics?.net_pnl, dd: r.max_drawdown_dollars, trades: r.metrics?.trades, pf: r.profit_factor })), null, 2));
