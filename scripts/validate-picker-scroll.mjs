import assert from "node:assert/strict";
import { chromium, expect as baseExpect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";

const folder = `reports/picker-scroll-${Date.now()}`;
await mkdir(folder, { recursive: true });
const browser = await chromium.launch({ channel: "msedge" });
const expect = baseExpect.configure({ timeout: 30000 });
const results = [];
try {
  for (const [name, size] of [["desktop", { width: 1440, height: 900 }], ["mobile", { width: 390, height: 844 }]]) {
    const page = await browser.newPage({ viewport: size, hasTouch: name === "mobile" });
    page.setDefaultTimeout(30000);
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto("http://127.0.0.1:5173/#collective-strategies");
    await page.locator(".collective-picker label").filter({hasText:/^All tested/}).click();
    const viewport = page.getByRole("region", { name: "Available strategy configurations", exact: true });
    const table = page.getByTestId("strategy-picker");
    assert.ok(await table.locator("tbody tr").count() > 100);
    await viewport.scrollIntoViewIfNeeded();
    const geometry = await viewport.evaluate(el => ({ height: el.clientHeight, content: el.scrollHeight }));
    assert.ok(geometry.height >= 200 && geometry.height < size.height, JSON.stringify(geometry));
    assert.ok(geometry.content > geometry.height * 2);
    await viewport.hover();
    await page.mouse.wheel(0, 650);
    await expect.poll(() => viewport.evaluate(el => el.scrollTop)).toBeGreaterThan(100);
    if (name === "mobile") {
      const box = await viewport.boundingBox();
      // Swipe the visible middle of the table, above the sticky drawer footer.
      const y = Math.min(box.y + box.height / 2, size.height - 180);
      const x = Math.min(box.x + 100, size.width - 30);
      const before = await viewport.evaluate(el => el.scrollTop);
      const cdp = await page.context().newCDPSession(page);
      await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] });
      for (const delta of [30, 60, 100])
        await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x, y: y - delta }] });
      await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
      await expect.poll(() => viewport.evaluate(el => el.scrollTop)).toBeGreaterThan(before);
      await cdp.detach();
    }
    await viewport.focus();
    await viewport.press("Control+End");
    await expect.poll(() => viewport.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThan(3);
    const last = table.locator("tbody tr").last();
    await expect(last).toBeInViewport();
    const checkbox = last.getByRole("checkbox");
    await checkbox.check();
    await expect(checkbox).toBeChecked();
    await page.screenshot({ path: `${folder}/${name}-last-row.png`, animations: "disabled" });
    await page.getByRole("button", { name: "Done", exact: true }).click();
    await expect(viewport).toHaveCount(0);
    assert.deepEqual(errors, []);
    results.push({ name, geometry, wheel: "PASS", keyboard: "PASS", last_row_selection: "PASS", touch: name === "mobile" ? "PASS" : "not applicable" });
    await page.close();
  }
  await writeFile(folder + "/validation.json", JSON.stringify({ status: "PASS", results }, null, 2));
  console.log(`PASS: desktop/mobile picker scrolling and final-row selection. ${folder}`);
} finally { await browser.close(); }
