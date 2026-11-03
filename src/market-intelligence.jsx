import React, {useEffect, useMemo, useState} from "react";
import {STUDIES} from "./studies.mjs";

const SPORTS = ["NFL","NBA","CFB","NHL","CBB","MLB","SOCCER","TENNIS"];
const UNKNOWN = "UNKNOWN";
const STATUS = new Set(["COLLECTED_VALID","COLLECTED_UNUSED","USED_VALID","STALE","MISSING","UNKNOWN","NOT_APPLICABLE"]);
const label = value => value == null ? UNKNOWN : String(value);
const formatCount = value => Number.isInteger(value) ? value.toLocaleString() : UNKNOWN;
const isPinned = row => /^chmoses98\/[A-Za-z0-9_-]+$/.test(row?.source_repository || "") &&
  /^[a-f0-9]{40}$/.test(row?.source_commit || "");
const sourceHref = row => isPinned(row) ? "https://github.com/" + row.source_repository + "/tree/" + row.source_commit : null;

function evidenceStatus(row) {
  if (STATUS.has(row?.market_collection_status)) return row.market_collection_status;
  // Source metadata or a retrospective evaluation report is not a complete
  // family-specific market collection. Only the exact archived CFB shard
  // supports a narrow, explicit collection statement.
  if (row?.observation_scope === "ONE_EVENT_SHARD_NOT_FULL_CFB_CATALOG" &&
      row?.exact_settlement_rule_status === "ARCHIVED_LITERAL_UNVERIFIED_SETTLEMENT")
    return "COLLECTED_VALID";
  return UNKNOWN;
}
function safeAudit(data) {
  if (!data || ![1,2].includes(data.schema_version) ||
      data.authority !== "RESEARCH_ONLY_NOT_LIVE_COLLECTION" ||
      !Array.isArray(data.family_rows) || !Array.isArray(data.missing_input_queue) ||
      data.live_capture_running !== false || data.all_market_families_certified !== false)
    throw new Error("Audit artifact missing required scientific safeguards");
  if (data.family_rows.length > 5000 ||
      data.family_rows.some(r => !SPORTS.includes(r.sport) || typeof r.family !== "string" ||
        (r.observed_denominator != null && (!Number.isInteger(r.observed_denominator) || r.observed_denominator < 0))))
    throw new Error("Audit artifact contains invalid market rows");
  return data;
}

