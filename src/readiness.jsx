import React from "react";
import R from "../research/input_research/readiness/dashboard.json";
import Lad from "../research/pipeline/ladder_summary.json";
import {CLASS_LABEL, LADDER_LABEL, P1_CATEGORY, ladderRows, p1CategoryValue, p1TrackerCheck, readinessCheck} from "./readiness.mjs";

// Rendered only from research/input_research/readiness/dashboard.json (readiness_ledger.py) and research/pipeline/ladder_summary.json (pipeline/ladder.py).
// Catalog completeness (how many market-input slots exist) is NOT operating readiness (can SIFT price its priority markets with certified, adopted,
// prediction- and price-verified inputs). Levels above "certified" move only through evidence-checked registry claims, never through keyword matches.
export function OperatingReadiness() {
  const chk = readinessCheck(R, Lad), rows = ladderRows(Lad);
  return <section className="cc" aria-label="Operating readiness" data-testid="operating-readiness">
    <div className="eyebrow">OPERATING READINESS / NOT THE SAME AS CATALOG COMPLETENESS</div>
    <h2>What is actually ready to drive a priced market?</h2>
    <p className="ir-fine"><b>RESEARCH ONLY.</b> The catalog counts {R.totals.slots.toLocaleString("en-US")} missing PRIMARY slots (one input required by one market type). Slots are not datasets: many share one dataset or one builder.
      Readiness asks a stricter question per input: calculated → certified → used by a frozen experiment → verified to improve prediction on unseen games → verified against executable prices → consumed in production.</p>
    <div className="ir-scroll"><table className="ir-table" data-testid="ladder-table"><thead><tr><th>Sport</th>{Lad.levels.map(l => <th key={l}>{LADDER_LABEL[l]}</th>)}</tr></thead>
      <tbody>{rows.map(r => <tr key={r.sport}><td style={{whiteSpace: "nowrap"}}>{r.sport}</td>{r.atLeast.map((v, i) => <td key={i}>{v.toLocaleString("en-US")}</td>)}</tr>)}</tbody></table></div>
    <p className="ir-fine">Counts are cumulative (“at least this level”). {chk.ladderOk ? "Certified count matches the ledger total." : "LADDER MISMATCH"} {Object.keys(Lad.registry_problems).length ? "Some registry claims failed their evidence checks and are not counted." : "Every registry claim passed its evidence check."}
      {Lad.non_catalog_columns_consumed.length ? ` Note: experiments so far consumed ${Lad.non_catalog_columns_consumed.map(x => x.columns.join(", ")).join("; ")} — intermediate builder columns, not certified catalog inputs.` : ""}</p>
    <h3>Missing PRIMARY slots by the action that would close them</h3>
    <div className="ir-scroll"><table className="ir-table" data-testid="readiness-classes"><thead><tr><th>Action class</th><th>Slots</th><th>In priority (P1) markets</th><th>Distinct inputs</th></tr></thead>
      <tbody>{R.classes.map(c => <tr key={c}><td style={{whiteSpace: "normal", minWidth: "11em"}}>{CLASS_LABEL[c] || c}</td><td>{R.by_class[c] ?? 0}</td><td>{R.by_class_and_tier[c + "|P1"] ?? 0}</td><td>{R.distinct_inputs_by_class[c]}</td></tr>)}
        <tr><td><b>total</b></td><td data-testid="readiness-total"><b>{chk.classTotal}</b></td><td>{R.by_tier.P1}</td><td></td></tr></tbody></table></div>
    <p className="ir-fine" data-testid="readiness-recon">{chk.classesOk ? `Reconciles exactly with the completeness inventory (${R.totals.inventory_primary_missing_critical}).` : "DOES NOT RECONCILE with the completeness inventory"} Priority tiers: P1 {R.by_tier.P1} · P2 {R.by_tier.P2} · optional/low value {R.by_tier.F}.{" "}
      {R.rights_unresolved_slots} of {R.totals.slots} slots depend on a dataset whose licence is unresolved: free to access is not cleared for every use. Archived in the vault but still listed as merely reachable: {R.queue_corrections.join(", ")}.</p>
    <details><summary>Priority (P1) market readiness: certified share of PRIMARY inputs</summary>
      <div className="ir-scroll"><table className="ir-table" data-testid="p1-readiness"><thead><tr><th>Sport</th><th>Market</th><th>Certified / primary</th><th>Missing, by action</th></tr></thead>
        <tbody>{R.p1_market_readiness.map(p => <tr key={p.sport + p.archetype}><td>{p.sport}</td><td>{p.archetype.replaceAll("_", " ")}</td><td>{p.primary_certified} / {p.primary_inputs}</td>
          <td>{Object.entries(p.missing_by_class).map(([k, v]) => `${R.short[k]} ${v}`).join(" · ") || "none"}</td></tr>)}</tbody></table></div></details>
    {R.p1_tracker && <P1Tracker t={R.p1_tracker} />}
    <details><summary>Shared work: one dataset or builder that closes many priority slots</summary>
      <ul>{R.shared_work.slice(0, 10).map((g, i) => <li key={i}>{R.short[g.class]} · {g.datasets}: {g.P1_slots} P1 / {g.slots} slots, {g.distinct_inputs} inputs</li>)}</ul></details>
  </section>;
}

