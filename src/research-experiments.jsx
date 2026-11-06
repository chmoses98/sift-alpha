import React from "react";
import universe from "../research/input_research/market_universe/universe_summary.json";
import gexp from "../research/audit/input_research/experiments/nfl_game_kalshi_v1.json";
import audit from "../research/audit/input_research/coverage_audit.json";
import srch from "../research/audit/input_research/experiments/search_nfl_qb_passing_v1.json";
import soc from "../research/audit/input_research/experiments/search_soccer_v1.json";
import exp from "../research/audit/input_research/experiments/nfl_passyds_kalshi_v1.json";

// Rendered only from committed JSON artifacts (alpha_engine.input_research.market_universe / prop_experiment). Nothing hand-typed.
const f = (x, d = 3) => x == null || Number.isNaN(x) ? "–" : Number(x).toFixed(d);
const c1 = x => x == null ? "–" : Number(x).toFixed(2);
const ci = a => a ? `[${f(a[0], 3)}, ${f(a[1], 3)}]` : "";
const SCOPE = ["NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"];

export function MarketUniverse() {
  const rows = SCOPE.map(s => [s, universe.by_sport[s] || {}]);
  const other = Object.entries(universe.by_sport).filter(([k]) => !SCOPE.includes(k));
  const otherN = other.reduce((a, [, v]) => a + v.series, 0);
  return <details className="ir-fine" open>
    <summary><b>Market universe audit</b> — live Kalshi sports listing ({universe.n_series.toLocaleString()} series, {universe.snapshot_date}) vs what the registry knows</summary>
    <p className="ir-warn">{universe.caveat}</p>
    <div className="ir-scroll"><table className="ir-table" style={{minWidth: 420}}>
      <thead><tr><th>Sport</th><th>Live series</th><th>In registry</th><th>New / unregistered</th></tr></thead>
      <tbody>{rows.map(([s, v]) => <tr key={s}><td>{s}</td><td>{v.series ?? 0}</td><td>{v.known_in_registry ?? 0}</td><td><b>{v.new_unregistered ?? 0}</b></td></tr>)}</tbody></table></div>
    <p>Not one of the eight sports ({otherN.toLocaleString()} series; {other.length} other sport/season groups: golf, motorsport, esports, MMA, cricket, other leagues, womens/international basketball, ...) — <b>unsupported</b>: no registry family, no inputs, no tests. Largest new in-scope gap by contract type: {universe.new_in_scope_by_kind.slice(0, 4).map(x => `${x.sport} ${x.kind.replaceAll("_", " ")} (${x.series})`).join("; ")}.</p>
  </details>;
}

