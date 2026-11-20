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
