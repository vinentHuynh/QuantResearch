import { researchStages, type ResearchStage } from "../../../shared/ts/progress.ts";
import "./strategyTesting.css";

export function ResearchStages({ stage, compact = false }: { stage?: ResearchStage; compact?: boolean }) {
  return <ol className="testing-stages" aria-label="Research milestones">
    {researchStages.map(s => <li key={s.stage} data-done={stage != null && stage >= s.stage} title={s.description}>
      <span>{s.stage}. {s.label}</span>{(stage != null || !compact) && <strong>{stage == null ? s.description : stage >= s.stage ? "Recorded" : "Not established"}</strong>}
    </li>)}
  </ol>;
}
