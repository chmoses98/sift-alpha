"""College basketball team-game builders from public ESPN box scores (RESEARCH_ONLY): opponent-adjusted efficiency ratings, adjusted tempo, rating uncertainty, regulation-tie / OT-chain rates,
blowout and starter-minute-reduction rates.

Raw data: sportsdataverse-data release assets (ESPN men's college basketball team box scores, schedules with period line scores, player box scores), collected by `college_collect.py`. These are the
same free bulk assets the owner's cbb-edge-finder uses; no CBBD/KenPom/Torvik access, no line, spread or price anywhere. Upstream licence terms are not stated (internal research use only).

Output table ``team`` keyed (game_id, team): every value for game G is computed from games on STRICTLY EARLIER DATES only (daily batches), never the game's own result.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec, prior_ewm

S = "CBB"
TB_COLS = ["game_id", "season", "season_type", "game_date", "team_id", "team_score", "opponent_team_id", "opponent_team_score", "field_goals_attempted", "free_throws_attempted", "offensive_rebounds", "turnovers"]
SC_COLS = ["game_id", "season", "season_type", "game_date", "neutral_site", "home_id", "away_id", "home_score", "away_score", "status_period", "status_type_completed"]
PB_COLS = ["game_id", "team_id", "minutes", "starter", "did_not_play"]
TB_CONTENT = ["team_score", "opponent_team_score", "field_goals_attempted", "free_throws_attempted", "offensive_rebounds", "turnovers"]
SC_CONTENT = ["home_score", "away_score", "status_period"]
PB_CONTENT = ["minutes", "starter", "did_not_play"]

HALF_LIFE_DAYS = 30.0
LAMBDA = 8.0          # prior weight (in weighted games) of the team offence / defence / tempo effects, and of the home-court term
LAMBDA_MU = 1.0       # prior weight of the league mean terms
RHO = 0.7             # fraction of a team's previous-season final effect carried as the prior mean
MU_EFF0, MU_TEMPO0 = 100.0, 68.0
SIGMA2_NONE = 225.0   # residual variance used before any training game exists
OT_LOOKBACK_DAYS = 3650
OT_PRIOR, OT_K = 0.25, 30.0


def load_raw(d) -> dict:
    d = Path(d) / "cbb"
    cat = lambda stem, cols: pd.concat([pd.read_parquet(f, columns=cols) for f in sorted(d.glob(f"{stem}_*.parquet"))], ignore_index=True)
    return {"team_box": cat("team_box", TB_COLS), "schedule": cat("schedule", SC_COLS), "player_box": cat("player_box", PB_COLS)}


def _games(raw: dict) -> pd.DataFrame:
    """One row per completed regular/postseason game with a complete box for BOTH teams."""
    sc = raw["schedule"]; sc = sc[(sc.status_type_completed == True) & sc.season_type.isin([2, 3])].copy()   # noqa: E712
    sc["n_per"] = sc.status_period.fillna(0).astype(int)   # ESPN status period at the final whistle: 2 + number of overtimes
    sc = sc[sc.n_per >= 2].drop_duplicates("game_id")
    tb = raw["team_box"].dropna(subset=["team_score", "opponent_team_score", "field_goals_attempted", "free_throws_attempted", "offensive_rebounds", "turnovers"]).copy()
    tb["poss"] = tb.field_goals_attempted + 0.44 * tb.free_throws_attempted - tb.offensive_rebounds + tb.turnovers
    tb = tb.drop_duplicates(["game_id", "team_id"]); n = tb.groupby("game_id").team_id.transform("size"); tb = tb[n == 2]
    gp = tb.groupby("game_id").poss.mean().rename("poss_game")
    sc = sc.merge(gp, left_on="game_id", right_index=True)
    sc = sc[sc.poss_game >= 40]
    sc["date"] = pd.to_datetime(sc.game_date)
    rows = []
    for me, op, home in (("home_id", "away_id", 1), ("away_id", "home_id", -1)):
        t = sc[["game_id", "season", "date", "neutral_site", "n_per", "poss_game", me, op]].rename(columns={me: "team", op: "opp"})
        t["hv"] = np.where(t.neutral_site.fillna(False).astype(bool), 0, home); rows.append(t)
    t = pd.concat(rows, ignore_index=True)
    sco = tb[["game_id", "team_id", "team_score", "opponent_team_score"]].rename(columns={"team_id": "team", "team_score": "pts", "opponent_team_score": "opp_pts"})
    t["team"] = t.team.astype("int64"); sco["team"] = sco.team.astype("int64")
    t = t.merge(sco, on=["game_id", "team"], how="inner"); n = t.groupby("game_id").team.transform("size"); t = t[n == 2].copy()
    t["opp"] = t.opp.astype("int64"); t["team"] = t.team.astype("int64")
    t["n_ot"] = t.n_per - 2; mins = 40 + 5 * t.n_ot
    t["eff_for"] = 100 * t.pts / t.poss_game; t["eff_against"] = 100 * t.opp_pts / t.poss_game; t["poss40"] = t.poss_game * 40 / mins
    t["margin"] = t.pts - t.opp_pts
    return t.sort_values(["date", "game_id", "hv", "team"], ascending=[True, True, False, True], kind="mergesort").reset_index(drop=True)


def _ridge_state(dim: int) -> dict:
    return {"S": np.zeros((dim, dim)), "b": np.zeros(dim), "yy": 0.0, "sw": 0.0}


def _decay(st: dict, f: float) -> None:
    st["S"] *= f; st["b"] *= f; st["yy"] *= f; st["sw"] *= f


def _add(st: dict, idx: np.ndarray, val: np.ndarray, y: np.ndarray) -> None:
    """idx (n,k) parameter indices, val (n,k) design values, y (n,) responses; weight 1 (decay is applied to the whole state)."""
    np.add.at(st["S"], (idx[:, :, None], idx[:, None, :]), val[:, :, None] * val[:, None, :])
    np.add.at(st["b"], idx, val * y[:, None]); st["yy"] += float((y * y).sum()); st["sw"] += float(len(y))


def _solve(st: dict, prior: np.ndarray, pen: np.ndarray, extra_cols=None) -> tuple[np.ndarray, np.ndarray | None, float]:
    """theta = (S + diag(pen))^-1 (b + pen*prior). With extra_cols (team indices) the second return value holds the inverse columns [o_t, d_t] for those teams (2 columns per team), else None."""
    A = st["S"] + np.diag(pen); rhs = st["b"] + pen * prior; T = (len(pen) - 2) // 2
    if extra_cols is not None:
        E = np.zeros((len(pen), 2 * len(extra_cols)))
        for k, i in enumerate(extra_cols): E[2 + i, 2 * k] = 1; E[2 + T + i, 2 * k + 1] = 1
        X = np.linalg.solve(A, np.column_stack([rhs, E])); theta, inv_cols = X[:, 0], X[:, 1:]
    else:
        theta = np.linalg.solve(A, rhs); inv_cols = None
    ssr = st["yy"] - 2 * float(theta @ st["b"]) + float(theta @ st["S"] @ theta)
    s2 = max(ssr, 0.0) / st["sw"] if st["sw"] > 0 else SIGMA2_NONE
    return theta, inv_cols, s2


def _season_fit(g: pd.DataFrame, prev: dict | None, major: set | None) -> tuple[pd.DataFrame, dict]:
    """Walk-forward ridge fits for one season. Returns per-row pre-game values and the final state (the prior for the next season).
    `major` = teams with an individual effect (>= 12 games in either of the two previous seasons: known before the season starts); every other team shares one pooled "other" effect (last index).
    The very first season in the data has no previous seasons: it uses its own >= 12-game teams, only seeds the priors, and its rows are emitted as NaN."""
    ids = sorted(major & (set(g.team) | set(g.opp)))
    T = len(ids) + 1; pos = {t: i for i, t in enumerate(ids)}; OTHER = len(ids)
    # efficiency parameters: [mu, h, o_1..o_T, d_1..d_T]; tempo parameters: [mu_t, a_1..a_T]
    pe = np.zeros(2 + 2 * T); pe[0] = MU_EFF0; pt = np.zeros(1 + T); pt[0] = MU_TEMPO0
    has_prior = prev is not None
    if has_prior:
        pe[0] = prev["mu"]; pe[1] = prev["h"]; pt[0] = prev["mu_t"]
        for t, i in pos.items():
            if t in prev["o"]: pe[2 + i] = RHO * prev["o"][t]; pe[2 + T + i] = RHO * prev["d"][t]; pt[1 + i] = RHO * prev["a"][t]
        if "OTHER" in prev["o"]: pe[2 + OTHER] = RHO * prev["o"]["OTHER"]; pe[2 + T + OTHER] = RHO * prev["d"]["OTHER"]; pt[1 + OTHER] = RHO * prev["a"]["OTHER"]
    pen_e = np.full(2 + 2 * T, LAMBDA); pen_e[0] = LAMBDA_MU; pen_t = np.full(1 + T, LAMBDA); pen_t[0] = LAMBDA_MU
    se, st_ = _ridge_state(2 + 2 * T), _ridge_state(1 + T)
    ge = g.assign(ti=g.team.map(pos).fillna(OTHER).astype(int), oi=g.opp.map(pos).fillna(OTHER).astype(int))
    dates = sorted(ge.date.unique()); out = []; last = None
    for d in dates:
        if last is not None:
            f = 0.5 ** ((d - last).days / HALF_LIFE_DAYS); _decay(se, f); _decay(st_, f)
        day = ge[ge.date == d]
        empty = se["sw"] == 0 and not has_prior
        ti, oi = day.ti.to_numpy(), day.oi.to_numpy()
        th, A, s2 = _solve(se, pe, pen_e, extra_cols=np.unique(ti)); tt, _, _ = _solve(st_, pt, pen_t)
        o, dd = th[2:2 + T], th[2 + T:]; em = o - dd
        # posterior sd of the adjusted efficiency margin o_t - d_t = sqrt(s2 * (Ainv[o,o] + Ainv[d,d] - 2 Ainv[o,d]))
        Ainv_cols = A   # (A holds the solved inverse columns for the day's teams; see _solve)
        sd = np.full(T, np.nan)
        for k, i in enumerate(np.unique(ti)):
            c_o, c_d = Ainv_cols[:, 2 * k], Ainv_cols[:, 2 * k + 1]
            sd[i] = math.sqrt(max(s2 * (c_o[2 + i] + c_d[2 + T + i] - c_o[2 + T + i] - c_d[2 + i]), 0.0))
        exp_poss = tt[0] + tt[1 + ti] + tt[1 + oi]
        pm = ((em[ti] - em[oi]) + 2 * th[1] * day.hv.to_numpy()) * exp_poss / 100.0
        res = pd.DataFrame({"game_id": day.game_id.to_numpy(), "team": day.team.to_numpy(), "rf_off_pre": th[0] + o[ti], "rf_def_pre": th[0] + dd[ti], "rf_adjem_pre": em[ti], "rf_hca_pre": th[1],
                            "rf_pred_margin_pre": pm, "tp_adj_pre": tt[0] + tt[1 + ti], "tp_exp_poss_pre": exp_poss, "ru_sd_pre": sd[ti], "ru_sd_pair_pre": np.sqrt(sd[ti] ** 2 + sd[oi] ** 2)})
        if empty:
            res[[c for c in res.columns if c.endswith("_pre")]] = np.nan
        out.append(res)
        # add this date's games (both sides) to the training state
        hv = day.hv.to_numpy().astype(float)
        idx = np.stack([np.zeros(len(day), int), np.ones(len(day), int), 2 + ti, 2 + T + oi], 1); val = np.stack([np.ones(len(day)), hv, np.ones(len(day)), np.ones(len(day))], 1)
        _add(se, idx, val, day.eff_for.to_numpy())
        # (the opponent row of the same game is part of `day` and adds the other side's observation)
        pairs = day.drop_duplicates("game_id")   # one tempo observation per game
        idt = np.stack([np.zeros(len(pairs), int), 1 + pairs.ti.to_numpy(), 1 + pairs.oi.to_numpy()], 1); _add(st_, idt, np.ones((len(pairs), 3)), pairs.poss40.to_numpy())
        last = d
    # final state as of the day after the season's last date
    f = 0.5 ** (1 / HALF_LIFE_DAYS); _decay(se, f); _decay(st_, f)
    th, _, _ = _solve(se, pe, pen_e); tt, _, _ = _solve(st_, pt, pen_t)
    fin = {"mu": th[0], "h": th[1], "mu_t": tt[0], "o": {t: th[2 + i] for t, i in {**pos, "OTHER": OTHER}.items()}, "d": {t: th[2 + T + i] for t, i in {**pos, "OTHER": OTHER}.items()}, "a": {t: tt[1 + i] for t, i in {**pos, "OTHER": OTHER}.items()}}
    return pd.concat(out, ignore_index=True), fin


def _phi(z: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.vectorize(math.erf)(z / math.sqrt(2.0)))


def compute(raw: dict) -> dict:
    t = _games(raw); parts = []; prev = None; seasons = sorted(t.season.unique()); cnt = {s: t[t.season == s].team.value_counts() for s in seasons}
    for k, s in enumerate(seasons):
        major = {tm for q in (seasons[max(0, k - 2):k] or [s]) for tm, c in cnt[q].items() if c >= 12}
        r, prev = _season_fit(t[t.season == s], prev, major)
        if k == 0: r[[c for c in r.columns if c.endswith("_pre")]] = np.nan
        parts.append(r)
    t = t.merge(pd.concat(parts, ignore_index=True), on=["game_id", "team"], how="left")
    t = t.sort_values(["date", "game_id", "hv", "team"], ascending=[True, True, False, True], kind="mergesort").reset_index(drop=True)
    t["tp_raw_ewm_pre"] = prior_ewm(t, "team", "poss40", hl=8, min_periods=3)
    # regulation-tie probability and OT chain
    m = t.rf_pred_margin_pre.to_numpy(); sd = np.sqrt(t.tp_exp_poss_pre.to_numpy() / 68.0) * 10.5
    t["ot_p_tie_reg_pre"] = _phi((0.5 - m) / sd) - _phi((-0.5 - m) / sd)
    gm = t.drop_duplicates("game_id").sort_values(["date", "game_id"])
    day = gm.assign(ot=(gm.n_ot > 0).astype(float), tied=np.where(gm.n_ot > 0, gm.n_ot - 1, 0).astype(float), per=gm.n_ot.astype(float)).groupby("date")[["tied", "per"]].sum().sort_index()
    cs_t = day.tied.cumsum().to_numpy(); cs_p = day.per.cumsum().to_numpy(); dd = day.index.to_numpy("datetime64[D]")
    hi = np.searchsorted(dd, dd, side="left"); lo = np.searchsorted(dd, dd - np.timedelta64(OT_LOOKBACK_DAYS, "D"), side="left")
    cum = lambda c, i: np.where(i > 0, c[np.maximum(i - 1, 0)], 0.0)
    tied = cum(cs_t, hi) - cum(cs_t, lo); per = cum(cs_p, hi) - cum(cs_p, lo)
    rate = pd.Series((tied + OT_PRIOR * OT_K) / (per + OT_K), index=day.index, name="ot_p_tie_ot_pre")
    t = t.merge(rate, left_on="date", right_index=True, how="left")
    t["ot_p_2plus_pre"] = t.ot_p_tie_reg_pre * t.ot_p_tie_ot_pre
    # blowout rates and starter-minute reduction
    for th_ in (15, 20, 25):
        t[f"_b{th_}"] = (t.margin.abs() > th_).astype(float); t[f"bg_p{th_}_pre"] = prior_ewm(t, "team", f"_b{th_}", hl=15, min_periods=5)
    opp = t[["game_id", "team", "bg_p20_pre"]].rename(columns={"team": "opp", "bg_p20_pre": "opp_bg_p20_pre"})
    t = t.merge(opp, on=["game_id", "opp"], how="left"); t["bg_pair_p20_pre"] = (t.bg_p20_pre + t.opp_bg_p20_pre) / 2
    pb = raw["player_box"]; pb = pb[(pb.starter == True) & (pb.did_not_play != True)].copy()   # noqa: E712
    pb["team"] = pb.team_id.astype("int64"); sm = pb.groupby(["game_id", "team"]).minutes.sum().rename("starter_min").reset_index()
    t = t.merge(sm, on=["game_id", "team"], how="left")
    close = (t.margin.abs() < 10) & t.starter_min.notna(); blow = (t.margin.abs() >= 20) & t.starter_min.notna()
    for nm, mask, mn in (("close", close, 5), ("blow", blow, 3)):
        t[f"_v_{nm}"] = np.where(mask, t.starter_min, 0.0); t[f"_c_{nm}"] = mask.astype(float)
        sv = t.groupby("team", sort=False)[f"_v_{nm}"].transform(lambda s: s.shift(1).rolling(60, min_periods=1).sum()); sc_ = t.groupby("team", sort=False)[f"_c_{nm}"].transform(lambda s: s.shift(1).rolling(60, min_periods=1).sum())
        t[f"bg_starter_{nm}_pre"] = np.where(sc_ >= mn, sv / sc_.replace(0, np.nan), np.nan)
    t["bg_starter_drop_pre"] = t.bg_starter_close_pre - t.bg_starter_blow_pre
    keep = ["game_id", "team", "date", "season"] + [c for s in specs() for c in s.columns]
    return {"team": t[list(dict.fromkeys(keep))]}


def specs() -> list[FeatureSpec]:
    F = lambda cid, cols, lvl, d, done, miss, raw=("espn_mbb_team_box", "espn_mbb_schedule"): FeatureSpec(S, cid, "team", cols, lvl, d, done, miss, list(raw), "pregame_rolling")
    return [
        F("cbb.ratings_fundamentals", ["rf_off_pre", "rf_def_pre", "rf_adjem_pre", "rf_hca_pre", "rf_pred_margin_pre"], "PARTIAL",
          "AdjEM_own only: walk-forward ridge of points per 100 possessions (poss = FGA + 0.44 FTA - OREB + TOV, game possessions = mean of both teams) on opponent offence/defence effects plus a home-court term, half-life 30 days, prior weight 8 games, prior mean = 0.7 x previous-season final effect; predicted margin = (AdjEM_A - AdjEM_B + 2 x home term x venue sign) x expected possessions / 100",
          ["own ridge rating with opponent and home-court terms", "exponential time decay half-life 30 days", "prior weight of 8 games", "predicted margin from expected possessions", "strictly earlier dates only"],
          ["Torvik / KenPom components and the fitted blend weights (not in hand, licence-restricted)", "returning-minutes-weighted preseason prior (previous-season rating times 0.7 is a stand-in)", "no garbage-time filter"]),
        F("cbb.tempo", ["tp_adj_pre", "tp_exp_poss_pre", "tp_raw_ewm_pre"], "PARTIAL",
          "opponent-adjusted possessions per 40 minutes (ridge tempo effects, half-life 30 days, prior weight 8, carried 0.7 from the previous season), expected game pace = league + (A - league) + (B - league), plus the team's raw EWMA (half-life 8 games) of possessions per 40",
          ["adjusted possessions per 40 via opponent-adjusted regression", "expected game pace = league + (A-league) + (B-league)"], ["tempo-control adjustment for the team that wants to slow", "garbage-time filter"]),
        F("cbb.rating_uncertainty", ["ru_sd_pre", "ru_sd_pair_pre"], "PARTIAL",
          "posterior standard deviation of the adjusted efficiency margin from the ridge normal equations (residual variance times the inverse penalised information), and the pair sd sqrt(sd_A^2 + sd_B^2)",
          ["posterior sd per team", "pair sd"], ["bootstrap alternative", "games played / effective opponent-link counts as separate features (structural, not content-dependent)", "roster-change magnitude", "downweighting of model edge by sd (a model step)"]),
        F("cbb.ot_period_tie_chain", ["ot_p_tie_reg_pre", "ot_p_tie_ot_pre", "ot_p_2plus_pre"], "PARTIAL",
          "P(regulation tie) = normal mass in (-0.5, 0.5) around the model expected margin with sd = sqrt(expected possessions / 68) x 10.5; P(tied after an OT period) = pooled empirical rate over the earlier 10 years shrunk to 0.25 with k = 30 OT periods; P(2+ OT) = product",
          ["integer pmf at margin 0 from a normal margin distribution", "empirical tied-after-OT rate over the last 10 seasons, shrunk by count", "P(N+ periods) = P_tie_reg x P_tie_OT^(N-1) for N = 2"],
          ["discrete correction for tie clustering at low margins", "free-throw-rate multiplier on the OT tie rate", "extra points per OT period mean/sd", "P(N+) for N > 2"]),
        F("cbb.blowout_garbage", ["bg_p15_pre", "bg_p20_pre", "bg_p25_pre", "bg_pair_p20_pre", "bg_starter_close_pre", "bg_starter_blow_pre", "bg_starter_drop_pre"], "PARTIAL",
          "team EWMA (half-life 15 games) of P(|margin| > 15/20/25), pair mean for 20, and the team's mean starter minutes (sum of starters' minutes) in close (<10) vs blowout (>=20) games over its last 60 games (>=5 / >=3 qualifying games), and their difference",
          ["P(|margin| > 15/20/25) per team", "coach-specific starter-minute behaviour by margin from historical minutes", "expected starter minute reduction"], ["probabilities conditioned on the spread (needs a line: excluded)", "per-coach identity"],
          ("espn_mbb_team_box", "espn_mbb_schedule", "espn_mbb_player_box")),
    ]
