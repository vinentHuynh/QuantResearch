import { Alert, Badge, Button, Code, ScrollArea, Table, Text } from "@mantine/core";
import { IconDatabase } from "@tabler/icons-react";
import { workbenchRequest as request } from "../../shared/api/workbench";
import { PageHeader } from "../../shared/ui/PageHeader";
import { WorkbenchAlerts } from "../workspace/WorkbenchChrome";
import type { WorkbenchController } from "../workspace/useWorkbenchController";
import { shortId } from "../workspace/workbenchModel";

export function DatasetsPage({ controller }: { controller: WorkbenchController }) {
  const { action, setNotice, state } = controller;
  if (!state) return null;
  return (
    <>
      <PageHeader
        crumb="Sources"
        title="Datasets"
        actions={
          <Button
            size="xs"
            leftSection={<IconDatabase size={14} />}
            loading={state.import.status === "Running"}
            onClick={() =>
              void action(async () => {
                await request("/import", {});
                setNotice("Dataset import started. Progress appears below.");
              })
            }
          >
            Import data ZIPs
          </Button>
        }
      />
      <WorkbenchAlerts controller={controller} />
      <div className="wb-content">
        <section className="wb-card">
          <h2>Local archive ingestion</h2>
          <p className="wb-card-sub">
            Import scans ZIP files under data/. Existing versions are reused; changed archives create new versions.
          </p>
          {state.import.log && <Code block mt="md" className="wb-log">{state.import.log}</Code>}
          {state.import.error && <Alert color="red" mt="md">{state.import.error}</Alert>}
        </section>
        <section className="wb-table-card">
          <ScrollArea>
            <Table miw={1000} verticalSpacing="md">
              <Table.Thead>
                <Table.Tr>
                  {["Market / source", "Version", "Coverage (UTC)", "Bars", "Quality", ""].map((heading) => (
                    <Table.Th key={heading}>{heading}</Table.Th>
                  ))}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {state.datasets.map((dataset) => (
                  <Table.Tr key={dataset.id}>
                    <Table.Td>
                      <Text fw={600}>{dataset.symbol}</Text>
                      <Text c="dimmed" size="xs">{dataset.source} · 1m</Text>
                    </Table.Td>
                    <Table.Td>
                      <Code>{shortId(dataset.id)}</Code>
                      <Text size="xs" c="dimmed">{dataset.registered_at.slice(0, 10)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{dataset.first.slice(0, 10)} → {dataset.last.slice(0, 10)}</Text>
                      <Text size="xs" c="dimmed">Last bar: {dataset.last}</Text>
                    </Table.Td>
                    <Table.Td>{dataset.rows.toLocaleString()}</Table.Td>
                    <Table.Td>
                      <Badge color="yellow" variant="light" radius="xs">Validated with limitations</Badge>
                      <Text size="xs" c="dimmed">
                        {dataset.quality.gaps_over_one_minute.toLocaleString()} gaps · {dataset.quality.contract_changes} contract changes
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <details>
                        <summary>Provenance</summary>
                        <Text size="xs">{dataset.archive}</Text>
                        <Code block>{JSON.stringify(dataset.quality, null, 2)}</Code>
                        <Text size="xs" className="wb-break">SHA256 {dataset.checksum}</Text>
                        {dataset.warnings.map((warning) => <Text key={warning} size="xs" mt="xs">{warning}</Text>)}
                      </details>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>
          {!state.datasets.length && (
            <div className="wb-empty"><Text>No registered datasets. Import the local ZIP archives to begin.</Text></div>
          )}
        </section>
      </div>
    </>
  );
}
