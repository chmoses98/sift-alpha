"""Market-free systematic search across sports whose raw data is now in hand (RESEARCH_ONLY): game totals for NBA, NHL, MLB, CBB, CFB and a tennis winner model, all through the SAME
nested chronological harness as NFL/soccer (search.py). No sportsbook line, Kalshi price or derived feature is read: only results, box-score/shot aggregates, rest and venue context.

Features are pre-game EWMAs over each team's earlier games (no game sees itself); the baseline is the running league mean (totals) or the model's own Elo (tennis), so a gain is information
beyond a strong no-market baseline. Each sport reports the nested out-of-sample gain, a permutation-null gain (the search's own overfitting) and per-group importance.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import marketfree as MF, search as SR

OUT = Path(__file__).resolve().parents[2] / "research/audit/input_research/experiments/search_crosssport_v1.json"
HL = 8.0


def rolling(long: pd.DataFrame, metrics: list[str], league_col=None) -> pd.DataFrame:
    """long: one row per team-game with date, game_id, team, home, metrics. Returns pre-game EWMA per row (team state BEFORE the game) + rest days + prior games."""
    lam = 0.5 ** (1 / HL)
    long = long.sort_values(["date", "game_id"]).reset_index(drop=True)
    st: dict = {}
    last: dict = {}
    out = {m: [] for m in metrics}
    rest, n = [], []
    for r in long.itertuples(index=False):
        s = st.get(r.team)
        for m in metrics:
            out[m].append(s[m][0] / s[m][1] if s and s[m][1] > 0 else np.nan)
        rest.append(min((r.date - last[r.team]).days, 10) if r.team in last else np.nan)
        n.append(s["n"] if s else 0)
        s = st.setdefault(r.team, {**{m: [0.0, 0.0] for m in metrics}, "n": 0})
        for m in metrics:
            v = getattr(r, m)
            if v == v and v is not None:
                s[m][0] = s[m][0] * lam + float(v); s[m][1] = s[m][1] * lam + 1.0
        s["n"] += 1
        last[r.team] = r.date
    res = long[["game_id", "team", "home"]].copy()
    for m in metrics:
        res[m] = out[m]
    res["rest"], res["n_prior"] = rest, n
    return res


def game_table(long: pd.DataFrame, metrics: list[str], games: pd.DataFrame) -> pd.DataFrame:
    r = rolling(long, metrics)
    h = r[r.home].drop(columns="home").add_prefix("h_").rename(columns={"h_game_id": "game_id"})
    a = r[~r.home].drop(columns="home").add_prefix("a_").rename(columns={"a_game_id": "game_id"})
    g = games.merge(h, on="game_id").merge(a, on="game_id")
    for m in metrics:
        g[f"sum_{m}"] = g[f"h_{m}"] + g[f"a_{m}"]
    return g


def league_mean(g: pd.DataFrame, tot="total", decay=0.998):
    g = g.sort_values(["date", "game_id"]).reset_index(drop=True)
    s = n = 0.0
    base = []
    for v in g[tot]:
        base.append(s / n if n > 0 else np.nan)
        s = s * decay + v; n = n * decay + 1
    g["lg_mean"] = base
    return g


def run_total(name, g, metrics, extra_groups, seasons_test, n_configs=100, null_reps=1, block_months=None, n_test_blocks=8) -> dict:
    g = league_mean(g)
    g = g[(g[[f"h_{metrics[0]}", f"a_{metrics[0]}"]].notna().all(axis=1)) & g.lg_mean.notna() & (g.h_n_prior >= 5) & (g.a_n_prior >= 5)].copy().reset_index(drop=True)
    groups = {"attack": [f"h_{metrics[0]}", f"a_{metrics[0]}"], "defence": [f"h_{metrics[1]}", f"a_{metrics[1]}"], "matchup_expected": ["exp_total"], "rest_schedule": ["h_rest", "a_rest"]}
    g["exp_total"] = (g[f"h_{metrics[0]}"] + g[f"a_{metrics[1]}"]) / 2 + (g[f"a_{metrics[0]}"] + g[f"h_{metrics[1]}"]) / 2
    for k, cols in extra_groups.items():
        cols = [c for c in cols if c in g and g[c].notna().mean() > 0.5]
        if cols:
            groups[k] = cols
    MF.assert_market_free([c for v in groups.values() for c in v])
    r = (g.total - g.lg_mean).to_numpy(float)
    keys = (g.season.astype(str) + "-" + pd.to_datetime(g.date).dt.isocalendar().week.astype(str)).to_numpy()
    if block_months:   # short histories: validate on chronological time blocks instead of whole seasons (same nested harness; the 'season' column is just the block id)
        g["season_label"] = g.season
        g["season"] = (pd.to_datetime(g.date).dt.year * 12 + pd.to_datetime(g.date).dt.month - 1) // block_months
        tests = sorted(g.season.unique())[-n_test_blocks:]
    else:
        tests = [s for s in sorted(g.season.unique()) if s in seasons_test]
    res = SR.nested_search(g, r, groups, tests, n_configs=n_configs)
    gain = SR.summarize_gain(g, r, res["pred"], keys)
    null = SR.permutation_null(g, r, groups, tests, keys, reps=null_reps, n_configs=n_configs)
    ch = res["chosen"]
    imp = {}
    for k in groups:
        dl = np.array([c["core_inner_rel_mse"][f"drop:{k}"] - c["core_inner_rel_mse"]["full"] for c in ch])
        imp[k] = {"mean_rel_mse_increase_when_dropped": round(float(dl.mean()), 5), "folds_where_dropping_hurts": int((dl > 0).sum()), "folds": int(len(dl))}
    return {"market": name, "n_games": int(len(g)), "validation_blocks": f"{block_months}-month blocks" if block_months else "seasons", "seasons_scored": gain["seasons"], "nested_gain": gain, "permutation_null": null, "groups": groups, "group_importance": imp,
            "model_structure_frequency": {k: round(float(np.mean([c["config"]["model"] == k for c in ch])), 3) for k in ("ridge", "gbm")}}


def nba(c: Path):
    fs = sorted((c / "nba/data/history/espn").glob("team_games_*.parquet"))
    d = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
    d = d[d.season_type.isin(["regular"])].copy()
    d["date"] = pd.to_datetime(d.game_date_et); d["season"] = np.where(d.date.dt.month >= 8, d.date.dt.year, d.date.dt.year - 1)
    d["ppp"] = d.pts / d.possessions; d["opp_ppp"] = d.opp_pts / d.possessions; d["tov_rate"] = d.tov / d.possessions; d["ft_rate"] = d.fta / d.fga
    long = d.rename(columns={"team_id": "team"})[["date", "game_id", "team", "home", "ppp", "opp_ppp", "possessions", "tov_rate", "ft_rate", "oreb"]].copy()
    m = d[d.home][["game_id", "date", "season", "total"]].drop_duplicates("game_id")
    g = game_table(long, ["ppp", "opp_ppp", "possessions", "tov_rate", "ft_rate"], m)
    return run_total("NBA game total (regular season)", g, ["ppp", "opp_ppp"], {"pace_volume": ["h_possessions", "a_possessions", "sum_possessions"], "ball_security_and_fouls": ["h_tov_rate", "a_tov_rate", "h_ft_rate", "a_ft_rate"]}, set(), block_months=2, n_test_blocks=8)


def nhl(c: Path):
    H = c / "nhl_hist/data/history"
    gm = pd.concat([pd.read_parquet(f) for f in sorted((H / "nhl").glob("games_*.parquet"))], ignore_index=True)
    gm = gm[(gm.game_type == 2) & (gm.final == True)].copy()
    gm["date"] = pd.to_datetime(gm.game_date)
    gm = gm.drop_duplicates("game_id")
    sh = pd.concat([pd.read_parquet(f, columns=["game_id", "team_id", "sog", "is_home"]) for f in sorted((H / "players").glob("players_*.parquet"))], ignore_index=True)
    ts = sh.groupby(["game_id", "team_id"]).sog.sum().reset_index()
    rows = []
    for r in gm.itertuples():
        for side, tid, opp, gf, ga in (("h", r.home_team_id, r.away_team_id, r.home_score, r.away_score), ("a", r.away_team_id, r.home_team_id, r.away_score, r.home_score)):
            rows.append({"date": r.date, "game_id": r.game_id, "team": tid, "opp": opp, "home": side == "h", "gf": gf, "ga": ga})
    long = pd.DataFrame(rows).merge(ts.rename(columns={"team_id": "team", "sog": "sf"}), on=["game_id", "team"], how="left").merge(ts.rename(columns={"team_id": "opp", "sog": "sa"}), on=["game_id", "opp"], how="left")
    gm["season"] = gm.season.astype(int); gm["total"] = gm.home_score + gm.away_score
    g = game_table(long, ["gf", "ga", "sf", "sa"], gm[["game_id", "date", "season", "total"]])
    g = g[g.season >= 2021]
    return run_total("NHL game total (regular season, 2021+ with shots)", g, ["gf", "ga"], {"shot_volume": ["h_sf", "a_sf", "h_sa", "a_sa"]}, set(), block_months=3, n_test_blocks=8)


def nba_player_points(c: Path):
    """NBA player points (a market-family archetype with no NFL equivalent): target = points minus the player's own shrunk recent rate; inputs = own recent minutes/usage/efficiency trends,
    team pace, opponent defence and rest. Rows only for players with >= 10 prior games and >= 15 expected minutes. Chronological 2-month blocks."""
    fs = sorted((c / "nba/data/history/espn").glob("player_games_*.parquet"))
    d = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
    d = d[(d.season_type == "regular") & (d.played == True)].copy()
    d["date"] = pd.to_datetime(d.game_date_et)
    d["usage"] = (d.fga + 0.44 * d.fta + d.tov)
    d = d.sort_values(["date", "game_id"]).reset_index(drop=True)
    tg = pd.concat([pd.read_parquet(f) for f in sorted((c / "nba/data/history/espn").glob("team_games_*.parquet"))], ignore_index=True)
    tg = tg[tg.season_type == "regular"].copy(); tg["date"] = pd.to_datetime(tg.game_date_et)
    tg["ppp"] = tg.pts / tg.possessions; tg["opp_ppp"] = tg.opp_pts / tg.possessions
    tl = rolling(tg.rename(columns={"team_id": "team"})[["date", "game_id", "team", "home", "ppp", "opp_ppp", "possessions"]], ["ppp", "opp_ppp", "possessions"])
    tl = tl.rename(columns={"team": "team_id"})
    lam = 0.5 ** (1 / 10.0)
    st: dict = {}
    last: dict = {}
    rows = []
    for r in d.itertuples(index=False):
        s_ = st.get(r.nba_id)
        def g(k): return s_[k][0] / s_[k][1] if s_ and s_[k][1] > 0 else np.nan
        row = {"game_id": r.game_id, "date": r.date, "pid": r.nba_id, "team_id": r.team_id, "opp_team_id": r.opp_team_id, "pts": r.pts, "n_prior": s_["n"] if s_ else 0,
               "min_ew": g("min"), "pts_ew": g("pts"), "usage_ew": g("usage"), "fg3a_ew": g("fg3a"), "fta_ew": g("fta"), "min_last3": np.nan, "started_ew": g("st"),
               "rest": min((r.date - last[r.nba_id]).days, 10) if r.nba_id in last else np.nan, "home": float(bool(r.home))}
        rows.append(row)
        s_ = st.setdefault(r.nba_id, {k: [0.0, 0.0] for k in ("min", "pts", "usage", "fg3a", "fta", "st")} | {"n": 0})
        for k, v in (("min", r.minutes), ("pts", r.pts), ("usage", r.usage), ("fg3a", r.fg3a), ("fta", r.fta), ("st", float(bool(r.started)))):
            if v == v and v is not None:
                s_[k][0] = s_[k][0] * lam + float(v); s_[k][1] = s_[k][1] * lam + 1.0
        s_["n"] += 1; last[r.nba_id] = r.date
    g_ = pd.DataFrame(rows)
    g_ = g_.merge(tl[["game_id", "team_id", "possessions", "ppp"]].rename(columns={"possessions": "team_pace", "ppp": "team_ppp"}), on=["game_id", "team_id"], how="left")
    g_ = g_.merge(tl[["game_id", "team_id", "opp_ppp", "possessions"]].rename(columns={"team_id": "opp_team_id", "opp_ppp": "opp_def_ppp", "possessions": "opp_pace"}), on=["game_id", "opp_team_id"], how="left")
    g_["pts_per_min"] = g_.pts_ew / g_.min_ew
    g_ = g_[(g_.n_prior >= 10) & (g_.min_ew >= 15)].copy().reset_index(drop=True)
    g_["season"] = (g_.date.dt.year * 12 + g_.date.dt.month - 1) // 2
    groups = {"role_and_minutes": ["min_ew", "started_ew"], "usage_and_volume": ["usage_ew", "fg3a_ew", "fta_ew"], "team_pace_and_efficiency": ["team_pace", "team_ppp", "opp_pace"], "opponent_defence": ["opp_def_ppp"], "rest_and_home": ["rest", "home"]}
    MF.assert_market_free([x for v in groups.values() for x in v])
    r_ = (g_.pts - g_.pts_ew).to_numpy(float)
    keys = (g_.season.astype(str) + "-" + g_.date.dt.isocalendar().week.astype(str)).to_numpy()
    tests = sorted(g_.season.unique())[-8:]
    res = SR.nested_search(g_, r_, groups, tests, n_configs=60)
    gain = SR.summarize_gain(g_, r_, res["pred"], keys)
    null = SR.permutation_null(g_, r_, groups, tests, keys, reps=1, n_configs=60)
    ch = res["chosen"]
    imp = {k: {"mean_rel_mse_increase_when_dropped": round(float(np.mean([c["core_inner_rel_mse"][f"drop:{k}"] - c["core_inner_rel_mse"]["full"] for c in ch])), 5)} for k in groups}
    return {"market": "NBA player points vs the player's own shrunk recent rate", "n_games": int(len(g_)), "validation_blocks": "2-month blocks", "nested_gain": gain, "permutation_null": null, "groups": groups, "group_importance": imp}


def mlb(c: Path):
    d = pd.read_csv(c / "mlb_schedule_games.csv.gz", parse_dates=["date"])
    d = d[d.home_score.notna() & d.away_score.notna()].copy()
    d["total"] = d.home_score + d.away_score
    rows = []
    for r in d.itertuples():
        rows.append({"date": r.date, "game_id": r.game_pk, "team": r.home_id, "home": True, "rs": r.home_score, "ra": r.away_score})
        rows.append({"date": r.date, "game_id": r.game_pk, "team": r.away_id, "home": False, "rs": r.away_score, "ra": r.home_score})
    long = pd.DataFrame(rows)
    d["date_"] = d.date
    # park factor and umpire tendency: running mean of total runs by venue / home-plate umpire BEFORE the game (no look-ahead)
    d = d.sort_values(["date", "game_pk"]).reset_index(drop=True)
    for key, col in (("venue_id", "park_runs"), ("home_plate_ump_id", "ump_runs")):
        s, n, out = {}, {}, []
        for k, tot in zip(d[key], d.total):
            out.append(s.get(k, 0) / n[k] if n.get(k, 0) >= 20 else np.nan)
            s[k] = s.get(k, 0) + tot; n[k] = n.get(k, 0) + 1
        d[col] = out
    d["temp_c"] = d.temp
    d["night"] = (d.day_night == "night").astype(float)
    m = d.rename(columns={"game_pk": "game_id"})[["game_id", "date", "season", "total", "park_runs", "ump_runs", "temp_c", "night"]]
    g = game_table(long, ["rs", "ra"], m)
    return run_total("MLB game total (regular season)", g, ["rs", "ra"], {"park_and_umpire": ["park_runs", "ump_runs"], "weather_observed": ["temp_c", "night"]}, {2023, 2024, 2025})


def espn(c: Path, league):
    d = pd.read_csv(c / f"espn_{league.lower()}_games.csv.gz", parse_dates=["date"])
    d = d[d.home_score.notna() & d.away_score.notna() & (d.season_type == 2)].copy()
    d["total"] = d.home_score + d.away_score
    rows = []
    for r in d.itertuples():
        rows.append({"date": r.date, "game_id": r.game_id, "team": r.home_id, "home": True, "pf": r.home_score, "pa": r.away_score})
        rows.append({"date": r.date, "game_id": r.game_id, "team": r.away_id, "home": False, "pf": r.away_score, "pa": r.home_score})
    long = pd.DataFrame(rows)
    d["neutral"] = d.neutral_site.astype(float); d["indoor_f"] = d.indoor.astype(float); d["ranked_pair"] = d.home_rank.notna().astype(float) + d.away_rank.notna().astype(float)
    g = game_table(long, ["pf", "pa"], d[["game_id", "date", "season", "total", "neutral", "indoor_f", "ranked_pair"]])
    last = int(g.season.max())
    return run_total(f"{league} game total (regular season)", g, ["pf", "pa"], {"venue_context": ["neutral", "indoor_f"], "ranking_context": ["ranked_pair"]}, set(), block_months=(2 if league == "CBB" else 1), n_test_blocks=8)


def tennis(c: Path, tour="atp"):
    fs = sorted(c.glob(f"tennis/{tour}_matches_*.csv.gz"))
    d = pd.concat([pd.read_csv(f, low_memory=False) for f in fs], ignore_index=True)
    d["date"] = pd.to_datetime(d.tourney_date.astype(str), format="%Y%m%d", errors="coerce")
    d = d.dropna(subset=["date", "winner_id", "loser_id"]).sort_values(["date", "tourney_id", "match_num"]).reset_index(drop=True)
    d["season"] = d.date.dt.year
    elo, selo = {}, {}
    st = {}
    lam = 0.5 ** (1 / 20.0)
    rows = []
    for r in d.itertuples():
        a, b = (r.winner_id, r.loser_id) if r.winner_id < r.loser_id else (r.loser_id, r.winner_id)   # player order by id, never by outcome
        y = 1.0 if a == r.winner_id else 0.0
        surf = r.surface if isinstance(r.surface, str) else "Hard"
        ea, eb = elo.get(a, 1500.0), elo.get(b, 1500.0)
        sa, sb = selo.get((a, surf), ea), selo.get((b, surf), eb)
        p_elo = 1 / (1 + 10 ** (-((0.5 * ea + 0.5 * sa) - (0.5 * eb + 0.5 * sb)) / 400))
        def f(pid, key):
            s = st.get(pid); return s[key][0] / s[key][1] if s and s[key][1] > 0 else np.nan
        row = {"game_id": f"{r.tourney_id}-{r.match_num}", "date": r.date, "season": r.season, "y": y, "p_elo": p_elo, "total": y}
        for who, pid in (("a", a), ("b", b)):
            row[f"{who}_ace"], row[f"{who}_1st"], row[f"{who}_bp"] = f(pid, "ace"), f(pid, "first"), f(pid, "bp")
            row[f"{who}_n"] = st.get(pid, {}).get("n", 0)
        row["rank_diff"] = (getattr(r, "winner_rank") - getattr(r, "loser_rank")) * (1 if a == r.winner_id else -1) if pd.notna(r.winner_rank) and pd.notna(r.loser_rank) else np.nan
        wa, ha = (r.winner_age, r.loser_age) if a == r.winner_id else (r.loser_age, r.winner_age)
        row["age_diff"] = wa - ha if pd.notna(wa) and pd.notna(ha) else np.nan
        row["best_of5"] = float(r.best_of == 5); row["surf_clay"] = float(surf == "Clay"); row["surf_grass"] = float(surf == "Grass")
        rows.append(row)
        # update AFTER the row
        k = 20.0
        elo[a] = ea + k * (y - 1 / (1 + 10 ** (-(ea - eb) / 400))); elo[b] = eb - k * (y - 1 / (1 + 10 ** (-(ea - eb) / 400)))
        selo[(a, surf)] = sa + k * (y - p_elo); selo[(b, surf)] = sb - k * (y - p_elo)
        for pid, pre in ((r.winner_id, "w_"), (r.loser_id, "l_")):
            if pd.notna(getattr(r, pre + "svpt", np.nan)) and getattr(r, pre + "svpt") > 0:
                s = st.setdefault(pid, {"ace": [0.0, 0.0], "first": [0.0, 0.0], "bp": [0.0, 0.0], "n": 0})
                vals = {"ace": getattr(r, pre + "ace") / getattr(r, pre + "svpt"), "first": getattr(r, pre + "1stIn") / getattr(r, pre + "svpt"),
                        "bp": (getattr(r, pre + "bpSaved") / getattr(r, pre + "bpFaced")) if getattr(r, pre + "bpFaced") > 0 else np.nan}
                for kk, v in vals.items():
                    if v == v:
                        s[kk][0] = s[kk][0] * lam + float(v); s[kk][1] = s[kk][1] * lam + 1.0
                s["n"] += 1
    g = pd.DataFrame(rows)
    g = g[(g.season >= 2005) & (g.a_n >= 10) & (g.b_n >= 10)].reset_index(drop=True)
    g["d_ace"], g["d_1st"], g["d_bp"] = g.a_ace - g.b_ace, g.a_1st - g.b_1st, g.a_bp - g.b_bp
    groups = {"serve_form": ["d_ace", "d_1st"], "pressure_points": ["d_bp"], "ranking_and_age": ["rank_diff", "age_diff"], "format_surface": ["best_of5", "surf_clay", "surf_grass"], "elo_gap": ["p_elo"]}
    MF.assert_market_free([x for v in groups.values() for x in v])
    r = (g.y - g.p_elo).to_numpy(float)
    keys = (g.season.astype(str) + "-" + g.date.dt.isocalendar().week.astype(str)).to_numpy()
    last = int(g.season.max())
    tests = [s for s in sorted(g.season.unique()) if s >= last - 4]
    # tennis: baseline = own Elo probability; target residual y - p_elo; gain measured on squared error (Brier) vs Elo
    res = SR.nested_search(g, r, groups, tests, n_configs=80)
    gain = SR.summarize_gain(g, r, res["pred"], keys)
    null = SR.permutation_null(g, r, groups, tests, keys, reps=1, n_configs=80)
    ch = res["chosen"]
    imp = {k: {"mean_rel_mse_increase_when_dropped": round(float(np.mean([c["core_inner_rel_mse"][f"drop:{k}"] - c["core_inner_rel_mse"]["full"] for c in ch])), 5)} for k in groups}
    return {"market": f"{tour.upper()} match winner vs own surface-blended Elo (Brier)", "n_games": int(len(g)), "nested_gain": gain, "permutation_null": null, "groups": groups, "group_importance": imp}


def main():
    from .phase import assert_predictive_allowed; assert_predictive_allowed('search_crosssport')
    c = Path(sys.argv[1])
    sports = sys.argv[2:] or ["NBA", "NHL", "MLB", "CBB", "CFB", "TENNIS"]
    fn = {"NBA_PLAYER_POINTS": nba_player_points, "NBA": nba, "NHL": nhl, "MLB": mlb, "CBB": lambda p: espn(p, "CBB"), "CFB": lambda p: espn(p, "CFB"), "TENNIS": tennis}
    out = json.loads(OUT.read_text()) if OUT.exists() else {"schema_version": "search-crosssport-1.0", "status": "RESEARCH_ONLY", "market_free": True, "studies": {}}
    for s in sports:
        try:
            out["studies"][s] = fn[s](c)
            g = out["studies"][s]["nested_gain"]
            print(s, out["studies"][s]["n_games"], f"gain {g['pct_gain']:.2f}% seasons+ {g['seasons_positive']}/{len(g['seasons'])} null {[round(x['pct_gain'],2) for x in out['studies'][s]['permutation_null']]}", flush=True)
        except Exception as e:
            out["studies"][s] = {"error": f"{type(e).__name__}: {e}"}; print(s, "ERROR", e, flush=True)
        OUT.write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
