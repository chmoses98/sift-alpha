import React, {useEffect, useMemo, useRef, useState} from "react";
import "./market-input-map.css";

const ALL = "all";
const TABS = [
  ["markets","Markets"],["inputs","Inputs"],["datasets","Raw datasets"],["queue","Acquisition queue"]
];
const STATUSES = ["FULL","PARTIAL","PROXY","DATA_IN_HAND","REQUIRES_COLLECTION","BLOCKED","FAILED","UNVERIFIED","EXCLUDED"];
const TYPES = {
  PREDICTIVE:"Predictive",
  MARKET_DERIVED_BENCHMARK:"Market benchmark / price",
  RULES_SETTLEMENT_METADATA:"Rules / settlement metadata",
  SETTLEMENT_OPERATIONS:"Settlement operations",
  CALIBRATION_OPERATIONS:"Calibration / operations",
};
const PAGE = 35;
const count = (x) => Number(x || 0).toLocaleString();
const caps = (x) => String(x ?? "unknown").replaceAll("_"," ").toLowerCase();
const base = (import.meta.env.BASE_URL || "/") + "market-input-map/";
const csvFiles = ["market-input-edges.csv","distinct-inputs.csv","dataset-input-edges.csv","acquisition-queue.csv"];
const safeLower = (x) => String(x ?? "").toLowerCase();

