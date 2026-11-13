/* Deterministic, read-only derivative of the approved SIFT Alpha catalogs.
 * No network access, credentials, raw-data collection, model training or catalog writes.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BASE = "research/input_research/";
const DATA = BASE + "data_foundation/";
const SPORTS = ["NBA", "NHL", "CBB", "SOCCER", "NFL", "TENNIS", "CFB", "MLB"];
const OUTPUT = "public/market-input-map";
const readJSON = (file) => JSON.parse(fs.readFileSync(path.join(ROOT, file), "utf8"));
const unq = (list) => [...new Set(list.filter(Boolean))].sort();
const value = (x) => (x == null ? "" : String(x));
const csv = (rows, fields) => [fields.join(","), ...rows.map((r) => fields.map((f) => {
  const s = value(r[f]);
  return /[,"\r\n]/.test(s) ? '"' + s.replaceAll('"', '""') + '"' : s;
}).join(","))].join("\n") + "\n";

export function parseCSV(content) {
  const rows = []; let cells = [], part = "", quoted = false;
  for (let i = 0; i < content.length; i++) {
    const c = content[i];
    if (c === '"' && quoted && content[i + 1] === '"') { part += '"'; i++; }
    else if (c === '"') quoted = !quoted;
    else if (c === "," && !quoted) { cells.push(part); part = ""; }
    else if ((c === "\n" || c === "\r") && !quoted) {
      if (c === "\r" && content[i + 1] === "\n") i++;
      cells.push(part); part = "";
      if (cells.some((x) => x !== "")) rows.push(cells);
      cells = [];
    } else part += c;
  }
  if (part || cells.length) { cells.push(part); rows.push(cells); }
  const [fields, ...body] = rows;
  if (!fields) return [];
  return body.map((cells) => Object.fromEntries(fields.map((f, i) => [f, cells[i] ?? ""])));
}

export function classifyEdge(id, category, row, definition) {
  if (category === "EXCLUDED_MARKET" || definition?.category === "market_structure") return "MARKET_DERIVED_BENCHMARK";
  if ((row.settlement_ops_ids || []).includes(id) || id === "m.settlement_truth") return "SETTLEMENT_OPERATIONS";
  if ((row.calibration_ids || []).includes(id) || id === "m.strike_hit_rates") return "CALIBRATION_OPERATIONS";
  if ((row.semantic_ids || []).includes(id) || id === "m.rules_text" || id.startsWith("xx.rules_")) return "RULES_SETTLEMENT_METADATA";
  return "PREDICTIVE";
}

export function auditFields(audit, key, datasetId) {
  const rows = Array.isArray(audit?.rows) ? audit.rows : (Array.isArray(audit?.inputs) ? audit.inputs : []);
  const index = Array.isArray(rows) ? rows.find((r) => r.key === key || (r.sport + ":" + r.id) === key) :
    (audit?.inputs?.[key] || audit?.rows?.[key]);
  const src = index || (!Array.isArray(audit?.inputs) ? audit?.inputs?.[key] : null);
  if (!src) return [];
  const fields = [];
  const harvest = (obj) => {
    if (!obj || typeof obj !== "object") return;
    for (const k of ["fields", "required_fields", "columns", "column_names", "raw_fields"]) {
      const a = obj[k];
      if (Array.isArray(a)) for (const f of a) if (typeof f === "string" && f.length < 100) fields.push(f);
    }
  };
  for (const row of [src, ...(Array.isArray(src.requirements) ? src.requirements : [])]) {
    if (!row) continue;
    const ds = row.dataset || row.dataset_id || row.satisfied_by;
    if (!ds || ds === datasetId) harvest(row);
  }
  return unq(fields);
}

function rightsFor(sourceId, registry) {
  const matches = (registry.sources || []).filter((r) =>
    r.id === sourceId || (r.tokens || []).some((t) => t === sourceId));
  return matches.map((r) => ({id:r.id, tier:r.tier, collection_allowed:r.collection_allowed === true,
    research_cleared:r.research_cleared === true, commercial_cleared:r.commercial_cleared === true,
    evidence:r.evidence || ""}));
}
function isMissing(status) {
  return !["FULL", "PARTIAL", "PROXY"].includes(status);
}
const preference = (x) => {
  // Stable categorical ordering, not an invented impact/profitability score.
  if (x.cost !== "free") return 4;
  if (x.provenanceReady && x.pit !== "PIT_UNAVAILABLE_HISTORICALLY") return 0;
  if (x.access === "COLLECTED_ARCHIVE" || x.access === "FREE_REACHABLE") return 1;
  if (x.access?.includes("BLOCKED") || x.access?.includes("UNCONFIRMED")) return 3;
  return 2;
};

export function buildMap({ catalog, completeness, coverage, coverageRows, datasets, sources, rights, audit = {},
    seriesAssignments = {}, seriesReconciliation = {}, baselineLock = null }) {
  const reports = {
    unmappedMarketArchetypes: [], unmappedMarketInputs: [], unmappedCoverageInputs: [],
    unmatchedDatasetIds: [], unmappedFields: [], unknownSeriesAssignments: [],
    primaryRoleReconciliation: [], inputStatusReconciliation: [],
  };
  const marketRows = completeness.rows || [];
  const verifiedRows = coverage.rows || [];
  const cov = new Map(coverageRows.map((r) => [r.sport + ":" + r.input_id, r]));
  const inputByKey = new Map();
  const defs = {};
  for (const sport of SPORTS) defs[sport] = catalog[sport]?.inputs || {};
  for (const rec of verifiedRows) {
    const key = rec.key || rec.sport + ":" + rec.id;
    const def = defs[rec.sport]?.[rec.id] || {};
    const cm = cov.get(key) || {};
    inputByKey.set(key, {
      key, id:rec.id, sport:rec.sport, label:def.label || rec.id, status:rec.verified_bucket || "UNVERIFIED",
      statusEvidence:rec.verified_status || "UNKNOWN", pit:rec.pit_verdict || cm.pit_verdict || "UNKNOWN",
      history: [cm.history_first || null, cm.history_last || null], cost:cm.cost || "unknown",
      pregame:def.pregame_knowable || cm.pregame_knowable || "unknown",
      category:def.category || "unknown", measurement:def.measurement || "",
      evidence:rec.evidence?.replay?.provenance?.basis || cm.evidence_summary || "",
      datasetIds:unq((cm.satisfied_by || "").split("|")), needs:unq((cm.needs || "").split("|")),
      markets:[], marketRoles:[], fieldsUnmapped:0
    });
  }
  const statusBuckets = Object.fromEntries(Object.entries(coverage.summary?.by_verified_bucket || {}));
  if (verifiedRows.length !== 1649 || marketRows.length !== 170) {
    throw new Error("Frozen baseline differs from the required 1,649 distinct inputs / 170 archetypes; refusing generation.");
  }
  const markets = [], edges = [];
  const reconciliation = seriesReconciliation.sports || {};
  for (const row of marketRows) {
    const id = row.sport + ":" + row.archetype;
    const arch = catalog[row.sport]?.archetypes?.[row.archetype] ||
      catalog[row.sport]?.unregistered_archetypes?.[row.archetype];
    if (!arch) reports.unmappedMarketArchetypes.push(id);
    const roles = new Map((arch?.inputs || []).map((i) => [i.id, i]));
    const counts = {primary:0, missingPrimary:0, predictive:0};
    const series = (reconciliation[row.sport] || []).filter((r) => r.archetype === row.archetype)
      .map((r) => ({kind:r.type_period || "", count:r.series || 0, examples:(r.examples || []).slice(0,3)}));
    const market = {id, sport:row.sport, archetype:row.archetype, label:row.label || arch?.label || row.archetype,
      target:arch?.target || "", mechanism:arch?.mechanism || "", kind:row.kind,
      primary:row.predictive_primary, primaryCovered:row.primary_FULL + row.primary_PARTIAL + row.primary_PROXY,
      primaryMissing:row.predictive_primary - row.primary_FULL - row.primary_PARTIAL - row.primary_PROXY,
      predictive:row.predictive_required, complete:row.independently_complete === true,
      sources:series, inputs:[]};
    const rawIds = Object.keys(row.input_categories || {});
    for (const inputId of rawIds) {
      const key = row.sport + ":" + inputId;
      const base = inputByKey.get(key), roleRec = roles.get(inputId), category = row.input_categories[inputId];
      const kind = classifyEdge(inputId, category, row, defs[row.sport]?.[inputId]);
      const role = roleRec?.role || "UNMAPPED_ROLE";
      if (!base || !roleRec) reports.unmappedMarketInputs.push({market:id,input:key,reason:!base ? "NO_VERIFIED_REGISTRY" : "NO_MARKET_ROLE"});
      const edge = {market:id,input:key,role,kind,marketCategory:category,
        verifiedStatus:base?.status || "UNVERIFIED", why:roleRec?.why || "", primary:role === "primary" && kind === "PREDICTIVE"};
      if (kind === "PREDICTIVE") {
        counts.predictive++;
        if (edge.primary) { counts.primary++; if (isMissing(edge.verifiedStatus)) counts.missingPrimary++; }
      }
      edges.push(edge); market.inputs.push(key);
      if (base) {base.markets.push(id);base.marketRoles.push({market:id,role,kind});}
    }
    if (counts.primary !== row.predictive_primary || counts.predictive !== row.predictive_required) {
      reports.primaryRoleReconciliation.push({market:id,listed:row.predictive_primary,derived:counts.primary,
        predictiveListed:row.predictive_required,predictiveDerived:counts.predictive});
    }
    markets.push(market);
  }
  for (const inp of inputByKey.values()) {
    inp.markets = unq(inp.markets);
    inp.marketRoles.sort((a,b)=>a.market.localeCompare(b.market));
    if (!inp.markets.length) reports.unmappedCoverageInputs.push(inp.key);
  }
  const dsObjects = datasets.datasets || {};
  const srcObjects = sources.sources || {};
  const datasetById = new Map(Object.entries(dsObjects).map(([id,d]) => [id,{
    id,title:d.title || id, sports:d.sports || [], cost:d.cost || "unknown", access:d.access_status || "UNKNOWN",
    evidence:d.evidence_grade || "UNKNOWN", pit:d.pit || "UNKNOWN",
    history:d.history || {}, sources:d.sources || [],
    sourceLinks:(d.sources || []).map((s)=>({id:s, name:srcObjects[s]?.name || s,
      proposedUrl:srcObjects[s]?.url || "", cost:srcObjects[s]?.cost || "unknown",
      rights:rightsFor(s,rights)})),
    inputs:[], markets:[], fieldMappings:[], rowsCollected:d.rows_collected, missingness:d.missingness || ""
  }]));
  const datasetEdges = [];
  for (const inp of inputByKey.values()) {
    for (const id of inp.datasetIds) {
      const ds = datasetById.get(id);
      if (!ds) {reports.unmatchedDatasetIds.push({dataset:id,input:inp.key});continue;}
      const fieldNames = auditFields(audit,inp.key,id);
      const link = {dataset:id,input:inp.key,fields:fieldNames,fieldEvidence:fieldNames.length ? "AUDIT_DECLARED_UNVERIFIED_SCHEMA" : "FIELD_UNMAPPED",
        needs:inp.needs, status:inp.status};
      datasetEdges.push(link);
      ds.inputs.push(inp.key); ds.fieldMappings.push(link);
      ds.markets.push(...inp.markets);
      if (!fieldNames.length) {reports.unmappedFields.push({dataset:id,input:inp.key});inp.fieldsUnmapped++;}
    }
  }
  const datasetsOut = [...datasetById.values()].map((d)=>({
    ...d, inputs:unq(d.inputs), markets:unq(d.markets),
    // A dataset is NOT cleared for use just because a source appears as a free candidate.
    provenanceReady:d.access === "COLLECTED_ARCHIVE" && d.rowsCollected != null &&
      d.sourceLinks.some((s)=>s.rights.some((r)=>r.research_cleared && r.collection_allowed)),
  })).sort((a,b)=>a.id.localeCompare(b.id));
  const primaryMissingEdges = edges.filter(e=>e.primary && isMissing(e.verifiedStatus));
  const missingByInput = new Map();
  for(const e of primaryMissingEdges){
    if(!missingByInput.has(e.input))missingByInput.set(e.input,new Set());
    missingByInput.get(e.input).add(e.market);
  }
  const queue = datasetsOut.map(d=>{
    const impacted = unq(d.inputs.filter(k=>missingByInput.has(k)));
    const impactedMarkets = new Set();
    const slotIds = new Set();
    for (const k of impacted) for (const m of missingByInput.get(k) || []) {
      impactedMarkets.add(m);slotIds.add(m+"|"+k);
    }
    const allowedPath = d.sourceLinks.some(s=>s.rights.some(r=>r.research_cleared && r.collection_allowed));
    const commercialPath = d.sourceLinks.some(s=>s.rights.some(r=>r.commercial_cleared && r.collection_allowed));
    const cost = d.cost.toLowerCase().includes("paid") ? "paid" :
      d.cost.toLowerCase().includes("free") ? "free" : "unknown";
    const pit = d.pit;
    let next = "Verify the exact dataset-to-input columns and acquisition licence before use.";
    if (!allowedPath) next = "Verify provider terms, original-source provenance and permission before any collection.";
    else if (pit === "LIVE_SNAPSHOT" || pit === "WEEKLY_SNAPSHOT" || pit === "PROSPECTIVE_CAPTURE_ONLY")
      next = "Design an explicitly approved timestamped capture and validate pre-decision vintages.";
    else if (!d.provenanceReady) next = "Verify authorized collection path, field schema and historical point-in-time coverage.";
    else if (impacted.some(k=>(inputByKey.get(k)?.fieldsUnmapped || 0)>0))
      next = "Resolve exact field mappings, then replay the historical feature with PIT guards.";
    else next = "Validate reusable fields and PIT windows, then independently replay linked inputs.";
    const q={dataset:d.id,title:d.title,impactedInputs:impacted,impactMarkets:unq([...impactedMarkets]),
      potentialPrimarySlots:slotIds.size,distinctInputs:impacted.length,distinctMarkets:impactedMarkets.size,
      cost,access:d.access,pit,rights:unq(d.sourceLinks.flatMap(s=>s.rights.map(r=>r.tier))),
      researchPath:allowedPath,commercialPath,provenanceReady:d.provenanceReady,
      fieldMappingsResolved:d.fieldMappings.filter(e=>e.fields.length).length,
      fieldMappingsTotal:d.fieldMappings.length, next,
      caveat:"Potential overlaps across datasets; individual dataset impacts MUST NOT be summed."};
    return q;
  }).filter(q=>q.potentialPrimarySlots>0)
    .sort((a,b)=>preference(a)-preference(b)||b.potentialPrimarySlots-a.potentialPrimarySlots||
      b.distinctInputs-a.distinctInputs||a.dataset.localeCompare(b.dataset))
    .map((q,i)=>({rank:i+1,...q}));
  const sourceSummary = {
    inputs:verifiedRows.length,archetypes:marketRows.length,
    predictiveSlots:marketRows.reduce((n,r)=>n+r.predictive_required,0),
    primarySlots:marketRows.reduce((n,r)=>n+r.predictive_primary,0),
    primaryCovered:marketRows.reduce((n,r)=>n+r.primary_FULL+r.primary_PARTIAL+r.primary_PROXY,0),
    primaryMissing:marketRows.reduce((n,r)=>n+r.predictive_primary-r.primary_FULL-r.primary_PARTIAL-r.primary_PROXY,0),
    statuses:statusBuckets, marketEdges:edges.length,datasetEdges:datasetEdges.length,
    datasets:datasetsOut.length, sourceCount:Object.keys(srcObjects).length, queue:queue.length,
    baselineLockPresent:baselineLock != null, unassignedSeriesGroups:
      Object.values(reconciliation).flat().filter(x=>!x.archetype).length
  };
  if(sourceSummary.predictiveSlots!==3670||sourceSummary.primaryMissing!==949)
    throw new Error("Predictive or PRIMARY denominator drift: "+JSON.stringify(sourceSummary));
  reports.unmatchedDatasetIds = reports.unmatchedDatasetIds.sort((a,b)=>a.dataset.localeCompare(b.dataset));
  return {schema:"sift-market-input-map-1",status:"RESEARCH_ONLY",
    note:"Existing approved catalog only. Dataset links are candidates, not evidence of data rights, complete schemas or PIT usability. Counts are NOT additive across datasets.",
    sourceBranch:"claude/sift-alpha-free-data-coverage-wdmcaz",summary:sourceSummary,report:reports,
    markets,inputs:[...inputByKey.values()],datasets:datasetsOut,edges,datasetEdges,queue};
}

function loadAll() {
  const cat = Object.fromEntries(SPORTS.map(s=>[s,readJSON(BASE+"catalog/"+s+".json")]));
  return buildMap({
    catalog:cat,completeness:readJSON(BASE+"market_completeness/market_completeness.json"),
    coverage:readJSON(DATA+"verified_coverage.json"),
    coverageRows:parseCSV(fs.readFileSync(path.join(ROOT,DATA+"coverage_matrix.csv"),"utf8")),
    datasets:readJSON(DATA+"datasets.json"),sources:readJSON(DATA+"sources.json"),
    rights:readJSON(DATA+"rights_registry.json"),
    audit:readJSON(DATA+"input_audit.json"),
    seriesAssignments:readJSON(BASE+"market_universe/series_assignment.json"),
    seriesReconciliation:readJSON(BASE+"market_universe/reconciliation.json"),
    baselineLock:readJSON(BASE+"baseline_lock.json"),
  });
}
function writeOutputs(g) {
  const dir=path.join(ROOT,OUTPUT);
  fs.mkdirSync(dir,{recursive:true});
  fs.writeFileSync(path.join(dir,"graph.json"),JSON.stringify(g)+"\n");
  const lookup=new Map(g.inputs.map(x=>[x.key,x]));
  const edgeRows=g.edges.map(e=>({...e,
    inputLabel:lookup.get(e.input)?.label||"",status:e.verifiedStatus,why:e.why}));
  const inputRows=g.inputs.map(i=>({...i,
    markets:i.markets.join("|"),datasets:i.datasetIds.join("|"),
    needs:i.needs.join("|"),history:i.history.join("|")}));
  const dsRows=g.datasetEdges.map(e=>({...e,fields:e.fields.join("|"),needs:e.needs.join("|")}));
  const qRows=g.queue.map(q=>({...q,impactedInputs:q.impactedInputs.join("|"),
    impactMarkets:q.impactMarkets.join("|"),rights:q.rights.join("|")}));
  const tables=[
    ["market-input-edges.csv",edgeRows,["market","input","inputLabel","role","kind","marketCategory","verifiedStatus","primary","why"]],
    ["distinct-inputs.csv",inputRows,["key","sport","id","label","status","statusEvidence","pit","pregame","cost","category","markets","datasets","needs","fieldsUnmapped"]],
    ["dataset-input-edges.csv",dsRows,["dataset","input","fields","fieldEvidence","needs","status"]],
    ["acquisition-queue.csv",qRows,["rank","dataset","title","potentialPrimarySlots","distinctInputs","distinctMarkets","impactedInputs","impactMarkets","cost","access","pit","rights","researchPath","commercialPath","provenanceReady","fieldMappingsResolved","fieldMappingsTotal","next","caveat"]]
  ];
  for(const [name,rows,fields] of tables) fs.writeFileSync(path.join(dir,name),csv(rows,fields));
  fs.writeFileSync(path.join(dir,"reconciliation.json"),JSON.stringify({summary:g.summary,unmapped:g.report},null,2)+"\n");
  return dir;
}
if (process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  const graph=loadAll();
  const dir=writeOutputs(graph);
  console.log(JSON.stringify({generated:dir,summary:graph.summary,unmapped:Object.fromEntries(
    Object.entries(graph.report).map(([k,v])=>[k,v.length]))},null,2));
}
