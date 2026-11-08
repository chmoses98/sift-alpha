import React, {useEffect, useMemo, useState} from "react";
import summary from "../research/input_research/completeness/summary.json";
import phase from "../research/input_research/phase_control.json";

// Rendered only from committed JSON (alpha_engine.input_research.completeness). Nothing is hand-typed.
// "Ready for your approval" is the ceiling the code can award. It never says complete: only approval.json (a human decision) can.
const REVIEWS = import.meta.glob("../research/input_research/completeness/reviews/*.json");
const INDEP = import.meta.glob("../research/input_research/completeness/independent/*.json");
const ORDER = ["READY_FOR_USER_APPROVAL", "INDEPENDENT_REVIEW_OPEN_FINDINGS", "REVERIFICATION_PENDING", "AUTHORED_NOT_INDEPENDENTLY_REVIEWED", "STRUCTURE_INCOMPLETE", "NOT_STARTED"];
const LABEL = {READY_FOR_USER_APPROVAL: "ready for your approval", INDEPENDENT_REVIEW_OPEN_FINDINGS: "independent review: open findings", REVERIFICATION_PENDING: "awaiting second verification", AUTHORED_NOT_INDEPENDENTLY_REVIEWED: "authored · awaiting independent review", STRUCTURE_INCOMPLETE: "structure incomplete", NOT_STARTED: "not started"};
const KIND = {READY_FOR_USER_APPROVAL: "ok", INDEPENDENT_REVIEW_OPEN_FINDINGS: "chipwarn", REVERIFICATION_PENDING: "chipwarn", AUTHORED_NOT_INDEPENDENTLY_REVIEWED: "chipwarn", STRUCTURE_INCOMPLETE: "miss", NOT_STARTED: "miss"};
const nice = s => String(s ?? "").toLowerCase().replaceAll("_", " ");
const Chip = ({s}) => <span className={"ir-chip ir-" + KIND[s]}>{LABEL[s]}</span>;

function Bar({v}) {
  const tot = v.archetypes || 1;
  return <span className="cc-bar" role="img" aria-label={ORDER.map(k => `${v[k]} ${LABEL[k]}`).join(", ")}>
    {ORDER.map(k => v[k] > 0 && <i key={k} className={"cc-seg cc-" + KIND[k]} style={{width: (100 * v[k] / tot) + "%"}}/>)}
  </span>;
}

