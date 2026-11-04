import React, {useState} from "react";
import summary from "../research/audit/clv/clv_summary.json";
import "./clv-dashboard.css";

// Everything rendered here comes from research/audit/clv/clv_summary.json (aggregates only: no stakes, P&L, ROI, tickers or
// per-wager rows). Values are probability points (dollars per contract); shown in cents. Positive = beat the benchmark.
const c = v => (v == null ? null : v * 100);
const f2 = v => (v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(2));
const cents = v => (v == null ? "—" : f2(c(v)) + "¢");
const int = v => (v == null ? "—" : Number(v).toLocaleString());
const pct = (a, b) => (b ? (100 * a / b).toFixed(0) + "%" : "—");
const sign = v => (v == null ? "na" : Math.abs(v) < 0.00005 ? "zero" : v > 0 ? "pos" : "neg");
const SPORTS = ["NFL", "CFB", "NBA", "NHL"];
const REASON = {NO_CLOSE: "no archived pregame close", CLOSE_STALE: "close older than 60 min", NOT_A_PREGAME_ENTRY: "placed at/after start (live)",
  CLOSE_ONE_SIDED: "one-sided close", CLOSE_CROSSED: "crossed close", CLOSE_AFTER_START: "close not before start", TICKER_MISMATCH: "ticker mismatch", OK: "verified"};

// One diverging bar row: bar from a zero axis, 95% whisker, value label in ink (sign is also in the text, never colour alone).
function BarRows({rows, ariaLabel}) {
  const vals = rows.flatMap(r => [r.v, ...(r.ci || [])]).filter(x => x != null);
  const max = Math.max(0.005, ...vals.map(Math.abs)) * 1.12;
  const LAB = 340, W = 420, VAL = 74, H = 30, zero = LAB + W / 2, k = (W / 2 - 4) / max;
  return <svg className="clv-bars" viewBox={`0 0 ${LAB + W + VAL} ${rows.length * H + 6}`} role="img" aria-label={ariaLabel}>
    <line x1={zero} x2={zero} y1="0" y2={rows.length * H + 4} className="clv-axis"/>
    {rows.map((r, i) => {
      const y = i * H + 4, w = r.v == null ? 0 : Math.abs(r.v) * k, x = r.v >= 0 ? zero : zero - w;
      return <g key={r.label} tabIndex="0">
        <title>{`${r.label}: ${cents(r.v)}${r.ci ? ` (95% CI ${cents(r.ci[0])} to ${cents(r.ci[1])})` : ""}${r.note ? " · " + r.note : ""}`}</title>
        <rect x="0" y={y} width={LAB + W + VAL} height={H - 6} className="clv-hit"/>
        <text x={LAB - 10} y={y + H / 2 - 3} textAnchor="end" className="clv-lab">{r.label.length > 58 ? r.label.slice(0, 57) + "…" : r.label}</text>
        <rect x={x} y={y + 4} width={Math.max(w, 1)} height={H - 14} rx="4" className={"clv-bar clv-" + sign(r.v)}/>
        {r.ci && <g className="clv-whisk"><line x1={zero + r.ci[0] * k} x2={zero + r.ci[1] * k} y1={y + H / 2 - 1} y2={y + H / 2 - 1}/>
          <line x1={zero + r.ci[0] * k} x2={zero + r.ci[0] * k} y1={y + H / 2 - 5} y2={y + H / 2 + 3}/>
          <line x1={zero + r.ci[1] * k} x2={zero + r.ci[1] * k} y1={y + H / 2 - 5} y2={y + H / 2 + 3}/></g>}
        <text x={LAB + W + 8} y={y + H / 2 - 3} className="clv-val">{cents(r.v)}</text>
      </g>;
    })}
  </svg>;
}

function Legend() {
  return <p className="clv-legend" aria-label="Colour key"><i className="clv-sw clv-pos"/> above zero (beat the benchmark) <i className="clv-sw clv-neg"/> below zero <i className="clv-sw clv-zero"/> ≈ 0 · whisker = 95% interval resampling whole games · every bar is also labelled with its signed value</p>;
}

