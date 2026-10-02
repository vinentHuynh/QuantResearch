import { useState } from "react";
import {
  Badge,
  Button,
  Checkbox,
  Group,
  Menu,
  Popover,
  ScrollArea,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import {
  IconArchive,
  IconArrowDown,
  IconArrowUp,
  IconArrowsSort,
  IconDots,
  IconFlask,
  IconPlayerPlay,
  IconPlus,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import type { Metrics, RunInput } from "../../../shared/ts/workbenchModels.ts";
import { archivedConfigurationForRun, isRunArchived } from "../../../shared/ts/researchArchive.ts";
import { href } from "../../app/navigation";
import { workbenchRequest as request } from "../../shared/api/workbench";
import { strategyTitle } from "../../shared/formatting/strategyTitle";
import { PageHeader } from "../../shared/ui/PageHeader";
import { RunStageBadge } from "../../shared/ui/StrategyStageBadge";
import { useStrategyStages } from "../../shared/ui/strategyStageContext";
import { strategyStageLabels } from "../../../shared/ts/strategyLifecycle.ts";
import { NqMonthlyComparison } from "../datasets/NqMonthlyComparison";
import { RefreshButton, WorkbenchAlerts } from "../workspace/WorkbenchChrome";
import type { WorkbenchController } from "../workspace/useWorkbenchController";
import { formatNumber, formatPercent, shortId, statusTone } from "../workspace/workbenchModel";
import { canAddRunToPortfolio, canArchiveRun, runSortColumns, runSortOptions, runtimeSeconds } from "./model";

export function RunsPage({ controller }: { controller: WorkbenchController }) {
  const { statuses } = useStrategyStages();
  const [stageFilter, setStageFilter] = useState("all");
  const {
    action,
    activeRuns,
    addRunToPortfolio,
    archiveRuns,
    archivedRuns,
    archiveView,
    busy,
    compareRuns,
    comparison,
    counts,
    dashboardRefresh,
    filter,
    filtered: unfiltered,
    go,
    inspect,
    latestHistory,
    route,
    restoreRuns,
    restoreRunConfiguration,
    selected,
    setComparison,
    setDeletion,
    setError,
    setFilter,
    setSelected,
    setShowAllAttempts,
    setSort,
    setStage,
    setStatus,
    setViewName,
    setViewOpen,
    showAllAttempts,
    sort,
    sortDirection,
    sortColumn,
    stage,
    state,
    status,
    viewName,
    viewOpen,
  } = controller;
  if (!state) return null;
  const filtered = unfiltered.filter(run => stageFilter === "all" || statuses.byRun.get(run.id)?.kind === stageFilter);
  const selectedRuns = filtered.filter(run => selected.includes(run.id));
  const visibleSelected = selectedRuns.map(run => run.id);
  const compareBlocked = busy || selectedRuns.length < 2 || selectedRuns.length > 8 || selectedRuns.some(run => run.status !== "Succeeded");
  const archiveBlocked = busy || !selectedRuns.length || selectedRuns.some(run => !canArchiveRun(run));
  const explicitArchiveIds = new Set(state.research_archive?.runs.map(run => run.id) || []);
  const restoreBlocked = busy || !selectedRuns.length || selectedRuns.some(run => !explicitArchiveIds.has(run.id));
  const clearRuns = archiveView ? archivedRuns : activeRuns;
  const comparedArchiveIds = compareRuns.filter(run => !isRunArchived(run, state.research_archive)).map(run => run.id);
  const activeView = state.views.find(
    (view) => view.filter === filter && view.stage === stage && view.status === status,
  );
  const experiments = route.sub === "experiments";
  const monthly = route.sub === "nq-monthly";
  const sortKey = sortColumn.key;
  const now = Date.now();

  return (
    <>
      <PageHeader
        crumb="Research"
        title="Runs & compare"
        actions={
          <>
            <RefreshButton controller={controller} />
            <Menu position="bottom-end" withinPortal>
              <Menu.Target><Button variant="default" size="xs" aria-label="More run actions"><IconDots size={15} /></Button></Menu.Target>
              <Menu.Dropdown>
                <Menu.Item leftSection={<IconPlayerPlay size={14} />} component="a" href={href("new-run")}>New run</Menu.Item>
                <Menu.Divider />
                <Menu.Item
                  color="red"
                  leftSection={<IconTrash size={14} />}
                  disabled={!clearRuns.length || busy}
                  onClick={() => void action(async () =>
                    setDeletion(await request("/runs/delete-preview", { ids: clearRuns.map((run) => run.id) })),
                  )}
                >
                  {archiveView ? "Clear all archived runs" : "Clear all active runs"}
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </>
        }
        tabsLabel="Run views"
        tabs={[
          {
            label: showAllAttempts ? "All attempts" : "Latest history",
            count: showAllAttempts ? activeRuns.length : latestHistory.length,
            active: !archiveView && !experiments && !monthly && !activeView,
            onClick: () => {
              if (!archiveView) {
                setFilter("");
                setStage("");
                setStatus("");
              }
              go("runs");
            },
          },
          { label: "Archive", count: archivedRuns.length, active: archiveView, href: href("runs", "archive") },
          { label: "NQ monthly", active: monthly, href: href("runs", "nq-monthly") },
          { label: "Experiments", count: state.experiments.length, active: experiments, href: href("runs", "experiments") },
          ...state.views.map((view) => ({
            label: view.name,
            active: !archiveView && !experiments && !monthly && activeView?.id === view.id,
            onClick: () => {
              setFilter(view.filter);
              setStage(view.stage);
              setStatus(view.status);
              go("runs");
            },
          })),
        ]}
        tabsExtra={
          !archiveView && !experiments && !monthly && (
            <Popover opened={viewOpen} onChange={setViewOpen} position="bottom-start" withinPortal>
              <Popover.Target>
                <button type="button" className="wb-tab-action" onClick={() => setViewOpen((open) => !open)}>
                  <IconPlus size={13} />Save current view
                </button>
              </Popover.Target>
              <Popover.Dropdown>
                <Stack gap="xs" w={240}>
                  <TextInput label="View name" placeholder="Name this view" value={viewName} onChange={(event) => setViewName(event.currentTarget.value)} />
                  <Text size="xs" c="dimmed">Saves the current search, run purpose and execution filters.</Text>
                  <Button
                    size="xs"
                    disabled={!viewName}
                    onClick={() => void action(async () => {
                      await request("/views", { name: viewName, filter, stage, status });
                      setViewName("");
                      setViewOpen(false);
                    })}
                  >
                    Save view
                  </Button>
                </Stack>
              </Popover.Dropdown>
            </Popover>
          )
        }
      />
      <WorkbenchAlerts controller={controller} />
      {monthly ? (
        <NqMonthlyComparison
          refreshKey={dashboardRefresh}
          onInspect={(id) => {
            const run = state.runs.find((candidate) => candidate.id === id);
            if (run) void action(() => inspect(run));
            else setError(`Saved run ${id} is no longer in the Workbench.`);
          }}
        />
      ) : experiments ? (
        <div className="wb-content">
          <p className="wb-context">All attempted variants remain recorded, including failed and losing runs.</p>
          <div className="wb-card">
            <h2>Experiment history</h2>
            {state.experiments.map((experiment) => (
              <Group key={experiment.id} justify="space-between" className="wb-history" wrap="nowrap">
                <Text size="sm">
                  {experiment.hypothesis || "Unlabeled experiment"}{" "}
                  <Text component="span" c="dimmed" size="xs">{shortId(experiment.id)}</Text>
                </Text>
                <Badge variant="light" color="gray">{experiment.attempted_variants} variants launched</Badge>
              </Group>
            ))}
            {!state.experiments.length && <Text c="dimmed" size="sm" py="md">No experiments recorded yet.</Text>}
          </div>
        </div>
      ) : (
        <div className="wb-content">
          <div className="wb-toolbar">
            <TextInput aria-label="Search runs" placeholder="Strategy, market, tags, or run ID" value={filter} onChange={(event) => setFilter(event.currentTarget.value)} />
            <Select aria-label="Strategy stage filter" placeholder="All strategy stages" value={stageFilter} onChange={value => { setStageFilter(value || "all"); setSelected([]); }} data={[{ value: "all", label: "All strategy stages" }, ...Object.entries(strategyStageLabels).map(([value, label]) => ({ value, label }))]} />
            <Select aria-label="Run purpose" placeholder="All run purposes" clearable data={["Exploratory", "Evaluation", "Tracking"]} value={stage || null} onChange={(value) => setStage(value || "")} />
            <Select aria-label="Execution" placeholder="All statuses" clearable data={["Queued", "Running", "Summarizing", "Succeeded", "Failed", "Canceled", "Interrupted"]} value={status || null} onChange={(value) => setStatus(value || "")} />
            <Select aria-label="Sort" data={runSortOptions} value={sort} onChange={(value) => setSort(value || "created:desc")} />
            {!archiveView && <Switch size="sm" label="All attempts" checked={showAllAttempts} onChange={(event) => setShowAllAttempts(event.currentTarget.checked)} />}
            <span className="wb-toolbar-note">{state.limits.concurrency} workers · up to {state.limits.maxBatch} jobs per launch</span>
          </div>
          <div className="wb-statline">
            <span><b>{counts.total}</b> {archiveView ? "archived attempts" : "recorded"}</span>
            <span><b>{counts.active}</b> in progress</span>
            <span><b>{counts.success}</b> succeeded</span>
            <span><b>{state.datasets.length}</b> dataset versions</span>
            {filtered.length !== counts.total && <span><b>{filtered.length}</b> shown</span>}
          </div>
          {archiveView && <Text size="sm" c="dimmed" mb="md">Archived runs remain available for inspection and comparison. Restore a run or its archived configuration to show it in active history.</Text>}
          <section className="wb-table-card" aria-label="Run ledger">
            <ScrollArea>
              <Table miw={1100} highlightOnHover verticalSpacing="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th />
                    {runSortColumns.slice(1).map((column) => (
                      <Table.Th
                        key={column.key}
                        ta={column.numeric ? "right" : undefined}
                        aria-sort={sortKey === column.key ? sortDirection === "asc" ? "ascending" : "descending" : "none"}
                      >
                        <button
                          type="button"
                          className={`wb-sort-header${column.numeric ? " wb-sort-numeric" : ""}`}
                          title={`Sort ${column.label} ${sortKey === column.key && sortDirection === "asc" ? "descending" : "ascending"}`}
                          onClick={() => setSort(`${column.key}:${sortKey === column.key && sortDirection === "asc" ? "desc" : "asc"}`)}
                        >
                          {column.label}
                          {sortKey !== column.key ? <IconArrowsSort size={14} aria-hidden="true" /> : sortDirection === "asc" ? <IconArrowUp size={14} aria-hidden="true" /> : <IconArrowDown size={14} aria-hidden="true" />}
                        </button>
                      </Table.Th>
                    ))}
                    <Table.Th />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {filtered.map((run) => (
                    <Table.Tr key={run.id} className={`wb-run-row${selected.includes(run.id) ? " selected" : ""}`} onClick={() => void action(() => inspect(run))}>
                      <Table.Td onClick={(event) => event.stopPropagation()}>
                        <Checkbox
                          aria-label={`Compare ${run.id}`}
                          disabled={busy || !canArchiveRun(run)}
                          checked={selected.includes(run.id)}
                          onChange={(event) => {
                            const checked = event.currentTarget.checked;
                            setSelected((current) => checked ? [...current, run.id] : current.filter((id) => id !== run.id));
                          }}
                        />
                      </Table.Td>
                      <Table.Td>
                        <Text fw={600} size="sm">{strategyTitle(run.input.strategy.name)}</Text>
                        <RunStageBadge runId={run.id} showFinding />
                        <Text size="xs" c="dimmed" ff="monospace">{shortId(run.id)} · code {shortId(run.input.source_hash)}</Text>
                        {run.tags && <Text size="xs">{run.tags}</Text>}
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">{run.input.dataset.symbol} · {run.input.timeframe}</Text>
                        <Text size="xs" c="dimmed">{run.input.start} → {run.input.end}</Text>
                      </Table.Td>
                      <Table.Td><Badge color={run.input.stage === "Evaluation" ? "violet" : "gray"} variant="light" radius="xs">{run.input.stage}</Badge></Table.Td>
                      <Table.Td><Badge color={statusTone(run.status)} variant="light" radius="xs">{run.status}</Badge></Table.Td>
                      <Table.Td ta="right" className={`mono ${(run.result?.metrics.net_return || 0) < 0 ? "wb-loss" : "wb-gain"}`}>{formatPercent(run.result?.metrics.net_return)}</Table.Td>
                      <Table.Td ta="right" className="mono">{formatPercent(run.result?.metrics.max_drawdown)}</Table.Td>
                      <Table.Td ta="right">{formatNumber(run.result?.metrics.trades)}</Table.Td>
                      <Table.Td ta="right" c="dimmed">{run.started_at ? `${runtimeSeconds(run, now)!.toFixed(1)}s` : "—"}</Table.Td>
                      <Table.Td onClick={(event) => event.stopPropagation()}>
                        <Group gap="xs" wrap="nowrap">
                          <Button variant="subtle" size="compact-sm" onClick={() => void action(() => inspect(run))}>Inspect</Button>
                          {canAddRunToPortfolio(run) && <Button variant="light" size="compact-sm" onClick={() => addRunToPortfolio(run.id)}>Add this run</Button>}
                          {!archiveView && <Button variant="subtle" color="gray" size="compact-sm" leftSection={<IconArchive size={14} />} disabled={busy || !canArchiveRun(run)} onClick={() => void archiveRuns([run.id])}>Archive</Button>}
                          {archiveView && explicitArchiveIds.has(run.id) && <Button variant="light" size="compact-sm" disabled={busy} onClick={() => void restoreRuns([run.id])}>Restore</Button>}
                          {archiveView && archivedConfigurationForRun(run, state.research_archive) && <Button variant="light" size="compact-sm" disabled={busy} onClick={() => void restoreRunConfiguration(run.id)}>Restore configuration</Button>}
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea>
            {!filtered.length && (
              <div className="wb-empty">
                <IconFlask size={36} />
                <Title order={3} mt="sm">{archiveView ? archivedRuns.length ? "No matching archived runs" : "No archived runs" : activeRuns.length ? "No matching runs" : archivedRuns.length ? "No active runs" : "A clean research notebook"}</Title>
                <Text c="dimmed" size="sm" mt="xs">{archiveView ? archivedRuns.length ? "Change the filters to see more archived attempts." : "Runs you archive will appear here for inspection or restoration." : activeRuns.length ? "Change the filters to see more experiments." : archivedRuns.length ? "Restore a run from Archive or launch a new experiment." : "Register your local ZIP data, choose a script, and launch your first experiment."}</Text>
                {!archiveView && <Button mt="md" variant="light" component="a" href={!activeRuns.length && archivedRuns.length ? href("runs", "archive") : href(state.datasets.length ? "new-run" : "datasets")}>{!activeRuns.length && archivedRuns.length ? "View archive" : state.datasets.length ? "Configure a run" : "Open datasets"}</Button>}
              </div>
            )}
          </section>
          {visibleSelected.length > 0 && (
            <div className="wb-selection-bar" role="toolbar" aria-label="Selected runs">
              <span className="count">{visibleSelected.length} selected</span>
              <button
                type="button"
                className="primary"
                disabled={compareBlocked}
                onClick={() => void action(async () => setComparison(await request("/compare", { ids: visibleSelected, mode: "as-run" })))}
              >
                Compare as run
              </button>
              <button
                type="button"
                disabled={compareBlocked}
                onClick={() => void action(async () => setComparison(await request("/compare", { ids: visibleSelected, mode: "aligned" })))}
              >
                Align evaluation interval
              </button>
              <button type="button" disabled={archiveView ? restoreBlocked : archiveBlocked} onClick={() => void (archiveView ? restoreRuns(visibleSelected) : archiveRuns(visibleSelected))} title={archiveView && restoreBlocked && !busy ? "Use Restore configuration on rows archived with their configuration." : undefined}>
                {archiveView ? "Restore selected" : "Archive selected"}
              </button>
              <button
                type="button"
                className="danger"
                disabled={busy}
                onClick={() => void action(async () => setDeletion(await request("/runs/delete-preview", { ids: visibleSelected })))}
              >
                Delete selected
              </button>
              <button type="button" className="clear" aria-label="Clear selection" onClick={() => setSelected([])}><IconX size={14} /></button>
            </div>
          )}
          {comparison && (
            <section className="wb-card">
              <div className="wb-card-head">
                <Title order={2} className="wb-comparison-title" fz={16}>{comparison.mode} comparison</Title>
                <Group gap="xs">
                  <Button size="xs" variant="light" leftSection={<IconArchive size={14} />} disabled={busy || !comparedArchiveIds.length || compareRuns.some(run => !canArchiveRun(run))} onClick={() => void archiveRuns(comparedArchiveIds)}>Archive compared runs</Button>
                  <Button size="xs" variant="subtle" onClick={() => setComparison(null)}>Close comparison</Button>
                </Group>
              </div>
              <Text size="sm" c="dimmed" mb="sm">
                {comparison.boundary || "Original windows and accounting assumptions are shown below. Different assumptions require new runs for a fair comparison."}
              </Text>
              {comparison.start && <Text size="sm">{comparison.start} → {comparison.end}</Text>}
              <ScrollArea>
                <Table miw={850}>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Input / result</Table.Th>
                      {compareRuns.map((run) => <Table.Th key={run.id}>{run.input.dataset.symbol} · {shortId(run.id)}</Table.Th>)}
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {["window", "stage", "timeframe", "session", "capital", "fee", "slippage", "delay_bars", "parameters", "source_hash", "dataset", "net_return", "max_drawdown", "sharpe", "trades"].map((key) => {
                      const values = compareRuns.map((run) => {
                        const metrics = comparison.rows?.find((row) => row.id === run.id)?.metrics || run.result!.metrics;
                        if (key in metrics) {
                          const value = metrics[key as keyof Metrics];
                          return ["net_return", "max_drawdown"].includes(key) ? formatPercent(value as number) : formatNumber(value as number);
                        }
                        if (key === "window") return `${run.input.start} → ${run.input.end}`;
                        if (key === "dataset") return shortId(run.input.dataset.id);
                        return typeof run.input[key as keyof RunInput] === "object"
                          ? JSON.stringify(run.input[key as keyof RunInput])
                          : String(run.input[key as keyof RunInput]);
                      });
                      return (
                        <Table.Tr key={key} className={new Set(values).size > 1 ? "wb-difference" : ""}>
                          <Table.Td>{key.replaceAll("_", " ")}</Table.Td>
                          {values.map((value, index) => <Table.Td key={index}>{value}</Table.Td>)}
                        </Table.Tr>
                      );
                    })}
                  </Table.Tbody>
                </Table>
              </ScrollArea>
              <Text size="xs" c="dimmed" mt="sm">Highlighted rows differ. Undefined statistics are shown as —.</Text>
            </section>
          )}
        </div>
      )}
    </>
  );
}
