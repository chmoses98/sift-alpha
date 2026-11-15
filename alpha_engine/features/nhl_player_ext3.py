"""Phase 6 NHL skater-game builder (RESEARCH_ONLY): nhl.pk_structure_opp.

Raw data (owner's NHL-edge-finder archive, read only, no new collection): ``players/team_states_*`` (team-game universe, seconds short-handed), ``players/shots_*`` (NHL shot events with x, y, strength,
shooter), ``players/players_*`` (skater-game box with PP ice time and PP shots on goal), ``moneypuck/shots_*`` (MoneyPuck xGoal with skaters on ice; seasons 2021-2025 only).

Catalog definition: "Opponent PK SOGA/60 and xGA/60, shot-location split on PK; the share of PK shots from the point; combine with the player's PP shot role."

Output table ``team`` is keyed (game_id, team) where ``team`` is the SKATER id (one row per skater-game; goalies excluded). Every value for game G uses only games on STRICTLY EARLIER DATES of the
current season plus the whole previous season ("window").

Opponent penalty kill (the team the skater faces):
  * pko_soga60_pre: shots on goal (SOG + GOAL) by the opponent's opponents at strength PP per 60 minutes the opponent was short-handed (team_states.sec_sh), shrunk to the league rate with k = 120 PK minutes;
  * pko_xga60_pre: MoneyPuck xGoal of power-play shots against the opponent (shooting side has more skaters, no empty net) per 60 short-handed minutes, same shrinkage; MoneyPuck seasons only;
  * pko_point_share_pre / pko_slot_share_pre: share of PP shot attempts against the opponent (SOG + GOAL + MISS; blocked attempts are excluded because they are logged at the block location) taken from
    the point (offensive zone, |x| <= 54, i.e. >= 35 ft from the goal line) / from the slot (|x| >= 69 and |y| <= 22), each shrunk to the league share with k = 150 attempts.
Skater power-play shot role:
  * pp_sog60_pre: the skater's PP shots on goal per 60 PP minutes, shrunk to the position-group (forward / defence) rate with k = 60 PP minutes;
  * pp_point_share_pre: share of the skater's PP attempts (SOG + GOAL + MISS) from the point, shrunk to the position-group share with k = 20 attempts.
Combination:
  * pko_combo_pp_sog60_pre = pp_sog60 x (pko_soga60 / league PK SOGA60) x [pp_point_share x (pko_point_share / league point share) + (1 - pp_point_share) x ((1 - pko_point_share) / (1 - league point share))]:
    the skater's PP shot rate rescaled by how many shots the opponent concedes on the PK and by how its location mix suits the skater's role.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec
from .nba_ext3 import before

S = "NHL"
K_PK_S, K_LOC, K_PP_S, K_PPLOC = 120 * 60.0, 150.0, 60 * 60.0, 20.0
TS_COLS = ["game_id", "season", "game_date", "game_type", "team_id", "is_home", "sec_sh"]
SH_COLS = ["game_id", "team_id", "shooter_id", "kind", "x", "y", "zone", "strength"]
PL_COLS = ["game_id", "season", "game_date", "player_id", "team_id", "position", "toi_pp_s", "sog_pp"]
MP_COLS = ["nhl_game_id", "isHomeTeam", "xGoal", "homeSkatersOnIce", "awaySkatersOnIce", "shotOnEmptyNet"]
TS_CONTENT = ["sec_sh"]
SH_CONTENT = ["team_id", "shooter_id", "kind", "x", "y", "zone", "strength"]
PL_CONTENT = ["toi_pp_s", "sog_pp"]
MP_CONTENT = ["isHomeTeam", "xGoal", "homeSkatersOnIce", "awaySkatersOnIce", "shotOnEmptyNet"]
COLS = ["pko_soga60_pre", "pko_xga60_pre", "pko_point_share_pre", "pko_slot_share_pre", "pp_sog60_pre", "pp_point_share_pre", "pko_combo_pp_sog60_pre"]


def load_raw(nhl_dir) -> dict:
    h = Path(nhl_dir)
    cat = lambda pat, cols: pd.concat([pd.read_parquet(f, columns=cols) for f in sorted(glob.glob(str(h / pat)))], ignore_index=True)
    return {"players": cat("players/players_*.parquet", PL_COLS), "team_states": cat("players/team_states_*.parquet", TS_COLS), "shots": cat("players/shots_*.parquet", SH_COLS),
            "mp": cat("moneypuck/shots_*.parquet", MP_COLS)}


def _window(df: pd.DataFrame, val: pd.Series, key: str | None) -> np.ndarray:
    """Sum of val over rows with the same key on STRICTLY EARLIER dates of the same season, plus the key's whole previous season (key None = league)."""
    by = ([key] if key else []) + ["season"]
    cur = before(df, val, by=by)
    tot = df.assign(_v=np.nan_to_num(np.asarray(val, dtype=float))).groupby(by)._v.sum().reset_index(); tot["season"] += 1
    prev = df[by].merge(tot, on=by, how="left")._v.fillna(0.0).to_numpy()
    return cur + prev


