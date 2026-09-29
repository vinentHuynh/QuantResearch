import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';

const folder = resolve('reports/market-intraday-momentum-2026-09-17');
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
  protocol: 'Historical exploratory research; no untouched holdout or gamma-causality claim. ES/NQ/MNQ/CL, every available year through 2026-09-03. Fixed one contract, $100000, $2.50 fee and one tick slippage per side; 5m RTH bars. Default Baltussen previous close to start of final 30 minutes, both directions; Gao previous close to 10:00 separate variant. ES/NQ/MNQ clock 16:00 New York; CL 14:30 and Gao 10:00 is an explicit adapted clock. Four markets times six full-history cases: baseline, Gao, double costs, five-minute entry delay preserving original signal, 25/35-minute window neighbors. Four additional 1m baseline checks from 2025 onward (same interval comparison comes from full-history ledgers). Total 28 attempts, all outcomes retained. Warmup ten days; first available prior close required, stale over four calendar days/nonpositive prices skip. Exact-time entry expiry and fail on missing held exit. Fixed clocks do not model early-close calendars; unadjusted rolls and nominal 5m bar completeness are limitations. Criteria reported descriptively: net profitability, stress resilience, yearly stability, trade counts, accounting and clock correctness.',
  groups: {}, presets: {},
};
save('campaign.json', campaign);
const catalog = await call('/discover', {});
assert(catalog.strategies.some(s => s.id === 'market-intraday-momentum'));
const state = await call('/state?view=summary');
const datasets = ['ES', 'NQ', 'MNQ', 'CL'].map(symbol => {
  const d = state.datasets.find(d => d.symbol === symbol);
  assert(d, `Missing ${symbol}`);
  return d;
});
campaign.unavailable_markets = ['MES', 'ZN', '6E'].filter(symbol => !state.datasets.some(d => d.symbol === symbol));
const base = d => ({ strategy_id: 'market-intraday-momentum', dataset_id: d.id,
  timeframe: '5m', session: 'new-york-rth', start: d.first.slice(0, 10), end: d.last.slice(0, 10),
  capital: 100000, fee: 2.5, slippage: 1, warmup_days: 10, timeout: 1800, stage: 'Exploratory',
  parameters: { signal_mode: 'rest-of-day', close_time: d.symbol === 'CL' ? '14:30' : '16:00', holding_minutes: '30', entry_delay_minutes: '0', minimum_move_bps: 0, contracts: 1 },
  criteria: 'Report positive net P&L, cost/delay resilience and yearly consistency; execution success does not award research validation.' });
async function launch(key, request) {
  if (campaign.groups[key]) return;
  request.hypothesis = `market-intraday-momentum-2026-09-17 | ${key} | ${campaign.protocol}`;
  const preview = await call('/preview', request);
  save(`preview-${key}.json`, preview);
  assert.equal(preview.jobs, 1);
  const existing = state.runs.filter(r => r.input.hypothesis === request.hypothesis);
  const runs = existing.length ? existing : await call('/runs', request);
  campaign.groups[key] = { request, ids: runs.map(r => r.id) };
  save('campaign.json', campaign);
  console.log(`Queued ${key}: ${runs[0].id}`);
}
for (const d of datasets) {
  const b = base(d);
  await launch(`${d.symbol}-baseline`, b);
  await launch(`${d.symbol}-gao`, { ...b, parameters: { ...b.parameters, signal_mode: 'first-half-hour' } });
  await launch(`${d.symbol}-cost-stress`, { ...b, fee: 5, slippage: 2 });
  await launch(`${d.symbol}-delay`, { ...b, parameters: { ...b.parameters, entry_delay_minutes: '5' } });
  for (const window of ['25', '35']) await launch(`${d.symbol}-window-${window}`, { ...b, parameters: { ...b.parameters, holding_minutes: window } });
  await launch(`${d.symbol}-minute-check`, { ...b, timeframe: '1m', start: '2025-01-01' });
  if (!campaign.presets[d.symbol]) {
    const preset = await call('/presets', { name: `Market intraday momentum | ${d.symbol} | last 30 minutes`, input: { ...base(d), hypothesis: campaign.protocol } });
    campaign.presets[d.symbol] = preset.id;
    save('campaign.json', campaign);
  }
}
// The full-history CL 5m baseline contains three trades with missing raw minute
// endpoints. Add an execution diagnostic, without changing the frozen signal.
const cl = datasets.find(d => d.symbol === 'CL');
await launch('CL-full-minute-confirmation', {
  ...base(cl), timeframe: '1m',
  criteria: 'Post-protocol execution diagnostic prompted by three missing raw minute endpoints in the CL 5m baseline. Same fixed default signal and full history; no parameter selection.',
});
const ids = Object.values(campaign.groups).flatMap(g => g.ids);
assert.equal(ids.length, 29);
for (;;) {
  const latest = await call('/state?view=summary');
  const runs = latest.runs.filter(r => ids.includes(r.id));
  save('run-status.json', runs);
  const active = runs.filter(r => ['Queued', 'Running'].includes(r.status));
  console.log(`${new Date().toISOString()} completed ${runs.length-active.length}/${ids.length}; ${active.filter(r=>r.status==='Running').map(r=>r.input.dataset.symbol+' '+r.input.parameters.signal_mode).join(', ')}`);
  if (!active.length) {
    campaign.completed_at = new Date().toISOString();
    save('campaign.json', campaign);
    console.log(JSON.stringify(runs.map(r => ({ id: r.id, status: r.status, symbol: r.input.dataset.symbol, pnl: r.result?.metrics?.net_pnl, error: r.error })), null, 2));
    break;
  }
  await new Promise(r => setTimeout(r, 15000));
}
