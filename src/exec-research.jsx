import React from "react";
import d from "../research/audit/exec/execution_research_summary.json";
import "./execution-dashboard.css";

// Everything is read from research/audit/exec/execution_research_summary.json (aggregates only; built by research/exec_track/build_dashboard_summary.py).
// No tickers, order ids, stakes or personal fills. Fills are SIMULATED from public tape / HYPOTHETICAL shadow orders: never observed personal fills.
const f2 = v => (v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(2));
const pc = v => (v == null ? "—" : Math.round(100 * v) + "%");
const ci = c => (c ? `${f2(c.mean)}¢ [${f2(c.lo)}, ${f2(c.hi)}]` : "—");
const int = v => (v == null ? "—" : Number(v).toLocaleString());

function Status() {
  return <div className="ex-card ex-lead"><h3>Status</h3>
    <p><span className="ex-badge ex-hyp">{d.status}</span> Validated strategies: <b>{d.validated_strategies.length === 0 ? "none" : d.validated_strategies.join(", ")}</b> · live execution authority: <b>{d.headline.live_execution_authority}</b></p>
    <ul><li><b>Absolute net EV:</b> {d.headline.absolute_net_ev}</li><li><b>Execution cost:</b> {d.headline.relative_execution_cost}</li></ul>
    <p className="ex-fine">{d.privacy}.</p></div>;
}

function Cost() {
  const t = d.execution_cost_by_strategy_2026_live, e = d.early_taker_vs_wait_2025;
  return <div className="ex-card"><h3>Execution cost by entry strategy (equal exposure, ¢ per contract, all-in of fees)</h3>
    <p className="ex-fine"><span className="ex-badge ex-hyp">SIMULATED FROM LIVE TAPE</span> 2026 live capture, queue = displayed size at the bid, 95% interval resamples games. Positive = cheaper than waiting and taking at the close. M0 / M25 / M100 = makers pay 0 / 0.0175 / 0.07 (the taker rate).</p>
    <table className="ex-table ex-compact"><thead><tr><th>Horizon</th><th>Wait & take (absolute)</th><th>Fill prob. at the bid</th><th>Limit + taker fallback − wait · M0</th><th>· M25</th><th>· M100</th><th>Limit, no fallback (per submitted) · M25</th></tr></thead>
      <tbody>{Object.entries(t.by_horizon).map(([h, r]) => <tr key={h}><th scope="row">{h} before kickoff</th><td>{ci(r.wait_cents)}</td><td>{pc(r.M25 && r.M25.fill_prob)}</td>
        {["M0", "M25", "M100"].map(s => <td key={s}>{r[s] ? ci(r[s].limit_fb_minus_wait_cents) : "—"}</td>)}<td>{r.M25 ? ci(r.M25.nobet_per_submitted_cents) : "—"}</td></tr>)}</tbody></table>
    <h4>Early taker entry vs waiting (2025 backfill, moneyline)</h4>
    <table className="ex-table ex-compact"><tbody>{Object.entries(e).map(([h, c]) => <tr key={h}><th scope="row">{h}</th><td>{ci(c)}</td></tr>)}</tbody></table>
    <p className="ex-take"><b>Reading:</b> buying early never beats waiting; a resting bid with a taker fallback saves a fraction of a cent to about one cent, and only if makers do not pay the taker rate. Absolute net value stays at or below zero.</p></div>;
}

function Fees() {
  const m = d.maker_fee_verification;
  return <div className="ex-card"><h3>Maker-fee verification status</h3>
    <p className="ex-fine">Taker 0.07: <b>{m.taker_0_07}</b>. Observed maker fills: <b>{m.maker_observed_fills}</b> — no maker coefficient has been observed anywhere; nothing here may be read as verified by a fill.</p>
    <table className="ex-table ex-compact"><tbody>{Object.entries(m.maker_status).map(([k, v]) => <tr key={k}><th scope="row">{k.replaceAll("_", " ")}</th><td>{v}</td></tr>)}</tbody></table></div>;
}

function Queue() {
  const q = d.queue_and_fill_evidence, b = q.displayed_best_bid_size_2026 || {};
  return <div className="ex-card"><h3>Queue and fill-probability evidence</h3>
    <table className="ex-table ex-compact"><thead><tr><th>Horizon</th><th>Displayed best-bid size, median (contracts)</th><th>Share ≥ 500</th><th>Simulated fill at the bid</th></tr></thead>
      <tbody>{["24h", "6h", "90m"].map(h => <tr key={h}><th scope="row">{h}</th><td>{int(b[h] && b[h].median)}</td><td>{pc(b[h] && b[h].share_ge_500)}</td><td>{pc(q.fill_prob_2026_at_bid[h])}</td></tr>)}</tbody></table>
    <p className="ex-fine">2025 research assumed a 500-contract queue: {q.assumed_queue_2025.central}. NFL tape: {q.tape.capped_moneyline} of {q.tape.moneyline} moneyline tapes are truncated at 10,000 prints; hourly candles match the tape exactly ({int(q.tape.candle_vs_tape && q.tape.candle_vs_tape.volume_equals_tape_sum)} of {int(q.tape.candle_vs_tape && q.tape.candle_vs_tape.hourly_candles_compared)} hours) and bound the rest.</p></div>;
}

