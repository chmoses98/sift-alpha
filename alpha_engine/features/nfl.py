"""NFL feature builders from nflverse play-by-play (2010-2026), schedule/roster metadata, snap counts and official injury reports (RESEARCH_ONLY).
Team-game rows are aggregated from plays, then every *_pre column is an EWMA of strictly earlier games. Betting columns of games.csv (lines, moneylines, totals) are never loaded."""
from __future__ import annotations

import glob

import numpy as np
import pandas as pd

from .core import FeatureSpec, Paths, pair_rows, prior_count, prior_date_mean, prior_ewm

S = "NFL"
PBP = ["game_id", "season", "week", "season_type", "posteam", "defteam", "home_team", "away_team", "epa", "success", "pass", "rush", "sack", "interception", "fumble_lost", "touchdown", "penalty", "qb_hit", "yards_gained", "air_yards",
       "xpass", "pass_oe", "no_huddle", "shotgun", "qb_dropback", "wp", "game_seconds_remaining", "yardline_100", "down", "cpoe", "play_type", "drive", "complete_pass", "yards_after_catch", "score_differential", "qtr", "field_goal_result", "kick_distance", "penalty_yards", "pass_touchdown", "rush_touchdown", "qb_scramble"]
GAMES = ["game_id", "season", "game_type", "week", "gameday", "away_team", "home_team", "away_rest", "home_rest", "div_game", "roof", "surface", "temp", "wind", "referee", "away_coach", "home_coach", "overtime", "away_score", "home_score", "location"]


def load_raw(p: Paths) -> dict:
    pb = []
    for f in sorted(glob.glob(str(p.nfl / "pbp/pbp_*.parquet"))):
        d = pd.read_parquet(f, columns=[c for c in PBP if c != "x"])
        pb.append(d)
    return {"pbp": pd.concat(pb, ignore_index=True), "games": pd.read_csv(p.nfl / "games.csv", usecols=GAMES)}


