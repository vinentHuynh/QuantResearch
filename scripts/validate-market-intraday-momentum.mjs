import assert from 'node:assert/strict';
import { chromium, expect } from '@playwright/test';
import { writeFile } from 'node:fs/promises';

// Read-only UI smoke: open the adapter and configuration; do not launch runs.
const folder = 'reports/market-intraday-momentum-2026-09-17';
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1500, height: 1100 } });
const errors = [];
page.on('pageerror', e => errors.push(e.message));
try {
  await page.goto('http://127.0.0.1:8001/#scripts', { waitUntil: 'domcontentloaded', timeout: 90000 });
  const card = page.locator('section.wb-card').filter({ has: page.getByRole('heading', { name: 'Market intraday momentum - last 30 minutes', exact: true }) });
  await expect(card).toBeVisible({ timeout: 120000 });
  await card.scrollIntoViewIfNeeded();
  await card.screenshot({ path: folder+'/strategy-card.png' });
  await card.getByRole('button', { name: 'Configure run', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Strategy', exact: true })).toHaveValue('Market intraday momentum - last 30 minutes');
  await expect(page.getByText('Signal adapter scope', { exact: true })).toBeVisible();
  await page.screenshot({ path: folder+'/configuration.png' });
  assert.deepEqual(errors, []);
  await writeFile(folder+'/browser-validation.json', JSON.stringify({ passed: true, checks: ['Adapter visible in runnable scripts', 'Configure run selects the new adapter', 'Execution scope visible', 'No page errors'], errors }, null, 2));
  console.log('Closing momentum UI smoke passed');
} finally {
  await browser.close();
}
