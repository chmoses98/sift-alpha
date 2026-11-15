import React, {useEffect, useMemo, useState} from "react";
import {CHECK_KIND, STATE_KIND, STATE_LABEL, TIER_KIND, TIER_SHORT, decisions, filterShortlist, lc, marketRequirements, money, priceLine, providersFor, rankForSport, requirementTally} from "./acquisition.mjs";
// The plan (shortlist, roadmap, providers, per-sport readiness) renders immediately; per-input detail loads on demand.
import PLAN from "../research/data_foundation_ops/acquisition_plan.json";
import P6 from "../research/data_foundation_ops/phase6_acquisition.json";
import P7 from "../research/data_foundation_ops/phase7_acquisition.json";

const INPUTS = import.meta.glob("../research/data_foundation_ops/acquisition_inputs.json");
let inputsPromise = null;
export function useAcqInputs(want = true) {
  const [A, setA] = useState(null);
  useEffect(() => { if (!want) return; let live = true; inputsPromise ||= Object.values(INPUTS)[0]().then(x => x.default || x);
    inputsPromise.then(x => live && setA(x)); return () => { live = false; }; }, [want]);
  return A;
}

const Chip = ({k = "plain", children, title}) => <span className={"ir-chip ir-" + k} title={title}>{children}</span>;
const fmt = n => n == null ? "UNKNOWN" : typeof n === "number" ? n.toLocaleString("en-US") : String(n);
const PAGE = 12;
const A = ({href, children}) => href ? <a className="mim-link" href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>;

function ProviderRow({p}) {
  return <li data-testid="acq-provider">
    <b>{p.name}</b> {p.role === "ALTERNATIVE" && <Chip>alternative</Chip>} <Chip k={p.price?.status === "VERIFIED" ? "ok" : p.price?.status === "ESTIMATE" ? "chipwarn" : "unv"}>{p.price?.status === "VERIFIED" ? "price verified" : p.price?.status === "ESTIMATE" ? "price estimate" : "price unknown"}</Chip>
    <div className="ir-why">{priceLine(p)}</div>
    {p.price?.evidence && <div className="ir-why">Price source: {p.price.evidence}</div>}
    <div className="ir-why">Fields: {p.fields || "n/a"}{p.history ? " · history: " + p.history : ""}{p.latency ? " · latency: " + p.latency : ""}</div>
    <div className="ir-why">Quota: {p.quota || "n/a"}{p.est_requests ? " · estimated requests: " + p.est_requests : ""} · point-in-time: {p.pit || "n/a"} · identity: {p.identity || "n/a"} · complexity: {lc(p.complexity)}</div>
    <div className="ir-why">Terms: {p.terms_summary || "not read"} · redistribution: <b>{lc(p.redistribution || "unclear")}</b> · commercial use needs a separate licence: <b>{lc(p.commercial_license_needed || "unclear")}</b></div>
    <div className="ir-why"><A href={p.url}>pricing page</A>{p.terms_url ? <> · <A href={p.terms_url}>terms</A></> : null} · {p.recommended_action}</div>
  </li>;
}

