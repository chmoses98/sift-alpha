"""Walk-forward check of the six-sport expansion inputs against naive baselines (RESEARCH_ONLY). Usage: python research/audit/six_sport_walkforward.py CFB_DIRS NHL_DIR MLB_DIRS
Each input value is already out of sample (ridge: earlier dates only; kernel: earlier seasons only). Baseline = the league mean of the same outcome over EARLIER seasons (same rows, same condition).
skill = 1 - MSE(input) / MSE(baseline) (Brier for probabilities). This is evidence about inputs vs naive baselines only, not about any projection model."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from alpha_engine.features import cfb_espn_ext as CF, mlb_line_ext as ML, nhl_period_ext as NH  # noqa: E402


def rows(g, cols):
    """Outcome columns per team row: cols = {name: (home_col, away_col)}."""
    h = g[["game_id"]].assign(team=g.home, **{k: g[a].to_numpy(float) for k, (a, _) in cols.items()}); a = g[["game_id"]].assign(team=g.away, **{k: g[b].to_numpy(float) for k, (_, b) in cols.items()})
    return pd.concat([h, a], ignore_index=True)


def score(t, col, y, cond=None):
    m = t[col].notna() & y.notna() & (cond if cond is not None else True); d = pd.DataFrame({"s": t.season[m], "p": t[col][m], "y": y[m].astype(float)})
    seas = sorted(d.s.unique()); per = []
    for s in seas[1:]:
        cur = d[d.s == s]; base = d.y[d.s < s].mean(); per.append((int(s), len(cur), float(((cur.p - cur.y) ** 2).mean()), float(((base - cur.y) ** 2).mean())))
    if not per:
        return None
    n = sum(p[1] for p in per); mi = sum(p[1] * p[2] for p in per) / n; mb = sum(p[1] * p[3] for p in per) / n
    return {"n": n, "seasons": [p[0] for p in per], "mse_input": round(mi, 6), "mse_baseline": round(mb, 6), "skill_pct": round(100 * (1 - mi / mb), 2), "seasons_better": sum(p[2] < p[3] for p in per), "seasons_total": len(per)}


def main(a):
    out = {"status": "RESEARCH_ONLY", "note": __doc__.split("\n", 1)[1].strip(), "sports": {}}
    # CFB
    g = CF.load_raw(a[0])["games"]; t = CF.compute({"games": g})["team"]
    for s in "ha":
        g[s + "reg"] = g[[f"{s}q{k}" for k in (1, 2, 3, 4)]].sum(axis=1); g[s + "h1"] = g[s + "q1"] + g[s + "q2"]; g[s + "h2"] = g[s + "q3"] + g[s + "q4"]; g[s + "ypp"] = g[s + "_yds"] / g[s + "_plays"]
    g["hft"] = g.first_td; g["aft"] = -g.first_td
    sw = lambda *c: {k: (f"h{k}" if f"h{k}" in g else f"h_{k}", f"a{k}" if f"a{k}" in g else f"a_{k}") for k in c}
    o = rows(g, sw("q1", "q2", "q3", "q4", "reg", "h1", "h2", "score", "td", "ft", "ypp", "rush", "drv")); x = rows(g, {k: (b, a_) for k, (a_, b) in sw("q1", "reg", "h1", "h2", "score", "drv").items()})
    t = t.merge(o, on=["game_id", "team"]).merge(x, on=["game_id", "team"], suffixes=("", "_o")); t["n_per"] = t.game_id.map(g.set_index("game_id").n_per); win = (t.score > t.score_o).astype(float)
    R = {"cfbx_pts_pre (expected regulation points)": score(t, "cfbx_pts_pre", t.reg), "cfbx_mar_pre (expected regulation margin)": score(t, "cfbx_mar_pre", t.reg - t.reg_o)}
    for k in (1, 2, 3, 4): R[f"qj_q{k}_zero_pre"] = score(t, f"qj_q{k}_zero_pre", (t[f"q{k}"] == 0).astype(float))
    R["qj_all4_pre"] = score(t, "qj_all4_pre", ((t.q1 > 0) & (t.q2 > 0) & (t.q3 > 0) & (t.q4 > 0)).astype(float))
    R["pml_lead_q1_pre"] = score(t, "pml_lead_q1_pre", (t.q1 > t.q1_o).astype(float)); R["pml_tie_q1_pre"] = score(t, "pml_tie_q1_pre", (t.q1 == t.q1_o).astype(float))
    R["pml_lead_half_pre"] = score(t, "pml_lead_half_pre", (t.h1 > t.h1_o).astype(float)); R["pml_tie_half_pre"] = score(t, "pml_tie_half_pre", (t.h1 == t.h1_o).astype(float))
    R["pml_win_2h_pre"] = score(t, "pml_win_2h_pre", (t.h2 > t.h2_o).astype(float)); R["rtc_tie_pre"] = score(t, "rtc_tie_pre", (t.n_per > 4).astype(float))
    R["hft_win_lead_pre"] = score(t, "hft_win_lead_pre", win, t.h1 > t.h1_o); R["hft_win_trail_pre"] = score(t, "hft_win_trail_pre", win, t.h1 < t.h1_o); R["htc_win_tied_pre"] = score(t, "htc_win_tied_pre", win, t.h1 == t.h1_o)
    R["tdc_mean_pre"] = score(t, "tdc_mean_pre", t.td)
    for k in (2, 4, 6): R[f"tdc_ge{k}_pre"] = score(t, f"tdc_ge{k}_pre", (t.td >= k).astype(float).where(t.td.notna()))
    R["ftd_first_pre"] = score(t, "ftd_first_pre", (t.ft == 1).astype(float).where(t.ft.notna())); R["ftd_none_pre"] = score(t, "ftd_none_pre", (t.ft == 0).astype(float).where(t.ft.notna()))
    R["nyp_exp_pre"] = score(t, "nyp_exp_pre", t.ypp); R["sra_exp_pre"] = score(t, "sra_exp_pre", t.rush); R["sra_script_pre"] = score(t, "sra_script_pre", t.rush)
    R["ods_exp_pre"] = score(t, "ods_exp_pre", t.drv); R["ods_share_pre"] = score(t, "ods_share_pre", t.drv / (t.drv + t.drv_o))
    out["sports"]["CFB"] = {"games": int(len(g)), "results": R, "not_assessed": ["qj_hi_q*", "pst_q*", "tdc_var_pre", "pml_tie_2h_pre", "nyp_off_pre", "nyp_def_pre"]}
    # NHL
    g = NH.load_raw(a[1])["games"]; t = NH.compute({"games": g})["team"]
    o = rows(g, {f"p{k}": (f"h_p{k}", f"a_p{k}") for k in (1, 2, 3)}); x = rows(g, {f"p{k}": (f"a_p{k}", f"h_p{k}") for k in (1, 2, 3)})
    t = t.merge(o, on=["game_id", "team"]).merge(x, on=["game_id", "team"], suffixes=("", "_o")); d2 = t.p1 + t.p2 - t.p1_o - t.p2_o; reg = t.p1 + t.p2 + t.p3; reg_o = t.p1_o + t.p2_o + t.p3_o
    R = {"nhlx_g_pre (expected regulation goals)": score(t, "nhlx_g_pre", reg), "nhlx_mar_pre (expected regulation margin)": score(t, "nhlx_mar_pre", reg - reg_o), "spu_total_pre": score(t, "spu_total_pre", reg + reg_o),
         "pes_lead_p2_pre": score(t, "pes_lead_p2_pre", (t.p1 > t.p1_o).astype(float)), "pes_tie_p2_pre": score(t, "pes_tie_p2_pre", (t.p1 == t.p1_o).astype(float)),
         "pes_lead_p3_pre": score(t, "pes_lead_p3_pre", (d2 > 0).astype(float)), "pes_tie_p3_pre": score(t, "pes_tie_p3_pre", (d2 == 0).astype(float)),
         "pes_p3_gf_lead_pre": score(t, "pes_p3_gf_lead_pre", t.p3, d2 > 0), "pes_p3_gf_tie_pre": score(t, "pes_p3_gf_tie_pre", t.p3, d2 == 0), "pes_p3_gf_trail_pre": score(t, "pes_p3_gf_trail_pre", t.p3, d2 < 0)}
    for k in (1, 2, 3):
        R[f"ppc_mu_p{k}_pre"] = score(t, f"ppc_mu_p{k}_pre", t[f"p{k}"]); R[f"ppc_tot_ge2_p{k}_pre"] = score(t, f"ppc_tot_ge2_p{k}_pre", (t[f"p{k}"] + t[f"p{k}_o"] >= 2).astype(float))
    out["sports"]["NHL"] = {"games": int(len(g)), "results": R, "not_assessed": ["ppc_cov_p12_pre", "spu_se_pre"]}
    # MLB
    g = ML.load_raw(a[2])["games"]; t = ML.compute({"games": g})["team"]; g["h_late"] = g.h_r - g.h_r5; g["a_late"] = g.a_r - g.a_r5
    c = {k: (f"h_{k}", f"a_{k}") for k in ("r1", "r5", "r", "late", "sp_outs", "sp_bf", "sp_np")}; o = rows(g, c); x = rows(g, {k: (b, a_) for k, (a_, b) in c.items() if k in ("r1", "r5", "r")})
    t = t.merge(o, on=["game_id", "team"]).merge(x, on=["game_id", "team"], suffixes=("", "_o")); gi = g.set_index("game_id"); t["walkoff"] = t.game_id.map(gi.walkoff); t["n_inn"] = t.game_id.map(gi.n_inn)
    R = {"mlbx_runs_pre (expected runs)": score(t, "mlbx_runs_pre", t.r), "mlbx_mar_pre (expected run margin)": score(t, "mlbx_mar_pre", t.r - t.r_o), "fi_exp_pre": score(t, "fi_exp_pre", t.r1),
         "fi_score_pre": score(t, "fi_score_pre", (t.r1 > 0).astype(float)), "fi_nrfi_pre": score(t, "fi_nrfi_pre", (t.r1 + t.r1_o == 0).astype(float)), "f5_exp_pre": score(t, "f5_exp_pre", t.r5),
         "f5_late_exp_pre": score(t, "f5_late_exp_pre", t.late), "f5_lead_pre": score(t, "f5_lead_pre", (t.r5 > t.r5_o).astype(float)), "f5_tie_pre": score(t, "f5_tie_pre", (t.r5 == t.r5_o).astype(float)),
         "wo_walkoff_pre": score(t, "wo_walkoff_pre", t.walkoff), "wo_extras_pre": score(t, "wo_extras_pre", (t.n_inn > 9).astype(float)), "spw_outs_pre": score(t, "spw_outs_pre", t.sp_outs),
         "spw_bf_pre": score(t, "spw_bf_pre", t.sp_bf), "spw_np_pre": score(t, "spw_np_pre", t.sp_np)}
    for k in (18, 21, 24, 27): R[f"hook_ge{k}_pre"] = score(t, f"hook_ge{k}_pre", (t.sp_bf >= k).astype(float).where(t.sp_bf.notna()))
    for k in (15, 16, 18, 19): R[f"exb_ge{k}_pre"] = score(t, f"exb_ge{k}_pre", (t.sp_outs >= k).astype(float).where(t.sp_outs.notna()))
    out["sports"]["MLB"] = {"games": int(len(g)), "results": R, "not_assessed": []}
    (Path(__file__).parent / "six_sport_walkforward.json").write_text(json.dumps(out, indent=1) + "\n")
    for sp, v in out["sports"].items():
        for k, r in v["results"].items():
            print(sp, k, None if r is None else (r["skill_pct"], f"{r['seasons_better']}/{r['seasons_total']}", r["n"]))


if __name__ == "__main__":
    main(sys.argv[1:])
