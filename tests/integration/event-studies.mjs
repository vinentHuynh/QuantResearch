import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { createEventStudies } from '../../server/eventStudies.ts';

const root = resolve('.');
const artifacts = resolve(process.env.WORKBENCH_ARTIFACTS || 'artifacts');
const testRuns = join(artifacts, 'test-runs');
const home = join(testRuns, `event-studies-validation-${Date.now()}`);
mkdirSync(home, { recursive: true });
const python = resolve('.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const fixture = `
import hashlib,json,sys
from pathlib import Path
import numpy as np
import pandas as pd
home=Path(sys.argv[1])
rng=np.random.default_rng(92)
index=pd.date_range('2025-01-06', '2025-02-01', freq='min', tz='UTC', inclusive='left', name='ts_event')
close=1000+np.cumsum(rng.normal(0,.35,len(index)))
opened=np.r_[close[0],close[:-1]]
frame=pd.DataFrame(dict(open=opened, high=np.maximum(opened,close)+rng.uniform(.01,.3,len(index)), low=np.minimum(opened,close)-rng.uniform(.01,.3,len(index)), close=close, volume=100),index=index)
path=home/'fixture.parquet'; frame.to_parquet(path)
dataset=dict(schema_version=2,id='event-study-fixture',symbol='TEST',path='fixture.parquet',checksum=hashlib.sha256(path.read_bytes()).hexdigest(),first=str(index[0]),last=str(index[-1]),warnings=['Synthetic software verification data; not market evidence.'])
(home/'datasets.json').write_text(json.dumps([dataset,dict(dataset,id='event-study-replica',symbol='TEST2')]))
`;
execFileSync(python, ['-c', fixture, home], { windowsHide: true });
const datasets = JSON.parse(readFileSync(join(home, 'datasets.json'), 'utf8'));
const app = createEventStudies(
  root,
  home,
  python,
  () => datasets,
  () => ({ ...process.env, WORKBENCH_HOME: home }),
);
const body = { name: 'Synthetic lifecycle verification', dataset_id: datasets[0].id, start: '2025-01-06', end: '2025-01-31', timeframe: '15m', session: 'full-trading-day', hypothesis: 'Software verification only; synthetic prices.', rules: { bootstrap_samples: 200 } };
async function finished(id) {
  const until = Date.now()+180000;
  while (Date.now() < until) {
    const record = app.read(id);
    const last = record.attempts.at(-1);
    if (last.status !== 'Running') { assert.equal(last.status, 'Succeeded', last.error); return record; }
    await new Promise(resolve => setTimeout(resolve, 300));
  }
  throw new Error('Study timed out');
}
try {
  await assert.rejects(app.preview({ ...body, rules: { future_lookahead: 1 } }), /Invalid rule/);
  await assert.rejects(app.preview({ ...body, rules: { return_bars: 100, cluster_bars: 50 } }), /Cluster length/);
  const preview = await app.preview(body);
  assert.equal(Object.keys(preview.plan.splits).length, 3);
  let study = app.create({ token: preview.token });
  assert.throws(() => app.create({ token: preview.token }), /expired/);
  assert.throws(() => app.launch(study.id, 'final'), /Freeze/);
  assert.throws(() => app.launch(study.id, 'validation'), /development/);
  assert.throws(() => app.freeze(study.id), /Complete/);
  app.launch(study.id, 'development');
  assert.throws(() => app.launch(study.id, 'development'), /active job/);
  study = await finished(study.id);
  const development = study.attempts.at(-1);
  const result = JSON.parse(readFileSync(app.artifact(study.id, development.id, 'result.json')));
  assert.equal(result.summaries.length, 4);
  assert.equal(result.recognizers.length, 8);
  assert.equal(new Set(result.recognizers.map(r => r.key)).size, 8);
  assert.equal(result.recognizers.reduce((sum, r) => sum+r.pattern.detected, 0), result.summaries.reduce((sum, s) => sum+s.pattern.detected, 0));
  assert.ok(result.samples.every(s => Object.keys(s.event.recognition).length > 0));
  assert.ok(result.samples.length > 0);
  assert.ok(result.summaries.some(row => row.matched > 0));
  assert.throws(() => app.launch(study.id, 'development'), /already complete/);
  assert.throws(() => app.artifact(study.id, development.id, '../study.json'), /Unknown/);
  app.review(study.id, { note: 'Synthetic lifecycle test: sampled chart data and confirmation ordering checked by assertions.' });
  for (const sample of result.samples) {
    assert.ok(sample.candles.every(c => Date.parse(c.timestamp) < Date.parse(preview.plan.splits.development.end)));
    assert.ok(sample.event.touch === null || sample.event.touch > sample.event.confirmation);
  }
  app.launch(study.id, 'validation');
  await finished(study.id);
  app.freeze(study.id);
  app.launch(study.id, 'final');
  study = await finished(study.id);
  assert.ok(study.final_opened_at);
  assert.throws(() => app.launch(study.id, 'final'), /already complete/);
  const replica = await app.preview({ ...body, dataset_id: datasets[1].id, parent_id: study.id, rules: { rejection_atr: 9 } });
  assert.equal(replica.protocol.rules.rejection_atr, study.protocol.rules.rejection_atr);
  assert.equal(replica.protocol.source_hash, study.protocol.source_hash);
  await assert.rejects(app.preview({ ...body, parent_id: study.id }), /another instrument/);
  const again = await app.preview(body);
  const second = app.create({ token: again.token });
  assert.deepEqual(second.prior_studies, [study.id]);
  const source = join(home, 'event-studies', second.id, 'source/workbench/event_study.py');
  writeFileSync(source, readFileSync(source, 'utf8') + '\n# tampered\n');
  assert.throws(() => app.launch(second.id, 'development'), /changed/);
  const exported = app.artifact(study.id, development.id, 'events.csv');
  writeFileSync(exported, readFileSync(exported, 'utf8')+'changed');
  assert.throws(() => app.artifact(study.id, development.id, 'events.csv'), /checksum changed/);
  // Restore the artifact so the preserved verification study remains inspectable.
  const text = readFileSync(exported, 'utf8'); writeFileSync(exported, text.slice(0, -7));
  mkdirSync(join(home, 'datasets'), { recursive: true });
  writeFileSync(join(home, 'datasets/catalog.json'), JSON.stringify({ datasets, errors: [] }));
  writeFileSync(join(home, 'checks.json'), JSON.stringify({ passed: true, study_id: study.id, home, summaries: result.summaries.map(s => ({ family: s.family, detected: s.pattern.detected, matched: s.matched })) }, null, 2));
  mkdirSync(testRuns, { recursive: true });
  writeFileSync(join(testRuns, 'event-studies-latest.json'), JSON.stringify({ home, study_id: study.id }));
  console.log(JSON.stringify({ passed: true, home, study_id: study.id, phases: study.attempts.map(a => `${a.phase}: ${a.status}`) }, null, 2));
} finally { app.stop(); }
