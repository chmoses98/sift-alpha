"""Phase 16 CBB early-season experiment (research only; nothing here touches production).

Arms (all share the #53 engine `cbb_p15_model.py`, copied verbatim from PR #53, LAM=8, tau=90, prior coefs
fitted on 2008-22 exactly as #53; layers fitted on DEV 2010-2025; holdout 2026 + 2027-to-date scored once):
  A  = #53 'full' (continuity learned from box appearances as of d; transfers only once seen).
  B  = (i) preseason roster known from day 1: membership from the preseason-features builder
       (2027: official ESPN roster snapshot before first tip, PIT; <=2026: box-appearance proxy, hindsight membership).
       Non-members contribute 0 continuity; members (incl. transfers) count from day 1.
  C  = B + (iii) game-count x roster-turnover term in the margin / total variance regression (calibration only).
Usage: python cbb_p16_exp.py <derived_dir> <roster_snapshot_dir> <prod_parquet> <work_dir>
"""
from __future__ import annotations

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
import json  # noqa: E402
import sys  # noqa: E402
from multiprocessing import Pool  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import norm  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import cbb_p15_model as M  # noqa: E402

from cbb_edge.rosters.preseason_features import snapshot_rosters  # noqa: E402

LAM, TAU = 8.0, 90.0
DEV = list(range(2010, 2026))
HOLD = [2026, 2027]
EARLY = 10
_G: dict = {}


class KnownRoster(M.RosterState):
    """Roster membership known before the season: members are 'seen' from day 1, non-members never return."""

    def __init__(self, S, pm_season, st, prev_ratings, pret, q, members: pd.DataFrame):
        start = pm_season.date.min() - pd.Timedelta(days=1)
        fake = members[["team_id", "athlete_id"]].assign(season=S, game_id=-1, date=start, minutes=0.0)
        super().__init__(S, pd.concat([fake, pm_season], ignore_index=True), st, prev_ratings, pret, q)
        self.team_dates = pm_season[["team_id", "game_id", "date"]].drop_duplicates()
        self.pairs_prev["pret"] = 0.0


def members_for(S, pm_s):
    if S == 2027:  # official preseason roster (PIT) U players actually seen (they enter at their first game)
        return _G["official"]
    return pm_s.groupby(["team_id", "athlete_id"], as_index=False).size()  # hindsight membership proxy


def wf(arm, S):
    games, finals, stt, pret, co = (_G[k] for k in ("games", "finals", "st", "pret", "co"))
    cfg = M.Cfg(variant="full", coef=co, lam_prior=LAM, lam_tempo=LAM, tau=TAU)
    if arm == "A":
        return M.walk_forward(games, finals, cfg, [S], st=stt, pret=pret).assign(arm="A")
    orig = M.RosterState
    pm_s = stt["_pm"][stt["_pm"].season == S]
    mem = members_for(S, pm_s)
    M.RosterState = lambda S_, pm, st, r, pr, q: KnownRoster(S_, pm, st, r, pr, q, mem)
    try:
        p = M.walk_forward(games, finals, cfg, [S], st=stt, pret=pret)
        g = games[games.season == S]
        idx0, _, r0, _ = finals[S - 1]
        rbt = {t: (r0["O"][i], r0["D"][i], r0["T"][i]) for t, i in idx0.items()}
        f = M.RosterState(S, pm_s, stt["st"], rbt, pret, 0.5).at(g.date.min())
    finally:
        M.RosterState = orig
    turn = (1 - f.c.clip(0, 1) + f.tr.clip(0, 1)).to_dict()
    gg = g.set_index("game_id").loc[p.game_id]
    p["turn"] = [turn.get(int(h), 1.0) + turn.get(int(a), 1.0) for h, a in zip(gg.home_id, gg.away_id, strict=True)]
    return p.assign(arm="B")


def _job(a):
    return wf(*a)


