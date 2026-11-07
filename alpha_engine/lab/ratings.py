"""Parametrised, strictly chronological opponent-adjusted team ratings (generalises input_research.nfl_features.rolling_ratings, whose decay/carry/adjustment were fixed).

Axes explored by the lab: ``half_life`` (games), offseason ``carry``, ``prior_k`` shrinkage and ``adjust`` (True: each observation is expressed relative to what the opponent
usually allows/produces; False: raw league-relative).  Ratings for game G use only games strictly before G (written before the update, like the original)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from alpha_engine.input_research import nfl_features as nf


def rolling_ratings_param(games: pd.DataFrame, tg: pd.DataFrame, half_life: float = 8.0, carry: float = 0.65, prior_k: float = 3.0, adjust: bool = True,
                          metrics=None) -> pd.DataFrame:
    metrics = list(metrics or nf.OFF_METRICS)
    lam = 0.5 ** (1.0 / half_life)
    games = games.sort_values(["gameday", "game_id"]).reset_index(drop=True)
    tgi = tg.set_index(["game_id", "posteam"])
    state: dict = {}
    league = {m: [0.0, 0.0] for m in metrics}
    last_season: dict = {}
    rows = []

    def val(team, side, m):
        n, d = state.get((team, side, m), (0.0, 0.0))
        return n / (d + prior_k)

    def lg(m):
        s, c = league[m]
        return s / c if c > 0 else np.nan

    for g in games.itertuples(index=False):
        h, a = g.home_team, g.away_team
        for t in (h, a):
            if last_season.get(t) is not None and last_season[t] != g.season:
                for key in [k for k in state if k[0] == t]:
                    v = state[key]; state[key] = [v[0] * carry, v[1] * carry]
            last_season[t] = g.season
        rec = {"game_id": g.game_id}
        for tag, t in (("h", h), ("a", a)):
            for m in metrics:
                rec[f"{tag}_off_{m}"] = val(t, "off", m)
                rec[f"{tag}_def_{m}"] = val(t, "def", m)
            rec[f"{tag}_games_played"] = state.get((t, "off", metrics[0]), [0, 0])[1]
        rows.append(rec)
        if ((g.game_id, h) not in tgi.index) or ((g.game_id, a) not in tgi.index):
            continue
        for t, o in ((h, a), (a, h)):
            obs_o, obs_d = tgi.loc[(g.game_id, t)], tgi.loc[(g.game_id, o)]
            for m in metrics:
                L = lg(m)
                if np.isnan(L):
                    continue
                x_off, x_def = obs_o[m], obs_d[m]
                if not np.isnan(x_off):
                    adj = (x_off - L) - (val(o, "def", m) if adjust else 0.0)
                    s = state.setdefault((t, "off", m), [0.0, 0.0]); s[0] = s[0] * lam + adj; s[1] = s[1] * lam + 1.0
                if not np.isnan(x_def):
                    adj = (x_def - L) - (val(o, "off", m) if adjust else 0.0)
                    s = state.setdefault((t, "def", m), [0.0, 0.0]); s[0] = s[0] * lam + adj; s[1] = s[1] * lam + 1.0
        for t in (h, a):
            r = tgi.loc[(g.game_id, t)]
            for m in metrics:
                if not np.isnan(r[m]):
                    league[m][0] += float(r[m]); league[m][1] += 1.0
    return pd.DataFrame(rows)
