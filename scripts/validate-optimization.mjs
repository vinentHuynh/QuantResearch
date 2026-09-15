import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";

const folder = "reports/strategy-optimization-2022-2024";
const campaign = JSON.parse(await readFile(`${folder}/campaign.json`, "utf8"));
assert(
  campaign.completed_at,
  "Finish the campaign before final browser validation",
);
const origin = "http://127.0.0.1:5173";
const api = `${origin}/api/workbench`;
const state = await (await fetch(`${api}/state`)).json();
const errors = [],
  checks = [];
const stages = ["validation", "holdout", "stress", "transfer"];
const campaignIds = [
  ...Object.values(campaign.groups).flat(),
  ...stages.flatMap((stage) => Object.values(campaign[stage])),
];
assert.equal(new Set(campaignIds).size, 69);
assert(
  campaignIds.every(
    (id) => state.runs.find((r) => r.id === id)?.status === "Succeeded",
  ),
);
for (const [strategy, selected] of Object.entries(campaign.selections)) {
  for (const stage of stages) {
    const run = state.runs.find((r) => r.id === campaign[stage][strategy]);
    assert.deepEqual(run.input.parameters, selected.parameters);
    assert.equal(run.input.source_hash, selected.source_hash);
    assert.equal(
      run.input.start,
      stage === "validation" ? "2023-01-01" : "2024-01-01",
    );
    assert.equal(
      run.input.end,
      stage === "validation" ? "2023-12-31" : "2024-12-31",
    );
    assert.equal(run.input.dataset.symbol, stage === "transfer" ? "ES" : "NQ");
  }
  const base = state.runs.find((r) => r.id === campaign.holdout[strategy])
    .result.metrics;
  const stress = state.runs.find((r) => r.id === campaign.stress[strategy])
    .result.metrics;
  assert.equal(stress.trades, base.trades);
  assert(
    Math.abs(stress.costs - 2 * base.costs) < 0.01,
    `${strategy}: cost stress did not double costs`,
  );
  assert(
    Math.abs(stress.net_pnl - (base.net_pnl - base.costs)) < 0.01,
    `${strategy}: cost stress did not reconcile`,
  );
}
checks.push(
  "All 69 completed configurations accounted for; frozen parameters, sources, years and markets verified; doubled-cost P&L reconciles for all nine strategies",
);
const browser = await chromium.launch();
const page = await browser.newPage({
  baseURL: origin,
  viewport: { width: 1500, height: 1080 },
});
page.setDefaultTimeout(30000);
page.on("pageerror", (e) => errors.push(e.message));
try {
  for (const [strategy, id] of Object.entries(campaign.holdout)) {
    const run = state.runs.find((r) => r.id === id);
    await page.goto(origin);
    await page.getByLabel("Search runs", { exact: true }).fill(id);
    await page.getByRole("button", { name: "Inspect", exact: true }).click();
    const drawer = page.getByRole("dialog", { name: "Run evidence" });
    await expect(
      drawer.getByRole("heading", {
        name: run.input.strategy.name,
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      drawer.getByRole("img", { name: "Equity curve in US dollars" }),
    ).toBeVisible();
    for (const artifact of ["equity.csv", "trades.csv", "positions.csv"]) {
      const link = drawer.getByRole("link", { name: artifact, exact: true });
      const response = await page.request.get(await link.getAttribute("href"));
      assert(response.ok(), `${strategy}: ${artifact} download failed`);
      assert((await response.text()).length > 20);
    }
    const exported = await page.request.get(
      await drawer
        .getByRole("link", { name: "Export evidence JSON" })
        .getAttribute("href"),
    );
    assert.equal((await exported.json()).run.id, id);
    await drawer
      .getByRole("button", { name: "Delete run", exact: true })
      .click();
    await expect(
      page.getByRole("dialog", { name: "Review run deletion" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Keep runs", exact: true }).click();
    await page.screenshot({
      path: `${folder}/${strategy}-evidence.png`,
      animations: "disabled",
    });
    checks.push(
      `${strategy}: chart, CSV downloads, evidence export, deletion preview cancellation`,
    );
    // A saved preset must restore the selected configuration and pass preflight.
    await page.goto(origin);
    await page.getByRole("button", { name: "New Run", exact: true }).click();
    await page
      .getByRole("textbox", { name: "Load saved preset", exact: true })
      .click();
    const preset = state.presets.find(
      (p) => p.id === campaign.presets[strategy],
    );
    await page.getByRole("option", { name: preset.name, exact: true }).click();
    const preview = page.waitForResponse(
      (r) => r.url().endsWith("/preview") && r.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: "Validate & preview", exact: true })
      .click();
    const response = await preview;
    assert(response.ok());
    assert.deepEqual((await response.json()).parameters, [
      campaign.selections[strategy].parameters,
    ]);
    await expect(page.getByText("1 job ready", { exact: true })).toBeVisible();
    checks.push(
      `${strategy}: saved preset restores frozen parameters and validates`,
    );
    console.log(`Validated ${strategy}`);
  }
  await page.goto(origin);
  for (const strategy of ["moving-average", "multi-speed-momentum"]) {
    await page
      .getByRole("checkbox", {
        name: `Compare ${campaign.holdout[strategy]}`,
        exact: true,
      })
      .check();
  }
  await page
    .getByRole("button", { name: "Compare as run", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "As run comparison", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Align evaluation interval", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Aligned comparison", exact: true }),
  ).toBeVisible();
  checks.push(
    "Compatible holdout runs compare both as run and on an aligned interval",
  );
  await page.screenshot({
    path: `${folder}/comparison.png`,
    animations: "disabled",
  });
  const interrupted = state.runs.find((r) => r.status === "Interrupted");
  if (interrupted) {
    await page.goto(origin);
    for (const id of [interrupted.id, campaign.holdout["buy-hold"]])
      await page
        .getByRole("checkbox", { name: `Compare ${id}`, exact: true })
        .check();
    await expect(
      page.getByRole("button", { name: "Compare as run", exact: true }),
    ).toBeDisabled();
    await page
      .getByRole("button", { name: "Delete selected", exact: true })
      .click();
    await expect(
      page.getByRole("dialog", { name: "Review run deletion" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Keep runs", exact: true }).click();
    checks.push(
      "Interrupted runs support bulk deletion preview; comparison is disabled for mixed statuses",
    );
  }
  const after = await (await fetch(`${api}/state`)).json();
  assert.equal(
    after.runs.length,
    state.runs.length,
    "Read-only checks changed the run ledger",
  );
  assert.deepEqual(errors, []);
  await writeFile(
    `${folder}/browser-validation.json`,
    JSON.stringify(
      {
        checked_at: new Date().toISOString(),
        checks,
        errors,
        runs: after.runs.length,
      },
      null,
      2,
    ),
  );
} catch (error) {
  await page.screenshot({
    path: `${folder}/validation-failure.png`,
    fullPage: true,
  });
  await writeFile(
    `${folder}/validation-failure.txt`,
    await page.locator("body").innerText(),
  );
  throw error;
} finally {
  await browser.close();
}
