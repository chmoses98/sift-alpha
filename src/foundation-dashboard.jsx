import React, {useMemo, useState} from "react";
import {STUDIES} from "./studies.mjs";
import master from "../research/audit/master_inventory.json";
import registry from "../research/audit/input_registry.json";
import status from "../research/audit/collection_status.json";
import gaps from "../research/audit/collection_gap_report.json";
import specs from "../research/audit/market_specs.json";
import modelVal from "../research/audit/model_validation.json";
import readiness from "../research/audit/essential_readiness.json";
import {MarketIntel, intelFor} from "./market-intel.jsx";
const VAL_MAP = {"NBA/player_points": "points", "NBA/player_rebounds": "rebounds", "NBA/player_assists": "assists", "NBA/player_threes": "threes", "NBA/player_pra": "pra", "NBA/team_total": "team_points", "NHL/player_shots": "shots", "NHL/player_goals": "goals", "NHL/player_assists": "assists", "NHL/player_points": "points", "NHL/goalie_saves": "saves", "NHL/team_total": "team_goals"};
import tennisIv from "../research/audit/sources/tennis_results_intervals.json";
import soccerAmb from "../research/audit/resolutions/soccer_ambiguous.json";
import soccerCtx from "../research/audit/lineage/soccer_context_lineage.json";
import soccerEv from "../research/audit/lineage/soccer_archive_and_espn_probe_evidence.json";
import soccerLive from "../research/audit/lineage/soccer_pr39_live_probe.json";
import valueEvidence from "../research/audit/lineage/source_value_probe_summary.json";
import mlbHitterEras from "../research/audit/lineage/mlb_hitter_evaluation_eras.json";
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
  const sp = specs.families[fam.id];
  const er = readiness.families[fam.id];
  // market-specific drivers (when specified) replace the kind-level blueprint; both are hypotheses
  Object.entries(sp?.drivers || fr?.inputs || {}).forEach(([id, t]) => groups[t].push(id));
  const audit = FAMILY_AUDITS.find(a => a.sport === sport && a.market_family === fam.native_family);
  return <div className="fam-detail">
    <p><strong>{fam.native_family}</strong> · {fam.canonical.kind.replaceAll("_", " ")} · {fam.canonical.scope} · periods {fam.canonical.periods.join(", ")}</p>
    <p className="fine">Observed: <b>{nice(fam.observed.state)}</b> — {n(fam.observed.markets_now)} markets now ({fam.observed.basis}; as of {fam.observed.as_of || "unknown"}){fam.markets_prior_snapshot != null && <> · prior snapshot {n(fam.markets_prior_snapshot)} ({fam.prior_snapshot_date})</>}. Series: {fam.series_count}{fam.series_sample.length ? " e.g. " + fam.series_sample.join(", ") : ""}.</p>
    <p className="fine">Settlement: {fam.settlement?.text || "unknown"} <em>({fam.settlement?.status || "UNKNOWN"}{fam.settlement?.source ? " · " + fam.settlement.source : ""})</em></p>
    {fam.historical && <p className="fine">Historical coverage: {fam.historical.state === "OBSERVED" ? <>first seen {fam.historical.first_seen}, last {fam.historical.last_seen}; present on {fam.historical.days_present} of {fam.historical.snapshot_days} archived days ({fam.historical.calendar_days_without_snapshot} calendar days in the span have no snapshot); peak {n(fam.historical.markets_peak)} markets/day. Basis: {fam.historical.basis}.</> : <b>{nice(fam.historical.state)}</b>}</p>}
    {sp && <div className="spec">
      <h4>Market-specific blueprint <span className={"badge b-" + (sp.status === "SPECIFIED" ? "ok" : sp.status === "SPECIFIED_UNOBSERVED" || sp.status === "SPECIFIED_BY_SERIES_SPLIT" || sp.status === "MISMAPPED_REROUTED" ? "warn" : "bad")}>{nice(sp.status)}</span></h4>
      {sp.specs.length > 0 ? <>
        {sp.specs.map(k => { const c = specs.classes[k]; return <div key={k} className="inp"><strong>{nice(k)}</strong>
          <p className="fine"><b>Outcome:</b> {c.outcome}</p><p className="fine"><b>Distribution:</b> {c.distribution}</p><p className="fine"><b>Key numbers:</b> {c.key_numbers}</p>
          <p className="fine"><b>Verify in rules text:</b> {c.settle}</p><p className="fine"><b>Point-in-time hazard:</b> {c.pit}</p><p className="fine"><b>History needed:</b> {c.history}</p></div>; })}
        <p className="fine"><b>Legacy blueprint tally (not strict verification):</b> {sp.essential_verified}/{sp.essential_total} verified or derived · {Object.entries(sp.essential_by_status).map(([k, v]) => v + " " + (VNAME[k] || nice(k))).join(", ")}
          {sp.essential_missing.length > 0 && <> · <b>not yet usable:</b> {sp.essential_missing.join(", ")}</>}</p></> : <p className="fine">{sp.reason}</p>}
    </div>}
    {er && <div className="spec" aria-label={`Essential input readiness for ${fam.native_family}`}>
      <h4>Essential input evidence · {er.verified}/{er.required} verified</h4>
      <p className="fine"><b>Strict verified collection only.</b> {er.collected - er.verified} collected but not fully verified · {er.derived} derived (separate; never automatically verified) · {er.required - er.verified} not verified.</p>
      <div className="inp-grid">{Object.entries(er.dims).map(([dim, d]) => <div className="inp" key={dim}>
        <strong>{nice(dim)}</strong>
        <p className="fine">{d.verified}/{d.required} verified · {d.collected} collected · {d.derived} derived</p>
      </div>)}</div>
      <p className="fine"><b>Model consumption:</b> {er.model_used}/{er.required} essential links marked used or partially used. <b>Predictive validation:</b> {nice(er.predictive_validation)} (independent evidence required). No collection or prediction authority is inferred from input names or source availability.</p>
      {er.gaps.length > 0 && <details><summary>Inspect {er.gaps.length} unverified essential inputs</summary>
        <ul className="fine">{er.gaps.map(g => <li key={g.input}><b>{g.input}</b> — {VNAME[g.class] || nice(g.class)} · {nice(g.dimension)}</li>)}</ul>
      </details>}
    </div>}
    {intelFor(sport, fam.native_family) && <MarketIntel intel={intelFor(sport, fam.native_family)} />}
    {VAL_MAP[fam.id] && modelVal.sports[sport]?.families[VAL_MAP[fam.id]] && (() => { const v = modelVal.sports[sport].families[VAL_MAP[fam.id]]; return <p className="fine"><b>Model validation (repo-reported, not reproduced by Alpha):</b> {v.model} · {v.readiness} — {v.reported}</p>; })()}
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
  const sr = readiness.sports[sport];
  const essentialPriority = Object.values(readiness.families).filter(r => r.sport === sport && r.required > r.verified)
    .sort((a, b) => ((b.markets_now || 0) * (b.required - b.verified) / b.required) - ((a.markets_now || 0) * (a.required - a.verified) / a.required)).slice(0, 6);
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
    <div className="intelligence-summary" aria-label="Strict essential input readiness">
      <strong>Essential links: {sr.ALL.verified}/{sr.ALL.required} verified</strong>
      <span>Family-by-input evidence links, not distinct fields or predictive performance · {sr.ALL.collected} collected · {sr.ALL.derived} derived</span>
      <span>{sr.FAMILIES.fully_verified}/{sr.FAMILIES.n_with_essentials} families fully verified · {n(sr.FAMILIES.markets_in_fully_verified)} observed markets in those families</span>
      <span>Model-use links: {sr.ALL.model_used}/{sr.ALL.required} · predictive validation is independent and not asserted by readiness</span>
    </div>
    <h3>Largest essential readiness gaps — {sport}</h3>
    <ol className="fine">{essentialPriority.map(r => <li key={r.sport + "/" + r.family}>
      <strong>{r.family}</strong> · {n(r.markets_now)} observed markets · {r.verified}/{r.required} essential links verified · {r.required - r.verified} not verified
    </li>)}</ol>
    <p className="fine">Ranking = current observed market count × share of essential links not strictly verified. It prioritizes research workload, not expected profitability. Drill into a family below for source categories and exact missing inputs.</p>
    <div className="status-row">{Object.entries(g.verification_counts).sort((a, b) => b[1] - a[1]).map(([k, v]) => <span key={k} className={"badge b-" + (COLL[k] || "unk")}>{VNAME[k] || nice(k)}: {v}</span>)}</div>
    <p className="fine">Market-specific blueprints ({sport}): {Object.entries(specs.summary[sport]).filter(([k]) => !["classes","families"].includes(k)).map(([k, v]) => v + " " + nice(k)).join(" · ")} of {specs.summary[sport].families} families, {specs.summary[sport].classes.length} market classes. A blueprint is a requirement list, not evidence of collection or predictive value.</p>
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
      <li><b>Soccer results collector live probe (run {soccerLive.run}; collector merged in PR #39)</b>: {soccerLive.verified.rows_with_exact_box_stats}/{soccerLive.verified.result_rows} finished matches in a five-day sample have exact box-score shots, shots on target, corners and yellow/red cards for both teams; {soccerLive.gaps.no_box_stats_rows} lacked box stats in that probe because they were older than its 100-hour finished-match selection cutoff; fresh ESPN summaries now provide all five bilateral stats for each. xG: {soccerLive.verified.xg_populated}/{soccerLive.verified.result_rows}. Replay appended {soccerLive.verified.idempotency.run2_results_appended} result rows and changed {soccerLive.verified.idempotency.box_stats_captured_at_changed_between_runs} timestamps; {soccerLive.gaps.unmapped.events_skipped_unmapped} additional matches skipped because of unmapped identities. This is a read-only probe, <b>not production archival</b> or proof of a complete season. The merged collector selects finished matches up to 30 hours after kickoff; opt-in historical backfill wiring is tracked in PR #42. Production archive coverage remains unverified.</li>
      <li><b>Populated value-level ESPN probe (run {valueEvidence.workflow_run})</b>: {valueEvidence.soccer.now_retrievable_with_bilateral_shots_sot_corners_cards}/{valueEvidence.soccer.original_missing} previously missing soccer box scores are available with bilateral values. They kicked off 101.6–125.9 hours before the original 100-hour snapshot cutoff, explaining the probe omission; the collector repair is merged in Soccer PR #39, but the opt-in workflow is pending PR #42 and production publication remains unverified. Tennis: 0 populated competitor-statistics blocks across {valueEvidence.tennis.atp_completed + valueEvidence.tennis.wta_completed} completed ATP/WTA matches, despite {valueEvidence.tennis.atp_linescores + valueEvidence.tennis.wta_linescores} sets of available match linescores. MLB StatsAPI has four sampled years of hitter/pitcher boxes and the NHL web API yielded populated shot coordinates/TOI; none of this proves continuous archived collection or predictive validation. Raw proof: <code>value-probe-data</code> @ {valueEvidence.raw_commit.slice(0, 7)}; input classes remain <b>source available, not collected</b>.</li>
      <li><b>Soccer box-score fields (ESPN probe, run {soccerEv.espn_probe.workflow_run.split(" ").pop()})</b>: shots, shots on target, corners and cards are present for both teams in {soccerEv.espn_probe.soccer_boxscore.matches}/{soccerEv.espn_probe.soccer_boxscore.matches} probed matches; no xG statistic exists in the box score. Archive at pinned probe: {soccerEv.soccer_archive.results.records.toLocaleString()} result records, 0 with shots/corners/cards/xG (the collector fix is now merged in Soccer PR #39; live production backfill is still unverified). Scoreboard cards differed from the box score in {soccerEv.espn_probe.cards_scoreboard_vs_boxscore.scoreboard_higher_by_1}/{soccerEv.espn_probe.cards_scoreboard_vs_boxscore.matches} matches, so they are marked unreconciled.</li>
      <li><b>MLB hitter model-evaluation eras (not interchangeable)</b>: original pinned Aug 1–20 historical <code>hitter_hits</code> opportunity corpus has {mlbHitterEras.original_hitter_hits_opportunity_corpus.joined_temporally_valid_model_evaluations.toLocaleString()}/{mlbHitterEras.original_hitter_hits_opportunity_corpus.observed_opportunity_rows.toLocaleString()} joined point-in-time model evaluations; a <em>separate</em> Aug 19–Sep 23 research calibration reports {mlbHitterEras.later_hitter_calibration_study.all_families_unique_ticker_rows.toLocaleString()} graded one-per-ticker observations across four hitter families ({mlbHitterEras.later_hitter_calibration_study.hitter_hits_unique_ticker_rows.toLocaleString()} for hits). Later study model Brier {mlbHitterEras.later_hitter_calibration_study.all_families_model_brier} vs Kalshi mid {mlbHitterEras.later_hitter_calibration_study.all_families_market_mid_brier}: parity, no validated advantage. The later counts are reported by the pinned MLB study, <b>not independently replayed in Alpha</b>, and must never fill the earlier 0/23,295 denominator or imply deployable trading authority.</li>
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
