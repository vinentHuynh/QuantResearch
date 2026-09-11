import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  Alert, Badge, Box, Button, Code, Container, Group, Loader, MultiSelect,
  NumberInput, Paper, ScrollArea, Select, SimpleGrid, Stack, Switch, Table,
  Text, TextInput, ThemeIcon, Title,
} from '@mantine/core';
import {
  IconChartBar, IconCheck, IconDatabase, IconDownload,
  IconRefresh, IconShieldCheck, IconTrendingUp,
} from '@tabler/icons-react';
import {
  fetchCatalogAudit, fetchCharts, fetchRun, fetchRunnerCatalog, fetchRuns, navigate, openStrategy,
  fetchPortfolio, fetchPortfolioAlerts, fetchPortfolioDecisions, fetchPortfolioExperiments,
  selectRun, startRun, useAppDispatch, useAppSelector, type AnalysisRun,
  type AutomatedAnalysis, type CatalogAudit, type MigrationCandidate, type RunnerParameter, type RunnerStrategy, type View,
} from './store';
import { DecisionsPage, HealthPage, LabPage, PortfolioOverview, RegistryPage, RiskPage } from './portfolio';

function Panel({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <Paper withBorder className={`panel ${className}`}>{children}</Paper>;
}

function StatusBadge({ value, tone = 'neutral' }: { value: string; tone?: 'pass' | 'watch' | 'fail' | 'neutral' }) {
  const color = tone === 'pass' ? 'teal' : tone === 'watch' ? 'yellow' : tone === 'fail' ? 'red' : 'gray';
  return <Badge color={color} variant={tone === 'fail' ? 'filled' : 'light'} radius="xs" size="sm" className="status">{value}</Badge>;
}

function RunStatus({ status }: { status: AnalysisRun['status'] }) {
  const tone = status === 'completed' ? 'pass' : status === 'failed' ? 'fail' : 'watch';
  return <StatusBadge value={status.toUpperCase()} tone={tone}/>;
}

function ValidationStatus({ status }: { status: AnalysisRun['validation_status'] }) {
  const effective = status ?? 'pending';
  const tone = effective === 'data_validated' ? 'pass' : effective === 'rejected' ? 'fail' : 'watch';
  return <StatusBadge value={effective === 'data_validated' ? 'DATA VALIDATED' : effective.toUpperCase()} tone={tone}/>;
}

function AnalysisStatus({ status }: { status: AutomatedAnalysis['status'] }) {
  const tone = ['blocked', 'negative_evidence'].includes(status) ? 'fail' : ['smoke_test', 'provisional'].includes(status) ? 'watch' : 'neutral';
  return <StatusBadge value={status.replaceAll('_', ' ').toUpperCase()} tone={tone}/>;
}

const tabs: { id: View; label: string }[] = [
  { id: 'overview', label: 'Portfolio' }, { id: 'health', label: 'Health' }, { id: 'risk', label: 'Risk' },
  { id: 'decisions', label: 'Decisions' }, { id: 'lab', label: 'Allocation lab' }, { id: 'registry', label: 'Registry' },
  { id: 'strategies', label: 'Backtests' }, { id: 'research', label: 'Run history' },
  { id: 'runner', label: 'Run analysis' }, { id: 'data', label: 'Chart data' },
];

function Header() {
  const dispatch = useAppDispatch();
  const view = useAppSelector(state => state.dashboard.view);
  const { catalog, charts, runs } = useAppSelector(state => state.runner);
  return <><Box className="topbar"><Container size={1420} className="topbarInner"><Group gap="sm"><ThemeIcon color="teal" variant="white" size={30}><IconShieldCheck size={19}/></ThemeIcon><Text className="brand">Strategy Research <span>Dashboard</span></Text></Group><Group gap="xl" className="metadata"><Box><Text>Strategies</Text><strong>{catalog.length}</strong></Box><Box><Text>Databento charts</Text><strong>{charts.filter(chart => chart.available).length}</strong></Box><Box><Text>Stored runs</Text><strong>{runs.length}</strong></Box></Group></Container></Box><Box className="navWrap"><Container size={1420}><Group gap={30} wrap="nowrap" className="navTabs">{tabs.map(tab => <button key={tab.id} className={view === tab.id ? 'active' : ''} onClick={() => dispatch(navigate(tab.id))}>{tab.label}</button>)}</Group></Container></Box></>;
}

function formatDate(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : '—';
}

function chartForRun(run: AnalysisRun) {
  if (Array.isArray(run.parameters.chart_ids)) return run.parameters.chart_ids.join('/');
  return typeof run.parameters.chart_id === 'string' ? run.parameters.chart_id : 'Legacy';
}

function timeframeForRun(run: AnalysisRun) {
  return typeof run.parameters.timeframe === 'string' ? run.parameters.timeframe : 'Legacy';
}

function sessionForRun(run: AnalysisRun) {
  return typeof run.parameters.session_id === 'string' ? run.parameters.session_id : '—';
}

function sizingForRun(run: AnalysisRun) {
  const value = run.parameters.quantity_mode;
  if (value === 'whole_contracts') return 'Whole contracts';
  if (value === 'fractional') return 'Fractional research';
  const sizing = run.summary?.sizing;
  if (typeof sizing === 'object' && sizing && 'executable_quantity' in sizing) {
    return (sizing as { executable_quantity?: unknown }).executable_quantity ? 'Whole contracts' : 'Fractional research';
  }
  return '—';
}

function RunTable({ runs, limit, onInspect }: { runs: AnalysisRun[]; limit?: number; onInspect?: (run: AnalysisRun) => void }) {
  const visible = limit ? runs.slice(0, limit) : runs;
  if (!visible.length) return <Text c="dimmed" size="sm">No analysis runs have been recorded yet.</Text>;
  return <ScrollArea><Table miw={1080} verticalSpacing="sm" highlightOnHover><Table.Thead><Table.Tr><Table.Th>Created</Table.Th><Table.Th>Strategy</Table.Th><Table.Th>Chart</Table.Th><Table.Th>Timeframe</Table.Th><Table.Th>Session</Table.Th><Table.Th>Sizing</Table.Th><Table.Th>Run</Table.Th><Table.Th>Validation</Table.Th><Table.Th>Artifacts</Table.Th>{onInspect && <Table.Th/>}</Table.Tr></Table.Thead><Table.Tbody>{visible.map(run => <Table.Tr key={run.id}><Table.Td><Text size="xs" className="mono">{formatDate(run.created_at)}</Text></Table.Td><Table.Td><Text size="sm" fw={600}>{run.strategy_name}</Text><Text size="xs" c="dimmed" className="mono">{run.id}</Text></Table.Td><Table.Td><Badge variant="outline" color="gray">{chartForRun(run)}</Badge></Table.Td><Table.Td><Badge variant="light" color="blue">{timeframeForRun(run)}</Badge></Table.Td><Table.Td><Badge variant="light" color="violet">{sessionForRun(run)}</Badge></Table.Td><Table.Td><Text size="xs">{sizingForRun(run)}</Text></Table.Td><Table.Td><RunStatus status={run.status}/></Table.Td><Table.Td><ValidationStatus status={run.validation_status}/></Table.Td><Table.Td><Text size="xs">{run.artifacts.length}</Text></Table.Td>{onInspect && <Table.Td><Button variant="subtle" size="compact-xs" onClick={() => onInspect(run)}>Inspect</Button></Table.Td>}</Table.Tr>)}</Table.Tbody></Table></ScrollArea>;
}

function PageHeading({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <Group justify="space-between" align="flex-end" mb="lg"><Box><Title order={2}>{title}</Title><Text c="dimmed" size="sm">{description}</Text></Box>{action}</Group>;
}

function strategyRuns(strategy: RunnerStrategy, runs: AnalysisRun[]) {
  return runs.filter(run => run.strategy_id === strategy.id || strategy.legacy_ids.includes(run.strategy_id));
}

function SpecificStrategyInventory({ audit }: { audit: CatalogAudit }) {
  const status = (candidate: MigrationCandidate) => {
    if (candidate.status === 'canonical_parity_verified') return <StatusBadge value="CANONICAL · FULL PARITY" tone="pass"/>;
    if (candidate.status === 'canonical_partial_parity') return <StatusBadge value={`CANONICAL · ${candidate.parity_evidence?.coverage.replaceAll('_', ' ').toUpperCase() ?? 'PARTIAL'} PARITY`} tone="watch"/>;
    if (candidate.status === 'canonical_pending_parity') return <StatusBadge value="CANONICAL · PARITY PENDING" tone="watch"/>;
    if (candidate.status === 'compatibility_adapter') return <StatusBadge value="ADAPTER ONLY" tone="watch"/>;
    return <StatusBadge value="UNMAPPED" tone="fail"/>;
  };
  return <Panel className="inventoryPanel">
    <Group justify="space-between" mb="sm">
      <Box>
        <Text fw={600}>Specific strategy inventory</Text>
        <Text c="dimmed" size="xs">Each historical strategy remains visible even when several use one shared execution mechanism.</Text>
      </Box>
      <Group gap="xs">
        <StatusBadge value={`${audit.counts.all_scripts} SCRIPTS`} />
        <StatusBadge value={`${audit.counts.canonical_parity_verified} FULL PARITY`} tone="pass"/>
        <StatusBadge value={`${audit.counts.canonical_partial_parity} PARTIAL PARITY`} tone="watch"/>
        <StatusBadge value={`${audit.counts.canonical_pending_parity} PENDING`} tone="watch"/>
        <StatusBadge value={`${audit.counts.compatibility_adapters} ADAPTER ONLY`} tone="watch"/>
      </Group>
    </Group>
    <ScrollArea><Table miw={1060} verticalSpacing="sm">
      <Table.Thead><Table.Tr><Table.Th>Specific strategy</Table.Th><Table.Th>Family</Table.Th><Table.Th>Canonical catalog entry</Table.Th><Table.Th>Migration state</Table.Th><Table.Th>Source</Table.Th></Table.Tr></Table.Thead>
      <Table.Tbody>{audit.specific_strategies.map(candidate => <Table.Tr key={candidate.id}>
        <Table.Td><Text fw={600} size="sm">{candidate.name}</Text><Text c="dimmed" size="xs" className="mono">{candidate.id}</Text></Table.Td>
        <Table.Td><Badge variant="outline" color="gray">{candidate.family}</Badge></Table.Td>
        <Table.Td><Text size="sm">{candidate.catalog_name ?? '—'}</Text><Text c="dimmed" size="xs" className="mono">{candidate.catalog_id ?? ''}</Text></Table.Td>
        <Table.Td>{status(candidate)}{candidate.parity_evidence && <Text c="dimmed" size="xs" mt={4}>{Object.values(candidate.parity_evidence.comparisons).reduce((sum, item) => sum + item.mismatches, 0)} mismatches across {candidate.parity_evidence.fixture.rows} frozen rows</Text>}</Table.Td>
        <Table.Td><Text size="xs" className="mono">{candidate.script}</Text></Table.Td>
      </Table.Tr>)}</Table.Tbody>
    </Table></ScrollArea>
  </Panel>;
}

function StrategiesPage() {
  const dispatch = useAppDispatch();
  const selectedId = useAppSelector(state => state.dashboard.selectedStrategy);
  const { catalog, catalogAudit, runs } = useAppSelector(state => state.runner);
  const selected = catalog.find(strategy => strategy.id === selectedId) ?? catalog[0];
  const selectedRuns = selected ? strategyRuns(selected, runs) : [];
  const latestAnalysis = selectedRuns[0]?.automated_analysis;
  return <>
    <PageHeading title="Backtests" description="Each specific strategy stays visible; chart, timeframe, and session are execution inputs." action={<Button onClick={() => dispatch(navigate('runner'))}>New run</Button>}/>
    {!selected ? <Panel><Text c="dimmed">No strategies are registered.</Text></Panel> : <SimpleGrid cols={{ base: 1, lg: 3 }} spacing="lg" style={{ alignItems: 'start' }}>
      <Panel><Stack gap="xs">{catalog.map(strategy => {
        const history = strategyRuns(strategy, runs);
        const latest = history[0];
        return <button key={strategy.id} className={`strategyChoice ${strategy.id === selected.id ? 'active' : ''}`} onClick={() => dispatch(openStrategy(strategy.id))}>
          <Group justify="space-between" wrap="nowrap"><Box><Text fw={600} size="sm" ta="left">{strategy.name}</Text><Text c="dimmed" size="xs" ta="left">{history.length} stored run{history.length === 1 ? '' : 's'}</Text></Box>{latest?.automated_analysis ? <AnalysisStatus status={latest.automated_analysis.status}/> : latest ? <ValidationStatus status={latest.validation_status}/> : <StatusBadge value="NOT RUN"/>}</Group>
        </button>;
      })}</Stack></Panel>
      <Box className="span2"><Panel>
        <Group justify="space-between" align="flex-start"><Box><Text className="eyebrow">{selected.id}</Text><Title order={3}>{selected.name}</Title><Text size="sm" c="dimmed" maw={760}>{selected.description}</Text></Box><Button onClick={() => dispatch(navigate('runner'))}>Run strategy</Button></Group>
        <Text className="eyebrow" mt="md">Charts</Text><Group gap="xs" mt={5}>{selected.charts.map(chart => <Badge key={chart} variant="light" color="teal">{chart}</Badge>)}</Group>
        <Text className="eyebrow" mt="md">Timeframes</Text><Group gap="xs" mt={5}>{selected.timeframes.map(frame => <Badge key={frame} variant="light" color="blue">{frame}</Badge>)}</Group>
        {selected.sessions.length > 0 && <><Text className="eyebrow" mt="md">Sessions</Text><Group gap="xs" mt={5}>{selected.sessions.map(session => <Badge key={session.id} variant="light" color="violet">{session.name}</Badge>)}</Group></>}
        {selected.legacy_sources.length > 0 && <Text size="xs" c="dimmed" mt="md">Tracks {selected.legacy_sources.length} specific legacy implementation{selected.legacy_sources.length === 1 ? '' : 's'} in the inventory and run provenance.</Text>}
        <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm" my="lg"><Box className="metricBox"><Text className="eyebrow">Configuration fields</Text><Text size="xl">{selected.parameters.length}</Text></Box><Box className="metricBox"><Text className="eyebrow">Runs</Text><Text size="xl">{selectedRuns.length}</Text></Box><Box className="metricBox"><Text className="eyebrow">Validated</Text><Text size="xl">{selectedRuns.filter(run => run.validation_status === 'data_validated').length}</Text></Box><Box className="metricBox"><Text className="eyebrow">Research status</Text><Text size="sm" fw={600} mt={7}>NOT REVIEWED</Text></Box></SimpleGrid>
        {latestAnalysis && <Alert color={['blocked', 'negative_evidence'].includes(latestAnalysis.status) ? 'red' : 'yellow'} mb="lg" title="Latest automated finding"><Group gap="xs" mb={5}><AnalysisStatus status={latestAnalysis.status}/></Group>{latestAnalysis.headline} {latestAnalysis.next_action}</Alert>}
        <Text fw={600} mb="xs">Run history</Text><RunTable runs={selectedRuns}/>
      </Panel></Box>
    </SimpleGrid>}
    {catalogAudit && <SpecificStrategyInventory audit={catalogAudit}/>}
  </>;
}

type MetricValue = string | number | null;

function readMetric(run: AnalysisRun, keys: string[]): MetricValue {
  if (!run.summary) return null;
  const summary = run.summary as Record<string, unknown>;
  const containers = [summary.statistics, summary.performance, summary.metrics, summary].filter(value => value && typeof value === 'object') as Record<string, unknown>[];
  for (const container of containers) for (const key of keys) { const value = container[key]; if (typeof value === 'string' || typeof value === 'number') return value; }
  return null;
}

function displayMetric(value: MetricValue, digits = 2) {
  if (value === null) return '—';
  return typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: digits }) : value;
}

