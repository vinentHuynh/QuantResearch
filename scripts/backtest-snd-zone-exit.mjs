import assert from 'node:assert/strict';
import { mkdirSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';

const folder = resolve('reports/snd-zone-exit-2026-09-17');
mkdirSync(folder, { recursive: true });
const save = (name, data) => writeFileSync(join(folder, name), JSON.stringify(data, null, 2));
async function call(path, body) {
  const response = await fetch('http://127.0.0.1:8001/api/workbench' + path,
    body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const result = await response.json();
  assert(response.ok, JSON.stringify(result));
  return result;
}
const campaign = existsSync(join(folder, 'campaign.json')) ? JSON.parse(readFileSync(join(folder, 'campaign.json'), 'utf8')) : {
  declared_at: new Date().toISOString(),
  protocol: 'Exploratory MNQ prior-1m RVOL SND comparison, 2024-01-01 through 2026-08-31, 60-day warmup, one contract, $100000 capital, $1.25 commission per side and one tick market/stop slippage; limit exits commission only. Compare baseline, opposing-zone touch, and close-inside; zone signals exit next minute open with slippage, never at historical touch price. Retain original stop/target/timed exits. All available active 1h/4h/daily opposing zones are eligible; preserve same-bar pre-invalidation zones. Full stateful reruns, continuous position/state between years, start flat and force final liquidation. All inspected history, no holdout claim or winner selection. Annual marked P&L, drawdown, trades, exit reasons and doubled-cost arithmetic stress reported for all attempts. Doubled costs cannot affect fixed-size decisions. Baseline uses identical new source with zone exits disabled.',
  groups: {},
};
save('campaign.json', campaign);
await call('/discover', {});
const state = await call('/state?view=summary');
const d = state.datasets.find(d => d.symbol === 'MNQ');
assert(d);
for (const mode of ['baseline', 'touch', 'close-inside']) {
  if (campaign.groups[mode]) continue;
  const request = { strategy_id: 'snd-zone-exit', dataset_id: d.id,
    timeframe: '1m', session: 'full-trading-day', start: '2024-01-01', end: '2026-08-31',
    capital: 100000, fee: 1.25, slippage: 1, warmup_days: 60, timeout: 3600, stage: 'Exploratory',
    parameters: { variant: 'phase7_prior_1m', contracts: 1, zone_exit: mode },
    hypothesis: `snd-zone-exit-2026-09-17 | ${mode} | ${campaign.protocol}`,
    criteria: 'Report every variant and year; assess P&L improvement, drawdown, costs and repeatability without relabeling history as holdout.' };
  const preview = await call('/preview', request);
  save(`preview-${mode}.json`, preview);
  assert.equal(preview.jobs, 1);
  const runs = state.runs.filter(r => r.input.hypothesis === request.hypothesis);
  const launched = runs.length ? runs : await call('/runs', request);
  campaign.groups[mode] = { request, ids: launched.map(r => r.id) };
  save('campaign.json', campaign);
  console.log(`Queued ${mode}: ${launched.map(r => r.id).join(', ')}`);
}
const completed = new Set();
while (completed.size < 3) {
  for (const [mode, group] of Object.entries(campaign.groups)) {
    if (completed.has(mode)) continue;
    const run = await call('/runs/' + group.ids[0]);
    if (!['Running', 'Queued'].includes(run.status)) {
      save(`run-${mode}.json`, run);
      completed.add(mode);
      console.log(`${mode}: ${run.status}; P&L ${run.result?.metrics?.net_pnl}`);
    }
  }
  if (completed.size < 3) await new Promise(r => setTimeout(r, 15000));
}
campaign.completed_at = new Date().toISOString();
save('campaign.json', campaign);
console.log('All three attempts terminal; analyze full ledgers next.');
