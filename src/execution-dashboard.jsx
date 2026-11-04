import React, {useState} from "react";
import ex from "../research/audit/clv/execution_summary.json";
import "./execution-dashboard.css";

// Everything here is generated from research/audit/clv/execution_summary.json (aggregates only: no stakes, P&L, ROI, tickers,
// contract counts, order ids or per-wager rows). All prices are cents per contract on the PURCHASED side.
const SPORTS = ["NFL", "CFB", "NBA", "NHL"];
const f2 = v => (v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(2));
const cents = v => (v == null ? "—" : f2(v) + "¢");
const int = v => (v == null ? "—" : Number(v).toLocaleString());
const pc = v => (v == null ? "—" : Math.round(100 * v) + "%");
const sign = v => (v == null ? "na" : Math.abs(v) < 0.005 ? "zero" : v > 0 ? "pos" : "neg");
const ci = a => (a ? ` (${f2(a[0])} to ${f2(a[1])})` : "");

function Badge({kind}) {
  return kind === "real"
    ? <span className="ex-badge ex-real" title="Built from the exchange's own fills of owner-placed wagers">VERIFIED ACTUAL TRADES</span>
    : <span className="ex-badge ex-hyp" title="Model selections or simulated orders; nothing here was traded">HYPOTHETICAL</span>;
}

// Diverging bars in cents; the signed value is always printed, so colour is never the only encoding.
function Bars({rows, label}) {
  const vals = rows.flatMap(r => [r.v, ...(r.ci || [])]).filter(x => x != null);
  const max = Math.max(0.5, ...vals.map(Math.abs)) * 1.12;
  const LAB = 330, W = 420, VAL = 74, H = 30, zero = LAB + W / 2, k = (W / 2 - 4) / max;
  return <svg className="ex-bars" viewBox={`0 0 ${LAB + W + VAL} ${rows.length * H + 6}`} role="img" aria-label={label}>
    <line x1={zero} x2={zero} y1="0" y2={rows.length * H + 4} className="ex-axis"/>
    {rows.map((r, i) => {
      const y = i * H + 4, w = r.v == null ? 0 : Math.abs(r.v) * k, x = r.v >= 0 ? zero : zero - w;
      return <g key={r.label} tabIndex="0">
        <title>{`${r.label}: ${cents(r.v)}${r.ci ? ` · 95% CI ${cents(r.ci[0])} to ${cents(r.ci[1])}` : ""}${r.note ? " · " + r.note : ""}`}</title>
        <rect x="0" y={y} width={LAB + W + VAL} height={H - 6} className="ex-hit"/>
        <text x={LAB - 10} y={y + H / 2 - 3} textAnchor="end" className="ex-lab">{r.label.length > 56 ? r.label.slice(0, 55) + "…" : r.label}</text>
        <rect x={x} y={y + 4} width={Math.max(w, 1)} height={H - 14} rx="4" className={"ex-bar ex-" + sign(r.v)}/>
        {r.ci && <g className="ex-whisk"><line x1={zero + r.ci[0] * k} x2={zero + r.ci[1] * k} y1={y + H / 2 - 1} y2={y + H / 2 - 1}/>
          <line x1={zero + r.ci[0] * k} x2={zero + r.ci[0] * k} y1={y + H / 2 - 5} y2={y + H / 2 + 3}/>
          <line x1={zero + r.ci[1] * k} x2={zero + r.ci[1] * k} y1={y + H / 2 - 5} y2={y + H / 2 + 3}/></g>}
        <text x={LAB + W + 8} y={y + H / 2 - 3} className="ex-val">{cents(r.v)}</text>
      </g>;
    })}
  </svg>;
}
const Key = () => <p className="ex-key"><i className="ex-sw ex-pos"/> above zero <i className="ex-sw ex-neg"/> below zero <i className="ex-sw ex-zero"/> ≈ 0 · whisker = 95% interval resampling whole games · each bar is also labelled with its signed value</p>;

function Definitions() {
  return <details className="ex-defs"><summary>What each number means (definitions, denominators, sources)</summary>
    <dl>{Object.entries(ex.metric_definitions).map(([k, v]) => <React.Fragment key={k}><dt>{k.replaceAll("_", " ")}</dt><dd>{v}</dd></React.Fragment>)}</dl>
    <p className="ex-fine">Privacy: {ex.privacy}.</p></details>;
}

