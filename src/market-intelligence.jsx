import React, {useState} from "react";
import {STUDIES} from "./studies.mjs";

// Machine-readable audit artifacts (research/audit). Anything not present here stays NOT AUDITED/unknown.
const AUDITS = Object.values(import.meta.glob("../research/audit/audits/*.json", {eager: true, import: "default"}));
const INVENTORIES = Object.values(import.meta.glob("../research/audit/*_market_inventory.json", {eager: true, import: "default"}));
const LABEL = {USED_CORRECTLY:"used", USED_DEFECT_REPAIRED:"defect repaired", USED_DEFECTIVE:"DEFECTIVE", COLLECTED_UNUSED:"collected, unused", NOT_MODELED:"not modeled", UNKNOWN:"unknown", NOT_APPLICABLE:"n/a"};
function AuditPanel({sport}){
 const inv=INVENTORIES.find(i=>i.sport===sport);
 const audits=AUDITS.filter(a=>a.sport===sport);
 if(!inv&&!audits.length) return <div className="intelligence-evidence"><strong>No market inventory for {sport}</strong><p>Observed Kalshi market families: unknown. Nothing audited.</p></div>;
 return <div className="intelligence-evidence">
  {inv&&<><strong>{inv.families.length} observed {sport} market families · {inv.series_total} series</strong><p>{inv.note}. Verified {inv.last_verified_utc} · <a href={`https://github.com/${inv.source.repo}/blob/${inv.source.commit}/${inv.source.path}`} target="_blank" rel="noreferrer">source ↗</a></p>
  <p>{inv.families.slice(0,12).map(f=>`${f.family} (${f.snapshot_markets_seen})`).join(" · ")}{inv.families.length>12?" · …":""}</p></>}
  {audits.map(a=><div key={a.market_family}><strong>{a.market_family} audit · repair priority {a.repair_priority} · verified {a.last_verified_utc}</strong>
   <p>Settles on: {a.settles_on}</p>
   <ul>{a.inputs.map(i=><li key={i.input}><strong>{i.input}</strong> — collection: {i.collection.toLowerCase()} · model: {LABEL[i.model_use]} · validation: {i.validation.toLowerCase().replaceAll("_"," ")}{i.defect&&<em> · {i.defect}</em>}{i.evidence.map((e,k)=><a key={k} href={e.url} target="_blank" rel="noreferrer"> [{k+1}]</a>)}</li>)}</ul>
   <p>{a.repair_notes}</p></div>)}
 </div>;
}