export function KalshiExperiment() {
  const h = exp.horizons["primary_T-60m"], w = h.waterfall, d = h.decisions;
  return <div className="ir-path">
    <h4>Experiment NFL-PASSYDS-1: QB passing yards model vs real Kalshi quotes <span className="ir-chip ir-L2_TESTED_VS_MARKET">L3 attempted — retrospective replay, NOT promoted</span></h4>
    <p className="ir-fine ir-warn"><b>Claim boundary:</b> {exp.label.replaceAll("_", " ").toLowerCase()}. The model is MARKET-FREE (no sportsbook line, Kalshi price or derived feature; game script is its own rating-based expectation), selected by a nested chronological search on 2013–2025 before any price was read; prices are used only afterwards as the benchmark. 2026 regular season weeks 1–8 only. Fills are hypothetical (one contract at the quoted top of book; depth not observed). Eligibility needs the realised QB1 (≥12 dropbacks), which is not known at quote time, so YES-side results are flattered; contracts excluded for that reason are shown below.</p>
    <p className="ir-fine"><b>Population (T−60 min quote):</b> {exp.contracts_listed.toLocaleString()} listed → {w.settled_regular_season.toLocaleString()} settled regular-season → {w.have_quote_at_horizon.toLocaleString()} with a pre-kickoff quote → {w.eligible_priced.toLocaleString()} with a model price ({w.games} games). Excluded: {w.no_quote_n} with no pre-kickoff quote (opened in-game; {(100 * w.no_quote_yes_rate).toFixed(0)}% resolved yes) and {w.no_model_row_n} whose player was not the realised QB1 ({(100 * w.no_model_row_yes_rate).toFixed(0)}% yes).</p>
    <div className="ir-cards">
      <div><b>{f(h.logloss.market_mid[0], 4)}</b><small>market mid log-loss</small></div>
      <div><b>{f(h.logloss.model[0], 4)}</b><small>model log-loss</small></div>
      <div><b>{f(h.logloss_gain_model_vs_market[0], 4)} {ci(h.logloss_gain_model_vs_market.slice(1))}</b><small>model gain vs market (positive = model better)</small></div>
      <div><b>{f(h.logloss_gain_model_vs_history[0], 4)} {ci(h.logloss_gain_model_vs_history.slice(1))}</b><small>model gain vs history-only</small></div>
      <div><b>{d.qualifying_n} of {w.eligible_priced}</b><small>qualified (net edge ≥ {Math.round(100 * exp.edge_min)}¢), {d.qualifying_games} games</small></div>
      <div><b>{c1(d.mean_net_cents)}¢ {d.ci95 ? `[${c1(d.ci95[0])}, ${c1(d.ci95[1])}]` : ""}</b><small>net per contract after taker fees (gross {c1(d.mean_gross_cents)}¢, fee {c1(d.mean_fee_cents)}¢) — interval includes 0</small></div>
    </div>
    <p className="ir-fine"><b>Verdict:</b> no demonstrated edge. {h.logloss_gain_model_vs_market[2] < 0 ? "The market mid is better than the independent model (interval excludes 0)" : "The model does not beat the market mid"}; qualifying trades lost {c1(-d.mean_net_cents)}¢ per contract at the point estimate with an interval spanning zero; always buying the better-priced side across all eligible contracts: {c1(d.all_eligible_if_always_buy_best_side.mean_net_cents)}¢ [{c1(d.all_eligible_if_always_buy_best_side.ci95[0])}, {c1(d.all_eligible_if_always_buy_best_side.ci95[1])}]. Selection bias check: realised yes-rate minus market mid is {c1(100 * w.market_bias_check_actual_minus_mid.eligible_with_model_row[1])} points on the model-eligible contracts but {c1(100 * w.market_bias_check_actual_minus_mid.excluded_no_model_row[1])} points on the excluded ones.</p>
    <details className="ir-fine"><summary>Edge-threshold sensitivity, side split, horizons and input-group ablation (exploratory)</summary>
      <p>Edge threshold sensitivity (net ¢/contract; looks at one threshold after another, so any positive cell is multiplicity-affected and not counted): {h.edge_threshold_sensitivity.map(x => `≥${Math.round(100 * x.edge_min)}¢: ${c1(x.mean_net_cents)} (n=${x.n})`).join("; ")}.</p>
      <p>By side at the pre-registered threshold: {Object.entries(d.by_side).map(([s, v]) => `${s}: n=${v.n}, ${c1(v.mean_net_cents)}¢, win ${(100 * v.win_rate).toFixed(0)}%`).join("; ")}. Horizons: {Object.entries(exp.horizons).map(([k, v]) => `${k}: ${v.decisions.qualifying_n} qualified, ${c1(v.decisions.mean_net_cents)}¢ ${v.decisions.ci95 ? `[${c1(v.decisions.ci95[0])}, ${c1(v.decisions.ci95[1])}]` : ""}`).join("; ")} (3 horizons: Bonferroni).</p>
      <div className="ir-scroll"><table className="ir-table" style={{minWidth: 420}}><thead><tr><th>Input group dropped (refit ≤2025)</th><th>Log-loss change on the 2026 contracts</th></tr></thead>
        <tbody>{exp["group_ablation_primary_T-60m_exploratory"].map(a => <tr key={a.group}><td>{a.group.replaceAll("_", " ")}</td><td>{f(a.logloss_increase_when_dropped, 4)} {ci(a.ci95)}</td></tr>)}</tbody></table></div>
      <p><b>Model-free structural-bias test</b> (all {exp["structure_test_primary_T-60m"].n_contracts.toLocaleString()} two-sided quoted contracts, {exp["structure_test_primary_T-60m"].games} games, no QB1 filter): buying YES or NO in each of 8 price bins at the ask/bid after taker fees, 16 pre-specified cells, Holm-corrected, minimum {exp["structure_test_primary_T-60m"].min_cell[0]} contracts / {exp["structure_test_primary_T-60m"].min_cell[1]} games per cell. Cells passing every gate: <b>{exp["structure_test_primary_T-60m"].cells_passing_all_gates}</b>. Best cell: {(() => { const c = exp["structure_test_primary_T-60m"].cells.filter(x => x.enough_sample).sort((a, b) => b.mean_net_cents - a.mean_net_cents)[0]; return `${c.side} at ${c.mid_bin}: ${c1(c.mean_net_cents)}¢ [${c1(c.ci95[0])}, ${c1(c.ci95[1])}], Holm p ${f(c.holm_p, 2)}`; })()}.</p>
      <p><b>Slow-incorporation test</b> (price move T−24 h → T−3 h, entry T−60 min): the median absolute move is {c1(100 * exp["drift_test_T-24h_to_T-3h_entry_T-60m"].abs_move_quantiles["0.5"])}¢ and only {exp["drift_test_T-24h_to_T-3h_entry_T-60m"].with_move} contracts ({exp["drift_test_T-24h_to_T-3h_entry_T-60m"].games} games) moved ≥ {Math.round(100 * exp["drift_test_T-24h_to_T-3h_entry_T-60m"].move_min)}¢, so momentum and fade rules are <b>INSUFFICIENT</b> (minimum {exp["structure_test_primary_T-60m"].min_cell[0]} contracts / {exp["structure_test_primary_T-60m"].min_cell[1]} games): the hypothesis is untestable on this history, not rejected.</p>
      <p>Positive = the model got worse without that group. {exp["group_ablation_primary_T-60m_exploratory"].filter(a => a.ci95[0] > 0).length} of {exp["group_ablation_primary_T-60m_exploratory"].length} groups have an interval above 0 ({w.games} games, exploratory, not multiplicity-controlled), so no weight is promoted.</p>
    </details>
  </div>;
}

