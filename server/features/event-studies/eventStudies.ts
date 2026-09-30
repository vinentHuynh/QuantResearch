import { spawn, type ChildProcess } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync, readdirSync, renameSync, copyFileSync } from 'node:fs';
import { join } from 'node:path';

type Dataset = { id: string; symbol: string; path: string; checksum: string; first: string; last: string };
type Rules = Record<string, number>;
type Protocol = { name: string; hypothesis: string; prior_exposure: string; dataset: Dataset; start: string; end: string; timeframe: string; session: string; rules: Rules; source_hash: string; parent_id?: string };
type Plan = { bars: number; splits: Record<string, { start: string; end: string; bars: number; offset: number }> };
type Attempt = { id: string; phase: string; status: string; created_at: string; ended_at?: string; error?: string };
type Study = { id: string; created_at: string; protocol: Protocol; plan: Plan; protocol_hash: string; attempts: Attempt[]; frozen_at?: string; reviewed_at?: string; review_note?: string; final_opened_at?: string; prior_studies: string[] };
const defaults: Rules = { atr_period: 14, base_bars: 3, base_atr: 1, departure_bars: 3, departure_atr: 1.5, ob_lookback: 5, breakout_bars: 20, swing_bars: 2, level_width_atr: .25, return_bars: 50, reaction_bars: 20, rejection_atr: 1, failure_atr: .25, seed: 1729, bootstrap_samples: 1000, match_caliper: 1, cluster_bars: 100 };
const limits: Record<string, [number, number]> = { atr_period: [2, 100], base_bars: [2, 10], base_atr: [.1, 5], departure_bars: [1, 10], departure_atr: [.1, 10], ob_lookback: [2, 20], breakout_bars: [5, 100], swing_bars: [1, 10], level_width_atr: [.01, 3], return_bars: [5, 200], reaction_bars: [2, 100], rejection_atr: [.1, 10], failure_atr: [.01, 5], seed: [0, 2147483647], bootstrap_samples: [200, 5000], match_caliper: [.1, 3], cluster_bars: [20, 2000] };
const integers = new Set(['atr_period', 'base_bars', 'departure_bars', 'ob_lookback', 'breakout_bars', 'swing_bars', 'return_bars', 'reaction_bars', 'seed', 'bootstrap_samples', 'cluster_bars']);
const files = ['workbench/event_study.py', 'workbench/dataset_reference.py', 'strategy_engine/data.py', 'strategy_engine/sessions.py'];
const hash = (value: string | Buffer) => createHash('sha256').update(value).digest('hex');
const now = () => new Date().toISOString();

