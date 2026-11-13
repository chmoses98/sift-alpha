import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { EMPTY_FILTERS, datasetReach, filterDatasets, filterInputs, filterMarkets, indexMap, inputDatasets, isMissingPrimary } from "../src/market-input-map.mjs";

const m = JSON.parse(readFileSync(new URL("../research/input_research/market_input_map/map.json", import.meta.url)));
const ix = indexMap(m);

test("index covers every archetype, edge and distinct input", () => {
  assert.equal(m.archetypes.length, 170);
  assert.equal(ix.edges.length, 4243);
  assert.equal(Object.keys(m.inputs).length, 1649);
  assert.equal(ix.edges.filter(e => e.cls === "PREDICTIVE").length, 3670);
  assert.equal(ix.edges.filter(isMissingPrimary).length, 949);
});

test("unfiltered views list all 170 markets, 1,649 inputs and 165 datasets", () => {
  assert.equal(filterMarkets(ix, EMPTY_FILTERS).length, 170);
  assert.equal(filterInputs(ix, EMPTY_FILTERS).length, 1649);
  assert.equal(filterDatasets(ix, EMPTY_FILTERS).length, 165);
});

test("filters: missing-primary edges across markets total 949; class and sport filters partition", () => {
  const rows = filterMarkets(ix, {...EMPTY_FILTERS, missing: true});
  assert.equal(rows.reduce((s, r) => s + r.edges.length, 0), 949);
  const pred = filterMarkets(ix, {...EMPTY_FILTERS, cls: "PREDICTIVE"}).reduce((s, r) => s + r.edges.length, 0);
  assert.equal(pred, 3670);
  const bySport = ["NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"].reduce((s, sp) => s + filterInputs(ix, {...EMPTY_FILTERS, sport: sp}).length, 0);
  assert.equal(bySport, 1649);
  for (const [, v] of filterInputs(ix, {...EMPTY_FILTERS, commercial: true})) assert.equal(v.rights.commercial_cleared, true);
});

test("Market -> Input -> Dataset -> affected markets round-trips without duplicates", () => {
  const e = ix.byArch.get("NFL:game_total").find(x => x.role === "primary");
  const ds = [...inputDatasets(ix, e.i).keys()];
  assert.ok(ds.length > 0);
  const reach = datasetReach(ix, ds[0]);
  assert.ok(reach.inputs.has(e.i));
  assert.ok(reach.markets.has("NFL:game_total"));
  assert.equal(new Set(reach.markets.keys()).size, reach.markets.size);
});

test("queue rows are unique datasets and their slots are real missing-primary edges", () => {
  const missing = new Set(ix.edges.filter(isMissingPrimary).map(e => e.a + "|" + e.i));
  assert.equal(new Set(m.queue.map(q => q.dataset)).size, m.queue.length);
  const covered = new Set();
  for (const q of m.queue) for (const [a, i] of q.slots) { assert.ok(missing.has(a + "|" + i)); covered.add(a + "|" + i); }
  assert.equal(covered.size, 949);
});
