import { useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Group,
  SegmentedControl,
  Text,
} from "@mantine/core";
import type {
  CollectiveCatalog,
  CollectiveItem,
  CollectiveSeries,
} from "./collectiveModel";
import { assessCondition } from "./strategyCondition";
import "./strategyCondition.css";

const money = (n: number) =>
  n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
type Props = {
  catalog: CollectiveCatalog | null;
  items: CollectiveItem[];
  histories: CollectiveSeries[];
  end: string;
  enabled: boolean;
  permissions: { id: string; state: string; status?: { reason: string } }[];
};
export function StrategyConditionPanel({
  catalog,
  items,
  histories,
  end,
  enabled,
  permissions,
}: Props) {
  const [cutoff, setCutoff] = useState("latest");
  const requested =
    cutoff === "latest" ? new Date().toISOString().slice(0, 10) : end;
  const assessments = useMemo(
    () =>
      items.map((i) =>
        assessCondition(
          i,
          histories.find((s) => s.id === i.id),
          requested,
          catalog?.condition_calibration,
          catalog?.market_data_through?.[i.symbol],
        ),
      ),
    [items, histories, requested, catalog],
  );
  const calibration = catalog?.condition_calibration;
  const unavailable = assessments.filter((s) => !s.available).length;
  return (
    <section
      className="wb-card strategy-condition"
      data-testid="strategy-condition"
    >
      <div className="wb-card-head">
        <h2>Strategy condition</h2>
        <Button
          size="compact-sm"
          variant="default"
          onClick={() => {
            const blob = new Blob(
              [
                JSON.stringify(
                  {
                    computedAt: new Date().toISOString(),
                    requested,
                    calibration,
                    assessments,
                    permissionCutoff: end,
                    permissionReplayEnabled: enabled,
                    permissions,
                  },
                  null,
                  2,
                ),
              ],
              { type: "application/json" },
            );
            const url = URL.createObjectURL(blob),
              link = document.createElement("a");
            link.href = url;
            link.download = `strategy-condition-${requested}.json`;
            link.click();
            URL.revokeObjectURL(url);
          }}
        >
          Export condition
        </Button>
      </div>
      <Text size="sm">
        Baseline performance continues to be assessed while entries are paused.
        Position size and manual resumes do not change this history.
      </Text>
      <Group my="sm">
        <SegmentedControl
          aria-label="Condition cutoff"
          value={cutoff}
          onChange={setCutoff}
          data={[
            { value: "latest", label: "Latest replay" },
            { value: "selected", label: "Selected date" },
          ]}
        />
        <Text size="xs" c="dimmed">
          Requested through {requested} UTC
        </Text>
      </Group>
      {unavailable > 0 && (
        <Alert color="yellow" title="Current status unavailable" mb="sm">
          {unavailable} of {assessments.length} selected histories do not cover
          the requested date. Their last available snapshot appears below. A
          refreshed catalog does not extend a replay. Market-data timestamps do
          not establish that a session is complete.
        </Alert>
      )}
      {!assessments.length && (
        <Text size="sm">Select strategies to inspect their condition.</Text>
      )}
      <div className="condition-cards">
        {assessments.map((s) => {
          const permission = permissions.find((p) => p.id === s.id);
          const label = !enabled
            ? "Replay off"
            : !permission
              ? "Unavailable"
              : permission.state === "Active"
                ? "Enabled"
                : permission.state;
          return (
            <article
              className="condition-book"
              key={s.id}
              data-testid={`condition-${s.id}`}
            >
              <Group justify="space-between" align="flex-start">
                <strong>{s.name}</strong>
                <Badge
                  color={
                    s.condition === "Unusual weakness"
                      ? "red"
                      : s.condition.includes("Watch")
                        ? "yellow"
                        : "gray"
                  }
                  variant="light"
                >
                  {s.condition}
                </Badge>
              </Group>
              <Text size="xs" c="dimmed">
                Historical snapshot: {s.asOf || "unavailable"} UTC · Entry
                permission at {end}: {label}
              </Text>
              <Text size="sm" mt="xs">
                {s.explanation}
              </Text>
              <div className="condition-metrics">
                {[
                  { label: "Last 10 natural trades", w: s.last10 },
                  { label: "Last 30 natural trades", w: s.last30 },
                  { label: "Last 20 observed UTC days", w: s.last20 },
                ].map(({ label, w }) => (
                  <div key={label}>
                    <Text size="xs" c="dimmed">
                      {label} ({w.count}/{w.requested})
                    </Text>
                    <strong>{w.count ? money(w.pnl) : "Unavailable"}</strong>
                    <Text size="xs">
                      {w.start || "—"} → {w.end || "—"}
                    </Text>
                  </div>
                ))}
              </div>
              <Text size="sm">
                Marked drawdown: {money(s.drawdown)} · {s.underwaterDays}{" "}
                calendar days below peak · Natural loss streak:{" "}
                {s.lossStreak ?? "unknown"}
              </Text>
              <details>
                <summary>Evidence and dates</summary>
                <Text size="xs">
                  Replay through {s.simulationThrough || "unknown"}; latest mark{" "}
                  {s.latestMark || "unknown"}; registered market data through{" "}
                  {s.marketThrough || "unknown"}. Latest natural exit:{" "}
                  {s.lastNaturalExit || "none recorded"}.
                </Text>
                <Text size="xs">
                  Drawdown measured from {s.equityStart || "unknown"}; latest
                  peak {s.peakDate || "unknown"}. Exposure overlaps{" "}
                  {s.exposedDays} of the last {s.last20.count} observed days
                  (daily resolution). Zero-trade periods are distinct from
                  missing replay data.
                </Text>
                <Text size="xs">
                  Excluded from natural-trade statistics: {s.excludedSynthetic}{" "}
                  forced exits and {s.unknownExits} exits of unknown type.{" "}
                  {s.inferredExits} exit classifications use legacy worker
                  timing. All recorded P&amp;L remains in marked accounting.
                </Text>
                <Text size="xs">
                  {s.detector
                    ? `CUSUM ${s.detector.cusum.toFixed(2)} / ${s.threshold!.toFixed(2)}; EWMA ${s.detector.ewma.toFixed(2)}; detector through ${s.detector.through}.`
                    : "Detector unavailable for this source and cutoff."}{" "}
                  Terminal marks are excluded from the detector. Independent
                  simulation segments restart its memory.
                </Text>
                {s.reference && (
                  <Text size="xs">
                    Reference: {s.reference.start} → {s.reference.end},{" "}
                    {s.reference.count} normalized observations.
                  </Text>
                )}
                {s.detector && s.detector.events.length > 0 && (
                  <Text size="xs">
                    Recent transitions:{" "}
                    {s.detector.events
                      .slice(-5)
                      .map((e) => `${e.date}: ${e.kind}`)
                      .join("; ")}
                    .
                  </Text>
                )}
                {enabled && permission?.status && (
                  <Text size="xs">
                    Permission rule: {permission.status.reason}
                  </Text>
                )}
                <Text size="xs">{s.evidence}</Text>
              </details>
            </article>
          );
        })}
      </div>
      <Text size="xs" c="dimmed" mt="sm">
        {calibration
          ? `Research detector: frozen reference ends ${calibration.calibrationEnd}; bootstrap family alarm target ${(calibration.validation.target * 100).toFixed(0)}% per ${calibration.validation.horizon} observed days for the ${calibration.sources.length} calibrated books. Validation rate up to ${(calibration.validation.worstRate * 100).toFixed(1)}%; upper bound ${(calibration.validation.worstUpper * 100).toFixed(1)}%. Development check ${calibration.validation.accepted ? "passed" : "failed"}.`
          : "No detector calibration has been published. Loss windows are descriptive."}{" "}
        No warning is a guarantee of profitability. Recovery never resumes
        entries automatically.
      </Text>
      {calibration?.validation.residualVolatilityAlarmRate !== undefined && (
        <Text size="xs" c="dimmed" mt="xs">
          Volatility sensitivity: doubling standardized-residual volatility
          caused warnings in up to{" "}
          {(calibration.validation.residualVolatilityAlarmRate * 100).toFixed(
            1,
          )}
          % of simulated paths without a weaker mean. A warning can reflect
          changing volatility; it is not proof that the strategy lost its edge.
        </Text>
      )}
    </section>
  );
}
