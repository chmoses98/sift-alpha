import { SPORT_REGISTRY, sportLabel, sportById, isCustomSport, SPORT_GROUPS } from "../src/sport-registry.mjs";
import test from "node:test";
import assert from "node:assert/strict";
import { STUDIES } from "../src/studies.mjs";
import readiness from "../research/audit/essential_readiness.json" with { type: "json" };
import valueEvidence from "../research/audit/lineage/source_value_probe_summary.json" with { type: "json" };
import { readFileSync } from "node:fs";
import { SPORTS, createDraft, filterStudies, makeSnapshot, readSnapshot, validSource } from "../src/domain.mjs";

test("curated records have real evidence URLs, honest status and a next action", () => {
  assert.equal(new Set(STUDIES.map((s) => s.id)).size, STUDIES.length);
  for (const s of STUDIES) {
    assert.ok(SPORTS.includes(s.sport));
    assert.ok(s.date.match(/^\d{4}-\d{2}-\d{2}$/));
    assert.ok(s.question.length > 15 && s.next.length > 15 && s.caveat.length > 15);
    assert.ok(Array.isArray(s.sources) && s.sources.length > 0);
    for (const source of s.sources) assert.ok(validSource(source.url));
  }
});
test("filter supports quick keyword, sport and evidence-state narrowing", () => {
  assert.equal(filterStudies(STUDIES, "biggest model", "NBA").length, 1);
  assert.equal(filterStudies(STUDIES, "", "MLB").length, 1);
  assert.equal(filterStudies(STUDIES, "", "All sports", "Verify fix").length, 1);
  assert.equal(filterStudies(STUDIES, "something absent").length, 0);
});
test("new drafts never imply a validated strategy", () => {
  const draft = createDraft("Does price move after roster news?", "NFL", "local-test");
  assert.equal(draft.status, "Draft");
  assert.match(draft.finding, /Not tested/);
  assert.equal(draft.sources.length, 0);
  assert.throws(() => createDraft("too", "NBA", "local-test"));
  assert.throws(() => createDraft("This is a useful question", "Unknown", "local-test"));
});
test("notes and drafts can be exported and restored without changing cited records", () => {
  const draft = createDraft("Does pricing respond late to injury news?", "NBA", "local-123");
  const snapshot = makeSnapshot([draft], { [draft.id]: "Test a genuine pregame cutoff." }, { [draft.id]: [0, 2] });
  const restored = readSnapshot(JSON.stringify(snapshot));
  assert.equal(restored.drafts[0].status, "Draft");
  assert.equal(restored.notes[draft.id], "Test a genuine pregame cutoff.");
  assert.deepEqual(restored.tasks[draft.id], [0, 2]);
  assert.equal(STUDIES.find((s) => s.id === "nba-selector-tail").status, "Investigate");
  assert.throws(() => readSnapshot('{"version":1,"drafts":[{"id":"not-local","question":"This looks like a question","sport":"NBA"}],"notes":{}}'));
  assert.throws(() => readSnapshot("not json"));
});
test("user-supplied URLs cannot cause unsafe source navigation", () => {
  assert.ok(validSource("https://github.com/chmoses98/nba-edge-finder/issues/39"));
  assert.equal(validSource("javascript:alert(1)"), false);
  assert.equal(validSource("https://github.com.evil.example/path"), false);
});

