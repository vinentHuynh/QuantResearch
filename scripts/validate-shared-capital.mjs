import assert from "node:assert/strict";
import { chromium, expect as baseExpect } from "@playwright/test";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { defaultPolicy } from "../shared/ts/portfolio.ts";

const origin = "http://127.0.0.1:5173";
const folder = `reports/shared-capital-${Date.now()}`;
await mkdir(folder, { recursive: true });
const catalog = await (await fetch(origin + "/api/workbench/collective")).json();
const items = catalog.items.filter((item) => item.working);
const legacy = { copies: Object.fromEntries(items.map((item) => [item.id, 1])),
  start: "2024-01-01", end: "2026-08-31", basis: "marked", policy: defaultPolicy };
const browser = await chromium.launch({ channel: "msedge" });
const page = await browser.newPage({ viewport: { width: 1500, height: 1050 } });
const expect = baseExpect.configure({ timeout: 30000 });
page.setDefaultTimeout(30000);
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
await page.addInitScript((settings) => {
  if (!localStorage.getItem("quant-collective-v1"))
    localStorage.setItem("quant-collective-v1", JSON.stringify(settings));
}, legacy);
const capital = () => page.getByLabel("Starting capital (USD)", { exact: true });
const metrics = () => page.getByTestId("portfolio-metrics");
try {
  await page.goto(origin + "/#/portfolio");
  await expect(capital()).toHaveValue("100000");
  await expect(metrics()).toBeVisible();
  const net = items.reduce((sum, item) => sum + item.recent_pnl, 0);
  const money = n => n.toLocaleString("en-US", { style: "currency", currency: "USD" });
  await expect(metrics().getByText(money(net), { exact: true })).toBeVisible();
  await expect(metrics()).toContainText(`${(net / 100000 * 100).toFixed(2)}% on total portfolio capital`);
  await expect(page.getByTestId("portfolio-capital")).toHaveCount(0);
  await expect(page.getByTestId("portfolio-equity")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Portfolio account" })).toHaveCount(0);
  await capital().fill("200000");
  await expect(metrics()).toContainText(`${(net / 200000 * 100).toFixed(2)}% on total portfolio capital`);
  await expect(metrics().getByText(money(net), { exact: true })).toBeVisible();
  await page.reload();
  await expect(capital()).toHaveValue("200000");
  await expect(metrics()).toBeVisible();
  await page.screenshot({ path: folder + "/overview.png", animations: "disabled" });
  const copies = page.getByRole("textbox", { name: /^Copies of / }).first();
  await copies.fill("2");
  await copies.blur();
  await expect(capital()).toHaveValue("200000");
  await page.getByRole("button", { name: /^Remove / }).first().click();
  await expect(page.getByTestId("selected-count")).toContainText(`${items.length - 1} books`);
  await expect(capital()).toHaveValue("200000");
  await expect(metrics()).toBeVisible();
  const download = async (button, filename) => {
    const pending = page.waitForEvent("download");
    await page.getByRole("button", { name: button, exact: true }).click();
    const artifact = await pending;
    await artifact.saveAs(folder + "/" + filename);
    return readFile(folder + "/" + filename, "utf8");
  };
  const combination = JSON.parse(await download("Combination JSON", "combination.json"));
  assert.equal(combination.version, 2);
  assert.equal(combination.capital_model, "shared");
  assert.equal(combination.capital, 200000);
  assert.equal(combination.results.capital, 200000);
  const rows = (await download("Daily P&L CSV", "daily.csv")).trim().split(/\r?\n/).map(row => row.split(","));
  const headers = rows.shift();
  const last = Object.fromEntries(headers.map((header, i) => [header, Number(rows.at(-1)[i])]));
  assert.equal(last.starting_capital, 200000);
  assert.ok(Math.abs(last.equity - 200000 - last.cumulative_pnl) < 1e-6);
  await page.getByRole("link", { name: "Contributions", exact: true }).click();
  await expect(page.getByRole("columnheader", { name: "Return contribution", exact: true })).toBeVisible();
  const contributions = page.getByTestId("strategy-contributions");
  for (const name of ["Strategy", "Chart", "Maximum drawdown"])
    await expect(contributions.getByRole("columnheader", { name, exact: true })).toBeVisible();
  await expect(contributions.getByRole("columnheader", { name: "Strategy / chart", exact: true })).toHaveCount(0);
  const remaining = items.slice(1);
  const histories = await (await fetch(origin + "/api/workbench/collective/series", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids: remaining.map(item => item.id) }),
  })).json();
  for (const [index, item] of remaining.entries()) {
    const row = contributions.locator("tbody tr").nth(index);
    await expect(row.locator("td").nth(1)).toContainText(`${item.symbol} · ${item.timeframe}`);
    const history = histories.find(history => history.id === item.id);
    let cumulative = 0, peak = 0, drawdown = 0;
    for (const mark of history.daily.filter(mark => mark.date >= legacy.start && mark.date <= legacy.end).sort((a, b) => a.date.localeCompare(b.date))) {
      cumulative += mark.pnl;
      peak = Math.max(peak, cumulative);
      drawdown = Math.max(drawdown, peak - cumulative);
    }
    await expect(row.locator("td").nth(3)).toHaveText(money(drawdown));
  }
  await page.screenshot({ path: folder + "/contributions.png", animations: "disabled" });
  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await expect(capital()).toHaveValue("200000");
  await capital().fill("150000");
  await page.reload();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await expect(page.getByTestId("selected-count")).toContainText(`${items.length - 1} books`);
  await expect(capital()).toHaveValue("150000");
  await capital().scrollIntoViewIfNeeded();
  await page.screenshot({ path: folder + "/mobile-capital.png", animations: "disabled" });
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem("quant-collective-v1")));
  assert.equal(saved.capital, 150000);
  assert.deepEqual(errors, []);
  await writeFile(folder + "/validation.json", JSON.stringify({ status: "PASS", checks: [
    "Legacy settings without capital default to $100,000 total",
    "Overview balance cards removed; Combination capital edits update returns, preserve P&L and survive reload",
    "Copies and removing strategies preserve shared capital",
    "Strategy and Chart are separate; every displayed drawdown reconciles with its daily history",
    "JSON and CSV exports retain shared capital and reconcile equity",
    "Mobile Combination capital edits persist and use the same shared balance",
  ], errors }, null, 2));
  console.log(`PASS: shared capital desktop/mobile validation. ${folder}`);
} finally { await browser.close(); }