function Headline() {
  const b = s => ex.real_wagers[s].measures_cents.executable_purchase_clv;
  return <div className="ex-card ex-lead"><h3>1 · Did we pay less than someone buying at the close?</h3>
    <p className="ex-fine"><Badge kind="real"/> Executable purchase CLV = closing <b>ask</b> of the held side − our actual fee-exclusive fill. Zero means the executable price did not change. A closing <b>bid</b> is never used as a purchase price.</p>
    <Key/>
    <Bars label="Executable purchase CLV versus the closing ask, by sport" rows={SPORTS.map(s => ({label: `${s} (n=${ex.real_wagers[s].denominators.verified_fills}, ${ex.real_wagers[s].denominators.games} games)`, v: b(s).mean, ci: b(s).game_cluster_ci95_cents,
      note: `${Math.round(b(s).zero_pct)}% of fills: executable price unchanged; ${Math.round(b(s).positive_pct)}% cheaper; ${Math.round(b(s).negative_pct)}% dearer`}))}/>
    <p className="ex-take"><b>Reading:</b> {ex.answers["1_price_advantage_vs_closing_ask"].split(". In ")[0]}.</p></div>;
}

function Compare() {
  return <div className="ex-card"><h3>2 · Same fills, three benchmarks, fees shown beside them</h3>
    <p className="ex-fine"><Badge kind="real"/> Midpoint execution CLV is the traditional mark-to-market number and is unchanged. Purchase CLV = midpoint CLV + closing half-spread; liquidation = midpoint CLV − closing half-spread. Fee-adjusted columns subtract the exchange entry fee exactly once.</p>
    <table className="ex-table"><thead><tr><th>Sport</th><th>Verified / eligible</th><th>Purchase vs ask</th><th>Midpoint (traditional)</th><th>Liquidation vs bid</th><th>Closing half-spread</th><th>Entry fee</th><th>Purchase, after fee</th><th>Midpoint, after fee</th><th>Liquidation, after entry + modelled sale fee</th></tr></thead>
      <tbody>{SPORTS.map(s => { const r = ex.real_wagers[s], m = r.measures_cents, d = r.denominators; return <tr key={s}><th scope="row">{s}</th>
        <td>{d.verified_fills} / {d.pregame_entries_eligible}</td><td>{cents(m.executable_purchase_clv.mean)}{ci(m.executable_purchase_clv.game_cluster_ci95_cents)}</td>
        <td>{cents(m.midpoint_execution_clv.mean)}</td><td>{cents(m.liquidation_clv.mean)}</td><td>{r.closing_half_spread_cents_mean.toFixed(2)}¢</td><td>{r.entry_fee_cents_mean.toFixed(2)}¢</td>
        <td>{cents(m.executable_purchase_net_of_entry_fee.mean)}</td><td>{cents(m.midpoint_execution_net_of_entry_fee.mean)}</td><td>{cents(m.liquidation_net_all_fees.mean)}</td></tr>; })}</tbody></table>
    <p className="ex-fine">Sale fee in the last column is a <b>modelled</b> taker fee for a hypothetical liquidation; positions held to settlement pay none.</p></div>;
}

function Decomp() {
  const rows = [];
  SPORTS.forEach(s => { const d = ex.real_wagers[s].cost_decomposition_cents_vs_close_mid;
    rows.push({label: `${s} price disadvantage vs closing buyer`, v: -d.price_disadvantage_vs_closing_ask}); });
  return <div className="ex-card"><h3>3 · Where the shortfall versus the closing midpoint comes from</h3>
    <p className="ex-fine"><Badge kind="real"/> For one fill: (fill + fee) − close mid = (fill − close ask) + closing half-spread + fee. Entry spread is not observable for owner-placed fills and is not invented.</p>
    <table className="ex-table"><thead><tr><th>Sport</th><th>Paid more than closing ask</th><th>+ Closing half-spread (what any taker pays)</th><th>+ Exchange entry fee</th><th>= Total shortfall</th></tr></thead>
      <tbody>{SPORTS.map(s => { const d = ex.real_wagers[s].cost_decomposition_cents_vs_close_mid; return <tr key={s}><th scope="row">{s}</th>
        <td>{cents(d.price_disadvantage_vs_closing_ask)}</td><td>{d.closing_half_spread.toFixed(2)}¢</td><td>{d.entry_fee.toFixed(2)}¢</td><td><b>{d.total_shortfall.toFixed(2)}¢</b></td></tr>; })}</tbody></table>
    <p className="ex-take"><b>Reading:</b> {ex.answers["3_spread_vs_fees"].split(". The exchange")[1] ? "The exchange" + ex.answers["3_spread_vs_fees"].split(". The exchange")[1] : ""}</p></div>;
}

