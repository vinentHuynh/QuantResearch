import { statusDisplay, type StrategyStageStatus } from "../../../shared/ts/strategyLifecycle.ts";
import "./researchStageIndicators.css";

export function ResearchGroupHeading({ id, title, count, hint }: { id: string; title: string; count: number; hint: string }) {
  return (
    <div className="wb-strategy-group-head">
      <h2 id={id}>{title}<span className="wb-group-count">{count}</span></h2>
      <p>{hint}</p>
    </div>
  );
}

export function StageDots({ status }: { status: StrategyStageStatus }) {
  const display = statusDisplay(status);
  const plain = display.state === "benchmark" || display.state === "tracking";
  return (
    <span className="wb-stage-dots" aria-label={display.label} role="img">
      {[1, 2, 3, 4, 5].map((stage) => {
        const tone = plain ? "todo"
          : stage < display.stage || (stage === display.stage && display.state === "ready") ? "done"
            : stage === display.stage ? display.state : "todo";
        return <i key={stage} className={`is-${tone}`} />;
      })}
    </span>
  );
}

export function StatusChip({ status }: { status: StrategyStageStatus }) {
  const display = statusDisplay(status);
  return <span className={`wb-status-chip is-${display.state}`} title={display.description}>{display.label}</span>;
}
