// Pure helpers for the Data Foundation pipeline section (no React). Tested against the real artifacts in tests/data-foundation.test.mjs.
export const STAGE_LABEL = {
  IDENTIFIED: "Identified", SOURCE_LOCATED: "Source located", COLLECTED: "Collected", VERIFIED: "Verified", FEATURE_BUILT: "Feature built",
  CHALLENGER_INTEGRATED: "Research challenger integrated", EVALUATED: "Evaluated", VALIDATED_IMPROVEMENT: "Validated improvement",
  PRODUCTION_APPROVED: "Production approved", PRODUCTION_ACTIVE: "Production active"};
export const OUTCOME_KIND = {OK: "ok", PARTIAL: "chipwarn", MISSING: "plain", UNKNOWN: "unv", BLOCKED: "miss", FAILED: "miss", REJECTED: "miss"};
export const OUTCOME_LABEL = {OK: "reached", PARTIAL: "partial", MISSING: "missing", UNKNOWN: "unknown", BLOCKED: "blocked", FAILED: "failed", REJECTED: "rejected"};
export const VERDICT_KIND = {VALIDATED_IMPROVEMENT: "ok", IMPROVED_NOT_VALIDATED: "chipwarn", INCONCLUSIVE: "unv", NOT_IMPROVED: "miss", REJECTED: "miss", DESCRIPTIVE: "plain"};
export const VERDICT_LABEL = {DESCRIPTIVE: "descriptive only (not in the tested family)", VALIDATED_IMPROVEMENT: "validated improvement", IMPROVED_NOT_VALIDATED: "improved, not validated", INCONCLUSIVE: "inconclusive", NOT_IMPROVED: "not improved", REJECTED: "rejected"};
export const P0 = ["NBA", "CBB", "NHL"];

export const fmt = n => n == null ? "UNKNOWN" : typeof n === "number" ? n.toLocaleString("en-US") : String(n);
export const num = (x, d = 4) => x == null ? "n/a" : (x >= 0 ? "" : "−") + Math.abs(x).toFixed(d);
export const signed = (x, d = 4) => x == null ? "n/a" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d);

// Stage rows for a sport or market: how many predictive inputs REACHED each stage (cumulative) and how many are AT it (stopped there).
export function stageRows(chain, atCounts) {
  let tail = atCounts.reduce((a, b) => a + b, 0);
  return chain.map((s, i) => { const reached = tail; tail -= atCounts[i]; return {stage: s, label: STAGE_LABEL[s], reached, at: atCounts[i]}; });
}

export const stageOf = (ledger, inp) => ledger.chain[inp.at];

// The single status line shown for an input: the stage it is AT, plus what stopped it at the next one.
export function inputStatus(ledger, inp) {
  const at = ledger.chain[inp.at];
  return inp.stop ? {at, next: inp.stop.stage, outcome: inp.stop.outcome, why: inp.stop.why} : {at, next: null, outcome: "OK", why: ""};
}

export const ROLE_ORDER = {primary: 0, secondary: 1, context: 2, interaction: 3};

export function marketInputs(ledger, key, {predictiveOnly = true, stop = "any", q = ""} = {}) {
  const mk = ledger.markets[key]; if (!mk) return [];
  const needle = q.trim().toLowerCase();
  return mk.inputs.map(([k, role, cls]) => ({key: k, role, cls, ...ledger.inputs[k]}))
    .filter(r => !predictiveOnly || r.cls === "PREDICTIVE")
    .filter(r => stop === "any" ? true : stop === "validated" ? r.at === 7 : stop === "challenger" ? r.at >= 5 : stop === "production" ? r.production_active === "OK" || r.production_active === "PARTIAL" : (r.stop && r.stop.outcome === stop))
    .filter(r => !needle || (r.label + " " + r.id).toLowerCase().includes(needle))
    .sort((a, b) => (ROLE_ORDER[a.role] ?? 9) - (ROLE_ORDER[b.role] ?? 9) || b.at - a.at || a.id.localeCompare(b.id));
}

