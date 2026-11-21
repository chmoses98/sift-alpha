"""Vectorised Monte-Carlo game simulator (Phase 14 MLB).

Each team's 9 regulation innings are simulated PA by PA (all lanes of many games at once): the batter's outcome is
drawn from his 8-class PA distribution vs the opposing starter until the starter's simulated batters-faced limit
(Normal(bf_mu, bf_sd)) is reached, then vs the opposing bullpen. Base-out transitions (post-bases, outs added, runs)
are drawn from an empirical table T[outcome, bases, outs] estimated on development seasons. Home 9th-inning skip /
walk-off truncation is applied from per-inning runs; ties go to extras drawn from the empirical extra-inning table.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

KMAX = 24  # transition outcomes kept per (event, bases, outs) row


def build_transitions(pa: pd.DataFrame):
    d = pa[(pa.inn <= 9) & (pa.pre_outs <= 2)]
    post_outs = d.pre_outs + d.outs_add
    post_base = np.where(post_outs >= 3, 0, d.post_base)
    oa = np.clip(d.outs_add.values, 0, 3)
    runs = np.clip(d.runs.values, 0, 4)
    code = (post_base * 4 + oa) * 5 + runs  # 160 cells
    key = (d.ev.values * 8 + d.pre_base.values) * 3 + d.pre_outs.values
    cnt = np.zeros((8 * 8 * 3, 160))
    np.add.at(cnt, (key, code), 1)
    cells = np.zeros((192, KMAX), np.int64)
    cdf = np.ones((192, KMAX))
    for r in range(192):
        c = cnt[r]
        if c.sum() == 0:  # unseen state: batter out, nobody moves
            c = np.zeros(160)
            c[(0 * 4 + 1) * 5] = 1
        order = np.argsort(-c)[:KMAX]
        w = c[order]
        cells[r] = order
        cdf[r] = np.cumsum(w) / w.sum()
    return cells, cdf


def build_extras(pa: pd.DataFrame, games: pd.DataFrame):
    """Empirical (winner, loser) runs scored in extra innings (dev seasons)."""
    x = pa[pa.inn >= 10].groupby(["game_pk", "top"]).runs.sum().unstack(fill_value=0)
    g = games.set_index("game_pk").loc[x.index]
    home_win = g.home_runs > g.away_runs
    w = np.where(home_win, x.get(False, 0), x.get(True, 0))
    l_ = np.where(home_win, x.get(True, 0), x.get(False, 0))
    pairs = np.stack([w, l_], 1)
    return pairs[(pairs[:, 0] > pairs[:, 1])]


def simulate_offense(Psp, Pbp, bf_mu, bf_sd, cells, cdf, n_sims, rng, max_steps=120):
    """Psp/Pbp: (g, 9, 8) per-slot PA probabilities. Returns runs per inning (g,S,9), starter K (g,S),
    batter H/TB/HR per slot (g,S,9)."""
    g = Psp.shape[0]
    L = g * n_sims
    gi = np.repeat(np.arange(g), n_sims)
    csp = np.cumsum(Psp, -1)
    cbp = np.cumsum(Pbp, -1)
    lim = np.clip(np.rint(rng.normal(np.repeat(bf_mu, n_sims), bf_sd)), 3, 40).astype(np.int64)
    inn = np.zeros(L, np.int64)
    outs = np.zeros(L, np.int64)
    base = np.zeros(L, np.int64)
    slot = np.zeros(L, np.int64)
    bf = np.zeros(L, np.int64)
    runs = np.zeros((L, 9), np.int64)
    k = np.zeros(L, np.int64)
    H = np.zeros((L, 9), np.int64)
    TB = np.zeros((L, 9), np.int64)
    HR = np.zeros((L, 9), np.int64)
    tbv = np.array([0, 0, 0, 1, 2, 3, 4, 0])
    act = np.arange(L)
    for _ in range(max_steps):
        if act.size == 0:
            break
        a = act
        use_sp = bf[a] < lim[a]
        c = np.where(use_sp[:, None], csp[gi[a], slot[a]], cbp[gi[a], slot[a]])
        u = rng.random(a.size)
        ev = np.minimum((u[:, None] > c).sum(1), 7)
        k[a] += (ev == 0) & use_sp
        bf[a] += 1
        s = slot[a]
        hit = (ev >= 3) & (ev <= 6)
        H[a, s] += hit
        TB[a, s] += tbv[ev]
        HR[a, s] += ev == 6
        row = (ev * 8 + base[a]) * 3 + outs[a]
        u2 = rng.random(a.size)
        j = np.minimum((u2[:, None] > cdf[row]).sum(1), KMAX - 1)
        cell = cells[row, j]
        r = cell % 5
        oa = (cell // 5) % 4
        pb = cell // 20
        runs[a, inn[a]] += r
        no = outs[a] + oa
        end = no >= 3
        outs[a] = np.where(end, 0, no)
        base[a] = np.where(end, 0, pb)
        inn[a] += end
        slot[a] = (s + 1) % 9
        act = a[inn[a] < 9]
    S = n_sims
    return runs.reshape(g, S, 9), k.reshape(g, S), H.reshape(g, S, 9), TB.reshape(g, S, 9), HR.reshape(g, S, 9)


def combine_game(runs_home, runs_away, extras, rng):
    """Apply home 9th skip / walk-off cap and extras. Inputs (g,S,9). Returns final home, away runs (g,S)."""
    a = runs_away.sum(-1)
    h8 = runs_home[..., :8].sum(-1)
    h9 = runs_home[..., 8]
    bats9 = h8 <= a
    cap = np.where(h8 <= a, a - h8 + 1, 0)
    h = h8 + np.where(bats9, np.minimum(h9, np.maximum(cap, 0)), 0)
    tie = h == a
    if tie.any():
        n = int(tie.sum())
        pick = extras[rng.integers(0, len(extras), n)]
        # P(home wins extras) from relative regulation scoring strength of the two teams in this game
        mh = runs_home.sum(-1).mean(-1, keepdims=True)
        ma = runs_away.sum(-1).mean(-1, keepdims=True)
        q = np.broadcast_to(mh / (mh + ma + 1e-9), h.shape)[tie]
        home_w = rng.random(n) < q
        h = h.copy()
        a = a.copy()
        h[tie] += np.where(home_w, pick[:, 0], pick[:, 1])
        a[tie] += np.where(home_w, pick[:, 1], pick[:, 0])
    return h, a
