import { configureStore, createAsyncThunk, createSlice, type PayloadAction } from '@reduxjs/toolkit';
import { useDispatch, useSelector, type TypedUseSelectorHook } from 'react-redux';

export type View = 'portfolio' | 'detail' | 'risk' | 'research' | 'runner' | 'data' | 'proposal';
type Filter = 'All strategies' | 'Actionable' | 'Eligible' | 'Watch / Breach';

interface DashboardState {
  view: View;
  selectedStrategy: string;
  expandedStrategy: string | null;
  filter: Filter;
  importKind: 'Live' | 'Backtest' | 'Paper';
  lastRefresh: string;
}

const initialState: DashboardState = {
  view: 'portfolio',
  selectedStrategy: 'mnq-on',
  expandedStrategy: null,
  filter: 'All strategies',
  importKind: 'Live',
  lastRefresh: '06 Sep 08:14',
};

const dashboardSlice = createSlice({
  name: 'dashboard',
  initialState,
  reducers: {
    navigate: (state, action: PayloadAction<View>) => { state.view = action.payload; },
    openStrategy: (state, action: PayloadAction<string>) => {
      state.selectedStrategy = action.payload;
      state.view = 'detail';
    },
    toggleStrategy: (state, action: PayloadAction<string>) => {
      state.expandedStrategy = state.expandedStrategy === action.payload ? null : action.payload;
    },
    setFilter: (state, action: PayloadAction<Filter>) => { state.filter = action.payload; },
    setImportKind: (state, action: PayloadAction<DashboardState['importKind']>) => { state.importKind = action.payload; },
    refreshData: (state) => {
      state.lastRefresh = new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date());
    },
  },
});

export const { navigate, openStrategy, toggleStrategy, setFilter, setImportKind, refreshData } = dashboardSlice.actions;

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

export interface RunnerStrategy { id: string; name: string; description: string; charts: string[]; parameters: RunnerParameter[] }
export interface ChartDataset { id: string; symbol: string; name: string; tick_size: number; point_value: number; timezone: string; source: string; available: boolean; fingerprint: string | null; rows: number | null; first_bar: string | null; last_bar: string | null; timeframes: string[] }
export interface Artifact { name: string; kind: 'image' | 'table' | 'json' | 'html' | 'text' | 'file'; size: number; url: string }
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
}

async function apiJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export const fetchRunnerCatalog = createAsyncThunk('runner/catalog', () => apiJson<RunnerStrategy[]>('/api/strategies'));
export const fetchCharts = createAsyncThunk('runner/charts', () => apiJson<ChartDataset[]>('/api/charts'));
export const fetchRuns = createAsyncThunk('runner/list', () => apiJson<AnalysisRun[]>('/api/runs'));
export const fetchRun = createAsyncThunk('runner/get', (id: string) => apiJson<AnalysisRun>(`/api/runs/${id}`));
export const startRun = createAsyncThunk('runner/start', ({ strategyId, chartId, parameters }: { strategyId: string; chartId: string; parameters: Record<string, unknown> }) => apiJson<AnalysisRun>('/api/runs', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ strategy_id: strategyId, chart_id: chartId, parameters }),
}));

interface RunnerState {
  catalog: RunnerStrategy[];
  charts: ChartDataset[];
  runs: AnalysisRun[];
  activeRunId: string | null;
  loading: boolean;
  error: string | null;
}

const runnerSlice = createSlice({
  name: 'runner', initialState: { catalog: [], charts: [], runs: [], activeRunId: null, loading: false, error: null } as RunnerState,
  reducers: { selectRun: (state, action: PayloadAction<string>) => { state.activeRunId = action.payload; state.error = null; } },
  extraReducers: builder => builder
    .addCase(fetchRunnerCatalog.fulfilled, (state, action) => { state.catalog = action.payload; })
    .addCase(fetchCharts.fulfilled, (state, action) => { state.charts = action.payload; })
    .addCase(fetchRuns.fulfilled, (state, action) => { state.runs = action.payload; if (!state.activeRunId && action.payload[0]) state.activeRunId = action.payload[0].id; })
    .addCase(startRun.pending, state => { state.loading = true; state.error = null; })
    .addCase(startRun.fulfilled, (state, action) => { state.loading = false; state.activeRunId = action.payload.id; state.runs.unshift(action.payload); })
    .addCase(startRun.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Unable to start the run'; })
    .addCase(fetchRun.fulfilled, (state, action) => { const index = state.runs.findIndex(run => run.id === action.payload.id); if (index >= 0) state.runs[index] = action.payload; else state.runs.unshift(action.payload); })
    .addCase(fetchRunnerCatalog.rejected, (state, action) => { state.error = action.error.message ?? 'Unable to load runner catalog'; })
    .addCase(fetchCharts.rejected, (state, action) => { state.error = action.error.message ?? 'Unable to load chart catalog'; })
    .addCase(fetchRuns.rejected, (state, action) => { state.error = action.error.message ?? 'Unable to load run history'; })
    .addCase(fetchRun.rejected, (state, action) => { state.error = action.error.message ?? 'Unable to refresh the run'; }),
});

export const { selectRun } = runnerSlice.actions;
export const store = configureStore({ reducer: { dashboard: dashboardSlice.reducer, runner: runnerSlice.reducer } });
export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
export const useAppDispatch = () => useDispatch<AppDispatch>();
export const useAppSelector: TypedUseSelectorHook<RootState> = useSelector;
