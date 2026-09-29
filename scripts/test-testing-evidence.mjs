import assert from 'node:assert/strict';
import { testingEvidence } from '../src/testingEvidence.ts';
import { reviewIssueKey, reviewPrefix } from '../src/testingReview.ts';
import { collectiveProgress, scorecardStage } from '../src/researchProgress.ts';

const strategy={id:'reversal',file_hash:'current'};
const run=(id,changes={})=>({id,status:'Succeeded',created_at:'2026-09-17T12:00:00Z',
 input:{strategy,dataset:{symbol:'NQ'},parameters:{},stage:'Exploratory',start:'2020-01-01',end:'2026-09-03',capital:100000,criteria:'',...changes.input},
 result:{metrics:{net_pnl:20000,net_return:.2,max_drawdown:-.1,trades:100,...changes.metrics}},...Object.fromEntries(Object.entries(changes).filter(([k])=>!['input','metrics'].includes(k)))});
const scenario=(name,changes={})=>({name,outcome:'Meets criteria',metrics:{net_pnl:20000,net_return:.2,max_drawdown:-.1,trades:100,...changes.metrics},...Object.fromEntries(Object.entries(changes).filter(([k])=>k!=='metrics'))});
const evaluation=(changes={})=>({id:'evaluation',created_at:'2026-09-17',status:'Succeeded',jobs:3,folds:[{training:[],tests:['base','cost','delay']}],scenarios:['Baseline','Higher costs','Delayed execution'],max_drawdown:.2,min_return:.01,min_test_trades:60,result:{scenarios:[scenario('Baseline'),scenario('Higher costs'),scenario('Delayed execution')]},...changes});
const children=()=>['base','cost','delay'].map((id,i)=>run(id,{input:{research:{evaluation_id:'evaluation',role:'Test',scenario:['Baseline','Higher costs','Delayed execution'][i]}}}));
const summarize=(runs,es=[],symbol='')=>testingEvidence(strategy,runs,es,symbol);
let checks=0;
let e=summarize([]);assert.equal(e.status,'Not tested');assert.equal(e.best,null);checks++;
e=summarize([run('pending',{status:'Queued',result:undefined}),run('busy',{status:'Running',result:undefined}),run('failed',{status:'Failed',error:'Missing input bars',result:undefined})]);
assert(e.inProgress);assert.equal(e.progress.done,1);assert.equal(e.progress.total,3);assert(e.issues.some(i=>i.reason==='Missing input bars'));checks++;
e=summarize(children(),[evaluation({outcome:'Meets criteria',result:{scenarios:[scenario('Baseline'),scenario('Higher costs'),scenario('Delayed execution',{outcome:'Does not meet criteria',metrics:{max_drawdown:-.3192}})]}})]);
assert.equal(e.status,'Backtested');assert(e.issues.some(i=>i.reason.includes('31.92% exceeds 20.00%')));assert.equal(e.best.tier,0);checks++;
e=summarize(children(),[evaluation()]);assert.equal(e.status,'Evaluation passed');assert.equal(e.best.run.id,'base');assert.equal(e.best.tier,3);checks++;
e=summarize(children(),[evaluation({result:{scenarios:[scenario('Baseline')]}})]);assert.equal(e.status,'Backtested');checks++;
e=summarize(children().slice(0,2),[evaluation()]);assert.equal(e.status,'Backtested');checks++;
e=summarize([run('old',{input:{strategy:{...strategy,file_hash:'old'}}})]);assert.equal(e.status,'Not tested');assert.equal(e.best,null);assert.equal(e.previousSource,1);checks++;
e=summarize([run('zero',{metrics:{trades:0}}),run('train',{input:{research:{role:'Training'}}}),run('invalid',{metrics:{net_return:NaN}})]);assert.equal(e.best,null);assert(e.issues.some(i=>i.title==='No trades'));checks++;
e=summarize([run('flagged',{tags:'checks-failed',metrics:{net_return:3},input:{criteria:'Max DD 20%',parameters:{delay:0}}}),run('unvalidated',{metrics:{net_return:10},input:{parameters:{delay:2}}}),run('passed',{tags:'stress,case-passed',input:{parameters:{delay:5}}})]);assert.equal(e.best.run.id,'passed');assert.equal(e.status,'Backtested');assert(e.issues.some(i=>i.reason.includes('Max DD 20%')));checks++;
e=summarize([run('es',{input:{dataset:{symbol:'ES'}},metrics:{net_return:10}}),run('nq')],[],'NQ');assert.equal(e.total,1);assert.equal(e.best.run.id,'nq');checks++;
e=summarize([run('zero-dd',{metrics:{max_drawdown:0,net_return:10}}),run('measured')]);assert.equal(e.best.run.id,'measured');checks++;
e=summarize(children().slice(0,1),[evaluation({status:'Running',jobs:12,result:undefined})]);assert.equal(e.progress.done,1);assert.equal(e.progress.total,12);assert(e.inProgress);checks++;
e=summarize(children(),[evaluation({result:{scenarios:[scenario('Baseline',{outcome:'Inconclusive',metrics:{trades:12}}),scenario('Higher costs'),scenario('Delayed execution')]}})]);assert(e.issues.some(i=>i.reason.includes('12 trades; 60 required')));checks++;
e=summarize([...children(),run('same-settings-new-window',{metrics:{net_return:20}})], [evaluation({result:{scenarios:[scenario('Baseline'),scenario('Higher costs'),scenario('Delayed execution',{outcome:'Does not meet criteria',metrics:{max_drawdown:-.4}})]}})]);
assert.equal(e.best.tier,0,'A standalone run cannot hide a failed matching configuration by changing dates');checks++;
const reviewed = (runs, evaluations = [], changes = {}) => {
 const record = {version:1,sourceHash:strategy.file_hash,reviewedAt:'2026-09-17T20:00:00Z',runIds:runs.map(r=>r.id),
  issueKeys:summarize(runs,evaluations).issues.map(reviewIssueKey),verdict:'Risk checks failed.',nextStep:'Validate revised risk rules.',...changes};
 return runs.map((r,i)=>i===0?{...r,notes:reviewPrefix+JSON.stringify(record)}:r);
};
const failedRuns=[run('failed-risk',{tags:'checks-failed',input:{criteria:'Max DD 20%'}})];
e=summarize(reviewed(failedRuns));assert.equal(e.status,'Backtested');assert(e.reviewComplete);assert.equal(e.reviewedIssues,1);assert.equal(e.best.tier,0);assert.equal(e.review,'Complete');checks++;
e=summarize(reviewed([run('zero',{metrics:{trades:0}})]));assert.equal(e.status,'Backtested');assert.equal(e.best,null);checks++;
e=summarize([...reviewed(failedRuns),run('new-result')]);assert.equal(e.status,'Backtested');assert(!e.reviewComplete);checks++;
e=summarize(reviewed(failedRuns).map(r=>({...r,input:{...r.input,criteria:'Updated risk limit'}})));assert.equal(e.status,'Backtested');assert.equal(e.reviewedIssues,0);checks++;
e=summarize(reviewed(failedRuns,[],{sourceHash:'old'}));assert.equal(e.status,'Backtested');assert(!e.savedReview);checks++;
e=summarize([run('failed-risk',{...failedRuns[0],notes:'Testing review: {bad json}',tags:'checks-failed,reviewed-2026-09-17'})]);assert.equal(e.status,'Backtested');checks++;
e=summarize(reviewed(children(),[evaluation()]),[evaluation()]);assert.equal(e.status,'Evaluation passed');assert(e.reviewComplete);assert.equal(e.best.tier,3);checks++;
e=summarize(reviewed(failedRuns).map(r=>({...r,ended_at:'2026-09-18T00:00:00Z'})));assert.equal(e.status,'Backtested');checks++;
const crossMarket=reviewed([run('es',{input:{dataset:{symbol:'ES'}}}),...failedRuns]);
e=summarize(crossMarket,[],'NQ');assert(e.reviewComplete);assert.equal(e.savedReview.runId,'es');
e=summarize(crossMarket,[],'CL');assert.equal(e.status,'Not tested');assert(!e.savedReview);checks++;
e=summarize(reviewed(children()),[evaluation({status:'Summarizing',result:undefined})]);assert(e.inProgress);assert(!e.reviewComplete);checks++;
// A failed symbol cannot erase a passing symbol, even after a saved review.
const mixed = [...children(), run('es-failure', {tags:'checks-failed', input:{dataset:{symbol:'ES'}}})];
e=summarize(reviewed(mixed,[evaluation()]),[evaluation()]);
assert.equal(e.status,'Evaluation passed');assert.equal(e.tone,'teal');assert.equal(e.passingConfigurations,1);assert.equal(e.failingConfigurations,1);
assert.equal(e.configurations.find(c=>c.symbol==='NQ').stage,2);assert.equal(e.configurations.find(c=>c.symbol==='ES').stage,1);
assert(e.reviewComplete);assert.equal(e.review,'Complete');assert(e.issues[0].scope.startsWith('ES'));checks++;
assert.equal(summarize(mixed,[evaluation()],'NQ').issues.length,0);
assert.equal(summarize(mixed,[evaluation()],'ES').status,'Backtested');checks++;
// Different settings on the same market also remain independent.
for (const input of [{parameters:{lookback:20}},{timeframe:'1h'},{session:'rth'},{source_hash:'different-snapshot'}]) {
 e=summarize([...children(),run('other-settings',{tags:'checks-failed',input})],[evaluation()]);
 assert.equal(e.stage,2);assert.equal(e.passingConfigurations,1);assert.equal(e.configurations.length,2);checks++;
}
e=summarize([...children(),run('same-settings',{tags:'checks-failed',input:{start:'2025-01-01',fee:100}})],[evaluation()]);
assert.equal(e.stage,1);assert.equal(e.passingConfigurations,0);assert.equal(e.failingConfigurations,1);checks++;
// Finishing jobs and completing review are not passing criteria.
e=summarize([run('summarizing',{status:'Summarizing',result:undefined})]);
assert(e.inProgress);assert.equal(e.stage,0);assert.equal(e.progress.done,0);assert.equal(e.summarizing,1);checks++;
e=summarize(children(),[evaluation({result:{scenarios:[scenario('Baseline')]}})]);
assert.equal(e.configurations[0].outcome,'Evaluation incomplete');assert.equal(e.failingConfigurations,0);checks++;
e=summarize(children(),[evaluation({scenarios:[],result:{scenarios:[]}})]);assert.equal(e.stage,1);checks++;
// Catalog dates are coverage, not validation. Legacy eligibility maps explicitly.
for (const tested of [true,false]) assert.equal(collectiveProgress({working:false,feasible:false,tested}).stage,1);
assert.equal(collectiveProgress({working:true,feasible:false}).stage,2);
assert.equal(collectiveProgress({working:true,feasible:true}).stage,3);
assert.equal(collectiveProgress({working:false,feasible:true}).stage,1);
assert.equal(collectiveProgress({working:true,feasible:true,benchmark:true}).label,'Benchmark');checks++;
assert.equal(scorecardStage({status:'Research candidate',scenarios:[{}]}),2);
assert.equal(scorecardStage({status:'Conditional',scenarios:[{}]}),1);
assert.equal(scorecardStage({status:'Retest required',scenarios:[{}]}),0);checks++;
console.log(`${checks} testing-evidence checks passed`);

if(process.argv.includes('--live')){
 const state=await(await fetch('http://127.0.0.1:8001/api/workbench/state?view=summary')).json();
 const s=state.strategies.find(s=>s.id==='short-term-reversal-minute');
 const real=testingEvidence(s,state.runs,state.evaluations,'NQ');
 assert.equal(real.status,'Backtested');assert(real.reviewComplete);assert.equal(real.reviewedIssues,4);assert.equal(real.total,6);assert.equal(real.issues.length,4);
 assert.equal(real.best.run.input.parameters.open_delay_minutes,5);assert.equal(real.best.run.result.metrics.net_pnl,146035);
 const daily=testingEvidence(state.strategies.find(s=>s.id==='short-term-reversal'),state.runs,state.evaluations,'NQ');
 assert(daily.issues.some(i=>i.reason.includes('31.92%')));
 console.log('Live NQ evidence: six cases, four failures, five-minute candidate; daily-delay risk failure retained.');
}