def _div(a, b):
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(b > 0, a / np.where(b > 0, b, 1.0), np.nan)


def _team_pk(raw: dict) -> pd.DataFrame:
    """Per team-game: seconds short-handed and what the PP opponent produced in those seconds."""
    t = raw["team_states"].drop_duplicates(["game_id", "team_id"]).copy()
    opp = t[["game_id", "team_id"]].rename(columns={"team_id": "opp_id"})
    t = t.merge(opp, on="game_id"); t = t[t.team_id != t.opp_id]
    s = raw["shots"]; s = s[s.strength == "PP"].copy()
    s["sog"] = s.kind.isin(["SOG", "GOAL"]).astype(float); s["att"] = s.kind.isin(["SOG", "GOAL", "MISS"]).astype(float)
    ax = s.x.abs()
    s["pt"] = s.att * ((s.zone == "O") & (ax <= 54)).astype(float); s["slot"] = s.att * ((ax >= 69) & (s.y.abs() <= 22)).astype(float)
    a = s.groupby(["game_id", "team_id"])[["sog", "att", "pt", "slot"]].sum()          # produced BY team_id on the PP -> conceded by its opponent on the PK
    t = t.merge(a, left_on=["game_id", "opp_id"], right_index=True, how="left")
    m = raw["mp"]; mp_games = set(m.nhl_game_id.dropna().astype("int64"))
    hs, aw = m.homeSkatersOnIce.astype(float), m.awaySkatersOnIce.astype(float); home = m.isHomeTeam.astype(float) == 1.0
    ppm = m[((home & (hs > aw)) | (~home & (aw > hs))) & (m.shotOnEmptyNet.fillna(0) == 0)]
    # xGoal is stored as float32: cast to float64 BEFORE summing (Phase 6 round-1 blind comparison found single-precision sums; same defect as Phase 15 nhl.ixg_player)
    x = ppm.assign(game_id=ppm.nhl_game_id.astype("int64"), shooter_home=(ppm.isHomeTeam.astype(float) == 1.0), xg=ppm.xGoal.astype("float64")).groupby(["game_id", "shooter_home"]).xg.sum().rename("xga")
    t["shooter_home"] = ~t.is_home.astype(bool)                                         # the PP shooters are the opponent
    t = t.merge(x, left_on=["game_id", "shooter_home"], right_index=True, how="left")
    t[["sog", "att", "pt", "slot"]] = t[["sog", "att", "pt", "slot"]].fillna(0.0)
    t["has_mp"] = t.game_id.isin(mp_games)
    t["xga"] = t.xga.fillna(0.0).where(t.has_mp, 0.0); t["sh_mp"] = t.sec_sh.astype(float).where(t.has_mp, 0.0)
    t["sec_sh"] = t.sec_sh.astype(float)
    t["date"] = pd.to_datetime(t.game_date); t["season"] = t.season.astype(int)
    return t.sort_values(["date", "game_id", "team_id"], kind="mergesort").reset_index(drop=True)


