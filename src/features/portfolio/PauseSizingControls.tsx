import { NumberInput, Select, SimpleGrid, Switch, Text, TextInput } from "@mantine/core";
import type { GatePolicy } from "../../../shared/ts/portfolio.ts";
import { sizingSettings, type SizingSettings } from "../../../shared/ts/riskSizing.ts";

export function PauseSizingControls({
  policy,
  updatePolicy,
}: {
  policy: GatePolicy;
  updatePolicy: (next: Partial<GatePolicy>) => void;
}) {
  const sizing = sizingSettings(policy);
  const volatility = ["volatility", "portfolio", "fixed"].includes(policy.mode);
  const changeSizing = (next: Partial<SizingSettings>) =>
    updatePolicy({ sizing: { ...sizing, ...next } });
  const numberField = (
    label: string,
    value: number,
    set: (value: number) => void,
    props: { min?: number; max?: number; step?: number; decimal?: boolean } = {},
  ) => (
    <NumberInput
      label={label}
      size="xs"
      min={props.min}
      max={props.max}
      step={props.step}
      allowDecimal={!!props.decimal}
      decimalScale={props.decimal ? 2 : undefined}
      value={value}
      onChange={(next) => set(Number(next))}
    />
  );

  return (
    <section className="wb-card collective-policy-settings">
      <Switch
        label="Enable pause/resume replay"
        checked={policy.enabled}
        onChange={(event) => updatePolicy({ enabled: event.currentTarget.checked })}
      />
      {policy.enabled ? (
        <>
          <Select
            label="Replay mode"
            size="xs"
            value={policy.mode}
            onChange={(value) =>
              updatePolicy({
                mode: (value || "fixed") as GatePolicy["mode"],
                sizing: {
                  ...sizing,
                  estimator:
                    value === "volatility" && sizing.estimator === "legacy"
                      ? "legacy"
                      : sizing.estimator === "legacy"
                        ? "ewma"
                        : sizing.estimator,
                },
              })
            }
            data={[
              { value: "fixed", label: "Constant size (no pause)" },
              { value: "portfolio", label: "Portfolio-aware volatility sizing" },
              { value: "deterioration", label: "Sustained deterioration / manual review" },
              { value: "rolling", label: "Rolling closed-trade losses" },
              { value: "manual", label: "Manual pause / resume schedule" },
              { value: "streak", label: "Consecutive losing trades" },
              { value: "drawdown", label: "Shadow equity drawdown" },
              { value: "volatility", label: "Scale size by realized volatility (no pause)" },
            ]}
          />
          {policy.mode !== "manual" && policy.mode !== "deterioration" && (
            <div className="wb-policy-group">
              <h3>{volatility ? "Size by" : "Pause when"}</h3>
              <SimpleGrid cols={2} spacing={8}>
                {policy.mode === "fixed" ? (
                  numberField(
                    "Constant size multiple",
                    sizing.fixedSize,
                    (value) => changeSizing({ fixedSize: Math.max(0, Math.min(4, value)) }),
                    { min: 0, max: 4, step: 0.25, decimal: true },
                  )
                ) : policy.mode === "rolling" ? (
                  <>
                    {numberField("Lookback trades", policy.lookback, (value) => updatePolicy({ lookback: Math.max(2, value || 2) }), { min: 2, max: 100 })}
                    {numberField("Rolling loss threshold ($ / copy)", policy.lossLimit, (value) => updatePolicy({ lossLimit: Math.max(0, value || 0) }), { min: 0 })}
                  </>
                ) : policy.mode === "streak" ? (
                  numberField("Consecutive losses to pause", policy.streak, (value) => updatePolicy({ streak: Math.max(1, value || 1) }), { min: 1, max: 50 })
                ) : policy.mode === "drawdown" ? (
                  numberField("Drawdown threshold ($ / copy)", policy.drawdown, (value) => updatePolicy({ drawdown: Math.max(1, value || 1) }), { min: 1 })
                ) : (
                  <>
                    {numberField("Volatility lookback (observations)", policy.volLookback, (value) => updatePolicy({ volLookback: Math.min(250, Math.max(10, value || 10)) }), { min: 10, max: 250 })}
                    {numberField("Maximum size multiple", policy.volCap, (value) => updatePolicy({ volCap: Math.min(4, Math.max(0.25, value || 1)) }), { min: 0.25, max: 4, step: 0.25, decimal: true })}
                  </>
                )}
              </SimpleGrid>
            </div>
          )}
          {!volatility && policy.mode !== "manual" && policy.mode !== "deterioration" && (
            <div className="wb-policy-group">
              <h3>Resume after</h3>
              <SimpleGrid cols={2} spacing={8}>
                {numberField("Cooldown (calendar days)", policy.cooldown, (value) => updatePolicy({ cooldown: Math.max(1, value || 1) }), { min: 1, max: 365 })}
                {numberField("Shadow recovery trades", policy.recovery, (value) => updatePolicy({ recovery: Math.max(1, value || 1) }), { min: 1, max: 100 })}
              </SimpleGrid>
            </div>
          )}
          {(policy.mode === "volatility" ||
            policy.mode === "portfolio" ||
            policy.mode === "deterioration" ||
            sizing.portfolioVolLimit > 0 ||
            sizing.equityVolLimit > 0 ||
            sizing.lossLimit > 0) && (
            <div className="wb-policy-group">
              <h3>Frozen risk calibration</h3>
              <TextInput
                size="xs"
                type="date"
                label="Calibration end (UTC)"
                value={sizing.calibrationEnd}
                onChange={(event) => changeSizing({ calibrationEnd: event.currentTarget.value })}
              />
              <Select
                size="xs"
                label="Volatility estimator"
                value={policy.sizing ? sizing.estimator : "legacy"}
                onChange={(value) => changeSizing({ estimator: value as SizingSettings["estimator"] })}
                data={[
                  { value: "ewma", label: "Exponentially weighted observed sessions" },
                  { value: "session", label: "Observed sessions, including zero P&L" },
                  ...(policy.mode === "volatility"
                    ? [{ value: "legacy", label: "Legacy nonzero days / chart-window target" }]
                    : []),
                ]}
              />
              <SimpleGrid cols={2} spacing={8} mt="xs">
                {numberField("Volatility floor / target", sizing.floorFraction, (value) => changeSizing({ floorFraction: value }), { min: 0.01, max: 1, step: 0.1, decimal: true })}
                {numberField("Max size change per entry", sizing.maxChange, (value) => changeSizing({ maxChange: value }), { min: 0.01, max: 4, step: 0.05, decimal: true })}
              </SimpleGrid>
              <Text size="xs" c="dimmed">
                {policy.mode === "volatility" && (!policy.sizing || sizing.estimator === "legacy")
                  ? "Legacy sizing uses nonzero days and recalibrates from the chart start. The frozen date, floor and step controls do not change legacy book sizing; portfolio limits still use the frozen calibration. Choose a session estimator for the revised sizing method."
                  : "The calibration date stays fixed when chart dates change. Observed zero-P&L sessions count; missing dates do not. These dates have already been researched."}
              </Text>
            </div>
          )}
          {policy.mode === "deterioration" && (
            <div className="wb-policy-group">
              <h3>Review trigger</h3>
              {numberField("Monitoring trades", sizing.monitorWindow, (value) => changeSizing({ monitorWindow: value }), { min: 20, max: 250 })}
              {numberField("Consecutive confirmations", sizing.monitorConfirm, (value) => changeSizing({ monitorConfirm: value }), { min: 2, max: 50 })}
              {numberField("Normalized shortfall threshold", sizing.monitorThreshold, (value) => changeSizing({ monitorThreshold: value }), { min: 1, max: 10, step: 0.5, decimal: true })}
              <Text size="xs" c="dimmed">
                Requires 50 calibration trades. A sustained shortfall against the frozen normalized mean pauses entries until a dated manual resume below. The threshold is a research setting, not a statistical confidence level.
              </Text>
            </div>
          )}
          <div className="wb-policy-group">
            <h3>Portfolio limits</h3>
            {numberField("Portfolio daily risk cap ($; 0 = auto/off)", sizing.portfolioVolLimit, (value) => changeSizing({ portfolioVolLimit: value }), { min: 0 })}
            {numberField("Equity-index daily risk cap ($; 0 = off)", sizing.equityVolLimit, (value) => changeSizing({ equityVolLimit: value }), { min: 0 })}
            {numberField("Portfolio closed-loss limit ($; 0 = off)", sizing.lossLimit, (value) => changeSizing({ lossLimit: value }), { min: 0 })}
            <Text size="xs" c="dimmed">
              Portfolio mode derives its risk cap from frozen calibration when zero. Other modes leave it off. The equity cap groups ES, NQ, YM, RTY and their micros. A closed-loss breach blocks new entries for the rest of the replay; existing positions retain their exits.
            </Text>
          </div>
          <div className="wb-policy-group">
            <h3>Contract feasibility</h3>
            <Switch
              size="xs"
              label="Round down to recorded whole contracts"
              checked={sizing.wholeContracts}
              onChange={(event) => changeSizing({ wholeContracts: event.currentTarget.checked })}
            />
            {sizing.wholeContracts && (
              <>
                {numberField("Assumed margin per contract ($)", sizing.marginPerContract, (value) => changeSizing({ marginPerContract: value }), { min: 0 })}
                {numberField("Shared margin budget ($; 0 = off)", sizing.marginBudget, (value) => changeSizing({ marginBudget: value }), { min: 0 })}
                <Text size="xs" c="dimmed">
                  Uses a user-supplied uniform margin assumption. One recorded contract at 75% rounds to zero. Micro contracts require their own data, fees and rerun.
                </Text>
              </>
            )}
          </div>
          <Text size="xs" c="dimmed">
            {volatility
              ? "Sizing is fixed at entry; pause recovery rules do not apply."
              : policy.mode === "manual" || policy.mode === "deterioration"
                ? "Schedule entry pauses and resumes below. A pause stays in effect until a manual resume."
                : "Recovery counts only completed shadow trades entered after the pause. The cooldown and positive recovery must both pass. Existing positions keep their exits."}
          </Text>
        </>
      ) : (
        <Text size="sm" c="dimmed">
          Test a fixed loss rule, or volatility-scaled sizing, against the same strategies always on. Turning it on switches accounting to closed trades.
        </Text>
      )}
    </section>
  );
}
