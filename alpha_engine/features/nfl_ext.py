"""NFL extension builders from nflverse injuries (final weekly status WITH a timestamp), snap counts and the player-id crosswalk (RESEARCH_ONLY).

Two catalog inputs, both PARTIAL by construction:
  nfl.injuries_pit  team-game counts of players listed Out / Doubtful / Questionable whose report was last modified AT OR BEFORE kickoff, a QB-out flag, and the prior-game snap share of the
                    players listed out. The file stores only the LAST status of each player-week: practice-status sequences and intra-week vintages are NOT available (the definition asks for them).
  nfl.snaps         team-game rotation depth and snap concentration, as an EWMA of strictly earlier games. Game-state splits (down/distance/score) and participation roles are NOT implemented.
Point-in-time rules enforced here (and tested by data_foundation.replay_ext): (1) an injury row is used only if date_modified <= kickoff; when gametime is missing (older seasons) kickoff is assumed to be
09:00 ET of the game day, the earliest plausible slot, so doubt can only EXCLUDE information; (2) snap counts enter only from games dated strictly before the game; (3) nothing from the game's own
box data is used. A team-game with no usable pre-kickoff report row (including every 2009 and 2025 game: timestamps 0.4% present / column absent) yields NaN, never an assumption; availability is decided per team-game, never from a season-wide statistic.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec, prior_ewm

S = "NFL"
TEAM_FIX = {"OAK": "LV", "SD": "LAC", "STL": "LA"}
OUT_STATUS = {"Out", "Doubtful"}
STATUSES = {"Out", "Doubtful", "Questionable"}
HL = 8.0


def _norm(s: pd.Series) -> pd.Series:
    return s.replace(TEAM_FIX)


def load_raw(inj_dir, snap_dir, players_file, games_file) -> dict:
    inj = pd.concat([pd.read_parquet(f, columns=["season", "game_type", "team", "week", "gsis_id", "position", "report_status", "date_modified"] if "date_modified" in pd.read_parquet(f).columns else None) for f in sorted(glob.glob(str(Path(inj_dir) / "injuries_*.parquet")))], ignore_index=True)
    snap = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(str(Path(snap_dir) / "snap_counts_*.parquet")))], ignore_index=True)
    snap = snap[snap["game_id"].notna()] if len(snap) else snap
    players = pd.read_parquet(players_file, columns=["gsis_id", "pfr_id"])
    games = pd.read_csv(games_file, usecols=["game_id", "season", "week", "game_type", "gameday", "gametime", "home_team", "away_team", "home_score"])
    return {"injuries": inj, "snaps": snap, "players": players, "games": games}


def _team_games(games: pd.DataFrame) -> pd.DataFrame:
    g = games[(games.season >= 2009) & games.home_score.notna()].copy()   # completed games only (a sample definition; features of a game never use later games)
    t = g.gametime.fillna("09:00").astype(str).str.slice(0, 5)
    local = pd.to_datetime(g.gameday + " " + t, errors="coerce").dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward")
    g["kickoff"] = local.dt.tz_convert("UTC"); g["date"] = pd.to_datetime(g.gameday)
    rows = []
    for side, opp in (("home_team", "away_team"), ("away_team", "home_team")):
        rows.append(g.assign(team=_norm(g[side]), opp=_norm(g[opp]))[["game_id", "season", "week", "game_type", "team", "opp", "date", "kickoff"]])
    tg = pd.concat(rows, ignore_index=True)
    return tg.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)


def compute(raw: dict) -> dict:
    tg = _team_games(raw["games"])
    inj = raw["injuries"].copy(); inj["team"] = _norm(inj["team"].astype(str))
    inj["mod"] = pd.to_datetime(inj["date_modified"], errors="coerce", utc=True) if "date_modified" in inj else pd.NaT
    inj = inj.merge(tg[["season", "week", "team", "game_id", "kickoff", "date"]], on=["season", "week", "team"], how="inner")
    usable = inj["mod"].notna() & (inj["mod"] <= inj["kickoff"])                      # rule (1): only reports last modified at or before kickoff
    inj = inj[usable].copy()
    present = inj.groupby(["game_id", "team"]).size().rename("_n_usable").reset_index()    # availability is LOCAL to the team-game (no season-wide statistic that could see later weeks)
    inj = inj[inj["report_status"].isin(STATUSES)].copy()
    # prior snap share of each listed player: last snap row of the same player and team dated strictly before this game
    sn = raw["snaps"].merge(raw["players"].dropna().drop_duplicates("pfr_id"), left_on="pfr_player_id", right_on="pfr_id", how="left")
    sn["team"] = _norm(sn["team"].astype(str))
    sd = tg[["game_id", "date"]].drop_duplicates("game_id").rename(columns={"date": "sdate"})
    sn = sn.merge(sd, on="game_id", how="left").dropna(subset=["gsis_id", "sdate"])[["gsis_id", "team", "sdate", "offense_pct", "defense_pct"]].sort_values("sdate", kind="mergesort")
    inj = inj.sort_values("date", kind="mergesort")
    m = pd.merge_asof(inj, sn, left_on="date", right_on="sdate", by=["gsis_id", "team"], allow_exact_matches=False, direction="backward")   # rule (2): strictly earlier
    m["is_out"] = m.report_status.isin(OUT_STATUS)
    agg = m.groupby(["game_id", "team"]).apply(lambda d: pd.Series({
        "inj_out_n_pre": float((d.report_status == "Out").sum()), "inj_doubt_n_pre": float((d.report_status == "Doubtful").sum()), "inj_quest_n_pre": float((d.report_status == "Questionable").sum()),
        "inj_qb_out_pre": float(((d.position == "QB") & d.is_out).any()), "inj_out_off_snap_pre": float(d.loc[d.is_out, "offense_pct"].fillna(0).sum()), "inj_out_def_snap_pre": float(d.loc[d.is_out, "defense_pct"].fillna(0).sum())}), include_groups=False).reset_index()
    t = tg.merge(present, on=["game_id", "team"], how="left").merge(agg, on=["game_id", "team"], how="left")
    cols = ["inj_out_n_pre", "inj_doubt_n_pre", "inj_quest_n_pre", "inj_qb_out_pre", "inj_out_off_snap_pre", "inj_out_def_snap_pre"]
    # a team-game with at least one usable pre-kickoff report row and no Out/Doubtful/Questionable listing is a genuine 0; a team-game with NO usable row is NaN (never an assumption)
    for c in cols:
        t[c] = np.where(t["_n_usable"].notna(), t[c].fillna(0.0), np.nan)
    t = t.drop(columns=["_n_usable"])
    # snaps: per team-game rotation depth from that game's own snaps, then EWMA of STRICTLY EARLIER games
    sg = raw["snaps"].copy(); sg["team"] = _norm(sg["team"].astype(str))
    own = sg.groupby(["game_id", "team"]).apply(lambda d: pd.Series({"_rot_off": float((d.offense_pct >= 0.5).sum()), "_rot_def": float((d.defense_pct >= 0.5).sum()),
                                                                    "_top5_off": float(d.offense_pct.nlargest(5).mean()) if d.offense_pct.notna().any() else np.nan}), include_groups=False).reset_index()
    t = t.merge(own, on=["game_id", "team"], how="left").sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)
    for src, dst in (("_rot_off", "snap_rot_off_pre"), ("_rot_def", "snap_rot_def_pre"), ("_top5_off", "snap_top5_off_pre")):
        t[dst] = prior_ewm(t, "team", src, HL, 3)
    t = t.drop(columns=["_rot_off", "_rot_def", "_top5_off"])
    return {"team": t}


def specs() -> list[FeatureSpec]:
    F = FeatureSpec
    return [
        F(S, "nfl.injuries_pit", "team", ["inj_out_n_pre", "inj_doubt_n_pre", "inj_quest_n_pre", "inj_qb_out_pre", "inj_out_off_snap_pre", "inj_out_def_snap_pre"], "PARTIAL",
          "players listed Out / Doubtful / Questionable by the LAST report modified at or before kickoff, a QB-out flag, and the summed prior-game offensive / defensive snap share of the players listed Out or Doubtful",
          done=["timestamped final weekly designation", "position (QB flag)", "snap-weighted impact from strictly earlier games"],
          missing=["practice-status sequences (DNP-limited-limited) and intra-week vintages: the file keeps only the last status of each player-week", "calibration of status to play probability", "2009 and 2025 have no usable timestamps (NaN)"],
          raw=["nflverse injuries", "nflverse snap_counts", "nflverse players"], pit="pregame_rolling"),
        F(S, "nfl.snaps", "team", ["snap_rot_off_pre", "snap_rot_def_pre", "snap_top5_off_pre"], "PARTIAL",
          "EWMA (half-life 8 games) over strictly earlier games of: players with >=50% offensive snap share, players with >=50% defensive snap share, mean share of the top five offensive players",
          done=["rolling snap share and rotation depth"], missing=["split by down / distance / score state", "participation-based role separation", "expected snaps given game script and injury"],
          raw=["nflverse snap_counts"], pit="pregame_rolling"),
    ]
