import { useMemo, useState, type ReactNode } from "react";
import { Alert, Button, Group, Text, TextInput } from "@mantine/core";
import { IconRefresh, IconSearch } from "@tabler/icons-react";
import { statusDisplay } from "../../../shared/ts/strategyLifecycle.ts";
import { strategyHref } from "../../app/navigation";
import { strategyTitle } from "../../shared/formatting/strategyTitle";
import { PageHeader } from "../../shared/ui/PageHeader";
import { useStrategyStages } from "../../shared/ui/strategyStageContext";
import { isInvalidRun } from "../runs/model";
import type { WorkbenchState } from "../workspace/workbenchModel";
import { rowAttempts, rowGroup, rowGroups, rowMeta, type ResearchRow, type RowGroupId } from "./researchRows";
import "./strategiesOverview.css";

const COLLAPSED = 4;
const collapsible: RowGroupId[] = ["failed", "rerun", "untested"];

export function StageDots({ row }: { row: ResearchRow }) {
  const display = statusDisplay(row.status);
  const plain = display.state === "benchmark" || display.state === "tracking";
  return (
    <span className="wb-stage-dots" aria-label={display.label} role="img">
      {[1, 2, 3, 4, 5].map((stage) => {
        const tone = plain ? "todo"
          : stage < display.stage || (stage === display.stage && display.state === "ready") ? "done"
            : stage === display.stage ? display.state : "todo";
        return <i key={stage} className={`is-${tone}`} />;
      })}
    </span>
  );
}

export function StatusChip({ row }: { row: ResearchRow }) {
  const display = statusDisplay(row.status);
  return <span className={`wb-status-chip is-${display.state}`} title={display.description}>{display.label}</span>;
}

