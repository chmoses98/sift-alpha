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
test("market benchmark is labelled a closing line, never a Kalshi price, and the no-market path says so", () => {
  for (const d of Object.values(docs)) for (const p of Object.values(d.paths)) {
    if (p.level === "L2_TESTED_VS_MARKET") assert.match(p.benchmark, /not a Kalshi price/i);
    if (p.level === "L1_TESTED_VS_BASELINE") assert.match(p.benchmark, /^NO MARKET/);
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
