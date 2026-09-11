import { configureStore, createAsyncThunk, createSlice, type PayloadAction } from '@reduxjs/toolkit';
import { useDispatch, useSelector, type TypedUseSelectorHook } from 'react-redux';

export type View = 'overview' | 'health' | 'risk' | 'decisions' | 'lab' | 'registry' | 'strategies' | 'research' | 'runner' | 'data';

interface DashboardState {
  view: View;
  selectedStrategy: string | null;
}

const initialState: DashboardState = {
  view: 'overview',
  selectedStrategy: null,
};

const dashboardSlice = createSlice({
  name: 'dashboard',
  initialState,
  reducers: {
    navigate: (state, action: PayloadAction<View>) => { state.view = action.payload; },
    openStrategy: (state, action: PayloadAction<string>) => {
      state.selectedStrategy = action.payload;
      state.view = 'strategies';
    },
  },
});

export const { navigate, openStrategy } = dashboardSlice.actions;

export interface RunnerParameter {
  key: string;
  label: string;
  kind: 'string' | 'number' | 'integer' | 'boolean' | 'date' | 'time' | 'select' | 'multiselect';
  default: unknown;
  help: string;
  choices: string[];
  minimum: number | null;
  maximum: number | null;
  required: boolean;
}

export interface RunnerStrategy {
  id: string; name: string; description: string; kind: 'strategy'; charts: string[];
  timeframes: string[]; default_timeframe: string; legacy_ids: string[]; legacy_sources: string[];
  sessions: RunnerSession[]; default_session: string | null;
  minimum_charts: number; maximum_charts: number; default_charts: string[];
  parameters: RunnerParameter[];
}
export interface RunnerSession { id: string; name: string; timezone: string; open_time: string; close_time: string; calendar: string; crosses_midnight: boolean; trading_date_offset_days: number }
export interface ParityComparison { passed: boolean; rows: number; mismatches: number; max_absolute_error: number; tolerance: number }
export interface ParityEvidence { legacy_id: string; catalog_id: string; passed: boolean; coverage: 'signal' | 'signal_and_return' | 'full'; fixture: { id: string; sha256: string; rows: number }; comparisons: Record<string, ParityComparison>; full_parity_blockers: string[] }
export interface MigrationCandidate { id: string; name: string; family: string; script: string; source: string; reason: string; catalog_id?: string | null; catalog_name?: string | null; status?: 'canonical_pending_parity' | 'canonical_partial_parity' | 'canonical_parity_verified' | 'compatibility_adapter' | 'unmapped'; parity_evidence?: ParityEvidence | null }
export interface WorkflowSummary { id: string; name: string; script: string; description: string }
export interface ScriptInventoryItem { path: string; language: string; role: string }
export interface CatalogAudit { counts: { runner_ready: number; migration_candidates: number; research_studies: number; data_utilities: number; other_support_scripts: number; python_scripts: number; pine_scripts: number; ninjatrader_scripts: number; all_scripts: number; canonical_pending_parity: number; canonical_partial_parity: number; canonical_parity_verified: number; compatibility_adapters: number; unmapped_strategies: number }; migration_candidates: MigrationCandidate[]; specific_strategies: MigrationCandidate[]; script_inventory: ScriptInventoryItem[]; script_role_counts: Record<string, number>; research_studies: WorkflowSummary[]; data_utilities: WorkflowSummary[] }
export interface ChartDataset { id: string; symbol: string; name: string; tick_size: number; point_value: number; timezone: string; source: string; available: boolean; fingerprint: string | null; rows: number | null; first_bar: string | null; last_bar: string | null; timeframes: string[] }
export interface Artifact { name: string; kind: 'image' | 'table' | 'json' | 'html' | 'text' | 'file'; size: number; url: string }
export interface ValidationCheck { code: string; state: 'pass' | 'watch' | 'fail'; message: string; evidence: Record<string, unknown> }
export interface ResearchCheck { code: string; name: string; state: 'pass' | 'watch' | 'fail' | 'unknown'; observed: string; requirement: string; rationale: string; response: string }
export interface PerformanceSection { name: string; trades: number | null; active_sessions: number | null; orders: number | null; pnl_observations: number | null; pnl_frequency: string | null; net_pnl: number | null; profit_factor: number | null; sharpe: number | null; win_rate: number | null; max_drawdown: number | null }
export interface AutomatedAnalysis { engine_version: string; status: 'blocked' | 'negative_evidence' | 'smoke_test' | 'provisional' | 'incomplete'; headline: string; next_action: string; research_status: 'not_reviewed'; chart_id: string | null; sections: PerformanceSection[]; checks: ResearchCheck[] }
export interface AnalysisRun {
  id: string;
  strategy_id: string;
  strategy_name: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  parameters: Record<string, unknown>;
  output_dir: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  return_code: number | null;
  log?: string;
  artifacts: Artifact[];
  summary: Record<string, unknown> | null;
  validation_status?: 'pending' | 'data_validated' | 'rejected';
  validation_checks?: ValidationCheck[];
  research_status?: 'not_reviewed';
  automated_analysis?: AutomatedAnalysis | null;
}