// Priority (P1) progress against the frozen sprint-start baseline (research/input_research/readiness/p1_baseline_20261120.json). A slot counts as closed only when the
// input it names is certified in the ledger (verified_coverage), never from code presence or a field-name match.
function P1Tracker({t}) {
  const chk = p1TrackerCheck(t), s = t.summary, lv = s.H_closed_by_level;
  const open = t.inputs.filter(i => i.remaining_blocker).sort((a, b) => b.p1_slots - a.p1_slots || a.sport.localeCompare(b.sport));
  const done = t.inputs.filter(i => !i.remaining_blocker);
  return <div data-testid="p1-tracker">
    <h3>Priority (P1) slots: {chk.baseline} at the start of the 2026-11-20 sprint → <span data-testid="p1-missing-now">{chk.missing}</span> missing now</h3>
    <p className="ir-fine" data-testid="p1-recon">{chk.ok ? "Reconciles with the ledger and the baseline." : "DOES NOT RECONCILE"} Closed: {s.closed} (FULL {lv.FULL} · PARTIAL {lv.PARTIAL} · PROXY {lv.PROXY}).
      A PROXY input measures the mechanism differently from the catalog definition; it closes the slot under the ledger rule but is reported separately.</p>
    <div className="ir-scroll"><table className="ir-table" data-testid="p1-categories"><tbody>{P1_CATEGORY.map(([k, label]) => <tr key={k}><td style={{whiteSpace: "normal"}}>{label}</td><td>{p1CategoryValue(s, k)}</td></tr>)}
      <tr><td style={{whiteSpace: "normal"}}>Missing P1 slots that depend on a dataset with unresolved rights</td><td>{s.F_missing_slots_with_unresolved_rights}</td></tr></tbody></table></div>
    <details><summary>Open P1 inputs ({open.length}): what each measures and what blocks it</summary>
      <div className="ir-scroll"><table className="ir-table" data-testid="p1-open"><thead><tr><th>Sport</th><th>Input</th><th>Markets</th><th>P1 slots</th><th>Data held?</th><th>Built?</th><th>Certification</th><th>Remaining blocker</th></tr></thead>
        <tbody>{open.map(i => <tr key={i.sport + i.input_id}><td>{i.sport}</td><td style={{whiteSpace: "normal", minWidth: "12em"}}><b>{i.label || i.input_id}</b><br /><span className="ir-fine">{i.input_id}</span></td>
          <td style={{whiteSpace: "normal"}}>{i.markets.map(m => m.replaceAll("_", " ")).join(", ")}</td><td>{i.p1_slots - i.p1_slots_closed}</td><td>{i.collection_status.replaceAll("_", " ").toLowerCase()}</td>
          <td>{i.calculation_status.replaceAll("_", " ").toLowerCase()}</td><td>{(i.certification_status || "").replaceAll("_", " ").toLowerCase()}</td><td style={{whiteSpace: "normal", minWidth: "14em"}}>{i.remaining_blocker}</td></tr>)}</tbody></table></div></details>
    <details><summary>Closed P1 inputs ({done.length})</summary>
      <div className="ir-scroll"><table className="ir-table" data-testid="p1-closed"><thead><tr><th>Sport</th><th>Input</th><th>P1 slots</th><th>Level</th><th>Adoption</th></tr></thead>
        <tbody>{done.map(i => <tr key={i.sport + i.input_id}><td>{i.sport}</td><td style={{whiteSpace: "normal", minWidth: "12em"}}><b>{i.label || i.input_id}</b><br /><span className="ir-fine">{i.input_id}</span></td>
          <td>{i.p1_slots}</td><td>{i.certified_level}</td><td>{(LADDER_LABEL[i.adoption_level] || i.adoption_level || "").toLowerCase()}</td></tr>)}</tbody></table></div></details>
  </div>;
}