export function sportMarkets(ledger, sport, {q = "", sort = "primary", onlyChallenger = false} = {}) {
  const needle = q.trim().toLowerCase();
  const rows = Object.entries(ledger.markets).filter(([, m]) => m.sport === sport).map(([key, m]) => ({key, ...m}))
    .filter(m => !onlyChallenger || m.challengers.length)
    .filter(m => !needle || (m.label + " " + m.name + " " + m.series.join(" ")).toLowerCase().includes(needle));
  const built = m => m.at_counts_primary.slice(4).reduce((a, b) => a + b, 0);
  const cmp = {primary: (a, b) => b.n_primary - a.n_primary, built: (a, b) => built(b) - built(a), challenger: (a, b) => b.challengers.length - a.challengers.length,
    missing: (a, b) => (b.n_primary - built(b)) - (a.n_primary - built(a)), name: () => 0}[sort] || (() => 0);
  return rows.sort((a, b) => cmp(a, b) || a.label.localeCompare(b.label));
}

export function challengerResults(ch, archetype) {
  return ch.results.filter(r => !archetype || r.archetypes.includes(archetype));
}

// Reconciliation used by the tests and shown in the footer: every count on screen must come back to these.
export function reconcile(ledger) {
  const inputs = Object.values(ledger.inputs);
  const bySport = {};
  for (const s of ledger.sports_order) {
    const pred = inputs.filter(i => i.sport === s && i.predictive);
    bySport[s] = {predictive: pred.length, at: ledger.chain.map((_, i) => pred.filter(x => x.at === i).length)};
  }
  return {inputs: inputs.length, markets: Object.keys(ledger.markets).length, datasets: Object.keys(ledger.datasets).length, bySport};
}

// Short tally for a challenger card: per kind of reference, how many result rows got each verdict (computed, never typed).
// The kind comes from the ledger (alpha_engine.foundation.contract.reference_kind, fail-closed), not from guessing at names here.
export const REF_LABEL = {CURRENT_MODEL: "the current model", MARKET: "the market price", PRIOR_CHALLENGER: "an earlier challenger", BASELINE: "a simple baseline"};
export function referenceTally(ch) {
  const out = {};
  for (const r of ch.results) { const k = r.reference_kind; (out[k] ||= {}); out[k][r.verdict] = (out[k][r.verdict] || 0) + 1; }
  return Object.keys(REF_LABEL).filter(k => out[k]).map(k => ({against: REF_LABEL[k], kind: k, rows: Object.values(out[k]).reduce((a, b) => a + b, 0), verdicts: out[k]}));
}

export const BOARD_LABEL = {NO_CHALLENGER: "no research challenger yet", NO_VALIDATED_GAIN: "no validated gain", VALIDATED_VS_CURRENT_MODEL_ONLY: "validated gains over the current model only; none over the market",
  VALIDATED_VS_MARKET: "validated gain over the market price on at least one row"};
export const BOARD_KIND = {NO_CHALLENGER: "plain", NO_VALIDATED_GAIN: "unv", VALIDATED_VS_CURRENT_MODEL_ONLY: "chipwarn", VALIDATED_VS_MARKET: "ok"};
export const GAP_LABEL = {WORSE_THAN_MARKET: "worse than the market", BETTER_THAN_MARKET: "better than the market", NO_DETECTABLE_DIFFERENCE: "no detectable difference"};
export const GAP_KIND = {WORSE_THAN_MARKET: "miss", BETTER_THAN_MARKET: "ok", NO_DETECTABLE_DIFFERENCE: "unv"};
// Days between the newest data a sport's challengers read and the day the page is viewed (freshness is shown, never hidden).
export const ageDays = (day, now = new Date()) => day ? Math.max(0, Math.floor((now - new Date(day + "T00:00:00Z")) / 864e5)) : null;
