import { test, expect } from "@playwright/test";
import { measureOverflow } from "./overflow-helper.mjs";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.waitForSelector("[data-testid=mim-summary]", { timeout: 60000 });
});

test("summary separates distinct inputs, predictive slots and missing PRIMARY slots", async ({ page }) => {
  const s = page.getByTestId("mim-summary");
  await expect(s).toContainText("1,649");
  await expect(s).toContainText("3,670");
  await expect(s).toContainText("949");
  await expect(page.getByTestId("mim-market-count")).toContainText("170 of 170");
});

test("Market -> Input -> Raw dataset -> affected market navigation", async ({ page }) => {
  const map = page.getByTestId("market-input-map");
  await map.locator("[data-testid=mim-market] .mim-title").first().click();
  await map.locator("[data-testid=mim-market] .mim-body li .mim-link").first().click();
  await expect(map.locator(".mim-focus [data-testid=mim-input] h4").first()).toBeVisible();
  await map.locator(".mim-focus .mim-body .mim-link[aria-label^='dataset '], .mim-focus .mim-body li .ir-why .mim-link").first().click();
  await expect(map.locator(".mim-focus [data-testid=mim-dataset]")).toBeVisible();
  await expect(map.locator(".mim-focus").getByText(/Affected markets/)).toBeVisible();
  await map.locator(".mim-focus h4:has-text('Affected markets') + ul .mim-link").first().click();
  await expect(map.locator(".mim-focus [data-testid=mim-market]")).toBeVisible();
  await map.getByRole("button", { name: "← Back" }).click();
  await expect(map.locator(".mim-focus [data-testid=mim-dataset]")).toBeVisible();
});

test("filters, queue and exports", async ({ page }) => {
  const map = page.getByTestId("market-input-map");
  await map.getByLabel("missing PRIMARY only").check();
  await map.getByLabel("Sport").selectOption("NBA");
  await expect(page.getByTestId("mim-market-count")).toContainText(/of 170/);
  await map.getByRole("tab", { name: "Queue" }).click();
  await expect(map.locator("[data-testid=mim-queue-row]").first()).toContainText("missing PRIMARY slots");
  await map.getByRole("tab", { name: "Export" }).click();
  for (const n of ["market_input_edges.csv", "distinct_inputs.csv", "dataset_input_edges.csv", "acquisition_queue.csv"]) await expect(map.getByRole("link", { name: n })).toBeVisible();
  await expect(page.getByTestId("mim-recon")).toContainText("per archetype match");
});

test("no horizontal overflow with a market and an input expanded", async ({ page }) => {
  const map = page.getByTestId("market-input-map");
  await map.locator("[data-testid=mim-market] .mim-title").first().click();
  await map.locator("[data-testid=mim-market] .mim-body li .mim-link").first().click();
  await expect(map.locator(".mim-focus [data-testid=mim-input] h4").first()).toBeVisible();
  const o = await measureOverflow(page);
  expect(o.scroll, JSON.stringify(o)).toBeLessThanOrEqual(o.view);
});
