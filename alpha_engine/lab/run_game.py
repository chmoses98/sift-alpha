"""Run the game-level laboratory end to end (RESEARCH_ONLY).  usage: python -m alpha_engine.lab.run_game --data DIR --out research/audit/lab [--work DIR]"""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
import numpy as np
import pandas as pd
from alpha_engine.input_research import nfl_features as nf, stats as S
from . import game_lab as GL


def load_inputs(data: Path, work: Path):
    gtp, tgp = work / "game_table.parquet", work / "tg.parquet"
    if gtp.exists() and tgp.exists():
        return pd.read_parquet(gtp), pd.read_parquet(tgp)
    gt = nf.add_matchup_features(nf.build_game_table(data, 2010, 2025))
    pbp = nf.load_pbp(data / "pbp", sorted(gt["season"].unique()))
    tg = nf.team_games_from_pbp(pbp)
    work.mkdir(parents=True, exist_ok=True)
    gt.to_parquet(gtp); tg.to_parquet(tgp)
    return gt, tg


def main_effects(rows):
    """Average selection/validation log-score gain of stage-1 configs WITH vs WITHOUT each optional group (a descriptive input-importance read-out; it is not a test)."""
    out = {}
    for g in GL.OPTIONAL:
        w = [r for r in rows if g in r["config"]["groups"]]
        wo = [r for r in rows if g not in r["config"]["groups"]]
        out[g] = dict(sel_with=float(np.mean([r["metrics"]["sel"]["mean"] for r in w])), sel_without=float(np.mean([r["metrics"]["sel"]["mean"] for r in wo])),
                      val_with=float(np.mean([r["metrics"]["val"]["mean"] for r in w])), val_without=float(np.mean([r["metrics"]["val"]["mean"] for r in wo])), pit=GL.GROUP_PIT[g])
        out[g]["sel_delta"] = out[g]["sel_with"] - out[g]["sel_without"]; out[g]["val_delta"] = out[g]["val_with"] - out[g]["val_without"]
    r_axis = {}
    for key in ("half_life", "carry", "adjust"):
        vals = sorted({str(r["config"]["rating"][key]) for r in rows})
        r_axis[key] = {v: dict(sel=float(np.mean([r["metrics"]["sel"]["mean"] for r in rows if str(r["config"]["rating"][key]) == v])),
                               val=float(np.mean([r["metrics"]["val"]["mean"] for r in rows if str(r["config"]["rating"][key]) == v]))) for v in vals}
    return dict(groups=out, rating_axes=r_axis)


def run(data: Path, out: Path, work: Path, targets=("margin", "total", "home_pts", "away_pts"), n_boot=1000):
    gt, tg = load_inputs(data, work)
    report = {"lab": "game/1", "targets": {}}
    preds = []
    for t in targets:
        t0 = time.time()
        lab = GL.GameLab(gt, tg, out / f"ledger_game_{t}.jsonl", work / "cache", n_boot=n_boot)
        lab.stage1(t); lab.stage2(t)
        sel = lab.select(t)
        best, ref = sel["best"], sel["reference"]
        # paired best-vs-reference gain on VALIDATION (a single pre-specified comparison)
        yb = lab.target(t); ok = ~np.isnan(yb)
        P = lab.final_predictions(t, best["config"]); pr = lab.final_predictions(t, dict(ref["config"], model="ridge", dist="normal"))
        val = np.isin(lab.seasons, lab.val_seasons) & ok
        from . import dists
        lb = dists.int_logscore(best["config"]["dist"], yb, P["mu"].to_numpy(), P["sigma"].to_numpy()); lr = dists.int_logscore("normal", yb, pr["mu"].to_numpy(), pr["sigma"].to_numpy())
        lc = dists.int_logscore("normal", yb, P["mu0"].to_numpy(), P["sigma0"].to_numpy())
        boot = lab.boot("val", val)
        paired = boot.summarize((lb - lr)[val]); vs_clim = boot.summarize((lb - lc)[val])
        s1 = [r for r in lab.led.select(lab="game/1", stage=1, target=t)]
        top = sorted(lab.led.select(lab="game/1", target=t), key=lambda r: -r["metrics"]["sel"]["mean"])[:10]
        report["targets"][t] = dict(
            n_experiments=sel["n_experiments"], n_stage1=sel["n_stage1"], n_stage2=sel["n_stage2"], n_selection_positive=sel["n_selection_positive"], n_validation_positive=sel["n_validation_positive"],
            n_bh_q05_on_selection=sel["n_bh_q05"], selected=dict(config=best["config"], selection=best["metrics"]["sel"], validation=best["metrics"]["val"], bh_q=sel["best_bh_q"],
                                                                  rmse_val=best["metrics"]["rmse_val"]),
            reference=dict(config=ref["config"], selection=ref["metrics"]["sel"], validation=ref["metrics"]["val"], rmse_val=ref["metrics"]["rmse_val"]),
            validation_selected_vs_reference=dict(mean=paired["mean"], ci=paired["ci_0.05"]), validation_selected_vs_climatology=dict(mean=vs_clim["mean"], ci=vs_clim["ci_0.05"]),
            top10=[dict(stage=r["config"]["stage"], model=r["config"]["model"], dist=r["config"]["dist"], groups=r["config"]["groups"], rating=r["config"]["rating"],
                        sel=r["metrics"]["sel"]["mean"], val=r["metrics"]["val"]["mean"], rmse_val=r["metrics"]["rmse_val"]) for r in top],
            main_effects=main_effects(s1), seconds=round(time.time() - t0))
        P["target"] = t
        preds.append(P)
        print(t, "experiments", sel["n_experiments"], "best sel", round(best["metrics"]["sel"]["mean"], 4), "val", round(best["metrics"]["val"]["mean"], 4), round(time.time() - t0), "s", flush=True)
    out.mkdir(parents=True, exist_ok=True)
    pd.concat(preds).to_parquet(work / "game_predictions.parquet")
    (out / "game_lab_report.json").write_text(json.dumps(report, indent=1, default=float))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--data", required=True); ap.add_argument("--out", required=True); ap.add_argument("--work", required=True)
    a = ap.parse_args()
    run(Path(a.data), Path(a.out), Path(a.work))
