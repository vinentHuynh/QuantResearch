import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { runSummaries } from '../server/stateSummary.ts';
import { encodeRecord } from '../server/infra/recordRepository.ts';

const db = new DatabaseSync(':memory:');
try {
  db.exec('CREATE TABLE records(kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id))');
  const run = { id: 'complete', status: 'Succeeded', input: { parameters: { lookback: 60 } },
    notes: 'retain', result: { metrics: { net_pnl: 42, monthly: [{ month: '2026-01' }] },
      warnings: ['retain'], artifacts: [{ name: 'trades.csv' }],
      equity_preview: [{ equity: 42 }], trade_preview: [{ net_pnl: 42 }] } };
  const put = (r, v2 = false) => db.prepare('INSERT INTO records VALUES(?,?,?)').run(
    'run', r.id, v2 ? encodeRecord('run', r.id, r) : JSON.stringify(r),
  );
  put(run);
  put({ id: 'queued', status: 'Queued', input: {}, error: 'retain' }, true);
  put({ id: 'domain-v2', schema_version: 2, status: 'Succeeded', input: {} });
  const [domain, queued, complete] = runSummaries(db);
  assert.equal(domain.schema_version, 2);
  assert.equal(domain.id, 'domain-v2');
  assert.equal(queued.status, 'Queued');
  assert.equal(queued.error, 'retain');
  assert.equal(queued.result, undefined);
  assert.deepEqual(complete.input, run.input);
  assert.deepEqual(complete.result.metrics, run.result.metrics);
  assert.deepEqual(complete.result.warnings, run.result.warnings);
  assert.deepEqual(complete.result.artifacts, run.result.artifacts);
  assert.equal(complete.result.equity_preview, undefined);
  assert.equal(complete.result.trade_preview, undefined);
  assert.deepEqual(JSON.parse(db.prepare("SELECT body FROM records WHERE id='complete'").get().body), run);
  const queuedRaw = JSON.parse(db.prepare("SELECT body FROM records WHERE id='queued'").get().body);
  assert.equal(queuedRaw.schema_version, 2);
  db.prepare('INSERT INTO records VALUES(?,?,?)').run(
    'run', 'malformed', JSON.stringify({ schema_version: 2, kind: 'view', id: 'malformed', body: {} }),
  );
  assert.throws(() => runSummaries(db), /Invalid protocol-v2 SQLite envelope/);
  console.log('PASS: summary projection preserves mixed records and rejects malformed v2 envelopes');
} finally { db.close(); }
