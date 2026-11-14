import React from "react";
import comp from "../research/input_research/computable_summary.json";
import ss from "../research/audit/input_research/scaled_search_summary.json";

// Rendered only from committed JSON (alpha_engine.features.audit -> milestone2.py; alpha_engine.input_research.scaled_search). Nothing hand-typed.
const pc = x => x == null ? "–" : Math.round(100 * x) + "%";
const f2 = x => x == null || Number.isNaN(x) ? "–" : Number(x).toFixed(2);
const OKS = ["COMPUTED_FULL", "COMPUTED_PARTIAL", "COMPUTED_PROXY", "COMPUTED_LIMITED_FULL", "COMPUTED_LIMITED_PARTIAL", "COMPUTED_LIMITED_PROXY"];
const LABEL = {COMPUTED_FULL: "computed · full definition", COMPUTED_PARTIAL: "computed · partial definition", COMPUTED_PROXY: "computed · proxy measure", COMPUTED_LIMITED_PARTIAL: "computed · limited history", COMPUTED_LIMITED_FULL: "computed · limited history", COMPUTED_LIMITED_PROXY: "computed · limited history",
  UNVERIFIED_LEAK_TEST: "built, not verified", LEAK_FAIL: "built, FAILED leak test", NOT_PREGAME_ELIGIBLE: "built, not pregame-eligible", NOT_COMPUTED: "not computed", EXCLUDED_BENCHMARK_ONLY: "market-derived (benchmark only)", DEGENERATE: "degenerate", BUILD_FAILED: "build failed"};
const kind = s => OKS.includes(s) ? "ok" : s === "NOT_COMPUTED" ? "miss" : s === "EXCLUDED_BENCHMARK_ONLY" ? "plain" : "chipwarn";
const VCOL = {VALIDATED: "ok", SUGGESTIVE: "chipwarn", NOT_VALIDATED: "plain", NO_GAIN: "plain"};

export function ComputableInputsPanel({sport}) {
  const rows = comp.inputs.filter(r => r.k.startsWith(sport + ":"));
  const order = r => OKS.includes(r.s) ? 0 : r.s === "NOT_COMPUTED" ? 2 : r.s === "EXCLUDED_BENCHMARK_ONLY" ? 3 : 1;
  const sorted = [...rows].sort((a, b) => order(a) - order(b) || a.k.localeCompare(b.k));
  const t = comp.by_sport[sport] || {};
  const ok = rows.filter(r => OKS.includes(r.s)).length, nm = rows.filter(r => r.s !== "EXCLUDED_BENCHMARK_ONLY").length;
  return <details className="ir-fine" open>
    <summary><b>Verified computable inputs</b> — {comp.verified_computed} of {comp.n_non_market} non-market inputs computed and verified across all sports; {sport}: {ok} of {nm}</summary>
    <p className="ir-warn">“Computed” means a feature builder produced the column from real raw rows, it is non-constant, its coverage was measured, and a point-in-time perturbation test passed (outcomes of later games and of the game itself were randomised; earlier and own-row features stayed bit-identical). Source-name keyword matching never counts. “Partial” and “proxy” show what part of the catalog definition is actually implemented.</p>
    <div className="ir-cards">
      <div><b>{comp.verified_computed} / {comp.n_non_market}</b><small>verified computable (full {comp.verified_by_level.FULL || 0} · partial {comp.verified_by_level.PARTIAL || 0} · proxy {comp.verified_by_level.PROXY || 0})</small></div>
      <div><b>{(comp.totals.NOT_COMPUTED || 0)}</b><small>not computed: raw data class absent or no builder</small></div>
      <div><b>{(comp.totals.LEAK_FAIL || 0) + (comp.totals.UNVERIFIED_LEAK_TEST || 0)}</b><small>built but failed or could not be verified (kept out of the search)</small></div>
      <div><b>{comp.totals.EXCLUDED_BENCHMARK_ONLY || 0}</b><small>market-derived, benchmark only</small></div>
    </div>
    <div className="ir-scroll"><table className="ir-table" style={{minWidth: 620}}><thead><tr><th>{sport} input</th><th>Status</th><th>Coverage (min column)</th><th>History</th><th>What is missing / why</th></tr></thead>
      <tbody>{sorted.map(r => <tr key={r.k}><td>{r.k.split(":")[1]}</td><td><span className={"ir-chip ir-" + kind(r.s)}>{LABEL[r.s] || r.s}</span></td><td>{pc(r.cov)}</td><td>{r.from ? `${r.from.slice(0, 4)}–${r.to.slice(0, 4)}` : "–"}</td><td>{[...(r.miss || []), r.why].filter(Boolean).join("; ")}</td></tr>)}</tbody></table></div>
    <details><summary>Why inputs are not computed (raw data class absent)</summary><p>{Object.entries(comp.blocker_classes).map(([k, v]) => `${k.replaceAll("_", " ").toLowerCase()}: ${v}`).join(" · ")}</p></details>
  </details>;
}

