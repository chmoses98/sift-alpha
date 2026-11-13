// Pure helpers for the Market & Input Map (RESEARCH_ONLY). No scoring: everything here indexes, filters or traverses
// research/input_research/market_input_map/map.json, which alpha_engine.input_research.data_foundation.market_input_map generates.

export const SPORTS = ["NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"];
export const BUCKETS = ["FULL", "PARTIAL", "PROXY", "DATA_IN_HAND", "REQUIRES_COLLECTION", "BLOCKED", "FAILED", "UNVERIFIED", "EXCLUDED"];
export const CLASSES = ["PREDICTIVE", "MARKET_BENCHMARK", "RULES_SETTLEMENT_METADATA", "OPERATIONAL"];
export const ROLE_ORDER = {primary: 0, secondary: 1, context: 2};
export const COVERED = ["FULL", "PARTIAL", "PROXY"];

export const EMPTY_FILTERS = {sport: "All", q: "", bucket: "All", cls: "All", primary: false, free: false, prospective: false, commercial: false, missing: false};

/** Turn the positional arrays of map.json into objects and build the lookups every view needs. */
export function indexMap(m) {
  const edges = m.edges.map(([a, i, role, cls, grp, cat]) => ({a, i, role, cls, grp, cat}));
  const dsEdges = m.dataset_edges.map(([d, i, type, need, trigger, pit, access]) => ({d, i, type, need, trigger, pit, access}));
  const group = (xs, k) => { const o = new Map(); for (const x of xs) { const v = o.get(x[k]); v ? v.push(x) : o.set(x[k], [x]); } return o; };
  const arch = new Map(m.archetypes.map(a => [a.k, a]));
  return {m, edges, dsEdges, arch, edge: new Map(edges.map(e => [e.a + "|" + e.i, e])), byArch: group(edges, "a"), byInput: group(edges, "i"), dsByInput: group(dsEdges, "i"), dsByDataset: group(dsEdges, "d")};
}

export const isMissingPrimary = e => e.cls === "PREDICTIVE" && e.role === "primary" && !COVERED.includes(e.cat);

// ---- Linked filtering. ONE model for every view: the filters select a set of matching market->input edges (and matching inputs);
// Markets, Inputs, Datasets and Queue each show the entities linked to that set. FILTER_SCOPE states, per view, exactly how filters apply.
export const FILTER_SCOPE = {
  markets: "A market is shown if at least one of its inputs passes every filter; only those inputs are listed. Search matches the market or any listed input.",
  inputs: "Sport, status, free-source, prospective and commercial filters test the input itself; class, PRIMARY and missing-PRIMARY require at least one matching market edge. Search matches the input id or label.",
  datasets: "Linked: a dataset is shown if it feeds at least one matching input; commercial-use additionally requires the dataset itself to be commercial-cleared. Search matches the dataset or a linked matching input. With no filters, all datasets are shown (including those no input names).",
  queue: "Linked: a queue row is shown if at least one of its missing PRIMARY slots is a matching edge; the row shows matching / total slots. Ranks, groups and committed totals are unchanged by filters. Search matches the dataset or a slot.",
};

const inputLevel = f => f.sport !== "All" || f.bucket !== "All" || f.free || f.prospective || f.commercial;
const edgeLevel = f => f.cls !== "All" || f.primary || f.missing;
export const edgeFilterActive = f => f.bucket !== "All" || edgeLevel(f) || f.free || f.prospective || f.commercial;
export const anyFilterActive = f => inputLevel(f) || edgeLevel(f);
export function activeFilterLabels(f) {
  const out = [];
  if (f.sport !== "All") out.push("sport " + f.sport); if (f.bucket !== "All") out.push("status " + f.bucket); if (f.cls !== "All") out.push("class " + f.cls);
  if (f.primary) out.push("PRIMARY only"); if (f.missing) out.push("missing PRIMARY"); if (f.free) out.push("free source available");
  if (f.prospective) out.push("prospective capture"); if (f.commercial) out.push("commercial-use cleared"); if (f.q) out.push(`search “${f.q}”`);
  return out;
}

/** Properties of the input itself (search excluded). */
export function inputMatches(key, inp, f) {
  if (f.sport !== "All" && inp.sport !== f.sport) return false;
  if (f.bucket !== "All" && inp.bucket !== f.bucket) return false;
  if (f.free && !inp.free_source_datasets.length) return false;
  if (f.prospective && !inp.prospective_need) return false;
  if (f.commercial && !inp.rights.commercial_cleared) return false;
  return true;
}

