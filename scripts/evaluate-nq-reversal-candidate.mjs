import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';

const api='http://127.0.0.1:8001/api/workbench';
const mode=process.argv[2] || 'status';
const folder=resolve(process.argv[3] || `reports/nq-reversal-5m-evaluation-${new Date().toISOString().replaceAll(':','-')}`);
const save=(name,value)=>writeFileSync(join(folder,name),JSON.stringify(value,null,2));
const read=name=>JSON.parse(readFileSync(join(folder,name),'utf8'));
const hash=path=>createHash('sha256').update(readFileSync(path)).digest('hex');
async function call(path,body,method='POST') {
  const r=await fetch(api+path,body===undefined?{signal:AbortSignal.timeout(120000)}:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(120000)});
  const value=await r.json();assert(r.ok,JSON.stringify(value));return value;
}
const compact=r=>({id:r.id,status:r.status,scenario:r.input.research?.scenario,role:r.input.research?.role,fold:r.input.research?.fold,error:r.error,
  offset:r.input.parameters.open_delay_minutes,fee:r.input.fee,slippage:r.input.slippage,
  metrics:r.result?.metrics&&{net_pnl:r.result.metrics.net_pnl,max_drawdown:r.result.metrics.max_drawdown,trades:r.result.metrics.trades}});
