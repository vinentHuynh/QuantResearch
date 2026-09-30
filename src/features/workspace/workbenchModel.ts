import type {
  Dataset,
  Metrics,
  Run,
  RunSummary,
  Strategy,
} from "../../../shared/ts/workbenchModels.ts";
import type { EvaluationView, RegimeView } from "../evaluations/ResearchPage";
import type { Library } from "../strategies/StrategyLibrary";
import type { NewRunInput } from "../new-run/model";
import type { WatchlistEntry } from "../watchlist/model";

export type SavedView = {
  id: string;
  name: string;
  filter: string;
  stage: string;
  status: string;
};

export type WorkbenchState = {
  library?: Library;
  evaluations?: EvaluationView[];
  regimes?: RegimeView[];
  strategies: Strategy[];
  errors: { file?: string; error: string }[];
  datasets: Dataset[];
  runs: RunSummary[];
  watchlist: WatchlistEntry[];
  presets: { id: string; name: string; input: NewRunInput }[];
  views: SavedView[];
  experiments: { id: string; attempted_variants: number; hypothesis: string }[];
  import: { status: string; log: string; error?: string };
  limits: { concurrency: number; maxBatch: number };
};

export type RunComparison = {
  mode: string;
  start?: string;
  end?: string;
  boundary?: string;
  runs?: Run[];
  rows?: { id: string; metrics: Metrics; baseline_equity: number }[];
};

export type WarmupCheck = {
  symbol: string;
  timeframe: string;
  parameters: Record<string, unknown>;
  status: string;
  required_bars: number;
  available_bars: number;
  warning: string | null;
};

export type DeletionPreview = {
  ids: string[];
  token: string;
  counts: Record<string, number>;
  explanation: string;
};

export const formatPercent = (value: number | null | undefined) =>
  value == null ? "—" : `${(value * 100).toFixed(2)}%`;

export const formatNumber = (value: number | null | undefined) =>
  value == null
    ? "—"
    : value.toLocaleString(undefined, { maximumFractionDigits: 2 });

export const shortId = (value: string) => value.slice(0, 8);

export const statusTone = (status: string) =>
  status === "Succeeded"
    ? "teal"
    : ["Failed", "Interrupted", "Error"].includes(status)
      ? "red"
      : ["Running", "Queued"].includes(status)
        ? "blue"
        : "gray";

export const sessionOptions = [
  { value: "new-york-rth", label: "New York RTH" },
  { value: "full-trading-day", label: "Full Globex day" },
  { value: "london", label: "London" },
  { value: "asia", label: "Tokyo" },
];
