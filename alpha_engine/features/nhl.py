"""NHL feature builders from MoneyPuck team-game data (xG model outputs, 2008-2025), NHL API player/goalie/game rows and team strength-state seconds already in NHL-edge-finder (RESEARCH_ONLY).
MoneyPuck's xG is a public shot-quality MODEL output, not a betting-market quantity. Output tables: ``team`` (team-game, pre-game features), ``skater`` and ``goalie`` (player-game)."""
from __future__ import annotations

import glob

import numpy as np
import pandas as pd

from .core import FeatureSpec, Paths, games_in_window, opp_adjusted, pair_rows, prior_count, prior_date_mean, prior_ewm, prior_mean, rest_days

S = "NHL"


def load_raw(p: Paths) -> dict:
    h = p.raw / "nhl_hist/data/history"
    cat = lambda pat, **kw: pd.concat([pd.read_parquet(f, **kw) for f in sorted(glob.glob(str(h / pat)))], ignore_index=True)
    return {"mp": cat("moneypuck/team_games_*.parquet"), "games": cat("nhl/games_*.parquet"), "skaters": cat("players/players_*.parquet"), "goalies": cat("players/goalies_*.parquet"), "states": cat("players/team_states_*.parquet")}


def _team(raw: dict) -> pd.DataFrame:
    mp = raw["mp"]
    mp = mp[mp.game_type == 2]
    piv = {}
    for sit, cols in (("all", ["xGoalsFor", "xGoalsAgainst", "goalsFor", "goalsAgainst", "shotsOnGoalFor", "shotsOnGoalAgainst", "shotAttemptsFor", "shotAttemptsAgainst", "blockedShotAttemptsFor", "missedShotsFor",
                              "highDangerShotsFor", "highDangerShotsAgainst", "mediumDangerShotsFor", "lowDangerShotsFor", "penaltiesFor", "penaltiesAgainst", "iceTime", "hitsFor", "takeawaysFor", "giveawaysFor", "faceOffsWonFor",
                              "savedShotsOnGoalAgainst", "highDangerxGoalsFor", "highDangerxGoalsAgainst"]),
                      ("5on4", ["xGoalsFor", "goalsFor", "iceTime", "shotAttemptsFor"]), ("4on5", ["xGoalsAgainst", "goalsAgainst", "iceTime", "shotAttemptsAgainst"]), ("5on5", ["xGoalsFor", "xGoalsAgainst", "iceTime"])):
        d = mp[mp.situation == sit][["game_id", "team_id", *cols]].copy()
        d.columns = ["game_id", "team"] + [f"{c}__{sit}" for c in cols]
        piv[sit] = d
    t = mp[mp.situation == "all"][["game_id", "game_date", "team_id", "opp_team_id", "home", "season"]].rename(columns={"team_id": "team", "opp_team_id": "opp", "game_date": "date"})
    for d in piv.values():
        t = t.merge(d, on=["game_id", "team"], how="left")
    t["date"] = pd.to_datetime(t.date)
    g = raw["games"][["game_id", "home_team_id", "home_score", "away_score", "last_period_type"]]
    t = t.merge(g, on="game_id", how="left")
    t["gf"] = np.where(t.home == True, t.home_score, t.away_score); t["ga"] = np.where(t.home == True, t.away_score, t.home_score)
    t["home"] = t.home.astype(bool)
    st = raw["states"][["game_id", "team_id", "sec_en", "sec_pp", "sec_sh", "n_seconds"]].rename(columns={"team_id": "team"})
    t = t.merge(st, on=["game_id", "team"], how="left")
    return t.sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)


