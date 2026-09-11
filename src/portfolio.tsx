import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  Alert, Badge, Box, Button, Checkbox, Group, MultiSelect, NumberInput, Paper,
  ScrollArea, Select, SimpleGrid, Stack, Table, Text, Textarea, TextInput, Title,
} from '@mantine/core';
import { IconActivity, IconAlertTriangle, IconDownload, IconPlayerPlay, IconScale, IconSettings } from '@tabler/icons-react';
import {
  actOnPortfolioAlert, createPortfolioDecision, fetchPortfolio, fetchPortfolioAlerts,
  fetchPortfolioDecisions, fetchPortfolioExperiments, importPortfolioObservations,
  runPortfolioExperiment, savePortfolioSettings, useAppDispatch, useAppSelector,
  type PortfolioStrategy,
} from './store';

function Panel({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <Paper withBorder className={`panel ${className}`}>{children}</Paper>;
}

function Heading({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <Group justify="space-between" align="flex-end" mb="lg"><Box><Title order={2}>{title}</Title><Text c="dimmed" size="sm">{description}</Text></Box>{action}</Group>;
}

function BadgeState({ value }: { value: string }) {
  const lower = value.toLowerCase();
  const color = ['normal', 'qualified', 'base', 'complete', 'resolved'].includes(lower) ? 'teal'
    : ['watch', 'provisional', 'reduced', 'acknowledged', 'in validation'].includes(lower) ? 'yellow'
      : ['breached', 'rejected', 'paused', 'critical'].includes(lower) ? 'red' : 'gray';
  return <Badge color={color} variant={color === 'red' ? 'filled' : 'light'} radius="xs" size="sm">{value}</Badge>;
}

function pct(value: number | null | undefined, digits = 1) {
  return value == null ? '—' : `${(value * 100).toFixed(digits)}%`;
}

function date(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : '—';
}

function reasons(values: string[]) {
  return values.map(value => value.replaceAll('_', ' ').toLowerCase()).join(', ');
}

function ConfigWarning() {
  const snapshot = useAppSelector(state => state.portfolio.snapshot);
  if (!snapshot || snapshot.configuration_complete) return null;
  return <Alert color="yellow" title="Configuration is incomplete" mb="lg">
    New capital-changing proposals remain unavailable until these fields are set: {snapshot.missing_configuration.join(', ')}.
  </Alert>;
}

function EquitySpark({ points, color = '#28766e' }: { points: PortfolioStrategy['equity_curve']; color?: string }) {
  if (points.length < 2) return <Text c="dimmed" size="xs">No return observations</Text>;
  const values = points.map(item => item.equity);
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const line = values.map((value, index) => `${(index / (values.length - 1)) * 100},${36 - ((value - min) / span) * 34}`).join(' ');
  return <svg viewBox="0 0 100 38" preserveAspectRatio="none" className="spark"><polyline fill="none" stroke={color} strokeWidth="1.5" points={line}/></svg>;
}

export function PortfolioOverview() {
  const dispatch = useAppDispatch();
  const { snapshot, loading, error } = useAppSelector(state => state.portfolio);
  const [filter, setFilter] = useState('actionable');
  const strategies = useMemo(() => {
    if (!snapshot) return [];
    if (filter === 'actionable') return snapshot.strategies.filter(item => item.health !== 'Normal' || item.eligibility !== 'Qualified' || item.allocation_state !== 'Base');
    return snapshot.strategies;
  }, [snapshot, filter]);
  return <><Heading title="Portfolio overview" description="Independent evidence, current health, and allocation proposals at the latest available cutoff."
    action={<Group><Select value={filter} data={[{ value: 'actionable', label: 'Actionable issues' }, { value: 'all', label: 'All strategies' }]} onChange={value => setFilter(value ?? 'actionable')} w={170}/><Button loading={loading} onClick={() => dispatch(createPortfolioDecision()).then(() => { void dispatch(fetchPortfolioDecisions()); void dispatch(fetchPortfolioAlerts()); })}>Save decision</Button></Group>}/>
    {error && <Alert color="red" mb="lg" title="Portfolio API">{error}</Alert>}<ConfigWarning/>{snapshot?.portfolio.review_due && <Alert color="yellow" mb="lg" title="Scheduled review is due">{reasons([snapshot.portfolio.review_reason])}. Saving a decision records the point-in-time proposal; it does not send orders.</Alert>}
    {!snapshot ? <Panel><Text c="dimmed">Loading portfolio assessment…</Text></Panel> : <>
      <SimpleGrid cols={{ base: 2, md: 4, xl: 7 }} spacing="md" mb="lg">
        {[
          ['Actual exposure', pct(snapshot.portfolio.actual_gross_exposure), 'Gross recorded exposure'],
          ['Proposed exposure', pct(snapshot.portfolio.proposed_gross_exposure), 'Null means no proposal'],
          ['Portfolio risk', pct(snapshot.portfolio.portfolio_volatility), 'Annualized estimate'],
          ['Current drawdown', pct(Math.min(0, ...snapshot.strategies.map(item => item.current_drawdown ?? 0))), 'Deepest current sleeve'],
          ['Unallocated', pct(snapshot.portfolio.unallocated_capital), 'Released risk remains unused'],
          ['Data as of', new Date(snapshot.as_of).toLocaleDateString(), `${snapshot.calculation_version} · refresh 60s`],
          ['Critical events', String(snapshot.portfolio.critical_events), 'Breached or unknown health'],
        ].map(([label, value, detail]) => <Panel className="kpi" key={label}><Text className="eyebrow">{label}</Text><Text className="kpiValue">{value}</Text><Text c="dimmed" size="xs">{detail}</Text></Panel>)}
      </SimpleGrid>
      <Panel><ScrollArea><Table miw={1480} verticalSpacing="sm" highlightOnHover><Table.Thead><Table.Tr>
        <Table.Th>Strategy version</Table.Th><Table.Th>Eligibility</Table.Th><Table.Th>Health</Table.Th><Table.Th>Allocation</Table.Th>
        <Table.Th ta="right">MTD</Table.Th><Table.Th ta="right">3m</Table.Th><Table.Th ta="right">12m</Table.Th><Table.Th ta="right">Drawdown</Table.Th>
        <Table.Th ta="right">Volatility</Table.Th><Table.Th ta="right">Risk contribution</Table.Th><Table.Th ta="right">Actual</Table.Th><Table.Th ta="right">Proposed</Table.Th><Table.Th>Reason / coverage</Table.Th>
      </Table.Tr></Table.Thead><Table.Tbody>{strategies.map(item => <Table.Tr key={item.id}>
        <Table.Td><Text fw={600} size="sm">{item.name}</Text><Text c="dimmed" size="xs" className="mono">{item.version}</Text></Table.Td>
        <Table.Td><BadgeState value={item.eligibility}/></Table.Td><Table.Td><BadgeState value={item.health}/></Table.Td><Table.Td><BadgeState value={item.allocation_state}/></Table.Td>
        <Table.Td ta="right" className="mono">{pct(item.mtd_return)}</Table.Td><Table.Td ta="right" className="mono">{pct(item.trailing_returns['3'])}</Table.Td><Table.Td ta="right" className="mono">{pct(item.trailing_returns['12'])}</Table.Td>
        <Table.Td ta="right" className="mono">{pct(item.current_drawdown)}</Table.Td><Table.Td ta="right" className="mono">{pct(item.realized_volatility)}</Table.Td><Table.Td ta="right" className="mono">{pct(item.risk_contribution)}</Table.Td>
        <Table.Td ta="right" className="mono">{pct(item.current_exposure)}</Table.Td><Table.Td ta="right" className="mono">{pct(item.proposed_exposure)}</Table.Td>
        <Table.Td maw={300}><Text size="xs">{reasons(item.allocation_reason_codes)}</Text><Text c="dimmed" size="xs">{item.days_observed} observations · latest {date(item.last_event_time)}</Text></Table.Td>
      </Table.Tr>)}</Table.Tbody></Table></ScrollArea>{strategies.length === 0 && <Text c="dimmed" size="sm">No strategies match this filter.</Text>}</Panel>
    </>}
  </>;
}

export function HealthPage() {
  const snapshot = useAppSelector(state => state.portfolio.snapshot);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const strategy = snapshot?.strategies.find(item => item.id === selectedId) ?? snapshot?.strategies[0];
  const [eligibilityHistory, setEligibilityHistory] = useState<{ id: string; assessment_time: string; eligibility: string; reviewer: string; reason_codes: string[] }[]>([]);
  useEffect(() => {
    if (!strategy) { setEligibilityHistory([]); return; }
    void fetch(`/api/portfolio/eligibility-assessments?strategy_version_id=${encodeURIComponent(strategy.id)}`).then(response => response.json()).then(setEligibilityHistory).catch(() => setEligibilityHistory([]));
  }, [strategy]);
  return <><Heading title="Strategy health" description="Continuous reference metrics, qualification evidence, and state explanations remain separate."/>
    {!snapshot || !strategy ? <Panel><Text c="dimmed">No registered strategy versions.</Text></Panel> : <SimpleGrid cols={{ base: 1, lg: 3 }} spacing="lg" style={{ alignItems: 'start' }}>
      <Panel><Select searchable label="Strategy version" value={strategy.id} data={snapshot.strategies.map(item => ({ value: item.id, label: `${item.name} · ${item.version}` }))} onChange={setSelectedId}/>
        <Stack gap="xs" mt="lg">{snapshot.strategies.map(item => <button className={`strategyChoice ${item.id === strategy.id ? 'active' : ''}`} onClick={() => setSelectedId(item.id)} key={item.id}><Group justify="space-between"><Text size="sm" fw={600}>{item.name}</Text><BadgeState value={item.health}/></Group></button>)}</Stack>
      </Panel><Box className="span2"><Stack gap="lg"><Panel><Group justify="space-between"><Box><Text className="eyebrow">{strategy.id}</Text><Title order={3}>{strategy.name} · {strategy.version}</Title></Box><Group><BadgeState value={strategy.eligibility}/><BadgeState value={strategy.health}/><BadgeState value={strategy.allocation_state}/></Group></Group>
        <SimpleGrid cols={{ base: 2, sm: 4 }} mt="lg">{[['MTD', pct(strategy.mtd_return)], ['Drawdown', pct(strategy.current_drawdown)], ['Volatility', pct(strategy.realized_volatility)], ['Coverage', `${strategy.days_observed} days`]].map(([label, value]) => <Box className="metricBox" key={label}><Text className="eyebrow">{label}</Text><Text size="xl">{value}</Text></Box>)}</SimpleGrid>
        <SimpleGrid cols={{ base: 1, md: 2 }} mt="lg"><Box><Text fw={600} size="sm">Current live/paper equity</Text><EquitySpark points={strategy.equity_curve}/></Box><Box><Text fw={600} size="sm">Continuous frozen reference equity</Text><EquitySpark points={strategy.reference_equity_curve} color="#687875"/></Box></SimpleGrid></Panel>
        <SimpleGrid cols={{ base: 1, md: 2 }}><Panel><Text fw={600}>Explanation</Text><Stack gap="sm" mt="sm"><Box><Text className="eyebrow">Observed state</Text><Text size="sm">{strategy.health} at {date(strategy.assessment_time)}</Text></Box><Box><Text className="eyebrow">Applicable reason codes</Text><Text size="sm">{reasons(strategy.reason_codes)}</Text></Box><Box><Text className="eyebrow">Allocation result</Text><Text size="sm">{strategy.proposed_exposure == null ? 'No target was produced. Existing exposure is not a liquidation instruction.' : `${pct(strategy.current_exposure)} → ${pct(strategy.proposed_exposure)}`}</Text></Box><Box><Text className="eyebrow">What changes the state</Text><Text size="sm">Resolve missing/stale inputs or the recorded hard-risk condition, then run a new cutoff assessment.</Text></Box></Stack></Panel>
        <Panel><Text fw={600}>Qualification evidence</Text><Stack gap="sm" mt="sm"><Box><Text className="eyebrow">Evidence strength</Text><Text size="sm">{strategy.evidence_strength}</Text></Box><Box><Text className="eyebrow">Reviewer</Text><Text size="sm">{strategy.reviewer ?? 'Not recorded'}</Text></Box><Box><Text className="eyebrow">Acceptance profile</Text><Text size="sm">{strategy.acceptance_profile ? JSON.stringify(strategy.acceptance_profile) : 'Not recorded'}</Text></Box><Box><Text className="eyebrow">Limitations</Text><Text size="sm">{strategy.limitations.join(' ') || 'None recorded'}</Text></Box></Stack></Panel></SimpleGrid>
        <SimpleGrid cols={{ base: 1, md: 2 }}><Panel><Text fw={600}>Execution diagnostics</Text><SimpleGrid cols={2} mt="sm">{[['Observed orders', String(strategy.execution_diagnostics.orders_observed)], ['Fill rate', pct(strategy.execution_diagnostics.fill_rate)], ['Rejected', String(strategy.execution_diagnostics.rejected_orders)], ['Average slippage', strategy.execution_diagnostics.average_slippage?.toFixed(3) ?? '—'], ['Fees', strategy.execution_diagnostics.fees?.toLocaleString() ?? '—'], ['Average delay', strategy.execution_diagnostics.average_execution_delay_seconds == null ? '—' : `${strategy.execution_diagnostics.average_execution_delay_seconds.toFixed(1)}s`]].map(([label, value]) => <Box className="metricBox" key={label}><Text className="eyebrow">{label}</Text><Text size="sm">{value}</Text></Box>)}</SimpleGrid></Panel><Panel><Text fw={600}>Position and history coverage</Text><SimpleGrid cols={2} mt="sm">{[['Live / paper', `${strategy.history_coverage.live} / ${strategy.history_coverage.paper}`], ['Reference / backtest', `${strategy.history_coverage.reference} / ${strategy.history_coverage.backtest}`], ['Gross / net', `${pct(strategy.position_diagnostics.gross_exposure)} / ${pct(strategy.position_diagnostics.net_exposure)}`], ['Margin', strategy.position_diagnostics.margin?.toLocaleString() ?? '—'], ['Liquidity usage', pct(strategy.position_diagnostics.liquidity_usage)], ['Live-reference gap', pct(strategy.live_reference_gap)]].map(([label, value]) => <Box className="metricBox" key={label}><Text className="eyebrow">{label}</Text><Text size="sm">{value}</Text></Box>)}</SimpleGrid></Panel></SimpleGrid>
        <Panel><Text fw={600}>Eligibility decision timeline</Text><Stack gap="xs" mt="sm">{eligibilityHistory.map(item => <Group key={item.id} justify="space-between" className="history"><Box><Text size="sm" fw={600}>{item.reviewer}</Text><Text size="xs" c="dimmed">{date(item.assessment_time)} · {reasons(item.reason_codes)}</Text></Box><BadgeState value={item.eligibility}/></Group>)}{eligibilityHistory.length === 0 && <Text c="dimmed" size="sm">No recorded reviewer assessment. The registry status is Provisional.</Text>}</Stack></Panel>
      </Stack></Box>
    </SimpleGrid>}
  </>;
}

export function RiskPage() {
  const snapshot = useAppSelector(state => state.portfolio.snapshot);
  const [paused, setPaused] = useState<string[]>([]);
  const [whatIf, setWhatIf] = useState<{ gross_exposure: number; portfolio_volatility: number; unallocated_capital: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    setError(null);
    const response = await fetch('/api/portfolio/what-if', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paused_strategy_ids: paused }) });
    if (!response.ok) { setError((await response.json()).detail ?? 'What-if failed'); return; }
    const result = await response.json(); setWhatIf(result.what_if);
  };
  return <><Heading title="Portfolio risk workspace" description="Covariance-aware risk, shared exposures, and hedge-sensitive what-if proposals."/>
    <ConfigWarning/>{error && <Alert color="red" mb="lg">{error}</Alert>}{snapshot && <>
      <SimpleGrid cols={{ base: 2, md: 3, xl: 6 }} mb="lg"><Panel><Text className="eyebrow">Actual gross / net</Text><Text className="kpiValue">{pct(snapshot.portfolio.actual_gross_exposure)} / {pct(snapshot.portfolio.actual_net_exposure)}</Text></Panel><Panel><Text className="eyebrow">Proposed gross / net</Text><Text className="kpiValue">{pct(snapshot.portfolio.proposed_gross_exposure)} / {pct(snapshot.portfolio.proposed_net_exposure)}</Text></Panel><Panel><Text className="eyebrow">Proposed volatility</Text><Text className="kpiValue">{pct(snapshot.portfolio.portfolio_volatility)}</Text></Panel><Panel><Text className="eyebrow">Actual / proposed margin</Text><Text className="kpiValue">{snapshot.portfolio.actual_margin.toLocaleString()} / {snapshot.portfolio.proposed_margin.toLocaleString()}</Text></Panel><Panel><Text className="eyebrow">10% gross stress</Text><Text className="kpiValue">{pct(snapshot.portfolio.stress_loss_10pct)}</Text></Panel><Panel><Text className="eyebrow">Unallocated capital</Text><Text className="kpiValue">{pct(snapshot.portfolio.unallocated_capital)}</Text></Panel></SimpleGrid>
      <SimpleGrid cols={{ base: 1, lg: 2 }}><Panel><Text fw={600} mb="sm">Correlation matrix</Text><ScrollArea><Table withTableBorder withColumnBorders verticalSpacing="xs"><Table.Thead><Table.Tr><Table.Th>Strategy</Table.Th>{snapshot.portfolio.correlation_labels.map(label => <Table.Th key={label}>{label.split('@')[0]}</Table.Th>)}</Table.Tr></Table.Thead><Table.Tbody>{snapshot.portfolio.correlation_matrix.map((row, index) => <Table.Tr key={snapshot.portfolio.correlation_labels[index]}><Table.Td><Text size="xs">{snapshot.portfolio.correlation_labels[index].split('@')[0]}</Text></Table.Td>{row.map((value, column) => <Table.Td key={column} ta="right" className="mono"><Text size="xs">{value == null ? '—' : value.toFixed(2)}</Text></Table.Td>)}</Table.Tr>)}</Table.Tbody></Table></ScrollArea><Text c="dimmed" size="xs" mt="sm">Cells remain unavailable until strategies share enough dated return observations.</Text></Panel>
      <Stack><Panel><Text fw={600}>Risk contributions and constraints</Text><Table verticalSpacing="xs" mt="sm"><Table.Thead><Table.Tr><Table.Th>Strategy</Table.Th><Table.Th ta="right">Target</Table.Th><Table.Th ta="right">Contribution</Table.Th><Table.Th>Group</Table.Th></Table.Tr></Table.Thead><Table.Tbody>{snapshot.strategies.map(item => <Table.Tr key={item.id}><Table.Td><Text size="xs">{item.name}</Text></Table.Td><Table.Td ta="right">{pct(item.proposed_exposure)}</Table.Td><Table.Td ta="right">{pct(item.risk_contribution)}</Table.Td><Table.Td><Text size="xs">{item.shared_exposure_group ?? 'Unclassified'}</Text></Table.Td></Table.Tr>)}</Table.Tbody></Table></Panel>
      <Panel><Text fw={600}>What-if pauses</Text><MultiSelect mt="sm" label="Pause strategy targets" data={snapshot.strategies.map(item => ({ value: item.id, label: item.name }))} value={paused} onChange={setPaused}/><Button mt="sm" leftSection={<IconScale size={16}/>} onClick={() => void run()}>Recalculate after hedge removal</Button>{whatIf && <SimpleGrid cols={3} mt="md">{[['Gross', pct(whatIf.gross_exposure)], ['Volatility', pct(whatIf.portfolio_volatility)], ['Unallocated', pct(whatIf.unallocated_capital)]].map(([label, value]) => <Box className="metricBox" key={label}><Text className="eyebrow">{label}</Text><Text>{value}</Text></Box>)}</SimpleGrid>}</Panel></Stack></SimpleGrid>
    </>}
  </>;
}

