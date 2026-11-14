"""Tennis feature builders from Jeff Sackmann's ATP/WTA match files (snapshot kept in Tennis-Edge-Finder), 2000-2026 (RESEARCH_ONLY). One row per PLAYER-match; every column is a
pre-match value computed from that player's earlier matches (ordered by tournament date, tournament id, match number) or from static pre-match attributes (ranking at match time, age, hand, height).
Not available in the raw data (so not computed): serve speed, court speed/altitude/weather, withdrawals, order of play, positions of points, tournament country."""
from __future__ import annotations

import glob
import re

import numpy as np
import pandas as pd

from .core import FeatureSpec, Paths, pair_rows, prior_count, prior_date_mean, prior_ewm, prior_mean

S = "TENNIS"
SET = re.compile(r"(\d+)-(\d+)(?:\((\d+)\))?")
ROUND = {"R128": 2, "R64": 3, "R32": 4, "R16": 5, "QF": 6, "SF": 7, "F": 8, "RR": 1, "BR": 7}


def load_raw(p: Paths) -> dict:
    out = {}
    for tour in ("atp", "wta"):
        fs = sorted(glob.glob(str(p.raw / f"tennis/{tour}_matches_*.csv.gz")))
        out[tour] = pd.concat([pd.read_csv(f, low_memory=False).assign(tour=tour) for f in fs], ignore_index=True)
    return out


def _sets(score):
    if not isinstance(score, str):
        return None
    return [(int(a), int(b)) for a, b, _ in SET.findall(score)]


def _long(raw: dict) -> pd.DataFrame:
    d = pd.concat(raw.values(), ignore_index=True)
    d["date"] = pd.to_datetime(d.tourney_date.astype(str), format="%Y%m%d", errors="coerce")
    d = d.dropna(subset=["date", "winner_id", "loser_id"]).copy()
    d["match_id"] = d.tour + "|" + d.tourney_id.astype(str) + "|" + d.match_num.astype(str)
    # Sackmann files list each tournament FINAL-FIRST (descending match_num), so file order is anti-chronological inside a tournament; chronological order = round, then match_num
    d["ord"] = d["round"].map(ROUND).fillna(4) * 100000 + pd.to_numeric(d.match_num, errors="coerce").fillna(0)
    sets = d.score.map(_sets)
    d["n_sets"] = sets.map(lambda s: len(s) if s else np.nan)
    d["games"] = sets.map(lambda s: sum(a + b for a, b in s) if s else np.nan)
    d["tb_sets"] = sets.map(lambda s: sum(1 for a, b in s if {a, b} == {6, 7}) if s else np.nan)
    d["lopsided_sets"] = sets.map(lambda s: sum(1 for a, b in s if min(a, b) <= 1 and max(a, b) >= 6) if s else np.nan)
    d["ret"] = d.score.astype(str).str.contains("RET|DEF|ABD", regex=True).astype(float)
    d["decider"] = (d.n_sets == d.best_of.where(d.best_of.isin([3, 5]))).astype(float).where(d.n_sets.notna())
    rows = []
    stat = ["ace", "df", "svpt", "1stIn", "1stWon", "2ndWon", "SvGms", "bpSaved", "bpFaced"]
    for side, me, op in (("w", "winner", "loser"), ("l", "loser", "winner")):
        t = pd.DataFrame({"match_id": d.match_id, "tour": d.tour, "date": d.date, "ord": d.ord, "season": d.date.dt.year, "surface": d.surface, "level": d.tourney_level, "round": d["round"], "best_of": d.best_of, "draw_size": d.draw_size,
                          "pid": d[f"{me}_id"], "opp": d[f"{op}_id"], "won": 1.0 if side == "w" else 0.0, "rank": d[f"{me}_rank"], "rank_pts": d[f"{me}_rank_points"], "opp_rank": d[f"{op}_rank"], "age": d[f"{me}_age"], "ht": d[f"{me}_ht"],
                          "hand": d[f"{me}_hand"], "opp_hand": d[f"{op}_hand"], "seed": d[f"{me}_seed"], "entry": d[f"{me}_entry"], "minutes": d.minutes, "n_sets": d.n_sets, "games": d.games, "tb_sets": d.tb_sets, "lopsided": d.lopsided_sets,
                          "ret": d.ret, "decider": d.decider, "tourney_id": d.tourney_id})
        for s in stat:
            t[s] = d[f"{side}_{s}"].to_numpy()
            t[f"o_{s}"] = d[f"{'l' if side == 'w' else 'w'}_{s}"].to_numpy()
        rows.append(t)
    p = pd.concat(rows, ignore_index=True)
    return p.sort_values(["date", "tour", "tourney_id", "ord", "pid"], kind="mergesort").reset_index(drop=True)


