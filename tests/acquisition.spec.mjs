import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { measureOverflow } from "./overflow-helper.mjs";

const P = JSON.parse(readFileSync(new URL("../research/data_foundation_ops/acquisition_plan.json", import.meta.url)));
const n = x => x.toLocaleString("en-US");

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.waitForSelector("[data-testid=acq-totals]", { timeout: 60000 });
});

test("Acquire is the default view: totals, decisions, sport coverage and a P0-first shortlist, without loading per-input detail", async ({ page }) => {
  const urls = []; page.on("request", r => urls.push(r.url()));
  await page.reload();
  const a = page.getByTestId("acq");
  await expect(a.getByTestId("acq-totals")).toContainText(n(P.totals.missing_primary_inputs));
  await expect(a.getByTestId("acq-totals")).toContainText(n(P.totals.missing_primary_slots));
  await expect(a.getByTestId("acq-sports").locator("> li")).toHaveCount(8);
  await expect(a.getByTestId("acq-decisions").locator("> li").first()).toBeVisible();
  const first = a.getByTestId("acq-row").first();
  await expect(first).toContainText("Next engineering step");
  await expect(first).toContainText("Your decision");
  // P0 is selected by default: the top card must feed an NBA, CBB or NHL input
  await expect(first.locator(".mim-qrank")).toContainText(/NBA|CBB|NHL/);
  await page.waitForTimeout(500);
  expect(urls.filter(u => /acquisition_inputs|pipeline_ledger/.test(u))).toEqual([]);
});

test("filters narrow the shortlist and a card expands to providers with prices, terms and links", async ({ page }) => {
  const a = page.getByTestId("acq");
  await a.getByRole("button", { name: "All", exact: true }).click();
  await expect(a.getByTestId("acq-count")).toContainText(`${P.shortlist.length} datasets`);
  await a.getByLabel("Cost tier").selectOption("LOW_COST");
  await expect(a.getByTestId("acq-count")).toContainText(`${P.shortlist.filter(r => r.tier === "LOW_COST").length} datasets`);
  const card = a.getByTestId("acq-row").first();
  await card.locator(".mim-title").click();
  await expect(card.getByTestId("acq-provider").first()).toContainText(/price (verified|estimate|unknown)/);
  await expect(card).toContainText("redistribution");
  await a.getByLabel("Cost tier").selectOption("all");
  await a.getByLabel("Maximum monthly cost").selectOption("0");
  await expect(a.getByTestId("acq-count")).toContainText(`${P.shortlist.filter(r => r.cheapest_monthly_usd === 0).length} datasets`);
});

test("Training shows readiness separately from availability for all eight sports", async ({ page }) => {
  const df = page.getByTestId("data-foundation");
  await df.getByRole("tab", { name: "Training" }).click();
  for (const s of P.sports_order) await expect(df.getByTestId("acq-train-" + s)).toContainText(`of ${P.sports[s].training.of} dataset checks`);
});

test("market drill-down lists data requirements with have/need, datasets and blockers", async ({ page }) => {
  const df = page.getByTestId("data-foundation");
  await df.getByRole("tab", { name: "Markets" }).click();
  await expect(df).toHaveAttribute("data-ready", "yes", { timeout: 60000 });
  await df.getByTestId("df-market").first().locator(".mim-title").click();
  const m = df.getByTestId("acq-market");
  await expect(m.getByTestId("acq-reqs").locator("> li").first()).toContainText("Blocker", { timeout: 60000 });
  await expect(m.getByTestId("acq-reqs").locator("> li").first()).toContainText(/have|need/);
  const o = await measureOverflow(page);
  expect(o.scroll, "market requirements " + JSON.stringify(o)).toBeLessThanOrEqual(o.view);
});
