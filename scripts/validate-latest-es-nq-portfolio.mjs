import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { chromium, expect as baseExpect } from "@playwright/test";
import { defaultPolicy } from "../shared/ts/portfolio.ts";

const origin = "http://127.0.0.1:8001";
const response = await fetch(`${origin}/api/workbench/collective`);
assert.equal(response.status, 200, "The live collective API must be available");
const catalog = await response.json();
const latest = catalog.items.filter(
  (item) => item.working && ["ES", "NQ"].includes(item.symbol),
);
const ym = catalog.items.find((item) => item.working && item.symbol === "YM");
assert.equal(latest.length, 5, "Expected the five refreshed ES/NQ books");
assert.ok(ym, "Expected a YM book for the older three-market combination");
assert.ok(latest.every((item) => item.end >= "2026-09-28"));
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
  await expectContext(6, 3, "2026-08-31");
  await expect.poll(activeSettings).toEqual({
    ids: oldIds,
    capital: 100000,
    start: "2024-01-01",
    end: "2026-08-31",
    basis: "marked",
  });

  await page.getByRole("button", { name: "View latest ES/NQ", exact: true }).click();
  await expectContext(5, 2, "2026-09-28");
  await expect.poll(activeSettings).toEqual({
    ids: latestIds,
    capital: 100000,
    start: "2024-01-01",
    end: "2026-09-28",
    basis: "marked",
  });
  await page.getByRole("link", { name: "Calendar", exact: true }).click();
  await expect(page.getByRole("region", { name: "Daily P&L calendar" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Calendar month" })).toHaveValue("2026-09");
  const september28 = page.getByRole("button", { name: /^2026-09-28:/ });
  await expect(september28).toBeEnabled();
  await expect(september28).not.toHaveAttribute("aria-label", /Outside test window/);
  await page.screenshot({ path: `${folder}/latest-es-nq-calendar.png`, animations: "disabled" });

  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await page.getByRole("button", { name: "Restore previous combination", exact: true }).click();
  await expectContext(6, 3, "2026-08-31");
  await expect.poll(activeSettings).toEqual({
    ids: oldIds,
    capital: 100000,
    start: "2024-01-01",
    end: "2026-08-31",
    basis: "marked",
  });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expectContext(6, 3, "2026-08-31");
  await expect.poll(activeSettings).toEqual({
    ids: oldIds,
    capital: 100000,
    start: "2024-01-01",
    end: "2026-08-31",
    basis: "marked",
  });
  await page.screenshot({ path: `${folder}/restored-combination.png`, animations: "disabled" });
  assert.deepEqual(errors, []);

  const directPage = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  directPage.setDefaultTimeout(30000);
  const directErrors = [];
  directPage.on("pageerror", (error) => directErrors.push(error.message));
  await directPage.addInitScript((settings) => {
    if (!localStorage.getItem("quant-collective-v1")) {
      localStorage.setItem("quant-collective-v1", JSON.stringify(settings));
    }
  }, staleSettings);
  try {
    await directPage.goto(`${origin}/?portfolio=latest-es-nq#/portfolio/calendar`, {
      waitUntil: "domcontentloaded",
    });
    const directContext = directPage.locator(".wb-context");
    await expect(directContext).toContainText("5 books");
    await expect(directContext).toContainText("2 markets");
    await expect(directContext).toContainText("2024-01-01 to 2026-09-28");
    await expect.poll(() => new URL(directPage.url()).searchParams.get("portfolio")).toBe(null);
    await expect(directPage.getByRole("textbox", { name: "Calendar month" })).toHaveValue("2026-09");
    await expect(directPage.getByRole("button", { name: /^2026-09-28:/ })).toBeEnabled();
    const previous = await directPage.evaluate(() =>
      JSON.parse(localStorage.getItem("quant-collective-previous-v1")),
    );
    assert.ok(previous, "The direct link must retain the prior combination for restore");
    assert.equal(previous.end, "2026-08-31");
    assert.deepEqual(Object.keys(previous.copies).sort(), oldIds);
    await directPage.screenshot({ path: `${folder}/direct-link-calendar.png`, animations: "disabled" });
    await directPage.getByRole("link", { name: "Overview", exact: true }).click();
    await directPage.getByRole("button", { name: "Restore previous combination", exact: true }).click();
    await expect(directPage.locator(".wb-context")).toContainText("6 books");
    await expect(directPage.locator(".wb-context")).toContainText("3 markets");
    await expect(directPage.locator(".wb-context")).toContainText("2024-01-01 to 2026-08-31");
    assert.deepEqual(directErrors, []);
  } catch (error) {
    await directPage.screenshot({ path: `${folder}/direct-link-failure.png`, animations: "disabled" });
    throw error;
  } finally {
    await directPage.close();
  }
  await writeFile(
    `${folder}/validation.json`,
    JSON.stringify({
      status: "PASS",
      catalog_generated_at: catalog.generated_at,
      latest_ids: latestIds,
      restored_ids: oldIds,
      latest_end: "2026-09-28",
      restored_end: "2026-08-31",
      page_errors: errors,
      direct_link: "PASS",
    }, null, 2),
  );
  console.log(`PASS: latest ES/NQ view, direct link, September coverage, and persistent restore. ${folder}`);
} catch (error) {
  await page.screenshot({ path: `${folder}/failure.png`, animations: "disabled" });
  throw error;
} finally {
  await browser.close();
}
