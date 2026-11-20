"""Shared market-free building blocks for score-derived pre-game inputs (RESEARCH_ONLY): a walk-forward off/def ridge on any per-side game quantity, and a
season-walk-forward Gaussian kernel for conditional frequencies. Used by cfb_espn_ext, nhl_period_ext and mlb_line_ext. No market price enters.

fit(g, targets, lam, hl): g = games sorted by (date, game_id) with columns season, date, home, away, ne (1.0 unless neutral site), optional avail.
  For each date d: S = largest season among the games on d; pool = games dated strictly before d with season >= S-1, chronological.
  Optional column `avail` (result-availability date, >= date): a pool game must ALSO have avail strictly before d. A game that started on one date and was
  completed later (MLB suspended game) is dated by its first pitch (its own row uses only information before first pitch) and its result enters pools
  only once it is complete. Without the column (or with avail == date) the behaviour is unchanged byte for byte.
  rank(team, pool game) = number of LATER pool games in which the team plays; rk = min(rank_home, rank_away); weight w = 0.5 ** (rk / hl).
  Each pool game with both target values present gives two observations (offence = home, defence = away, y = y_home, I = ne) and (offence = away, defence = home, y = y_away, I = 0).
  Weighted ridge y ~ b0 + a[offence] + d[defence] + h * I, penalty lam on every a and d, none on b0 and h. Fewer than MIN_POOL usable pool games -> missing.
  Per game on d: ep_h = b0 + a[H] + d[V] + ne * h; ep_a = b0 + a[V] + d[H]; off_X = b0 + a[X]; def_X = b0 + d[X].  (A team absent from the pool has a = d = 0.)
  Optional se: s2 = sum(w r^2) / sum(w) over the fitted observations; c = design row of the home observation + design row of the away observation; se = sqrt(s2 * c' A^-1 c), A = Z'WZ + P.
kernel(season, dims, events, cond): for a row of season s, the reference set is every row of an EARLIER season with all conditioning values present; per event the reference rows are further limited
  to rows where the event value is present (and cond is true). Fewer than min_ref such rows -> missing. k_i = exp(-0.5 * sum_dims ((x_i - x) / bw) ** 2); value = sum(k_i v_i) / sum(k_i).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_POOL = 16


def fit(g: pd.DataFrame, targets: dict, lam: float, hl: float, se: str | None = None) -> pd.DataFrame:
    teams = sorted(set(g.home) | set(g.away)); ti = {t: i for i, t in enumerate(teams)}
    h = g.home.map(ti).to_numpy(); a = g.away.map(ti).to_numpy(); ne = g["ne"].to_numpy(float); season = g.season.to_numpy(); date = g.date.to_numpy(); n = len(g)
    avail = g["avail"].to_numpy() if "avail" in g else None
    if avail is not None and (avail < date).any():
        raise ValueError("avail (result availability) earlier than the game date")
    names = list(targets); Y = {k: (np.asarray(v[0], float), np.asarray(v[1], float)) for k, v in targets.items()}
    out = {f"{k}_{s}": np.full(n, np.nan) for k in names for s in ("ep_h", "ep_a", "off_h", "def_h", "off_a", "def_a")}
    if se: out[se + "_se"] = np.full(n, np.nan)
    starts = np.flatnonzero(np.r_[True, date[1:] != date[:-1]]); ends = np.r_[starts[1:], n]
    for s0, e0 in zip(starts, ends):
        keep = season[:s0] >= season[s0:e0].max() - 1
        if avail is not None:
            keep &= avail[:s0] < date[s0]                                    # result not yet known on d (suspended game resumed on/after d)
        pool = np.flatnonzero(keep); m = len(pool)
        if m < MIN_POOL:
            continue
        ph, pa, pne = h[pool], a[pool], ne[pool]
        cnt = np.zeros(len(teams), int); rh = np.empty(m, int); ra = np.empty(m, int)
        for i in range(m - 1, -1, -1):
            rh[i] = cnt[ph[i]]; ra[i] = cnt[pa[i]]; cnt[ph[i]] += 1; cnt[pa[i]] += 1
        w = 0.5 ** (np.minimum(rh, ra) / hl)
        act = np.unique(np.r_[ph, pa]); loc = np.full(len(teams), -1); loc[act] = np.arange(len(act)); T = len(act); p = 2 * T + 2
        groups: dict = {}
        for k in names:
            ok = np.isfinite(Y[k][0][pool]) & np.isfinite(Y[k][1][pool]); groups.setdefault(ok.tobytes(), (ok, []))[1].append(k)
        for ok, ks in groups.values():
            kk = int(ok.sum())
            if kk < MIN_POOL:
                continue
            lh, la, wk, nk = loc[ph[ok]], loc[pa[ok]], w[ok], pne[ok]
            idx = np.r_[np.c_[np.zeros(kk, int), 1 + lh, 1 + T + la, np.full(kk, p - 1)], np.c_[np.zeros(kk, int), 1 + la, 1 + T + lh, np.full(kk, p - 1)]]
            val = np.r_[np.c_[np.ones((kk, 3)), nk], np.c_[np.ones((kk, 3)), np.zeros(kk)]]; w2 = np.r_[wk, wk]
            A = np.zeros((p, p)); np.add.at(A, (idx[:, :, None], idx[:, None, :]), w2[:, None, None] * val[:, :, None] * val[:, None, :])
            A[np.arange(1, p - 1), np.arange(1, p - 1)] += lam
            R = np.zeros((p, len(ks)))
            for q, k in enumerate(ks):
                np.add.at(R[:, q], idx, (w2 * np.r_[Y[k][0][pool][ok], Y[k][1][pool][ok]])[:, None] * val)
            try:
                B = np.linalg.solve(A, R)
            except np.linalg.LinAlgError:
                continue
            for q, k in enumerate(ks):
                b = B[:, q]; ca = np.r_[b[1:1 + T], 0.0]; cd = np.r_[b[1 + T:1 + 2 * T], 0.0]      # index -1 (absent team) -> 0
                for j in range(s0, e0):
                    H, V = loc[h[j]], loc[a[j]]
                    out[k + "_ep_h"][j] = b[0] + ca[H] + cd[V] + ne[j] * b[-1]; out[k + "_ep_a"][j] = b[0] + ca[V] + cd[H]
                    out[k + "_off_h"][j] = b[0] + ca[H]; out[k + "_def_h"][j] = b[0] + cd[H]; out[k + "_off_a"][j] = b[0] + ca[V]; out[k + "_def_a"][j] = b[0] + cd[V]
                if k == se:
                    y = np.r_[Y[k][0][pool][ok], Y[k][1][pool][ok]]; r = y - (val * b[idx]).sum(axis=1); s2 = float((w2 * r * r).sum() / w2.sum())
                    for j in range(s0, e0):
                        H, V = loc[h[j]], loc[a[j]]; c = np.zeros(p); c[0] = 2.0; c[-1] = ne[j]; extra = 0.0
                        for t in (H, V):
                            if t >= 0: c[1 + t] += 1.0; c[1 + T + t] += 1.0
                            else: extra += 2.0 / lam
                        out[se + "_se"][j] = float(np.sqrt(s2 * (c @ np.linalg.solve(A, c) + extra)))
    return pd.DataFrame(out)


def kernel(season, dims: list, events: dict, cond=None, min_ref: int = 500, chunk: int = 500) -> dict:
    season = np.asarray(season); n = len(season); X = [(np.asarray(x, float), float(bw)) for x, bw in dims]
    has = np.ones(n, bool)
    for x, _ in X: has &= np.isfinite(x)
    ev = {k: np.asarray(v, float) for k, v in events.items()}; out = {k: np.full(n, np.nan) for k in ev}
    cm = np.ones(n, bool) if cond is None else np.asarray(cond, bool)
    for s in np.unique(season):
        ref = np.flatnonzero(has & (season < s)); cur = np.flatnonzero(has & (season == s))
        if not len(ref) or not len(cur):
            continue
        V = {k: np.isfinite(v[ref]) & cm[ref] for k, v in ev.items()}; V = {k: m for k, m in V.items() if int(m.sum()) >= min_ref}
        for c0 in range(0, len(cur), chunk):
            cc = cur[c0:c0 + chunk]; z = np.zeros((len(cc), len(ref)))
            for x, bw in X:
                z += ((x[cc][:, None] - x[ref][None, :]) / bw) ** 2
            K = np.exp(-0.5 * z)
            for k, m in V.items():
                den = K @ m.astype(float); num = K @ np.where(m, ev[k][ref], 0.0)
                out[k][cc] = np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)
    return out


def team_rows(g: pd.DataFrame, home: dict, away: dict) -> pd.DataFrame:
    """Two rows per game (team = home, team = away); `home` / `away` map output column -> per-game array for that side."""
    base = g[["game_id", "season", "date"]]
    t = pd.concat([base.assign(team=g.home, opp=g.away, is_home=1.0, **home), base.assign(team=g.away, opp=g.home, is_home=0.0, **away)], ignore_index=True)
    return t.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)
