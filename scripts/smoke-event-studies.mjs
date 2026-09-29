// One real-data development check. Never reviews, freezes or opens later splits.
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
const base = 'http://127.0.0.1:8001/api/workbench/event-studies';
async function api(path = '', body) {
  const response = await fetch(base+path, body === undefined ? undefined : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const value = await response.json(); if (!response.ok) throw new Error(value.error); return value;
}
const datasets = JSON.parse(readFileSync('data/workbench/datasets/catalog.json', 'utf8')).datasets;
const dataset = datasets.find(d => d.symbol === 'NQ');
assert.ok(dataset, 'NQ dataset is required for this smoke check');
const name = 'NQ pattern behaviour · implementation check';
const saved = (await api()).studies.find(s => s.protocol.name === name);
let study = saved;
if (!study) {
  const preview = await api('/preview', { name, dataset_id: dataset.id, start: '2026-06-01', end: '2026-09-03', timeframe: '15m', session: 'full-trading-day',
    hypothesis: 'Do mechanically defined zones, order blocks and FVGs predict return or rejection beyond matched controls and swing support/resistance?',
    prior_exposure: 'Historical NQ data already present in the research workbench and potentially inspected by prior strategy research. Development implementation check; later splits remain reserved, not certified fresh.' });
  study = await api('', { token: preview.token });
}
if (!study.attempts.some(a => a.phase === 'development' && ['Running', 'Succeeded'].includes(a.status))) study = await api(`/${study.id}/run`, { phase: 'development' });
console.log('Development study:', study.id);
for (let i = 0; i < 300; i++) {
  study = await api('/'+study.id);
  const attempt = study.attempts.at(-1);
  if (attempt.status !== 'Running') {
    assert.equal(attempt.status, 'Succeeded', attempt.error);
    assert.equal(study.final_opened_at, undefined);
    const result = await api(`/${study.id}/artifacts/${attempt.id}/result.json`);
    const summary = { study_id: study.id, status: attempt.status, final_opened: false, summaries: result.summaries.map(s => ({ family: s.family, detected: s.pattern.detected, matched: s.matched, ambiguous: s.pattern.counts.ambiguous })) };
    writeFileSync('reports/event-studies-real-data-check.json', JSON.stringify(summary, null, 2));
    console.log(JSON.stringify(summary, null, 2)); break;
  }
  if (i === 299) throw new Error('Development smoke check timed out');
  await new Promise(done => setTimeout(done, 1000));
}