def _team_features(t: pd.DataFrame) -> pd.DataFrame:
    t = t.copy()
    T = lambda c: t[f"{c}__all"]
    mins = T("iceTime") / 60.0
    t["xgf60"], t["xga60"] = T("xGoalsFor") / mins * 60, T("xGoalsAgainst") / mins * 60
    t["sf60"], t["sa60"] = T("shotsOnGoalFor") / mins * 60, T("shotsOnGoalAgainst") / mins * 60
    t["cf60"], t["ca60"] = T("shotAttemptsFor") / mins * 60, T("shotAttemptsAgainst") / mins * 60
    t["pace60"] = (T("shotAttemptsFor") + T("shotAttemptsAgainst")) / mins * 60
    t["hdf60"], t["hda60"] = T("highDangerShotsFor") / mins * 60, T("highDangerShotsAgainst") / mins * 60
    t["hd_share_for"] = T("highDangerShotsFor") / T("shotsOnGoalFor"); t["hd_share_against"] = T("highDangerShotsAgainst") / T("shotsOnGoalAgainst")
    t["sh_pct"], t["sv_pct"] = t.gf / T("shotsOnGoalFor"), 1 - t.ga / T("shotsOnGoalAgainst")
    t["pdo"] = t.sh_pct + t.sv_pct
    t["block_rate"] = T("blockedShotAttemptsFor") / T("shotAttemptsFor"); t["miss_rate"] = T("missedShotsFor") / T("shotAttemptsFor"); t["sog_conv"] = T("shotsOnGoalFor") / T("shotAttemptsFor")
    t["pen_taken60"], t["pen_drawn60"] = T("penaltiesFor") / mins * 60, T("penaltiesAgainst") / mins * 60
    t["pp_xg60"] = t["xGoalsFor__5on4"] / (t["iceTime__5on4"] / 3600).replace(0, np.nan); t["pk_xga60"] = t["xGoalsAgainst__4on5"] / (t["iceTime__4on5"] / 3600).replace(0, np.nan)
    t["pp_share"] = t["iceTime__5on4"] / t["iceTime__all"]; t["pk_share"] = t["iceTime__4on5"] / t["iceTime__all"]
    t["xg5v5_diff60"] = (t["xGoalsFor__5on5"] - t["xGoalsAgainst__5on5"]) / (t["iceTime__5on5"] / 3600).replace(0, np.nan)
    t["ot"] = (t.last_period_type.isin(["OT", "SO"])).astype(float); t["so"] = (t.last_period_type == "SO").astype(float)
    t["so_win"] = np.where(t.last_period_type == "SO", (t.gf > t.ga).astype(float), np.nan)
    t["reg_tie"] = (t.last_period_type.isin(["OT", "SO"])).astype(float)
    t["goal_diff"] = t.gf - t.ga; t["total_goals"] = t.gf + t.ga
    t["en_share"] = t.sec_en / t.n_seconds
    t["won"] = (t.gf > t.ga).astype(float)
    base = ["xgf60", "xga60", "sf60", "sa60", "cf60", "ca60", "pace60", "hdf60", "hda60", "hd_share_for", "hd_share_against", "sh_pct", "sv_pct", "pdo", "block_rate", "miss_rate", "sog_conv", "pen_taken60", "pen_drawn60",
            "pp_xg60", "pk_xga60", "pp_share", "pk_share", "xg5v5_diff60", "ot", "so_win", "goal_diff", "total_goals", "en_share", "won"]
    for c in base:
        t[f"{c}_pre"] = prior_ewm(t, "team", c, hl=10)
    t["pdo_long_pre"] = prior_ewm(t, "team", "pdo", hl=40)
    t["pdo_dev_pre"] = t.pdo_pre - t.pdo_long_pre
    t["goals_var_pre"] = t.groupby("team", sort=False)["total_goals"].transform(lambda s: s.shift(1).rolling(40, min_periods=15).var())
    t = pair_rows(t, cols=["xgf60_pre", "xga60_pre", "sf60_pre", "sa60_pre", "pen_drawn60_pre", "pk_xga60_pre", "pp_xg60_pre", "goal_diff_pre"]).sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)
    t["rest_days"] = rest_days(t, "team"); t["back_to_back"] = (t.rest_days == 1).astype(float).where(t.rest_days.notna()); t["games_last7"] = games_in_window(t, "team", days=7)
    t["games_played_pre"] = prior_count(t, ["team", "season"]); t["win_pct_pre"] = prior_mean(t, ["team", "season"], "won", min_periods=1)
    # venue (rink) shot-counting bias: home-team shot attempts both teams combined at this arena (earlier games) relative to league
    hm = t[t.home].copy(); hm["venue_cf"] = hm.cf60 + hm.ca60
    hm["venue_bias_pre"] = prior_mean(hm, "team", "venue_cf", min_periods=15) - prior_date_mean(hm, "date", "venue_cf")
    t = t.merge(hm[["game_id", "team", "venue_bias_pre"]], on=["game_id", "team"], how="left")
    t["venue_bias_pre"] = t.groupby("team", sort=False)["venue_bias_pre"].ffill()
    t["rating_pre"] = 0.5 * t.goal_diff_pre + 0.5 * (t.xgf60_pre - t.xga60_pre)
    # opponent-adjusted xG rates
    t["lg_xg60_pre"] = prior_date_mean(t, "date", "xgf60")
    t["adj_xgf60"] = opp_adjusted(t, "xgf60", "opp_xga60_pre", "lg_xg60_pre"); t["adj_xga60"] = opp_adjusted(t, "xga60", "opp_xgf60_pre", "lg_xg60_pre")
    t["xgf_adj_pre"] = prior_ewm(t, "team", "adj_xgf60", hl=10); t["xga_adj_pre"] = prior_ewm(t, "team", "adj_xga60", hl=10)
    return t


