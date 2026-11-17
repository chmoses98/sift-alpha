import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { measureOverflow } from "./overflow-helper.mjs";

const C = JSON.parse(readFileSync(new URL("../research/data_foundation_ops/market_coverage.json", import.meta.url)));
const n = x => x.toLocaleString("en-US");

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.waitForSelector("[data-testid=acq-totals]", { timeout: 60000 });
  await page.getByTestId("data-foundation").getByRole("tab", { name: "Coverage", exact: true }).click();
  await page.waitForSelector("[data-testid=market-coverage][data-ready=yes]", { timeout: 60000 });
});

test("coverage totals show before / after and match the generated file", async ({ page }) => {
  const t = page.getByTestId("cov-totals");
  await expect(t).toContainText(n(C.now.cls.CERTIFIED));
  await expect(t).toContainText(n(C.now.data_complete_missing_inputs));
  await expect(t).toContainText(n(C.now.missing_primary_slots));
  await expect(t).toContainText("since Phase 11");
});

test("sport -> market -> input drill-down reaches source, gap and next action", async ({ page }) => {
  const cov = page.getByTestId("market-coverage");
  await cov.getByRole("tab", { name: "MLB", exact: true }).click();
  await expect(cov.getByTestId("cov-sport-table")).toContainText(n(C.sports.MLB.cls.NO_PREGAME_HISTORY));
  const m = cov.getByTestId("cov-market").first();
  await expect(m).toContainText("Next:");
  await m.getByRole("button").first().click();
  const i = m.getByTestId("cov-input").first();
  await i.getByRole("button").first().click();
  await expect(i).toContainText("Sources:");
  await expect(i).toContainText("Gap:");
  await expect(i).toContainText("Next:");
  const o = await measureOverflow(page);
  expect(o.scroll, JSON.stringify(o)).toBeLessThanOrEqual(o.view + 1);
});

test("research studies list their holdout status and never claim value", async ({ page }) => {
  const cov = page.getByTestId("market-coverage");
  expect(await cov.getByTestId("cov-study").count()).toBeGreaterThanOrEqual(6);
  await expect(cov).toContainText("nothing below is a claim of betting value");
  await expect(cov.getByTestId("cov-study").first()).toContainText("holdout scored once");
});