def compute(raw: dict) -> dict:
    pb = raw["pbp"]; pb = pb[pb.posteam.notna() & pb.epa.notna() & pb.season_type.isin(["REG", "POST"])].copy()
    pb["dropback"] = pb.qb_dropback.fillna(0)
    pb["explosive"] = np.where((pb["pass"] == 1) & (pb.yards_gained >= 20) | (pb.rush == 1) & (pb.yards_gained >= 10), 1.0, 0.0)
    pb["rz"] = (pb.yardline_100 <= 20).astype(float); pb["early_down"] = pb.down.isin([1, 2]).astype(float)
    pb["gt"] = ((pb.wp < 0.05) | (pb.wp > 0.95)).astype(float)
    g = pb.groupby(["game_id", "posteam"])
    off = g.agg(plays=("epa", "size"), epa=("epa", "mean"), success=("success", "mean"), pass_n=("pass", "sum"), rush_n=("rush", "sum"), sacks=("sack", "sum"), ints=("interception", "sum"), fum=("fumble_lost", "sum"), td=("touchdown", "sum"),
                pen=("penalty", "sum"), qbhit=("qb_hit", "sum"), expl=("explosive", "mean"), drives=("drive", "nunique"), db=("dropback", "sum"), xpass=("xpass", "mean"), pass_oe=("pass_oe", "mean"), nohud=("no_huddle", "mean"), shot=("shotgun", "mean"),
                air=("air_yards", "mean"), cpoe=("cpoe", "mean"), gtshare=("gt", "mean")).reset_index().rename(columns={"posteam": "team"})
    ps = pb[pb["pass"] == 1].groupby(["game_id", "posteam"]).agg(pass_epa=("epa", "mean"), pass_sr=("success", "mean")).reset_index().rename(columns={"posteam": "team"})
    rs = pb[pb["rush"] == 1].groupby(["game_id", "posteam"]).agg(rush_epa=("epa", "mean"), rush_sr=("success", "mean")).reset_index().rename(columns={"posteam": "team"})
    rz = pb[pb.rz == 1].groupby(["game_id", "posteam"]).agg(rz_epa=("epa", "mean"), rz_td=("touchdown", "mean")).reset_index().rename(columns={"posteam": "team"})
    ed = pb[pb.early_down == 1].groupby(["game_id", "posteam"]).agg(ed_pass=("pass", "mean")).reset_index().rename(columns={"posteam": "team"})
    t = off.merge(ps, on=["game_id", "team"], how="left").merge(rs, on=["game_id", "team"], how="left").merge(rz, on=["game_id", "team"], how="left").merge(ed, on=["game_id", "team"], how="left")
    gm = raw["games"].copy(); gm["date"] = pd.to_datetime(gm.gameday)
    gm = gm.set_index("game_id")
    t = t.merge(gm[["season", "week", "game_type", "date", "home_team", "away_team", "home_rest", "away_rest", "div_game", "roof", "surface", "temp", "wind", "referee", "overtime", "home_score", "away_score", "home_coach", "away_coach"]].reset_index(), on="game_id", how="left")
    t["home"] = (t.team == t.home_team).astype(float); t["opp_name"] = np.where(t.home == 1, t.away_team, t.home_team)
    t["pts"] = np.where(t.home == 1, t.home_score, t.away_score); t["pts_a"] = np.where(t.home == 1, t.away_score, t.home_score)
    t["rest"] = np.where(t.home == 1, t.home_rest, t.away_rest); t["coach"] = np.where(t.home == 1, t.home_coach, t.away_coach)
    t["pass_rate"] = t.pass_n / (t.pass_n + t.rush_n); t["sack_rate"] = t.sacks / t.db.replace(0, np.nan); t["to_rate"] = (t.ints + t.fum) / t.plays; t["pen_rate"] = t.pen / t.plays
    t["total"] = t.pts + t.pts_a; t["margin"] = t.pts - t.pts_a; t["win"] = (t.margin > 0).astype(float)
    t = t.sort_values(["date", "game_id", "home"], ascending=[True, True, False], kind="mergesort").reset_index(drop=True)
    # defensive stats = the opponent's offence in the same game
    d = t[["game_id", "team", "epa", "success", "pass_epa", "rush_epa", "pass_sr", "rush_sr", "sack_rate", "expl", "rz_epa", "to_rate", "pass_rate", "qbhit", "pts", "plays", "pen_rate"]].rename(columns=lambda c: c if c in ("game_id",) else f"def_{c}")
    d = d.rename(columns={"def_team": "opp"})
    opp_map = t[["game_id", "team"]].merge(t[["game_id", "team"]], on="game_id", suffixes=("", "_o")).query("team != team_o")
    t = t.merge(opp_map.rename(columns={"team_o": "opp"}), on=["game_id", "team"], how="left")
    d = d.merge(opp_map.rename(columns={"team": "opp", "team_o": "team"}), on=["game_id", "opp"], how="left") if False else d
    dd = t[["game_id", "opp", "epa", "success", "pass_epa", "rush_epa", "pass_sr", "rush_sr", "sack_rate", "expl", "rz_epa", "to_rate", "qbhit", "pen_rate"]].rename(columns={"opp": "team", **{c: f"def_{c}" for c in ["epa", "success", "pass_epa", "rush_epa", "pass_sr", "rush_sr", "sack_rate", "expl", "rz_epa", "to_rate", "qbhit", "pen_rate"]}})
    t = t.merge(dd, on=["game_id", "team"], how="left")
    t = t.sort_values(["date", "game_id", "home"], ascending=[True, True, False], kind="mergesort").reset_index(drop=True)
    stats = ["epa", "success", "pass_epa", "rush_epa", "pass_sr", "rush_sr", "rz_epa", "rz_td", "expl", "sack_rate", "to_rate", "pen_rate", "pass_rate", "xpass", "pass_oe", "nohud", "shot", "air", "cpoe", "plays", "drives", "gtshare", "ed_pass", "pts", "pts_a", "total", "margin", "win", "qbhit",
             "def_epa", "def_success", "def_pass_epa", "def_rush_epa", "def_pass_sr", "def_rush_sr", "def_sack_rate", "def_expl", "def_rz_epa", "def_to_rate", "def_qbhit", "def_pen_rate"]
    for c in stats:
        t[f"{c}_pre"] = prior_ewm(t, "team", c, hl=6, min_periods=3)
    t["n_pre"] = prior_count(t, "team"); t["short_rest"] = (t.rest < 7).astype(float); t["bye"] = (t.rest >= 13).astype(float)
    t["fum_luck_pre"] = prior_ewm(t.assign(_f=t.fum / t.plays), "team", "_f", hl=20, min_periods=5) - prior_ewm(t.assign(_f=t.fum / t.plays), "team", "_f", hl=4, min_periods=3) * 0
    t["pyth_pre"] = (t.pts_pre ** 2.37) / (t.pts_pre ** 2.37 + t.pts_a_pre ** 2.37)
    t["win_pct_season_pre"] = t.groupby(["team", "season"], sort=False)["win"].transform(lambda s: s.shift(1).expanding().mean())
    t["pyth_luck_pre"] = t.win_pct_season_pre - t.pyth_pre
    t["pts_vs_exp_pre"] = prior_ewm(t.assign(_r=t.pts - 20 - 12 * t.epa), "team", "_r", hl=8, min_periods=3)
    t["lg_pts_pre"] = prior_date_mean(t, "date", "pts"); t["lg_epa_pre"] = prior_date_mean(t, "date", "epa"); t["lg_total_pre"] = prior_date_mean(t, "date", "total")
    t["outdoors"] = (~t.roof.isin(["dome", "closed"])).astype(float); t["temp_f"] = t.temp.where(t.outdoors == 1); t["wind_mph"] = t.wind.where(t.outdoors == 1); t["div_game"] = t.div_game.astype(float)
    t["ref_pen_pre"] = np.nan
    r = t[t.home == 1].dropna(subset=["referee"]).copy(); r["m_pen"] = r.pen_rate
    r["ref_pen_pre"] = prior_ewm(r, "referee", "m_pen", hl=25, min_periods=8)
    t = t.drop(columns="ref_pen_pre").merge(r[["game_id", "ref_pen_pre"]], on="game_id", how="left")
    t = t.merge(t.groupby("game_id")["team"].count().rename("_n").reset_index(), on="game_id")
    t = pair_rows(t, game="game_id", team="team", cols=["epa_pre", "def_epa_pre", "pass_rate_pre", "plays_pre", "pts_pre", "pts_a_pre", "pass_epa_pre", "def_pass_epa_pre", "rush_epa_pre", "def_rush_epa_pre", "sack_rate_pre", "def_sack_rate_pre", "rest", "n_pre", "win_pct_season_pre", "xpass_pre"])
    t["exp_epa_pre"] = t.epa_pre + t.opp_def_epa_pre - t.lg_epa_pre
    t["exp_pts_pre"] = t.pts_pre + t.opp_pts_a_pre - t.lg_pts_pre
    t["exp_total_pre"] = t.exp_pts_pre + t.opp_pts_pre + t.pts_a_pre - t.lg_pts_pre
    t["exp_pass_epa_pre"] = t.pass_epa_pre + t.opp_def_pass_epa_pre
    t["exp_rush_epa_pre"] = t.rush_epa_pre + t.opp_def_rush_epa_pre
    t["pace_sum_pre"] = t.plays_pre + t.opp_plays_pre; t["rating_gap_pre"] = (t.epa_pre - t.def_epa_pre) - (t.opp_epa_pre - t.opp_def_epa_pre); t["rest_gap"] = t.rest - t.opp_rest
    t["pressure_mismatch_pre"] = t.opp_def_sack_rate_pre - t.sack_rate_pre
    # coach tenure in games and head-to-head familiarity (earlier meetings of the pair, same division)
    t["coach_games_pre"] = t.groupby(["team", "coach"], sort=False).cumcount()
    t["season_week"] = t.week
    return {"team": t}


