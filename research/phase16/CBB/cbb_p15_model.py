"""Phase 15 CBB game model (research only; no production imports).

Walk-forward, date-strict opponent-adjusted efficiency + tempo ratings:

* For each date d of season S, ridge-fit  eff(off i vs def j) = mu + hca * x + O_i - D_j  (x = +-1/2 home/away, 0 neutral)
  and  poss(i, j) = muP + T_i + T_j  on season-S games strictly before d, recency weight exp(-(d - t)/tau),
  shrunk toward a preseason prior.  Non-D-I opponents (no ESPN conference id) share one pooled team.
* Preseason prior (variant "full"): previous-season final rating regressed by roster continuity
  (share of previous-season minutes from players already seen for the team before d; unseen returners count with
  P(return | seasons played) * q^games) and incoming-transfer quality (players seen before d whose previous-season
  minutes were for another team, weighted by that team's rating).  Variant "base": constant regression factor.
* Team-specific home court: shrunk mean of home-game residuals of previous seasons' final fits (full variant).
* Linear calibration layer (frozen on training seasons): margin ~ raw margin + team HCA + rest; total ~ raw total
  + early-season terms.  SDs: variance regression on games played and predicted size.

Everything that a prediction for date d uses is computed from games dated < d (or earlier seasons).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")  # 700x700 solves are 100x slower with threaded OpenBLAS here

import numpy as np
import pandas as pd

NONDI = -1


def _blas_single():
    try:
        from threadpoolctl import threadpool_limits
        return threadpool_limits(1)
    except ImportError:  # pragma: no cover
        import contextlib
        return contextlib.nullcontext()


@dataclass
class Cfg:
    variant: str = "full"        # "full" | "base"
    lam_prior: float = 6.0       # prior strength in game-rows for O / D
    lam_tempo: float = 6.0
    tau: float = 1e9             # recency (days); 1e9 = none
    lam_mu: float = 20.0
    lam_hca: float = 400.0
    q_unseen: float = 0.5
    hca_k: float = 60.0          # team HCA shrinkage (home games)
    new_team_pct: float = 15.0   # prior percentile for teams with no previous-season rating
    coef: dict = field(default_factory=dict)   # frozen regression coefficients (filled by fit_prior_coefs)


# ----------------------------------------------------------------------------------------------- ridge solver
def _solve(nparam, cols, vals, y, w, lam_vec, prior_vec):
    """Ridge normal equations (A = X'WX + diag(lam), b = X'Wy + lam*prior) for a sparse design given as k nonzero
    (column, value) pairs per row."""
    k = cols.shape[1]
    ii = np.repeat(cols, k, axis=1).ravel() * nparam + np.tile(cols, (1, k)).ravel()
    vv = (np.repeat(vals, k, axis=1) * np.tile(vals, (1, k)) * w[:, None]).ravel()
    A = np.bincount(ii, weights=vv, minlength=nparam * nparam).astype(float).reshape(nparam, nparam)
    A[np.diag_indices(nparam)] += lam_vec
    b = np.bincount(cols.ravel(), weights=(vals * (w * y)[:, None]).ravel(), minlength=nparam).astype(float) + lam_vec * prior_vec
    with _blas_single():
        return np.linalg.solve(A, b)


def team_index(games: pd.DataFrame):
    """D-I teams of the season (ESPN conference id present = static pregame membership) + pooled non-D-I."""
    ids = np.unique(np.r_[games.home_id[games.home_d1], games.away_id[games.away_d1]])
    return {int(t): i for i, t in enumerate(ids)}, len(ids) + 1


def _map(ids, d1, idx, n):
    return np.array([idx.get(int(t), n - 1) if f else n - 1 for t, f in zip(ids, d1, strict=False)], dtype=np.int64)


def fit_ratings(g: pd.DataFrame, idx, n, d, cfg: Cfg, prior: dict):
    """Ratings from games strictly before date d. Returns dict of arrays (length n) and scalars."""
    tr = g[(g.date < d) & (g.poss > 40)]
    h = _map(tr.home_id.values, tr.home_d1.values, idx, n)
    a = _map(tr.away_id.values, tr.away_d1.values, idx, n)
    age = (d - tr.date).dt.days.values.astype(float)
    w = np.exp(-age / cfg.tau)
    x = np.where(tr.neutral.values, 0.0, 0.5)
    poss = tr.poss.values
    # efficiency: params [mu, hca, O(n), D(n)]
    y = np.r_[100 * tr.home_pts.values / poss, 100 * tr.away_pts.values / poss]
    off, de = np.r_[h, a], np.r_[a, h]
    cols = np.c_[np.zeros_like(off), np.ones_like(off), 2 + off, 2 + n + de]
    vals = np.c_[np.ones(len(off)), np.r_[x, -x], np.ones(len(off)), -np.ones(len(off))]
    lam = np.r_[cfg.lam_mu, cfg.lam_hca, np.full(n, cfg.lam_prior), np.full(n, cfg.lam_prior)]
    pri = np.r_[prior["mu"], prior["hca"], prior["O"], prior["D"]]
    th = _solve(2 + 2 * n, cols, vals, y, np.r_[w, w], lam, pri)
    # tempo: [muP, T(n)]
    cols_t = np.c_[np.zeros_like(h), 1 + h, 1 + a]
    vals_t = np.ones((len(h), 3))
    lam_t = np.r_[cfg.lam_mu, np.full(n, cfg.lam_tempo)]
    th_t = _solve(1 + n, cols_t, vals_t, poss, w, lam_t, np.r_[prior["muP"], prior["T"]])
    return {"mu": th[0], "hca": th[1], "O": th[2:2 + n], "D": th[2 + n:], "muP": th_t[0], "T": th_t[1:]}


def raw_predict(r, h, a, neutral):
    x = np.where(neutral, 0.0, 0.5)
    poss = r["muP"] + r["T"][h] + r["T"][a]
    eh = r["mu"] + r["hca"] * x + r["O"][h] - r["D"][a]
    ea = r["mu"] - r["hca"] * x + r["O"][a] - r["D"][h]
    ph, pa = eh * poss / 100, ea * poss / 100
    return ph, pa, poss


# ----------------------------------------------------------------------------------------------- season pieces
def final_fit(g: pd.DataFrame):
    """End-of-season ratings (all games of the season, weak shrink to 0) + per-game residuals. Used only for the
    NEXT season's prior and team HCA."""
    idx, n = team_index(g)
    cfg = Cfg(lam_prior=2.0, lam_tempo=2.0, lam_mu=0.01, lam_hca=0.01)
    z = np.zeros(n)
    r = fit_ratings(g, idx, n, g.date.max() + pd.Timedelta(days=1), cfg,
                    {"mu": 100.0, "hca": 0.0, "O": z, "D": z, "muP": 68.0, "T": z})
    h = _map(g.home_id.values, g.home_d1.values, idx, n)
    a = _map(g.away_id.values, g.away_d1.values, idx, n)
    ph, pa, _ = raw_predict(r, h, a, g.neutral.values)
    res = (g.home_pts - g.away_pts).values - (ph - pa) + np.where(g.neutral, 0, 1) * 0  # global hca already in ph-pa
    return idx, n, r, pd.DataFrame({"home_id": g.home_id.values, "neutral": g.neutral.values, "home_d1": g.home_d1.values,
                                    "res": res})


