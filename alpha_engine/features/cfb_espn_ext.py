"""CFB pre-game inputs from archived ESPN post-game summaries (RESEARCH_ONLY): quarter scores, scoring plays, team box and drive counts.

Raw data: sift-data-vault `archives/CFB/espn_summary_postgame` (2014-2025 and 2026), one JSON per game. No market price enters. Nothing is deployed or consumed by a model.
Output `team` keyed (game_id, team). Every value for a game dated d uses only games dated strictly before d (date = kickoff UTC minus 10 hours, so one US game day is one date);
conditional frequencies use earlier SEASONS only. Method: `score_core.fit` (lam 3, half-life 10 games) on regulation points, yards per play, rush attempts and drives, then
`score_core.kernel` on the expected points x_pts, expected margin x_mar = x_pts - opponent x_pts and expected total x_tot. The brief
`research/input_research/data_foundation/verification/blind_briefs/briefs_cfb_espn.md` is the full definition.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import score_core as C
from .core import FeatureSpec

S = "CFB"
LAM, HL = 3.0, 10.0
BW_PTS, BW_MAR, BW_TOT, BW_TIE_M, BW_TIE_T, BW_HT = 3.0, 4.0, 5.0, 4.0, 7.0, 6.0
MIN_REF, MIN_COND = 500, 150
CONTENT = [f"{s}q{k}" for s in "ha" for k in (1, 2, 3, 4)] + ["h_score", "a_score", "n_per", "h_td", "a_td", "first_td", "h_yds", "a_yds", "h_plays", "a_plays", "h_rush", "a_rush", "h_drv", "a_drv"]
QJ = [f"qj_q{k}_zero_pre" for k in (1, 2, 3, 4)] + ["qj_all4_pre"] + [f"qj_hi_q{k}_pre" for k in (1, 2, 3, 4)]
PML = ["pml_lead_q1_pre", "pml_tie_q1_pre", "pml_lead_half_pre", "pml_tie_half_pre", "pml_win_2h_pre", "pml_tie_2h_pre"]
RTC = ["rtc_tie_pre"]; HFT = ["hft_win_lead_pre", "hft_win_trail_pre"]; HTC = ["htc_win_tied_pre"]
PST = [f"pst_q{k}_pre" for k in (1, 2, 3, 4)]
TDC = ["tdc_mean_pre", "tdc_var_pre", "tdc_ge2_pre", "tdc_ge4_pre", "tdc_ge6_pre"]
FTD = ["ftd_first_pre", "ftd_none_pre"]; NYP = ["nyp_off_pre", "nyp_def_pre", "nyp_exp_pre"]; SRA = ["sra_exp_pre", "sra_script_pre"]; ODS = ["ods_exp_pre", "ods_share_pre"]
BASE = ["cfbx_pts_pre", "cfbx_mar_pre", "cfbx_tot_pre"]


def _parse(j: dict) -> dict | None:
    try:
        hd = j["header"]; co = hd["competitions"][0]; cs = {c["homeAway"]: c for c in co["competitors"]}; H, A = cs["home"], cs["away"]
        if not co["status"]["type"]["completed"]:
            return None
        hl = [int(x["displayValue"]) for x in H["linescores"]]; al = [int(x["displayValue"]) for x in A["linescores"]]; hs, as_ = int(H["score"]), int(A["score"])
    except (KeyError, ValueError, TypeError, IndexError):
        return None
    if len(hl) < 4 or len(al) < 4:
        return None
    hid, aid = int(H["team"]["id"]), int(A["team"]["id"])
    r = {"game_id": int(hd["id"]), "season": int(hd["season"]["year"]), "game_date": (pd.Timestamp(co["date"]).tz_localize(None) - pd.Timedelta(hours=10)).normalize(),
         "home": hid, "away": aid, "ne": 0.0 if co.get("neutralSite") else 1.0, "h_score": float(hs), "a_score": float(as_), "n_per": float(max(len(hl), len(al)))}
    for k in range(4):
        r[f"hq{k + 1}"] = float(hl[k]); r[f"aq{k + 1}"] = float(al[k])
    sp = j.get("scoringPlays") or []
    td = [int((x.get("team") or {}).get("id") or -1) for x in sp if (x.get("scoringType") or {}).get("name") == "touchdown"]
    if sp or hs + as_ == 0:
        r["h_td"] = float(td.count(hid)); r["a_td"] = float(td.count(aid)); r["first_td"] = 0.0 if not td else (1.0 if td[0] == hid else (-1.0 if td[0] == aid else np.nan))
    else:
        r["h_td"] = r["a_td"] = r["first_td"] = np.nan
    box = {}
    try:
        for t in j["boxscore"]["teams"]:
            st = {x["name"]: x.get("displayValue") for x in t["statistics"]}; att = int(str(st["completionAttempts"]).replace("-", "/").split("/")[1])
            box[int(t["team"]["id"])] = (float(int(st["totalYards"])), float(att + int(st["rushingAttempts"])), float(int(st["rushingAttempts"])))
        ok = box[hid][1] > 0 and box[aid][1] > 0
    except (KeyError, ValueError, TypeError, IndexError):
        ok = False
    for s, tid in (("h", hid), ("a", aid)):
        r[f"{s}_yds"], r[f"{s}_plays"], r[f"{s}_rush"] = box[tid] if ok else (np.nan, np.nan, np.nan)
    dr = [int((x.get("team") or {}).get("id") or -1) for x in ((j.get("drives") or {}).get("previous") or [])]; dh, da = dr.count(hid), dr.count(aid)
    r["h_drv"], r["a_drv"] = (float(dh), float(da)) if dh > 0 and da > 0 else (np.nan, np.nan)
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
    reg_h = sum(f(f"hq{k}") for k in (1, 2, 3, 4)); reg_a = sum(f(f"aq{k}") for k in (1, 2, 3, 4))
    F = C.fit(g, {"pts": (reg_h, reg_a), "ypp": (f("h_yds") / f("h_plays"), f("a_yds") / f("a_plays")), "rush": (f("h_rush"), f("a_rush")), "drv": (f("h_drv"), f("a_drv"))}, LAM, HL)
    side = lambda s, o: dict(
        **{f"q{k}": f(f"{s}q{k}") for k in (1, 2, 3, 4)}, **{f"oq{k}": f(f"{o}q{k}") for k in (1, 2, 3, 4)}, score=f(f"{s}_score"), oscore=f(f"{o}_score"), n_per=f("n_per"),
        td=f(f"{s}_td"), ftd=f("first_td") * (1.0 if s == "h" else -1.0), rush=f(f"{s}_rush"),
        cfbx_pts_pre=F[f"pts_ep_{s}"].to_numpy(), cfbx_mar_pre=(F[f"pts_ep_{s}"] - F[f"pts_ep_{o}"]).to_numpy(), cfbx_tot_pre=(F.pts_ep_h + F.pts_ep_a).to_numpy(),
        nyp_off_pre=F[f"ypp_off_{s}"].to_numpy(), nyp_def_pre=F[f"ypp_def_{s}"].to_numpy(), nyp_exp_pre=F[f"ypp_ep_{s}"].to_numpy(), sra_exp_pre=F[f"rush_ep_{s}"].to_numpy(),
        ods_exp_pre=F[f"drv_ep_{s}"].to_numpy(), ods_share_pre=(F[f"drv_ep_{s}"] / (F.drv_ep_h + F.drv_ep_a)).to_numpy())
    t = C.team_rows(g, side("h", "a"), side("a", "h")); v = lambda c: t[c].to_numpy(float)
    q = np.c_[v("q1"), v("q2"), v("q3"), v("q4")]; oq = np.c_[v("oq1"), v("oq2"), v("oq3"), v("oq4")]; cq = q + oq; hi = cq.argmax(axis=1)
    xp, xm, xt, sea = v("cfbx_pts_pre"), v("cfbx_mar_pre"), v("cfbx_tot_pre"), t.season.to_numpy()
    h1, o1 = q[:, 0] + q[:, 1], oq[:, 0] + oq[:, 1]; h2, o2 = q[:, 2] + q[:, 3], oq[:, 2] + oq[:, 3]; win = (v("score") > v("oscore")).astype(float); td = v("td")
    K = lambda dims, ev, cond=None, mr=MIN_REF: C.kernel(sea, dims, ev, cond, mr)
    o = {}
    o.update(K([(xp, BW_PTS)], {**{f"qj_q{k + 1}_zero_pre": (q[:, k] == 0).astype(float) for k in range(4)}, "qj_all4_pre": (q > 0).all(axis=1).astype(float),
                                "tdc_mean_pre": td, "_td2": td * td, "tdc_ge2_pre": np.where(np.isnan(td), np.nan, td >= 2), "tdc_ge4_pre": np.where(np.isnan(td), np.nan, td >= 4),
                                "tdc_ge6_pre": np.where(np.isnan(td), np.nan, td >= 6)}))
    o["tdc_var_pre"] = o.pop("_td2") - o["tdc_mean_pre"] ** 2
    o.update(K([(xt, BW_TOT)], {**{f"qj_hi_q{k + 1}_pre": (hi == k).astype(float) for k in range(4)}, **{f"_c{k + 1}": cq[:, k] for k in range(4)}, "_reg": cq.sum(axis=1),
                                "ftd_none_pre": np.where(np.isnan(v("ftd")), np.nan, v("ftd") == 0)}))
    reg = o.pop("_reg")
    for k in (1, 2, 3, 4):
        o[f"pst_q{k}_pre"] = o.pop(f"_c{k}") / reg
    o.update(K([(xm, BW_MAR)], {"pml_lead_q1_pre": (q[:, 0] > oq[:, 0]).astype(float), "pml_tie_q1_pre": (q[:, 0] == oq[:, 0]).astype(float), "pml_lead_half_pre": (h1 > o1).astype(float),
                                "pml_tie_half_pre": (h1 == o1).astype(float), "pml_win_2h_pre": (h2 > o2).astype(float), "pml_tie_2h_pre": (h2 == o2).astype(float),
                                "ftd_first_pre": np.where(np.isnan(v("ftd")), np.nan, v("ftd") == 1), "sra_script_pre": v("rush")}))
    o.update(K([(np.abs(xm), BW_TIE_M), (xt, BW_TIE_T)], {"rtc_tie_pre": (v("n_per") > 4).astype(float)}))
    o.update(K([(xm, BW_MAR)], {"hft_win_lead_pre": win}, h1 > o1, MIN_COND)); o.update(K([(xm, BW_MAR)], {"hft_win_trail_pre": win}, h1 < o1, MIN_COND))
    o.update(K([(xm, BW_HT)], {"htc_win_tied_pre": win}, h1 == o1, MIN_COND))
    for k, x in o.items():
        t[k] = x
    cols = BASE + QJ + PML + RTC + HFT + HTC + PST + TDC + FTD + NYP + SRA + ODS
    return {"team": t[["game_id", "season", "team", "opp", "date", "is_home"] + cols]}


def specs() -> list[FeatureSpec]:
    raw = ["ESPN college-football game summary (header linescores, scoringPlays, boxscore.teams, drives), sift-data-vault archives/CFB/espn_summary_postgame"]
    wf = "walk-forward by season (earlier seasons only)"; ke = "kernel empirical frequencies in place of a fitted parametric model"
    F = lambda cid, cols, lvl, d, done, miss: FeatureSpec(S, cid, "team", cols, lvl, d, done, miss, raw, "pregame_rolling")
    return [
        F("cfb.quarter_joint_scoring_pmf", QJ, "PROXY", "Kernel-conditional P(team scoreless in each quarter), P(team scores in all four quarters) given market-free expected team points; "
          "P(each quarter is the game's highest-scoring quarter) given the expected total", ["per-team scoreless mass by quarter", "highest-scoring-quarter probabilities", wf],
          ["joint four-quarter pmf (marginals and two functionals only)", ke, "ties for highest quarter resolved to the earliest quarter"]),
        F("cfb.period_margin_lattice", PML, "PROXY", "Kernel-conditional P(lead / tie after Q1, at half, in the second half) given the market-free expected margin",
          ["period lead and tie mass by expected margin", wf], ["integer margin lattice per period (lead / tie mass only)", "conditioning on the expected total", ke]),
        F("cfb.regulation_tie_curve", RTC, "PROXY", "Kernel-conditional P(game tied after regulation) given |expected margin| and expected total (market-free)",
          ["tie probability as a function of non-market expected margin and total", wf], [ke]),
        F("cfb.half_to_full_transition_matrix", HFT, "PROXY", "Kernel-conditional P(win | leading at half) and P(win | trailing at half) given the market-free expected margin",
          ["half-time lead / trail state to full-game winner", wf], ["half-time margin buckets (three states only)", ke]),
        F("cfb.half_tie_conditional_win", HTC, "PROXY", "Kernel-conditional P(win | tied at half) given the market-free expected margin", ["conditional win probability given a tied first half", wf],
          [ke, "second-half kickoff possession"]),
        F("cfb.period_share_of_total", PST, "PARTIAL", "Kernel regression of each quarter's combined points over regulation total points given the market-free expected total",
          ["league share of scoring by quarter conditional on expected total", wf], ["overtime share", "tempo conditioning"]),
        F("cfb.td_count_dispersion", TDC, "PROXY", "Kernel-conditional mean and variance of team touchdowns and P(touchdowns >= 2 / 4 / 6) given market-free expected team points",
          ["touchdown count mean, dispersion and tail probabilities", wf], ["fitted count distribution (empirical moments and three tails only)", "touchdown-type split"]),
        F("cfb.first_td_race_rate", FTD, "PROXY", "Kernel-conditional P(team scores the game's first touchdown) given expected margin and P(no touchdown in the game) given expected total",
          ["first-touchdown race probability", "no-touchdown mass", wf], ["time-to-first-touchdown hazard", "opening-possession information"]),
        F("cfb.net_yards_per_play_model", NYP, "PARTIAL", "Opponent-adjusted ridge of net yards per play (total yards / (pass attempts + rush attempts incl. sacks)): offence, defence and expectation vs the opponent",
          ["net yards per play expectation, sacks included", "opponent adjustment", "recency weighting"], ["separate rush / pass components", "garbage-time filter"]),
        F("cfb.script_rush_attempts", SRA, "PROXY", "Opponent-adjusted ridge expectation of team rush attempts (sacks included, NCAA convention) and kernel regression of rush attempts on the expected margin",
          ["team rush attempts including sacks", "game-script dependence through expected margin"], ["joint model of tendency and script (two separate estimates)", "in-game script path"]),
        F("cfb.own_drive_share", ODS, "PARTIAL", "Opponent-adjusted ridge expectation of the team's drive count and its share of the combined expected drives",
          ["own share of combined possessions"], ["opening-kick / deferral information", "end-of-half kneel drives not removed"]),
    ]
