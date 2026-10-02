import { runConfigurationKey } from "./evidence.ts";
import type { RunSummary } from "./workbenchModels.ts";

export type ArchivedConfiguration = {
  strategy_id: string;
  configuration_key: string;
  archived_at: string;
};

export type ResearchArchive = {
  runs: { id: string; archived_at: string }[];
  configurations: ArchivedConfiguration[];
};

export function isConfigurationArchived(
  strategyId: string,
  configurationKey: string,
  archive?: ResearchArchive,
): boolean {
  return archive?.configurations.some(entry =>
    entry.strategy_id === strategyId && entry.configuration_key === configurationKey,
  ) ?? false;
}

export function archivedConfigurationForRun(
  run: RunSummary,
  archive?: ResearchArchive,
): ArchivedConfiguration | undefined {
  if (!archive?.configurations.length) return undefined;
  const key = runConfigurationKey(run);
  return archive.configurations.find(entry =>
    entry.strategy_id === run.input.strategy.id && entry.configuration_key === key,
  );
}

export function isRunArchived(run: RunSummary, archive?: ResearchArchive): boolean {
  return (archive?.runs.some(entry => entry.id === run.id) ?? false)
    || archivedConfigurationForRun(run, archive) !== undefined;
}
