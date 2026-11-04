import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const ex = JSON.parse(readFileSync(new URL("../research/audit/clv/execution_summary.json", import.meta.url)));
const text = JSON.stringify(ex);
test("schema and sports present", () => {
  assert.equal(ex.schema, "sift-clv-execution-summary/1");
  for (const s of ["NFL", "CFB", "NBA", "NHL"]) assert.ok(ex.real_wagers[s].measures_cents.executable_purchase_clv);
});
test("ten answers present", () => assert.equal(Object.keys(ex.answers).length, 10));
test("hypothetical and verified blocks are labelled", () => {
  assert.match(ex.hypothetical_early_taker_nfl.evidence, /HYPOTHETICAL/);
  assert.match(ex.limit_order_simulation_nfl.evidence, /HYPOTHETICAL/);
  assert.match(ex.real_wagers.NFL.evidence, /VERIFIED/);
});
test("no private economics or identifiers", () => {
  for (const bad of ["\"roi\"", "\"pnl\"", "\"stake", "order_id", "\"ticker\"", "KXNFLGAME-2"]) assert.ok(!text.includes(bad), bad);
  assert.ok(!/KX[A-Z]+-\d{2}[A-Z]{3}/.test(text));
});
test("identity B = D + half spread (aggregate)", () => {
  for (const s of ["NFL", "CFB", "NBA", "NHL"]) {
    const r = ex.real_wagers[s], m = r.measures_cents;
    const lhs = m.executable_purchase_clv.mean, rhs = m.midpoint_execution_clv.mean + r.closing_half_spread_cents_mean;
    assert.ok(Math.abs(lhs - rhs) < 0.06, `${s} ${lhs} vs ${rhs}`);
  }
});