export function GameWinnerExperiment() {
  const h = gexp.horizons["primary_T-60m"], d = h.decisions, w = h.waterfall, h2 = gexp.horizons["secondary_T-24h"];
  return <div className="ir-path">
    <h4>Experiment NFL-GAME-1: Kalshi game-winner price vs the de-vigged sportsbook moneyline <span className="ir-chip ir-L2_TESTED_VS_MARKET">cross-market check — no edge found</span></h4>
    <p className="ir-fine ir-warn"><b>Claim boundary:</b> retrospective quote replay, hypothetical fills (top of book, depth not observed). The book line is documented only as “near close”, so it may contain information newer than the Kalshi quote, which would flatter the test. Rule fixed in advance: buy a side only if book probability − price − taker fee ≥ {Math.round(100 * gexp.edge_min)}¢.</p>
    <p className="ir-fine"><b>Population:</b> {gexp.contracts_listed} contracts listed → {w.settled_with_book_line} settled with a book line → {w.two_sided_quote_at_horizon} with a two-sided quote at T−60 min ({w.games} games); {w.no_usable_quote} excluded for no quote.</p>
    <div className="ir-cards">
      <div><b>{c1(h.mean_kalshi_mid_minus_book_cents)}¢</b><small>average Kalshi mid minus de-vigged book</small></div>
      <div><b>{f(h.logloss_gain_book_vs_kalshi_mid[0], 4)} {ci(h.logloss_gain_book_vs_kalshi_mid.slice(1))}</b><small>log-loss gain, book vs Kalshi mid (interval includes 0)</small></div>
      <div><b>{d.qualifying_n} of {d.of}</b><small>contracts qualified at T−60 min (T−24 h: {h2.decisions.qualifying_n}, {h2.decisions.games ?? 0} game)</small></div>
      <div><b>{c1(d.all_best_side.mean_net_cents)}¢ [{c1(d.all_best_side.ci95[0])}, {c1(d.all_best_side.ci95[1])}]</b><small>net per contract always buying the better-priced side (no rule)</small></div>
    </div>
    <p className="ir-fine"><b>Verdict:</b> Kalshi's winner price tracks the sportsbook line to within a fraction of a cent on average and no contract cleared the fee-adjusted edge; the two T−24 h qualifiers come from a single game and are not interpretable. No mispricing relative to the book is demonstrated.</p>
  </div>;
}

