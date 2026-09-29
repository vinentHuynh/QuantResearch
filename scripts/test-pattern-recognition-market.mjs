// Exercise all eight recognizers through the Workbench. Never opens the final split.
import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
const phase = process.argv[2] || 'development';
assert.ok(['development', 'validation'].includes(phase));
const base = 'http://127.0.0.1:8001/api/workbench/event-studies';
async function api(path = '', body) {
  const response = await fetch(base+path, body === undefined ? undefined : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const value = await response.json(); if (!response.ok) throw new Error(value.error); return value;
}
const datasets = JSON.parse(readFileSync('data/workbench/datasets/catalog.json', 'utf8')).datasets;
const dataset = datasets.find(d => d.symbol === 'NQ');
assert.ok(dataset);
const name = 'NQ - all eight pattern recognizers';
let study = (await api()).studies.find(s => s.protocol.name === name);
if (!study) {
  const preview = await api('/preview', { name, dataset_id: dataset.id, start: '2026-06-01', end: '2026-09-03', timeframe: '15m', session: 'full-trading-day',
    hypothesis: 'Test all eight specified recognizers. Primary comparisons remain supply/demand, order blocks, FVG and support/resistance versus matched controls. Directional breakdowns are descriptive; no parameter search.',
    prior_exposure: 'Development reuses the earlier NQ implementation-check interval. Recognizer-specific fixtures and explicit formation evidence were added. This is historical verification, not a new untouched holdout.' });
  study = await api('', { token: preview.token });
}
if (!study.attempts.some(a => a.phase === phase && ['Running', 'Succeeded'].includes(a.status))) study = await api(`/${study.id}/run`, { phase });
console.log(phase, study.id);
for (let i = 0; i < 600; i++) {
  study = await api('/'+study.id);
  const attempt = study.attempts.filter(a => a.phase === phase).at(-1);
  if (attempt.status !== 'Running') {
    assert.equal(attempt.status, 'Succeeded', attempt.error);
    assert.equal(study.final_opened_at, undefined);
    const result = await api(`/${study.id}/artifacts/${attempt.id}/result.json`);
    assert.equal(result.recognizers.length, 8);
    if (phase === 'development') assert.ok(result.recognizers.every(r => r.pattern.detected > 0));
    const home = resolve('reports', 'pattern-recognition', study.id);
    mkdirSync(home, { recursive: true });
    const report = { study_id: study.id, attempt_id: attempt.id, phase, status: attempt.status, final_opened: false,
      home, split: result.split, patterns: result.recognizers,
      primary_comparisons: result.summaries.map(s => ({ family: s.family, evidence: s.evidence, comparisons: s.comparisons })) };
    writeFileSync(join(home, `${phase}.json`), JSON.stringify(report, null, 2));
    writeFileSync('reports/pattern-recognition-latest.json', JSON.stringify({ home, study_id: study.id }));
    console.log(JSON.stringify({ study_id: study.id, phase, patterns: result.recognizers.map(r => ({ name: r.name, detected: r.pattern.detected, revisited: r.pattern.revisited, matched: r.matched })) }, null, 2));
    break;
  }
  if (i === 599) throw new Error('Market check timed out');
  await new Promise(done => setTimeout(done, 1000));
}
