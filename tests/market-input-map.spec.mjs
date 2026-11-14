import { test, expect } from "@playwright/test";
import { measureOverflow } from "./overflow-helper.mjs";

test.beforeEach(async ({ page }, info) => {
  if (info.title.startsWith("initial load")) return;
  await page.goto("/");
  await page.waitForSelector("[data-testid=mim-summary]", { timeout: 60000 });
  await page.getByTestId("market-input-map").scrollIntoViewIfNeeded();
  await page.waitForSelector("[data-testid=market-input-map][data-ready=yes]", { timeout: 60000 });
});

test("initial load: summary renders from the small reconciliation file without fetching the map index", async ({ page }) => {
  const urls = [];
  page.on("request", r => urls.push(r.url()));
  await page.goto("/");
  await expect(page.getByTestId("mim-summary")).toContainText("1,649");
  await page.waitForTimeout(1000);
  expect(urls.filter(u => /market_input_map\/map\.json|\/map-[^/]*\.js/.test(u))).toEqual([]);
  await expect(page.locator("[data-testid=market-input-map]")).toHaveAttribute("data-ready", "no");
  await page.getByTestId("market-input-map").scrollIntoViewIfNeeded();
  await expect(page.locator("[data-testid=market-input-map]")).toHaveAttribute("data-ready", "yes", { timeout: 60000 });
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
  for (const n of ["market_input_edges.csv", "distinct_inputs.csv", "dataset_input_edges.csv", "acquisition_queue.csv", "reconciliation.json"]) await expect(map.getByTestId("mim-exports")).toContainText("research/input_research/market_input_map/" + n);
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

test("queue action groups: five groups, exact committed counts, rank order kept inside a group", async ({ page }) => {
  const map = page.getByTestId("market-input-map");
  await map.getByRole("tab", { name: "Queue" }).click();
  await expect(map.getByTestId("mim-group-ARCHIVED_BUILD_NEXT")).toContainText("1 datasets");
  await expect(map.getByTestId("mim-group-RIGHTS_APPROVAL_NEEDED")).toContainText("86 datasets");
  await expect(map.getByTestId("mim-group-FREE_COLLECTION_POSSIBLE")).toContainText("0 datasets");
  await expect(map.getByTestId("mim-group-PROSPECTIVE_CAPTURE_REQUIRED")).toContainText("26 datasets");
  await expect(map.getByTestId("mim-group-BLOCKED_OR_PAID")).toContainText("8 datasets");
  await map.getByTestId("mim-group-PROSPECTIVE_CAPTURE_REQUIRED").click();
  await expect(page.getByTestId("mim-queue-count")).toContainText("26 of 26");
  const ranks = await map.locator("[data-testid=mim-queue-row] .mim-qrank").allTextContents();
  const n = ranks.map(t => Number(t.match(/#(\d+)/)[1]));
  expect(n).toEqual([...n].sort((a, b) => a - b));
  await map.getByTestId("mim-group-FREE_COLLECTION_POSSIBLE").click();
  await expect(map.getByTestId("mim-group-empty")).toBeVisible();
});

test("linked filters persist across Markets, Inputs, Datasets and Queue and each view states its scope", async ({ page }) => {
  const map = page.getByTestId("market-input-map");
  await map.getByLabel("Sport").selectOption("NBA");
  await map.getByLabel("missing PRIMARY only").check();
  for (const tab of ["Markets", "Inputs", "Datasets", "Queue"]) {
    await map.getByRole("tab", { name: tab }).click();
    await expect(map.getByTestId("mim-scope")).toContainText("sport NBA · missing PRIMARY");
  }
  await expect(page.getByTestId("mim-queue-count")).toContainText("distinct missing PRIMARY slots match");
  const row = map.locator("[data-testid=mim-queue-row]").first();
  await expect(row).toContainText(/\d+ of \d+ missing PRIMARY slots match/);
  await row.getByRole("button", { name: /Show the \d+ matching slots/ }).click();
  const slots = await row.locator(".mim-list li").allTextContents();
  expect(slots.length).toBeGreaterThan(0);
  for (const t of slots) expect(t.startsWith("NBA:")).toBeTruthy();
  await map.getByRole("tab", { name: "Datasets" }).click();
  await expect(map.locator("[data-testid=mim-dataset]").first()).toContainText(/linked inputs? match filters/);
});

test("queue groups are shown in the action order", async ({ page }) => {
  const map = page.getByTestId("market-input-map");
  await map.getByRole("tab", { name: "Queue" }).click();
  const ids = await map.locator(".mim-groups button[data-testid]").evaluateAll(els => els.map(e => e.dataset.testid.replace("mim-group-", "")));
  expect(ids).toEqual(["ARCHIVED_BUILD_NEXT", "RIGHTS_APPROVAL_NEEDED", "FREE_COLLECTION_POSSIBLE", "PROSPECTIVE_CAPTURE_REQUIRED", "BLOCKED_OR_PAID"]);
});
