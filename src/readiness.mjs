// Pure helpers for the operating-readiness panel (unit-tested in tests/readiness.test.mjs).
export const LADDER_LABEL = {
  EXISTS: "in catalog", CALCULATED: "calculated", CERTIFIED: "certified", EXPERIMENTAL_ADOPTION: "used by an experiment",
  PREDICTION_VERIFIED: "prediction gain verified", PRICE_AWARE_VERIFIED: "price-aware gain verified", PRODUCTION_CONSUMED: "consumed in production",
};

export const CLASS_LABEL = {
  A_FREE_NOT_COLLECTED: "A · data missing: free source known, not collected", A_NO_FREE_SOURCE: "A · data missing: no permitted free source known",
  A_SOURCE_CONTESTED: "A · data missing: source existence contested", B_DATA_IN_HAND_NO_BUILDER: "B · data in hand, no certified builder",
  C_CALCULATED_NOT_CERTIFIED: "C · calculated, certification failed or downgraded", E_PROSPECTIVE_CAPTURE: "E · needs timestamped capture from now on",
  G_LEGAL_POLICY_BLOCKED: "G · blocked by provider policy / terms",
};

export function ladderRows(lad) {
  const sports = Object.keys(lad.by_sport).sort();
  const cum = counts => lad.levels.map((_, i) => lad.levels.slice(i).reduce((a, l) => a + (counts[l] || 0), 0));
  const all = Object.fromEntries(lad.levels.map(l => [l, sports.reduce((a, s) => a + (lad.by_sport[s][l] || 0), 0)]));
  return [...sports.map(s => ({sport: s, atLeast: cum(lad.by_sport[s])})), {sport: "all", atLeast: cum(all)}];
}

export function readinessCheck(r, lad) {
  const classTotal = r.classes.reduce((a, c) => a + (r.by_class[c] || 0), 0);
  const all = ladderRows(lad).at(-1).atLeast;
  return {classTotal, classesOk: classTotal === r.totals.inventory_primary_missing_critical && r.totals.reconciles === true,
          ladderOk: all[lad.levels.indexOf("CERTIFIED")] === lad.counts_at_least.CERTIFIED && all[0] === lad.counts_at_least.EXISTS};
}
