/**
 * Transport models shared by the workbench UI and pure evidence calculations.
 *
 * These describe the protocol-v1 fields the current UI consumes. Protocol-v2
 * additions are optional so old saved records and new responses remain
 * structurally compatible during the migration.
 */
export type StrategyField = {
  type: string;
  default: unknown;
  minimum?: number;
  maximum?: number;
  choices?: string[];
  description?: string;
};

export type Strategy = {
  id: string;
  name: string;
  description: string;
  version: string;
  file: string;
  file_hash: string;
  execution_source_hash?: string;
  timeframes: string[];
  parameters: Record<string, StrategyField>;
  migration_scope?: string;
  default_warmup_days?: number;
  default_session?: string;
  execution_model?: string;
  source_files?: string[];
  source_id?: string;
};

export type Dataset = {
  id: string;
  symbol: string;
  source: string;
  rows: number;
  first: string;
  last: string;
  registered_at: string;
  archive: string;
  checksum: string;
  tick_size: number;
  point_value: number;
  warnings: string[];
  quality: Record<string, number>;
};

export type Metrics = {
  net_return: number;
  net_pnl: number;
  max_drawdown: number;
  sharpe: number | null;
  cagr: number | null;
  volatility: number | null;
  trades: number | null;
  observations: number;
  costs: number;
  underwater_bars: number;
  current_underwater_bars: number;
  monthly: { month: string; return: number }[];
  basis: string;
  undefined_reason: string;
  first: string;
  last: string;
};

export type RunInput = {
  /** Absent and protocol 1 are legacy records; protocol 2 uses execution hashes. */
  protocol?: number;
  delay_bars?: number;
  dataset_ids?: string[];
  timeframes?: string[];
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
  research?: {
    evaluation_id: string;
    fold: number;
    role: string;
    candidate: number;
    scenario: string;
  };
  strategy: Strategy;
  dataset: Dataset;
  source_hash: string;
  configuration_id: string;
  experiment_id: string;
  selection_time: string;
  retry_of?: string;
  execution_source_hash?: string;
  snapshot_hash?: string;
  app_build_hash?: string;
};

export type RunSummary = {
  id: string;
  status: string;
  created_at: string;
  started_at?: string;
  ended_at?: string;
  input: RunInput;
  error?: string;
  notes?: string;
  tags?: string;
  watch_id?: string;
  log?: string;
  result?: {
    metrics: Metrics;
    warnings: string[];
    artifacts: { name: string }[];
  };
};

export type Run = Omit<RunSummary, "result"> & {
  result?: NonNullable<RunSummary["result"]> & {
    equity_preview: { timestamp: string; equity: number; drawdown?: number }[];
    trade_preview: Record<string, unknown>[];
  };
};

export type EvaluationMetrics = {
  net_return: number;
  max_drawdown: number;
  trades: number;
  costs: number;
  sharpe: number | null;
  net_pnl: number;
};

export type EvaluationFold = {
  index: number;
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  training: string[];
  tests: string[];
  selection?: {
    run_id: string;
    candidate: number;
    score: number;
    selected_at: string;
    permitted_through: string;
    ranked: {
      run_id: string;
      candidate: number;
      score: number | null;
      eligible: boolean;
    }[];
  };
};

export type EvaluationView = {
  scenarios?: string[];
  note?: string;
  id: string;
  name: string;
  status: string;
  created_at: string;
  folds: EvaluationFold[];
  jobs: number;
  metric: string;
  source_hash: string;
  inspected_overlap: string[];
  error?: string;
  outcome?: string;
  hypothesis?: string;
  min_trades?: number;
  min_test_trades?: number;
  min_return?: number;
  max_drawdown?: number;
  stress_multiple?: number;
  delay_bars?: number;
  candidates: { parameters: Record<string, unknown> }[];
  result?: {
    scenarios: {
      name: string;
      metrics: EvaluationMetrics;
      outcome: string;
      equity_preview: { timestamp: string; equity: number }[];
    }[];
    boundary: string;
    warnings: string[];
  };
};

export type RegimeView = {
  id: string;
  evaluation_id: string;
  status: string;
  feature: string;
  window: number;
  error?: string;
  result?: {
    source: string;
    formula: string;
    states: {
      state: string;
      observations: number;
      episodes: number;
      net_pnl: number;
      costs: number;
      invested_bar_fraction: number;
      entry_count: number;
      mean_episode_pnl: number;
      mean_episode_pnl_interval_95: number[] | null;
      evidence: string;
    }[];
    thresholds: {
      fold: number;
      threshold: number;
      training_observations: number;
      calibrated_through: string;
    }[];
    warnings: string[];
  };
};
