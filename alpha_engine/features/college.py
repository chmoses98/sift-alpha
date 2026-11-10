"""College basketball / football builders from ESPN scoreboard rows (scores, period scores, rank, neutral site, attendance, conference flag). RESEARCH_ONLY.
The raw data has NO box scores, play-by-play, tempo, shooting, injuries or officials, so the many catalog inputs that need them stay uncomputed (the audit lists them with reasons)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .core import FeatureSpec, Paths, pair_rows, prior_count, prior_date_mean, prior_ewm


def load_raw(p: Paths, sport: str) -> pd.DataFrame:
    return pd.read_csv(p.raw / f"espn_{sport.lower()}_games.csv.gz", low_memory=False)


def compute(raw: pd.DataFrame) -> dict:
    d = raw.dropna(subset=["home_score", "away_score", "home_id", "away_id"]).copy()
    d["date"] = pd.to_datetime(d.date, errors="coerce"); d = d.dropna(subset=["date"]).sort_values(["date", "game_id"], kind="mergesort").reset_index(drop=True)
    rows = []
    for s, o, home in (("home", "away", 1), ("away", "home", 0)):
        h1 = d[f"{s}_periods"].map(lambda x: _first(x)); a1 = d[f"{o}_periods"].map(lambda x: _first(x))
        rows.append(pd.DataFrame({"game_id": d.game_id, "date": d.date, "season": d.season, "team": d[f"{s}_id"], "home": home, "neutral": d.neutral_site.fillna(False).astype(float), "conf_game": d.conference_game.fillna(False).astype(float),
                                  "pts": d[f"{s}_score"], "pts_a": d[f"{o}_score"], "h1": h1, "h1_a": a1, "ranked": d[f"{s}_rank"].between(1, 25).astype(float), "opp_ranked": d[f"{o}_rank"].between(1, 25).astype(float), "rank": d[f"{s}_rank"],
                                  "ot": (d.n_periods > (2 if str(d.league.iloc[0]).upper() == "CBB" else 4)).astype(float), "attendance": d.attendance, "season_type": d.season_type}))
    t = pd.concat(rows, ignore_index=True).sort_values(["date", "game_id", "home"], ascending=[True, True, False], kind="mergesort").reset_index(drop=True)
    t["margin"] = t.pts - t.pts_a; t["total"] = t.pts + t.pts_a; t["win"] = (t.margin > 0).astype(float)
    t["h1_share"] = (t.h1 + t.h1_a) / t.total.replace(0, np.nan); t["h2"] = t.pts - t.h1; t["h2_a"] = t.pts_a - t.h1_a
    for c in ["pts", "pts_a", "margin", "total", "win", "h1_share", "h1", "h1_a", "h2", "h2_a", "ot"]:
        t[f"{c}_pre"] = prior_ewm(t, "team", c, hl=6, min_periods=3)
    t["season_games_pre"] = t.groupby(["team", "season"], sort=False).cumcount()
    t["n_pre"] = prior_count(t, "team")
    t["attendance_pre"] = prior_ewm(t, "team", "attendance", hl=6, min_periods=2)
    t["rest"] = t.groupby("team", sort=False)["date"].transform(lambda s: (s - s.shift(1)).dt.days).clip(upper=21)
    t["games_7d_pre"] = 0.0
    for _, idx in t.groupby("team", sort=False).groups.items():
        dd = t.loc[idx, "date"].to_numpy("datetime64[D]"); lo = np.searchsorted(dd, dd - np.timedelta64(7, "D"), side="left"); t.loc[idx, "games_7d_pre"] = np.arange(len(dd)) - lo
    t["win_pct_season_pre"] = t.groupby(["team", "season"], sort=False)["win"].transform(lambda s: s.shift(1).expanding().mean())
    t["margin_season_pre"] = t.groupby(["team", "season"], sort=False)["margin"].transform(lambda s: s.shift(1).expanding().mean())
    t["lg_pts_pre"] = prior_date_mean(t, "date", "pts"); t["lg_total_pre"] = prior_date_mean(t, "date", "total")
    t["pyth_pre"] = (t.pts_pre ** 11.5) / (t.pts_pre ** 11.5 + t.pts_a_pre ** 11.5)
    t["pyth_luck_pre"] = t.win_pct_season_pre - t.pyth_pre
    t["blowout_pre"] = prior_ewm(t.assign(_b=(t.margin.abs() >= (20 if t.pts.median() > 50 else 20)).astype(float)), "team", "_b", hl=8, min_periods=3)
    t["h2_adj_pre"] = t.h2_pre - t.h2_a_pre
    t = pair_rows(t, game="game_id", team="team", cols=["pts_pre", "pts_a_pre", "margin_pre", "total_pre", "n_pre", "win_pct_season_pre", "rest", "h1_share_pre", "ot_pre", "season_games_pre"])
    t["exp_pts_pre"] = t.pts_pre + t.opp_pts_a_pre - t.lg_pts_pre
    t["exp_total_pre"] = t.exp_pts_pre + (t.opp_pts_pre + t.pts_a_pre - t.lg_pts_pre)
    t["rating_gap_pre"] = t.margin_pre - t.opp_margin_pre
    t["rest_gap"] = t.rest - t.opp_rest
    t["ot_prob_pre"] = (t.ot_pre + t.opp_ot_pre) / 2; t["h1_share_match_pre"] = (t.h1_share_pre + t.opp_h1_share_pre) / 2
    t["neutral_home"] = t.neutral * t.home
    t["early_season"] = (t.season_games_pre < 5).astype(float)
    return {"team": t}


def _first(x):
    try:
        s = str(x).strip("[]").split(",")
        return float(s[0])
    except Exception:
        return np.nan


def specs_cbb() -> list[FeatureSpec]:
    return _specs("cbb", {
        "cbb.adj_off": (["pts_pre", "exp_pts_pre"], "PARTIAL", "EWMA points scored and opponent-adjusted expected points", ["scoring level", "opponent adjustment"], ["per-possession efficiency (no possessions in raw data)"]),
        "cbb.adj_def": (["pts_a_pre"], "PARTIAL", "EWMA points allowed", ["points allowed"], ["per-possession efficiency"]),
        "cbb.ratings": (["rating_gap_pre", "margin_pre", "margin_season_pre"], "PARTIAL", "EWMA scoring margin and season margin gap to the opponent", ["margin rating"], ["opponent-adjusted efficiency rating"]),
        "cbb.preseason_prior": (["early_season", "season_games_pre"], "PROXY", "early-season flag and games played; no preseason ranking in the raw data", [], ["prior-season ratings, returning production"]),
        "cbb.rating_uncertainty": (["n_pre", "season_games_pre"], "PARTIAL", "number of earlier games and games this season", ["sample size"], ["rating deviation"]),
        "cbb.in_season_improvement": (["margin_pre", "margin_season_pre"], "PARTIAL", "short EWMA margin vs season average", ["trend"], ["roster-based improvement"]),
        "cbb.venue": (["home", "neutral", "neutral_home"], "PARTIAL", "home and neutral flags", ["venue flags"], ["altitude, arena effects"]),
        "cbb.neutral_site": (["neutral", "neutral_home"], "FULL", "neutral-site flag"),
        "cbb.home_court_team": (["home"], "PARTIAL", "home flag", ["home flag"], ["team-specific home advantage"]),
        "cbb.rest_travel": (["rest", "games_7d_pre", "rest_gap"], "PARTIAL", "days of rest, games in 7 days and the rest gap", ["rest, density"], ["travel distance"]),
        "cbb.schedule_spot": (["games_7d_pre", "rest_gap", "conf_game"], "PARTIAL", "density, rest gap and conference-game flag", ["spot components"], ["lookahead/letdown flags"]),
        "cbb.ot_model": (["ot_prob_pre", "ot_pre"], "PARTIAL", "EWMA overtime frequency of both teams", ["OT base rate"], ["close-game dispersion model"]),
        "cbb.score_resid": (["pyth_luck_pre"], "PROXY", "win-percentage minus Pythagorean expectation", [], ["points-vs-expected regression"]),
        "cbb.blowout_garbage": (["blowout_pre"], "PARTIAL", "EWMA frequency of 20+ point margins", ["blowout rate"], ["garbage-time minutes"]),
        "cbb.half_split": (["h1_share_match_pre", "h1_pre", "h2_pre"], "PARTIAL", "EWMA first/second-half scoring from period scores", ["half scoring"], ["possession-level half pace"]),
        "cbb.tempo": (["total_pre", "exp_total_pre"], "PROXY", "EWMA total points as a tempo proxy (no possessions)", [], ["possessions per 40"]),
        "cbb.pace_mismatch": (["exp_total_pre"], "PROXY", "expected total points from both teams' scoring levels", [], ["possession pace gap"]),
        "cbb.conf_strength": (["conf_game"], "PROXY", "conference-game flag only", [], ["conference ratings"]),
        "cbb.motivation": (["season_games_pre", "win_pct_season_pre", "ranked", "opp_ranked"], "PROXY", "record, rank flags and season progress", [], ["tournament-bubble state"]),
        "cbb.popularity_bias": (["ranked", "opp_ranked", "attendance_pre"], "PARTIAL", "AP-rank flags and the team's EWMA home attendance in earlier games (this game's attendance is only known afterwards)", ["ranks, prior attendance"], ["public betting share"]),
    })


def specs_cfb() -> list[FeatureSpec]:
    return _specs("cfb", {
        "cfb.pythag_luck": (["pyth_luck_pre"], "FULL", "season win percentage minus Pythagorean expectation (exponent 11.5)"),
        "cfb.score_resid": (["pyth_luck_pre"], "PROXY", "win-percentage minus Pythagorean expectation", [], ["points-vs-expected from drives"]),
        "cfb.q_scoring": (["h1_pre", "h2_pre", "h1_share_match_pre"], "PARTIAL", "EWMA first/second-half points", ["half scoring"], ["quarter scoring"]),
        "cfb.half_split": (["h1_pre", "h2_pre", "h2_adj_pre"], "PARTIAL", "EWMA first/second-half points for and against", ["halves"], ["drive-level splits"]),
        "cfb.rest_travel": (["rest", "rest_gap", "games_7d_pre"], "PARTIAL", "days rest and the rest gap", ["rest"], ["travel"]),
        "cfb.venue": (["home", "neutral", "neutral_home", "attendance_pre"], "PARTIAL", "home/neutral flags and the team's EWMA attendance in earlier games", ["flags, prior attendance"], ["stadium altitude, surface"]),
        "cfb.ot_model": (["ot_prob_pre", "ot_pre"], "PARTIAL", "EWMA overtime frequency", ["OT base rate"], ["close-game model"]),
        "cfb.blowout_management": (["blowout_pre"], "PARTIAL", "EWMA frequency of 20+ point margins", ["blowout rate"], ["clock management behaviour"]),
        "cfb.team_total_split": (["exp_pts_pre", "exp_total_pre"], "PARTIAL", "expected team points and match total from scoring levels", ["expected points"], ["drive/pace based split"]),
        "cfb.polls": (["ranked", "opp_ranked", "rank"], "FULL", "AP rank at game time and ranked flags"),
        "cfb.motivation": (["season_games_pre", "win_pct_season_pre", "ranked"], "PROXY", "record, rank, season progress", [], ["playoff/bowl stakes"]),
        "cfb.standings": (["win_pct_season_pre", "season_games_pre", "conf_game"], "PARTIAL", "season record and conference flag", ["record"], ["conference standings"]),
        "cfb.sp_plus": (["rating_gap_pre", "margin_pre"], "PROXY", "EWMA scoring margin gap, not an efficiency rating", [], ["SP+/opponent-adjusted efficiency"]),
        "cfb.pace": (["total_pre", "exp_total_pre"], "PROXY", "scoring total as a pace proxy", [], ["plays per game"]),
    })


def _specs(sport, m):
    out = []
    for cid, v in m.items():
        cols, lvl, d = v[0], v[1], v[2]
        out.append(FeatureSpec(sport.upper(), cid, "team", cols, lvl, d, list(v[3]) if len(v) > 3 else [], list(v[4]) if len(v) > 4 else [], ["ESPN scoreboard"], "pregame_rolling"))
    return out
