import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const folder = dirname(fileURLToPath(import.meta.url));
const api = 'http://127.0.0.1:8001/api/workbench';
const ledger = join(folder, 'campaign.json');
const save = (name, value) => writeFileSync(join(folder, name), JSON.stringify(value, null, 2));
const campaign = existsSync(ledger) ? JSON.parse(readFileSync(ledger, 'utf8')) : {
  created_at: new Date().toISOString(), runs: [], evaluations: [],
};
async function call(path, body) {
  const response = await fetch(api + path, body === undefined ? undefined : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  const result = await response.json();
  assert(response.ok, JSON.stringify(result));
  return result;
}
const mode = process.argv[2] || 'development';
const source = 'consolidation';
const base = {
  strategy_id: 'consolidation-box-failure',
  dataset_id: '3b9114199a2f6f0e51b70a63edc43de00940ae5df8d047b3aaa6aa8424aac9f1-v1',
  timeframe: '15m', session: 'full-trading-day', capital: 100000,
  fee: 2.50, slippage: 1, warmup_days: 30, timeout: 900,
  parameters: {box_bars: 8, max_range_atr: 2.0, zone_half_width_atr: 0.10},
  hypothesis: 'Frozen consolidation-box-failure-2026-09-30 protocol. Same first-armed-visit sweep/close-inside trigger and trade management; test frozen compact eight-bar box edges. Retrospective NQ history.',
  criteria: 'See preserved PROTOCOL.md. No retuning, all attempts retained; frozen stage gates.',
};
await call('/discover', {});
let runs;
if (mode === 'evaluation') {
  const request = {
    name: `Consolidation box failure | ${source} | frozen 2025 evaluation`,
    base: {...base, start: '2024-01-01', end: '2025-12-31'},
    train_days: 366, test_days: 365, folds: 1, metric: 'net_pnl',
    min_trades: 20, min_test_trades: 40, min_return: 0, max_drawdown: 0.35,
    stress_multiple: 2, delay_bars: 0, sweep: {}, hypothesis: base.hypothesis,
  };
  assert(!campaign.evaluations.some(e => e.source === source), 'Evaluation already launched');
  save(`${source}-evaluation-request.json`, request);
  save(`${source}-evaluation-preview.json`, await call('/evaluations/preview', request));
  const evaluation = await call('/evaluations', request);
  campaign.evaluations.push({source, id: evaluation.id}); save('campaign.json', campaign);
  console.log(JSON.stringify({evaluation: evaluation.id, source}));
  for (;;) {
    const detail = await call('/evaluations/' + evaluation.id);
    save(`${source}-evaluation.json`, detail);
    console.log(JSON.stringify({at: new Date().toISOString(), source, status: detail.status, outcome: detail.outcome}));
    if (!['Running', 'Queued', 'Summarizing'].includes(detail.status)) {
      const state = await call('/state?view=summary');
      runs = state.runs.filter(r => r.input.research?.evaluation_id === evaluation.id || r.input.research?.id === evaluation.id);
      // Fold lineage is authoritative if runtime research field names change.
      const ids = detail.folds.flatMap(f => [...f.training, ...f.tests].map(r => typeof r === 'string' ? r : r.run_id || r.id)).filter(Boolean);
      if (ids.length) runs = await Promise.all([...new Set(ids)].map(id => call('/runs/' + id)));
      save(`${source}-evaluation-child-runs.json`, runs);
      break;
    }
    await new Promise(done => setTimeout(done, 20000));
  }
} else {
  const key = mode === 'development' ? mode : `${mode}-${source}`;
  assert(!campaign.runs.some(r => r.stage === key), 'Stage already launched; inspect saved ledger instead');
  let request;
  if (mode === 'development') request = {...base, start: '2022-01-01', end: '2024-12-31',
    sweep: {}};
  else if (mode === 'later') request = {...base, start: '2026-01-01', end: '2026-09-28',
    stage: 'Evaluation', development_end: '2025-12-31'};
  else if (mode === 'later-stress') request = {...base, start: '2026-01-01', end: '2026-09-28',
    stage: 'Evaluation', development_end: '2025-12-31', fee: 5, slippage: 2};
  else if (mode === 'nearby') request = {...base, start: '2022-01-01', end: '2024-12-31',
    sweep: {zone_half_width_atr: [0.075, 0.125]}};
  else throw new Error('Unknown phase');
  save(`${key}-request.json`, request);
  save(`${key}-preview.json`, await call('/preview', request));
  runs = await call('/runs', request);
  for (const run of runs) campaign.runs.push({stage: key, id: run.id, parameters: run.input.parameters});
  save('campaign.json', campaign);
  console.log(JSON.stringify({launched: campaign.runs.filter(r => r.stage === key)}));
  for (;;) {
    runs = await Promise.all(runs.map(r => call('/runs/' + r.id)));
    save(`${key}-runs.json`, runs);
    console.log(JSON.stringify(runs.map(r => ({id: r.id, source: source, status: r.status, metrics: r.result?.metrics}))));
    if (runs.every(r => !['Running', 'Queued'].includes(r.status))) break;
    await new Promise(done => setTimeout(done, 20000));
  }
}
for (const run of runs || []) {
  const detail = await call('/runs/' + run.id);
  const destination = join(folder, 'runs', run.id); mkdirSync(destination, {recursive: true});
  writeFileSync(join(destination, 'record.json'), JSON.stringify(detail, null, 2));
  if (detail.status !== 'Succeeded') continue;
  const manifestResponse = await fetch(api + `/runs/${run.id}/artifact?name=manifest.json`);
  assert(manifestResponse.ok); const manifestBytes = Buffer.from(await manifestResponse.arrayBuffer());
  writeFileSync(join(destination, 'manifest.json'), manifestBytes);
  const manifest = JSON.parse(manifestBytes);
  for (const artifact of manifest.artifacts) {
    const response = await fetch(api + `/runs/${run.id}/artifact?name=${encodeURIComponent(artifact.name)}`);
    assert(response.ok); const bytes = Buffer.from(await response.arrayBuffer());
    assert.equal(createHash('sha256').update(bytes).digest('hex'), artifact.checksum);
    assert.equal(bytes.length, artifact.bytes);
    writeFileSync(join(destination, artifact.name), bytes);
  }
  console.log(JSON.stringify({verified: run.id, artifacts: manifest.artifacts.length}));
}
