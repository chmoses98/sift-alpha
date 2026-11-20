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

// P1 tracker (readiness_ledger.p1_tracker): progress against the frozen 2026-11-20 baseline of 180 priority slots.
export const P1_CATEGORY = [
  ["A_closed_certified_full_or_partial", "A · P1 slots closed by FULL or PARTIAL certification"],
  ["B_closed_by_proxy", "B · P1 slots covered only by a PROXY input"],
  ["C_built_not_certified_inputs", "C · inputs replayed but not certified (count)"],
  ["D_data_held_not_transformed", "D · missing P1 slots whose data is held (needs a builder)"],
  ["E_future_capture_required", "E · missing P1 slots needing prospective capture"],
  ["F_licensing_or_policy_blocked", "F · missing P1 slots blocked by provider policy"],
  ["G_owner_decision_required", "G · missing P1 slots needing an owner certification decision"],
];

export function p1TrackerCheck(t) {
  if (!t) return {ok: false, closed: 0, missing: null};
  const s = t.summary, lv = s.H_closed_by_level;
  const closedByLevel = lv.FULL + lv.PARTIAL + lv.PROXY;
  const perInput = t.inputs.reduce((a, i) => a + i.p1_slots, 0), perInputClosed = t.inputs.reduce((a, i) => a + i.p1_slots_closed, 0);
  return {ok: s.reconciles === true && closedByLevel === s.closed && perInput === s.baseline_p1_slots && perInputClosed === s.closed
            && s.A_closed_certified_full_or_partial + s.B_closed_by_proxy === s.closed,
          closed: s.closed, missing: s.p1_missing_now, baseline: s.baseline_p1_slots};
}

export function p1CategoryValue(s, key) {
  const v = s[key];
  return Array.isArray(v) ? v.length : v;
}
