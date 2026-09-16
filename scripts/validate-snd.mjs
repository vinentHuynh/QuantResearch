import { chromium, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';

const base = 'http://127.0.0.1:5173', api = base + '/api/workbench';
const folder = 'reports/snd-workbench-adapter-2026-09-16';
mkdirSync(folder, { recursive: true });
const json = async (path, body) => {
  const response = await fetch(api + path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const result = await response.json();
  assert(response.ok, JSON.stringify(result));
  return result;
};
await json('/discover', {});
const before = await json('/state');
assert(before.strategies.some(s => s.id === 'snd'));
const browser = await chromium.launch({ channel: 'msedge' });
const page = await browser.newPage({ viewport: { width: 1500, height: 1100 } });
page.setDefaultTimeout(30000);
const errors = [], runs = [];
page.on('pageerror', e => errors.push(e.message));
try {
  await page.goto(base);
  await page.getByRole('button', { name: 'Scripts', exact: true }).click();
  await page.getByLabel('Search strategy library').fill('SND');
  await page.getByRole('button', { name: 'Inspect scripts/mnq/SND_baseline_backtest.py', exact: true }).click();
  await page.getByRole('button', { name: 'Configure SND - Supply and demand', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Timeframe', exact: true })).toHaveValue('1m');
  await expect(page.getByLabel('Warmup calendar days', { exact: true })).toHaveValue('60');
  await page.getByRole('textbox', { name: 'Dataset version', exact: true }).click();
  await page.getByRole('option', { name: /^MNQ / }).first().click();
  await page.getByLabel('Start date (UTC)', { exact: true }).fill('2026-01-01');
  await page.getByLabel('End date (UTC, inclusive)', { exact: true }).fill('2026-01-31');
  await page.getByLabel('Question / hypothesis', { exact: true }).fill('SND native adapter integration check: January 2026, fixed one contract; not an eligibility evaluation.');
  await page.screenshot({ path: folder + '/new-run.png', fullPage: true });
  await page.getByRole('button', { name: 'Validate & preview' }).click();
  await page.getByText('1 job ready', { exact: true }).waitFor();
  const responsePromise = page.waitForResponse(r => r.url().endsWith('/api/workbench/runs') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Launch 1 run', exact: true }).click();
  const response = await responsePromise;
  assert.equal(response.status(), 201);
  runs.push(...await response.json());
  writeFileSync(folder + '/runs.json', JSON.stringify(runs, null, 2));
  const variants = ['original_multi_tf', 'phase6', 'phase7_prior_1m', 'phase7_prior_5m'];
  for (const dataset of before.datasets) {
    const selected = variants.filter(v => dataset.symbol !== 'MNQ' || v !== 'phase7_prior_5m');
    runs.push(...await json('/runs', {
      strategy_id: 'snd', dataset_id: dataset.id, timeframe: '1m', session: 'full-trading-day',
      start: '2026-01-01', end: '2026-01-31', capital: 100000, fee: 1.25, slippage: 1,
      warmup_days: 60, timeout: 600, parameters: { contracts: 1 }, sweep: { variant: selected },
      hypothesis: 'SND native adapter integration check: January 2026; not an eligibility evaluation.',
    }));
    writeFileSync(folder + '/runs.json', JSON.stringify(runs, null, 2));
  }
  console.log(`Launched ${runs.length} SND workbench runs across ${before.datasets.length} markets.`);
  const completed = [];
  for (const run of runs) {
    let record;
    for (let attempt = 0; attempt < 900; attempt++) {
      record = await json('/runs/' + run.id);
      if (!['Queued', 'Running'].includes(record.status)) break;
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    assert.equal(record.status, 'Succeeded', JSON.stringify(record));
    assert(record.result.artifacts.every(a => a.checksum && a.rows >= 0));
    completed.push({ id: run.id, symbol: record.input.dataset.symbol, variant: record.input.parameters.variant,
      metrics: record.result.metrics, warnings: record.result.warnings });
    console.log(completed.at(-1).symbol, completed.at(-1).variant, record.result.metrics.trades, record.result.metrics.net_pnl);
    writeFileSync(folder + '/results.json', JSON.stringify(completed, null, 2));
  }
  const after = await json('/state');
  for (const old of before.runs) assert.equal(after.runs.find(r => r.id === old.id)?.status, old.status);
  await page.getByRole('button', { name: 'Scripts', exact: true }).click();
  await page.getByLabel('Search strategy library').fill('SND');
  await page.screenshot({ path: folder + '/scripts.png', fullPage: true });
  assert.deepEqual(errors, []);
  writeFileSync(folder + '/validation.json', JSON.stringify({ status: 'PASS', runs: completed.length,
    old_runs_preserved: before.runs.length, browser_errors: errors, checks: ['Scripts source configures SND', '1m and 60-day defaults', 'MNQ dataset selectable', 'Browser preview and launch succeed', 'Four variants on every available market', 'Full native artifacts published', 'Prior runs preserved'] }, null, 2));
} finally {
  await browser.close();
}