function DatasetCard({r, open: open0 = false, rankLabel}) {
  const [open, setOpen] = useState(open0);
  const provs = providersFor(PLAN, r);
  return <li className="mim-card" data-testid="acq-row">
    <span className="mim-qrank">{rankLabel} · {r.sports.join(", ")}</span>
    <button className="mim-title" onClick={() => setOpen(o => !o)} aria-expanded={open}>{r.title}</button> <code>{r.dataset}</code>
    <div className="mim-stats"><Chip k={TIER_KIND[r.tier]}>{TIER_SHORT[r.tier]}</Chip> <Chip>{money(r.cheapest_monthly_usd)}{r.tier === "FREE" && r.paid_alternative_monthly_usd ? " · paid option " + money(r.paid_alternative_monthly_usd) : ""}</Chip>
      <Chip k={r.completes ? "ok" : "plain"}>completes {r.completes} inputs</Chip> <Chip>advances {r.advances}</Chip> <Chip>feeds {r.feeds_missing_inputs} missing inputs · {r.market_families} markets</Chip>
      <Chip>{r.history_years ? r.history_years + " seasons" : "history unknown"}</Chip> <Chip>{lc(r.pit)}</Chip> <Chip k={r.access_status === "COLLECTED_ARCHIVE" ? "ok" : "plain"}>{lc(r.access_status)}</Chip></div>
    <div className="ir-why"><b>Why it matters:</b> {r.why}</div>
    <div className="ir-why"><b>Next engineering step:</b> {r.next_step}</div>
    <div className="ir-why"><b>Your decision:</b> {r.decision}</div>
    {open && <div className="mim-body">
      {r.blockers.length > 0 && <><h4>What blocks it today</h4><ul className="mim-actions">{r.blockers.map((b, i) => <li key={i}>{b}</li>)}</ul></>}
      <h4>Coverage by sport (missing PRIMARY inputs it feeds)</h4>
      <p className="ir-fine">{Object.entries(r.feeds_by_sport).map(([s, n]) => s + " " + n).join(" · ")}. Refresh: {r.freshness || "unknown"} · history {r.history?.first || "?"} → {r.history?.last || "?"} ({lc(r.history?.basis || "unknown")}). {r.missingness}</p>
      <h4>Rights and terms</h4>
      <p className="ir-fine">Rights tier: {r.rights.join(", ")} · ToS risk {r.tos_risk} · reachability {r.reachability.map(lc).join(", ")}.</p>
      {r.terms.map(t => <p key={t.source} className="ir-fine"><code>{t.source}</code>: internal research {lc(t.internal_noncommercial_research)}, automated collection {lc(t.automated_collection)}, raw redistribution {lc(t.raw_redistribution)}, commercial use {lc(t.commercial_use)}.</p>)}
      <h4>Where to get it ({provs.length ? provs.length + " priced providers" : "source: " + r.sources.join(", ")})</h4>
      {provs.length ? <ul className="mim-list">{provs.map(p => <ProviderRow key={p.id} p={p}/>)}</ul> : <p className="ir-fine">No commercial provider is catalogued; the free source(s) {r.sources.join(", ")} are the path.</p>}
      <h4>Markets it feeds (sample)</h4>
      <p className="ir-fine">{r.markets_sample.join(", ")}</p>
      {r.completes_sample.length > 0 && <><h4>Inputs it completes on its own (sample)</h4><p className="ir-fine">{r.completes_sample.join(", ")}</p></>}
    </div>}
  </li>;
}