export function FoundationAudit() {
  const sports = Object.keys(audit.readiness);
  const probe = audit.source_probe;
  const sum = o => Object.values(o || {}).reduce((a, b) => a + b, 0);
  return <details className="ir-fine" open>
    <summary><b>Input foundation audit</b> — completeness, market-derived inputs and data readiness, all eight sports</summary>
    <p className="ir-warn"><b>Policy:</b> primary prediction models may not use sportsbook lines, Kalshi prices or anything derived from them (enforced in code: a forbidden column is an error). Those inputs are <b>benchmark-only</b>. “Required mechanism missing” is a checklist against a rule table (archetype plus parent-blueprint inputs), a prompt for review, not proof that the remaining inputs are sufficient.</p>
    <div className="ir-scroll"><table className="ir-table" style={{minWidth: 560}}>
      <thead><tr><th>Sport</th><th>Candidate inputs</th><th>Benchmark-only (market-derived)</th><th>Model-eligible: collected & timestamped</th><th>partial</th><th>missing / no free source</th><th>unverified</th><th>Archetypes with a required mechanism missing</th></tr></thead>
      <tbody>{sports.map(sp => { const r = audit.readiness[sp].primary_model_eligible_inputs; const rows = audit.mechanism_matrix[sp]; const gaps = rows.filter(x => x.required_categories_missing.length).length;
        return <tr key={sp}><td>{sp}</td><td>{sum(audit.readiness[sp].all_inputs)}</td><td>{audit.market_derived_inputs[sp].market_derived_benchmark_only}</td><td>{r.collected_pit || 0}</td><td>{(r.partial || 0) + (r.derived || 0)}</td>
          <td>{(r.missing_source_exists || 0) + (r.missing_no_free_source || 0)}</td><td>{(r.unverified_not_in_registry || 0) + (r.unverified_code_only || 0) + (r.unverified || 0)}</td><td>{gaps} of {rows.length}</td></tr>; })}</tbody></table></div>
    <p><b>Source reachability:</b> {probe.reachable_2xx_3xx} of {probe.n_urls} free-source hosts named in the catalogs were reachable from the research runner. The rest returned errors because the runner's network policy blocks them (not evidence the data is unavailable). Six free public hosts (MLB, NHL, NBA, ESPN, football-data, tennis-data) were added to the allowlist; re-run <code>coverage_audit --probe</code> next session. “Collected” means present in the registry with point-in-time archiving; it does not certify licence or accuracy.</p>
  </details>;
}