def player_tables(pm: pd.DataFrame):
    """Season-level minutes per (season, team, athlete) and seasons-seen count before each season."""
    st = pm.groupby(["season", "team_id", "athlete_id"], as_index=False).minutes.sum()
    first = pm.groupby("athlete_id").season.min()
    st["k_seen"] = st.season - st.athlete_id.map(first) + 1     # seasons since first appearance (incl. this one)
    return st


def return_rates(st: pd.DataFrame, seasons) -> dict:
    """P(player plays for the same team next season | k seasons seen), minutes-weighted, from training seasons."""
    nxt = st[["season", "team_id", "athlete_id"]].assign(season=lambda x: x.season - 1, back=1)
    m = st[st.season.isin(seasons)].merge(nxt, on=["season", "team_id", "athlete_id"], how="left").fillna({"back": 0})
    m["k"] = m.k_seen.clip(upper=5)
    return (m.groupby("k").apply(lambda x: np.average(x.back, weights=x.minutes))).to_dict()


class RosterState:
    """Per-season roster continuity / transfer state; `at(d)` uses only player boxes of games dated < d."""

    def __init__(self, S, pm_season: pd.DataFrame, st: pd.DataFrame, prev_ratings: dict, pret: dict, q: float):
        prev = st[st.season == S - 1].copy()
        prev["pret"] = prev.k_seen.clip(upper=5).map(lambda k: pret.get(k, 0.3))
        self.tot_prev = prev.groupby("team_id").minutes.sum()
        self.prev = prev
        cur = pm_season.groupby(["team_id", "athlete_id"], as_index=False).date.min().rename(columns={"date": "first"})
        self.cur = cur
        self.team_dates = pm_season[["team_id", "game_id", "date"]].drop_duplicates()
        # athlete's main previous-season team and total previous minutes
        main = prev.sort_values("minutes").groupby("athlete_id").tail(1).set_index("athlete_id")
        ptot = prev.groupby("athlete_id").minutes.sum()
        rat = pd.DataFrame.from_dict(prev_ratings, orient="index", columns=["pO", "pD", "pT"])
        tin = cur.join(main.team_id.rename("prev_team"), on="athlete_id").join(ptot.rename("pmin"), on="athlete_id")
        tin = tin[tin.prev_team.notna() & (tin.prev_team != tin.team_id)].join(rat, on="prev_team").dropna(subset=["pO"])
        self.tin = tin
        self.pairs_prev = prev.merge(cur, on=["team_id", "athlete_id"], how="left")
        self.q = q

    def at(self, d=None) -> pd.DataFrame:
        far = pd.Timestamp("2100-01-01")
        d = far if d is None else d
        ng = self.team_dates[self.team_dates.date < d].groupby("team_id").size()
        pp = self.pairs_prev
        seen = pp["first"].notna() & (pp["first"] < d)
        ngt = pp.team_id.map(ng).fillna(0).values
        contrib = pp.minutes.values * np.where(seen, 1.0, pp.pret.values * self.q ** ngt)
        c = pd.Series(contrib).groupby(pp.team_id.values).sum() / self.tot_prev
        out = pd.DataFrame({"c": c})
        t = self.tin[self.tin["first"] < d]
        if len(t):
            wsum = t.groupby("team_id").pmin.sum()
            out["tr"] = wsum / self.tot_prev
            for k, col in (("inO", "pO"), ("inD", "pD"), ("inT", "pT")):
                out[k] = (t[col] * t.pmin).groupby(t.team_id).sum() / wsum
        for col in ["tr", "inO", "inD", "inT"]:
            if col not in out:
                out[col] = 0.0
        out = out.fillna(0.0)
        out["tr"] = out["tr"].clip(0, 1.5)
        out["ng"] = out.index.map(ng).fillna(0)
        return out