function ResearchPage() {
  const dispatch = useAppDispatch();
  const runs = useAppSelector(state => state.runner.runs).filter(run => ['completed', 'failed'].includes(run.status));
  return <><PageHeading title="Research history" description="Compare machine-readable results without inventing metrics that a strategy did not report." action={<Button onClick={() => dispatch(navigate('runner'))}>Run another test</Button>}/><Alert color="blue" mb="lg" title="Interpretation">Data validation confirms a reproducible run. Profitability, robustness, out-of-sample evidence, and trading approval require separate review.</Alert><Panel><ScrollArea><Table miw={1240} verticalSpacing="sm" highlightOnHover><Table.Thead><Table.Tr><Table.Th>Run</Table.Th><Table.Th>Chart</Table.Th><Table.Th ta="right">Sessions</Table.Th><Table.Th ta="right">Closed trades</Table.Th><Table.Th ta="right">Net $</Table.Th><Table.Th ta="right">Session Sharpe</Table.Th><Table.Th ta="right">Max DD (reported unit)</Table.Th><Table.Th>Validation</Table.Th><Table.Th>Automated finding</Table.Th></Table.Tr></Table.Thead><Table.Tbody>{runs.map(run => <Table.Tr key={run.id}><Table.Td><Text fw={600} size="sm">{run.strategy_name}</Text><Text c="dimmed" className="mono" size="xs">{formatDate(run.created_at)}</Text></Table.Td><Table.Td>{chartForRun(run)}</Table.Td><Table.Td ta="right" className="mono">{displayMetric(readMetric(run, ['sessions', 'profile_grade_sessions']), 0)}</Table.Td><Table.Td ta="right" className="mono">{displayMetric(readMetric(run, ['trades', 'trade_count']), 0)}</Table.Td><Table.Td ta="right" className="mono">{displayMetric(readMetric(run, ['net_dollars', 'net_profit_dollars', 'total_pnl', 'total_dollars']))}</Table.Td><Table.Td ta="right" className="mono">{displayMetric(readMetric(run, ['sharpe', 'sharpe_ratio']))}</Table.Td><Table.Td ta="right" className="mono">{displayMetric(readMetric(run, ['max_drawdown_pct_initial', 'max_drawdown_pct', 'max_drawdown_dollars', 'max_drawdown']))}</Table.Td><Table.Td><ValidationStatus status={run.validation_status}/></Table.Td><Table.Td maw={330}>{run.automated_analysis ? <><AnalysisStatus status={run.automated_analysis.status}/><Text size="xs" mt={5}>{run.automated_analysis.headline}</Text></> : <StatusBadge value="PENDING" tone="watch"/>}</Table.Td></Table.Tr>)}</Table.Tbody></Table></ScrollArea>{!runs.length && <Text c="dimmed" size="sm">No completed research runs yet.</Text>}</Panel></>;
}

