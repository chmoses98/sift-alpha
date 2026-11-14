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
  if (Object.keys(S.challengers).length) { await expect(v).toContainText("Data used"); await expect(v).toContainText("Limitations"); await expect(v).toContainText("checks computed and passed"); await expect(v).toContainText("attested, not independently computed"); }
});

test("Queue is ranked P0 first and labels evidence-backed vs hypothesis", async ({ page }) => {
  const df = page.getByTestId("data-foundation");
  await df.getByRole("tab", { name: "Queue" }).click();
  const rows = df.getByTestId("df-queue-row");
  await expect(rows.first()).toContainText("#1", { timeout: 60000 });
  await expect(rows.first()).toContainText("P0");
  await expect(rows.first()).toContainText(/evidence-backed|hypothesis/);
});

test("Sources ranks source decisions by missing P0 slots and never presents reachability as permission", async ({ page }) => {
  const SRC = JSON.parse(readFileSync(new URL("../research/data_foundation_ops/source_acquisition.json", import.meta.url)));
  const df = page.getByTestId("data-foundation");
  await df.getByRole("tab", { name: "Sources" }).click();
  const rows = df.getByTestId("df-source-row");
  await expect(rows.first()).toContainText("#1");
  await expect(rows.first()).toContainText(SRC.sources[0].source);
  await expect(rows.first()).toContainText("Next step");
  await expect(rows.first()).toContainText("terms: " + SRC.sources[0].terms_status.replaceAll("_", " ").toLowerCase());
  await expect(df.getByTestId("df-p0-distinct")).toContainText(n(SRC.p0_distinct.missing_primary_slots));
  await expect(df.getByTestId("df-p0-distinct")).toContainText(n(SRC.p0_distinct.archived_datasets_only));
  await expect(df.getByTestId("df-sources")).toContainText("Reachable is not permission");
  await expect(df.getByTestId("df-blockers").locator("li")).toHaveCount(Object.keys(SRC.p0_slots_by_blocker).length);
});

test("Models shows every sport's status, freshness and gap to the market without loading the ledger", async ({ page }) => {
  const df = page.getByTestId("data-foundation");
  await df.getByRole("tab", { name: "Models" }).click();
  for (const s of S.sports_order) {
    const card = df.getByTestId("df-model-" + s), b = S.scoreboard[s];
    await expect(card).toBeVisible();
    for (const c of b.challengers) await expect(card).toContainText(c.id);
    if (b.challengers.length) await expect(card).toContainText("Newest data read: " + b.data_through);
    else await expect(card).toContainText("No challenger has been evaluated");
  }
  await expect(df).toHaveAttribute("data-ready", "no");
  const nba = S.scoreboard.NBA.challengers.at(-1);
  await df.getByTestId("df-model-NBA").getByRole("button", { name: "challenger " + nba.id }).click();
  await expect(df.getByTestId("df-challengers")).toContainText(nba.id, { timeout: 60000 });
});

test("Built inputs separates built, used, evaluated, selected and validated for the 30 archive inputs", async ({ page }) => {
  const df = page.getByTestId("data-foundation");
  const B = S.built_inputs;
  await expect(df.getByTestId("df-built-NBA")).toContainText(`${B.filter(x => x.sport === "NBA").length} built`);
  await df.getByRole("tab", { name: "Built inputs" }).click();
  const v = df.getByTestId("df-built");
  await expect(v.getByTestId("df-built-row")).toHaveCount(B.length);
  const t = v.getByTestId("df-built-totals");
  await expect(t).toContainText(`${B.filter(x => x.used_in_challenger).length}used by a challenger`);
  await expect(t).toContainText(`${B.filter(x => x.validated).length}validated improvements`);
  expect(B.filter(x => x.validated).length).toBe(0);
  // an earlier challenger's own implementation is not counted as use of the built feature
  const srp = B.find(x => x.id === "nba.stat_rate_posterior");
  expect(srp.uses.some(u => !u.uses_phase15_builder)).toBe(true);
  await expect(v.getByTestId("df-built-row").filter({ hasText: "nba.stat_rate_posterior" })).toContainText("Also claimed with a different implementation");
  // navigation into the input's pipeline chain
  await v.getByRole("button", { name: "input nba.stat_rate_posterior" }).click();
  await expect(df.getByTestId("df-input-detail")).toBeVisible({ timeout: 60000 });
});

test("no horizontal overflow in any view (desktop and iPhone)", async ({ page }) => {
  const df = page.getByTestId("data-foundation");
  for (const tab of ["Summary", "Models", "Built inputs", "Markets", "Challengers", "Queue", "Sources"]) {
    await df.getByRole("tab", { name: tab }).click();
    if (tab !== "Summary" && tab !== "Sources" && tab !== "Models" && tab !== "Built inputs") await expect(df).toHaveAttribute("data-ready", "yes", { timeout: 60000 });
    const o = await measureOverflow(page);
    expect(o.scroll, tab + " " + JSON.stringify(o)).toBeLessThanOrEqual(o.view);
  }
  await df.getByRole("tab", { name: "Markets" }).click();
  await df.getByTestId("df-market").first().locator(".mim-title").click();
  await df.getByTestId("df-inputs").locator(".mim-link").first().click();
  const o = await measureOverflow(page);
  expect(o.scroll, "input detail " + JSON.stringify(o)).toBeLessThanOrEqual(o.view);
});
