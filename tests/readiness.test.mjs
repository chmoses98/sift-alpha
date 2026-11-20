import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {CLASS_LABEL, LADDER_LABEL, ladderRows, readinessCheck} from "../src/readiness.mjs";

const R = JSON.parse(readFileSync(new URL("../research/input_research/readiness/dashboard.json", import.meta.url)));
const LAD = JSON.parse(readFileSync(new URL("../research/pipeline/ladder_summary.json", import.meta.url)));
const MAP = JSON.parse(readFileSync(new URL("../research/input_research/market_input_map/reconciliation.json", import.meta.url)));

test("readiness classes reconcile exactly with the completeness inventory and the market-input map", () => {
  const c = readinessCheck(R, LAD);
  assert.equal(c.classesOk, true);
  assert.equal(c.classTotal, MAP.missing_primary_predictive_slots);
  assert.equal(R.by_tier.P1 + R.by_tier.P2 + R.by_tier.F, c.classTotal);
  for (const k of R.classes) assert.ok(CLASS_LABEL[k], k);
});

test("adoption ladder is cumulative, labelled, and its certified count matches the ledger summary", () => {
  for (const l of LAD.levels) assert.ok(LADDER_LABEL[l], l);
  const rows = ladderRows(LAD), all = rows.at(-1).atLeast;
  for (const r of rows) for (let i = 1; i < r.atLeast.length; i++) assert.ok(r.atLeast[i] <= r.atLeast[i - 1], r.sport);
  assert.equal(readinessCheck(R, LAD).ladderOk, true);
  assert.equal(all[0], MAP.distinct_inputs);
  assert.equal(LAD.counts_at_least.PRODUCTION_CONSUMED, 0);   // nothing is consumed in production; a change here needs an approved activation
});

test("P1 tracker reconciles with the frozen baseline and the ledger; closures come only from certified levels", async () => {
  const {p1TrackerCheck, P1_CATEGORY, p1CategoryValue} = await import("../src/readiness.mjs");
  const t = R.p1_tracker; assert.ok(t, "dashboard carries the P1 tracker");
  const c = p1TrackerCheck(t);
  assert.equal(c.ok, true); assert.equal(c.baseline, 180);
  assert.equal(c.missing, R.by_tier.P1);                                             // the tracker's "missing now" is the ledger's P1 count
  for (const i of t.inputs) {
    if (i.p1_slots_closed > 0) assert.ok(["FULL", "PARTIAL", "PROXY"].includes(i.certified_level), i.input_id);
    if (i.p1_slots_closed === i.p1_slots) assert.equal(i.remaining_blocker, null, i.input_id); else assert.ok(i.remaining_blocker, i.input_id);
  }
  for (const [k] of P1_CATEGORY) assert.equal(typeof p1CategoryValue(t.summary, k), "number", k);
});
