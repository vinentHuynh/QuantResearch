import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import { resolve, join } from 'node:path';

const api = 'http://127.0.0.1:8001/api/workbench';
const folder = resolve('reports/tsmom-orb-fix-2026-09-29');
mkdirSync(folder, { recursive: true });
const save = (name, value) => writeFileSync(join(folder, name), JSON.stringify(value, null, 2));
async function call(path, body) {
  const response = await fetch(api + path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const value = await response.json();
  assert(response.ok, JSON.stringify(value));
  return value;
}
const campaignPath = join(folder, 'campaign.json');
const campaign = existsSync(campaignPath) ? JSON.parse(readFileSync(campaignPath, 'utf8')) : {
  declared_at: new Date().toISOString(),
  purpose: 'Correct known holiday/session exit defect; frozen rules, no parameter optimization. Previously inspected 2024-2026 data is historical regression, not a fresh holdout.',
  criteria: 'Each recorded NQ year and MNQ combined baseline/cost/next-open case: positive net P&L, at least10 trades, marked max drawdown<=35%, zero trades held past the scheduled entry-session close, reconciled ledgers. All failures retained. Passing is historical evidence, not live execution validation.',
  calendar: 'Frozen NT CME US Index Futures ETH v5119, 2016-2026, known-date close minus5minutes or normal15:50, whichever earlier. Not a historical-vintage exchange archive.',
  groups: {},
};
save('campaign.json', campaign);
const catalog = await call('/discover', {});
assert.equal(catalog.strategies.find(s => s.id === 'pine-tsmom-orb')?.version, '1.1.0');
const state = await call('/state?view=summary');
const nq = state.datasets.find(d => d.symbol === 'NQ');
const mnq = state.datasets.find(d => d.symbol === 'MNQ');
assert(nq && mnq);
const parameters = { fast_length:20, medium_length:60, slow_length:120, annual_length:252,
  timezone:'America/New_York', minimum_score:.5, opening_start:570, opening_end:585,
  entry_start:585, entry_end:900, flatten_start:945, flatten_end:960, maximum_contracts:1,
  reward_risk:2, require_close_break:true, execution_timing:'close' };
function request(dataset, start, end, fee, slippage, timing='close') {
  return { strategy_id:'pine-tsmom-orb', dataset_id:dataset.id, timeframe:'5m', session:'full-trading-day',
    start, end, capital:100000, fee, slippage, warmup_days:600, timeout:3600, stage:'Evaluation',
    development_end:'2023-12-31', criteria:campaign.criteria,
    parameters:{...parameters, risk_budget:dataset.symbol==='NQ'?2500:250, execution_timing:timing} };
}
const cases = [];
for (const year of [2024,2025,2026]) {
  const start = `${year}-01-01`, end=year===2026?'2026-08-31':`${year}-12-31`;
  cases.push([`NQ-${year}-baseline`,request(nq,start,end,1.25,1)]);
  cases.push([`NQ-${year}-double-cost`,request(nq,start,end,2.5,2)]);
}
cases.push(['MNQ-baseline',request(mnq,'2024-01-01','2026-08-31',.62,1)]);
cases.push(['MNQ-double-cost',request(mnq,'2024-01-01','2026-08-31',1.24,2)]);
cases.push(['MNQ-next-open',request(mnq,'2024-01-01','2026-08-31',.62,1,'next-open')]);
cases.push(['MNQ-next-open-strict-expiry',request(mnq,'2024-01-01','2026-08-31',.62,1,'next-open')]);
campaign.execution_boundary_revision = 'Added exclusive entry/exit expiration boundaries after the first nine source snapshots were queued. MNQ-next-open-strict-expiry is the current next-open confirmation; the earlier attempt remains visible. Close-mode accounting does not read expiry fields.';
for (const [key, body] of cases) {
  if (campaign.groups[key]) continue;
  body.hypothesis = `tsmom-orb-calendar-fix-2026-09-29 | ${key} | ${campaign.purpose}`;
  const preview = await call('/preview',body);
  assert.equal(preview.jobs,1);
  save(`preview-${key}.json`,preview);
  const existing = state.runs.filter(r=>r.input.hypothesis===body.hypothesis);
  const runs = existing.length ? existing : await call('/runs',body);
  assert.equal(runs.length,1);
  campaign.groups[key] = { request:body, run_id:runs[0].id };
  save('campaign.json',campaign);
  console.log(`Queued ${key}: ${runs[0].id}`);
}
console.log('Historical regression runs queued; inspect saved campaign IDs for completion.');
