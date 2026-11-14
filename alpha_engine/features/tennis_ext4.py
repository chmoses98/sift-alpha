"""Tennis hold / set / tiebreak dynamic programme (RESEARCH_ONLY): deterministic closed-form components of ten.games_per_set_distribution and ten.hold_gap_expected_margin.

Data, keys and date-batching are those of tennis_ext3 (Sackmann ATP/WTA files, CC BY-NC-SA 4.0 research use; a match sees only matches with tourney_date STRICTLY EARLIER).
No fitted or outcome-optimised model: every number is a closed-form / dynamic-programming function of two pre-match serve-point-win estimates.

Serve-point-win estimate for player i against j (all weights 0.5**(age_days/365) over the previous 1095 days, strictly earlier tourney_date):
  sp_i  = sum w*(1stWon+2ndWon) / sum w*svpt           over i's matches (own serve)
  rr_j  = sum w*(opp_svpt-(opp_1stWon+opp_2ndWon)) / sum w*opp_svpt   over j's matches (points won on return)
  t     = tour-wide UNWEIGHTED serve rate over the same window
  spw_ij = clip(sp_i + (rr_j - (1 - t)), 0.30, 0.90)
A player-match row counts only if w_/l_ svpt, 1stWon, 2ndWon are all present for BOTH sides, both svpt > 0 and the score is not a walkover.
Game: p = spw, q = 1-p, hold(p) = p^4 (1 + 4q + 10 q^2) + 20 p^3 q^3 * p^2/(1 - 2 p q).
Set: games alternate service starting with a randomised first server (average of the two cases), 6 games with a 2-game lead, 7-5, tiebreak at 6-6.
Tiebreak: first to 7 by 2; point k server = S1 for k=1, then S2 for k=2,3, S1 for 4,5, ...; from 6-6 each further pair of points contains one point served by each player, so P(win from level) = a/(a+b) with a = pA_serve*pA_return, b = (1-pA_serve)*(1-pA_return).
Point-win probability of A when A serves = spw_A, when B serves = 1 - spw_B.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec
from .tennis_ext2 import _wsum, perturb as _perturb

S = "TENNIS"
COLS4 = ["tourney_id", "tourney_date", "match_num", "winner_id", "loser_id", "score", "best_of", "w_svpt", "w_1stWon", "w_2ndWon", "l_svpt", "l_1stWon", "l_2ndWon"]
CONTENT = ["score", "winner_id", "loser_id", "best_of", "w_svpt", "w_1stWon", "w_2ndWon", "l_svpt", "l_1stWon", "l_2ndWon"]
GAMES = (6, 7, 8, 9, 10, 12, 13)


def load_raw(tennis_dir) -> dict:
    fs = sorted(glob.glob(str(Path(tennis_dir) / "[aw]t[pa]_matches_20*.csv.gz")))
    d = pd.concat([pd.read_csv(f, usecols=lambda c: c in COLS4, low_memory=False).assign(tour=Path(f).name[:3]) for f in fs], ignore_index=True)
    d = d.dropna(subset=["tourney_date", "winner_id", "loser_id"]).copy()
    d["date"] = pd.to_datetime(d.tourney_date.astype(int).astype(str), format="%Y%m%d", errors="coerce"); d = d.dropna(subset=["date"])
    d["game_id"] = d.tour + "|" + d.tourney_id.astype(str) + "|" + d.match_num.astype(str)
    d["game_id"] = d.game_id + "|" + d.groupby("game_id").cumcount().astype(str)
    d["season"] = d.date.dt.year
    return {"matches": d[["game_id", "tour", "date", "season"] + [c for c in COLS4 if c not in ("tourney_date",)]].reset_index(drop=True)}


def hold(p):
    q = 1.0 - p
    return p ** 4 * (1 + 4 * q + 10 * q * q) + 20 * p ** 3 * q ** 3 * p * p / (1 - 2 * p * q)


def tiebreak_win(pa_serve, pb_serve):
    """P(A wins a tiebreak) when A serves the first point. pa_serve = P(A wins a point A serves); pb_serve = P(B wins a point B serves). Arrays."""
    sa = np.asarray(pa_serve, float); sb = np.asarray(pb_serve, float); n = len(sa)
    a = sa * (1 - sb); b = (1 - sa) * sb                      # one pair of points holds one point served by each: A wins both / B wins both
    lvl = a / (a + b)

    def pa_pt(k):                                              # P(A wins point k, 1-indexed); A = S1 serves points 1, 4, 5, 8, 9, ...
        return sa if (k == 1 or ((k - 2) // 2) % 2 == 1) else 1 - sb
    memo = {}

    def f(x, y):
        if x == 7 and y <= 5: return np.ones(n)
        if y == 7 and x <= 5: return np.zeros(n)
        if x == 6 and y == 6: return lvl
        if (x, y) in memo: return memo[(x, y)]
        p = pa_pt(x + y + 1); r = p * f(x + 1, y) + (1 - p) * f(x, y + 1); memo[(x, y)] = r; return r
    return f(0, 0)


def set_dp(ha, hb, spa, spb):
    """Set score distribution for A and B, averaged over the first server. Returns dict with P(A wins set), pmf over total games {6,7,8,9,10,12,13}, E[A-B games], E[(A-B)^2], P(tiebreak)."""
    n = len(ha); out = None
    tb_a = tiebreak_win(spa, spb)            # A serves first point of the tiebreak
    tb_b = 1 - tiebreak_win(spb, spa)        # B serves first point: P(A wins) = 1 - P(B wins | B first)
    for first_a in (True, False):
        res = {"win": np.zeros(n), "tb": np.zeros(n), "m1": np.zeros(n), "m2": np.zeros(n), **{f"g{g}": np.zeros(n) for g in GAMES}}
        # state probability dict keyed (a, b)
        st = {(0, 0): np.ones(n)}
        for tot in range(0, 13):
            nxt = {}
            for (a, b), pr in st.items():
                if a + b != tot: continue
                a_serves = (tot % 2 == 0) == first_a
                pg = ha if a_serves else 1 - hb
                for da, p in ((1, pg), (0, 1 - pg)):
                    na, nb = a + da, b + 1 - da; q = pr * p
                    over = (na == 6 and nb <= 4) or (nb == 6 and na <= 4) or (na == 7 and nb == 5) or (nb == 7 and na == 5)
                    if over:
                        res["win"] += q * (na > nb); res[f"g{na + nb}"] += q; d = na - nb; res["m1"] += q * d; res["m2"] += q * d * d
                    elif na == 6 and nb == 6:
                        tbw = tb_a if first_a else tb_b             # the set's first server also serves the first tiebreak point (12 games played)
                        res["tb"] += q; res["g13"] += q; res["win"] += q * tbw; res["m1"] += q * (2 * tbw - 1); res["m2"] += q
                    else: nxt[(na, nb)] = nxt.get((na, nb), 0) + q
            st = {**{k: v for k, v in st.items() if k[0] + k[1] != tot}, **nxt}
        out = res if out is None else {k: out[k] + res[k] for k in res}
    return {k: v / 2 for k, v in out.items()}


def compute(raw: dict) -> dict:
    m = raw["matches"].copy()
    wo = m.score.astype(str).str.contains("W/O", regex=False)
    ok = ~wo & (m.w_svpt > 0) & (m.l_svpt > 0) & m[["w_1stWon", "w_2ndWon", "l_1stWon", "l_2ndWon"]].notna().all(axis=1)
    ws, ls = m.w_1stWon + m.w_2ndWon, m.l_1stWon + m.l_2ndWon
    rows = []
    for me, op, k_me, k_op in (("w", "l", "winner_id", "loser_id"), ("l", "w", "loser_id", "winner_id")):
        sv, ov = (m.w_svpt, m.l_svpt) if me == "w" else (m.l_svpt, m.w_svpt); sw, ow = (ws, ls) if me == "w" else (ls, ws)
        rows.append(pd.DataFrame({"game_id": m.game_id, "team": m.tour + ":" + m[k_me].astype(int).astype(str), "opp": m.tour + ":" + m[k_op].astype(int).astype(str), "tour": m.tour, "date": m.date, "season": m.season, "best_of": m.best_of,
                                  "s_won": np.where(ok, sw, np.nan), "s_pts": np.where(ok, sv, np.nan), "r_won": np.where(ok, ov - ow, np.nan), "r_pts": np.where(ok, ov, np.nan)}))
    L = pd.concat(rows, ignore_index=True); dd = L.date.to_numpy()
    V = L[["s_won", "s_pts", "r_won", "r_pts"]].to_numpy(float)
    ps, _ = _wsum(L[["team"]], dd, V, 1095, hl_days=365.0)
    ts, _ = _wsum(L[["tour"]], dd, V[:, :2], 1095)
    with np.errstate(all="ignore"):
        L["sp"] = ps[:, 0] / ps[:, 1]; L["rr"] = ps[:, 2] / ps[:, 3]; L["t"] = ts[:, 0] / ts[:, 1]
    o = L[["game_id", "team", "sp", "rr"]].rename(columns={"team": "opp", "sp": "o_sp", "rr": "o_rr"})
    L = L.merge(o, on=["game_id", "opp"], how="left")
    L["spw_pre"] = (L.sp + (L.o_rr - (1 - L.t))).clip(0.30, 0.90)
    L["o_spw"] = (L.o_sp + (L.rr - (1 - L.t))).clip(0.30, 0.90)
    good = L.spw_pre.notna() & L.o_spw.notna()
    n = int(good.sum()); cols = {}
    if n:
        pa = L.spw_pre[good].to_numpy(float); pb = L.o_spw[good].to_numpy(float)
        ha, hb = hold(pa), hold(pb); r = set_dp(ha, hb, pa, pb)
        for g in GAMES: cols[f"gps_p{g}_pre"] = r[f"g{g}"]
        cols["gps_p_tiebreak_pre"] = r["tb"]; cols["gps_mean_games_pre"] = sum(g * r[f"g{g}"] for g in GAMES)
        cols["gps_hold_pre"] = ha; cols["gps_opp_hold_pre"] = hb
        w, e1, e2 = r["win"], r["m1"], r["m2"]; v1 = e2 - e1 ** 2
        bo = L.best_of[good].to_numpy(float); need = np.where(bo == 5, 3, 2)
        # number of sets N (iid sets, first to `need`): bo3: N=2 w.p. w^2+(1-w)^2, 3 otherwise; bo5: N=3, 4, 5
        l_ = 1 - w
        pn2 = w ** 2 + l_ ** 2; en3 = 2 + (1 - pn2); vn3 = pn2 * (1 - pn2)
        p3 = w ** 3 + l_ ** 3; p4 = 3 * (w ** 3 * l_ + l_ ** 3 * w); p5 = 1 - p3 - p4
        en5 = 3 * p3 + 4 * p4 + 5 * p5; vn5 = 3 ** 2 * p3 + 16 * p4 + 25 * p5 - en5 ** 2
        en = np.where(need == 3, en5, en3); vn = np.where(need == 3, vn5, vn3)
        cols["hgm_e_sets_pre"] = en; cols["hgm_mean_margin_pre"] = en * e1; cols["hgm_sd_margin_pre"] = np.sqrt(np.maximum(en * v1 + vn * e1 ** 2, 0.0))
        cols["hgm_set_win_pre"] = w
    out = L[["game_id", "team", "date", "season"]].copy()
    for k in ([f"gps_p{g}_pre" for g in GAMES] + ["gps_p_tiebreak_pre", "gps_mean_games_pre", "gps_hold_pre", "gps_opp_hold_pre", "hgm_e_sets_pre", "hgm_mean_margin_pre", "hgm_sd_margin_pre", "hgm_set_win_pre"]):
        out[k] = np.nan
        if n: out.loc[good.to_numpy(), k] = cols[k]
    return {"team": out.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


def perturb(raw: dict, ids, seed: int) -> dict:
    return _perturb(raw, ids, seed, ["score", "w_svpt", "w_1stIn", "w_2ndWon", "l_svpt", "l_1stIn", "l_2ndWon"])


def specs() -> list[FeatureSpec]:
    gps = [f"gps_p{g}_pre" for g in GAMES] + ["gps_p_tiebreak_pre", "gps_mean_games_pre", "gps_hold_pre", "gps_opp_hold_pre"]
    hgm = ["hgm_e_sets_pre", "hgm_mean_margin_pre", "hgm_sd_margin_pre", "hgm_set_win_pre"]
    return [
        FeatureSpec(S, "ten.games_per_set_distribution", "team", gps, "PARTIAL", "model PMF of games per set over {6,7,8,9,10,12,13} and P(tiebreak) from the pair's closed-form hold probabilities (opponent-adjusted serve-point-win, half-life 365 days over 1095), averaged over the first server",
                   ["closed-form game hold formula", "set-score dynamic programme with alternating serve and randomised first server", "PMF of games per set", "P(tiebreak)"],
                   ["logistic ridge opponent-adjusted spw (a simple additive adjustment is used)", "calibration to empirical set-score frequency by bins with kernel smoothing and n/(n+60) shrinkage"], ["sackmann_atp_wta_matches"], "pregame_rolling"),
        FeatureSpec(S, "ten.hold_gap_expected_margin", "team", hgm, "PARTIAL", "mean and SD of the total game margin (player minus opponent) of the match from the set margin pmf and the set-count distribution of the format (best_of 3 or 5, iid sets, Wald identities)",
                   ["closed-form hold", "set margin dynamic programme averaged over first server", "roll-up over the set-count distribution for the format", "mean and SD of the total game margin"],
                   ["opponent-adjusted spw by the catalog's regression (additive adjustment used)", "Beta-posterior draws of spw (SD about 0.015)", "final-set tiebreak rules of the Grand Slams"], ["sackmann_atp_wta_matches"], "pregame_rolling"),
    ]
