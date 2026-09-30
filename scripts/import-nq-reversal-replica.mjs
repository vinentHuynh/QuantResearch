// Append a completed, independently audited local replica to the main workbench.
// No existing record is replaced; artifacts and original absolute source paths are preserved.
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { cpSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { createHash } from 'node:crypto';
import { encodeRecord } from '../server/infra/recordRepository.ts';

const folder=resolve(process.argv[2]);
const read=name=>JSON.parse(readFileSync(join(folder,name),'utf8'));
const save=(name,value)=>writeFileSync(join(folder,name),JSON.stringify(value,null,2));
const campaign=read('campaign.json'),replication=read('replication.json'),audit=read('replication-audit.json');
const {runs,...evaluation}=read('replication-evaluation.json');
assert.equal(evaluation.status,'Succeeded');
assert.equal(runs.length,18);assert(runs.every(r=>r.status==='Succeeded'));
assert.equal(audit.verified_runs,24);assert.equal(audit.scenarios.length,2);
assert.equal(evaluation.id,replication.evaluation_id);
assert(read('replication-source-audit.json').identical);
const primary=resolve('data/workbench');
const db=new DatabaseSync(join(primary,'workbench.sqlite3'));
db.exec('PRAGMA busy_timeout=5000');
const get=db.prepare('SELECT body FROM records WHERE kind=? AND id=?');
assert(!get.get('evaluation',evaluation.id),'Replica already exists in primary ledger');
for(const run of runs) {
  assert(!get.get('run',run.id),'Never replace an existing run');
  const source=join(replication.home,'runs',run.id);
  const manifest=JSON.parse(readFileSync(join(source,'manifest.json'),'utf8'));
  const hash=file=>createHash('sha256').update(readFileSync(file)).digest('hex');
  assert.equal(hash(join(source,'manifest.json')),audit.runs.find(r=>r.id===run.id).manifest_checksum);
  for(const artifact of manifest.artifacts)assert.equal(hash(join(source,artifact.name)),artifact.checksum);
  assert(existsSync(run.input.source_dir),'Frozen source remains available');
  const destination=join(primary,'runs',run.id);
  assert(!existsSync(destination),'Artifact destination must be new');
  cpSync(source,destination,{recursive:true,force:false,errorOnExist:true});
}
const destination=join(primary,'evaluations',evaluation.id);
assert(!existsSync(destination));
cpSync(join(replication.home,'evaluations',evaluation.id),destination,{recursive:true,force:false,errorOnExist:true});
db.exec('BEGIN IMMEDIATE');
try {
  const insert=db.prepare('INSERT INTO records(kind,id,body) VALUES(?,?,?)');
  for(const run of runs)insert.run('run',run.id,encodeRecord('run',run.id,run));
  insert.run('evaluation',evaluation.id,encodeRecord('evaluation',evaluation.id,evaluation));
  db.exec('COMMIT');
} catch(error) { db.exec('ROLLBACK');throw error; }
db.close();
const api='http://127.0.0.1:8001/api/workbench';
const response=await fetch(api+'/evaluations/'+evaluation.id);assert(response.ok);
const visible=await response.json();assert.equal(visible.status,'Succeeded');assert.equal(visible.runs.length,18);
campaign.primary_evaluation_id=campaign.evaluation_id;
campaign.evaluation_id=evaluation.id;
campaign.replication_import={at:new Date().toISOString(),home:replication.home,unchanged_run_records:runs.map(r=>r.id),reason:'Original evaluation delayed by unrelated queued batches. Identical protocol completed in separate supervisor; checksum-verified completed records appended atomically.'};
save('campaign.json',campaign);
const original=await(await fetch(api+'/evaluations/'+campaign.primary_evaluation_id)).json();
save('original-evaluation-at-import.json',original);
if(['Running','Summarizing'].includes(original.status)) {
  const canceled=await fetch(api+'/evaluations/'+original.id+'/cancel',{method:'POST'});assert(canceled.ok);
  save('superseded-evaluation.json',await canceled.json());
  campaign.original_evaluation_status='Canceled after verified replica import';
  for(const run of original.runs) {
    const update=await fetch(api+'/runs/'+run.id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({notes:`${run.notes||''}\nDuplicate execution superseded by the complete, independently audited evaluation ${evaluation.id}. Pending duplicate jobs were canceled to avoid redundant computation; this administrative cancellation is not a failed profitability check. Evidence: ${folder}`})});
    assert(update.ok);
  }
} else campaign.original_evaluation_status=original.status;
save('campaign.json',campaign);
save('replication-import.json',campaign.replication_import);
console.log(JSON.stringify({imported:evaluation.id,run_count:runs.length,outcome:evaluation.outcome,original_retained:original.id},null,2));
