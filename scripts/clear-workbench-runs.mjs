// Explicit maintenance command: invoke only when clearing all runs is intended.
import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
const origin = "http://127.0.0.1:5173",
  api = origin + "/api/workbench";
const before = await (await fetch(api + "/state")).json();
assert(before.runs.length > 0, "No runs to clear");
assert(
  before.runs.every((r) => !["Queued", "Running"].includes(r.status)),
  "Wait for active jobs",
);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
try {
  await page.goto(origin, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page
    .getByRole("button", { name: "Clear all runs", exact: true })
    .click();
  await page.getByRole("dialog", { name: "Review run deletion" }).waitFor();
  const responsePromise = page.waitForResponse(
    (r) => r.url().endsWith("/runs/delete") && r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Delete reviewed runs", exact: true })
    .click();
  const response = await responsePromise,
    deleted = await response.json();
  assert.equal(response.status(), 200, JSON.stringify(deleted));
  assert.deepEqual(deleted.warnings, []);
  assert.equal(deleted.counts.runs, before.runs.length);
  const after = await (await fetch(api + "/state")).json();
  for (const key of [
    "runs",
    "experiments",
    "evaluations",
    "regimes",
    "watchlist",
  ])
    assert.equal(after[key].length, 0, key);
  assert.equal(after.datasets.length, before.datasets.length);
  assert.equal(after.strategies.length, before.strategies.length);
  await page.reload();
  await page
    .getByRole("heading", { name: "Run ledger", exact: true })
    .waitFor();
  await mkdir("reports/workbench-validation", { recursive: true });
  await page.screenshot({
    path: "reports/workbench-validation/cleared-ledger.png",
    animations: "disabled",
  });
  await writeFile(
    "reports/workbench-validation/run-cleanup.json",
    JSON.stringify(
      {
        deleted,
        previous_runs: before.runs.map((r) => r.id),
        preserved_datasets: after.datasets.map((d) => d.id),
      },
      null,
      2,
    ),
  );
  console.log(JSON.stringify(deleted, null, 2));
} finally {
  await browser.close();
}
