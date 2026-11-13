import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { EMPTY_FILTERS, FILTER_SCOPE, datasetReach, edgeMatches, filterDatasets, filterInputs, filterMarkets, filterQueue, indexMap, inputDatasets, isMissingPrimary } from "../src/market-input-map.mjs";

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

// ---- Linked dependency filtering: every view is derived from the same matching-edge set, recomputed here by brute force.
const CASES = [
  {sport: "NBA", missing: true}, {sport: "NFL", primary: true, bucket: "REQUIRES_COLLECTION"}, {prospective: true}, {free: true, missing: true},
  {cls: "PREDICTIVE", sport: "TENNIS"}, {commercial: true}, {bucket: "FULL"}, {sport: "MLB", cls: "OPERATIONAL"},
].map(c => ({...EMPTY_FILTERS, ...c}));
const truthEdges = f => ix.edges.filter(e => edgeMatches(e, m.inputs[e.i], f));

for (const f of CASES) {
  const tag = JSON.stringify(Object.fromEntries(Object.entries(f).filter(([k, v]) => v !== EMPTY_FILTERS[k])));
  test(`linked filters agree across views ${tag}`, () => {
    const E = truthEdges(f);
    // Markets: exactly the archetypes owning a matching edge, listing exactly those edges
    const mk = filterMarkets(ix, f);
    assert.deepEqual(new Set(mk.map(r => r.a.k)), new Set(E.map(e => e.a)));
    assert.equal(mk.reduce((s, r) => s + r.edges.length, 0), E.length);
    // Inputs: every input that owns a matching edge is listed (inputs with no edge may also match input-level-only filters)
    const ik = new Set(filterInputs(ix, f).map(([k]) => k));
    for (const e of E) assert.ok(ik.has(e.i), e.i);
    // Datasets: exactly those that feed a listed input, and their linked set is a subset of the listed inputs
    const ds = filterDatasets(ix, f);
    const want = new Set(m.dataset_edges.filter(([d, i]) => ik.has(i) && (!f.commercial || m.datasets[d].rights.commercial_cleared)).map(([d]) => d));
    assert.deepEqual(new Set(ds.map(([id]) => id)), want);
    for (const [, , linked] of ds) for (const k of linked) assert.ok(ik.has(k));
    // Queue: matching slots are exactly the matching edges that are missing PRIMARY (restricted to commercial-cleared rows if that filter is on)
    const qs = filterQueue(ix, f);
    const got = new Set(qs.flatMap(x => x.match.map(([a, i]) => a + "|" + i)));
    const rowsOk = m.queue.filter(q => !f.commercial || q.commercial_cleared);
    const exp = new Set(E.filter(isMissingPrimary).map(e => e.a + "|" + e.i).filter(k => rowsOk.some(q => q.slots.some(([a, i]) => a + "|" + i === k))));
    assert.deepEqual(got, exp);
    // ranks are preserved (committed order, filtered)
    const ranks = qs.map(x => x.q.rank); assert.deepEqual(ranks, [...ranks].sort((a, b) => a - b));
  });
}

test("NBA + missing PRIMARY: queue slots equal the NBA missing PRIMARY edges; Market -> Dataset -> Queue linkage holds", () => {
  const f = {...EMPTY_FILTERS, sport: "NBA", missing: true};
  const nbaMissing = ix.edges.filter(e => e.a.startsWith("NBA:") && isMissingPrimary(e));
  const qs = filterQueue(ix, f);
  assert.equal(new Set(qs.flatMap(x => x.match.map(s => s.join("|")))).size, nbaMissing.length);
  for (const {q, match} of qs) for (const [a] of match) assert.ok(a.startsWith("NBA:"));
  // every dataset shown in the queue under this filter is also shown in the Datasets view under the same filter
  const ds = new Set(filterDatasets(ix, f).map(([id]) => id));
  for (const {q} of qs) assert.ok(ds.has(q.dataset), q.dataset);
});

test("unfiltered queue keeps all 121 rows in committed rank order and every group", () => {
  const qs = filterQueue(ix, EMPTY_FILTERS);
  assert.equal(qs.length, m.queue.length);
  assert.deepEqual(qs.map(x => x.q.rank), m.queue.map(q => q.rank));
  const G = m.reconciliation.queue_groups.groups;
  for (const [g, v] of Object.entries(G)) assert.equal(qs.filter(x => x.q.action_group === g).length, v.datasets);
});

test("every view documents how filters apply", () => {
  for (const v of ["markets", "inputs", "datasets", "queue"]) assert.ok(FILTER_SCOPE[v].length > 40);
});
