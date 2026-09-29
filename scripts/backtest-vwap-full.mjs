import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';

const folder = resolve('reports/vwap-full-2026-09-17');
mkdirSync(folder, {recursive:true});
const save = (name, value) => writeFileSync(join(folder,name), JSON.stringify(value,null,2));
async function call(path, body) {
  const response = await fetch('http://127.0.0.1:8001/api/workbench'+path, body === undefined ? undefined : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const value = await response.json(); assert(response.ok,JSON.stringify(value)); return value;
}
const state = await call('/state?view=summary');
const dataset = state.datasets.find(d=>d.symbol==='NQ'); assert(dataset);
const campaign = existsSync(join(folder,'campaign.json')) ? JSON.parse(readFileSync(join(folder,'campaign.json'),'utf8')) : {
  declared_at:new Date().toISOString(), groups:{},
  protocol:'NQ full available history, default 0.2% and previously used 0.4% bands on 5m/15m/30m. Fixed one contract, New York RTH, $100000 initial capital, $2.50 commission per side and one tick slippage per side, 60-day warmup, next-open fills. Both 5m bands receive doubled fee/slippage and one additional bar delay. 5m 0.3%/0.5% neighbor checks. Separate frozen 0.4% 5m evaluation: 2025 training with exactly one candidate, Jan 1-Sep 3 2026 test; return >=0, maximum drawdown <=35%, >=100 trades, doubled costs and one extra bar delay. Total 16 runs, no parameter selection using these results. All history is previously available/inspected; no untouched or prospective claim. Preserve every attempt including failures.'
};
save('campaign.json',campaign);
const base = {strategy_id:'vwap-reversion',dataset_id:dataset.id,timeframe:'5m',session:'new-york-rth',start:dataset.first.slice(0,10),end:dataset.last.slice(0,10),parameters:{band:.004,contracts:1},capital:100000,fee:2.5,slippage:1,warmup_days:60,timeout:1800,stage:'Exploratory',criteria:'Descriptive full-history results; no historical profitability promotion.'};
async function launch(key,patch) {
  if(campaign.groups[key])return;
  const request={...base,...patch,hypothesis:`vwap-full-2026-09-17 | ${key} | ${campaign.protocol}`};
  const preview=await call('/preview',request);save(`preview-${key}.json`,preview);assert(preview.jobs>0);
  const existing=state.runs.filter(r=>r.input.hypothesis===request.hypothesis);
  const runs=existing.length?existing:await call('/runs',request);
  assert.equal(runs.length,preview.jobs);
  campaign.groups[key]={request,ids:runs.map(r=>r.id)};save('campaign.json',campaign);
  console.log(`Queued ${key}: ${runs.length}`);
}
await launch('full-history',{timeframes:['5m','15m','30m'],sweep:{band:[.002,.004]}});
await launch('higher-costs',{fee:5,slippage:2,sweep:{band:[.002,.004]}});
await launch('delayed-execution',{delay_bars:1,sweep:{band:[.002,.004]}});
await launch('nearby-bands',{sweep:{band:[.003,.005]}});
if(!campaign.evaluation){
  const request={name:'vwap-full-2026-09-17 | frozen 0.4% recent evaluation',base:{...base,start:'2025-01-01'},sweep:{},train_days:365,test_days:246,folds:1,metric:'net_pnl',min_trades:0,min_return:0,max_drawdown:.35,min_test_trades:100,stress_multiple:2,delay_bars:1,hypothesis:campaign.protocol};
  const preview=await call('/evaluations/preview',request);save('evaluation-preview.json',preview);assert.equal(preview.jobs,4);
  const existing=state.evaluations.find(e=>e.name===request.name);
  const record=existing||await call('/evaluations',request);
  campaign.evaluation={id:record.id,request};save('campaign.json',campaign);console.log(`Queued recent evaluation ${record.id}`);
}
const ids=Object.values(campaign.groups).flatMap(g=>g.ids);
while(true){
  let terminal=0;
  for(const id of ids){const run=await call(`/runs/${id}`);save(`run-${id}.json`,run);if(!['Queued','Running'].includes(run.status))terminal++;}
  const evaluation=await call(`/evaluations/${campaign.evaluation.id}`);save('evaluation.json',evaluation);
  console.log(`${terminal}/${ids.length} full-history jobs terminal; evaluation ${evaluation.status}`);
  if(terminal===ids.length&&!['Queued','Running','Summarizing'].includes(evaluation.status))break;
  await new Promise(r=>setTimeout(r,15000));
}
campaign.completed_at=new Date().toISOString();save('campaign.json',campaign);
console.log(`Finished: ${folder}`);