function Depth() {
  return <div className="ex-card"><h3>4 · Closing order-book depth (size-adjusted benchmark)</h3>
    <p className="ex-fine"><Badge kind="real"/> The best ask may cover only a few contracts. Where an archived same-ticker book exists before the start, we walk the ask levels for our actual quantity. Without a book we report “no depth”; we never assume the whole order fills at the top of book.</p>
    <table className="ex-table"><thead><tr><th>Sport</th><th>Verified fills</th><th>With usable depth</th><th>No archived book</th><th>Book after start (excluded)</th><th>Insufficient depth</th><th>Size premium over best ask</th><th>Fills larger than best level</th></tr></thead>
      <tbody>{SPORTS.map(s => { const dp = ex.real_wagers[s].depth, c = dp.depth_status_counts, sa = dp.size_adjusted; return <tr key={s}><th scope="row">{s}</th>
        <td>{dp.verified_fills}</td><td>{dp.with_depth_snapshot}</td><td>{c.TOP_OF_BOOK_ONLY_NO_DEPTH || 0}</td><td>{c.BOOK_AFTER_START || 0}</td>
        <td>{dp.insufficient_depth_share_of_snapshotted == null ? "—" : pc(dp.insufficient_depth_share_of_snapshotted)}</td>
        <td>{sa ? cents(sa.premium_over_best_ask_cents_mean) : "—"}</td><td>{sa ? pc(sa.share_of_fills_larger_than_best_ask_level) : "—"}</td></tr>; })}</tbody></table>
    <p className="ex-fine">CFB has top-of-book catalog proxies only. Where depth exists our sizes were small relative to the book, so size added little to the closing purchase price.</p></div>;
}

function Timing() {
  return <div className="ex-card"><h3>5 · When real orders were placed</h3>
    <p className="ex-fine"><Badge kind="real"/> Purchase CLV by hours between fill and start. Most real orders were placed within an hour of the start, so real bets cannot tell us whether entering earlier helps.</p>
    <table className="ex-table ex-compact"><thead><tr><th>Sport</th><th>Hours before start</th><th>Fills</th><th>Games</th><th>Purchase CLV</th><th>Midpoint CLV</th></tr></thead>
      <tbody>{SPORTS.flatMap(s => Object.entries(ex.real_wagers[s].by_entry_hours_before_start).map(([h, v]) => <tr key={s + h}><th scope="row">{s}</th><td>{h}</td><td>{v.n}</td><td>{v.games}</td>
        <td>{cents(v.executable_purchase_clv.mean)}</td><td>{cents(v.midpoint_execution_clv.mean)}</td></tr>))}</tbody></table></div>;
}

