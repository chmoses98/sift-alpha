"""NHL team-game extension builders (RESEARCH_ONLY): loser-point / extra-time rates, 5v5 attempt volume, Kalman rating posterior, playoff series OT-count, series-state scoring shift, series-game dependence.

Raw data: owner's NHL-edge-finder archive: NHL API game results (nhl/games_*.parquet, 2008-2025) and MoneyPuck team-game rows (moneypuck/team_games_*.parquet; xG is a published model output, MoneyPuck terms unresolved -> research only).
Output table ``team`` keyed (game_id, team): every feature for game G uses games on STRICTLY EARLIER DATES only (daily batches: all games of a date see the same earlier state), never the game's own result.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec

S = "NHL"
G_COLS = ["game_id", "season", "game_type", "game_date", "home_team_id", "away_team_id", "home_score", "away_score", "last_period_type", "final"]
MP_COLS = ["game_id", "team_id", "situation", "shotAttemptsFor", "shotAttemptsAgainst", "iceTime", "scoreVenueAdjustedxGoalsFor", "scoreVenueAdjustedxGoalsAgainst"]
G_CONTENT = ["home_score", "away_score", "last_period_type"]
MP_CONTENT = ["shotAttemptsFor", "shotAttemptsAgainst", "iceTime", "scoreVenueAdjustedxGoalsFor", "scoreVenueAdjustedxGoalsAgainst"]
HL_ATT = 164.0          # two seasons of games


def load_raw(nhl_dir) -> dict:
    h = Path(nhl_dir)
    cat = lambda pat, cols: pd.concat([pd.read_parquet(f, columns=cols) for f in sorted(glob.glob(str(h / pat)))], ignore_index=True)
    return {"games": cat("nhl/games_*.parquet", G_COLS), "mp": cat("moneypuck/team_games_*.parquet", MP_COLS)}


def _rows(raw: dict) -> pd.DataFrame:
    g = raw["games"]; g = g[g.final == True].copy(); g["date"] = pd.to_datetime(g.game_date)
    rows = []
    for side, opp, me_s, op_s, home in (("home_team_id", "away_team_id", "home_score", "away_score", True), ("away_team_id", "home_team_id", "away_score", "home_score", False)):
        rows.append(pd.DataFrame({"game_id": g.game_id, "team": g[side], "opp": g[opp], "date": g.date, "season": g.season, "gtype": g.game_type, "home": home, "gf": g[me_s], "ga": g[op_s], "lpt": g.last_period_type.astype(str)}))
    t = pd.concat(rows, ignore_index=True)
    t["win"] = (t.gf > t.ga).astype(float); t["beyond"] = t.lpt.isin(["OT", "SO"]).astype(float)
    t["reg_win"] = t.win * (t.lpt == "REG"); t["extra_win"] = t.win * t.beyond; t["row_win"] = t.win * (t.lpt != "SO")
    return t.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)


def _loser_point(t: pd.DataFrame) -> None:
    reg = t[t.gtype == 2]
    ssum = reg.groupby(["team", "season"])[["beyond", "reg_win", "extra_win", "row_win"]].agg(["sum", "size"])
    # per-team season-to-date counts BEFORE the game (strictly earlier dates: batch by date)
    day = reg.groupby(["team", "season", "date"])[["beyond", "reg_win", "extra_win", "row_win"]].sum().reset_index().sort_values(["team", "season", "date"])
    day["n"] = reg.groupby(["team", "season", "date"]).size().values
    for c in ("beyond", "reg_win", "extra_win", "row_win", "n"):
        day[f"c_{c}"] = day.groupby(["team", "season"])[c].cumsum() - day[c]
    tot = reg.groupby(["team", "season"])[["beyond", "reg_win", "extra_win", "row_win"]].sum(); tot["n"] = reg.groupby(["team", "season"]).size(); tot = tot.reset_index(); tot["season"] += 1
    tot = tot.rename(columns={c: f"p_{c}" for c in ("beyond", "reg_win", "extra_win", "row_win", "n")})
    m = t.merge(day[["team", "season", "date"] + [f"c_{c}" for c in ("beyond", "reg_win", "extra_win", "row_win", "n")]], on=["team", "season", "date"], how="left").merge(tot, on=["team", "season"], how="left")
    ok = (m.gtype == 2).to_numpy()
    for c in ("beyond", "reg_win", "extra_win", "row_win", "n"):
        m[f"w_{c}"] = m[f"c_{c}"].fillna(0) + 0.5 * m[f"p_{c}"].fillna(0)
    # league beyond rate over earlier dates (regular season, all earlier games)
    d = reg.groupby("date").beyond.agg(["sum", "count"]).sort_index(); d["cs"] = d["sum"].cumsum() - d["sum"]; d["cn"] = d["count"].cumsum() - d["count"]
    lg = (d.cs / d.cn.replace(0, np.nan)).rename("lg_beyond"); m = m.merge(lg, left_on="date", right_index=True, how="left")
    n = m.w_n
    pb = (m.w_beyond + 30 * m.lg_beyond) / (n + 30)
    pwe = (m.w_extra_win + 40 * 0.5) / (m.w_beyond + 40)
    prw = (m.w_reg_win / n).where(n >= 10)
    pts = 2 * prw + 2 * pb * pwe + 1 * pb * (1 - pwe)
    out = {"lp_beyond_pre": pb, "lp_win_extra_pre": pwe, "lp_reg_win_pre": prw, "lp_pts_pg_pre": pts, "lp_reg_wins_season_pre": m.c_reg_win, "lp_row_season_pre": m.c_row_win}
    for k, v in out.items():
        t[k] = np.where(ok & (n.to_numpy() >= 10), v.to_numpy(), np.nan) if k != "lp_reg_wins_season_pre" and k != "lp_row_season_pre" else np.where(ok, v.fillna(0).to_numpy(), np.nan)


def _attempts(t: pd.DataFrame, raw: dict) -> None:
    mp = raw["mp"]
    a = mp[mp.situation == "5on5"][["game_id", "team_id", "shotAttemptsFor", "shotAttemptsAgainst", "iceTime"]].rename(columns={"team_id": "team"}).drop_duplicates(["game_id", "team"])
    pp = mp[mp.situation == "5on4"][["game_id", "team_id", "iceTime"]].rename(columns={"team_id": "team", "iceTime": "pp"}).drop_duplicates(["game_id", "team"])
    pk = mp[mp.situation == "4on5"][["game_id", "team_id", "iceTime"]].rename(columns={"team_id": "team", "iceTime": "pk"}).drop_duplicates(["game_id", "team"])
    m = t[["game_id", "team", "opp", "date", "home", "gtype"]].merge(a, on=["game_id", "team"], how="left").merge(pp, on=["game_id", "team"], how="left").merge(pk, on=["game_id", "team"], how="left")
    m = m[m.gtype == 2]
    ice = m.iceTime.where(m.iceTime > 0)       # a zero-ice-time 5v5 row carries no rate
    m["off60"] = m.shotAttemptsFor / (ice / 3600.0); m["def60"] = m.shotAttemptsAgainst / (ice / 3600.0)
    m["pp_min"] = m.pp.fillna(0) / 60.0; m["pk_min"] = m.pk.fillna(0) / 60.0
    m = m.sort_values(["date", "game_id", "team"], kind="mergesort")
    # per-team EWMA of earlier DATES: collapse to one row per (team,date)
    dd = m.groupby(["team", "date"], sort=False)[["off60", "def60", "pp_min", "pk_min"]].mean().reset_index().sort_values(["team", "date"], kind="mergesort")
    for c, hl in (("off60", HL_ATT), ("def60", HL_ATT), ("pp_min", 40.0), ("pk_min", 40.0)):
        dd[f"{c}_pre"] = dd.groupby("team", sort=False)[c].transform(lambda s: s.shift(1).ewm(halflife=hl, min_periods=5).mean())
    m = m.merge(dd[["team", "date", "off60_pre", "def60_pre", "pp_min_pre", "pk_min_pre"]], on=["team", "date"], how="left")
    # league baselines over earlier dates
    ld = m.groupby("date").agg(o=("off60", "sum"), n=("off60", "count")).sort_index(); ld["lg"] = (ld.o.cumsum() - ld.o) / (ld.n.cumsum() - ld.n).replace(0, np.nan)
    m = m.merge(ld[["lg"]].rename(columns={"lg": "lg_att60"}), left_on="date", right_index=True, how="left")
    hd = m.assign(hm=np.where(m.home, 1.0, -1.0) * m.off60).groupby("date").agg(h=("hm", "sum"), n=("off60", "count")).sort_index(); hd["ha"] = (hd.h.cumsum() - hd.h) / (hd.n.cumsum() - hd.n).replace(0, np.nan)
    m = m.merge(hd[["ha"]].rename(columns={"ha": "home_adj"}), left_on="date", right_index=True, how="left")
    o = m[["game_id", "team", "off60_pre", "def60_pre", "pp_min_pre", "pk_min_pre"]].rename(columns={"team": "opp", "off60_pre": "o_off", "def60_pre": "o_def", "pp_min_pre": "o_pp", "pk_min_pre": "o_pk"})
    m = m.merge(o, on=["game_id", "opp"], how="left")
    m["exp_att60_pre"] = m.lg_att60 + (m.off60_pre - m.lg_att60) + (m.o_def - m.lg_att60) + np.where(m.home, 0.5, -0.5) * m.home_adj
    m["proj_5v5_min_pre"] = 60 - ((m.pp_min_pre + m.o_pk) / 2 + (m.pk_min_pre + m.o_pp) / 2)
    o2 = m[["game_id", "team", "exp_att60_pre"]].rename(columns={"team": "opp", "exp_att60_pre": "o_exp"})
    m = m.merge(o2, on=["game_id", "opp"], how="left")
    m["exp_game_att_pre"] = (m.exp_att60_pre + m.o_exp) * m.proj_5v5_min_pre / 60
    for c in ("off60_pre", "def60_pre", "exp_att60_pre", "proj_5v5_min_pre", "exp_game_att_pre"):
        t[f"att_{c}"] = t[["game_id", "team"]].merge(m[["game_id", "team", c]], on=["game_id", "team"], how="left")[c].to_numpy()


def _kalman(t: pd.DataFrame, raw: dict) -> None:
    mp = raw["mp"]; a = mp[mp.situation == "all"][["game_id", "team_id", "scoreVenueAdjustedxGoalsFor", "scoreVenueAdjustedxGoalsAgainst"]].rename(columns={"team_id": "team"}).drop_duplicates(["game_id", "team"])
    m = t[t.gtype == 2][["game_id", "team", "opp", "date", "season"]].merge(a, on=["game_id", "team"], how="left")
    m["y"] = m.scoreVenueAdjustedxGoalsFor - m.scoreVenueAdjustedxGoalsAgainst
    mean: dict = {}; var: dict = {}; last_season: dict = {}; res_n = 0; res_ss = 0.0
    out_m = {}; out_s = {}
    for date, day in m.groupby("date", sort=True):
        # pre-game state for every team playing today (season rollover: mean shrunk by 0.5, variance reset to the 0.25^2 preseason prior)
        pre = {}
        for team in set(day.team):
            s = int(day[day.team == team].season.iloc[0])
            if team not in mean: mean[team], var[team] = 0.0, 0.25 ** 2
            elif last_season[team] != s: mean[team], var[team] = 0.5 * mean[team], 0.25 ** 2
            last_season[team] = s; pre[team] = (mean[team], var[team])
        s2 = res_ss / res_n if res_n >= 100 else 1.5 ** 2
        upd = []
        for r in day.itertuples():
            mi, vi = pre[r.team]; out_m[(r.game_id, r.team)] = mi; out_s[(r.game_id, r.team)] = np.sqrt(vi)
            if np.isnan(r.y) or r.opp not in pre: continue
            mj, vj = pre[r.opp]
            vpred = vi + 0.02 ** 2; R = s2 + vj
            z = r.y + mj; K = vpred / (vpred + R)
            upd.append((r.team, mi + K * (z - mi), (1 - K) * vpred, r.y - (mi - mj)))
        for team, mn, vr, resid in upd:
            mean[team], var[team] = mn, vr; res_n += 1; res_ss += resid ** 2
        # teams that played today but had no usable observation still take the drift step
        for team in pre:
            if not any(u[0] == team for u in upd): var[team] = pre[team][1] + 0.02 ** 2
    t["kf_rating_mean_pre"] = [out_m.get((g, x), np.nan) for g, x in zip(t.game_id, t.team)]
    t["kf_rating_sd_pre"] = [out_s.get((g, x), np.nan) for g, x in zip(t.game_id, t.team)]


def _series(t: pd.DataFrame) -> None:
    po = t[t.gtype == 3].copy(); po["a"] = po[["team", "opp"]].min(axis=1); po["b"] = po[["team", "opp"]].max(axis=1)
    po["skey"] = po.season.astype(str) + "|" + po.a.astype(str) + "|" + po.b.astype(str)
    g = po[po.home].drop_duplicates("game_id").sort_values(["skey", "date", "game_id"], kind="mergesort")      # one row per game (home perspective)
    g["gno"] = g.groupby("skey").cumcount() + 1
    g["w_a"] = ((g.team == g.a) & (g.win == 1) | (g.opp == g.a) & (g.win == 0)).astype(float); g["w_b"] = 1 - g.w_a
    g["wa_pre"] = g.groupby("skey").w_a.cumsum() - g.w_a; g["wb_pre"] = g.groupby("skey").w_b.cumsum() - g.w_b
    g["ot"] = g.beyond; g["ot_pre"] = g.groupby("skey").ot.cumsum() - g.ot
    g["total"] = g.gf + g.ga
    g["state"] = np.maximum(g.wa_pre, g.wb_pre).astype(int).astype(str) + "-" + np.minimum(g.wa_pre, g.wb_pre).astype(int).astype(str)
    g["elim"] = (np.maximum(g.wa_pre, g.wb_pre) == 3).astype(float)
    end = g.groupby("skey").agg(end=("date", "max"), n=("gno", "max"), k=("ot", "sum"), wmax=("w_a", "sum"))
    end["done"] = (end.wmax == 4) | ((end.n - end.wmax) == 4); end = end[end.done]
    dates = sorted(g.date.unique()); out = {}
    cum_games = g.groupby("date").agg(n=("ot", "size"), k=("ot", "sum"), s=("total", "sum")).sort_index()
    cum = cum_games.cumsum() - cum_games
    for d in dates:
        e = end[end.end < d]; ge = g[g.date < d]
        p = (ge.ot.sum() / len(ge)) if len(ge) else np.nan
        rho = np.nan; N = len(e)
        if N >= 5 and 0 < e.k.sum() < e.n.sum():
            pe = e.k.sum() / e.n.sum(); Q = ((e.k - e.n * pe) ** 2).sum() / (pe * (1 - pe)); rho = (Q - e.n.sum()) / (e.n * (e.n - 1)).sum()
        rho_s = (N * (rho if not np.isnan(rho) else 0.05) + 40 * 0.05) / (N + 40) if N >= 5 else np.nan
        pm = (ge.total.mean() if len(ge) else np.nan)
        cells = ge.groupby("state").total.agg(["sum", "count"])
        out[d] = (p, rho_s, N, pm, cells)
    pp = []; sf = []; sn = []; rr = []; nn = []
    for r in g.itertuples():
        p, rho_s, N, pm, cells = out[r.date]
        c = cells.loc[r.state] if r.state in cells.index else None; ns = 0 if c is None else c["count"]; ss = 0.0 if c is None else c["sum"]
        fac = ((ss + 15 * pm) / (ns + 15)) / pm if pm and not np.isnan(pm) else np.nan
        pp.append(p); rr.append(rho_s); nn.append(N); sf.append(fac); sn.append(ns)
    g["ot_p_hist_pre"] = pp; g["ot_rho_pre"] = rr; g["ot_nseries_pre"] = nn; g["sss_factor_pre"] = sf; g["sss_n_pre"] = sn
    # logit lag coefficient refit once per season on playoff games of EARLIER seasons: y = home win; x = [1, rating gap, lag]; lag-coefficient ridge sd 0.15
    reg = t[t.gtype == 2]; gd = reg.assign(gd=reg.gf - reg.ga).groupby(["season", "team"]).gd.mean().rename("gdpg")
    g = g.merge(gd.rename("gd_h"), left_on=["season", "team"], right_index=True, how="left").merge(gd.rename("gd_o"), left_on=["season", "opp"], right_index=True, how="left")
    g["x_gap"] = g.gd_h - g.gd_o
    # lag result from THIS home team's view: +1 if it won the previous game of the series, -1 if it lost it, 0 for game 1
    pw = g.groupby("skey").win.shift(1).astype(float).to_numpy(); ph = g.groupby("skey").team.shift(1).astype(float).to_numpy()
    won_prev = np.where(ph == g.team.to_numpy(float), pw, 1 - pw); g["x_lag"] = np.where(g.gno.to_numpy() == 1, 0.0, 2 * won_prev - 1)
    coef = {}
    for s in sorted(g.season.unique()):
        tr = g[(g.season < s) & g.x_gap.notna()]
        if len(tr) < 300: continue
        X = np.column_stack([np.ones(len(tr)), tr.x_gap.to_numpy(float), tr.x_lag.to_numpy(float)]); y = tr.win.to_numpy(float)
        lam = np.array([0.0, 0.0, 1 / 0.15 ** 2]); b = np.zeros(3)
        for _ in range(30):
            pr = 1 / (1 + np.exp(-X @ b)); gr = X.T @ (y - pr) - lam * b; H = (X * (pr * (1 - pr))[:, None]).T @ X + np.diag(lam); b = b + np.linalg.solve(H, gr)
        coef[s] = (b[2], np.sqrt(np.linalg.inv(H)[2, 2]))
    g["sgd_lag_coef_pre"] = g.season.map(lambda s: coef.get(s, (np.nan, np.nan))[0]); g["sgd_lag_se_pre"] = g.season.map(lambda s: coef.get(s, (np.nan, np.nan))[1])
    # team-perspective frame
    base = po[["game_id", "team", "opp", "home"]].merge(g[["game_id", "a", "gno", "wa_pre", "wb_pre", "ot_pre", "elim", "x_lag", "ot_p_hist_pre", "ot_rho_pre", "ot_nseries_pre", "sss_factor_pre", "sss_n_pre", "sgd_lag_coef_pre", "sgd_lag_se_pre", "team"]].rename(columns={"team": "h_team"}), on="game_id", how="left")
    mine = np.where(base.team == base.a, base.wa_pre, base.wb_pre); oth = np.where(base.team == base.a, base.wb_pre, base.wa_pre)
    base["ser_game_no"] = base.gno; base["ser_wins_pre"] = mine; base["ser_opp_wins_pre"] = oth; base["ser_ot_games_pre"] = base.ot_pre; base["ser_elim_pre"] = base.elim
    base["ser_lag_result_pre"] = np.where(base.team == base.h_team, base.x_lag, -base.x_lag)
    base = base.rename(columns={"ot_p_hist_pre": "ser_ot_p_hist_pre", "ot_rho_pre": "ser_ot_rho_pre", "ot_nseries_pre": "ser_ot_nseries_pre", "sss_factor_pre": "ser_state_factor_pre", "sss_n_pre": "ser_state_n_pre", "sgd_lag_coef_pre": "ser_lag_coef_pre", "sgd_lag_se_pre": "ser_lag_se_pre"})
    for c in ("ser_game_no", "ser_wins_pre", "ser_opp_wins_pre", "ser_ot_games_pre", "ser_elim_pre", "ser_lag_result_pre", "ser_ot_p_hist_pre", "ser_ot_rho_pre", "ser_ot_nseries_pre", "ser_state_factor_pre", "ser_state_n_pre", "ser_lag_coef_pre", "ser_lag_se_pre"):
        t[c] = t[["game_id", "team"]].merge(base[["game_id", "team", c]].drop_duplicates(["game_id", "team"]), on=["game_id", "team"], how="left")[c].to_numpy()


def compute(raw: dict) -> dict:
    t = _rows(raw)
    _loser_point(t); _attempts(t, raw); _kalman(t, raw); _series(t)
    cols = [c for s in specs() for c in s.columns]
    out = t[["game_id", "team", "date", "season"] + cols].copy()
    return {"team": out.loc[:, ~out.columns.duplicated()]}


def specs() -> list[FeatureSpec]:
    F = lambda cid, cols, lvl, d, done, miss, raw=("nhl_games",): FeatureSpec(S, cid, "team", cols, lvl, d, done, miss, list(raw), "pregame_rolling")
    return [
        F("nhl.loser_point_rate", ["lp_beyond_pre", "lp_win_extra_pre", "lp_reg_win_pre", "lp_pts_pg_pre", "lp_reg_wins_season_pre", "lp_row_season_pre"], "FULL",
          "regular-season P(beyond regulation) shrunk to the league rate (k=30), P(win | beyond) shrunk to 0.5 (k=40), regulation win rate, points per game = 2*Preg + 2*Pextra*pwin + Pextra*(1-pwin), season-to-date regulation wins and ROW; 2-season weights: current season 1.0, previous season 0.5; defined from >=10 weighted games",
          ["all listed rates", "points formula", "RW and ROW tiebreak counts", "2-season weights"], []),
        F("nhl.pair_attempt_volume", ["att_off60_pre", "att_def60_pre", "att_exp_att60_pre", "att_proj_5v5_min_pre", "att_exp_game_att_pre"], "PARTIAL",
          "5v5 shot attempts per 60 for/against (EWMA over earlier dates, 2-season half-life), additive league + offence + opponent-defence + half home adjustment, projected 5v5 minutes = 60 - expected special-teams minutes, expected game attempts",
          ["offence/defence attempts per 60", "home effect", "projected 5v5 minutes", "game attempts"], ["Poisson regression with ridge", "score-state adjustment", "pair random effect", "pace-weighted xG conversion"], ("nhl_games", "moneypuck_team_games")),
        F("nhl.rating_posterior_uncertainty", ["kf_rating_mean_pre", "kf_rating_sd_pre"], "PARTIAL",
          "Kalman local-level rating per team (drift sd 0.02 goals/game per game, preseason prior sd 0.25, season rollover halves the mean), observation = MoneyPuck score-venue-adjusted xG differential (all situations) with the opponent's pre-game mean added back, measurement variance from the running residual variance",
          ["posterior mean and sd per team per game", "drift 0.02", "preseason prior sd 0.25"], ["goal-differential second observation", "out-of-sample estimation of drift variance and re-estimation each season", "joint (non-diagonal) filter", "simulation draws"], ("nhl_games", "moneypuck_team_games")),
        F("nhl.series_ot_count_dependence", ["ser_ot_games_pre", "ser_ot_p_hist_pre", "ser_ot_rho_pre", "ser_ot_nseries_pre"], "PARTIAL",
          "playoff series: OT games so far, historical OT-game share, beta-binomial overdispersion rho by moment estimate over series completed before the game date, shrunk to 0.05 with k=40 series",
          ["series reconstruction", "OT counts", "rho with prior 0.05 k=40"], ["pregame tie probability from reg_tie_model", "series-length conditioning pmf"]),
        F("nhl.series_state_scoring_shift", ["ser_state_factor_pre", "ser_state_n_pre", "ser_wins_pre", "ser_opp_wins_pre", "ser_elim_pre"], "PARTIAL",
          "series score entering the game and elimination flag; multiplicative total-goals factor for that state = shrunk (k=15) state mean over earlier playoff games / pooled mean",
          ["state tagging", "elimination flag", "shrunk multiplicative factor"], ["regression on team rating-implied mean and venue", "team random effect", "standard errors"]),
        F("nhl.series_game_dependence", ["ser_lag_result_pre", "ser_lag_coef_pre", "ser_lag_se_pre"], "PARTIAL",
          "lag-result of the previous series game from the team's view and the ridge-logit lag coefficient (prior sd 0.15) fitted on playoff games of strictly earlier seasons with intercept and regular-season goal-differential gap",
          ["lag coefficient via ridge logit", "series score", "lagged result"], ["integration over the series-level rating posterior", "rating-implied log-odds from the Kalman rating", "predicted game-7/sweep share check"]),
    ]
