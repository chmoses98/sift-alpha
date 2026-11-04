import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const d = JSON.parse(readFileSync(new URL("../research/audit/exec/execution_research_summary.json", import.meta.url)));
const text = JSON.stringify(d);
test("research-only status, no validated strategy, no live authority", () => {
  assert.equal(d.status, "RESEARCH_ONLY");
  assert.deepEqual(d.validated_strategies, []);
  assert.equal(d.headline.live_execution_authority, "NONE");
  assert.match(d.headline.absolute_net_ev, /NOT DEMONSTRATED/);
});
test("maker fee verification is explicit: zero observed maker fills, spread/total unverified", () => {
  assert.equal(d.maker_fee_verification.maker_observed_fills, 0);
  assert.match(d.maker_fee_verification.maker_status.KXNFLSPREAD, /UNVERIFIED/);
  assert.match(d.maker_fee_verification.maker_status.NBA, /UNVERIFIED/);
  assert.deepEqual(d.maker_fee_verification.scenarios, { M0: 0, M25: 0.0175, M100: 0.07 });
});
test("shadow orders are hypothetical and retrospective rows are not counted as prospective", () => {
  assert.match(d.shadow_orders.provenance, /HYPOTHETICAL/);
  assert.ok(d.shadow_orders.prospective_decisions <= d.shadow_orders.decisions_placed);
  if (d.shadow_orders.by_generation) assert.equal(d.shadow_orders.prospective_decisions, d.shadow_orders.by_generation.PROSPECTIVE || 0);
});
test("limit+fallback advantage is not claimed at the taker-equivalent maker fee", () => {
  const r = d.execution_cost_by_strategy_2026_live.by_horizon["24h"].M100.limit_fb_minus_wait_cents;
  assert.ok(r.lo < 0.1, "M100 interval must not exclude ~0 by a wide margin");
  for (const h of Object.values(d.execution_cost_by_strategy_2026_live.by_horizon)) assert.ok(h.M25.nobet_per_submitted_cents.mean <= 0.2);
});
test("aggregates only: no tickers, ids, stakes or personal P&L", () => {
  for (const bad of ["order_id", "\"stake", "\"pnl\"", "\"roi\"", "client_order"]) assert.ok(!text.includes(bad), bad);
  assert.ok(!/KX[A-Z0-9]+-\d{2}[A-Z]{3}/.test(text));
});
