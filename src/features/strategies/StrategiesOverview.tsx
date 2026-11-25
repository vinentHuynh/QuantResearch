import { useMemo, useState, type ReactNode } from "react";
import { Alert, Button, Group, Text, TextInput } from "@mantine/core";
import { IconRefresh, IconSearch } from "@tabler/icons-react";
import { statusDisplay } from "../../../shared/ts/strategyLifecycle.ts";
import { href, strategyHref } from "../../app/navigation";
import { strategyTitle } from "../../shared/formatting/strategyTitle";
import { PageHeader } from "../../shared/ui/PageHeader";
import { useStrategyStages } from "../../shared/ui/strategyStageContext";
import { isInvalidRun } from "../runs/model";
import { formatNumber, formatPercent, type WorkbenchState } from "../workspace/workbenchModel";
import { groupedResearchRows, rowAttempts, rowMeta, type ResearchRow, type RowGroupId } from "./researchRows";
import { ResearchGroupHeading, StageDots, StatusChip } from "./ResearchStageIndicators";
import "./strategiesOverview.css";

const COLLAPSED = 4;
const collapsible: RowGroupId[] = ["failed", "rerun", "untested"];

function StrategyRowSummary({ row, attempts }: { row: ResearchRow; attempts: number }) {
  const best = row.config?.bestRun;
  const metrics = best?.result?.metrics;
  const title = strategyTitle(row.strategy.name);
  return (
    <div className="wb-strategy-summary">
      <a className="wb-strategy-name" href={strategyHref(row.id)}>
        <strong>{title}</strong>
        <span>{rowMeta(row, attempts)}</span>
      </a>
      {best && metrics ? (
        <div className="wb-strategy-best">
          <a className="wb-link" href={href("runs", `inspect~${best.id}`)}
            aria-label={`Open best run for ${title}, ${best.input.dataset.symbol} ${best.input.timeframe}`}
            title={`${best.input.research?.scenario || best.input.stage} · ${best.input.start} – ${best.input.end}`}>
            Best run
          </a>
          <span className="wb-gain">${formatNumber(metrics.net_pnl)} net</span>
          <span>{formatPercent(Math.abs(metrics.max_drawdown))} drawdown</span>
          <span>{formatNumber(metrics.trades)} {metrics.trades === 1 ? "trade" : "trades"}</span>
        </div>
      ) : row.config && <span className="wb-strategy-best">No qualifying run yet</span>}
    </div>
  );
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
  const groups = groupedResearchRows(listed);
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
              <ResearchGroupHeading id={`group-${group.id}`} title={group.title} hint={group.hint} count={group.rows.length} />
              <ul className="wb-strategy-rows">
                {shown.map((row) => {
                  const display = statusDisplay(row.status);
                  return (
                    <li key={row.id} className="wb-strategy-row">
                      <StrategyRowSummary row={row} attempts={attempts[row.id] || 0} />
                      <StageDots status={row.status} />
                      <StatusChip status={row.status} />
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
          const attempts = rowAttempts(state, row);
          const seed = attempts[0];
          return (
            <li key={row.id} className="wb-strategy-row">
              <StrategyRowSummary row={row} attempts={attempts.length} />
              <StageDots status={row.status} />
              <StatusChip status={row.status} />
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
