import type { Dispatch, SetStateAction } from "react";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Chip,
  Group,
  ScrollArea,
  SegmentedControl,
  Select,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import type { CollectiveCatalog, CollectiveItem } from "../../../shared/ts/portfolio.ts";
import { collectiveProgress, stageColor } from "../../../shared/ts/progress.ts";
import { formatMoney as money, valueTone as tone, type CollectiveSettings } from "./collectiveViewModel";

export function StrategyPickerControls({
  catalog,
  choose,
  filter,
  hidden,
  isMobile,
  markets,
  search,
  selected,
  setFilter,
  setMarkets,
  setPickerOpen,
  setSearch,
  setTimeframe,
  settings,
  timeframe,
  visible,
}: {
  catalog: CollectiveCatalog;
  choose: (copies: Record<string, number>) => void;
  filter: string;
  hidden: CollectiveItem[];
  isMobile: boolean;
  markets: string[];
  search: string;
  selected: CollectiveItem[];
  setFilter: Dispatch<SetStateAction<string>>;
  setMarkets: Dispatch<SetStateAction<string[]>>;
  setPickerOpen: Dispatch<SetStateAction<boolean>>;
  setSearch: Dispatch<SetStateAction<string>>;
  setTimeframe: Dispatch<SetStateAction<string>>;
  settings: CollectiveSettings;
  timeframe: string;
  visible: CollectiveItem[];
}) {
  const counts = {
    working: catalog.items.filter((item) => item.working).length,
    feasible: catalog.items.filter((item) => item.feasible).length,
    backtested: catalog.items.filter((item) => !item.working && !item.benchmark).length,
  };
  return (
    <div className="collective-picker">
      <Text size="sm" c="dimmed">
        Pick tested configurations for this combination. Filters only change what you see here; books you already chose stay in the combination.
      </Text>
      <SegmentedControl
        aria-label="Eligibility filter"
        fullWidth
        orientation={isMobile ? "vertical" : "horizontal"}
        value={filter}
        onChange={setFilter}
        data={[
          { value: "working", label: `Evaluation passed · ${counts.working}` },
          { value: "feasible", label: `Robustness checked · ${counts.feasible}` },
          { value: "all", label: `All tested · ${catalog.items.length}` },
          { value: "backtested", label: `Backtested only · ${counts.backtested}` },
        ]}
      />
      <Text size="xs" c="dimmed">Stages apply to each market and configuration. Recorded findings remain in Review notes.</Text>
      <div className="collective-filters">
        <Group gap={6} align="center">
          <Text size="sm" fw={600} mr={4}>Markets</Text>
          <Chip size="sm" checked={!markets.length} onChange={() => setMarkets([])}>All</Chip>
          <Chip.Group multiple value={markets} onChange={setMarkets}>
            {[...new Set(catalog.items.map((item) => item.symbol))].sort().map((symbol) => (
              <Chip key={symbol} value={symbol} size="sm">{symbol}</Chip>
            ))}
          </Chip.Group>
        </Group>
        <Group gap={8} align="end" wrap="nowrap" className="collective-filter-fields">
          <Select
            label="Chart timeframe"
            size="xs"
            w={150}
            value={timeframe}
            onChange={(value) => setTimeframe(value || "all")}
            data={[
              { value: "all", label: "All timeframes" },
              ...[...new Set(catalog.items.map((item) => item.timeframe))]
                .sort()
                .map((value) => ({ value, label: value })),
            ]}
          />
          <TextInput
            label="Find a strategy"
            size="xs"
            placeholder="Name, session or source"
            value={search}
            onChange={(event) => setSearch(event.currentTarget.value)}
          />
        </Group>
      </div>
      <ScrollArea
        className="collective-picker-table"
        type="always"
        viewportProps={{ tabIndex: 0, role: "region", "aria-label": "Available strategy configurations" }}
      >
        <Table miw={880} highlightOnHover data-testid="strategy-picker">
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={40}><span className="visually-hidden">Include</span></Table.Th>
              <Table.Th>Strategy / chart</Table.Th>
              <Table.Th>Evidence</Table.Th>
              <Table.Th>Test coverage</Table.Th>
              <Table.Th ta="right">2024 onward</Table.Th>
              <Table.Th>Review notes</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {visible.map((item) => (
              <Table.Tr key={item.id}>
                <Table.Td>
                  <Checkbox
                    aria-label={`Include ${item.name} ${item.symbol} ${item.timeframe} ${item.source}`}
                    checked={settings.copies[item.id] > 0}
                    disabled={!settings.copies[item.id] && selected.length >= 100}
                    onChange={(event) => {
                      const next = { ...settings.copies };
                      if (event.currentTarget.checked) next[item.id] = 1;
                      else delete next[item.id];
                      choose(next);
                    }}
                  />
                </Table.Td>
                <Table.Td>
                  <Text fw={600} size="sm">{item.name}</Text>
                  <Text size="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>{item.symbol} · {item.timeframe} · {item.session}</Text>
                </Table.Td>
                <Table.Td>
                  <Badge
                    className="collective-milestone-badge"
                    radius="xs"
                    variant="light"
                    color={item.benchmark ? "gray" : stageColor(collectiveProgress(item).stage)}
                  >
                    {collectiveProgress(item).label}
                  </Badge>
                  <Text size="xs" c="dimmed">{item.source}</Text>
                </Table.Td>
                <Table.Td data-label="Test coverage">
                  <Text size="xs" className="mono" style={{ whiteSpace: "nowrap" }}>{item.start} → {item.end}</Text>
                </Table.Td>
                <Table.Td data-label="2024 onward" ta="right" c={tone(item.recent_pnl)} className="mono">
                  {item.end < "2024" ? "Not tested" : money(item.recent_pnl)}
                </Table.Td>
                <Table.Td maw={280}>
                  <details>
                    <summary>
                      {item.reasons[0]
                        ? item.reasons[0].length > 60
                          ? item.reasons[0].slice(0, 58) + "…"
                          : item.reasons[0]
                        : `${item.reasons.length} notes`}
                    </summary>
                    {item.reasons.map((reason, index) => <Text key={index} size="xs" mb={5}>{reason}</Text>)}
                    <Text size="xs">Parameters: {JSON.stringify(item.parameters)}</Text>
                  </details>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>
      {!visible.length && <Text c="dimmed" py="md">No strategies meet these filters. Missing tests are not treated as passes.</Text>}
      {catalog.errors.length > 0 && (
        <Alert color="yellow">
          {catalog.errors.length} configurations could not be verified and are excluded:{" "}
          {catalog.errors.map((error) => `${error.key}: ${error.error}`).join("; ")}
        </Alert>
      )}
      <div className="collective-picker-foot">
        <Text size="sm">
          <b>{selected.length} selected</b>
          {hidden.length > 0 && <Text span c="dimmed"> · {hidden.length} hidden by these filters stay in the combination</Text>}
        </Text>
        <Group gap={8} ml="auto">
          <Button size="xs" variant="subtle" color="gray" onClick={() => choose({})}>Clear combination</Button>
          <Button
            size="xs"
            variant="default"
            onClick={() => choose(Object.fromEntries(visible.slice(0, 100).map((item) => [item.id, 1])))}
            disabled={!visible.length || visible.length > 100}
          >
            Apply visible strategies ({visible.length})
          </Button>
          <Button size="xs" onClick={() => setPickerOpen(false)}>Done</Button>
        </Group>
      </div>
    </div>
  );
}
