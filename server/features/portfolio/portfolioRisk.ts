import { createHash } from "node:crypto";
import { createReadStream, existsSync, mkdirSync, readFileSync, renameSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createInterface } from "node:readline";
import type { RunSummary } from "../../../shared/ts/workbenchModels.ts";

export type HistoryRisk = {
  net_pnl: number;
  /** Largest daily-close loss below a previous equity peak, in dollars. */
  max_drawdown_dollars: number;
  /** Most negative daily-close change from its previous equity peak. */
  max_drawdown: number;
};

export function dailyPnlRisk(marks: readonly { date: string; pnl: number }[], capital: number): HistoryRisk {
  if (!Number.isFinite(capital) || capital <= 0 || !marks.length)
    throw new Error("Saved history has no valid starting capital or daily marks.");
  let equity = capital;
  let peak = capital;
  let max_drawdown_dollars = 0;
  let max_drawdown = 0;
  let previousDate = "";
  for (const mark of marks) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(mark.date) || mark.date <= previousDate || !Number.isFinite(mark.pnl))
      throw new Error("Saved history has invalid or unordered daily marks.");
    previousDate = mark.date;
    equity += mark.pnl;
    if (!Number.isFinite(equity)) throw new Error("Saved history equity is not finite.");
    peak = Math.max(peak, equity);
    max_drawdown_dollars = Math.max(max_drawdown_dollars, peak - equity);
    max_drawdown = Math.min(max_drawdown, equity / peak - 1);
  }
  return { net_pnl: equity - capital, max_drawdown_dollars, max_drawdown };
}

type RiskResponse = {
  ready: Record<string, HistoryRisk>;
  pending: string[];
  errors: Record<string, string>;
};
type Artifact = { name: string; checksum: string };
type CacheEntry = { checksum: string; signature: string; risk: HistoryRisk };
type PreparedRun = {
  id: string;
  path: string;
  checksum: string;
  signature: string;
  capital: number;
  start: string;
  end: string;
  expectedPnl?: number;
};

function artifactFor(run: RunSummary, state: string): PreparedRun {
  const path = join(state, "runs", run.id, "equity.csv");
  const manifestPath = join(state, "runs", run.id, "manifest.json");
  if (!existsSync(manifestPath)) throw new Error("Saved run manifest is missing.");
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as { artifacts?: Artifact[] };
  const checksum = manifest.artifacts?.find(artifact => artifact.name === "equity.csv")?.checksum;
  if (!checksum || !/^[a-f0-9]{64}$/i.test(checksum))
    throw new Error("Saved run manifest has no equity checksum.");
  const recorded = (run.result?.artifacts as Artifact[] | undefined)?.find(artifact => artifact.name === "equity.csv")?.checksum;
  if (recorded && recorded !== checksum)
    throw new Error("Saved run manifest differs from its recorded result.");
  let stat;
  try { stat = statSync(path); }
  catch { throw new Error("Saved run equity artifact is missing."); }
  if (!stat.isFile()) throw new Error("Saved run equity artifact is unavailable.");
  const capital = Number(run.input.capital);
  if (!Number.isFinite(capital) || capital <= 0) throw new Error("Saved run capital is invalid.");
  const expectedPnl = Number(run.result?.metrics?.net_pnl);
  return {
    id: run.id, path, checksum: checksum.toLowerCase(),
    signature: `${stat.size}/${stat.mtimeMs}/${stat.ctimeMs}`,
    capital,
    start: run.input.start,
    end: run.input.end,
    expectedPnl: Number.isFinite(expectedPnl) ? expectedPnl : undefined,
  };
}

async function streamedRunRisk(run: PreparedRun): Promise<HistoryRisk> {
  const file = createReadStream(run.path);
  const hash = createHash("sha256");
  file.on("data", chunk => hash.update(chunk));
  const lines = createInterface({ input: file, crlfDelay: Infinity });
  let header = true;
  let timestampColumn = -1;
  let equityColumn = -1;
  let previousTime = -Infinity;
  let lastDate = "";
  let lastEquity = NaN;
  let scoredEquity = NaN;
  let peak = run.capital;
  let max_drawdown_dollars = 0;
  let max_drawdown = 0;
  let count = 0;
  const observe = (equity: number) => {
    peak = Math.max(peak, equity);
    max_drawdown_dollars = Math.max(max_drawdown_dollars, peak - equity);
    max_drawdown = Math.min(max_drawdown, equity / peak - 1);
  };
  try {
    for await (const line of lines) {
      if (header) {
        const fields = line.replace(/^\uFEFF/, "").split(",").map(field => field.trim());
        timestampColumn = fields.indexOf("timestamp");
        equityColumn = fields.indexOf("equity");
        if (timestampColumn < 0 || equityColumn < 0)
          throw new Error("Saved run equity artifact has invalid columns.");
        header = false;
        continue;
      }
      if (!line.trim()) continue;
      const fields = line.split(",");
      const rawTimestamp = fields[timestampColumn]?.trim();
      const equity = Number(fields[equityColumn]?.trim());
      const time = Date.parse(rawTimestamp || "");
      if (!rawTimestamp || !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(rawTimestamp) ||
          !Number.isFinite(time) || time < previousTime ||
          !fields[equityColumn]?.trim() || !Number.isFinite(equity))
        throw new Error("Saved run equity artifact contains invalid or unordered rows.");
      previousTime = time;
      const date = new Date(time).toISOString().slice(0, 10);
      if (lastDate && date !== lastDate && lastDate >= run.start && lastDate <= run.end) {
        observe(lastEquity);
        scoredEquity = lastEquity;
      }
      lastDate = date;
      lastEquity = equity;
      count++;
    }
  } finally {
    lines.close();
    file.destroy();
  }
  if (!count) throw new Error("Saved run equity artifact has no rows.");
  if (lastDate >= run.start && lastDate <= run.end) {
    observe(lastEquity);
    scoredEquity = lastEquity;
  }
  if (!Number.isFinite(scoredEquity)) throw new Error("Saved run equity artifact has no rows in the run window.");
  if (hash.digest("hex") !== run.checksum)
    throw new Error("Saved run equity artifact checksum changed.");
  const after = statSync(run.path);
  if (`${after.size}/${after.mtimeMs}/${after.ctimeMs}` !== run.signature)
    throw new Error("Saved run equity artifact changed during calculation.");
  const net_pnl = scoredEquity - run.capital;
  if (run.expectedPnl !== undefined && Math.abs(net_pnl - run.expectedPnl) > 0.01)
    throw new Error("Saved run equity does not reconcile with its recorded P&L.");
  return { net_pnl, max_drawdown_dollars, max_drawdown };
}