const BLUEPRINTS = {
 CFB: {"1Q total":["Pace and projected possessions","Opponent-adjusted early-down efficiency","Opening-drive strategy","QB and lineup availability","Weather and venue","Kalshi quote and settlement history"],"1H spread":["Opponent-adjusted team strength","Expected first-half possessions","QB and line availability","Field position and special teams","Price and settlement"]},
 NFL: {"Team total":["Expected drives and pace","Opponent-adjusted scoring efficiency","QB, offensive line and injuries","Defensive matchup and coverage","Red-zone conversion","Market quote and fees"],"Receptions":["Routes and snap share","Targets per route","Defensive coverage","Projected pass volume","Injuries and game script","Quote history"]},
 NBA: {"Assists":["Projected minutes","Potential assists","Creation role and touches","Teammate shooting and injuries","Opponent defense","Possessions and market quotes"],"Rebounds":["Projected minutes","Rebound chances","Shot locations and misses","Lineup assignments","Opponent pace","Market prices"]},
 NHL: {"Shots on goal":["Expected ice time","Shot attempts and rates","Line combinations","Opponent shot suppression","Power-play role","Market prices"],"Game total":["Expected shot quality","Starting goaltender","Special teams","Rest and travel","Expected pace","Market history"]},
 MLB: {"Hitter hits":["Batting order and plate appearances","Pitch mix versus batter","Contact quality and handedness","Confirmed lineup","Park and weather","Original timestamped forecast","Kalshi quote and settlement"],"Pitcher strikeouts":["Pitch mix and whiff matchup","Confirmed opposing lineup","Expected batters faced","Pitch count and workload","Umpire and park context","Market quotes"]},
 CBB: {"Game total":["Opponent-adjusted pace","Shot quality","Turnovers and offensive rebounds","Current roster and minutes","Venue and travel","Market quotes"]},
 SOCCER: {"Match total":["Expected goals and shot quality","Lineups and injuries","Pressing and tactical pace","Rest and motivation","Goalkeeper","Market history"]},
 TENNIS: {"Match winner":["Surface-adjusted serve strength","Return and break probabilities","Matchup and style","Injury and fatigue","Match format","Market prices"]}
};
const STATUS = "NOT AUDITED";
const evidence = {
 "MLB|Hitter hits": {label:"Historical evaluation gap verified",detail:"Pinned Aug 1–20 research report: 0 model-evaluated rows among 23,295 observed hitter-hits market rows. This does not establish whether a separate forecast existed at the original quote.",url:"https://github.com/chmoses98/sift-alpha/blob/build/alpha-research-desk/alpha_engine/research_repair.py"}
};
export function MarketIntelligence(){
 const [sport,setSport]=useState("CFB");
 const [market,setMarket]=useState("1Q total");
 const markets=Object.keys(BLUEPRINTS[sport]);
 const selected=BLUEPRINTS[sport][market] || BLUEPRINTS[sport][markets[0]];
 const ev=evidence[sport+"|"+market];
 const relevant=STUDIES.filter(x=>x.sport===sport).slice(0,4);
 return <section className="intelligence" aria-label="Market intelligence input dashboard">
   <div className="eyebrow">MARKET INTELLIGENCE / SOURCE-TRUTH VIEW</div>
   <h2>What goes into each market?</h2>
   <p>These are <strong>candidate inputs to investigate</strong>, not verified model features. Unknown collection, model use, and predictive value are explicitly shown as unaudited.</p>
   <div className="intelligence-filters"><label>Sport<select value={sport} onChange={e=>{setSport(e.target.value);setMarket(Object.keys(BLUEPRINTS[e.target.value])[0]);}}>{Object.keys(BLUEPRINTS).map(x=><option key={x}>{x}</option>)}</select></label>
   <label>Market family<select value={selected===BLUEPRINTS[sport][market]?market:markets[0]} onChange={e=>setMarket(e.target.value)}>{markets.map(x=><option key={x}>{x}</option>)}</select></label></div>
   <div className="intelligence-summary"><strong>{selected.length} candidate input groups</strong><span>Verified model inputs: unknown</span><span>Research authority: none</span></div>
   <AuditPanel sport={sport}/>
 {ev&&<div className="intelligence-evidence"><strong>{ev.label}</strong><p>{ev.detail}</p><a href={ev.url} target="_blank" rel="noreferrer">Inspect pinned evidence ↗</a></div>}
   <div className="intelligence-grid">{selected.map((name,i)=><div className="intelligence-factor" key={name}>
     <div className="factor-heading"><span className="factor-number">{i+1}</span><strong>{name}</strong></div>
     <div className="factor-status"><span>Collected: {STATUS}</span><span>Quality: {STATUS}</span><span>Used by model: {STATUS}</span><span>Validated impact: {STATUS}</span></div>
   </div>)}</div>
   <div className="intelligence-related"><strong>Related source-linked research</strong>{relevant.length?relevant.map(x=><p key={x.id}>{x.title} · {x.status} {x.sources[0]?.url&&<a href={x.sources[0].url} target="_blank" rel="noreferrer">Source ↗</a>}</p>):<p>No verified sport-specific research records are linked yet.</p>}</div>
   <p className="fine-print">This dashboard currently displays curated candidate blueprints and existing source-linked research. It does not yet read a continuously generated collection/usage audit. No green completeness percentages are inferred.</p>
 </section>;
}
