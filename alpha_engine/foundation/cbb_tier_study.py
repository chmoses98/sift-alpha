"""Operation Data Foundation, CBB: is the conference-tier margin bias of frozen ``pure-0.2.0`` genuine or an artifact?

RESEARCH_ONLY, descriptive and out-of-sample tests on the same frozen records ``alpha-cbb-mean-0.1`` reads (``cbb_mean.build``;
``pure-0.2.0`` records only, so Waves 14-16 and their ``pure-0.5.0`` base are never opened). Residual = actual home margin
minus the frozen projected margin. ``ph`` / ``lh`` = (home is power) - (away is power) / (home is low-major) - (away is
low-major), with the tier lists fixed in ``cbb_mean`` before its regressions were run.

Alternative explanations tested, each as a regression of the residual on the projected margin, the two tier terms and the
candidate confounder (pairs bootstrap over games):

* opponent quality: the frozen team quality difference (``net26_d``: 2025-26 net rating; ``pre_d``: preseason prior) and the
  projected margin itself; if the tier terms vanish once quality is in, the "tier" effect is a rating-gap effect;
* venue: home-site vs neutral-site games separately;
* early-season priors: games where either team had played 0-1 games vs 2+ (the frozen ``games_seen``);
* selection: Kalshi-listed vs ESPN-lined subsets, and the share of verified finals that have a frozen projection;
* market: the ESPN line's own residual on the tier terms (a real structural miss should be priced by the market);
* out of sample: tier coefficients fitted on slates before the median slate, applied unchanged to the later slates
  (margin abs error and normal NLL with the frozen sd), game-level paired bootstrap.

Multi-season validation needs game-level data that is in no repository this session can read
(``research/data_foundation_ops/CBB/MULTISEASON_GAME_DATA_SPEC.md``); this study is one season by construction.
``python -m alpha_engine.foundation.cbb_tier_study --arch DIR`` writes ``research/data_foundation_ops/CBB/conference_tier_study.json``.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

from . import cbb_mean as M
from . import contract as C

OUT = C.OPS / "CBB" / "conference_tier_study.json"


def nll_normal(y, mu, sd):
    sd = np.maximum(np.asarray(sd, float), 1e-6)
    return 0.5 * np.log(2 * np.pi * sd ** 2) + 0.5 * ((np.asarray(y, float) - mu) / sd) ** 2


def prep(g: pd.DataFrame) -> pd.DataFrame:
    d = g.copy()
    d["rm"] = d["y_m"] - d["margin"]; d["km"] = d["y_m"] - d["mk_m"]
    d["th"] = d["conf_h"].map(M.tier); d["ta"] = d["conf_a"].map(M.tier)
    d["ph"] = (d["th"] == "P").astype(float) - (d["ta"] == "P"); d["lh"] = (d["th"] == "L").astype(float) - (d["ta"] == "L")
    d["net26_d"] = d["net26_h"] - d["net26_a"]; d["pre_d"] = d["pre_h"] - d["pre_a"]
    d["gmin"] = np.minimum(d["hgs"], d["ags"])
    return d


def tier_terms(res: dict) -> dict:
    c = res["coef"]
    return dict(n=res["n"], ph=c["ph"], lh=c["lh"], margin=c.get("margin"))


def out_of_sample(d: pd.DataFrame, seed: int = 23) -> dict:
    slates = sorted(d["slate"].unique()); cut = slates[len(slates) // 2]
    tr, te = d[d["slate"] < cut], d[d["slate"] >= cut].copy()
    out = {"split_slate": cut, "train_games": int(len(tr)), "test_games": int(len(te))}
    for name, xs in (("tier_only", ["ph", "lh"]), ("margin_slope_only", ["margin"]), ("margin_slope_and_tier", ["margin", "ph", "lh"])):
        X = np.column_stack([np.ones(len(tr))] + [tr[c].to_numpy(float) for c in xs]); b = np.linalg.lstsq(X, tr["rm"].to_numpy(float), rcond=None)[0]
        Xt = np.column_stack([np.ones(len(te))] + [te[c].to_numpy(float) for c in xs]); adj = te["margin"].to_numpy(float) + Xt @ b
        y = te["y_m"].to_numpy(float); m0 = te["margin"].to_numpy(float); sd = te["msd"].to_numpy(float)
        rows = {}
        for metric, f in (("abs_error", lambda mu: np.abs(y - mu)), ("normal_nll_frozen_sd", lambda mu: nll_normal(y, mu, sd))):
            bs = C.paired_cluster_bootstrap(f(adj) - f(m0), te["game_id"].to_numpy(), seed=seed)
            rows[metric] = dict(corrected=float(f(adj).mean()), frozen=float(f(m0).mean()), diff=bs["mean"], ci95=[bs["lo"], bs["hi"]], p=bs["p_two_sided"])
        out[name] = dict(fitted_on_train=dict(zip(["const"] + xs, map(float, b))), test=rows)
    return out


def run(arch: Path, repo: Path) -> dict:
    g, checks, tips, meta = M.build(arch, repo)
    d = prep(g)
    base = ["margin", "ph", "lh"]
    reg = lambda df, xs, y="rm": tier_terms(M._ols_ci(df, y, xs))
    hs, ne = d[d["site"] == "home"], d[d["site"] == "neutral"]
    early, later = d[d["gmin"] <= 1], d[d["gmin"] >= 2]
    first, second = d[d["slate"] < sorted(d["slate"].unique())[len(d["slate"].unique()) // 2]], d[d["slate"] >= sorted(d["slate"].unique())[len(d["slate"].unique()) // 2]]
    lined = d[d["mk_m"].notna()]
    res = dict(
        full_sample=reg(d, base),
        opponent_quality=dict(with_2025_26_net_rating_diff=reg(d, base + ["net26_d"]), with_preseason_prior_diff=reg(d, base + ["pre_d"]),
                              with_both=reg(d, base + ["net26_d", "pre_d"])),
        venue=dict(home_site=reg(hs, base), neutral_site=reg(ne, base) if len(ne) >= 30 else None, n_neutral=int(len(ne))),
        early_season=dict(either_team_0_or_1_games=reg(early, base), both_teams_2_plus_games=reg(later, base)),
        time_halves=dict(first_half_slates=reg(first, base), second_half_slates=reg(second, base)),
        selection=dict(espn_lined_games=reg(lined, base), n_lined=int(len(lined)),
                       verified_finals_without_frozen_projection=meta["audit"].get("period_score_games_without_incumbent_projection"),
                       verified_finals_used=meta["audit"].get("used")),
        market=dict(espn_line_residual_on_tier=reg(lined, ["mk_m", "ph", "lh"], y="km"), model_minus_line_on_tier=reg(lined.assign(gap=lined["mk_m"] - lined["margin"]), base, y="gap")),
        out_of_sample=out_of_sample(d),
        tier_composition=d.assign(pair=d["th"] + d["ta"]).groupby("pair").agg(n=("rm", "size"), mean_resid=("rm", "mean"), mean_proj_margin=("margin", "mean")).reset_index().to_dict("records"),
    )
    # ---- reading
    fs = res["full_sample"]; oq = res["opponent_quality"]["with_both"]; oos = res["out_of_sample"]["margin_slope_and_tier"]["test"]
    sig = lambda t: t is not None and (t["ci95"][0] > 0 or t["ci95"][1] < 0)
    survives_quality = sig(oq["ph"]) or sig(oq["lh"])
    oos_gain = oos["abs_error"]["ci95"][1] < 0 or oos["normal_nll_frozen_sd"]["ci95"][1] < 0
    oos_tier_only = res["out_of_sample"]["tier_only"]["test"]
    reading = dict(
        tier_terms_full_sample=dict(ph=fs["ph"], lh=fs["lh"]),
        survives_team_quality_controls=bool(survives_quality),
        out_of_sample_margin_slope_and_tier=oos, out_of_sample_tier_only=oos_tier_only,
        out_of_sample_gain_significant=bool(oos_gain),
        market_prices_tier=sig(res["market"]["model_minus_line_on_tier"]["ph"]) or sig(res["market"]["model_minus_line_on_tier"]["lh"]),
        market_residual_shows_tier=sig(res["market"]["espn_line_residual_on_tier"]["ph"]) or sig(res["market"]["espn_line_residual_on_tier"]["lh"]),
    )
    verdict = ("GENUINE_BUT_NOT_YET_EXPLOITABLE" if survives_quality and not oos_gain else "GENUINE_AND_PREDICTIVE_ONE_SEASON" if survives_quality and oos_gain
               else "EXPLAINED_BY_TEAM_QUALITY")
    return dict(schema="sift-foundation-study/1", status="RESEARCH_ONLY", sport="CBB", incumbent="pure-0.2.0 (frozen records only; Waves 14-16 untouched)",
                games=int(len(d)), slates=int(d["slate"].nunique()), first_tip=str(d["tip"].min()), last_tip=str(d["tip"].max()),
                checks=checks, results=res, reading=reading, verdict=verdict,
                limitations=["one season, two weeks; every coefficient has wide intervals",
                             "tier lists are hand-defined (cbb_mean.TIER_P / TIER_M), fixed before the 0.1 regressions",
                             "the out-of-sample split is one chronological split of 13 slates, not a multi-season validation",
                             "multi-season game-level data is not in any readable repository: see MULTISEASON_GAME_DATA_SPEC.md"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--arch", default=os.environ.get("SIFT_CBB_ARCH_DIR"))
    ap.add_argument("--repo", default=str(C.repos_dir() / "cbb-edge-finder"))
    a = ap.parse_args(argv)
    if not a.arch:
        ap.error("--arch or SIFT_CBB_ARCH_DIR is required")
    doc = run(Path(a.arch), Path(a.repo))
    C.write_json(OUT, doc)
    import json
    print(json.dumps(doc["reading"], indent=1)[:3000]); print("verdict", doc["verdict"])
    for k in ("opponent_quality", "venue", "early_season", "time_halves"):
        for kk, v in doc["results"][k].items():
            if isinstance(v, dict):
                print(k, kk, "n", v["n"], "ph", round(v["ph"]["est"], 2), [round(x, 2) for x in v["ph"]["ci95"]], "lh", round(v["lh"]["est"], 2), [round(x, 2) for x in v["lh"]["ci95"]])


if __name__ == "__main__":
    main()