def _elo(p: pd.DataFrame) -> pd.DataFrame:
    """Own Elo (overall and per-surface) computed match by match in chronological order; the value stored on a row is BEFORE the match. Pairs are processed once per match."""
    elo, selo = {}, {}
    pre_o, pre_s = np.full(len(p), np.nan), np.full(len(p), np.nan)
    first = p.groupby("match_id", sort=False).head(1)
    idx = {m: [] for m in first.match_id}
    for i, m in enumerate(p.match_id.to_numpy()):
        idx[m].append(i)
    for m in first.match_id:
        ii = idx[m]
        if len(ii) != 2:
            continue
        a, b = ii
        pa, pb = p.pid.iat[a], p.pid.iat[b]
        sf = p.surface.iat[a] if isinstance(p.surface.iat[a], str) else "Hard"
        ea, eb = elo.get(pa, 1500.0), elo.get(pb, 1500.0)
        sa, sb = selo.get((pa, sf), ea), selo.get((pb, sf), eb)
        pre_o[a], pre_o[b] = ea, eb
        pre_s[a], pre_s[b] = sa, sb
        y = p.won.iat[a]
        ex = 1 / (1 + 10 ** (-(ea - eb) / 400)); exs = 1 / (1 + 10 ** (-(sa - sb) / 400))
        elo[pa] = ea + 24 * (y - ex); elo[pb] = eb - 24 * (y - ex)
        selo[(pa, sf)] = sa + 24 * (y - exs); selo[(pb, sf)] = sb - 24 * (y - exs)
    p["elo_pre"], p["surface_elo_pre"] = pre_o, pre_s
    return p


