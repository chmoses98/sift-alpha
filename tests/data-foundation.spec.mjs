import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { measureOverflow } from "./overflow-helper.mjs";

const S = JSON.parse(readFileSync(new URL("../research/data_foundation_ops/summary.json", import.meta.url)));
const n = x => x.toLocaleString("en-US");

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.waitForSelector("[data-testid=df-totals]", { timeout: 60000 });
});

test("executive summary renders from the small summary file without fetching the ledger", async ({ page }) => {
  const urls = [];
  page.on("request", r => urls.push(r.url()));
  await page.reload();
  const df = page.getByTestId("data-foundation");
  await expect(df.getByTestId("df-totals")).toContainText(n(S.totals.inputs));
  await expect(df.getByTestId("df-totals")).toContainText(n(S.totals.archetypes));
  await expect(df.getByTestId("df-recon")).toContainText("all totals match");
  await page.waitForTimeout(800);
  expect(urls.filter(u => /pipeline_ledger/.test(u))).toEqual([]);
  await expect(df).toHaveAttribute("data-ready", "no");
});

test("P0 cards show committed counts, the stage ladder and each sport's challenger verdict", async ({ page }) => {
  for (const s of ["NBA", "CBB", "NHL"]) {
    const card = page.getByTestId("df-sport-" + s), d = S.sports[s];
    await expect(card).toContainText(n(d.inputs_predictive));
    await expect(card).toContainText(n(d.missing_primary_slots));
    await expect(card.getByTestId("df-ladder-" + s).locator("li")).toHaveCount(8);
    const mine = Object.values(S.challengers).filter(c => c.sport === s);
    await expect(card.getByTestId("df-challenger")).toHaveCount(mine.length);
    for (const c of mine) await expect(card).toContainText(c.id);
  }
  await expect(page.getByTestId("df-all-sports").locator("li")).toHaveCount(8);
});

test("Sport -> Market -> Input -> Dataset/Collector -> Challenger navigation with Back", async ({ page }) => {
  const df = page.getByTestId("data-foundation");
  await df.getByRole("tab", { name: "Markets" }).click();
  await expect(df).toHaveAttribute("data-ready", "yes", { timeout: 60000 });
  await df.getByRole("tab", { name: /^NHL/ }).click();
  await expect(df.getByTestId("df-market-count")).toContainText(`${S.sports.NHL.archetypes} of ${S.sports.NHL.archetypes} NHL markets`);
  await df.getByLabel("Sort markets").selectOption("challenger");
  await df.getByTestId("df-market").first().locator(".mim-title").click();
  const md = df.getByTestId("df-market-detail");
  await expect(md.getByTestId("df-market-ladder").locator("li")).toHaveCount(8);
  await expect(md).toContainText("Next engineering action");
  await md.getByTestId("df-inputs").locator(".mim-link").first().click();
  const id = df.getByTestId("df-input-detail");
  await expect(id.getByTestId("df-chain").locator("li")).toHaveCount(10);
  await expect(id).toContainText("Production active");
  await expect(id).toContainText("Datasets and collectors");
  await expect(id).toContainText("Next engineering action");
  await df.getByTestId("df-back").click();
  await expect(df.getByTestId("df-market-detail")).toBeVisible();
  await df.getByTestId("df-back").click();
  await expect(df.getByTestId("df-market").first()).toBeVisible();
});

test("market input filters narrow the list and an input status names why it stopped", async ({ page }) => {
  const df = page.getByTestId("data-foundation");
  await df.getByRole("tab", { name: "Markets" }).click();
  await df.getByTestId("df-market").first().locator(".mim-title").click({ timeout: 60000 });
  const list = df.getByTestId("df-inputs").locator("li");
  const all = await list.count();
  await df.getByLabel("Filter inputs by status").selectOption("BLOCKED");
  const blocked = await list.count();
  expect(blocked).toBeLessThanOrEqual(all);
  if (blocked) await expect(list.first()).toContainText("blocked");
});

test("Challengers view lists every committed evaluation with data, checks, results and limitations", async ({ page }) => {
  const df = page.getByTestId("data-foundation");
  await df.getByRole("tab", { name: "Challengers" }).click();
  const v = df.getByTestId("df-challengers");
  await expect(v.getByTestId("df-challenger")).toHaveCount(Object.keys(S.challengers).length, { timeout: 60000 });
  for (const c of Object.values(S.challengers)) await expect(v).toContainText(c.id);
  if (Object.keys(S.challengers).length) { await expect(v).toContainText("Data used"); await expect(v).toContainText("Limitations"); await expect(v).toContainText("checks passed"); }
});

test("Queue is ranked P0 first and labels evidence-backed vs hypothesis", async ({ page }) => {
  const df = page.getByTestId("data-foundation");
  await df.getByRole("tab", { name: "Queue" }).click();
  const rows = df.getByTestId("df-queue-row");
  await expect(rows.first()).toContainText("#1", { timeout: 60000 });
  await expect(rows.first()).toContainText("P0");
  await expect(rows.first()).toContainText(/evidence-backed|hypothesis/);
});

test("no horizontal overflow in any view (desktop and iPhone)", async ({ page }) => {
  const df = page.getByTestId("data-foundation");
  for (const tab of ["Summary", "Markets", "Challengers", "Queue"]) {
    await df.getByRole("tab", { name: tab }).click();
    if (tab !== "Summary") await expect(df).toHaveAttribute("data-ready", "yes", { timeout: 60000 });
    const o = await measureOverflow(page);
    expect(o.scroll, tab + " " + JSON.stringify(o)).toBeLessThanOrEqual(o.view);
  }
  await df.getByRole("tab", { name: "Markets" }).click();
  await df.getByTestId("df-market").first().locator(".mim-title").click();
  await df.getByTestId("df-inputs").locator(".mim-link").first().click();
  const o = await measureOverflow(page);
  expect(o.scroll, "input detail " + JSON.stringify(o)).toBeLessThanOrEqual(o.view);
});
