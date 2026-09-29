// Read-only check of the summary percentages against saved results.
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { chromium, expect } from '@playwright/test';

const origin = 'http://127.0.0.1:8001';
const base = origin+'/api/workbench/event-studies';
const studies = (await (await fetch(base)).json()).studies;
const study = studies.find(s => s.protocol.name === 'NQ - all eight pattern recognizers');
assert.ok(study);
const attempt = study.attempts.find(a => a.phase === 'validation' && a.status === 'Succeeded');
assert.ok(attempt);
const path = `/${study.id}/artifacts/${attempt.id}/result.json`;
const result = await (await fetch(base+path)).json();
const report = resolve('reports', `pattern-summary-${Date.now()}`);
mkdirSync(report, { recursive: true });
const browser = await chromium.launch({ channel: 'msedge', headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const errors = []; let writes = 0;
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', r => { if (r.method() === 'POST') writes++; });
  await page.goto(origin+'/#/event-studies');
  await page.getByRole('textbox', { name: 'Saved studies', exact: true }).click();
  await page.getByRole('option').filter({ hasText: study.protocol.name }).click();
  await expect(page.getByRole('tab', { name: 'Summary', exact: true })).toHaveAttribute('aria-selected', 'true', { timeout: 30000 });
  const summary = page.getByRole('region', { name: 'Pattern validity summary', exact: true });
  await expect(summary).toBeVisible();
  await expect(summary.getByRole('article')).toHaveCount(8);
  for (const r of result.recognizers) {
    const card = summary.getByRole('article', { name: r.name, exact: true });
    const n = r.pattern.reaction_denominator;
    const expected = n ? `${(r.pattern.counts.rejection/n*100).toFixed(1)}%` : '—';
    await expect(card.getByTestId('bounce-percentage')).toHaveText(expected);
    if (n) await expect(card.getByText(`${r.pattern.counts.rejection} of ${n} measured returns bounced`, { exact: true })).toBeVisible();
    if (!n) await expect(card.getByText('Not enough data', { exact: true })).toBeVisible();
  }
  const sparse = summary.getByRole('article', { name: 'Supply zone', exact: true });
  await expect(sparse.getByTestId('bounce-percentage')).toHaveText('100.0%');
  await expect(sparse.getByText('Too little evidence to judge', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'What the results mean' })).toHaveCount(0);
  await page.screenshot({ path: join(report, 'desktop.png') });
  await summary.screenshot({ path: join(report, 'percentages.png') });
  await page.getByRole('tab', { name: 'Details & charts', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Chart examples', exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Summary', exact: true }).click();
  await expect(summary).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await summary.scrollIntoViewIfNeeded();
  await page.screenshot({ path: join(report, 'mobile.png') });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth+1), false);

  // A completed, unresolved reaction stays in the denominator. A zero rate must
  // display as 0%, distinct from an unavailable rate with no measured returns.
  const fixture = structuredClone(result);
  const support = fixture.recognizers.find(r => r.key === 'support');
  support.pattern = { ...support.pattern, reaction_denominator: 10, rejection_rate: 0,
    counts: { ...support.pattern.counts, rejection: 0, failure: 4, unresolved: 6 } };
  const resistance = fixture.recognizers.find(r => r.key === 'resistance');
  resistance.pattern = { ...resistance.pattern, reaction_denominator: 10, rejection_rate: .3,
    counts: { ...resistance.pattern.counts, rejection: 3, failure: 2, unresolved: 5 } };
  await page.route(base+path, route => route.fulfill({ json: fixture }));
  await page.reload();
  await expect(summary.getByRole('article', { name: 'Support', exact: true }).getByTestId('bounce-percentage')).toHaveText('0.0%');
  await expect(summary.getByRole('article', { name: 'Resistance', exact: true }).getByTestId('bounce-percentage')).toHaveText('30.0%');
  assert.deepEqual(errors, []);
  assert.equal(writes, 0);
  writeFileSync(join(report, 'checks.json'), JSON.stringify({ passed: true, patterns: 8, errors, writes, checks: ['saved percentages reconcile', 'zero versus missing', 'one-observation caution', 'unresolved denominator', 'summary/details tabs', 'mobile layout'] }, null, 2));
  console.log('Pattern percentage summary passed:', report);
} finally { await browser.close(); }
