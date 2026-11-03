import React, {useMemo, useState} from "react";
import {STUDIES} from "./studies.mjs";
import master from "../research/audit/master_inventory.json";
import registry from "../research/audit/input_registry.json";
import status from "../research/audit/collection_status.json";
import gaps from "../research/audit/collection_gap_report.json";
import tennisIv from "../research/audit/sources/tennis_results_intervals.json";
import soccerAmb from "../research/audit/resolutions/soccer_ambiguous.json";
import soccerCtx from "../research/audit/lineage/soccer_context_lineage.json";
import soccerEv from "../research/audit/lineage/soccer_archive_and_espn_probe_evidence.json";
import mktExtra from "../research/audit/lineage/market_record_fields_extra.json";
import nbaProt from "../research/audit/variants/NBA_PROT_equivalence.json";
import tsInt from "../research/audit/integrity/timestamp_integrity.json";
import rvb from "../research/audit/integrity/record_vs_batch_timing.json";
import wxPit from "../research/audit/lineage/soccer_weather_pit_report.json";
import gapsArch from "../research/audit/lineage/historical_archive_gaps.json";
import sweepSum from "../research/audit/sweep_results/summary.json";
import tennisOpt from "../research/audit/sources/tennis_results_options.json";

// Everything below is generated from research/audit/*.json. Nothing here asserts completeness; anything absent is unknown.
const FAMILY_AUDITS = Object.values(import.meta.glob("../research/audit/audits/*.json", {eager: true, import: "default"}));
const SPORTS = Object.keys(registry.sports);
const TIER = {E: "Essential", C: "Contextual", X: "Exploratory"};
const COLL = {PIT_ARCHIVED: "ok", DERIVED: "ok", COLLECTED_NOT_PIT_ARCHIVED: "warn", PARTIAL_OR_STALE: "stale", SOURCE_AVAILABLE_NOT_COLLECTED: "bad", NO_RELIABLE_SOURCE: "bad", NO_REFERENCE_FOUND: "unk", CODE_REFERENCE_ONLY: "code", UNKNOWN: "unk",
  VERIFIED_COLLECTION: "ok", COLLECTED_UNVERIFIED_PIT: "warn", STALE_OR_PARTIAL: "stale", MISSING: "bad"};
const VNAME = {VERIFIED_COLLECTION: "verified collection", COLLECTED_UNVERIFIED_PIT: "collected, PIT unverified", STALE_OR_PARTIAL: "stale / partial", MISSING: "missing", CODE_REFERENCE_ONLY: "code reference only", UNKNOWN: "unknown", DERIVED: "derived"};
const nice = s => s.toLowerCase().replaceAll("_", " ");
const n = v => v == null ? "—" : v.toLocaleString();
function Badge({v, raw}) { return <span title={raw ? nice(raw) : undefined} className={"badge b-" + (COLL[v] || "unk")}>{VNAME[v] || nice(v)}</span>; }

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
    {fam.historical && <p className="fine">Historical coverage: {fam.historical.state === "OBSERVED" ? <>first seen {fam.historical.first_seen}, last {fam.historical.last_seen}; present on {fam.historical.days_present} of {fam.historical.snapshot_days} archived days ({fam.historical.calendar_days_without_snapshot} calendar days in the span have no snapshot); peak {n(fam.historical.markets_peak)} markets/day. Basis: {fam.historical.basis}.</> : <b>{nice(fam.historical.state)}</b>}</p>}
    {audit && <p className="fine audited">End-to-end audit exists: repair priority {audit.repair_priority}, verified {audit.last_verified_utc}. See audit file for per-input evidence.</p>}
    {["E", "C", "X"].map(t => groups[t].length > 0 && <div key={t}><h4>{TIER[t]} candidate inputs ({groups[t].length})</h4>
      <div className="inp-grid">{groups[t].map(id => { const s = st[id]; return <div className="inp" key={id}>
        <strong>{defs[id].label}</strong>
        <div><Badge v={s.verification_class} raw={s.collection}/> <span className="badge b-use">model: {nice(s.model_use)}</span></div>
        <p className="fine">{s.note}{s.evidence?.length > 0 && <> · evidence: {s.evidence.map(e => e.replace(/^(doc|arch):/, "")).join("; ")}</>}</p>
      </div>; })}</div></div>)}
    <p className="fine">Tier = candidate relevance, not validated predictive value. Validation status: not tested.</p>
  </div>;
}

