import React from "react";
import cs from "../research/audit/clv/collectors_status.json";
import "./execution-dashboard.css";

// Counters published by the running collectors, fetched at Pages build time. A missing block renders as "not yet measured", never as zero.
const n = v => (v == null ? "—" : Number(v).toLocaleString());

export function CollectorsStatus() {
  const e = cs.entry_capture, s = cs.shadow_ledger;
  return <section className="ex-dash" aria-label="Live collector status">
    <div className="eyebrow">LIVE COLLECTORS · data vintage {cs.generated_at ? cs.generated_at.slice(0, 16).replace("T", " ") + "Z" : "not fetched"}</div>
    <h2>Is prospective evidence actually being collected?</h2>
    <p className="ex-lede">Health of the two prospective collectors, read from their published aggregates when this site was built. A green workflow is not evidence: only valid output counts.</p>
    <div className="ex-card"><h3>Entry-market capture (20-second top-of-book sampler + order join)</h3>
      {!e ? <p className="ex-fine">Not yet fetched at build time.</p> : <>
        <p className="ex-fine"><span className="ex-badge ex-real">RUNNING</span> last pass {e.sampler.last_pass_at}; first pass {e.sampler.first_pass_at}.</p>
        <table className="ex-table ex-compact"><tbody>
          <tr><th scope="row">Sampling passes / worst gap between passes</th><td>{n(e.sampler.passes)} / {n(Math.round(e.sampler.max_gap_seconds))} s</td></tr>
          <tr><th scope="row">Series watched · top-of-book snapshots taken</th><td>{n(e.sampler.series_watched)} · {n(e.sampler.snapshots)}</td></tr>
          <tr><th scope="row">Series and order read errors</th><td>{n(e.sampler.series_errors)} · {n(e.sampler.order_errors)}</td></tr>
          <tr><th scope="row">Price-axis metrics version</th><td><b>{e.metrics_version || "unversioned (pre-v2 collector)"}</b>{e.metrics_version === "purchased_leg_v2" ? "" : " — price-vs-ask comparisons from this version are NOT validated"}</td></tr>
          <tr><th scope="row">{e.metrics_version === "purchased_leg_v2" ? "New orders joined under v2 (fresh entry quote / any)" : "Orders joined, UNRECONCILED legacy basis (fresh entry quote / any)"}</th><td><b>{n(e.totals.ENTRY_FRESH)}</b> / {n(e.totals.orders)}</td></tr>
          <tr><th scope="row">Legacy pre-v2 orders quarantined (orders / fresh quotes)</th><td>{e.legacy_unreconciled ? n(e.legacy_unreconciled.orders) + " / " + n(e.legacy_unreconciled.fresh_entry_quotes) : "none recorded"}</td></tr>
          <tr><th scope="row">Orders placed before capture started (never joined to a later book)</th><td>{n(e.sampler.historical_not_capturable)}</td></tr></tbody></table>
        <p className="ex-fine">An entry quote must be a same-contract snapshot observed at or before placement and ≤45 s old. Later or older books are labelled and excluded, never used. A v2 count of zero right after the fix ships means no new order has been joined yet, not a collector outage (check passes and last pass above). Legacy fills cannot be retro-corrected: public state holds only aggregates.</p></>}</div>
    <div className="ex-card"><h3>Shadow-order ledger (hypothetical orders on live NFL quotes and trade prints)</h3>
      {!s ? <p className="ex-fine">Not yet fetched at build time, or the ledger has not published valid output.</p> : <>
        <p className="ex-fine"><span className={"ex-badge " + (s.valid ? "ex-real" : "ex-hyp")}>{s.valid ? "VALID OUTPUT" : "INVALID OUTPUT"}</span> health generated {s.generated_at}.</p>
        <table className="ex-table ex-compact"><tbody>
          <tr><th scope="row">Hypothetical strategy rows (prospective / archive replay) — NOT independent: ~9 tactics share each snapshot</th><td><b>{n(s.counts.prospective)}</b> / {n(s.counts.retrospective)}</td></tr>
          <tr><th scope="row">Unique contract-time decisions (prospective / archive replay)</th><td><b>{n(s.counts.prospective_unique_decisions)}</b> / {n(s.counts.retrospective_unique_decisions)}</td></tr>
          <tr><th scope="row">Independent games (prospective / archive replay)</th><td><b>{n(s.counts.prospective_independent_games)}</b> / {n(s.counts.retrospective_independent_games)}</td></tr>
          <tr><th scope="row">Contracts · games</th><td>{n(s.counts.contracts)} · {n(s.counts.games)}</td></tr>
          <tr><th scope="row">Tape-bound observations · settled</th><td>{n(s.counts.observed)} · {n(s.counts.settled)}</td></tr>
          <tr><th scope="row">Newest ingested capture run is how old</th><td>{s.capture_age_minutes == null ? "—" : n(Math.round(s.capture_age_minutes)) + " min"}{s.capture_stale ? " (STALE)" : ""}</td></tr></tbody></table>
        <p className="ex-fine">Rows rebuilt from the archive are labelled RETROSPECTIVE_REPLAY and never count as prospective evidence. Strategy rows are repetitions of the same snapshot: use unique decisions and independent games as N, not row counts. Entry-capture matches are actual-order matches, not verified recommendation links.</p></>}</div>
  </section>;
}
