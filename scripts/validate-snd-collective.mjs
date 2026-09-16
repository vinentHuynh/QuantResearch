import { chromium, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { calculatePortfolio, defaultPolicy } from '../src/collectiveModel.ts';

const base = 'http://127.0.0.1:5173', api = base + '/api/workbench';
const folder = 'reports/snd-workbench-adapter-2026-09-16';
const catalog = await (await fetch(api + '/collective')).json();
const items = catalog.items.filter(i => i.source === 'Current workbench' && i.key.startsWith('snd__'));
assert.equal(items.length, 20);
assert(items.every(i => !i.working && !i.feasible));
assert.equal(catalog.errors.length, 0);
const histories = await (await fetch(api + '/collective/series', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids: items.map(i => i.id) }) })).json();
const portfolio = calculatePortfolio(items, histories, Object.fromEntries(items.map(i => [i.id, 1])), '2026-01-01', '2026-01-31', 'marked', defaultPolicy);
const expected = JSON.parse(readFileSync(folder + '/results.json', 'utf8')).reduce((sum, r) => sum + r.metrics.net_pnl, 0);
assert(Math.abs(portfolio.net - expected) < 1e-6);
const browser = await chromium.launch({ channel: 'msedge' });
const page = await browser.newPage({ viewport: { width: 1500, height: 1100 } });
page.setDefaultTimeout(30000);
const errors = [];
page.on('pageerror', e => errors.push(e.message));
const select = async (label, option) => {
  await page.getByRole('textbox', { name: label, exact: true }).click();
  await page.getByRole('option', { name: option, exact: true }).click();
};
try {
  await page.goto(base);
  await page.getByRole('button', { name: 'Dashboard', exact: true }).click();
  await select('Eligibility filter', 'All tested configurations');
  await page.getByLabel('Find a strategy', { exact: true }).fill('SND');
  await select('Chart timeframe', '1m');
  await expect(page.getByTestId('strategy-picker').locator('tbody tr')).toHaveCount(20);
  await page.getByRole('button', { name: 'Apply visible strategies (20)', exact: true }).click();
  await page.getByRole('button', { name: 'Use common tested window', exact: true }).click();
  await expect(page.getByTestId('selected-count')).toHaveText('20 selected');
  await expect(page.getByTestId('portfolio-metrics').getByText(expected.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }), { exact: true })).toBeVisible();
  await expect(page.getByTestId('market-contributions').locator('tbody tr')).toHaveCount(5);
  await page.getByTestId('portfolio-metrics').scrollIntoViewIfNeeded();
  await page.screenshot({ path: folder + '/collective-all-markets.png' });
  await page.getByRole('heading', { name: 'Daily P&L calendar', exact: true }).scrollIntoViewIfNeeded();
  await page.getByRole('button', { name: /^2026-01-05:/ }).click();
  await page.screenshot({ path: folder + '/collective-calendar.png' });
  await page.getByRole('button', { name: 'Clear combination', exact: true }).click();
  for (const variant of ['phase6', 'original multi tf']) {
    await page.getByRole('checkbox', { name: `Include SND - Supply and demand / ${variant} MNQ 1m Current workbench`, exact: true }).check();
  }
  await expect(page.getByTestId('portfolio-metrics').getByText('$1,228.50', { exact: true })).toBeVisible();
  await expect(page.getByTestId('selected-count')).toHaveText('2 selected');
  await select('Eligibility filter', /^Working/);
  await expect(page.getByTestId('strategy-picker').locator('tbody tr')).toHaveCount(0);
  assert.deepEqual(errors, []);
  writeFileSync(folder + '/collective-validation.json', JSON.stringify({ status: 'PASS', imported: items.length, total_catalog: catalog.items.length,
    all_markets_combined_net: portfolio.net, represented_capital: portfolio.capital, mnq_two_variant_net: 1228.5,
    checks: ['Twenty named SND configurations imported with checksummed full ledgers', 'Combined net matches native run totals', 'Five market contributions visible', 'January calendar and daily drilldown work', 'Two MNQ variants combine correctly', 'Unqualified SND runs excluded from Working'], browser_errors: errors }, null, 2));
} finally { await browser.close(); }