export function MarketIntelligence(){
  const [audit,setAudit] = useState(null);
  const [error,setError] = useState("");
  const [sport,setSport] = useState("CFB");
  const [market,setMarket] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    const base = import.meta.env.BASE_URL || "/";
    fetch(base + "market-family-input-coverage.json", {signal:controller.signal, cache:"no-store"})
      .then(response => {if (!response.ok) throw new Error("No published verified audit artifact"); return response.json();})
      .then(data => setAudit(safeAudit(data)))
      .catch(err => {if (err.name !== "AbortError") setError(err.message);});
    return () => controller.abort();
  }, []);
  const rows = useMemo(() => audit?.family_rows.filter(r=>r.sport===sport) || [], [audit,sport]);
  const selected = rows.find(r=>r.family===market) || rows[0];
  const gaps = audit?.missing_input_queue.filter(g=>g.sport===sport && g.family===selected?.family) || [];
  const relevant = STUDIES.filter(x=>x.sport===sport).slice(0,3);
  const validSource = selected && isPinned(selected);
  const observedStatus = evidenceStatus(selected);
  const modelStatus = selected?.model_usage_status || UNKNOWN;
  const inputs = selected?.candidate_inputs || [];
  return <section className="intelligence" aria-label="Market intelligence input dashboard">
    <div className="eyebrow">MARKET INTELLIGENCE / PINNED SOURCE AUDIT</div>
    <h2>What do we actually know about each market?</h2>
    <p>Market collection, model use, source truth, and predictive value are separate claims. A literal exchange series is <strong>not</strong> a certified market family. Counts from different archive scopes must never be added together.</p>
    {!audit && !error && <p role="status">Loading source-backed market audit…</p>}
    {error && <div className="intelligence-evidence" role="alert"><strong>Audit data unavailable</strong><p>{error}. No family is certified from a missing artifact; the build must generate and publish the pinned-source audit before the dashboard can show verified evidence.</p></div>}
    {audit && <>
      <div className="intelligence-summary"><strong>{audit.family_rows.length} source-scoped audit rows</strong>
        <span>{audit.discovered_literal_series_count ?? 0} literal NBA/NHL series from verified tape prefix</span>
        <span>{audit.supported_sports.length} sports inventoried · live capture: NOT VERIFIED</span>
        {audit.cfb_event_shard_audit && <span>CFB: {audit.cfb_event_shard_audit.n_event_shards} verified event shards / {audit.cfb_event_shard_audit.n_distinct_market_tickers} literal tickers (one archived game directory only)</span>}
      </div>
      <div className="intelligence-filters"><label>Sport<select value={sport} onChange={e=>{setSport(e.target.value);setMarket("");}}>
        {SPORTS.map(x=><option key={x} value={x}>{x}</option>)}
      </select></label>
      <label>Observed market grouping<select value={selected?.family || ""} onChange={e=>setMarket(e.target.value)}>
        {rows.map((r,i)=><option key={r.family+"-"+i} value={r.family}>{r.family}</option>)}
      </select></label></div>
      {selected && <>
        <div className="intelligence-evidence">
          <strong>{selected.family} · {selected.observation_scope}</strong>
          <p><b>Market collection:</b> {observedStatus} (only within stated archive scope) · <b>Model usage:</b> {modelStatus}</p>
          <p><b>Observed denominator:</b> {formatCount(selected.observed_denominator)} {label(selected.denominator_unit)} · <b>Source-reported evaluations:</b> {formatCount(selected.source_reported_model_evaluated)} · <b>Independently valid evaluations:</b> {formatCount(selected.independently_valid_evaluations)}</p>
          <p><b>Source clock:</b> {label(selected.observed_at_utc)} · <b>Forecast availability:</b> {label(selected.historical_availability)} · <b>Pregame status:</b> {label(selected.point_in_time_pregame_eligibility)}</p>
          <p><b>Settlement rules:</b> {label(selected.exact_settlement_rule_status)} · <b>Outcome join:</b> {label(selected.settlement_outcome_join)} · <b>Projected outcome:</b> {label(selected.projected_outcome)}</p>
          {selected.rule_text_sample && <p><b>Archived sample rule:</b> {label(selected.rule_text_sample.primary)} (not independent exchange settlement verification)</p>}
          {selected.observed_contracts?.length>0 && <details><summary>All {selected.observed_contracts.length} archived literal contracts and rules</summary><div className="intelligence-contracts">{selected.observed_contracts.map(c=><div key={c.ticker}><code>{c.ticker}</code> · {label(c.period)} · {label(c.strike_type)} {label(c.floor_strike)} · primary SHA256 <code>{label(c.rules_primary_sha256)}</code>{(c.rules_primary || c.rules_secondary) ? <details><summary>Archived literal rule text (not verified settlement)</summary><p><b>Primary:</b> {label(c.rules_primary)}</p><p><b>Secondary:</b> {label(c.rules_secondary)}</p></details> : <span> · Literal rule text UNKNOWN</span>}</div>)}</div></details>}
          {selected.sample_contract && <p><b>Observed sample ticker:</b> {selected.sample_contract.ticker} · <b>Last ticker observation:</b> {label(selected.sample_contract.last_ticker_observed_at_utc)}</p>}
          {validSource && <a href={sourceHref(selected)} target="_blank" rel="noreferrer">Pinned source commit ↗</a>}
          {selected.source_code_paths?.length>0 && <p><b>Audited processing paths:</b> {selected.source_code_paths.join(", ")}</p>}
        </div>
        <h3>Candidate inputs and observed gaps</h3>
        {inputs.length ? <div className="intelligence-grid">{inputs.map((factor,i)=><div className="intelligence-factor" key={factor.name+"-"+i}>
          <div className="factor-heading"><span className="factor-number">{i+1}</span><strong>{factor.name}</strong></div>
          <div className="factor-status"><span>Hypothesis: {label(factor.evidence)}</span><span>Model used: {label(factor.model_used)}</span><span>Historical source: {label(factor.historical_source)}</span><span>Validated impact: {UNKNOWN}</span></div>
        </div>)}</div> : <p>Candidate-input lineage is {UNKNOWN} for this observed grouping. No speculative features are labeled as collected or useful.</p>}
        {gaps.length>0 && <p><strong>Unresolved research gaps:</strong> {gaps.flatMap(g=>g.missing || []).join(" · ")}</p>}
      </>}
      <div className="intelligence-related"><strong>Related source-linked research</strong>{relevant.length?relevant.map(x=><p key={x.id}>{x.title} · {x.status} {x.sources[0]?.url&&<a href={x.sources[0].url} target="_blank" rel="noreferrer">Source ↗</a>}</p>):<p>No independently verified sport-specific studies linked yet.</p>}</div>
      <p className="fine-print">Artifact is a pinned historical research snapshot, generated in CI before build; it is NOT live Kalshi polling. Literal-series rows cover only an NBA/NHL checkpoint plus three deltas. No independent game start, calibrated model, complete market coverage, settlement, trade, or profitability is certified.</p>
    </>}
  </section>;
}

export {safeAudit, evidenceStatus};
