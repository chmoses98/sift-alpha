"""NBA feature builders from raw ESPN box scores, shot events and official injury reports already in nba-edge-finder (RESEARCH_ONLY, point-in-time).

Raw datasets: espn_team_games, espn_player_games, espn_shot_events, nba_official_injury_report_rows.  Output tables: ``team`` (one row per team-game, pre-game features) and ``player``
(one row per player-game). Every FeatureSpec says which part of the catalog definition is implemented and what is not (e.g. no tracking data, no positions, no referee assignments).
"""
from __future__ import annotations

import glob

import numpy as np
import pandas as pd

from .core import FeatureSpec, Paths, games_in_window, opp_adjusted, pair_rows, prior_count, prior_date_mean, prior_ewm, prior_mean, rest_days, sort_chrono

S = "NBA"


def load_raw(p: Paths) -> dict:
    h = p.raw / "nba/data/history"
    cat = lambda pat, **kw: pd.concat([pd.read_parquet(f, **kw) for f in sorted(glob.glob(str(h / pat)))], ignore_index=True)
    return {"team_games": cat("espn/team_games_*.parquet"), "player_games": cat("espn/player_games_*.parquet"),
            "shots": cat("espn/shot_events_*.parquet", columns=["game_id", "team_id", "is_home", "zone", "shot_made", "is_free_throw", "is_shooting_play", "points_value", "season_type"]),
            "injury": cat("injury_reports/report_rows_*.parquet")}


def _team_table(raw: dict) -> pd.DataFrame:
    t = raw["team_games"]
    t = t[t.season_type == "regular"].copy()
    t["date"] = pd.to_datetime(t.game_date_et)
    t = t.rename(columns={"team_id": "team", "opp_team_id": "opp"})
    # team box components aggregated from player rows (3-point, assists, rebounds, steals, blocks, fouls, FG made)
    pg = raw["player_games"]
    agg = pg[pg.played == True].groupby(["game_id", "team_id"])[["fg3a", "fg3m", "fgm", "ftm", "ast", "reb", "stl", "blk", "pf"]].sum().reset_index().rename(columns={"team_id": "team"})
    t = t.merge(agg, on=["game_id", "team"], how="left")
    # bench scoring and rotation depth (post-game values; used only through prior-game EWMAs)
    b = pg[pg.played == True].assign(bench_pts=lambda d: np.where(d.started == True, 0, d.pts), deep=lambda d: (d.minutes >= 10).astype(float)).groupby(["game_id", "team_id"]).agg(bench_pts=("bench_pts", "sum"), n_rot=("deep", "sum")).reset_index().rename(columns={"team_id": "team"})
    t = t.merge(b, on=["game_id", "team"], how="left")
    # shot-zone mix from shot events (field-goal attempts only)
    sh = raw["shots"]
    sh = sh[(sh.is_shooting_play == True) & (sh.is_free_throw == False) & (sh.season_type == "regular")]
    z = sh.assign(rim=(sh.zone == "rim"), mid=(sh.zone == "midrange"), paint=(sh.zone == "paint_non_rim"), three=sh.zone.isin(["above_break_three", "corner_three"])) \
          .groupby(["game_id", "is_home"]).agg(z_att=("zone", "size"), z_rim=("rim", "sum"), z_mid=("mid", "sum"), z_paint=("paint", "sum"), z_three=("three", "sum")).reset_index().rename(columns={"is_home": "home"})
    z["home"] = z.home.astype(bool)           # shot events carry ESPN team ids, team_games carry NBA ids: the home flag within a game is the shared key
    t["home"] = t.home.astype(bool)
    t = t.merge(z, on=["game_id", "home"], how="left")
    t = sort_chrono(t)
    return t


