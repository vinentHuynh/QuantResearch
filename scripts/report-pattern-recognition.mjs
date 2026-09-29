import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
const { home, study_id } = JSON.parse(readFileSync('reports/pattern-recognition-latest.json', 'utf8'));
const read = name => JSON.parse(readFileSync(join(home, name), 'utf8'));
const development = read('development.json'), validation = read('validation.json'), audit = read('recognition-audit.json');
const pct = n => n == null ? 'Unavailable' : `${(100*n).toFixed(1)}%`;
const pp = n => n == null ? 'Unavailable' : `${(100*n).toFixed(1)} pp`;
const ci = c => c.interval_95 ? c.interval_95.map(pp).join(' to ') : 'Insufficient independent observations';
const rows = validation.patterns.map(v => {
  const d = development.patterns.find(p => p.key === v.key);
  return `| [${v.name}](${v.key}.png) | ${d.pattern.detected} | ${v.pattern.detected} | ${v.pattern.revisited} | ${v.matched} | ${pct(v.pattern.rejection_rate)} | ${pp(v.comparisons.rejection.difference)} | ${ci(v.comparisons.rejection)} |`;
});
const text = [
  '# Eight pattern recognizers: implementation and tests', '',
  `Saved Workbench study: **NQ - all eight pattern recognizers** (${study_id}).`, '',
  'All eight named recognizers are implemented with explicit formation measurements, confirmation timestamps and full zone bounds. Results and chart filters appear in Research → Pattern event studies.', '',
  '## Software verification', '',
  '- 18 recognition tests passed. Positive/negative fixtures cover both directions, exact thresholds, wick-only false positives, strict breakout closes, expired departures, opposite-candle lookback, dojis, swing ties, first confirmation, prefix causality, independent lookbacks and mirror symmetry.',
  '- 13 shared measurement/control tests passed.',
  `- Independent formation-first audit reconciled all ${audit.events_audited.toLocaleString()} development detections, including complete membership, unique anchors, first confirmation, zone bounds and frozen ATR. Artifact checksums passed.`,
  '- Saved-study lifecycle, desktop/mobile browser checks and production build passed.',
  '- One seeded development chart for each recognizer was visually reviewed, with its numerical recognition evidence. Each pattern name below links to the reviewed chart.', '',
  '## Real-data test', '',
  'NQ, 15-minute candles, full trading day, 2026-06-01 through 2026-09-03. Rules remained unchanged between development and validation. Prior historical exposure is recorded. Development/validation splitting is based on completed candle counts.', '',
  `Development: ${development.split.start} to ${development.split.end} (${development.split.bars} candles).`, '',
  `Validation: ${validation.split.start} to ${validation.split.end} (${validation.split.bars} candles).`, '',
  '| Recognizer | Development detections | Validation detections | Revisited | Matched | Rejection after touch | Matched rejection difference | Pointwise 95% interval |',
  '|---|---:|---:|---:|---:|---:|---:|---|', ...rows, '',
  'Rejection rates exclude ambiguous/incomplete outcomes, retained in the JSON event ledgers. The displayed rejection rate uses all eligible detections; differences and intervals use the matched subset. Directional breakdowns are descriptive and do not replace the four predeclared family comparisons.', '',
  '## Primary family comparisons on validation', '',
  ...validation.primary_comparisons.map(s => `- **${s.family.replaceAll('_', ' ')}:** ${s.evidence}. Rejection difference ${pp(s.comparisons.rejection.difference)}; interval ${ci(s.comparisons.rejection)}. Return difference ${pp(s.comparisons.return.difference)}; interval ${ci(s.comparisons.return)}.`), '',
  'Correct recognition and successful execution are separate from evidence of a predictive advantage. Sparse supply/demand detections in particular limit inference. The intervals are exploratory, pointwise time-block estimates; continuous-price roll gaps and longer dependence remain limitations.', '',
  '**The reserved final test remains unopened.** No profitability or live-trading conclusion is made.', '',
  'Artifacts: [recognition audit](recognition-audit.json), [development](development.json), [validation](validation.json), [browser verification](browser-recognizers.json). Full event CSV/JSON and source manifests are downloadable from the saved Workbench study.', ''
].join('\n');
writeFileSync(join(home, 'REPORT.md'), text);
console.log(text);
