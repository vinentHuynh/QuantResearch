import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  ActionIcon, Alert, Badge, Box, Button, Code, Container, Group, Loader, MultiSelect,
  NumberInput, Paper, Radio, ScrollArea, Select, SimpleGrid, Stack, Switch, Table,
  Text, TextInput, ThemeIcon, Title, Tooltip,
} from '@mantine/core';
import {
  IconAlertTriangle, IconArrowLeft, IconArrowRight, IconCheck, IconChevronDown,
  IconChevronRight, IconClock, IconCopy, IconDatabase, IconDownload, IconRefresh,
  IconShieldCheck, IconTrendingDown, IconTrendingUp,
} from '@tabler/icons-react';
import { bookReturns, correlationLabels, correlations, experiments, months, sources, strategies, type Strategy } from './data';
import { fetchCharts, fetchRun, fetchRunnerCatalog, fetchRuns, navigate, openStrategy, refreshData, selectRun, setFilter, setImportKind, startRun, toggleStrategy, useAppDispatch, useAppSelector, type AnalysisRun, type RunnerParameter, type View } from './store';

const fmtPct = (value: number) => `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(1)}%`;
const money = (value: number) => `$${value.toLocaleString('en-US')}`;
const proposedAllocated = strategies.reduce((sum, item) => sum + item.proposedRisk, 0);
const reserved = 6;
const unused = 100 - proposedAllocated - reserved;

function StatusBadge({ value, kind = 'check', tone }: { value: string; kind?: 'check' | 'eligibility' | 'health'; tone?: string }) {
  let color = 'gray';
  let variant: 'light' | 'outline' | 'filled' = 'light';
  const normalized = (tone ?? value).toLowerCase().replace('health ', '');
  if (['pass', 'ok', 'eligible', 'supported'].includes(normalized)) color = 'teal';
  if (['watch', 'provisional', 'inconclusive'].includes(normalized)) color = 'yellow';
  if (['fail', 'breach', 'ineligible', 'block'].includes(normalized)) { color = 'red'; variant = 'filled'; }
  if (['enabled'].includes(normalized)) { color = 'dark'; variant = 'filled'; }
  if (['unknown', 'reference', 'disabled'].includes(normalized)) variant = 'outline';
  return <Badge color={color} variant={variant} radius="xs" size="sm" className={`status ${kind}`}>{value}</Badge>;
}

