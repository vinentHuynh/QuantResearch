import type { ReactNode } from "react";
import {
  Alert,
  Badge,
  Button,
  Drawer,
  SegmentedControl,
  Text,
  TextInput,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { IconPlus, IconSearch } from "@tabler/icons-react";
import type {
  EvaluationView,
  RegimeView,
  RunSummary,
} from "../../../shared/ts/workbenchModels.ts";
import { PageHeader } from "../../shared/ui/PageHeader";
import { EvaluationDetail } from "./EvaluationDetail";
import {
  evaluationOutcomeColor as outcomeColor,
  evaluationStatusColor as color,
} from "./researchModel";
import { ResearchPlanControls } from "./ResearchPlanControls";
import { useResearchController } from "./useResearchController";

export type { EvaluationView, RegimeView };

export function ResearchPage({
  selectedId,
  onSelect,
  alerts,
  runs,
  evaluations,
  regimes,
  refresh,
  inspect,
}: {
  selectedId?: string;
  onSelect: (id: string) => void;
  alerts?: ReactNode;
  runs: RunSummary[];
  evaluations: EvaluationView[];
  regimes: RegimeView[];
  refresh: () => Promise<void>;
  inspect: (run: RunSummary) => void;
}) {
  const isMobile = useMediaQuery("(max-width: 900px)");
  const controller = useResearchController({
    evaluations,
    refresh,
    runs,
    selectedId,
  });
  const {
    current,
    error,
    fails,
    listed,
    meets,
    outcomeFilter,
    planOpen,
    query,
    setError,
    setOutcomeFilter,
    setPlanOpen,
    setQuery,
  } = controller;

  return (
    <>
      <PageHeader
        crumb="Research"
        title="Evaluations & regimes"
        actions={
          <Button
            size="xs"
            variant="light"
            leftSection={<IconPlus size={14} />}
            onClick={() => setPlanOpen(true)}
          >
            Plan walk-forward evaluation
          </Button>
        }
      />
      {alerts}
      {error && !planOpen && (
        <div className="wb-alerts">
          <Alert
            color="red"
            title="Research action failed"
            withCloseButton
            onClose={() => setError("")}
          >
            {error}
          </Alert>
        </div>
      )}
      <div className="wb-ledger">
        <div className="wb-ledger-list">
          <div className="wb-ledger-tools">
            <SegmentedControl
              aria-label="Outcome filter"
              size="xs"
              fullWidth
              value={outcomeFilter}
              onChange={setOutcomeFilter}
              data={[
                { value: "all", label: `All · ${evaluations.length}` },
                { value: "meets", label: `Meets · ${meets.length}` },
                { value: "fails", label: `Does not · ${fails.length}` },
              ]}
            />
            <TextInput
              size="xs"
              aria-label="Search evaluations"
              placeholder="Strategy, market or year"
              leftSection={<IconSearch size={13} />}
              value={query}
              onChange={(event) => setQuery(event.currentTarget.value)}
            />
          </div>
          <ul className="wb-ledger-items" aria-label="Evaluation ledger">
            {listed.map((evaluation) => (
              <li key={evaluation.id}>
                <button
                  type="button"
                  className={`wb-ledger-item${current?.id === evaluation.id ? " active" : ""}`}
                  aria-current={
                    current?.id === evaluation.id ? "true" : undefined
                  }
                  onClick={() => {
                    onSelect(evaluation.id);
                    if (isMobile) {
                      document
                        .querySelector(".wb-ledger-detail")
                        ?.scrollIntoView({ behavior: "smooth" });
                    }
                  }}
                >
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <b>{evaluation.name}</b>
                    <small>
                      {evaluation.created_at.slice(0, 10)} · {evaluation.jobs}{" "}
                      jobs · {evaluation.status}
                    </small>
                  </span>
                  <Badge
                    size="sm"
                    radius="xs"
                    variant="light"
                    color={
                      evaluation.outcome
                        ? outcomeColor(evaluation.outcome)
                        : color(evaluation.status)
                    }
                  >
                    {evaluation.outcome === "Meets criteria"
                      ? "Meets"
                      : evaluation.outcome === "Does not meet criteria"
                        ? "Does not"
                        : evaluation.outcome || "Not scored"}
                  </Badge>
                </button>
              </li>
            ))}
          </ul>
          {!listed.length && (
            <Text p="md" size="sm" c="dimmed">
              {evaluations.length
                ? "No evaluations match."
                : "No evaluations yet."}
            </Text>
          )}
          <Text px="md" py="sm" size="xs" c="dimmed">
            Complete grids and selection records stay visible.
          </Text>
        </div>
        {current ? (
          <EvaluationDetail
            current={current}
            runs={runs}
            regimes={regimes}
            inspect={inspect}
            controller={controller}
          />
        ) : (
          <div className="wb-ledger-detail">
            <section className="wb-card">
              <h2>No evaluations yet</h2>
              <p className="wb-card-sub">
                Start with a declared chronological plan: choose a successful
                run, set folds and criteria, preview, then launch.
              </p>
              <Button
                mt="md"
                variant="light"
                leftSection={<IconPlus size={14} />}
                onClick={() => setPlanOpen(true)}
              >
                Plan walk-forward evaluation
              </Button>
            </section>
          </div>
        )}
      </div>
      <Drawer
        opened={planOpen}
        onClose={() => setPlanOpen(false)}
        position="right"
        size={isMobile ? "100%" : 720}
        title={
          <span className="collective-drawer-title">
            Plan walk-forward evaluation
          </span>
        }
      >
        <ResearchPlanControls
          controller={controller}
          onSelect={onSelect}
          runs={runs}
        />
      </Drawer>
    </>
  );
}
