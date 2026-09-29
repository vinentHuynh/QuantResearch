import assert from 'node:assert/strict';
import { chromium, expect } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import { dashboardActionStatus } from '../src/dashboardTypes.ts';
import { strategyTitle } from '../src/strategyTitle.ts';

const origin = 'http://127.0.0.1:8001';
const folder = `reports/review-action-labels-${new Date().toISOString().replaceAll(':','-')}`;
await mkdir(folder, {recursive:true});
const state = await (await fetch(origin + '/api/workbench/state?view=summary')).json();
const data = await (await fetch(origin + '/api/workbench/dashboard?symbol=NQ')).json();
const actions = ['Failed criteria','Retest required','Evidence repair needed','Further testing needed','Incomplete'];
const rows = data.rows.map(row => ({...row,status:dashboardActionStatus(row)}));
const browser = await chromium.launch();
const page = await browser.newPage({viewport:{width:1500,height:1100}});
const errors = [], checks = [];
page.on('pageerror', e => errors.push(e.message));
const select = async (label, value) => {
  await page.getByRole('textbox',{name:label,exact:true}).click();
  await page.getByRole('option',{name:value,exact:true}).click();
};
try {
  await page.goto(origin);
  await page.getByRole('link',{name:'Strategy scorecards',exact:true}).click();
  await page.getByRole('textbox',{name:'Dashboard market',exact:true}).waitFor();
  await select('Dashboard market','NQ');
  for (const row of rows.filter(r => actions.includes(r.status))) {
    await page.getByRole('button',{name:`Select ${strategyTitle(row.name)}`,exact:true}).click();
    await expect(page.locator('.sd-selected').getByText(`Latest evaluation: ${row.status}`,{exact:true})).toBeVisible();
  }
  assert(!/needs review/i.test(await page.locator('body').innerText()));
  await select('Show strategies','Action needed');
  await expect(page.locator('.sd-profit-row')).toHaveCount(rows.filter(r=>actions.includes(r.status)).length);
  await page.screenshot({path:folder+'/scorecards.png'});
  checks.push('Scorecards show specific next actions and filter them correctly, including responses from the existing API.');
  await page.getByRole('link',{name:'Combined portfolio',exact:true}).click();
  await page.getByRole('button',{name:'Add',exact:true}).click();
  await page.locator('.collective-picker label').filter({hasText:/^All tested/}).click();
  const picker=page.getByTestId('strategy-picker');
  await expect(picker.getByText('Backtested',{exact:true}).first()).toBeVisible();
  assert(!/needs review/i.test(await picker.innerText()));
  await page.screenshot({path:folder+'/portfolio-picker.png'});
  checks.push('Configurations without a passing evaluation show Backtested, with original findings preserved.');
  await page.getByRole('button',{name:'Done',exact:true}).click();
  await page.getByRole('link',{name:'Scripts & library',exact:true}).click();
  const name=strategyTitle(state.strategies.find(s=>s.id==='short-term-reversal-minute').name);
  const card=page.locator('section.wb-card').filter({has:page.getByRole('heading',{name,exact:true})});
  await card.getByText('Testing details',{exact:true}).click();
  await expect(card.getByText('Backtested',{exact:true}).first()).toBeVisible();
  await expect(card.getByText(/4 reviewed · 0 awaiting review/)).toBeVisible();
  checks.push('Completed script reviews remain completed and retain all four risk failures.');
  assert.deepEqual(errors,[]);
  const after=await(await fetch(origin+'/api/workbench/state?view=summary')).json();
  assert.equal(after.runs.length,state.runs.length);
  assert.equal(after.evaluations.length,state.evaluations.length);
  await writeFile(folder+'/validation.json',JSON.stringify({checks,errors,statuses:rows.map(r=>({id:r.strategy_id,status:r.status}))},null,2));
  console.log(JSON.stringify({checks,errors},null,2));
} catch(error) {
  await page.screenshot({path:folder+'/failure.png'});
  throw error;
} finally { await browser.close(); }