function Early() {
  const h = ex.hypothetical_early_taker_nfl, o = h.overall, H = h.by_horizon;
  const rows = ["CYCLE", "T-24h", "T-6h", "T-90m", "T-30m"].map(k => ({label: `${k} (n=${int(H[k].n)}, ${H[k].games} games)`, v: H[k].early_advantage.mean_cents, ci: H[k].early_advantage.game_cluster_ci95_cents,
    note: `selection ${cents(H[k].selection.mean_cents)}, entry half-spread ${H[k].entry_half_spread.mean_cents.toFixed(2)}¢ vs closing ${H[k].close_half_spread.mean_cents.toFixed(2)}¢`}));
  const [showAll, setShowAll] = useState(false);
  const rk = h.ranked_families_by_early_advantage, show = showAll ? rk : [...rk.slice(0, 5), ...rk.slice(-3)];
  return <div className="ex-card"><h3>6 · Early entry at the ask versus a closing buyer</h3>
    <p className="ex-fine"><Badge kind="hyp"/> NFL model-preferred selections ({int(o.n)} records, {o.games} games, weeks 1–8): buying immediately at the horizon ask versus buying at the closing ask. Positive = the early buyer paid less. <b>Early advantage = selection CLV + (closing half-spread − entry half-spread)</b>: a widened closing spread would inflate it without any fair-value gain.</p>
    <Key/><Bars label="Early taker advantage over a closing buyer by entry horizon" rows={rows}/>
    <table className="ex-table ex-compact"><thead><tr><th>Horizon</th><th>Records</th><th>Selection (fair value)</th><th>Entry half-spread</th><th>Closing half-spread</th><th>Early advantage</th><th>Mark-to-mid</th></tr></thead>
      <tbody>{["CYCLE", "T-24h", "T-6h", "T-90m", "T-30m"].map(k => <tr key={k}><th scope="row">{k}</th><td>{int(H[k].n)}</td><td>{cents(H[k].selection.mean_cents)}</td><td>{H[k].entry_half_spread.mean_cents.toFixed(2)}¢</td><td>{H[k].close_half_spread.mean_cents.toFixed(2)}¢</td><td>{cents(H[k].early_advantage.mean_cents)}</td><td>{cents(H[k].quoted_exec.mean_cents)}</td></tr>)}</tbody></table>
    <p className="ex-fine">Horizons T-48h, T-12h and T-1h do not exist in this corpus and were not invented. Chronological split: weeks 1–4 {cents(h.by_chronological_split["weeks_01-04"].early_advantage.mean_cents)}, weeks 5–8 {cents(h.by_chronological_split["weeks_05-08"].early_advantage.mean_cents)}.</p>
    <h4>By market family ({h.rank_basis}); {showAll ? "all" : "top 5 and bottom 3"}</h4>
    <table className="ex-table ex-compact"><thead><tr><th>Family</th><th>Records</th><th>Games</th><th>Early advantage (95% CI)</th><th>Selection</th><th>Spread change</th></tr></thead>
      <tbody>{show.map(r => <tr key={r.family}><th scope="row">{r.family.replace("KXNFL", "")}</th><td>{int(r.n)}</td><td>{r.games}</td><td>{cents(r.early_advantage_cents)}{ci(r.ci95_cents)}</td><td>{cents(r.selection_cents)}</td><td>{cents(r.spread_change_cents)}</td></tr>)}</tbody></table>
    <button type="button" className="ex-link" onClick={() => setShowAll(!showAll)} aria-expanded={showAll}>{showAll ? "Show fewer" : `Show all ${rk.length} families`}</button>
    <p className="ex-fine">Family rankings are descriptive and unadjusted for the number of comparisons.</p></div>;
}

