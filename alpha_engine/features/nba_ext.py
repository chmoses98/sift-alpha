"""NBA team-game extension builders (RESEARCH_ONLY): four factors, three-point attempt matchup, assisted-FGM, shot-variance load, bench minutes, own-game environment, team 3PM pair stat.

Raw data: owner's nba-edge-finder ESPN box-score archive (team_games, player_games), regular season only. Output table ``team`` keyed (game_id, team); every feature for game G is built from STRICTLY EARLIER games
(core.prior_ewm shifts one game per team; league baselines use earlier DATES only; the opponent term is the opponent's own pre-game column). Every input is PARTIAL: each spec's `missing` lists what the catalog
definition asks for that is not implemented (lineup/active-set adjustment, fitted joint models, calibration scalars, tonight's confirmed lineup).
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec, pair_rows, prior_count, prior_date_mean, prior_ewm, prior_mean, sort_chrono

S = "NBA"
TG_COLS = ["game_id", "game_date_et", "season", "season_type", "team_id", "opp_team_id", "home", "pts", "opp_pts", "n_ot", "fga", "fta", "oreb", "tov", "possessions"]
PG_COLS = ["game_id", "team_id", "played", "started", "minutes", "pts", "ast", "fgm", "fg3m", "fg3a", "dreb"]
TG_CONTENT = ["pts", "opp_pts", "fga", "fta", "oreb", "tov", "possessions", "n_ot"]
PG_CONTENT = ["played", "started", "minutes", "pts", "ast", "fgm", "fg3m", "fg3a", "dreb"]


def load_raw(nba_dir) -> dict:
    h = Path(nba_dir) / "espn"
    cat = lambda pat, cols: pd.concat([pd.read_parquet(f, columns=cols) for f in sorted(glob.glob(str(h / pat)))], ignore_index=True)
    return {"team_games": cat("team_games_*.parquet", TG_COLS), "player_games": cat("player_games_*.parquet", PG_COLS)}


def _table(raw: dict) -> pd.DataFrame:
    t = raw["team_games"]; t = t[t.season_type == "regular"].copy(); t["date"] = pd.to_datetime(t.game_date_et)
    t = t.rename(columns={"team_id": "team", "opp_team_id": "opp"}); t["home"] = t.home.astype(bool)
    pg = raw["player_games"]; pg = pg[pg.played == True]
    agg = pg.groupby(["game_id", "team_id"]).agg(fgm=("fgm", "sum"), fg3m=("fg3m", "sum"), fg3a=("fg3a", "sum"), ast=("ast", "sum"), dreb=("dreb", "sum")).reset_index().rename(columns={"team_id": "team"})
    st = pg[pg.started == True].groupby(["game_id", "team_id"]).agg(st_min=("minutes", "sum"), st_n=("minutes", "size")).reset_index().rename(columns={"team_id": "team"})
    bn = pg[pg.started != True].groupby(["game_id", "team_id"]).agg(bench_pts=("pts", "sum")).reset_index().rename(columns={"team_id": "team"})
    t = t.merge(agg, on=["game_id", "team"], how="left").merge(st, on=["game_id", "team"], how="left").merge(bn, on=["game_id", "team"], how="left")
    t = sort_chrono(t)
    # opponent's same-game raw values (allowed quantities); these are shifted by prior_ewm below, so only EARLIER games ever reach a feature
    t = pair_rows(t, cols=["fgm", "fg3m", "fg3a", "fga", "fta", "oreb", "dreb", "tov", "possessions", "ast"])
    return sort_chrono(t)


def _lg(t, col):
    return prior_date_mean(t, "date", col)


def compute(raw: dict) -> dict:
    t = _table(raw); T = "team"
    poss = t.possessions
    # --- four factors (per game raw values)
    t["efg_o"] = (t.fgm + 0.5 * t.fg3m) / t.fga; t["efg_d"] = (t.opp_fgm + 0.5 * t.opp_fg3m) / t.opp_fga
    t["tov_o"] = t.tov / poss; t["tov_d"] = t.opp_tov / poss
    t["orb_o"] = t.oreb / (t.oreb + t.opp_dreb); t["orb_d"] = t.opp_oreb / (t.opp_oreb + t.dreb)
    t["ftr_o"] = t.fta / t.fga; t["ftr_d"] = t.opp_fta / t.opp_fga
    t["ppp100"] = t.pts / poss * 100
    for c in ("efg_o", "efg_d", "tov_o", "tov_d", "orb_o", "orb_d", "ftr_o", "ftr_d"):
        t[f"ff_{c}_pre"] = prior_ewm(t, T, c, hl=12)
    ff = [f"ff_{c}_pre" for c in ("efg_o", "efg_d", "tov_o", "tov_d", "orb_o", "orb_d", "ftr_o", "ftr_d")]
    t = pair_rows(t, cols=ff); t = sort_chrono(t)
    for k, o, d in (("efg", "efg_o", "efg_d"), ("tov", "tov_o", "tov_d"), ("orb", "orb_o", "orb_d"), ("ftr", "ftr_o", "ftr_d")):
        lg = _lg(t, o)
        t[f"ff_exp_{k}_pre"] = lg + (t[f"ff_{o}_pre"] - lg) + (t[f"opp_ff_{d}_pre"] - lg)
    lgp = _lg(t, "ppp100"); lef, lto, lor, lft = _lg(t, "efg_o"), _lg(t, "tov_o"), _lg(t, "orb_o"), _lg(t, "ftr_o")
    t["ff_exp_pts100_pre"] = lgp + 100 * (0.40 * (t.ff_exp_efg_pre - lef) - 0.25 * (t.ff_exp_tov_pre - lto) + 0.20 * (t.ff_exp_orb_pre - lor) + 0.15 * (t.ff_exp_ftr_pre - lft))
    # --- team 3PA matchup
    t["r3"] = t.fg3a / poss * 100; t["a3"] = t.opp_fg3a / poss * 100
    t["season_idx"] = t.season.astype(str).str[:4].astype(int)
    t["n_season_pre"] = prior_count(t, [T, "season"])
    t["t3_ewm"] = prior_ewm(t, T, "r3", hl=15); t["a3_ewm"] = prior_ewm(t, T, "a3", hl=20)
    ps = t.groupby([T, "season_idx"]).r3.mean().rename("_ps").reset_index(); ps["season_idx"] += 1
    t = t.merge(ps, on=[T, "season_idx"], how="left")
    w = t.n_season_pre.clip(upper=82)
    t["t3_rate_pre"] = np.where(t._ps.notna() & t.t3_ewm.notna(), (w * t.t3_ewm + 20 * t._ps) / (w + 20), t.t3_ewm)
    lg3 = _lg(t, "r3")
    t["t3_allowed_idx_pre"] = (w * (t.a3_ewm / lg3) + 25 * 1.0) / (w + 25)
    t["pace_pre"] = prior_ewm(t, T, "possessions", hl=20)
    t = pair_rows(t, cols=["t3_allowed_idx_pre", "pace_pre"]); t = sort_chrono(t)
    t["exp_pace_pre"] = np.sqrt(t.pace_pre * t.opp_pace_pre)
    t["exp_3pa_pre"] = t.t3_rate_pre * t.opp_t3_allowed_idx_pre * t.exp_pace_pre / 100
    # --- assisted FGM
    t["ast_rate"] = t.ast / t.fgm; t["fg_pct"] = t.fgm / t.fga; t["fga_pp"] = t.fga / poss
    for c in ("ast_rate", "fg_pct", "fga_pp"): t[f"{c}_pre"] = prior_ewm(t, T, c, hl=20)
    t["exp_ast_fgm_pre"] = t.exp_pace_pre * t.fga_pp_pre * t.fg_pct_pre * t.ast_rate_pre
    # --- shot variance load (components per team; total needs both teams)
    t["fg2a"] = t.fga - t.fg3a; t["fg2m"] = t.fgm - t.fg3m;
    t["p3"] = t.fg3m / t.fg3a; t["p2"] = t.fg2m / t.fg2a
    t["fg3a_g"], t["fg2a_g"], t["fta_g"] = t.fg3a, t.fg2a, t.fta
    for c in ("p3", "p2", "fg3a_g", "fg2a_g", "fta_g"): t[f"{c}_pre"] = prior_ewm(t, T, c, hl=20)
    t["pace_dev2"] = (t.possessions - prior_ewm(t, T, "possessions", hl=20)) ** 2
    t["var_pace_pre"] = prior_ewm(t, T, "pace_dev2", hl=40)
    t["ppp_pre"] = prior_ewm(t, T, "ppp100", hl=20) / 100
    t["var_shot_pre"] = t.fg3a_g_pre * 9 * t.p3_pre * (1 - t.p3_pre) + t.fg2a_g_pre * 4 * t.p2_pre * (1 - t.p2_pre)
    t = pair_rows(t, cols=["var_shot_pre"]); t = sort_chrono(t)
    t["var_total_pre"] = t.var_pace_pre * t.ppp_pre ** 2 + t.var_shot_pre + t.opp_var_shot_pre
    # --- bench minutes
    t["bench_min"] = 240 + 25 * t.n_ot - t.st_min
    t["bench_ppm"] = t.bench_pts / t.bench_min.where(t.bench_min > 0)
    t["bench_min_pre"] = prior_ewm(t, T, "bench_min", hl=30)
    t["bench_min_sd_pre"] = np.sqrt(prior_ewm(t.assign(_d=(t.bench_min - t.bench_min_pre) ** 2), T, "_d", hl=30))
    cp = t.groupby(T, sort=False).bench_pts.transform(lambda s: s.shift(1).expanding().sum()); cm = t.groupby(T, sort=False).bench_min.transform(lambda s: s.shift(1).expanding().sum())
    lgb = _lg(t, "bench_ppm"); t["bench_ppm_shr_pre"] = (cp.fillna(0) + 300 * lgb * 1.0) / (cm.fillna(0) + 300)
    t["exp_bench_pts_pre"] = t.bench_min_pre * t.bench_ppm_shr_pre
    # --- own-game environment: opponent-adjusted ortg (hl 20) and points
    t["ppp_opp_d"] = t.opp_pts / poss * 100
    t["env_ortg_pre"] = prior_ewm(t, T, "ppp100", hl=20)
    t["env_drtg_pre"] = prior_ewm(t, T, "ppp_opp_d", hl=20)
    t = pair_rows(t, cols=["env_ortg_pre", "env_drtg_pre"]); t = sort_chrono(t)
    lgo = _lg(t, "ppp100")
    t["env_exp_ortg_pre"] = t.env_ortg_pre + t.opp_env_drtg_pre - lgo
    t["env_exp_pts_pre"] = t.exp_pace_pre * t.env_exp_ortg_pre / 100
    t["env_sd_pts_pre"] = np.sqrt(prior_ewm(t.assign(_d=(t.pts - prior_ewm(t, T, "pts", hl=20)) ** 2), T, "_d", hl=20))
    # --- team 3PM pair stat
    t["fg3_pct_ew"] = prior_ewm(t.assign(_p=t.fg3m / t.fg3a), T, "_p", hl=20)
    c3m = t.groupby(T, sort=False).fg3m.transform(lambda s: s.shift(1).expanding().sum()); c3a = t.groupby(T, sort=False).fg3a.transform(lambda s: s.shift(1).expanding().sum())
    lgp3 = _lg(t.assign(_p=t.fg3m / t.fg3a), "_p"); t["fg3_rate_shr_pre"] = (c3m.fillna(0) + 150 * lgp3) / (c3a.fillna(0) + 150)
    t["exp_3pm_pre"] = t.exp_3pa_pre * t.fg3_rate_shr_pre
    # dispersion of team 3PM: var/mean excess from the team's own earlier games (method of moments, expanding)
    mu = t.groupby(T, sort=False).fg3m.transform(lambda s: s.shift(1).expanding(min_periods=20).mean()); vr = t.groupby(T, sort=False).fg3m.transform(lambda s: s.shift(1).expanding(min_periods=20).var())
    t["nb_disp3_pre"] = ((vr - mu) / mu ** 2).clip(lower=0)
    t["season"] = t.season.astype(str).str[:4].astype(int)
    out = t[["game_id", "team", "date", "season"] + [c for s in specs() for c in s.columns if c in t.columns]].copy()
    out = out.loc[:, ~out.columns.duplicated()]
    return {"team": out}


def specs() -> list[FeatureSpec]:
    F = lambda cid, cols, d, done, miss: FeatureSpec(S, cid, "team", cols, "PARTIAL", d, done, miss, ["espn_team_games", "espn_player_games"], "pregame_rolling")
    return [
        F("nba.four_factors_matchup", [f"ff_{c}_pre" for c in ("efg_o", "efg_d", "tov_o", "tov_d", "orb_o", "orb_d", "ftr_o", "ftr_d")] + ["ff_exp_efg_pre", "ff_exp_tov_pre", "ff_exp_orb_pre", "ff_exp_ftr_pre", "ff_exp_pts100_pre"],
          "per-possession four factors, offence and defence (EWMA hl 12), expected factor = league + own offence dev + opponent defence-allowed dev, combined with the stated weights",
          ["four factors offence+defence", "EWMA hl 12", "league+dev+opp-dev expected factor", "weights 0.4/0.25/0.2/0.15"], ["iterative opponent adjustment", "season window", "team shrinkage prior weight 20", "lineup adjustment for absentees"]),
        F("nba.team_three_attempt_matchup", ["t3_rate_pre", "t3_allowed_idx_pre", "exp_3pa_pre"], "3PA per 100 possessions (EWMA hl 15, shrunk to prior-season mean, weight 20 games), opponent 3PA-allowed index (hl 20, shrunk to 1.0 with weight 25), expected 3PA = rate x index x geometric-mean pace / 100",
          ["rate", "allowed index", "expected 3PA"], ["adjustment for missing high-volume shooters", "three_pt_luck make rate", "as-of market snapshot"]),
        F("nba.team_assisted_fgm_expectation", ["ast_rate_pre", "fg_pct_pre", "fga_pp_pre", "exp_ast_fgm_pre"], "E[assisted FGM] = projected pace x FGA per possession x FG% x assisted rate (team assists / FGM; all EWMA hl 20)",
          ["assisted-rate, FG%, FGA/poss", "expected assisted FGM"], ["opponent adjustment of FG% and assisted rate", "shrinkage k=150/100", "player minutes-share scaling", "sd by game"]),
        F("nba.three_point_variance_load", ["var_pace_pre", "var_shot_pre", "var_total_pre"], "variance of game total from pace variance x ppp^2 plus 3PA/2PA binomial shot variance of both teams (EWMA hl 20/40)",
          ["pace-variance term", "3PA and 2PA binomial terms", "total variance"], ["FTA term and dispersion", "pace/ppp covariance", "opponent-adjusted attempts", "calibration scalar lambda", "skew"]),
        F("nba.bench_minutes_distribution", ["bench_min_pre", "bench_min_sd_pre", "bench_ppm_shr_pre", "exp_bench_pts_pre"], "bench minutes = 240+25*OT-starter minutes (EWMA hl 30) with sd, bench points per minute shrunk to league with k=300 minutes, expected bench points",
          ["bench minutes mean+sd", "bench ppm shrunk k=300", "expected bench points"], ["scenario mixture (blowout/close/OT/foul trouble)", "as-of confirmed lineup", "30-game half-life on ppm"]),
        F("nba.own_game_environment", ["exp_pace_pre", "env_exp_ortg_pre", "env_exp_pts_pre", "env_sd_pts_pre"], "geometric-mean projected pace x opponent-adjusted ortg (hl 20) / 100, points sd",
          ["pace", "adjusted ortg", "expected points", "sd"], ["ridge opponent adjustment tuned on 2 prior seasons", "active-set lineup deltas", "tonight availability"]),
        F("nba.team_stat_pair_difference_model", ["fg3_rate_shr_pre", "exp_3pm_pre", "nb_disp3_pre"], "expected team 3PM = expected 3PA x shrunk 3P% (k=150 attempts) with method-of-moments NB dispersion from the team's own earlier games",
          ["expected 3PM per team", "NB dispersion"], ["Gaussian copula and rho vs pace", "P(A>B)/P(tie) pmf", "blowout correction"]),
    ]