function Detail({sport, k}) {
  const [rec, setRec] = useState(undefined);
  const [ind, setInd] = useState(null);
  useEffect(() => {
    let live = true;
    (async () => {
      let found = null, indep = null;
      for (const [p, load] of Object.entries(REVIEWS)) if (p.includes(`/${sport}_`) || p.endsWith(`/${sport}.json`)) { const d = (await load()).default; if (d[k]) found = d[k]; }
      for (const [p, load] of Object.entries(INDEP)) if (p.endsWith(`/${sport}.json`)) { const d = (await load()).default; indep = d[k] || null; }
      if (live) { setRec(found); setInd(indep); }
    })();
    return () => { live = false; };
  }, [sport, k]);
  if (rec === undefined) return <p className="ir-fine">Loading review…</p>;
  if (!rec) return <p className="ir-fine">No review record yet for this archetype.</p>;
  const m = rec.mechanism, ct = rec.contract;
  return <div className="cc-detail">
    <h4>Contract</h4>
    <p>{ct.settlement_definition}</p>
    <p className="ir-fine"><b>Verification:</b> {nice(ct.rules_verification)}. <b>Settlement source:</b> {ct.settlement_data_source || "not stated"}.</p>
    <ul>{ct.variants_and_edge_cases.map((x, i) => <li key={i}>{x}</li>)}</ul>
    {(ct.rules_evidence || []).map((x, i) => <blockquote key={i} className="cc-quote"><code>{x.ticker}</code> “{x.quote}” <span className="ir-fine">— {x.establishes}</span></blockquote>)}
    <h4>Mechanism</h4>
    <p>{m.summary}</p>
    <ol>{m.stages.map(s => <li key={s.id}><b>{s.name}</b> <span className="ir-fine">[{s.categories.map(nice).join(", ")}]</span><br/>{s.description}<br/><span className="ir-fine"><b>Distribution:</b> {s.distribution} · <b>Inputs:</b> {s.input_ids.join(", ")}</span></li>)}</ol>
    <h4>Mechanism categories</h4>
    <div className="ir-scroll"><table className="ir-table" style={{minWidth: 520}}><tbody>{Object.entries(m.category_coverage).map(([c, v]) => <tr key={c}><td>{nice(c)}</td><td><span className={"ir-chip ir-" + (v.status === "COVERED" ? "ok" : v.status === "GAP" ? "miss" : "plain")}>{nice(v.status)}</span></td><td>{(v.input_ids || []).join(", ")}{v.note ? (v.input_ids?.length ? " — " : "") + v.note : ""}</td></tr>)}</tbody></table></div>
    <h4>Audit of existing inputs ({Object.keys(rec.input_audit).length})</h4>
    <div className="ir-scroll"><table className="ir-table" style={{minWidth: 520}}><tbody>{Object.entries(rec.input_audit).map(([i, v]) => <tr key={i}><td>{i}</td><td><span className={"ir-chip ir-" + (v.verdict.startsWith("KEEP") ? "ok" : "chipwarn")}>{nice(v.verdict)}</span></td><td>{v.reason}</td></tr>)}</tbody></table></div>
    <h4>New inputs discovered by this review ({Object.keys(rec.new_inputs || {}).length})</h4>
    {Object.entries(rec.new_inputs || {}).map(([i, v]) => <details key={i}><summary><b>{i}</b> — {v.label} <span className="ir-fine">({nice(v.category)}, pregame {v.pregame_knowable})</span></summary>
      <p>{v.rationale}</p><p><b>Calculation:</b> {v.measurement}</p><p className="ir-fine"><b>Raw data:</b> {v.raw_data.join("; ")} · <b>Sources:</b> {v.free_sources.join("; ")}</p></details>)}
    <h4>Interactions ({rec.interactions.length}) and non-linearities ({rec.nonlinearities.length})</h4>
    <ul>{rec.interactions.map((x, i) => <li key={i}><b>{x.inputs.join(" × ")}</b> <span className="ir-chip ir-plain">{x.form}</span> {x.mechanism} <span className="ir-fine"><b>Test:</b> {x.how_to_test}</span></li>)}
      {rec.nonlinearities.map((x, i) => <li key={"n" + i}><b>{x.input_id}</b> <span className="ir-chip ir-plain">{x.shape}</span> {x.why}</li>)}</ul>
    <h4>Required data</h4>
    <div className="ir-scroll"><table className="ir-table" style={{minWidth: 640}}><thead><tr><th>Dataset (grain)</th><th>Fields</th><th>As-of rule · history</th><th>Candidate sources</th></tr></thead>
      <tbody>{rec.required_data.map((d, i) => <tr key={i}><td>{d.dataset}<br/><span className="ir-fine">{d.grain}</span></td><td>{d.fields.join(", ")}</td><td>{d.timestamp_requirement}<br/><span className="ir-fine">{d.history_needed}</span></td><td>{d.candidate_sources.map(s => `${s.name} [${nice(s.access)}]${s.note ? ": " + s.note : ""}`).join("; ")}</td></tr>)}</tbody></table></div>
    <h4>Unresolved ({rec.unresolved.length}) — stated, not hidden</h4>
    <ul>{rec.unresolved.map((u, i) => <li key={i}><span className="ir-chip ir-chipwarn">{nice(u.type)}</span>{u.category ? <span className="ir-chip ir-plain">{nice(u.category)}</span> : null} {u.description} <span className="ir-fine"><b>Would resolve:</b> {u.what_would_resolve}</span></li>)}</ul>
    <h4>Independent review</h4>
    {!ind ? <p className="ir-fine">No independent review recorded yet.</p> : <>
      <p className="ir-fine">{ind.reviewer} · {ind.date} · verdict {nice(ind.verdict)}</p>
      <ul>{(ind.findings || []).map((f, i) => <li key={i}><span className={"ir-chip ir-" + (f.severity === "MINOR" ? "plain" : "miss")}>{f.severity.toLowerCase()}</span> {f.text} <span className="ir-fine"><b>Resolution:</b> {f.resolution}</span></li>)}</ul></>}
  </div>;
}