// The data command center: which dataset to acquire next, what it costs, what it unlocks, and what decision it needs.
export function AcquireView() {
  const [sport, setSport] = useState("P0"); const [tier, setTier] = useState("all"); const [cost, setCost] = useState("any"); const [status, setStatus] = useState("any");
  const [q, setQ] = useState(""); const [n, setN] = useState(PAGE);
  const T = PLAN.totals;
  const rows = useMemo(() => rankForSport(filterShortlist(PLAN.shortlist, {sport, tier, q, status, maxCost: cost === "any" ? null : Number(cost)}), sport), [sport, tier, cost, status, q]);
  const dec = decisions(PLAN);
  return <div data-testid="acq">
    <p className="ir-fine">{PLAN.notice}</p>
    <div className="mim-cards" data-testid="acq-totals">
      <div><b>{fmt(T.missing_primary_inputs)}</b><small>distinct inputs behind {fmt(T.missing_primary_slots)} missing PRIMARY slots</small></div>
      <div><b>{fmt(T.complete_with_archives)}</b><small>have every raw dataset already (archive or open bulk download)</small></div>
      <div><b>{fmt(T.complete_after_free)}</b><small>would have all raw data after the free plan</small></div>
      <div><b>{fmt(T.complete_after_low_cost)}</b><small>after low-cost purchases too</small></div>
      <div><b>{fmt(T.missing_primary_inputs - T.complete_after_all_priced)}</b><small>still need an unresolved source</small></div>
      <div><b>{fmt(T.training_ready_inputs)}</b><small>predictive inputs training-ready ({fmt(T.proxy_ready_inputs)} proxy-ready) of {fmt(T.predictive_inputs)}</small></div>
    </div>
    <p className="ir-fine">“Have all raw data” is availability only: rights stay as recorded and an input still needs a built, blind-matched, point-in-time-safe feature before it is training-ready (Training tab). Counts are distinct inputs; one dataset or provider never counts an input twice.</p>

    <h3>Decisions for you</h3>
    <ul className="mim-list" data-testid="acq-decisions">{dec.map(r => <li key={r.dataset}><b>{r.title}</b> <Chip k={TIER_KIND[r.tier]}>{TIER_SHORT[r.tier]}</Chip> <Chip>{money(r.cheapest_monthly_usd)}</Chip><div className="ir-why">{r.decision}</div></li>)}</ul>

    <h3>Coverage by sport: missing PRIMARY inputs with all raw data</h3>
    <ul className="mim-list" data-testid="acq-sports">{PLAN.sports_order.map(s => { const d = PLAN.sports[s]; const pct = x => Math.round(100 * x / Math.max(1, d.missing_primary_inputs)); return <li key={s}>
      <b>{s}</b> <Chip>{d.tier}</Chip> <span className="ir-why">{d.missing_primary_inputs} missing inputs ({d.missing_primary_slots} slots)</span>
      <div className="acq-bar" aria-hidden="true"><i style={{width: pct(d.complete_after_all_priced) + "%"}} className="acq-b3"/><i style={{width: pct(d.complete_after_free) + "%"}} className="acq-b2"/><i style={{width: pct(d.complete_with_archives) + "%"}} className="acq-b1"/></div>
      <div className="ir-why">held now {d.complete_with_archives} · after free {d.complete_after_free} · after low cost {d.complete_after_low_cost} · after every priced option {d.complete_after_all_priced} · unresolved {d.never_completable_without_unresolved}</div></li>; })}</ul>

    <h3>Recommended datasets</h3>
    <div className="ir-filter" role="group" aria-label="Sport filter">{["P0", "P1", "P2", "all", ...PLAN.sports_order].map(x => <button key={x} className={sport === x ? "on" : ""} onClick={() => { setSport(x); setN(PAGE); }}>{x === "all" ? "All" : x}</button>)}</div>
    <div className="mim-frow">
      <label>Cost<select value={tier} onChange={e => { setTier(e.target.value); setN(PAGE); }} aria-label="Cost tier"><option value="all">all tiers</option>{PLAN.tiers.map(t => <option key={t} value={t}>{TIER_SHORT[t]}</option>)}</select></label>
      <label>Max $/month<select value={cost} onChange={e => { setCost(e.target.value); setN(PAGE); }} aria-label="Maximum monthly cost"><option value="any">any</option><option value="0">free only</option><option value="10">≤ $10</option><option value="50">≤ $50</option><option value="150">≤ $150</option></select></label>
      <label>Status<select value={status} onChange={e => { setStatus(e.target.value); setN(PAGE); }} aria-label="Acquisition status"><option value="any">any</option><option value="FREE_REACHABLE">free, reachable</option><option value="FREE_UNPROBED">free, not probed</option><option value="FREE_BLOCKED_FROM_RUNNER">blocked from runner</option><option value="PROSPECTIVE_CAPTURE_ONLY">forward capture only</option><option value="PAID_ONLY">paid only</option><option value="blocked">has a blocker</option></select></label>
      <label className="mim-q">Search<input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="dataset, source or provider"/></label>
    </div>
    <p className="ir-fine" data-testid="acq-count">{rows.length} datasets · ranked by estimated value inside the selected sports ({PLAN.weights.basis}: breadth × sport priority × point-in-time × history ÷ difficulty ÷ cost; never a predicted model gain).</p>
    <ul className="mim-queue">{rows.slice(0, n).map((r, i) => <DatasetCard key={r.dataset} r={r} rankLabel={"#" + (i + 1)}/>)}</ul>
    {rows.length > n && <button className="mim-more" onClick={() => setN(x => x + PAGE)}>Show more ({rows.length - n} left)</button>}

    <h3>Roadmap: cumulative unlocks, each input counted once</h3>
    <p className="ir-fine">Greedy order inside each cost tier: each step lists only the inputs it newly completes given every earlier step and the data already held. Costs are the planning tier's monthly equivalent (estimates unless marked verified).</p>
    <ol className="mim-list acq-road" data-testid="acq-roadmap">{PLAN.roadmap.slice(0, 40).map(s => <li key={s.step}><b>{s.dataset}</b> <Chip k={TIER_KIND[s.tier]}>{TIER_SHORT[s.tier]}</Chip> <span className="ir-why">+{s.newly_complete} → {s.cumulative_complete} complete{s.monthly_usd ? " · " + money(s.monthly_usd) + " (running " + money(s.cumulative_monthly_usd) + ")" : ""} · {Object.entries(s.newly_complete_by_sport).map(([k, v]) => k + " +" + v).join(", ")}</span></li>)}</ol>
    {PLAN.roadmap.length > 40 && <p className="ir-fine">{PLAN.roadmap.length - 40} more steps, each completing few inputs.</p>}

    <details className="mim-units"><summary>Already held: {PLAN.held.length} datasets (owner archives and open bulk releases)</summary>
      <ul className="mim-queue">{PLAN.held.map(r => <DatasetCard key={r.dataset} r={r} rankLabel={r.held_kind === "ARCHIVE" ? "owner archive" : "open bulk download"}/>)}</ul></details>
    <details className="mim-units" data-testid="acq-providers"><summary>Provider directory: {PLAN.providers.length} providers, links, prices and terms</summary>
      <p className="ir-fine">Checked {PLAN.provider_catalog_checked}. Provider websites were not reachable from the research environment, so most paid prices are estimates from search results; verify on the linked page before any purchase.</p>
      <ul className="mim-list">{PLAN.providers.map(p => <ProviderRow key={p.id} p={p}/>)}</ul></details>
    <details className="mim-units"><summary>How the ranking is computed</summary><ul className="ir-fine">{Object.entries(PLAN.weights).map(([k, v]) => <li key={k}><b>{lc(k)}:</b> {v}</li>)}</ul></details>
  </div>;
}

