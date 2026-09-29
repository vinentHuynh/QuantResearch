import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
const parent=resolve('reports/nq-reversal-development-2026-09-17');
const folder=join(parent,'shorter-hold-followup');mkdirSync(folder,{recursive:true});
const read=p=>JSON.parse(readFileSync(p,'utf8'));
const save=(name,value)=>writeFileSync(join(folder,name),JSON.stringify(value,null,2));
const api='http://127.0.0.1:8001/api/workbench';
async function call(path,body,method='POST'){
 const r=await fetch(api+path,body===undefined?undefined:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const value=await r.json();assert(r.ok,JSON.stringify(value));return value;
}
const original=read(join(parent,'evaluation.json'));
const base=original.candidates[0];
const parameters={...base.parameters,hold_sessions:1};
const request={name:'NQ reversal v1.1 | shorter-hold exploratory follow-up',
 base:{strategy_id:base.strategy.id,dataset_id:base.dataset.id,timeframe:base.timeframe,session:base.session,
 start:original.folds[0].train_start,end:original.folds.at(-1).test_end,parameters,capital:base.capital,fee:base.fee,
 slippage:base.slippage,warmup_days:base.warmup_days,timeout:1800,stage:'Exploratory'},
 train_days:365,test_days:365,folds:6,metric:'sharpe',min_trades:1,min_return:original.min_return,
 max_drawdown:original.max_drawdown,min_test_trades:original.min_test_trades,stress_multiple:original.stress_multiple,delay_bars:original.delay_bars,
 hypothesis:'Post-review exploratory revision after the frozen two-session strategy failed its risk/delay gates. The one-session neighbor had positive baseline P&L and 17.6% drawdown, motivating a bounded single follow-up with unchanged 20%/60-trade/positive-profit criteria, doubled costs and one daily-bar delay. Uses already inspected 2020-2026 history and has selection bias; not a fresh holdout. No further threshold/trend changes. Preserve original failed evaluation '+original.id+'.'};
const path=join(folder,'campaign.json');
const campaign=existsSync(path)?read(path):{declared_at:new Date().toISOString(),request,earlier_failed_evaluation:original.id};
save('campaign.json',campaign);
if(!campaign.evaluation_id){
 const discovery=await call('/discover',{});assert.equal(discovery.strategies.find(s=>s.id===base.strategy.id).file_hash,base.strategy.file_hash);
 save('preview.json',await call('/evaluations/preview',request));
 const evaluation=await call('/evaluations',request);campaign.evaluation_id=evaluation.id;save('campaign.json',campaign);
}
let evaluation;
for(;;){
 evaluation=await call('/evaluations/'+campaign.evaluation_id);
 console.log(`Shorter hold ${evaluation.status}: ${evaluation.runs.filter(r=>!['Running','Queued'].includes(r.status)).length}/${evaluation.jobs}`);
 if(['Succeeded','Failed','Canceled','Interrupted'].includes(evaluation.status))break;
 await new Promise(r=>setTimeout(r,10000));
}
save('evaluation.json',evaluation);assert.equal(evaluation.status,'Succeeded');
assert(evaluation.runs.every(r=>r.status==='Succeeded'&&r.result.warmup.status==='sufficient'));
const scenarios=evaluation.result.scenarios;
const working=scenarios.length===3&&scenarios.every(s=>s.outcome==='Meets criteria'&&s.metrics.net_pnl>0);
campaign.outcome=working?'Working — exploratory historical revision':'Needs review — shorter hold also failed declared checks';
if(!campaign.preset_id){const preset=await call('/presets',{name:`NQ reversal v1.1 | 1.25% / 1 session | ${working?'Working research':'Needs review'}`,input:{...request.base,start:original.folds[0].test_start,hypothesis:request.hypothesis,criteria:'All three scenarios: positive net return, max daily-close drawdown <=20%, >=60 trades'}});campaign.preset_id=preset.id;save('campaign.json',campaign);}
await call('/collective/refresh',{});
for(;;){const s=await call('/collective/status');if(!s.running){assert(!s.error,s.error);break;}await new Promise(r=>setTimeout(r,10000));}
const catalog=await call('/collective');
const same=(a,b)=>Object.keys(a).length===Object.keys(b).length&&Object.entries(a).every(([k,v])=>b[k]===v);
const matches=catalog.items.filter(i=>i.symbol==='NQ'&&i.name===base.strategy.name&&same(i.parameters,parameters));save('collective-matches.json',matches);
if(working)assert(matches.some(i=>i.working));
save('dashboard.json',await call('/dashboard?symbol=NQ'));
campaign.completed_at=new Date().toISOString();save('campaign.json',campaign);
const money=n=>n.toLocaleString('en-US',{maximumFractionDigits:0});
const lines=['# One-session follow-up','',`**${campaign.outcome}**`,'',request.hypothesis,'',
 'The rule is a daily RTH decline greater than 1.25%, above the 200-day SMA, then buy next RTH open for one open-to-open interval. Renewal is disabled, so each exit imposes a flat interval. No ATR, crash-size or weak-close filter. One contract, $100000, $2.50 fee and one tick slippage per side. No stop loss.','',
 '| Scenario | Net P&L | Max daily-close DD | Trades | Sharpe | Outcome |','|---|---:|---:|---:|---:|---|'];
for(const s of scenarios)lines.push(`| ${s.name} | $${money(s.metrics.net_pnl)} | ${(Math.abs(s.metrics.max_drawdown)*100).toFixed(1)}% | ${s.metrics.trades} | ${s.metrics.sharpe?.toFixed(2)} | ${s.outcome} |`);
lines.push('','## Individual annual folds','','| Dates | Baseline | Higher costs | Delayed entry |','|---|---:|---:|---:|');
for(const fold of evaluation.folds){const tests=fold.tests.map(id=>evaluation.runs.find(r=>r.id===id));lines.push(`| ${fold.test_start}–${fold.test_end} | ${tests.map(r=>'$'+money(r.result.metrics.net_pnl)).join(' | ')} |`);}
lines.push('','All 24 child runs have sufficient warmup. The native evaluator verifies artifact checksums, joins annual marked-equity paths without resetting drawdown peaks, and reconciles P&L. Each fold starts/ends flat; costs include liquidation. Neighbor results from the earlier search are baseline diagnostics, not stress evidence for every nearby parameter.','',
 'This post-review revision is exposed to selection bias. Historical profitability and an application label do not establish a prospective edge or live feasibility. One-day delay is a severe sensitivity test, not typical broker latency. Continuous rolls, missing sessions, overnight gaps, and daily-close rather than intraday risk measurement remain.','',
 'Earlier frozen failure and all 64 preceding runs: [parent report](../REPORT.md). [Complete native evaluation](evaluation.json).');
writeFileSync(join(folder,'REPORT.md'),lines.join('\n')+'\n');
console.log(JSON.stringify({outcome:campaign.outcome,scenarios:scenarios.map(s=>({name:s.name,net_pnl:s.metrics.net_pnl,max_drawdown:s.metrics.max_drawdown,trades:s.metrics.trades,outcome:s.outcome})),items:matches.map(i=>({id:i.id,working:i.working}))},null,2));
