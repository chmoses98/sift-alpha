import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const s = JSON.parse(readFileSync(new URL("../research/audit/lab/dashboard_summary.json", import.meta.url), "utf8"));
const raw = readFileSync(new URL("../research/audit/lab/dashboard_summary.json", import.meta.url), "utf8");

test("lab summary is research-only and aggregate-only", () => {
  assert.equal(s.mode, "RESEARCH_ONLY");
  assert.ok(!/KXNFL[A-Z0-9]*-\d\d[A-Z]{3}/.test(raw), "no Kalshi tickers");
  assert.ok(!/order_id|client_order|api_key/i.test(raw));
});

test("every family carries a verdict derived from its CI and none claims an edge", () => {
  assert.ok(s.families.length >= 8);
  for (const r of s.families) {
    const [lo, hi] = r.ci_after;
    const want = hi < 0 ? "MARKET_BETTER" : lo > 0 ? "MODEL_BETTER_UNCONFIRMED" : "NO_DIFFERENCE_DETECTED";
    assert.equal(r.verdict, want, r.family);
  }
  assert.ok(!/profitab|positive ev|edge confirmed/i.test(JSON.stringify(s.claim_boundary).replace(/no after-fee edge|nothing here is an after-fee edge/gi, "")));
});

test("prospective status never reports inference before the pre-registered minimum", () => {
  assert.ok(s.prospective_2026.decision_games < 60 ? /withheld/.test(s.prospective_2026.inference) : true);
});

test("panel is mounted", () => {
  assert.ok(/<LabResearch \/>/.test(readFileSync(new URL("../src/main.jsx", import.meta.url), "utf8")));
});

test("summary never presents unmerged build artifacts as live evidence", () => {
  assert.match(s.evidence_status.dashboard_panel, /NOT_VIEWED/);
  assert.match(s.evidence_status.prospective_workflow, /INERT|NOT_MERGED/);
  assert.ok(["INSUFFICIENT_N", "FAIL", "PASS_PROVISIONAL"].includes(s.prospective_2026.gate));
});

test("panel shows the evidence-status warning", () => {
  assert.ok(/lab-evidence-status/.test(readFileSync(new URL("../src/lab-research.jsx", import.meta.url), "utf8")));
});
