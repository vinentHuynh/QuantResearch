import { useCallback, useEffect, useState } from 'react';
import { Alert, Badge, Button, Checkbox, Code, Group, NumberInput, Progress, ScrollArea, Select, SimpleGrid, Stack, Table, Tabs, Text, Textarea, TextInput, Title } from '@mantine/core';
import { PageHeader } from './Shell';

type Dataset = { id: string; symbol: string; first: string; last: string };
type Split = { start: string; end: string; bars: number };
type Protocol = { name: string; hypothesis: string; prior_exposure: string; dataset: Dataset; start: string; end: string; timeframe: string; session: string; rules: Record<string, number>; source_hash: string; parent_id?: string };
type Preview = { token: string; protocol: Protocol; plan: { bars: number; splits: Record<string, Split> } };
type Attempt = { id: string; phase: string; status: string; error?: string; created_at: string };
type Study = Omit<Preview, 'token'> & { id: string; created_at: string; frozen_at?: string; final_opened_at?: string; reviewed_at?: string; review_note?: string; attempts: Attempt[]; prior_studies: string[]; protocol_hash: string };
type Rates = { detected: number; revisited: number; return_denominator: number; reaction_denominator: number; return_rate: number | null; rejection_rate: number | null; failure_rate: number | null; unresolved_rate: number | null; fill_rates: Record<string, number | null>; counts: Record<string, number>; distributions: Record<string, number[] | null> };
type Comparison = { difference: number | null; interval_95: number[] | null; clusters: number; pattern_n: number; control_n: number };
type Summary = { family: string; pattern: Rates; control: Rates; matched: number; unmatched: number; comparisons: Record<string, Comparison>; evidence: string; groups: Record<string, Rates>; periods: Record<string, Rates>; visits: { visit: number; n: number; counts: Record<string, number> }[]; overlaps: number };
type Event = { id: number; family: string; pattern?: string; recognition?: Record<string, number>; direction: number; confirmation: number; anchor: number; low: number; high: number; timestamp: string; outcome: string; age: number | null; touch: number | null; atr: number; match_id: string | null; overlap: boolean };
type Candle = { index: number; timestamp: string; open: number; high: number; low: number; close: number };
type Sample = { event: Event; candles: Candle[] };
type Recognizer = { key: string; name: string; pattern: Rates; control: Rates; matched: number; comparisons: Record<string, Comparison> };
type Result = { phase: string; split: Split; summaries: Summary[]; warnings: string[]; samples: Sample[]; recognizers?: Recognizer[]; sample_policy?: string };
const names: Record<string, string> = { support_resistance: 'Support / resistance', supply_demand: 'Supply / demand', order_block: 'Order blocks', fvg: 'Fair value gaps' };
const patternNames: Record<string, string> = { demand_zone: 'Demand zone', supply_zone: 'Supply zone', bullish_order_block: 'Bullish order block', bearish_order_block: 'Bearish order block', bullish_fvg: 'Bullish FVG', bearish_fvg: 'Bearish FVG', support: 'Support', resistance: 'Resistance' };
const patternDescriptions: Record<string, string> = {
  demand_zone: 'A tight price range followed by a strong rise. We look for a bounce up when price returns.',
  supply_zone: 'A tight price range followed by a strong fall. We look for a bounce down when price returns.',
  bullish_order_block: 'The last down candle before a strong upward breakout. We test its price range for a bounce up.',
  bearish_order_block: 'The last up candle before a strong downward breakout. We test its price range for a bounce down.',
  bullish_fvg: 'A gap between the first and third candles during an upward move. We track whether it fills and bounces up.',
  bearish_fvg: 'A gap between the first and third candles during a downward move. We track whether it fills and bounces down.',
  support: 'A recent low with two higher lows on each side. We test whether price bounces up on its return.',
  resistance: 'A recent high with two lower highs on each side. We test whether price bounces down on its return.',
};
const outcomeLabels: Record<string, string> = { rejection: 'Bounced away', failure: 'Moved through the zone', unresolved: 'No clear move in time', ambiguous: 'Order of moves unclear', incomplete: 'Not enough later data', not_returned: 'Did not return' };
const stageDescriptions: Record<string, string> = { development: 'First, check that patterns are found correctly.', validation: 'Then, test the same rules on later prices.', final: 'Keep this data closed until the rules are locked.' };
function plainFinding(c: Comparison) {
  if (!c.interval_95) return { label: 'More data needed', detail: 'Too few usable examples or separate time periods to judge.', color: 'gray' };
  if (c.interval_95[0] > 0) return { label: 'Stronger bounces in this sample', detail: 'Bounces were more frequent than at comparable areas. This still needs further testing.', color: 'teal' };
  if (c.interval_95[1] < 0) return { label: 'Weaker bounces in this sample', detail: 'Bounces were less frequent than at comparable areas.', color: 'orange' };
  return { label: 'No clear advantage', detail: 'The difference from comparable areas could go either way.', color: 'gray' };
}
const phases = ['development', 'validation', 'final'];
const labels: Record<string, string> = { atr_period: 'ATR candles', base_bars: 'Base candles', base_atr: 'Maximum base width (ATR)', departure_bars: 'Departure window', departure_atr: 'Departure (ATR)', ob_lookback: 'Opposite candle lookback', breakout_bars: 'Breakout lookback', swing_bars: 'Swing candles each side', level_width_atr: 'S/R full width (ATR)', return_bars: 'Return horizon', reaction_bars: 'Reaction horizon', rejection_atr: 'Rejection distance (ATR)', failure_atr: 'Adverse buffer (ATR)', seed: 'Random seed', bootstrap_samples: 'Bootstrap repetitions', match_caliper: 'Matching caliper', cluster_bars: 'Uncertainty block length' };
const percent = (n: number | null | undefined) => n == null ? '—' : `${(n * 100).toFixed(1)}%`;
const difference = (n: number | null | undefined) => n == null ? '—' : `${n >= 0 ? '+' : ''}${(n * 100).toFixed(1)} pp`;
const interval = (c: Comparison) => c.interval_95 ? `${difference(c.interval_95[0])} to ${difference(c.interval_95[1])}` : 'Insufficient evidence';
const base = '/api/workbench/event-studies';
async function api<T>(path = '', body?: unknown): Promise<T> {
  const response = await fetch(base + path, body === undefined ? undefined : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Event study request failed');
  return data;
}

function Splits({ plan }: { plan: Preview['plan'] }) {
  return <SimpleGrid cols={{ base: 1, sm: 3 }}>{Object.entries(plan.splits).map(([phase, split]) => <div className="wb-card" key={phase}><Text fw={600} tt="capitalize">{phase} · {phase === 'development' ? '60%' : '20%'}</Text><Text size="sm">{stageDescriptions[phase]}</Text><Text size="xs" c="dimmed" mt="xs">{split.bars.toLocaleString()} candles · {split.start.slice(0, 10)} to {split.end.slice(0, 10)}</Text></div>)}</SimpleGrid>;
}

function DetectionChart({ sample }: { sample: Sample }) {
  const { event: e, candles } = sample;
  if (!candles.length) return null;
  const lo = Math.min(e.low - e.atr, ...candles.map(c => c.low));
  const hi = Math.max(e.high + e.atr, ...candles.map(c => c.high));
  const x = (i: number) => 38 + (i - candles[0].index + .5) / candles.length * 860;
  const y = (p: number) => 220 - (p - lo) / (hi - lo || 1) * 190;
  const width = Math.max(1, 860 / candles.length * .65);
  return <div><Text size="sm" fw={600}>{e.pattern ? patternNames[e.pattern] : names[e.family]} · {outcomeLabels[e.outcome] || e.outcome}</Text><Text size="xs" c="dimmed">Pattern confirmed {e.timestamp.slice(0, 10)} at {e.timestamp.slice(11, 16)} (chart time) · {e.age == null ? 'Price did not return during the available observation window.' : `Price returned ${e.age} candles later.`}</Text>
    <svg viewBox="0 0 930 260" role="img" aria-label={`${names[e.family]} detection with confirmation and first touch`} style={{ width: '100%', minHeight: 160, background: 'var(--mantine-color-gray-0)', borderRadius: 8 }}>
      <rect x={x(e.confirmation)} y={y(e.high)} width={Math.max(0, 900-x(e.confirmation))} height={Math.max(1, y(e.low)-y(e.high))} fill={e.direction === 1 ? '#12b886' : '#fa5252'} opacity={.18}/>
      {candles.map(c => <g key={c.index} stroke={c.close >= c.open ? '#087f5b' : '#c92a2a'}><title>{c.timestamp} O {c.open} H {c.high} L {c.low} C {c.close}</title><line x1={x(c.index)} x2={x(c.index)} y1={y(c.high)} y2={y(c.low)}/><rect x={x(c.index)-width/2} y={y(Math.max(c.open, c.close))} width={width} height={Math.max(1, Math.abs(y(c.open)-y(c.close)))} fill={c.close >= c.open ? '#12b886' : '#fa5252'}/></g>)}
      <line x1={x(e.confirmation)} x2={x(e.confirmation)} y1={15} y2={230} stroke="#4263eb" strokeDasharray="4 3"/><text x={Math.min(800, x(e.confirmation)+5)} y={15} fontSize="11" fill="#4263eb">Confirmation close</text>
      {e.touch !== null && <><line x1={x(e.touch)} x2={x(e.touch)} y1={30} y2={230} stroke="#7950f2" strokeDasharray="2 3"/><text x={Math.min(810, x(e.touch)+5)} y={242} fontSize="11" fill="#7950f2">First touch</text></>}
      <text x={3} y={30} fontSize="10" fill="#495057">{hi.toFixed(0)}</text><text x={3} y={220} fontSize="10" fill="#495057">{lo.toFixed(0)}</text>
      <text x={40} y={258} fontSize="10" fill="#495057">{candles[0].timestamp.slice(0, 16)}</text><text x={740} y={258} fontSize="10" fill="#495057">{candles.at(-1)!.timestamp.slice(0, 16)}</text>
    </svg>{e.recognition && <details><summary>Why this pattern was recognized</summary><Text size="sm" mt="xs">{e.pattern && patternDescriptions[e.pattern]}</Text><Text size="xs" c="dimmed">Price area: {e.low.toFixed(2)} to {e.high.toFixed(2)}. Typical candle movement at confirmation (ATR): {e.atr.toFixed(2)}. {e.match_id ? 'A comparable area was found for the comparison.' : 'No sufficiently similar comparison area was found.'}{e.overlap ? ' This overlaps another detected pattern.' : ''}</Text><details><summary>Exact measurements</summary><Text size="xs">Anchor candle {e.anchor} · confirmation candle {e.confirmation}</Text><SimpleGrid cols={{ base: 1, sm: 3 }} mt="xs">{Object.entries(e.recognition).map(([key, value]) => <Text size="xs" key={key}>{key.replaceAll('_', ' ')}: <strong>{value.toLocaleString(undefined, { maximumFractionDigits: 4 })}</strong></Text>)}</SimpleGrid></details></details>}</div>;
}

function PercentageSummary({ result }: { result: Result }) {
  const rows = result.recognizers?.length
    ? Object.keys(patternNames).flatMap(key => result.recognizers!.filter(r => r.key === key))
    : result.summaries.map(s => ({ key: s.family, name: names[s.family], pattern: s.pattern, comparisons: s.comparisons }));
  return <section aria-label="Pattern validity summary" className="wb-card">
    <Group justify="space-between" align="start" mb="lg"><div><Title order={3}>Pattern validity summary</Title><Text size="sm" c="dimmed" mt={4}>How often price bounced as expected after returning to the pattern.</Text></div><Badge color="gray" variant="light">{result.phase} results</Badge></Group>
    <SimpleGrid cols={{ base: 1, xs: 2, lg: 4 }} spacing="md">
      {rows.map(row => {
        const rate = row.pattern.rejection_rate;
        const count = row.pattern.reaction_denominator;
        const finding = plainFinding(row.comparisons.rejection);
        const enoughToMeasure = count > 0 && rate !== null;
        const insufficient = !row.comparisons.rejection.interval_95;
        const color = !enoughToMeasure ? 'gray' : insufficient ? 'yellow' : finding.color === 'teal' ? 'teal' : 'gray';
        return <article key={row.key} aria-label={row.name} style={{ padding: 18, border: '1px solid var(--line)', borderRadius: 8, display: 'flex', flexDirection: 'column' }}>
          <Text fw={600} size="sm" mih={40}>{row.name}</Text>
          <Text data-testid="bounce-percentage" style={{ fontSize: 38, lineHeight: 1.2, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{enoughToMeasure ? percent(rate) : '—'}</Text>
          <Text size="xs" c="dimmed" mt={4}>{enoughToMeasure ? 'expected bounce rate' : 'No measurable returns yet'}</Text>
          <Progress mt="md" mb="sm" size={5} value={enoughToMeasure ? rate! * 100 : 0} color={color} aria-label={`${row.name} expected bounce rate`}/>
          <Text size="xs">{enoughToMeasure ? `${row.pattern.counts.rejection} of ${count} measured returns bounced` : `${row.pattern.detected} patterns found`}</Text>
          <Text size="xs" fw={600} c={insufficient && enoughToMeasure ? 'yellow.9' : 'dimmed'} mt="sm">{!enoughToMeasure ? 'Not enough data' : insufficient ? 'Too little evidence to judge' : finding.label}</Text>
        </article>;
      })}
    </SimpleGrid>
    <Text size="xs" c="dimmed" mt="md">Percentage = expected bounces ÷ measurable returns. Unclear and unfinished reactions are excluded. This is an observed rate, not a confidence score or trading win rate.</Text>
    <Text size="xs" c="dimmed" mt={4}>Evidence labels use matched comparisons. A high percentage from a small sample does not establish an advantage.</Text>
  </section>;
}

function StudyResults({ result }: { result: Result }) {
  return <Tabs defaultValue="summary" keepMounted={false}>
    <Tabs.List mb="md" aria-label="Result screens"><Tabs.Tab value="summary">Summary</Tabs.Tab><Tabs.Tab value="details">Details & charts</Tabs.Tab></Tabs.List>
    <Tabs.Panel value="summary"><PercentageSummary result={result}/></Tabs.Panel>
    <Tabs.Panel value="details"><ResultTables result={result}/></Tabs.Panel>
  </Tabs>;
}

function ResultTables({ result }: { result: Result }) {
  const [patternFilter, setPatternFilter] = useState(result.samples[0]?.event.pattern || 'all');
  const found = result.summaries.reduce((n, s) => n + s.pattern.detected, 0);
  const revisited = result.summaries.reduce((n, s) => n + s.pattern.revisited, 0);
  const anyAdvantage = result.summaries.some(s => (s.comparisons.rejection.interval_95?.[0] ?? -1) > 0);
  const anyInterval = result.summaries.some(s => s.comparisons.rejection.interval_95 !== null);
  return <Stack>
    <div className="wb-card"><Text size="xs" c="dimmed" tt="uppercase">{result.phase} · {result.split.start.slice(0, 10)} to {result.split.end.slice(0, 10)}</Text><Title order={3} mt="xs">What the results mean</Title><Text fw={600} mt="sm">{!found ? 'No patterns were found in this period.' : anyAdvantage ? 'Some patterns bounced more often than similar areas in this sample.' : anyInterval ? 'These tests have not shown a clear bounce advantage.' : 'There is not enough evidence to judge these patterns yet.'}</Text><Text size="sm" c="dimmed" mt="xs">Finding a pattern tells us the rule worked. To judge whether it helps, we compare what happens next with similar price areas. A bounce is a price reaction, not a profitable trade.</Text><Group gap="xl" mt="md"><div><Text size="xl" fw={700}>{found.toLocaleString()}</Text><Text size="sm">patterns found</Text></div><div><Text size="xl" fw={700}>{revisited.toLocaleString()}</Text><Text size="sm">were revisited</Text></div><div><Text size="xl" fw={700}>{result.summaries.filter(s => !s.comparisons.rejection.interval_95).length} of {result.summaries.length}</Text><Text size="sm">groups need more data</Text></div></Group><Text size="xs" c="dimmed" mt="sm">Patterns can overlap, so these are not all independent examples.</Text></div>
    <div className="wb-card"><Title order={3}>Does each pattern help?</Title><Text size="sm" c="dimmed" mb="md">A comparison area is a similar price area used as a reference. These are the four main tests.</Text><SimpleGrid cols={{ base: 1, sm: 2 }}>{result.summaries.map(s => { const finding = plainFinding(s.comparisons.rejection); return <div key={s.family} style={{ border: '1px solid var(--line)', borderRadius: 8, padding: 16 }}><Text fw={600}>{names[s.family]}</Text><Text size="sm" fw={600} c={finding.color === 'gray' ? 'dimmed' : finding.color} mt="xs">{finding.label}</Text><Text size="sm" mt="xs">{finding.detail}</Text><Text size="xs" c="dimmed" mt="sm">{s.pattern.detected} found · {s.pattern.revisited} revisited · {s.matched} had a comparison area</Text>{s.family === 'fvg' && <Text size="xs" mt="xs">Gap filling and bouncing are separate questions. Fill results are in Detailed statistics.</Text>}</div>; })}</SimpleGrid></div>
    {result.recognizers && <div className="wb-card"><Title order={3}>The eight patterns</Title><Text size="sm" c="dimmed" mb="md">Bullish means looking for a move up; bearish means looking for a move down.</Text><SimpleGrid cols={{ base: 1, sm: 2 }}>{result.recognizers.map(r => <div key={r.key} style={{ borderBottom: '1px solid var(--line)', paddingBottom: 12 }}><Text fw={600}>{r.name}</Text><Text size="sm" c="dimmed" mt={4}>{patternDescriptions[r.key]}</Text><Group justify="space-between" mt="xs"><Text size="sm">{r.pattern.detected} found · {r.pattern.revisited} revisited</Text><Button size="compact-xs" variant="subtle" disabled={!result.samples.some(s => s.event.pattern === r.key)} onClick={() => { setPatternFilter(r.key); document.getElementById('pattern-example-charts')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }}>See examples</Button></Group></div>)}</SimpleGrid></div>}
    <details className="wb-card"><summary>Detailed statistics</summary><Stack mt="md"><Text size="sm" c="dimmed">Return = price revisited the area. Rejection = price bounced away by the required distance first. Failure = price went too far through it first. Ambiguous = we cannot tell which move happened first. Incomplete = not enough later data. ATR measures typical recent candle movement; pp means percentage points.</Text>
    <div className="wb-card"><Title order={3} tt="capitalize">{result.phase} results</Title><Text size="sm" c="dimmed" mb="md">Rejection is measured after touch. Return and fill use the full return horizon. Differences use the matched subset; all detections remain in the first table.</Text>
      <ScrollArea><Table miw={1150}><Table.Thead><Table.Tr>{['Pattern', 'Detected / revisited', 'Return', 'Rejection', 'Failure', 'Unresolved', 'Ambiguous', 'Incomplete', 'Matched / unmatched'].map(h => <Table.Th key={h}>{h}</Table.Th>)}</Table.Tr></Table.Thead><Table.Tbody>{result.summaries.map(s => <Table.Tr key={s.family}><Table.Td>{names[s.family]}</Table.Td><Table.Td>{s.pattern.detected} / {s.pattern.revisited}</Table.Td><Table.Td>{percent(s.pattern.return_rate)}<Text size="xs" c="dimmed">n={s.pattern.return_denominator}</Text></Table.Td><Table.Td>{percent(s.pattern.rejection_rate)}<Text size="xs" c="dimmed">n={s.pattern.reaction_denominator}</Text></Table.Td><Table.Td>{percent(s.pattern.failure_rate)}</Table.Td><Table.Td>{percent(s.pattern.unresolved_rate)}</Table.Td><Table.Td>{s.pattern.counts.ambiguous}</Table.Td><Table.Td>{s.pattern.counts.incomplete}</Table.Td><Table.Td>{s.matched} / {s.unmatched}</Table.Td></Table.Tr>)}</Table.Tbody></Table></ScrollArea>
    </div>
    {result.recognizers && <div className="wb-card"><Title order={3}>Each pattern recognizer</Title><Text size="sm" c="dimmed" mb="md">All eight recognition rules are measured separately. These directional breakdowns are descriptive; the four family comparisons remain the declared primary tests.</Text><ScrollArea><Table miw={1000}><Table.Thead><Table.Tr>{['Recognizer', 'Detected', 'Revisited', 'Matched', 'Rejection', 'Control rejection', 'Difference', '95% interval'].map(h => <Table.Th key={h}>{h}</Table.Th>)}</Table.Tr></Table.Thead><Table.Tbody>{result.recognizers.map(r => <Table.Tr key={r.key}><Table.Td>{r.name}</Table.Td><Table.Td>{r.pattern.detected}</Table.Td><Table.Td>{r.pattern.revisited}</Table.Td><Table.Td>{r.matched}</Table.Td><Table.Td>{percent(r.pattern.rejection_rate)}<Text size="xs" c="dimmed">n={r.pattern.reaction_denominator}</Text></Table.Td><Table.Td>{percent(r.control.rejection_rate)}</Table.Td><Table.Td>{difference(r.comparisons.rejection.difference)}</Table.Td><Table.Td>{interval(r.comparisons.rejection)}</Table.Td></Table.Tr>)}</Table.Tbody></Table></ScrollArea></div>}
    <div className="wb-card"><Title order={3}>Pattern minus matched control</Title><Text size="sm" c="dimmed">Pointwise 95% intervals resample shared chronological blocks. Fewer than 10 occupied blocks or 20 eligible observations in either arm gives no interval.</Text><ScrollArea><Table miw={1000}><Table.Thead><Table.Tr><Table.Th>Pattern / measure</Table.Th><Table.Th>Control rate</Table.Th><Table.Th>Difference</Table.Th><Table.Th>95% interval</Table.Th><Table.Th>Pattern / control n</Table.Th><Table.Th>Time blocks</Table.Th></Table.Tr></Table.Thead><Table.Tbody>{result.summaries.flatMap(s => (s.family === 'fvg' ? ['return', 'rejection', 'midpoint', 'far'] : ['return', 'rejection']).map(metric => { const c = s.comparisons[metric]; return <Table.Tr key={s.family+metric}><Table.Td>{names[s.family]} · {metric === 'far' ? 'full fill' : metric}</Table.Td><Table.Td>{percent(metric === 'return' ? s.control.return_rate : metric === 'rejection' ? s.control.rejection_rate : s.control.fill_rates[metric])}</Table.Td><Table.Td>{difference(c.difference)}</Table.Td><Table.Td>{interval(c)}</Table.Td><Table.Td>{c.pattern_n} / {c.control_n}</Table.Td><Table.Td>{c.clusters}</Table.Td></Table.Tr>; }))}</Table.Tbody></Table></ScrollArea></div>
    {result.summaries.map(s => <details className="wb-card" key={s.family}><summary><strong>{names[s.family]}</strong> · {s.evidence}</summary><Stack mt="md"><Text size="sm">{s.overlaps} overlapping detections. Favourable/adverse movement below is in frozen ATR units (10th / median / 90th percentiles).</Text><Text size="sm">Favourable: {s.pattern.distributions.mfe?.map(v => v.toFixed(2)).join(' / ') || '—'} · Adverse: {s.pattern.distributions.mae?.map(v => v.toFixed(2)).join(' / ') || '—'}</Text>{s.family === 'fvg' && <Text size="sm">Near edge: {percent(s.pattern.fill_rates.near)} · midpoint: {percent(s.pattern.fill_rates.midpoint)} · full fill: {percent(s.pattern.fill_rates.far)}</Text>}
      <ScrollArea><Table miw={650}><Table.Thead><Table.Tr><Table.Th>Period / group</Table.Th><Table.Th>Detected</Table.Th><Table.Th>Revisited</Table.Th><Table.Th>Rejection</Table.Th><Table.Th>Reaction n</Table.Th></Table.Tr></Table.Thead><Table.Tbody>{Object.entries({ ...s.groups, ...s.periods }).map(([key, rates]) => <Table.Tr key={key}><Table.Td>{key.replaceAll('_', ' ')}</Table.Td><Table.Td>{rates.detected}</Table.Td><Table.Td>{rates.revisited}</Table.Td><Table.Td>{percent(rates.rejection_rate)}</Table.Td><Table.Td>{rates.reaction_denominator}</Table.Td></Table.Tr>)}</Table.Tbody></Table></ScrollArea>
      <Text size="sm" fw={600}>Repeated visits (descriptive, overlapping observations)</Text>{s.visits.map(v => <Text size="sm" key={v.visit}>Visit {v.visit}: {v.n} observations · {Object.entries(v.counts).map(([key, n]) => `${n} ${key}`).join(' · ')}</Text>)}</Stack></details>)}
    <details className="wb-card"><summary>Interpretation and limitations</summary><Stack mt="md">{result.warnings.map(w => <Text size="sm" key={w}>{w}</Text>)}</Stack></details>
    </Stack></details>
    <div className="wb-card" id="pattern-example-charts"><Title order={3}>Chart examples</Title><Text size="sm" c="dimmed" mb="md">The shaded area is the pattern. The blue line marks when it was confirmed; the purple line marks the first return. Examples were selected randomly, including patterns that did not work.</Text>{result.recognizers && <Select label="Review pattern" mb="md" value={patternFilter} data={[{ value: 'all', label: 'Show all patterns' }, ...result.recognizers.map(r => ({ value: r.key, label: `${r.name} (${r.pattern.detected} detections)` }))]} onChange={v => setPatternFilter(v || 'all')}/>}<Stack>{result.samples.filter(s => patternFilter === 'all' || !result.recognizers || s.event.pattern === patternFilter).map(s => <DetectionChart key={s.event.id} sample={s}/>)}{!result.samples.filter(s => patternFilter === 'all' || !result.recognizers || s.event.pattern === patternFilter).length && <Text>No examples for this pattern in this period. Try another pattern or period.</Text>}</Stack></div>
  </Stack>;
}

export function EventStudies({ datasets }: { datasets: Dataset[] }) {
  const [studies, setStudies] = useState<Study[]>([]);
  const [defaults, setDefaults] = useState<Record<string, number>>({});
  const [limits, setLimits] = useState<Record<string, [number, number]>>({});
  const [selected, setSelected] = useState('');
  const [attemptId, setAttemptId] = useState('');
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [newStudy, setNewStudy] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [rules, setRules] = useState<Record<string, number>>({});
  const [form, setForm] = useState({ name: 'Pattern behaviour study', dataset_id: '', start: '', end: '', timeframe: '15m', session: 'full-trading-day', hypothesis: 'Do supply/demand zones, order blocks and FVGs predict revisits or rejection beyond matched controls and ordinary support/resistance?', prior_exposure: 'Unknown; this history may have been inspected in other research.', parent_id: '' });
  const [reviewNote, setReviewNote] = useState('');
  const [acceptFinal, setAcceptFinal] = useState(false);
  const study = studies.find(s => s.id === selected);
  const attempt = study?.attempts.find(a => a.id === attemptId) || study?.attempts.at(-1);
  const resultUrl = study && attempt?.status === 'Succeeded' ? `/${study.id}/artifacts/${attempt.id}/result.json` : null;
  const refresh = useCallback(async () => {
    const data = await api<{ studies: Study[]; defaults: Record<string, number>; limits: Record<string, [number, number]> }>();
    setStudies(data.studies); setDefaults(data.defaults); setLimits(data.limits);
    setSelected(current => current || data.studies[0]?.id || '');
  }, []);
  useEffect(() => { let live = true; const poll = () => { if (live) void refresh().catch(e => { if (live) setError(e.message); }); }; poll(); const timer = window.setInterval(poll, 3000); return () => { live = false; clearInterval(timer); }; }, [refresh]);
  useEffect(() => {
    setResult(null);
    if (!resultUrl) return;
    let live = true;
    void api<Result>(resultUrl).then(data => { if (live) setResult(data); }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [resultUrl]);
  async function act(task: () => Promise<void>) { setBusy(true); setError(''); try { await task(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); } }
  function change(key: keyof typeof form, value: string) { setForm(old => ({ ...old, [key]: value })); setPreview(null); }
  function chooseDataset(id: string) {
    const d = datasets.find(item => item.id === id);
    if (!d) return;
    const ending = d.last.slice(0, 10);
    const yearBefore = new Date(ending); yearBefore.setUTCFullYear(yearBefore.getUTCFullYear()-1);
    setForm(old => ({ ...old, dataset_id: id, end: ending, start: [d.first.slice(0, 10), yearBefore.toISOString().slice(0, 10)].sort().at(-1)! })); setPreview(null);
  }
  function begin(parent?: Study) {
    setNewStudy(true); setPreview(null); setRules(parent?.protocol.rules || defaults);
    setForm(old => ({ ...old, parent_id: parent?.id || '', name: parent ? `Replication: ${parent.protocol.name}` : 'Pattern behaviour study', timeframe: parent?.protocol.timeframe || '15m', session: parent?.protocol.session || 'full-trading-day' }));
    const first = datasets.find(d => d.symbol !== parent?.protocol.dataset.symbol);
    if (first) chooseDataset(first.id);
  }
  async function operation(kind: string, body: unknown = {}) {
    const updated = await api<Study>(`/${study!.id}/${kind}`, body);
    await refresh();
    if (kind === 'run') setAttemptId(updated.attempts.at(-1)!.id);
  }
  const done = (phase: string) => !!study?.attempts.some(a => a.phase === phase && a.status === 'Succeeded');
  const running = !!study?.attempts.some(a => a.status === 'Running');
  return <><PageHeader crumb="Research" title="Pattern event studies" actions={<Button onClick={() => begin()} disabled={busy || !Object.keys(defaults).length}>New study</Button>}/><div className="wb-content"><Stack>
    <Text c="dimmed">Find price patterns, see what happened next, and compare them with similar price areas.</Text>
    {error && <Alert color="red" title="Study could not continue" withCloseButton onClose={() => setError('')}>{error}</Alert>}
    <details className="wb-card"><summary>Definitions and research protocol</summary><Stack mt="md"><Text size="sm">Default rules: three base candles spanning at most 1 ATR, then a close 1.5 ATR beyond the base within three candles. Order blocks use the last opposite-colour candle in five candles before a 1.5 ATR departure and a preceding 20-candle breakout. FVGs use the interval between candle one and candle three. Support/resistance uses a swing with two completed candles on either side and 0.25 ATR full width.</Text><Text size="sm">ATR is a 14-candle simple average of true range, fixed at confirmation for outcomes. Base compactness and departure use ATR at the base close. Return: 50 candles; rejection: 1 ATR from the near edge before a breach 0.25 ATR beyond the far edge, within 20 candles including touch. Unknown order within one minute is ambiguous.</Text><Text size="sm">Controls: supply/demand and S/R use other timestamps with the same normalized width, distance and session bucket, matched on volatility, trend and move size. Order blocks use another pre-move candle at the same breakout. FVG controls use strong moves without the same-direction FVG. Candidates come from at most 2,000 prior candles in the same split; unmatched detections are retained.</Text><Text size="sm">Each immutable protocol declares one comparison per family (four comparisons). Development → visual review → one validation result → freeze → final test. Changes require a new study; prior overlapping studies remain linked. Replication copies frozen code and rules to another instrument. Final-test results cannot certify that you have never inspected the history elsewhere.</Text></Stack></details>
    {newStudy && <div className="wb-card"><Stack><Group justify="space-between"><Title order={3}>{form.parent_id ? 'Replicate frozen study' : 'Declare a study'}</Title><Button variant="subtle" onClick={() => setNewStudy(false)}>Close</Button></Group>
      <SimpleGrid cols={{ base: 1, sm: 2 }}><TextInput label="Study name" value={form.name} onChange={e => change('name', e.currentTarget.value)}/><Select label="Dataset version" searchable value={form.dataset_id || null} data={datasets.filter(d => !form.parent_id || d.symbol !== studies.find(s => s.id === form.parent_id)?.protocol.dataset.symbol).map(d => ({ value: d.id, label: `${d.symbol} · ${d.first.slice(0, 10)} to ${d.last.slice(0, 10)} · ${d.id.slice(0, 8)}` }))} onChange={v => chooseDataset(v || '')}/><TextInput label="Start (UTC)" type="date" value={form.start} onChange={e => change('start', e.currentTarget.value)}/><TextInput label="End (UTC, inclusive)" type="date" value={form.end} onChange={e => change('end', e.currentTarget.value)}/><Select label="Timeframe" disabled={!!form.parent_id} data={['5m', '15m', '30m', '1h']} value={form.timeframe} onChange={v => change('timeframe', v || '15m')}/><Select label="Session" disabled={!!form.parent_id} data={[{ value: 'full-trading-day', label: 'Full trading day' }, { value: 'new-york-rth', label: 'New York RTH' }]} value={form.session} onChange={v => change('session', v || 'full-trading-day')}/></SimpleGrid>
      <Textarea label="What do you want to find out?" value={form.hypothesis} onChange={e => change('hypothesis', e.currentTarget.value)} autosize minRows={2}/><Textarea label="Have you already studied these dates?" description="Record any earlier tests, so reused data is not mistaken for a new test." value={form.prior_exposure} onChange={e => change('prior_exposure', e.currentTarget.value)} autosize/>
      <details><summary>Advanced settings</summary><Text size="sm" c="dimmed" mt="sm">The defaults follow the study plan. ATR means typical recent candle movement; distances use it to adjust for market volatility.</Text><SimpleGrid mt="md" cols={{ base: 1, sm: 3 }}>{Object.entries(rules).map(([key, value]) => <NumberInput key={key} label={labels[key]} value={value} min={limits[key]?.[0]} max={limits[key]?.[1]} disabled={!!form.parent_id} step={key.includes('atr') || key === 'match_caliper' ? .05 : 1} onChange={v => { setRules(old => ({ ...old, [key]: Number(v) })); setPreview(null); }}/>)}</SimpleGrid></details>
      <Group><Button loading={busy} onClick={() => void act(async () => setPreview(await api<Preview>('/preview', { ...form, rules })))}>Validate & preview</Button><Text size="xs" c="dimmed">Computes candle splits and verifies data. No pattern outcomes are revealed.</Text></Group>
      {preview && <><Splits plan={preview.plan}/><Alert color="blue">One declared definition per concept, four family comparisons. The final 20% stays closed until the protocol is frozen.</Alert><Button loading={busy} onClick={() => void act(async () => { const created = await api<Study>('', { token: preview.token }); await refresh(); setSelected(created.id); setAttemptId(''); setNewStudy(false); setAcceptFinal(false); })}>Save study protocol</Button></>}
    </Stack></div>}
    <div className="wb-card"><Select label="Saved studies" placeholder="Create a study to begin" value={selected || null} searchable data={studies.map(s => ({ value: s.id, label: `${s.protocol.name} · ${s.protocol.dataset.symbol} ${s.protocol.timeframe} · ${s.created_at.slice(0, 10)}${s.final_opened_at ? ' · final opened' : s.frozen_at ? ' · frozen' : ''}` }))} onChange={id => { setSelected(id || ''); setAttemptId(studies.find(s => s.id === id)?.attempts.at(-1)?.id || ''); setAcceptFinal(false); setReviewNote(''); }}/>{!studies.length && <Text size="sm" c="dimmed" mt="md">No event studies yet. Start with one instrument and the default 15-minute protocol.</Text>}</div>
    {study && <>
    <div className="wb-card"><SimpleGrid cols={{ base: 1, sm: 2 }}><div><Text fw={600}>{study.protocol.dataset.symbol} · {study.protocol.timeframe} candles</Text><Text size="sm" c="dimmed">{running ? 'A test is running.' : done('final') ? 'Final test complete.' : done('validation') ? 'Validation complete. Review the findings before the final test.' : done('development') ? 'Patterns found. Review the chart examples before validation.' : 'Ready to find patterns in the first part of the data.'}</Text><Badge mt="xs" variant="light" color="gray">{study.final_opened_at ? 'Final data opened' : 'Final data still closed'}</Badge></div>{study.attempts.length > 0 && <Select label="Results to view" value={attempt?.id || null} data={[...study.attempts].reverse().map(a => ({ value: a.id, label: `${a.phase === 'development' ? 'Development — first check' : a.phase === 'validation' ? 'Validation — later data' : 'Final test'} · ${a.status === 'Succeeded' ? 'Complete' : a.status} · ${new Date(a.created_at).toLocaleString()}` }))} onChange={id => setAttemptId(id || '')}/>}</SimpleGrid><Button variant="subtle" size="compact-sm" mt="sm" onClick={() => { const section = document.getElementById('study-next-steps') as HTMLDetailsElement | null; if (section) { section.open = true; section.scrollIntoView({ behavior: 'smooth', block: 'start' }); } }}>Study setup & next steps</Button>{attempt?.error && <Alert color="red" mt="sm" title={`${attempt.phase} test ${attempt.status.toLowerCase()}`}>{attempt.error}</Alert>}{attempt?.status === 'Succeeded' && !result && <Text size="sm" mt="sm">Loading results…</Text>}</div>
    {result && <StudyResults key={resultUrl} result={result}/>}
    <details className="wb-card" id="study-next-steps" open={!study.attempts.length}><summary>Study setup & next steps</summary><Stack mt="md"><Group justify="space-between"><Title order={3}>{study.protocol.name}</Title><Badge color={study.frozen_at ? 'teal' : 'blue'}>{study.final_opened_at ? 'Final opened' : study.frozen_at ? 'Rules locked' : 'Rules saved'}</Badge></Group><Text>{study.protocol.hypothesis}</Text><Text size="sm" c="dimmed">{study.protocol.dataset.symbol} · {study.protocol.timeframe} · {study.protocol.session} · {study.protocol.start} to {study.protocol.end}</Text><Text size="sm">Earlier use of these dates: {study.protocol.prior_exposure}</Text>{study.prior_studies.length > 0 && <Alert color="yellow">{study.prior_studies.length} earlier studies use some of these dates. This history is not a completely new test.</Alert>}<Splits plan={study.plan}/><Text size="sm">Start with development, review the charts, then run validation. “Freeze protocol” locks the rules before you open the last part of the data.</Text>
      <Group><Button disabled={busy || running || done('development') || !!study.frozen_at} onClick={() => void act(() => operation('run', { phase: 'development' }))}>Run development</Button><Button disabled={busy || running || !study.reviewed_at || done('validation') || !done('development')} onClick={() => void act(() => operation('run', { phase: 'validation' }))}>Run validation</Button><Button variant="default" disabled={busy || running || !done('validation') || !!study.frozen_at} onClick={() => void act(() => operation('freeze'))}>Freeze protocol</Button>{running && <Button color="red" variant="light" disabled={busy} onClick={() => void act(() => operation('cancel'))}>Cancel active job</Button>}</Group>
      {done('development') && !study.frozen_at && <><Textarea label="Visual review record" description="Inspect the random development charts below, then record confirmation timing, zone boundaries and any detection issues." value={reviewNote || study.review_note || ''} onChange={e => setReviewNote(e.currentTarget.value)}/><Button variant="light" disabled={busy || running} onClick={() => void act(() => operation('review', { note: reviewNote || study.review_note }))}>{study.reviewed_at ? 'Update review record' : 'Record visual review'}</Button></>}
      {study.frozen_at && !done('final') && <><Checkbox label="Open the reserved final 20% using the frozen rules. This exposure will be recorded." checked={acceptFinal} onChange={e => setAcceptFinal(e.currentTarget.checked)}/><Button disabled={!acceptFinal || busy || running} onClick={() => void act(() => operation('run', { phase: 'final' }))}>Run final test</Button></>}
      {done('final') && <Button variant="light" onClick={() => begin(study)}>Replicate on another instrument</Button>}
      <details><summary>Saved rules and provenance</summary><Text size="xs" mt="sm">Study {study.id} · source {study.protocol.source_hash} · protocol {study.protocol_hash}</Text>{study.protocol.parent_id && <Text size="sm">Replicates {study.protocol.parent_id}</Text>}<Code block mt="sm">{JSON.stringify(study.protocol.rules, null, 2)}</Code></details>
    </Stack></details>
    <details className="wb-card"><summary>All test attempts</summary><Text size="sm" c="dimmed" mt="sm">Includes failed, cancelled and interrupted tests. “Succeeded” means the calculation finished, not that the pattern has an advantage.</Text><ScrollArea><Table miw={650}><Table.Thead><Table.Tr><Table.Th>Phase</Table.Th><Table.Th>Created</Table.Th><Table.Th>Status</Table.Th><Table.Th>Results</Table.Th></Table.Tr></Table.Thead><Table.Tbody>{study.attempts.map(a => <Table.Tr key={a.id}><Table.Td tt="capitalize">{a.phase}</Table.Td><Table.Td>{new Date(a.created_at).toLocaleString()}</Table.Td><Table.Td><Badge color={a.status === 'Succeeded' ? 'teal' : a.status === 'Running' ? 'blue' : 'red'}>{a.status}</Badge>{a.error && <Text size="xs" c="red" maw={500}>{a.error}</Text>}</Table.Td><Table.Td><Button variant="subtle" size="xs" onClick={() => setAttemptId(a.id)}>Inspect</Button></Table.Td></Table.Tr>)}</Table.Tbody></Table></ScrollArea>{!study.attempts.length && <Text size="sm" mt="md">No tests yet. Start with Run development in Study setup & next steps.</Text>}</details>
    {attempt && <details className="wb-card"><summary>Download results and logs</summary><Group mt="sm"><Text fw={600} tt="capitalize">{attempt.phase} · {attempt.status}</Text>{(attempt.status === 'Succeeded' ? ['events.csv', 'events.json', 'result.json', 'manifest.json', 'input.json', 'process.log'] : ['input.json', 'process.log']).map(name => <Button component="a" size="xs" variant="subtle" key={name} href={`${base}/${study.id}/artifacts/${attempt.id}/${name}?download=1`} target="_blank" rel="noreferrer">{name}</Button>)}</Group>{attempt.status === 'Running' && <Text size="sm" mt="sm">Finding patterns and comparing reactions. You can leave this page; the test continues.</Text>}</details>}
    {phases.filter(done).length > 1 && <Text size="xs" c="dimmed">Use Results to view to compare earlier and later tests. A pattern that only looks good in development still needs more evidence.</Text>}
    </>}
  </Stack></div></>;
}
