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
  return {m, edges, dsEdges, arch, byArch: group(edges, "a"), byInput: group(edges, "i"), dsByInput: group(dsEdges, "i"), dsByDataset: group(dsEdges, "d")};
}

export const isMissingPrimary = e => e.cls === "PREDICTIVE" && e.role === "primary" && !COVERED.includes(e.cat);

/** Input-level filters (sport, search, verified bucket, free source, prospective need, commercial rights). */
export function inputMatches(key, inp, f) {
  if (f.sport !== "All" && inp.sport !== f.sport) return false;
  if (f.bucket !== "All" && inp.bucket !== f.bucket) return false;
  if (f.cls !== "All" && !inp.classes.includes(f.cls)) return false;
  if (f.free && !inp.free_source_datasets.length) return false;
  if (f.prospective && !inp.prospective_need) return false;
  if (f.commercial && !inp.rights.commercial_cleared) return false;
  if (f.q) { const q = f.q.toLowerCase(); if (!(key.toLowerCase().includes(q) || String(inp.label).toLowerCase().includes(q))) return false; }
  return true;
}

/** Edge-level filters: the input filters (search excluded: market search matches the market too), plus class / role / missing on the edge itself. */
export function edgeMatches(e, inp, f) {
  if (f.cls !== "All" && e.cls !== f.cls) return false;
  if (f.primary && e.role !== "primary") return false;
  if (f.missing && !isMissingPrimary(e)) return false;
  return inputMatches(e.i, inp, {...f, q: "", cls: "All"});
}

export const edgeFilterActive = f => f.bucket !== "All" || f.cls !== "All" || f.primary || f.free || f.prospective || f.commercial || f.missing;

/** Archetypes passing the filters, each with the edges that pass. A market matches search by its own name/label or by any of its inputs. */
export function filterMarkets(ix, f) {
  const out = [];
  const q = f.q.toLowerCase();
  for (const a of ix.m.archetypes) {
    if (f.sport !== "All" && a.sport !== f.sport) continue;
    const es = (ix.byArch.get(a.k) || []).filter(e => edgeMatches(e, ix.m.inputs[e.i], f));
    if (edgeFilterActive(f) && !es.length) continue;
    if (q && !(a.k.toLowerCase().includes(q) || a.label.toLowerCase().includes(q) || es.some(e => e.i.toLowerCase().includes(q) || ix.m.inputs[e.i].label.toLowerCase().includes(q)))) continue;
    out.push({a, edges: es});
  }
  return out;
}

export function filterInputs(ix, f) {
  return Object.entries(ix.m.inputs).filter(([k, v]) => inputMatches(k, v, f) && (!f.primary || v.n_primary_markets > 0) && (!f.missing || (ix.byInput.get(k) || []).some(isMissingPrimary)));
}

export function filterDatasets(ix, f) {
  const q = f.q.toLowerCase();
  return Object.entries(ix.m.datasets).filter(([id, d]) => (f.sport === "All" || d.sports.includes(f.sport)) && (!f.commercial || d.rights.commercial_cleared) && (!f.free || d.cost !== "paid")
    && (!f.prospective || d.access_status === "PROSPECTIVE_CAPTURE_ONLY") && (!q || id.toLowerCase().includes(q) || d.title.toLowerCase().includes(q)));
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
