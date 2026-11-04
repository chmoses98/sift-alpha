import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const cs = JSON.parse(readFileSync(new URL("../research/audit/clv/collectors_status.json", import.meta.url)));
test("collectors status is aggregate-only with no identifier keys", () => {
  assert.match(cs.privacy, /aggregates only/);
  const keys = []; (function walk(x) { if (x && typeof x === "object") for (const [k, v] of Object.entries(x)) { keys.push(k); walk(v); } })(cs);
  for (const bad of ["ticker", "order_id", "source_bet_key", "game_sums", "orders_seen", "stake", "pnl", "roi"]) assert.ok(!keys.includes(bad), bad);
  assert.ok(!/KX[A-Z0-9]+-\d{2}[A-Z]{3}/.test(JSON.stringify(cs)));
});
test("a missing collector block is null, never a fabricated zero", () => {
  if (!cs.fetched) { assert.equal(cs.entry_capture, null); assert.equal(cs.shadow_ledger, null); }
  else { assert.ok(cs.entry_capture === null || typeof cs.entry_capture.sampler.passes === "number"); }
});
