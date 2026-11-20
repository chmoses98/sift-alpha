"""MLB batch 11 (RESEARCH_ONLY, PROXY): first-inning run probability from an exact base-out Markov chain. Team-level rates only: the batting team's first-inning PA
outcomes vs the fielding team's STARTERS' first-trip (batters 1-9) outcomes allowed; no confirmed lineup and no announced starter exist in the archive. Chronology, rights and
tables as mlb_pa_core (first-pitch dating; history only from games with avail_date < d; league constants from season S-1).

Outcome classes of a PA event: W = walk, intent_walk, hit_by_pitch, catcher_interf; S1 = single, field_error; XB = double, triple; HR = home_run; K = strikeout, strikeout_double_play;
O = every other PA event.
Rates (window = seasons S-1..S, avail < d): batting b_c = (n_c + 250 lb_c)/(N + 250) over the batting team's PAs with inn == 1; pitching p_c = (n_c + 300 lp_c)/(N + 300) over the fielding team's
start PAs (is_start) with bf_i <= 9; lb_c / lp_c = the same shares over all such PAs of season S-1. Combined q_c = b_c p_c / lb_c, normalised to sum 1.
Chain: state (outs, runner on 1st, 2nd, 3rd), start (0, empty). W: batter to 1st, runners advance only when forced (a run if loaded). S1: batter to 1st, every runner advances one base
(a runner on 3rd scores). XB: batter to 2nd, every runner scores. HR: everyone scores. K and O: one out, runners hold. P(no run) = probability of reaching 3 outs without any run.
mlb.first_inning_markov_run_prob  fim_p_score_pre = 1 - P(no run) for the batting team; fim_p_nrfi_pre = product of the two teams' P(no run) in the game.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import mlb_pa_core as C
from .core import FeatureSpec

S = "MLB"
OUT_FIRST = 2023
CLASSES = ["W", "S1", "XB", "HR", "K", "O"]
EV = {**{e: "W" for e in ("walk", "intent_walk", "hit_by_pitch", "catcher_interf")}, **{e: "S1" for e in ("single", "field_error")}, "double": "XB", "triple": "XB", "home_run": "HR",
      "strikeout": "K", "strikeout_double_play": "K"}
K_BAT, K_PIT = 250.0, 300.0
CONTENT = C.PA_CONTENT
load_raw = C.load_raw


def p_no_run(q: np.ndarray) -> np.ndarray:
    """q: (n, 6) outcome probabilities in CLASSES order. Exact probability of three outs with no run (runs only leave the no-run set)."""
    n = len(q); mass = {(0, 0): np.ones(n)}; done = np.zeros(n)
    qW, qS, qX, qH, qK, qO = (q[:, i] for i in range(6))
    for _ in range(12):                                   # a no-run path has at most 3 outs + 3 runner additions
        nxt: dict = {}
        def add(k, v):
            nxt[k] = nxt.get(k, 0.0) + v
        for (outs, b), m in mass.items():
            # outs
            if outs == 2:
                done = done + m * (qK + qO)
            else:
                add((outs + 1, b), m * (qK + qO))
            # walk: forced advance; a run only when loaded
            if b != 7:
                nb = {0: 1, 1: 3, 2: 3, 3: 7, 4: 5, 5: 7, 6: 7}[b]
                add((outs, nb), m * qW)
            # single: every runner advances one base; a runner on 3rd scores
            if not (b & 4):
                add((outs, ((b << 1) & 7) | 1), m * qS)
            # extra-base hit with anyone on, and every home run, score; XB with bases empty -> runner on 2nd
            if b == 0:
                add((outs, 2), m * qX)
        mass = nxt
        if not mass:
            break
    return done


def compute(raw: dict) -> dict:
    g, p = C.prepared(raw)
    p = p.assign(cls=p.event.map(EV).fillna("O"))
    for c in CLASSES:
        p["c_" + c] = (p.cls == c).astype(float)
    p["one"] = 1.0
    tg = C.team_games(g)
    rows = tg[tg.season >= OUT_FIRST][["game_id", "team", "opp", "date", "season"]].sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)
    rows["row_id"] = np.arange(len(rows))
    cols = ["one"] + ["c_" + c for c in CLASSES]
    bat = p[p.inn == 1]; pit = p[p.is_start & (p.bf_i <= 9)]
    wb = C.window_sums(bat, "bat_team", rows.assign(bat_team=rows.team)[["row_id", "bat_team", "date", "season"]], cols).loc[rows.row_id]
    wp = C.window_sums(pit, "fld_team", rows.assign(fld_team=rows.opp)[["row_id", "fld_team", "date", "season"]], cols).loc[rows.row_id]
    lb = {s_: {c: (bat[bat.season == s_].cls == c).mean() for c in CLASSES} for s_ in sorted(p.season.unique())}
    lp = {s_: {c: (pit[pit.season == s_].cls == c).mean() for c in CLASSES} for s_ in sorted(p.season.unique())}
    prev = (rows.season - 1).to_numpy()
    q = np.zeros((len(rows), 6))
    for i, c in enumerate(CLASSES):
        LB = np.array([lb[s_][c] for s_ in prev]); LP = np.array([lp[s_][c] for s_ in prev])
        b = (wb["c_" + c].to_numpy() + K_BAT * LB) / (wb.one.to_numpy() + K_BAT); pp = (wp["c_" + c].to_numpy() + K_PIT * LP) / (wp.one.to_numpy() + K_PIT)
        q[:, i] = b * pp / LB
    q = q / q.sum(axis=1, keepdims=True)
    rows["pnr"] = p_no_run(q)
    rows["fim_p_score_pre"] = 1.0 - rows.pnr
    o = rows[["game_id", "team", "pnr"]].rename(columns={"team": "opp", "pnr": "opp_pnr"})
    rows = rows.merge(o, on=["game_id", "opp"], how="left")
    rows["fim_p_nrfi_pre"] = rows.pnr * rows.opp_pnr
    out = rows[["game_id", "team", "opp", "date", "season", "fim_p_score_pre", "fim_p_nrfi_pre"]].copy()
    return {"team": out.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


def specs() -> list[FeatureSpec]:
    return [FeatureSpec(S, "mlb.first_inning_markov_run_prob", "team", ["fim_p_score_pre", "fim_p_nrfi_pre"], "PROXY",
                        "Exact base-out Markov chain for the first inning: walk / single / extra-base / home run / strikeout / other-out probabilities from the batting team's first-inning PAs "
                        "(regressed with 250 PA) combined odds-ratio style with the fielding team's starters' first-trip outcomes allowed (regressed with 300 BF); P(team scores) and P(no run first inning)",
                        ["base-out Markov chain solved exactly for P(no run)", "batting rates combined with starter first-trip rates", "shrinkage to league (k = 250 / 300)", "RFI and team-specific outputs"],
                        ["confirmed top-of-order hitters and their hand splits (team first-inning PAs used)", "the announced starter (the fielding team's starters as a group)",
                         "realistic runner advancement (singles advance one base, outs hold runners, no double plays)"], ["MLB Stats API post-game feed 2022-2026 (plays, box starters)"])]
