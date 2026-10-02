import type { Dispatch, SetStateAction } from "react";
import {
  ActionIcon,
  Button,
  Group,
  NumberInput,
  SegmentedControl,
  Select,
  SimpleGrid,
  Switch,
  Text,
  TextInput,
} from "@mantine/core";
import { IconChevronRight, IconDownload, IconPlus, IconX } from "@tabler/icons-react";
import type { PortfolioResult } from "../../../shared/ts/collective.ts";
import type { CollectiveCatalog, CollectiveItem, Coverage } from "../../../shared/ts/portfolio.ts";
import {
  formatMoney as money,
  formatPercent as pct,
  portfolioUpdatePresentation,
  strategyReturnAndDrawdownPercent,
  type CollectiveSettings,
  type PortfolioTracking,
  type SavedCombination,
} from "./collectiveViewModel";

export function CombinationControls({
  capital,
  catalog,
  choose,
  deleteCombination,
  exportCombination,
  exportDaily,
  followLatestEnd,
  hasResult,
  isMobile,
  loadCombination,
  result,
  retryTracking,
  saveCombination,
  savedBookName,
  savedBooks,
  selectedSavedBookId,
  selected,
  setMonth,
  setPickerOpen,
  setRailCollapsed,
  setSavedBookName,
  setSettings,
  setSheetOpen,
  settings,
  testedWindow,
  tracking,
  useCommon,
}: {
  capital: number;
  catalog: CollectiveCatalog | null;
  choose: (copies: Record<string, number>) => void;
  deleteCombination: () => void;
  exportCombination: () => void;
  exportDaily: () => void;
  followLatestEnd: string;
  hasResult: boolean;
  isMobile: boolean;
  loadCombination: (id: string | null) => void;
  result: PortfolioResult | null;
  retryTracking: (id: string) => Promise<void>;
  saveCombination: () => void;
  savedBookName: string;
  savedBooks: SavedCombination[];
  selectedSavedBookId: string | null;
  selected: CollectiveItem[];
  setMonth: Dispatch<SetStateAction<string>>;
  setPickerOpen: Dispatch<SetStateAction<boolean>>;
  setRailCollapsed: Dispatch<SetStateAction<boolean | null>>;
  setSavedBookName: Dispatch<SetStateAction<string>>;
  setSettings: Dispatch<SetStateAction<CollectiveSettings>>;
  setSheetOpen: Dispatch<SetStateAction<boolean>>;
  settings: CollectiveSettings;
  testedWindow: Coverage;
  tracking: PortfolioTracking | null;
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
          {selected.map((item) => {
            const metrics = result && strategyReturnAndDrawdownPercent(result, item.id);
            const update = tracking?.items[item.id];
            const updatePresentation = portfolioUpdatePresentation(item, update);
            return <li key={item.id}>
              <div className="wb-book-summary">
                <div className="wb-book-heading">
                  <span className="wb-book-symbol">{item.symbol}</span>
                  <span className="wb-book-name">{item.name}</span>
                </div>
                <div className="wb-book-performance">
                  <span title="P&L as a percentage of the portfolio's starting capital">
                    P&amp;L <strong className={metrics?.pnlPercent == null ? undefined : metrics.pnlPercent < 0 ? "wb-loss" : "wb-gain"}>
                      {metrics ? `${metrics.pnlPercent > 0 ? "+" : ""}${pct(metrics.pnlPercent)}` : "—"}
                    </strong>
                  </span>
                  <span title="Daily peak-to-trough drawdown as a percentage of the strategy's peak equity">
                    Drawdown <strong className={metrics?.drawdownPercent ? "wb-loss" : undefined}>
                      {metrics ? pct(metrics.drawdownPercent) : "—"}
                    </strong>
                  </span>
                </div>
                <div className="wb-book-coverage" title={updatePresentation.title}>
                  <span>Data through {update?.dataset_last || "checking"}</span>
                  <span>Simulated through {update?.simulated_through || item.end}</span>
                  <span className={updatePresentation.attention ? "wb-book-update-attention" : undefined}>
                    {updatePresentation.label}
                  </span>
                  {update?.status === "failed" && (
                    <button type="button" className="wb-link-button" onClick={() => void retryTracking(item.id)}>
                      Retry update
                    </button>
                  )}
                </div>
              </div>
              <ActionIcon
                className="wb-book-remove"
                variant="subtle"
                color="gray"
                size="sm"
                aria-label={`Remove ${item.name} ${item.symbol} ${item.timeframe}`}
                title="Remove from combination"
                onClick={() => {
                  const next = { ...settings.copies };
                  delete next[item.id];
                  choose(next);
                }}
              >
                <IconX size={14} />
              </ActionIcon>
            </li>;
          })}
        </ul>
      ) : (
        <Text size="sm" c="dimmed">
          {catalog ? "No books yet. Add strategies to build a combination." : "Loading the combination…"}
        </Text>
      )}
      <div className="wb-rail-section wb-saved-combinations">
        <span className="wb-rail-label">Saved combinations</span>
        <Group gap={6} wrap="nowrap">
          <Select
            size="xs"
            style={{ flex: 1, minWidth: 0 }}
            placeholder={savedBooks.length ? "Load a saved combination" : "No saved combinations"}
            data={savedBooks.map((item) => ({ value: item.id, label: item.name }))}
            value={selectedSavedBookId}
            onChange={loadCombination}
            onOptionSubmit={(id) => {
              if (id === selectedSavedBookId) loadCombination(id);
            }}
            allowDeselect={false}
            searchable
            clearable
            clearButtonProps={{ "aria-label": "Clear saved combination", "aria-hidden": false, tabIndex: 0 }}
          />
          <Button size="compact-sm" variant="subtle" color="red" onClick={deleteCombination}
            disabled={!selectedSavedBookId}>Delete</Button>
        </Group>
        <Group gap={6} wrap="nowrap">
          <TextInput
            size="xs"
            style={{ flex: 1 }}
            placeholder={selectedSavedBookId ? "Clear selection to save a new combination" : "Name this combination"}
            value={savedBookName}
            onChange={(event) => setSavedBookName(event.currentTarget.value)}
            disabled={Boolean(selectedSavedBookId)}
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
            onChange={(event) => setSettings((current) => ({
              ...current,
              start: event.currentTarget.value,
              followCommonStart: false,
            }))}
          />
          <TextInput
            type="date"
            size="xs"
            label="P&L end"
            value={settings.end}
            onChange={(event) => {
              const end = event.currentTarget.value;
              setSettings((current) => ({ ...current, end, followLatest: false }));
              if (end) setMonth(end.slice(0, 7));
            }}
          />
        </SimpleGrid>
        <Switch
          mt="xs"
          size="xs"
          label="Follow common start"
          description="Use the first date covered by every selected book."
          checked={settings.followCommonStart === true}
          onChange={(event) => {
            const checked = event.currentTarget.checked;
            setSettings((current) => ({ ...current, followCommonStart: checked }));
          }}
        />
        <Switch
          mt="xs"
          size="xs"
          label="Follow latest"
          description="Advance the P&L end date when all selected books have verified coverage."
          checked={settings.followLatest === true}
          onChange={(event) => {
            const checked = event.currentTarget.checked;
            setSettings((current) => ({
              ...current,
              followLatest: checked,
              end: checked && followLatestEnd ? followLatestEnd : current.end,
            }));
          }}
        />
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
        Copies scale recorded P&L and exposure. Starting capital stays fixed.
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
