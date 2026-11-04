import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
});

test("find a source-linked study and read evidence in two actions", async ({ page }) => {
  await expect(page.getByRole("heading", { name: /Pick up the research/ })).toBeVisible();
  await page.getByRole("button", { name: /Sharp-anchored MLB pricing has no qualified edge/ }).click();
  await expect(page.getByRole("heading", { name: /Sharp-anchored MLB pricing/ })).toBeVisible();
  await expect(page.getByText(/no executable, post-fee, out-of-sample strategy/i)).toBeVisible();
  await expect(page.getByRole("link", { name: /MLB Alpha full-market research/ })).toHaveAttribute("href", "https://github.com/chmoses98/edge-finder-api/pull/305");
  await expect(page.getByText(/What we cannot claim/i)).toBeVisible();
});

test("one search narrows the work queue without hiding qualifications", async ({ page }) => {
  await page.getByLabel("Find a question or finding").fill("pregame information clock");
  await expect(page.getByRole("button", { name: /Verify the pregame information clock/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Our NBA market baseline/ })).toHaveCount(0);
  await expect(page.getByText(/Before the clock change/)).toBeVisible();
});

test("new question, checklist and note survive reload", async ({ page }) => {
  await page.getByRole("button", { name: /New question/ }).click();
  await page.getByPlaceholder("Example: Do lineup changes create a short pricing delay?").fill("Do late scratches predict a price correction?");
  await page.getByRole("button", { name: "Save research question" }).click();
  await expect(page.getByRole("heading", { name: "Do late scratches predict a price correction?" })).toBeVisible();
  await page.getByRole("checkbox", { name: /Define a falsifiable hypothesis/ }).check();
  await page.getByLabel("YOUR WORKING NOTES").fill("Require a timestamped pregame baseline.");
  await page.reload();
  await page.getByRole("button", { name: /Do late scratches predict a price correction/ }).click();
  await expect(page.getByRole("checkbox", { name: /Define a falsifiable hypothesis/ })).toBeChecked();
  await expect(page.getByLabel("YOUR WORKING NOTES")).toHaveValue("Require a timestamped pregame baseline.");
});

test("mobile and desktop never require sideways scrolling", async ({ page }) => {
  const sizes = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, view: window.innerWidth }));
  expect(sizes.scroll).toBeLessThanOrEqual(sizes.view);
  await expect(page.getByRole("button", { name: "Export" })).toBeVisible();
});

test("browse CFB, CBB and NCAA baseball without pretending unsupported models exist", async ({ page }) => {
  await page.getByRole("button", { name: "Browse sports" }).click();
  await expect(page.getByRole("heading", { name: "Any sport can start with a question." })).toBeVisible();
  await expect(page.getByRole("button", { name: /College Football \(FBS\)/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /College Basketball \(Men\)/ })).toBeVisible();
  await page.getByRole("button", { name: /NCAA Baseball/ }).click();
  await expect(page.getByRole("heading", { name: /Build the NCAA baseball research foundation/ })).toBeVisible();
  await expect(page.getByText("Discovery needed", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/No dedicated NCAA baseball research repo/)).toBeVisible();
  await expect(page.getByRole("link", { name: /Kalshi 2026 NCAA baseball game contract/ })).toHaveAttribute("href", /kalshi.com/);
});

test("unmodeled and entirely new sports can enter the lab without new code", async ({ page }) => {
  await page.getByRole("button", { name: "Browse sports" }).click();
  await page.getByRole("button", { name: /Golf \(PGA \/ LPGA\)/ }).click();
  await expect(page.getByRole("heading", { name: /Start with what you want to learn/ })).toBeVisible();
  await expect(page.locator(".create-form select")).toHaveValue("GOLF");
  await page.locator(".create-form select").selectOption("__new__");
  await page.getByPlaceholder("e.g. Cycling").fill("Cycling");
  await page.getByPlaceholder("Example: Do lineup changes create a short pricing delay?").fill("Do weather and course profiles change cycling upset probabilities?");
  await page.getByRole("button", { name: "Save research question" }).click();
  await expect(page.getByRole("heading", { name: /Do weather and course profiles/ })).toBeVisible();
  await page.reload();
  await expect(page.locator(".filters select").first()).toContainText("Cycling");
});