function Shadow() {
  const s = d.shadow_orders;
  const rows = Object.entries(s.cells || {}).map(([k, v]) => [k.split("|").slice(2).join(" · "), v]).filter(([, v]) => v.vs_wait_cents);
  return <div className="ex-card"><h3>Shadow-order ledger (hypothetical)</h3>
    <p className="ex-fine"><span className="ex-badge ex-hyp">HYPOTHETICAL SHADOW</span> {s.provenance}. Decisions: <b>{int(s.decisions_placed)}</b> recorded, <b>{int(s.decisions_closed)}</b> closed; <b>prospective: {int(s.prospective_decisions)}</b>. {s.results_note}</p>
    {rows.length > 0 && <table className="ex-table ex-compact"><thead><tr><th>Cell (maker M25)</th><th>vs wait, ¢ [95%]</th><th>n</th></tr></thead><tbody>{rows.map(([k, v]) => <tr key={k}><th scope="row">{k}</th><td>{ci(v.vs_wait_cents)}</td><td>{v.n}</td></tr>)}</tbody></table>}</div>;
}

function Health() {
  const c = d.data_completeness, n = c.nfl_backfill_before || {};
  return <div className="ex-card"><h3>Data completeness and collector health</h3>
    <table className="ex-table ex-compact"><tbody>
      <tr><th scope="row">NFL contracts archived / settled</th><td>{int(n.unique_contracts)} / {int(n.settled)}</td></tr>
      <tr><th scope="row">Contracts with a two-sided pre-start quote at ≥1 horizon</th><td>{int(n.horizon_rows_with_any_two_sided_prestart_quote)} of {int(n.horizon_rows)} horizon rows</td></tr>
      <tr><th scope="row">Trade tapes truncated at 10,000 prints</th><td>{int(c.tape_cap.capped_tapes)} of {int(c.tape_cap.tapes)}</td></tr>
      <tr><th scope="row">Recovered tape (after repair)</th><td>{int(n.recovered_complete)} complete — {c.collector_repair}</td></tr></tbody></table></div>;
}

function Outcome() {
  const o = d.outcome_candidates;
  return <div className="ex-card"><h3>Outcome research — separate from execution</h3><p className="ex-fine">{o.note}</p>
    <table className="ex-table ex-compact"><thead><tr><th>Cell</th><th>Holdout mean, ¢ [95%]</th><th>Games</th><th>Status</th></tr></thead>
      <tbody>{o.cells.map(r => <tr key={r.cell}><th scope="row">{r.sport} {r.cell}</th><td>{f2(r.holdout_mean_cents)} [{f2(r.holdout_ci_cents[0])}, {f2(r.holdout_ci_cents[1])}]</td><td>{r.n_games}</td><td>{r.status}</td></tr>)}</tbody></table>
    {o.family_scan && <><h4>Market-only scan of every family with pre-start quotes</h4>
      <p className="ex-fine">{o.family_scan.design}. Cells tried: {o.family_scan.cells_tried}; positive in both validation and holdout: <b>{o.family_scan.positive_validation_and_holdout}</b>; passing a Holm-corrected holdout test: <b>{o.family_scan.pass_holdout_holm_0p10}</b>.</p>
      <table className="ex-table ex-compact"><thead><tr><th>Family · horizon · side</th><th>Validation, ¢</th><th>Holdout, ¢ [95%]</th><th>n</th></tr></thead>
        <tbody>{o.family_scan.top.map(r => <tr key={r.series + r.horizon + r.side}><th scope="row">{r.series} · {r.horizon} · {r.side}</th><td>{f2(r.validation_mean_cents)}</td><td>{f2(r.holdout_mean_cents)} [{f2(r.holdout_ci_cents[0])}, {f2(r.holdout_ci_cents[1])}]</td><td>{r.n}</td></tr>)}</tbody></table></>}</div>;
}

export function ExecutionResearch() {
  return <section className="ex-dash" aria-label="Execution research status">
    <div className="eyebrow">EXECUTION RESEARCH · {d.schema} · {d.status}</div>
    <h2>Can realistic limit orders improve net profitability?</h2>
    <Status/><Cost/><Fees/><Queue/><Shadow/><Health/><Outcome/></section>;
}