// Training readiness is separate from availability: archived data and working code are both necessary, neither is sufficient.
export function TrainingView() {
  return <div data-testid="acq-training">
    <p className="ir-fine">An input is <b>training-ready</b> only when all of these hold: {PLAN.readiness_criteria.slice(0, 5).map(c => c[1].toLowerCase()).join("; ")}. <b>Proxy-ready</b> means every check passes at least partially (partial archive or a proxy build). A chronological challenger evaluation is tracked but not required.</p>
    {PLAN.sports_order.map(s => { const d = PLAN.sports[s]; const t = d.training; return <div key={s} className="df-sport" data-testid={"acq-train-" + s}>
      <h3>{s} <Chip>{d.tier}</Chip> <Chip k={t.score >= 6 ? "ok" : t.score >= 4 ? "chipwarn" : "unv"}>{t.score} of {t.of} dataset checks</Chip></h3>
      <div className="mim-stats">{Object.keys(STATE_LABEL).map(k => d.readiness[k] ? <Chip key={k} k={STATE_KIND[k]}>{d.readiness[k]} {STATE_LABEL[k]}</Chip> : null)}</div>
      <ul className="mim-list">{t.checks.map(([name, st, why]) => <li key={name}><Chip k={CHECK_KIND[st]}>{lc(st)}</Chip> {name}<div className="ir-why">{why}</div></li>)}</ul>
      {t.blockers.length > 0 && <p className="ir-fine"><b>Main blockers:</b> {t.blockers.slice(0, 3).join(" · ")}</p>}
    </div>; })}
  </div>;
}

