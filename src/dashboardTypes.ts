export type DashboardStatus =
  | "Research candidate"
  | "Conditional"
  | "Needs review"
  | "Benchmark"
  | "In progress"
  | "Incomplete"
  | "Not evaluated";
export type TradeStats = {
  trades: number;
  wins: number;
  losses: number;
  breakeven: number;
  net_pnl: number;
  win_rate: number | null;
  average_win: number | null;
  average_loss: number | null;
  expectancy: number | null;
  payoff_ratio: number | null;
  profit_factor: number | null;
};
export type DashboardScenario = {
  name: string;
  outcome: string;
  metrics: {
    net_pnl: number;
    net_return: number;
    max_drawdown: number;
    trades: number;
    costs: number;
    sharpe: number | null;
  };
  equity_preview: { timestamp: string; equity: number }[];
};
export type DashboardRegime = {
  id: string;
  feature: string;
  window: number;
  states: {
    state: string;
    net_pnl: number;
    observations: number;
    episodes: number;
    invested_bar_fraction: number;
    mean_episode_pnl_interval_95: number[] | null;
  }[];
};
export type DashboardRow = {
  strategy_id: string;
  name: string;
  symbol: string;
  status: DashboardStatus;
  reasons: string[];
  evaluation_id?: string;
  evaluation_name?: string;
  evaluated_at?: string;
  start?: string;
  end?: string;
  timeframe?: string;
  session?: string;
  capital?: number;
  fee?: number;
  slippage?: number;
  source_hash?: string;
  target_rr: number | null;
  scenarios: DashboardScenario[];
  trades: TradeStats | null;
  trade_error?: string;
  baseline_run_ids: string[];
  regimes: DashboardRegime[];
  prior_flags: { id: string; end: string; kind: "run" | "evaluation" }[];
  newer_data_through?: string;
  parameters: Record<string, unknown>[];
};
export type DashboardData = {
  generated_at: string;
  symbols: string[];
  symbol: string;
  rows: DashboardRow[];
};
