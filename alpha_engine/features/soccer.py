"""Soccer feature builders from football-data.co.uk league files (E0, D1, F1, I1, SP1; 2015-16 onward). One row per TEAM-match; all *_pre columns use strictly earlier matches (RESEARCH_ONLY).
Odds columns in the files are never read. Not in this raw data: xG, lineups, injuries, weather, formations, VAR, added time, player data."""
from __future__ import annotations

import glob

import numpy as np
import pandas as pd

from .core import FeatureSpec, Paths, pair_rows, prior_count, prior_date_mean, prior_ewm

S = "SOCCER"
COLS = ["Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "HTHG", "HTAG", "HS", "AS", "HST", "AST", "HF", "AF", "HC", "AC", "HY", "AY", "HR", "AR", "Referee"]


def load_raw(p: Paths) -> pd.DataFrame:
    out = []
    for f in sorted(glob.glob(str(p.soccer / "*_*.csv"))):
        d = pd.read_csv(f, encoding="utf-8-sig", on_bad_lines="skip")
        d = d[[c for c in COLS if c in d.columns]].dropna(subset=["HomeTeam", "FTHG"])
        d["season_code"] = f.rsplit("_", 1)[1][:-4]
        out.append(d)
    return pd.concat(out, ignore_index=True)


def compute(raw: pd.DataFrame) -> dict:
    d = raw.copy()
    d["date"] = pd.to_datetime(d.Date, format="mixed", dayfirst=True, errors="coerce")
    d = d.dropna(subset=["date"]).sort_values(["date", "Div", "HomeTeam"], kind="mergesort").reset_index(drop=True)
    d["game_id"] = d.index
    rows = []
    for side, o, home in (("H", "A", 1), ("A", "H", 0)):
        t = pd.DataFrame({"game_id": d.game_id, "date": d.date, "div": d.Div, "season": d.season_code, "team": d[f"{'Home' if side == 'H' else 'Away'}Team"], "opp_name": d[f"{'Away' if side == 'H' else 'Home'}Team"], "home": home, "referee": d.get("Referee"),
                          "gf": d[f"FT{side}G"], "ga": d[f"FT{o}G"], "ht_gf": d.get(f"HT{side}G"), "ht_ga": d.get(f"HT{o}G"), "shots": d[f"{side[0]}S"] if f"{side}S" in d else np.nan, "shots_a": d[f"{o}S"] if f"{o}S" in d else np.nan})
        for k, n in (("ST", "sot"), ("F", "fouls"), ("C", "corners"), ("Y", "yel"), ("R", "red")):
            t[n] = d.get(f"{side}{k}"); t[n + "_a"] = d.get(f"{o}{k}")
        rows.append(t)
    t = pd.concat(rows, ignore_index=True).sort_values(["date", "game_id", "home"], ascending=[True, True, False], kind="mergesort").reset_index(drop=True)
    t["pts"] = np.select([t.gf > t.ga, t.gf == t.ga], [3.0, 1.0], 0.0); t["win"] = (t.gf > t.ga).astype(float); t["draw"] = (t.gf == t.ga).astype(float)
    t["cards"] = t.yel + 2 * t.red; t["cards_a"] = t.yel_a + 2 * t.red_a; t["gd"] = t.gf - t.ga
    t["total_goals"] = t.gf + t.ga; t["btts"] = ((t.gf > 0) & (t.ga > 0)).astype(float); t["over25"] = (t.total_goals > 2.5).astype(float)
    t["ht_share"] = (t.ht_gf + t.ht_ga) / t.total_goals.replace(0, np.nan); t["late_gf"] = t.gf - t.ht_gf; t["late_ga"] = t.ga - t.ht_ga
    t["sot_conv"] = t.gf / t.sot.replace(0, np.nan); t["sot_save"] = 1 - t.ga / t.sot_a.replace(0, np.nan); t["shot_acc"] = t.sot / t.shots.replace(0, np.nan)
    t["fouls_per_card"] = t.cards / t.fouls.replace(0, np.nan)
    stats = ["gf", "ga", "shots", "shots_a", "sot", "sot_a", "corners", "corners_a", "fouls", "fouls_a", "cards", "cards_a", "pts", "win", "draw", "total_goals", "btts", "over25", "ht_share", "late_gf", "late_ga", "sot_conv", "sot_save", "shot_acc", "red", "gd"]
    for c in stats:
        t[f"{c}_pre"] = prior_ewm(t, "team", c, hl=8, min_periods=3)
    for c in ("gf", "ga", "total_goals"):
        t[f"{c}_homeaway_pre"] = prior_ewm(t, ["team", "home"], c, hl=8, min_periods=3)
    t["n_pre"] = prior_count(t, "team"); t["rest"] = t.groupby("team", sort=False)["date"].transform(lambda s: (s - s.shift(1)).dt.days).clip(upper=21)
    t["matches_14d_pre"] = 0.0
    for _, idx in t.groupby("team", sort=False).groups.items():
        dd = t.loc[idx, "date"].to_numpy("datetime64[D]"); lo = np.searchsorted(dd, dd - np.timedelta64(14, "D"), side="left"); t.loc[idx, "matches_14d_pre"] = np.arange(len(dd)) - lo
    t["points_season_pre"] = t.groupby(["team", "season"], sort=False)["pts"].transform(lambda s: s.shift(1).fillna(0).cumsum())
    t["games_season_pre"] = t.groupby(["team", "season"], sort=False).cumcount()
    t["ppg_season_pre"] = t.points_season_pre / t.games_season_pre.replace(0, np.nan)
    t["games_left_pre"] = t.groupby(["team", "season"], sort=False)["game_id"].transform("count") - t.games_season_pre
    # league baselines from strictly earlier dates, per division
    for c in ("gf", "total_goals", "corners", "cards", "fouls", "shots"):
        t[f"lg_{c}_pre"] = np.nan
    for dv, idx in t.groupby("div").groups.items():
        sub = t.loc[idx]
        for c in ("gf", "total_goals", "corners", "cards", "fouls", "shots"):
            t.loc[idx, f"lg_{c}_pre"] = prior_date_mean(sub, "date", c)
    t["home_adv_pre"] = t.groupby("div")["gd"].transform(lambda s: s.where(t.loc[s.index, "home"] == 1).shift(1).expanding(min_periods=50).mean()) if False else np.nan
    t = pair_rows(t, game="game_id", team="team", cols=["gf_pre", "ga_pre", "shots_pre", "shots_a_pre", "sot_pre", "sot_a_pre", "corners_pre", "corners_a_pre", "fouls_pre", "fouls_a_pre", "cards_pre", "cards_a_pre", "draw_pre", "total_goals_pre", "n_pre", "ppg_season_pre", "over25_pre", "btts_pre"])
    t["exp_gf_pre"] = t.lg_gf_pre * (t.gf_pre / t.lg_gf_pre) * (t.opp_ga_pre / t.lg_gf_pre)
    t["exp_total_goals_pre"] = t.exp_gf_pre + t.opp_gf_pre * (t.ga_pre / t.lg_gf_pre) * (t.lg_gf_pre / t.lg_gf_pre) * 0 + (t.lg_gf_pre * (t.opp_gf_pre / t.lg_gf_pre) * (t.ga_pre / t.lg_gf_pre))
    t["exp_corners_pre"] = t.corners_pre + t.opp_corners_a_pre - t.lg_corners_pre / 2
    t["exp_cards_pre"] = t.cards_pre + t.opp_cards_a_pre - t.lg_cards_pre / 2
    t["exp_fouls_pre"] = t.fouls_pre + t.opp_fouls_a_pre - t.lg_fouls_pre / 2
    t["exp_shots_pre"] = t.shots_pre + t.opp_shots_a_pre - t.lg_shots_pre / 2
    t["draw_prop_pre"] = (t.draw_pre + t.opp_draw_pre) / 2
    t["open_game_pre"] = (t.total_goals_pre + t.opp_total_goals_pre) / 2
    t["rating_gap_pre"] = (t.gf_pre - t.ga_pre) - (t.opp_gf_pre - t.opp_ga_pre)
    t["ppg_gap_pre"] = t.ppg_season_pre - t.opp_ppg_season_pre
    # referee: EWMA of cards/fouls per match he officiated before (E0 files only carry referee names)
    r = t[t.home == 1].dropna(subset=["referee"]).copy()
    r["match_cards"] = r.cards + r.cards_a; r["match_fouls"] = r.fouls + r.fouls_a
    for c in ("match_cards", "match_fouls"):
        r[f"ref_{c}_pre"] = prior_ewm(r, "referee", c, hl=20, min_periods=5)
    t = t.merge(r[["game_id", "ref_match_cards_pre", "ref_match_fouls_pre"]], on="game_id", how="left")
    return {"team": t}


def specs() -> list[FeatureSpec]:
    F = lambda cid, cols, lvl, d, done=(), miss=(), pit="pregame_rolling": FeatureSpec(S, cid, "team", list(cols), lvl, d, list(done), list(miss), ["football-data.co.uk league files"], pit)
    return [
        F("soc.goal_dist", ["exp_gf_pre", "exp_total_goals_pre", "gf_pre", "ga_pre", "total_goals_pre"], "PARTIAL", "attack/defence-adjusted expected goals from goals scored and conceded vs league mean, per team and for the match", ["goal rates", "opponent adjustment"], ["Poisson/Dixon-Coles fit"]),
        F("soc.ratings", ["rating_gap_pre", "gf_pre", "ga_pre", "pts_pre", "ppg_season_pre"], "PARTIAL", "EWMA goal difference gap and points per game", ["goal-difference rating"], ["Elo/Bradley-Terry with cross-league links"]),
        F("soc.xg", ["shots_pre", "sot_pre", "shots_a_pre", "sot_a_pre"], "PROXY", "EWMA shots and shots on target for/against stand in for xG", [], ["shot location/quality (xG)"]),
        F("soc.shots", ["shots_pre", "shots_a_pre", "exp_shots_pre", "sot_pre", "shot_acc_pre"], "FULL", "EWMA shots/shots on target for and against, and the matchup expectation"),
        F("soc.corners", ["corners_pre", "corners_a_pre", "exp_corners_pre"], "FULL", "EWMA corners for/against and the opponent-adjusted expected corners"),
        F("soc.fouls_cards", ["fouls_pre", "cards_pre", "cards_a_pre", "exp_cards_pre", "exp_fouls_pre", "red_pre"], "FULL", "EWMA fouls and card points (yellow=1, red=2) for/against and matchup expectations"),
        F("soc.referee", ["ref_match_cards_pre", "ref_match_fouls_pre"], "PARTIAL", "referee's EWMA cards and fouls per match from earlier matches (E0 only; other leagues have no referee column)", ["EPL referee tendencies"], ["referees outside the EPL"]),
        F("soc.rest_travel", ["rest", "matches_14d_pre"], "PARTIAL", "days of rest and matches in the previous 14 days in the league only", ["league rest"], ["cup/European matches, travel distance"]),
        F("soc.congestion_load", ["matches_14d_pre", "rest"], "PARTIAL", "matches in 14 days in the league only", ["league congestion"], ["cups and European competition"]),
        F("soc.home_advantage", ["home", "gf_homeaway_pre", "ga_homeaway_pre"], "FULL", "venue flag and venue-specific EWMA goals for/against"),
        F("soc.draw_propensity", ["draw_prop_pre", "draw_pre"], "FULL", "EWMA draw frequency of each side and their mean"),
        F("soc.open_game_index", ["open_game_pre", "over25_pre", "btts_pre"], "FULL", "mean EWMA total goals, over-2.5 and both-teams-scored frequencies of the two sides"),
        F("soc.period_split", ["ht_share_pre", "late_gf_pre", "late_ga_pre"], "PARTIAL", "EWMA first-half share of goals and second-half goals for/against", ["half split"], ["goal-minute timing"]),
        F("soc.finishing_regression", ["sot_conv_pre", "shot_acc_pre"], "PROXY", "goals per shot on target and shot accuracy; no xG baseline", [], ["xG-based finishing luck"]),
        F("soc.keeper_shot_stopping_regression", ["sot_save_pre"], "PROXY", "EWMA share of shots on target saved by the team, not keeper-specific and not post-shot xG", [], ["keeper identity and PSxG"]),
        F("soc.motivation", ["games_left_pre", "ppg_season_pre"], "PARTIAL", "season points per game and games left", ["season progress"], ["table position stakes (relegation/title/Europe)"]),
        F("soc.stakes_leverage", ["games_left_pre", "ppg_gap_pre"], "PARTIAL", "games left and points-per-game gap to the opponent", ["season progress"], ["stakes derived from the table"]),
        F("soc.league_baseline_environment", ["lg_gf_pre", "lg_total_goals_pre", "lg_corners_pre", "lg_cards_pre"], "FULL", "league mean goals, corners and cards from strictly earlier dates in that division"),
        F("soc.ratings_uncertainty", ["n_pre"], "PARTIAL", "number of earlier matches", ["sample size"], ["rating deviation"]),
        F("soc.paired_team_correlation", ["open_game_pre", "rating_gap_pre"], "PARTIAL", "pair-level features that drive co-movement of two teams' goals", ["pair features"], ["fitted correlation parameter"]),
        F("soc.points_total_distribution", ["ppg_season_pre", "points_season_pre", "games_left_pre"], "PARTIAL", "points to date, points per game and games remaining", ["season-to-date state"], ["simulation of the remaining schedule"]),
    ]