function Panel({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <Paper withBorder className={`panel ${className}`}>{children}</Paper>;
}

function Kpi({ label, value, detail, icon }: { label: string; value: string; detail: string; icon?: ReactNode }) {
  return (
    <Panel className="kpi">
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Box><Text className="eyebrow">{label}</Text><Text className="kpiValue">{value}</Text></Box>
        {icon && <ThemeIcon variant="light" color="teal" size={32}>{icon}</ThemeIcon>}
      </Group>
      <Text c="dimmed" size="xs">{detail}</Text>
    </Panel>
  );
}

const tabs: { id: Exclude<View, 'detail'>; label: string }[] = [
  { id: 'portfolio', label: 'Portfolio' }, { id: 'risk', label: 'Portfolio risk' },
  { id: 'research', label: 'Research' }, { id: 'data', label: 'Data' }, { id: 'proposal', label: 'Proposal' },
  { id: 'runner', label: 'Run analysis' },
];

function Header() {
  const dispatch = useAppDispatch();
  const { view, lastRefresh } = useAppSelector((state) => state.dashboard);
  return <>
    <Box className="topbar">
      <Container size={1420} className="topbarInner">
        <Group gap="sm"><ThemeIcon color="teal" variant="white" size={30}><IconShieldCheck size={19}/></ThemeIcon><Text className="brand">Strategy Health <span>& Allocation</span></Text></Group>
        <Group gap="xl" className="metadata">
          <Box><Text>Policy</Text><strong>v2.3</strong></Box>
          <Box><Text>Computed</Text><strong>{lastRefresh}</strong></Box>
          <Badge leftSection={<span className="freshDot"/>} variant="outline" color="gray">inputs 1 d old</Badge>
        </Group>
      </Container>
    </Box>
    <Box className="navWrap">
      <Container size={1420}><Group gap={30} wrap="nowrap" className="navTabs">
        {tabs.map((tab) => <button key={tab.id} className={(view === tab.id || (view === 'detail' && tab.id === 'portfolio')) ? 'active' : ''} onClick={() => dispatch(navigate(tab.id))}>{tab.label}</button>)}
      </Group></Container>
    </Box>
  </>;
}

function MiniLineChart() {
  const cumulative = bookReturns.reduce<number[]>((acc, value) => [...acc, value + (acc.at(-1) ?? 0)], []);
  const min = Math.min(...cumulative, 0), max = Math.max(...cumulative, 1);
  const points = cumulative.map((v, i) => `${(i/(cumulative.length-1))*100},${82-((v-min)/(max-min))*72}`).join(' ');
  let peak = -Infinity;
  const dd = cumulative.map((v) => { peak = Math.max(peak, v); return v - peak; });
  const ddMin = Math.min(...dd, -1);
  const ddPoints = dd.map((v, i) => `${(i/(dd.length-1))*100},${3+(v/ddMin)*32}`).join(' ');
  return <Panel className="chartPanel">
    <Group justify="space-between" mb="xs"><Text fw={600}>Book equity · % of starting capital</Text><Text c="dimmed" size="xs">Jan–Sep 2026 · live returns</Text></Group>
    <svg viewBox="0 0 100 88" preserveAspectRatio="none" className="equityChart">
      {[18,38,58,78].map(y => <line key={y} x1="0" x2="100" y1={y} y2={y} className="gridLine"/>)}
      <polygon points={`0,84 ${points} 100,84`} className="area"/><polyline points={points} className="equityLine"/>
    </svg>
    <Group justify="space-between" className="chartLabels">{months.map(m => <span key={m}>{m}</span>)}</Group>
    <Group justify="space-between" mt="md" mb={4}><Text fw={600} size="sm">Drawdown from peak</Text><Text c="dimmed" size="xs">current −0.8% · 5 months under water</Text></Group>
    <svg viewBox="0 0 100 38" preserveAspectRatio="none" className="ddChart"><line x1="0" x2="100" y1="2" y2="2" className="gridLine"/><polygon points={`0,2 ${ddPoints} 100,2`} className="ddArea"/><polyline points={ddPoints} className="ddLine"/></svg>
  </Panel>;
}

function Budget() {
  const items = [
    { label: 'Allocated', value: proposedAllocated, color: '#34877f', detail: '4 sleeves funded at proposed weights' },
    { label: 'Reserved', value: reserved, color: '#a9d8d0', detail: 'MNQ Asia-Fill pending registration' },
    { label: 'Unused', value: unused, color: '#e4e8e7', detail: 'freed by removal and cost reduction' },
  ];
  return <Panel className="budgetPanel">
    <Group justify="space-between" mb="sm"><Text fw={600}>Risk budget · $100,000 at τ 12%</Text><Text size="xs" c="dimmed">calculation ALLOC-2026-09-06-01</Text></Group>
    <div className="budgetBar">{items.map(i => <Tooltip key={i.label} label={`${i.label} ${i.value}%`}><div style={{ width: `${i.value}%`, background: i.color }}/></Tooltip>)}</div>
    <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="md" mt="sm">{items.map(i => <Group key={i.label} gap="xs" wrap="nowrap"><span className="legend" style={{background:i.color}}/><Box><Text size="sm"><strong>{i.value}%</strong> {i.label.toLowerCase()}</Text><Text c="dimmed" size="xs">{i.detail}</Text></Box></Group>)}</SimpleGrid>
  </Panel>;
}

const findings = [
  ['COST LIMIT','MNQ Overnight over its cost limit','Measured 0.147 SR/yr against 0.100. Reduce to 8%; do not pause.','mnq-on','fail'],
  ['NO EDGE','MCL Trend fails the evidence check','Negative net Sharpe at all speeds and in both research windows.','mcl-trend','fail'],
  ['WATCH','MGC ORB 92 days under water','Depth −24.6% against a −27% one-year reference.','mgc-orb','watch'],
  ['PROVISIONAL','MNQ Asia-Fill has no post-registration data','Six percent is reserved; live checks remain Unknown.','mnq-asia','unknown'],
] as const;

function Findings() {
  const dispatch = useAppDispatch();
  return <Panel className="findings"><Text fw={600} mb="xs">Findings · Sep 2016–05 Sep 2026</Text><Stack gap={0}>{findings.map(([kind,title,body,id,state]) => <button key={id} className="finding" onClick={() => dispatch(openStrategy(id))}><Group gap="xs"><StatusBadge value={kind} tone={state}/><Text fw={600} size="sm">{title}</Text></Group><Text size="xs" mt={5}>{body}</Text><Text c="dimmed" size="xs" mt={3}>Evidence and response details →</Text></button>)}</Stack></Panel>;
}

function CheckCards({ strategy, compact = false }: { strategy: Strategy; compact?: boolean }) {
  return <SimpleGrid cols={{ base: 1, sm: compact ? 2 : 2, lg: compact ? 2 : 4 }} spacing="md">{strategy.checks.map(check => <Box key={check.name} className={`checkCard ${check.state}`}>
    <Group justify="space-between" wrap="nowrap"><Text fw={600} size="sm">{check.name}</Text><StatusBadge value={check.state.toUpperCase()}/></Group>
    <Text className="mono" size="xs" mt={6}>{check.observed}</Text><Text c="dimmed" size="xs">Limit: {check.limit}</Text>
    <Text size="xs" mt={6}>{check.rationale}</Text><Text size="xs" c="teal.8" mt={6}><strong>Response:</strong> {check.response}</Text>
  </Box>)}</SimpleGrid>;
}

function StrategyTable() {
  const dispatch = useAppDispatch();
  const { expandedStrategy, filter } = useAppSelector((state) => state.dashboard);
  const filtered = strategies.filter(s => filter === 'All strategies' || (filter === 'Actionable' && (s.health !== 'OK' || s.eligibility !== 'Eligible')) || (filter === 'Eligible' && s.eligibility === 'Eligible') || (filter === 'Watch / Breach' && ['Watch','Breach'].includes(s.health)));
  return <>
    <Group justify="space-between" mb="sm"><Group gap="sm"><Title order={3}>Strategies</Title><Text size="xs" c="dimmed">{filtered.length} of {strategies.length} versions</Text></Group><Select size="xs" w={170} value={filter} data={['All strategies','Actionable','Eligible','Watch / Breach']} onChange={(value) => value && dispatch(setFilter(value as typeof filter))}/></Group>
    <Panel className="tablePanel"><ScrollArea><Table verticalSpacing="sm" horizontalSpacing="sm" highlightOnHover miw={1020}>
      <Table.Thead><Table.Tr><Table.Th>Strategy · version</Table.Th><Table.Th>Eligibility</Table.Th><Table.Th>Health</Table.Th><Table.Th>Reason</Table.Th><Table.Th ta="right">Recent net</Table.Th><Table.Th ta="right">Drawdown</Table.Th><Table.Th ta="right">Risk</Table.Th><Table.Th/></Table.Tr></Table.Thead>
      <Table.Tbody>{filtered.map(s => {
        const open = expandedStrategy === s.id;
        return <Fragment key={s.id}><Table.Tr className="strategyRow" onClick={() => dispatch(openStrategy(s.id))}>
          <Table.Td><Text fw={600}>{s.name}</Text><Text c="dimmed" size="xs">{s.version} · {s.instrument} · {s.family}</Text></Table.Td>
          <Table.Td><StatusBadge value={s.eligibility} kind="eligibility"/></Table.Td><Table.Td><StatusBadge value={s.health} kind="health"/></Table.Td>
          <Table.Td maw={330}><Text size="xs" lineClamp={2}>{s.reason}</Text></Table.Td>
          <Table.Td ta="right"><Text className="mono" size="sm">MTD {fmtPct(s.months[8])}</Text><Text c="dimmed" size="xs">Aug {fmtPct(s.months[7])} · YTD {fmtPct(s.ytd)}</Text></Table.Td>
          <Table.Td ta="right"><Text className="mono" size="sm">{fmtPct(s.drawdown)}</Text><Text c="dimmed" size="xs">{s.underwater}</Text></Table.Td>
          <Table.Td ta="right"><Text className="mono" size="sm">{s.currentRisk}% → <strong>{s.proposedRisk}%</strong></Text><Text c="dimmed" size="xs">{s.proposedRisk === s.currentRisk ? 'unchanged' : `${s.proposedRisk > s.currentRisk ? '+' : '−'}${Math.abs(s.proposedRisk-s.currentRisk)} pts`}</Text></Table.Td>
          <Table.Td><ActionIcon variant="subtle" color="gray" onClick={(event) => {event.stopPropagation(); dispatch(toggleStrategy(s.id));}}>{open ? <IconChevronDown size={17}/> : <IconChevronRight size={17}/>}</ActionIcon></Table.Td>
        </Table.Tr>{open && <Table.Tr><Table.Td colSpan={8} className="expanded"><CheckCards strategy={s} compact/></Table.Td></Table.Tr>}</Fragment>;
      })}</Table.Tbody>
    </Table></ScrollArea></Panel>
  </>;
}

function Portfolio() {
  return <><Budget/><SimpleGrid cols={{base:1,xs:2,md:5}} spacing="md" my="lg">
    <Kpi label="Book NAV" value="$102,800" detail="YTD +2.8% net" icon={<IconTrendingUp size={18}/>}/><Kpi label="Current drawdown" value="−0.8%" detail="5 months under water" icon={<IconTrendingDown size={18}/>}/><Kpi label="Deepest DD, 12 mo" value="−6.4%" detail="Nov 2025 · reference −14%"/><Kpi label="Realised vol" value="10.4%" detail="0.87× τ · 60-day window"/><Kpi label="Checks failing" value="3 of 24" detail="2 evidence · 1 cost" icon={<IconAlertTriangle size={18}/>}/>
  </SimpleGrid><SimpleGrid cols={{base:1,lg:3}} spacing="lg" mb="xl"><Box className="span2"><MiniLineChart/></Box><Findings/></SimpleGrid><StrategyTable/></>;
}

function MonthlyBars({ strategy }: { strategy: Strategy }) {
  const max = Math.max(...strategy.months.map(Math.abs), 1);
  return <Panel><Group justify="space-between" mb="md"><Text fw={600}>Monthly net return · % of sleeve capital</Text><Text c="dimmed" size="xs">Jan–Sep 2026</Text></Group><div className="bars">{strategy.months.map((v,i) => <Tooltip key={months[i]} label={`${months[i]}: ${fmtPct(v)} · ${strategy.trades[i]} trades`}><div className="barCol"><div className="barPlot"><div className={`bar ${v >= 0 ? 'positive':'negative'}`} style={{height:`${Math.abs(v)/max*46}%`, [v >= 0 ? 'bottom':'top']:'50%'}}/></div><Text size="xs" c="dimmed">{months[i]}</Text><Text size="xs" className="mono">{fmtPct(v)}</Text></div></Tooltip>)}</div></Panel>;
}

function KeyValues({ title, rows }: { title: string; rows: [string,string][] }) {
  return <Panel><Text fw={600} mb="xs">{title}</Text><Stack gap={0}>{rows.map(([key,value]) => <Group key={key} justify="space-between" wrap="nowrap" className="kv"><Text c="dimmed" size="xs">{key}</Text><Text size="xs" ta="right" className="mono">{value}</Text></Group>)}</Stack></Panel>;
}

function StrategyDetail() {
  const dispatch = useAppDispatch(); const selected = useAppSelector(s => s.dashboard.selectedStrategy);
  const strategy = strategies.find(s => s.id === selected) ?? strategies[0];
  return <>
    <Button variant="subtle" color="gray" size="xs" leftSection={<IconArrowLeft size={15}/>} onClick={() => dispatch(navigate('portfolio'))} mb="xs">All strategies</Button>
    <Group justify="space-between" align="flex-end" mb="xs"><Box><Text className="eyebrow">{strategy.family} · {strategy.instrument}</Text><Group><Title order={2}>{strategy.name}</Title><Text c="dimmed" className="mono">{strategy.version}</Text><StatusBadge value={strategy.eligibility}/><StatusBadge value={`Health ${strategy.health}`}/></Group></Box><Group gap={5} className="peerNav">{strategies.map(s => <Button key={s.id} size="compact-xs" variant={s.id === strategy.id ? 'filled':'default'} onClick={() => dispatch(openStrategy(s.id))}>{s.short}</Button>)}</Group></Group>
    <Text size="sm" maw={860} mb="lg">{strategy.reason}</Text>
    <SimpleGrid cols={{base:1,lg:3}} spacing="lg"><Box className="span2"><MonthlyBars strategy={strategy}/></Box><KeyValues title="Current condition" rows={strategy.condition}/></SimpleGrid>
    <SimpleGrid cols={{base:1,md:2}} spacing="lg" my="lg"><KeyValues title="Qualification evidence" rows={strategy.evidence}/><Panel><Text fw={600} mb="md">Execution</Text><SimpleGrid cols={2}>{strategy.execution.map(([k,v,sub]) => <Box key={k}><Text className="eyebrow">{k}</Text><Text size="xl" className="mono">{v}</Text><Text size="xs" c="dimmed">{sub}</Text></Box>)}</SimpleGrid></Panel></SimpleGrid>
    <SimpleGrid cols={{base:1,md:2}} spacing="lg" mb="lg"><Panel><Text fw={600}>Allocation change</Text><Group my="sm"><Box><Text className="eyebrow">Risk now</Text><Text size="xl" className="mono">{strategy.currentRisk}%</Text></Box><IconArrowRight color="#85918f"/><Box><Text className="eyebrow">Proposed</Text><Text size="xl" fw={700} className="mono">{strategy.proposedRisk}%</Text></Box><Text c="dimmed" size="xs" ml="auto">{strategy.contracts} contracts</Text></Group><Text size="xs">{strategy.allocationReason}</Text></Panel><Panel><Text fw={600} mb="xs">Route back to allocation</Text>{(strategy.restart.length ? strategy.restart : ['No restart conditions: the sleeve is fully allocated.']).map((line,i) => <Group key={line} wrap="nowrap" align="flex-start" mb={7}><Text c="dimmed" size="xs">{strategy.restart.length ? i+1 : '—'}</Text><Text size="xs">{line}</Text></Group>)}</Panel></SimpleGrid>
    <Text fw={600} mb="sm">Checks</Text><CheckCards strategy={strategy}/>
  </>;
}

function Risk() {
  const exposures = [['MNQ','MNQ-T + MNQ-ON + Asia reserve',44,40],['MGC','MGC-T + MGC-ORB',38,40],['MCL','MCL-T · removed in proposal',12,40],['Overnight','18:00–06:00 ET clock window',18,25]] as const;
  return <><Title order={2}>Portfolio risk</Title><Text size="xs" c="dimmed" mb="lg">Daily sleeve returns · Sep 2016–05 Sep 2026 · 2,494 observations</Text><SimpleGrid cols={{base:1,lg:2}} spacing="lg"><Panel><Text fw={600} mb="md">Sleeve correlation</Text><div className="corrGrid"><div/>{correlationLabels.map(h => <Text key={h} size="xs" ta="center">{h}</Text>)}{correlations.flatMap((row,i) => [<Text key={`h${i}`} size="xs" ta="right" pr={6}>{correlationLabels[i]}</Text>, ...row.map((v,j) => <Tooltip key={`${i}-${j}`} label={`${correlationLabels[i]} × ${correlationLabels[j]} · ${v.toFixed(2)}`}><div className="corrCell" style={{background:`color-mix(in srgb, #2f7d75 ${Math.max(7,Math.abs(v)*100)}%, #f4f5f3)`,color:Math.abs(v)>.75?'white':'#163735'}}>{v.toFixed(2)}</div></Tooltip>)])}</div></Panel><Stack gap="lg"><Panel><Text fw={600} mb="md">Instrument exposure · share of book risk</Text>{exposures.map(([label,detail,pct,cap]) => <Box key={label} mb="md"><Group justify="space-between"><Box><Text fw={600} size="sm">{label}</Text><Text c="dimmed" size="xs">{detail}</Text></Box><Text className="mono" size="sm">{pct}% / cap {cap}%</Text></Group><div className="riskBar"><div style={{width:`${pct}%`}}/><span style={{left:`${cap}%`}}/></div></Box>)}</Panel><Panel><Text fw={600} mb="sm">Observations</Text><Stack gap="sm">{['MNQ currently carries 44% of book risk, above its 40% instrument cap. The proposal lowers it to 32%.','MGC Trend and MGC ORB correlate +0.62. Separate strategies can still behave like one bet in a drawdown.','Reducing MNQ Overnight removes diversification, so the freed budget remains unused.'].map((x,i)=><Box key={x} className={`note note${i}`}><Text size="xs">{x}</Text><Text size="xs" c="dimmed">basis: overlapping daily observations</Text></Box>)}</Stack></Panel></Stack></SimpleGrid></>;
}

function Research() {
  return <><Title order={2}>Research</Title><Text size="xs" c="dimmed" maw={970} mb="lg">Each policy is replayed on the same daily returns. Δ SR is a paired difference against the reference with a 95% interval from a 20-day block bootstrap; evidence and policy status are intentionally separate.</Text><Panel className="tablePanel"><ScrollArea><Table miw={1000} verticalSpacing="sm"><Table.Thead><Table.Tr><Table.Th>Policy</Table.Th><Table.Th ta="right">Ann. net return</Table.Th><Table.Th ta="right">SR net</Table.Th><Table.Th ta="right">Δ SR (95%)</Table.Th><Table.Th ta="right">Vol / τ</Table.Th><Table.Th ta="right">1-yr DD</Table.Th><Table.Th>Evidence</Table.Th><Table.Th>Policy</Table.Th></Table.Tr></Table.Thead><Table.Tbody>{experiments.map(e => <Table.Tr key={e[0]}><Table.Td><Text fw={600} size="sm">{e[0]}</Text><Text c="dimmed" size="xs">{e[1]}</Text></Table.Td><Table.Td ta="right" className="mono">{e[2]}</Table.Td><Table.Td ta="right" className="mono">{e[3]}</Table.Td><Table.Td ta="right"><Text className="mono" size="sm">{e[4]}</Text><Text c="dimmed" size="xs">{e[5]}</Text></Table.Td><Table.Td ta="right" className="mono">{e[6]}</Table.Td><Table.Td ta="right" className="mono">{e[7]}</Table.Td><Table.Td><StatusBadge value={e[8]}/></Table.Td><Table.Td><StatusBadge value={e[9]}/></Table.Td></Table.Tr>)}</Table.Tbody></Table></ScrollArea></Panel><SimpleGrid cols={{base:1,md:3}} spacing="lg" mt="lg">{[['How to read Δ SR','Paired differences, not overlapping intervals','Each difference is bootstrapped on the same days, avoiding overstated uncertainty.'],['Enabled without evidence','The cost rule is a constraint','The overnight reduction is enabled because measured cost breaches a limit, not because Δ SR proves improvement.'],['Exposure control','Less risk is not free','The 0.7× control leaves Sharpe unchanged while giving up 1.7 points of annual net return.']].map(n => <Panel key={n[0]}><Text className="eyebrow">{n[0]}</Text><Text fw={600} my={5}>{n[1]}</Text><Text size="xs">{n[2]}</Text></Panel>)}</SimpleGrid></>;
}

function DataPage() {
  const dispatch = useAppDispatch(); const { importKind } = useAppSelector(s => s.dashboard); const [message,setMessage] = useState('');
  return <><Group justify="space-between" mb="lg"><Box><Title order={2}>Data</Title><Text c="dimmed" size="xs">calculation ALLOC-2026-09-06-01 · policy v2.3</Text></Box><Button leftSection={<IconRefresh size={16}/>} onClick={() => {dispatch(refreshData());setMessage('All source checks recomputed.');}}>Refresh all</Button></Group>{message && <Paper withBorder p="xs" mb="md" bg="teal.0"><Text size="xs" c="teal.9">{message}</Text></Paper>}<SimpleGrid cols={{base:1,lg:3}} spacing="lg"><Box className="span2"><Panel className="tablePanel"><ScrollArea><Table miw={800} verticalSpacing="sm"><Table.Thead><Table.Tr><Table.Th>Source</Table.Th><Table.Th>Kind</Table.Th><Table.Th ta="right">Rows</Table.Th><Table.Th ta="right">Covers to</Table.Th><Table.Th>Age</Table.Th><Table.Th>Validation</Table.Th><Table.Th/></Table.Tr></Table.Thead><Table.Tbody>{sources.map(s => <Table.Tr key={s[0]}><Table.Td><Text className="mono" size="xs">{s[0]}</Text><Text c="dimmed" size="xs">{s[1]}</Text></Table.Td><Table.Td><Text size="xs">{s[2]}</Text></Table.Td><Table.Td ta="right" className="mono">{s[3]}</Table.Td><Table.Td ta="right" className="mono">{s[4]}</Table.Td><Table.Td><StatusBadge value={s[5]}/></Table.Td><Table.Td><Text size="xs" c={s[6] === 'OK' ? 'dimmed':'red.8'}>{s[6]}</Text></Table.Td><Table.Td><Button variant="subtle" size="compact-xs" onClick={() => setMessage(`${s[0]} queued for re-import.`)}>Re-import</Button></Table.Td></Table.Tr>)}</Table.Tbody></Table></ScrollArea></Panel><Text fw={600} mt="lg" mb="sm">Decision history</Text><Panel><Stack gap={0}>{['Proposal generated: MCL removed and MNQ Overnight reduced 18% → 8%.','Cost check on MNQ Overnight moved pass → fail at 0.147 SR/yr.','Policy response changed from Pause to Reduce-to-feasible.','MNQ Asia-Fill imported as paper and recorded Provisional.'].map((x,i)=><Group key={x} wrap="nowrap" className="history"><Text className="mono" size="xs" c="dimmed">{['06 Sep 08:14','04 Sep 17:02','02 Sep 09:30','12 Aug 11:47'][i]}</Text><Text size="xs">{x}</Text></Group>)}</Stack></Panel></Box><Stack gap="lg"><Panel><Text fw={600} mb="sm">Import a run</Text><TextInput label="Results file or directory" value="reports/mnq_asia_fill_strategy/" readOnly classNames={{input:'mono'}}/><TextInput label="Attach to" value="MNQ Asia-Fill · v1.0" readOnly mt="sm"/><Radio.Group value={importKind} onChange={value => dispatch(setImportKind(value as typeof importKind))} label="Treat as" mt="sm"><Group mt={5}>{['Live','Backtest','Paper'].map(x=><Radio key={x} value={x} label={x}/>)}</Group></Radio.Group><Button fullWidth mt="md" onClick={() => setMessage(`Imported as ${importKind}; checks recomputed in preview state.`)}>Import & recompute</Button><Text c="dimmed" size="xs" mt="xs">This preview does not place broker orders.</Text></Panel><Panel><Text fw={600} mb="sm">Blocking conditions</Text>{[['BLOCK','Correlation reference is 39 days stale.'],['BLOCK','Asia-Fill has no post-registration rows.'],['OK','No missing exchange sessions.'],['OK','Live trades reconcile to broker confirmations.']].map(([mark,text])=><Group key={text} wrap="nowrap" align="flex-start" mb="sm"><StatusBadge value={mark}/><Text size="xs">{text}</Text></Group>)}</Panel></Stack></SimpleGrid></>;
}

function ParameterField({ parameter, value, onChange }: { parameter: RunnerParameter; value: unknown; onChange: (value: unknown) => void }) {
  const common = { label: parameter.label, description: parameter.help };
  if (parameter.kind === 'boolean') return <Switch {...common} checked={Boolean(value)} onChange={event => onChange(event.currentTarget.checked)}/>;
  if (parameter.kind === 'number' || parameter.kind === 'integer') return <NumberInput {...common} value={typeof value === 'number' ? value : ''} min={parameter.minimum ?? undefined} max={parameter.maximum ?? undefined} decimalScale={parameter.kind === 'integer' ? 0 : undefined} onChange={onChange}/>;
  if (parameter.kind === 'select') return <Select {...common} value={String(value ?? '')} data={parameter.choices} allowDeselect={!parameter.required} onChange={onChange}/>;
  if (parameter.kind === 'multiselect') return <MultiSelect {...common} value={Array.isArray(value) ? value.map(String) : []} data={parameter.choices} searchable onChange={onChange}/>;
  return <TextInput {...common} type={parameter.kind === 'date' ? 'date' : parameter.kind === 'time' ? 'time' : 'text'} value={String(value ?? '')} onChange={event => onChange(event.currentTarget.value)}/>;
}

type ArtifactPreviewValue = { kind: 'table'; columns: string[]; rows: Record<string,string>[]; truncated: boolean } | { kind: 'json' | 'text'; value: unknown };

function TinyResultChart({ rows, columns }: { rows: Record<string,string>[]; columns: string[] }) {
  const numericColumns = useMemo(() => columns.filter(column => rows.some(row => row[column] !== '' && Number.isFinite(Number(row[column])))), [columns, rows]);
  const [yColumn, setYColumn] = useState(numericColumns.at(-1) ?? '');
  useEffect(() => { if (!numericColumns.includes(yColumn)) setYColumn(numericColumns.at(-1) ?? ''); }, [numericColumns, yColumn]);
  const values = rows.map(row => Number(row[yColumn])).filter(Number.isFinite);
  if (!values.length) return <Text c="dimmed" size="sm">This file has no numeric series to chart.</Text>;
  const min = Math.min(...values), max = Math.max(...values); const span = max - min || 1;
  const points = values.map((value,index) => `${values.length === 1 ? 50 : index/(values.length-1)*100},${78-(value-min)/span*70}`).join(' ');
  return <><Select label="Y-axis" size="xs" w={240} data={numericColumns} value={yColumn} onChange={value => value && setYColumn(value)} mb="sm"/><svg viewBox="0 0 100 82" preserveAspectRatio="none" className="resultChart">{[8,25,42,59,78].map(y=><line key={y} x1="0" x2="100" y1={y} y2={y} className="gridLine"/>)}<polyline points={points} className="equityLine"/></svg><Group justify="space-between"><Text size="xs" c="dimmed">{min.toLocaleString()}</Text><Text size="xs" c="dimmed">{yColumn} · {values.length} rows</Text><Text size="xs" c="dimmed">{max.toLocaleString()}</Text></Group></>;
}

function ArtifactPreview({ run }: { run: AnalysisRun }) {
  const [artifactName, setArtifactName] = useState(run.artifacts[0]?.name ?? '');
  const [mode, setMode] = useState<'table'|'chart'|'raw'>('table');
  const [preview, setPreview] = useState<ArtifactPreviewValue | null>(null);
  const [loading, setLoading] = useState(false);
  const artifact = useMemo(() => run.artifacts.find(item => item.name === artifactName) ?? run.artifacts[0], [artifactName, run.artifacts]);
  useEffect(() => {
    if (!artifact || artifact.kind === 'image' || artifact.kind === 'html' || artifact.kind === 'file') { setPreview(null); return; }
    setLoading(true);
    fetch(`/api/runs/${run.id}/preview/${artifact.name}`).then(response => response.ok ? response.json() : Promise.reject(new Error('Preview unavailable'))).then(setPreview).catch(() => setPreview(null)).finally(() => setLoading(false));
  }, [run.id, artifact]);
  if (!run.artifacts.length) return <Text c="dimmed" size="sm">The run produced no recognized result files.</Text>;
  return <>
    <Group mb="md" align="flex-end"><Select label="Result file" searchable value={artifact?.name} data={run.artifacts.map(item => ({value:item.name,label:`${item.name} · ${item.kind}`}))} onChange={value => value && setArtifactName(value)} flex={1}/>{artifact?.kind === 'table' && <Select label="View" value={mode} data={[{value:'table',label:'Table'},{value:'chart',label:'Line chart'},{value:'raw',label:'Raw JSON'}]} onChange={value => setMode((value ?? 'table') as typeof mode)} w={140}/>}<Button component="a" variant="default" href={artifact?.url} download>Download</Button></Group>
    {loading && <Group justify="center" p="xl"><Loader size="sm"/></Group>}
    {!loading && artifact?.kind === 'image' && <img className="artifactImage" src={artifact.url} alt={artifact.name}/>} 
    {!loading && artifact?.kind === 'html' && <iframe className="artifactFrame" src={artifact.url} title={artifact.name}/>} 
    {!loading && preview?.kind === 'table' && mode === 'chart' && <TinyResultChart rows={preview.rows} columns={preview.columns}/>} 
    {!loading && preview?.kind === 'table' && mode === 'table' && <ScrollArea h={390}><Table striped highlightOnHover miw={700} verticalSpacing="xs"><Table.Thead><Table.Tr>{preview.columns.map(column=><Table.Th key={column}>{column}</Table.Th>)}</Table.Tr></Table.Thead><Table.Tbody>{preview.rows.map((row,index)=><Table.Tr key={index}>{preview.columns.map(column=><Table.Td key={column} className="mono"><Text size="xs">{row[column]}</Text></Table.Td>)}</Table.Tr>)}</Table.Tbody></Table></ScrollArea>} 
    {!loading && preview && (preview.kind !== 'table' || mode === 'raw') && <Code block className="rawPreview">{JSON.stringify(preview.kind === 'table' ? preview.rows : preview.value, null, 2)}</Code>}
  </>;
}

function RunStatus({ status }: { status: AnalysisRun['status'] }) {
  const tone = status === 'completed' ? 'pass' : status === 'failed' ? 'fail' : 'watch';
  return <StatusBadge value={status.toUpperCase()} tone={tone}/>;
}

function AnalysisRunner() {
  const dispatch = useAppDispatch();
  const { catalog, charts, runs, activeRunId, loading, error } = useAppSelector(state => state.runner);
  const [strategyId, setStrategyId] = useState('');
  const [chartId, setChartId] = useState('');
  const [parameters, setParameters] = useState<Record<string,unknown>>({});
  const activeRun = runs.find(run => run.id === activeRunId) ?? null;
  const definition = catalog.find(item => item.id === strategyId);
  useEffect(() => { void dispatch(fetchRunnerCatalog()); void dispatch(fetchCharts()); void dispatch(fetchRuns()); }, [dispatch]);
  useEffect(() => { if (!strategyId && catalog[0]) setStrategyId(catalog[0].id); }, [catalog, strategyId]);
  useEffect(() => {
    if (!definition) return;
    if (!definition.charts.includes(chartId)) setChartId(definition.charts[0] ?? '');
  }, [chartId, definition]);
  useEffect(() => { if (definition) setParameters(Object.fromEntries(definition.parameters.map(param => [param.key,param.default]))); }, [definition]);
  const activeRunIdForPoll = activeRun?.id;
  const activeRunStatus = activeRun?.status;
  useEffect(() => {
    if (!activeRunIdForPoll || !activeRunStatus || !['queued','running'].includes(activeRunStatus)) return;
    const timer = window.setInterval(() => { void dispatch(fetchRun(activeRunIdForPoll)); }, 1200);
    return () => window.clearInterval(timer);
  }, [activeRunIdForPoll, activeRunStatus, dispatch]);
  const selectedChart = charts.find(chart => chart.id === chartId);
  const submit = () => { if (strategyId && chartId) void dispatch(startRun({strategyId,chartId,parameters})); };
  return <>
    <Group justify="space-between" align="flex-end" mb="lg"><Box><Title order={2}>Run analysis</Title><Text c="dimmed" size="xs">Databento one-minute chart data → chart-agnostic strategy → reproducible report</Text></Box><Badge variant="outline" color="teal" leftSection={<IconDatabase size={13}/>}>Local data · no TradingView</Badge></Group>
    {error && <Alert color="red" title="Runner unavailable" mb="lg">{error}. Start both services with <Code>npm run dev:full</Code>.</Alert>}
    <SimpleGrid cols={{base:1,lg:3}} spacing="lg" style={{alignItems:'start'}}>
      <Panel><Text fw={600} mb="sm">Analysis parameters</Text><Select label="Strategy" searchable data={catalog.map(item=>({value:item.id,label:item.name}))} value={strategyId} onChange={value => value && setStrategyId(value)}/>{definition && <><Text size="xs" c="dimmed" mt="xs" mb="md">{definition.description}</Text><Select label="Chart dataset" searchable data={charts.filter(chart=>definition.charts.includes(chart.id) && chart.available).map(chart=>({value:chart.id,label:`${chart.symbol} · ${chart.name}`}))} value={chartId} onChange={value=>value&&setChartId(value)}/>{selectedChart && <Box className="datasetCard"><Group justify="space-between"><Text fw={600} size="xs">{selectedChart.source}</Text><Badge size="xs" color="teal" variant="light">READY</Badge></Group><Text c="dimmed" size="xs">{selectedChart.rows?.toLocaleString() ?? '—'} one-minute bars · {selectedChart.first_bar?.slice(0,10)} to {selectedChart.last_bar?.slice(0,10)}</Text><Text c="dimmed" size="xs">tick {selectedChart.tick_size} · ${selectedChart.point_value}/point · {selectedChart.timezone}</Text><Text c="dimmed" size="xs" className="mono">dataset {selectedChart.fingerprint?.slice(0,12)}…</Text></Box>}<Stack gap="md">{definition.parameters.map(parameter=><ParameterField key={parameter.key} parameter={parameter} value={parameters[parameter.key]} onChange={value=>setParameters(current=>({...current,[parameter.key]:value}))}/>)}</Stack><Button fullWidth mt="xl" loading={loading} disabled={!chartId} onClick={submit} leftSection={<IconTrendingUp size={16}/>}>Run analysis</Button><Text c="dimmed" size="xs" mt="xs">Each report records the chart, dataset fingerprint, contract economics, strategy parameters, and output artifacts.</Text></>}</Panel>
      <Box className="span2"><Panel><Group justify="space-between" mb="sm"><Text fw={600}>Runs</Text><Button size="compact-xs" variant="subtle" leftSection={<IconRefresh size={14}/>} onClick={()=>void dispatch(fetchRuns())}>Refresh</Button></Group>{runs.length === 0 ? <Text c="dimmed" size="sm">No dashboard runs yet.</Text> : <ScrollArea><Table miw={620} verticalSpacing="xs"><Table.Thead><Table.Tr><Table.Th>Created</Table.Th><Table.Th>Analysis</Table.Th><Table.Th>Status</Table.Th><Table.Th>Files</Table.Th><Table.Th/></Table.Tr></Table.Thead><Table.Tbody>{runs.slice(0,12).map(run=><Table.Tr key={run.id} className={run.id===activeRunId?'selectedRun':''}><Table.Td><Text className="mono" size="xs">{new Date(run.created_at).toLocaleString()}</Text></Table.Td><Table.Td><Text size="xs" fw={600}>{run.strategy_name}</Text><Text c="dimmed" size="xs" className="mono">{run.id}</Text></Table.Td><Table.Td><RunStatus status={run.status}/></Table.Td><Table.Td><Text size="xs">{run.artifacts.length}</Text></Table.Td><Table.Td><Button variant="subtle" size="compact-xs" onClick={()=>dispatch(selectRun(run.id))}>Inspect</Button></Table.Td></Table.Tr>)}</Table.Tbody></Table></ScrollArea>}</Panel>
      {activeRun && <Panel className="runDetail"><Group justify="space-between" mb="sm"><Box><Text fw={600}>{activeRun.strategy_name}</Text><Text c="dimmed" size="xs" className="mono">{activeRun.output_dir}</Text></Box><RunStatus status={activeRun.status}/></Group>{['queued','running'].includes(activeRun.status) && <Group justify="center" p="xl"><Loader size="sm"/><Text size="sm">{activeRun.status === 'queued' ? 'Waiting for a worker…':'Analysis is running…'}</Text></Group>}{activeRun.status === 'failed' && <Alert color="red" title={`Exited with code ${activeRun.return_code ?? 'unknown'}`}><Code block>{activeRun.log || 'No process output was captured.'}</Code></Alert>}{activeRun.status === 'completed' && <ArtifactPreview run={activeRun}/>}<details className="runMeta"><summary>Parameters and process log</summary><Text className="eyebrow" mt="sm">Parameters</Text><Code block>{JSON.stringify(activeRun.parameters,null,2)}</Code>{activeRun.log && <><Text className="eyebrow" mt="sm">Process output</Text><Code block className="runLog">{activeRun.log}</Code></>}</details></Panel>}
      </Box>
    </SimpleGrid>
  </>;
}

function proposalCsv() {
  const header = 'strategy,version,instrument,current_risk,proposed_risk,contracts,margin,monthly_cost';
  return [header,...strategies.map(s => [s.name,s.version,s.instrument,s.currentRisk,s.proposedRisk,`"${s.contracts}"`,s.margin,s.cost].join(','))].join('\n');
}

function Proposal() {
  const [copied,setCopied] = useState(false);
  const reasoning = strategies.map(s => `${s.name}: ${s.allocationReason}`).join('\n\n');
  const exportCsv = () => { const url = URL.createObjectURL(new Blob([proposalCsv()],{type:'text/csv'})); const a=document.createElement('a'); a.href=url;a.download='allocation-proposal-2026-09-06.csv';a.click();URL.revokeObjectURL(url); };
  return <><Group justify="space-between" mb="xs"><Box><Title order={2}>Allocation proposal</Title><Text c="dimmed" size="xs">ALLOC-2026-09-06-01 · read-only · manual execution</Text></Box><Group><Button variant="default" leftSection={copied?<IconCheck size={16}/>:<IconCopy size={16}/>} onClick={async()=>{await navigator.clipboard.writeText(reasoning);setCopied(true);}}>{copied?'Copied':'Copy reasoning'}</Button><Button leftSection={<IconDownload size={16}/>} onClick={exportCsv}>Export CSV</Button></Group></Group><Text size="xs" c="dimmed" mb="lg">Risk shares are converted to whole micro contracts. Rounding, margin and estimated costs are shown per sleeve.</Text><SimpleGrid cols={{base:1,xs:2,md:4}} spacing="md" mb="lg"><Kpi label="Allocated / reserved / unused" value={`${proposedAllocated} / ${reserved} / ${unused}`} detail="% of risk budget · sums to 100"/><Kpi label="Orders implied" value="3 lines" detail="flatten 5 MCL, cut MNQ-ON, add 1 MGC"/><Kpi label="Margin after" value="$15,620" detail="from $21,340 · 15.6% of capital"/><Kpi label="Est. trading cost" value="$1,024 / mo" detail="from $1,656 · mostly overnight"/></SimpleGrid><Panel className="tablePanel"><ScrollArea><Table miw={1050} verticalSpacing="sm"><Table.Thead><Table.Tr><Table.Th>Strategy</Table.Th><Table.Th ta="right">Risk now</Table.Th><Table.Th ta="right">Proposed</Table.Th><Table.Th ta="right">Contracts</Table.Th><Table.Th ta="right">Margin</Table.Th><Table.Th ta="right">Cost / mo</Table.Th><Table.Th>Reason</Table.Th></Table.Tr></Table.Thead><Table.Tbody>{strategies.map(s=><Table.Tr key={s.id}><Table.Td><Text fw={600} size="sm">{s.name}</Text><Text c="dimmed" size="xs">{s.version} · {s.instrument}</Text></Table.Td><Table.Td ta="right" className="mono">{s.currentRisk}%</Table.Td><Table.Td ta="right" className="mono"><strong>{s.proposedRisk}%</strong></Table.Td><Table.Td ta="right"><Text className="mono" size="sm">{s.contracts}</Text><Text c="dimmed" size="xs">round {s.rounding}</Text></Table.Td><Table.Td ta="right" className="mono">{s.margin?money(s.margin):'—'}</Table.Td><Table.Td ta="right" className="mono">{s.cost?money(s.cost):'—'}</Table.Td><Table.Td><Text size="xs" maw={370}>{s.allocationReason}</Text></Table.Td></Table.Tr>)}</Table.Tbody></Table></ScrollArea></Panel><SimpleGrid cols={{base:1,md:2}} spacing="lg" mt="lg"><KeyValues title="Portfolio risk before → after" rows={[["Deployed risk","90% → 72%"],["Projected vol / τ","1.17× → 0.87×"],["1-yr DD, 95th pct","−19.5% → −14.9%"],["MNQ instrument share","44% → 32%"],["Margin used","$21,340 → $15,620"]]}/><KeyValues title="Provenance & method" rows={[["Calculation","ALLOC-2026-09-06-01"],["Policy","v2.3 · risk parity · τ 12%"],["Cost limit","0.100 SR/yr"],["DD reference","20-day blocks · 5,000 draws"],["Inputs hash","sha256 4f1c…9ae2"]]}/></SimpleGrid></>;
}

export function App() {
  const view = useAppSelector(state => state.dashboard.view);
  const content = useMemo(() => ({portfolio:<Portfolio/>,detail:<StrategyDetail/>,risk:<Risk/>,research:<Research/>,runner:<AnalysisRunner/>,data:<DataPage/>,proposal:<Proposal/>})[view], [view]);
  return <><Header/><Container size={1420} className="main">{content}</Container><footer><Container size={1420}><Group justify="space-between"><Text size="xs">Strategy Health & Allocation · decision support only</Text><Group gap={6}><IconClock size={13}/><Text size="xs">Next scheduled review 30 Sep 2026</Text></Group></Group></Container></footer></>;
}
