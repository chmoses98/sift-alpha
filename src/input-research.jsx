import React, {useEffect, useMemo, useState} from "react";
import index from "../research/audit/input_research/index.json";
import queue from "../research/audit/input_research/queue.json";
import {ComputableInputsPanel, ScaledSearchPanel} from "./research-milestone2.jsx";
import {MarketUniverse, KalshiExperiment, GameWinnerExperiment, FoundationAudit, SearchResult, SoccerSearch, UnregisteredArchetypes, DataReadinessPanel} from "./research-experiments.jsx";
import {CatalogCompleteness} from "./catalog-completeness.jsx";
import {MarketInputMap} from "./market-input-map.jsx";
import {DataFoundation} from "./data-foundation.jsx";
import "./input-research.css";

// Everything is rendered from research/audit/input_research/*.json (alpha_engine.input_research). Nothing is hand-typed.
// Hypotheses and availability audits are NOT evidence; an untested input is labelled UNTESTED, never "weak" or "strong".
const LOADERS = import.meta.glob("../research/audit/input_research/sport_*.json");
const nice = s => String(s ?? "").toLowerCase().replaceAll("_", " ");
const f = (x, d = 3) => x == null || Number.isNaN(x) ? "–" : Math.abs(x) >= 100 ? x.toFixed(1) : Number(x).toPrecision(d);
const pct = x => x == null ? "–" : (100 * x).toFixed(0) + "%";
const ci = a => a ? `[${f(a[0], 2)}, ${f(a[1], 2)}]` : "";
const LV = {L0_INVENTORY_ONLY: "L0 inventory only", L1_TESTED_VS_BASELINE: "L1 tested vs baseline", L2_TESTED_VS_MARKET: "L2 tested vs near-close sportsbook line", L3_TESTED_VS_KALSHI: "L3 tested vs Kalshi price", L4_PROSPECTIVELY_CONFIRMED: "L4 prospectively confirmed"};
const Chip = ({kind, children, title}) => <span className={"ir-chip ir-" + kind} title={title}>{children}</span>;
const VerdictChip = ({v}) => <Chip kind={v || "UNTESTED"} title="Verdict ladder: demonstrated needs Holm-adjusted CI above zero, both chronological halves and every leave-one-season-out above zero">{nice(v || "UNTESTED")}</Chip>;

