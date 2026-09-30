import { Alert, Button, Code, Group, Select, SimpleGrid, Text, Title } from "@mantine/core";
import { IconArrowUpRight, IconRefresh } from "@tabler/icons-react";
import { comparePromising, testingEvidence } from "../../../shared/ts/evidence.ts";
import { href } from "../../app/navigation";
import { workbenchRequest as request } from "../../shared/api/workbench";
import { strategyTitle } from "../../shared/formatting/strategyTitle";
import { PageHeader } from "../../shared/ui/PageHeader";
import { StrategyTesting } from "../evaluations/StrategyTesting";
import { WorkbenchAlerts } from "../workspace/WorkbenchChrome";
import type { WorkbenchController } from "../workspace/useWorkbenchController";
import { shortId } from "../workspace/workbenchModel";
import { StrategyLibrary } from "./StrategyLibrary";

export function StrategiesPage({ controller }: { controller: WorkbenchController }) {
  const {
    action,
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
          { label: "Runnable scripts", count: state.strategies.length, active: !library, href: href("scripts") },
          { label: "Library", count: state.library?.total, active: library, href: href("scripts", "library") },
        ]}
      />
      <WorkbenchAlerts controller={controller} />
      <div className="wb-content">
        <Group justify="space-between" align="end" mb="md">
          <Text size="sm" c="dimmed">Most promising first — validation strength, then return / drawdown.</Text>
          <Select
            label="Testing evidence market"
            value={testingMarket}
            onChange={(value) => setTestingMarket(value || "")}
            data={[
              { value: "", label: "All markets" },
              ...[...new Set(state.datasets.map((dataset) => dataset.symbol))]
                .sort()
                .map((symbol) => ({ value: symbol, label: symbol })),
            ]}
          />
        </Group>
        {library ? (
          <StrategyLibrary library={state.library} configure={configure} evidence={evidence} testingActions={testingActions} />
        ) : (
          <>
            <details className="wb-card">
              <summary>Create your next strategy</summary>
              <Text size="sm" mt="xs">
                Copy <Code>strategies/_template.py</Code> to <Code>strategies/my_strategy.py</Code>, give it a unique <Code>STRATEGY['id']</Code>, and implement <Code>signals(bars, parameters)</Code>. The workbench picks it up automatically within five seconds.
              </Text>
              <Text size="sm" c="dimmed" mt="xs">
                The template documents signal timing, parameters, and helper imports. Source snapshots preserve registered scripts and local helpers when you launch. Existing scripts can be wrapped by this small adapter.
              </Text>
            </details>
            {state.errors.map((error, index) => (
              <Alert key={index} color="red" title={error.file || "Discovery error"}>{error.error}</Alert>
            ))}
            <SimpleGrid cols={{ base: 1, md: 2 }}>
              {[...state.strategies]
                .sort(
                  (left, right) =>
                    comparePromising(evidence[left.id], evidence[right.id]) ||
                    left.name.localeCompare(right.name),
                )
                .map((strategy) => (
                  <section className="wb-card" key={strategy.id}>
                    <Group justify="space-between" wrap="nowrap" align="start">
                      <Title order={3}>{strategyTitle(strategy.name)}</Title>
                    </Group>
                    <StrategyTesting evidence={evidence[strategy.id]} {...testingActions} />
                    <details className="script-source-details">
                      <summary>Script details</summary>
                      <Text size="sm" c="dimmed" my="sm">{strategy.description}</Text>
                      {strategy.migration_scope && <Text size="xs" mb="sm">{strategy.migration_scope}</Text>}
                      <Text size="xs"><Code>{strategy.file}</Code> · {shortId(strategy.file_hash)}</Text>
                      <Text size="sm" mt="sm">{strategy.timeframes.join(" · ")}</Text>
                      <Text size="xs" c="dimmed" mt="xs">{Object.keys(strategy.parameters).join(", ")}</Text>
                      <Text size="xs" mt="sm">
                        Last successful run:{" "}
                        {state.runs
                          .find((run) => run.input.strategy.id === strategy.id && run.status === "Succeeded")
                          ?.ended_at?.slice(0, 19)
                          .replace("T", " ") || "No runs yet"}
                      </Text>
                    </details>
                    <Button
                      mt="md"
                      variant="light"
                      rightSection={<IconArrowUpRight size={15} />}
                      onClick={() => configure(strategy.id)}
                    >
                      Configure run
                    </Button>
                  </section>
                ))}
            </SimpleGrid>
          </>
        )}
      </div>
    </>
  );
}
