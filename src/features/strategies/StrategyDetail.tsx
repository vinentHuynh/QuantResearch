import type { ReactNode } from "react";
import { Button, Group, Menu, Text } from "@mantine/core";
import { IconArchive, IconArchiveOff, IconArrowLeft, IconDots } from "@tabler/icons-react";
import type { Run, RunSummary } from "../../../shared/ts/workbenchModels.ts";
import { statusDisplay, type StrategyStageStatus } from "../../../shared/ts/strategyLifecycle.ts";
import { outcomeLabel, strategySourceTags } from "../../../shared/ts/formatting.ts";
import { readinessChecks } from "../../../shared/ts/readiness.ts";
import { href } from "../../app/navigation";
import { workbenchRequest as request } from "../../shared/api/workbench";
import { strategyTitle } from "../../shared/formatting/strategyTitle";
import { ResearchNote } from "../../shared/ui/StrategyStageBadge";
import { useStrategyStages } from "../../shared/ui/strategyStageContext";
import type { WorkbenchController } from "../workspace/useWorkbenchController";
import { rowAttempts, rowEvaluations, type ResearchRow } from "./researchRows";
import { StatusChip } from "./StrategiesOverview";
import "./strategiesOverview.css";

const stageNames = ["", "Backtest", "Evaluation", "Robustness", "Forward test", "Ready"];
const sessionNames: Record<string, string> = { "full-trading-day": "full trading day", "new-york-rth": "New York RTH" };
const sessionLabel = (session: string) => sessionNames[session] || session.replaceAll("-", " ");

const money = (value: number) =>
  `${value < 0 ? "−" : "+"}$${Math.abs(Math.round(value)).toLocaleString("en-US")}`;
const percent = (value: number) => `${value < 0 ? "−" : "+"}${Math.abs(value * 100).toFixed(1)}%`;
const shortDate = (value: string) =>
  new Date(value.length <= 10 ? `${value}T00:00:00Z` : value).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });

function stageState(number: number, status: StrategyStageStatus) {
  const failed = status.failedStage === number || (status.kind === "failed-checks" && !status.failedStage && number === Math.min(5, status.stage + 1));
  const blocked = status.blockedStage === number;
  const running = number === 4 && status.kind === "forward-testing";
  const complete = status.stage >= number && !failed && !running;
  if (failed) return { tone: "failed", label: "Failed" };
  if (complete) return { tone: "done", label: "Complete" };
  if (blocked) return { tone: "blocked", label: `Blocked${status.checks.length ? ` · ${status.checks.length} open check${status.checks.length === 1 ? "" : "s"}` : ""}` };
  if (running) return { tone: "running", label: "Running" };
  if (number === status.stage + 1 || (number === 5 && status.kind === "forward-tested")) return { tone: "next", label: "Next up" };
  return { tone: "todo", label: "Locked" };
}

