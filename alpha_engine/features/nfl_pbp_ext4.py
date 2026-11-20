"""NFL schedule / play-by-play builders, batch 4 (RESEARCH_ONLY): market-free team rating, points for / against rates, neutral pass rate over expected, and
kernel-conditional team-score and margin distributions. No market price or line enters anywhere.

Source: nflverse schedule (games.csv, 1999-2026) and nflverse play_by_play 2010-2026, both archived in sift-data-vault (archives/NFL/inseason_player_team, archives/NFL/pbp).
Point in time: every value for a game dated d uses only games dated STRICTLY BEFORE d; the conditional distributions for season S use only seasons before S.

Common
  Games: schedule rows with season >= 1999 and home_score present, all game types. Team codes OAK->LV, SD->LAC, STL->LA. Order: (date, game_id). Two team rows per game.
  Pool of a cutoff date d (season S = the season of the games played on d): games dated before d with season >= S-1, chronological. rank(team, game) = number of LATER pool games of that team.
  Fewer than 16 pool games -> every column of A and B is NaN for the date.

A nfl.own_team_rating_market_free (PARTIAL)
  Weighted ridge over the pool: y = clip(home_score - away_score, -24, 24); design +1 home team, -1 away team, and a home-edge column (1, or 0 when location == "Neutral");
  weight 0.5 ** (min(rank_home, rank_away) / 10); penalty 20 on every team coefficient, none on the home edge. Solve (X'WX + P) b = X'Wy.
  omr_rating_pre = team coefficient, omr_home_edge_pre = home-edge coefficient, omr_exp_margin_pre = rating_team - rating_opp + s x home_edge (s = +1 home, -1 away, 0 neutral).

B nfl.team_points_for_against_rates (PARTIAL)
  Observations: two per pool game (offence O scores pts against defence D), kept when min(rank_O, rank_D) < 17; weight 0.5 ** (min(rank_O, rank_D) / 8).
  Weighted ridge pts ~ b0 + a_O + d_D + h x [O is home and not neutral]; penalty 6 on every a and d, none on b0 and h.
  pfa_off_pre = b0 + a_T; pfa_def_pre = b0 + d_T (points allowed; higher = worse defence); pfa_exp_points_pre = b0 + a_T + d_Opp + h x [T home, not neutral].

C nfl.proe (PARTIAL)
  Neutral plays: pbp rows with pass == 1 or rush == 1, qb_kneel != 1, qb_spike != 1, xpass present, wp present, qtr <= 3, 0.20 <= wp <= 0.80, posteam present.
  Per game and offence: n = neutral plays, s = sum(pass - xpass), p = sum(pass). A team's last 12 games WITH n > 0 dated before d, newest first with index r, weight 0.5 ** (r / 6):
  proe_pre = sum(w s) / sum(w n); proe_pass_rate_pre = sum(w p) / sum(w n); proe_n_pre = sum(n). NaN when the team has no such earlier game.

D nfl.team_score_pmf_own_mean (PROXY) and E nfl.model_margin_lattice (PROXY)
  For a team row of season S with x present: reference = all team rows of seasons < S with x present (NaN unless at least 500); kernel k_i = exp(-0.5 ((x_i - x) / BW) ** 2);
  P(event) = sum(k_i [event_i]) / sum(k_i).
  D: x = pfa_exp_points_pre, BW 2.5, events: team points >= r for r in 14, 17, 21, 24, 28, 31 (tsp_ge{r}_pre) and team points == r for r in 3, 10 (tsp_eq{r}_pre).
  E: x = omr_exp_margin_pre, BW 3.0, events: margin >= r for r in 1, 4, 8, 15 (mml_ge{r}_pre), margin == 3 or == -3 (mml_abs3_pre), margin == 7 or == -7 (mml_abs7_pre),
     game went to overtime (schedule overtime == 1; mml_ot_pre). Margin and points are final (overtime-inclusive).
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec
from .nfl_ext import TEAM_FIX

S = "NFL"
FIRST = 1999
CAP, LAM_R, HL_R = 24.0, 20.0, 10.0
LAST_P, LAM_P, HL_P = 17, 6.0, 8.0
LAST_E, HL_E = 12, 6.0
MIN_POOL, MIN_REF = 16, 500
BW_PTS, BW_MAR = 2.5, 3.0
PTS_GE, PTS_EQ, MAR_GE = (14, 17, 21, 24, 28, 31), (3, 10), (1, 4, 8, 15)
PBP_COLS = ["game_id", "posteam", "qtr", "pass", "rush", "qb_kneel", "qb_spike", "wp", "xpass"]
CONTENT = ["posteam", "qtr", "pass", "rush", "qb_kneel", "qb_spike", "wp", "xpass"]
GAMES_CONTENT = ["home_score", "away_score", "overtime"]
OMR_COLS = ["omr_rating_pre", "omr_home_edge_pre", "omr_exp_margin_pre"]
PFA_COLS = ["pfa_off_pre", "pfa_def_pre", "pfa_exp_points_pre"]
PROE_COLS = ["proe_pre", "proe_pass_rate_pre", "proe_n_pre"]
TSP_COLS = [f"tsp_ge{r}_pre" for r in PTS_GE] + [f"tsp_eq{r}_pre" for r in PTS_EQ]
MML_COLS = [f"mml_ge{r}_pre" for r in MAR_GE] + ["mml_abs3_pre", "mml_abs7_pre", "mml_ot_pre"]


def load_raw(pbp_dir, games_file) -> dict:
    import pyarrow.parquet as pq
    fs = sorted(glob.glob(str(Path(pbp_dir) / "*.parquet")))
    pbp = pd.concat([pd.read_parquet(f, columns=[c for c in PBP_COLS if c in pq.read_schema(f).names]) for f in fs], ignore_index=True)
    games = pd.read_csv(games_file, usecols=["game_id", "season", "week", "game_type", "gameday", "home_team", "away_team", "home_score", "away_score", "overtime", "location"])
    return {"pbp": pbp, "games": games}


def _games(games: pd.DataFrame) -> pd.DataFrame:
    g = games[(games.season >= FIRST) & games.home_score.notna() & games.away_score.notna()].copy()
    g["date"] = pd.to_datetime(g.gameday)
    for c in ("home_team", "away_team"):
        g[c] = g[c].astype("object").replace(TEAM_FIX)
    return g.sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)


def _ratings(g: pd.DataFrame) -> pd.DataFrame:
    """Per game: the A and B columns for the home and the away side (suffix _h / _a)."""
    teams = sorted(set(g.home_team) | set(g.away_team)); ti = {t: i for i, t in enumerate(teams)}; T = len(teams)
    h = g.home_team.map(ti).to_numpy(); a = g.away_team.map(ti).to_numpy()
    hs = g.home_score.to_numpy(float); as_ = g.away_score.to_numpy(float)
    ne = (g.location.astype(str) != "Neutral").to_numpy(float); season = g.season.to_numpy(); date = g.date.to_numpy()
    n = len(g); out = np.full((n, 11), np.nan)
    starts = np.flatnonzero(np.r_[True, date[1:] != date[:-1]]); ends = np.r_[starts[1:], n]
    for s0, e0 in zip(starts, ends):
        prev = np.flatnonzero(season[:s0] >= season[s0:e0].max() - 1); lo = int(prev[0]) if len(prev) else s0
        m = s0 - lo
        if m < MIN_POOL:
            continue
        ph, pa, pne = h[lo:s0], a[lo:s0], ne[lo:s0]
        cnt = np.zeros(T, int); rh = np.empty(m, int); ra = np.empty(m, int)
        for i in range(m - 1, -1, -1):
            rh[i] = cnt[ph[i]]; ra[i] = cnt[pa[i]]; cnt[ph[i]] += 1; cnt[pa[i]] += 1
        rk = np.minimum(rh, ra); ix = np.arange(m)
        # A: margin ridge
        X = np.zeros((m, T + 1)); X[ix, ph] = 1.0; X[ix, pa] = -1.0; X[:, T] = pne
        w = 0.5 ** (rk / HL_R); y = np.clip(hs[lo:s0] - as_[lo:s0], -CAP, CAP)
        P = np.eye(T + 1) * LAM_R; P[T, T] = 0.0
        A = X.T @ (X * w[:, None]) + P
        try:
            b = np.linalg.solve(A, X.T @ (w * y))
        except np.linalg.LinAlgError:
            b = None
        # B: points ridge  [b0 | a (T) | d (T) | h]
        keep = rk < LAST_P; k = int(keep.sum()); kh, ka, kne = ph[keep], pa[keep], pne[keep]; jx = np.arange(k)
        Z = np.zeros((2 * k, 2 * T + 2)); Z[:, 0] = 1.0
        Z[jx, 1 + kh] = 1.0; Z[jx, 1 + T + ka] = 1.0; Z[jx, 2 * T + 1] = kne
        Z[k + jx, 1 + ka] = 1.0; Z[k + jx, 1 + T + kh] = 1.0
        w2 = np.tile(0.5 ** (rk[keep] / HL_P), 2); y2 = np.r_[hs[lo:s0][keep], as_[lo:s0][keep]]
        Q = np.eye(2 * T + 2) * LAM_P; Q[0, 0] = 0.0; Q[-1, -1] = 0.0
        try:
            c = np.linalg.solve(Z.T @ (Z * w2[:, None]) + Q, Z.T @ (w2 * y2))
        except np.linalg.LinAlgError:
            c = None
        for j in range(s0, e0):
            H, V, e = h[j], a[j], ne[j]
            if b is not None:
                out[j, 0:5] = [b[H], b[V], b[T], b[H] - b[V] + e * b[T], b[V] - b[H] - e * b[T]]
            if c is not None:
                out[j, 5:11] = [c[0] + c[1 + H], c[0] + c[1 + T + H], c[0] + c[1 + H] + c[1 + T + V] + e * c[-1], c[0] + c[1 + V], c[0] + c[1 + T + V], c[0] + c[1 + V] + c[1 + T + H]]
    return pd.DataFrame(out, columns=["r_h", "r_a", "he", "em_h", "em_a", "off_h", "def_h", "ep_h", "off_a", "def_a", "ep_a"])


def _team_rows(g: pd.DataFrame, r: pd.DataFrame) -> pd.DataFrame:
    base = ["game_id", "season", "week", "game_type", "date"]
    hm = g[base].assign(team=g.home_team, opp=g.away_team, pts=g.home_score, opp_pts=g.away_score, ot=g.overtime, omr_rating_pre=r.r_h, omr_home_edge_pre=r.he, omr_exp_margin_pre=r.em_h,
                        pfa_off_pre=r.off_h, pfa_def_pre=r.def_h, pfa_exp_points_pre=r.ep_h)
    aw = g[base].assign(team=g.away_team, opp=g.home_team, pts=g.away_score, opp_pts=g.home_score, ot=g.overtime, omr_rating_pre=r.r_a, omr_home_edge_pre=r.he, omr_exp_margin_pre=r.em_a,
                        pfa_off_pre=r.off_a, pfa_def_pre=r.def_a, pfa_exp_points_pre=r.ep_a)
    return pd.concat([hm, aw], ignore_index=True).sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)


def _proe(p: pd.DataFrame, t: pd.DataFrame) -> pd.DataFrame:
    def num(c):
        return pd.to_numeric(p[c], errors="coerce") if c in p else pd.Series(np.nan, index=p.index)
    pa_, ru, wp, xp, q = num("pass"), num("rush"), num("wp"), num("xpass"), num("qtr")
    ok = ((pa_ == 1) | (ru == 1)) & (num("qb_kneel") != 1) & (num("qb_spike") != 1) & xp.notna() & wp.notna() & (q <= 3) & (wp >= 0.20) & (wp <= 0.80) & p.posteam.notna()
    d = pd.DataFrame({"game_id": p.game_id[ok], "team": p.posteam[ok].astype("object").replace(TEAM_FIX), "n": 1.0, "s": (pa_ - xp)[ok], "p": pa_[ok]})
    a = d.groupby(["game_id", "team"], as_index=False)[["n", "s", "p"]].sum()
    m = t[["game_id", "team", "date"]].merge(a, on=["game_id", "team"], how="inner").sort_values(["team", "date", "game_id"], kind="mergesort")
    rows = []
    for team, x in m.groupby("team", sort=False):
        nn, ss, pp = x.n.to_numpy(), x.s.to_numpy(), x.p.to_numpy()
        tx = t.loc[t.team == team, ["game_id", "date"]]; pos = np.searchsorted(x.date.to_numpy(), tx.date.to_numpy(), side="left")
        for gid, e in zip(tx.game_id.to_numpy(), pos):
            if e == 0:
                continue
            b = max(0, e - LAST_E); w = 0.5 ** (np.arange(e - b - 1, -1, -1) / HL_E); sw = float((w * nn[b:e]).sum())
            rows.append((gid, team, float((w * ss[b:e]).sum()) / sw, float((w * pp[b:e]).sum()) / sw, float(nn[b:e].sum())))
    return pd.DataFrame(rows, columns=["game_id", "team"] + PROE_COLS)


def _kernel(t: pd.DataFrame, xcol: str, bw: float, events: dict) -> pd.DataFrame:
    out = pd.DataFrame(np.nan, index=t.index, columns=list(events)); x = t[xcol].to_numpy(float); season = t.season.to_numpy(); has = ~np.isnan(x)
    ev = {k: np.asarray(v, float) for k, v in events.items()}
    for s in np.unique(season):
        ref = has & (season < s); cur = np.flatnonzero(has & (season == s))
        if ref.sum() < MIN_REF or not len(cur):
            continue
        K = np.exp(-0.5 * ((x[ref][None, :] - x[cur][:, None]) / bw) ** 2); tot = K.sum(axis=1)
        for k, v in ev.items():
            out.loc[t.index[cur], k] = (K @ v[ref]) / tot
    return out


def compute(raw: dict) -> dict:
    g = _games(raw["games"]); t = _team_rows(g, _ratings(g))
    t = t.merge(_proe(raw["pbp"], t), on=["game_id", "team"], how="left")
    pts = t.pts.to_numpy(float); mar = pts - t.opp_pts.to_numpy(float)
    ev_p = {**{f"tsp_ge{k}_pre": pts >= k for k in PTS_GE}, **{f"tsp_eq{k}_pre": pts == k for k in PTS_EQ}}
    ev_m = {**{f"mml_ge{k}_pre": mar >= k for k in MAR_GE}, "mml_abs3_pre": np.abs(mar) == 3, "mml_abs7_pre": np.abs(mar) == 7, "mml_ot_pre": pd.to_numeric(t.ot, errors="coerce").to_numpy() == 1}
    t = pd.concat([t, _kernel(t, "pfa_exp_points_pre", BW_PTS, ev_p), _kernel(t, "omr_exp_margin_pre", BW_MAR, ev_m)], axis=1)
    cols = ["game_id", "season", "week", "game_type", "team", "opp", "date"] + OMR_COLS + PFA_COLS + PROE_COLS + TSP_COLS + MML_COLS
    return {"team": t[cols].sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


def specs() -> list[FeatureSpec]:
    raw_s, raw_p = "nflverse schedule (scores, overtime flag, location)", "nflverse play_by_play (pass, rush, xpass, wp, qtr)"
    return [
        FeatureSpec(S, "nfl.own_team_rating_market_free", "team", OMR_COLS, "PARTIAL",
                    "Weighted ridge of capped (+/-24) game margin on team, opponent and home indicators over games since the start of the prior season, weight 0.5^(games_ago/10), penalty 20; "
                    "team rating, home edge and expected margin against the opponent, in points",
                    ["capped-margin ridge with home indicator", "window from the start of the prior season", "games-ago half-life 10", "expected margin vs the opponent"],
                    ["penalty fixed at 20 (no leave-one-season-out CV)", "home edge refit at every date, not yearly", "50/50 blend with the opponent-adjusted EPA/play margin rating", "quarterback adjustment"],
                    [raw_s], "pregame_rolling"),
        FeatureSpec(S, "nfl.team_points_for_against_rates", "team", PFA_COLS, "PARTIAL",
                    "Weighted ridge of team points on offence and opposing-defence indicators with a home indicator over each side's last 17 games, weight 0.5^(games_ago/8), penalty 6; "
                    "offence points rate, defence points-allowed rate and expected points against the opponent",
                    ["separate offence / defence opponent-adjusted points rates", "last 17 games, half-life 8", "ridge shrink of 6 game-equivalents", "home indicator"],
                    ["one-third pre-season reversion to the league mean", "simulation of remaining games conditioned on banked points"], [raw_s], "pregame_rolling"),
        FeatureSpec(S, "nfl.proe", "team", PROE_COLS, "PARTIAL",
                    "Pass rate over expected on neutral plays (quarters 1-3, win probability 0.20-0.80) over the team's last 12 games, half-life 6 games; neutral pass rate and sample size",
                    ["mean(actual - expected pass) over neutral plays per team", "recency weighting"],
                    ["own expected-pass model: uses nflfastR xpass, whose model is fitted upstream on seasons that include later games", "coordinator / quarterback regime flags", "attempts forecast"],
                    [raw_p, raw_s], "pregame_rolling"),
        FeatureSpec(S, "nfl.team_score_pmf_own_mean", "team", TSP_COLS, "PROXY",
                    "Kernel-conditional (bandwidth 2.5 points) empirical distribution of final team points given the market-free expected team points, fitted on earlier seasons only: "
                    "P(points >= 14/17/21/24/28/31) and P(points = 3/10)",
                    ["distribution conditioned on a market-free expected team points", "walk-forward by season", "key-number masses at 3 and 10"],
                    ["negative-binomial body with per-bin dispersion and smoothed correction ratio (kernel empirical frequencies instead)", "regulation-only pmf (final scores only)",
                     "conditioning mean is nfl.team_points_for_against_rates, not nfl.model_team_points_mean", "full integer pmf (8 rungs only)"], [raw_s], "pregame_rolling"),
        FeatureSpec(S, "nfl.model_margin_lattice", "team", MML_COLS, "PROXY",
                    "Kernel-conditional (bandwidth 3 points) empirical distribution of final margin given the market-free expected margin, fitted on earlier seasons only: "
                    "P(margin >= 1/4/8/15), P(|margin| = 3), P(|margin| = 7), P(overtime)",
                    ["margin distribution around a market-free model mean", "key-number atoms at 3 and 7", "regulation-tie (overtime) mass", "walk-forward by season"],
                    ["drive-level simulation and isotonic correction (kernel empirical frequencies instead)", "regulation margin lattice (final margins plus the overtime flag only)", "full integer lattice (7 events only)"],
                    [raw_s], "pregame_rolling"),
    ]