function Status({children}) {
  const state = String(children || "UNVERIFIED");
  return <span className={"mim-status mim-" + (["FULL","PARTIAL","PROXY","DATA_IN_HAND"].includes(state) ? "built" : ["BLOCKED","FAILED"].includes(state) ? "blocked" : "unknown")}>{state}</span>;
}
function ButtonLink({onClick,children}) { return <button className="mim-link" type="button" onClick={onClick}>{children}</button>; }
function ExportLinks() {
  return <div className="mim-exports" aria-label="Download generated CSV exports">
    {csvFiles.map((f)=> <a href={base+f} download key={f}>{f.replace(".csv","").replaceAll("-"," ")} <span aria-hidden="true">↓</span></a>)}
    <a href={base+"reconciliation.json"} download>Reconciliation ↓</a>
  </div>;
}
function Detail({view,item,graph,onNavigate}) {
  if (!item) return <p className="mim-empty">Select any row to inspect its dependencies and evidence.</p>;
  const inputs = new Map(graph.inputs.map((x)=>[x.key,x]));
  const markets = new Map(graph.markets.map((x)=>[x.id,x]));
  const datasets = new Map(graph.datasets.map((x)=>[x.id,x]));
  if(view==="markets") {
    const edges=graph.edges.filter(e=>e.market===item.id);
    return <div className="mim-detail" data-testid="market-input-detail">
      <div className="mim-detail-title"><div><small>{item.sport} · {item.archetype}</small><h4>{item.label}</h4></div><Status>{item.complete?"COMPLETE":"INCOMPLETE"}</Status></div>
      <p>{item.target || "No catalog target supplied"}</p>
      <p className="mim-fine">{item.mechanism || "Mechanism not specified."}</p>
      <strong>{count(item.primaryMissing)} missing of {count(item.primary)} predictive PRIMARY requirements</strong>
      <details><summary>Series assignments ({item.sources.reduce((n,s)=>n+s.count,0)})</summary>
        {(item.sources.length ? item.sources : [{kind:"No mapped series group",count:0,examples:[]}]).map((s,i)=>
          <p className="mim-fine" key={i}>{s.kind}: {count(s.count)} series · {s.examples.join("; ") || "No examples"}</p>)}
        <p className="mim-fine">Series-level grouping only. Contract counts and verification are not implied.</p>
      </details>
      <div className="mim-section-label">Every catalog input ({edges.length})</div>
      <div className="mim-table-scroll"><table><thead><tr><th>Input</th><th>Role</th><th>Category</th><th>Verified</th><th>Requirement</th></tr></thead>
        <tbody>{edges.map(e=><tr key={e.input}>
          <td><ButtonLink onClick={()=>onNavigate("inputs",e.input)}>{inputs.get(e.input)?.label || e.input}</ButtonLink><small className="mim-id">{e.input}</small></td>
          <td>{e.role}{e.primary?" · PRIMARY":""}</td><td>{TYPES[e.kind]||e.kind}</td>
          <td><Status>{e.verifiedStatus}</Status><small>{caps(e.marketCategory)}</small></td><td>{e.why || "Requirement text unmapped"}</td>
        </tr>)}</tbody></table></div>
    </div>;
  }
  if(view==="inputs"){
    const edges=graph.edges.filter(e=>e.input===item.key);
    return <div className="mim-detail" data-testid="distinct-input-detail">
      <div className="mim-detail-title"><div><small>{item.sport} · distinct input</small><h4>{item.label}</h4><code>{item.key}</code></div><Status>{item.status}</Status></div>
      <p><b>Point-in-time:</b> {item.pit} · <b>Pregame knowable:</b> {item.pregame} · <b>Cost:</b> {item.cost}</p>
      <p className="mim-fine"><b>Verified evidence:</b> {item.evidence || "No provenance statement in the mapped artifact"}. Verification status: {item.statusEvidence}.</p>
      <p><b>Catalog measurement:</b> {item.measurement || "Not specified"}</p>
      <p><b>Needs:</b> {item.needs.join(", ") || "Unknown"} · <b>Historical coverage:</b> {item.history.filter(Boolean).join("–") || "Unverified"}</p>
      <div className="mim-section-label">Candidate datasets ({item.datasetIds.length})</div>
      {item.datasetIds.length ? item.datasetIds.map(id=><div className="mim-cross" key={id}>
        <ButtonLink onClick={()=>onNavigate("datasets",id)}>{datasets.get(id)?.title||id}</ButtonLink>
        <small>{id}{datasets.has(id) ? "" : " · NOT MAPPED to dataset registry"}</small></div>) :
        <p className="mim-fine">No dataset ID in coverage_matrix.csv. Source mapping unresolved.</p>}
      <div className="mim-section-label">Affected markets ({edges.length} edges)</div>
      {edges.map(e=><div className="mim-cross" key={e.market}>
        <ButtonLink onClick={()=>onNavigate("markets",e.market)}>{markets.get(e.market)?.label||e.market}</ButtonLink>
        <small>{e.market} · {e.role} · {TYPES[e.kind]||e.kind}</small></div>)}
    </div>;
  }
  if(view==="datasets"){
    const q=graph.queue.find(x=>x.dataset===item.id);
    return <div className="mim-detail" data-testid="dataset-detail">
      <div className="mim-detail-title"><div><small>Raw dataset · candidate dependency</small><h4>{item.title}</h4><code>{item.id}</code></div></div>
      <p><b>Access:</b> {item.access} · <b>Evidence:</b> {item.evidence} · <b>Cost:</b> {item.cost}</p>
      <p><b>PIT:</b> {item.pit} · <b>Historical:</b> {item.history?.first || "?"} – {item.history?.last || "?"}</p>
      <p className="mim-fine">{item.missingness || "Historical completeness / raw schema not independently established."}</p>
      <p className="mim-fine"><b>Usable:</b> {item.provenanceReady?"Evidence of an acquired path; verify each field and use case":"NOT established. A free source or collected archive alone does not grant permissions."}</p>
      <div className="mim-section-label">Proposed raw sources · rights</div>
      {item.sourceLinks.map(s=><div className="mim-cross" key={s.id}>
        <b>{s.name}</b><small>{s.id} · {s.cost}</small>
        {s.proposedUrl ? <a href={s.proposedUrl} target="_blank" rel="noreferrer">Example probed source URL (not permission) ↗</a> : <small>Exact provider URL not recorded; do not infer one.</small>}
        <small>{s.rights.length?s.rights.map(r=>r.tier + (r.collection_allowed?" (conditional access)":" (collection not approved)")).join("; "):"Licence unresolved / no mapped authoritative rights record"}</small>
      </div>)}
      {q && <p><b>Potential missing PRIMARY slots:</b> {q.potentialPrimarySlots} (nonadditive); <ButtonLink onClick={()=>onNavigate("queue",q.dataset)}>View acquisition decision</ButtonLink></p>}
      <div className="mim-section-label">Dataset → field → input → markets ({item.fieldMappings.length} links)</div>
      {item.fieldMappings.map(e=> <div key={e.input} className="mim-cross">
        <ButtonLink onClick={()=>onNavigate("inputs",e.input)}>{inputs.get(e.input)?.label||e.input}</ButtonLink>
        <small>{e.input} · requires {e.needs.join(", ") || "unknown"}</small>
        <small><b>Fields:</b> {e.fields.length?e.fields.join(", "):"UNMAPPED — exact raw columns need verification"} · {e.fieldEvidence}</small>
        <small>Affects {inputs.get(e.input)?.markets.length||0} distinct archetypes (not additive)</small>
      </div>)}
    </div>;
  }
  return <div className="mim-detail" data-testid="queue-detail">
    <div className="mim-detail-title"><div><small>Acquisition queue · #{item.rank}</small><h4>{item.title}</h4><code>{item.dataset}</code></div></div>
    <p><b>{count(item.potentialPrimarySlots)}</b> potentially affected missing PRIMARY edges · {count(item.distinctInputs)} inputs · {count(item.distinctMarkets)} markets</p>
    <p><b>Feasibility:</b> {item.access} · {item.cost} · <b>PIT:</b> {item.pit}</p>
    <p><b>Rights:</b> {item.rights.join("; ") || "UNRESOLVED"}; research-cleared candidate path: {item.researchPath?"yes, conditions apply":"not demonstrated"}; commercial: {item.commercialPath?"candidate, conditions apply":"not demonstrated"}.</p>
    <p><b>Next action:</b> {item.next}</p>
    <p className="mim-fine">{item.caveat} Missing fields: {item.fieldMappingsTotal-item.fieldMappingsResolved}/{item.fieldMappingsTotal} mappings.</p>
    <ButtonLink onClick={()=>onNavigate("datasets",item.dataset)}>Inspect dataset, source rights and fields</ButtonLink>
    <div className="mim-section-label">Inputs relying on this dataset</div>
    {item.impactedInputs.map(key=><div key={key} className="mim-cross"><ButtonLink onClick={()=>onNavigate("inputs",key)}>{inputs.get(key)?.label||key}</ButtonLink>
      <small>{key} · {inputs.get(key)?.markets.length||0} associated markets (all roles)</small></div>)}
  </div>;
}