export function InputResearch() {
  const sports = Object.keys(index.sports);
  const [sport, setSport] = useState(sports.includes("NFL") ? "NFL" : sports[0]);
  const [doc, setDoc] = useState(null);
  const [fam, setFam] = useState(null);
  const [filter, setFilter] = useState("all");
  const [open, setOpen] = useState(null);
  const [archKey, setArchKey] = useState(null);
  useEffect(() => {
    let live = true;
    setDoc(null);
    const load = LOADERS[`../research/audit/input_research/sport_${sport}.json`];
    if (load) load().then(m => { if (live) { setDoc(m.default || m); } });
    return () => { live = false; };
  }, [sport]);
  const famList = useMemo(() => doc ? Object.entries(doc.families).sort((a, b) => (b[1].markets_now || 0) - (a[1].markets_now || 0)) : [], [doc]);
  useEffect(() => {
    if (!doc) return;
    const tested = famList.find(([, v]) => v.level !== "L0_INVENTORY_ONLY");
    const classified = famList.find(([, v]) => !v.unclassified && v.archetype);
    setFam((tested || classified || famList[0] || [])[0] || null); setOpen(null);
  }, [doc]);
  const rec = doc && fam ? doc.families[fam] : null;
  useEffect(() => { setArchKey(rec ? rec.archetype : null); setOpen(null); }, [fam, doc]);
  const archName = rec && rec.archetypes.includes(archKey) ? archKey : (rec ? rec.archetype : null);
  const arch = archName ? doc.archetypes[archName] : null;
  const bp = rec && rec.blueprint ? doc.blueprints[rec.blueprint] : null;
  const archPaths = arch ? arch.paths.map(p => ({id: p, ...doc.paths[p]})) : [];
  const paths = archPaths.filter(p => p.evidenced_families.includes(fam));
  const level = paths.length ? paths.map(p => p.level).sort((a, b) => b.localeCompare(a))[0] : "L0_INVENTORY_ONLY";
  const defs = doc ? doc.inputs : {};
  const inputs = (arch ? arch.inputs : (bp ? bp.inputs.map(i => ({...i, tested: false, evidence: []})) : [])).map(i => ({...defs[i.id], ...i, availability: {...(defs[i.id]?.availability || {overall: "UNKNOWN", model_use: "UNKNOWN", registry: [], free_sources: []})}}));
  const shown = inputs.filter(i => filter === "all" || (filter === "tested" ? i.tested : filter === "untested" ? !i.tested : filter === "missing" ? ["NOT_IN_REGISTRY", "NO_FREE_SOURCE_FOUND", "NO_REFERENCE_FOUND", "SOURCE_AVAILABLE_NOT_COLLECTED"].includes(i.availability.overall) : i.availability.model_use.startsWith("USED")));
  const myQueue = queue.items.filter(q => q.sport === sport).slice(0, 5);
  const idx = index.sports[sport];

  return <>
  <DataFoundation/>
  <CatalogCompleteness/>
  <MarketInputMap/>
  <section className="ir" aria-label="Input research: what predicts each market">
    <div className="eyebrow">INPUT RESEARCH / WHAT PREDICTS EACH MARKET</div>
    <h2>Which inputs predict the market, how much, and does the combination beat the price?</h2>
    <p className="ir-fine"><b>RESEARCH ONLY.</b> {index.notice} Data vintage: latest completed game {index.vintage.latest_completed_game}; generated {index.generated_utc}. Evidence levels: {Object.values(LV).join(" › ")}.</p>
    <FoundationAudit/>
    <MarketUniverse/>
    <div className="ir-sports" role="tablist" aria-label="Sport">
      {sports.map(s => {
        const d = index.sports[s]; const tested = d.families - d.levels.L0_INVENTORY_ONLY;
        return <button key={s} role="tab" aria-selected={s === sport} className={"ir-sport" + (s === sport ? " on" : "")} onClick={() => setSport(s)}>
          <strong>{s}</strong><small>{d.families} families · {d.catalog.inputs} candidate inputs</small><small>{tested} with a predictive test</small></button>;
      })}
    </div>
    {sport === "SOCCER" && <SoccerSearch/>}
    {doc && <UnregisteredArchetypes doc={doc} sport={sport}/>}
    <DataReadinessPanel sport={sport}/>
    <ComputableInputsPanel sport={sport}/>
    <ScaledSearchPanel/>
    {!doc ? <p className="ir-fine">Loading {sport}…</p> : <>
      <div className="ir-pick">
        <label>Market family
          <select value={fam || ""} onChange={e => { setFam(e.target.value); setOpen(null); }}>
            {famList.map(([k, v]) => <option key={k} value={k}>{k} — {(v.markets_now ?? 0).toLocaleString()} markets — {LV[v.level].split(" ").slice(0, 2).join(" ")}{v.archetypes.length > 1 ? ` · ${v.archetypes.length} archetypes` : ""}</option>)}
          </select></label>
        {rec && rec.archetypes.length > 1 && <label>Market archetype within this family
          <select value={archName || ""} onChange={e => setArchKey(e.target.value)}>{rec.archetypes.map(a => <option key={a} value={a}>{doc.archetypes[a].label} {doc.archetypes[a].paths.length ? "(tested)" : "(untested)"}</option>)}</select></label>}
        {rec && <span><Chip kind={level}>{LV[level]}</Chip> <Chip kind="plain">{arch ? "archetype: " + arch.label : "blueprint-level inventory: " + rec.blueprint}</Chip></span>}
      </div>
      {rec && <>
        {!arch && !bp && <p className="ir-fine ir-warn"><b>Unclassified family.</b> The registry has no blueprint for {fam}, so no candidate inputs are defined: this is a research gap, not an absence of drivers.</p>}
        {(arch || bp) && <p className="ir-mech"><b>Mechanism.</b> {arch ? arch.mechanism : bp.mechanism}</p>}
        {(arch || bp) && <p className="ir-fine"><b>Settles on:</b> {arch ? arch.target : bp.target}. {level === "L0_INVENTORY_ONLY" ? "No predictive test has been run for this family: the list below is a hypothesis inventory with an availability audit." : ""}</p>}
        {paths.map(p => <PathCard key={p.id} p={p}/>)}
        {fam === "NFL/PLAYER_STAT" && archName === "qb_passing_yards" && <><KalshiExperiment/><SearchResult/></>}
        {fam === "NFL/GAME_WINNER" && <GameWinnerExperiment/>}
        {level === "L0_INVENTORY_ONLY" && archPaths.length > 0 && <p className="ir-fine ir-warn">Related tested paths for this archetype ({archPaths.map(p => p.title).join("; ")}) cover other families; their results are NOT transferred to {fam}.</p>}
        <h4>Candidate inputs ({inputs.length}) — rationale, availability, model use and evidence</h4>
        <p className="ir-fine"><b>How to read this:</b> every input is a <b>hypothesis</b> unless it carries a verdict. <i>Untested</i> = no predictive test exists. A verdict only ever refers to the benchmark named on the path card (a near-close sportsbook line or a QB's own history), <b>never to a Kalshi price</b>. {inputs.filter(i => i.tested).length} of {inputs.length} inputs here have been tested; {inputs.filter(i => i.evidence.some(e => e.verdict === "DEMONSTRATED_INCREMENTAL")).length} show a demonstrated incremental effect against that benchmark; 0 beat a Kalshi price (not tested).</p>
        <div className="ir-filter" role="group" aria-label="Filter inputs">{[["all", "All"], ["tested", "Tested"], ["untested", "Untested"], ["missing", "Missing / unsourced"], ["used", "Used by current model"]].map(([k, l]) =>
          <button key={k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>{l}</button>)}</div>
        <div className="ir-scroll"><table className="ir-table">
          <thead><tr><th>Input (role)</th><th>Availability</th><th>Current model</th><th>Pregame</th><th>Evidence (walk-forward)</th></tr></thead>
          <tbody>{shown.map(i => <React.Fragment key={i.id}>
            <tr className={open === i.id ? "on" : ""}>
              <td><button className="ir-link" onClick={() => setOpen(open === i.id ? null : i.id)} aria-expanded={open === i.id}>{i.label}</button> <small>({i.role || "–"})</small><div className="ir-why">{i.why}</div></td>
              <td><Chip kind={i.availability.overall}>{nice(i.availability.overall)}</Chip>{i.availability.research_path && <small> {pct(i.availability.research_path.mean_coverage)} complete, latest game {String(i.availability.research_path.latest_game).slice(0, 10)}</small>}</td>
              <td><small>{i.availability.model_use}</small></td>
              <td><small>{i.availability.pregame_knowable}</small></td>
              <td>{i.evidence && i.evidence.length ? i.evidence.map(e => <div key={e.path + e.feature}><VerdictChip v={e.verdict}/> <small>{e.feature}{e.pit === "partial" ? " [partial pregame]" : ""}: q={f(e.q_bh, 2)}, {e.weight_reliable ? `weight/SD ${f(e.weight_per_sd, 2)} ${ci(e.weight_ci95)}` : "weight not reliable (no demonstrated effect)"}</small></div>) : <VerdictChip v={null}/>}</td>
            </tr>
            {open === i.id && <tr className="ir-open"><td colSpan={5}>
              {i.mechanism && <p><b>Mechanism.</b> {i.mechanism}</p>}{i.rationale && <p><b>Rationale.</b> {i.rationale}</p>}{i.measurement && <p><b>How to measure.</b> {i.measurement}</p>}
              <p className="ir-fine"><b>Free sources:</b> {(i.availability.free_sources || []).join("; ") || "–"}</p>
              {(i.availability.registry || []).map(r => <p className="ir-fine" key={r.registry_id}><b>Registry {r.registry_id}:</b> collection {nice(r.collection)}; model use {nice(r.model_use)}{r.first_failure ? "; first gap: " + r.first_failure : ""}{r.note ? " — " + r.note : ""}</p>)}
              {(i.availability.related_registry_context || []).map(r => <p className="ir-fine" key={r.registry_id}><b>Related (not identical) registry input {r.registry_id}:</b> collection {nice(r.collection)}; model use {nice(r.model_use)} — context only, NOT counted as collected or used for this input.</p>)}
              {(i.availability.registry || []).length === 0 && <p className="ir-fine">Not itself in the committed input registry: no collector or model-use record exists for this exact input.</p>}
              {i.evidence && i.evidence.map(e => <p className="ir-fine" key={e.path + e.feature}><b>{e.path}:{e.feature}</b> — PIT {e.pit}, coverage {pct(e.coverage)}, nominal p {f(e.p, 2)}, BH q {f(e.q_bh, 2)}, effect {f(e.gain, 2)} (% of baseline error, or log-loss for moneyline).</p>)}
            </td></tr>}
          </React.Fragment>)}</tbody></table></div>
        {bp && <details className="ir-fine"><summary><b>Parent blueprint "{rec.blueprint}"</b>: {bp.inputs.length} candidate inputs and {bp.interactions.length} interactions hypothesised for the whole class of markets (hypotheses only)</summary>
          <p>{bp.mechanism}</p>
          <ul>{bp.inputs.map(i => <li key={i.id}><b>{defs[i.id]?.label || i.id}</b> ({i.role || "–"}): {i.why}</li>)}</ul>
          <ul>{bp.interactions.map((x, k) => <li key={k}><b>{x.inputs.join(" × ")}</b>: {x.hypothesis}</li>)}</ul>
          {arch && arch.blueprint_exclusions && arch.blueprint_exclusions.length > 0 && <p data-testid="blueprint-exclusions"><b>Parent-blueprint interactions that do NOT apply to this archetype ({arch.blueprint_exclusions.length}):</b> {arch.blueprint_exclusions.map(x => x.inputs.join(" × ") + " (" + x.reason + ")").join("; ")}</p>}</details>}
        {arch && <><h4>Interactions hypothesised ({arch.interactions.length})</h4><ul className="ir-fine">{arch.interactions.map((x, k) => <li key={k}><b>{x.inputs.join(" × ")}</b>: {x.hypothesis}</li>)}</ul></>}
        <h4>Gaps and what Alpha should research next</h4>
        <ul className="ir-fine">
          <li>{inputs.filter(i => !i.tested).length} of {inputs.length} candidate inputs are UNTESTED for this family; {inputs.filter(i => ["NOT_IN_REGISTRY", "NO_FREE_SOURCE_FOUND", "NO_REFERENCE_FOUND"].includes(i.availability.overall)).length} are not in the registry or have no free source found; {inputs.filter(i => i.availability.model_use.startsWith("USED")).length} are recorded as used by the current model.</li>
          {myQueue.map(q => <li key={q.id}><b>#{q.rank} {q.label}</b> ({nice(q.status)}): {q.question} <i>First step: {q.first_step}</i></li>)}
        </ul>
      </>}
    </>}
    <details className="ir-fine"><summary>Global research queue (highest-value unanswered questions, ranked by market size × evidence gap × feasibility)</summary>
      <ol>{queue.items.slice(0, 15).map(q => <li key={q.id}><b>{q.sport} · {q.label}</b> — score {q.score}: {q.question}</li>)}</ol></details>
    <p className="ir-fine">Catalog quality ({sport}): {doc ? pct(doc.catalog_quality.share_formulaic) : "–"} of per-market rationale strings are formulaic/machine-padded; treat the catalog as hypotheses to review, not settled reasoning.</p>
    <p className="ir-fine">{idx.families} {sport} families · {idx.markets_now.toLocaleString()} live markets in the last inventory · levels: {Object.entries(idx.levels).filter(([, n]) => n).map(([k, n]) => `${n} ${LV[k].split(" ").slice(0, 2).join(" ")}`).join(", ")}</p>
  </section>
  </>;
}

function PathCard({p}) {
  const r = p.result; const hm = r.headline_models; const best = hm.ridge_all || hm.logit_all;
  const base = r.baselines;
  return <div className="ir-path">
    <h4>{p.title} <Chip kind={p.level}>{LV[p.level]}</Chip></h4>
    <p className="ir-fine ir-warn"><b>Claim boundary:</b> {p.claim_boundary}</p>
    <p className="ir-fine"><b>Benchmark:</b> {p.benchmark}</p>
    {p.sample_note && <p className="ir-fine"><b>Sample note:</b> {p.sample_note}</p>}
    <p className="ir-fine"><b>Pregame discipline:</b> the headline model uses only inputs knowable before the decision. {(r.partial_pit_inputs || []).length > 0 ? `Partially-knowable inputs (${r.partial_pit_inputs.join(", ")}) — the realised starter and observed weather/roof state — are tested separately and excluded from the headline.` : ""} {(hm.sensitivity_incl_partial_inputs && hm.sensitivity_incl_partial_inputs.ridge) ? `Sensitivity incl. partial inputs: MSE gain ${f(hm.sensitivity_incl_partial_inputs.ridge.mse_gain_vs_baseline, 3)} ${ci(hm.sensitivity_incl_partial_inputs.ridge.ci95)} — not a pregame claim.` : ""} {hm.sensitivity_incl_partial_inputs && hm.sensitivity_incl_partial_inputs.logloss_gain_vs_market != null ? `Sensitivity incl. partial inputs: log-loss gain ${f(hm.sensitivity_incl_partial_inputs.logloss_gain_vs_market, 2)} ${ci(hm.sensitivity_incl_partial_inputs.ci95)} — not a pregame claim.` : ""}</p>
    <p className="ir-fine"><b>Scope:</b> {p.scope_note}</p>
    <p className="ir-fine"><b>Validation:</b> expanding-window by season (train on earlier seasons only, penalty chosen on the last training season); {r.n_test_rows.toLocaleString()} out-of-sample rows, seasons {r.test_seasons[0]}–{r.test_seasons[r.test_seasons.length - 1]}, {r.n_week_clusters} week clusters (cluster bootstrap); Holm control over groups/interactions, Benjamini–Hochberg over single inputs.</p>
    <div className="ir-cards">
      {r.kind === "moneyline" ? <>
        <div><b>{f(base.market_devig.logloss, 4)}</b><small>de-vigged close log-loss</small></div>
        <div><b>{f(best.logloss_model, 4)}</b><small>all-inputs model log-loss</small></div>
        <div><b>{f(best.logloss_gain_vs_market, 2)} {ci(best.ci95)}</b><small>log-loss gain vs close (positive = better)</small></div>
      </> : <>
        <div><b>{f((base.B0_market_line || {}).mse, 4)}</b><small>{(r.benchmark_names || {}).B0 || "benchmark"} MSE</small></div>
        <div><b>{f((base.ALL_FEATURES_RIDGE || {}).mse, 4)}</b><small>all-inputs ridge MSE</small></div>
        <div><b>{f(best.mse_gain_vs_baseline, 3)} {ci(best.ci95)}</b><small>MSE gain vs strict baseline (positive = better)</small></div>
        <div><b>{f((hm.gbm_all || {}).mse_gain_vs_baseline, 3)}</b><small>gradient-boosting gain (nonlinear/interactions)</small></div>
      </>}
      <div><VerdictChip v={best.verdict}/><small>headline verdict · halves {best.halves ? best.halves.map(x => f(x, 2)).join(" / ") : "–"}</small></div>
    </div>
    {r.standalone && <p className="ir-fine"><b>Importance without any market:</b> all inputs explain {pct(r.standalone.all_features_r2_vs_no_information)} of out-of-sample outcome variance vs a no-information mean; the benchmark itself explains {pct(r.standalone.market_r2_vs_no_information)}. {r.standalone.market_r2_vs_no_information > r.standalone.all_features_r2_vs_no_information ? "The benchmark already contains more than the inputs add." : ""}</p>}
    {r.probability && <p className="ir-fine"><b>Probability scoring vs {r.probability.market_price_source}:</b> log-loss gain {f(r.probability.models.ridge_all.logloss_gain.mean, 2)} {ci(r.probability.models.ridge_all.logloss_gain["ci_0.05"])} (n={r.probability.n_scored_non_push}); model calibration slope {f(r.probability.models.ridge_all.calibration.slope, 2)}.</p>}
    {r.latest_season_holdout && <p className="ir-fine"><b>Forward slice:</b> {r.latest_season_holdout.season} season to date (n={r.latest_season_holdout.n}) — MSE benchmark {f(r.latest_season_holdout.mse_B0_market, 4)} vs ridge {f(r.latest_season_holdout.mse_ridge_all, 4)}.</p>}
    <details className="ir-fine"><summary>Input groups: standalone importance, incremental gain, necessity, and tested interactions</summary>
      <div className="ir-scroll"><table className="ir-table"><thead><tr><th>Group</th><th>Standalone R² (no market)</th><th>Incremental vs benchmark</th><th>Verdict</th><th>Seasons +</th></tr></thead>
        <tbody>{Object.entries(r.groups).map(([g, v]) => <tr key={g}><td>{nice(g)}</td><td>{v.standalone_r2 == null ? "–" : pct(v.standalone_r2)}</td>
          <td>{f(v.pct_of_baseline_mse ?? v.logloss_gain_vs_recalibrated_market, 2)} {ci(v.ci95)}{v.contains_partial_pit_inputs ? " (includes partial-pregame inputs)" : ""}</td><td><VerdictChip v={v.verdict}/></td><td>{v.seasons_positive}/{v.seasons_total}</td></tr>)}</tbody></table></div>
      {r.interactions && Object.keys(r.interactions).length > 0 && <ul>{Object.entries(r.interactions).map(([k, v]) => <li key={k}><b>{v.label}</b>: gain {f(v.mse_gain_vs_main_effects, 2)} {ci(v.ci95)}, Holm p {f(v.holm_p, 2)} <VerdictChip v={v.verdict}/> — {v.hypothesis}</li>)}</ul>}
    </details>
  </div>;
}