export function createPortfolioRisk(
  state: string,
  runs: () => RunSummary[],
  archivedIds: () => ReadonlySet<string> = () => new Set(),
) {
  const cachePath = join(state, "collective", "run-risk-cache.json");
  let entries: Record<string, CacheEntry> = {};
  try {
    const parsed = JSON.parse(readFileSync(cachePath, "utf8")) as { version: number; entries: Record<string, CacheEntry> };
    if (parsed.version === 1 && parsed.entries && typeof parsed.entries === "object") {
      entries = Object.fromEntries(Object.entries(parsed.entries).filter(([, entry]) =>
        entry && /^[a-f0-9]{64}$/.test(entry.checksum) && typeof entry.signature === "string" &&
        Number.isFinite(entry.risk?.net_pnl) && Number.isFinite(entry.risk?.max_drawdown_dollars) &&
        entry.risk.max_drawdown_dollars >= 0 && Number.isFinite(entry.risk?.max_drawdown) && entry.risk.max_drawdown <= 0));
    }
  } catch { /* A missing or damaged derived cache is safe to recalculate. */ }
  const queued = new Map<string, PreparedRun>();
  const active = new Map<string, PreparedRun>();
  const failures = new Map<string, { signature: string; message: string }>();
  let running = 0;
  const save = () => {
    mkdirSync(join(state, "collective"), { recursive: true });
    const temp = `${cachePath}.${process.pid}.tmp`;
    writeFileSync(temp, JSON.stringify({ version: 1, entries }));
    renameSync(temp, cachePath);
  };
  const pump = () => {
    while (running < 2 && queued.size) {
      const [id, prepared] = queued.entries().next().value!;
      queued.delete(id);
      active.set(id, prepared);
      running++;
      void streamedRunRisk(prepared).then(risk => {
        const prior = entries[id];
        entries[id] = { checksum: prepared.checksum, signature: prepared.signature, risk };
        try { save(); }
        catch (error) {
          if (prior) entries[id] = prior;
          else delete entries[id];
          throw error;
        }
        failures.delete(id);
      }).catch(error => {
        failures.set(id, { signature: `${prepared.checksum}/${prepared.signature}`, message: String(error instanceof Error ? error.message : error) });
      }).finally(() => {
        active.delete(id);
        running--;
        pump();
      });
    }
  };
  const risk = (ids: unknown): RiskResponse => {
    if (!Array.isArray(ids) || ids.length > 100 || ids.some(id => typeof id !== "string") || new Set(ids).size !== ids.length)
      throw new Error("Choose up to 100 unique saved runs.");
    const all = new Map(runs().map(run => [run.id, run]));
    const archived = archivedIds();
    const result: RiskResponse = { ready: {}, pending: [], errors: {} };
    for (const id of ids) {
      if (!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(id)) {
        result.errors[id] = "Invalid saved run ID.";
        continue;
      }
      const run = all.get(id);
      if (!run || run.status !== "Succeeded" || run.input.portfolio_replay || archived.has(run.input.strategy.id)) {
        result.errors[id] = "Run is unavailable for portfolio research.";
        continue;
      }
      const research = run.input.research;
      const tags = (run.tags || "").toLowerCase();
      const baseline = research
        ? research.role === "Test" && research.scenario === "Baseline"
        : !run.input.delay_bars && !["stress", "sensitivity", "benchmark"].some(tag => tags.includes(tag));
      if (!baseline) {
        result.errors[id] = "Only baseline runs can be compared.";
        continue;
      }
      try {
        const prepared = artifactFor(run, state);
        const key = `${prepared.checksum}/${prepared.signature}`;
        const cached = entries[id];
        if (cached?.checksum === prepared.checksum && cached.signature === prepared.signature) {
          result.ready[id] = cached.risk;
        } else if (failures.get(id)?.signature === key) {
          result.errors[id] = failures.get(id)!.message;
        } else {
          if (!active.has(id) && !queued.has(id)) queued.set(id, prepared);
          result.pending.push(id);
        }
      } catch (error) {
        result.errors[id] = String(error instanceof Error ? error.message : error);
      }
    }
    pump();
    return result;
  };
  return { risk };
}
