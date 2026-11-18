"""Does starter information improve V2 game forecasts? Holdout 2024-25 + 2025-26 (2,624 games), point-in-time.

V2 = the walk-forward SIM2_ST arm (special-teams lambdas, nhl-sim-2.0, parameters fitted on earlier seasons, archived in
docs/research/walk_forward_v2_wf2_20260929*). Every arm reuses the archived lambdas, seed and sim parameters; only the goalie factor
(point-in-time true talent, GoalieBook with the season's validated prior/b2b multiplier) changes:
  G1      goalie factor 1.0 (the archived SIM2_ST; re-simulated here for an identical-noise comparison)
  PROD    production V2 with no starter observation: start-share-weighted mixture over candidates
  RES     expected-starter resolver probabilities (fitted 2008-21) as mixture weights
  ORACLE  the actual starter (= what a confirmed starter gives; archived SIM2_ST_GTT definition)
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, "/home/user/NHL-edge-finder/src")
from nhl_edge.features import goalie_talent as gt
from nhl_edge.research.walk_forward import game_seed
from nhl_edge.research.walk_forward_v2 import TOTAL_LINES, _probs
from nhl_edge.sim.engine import TeamParams
from nhl_edge.sim.engine_v2 import SimV2Params, simulate_game_v2

HERE = Path(__file__).parent; REPO = Path("/home/user/NHL-edge-finder")
N_SIMS = int(sys.argv[1]) if len(sys.argv) > 1 else 4000

def main():
    wf = pd.read_csv(REPO / "docs/research/walk_forward_v2_wf2_20260929_games.csv")
    fits = json.load(open(REPO / "docs/research/walk_forward_v2_wf2_20260929.json"))["fits"]
    R = pd.read_parquet(HERE / "data/resolver_rows.parquet")
    coef = json.load(open(HERE / "results/resolver_eval.json"))["coef"]
    F = list(coef); z = R[F].to_numpy() @ np.array([coef[f] for f in F]); k = R.key.to_numpy()
    z = z - pd.Series(z).groupby(k).transform("max").to_numpy(); e = np.exp(z)
    R["p_res"] = e / pd.Series(e).groupby(k).transform("sum").to_numpy()
    R["p_v2"] = R.v2w / R.groupby("key").v2w.transform("sum")
    st = pd.read_csv(HERE / "data/starters_history.csv.gz")
    tid = {(r.game_id, bool(r.is_home)): r.team_id for r in st.itertuples()}
    H = Path(REPO / "data/history")
    shots = pd.concat([pd.read_parquet(p) for p in sorted((H / "moneypuck").glob("shots_*.parquet"))], ignore_index=True)
    games = pd.concat([pd.read_parquet(p) for p in sorted((H / "nhl").glob("games_*.parquet"))])
    glog = gt.goalie_game_log(shots, games)
    cand = {key: g for key, g in R.groupby("key")}
    recs, check = [], []
    for S in (2024, 2025):
        f = fits[str(S)]; prm = SimV2Params.from_dict(f["sim_params"])
        book = gt.GoalieBook(glog, prior_xg=float(f["goalie_prior"]["best_prior_xg"]), b2b_mult=float(f["goalie_b2b"]["b2b_mult"]))
        for r in wf[wf.season == S].itertuples(index=False):
            date = str(r.game_date); lr = book.league_ratio(date)
            fac = lambda g: (lambda t: t.factor * t.workload_mult)(book.talent(int(g), date, lr))
            arms = {"ORACLE": (r.home_gtt, r.away_gtt)}
            check.append(abs(fac(r.home_starter) - r.home_gtt))
            for arm, col in (("PROD", "p_v2"), ("RES", "p_res")):
                vals = []
                for is_home in (True, False):
                    c = cand.get(f"{r.game_id}_{tid.get((r.game_id, is_home))}")
                    vals.append(1.0 if c is None else float(sum(p * fac(g) for g, p in zip(c.cand, c[col]))))
                arms[arm] = tuple(vals)
            arms["G1"] = (1.0, 1.0)
            y_total = int(r.y_total); rec = {"game_id": r.game_id, "season": S, "game_date": date, "y_home_win": r.y_home_win, "y_total": y_total}
            for arm, (hf, af) in arms.items():
                res = simulate_game_v2(TeamParams(0, r.home, r.lam_st_home * af), TeamParams(0, r.away, r.lam_st_away * hf), game_seed(r.game_id), N_SIMS, prm)
                p = _probs(res, "", TOTAL_LINES, y_total)
                rec |= {f"{arm}_p_home_win": p["p_home_win"], f"{arm}_ll_total": p["ll_total"], **{f"{arm}_p_over_{x}": p[f"p_over_{x}"] for x in (5.5, 6.5)},
                        f"{arm}_hf": hf, f"{arm}_af": af}
            recs.append(rec)
    df = pd.DataFrame(recs); df.to_csv(HERE / "data/forecast_impact_games.csv.gz", index=False)
    rep = score(df); rep["oracle_factor_reproduction_max_abs_err"] = float(np.max(check)); rep["n_sims"] = N_SIMS
    rep["g1_reproduces_archived_SIM2_ST_p_home_win_max_abs"] = float(np.max(np.abs(df.G1_p_home_win.to_numpy() - wf.set_index("game_id").loc[df.game_id, "SIM2_ST_p_home_win"].to_numpy())))
    (HERE / "results/forecast_impact.json").write_text(json.dumps(rep, indent=1)); print(json.dumps(rep, indent=1))

def ll_bin(p, y):
    p = np.clip(p, 1e-4, 1 - 1e-4); return -(y * np.log(p) + (1 - y) * np.log(1 - p))

def score(df, nb=2000):
    y = df.y_home_win.to_numpy(); yt = df.y_total.to_numpy()
    m = {}
    for arm in ("G1", "PROD", "RES", "ORACLE"):
        m[arm] = {"winner": ll_bin(df[f"{arm}_p_home_win"].to_numpy(), y),
                  "total_ll": -df[f"{arm}_ll_total"].to_numpy(),
                  "over_5.5": ll_bin(df[f"{arm}_p_over_5.5"].to_numpy(), (yt > 5.5).astype(float)),
                  "over_6.5": ll_bin(df[f"{arm}_p_over_6.5"].to_numpy(), (yt > 6.5).astype(float))}
    dates = pd.factorize(df.game_date)[0]; nd = dates.max() + 1; rng = np.random.default_rng(20261118)
    idx_by_d = [np.where(dates == d)[0] for d in range(nd)]
    W = np.zeros((nb, len(df)))
    for b in range(nb):
        cnt = np.bincount(rng.integers(0, nd, nd), minlength=nd)
        for d in np.nonzero(cnt)[0]: W[b, idx_by_d[d]] = cnt[d]
    out = {"n_games": int(len(df)), "metric": "mean log loss (lower = better); d = arm - base, 95% date-cluster bootstrap", "levels": {}, "diffs": {}}
    for arm in m: out["levels"][arm] = {k: float(v.mean()) for k, v in m[arm].items()}
    for a, b in (("ORACLE", "PROD"), ("RES", "PROD"), ("ORACLE", "RES"), ("PROD", "G1"), ("ORACLE", "G1")):
        out["diffs"][f"{a}-{b}"] = {}
        for k in m[a]:
            dd = m[a][k] - m[b][k]; bs = (W @ dd) / W.sum(1)
            out["diffs"][f"{a}-{b}"][k] = {"d": float(dd.mean()), "ci": [float(np.quantile(bs, .025)), float(np.quantile(bs, .975))]}
    return out

if __name__ == "__main__":
    main()
