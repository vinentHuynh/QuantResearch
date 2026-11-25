import { useEffect, useMemo, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Checkbox,
  Code,
  Group,
  NumberInput,
  Select,
  Text,
  TextInput,
} from "@mantine/core";
import { IconCheck, IconPlus } from "@tabler/icons-react";
import type {
  CollectiveCatalog,
  CollectiveItem,
} from "../../../shared/ts/portfolio.ts";
import type {
  RunSummary,
  Strategy,
} from "../../../shared/ts/workbenchModels.ts";
import {
  canAddPortfolioCandidate,
} from "../../../shared/ts/portfolioCandidates.ts";
import { bestPortfolioPreview, groupPortfolioHistories, portfolioItemStrategyId, portfolioRiskDetails, portfolioScriptGroups, selectPortfolioHistory, type PortfolioDailyRisk, type PortfolioScriptGroup } from "../../../shared/ts/portfolioScriptCandidates.ts";
import { href } from "../../app/navigation";
import { statusDisplay } from "../../../shared/ts/strategyLifecycle.ts";
import { strategySourceTags, strategyTitle } from "../../../shared/ts/formatting.ts";
import { useStrategyStages } from "../../shared/ui/strategyStageContext";
import { groupedResearchRows, sortResearchRows } from "../strategies/researchRows";
import { ResearchGroupHeading, StageDots, StatusChip } from "../strategies/ResearchStageIndicators";
import type { CollectiveSettings, PortfolioTracking } from "./collectiveViewModel";
import { formatMoney as money } from "./collectiveViewModel";
import "./strategyPicker.css";

const statusFilters = [
  { value: "any", label: "Any status" },
  { value: "needs-review", label: "Needs review" },
  { value: "retest-required", label: "Retest required" },
  { value: "validation-pending", label: "Awaiting evaluation" },
  { value: "failed-checks", label: "Failed checks" },
] as const;
type StatusFilter = (typeof statusFilters)[number]["value"];
type SortKey = "research" | "score" | "net" | "drawdown";

type RiskResponse = {
  ready: Record<string, PortfolioDailyRisk>;
  pending: string[];
  errors: Record<string, string>;
};
type RiskState = RiskResponse & { key: string };
type ImportState = { runId?: string; phase: "idle" | "importing" | "verifying" | "error"; error?: string };
type PickerOption = ReturnType<typeof portfolioScriptGroups>[number]["options"][number];

const matchesStatus = (row: PickerOption, value: StatusFilter) => value === "any" || row.status.kind === value;

const drawdownText = (percent: number | null) => percent === null
  ? "Unavailable" : percent === 0 ? "0.00%" : `-${percent.toFixed(2)}%`;
const scoreText = (score: number | null) => score === null
  ? "Unscored" : score === Infinity ? "∞" : score.toFixed(2);
const previewMoney = (value: number) => value.toLocaleString("en-US", {
  style: "currency", currency: "USD",
  minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
  maximumFractionDigits: 2,
});

function PickerStageSection({ stage, count, children }: {
  stage?: { id: string; title: string; hint: string };
  count: number;
  children: ReactNode;
}) {
  if (!stage) return children;
  const heading = `picker-stage-${stage.id}`;
  return (
    <div role="listitem">
      <section className="strategy-picker-stage" aria-labelledby={heading}>
        <ResearchGroupHeading id={heading} title={stage.title} hint={stage.hint} count={count} />
        <div className="strategy-picker-stage-list" role="list" aria-labelledby={heading}>{children}</div>
      </section>
    </div>
  );
}

