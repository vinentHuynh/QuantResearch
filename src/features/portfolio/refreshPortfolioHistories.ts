import { commonWindow, type CollectiveCatalog, type CollectiveItem, type CollectiveSeries, type Coverage } from "../../../shared/ts/portfolio.ts";
import { exactPortfolioItemForRun, isPortfolioBaselineRun } from "../../../shared/ts/portfolioScriptCandidates.ts";
import { isCurrentStrategyRun } from "../../../shared/ts/stageStatus.ts";
import type { RunInput, RunSummary } from "../../../shared/ts/workbenchModels.ts";
import { workbenchRequest as request } from "../../shared/api/workbench.ts";
import type { NewRunInput } from "../new-run/model.ts";
import type { WorkbenchState } from "../workspace/workbenchModel.ts";

type RefreshPlan = {
  item: CollectiveItem;
  coverage: Coverage[];
  payload: NewRunInput;
  run?: RunSummary;
};

const label = (item: CollectiveItem) => `${item.name} (${item.symbol} ${item.timeframe})`;
const parametersKey = (parameters: RunInput["parameters"]) => JSON.stringify(Object.entries(parameters).sort(([a], [b]) => a.localeCompare(b)));
const active = (status: string) => ["Queued", "Running", "Summarizing"].includes(status);
const pause = () => new Promise<void>(resolve => setTimeout(resolve, 2000));

export function planPortfolioRefresh(items: CollectiveItem[], state: Pick<WorkbenchState, "runs" | "datasets" | "strategies">): RefreshPlan[] {
  const runs = new Map(state.runs.map(run => [run.id, run]));
  return items.map(item => {
    if (item.research_integrity_error) throw new Error(`${label(item)}: ${item.research_integrity_error}`);
    const params = parametersKey(item.parameters);
    const sources = (item.source_run_ids || []).map(id => runs.get(id)).filter((r): r is RunSummary =>
      !!r && r.status === "Succeeded" && isPortfolioBaselineRun(r) && r.input.dataset.symbol === item.symbol &&
      r.input.timeframe === item.timeframe && r.input.session === item.session && parametersKey(r.input.parameters) === params);
    const source = sources.sort((a, b) => b.input.end.localeCompare(a.input.end) || b.created_at.localeCompare(a.created_at))[0];
    if (!source || new Set(sources.map(r => r.input.strategy.id)).size !== 1) throw new Error(`Cannot recalculate ${label(item)}. Select a history linked to a completed baseline run.`);
    const input = source.input;
    const strategy = state.strategies.find(s => s.id === input.strategy.id);
    if (!strategy) throw new Error(`Cannot recalculate ${label(item)}. Its strategy script is unavailable.`);
    const originalStart = Date.parse(input.start);
    const warmup = Math.min((input.warmup_days || 0) * 86400000,
      Math.max(0, originalStart - Date.parse((input.dataset.first || input.start).slice(0, 10))));
    const available = state.datasets.filter(d => d.symbol === item.symbol).map(dataset => {
      const earliest = Date.parse(dataset.first.slice(0, 10)) + warmup;
      const start = new Date(Math.max(originalStart, earliest)).toISOString().slice(0, 10);
      return { dataset, start, end: dataset.last.slice(0, 10) };
    }).filter(target => target.start <= target.end)
      .sort((a, b) => b.dataset.last.localeCompare(a.dataset.last) || a.start.localeCompare(b.start) ||
        (b.dataset.registered_at || "").localeCompare(a.dataset.registered_at || ""));
    if (!available.length) throw new Error(`Cannot recalculate ${label(item)}. Import market data covering the backtest and its warmup.`);
    const { dataset, start, end } = available[0];
    const payload: NewRunInput = {
      strategy_id: strategy.id, dataset_id: dataset.id, start, end,
      timeframe: input.timeframe, session: input.session, stage: input.stage === "Evaluation" ? "Evaluation" : "Exploratory",
      parameters: input.parameters, capital: input.capital, fee: input.fee, slippage: input.slippage,
      delay_bars: input.delay_bars ?? 0, warmup_days: input.warmup_days, timeout: input.timeout,
      development_end: input.development_end, hypothesis: input.hypothesis, criteria: input.criteria, sweep: {},
    };
    return { item, coverage: [{ start, end }], payload };
  });
}

type ImportStatus = { running: boolean; error?: string; evidence_error?: string };