if(mode==='start') {
  mkdirSync(folder,{recursive:false});
  const state=await call('/state?view=summary');
  const strategy=state.strategies.find(s=>s.id==='short-term-reversal-minute');
  const dataset=state.datasets.find(d=>d.symbol==='NQ');
  const preflight=JSON.parse(readFileSync('reports/nq-reversal-minute-2026-09-17/preflight.json','utf8'));
  assert.equal(strategy.file_hash,preflight.adapter_checksum);
  assert.equal(hash(strategy.file),preflight.adapter_checksum);
  assert.equal(hash('strategies/short_term_reversal.py'),preflight.daily_helper_checksum);
  assert.equal(dataset.checksum,preflight.dataset_checksum);
  const baseline=state.runs.find(r=>r.id==='bcdf683c-7a24-4465-981c-ad1102e5a774');
  assert.equal(baseline.status,'Succeeded');assert.equal(baseline.input.parameters.open_delay_minutes,5);
  assert.equal(baseline.input.strategy.file_hash,strategy.file_hash);
  const protocol='Fixed five-minute NQ reversal candidate selected from already inspected timing research. Freeze decline 1.25%, SMA200, one-session long, no renewal, one flat session, five-minute entry tolerance, one contract and $100000. No further selection, sizing or threshold changes. Native six rolling 365-day test folds cover 2020-09-05 through 2026-09-03, with preceding 365-day training and one fixed candidate (minimum one training trade; selection metric net P&L). Every aggregated declared scenario must have positive net return, >=60 trades and <=20% minute-close drawdown. Native event evaluation supports baseline and doubled costs only, so mandatory supplemental continuous tests cover five-minute doubled costs and offsets four/six minutes at normal and doubled costs. All continuous cases, including the saved five-minute baseline, must satisfy the same gates. Four-minute offset is an earlier timing neighbor, six-minute offset models one-minute scheduling delay to both entry and exit. No generic event-order latency is claimed. Historical development validation only, not untouched holdout. Prior 09:30 campaign and daily-delay failures remain retained.';
  const base={strategy_id:strategy.id,dataset_id:dataset.id,start:'2019-09-06',end:'2026-09-03',timeframe:'1m',session:'full-trading-day',capital:100000,
    fee:2.5,slippage:1,warmup_days:600,timeout:3600,stage:'Exploratory',parameters:{...baseline.input.parameters,open_delay_minutes:5}};
  const request={name:'NQ reversal | fixed 09:35 candidate evaluation',base,train_days:365,test_days:365,folds:6,metric:'net_pnl',min_trades:1,min_return:.000001,max_drawdown:.2,min_test_trades:60,stress_multiple:2,delay_bars:0,hypothesis:protocol};
  const cases=[{key:'five-minute-higher-costs',offset:5,fee:5,slippage:2},
    {key:'six-minute-delay',offset:6,fee:2.5,slippage:1},{key:'six-minute-delay-higher-costs',offset:6,fee:5,slippage:2},
    {key:'four-minute-neighbor',offset:4,fee:2.5,slippage:1},{key:'four-minute-neighbor-higher-costs',offset:4,fee:5,slippage:2}];
  const campaign={declared_at:new Date().toISOString(),protocol,request,cases,reused_baseline:baseline.id,prior_failed_daily_evaluation:'3110fdcc-2ada-4576-91cd-cb5f9bba1015',
    prior_minute_runs:state.runs.filter(r=>r.input.strategy.id===strategy.id).map(compact),dataset:{id:dataset.id,checksum:dataset.checksum,through:dataset.last},source:{adapter:strategy.file_hash,daily_helper:preflight.daily_helper_checksum},runs:{}};
  save('campaign.json',campaign);save('state-before.json',state);save('baseline.json',baseline);save('prior-preflight.json',preflight);
  const preview=await call('/evaluations/preview',request);save('evaluation-preview.json',preview);
  assert.equal(preview.jobs,18);assert.equal(preview.folds[0].test_start,'2020-09-05');assert.equal(preview.folds.at(-1).test_end,'2026-09-03');
  for(const test of cases) {
    test.input={...base,start:'2020-09-05',parameters:{...base.parameters,open_delay_minutes:test.offset},fee:test.fee,slippage:test.slippage,
      criteria:'Positive net P&L; at least 60 trades; maximum minute-close drawdown <=20%. Fixed 09:35 candidate campaign requires every predeclared scenario to pass.',
      hypothesis:`${folder.split(/[\\/]/).at(-1)} | ${test.key} | ${protocol}`};
    const p=await call('/preview',test.input);assert.equal(p.jobs,1);save(`preview-${test.key}.json`,p);
  }
  save('campaign.json',campaign);
  const evaluation=await call('/evaluations',request);campaign.evaluation_id=evaluation.id;save('campaign.json',campaign);
  for(const test of cases) {
    const runs=await call('/runs',test.input);assert.equal(runs.length,1);
    campaign.runs[test.key]=runs[0].id;save('campaign.json',campaign);
    await call(`/runs/${runs[0].id}`,{tags:'nq-reversal-5m-evaluation,stress,'+test.key,notes:protocol},'PATCH');
  }
  console.log(JSON.stringify({folder,evaluation:campaign.evaluation_id,planned_native_jobs:18,new_continuous_tests:5,reused_baseline:campaign.reused_baseline},null,2));
} else {
  const campaign=read('campaign.json');
  const state=await call('/state?view=summary');
  const evaluation=state.evaluations.find(e=>e.id===campaign.evaluation_id);
  const ids=new Set([...Object.values(campaign.runs),campaign.reused_baseline]);
  const runs=state.runs.filter(r=>ids.has(r.id)||r.input.research?.evaluation_id===campaign.evaluation_id);
  const result={folder,evaluation:{id:evaluation.id,status:evaluation.status,outcome:evaluation.outcome,note:evaluation.note,error:evaluation.error,scenarios:evaluation.result?.scenarios.map(s=>({name:s.name,outcome:s.outcome,net_pnl:s.metrics.net_pnl,max_drawdown:s.metrics.max_drawdown,trades:s.metrics.trades}))},
    counts:Object.fromEntries(['Queued','Running','Succeeded','Failed','Interrupted','Timed out'].map(s=>[s,runs.filter(r=>r.status===s).length])),
    continuous:runs.filter(r=>ids.has(r.id)).map(compact),native:runs.filter(r=>r.input.research?.evaluation_id===campaign.evaluation_id).map(compact)};
  save('latest-status.json',result);console.log(JSON.stringify(result,null,2));
  if(mode==='collect') {
    assert(!['Running','Queued','Summarizing'].includes(evaluation.status));
    assert(runs.every(r=>!['Running','Queued','Summarizing'].includes(r.status)));
    save('evaluation.json',await call('/evaluations/'+campaign.evaluation_id));
    save('runs.json',runs);
  }
}