function Limit() {
  const L = ex.limit_order_simulation_nfl, rules = ["AT_BID", "BID_PLUS_1TICK", "INSIDE_MID", "AT_ASK"], wins = ["48h", "24h", "12h", "6h", "1h"];
  const RN = {AT_BID: "At the bid", BID_PLUS_1TICK: "One tick above bid", INSIDE_MID: "Inside the spread", AT_ASK: "At the ask (immediate)"};
  const fr = (r, rule, w) => { const c = L.by_rule[rule][w]; const a = c.lo.full_fill_rate_of_determinate, b = c.up.full_fill_rate_of_determinate; return a == null && b == null ? "—" : `${pc(a)}–${pc(b)}`; };
  const det = (r, rule, w) => { const c = L.by_rule[rule][w]; return `${c.lo.decisions - c.lo.uncertain_or_unknown}/${c.up.decisions - c.up.uncertain_or_unknown}`; };
  const imp = (rule, w) => { const c = L.by_rule[rule][w]; const a = c.lo.price_improvement_vs_closing_ask_filled_cents, b = c.up.price_improvement_vs_closing_ask_filled_cents; return a == null ? "—" : `${f2(a)} to ${f2(b)}`; };
  const be = (rule, w) => { const c = L.by_rule[rule][w]; const a = c.lo.breakeven_edge_cents, b = c.up.breakeven_edge_cents; return a == null ? "—" : `${a.toFixed(1)}–${b.toFixed(1)}`; };
  const m = L.scope;
  return <div className="ex-card"><h3>7 · Patient limit orders (simulated against the historical trade tape)</h3>
    <p className="ex-fine"><Badge kind="hyp"/> <b>Nothing here was traded.</b> A resting bid is counted as filled only when the tape shows a seller hitting that price, as a range: the low end puts us at the back of the queue with no credit for cancellations ahead, the high end at the front. “—” = not determinable. Scope: NFL week {m.weeks[0]} only, {m.decisions_evaluated} owner-placed decisions (no verified recommendation link), {m.games} games, {m.placement_instants} placements, {m.with_book} with a book at placement.</p>
    <table className="ex-table ex-compact"><thead><tr><th>Placement</th><th>Window</th><th>Fully filled (low–high)</th><th>Determinate orders (low/high)</th><th>Price vs closing ask when filled, cents (low to high)</th><th>Break-even edge, cents (low–high)</th></tr></thead>
      <tbody>{rules.flatMap(rule => wins.map(w => <tr key={rule + w}><th scope="row">{RN[rule]}</th><td>{w}</td><td>{fr(null, rule, w)}{rule === "AT_ASK" ? " *" : ""}</td><td>{det(null, rule, w)}</td><td>{rule === "AT_ASK" ? "—" : imp(rule, w)}</td><td>{rule === "AT_ASK" ? "—" : be(rule, w)}</td></tr>))}</tbody></table>
    <p className="ex-fine">* Immediate orders fill by construction; displayed size at the ask was not tested here. <b>Break-even edge:</b> resting orders beat buying at the closing ask only if the bet's edge over the closing midpoint is below this figure; a resting order that never fills forfeits the bet’s edge entirely. Resting orders that do not fill are <b>not</b> a gain — scoring them as zero would only mean “not betting”.</p>
    <p className="ex-take"><b>Reading:</b> {ex.answers["8_repeatable_advantage_after_fees_fills_opportunity_cost"].split(" Break-even")[0]}</p></div>;
}

function Answers() {
  const names = {"1": "Price advantage vs the closing ask", "2": "Versus the earlier midpoint CLV", "3": "Spread versus fees", "4": "Where executable CLV is positive", "5": "Would early limit orders help", "6": "How often would they fill", "7": "Strongest entry window", "8": "Any repeatable advantage", "9": "Changes to execution research", "10": "What remains unverifiable"};
  return <div className="ex-card"><h3>8 · The ten questions, answered from the data above</h3>
    {Object.entries(ex.answers).sort((a, b) => parseInt(a[0]) - parseInt(b[0])).map(([k, v]) => { const n = k.split("_")[0]; return <details key={k} className="ex-qa"><summary>{n}. {names[n]}</summary><p>{v}</p></details>; })}</div>;
}

function Evidence() {
  return <div className="ex-card"><h3>9 · Evidence quality and what is missing</h3>
    <table className="ex-table ex-compact"><tbody>{Object.entries(ex.evidence_quality).map(([k, v]) => <tr key={k}><th scope="row">{k.replaceAll("_", " ")}</th><td>{v}</td></tr>)}</tbody></table>
    <h4>Not measured</h4><ul>{ex.not_measured.map(x => <li key={x}>{x}</li>)}</ul>
    <p className="ex-fine">Provenance: {Object.entries(ex.provenance).map(([k, v]) => `${k.replaceAll("_", " ")}: ${String(v).slice(0, 60)}`).join(" · ")}</p></div>;
}

export function ExecutionDashboard() {
  return <section className="ex-dash" aria-label="Execution and CLV dashboard">
    <div className="eyebrow">EXECUTION & CLV · generated {ex.generated_at.slice(0, 10)} · {ex.schema}</div>
    <h2>Are we getting better executable prices than a buyer at the close?</h2>
    <p className="ex-lede">Fair-value movement, executable price, spread and fees are measured separately. <Badge kind="real"/> panels come from real exchange fills; <Badge kind="hyp"/> panels are model selections or simulated orders. None of this is a profitability claim.</p>
    <Definitions/><Headline/><Compare/><Decomp/><Depth/><Timing/><Early/><Limit/><Answers/><Evidence/></section>;
}