def prior_from(prev_r: dict, prev_idx: dict, idx: dict, n: int, feats: pd.DataFrame | None, cfg: Cfg, prev_hca: float):
    """Preseason prior means for season S (arrays of length n) from S-1 final ratings (+ roster features at d)."""
    pO, pD, pT = prev_r["O"], prev_r["D"], prev_r["T"]
    co = cfg.coef
    teams = np.fromiter(idx.keys(), dtype=np.int64, count=len(idx))
    pos = np.fromiter(idx.values(), dtype=np.int64, count=len(idx))
    j = np.array([prev_idx.get(int(t), -1) for t in teams])
    has = j >= 0
    new = (np.percentile(pO[:-1], cfg.new_team_pct), np.percentile(pD[:-1], cfg.new_team_pct), np.median(pT[:-1]))
    X = [np.where(has, p[np.maximum(j, 0)], 0.0) for p in (pO, pD, pT)]
    out = []
    for k, (x, p, nw) in enumerate(zip(X, (pO, pD, pT), new, strict=False)):
        key = "ODT"[k]
        arr = np.zeros(n)
        if cfg.variant == "base" or feats is None:
            v = co["r" + key] * x
        else:
            f = feats.reindex(teams)
            c = f.c.fillna(0.45).values
            tr = f.tr.fillna(0.0).values
            inx = f["in" + key].fillna(0.0).values
            b = co[key]
            v = (b[0] + b[1] * c) * x + b[2] * tr * inx
        arr[pos] = np.where(has, v, nw)
        arr[n - 1] = co["r" + key] * p[-1]
        out.append(arr)
    return {"mu": prev_r["mu"], "hca": prev_hca, "O": out[0], "D": out[1], "muP": prev_r["muP"], "T": out[2]}


def team_hca(resid_hist: list[pd.DataFrame], k: float) -> dict:
    """Shrunk team-specific home-court residual (points) from earlier seasons' final-fit residuals."""
    if not resid_hist:
        return {}
    r = pd.concat(resid_hist)
    r = r[(~r.neutral) & r.home_d1]
    agg = r.groupby("home_id").res.agg(["sum", "size"])
    return (agg["sum"] / (agg["size"] + k)).to_dict()


