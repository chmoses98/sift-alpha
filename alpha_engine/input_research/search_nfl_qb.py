"""Market-free systematic search for NFL QB passing yards, producing independent probabilities (RESEARCH_ONLY).

No sportsbook line, Kalshi price or derived feature enters (marketfree.assert_market_free). Baseline = the QB's own shrunk history. Outputs: honest nested-search gain,
permutation-null gain, per-group importance (leave-one-group-out under a fixed structure, inner folds only), selection frequencies, and OOS/forward predictions that the
Kalshi benchmark (prop_experiment) consumes AFTER the model is fixed.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import marketfree as MF, nfl_features as nf, qb_passing as qp, search as SR

OUT = Path(__file__).resolve().parents[2] / "research/audit/input_research/experiments"
N_CONFIGS, TEST_FROM, LAST_TRAIN = 240, 2019, 2025
GROUPS_CACHE: dict = {}


def build_table(data_dir: Path):
    gm = nf.market_columns(nf.add_matchup_features(nf.build_game_table(data_dir)))
    pbp = nf.load_pbp(data_dir / "pbp", range(2010, int(gm.season.max()) + 1))
    qb = qp.build_qb_table(gm, pbp)
    q = MF.qb_market_free(qb, MF.own_script(gm))
    groups = {}
    for k, v in qp.QB_GROUPS.items():
        cols = [c for c in v if c not in qp.PARTIAL_PIT and c in q.columns]
        if k != "game_script_market" and cols:
            groups[k] = cols
    groups["game_script_own_ratings"] = ["own_spread_team", "own_abs_spread", "own_total", "own_exp_team_pts", "ix_own_trailing_x_passrate", "ix_own_total_x_pace"]
    MF.assert_market_free([c for g in groups.values() for c in g])
    return q, groups


def run(data_dir: Path, n_configs: int = N_CONFIGS, null_reps: int = 2):
    q, groups = build_table(data_dir)
    d = q[(q.season >= 2013) & q.baseline_ypg.notna() & ((q.season <= LAST_TRAIN) & q.pass_yards.notna() | (q.season > LAST_TRAIN))].reset_index(drop=True)
    r = (d.pass_yards - d.baseline_ypg).to_numpy(float)          # NaN for rows of the forward season
    keys = (d.season.astype(str) + "-" + d.week.astype(str)).to_numpy()
    res = SR.nested_search(d, r, groups, range(TEST_FROM, int(d.season.max()) + 1), n_configs=n_configs)
    pred = res["pred"]
    hist = d.season <= LAST_TRAIN
    gain = SR.summarize_gain(d[hist].reset_index(drop=True), r[hist], pred[hist.to_numpy()], keys[hist.to_numpy()])
    null = SR.permutation_null(d[hist].reset_index(drop=True), r[hist.to_numpy()], groups, range(TEST_FROM, LAST_TRAIN + 1), keys[hist.to_numpy()], reps=null_reps, n_configs=n_configs)
    chosen = [c for c in res["chosen"] if c["season"] <= LAST_TRAIN]
    names = list(groups)
    freq = {g: round(float(np.mean([g in c["config"]["groups"] for c in chosen])), 3) for g in names}
    imp = {}
    for g in names:
        deltas = np.array([c["core_inner_rel_mse"][f"drop:{g}"] - c["core_inner_rel_mse"]["full"] for c in chosen])
        imp[g] = {"mean_rel_mse_increase_when_dropped": round(float(deltas.mean()), 5), "folds_where_dropping_hurts": int((deltas > 0).sum()), "folds": int(len(deltas)),
                  "se": round(float(deltas.std(ddof=1) / np.sqrt(len(deltas))), 5)}
    model_freq = {m: round(float(np.mean([c["config"]["model"] == m for c in chosen])), 3) for m in ("ridge", "gbm")}
    out = {"schema_version": "search-nfl-qb-1.0", "status": "RESEARCH_ONLY", "market_free": True,
           "market_free_note": "No sportsbook line, Kalshi price or market-derived feature is an input; game script comes from the model's own rating-based expectation (marketfree.own_script).",
           "target": "QB1 passing yards minus the QB's own shrunk historical rate", "n_configs_per_fold": res["n_configs"], "outer_test_seasons": [TEST_FROM, LAST_TRAIN],
           "inner_k": 3, "selection_rule": "one-standard-error, simplest within 1 SE of best inner score", "nested_gain": gain, "permutation_null": null,
           "group_importance_leave_one_group_out_inner": imp, "group_selection_frequency": freq, "model_structure_frequency": model_freq, "groups": groups,
           "forward_season_config": res["chosen"][-1]["config"] if res["chosen"] and res["chosen"][-1]["season"] > LAST_TRAIN else None,
           "chosen_per_fold": [{k: v for k, v in c.items() if k != "core_inner_rel_mse"} for c in res["chosen"]]}
    mu = d[["game_id", "qb_id", "season"]].copy()
    mu["resid_pred"] = pred
    mu["baseline_ypg"] = d.baseline_ypg.to_numpy()
    mu["pass_yards"] = d.pass_yards.to_numpy()
    return out, mu


def main():
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--data-dir", required=True); ap.add_argument("--n-configs", type=int, default=N_CONFIGS); ap.add_argument("--null-reps", type=int, default=2)
    a = ap.parse_args()
    out, mu = run(Path(a.data_dir), a.n_configs, a.null_reps)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "search_nfl_qb_passing_v1.json").write_text(json.dumps(out, indent=1, default=float))
    mu.round(3).to_csv(OUT / "search_nfl_qb_passing_v1_predictions.csv", index=False)
    g = out["nested_gain"]
    print(f"nested gain {g['pct_gain']:.2f}% CI {g['ci_0.05']} seasons+ {g['seasons_positive']}/{len(g['seasons'])}; null {[round(x['pct_gain'],2) for x in out['permutation_null']]}")
    print(json.dumps(out["group_importance_leave_one_group_out_inner"], indent=0)[:1500])


if __name__ == "__main__":
    main()
