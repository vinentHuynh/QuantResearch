import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadWorkbenchLayout } from '../../../server/layout.ts';

const folder = dirname(fileURLToPath(import.meta.url));
const api = 'http://127.0.0.1:8001/api/workbench';
const home = loadWorkbenchLayout().stateRoot;
const ledger = join(folder, 'campaign.json');
const save = (name, value) => writeFileSync(join(folder, name), JSON.stringify(value, null, 2));
const campaign = existsSync(ledger) ? JSON.parse(readFileSync(ledger, 'utf8')) : {created_at: new Date().toISOString(), runs: [], evaluations: []};
const modes = ['swing-1h', 'swing-4h', 'opening-15m', 'opening-30m', 'departure-swing', 'role-flip', 'rolling-20', 'round-100', 'daily-pivots', 'generic-prior-bar'];
const stage = process.argv[2] || 'development';
const detector = process.argv[3] || 'swing-1h';
assert(modes.includes(detector));
async function call(path, body) {
  const response = await fetch(api + path, body === undefined ? undefined : {method: 'POST', headers: {'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const result = await response.json(); assert(response.ok, JSON.stringify(result)); return result;
}
const base = {
  strategy_id: 'remaining-zone-failure', dataset_id: '3b9114199a2f6f0e51b70a63edc43de00940ae5df8d047b3aaa6aa8424aac9f1-v1',
  timeframe: '15m', session: 'full-trading-day', capital: 100000, fee: 2.5, slippage: 1, warmup_days: 30, timeout: 900,
  parameters: {detector, zone_half_width_atr: 0.10, swing_sides: 2},
  hypothesis: 'Remaining-zones-failure-2026-09-30 frozen bounded screen: seven families/nine detector candidates plus generic prior-bar benchmark, identical failure engine, no outcome-driven tuning. Retrospective NQ history.',
  criteria: 'PROTOCOL.md frozen gates; sparse is inconclusive, economic failure rejects the tested configuration. All attempts retained.',
};
assert(existsSync(join(folder, 'REVIEW.md')) && existsSync(join(folder, 'detection-review.json')));
await call('/discover', {});
let runs;
if (stage === 'evaluation') {
  assert(!campaign.evaluations.some(e=>e.detector === detector), 'Evaluation already exists');
  const request = {name:`Remaining zones | ${detector} | frozen 2025 evaluation`, base:{...base,start:'2024-01-01',end:'2025-12-31'},
    train_days:366,test_days:365,folds:1,metric:'net_pnl',min_trades:20,min_test_trades:40,min_return:0,max_drawdown:0.35,stress_multiple:2,delay_bars:0,sweep:{},hypothesis:base.hypothesis};
  save(`${detector}-evaluation-request.json`,request);
  save(`${detector}-evaluation-preview.json`,await call('/evaluations/preview',request));
  const launched=await call('/evaluations',request);campaign.evaluations.push({detector,id:launched.id});save('campaign.json',campaign);
  console.log(JSON.stringify({evaluation:launched.id,detector}));
  for (;;) {
    const evaluation=await call('/evaluations/'+launched.id);save(`${detector}-evaluation.json`,evaluation);
    console.log(JSON.stringify({detector,status:evaluation.status,outcome:evaluation.outcome,folds:evaluation.folds.map(f=>({training:f.training,tests:f.tests}))}));
    if (!['Running','Queued','Summarizing'].includes(evaluation.status)) {
      const ids=evaluation.folds.flatMap(f=>[...f.training,...f.tests]);runs=await Promise.all(ids.map(id=>call('/runs/'+id)));break;
    }
    await new Promise(done=>setTimeout(done,30000));
  }
} else {
  const key=stage==='development'?stage:`${stage}-${detector}`;
  assert(!campaign.runs.some(r=>r.stage===key),'Stage already exists; inspect ledger');
  let request;
  if(stage==='development')request={...base,start:'2022-01-01',end:'2024-12-31',sweep:{detector:modes}};
  else if(stage==='later')request={...base,start:'2026-01-01',end:'2026-09-28',stage:'Evaluation',development_end:'2025-12-31'};
  else if(stage==='later-stress')request={...base,start:'2026-01-01',end:'2026-09-28',stage:'Evaluation',development_end:'2025-12-31',fee:5,slippage:2};
  else if(stage==='nearby')request={...base,start:'2022-01-01',end:'2024-12-31',sweep:{zone_half_width_atr:[0.075,0.125]}};
  else throw new Error('Unknown stage');
  save(`${key}-request.json`,request);save(`${key}-preview.json`,await call('/preview',request));
  runs=await call('/runs',request);campaign.runs.push(...runs.map(r=>({stage:key,id:r.id,parameters:r.input.parameters})));save('campaign.json',campaign);
  console.log(JSON.stringify({launched:campaign.runs.filter(r=>r.stage===key)}));
  for (;;) {
    runs=await Promise.all(runs.map(r=>call('/runs/'+r.id)));save(`${key}-runs.json`,runs);
    console.log(JSON.stringify(runs.map(r=>({id:r.id,detector:r.input.parameters.detector,status:r.status,net:r.result?.metrics.net_pnl,trades:r.result?.metrics.trades}))));
    if(runs.every(r=>!['Running','Queued'].includes(r.status)))break;
    await new Promise(done=>setTimeout(done,30000));
  }
}
for(const run of runs){
  const destination=join(folder,'runs',run.id);mkdirSync(destination,{recursive:true});writeFileSync(join(destination,'record.json'),JSON.stringify(run,null,2));
  if(run.status!=='Succeeded')continue;
  const primary=join(home,'runs',run.id);
  assert(existsSync(join(primary,'manifest.json')),'Cannot locate canonical local artifacts; use API export instead');
  const manifest=JSON.parse(readFileSync(join(primary,'manifest.json'),'utf8'));assert.equal(manifest.run_id,run.id);
  copyFileSync(join(primary,'manifest.json'),join(destination,'manifest.json'));
  for(const item of manifest.artifacts){
    const bytes=readFileSync(join(primary,item.name));assert.equal(bytes.length,item.bytes);
    assert.equal(createHash('sha256').update(bytes).digest('hex'),item.checksum);writeFileSync(join(destination,item.name),bytes);
  }
  console.log(JSON.stringify({verified:run.id,detector:run.input.parameters.detector,artifacts:manifest.artifacts.length}));
}
