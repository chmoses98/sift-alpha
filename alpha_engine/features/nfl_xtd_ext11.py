"""NFL batch 11 (RESEARCH_ONLY, PARTIAL): player expected touchdowns (xTD) from play-level opportunity. nflverse play-by-play + schedule only; no line or price.
Rows keyed (game_id, team) where `team` holds the player gsis id (harness convention of nfl_player_ext5); `pteam` is his club.

DEFINITIONS (every value for a row dated d uses only plays of games dated strictly before d)
  Games: schedule rows with home_score present, season >= 2010; codes OAK->LV, SD->LAC, STL->LA (schedule and posteam). Played games ordered (date, game_id).
  Opportunities (as nfl_player_ext5): posteam present, two_point_attempt != 1; target = play_type "pass" with receiver_player_id (player = receiver; TD = pass_touchdown == 1);
  carry = play_type "run" with rusher_player_id and qb_scramble != 1 (player = rusher; TD = rush_touchdown == 1).
  Cell = kind (target / carry) x yardline_100 bucket (<= 2, <= 5, <= 10, <= 20, else incl. missing) x down group (down 1-2 / 3-4 or missing). Model for season S: over opportunities of seasons
  max(2010, S-3) .. max(2010, S-1): p_cell = (TD + 10 p_all)/(n + 10), p_all = overall TD rate of those opportunities (absent cell -> p_all). Each opportunity of season S gets x = p_cell.
  Player-game (game, team, player) with >= 1 opportunity: xtd = sum x; team-game xtd_team = sum x over all the club's opportunities.
  Player EWM over his player-games ordered (date, game_id, team), half-life 6: W(z) = sum r^(i-j) z_j; read after his last player-game dated before d.
  Club EWM over the club's played games (half-life 6) of xtd_team.
  Universe: players with an opportunity for T in T's last 4 played games before d (both clubs: latest date wins; ties smaller code).
  League share prior of season S: mean over player-games of season S-1 of xtd / xtd_team (xtd_team > 0).
nfl.player_xtd  pxt_xtd_pg_pre = W(xtd)/W(1); pxt_share_pre = (W(xtd) + K L_share)/(W(xtd_team) + K), K = 4 x (season S-1 mean xtd_team per team-game), L_share = league share prior;
                pxt_exp_td_pre = pxt_share_pre x (club EWM xtd_team per game).
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec
from .nfl_ext import TEAM_FIX

S = "NFL"
HIST_FIRST, OUT_FIRST = 2010, 2013
HL = 6.0
PREV = 4
PBP_COLS = ["game_id", "posteam", "play_type", "two_point_attempt", "qb_scramble", "receiver_player_id", "rusher_player_id", "yardline_100", "down", "pass_touchdown", "rush_touchdown"]
CONTENT = ["receiver_player_id", "rusher_player_id", "yardline_100", "down", "pass_touchdown", "rush_touchdown"]
GAMES_COLS = ["game_id", "season", "gameday", "home_team", "away_team", "home_score"]


def load_raw(pbp_dir, games_file) -> dict:
    fs = sorted(glob.glob(str(Path(pbp_dir) / "play_by_play_*.parquet"))) or sorted(glob.glob(str(Path(pbp_dir) / "pbp_*.parquet")))
    pbp = pd.concat([pd.read_parquet(f, columns=PBP_COLS) for f in fs], ignore_index=True)
    g = pd.read_csv(games_file, usecols=GAMES_COLS)
    g = g[(g.season >= HIST_FIRST) & g.home_score.notna()].drop_duplicates("game_id")
    pbp = pbp[pbp.game_id.isin(set(g.game_id))]
    warm = set(g.game_id[g.season < OUT_FIRST]); pw = pbp.game_id.isin(warm)
    return {"pbp": pbp[~pw].reset_index(drop=True), "games": g[g.season >= OUT_FIRST].reset_index(drop=True),
            "pbp_warm": pbp[pw].reset_index(drop=True), "games_warm": g[g.season < OUT_FIRST].reset_index(drop=True)}


def _all(raw, key):
    parts = [raw[k] for k in (key + "_warm", key) if raw.get(k) is not None and len(raw[k])]
    return pd.concat(parts, ignore_index=True) if parts else raw[key]


def _fix(s):
    return s.astype("object").replace(TEAM_FIX)


def _wsum(keys, x, hl):
    r = 0.5 ** (1.0 / hl); out = np.empty(len(x)); acc = 0.0; prev = None
    for i, (k, v) in enumerate(zip(keys.tolist(), np.asarray(x, float).tolist())):
        if k != prev:
            acc = 0.0; prev = k
        acc = acc * r + v; out[i] = acc
    return out


COLS = ["pxt_xtd_pg_pre", "pxt_share_pre", "pxt_exp_td_pre"]


def compute(raw: dict) -> dict:
    g = _all(raw, "games").drop_duplicates("game_id").copy(); g["date"] = pd.to_datetime(g.gameday)
    g["home_team"] = _fix(g.home_team); g["away_team"] = _fix(g.away_team)
    p = _all(raw, "pbp").merge(g[["game_id", "season", "date"]], on="game_id", how="inner")
    num = lambda c: pd.to_numeric(p[c], errors="coerce")  # noqa: E731
    ok = p.posteam.notna() & (num("two_point_attempt").fillna(0) != 1); pt = p.play_type.astype(object)
    tgt = ok & (pt == "pass") & p.receiver_player_id.notna(); car = ok & (pt == "run") & p.rusher_player_id.notna() & (num("qb_scramble").fillna(0) != 1)
    q = p[tgt | car].copy(); is_t = tgt[tgt | car].to_numpy()
    q["kind"] = np.where(is_t, 0, 1); q["pid"] = np.where(is_t, q.receiver_player_id, q.rusher_player_id); q["T"] = _fix(q.posteam)
    q["td"] = np.where(is_t, pd.to_numeric(q.pass_touchdown, errors="coerce") == 1, pd.to_numeric(q.rush_touchdown, errors="coerce") == 1).astype(float)
    y = pd.to_numeric(q.yardline_100, errors="coerce").to_numpy(); dn = pd.to_numeric(q.down, errors="coerce").to_numpy()
    yb = np.select([y <= 2, y <= 5, y <= 10, y <= 20], [0, 1, 2, 3], 4); dg = np.where((dn == 3) | (dn == 4), 1, 0)
    q["cell"] = q.kind * 10 + yb * 2 + dg
    q["x"] = np.nan
    for s_ in sorted(q.season.unique()):
        lo, hi = max(HIST_FIRST, s_ - 3), max(HIST_FIRST, s_ - 1)
        ref = q[(q.season >= lo) & (q.season <= hi)]; pall = ref.td.mean()
        t = ref.groupby("cell").td.agg(["sum", "count"]); pc = (t["sum"] + 10 * pall) / (t["count"] + 10)
        m = (q.season == s_).to_numpy(); q.loc[m, "x"] = q.loc[m, "cell"].map(pc).fillna(pall).to_numpy()
    tm = q.groupby(["game_id", "T"]).x.sum().rename("xtd_team").reset_index()
    pg = q.groupby(["game_id", "T", "pid"]).agg(date=("date", "first"), season=("season", "first"), xtd=("x", "sum")).reset_index().merge(tm, on=["game_id", "T"])
    pg = pg.sort_values(["pid", "date", "game_id", "T"], kind="mergesort").reset_index(drop=True)
    k = pg.pid.to_numpy(); st = pg[["pid", "date"]].copy()
    st["W_x"] = _wsum(k, pg.xtd, HL); st["W_t"] = _wsum(k, pg.xtd_team, HL); st["W_1"] = _wsum(k, np.ones(len(pg)), HL)
    # club slots, universe and club state
    slots = pd.concat([g.assign(team=g[a], opp=g[b])[["game_id", "season", "date", "team", "opp"]] for a, b in (("home_team", "away_team"), ("away_team", "home_team"))], ignore_index=True)
    slots = slots.sort_values(["team", "date", "game_id"], kind="mergesort").reset_index(drop=True)
    sl = slots.merge(tm.rename(columns={"T": "team"}), on=["game_id", "team"], how="left").fillna({"xtd_team": 0.0})
    cs = sl[["team", "date"]].copy(); kk = sl.team.to_numpy(); cs["C_t"] = _wsum(kk, sl.xtd_team, HL); cs["C_1"] = _wsum(kk, np.ones(len(sl)), HL)
    prev = []
    for team, rows in slots.groupby("team", sort=True):
        hd = rows.date.to_numpy(); hg = rows.game_id.to_numpy(); n = np.searchsorted(hd, hd, side="left")
        for o in range(1, PREV + 1):
            j = n - o; okk = j >= 0
            prev.append(pd.DataFrame({"game_id": hg[okk], "team": team, "prev_gid": hg[j[okk]]}))
    pv = pd.concat(prev, ignore_index=True)
    inv = pg[["game_id", "T", "pid", "date"]].rename(columns={"game_id": "prev_gid", "T": "team", "date": "pd"})
    u = pv.merge(inv, on=["prev_gid", "team"], how="inner").groupby(["game_id", "team", "pid"], sort=True)["pd"].max().reset_index()
    u = u.sort_values(["game_id", "pid", "pd", "team"], ascending=[True, True, False, True], kind="mergesort").drop_duplicates(["game_id", "pid"]).drop(columns="pd")
    u = u.merge(slots, on=["game_id", "team"], how="left")
    u = u[u.season >= OUT_FIRST].sort_values(["date", "pid"], kind="mergesort")
    f = pd.merge_asof(u, st.sort_values("date", kind="mergesort"), on="date", by="pid", allow_exact_matches=False, direction="backward")
    f = pd.merge_asof(f.sort_values("date", kind="mergesort"), cs.sort_values("date", kind="mergesort"), on="date", by="team", allow_exact_matches=False, direction="backward")
    lg = {s_ + 1: (float((x.xtd / x.xtd_team).mean()), float(sl[sl.season == s_].xtd_team.mean())) for s_, x in pg[pg.xtd_team > 0].groupby("season")}
    Ls = f.season.map(lambda s_: lg[s_][0]).to_numpy(float); K = 4.0 * f.season.map(lambda s_: lg[s_][1]).to_numpy(float)
    f["pxt_xtd_pg_pre"] = f.W_x / f.W_1
    f["pxt_share_pre"] = (f.W_x + K * Ls) / (f.W_t + K)
    f["pxt_exp_td_pre"] = f.pxt_share_pre * f.C_t / f.C_1
    f = f.rename(columns={"team": "pteam"}).rename(columns={"pid": "team"})
    out = f[["game_id", "team", "pteam", "opp", "season", "date"] + COLS].copy()
    for c in COLS:
        out[c] = out[c].astype("float64")
    return {"team": out.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


def specs() -> list[FeatureSpec]:
    return [FeatureSpec(S, "nfl.player_xtd", "team", COLS, "PARTIAL",
                        "Player expected touchdowns from a walk-forward league table P(TD | target or carry, yardline bucket, down group) (previous 3 seasons): EWM (half-life 6 games) per game, share of "
                        "the club's xTD shrunk with 4 games' worth of club xTD toward the league share, and expected TDs = share x club EWM xTD per game",
                        ["league-wide P(TD | yardline, down, play type, is_target)", "half-life 6 games", "share of team xTD with shrinkage", "through the previous game"],
                        ["ydstogo in the TD model (field position and down group only)", "logistic model (smoothed cell table)", "positional prior (league share used)", "the 17-team-game cap",
                         "recompute after inactives (availability not used)"], ["nflverse play_by_play 2010-2026", "nflverse schedule"])]


def perturb_nv(raw: dict, block_ids, seed: int) -> dict:
    """Role-preserving non-vacuity perturbation of nfl_player_ext5 (who caught / carried is permuted within each (game, posteam) of the block), so the universe of later rows is unchanged."""
    from .nfl_player_ext5 import perturb
    return perturb(raw, block_ids, seed)