export function DecisionsPage() {
  const dispatch = useAppDispatch();
  const { decisions, alerts, loading } = useAppSelector(state => state.portfolio);
  const snapshot = useAppSelector(state => state.portfolio.snapshot);
  const [overrides, setOverrides] = useState<{ id: string; strategy_version_id: string; target_exposure: number; owner: string; reason: string; created_at: string; expires_at: string }[]>([]);
  const [override, setOverride] = useState({ strategy_version_id: '', target_exposure: '0', owner: '', reason: '', expires_at: new Date(Date.now() + 86_400_000).toISOString().slice(0, 16) });
  const [overrideError, setOverrideError] = useState<string | null>(null);
  useEffect(() => { void fetch('/api/portfolio/overrides').then(response => response.json()).then(setOverrides).catch(() => undefined); }, []);
  const submitOverride = async () => {
    setOverrideError(null);
    const response = await fetch('/api/portfolio/overrides', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...override, target_exposure: Number(override.target_exposure), expires_at: new Date(override.expires_at).toISOString() }) });
    const body = await response.json();
    if (!response.ok) { setOverrideError(body.detail ?? 'Override failed'); return; }
    setOverrides(current => [body, ...current]);
  };
  return <><Heading title="Decisions and alerts" description="Immutable recommendations, grouped issue episodes, acknowledgments, and resolutions."
    action={<Group><Button component="a" href="/api/portfolio/export?kind=decisions&format=csv" variant="default" leftSection={<IconDownload size={16}/>}>Export</Button><Button loading={loading} onClick={() => dispatch(createPortfolioDecision()).then(() => { void dispatch(fetchPortfolioDecisions()); void dispatch(fetchPortfolioAlerts()); })}>Run decision</Button></Group>}/>
    <SimpleGrid cols={{ base: 1, lg: 2 }}><Panel><Group justify="space-between" mb="sm"><Text fw={600}>Alert queue</Text><Badge color="red" variant="light">{alerts.filter(item => item.state !== 'Resolved').length} unresolved</Badge></Group><Stack gap="sm">{alerts.map(item => <Box className="alertRow" key={item.id}><Group justify="space-between" align="flex-start"><Box><Group gap="xs"><BadgeState value={item.severity}/><BadgeState value={item.state}/></Group><Text fw={600} size="sm" mt={5}>{item.title}</Text><Text size="xs" c="dimmed">{item.detail}</Text><Text size="xs" c="dimmed">First {date(item.first_seen)} · latest {date(item.last_seen)}</Text></Box>{item.state !== 'Resolved' && <Group gap="xs"><Button size="compact-xs" variant="default" disabled={item.state === 'Acknowledged'} onClick={() => dispatch(actOnPortfolioAlert({ id: item.id, action: 'acknowledge' }))}>Acknowledge</Button><Button size="compact-xs" color="teal" onClick={() => dispatch(actOnPortfolioAlert({ id: item.id, action: 'resolve', note: 'Resolved in dashboard' }))}>Resolve</Button></Group>}</Group></Box>)}{alerts.length === 0 && <Text c="dimmed" size="sm">Run a decision to create grouped health or exposure alerts.</Text>}</Stack></Panel>
    <Stack><Panel><Text fw={600} mb="sm">Decision history</Text><Stack gap="sm">{decisions.map(item => <Box className="decisionRow" key={item.id}><Group justify="space-between"><Text fw={600} size="sm" className="mono">{item.id}</Text><BadgeState value={item.configuration_complete ? 'Complete' : 'No current proposal'}/></Group><Text size="xs">Cutoff {date(item.cutoff)} · effective {date(item.effective_time)}</Text><Text size="xs" c="dimmed">{item.policy_version} · {item.calculation_version} · {item.proposals.length} strategies</Text><Text className="mono" size="xs" c="dimmed">snapshot {item.snapshot_hash.slice(0, 16)}…</Text></Box>)}{decisions.length === 0 && <Text c="dimmed" size="sm">No saved allocation decisions.</Text>}</Stack></Panel>
    <Panel><Text fw={600}>Manual override</Text><Text c="dimmed" size="xs">The engine recommendation remains unchanged; this records the separate owner action and expiry.</Text><Select mt="sm" label="Strategy version" value={override.strategy_version_id} data={(snapshot?.strategies ?? []).map(item => ({ value: item.id, label: item.name }))} onChange={value => setOverride(current => ({ ...current, strategy_version_id: value ?? '' }))}/><SimpleGrid cols={2} mt="sm"><TextInput label="Target exposure" value={override.target_exposure} onChange={event => setOverride(current => ({ ...current, target_exposure: event.currentTarget.value }))}/><TextInput type="datetime-local" label="Expires" value={override.expires_at} onChange={event => setOverride(current => ({ ...current, expires_at: event.currentTarget.value }))}/><TextInput label="Owner" value={override.owner} onChange={event => setOverride(current => ({ ...current, owner: event.currentTarget.value }))}/><TextInput label="Reason" value={override.reason} onChange={event => setOverride(current => ({ ...current, reason: event.currentTarget.value }))}/></SimpleGrid>{overrideError && <Alert color="red" mt="sm">{overrideError}</Alert>}<Button mt="sm" disabled={!override.strategy_version_id || !override.owner || !override.reason} onClick={() => void submitOverride()}>Record override</Button>{overrides.slice(0, 3).map(item => <Text key={item.id} size="xs" mt="sm"><span className="mono">{item.id}</span> · {pct(item.target_exposure)} until {date(item.expires_at)} · {item.owner}</Text>)}</Panel></Stack></SimpleGrid>
  </>;
}