function DataPage() {
  const dispatch = useAppDispatch();
  const { charts, runs } = useAppSelector(state => state.runner);
  const refresh = () => { void dispatch(fetchCharts()); void dispatch(fetchRuns()); };
  return <><PageHeading title="Data" description="Prepared Databento one-minute archives and the separate analysis-run registry." action={<Button variant="default" leftSection={<IconRefresh size={16}/>} onClick={refresh}>Refresh</Button>}/><SimpleGrid cols={{ base: 1, lg: 3 }} spacing="lg" style={{ alignItems: 'start' }}><Box className="span2"><Panel><ScrollArea><Table miw={850} verticalSpacing="sm"><Table.Thead><Table.Tr><Table.Th>Chart</Table.Th><Table.Th>Coverage</Table.Th><Table.Th ta="right">1m bars</Table.Th><Table.Th>Prepared frames</Table.Th><Table.Th>Contract</Table.Th><Table.Th>Status</Table.Th></Table.Tr></Table.Thead><Table.Tbody>{charts.map(chart => <Table.Tr key={chart.id}><Table.Td><Text fw={600}>{chart.symbol}</Text><Text c="dimmed" size="xs">{chart.name}</Text></Table.Td><Table.Td><Text size="xs">{chart.first_bar?.slice(0, 10) ?? '—'} → {chart.last_bar?.slice(0, 10) ?? '—'}</Text><Text c="dimmed" size="xs">{chart.timezone}</Text></Table.Td><Table.Td ta="right" className="mono">{chart.rows?.toLocaleString() ?? '—'}</Table.Td><Table.Td><Group gap={4}>{chart.timeframes.map(frame => <Badge key={frame} size="xs" variant="outline" color="gray">{frame}</Badge>)}</Group></Table.Td><Table.Td><Text size="xs">tick {chart.tick_size}</Text><Text c="dimmed" size="xs">${chart.point_value}/point</Text></Table.Td><Table.Td><StatusBadge value={chart.available ? 'READY' : 'MISSING'} tone={chart.available ? 'pass' : 'fail'}/></Table.Td></Table.Tr>)}</Table.Tbody></Table></ScrollArea></Panel></Box><Stack gap="lg"><Panel><Text fw={600}>Analysis registry</Text><Text size="xl" mt="xs">{runs.length} runs</Text><Text className="mono" size="xs" mt="sm">data/strategy_dashboard.sqlite3</Text><Text c="dimmed" size="xs" mt="sm">Stores parameters, lifecycle status, artifact indexes, hashes, and validation checks. It does not modify the market-data Parquet files.</Text></Panel><Panel><Text fw={600}>Dataset contract</Text><Stack gap={8} mt="sm">{['Databento source', 'One-minute UTC timestamps', 'Continuous volume roll', 'OHLCV schema', 'Prepared resampled frames'].map(item => <Group key={item} gap="xs"><IconCheck size={14} color="#28766e"/><Text size="xs">{item}</Text></Group>)}</Stack></Panel></Stack></SimpleGrid></>;
}

