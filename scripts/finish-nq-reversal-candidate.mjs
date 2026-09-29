import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
const folder=resolve(process.argv[2]);
const read=name=>JSON.parse(readFileSync(join(folder,name),'utf8'));
const save=(name,value)=>writeFileSync(join(folder,name),JSON.stringify(value,null,2));
const campaign=read('campaign.json'),evaluation=read('evaluation.json'),audit=read('audit.json'),runs=read('runs.json');
const byId=new Map(audit.runs.map(r=>[r.id,r]));
const continuous=[{key:'five-minute-baseline',id:campaign.reused_baseline},...campaign.cases.map(c=>({key:c.key,id:campaign.runs[c.key]}))].map(c=>({...c,...byId.get(c.id)}));
assert(continuous.every(r=>r.manifest_checksum),'All continuous results must be independently audited before publication');
assert.equal(audit.scenarios.length,2);
assert.equal(audit.verified_runs,24);
const nativePass=evaluation.status==='Succeeded'&&audit.scenarios.every(s=>s.outcome==='Meets criteria'&&s.net_pnl>0&&s.trades>=60&&Math.abs(s.max_drawdown)<=.2);
const passed=nativePass&&continuous.every(r=>r.passed);
const worstStart=audit.runs.filter(r=>r.research?.role==='Test').reduce((worst,r)=>!worst||Math.abs(r.max_drawdown)>Math.abs(worst.max_drawdown)?r:worst,null);
const freshStartNote=`Fresh-start diagnostic: worst individual annual test drawdown ${(Math.abs(worstStart.max_drawdown)*100).toFixed(2)}% on a new $100,000 account; the 20% declared gate applies to the combined history, not every starting date.`;
const verdict=passed?'PASS: fixed 09:35 candidate met the native evaluation and all predeclared supplemental gates.':'FAIL: fixed 09:35 candidate did not meet every predeclared gate.';
const cash=n=>'$'+n.toLocaleString('en-US',{maximumFractionDigits:0});
const lines=['# NQ short-term reversal: fixed 09:35 candidate','',`**${verdict}**`,'',campaign.protocol,'',
  '## Native annual-fold evaluation','',`Evaluation ID: ${evaluation.id}. All 18 jobs are retained; risk is calculated from the joined minute equity without resetting peaks at each fold.`,'',
  '| Scenario | Net profit | Max drawdown | Trades | Outcome |','|---|---:|---:|---:|---|',
  ...audit.scenarios.map(s=>`| ${s.name} | ${cash(s.net_pnl)} | ${(Math.abs(s.max_drawdown)*100).toFixed(2)}% | ${s.trades} | ${s.outcome} |`),'',
  'Annual outcomes are retained below. The frozen gates apply to the combined scenarios, not to each year separately.','',
  '| Test window | Baseline net | Higher-cost net | Baseline trades | Baseline fresh-start DD | Higher-cost fresh-start DD |','|---|---:|---:|---:|---:|---:|',
  ...evaluation.folds.map(f=>{const rows=f.tests.map(id=>byId.get(id));const base=rows.find(r=>r.research.scenario==='Baseline'),cost=rows.find(r=>r.research.scenario==='Higher costs');return `| ${f.test_start} to ${f.test_end} | ${cash(base.net_pnl)} | ${cash(cost.net_pnl)} | ${base.trades} | ${(Math.abs(base.max_drawdown)*100).toFixed(2)}% | ${(Math.abs(cost.max_drawdown)*100).toFixed(2)}% |`;}),'',
  '## Continuous-history timing and cost checks','',
  '| Case | Net profit | Max drawdown | Trades | Pass |','|---|---:|---:|---:|---|',
  ...continuous.map(r=>`| ${r.key} | ${cash(r.net_pnl)} | ${(Math.abs(r.max_drawdown)*100).toFixed(2)}% | ${r.trades} | ${r.passed?'Yes':'No'} |`),'',
  'Five-minute baseline reused its unchanged saved run; five supplemental cases and 18 native evaluation jobs were newly launched after API previews. Artifact checksums, preserved adapter/helper identity, complete trade accounting and minute equity drawdowns were independently checked. Annual scenario equity was independently rejoined and reconciled to the native evaluator. All six continuous cases executed the same 130 signals on identical entry/exit dates, at their declared 09:34, 09:35 or 09:36 New York times (see timing-comparison.json).','',
  ...(campaign.replication_import ? [`The original evaluation ${campaign.primary_evaluation_id} was delayed by unrelated shared-queue batches. The identical protocol was replayed in a separate workbench instance, using identical engine and adapter code. Its 18 completed runs and evaluation artifacts were independently verified and appended to the main app without replacing any existing record. Original evaluation status: ${campaign.original_evaluation_status}; all its prior results remain preserved. Cancellation of redundant queued work is administrative, not a failed strategy check. This is execution replication, not additional independent market evidence. See replication-import.json and replication-source-audit.json.`,''] : []),
  '## Interpretation','',
  'The original 09:30 campaign remains failed: baseline 20.60% drawdown, doubled costs 20.82%, one-minute offset 21.31%, and one-minute offset with doubled costs 21.55%, all above the 20% cap. The daily-adapter delayed case remains failed at 31.92%. This follow-up fixes the previously observed 09:35 candidate and does not revise those earlier outcomes.','',
  'This is historical development validation on an already inspected 2020-09-05 through 2026-09-03 sample. Choosing the five-minute candidate after seeing prior offsets introduces selection bias. It is not a new holdout, prospective evidence, or live-trading approval. The native event evaluator has no generic order-delay scenario; supplemental offsets shift scheduled entry AND exit, not broker queue latency. Continuous contract rolls, missing sessions, intraminute extremes and margin remain unmodeled. Daily RTH warmup is enforced within the adapter; the generic minute warmup field remains undeclared.','',
  'Returns are uneven: the continuous baseline lost $4,510 in calendar 2022, while partial 2026 contributes $66,900 (45.8% of total profit). Removing its ten best trades leaves $33,465 net profit. These are concentration diagnostics on the same inspected sample, not additional validation periods.','',
  'Fresh-start risk: the 2023-09-05 through 2024-09-03 fold drew down 25.04% at baseline costs and 25.12% at doubled costs when initialized with $100,000. It would fail a separate requirement that every new annual start stay below 20%. The frozen protocol instead assesses continuous combined equity, which retains prior gains as a buffer. Passing that protocol must not be represented as passing every possible starting date.','',
  'Files: [frozen protocol and run IDs](campaign.json), [native evaluation](evaluation.json), [independent audit](audit.json), [all run summaries](runs.json).'];
