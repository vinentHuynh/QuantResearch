// Frozen carry-forward evaluation. Safe to resume: accepted launches are recovered by name.
import { chromium } from '@playwright/test';
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';

const folder = 'reports/strategy-potential-2026';
const api = 'http://127.0.0.1:8001/api/workbench';
const origin = 'http://127.0.0.1:5173';
const get = async path => {
  const r = await fetch(api + path); const b = await r.json();
  assert(r.ok, JSON.stringify(b)); return b;
};
const post = async (path, body) => {
  const r = await fetch(api + path, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
  const b = await r.json(); assert(r.ok, JSON.stringify(b)); return b;
};
await mkdir(folder, {recursive:true});
const previous = JSON.parse(await readFile('reports/strategy-optimization-2022-2024/campaign.json', 'utf8'));
const prior = JSON.parse(await readFile('reports/strategy-potential-2025/campaign.json', 'utf8'));
const ledger = `${folder}/campaign.json`;
const initial = await get('/state');
const campaign = existsSync(ledger) ? JSON.parse(await readFile(ledger,'utf8')) : {
  id:'potential-2026-v1', created_at:new Date().toISOString(), evaluations:{}, september:{}, regimes:{},
  prior_run_ids:initial.runs.map(r=>r.id),
  preexisting_2026_runs:initial.runs.filter(r=>r.input.start <= '2026-09-03' && r.input.end >= '2026-01-01').map(r=>r.id),
};
const plan = {
  training:'2025-01-01 through 2025-12-31, 365 calendar days; exactly one frozen candidate, no parameter selection',
  test:'2026-01-01 through 2026-08-31, 243 calendar days',
  september:'2026-09-01 through 2026-09-03; separate baseline runs starting flat, descriptive only, not appended to the main evaluation',
  parameters:'Original frozen 2022 selections for all nine NQ strategies; no retuning',
  criteria:'Positive net P&L for shortlist consideration; evaluation rule return >=0, drawdown <=35%, original minimum trade counts retained conservatively despite shorter period',
  scenarios:'Baseline and doubled fees/slippage; one additional bar delay for signal strategies only',
  sizing:'$100000 capital; fixed one contract; fee $1.25 per side, slippage one tick; ORB risk budget $2500 and maximum one contract',
  regimes:'Trend and volatility, 20 preceding native-timeframe bars, threshold at 2025 median, seed 42. Attribution only, no regime filter.',
  exits:'ORB baseline trade-ledger attribution, opening-range initial risk, exit reasons, gross/net R multiples, holding duration, monthly concentration. No exit-rule optimization.',
  limitations:'Historical carry-forward research; not certified untouched. Unadjusted continuous roll gaps, no margin liquidation, one-minute bracket assumptions, no event delay stress. September is only a partial month.',
};
if(campaign.plan) assert.deepEqual(campaign.plan, plan); else campaign.plan=plan;
const save = () => writeFile(ledger, JSON.stringify(campaign,null,2));
await save(); await writeFile(`${folder}/PLAN.json`, JSON.stringify(plan,null,2));
const browser = await chromium.launch();
const page = await browser.newPage({viewport:{width:1500,height:1080}});
page.setDefaultTimeout(60000);
const errors=[]; page.on('pageerror',e=>errors.push(e.message));
try {
  for(const config of previous.plan.strategies){
    if(campaign.evaluations[config.id]) continue;
    const name=`${campaign.id} | ${config.id}`;
    const existing=(await get('/state')).evaluations.filter(e=>e.name===name);
    assert(existing.length<=1);
    if(existing.length){campaign.evaluations[config.id]=existing[0].id; await save(); continue;}
    const seed=initial.runs.find(r=>r.id===previous.holdout[config.id]);
    assert.equal(seed.status,'Succeeded');
    const event=seed.input.strategy.execution_model==='event-v1';
    await page.goto(origin);
    await page.getByRole('button',{name:'Evaluation & Regimes',exact:true}).click();
    await page.getByRole('textbox',{name:'Starting run',exact:true}).fill(seed.id.slice(0,8));
    await page.getByRole('option',{name:new RegExp(seed.id.slice(0,8))}).click();
    const fields={
      'Evaluation name':name,'Research interval starts (UTC)':'2025-01-01','Research interval ends (UTC)':'2026-08-31',
      'Training calendar days':'365','Test calendar days':'243','Number of folds':'1',
      'Minimum training trades':'0','Minimum combined test trades':String(config.min),
      'Minimum test return (%)':'0','Maximum test drawdown (%)':'35','Stress cost multiplier':'2',
      'Candidate parameter grid (JSON)':'{}',
      'Evaluation hypothesis':`${plan.parameters}. ${plan.test}. ${plan.limitations}`,
    };
    for(const [label,value] of Object.entries(fields)) await page.getByLabel(label,{exact:true}).fill(value);
    if(event) assert(await page.getByLabel('Additional execution delay (bars)',{exact:true}).isDisabled());
    else await page.getByLabel('Additional execution delay (bars)',{exact:true}).fill('1');
    const pending=page.waitForResponse(r=>r.url().endsWith('/evaluations/preview')&&r.request().method()==='POST');
    await page.getByRole('button',{name:'Preview evaluation',exact:true}).click();
    const preview=await(await pending).json();
    assert.equal(preview.jobs,event?3:4);
    assert.equal(preview.folds[0].train_end,'2025-12-31');
    assert.equal(preview.folds[0].test_start,'2026-01-01');
    assert.equal(preview.folds[0].test_end,'2026-08-31');
    assert.deepEqual(preview.candidates[0].parameters,previous.selections[config.id].parameters);
    const response=page.waitForResponse(r=>r.url().endsWith('/api/workbench/evaluations')&&r.request().method()==='POST');
    await page.getByRole('button',{name:'Launch walk-forward',exact:true}).click();
    const launched=await response; const record=await launched.json();
    assert.equal(launched.status(),201,JSON.stringify(record));
    campaign.evaluations[config.id]=record.id; await save();
    console.log(`Launched ${config.id}: ${preview.jobs} jobs`);
  }
  for(const config of previous.plan.strategies){
    if(campaign.september[config.id]) continue;
    const hypothesis=`${campaign.id} September partial | ${config.id}. ${plan.september}. ${plan.limitations}`;
    const existing=(await get('/state')).runs.filter(r=>r.input.hypothesis===hypothesis);
    assert(existing.length<=1);
    if(existing.length){campaign.september[config.id]=existing[0].id; await save(); continue;}
    const seed=initial.runs.find(r=>r.id===previous.holdout[config.id]).input;
    const launched=await post('/runs',{
      ...seed,strategy_id:config.id,dataset_id:seed.dataset.id,
      start:'2026-09-01',end:'2026-09-03',stage:'Exploratory',development_end:'',criteria:'',hypothesis,
    });
    assert.equal(launched.length,1); campaign.september[config.id]=launched[0].id; await save();
  }
  for(;;){
    const state=await get('/state');
    const records=[...Object.values(campaign.evaluations).map(id=>state.evaluations.find(e=>e.id===id)),...Object.values(campaign.september).map(id=>state.runs.find(r=>r.id===id))];
    assert(records.every(Boolean));
    assert(!records.some(r=>['Failed','Interrupted','Canceled'].includes(r.status)),JSON.stringify(records.filter(r=>['Failed','Interrupted','Canceled'].includes(r.status))));
    console.log(`Evaluations and September runs: ${records.filter(r=>r.status==='Succeeded').length}/18 complete`);
    if(records.every(r=>r.status==='Succeeded')) break;
    await new Promise(r=>setTimeout(r,15000));
  }
  for(const [strategy,id] of Object.entries(campaign.evaluations)){
    campaign.regimes[strategy] ||= {};
    for(const feature of ['volatility','trend']){
      if(campaign.regimes[strategy][feature]) continue;
      const existing=(await get('/state')).regimes.filter(r=>r.evaluation_id===id&&r.feature===feature&&r.window===20&&r.quantile===0.5&&r.seed===42);
      assert(existing.length<=1);
      const task=existing[0]||await post(`/evaluations/${id}/regimes`,{feature,window:20,quantile:0.5,seed:42});
      campaign.regimes[strategy][feature]=task.id; await save();
    }
  }
  for(;;){
    const state=await get('/state');
    const studies=Object.values(campaign.regimes).flatMap(Object.values).map(id=>state.regimes.find(r=>r.id===id));
    assert(studies.every(Boolean));
    assert(!studies.some(r=>['Failed','Interrupted'].includes(r.status)));
    console.log(`Regimes: ${studies.filter(r=>r.status==='Succeeded').length}/18 complete`);
    if(studies.every(r=>r.status==='Succeeded')) break;
    await new Promise(r=>setTimeout(r,15000));
  }
  const state=await get('/state');
  const sourceHashes=new Set(); campaign.summary=[];
  for(const config of previous.plan.strategies){
    const e=await get(`/evaluations/${campaign.evaluations[config.id]}`);
    const september=state.runs.find(r=>r.id===campaign.september[config.id]);
    const studies=Object.fromEntries(['volatility','trend'].map(f=>[f,state.regimes.find(r=>r.id===campaign.regimes[config.id][f])]));
    const baseline=e.result.scenarios.find(s=>s.name==='Baseline');
    const training=e.runs.find(r=>r.input.research.role==='Training');
    const old=prior.summary.find(r=>r.strategy===config.id).scenarios.Baseline.metrics;
    for(const key of ['net_pnl','max_drawdown','trades','costs']) assert.equal(training.result.metrics[key],old[key],`${config.id}: 2025 economics changed`);
    for(const r of [...e.runs,september]){
      assert.equal(r.status,'Succeeded');
      assert.deepEqual(r.input.parameters,previous.selections[config.id].parameters);
      sourceHashes.add(r.input.source_hash);
    }
    for(const study of Object.values(studies)){
      assert(Math.abs(study.result.states.reduce((n,s)=>n+s.net_pnl,0)-baseline.metrics.net_pnl)<0.01);
      assert.equal(study.result.states.reduce((n,s)=>n+s.entry_count,0),baseline.metrics.trades);
      assert.equal(study.result.thresholds[0].calibrated_through,'2025-12-31');
    }
    const stress=e.result.scenarios.find(s=>s.name==='Higher costs');
    assert(Math.abs(stress.metrics.net_pnl-(baseline.metrics.net_pnl-baseline.metrics.costs))<0.01);
    await writeFile(`${folder}/${config.id}.json`,JSON.stringify({evaluation:e,september,studies},null,2));
    campaign.summary.push({strategy:config.id,evaluation_id:e.id,scenarios:e.result.scenarios.map(({name,metrics,outcome})=>({name,metrics,outcome})),september:{run_id:september.id,metrics:september.result.metrics}});
  }
  assert.equal(sourceHashes.size,1,'Campaign sources changed while launching');
  assert(campaign.prior_run_ids.every(id=>state.runs.some(r=>r.id===id)),'Earlier evidence was removed');
  assert.deepEqual(errors,[]);
  campaign.source_hash=[...sourceHashes][0]; campaign.completed_at=new Date().toISOString(); await save();
  console.log(JSON.stringify(campaign.summary.map(s=>({strategy:s.strategy,pnl:s.scenarios[0].metrics.net_pnl,dd:s.scenarios[0].metrics.max_drawdown,september:s.september.metrics.net_pnl})),null,2));
}catch(error){
  await writeFile(`${folder}/error.txt`,String(error));
  await page.screenshot({path:`${folder}/failure.png`,timeout:10000}).catch(()=>{});
  throw error;
}finally{await browser.close();}
