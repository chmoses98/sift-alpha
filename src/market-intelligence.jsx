import React, {useMemo, useState} from "react";
import {STUDIES} from "./studies.mjs";
import master from "../research/audit/master_inventory.json";
import registry from "../research/audit/input_registry.json";
import status from "../research/audit/collection_status.json";
import gaps from "../research/audit/collection_gap_report.json";

// Everything below is generated from research/audit/*.json. Nothing here asserts completeness; anything absent is unknown.
const FAMILY_AUDITS = Object.values(import.meta.glob("../research/audit/audits/*.json", {eager: true, import: "default"}));
const SPORTS = Object.keys(registry.sports);
const TIER = {E: "Essential", C: "Contextual", X: "Exploratory"};
const COLL = {PIT_ARCHIVED: "ok", DERIVED: "ok", COLLECTED_NOT_PIT_ARCHIVED: "warn", PARTIAL_OR_STALE: "bad", SOURCE_AVAILABLE_NOT_COLLECTED: "bad", NO_RELIABLE_SOURCE: "bad", NO_REFERENCE_FOUND: "bad", CODE_REFERENCE_ONLY: "unk", UNKNOWN: "unk"};
const nice = s => s.toLowerCase().replaceAll("_", " ");
const n = v => v == null ? "—" : v.toLocaleString();
function Badge({v}) { return <span className={"badge b-" + (COLL[v] || "unk")}>{nice(v)}</span>; }

function FamilyDetail({fam, sport}) {
  const fr = registry.sports[sport].families[fam.id];
  const st = status.sports[sport].inputs;
  const defs = {...registry.common_inputs, ...registry.sports[sport].inputs};
  const groups = {E: [], C: [], X: []};
  Object.entries(fr?.inputs || {}).forEach(([id, t]) => groups[t].push(id));
  const audit = FAMILY_AUDITS.find(a => a.sport === sport && a.market_family === fam.native_family);
  return <div className="fam-detail">
    <p><strong>{fam.native_family}</strong> · {fam.canonical.kind.replaceAll("_", " ")} · {fam.canonical.scope} · periods {fam.canonical.periods.join(", ")}</p>
    <p className="fine">Observed: <b>{nice(fam.observed.state)}</b> — {n(fam.observed.markets_now)} markets now ({fam.observed.basis}; as of {fam.observed.as_of || "unknown"}){fam.markets_prior_snapshot != null && <> · prior snapshot {n(fam.markets_prior_snapshot)} ({fam.prior_snapshot_date})</>}. Series: {fam.series_count}{fam.series_sample.length ? " e.g. " + fam.series_sample.join(", ") : ""}.</p>
    <p className="fine">Settlement: {fam.settlement?.text || "unknown"} <em>({fam.settlement?.status || "UNKNOWN"}{fam.settlement?.source ? " · " + fam.settlement.source : ""})</em></p>
    {audit && <p className="fine audited">End-to-end audit exists: repair priority {audit.repair_priority}, verified {audit.last_verified_utc}. See audit file for per-input evidence.</p>}
    {["E", "C", "X"].map(t => groups[t].length > 0 && <div key={t}><h4>{TIER[t]} candidate inputs ({groups[t].length})</h4>
      <div className="inp-grid">{groups[t].map(id => { const s = st[id]; return <div className="inp" key={id}>
        <strong>{defs[id].label}</strong>
        <div><Badge v={s.collection}/> <span className="badge b-use">model: {nice(s.model_use)}</span></div>
        <p className="fine">{s.note}{s.evidence?.length > 0 && <> · evidence: {s.evidence.map(e => e.replace(/^(doc|arch):/, "")).join("; ")}</>}</p>
      </div>; })}</div></div>)}
    <p className="fine">Tier = candidate relevance, not validated predictive value. Validation status: not tested.</p>
  </div>;
}