# ----------------------------------------------------------------------------------------------- walk-forward
def walk_season(g: pd.DataFrame, cfg: Cfg, prior: dict, idx, n, prev_info=None, dates=None):
    """Raw predictions for every game of the season (or only games on `dates`), each from ratings fitted on games
    strictly before its date.  Returns a DataFrame keyed by game_id."""
    out = []
    use_dates = sorted(g.date.unique()) if dates is None else sorted(dates)
    for d in use_dates:
        d = pd.Timestamp(d)
        day = g[g.date == d]
        if not len(day):
            continue
        pri = prior
        feats = None
        if cfg.variant == "full" and prev_info is not None:
            feats = prev_info["roster"].at(d)
            pri = prior_from(prev_info["r"], prev_info["idx"], idx, n, feats, cfg, prev_info["hca"])
        r = fit_ratings(g, idx, n, d, cfg, pri)
        h = _map(day.home_id.values, day.home_d1.values, idx, n)
        a = _map(day.away_id.values, day.away_d1.values, idx, n)
        ph, pa, poss = raw_predict(r, h, a, day.neutral.values)
        out.append(pd.DataFrame({"game_id": day.game_id.values, "raw_h": ph, "raw_a": pa, "raw_poss": poss,
                                 "prior_net_h": pri["O"][h] - pri["D"][h], "prior_net_a": pri["O"][a] - pri["D"][a]}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def context_features(g: pd.DataFrame) -> pd.DataFrame:
    """Rest days and games played before each game (date-strict, from the schedule of completed games)."""
    long = pd.concat([g[["game_id", "season", "date", "home_id"]].rename(columns={"home_id": "team"}).assign(side="h"),
                      g[["game_id", "season", "date", "away_id"]].rename(columns={"away_id": "team"}).assign(side="a")])
    long = long.sort_values(["season", "team", "date", "game_id"])
    grp = long.groupby(["season", "team"])
    long["n_before"] = grp.cumcount()
    # same-date double headers do not exist in practice; rest from the previous dated game
    long["rest"] = (long.date - grp.date.shift()).dt.days.fillna(10).clip(upper=10)
    w = long.pivot_table(index="game_id", columns="side", values=["n_before", "rest"], aggfunc="first")
    w.columns = [f"{a}_{b}" for a, b in w.columns]
    return w.reset_index()


# ----------------------------------------------------------------------------------------------- drivers
def season_finals(games: pd.DataFrame):
    return {S: final_fit(games[games.season == S]) for S in sorted(games.season.unique())}


def fit_prior_coefs(games, finals, st, pret, seasons, q=0.5) -> dict:
    """OLS (no intercept, rating deviations) of season-S final ratings on S-1 ratings (base) and on S-1 ratings x
    end-of-season continuity + transfer-in quality (full).  Fitted on `seasons` only, then frozen."""
    rows = []
    for S in seasons:
        idx0, _, r0, _ = finals[S - 1]
        idx1, _, r1, _ = finals[S]
        pm_s = st["_pm"][st["_pm"].season == S]
        rbt = {t: (r0["O"][i], r0["D"][i], r0["T"][i]) for t, i in idx0.items()}
        f = RosterState(S, pm_s, st["st"], rbt, pret, q).at(None)
        for t, i in idx1.items():
            j = idx0.get(t)
            if j is None or t not in f.index:
                continue
            rows.append((r1["O"][i], r1["D"][i], r1["T"][i], r0["O"][j], r0["D"][j], r0["T"][j],
                         f.at[t, "c"], f.at[t, "tr"], f.at[t, "inO"], f.at[t, "inD"], f.at[t, "inT"]))
    R = np.array(rows)
    co = {}
    for k, key in enumerate("ODT"):
        y, x = R[:, k], R[:, 3 + k]
        co["r" + key] = float(x @ y / (x @ x))
        X = np.c_[x, x * R[:, 6], R[:, 7] * R[:, 8 + k]]
        co[key] = [float(v) for v in np.linalg.lstsq(X, y, rcond=None)[0]]
    co["n_team_seasons"] = len(R)
    return co


def walk_forward(games: pd.DataFrame, finals: dict, cfg: Cfg, seasons, st=None, pret=None, dates_by_season=None):
    """Raw walk-forward predictions for the given seasons. st = {"st": season table, "_pm": player minutes}."""
    out = []
    for S in seasons:
        g = games[games.season == S]
        idx, n = team_index(g)
        idx0, _, r0, _ = finals[S - 1]
        resid = [finals[s][3] for s in range(max(min(finals), S - 5), S)]
        hca_team = team_hca(resid, cfg.hca_k)
        prev_info = None
        if cfg.variant == "full":
            rbt = {t: (r0["O"][i], r0["D"][i], r0["T"][i]) for t, i in idx0.items()}
            rs = RosterState(S, st["_pm"][st["_pm"].season == S], st["st"], rbt, pret, cfg.q_unseen)
            prev_info = {"r": r0, "idx": idx0, "hca": r0["hca"], "roster": rs}
        prior = prior_from(r0, idx0, idx, n, None, Cfg(variant="base", coef=cfg.coef, new_team_pct=cfg.new_team_pct), r0["hca"])
        dts = None if dates_by_season is None else dates_by_season.get(S)
        p = walk_season(g, cfg, prior, idx, n, prev_info=prev_info, dates=dts)
        if not len(p):
            continue
        gg = g.set_index("game_id").loc[p.game_id]
        p["hca_team"] = np.where(gg.neutral.values | ~gg.home_d1.values, 0.0,
                                 [hca_team.get(int(t), 0.0) for t in gg.home_id.values])
        p["season"] = S
        out.append(p)
    return pd.concat(out, ignore_index=True)
