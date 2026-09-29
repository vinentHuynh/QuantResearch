import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { readFileSync, createWriteStream, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { chromium, expect } from '@playwright/test';

const { home, study_id } = JSON.parse(readFileSync('reports/event-studies-latest.json', 'utf8'));
const origin = 'http://127.0.0.1:8003';
const output = createWriteStream(join(home, 'browser-api.log'));
const server = spawn(process.execPath, ['server/workbench.ts'], { windowsHide: true, env: { ...process.env, WORKBENCH_HOME: home, WORKBENCH_PORT: '8003' } });
server.stdout.pipe(output, { end: false }); server.stderr.pipe(output, { end: false });
let browser;
const delay = ms => new Promise(done => setTimeout(done, ms));
try {
  for (let i = 0; ; i++) {
    try { const r = await fetch(origin+'/api/workbench/event-studies'); if (r.ok) break; } catch { /* startup */ }
    if (i >= 30) throw new Error('Isolated server failed to start');
    await delay(1000);
  }
  const denied = await fetch(origin+'/api/workbench/event-studies/'+study_id+'/run', { method: 'POST', headers: { Origin: 'https://example.com', 'Content-Type': 'application/json' }, body: JSON.stringify({ phase: 'final' }) });
  assert.equal(denied.status, 403);
  const studies = await (await fetch(origin+'/api/workbench/event-studies')).json();
  const study = studies.studies.find(s => s.id === study_id);
  const artifact = await fetch(`${origin}/api/workbench/event-studies/${study_id}/artifacts/${study.attempts[0].id}/events.csv?download=1`);
  assert.equal(artifact.status, 200); assert.ok(artifact.headers.get('content-disposition').includes('events.csv'));
  browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(origin+'/#/event-studies');
  await expect(page.getByRole('heading', { name: 'Pattern event studies', exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: 'Saved studies', exact: true }).click();
  await page.getByRole('option').filter({ hasText: 'final opened' }).click();
  await page.getByRole('tab', { name: 'Details & charts', exact: true }).click();
  await page.getByText('Detailed statistics', { exact: true }).click();
  await expect(page.getByRole('heading', { name: 'final results', exact: true })).toBeVisible({ timeout: 20000 });
  const finalResult = await (await fetch(`${origin}/api/workbench/event-studies/${study_id}/artifacts/${study.attempts.at(-1).id}/result.json`)).json();
  if (finalResult.recognizers) {
    await page.getByRole('textbox', { name: 'Review pattern', exact: true }).click();
    await page.getByRole('option', { name: 'Show all patterns', exact: true }).click();
  }
  await expect(page.getByRole('img', { name: /detection with confirmation and first touch/ })).toHaveCount(finalResult.samples.length);
  await page.screenshot({ path: join(home, 'desktop.png') });
  await page.getByRole('heading', { name: 'Pattern minus matched control' }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: join(home, 'results.png') });
  await page.getByRole('heading', { name: 'Chart examples' }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: join(home, 'detections.png') });
  await page.getByRole('button', { name: 'New study', exact: true }).click();
  await page.getByLabel('Study name', { exact: true }).fill('Browser workflow verification');
  await page.getByRole('button', { name: 'Validate & preview', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Save study protocol' })).toBeVisible({ timeout: 60000 });
  await page.getByRole('button', { name: 'Save study protocol' }).click();
  await expect(page.getByRole('button', { name: 'Run development', exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Run validation', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Freeze protocol', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Run development', exact: true }).click();
  await page.getByRole('tab', { name: 'Details & charts', exact: true }).click({ timeout: 120000 });
  await expect(page.getByRole('heading', { name: 'What the results mean', exact: true })).toBeVisible({ timeout: 120000 });
  await page.getByText('Detailed statistics', { exact: true }).click();
  await expect(page.getByRole('heading', { name: 'development results', exact: true })).toBeVisible({ timeout: 120000 });
  await page.getByRole('button', { name: 'Study setup & next steps', exact: true }).first().click();
  await page.getByLabel('Visual review record', { exact: true }).fill('Browser test verifies chart rendering; synthetic data only.');
  await page.getByRole('button', { name: 'Record visual review', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Run validation', exact: true })).toBeEnabled();
  await page.reload();
  await page.getByRole('textbox', { name: 'Saved studies', exact: true }).click();
  await page.getByRole('option').filter({ hasText: 'Browser workflow verification' }).first().click();
  await page.getByRole('tab', { name: 'Details & charts', exact: true }).click();
  await page.getByText('Detailed statistics', { exact: true }).click();
  await expect(page.getByRole('heading', { name: 'development results', exact: true })).toBeVisible({ timeout: 20000 });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: join(home, 'mobile.png') });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  assert.equal(overflow, false, 'Mobile document must not overflow horizontally');
  assert.deepEqual(errors, []);
  writeFileSync(join(home, 'browser-checks.json'), JSON.stringify({ passed: true, errors, overflow, screenshots: ['desktop.png', 'results.png', 'detections.png', 'mobile.png'] }, null, 2));
  console.log('Event-study browser checks passed:', resolve(home));
} finally { await browser?.close(); server.kill(); output.end(); }
