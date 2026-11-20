import React from "react";
import d from "../research/audit/derived_inputs.json";

// Rendered only from research/audit/derived_inputs.json (python -m alpha_engine.derived.verify). Nothing hand-typed.
// Four separate questions per input, never merged: definition completeness (level), verification (leak replay + independent recomputation + coverage),
// out-of-sample evidence against a stated naive baseline, and whether any projection model consumes it.
const pc = x => x == null ? "–" : Math.round(100 * x) + "%";
const LV = {FULL: "full definition", PARTIAL: "partial definition", PROXY: "proxy measure"};
const PRED = {BEATS_NAIVE_BASELINE_OOS: ["beats naive baseline", "ok"], MIXED_VS_NAIVE_BASELINE: ["mixed vs baseline", "chipwarn"], NO_GAIN_VS_NAIVE_BASELINE: ["no gain vs baseline", "plain"], NOT_ASSESSED: ["not assessed", "plain"]};
const ADOPT = {NOT_ADOPTED: "no related code found in the projection repo", CONCEPT_REFERENCED_IN_PROJECTION_REPO: "a related concept is mentioned in projection code (keyword probe; not this input)", NOT_PROBED: "projection repo not probed"};
const CERT = {VERIFIED_FULL: ["certified full", "ok"], VERIFIED_PARTIAL: ["certified partial", "ok"], VERIFIED_PROXY: ["certified proxy", "ok"], NOT_IN_CATALOG: ["not in catalog", "plain"],
  REQUIRES_COLLECTION: ["not certified: foundation replay / blind match pending", "chipwarn"], BLOCKED_CONTESTED: ["not certified: ledger says blocked (contested)", "chipwarn"],
  DOWNGRADED_BY_VERIFIER: ["not certified: downgraded by an earlier verifier", "chipwarn"]};
const certOf = r => r.certification || {status: r.kind === "catalog" ? "UNKNOWN" : "NOT_IN_CATALOG"};
const was = s => s === "NOT_IN_CATALOG" ? "new input" : s === "NOT_COMPUTED" ? "was not computed" : "was " + s.replace("COMPUTED_", "").replaceAll("_", " ").toLowerCase();
const weakest = t => t.length ? t.reduce((a, b) => b.improvement_pct < a.improvement_pct ? b : a) : null;   // show the weakest test, never the best one

