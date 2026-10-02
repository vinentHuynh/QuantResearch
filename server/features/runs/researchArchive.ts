import type { DatabaseSync } from "node:sqlite";
import { runConfigurationKey } from "../../../shared/ts/evidence.ts";
import type { ResearchArchive } from "../../../shared/ts/researchArchive.ts";
import type { RunSummary } from "../../../shared/ts/workbenchModels.ts";
import type { RecordRepository } from "../../infra/recordRepository.ts";
import type { Evaluation } from "../evaluations/research.ts";

const RECORD_KIND = "research_archive";
const RECORD_ID = "workspace";
const activeStatus = (status: string) => ["Queued", "Running", "Summarizing"].includes(status);

type Dependencies = {
  db: DatabaseSync;
  records: RecordRepository;
  runs: () => RunSummary[];
  active: (id: string) => boolean;
  now?: () => string;
};

/** Visibility metadata is independent of immutable research inputs and evidence. */
export function createResearchArchive(d: Dependencies) {
  const now = d.now || (() => new Date().toISOString());

  function read(): ResearchArchive {
    return d.records.raw(RECORD_KIND, RECORD_ID) === undefined
      ? { runs: [], configurations: [] }
      : d.records.get<ResearchArchive>(RECORD_KIND, RECORD_ID);
  }

  function update(change: (archive: ResearchArchive) => void): ResearchArchive {
    d.db.exec("BEGIN IMMEDIATE");
    try {
      const archive = read();
      const before = JSON.stringify(archive);
      change(archive);
      if (JSON.stringify(archive) !== before)
        d.records.put(RECORD_KIND, RECORD_ID, archive);
      d.db.exec("COMMIT");
      return archive;
    } catch (error) {
      d.db.exec("ROLLBACK");
      throw error;
    }
  }

  function selectedRuns(ids: unknown): RunSummary[] {
    if (!Array.isArray(ids) || !ids.length || ids.some(id => typeof id !== "string" || !id.trim()))
      throw new Error("Select at least one valid run");
    const runs = new Map(d.runs().map(run => [run.id, run]));
    return [...new Set<string>(ids)].map(id => {
      const run = runs.get(id);
      if (!run) throw new Error("A selected run no longer exists; refresh and try again");
      return run;
    });
  }

  function archiveRuns(ids: unknown): ResearchArchive {
    return update(archive => {
      const runs = selectedRuns(ids);
      if (runs.some(run => activeStatus(run.status) || d.active(run.id)))
        throw new Error("Wait for selected runs to finish before archiving them");
      const existing = new Set(archive.runs.map(entry => entry.id));
      const archivedAt = now();
      for (const run of runs)
        if (!existing.has(run.id)) archive.runs.push({ id: run.id, archived_at: archivedAt });
    });
  }

  function unarchiveRuns(ids: unknown): ResearchArchive {
    return update(archive => {
      const selected = new Set(selectedRuns(ids).map(run => run.id));
      archive.runs = archive.runs.filter(entry => !selected.has(entry.id));
    });
  }

  function configurationSeed(runId: unknown) {
    const [seed] = selectedRuns([runId]);
    return { seed, strategyId: seed.input.strategy.id, key: runConfigurationKey(seed) };
  }

  function configurationIsActive(strategyId: string, key: string): boolean {
    const matchingRuns = d.runs().filter(run => run.input.strategy.id === strategyId && runConfigurationKey(run) === key);
    if (matchingRuns.some(run => activeStatus(run.status) || d.active(run.id))) return true;
    const matchingRunIds = new Set(matchingRuns.map(run => run.id));
    const linkedEvaluationIds = new Set(matchingRuns.map(run => run.input.research?.evaluation_id).filter(Boolean));

    // An evaluation may still be selecting or summarizing between run jobs.
    // Its frozen source fingerprint belongs to the evaluation, not the candidate.
    const matchingEvaluations = d.records.all<Evaluation>("evaluation").filter(evaluation =>
      linkedEvaluationIds.has(evaluation.id) ||
      evaluation.folds?.some(fold => [...fold.training, ...fold.tests].some(id => matchingRunIds.has(id))) ||
      evaluation.candidates?.some(candidate => candidate.strategy.id === strategyId &&
        runConfigurationKey({ input: {
          ...candidate,
          source_hash: evaluation.source_hash,
          execution_source_hash: evaluation.execution_source_hash,
        } } as unknown as RunSummary) === key),
    );
    if (matchingEvaluations.some(evaluation => activeStatus(evaluation.status))) return true;
    const matchingIds = new Set(matchingEvaluations.map(evaluation => evaluation.id));
    return d.records.all<{ evaluation_id: string; status: string }>("regime")
      .some(regime => matchingIds.has(regime.evaluation_id) && activeStatus(regime.status));
  }

  function archiveConfiguration(runId: unknown): ResearchArchive {
    return update(archive => {
      const { strategyId, key } = configurationSeed(runId);
      if (configurationIsActive(strategyId, key))
        throw new Error("Wait for this configuration's active research to finish before archiving it");
      if (!archive.configurations.some(entry => entry.strategy_id === strategyId && entry.configuration_key === key))
        archive.configurations.push({ strategy_id: strategyId, configuration_key: key, archived_at: now() });
    });
  }

  function unarchiveConfiguration(runId: unknown): ResearchArchive {
    return update(archive => {
      const { strategyId, key } = configurationSeed(runId);
      archive.configurations = archive.configurations.filter(entry =>
        entry.strategy_id !== strategyId || entry.configuration_key !== key);
    });
  }

  return { read, archiveRuns, unarchiveRuns, archiveConfiguration, unarchiveConfiguration };
}
