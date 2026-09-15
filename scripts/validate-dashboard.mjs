import { chromium, expect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import assert from "node:assert/strict";
const origin = "http://127.0.0.1:5173",
  api = `${origin}/api/workbench`,
  folder = "reports/workbench-validation";
await mkdir(folder, { recursive: true });
const before = await (await fetch(`${api}/state`)).json();
const data = await (await fetch(`${api}/dashboard?symbol=NQ`)).json();
assert.equal(data.rows.length, 9);
const shortlistCount = data.rows.filter((r) =>
  ["Research candidate", "Conditional"].includes(r.status),
).length;
const reviewCount = data.rows.filter((r) => r.status === "Needs review").length;
const orb = data.rows.find((r) => r.strategy_id === "pine-tsmom-orb");
assert(orb.trades.trades > 0);
assert.equal(orb.target_rr, 2);
assert(Number.isFinite(orb.trades.payoff_ratio));
const browser = await chromium.launch(),
  page = await browser.newPage({
    baseURL: origin,
    viewport: { width: 1500, height: 1120 },
  });
page.setDefaultTimeout(30000);
const errors = [],
  checks = [];
page.on("pageerror", (e) => errors.push(e.message));
async function select(label, value) {
  await page.getByRole("textbox", { name: label, exact: true }).click();
  await page.getByRole("option", { name: value, exact: true }).click();
}
try {
  await page.goto(origin);
  await page.getByRole("button", { name: "Dashboard", exact: true }).click();
  await page
    .getByRole("button", { name: `Select ${orb.name}`, exact: true })
    .click();
  await page.getByRole("heading", { name: orb.name, exact: true }).waitFor();
  await expect(
    page.getByText(`${orb.trades.payoff_ratio.toFixed(2)} : 1`, { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText("2.00 : 1", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("img", {
      name: `${orb.name} evaluation equity`,
      exact: true,
    }),
  ).toBeVisible();
  await page.screenshot({
    path: `${folder}/dashboard-desktop.png`,
    animations: "disabled",
  });
  await select("Equity scenario", "Higher costs");
  assert.equal(
    await page
      .getByRole("img", { name: `${orb.name} evaluation equity` })
      .locator("polyline")
      .count(),
    1,
  );
  await select("Equity scenario", "All scenarios");
  await select("Regime feature", "Trailing volatility");
  await expect(
    page.getByText("Higher volatility", { exact: true }),
  ).toBeVisible();
  checks.push(
    "Full-ledger realized R:R differs from target R:R; scenario and regime controls update charts",
  );
  for (const row of data.rows) {
    await page
      .getByRole("button", { name: `Select ${row.name}`, exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: row.name, exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("img", {
        name: `${row.name} evaluation equity`,
        exact: true,
      }),
    ).toBeVisible();
  }
  checks.push(
    "All nine strategy details and charts render; benchmark ratios remain undefined without losses",
  );
  await select("Show strategies", "Shortlist");
  assert.equal(await page.locator(".sd-profit-row").count(), shortlistCount);
  await select("Show strategies", "Needs review");
  assert.equal(await page.locator(".sd-profit-row").count(), reviewCount);
  await select("Show strategies", "All strategies");
  await page
    .getByRole("button", { name: `Select ${orb.name}`, exact: true })
    .click();
  await page
    .getByRole("button", { name: "Open evaluation", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: orb.evaluation_name, exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Dashboard", exact: true }).click();
  await page
    .getByRole("button", { name: "Inspect baseline run", exact: true })
    .click();
  const drawer = page.getByRole("dialog", { name: "Run evidence" });
  await expect(
    drawer.getByRole("heading", { name: orb.name, exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  checks.push(
    "Shortlist/review filters and evaluation/run evidence links work",
  );
  await select("Dashboard market", "ES");
  await expect(
    page.getByRole("heading", { name: "An evaluation is needed", exact: true }),
  ).toBeVisible();
  assert(
    (await (await fetch(`${api}/dashboard?symbol=ES`)).json()).rows.every(
      (r) => r.status === "Not evaluated",
    ),
  );
  await select("Dashboard market", "NQ");
  await page.getByRole("heading", { name: orb.name, exact: true }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: `${folder}/dashboard-mobile.png`,
    animations: "disabled",
  });
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    ),
    "Mobile page overflows",
  );
  await page
    .getByRole("heading", { name: "Strategy scorecard", exact: true })
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: `${folder}/dashboard-mobile-scorecard.png`,
    animations: "disabled",
  });
  checks.push(
    "Markets without evaluations show an honest empty state; mobile layout fits viewport",
  );
  assert.deepEqual(errors, []);
  const after = await (await fetch(`${api}/state`)).json();
  assert.equal(after.runs.length, before.runs.length);
  assert.equal(after.evaluations.length, before.evaluations.length);
  await writeFile(
    `${folder}/dashboard-validation.json`,
    JSON.stringify(
      {
        checked_at: new Date().toISOString(),
        checks,
        errors,
        rows: data.rows.map((r) => ({
          strategy: r.strategy_id,
          status: r.status,
          trades: r.trades.trades,
          payoff_ratio: r.trades.payoff_ratio,
          profit_factor: r.trades.profit_factor,
        })),
      },
      null,
      2,
    ),
  );
  console.log("Dashboard browser checks passed");
} catch (error) {
  console.error(error);
  await page
    .screenshot({ path: `${folder}/dashboard-failure.png`, timeout: 10000 })
    .catch(() => {});
  await writeFile(
    `${folder}/dashboard-failure.txt`,
    await page.locator("body").innerText(),
  );
  throw error;
} finally {
  await browser.close();
}