def _team_features(t: pd.DataFrame) -> pd.DataFrame:
    t = t.copy()
    t["ppp"], t["allow_ppp"] = t.pts / t.possessions, t.opp_pts / t.possessions
    t["tov_rate"], t["ft_rate"], t["oreb_rate"] = t.tov / t.possessions, t.fta / t.fga, t.oreb / t.fga
    t["fg3_rate"], t["fg3_pct"] = t.fg3a / t.fga, t.fg3m / t.fg3a
    t["pf_rate"], t["ast_rate"] = t.pf / t.possessions, t.ast / t.fgm
    t["q1_share"], t["fh_share"] = t.q1 / t.pts, (t.q1 + t.q2) / t.pts
    t["ot"] = (t.n_ot > 0).astype(float)
    t["bench_share"] = t.bench_pts / t.pts
    for z in ("rim", "mid", "paint", "three"):
        t[f"zone_{z}"] = t[f"z_{z}"] / t.z_att
    t["won"] = (t.pts > t.opp_pts).astype(float)
    base = ["ppp", "allow_ppp", "possessions", "tov_rate", "ft_rate", "oreb_rate", "fg3_rate", "fg3_pct", "pf_rate", "ast_rate", "q1_share", "fh_share", "ot", "bench_share", "n_rot", "zone_rim", "zone_mid", "zone_paint", "zone_three", "won"]
    for c in base:
        t[f"{c}_pre"] = prior_ewm(t, "team", c)
    t["fg3_pct_long_pre"] = prior_ewm(t, "team", "fg3_pct", hl=30)
    t["fg3_pct_short_pre"] = prior_ewm(t, "team", "fg3_pct", hl=3, min_periods=2)
    # opponent's pre-game (allowed) columns -> opponent-adjusted ratings
    t = pair_rows(t, cols=["ppp_pre", "allow_ppp_pre", "possessions_pre", "tov_rate_pre", "ft_rate_pre", "zone_rim_pre", "zone_mid_pre", "zone_paint_pre", "zone_three_pre", "pf_rate_pre", "ast_rate_pre", "fg3_rate_pre"]).sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)
    t["lg_ppp_pre"] = prior_date_mean(t, "date", "ppp")
    t["lg_poss_pre"] = prior_date_mean(t, "date", "possessions")
    t["adj_ppp"] = opp_adjusted(t, "ppp", "opp_allow_ppp_pre", "lg_ppp_pre")
    t["adj_opp_ppp"] = opp_adjusted(t, "allow_ppp", "opp_ppp_pre", "lg_ppp_pre")
    t["adj_pace"] = opp_adjusted(t, "possessions", "opp_possessions_pre", "lg_poss_pre")
    t["off_rtg_adj_pre"] = prior_ewm(t, "team", "adj_ppp")
    t["def_rtg_adj_pre"] = prior_ewm(t, "team", "adj_opp_ppp")
    t["pace_adj_pre"] = prior_ewm(t, "team", "adj_pace")
    t["net_rtg_adj_pre"] = t.off_rtg_adj_pre - t.def_rtg_adj_pre
    # schedule
    t["rest_days"] = rest_days(t, ["team"])
    t["back_to_back"] = (t.rest_days == 1).astype(float).where(t.rest_days.notna())
    t["games_last7"] = games_in_window(t, "team", days=7)
    t["games_played_pre"] = prior_count(t, ["team", "season"])
    t["win_pct_pre"] = prior_mean(t, ["team", "season"], "won", min_periods=1)
    t["games_remaining"] = 82 - t.games_played_pre
    # home-court effect: expanding home-minus-away margin differential (own earlier games)
    t["margin"] = t.pts - t.opp_pts
    th = t[t.home].copy(); ta = t[~t.home].copy()
    th["home_margin_pre"] = prior_mean(th, "team", "margin", min_periods=5); ta["away_margin_pre"] = prior_mean(ta, "team", "margin", min_periods=5)
    t = t.merge(th[["game_id", "team", "home_margin_pre"]], on=["game_id", "team"], how="left").merge(ta[["game_id", "team", "away_margin_pre"]], on=["game_id", "team"], how="left")
    t["home_court_effect_pre"] = t.groupby("team", sort=False)["home_margin_pre"].ffill() - t.groupby("team", sort=False)["away_margin_pre"].ffill()
    # Pythagorean residual over the team's last 20 games (earlier games only)
    py = (t.pts ** 14) / (t.pts ** 14 + t.opp_pts ** 14)
    t["_resid"] = t.won - py
    t["pythag_resid_pre"] = prior_mean(t, "team", "_resid", window=20, min_periods=8)
    # own expected margin for the game (own ratings only, NO betting market): used for blowout probability
    t = pair_rows(t, cols=["off_rtg_adj_pre", "def_rtg_adj_pre", "pace_adj_pre"]).sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)
    poss = (t.pace_adj_pre + t.opp_pace_adj_pre) / 2
    t["exp_margin_pre"] = ((t.off_rtg_adj_pre - t.opp_def_rtg_adj_pre) - (t.opp_off_rtg_adj_pre - t.def_rtg_adj_pre)) / 2 * poss + np.where(t.home, 1.0, -1.0) * 1.5
    return t