export type Eligibility = 'Qualified' | 'Provisional' | 'Rejected' | 'Retired';
export type Health = 'Normal' | 'Watch' | 'Breached' | 'Unknown';
export type AllocationState = 'Base' | 'Reduced' | 'Paused' | 'No current proposal';
export interface PortfolioStrategy {
  id: string; strategy_id: string; name: string; version: string; eligibility: Eligibility;
  eligibility_as_of: string; evidence_strength: string; eligibility_reason_codes: string[];
  health: Health; reason_codes: string[]; allocation_state: AllocationState; allocation_reason_codes: string[];
  assessment_time: string; current_exposure: number; proposed_exposure: number | null;
  mtd_return: number | null; trailing_returns: Record<string, number | null>;
  recent_completed_months: { month: string; return: number }[]; current_drawdown: number | null;
  max_drawdown: number | null; drawdown_duration_observations: number | null;
  realized_volatility: number | null; risk_contribution: number | null; days_observed: number;
  last_event_time: string | null; data_freshness_days: number | null; next_review_time: string | null;
  family: string | null; asset_class: string | null; shared_exposure_group: string | null;
  limitations: string[]; acceptance_profile: Record<string, unknown> | null; reviewer: string | null;
  equity_curve: { time: string; equity: number; drawdown: number }[];
  reference_equity_curve: { time: string; equity: number; drawdown: number }[];
  history_coverage: { live: number; paper: number; reference: number; backtest: number };
  live_reference_gap: number | null;
  feature_availability: { current_performance: boolean; reference_performance: boolean; execution: boolean; positions: boolean; daily_risk: boolean };
  execution_diagnostics: { orders_observed: number; filled_orders: number; rejected_orders: number; fill_rate: number | null; average_slippage: number | null; fees: number | null; average_execution_delay_seconds: number | null };
  position_diagnostics: { event_time: string | null; gross_exposure: number | null; net_exposure: number | null; margin: number | null; liquidity_usage: number | null };
}
export interface PortfolioSnapshot {
  as_of: string; calculation_version: string; configuration_complete: boolean; missing_configuration: string[];
  settings: Record<string, unknown> & { policy_version?: string; policy_state?: string; version?: number };
  strategies: PortfolioStrategy[];
  portfolio: { actual_gross_exposure: number; proposed_gross_exposure: number | null; portfolio_volatility: number | null;
    unallocated_capital: number | null; critical_events: number; correlation_labels: string[];
    correlation_matrix: (number | null)[][]; covariance_matrix: (number | null)[][]; risk_contributions: (number | null)[];
    actual_net_exposure: number; proposed_net_exposure: number; actual_margin: number; proposed_margin: number; stress_loss_10pct: number;
    review_due: boolean; review_reason: string; last_decision_cutoff: string | null; monitoring_frequency: string };
}
export interface PortfolioDecision { id: string; created_at: string; cutoff: string; effective_time: string; snapshot_hash: string;
  policy_version: string; calculation_version: string; configuration_complete: boolean; missing_configuration: string[];
  proposals: Pick<PortfolioStrategy, 'id' | 'name' | 'version' | 'eligibility' | 'health' | 'current_exposure' | 'proposed_exposure' | 'allocation_state' | 'allocation_reason_codes' | 'reason_codes'>[] }
export interface PortfolioAlert { id: string; strategy_version_id: string | null; code: string; severity: string; title: string; detail: string;
  state: 'Open' | 'Acknowledged' | 'Resolved'; first_seen: string; last_seen: string; acknowledged_at: string | null; resolution: { time: string; note: string | null } | null }