export function DerivedInputsPanel({sport}) {
  const rows = d.inputs.filter(r => r.sport === sport), sp = d.sports[sport], acc = d.accounting, cert = acc.certified, pend = acc.pending_promotion, cs = cert.by_sport[sport] || {}, ps = pend.by_sport[sport] || {};
  const ok = rows.filter(r => r.status.startsWith("COMPUTED"));
  const fresh = ok.filter(r => r.kind === "catalog" && !r.previous_status.startsWith("COMPUTED")).length, up = ok.filter(r => r.kind === "catalog" && r.previous_status.startsWith("COMPUTED")).length, disc = ok.filter(r => r.kind === "discovered").length;
  const gov = d.governance || {}, cat = rows.filter(r => r.kind === "catalog"), certN = cat.filter(r => certOf(r).certified).length, mineN = cat.filter(r => certOf(r).by_this_builder).length;
  const fams = new Map(); ok.forEach(r => r.lineage.kalshi_families.forEach(f => fams.set(f.family, f.markets_now || 0)));
  return <details className="ir-fine" open aria-label={`Derived inputs unlocked from archived data for ${sport}`}>
    <summary><b>Derived inputs unlocked from data we already hold</b> — {sport}: {ok.length} calculated · {certN} of {cat.length} catalog inputs certified · 0 consumed by an operating model</summary>
    <p className="ir-warn">Research-only build, from one shared engine from archived box scores and schedules (no new collection, no market prices). “Calculated” means the engine’s own checks passed: later and same-game outcomes were shuffled and every earlier feature stayed unchanged (tolerance {sp ? sp.pit_test.tolerance : d.sports[Object.keys(d.sports)[0]].pit_test.tolerance}); the core estimates were recomputed by separate plain code and matched; coverage was measured. “Full” is claimed only when the whole definition is implemented. Out-of-sample evidence compares the input with a naive baseline on the latest seasons; it is not a claim that any projection model improved. <b>Certification is separate:</b> a catalog input counts as certified only when the data-foundation ledger (verified_coverage.json) holds it after the foundation’s replay and a blind exact-match re-implementation; this panel only reads that ledger. Generated {d.generated_utc}.</p>
    <div className="ir-cards" aria-label="Calculated, certified and consumed are separate">
      <div><b>{ok.length}</b><small>{sport} inputs calculated by this engine (its own leak replay, recomputation and coverage checks passed; not certification)</small></div>
      <div><b>{certN} of {cat.length}</b><small>{sport} catalog inputs certified in the data-foundation ledger (foundation replay + blind exact match); {mineN} on this builder's own evidence, {certN - mineN} by an earlier builder</small></div>
      <div><b>0</b><small>{sport} inputs consumed by an operating model{rows[0]?.operating_model?.operating_model ? ` (promoted: ${rows[0].operating_model.operating_model})` : ""}; adoption needs a separate approved model change</small></div>
    </div>
    <div className="ir-cards">
      <div><b>{cs.verified_computed ?? "–"} → {ps.verified_computed ?? "–"}</b><small>{sport} catalog computability ledger (computable_inputs.json): computed today → if these builds were adopted there (all sports {cert.verified_computed} → {pend.verified_computed} of {acc.catalog_inputs - acc.benchmark_only_excluded})</small></div>
      <div><b>{fresh} + {up} + {disc}</b><small>this build for {sport}: newly computed · upgraded · new inputs outside the catalog</small></div>
      <div><b>{ps.calculation_only ?? "–"}</b><small>{sport} still calculation-only: raw data graded present, no verified builder yet (estimate)</small></div>
      <div><b>{ps.acquisition_gap ?? "–"}</b><small>{sport} real acquisition gaps: a required raw data class is absent</small></div>
    </div>
    {sp ? <>
      <p><b>Lineage.</b> Raw: {sp.raw.join("; ")} → {sp.team_games.toLocaleString()} team-games, seasons {sp.seasons[0]}–{sp.seasons[1]}, through {sp.last_game_date} → {sp.feature_columns_verified} verified feature columns → {fams.size} Kalshi families ({[...fams.values()].reduce((a, b) => a + b, 0).toLocaleString()} markets observed now). Leak replay cut {sp.pit_test.cut}: {sp.pit_test.rows_on_or_before_cut.toLocaleString()} earlier rows unchanged, {sp.pit_test.rows_after_cut.toLocaleString()} later rows moved. Independent recomputation: {sp.independent_check.n_rows} sampled rows, {sp.independent_check.ok ? "all matched" : "MISMATCH"}.</p>
      <div className="ir-scroll"><table className="ir-table" style={{minWidth: 860}}><thead><tr><th>{sport} input</th><th>Definition</th><th>Foundation certification</th><th>Before</th><th>Coverage</th><th>Out-of-sample vs naive baseline (latest 4 seasons)</th><th>Operating model / projection code</th><th>Kalshi families</th><th>Not implemented yet</th></tr></thead>
        <tbody>{rows.map(r => { const b = weakest(r.predictive.tests), nt = r.predictive.tests.length, [pl, pk] = PRED[r.predictive.label] || [r.predictive.label, "plain"]; return <tr key={r.id}>
          <td title={r.definition}>{r.id.split(".").slice(1).join(".").replaceAll("_", " ")}{r.kind === "discovered" ? " *" : ""}</td>
          <td><span className={"ir-chip ir-" + (r.status.startsWith("COMPUTED") ? "ok" : "chipwarn")}>{r.status.startsWith("COMPUTED") ? LV[r.level] + (r.kind === "discovered" ? " (own definition)" : "") : r.status.replaceAll("_", " ").toLowerCase()}</span></td>
          <td>{(([cl, ck]) => <span className={"ir-chip ir-" + ck} title={(certOf(r).limits || []).join("; ")}>{cl}{certOf(r).by_this_builder ? " (this builder)" : certOf(r).certified ? " (earlier builder)" : ""}</span>)(CERT[certOf(r).status] || [certOf(r).status.replaceAll("_", " ").toLowerCase(), "plain"])}</td>
          <td>{was(r.previous_status)}</td>
          <td>{pc(r.coverage.min)} · {r.coverage.first.slice(0, 7)} to {r.coverage.last.slice(0, 7)}</td>
          <td><span className={"ir-chip ir-" + pk}>{pl}</span>{b ? ` ${nt > 1 ? `weakest of ${nt} tests, ` : ""}${b.pred.replace("_pre", "").replaceAll("_", " ")}: ${b.improvement_pct > 0 ? "+" : ""}${b.improvement_pct.toFixed(1)}% ${b.metric.replace("_", " ")} (n ${b.n.toLocaleString()})` : ""}</td>
          <td><b>not consumed</b>; {ADOPT[r.lineage.model_adoption.status] || r.lineage.model_adoption.status}</td>
          <td>{r.lineage.kalshi_families.map(f => f.family.split("/")[1].replaceAll("_", " ").toLowerCase()).join(", ")}</td>
          <td>{r.missing.join("; ") || "–"}</td></tr>; })}</tbody></table></div>
      <p className="ir-fine">* new input proposed by this build; it is not in the approved catalog and its “full” level is judged against its own stated definition. No input here is consumed by a projection model yet: adoption requires a separate, approved model change.</p>
    </> : <p>No derived-input build covers {sport} yet. The shared engine currently reads NBA and CBB box scores; the counts above come from the catalog ledger.</p>}
    <details><summary>Real acquisition gaps by missing raw data class (all sports)</summary><p>{Object.entries(pend.acquisition_gap_by_raw_class).map(([k, v]) => `${k.replaceAll("_", " ").toLowerCase()}: ${v}`).join(" · ")}. {acc.raw_class_regraded_by_this_build.length > 0 ? `Graded absent in the ledger but computed here from archived box scores: ${acc.raw_class_regraded_by_this_build.join("; ")}. ` : ""}{acc.note}</p></details>
  </details>;
}
