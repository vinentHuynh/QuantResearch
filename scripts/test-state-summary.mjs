import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { runSummaries } from '../server/stateSummary.ts';

const db = new DatabaseSync(':memory:');
try {
  db.exec('CREATE TABLE records(kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id))');
  const run = { id: 'complete', status: 'Succeeded', input: { parameters: { lookback: 60 } },
    notes: 'retain', result: { metrics: { net_pnl: 42, monthly: [{ month: '2026-01' }] },
      warnings: ['retain'], artifacts: [{ name: 'trades.csv' }],
      equity_preview: [{ equity: 42 }], trade_preview: [{ net_pnl: 42 }] } };
  const put = (r) => db.prepare('INSERT INTO records VALUES(?,?,?)').run('run', r.id, JSON.stringify(r));
  put(run);
  put({ id: 'queued', status: 'Queued', input: {}, error: 'retain' });
  const [queued, complete] = runSummaries(db);
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
  console.log('PASS: summary projection preserves records, metrics, inputs, warnings, order and queued states');
} finally { db.close(); }