function ParameterField({ parameter, value, onChange }: { parameter: RunnerParameter; value: unknown; onChange: (value: unknown) => void }) {
  const common = { label: parameter.label, description: parameter.help };
  const choices = parameter.choices.map(choice => ({
    value: choice,
    label: choice === 'fractional' ? 'Fractional research units' : choice === 'whole_contracts' ? 'Whole contracts' : choice,
  }));
  if (parameter.kind === 'boolean') return <Switch {...common} checked={Boolean(value)} onChange={event => onChange(event.currentTarget.checked)}/>;
  if (parameter.kind === 'number' || parameter.kind === 'integer') return <NumberInput {...common} value={typeof value === 'number' ? value : ''} min={parameter.minimum ?? undefined} max={parameter.maximum ?? undefined} decimalScale={parameter.kind === 'integer' ? 0 : undefined} onChange={onChange}/>;
  if (parameter.kind === 'select') return <Select {...common} value={String(value ?? '')} data={choices} allowDeselect={!parameter.required} onChange={onChange}/>;
  if (parameter.kind === 'multiselect') return <MultiSelect {...common} value={Array.isArray(value) ? value.map(String) : []} data={parameter.choices} searchable onChange={onChange}/>;
  return <TextInput {...common} type={parameter.kind === 'date' ? 'date' : parameter.kind === 'time' ? 'time' : 'text'} value={String(value ?? '')} onChange={event => onChange(event.currentTarget.value)}/>;
}

