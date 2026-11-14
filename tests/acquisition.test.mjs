import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { decisions, filterShortlist, marketRequirements, money, rankForSport, requirementTally } from "../src/acquisition.mjs";

const P = JSON.parse(readFileSync(new URL("../research/data_foundation_ops/acquisition_plan.json", import.meta.url)));
const A = JSON.parse(readFileSync(new URL("../research/data_foundation_ops/acquisition_inputs.json", import.meta.url)));
const L = JSON.parse(readFileSync(new URL("../research/data_foundation_ops/pipeline_ledger.json", import.meta.url)));

test("plan totals reconcile with the catalog and the pipeline ledger", () => {
  assert.equal(P.totals.inputs, L.totals.inputs);
  assert.equal(P.totals.archetypes, L.totals.archetypes);
  assert.equal(P.totals.missing_primary_slots, L.totals.missing_primary_slots);
  const sum = P.sports_order.reduce((a, s) => a + P.sports[s].missing_primary_inputs, 0);
  assert.equal(sum, P.totals.missing_primary_inputs);
  assert.ok(P.totals.complete_with_archives <= P.totals.complete_after_free && P.totals.complete_after_free <= P.totals.complete_after_low_cost && P.totals.complete_after_low_cost <= P.totals.complete_after_all_priced);
});

test("roadmap is cumulative and never counts an input twice", () => {
  let prev = P.totals.complete_with_archives;
  for (const s of P.roadmap) { assert.equal(s.cumulative_complete, prev + s.newly_complete); prev = s.cumulative_complete; }
  assert.ok(prev <= P.totals.missing_primary_inputs);
});

test("filters and sport ranking", () => {
  const p0 = rankForSport(filterShortlist(P.shortlist, { sport: "P0" }), "P0");
  assert.ok(p0.every(r => r.sports.some(s => ["NBA", "CBB", "NHL"].includes(s))));
  for (let i = 1; i < p0.length; i++) assert.ok(p0[i - 1].sport_score >= p0[i].sport_score);
  assert.ok(filterShortlist(P.shortlist, { maxCost: 0 }).every(r => r.cheapest_monthly_usd === 0));
  assert.ok(filterShortlist(P.shortlist, { tier: "UNRESOLVED" }).every(r => r.tier === "UNRESOLVED"));
});

test("prices are never invented: a paid row without a price is unresolved and money() says unknown", () => {
  for (const r of P.shortlist) if (r.tier === "LOW_COST" || r.tier === "HIGHER_COST") assert.ok(r.cheapest_monthly_usd > 0);
  assert.equal(money(null), "price unknown");
  for (const p of P.providers) assert.ok(["VERIFIED", "ESTIMATE", "UNKNOWN", "UNKNOWN_ENTERPRISE"].includes(p.price.status), p.id);
  assert.ok(decisions(P).length > 0);
});

test("market requirements cover every predictive input of a market", () => {
  const [k, mk] = Object.entries(L.markets).find(([, m]) => m.sport === "NBA" && m.inputs.length > 10);
  const rows = marketRequirements(mk, A);
  assert.equal(rows.length, mk.inputs.filter(x => x[2] === "PREDICTIVE").length, k);
  const t = requirementTally(rows);
  assert.equal(t.have + t.partial + t.missing, rows.length);
});