/** An edge matches when its input matches and the edge passes class / role / missing filters. */
export function edgeMatches(e, inp, f) {
  if (f.cls !== "All" && e.cls !== f.cls) return false;
  if (f.primary && e.role !== "primary") return false;
  if (f.missing && !isMissingPrimary(e)) return false;
  return inputMatches(e.i, inp, f);
}

const has = (s, q) => String(s).toLowerCase().includes(q);

/** Inputs passing the filters, search excluded (the linked set the Datasets and Queue views use). */
export function matchingInputKeys(ix, f) {
  const out = new Set();
  for (const [k, v] of Object.entries(ix.m.inputs)) {
    if (!inputMatches(k, v, f)) continue;
    if (edgeLevel(f) && !(ix.byInput.get(k) || []).some(e => edgeMatches(e, v, f))) continue;
    out.add(k);
  }
  return out;
}

export function filterMarkets(ix, f) {
  const out = []; const q = f.q.toLowerCase();
  for (const a of ix.m.archetypes) {
    if (f.sport !== "All" && a.sport !== f.sport) continue;
    const es = (ix.byArch.get(a.k) || []).filter(e => edgeMatches(e, ix.m.inputs[e.i], f));
    if (edgeFilterActive(f) && !es.length) continue;
    if (q && !(has(a.k, q) || has(a.label, q) || es.some(e => has(e.i, q) || has(ix.m.inputs[e.i].label, q)))) continue;
    out.push({a, edges: es});
  }
  return out;
}

export function filterInputs(ix, f) {
  const keys = matchingInputKeys(ix, f); const q = f.q.toLowerCase();
  return Object.entries(ix.m.inputs).filter(([k, v]) => keys.has(k) && (!q || has(k, q) || has(v.label, q)));
}

/** [id, dataset, matching linked input keys] */
export function filterDatasets(ix, f) {
  const active = anyFilterActive(f); const keys = active ? matchingInputKeys(ix, f) : null; const q = f.q.toLowerCase();
  const out = [];
  for (const [id, d] of Object.entries(ix.m.datasets)) {
    if (f.commercial && !d.rights.commercial_cleared) continue;
    const linked = new Set((ix.dsByDataset.get(id) || []).map(e => e.i).filter(k => !active || keys.has(k)));
    if (active && !linked.size) continue;
    if (q && !(has(id, q) || has(d.title, q) || [...linked].some(k => has(k, q) || has(ix.m.inputs[k].label, q)))) continue;
    out.push([id, d, linked]);
  }
  return out;
}

/** [{q: queue row, match: matching slots}] in committed rank order. */
export function filterQueue(ix, f) {
  const active = anyFilterActive(f); const s = f.q.toLowerCase(); const out = [];
  for (const row of ix.m.queue) {
    if (f.commercial && !row.commercial_cleared) continue;
    const match = active ? row.slots.filter(([a, i]) => { const e = ix.edge.get(a + "|" + i); return e && edgeMatches(e, ix.m.inputs[i], f); }) : row.slots;
    if (!match.length) continue;
    if (s && !(has(row.dataset, s) || has(row.title, s) || match.some(([a, i]) => has(a, s) || has(i, s)))) continue;
    out.push({q: row, match});
  }
  return out;
}

/** Dataset -> inputs it feeds (deduplicated, with every requirement that links them) -> markets those inputs serve (deduplicated). */
export function datasetReach(ix, id) {
  const inputs = new Map();
  for (const e of ix.dsByDataset.get(id) || []) { const v = inputs.get(e.i); v ? v.push(e) : inputs.set(e.i, [e]); }
  const markets = new Map();
  for (const k of inputs.keys()) for (const e of ix.byInput.get(k) || []) { const v = markets.get(e.a); v ? v.add(e.i) : markets.set(e.a, new Set([e.i])); }
  const satisfiedInputs = [...inputs].filter(([, es]) => es.some(e => e.type === "SATISFIED_BY")).length;
  return {inputs, markets, satisfiedInputs};
}

/** Datasets an input needs: one entry per dataset (deduplicated), listing each requirement (need/trigger) that names it. */
export function inputDatasets(ix, key) {
  const out = new Map();
  for (const e of ix.dsByInput.get(key) || []) { const v = out.get(e.d); v ? v.push(e) : out.set(e.d, [e]); }
  return out;
}

export function countBy(xs, fn) { const o = {}; for (const x of xs) { const k = fn(x); o[k] = (o[k] || 0) + 1; } return o; }

export const nice = s => String(s ?? "").toLowerCase().replaceAll("_", " ");
export const fmt = n => n == null ? "–" : Number(n).toLocaleString("en-US");
export const unknown = v => (v == null || v === "") ? "UNKNOWN" : v;
