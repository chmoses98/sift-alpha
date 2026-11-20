"""NHL pre-game period-state inputs from archived daily score files with goal-by-goal period data (RESEARCH_ONLY).

Raw data: sift-data-vault `archives/NHL/daily_scores_goals_periods/2021-2026` (api-web.nhle.com /v1/score/DATE, one JSON per date). No market price enters. Nothing is deployed or consumed.
Output `team` keyed (game_id, team). Every value for a game dated d uses only games dated strictly before d; conditional frequencies use earlier SEASONS only.
Method: `score_core.fit` (lam 8, half-life 20 games) on regulation goals, then `score_core.kernel` on expected goals x_g, expected margin x_mar and expected total x_tot.
Full definition: `research/input_research/data_foundation/verification/blind_briefs/briefs_nhl_period.md`.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import score_core as C
from .core import FeatureSpec

S = "NHL"
LAM, HL = 8.0, 20.0
BW_G, BW_MAR, BW_TOT = 0.25, 0.35, 0.35
MIN_REF, MIN_COND = 500, 150
CONTENT = [f"{s}_p{k}" for s in "ha" for k in (1, 2, 3)]
PES = ["pes_lead_p2_pre", "pes_tie_p2_pre", "pes_lead_p3_pre", "pes_tie_p3_pre", "pes_p3_gf_lead_pre", "pes_p3_gf_tie_pre", "pes_p3_gf_trail_pre"]
PPC = [f"ppc_mu_p{k}_pre" for k in (1, 2, 3)] + [f"ppc_tot_ge2_p{k}_pre" for k in (1, 2, 3)] + ["ppc_cov_p12_pre"]
SPU = ["spu_total_pre", "spu_se_pre"]
BASE = ["nhlx_g_pre", "nhlx_mar_pre"]


def load_raw(d) -> dict:
    rows = []
    for f in sorted(Path(d).glob("*.json")):
        if f.name.startswith("_"):
            continue
        for x in json.loads(f.read_text()).get("games") or []:
            if x.get("gameType") not in (2, 3) or x.get("gameState") not in ("OFF", "FINAL") or "goals" not in x:
                continue
            r = {"game_id": int(x["id"]), "season": int(str(x["season"])[:4]), "game_date": x["gameDate"], "home": x["home"]["abbrev"], "away": x["away"]["abbrev"], "ne": 0.0 if x.get("neutralSite") else 1.0}
            for s in "ha":
                for k in (1, 2, 3):
                    r[f"{s}_p{k}"] = 0.0
            for go in x["goals"]:
                pd_ = go.get("periodDescriptor") or {}
                if pd_.get("periodType") == "REG" and go.get("period") in (1, 2, 3):
                    r[("h" if go.get("teamAbbrev") == r["home"] else "a") + f"_p{go['period']}"] += 1.0
            rows.append(r)
    return {"games": pd.DataFrame(rows).drop_duplicates("game_id")}


def compute(raw: dict) -> dict:
    g = raw["games"].copy(); g["date"] = pd.to_datetime(g.game_date)
    g = g.sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)
    f = lambda c: g[c].to_numpy(float)
    F = C.fit(g, {"g": (f("h_p1") + f("h_p2") + f("h_p3"), f("a_p1") + f("a_p2") + f("a_p3"))}, LAM, HL, se="g")
    side = lambda s, o: dict(**{f"p{k}": f(f"{s}_p{k}") for k in (1, 2, 3)}, **{f"o{k}": f(f"{o}_p{k}") for k in (1, 2, 3)}, nhlx_g_pre=F[f"g_ep_{s}"].to_numpy(),
                             nhlx_mar_pre=(F[f"g_ep_{s}"] - F[f"g_ep_{o}"]).to_numpy(), spu_total_pre=(F.g_ep_h + F.g_ep_a).to_numpy(), spu_se_pre=F.g_se.to_numpy())
    t = C.team_rows(g, side("h", "a"), side("a", "h")); v = lambda c: t[c].to_numpy(float)
    p = np.c_[v("p1"), v("p2"), v("p3")]; o = np.c_[v("o1"), v("o2"), v("o3")]; c = p + o; xg, xm, xt, sea = v("nhlx_g_pre"), v("nhlx_mar_pre"), v("spu_total_pre"), t.season.to_numpy()
    d2 = p[:, 0] + p[:, 1] - o[:, 0] - o[:, 1]; r = {}
    r.update(C.kernel(sea, [(xm, BW_MAR)], {"pes_lead_p2_pre": (p[:, 0] > o[:, 0]).astype(float), "pes_tie_p2_pre": (p[:, 0] == o[:, 0]).astype(float),
                                            "pes_lead_p3_pre": (d2 > 0).astype(float), "pes_tie_p3_pre": (d2 == 0).astype(float)}, None, MIN_REF))
    for nm, m in (("lead", d2 > 0), ("tie", d2 == 0), ("trail", d2 < 0)):
        r.update(C.kernel(sea, [(xg, BW_G)], {f"pes_p3_gf_{nm}_pre": p[:, 2]}, m, MIN_COND))
    r.update(C.kernel(sea, [(xg, BW_G)], {f"ppc_mu_p{k + 1}_pre": p[:, k] for k in range(3)}, None, MIN_REF))
    r.update(C.kernel(sea, [(xt, BW_TOT)], {**{f"ppc_tot_ge2_p{k + 1}_pre": (c[:, k] >= 2).astype(float) for k in range(3)}, "_c1": c[:, 0], "_c2": c[:, 1], "_c12": c[:, 0] * c[:, 1]}, None, MIN_REF))
    r["ppc_cov_p12_pre"] = r.pop("_c12") - r.pop("_c1") * r.pop("_c2")
    for k, x in r.items():
        t[k] = x
    return {"team": t[["game_id", "season", "team", "opp", "date", "is_home"] + BASE + PES + PPC + SPU]}


def specs() -> list[FeatureSpec]:
    raw = ["NHL api-web daily score files (goals with period and team), sift-data-vault archives/NHL/daily_scores_goals_periods"]
    wf = "walk-forward by season (earlier seasons only)"
    F = lambda cid, cols, lvl, d, done, miss: FeatureSpec(S, cid, "team", cols, lvl, d, done, miss, raw, "pregame_rolling")
    return [
        F("nhl.period_entry_state_matrix", PES, "PROXY", "Kernel-conditional P(lead / tie entering period 2 and period 3) given the market-free expected goal margin, and expected third-period team goals "
          "given the state entering period 3 (lead / tie / trail) and the team's expected goals", ["entering-period score-state distribution", "state-conditional third-period scoring rate", wf],
          ["full score-state matrix (three states, not goal differentials)", "state-conditional rates for period 2", "empty-net and strength-state split", "kernel empirical frequencies, not a fitted model"]),
        F("nhl.period_pair_count_model", PPC, "PROXY", "Kernel regression of team goals in each regulation period on expected goals; P(combined period goals >= 2) and the covariance of combined "
          "period-1 and period-2 goals given the expected total", ["period-level goal means", "period total tail", "cross-period dependence (P1-P2 covariance)", wf],
          ["bivariate count distribution (means, one tail and one covariance only)", "team-pair dependence within a period", "overtime"]),
        F("nhl.series_pair_scoring_rate_uncertainty", SPU, "PARTIAL", "Expected combined regulation goals of the pair from an opponent-adjusted ridge (attack plus defence, both sides) and its posterior "
          "standard error (residual scale times the ridge posterior variance of the combined rate)", ["pair combined goal rate", "shared posterior uncertainty of the attack-plus-defence sum"],
          ["series-level update after each game of the series", "goalie and lineup terms", "Poisson-gamma posterior (Gaussian ridge approximation)"]),
    ]
