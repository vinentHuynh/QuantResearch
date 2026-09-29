import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync, createWriteStream } from 'node:fs';
import { resolve, join } from 'node:path';

const folder=resolve(process.argv[2]);
const campaign=JSON.parse(readFileSync(join(folder,'campaign.json'),'utf8'));
const home=join(folder,'isolated-workbench');
const api='http://127.0.0.1:8007/api/workbench';
const save=(name,data)=>writeFileSync(join(folder,name),JSON.stringify(data,null,2));
async function call(path,body) {
  const r=await fetch(api+path,body===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await r.json();assert(r.ok,JSON.stringify(data));return data;
}
const primary=await(await fetch('http://127.0.0.1:8001/api/workbench/state?view=summary')).json();
mkdirSync(join(home,'datasets'),{recursive:true});
writeFileSync(join(home,'.gitignore'),'# Local immutable research artifacts; summaries are saved in the parent report.\n*\n!.gitignore\n');
writeFileSync(join(home,'datasets/catalog.json'),JSON.stringify({datasets:primary.datasets,errors:[]}));
const log=createWriteStream(join(folder,'isolated-api.log'),{flags:'a'});
const server=spawn(process.execPath,['server/workbench.ts'],{windowsHide:true,env:{...process.env,WORKBENCH_HOME:home,WORKBENCH_PORT:'8007',WORKBENCH_CONCURRENCY:'2'}});
server.stdout.pipe(log,{end:false});server.stderr.pipe(log,{end:false});
const delay=ms=>new Promise(done=>setTimeout(done,ms));
for(let i=0;;i++) {
  try { await call('/state?view=summary');break; }
  catch(e) { if(i>=60||server.exitCode!==null) throw e;await delay(1000); }
}
const state=await call('/state?view=summary');
assert.equal(state.strategies.find(s=>s.id==='short-term-reversal-minute').file_hash,campaign.source.adapter);
assert.equal(state.datasets.find(d=>d.id===campaign.dataset.id).checksum,campaign.dataset.checksum);
assert.equal(state.evaluations.length,0,'Replica must start from an empty research ledger');
const preview=await call('/evaluations/preview',campaign.request);assert.equal(preview.jobs,18);
save('replication-preview.json',preview);
const evaluation=await call('/evaluations',campaign.request);
save('replication.json',{evaluation_id:evaluation.id,primary_evaluation_id:campaign.evaluation_id,home,api,started_at:new Date().toISOString(),reason:'Independent execution of the identical frozen protocol to avoid waiting behind unrelated batches. Primary evaluation remains preserved.'});
console.log(JSON.stringify({home,evaluation:evaluation.id,api}));
for(;;) {
  await delay(30000);
  const current=await call('/state?view=summary');
  const e=current.evaluations.find(e=>e.id===evaluation.id);
  save('replication-status.json',{evaluation:e,runs:current.runs});
  console.log(JSON.stringify({at:new Date().toISOString(),status:e.status,outcome:e.outcome,complete:current.runs.filter(r=>r.status==='Succeeded').length,runs:current.runs.filter(r=>r.status!=='Succeeded').map(r=>({id:r.id,status:r.status,fold:r.input.research.fold,role:r.input.research.role}))}));
  if(!['Running','Queued','Summarizing'].includes(e.status)) {
    save('replication-evaluation.json',await call('/evaluations/'+e.id));
    save('replication-runs.json',current.runs);
    console.log(JSON.stringify({complete:true,status:e.status,outcome:e.outcome,scenarios:e.result?.scenarios.map(s=>({name:s.name,outcome:s.outcome,net:s.metrics.net_pnl,dd:s.metrics.max_drawdown,trades:s.metrics.trades}))}));
    break;
  }
}
// Keep the separate API available for evidence inspection; Ctrl+C stops this process and its child.
await new Promise(resolve=>server.on('exit',resolve));