function Definitions() {
  const d = summary.metric_definitions;
  return <details className="clv-defs"><summary>Metric definitions, denominators and sources</summary>
    <dl>{Object.entries(d).map(([k, v]) => <React.Fragment key={k}><dt>{k.replaceAll("_", " ")}</dt>
      <dd>{v.definition}{v.applies_to ? <em> — {v.applies_to}</em> : null}</dd></React.Fragment>)}</dl>
    <p className="clv-fine">Privacy: {summary.privacy}. Provenance: {Object.entries(summary.provenance).map(([k, v]) => `${k.replaceAll("_", " ")} ${String(v).slice(0, 40)}`).join(" · ")}.</p></details>;
}

function Coverage() {
  return <div className="clv-card"><h3>1 · Real-wager CLV coverage (verified vs unverifiable)</h3>
    <p className="clv-fine">Denominator = pregame entries eligible (orders placed before the start). Source: router fills + archived pregame closes.
      Real-bet <b>selection CLV is unverifiable everywhere</b>: 0 recommendation→order links exist.</p>
    <table className="clv-table"><thead><tr><th>Sport</th><th>Wagers</th><th>Pregame entries</th><th>Verified CLV</th><th>Coverage</th><th>Unverifiable, by reason</th><th>Close source</th></tr></thead>
      <tbody>{SPORTS.map(s => {
        const b = summary.real_wagers[s], d = b.denominators;
        return <tr key={s}><th scope="row">{s}</th><td>{int(d.wagers_in_ledger)}</td><td>{int(d.pregame_entries_eligible)}</td><td>{int(d.verified_clv_observations)}</td>
          <td><span className="clv-meter" title={`${d.verified_clv_observations} of ${d.pregame_entries_eligible}`}><span style={{width: pct(d.verified_clv_observations, d.pregame_entries_eligible)}}/></span> {pct(d.verified_clv_observations, d.pregame_entries_eligible)}</td>
          <td className="clv-small">{Object.entries(b.unverifiable_by_reason).filter(([k]) => k !== "OK").map(([k, n]) => `${n} ${REASON[k] || k}`).join("; ") || "—"}</td>
          <td className="clv-small">{b.source}</td></tr>;
      })}</tbody></table></div>;
}

function RealCLV() {
  const rows = [], fee = [];
  SPORTS.forEach(s => { const b = summary.real_wagers[s], a = b.actual_execution_clv;
    rows.push({label: `${s} actual-fill CLV (n=${a.n}, ${a.game_cluster.clusters} games)`, v: a.mean, ci: a.game_cluster.ci95, note: `fee-exclusive VWAP; median ${cents(a.median)}; ${a.positive_pct.toFixed(0)}% positive`});
    rows.push({label: `${s} after 1 entry fee`, v: b.fee_adjusted_difference.mean, note: `entry fee ${cents(b.fee_per_contract.mean)} per contract, counted once`}); });
  return <div className="clv-card"><h3>2 · Real wagers: actual execution CLV and fee drag</h3>
    <p className="clv-fine">Actual execution CLV = closing midpoint − exchange fill VWAP (fee-exclusive). The second bar subtracts the real entry fee once. Includes slippage and the half-spread actually crossed; the two cannot be separated without a joined entry quote.</p>
    <Legend/><BarRows rows={rows} ariaLabel="Real wager actual execution CLV and fee-adjusted difference by sport"/></div>;
}

function Decomposition() {
  const a = summary.hypothetical_selections.NFL_shadow_v2.after_gated_deduped, ci = k => a[k].game_cluster_ci95;
  const rows = [
    {label: "Selection CLV (mid → mid)", v: a.selection.mean, ci: ci("selection"), note: "no spread, no fee"},
    {label: "− entry spread (half)", v: -a.spread_drag_mean, note: "selection − quoted execution"},
    {label: "= Quoted execution CLV (close mid − ask)", v: a.quoted_exec.mean, ci: ci("quoted_exec")},
    {label: "− modelled entry fee (once)", v: -a.fee_drag_mean, note: "schedule estimate, not a fill"},
    {label: "= Fee-adjusted difference", v: a.fee_adjusted.mean, ci: ci("fee_adjusted")}];
  return <div className="clv-card"><h3>3 · Hypothetical NFL selections: market movement vs spread vs fee</h3>
    <p className="clv-fine">{int(a.selection.n)} records from {a.games} games (weeks 1–8), one per game·ticker·horizon·arm, close ≤ 60 min old, model-preferred side. <b>Descriptive: not bets, not profit.</b>
      Median selection CLV is {cents(a.selection.median)}; {a.selection.positive_pct.toFixed(0)}% positive, {a.selection.zero_pct.toFixed(0)}% unchanged.</p>
    <Legend/><BarRows rows={rows} ariaLabel="Decomposition of selection CLV into spread drag, quoted execution, fee drag and fee-adjusted result"/></div>;
}

