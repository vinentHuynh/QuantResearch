export type RecordValue = Record<string, unknown>;

export type Parameter = {
  type: string;
  default: unknown;
  minimum?: number;
  maximum?: number;
  choices?: string[];
  required_when?: RecordValue;
};

export type Strategy = {
  schema_version?: number;
  id: string;
  name: string;
  file: string;
  file_hash: string;
  /** Current fingerprint of the adapter, declared dependencies, and execution runtime. */
  execution_source_hash?: string;
  source_files?: string[];
  timeframes: string[];
  parameters: Record<string, Parameter>;
  execution_model?: string;
  required_session?: string;
  warmup_bars?: { parameter: string; multiplier?: number; offset?: number };
  default_warmup_days?: number;
};

export type Dataset = {
  schema_version?: number;
  id: string;
  symbol: string;
  first: string;
  last: string;
  path: string;
  checksum: string;
  registered_at: string;
  currency: string;
  [key: string]: unknown;
};

export type Run = {
  id: string;
  status: string;
  created_at: string;
  input: Input;
  started_at?: string;
  ended_at?: string;
  error?: string;
  result?: RecordValue;
  notes?: string;
  tags?: string;
  watch_id?: string;
};

export type Input = {
  protocol: number;
  id: string;
  experiment_id: string;
  strategy: Strategy;
  dataset: Dataset;
  parameters: RecordValue;
  start: string;
  end: string;
  timeframe: string;
  session: string;
  stage: string;
  capital: number;
  fee: number;
  slippage: number;
  warmup_days: number;
  timeout: number;
  source_dir: string;
  source_hash: string;
  source_snapshot?: string;
  execution_source_hash?: string;
  snapshot_hash?: string;
  app_build_hash?: string;
  configuration_id: string;
  development_end: string;
  selection_time: string;
  hypothesis: string;
  retry_of?: string;
  criteria: string;
  delay_bars?: number;
  research?: {
    evaluation_id: string;
    fold: number;
    role: string;
    candidate: number;
    scenario: string;
  };
};
