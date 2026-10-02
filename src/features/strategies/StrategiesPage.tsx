import { useState } from "react";
import { Alert, Button, Code, Select, SimpleGrid, Text, TextInput, Title } from "@mantine/core";
import { IconArrowUpRight, IconRefresh } from "@tabler/icons-react";
import { comparePromising, testingEvidence } from "../../../shared/ts/evidence.ts";
import { href } from "../../app/navigation";
import { workbenchRequest as request } from "../../shared/api/workbench";
import { strategyTitle } from "../../shared/formatting/strategyTitle";
import { PageHeader } from "../../shared/ui/PageHeader";
import { StrategyTesting } from "../evaluations/StrategyTesting";
import { WorkbenchAlerts } from "../workspace/WorkbenchChrome";
import type { WorkbenchController } from "../workspace/useWorkbenchController";
import { StrategyLibrary } from "./StrategyLibrary";
import "./strategies.css";

export function StrategiesPage({ controller }: { controller: WorkbenchController }) {
  const [search, setSearch] = useState("");
  const [archiveSearch, setArchiveSearch] = useState("");
  const {
    action,
    busy,
    configure,
    go,
    inspect,
    route,
    setNotice,
    setResearchSelection,
    setTestingMarket,
    state,
    testingMarket,
  } = controller;
  if (!state) return null;
  const library = route.sub === "library";
  const archived = route.sub === "archive";
  const archivedScripts = state.archived_scripts || [];
  const visibleArchivedScripts = [...archivedScripts]
    .filter(script => `${script.name} ${script.id} ${script.original_path} ${script.archive_path}`.toLowerCase().includes(archiveSearch.toLowerCase()))
    .sort((left, right) => right.archived_at.localeCompare(left.archived_at) || left.name.localeCompare(right.name));
  const evidence = Object.fromEntries(
    state.strategies.map((strategy) => [
      strategy.id,
      testingEvidence(strategy, state.runs, state.evaluations || [], testingMarket),
    ]),
  );
  const testingActions = {
    inspectRun: (id: string) => {
      const run = state.runs.find((candidate) => candidate.id === id);
      if (run) void action(() => inspect(run));
    },
    openEvaluation: (id: string) => {
      setResearchSelection(id);
      go("evaluations");
    },
  };
  return (
    <>
      <PageHeader
        crumb="Sources"
        title="Scripts & library"
        actions={
          <Button
            variant="default"
            size="xs"
            leftSection={<IconRefresh size={14} />}
            onClick={() =>
              void action(async () => {
                await request("/discover", {});
                setNotice("Strategy folder scanned.");
              })
            }
          >
            Scan scripts
          </Button>
        }
        tabsLabel="Script views"
        tabs={[
          { label: "Runnable scripts", count: state.strategies.length, active: !library && !archived, href: href("scripts") },
          { label: "Library", count: state.library?.total, active: library, href: href("scripts", "library") },
          { label: "Archive", count: archivedScripts.length, active: archived, href: href("scripts", "archive") },
        ]}
      />
      <WorkbenchAlerts controller={controller} />
      <div className="wb-content scripts-page">
        <div className="scripts-toolbar">
          {!library && <TextInput
            aria-label={archived ? "Search archived scripts" : "Search runnable strategies"}
            placeholder={archived ? "Search archive" : "Search scripts"}
            value={archived ? archiveSearch : search}
            onChange={event => archived ? setArchiveSearch(event.currentTarget.value) : setSearch(event.currentTarget.value)}
          />}
          {!archived && <Select
            aria-label="Testing evidence market"
            value={testingMarket}
            onChange={(value) => setTestingMarket(value || "")}
            data={[
              { value: "", label: "All markets" },
              ...[...new Set(state.datasets.map((dataset) => dataset.symbol))]
                .sort()
                .map((symbol) => ({ value: symbol, label: symbol })),
            ]}
          />}
          {!library && !archived && <details className="scripts-create">
            <summary>Create your next strategy</summary>
            <div className="scripts-create-body">
              <Text size="sm">
                Copy <Code>strategies/_template.py</Code> to <Code>strategies/my_strategy.py</Code>, give it a unique <Code>STRATEGY['id']</Code>, and implement <Code>signals(bars, parameters)</Code>. The workbench picks it up automatically within five seconds.
              </Text>
              <Text size="sm" c="dimmed" mt="xs">
                The template documents signal timing, parameters, and helper imports. Source snapshots preserve registered scripts and local helpers when you launch. Existing scripts can be wrapped by this small adapter.
              </Text>
            </div>
          </details>}
        </div>
        {library ? (
          <StrategyLibrary library={state.library} configure={configure} evidence={evidence} testingActions={testingActions} />
        ) : archived ? (
          visibleArchivedScripts.length ? (
            <SimpleGrid className="scripts-grid" cols={{ base: 1, lg: 2 }} spacing="sm">
              {visibleArchivedScripts.map(script => (
                  <section className="wb-card scripts-strategy-card" key={script.id}>
                    <div className="scripts-strategy-heading">
                      <Title order={3}>{strategyTitle(script.name)}</Title>
                      <Text size="xs" c="dimmed">Archived {new Date(script.archived_at).toLocaleString()}</Text>
                    </div>
                    <Text size="xs" c="dimmed" mt="sm" className="scripts-archive-path">Stored at <Code>{script.archive_path}</Code></Text>
                    <Text size="xs" c="dimmed" className="scripts-archive-path">Original location <Code>{script.original_path}</Code></Text>
                    <div className="scripts-strategy-actions">
                      <Button
                        size="xs"
                        variant="light"
                        disabled={busy}
                        onClick={() => void action(async () => {
                          await request("/scripts/restore", { id: script.id });
                          setNotice(`${strategyTitle(script.name)} restored.`);
                        })}
                      >
                        Restore script
                      </Button>
                    </div>
                  </section>
                ))}
            </SimpleGrid>
          ) : (
            <div className="wb-empty"><Text>{archivedScripts.length ? "No archived scripts match this search." : "No archived scripts yet."}</Text></div>
          )
        ) : (
          <>
            {state.errors.map((error, index) => (
              <Alert key={index} color="red" title={error.file || "Discovery error"}>{error.error}</Alert>
            ))}
            <SimpleGrid className="scripts-grid" cols={{ base: 1, lg: 2 }} spacing="sm">
              {[...state.strategies]
                .filter(strategy => `${strategy.name} ${strategy.description} ${strategy.id}`.toLowerCase().includes(search.toLowerCase()))
                .sort(
                  (left, right) =>
                    comparePromising(evidence[left.id], evidence[right.id]) ||
                    left.name.localeCompare(right.name),
                )
                .map((strategy) => {
                  const summary = evidence[strategy.id];
                  const bestRunId = summary.best?.run.id;
                  return (
                  <section className="wb-card scripts-strategy-card" key={strategy.id}>
                    <div className="scripts-strategy-heading">
                      <Title order={3}>{strategyTitle(strategy.name)}</Title>
                      <Text size="xs" c="dimmed">{summary.configurations.length} configurations · {summary.failingConfigurations} failed · {summary.total} attempts</Text>
                    </div>
                    <StrategyTesting runnableCard evidence={summary} {...testingActions} />
                    <div className="scripts-strategy-actions">
                      <Button
                        size="xs"
                        variant="light"
                        rightSection={<IconArrowUpRight size={15} />}
                        onClick={() => configure(strategy.id)}
                      >
                        Configure run
                      </Button>
                      {bestRunId && <Button size="compact-xs" variant="subtle" onClick={() => testingActions.inspectRun(bestRunId)}>Inspect best run</Button>}
                      <Button component="a" href={href("workspace")} size="compact-xs" variant="subtle">Research history</Button>
                      <Button
                        size="compact-xs"
                        variant="subtle"
                        disabled={busy}
                        onClick={() => void action(async () => {
                          await request("/scripts/archive", { id: strategy.id });
                          setNotice(`${strategyTitle(strategy.name)} archived. Find it in Archive.`);
                          go("scripts", "archive");
                        })}
                      >
                        Archive script
                      </Button>
                    </div>
                  </section>
                  );
                })}
            </SimpleGrid>
          </>
        )}
      </div>
    </>
  );
}
