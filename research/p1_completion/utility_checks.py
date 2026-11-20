"""Efficient walk-forward utility checks for the inputs certified on 2026-11-20 (RESEARCH_ONLY). Not a betting claim and not certification.

Every input is already point-in-time (each row uses only earlier games), so scoring it against the realised outcome of the row's own game on later seasons is a walk-forward
test. Each check compares squared error against a sensible baseline on the same rows, with a game-clustered bootstrap 95% CI of the MSE difference (negative = input better).
    python research/p1_completion/utility_checks.py RAW_DIR OUT.json [cbb]
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def boot(err_a, err_b, groups, n=1000, seed=0):
    d = pd.DataFrame({"g": groups, "x": np.asarray(err_a) - np.asarray(err_b)}).groupby("g").x.agg(["sum", "count"])
    s, c = d["sum"].to_numpy(), d["count"].to_numpy(); rng = np.random.default_rng(seed); k = len(d)
    bs = [(s[i].sum() / c[i].sum()) for i in (rng.integers(0, k, k) for _ in range(n))]
    return [round(float(np.quantile(bs, 0.025)), 4), round(float(np.quantile(bs, 0.975)), 4)]


def compare(name, y, pred, base, groups, base_name):
    ok = ~(np.isnan(y) | np.isnan(pred) | np.isnan(base)); y, pred, base, groups = y[ok], pred[ok], base[ok], np.asarray(groups)[ok]
    ea, eb = (y - pred) ** 2, (y - base) ** 2
    return {"check": name, "n": int(ok.sum()), "mse_input": round(float(ea.mean()), 4), "mse_baseline": round(float(eb.mean()), 4), "baseline": base_name,
            "delta_mse": round(float(ea.mean() - eb.mean()), 4), "ci95": boot(ea, eb, groups), "skill_vs_baseline": round(float(1 - ea.mean() / eb.mean()), 4)}


def nfl(raw):
    from alpha_engine.features import nfl_pbp_ext4 as N4, nfl_qb_ext8 as Q, nfl_team_ext8 as T
    R = Path(raw) / "NFL"; out = []
    t = T.compute(T.load_raw(R / "pbp", R / "schedules/games.csv"))["team"]
    tg = T._team_games(T.load_raw(R / "pbp", R / "schedules/games.csv"))[["game_id", "team", "pts", "pts_a", "td"]]
    f = t.merge(tg, on=["game_id", "team"]); f = f[f.season.between(2016, 2025)]
    lg = f.groupby("season").pts.transform("mean").to_numpy()          # in-sample league mean (a generous baseline)
    out.append(compare("NFL team points: mtp_mean_pre vs same-season league mean", f.pts.to_numpy(float), f.mtp_mean_pre.to_numpy(float), lg, f.game_id, "season league mean (in-sample)"))
    try:
        b4 = N4.compute(N4.load_raw(R / "pbp", R / "schedules/games.csv"))["team"][["game_id", "team", "pfa_exp_points_pre"]]
        g = f.merge(b4, on=["game_id", "team"])
        out.append(compare("NFL team points: mtp_mean_pre vs certified batch-4 pfa_exp_points_pre", g.pts.to_numpy(float), g.mtp_mean_pre.to_numpy(float), g.pfa_exp_points_pre.to_numpy(float), g.game_id, "nfl.team_points_for_against_rates (certified)"))
        g2 = g.assign(avg=0.5 * (g.mtp_mean_pre + g.pfa_exp_points_pre))
        out.append(compare("NFL team points: average of drive model and batch-4 vs batch-4 alone", g2.pts.to_numpy(float), g2.avg.to_numpy(float), g2.pfa_exp_points_pre.to_numpy(float), g2.game_id, "batch-4 alone"))
    except Exception as e:                                                # noqa: BLE001
        out.append({"check": "batch-4 comparison", "error": repr(e)})
    out.append(compare("NFL team TD count: mtd_lambda_pre vs league mean", f.td.to_numpy(float), f.mtd_lambda_pre.to_numpy(float), f.groupby("season").td.transform("mean").to_numpy(), f.game_id, "season league mean (in-sample)"))
    m = (f.pts - f.pts_a - f.mtp_margin_pre).abs().to_numpy(); z = m / f.hms_sd_pre.to_numpy()
    out.append({"check": "NFL margin: conditional SD calibration", "n": int(len(z)), "share_abs_resid_within_1sd": round(float((z <= 1).mean()), 4), "normal_expectation": 0.6827,
                "corr_sd_vs_abs_resid": round(float(np.corrcoef(f.hms_sd_pre, m)[0, 1]), 4)})
    q = Q.compute(Q.load_raw(R / "pbp", R / "schedules/games.csv"))["team"]
    _, a = Q._attempts(Q.load_raw(R / "pbp", R / "schedules/games.csv"))
    act = a.groupby(["game_id", "passer_player_id"]).agg(att=("int", "size"), ints=("int", "sum"), comp=("comp", "sum"), tds=("td", "sum")).reset_index().rename(columns={"passer_player_id": "team"})
    g = q.merge(act, on=["game_id", "team"]); g = g[(g.att >= 15) & g.season.between(2016, 2025)]
    lgi = g.groupby("season").apply(lambda x: x.ints.sum() / x.att.sum()).rename("lgi").reset_index(); g = g.merge(lgi, on="season")
    out.append(compare("NFL QB interceptions given attempts: int_exp_rate_pre x att vs league rate x att", g.ints.to_numpy(float), (g.int_exp_rate_pre * g.att).to_numpy(float), (g.lgi * g.att).to_numpy(float), g.game_id, "season league INT rate (in-sample)"))
    lgc = g.groupby("season").apply(lambda x: x.comp.sum() / x.att.sum()).rename("lgc").reset_index(); g = g.merge(lgc, on="season")
    out.append(compare("NFL QB completions given attempts: qcc_p_pre x att vs league rate x att", g.comp.to_numpy(float), (g.qcc_p_pre * g.att).to_numpy(float), (g.lgc * g.att).to_numpy(float), g.game_id, "season league completion rate (in-sample)"))
    out.append(compare("NFL QB passing TDs given attempts: qbx_adj_td_rate_pre x att vs league rate x att", g.tds.to_numpy(float), (g.qbx_adj_td_rate_pre * g.att).to_numpy(float),
                       (g.groupby("season").tds.transform("sum") / g.groupby("season").att.transform("sum") * g.att).to_numpy(float), g.game_id, "season league TD rate (in-sample)"))
    return out


def mlb(raw):
    from alpha_engine.features import mlb_pa_core as C, mlb_pitcher_ext7 as P, mlb_team_ext7 as T
    r = C.load_raw(Path(raw) / "MLB" / "cache"); out = []
    t = T.compute(r)["team"]; g, p = C.prepared(r); tg = C.team_games(g)[["game_id", "team", "runs"]]
    f = t.merge(tg, on=["game_id", "team"])
    out.append(compare("MLB team runs: rd_mu_pre vs same-season league mean", f.runs.to_numpy(float), f.rd_mu_pre.to_numpy(float), f.groupby("season").runs.transform("mean").to_numpy(), f.game_id, "season league mean (in-sample)"))
    for k in (4, 5):
        y = (f.runs >= k).astype(float).to_numpy(); base = f.groupby("season").runs.transform(lambda x: (x >= k).mean()).to_numpy()
        out.append(compare(f"MLB team runs >= {k}: rd_p_ge{k}_pre Brier vs league frequency", y, f[f"rd_p_ge{k}_pre"].to_numpy(float), base, f.game_id, "season league frequency (in-sample)"))
    # starter strikeouts: evaluate the candidate row of the pitcher who ACTUALLY started (evaluation only; the input itself never knows who starts)
    pc = P.compute(r)["team"]
    s = p[p.is_start].groupby(["game_id", "pit"]).agg(bf=("k", "size"), ks=("k", "sum")).reset_index().rename(columns={"pit": "team"})
    m = pc.merge(s, on=["game_id", "team"]); m = m[m.bf >= 9]
    lg = m.groupby("season").apply(lambda x: x.ks.sum() / x.bf.sum()).rename("lg").reset_index(); m = m.merge(lg, on="season")
    out.append(compare("MLB starter strikeouts given BF: kr_log5_k_pre x BF vs league K% x BF", m.ks.to_numpy(float), (m.kr_log5_k_pre * m.bf).to_numpy(float), (m.lg * m.bf).to_numpy(float), m.game_id, "season league K% (in-sample)"))
    out.append(compare("MLB starter strikeouts given BF: log5 vs pitcher-only kr_pit_k_pre", m.ks.to_numpy(float), (m.kr_log5_k_pre * m.bf).to_numpy(float), (m.kr_pit_k_pre * m.bf).to_numpy(float), m.game_id, "pitcher K% only"))
    e = m.assign(e1=m.tto_exp_bf_1_pre + m.tto_exp_bf_2_pre + m.tto_exp_bf_3_pre, bf27=np.minimum(m.bf, 27))
    out.append(compare("MLB starter batters faced (capped 27): sum of tto_exp_bf vs league mean", e.bf27.to_numpy(float), e.e1.to_numpy(float), e.groupby("season").bf27.transform("mean").to_numpy(), e.game_id, "season league mean (in-sample)"))
    out.append({"note": "starter rows are evaluated only for the candidate who actually started; the archive has no pregame probable-pitcher vintages, so a live consumer must match the announced probable"})
    return out


def cbb(raw):
    from alpha_engine.features import cbb_player_ext6 as X
    rr = X.load_raw(Path(raw) / "CBB"); f = X.compute(rr)["team"]
    bx = X._prep(rr); act = bx[bx.pid.notna() & (bx["min"] > 0)][["game_id", "pid", "pts", "reb", "ast", "fg3m", "min"]].rename(columns={"pid": "team"}); act["team"] = act.team.astype("int64")
    g = f.merge(act, on=["game_id", "team"], how="left"); g = g[g.season.between(2020, 2027)]
    for c in ("pts", "reb", "ast", "fg3m"):
        g[c] = g[c].fillna(0.0)                                         # did not appear = 0 (props settle on appearance; this is a forecasting check)
    out = []
    for stat, col in (("pts", "pu_pts40_pre"), ("reb", "pu_reb40_pre"), ("ast", "pu_ast40_pre")):
        pred = (g[col] * g.aux_min_ewm_pre / 40).to_numpy(float)
        out.append(compare(f"CBB player {stat}: per-40 (shrunk) x EWM minutes vs last-15 mean (psd_{stat}_mean_pre)", g[stat].to_numpy(float), pred, g[f"psd_{stat}_mean_pre"].to_numpy(float), g.game_id, "player's last-15 mean"))
    y = (g.fg3m >= 1).astype(float).to_numpy()
    base = np.clip(g.psd_fg3m_mean_pre.to_numpy(float), 0, None); base = 1 - np.exp(-base)            # Poisson from the recent mean
    out.append(compare("CBB player threes >= 1: pc_p_ge1_pre Brier vs Poisson(last-15 mean)", y, g.pc_p_ge1_pre.to_numpy(float), base, g.game_id, "Poisson from last-15 threes mean"))
    y2 = (g.fg3m >= 2).astype(float).to_numpy(); m2 = np.clip(g.psd_fg3m_mean_pre.to_numpy(float), 0, None); b2 = 1 - np.exp(-m2) * (1 + m2)
    out.append(compare("CBB player threes >= 2: pc_p_ge2_pre Brier vs Poisson(last-15 mean)", y2, g.pc_p_ge2_pre.to_numpy(float), b2, g.game_id, "Poisson from last-15 threes mean"))
    return out


if __name__ == "__main__":
    raw, out = sys.argv[1], Path(sys.argv[2]); res = json.loads(out.read_text()) if out.exists() else {}
    if "cbb" in sys.argv[3:]:
        res["CBB"] = cbb(raw)
    else:
        res["NFL"] = nfl(raw); res["MLB"] = mlb(raw)
    res["status"] = "RESEARCH_ONLY"; res["note"] = "inputs vs naive or certified baselines on realised outcomes; in-sample league means make the baselines generous; not a betting claim"
    out.write_text(json.dumps(res, indent=1) + "\n"); print(json.dumps(res, indent=1)[:6000])
