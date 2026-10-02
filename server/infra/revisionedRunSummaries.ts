import type { DatabaseSync } from "node:sqlite";
import type { RunSummary } from "../../shared/ts/workbenchModels.ts";
import { runSummaries } from "./stateSummary.ts";

// data_version notices writes from another SQLite connection; total_changes
// notices writes made through this connection, including direct deletion SQL.
export function createRevisionedRunSummaries(db: DatabaseSync) {
  const dataVersion = db.prepare("PRAGMA data_version");
  const localChanges = db.prepare("SELECT total_changes() AS changes");
  let cachedRevision = "";
  let cachedRuns: RunSummary[] = [];

  function revision() {
    return `${String(localChanges.get()?.changes)}/${String(dataVersion.get()?.data_version)}`;
  }

  function read(currentRevision = revision()): RunSummary[] {
    if (currentRevision !== cachedRevision) {
      cachedRuns = runSummaries(db) as RunSummary[];
      cachedRevision = currentRevision;
    }
    return cachedRuns;
  }

  return { revision, read };
}
