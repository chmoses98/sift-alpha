import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
const rd = f => JSON.parse(readFileSync(new URL("../research/audit/input_research/" + f, import.meta.url)));
const idx = rd("index.json"), queue = rd("queue.json");
const SPORTS = ["NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"];
const docs = Object.fromEntries(SPORTS.map(s => [s, rd(`sport_${s}.json`)]));
const reg = JSON.parse(readFileSync(new URL("../research/audit/input_registry.json", import.meta.url))).sports;

test("research-only status and all eight sports published", () => {
  assert.equal(idx.status, "RESEARCH_ONLY");
  assert.deepEqual(Object.keys(idx.sports).sort(), [...SPORTS].sort());
});
test("every registry family appears for its sport (none hidden)", () => {
  for (const s of SPORTS) assert.deepEqual(Object.keys(docs[s].families).sort(), Object.keys(reg[s].families).sort(), s);
});
test("no family above L2 and evidence paths match levels", () => {
  for (const d of Object.values(docs)) for (const [f, v] of Object.entries(d.families)) {
    assert.ok(["L0_INVENTORY_ONLY", "L1_TESTED_VS_BASELINE", "L2_TESTED_VS_MARKET"].includes(v.level), f);
    assert.equal(v.level === "L0_INVENTORY_ONLY", v.evidence_paths.length === 0, f);
  }
});
test("every candidate input referenced has a rationale, mechanism and availability record", () => {
  for (const d of Object.values(docs)) {
    for (const a of Object.values(d.archetypes)) for (const i of a.inputs) {
      const def = d.inputs[i.id]; assert.ok(def, i.id);
      assert.ok(def.rationale.length >= 60 && def.mechanism.length >= 25, i.id);
      assert.ok(def.availability.overall, i.id);
      assert.equal(i.tested, i.evidence.length > 0);
    }
  }
});
test("tested inputs carry uncertainty and false-discovery control", () => {
  for (const d of Object.values(docs)) for (const p of Object.values(d.paths)) for (const r of Object.values(p.result.inputs)) {
    assert.ok(Array.isArray(r.incremental.ci95) && r.incremental.q_bh >= 0 && r.incremental.q_bh <= 1 + 1e-9);
  }
});
test("market benchmark is labelled a near-close sportsbook line, never a Kalshi price, and the no-market path says so", () => {
  for (const d of Object.values(docs)) for (const p of Object.values(d.paths)) {
    if (p.level === "L2_TESTED_VS_MARKET") assert.match(p.benchmark, /not a Kalshi price/i);
    if (p.level === "L1_TESTED_VS_BASELINE") assert.match(p.benchmark, /^NO MARKET/);
  }
});
test("every family, input and interaction is reachable in the published data (275 / 691 / 679)", () => {
  let fam = 0, inp = 0, ix = 0;
  for (const d of Object.values(docs)) {
    fam += Object.keys(d.families).length; inp += Object.keys(d.inputs).length;
    ix += Object.values(d.archetypes).reduce((a, x) => a + x.interactions.length, 0) + Object.values(d.blueprints).reduce((a, x) => a + x.interactions.length, 0);
    for (const b of Object.values(d.blueprints)) assert.ok(b.families.length > 0);
  }
  assert.deepEqual([fam, inp, ix], [275, 691, 679]);
});
test("every path states a claim boundary that mentions Kalshi, and headline models are strict-pregame", () => {
  for (const d of Object.values(docs)) for (const p of Object.values(d.paths)) {
    assert.match(p.claim_boundary, /kalshi/i);
    const best = p.result.headline_models.ridge_all || p.result.headline_models.logit_all;
    assert.equal(best.pit_strict, true);
  }
});
test("queue is ranked, costs $0, and promises no profit", () => {
  const sc = queue.items.map(q => q.score);
  assert.deepEqual(sc, [...sc].sort((a, b) => b - a));
  assert.ok(queue.items.every(q => q.cost.startsWith("$0")));
  assert.ok(!/guaranteed|profitable|\+ev/i.test(JSON.stringify(queue)));
});
test("dashboard component and stylesheet are wired into the page", () => {
  const main = readFileSync(new URL("../src/main.jsx", import.meta.url), "utf8");
  assert.match(main, /<InputResearch \/>/);
  assert.ok(existsSync(new URL("../src/input-research.css", import.meta.url)));
});

// milestone 2: verified computable inputs + scaled search artifacts must be internally consistent
const comp = JSON.parse(readFileSync(new URL("../research/input_research/computable_summary.json", import.meta.url)));
const ss = JSON.parse(readFileSync(new URL("../research/audit/input_research/scaled_search_summary.json", import.meta.url)));
test("computable summary: one status per catalog input, verified count reconciles", () => {
  assert.equal(comp.status, "RESEARCH_ONLY");
  assert.equal(comp.inputs.length, comp.n_inputs);
  assert.equal(Object.values(comp.totals).reduce((a, b) => a + b, 0), comp.n_inputs);
  assert.equal(comp.n_non_market, comp.n_inputs - comp.totals.EXCLUDED_BENCHMARK_ONLY);
  const ok = comp.inputs.filter(r => r.s.startsWith("COMPUTED"));
  assert.equal(ok.length, comp.verified_computed);
  for (const r of comp.inputs) {
    if (r.s === "NOT_COMPUTED") assert.ok(r.why && r.why.length > 5, r.k);
  }
});
test("scaled search: every tested market states baseline, null, Holm p and a verdict; validated rows satisfy the rule", () => {
  assert.equal(ss.status, "RESEARCH_ONLY");
  const rows = ss.rows.filter(r => r.status === "TESTED");
  assert.equal(rows.length, ss.totals.n_tested);
  assert.ok(ss.ledger.rows_logged >= rows.length * 50, "every configuration is logged");
  assert.ok(ss.ledger.lab59_experiments_read_only >= 13362);
  for (const r of rows) {
    assert.ok(r.baseline && r.null.length >= 1 && r.holm_p >= 0 && r.holm_p <= 1, r.market);
    if (r.verdict === "VALIDATED") {
      assert.ok(r.holm_p < 0.05 && r.ci[0] > 0 && Math.min(...r.halves) > 0 && r.pos / r.blocks >= 0.7, r.market);
      assert.ok(r.gain > 2 * Math.max(0, ...r.null), r.market);
    }
  }
});