def _skaters(raw: dict) -> pd.DataFrame:
    s = raw["skaters"]; s = s[s.game_type == 2].copy()
    s["date"] = pd.to_datetime(s.game_date); s = s.rename(columns={"player_id": "pid", "team_id": "team"})
    s = s[s.position != "G"].copy()
    s["toi"] = s.toi_s / 60.0
    for k in ("ev", "pp", "sh"):
        s[f"toi_{k}"] = s[f"toi_{k}_s"] / 60.0
    s["pp_toi_share"] = s.toi_pp / s.toi.where(s.toi > 0)
    s["att60"] = (s.att_ev + s.att_pp + s.att_sh) / s.toi.where(s.toi > 0) * 60; s["sog60"] = s.sog / s.toi.where(s.toi > 0) * 60
    s["att60_ev"] = s.att_ev / s.toi_ev.where(s.toi_ev > 0) * 60; s["att60_pp"] = s.att_pp / s.toi_pp.where(s.toi_pp > 0) * 60
    s["a1_60"] = s.a1 / s.toi.where(s.toi > 0) * 60; s["a2_60"] = s.a2 / s.toi.where(s.toi > 0) * 60; s["pts60"] = s.points / s.toi.where(s.toi > 0) * 60
    s["onice_sh_ev"] = s.gf_ev / s.sog_ev.where(s.sog_ev > 0)
    s["is_d"] = (s.position == "D").astype(float)
    s["en_goals"] = s.gf_en
    s = s.sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)
    for c in ("toi", "toi_ev", "toi_pp", "toi_sh", "pp_toi_share", "att60", "sog60", "att60_ev", "att60_pp", "a1_60", "a2_60", "pts60", "onice_sh_ev", "goals", "sog", "points", "pim", "shifts"):
        s[f"{c}_pre"] = prior_ewm(s, "pid", c, hl=10)
    s["toi_last3_pre"] = prior_mean(s, "pid", "toi", window=3, min_periods=2); s["toi_trend_pre"] = s.toi_last3_pre - s.toi_pre
    s["rest_days"] = rest_days(s, "pid", cap=30); s["games_pre"] = prior_count(s, "pid")
    s["toi_sd10_pre"] = s.groupby("pid", sort=False)["toi"].transform(lambda x: x.shift(1).rolling(10, min_periods=5).std())
    s["return_from_absence"] = (s.rest_days >= 10).astype(float).where(s.rest_days.notna())
    cg = s.groupby("pid", sort=False)["goals"].transform(lambda x: x.shift(1).expanding().sum()); cs = s.groupby("pid", sort=False)["sog"].transform(lambda x: x.shift(1).expanding().sum())
    lg = prior_date_mean(s.assign(_r=s.goals / s.sog.where(s.sog > 0)), "date", "_r")
    s["shpct_shrunk_pre"] = (cg.fillna(0) + 40 * lg) / (cs.fillna(0) + 40)
    s["goals_overdisp_pre"] = prior_ewm(s.assign(_s=s.goals ** 2), "pid", "_s", hl=20) - s.goals_pre ** 2
    s["sog_overdisp_pre"] = (prior_ewm(s.assign(_s=s.sog ** 2), "pid", "_s", hl=20) - s.sog_pre ** 2) / s.sog_pre.where(s.sog_pre > 0)
    return s


