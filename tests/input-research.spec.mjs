import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { measureOverflow } from "./overflow-helper.mjs";

const reg = JSON.parse(readFileSync(new URL("../research/audit/input_registry.json", import.meta.url))).sports;
const SPORTS = ["NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"];

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.waitForSelector(".ir .ir-pick select");
});

test("section is labelled research-only and offers all eight sports", async ({ page }) => {
  const ir = page.locator("section.ir");
  await expect(ir.getByText("RESEARCH ONLY.")).toBeVisible();
  await expect(ir.locator(".ir-sport")).toHaveCount(8);
  await expect(ir.getByText(/not an edge|nothing is at L3\/L4/i).first()).toBeVisible();
});

test("every registry family of every sport is selectable (275 in total)", async ({ page }) => {
  let total = 0;
  for (const s of SPORTS) {
    await page.locator(".ir-sport", { hasText: new RegExp("^" + s) }).click();
    await expect(page.locator(".ir-pick select").first().locator("option")).toHaveCount(Object.keys(reg[s].families).length);
    total += Object.keys(reg[s].families).length;
  }
  expect(total).toBe(275);
});

test("a tested NFL family shows its benchmark, claim boundary and verdicts without implying a Kalshi edge", async ({ page }) => {
  await page.locator(".ir-pick select").first().selectOption("NFL/TOTAL");
  const ir = page.locator("section.ir");
  await expect(ir.getByText("L2 tested vs near-close sportsbook line").first()).toBeVisible();
  await expect(ir.getByText(/Claim boundary:/)).toBeVisible();
  await expect(ir.getByText(/does NOT show, and nothing here implies, an edge over Kalshi prices/)).toBeVisible();
  await expect(ir.getByText(/Pregame discipline/)).toBeVisible();
  await expect(ir.locator(".ir-chip.ir-NOT_DEMONSTRATED, .ir-chip.ir-WORSE_THAN_BASELINE").first()).toBeVisible();
  await expect(ir.locator(".ir-chip.ir-DEMONSTRATED_INCREMENTAL")).toHaveCount(0);   // no input beats the near-close total
  const text = await ir.innerText();
  expect(text).not.toMatch(/profitable|guaranteed|beats kalshi/i);
});

test("the QB passing-yards lead is labelled as a no-market baseline result", async ({ page }) => {
  await page.locator(".ir-pick select").first().selectOption("NFL/PLAYER_STAT");
  const ir = page.locator("section.ir");
  await expect(ir.getByText("L1 tested vs baseline").first()).toBeVisible();
  await expect(ir.getByText(/NO MARKET/).first()).toBeVisible();
  await expect(ir.getByText(/says nothing about whether any passing-yards price \(Kalshi or otherwise\) is wrong/)).toBeVisible();
  await expect(ir.getByText(/0 beat a Kalshi price \(not tested\)/)).toBeVisible();
});

test("untested sports are plainly inventory-only and inputs read as hypotheses", async ({ page }) => {
  await page.locator(".ir-sport", { hasText: /^NBA/ }).click();
  const ir = page.locator("section.ir");
  await expect(ir.getByText("L0 inventory only").first()).toBeVisible();
  await expect(ir.getByText("No predictive test has been run for this family")).toBeVisible();
  await expect(ir.locator(".ir-chip.ir-UNTESTED").first()).toBeVisible();
  await expect(ir.locator(".ir-chip.ir-DEMONSTRATED_INCREMENTAL")).toHaveCount(0);
});

test("an input row expands to rationale, measurement and registry status", async ({ page }) => {
  await page.locator(".ir-pick select").first().selectOption("NFL/TOTAL");
  await page.locator(".ir-table .ir-link").first().click();
  const open = page.locator(".ir-open").first();
  await expect(open.getByText(/Rationale\./)).toBeVisible();
  await expect(open.getByText(/How to measure\./)).toBeVisible();
  await expect(open.getByText(/Free sources:/)).toBeVisible();
});

test("parent blueprint hypotheses (inputs and interactions) are reachable", async ({ page }) => {
  await page.locator(".ir-pick select").first().selectOption("NFL/TOTAL");
  await page.locator("section.ir details", { hasText: /Parent blueprint/ }).locator("summary").click();
  await expect(page.locator("section.ir").getByText(/interactions hypothesised for the whole class of markets/)).toBeVisible();
});

test("the research section never forces sideways page scrolling", async ({ page }) => {
  await page.locator(".ir-pick select").first().selectOption("NFL/PLAYER_STAT");
  const sizes = await measureOverflow(page);
  expect(sizes.scroll, JSON.stringify(sizes)).toBeLessThanOrEqual(sizes.view);
});

test("market-universe audit is shown with its series-level caveat and unsupported sports", async ({ page }) => {
  const ir = page.locator("section.ir");
  await expect(ir.getByText(/Market universe audit/)).toBeVisible();
  await expect(ir.getByText(/Series-level only/)).toBeVisible();
  await expect(ir.getByText(/unsupported/i).first()).toBeVisible();
});

test("Kalshi passing-yards experiment is shown with its limits and no edge claim", async ({ page }) => {
  await page.locator(".ir-pick select").first().selectOption("NFL/PLAYER_STAT");
  const ir = page.locator("section.ir");
  await expect(ir.getByText(/Experiment NFL-PASSYDS-1/)).toBeVisible();
  await expect(ir.getByText(/NOT promoted/)).toBeVisible();
  await expect(ir.getByText(/no demonstrated edge/i)).toBeVisible();
  await expect(ir.getByText(/hypothetical/i).first()).toBeVisible();
  const text = await ir.innerText();
  expect(text).not.toMatch(/profitable strategy|guaranteed|proven edge/i);
});
