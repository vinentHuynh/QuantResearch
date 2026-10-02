import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { chromium, expect as baseExpect } from "@playwright/test";
import { commonWindow, defaultPolicy } from "../shared/ts/portfolio.ts";

const origin = "http://127.0.0.1:8001";
const response = await fetch(`${origin}/api/workbench/collective`);
assert.equal(response.status, 200, "The live collective API must be available");
const catalog = await response.json();
const latest = catalog.items.filter(
  (item) => item.working && ["ES", "NQ"].includes(item.symbol),
);
assert.equal(latest.length, 5, "Expected the five refreshed ES/NQ books");
assert.ok(latest.every((item) => item.end >= "2026-09-28"));
const latestEnd = commonWindow(latest).end;
const ym = catalog.items.find((item) => item.working && item.symbol === "YM");
assert.ok(ym, "Expected a YM book for the older three-market combination");
const oldBooks = [...latest, ym];
const oldCopies = Object.fromEntries(oldBooks.map((item) => [item.id, 1]));
const latestIds = latest.map((item) => item.id).sort();
const oldIds = oldBooks.map((item) => item.id).sort();
const staleSettings = {
  capital: 100000,
  copies: oldCopies,
  start: "2024-01-01",
  end: "2026-08-31",
  basis: "marked",
  policy: defaultPolicy,
};

const folder = `reports/latest-es-nq-portfolio-${Date.now()}`;
await mkdir(folder, { recursive: true });
const browser = await chromium.launch({ channel: "msedge" });
const expect = baseExpect.configure({ timeout: 30000 });
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
page.setDefaultTimeout(30000);
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
await page.addInitScript((settings) => {
  if (!localStorage.getItem("quant-collective-v1")) {
    localStorage.setItem("quant-collective-v1", JSON.stringify(settings));
  }
}, staleSettings);

const context = () => page.locator(".wb-context");
const activeSettings = () =>
  page.evaluate(() => {
    const saved = JSON.parse(localStorage.getItem("quant-collective-v1"));
    return {
      ids: Object.entries(saved.copies)
        .filter(([, copies]) => copies > 0)
        .map(([id]) => id)
        .sort(),
      capital: saved.capital,
      start: saved.start,
      end: saved.end,
      basis: saved.basis,
    };
  });
async function expectContext(books, markets, end) {
  await expect(context()).toContainText(`${books} books`);
  await expect(context()).toContainText(`${markets} markets`);
  await expect(context()).toContainText(`2024-01-01 to ${end}`);
  await expect(page.getByTestId("portfolio-metrics")).toBeVisible();
}

try {
  await page.goto(`${origin}/#/portfolio`, { waitUntil: "domcontentloaded" });
  await expectContext(5, 2, latestEnd);
  await expect(page.getByRole("button", { name: "View latest ES/NQ", exact: true })).toHaveCount(0);
  await expect.poll(activeSettings).toEqual({
    ids: latestIds,
    capital: 100000,
    start: "2024-01-01",
    end: latestEnd,
    basis: "marked",
  });
  await page.getByRole("link", { name: "Calendar", exact: true }).click();
  await expect(page.getByRole("region", { name: "Daily P&L calendar" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Calendar month" })).toHaveValue(latestEnd.slice(0, 7));
  const latestDay = page.getByRole("button", { name: new RegExp(`^${latestEnd}:`) });
  await expect(latestDay).toBeEnabled();
  await expect(latestDay).not.toHaveAttribute("aria-label", /Outside test window/);
  await page.screenshot({ path: `${folder}/latest-es-nq-calendar.png`, animations: "disabled" });

  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await page.reload({ waitUntil: "domcontentloaded" });
  await expectContext(5, 2, latestEnd);
  await expect.poll(activeSettings).toEqual({
    ids: latestIds,
    capital: 100000,
    start: "2024-01-01",
    end: latestEnd,
    basis: "marked",
  });
  assert.deepEqual(errors, []);
  await writeFile(
    `${folder}/validation.json`,
    JSON.stringify({
      status: "PASS",
      catalog_generated_at: catalog.generated_at,
      latest_ids: latestIds,
      previous_ids: oldIds,
      latest_end: latestEnd,
      page_errors: errors,
    }, null, 2),
  );
  console.log(`PASS: latest ES/NQ loads automatically, shows its latest coverage, and persists. ${folder}`);
} catch (error) {
  await page.screenshot({ path: `${folder}/failure.png`, animations: "disabled" });
  throw error;
} finally {
  await browser.close();
}