export function MarketInputMap() {
  const [open,setOpen] = useState(false);
  const [graph,setGraph] = useState(null);
  const [error,setError] = useState("");
  const [view,setView] = useState("markets");
  const [selected,setSelected] = useState(null);
  const [sport,setSport] = useState(ALL);
  const [query,setQuery] = useState("");
  const [marketQuery,setMarketQuery] = useState("");
  const [status,setStatus] = useState(ALL);
  const [primary,setPrimary] = useState(false);
  const [free,setFree] = useState(false);
  const [prospective,setProspective] = useState(false);
  const [commercial,setCommercial] = useState(false);
  const [limit,setLimit] = useState(PAGE);
  const [notice,setNotice] = useState("");
  const detailRef = useRef(null);
  useEffect(()=>{if(!selected)return;requestAnimationFrame(()=>detailRef.current?.scrollIntoView({behavior:"smooth",block:"start"}));},[selected]);
  useEffect(()=>{
    if(!open || graph) return;
    let active=true;
    fetch(base+"graph.json").then(r=>{if(!r.ok)throw new Error("Graph not generated; run npm run map:generate.");return r.json();})
      .then(g=>{if(active)setGraph(g);})
      .catch(e=>{if(active)setError(e.message);});
    return ()=>{active=false;};
  },[open,graph]);
  const marketIndex=useMemo(()=>new Map((graph?.markets||[]).map(m=>[m.id,m])),[graph]);
  const inputIndex=useMemo(()=>new Map((graph?.inputs||[]).map(i=>[i.key,i])),[graph]);
  const datasetIndex=useMemo(()=>new Map((graph?.datasets||[]).map(d=>[d.id,d])),[graph]);
  const queueIndex=useMemo(()=>new Map((graph?.queue||[]).map(q=>[q.dataset,q])),[graph]);
  const primaryInputs=useMemo(()=>new Set((graph?.edges||[]).filter(e=>e.primary).map(e=>e.input)),[graph]);
  const prospectiveInputs=useMemo(()=>new Set((graph?.inputs||[]).filter(i=>
    safeLower(i.pit).includes("unavailable")||safeLower(i.pit).includes("prospective")||
    (graph?.edges||[]).some(e=>e.input===i.key && e.marketCategory==="PROSPECTIVE")).map(i=>i.key)),[graph]);
  const freeDatasetIds=useMemo(()=>new Set((graph?.datasets||[]).filter(d=>safeLower(d.cost).includes("free")).map(d=>d.id)),[graph]);
  const commercialDatasetIds=useMemo(()=>new Set((graph?.queue||[]).filter(q=>q.commercialPath).map(q=>q.dataset)),[graph]);
  const candidates=useMemo(()=>{
    if(!graph)return [];
    const matchingInput=(i)=>{
      if(sport!==ALL&&i.sport!==sport)return false;
      if(status!==ALL&&i.status!==status)return false;
      if(primary&&!primaryInputs.has(i.key))return false;
      if(prospective&&!prospectiveInputs.has(i.key))return false;
      if(free&&!i.datasetIds.some(d=>freeDatasetIds.has(d)))return false;
      if(commercial&&!i.datasetIds.some(d=>commercialDatasetIds.has(d)))return false;
      if(query&&!safeLower([i.key,i.label,i.measurement,...i.needs].join(" ")).includes(safeLower(query)))return false;
      if(marketQuery&&!i.markets.some(m=>safeLower(marketIndex.get(m)?.label+" "+m).includes(safeLower(marketQuery))))return false;
      return true;
    };
    const visibleInputs=new Set(graph.inputs.filter(matchingInput).map(i=>i.key));
    if(view==="inputs")return graph.inputs.filter(i=>visibleInputs.has(i.key));
    if(view==="markets")return graph.markets.filter(m=>
      (sport===ALL||m.sport===sport)&&
      (!marketQuery||safeLower(m.label+" "+m.id).includes(safeLower(marketQuery)))&&
      (!query&&!primary&&!free&&!prospective&&!commercial&&status===ALL||
       graph.edges.some(e=>e.market===m.id&&visibleInputs.has(e.input)&&(!primary||e.primary))));
    if(view==="datasets")return graph.datasets.filter(d=>
      (!query||safeLower(d.title+" "+d.id+" "+d.sources.join(" ")).includes(safeLower(query))||d.inputs.some(k=>visibleInputs.has(k)))&&
      (!sport||sport===ALL||d.sports.includes(sport))&&
      (!marketQuery||d.inputs.some(k=>visibleInputs.has(k)))&&
      (!free||freeDatasetIds.has(d.id))&&(!commercial||commercialDatasetIds.has(d.id))&&
      (!primary||d.inputs.some(i=>primaryInputs.has(i)))&&(!prospective||d.inputs.some(i=>prospectiveInputs.has(i)))&&
      (status===ALL||d.inputs.some(i=>inputIndex.get(i)?.status===status)));
    return graph.queue.filter(q=>
      (!query||safeLower(q.title+" "+q.dataset).includes(safeLower(query))||q.impactedInputs.some(k=>visibleInputs.has(k)))&&
      (sport===ALL||q.impactedInputs.some(k=>inputIndex.get(k)?.sport===sport))&&
      (!marketQuery||q.impactedInputs.some(k=>visibleInputs.has(k)))&&
      (!free||q.cost==="free")&&(!commercial||q.commercialPath)&&
      (!prospective||q.impactedInputs.some(k=>prospectiveInputs.has(k)))&&
      (status===ALL||q.impactedInputs.some(k=>inputIndex.get(k)?.status===status)));
  },[graph,view,sport,query,marketQuery,status,primary,free,prospective,commercial,primaryInputs,prospectiveInputs,freeDatasetIds,commercialDatasetIds,marketIndex,inputIndex]);
  const selectedItem=selected&&selected.view===view?({markets:marketIndex,inputs:inputIndex,datasets:datasetIndex,queue:queueIndex}[view].get(selected.id)):null;
  function navigate(tab,id) {
    setView(tab);setSelected({view:tab,id});setSport(ALL);setQuery("");setMarketQuery("");setStatus(ALL);
    setPrimary(false);setFree(false);setProspective(false);setCommercial(false);setLimit(PAGE);
    setNotice("Showing "+tab+" dependency "+id);
  }
  const list=candidates.slice(0,limit);
  return <section className="mim" aria-label="Market and input map" id="market-input-map">
    <div className="mim-head">
      <div><div className="eyebrow">MARKET & INPUT MAP · SOURCE-LINKED / RESEARCH ONLY</div>
        <h2>What does each market need—and what data unlocks it?</h2>
        <p>One map over the approved catalog, verified inputs, raw dataset candidates and market assignments. No new source claims or predictions.</p>
      </div>
      <button type="button" className="mim-open" onClick={()=>setOpen(x=>!x)} aria-expanded={open}>{open?"Close map":"Explore dependencies →"}</button>
    </div>
    {open&&(!graph? <div className="mim-loading" role="status">{error||"Loading generated catalog map…"}</div>:
    <>
      <div className="mim-metrics">
        {[["Market archetypes",graph.summary.archetypes],["Distinct inputs",graph.summary.inputs],["Predictive slots",graph.summary.predictiveSlots],["Missing PRIMARY",graph.summary.primaryMissing]].map(([k,n])=>
          <div key={k}><strong>{count(n)}</strong><small>{k}</small></div>)}
      </div>
      <p className="mim-fine">Predictive slots are per-market requirements, not distinct inputs. Missing PRIMARY excludes the {count(graph.summary.primaryCovered)} built PRIMARY slots. Dataset impacts overlap and are never additive.</p>
      <div className="mim-tabs" role="tablist" aria-label="Dependency map views">{TABS.map(([v,label])=><button type="button" key={v} role="tab" aria-selected={view===v} onClick={()=>{
        setView(v);setSelected(null);setLimit(PAGE);}} className={view===v?"on":""}>{label}</button>)}</div>
      <div className="mim-filters">
        <label>Search {view}<input type="search" value={query} onChange={e=>{setQuery(e.target.value);setLimit(PAGE);}} placeholder="Name, identifier, requirement…" /></label>
        <label>Market <input type="search" value={marketQuery} onChange={e=>{setMarketQuery(e.target.value);setLimit(PAGE);}} placeholder="Archetype or market…" /></label>
        <label>Sport<select value={sport} onChange={e=>{setSport(e.target.value);setLimit(PAGE);}}><option value={ALL}>All eight</option>{["NBA","NHL","NFL","MLB","CFB","CBB","SOCCER","TENNIS"].map(s=><option key={s}>{s}</option>)}</select></label>
        <label>Verified status<select value={status} onChange={e=>{setStatus(e.target.value);setLimit(PAGE);}}><option value={ALL}>All statuses</option>{STATUSES.map(s=><option key={s}>{s}</option>)}</select></label>
        <div className="mim-switches"><label><input type="checkbox" checked={primary} onChange={e=>setPrimary(e.target.checked)}/> PRIMARY only</label>
          <label><input type="checkbox" checked={free} onChange={e=>setFree(e.target.checked)}/> Free candidates</label>
          <label><input type="checkbox" checked={prospective} onChange={e=>setProspective(e.target.checked)}/> Prospective needed</label>
          <label><input type="checkbox" checked={commercial} onChange={e=>setCommercial(e.target.checked)}/> Commercial-rights candidate</label></div>
        <button className="mim-clear" type="button" onClick={()=>{setSport(ALL);setQuery("");setMarketQuery("");setStatus(ALL);setPrimary(false);setFree(false);setProspective(false);setCommercial(false);}}>Clear filters</button>
      </div>
      {selectedItem&&<div ref={detailRef}><Detail view={view} item={selectedItem} graph={graph} onNavigate={navigate}/></div>}
      <div className="mim-list-header"><strong>{count(candidates.length)} {view==="queue"?"dataset acquisition options":view}</strong><span>Tap any row to explore</span></div>
      <div className="mim-results">
        {list.map(item=>{
          const id=view==="markets"?item.id:view==="inputs"?item.key:view==="datasets"?item.id:item.dataset;
          const name=item.label||item.title||id;
          const meta=view==="markets"?item.sport+" · "+item.primaryMissing+" missing PRIMARY / "+item.primary+" total":
            view==="inputs"?item.sport+" · "+item.markets.length+" markets · "+item.datasetIds.length+" dataset candidates":
            view==="datasets"?item.access+" · "+item.inputs.length+" inputs · "+item.markets.length+" markets":
            item.potentialPrimarySlots+" potential missing PRIMARY edges · "+item.distinctInputs+" inputs · "+item.access;
          return <button type="button" key={id} className={"mim-result"+(selected?.id===id&&selected?.view===view?" on":"")}
            onClick={()=>{setSelected({view,id});setNotice("");}} aria-expanded={selected?.id===id&&selected?.view===view}>
            <span><strong>{view==="queue"?"#"+item.rank+" · ":""}{name}</strong><small>{id}</small><small>{meta}</small></span>
            <span>{view==="inputs"?<Status>{item.status}</Status>:<span className="mim-caret">›</span>}</span>
          </button>;
        })}
        {!list.length&&<p className="mim-empty">No matches. Try clearing one or more filters; an unknown source is not treated as usable.</p>}
      </div>
      {candidates.length>limit&&<button type="button" className="mim-more" onClick={()=>setLimit(x=>x+PAGE)}>Show {Math.min(PAGE,candidates.length-limit)} more</button>}
      {notice&&<p className="mim-fine" role="status">{notice}</p>}
      <details className="mim-reconcile"><summary>Evidence, counts and unmapped records</summary>
        <p>Original classification: FULL {count(graph.summary.statuses.FULL)} · PARTIAL {count(graph.summary.statuses.PARTIAL)} · PROXY {count(graph.summary.statuses.PROXY)} · DATA_IN_HAND {count(graph.summary.statuses.DATA_IN_HAND)} · REQUIRES_COLLECTION {count(graph.summary.statuses.REQUIRES_COLLECTION)} · BLOCKED {count(graph.summary.statuses.BLOCKED)} · FAILED {count(graph.summary.statuses.FAILED)} · UNVERIFIED {count(graph.summary.statuses.UNVERIFIED)} · EXCLUDED {count(graph.summary.statuses.EXCLUDED)}.</p>
        <p>Rows: {count(graph.summary.marketEdges)} market-input edges, {count(graph.summary.datasetEdges)} dataset-input candidates; {count(graph.summary.datasets)} distinct datasets. Strict human validation is not claimed.</p>
        {Object.entries(graph.report).map(([key,arr])=><p key={key}><b>{key}:</b> {count(arr.length)} · examples: {arr.slice(0,4).map(x=>typeof x==="string"?x:JSON.stringify(x)).join(" / ")||"none"}</p>)}
        <p className="mim-fine">Unknown field names are explicit. Mapping candidate sources by name alone never establishes a licence. Series assignments are series-level and cannot be interpreted as contract counts.</p>
      </details>
      <ExportLinks/>
    </>)}
  </section>;
}