// Market drill-down: for every predictive input, what we have, what is missing, which dataset and provider, and what blocks training.
export function MarketAcquisition({mk}) {
  const acq = useAcqInputs(true); const [n, setN] = useState(PAGE); const [show, setShow] = useState("open");
  if (!acq) return <p className="ir-fine">Loading data requirements…</p>;
  const all = marketRequirements(mk, acq); const t = requirementTally(all);
  const rows = all.filter(r => show === "all" || (show === "open" ? r.tr?.state !== "TRAINING_READY" : r.tr?.state === show));
  return <div data-testid="acq-market">
    <div className="mim-cards df-cards4">
      <div><b>{t.have}</b><small>inputs with all data held</small></div>
      <div><b>{t.partial}</b><small>partial or proxy builds</small></div>
      <div><b>{t.missing}</b><small>data missing</small></div>
      <div><b>{t.ready}</b><small>training-ready</small></div>
    </div>
    <label>Show<select value={show} onChange={e => { setShow(e.target.value); setN(PAGE); }} aria-label="Filter requirements"><option value="open">not yet training-ready</option><option value="all">all</option>{Object.keys(STATE_LABEL).map(k => <option key={k} value={k}>{STATE_LABEL[k]}</option>)}</select></label>
    <ul className="mim-list" data-testid="acq-reqs">{rows.slice(0, n).map(r => <li key={r.key}>
      <b>{r.l}</b> <Chip>{r.role}</Chip> <Chip k={STATE_KIND[r.tr.state]}>{STATE_LABEL[r.tr.state]}</Chip>
      <div className="ir-why"><b>Blocker:</b> {r.b}</div>
      <ul className="acq-needs">{r.n.map(([need, have, opts]) => <li key={need}><Chip k={have ? "ok" : "miss"}>{have ? "have" : "need"}</Chip> <b>{lc(need)}</b>: {opts.slice(0, 3).map(d => { const x = acq.datasets[d]; return <span key={d} className="acq-opt"><code>{d}</code> ({x.held ? (x.hk === "ARCHIVE" ? "in archive" : "open download") : TIER_SHORT[x.tier] + ", " + money(x.c)}{x.h ? ", " + x.h + " seasons" : ""})</span>; })}{opts.length > 3 ? ` +${opts.length - 3} more` : ""}</li>)}</ul>
      <div className="ir-why">Checks: {Object.entries(r.tr.c).map(([k, v]) => k + " " + lc(v)).join(" · ")}</div>
    </li>)}</ul>
    {rows.length > n && <button className="mim-more" onClick={() => setN(x => x + PAGE)}>Show more ({rows.length - n} left)</button>}
  </div>;
}

// Phase 6 acquisition log: what was probed, collected, verified, built and made training-ready, kept on separate rungs. Rendered only from
// research/data_foundation_ops/phase6_acquisition.json (alpha_engine.foundation.phase6); no number is typed here.
const P6_RUNG = {RESEARCHED: "researched (documented only)", PROBED: "probed (a request answered)", COLLECTED: "collected (rows held)", REPLAY_VERIFIED: "replay-verified (leak gates)",
  BLIND_MATCHED_FEATURE_BUILT: "feature built + blind-matched", TRAINING_READY: "training-ready"};