writeFileSync(join(folder,'REPORT.md'),lines.join('\n')+'\n');
const result={completed_at:new Date().toISOString(),verdict,passed,native_pass:nativePass,evaluation_id:evaluation.id,scenarios:audit.scenarios,continuous,fresh_start_diagnostic:{note:freshStartNote,max_drawdown:worstStart.max_drawdown,run_id:worstStart.id,passes_20pct_at_every_test_start:Math.abs(worstStart.max_drawdown)<=.2},report:join(folder,'REPORT.md')};
save('result.json',result);
async function call(path,body,method='POST') {
  const r=await fetch('http://127.0.0.1:8001/api/workbench'+path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await r.json();assert(r.ok,JSON.stringify(data));return data;
}
for(const row of continuous.filter(r=>r.id!==campaign.reused_baseline)) {
  const run=runs.find(r=>r.id===row.id);
  await call(`/runs/${row.id}`,{tags:[run.tags,row.passed?'case-passed':'checks-failed'].filter(Boolean).join(','),
    notes:`${campaign.protocol}\nThis individual case ${row.passed?'passed':'failed'} the fixed thresholds. ${verdict}\nEvidence: ${folder}`},'PATCH');
}
for(const id of evaluation.folds.flatMap(f=>f.tests)) {
  const run=runs.find(r=>r.id===id);
  await call(`/runs/${id}`,{tags:[run.tags,'nq-reversal-5m-evaluation'].filter(Boolean).join(','),
    notes:`${verdict}\nCriteria apply to joined test folds, not each individual year. ${passed?'Historical evaluation passed; prospective and broader feasibility evidence remain pending.':'Inspect the supplemental results before treating this configuration as a candidate.'}\n${freshStartNote}\nEvidence: ${folder}`},'PATCH');
}
if(passed&&!campaign.preset_id) {
  const preset=await call('/presets',{name:'NQ reversal | 09:35 | historical evaluation passed',input:{...campaign.request.base,start:'2020-09-05',hypothesis:campaign.protocol,criteria:'Positive net profit, at least 60 trades, maximum minute-close drawdown <=20%; fixed 09:35 validation report '+folder}});
  campaign.preset_id=preset.id;
}
campaign.completed_at=result.completed_at;campaign.outcome=verdict;save('campaign.json',campaign);
if(passed) result.refresh=await call('/collective/refresh',{});
save('result.json',result);
console.log(JSON.stringify({verdict,native_pass:nativePass,report:result.report,preset:campaign.preset_id,scenarios:audit.scenarios,continuous:continuous.map(r=>({case:r.key,net:r.net_pnl,dd:r.max_drawdown,trades:r.trades,passed:r.passed}))},null,2));
