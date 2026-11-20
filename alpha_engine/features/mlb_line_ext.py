"""MLB pre-game inputs from archived post-game feeds: inning linescores and starting-pitcher box lines (RESEARCH_ONLY).

Raw data: sift-data-vault `archives/MLB/postgame_feed_compact/2022..2026` (MLB Stats API game feed, compacted; one JSON per game). No market price enters. Nothing is deployed or consumed.
Output `team` keyed (game_id, team). Every value for a game dated d uses only games dated strictly before d; conditional frequencies use earlier SEASONS only.
Starter quantities are TEAM-level (the team's starters in earlier games, opponent-adjusted): the game's own starter identity is an as-played field and is never read for that game's row.
Method: `score_core.fit` (lam 10, half-life 30 games) then `score_core.kernel`. Full definition: `research/input_research/data_foundation/verification/blind_briefs/briefs_mlb_line.md`.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import score_core as C
from .core import FeatureSpec

S = "MLB"
LAM, HL = 10.0, 30.0
BW_R1, BW_R1T, BW_F5M, BW_M, BW_T, BW_BF, BW_OUT = 0.04, 0.06, 0.25, 0.4, 0.5, 0.5, 0.4
MIN_REF = 500
TYPES = ("R", "F", "D", "L", "W")
CONTENT = ["h_r1", "a_r1", "h_r5", "a_r5", "h_r", "a_r", "n_inn", "walkoff", "h_sp_outs", "a_sp_outs", "h_sp_bf", "a_sp_bf", "h_sp_np", "a_sp_np"]
FI = ["fi_exp_pre", "fi_score_pre", "fi_nrfi_pre"]; F5 = ["f5_exp_pre", "f5_late_exp_pre", "f5_lead_pre", "f5_tie_pre"]; WO = ["wo_walkoff_pre", "wo_extras_pre"]
SPW = ["spw_outs_pre", "spw_bf_pre", "spw_np_pre"]; HOOK = [f"hook_ge{k}_pre" for k in (18, 21, 24, 27)]; EXB = [f"exb_ge{k}_pre" for k in (15, 16, 18, 19)]
BASE = ["mlbx_runs_pre", "mlbx_mar_pre", "mlbx_tot_pre"]


def _parse(j: dict) -> dict | None:
    try:
        if j["game"]["type"] not in TYPES or j["status"]["codedGameState"] != "F":
            return None
        inn = j["linescore"]["innings"]
        if len(inn) < 5:
            return None
        hr = [float((x.get("home") or {}).get("runs") or 0) for x in inn]; ar = [float((x.get("away") or {}).get("runs") or 0) for x in inn]
        dt = j["datetime"]; r = {"game_id": int(j["pk"]), "season": int(j["game"]["season"]), "game_date": dt.get("resumeDate") or dt["officialDate"], "home": int(j["teams"]["home"]["id"]), "away": int(j["teams"]["away"]["id"]), "ne": 1.0,
                                 "h_r1": hr[0], "a_r1": ar[0], "h_r5": sum(hr[:5]), "a_r5": sum(ar[:5]), "h_r": sum(hr), "a_r": sum(ar), "n_inn": float(len(inn))}
        r["walkoff"] = float(r["h_r"] > r["a_r"] and r["h_r"] - hr[-1] <= r["a_r"])
    except (KeyError, ValueError, TypeError, IndexError):
        return None
    sp = {}
    try:
        for s, side in (("h", "home"), ("a", "away")):
            b = j["box"][side]; pid = b["pitchers"][0]; pit = next(p for p in b["players"] if p["id"] == pid)["pit"]
            sp[s] = (float(pit["outs"]), float(pit["battersFaced"]), float(pit["numberOfPitches"]))
    except (KeyError, ValueError, TypeError, IndexError, StopIteration):
        sp = {}
    for s in "ha":
        r[f"{s}_sp_outs"], r[f"{s}_sp_bf"], r[f"{s}_sp_np"] = sp[s] if len(sp) == 2 else (np.nan, np.nan, np.nan)
    return r


def load_raw(dirs) -> dict:
    rows = []
    for d in str(dirs).split(","):
        for f in sorted(Path(d).glob("*.json")):
            if f.name.startswith("_"):
                continue
            r = _parse(json.loads(f.read_text()))
            if r: rows.append(r)
    return {"games": pd.DataFrame(rows).drop_duplicates("game_id")}


def compute(raw: dict) -> dict:
    g = raw["games"].copy(); g["date"] = pd.to_datetime(g.game_date)
    g = g.sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)
    f = lambda c: g[c].to_numpy(float)
    F = C.fit(g, {"run": (f("h_r"), f("a_r")), "r1": (f("h_r1"), f("a_r1")), "r5": (f("h_r5"), f("a_r5")), "late": (f("h_r") - f("h_r5"), f("a_r") - f("a_r5")),
                  "outs": (f("h_sp_outs"), f("a_sp_outs")), "bf": (f("h_sp_bf"), f("a_sp_bf")), "np": (f("h_sp_np"), f("a_sp_np"))}, LAM, HL)
    side = lambda s, o: dict(r1=f(f"{s}_r1"), o1=f(f"{o}_r1"), r5=f(f"{s}_r5"), o5=f(f"{o}_r5"), n_inn=f("n_inn"), walkoff=f("walkoff"), outs=f(f"{s}_sp_outs"), bf=f(f"{s}_sp_bf"),
                             mlbx_runs_pre=F[f"run_ep_{s}"].to_numpy(), mlbx_mar_pre=(F[f"run_ep_{s}"] - F[f"run_ep_{o}"]).to_numpy(), mlbx_tot_pre=(F.run_ep_h + F.run_ep_a).to_numpy(),
                             hmar=(F.run_ep_h - F.run_ep_a).to_numpy(), fi_exp_pre=F[f"r1_ep_{s}"].to_numpy(), fi_tot=(F.r1_ep_h + F.r1_ep_a).to_numpy(), f5_exp_pre=F[f"r5_ep_{s}"].to_numpy(),
                             f5_mar=(F[f"r5_ep_{s}"] - F[f"r5_ep_{o}"]).to_numpy(), f5_late_exp_pre=F[f"late_ep_{s}"].to_numpy(), spw_outs_pre=F[f"outs_ep_{s}"].to_numpy(),
                             spw_bf_pre=F[f"bf_ep_{s}"].to_numpy(), spw_np_pre=F[f"np_ep_{s}"].to_numpy())
    t = C.team_rows(g, side("h", "a"), side("a", "h")); v = lambda c: t[c].to_numpy(float); sea = t.season.to_numpy(); r = {}
    K = lambda dims, ev: r.update(C.kernel(sea, dims, ev, None, MIN_REF)); nn = lambda x, b: np.where(np.isnan(x), np.nan, b)
    K([(v("fi_exp_pre"), BW_R1)], {"fi_score_pre": (v("r1") > 0).astype(float)}); K([(v("fi_tot"), BW_R1T)], {"fi_nrfi_pre": (v("r1") + v("o1") == 0).astype(float)})
    K([(v("f5_mar"), BW_F5M)], {"f5_lead_pre": (v("r5") > v("o5")).astype(float), "f5_tie_pre": (v("r5") == v("o5")).astype(float)})
    K([(v("hmar"), BW_M), (v("mlbx_tot_pre"), BW_T)], {"wo_walkoff_pre": v("walkoff"), "wo_extras_pre": (v("n_inn") > 9).astype(float)})
    K([(v("spw_bf_pre"), BW_BF)], {f"hook_ge{k}_pre": nn(v("bf"), v("bf") >= k) for k in (18, 21, 24, 27)})
    K([(v("spw_outs_pre"), BW_OUT)], {f"exb_ge{k}_pre": nn(v("outs"), v("outs") >= k) for k in (15, 16, 18, 19)})
    for k, x in r.items():
        t[k] = x
    return {"team": t[["game_id", "season", "team", "opp", "date", "is_home"] + BASE + FI + F5 + WO + SPW + HOOK + EXB]}


def specs() -> list[FeatureSpec]:
    raw = ["MLB Stats API post-game feed (linescore innings, box pitchers), sift-data-vault archives/MLB/postgame_feed_compact"]
    wf = "walk-forward by season (earlier seasons only)"; tl = "starter-specific estimate for the announced probable pitcher (team-level: the team's starters in earlier games)"
    F = lambda cid, cols, lvl, d, done, miss: FeatureSpec(S, cid, "team", cols, lvl, d, done, miss, raw, "pregame_rolling")
    return [
        F("mlb.first_inning_splits", FI, "PROXY", "Opponent-adjusted ridge expectation of the team's first-inning runs; kernel-conditional P(team scores in the first inning) and P(no run in the first inning by either team)",
          ["team first-inning scoring rate, opponent-adjusted", "no-run-first-inning probability", wf], ["starter first-inning performance (team staff level only)", "top-of-order quality from the confirmed lineup", "park and weather"]),
        F("mlb.f5_split", F5, "PARTIAL", "Opponent-adjusted ridge expectation of the team's runs in innings 1-5 and in innings 6+, and kernel-conditional P(lead / tie after five innings) given the expected five-inning margin",
          ["first-five-innings vs later-innings run split", "five-inning lead and tie probability", wf], ["starter vs bullpen attribution of runs allowed (inning split only)", "probable-pitcher adjustment"]),
        F("mlb.playoff_walkoff_event_rate", WO, "PROXY", "Kernel-conditional per-game P(walk-off win by the home team) and P(extra innings) given the market-free expected home run margin and expected total runs",
          ["per-game walk-off rate", "extra-innings rate", wf], ["postseason-specific rate (all game types pooled)", "remaining-games exposure of a playoff bracket", "walk-off identified from the linescore, not the final play"]),
        F("mlb.sp_workload", SPW, "PROXY", "Opponent-adjusted ridge expectation of the team's starting pitcher outs, batters faced and pitch count (team's starters in earlier games vs the opposing lineup's effect)",
          ["expected starter outs / batters faced / pitches", "opposing-team effect", "recency weighting"], [tl, "days of rest and pitch-count history of the individual starter", "opener / bulk-pitcher detection"]),
        F("mlb.sp_hook_hazard_curve", HOOK, "PROXY", "Kernel-conditional P(starter faces >= 18 / 21 / 24 / 27 batters) given the team-level expected starter batters faced",
          ["survival curve of the starter over batters faced at four points", wf], [tl, "per-batter discrete-time hazard with game-state covariates (four survival points only)"]),
        F("mlb.exit_boundary_mass", EXB, "PROXY", "Kernel-conditional P(starter records >= 15 / 16 / 18 / 19 outs) given the team-level expected starter outs",
          ["exit-outs lattice mass at the 5.0 / 5.1 / 6.0 / 6.1 inning boundaries", wf], [tl, "readout from a shared per-batter hazard (empirical frequencies instead)"]),
    ]
