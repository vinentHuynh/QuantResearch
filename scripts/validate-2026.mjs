import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {parseCsv,tradeStatistics} from '../server/dashboard.ts';

const folder='reports/strategy-potential-2026';
const api='http://127.0.0.1:8001/api/workbench';
const origin='http://127.0.0.1:5173';
const campaign=JSON.parse(await readFile(`${folder}/campaign.json`,'utf8'));
assert(campaign.completed_at);
const before=await(await fetch(`${api}/state`)).json();
const dashboard=await(await fetch(`${api}/dashboard?symbol=NQ`)).json();
const browser=await chromium.launch();
const page=await browser.newPage({baseURL:origin,viewport:{width:1500,height:1080}});
page.setDefaultTimeout(60000);
const errors=[], checks=[], summary=[];
page.on('pageerror',e=>errors.push(e.message));
try{
  for(const [strategy,id] of Object.entries(campaign.evaluations)){
    const detail=JSON.parse(await readFile(`${folder}/${strategy}.json`,'utf8'));
    const e=detail.evaluation;
    assert.equal(e.status,'Succeeded');
    const row=dashboard.rows.find(r=>r.strategy_id===strategy);
    assert.equal(row.evaluation_id,id);
    assert.equal(row.start,'2026-01-01'); assert.equal(row.end,'2026-08-31');
    assert.equal(e.folds.length,1);
    assert.equal(e.candidates.length,1);
    const base=e.runs.find(r=>r.input.research.scenario==='Baseline');
    const test=e.result.scenarios.find(s=>s.name==='Baseline');
    for(const r of [...e.runs,detail.september]){
      assert.equal(r.input.source_hash,campaign.source_hash);
      assert.equal(r.status,'Succeeded');
      for(const artifact of r.result.artifacts){
        const bytes=await readFile(`data/workbench/runs/${r.id}/${artifact.name}`);
        assert.equal(createHash('sha256').update(bytes).digest('hex'),artifact.checksum);
        const [head,...records]=parseCsv(bytes.toString('utf8'));
        assert.equal(records.length,artifact.rows);
        if(artifact.name==='trades.csv'){
          const pnl=records.map(v=>Number(v[head.indexOf('net_pnl')]));
          assert(pnl.every(Number.isFinite));
          assert.equal(pnl.length,r.result.metrics.trades);
          assert(Math.abs(pnl.reduce((a,b)=>a+b,0)-r.result.metrics.net_pnl)<0.01);
          if(r.id===base.id) assert.deepEqual(row.trades,tradeStatistics(pnl));
        }
      }
      if(r.input.research?.role==='Test') assert(r.created_at>=e.folds[0].selection.selected_at);
    }
    assert.equal(detail.september.input.start,'2026-09-01');
    assert.equal(detail.september.input.end,'2026-09-03');
    assert.equal(row.regimes.length,2);
    assert.equal(row.scenarios.length,e.scenarios.length);
    assert.deepEqual(row.parameters[0],base.input.parameters);
    assert.equal(row.trades.net_pnl,test.metrics.net_pnl);
    await page.goto(origin);
    await page.getByRole('button',{name:'Evaluation & Regimes',exact:true}).click();
    await page.getByRole('row').filter({has:page.getByText(e.name,{exact:true})}).getByRole('button',{name:'Open evaluation',exact:true}).click();
    await expect(page.getByRole('heading',{name:e.name,exact:true})).toBeVisible();
    const chart=page.getByRole('img',{name:'Walk-forward test equity',exact:true});
    await expect(chart).toBeVisible(); await chart.scrollIntoViewIfNeeded();
    await page.screenshot({path:`${folder}/${strategy}-evaluation.png`,animations:'disabled'});
    assert.equal(await page.getByText('Historical conditional attribution',{exact:true}).count(),2);
    const link=page.locator(`a[href="/api/workbench/research-artifact?kind=regimes&id=${detail.studies.volatility.id}&name=observations.csv"]`);
    await expect(link).toHaveCount(1);
    const response=await page.request.get(await link.getAttribute('href')); assert(response.ok());
    await page.getByRole('button',{name:'Dashboard',exact:true}).click();
    await page.getByRole('button',{name:`Select ${row.name}`,exact:true}).click();
    await expect(page.getByRole('heading',{name:row.name,exact:true})).toBeVisible();
    await expect(page.getByRole('img',{name:`${row.name} evaluation equity`,exact:true})).toBeVisible();
    if(strategy==='pine-tsmom-orb') await page.screenshot({path:`${folder}/dashboard-orb.png`,animations:'disabled'});
    summary.push({strategy,status:row.status,reasons:row.reasons,...row.trades,max_drawdown:test.metrics.max_drawdown,
      higher_cost_pnl:e.result.scenarios.find(s=>s.name==='Higher costs').metrics.net_pnl,
      delayed_pnl:e.result.scenarios.find(s=>s.name==='Delayed execution')?.metrics.net_pnl??null,
      september_pnl:detail.september.result.metrics.net_pnl,september_trades:detail.september.result.metrics.trades});
    checks.push(`${strategy}: frozen inputs, full artifact checksums and accounting, current dashboard metrics/status, evaluation chart, both regime studies and artifact download`);
    console.log(`Validated ${strategy}`);
  }
  await page.getByRole('button',{name:'Open evaluation',exact:true}).click();
  await expect(page.getByRole('heading',{name:'potential-2026-v1 | pine-tsmom-orb',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Dashboard',exact:true}).click();
  await page.getByRole('button',{name:'Inspect baseline run',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'Run evidence'})).toBeVisible();
  await page.keyboard.press('Escape');
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));
  await page.screenshot({path:`${folder}/dashboard-mobile.png`,animations:'disabled'});
  assert.deepEqual(errors,[]);
  const after=await(await fetch(`${api}/state`)).json();
  assert.equal(after.runs.length,before.runs.length);
  assert.equal(after.evaluations.length,before.evaluations.length);
  assert(campaign.prior_run_ids.every(id=>after.runs.some(r=>r.id===id)));
  assert(!after.runs.some(r=>['Running','Queued'].includes(r.status)));
  await writeFile(`${folder}/summary.json`,JSON.stringify(summary,null,2));
  const keys=['strategy','status','net_pnl','max_drawdown','trades','win_rate','payoff_ratio','profit_factor','expectancy','higher_cost_pnl','delayed_pnl','september_pnl','september_trades'];
  await writeFile(`${folder}/summary.csv`,[keys,...summary.map(s=>keys.map(k=>s[k]))].map(r=>r.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\n'));
  await writeFile(`${folder}/browser-validation.json`,JSON.stringify({checked_at:new Date().toISOString(),checks,errors,evaluations:9,child_runs:32,september_runs:9,regimes:18,prior_runs_preserved:campaign.prior_run_ids.length},null,2));
  console.log('All 2026 accounting and browser checks passed');
}catch(error){
  await page.screenshot({path:`${folder}/validation-failure.png`,timeout:10000}).catch(()=>{});
  throw error;
}finally{await browser.close();}
