"""Soccer league-table and win-run state builders from the OpenFootball public-domain (CC0 1.0) fixtures-and-results files (RESEARCH_ONLY).

Raw data: the same Football.TXT clones as ``soccer_of_ext`` (england tiers 1-5 from 2000-01, deutschland / espana / italy from 2010-11). Output table ``team`` keyed (game_id, team): every value for a match uses ONLY league matches on STRICTLY EARLIER DATES
(nothing from the same date, so nothing from the match itself). Fixture COUNTS (how many league matches a team or a pair has in the season) come from the season's fixture list, which is published before the season starts, never from a score.
No odds, lines or prices exist in the source.

Inputs: soc.points_gap_state (league table state and pair gaps) and soc.current_win_run_state (consecutive-win run). League matches only: cups, European ties and friendlies are not in these files.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .core import FeatureSpec
from .soccer_of_ext import CONTENT, load_raw  # noqa: F401  (same raw loader and replay content columns)

S = "SOCCER"
# Internal arrays hold 10 + 4 columns. The fixture-COUNT columns (played, matches left, direct meetings left, in-year matches played) were built and blind-verified but FAIL the replay gates by construction:
# "left" depends on the season's future fixture list (the truncation test cannot tell a published fixture from a future row) and the pure counts do not move when scores are perturbed (non-vacuity). They are therefore NOT published as columns of the input.
ALL_PGS = ["pgs_pts_pre", "pgs_gd_pre", "pgs_gf_pre", "pgs_played_pre", "pgs_left_pre", "pgs_pts_gap_pre", "pgs_gd_gap_pre", "pgs_gf_gap_pre", "pgs_left_opp_pre", "pgs_left_both_pre"]
ALL_CWR = ["cwr_run_pre", "cwr_run_in_year_pre", "cwr_max_run_in_year_pre", "cwr_played_in_year_pre"]
PGS = ["pgs_pts_pre", "pgs_gd_pre", "pgs_gf_pre", "pgs_pts_gap_pre", "pgs_gd_gap_pre", "pgs_gf_gap_pre"]
CWR = ["cwr_run_pre", "cwr_run_in_year_pre", "cwr_max_run_in_year_pre"]


def compute(raw: dict) -> dict:
    m = raw["matches"].sort_values(["game_date", "game_id"], kind="mergesort").reset_index(drop=True)
    n = len(m)
    lg = m.league.to_numpy(); se = m.season.to_numpy(); hm = m.home.to_numpy(); aw = m.away.to_numpy()
    hg = m.hg.to_numpy(np.int64); ag = m.ag.to_numpy(np.int64); dt = m.game_date.to_numpy("datetime64[D]"); yr = m.game_date.dt.year.to_numpy()
    country = np.array([x.split("/")[0] for x in lg])
    # fixture-list counts: team matches and direct meetings per league-season (scores are never read here)
    tot_team: dict = {}; tot_pair: dict = {}
    for i in range(n):
        for t in (hm[i], aw[i]): tot_team[(lg[i], se[i], t)] = tot_team.get((lg[i], se[i], t), 0) + 1
        pk = (lg[i], se[i]) + tuple(sorted((hm[i], aw[i]))); tot_pair[pk] = tot_pair.get(pk, 0) + 1
    out_pgs = np.full((2, n, len(ALL_PGS)), np.nan); out_cwr = np.full((2, n, len(ALL_CWR)), np.nan)
    tab: dict = {}; pair_played: dict = {}; run: dict = {}
    cuts = np.flatnonzero(np.r_[True, dt[1:] != dt[:-1], True])
    for a0, b0 in zip(cuts[:-1], cuts[1:]):
        # ---- read states BEFORE this date batch is applied
        for i in range(a0, b0):
            pk = (lg[i], se[i]) + tuple(sorted((hm[i], aw[i]))); left_both = tot_pair[pk] - pair_played.get(pk, 0)
            st = {}
            for side, (t, o) in enumerate(((hm[i], aw[i]), (aw[i], hm[i]))):
                p, gd, gf, pl = tab.get((lg[i], se[i], t), (0, 0, 0, 0)); st[side] = (p, gd, gf, pl, tot_team[(lg[i], se[i], t)] - pl)
            for side in (0, 1):
                p, gd, gf, pl, left = st[side]; po, gdo, gfo, plo, lefto = st[1 - side]
                out_pgs[side, i] = [p, gd, gf, pl, left, p - po, gd - gdo, gf - gfo, lefto, left_both]
                key = (country[i], hm[i] if side == 0 else aw[i]); r = run.get(key)
                if r is None or r[4] != yr[i]: rin, mx, pin = 0, 0, 0
                else: rin, mx, pin = r[1], r[2], r[3]
                out_cwr[side, i] = [0 if r is None else r[0], rin, mx, pin]
        # ---- apply this date batch
        for i in range(a0, b0):
            for side, (t, gf_, ga_) in enumerate(((hm[i], hg[i], ag[i]), (aw[i], ag[i], hg[i]))):
                k = (lg[i], se[i], t); p, gd, gf, pl = tab.get(k, (0, 0, 0, 0))
                tab[k] = (p + (3 if gf_ > ga_ else 1 if gf_ == ga_ else 0), gd + gf_ - ga_, gf + gf_, pl + 1)
                key = (country[i], t); r = run.get(key, (0, 0, 0, 0, yr[i]))
                if r[4] != yr[i]: r = (r[0], 0, 0, 0, yr[i])                      # new calendar year: the in-year counters restart, the overall run carries
                total, rin, mx, pin, _ = r; win = gf_ > ga_
                total = total + 1 if win else 0; rin = rin + 1 if win else 0; pin += 1; mx = max(mx, rin)
                run[key] = (total, rin, mx, pin, yr[i])
            pk = (lg[i], se[i]) + tuple(sorted((hm[i], aw[i]))); pair_played[pk] = pair_played.get(pk, 0) + 1
    parts = []
    for side, (col, tcol) in enumerate((("home", "home"), ("away", "away"))):
        x = m[["game_id", tcol, "game_date", "season"]].rename(columns={tcol: "team", "game_date": "date"}); x["season"] = x.season.str[:4].astype(int)
        for j, c in enumerate(ALL_PGS):
            if c in PGS: x[c] = out_pgs[side][:, j]
        for j, c in enumerate(ALL_CWR):
            if c in CWR: x[c] = out_cwr[side][:, j]
        parts.append(x)
    t = pd.concat(parts, ignore_index=True).sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)
    return {"team": t}


def specs() -> list[FeatureSpec]:
    return [
        FeatureSpec(S, "soc.points_gap_state", "team", PGS, "PARTIAL",
                    "league-season table state of the row's team before the match date (points 3/1/0, goal difference, goals for) and the gaps to the opponent (points, goal difference, goals for), from league matches on strictly earlier dates",
                    ["points_A - points_B", "GD_A - GD_B", "GF_A - GF_B", "recomputed every matchday from earlier dates only"],
                    ["matches_left_A, matches_left_B and direct meetings left: built and blind-verified but they need the season's future fixture list, which the truncation replay rejects as future information", "announced points deductions applied to the table (no deductions log in the source)", "an as-of time within the match day (T-1h): the source has dates only, so same-day matches are excluded"], ["openfootball_league_results"], "pregame_rolling"),
        FeatureSpec(S, "soc.current_win_run_state", "team", CWR, "PARTIAL",
                    "consecutive league wins ending at the team's latest completed match before the match date (across leagues and seasons of the country files; a draw or loss resets it), the part of that run inside the as-of date's calendar year, the maximum run achieved inside "
                    "that calendar year so far, from matches on strictly earlier dates",
                    ["consecutive wins ending at the latest completed match", "split into wins inside and before the window start (calendar-year window)", "max run achieved inside the window so far", "recomputed after each match"],
                    ["all counted competitions (cups, European ties and friendlies are not in the source)", "the market's own window start and the threshold_reached indicator", "the penalty-win scope rule"], ["openfootball_league_results"], "pregame_rolling"),
    ]