function Section({ title, aside, children, label }: { title: string; aside?: ReactNode; children: ReactNode; label?: string }) {
  return (
    <section className="wb-card wb-detail-section" aria-label={label || title}>
      <div className="wb-card-head">
        <h2>{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function StrategyDetail({ row, controller, onArchive }: {
  row: ResearchRow | undefined;
  controller: WorkbenchController;
  onArchive: (runId: string, archived: boolean) => void;
}) {
  const { onAction } = useStrategyStages();
  const { state, action, inspect, reuse, busy, setResearchSelection, go } = controller;
  if (!state) return null;
  if (!row) {
    return (
      <div className="wb-content wb-strategy-detail">
        <a className="wb-back" href={href("strategies")}><IconArrowLeft size={14} />Strategies</a>
        <div className="wb-card"><h2>Strategy not found</h2><Text size="sm" c="dimmed">It may have been archived or renamed. Go back to the list to find it.</Text></div>
      </div>
    );
  }
  const attempts = rowAttempts(state, row);
  const evaluations = rowEvaluations(state, attempts);
  const seed = attempts.find((run) => run.id === row.config?.runId) || attempts[0];
  const history = attempts.find((run) => run.status === "Succeeded" && run.result) || seed;
  const display = statusDisplay(row.status);
  const tags = strategySourceTags(row.strategy.name);
  const reviews = attempts.flatMap((run) => run.stage_assessments || []);
  const openRun = (run: RunSummary) => void action(() => inspect(run));
  const newBacktest = seed
    ? () => void action(async () => reuse(await request<Run>(`/runs/${seed.id}`)))
    : () => controller.configure(row.strategy.id);
  const parameters = Object.entries(history?.input.parameters || row.config?.parameters || {});

  return (
    <>
      <div className="wb-content wb-strategy-detail">
        <a className="wb-back" href={href("strategies")}><IconArrowLeft size={14} />Strategies</a>
        <header className="wb-detail-head">
          <div className="wb-detail-title">
            <h1>{strategyTitle(row.strategy.name)}</h1>
            <div className="wb-detail-meta">
              {tags.map((tag) => <span className="wb-source-tag" key={tag}>{tag}</span>)}
              <span>{row.config ? `${row.config.symbol} ${row.config.timeframe} · ${sessionLabel(row.config.session)}` : "No backtest yet"}</span>
              {row.config && <span>· {attempts.length} {attempts.length === 1 ? "attempt" : "attempts"}</span>}
              <StatusChip row={row} />
              {row.archived && <span className="wb-source-tag">Archived</span>}
            </div>
          </div>
          <Group gap="xs">
            <Button variant="default" size="xs" onClick={newBacktest} disabled={busy}>New backtest from this</Button>
            {row.status.action && onAction && !row.archived && (
              <Button size="xs" onClick={() => onAction(row.status.action!)}>{row.status.action.label}</Button>
            )}
            {seed && (
              <Menu position="bottom-end" withinPortal>
                <Menu.Target>
                  <Button variant="default" size="xs" aria-label="More actions"><IconDots size={15} /></Button>
                </Menu.Target>
                <Menu.Dropdown>
                  <Menu.Item
                    leftSection={row.archived ? <IconArchiveOff size={14} /> : <IconArchive size={14} />}
                    disabled={busy || (!row.archived && !!row.config?.busy)}
                    onClick={() => onArchive(seed.id, !row.archived)}
                  >
                    {row.archived ? "Restore configuration" : "Archive configuration"}
                  </Menu.Item>
                </Menu.Dropdown>
              </Menu>
            )}
          </Group>
        </header>

        <ol className="wb-stage-track" aria-label="Research stages">
          {[1, 2, 3, 4, 5].map((number) => {
            const stage = stageState(number, row.status);
            return (
              <li key={number} className={`is-${stage.tone}`}>
                <strong>{number} · {stageNames[number]}</strong>
                <span>{stage.label}</span>
              </li>
            );
          })}
        </ol>

        <Section title="Where it stands" label="Where it stands">
          <Text size="sm" c="dimmed" mb={4}>{display.description}</Text>
          <ResearchNote finding={row.status.finding} checks={row.status.checks} assessment={row.status.assessment} />
          {display.stage === 3 && (
            <details className="wb-detail-criteria">
              <summary>What robustness asks for</summary>
              <ul>{readinessChecks.robustness.map((check) => <li key={check.label}>{check.label}</li>)}</ul>
            </details>
          )}
        </Section>

        {history?.result && (
          <Section title="Full history" aside={<Text size="xs" c="dimmed">{shortDate(history.input.start)} – {shortDate(history.input.end)}</Text>}>
            <div className="wb-detail-figures">
              <div><b className={history.result.metrics.net_pnl < 0 ? "wb-loss" : "wb-gain"}>{money(history.result.metrics.net_pnl)}</b><span>net P&amp;L · {percent(history.result.metrics.net_return)}</span></div>
              <div><b className="wb-loss">{percent(-Math.abs(history.result.metrics.max_drawdown))}</b><span>max drawdown</span></div>
              <div><b>{(history.result.metrics.trades ?? 0).toLocaleString()}</b><span>trades</span></div>
              <div><Button size="compact-sm" variant="subtle" onClick={() => openRun(history)}>Open results</Button></div>
            </div>
          </Section>
        )}

        <Section
          title="Evaluations"
          aside={<a className="wb-link" href={href("runs", "evaluations")}>All evaluations</a>}
        >
          {evaluations.length ? (
            <div className="wb-eval-cards">
              {evaluations.map((evaluation) => {
                const baseline = evaluation.result?.scenarios[0];
                const outcome = outcomeLabel(evaluation.outcome || evaluation.status);
                return (
                  <button
                    type="button"
                    key={evaluation.id}
                    className="wb-eval-card"
                    onClick={() => { setResearchSelection(evaluation.id); go("runs", "evaluations"); }}
                  >
                    <strong>{evaluation.name}</strong>
                    <span className={`wb-outcome is-${outcome.toLowerCase()}`}>{outcome}</span>
                    {baseline && (
                      <span className="wb-eval-figures">
                        <b>{money(baseline.metrics.net_pnl)}</b> net · {percent(-Math.abs(baseline.metrics.max_drawdown))} DD · {baseline.metrics.trades} trades
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ) : (
            <Text size="sm" c="dimmed">No evaluation yet. {display.stage <= 2 ? "Plan one on later data, with pass criteria set before the run." : ""}</Text>
          )}
        </Section>

        <Section
          title="Recent runs"
          aside={attempts.length > 0 && <a className="wb-link" href={href("runs")}>{attempts.length === 1 ? "Open Runs" : `All ${attempts.length} attempts in Runs`}</a>}
        >
          {attempts.length ? (
            <div className="wb-detail-table" role="table" aria-label="Recent runs">
              <div role="row" className="is-head">
                {["Date", "Purpose", "Market · window", "Net return", "Max DD", "Trades"].map((heading) => <span role="columnheader" key={heading}>{heading}</span>)}
              </div>
              {attempts.slice(0, 8).map((run) => (
                <button type="button" role="row" key={run.id} onClick={() => openRun(run)} aria-label={`Open run ${run.id.slice(0, 8)}`}>
                  <span role="cell">{shortDate(run.created_at)}</span>
                  <span role="cell">{run.input.stage}</span>
                  <span role="cell">{run.input.dataset.symbol} · {run.input.start} – {run.input.end}</span>
                  <span role="cell" className={run.result ? (run.result.metrics.net_return < 0 ? "wb-loss" : "wb-gain") : "wb-loss"}>
                    {run.result ? percent(run.result.metrics.net_return) : run.status}
                  </span>
                  <span role="cell">{run.result ? percent(-Math.abs(run.result.metrics.max_drawdown)) : "—"}</span>
                  <span role="cell">{run.result ? (run.result.metrics.trades ?? 0).toLocaleString() : "—"}</span>
                </button>
              ))}
            </div>
          ) : (
            <Text size="sm" c="dimmed">No runs recorded for this setup yet.</Text>
          )}
        </Section>

        {parameters.length > 0 && (
          <details className="wb-card wb-detail-settings">
            <summary>Settings used in the latest run</summary>
            <dl>
              {parameters.map(([key, value]) => (
                <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd></div>
              ))}
              {history && (
                <div><dt>Costs</dt><dd>${history.input.fee}/side · {history.input.slippage} tick slippage · ${history.input.capital.toLocaleString()} capital</dd></div>
              )}
            </dl>
          </details>
        )}

        {reviews.length > 0 && (
          <details className="wb-card wb-detail-settings">
            <summary>Review history ({reviews.length})</summary>
            {reviews.map((review) => (
              <Text size="xs" key={review.id} mt={6}>
                {review.recordedAt.slice(0, 10)} · {stageNames[review.attemptedStage]} {review.outcome}: {review.findings}
              </Text>
            ))}
          </details>
        )}
      </div>
    </>
  );
}