def _goalies(raw: dict) -> pd.DataFrame:
    g = raw["goalies"]; g = g[g.game_type == 2].copy()
    g["date"] = pd.to_datetime(g.game_date); g = g.rename(columns={"player_id": "pid", "team_id": "team"})
    g["start"] = g.starter.astype(float); g["toi"] = g.toi_s / 60.0
    g["sv"] = g.saves / g.shots_against.where(g.shots_against > 0)
    g["pulled"] = ((g.start == 1) & (g.toi < 58) & (g.toi > 0)).astype(float)
    g = g.sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)
    g["shots_faced"] = g.shots_against
    # started-games frame for rest/consecutive-start features
    st = g[g.start == 1].copy()
    st["rest_days"] = rest_days(st, "pid", cap=30)
    st["sa_last3"] = st.groupby("pid", sort=False)["shots_faced"].transform(lambda x: x.shift(1).rolling(3, min_periods=1).sum())
    for c in ("sv", "shots_faced", "pulled"):
        st[f"{c}_pre"] = prior_ewm(st, "pid", c, hl=10, min_periods=3)
    cs = st.groupby("pid", sort=False)["saves"].transform(lambda x: x.shift(1).expanding().sum()); ca = st.groupby("pid", sort=False)["shots_against"].transform(lambda x: x.shift(1).expanding().sum())
    lg = prior_date_mean(st.assign(_r=st.sv), "date", "_r")
    st["sv_shrunk_pre"] = (cs.fillna(0) + 600 * lg) / (ca.fillna(0) + 600)
    st["ev_sv_pre"] = prior_ewm(st.assign(_e=st.ev_saves / st.ev_sa.where(st.ev_sa > 0)), "pid", "_e", hl=15); st["pp_sa_share_pre"] = prior_ewm(st.assign(_e=st.pp_sa / st.shots_against.where(st.shots_against > 0)), "pid", "_e", hl=15)
    st["starts_pre"] = prior_count(st, "pid")
    return st


def _start_probability(g: pd.DataFrame, t: pd.DataFrame) -> pd.DataFrame:
    """For every team-game: the empirical probability (earlier dates only) that a team's goalie who started its previous game starts again, given the team's rest days (b2b vs not)."""
    sg = g[["game_id", "team", "pid", "date", "rest_days"]].copy()
    prev = sg.sort_values(["date", "game_id"]).groupby("team", sort=False).shift(1)
    sg["prev_pid"] = prev.pid
    sg["same"] = (sg.pid == sg.prev_pid).astype(float).where(sg.prev_pid.notna())
    sg = sg.merge(t[["game_id", "team", "back_to_back"]], on=["game_id", "team"], how="left")
    out = {}
    for b, d in sg.groupby("back_to_back"):
        a = d.groupby("date").same.agg(["sum", "count"]).sort_index(); a["cs"], a["cn"] = a["sum"].cumsum() - a["sum"], a["count"].cumsum() - a["count"]
        out[b] = (a.cs / a.cn.replace(0, np.nan)).where(a.cn >= 30)
    tt = t[["game_id", "team", "date", "back_to_back"]].copy()
    tt["p_same_goalie_pre"] = [out.get(b, pd.Series(dtype=float)).get(d, np.nan) if pd.notna(b) else np.nan for b, d in zip(tt.back_to_back, tt.date)]
    return tt[["game_id", "team", "p_same_goalie_pre"]]


def compute(raw: dict) -> dict:
    t = _team_features(_team(raw))
    g = _goalies(raw)
    g = g.merge(t[["game_id", "team", "rest_days"]].rename(columns={"rest_days": "team_rest_days"}), on=["game_id", "team"], how="left")
    t = t.merge(_start_probability(g, t), on=["game_id", "team"], how="left")
    return {"team": t, "skater": _skaters(raw), "goalie": g}