const P6_RESULT = {REACHABLE: "ok", NOT_PROBED: "miss"};
export function Phase6View() {
  const B = P6.baseline, F = P6.after;
  const delta = (k, label) => <div key={k}><b>{fmt(B[k])} → {fmt(F[k])}</b><small>{label}</small></div>;
  return <div data-testid="p6">
    <p className="ir-fine">{P6.notice}</p>
    <ol className="p6-ladder" data-testid="p6-ladder" aria-label="Stages, weakest to strongest">{P6.stage_order.map(s => <li key={s}>{P6_RUNG[s]}</li>)}</ol>
    <div className="mim-cards" data-testid="p6-totals">
      {delta("training_ready_inputs", "training-ready predictive inputs")}
      {delta("verified_full", "inputs VERIFIED_FULL (certified)")}
      {delta("missing_primary_slots", "missing PRIMARY slots")}
      {delta("missing_primary_inputs", "distinct inputs behind them")}
    </div>
    <p className="ir-fine">Baseline: {B.as_of}. The new inputs feed no market where they are a missing PRIMARY slot, so the slot count does not move.</p>

    <h3>New training-ready inputs</h3>
    <ul className="mim-list" data-testid="p6-built">{P6.built.map(b => <li key={b.input}><b>{b.input}</b> <Chip k={b.replay_ok ? "ok" : "miss"}>replay {b.replay_ok ? "passed" : "failed"}</Chip> <Chip k={b.blind_match.split("/")[0] === b.blind_match.split("/")[1] ? "ok" : "miss"}>blind match {b.blind_match}</Chip> <Chip k={b.verified_status === "VERIFIED_FULL" ? "ok" : "chipwarn"}>{lc(b.verified_status)}</Chip> <Chip k={STATE_KIND[b.training_state] || "plain"}>{STATE_LABEL[b.training_state] || lc(b.training_state)}</Chip>
      <div className="ir-why">{b.builder} · {b.columns.length} columns · {b.span[0]} .. {b.span[1]} · min coverage {Math.round(100 * b.min_coverage)}% · {lc(b.pit)} · next: {b.training_blocker}</div></li>)}</ul>

    <h3>Sources probed</h3>
    <ul className="mim-list" data-testid="p6-probes">{P6.probes.map(p => <li key={p.id}><b>{p.id}</b> <Chip>{p.sport}</Chip> <Chip k={P6_RESULT[p.result] || "unv"}>{lc(p.result)}{p.http ? " · HTTP " + p.http : ""}</Chip><div className="ir-why">{p.description}</div></li>)}</ul>
    <p className="ir-fine">Reachable is not permitted: rights stay as recorded in the rights registry.</p>

    <h3>Data actually read or collected</h3>
    <ul className="mim-list" data-testid="p6-collected">{P6.collected.map(c => <li key={c.dataset}><b>{c.dataset}</b> <Chip k={c.status === "READ_FROM_OWNER_ARCHIVE" ? "ok" : "miss"}>{lc(c.status)}</Chip><div className="ir-why">{c.files} files · about {Math.round(c.bytes / 1e6)} MB · {c.why}</div></li>)}</ul>

    <h3>Blockers and decisions for you</h3>
    <ul className="mim-list" data-testid="p6-blockers">{P6.blockers.map(b => <li key={b.id}><Chip k={b.kind === "OWNER_DECISION" ? "miss" : "chipwarn"}>{lc(b.kind)}</Chip> <Chip>{b.sports.join(" · ")}</Chip><div className="ir-why">{b.text}</div></li>)}</ul>

    <h3>Acquisition priorities that changed</h3>
    <ul className="mim-list">{P6.priority_changes.map((t, i) => <li key={i}><div className="ir-why">{t}</div></li>)}</ul>

    <h3>Forward-capture proposal (not scheduled)</h3>
    <p className="ir-fine">{P6.capture_note}</p>
    <ul className="mim-list" data-testid="p6-capture">{P6.capture_proposal.map(c => <li key={c.feed}><b>{c.feed}</b> <Chip>{String(c.requests_per_day)} req/day</Chip><div className="ir-why">when: {c.times} · unlocks: {c.unlocks} · storage: {c.storage} · checks: {c.quality} · reuse: {c.reuse}</div></li>)}</ul>
  </div>;
}