def compute(raw: dict) -> dict:
    p = _elo(_long(raw))
    p["spw"] = (p["1stWon"] + p["2ndWon"]) / p.svpt.replace(0, np.nan)
    p["rpw"] = 1 - (p.o_1stWon + p.o_2ndWon) / p.o_svpt.replace(0, np.nan)
    p["ace_rate"], p["df_rate"] = p.ace / p.svpt.replace(0, np.nan), p.df / p.svpt.replace(0, np.nan)
    p["first_in"] = p["1stIn"] / p.svpt.replace(0, np.nan); p["first_won"] = p["1stWon"] / p["1stIn"].replace(0, np.nan)
    p["second_won"] = p["2ndWon"] / (p.svpt - p["1stIn"]).replace(0, np.nan)
    p["ace_alw"] = p.o_ace / p.o_svpt.replace(0, np.nan)
    p["bp_save"] = p.bpSaved / p.bpFaced.replace(0, np.nan); p["bp_conv"] = (p.o_bpFaced - p.o_bpSaved) / p.o_bpFaced.replace(0, np.nan)
    p["hold_est"] = 1 - (p.o_bpFaced - p.o_bpSaved) / p.SvGms.replace(0, np.nan); p["break_est"] = (p.bpFaced - p.bpSaved) / p.o_SvGms.replace(0, np.nan)
    p["tb_share"] = p.tb_sets / p.n_sets.replace(0, np.nan); p["lopsided_share"] = p.lopsided / p.n_sets.replace(0, np.nan)
    p["games_per_set"] = p.games / p.n_sets.replace(0, np.nan)
    p["dec_win"] = np.where(p.decider == 1, p.won, np.nan)
    p["ret_by_me"] = np.where(p.won == 0, p.ret, 0.0)
    base = ["spw", "rpw", "ace_rate", "df_rate", "first_in", "first_won", "second_won", "ace_alw", "bp_save", "bp_conv", "hold_est", "break_est", "tb_share", "lopsided_share", "games_per_set", "n_sets", "minutes", "ret_by_me", "decider", "won"]
    for c in base:
        p[f"{c}_pre"] = prior_ewm(p, "pid", c, hl=20, min_periods=5)
    p["dec_win_pre"] = prior_ewm(p, "pid", "dec_win", hl=40, min_periods=3)
    for c in ("spw", "rpw", "ace_rate"):
        p[f"{c}_surf_pre"] = prior_ewm(p, ["pid", "surface"], c, hl=20, min_periods=5)
    p["n_pre"] = prior_count(p, "pid"); p["n_surface_pre"] = prior_count(p, ["pid", "surface"])
    p["days_since_prev"] = p.groupby("pid", sort=False)["date"].transform(lambda s: (s - s.shift(1)).dt.days)
    p["layoff_days_pre"] = p.days_since_prev.clip(upper=365)
    p["days_since_surface"] = p.groupby(["pid", "surface"], sort=False)["date"].transform(lambda s: (s - s.shift(1)).dt.days).clip(upper=720)
    p["minutes_last3_pre"] = p.groupby("pid", sort=False)["minutes"].transform(lambda s: s.shift(1).rolling(3, min_periods=1).sum())
    p["matches_last14d_pre"] = 0.0
    for _, idx in p.groupby("pid", sort=False).groups.items():
        d = p.loc[idx, "date"].to_numpy("datetime64[D]"); lo = np.searchsorted(d, d - np.timedelta64(14, "D"), side="left")
        p.loc[idx, "matches_last14d_pre"] = np.arange(len(d)) - lo
    p["first_in_sd_pre"] = p.groupby("pid", sort=False)["first_in"].transform(lambda s: s.shift(1).rolling(20, min_periods=8).std())
    p["ace_var_pre"] = (prior_ewm(p.assign(_s=p.ace ** 2), "pid", "_s", hl=20) - prior_ewm(p, "pid", "ace", hl=20) ** 2)
    p["bp_save_dev_pre"] = prior_ewm(p, "pid", "bp_save", hl=5, min_periods=3) - p.bp_save_pre
    p["bp_conv_dev_pre"] = prior_ewm(p, "pid", "bp_conv", hl=5, min_periods=3) - p.bp_conv_pre
    p["age_sq"] = p.age ** 2
    p["round_idx"] = p["round"].map(ROUND)
    p["is_left"] = (p.hand == "L").astype(float).where(p.hand.isin(["L", "R"])); p["opp_is_left"] = (p.opp_hand == "L").astype(float).where(p.opp_hand.isin(["L", "R"]))
    p["qualifier"] = p.entry.isin(["Q", "LL"]).astype(float); p["seeded"] = p.seed.notna().astype(float)
    p["rank_log"], p["rank_diff_log"] = np.log(p["rank"]), np.log(p["rank"]) - np.log(p.opp_rank)
    p["best_of5"] = (p.best_of == 5).astype(float); p["tour_wta"] = (p.tour == "wta").astype(float)
    for s_ in ("Clay", "Grass", "Hard"):
        p[f"surf_{s_.lower()}"] = (p.surface == s_).astype(float)
    # head-to-head: wins of this player over this opponent in EARLIER matches
    p["pair"] = np.where(p.pid < p.opp, p.pid.astype(str) + "-" + p.opp.astype(str), p.opp.astype(str) + "-" + p.pid.astype(str))
    p["h2h_n_pre"] = p.groupby(["pair"], sort=False).cumcount() // 1
    p["h2h_n_pre"] = p.groupby("pair", sort=False)["match_id"].transform(lambda s: s.map(lambda m: 0)).add(p.groupby(["pair", "pid"], sort=False).cumcount() * 0)  # placeholder, replaced below
    first = p.drop_duplicates("match_id")[["match_id", "pair", "date"]].reset_index(drop=True)
    seen = first.groupby("pair", sort=False).cumcount()
    p = p.merge(first.assign(h2h_n_pre2=seen.values)[["match_id", "h2h_n_pre2"]], on="match_id", how="left")
    p["h2h_n_pre"] = p.h2h_n_pre2; p = p.drop(columns="h2h_n_pre2")
    p["h2h_wins_pre"] = p.groupby(["pair", "pid"], sort=False)["won"].transform(lambda s: s.shift(1).fillna(0).cumsum()) if False else np.nan
    w = p[["match_id", "pid", "pair", "won"]].copy(); w["w1"] = w.won
    cum = w.groupby(["pair", "pid"], sort=False)["w1"].transform(lambda s: s.shift(1).fillna(0).cumsum())
    # a player's cumulative wins vs this opponent counts only matches already played because rows are chronological
    p["h2h_wins_pre"] = cum.to_numpy()
    p["h2h_share_pre"] = p.h2h_wins_pre / p.h2h_n_pre.replace(0, np.nan)
    p = pair_rows(p.rename(columns={"pid": "team"}), game="match_id", team="team", cols=["ace_alw_pre", "ace_rate_pre", "spw_pre", "rpw_pre", "n_pre", "elo_pre", "games_per_set_pre", "tb_share_pre"]).rename(columns={"team": "pid"})
    lg_ace = prior_date_mean(p, "date", "ace_rate")
    p["exp_ace_rate_pre"] = lg_ace + (p.ace_rate_pre - lg_ace) + (p.opp_ace_alw_pre - lg_ace)
    p["exp_spw_pre"] = prior_date_mean(p, "date", "spw") + (p.spw_pre - prior_date_mean(p, "date", "spw")) - (p.opp_rpw_pre - prior_date_mean(p, "date", "rpw"))
    p["elo_gap_pre"] = p.elo_pre - p.opp_elo_pre
    p["exp_games_per_set_pre"] = (p.games_per_set_pre + p.opp_games_per_set_pre) / 2
    p["tb_reach_pre"] = (p.tb_share_pre + p.opp_tb_share_pre) / 2
    return {"player": p}


