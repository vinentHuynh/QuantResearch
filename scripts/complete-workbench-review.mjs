import { readFileSync, writeFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import assert from 'node:assert/strict';
const folder = 'reports/workbench-review-2026-09-16';
const api = async (path, body) => {
  const response = await fetch('http://127.0.0.1:8001/api/workbench' + path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  assert(response.ok);
  return response.json();
};
const campaign = JSON.parse(readFileSync(folder + '/campaign.json', 'utf8'));
const ids = new Set(Object.values(campaign.runs));
let state;
while (true) {
  state = await api('/state');
  const runs = state.runs.filter(r => ids.has(r.id));
  const counts = runs.reduce((a,r) => (a[r.status] = (a[r.status] || 0) + 1, a), {});
  console.log(new Date().toISOString(), JSON.stringify(counts));
  if (runs.length === ids.size && runs.every(r => !['Queued', 'Running'].includes(r.status))) break;
  await new Promise(resolve => setTimeout(resolve, 15000));
}
const before = JSON.parse(readFileSync(folder + '/state-before.json', 'utf8'));
for (const previous of before.runs) assert.deepEqual(state.runs.find(r => r.id === previous.id), previous);
writeFileSync(folder + '/preservation.json', JSON.stringify({ checked_at: new Date().toISOString(), prior_runs_unchanged: before.runs.length, campaign_runs: ids.size }, null, 2));
await api('/collective/refresh', {});
while (true) {
  const status = await api('/collective/status');
  if (!status.running) { assert(!status.error, status.error); break; }
  await new Promise(resolve => setTimeout(resolve, 5000));
}
async function run(args) {
  await new Promise((resolve, reject) => {
    const child = spawn(process.execPath, args, { stdio: 'inherit', windowsHide: true });
    child.on('error', reject);
    child.on('close', code => code === 0 ? resolve() : reject(new Error('Audit exit ' + code)));
  });
}
await run(['scripts/python-command.mjs', 'scripts/audit-workbench.py']);
await run(['scripts/analyze-collective-review.mjs']);
console.log('Campaign complete, prior runs preserved, evidence refreshed and full audits complete.');