export function LabPage() {
  const dispatch = useAppDispatch();
  const { snapshot, experiments } = useAppSelector(state => state.portfolio);
  const [universe, setUniverse] = useState<string[]>([]);
  const [name, setName] = useState('Trailing-return timing candidate');
  const [mechanism, setMechanism] = useState('Reduce exposure after negative trailing reference performance.');
  const [objective, setObjective] = useState('Improve downside risk while preserving compound return.');
  const [minimumImprovement, setMinimumImprovement] = useState('0.01 lower maximum drawdown');
  const [returnSacrifice, setReturnSacrifice] = useState('No more than 0.02 annualized return');
  const [start, setStart] = useState('2024-01-01T00:00:00Z');
  const [end, setEnd] = useState(new Date().toISOString());
  const [cost, setCost] = useState<number | string>(5);
  const [costStress, setCostStress] = useState<number | string>(10);
  const [policyReviewer, setPolicyReviewer] = useState('');
  const [untouchedEvidence, setUntouchedEvidence] = useState('');
  const [paperEvidence, setPaperEvidence] = useState('');
  const [promotionMessage, setPromotionMessage] = useState<string | null>(null);
  const submit = () => dispatch(runPortfolioExperiment({ name, intended_mechanism: mechanism, primary_objective: objective, minimum_meaningful_improvement: minimumImprovement, acceptable_return_sacrifice: returnSacrifice, strategy_version_ids: universe, start, end, resizing_cost_bps: Number(cost), cost_stress_bps: Number(costStress), lookback_days: 63, reduced_multiplier: 0.5, random_seed: 1729, state: 'Exploratory' })).then(() => void dispatch(fetchPortfolioExperiments()));
  const promote = async (experimentId: string, state: string) => {
    setPromotionMessage(null);
    const response = await fetch(`/api/portfolio/experiments/${experimentId}/reviews`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ state, reviewer: policyReviewer, untouched_evaluation_evidence: untouchedEvidence ? { reference: untouchedEvidence } : undefined, forward_paper_evidence: paperEvidence ? { reference: paperEvidence } : undefined }) });
    const body = await response.json();
    if (!response.ok) { setPromotionMessage(body.detail ?? 'Promotion failed'); return; }
    setPromotionMessage(`Recorded ${body.state} review for ${experimentId}`); void dispatch(fetchPortfolioExperiments());
  };
  return <><Heading title="Allocation research lab" description="Pre-register candidate mechanisms and compare timing against the required simpler policies."/>
    <SimpleGrid cols={{ base: 1, lg: 3 }} style={{ alignItems: 'start' }}><Stack><Panel><Stack><TextInput label="Experiment name" value={name} onChange={event => setName(event.currentTarget.value)}/><Textarea label="Intended mechanism" value={mechanism} onChange={event => setMechanism(event.currentTarget.value)}/><Textarea label="Primary objective" value={objective} onChange={event => setObjective(event.currentTarget.value)}/><TextInput label="Minimum meaningful improvement" value={minimumImprovement} onChange={event => setMinimumImprovement(event.currentTarget.value)}/><TextInput label="Acceptable return sacrifice" value={returnSacrifice} onChange={event => setReturnSacrifice(event.currentTarget.value)}/><MultiSelect label="Fixed strategy universe" data={(snapshot?.strategies ?? []).map(item => ({ value: item.id, label: item.name }))} value={universe} onChange={setUniverse}/><TextInput label="Evaluation start (ISO)" value={start} onChange={event => setStart(event.currentTarget.value)}/><TextInput label="Evaluation end (ISO)" value={end} onChange={event => setEnd(event.currentTarget.value)}/><SimpleGrid cols={2}><NumberInput label="Resizing cost (bps)" value={cost} onChange={setCost} min={0}/><NumberInput label="Cost stress (bps)" value={costStress} onChange={setCostStress} min={0}/></SimpleGrid><Button leftSection={<IconPlayerPlay size={16}/>} disabled={!universe.length} onClick={submit}>Run chronological comparison</Button><Text c="dimmed" size="xs">Experiments remain Exploratory until a separate review is recorded.</Text></Stack></Panel><Panel><Text fw={600}>Policy review evidence</Text><TextInput mt="sm" label="Reviewer" value={policyReviewer} onChange={event => setPolicyReviewer(event.currentTarget.value)}/><TextInput mt="sm" label="Untouched evaluation evidence reference" value={untouchedEvidence} onChange={event => setUntouchedEvidence(event.currentTarget.value)}/><TextInput mt="sm" label="Forward paper evidence reference" value={paperEvidence} onChange={event => setPaperEvidence(event.currentTarget.value)}/>{promotionMessage && <Alert mt="sm" color={promotionMessage.startsWith('Recorded') ? 'teal' : 'red'}>{promotionMessage}</Alert>}<Text c="dimmed" size="xs" mt="sm">Paper approval requires uncertainty and untouched evaluation evidence. Allocation approval additionally requires forward paper evidence.</Text></Panel></Stack>
    <Box className="span2"><Stack>{experiments.map(item => <Panel key={item.id}><Group justify="space-between"><Box><Text fw={600}>{item.name ?? item.id}</Text><Text size="xs" c="dimmed">{date(item.created_at)}</Text></Box><Group><BadgeState value={item.state}/><BadgeState value={item.result.status}/></Group></Group>{item.result.reason && <Alert color="yellow" mt="sm">{item.result.reason}</Alert>}{item.result.comparators.length > 0 && <ScrollArea mt="sm"><Table miw={650}><Table.Thead><Table.Tr><Table.Th>Comparator</Table.Th><Table.Th ta="right">Net return</Table.Th><Table.Th ta="right">Volatility</Table.Th><Table.Th ta="right">Sharpe</Table.Th><Table.Th ta="right">Max DD</Table.Th></Table.Tr></Table.Thead><Table.Tbody>{item.result.comparators.map(row => <Table.Tr key={row.name}><Table.Td>{row.name}</Table.Td><Table.Td ta="right">{pct(row.net_compound_return)}</Table.Td><Table.Td ta="right">{pct(row.annualized_volatility)}</Table.Td><Table.Td ta="right">{row.sharpe?.toFixed(2) ?? '—'}</Table.Td><Table.Td ta="right">{pct(row.max_drawdown)}</Table.Td></Table.Tr>)}</Table.Tbody></Table></ScrollArea>}{item.result.warning && <Text c="dimmed" size="xs" mt="sm">{item.result.warning}</Text>}<Group mt="md"><Button size="compact-sm" variant="default" disabled={!policyReviewer} onClick={() => void promote(item.id, 'In validation')}>Move to validation</Button><Button size="compact-sm" variant="default" disabled={!policyReviewer || !untouchedEvidence} onClick={() => void promote(item.id, 'Approved for paper proposals')}>Approve paper</Button><Button size="compact-sm" disabled={!policyReviewer || !untouchedEvidence || !paperEvidence} onClick={() => void promote(item.id, 'Approved for allocation proposals')}>Approve allocation</Button></Group></Panel>)}{experiments.length === 0 && <Panel><Text c="dimmed">No allocation experiments have been registered.</Text></Panel>}</Stack></Box></SimpleGrid>
  </>;
}

