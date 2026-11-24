import { Fragment, useState } from "react";
import { Alert, Button, Code, ScrollArea, Text } from "@mantine/core";
import { IconChevronDown, IconChevronRight, IconDatabase } from "@tabler/icons-react";
import type { Dataset } from "../../../shared/ts/workbenchModels.ts";
import { workbenchRequest as request } from "../../shared/api/workbench";
import { PageHeader } from "../../shared/ui/PageHeader";
import { WorkbenchAlerts } from "../workspace/WorkbenchChrome";
import type { WorkbenchController } from "../workspace/useWorkbenchController";
import { shortId } from "../workspace/workbenchModel";
import "./datasets.css";

const DAY = 86_400_000;
const dateLabel = (value: string, withYear = true) =>
  new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric", ...(withYear ? { year: "numeric" } : {}), timeZone: "UTC" });
const monthLabel = (value: string) =>
  new Date(value).toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });

function freshness(last: string) {
  const days = Math.floor((Date.now() - Date.parse(last)) / DAY);
  if (days <= 1) return { label: days <= 0 ? "Today" : "Yesterday", ok: true };
  if (days < 14) return { label: `${days} days behind`, ok: days <= 3 };
  return { label: `${Math.round(days / 7)} weeks behind`, ok: false };
}

/** Newest data first: the version backtests use unless you pick another. */
const newestFirst = (a: Dataset, b: Dataset) => b.last.localeCompare(a.last) || b.registered_at.localeCompare(a.registered_at);

export function DatasetsPage({ controller }: { controller: WorkbenchController }) {
  const { action, setNotice, state } = controller;
  const [open, setOpen] = useState<Record<string, boolean>>({});
  if (!state) return null;
  const markets = Object.entries(
    state.datasets.reduce<Record<string, Dataset[]>>((groups, dataset) => {
      (groups[dataset.symbol] ||= []).push(dataset);
      return groups;
    }, {}),
  )
    .map(([symbol, versions]) => ({ symbol, versions: [...versions].sort(newestFirst) }))
    .sort((a, b) => b.versions[0].last.localeCompare(a.versions[0].last) || a.symbol.localeCompare(b.symbol));

  return (
    <>
      <PageHeader
        crumb="Data"
        title="Market data"
        actions={
          <Button
            size="xs"
            leftSection={<IconDatabase size={14} />}
            loading={state.import.status === "Running"}
            onClick={() =>
              void action(async () => {
                await request("/import", {});
                setNotice("Data import started. Progress appears below.");
              })
            }
          >
            Import data ZIPs
          </Button>
        }
      />
      <WorkbenchAlerts controller={controller} />
      <div className="wb-content wb-data">
        {(state.import.log || state.import.error) && (
          <section className="wb-card">
            <h2>Import</h2>
            {state.import.log && <Code block mt="xs" className="wb-log">{state.import.log}</Code>}
            {state.import.error && <Alert color="red" mt="sm">{state.import.error}</Alert>}
          </section>
        )}
        <section className="wb-table-card" aria-label="Markets">
          <ScrollArea>
            <div className="wb-market-table" role="table" aria-label="Market data">
              <div role="row" className="is-head">
                {["Market", "Covers", "Up to date?", "1-minute bars", "Quality", "Versions"].map((heading) => (
                  <span role="columnheader" key={heading}>{heading}</span>
                ))}
              </div>
              {markets.map(({ symbol, versions }) => {
                const current = versions[0];
                const first = versions.reduce((earliest, version) => (version.first < earliest ? version.first : earliest), current.first);
                const fresh = freshness(current.last);
                const expanded = !!open[symbol];
                return (
                  <Fragment key={symbol}>
                    <div role="row" className="wb-market-row">
                      <span role="cell" className="wb-market-name">
                        <strong>{symbol}</strong>
                        <small>{current.source}</small>
                      </span>
                      <span role="cell">{monthLabel(first)} – {dateLabel(current.last)}</span>
                      <span role="cell"><span className={`wb-fresh ${fresh.ok ? "is-ok" : "is-behind"}`}>{fresh.label}</span></span>
                      <span role="cell" className="mono">{current.rows.toLocaleString()}</span>
                      <span role="cell" className="wb-market-quality">
                        <span>Usable, with known gaps</span>
                        <small>
                          {(current.quality.gaps_over_one_minute ?? 0).toLocaleString()} gaps · {current.quality.contract_changes ?? 0} contract changes
                        </small>
                      </span>
                      <span role="cell">
                        <button
                          type="button"
                          className="wb-link-button wb-version-toggle"
                          aria-expanded={expanded}
                          onClick={() => setOpen((current) => ({ ...current, [symbol]: !expanded }))}
                        >
                          {expanded ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
                          {expanded ? "Hide " : ""}{versions.length} {versions.length === 1 ? "version" : "versions"}
                        </button>
                      </span>
                    </div>
                    {expanded && versions.map((version, index) => (
                      <div role="row" className="wb-version-row" key={version.id}>
                        <span role="cell"><Code>{shortId(version.id)}</Code></span>
                        <span role="cell">Imported {dateLabel(version.registered_at, false)}</span>
                        <span role="cell">to {dateLabel(version.last, false)}, {version.last.slice(11, 16) || "00:00"} UTC</span>
                        <span role="cell" className="mono">{version.rows.toLocaleString()}</span>
                        <span role="cell"><span className={`wb-version-tag${index === 0 ? " is-current" : ""}`}>{index === 0 ? "In use" : "Older"}</span></span>
                        <span role="cell">
                          <details className="wb-provenance">
                            <summary>Provenance</summary>
                            <Text size="xs">{version.archive}</Text>
                            <Code block>{JSON.stringify(version.quality, null, 2)}</Code>
                            <Text size="xs" className="wb-break">SHA256 {version.checksum}</Text>
                            {version.warnings.map((warning) => <Text key={warning} size="xs" mt="xs">{warning}</Text>)}
                          </details>
                        </span>
                      </div>
                    ))}
                  </Fragment>
                );
              })}
            </div>
          </ScrollArea>
          {!state.datasets.length && (
            <div className="wb-empty"><Text>No market data yet. Import the local ZIP archives to begin.</Text></div>
          )}
        </section>
        <Text size="sm" c="dimmed">
          Import scans ZIP files under <Code>data/</Code>. Unchanged archives are reused; changed ones become a new version,
          and backtests use the newest version unless you pick another.
        </Text>
      </div>
    </>
  );
}