def specs() -> list[FeatureSpec]:
    F = lambda cid, cols, lvl, d, done=(), miss=(), raw=("atp_matches", "wta_matches"), pit="pregame_rolling": FeatureSpec(S, cid, "player", list(cols), lvl, d, list(done), list(miss), list(raw), pit)
    return [
        F("ten.surface_rating", ["elo_pre", "surface_elo_pre", "elo_gap_pre"], "FULL", "own Elo (K=24) overall and per surface from this data only (value before the match) and the gap to the opponent", ["overall and surface Elo"], ["serve/return-component rating"]),
        F("ten.serve_return", ["spw_pre", "rpw_pre", "spw_surf_pre", "rpw_surf_pre"], "FULL", "EWMA serve-points-won and return-points-won overall and on the match surface", ["serve and return point-win by surface"]),
        F("ten.opp_adjusted_serve_return", ["exp_spw_pre", "exp_ace_rate_pre"], "PARTIAL", "expected serve-point win = own EWMA adjusted for the opponent's return level; expected ace rate adjusted for the opponent's aces allowed", ["opponent-adjusted serve", "opponent-adjusted aces"], ["return components for each side symmetrically"]),
        F("ten.first_serve", ["first_in_pre", "first_won_pre", "second_won_pre"], "FULL", "EWMA first-serve in %, first-serve points won %, second-serve points won %"),
        F("ten.second_serve_vulnerability", ["second_won_pre", "opp_rpw_pre"], "PARTIAL", "own second-serve points won and the opponent's return points won", ["second-serve strength vs return"], ["return win on second serve specifically"]),
        F("ten.aces_df", ["ace_rate_pre", "df_rate_pre"], "PARTIAL", "EWMA aces and double faults per serve point", ["ace and DF rates"], ["serve speed, court speed"]),
        F("ten.ace_opp_adjusted", ["exp_ace_rate_pre", "ace_alw_pre", "opp_ace_alw_pre"], "FULL", "expected ace rate for the match = own ace rate adjusted by the opponent's aces-allowed rate (EWMA)"),
        F("ten.ace_count_distribution", ["ace_var_pre", "exp_ace_rate_pre"], "PARTIAL", "EWMA variance of per-match aces and the expected per-point ace rate", ["dispersion of ace counts", "per-point probability"], ["expected service points per set"]),
        F("ten.break_points", ["bp_save_pre", "bp_conv_pre"], "FULL", "EWMA break points saved % and break points converted %"),
        F("ten.break_point_luck", ["bp_save_dev_pre", "bp_conv_dev_pre"], "PROXY", "short (hl 5) minus long (hl 20) EWMA of break-point saving/converting rates, not an expectation from point-level chances", [], ["expected conversion from rally/serve context"]),
        F("ten.hold_break", ["hold_est_pre", "break_est_pre"], "PARTIAL", "EWMA estimated hold % and break % per service game from break points faced/saved", ["hold/break estimates"], ["game-level Markov chain"]),
        F("ten.first_serve_in_variance", ["first_in_sd_pre"], "FULL", "rolling standard deviation of first-serve % over the previous 20 matches"),
        F("ten.tiebreak", ["tb_share_pre"], "PARTIAL", "EWMA share of the player's sets that were decided by tiebreak", ["tiebreak frequency"], ["tiebreak win rate and hold-under-pressure"]),
        F("ten.tiebreak_reach_probability", ["tb_reach_pre", "tb_share_pre", "opp_tb_share_pre"], "FULL", "mean of the two players' EWMA tiebreak-set shares (probability a set reaches 6-6)"),
        F("ten.lopsided_set_rate", ["lopsided_share_pre"], "FULL", "EWMA share of sets decided 6-0/6-1 (either way)"),
        F("ten.decider_record", ["dec_win_pre", "decider_pre"], "FULL", "EWMA win rate in deciding sets and the share of the player's matches that went the distance"),
        F("ten.match_length_expectation", ["exp_games_per_set_pre", "games_per_set_pre", "n_sets_pre", "minutes_pre"], "PARTIAL", "mean of both players' EWMA games per set, sets and minutes", ["games/sets/minutes expectation"], ["service-points expectation from first-serve rates"]),
        F("ten.form", ["won_pre", "spw_pre", "rpw_pre"], "PARTIAL", "EWMA win rate and point-win rates", ["recent results form"], ["rating-surprise form"]),
        F("ten.workload_minutes", ["minutes_last3_pre", "matches_last14d_pre"], "FULL", "minutes in the previous 3 matches and matches in the previous 14 days"),
        F("ten.fatigue", ["minutes_last3_pre", "days_since_prev", "matches_last14d_pre"], "PARTIAL", "recent minutes, days since previous match and density", ["match length, density, rest"], ["travel, back-to-back-day detail within a tournament"]),
        F("ten.injury_comeback", ["layoff_days_pre", "n_pre"], "PARTIAL", "days since the player's previous match (capped 365) and number of earlier matches", ["layoff length"], ["injury history"]),
        F("ten.retirement_base_rate", ["ret_by_me_pre"], "FULL", "EWMA share of the player's matches ended by his own retirement"),
        F("ten.rating_uncertainty", ["n_pre", "n_surface_pre", "layoff_days_pre", "age"], "PARTIAL", "number of earlier matches (overall and on surface), layoff and age", ["sample-size based uncertainty"], ["Glicko-style rating deviation"]),
        F("ten.age_career_stage", ["age", "age_sq"], "FULL", "age at the match and its square"),
        F("ten.serve_profile_physical", ["ht", "is_left"], "PARTIAL", "height and handedness", ["height, hand"], ["serve speed"]),
        F("ten.handedness", ["is_left", "opp_is_left"], "FULL", "player and opponent left-handed flags"),
        F("ten.h2h_style", ["h2h_n_pre", "h2h_wins_pre", "h2h_share_pre"], "PARTIAL", "head-to-head matches and wins before this match", ["head-to-head record"], ["style tags (rally length, net play)"]),
        F("ten.format", ["best_of5", "level_slam"] if False else ["best_of5"], "PARTIAL", "best-of-five flag", ["best-of-3/5"], ["tiebreak rules and ad scoring by event"]),
        F("ten.rankings", ["rank", "rank_pts", "rank_log", "rank_diff_log"], "FULL", "ATP/WTA ranking and ranking points at match time, log rank and log-rank difference to the opponent"),
        F("ten.round_context", ["round_idx", "seeded", "qualifier", "draw_size"], "PARTIAL", "round index, seeded and qualifier/lucky-loser flags, draw size", ["round, seed, entry type"], ["bracket path difficulty"]),
        F("ten.qualifying_path_fatigue", ["qualifier", "minutes_last3_pre"], "PARTIAL", "qualifier/lucky-loser flag and minutes in the previous 3 matches", ["entry type and recent minutes"], ["qualifying-round matches are not in the main-draw files"]),
        F("ten.surface_calendar", ["days_since_surface", "n_surface_pre"], "FULL", "days since the player's previous match on this surface and earlier matches on it"),
        F("ten.surface_similarity", ["spw_surf_pre", "spw_pre", "n_surface_pre"], "PARTIAL", "surface-specific vs overall serve rates with surface sample size (the pooling weight is for the model)", ["inputs for surface pooling"], ["learned cross-surface transfer matrix"]),
        F("ten.tour_gender_effect", ["tour_wta"], "FULL", "tour flag (ATP/WTA)"),
        F("ten.home_crowd", ["tour_wta"], "PROXY", "placeholder tour flag only", [], ["tournament country is not in the raw data"]) if False else F("ten.motivation", ["rank_pts", "round_idx"], "PROXY", "ranking points and round as stake proxies", [], ["prize money and tanking signals"]),
    ]
