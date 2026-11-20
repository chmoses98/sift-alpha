import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { measureOverflow } from "./overflow-helper.mjs";

const R = JSON.parse(readFileSync(new URL("../research/input_research/readiness/dashboard.json", import.meta.url)));
const LAD = JSON.parse(readFileSync(new URL("../research/pipeline/ladder_summary.json", import.meta.url)));

test("operating readiness renders separately from catalog completeness and reconciles", async ({ page }) => {
  await page.goto("/");
  const p = page.getByTestId("operating-readiness");
  await p.scrollIntoViewIfNeeded();
  await expect(p).toContainText("NOT THE SAME AS CATALOG COMPLETENESS");
  await expect(page.getByTestId("readiness-total")).toHaveText(String(R.totals.inventory_primary_missing_critical));
  await expect(page.getByTestId("readiness-recon")).toContainText("Reconciles exactly");
  const lastRow = page.getByTestId("ladder-table").locator("tbody tr").last();
  await expect(lastRow).toContainText(LAD.counts_at_least.CERTIFIED.toLocaleString("en-US"));
  await expect(page.getByTestId("ladder-table")).toContainText("consumed in production");
  const o = await measureOverflow(page);
  expect(o.scroll, JSON.stringify(o.offenders)).toBeLessThanOrEqual(o.view);
});

test("P1 tracker shows the baseline, the ledger's missing P1 count, categories and per-input blockers", async ({ page }) => {
  await page.goto("/");
  const t = page.getByTestId("p1-tracker");
  await t.scrollIntoViewIfNeeded();
  await expect(page.getByTestId("p1-missing-now")).toHaveText(String(R.by_tier.P1));
  await expect(page.getByTestId("p1-recon")).toContainText("Reconciles with the ledger and the baseline");
  await expect(page.getByTestId("p1-categories")).toContainText("PROXY");
  await t.getByText(/^Open P1 inputs/).click();
  await expect(page.getByTestId("p1-open").locator("tbody tr")).toHaveCount(R.p1_tracker.inputs.filter(i => i.remaining_blocker).length);
  await t.getByText(/^Closed P1 inputs/).click();
  await expect(page.getByTestId("p1-closed").locator("tbody tr")).toHaveCount(R.p1_tracker.inputs.filter(i => !i.remaining_blocker).length);
  const o = await measureOverflow(page);
  expect(o.scroll, JSON.stringify(o.offenders)).toBeLessThanOrEqual(o.view);
});
