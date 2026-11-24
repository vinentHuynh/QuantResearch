import { useState } from "react";
import { Button, Drawer, Group, NumberInput, SegmentedControl, SimpleGrid, Text, TextInput } from "@mantine/core";
import { IconDownload } from "@tabler/icons-react";
import type { CollectiveDashboardModel } from "./useCollectiveDashboardModel";

type Draft = {
  capital: number;
  range: "common" | "custom";
  start: string;
  end: string;
  basis: "marked" | "closed";
};

function draftFrom(model: CollectiveDashboardModel): Draft {
  const { settings } = model;
  return {
    capital: settings.capital,
    range: settings.followCommonStart && settings.followLatest ? "common" : "custom",
    start: settings.start,
    end: settings.end,
    basis: settings.basis,
  };
}

function SettingsForm({ model, onClose }: { model: CollectiveDashboardModel; onClose: () => void }) {
  const { exportCombination, exportDaily, followLatestEnd, result, selected, setMonth, setSettings, settings, testedWindow } = model;
  const [draft, setDraft] = useState<Draft>(() => draftFrom(model));
  const update = (patch: Partial<Draft>) => setDraft((current) => ({ ...current, ...patch }));
  const commonLabel = testedWindow.start
    ? `${testedWindow.start} – ${followLatestEnd || testedWindow.end} · moves forward on its own as new data arrives`
    : "These strategies have no common tested window yet";
  const apply = () => {
    setSettings((current) => {
      const common = draft.range === "common" && !!testedWindow.start;
      const end = common ? followLatestEnd || testedWindow.end : draft.end;
      return {
        ...current,
        capital: draft.capital,
        basis: current.policy.enabled ? current.basis : draft.basis,
        followCommonStart: common,
        followLatest: common,
        start: common ? testedWindow.start : draft.start,
        end,
      };
    });
    const end = draft.range === "common" ? followLatestEnd || testedWindow.end : draft.end;
    if (end) setMonth(end.slice(0, 7));
    onClose();
  };
  return (
    <div className="wb-settings-form">
      <NumberInput
        label="Starting capital (USD)"
        description="One balance shared by every strategy in the portfolio."
        min={1}
        decimalScale={2}
        allowNegative={false}
        thousandSeparator=","
        prefix="$"
        value={draft.capital}
        onChange={(value) => update({ capital: Number(value) || 0 })}
      />
      <fieldset className="wb-settings-fieldset">
        <legend>Date range</legend>
        <button
          type="button"
          className={`wb-choice${draft.range === "common" ? " active" : ""}`}
          aria-pressed={draft.range === "common"}
          disabled={!testedWindow.start}
          onClick={() => update({ range: "common" })}
        >
          <strong>Longest shared window</strong>
          <span>{commonLabel}</span>
        </button>
        <button
          type="button"
          className={`wb-choice${draft.range === "custom" ? " active" : ""}`}
          aria-pressed={draft.range === "custom"}
          onClick={() => update({ range: "custom" })}
        >
          <strong>Custom range</strong>
          <span>Pick your own start and end dates</span>
        </button>
        {draft.range === "custom" && (
          <SimpleGrid cols={2} spacing="xs">
            <TextInput type="date" label="P&L start" value={draft.start} onChange={(event) => update({ start: event.currentTarget.value })} />
            <TextInput type="date" label="P&L end" value={draft.end} onChange={(event) => update({ end: event.currentTarget.value })} />
          </SimpleGrid>
        )}
      </fieldset>
      <div>
        <Text size="sm" fw={600} mb={4}>Count P&amp;L</Text>
        <SegmentedControl
          aria-label="P&L accounting"
          fullWidth
          value={draft.basis}
          disabled={settings.policy.enabled}
          onChange={(value) => update({ basis: value === "closed" ? "closed" : "marked" })}
          data={[
            { value: "marked", label: "Every day" },
            { value: "closed", label: "When trades close" },
          ]}
        />
        <Text size="xs" c="dimmed" mt={4}>
          {settings.policy.enabled
            ? "A pause or sizing rule is on, so P&L counts when trades close."
            : draft.basis === "marked"
              ? "Open positions are marked at each daily close."
              : "Each complete trade counts on the day it closes."}
        </Text>
      </div>
      <div>
        <Text size="sm" fw={600} mb={4}>Export</Text>
        <Group gap="xs">
          <Button variant="default" size="xs" leftSection={<IconDownload size={13} />} disabled={!result} onClick={exportDaily}>
            Daily P&amp;L (CSV)
          </Button>
          <Button variant="default" size="xs" leftSection={<IconDownload size={13} />} disabled={!selected.length} onClick={exportCombination}>
            Setup (JSON)
          </Button>
        </Group>
      </div>
      <details className="wb-settings-help">
        <summary>How the numbers are calculated</summary>
        <Text size="xs" c="dimmed" mt={6}>
          P&amp;L uses UTC calendar days, net of recorded fees and slippage. Each strategy is its own book: no position
          netting, shared margin or resizing between them. Size multiplies a strategy’s recorded P&amp;L and exposure;
          starting capital stays fixed. Missing dates block the combined result; daily drawdown leaves out intraday
          extremes. These historical results were looked at while choosing strategies.
        </Text>
      </details>
      <Group justify="flex-end" gap="xs" className="wb-settings-actions">
        <Button variant="default" onClick={onClose}>Cancel</Button>
        <Button onClick={apply} disabled={draft.capital <= 0 || (draft.range === "custom" && (!draft.start || !draft.end))}>Apply</Button>
      </Group>
    </div>
  );
}

export function PortfolioSettingsDrawer({ model, opened, onClose }: {
  model: CollectiveDashboardModel;
  opened: boolean;
  onClose: () => void;
}) {
  return (
    <Drawer opened={opened} onClose={onClose} position="right" size={440} title={<span className="wb-drawer-title">Portfolio settings</span>}>
      {opened && <SettingsForm model={model} onClose={onClose} />}
    </Drawer>
  );
}
