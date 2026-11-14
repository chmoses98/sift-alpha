"""Operation Data Foundation, NHL: point-in-time goalie inputs for ``alpha-nhl-joint-0.2``.

RESEARCH_ONLY. Pure numpy/pandas helpers, unit-tested on synthetic data:

* ``goalie_quality_state``  walk-forward, per-goalie exponentially decayed goals-allowed vs expected-goals sums (expected =
                            MoneyPuck unblocked-shot xG scaled to the trailing league goals/xG ratio where available, else
                            shots against x trailing league goals/shot), season discount ``carry`` and empirical-Bayes
                            shrinkage ``q = log((GA + P) / (E + P))`` (q > 0 = goalie allows more than expected).
* ``starter_candidates``    for every team-game, the goalies who started for that team in the previous 365 days (at most 4,
                            most recent first) with pre-game features: share of the team's last 10 starts, started the team's
                            previous game, goalie back-to-back, log days since the goalie's last start, season start share.
* ``fit_conditional_logit`` / ``starter_probs``  multinomial (conditional) logit of who starts -> a mixture over the team's
                            goalies instead of a league-average fallback.

Everything uses strictly earlier dates. The as-played ``starter`` flag is only ever a TRAINING LABEL for the starter model
and the input of the explicitly labelled ORACLE_NOT_PIT ablation.
"""
from __future__ import annotations

import math

import numpy as np

CAND_FEATS = ["share10", "last1", "g_b2b", "log_days", "season_share"]
MAX_CAND = 4
LOOKBACK_DAYS = 365


def league_ratio_trailing(day, num, den, fallback):
    """Per-row ratio sum(num)/sum(den) over rows with a strictly earlier day (NaN rows skipped); ``fallback`` before data."""
    day = np.asarray(day); num = np.asarray(num, float); den = np.asarray(den, float)
    ok = ~(np.isnan(num) | np.isnan(den))
    ud = np.unique(day); pos = np.searchsorted(ud, day)
    sn = np.zeros(len(ud)); sd = np.zeros(len(ud))
    np.add.at(sn, pos[ok], num[ok]); np.add.at(sd, pos[ok], den[ok])
    cn = np.concatenate([[0.0], np.cumsum(sn)]); cd = np.concatenate([[0.0], np.cumsum(sd)])
    n, d = cn[pos], cd[pos]  # cumulative over days strictly before this row's day
    with np.errstate(invalid="ignore", divide="ignore"):
        r = n / d
    return np.where(d > 50, r, fallback)


def expected_goals(day, ga, sa, xga, toi):
    """Expected goals against per goalie-game row: xG x trailing league GA/xG where xG exists, else SA x trailing league GA/SA."""
    use = np.asarray(toi, float) > 0
    ga = np.where(use, ga, np.nan).astype(float); sa = np.where(use, sa, np.nan).astype(float); xga = np.asarray(xga, float)
    kx = league_ratio_trailing(day, np.where(np.isnan(xga), np.nan, ga), xga, 1.0)
    ks = league_ratio_trailing(day, ga, sa, 0.095)
    return np.where(~np.isnan(xga), xga * kx, sa * ks), kx, ks


def goalie_quality_state(player, season, day, ga, e, toi, hl, carry):
    """POST-game decayed sums (GA, E) per row (rows sorted by day). Rows with toi <= 0 do not update."""
    d = 0.5 ** (1.0 / hl); post = np.zeros((len(player), 2)); state, last = {}, {}
    upd = np.asarray(toi, float) > 0
    for i in range(len(player)):
        p = player[i]; s = state.get(p)
        if s is None:
            s = np.zeros(2)
        elif last[p] != season[i]:
            s = s * carry
        if upd[i] and ga[i] == ga[i] and e[i] == e[i]:
            s = s * d + np.array([ga[i], e[i]])
        state[p] = s; last[p] = season[i]; post[i] = s
    return post


class QualityLookup:
    """q of goalie ``p`` before day ``d`` (strictly earlier rows), with the season discount if the last row is an earlier season."""

    def __init__(self, player, season, day, post, carry, prior):
        self.carry, self.prior = carry, prior; self.idx = {}
        order = np.lexsort((np.arange(len(player)), day))
        for i in order:
            self.idx.setdefault(player[i], []).append(i)
        self.day = np.asarray(day); self.season = np.asarray(season); self.post = post
        self.days = {p: self.day[np.array(v)] for p, v in self.idx.items()}

    def q(self, p, d, s):
        v = self.idx.get(p)
        if v is None:
            return 0.0
        k = int(np.searchsorted(self.days[p], d, side="left")) - 1
        if k < 0:
            return 0.0
        i = v[k]; ga, e = self.post[i]
        if self.season[i] != s:
            ga, e = ga * self.carry, e * self.carry
        return float(math.log((ga + self.prior) / (e + self.prior)))


def starter_candidates(tgames, starts):
    """``tgames``: list of (key, team, day, season) in chronological order (one row per team-game).
    ``starts``: dict team -> chronological list of (day, season, player) for STARTS strictly by that team (as-played history).
    Returns list per team-game of (players, feature matrix (n, len(CAND_FEATS))) using only starts with day < game day."""
    import bisect
    gstarts = {}
    for team, lst in starts.items():
        for d, s, p in lst:
            gstarts.setdefault(p, []).append(d)
    for p in gstarts:
        gstarts[p].sort()
    tdays = {t: [x[0] for x in lst] for t, lst in starts.items()}
    out = []
    for key, team, day, season in tgames:
        lst = starts.get(team, []); k = bisect.bisect_left(tdays.get(team, []), day)
        prev = lst[:k]
        recent = [x for x in prev if x[0] >= day - LOOKBACK_DAYS]
        players = []
        for d, s, p in reversed(recent):
            if p not in players:
                players.append(p)
            if len(players) == MAX_CAND:
                break
        last10 = [x[2] for x in prev[-10:]]; last1 = prev[-1][2] if prev else None
        sea = [x[2] for x in prev if x[1] == season]
        X = np.zeros((len(players), len(CAND_FEATS)))
        for j, p in enumerate(players):
            gd = gstarts[p]; m = bisect.bisect_left(gd, day)
            dl = day - gd[m - 1] if m > 0 else 100
            X[j] = [last10.count(p) / max(len(last10), 1), float(p == last1), float(dl == 1), math.log1p(min(dl, 100)),
                    sea.count(p) / len(sea) if sea else 0.0]
        out.append((players, X))
    return out


def starter_probs(X, beta):
    if len(X) == 0:
        return np.zeros(0)
    u = X @ beta; u = u - u.max(); e = np.exp(u)
    return e / e.sum()


def fit_conditional_logit(groups, ridge=1e-3, iters=50):
    """``groups``: list of (X (n_j, k), chosen index). Newton-Raphson on the conditional-logit log-likelihood."""
    k = groups[0][0].shape[1]; b = np.zeros(k)
    for _ in range(iters):
        g = -ridge * b; H = -ridge * np.eye(k)
        for X, c in groups:
            p = starter_probs(X, b); mx = p @ X
            g += X[c] - mx
            H -= (X * p[:, None]).T @ X - np.outer(mx, mx)
        step = np.linalg.solve(H, g); b = b - step
        if np.max(np.abs(step)) < 1e-10:
            break
    return b


def starter_nll(groups, beta):
    return float(np.mean([-math.log(max(starter_probs(X, beta)[c], 1e-12)) for X, c in groups]))