def _player_features(raw: dict, t: pd.DataFrame) -> pd.DataFrame:
    p = raw["player_games"]
    p = p[(p.season_type == "regular")].copy()
    p["date"] = pd.to_datetime(p.game_date_et)
    p = p.rename(columns={"team_id": "team", "opp_team_id": "opp", "nba_id": "pid"})
    p = p[p.played == True].copy()
    p["started_f"] = p.started.astype(float)
    for c in ("pts", "reb", "ast", "stl", "blk", "tov", "pf", "fga", "fta", "ftm", "fg3a", "fg3m", "fgm"):
        p[f"{c}_pm"] = p[c] / p.minutes.where(p.minutes > 0)
    p["usage_pm"] = (p.fga + 0.44 * p.fta + p.tov) / p.minutes.where(p.minutes > 0)
    p["dd"] = ((p[["pts", "reb", "ast", "stl", "blk"]] >= 10).sum(axis=1) >= 2).astype(float)
    p["td"] = ((p[["pts", "reb", "ast", "stl", "blk"]] >= 10).sum(axis=1) >= 3).astype(float)
    p["foul_trouble"] = (p.pf >= 5).astype(float)
    p["foul_out"] = (p.pf >= 6).astype(float)
    p["fg3_share"] = p.fg3a / p.fga.where(p.fga > 0)
    p = p.sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)
    for c in ("minutes", "started_f", "pts_pm", "reb_pm", "ast_pm", "stl_pm", "blk_pm", "tov_pm", "pf_pm", "fga_pm", "fta_pm", "fg3a_pm", "usage_pm", "dd", "td", "foul_trouble", "foul_out", "fg3_share", "pts", "reb", "ast"):
        p[f"{c}_pre"] = prior_ewm(p, "pid", c, min_periods=3)
    p["min_last3_pre"] = prior_mean(p, "pid", "minutes", window=3, min_periods=2)
    p["min_sd10_pre"] = p.groupby("pid", sort=False)["minutes"].transform(lambda s: s.shift(1).rolling(10, min_periods=5).std())
    p["games_pre"] = prior_count(p, "pid")
    p["rest_days"] = rest_days(p, "pid", cap=30)
    p["role_change_pre"] = prior_mean(p, "pid", "started_f", window=3, min_periods=2) - prior_ewm(p, "pid", "started_f", hl=15)
    # shrunk shooting percentages (Beta-style prior toward the pre-game league rate with k attempts)
    for made, att, k, nm in (("fg3m", "fg3a", 100, "fg3"), ("ftm", "fta", 60, "ft")):
        cm = p.groupby("pid", sort=False)[made].transform(lambda s: s.shift(1).expanding().sum()); ca = p.groupby("pid", sort=False)[att].transform(lambda s: s.shift(1).expanding().sum())
        lg = prior_date_mean(p.assign(_r=p[made] / p[att].where(p[att] > 0)), "date", "_r")
        p[f"{nm}_pct_shrunk_pre"] = (cm.fillna(0) + k * lg) / (ca.fillna(0) + k)
        # recent (EWMA hl=5 of per-game rate) minus the long-run shrunk rate: a PROXY for shooting luck vs expectation
        p[f"{nm}_recent_dev_pre"] = prior_ewm(p.assign(_r=p[made] / p[att].where(p[att] > 0)), "pid", "_r", hl=5, min_periods=3) - p[f"{nm}_pct_shrunk_pre"]
    # EWMA covariance of pts/reb/ast (approximate: E[xy]-E[x]E[y] with EWMAs of earlier games)
    for a, b in (("pts", "reb"), ("pts", "ast"), ("reb", "ast")):
        p[f"_{a}{b}"] = p[a] * p[b]
        p[f"cov_{a}_{b}_pre"] = prior_ewm(p, "pid", f"_{a}{b}", hl=15) - p[f"{a}_pre"] * p[f"{b}_pre"]
    p["sd_pts_pre"] = np.sqrt((prior_ewm(p.assign(_s=p.pts ** 2), "pid", "_s", hl=15) - p.pts_pre ** 2).clip(lower=0))
    p["pts_overdisp_pre"] = (p.sd_pts_pre ** 2) / p.pts_pre.where(p.pts_pre > 0)
    # season-to-date per game
    for c in ("pts", "reb", "ast"):
        p[f"{c}_season_pg_pre"] = p.groupby(["pid", "season"], sort=False)[c].transform(lambda s: s.shift(1).expanding(min_periods=1).mean())
    p["games_season_pre"] = prior_count(p, ["pid", "season"])
    # attach team/opponent context from the team table (PRE-game columns only)
    ctx = ["game_id", "team", "off_rtg_adj_pre", "def_rtg_adj_pre", "pace_adj_pre", "possessions_pre", "exp_margin_pre", "opp_def_rtg_adj_pre", "opp_pace_adj_pre", "opp_tov_rate_pre", "opp_pf_rate_pre", "opp_ast_rate_pre", "opp_fg3_rate_pre", "opp_zone_rim_pre", "rest_days", "back_to_back"]
    tt = t[ctx].rename(columns={"rest_days": "team_rest_days", "back_to_back": "team_b2b"})
    p = p.merge(tt, on=["game_id", "team"], how="left")
    p["blowout_prob_pre"] = 2 * (1 - 0.5 * (1 + np.vectorize(__import__("math").erf)(((15 - p.exp_margin_pre.abs().fillna(0)) / 12) / 2 ** 0.5))) if False else _blowout(p.exp_margin_pre)
    # expected missed shots in the game by type (own and opponent pre-game rates x pre-game possessions), a rebound-pool measure
    return p