type ArtifactPreviewValue = { kind: 'table'; columns: string[]; rows: Record<string, string>[]; truncated: boolean } | { kind: 'json' | 'text'; value: unknown };

function TinyResultChart({ rows, columns }: { rows: Record<string, string>[]; columns: string[] }) {
  const numericColumns = useMemo(() => columns.filter(column => rows.some(row => row[column] !== '' && Number.isFinite(Number(row[column])))), [columns, rows]);
  const [yColumn, setYColumn] = useState(numericColumns.at(-1) ?? '');
  useEffect(() => { if (!numericColumns.includes(yColumn)) setYColumn(numericColumns.at(-1) ?? ''); }, [numericColumns, yColumn]);
  const values = rows.map(row => Number(row[yColumn])).filter(Number.isFinite);
  if (!values.length) return <Text c="dimmed" size="sm">This file has no numeric series to chart.</Text>;
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const points = values.map((value, index) => `${values.length === 1 ? 50 : index / (values.length - 1) * 100},${78 - (value - min) / span * 70}`).join(' ');
  return <><Select label="Y-axis" size="xs" w={240} data={numericColumns} value={yColumn} onChange={value => value && setYColumn(value)} mb="sm"/><svg viewBox="0 0 100 82" preserveAspectRatio="none" className="resultChart">{[8, 25, 42, 59, 78].map(y => <line key={y} x1="0" x2="100" y1={y} y2={y} className="gridLine"/>)}<polyline points={points} className="equityLine"/></svg><Group justify="space-between"><Text size="xs" c="dimmed">{min.toLocaleString()}</Text><Text size="xs" c="dimmed">{yColumn} · {values.length} rows</Text><Text size="xs" c="dimmed">{max.toLocaleString()}</Text></Group></>;
}

