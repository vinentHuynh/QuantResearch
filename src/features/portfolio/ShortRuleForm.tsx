import { useState } from "react";
import { Button, Checkbox, NumberInput, Select, Text, TextInput } from "@mantine/core";
import { defaultSizing, sizingSettings } from "../../../shared/ts/riskSizing.ts";
import type { CollectiveDashboardModel } from "./useCollectiveDashboardModel";

/** Three questions instead of the full control surface; everything else stays under Advanced. */
export function ShortRuleForm({ model }: { model: CollectiveDashboardModel }) {
  const { policy: updatePolicy, settings } = model;
  const current = settings.policy;
  const sizing = sizingSettings(current);
  const [rule, setRule] = useState<"rolling" | "volatility">(current.mode === "volatility" ? "volatility" : "rolling");
  const [resume, setResume] = useState<number>(current.cooldown);
  const [calibrate, setCalibrate] = useState(sizing.calibrationEnd || defaultSizing.calibrationEnd);
  const [whole, setWhole] = useState(sizing.wholeContracts);
  return (
    <form
      className="wb-short-rule"
      onSubmit={(event) => {
        event.preventDefault();
        updatePolicy({
          enabled: true,
          mode: rule,
          cooldown: Math.max(1, resume || 1),
          sizing: { ...sizing, calibrationEnd: calibrate, wholeContracts: whole },
        });
      }}
    >
      <Select
        label="Rule"
        size="sm"
        allowDeselect={false}
        value={rule}
        onChange={(value) => setRule((value as "rolling" | "volatility") || "rolling")}
        data={[
          { value: "rolling", label: "Pause after losses" },
          { value: "volatility", label: "Volatility-scaled size" },
        ]}
      />
      {rule === "rolling" && (
        <NumberInput label="Resume after (trading days)" size="sm" min={1} max={365} value={resume} onChange={(value) => setResume(Number(value))} />
      )}
      <TextInput label="Calibrate on data up to" size="sm" type="date" value={calibrate} onChange={(event) => setCalibrate(event.currentTarget.value)} />
      <Checkbox label="Round down to whole contracts" checked={whole} onChange={(event) => setWhole(event.currentTarget.checked)} />
      <div>
        <Button type="submit" size="sm">Run replay</Button>
      </div>
      <Text size="xs" c="dimmed">
        Switches accounting to closed trades while on. Loss-clustering check, manual pause log and portfolio limits
        appear with the results.
      </Text>
    </form>
  );
}