function Slice({title, data, order, caption}) {
  const keys = order || Object.keys(data);
  const rows = keys.filter(k => data[k] && data[k].selection.n).map(k => ({label: `${k} (n=${int(data[k].selection.n)}, ${data[k].games} games)`, v: data[k].selection.mean, ci: data[k].selection.game_cluster_ci95 || null,
    note: `quoted ${cents(data[k].quoted_exec.mean)}, fee-adjusted ${cents(data[k].fee_adjusted.mean)}`}));
  return <div className="clv-card"><h3>{title}</h3><p className="clv-fine">{caption}</p><BarRows rows={rows} ariaLabel={title}/>
    <table className="clv-table clv-compact"><thead><tr><th>{title.split("·")[1]?.trim() || "Slice"}</th><th>n</th><th>games</th><th>Selection</th><th>Quoted exec</th><th>Fee-adjusted</th><th>% positive (sel)</th></tr></thead>
      <tbody>{keys.filter(k => data[k] && data[k].selection.n).map(k => <tr key={k}><th scope="row">{k}</th><td>{int(data[k].selection.n)}</td><td>{data[k].games}</td>
        <td>{cents(data[k].selection.mean)}</td><td>{cents(data[k].quoted_exec.mean)}</td><td>{cents(data[k].fee_adjusted.mean)}</td><td>{data[k].selection.positive_pct.toFixed(0)}%</td></tr>)}</tbody></table></div>;
}

function Families() {
  const s = summary.hypothetical_selections.NFL_shadow_v2, rk = s.ranked_families_by_selection;
  const [all, setAll] = useState(false);
  const best = rk.slice(0, 6), worst = rk.slice(-6).reverse();
  const T = ({rows, title}) => <><h4>{title}</h4><table className="clv-table clv-compact"><thead><tr><th>Family</th><th>n</th><th>games</th><th>Selection (95% CI)</th><th>Quoted exec</th><th>Fee-adjusted</th></tr></thead>
    <tbody>{rows.map(r => <tr key={r.family}><th scope="row">{r.family.replace("KXNFL", "")}</th><td>{int(r.n)}</td><td>{r.games}</td>
      <td>{cents(r.selection_mean)} {r.selection_ci95 ? <span className="clv-small">({cents(r.selection_ci95[0])}, {cents(r.selection_ci95[1])})</span> : null}</td>
      <td>{cents(r.quoted_exec_mean)}</td><td>{cents(r.fee_adjusted_mean)}</td></tr>)}</tbody></table></>;
  return <div className="clv-card"><h3>4 · Market families, ranked (NFL hypothetical selections)</h3>
    <p className="clv-fine">Ranked by selection CLV; {s.rank_basis}. Note how every family with the best midpoint movement is still negative after spread and fee.
      These rankings are descriptive and unadjusted for multiple comparisons; a chronological holdout and preregistration are required before acting on them.</p>
    <T rows={best} title="Best-supported by selection CLV"/><T rows={worst} title="Weakest by selection CLV"/>
    <button type="button" className="clv-link" onClick={() => setAll(!all)} aria-expanded={all}>{all ? "Hide" : "Show"} all {rk.length} ranked families</button>
    {all && <T rows={rk} title="All ranked families"/>}</div>;
}