def compute(raw: dict) -> dict:
    t = _team_pk(raw)
    W = {c: _window(t, t[c], "team_id") for c in ("sec_sh", "sog", "att", "pt", "slot", "xga", "sh_mp")}
    L = {c: _window(t, t[c], None) for c in ("sec_sh", "sog", "att", "pt", "slot", "xga", "sh_mp")}
    lg_soga = 3600 * _div(L["sog"], L["sec_sh"]); lg_xga = 3600 * _div(L["xga"], L["sh_mp"]); lg_pt = _div(L["pt"], L["att"]); lg_slot = _div(L["slot"], L["att"])
    t["pko_soga60_pre"] = 3600 * (W["sog"] + K_PK_S * lg_soga / 3600) / (W["sec_sh"] + K_PK_S)
    t["pko_xga60_pre"] = 3600 * (W["xga"] + K_PK_S * lg_xga / 3600) / (W["sh_mp"] + K_PK_S)
    t["pko_point_share_pre"] = (W["pt"] + K_LOC * lg_pt) / (W["att"] + K_LOC)
    t["pko_slot_share_pre"] = (W["slot"] + K_LOC * lg_slot) / (W["att"] + K_LOC)
    t["lg_soga"], t["lg_pt"] = lg_soga, lg_pt
    pk = t[["game_id", "team_id", "pko_soga60_pre", "pko_xga60_pre", "pko_point_share_pre", "pko_slot_share_pre", "lg_soga", "lg_pt"]].rename(columns={"team_id": "opp_id"})
    opp_of = t[["game_id", "team_id", "opp_id"]]

    # skater power-play role
    p = raw["players"]; p = p[p.position != "G"].drop_duplicates(["game_id", "player_id"]).copy()
    s = raw["shots"]; s = s[(s.strength == "PP") & s.kind.isin(["SOG", "GOAL", "MISS"])].copy()
    s["pt"] = ((s.zone == "O") & (s.x.abs() <= 54)).astype(float); s["att"] = 1.0
    ps = s.groupby(["game_id", "shooter_id"])[["att", "pt"]].sum()
    p = p.merge(ps, left_on=["game_id", "player_id"], right_index=True, how="left")
    p[["att", "pt"]] = p[["att", "pt"]].fillna(0.0)
    p["toi_pp"] = p.toi_pp_s.astype(float).fillna(0.0); p["sog_pp"] = p.sog_pp.astype(float).fillna(0.0)
    p["grp"] = np.where(p.position == "D", "D", "F"); p["date"] = pd.to_datetime(p.game_date); p["season"] = p.season.astype(int)
    p = p.sort_values(["date", "game_id", "player_id"], kind="mergesort").reset_index(drop=True)
    P = {c: _window(p, p[c], "player_id") for c in ("toi_pp", "sog_pp", "att", "pt")}
    G = {c: _window(p, p[c], "grp") for c in ("toi_pp", "sog_pp", "att", "pt")}
    g_rate = _div(G["sog_pp"], G["toi_pp"]); g_pt = _div(G["pt"], G["att"])
    p["pp_sog60_pre"] = 3600 * (P["sog_pp"] + K_PP_S * g_rate) / (P["toi_pp"] + K_PP_S)
    p["pp_point_share_pre"] = (P["pt"] + K_PPLOC * g_pt) / (P["att"] + K_PPLOC)
    p = p.merge(opp_of, on=["game_id", "team_id"], how="left").merge(pk, on=["game_id", "opp_id"], how="left")
    with np.errstate(invalid="ignore", divide="ignore"):
        loc = p.pp_point_share_pre * (p.pko_point_share_pre / p.lg_pt) + (1 - p.pp_point_share_pre) * ((1 - p.pko_point_share_pre) / (1 - p.lg_pt))
        p["pko_combo_pp_sog60_pre"] = p.pp_sog60_pre * (p.pko_soga60_pre / p.lg_soga) * loc
    out = p.rename(columns={"player_id": "team"})[["game_id", "team", "date", "season"] + COLS]
    return {"team": out}


def specs() -> list[FeatureSpec]:
    return [FeatureSpec(S, "nhl.pk_structure_opp", "team", COLS, "FULL",
                        "opponent penalty kill: PP shots on goal and MoneyPuck xG conceded per 60 short-handed minutes (k = 120 PK minutes), point and slot shares of PP attempts conceded (k = 150); "
                        "skater PP role: PP SOG per 60 PP minutes (k = 60 minutes to the position group) and share of PP attempts from the point (k = 20); combined expected PP SOG per 60 against this PK",
                        ["opponent PK SOGA/60 (shots on goal against per 60 short-handed minutes)", "opponent PK xGA/60 (MoneyPuck xGoal of PP shots against per 60 short-handed minutes)",
                         "shot-location split on PK (point share and slot share of PP attempts conceded)", "share of PK shots from the point",
                         "player's PP shot role (PP SOG/60 and share of own PP attempts from the point)", "combine (role-weighted rescaling of the skater's PP SOG/60 by the opponent's PK volume and location mix)"],
                        [], ["nhl_archive team_states", "nhl_archive shots", "nhl_archive players", "moneypuck shots (xGoal)"], "pregame_rolling")]