export function createEventStudies(root: string, state: string, python: string, datasets: () => Dataset[], environment: () => NodeJS.ProcessEnv) {
  const home = join(state, 'event-studies');
  mkdirSync(home, { recursive: true });
  const active = new Map<string, ChildProcess>();
  const previews = new Map<string, { protocol: Protocol; plan: Plan; folder: string; expires: number }>();
  const folder = (id: string) => {
    if (!/^[a-f0-9-]{36}$/.test(id)) throw new Error('Invalid study ID');
    return join(home, id);
  };
  const read = (id: string): Study => JSON.parse(readFileSync(join(folder(id), 'study.json'), 'utf8'));
  const save = (record: Study) => {
    const target = join(folder(record.id), 'study.json');
    writeFileSync(target + '.tmp', JSON.stringify(record, null, 2));
    renameSync(target + '.tmp', target);
  };
  const list = (): Study[] => readdirSync(home).filter(id => /^[a-f0-9-]{36}$/.test(id) && existsSync(join(home, id, 'study.json'))).map(read).sort((a, b) => b.created_at.localeCompare(a.created_at));
  for (const record of list()) {
    for (const attempt of record.attempts) if (attempt.status === 'Running') {
      attempt.status = 'Interrupted'; attempt.error = 'Server stopped before completion'; attempt.ended_at = now();
    }
    save(record);
  }
  const snapshot = (destination: string, from = root) => {
    for (const dir of ['workbench', 'strategy_engine']) {
      mkdirSync(join(destination, dir), { recursive: true });
      writeFileSync(join(destination, dir, '__init__.py'), '');
    }
    for (const file of files) copyFileSync(join(from, file), join(destination, file));
    return hash(files.map(file => `${file}:${hash(readFileSync(join(destination, file)))}`).join('\n'));
  };
  const sourceHash = (source: string) => hash(files.map(file => `${file}:${hash(readFileSync(join(source, file)))}`).join('\n'));
  function runWorker(source: string, args: string[], log: string, key: string) {
    if (active.size >= 2) throw new Error('Two event-study workers are already running; wait for completion');
    const child = spawn(python, ['-m', 'workbench.event_study', ...args], { cwd: source, env: { ...environment(), PYTHONPATH: source }, windowsHide: true });
    active.set(key, child);
    let output = '';
    child.stdout.on('data', data => { output = (output + data.toString()).slice(-100000); writeFileSync(log, output); });
    child.stderr.on('data', data => { output = (output + data.toString()).slice(-100000); writeFileSync(log, output); });
    const timeout = setTimeout(() => child.kill(), 30 * 60 * 1000);
    return new Promise<void>((resolve, reject) => {
      child.on('error', error => { clearTimeout(timeout); active.delete(key); reject(error); });
      child.on('close', code => { clearTimeout(timeout); active.delete(key); if (code === 0) resolve(); else reject(new Error(output.slice(-4000) || 'Worker interrupted or timed out')); });
    });
  }
  async function preview(body: Record<string, unknown>) {
    const dataset = datasets().find(d => d.id === body.dataset_id);
    if (!dataset) throw new Error('Choose a registered dataset version');
    const parent = typeof body.parent_id === 'string' && body.parent_id ? read(body.parent_id) : undefined;
    if (parent && (!parent.frozen_at || !parent.attempts.some(a => a.phase === 'final' && a.status === 'Succeeded'))) throw new Error('Replication requires a completed frozen final test');
    if (parent && parent.protocol.dataset.symbol === dataset.symbol) throw new Error('Replication requires another instrument');
    const rules = parent ? { ...parent.protocol.rules } : { ...defaults };
    const supplied = body.rules;
    if (!parent && supplied !== undefined) {
      if (!supplied || typeof supplied !== 'object' || Array.isArray(supplied)) throw new Error('Rules must be an object');
      for (const [key, value] of Object.entries(supplied)) {
        if (!(key in limits) || typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`Invalid rule: ${key}`);
        const [min, max] = limits[key];
        if (value < min || value > max || (integers.has(key) && !Number.isInteger(value))) throw new Error(`Rule ${key} must be ${integers.has(key) ? 'an integer ' : ''}between ${min} and ${max}`);
        rules[key] = value;
      }
    }
    if (rules.cluster_bars < rules.return_bars + rules.reaction_bars) throw new Error('Cluster length must cover the return plus reaction windows');
    const start = String(body.start || ''), end = String(body.end || '');
    const validDate = (v: string) => /^\d{4}-\d{2}-\d{2}$/.test(v) && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v;
    if (!validDate(start) || !validDate(end) || start >= end) throw new Error('Choose a valid chronological UTC date range');
    if (start < dataset.first.slice(0, 10) || end > dataset.last.slice(0, 10)) throw new Error('Dates must lie inside the registered dataset coverage');
    const timeframe = parent?.protocol.timeframe || String(body.timeframe || '15m');
    const session = parent?.protocol.session || String(body.session || 'full-trading-day');
    if (!['5m', '15m', '30m', '1h'].includes(timeframe) || !['full-trading-day', 'new-york-rth'].includes(session)) throw new Error('Unsupported timeframe or session');
    const name = String(body.name || '').trim().slice(0, 120);
    const hypothesis = String(body.hypothesis || '').trim().slice(0, 4000);
    if (!name || !hypothesis) throw new Error('Give the study a name and a declared hypothesis');
    const token = randomUUID(), staging = join(home, 'previews', token);
    mkdirSync(staging, { recursive: true });
    const source = join(staging, 'source');
    const source_hash = snapshot(source, parent ? join(folder(parent.id), 'source') : root);
    if (parent && source_hash !== parent.protocol.source_hash) throw new Error('Parent source snapshot changed');
    const protocol: Protocol = { name, hypothesis, prior_exposure: String(body.prior_exposure || 'Unknown; reserved history is not certified untouched').slice(0, 4000), dataset, start, end, timeframe, session, rules, source_hash, ...(parent ? { parent_id: parent.id } : {}) };
    writeFileSync(join(staging, 'protocol.json'), JSON.stringify(protocol));
    await runWorker(source, ['preview', join(staging, 'protocol.json'), join(staging, 'preview.json')], join(staging, 'preview.log'), token);
    const plan: Plan = JSON.parse(readFileSync(join(staging, 'preview.json'), 'utf8'));
    previews.set(token, { protocol, plan, folder: staging, expires: Date.now() + 3600000 });
    return { token, protocol, plan };
  }
  function create(body: Record<string, unknown>) {
    const token = String(body.token || ''), checked = previews.get(token);
    if (!checked || checked.expires < Date.now()) throw new Error('Preview expired; validate again');
    const id = randomUUID();
    mkdirSync(folder(id));
    snapshot(join(folder(id), 'source'), join(checked.folder, 'source'));
    const record: Study = { id, created_at: now(), protocol: checked.protocol, plan: checked.plan,
      protocol_hash: hash(JSON.stringify({ protocol: checked.protocol, plan: checked.plan })), attempts: [],
      prior_studies: list().filter(s => s.protocol.dataset.symbol === checked.protocol.dataset.symbol && s.protocol.start <= checked.protocol.end && s.protocol.end >= checked.protocol.start).map(s => s.id) };
    writeFileSync(join(folder(id), 'protocol.json'), JSON.stringify({ protocol: record.protocol, plan: record.plan }, null, 2));
    save(record); previews.delete(token); return record;
  }
  function launch(id: string, phase: string) {
    const record = read(id);
    if (!['development', 'validation', 'final'].includes(phase)) throw new Error('Unknown study phase');
    if (record.attempts.some(a => a.status === 'Running')) throw new Error('This study already has an active job');
    if (record.attempts.some(a => a.phase === phase && a.status === 'Succeeded')) throw new Error('This phase is already complete; inspect its saved result');
    if (phase === 'development' && record.frozen_at) throw new Error('Frozen study cannot return to development');
    if (phase === 'validation' && (!record.reviewed_at || !record.attempts.some(a => a.phase === 'development' && a.status === 'Succeeded'))) throw new Error('Complete development and record the visual review first');
    if (phase === 'final' && !record.frozen_at) throw new Error('Freeze the protocol before opening the final test');
    if (active.size >= 2) throw new Error('Two event-study workers are running; wait for completion');
    const source = join(folder(id), 'source');
    if (sourceHash(source) !== record.protocol.source_hash || hash(JSON.stringify({ protocol: record.protocol, plan: record.plan })) !== record.protocol_hash) throw new Error('Saved source or protocol changed');
    const attempt: Attempt = { id: randomUUID(), phase, status: 'Running', created_at: now() };
    const destination = join(folder(id), attempt.id);
    mkdirSync(destination);
    writeFileSync(join(destination, 'input.json'), JSON.stringify({ protocol: record.protocol, plan: record.plan, phase }));
    record.attempts.push(attempt);
    if (phase === 'final') record.final_opened_at ||= now();
    save(record);
    void runWorker(source, ['run', join(destination, 'input.json'), destination], join(destination, 'process.log'), attempt.id).then(() => {
      const current = read(id), item = current.attempts.find(a => a.id === attempt.id)!;
      if (item.status !== 'Running') return;
      item.status = 'Succeeded'; item.ended_at = now(); save(current);
    }).catch(error => {
      const current = read(id), item = current.attempts.find(a => a.id === attempt.id)!;
      if (item.status !== 'Running') return;
      item.status = 'Failed'; item.error = String(error.message); item.ended_at = now(); save(current);
    });
    return record;
  }
  function review(id: string, body: Record<string, unknown>) {
    const record = read(id);
    if (record.frozen_at || !record.attempts.some(a => a.phase === 'development' && a.status === 'Succeeded')) throw new Error('Review requires completed development before freeze');
    const note = String(body.note || '').trim();
    if (note.length < 10) throw new Error('Record what you checked in the sampled detection charts');
    record.reviewed_at = now(); record.review_note = note.slice(0, 4000); save(record); return record;
  }
  function freeze(id: string) {
    const record = read(id);
    if (!record.reviewed_at || !record.attempts.some(a => a.phase === 'validation' && a.status === 'Succeeded') || record.attempts.some(a => a.status === 'Running')) throw new Error('Complete the visual review and validation before freezing');
    record.frozen_at ||= now(); save(record); return record;
  }
  function artifact(id: string, attemptId: string, name: string) {
    const record = read(id), attempt = record.attempts.find(a => a.id === attemptId);
    if (!attempt || !['result.json', 'events.json', 'events.csv', 'manifest.json', 'input.json', 'process.log'].includes(name)) throw new Error('Unknown study artifact');
    if (name !== 'process.log' && name !== 'input.json' && attempt.status !== 'Succeeded') throw new Error('Results are available only for a completed job');
    const path = join(folder(id), attemptId, name);
    if (!existsSync(path)) throw new Error('Artifact is not available yet');
    if (['result.json', 'events.json', 'events.csv'].includes(name)) {
      const manifest = JSON.parse(readFileSync(join(folder(id), attemptId, 'manifest.json'), 'utf8'));
      if (hash(readFileSync(path)) !== manifest.artifacts[name]) throw new Error('Study artifact checksum changed');
    }
    return path;
  }
  function cancel(id: string) {
    const record = read(id);
    const attempt = record.attempts.find(a => a.status === 'Running');
    if (!attempt) throw new Error('No active study job');
    active.get(attempt.id)?.kill();
    attempt.status = 'Cancelled'; attempt.ended_at = now(); save(record); return record;
  }
  return { list, read, preview, create, launch, review, freeze, artifact, cancel, defaults, limits,
    stop: () => { for (const child of active.values()) child.kill(); } };
}
