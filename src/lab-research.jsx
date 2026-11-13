import React from "react";
import summary from "../research/audit/lab/dashboard_summary.json";
import "./lab-research.css";

// Aggregates only (alpha_engine/lab/summary.py): no tickers, no per-order data. A verdict of MARKET_BETTER / NO_DIFFERENCE_DETECTED is a research result, never trading authority.
const f = (x, d = 3) => (x == null || Number.isNaN(x) ? "–" : Number(x).toFixed(d));
const nice = s => String(s ?? "").toLowerCase().replaceAll("_", " ");

export function LabResearch() {
  const s = summary;
  const p = s.prospective_2026;
  return (
    <section className="lab-research" data-testid="lab-research" aria-label="Independent prediction laboratory">
      <h2>Independent prediction laboratory</h2>
      <p className="lab-note">{s.claim_boundary}</p>
      <p className="lab-note lab-warn" data-testid="lab-evidence-status">Static build snapshot ({nice(s.evidence_status.dashboard_panel)}; workflow {nice(s.evidence_status.prospective_workflow)}). Not live production evidence: the ledgers published on prospective-data are authoritative.</p>
      <div className="lab-scroll">
        <table>
          <thead><tr><th>Family</th><th>Games (before → after repairs)</th><th>Log-loss gain vs market (after)</th><th>95% CI</th><th>Verdict</th></tr></thead>
          <tbody>
            {s.families.map(r => (
              <tr key={r.family}>
                <td>{nice(r.family)}</td>
                <td>{r.games_before ?? "–"} → {r.games_after}</td>
                <td>{f(r.gain_after, 4)}</td>
                <td>[{f(r.ci_after[0], 3)}, {f(r.ci_after[1], 3)}]</td>
                <td><span className={"lab-chip lab-" + r.verdict}>{nice(r.verdict)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>Prospective 2026 totals test</h3>
      <p>Frozen model <b>{p.frozen_model}</b>: {p.predictions} timestamped predictions, {p.quotes} captured quotes, {p.decision_games} settled decision games, {p.complete_observations} complete quote observations. Status: {nice(p.status)}; claim gate: {nice(p.gate)}. Inference: {p.inference}.</p>
      <h3>Open repair cases</h3>
      <ul className="lab-cases">
        {s.repair_cases.map(c => <li key={c.id}><b>{c.priority}</b> {c.id} <span className="lab-chip">{nice(c.status)}</span></li>)}
      </ul>
    </section>
  );
}
