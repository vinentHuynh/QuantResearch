import assert from 'node:assert/strict';
import {existsSync, mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {join, resolve} from 'node:path';

const folder = resolve('reports/model-review-2026-09-24');
mkdirSync(folder, {recursive:true});
const save = (name, value) => writeFileSync(join(folder,name), JSON.stringify(value,null,2));
async function call(path, body) {
  const response = await fetch('http://127.0.0.1:8001/api/workbench'+path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data = await response.json();
  assert(response.ok, JSON.stringify(data));
  return data;
}
const protocol = 'Predeclared bounded review of all 14 existing runnable models, with one candidate per active model and an unchanged passive reference. Historical comparison on 2024-2025 and separately Jan-Aug2026, plus doubled fees/slippage for BOTH recent variants. These periods have already been inspected in earlier research; no untouched holdout or prospective claim. Same market, chart, session, one contract, $100000 and warmup within every pair. Base fees $2.50/side, slippage 1 tick/side; stress $5 and 2 ticks. ORB caps at one contract with $75 entry-risk budget. One new adapter corrects RSI zero-loss exits; legacy adapter preserved. All other candidates use existing declared parameters. Retain every failed, cancelled, zero-trade and losing attempt. No parameter search or changes after launch. A candidate is a historical improvement only if profitable in all three scenarios, with >=20 earlier and >=10 recent trades, at least 10% higher P&L/max dollar drawdown in each scenario, and no greater dollar drawdown in either later scenario. These gates do not award app evaluation or robustness milestones. Missing session exits, roll gaps, small samples and measured rather than intrabar drawdown remain limitations.';
const definitions = [
  {id:'buy-hold',symbol:'ES',timeframe:'1d',warmup:10,baseline:{},reason:'Passive exposure reference; no parameter optimization.'},
  {id:'moving-average',symbol:'ES',timeframe:'1d',warmup:600,baseline:{lookback:20},candidate:{lookback:40},reason:'A slower trend filter may reduce whipsaw and transaction costs.'},
  {id:'multi-speed-momentum',symbol:'MNQ',timeframe:'1d',warmup:900,baseline:{lookback:60},candidate:{lookback:90},reason:'Slower multi-horizon consensus may reduce turnover; retest current source with sufficient warmup.'},
  {id:'pine-daily-tsmom',symbol:'MNQ',timeframe:'15m',warmup:600,baseline:{sizing_mode:'Fixed contracts'},candidate:{fast_length:40},reason:'Slow the shortest daily vote without increasing exposure or changing other horizons.'},
  {id:'pine-overnight-block',symbol:'NQ',timeframe:'15m',warmup:10,baseline:{},candidate:{exit_hour:5},reason:'Exit one hour earlier to test whether the final overnight hour adds compensated risk.'},
  {id:'pine-overnight-drift',symbol:'ES',timeframe:'5m',warmup:180,baseline:{sizing_mode:'Fixed contracts'},candidate:{close_rule:'Long after down close'},reason:'Test overnight rebound following a down session against continuation following an up session.'},
  {id:'pine-tsmom-orb',symbol:'MNQ',timeframe:'5m',warmup:600,baseline:{risk_budget:75,maximum_contracts:1},candidate:{minimum_score:1},reason:'Require unanimous daily trend votes; missing-session flattening remains unresolved in both.'},
  {id:'rsi2-reversion',candidate_id:'rsi2-reversion-corrected',symbol:'MNQ',timeframe:'1d',warmup:600,baseline:{},candidate:{},reason:'Correct undefined RSI after consecutive gains so rebound exits can execute; retain original rolling RSI definition.'},
  {id:'short-term-reversal',symbol:'NQ',timeframe:'1d',session:'new-york-rth',warmup:600,baseline:{decline_pct:1.25,confluence:'trend',hold_sessions:1,renew_on_signal:false},candidate:{max_decline_pct:3},reason:'Avoid new entries after declines exceeding 3%; this is an entry filter, not a stop loss.'},
  {id:'short-term-reversal-minute',symbol:'NQ',timeframe:'1m',warmup:600,baseline:{open_delay_minutes:0},candidate:{open_delay_minutes:5},reason:'Test the previously studied 09:35 schedule against the adapter default 09:30; acknowledges prior timing selection.'},
  {id:'snd',symbol:'NQ',timeframe:'1m',warmup:60,baseline:{variant:'phase7_prior_5m'},candidate:{variant:'phase6'},reason:'Remove the prior-five-minute relative-volume gate while retaining Phase6 structural rules.'},
  {id:'snd-zone-exit',symbol:'MNQ',timeframe:'1m',warmup:60,baseline:{variant:'phase7_prior_1m',zone_exit:'close-inside'},candidate:{zone_exit:'baseline'},reason:'Test whether removing the opposing-zone exit recovers expectancy; earlier all exits lost money.'},
  {id:'vwap-reversion',symbol:'NQ',timeframe:'5m',session:'new-york-rth',warmup:10,baseline:{band:0.004},candidate:{band:0.005},reason:'Widen entry band from 0.4% to 0.5% to reduce weak fades; this does not repair overnight carry.'},
  {id:'market-intraday-momentum',symbol:'NQ',timeframe:'5m',session:'new-york-rth',warmup:10,baseline:{},candidate:{minimum_move_bps:10},reason:'Require a 0.10% move to avoid near-zero closing-window signals and their costs.'},
];
const periods = [
  {key:'earlier',start:'2024-01-01',end:'2025-12-31',fee:2.5,slippage:1},
  {key:'recent',start:'2026-01-01',end:'2026-08-31',fee:2.5,slippage:1},
  {key:'recent-double-cost',start:'2026-01-01',end:'2026-08-31',fee:5,slippage:2},
];
const campaignPath=join(folder,'campaign.json');
const catalog=await call('/discover',{});
const state=await call('/state?view=summary');
let campaign;
if(existsSync(campaignPath)) campaign=JSON.parse(readFileSync(campaignPath,'utf8'));
else {
  const cases=[];
  for(const d of definitions) for(const period of periods) for(const variant of d.candidate === undefined ? ['baseline'] : ['baseline','candidate']) {
    const strategy_id=variant==='candidate' ? d.candidate_id ?? d.id : d.id;
    const strategy=catalog.strategies.find(s=>s.id===strategy_id); assert(strategy, strategy_id);
    const dataset=state.datasets.find(s=>s.symbol===d.symbol); assert(dataset,d.symbol);
    const key=`${d.id}--${period.key}--${variant}`;
    const parameters={...Object.fromEntries(Object.entries(strategy.parameters).map(([k,v])=>[k,v.default])),...d.baseline,...(variant==='candidate'?d.candidate:{})};
    const request={strategy_id,dataset_id:dataset.id,timeframe:d.timeframe,session:d.session ?? strategy.required_session ?? 'full-trading-day',start:period.start,end:period.end,fee:period.fee,slippage:period.slippage,parameters,capital:100000,warmup_days:d.warmup,timeout:1800,stage:'Exploratory',criteria:protocol,hypothesis:`model-review-2026-09-24 | ${key} | ${d.reason} Historical reused data; fixed before campaign outcomes.`};
    cases.push({key,model:d.id,variant,period:period.key,reason:d.reason,expected_adapter_hash:strategy.file_hash,request});
  }
  assert.equal(cases.length,81);
  campaign={declared_at:new Date().toISOString(),protocol,definitions,cases,runs:{}};
  save('campaign.json',campaign);
}
for(const c of campaign.cases) {
  if(campaign.runs[c.key]) continue;
  const current=catalog.strategies.find(s=>s.id===c.request.strategy_id);
  assert.equal(current?.file_hash,c.expected_adapter_hash,'Source changed: declare a new campaign instead of silently resuming');
  const preview=await call('/preview',c.request);
  save(`preview-${c.key}.json`,preview); assert.equal(preview.jobs,1);
  const insufficient=(preview.warmup??[]).filter(x=>x.status==='insufficient');
  assert.equal(insufficient.length,0,JSON.stringify(insufficient));
  const existing=state.runs.filter(r=>r.input.hypothesis===c.request.hypothesis);
  assert(existing.length<2,'Duplicate recovery matches');
  const launched=existing.length?existing:await call('/runs',c.request);
  assert.equal(launched.length,1);
  campaign.runs[c.key]={id:launched[0].id}; save('campaign.json',campaign);
  console.log(`Queued ${Object.keys(campaign.runs).length}/81 ${c.key} ${launched[0].id}`);
}
const completed=new Map();
for(;;) {
  for(const c of campaign.cases) {
    if(completed.has(c.key))continue;
    const r=await call('/runs/'+campaign.runs[c.key].id);
    if(!['Queued','Running'].includes(r.status)) {
      completed.set(c.key,r); save(`run-${c.key}.json`,r);
      console.log(`Finished ${completed.size}/81 ${c.key}: ${r.status}; P&L ${r.result?.metrics?.net_pnl ?? 'n/a'}`);
    }
  }
  save('progress.json',{at:new Date().toISOString(),terminal:completed.size,total:campaign.cases.length});
  if(completed.size===campaign.cases.length)break;
  await new Promise(r=>setTimeout(r,10000));
}
campaign.completed_at=new Date().toISOString();save('campaign.json',campaign);
console.log('All 81 attempts terminal. Run the full-artifact analysis next.');