# ------------------------------------------------------------------------------------------------- layers (from #53)
def design(d, var_turn=False):
    rm, rt = d.raw_h - d.raw_a, d.raw_h + d.raw_a
    one = np.ones(len(d))
    e = 1.0 / (1.0 + np.minimum(d.n_before_h, d.n_before_a).values)
    rest = np.clip(d.rest_h - d.rest_a, -4, 4).values
    b2b = (d.rest_h <= 1).astype(float).values - (d.rest_a <= 1).astype(float).values
    Xm = np.c_[one, rm, d.hca_team.values, rest, b2b]
    Xt = np.c_[one, rt, e, rt * e]
    Vm, Vt = np.c_[one, e, np.abs(rm)], np.c_[one, e, rt]
    if var_turn:
        Vm, Vt = np.c_[Vm, e * d.turn.values], np.c_[Vt, e * d.turn.values]
    return Xm, Xt, Vm, Vt


def ols(X, y):
    return np.linalg.lstsq(X, y, rcond=None)[0]


def fit_layer(d, var_turn=False):
    Xm, Xt, Vm, Vt = design(d, var_turn)
    m, t = (d.home_pts - d.away_pts).values, (d.home_pts + d.away_pts).values
    bm, bt = ols(Xm, m), ols(Xt, t)
    return {"bm": bm, "bt": bt, "vm": ols(Vm, (m - Xm @ bm) ** 2), "vt": ols(Vt, (t - Xt @ bt) ** 2)}


def apply_layer(d, P, var_turn=False):
    Xm, Xt, Vm, Vt = design(d, var_turn)
    return pd.DataFrame({"game_id": d.game_id.values, "mu_m": Xm @ P["bm"], "mu_t": Xt @ P["bt"],
                         "sd_m": np.sqrt(np.maximum(Vm @ P["vm"], 25.0)), "sd_t": np.sqrt(np.maximum(Vt @ P["vt"], 36.0))})


# ------------------------------------------------------------------------------------------------- metrics
def per_game(F, y):
    p = np.clip(norm.cdf(F.mu_m / F.sd_m), 1e-4, 1 - 1e-4)
    w = (y.m > 0).astype(float)
    return pd.DataFrame({"ae_m": np.abs(y.m - F.mu_m), "ae_t": np.abs(y.t - F.mu_t),
                         "ll": -(w * np.log(p) + (1 - w) * np.log(1 - p)), "br": (p - w) ** 2, "p": p, "w": w,
                         "z": (y.m - F.mu_m) / F.sd_m})


def slope(p, w):
    from sklearn.linear_model import LogisticRegression
    x = np.log(p / (1 - p)).reshape(-1, 1)
    return float(LogisticRegression(C=1e6).fit(x, w).coef_[0, 0])


def summarize(Q, others, rng, B=1000):
    """Q: arm -> per-game frame (aligned rows). Point metrics + game-bootstrap CI of deltas vs each `others` pair."""
    n = len(next(iter(Q.values())))
    idx = rng.integers(0, n, (B, n))
    out = {"n": n}
    for a, q in Q.items():
        out[a] = {k: round(float(q[k].mean()), 4) for k in ("ae_m", "ae_t", "ll", "br")}
        out[a]["slope"] = round(slope(q.p.values, q.w.values), 3)
        out[a]["z_sd"] = round(float(q.z.std()), 3)
    for a, b in others:
        dd = {}
        for k in ("ae_m", "ae_t", "ll", "br"):
            diff = (Q[a][k] - Q[b][k]).values
            bs = diff[idx].mean(1)
            dd[k] = [round(float(diff.mean()), 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)]
        out[f"{a}-{b}"] = dd
    return out


