import React from "react";
import universe from "../research/input_research/market_universe/universe_summary.json";
import gexp from "../research/audit/input_research/experiments/nfl_game_kalshi_v1.json";
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
    <p className="ir-fine ir-warn"><b>Claim boundary:</b> {exp.label.replaceAll("_", " ").toLowerCase()}. Model frozen on 2013–{2025} before any price was read; 2026 regular season weeks 1–8 only. Fills are hypothetical (one contract at the quoted top of book; depth not observed). Eligibility needs the realised QB1 (≥12 dropbacks), which is not known at quote time, so YES-side results are flattered; contracts excluded for that reason are shown below.</p>
    <p className="ir-fine"><b>Population (T−60 min quote):</b> {exp.contracts_listed.toLocaleString()} listed → {w.settled_regular_season.toLocaleString()} settled regular-season → {w.have_quote_at_horizon.toLocaleString()} with a pre-kickoff quote → {w.eligible_priced.toLocaleString()} with a model price ({w.games} games). Excluded: {w.no_quote_n} with no pre-kickoff quote (opened in-game; {(100 * w.no_quote_yes_rate).toFixed(0)}% resolved yes) and {w.no_model_row_n} whose player was not the realised QB1 ({(100 * w.no_model_row_yes_rate).toFixed(0)}% yes).</p>
    <div className="ir-cards">
      <div><b>{f(h.logloss.market_mid[0], 4)}</b><small>market mid log-loss</small></div>
      <div><b>{f(h.logloss.model[0], 4)}</b><small>model log-loss</small></div>
      <div><b>{f(h.logloss_gain_model_vs_market[0], 4)} {ci(h.logloss_gain_model_vs_market.slice(1))}</b><small>model gain vs market (positive = better): not better</small></div>
      <div><b>{f(h.logloss_gain_model_vs_history[0], 4)} {ci(h.logloss_gain_model_vs_history.slice(1))}</b><small>model gain vs history-only (interval includes 0)</small></div>
      <div><b>{d.qualifying_n} of {w.eligible_priced}</b><small>qualified (net edge ≥ {Math.round(100 * exp.edge_min)}¢), {d.qualifying_games} games</small></div>
      <div><b>{c1(d.mean_net_cents)}¢ {d.ci95 ? `[${c1(d.ci95[0])}, ${c1(d.ci95[1])}]` : ""}</b><small>net per contract after taker fees (gross {c1(d.mean_gross_cents)}¢, fee {c1(d.mean_fee_cents)}¢) — interval includes 0</small></div>
    </div>
    <p className="ir-fine"><b>Verdict:</b> no demonstrated edge. The model does not beat the market mid; qualifying trades lost {c1(-d.mean_net_cents)}¢ per contract at the point estimate with an interval spanning zero; always buying the better-priced side across all eligible contracts: {c1(d.all_eligible_if_always_buy_best_side.mean_net_cents)}¢ [{c1(d.all_eligible_if_always_buy_best_side.ci95[0])}, {c1(d.all_eligible_if_always_buy_best_side.ci95[1])}]. Selection bias check: realised yes-rate minus market mid is {c1(100 * w.market_bias_check_actual_minus_mid.eligible_with_model_row[1])} points on the model-eligible contracts but {c1(100 * w.market_bias_check_actual_minus_mid.excluded_no_model_row[1])} points on the excluded ones.</p>
    <details className="ir-fine"><summary>Edge-threshold sensitivity, side split, horizons and input-group ablation (exploratory)</summary>
      <p>Edge threshold sensitivity (net ¢/contract; looks at one threshold after another, so any positive cell is multiplicity-affected and not counted): {h.edge_threshold_sensitivity.map(x => `≥${Math.round(100 * x.edge_min)}¢: ${c1(x.mean_net_cents)} (n=${x.n})`).join("; ")}.</p>
      <p>By side at the pre-registered threshold: {Object.entries(d.by_side).map(([s, v]) => `${s}: n=${v.n}, ${c1(v.mean_net_cents)}¢, win ${(100 * v.win_rate).toFixed(0)}%`).join("; ")}. Horizons: {Object.entries(exp.horizons).map(([k, v]) => `${k}: ${v.decisions.qualifying_n} qualified, ${c1(v.decisions.mean_net_cents)}¢ ${v.decisions.ci95 ? `[${c1(v.decisions.ci95[0])}, ${c1(v.decisions.ci95[1])}]` : ""}`).join("; ")} (3 horizons: Bonferroni).</p>
      <div className="ir-scroll"><table className="ir-table" style={{minWidth: 420}}><thead><tr><th>Input group dropped (refit ≤2025)</th><th>Log-loss change on the 2026 contracts</th></tr></thead>
        <tbody>{exp["group_ablation_primary_T-60m_exploratory"].map(a => <tr key={a.group}><td>{a.group.replaceAll("_", " ")}</td><td>{f(a.logloss_increase_when_dropped, 4)} {ci(a.ci95)}</td></tr>)}</tbody></table></div>
      <p><b>Model-free structural-bias test</b> (all {exp["structure_test_primary_T-60m"].n_contracts.toLocaleString()} two-sided quoted contracts, {exp["structure_test_primary_T-60m"].games} games, no QB1 filter): buying YES or NO in each of 8 price bins at the ask/bid after taker fees, 16 pre-specified cells, Holm-corrected, minimum {exp["structure_test_primary_T-60m"].min_cell[0]} contracts / {exp["structure_test_primary_T-60m"].min_cell[1]} games per cell. Cells passing every gate: <b>{exp["structure_test_primary_T-60m"].cells_passing_all_gates}</b>. Best cell: {(() => { const c = exp["structure_test_primary_T-60m"].cells.filter(x => x.enough_sample).sort((a, b) => b.mean_net_cents - a.mean_net_cents)[0]; return `${c.side} at ${c.mid_bin}: ${c1(c.mean_net_cents)}¢ [${c1(c.ci95[0])}, ${c1(c.ci95[1])}], Holm p ${f(c.holm_p, 2)}`; })()}.</p>
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