export function StrategyPickerControls({
  catalog,
  choose,
  focusRunId,
  importState,
  markets,
  pickerOpen,
  search,
  selected,
  runs = [],
  strategies: scripts = [],
  refreshEvidence,
  refreshing,
  retryTracking,
  setMarkets,
  setPickerOpen,
  setSearch,
  setSettings,
  setTimeframe,
  settings,
  timeframe,
  tracking,
}: {
  catalog: CollectiveCatalog;
  choose: (copies: Record<string, number>) => void;
  focusRunId?: string;
  importState?: ImportState;
  markets: string[];
  pickerOpen: boolean;
  search: string;
  selected: CollectiveItem[];
  runs?: RunSummary[];
  strategies?: Strategy[];
  refreshEvidence: (runId?: string) => Promise<unknown>;
  refreshing: boolean;
  retryTracking: (id: string) => Promise<void>;
  setMarkets: Dispatch<SetStateAction<string[]>>;
  setPickerOpen: Dispatch<SetStateAction<boolean>>;
  setSearch: Dispatch<SetStateAction<string>>;
  setSettings: Dispatch<SetStateAction<CollectiveSettings>>;
  setTimeframe: Dispatch<SetStateAction<string>>;
  settings: CollectiveSettings;
  timeframe: string;
  tracking: PortfolioTracking | null;
}) {
  const { statuses, onAction } = useStrategyStages();
  const [status, setStatus] = useState<StatusFilter>("any");
  const [sort, setSort] = useState<SortKey>("research");
  useEffect(() => { if (focusRunId) setStatus("any"); }, [focusRunId]);
  const openingCopies = useRef<Record<string, number>>({});
  useEffect(() => { if (pickerOpen) openingCopies.current = { ...settings.copies }; }, [pickerOpen]); // eslint-disable-line react-hooks/exhaustive-deps
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const groups = useMemo(
    () => portfolioScriptGroups(scripts, catalog, runs, statuses, { markets, timeframe, search }),
    [scripts, catalog, runs, statuses, markets, timeframe, search],
  );
  const byRun = useMemo(() => new Map(runs.map(run => [run.id, run])), [runs]);
  const filtered = useMemo(() => groups
    .map(group => ({ ...group, options: group.options.filter(row => row.status.kind !== "benchmark" && matchesStatus(row, status)) }))
    .filter(group => group.options.length > 0), [groups, status]);
  const riskRunIds = useMemo(() => [...new Set(filtered.flatMap(group => group.options.flatMap(row =>
    !row.item && row.run?.status === "Succeeded" && row.run.result ? [row.run.id] : [])))].sort(), [filtered]);
  const riskKey = JSON.stringify([catalog.generated_at, riskRunIds]);
  const [riskState, setRiskState] = useState<RiskState>({ key: "", ready: {}, pending: [], errors: {} });
  const risk = useMemo(() => riskState.key === riskKey
    ? riskState : { key: riskKey, ready: {}, pending: riskRunIds, errors: {} }, [riskState, riskKey, riskRunIds]);
  const sections = useMemo(() => {
    if (sort === "research") {
      const histories = sortResearchRows(filtered.flatMap(group => group.options), row => row.name);
      return groupedResearchRows(histories).map(({ rows, ...stage }) => ({
        stage, groups: groupPortfolioHistories(rows),
      }));
    }
    const key = (group: (typeof filtered)[number]) => {
      const best = bestPortfolioPreview(group.options, risk.ready);
      const details = best ? portfolioRiskDetails(best, risk.ready) : null;
      if (sort === "net") return best?.pnl ?? -Infinity;
      if (sort === "drawdown") return details?.maxDrawdownPercent == null ? -Infinity : -details.maxDrawdownPercent;
      return details?.score ?? -Infinity;
    };
    return [{ stage: undefined, groups: [...filtered].sort((a, b) => key(b) - key(a)) }];
  }, [filtered, risk, sort]);
  useEffect(() => {
    if (!pickerOpen || !riskRunIds.length) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let active = true;
    setRiskState({ key: riskKey, ready: {}, pending: riskRunIds, errors: {} });
    const poll = async (ids: string[], previous: RiskResponse) => {
      const batches: string[][] = [];
      for (let index = 0; index < ids.length; index += 100) batches.push(ids.slice(index, index + 100));
      const replies = await Promise.all(batches.map(async batch => {
        try {
          const response = await fetch("/api/workbench/collective/risk", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ runIds: batch }), signal: controller.signal, cache: "no-store",
          });
          if (!response.ok) {
            const failure = await response.json().catch(() => ({}));
            throw new Error(failure.error || `Risk calculation failed (${response.status})`);
          }
          return { batch, result: await response.json() as RiskResponse };
        } catch (error) {
          return { batch, error: String(error) };
        }
      }));
      if (!active) return;
      const next: RiskResponse = { ready: { ...previous.ready }, pending: [], errors: { ...previous.errors } };
      for (const reply of replies) {
        if (reply.error) {
          for (const id of reply.batch) next.errors[id] = reply.error;
          continue;
        }
        const result = reply.result!;
        Object.assign(next.ready, result.ready || {});
        Object.assign(next.errors, result.errors || {});
        const pending = new Set(result.pending || []);
        for (const id of reply.batch) {
          if (pending.has(id)) next.pending.push(id);
          else if (!(id in next.ready) && !(id in next.errors)) next.errors[id] = "Risk calculation returned no result.";
        }
      }
      setRiskState({ key: riskKey, ...next });
      if (next.pending.length) timer = setTimeout(() => void poll(next.pending, next), 1500);
    };
    void poll(riskRunIds, { ready: {}, pending: [], errors: {} });
    return () => { active = false; controller.abort(); if (timer) clearTimeout(timer); };
  }, [pickerOpen, riskKey, riskRunIds]);
  const shownIds = new Set(filtered.flatMap(group => group.options.map(row => row.item?.id).filter(Boolean)));
  const hidden = selected.filter(item => !shownIds.has(item.id));
  const symbols = [...new Set([...catalog.items.map(item => item.symbol), ...runs.map(run => run.input.dataset.symbol)])].filter(Boolean).sort();
  const timeframes = [...new Set([...catalog.items.map(item => item.timeframe), ...runs.map(run => run.input.timeframe)])].filter(Boolean).sort();
  const selectedCount = selected.length;
  const addedCount = Object.keys(settings.copies).filter(id => settings.copies[id] > 0 && !(openingCopies.current[id] > 0)).length;

  return (
    <div className="collective-picker strategy-picker-simple">
      <div className="wb-add-filters">
        <TextInput aria-label="Find a strategy" type="search" label="Search strategies" placeholder="Search by name, market, run ID or parameter"
          value={search} onChange={event => setSearch(event.currentTarget.value)} />
        <div className="wb-add-chips" role="group" aria-label="Market">
          {symbols.map(symbol => {
            const on = markets.includes(symbol);
            return (
              <button type="button" key={symbol} className={on ? "is-on" : undefined} aria-pressed={on}
                onClick={() => setMarkets(on ? markets.filter(m => m !== symbol) : [...markets, symbol])}>{symbol}</button>
            );
          })}
        </div>
        <Group gap="xs" grow>
          <Select label="Status" value={status} allowDeselect={false} onChange={value => setStatus((value || "any") as StatusFilter)}
            data={statusFilters.map(option => ({ value: option.value, label: option.label }))} />
          <Select label="Timeframe" value={timeframe} onChange={value => setTimeframe(value || "all")}
            data={[{ value: "all", label: "Any timeframe" }, ...timeframes.map(value => ({ value, label: value }))]} />
          <Select label="Sort" value={sort} allowDeselect={false} onChange={value => setSort((value || "research") as SortKey)}
            data={[{ value: "research", label: "Research stage" }, { value: "score", label: "Best return ÷ drawdown" }, { value: "net", label: "Highest net P&L" }, { value: "drawdown", label: "Smallest drawdown" }]} />
        </Group>
      </div>
      <div className="strategy-picker-tabs">
        <Text size="xs" c="dimmed">
          Expand a strategy to choose an exact saved history. P&amp;L and daily drawdown cover each
          history's saved dates; the portfolio result uses the active portfolio window.
        </Text>
        {importState?.phase === "error" && importState.error && (
          <Alert color="red" title="Exact run import failed" role="alert">{importState.error}</Alert>
        )}
        <div>
          <div className="strategy-picker-rows" role="list" aria-label="Strategies and exact histories">
            {sections.map(({ stage, groups }) => (
              <PickerStageSection key={stage?.id ?? "performance"} stage={stage} count={groups.length}>
                {groups.map(group => renderStrategy(group, stage?.id))}
              </PickerStageSection>
            ))}
          </div>
          {!filtered.length && (
            <Text size="sm" c="dimmed" p="md">
              No strategies match these filters.
              {status !== "any" && <Button size="compact-xs" variant="subtle" onClick={() => setStatus("any")}>Any status</Button>}
            </Text>
          )}
        </div>
      </div>
      {catalog.errors.length > 0 && (
        <details>
          <summary>{catalog.errors.length} import issues</summary>
          {catalog.errors.map(error => <Text size="xs" key={error.key}>{error.key}: {error.error}</Text>)}
        </details>
      )}
      {selected.length > 0 && (
        <details className="strategy-picker-copies">
          <summary>Selected copies</summary>
          <div className="strategy-picker-copies-list">
            {selected.map((item) => (
              <div className="strategy-picker-copies-row" key={item.id}>
                <Text size="sm">{item.symbol} · {strategyTitle(item.name)}</Text>
                <Group gap={6} wrap="nowrap">
                  <NumberInput
                    aria-label={`Copies of ${strategyTitle(item.name)} ${item.symbol} ${item.timeframe}`}
                    size="xs"
                    w={72}
                    min={1}
                    max={100}
                    allowDecimal={false}
                    value={settings.copies[item.id]}
                    onChange={(copies) => setSettings((current) => ({
                      ...current,
                      copies: {
                        ...current.copies,
                        [item.id]: Math.max(1, Math.min(100, Number(copies) || 1)),
                      },
                    }))}
                  />
                  {tracking?.items[item.id]?.status === "failed" && (
                    <Button size="compact-xs" variant="light" onClick={() => void retryTracking(item.id)}>
                      Retry update
                    </Button>
                  )}
                </Group>
              </div>
            ))}
          </div>
        </details>
      )}
      <div className="collective-picker-foot">
        <Text size="sm">
          {addedCount > 0 ? <><b>{addedCount}</b> to add</> : <b>{selected.length} selected</b>}
          {hidden.length > 0 && " · " + hidden.length + " outside this view"}
        </Text>
        <Group gap="xs" ml="auto">
          <Button size="xs" variant="subtle" onClick={() => choose({})}>Clear</Button>
          <Button size="xs" variant="default" onClick={() => { choose(openingCopies.current); setPickerOpen(false); }}>Cancel</Button>
          <Button size="xs" onClick={() => setPickerOpen(false)}>{addedCount > 0 ? `Add ${addedCount} ${addedCount === 1 ? "strategy" : "strategies"}` : "Done"}</Button>
        </Group>
      </div>
    </div>
  );

  function renderStrategy(group: PortfolioScriptGroup, stageId?: string) {
    const groupKey = JSON.stringify([stageId, group.strategyId]);
    const first = group.options[0];
    const historyCount = group.options.filter(row => row.item || row.run).length;
    const best = bestPortfolioPreview(group.options, risk.ready);
    const bestRisk = best ? portfolioRiskDetails(best, risk.ready) : null;
    const bestTrades = best?.item?.trades ?? best?.run?.result?.metrics.trades;
    const calculating = group.options.some(row => !row.item && row.run?.status === "Succeeded"
      && row.run.result && !risk.ready[row.run.id] && !risk.errors[row.run.id]);
    const previewStatus = (best ?? first).status;
    const mixedStatus = new Set(group.options.map(row => statusDisplay(row.status).label)).size > 1;
    const focused = !!focusRunId && group.options.some(row => row.item?.source_run_ids?.includes(focusRunId)
      || row.run?.id === focusRunId);
    const open = expanded[groupKey] ?? (focused
      || (Boolean(search.trim()) && group.options.length <= 5));
    const bestSelected = !!best?.item && settings.copies[best.item.id] > 0;
    const bestNext = best?.item
      ? selectPortfolioHistory(settings.copies, catalog, runs, best.item, group.strategyId) : null;
    const bestSlotOccupied = !!best && selected.some(item => item.symbol === best.symbol
      && item.timeframe === best.timeframe && portfolioItemStrategyId(item, runs) === group.strategyId);
    const bestCanFit = bestNext
      ? Object.values(bestNext).filter(value => value > 0).length <= 100
      : selectedCount + (bestSlotOccupied ? 0 : 1) <= 100;
    const bestImportable = !best?.item && best?.run?.status === "Succeeded" && !!best.run.result;
    const bestImporting = bestImportable && importState?.runId === best.run?.id
      && (importState?.phase === "importing" || importState?.phase === "verifying");
    const showBestAction = !open && !!best && (!!best.item || bestImportable);
    const canAddBest = !!best && !calculating && !bestSelected && bestCanFit
      && (best.item ? canAddPortfolioCandidate(best.item) : bestImportable && !refreshing);
    return (
      <section className="strategy-picker-group" role="listitem" key={group.strategyId} data-strategy-id={group.strategyId}>
        <div className={showBestAction ? "strategy-picker-group-header has-best-action" : "strategy-picker-group-header"}>
        <button type="button" className="strategy-picker-group-head" aria-expanded={open}
          onClick={() => setExpanded(current => ({ ...current, [groupKey]: !open }))}>
          <span aria-hidden="true">{open ? "−" : "+"}</span>
          <span className="strategy-picker-group-name">{strategyTitle(group.name)}{strategySourceTags(group.name).map(tag => <Badge key={tag} size="xs" variant="outline" color="gray" ml={6}>{tag}</Badge>)}</span>
          <span className="strategy-picker-stage-status">
            {open && mixedStatus ? <span className="wb-status-chip">Mixed research status</span> : <>
              <StageDots status={previewStatus} />
              <StatusChip status={previewStatus} />
            </>}
          </span>
          {!open && best && (
            <span className="strategy-picker-group-preview" data-preview-run-id={best.run?.id}>
              {calculating ? <span className="strategy-picker-preview-pending">Calculating best run</span> : <>
                {!best.item && !best.run ? <span className="strategy-picker-preview-empty">No saved history</span> : <>
                  <span className={bestRisk?.score === null ? "strategy-picker-preview-empty" : "strategy-picker-preview-title"}>
                    {bestRisk?.score === null ? "Unscored preview" : "Best run"}
                    {" · "}{best.symbol || "No market"}{" · "}{best.timeframe || "No timeframe"}
                  </span>
                  <span className="strategy-picker-preview-metrics">
                    <span className="strategy-picker-preview-metric">
                      <strong className={best.pnl == null || best.pnl === 0 ? undefined
                        : best.pnl < 0 ? "strategy-picker-preview-loss" : "strategy-picker-preview-profit"}>
                        {best.pnl === null ? "Unavailable" : previewMoney(best.pnl)}
                      </strong>
                      <small>Net P&amp;L</small>
                    </span>
                    <span className="strategy-picker-preview-metric">
                      <strong>{bestRisk?.maxDrawdownPercent == null ? "Unavailable" : `${bestRisk.maxDrawdownPercent.toFixed(2)}%`}</strong>
                      <small>Drawdown</small>
                    </span>
                    <span className="strategy-picker-preview-metric">
                      <strong>{typeof bestTrades === "number" && Number.isFinite(bestTrades) ? bestTrades.toLocaleString("en-US") : "Unavailable"}</strong>
                      <small>Trades</small>
                    </span>
                    <span className="strategy-picker-preview-metric">
                      <strong>{scoreText(bestRisk?.score ?? null)}</strong>
                      <small>Return/DD</small>
                    </span>
                  </span>
                </>}
              </>}
            </span>
          )}
          {historyCount > 0 && <span className="strategy-picker-group-count">
            {historyCount} {historyCount === 1 ? "history" : "histories"}
          </span>}
        </button>
        {showBestAction && <ActionIcon className="strategy-picker-best-add" size="sm" variant="light" color="teal"
          aria-label={bestSelected ? `Best run already added for ${strategyTitle(group.name)}` : `Add best run for ${strategyTitle(group.name)}`}
          title={bestSelected ? "Best run already added" : calculating ? "Calculating best run"
            : !bestCanFit ? "Portfolio limit reached" : bestImportable ? "Import and add exact best run" : "Add best saved history"}
          disabled={!canAddBest} loading={bestImporting}
          onClick={() => {
            if (!canAddBest || !best) return;
            if (bestNext) choose(bestNext);
            else if (bestImportable && best.run) void refreshEvidence(best.run.id);
          }}>
          {bestSelected ? <IconCheck size={16} /> : <IconPlus size={16} />}
        </ActionIcon>}
        </div>
        {open && (
          <div className="strategy-picker-options" role="list" aria-label={strategyTitle(group.name) + " histories"}>
            {group.options.map(row => {
              const item = row.item;
              const ids = item?.source_run_ids || (row.run ? [row.run.id] : []);
              const linked = ids.map(id => byRun.get(id)).filter((run): run is RunSummary => !!run);
              const sourceRun = row.run || linked[0];
              const start = item?.start || sourceRun?.input.start || "";
              const end = item?.end || sourceRun?.input.end || "";
              const capital = item?.capital ?? sourceRun?.input.capital;
              const parameters = item?.parameters || sourceRun?.input.parameters || {};
              const warnings = [...new Set(linked.flatMap(run => run.result?.warnings || []).concat(row.run?.result?.warnings || []))];
              const checks = row.status.checks || [];
              const versions = [...new Set(linked.map(run => run.input.strategy.version).filter(Boolean))];
              const composite = !!item && ids.length > 1;
              const included = !!item && settings.copies[item.id] > 0;
              const next = item ? selectPortfolioHistory(settings.copies, catalog, runs, item, row.strategyId) : null;
              const canFit = !next || Object.values(next).filter(value => value > 0).length <= 100;
              const canSelect = !!item && canAddPortfolioCandidate(item) && canFit;
              const key = item ? "item:" + item.id : "run:" + (row.run?.id || row.strategyId);
              const riskDetails = portfolioRiskDetails(row, risk.ready);
              const importingThisRun = !!row.run && importState?.runId === row.run.id
                && (importState.phase === "importing" || importState.phase === "verifying");
              const importError = !!row.run && importState?.runId === row.run.id
                && importState.phase === "error" ? importState.error : undefined;
              return (
                <div className="strategy-picker-option" role="listitem" key={key}
                  data-history-id={item?.id} data-run-id={ids.length === 1 ? ids[0] : undefined}>
                  <div className="strategy-picker-option-top">
                    <Checkbox
                      aria-label={(included ? "Remove " : "Add ") + strategyTitle(group.name) + " " + row.symbol + " " + row.timeframe
                        + (start && end ? " " + start + " to " + end : "")}
                      checked={included} disabled={!included && !canSelect}
                      onChange={event => {
                        if (!item) return;
                        if (event.currentTarget.checked) choose(selectPortfolioHistory(settings.copies, catalog, runs, item, row.strategyId));
                        else {
                          const copies = { ...settings.copies };
                          delete copies[item.id];
                          choose(copies);
                        }
                      }}
                    />
                    <div className="strategy-picker-option-main">
                      <Group gap="xs" wrap="wrap">
                        <Text size="sm" fw={600}>{row.symbol || "No market"} / {row.timeframe || "No timeframe"}</Text>
                        <Badge size="xs" variant="light" color={statusDisplay(row.status).color} title={statusDisplay(row.status).description}>{statusDisplay(row.status).label}</Badge>
                        {warnings.length > 0 && <Badge size="xs" variant="outline" color="orange">{warnings.length} run warning{warnings.length === 1 ? "" : "s"}</Badge>}
                        {checks.length > 0 && <Badge size="xs" variant="outline" color={statusDisplay(row.status).color}>{checks.length} research note{checks.length === 1 ? "" : "s"}</Badge>}
                        {composite && <Badge size="xs" variant="outline">Combined history - {ids.length} runs</Badge>}
                        {item?.latest_replay && <Badge size="xs" variant="outline">Extended history</Badge>}
                        {!item && <Badge size="xs" variant="outline">Not imported</Badge>}
                      </Group>
                      <Text size="xs" c="dimmed">
                        {start && end ? start + " to " + end : "No saved window"}
                        {capital != null ? " | Starting capital " + money(capital) : ""}
                        {sourceRun ? " | " + sourceRun.input.stage : ""}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {composite ? `Combined history from ${ids.length} runs` : ids.length ? "Exact run history" : "Unlinked history"}
                        {versions.length ? " | Source " + versions.join(", ") : ""}
                      </Text>
                    </div>
                    <div className="strategy-picker-option-result">
                      <div className="strategy-picker-option-metrics">
                        <div><Text size="xs" c="dimmed">Saved history P&amp;L</Text>
                          <Text className="strategy-picker-pnl" fw={700}
                            c={row.pnl == null ? "dimmed" : row.pnl < 0 ? "red" : "teal"} size="sm">
                            {row.pnl == null ? "Unavailable" : money(row.pnl)}
                          </Text></div>
                        <div><Text size="xs" c="dimmed">Daily max drawdown</Text>
                          <Text className="strategy-picker-drawdown" fw={700} size="sm">
                            {risk.pending.includes(row.run?.id || "") && !item ? "Calculating…" : drawdownText(riskDetails.maxDrawdownPercent)}
                          </Text></div>
                      </div>
                      <Text size="xs" c="dimmed" className="strategy-picker-score">
                        P&amp;L ÷ drawdown: {risk.pending.includes(row.run?.id || "") && !item ? "Calculating…" : scoreText(riskDetails.score)}
                      </Text>
                    </div>
                    {!item && row.run?.status === "Succeeded" && (
                      <Button size="compact-xs" variant="light" loading={importingThisRun}
                        disabled={refreshing && !importingThisRun}
                        onClick={() => void refreshEvidence(row.run?.id)}>Import exact run</Button>
                    )}
                    {!item && row.run?.status !== "Succeeded" && onAction && (
                      <Button size="compact-xs" variant="light"
                        onClick={() => onAction(row.status.action || { kind: "configure-run", label: "Research", strategyId: row.strategyId })}>
                        Research
                      </Button>
                    )}
                  </div>
                  <Group gap="xs" className="strategy-picker-option-links">
                    {ids.length === 1 && <Button component="a" href={href("runs", "inspect~" + ids[0])}
                      size="compact-xs" variant="subtle">Inspect run</Button>}
                    {item?.research_integrity_error && <Text size="xs" c="red">{item.research_integrity_error}</Text>}
                  </Group>
                  {composite && <details className="strategy-picker-source-links">
                    <summary>Inspect source runs ({ids.length})</summary>
                    <Group gap="xs">{ids.map((id, index) => <Button key={id} component="a" href={href("runs", "inspect~" + id)}
                      size="compact-xs" variant="subtle">Run {index + 1}</Button>)}</Group>
                  </details>}
                  {importingThisRun && <Text size="xs" className="strategy-picker-import-status" role="status">
                    {importState?.phase === "importing" ? "Importing exact run…" : "Verifying exact history…"}
                  </Text>}
                  {importError && <Text size="xs" c="red" className="strategy-picker-import-status" role="alert">{importError}</Text>}
                  {!item && row.run && risk.errors[row.run.id] && <Text size="xs" c="red" className="strategy-picker-import-status">
                    Daily drawdown unavailable: {risk.errors[row.run.id]}
                  </Text>}
                  <details className="strategy-picker-option-details">
                    <summary>Parameters and evidence{warnings.length || checks.length ? " | " + (warnings.length + checks.length) + " notes" : ""}</summary>
                    <Code block>{JSON.stringify(parameters, null, 2)}</Code>
                    <Text size="xs">Research status: {row.status.finding}</Text>
                    {warnings.map((warning, index) => <Text size="xs" key={"warning:" + index}>Run warning: {warning}</Text>)}
                    {checks.map((check, index) => <Text size="xs" key={"check:" + index}>Research check: {check}</Text>)}
                    {item?.reasons.map((reason, index) => <Text size="xs" key={"history:" + index}>Saved history note: {reason}</Text>)}
                  </details>
                </div>
              );
            })}
          </div>
        )}
      </section>
    );
  }
}
