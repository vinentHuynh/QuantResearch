export type NewRunInput = {
  delay_bars?: number;
  dataset_ids?: string[];
  timeframes?: string[];
  strategy_id: string;
  dataset_id: string;
  start: string;
  end: string;
  timeframe: string;
  session: string;
  stage: string;
  capital: number;
  fee: number;
  slippage: number;
  timeout: number;
  warmup_days: number;
  development_end: string;
  hypothesis: string;
  criteria: string;
  parameters: Record<string, unknown>;
  sweep: Record<string, unknown[]>;
};

export const initialNewRunInput: NewRunInput = {
  strategy_id: "",
  dataset_id: "",
  start: "2026-01-01",
  end: "2026-09-03",
  timeframe: "1h",
  session: "new-york-rth",
  stage: "Exploratory",
  capital: 100000,
  fee: 1.25,
  slippage: 1,
  timeout: 300,
  warmup_days: 60,
  development_end: "",
  hypothesis: "",
  criteria: "",
  parameters: {},
  sweep: {},
};

export const NEW_RUN_DRAFT_KEY = "quant-workbench-draft-v2";

export const newRunSteps = [
  "Script & dataset",
  "Parameters",
  "Assumptions & record",
  "Preview & launch",
] as const;

export function readNewRunDraft() {
  try {
    const value = JSON.parse(localStorage.getItem(NEW_RUN_DRAFT_KEY) || "null");
    if (!value || typeof value !== "object") return null;
    return {
      input:
        value.input && typeof value.input === "object"
          ? (value.input as NewRunInput)
          : initialNewRunInput,
      sweepText: typeof value.sweepText === "string" ? value.sweepText : "{}",
      step: Number.isInteger(value.step)
        ? Math.max(0, Math.min(3, value.step))
        : 0,
    };
  } catch {
    return null;
  }
}

export function parseSweep(text: string): Record<string, unknown[]> | null {
  try {
    const value = JSON.parse(text);
    return value && typeof value === "object" && !Array.isArray(value)
      ? value
      : null;
  } catch {
    return null;
  }
}
