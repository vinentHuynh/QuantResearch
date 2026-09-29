import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const folder = resolve('reports/nq-reversal-development-2026-09-17');
mkdirSync(folder, { recursive: true });
const api = 'http://127.0.0.1:8001/api/workbench';
const write = (name, value) => writeFileSync(join(folder, name), JSON.stringify(value, null, 2));
const read = name => JSON.parse(readFileSync(join(folder, name), 'utf8'));
const pause = () => new Promise(r => setTimeout(r, 10000));
async function call(path, body, method = 'POST') {
  const response = await fetch(api + path, body === undefined ? undefined : { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const result = await response.json();
  assert(response.ok, JSON.stringify(result));
  return result;
}
const plan = {
  declared_at: new Date().toISOString(),
  hypothesis: 'NQ short-term reversal: larger selloffs within an uptrend may rebound over the next 1-5 sessions. Use bounded percentage/holding search, then one-factor filter checks on earlier history only. Prior full-history v1 results were inspected; subsequent periods are historical validation, not a fresh holdout.',
  development: { start: '2012-01-01', end: '2020-09-04', declines: [.5, .75, 1, 1.25, 1.5, 2], holds: [1, 2, 3, 5] },
  selection: 'Among successful development runs with positive net P&L, >=100 trades, profit factor >=1.15, daily-close drawdown <=25%, select highest daily Sharpe; ties preserve declared order. Test nine one-factor changes on the stage-one winner: cap=3/4%, ATR=.5/1, rebound exit, no renewal, trend=100/150/250. Use the best eligible refinement only if Sharpe improves by at least .05; otherwise keep the simpler stage-one winner. Stop if no eligible development candidate. Freeze before later-period tests; never select using validation or neighboring results.',
  validation: 'One native workbench evaluation: six consecutive 365-day test folds ending 2026-09-03, fixed chosen parameters, 365 preceding training days per fold (one candidate, no reselection). Baseline, doubled fees/slippage, and one additional daily-bar execution delay. Every joined scenario must have positive net return, max daily-close drawdown <=20%, >=60 trades. Report individual losing folds and concentration, even if aggregate criteria pass.',
  diagnostics: 'After freezing, six one-factor later-period neighbors: threshold x.8/x1.2, hold -1/+1 (hold=1 uses +1/+2), trend -50/+50. No reselection. One full-available-history replay for context. All discarded/failed candidates preserved. 64 planned runs: 24 main + 9 refinements + 24 native evaluation children + 6 neighbors + 1 full history.',
  economics: 'NQ 1 contract, $100000, New York RTH 09:30-16:00 daily bars, $2.50 fee and 1 tick slippage per side, 600-day warmup. Open-to-open holds include overnight risk; no stop loss or margin simulation. Full history starts at dataset beginning with flat initialization until SMA exists.',
};
const file = join(folder, 'campaign.json');
const campaign = existsSync(file) ? read('campaign.json') : { plan, groups: {}, selected: null };
write('campaign.json', campaign);
const catalog = await call('/discover', {});
const strategy = catalog.strategies.find(s => s.id === 'short-term-reversal');
assert.equal(strategy.version, '1.1.0');
campaign.adapter_hash ??= strategy.file_hash;
assert.equal(campaign.adapter_hash, strategy.file_hash, 'Do not change adapter during the campaign');
const state = await call('/state?view=summary');
const dataset = state.datasets.find(d => d.symbol === 'NQ');
const parameters = Object.fromEntries(Object.entries(strategy.parameters).map(([k,v]) => [k, v.default]));
const base = { strategy_id: strategy.id, dataset_id: dataset.id, timeframe: '1d', session: 'new-york-rth',
  start: campaign.plan.development.start, end: campaign.plan.development.end, stage: 'Exploratory',
  capital: 100000, fee: 2.5, slippage: 1, warmup_days: 600, timeout: 1800,
  parameters: { ...parameters, confluence: 'trend', direction: 'long-only' },
  hypothesis: campaign.plan.hypothesis, criteria: campaign.plan.selection };
async function launch(key, input, tag = 'development') {
  if (campaign.groups[key]) return campaign.groups[key];
  const request = { ...input, hypothesis: `nq-reversal-development-2026-09-17 | ${key} | ${input.hypothesis}` };
  const preview = await call('/preview', request);
  write(`preview-${key}.json`, preview);
  const previous = state.runs.filter(r => r.input.hypothesis === request.hypothesis);
  const runs = previous.length ? previous : await call('/runs', request);
  campaign.groups[key] = { ids: runs.map(r => r.id), request, tag };
  write('campaign.json', campaign);
  for (const r of runs) await call(`/runs/${r.id}`, { tags: `nq-reversal-v11,${tag}`, notes: campaign.plan.hypothesis }, 'PATCH');
  console.log(`Queued ${key}: ${runs.length}`);
  return campaign.groups[key];
}
const csv = path => {
  const [header, ...lines] = readFileSync(path, 'utf8').trim().split(/\r?\n/);
  const keys = header.split(',');
  return lines.filter(Boolean).map(line => Object.fromEntries(line.split(',').map((v,i) => [keys[i],v])));
};
function stats(run) {
  assert.equal(run.status, 'Succeeded', JSON.stringify({ id:run.id,status:run.status,error:run.error }));
  assert.equal(run.input.strategy.file_hash, campaign.adapter_hash);
  const dir = resolve('data/workbench/runs', run.id);
  const manifest = JSON.parse(readFileSync(join(dir, 'manifest.json'), 'utf8'));
  for (const a of manifest.artifacts) assert.equal(createHash('sha256').update(readFileSync(join(dir, a.name))).digest('hex'), a.checksum);
  const trades = csv(join(dir, 'trades.csv')), equity = csv(join(dir, 'equity.csv'));
  let gain=0, loss=0, wins=0, sum=0, peak=run.input.capital, dd=0;
  const yearly = {};
  for (const t of trades) { const p=+t.net_pnl; sum+=p; if(p>0){gain+=p;wins++;} else loss-=p; }
  for (const e of equity) { peak=Math.max(peak,+e.equity); dd=Math.max(dd,peak-+e.equity); const y=e.timestamp.slice(0,4); yearly[y]=(yearly[y]||0)+ +e.net_pnl; }
  assert(Math.abs(sum-manifest.metrics.net_pnl)<1e-5);
  return { id:run.id, status:run.status, parameters:run.input.parameters, input:run.input, metrics:manifest.metrics,
    profit_factor:loss?gain/loss:null, win_rate:trades.length?wins/trades.length:null, max_drawdown_dollars:dd,
    yearly_net_pnl:yearly, warmup:manifest.warmup, warnings:manifest.warnings };
}
async function waitRuns(ids, name) {
  const results = new Map();
  while(results.size<ids.length) {
    for(const id of ids.filter(id=>!results.has(id))) {
      const r=await call(`/runs/${id}`);
      if(!['Queued','Running'].includes(r.status)) { write(`run-${id}.json`,r); results.set(id,r); }
    }
    console.log(`${name}: ${results.size}/${ids.length} terminal`);
    if(results.size<ids.length) await pause();
  }
  return ids.map(id=>stats(results.get(id)));
}
const eligible = r => r.metrics.net_pnl>0 && r.metrics.trades>=100 && r.profit_factor>=1.15 && Math.abs(r.metrics.max_drawdown)<=.25 && Number.isFinite(r.metrics.sharpe);
const rank = rows => rows.filter(eligible).sort((a,b)=>b.metrics.sharpe-a.metrics.sharpe);
const grid = await launch('percentage-holding-grid', {...base, sweep:{ decline_pct:campaign.plan.development.declines, hold_sessions:campaign.plan.development.holds }});
const stageOne = await waitRuns(grid.ids,'Main grid');
write('stage-one.json',stageOne);
assert(rank(stageOne).length,'No candidate met the declared development gate; do not loosen it after seeing outcomes');
const first = rank(stageOne)[0];
campaign.stage_one_winner = first;
write('campaign.json',campaign);
console.log('Stage one winner '+JSON.stringify({parameters:first.parameters,metrics:first.metrics,profit_factor:first.profit_factor}));
const changes = [{max_decline_pct:3},{max_decline_pct:4},{min_atr_multiple:.5},{min_atr_multiple:1},
  {exit_on_rebound:true},{renew_on_signal:false},{trend_lookback:100},{trend_lookback:150},{trend_lookback:250}];
const refinementIds=[];
for(let i=0;i<changes.length;i++) {
  const g=await launch(`refinement-${i+1}`,{...base,parameters:{...first.parameters,...changes[i]}});
  refinementIds.push(...g.ids);
}
const refinements=await waitRuns(refinementIds,'Refinements');
write('refinements.json',refinements);
if(!campaign.selected) {
  const best=rank(refinements)[0];
  campaign.selected=best && best.metrics.sharpe >= first.metrics.sharpe+.05 ? best : first;
  campaign.frozen_at=new Date().toISOString();
  write('campaign.json',campaign);
  write('FROZEN_SELECTION.json',{declared_rule:campaign.plan.selection,frozen_at:campaign.frozen_at,selected:campaign.selected});
}
const chosen=campaign.selected.parameters;
console.log('Frozen parameters '+JSON.stringify(chosen));
// Calendar arithmetic deliberately derives six equal nonoverlapping test windows.
const day=86400000, last=Date.parse('2026-09-03T00:00:00Z');
const testStart=new Date(last-(6*365-1)*day).toISOString().slice(0,10);
const evaluationStart=new Date(Date.parse(testStart+'T00:00:00Z')-365*day).toISOString().slice(0,10);
assert(testStart>campaign.plan.development.end);
const evalRequest={name:'NQ reversal v1.1 | frozen 6-year validation',base:{...base,start:evaluationStart,end:'2026-09-03',parameters:chosen},
  train_days:365,test_days:365,folds:6,metric:'sharpe',min_trades:1,min_return:.000001,max_drawdown:.20,min_test_trades:60,
  stress_multiple:2,delay_bars:1,hypothesis:campaign.plan.hypothesis+' Parameters frozen using development through 2020-09-04 only. '+campaign.plan.validation};
if(!campaign.evaluation_id) {
  const preview=await call('/evaluations/preview',evalRequest); write('evaluation-preview.json',preview);
  assert.equal(preview.folds.at(-1).test_end,'2026-09-03');
  const prior=state.evaluations.find(e=>e.name===evalRequest.name && e.hypothesis===evalRequest.hypothesis);
  const evaluation=prior??await call('/evaluations',evalRequest);
  campaign.evaluation_id=evaluation.id;write('campaign.json',campaign);
  console.log('Queued native evaluation '+evaluation.id);
}
const near=[{decline_pct:+(chosen.decline_pct*.8).toFixed(3)},{decline_pct:+(chosen.decline_pct*1.2).toFixed(3)},
  {hold_sessions:chosen.hold_sessions>1?chosen.hold_sessions-1:2},{hold_sessions:chosen.hold_sessions>1?chosen.hold_sessions+1:3},
  {trend_lookback:chosen.trend_lookback-50},{trend_lookback:chosen.trend_lookback+50}];
const neighborIds=[];
for(let i=0;i<near.length;i++) {
  const group=await launch(`neighbor-${i+1}`,{...base,start:testStart,end:'2026-09-03',parameters:{...chosen,...near[i]},hypothesis:'Frozen local sensitivity; no reselection. '+campaign.plan.hypothesis},'sensitivity');
  neighborIds.push(...group.ids);
}
const full=await launch('full-history',{...base,start:dataset.first.slice(0,10),end:dataset.last.slice(0,10),parameters:chosen,hypothesis:'Full-history context, includes development and validation. '+campaign.plan.hypothesis},'context');
let evaluation;
for(;;) {
  evaluation=await call(`/evaluations/${campaign.evaluation_id}`);
  const terminal=evaluation.runs.filter(r=>!['Queued','Running'].includes(r.status)).length;
  console.log(`Evaluation ${evaluation.status}: ${terminal}/${evaluation.jobs} children terminal`);
  if(['Succeeded','Failed','Canceled','Interrupted'].includes(evaluation.status)) break;
  await pause();
}
write('evaluation.json',evaluation);
assert.equal(evaluation.status,'Succeeded',JSON.stringify(evaluation.error));
const evaluationRuns=evaluation.runs.map(stats);write('evaluation-run-stats.json',evaluationRuns);
const neighbors=await waitRuns(neighborIds,'Neighbors');write('neighbors.json',neighbors);
const history=(await waitRuns(full.ids,'Full history'))[0];write('full-history.json',history);
const scenarios=evaluation.result?.scenarios??[];
const working=scenarios.length===3&&scenarios.every(s=>s.outcome==='Meets criteria'&&s.metrics.net_pnl>0);
campaign.outcome=working?'Working — historical research':'Needs review — declared checks did not all pass';
campaign.neighbors_positive=neighbors.filter(r=>r.metrics.net_pnl>0).length;
if(!campaign.preset_id) {
  const preset=await call('/presets',{name:`NQ reversal v1.1 | ${chosen.decline_pct}% / ${chosen.hold_sessions} sessions | ${working?'Working research':'Needs review'}`,input:{...base,start:testStart,end:'2026-09-03',parameters:chosen,hypothesis:campaign.plan.hypothesis,criteria:campaign.plan.validation}});
  campaign.preset_id=preset.id;
}
write('campaign.json',campaign);
// Refresh imports the native evaluation and lets the app derive its own evidence label.
await call('/collective/refresh',{});
for(;;){const s=await call('/collective/status');if(!s.running){assert(!s.error,s.error);break;}await pause();}
const collective=await call('/collective');
const items=collective.items.filter(i=>i.symbol==='NQ'&&i.name===strategy.name&&JSON.stringify(i.parameters)===JSON.stringify(chosen));
write('collective-matches.json',items);
const dashboard=await call('/dashboard?symbol=NQ');write('dashboard.json',dashboard);
if(working)assert(items.some(i=>i.working),'Expected evaluation-driven Working item not found');
campaign.completed_at=new Date().toISOString();write('campaign.json',campaign);
const money=n=>n.toLocaleString('en-US',{maximumFractionDigits:0});
const lines=['# NQ reversal development', '',`**${campaign.outcome}**`, '',campaign.plan.hypothesis,'',
  `Selected using ${base.start}–${base.end}; frozen ${campaign.frozen_at}. Validated ${testStart}–2026-09-03 in six annual folds.`, '',
  '## Parameters', '', '```json',JSON.stringify(chosen,null,2),'```','',
  '## Frozen later-period scenarios', '', '| Scenario | Net P&L | Daily-close max DD | Trades | Sharpe | Outcome |','|---|---:|---:|---:|---:|---|'];
for(const s of scenarios)lines.push(`| ${s.name} | $${money(s.metrics.net_pnl)} | ${(Math.abs(s.metrics.max_drawdown)*100).toFixed(1)}% | ${s.metrics.trades} | ${s.metrics.sharpe?.toFixed(2)} | ${s.outcome} |`);
lines.push('','## Individual folds','','| Interval | Baseline | Higher costs | Delayed execution |','|---|---:|---:|---:|');
for(const f of evaluation.folds){const tests=f.tests.map(id=>evaluationRuns.find(r=>r.id===id));lines.push(`| ${f.test_start}–${f.test_end} | ${tests.map(r=>'$'+money(r.metrics.net_pnl)).join(' | ')} |`);}
lines.push('','## Development search — all candidates','','| Run | Decline | Hold | Extra settings | Net P&L | Sharpe | PF | Eligible |','|---|---:|---:|---|---:|---:|---:|---|');
for(const r of [...stageOne,...refinements])lines.push(`| ${r.id} | ${r.parameters.decline_pct}% | ${r.parameters.hold_sessions} | trend=${r.parameters.trend_lookback}; cap=${r.parameters.max_decline_pct}; ATR=${r.parameters.min_atr_multiple}; rebound=${r.parameters.exit_on_rebound}; renewal=${r.parameters.renew_on_signal} | $${money(r.metrics.net_pnl)} | ${r.metrics.sharpe?.toFixed(3)} | ${r.profit_factor?.toFixed(2)} | ${eligible(r)} |`);
lines.push('','## Neighboring settings — no reselection','','| Change | Net P&L | Max DD ($) | Trades |','|---|---:|---:|---:|');
neighbors.forEach((r,i)=>lines.push(`| ${JSON.stringify(near[i])} | $${money(r.metrics.net_pnl)} | $${money(r.max_drawdown_dollars)} | ${r.metrics.trades} |`));
lines.push('',`${campaign.neighbors_positive}/6 neighbors profitable. Full-history selected configuration: $${money(history.metrics.net_pnl)}, max daily-close dollar drawdown $${money(history.max_drawdown_dollars)}, ${history.metrics.trades} trades, profit factor ${history.profit_factor?.toFixed(2)}. Full history includes the development sample and is not validation.`, '',
  '## Limits', '',
  '- All history was previously inspected under v1. Selection here uses only the declared earlier interval, but none of this becomes a fresh or prospective holdout.',
  '- Working means the frozen aggregate baseline, doubled-cost and one-day delayed paths meet the stated historical criteria. It does not mean every year wins, nor fully tested/feasible or live approved.',
  '- One daily-bar delay is an intentionally severe timing test, not a realistic estimate of execution latency. Neighbor tests are uninterrupted runs; evaluation paths reset flat at annual fold boundaries.',
  '- Signal and entry filters do not cap losses. There is no intraday stop, target, margin or liquidation model. Overnight gaps, weekend exposure, missing sessions and continuous-contract roll jumps remain.',
  '- Drawdowns are daily-close marks, not intraday maximum losses. Fixed one-contract sizing on $100000 is not a sizing recommendation. Full-history replay uses early data to initialize and flags absent pre-start warmup.',
  '- Nine focused strategy tests, seven discovery/causality tests and production build passed before launching. Inputs, previews, source snapshots and checksum-verified/reconciled ledgers remain linked through the workbench.', '',
  'Machine-readable records: [campaign](campaign.json), [native evaluation](evaluation.json), [neighbors](neighbors.json), [full history](full-history.json), [app evidence](collective-matches.json).');
writeFileSync(join(folder,'REPORT.md'),lines.join('\n')+'\n');
console.log(JSON.stringify({outcome:campaign.outcome,parameters:chosen,scenarios:scenarios.map(s=>({name:s.name,...s.metrics,outcome:s.outcome})),neighbors_positive:campaign.neighbors_positive,collective:items.map(i=>({id:i.id,working:i.working,feasible:i.feasible}))},null,2));