const configurable = [
  ['calendar', 'Trading calendar', 'e.g. CME'], ['review_cadence', 'Review cadence', 'e.g. month-end'],
  ['staleness_days', 'Staleness days', 'number'], ['portfolio_volatility_budget', 'Portfolio volatility budget', 'decimal'],
  ['volatility_floor', 'Volatility floor', 'decimal'], ['gross_exposure_limit', 'Gross exposure limit', 'decimal'],
  ['margin_limit', 'Margin limit', 'decimal'], ['outage_procedure', 'Outage procedure', 'text'],
  ['decision_owner', 'Decision owner', 'name'], ['cash_balance', 'Cash balance', 'currency'],
  ['watch_window_observations', 'Watch window', 'observations'], ['watch_negative_fraction', 'Watch negative fraction', 'decimal'],
  ['false_alert_budget', 'False-alert budget', 'declared rate'],
] as const;

export function RegistryPage() {
  const dispatch = useAppDispatch();
  const snapshot = useAppSelector(state => state.portfolio.snapshot);
  const notice = useAppSelector(state => state.portfolio.notice);
  const error = useAppSelector(state => state.portfolio.error);
  const [settings, setSettings] = useState<Record<string, string | number>>({});
  const [strategy, setStrategy] = useState<string | null>(null);
  const [source, setSource] = useState('manual CSV import');
  const [csv, setCsv] = useState('event_time,availability_time,observation_type,net_return,equity,cash_flow,currency\n');
  const [qualified, setQualified] = useState(false);
  const [newVersion, setNewVersion] = useState({ strategy_id: '', name: '', version: 'v1', eligibility: 'Provisional', reviewer: '', selection_date: '', code_hash: '', objective: '', base_allocation: '', hard_drawdown_limit: '' });
  const [versionResult, setVersionResult] = useState<string | null>(null);
  const [review, setReview] = useState({ strategy_version_id: '', eligibility: 'Provisional', reviewer: '', evidence_strength: 'Unknown', selection_date: '', objective: '', evidence_snapshot: '{\n  "run_id": ""\n}', limitations: '' });
  const [reviewResult, setReviewResult] = useState<string | null>(null);
  const effective = { ...(snapshot?.settings ?? {}), ...settings };
  const save = () => dispatch(savePortfolioSettings({ ...Object.fromEntries(Object.entries(settings).map(([key, value]) => [key, value === '' ? null : value])), policy_state: qualified ? 'Approved for allocation proposals' : snapshot?.settings.policy_state })).then(() => void dispatch(fetchPortfolio()));
  const importRows = () => strategy && dispatch(importPortfolioObservations({ strategy_version_id: strategy, source, csv })).then(() => void dispatch(fetchPortfolio()));
  const registerVersion = async () => {
    setVersionResult(null);
    const payload: Record<string, unknown> = { strategy_id: newVersion.strategy_id, name: newVersion.name, version: newVersion.version, eligibility: newVersion.eligibility,
      base_allocation: newVersion.base_allocation === '' ? null : Number(newVersion.base_allocation), hard_drawdown_limit: newVersion.hard_drawdown_limit === '' ? null : Number(newVersion.hard_drawdown_limit) };
    if (newVersion.eligibility === 'Qualified') Object.assign(payload, { reviewer: newVersion.reviewer, selection_date: newVersion.selection_date, code_hash: newVersion.code_hash, acceptance_profile: { objective: newVersion.objective } });
    const response = await fetch('/api/portfolio/strategy-versions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const body = await response.json();
    if (!response.ok) { setVersionResult(body.detail ?? 'Registration failed'); return; }
    setVersionResult(`Registered immutable version ${body.id}`); void dispatch(fetchPortfolio());
  };
  const recordReview = async () => {
    setReviewResult(null);
    let evidence: Record<string, unknown>;
    try { evidence = JSON.parse(review.evidence_snapshot) as Record<string, unknown>; }
    catch { setReviewResult('Evidence snapshot must be valid JSON.'); return; }
    const response = await fetch('/api/portfolio/eligibility-assessments', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
      strategy_version_id: review.strategy_version_id, eligibility: review.eligibility, reviewer: review.reviewer,
      evidence_strength: review.evidence_strength, acceptance_profile: review.objective ? { objective: review.objective } : undefined,
      evidence_snapshot: evidence, limitations: review.limitations ? [review.limitations] : [], policy_version: snapshot?.settings.policy_version,
      selection_date: review.selection_date || undefined,
    }) });
    const body = await response.json();
    if (!response.ok) { setReviewResult(body.detail ?? 'Review failed'); return; }
    setReviewResult(`Recorded ${body.eligibility} assessment ${body.id}`); void dispatch(fetchPortfolio());
  };
  return <><Heading title="Data and strategy registry" description="Versioned settings, immutable strategy versions, typed imports, and explicit unsupported fields."
    action={<Button component="a" href="/api/portfolio/export?kind=strategies&format=json" variant="default" leftSection={<IconDownload size={16}/>}>Export registry</Button>}/>
    {notice && <Alert color="teal" mb="lg">{notice}</Alert>}{error && <Alert color="red" mb="lg">{error}</Alert>}
    <SimpleGrid cols={{ base: 1, lg: 2 }}><Panel><Group gap="xs"><IconSettings size={18}/><Text fw={600}>Portfolio configuration</Text></Group><Text c="dimmed" size="xs" mt={4}>Each save creates a new settings version. Blank investment fields stay unconfigured.</Text><SimpleGrid cols={{ base: 1, sm: 2 }} mt="md">{configurable.map(([key, label, placeholder]) => <TextInput key={key} label={label} placeholder={placeholder} value={String(effective[key] ?? '')} onChange={event => { const raw = event.currentTarget.value; setSettings(current => ({ ...current, [key]: ['staleness_days', 'portfolio_volatility_budget', 'volatility_floor', 'gross_exposure_limit', 'margin_limit', 'cash_balance', 'watch_window_observations', 'watch_negative_fraction', 'false_alert_budget'].includes(key) && raw !== '' ? Number(raw) : raw })); }}/>)}</SimpleGrid>
      <TextInput mt="sm" label="Policy version" value={String(effective.policy_version ?? '')} onChange={event => setSettings(current => ({ ...current, policy_version: event.currentTarget.value }))}/><Checkbox mt="md" checked={qualified} onChange={event => setQualified(event.currentTarget.checked)} label="I am recording this policy version as Approved for allocation proposals"/><Alert color="blue" mt="sm" title="Owner decision required">Approval is recorded explicitly. It should only be enabled after the declared evidence and forward-paper conditions are met.</Alert><Button mt="md" onClick={save}>Save new configuration version</Button></Panel>
    <Panel><Group gap="xs"><IconActivity size={18}/><Text fw={600}>CSV / JSON-compatible observation import</Text></Group><Select mt="md" searchable label="Exact strategy version" value={strategy} onChange={setStrategy} data={(snapshot?.strategies ?? []).map(item => ({ value: item.id, label: `${item.name} · ${item.version}` }))}/><TextInput mt="sm" label="Source identity" value={source} onChange={event => setSource(event.currentTarget.value)}/><Textarea mt="sm" minRows={11} autosize label="CSV rows" description="Required: event_time. Return rows require net_return or equity. availability_time defaults to event_time and should only be omitted when that is factually correct." value={csv} onChange={event => setCsv(event.currentTarget.value)}/><Button mt="md" disabled={!strategy} onClick={importRows}>Validate and import</Button><Alert color="yellow" mt="sm" icon={<IconAlertTriangle size={16}/>} title="Supported observation types">return, position, fill, market, cash_flow. Unknown values remain blank; monthly data does not create daily observations.</Alert></Panel></SimpleGrid>
    <Box mt="lg"><Panel><Text fw={600}>Register a new immutable strategy version</Text><Text c="dimmed" size="xs">Material code, universe, signal, or cost-model changes require another version. Existing versions are never edited.</Text><SimpleGrid cols={{ base: 1, sm: 4 }} mt="md"><TextInput label="Strategy ID" value={newVersion.strategy_id} onChange={event => setNewVersion(current => ({ ...current, strategy_id: event.currentTarget.value }))}/><TextInput label="Name" value={newVersion.name} onChange={event => setNewVersion(current => ({ ...current, name: event.currentTarget.value }))}/><TextInput label="Version" value={newVersion.version} onChange={event => setNewVersion(current => ({ ...current, version: event.currentTarget.value }))}/><Select label="Research eligibility" value={newVersion.eligibility} data={['Provisional', 'Qualified', 'Rejected', 'Retired']} onChange={value => setNewVersion(current => ({ ...current, eligibility: value ?? 'Provisional' }))}/></SimpleGrid>{newVersion.eligibility === 'Qualified' && <SimpleGrid cols={{ base: 1, sm: 4 }} mt="sm"><TextInput label="Reviewer" value={newVersion.reviewer} onChange={event => setNewVersion(current => ({ ...current, reviewer: event.currentTarget.value }))}/><TextInput label="Selection date" type="date" value={newVersion.selection_date} onChange={event => setNewVersion(current => ({ ...current, selection_date: event.currentTarget.value }))}/><TextInput label="Code/config SHA-256" value={newVersion.code_hash} onChange={event => setNewVersion(current => ({ ...current, code_hash: event.currentTarget.value }))}/><TextInput label="Predeclared objective" value={newVersion.objective} onChange={event => setNewVersion(current => ({ ...current, objective: event.currentTarget.value }))}/></SimpleGrid>}<SimpleGrid cols={{ base: 1, sm: 2 }} mt="sm"><TextInput label="Base allocation (decimal, optional)" value={newVersion.base_allocation} onChange={event => setNewVersion(current => ({ ...current, base_allocation: event.currentTarget.value }))}/><TextInput label="Hard drawdown limit (positive decimal)" value={newVersion.hard_drawdown_limit} onChange={event => setNewVersion(current => ({ ...current, hard_drawdown_limit: event.currentTarget.value }))}/></SimpleGrid>{versionResult && <Alert color={versionResult.startsWith('Registered') ? 'teal' : 'red'} mt="sm">{versionResult}</Alert>}<Button mt="md" disabled={!newVersion.strategy_id || !newVersion.name || !newVersion.version} onClick={() => void registerVersion()}>Register version</Button></Panel></Box>
    <Box mt="lg"><Panel><Text fw={600}>Record research eligibility assessment</Text><Text c="dimmed" size="xs">This appends a reviewer decision to the exact version without changing its immutable definition or prior assessments.</Text><SimpleGrid cols={{ base: 1, sm: 5 }} mt="md"><Select searchable label="Exact strategy version" value={review.strategy_version_id} data={(snapshot?.strategies ?? []).map(item => ({ value: item.id, label: `${item.name} · ${item.version}` }))} onChange={value => setReview(current => ({ ...current, strategy_version_id: value ?? '' }))}/><Select label="Decision" value={review.eligibility} data={['Provisional', 'Qualified', 'Rejected', 'Retired']} onChange={value => setReview(current => ({ ...current, eligibility: value ?? 'Provisional' }))}/><TextInput label="Reviewer" value={review.reviewer} onChange={event => setReview(current => ({ ...current, reviewer: event.currentTarget.value }))}/><Select label="Evidence strength" value={review.evidence_strength} data={['Unknown', 'Limited', 'Moderate', 'Strong']} onChange={value => setReview(current => ({ ...current, evidence_strength: value ?? 'Unknown' }))}/><TextInput type="date" label="Original selection date" value={review.selection_date} onChange={event => setReview(current => ({ ...current, selection_date: event.currentTarget.value }))}/></SimpleGrid><TextInput mt="sm" label="Predeclared acceptance objective" value={review.objective} onChange={event => setReview(current => ({ ...current, objective: event.currentTarget.value }))}/><SimpleGrid cols={{ base: 1, sm: 2 }} mt="sm"><Textarea autosize minRows={5} label="Evidence snapshot (JSON)" value={review.evidence_snapshot} onChange={event => setReview(current => ({ ...current, evidence_snapshot: event.currentTarget.value }))}/><Textarea autosize minRows={5} label="Limitations" value={review.limitations} onChange={event => setReview(current => ({ ...current, limitations: event.currentTarget.value }))}/></SimpleGrid>{reviewResult && <Alert color={reviewResult.startsWith('Recorded') ? 'teal' : 'red'} mt="sm">{reviewResult}</Alert>}<Button mt="md" disabled={!review.strategy_version_id || !review.reviewer} onClick={() => void recordReview()}>Append assessment</Button></Panel></Box>
    <Box mt="lg"><Panel><Text fw={600} mb="sm">Registered immutable versions</Text><ScrollArea><Table miw={950}><Table.Thead><Table.Tr><Table.Th>Name</Table.Th><Table.Th>Version ID</Table.Th><Table.Th>Eligibility</Table.Th><Table.Th>Evidence</Table.Th><Table.Th>Code</Table.Th><Table.Th>Coverage</Table.Th></Table.Tr></Table.Thead><Table.Tbody>{snapshot?.strategies.map(item => <Table.Tr key={item.id}><Table.Td>{item.name}</Table.Td><Table.Td className="mono"><Text size="xs">{item.id}</Text></Table.Td><Table.Td><BadgeState value={item.eligibility}/></Table.Td><Table.Td>{item.evidence_strength}</Table.Td><Table.Td><Text size="xs">immutable fingerprint</Text></Table.Td><Table.Td>{item.days_observed} current rows</Table.Td></Table.Tr>)}</Table.Tbody></Table></ScrollArea></Panel></Box>
  </>;
}

export function PortfolioLoadingNotice() {
  const { snapshot, error } = useAppSelector(state => state.portfolio);
  if (snapshot || error) return null;
  return <Alert color="blue" icon={<IconActivity size={16}/>}>Loading the portfolio assessment engine…</Alert>;
}