export function ScaledSearchPanel() {
  const t = ss.totals, lg = ss.ledger, rows = ss.rows.filter(r => r.status === "TESTED");
  return <details className="ir-fine" open>
    <summary><b>Systematic combination testing (market-free, ledger-logged)</b> — {t.n_tested} markets, {lg.rows_logged.toLocaleString()} configuration-fold records logged; {t.verdicts?.VALIDATED || 0} validated</summary>
    <p className="ir-warn">Only audited inputs enter; no sportsbook line or Kalshi price is used. Every configuration (input groups, squares, interactions, ridge/boosting, penalty) × outer chronological block is written to an append-only ledger ({lg.unique_market_configurations.toLocaleString()} unique market-configurations; PR #59's {lg.lab59_experiments_read_only?.toLocaleString()} experiments are read from its branch, not copied). {ss.multiple_testing}.</p>
    <div className="ir-scroll"><table className="ir-table" style={{minWidth: 760}}><thead><tr><th>Market</th><th>Rows</th><th>Verified groups</th><th>Gain vs baseline</th><th>95% CI</th><th>Holm p</th><th>Blocks +</th><th>Null</th><th>Verdict</th></tr></thead>
      <tbody>{rows.map(r => <tr key={r.market}><td title={r.baseline}>{r.market.replace(":", " ").replaceAll("_", " ")}</td><td>{r.n.toLocaleString()}</td><td>{r.groups}</td><td>{f2(r.gain)}%</td><td>[{f2(r.ci[0])}, {f2(r.ci[1])}]</td><td>{r.holm_p < 0.001 ? "<0.001" : f2(r.holm_p)}</td><td>{r.pos}/{r.blocks}</td><td>{r.null.map(x => f2(x) + "%").join(", ")}</td><td><span className={"ir-chip ir-" + VCOL[r.verdict]}>{r.verdict === "VALIDATED" ? "validated vs baseline" : r.verdict.replace("_", " ").toLowerCase()}</span></td></tr>)}</tbody></table></div>
    <p>VALIDATED (always “versus the naive baseline shown”, never versus a market) = Holm-adjusted p &lt; 0.05 over all {t.n_tested} markets, CI above zero, both chronological halves positive, ≥70% of blocks positive and a gain above twice the permutation-null gain. SUGGESTIVE = nominal CI above zero only. Gains are measured against weak baselines (league mean / the player's own average), so they show information in the inputs, not a price edge; none has been compared with Kalshi prices.</p>
    {rows.filter(r => r.top?.length).slice(0, 12).map(r => <p key={r.market} className="ir-fine"><b>{r.market.replace(":", " ")}</b> — inputs whose removal hurts most: {r.top.map(([k, v]) => `${k.split(".").pop().replaceAll("_", " ")} (+${(100 * v).toFixed(2)}%)`).join(", ")}</p>)}
    {ss.rows.filter(r => r.status !== "TESTED").length > 0 && <p className="ir-fine">Not tested: {ss.rows.filter(r => r.status !== "TESTED").map(r => `${r.market} (${r.why})`).join("; ")}.</p>}
  </details>;
}