export function MarketIntelligence() {
  const [sport, setSport] = useState("NFL");
  const [kind, setKind] = useState("all");
  const [sel, setSel] = useState(null);
  const sm = master.sports[sport];
  const fams = useMemo(() => master.families.filter(f => f.sport === sport && (kind === "all" || f.canonical.kind === kind)).sort((a, b) => (b.observed.markets_now || b.markets_prior_snapshot || 0) - (a.observed.markets_now || a.markets_prior_snapshot || 0)), [sport, kind]);
  const kinds = [...new Set(master.families.filter(f => f.sport === sport).map(f => f.canonical.kind))].sort();
  const fam = fams.find(f => f.id === sel) || fams[0];
  const g = gaps.sports[sport];
  const sc = status.sports[sport];
  const relevant = STUDIES.filter(x => x.sport === sport).slice(0, 3);
  return <section className="intelligence" aria-label="Market intelligence foundation dashboard">
    <div className="eyebrow">MARKET INTELLIGENCE / DATA FOUNDATION · generated from research/audit</div>
    <h2>What markets exist, what inputs matter, what do we collect?</h2>
    <p>Inventory built {master.generated_utc}. Counts have a different basis per sport (see each family) and are never summed across sports. “Not observed” means absent from that snapshot, not nonexistent. Candidate inputs are hypotheses; none is claimed predictive.</p>
    <div className="sport-tabs" role="tablist">{SPORTS.map(s => <button key={s} role="tab" aria-selected={s === sport} className={s === sport ? "on" : ""} onClick={() => {setSport(s); setKind("all"); setSel(null);}}>{s}</button>)}</div>
    <div className="intelligence-summary">
      <strong>{sm.families} families · {sm.series} series</strong><span>{sm.families_observed_now} observed in latest snapshot · {master.families.filter(f => f.sport === sport && f.observed.state === "OBSERVED_PRIOR_SNAPSHOT_ONLY").length} only in an older snapshot · {master.families.filter(f => f.sport === sport && f.observed.state === "DEFINED_NOT_OBSERVED").length} defined, not observed</span>
      <span>{g.inputs} candidate inputs ({g.curated_inputs} with curated evidence)</span><span>unclassified: {sm.unclassified_families.length ? sm.unclassified_families.join(", ") : "none"}</span>
    </div>
    <div className="status-row">{Object.entries(g.status_counts).sort((a, b) => b[1] - a[1]).map(([k, v]) => <span key={k} className={"badge b-" + (COLL[k] || "unk")}>{nice(k)}: {v}</span>)}</div>
    <h3>Top collection gaps — {sport}</h3>
    <div className="gap-list">{g.top_gaps.slice(0, 6).map(r => <div className="gap" key={r.input}><strong>{r.label}</strong> <Badge v={r.collection}/> <span className="badge b-use">model: {nice(r.model_use)}</span>
      <span className="fine"> essential for {r.essential_for_families} families · {(r.share_of_sport_markets * 100).toFixed(0)}% of this sport's observed markets</span><p className="fine">{r.note}</p></div>)}</div>
    <h3>Market families</h3>
    <div className="intelligence-filters"><label>Kind<select value={kind} onChange={e => {setKind(e.target.value); setSel(null);}}><option value="all">all kinds</option>{kinds.map(k => <option key={k}>{k}</option>)}</select></label>
      <label>Family<select value={fam?.id || ""} onChange={e => setSel(e.target.value)}>{fams.map(f => <option key={f.id} value={f.id}>{f.native_family} — {n(f.observed.markets_now ?? f.markets_prior_snapshot)} mkts · {nice(f.observed.state)}</option>)}</select></label></div>
    {fam && <FamilyDetail fam={fam} sport={sport}/>}
    <h3>Cross-sport gap ranking (within-sport shares)</h3>
    <ol className="fine">{gaps.cross_sport.slice(0, 8).map((r, i) => <li key={i}><b>{r.sport}</b> {r.input} — {nice(r.collection)}, model {nice(r.model_use)}, {(r.share_of_sport_markets * 100).toFixed(0)}% of its markets</li>)}</ol>
    <div className="intelligence-related"><strong>Related source-linked research</strong>{relevant.length ? relevant.map(x => <p key={x.id}>{x.title} · {x.status} {x.sources[0]?.url && <a href={x.sources[0].url} target="_blank" rel="noreferrer">Source ↗</a>}</p>) : <p>No verified sport-specific research records are linked yet.</p>}</div>
    <p className="fine-print">Sources: {sc.repo}@{sc.commit.slice(0, 7)} · {sc.archives.length} archive branches scanned. Static code references are not proof of correct collection or use. Predictive value: untested. No completeness percentage is inferred.</p>
  </section>;
}
