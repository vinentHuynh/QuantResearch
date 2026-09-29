import { useState } from "react";
import { strategyTitle } from "./strategyTitle";
import { StrategyTesting, type TestingActions } from "./StrategyTesting";
import { comparePromising, type TestingEvidence } from "./testingEvidence";
import {
  Alert,
  Badge,
  Button,
  Code,
  Drawer,
  Group,
  Paper,
  ScrollArea,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";

export type LibraryEntry = {
  python_counterparts?: string[];
  id: string;
  path: string;
  name: string;
  description: string;
  family: string;
  role: string;
  file_hash: string;
  functions: string[];
  status: string;
  requirements: string;
  adapters: { id: string; name: string; scope: string }[];
  arguments: { flags: string[]; options: Record<string, string> }[];
};
export type Library = {
  entries: LibraryEntry[];
  total: number;
  counts: Record<string, number>;
};

export function StrategyLibrary({
  library,
  configure,
  evidence,
  testingActions,
}: {
  library?: Library;
  configure: (id: string) => void;
  evidence: Record<string, TestingEvidence>;
  testingActions: TestingActions;
}) {
  const [search, setSearch] = useState("");
  const [family, setFamily] = useState<string | null>(null);
  const [role, setRole] = useState<string | null>(null);
  const [selected, setSelected] = useState<LibraryEntry | null>(null);
  const [source, setSource] = useState<{ id: string; text: string } | null>(
    null,
  );
  const [error, setError] = useState("");
  if (!library) return null;
  const bestEvidence = (entry: LibraryEntry) => entry.adapters.map(a => evidence[a.id]).filter(Boolean).sort(comparePromising)[0];
  const entries = library.entries.filter(
    (e) =>
      (!family || e.family === family) &&
      (!role || e.role === role) &&
      [e.path, e.name, e.description, e.family, ...e.functions]
        .join(" ")
        .toLowerCase()
        .includes(search.toLowerCase()),
  ).sort((a, b) => comparePromising(bestEvidence(a), bestEvidence(b)) || a.name.localeCompare(b.name));
  async function viewSource(entry: LibraryEntry) {
    setError("");
    try {
      const response = await fetch(`/api/workbench/library/${entry.id}/source`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.error);
      setSource({ id: entry.id, text: body.source });
    } catch (e) {
      setError(String(e));
    }
  }
  return (
    <Paper p="lg" withBorder>
      <Title order={3}>Consolidated strategy library</Title>
      <Text c="dimmed" size="sm" my="sm">
        {library.total} sources, most promising first. Open a source for implementation details.
      </Text>
      <Group mb="md" align="end">
        <TextInput
          label="Search strategy library"
          placeholder="Strategy, filename, or rule function"
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          style={{ flex: 1 }}
        />
        <Select
          label="Strategy family"
          clearable
          data={[...new Set(library.entries.map((e) => e.family))].sort()}
          value={family}
          onChange={setFamily}
        />
        <Select
          label="Source role"
          clearable
          data={Object.keys(library.counts).sort()}
          value={role}
          onChange={setRole}
        />
      </Group>
      <Text size="sm" mb="sm">
        Showing {entries.length} of {library.total} sources
      </Text>
      <ScrollArea>
        <Table striped highlightOnHover miw={850} className="strategy-library-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Source</Table.Th>
              <Table.Th>Family / role</Table.Th>
              <Table.Th>Most promising / stage</Table.Th>
              <Table.Th>Details</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {entries.map((e) => (
              <Table.Tr key={e.id}>
                <Table.Td>
                  <Text size="sm" fw={600} lineClamp={2}>
                    {strategyTitle(e.name)}
                  </Text>
                  <Code fz="xs">{e.path}</Code>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{e.family}</Text>
                  <Text size="xs" c="dimmed">
                    {e.role}
                  </Text>
                </Table.Td>
                <Table.Td>
                  {!e.adapters.length && <Badge
                    color={
                      e.adapters.length
                        ? "teal"
                        : e.status === "Adapter required"
                          ? "yellow"
                          : "gray"
                    }
                    variant="light"
                  >
                    {e.status}
                  </Badge>}
                  {[...e.adapters].sort((a,b) => comparePromising(evidence[a.id], evidence[b.id])).slice(0, 1).map(adapter => <div key={adapter.id}>
                    {e.adapters.length > 1 && <Text size="xs" c="dimmed">{strategyTitle(adapter.name)} · best of {e.adapters.length} adapters</Text>}
                    {evidence[adapter.id] ? <StrategyTesting compact evidence={evidence[adapter.id]} {...testingActions} /> : <Text size="xs">Adapter unavailable; testing evidence cannot be matched.</Text>}
                  </div>)}
                </Table.Td>
                <Table.Td>
                  <Button
                    variant="subtle"
                    size="xs"
                    onClick={() => {
                      setSelected(e);
                      setSource(null);
                      setError("");
                    }}
                    aria-label={`Inspect ${e.path}`}
                  >
                    Inspect source
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>
      <Drawer
        opened={!!selected}
        onClose={() => setSelected(null)}
        position="right"
        size="xl"
        title="Source and strategy lineage"
      >
        {selected && (
          <Stack>
            <Title order={3}>{strategyTitle(selected.name)}</Title>
            <Code>{selected.path}</Code>
            <Text size="xs" c="dimmed">
              SHA-256: {selected.file_hash}
            </Text>
            <Badge variant="light">{selected.status}</Badge>
            <Text style={{ whiteSpace: "pre-wrap" }} size="sm">
              {selected.description || "No module description."}
            </Text>
            <Alert title="Original workflow requirements" color="yellow">
              {selected.requirements}
            </Alert>
            {!!selected.python_counterparts?.length && (
              <>
                <Title order={4}>Existing Python counterparts</Title>
                {selected.python_counterparts.map((path) => (
                  <Code key={path}>{path}</Code>
                ))}
              </>
            )}
            {selected.adapters.map((adapter) => (
              <Paper withBorder p="md" key={adapter.id}>
                <Text fw={600}>{strategyTitle(adapter.name)}</Text>
                <Text size="sm" my="xs">
                  {adapter.scope}
                </Text>
                {evidence[adapter.id] && <StrategyTesting evidence={evidence[adapter.id]}
                  inspectRun={id => { setSelected(null); testingActions.inspectRun(id); }}
                  openEvaluation={id => { setSelected(null); testingActions.openEvaluation(id); }} />}
                <Button
                  variant="light"
                  onClick={() => {
                    setSelected(null);
                    configure(adapter.id);
                  }}
                >
                  Configure {strategyTitle(adapter.name)}
                </Button>
              </Paper>
            ))}
            <Title order={4}>Functions and rule variants</Title>
            <Text size="sm">
              {selected.functions.join(", ") || "No top-level functions."}
            </Text>
            <Title order={4}>Original parameters</Title>
            <Text size="sm" c="dimmed">
              These are source declarations for the original script. Use the
              adapter's form to launch a workbench run.
            </Text>
            {selected.arguments.map((arg, i) => (
              <Paper withBorder p="xs" key={i}>
                <Code>{arg.flags.join(", ")}</Code>
                <Text size="xs" style={{ whiteSpace: "pre-wrap" }}>
                  {Object.entries(arg.options)
                    .map(([k, v]) => `${k}: ${v}`)
                    .join("\n")}
                </Text>
              </Paper>
            ))}
            {!selected.arguments.length && (
              <Text size="sm">
                No parameter declarations found; inspect the original source for
                configuration.
              </Text>
            )}
            {error && <Alert color="red">{error}</Alert>}
            <Button variant="light" onClick={() => void viewSource(selected)}>
              Read original source
            </Button>
            {source?.id === selected.id && <Code block>{source.text}</Code>}
          </Stack>
        )}
      </Drawer>
    </Paper>
  );
}