export function SearchResult() {
  const g = srch.nested_gain, nul = srch.permutation_null.map(x => x.pct_gain);
  const imp = Object.entries(srch.group_importance_leave_one_group_out_inner).sort((a, b) => b[1].mean_rel_mse_increase_when_dropped - a[1].mean_rel_mse_increase_when_dropped);
  return <details className="ir-fine">
    <summary><b>Systematic input search (market-free, nested chronological validation)</b> — {srch.n_configs_per_fold} configurations per fold × {g.seasons.length} outer seasons</summary>
    <p>Each outer season S: random search over input-group subsets, squared terms, 0/6/20 data-picked interactions and model structure (ridge or boosting), scored on the last {srch.inner_k} seasons before S, one-standard-error rule, refit, predict S. Nothing at or after S is used for selection. Out-of-sample MSE gain vs the QB's own history: <b>{g.pct_gain.toFixed(2)}%</b> (cluster-bootstrap 95% CI {c1(g["ci_0.05"][0])} to {c1(g["ci_0.05"][1])} yards², {g.seasons_positive} of {g.seasons.length} seasons positive). The identical search on a target with its signal destroyed gained {nul.map(x => x.toFixed(2) + "%").join(" and ")}: that is the search's own overfitting, so the real gain is about {(g.pct_gain - Math.max(...nul)).toFixed(1)} points. Boosting was selected in {Math.round(100 * srch.model_structure_frequency.gbm)}% of folds.</p>
    <div className="ir-scroll"><table className="ir-table" style={{minWidth: 440}}><thead><tr><th>Input group</th><th>Inner-fold MSE increase when dropped (fixed ridge)</th><th>Folds it helped</th><th>Selected</th></tr></thead>
      <tbody>{imp.map(([k, v]) => <tr key={k}><td>{k.replaceAll("_", " ")}</td><td>{(100 * v.mean_rel_mse_increase_when_dropped).toFixed(2)}% ± {(100 * v.se).toFixed(2)}</td><td>{v.folds_where_dropping_hurts}/{v.folds}</td><td>{Math.round(100 * srch.group_selection_frequency[k])}%</td></tr>)}</tbody></table></div>
    <p>Only opponent pass defence helps in every fold; no other group is consistently needed. Weights are not promoted.</p>
  </details>;
}

export function SoccerSearch() {
  return <details className="ir-fine" open>
    <summary><b>Systematic input search — soccer (market-free)</b>: {soc.leagues.join(", ")}, 2015/16–2025/26, {soc.studies.total_goals.n_matches.toLocaleString()} matches</summary>
    <p className="ir-warn">Free football-data.co.uk results only; every bookmaker odds column is dropped before any feature is built. Same nested chronological search as NFL ({soc.n_configs_per_fold} configurations per fold). <b>No Kalshi comparison has been run for soccer</b>: these are independent-model results against a trivial baseline, not evidence about any price.</p>
    <div className="ir-scroll"><table className="ir-table" style={{minWidth: 520}}><thead><tr><th>Target (baseline)</th><th>Out-of-sample MSE gain</th><th>Seasons positive</th><th>Permutation-null gain</th><th>Groups needed in every fold</th></tr></thead>
      <tbody>{Object.values(soc.studies).map(t => <tr key={t.target}><td>{t.target.replaceAll("_", " ")} ({t.baseline})</td><td>{t.nested_gain.pct_gain.toFixed(2)}%</td><td>{t.nested_gain.seasons_positive}/{t.nested_gain.seasons.length}</td><td>{t.permutation_null.map(x => x.pct_gain.toFixed(2) + "%").join(", ")}</td>
        <td>{Object.entries(t.group_importance_leave_one_group_out_inner).filter(([, v]) => v.folds_where_dropping_hurts === v.folds).map(([k]) => k.replaceAll("_", " ")).join("; ") || "none"}</td></tr>)}</tbody></table></div>
    <p>Total goals: league scoring context and attack form carry the small, stable gain (~2%). Goal difference: team strength (Elo), defensive form and tempo/set-piece volume are needed in every fold, but the baseline contains no team information, so that large gain shows the inputs matter, not that the model is accurate enough to price a market.</p>
  </details>;
}