function ArtifactPreview({ run }: { run: AnalysisRun }) {
  const [artifactName, setArtifactName] = useState(run.artifacts[0]?.name ?? '');
  const [mode, setMode] = useState<'table' | 'chart' | 'raw'>('table');
  const [preview, setPreview] = useState<ArtifactPreviewValue | null>(null);
  const [loading, setLoading] = useState(false);
  const artifact = useMemo(() => run.artifacts.find(item => item.name === artifactName) ?? run.artifacts[0], [artifactName, run.artifacts]);
  useEffect(() => { if (!artifact || ['image', 'html', 'file'].includes(artifact.kind)) { setPreview(null); return; } setLoading(true); fetch(`/api/runs/${run.id}/preview/${artifact.name}`).then(response => response.ok ? response.json() : Promise.reject(new Error('Preview unavailable'))).then(setPreview).catch(() => setPreview(null)).finally(() => setLoading(false)); }, [run.id, artifact]);
  if (!run.artifacts.length) return <Text c="dimmed" size="sm">The run produced no recognized result files.</Text>;
  return <Box className="artifactPreview"><Group mb="md" align="flex-end"><Select label="Result file" searchable value={artifact?.name} data={run.artifacts.map(item => ({ value: item.name, label: `${item.name} · ${item.kind}` }))} onChange={value => value && setArtifactName(value)} flex={1}/>{artifact?.kind === 'table' && <Select label="View" value={mode} data={[{ value: 'table', label: 'Table' }, { value: 'chart', label: 'Line chart' }, { value: 'raw', label: 'Raw JSON' }]} onChange={value => setMode((value ?? 'table') as typeof mode)} w={140}/>}<Button component="a" variant="default" href={artifact?.url} download leftSection={<IconDownload size={15}/>}>Download</Button></Group>{loading && <Group justify="center" p="xl"><Loader size="sm"/></Group>}{!loading && artifact?.kind === 'image' && <img className="artifactImage" src={artifact.url} alt={artifact.name}/>} {!loading && artifact?.kind === 'html' && <iframe className="artifactFrame" src={artifact.url} title={artifact.name}/>} {!loading && preview?.kind === 'table' && mode === 'chart' && <TinyResultChart rows={preview.rows} columns={preview.columns}/>} {!loading && preview?.kind === 'table' && mode === 'table' && <ScrollArea h={390}><Table striped highlightOnHover miw={700} verticalSpacing="xs"><Table.Thead><Table.Tr>{preview.columns.map(column => <Table.Th key={column}>{column}</Table.Th>)}</Table.Tr></Table.Thead><Table.Tbody>{preview.rows.map((row, index) => <Table.Tr key={index}>{preview.columns.map(column => <Table.Td key={column} className="mono"><Text size="xs">{row[column]}</Text></Table.Td>)}</Table.Tr>)}</Table.Tbody></Table></ScrollArea>} {!loading && preview && (preview.kind !== 'table' || mode === 'raw') && <Code block className="rawPreview">{JSON.stringify(preview.kind === 'table' ? preview.rows : preview.value, null, 2)}</Code>}</Box>;
}

function ValidationPanel({ run }: { run: AnalysisRun }) {
  return <Box className="validationPanel"><Group justify="space-between" mb="xs"><Box><Text fw={600} size="sm">Automated validation</Text><Text c="dimmed" size="xs">Stored with this analysis run.</Text></Box><ValidationStatus status={run.validation_status}/></Group>{(run.validation_checks?.length ?? 0) > 0 ? <Stack gap={6}>{run.validation_checks?.map(item => <Group key={item.code} justify="space-between" align="flex-start" wrap="nowrap" className="validationCheck"><Box><Text size="xs" fw={600}>{item.code.replaceAll('_', ' ')}</Text><Text size="xs" c="dimmed">{item.message}</Text></Box><StatusBadge value={item.state.toUpperCase()} tone={item.state}/></Group>)}</Stack> : <Text size="xs" c="dimmed">Validation details are pending.</Text>}<Alert color="blue" mt="sm" title="Research review is separate">This does not declare the strategy profitable or approved for trading.</Alert></Box>;
}

function AutomatedAnalysisPanel({ analysis }: { analysis: AutomatedAnalysis | null | undefined }) {
  if (!analysis) return <Box className="analysisPanel"><Text fw={600}>Automated research analysis</Text><Text size="xs" c="dimmed" mt="xs">Analysis is pending. Restart an older API process or rerun the strategy to generate it.</Text></Box>;
  const toneForCheck = (state: 'pass' | 'watch' | 'fail' | 'unknown') => state === 'unknown' ? 'neutral' : state;
  return <Box className="analysisPanel">
    <Group justify="space-between" align="flex-start" mb="md"><Box><Text fw={600}>Automated research analysis</Text><Text size="sm" mt={4}>{analysis.headline}</Text></Box><AnalysisStatus status={analysis.status}/></Group>
    {analysis.sections.length > 0 && <><Text className="eyebrow" mb={6}>Reported performance sections</Text><ScrollArea><Table miw={820} verticalSpacing="xs" mb="md"><Table.Thead><Table.Tr><Table.Th>Section</Table.Th><Table.Th ta="right">Closed trades</Table.Th><Table.Th ta="right">Active sessions</Table.Th><Table.Th ta="right">Orders</Table.Th><Table.Th ta="right">Net P&amp;L</Table.Th><Table.Th ta="right">Profit factor</Table.Th><Table.Th ta="right">Session Sharpe</Table.Th><Table.Th ta="right">Max drawdown</Table.Th></Table.Tr></Table.Thead><Table.Tbody>{analysis.sections.map(section => <Table.Tr key={section.name}><Table.Td><Text size="xs" fw={600}>{section.name}</Text></Table.Td><Table.Td ta="right" className="mono">{displayMetric(section.trades, 0)}</Table.Td><Table.Td ta="right" className="mono">{displayMetric(section.active_sessions, 0)}</Table.Td><Table.Td ta="right" className="mono">{displayMetric(section.orders, 0)}</Table.Td><Table.Td ta="right" className="mono">{displayMetric(section.net_pnl)}</Table.Td><Table.Td ta="right" className="mono">{displayMetric(section.profit_factor)}</Table.Td><Table.Td ta="right" className="mono">{displayMetric(section.sharpe)}</Table.Td><Table.Td ta="right" className="mono">{displayMetric(section.max_drawdown)}</Table.Td></Table.Tr>)}</Table.Tbody></Table></ScrollArea></>}
    <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">{analysis.checks.map(item => <Box key={item.code} className={`researchCheck ${item.state}`}><Group justify="space-between"><Text fw={600} size="sm">{item.name}</Text><StatusBadge value={item.state.toUpperCase()} tone={toneForCheck(item.state)}/></Group><Text size="xs" mt={7}><strong>Observed:</strong> {item.observed}</Text><Text size="xs" c="dimmed" mt={4}><strong>Requirement:</strong> {item.requirement}</Text><Text size="xs" mt={4}>{item.rationale}</Text><Text size="xs" c="teal.8" mt={6}><strong>Next:</strong> {item.response}</Text></Box>)}</SimpleGrid>
    <Alert color={['blocked', 'negative_evidence'].includes(analysis.status) ? 'red' : 'yellow'} mt="md" title="Recommended next action">{analysis.next_action}</Alert>
  </Box>;
}

