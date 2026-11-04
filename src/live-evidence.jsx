import React from "react";
import ev from "../research/audit/clv/live_execution_evidence.json";
import "./execution-dashboard.css";

// Aggregate-only counters from bounded read-only probes. Null blocks render as "not yet measured", never as zero.
const n = v => (v == null ? "—" : Number(v).toLocaleString());

export function LiveEvidence() {
  const o = ev.order_endpoint, l = ev.linkage, e = ev.entry_capture, f = ev.fees, t = ev.tape_coverage;
  return <section className="ex-dash" aria-label="Live execution evidence coverage">
    <div className="eyebrow">LIVE EXECUTION EVIDENCE · {ev.generated_at.slice(0, 10)} · {ev.schema}</div>
    <h2>What we can and cannot prove about execution</h2>
    <p className="ex-lede">Coverage of verified evidence, not results. Counters come from bounded read-only probes of the exchange; nothing here is a profitability claim.</p>
    <div className="ex-card"><h3>1 · Order-to-recommendation linkage</h3>
      <p className="ex-fine"><span className="ex-badge ex-real">VERIFIED LIVE</span> {o.orders_sampled} orders and {o.fills_sampled} fills sampled (counters only).</p>
      <table className="ex-table ex-compact"><tbody>
        <tr><th scope="row">Orders exposing a client_order_id field</th><td>{n(o.client_order_id_field_present)} / {n(o.orders_sampled)}</td></tr>
        <tr><th scope="row">…with a non-empty value</th><td>{n(o.client_order_id_non_empty)} / {n(o.orders_sampled)}</td></tr>
        <tr><th scope="row">…carrying a SIFT recommendation token</th><td>{n(o.client_order_id_sift_prefixed)}</td></tr>
        <tr><th scope="row">Fills joined to their order by order id</th><td>{n(o.fills_joined_to_order_by_order_id)} / {n(o.fills_sampled)}</td></tr>
        <tr><th scope="row">Verified recommendation→order links</th><td><b>{n(l.verified_links)}</b></td></tr>
        <tr><th scope="row">Ticker/time matches counted as verified</th><td>{n(l.unique_window_candidates_counted_as_verified)}</td></tr></tbody></table>
      <p className="ex-take"><b>Reading:</b> {o.reading}</p>
      <p className="ex-fine">Blocker: {l.blocker}.</p></div>
    <div className="ex-card"><h3>2 · Entry-market quote capture</h3>
      <p className="ex-fine"><span className="ex-badge ex-hyp">NOT YET COLLECTING</span> {e.joiner}.</p>
      <table className="ex-table ex-compact"><tbody>
        <tr><th scope="row">Prospective fills with a prior entry quote</th><td>{n(e.prospective_fills_with_entry_quote)} / {n(e.prospective_fills_evaluated)}</td></tr>
        <tr><th scope="row">Historical entry quotes</th><td>{e.historical_entry_quotes}</td></tr></tbody></table></div>
    {ev.order_behavior && <div className="ex-card"><h3>2b · How real orders actually executed</h3>
      <p className="ex-fine"><span className="ex-badge ex-real">VERIFIED LIVE</span> {ev.order_behavior.evidence}</p>
      <table className="ex-table ex-compact"><tbody>
        <tr><th scope="row">Executed orders sampled (market / limit)</th><td>{n(ev.order_behavior.executed_orders_sampled)} ({n(ev.order_behavior.executed_market_orders)} / {n(ev.order_behavior.executed_limit_orders)})</td></tr>
        <tr><th scope="row">Fully filled, all taker, within 5 s of placement</th><td>{n(ev.order_behavior.executed_fully_filled)} / {n(ev.order_behavior.executed_orders_sampled)}</td></tr>
        <tr><th scope="row">Executed orders with any maker fill</th><td>{n(ev.order_behavior.executed_with_any_maker_fill)}</td></tr>
        <tr><th scope="row">Canceled / resting orders in the account (all)</th><td>{n(ev.order_behavior.canceled_orders_total)} / {n(ev.order_behavior.resting_orders_total)}</td></tr></tbody></table>
      <p className="ex-take"><b>Reading:</b> {ev.order_behavior.reading}</p></div>}
    <div className="ex-card"><h3>3 · Fees and maker/taker evidence</h3>
      <p className="ex-fine"><span className="ex-badge ex-real">VERIFIED ACTUAL FEES</span></p>
      <table className="ex-table ex-compact"><tbody>
        <tr><th scope="row">Entry fees matching the taker schedule (0.07)</th><td>{n(f.taker_matches_0_07)} / {n(f.taker_fee_rows_validated)} across {n(f.series_checked)} series</td></tr>
        <tr><th scope="row">Maker fills observed in fee ledgers</th><td>{n(f.maker_fills_observed)}</td></tr>
        <tr><th scope="row">Maker fee schedule</th><td>{f.maker_fee_status}</td></tr></tbody></table>
      {ev.series_fee_schedule && <p className="ex-take"><b>Published schedule ({ev.series_fee_schedule.series_checked} series):</b> {Object.entries(ev.series_fee_schedule.fee_type_counts).map(([k, v]) => `${v} × ${k.replaceAll("_", " ")}`).join(" · ")}. {ev.series_fee_schedule.reading}</p>}</div>
    <div className="ex-card"><h3>4 · Trade-tape and order-book coverage</h3>
      <table className="ex-table ex-compact"><tbody>{Object.entries(t).map(([k, v]) => <tr key={k}><th scope="row">{k}</th><td>{v}</td></tr>)}</tbody></table></div>
    <p className="ex-fine">Research confidence: {ev.confidence}</p>
  </section>;
}