export function FoundationDashboard() {
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
  return <section className="intelligence" aria-label="Data foundation dashboard">
    <div className="eyebrow">MARKET INTELLIGENCE / DATA FOUNDATION · generated from research/audit</div>
    <h2>What markets exist, what inputs matter, what do we collect?</h2>
    <p>Inventory built {master.generated_utc}. Counts have a different basis per sport (see each family) and are never summed across sports. “Not observed” means absent from that snapshot, not nonexistent. Candidate inputs are hypotheses; none is claimed predictive.</p>
    <div className="sport-tabs" role="tablist">{SPORTS.map(s => <button key={s} role="tab" aria-selected={s === sport} className={s === sport ? "on" : ""} onClick={() => {setSport(s); setKind("all"); setSel(null);}}>{s}</button>)}</div>
    <div className="intelligence-summary">
      <strong>{sm.families} families · {sm.series} series</strong><span>{sm.families_observed_now} observed in latest snapshot · {master.families.filter(f => f.sport === sport && f.observed.state === "OBSERVED_PRIOR_SNAPSHOT_ONLY").length} only in an older snapshot · {master.families.filter(f => f.sport === sport && f.observed.state === "DEFINED_NOT_OBSERVED").length} defined, not observed</span>
      <span>{g.inputs} candidate inputs ({g.curated_inputs} with curated evidence)</span><span>unclassified: {sm.unclassified_families.length ? sm.unclassified_families.join(", ") : "none"}</span>
    </div>
    <div className="status-row">{Object.entries(g.verification_counts).sort((a, b) => b[1] - a[1]).map(([k, v]) => <span key={k} className={"badge b-" + (COLL[k] || "unk")}>{VNAME[k] || nice(k)}: {v}</span>)}</div>
    <h3>Top collection gaps — {sport}</h3>
    <div className="gap-list">{g.top_gaps.slice(0, 6).map(r => <div className="gap" key={r.input}><strong>{r.label}</strong> <Badge v={r.verification_class || r.collection} raw={r.collection}/> <span className="badge b-use">model: {nice(r.model_use)}</span>
      <span className="fine"> essential for {r.essential_for_families} families · {(r.share_of_sport_markets * 100).toFixed(0)}% of this sport's observed markets</span><p className="fine">{r.note}</p></div>)}</div>
    <h3>Market families</h3>
    <div className="intelligence-filters"><label>Kind<select value={kind} onChange={e => {setKind(e.target.value); setSel(null);}}><option value="all">all kinds</option>{kinds.map(k => <option key={k}>{k}</option>)}</select></label>
      <label>Family<select value={fam?.id || ""} onChange={e => setSel(e.target.value)}>{fams.map(f => <option key={f.id} value={f.id}>{f.native_family} — {n(f.observed.markets_now ?? f.markets_prior_snapshot)} mkts · {nice(f.observed.state)}</option>)}</select></label></div>
    {fam && <FamilyDetail fam={fam} sport={sport}/>}
    <h3>Source investigations (generated)</h3>
    <ul className="fine">
      <li><b>NBA PROT series</b>: {Object.keys(nbaProt.pairs).length} stat families; settlement equivalent to base: {Object.values(nbaProt.pairs).every(p => p.settlement_equivalent) ? "yes" : "NO"} (differs in {[...new Set(Object.values(nbaProt.pairs).flatMap(p => p.settlement_fields_differing))].join(", ")}). Kept as separate identifiers.</li>
      <li><b>Tennis results</b> ({tennisIv.status.toLowerCase().replaceAll("_", " ")}): primary frozen since ATP {tennisIv.tours.atp.unavailable_from_primary.from}, WTA {tennisIv.tours.wta.unavailable_from_primary.from}; candidate covers to {tennisIv.tours.atp.candidate_last_match} but thin months {tennisIv.tours.wta.candidate_thin_months_inside_gap.join(", ")}.</li>
      <li><b>Soccer ambiguous series</b>: {soccerAmb.total} → {Object.entries(soccerAmb.counts).map(([k, v]) => v + " " + nice(k)).join(", ")} (ticker evidence only).</li>
      <li><b>Series sweep ({sweepSum.swept_utc})</b>: MLB {sweepSum.mlb.complete}/{sweepSum.mlb.series} series complete in {sweepSum.mlb.requests} requests ({sweepSum.mlb.series_with_markets} with markets, {sweepSum.mlb.empty_series} empty, {sweepSum.mlb.families} families, {sweepSum.mlb.markets.settled.toLocaleString()} settled markets, {sweepSum.mlb.title_mismatch.length} title mismatches); soccer ambiguous {sweepSum.soccer.complete}/{sweepSum.soccer.series} complete: {Object.entries(sweepSum.soccer.classes).map(([k, v]) => v + " " + nice(k)).join(", ")}. Errors: {sweepSum.mlb.errors + sweepSum.soccer.errors}.</li>
      <li><b>Archive gaps (days with no snapshot)</b>: {Object.entries(gapsArch.sports).filter(([k, v]) => v.missing_calendar_days && v.missing_calendar_days.length).map(([k, v]) => k + " " + v.missing_calendar_days.length).join(" · ")}; NFL history is sampled, not exhaustive.</li>
      <li><b>Soccer context</b>: lineups {(soccerCtx.lineups.share_pre_kickoff * 100).toFixed(0)}% of {soccerCtx.lineups.fixtures.toLocaleString()} fixtures with a pre-kickoff XI; weather {(soccerCtx.weather.share_rows_after_kickoff * 100).toFixed(1)}% of snapshots captured after kickoff; injuries and xG: no archive; ESPN carries no xG.</li>
      <li><b>Soccer box-score fields (ESPN probe, run {soccerEv.espn_probe.workflow_run.split(" ").pop()})</b>: shots, shots on target, corners and cards are present for both teams in {soccerEv.espn_probe.soccer_boxscore.matches}/{soccerEv.espn_probe.soccer_boxscore.matches} probed matches; no xG statistic exists in the box score. Archive today: {soccerEv.soccer_archive.results.records.toLocaleString()} result records, 0 with shots/corners/cards/xG (fix is in draft soccer-edge-finder PR #39, not merged). Scoreboard cards differed from the box score in {soccerEv.espn_probe.cards_scoreboard_vs_boxscore.scoreboard_higher_by_1}/{soccerEv.espn_probe.cards_scoreboard_vs_boxscore.matches} matches, so they are marked unreconciled.</li>
      <li><b>NBA pregame starters (ESPN core roster)</b>: summary endpoint carries {soccerEv.espn_probe.nba_pregame_starters.endpoint_summary.starter_flags_in_summary} starter flags pre-tip; core roster showed 5 starters per team at {soccerEv.espn_probe.nba_pregame_starters.coverage_by_minutes_to_tip[0].minutes_to_tip} min before tip and 0 at {soccerEv.espn_probe.nba_pregame_starters.coverage_by_minutes_to_tip[1].minutes_to_tip} min (n=3 games probed; collector integration pending).</li>
      <li><b>Market-record fields by sport (newest archived capture)</b>: NFL {mktExtra.NFL.quotes.records.toLocaleString()} quotes — volume {(mktExtra.NFL.quotes.nonzero_share.volume_fp * 100).toFixed(0)}% / open interest {(mktExtra.NFL.quotes.nonzero_share.open_interest_fp * 100).toFixed(0)}% non-zero, {mktExtra.NFL.books.records} order books · Tennis {mktExtra.TENNIS.quotes.records} quotes — volume {(mktExtra.TENNIS.quotes.nonzero_share.volume_fp * 100).toFixed(0)}% non-zero, {mktExtra.TENNIS.books.records} order books · CFB capture has status/kickoff only (no volume, open interest or book) · MLB markets file is a contract registry with no price/volume/open-interest fields, and its files after 2026-10-28 are empty.</li>
      <li><b>Soccer weather PIT guard</b>: {wxPit.quarantined.toLocaleString()} of {wxPit.rows.toLocaleString()} snapshots excluded from pregame use (captured after kickoff); {wxPit.events_without_usable_snapshot} of {wxPit.events} events have no usable snapshot; raw archive untouched.</li>
      <li><b>Record vs batch time</b>: {rvb.findings.filter(f => f.record_obs_later_than_batch_stamp > 0 && f.record_minus_batch_seconds_max > 1).map(f => f.sport + " " + f.dir + " up to " + Math.round(f.record_minus_batch_seconds_max) + " s").join("; ")} — record time is later than the batch stamp (use record-level time).</li>
      <li><b>Tennis results options</b>: {tennisOpt.options.length} sources assessed, none ingested; {tennisOpt.options.filter(o => o.status === "PARTIAL_CANDIDATE").length} partial candidate (licence-restricted).</li>
      <li><b>Timestamp integrity</b>: {Object.entries(tsInt.sports).map(([k, v]) => k + " " + v.updated_after_stamp + " rows updated after batch stamp (max " + Math.round(v.max_lag_seconds) + " s)").join(" · ")}.</li>
    </ul>
    <h3>Cross-sport gap ranking (within-sport shares)</h3>
    <ol className="fine">{gaps.cross_sport.slice(0, 8).map((r, i) => <li key={i}><b>{r.sport}</b> {r.input} — {nice(r.collection)}, model {nice(r.model_use)}, {(r.share_of_sport_markets * 100).toFixed(0)}% of its markets</li>)}</ol>
    <div className="intelligence-related"><strong>Related source-linked research</strong>{relevant.length ? relevant.map(x => <p key={x.id}>{x.title} · {x.status} {x.sources[0]?.url && <a href={x.sources[0].url} target="_blank" rel="noreferrer">Source ↗</a>}</p>) : <p>No verified sport-specific research records are linked yet.</p>}</div>
    <p className="fine-print">Sources: {sc.repo}@{sc.commit.slice(0, 7)} · {sc.archives.length} archive branches scanned. Static code references are not proof of correct collection or use. Predictive value: untested. No completeness percentage is inferred.</p>
  </section>;
}