def _blowout(m: pd.Series) -> pd.Series:
    from math import erf, sqrt
    sd = 12.0
    f = lambda x: 0.5 * (1 + erf(x / sqrt(2)))
    return m.map(lambda v: np.nan if pd.isna(v) else (1 - f((15 - v) / sd)) + f((-15 - v) / sd))


def _injury_features(raw: dict, p: pd.DataFrame, horizon_min: int = 90) -> pd.DataFrame:
    """Point-in-time injury status: the last official report row published at least `horizon_min` minutes before the game's start; plus the calibrated probability that a player with that status
    plays, estimated from EARLIER games only (expanding). Coverage: 2025-26 only (the archive that has report timestamps)."""
    ir = raw["injury"].copy()
    ir = ir[ir.nba_id.notna() & ir.game_id.notna()].copy()
    ir["gid"] = ir.game_id.astype(str)
    ir = ir.drop(columns=["game_id"])
    ir["rt"] = pd.to_datetime(ir.report_time_utc, utc=True, errors="coerce")
    g = raw["player_games"][["game_id", "start_time_utc"]].drop_duplicates("game_id")
    g["gid"] = g.game_id.astype(str)
    g["start"] = pd.to_datetime(g.start_time_utc, utc=True, errors="coerce")
    ir = ir.merge(g[["gid", "game_id", "start"]], on="gid", how="inner")
    ir = ir[ir.rt <= ir.start - pd.Timedelta(minutes=horizon_min)]
    ir = ir.sort_values("rt").groupby(["game_id", "nba_id"], as_index=False).last()[["game_id", "nba_id", "status", "rt"]].rename(columns={"nba_id": "pid", "status": "inj_status", "rt": "inj_report_time"})
    code = {"available": 0, "probable": 1, "questionable": 2, "doubtful": 3, "out": 4}
    ir["inj_status_code"] = ir.inj_status.map(code)
    return ir