function AnalysisRunner() {
  const dispatch = useAppDispatch();
  const { catalog, charts, runs, activeRunId, loading, error } = useAppSelector(state => state.runner);
  const requestedStrategyId = useAppSelector(state => state.dashboard.selectedStrategy);
  const [strategyId, setStrategyId] = useState('');
  const [chartId, setChartId] = useState('');
  const [chartIds, setChartIds] = useState<string[]>([]);
  const [timeframe, setTimeframe] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [parameters, setParameters] = useState<Record<string, unknown>>({});
  const activeRun = runs.find(run => run.id === activeRunId) ?? null;
  const definition = catalog.find(item => item.id === strategyId);
  useEffect(() => { if (requestedStrategyId && catalog.some(item => item.id === requestedStrategyId)) setStrategyId(requestedStrategyId); else if (!strategyId && catalog[0]) setStrategyId(catalog[0].id); }, [catalog, requestedStrategyId, strategyId]);
  useEffect(() => {
    if (!definition) return;
    const readyCharts = definition.charts.filter(id => charts.some(chart => chart.id === id && chart.available));
    if (definition.maximum_charts > 1) {
      const valid = chartIds.filter(id => readyCharts.includes(id));
      const defaults = definition.default_charts.filter(id => readyCharts.includes(id));
      const next = valid.length >= definition.minimum_charts ? valid : defaults.length >= definition.minimum_charts ? defaults : readyCharts.slice(0, definition.minimum_charts);
      if (next.join('|') !== chartIds.join('|')) setChartIds(next);
    } else if (!readyCharts.includes(chartId)) setChartId(readyCharts[0] ?? '');
  }, [chartId, chartIds, charts, definition]);
  useEffect(() => { if (definition && !definition.timeframes.includes(timeframe)) setTimeframe(definition.default_timeframe); }, [definition, timeframe]);
  useEffect(() => { if (!definition) return; const sessionIds = definition.sessions.map(session => session.id); if (!sessionIds.includes(sessionId)) setSessionId(definition.default_session ?? sessionIds[0] ?? ''); }, [definition, sessionId]);
  useEffect(() => { if (definition) setParameters(Object.fromEntries(definition.parameters.map(parameter => [parameter.key, parameter.default]))); }, [definition]);
  useEffect(() => { if (!activeRun || !['queued', 'running'].includes(activeRun.status)) return; const timer = window.setInterval(() => { void dispatch(fetchRun(activeRun.id)); }, 1200); return () => window.clearInterval(timer); }, [activeRun, dispatch]);
  const selectedChartIds = definition?.maximum_charts && definition.maximum_charts > 1 ? chartIds : chartId ? [chartId] : [];
  const selectedCharts = charts.filter(chart => selectedChartIds.includes(chart.id));
  const chartCountValid = !!definition && selectedChartIds.length >= definition.minimum_charts && selectedChartIds.length <= definition.maximum_charts;
  const submit = () => { if (strategyId && chartCountValid && timeframe && (!definition?.sessions.length || sessionId)) void dispatch(startRun({ strategyId, chartIds: selectedChartIds, timeframe, sessionId: sessionId || undefined, parameters })); };
  return <>
    <PageHeading title="Run analysis" description="Choose a specific strategy, then apply its chart universe, timeframe, and session inputs." action={<Badge variant="outline" color="teal" leftSection={<IconDatabase size={13}/>}>Historical data</Badge>}/>
    {error && <Alert color="red" title="Runner unavailable" mb="lg">{error}. Start both services with <Code>npm run dev:full</Code>.</Alert>}
    <SimpleGrid cols={{ base: 1, lg: 3 }} spacing="lg" style={{ alignItems: 'start' }}>
      <Panel><Text fw={600} mb="sm">Run configuration</Text>
        <Select label="Specific strategy" searchable data={catalog.map(item => ({ value: item.id, label: item.name }))} value={strategyId} onChange={value => value && setStrategyId(value)}/>
        {definition && <>
          <Text size="xs" c="dimmed" mt="xs" mb="md">{definition.description}</Text>
          {definition.maximum_charts > 1 ? <MultiSelect
            label="Chart universe"
            description={`Select ${definition.minimum_charts}${definition.maximum_charts === definition.minimum_charts ? '' : `–${definition.maximum_charts}`} distinct charts.`}
            searchable
            data={charts.filter(chart => definition.charts.includes(chart.id) && chart.available).map(chart => ({ value: chart.id, label: `${chart.symbol} · ${chart.name}` }))}
            value={chartIds}
            onChange={setChartIds}
            maxValues={definition.maximum_charts}
          /> : <Select label="Chart" searchable data={charts.filter(chart => definition.charts.includes(chart.id) && chart.available).map(chart => ({ value: chart.id, label: `${chart.symbol} · ${chart.name}` }))} value={chartId} onChange={value => value && setChartId(value)}/>}
          <Select label="Timeframe" description="Signal and execution bar resolution for this run." data={definition.timeframes} value={timeframe} onChange={value => value && setTimeframe(value)} mb="md"/>
          {definition.sessions.length > 0 && <Select label="Market session" description="Timezone and bar boundaries come from the session registry." data={definition.sessions.map(session => ({ value: session.id, label: `${session.name} · ${session.open_time}–${session.close_time} ${session.timezone}` }))} value={sessionId} onChange={value => value && setSessionId(value)} mb="md"/>}
          {selectedCharts.map(selectedChart => <Box className="datasetCard" key={selectedChart.id}><Group justify="space-between"><Text fw={600} size="xs">{selectedChart.symbol} · {selectedChart.source}</Text><StatusBadge value="READY" tone="pass"/></Group><Text c="dimmed" size="xs">{selectedChart.rows?.toLocaleString() ?? '—'} one-minute bars · {selectedChart.first_bar?.slice(0, 10)} to {selectedChart.last_bar?.slice(0, 10)}</Text><Text c="dimmed" size="xs">tick {selectedChart.tick_size} · ${selectedChart.point_value}/point · {selectedChart.timezone}</Text><Text c="dimmed" size="xs" className="mono">dataset {selectedChart.fingerprint?.slice(0, 12)}…</Text></Box>)}
          <Stack gap="md">{definition.parameters.map(parameter => <ParameterField key={parameter.key} parameter={parameter} value={parameters[parameter.key]} onChange={value => setParameters(current => ({ ...current, [parameter.key]: value }))}/>)}</Stack>
          <Button fullWidth mt="xl" loading={loading} disabled={!chartCountValid || !timeframe || (definition.sessions.length > 0 && !sessionId)} onClick={submit} leftSection={<IconTrendingUp size={16}/>}>Run strategy</Button>
        </>}
      </Panel>
      <Box className="span2"><Panel><Group justify="space-between" mb="sm"><Text fw={600}>Runs</Text><Button size="compact-xs" variant="subtle" leftSection={<IconRefresh size={14}/>} onClick={() => void dispatch(fetchRuns())}>Refresh</Button></Group><RunTable runs={runs} limit={12} onInspect={run => dispatch(selectRun(run.id))}/></Panel>
        {activeRun && <Panel className="runDetail"><Group justify="space-between" mb="sm"><Box><Text fw={600}>{activeRun.strategy_name}</Text><Text c="dimmed" size="xs" className="mono">{activeRun.output_dir}</Text></Box><RunStatus status={activeRun.status}/></Group>{['queued', 'running'].includes(activeRun.status) && <Group justify="center" p="xl"><Loader size="sm"/><Text size="sm">{activeRun.status === 'queued' ? 'Waiting for a worker…' : 'Analysis is running…'}</Text></Group>}{['completed', 'failed'].includes(activeRun.status) && <><ValidationPanel run={activeRun}/><AutomatedAnalysisPanel analysis={activeRun.automated_analysis}/></>} {activeRun.status === 'failed' && <Alert color="red" mt="md" title={`Exited with code ${activeRun.return_code ?? 'unknown'}`}><Code block>{activeRun.log || 'No process output was captured.'}</Code></Alert>}{activeRun.status === 'completed' && <ArtifactPreview run={activeRun}/>}<details className="runMeta"><summary>Run specification</summary><Code block>{JSON.stringify(activeRun.parameters, null, 2)}</Code>{activeRun.log && <><Text className="eyebrow" mt="sm">Process output</Text><Code block className="runLog">{activeRun.log}</Code></>}</details></Panel>}
      </Box>
    </SimpleGrid>
  </>;
}

