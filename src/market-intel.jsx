import React, {useState} from "react";

// Generic market-intelligence panel. Data comes from research/audit/intel/*.json (one per sport/family).
// It shows only what was collected and validated; projections are labelled by their validation verdict.
const INTEL = Object.values(import.meta.glob("../research/audit/intel/*.json", {eager: true, import: "default"}));
export const intelFor = (sport, family) => INTEL.find(i => i.sport === sport && i.market_family === family);
const f1 = v => (v == null ? "—" : Number(v).toFixed(1));
const sign = v => (v > 0 ? "+" : "") + f1(v);

export function MarketIntel({intel}) {
  const rows = intel.walk_forward_rows;
  const [eid, setEid] = useState(rows.length ? rows[rows.length - 1].event_id : null);
  const g = rows.find(r => r.event_id === eid);
  const v = intel.validation, b = intel.base_rates;
  const dist = Object.entries(b.distribution).map(([k, c]) => [Number(k), c]);
  const maxC = Math.max(...dist.map(d => d[1]));
  const supported = v.verdict === "SUPPORTED";
  return <div className="spec" aria-label={`Market intelligence ${intel.sport} ${intel.market_family} ${intel.period}`}>
    <h4>Market intelligence · {intel.sport} {intel.period} total <span className={"badge b-" + (supported ? "ok" : "warn")}>projection {v.verdict.toLowerCase().replaceAll("_", " ")}</span></h4>
    <p className="fine"><b>Outcome:</b> combined points by both teams in regulation quarter 1; Over/Under a stated line. <b>Source:</b> {intel.provenance.data_branch} @ {intel.provenance.data_commit.slice(0, 7)} ({intel.provenance.files_verified} sha256-verified files). Every row is post-game; a result is treated as available {intel.provenance.result_lag_hours_assumption}h after scheduled start (assumption, true end time not recorded).</p>
    <h5>Base rate ({b.n_games} games, 2026 season only)</h5>
    <p className="fine">Mean {b.mean} · SD {b.sd} · Over frequency: {Object.entries(b.p_over).sort((x, y) => Number(x[0]) - Number(y[0])).map(([l, p]) => `>${l}: ${(p * 100).toFixed(0)}%`).join(" · ")}</p>
    <div role="img" aria-label="Q1 combined points histogram" style={{display: "flex", alignItems: "flex-end", gap: 2, height: 60}}>
      {dist.map(([k, c]) => <div key={k} title={`${k} pts: ${c} games`} style={{height: Math.max(2, 60 * c / maxC), width: 10, background: "currentColor", opacity: 0.55}} />)}
    </div>
    <p className="fine">Points 0 to {dist[dist.length - 1][0]} left to right; spikes at 7/10/14 reflect touchdown and field-goal key numbers. {b.caveat}</p>
    <h5>Validation (walk-forward, held-out)</h5>
    <p className="fine">Team Q1 scored/allowed history with shrinkage vs prior league mean, {v.n_eval} games (both teams ≥3 prior). MAE {v.model_mae} vs baseline {v.baseline_mae}; RMSE {v.model_rmse} vs {v.baseline_rmse}; improvement {v.mae_improvement_mean} (95% CI {v.mae_improvement_ci95[0]} to {v.mae_improvement_ci95[1]}). <b>{supported ? "Supported." : "Not supported: team history does not beat the league mean on held-out games."}</b> Rule fixed in advance: {v.rule}.</p>
    <h5>Inspect a game as of kickoff</h5>
    <label>Game <select value={eid || ""} onChange={e => setEid(e.target.value)}>
      {rows.map(r => <option key={r.event_id} value={r.event_id}>{r.start_time_utc.slice(0, 10)} · {r.away} @ {r.home}</option>)}
    </select></label>
    {g && <div className="inp-grid">
      <div className="inp"><strong>Actual (post-game)</strong><p className="fine">Q1 total: {g.actual} · baseline {f1(g.baseline)} · model {f1(g.model)}</p></div>
      <div className="inp"><strong>Offense vs defense (points vs league {f1(g.league_team_mean)}/team)</strong>
        <p className="fine">{g.home} offense {sign(g.ratings.home_off)} (n={g.n_prior_home}) · {g.away} defense allows {sign(g.ratings.away_def_allowed)} (n={g.n_prior_away})</p>
        <p className="fine">{g.away} offense {sign(g.ratings.away_off)} · {g.home} defense allows {sign(g.ratings.home_def_allowed)}</p></div>
      <div className="inp"><strong>Net lean (not validated)</strong>
        <p className="fine">{g.model > g.baseline ? "Over" : "Under"} lean of {f1(Math.abs(g.model - g.baseline))} pts vs league mean from team scoring history alone. Not validated as predictive; weak on held-out data.</p></div>
      <div className="inp"><strong>Not yet available</strong>
        <p className="fine">Opening possession, first-drive tempo, pace, kicker, QB status as-of, weather, quote line (no archived pregame line is joined to this game).</p></div>
    </div>}
  </div>;
}