function BeforeAfter() {
  const fmt = o => o == null ? "—" : [o.n != null ? `n=${int(o.n)}` : null, o.mean_cents != null ? `mean ${f2(o.mean_cents)}¢` : null, o.ci95_cents ? `CI ${f2(o.ci95_cents[0])}…${f2(o.ci95_cents[1])}¢` : null, o.note || null].filter(Boolean).join(" · ");
  const flat = o => o && (o.mean_cents != null || o.note || o.n != null) ? fmt(o) : (o ? Object.entries(o).map(([k, v]) => `${k.replace("_exec", "")}: ${fmt(v)}`).join(" | ") : "—");
  return <div className="clv-card"><h3>5 · Before vs after the corrections</h3>
    <p className="clv-fine">“Before” is what the producing repository published; “after” is recomputed from raw ledger fields and raw closes under the canonical definitions.</p>
    <table className="clv-table clv-compact"><thead><tr><th>Sport · population</th><th>Metric</th><th>Before</th><th>After</th><th>Why it changed</th><th>Verdict</th></tr></thead>
      <tbody>{summary.before_after.map((r, i) => <tr key={i}><th scope="row">{r.sport}{r.population ? " · " + r.population : ""}</th><td>{r.metric}</td><td className="clv-small">{flat(r.before)}</td><td className="clv-small">{flat(r.after)}</td><td className="clv-small">{r.cause}</td>
        <td><span className={"badge clv-v-" + (r.verdict.startsWith("CONTAMINATED") ? "bad" : r.verdict.startsWith("NOT_") ? "ok" : "info")}>{r.verdict.split(" (")[0].replaceAll("_", " ").toLowerCase()}</span></td></tr>)}</tbody></table></div>;
}

function Gaps() {
  const m = summary.missing_evidence, q = summary.evidence_quality;
  return <div className="clv-card"><h3>6 · Evidence quality and what is missing</h3>
    <table className="clv-table clv-compact"><tbody>{Object.entries(q).filter(([k]) => k !== "interpretation").map(([k, v]) => <tr key={k}><th scope="row">{k.replaceAll("_", " ")}</th><td>{v}</td></tr>)}</tbody></table>
    <p><b>{q.interpretation}.</b></p><h4>Missing evidence</h4>
    <ul>{Object.entries(m).map(([k, v]) => <li key={k}><b>{k.replaceAll("_", " ")}</b>: {typeof v === "string" ? v : Object.entries(v).map(([a, b]) => `${a.replaceAll("_", " ")} ${b}`).join(" · ")}</li>)}</ul>
    <h4>Not measured</h4><ul>{summary.not_measured.map(x => <li key={x}>{x}</li>)}</ul></div>;
}

export function ClvDashboard() {
  const sh = summary.hypothetical_selections.NFL_shadow_v2;
  return <section className="clv-dash" aria-label="CLV accuracy dashboard">
    <div className="eyebrow">CLV ACCURACY · generated {summary.generated_at.slice(0, 10)} · {summary.schema}</div>
    <h2>Do SIFT’s selections beat the closing market? Spread and fees kept apart.</h2>
    <p className="clv-lede">Selection CLV (market movement) is separated from spread, slippage and Kalshi fees, and none of them is profit. Positive CLV is not guaranteed profitability.</p>
    <Definitions/><Coverage/><RealCLV/><Decomposition/>
    <Slice title="Entry timing · Horizon" data={sh.by_horizon} order={["CYCLE", "T-24h", "T-6h", "T-90m", "T-30m"]} caption="Selection CLV by how long before the start the quote was taken (same denominators as above)."/>
    <Slice title="Probability bucket · Entry price" data={sh.by_price_bucket} caption="Entry executable price of the model side."/>
    <Slice title="Chronological holdout · Weeks" data={sh.chronological_split} order={["weeks_01-04", "weeks_05-08"]} caption="Weeks 1–4 versus weeks 5–8: the later block was not used to choose anything in the earlier one. Selection CLV persisted out of sample; after spread and fee both blocks are negative."/>
    <Slice title="Chronological · NFL week" data={sh.by_week_chronological} caption="Week by week, in order. Week 8 is a single game (recovery of that week was partial at the time of capture); intervals with very few games are wide or absent."/>
    <Families/><BeforeAfter/><Gaps/></section>;
}