def compute(raw: dict) -> dict:
    t = _team_features(_team_table(raw))
    p = _player_features(raw, t)
    inj = _injury_features(raw, p)
    # status -> played base rate from EARLIER games: join statuses to all player rows (listed or not); a player-game with a status row is 'listed'
    allp = raw["player_games"][["game_id", "nba_id", "played", "game_date_et"]].rename(columns={"nba_id": "pid"})
    allp["date"] = pd.to_datetime(allp.game_date_et)
    lst = inj.merge(allp, on=["game_id", "pid"], how="inner").sort_values(["date", "game_id"], kind="mergesort")
    lst["played_f"] = lst.played.astype(float)
    # expanding rate by status over strictly earlier DATES
    rates = {}
    for s, grp in lst.groupby("inj_status"):
        d = grp.groupby("date").played_f.agg(["sum", "count"]).sort_index()
        d["cs"], d["cn"] = d["sum"].cumsum() - d["sum"], d["count"].cumsum() - d["count"]
        d["rate"] = np.where(d.cn >= 20, d.cs / d.cn.replace(0, np.nan), np.nan)
        rates[s] = d["rate"]
    lst["p_play_given_status_pre"] = [rates[s].get(dt, np.nan) for s, dt in zip(lst.inj_status, lst.date)]
    p = p.merge(inj[["game_id", "pid", "inj_status", "inj_status_code", "inj_report_time"]], on=["game_id", "pid"], how="left").merge(lst[["game_id", "pid", "p_play_given_status_pre"]], on=["game_id", "pid"], how="left")
    return {"team": t, "player": p}


