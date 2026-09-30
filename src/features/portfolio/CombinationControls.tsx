import type { Dispatch, SetStateAction } from "react";
import {
  ActionIcon,
  Button,
  Group,
  NumberInput,
  SegmentedControl,
  Select,
  SimpleGrid,
  Text,
  TextInput,
} from "@mantine/core";
import { IconChevronRight, IconDownload, IconPlus, IconX } from "@tabler/icons-react";
import type { CollectiveCatalog, CollectiveItem, Coverage } from "../../../shared/ts/portfolio.ts";
import { formatMoney as money, type CollectiveSettings, type SavedCombination } from "./collectiveViewModel";

export function CombinationControls({
  capital,
  catalog,
  choose,
  exportCombination,
  exportDaily,
  hasResult,
  isMobile,
  loadCombination,
  saveCombination,
  savedBookName,
  savedBooks,
  selected,
  setMonth,
  setPickerOpen,
  setRailCollapsed,
  setSavedBookName,
  setSettings,
  setSheetOpen,
  settings,
  testedWindow,
  useCommon,
}: {
  capital: number;
  catalog: CollectiveCatalog | null;
  choose: (copies: Record<string, number>) => void;
  exportCombination: () => void;
  exportDaily: () => void;
  hasResult: boolean;
  isMobile: boolean;
  loadCombination: (id: string | null) => void;
  saveCombination: () => void;
  savedBookName: string;
  savedBooks: SavedCombination[];
  selected: CollectiveItem[];
  setMonth: Dispatch<SetStateAction<string>>;
  setPickerOpen: Dispatch<SetStateAction<boolean>>;
  setRailCollapsed: Dispatch<SetStateAction<boolean | null>>;
  setSavedBookName: Dispatch<SetStateAction<string>>;
  setSettings: Dispatch<SetStateAction<CollectiveSettings>>;
  setSheetOpen: Dispatch<SetStateAction<boolean>>;
  settings: CollectiveSettings;
  testedWindow: Coverage;
  useCommon: () => void;
}) {
  return (
    <>
      <div className="wb-rail-head">
        <div>
          <h2>Combination</h2>
          <p>
            <span data-testid="selected-count">
              {selected.length} {selected.length === 1 ? "book" : "books"}
            </span>{" "}
            · {money(capital)}
          </p>
        </div>
        <Group gap={4} wrap="nowrap">
          <Button
            size="compact-sm"
            variant="light"
            leftSection={<IconPlus size={13} />}
            onClick={() => {
              setSheetOpen(false);
              setPickerOpen(true);
            }}
          >
            Add
          </Button>
          {!isMobile && (
            <ActionIcon
              variant="subtle"
              color="gray"
              aria-label="Collapse combination"
              onClick={() => setRailCollapsed(true)}
            >
              <IconChevronRight size={15} />
            </ActionIcon>
          )}
        </Group>
      </div>
      {selected.length ? (
        <ul className="wb-books" data-testid="selected-strategies">
          {selected.map((item) => (
            <li key={item.id}>
              <div className="wb-book-text">
                <div className="wb-book-name" title={item.name}>{item.name}</div>
                <div className="wb-book-meta">{item.symbol} · {item.timeframe} · {item.session}</div>
                <div className="wb-book-meta">
                  Tested: {item.coverage.map((span) => `${span.start} to ${span.end}`).join("; ") || "No covered dates"}
                </div>
              </div>
              <NumberInput
                aria-label={`Copies of ${item.name} ${item.symbol} ${item.timeframe}`}
                size="xs"
                w={62}
                min={1}
                max={100}
                allowDecimal={false}
                value={settings.copies[item.id]}
                onChange={(copies) =>
                  setSettings((current) => ({
                    ...current,
                    copies: {
                      ...current.copies,
                      [item.id]: Math.max(1, Math.min(100, Number(copies) || 1)),
                    },
                  }))
                }
              />
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                aria-label={`Remove ${item.name} ${item.symbol} ${item.timeframe}`}
                onClick={() => {
                  const next = { ...settings.copies };
                  delete next[item.id];
                  choose(next);
                }}
              >
                <IconX size={13} />
              </ActionIcon>
            </li>
          ))}
        </ul>
      ) : (
        <Text size="sm" c="dimmed">
          {catalog ? "No books yet. Add strategies to build a combination." : "Loading the combination…"}
        </Text>
      )}
      <div className="wb-rail-section wb-saved-combinations">
        <span className="wb-rail-label">Saved combinations</span>
        <Select
          size="xs"
          placeholder={savedBooks.length ? "Load a saved combination" : "No saved combinations"}
          data={savedBooks.map((item) => ({ value: item.id, label: item.name }))}
          value={null}
          onChange={loadCombination}
          searchable
          clearable
        />
        <Group gap={6} wrap="nowrap">
          <TextInput
            size="xs"
            style={{ flex: 1 }}
            placeholder="Name this combination"
            value={savedBookName}
            onChange={(event) => setSavedBookName(event.currentTarget.value)}
          />
          <Button size="compact-sm" variant="light" onClick={saveCombination} disabled={!selected.length}>Save</Button>
        </Group>
      </div>
      <div className="wb-rail-section">
        <NumberInput
          label="Starting capital (USD)"
          description="One balance shared across all selected strategies."
          size="xs"
          min={1}
          decimalScale={2}
          allowNegative={false}
          value={capital}
          onChange={(value) => setSettings((current) => ({ ...current, capital: Number(value) }))}
        />
      </div>
      <div className="wb-rail-section">
        <SimpleGrid cols={2} spacing={6}>
          <TextInput
            type="date"
            size="xs"
            label="P&L start"
            value={settings.start}
            onChange={(event) => setSettings((current) => ({ ...current, start: event.currentTarget.value }))}
          />
          <TextInput
            type="date"
            size="xs"
            label="P&L end"
            value={settings.end}
            onChange={(event) => {
              const end = event.currentTarget.value;
              setSettings((current) => ({ ...current, end }));
              if (end) setMonth(end.slice(0, 7));
            }}
          />
        </SimpleGrid>
        <button type="button" className="wb-link-button" onClick={useCommon} disabled={!testedWindow.start}>
          Use common tested window
        </button>
        {selected.length > 0 && (
          <Text size="xs" c="dimmed">
            {testedWindow.start
              ? `Common continuous window: ${testedWindow.start} to ${testedWindow.end}.`
              : "These configurations have no common tested window. Remove a configuration or choose different histories."}
          </Text>
        )}
      </div>
      <div className="wb-rail-section">
        <span className="wb-rail-label">Accounting</span>
        <SegmentedControl
          aria-label="P&L accounting"
          size="xs"
          fullWidth
          value={settings.basis}
          disabled={settings.policy.enabled}
          onChange={(value) =>
            setSettings((current) => ({ ...current, basis: value === "closed" ? "closed" : "marked" }))
          }
          data={[
            { value: "marked", label: "Marked daily" },
            { value: "closed", label: "Closed trades" },
          ]}
        />
        <Text size="xs" c="dimmed">
          {settings.policy.enabled
            ? "The pause & sizing replay uses closed-trade accounting."
            : settings.basis === "marked"
              ? "Includes open P&L at daily observations."
              : "Books each complete net trade on its exit date."}
        </Text>
      </div>
      <Text size="xs" c="dimmed">
        Copies multiply recorded P&L and exposure. Starting capital stays fixed when adding strategies or copies; shared margin and liquidation are not simulated.
      </Text>
      <div className="wb-rail-foot">
        <Button size="compact-sm" variant="default" leftSection={<IconDownload size={13} />} onClick={exportDaily} disabled={!hasResult}>
          Daily P&L CSV
        </Button>
        <Button size="compact-sm" variant="default" onClick={exportCombination} disabled={!selected.length}>
          Combination JSON
        </Button>
      </div>
    </>
  );
}