export function CatalogCompleteness() {
  const [sport, setSport] = useState("All");
  const [status, setStatus] = useState("All");
  const [open, setOpen] = useState(null);
  const sports = Object.keys(summary.by_sport);
  const rows = useMemo(() => summary.rows.filter(r => (sport === "All" || r.sport === sport) && (status === "All" || r.status === status)), [sport, status]);
  const t = summary.totals, paused = phase.predictive_experiments.state !== "RUNNING";
  return <section className="cc" aria-label="Catalog completeness gate" data-testid="catalog-completeness">
    <div className="eyebrow">CATALOG COMPLETENESS / WHAT INFORMATION DOES EVERY MARKET NEED</div>
    <h2>Catalog completeness gate: {t.READY_FOR_USER_APPROVAL} of {t.archetypes} archetypes ready for your approval, none declared complete</h2>
    {paused && <p className="ir-warn" data-testid="pause-banner"><b>Predictive experimentation is PAUSED.</b> {phase.instruction} All predictive results below on this page are <b>preliminary</b> (PR #60 / #62), preserved and not being expanded. RESEARCH ONLY: no orders, spending, deployments or merges.</p>}
    <p className="ir-fine">Approval recorded: <b>{summary.approval.approved ? "yes" : "no"}</b>. A populated list or a passing automated check is necessary, never sufficient. The code can award at most “ready for your approval”; only a human decision (approval.json) can mark anything approved.</p>
    <div className="ir-cards">{ORDER.map(k => <div key={k}><b>{t[k]}</b><small>{LABEL[k]}</small></div>)}</div>
    <div className="ir-scroll"><table className="ir-table" style={{minWidth: 700}}>
      <thead><tr><th>Sport</th><th>Archetypes</th><th>Progress</th>{ORDER.map(k => <th key={k}>{LABEL[k]}</th>)}<th>Inputs in catalog</th></tr></thead>
      <tbody>{sports.map(s => { const v = summary.by_sport[s]; return <tr key={s}><td><button className="cc-link" onClick={() => setSport(s)}>{s}</button></td><td>{v.archetypes}</td><td><Bar v={v}/></td>{ORDER.map(k => <td key={k}>{v[k]}</td>)}<td>{v.inputs}</td></tr>; })}</tbody></table></div>
    {summary.acceptance && <details open data-testid="acceptance"><summary><b>Documented acceptance criteria, evaluated from the artifacts</b>: {summary.acceptance.meets_criteria ? "all met" : "NOT all met"} (never approval)</summary>
      <div className="ir-scroll"><table className="ir-table" style={{minWidth: 560}}><thead><tr><th>Criterion</th><th>Result</th><th>Detail</th></tr></thead>
        <tbody>{summary.acceptance.criteria.map((c, i) => <tr key={i}><td>{c.criterion}</td><td><span className={"ir-chip ir-" + (c.pass ? "ok" : "miss")}>{c.pass ? "pass" : "not met"}</span></td><td>{c.detail}</td></tr>)}</tbody></table></div>
      <p className="ir-fine">{summary.acceptance.note}</p>
      <div className="ir-scroll"><table className="ir-table" style={{minWidth: 640}}><thead><tr><th>Sport</th><th>Inputs</th><th>Registered archetypes</th><th>New / unregistered archetypes</th><th>Interactions</th><th>Non-linearities</th><th>Inputs with raw-data definition</th></tr></thead>
        <tbody>{Object.entries(summary.acceptance.catalog_totals).map(([s, v]) => <tr key={s}><td>{s}</td><td>{v.inputs}</td><td>{v.registered_archetypes}</td><td>{v.unregistered_archetypes}</td><td>{v.archetype_interactions + v.blueprint_interactions}</td><td>{v.nonlinearities}</td><td>{v.inputs_with_raw_data_definition}</td></tr>)}</tbody></table></div>
      <p className="ir-fine"><b>Gaps</b> ({summary.acceptance.gap_classification.classified} of {summary.acceptance.gap_classification.declared} classified): {Object.entries(summary.acceptance.gap_classification.by_class).map(([k, v]) => `${nice(k)} ${v}`).join(" · ") || "none classified yet"}.</p>
      <p className="ir-fine"><b>Input audit</b>: {Object.values(summary.acceptance.input_audit.audited).reduce((a, b) => a + b, 0)} audited · market-free {Object.entries(summary.acceptance.input_audit.market_free).map(([k, v]) => `${k} ${v}`).join(", ") || "n/a"}.</p>
      <p className="ir-fine"><b>Verification record</b>: second verification of closed blocker/major findings {JSON.stringify(summary.acceptance.verification.second_verification_of_closed_blocker_major)}; post-reconcile audit {JSON.stringify(summary.acceptance.verification.post_reconcile_audit)}. Agents, not human experts.</p>
    </details>}
    <details className="ir-fine"><summary><b>Acceptance criteria</b> (every archetype)</summary><ol>{summary.criteria.map((c, i) => <li key={i}>{c}</li>)}</ol></details>
    <div className="ir-filter" role="group" aria-label="Sport filter">{["All", ...sports].map(s => <button key={s} className={s === sport ? "on" : ""} onClick={() => setSport(s)}>{s}</button>)}</div>
    <div className="ir-filter" role="group" aria-label="Status filter">{["All", ...ORDER].map(s => <button key={s} className={s === status ? "on" : ""} onClick={() => setStatus(s)}>{s === "All" ? "All statuses" : LABEL[s]}</button>)}</div>
    <div className="ir-scroll"><table className="ir-table" style={{minWidth: 860}}>
      <thead><tr><th>Sport</th><th>Market archetype</th><th>Status</th><th title="live Kalshi series (with rules text read)">Series (rules read)</th><th>Stages</th><th>New inputs</th><th>Existing audited</th><th>Interactions / non-linear</th><th>Datasets</th><th>Open gaps</th><th>Contract rules</th><th>Independent (open)</th></tr></thead>
      <tbody>{rows.map(r => { const id = r.sport + ":" + r.archetype; return <React.Fragment key={id}>
        <tr className={open === id ? "on" : ""}><td>{r.sport}</td>
          <td><button className="cc-link" aria-expanded={open === id} onClick={() => setOpen(open === id ? null : id)}>{r.archetype}</button><div className="ir-why">{r.registered ? "registered" : "unregistered contract type"} · {r.label}</div></td>
          <td><Chip s={r.status}/></td><td>{r.live_series} ({r.rules_text_series})</td><td>{r.stages ?? "–"}</td><td>{r.new_inputs ?? "–"}</td><td>{r.existing_inputs_audited ?? "–"}</td>
          <td>{r.interactions ?? "–"} / {r.nonlinearities ?? "–"}</td><td>{r.datasets ?? "–"}</td><td>{r.unresolved ?? "–"}</td><td>{nice(r.rules_verification) || "–"}</td><td>{r.independent ? nice(r.independent) : "–"} ({r.open_findings ?? "–"})</td></tr>
        {open === id && <tr className="cc-open"><td colSpan={12}><Detail sport={r.sport} k={r.archetype}/></td></tr>}</React.Fragment>; })}</tbody></table></div>
    <details><summary><b>Contract universe behind the review</b> (exact reconciled assignment of every ledger series)</summary>
      <div className="ir-scroll"><table className="ir-table" style={{minWidth: 760}}><thead><tr><th>Sport</th><th>Series</th><th>In scope</th><th>Out of scope (explicit)</th><th>No listed market: contract unreadable</th><th>In scope: rules text read</th><th>In scope: title only</th><th>In scope: no listing</th><th>Reviewed</th><th>Re-filed</th><th>In new archetypes</th></tr></thead>
        <tbody>{Object.entries(summary.contract_universe).map(([s, v]) => <tr key={s}><td>{s}</td><td>{v.series}</td><td>{v.in_scope}</td><td>{v.out_of_scope}</td><td>{v.no_listed_market}</td><td>{v.in_scope_rules_text_read}</td><td>{v.in_scope_title_only}</td><td>{v.in_scope_no_listing}</td><td>{v.reviewed_against_rules_or_title}</td><td>{v.refiled_by_review}</td><td>{v.in_new_archetypes}</td></tr>)}</tbody></table></div>
      <p className="ir-fine">Series that list no market, and series classified from the title alone, are explicitly unresolved rather than complete.</p>
      </details>
  </section>;
}