def specs() -> list[FeatureSpec]:
    F = lambda cid, tab, cols, lvl, d, done=(), miss=(), raw=("moneypuck_team_games",), pit="pregame_rolling": FeatureSpec(S, cid, tab, list(cols), lvl, d, list(done), list(miss), list(raw), pit)
    T, K, G = "team", "skater", "goalie"
    return [
        F("nhl.xg_for", T, ["xgf60_pre", "xgf_adj_pre"], "FULL", "EWMA (half-life 10) of MoneyPuck team xG for per 60, raw and opponent-adjusted", ["team xG for", "opponent adjustment"]),
        F("nhl.xg_against", T, ["xga60_pre", "xga_adj_pre"], "FULL", "same for xG against", ["team xG against"]),
        F("nhl.pace", T, ["pace60_pre", "cf60_pre", "ca60_pre"], "PARTIAL", "EWMA shot attempts for+against per 60 and each side", ["event pace"], ["score-effects adjustment"]),
        F("nhl.special_teams", T, ["pp_xg60_pre", "pk_xga60_pre", "pp_share_pre", "pk_share_pre"], "FULL", "EWMA power-play xG for per 60 on 5v4, penalty-kill xG against per 60 on 4v5, and the share of ice time spent on each", ["PP efficiency", "PK efficiency", "time on each"]),
        F("nhl.shots_against", T, ["sa60_pre", "hd_share_against_pre", "hda60_pre"], "PARTIAL", "EWMA shots on goal against per 60, high-danger share and high-danger shots against per 60", ["volume and quality against"], ["score-effects adjustment"]),
        F("nhl.opp_supp", T, ["opp_xga60_pre", "opp_sa60_pre"], "PARTIAL", "the opponent's own pre-game xG-against and shots-against rates", ["opponent suppression"], ["by player/position"]),
        F("nhl.shot_location", T, ["hdf60_pre", "hda60_pre", "hd_share_for_pre", "hd_share_against_pre"], "PARTIAL", "high-danger shot rates and shares for and against (MoneyPuck danger zones)", ["danger-zone mix for/against"], ["coordinates-level shot maps"]),
        F("nhl.shot_block_miss", T, ["block_rate_pre", "miss_rate_pre", "sog_conv_pre"], "FULL", "EWMA share of shot attempts blocked, missed and reaching the net", ["block, miss and conversion to SOG"]),
        F("nhl.penalty_rates", T, ["pen_taken60_pre", "pen_drawn60_pre", "opp_pen_drawn60_pre"], "PARTIAL", "penalties taken and drawn per 60 and the opponent's drawn rate", ["team penalty rates"], ["referee crew tendencies (no officials data)"]),
        F("nhl.pdo_regression", T, ["pdo_pre", "pdo_dev_pre"], "FULL", "EWMA PDO (shooting% + save%) and its gap to the long-run (half-life 40) value", ["team PDO", "regression pressure"]),
        F("nhl.finishing", T, ["sh_pct_pre"], "PARTIAL", "team shooting percentage (EWMA); player-level shrunk finishing is in the skater table", ["team finishing"], ["finishing talent by shooter"], raw=("moneypuck_team_games",)),
        F("nhl.ratings", T, ["rating_pre", "goal_diff_pre", "win_pct_pre"], "PARTIAL", "own rating = half goal-differential EWMA + half xG-differential EWMA; season win pct", ["own team rating"], ["season simulation"]),
        F("nhl.rest_travel", T, ["rest_days", "back_to_back", "games_last7"], "PARTIAL", "rest days, back-to-back flag, games in the previous 7 days", ["rest, back-to-back, density"], ["travel distance and time zones (no rink coordinates)"], raw=("moneypuck_team_games",), pit="schedule_known"),
        F("nhl.venue", T, ["venue_bias_pre"], "PARTIAL", "this home team's arena: mean combined shot attempts per 60 at home over earlier games minus the league mean (rink shot-counting bias)", ["rink shot-counting bias"], ["home-ice advantage in results; altitude/ice quality"]),
        F("nhl.ot_so", T, ["ot_pre", "so_win_pre"], "PARTIAL", "EWMA share of the team's games that reach overtime/shootout and its shootout win rate", ["OT/SO frequency", "shootout record"], ["3v3 scoring split", "rules by season"], raw=("nhl_games",)),
        F("nhl.empty_net", T, ["en_share_pre"], "PARTIAL", "EWMA share of the game's seconds with the team's net empty", ["empty-net time"], ["pulled-goalie timing and goals"], raw=("nhl_team_states",)),
        F("nhl.reg_tie_model", T, ["ot_pre", "goals_var_pre"], "PROXY", "frequency of games tied after regulation and the variance of total goals (EWMA / rolling 40)", [], ["bivariate Skellam/Poisson tie model (not built)"], raw=("nhl_games",)),
        F("nhl.total_goal_dispersion", T, ["goals_var_pre", "total_goals_pre"], "PARTIAL", "rolling 40-game variance and EWMA mean of the team's game total goals", ["goal-total dispersion"], ["home/away goal correlation"], raw=("nhl_games",)),
        F("nhl.toi", K, ["toi_pre", "toi_ev_pre", "toi_pp_pre", "toi_sh_pre", "toi_last3_pre"], "FULL", "EWMA time on ice by strength state (EV, PP, SH) and last-3 mean", ["TOI by strength state"], raw=("nhl_player_games",)),
        F("nhl.toi_trend", K, ["toi_trend_pre", "toi_sd10_pre"], "FULL", "last-3 mean minus EWMA TOI and the 10-game TOI standard deviation", ["TOI trend and workload"], raw=("nhl_player_games",)),
        F("nhl.pp_role", K, ["pp_toi_share_pre", "toi_pp_pre"], "PARTIAL", "EWMA share of the player's TOI on the power play and PP minutes", ["PP involvement"], ["PP1/PP2 unit assignment (no lines data)"], raw=("nhl_player_games",)),
        F("nhl.shot_rate", K, ["att60_pre", "sog60_pre", "att60_ev_pre", "att60_pp_pre"], "FULL", "EWMA individual shot attempts and shots on goal per 60 overall, at even strength and on the power play", ["individual shot rates by strength"], raw=("nhl_player_games",)),
        F("nhl.assist_rate", K, ["a1_60_pre", "a2_60_pre", "pts60_pre"], "FULL", "EWMA primary and secondary assists and points per 60", ["assist involvement"], raw=("nhl_player_games",)),
        F("nhl.onice_shpct", K, ["onice_sh_ev_pre"], "PARTIAL", "EWMA even-strength on-ice shooting percentage (GF/SOG with the player on ice)", ["on-ice shooting %"], ["on-ice goals vs expectation (needs on-ice xG)"], raw=("nhl_player_games",)),
        F("nhl.dman_shot_profile", K, ["is_d", "att60_pre", "toi_pp_pre"], "PARTIAL", "defenceman flag with shot rate and PP minutes", ["defence offensive role"], ["point-shot share (needs shot locations joined by shooter)"], raw=("nhl_player_games",)),
        F("nhl.injury_return_ramp", K, ["return_from_absence", "rest_days", "toi_trend_pre"], "PROXY", "days since the player's previous game (>=10 flags a return) and recent TOI trend", [], ["injury status itself (no timestamped injury source)"], raw=("nhl_player_games",)),
        F("nhl.stat_dist", K, ["goals_overdisp_pre", "sog_overdisp_pre"], "PARTIAL", "EWMA variance of goals and variance/mean of shots", ["overdispersion of goals and shots"], ["correlations between stats"], raw=("nhl_player_games",)),
        F("nhl.goalie_quality", G, ["sv_shrunk_pre", "sv_pre", "ev_sv_pre"], "PROXY", "save percentage shrunk toward the league rate (600 shots) and EWMA save %, even-strength save %", [], ["goals saved above expected (no xG by goalie joined)"], raw=("nhl_goalie_games",)),
        F("nhl.goalie_workload", G, ["rest_days", "sa_last3", "shots_faced_pre"], "FULL", "days since the goalie's previous start, shots faced in the previous 3 starts, EWMA shots faced", ["goalie rest", "recent shot load"], raw=("nhl_goalie_games",)),
        F("nhl.goalie_pull_risk", G, ["pulled_pre"], "FULL", "EWMA share of the goalie's starts where he played under 58 minutes", ["early-pull frequency"], raw=("nhl_goalie_games",)),
        F("nhl.goalie_danger_split", G, ["ev_sv_pre", "pp_sa_share_pre"], "PARTIAL", "even-strength save % and the share of shots faced on the penalty kill", ["strength-state split"], ["danger-zone save %, rebound control"], raw=("nhl_goalie_games",)),
        F("nhl.goalie_start_forecast", T, ["p_same_goalie_pre"], "PARTIAL", "empirical probability (earlier dates, >=30 cases) that the goalie who started the team's previous game starts again, by team back-to-back status", ["start probability from rest structure"], ["team-specific tendencies; confirmed starter (final flag only)"], raw=("nhl_goalie_games", "moneypuck_team_games")),
    ]
