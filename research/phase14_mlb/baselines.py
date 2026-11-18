"""Simple point-in-time baselines (Phase 14 MLB): team run ridge ratings, Elo, season-average player rates.
Every prediction for date D is produced before date D's games are added."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ridge_ratings(G: pd.DataFrame, tau: float = 150.0, lam: float = 30.0, carry: float = 0.7):
    """Decayed ridge on runs: runs = mu + home*h + off[team] - def[opp]. Returns (pred_home, pred_away) arrays."""
    teams = pd.Index(sorted(set(G.home_id) | set(G.away_id)))
    T = len(teams)
    k = 2 + 2 * T
    A = np.zeros((k, k))
    b = np.zeros(k)
    ph = np.full(len(G), np.nan)
    pa = np.full(len(G), np.nan)
    prev = None
    reg = np.full(k, lam)
    reg[:2] = 1e-3
    for d, idx in G.groupby("date").indices.items():
        season = d[:4]
        f = np.exp(-1.0 / tau) * (carry if (prev is not None and season != prev) else 1.0)
        prev = season
        A *= f
        b *= f
        beta = np.linalg.solve(A + np.diag(reg), b) if A[0, 0] > 0 else np.r_[4.4, 0, np.zeros(2 * T)]
        hi = teams.get_indexer(G.home_id.values[idx])
        ai = teams.get_indexer(G.away_id.values[idx])
        ph[idx] = beta[0] + beta[1] + beta[2 + hi] - beta[2 + T + ai]
        pa[idx] = beta[0] + beta[2 + ai] - beta[2 + T + hi]
        for j, h_, a_ in zip(idx, hi, ai):
            for off, de, home, y in ((h_, a_, 1, G.home_runs.values[j]), (a_, h_, 0, G.away_runs.values[j])):
                x = np.zeros(k)
                x[0] = 1
                x[1] = home
                x[2 + off] = 1
                x[2 + T + de] = -1
                A += np.outer(x, x)
                b += x * y
    return ph, pa


def elo(G: pd.DataFrame, K: float = 4.0, hfa: float = 24.0, revert: float = 1 / 3):
    """538-style MLB Elo with margin multiplier. Returns P(home win)."""
    r: dict[int, float] = {}
    p = np.full(len(G), np.nan)
    prev = None
    for d, idx in G.groupby("date").indices.items():
        season = d[:4]
        if prev is not None and season != prev:
            r = {t: 1500 + (1 - revert) * (v - 1500) for t, v in r.items()}
        prev = season
        for j in idx:
            h, a = G.home_id.values[j], G.away_id.values[j]
            dr = r.get(h, 1500) + hfa - r.get(a, 1500)
            p[j] = 1 / (1 + 10 ** (-dr / 400))
        for j in idx:
            h, a = G.home_id.values[j], G.away_id.values[j]
            dr = r.get(h, 1500) + hfa - r.get(a, 1500)
            e = 1 / (1 + 10 ** (-dr / 400))
            hr, ar = G.home_runs.values[j], G.away_runs.values[j]
            y = 1.0 if hr > ar else 0.0
            mov = np.log(abs(hr - ar) + 1) * 2.2 / ((dr if y else -dr) * 0.001 + 2.2)
            delta = K * mov * (y - e)
            r[h] = r.get(h, 1500) + delta
            r[a] = r.get(a, 1500) - delta
    return p


def season_avg(lines: pd.DataFrame, stat: str, key: str = "player", min_n: int = 3, prior_w: float = 0.0):
    """Point-in-time season-to-date average of `stat` per `key`; falls back to previous season, then league-to-date.
    lines must have date, season, key, stat. Returns array aligned to lines."""
    lines = lines.sort_values("date")
    out = pd.Series(np.nan, index=lines.index)
    cur: dict = {}
    last: dict = {}
    lg = [0.0, 0.0]
    prev = None
    for d, grp in lines.groupby("date", sort=True):
        season = d[:4]
        if prev is not None and season != prev:
            last = {k: v[0] / v[1] for k, v in cur.items() if v[1] >= min_n}
            cur = {}
        prev = season
        lgm = lg[0] / lg[1] if lg[1] else np.nan
        vals = []
        for pid in grp[key].values:
            c = cur.get(pid)
            if c and c[1] >= min_n:
                vals.append(c[0] / c[1])
            elif pid in last:
                vals.append(last[pid])
            else:
                vals.append(lgm)
        out.loc[grp.index] = vals
        for pid, v in zip(grp[key].values, grp[stat].values):
            c = cur.setdefault(pid, [0.0, 0])
            c[0] += v
            c[1] += 1
            lg[0] += v
            lg[1] += 1
    return out.reindex(lines.index).sort_index().values
