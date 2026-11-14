// Pure helpers for the Acquire and Training views (no React). Tested against the real artifacts in tests/acquisition.test.mjs.
export const TIER_KIND = {FREE: "ok", LOW_COST: "chipwarn", HIGHER_COST: "unv", UNRESOLVED: "miss"};
export const TIER_SHORT = {FREE: "free", LOW_COST: "low cost", HIGHER_COST: "higher cost", UNRESOLVED: "unresolved"};
export const STATE_LABEL = {TRAINING_READY: "training-ready", PROXY_READY: "proxy-ready (partial data or partial build)", BUILT_NOT_READY: "built, not training-ready",
  DATA_HELD_NOT_BUILT: "data held, not built", DATA_MISSING: "data missing"};
export const STATE_KIND = {TRAINING_READY: "ok", PROXY_READY: "chipwarn", BUILT_NOT_READY: "unv", DATA_HELD_NOT_BUILT: "plain", DATA_MISSING: "miss"};
export const CHECK_KIND = {OK: "ok", PARTIAL: "chipwarn", MISSING: "plain", FAILED: "miss", UNKNOWN: "unv", BLOCKED: "miss", REJECTED: "miss"};
export const SPORT_GROUP = {P0: ["NBA", "CBB", "NHL"], P1: ["NFL", "CFB"], P2: ["MLB", "SOCCER", "TENNIS"]};

const lc = x => String(x ?? "").replaceAll("_", " ").toLowerCase();
export {lc};

export function money(m, status) {
  if (m == null) return status === "UNKNOWN_ENTERPRISE" ? "enterprise (unpublished)" : "price unknown";
  if (m === 0) return "free";
  return "$" + (m >= 100 ? m.toFixed(0) : m.toFixed(2).replace(/\.00$/, "")) + "/mo";
}

export function priceLine(p) {
  const pr = p.price || {};
  const parts = [];
  if (pr.monthly_usd != null) parts.push("$" + pr.monthly_usd + "/month");
  if (pr.annual_usd != null) parts.push("$" + pr.annual_usd + "/year");
  const base = parts.length ? parts.join(" or ") : pr.status === "UNKNOWN_ENTERPRISE" ? "enterprise pricing (not published)" : pr.monthly_usd === 0 ? "free" : "price unknown";
  return `${base} · ${pr.tier || "tier n/a"} · ${pr.status || "UNKNOWN"}`;
}

const sportsOf = f => f === "all" ? null : SPORT_GROUP[f] || [f];

// Shortlist filter: sport or tier group, cost tier, max monthly cost (null = any), acquisition status, text.
export function filterShortlist(rows, {sport = "all", tier = "all", maxCost = null, status = "any", q = ""} = {}) {
  const S = sportsOf(sport); const needle = q.trim().toLowerCase();
  return rows.filter(r => !S || r.sports.some(s => S.includes(s)))
    .filter(r => tier === "all" || r.tier === tier)
    .filter(r => maxCost == null || (r.cheapest_monthly_usd != null && r.cheapest_monthly_usd <= maxCost))
    .filter(r => status === "any" || (status === "blocked" ? r.blockers.length > 0 : r.access_status === status))
    .filter(r => !needle || (r.title + " " + r.dataset + " " + r.sources.join(" ")).toLowerCase().includes(needle));
}

// Re-rank a filtered shortlist by the share of its value inside the chosen sports, so a P0 view leads with P0 datasets.
export function sportScore(r, sport) {
  const S = sportsOf(sport); if (!S) return r.score;
  const tot = Object.values(r.feeds_by_sport).reduce((a, b) => a + b, 0) || 1;
  const inS = S.reduce((a, s) => a + (r.feeds_by_sport[s] || 0), 0);
  return r.score * inS / tot;
}

export function rankForSport(rows, sport) {
  return [...rows].map(r => ({...r, sport_score: sportScore(r, sport)})).sort((a, b) => b.sport_score - a.sport_score || a.rank - b.rank);
}

export function providersFor(plan, row) {
  const ids = new Set(row.providers);
  return plan.providers.filter(p => ids.has(p.id));
}

// Decisions the owner must make, from the top of the shortlist (one per dataset, de-duplicated by text).
export function decisions(plan, n = 8) {
  const seen = new Set(); const out = [];
  for (const r of plan.shortlist) {
    if (r.tier === "FREE" && !r.blockers.some(b => b.startsWith("ACCESS") || b.startsWith("RIGHTS"))) continue;
    const key = r.decision; if (seen.has(key + r.dataset)) continue; seen.add(key + r.dataset);
    out.push(r); if (out.length >= n) break;
  }
  return out;
}

// Per-market acquisition rows: every predictive input of the market with its needs, training state and blocker.
export function marketRequirements(ledgerMarket, acq) {
  return ledgerMarket.inputs.filter(([, , cls]) => cls === "PREDICTIVE").map(([k, role]) => ({key: k, role, ...(acq.inputs[k] || {})}))
    .filter(r => r.l)
    .sort((a, b) => (a.role === "primary" ? 0 : 1) - (b.role === "primary" ? 0 : 1) || order(a.tr?.state) - order(b.tr?.state) || a.l.localeCompare(b.l));
}
const ORDER = ["DATA_MISSING", "DATA_HELD_NOT_BUILT", "BUILT_NOT_READY", "PROXY_READY", "TRAINING_READY"];
const order = s => ORDER.indexOf(s);

export function requirementTally(rows) {
  const t = {have: 0, partial: 0, missing: 0, ready: 0};
  for (const r of rows) {
    const st = r.tr?.state;
    if (st === "TRAINING_READY") t.ready++;
    if (st === "TRAINING_READY" || st === "DATA_HELD_NOT_BUILT") t.have++;
    else if (st === "PROXY_READY" || st === "BUILT_NOT_READY") t.partial++;
    else t.missing++;
  }
  return t;
}
