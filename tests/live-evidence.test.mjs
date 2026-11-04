import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const ev = JSON.parse(readFileSync(new URL("../research/audit/clv/live_execution_evidence.json", import.meta.url)));
const text = JSON.stringify(ev);
test("aggregate-only and no identifiers", () => {
  assert.match(ev.privacy, /aggregates only/);
  assert.ok(!/KX[A-Z0-9]+-\d{2}[A-Z]{3}/.test(text) && !text.includes("kalshi:v1") && !/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}/.test(text));
  const keys = []; (function walk(x) { if (x && typeof x === "object") for (const [k, v] of Object.entries(x)) { keys.push(k); walk(v); } })(ev);
  for (const bad of ["stake", "pnl", "roi", "order_id", "fill_id", "client_order_id_value", "ticker", "source_bet_key"]) assert.ok(!keys.includes(bad), bad);
});
test("no inferred match is ever counted as verified", () => {
  assert.equal(ev.linkage.unique_window_candidates_counted_as_verified, 0);
  assert.ok(ev.linkage.verified_links <= ev.order_endpoint.client_order_id_sift_prefixed);
});
test("counters are internally consistent", () => {
  const o = ev.order_endpoint;
  assert.ok(o.client_order_id_non_empty <= o.client_order_id_field_present && o.client_order_id_sift_prefixed <= o.client_order_id_non_empty);
  assert.ok(o.fills_joined_to_order_by_order_id <= o.fills_sampled);
  assert.ok(ev.fees.taker_matches_0_07 <= ev.fees.taker_fee_rows_validated);
});

test("series fee schedule counts add up and flag disagreements", () => {
  const f = ev.series_fee_schedule;
  assert.equal(Object.values(f.fee_type_counts).reduce((a, b) => a + b, 0), f.series_checked);
  assert.equal(Object.values(f.fee_multiplier_counts).reduce((a, b) => a + b, 0), f.series_checked);
  assert.equal(f.maker_fills_observed, 0);
  assert.ok(f.published_multiplier_vs_observed_rate_disagreements >= 0);
  assert.ok(!JSON.stringify(f).match(/KX[A-Z]/));
});