export function App() {
  const dispatch = useAppDispatch();
  const view = useAppSelector(state => state.dashboard.view);
  useEffect(() => {
    void dispatch(fetchRunnerCatalog()); void dispatch(fetchCatalogAudit()); void dispatch(fetchCharts()); void dispatch(fetchRuns());
    void dispatch(fetchPortfolio()); void dispatch(fetchPortfolioDecisions()); void dispatch(fetchPortfolioAlerts()); void dispatch(fetchPortfolioExperiments());
    const monitor = window.setInterval(() => { void dispatch(fetchPortfolio()); void dispatch(fetchPortfolioAlerts()); }, 60_000);
    return () => window.clearInterval(monitor);
  }, [dispatch]);
  const content: Record<View, ReactNode> = {
    overview: <PortfolioOverview/>, health: <HealthPage/>, risk: <RiskPage/>, decisions: <DecisionsPage/>,
    lab: <LabPage/>, registry: <RegistryPage/>, strategies: <StrategiesPage/>, research: <ResearchPage/>,
    runner: <AnalysisRunner/>, data: <DataPage/>,
  };
  return <><Header/><Container size={1420} className="main">{content[view]}</Container><footer><Container size={1420}><Group justify="space-between"><Text size="xs">Strategy Research Dashboard · historical decision support</Text><Group gap={6}><IconChartBar size={13}/><Text size="xs">Databento data · local run registry</Text></Group></Group></Container></footer></>;
}