def specs() -> list[FeatureSpec]:
    F = lambda cid, tab, cols, lvl, d, done=(), miss=(), raw=("espn_team_games",), pit="pregame_rolling": FeatureSpec(S, cid, tab, list(cols), lvl, d, list(done), list(miss), list(raw), pit)
    T, P = "team", "player"
    return [
        F("nba.off_rtg", T, ["off_rtg_adj_pre"], "PARTIAL", "EWMA (half-life 8 games) of points per possession, adjusted for the opponent's earlier-game points allowed, re-centred on the pre-game league mean", ["opponent-adjusted offensive rating"], ["lineup adjustment (needs confirmed lineups)"]),
        F("nba.def_rtg", T, ["def_rtg_adj_pre"], "FULL", "same construction for points allowed per possession", ["opponent-adjusted defensive rating"]),
        F("nba.pace", T, ["pace_adj_pre", "possessions_pre"], "PARTIAL", "EWMA of possessions per game, raw and opponent-adjusted", ["pace, opponent-adjusted"], ["lineup-aware pace"]),
        F("nba.ratings", T, ["net_rtg_adj_pre", "win_pct_pre"], "PARTIAL", "pre-game net rating (off minus def adjusted) and season win pct", ["team rating"], ["schedule strength for season markets", "market-implied history (excluded by policy)"]),
        F("nba.venue", T, ["home_court_effect_pre"], "PARTIAL", "own earlier home-margin minus away-margin (expanding, >=5 games each)", ["team-specific home-court effect"], ["arena-specific factors (altitude, rims)"]),
        F("nba.rest_travel", T, ["rest_days", "back_to_back", "games_last7"], "PARTIAL", "days since the team's previous game, back-to-back flag, games in the previous 7 days", ["rest", "back-to-back", "schedule density"], ["travel distance and time zones (no arena coordinates)", "altitude"], pit="schedule_known"),
        F("nba.pythag_residual", T, ["pythag_resid_pre"], "PARTIAL", "mean over the last 20 earlier games of (win - Pythagorean expectation, exponent 14)", ["point-differential vs record luck"], ["clutch record"]),
        F("nba.three_pt_luck", T, ["fg3_pct_short_pre", "fg3_pct_long_pre"], "PROXY", "recent (half-life 3) vs long-run (half-life 30) team 3P% — regression pressure, NOT a comparison with shot quality", [], ["shot-quality expectation for 3-point attempts (no defender-distance data)"]),
        F("nba.q_scoring", T, ["q1_share_pre", "fh_share_pre"], "PARTIAL", "EWMA of the share of the team's points scored in Q1 and in the first half", ["quarter/half scoring shape"], ["starter minutes in the first quarter"]),
        F("nba.ot_model", T, ["ot_pre"], "PARTIAL", "EWMA overtime frequency of the team's earlier games", ["team overtime base rate"], ["frequency by own-forecast margin/total bucket (not built yet)"]),
        F("nba.bench_scoring", T, ["bench_share_pre", "n_rot_pre"], "FULL", "EWMA share of points from non-starters and number of players with >=10 minutes", ["bench share", "rotation depth"], raw=("espn_player_games",)),
        F("nba.standings_motivation", T, ["win_pct_pre", "games_remaining", "games_played_pre"], "PARTIAL", "season win pct to date, games played and remaining", ["standing basics"], ["clinch/tank incentive and seed distance"]),
        F("nba.shot_profile", T, ["zone_rim_pre", "zone_mid_pre", "zone_paint_pre", "zone_three_pre", "opp_zone_rim_pre", "opp_zone_three_pre"], "FULL", "EWMA share of the team's FGA by zone (rim, paint, mid, three) and the opponent's zone mix (own-opponent allowed is the mirror: opponent's own mix is its tendency)", ["own zone mix", "opponent zone mix"], raw=("espn_shot_events",)),
        F("nba.turnover_pressure", T, ["tov_rate_pre", "opp_tov_rate_pre"], "PARTIAL", "team turnover rate per possession and the opponent's turnover rate (both pre-game EWMA)", ["turnover propensity"], ["deflections, turnovers per touch"]),
        F("nba.fouls_ft", T, ["ft_rate_pre", "pf_rate_pre", "opp_pf_rate_pre"], "PARTIAL", "free-throw attempts per FGA (drawing) and personal fouls per possession for the team and the opponent", ["foul drawing and committing rates"], ["officials/referee crew"], raw=("espn_team_games", "espn_player_games")),
        F("nba.rebound_pool", T, ["tov_rate_pre", "fg3_rate_pre", "oreb_rate_pre"], "PROXY", "components of the missed-shot pool (3-point rate, offensive-rebound rate); expected missed shots by type is built in the player table", [], ["expected missed shots by type"]),
        F("nba.opp_ast_allowed", T, ["opp_ast_rate_pre"], "PARTIAL", "the opponent team's own assist-per-made-FG rate (EWMA); NOT the assists it allows by role", ["team assist rate"], ["assists allowed by role/position (no positions)"]),
        F("nba.minutes", P, ["minutes_pre", "min_last3_pre", "min_sd10_pre", "blowout_prob_pre", "pf_pm_pre", "foul_trouble_pre"], "FULL", "EWMA minutes, last-3 mean, 10-game minutes SD, blowout probability P(|own-forecast margin|>15) from own ratings, personal-foul rate and foul-trouble frequency", ["role (minutes)", "blowout risk", "foul trouble"], raw=("espn_player_games", "espn_team_games")),
        F("nba.starter_probability", P, ["started_f_pre", "role_change_pre"], "PARTIAL", "EWMA share of games started and the last-3 minus long-run start share (role change)", ["start share", "role change"], ["closing-lineup probability"], raw=("espn_player_games",)),
        F("nba.usage", P, ["usage_pm_pre", "fga_pm_pre", "pts_pm_pre"], "PARTIAL", "EWMA of (FGA+0.44 FTA+TOV) per minute, FGA per minute and points per minute", ["usage proxy", "shot attempts"], ["creation share (no tracking/touches)"], raw=("espn_player_games",)),
        F("nba.three_volume", P, ["fg3a_pm_pre", "fg3_share_pre", "fg3_pct_shrunk_pre", "opp_fg3_rate_pre"], "PARTIAL", "3PA per minute, 3PA share of FGA, 3P% shrunk toward the pre-game league rate (k=100) and the opponent's 3-point attempt rate", ["3PA rate", "3P% shrinkage", "opponent 3PA"], ["catch-and-shoot share"], raw=("espn_player_games",)),
        F("nba.ft_attempts", P, ["fta_pm_pre", "ft_pct_shrunk_pre", "opp_pf_rate_pre"], "FULL", "FTA per minute, FT% shrunk toward league (k=60) and the opponent's foul rate", ["FT attempt rate", "FT%", "opponent foul rate"], raw=("espn_player_games", "espn_team_games")),
        F("nba.foul_rates", P, ["pf_pm_pre", "foul_trouble_pre", "foul_out_pre"], "FULL", "personal fouls per minute, share of games with >=5 fouls and with 6 fouls", ["fouls per minute", "foul-trouble and foul-out rates"], raw=("espn_player_games",)),
        F("nba.steal_block_rates", P, ["stl_pm_pre", "blk_pm_pre", "opp_tov_rate_pre", "opp_zone_rim_pre"], "FULL", "steals and blocks per minute, opponent turnover rate and opponent rim-attempt share", ["steals/blocks per minute", "opponent turnover rate", "opponent rim attempts"], raw=("espn_player_games", "espn_shot_events")),
        F("nba.player_shooting_regression", P, ["fg3_recent_dev_pre", "ft_recent_dev_pre"], "PROXY", "recent (half-life 5) per-game 3P%/FT% minus the long-run shrunk rate", [], ["expectation from shot quality; FG% by zone"], raw=("espn_player_games",)),
        F("nba.opp_def_pos", P, ["opp_def_rtg_adj_pre", "opp_ast_rate_pre"], "PROXY", "team-level defensive rating and assist rate of the opponent, NOT allowed stats by position", [], ["positions are not in the raw data"], raw=("espn_team_games",)),
        F("nba.milestone_rates", P, ["dd_pre", "td_pre"], "PARTIAL", "EWMA double-double and triple-double rates", ["base rates"], ["threshold proximity (a market-line concept)"], raw=("espn_player_games",)),
        F("nba.stat_dist", P, ["sd_pts_pre", "pts_overdisp_pre"], "PARTIAL", "EWMA standard deviation and variance/mean of points", ["points overdispersion"], ["rebounds/assists distributions and correlations beyond the covariance columns"], raw=("espn_player_games",)),
        F("nba.combo_covariance", P, ["cov_pts_reb_pre", "cov_pts_ast_pre", "cov_reb_ast_pre"], "PARTIAL", "EWMA covariance of points/rebounds/assists (half-life 15, E[xy]-E[x]E[y])", ["PRA/PR/PA/RA covariance"], ["exact rolling covariance"], raw=("espn_player_games",)),
        F("nba.season_stat_pace", P, ["pts_season_pg_pre", "reb_season_pg_pre", "ast_season_pg_pre", "games_season_pre"], "FULL", "season-to-date per-game points, rebounds and assists and games played", ["per-game trajectory"], raw=("espn_player_games",)),
        F("nba.injuries_pit", P, ["inj_status_code"], "PARTIAL", "official report status published at least 90 minutes before tip (0 available .. 4 out)", ["official NBA injury report vintage with report timestamp"], ["ESPN injury vintages (archive branch not pulled)", "history before 2025-26"], raw=("nba_official_injury_report_rows",), pit="pregame_rolling"),
        F("nba.status_resolution_prob", P, ["p_play_given_status_pre"], "FULL", "probability that a player with this status 90+ minutes before tip plays, from earlier dates only (needs >=20 earlier cases)", ["calibrated play probability by status"], raw=("nba_official_injury_report_rows", "espn_player_games")),
    ]
