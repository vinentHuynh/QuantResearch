import { readFileSync, existsSync, statSync, mkdirSync, writeFileSync, renameSync } from "node:fs";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import type { CollectiveCatalog, CollectiveItem } from "../../../shared/ts/portfolio.ts";
import type { EvaluationView, RunSummary, Strategy } from "../../../shared/ts/workbenchModels.ts";
import { portfolioStageStatus, strategyStageStatuses } from "../../../shared/ts/stageStatus.ts";
import { lifecycleStatus } from "../../../shared/ts/strategyLifecycle.ts";
import { dailyPnlRisk } from "./portfolioRisk.ts";

/** A frozen portfolio import can predate source-run links, so retain its exact
 * script key and source label as fallbacks for archive visibility. */
export function isArchivedCollectiveItem(
  item: CollectiveItem,
  archived: ReadonlySet<string>,
  runStrategies: ReadonlyMap<string, string>,
): boolean {
  if (archived.has(item.key.split("__")[0])) return true;
  if (archived.has(item.source.toLowerCase())) return true;
  return (item.source_run_ids || []).some((id) => archived.has(runStrategies.get(id) || ""));
}

export function createCollective(
  root: string,
  state: string,
  python: string,
  evidenceStatus: () => string = () => "",
  researchState?: () => { strategies: Pick<Strategy, "id" | "file_hash" | "execution_source_hash">[]; runs: RunSummary[]; evaluations: EvaluationView[] },
  archivedIds: () => ReadonlySet<string> = () => new Set(),
) {
  const folder = join(state, "collective");
  let refresh = { running: false, error: "", started_at: "", completed_at: "" };
  let pinnedOnlyRefresh = false;
  const lineage = new Map<string, { signature: string; ids: string[]; chart_points: number[]; max_drawdown_dollars?: number; max_drawdown?: number }>();
  function catalog(): CollectiveCatalog {
    if (!existsSync(join(folder, "index.json")))
      throw new Error(
        "No collective catalog yet. Refresh evidence to import completed research.",
      );
    return JSON.parse(readFileSync(join(folder, "index.json"), "utf8"));
  }
  function visibleItems(index: CollectiveCatalog, runs: RunSummary[]) {
    const archived = archivedIds();
    if (!archived.size) return index.items;
    const runStrategies = new Map(runs.map((run) => [run.id, run.input.strategy.id]));
    return index.items.filter((item) => !isArchivedCollectiveItem(item, archived, runStrategies));
  }
  const api = {
    importRun: (runId: string) => {
      if (refresh.running) throw new Error("Wait for the current evidence refresh to finish.");
      if (!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(runId))
        throw new Error("Choose a saved run with a valid ID.");
      const run = researchState?.().runs.find(candidate => candidate.id === runId);
      if (!run || run.status !== "Succeeded")
        throw new Error("Choose a completed saved run.");
      if (run.input.portfolio_replay)
        throw new Error("Portfolio tracking runs cannot be imported as research baselines.");
      const research = run.input.research;
      const tags = (run.tags || "").toLowerCase();
      const baseline = research
        ? research.role === "Test" && research.scenario === "Baseline"
        : !run.input.delay_bars && !["stress", "sensitivity", "benchmark"].some(tag => tags.includes(tag));
      if (!baseline) throw new Error("Only baseline histories can be imported.");
      if (existsSync(join(folder, "index.json"))) {
        const existing = api.catalog().items.find(item =>
          item.source_run_ids?.length === 1 &&
          item.source_run_ids[0] === runId &&
          item.coverage.length === 1 &&
          item.coverage[0].start === run.input.start &&
          item.coverage[0].end === run.input.end &&
          !item.latest_replay &&
          !item.research_integrity_error,
        );
        if (existing) {
          const now = new Date().toISOString();
          pinnedOnlyRefresh = true;
          refresh = { running: false, error: "", started_at: now, completed_at: now };
          return refresh;
        }
      }
      mkdirSync(folder, { recursive: true });
      const pinsFile = join(folder, "pinned-runs.json");
      const pins: unknown = existsSync(pinsFile) ? JSON.parse(readFileSync(pinsFile, "utf8")) : [];
      if (!Array.isArray(pins) || pins.some(id => typeof id !== "string"))
        throw new Error("Saved history imports need repair before adding another run.");
      let rollbackPin: (() => void) | undefined;
      if (!pins.includes(runId)) {
        const temp = `${pinsFile}.${process.pid}.tmp`;
        writeFileSync(temp, JSON.stringify([...pins, runId]));
        renameSync(temp, pinsFile);
        rollbackPin = () => {
          if (!existsSync(pinsFile)) return;
          const current: unknown = JSON.parse(readFileSync(pinsFile, "utf8"));
          if (!Array.isArray(current) || current.some(id => typeof id !== "string"))
            throw new Error("Saved history imports changed during failed import.");
          const index = current.indexOf(runId);
          if (index < 0) return;
          current.splice(index, 1);
          const rollbackTemp = `${pinsFile}.${process.pid}.rollback.tmp`;
          writeFileSync(rollbackTemp, JSON.stringify(current));
          renameSync(rollbackTemp, pinsFile);
        };
      }
      try {
        return api.rebuild(true, rollbackPin);
      } catch (error) {
        rollbackPin?.();
        throw error;
      }
    },
    catalog: () => {
      const index = catalog();
      const research = researchState?.();
      const archived = archivedIds();
      index.items = visibleItems(index, research?.runs || []);
      index.errors = (index.errors || []).filter(error => !archived.has(error.key.split("__")[0]));
      if (research) {
        const runs = research.runs.filter(run => !archived.has(run.input.strategy.id));
        const knownRunIds = new Set(research.runs.map(run => run.id));
        const researchRunIds = new Set(research.runs.filter(run => !run.input.portfolio_replay).map(run => run.id));
        const isResearchLineage = (id: string) => !knownRunIds.has(id) || researchRunIds.has(id);
        const evaluations = research.evaluations.filter(evaluation => !archived.has((evaluation.candidates?.[0] as { strategy?: { id?: string } } | undefined)?.strategy?.id || ""));
        const statuses = strategyStageStatuses(research.strategies, runs, evaluations);
        index.items = index.items.map(item => {
          try {
            if (!/^[a-f0-9]{20}-[a-f0-9]{16}\.json$/.test(item.series_file)) throw new Error("Unknown history file.");
            const file = join(folder, item.series_file);
            const stat = statSync(file);
            const signature = `${item.checksum}/${stat.mtimeMs}/${stat.ctimeMs}/${stat.size}/${item.capital}/${item.net_pnl}`;
            let cached = lineage.get(item.series_file);
            if (cached?.signature !== signature) {
              const bytes = readFileSync(file);
              if (createHash("sha256").update(bytes).digest("hex") !== item.checksum) throw new Error("History checksum changed; refresh evidence.");
              const history = JSON.parse(bytes.toString("utf8")) as { trades: { source_run?: string }[] };
              const daily = (history as { daily?: { date: string; pnl: number }[] }).daily || [];
              // Old index fixtures may lack capital. Keep their lineage visible;
              // only complete saved histories can carry a daily risk measure.
              const risk = Number.isFinite(item.capital) && item.capital > 0
                ? dailyPnlRisk(daily, item.capital) : undefined;
              if (risk && Number.isFinite(item.net_pnl) && Math.abs(risk.net_pnl - item.net_pnl) > 0.01)
                throw new Error("Saved history daily P&L does not reconcile with its catalog.");
              let cumulative = 0;
              const values = [0, ...daily.map(mark => cumulative += Number(mark.pnl) || 0)];
              const stride = Math.max(1, Math.ceil(values.length / 48));
              const chart_points = values.filter((_, index) => index % stride === 0);
              if (chart_points.at(-1) !== values.at(-1)) chart_points.push(values.at(-1)!);
              cached = { signature, ids: [...new Set(history.trades.map(trade => trade.source_run).filter((id): id is string => !!id))], chart_points, max_drawdown_dollars: risk?.max_drawdown_dollars, max_drawdown: risk?.max_drawdown };
              lineage.set(item.series_file, cached);
              const linked = { ...item, source_run_ids: [...new Set([...(item.source_run_ids || []), ...cached.ids])].filter(id =>
                id !== item.verified_replay?.source_run_id && isResearchLineage(id)) };
              return { ...linked, chart_points: cached.chart_points, max_drawdown_dollars: cached.max_drawdown_dollars, max_drawdown: cached.max_drawdown, research_status: portfolioStageStatus(linked, runs, statuses) };
            }
            const linked = { ...item, source_run_ids: [...new Set([...(item.source_run_ids || []), ...cached.ids])].filter(id =>
              id !== item.verified_replay?.source_run_id && isResearchLineage(id)) };
            return { ...linked, chart_points: cached.chart_points, max_drawdown_dollars: cached.max_drawdown_dollars, max_drawdown: cached.max_drawdown, research_status: portfolioStageStatus(linked, runs, statuses) };
          } catch (error) {
            const message = String(error instanceof Error ? error.message : error);
            return { ...item, research_integrity_error: message, research_status: lifecycleStatus("needs-review", 1, message, ["Repair or refresh the verified history."]) };
          }
        });
        // Verified series can reveal lineage missing from older index files.
        index.items = visibleItems(index, research.runs);
      }
      return { ...index, refresh, evidence_error: evidenceStatus() };
    },
    status: () => ({ ...refresh, evidence_error: pinnedOnlyRefresh ? "" : evidenceStatus() }),
    series: (ids: unknown) => {
      if (
        !Array.isArray(ids) ||
        ids.length > 100 ||
        ids.some((id) => typeof id !== "string") ||
        new Set(ids).size !== ids.length
      )
        throw new Error("Choose up to 100 unique strategy configurations.");
      const index = catalog();
      const runs = researchState?.().runs || [];
      const trackingRunIds = new Set(runs.filter(run => run.input.portfolio_replay).map(run => run.id));
      index.items = visibleItems(index, runs);
      const archived = archivedIds();
      const runStrategies = new Map(runs.map(run => [run.id, run.input.strategy.id]));
      return ids.map((id) => {
        const item = index.items.find((i) => i.id === id);
        if (
          !item ||
          !/^[a-f0-9]{20}-[a-f0-9]{16}\.json$/.test(item.series_file)
        )
          throw new Error(
            "Unknown strategy configuration. Refresh the catalog.",
          );
        const bytes = readFileSync(join(folder, item.series_file));
        if (createHash("sha256").update(bytes).digest("hex") !== item.checksum)
          throw new Error(
            "Saved portfolio history changed. Refresh evidence before combining it.",
          );
        const history = JSON.parse(bytes.toString("utf8")) as { trades?: { source_run?: string }[] };
        const linked = {
          ...item,
          source_run_ids: [...new Set([
            ...(item.source_run_ids || []),
            ...(history.trades || []).map(trade => trade.source_run).filter((runId): runId is string => !!runId),
          ])].filter(runId => runId !== item.verified_replay?.source_run_id && !trackingRunIds.has(runId)),
        };
        if (isArchivedCollectiveItem(linked, archived, runStrategies))
          throw new Error("Unknown strategy configuration. Refresh the catalog.");
        return history;
      });
    },
    rebuild: (pinnedOnly = false, onFailure?: () => void) => {
      if (refresh.running) return refresh;
      pinnedOnlyRefresh = pinnedOnly;
      const fail = (error: string) => {
        let message = error;
        try { onFailure?.(); }
        catch (rollbackError) {
          message += `\nCould not undo failed run import: ${String(rollbackError)}`;
        }
        refresh = { ...refresh, running: false, error: message, completed_at: new Date().toISOString() };
        return refresh;
      };
      const evidenceError = pinnedOnly ? "" : evidenceStatus();
      if (evidenceError) {
        const now = new Date().toISOString();
        refresh = {
          running: false,
          error: "",
          started_at: now,
          completed_at: now,
        };
        return fail(evidenceError);
      }
      refresh = {
        running: true,
        error: "",
        started_at: new Date().toISOString(),
        completed_at: "",
      };
      let child;
      try {
        child = spawn(python, [join(root, "scripts/build-collective.py"), ...(pinnedOnly ? ["--pinned-only"] : [])], {
          cwd: root,
          windowsHide: true,
          env: { ...process.env, WORKBENCH_HOME: state },
        });
      } catch (error) {
        return fail(String(error));
      }
      let output = "";
      child.stdout.on("data", (data) => {
        output = (output + data).slice(-12000);
      });
      child.stderr.on("data", (data) => {
        output = (output + data).slice(-12000);
      });
      let finished = false;
      const finish = (error?: string) => {
        if (finished) return;
        finished = true;
        if (error) fail(error);
        else refresh = { ...refresh, running: false, error: "", completed_at: new Date().toISOString() };
      };
      child.on("error", (error) => finish(error.message));
      child.on("close", (code) => {
        finish(code === 0 ? undefined : output || "Evidence import failed");
      });
      return refresh;
    },
  };
  return api;
}
