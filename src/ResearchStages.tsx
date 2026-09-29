import { researchStages, type ResearchStage } from "./researchProgress";
import "./strategyTesting.css";

export function ResearchStages({ stage }: { stage: ResearchStage }) {
  return <ol className="testing-stages" aria-label="Research milestones">
    {researchStages.map(s => <li key={s.stage} data-done={stage >= s.stage} title={s.description}>
      <span>{s.stage}. {s.label}</span><strong>{stage >= s.stage ? "Recorded" : "Not established"}</strong>
    </li>)}
  </ol>;
}
