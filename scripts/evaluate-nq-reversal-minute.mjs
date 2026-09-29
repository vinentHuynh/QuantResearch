import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {existsSync,mkdirSync,readFileSync,writeFileSync,createReadStream} from 'node:fs';
import {join,resolve} from 'node:path';

const folder=resolve('reports/nq-reversal-minute-2026-09-17');mkdirSync(folder,{recursive:true});
const read=name=>JSON.parse(readFileSync(join(folder,name),'utf8'));
const save=(name,value)=>writeFileSync(join(folder,name),JSON.stringify(value,null,2));
const url='http://127.0.0.1:8001/api/workbench';
async function call(path,body,method='POST'){
 const r=await fetch(url+path,body===undefined?undefined:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const value=await r.json();assert(r.ok,JSON.stringify(value));return value;
}
const checksum=async path=>{const hash=createHash('sha256');for await(const chunk of createReadStream(path))hash.update(chunk);return hash.digest('hex');};
const file=join(folder,'campaign.json');
const campaign=existsSync(file)?read('campaign.json'):{
 declared_at:new Date().toISOString(),
 protocol:'Fixed NQ 1.25% RTH close-to-close selloff above SMA200; one session long, no renewal and one mandatory flat session. Recompute signals from immutable minute prices, not saved trade lists. Continuous scored 2020-09-05 through 2026-09-03, no annual resets. Full-trading-day 1m equity including overnight. Six predeclared cases: offsets 0/1/5/15 minutes with base costs, plus doubled costs at offsets 0/1. Both entries and exits use the same offset. Fixed one contract and $100000, fee $2.50 and one tick per side (double=$5 and two ticks). 600 warmup days with separately audited >=201 completed RTH days; native minute-count warmup is undeclared. Each case must have positive profit, >=60 trades and max one-minute-close drawdown <=20%. Baseline and all required stresses must pass for the campaign to pass. Do not select a better offset, change size/capital, or weaken gates after outcomes. Historical validation using previously inspected data; preserve all earlier failed daily-shift evidence. No authoritative holiday calendar, actual contract-roll execution, margin or intraminute stop model; no Fully tested & feasible claim.',
 cases:[{key:'baseline-0m',offset:0,fee:2.5,slippage:1},{key:'costs-0m',offset:0,fee:5,slippage:2},
        {key:'latency-1m',offset:1,fee:2.5,slippage:1},{key:'costs-latency-1m',offset:1,fee:5,slippage:2},
        {key:'latency-5m',offset:5,fee:2.5,slippage:1},{key:'latency-15m',offset:15,fee:2.5,slippage:1}],runs:{},
 prior_failed_evaluation:'3110fdcc-2ada-4576-91cd-cb5f9bba1015',
};save('campaign.json',campaign);
assert(existsSync(join(folder,'preflight.json')),'Finish the independent price-derived parity/warmup preflight first');
const preflight=read('preflight.json');
assert(preflight.completed_warmup_rth_days>=preflight.required_rth_days);
const catalog=await call('/discover',{});
const strategy=catalog.strategies.find(s=>s.id==='short-term-reversal-minute');
assert.equal(strategy.file_hash,preflight.adapter_checksum);
assert.equal(await checksum(resolve('strategies/short_term_reversal.py')),preflight.daily_helper_checksum);
const state=await call('/state?view=summary');
const dataset=state.datasets.find(d=>d.symbol==='NQ');assert.equal(dataset.checksum,preflight.dataset_checksum);
const base={strategy_id:strategy.id,dataset_id:dataset.id,start:'2020-09-05',end:'2026-09-03',timeframe:'1m',session:'full-trading-day',
 capital:100000,warmup_days:600,timeout:3600,stage:'Exploratory',parameters:{decline_pct:1.25,trend_lookback:200,open_delay_minutes:0,max_entry_lateness_minutes:5,contracts:1},
 criteria:'Fixed six-case campaign: positive net P&L, at least 60 trades, <=20% maximum minute-close drawdown in every declared case. No timing selection. Earlier daily-shift failure retained.'};
for(const test of campaign.cases){
 if(campaign.runs[test.key])continue;
 const concurrency=Math.max(1,Math.min(2,Number(process.env.NQ_MINUTE_CONCURRENCY)||1));
 for(;;){
  const current=await Promise.all(Object.values(campaign.runs).map(r=>call(`/runs/${r.id}`)));
  if(current.filter(r=>['Queued','Running'].includes(r.status)).length<concurrency)break;
  await new Promise(r=>setTimeout(r,10000));
 }
 const input={...base,parameters:{...base.parameters,open_delay_minutes:test.offset},fee:test.fee,slippage:test.slippage,
  hypothesis:`nq-reversal-minute-2026-09-17 | ${test.key} | ${campaign.protocol}`};
 const preview=await call('/preview',input);save(`preview-${test.key}.json`,preview);assert.equal(preview.jobs,1);
 const existing=state.runs.filter(r=>r.input.hypothesis===input.hypothesis);
 const runs=existing.length?existing:await call('/runs',input);assert.equal(runs.length,1);
 campaign.runs[test.key]={id:runs[0].id,input};save('campaign.json',campaign);
 await call(`/runs/${runs[0].id}`,{tags:`nq-reversal-minute,${test.key==='baseline-0m'?'baseline':'stress'}`,notes:campaign.protocol},'PATCH');
 console.log('Queued '+test.key+' '+runs[0].id);
}
const terminal=new Map();
while(terminal.size<campaign.cases.length){
 for(const [key,record]of Object.entries(campaign.runs))if(!terminal.has(key)){
  const r=await call(`/runs/${record.id}`);
  if(!['Queued','Running'].includes(r.status)){terminal.set(key,r);save(`run-${key}.json`,r);}
 }
 console.log(`${terminal.size}/${campaign.cases.length} terminal`);
 if(terminal.size<campaign.cases.length)await new Promise(r=>setTimeout(r,10000));
}
const csv=path=>{const [head,...lines]=readFileSync(path,'utf8').trim().split(/\r?\n/);const keys=head.split(',');return lines.filter(Boolean).map(line=>Object.fromEntries(line.split(',').map((v,i)=>[keys[i],v])));};
const results=[];
for(const test of campaign.cases){
 const run=terminal.get(test.key);
 if(run.status!=='Succeeded'){results.push({key:test.key,status:run.status,error:run.error,id:run.id});continue;}
 const directory=resolve('data/workbench/runs',run.id);const m=readFileSync(join(directory,'manifest.json'),'utf8');const manifest=JSON.parse(m);
 assert.equal(run.input.strategy.file_hash,preflight.adapter_checksum);
 for(const a of manifest.artifacts)assert.equal(await checksum(join(directory,a.name)),a.checksum);
 const trades=csv(join(directory,'trades.csv'));const pnl=trades.map(t=>+t.net_pnl);
 assert(Math.abs(pnl.reduce((a,b)=>a+b,0)-manifest.metrics.net_pnl)<1e-6);
 const profit=pnl.filter(v=>v>0).reduce((a,b)=>a+b,0),loss=-pnl.filter(v=>v<0).reduce((a,b)=>a+b,0);
 const parity=preflight.parity.find(p=>p.delay_minutes===test.offset);
 const expected=parity.net_pnl-(test.fee===5?15*parity.expected_trades:0);
 assert.equal(trades.length,parity.expected_trades);assert(Math.abs(expected-manifest.metrics.net_pnl)<1e-6,'Native execution must match independent audit at exact fixed settings');
 const pass=manifest.metrics.net_pnl>0&&manifest.metrics.trades>=60&&Math.abs(manifest.metrics.max_drawdown)<=.20;
 results.push({key:test.key,id:run.id,status:run.status,pass,metrics:manifest.metrics,profit_factor:loss?profit/loss:null,
  win_rate:pnl.filter(v=>v>0).length/pnl.length,native_warmup:manifest.warmup,completed_warmup_rth_days:preflight.completed_warmup_rth_days,
  warnings:manifest.warnings,source_hash:run.input.source_hash});
 await call(`/runs/${run.id}`,{tags:`nq-reversal-minute,${test.key==='baseline-0m'?'baseline':'stress'},${pass?'case-passed':'checks-failed'}`,
  notes:`${campaign.protocol}\nThis case ${pass?'passed':'failed'} the declared thresholds. Campaign acceptance requires all cases. Native 1m warmup is undeclared; independent preflight verifies ${preflight.completed_warmup_rth_days} completed RTH days before scoring. Earlier daily-shift failure remains retained.`},'PATCH');
}
save('results.json',results);
const passed=results.length===6&&results.every(r=>r.pass);
campaign.outcome=passed?'All minute campaign criteria passed; older daily-delay failure and feasibility limitations remain':'Needs review — minute campaign did not pass all declared checks';
if(!campaign.preset_id){const preset=await call('/presets',{name:'NQ reversal minute | 1.25% / 09:30 | '+(passed?'historical checks passed':'Needs review'),input:{...base,fee:2.5,slippage:1,hypothesis:campaign.protocol}});campaign.preset_id=preset.id;}
save('campaign.json',campaign);
await call('/collective/refresh',{});
for(;;){const refresh=await call('/collective/status');if(!refresh.running){assert(!refresh.error,refresh.error);break;}await new Promise(r=>setTimeout(r,10000));}
const index=await call('/collective');save('app-evidence.json',index.items.filter(i=>i.name===strategy.name&&i.symbol==='NQ'));
campaign.completed_at=new Date().toISOString();save('campaign.json',campaign);
const cash=n=>n.toLocaleString('en-US',{maximumFractionDigits:0});
const lines=['# NQ minute execution validation','',`**${campaign.outcome}**`,'',campaign.protocol,'',
 '| Case | Status | Net profit | Minute-close max DD | Trades | PF | Pass |','|---|---|---:|---:|---:|---:|---|'];
for(const r of results)lines.push(`| ${r.key} | ${r.status} | ${r.metrics?'$'+cash(r.metrics.net_pnl):'n/a'} | ${r.metrics?(Math.abs(r.metrics.max_drawdown)*100).toFixed(2)+'%':'n/a'} | ${r.metrics?.trades??'-'} | ${r.profit_factor?.toFixed(2)??'-'} | ${r.pass??false} |`);
lines.push('',`Independent preflight verified ${preflight.completed_warmup_rth_days} completed daily RTH bars before the scored start (201 required), exact 130-trade schedule parity at every offset, and unchanged data/helper identity. Native warmup remains explicitly undeclared rather than treating minute counts as daily observations.`, '',
 'Each successful native run recomputes signals from source prices and reconciles full trade P&L to minute equity. Complete CSV artifacts were checksum-verified. These are continuous six-year fixed-configuration validation runs, not annual walk-forward selections or a new holdout. No prior evaluation or failed case was removed.', '',
 'The app exposes the new `Short-term reversal - minute execution` adapter and a 09:30 preset. No Working/feasible status was manually assigned. Case-level success at 5 or 15 minutes cannot promote a predeclared 09:30 baseline that fails risk. The prior daily adapter and its full-day-shift failure remain visible.', '',
 '## Execution limits','',
 '- Signal data: completed 09:30–16:00 New York RTH OHLC. Orders: next selected-minute open following the scheduling minute at 09:30 plus the configured offset. Both entry and exit offset together. One session long, then one mandatory flat session; no renewal.',
 '- Missing scheduling minutes can produce late fills. Entry orders expire five minutes after the scheduled opening; exit orders expire at 16:00 and can be resubmitted at a subsequent opening window. Warmup orders are never carried into the scored period. Preflight found exact recorded entry/exit timestamps for all 130 researched trades; one zero-offset exit order expired on 2025-01-09 and correctly exited at the next observed RTH opening.',
 '- Explicit order lifetimes handle absent quotes without using future bars to schedule orders. This is not an authoritative exchange holiday calendar. Partial/holiday RTH days retain the original nominal 16:00 availability convention.',
 '- Equity marks include available overnight minutes in the 18:00–17:00 full-trading-day session. The maintenance break, exchange closures, absent data and unknown intraminute excursions are not sampled. Close-only marks also omit some instantaneous open/fee excursions; independent review retained those points.',
 '- Unadjusted continuous contracts are not a per-contract roll execution model. The prior review flagged three roll-exposed trades; excluding them was a diagnostic only. No stop loss, margin, liquidation, spread or queue-position model is present.',
 '- Minute Sharpe uses UTC-day closing equity; it need not equal the earlier RTH-close daily Sharpe. No risk-based sizing changes, capital increases or delay selection were used to force a pass.', '',
 'Evidence: [plan and run IDs](campaign.json), [preflight](preflight.json), [all results](results.json), [app import](app-evidence.json).');
writeFileSync(join(folder,'REPORT.md'),lines.join('\n')+'\n');
console.log(JSON.stringify({outcome:campaign.outcome,results:results.map(r=>({case:r.key,status:r.status,net:r.metrics?.net_pnl,drawdown:r.metrics?.max_drawdown,trades:r.metrics?.trades,pass:r.pass}))},null,2));
