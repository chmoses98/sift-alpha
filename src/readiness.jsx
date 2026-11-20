import React from "react";
import R from "../research/input_research/readiness/dashboard.json";
import Lad from "../research/pipeline/ladder_summary.json";
import {LADDER_LABEL, ladderRows, readinessCheck} from "./readiness.mjs";

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
      <tbody>{rows.map(r => <tr key={r.sport}><td>{r.sport}</td>{r.atLeast.map((v, i) => <td key={i}>{v.toLocaleString("en-US")}</td>)}</tr>)}</tbody></table></div>
    <p className="ir-fine">Counts are cumulative (“at least this level”). {chk.ladderOk ? "Certified count matches the ledger total." : "LADDER MISMATCH"} {Object.keys(Lad.registry_problems).length ? "Some registry claims failed their evidence checks and are not counted." : "Every registry claim passed its evidence check."}
      {Lad.non_catalog_columns_consumed.length ? ` Note: experiments so far consumed ${Lad.non_catalog_columns_consumed.map(x => x.columns.join(", ")).join("; ")} — intermediate builder columns, not certified catalog inputs.` : ""}</p>
    <h3>Missing PRIMARY slots by the action that would close them</h3>
    <div className="ir-scroll"><table className="ir-table" data-testid="readiness-classes"><thead><tr><th>Action class</th><th>Slots</th><th>In priority (P1) markets</th><th>Distinct inputs</th></tr></thead>
      <tbody>{R.classes.map(c => <tr key={c}><td>{c.replaceAll("_", " ").toLowerCase()}</td><td>{R.by_class[c] ?? 0}</td><td>{R.by_class_and_tier[c + "|P1"] ?? 0}</td><td>{R.distinct_inputs_by_class[c]}</td></tr>)}
        <tr><td><b>total</b></td><td data-testid="readiness-total"><b>{chk.classTotal}</b></td><td>{R.by_tier.P1}</td><td></td></tr></tbody></table></div>
    <p className="ir-fine" data-testid="readiness-recon">{chk.classesOk ? `Reconciles exactly with the completeness inventory (${R.totals.inventory_primary_missing_critical}).` : "DOES NOT RECONCILE with the completeness inventory"} Priority tiers: P1 {R.by_tier.P1} · P2 {R.by_tier.P2} · optional/low value {R.by_tier.F}.
      {R.rights_unresolved_slots} slots depend on a dataset whose licence is unresolved: free to access is not cleared for every use. Archived in the vault but still listed as merely reachable: {R.queue_corrections.join(", ")}.</p>
    <details><summary>Priority (P1) market readiness: certified share of PRIMARY inputs</summary>
      <div className="ir-scroll"><table className="ir-table" data-testid="p1-readiness"><thead><tr><th>Sport</th><th>Market</th><th>Certified / primary</th><th>Missing, by action</th></tr></thead>
        <tbody>{R.p1_market_readiness.map(p => <tr key={p.sport + p.archetype}><td>{p.sport}</td><td>{p.archetype.replaceAll("_", " ")}</td><td>{p.primary_certified} / {p.primary_inputs}</td>
          <td>{Object.entries(p.missing_by_class).map(([k, v]) => `${R.short[k]} ${v}`).join(" · ") || "none"}</td></tr>)}</tbody></table></div></details>
    <details><summary>Shared work: one dataset or builder that closes many priority slots</summary>
      <ul>{R.shared_work.slice(0, 10).map((g, i) => <li key={i}>{R.short[g.class]} · {g.datasets}: {g.P1_slots} P1 / {g.slots} slots, {g.distinct_inputs} inputs</li>)}</ul></details>
  </section>;
}
