"""NFL participation-based team builders (RESEARCH_ONLY): offensive personnel/formation mix, defensive coverage shell, box counts, pressure and goal-line personnel, from nflverse pbp_participation joined to nflverse pbp (seasons 2016+).

Every input is PARTIAL (see each spec's `missing`): the catalog definitions also ask for opponent adjustment, EPA splits, FTN charting (motion / play action; not implemented here), injury weighting and shrinkage models.
Implemented: EWMA (half-life 8 team games, min 3 observations) of per-game shares computed from STRICTLY EARLIER games only (core.prior_ewm shifts by one game per team).
Play universe: usable pbp plays (not deleted/aborted, posteam known), scrimmage plays = pass attempt, rush attempt, sack or scramble, excluding kneels and spikes; dropbacks = qb_dropback==1; designed rushes = rush_attempt==1 and qb_scramble==0.
Participation columns are joined on (game_id, play_id). A share is NaN (not 0) when the game has no plays with the needed participation field non-null (participation coverage varies by season: formation/coverage fields are ~72-80% present).
No EPA / win-probability columns are used. Games before 2016 are outside the universe (no participation data).
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec, prior_ewm
from .nfl_ext import _norm, _team_games

S = "NFL"
HL = 8.0
FIRST = 2016
PBP_COLS = ["game_id", "play_id", "posteam", "defteam", "yardline_100", "yards_gained", "pass_attempt", "rush_attempt", "sack", "qb_dropback", "qb_scramble", "qb_kneel", "qb_spike", "play_deleted", "aborted_play"]
PART_COLS = ["nflverse_game_id", "play_id", "offense_formation", "offense_personnel", "defenders_in_box", "number_of_pass_rushers", "was_pressure", "defense_man_zone_type", "defense_coverage_type"]
SCR_PBP = [c for c in PBP_COLS if c not in ("game_id", "play_id", "posteam", "defteam")]
SCR_PART = [c for c in PART_COLS if c not in ("nflverse_game_id", "play_id")]
SINGLE_HIGH, TWO_HIGH, ZERO = ("COVER_1", "COVER_3"), ("COVER_2", "COVER_4", "COVER_6", "2_MAN"), ("COVER_0",)


def load_raw(pbp_dir, part_dir, games_file) -> dict:
    fs = [f for f in sorted(glob.glob(str(Path(pbp_dir) / "pbp_*.parquet"))) if int(Path(f).stem.split("_")[1]) >= FIRST]
    pbp = pd.concat([pd.read_parquet(f, columns=PBP_COLS) for f in fs], ignore_index=True)
    part = pd.concat([pd.read_parquet(f, columns=PART_COLS) for f in sorted(glob.glob(str(Path(part_dir) / "p*.parquet")))], ignore_index=True)
    games = pd.read_csv(games_file, usecols=["game_id", "season", "week", "game_type", "gameday", "gametime", "home_team", "away_team", "home_score"])
    return {"pbp": pbp, "part": part, "games": games[games.season >= FIRST]}


def _num(d, c):
    return pd.to_numeric(d[c], errors="coerce") if c in d else pd.Series(np.nan, index=d.index)


def _count(pers: pd.Series, pos: str) -> pd.Series:
    return pd.to_numeric(pers.astype(str).str.extract(rf"(\d+) {pos}\b")[0], errors="coerce").where(pers.notna())


def _plays(raw: dict) -> pd.DataFrame:
    p = raw["pbp"].copy()
    for c in ("pass_attempt", "rush_attempt", "sack", "qb_dropback", "qb_scramble", "qb_kneel", "qb_spike"):
        p[c] = _num(p, c).fillna(0.0)
    for c in ("yardline_100", "yards_gained", "play_id"):
        p[c] = _num(p, c)
    p["posteam"] = _norm(p.posteam.astype(str)).where(p.posteam.notna()); p["defteam"] = _norm(p.defteam.astype(str)).where(p.defteam.notna())
    p = p[~((_num(p, "play_deleted").fillna(0) == 1) | (_num(p, "aborted_play").fillna(0) == 1)) & p.posteam.notna() & p.defteam.notna()]
    p = p[((p.pass_attempt == 1) | (p.rush_attempt == 1) | (p.sack == 1) | (p.qb_scramble == 1)) & (p.qb_kneel == 0) & (p.qb_spike == 0)]
    q = raw["part"].rename(columns={"nflverse_game_id": "game_id"}).copy(); q["play_id"] = _num(q, "play_id")
    q = q.drop_duplicates(["game_id", "play_id"])
    p = p.merge(q, on=["game_id", "play_id"], how="left")
    rb, te = _count(p.offense_personnel, "RB"), _count(p.offense_personnel, "TE")
    p["rb"], p["te"] = rb, te
    cov = p.defense_coverage_type
    p["cov_ok"] = cov.isin(SINGLE_HIGH + TWO_HIGH + ZERO)
    p["box"] = _num(p, "defenders_in_box"); p["rushers"] = _num(p, "number_of_pass_rushers")
    p["press"] = p.was_pressure.map({True: 1.0, False: 0.0, "True": 1.0, "False": 0.0, 1: 1.0, 0: 0.0, 1.0: 1.0, 0.0: 0.0})
    return p


def _mean(sub: pd.DataFrame, key, val: pd.Series) -> pd.Series:
    return val.groupby([sub.game_id, sub[key]]).mean()


def _per_game(p: pd.DataFrame) -> pd.DataFrame:
    out: dict = {}; o = ["game_id", "posteam"]
    pt = p[p.rb.notna() & p.te.notna()]
    for rbn, ten in ((1, 1), (1, 2), (1, 3), (2, 1), (2, 2)):
        out[f"p{rbn}{ten}"] = _mean(pt, "posteam", ((pt.rb == rbn) & (pt.te == ten)).astype(float))
    pf = p[p.offense_formation.notna()]
    out["gun"] = _mean(pf, "posteam", pf.offense_formation.isin(["SHOTGUN", "PISTOL", "EMPTY"]).astype(float)); out["empty"] = _mean(pf, "posteam", (pf.offense_formation == "EMPTY").astype(float))
    db = p[p.qb_dropback == 1]; dd = "defteam"
    mz = db[db.defense_man_zone_type.isin(["MAN_COVERAGE", "ZONE_COVERAGE"])]; out["man"] = _mean(mz, dd, (mz.defense_man_zone_type == "MAN_COVERAGE").astype(float))
    cv = db[db.cov_ok]
    out["single_high"] = _mean(cv, dd, cv.defense_coverage_type.isin(SINGLE_HIGH).astype(float)); out["two_high"] = _mean(cv, dd, cv.defense_coverage_type.isin(TWO_HIGH).astype(float)); out["cover0"] = _mean(cv, dd, cv.defense_coverage_type.isin(ZERO).astype(float))
    bl = db[db.rushers.notna()]; out["blitz"] = _mean(bl, dd, (bl.rushers >= 5).astype(float))
    pr = db[db.press.notna()]; out["pressure"] = _mean(pr, dd, pr.press)
    out["def_sack"] = _mean(db, dd, (db.sack == 1).astype(float))
    rs = p[(p.rush_attempt == 1) & (p.qb_scramble == 0)]; bx = rs[rs.box.notna()]
    out["box8"] = _mean(bx, dd, (bx.box >= 8).astype(float)); out["box6"] = _mean(bx, dd, (bx.box <= 6).astype(float)); out["box_mean"] = _mean(bx, dd, bx.box)
    out["stuff"] = _mean(rs[rs.yards_gained.notna()], dd, (rs[rs.yards_gained.notna()].yards_gained <= 0).astype(float))
    gl = p[p.yardline_100 <= 5]; out["gl_n"] = gl.groupby(o).size(); out["gl_run"] = _mean(gl, "posteam", (gl.rush_attempt == 1).astype(float))
    gh = gl[gl.rb.notna() & gl.te.notna()]; out["gl_heavy"] = _mean(gh, "posteam", ((gh.rb >= 2) | (gh.te >= 2)).astype(float))
    df = pd.DataFrame(out); df.index.names = ["game_id", "team"]
    return df.reset_index()


def compute(raw: dict) -> dict:
    tg = _team_games(raw["games"]); p = _plays(raw)
    pg = _per_game(p)
    t = tg.merge(pg, on=["game_id", "team"], how="left").sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)
    has = t.game_id.isin(set(p.game_id))
    t["gl_n"] = np.where(has, t["gl_n"].fillna(0.0), np.nan)           # no usable pbp rows for the game: NaN, never zero
    out = t[["game_id", "season", "week", "team", "opp", "date"]].copy()
    for c in ["p11", "p12", "p13", "p21", "p22", "gun", "empty", "man", "single_high", "two_high", "cover0", "blitz", "pressure", "def_sack", "box8", "box6", "box_mean", "stuff", "gl_n", "gl_run", "gl_heavy"]:
        out[c + "_pre"] = prior_ewm(t, "team", c, hl=HL, min_periods=3)
    return {"team": out.reset_index(drop=True)}


def specs() -> list[FeatureSpec]:
    def F(cid, cols, d, done, miss):
        return FeatureSpec(S, cid, "team", [c + "_pre" for c in cols], "PARTIAL", d, done, miss, ["nflverse pbp_participation (CC BY 4.0 repo licence; 2016+)", "nflverse pbp (play structure columns only)", "nflverse schedule"], "pregame_rolling")
    return [
        F("nfl.formation", ["p11", "p12", "p13", "p21", "p22", "gun", "empty"],
          "EWMA (half-life 8) of the share of the team's scrimmage plays with 11 / 12 / 13 / 21 / 22 personnel (RBs and TEs of offense_personnel) and with shotgun-family (SHOTGUN, PISTOL, EMPTY) and EMPTY formations, over plays with the field present",
          ["personnel and formation shares (participation 2016+)"], ["motion, play-action, screen and RPO rates (FTN 2022+, not implemented)", "performance by formation", "join with defensive personnel (nickel/dime) to estimate game formation mix"]),
        F("nfl.coverage_scheme", ["man", "single_high", "two_high", "cover0", "blitz"],
          "EWMA (half-life 8) of the defence's per-game share of dropbacks facing man coverage (among man/zone coded), single-high (COVER_1/3), two-high (COVER_2/4/6/2_MAN) and COVER_0 shells (among those coded), and 5+ pass rushers",
          ["man/zone rate", "single-high/two-high shell rates", "blitz rate (5+ rushers)"], ["split by down and distance", "FTN blitz charting", "offence EPA/target distribution versus man/zone", "small-sample shrinkage"]),
        F("nfl.run_defense", ["box8", "box6", "box_mean", "stuff"],
          "EWMA (half-life 8) of the defence's per-game share of designed rushes faced with 8+ and with <=6 defenders in the box, mean box count, and stuff rate (rush yards <= 0)",
          ["box-count rates", "stuff rate"], ["rush EPA allowed", "yards before contact", "opponent adjustment", "injury weighting of DL/LB via snap shares", "expected rushes from script"]),
        F("nfl.pass_rush", ["pressure", "def_sack"],
          "EWMA (half-life 8) of the defence's per-game pressure rate (participation was_pressure) and sack rate per dropback",
          ["team pressure rate", "sack rate per dropback"], ["blitz-adjusted pressure", "opponent OL adjustment", "player-level pressures (PFR)", "pressure-to-sack conversion with shrinkage"]),
        F("nfl.goal_line_personnel", ["gl_n", "gl_run", "gl_heavy"],
          "EWMA (half-life 8) of the team's per-game count of scrimmage plays at yardline_100 <= 5, their run share, and the share run from heavy personnel (2+ RB or 2+ TE)",
          ["inside-5 play count, run share, heavy-personnel share"], ["player shares of carries/targets/sneaks", "TE/FB TD share", "shrinkage k=8 snaps to team-level rates", "20-game window", "zero-fill flags for new players"]),
    ]
