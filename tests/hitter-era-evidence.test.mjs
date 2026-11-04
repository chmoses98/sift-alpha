import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import eras from "../research/audit/lineage/mlb_hitter_evaluation_eras.json" with {type: "json"};

const original = eras.original_hitter_hits_opportunity_corpus;
const later = eras.later_hitter_calibration_study;
const guard = eras.compatibility;

test("MLB hitter historical gap cannot be silently rebaselined with a later calibration sample", () => {
  assert.equal(eras.schema_version, 1);
  assert.equal(eras.authority, "RESEARCH_ONLY_SCOPE_SEPARATED");
  assert.equal(original.market_family, "hitter_hits");
  assert.equal(original.date_start, "2026-08-01");
  assert.equal(original.date_end, "2026-08-20");
  assert.equal(original.observed_opportunity_rows, 23295);
  assert.equal(original.joined_temporally_valid_model_evaluations, 0);
  assert.equal(original.source_commit, "de1798270c6a7fa53ea0ed3cc0dae287bf58584c");
  assert.equal(original.source_git_blob_sha1, "2c63cbee32c78bd47cd4586e19766c4c7723dccd");

  assert.equal(later.date_start, "2026-08-19");
  assert.equal(later.date_end, "2026-09-23");
  assert.equal(later.source_commit, "a849ca9cb32f431b9f8a70378cee802bbb4af7dd");
  assert.equal(later.source_git_blob_sha1, "49ccf03396621f2a3a28fb12e3cd6eddb687994b");
  assert.match(later.measurement_status, /NOT_INDEPENDENTLY_REPLAYED/);
  assert.equal(later.all_families_unique_ticker_rows, 5913);
  assert.equal(later.hitter_hits_unique_ticker_rows, 1357);
  assert.equal(later.families.length, 4);
  assert.ok(later.hitter_hits_unique_ticker_rows < later.all_families_unique_ticker_rows);
  assert.ok(later.model_minus_market_brier_95ci[0] < 0 && later.model_minus_market_brier_95ci[1] > 0);
  assert.equal(later.profitability_certified, false);

  assert.equal(guard.same_population, false);
  assert.equal(guard.same_denominator, false);
  assert.equal(guard.no_automatic_retroactive_evaluation_credit, true);
  assert.equal(guard.actual_independently_verified_cross_corpus_market_join, false);
  assert.equal(guard.no_point_in_time_or_trading_authority, true);
});

test("dashboard labels MLB evaluation eras and soccer merge status without claiming production", () => {
  const dashboard = readFileSync(new URL("../src/foundation-dashboard.jsx", import.meta.url), "utf8");
  assert.match(dashboard, /import mlbHitterEras from/);
  assert.match(dashboard, /original_hitter_hits_opportunity_corpus\.observed_opportunity_rows/);
  assert.match(dashboard, /later_hitter_calibration_study\.hitter_hits_unique_ticker_rows/);
  assert.match(dashboard, /not independently replayed in Alpha/);
  assert.doesNotMatch(dashboard, /DRAFT PR #39/);
  assert.doesNotMatch(dashboard, /draft Soccer PR #39/);
  assert.match(dashboard, /Production archive coverage remains unverified/);
});