export function StrategiesOverview({
  state,
  rows,
  busy,
  onScan,
  onCleanup,
  alerts,
}: {
  state: WorkbenchState;
  rows: ResearchRow[];
  busy: boolean;
  onScan: () => void;
  onCleanup: (ids: string[]) => void;
  alerts?: ReactNode;
}) {
  const { onAction } = useStrategyStages();
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Partial<Record<RowGroupId, boolean>>>({});
  const active = rows.filter((row) => !row.archived);
  const listed = active.filter((row) =>
    `${row.strategy.name} ${strategyTitle(row.strategy.name)} ${row.config?.symbol || ""} ${row.config?.timeframe || ""}`
      .toLowerCase()
      .includes(query.trim().toLowerCase()));
  const attempts = useMemo(
    () => Object.fromEntries(rows.filter((row) => !row.archived).map((row) => [row.id, rowAttempts(state, row).length])),
    [rows, state],
  );
  const groups = rowGroups
    .map((group) => ({ ...group, rows: listed.filter((row) => rowGroup(row) === group.id) }))
    .filter((group) => group.rows.length);
  const invalidRuns = state.runs.filter(isInvalidRun);

  return (
    <>
      <PageHeader
        crumb="Strategies"
        title="Strategies"
        actions={
          <Button variant="default" size="xs" leftSection={<IconRefresh size={14} />} disabled={busy} onClick={onScan}>
            Scan for new scripts
          </Button>
        }
      />
      {alerts}
      <div className="wb-content wb-strategies">
        {invalidRuns.length > 0 && (
          <Alert color="yellow" title={`${invalidRuns.length} run records need cleanup`}>
            <Group justify="space-between">
              <Text size="sm">Their result manifests are invalid.</Text>
              <Button size="xs" variant="light" onClick={() => onCleanup(invalidRuns.map((run) => run.id))}>Review cleanup</Button>
            </Group>
          </Alert>
        )}
        <TextInput
          className="wb-strategies-search"
          aria-label="Search strategies"
          placeholder="Search by name or market"
          leftSection={<IconSearch size={15} />}
          value={query}
          onChange={(event) => setQuery(event.currentTarget.value)}
        />
        {groups.map((group) => {
          const open = expanded[group.id] || !collapsible.includes(group.id) || group.rows.length <= COLLAPSED + 1;
          const shown = open ? group.rows : group.rows.slice(0, COLLAPSED);
          return (
            <section className="wb-strategy-group" key={group.id} aria-labelledby={`group-${group.id}`}>
              <div className="wb-strategy-group-head">
                <h2 id={`group-${group.id}`}>{group.title}<span className="wb-group-count">{group.rows.length}</span></h2>
                <p>{group.hint}</p>
              </div>
              <ul className="wb-strategy-rows">
                {shown.map((row) => {
                  const display = statusDisplay(row.status);
                  return (
                    <li key={row.id} className="wb-strategy-row">
                      <a className="wb-strategy-name" href={strategyHref(row.id)}>
                        <strong>{strategyTitle(row.strategy.name)}</strong>
                        <span>{rowMeta(row, attempts[row.id] || 0)}</span>
                      </a>
                      <StageDots row={row} />
                      <StatusChip row={row} />
                      <div className="wb-strategy-row-actions">
                        {row.status.action && onAction ? (
                          <Button
                            size="xs"
                            variant={display.state === "failed" ? "default" : "filled"}
                            onClick={() => onAction(row.status.action!)}
                          >
                            {row.status.action.label}
                          </Button>
                        ) : null}
                        <Button size="xs" variant="subtle" component="a" href={strategyHref(row.id)}>Open</Button>
                      </div>
                    </li>
                  );
                })}
              </ul>
              {!open && (
                <button type="button" className="wb-link-button" onClick={() => setExpanded((current) => ({ ...current, [group.id]: true }))}>
                  Show all {group.rows.length}
                </button>
              )}
              {open && collapsible.includes(group.id) && group.rows.length > COLLAPSED + 1 && expanded[group.id] && (
                <button type="button" className="wb-link-button" onClick={() => setExpanded((current) => ({ ...current, [group.id]: false }))}>
                  Show fewer
                </button>
              )}
            </section>
          );
        })}
        {!groups.length && <div className="wb-card"><Text size="sm" c="dimmed">{active.length ? "No strategies match." : "No runnable strategies yet. Scan the strategy folder to add scripts."}</Text></div>}
        <footer className="wb-stage-legend" aria-label="Research stages">
          <span>Research stages</span>
          {["Backtest", "Evaluation", "Robustness", "Forward test", "Ready"].map((name, index) => (
            <span key={name}>{index > 0 && <i aria-hidden="true">→</i>}<b>{index + 1}</b> {name}</span>
          ))}
        </footer>
      </div>
    </>
  );
}

export function ArchivedConfigurations({ state, rows, busy, onRestore }: {
  state: WorkbenchState;
  rows: ResearchRow[];
  busy: boolean;
  onRestore: (runId: string) => void;
}) {
  const archived = rows.filter((row) => row.archived);
  if (!archived.length) return null;
  return (
    <section className="wb-strategy-group" aria-labelledby="group-archived-configurations">
      <div className="wb-strategy-group-head">
        <h2 id="group-archived-configurations">Archived setups<span className="wb-group-count">{archived.length}</span></h2>
        <p>Archived setups keep their runs, results and evidence. Restore one to show it and its runs again.</p>
      </div>
      <ul className="wb-strategy-rows">
        {archived.map((row) => {
          const seed = rowAttempts(state, row)[0];
          return (
            <li key={row.id} className="wb-strategy-row">
              <a className="wb-strategy-name" href={strategyHref(row.id)}>
                <strong>{strategyTitle(row.strategy.name)}</strong>
                <span>{rowMeta(row, rowAttempts(state, row).length)}</span>
              </a>
              <StageDots row={row} />
              <StatusChip row={row} />
              <div className="wb-strategy-row-actions">
                {seed && <Button size="xs" variant="default" disabled={busy} onClick={() => onRestore(seed.id)}>Restore</Button>}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
