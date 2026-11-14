import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {STAGE_LABEL, OUTCOME_KIND, challengerResults, referenceTally, inputStatus, marketInputs, reconcile, sportMarkets, stageRows} from "../src/data-foundation.mjs";

const L = JSON.parse(readFileSync(new URL("../research/data_foundation_ops/pipeline_ledger.json", import.meta.url)));
const S = JSON.parse(readFileSync(new URL("../research/data_foundation_ops/summary.json", import.meta.url)));
const MAP = JSON.parse(readFileSync(new URL("../research/input_research/market_input_map/reconciliation.json", import.meta.url)));

test("ten explicit stages, each with a label; every outcome has a chip style", () => {
  assert.equal(L.stages.length, 10);
  for (const s of L.stages) assert.ok(STAGE_LABEL[s], s);
  for (const i of Object.values(L.inputs)) for (const o of i.chain) assert.ok(OUTCOME_KIND[o], o);
});

test("summary and ledger agree, and both reconcile to the Market & Input Map", () => {
  const r = reconcile(L);
  assert.equal(r.inputs, MAP.distinct_inputs); assert.equal(r.markets, MAP.archetypes); assert.equal(r.datasets, MAP.datasets);
  assert.equal(S.totals.missing_primary_slots, MAP.missing_primary_predictive_slots);
  assert.equal(S.reconciliation.ok, true);
  for (const s of L.sports_order) {
    assert.deepEqual(S.sports[s].at_counts, r.bySport[s].at, s);
    assert.equal(S.sports[s].inputs_predictive, r.bySport[s].predictive, s);
    assert.deepEqual(S.sports[s], L.sports[s], s);
  }
  assert.deepEqual(Object.keys(S.challengers).sort(), Object.keys(L.challengers).sort());
});

test("stage rows: reached is cumulative, 'stop here' sums to the total, never a percentage", () => {
  for (const s of L.sports_order) {
    const rows = stageRows(L.chain, L.sports[s].at_counts);
    assert.equal(rows[0].reached, L.sports[s].inputs_predictive);
    assert.equal(rows.reduce((a, r) => a + r.at, 0), L.sports[s].inputs_predictive);
    for (let i = 1; i < rows.length; i++) assert.ok(rows[i].reached <= rows[i - 1].reached);
    assert.deepEqual(rows.map(r => r.reached), L.sports[s].reached_counts);
  }
});

test("market inputs: default list is the predictive inputs; filters select by brute-force definition", () => {
  for (const [k, m] of Object.entries(L.markets)) {
    assert.equal(marketInputs(L, k).length, m.n_predictive, k);
    assert.equal(marketInputs(L, k, {predictiveOnly: false}).length, m.n_inputs_all_classes, k);
    for (const o of ["MISSING", "BLOCKED", "FAILED", "REJECTED", "UNKNOWN"]) {
      const want = m.inputs.filter(([i, , c]) => c === "PREDICTIVE" && L.inputs[i].stop && L.inputs[i].stop.outcome === o).length;
      assert.equal(marketInputs(L, k, {stop: o}).length, want, k + " " + o);
    }
    assert.equal(marketInputs(L, k, {stop: "challenger"}).length, m.at_counts.slice(5).reduce((a, b) => a + b, 0), k);
  }
});

test("input status names the stage it is at and the reason it stopped", () => {
  for (const i of Object.values(L.inputs)) {
    const st = inputStatus(L, i);
    assert.equal(st.at, L.chain[i.at]);
    if (i.at < 7) { assert.equal(st.next, L.chain[i.at + 1]); assert.ok(st.why.length > 0); assert.ok(!["OK", "PARTIAL"].includes(st.outcome)); }
  }
});

test("sport market list covers every archetype of the sport; search and challenger filter narrow it", () => {
  let total = 0;
  for (const s of L.sports_order) { const rows = sportMarkets(L, s); total += rows.length; assert.equal(rows.length, L.sports[s].archetypes, s); }
  assert.equal(total, 170);
  assert.ok(sportMarkets(L, "NBA", {q: "points"}).length >= 1);
  assert.ok(sportMarkets(L, "NBA", {q: "zzzz-no-such"}).length === 0);
  for (const s of L.sports_order) assert.equal(sportMarkets(L, s, {onlyChallenger: true}).length, L.sports[s].markets_with_challenger, s);
});

test("challenger results shown for a market are only rows that name that market", () => {
  for (const ch of Object.values(L.challengers)) for (const a of ch.archetypes) {
    const rows = challengerResults(ch, a);
    assert.ok(rows.every(r => r.archetypes.includes(a)));
    assert.ok(L.markets[a], a);
  }
});

test("challenger tally counts every pooled result row exactly once", () => {
  for (const ch of Object.values(L.challengers)) {
    const t = referenceTally(ch);
    assert.equal(t.reduce((a, x) => a + x.rows, 0), ch.results.length, ch.id);
    for (const x of t) assert.equal(Object.values(x.verdicts).reduce((a, b) => a + b, 0), x.rows);
  }
});