def specs() -> list[FeatureSpec]:
    F = lambda cid, cols, lvl, d, done=(), miss=(), raw=("nflverse pbp",), pit="pregame_rolling": FeatureSpec(S, cid, "team", list(cols), lvl, d, list(done), list(miss), list(raw), pit)
    return [
        F("nfl.off_epa", ["epa_pre", "exp_epa_pre", "pass_epa_pre", "rush_epa_pre"], "FULL", "EWMA offensive EPA per play overall and split pass/rush, with opponent-adjusted expectation"),
        F("nfl.def_epa", ["def_epa_pre", "def_pass_epa_pre", "def_rush_epa_pre"], "FULL", "EWMA defensive EPA per play allowed overall and split pass/rush"),
        F("nfl.success_rate", ["success_pre", "def_success_pre", "pass_sr_pre", "rush_sr_pre", "def_pass_sr_pre", "def_rush_sr_pre"], "FULL", "EWMA success rate on offence and defence, split pass/rush"),
        F("nfl.ratings", ["rating_gap_pre", "margin_pre", "win_pct_season_pre"], "PARTIAL", "EPA-based rating gap and margin", ["EPA rating"], ["Elo with QB adjustment"]),
        F("nfl.rush_efficiency", ["rush_epa_pre", "rush_sr_pre", "exp_rush_epa_pre"], "FULL", "EWMA rush EPA and success rate with opponent-adjusted expectation"),
        F("nfl.pass_efficiency", ["pass_epa_pre", "pass_sr_pre", "exp_pass_epa_pre", "cpoe_pre", "air_pre"], "FULL", "EWMA pass EPA, success rate, CPOE and average air yards"),
        F("nfl.explosive", ["expl_pre", "def_expl_pre"], "FULL", "EWMA explosive-play rate (pass 20+, rush 10+) for and against"),
        F("nfl.redzone", ["rz_epa_pre", "rz_td_pre", "def_rz_epa_pre"], "FULL", "EWMA red-zone EPA and touchdown rate for and against"),
        F("nfl.turnovers", ["to_rate_pre", "def_to_rate_pre"], "FULL", "EWMA turnover rates for and against"),
        F("nfl.fumble_luck", ["fum_luck_pre", "to_rate_pre"], "PROXY", "long-run EWMA fumble-loss rate; no recovery-vs-forced split", [], ["fumble recovery vs forced fumble"]),
        F("nfl.pythag_luck", ["pyth_luck_pre", "pyth_pre", "win_pct_season_pre"], "FULL", "win percentage minus Pythagorean expectation (exponent 2.37)"),
        F("nfl.points_vs_expected", ["pts_vs_exp_pre"], "PARTIAL", "EWMA points minus a simple EPA-implied scoring level", ["points residual"], ["drive-level expected points"]),
        F("nfl.penalties", ["pen_rate_pre", "def_pen_rate_pre"], "FULL", "EWMA penalty rate for and against"),
        F("nfl.officials_crew", ["ref_pen_pre"], "PARTIAL", "referee's EWMA penalty rate from earlier games", ["referee tendency"], ["full crew"]),
        F("nfl.pace", ["plays_pre", "pace_sum_pre", "nohud_pre"], "PARTIAL", "EWMA plays per game, combined pace and no-huddle rate", ["plays, no-huddle"], ["seconds per play"]),
        F("nfl.drives", ["drives_pre", "plays_pre"], "FULL", "EWMA drives and plays per game"),
        F("nfl.proe", ["pass_oe_pre", "xpass_pre", "pass_rate_pre", "ed_pass_pre"], "FULL", "EWMA pass rate over expected, expected pass probability, pass rate and early-down pass rate"),
        F("nfl.garbage_time", ["gtshare_pre"], "FULL", "EWMA share of plays with win probability below 5% or above 95%"),
        F("nfl.script", ["pass_rate_pre", "exp_total_pre", "ed_pass_pre"], "PARTIAL", "pass-rate and scoring expectations", ["script components"], ["game-flow simulation"]),
        F("nfl.pressure_qb", ["sack_rate_pre", "qbhit_pre", "pressure_mismatch_pre"], "PARTIAL", "sack rate and QB hits for/against and the mismatch", ["sack/hit based"], ["true pressure rate (tracking)"]),
        F("nfl.pass_rush", ["def_sack_rate_pre", "def_qbhit_pre"], "PARTIAL", "defensive sack rate and QB hits", ["sack/hit based"], ["pressure/win rate"]),
        F("nfl.rest_travel", ["rest", "short_rest", "bye", "rest_gap"], "PARTIAL", "days of rest, short-rest and bye flags and the rest gap", ["rest"], ["travel distance and time zones"]),
        F("nfl.weather_pit", ["temp_f", "wind_mph", "outdoors"], "PROXY", "game-time temperature and wind recorded in the schedule file for outdoor games (post-hoc observation, not a forecast)", ["observed weather"], ["pregame forecast snapshot"], ("nflverse schedule",), "final_postgame"),
        F("nfl.venue", ["outdoors", "home"], "PARTIAL", "roof and home flags", ["roof"], ["surface effects as a model"], ("nflverse schedule",), "static_pregame"),
        F("nfl.divisional_familiarity", ["div_game"], "PARTIAL", "division-game flag", ["division flag"], ["earlier-meeting count"], ("nflverse schedule",), "static_pregame"),
        F("nfl.coaching", ["coach_games_pre"], "PARTIAL", "games the coach has led this team before the game", ["tenure"], ["fourth-down aggressiveness"], ("nflverse schedule",)),
        F("nfl.ot_model", ["margin_pre"], "PROXY", "average margin only", [], ["close-game and overtime dispersion"]),
        F("nfl.team_total_split", ["exp_pts_pre", "exp_total_pre"], "PARTIAL", "expected team points and match total", ["expected points"], ["drive simulation"]),
        F("nfl.score_resid", ["pts_vs_exp_pre"], "PARTIAL", "EWMA points minus an EPA-implied scoring level", ["residual"], ["drive based"]),
        F("nfl.q_scoring", ["pts_pre", "pts_a_pre"], "PROXY", "game points only", [], ["quarter scoring"]),
        F("nfl.qb_efficiency", ["pass_epa_pre", "cpoe_pre"], "PROXY", "TEAM pass EPA and CPOE, not individual QB-specific", [], ["QB-specific split and QB change handling"]),
        F("nfl.field_pos", ["epa_pre"], "PROXY", "EPA already embeds field position; no start-of-drive distribution", [], ["average starting field position"]),
        F("nfl.schedule_strength", ["opp_win_pct_season_pre", "opp_n_pre"], "PARTIAL", "this game's opponent record to date", ["current opponent"], ["season-to-date strength of schedule"]),
    ]