def main():
    derived, snapdir, prodp, work = (Path(x) for x in sys.argv[1:5])
    work.mkdir(parents=True, exist_ok=True)
    games = pd.read_parquet(derived / "cbb_games.parquet")
    pm = pd.read_parquet(derived / "cbb_player_minutes.parquet")
    finals = M.season_finals(games)
    st = M.player_tables(pm)
    pret = M.return_rates(st, range(2008, 2022))
    stt = {"st": st, "_pm": pm}
    co = M.fit_prior_coefs(games, finals, stt, pret, range(2008, 2023))
    g27 = games[games.season == 2027]
    pm27 = pm[pm.season == 2027]
    first = pm27.merge(g27[["game_id", "start"]], on="game_id").groupby("team_id").start.min()
    off = snapshot_rosters(sorted(snapdir.glob("*.jsonl")), first, 2027)
    _G.update(games=games, finals=finals, st=stt, pret=pret, co=co, official=off[["team_id", "athlete_id"]])
    raw_f = work / "wf_raw.parquet"
    if raw_f.exists():
        raw = pd.read_parquet(raw_f)
    else:
        jobs = [(a, s) for s in range(2027, 2009, -1) for a in ("A", "B")]
        with Pool(4) as pool:
            raw = pd.concat(pool.map(_job, jobs, chunksize=1), ignore_index=True)
        raw.to_parquet(raw_f)
    ctx = M.context_features(games)
    D = {}
    for a in ("A", "B"):
        d = raw[raw.arm == a].merge(games, on=["game_id", "season"]).merge(ctx, on="game_id")
        D[a] = d[d.home_d1 & d.away_d1].reset_index(drop=True)
    PA = fit_layer(D["A"][D["A"].season.isin(DEV)])
    PB = fit_layer(D["B"][D["B"].season.isin(DEV)])
    PC = fit_layer(D["B"][D["B"].season.isin(DEV)], var_turn=True)
    F = {"A": apply_layer(D["A"], PA), "B": apply_layer(D["B"], PB), "C": apply_layer(D["B"], PC, var_turn=True)}
    base = D["B"][["game_id", "season", "n_before_h", "n_before_a", "home_pts", "away_pts", "home_id", "away_id"]]
    # production (pure-0.2.0 incumbent, last pre-tip archived record), oriented to ESPN home
    prod = pd.read_parquet(prodp)
    prod = prod.merge(games[["game_id", "home_id", "away_id"]], on="game_id")
    prod = prod[prod.oriented]
    F["P"] = pd.DataFrame({"game_id": prod.game_id, "mu_m": prod.margin, "mu_t": prod.total, "sd_m": prod.margin_sd,
                           "sd_t": prod.total_sd})
    rng = np.random.default_rng(16)
    res = {"layers_fit_on": "2010-2025 (DEV)", "prior_coefs": {k: v for k, v in co.items()}, "variance_coef_C": {
        "vm": PC["vm"].round(3).tolist(), "vt": PC["vt"].round(3).tolist()}}
    for S in (2026, 2027, "DEV"):
        for sl in ("early", "all"):
            b = base[base.season.isin(DEV)] if S == "DEV" else base[base.season == S]
            if sl == "early":
                b = b[np.minimum(b.n_before_h, b.n_before_a) < EARLY]
            arms = ["A", "B", "C"] + (["P"] if S == 2027 else [])
            ids = set(b.game_id)
            for a in arms:
                ids &= set(F[a].game_id)
            b = b[b.game_id.isin(ids)].sort_values("game_id")
            y = pd.DataFrame({"m": (b.home_pts - b.away_pts).values, "t": (b.home_pts + b.away_pts).values})
            Q = {a: per_game(F[a].set_index("game_id").loc[b.game_id].reset_index(), y) for a in arms}
            pairs = [("B", "A"), ("C", "B"), ("C", "A")] + ([("A", "P"), ("B", "P"), ("C", "P")] if "P" in arms else [])
            res[f"{S}_{sl}"] = summarize(Q, pairs, rng)
            print(S, sl, json.dumps(res[f"{S}_{sl}"])[:600])
    (work / "results.json").write_text(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    main()
