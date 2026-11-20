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
