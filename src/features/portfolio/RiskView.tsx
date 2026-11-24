import { useState } from "react";
import { Button, ScrollArea, Table, Text } from "@mantine/core";
import type { CollectiveDashboardModel } from "./useCollectiveDashboardModel";
import { CollectiveContributionsView, CollectiveEmptyState } from "./CollectiveDashboardViews";
import { PauseSizingView } from "./PauseSizingView";
import { StrategyConditionPanel } from "./StrategyConditionPanel";
import { RecentFormCards } from "./RecentFormCards";
import { ShortRuleForm } from "./ShortRuleForm";
import { formatMoney as money, signedClass as signed } from "./collectiveViewModel";

function PositionSize({ model }: { model: CollectiveDashboardModel }) {
  const { result, periodMetrics } = model;
  if (!result) return null;
  const rows = result.benchmarks.map((benchmark) => ({
    ...benchmark,
    current: benchmark.size === 1,
  }));
  const ratio = periodMetrics?.recoveryFactor;
  return (
    <section className="wb-card" aria-label="Position size" data-testid="position-size">
      <div className="wb-card-head">
        <h2>Position size</h2>
      </div>
      <Text size="sm" c="dimmed">
        The same dates and strategies at a smaller size. {ratio != null && <>Return ÷ drawdown stays {ratio.toFixed(2)} at every size: </>}
        size changes how big the swings are, not how good the strategy is. Sizes below 1× are shown for comparison;
        the replay itself trades whole copies.
      </Text>
      <ScrollArea>
        <Table mt="sm" miw={520}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Size</Table.Th>
              <Table.Th ta="right">Net P&amp;L</Table.Th>
              <Table.Th ta="right">Max drawdown</Table.Th>
              <Table.Th ta="right">Worst day</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => (
              <Table.Tr key={row.size} className={row.current ? "wb-row-current" : undefined}>
                <Table.Td>{Math.round(row.size * 100)}%{row.current && <Text span size="xs" c="dimmed"> · current</Text>}</Table.Td>
                <Table.Td ta="right" className={`mono ${signed(row.net)}`}>{money(row.net)}</Table.Td>
                <Table.Td ta="right" className="mono wb-loss">{money(-Math.abs(row.drawdown))}</Table.Td>
                <Table.Td ta="right" className="mono wb-loss">{money(row.worstDay)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>
    </section>
  );
}

export function RiskView({ model }: { model: CollectiveDashboardModel }) {
  const { catalog, histories, result, selected, settings } = model;
  const [rulesOpen, setRulesOpen] = useState(settings.policy.enabled);
  const [advanced, setAdvanced] = useState(false);
  if (!result) return <CollectiveEmptyState model={model} />;
  return (
    <div className="wb-risk">
      <RecentFormCards
        model={model}
        onPause={(id) => {
          model.setManualBook(id);
          model.setManualAction("pause");
          model.policy({ enabled: true, mode: "manual" });
          setRulesOpen(true);
          setAdvanced(true);
        }}
      />
      <details className="wb-condition-details">
        <summary>Full condition details</summary>
        <StrategyConditionPanel
          catalog={catalog}
          items={selected}
          histories={histories}
          end={settings.end}
          enabled={settings.policy.enabled}
          permissions={result.components || []}
        />
      </details>
      <PositionSize model={model} />
      <section className="wb-card" aria-label="Pause and resume rules">
        <div className="wb-card-head">
          <div>
            <h2>
              Pause &amp; resume rules
              <span className={`wb-status-chip ${settings.policy.enabled ? "is-running" : "is-tracking"}`}>{settings.policy.enabled ? "On" : "Off"}</span>
            </h2>
            <Text size="sm" c="dimmed">
              Replay a loss-based pause or volatility-scaled sizing against always-on trading, and see every decision it
              would have made.
            </Text>
          </div>
          <Button variant="default" size="xs" onClick={() => setRulesOpen((open) => !open)} aria-expanded={rulesOpen}>
            {rulesOpen ? "Hide rules" : "Set up a rule"}
          </Button>
        </div>
        {rulesOpen && !advanced && <ShortRuleForm model={model} />}
        {rulesOpen && (
          <Button variant="subtle" size="compact-xs" mt="xs" onClick={() => setAdvanced((open) => !open)} aria-expanded={advanced}>
            {advanced ? "Hide advanced options" : "Advanced options"}
          </Button>
        )}
        {rulesOpen && advanced && <PauseSizingView model={model} showCondition={false} showBenchmarks={settings.policy.enabled} />}
      </section>
      {settings.policy.enabled && <CollectiveContributionsView model={model} />}
    </div>
  );
}