export async function updatePortfolioEvidence(runIds?: string[], signal?: AbortSignal) {
  const data = runIds?.length === 1 ? { runId: runIds[0] } : { runIds };
  let status: ImportStatus;
  try {
    status = await request<ImportStatus>(runIds ? "/collective/import" : "/collective/refresh", runIds ? data : {}, "POST", signal);
  } catch (error) {
    // A running workbench API may predate batch imports while Vite has already reloaded the drawer.
    if (runIds && runIds.length > 1 && error instanceof Error && error.message.endsWith("Choose a saved run with a valid ID.")) {
      for (const id of runIds) await updatePortfolioEvidence([id], signal);
      return;
    }
    throw error;
  }
  while (status.running && !status.error && !status.evidence_error) {
    await pause();
    status = await request<ImportStatus>("/collective/status", undefined, "GET", signal);
  }
  if (status.error || status.evidence_error) throw new Error(status.error || status.evidence_error);
}

export async function recalculatePortfolioHistories(
  selected: CollectiveItem[], catalog: CollectiveCatalog, attemptRunIds: Map<string, string>,
  signal: AbortSignal, progress: (text: string) => void,
) {
  const state = await request<WorkbenchState>("/state?view=summary", undefined, "GET", signal);
  const plans = planPortfolioRefresh(selected, state);
  const window = commonWindow(plans);
  if (!window.start) {
    const ranges = plans.map(p => `${label(p.item)}: ${p.payload.start} to ${p.payload.end}`);
    throw new Error(`The available market data still has no shared tested dates. Review these histories or import additional market data. ${ranges.join(". ")}.`);
  }

  const jobs = new Map<string, RunSummary>();
  for (const plan of plans) {
    const key = JSON.stringify({ ...plan.payload, parameters: parametersKey(plan.payload.parameters) });
    plan.run = jobs.get(key);
    const retryId = attemptRunIds.get(key);
    if (!plan.run && retryId) {
      const prior = state.runs.find(r => r.id === retryId);
      const strategy = state.strategies.find(s => s.id === plan.payload.strategy_id);
      if (prior && (active(prior.status) || (prior.status === "Succeeded" && prior.result)) && isCurrentStrategyRun(prior, strategy))
        plan.run = prior;
    }
    if (!plan.run) {
      progress(`Starting ${label(plan.item)} through ${plan.payload.end}…`);
      try {
        const launched = await request<RunSummary[]>("/runs", plan.payload, "POST", signal);
        if (launched.length !== 1 || !launched[0]?.id) throw new Error("The server did not return the new run.");
        plan.run = launched[0];
        attemptRunIds.set(key, plan.run.id);
      } catch (error) {
        throw new Error(`${label(plan.item)}: ${error instanceof Error ? error.message : error}`);
      }
    }
    jobs.set(key, plan.run);
  }
  const pending = [...jobs.values()].filter(run => run.status !== "Succeeded");
  const total = jobs.size;
  while (pending.length) {
    progress(`Backtests complete: ${total - pending.length} of ${total}. Waiting for ${pending[0].input.strategy.name}…`);
    await pause();
    for (const run of [...pending]) {
      const result = await request<Pick<RunSummary, "status" | "error">>(`/runs/${encodeURIComponent(run.id)}/status`, undefined, "GET", signal);
      if (result.status === "Succeeded") pending.splice(pending.indexOf(run), 1);
      else if (!active(result.status)) throw new Error(`${run.input.strategy.name}: ${result.error || result.status}. See Runs for details.`);
    }
  }

  const missing = [...jobs.values()].filter(run => !exactPortfolioItemForRun(catalog, run));
  if (missing.length) {
    progress(`Importing ${missing.length} completed ${missing.length === 1 ? "history" : "histories"}…`);
    await updatePortfolioEvidence(missing.map(run => run.id), signal);
  }
  progress("Verifying the shared tested window…");
  const updated = await request<CollectiveCatalog>("/collective", undefined, "GET", signal);
  const replacements = plans.map(({ item, run }) => {
    const next = run && exactPortfolioItemForRun(updated, run);
    if (!next || next.research_integrity_error) throw new Error(`Could not verify the saved history for ${label(item)}. Retry this recalculation to finish importing its runs.`);
    return { previous: item.id, next };
  });
  const ids = [...new Set(replacements.map(r => r.next.id))];
  const histories = await request<CollectiveSeries[]>("/collective/series", { ids }, "POST", signal);
  if (histories.length !== ids.length || !ids.every(id => histories.some(history => history.id === id)))
    throw new Error("Some refreshed histories could not be loaded. Retry to verify them before updating the portfolio.");
  const common = commonWindow(histories);
  if (!common.start) throw new Error("The verified histories have no common tested window. Review the selected configurations.");
  return { catalog: updated, replacements, histories, common };
}