export interface PortfolioExperiment { id: string; created_at: string; name?: string; state: string; intended_mechanism?: string;
  result: { status: string; reason?: string; sample_size: number; warning?: string; comparators: { name: string; net_compound_return: number; annualized_volatility: number | null; sharpe: number | null; max_drawdown: number; observations: number }[] } }

async function apiJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export const fetchRunnerCatalog = createAsyncThunk('runner/catalog', () => apiJson<RunnerStrategy[]>('/api/strategies'));
export const fetchCatalogAudit = createAsyncThunk('runner/audit', () => apiJson<CatalogAudit>('/api/catalog-audit'));
export const fetchCharts = createAsyncThunk('runner/charts', () => apiJson<ChartDataset[]>('/api/charts'));
export const fetchRuns = createAsyncThunk('runner/list', () => apiJson<AnalysisRun[]>('/api/runs'));
export const fetchRun = createAsyncThunk('runner/get', (id: string) => apiJson<AnalysisRun>(`/api/runs/${id}`));
export const startRun = createAsyncThunk('runner/start', ({ strategyId, chartIds, timeframe, sessionId, parameters }: { strategyId: string; chartIds: string[]; timeframe: string; sessionId?: string; parameters: Record<string, unknown> }) => apiJson<AnalysisRun>('/api/runs', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ strategy_id: strategyId, chart_id: chartIds[0], chart_ids: chartIds, timeframe, session_id: sessionId, parameters }),
}));
export const fetchPortfolio = createAsyncThunk('portfolio/get', () => apiJson<PortfolioSnapshot>('/api/portfolio'));
export const fetchPortfolioDecisions = createAsyncThunk('portfolio/decisions', () => apiJson<PortfolioDecision[]>('/api/portfolio/decisions'));
export const fetchPortfolioAlerts = createAsyncThunk('portfolio/alerts', () => apiJson<PortfolioAlert[]>('/api/portfolio/alerts'));
export const fetchPortfolioExperiments = createAsyncThunk('portfolio/experiments', () => apiJson<PortfolioExperiment[]>('/api/portfolio/experiments'));
export const createPortfolioDecision = createAsyncThunk('portfolio/createDecision', () => apiJson<PortfolioDecision>('/api/portfolio/decisions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }));
export const savePortfolioSettings = createAsyncThunk('portfolio/settings', (changes: Record<string, unknown>) => apiJson<Record<string, unknown>>('/api/portfolio/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes) }));
export const importPortfolioObservations = createAsyncThunk('portfolio/import', (payload: { strategy_version_id: string; source: string; csv: string }) => apiJson<{ accepted: number; rejected: number; errors: { row: number; message: string }[] }>('/api/portfolio/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }));
export const runPortfolioExperiment = createAsyncThunk('portfolio/experiment', (payload: Record<string, unknown>) => apiJson<PortfolioExperiment>('/api/portfolio/experiments', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }));
export const actOnPortfolioAlert = createAsyncThunk('portfolio/alertAction', ({ id, action, note }: { id: string; action: 'acknowledge' | 'resolve'; note?: string }) => apiJson<PortfolioAlert>(`/api/portfolio/alerts/${id}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, note }) }));

interface RunnerState {
  catalog: RunnerStrategy[];
  catalogAudit: CatalogAudit | null;
  charts: ChartDataset[];
  runs: AnalysisRun[];
  activeRunId: string | null;
  loading: boolean;
  error: string | null;
}

const runnerSlice = createSlice({
  name: 'runner', initialState: { catalog: [], catalogAudit: null, charts: [], runs: [], activeRunId: null, loading: false, error: null } as RunnerState,
  reducers: { selectRun: (state, action: PayloadAction<string>) => { state.activeRunId = action.payload; state.error = null; } },
  extraReducers: builder => builder
    .addCase(fetchRunnerCatalog.fulfilled, (state, action) => { state.catalog = action.payload; })
    .addCase(fetchCatalogAudit.fulfilled, (state, action) => { state.catalogAudit = action.payload; })
    .addCase(fetchCharts.fulfilled, (state, action) => { state.charts = action.payload; })
    .addCase(fetchRuns.fulfilled, (state, action) => { state.runs = action.payload; if (!state.activeRunId && action.payload[0]) state.activeRunId = action.payload[0].id; })
    .addCase(startRun.pending, state => { state.loading = true; state.error = null; })
    .addCase(startRun.fulfilled, (state, action) => { state.loading = false; state.activeRunId = action.payload.id; state.runs.unshift(action.payload); })
    .addCase(startRun.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Unable to start the run'; })
    .addCase(fetchRun.fulfilled, (state, action) => { const index = state.runs.findIndex(run => run.id === action.payload.id); if (index >= 0) state.runs[index] = action.payload; else state.runs.unshift(action.payload); })
    .addCase(fetchRunnerCatalog.rejected, (state, action) => { state.error = action.error.message ?? 'Unable to load runner catalog'; })
    .addCase(fetchCatalogAudit.rejected, (state, action) => { state.error = action.error.message ?? 'Unable to audit strategy catalog'; })
    .addCase(fetchCharts.rejected, (state, action) => { state.error = action.error.message ?? 'Unable to load chart catalog'; })
    .addCase(fetchRuns.rejected, (state, action) => { state.error = action.error.message ?? 'Unable to load run history'; })
    .addCase(fetchRun.rejected, (state, action) => { state.error = action.error.message ?? 'Unable to refresh the run'; }),
});

interface PortfolioState { snapshot: PortfolioSnapshot | null; decisions: PortfolioDecision[]; alerts: PortfolioAlert[]; experiments: PortfolioExperiment[]; loading: boolean; error: string | null; notice: string | null }
const portfolioInitial: PortfolioState = { snapshot: null, decisions: [], alerts: [], experiments: [], loading: false, error: null, notice: null };
const portfolioSlice = createSlice({
  name: 'portfolio', initialState: portfolioInitial, reducers: { clearPortfolioNotice: state => { state.notice = null; state.error = null; } },
  extraReducers: builder => builder
    .addCase(fetchPortfolio.pending, state => { state.loading = true; })
    .addCase(fetchPortfolio.fulfilled, (state, action) => { state.snapshot = action.payload; state.loading = false; state.error = null; })
    .addCase(fetchPortfolio.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Unable to load portfolio'; })
    .addCase(fetchPortfolioDecisions.fulfilled, (state, action) => { state.decisions = action.payload; })
    .addCase(fetchPortfolioAlerts.fulfilled, (state, action) => { state.alerts = action.payload; })
    .addCase(fetchPortfolioExperiments.fulfilled, (state, action) => { state.experiments = action.payload; })
    .addCase(createPortfolioDecision.pending, state => { state.loading = true; state.error = null; })
    .addCase(createPortfolioDecision.fulfilled, (state, action) => { state.loading = false; state.decisions.unshift(action.payload); state.notice = `Decision ${action.payload.id} saved`; })
    .addCase(createPortfolioDecision.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Unable to create decision'; })
    .addCase(savePortfolioSettings.fulfilled, state => { state.notice = 'Configuration saved as a new version'; })
    .addCase(savePortfolioSettings.rejected, (state, action) => { state.error = action.error.message ?? 'Unable to save configuration'; })
    .addCase(importPortfolioObservations.fulfilled, (state, action) => { state.notice = `Imported ${action.payload.accepted} rows; ${action.payload.rejected} rejected`; })
    .addCase(importPortfolioObservations.rejected, (state, action) => { state.error = action.error.message ?? 'Unable to import observations'; })
    .addCase(runPortfolioExperiment.fulfilled, (state, action) => { state.experiments.unshift(action.payload); state.notice = `Experiment ${action.payload.id} saved`; })
    .addCase(runPortfolioExperiment.rejected, (state, action) => { state.error = action.error.message ?? 'Unable to run experiment'; })
    .addCase(actOnPortfolioAlert.fulfilled, (state, action) => { const index = state.alerts.findIndex(item => item.id === action.payload.id); if (index >= 0) state.alerts[index] = action.payload; }),
});

export const { selectRun } = runnerSlice.actions;
export const { clearPortfolioNotice } = portfolioSlice.actions;
export const store = configureStore({ reducer: { dashboard: dashboardSlice.reducer, runner: runnerSlice.reducer, portfolio: portfolioSlice.reducer } });
export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
export const useAppDispatch = () => useDispatch<AppDispatch>();
export const useAppSelector: TypedUseSelectorHook<RootState> = useSelector;