test("all sport groups are distinct, and CFB CBB NCAA baseball are first-class research tracks", () => {
  assert.equal(new Set(SPORT_REGISTRY.map((x) => x.id)).size, SPORT_REGISTRY.length);
  for (const id of ["CFB", "CBB", "NCAA-BASEBALL", "NBA", "NFL", "MLB", "NHL", "SOCCER", "TENNIS"]) {
    assert.ok(sportById(id), id + " must exist");
  }
  assert.equal(sportById("NCAA-BASEBALL").research, "Needs research pipeline");
  assert.equal(sportById("CBB").research, "Existing repository");
  assert.ok(SPORT_GROUPS.includes("Baseball / Softball"));
  assert.equal(sportLabel("NCAA-BASEBALL"), "NCAA Baseball");
  assert.ok(SPORTS.includes("OTHER"), "new/unclassified sports remain researchable");
  for (const row of SPORT_REGISTRY) {
    assert.ok(row.id && row.label && row.group && row.priority && row.research);
    assert.ok(["Existing repository", "Needs research pipeline"].includes(row.research));
    if (row.repository) assert.ok(validSource(row.repository));
    if (row.marketEvidence) assert.ok(validSource(row.marketEvidence));
  }
});
test("future sport can start an honest local draft without a model", () => {
  const sport = "Custom: Cycling";
  assert.equal(isCustomSport(sport), true);
  const draft = createDraft("Do weather changes affect road race outcomes?", sport, "local-cycling");
  assert.equal(draft.sport, sport);
  assert.equal(draft.status, "Draft");
  const restored = readSnapshot(JSON.stringify(makeSnapshot([draft], {}, {})));
  assert.equal(restored.drafts[0].sport, sport);
  assert.equal(createDraft("Do match odds show late information?", "Soccer", "local-legacy").sport, "SOCCER");
  assert.throws(() => createDraft("Research question can run now?", "Custom: <script>", "local-invalid"));
});
test("source URLs accept only GitHub and Kalshi HTTPS hosts", () => {
  assert.ok(validSource("https://kalshi.com/markets/kxncaabbgame/college-baseball-game"));
  assert.equal(validSource("https://kalshi.com.evil.invalid/markets"), false);
  assert.equal(validSource("http://kalshi.com/markets"), false);
});

test("dashboard reads strict essential evidence rather than a blueprint tally", () => {
  const dashboard = readFileSync(new URL("../src/foundation-dashboard.jsx", import.meta.url), "utf8");
  assert.match(dashboard, /import readiness from/);
  assert.match(dashboard, /Strict verified collection only/);
  assert.match(dashboard, /er\.dims/);
  assert.match(dashboard, /er\.gaps/);
  assert.match(dashboard, /predictive validation is independent/);
  for (const [id, family] of Object.entries(readiness.families)) {
    assert.ok(family.required >= family.verified, id);
    assert.equal(family.required - family.verified, family.gaps.length, id);
    assert.equal(family.required, Object.values(family.dims).reduce((n, d) => n + d.required, 0), id);
    assert.equal(family.verified, Object.values(family.dims).reduce((n, d) => n + d.verified, 0), id);
    assert.ok(family.gaps.every(g => g.class !== "VERIFIED_COLLECTION"), id);
  }
  for (const [sport, summary] of Object.entries(readiness.sports)) {
    const families = Object.values(readiness.families).filter(r => r.sport === sport);
    assert.equal(summary.ALL.verified, families.reduce((n, r) => n + r.verified, 0), sport);
    assert.equal(summary.ALL.required, families.reduce((n, r) => n + r.required, 0), sport);
  }
});

test("value-level evidence remains source only and is visible in dashboard", () => {
  assert.equal(valueEvidence.workflow_run, 41713797744);
  assert.equal(valueEvidence.soccer.original_missing, 11);
  assert.equal(valueEvidence.soccer.now_retrievable_with_bilateral_shots_sot_corners_cards, 11);
  assert.equal(valueEvidence.soccer.original_missing_kickoffs_older_than_probe_100h_lookback, 11);
  assert.equal(valueEvidence.tennis.atp_competitor_statistics + valueEvidence.tennis.wta_competitor_statistics, 0);
  assert.equal(valueEvidence.tennis.atp_completed + valueEvidence.tennis.wta_completed, 149);
  assert.equal(valueEvidence.tennis.atp_linescores + valueEvidence.tennis.wta_linescores, 148);
  assert.match(valueEvidence.classification, /SOURCE_AVAILABLE_NOT_COLLECTED/);
  const dashboard = readFileSync(new URL("../src/foundation-dashboard.jsx", import.meta.url), "utf8");
  assert.match(dashboard, /import valueEvidence from/);
  assert.match(dashboard, /valueEvidence.soccer.now_retrievable_with_bilateral_shots_sot_corners_cards/);
  assert.match(dashboard, /valueEvidence.tennis.atp_completed/);
});