// Phase 7 log: real collection, new certified inputs, per-sport training datasets and capture status. Rendered only from
// research/data_foundation_ops/phase7_acquisition.json (alpha_engine.foundation.phase7); no number is typed here.
const P7_RESULT = {COLLECTED: "ok", OWNER_ARCHIVE_CURRENT: "ok", REACHABLE: "plain", REACHABLE_NOT_USED: "chipwarn", NOT_PUBLISHED: "unv", BLOCKED: "miss", CAPTURE_STALLED: "miss"};
const pct = x => x == null ? "n/a" : Math.round(100 * x) + "%";
export function Phase7View() {
  const B = P7.baseline, F = P7.after;
  const delta = (k, label) => <div key={k}><b>{fmt(B[k])} → {fmt(F[k])}</b><small>{label}</small></div>;
  return <div data-testid="p7">
    <p className="ir-fine">{P7.notice}</p>
    <ol className="p6-ladder" aria-label="Stages, weakest to strongest">{P7.stage_order.map(s => <li key={s}>{P6_RUNG[s]}</li>)}</ol>
    <div className="mim-cards" data-testid="p7-totals">
      {delta("training_ready_inputs", "training-ready predictive inputs")}
      {delta("verified_full", "inputs VERIFIED_FULL (certified)")}
      {delta("missing_primary_slots", "missing PRIMARY slots")}
      {delta("missing_primary_inputs", "distinct inputs behind them")}
    </div>
    <p className="ir-fine">Baseline: {B.as_of}. Training-ready by sport now: {Object.entries(P7.training_ready_by_sport).map(([s, n]) => s + " " + n).join(" · ")}.</p>

    <h3>Training datasets</h3>
    <ul className="mim-list" data-testid="p7-sets">{P7.training_sets.map(t => <li key={t.sport}><b>{t.sport}</b> <Chip k={t.checks.keys_unique && t.checks.deterministic_regeneration ? "ok" : "miss"}>{t.checks.deterministic_regeneration ? "regenerates identically" : "not deterministic"}</Chip> <Chip>{fmt(t.rows)} games · {t.seasons[0]}..{t.seasons[1]}</Chip> <Chip>{t.n_inputs} inputs · {t.n_feature_columns} columns</Chip>
      <div className="ir-why">{t.unit} · splits: {Object.entries(t.rows_by_split).map(([k, v]) => k + " " + fmt(v)).join(" · ")} · latest game {t.latest_game_date}</div>
      <div className="ir-why">Outcomes reconciled with play-by-play: {fmt(t.outcome_reconciliation.games_with_pbp)} games, {fmt(t.outcome_reconciliation.outcome_mismatches)} mismatches · cutoff: {t.prediction_cutoff}</div>
      <div className="ir-why">Walk-forward check (market-free ridge, test seasons): home-margin MAE {t.walk_forward.all.mae_model} with all ready inputs vs {t.walk_forward.legacy.mae_model} with the earlier ready inputs only vs {t.walk_forward.all.mae_constant} constant; winner accuracy {pct(t.walk_forward.all.winner_acc_model)}. Diagnostic only, not a model promotion.</div>
      <div className="ir-why">{t.file}</div></li>)}
      {Object.entries(P7.no_training_set).map(([s, why]) => <li key={s}><b>{s}</b> <Chip k="chipwarn">no dataset yet</Chip><div className="ir-why">{why}</div></li>)}</ul>

    <h3>New training-ready inputs</h3>
    <ul className="mim-list" data-testid="p7-built">{P7.built.map(b => <li key={b.input}><b>{b.input}</b> <Chip k={b.replay_ok ? "ok" : "miss"}>replay {b.replay_ok ? "passed" : "failed"}</Chip> <Chip k={b.blind_match.split("/")[0] === b.blind_match.split("/")[1] ? "ok" : "miss"}>blind match {b.blind_match}</Chip> <Chip k={b.verified_status === "VERIFIED_FULL" ? "ok" : "chipwarn"}>{lc(b.verified_status)}</Chip> <Chip k={STATE_KIND[b.training_state] || "plain"}>{STATE_LABEL[b.training_state] || lc(b.training_state)}</Chip>
      <div className="ir-why">{b.builder} · {b.columns.length} columns · {b.span[0]} .. {b.span[1]} · min coverage {pct(b.min_coverage)} · {lc(b.pit)} · next: {b.training_blocker}</div></li>)}</ul>

    <h3>Sources tested and data collected</h3>
    <ul className="mim-list" data-testid="p7-sources">{P7.sources.map(p => <li key={p.id}><b>{p.id}</b> <Chip>{p.sport}</Chip> <Chip k={P7_RESULT[p.result] || "unv"}>{lc(p.result)}</Chip><div className="ir-why">{p.detail} · rights: {p.rights}</div></li>)}</ul>

    <h3>Capture status (nothing new scheduled)</h3>
    <p className="ir-fine">{P7.capture_note}</p>
    <ul className="mim-list" data-testid="p7-capture">{P7.capture.map(c => <li key={c.feed}><b>{c.feed}</b> <Chip k={/STALLED/.test(c.status) ? "miss" : "plain"}>{c.status}</Chip><div className="ir-why">action: {c.action} · requests/day: {c.requests_per_day} · value: {c.value}</div></li>)}</ul>

    <h3>Blockers and decisions for you</h3>
    <ul className="mim-list" data-testid="p7-blockers">{P7.blockers.map(b => <li key={b.id}><Chip k={/OWNER/.test(b.kind) ? "miss" : "chipwarn"}>{lc(b.kind)}</Chip> <Chip>{b.sports.join(" · ")}</Chip><div className="ir-why">{b.text}</div></li>)}</ul>

    <h3>Best next acquisitions</h3>
    <ul className="mim-list">{P7.priority_changes.map((t, i) => <li key={i}><div className="ir-why">{t}</div></li>)}</ul>
  </div>;
}
