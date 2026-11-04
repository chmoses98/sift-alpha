import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const raw = readFileSync(new URL("../research/audit/clv/clv_summary.json", import.meta.url), "utf8");
const s = JSON.parse(raw);
const FORBIDDEN = new Set(["stake", "net_profit_loss", "gross_return", "roi", "economics", "source_bet_key", "market_ticker", "ticker", "execution_price", "order_id", "wager_id"]);
function* keys(o) { if (o && typeof o === "object") for (const [k, v] of Object.entries(o)) { yield k; yield* keys(v); } }

test("public CLV summary carries no private trading fields", () => {
  for (const k of keys(s)) assert.ok(!FORBIDDEN.has(k.toLowerCase()), `forbidden key ${k}`);
  assert.ok(!/KX[A-Z0-9]{3,}-\d{2}[A-Z]{3}\d{2}/.test(raw), "ticker-shaped string present");
});

test("every real-wager block states its denominators and the fee is counted once", () => {
  for (const sport of ["NFL", "CFB", "NBA"]) {
    const b = s.real_wagers[sport];
    assert.equal(b.actual_execution_clv.n, b.denominators.verified_clv_observations);
    assert.ok(b.denominators.verified_clv_observations <= b.denominators.pregame_entries_eligible);
    assert.equal(b.fee_adjustment_count_max, 1);
    assert.equal(b.selection_clv.verified, 0);
    const gap = b.actual_execution_clv.mean - b.fee_adjusted_difference.mean;
    assert.ok(Math.abs(gap - b.fee_per_contract.mean) < 1e-9, `${sport}: fee-adjusted != actual - one fee`);
  }
});

test("dashboard sections have the data they render", () => {
  const sh = s.hypothetical_selections.NFL_shadow_v2;
  for (const k of ["by_horizon", "by_price_bucket", "by_week_chronological", "by_family", "ranked_families_by_selection", "after_gated_deduped"]) assert.ok(sh[k], k);
  assert.ok(Math.abs((sh.after_gated_deduped.selection.mean - sh.after_gated_deduped.quoted_exec.mean) - sh.after_gated_deduped.spread_drag_mean) < 1e-9);
  assert.ok(s.before_after.length >= 5 && s.missing_evidence && s.not_measured.length > 0);
  for (const key of ["selection_clv", "quoted_execution_clv", "actual_execution_clv", "fee_adjusted_difference"]) assert.ok(s.metric_definitions[key].definition, key);
});
