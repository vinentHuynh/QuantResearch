import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { chromium, expect } from '@playwright/test';

const { home, study_id } = JSON.parse(readFileSync('reports/pattern-recognition-latest.json', 'utf8'));
const report = JSON.parse(readFileSync(join(home, 'development.json'), 'utf8'));
const browser = await chromium.launch({ channel: 'msedge', headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:8001/#/event-studies');
  await page.getByRole('textbox', { name: 'Saved studies', exact: true }).click();
  await page.getByRole('option').filter({ hasText: 'NQ - all eight pattern recognizers' }).click();
  // Select the saved development phase even if validation was subsequently run.
  await page.getByRole('textbox', { name: 'Results to view', exact: true }).click();
  await page.getByRole('option').filter({ hasText: 'Development — first check' }).click();
  await page.getByRole('tab', { name: 'Details & charts', exact: true }).click();
  await page.getByText('Detailed statistics', { exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Each pattern recognizer', exact: true })).toBeVisible();
  await page.getByRole('heading', { name: 'Each pattern recognizer', exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: join(home, 'recognizer-results.png') });
  const captures = [];
  for (const item of report.patterns) {
    await page.getByRole('textbox', { name: 'Review pattern', exact: true }).click();
    await page.getByRole('option').filter({ hasText: item.name+' (' }).click();
    const charts = page.getByRole('img', { name: /detection with confirmation and first touch/ });
    await expect(charts).toHaveCount(Math.min(2, item.pattern.detected));
    const container = charts.first().locator('..');
    await container.getByText('Why this pattern was recognized', { exact: true }).click();
    await container.scrollIntoViewIfNeeded();
    const path = join(home, item.key+'.png');
    await container.screenshot({ path });
    captures.push({ pattern: item.key, image: path });
  }
  assert.deepEqual(errors, []);
  writeFileSync(join(home, 'browser-recognizers.json'), JSON.stringify({ passed: true, study_id, captures, errors }, null, 2));
  console.log(JSON.stringify({ passed: true, captures }, null, 2));
} finally { await browser.close(); }
