import assert from 'node:assert/strict';
import {existsSync, mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {join, resolve} from 'node:path';

const folder=resolve('reports/rsi-research-2026-09-24');
mkdirSync(folder,{recursive:true});
const save=(name,value)=>writeFileSync(join(folder,name),JSON.stringify(value,null,2));
const read=name=>JSON.parse(readFileSync(join(folder,name),'utf8'));
const plus=(date,days)=>new Date(Date.parse(date)+days*86400000).toISOString().slice(0,10);
async function call(path,body,method='POST') {
  const response=await fetch('http://127.0.0.1:8001/api/workbench'+path,body===undefined?{}:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const value=await response.json(); assert(response.ok,JSON.stringify(value));return value;
}
const protocol='Frozen RSI follow-up: fixed corrected simple RSI(2), trend200/entry10/exit70, long one MNQ, $100000, full-session daily signals and next-open execution. Compare unchanged legacy. Main continuous history 2021-Jan-Aug2026; six annual fresh-start diagnostics; 2020Jun-Dec older slice; ES/NQ2012-Aug2026 transfer diagnostics. Base $2.50+1tick per side, stress $5+2ticks, delay one extra DAILY bar (not milliseconds). Six one-at-a-time neighbors: trend150/250, entry5/15, exit60/80 on2021-25 and2026; no selection or default changes from outcomes. Formal singleton evaluation has five365-day test folds ending2026Aug31, preceding365-day eligibility periods, min training trades0; no candidate selection. Historical reused data, no untouched holdout. Standalone MNQ research support requires positive continuous net/PF>1 in all3 scenarios, >=60 trades each, <=20% daily AND audited minute-mark drawdown, at least4/6 positive baseline calendar years, >=10 trades each year, and >=5/6 neighbors positive in BOTH2021-25 and2026 baseline (also disclose doubled-cost results). Formal each aggregated scenario requires positive return, >=60 trades, <=20% daily-closeDD. These are new standalone research gates, NOT a relaxation or pass of the prior failed improvement comparison. Keep all losses/failures. Audit concentration, holding, roll exposure and every artifact. Continuous unadjusted futures, no actual roll/margin/stop execution model; minute marks are diagnostics not rerun executions. No live-readiness or independent NQ/MNQ replication claim.';
let campaign;
const live=await call('/state?view=summary');
if(existsSync(join(folder,'campaign.json'))) campaign=read('campaign.json');
else {
  save('state-before.json',live);
  const cases=[];
  const fixed={trend_lookback:200,entry_rsi:10,exit_rsi:70,contracts:1};
  const scenarios=[{key:'base',fee:2.5,slippage:1,delay_bars:0},{key:'cost',fee:5,slippage:2,delay_bars:0},{key:'delay',fee:2.5,slippage:1,delay_bars:1}];
  const add=(key,variant,symbol,start,end,scenario,changes={},role='anchor')=>{
    const strategy_id=variant==='corrected'?'rsi2-reversion-corrected':'rsi2-reversion';
    const strategy=live.strategies.find(s=>s.id===strategy_id);assert(strategy);
    const dataset=live.datasets.find(d=>d.symbol===symbol);assert(dataset);
    const request={strategy_id,dataset_id:dataset.id,timeframe:'1d',session:'full-trading-day',start,end,capital:100000,warmup_days:600,timeout:1800,
      fee:scenario.fee,slippage:scenario.slippage,delay_bars:scenario.delay_bars,parameters:{...fixed,...changes},stage:'Exploratory',criteria:protocol,
      hypothesis:`rsi-research-2026-09-24 | ${key} | Frozen historical follow-up; ${role}; no prospective holdout.`};
    cases.push({key,variant,symbol,role,scenario:scenario.key,expected_adapter_hash:strategy.file_hash,request});
  };
  for(const variant of ['corrected','legacy']) {
    for(const scenario of scenarios)add(`MNQ-full-${variant}-${scenario.key}`,variant,'MNQ','2021-01-01','2026-08-31',scenario);
    add(`MNQ-earlier-${variant}-base`,variant,'MNQ','2021-01-01','2025-12-31',scenarios[0]);
    add(`MNQ-2020partial-${variant}-base`,variant,'MNQ','2020-06-01','2020-12-31',scenarios[0],{},'older partial diagnostic');
    for(let year=2021;year<=2026;year++)for(const scenario of variant==='corrected'?scenarios:[scenarios[0]])
      add(`MNQ-${year}-${variant}-${scenario.key}`,variant,'MNQ',`${year}-01-01`,year===2026?'2026-08-31':`${year}-12-31`,scenario,{},'annual fresh-start diagnostic');
    for(const symbol of ['ES','NQ'])for(const scenario of scenarios.slice(0,2))
      add(`${symbol}-long-${variant}-${scenario.key}`,variant,symbol,'2012-01-01','2026-08-31',scenario,{},'transfer diagnostic, different nominal risk');
  }
  const neighbors=[['trend150',{trend_lookback:150}],['trend250',{trend_lookback:250}],['entry5',{entry_rsi:5}],['entry15',{entry_rsi:15}],['exit60',{exit_rsi:60}],['exit80',{exit_rsi:80}]];
  for(const [name,changes]of neighbors) {
    add(`MNQ-neighbor-${name}-earlier-base`,'corrected','MNQ','2021-01-01','2025-12-31',scenarios[0],changes,'one-at-a-time sensitivity');
    for(const scenario of scenarios.slice(0,2))add(`MNQ-neighbor-${name}-recent-${scenario.key}`,'corrected','MNQ','2026-01-01','2026-08-31',scenario,changes,'one-at-a-time sensitivity');
  }
  assert.equal(cases.length,60);
  const end='2026-08-31',start=plus(end,-6*365+1);
  const evaluation_request={name:'RSI corrected | fixed MNQ daily | five-year historical evaluation',base:{...cases[0].request,start,end,hypothesis:protocol},
    train_days:365,test_days:365,folds:5,metric:'net_pnl',min_trades:0,min_return:0.000001,max_drawdown:.2,min_test_trades:60,stress_multiple:2,delay_bars:1,hypothesis:protocol};
  campaign={declared_at:new Date().toISOString(),protocol,fixed,scenarios,neighbors,cases,evaluation_request,runs:{},expected_jobs:80};
  save('campaign.json',campaign);
}
for(const c of campaign.cases)assert.equal(live.strategies.find(s=>s.id===c.request.strategy_id)?.file_hash,c.expected_adapter_hash,'Adapter changed since declaration');
if(!campaign.preview_complete) {
  for(const c of campaign.cases) {
    const p=await call('/preview',c.request);save(`preview-${c.key}.json`,p);assert.equal(p.jobs,1);
    assert(!(p.warmup??[]).some(w=>w.status==='insufficient'),`Insufficient warmup ${c.key}`);
  }
  const ep=await call('/evaluations/preview',campaign.evaluation_request);save('evaluation-preview.json',ep);assert.equal(ep.jobs,20);
  for(const f of ep.folds)for(const role of ['train','test']) {
    const p=await call('/preview',{...campaign.evaluation_request.base,start:f[`${role}_start`],end:f[`${role}_end`]});
    save(`preview-evaluation-${f.index}-${role}.json`,p);
    assert(p.warmup?.length&&p.warmup.every(w=>w.status==='sufficient'),'Evaluation warmup insufficient');
  }
  campaign.preview_complete=new Date().toISOString();save('campaign.json',campaign);
}
if(!campaign.evaluation_id) {
  const matches=live.evaluations.filter(e=>e.name===campaign.evaluation_request.name&&e.hypothesis===protocol);assert(matches.length<2);
  const evaluation=matches[0]??await call('/evaluations',campaign.evaluation_request);
  campaign.evaluation_id=evaluation.id;save('campaign.json',campaign);
  console.log('Evaluation '+evaluation.id);
}
for(const c of campaign.cases) {
  if(campaign.runs[c.key])continue;
  const matches=live.runs.filter(r=>r.input.hypothesis===c.request.hypothesis);assert(matches.length<2);
  const launched=matches.length?matches:await call('/runs',c.request);assert.equal(launched.length,1);
  campaign.runs[c.key]={id:launched[0].id};save('campaign.json',campaign);
  console.log(`Queued ${Object.keys(campaign.runs).length}/60 ${c.key}`);
}
let last='';
for(;;) {
  const state=await call('/state?view=summary');
  const ids=new Set(Object.values(campaign.runs).map(r=>r.id));
  const records=state.runs.filter(r=>ids.has(r.id)||r.input.research?.evaluation_id===campaign.evaluation_id);
  const evaluation=state.evaluations.find(e=>e.id===campaign.evaluation_id);
  const counts=Object.fromEntries([...new Set(records.map(r=>r.status))].map(s=>[s,records.filter(r=>r.status===s).length]));
  const status={at:new Date().toISOString(),evaluation:{id:evaluation.id,status:evaluation.status,outcome:evaluation.outcome,error:evaluation.error},counts,created:records.length,planned:80};
  save('progress.json',status);
  const summary=JSON.stringify({evaluation:evaluation.status,counts,created:records.length});
  if(summary!==last){console.log(summary);last=summary;}
  if(!['Queued','Running','Summarizing'].includes(evaluation.status)&&records.every(r=>!['Queued','Running'].includes(r.status))) {
    save('evaluation.json',await call('/evaluations/'+evaluation.id));
    for(const c of campaign.cases)save(`run-${c.key}.json`,await call('/runs/'+campaign.runs[c.key].id));
    const all=[];
    for(const r of records)all.push(await call('/runs/'+r.id));
    save('runs.json',all);campaign.completed_at=new Date().toISOString();campaign.actual_jobs=records.length;save('campaign.json',campaign);
    console.log('Campaign terminal; full artifact audit required.');break;
  }
  await new Promise(r=>setTimeout(r,10000));
}
