"""Operation Data Foundation, NHL vertical slice: independent joint-score challenger ``alpha-nhl-joint-0.1``.

RESEARCH_ONLY. One coherent joint distribution of the regulation score drives every game market:

1. Team strength   walk-forward, exponentially weighted, shrunk-to-league xG rates (5v5 offence/defence per 60, power-play
                   xG for and penalty-kill xG against per game = rate x penalty time), a regressed finishing term
                   (goals vs xG, for and against), fitted home ice and back-to-back flags. Log-linear Poisson GLM of
                   REGULATION goals with a walk-forward league scoring offset.
2. Joint score     bivariate Poisson (shared component) x margin weights exp(theta0) on ties and exp(theta1) on one-goal
                   margins (the pulled-goalie endgame moves mass from one-goal margins to ties and two-goal margins;
                   empty-net goals are part of the regulation target and are absorbed here, never modelled separately).
3. OT/SO           P(home wins | regulation tie) = 0.5 + k * log(lam_home / lam_away); the winner gets +1 goal.
4. Markets         moneyline, overtime, totals ladder, puck line, team totals are all sums over the SAME final-score pmf.

Point in time: a game's features use only games with an earlier game_date. Every tunable parameter is fitted on seasons
<= 2023 (season = start year); seasons 2024 and 2025 are untouched test cohorts. Raw rows are read from the owner's
NHL repository under ``contract.repos_dir()`` and never written here: only aggregates, digests and row counts.

``python -m alpha_engine.foundation.nhl_joint`` regenerates the evaluation deterministically (seeded bootstrap).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from .contract import (EVAL_SCHEMA, OPS, brier_rows, calibration_slope, crps_pmf, holm, logloss_rows,
                       paired_cluster_bootstrap, repos_dir, sha256_file, validate_evaluation, verdict_from, write_json)

CHALLENGER_ID = "alpha-nhl-joint-0.1"
INCUMBENT_ID = "DATA_ONLY_V1 (nhl-sim-1.1)"
REPO = "chmoses98/NHL-edge-finder"
SOURCE_COMMIT = "de1c36a10b7d593e17f327c9217906b6b915fb4f"
OUT = OPS / "NHL" / CHALLENGER_ID
K = 13  # regulation goals support 0..12 per team
FIT_FIRST, VAL_FIRST, TRAIN_LAST = 2009, 2019, 2023  # 2008 is rating burn-in only
TEST_SEASONS = (2024, 2025)
FRANCHISE = {11: 52, 27: 68, 53: 68, 59: 68}  # ATL->WPG, PHX->ARI->UHC->UTA share one rating history
KALSHI_ALIAS = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL", "UHC": "UTA", "MON": "MTL", "WAS": "WSH"}
ARCH = {"ml": ["NHL:game_moneyline_puckline"], "tot": ["NHL:game_total_and_team_total"], "ev": ["NHL:game_events"]}
REF_V1, REF_SIM2, REF_MKT = "incumbent:DATA_ONLY_V1", "shadow:SIM2", "market:kalshi_mid_T-60"
STAT_COLS = ["n", "t5", "xf5", "xa5", "xfpp", "xapk", "tpp", "tpk", "tall", "xfall", "xaall", "gf", "xff", "ga", "xaf"]
FIN_COLS = (11, 12, 13, 14)
FEATS = {"full": ["home", "off5", "def5", "pp", "pk", "fin_o", "fin_d", "b2b_t", "b2b_o"],
         "no_special_teams_split": ["home", "offall", "defall", "fin_o", "fin_d", "b2b_t", "b2b_o"],
         "no_finishing": ["home", "off5", "def5", "pp", "pk", "b2b_t", "b2b_o"],
         "no_rest": ["home", "off5", "def5", "pp", "pk", "fin_o", "fin_d"]}
HP0 = {"hl": 30.0, "k_prior": 10.0, "carry": 0.6, "xg": "raw", "hl_fin": 80.0, "m_fin": 150.0}
HP_GRID = {"hl": [10.0, 15.0, 20.0, 30.0, 45.0, 70.0, 110.0, 200.0], "k_prior": [2.0, 5.0, 10.0, 20.0, 40.0, 80.0, 160.0],
           "carry": [0.2, 0.4, 0.6, 0.8, 1.0], "xg": ["raw", "sva", "fsva"], "hl_fin": [40.0, 80.0, 160.0, 320.0, 1000.0],
           "m_fin": [50.0, 150.0, 400.0, 1000.0, 2500.0, 6000.0]}
VERDICT_RULE = ("verdict_from(ci_lo, ci_hi, p_holm, replicated) for LOSS metrics (diff = challenger - reference, lower is better): "
                "VALIDATED_IMPROVEMENT needs the 95% paired game-cluster bootstrap CI entirely below 0, Holm-adjusted p < 0.05 AND the "
                "sign of improvement replicated in BOTH chronological cohorts (2024, 2025); CI below 0 and p_holm < 0.05 without "
                "replication is IMPROVED_NOT_VALIDATED; CI entirely above 0 with p_holm < 0.05 is NOT_IMPROVED; everything else "
                "INCONCLUSIVE.")


# ====================================================================== pure numpy core (unit-tested on synthetic data)
def regulation_scores(home_score, away_score, last_period_type):
    """Regulation score from the final score: an OT/SO game was tied after 60 minutes and the winner got exactly +1."""
    h = np.asarray(home_score, float); a = np.asarray(away_score, float)
    extra = np.array([str(x) in ("OT", "SO") for x in last_period_type])
    return (h - (extra & (h > a))).astype(int), (a - (extra & (a > h))).astype(int), extra.astype(int)


def walk_forward_state(team, season, X, decay, carry):
    """Pre-game exponentially weighted sums. Rows MUST be in chronological order with at most one game per team per date,
    so ``out[i]`` only contains that team's rows with an earlier date. State is multiplied by ``carry`` at a season change
    and by ``decay`` after each game; rows with NaN stats do not update the state."""
    X = np.asarray(X, float); out = np.zeros_like(X); decay = np.asarray(decay, float); carry = np.asarray(carry, float)
    ok = ~np.isnan(X).any(1); state, last = {}, {}
    for i in range(len(X)):
        t = team[i]; s = state.get(t)
        if s is None:
            s = np.zeros(X.shape[1])
        elif last[t] != season[i]:
            s = s * carry
        out[i] = s
        if ok[i]:
            s = s * decay + X[i]
        state[t] = s; last[t] = season[i]
    return out


def trailing_league(day, M, window=365):
    """Per-row league means of ``M`` over rows with ``day - window <= d < day`` (strictly earlier dates only)."""
    day = np.asarray(day); M = np.asarray(M, float); ok = ~np.isnan(M).any(1)
    ud = np.unique(day); pos = np.searchsorted(ud, day)
    sums = np.zeros((len(ud), M.shape[1])); cnt = np.zeros(len(ud))
    np.add.at(sums, pos[ok], M[ok]); np.add.at(cnt, pos[ok], 1.0)
    cs = np.vstack([np.zeros((1, M.shape[1])), np.cumsum(sums, 0)]); cc = np.concatenate([[0.0], np.cumsum(cnt)])
    hi = np.searchsorted(ud, day, side="left"); lo = np.searchsorted(ud, day - window, side="left")
    n = cc[hi] - cc[lo]
    with np.errstate(invalid="ignore", divide="ignore"):
        out = (cs[hi] - cs[lo]) / n[:, None]
    out[n < 200] = np.nan  # too thin: filled below with the first usable value (2008 burn-in only, never fitted or tested)
    good = np.flatnonzero(~np.isnan(out).any(1))
    if len(good):
        first = out[good[0]].copy()
        out[np.isnan(out).any(1)] = first
    return out


def poisson_glm(X, y, offset=None, iters=50):
    """Poisson log-link GLM by Newton/IRLS. Returns beta."""
    X = np.asarray(X, float); y = np.asarray(y, float); off = np.zeros(len(y)) if offset is None else np.asarray(offset, float)
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        mu = np.exp(np.clip(X @ b + off, -20, 20))
        step = np.linalg.solve(X.T @ (X * mu[:, None]) + 1e-9 * np.eye(X.shape[1]), X.T @ (y - mu))
        b += step
        if np.max(np.abs(step)) < 1e-10:
            break
    return b


def poisson_deviance_rows(y, mu):
    y = np.asarray(y, float); mu = np.asarray(mu, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(y > 0, y * np.log(y / mu), 0.0)
    return 2 * (t - (y - mu))


def nelder_mead(f, x0, step=0.1, iters=400, tol=1e-9):
    """Small deterministic Nelder-Mead (no scipy dependency)."""
    x0 = np.asarray(x0, float); n = len(x0)
    sim = np.vstack([x0] + [x0 + step * np.eye(n)[i] for i in range(n)]); fs = np.array([f(p) for p in sim])
    for _ in range(iters):
        o = np.argsort(fs, kind="stable"); sim, fs = sim[o], fs[o]
        if abs(fs[-1] - fs[0]) < tol:
            break
        c = sim[:-1].mean(0); xr = c + (c - sim[-1]); fr = f(xr)
        if fr < fs[0]:
            xe = c + 2 * (c - sim[-1]); fe = f(xe)
            sim[-1], fs[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < fs[-2]:
            sim[-1], fs[-1] = xr, fr
        else:
            xc = c + 0.5 * (sim[-1] - c); fc = f(xc)
            if fc < fs[-1]:
                sim[-1], fs[-1] = xc, fc
            else:
                sim[1:] = sim[0] + 0.5 * (sim[1:] - sim[0]); fs[1:] = [f(p) for p in sim[1:]]
    o = int(np.argmin(fs))
    return sim[o], float(fs[o])


def _pois(lam, k=K):
    lam = np.clip(np.asarray(lam, float), 1e-9, None)[:, None]; x = np.arange(k)[None, :]
    lg = np.cumsum(np.concatenate([[0.0], np.log(np.arange(1, k))]))[None, :]
    return np.exp(x * np.log(lam) - lam - lg)


def joint_reg_pmf(lam_h, lam_a, c3=0.0, th0=0.0, th1=0.0, delta=0.0, k=K):
    """Regulation score pmf, shape (n, k, k) indexed [game, home goals, away goals].
    Bivariate Poisson with shared component ``c3`` and marginal means ``lam * exp(delta)``, multiplied by exp(th0) on the
    diagonal (ties) and exp(th1) on one-goal margins, renormalised."""
    lh = np.asarray(lam_h, float) * math.exp(delta); la = np.asarray(lam_a, float) * math.exp(delta)
    c = np.minimum(max(float(c3), 0.0), 0.8 * np.minimum(lh, la))
    pa, pb, pc = _pois(lh - c, k), _pois(la - c, k), _pois(c, k)
    P = np.zeros((len(lh), k, k))
    for j in range(k):
        if j > 0 and float(pc[:, j].max()) < 1e-12:
            break
        P[:, j:, j:] += pc[:, j, None, None] * pa[:, :k - j, None] * pb[:, None, :k - j]
    d = np.abs(np.arange(k)[:, None] - np.arange(k)[None, :])
    P = P * np.where(d == 0, math.exp(th0), np.where(d == 1, math.exp(th1), 1.0))[None]
    return P / P.sum((1, 2), keepdims=True)


def final_pmf(reg, p_ot_home):
    """Final-score pmf (n, k+1, k+1): a regulation tie (i, i) becomes (i+1, i) w.p. p_ot_home else (i, i+1)."""
    n, k, _ = reg.shape; F = np.zeros((n, k + 1, k + 1)); F[:, :k, :k] = reg
    p = np.asarray(p_ot_home, float); i = np.arange(k)
    diag = reg[:, i, i]; F[:, i, i] = 0.0
    F[:, i + 1, i] += diag * p[:, None]; F[:, i, i + 1] += diag * (1 - p)[:, None]
    return F


def markets_from(reg, p_ot_home):
    """Every market from the one joint distribution. Returns a dict of arrays (probabilities and pmfs)."""
    F = final_pmf(reg, p_ot_home); n, m, _ = F.shape; k = reg.shape[1]
    x = np.arange(m)[:, None]; y = np.arange(m)[None, :]
    tot = np.stack([F[:, (x + y) == s].sum(1) for s in range(2 * m - 1)], 1)
    mar = np.stack([F[:, (x - y) == d].sum(1) for d in range(-(m - 1), m)], 1)  # index d + (m-1)
    hp, ap = F.sum(2), F.sum(1); i = np.arange(k)
    rt = np.stack([reg[:, (np.arange(k)[:, None] + np.arange(k)[None, :]) == s].sum(1) for s in range(2 * k - 1)], 1)
    return {"final": F, "total_pmf": tot, "margin_pmf": mar, "margin_offset": m - 1, "home_pmf": hp, "away_pmf": ap,
            "p_home_win": F[:, (x > y)].sum(1), "p_reg_tie": reg[:, i, i].sum(1),
            "p_home_reg_win": reg[:, np.arange(k)[:, None] > np.arange(k)[None, :]].sum(1),
            "exp_total": tot @ np.arange(tot.shape[1]), "exp_margin": mar @ np.arange(-(m - 1), m),
            "exp_reg_total": rt @ np.arange(rt.shape[1])}


def p_over(pmf, strike):
    """P(X > strike) for an integer-support pmf (n, K)."""
    return pmf[:, int(math.floor(strike)) + 1:].sum(1)


def p_margin_over(mk, strike, side="home"):
    """P(team wins by more than ``strike`` goals) from the margin pmf."""
    off = mk["margin_offset"]; mar = mk["margin_pmf"]; d = np.arange(-off, off + 1)
    return mar[:, d > strike].sum(1) if side == "home" else mar[:, -d > strike].sum(1)


def ot_home_prob(lam_h, lam_a, k_ot):
    return np.clip(0.5 + k_ot * np.log(np.asarray(lam_h, float) / np.asarray(lam_a, float)), 0.02, 0.98)


def fit_joint(lam_h, lam_a, rh, ra):
    """ML fit of (c3, th0, th1, delta) on regulation scores. c3 is parameterised as u^2 >= 0."""
    rh = np.clip(rh, 0, K - 1); ra = np.clip(ra, 0, K - 1); idx = np.arange(len(rh))

    def nll(p):
        P = joint_reg_pmf(lam_h, lam_a, p[0] ** 2, p[1], p[2], p[3])
        return float(-np.mean(np.log(P[idx, rh, ra] + 1e-300)))
    x, v = nelder_mead(nll, [0.2, 0.0, 0.0, 0.0], step=0.1, iters=300, tol=1e-9)
    return {"c3": float(x[0] ** 2), "theta_tie": float(x[1]), "theta_one_goal": float(x[2]), "delta": float(x[3]), "train_nll": v,
            "train_nll_independent": nll([0.0, 0.0, 0.0, 0.0])}


def fit_ot_k(lam_h, lam_a, home_won, grid=None):
    """1-D ML for P(home wins | tie) = 0.5 + k * log(lam_h / lam_a) on training ties."""
    grid = np.linspace(-0.5, 1.5, 401) if grid is None else grid
    y = np.asarray(home_won, float)
    ll = [float(np.mean(logloss_rows(ot_home_prob(lam_h, lam_a, k), y))) for k in grid]
    return float(grid[int(np.argmin(ll))]), float(min(ll))


def kalshi_reference_quote(end_ts, bid, ask, start_ts, lead_s=3600, empty=None):
    """Mid of the LAST candle with end_period_ts <= start - lead, only if two-sided (0 < bid <= ask < 1).
    Returns (mid or None, reason, age_s)."""
    end_ts = np.asarray(end_ts, float); cut = start_ts - lead_s
    ok = ~np.isnan(end_ts) & (end_ts <= cut)
    if empty is not None:
        ok &= ~np.asarray(empty, bool)
    if not ok.any():
        return None, "no_candle_before_cutoff", None
    j = np.flatnonzero(ok)[int(np.argmax(end_ts[ok]))]
    b, a = float(bid[j]), float(ask[j])
    if not (b == b and a == a and b > 0 and a < 1 and a >= b):
        return None, "not_two_sided", float(cut - end_ts[j])
    return (b + a) / 2, "ok", float(cut - end_ts[j])


def parse_kalshi_ticker(ticker):
    """'KXNHLSPREAD-25DEC01ANASTL-ANA1' -> (series, 'YYYY-MM-DD', teams 'ANASTL', suffix team 'ANA', suffix number '1')."""
    parts = str(ticker).split("-")
    if len(parts) != 3 or len(parts[1]) < 11:
        return None
    ev, suf = parts[1], parts[2]
    mon = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}.get(ev[2:5])
    if mon is None or not ev[:2].isdigit() or not ev[5:7].isdigit():
        return None
    team = suf.rstrip("0123456789")
    return parts[0], f"20{ev[:2]}-{mon:02d}-{ev[5:7]}", ev[7:], team, suf[len(team):]


def split_teams(teams, away, home):
    """True when the concatenated Kalshi codes are exactly (away, home) after alias resolution."""
    for cut in (2, 3, 4):
        a, h = teams[:cut], teams[cut:]
        if KALSHI_ALIAS.get(a, a) == away and KALSHI_ALIAS.get(h, h) == home:
            return True
    return False


# ====================================================================== feature construction (pandas, lazy import)
def resolve_home(mp, games):
    """MoneyPuck's home/away flag is wrong for some relocated-franchise games (both rows flagged AWAY). The home flag is
    re-derived from the official record: a row is home when its (franchise-mapped) team_id equals the official home id;
    rows with a NULL MoneyPuck team_id keep the MoneyPuck flag. Returns (mp copy with corrected ``home``, rows changed)."""
    ids = games.drop_duplicates("game_id").set_index("game_id")[["home_team_id", "away_team_id"]].astype(float)
    fr = lambda a: np.array([FRANCHISE.get(int(x), int(x)) if x == x else -1 for x in a])
    tid = fr(mp["team_id"].astype(float).values)
    hid = fr(ids["home_team_id"].reindex(mp["game_id"].values).values); aid = fr(ids["away_team_id"].reindex(mp["game_id"].values).values)
    old = mp["home"].values.astype(bool)
    new = np.where((tid >= 0) & (tid == hid), True, np.where((tid >= 0) & (tid == aid), False, old))
    out = mp.copy(); out["home"] = new
    return out, int((new != old).sum())


def build_team_games(games, mp):
    """Two rows per final regular-season game (away row then home row), chronologically sorted, with regulation goals and
    MoneyPuck situation stats. Team identity comes from the official game record (home flag), not from MoneyPuck ids."""
    import pandas as pd
    g = games[(games["game_type"] == 2) & games["final"].astype(bool)].copy()
    rh, ra, extra = regulation_scores(g["home_score"].astype(float), g["away_score"].astype(float), g["last_period_type"])
    g["rh"], g["ra"], g["extra"] = rh, ra, extra
    g["day"] = (pd.to_datetime(g["game_date"]).values.astype("datetime64[D]") - np.datetime64("2000-01-01")).astype(int)
    rows = []
    for home in (0, 1):
        t, o = ("home", "away") if home else ("away", "home")
        rows.append(pd.DataFrame({"game_id": g["game_id"].values, "day": g["day"].values, "season": g["season"].values, "home": home,
                                  "team": g[f"{t}_team_id"].astype(int).values, "opp": g[f"{o}_team_id"].astype(int).values,
                                  "rg": g["rh" if home else "ra"].values, "rga": g["ra" if home else "rh"].values}))
    tg = pd.concat(rows, ignore_index=True)
    tg["team"] = tg["team"].replace(FRANCHISE); tg["opp"] = tg["opp"].replace(FRANCHISE)
    m = resolve_home(mp, games)[0]
    m = m[m["game_type"] == 2]
    stats = [c for c in m.columns if c not in ("game_id", "home", "situation", "game_type", "season", "game_date", "team_id", "opp_team_id")]
    wide = m.pivot_table(index=["game_id", "home"], columns="situation", values=stats, aggfunc="first")
    wide.columns = [f"{a}_{b}" for a, b in wide.columns]; wide = wide.reset_index(); wide["home"] = wide["home"].astype(int)
    tg = tg.merge(wide, on=["game_id", "home"], how="left").sort_values(["day", "game_id", "home"], kind="stable").reset_index(drop=True)
    prev = tg.groupby("team")["day"].shift(1)
    tg["b2b"] = ((tg["day"] - prev) == 1).astype(float)
    tg["rest_days"] = (tg["day"] - prev)
    return tg


def stat_matrix(tg, xg="raw"):
    c5 = {"raw": "xGoals", "sva": "scoreVenueAdjustedxGoals", "fsva": "flurryScoreVenueAdjustedxGoals"}[xg]
    g = lambda c: tg[c].values.astype(float)
    X = np.column_stack([np.ones(len(tg)), g("iceTime_5on5"), g(f"{c5}For_5on5"), g(f"{c5}Against_5on5"), g("xGoalsFor_5on4"),
                         g("xGoalsAgainst_4on5"), g("iceTime_5on4"), g("iceTime_4on5"), g("iceTime_all"), g("xGoalsFor_all"),
                         g("xGoalsAgainst_all"), g("goalsFor_all"), g("xGoalsFor_all"), g("goalsAgainst_all"), g("xGoalsAgainst_all")])
    X[np.isnan(X).any(1)] = np.nan
    return X


def make_features(tg, hp):
    """Walk-forward team features (dict of per-row arrays, log ratios to the trailing league value) + league offsets."""
    X = stat_matrix(tg, hp["xg"]); m = X.shape[1]
    d = np.full(m, 0.5 ** (1.0 / hp["hl"])); d[list(FIN_COLS)] = 0.5 ** (1.0 / hp["hl_fin"])
    S = walk_forward_state(tg["team"].values, tg["season"].values, X, d, np.full(m, hp["carry"]))
    day = tg["day"].values
    L = trailing_league(day, X); Lreg = trailing_league(day, tg[["rg"]].values.astype(float))[:, 0]
    c = {n: i for i, n in enumerate(STAT_COLS)}; kp, mf = hp["k_prior"], hp["m_fin"]
    s = lambda n: S[:, c[n]]; l = lambda n: L[:, c[n]]
    rate = lambda num, den: np.log(((s(num) + kp * l(num)) / (s(den) + kp * l(den))) / (l(num) / l(den)))
    r_f, r_a = l("gf") / l("xff"), l("ga") / l("xaf")
    own = {"off5": rate("xf5", "t5"), "def5": rate("xa5", "t5"), "pp": rate("xfpp", "n"), "pk": rate("xapk", "n"),
           "offall": rate("xfall", "tall"), "defall": rate("xaall", "tall"),
           "fin_o": np.log((s("gf") + mf * r_f) / (r_f * (s("xff") + mf))), "fin_d": np.log((s("ga") + mf * r_a) / (r_a * (s("xaf") + mf)))}
    opp = np.arange(len(tg)) ^ 1  # rows are (away, home) pairs
    b2b = tg["b2b"].values.astype(float)
    f = {"home": tg["home"].values.astype(float), "off5": own["off5"], "def5": own["def5"][opp], "pp": own["pp"], "pk": own["pk"][opp],
         "offall": own["offall"], "defall": own["defall"][opp], "fin_o": own["fin_o"], "fin_d": own["fin_d"][opp], "b2b_t": b2b,
         "b2b_o": b2b[opp]}
    return {"f": f, "own": own, "offset": np.log(Lreg), "league_reg_goals": Lreg, "games_w": S[:, 0], "L": L, "S": S,
            "pp_rate60": 3600 * (s("xfpp") + kp * l("xfpp")) / (s("tpp") + kp * l("tpp"))}


def design(F, names):
    return np.column_stack([np.ones(len(F["offset"]))] + [F["f"][n] for n in names])


def fit_glm(tg, F, names, mask):
    X = design(F, names); b = poisson_glm(X[mask], tg["rg"].values[mask], F["offset"][mask])
    return b


def predict_lam(F, names, beta):
    return np.exp(design(F, names) @ beta + F["offset"])


def search_hyper(tg, log=print):
    """Coordinate descent on validation deviance: GLM fitted on seasons FIT_FIRST..VAL_FIRST-1, scored on VAL_FIRST..TRAIN_LAST.
    Nothing after TRAIN_LAST is ever read here."""
    season = tg["season"].values; y = tg["rg"].values
    fit = (season >= FIT_FIRST) & (season < VAL_FIRST); val = (season >= VAL_FIRST) & (season <= TRAIN_LAST)
    assert season[fit | val].max() <= TRAIN_LAST
    cache = {}

    def score(hp):
        key = tuple(hp[k] for k in sorted(hp))
        if key not in cache:
            F = make_features(tg, hp); b = fit_glm(tg, F, FEATS["full"], fit)
            cache[key] = float(np.mean(poisson_deviance_rows(y[val], predict_lam(F, FEATS["full"], b)[val])))
        return cache[key]
    hp = dict(HP0); best = score(hp); trace = [{"step": "start", "val_deviance": best}]
    for sweep in range(3):
        changed = False
        for k in ["hl", "k_prior", "carry", "xg", "hl_fin", "m_fin"]:
            for v in HP_GRID[k]:
                sc = score({**hp, k: v})
                if sc < best - 1e-9:
                    best, hp, changed = sc, {**hp, k: v}, True
            trace.append({"step": f"sweep{sweep}:{k}", "value": hp[k], "val_deviance": best})
        log(f"  hyper sweep {sweep}: {hp} val_dev={best:.6f}")
        if not changed:
            break
    return hp, best, trace, len(cache)


# ====================================================================== loaders (pyarrow only here)
def _hist():
    return repos_dir() / "NHL-edge-finder" / "data" / "history"


def load_games():
    import pandas as pd
    fs = sorted((_hist() / "nhl").glob("games_*.parquet"))
    return pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True), fs


MP_COLS = ["season", "game_id", "game_date", "game_type", "team_id", "opp_team_id", "home", "situation", "iceTime", "xGoalsFor", "xGoalsAgainst",
           "goalsFor", "goalsAgainst", "scoreVenueAdjustedxGoalsFor", "scoreVenueAdjustedxGoalsAgainst",
           "flurryScoreVenueAdjustedxGoalsFor", "flurryScoreVenueAdjustedxGoalsAgainst"]


def load_moneypuck():
    import pandas as pd
    fs = sorted((_hist() / "moneypuck").glob("team_games_*.parquet"))
    return pd.concat([pd.read_parquet(f, columns=MP_COLS) for f in fs], ignore_index=True), fs


def load_goalies():
    import pandas as pd
    fs = [f for f in sorted((_hist() / "players").glob("goalies_*.parquet"))]
    cols = ["game_id", "season", "game_date", "game_type", "player_id", "team_id", "is_home", "starter", "toi_s", "saves", "shots_against"]
    return pd.concat([pd.read_parquet(f, columns=cols) for f in fs], ignore_index=True), fs


def files_digest(files):
    h = hashlib.sha256()
    for f in sorted(files):
        h.update(Path(f).name.encode()); h.update(sha256_file(f).encode())
    return h.hexdigest()


# ====================================================================== evaluation helpers
def compare(family, arch, metric, reference, p_c, p_r, y, gid, cohort, extra=None):
    """Rows for one family/metric/reference: each cohort present plus pooled. Verdicts are filled after Holm."""
    fn = brier_rows if metric == "brier" else logloss_rows
    lc, lr = fn(p_c, y), fn(p_r, y); rows = []; cohorts = sorted(set(cohort.tolist()))
    signs = {}
    for co in cohorts + (["pooled"] if len(cohorts) > 1 else []):
        m = np.ones(len(y), bool) if co == "pooled" else cohort == co
        bs = paired_cluster_bootstrap((lc - lr)[m], gid[m])
        signs[co] = bs["mean"]
        rows.append({"market_family": family, "archetypes": arch, "metric": metric, "reference": reference, "cohort": str(co),
                     "n_rows": bs["n_rows"], "n_clusters": bs["n_clusters"], "challenger": float(lc[m].mean()),
                     "reference_value": float(lr[m].mean()), "diff": bs["mean"], "ci95": [bs["lo"], bs["hi"]], "p_raw": bs["p_two_sided"],
                     **(extra or {})})
    rep = len(cohorts) == len(TEST_SEASONS) and all(signs[c] < 0 for c in cohorts)
    for r in rows:
        r["replicated"] = bool(rep)
        r["cohort_diffs"] = {str(c): signs[c] for c in cohorts}
    return rows


def finalize_verdicts(rows):
    """Holm inside each (reference, cohort) hypothesis group; the HEADLINE group is (incumbent, pooled)."""
    groups = {}
    for i, r in enumerate(rows):
        groups.setdefault((r["reference"], r["cohort"]), []).append(i)
    for (ref, co), idx in sorted(groups.items()):
        adj = holm([rows[i]["p_raw"] for i in idx])
        for i, p in zip(idx, adj):
            r = rows[i]; r["p_holm"] = float(p); r["holm_group"] = f"{ref}|{co}"; r["holm_m"] = len(idx)
            r["headline"] = bool(ref == REF_V1 and co == "pooled")
            r["verdict"] = verdict_from(r["ci95"][0], r["ci95"][1], r["p_holm"], r["replicated"])
    return rows


def reliability(p, y, bins=10):
    p = np.asarray(p, float); y = np.asarray(y, float); out = []
    e = np.linspace(0, 1, bins + 1); b = np.clip(np.digitize(p, e[1:-1]), 0, bins - 1)
    for i in range(bins):
        m = b == i
        if m.any():
            out.append({"bin": f"{e[i]:.1f}-{e[i + 1]:.1f}", "n": int(m.sum()), "mean_p": float(p[m].mean()), "observed": float(y[m].mean())})
    return out


def check(name, passed, detail):
    return {"name": name, "passed": bool(passed), "detail": str(detail)}


# ====================================================================== model wrapper
class Model:
    """Frozen parameters (all fitted on seasons <= TRAIN_LAST) and prediction for any set of game rows."""

    def __init__(self, tg, F, names, beta, joint, k_ot, extra_log=None):
        self.names, self.beta, self.joint, self.k_ot = names, beta, joint, k_ot
        lam = predict_lam(F, names, beta)
        if extra_log is not None:
            lam = lam * np.exp(extra_log)
        self.lam_a, self.lam_h = lam[0::2], lam[1::2]

    def reg(self, m):
        j = self.joint
        return joint_reg_pmf(self.lam_h[m], self.lam_a[m], j["c3"], j["theta_tie"], j["theta_one_goal"], j["delta"])

    def markets(self, m):
        return markets_from(self.reg(m), ot_home_prob(self.lam_h[m], self.lam_a[m], self.k_ot))


def fit_variant(tg, G, hp, names, train_g, independent=False, F=None):
    F = make_features(tg, hp) if F is None else F
    season = tg["season"].values; fit = (season >= FIT_FIRST) & (season <= TRAIN_LAST)
    beta = fit_glm(tg, F, names, fit); lam = predict_lam(F, names, beta); la, lh = lam[0::2], lam[1::2]
    if independent:
        joint = {"c3": 0.0, "theta_tie": 0.0, "theta_one_goal": 0.0, "delta": 0.0}
    else:
        joint = fit_joint(lh[train_g], la[train_g], G["rh"][train_g], G["ra"][train_g])
    ties = train_g & (G["extra"] == 1)
    k_ot, _ = fit_ot_k(lh[ties], la[ties], G["home_win"][ties])
    return Model(tg, F, names, beta, joint, k_ot), F


def game_frame(tg):
    h = tg.iloc[1::2]; a = tg.iloc[0::2]
    assert (h["game_id"].values == a["game_id"].values).all() and (h["home"].values == 1).all() and (a["home"].values == 0).all()
    return {"game_id": h["game_id"].values, "season": h["season"].values, "day": h["day"].values, "rh": h["rg"].values.astype(int),
            "ra": a["rg"].values.astype(int)}


def reg_nll_rows(model, m, G):
    P = model.reg(m); i = np.arange(P.shape[0])
    return -np.log(P[i, np.clip(G["rh"][m], 0, K - 1), np.clip(G["ra"][m], 0, K - 1)] + 1e-300)


# ====================================================================== Kalshi reference
def kalshi_reference(games25, log=print):
    """Pre-game T-60 mids for the 2025 regular-season cohort. Returns (quotes DataFrame, coverage dict, data entries, checks)."""
    import pandas as pd
    kd = _hist() / "kalshi"
    g = games25.copy()
    st = pd.to_datetime(g["start_time_et"]).dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    g["start_ts"] = (st.dt.tz_localize(None) - pd.Timestamp("1970-01-01")) // pd.Timedelta("1s")
    by_date = {}
    for r in g.itertuples():
        by_date.setdefault(r.game_date, []).append(r)
    core = pd.read_parquet(kd / "candles_core.parquet"); lad = pd.read_parquet(kd / "candles_ladders.parquet")
    cand = pd.concat([core, lad], ignore_index=True)
    cand_gid = cand.drop_duplicates("ticker").set_index("ticker")["game_id"].to_dict()
    cand_start = cand.drop_duplicates("ticker").set_index("ticker")["start_ts"].to_dict()
    cand = cand[cand["game_id"].isin(set(g["game_id"]))]
    groups = {t: d for t, d in cand.groupby("ticker", sort=False)}
    rows, cov, entries = [], {}, []
    n_map = n_map_agree = n_start = n_start_agree = 0
    for series in ("KXNHLGAME", "KXNHLTOTAL", "KXNHLSPREAD", "KXNHLOVERTIME", "KXNHLTEAMTOTAL"):
        f = kd / f"markets_{series}.jsonl.gz"
        ms = [json.loads(l) for l in gzip.open(f, "rt") if l.strip()] if f.exists() else []
        closes = sorted(m.get("close_time", "")[:10] for m in ms if m.get("close_time"))
        entries.append({"dataset_id": f"kalshi_markets_{series}", "repo": REPO, "path": f"data/history/kalshi/{f.name}", "rows": len(ms),
                        "first": closes[0] if closes else None, "last": closes[-1] if closes else None,
                        "sha256": sha256_file(f) if f.exists() else None, "kind": "HISTORICAL_BACKFILL", "rights_tier": "UNRESOLVED_INTERNAL_ONLY"})
        c = {"markets_in_file": len(ms), "markets_in_cohort": 0, "usable_two_sided": 0, "no_candles": 0, "no_candle_before_cutoff": 0,
             "not_two_sided": 0, "result_not_binary": 0, "side_unresolved": 0}
        for m in ms:
            pt = parse_kalshi_ticker(m.get("ticker", ""))
            if pt is None:
                continue
            _, date, teams, team, _num = pt
            game = next((r for r in by_date.get(date, []) if split_teams(teams, r.away_abbrev, r.home_abbrev)), None)
            if game is None:
                continue
            c["markets_in_cohort"] += 1
            if m["ticker"] in cand_gid:
                n_map += 1; n_map_agree += int(cand_gid[m["ticker"]] == game.game_id)
                n_start += 1; n_start_agree += int(abs(cand_start[m["ticker"]] - game.start_ts) <= 60)
            if m.get("result") not in ("yes", "no"):
                c["result_not_binary"] += 1; continue
            side = None
            if series in ("KXNHLGAME", "KXNHLSPREAD"):
                tm = KALSHI_ALIAS.get(team, team)
                side = "home" if tm == game.home_abbrev else "away" if tm == game.away_abbrev else None
                if side is None:
                    c["side_unresolved"] += 1; continue
            d = groups.get(m["ticker"])
            if d is None:
                c["no_candles"] += 1; continue
            mid, why, age = kalshi_reference_quote(d["end_period_ts"].values, d["yes_bid_close"].values, d["yes_ask_close"].values,
                                                   game.start_ts, 3600, d["_empty"].values == True)  # noqa: E712
            if mid is None:
                c[why] += 1; continue
            c["usable_two_sided"] += 1
            rows.append({"series": series, "game_id": game.game_id, "side": side, "strike": m.get("floor_strike"), "mid": mid,
                         "age_s": age, "y": int(m["result"] == "yes")})
        c["no_usable_quote"] = c["markets_in_cohort"] - c["usable_two_sided"]
        cov[series] = c
    q = pd.DataFrame(rows)
    for name, df in (("candles_core", core), ("candles_ladders", lad)):
        ts = df["end_period_ts"].dropna()
        entries.append({"dataset_id": f"kalshi_{name}", "repo": REPO, "path": f"data/history/kalshi/{name}.parquet", "rows": int(len(df)),
                        "first": str(pd.to_datetime(ts.min(), unit="s").date()), "last": str(pd.to_datetime(ts.max(), unit="s").date()),
                        "sha256": sha256_file(kd / f"{name}.parquet"), "kind": "HISTORICAL_BACKFILL", "rights_tier": "UNRESOLVED_INTERNAL_ONLY",
                        "tickers": int(df["ticker"].nunique())})
    checks = [check("kalshi_ticker_to_game_mapping_agrees_with_repo_join", n_map > 0 and n_map_agree == n_map,
                    f"{n_map_agree}/{n_map} cohort markets with candles: game_id parsed from the ticker (date + away/home codes) equals the repo's stored join"),
              check("kalshi_scheduled_start_agrees", n_start > 0 and n_start_agree / max(n_start, 1) > 0.99,
                    f"{n_start_agree}/{n_start} markets: start from games.start_time_et (ET->UTC) within 60 s of the candle file's start_ts")]
    return q, cov, entries, checks


# ====================================================================== main pipeline
def run(log=print):
    import pandas as pd
    games, gfiles = load_games(); mp, mfiles = load_moneypuck()
    hist = _hist(); docs = repos_dir() / "NHL-edge-finder" / "docs" / "research"
    v1 = pd.read_csv(docs / "walk_forward_36570274279_games.csv"); v2 = pd.read_csv(docs / "walk_forward_v2_wf2_20260929_games.csv")

    # ---------------------------------------------------------------- data-quality checks (real, on the loaded data)
    fin = games[games["final"].astype(bool)]
    reg_games = fin[fin["game_type"] == 2]
    mar = (fin["home_score"].astype(int) - fin["away_score"].astype(int)).abs()
    extra = fin["last_period_type"].isin(["OT", "SO"])
    raw_dup = int(mp.duplicated(["game_id", "home", "situation"]).sum())
    raw_dup_seasons = sorted(set(mp["season"].values[mp.duplicated(["game_id", "home", "situation"], keep=False).values].tolist()))
    mp_fixed, n_home_fixed = resolve_home(mp, games)
    mp_all = mp_fixed[mp_fixed["situation"] == "all"].merge(fin[["game_id", "home_team_id", "away_team_id", "home_score", "away_score", "last_period_type",
                                                    "game_date"]], on="game_id", how="left", suffixes=("", "_g"))
    off = np.where(mp_all["home"], mp_all["home_score"], mp_all["away_score"]).astype(float)
    won = np.where(mp_all["home"], mp_all["home_score"] > mp_all["away_score"], mp_all["away_score"] > mp_all["home_score"])
    exp_goals = off - ((mp_all["last_period_type"] == "SO").values & np.asarray(won, bool))
    rec = float((mp_all["goalsFor"].values == exp_goals).mean())
    rec_recent = float((mp_all["goalsFor"].values == exp_goals)[mp_all["season"].values >= 2014].mean())
    mism_seasons = sorted(set(mp_all["season"].values[mp_all["goalsFor"].values != exp_goals].tolist()))
    fr = lambda a: np.array([FRANCHISE.get(int(x), int(x)) if x == x else -1 for x in a])
    mp_tid = fr(mp_all["team_id"].astype("float").values)
    idm = float(np.where(mp_all["home"].values.astype(bool), mp_tid == fr(mp_all["home_team_id"].astype(float).values),
                         mp_tid == fr(mp_all["away_team_id"].astype(float).values)).mean())
    id_missing = int(mp_all["team_id"].isna().sum())
    missing_mp = reg_games[~reg_games["game_id"].isin(set(mp["game_id"]))]
    n_nonfinal = int((~games["final"].astype(bool)).sum())
    sit_counts = mp.groupby("situation").size().to_dict()

    tg = build_team_games(games, mp)
    G = game_frame(tg)
    gi = fin.set_index("game_id").loc[G["game_id"]]
    G["home_win"] = gi["home_win"].astype(int).values; G["extra"] = gi["last_period_type"].isin(["OT", "SO"]).astype(int).values
    G["hs"] = gi["home_score"].astype(int).values; G["as"] = gi["away_score"].astype(int).values
    G["total"] = G["hs"] + G["as"]; G["margin"] = G["hs"] - G["as"]
    dup_td = int(tg.duplicated(["team", "day"]).sum())
    order_ok = bool((np.diff(tg["day"].values) >= 0).all())
    stat_nan = int(np.isnan(stat_matrix(tg)).any(1).sum())
    ice = tg["iceTime_all"].dropna()
    xg_all = tg["xGoalsFor_all"].dropna()
    data_checks = [
        check("games_no_duplicate_game_id", games["game_id"].duplicated().sum() == 0, f"{len(games)} rows, 0 duplicate game_id"),
        check("games_non_final_rows_excluded", True, f"{n_nonfinal} non-final placeholder rows (unplayed if-necessary playoff games, score 0-0) dropped; "
              f"{len(reg_games)} final regular-season games kept"),
        check("regulation_score_derivable", int((extra & (mar != 1)).sum()) == 0 and int((~extra & (mar == 0)).sum()) == 0,
              f"OT/SO finals with margin != 1: {int((extra & (mar != 1)).sum())}; REG finals tied: {int((~extra & (mar == 0)).sum())} of {len(fin)} final games"),
        check("moneypuck_home_flag_unique_per_game", raw_dup == 0,
              f"RAW CHECK FAILED: {raw_dup} rows duplicate (game_id, home, situation) in seasons {raw_dup_seasons}: MoneyPuck flags BOTH teams AWAY in "
              f"{raw_dup // 4} Phoenix home games. Mitigated: home flag re-derived from the official home/away team ids ({n_home_fixed} rows corrected)"),
        check("moneypuck_no_duplicate_team_game_situation_after_fix", int(mp_fixed.duplicated(["game_id", "home", "situation"]).sum()) == 0,
              f"{len(mp)} rows; situations {sit_counts}; 0 duplicate (game_id, home, situation) after the home-flag correction"),
        check("moneypuck_goals_reconcile_with_official_score", rec > 0.995,
              f"all-situations goalsFor equals official score minus the shootout-winner goal in {rec:.4%} of {len(mp_all)} team-games "
              f"({rec_recent:.4%} for seasons >= 2014); mismatching seasons: {mism_seasons}"),
        check("moneypuck_team_id_matches_official", idm > 0.999,
              f"RAW CHECK FAILED: franchise-mapped team_id equals the official home/away id in {idm:.4%} of team-games; {id_missing} team-games have a "
              "NULL MoneyPuck team_id (Atlanta, seasons 2008-2010). Mitigated: team identity is taken from the official game record via "
              "(game_id, corrected home flag); NULL-id rows keep the MoneyPuck flag, which is unique per game for them"),
        check("moneypuck_coverage_of_final_regular_season_games", len(missing_mp) <= 5,
              f"{len(missing_mp)} final regular-season games without MoneyPuck rows (seasons {sorted(set(missing_mp['season'].tolist()))}); "
              f"they keep their outcome but do not update ratings ({stat_nan} team-game rows with missing stats)"),
        check("one_game_per_team_per_date", dup_td == 0, f"{dup_td} duplicate (team, game_date) rows: pre-game state can only contain earlier dates"),
        check("chronological_order", order_ok, "team-game table sorted by (game_date, game_id); walk-forward state is read BEFORE the game's own update"),
        check("plausibility_ranges", bool(ice.min() >= 1200 and ice.median() == 3600 and 0.3 < xg_all.min() and xg_all.max() < 12),
              f"iceTime_all min/median/max {ice.min():.0f}/{ice.median():.0f}/{ice.max():.0f} s (one 2019 row at 1200 s is a MoneyPuck partial record); "
              f"xGoalsFor_all min/mean/max {xg_all.min():.2f}/{xg_all.mean():.2f}/{xg_all.max():.2f}"),
    ]

    # ---------------------------------------------------------------- fit on <= TRAIN_LAST
    log("hyper-parameter search (validation deviance, seasons <= 2023 only)")
    hp, val_dev, trace, n_eval = search_hyper(tg, log)
    season_g = G["season"]; train_g = (season_g >= FIT_FIRST) & (season_g <= TRAIN_LAST)
    log("fitting headline model + ablations")
    full, F = fit_variant(tg, G, hp, FEATS["full"], train_g)
    variants = {"no_special_teams_split": fit_variant(tg, G, hp, FEATS["no_special_teams_split"], train_g, F=F)[0],
                "no_tie_inflation_or_correlation": fit_variant(tg, G, hp, FEATS["full"], train_g, independent=True, F=F)[0],
                "no_finishing": fit_variant(tg, G, hp, FEATS["no_finishing"], train_g, F=F)[0],
                "no_rest": fit_variant(tg, G, hp, FEATS["no_rest"], train_g, F=F)[0]}

    # leak guard: recompute features after deleting every row from the first test date onward; training features must be identical
    cut = int(tg["day"].values[tg["season"].values > TRAIN_LAST].min())
    tr_rows = tg["day"].values < cut
    F_tr = make_features(tg[tr_rows].reset_index(drop=True), hp)
    leak_diff = float(max(np.max(np.abs(F_tr["f"][n] - F["f"][n][tr_rows])) for n in FEATS["full"]))
    # and: scrambling ALL outcomes/stats of a late block must not change any earlier feature
    tg2 = tg.copy(); late = tg2["day"].values >= cut
    for ccol in [c for c in tg2.columns if c.startswith(("xGoals", "goals", "iceTime", "scoreVenue", "flurry"))] + ["rg"]:
        col = tg2[ccol].values.astype(float); col[late] = col[late][::-1] * 1.7; tg2[ccol] = col
    F2 = make_features(tg2, hp)
    first_test = np.flatnonzero(late)[0]
    same_day_ok = float(max(np.max(np.abs(F2["f"][n][~late] - F["f"][n][~late])) for n in FEATS["full"]))
    first_rows = (tg["day"].values == cut)
    first_day_ok = float(max(np.max(np.abs(F2["f"][n][first_rows] - F["f"][n][first_rows])) for n in FEATS["full"]))
    leak_checks = [
        check("leak_guard_truncation_invariance", leak_diff < 1e-12, f"features of all pre-2024-season rows are identical (max abs diff {leak_diff:.1e}) "
              "when every row from the first 2024-season date onward is removed"),
        check("leak_guard_future_perturbation", same_day_ok < 1e-12 and first_day_ok < 1e-12,
              f"perturbing all stats/outcomes from the first test date onward changes no earlier feature (max diff {same_day_ok:.1e}) and no "
              f"feature of games ON that first date (max diff {first_day_ok:.1e}; row {int(first_test)} onward perturbed)"),
        check("parameters_fitted_on_train_only", True, f"GLM/joint/OT parameters use seasons {FIT_FIRST}-{TRAIN_LAST}; hyper-parameters chosen on "
              f"validation seasons {VAL_FIRST}-{TRAIN_LAST} with the GLM fitted on {FIT_FIRST}-{VAL_FIRST - 1}; search_hyper asserts max season <= {TRAIN_LAST}"),
    ]

    # ---------------------------------------------------------------- test frame aligned to the incumbent walk-forward games
    assert (v1["game_id"].values == v2["game_id"].values).all()
    pos = pd.Series(np.arange(len(G["game_id"])), index=G["game_id"])
    tmask_idx = pos.reindex(v1["game_id"].values)
    n_missing_inc = int(tmask_idx.isna().sum())
    assert n_missing_inc == 0, "incumbent games missing from the challenger frame"
    ti = tmask_idx.values.astype(int)
    assert set(G["season"][ti].tolist()) == set(TEST_SEASONS)
    gid = G["game_id"][ti]; coh = G["season"][ti].astype(str)
    y = {"home_win": G["home_win"][ti], "ot": G["extra"][ti], "total": G["total"][ti], "margin": G["margin"][ti], "hs": G["hs"][ti], "as": G["as"][ti]}
    inc_checks = [
        check("incumbent_csv_same_games", True, f"{len(v1)} games in both incumbent CSVs, identical order; all present in the challenger frame; "
              f"cohorts {dict((str(a), int(b)) for a, b in zip(*np.unique(coh, return_counts=True)))}"),
        check("incumbent_csv_outcomes_match_official", bool((v1["y_home_win"].values == y["home_win"]).all() and (v1["y_total"].values == y["total"]).all()
              and (v1["y_overtime"].values == y["ot"]).all()), "y_home_win / y_total / y_overtime in the incumbent CSV equal the official record for every game"),
        check("incumbent_v1_columns_identical_across_csvs", float(np.abs(v1["p_home_win"] - v2["V1_p_home_win"]).max()) == 0.0
              and float(np.abs(v1["p_over_5.5"] - v2["V1_p_over_5.5"]).max()) == 0.0, "V1 probabilities in the V2 walk-forward CSV reproduce the published V1 run exactly"),
    ]
    mk = full.markets(ti)

    def fam_probs(mkt):
        """Long-form (p, y, gid, cohort) per family from a markets dict (challenger or ablation variant)."""
        o = {"moneyline": (mkt["p_home_win"], y["home_win"], gid, coh), "regulation_tie_overtime": (mkt["p_reg_tie"], y["ot"], gid, coh)}
        for s in (4.5, 5.5, 6.5, 7.5):
            o[f"total_{s}"] = (p_over(mkt["total_pmf"], s), (y["total"] > s).astype(int), gid, coh)
        o["puck_line_1.5"] = (np.concatenate([p_margin_over(mkt, 1.5, "home"), p_margin_over(mkt, 1.5, "away")]),
                              np.concatenate([(y["margin"] > 1.5), (-y["margin"] > 1.5)]).astype(int), np.concatenate([gid, gid]), np.concatenate([coh, coh]))
        for s in (2.5, 3.5):
            o[f"team_total_{s}"] = (np.concatenate([p_over(mkt["home_pmf"], s), p_over(mkt["away_pmf"], s)]),
                                    np.concatenate([(y["hs"] > s), (y["as"] > s)]).astype(int), np.concatenate([gid, gid]), np.concatenate([coh, coh]))
        return o

    def ref_probs(pre):
        d = v2
        o = {"moneyline": d[f"{pre}_p_home_win"].values, "regulation_tie_overtime": d[f"{pre}_p_overtime"].values}
        for s in (4.5, 5.5, 6.5, 7.5):
            o[f"total_{s}"] = d[f"{pre}_p_over_{s}"].values
        o["puck_line_1.5"] = np.concatenate([d[f"{pre}_p_home_minus_1_5"].values, d[f"{pre}_p_away_minus_1_5"].values])
        for s in (2.5, 3.5):
            o[f"team_total_{s}"] = np.concatenate([d[f"{pre}_p_home_over_{s}"].values, d[f"{pre}_p_away_over_{s}"].values])
        return o
    ch = fam_probs(mk); refs = {REF_V1: ref_probs("V1"), REF_SIM2: ref_probs("SIM2")}
    arch_of = lambda fam: ARCH["ev"] if fam.startswith("regulation") else ARCH["tot"] if "total" in fam else ARCH["ml"]
    HEAD = ["moneyline", "regulation_tie_overtime", "total_5.5", "total_6.5", "puck_line_1.5", "team_total_2.5", "team_total_3.5"]
    results = []
    for ref, rp in refs.items():
        for fam in HEAD:
            p, yy, gg, cc = ch[fam]
            for metric in ("logloss", "brier"):
                results += compare(fam, arch_of(fam), metric, ref, p, rp[fam], yy, gg, cc)

    # ---------------------------------------------------------------- Kalshi T-60 mid (2025 cohort)
    log("kalshi reference quotes")
    g25 = reg_games[(reg_games["season"] == 2025) & reg_games["game_id"].isin(set(gid.tolist()))]
    q, cov, k_entries, k_checks = kalshi_reference(g25, log)
    tpos = pd.Series(np.arange(len(gid)), index=gid)
    market_context, settle_checks = [], []

    def vs_market(fam, arch, p_c, p_m, yy, gg, p_v1=None):
        cc = np.full(len(yy), "2025")
        rows = []
        for metric in ("logloss", "brier"):
            rows += compare(fam, arch, metric, REF_MKT, p_c, p_m, yy, gg, cc)
            if p_v1 is not None:
                fn = brier_rows if metric == "brier" else logloss_rows
                bs = paired_cluster_bootstrap(fn(p_v1, yy) - fn(p_m, yy), gg)
                market_context.append({"market_family": fam, "metric": metric, "cohort": "2025", "n_rows": bs["n_rows"], "n_clusters": bs["n_clusters"],
                                       "incumbent_V1": float(fn(p_v1, yy).mean()), "market": float(fn(p_m, yy).mean()),
                                       "challenger": float(fn(p_c, yy).mean()), "incumbent_minus_market": bs["mean"], "ci95": [bs["lo"], bs["hi"]]})
        return rows
    if len(q):
        q["pos"] = tpos.reindex(q["game_id"].values).values
        q = q[q["pos"].notna()].copy(); q["pos"] = q["pos"].astype(int)
        # settlement truth vs official outcomes
        ml = q[q["series"] == "KXNHLGAME"]
        own = np.where(ml["side"] == "home", y["home_win"][ml["pos"]], 1 - y["home_win"][ml["pos"]])
        tt = q[q["series"] == "KXNHLTOTAL"]; own_t = (y["total"][tt["pos"]] > tt["strike"].values).astype(int)
        sp = q[q["series"] == "KXNHLSPREAD"]
        own_s = (np.where(sp["side"] == "home", 1, -1) * y["margin"][sp["pos"]] > sp["strike"].values).astype(int)
        agree = [int((own == ml["y"].values).sum()), int((own_t == tt["y"].values).sum()), int((own_s == sp["y"].values).sum())]
        nn = [len(ml), len(tt), len(sp)]
        settle_checks.append(check("kalshi_settlement_matches_official_final_score", agree == nn,
                                   f"Kalshi `result` equals the outcome recomputed from the official final score (incl. the OT/SO winner goal): "
                                   f"moneyline {agree[0]}/{nn[0]}, total {agree[1]}/{nn[1]}, spread {agree[2]}/{nn[2]} quoted markets"))
        age = q["age_s"].values
        cov["quote_age_s_before_cutoff"] = {"median": float(np.median(age)), "p90": float(np.quantile(age, 0.9)), "max": float(age.max())}
        # moneyline: P(home) = mean of the home mid and 1 - away mid where both exist
        ml = ml.assign(p_home=np.where(ml["side"] == "home", ml["mid"], 1 - ml["mid"]))
        gm = ml.groupby("pos")["p_home"].mean(); ps = gm.index.values
        cov["games"] = {"cohort_games": int((coh == "2025").sum()), "moneyline_games_with_quote": int(len(gm)),
                        "total_5.5_games_with_quote": int(((tt["strike"] == 5.5)).sum()), "total_6.5_games_with_quote": int(((tt["strike"] == 6.5)).sum()),
                        "puck_line_1.5_markets_with_quote": int((sp["strike"] == 1.5).sum()),
                        "overtime_markets_in_cohort": cov.get("KXNHLOVERTIME", {}).get("markets_in_cohort", 0),
                        "team_total_markets_in_cohort": cov.get("KXNHLTEAMTOTAL", {}).get("markets_in_cohort", 0)}
        results += vs_market("moneyline", ARCH["ml"], mk["p_home_win"][ps], gm.values, y["home_win"][ps], gid[ps], v2["V1_p_home_win"].values[ps])
        for s in sorted(tt["strike"].unique()):
            d = tt[tt["strike"] == s]; ps = d["pos"].values
            if s in (5.5, 6.5) and len(d) > 50:
                results += vs_market(f"total_{s}", ARCH["tot"], p_over(mk["total_pmf"][ps], s), d["mid"].values, d["y"].values, gid[ps],
                                     v2[f"V1_p_over_{s}"].values[ps])
        ps = tt["pos"].values
        pc = np.array([mk["total_pmf"][p, int(math.floor(s)) + 1:].sum() for p, s in zip(ps, tt["strike"].values)])
        results += vs_market("total_all_listed_strikes", ARCH["tot"], pc, tt["mid"].values, tt["y"].values, gid[ps])
        cov["total_strikes_quoted"] = {str(k): int(v) for k, v in tt.groupby("strike").size().items()}
        for s, fam in ((1.5, "puck_line_1.5"), (2.5, "spread_2.5")):
            d = sp[sp["strike"] == s]; ps = d["pos"].values; hm = (d["side"] == "home").values
            ph, pa = p_margin_over(mk, s, "home"), p_margin_over(mk, s, "away")
            pv = np.where(hm, v2["V1_p_home_minus_1_5"].values[ps], v2["V1_p_away_minus_1_5"].values[ps]) if s == 1.5 else None
            if len(d) > 50:
                results += vs_market(fam, ARCH["ml"], np.where(hm, ph[ps], pa[ps]), d["mid"].values, d["y"].values, gid[ps], pv)
    results = finalize_verdicts(results)

    # ---------------------------------------------------------------- ablations
    log("ablations")
    ABL_FAMS = ["moneyline", "regulation_tie_overtime", "total_5.5", "total_6.5", "puck_line_1.5", "team_total_2.5"]

    def ablation_block(name, model, label, feature_helps_when):
        mv = model.markets(ti); fv = fam_probs(mv); out = []
        comps = [("regulation_score_nll", reg_nll_rows(model, ti, G) - reg_nll_rows(full, ti, G), reg_nll_rows(model, ti, G), reg_nll_rows(full, ti, G), gid, coh)]
        for fam in ABL_FAMS:
            p0, yy, gg, cc = ch[fam]; lv, lf = logloss_rows(fv[fam][0], yy), logloss_rows(p0, yy)
            comps.append((f"{fam}_logloss", lv - lf, lv, lf, gg, cc))
        for metric, dlt, lv, lf, gg, cc in comps:
            per = {}
            for co in ("2024", "2025", "pooled"):
                m = np.ones(len(dlt), bool) if co == "pooled" else cc == co
                bs = paired_cluster_bootstrap(dlt[m], gg[m]); per[co] = bs
                out.append({"metric": metric, "cohort": co, "n_rows": bs["n_rows"], "n_clusters": bs["n_clusters"], "variant": float(lv[m].mean()),
                            "headline_challenger": float(lf[m].mean()), "diff_variant_minus_headline": bs["mean"], "ci95": [bs["lo"], bs["hi"]],
                            "p_raw": bs["p_two_sided"]})
            for r in out[-3:]:
                r["same_sign_both_cohorts"] = bool(per["2024"]["mean"] * per["2025"]["mean"] > 0)
        prim = [r for r in out if r["metric"] == "regulation_score_nll" and r["cohort"] == "pooled"][0]
        sgn = 1 if feature_helps_when == "positive" else -1
        lo, hi = sorted([sgn * prim["ci95"][0], sgn * prim["ci95"][1]])
        if lo > 0 and prim["same_sign_both_cohorts"]:
            concl = "HELPS_SIGNIFICANT_REPLICATED"
        elif lo > 0:
            concl = "HELPS_SIGNIFICANT_NOT_REPLICATED"
        elif hi < 0:
            concl = "HURTS_SIGNIFICANT"
        else:
            concl = "NO_DETECTABLE_VALUE" if sgn * prim["diff_variant_minus_headline"] <= 0 or not prim["same_sign_both_cohorts"] else "FAVOURABLE_NOT_SIGNIFICANT"
        return {"ablation_id": name, "label": label, "primary_metric": "regulation_score_nll (mean negative log-likelihood of the observed regulation score, per game)",
                "sign_convention": f"diff = variant - headline challenger; the {'removed feature helps' if sgn == 1 else 'added information helps'} when diff is "
                                   f"{'positive' if sgn == 1 else 'negative'}", "conclusion": concl, "rows": out,
                "fitted": {"beta": dict(zip(["intercept"] + model.names, model.beta.tolist())), "joint": model.joint, "k_ot": model.k_ot}}
    ablations = [
        ablation_block("a_no_special_teams_split", variants["no_special_teams_split"],
                       "(a) no special-teams split: all-situations xG rates replace 5v5 + PP/PK terms", "positive"),
        ablation_block("b_no_tie_inflation_or_correlation", variants["no_tie_inflation_or_correlation"],
                       "(b) independent Poisson: no shared component, no tie / one-goal margin weights", "positive"),
        ablation_block("c_no_finishing", variants["no_finishing"], "(c) no finishing term (goals vs xG, for and against)", "positive"),
        ablation_block("e_no_rest", variants["no_rest"], "(e) no back-to-back flags", "positive"),
    ]

    # (d) ORACLE: as-played starting goalie quality (NOT point-in-time knowable; upper bound only; never in the headline)
    gl, glfiles = load_goalies()
    gl = gl[(gl["game_type"] == 2)].copy()
    gl["day"] = (pd.to_datetime(gl["game_date"]).values.astype("datetime64[D]") - np.datetime64("2000-01-01")).astype(int)
    gl = gl.sort_values(["day", "game_id", "player_id"], kind="stable").reset_index(drop=True)
    gdup = int(gl.duplicated(["game_id", "player_id"]).sum())
    starters = gl[gl["starter"].astype(bool)]
    st_per = starters.groupby(["game_id", "team_id"]).size()
    cs = gl.groupby("player_id")[["saves", "shots_against"]].cumsum() - gl[["saves", "shots_against"]]  # strictly earlier games of that goalie
    dsum = gl.groupby("day")[["saves", "shots_against"]].sum().cumsum()
    prior_day = dsum.shift(1).reindex(gl["day"].values)
    lsv = (prior_day["saves"].values / prior_day["shots_against"].values); lsv = np.where(np.isnan(lsv), 0.905, lsv)
    gl["cs_saves"], gl["cs_shots"], gl["lsv"] = cs["saves"].values, cs["shots_against"].values, lsv
    st = gl[gl["starter"].astype(bool)].drop_duplicates(["game_id", "is_home"])
    sh = st[st["is_home"].astype(bool)].set_index("game_id").reindex(G["game_id"])
    sa = st[~st["is_home"].astype(bool)].set_index("game_id").reindex(G["game_id"])
    has_g = (sh["cs_shots"].notna() & sa["cs_shots"].notna()).values
    g_train = has_g & (season_g >= 2021) & (season_g <= TRAIN_LAST)

    def gq(side, P):
        sv = (side["cs_saves"].values + P * side["lsv"].values) / (side["cs_shots"].values + P)
        out = np.log((1 - sv) / (1 - side["lsv"].values))
        return np.where(np.isnan(out), 0.0, out)
    best = None
    yrow = tg["rg"].values; base = np.log(predict_lam(F, FEATS["full"], full.beta))
    for P in (300.0, 600.0, 1000.0, 2000.0, 4000.0):
        ex = np.zeros(len(tg)); ex[0::2] = gq(sh, P); ex[1::2] = gq(sa, P)  # the away team shoots on the HOME starter and vice versa
        rm = np.repeat(g_train, 2)
        b = poisson_glm(np.column_stack([np.ones(rm.sum()), ex[rm]]), yrow[rm], base[rm])
        dev = float(np.mean(poisson_deviance_rows(yrow[rm], np.exp(base[rm] + b[0] + b[1] * ex[rm]))))
        if best is None or dev < best[0]:
            best = (dev, P, b, ex)
    _, Pg, bg, exg = best
    oracle = Model(tg, F, FEATS["full"], full.beta, full.joint, full.k_ot, extra_log=bg[0] + bg[1] * exg)
    ob = ablation_block("d_oracle_as_played_starting_goalie", oracle,
                        "(d) ORACLE_NOT_PIT upper bound: + as-played starting-goalie quality (walk-forward shrunk save% of the goalie who actually "
                        "started; the starter identity is NOT knowable pregame from this file)", "negative")
    ob["oracle_not_pit"] = True
    ob["fitted"] = {"prior_shots": Pg, "gamma_intercept": float(bg[0]), "gamma_goalie_log_goal_rate": float(bg[1]), "fit_seasons": "2021-2023",
                    "train_games": int(g_train.sum()), "test_games_with_both_starters": int(has_g[ti].sum())}
    ablations.insert(3, ob)
    goalie_checks = [
        check("goalies_no_duplicate_game_player", gdup == 0, f"{len(gl)} regular-season goalie-game rows, {gdup} duplicates"),
        check("goalies_exactly_one_starter_per_team_game", bool((st_per == 1).all()), f"{int((st_per == 1).sum())}/{len(st_per)} team-games have exactly one starter flag"),
        check("goalies_starter_coverage_of_test_games", bool(has_g[ti].mean() > 0.99), f"{int(has_g[ti].sum())}/{len(ti)} test games have both starters"),
        check("goalie_rating_uses_prior_games_only", True, "save/shot sums are cumulative over the goalie's strictly earlier game rows; the league save% uses strictly earlier dates"),
        check("starter_flag_is_point_in_time", False, "FAILED BY DESIGN: `starter` is the as-played flag recorded after the game; a pregame projection could not know it. "
              "Ablation (d) is therefore labelled ORACLE_NOT_PIT and excluded from the headline challenger"),
    ]

    # ---------------------------------------------------------------- calibration and distribution diagnostics
    def cal_block(p, yy, cc):
        o = {}
        for co in ("2024", "2025", "pooled"):
            m = np.ones(len(yy), bool) if co == "pooled" else cc == co
            a, b = calibration_slope(p[m], yy[m])
            o[co] = {"intercept": a, "slope": b, "mean_p": float(np.mean(p[m])), "observed": float(np.mean(yy[m])), "n": int(m.sum())}
        return o
    calibration = {}
    for fam in ["moneyline", "regulation_tie_overtime", "total_4.5", "total_5.5", "total_6.5", "total_7.5", "puck_line_1.5", "team_total_2.5", "team_total_3.5"]:
        p, yy, gg, cc = ch[fam]
        calibration[fam] = {"challenger": cal_block(p, yy, cc), "incumbent_V1": cal_block(refs[REF_V1][fam], yy, cc), "shadow_SIM2": cal_block(refs[REF_SIM2][fam], yy, cc)}
    train_tot = G["total"][train_g]; clim = np.bincount(train_tot, minlength=mk["total_pmf"].shape[1])[:mk["total_pmf"].shape[1]].astype(float); clim /= clim.sum()
    crps_c = np.array([crps_pmf(mk["total_pmf"][i], y["total"][i]) for i in range(len(ti))])
    crps_k = np.array([crps_pmf(clim, t) for t in y["total"]])
    ladder = lambda rp: sum(brier_rows(rp[f"total_{s}"], (y["total"] > s).astype(int)) for s in (4.5, 5.5, 6.5, 7.5))
    lad_c = sum(brier_rows(ch[f"total_{s}"][0], ch[f"total_{s}"][1]) for s in (4.5, 5.5, 6.5, 7.5))
    totals, margin, tie = {}, {}, {}
    for co in ("2024", "2025", "pooled"):
        m = np.ones(len(ti), bool) if co == "pooled" else coh == co
        bs = paired_cluster_bootstrap((crps_c - crps_k)[m], gid[m])
        t = {"n": int(m.sum()), "crps_challenger": float(crps_c[m].mean()), "crps_train_climatology": float(crps_k[m].mean()),
             "crps_diff_vs_climatology": bs["mean"], "crps_diff_ci95": [bs["lo"], bs["hi"]], "observed_mean_total": float(y["total"][m].mean())}
        for nm, et in (("challenger", mk["exp_total"]), ("incumbent_V1", v2["V1_expected_total"].values), ("shadow_SIM2", v2["SIM2_expected_total"].values)):
            e = et[m] - y["total"][m]
            t[f"expected_total_{nm}"] = {"mean_pred": float(et[m].mean()), "bias": float(e.mean()), "mae": float(np.abs(e).mean()), "rmse": float(np.sqrt((e ** 2).mean()))}
        for nm, lv in (("challenger", lad_c), ("incumbent_V1", ladder(refs[REF_V1])), ("shadow_SIM2", ladder(refs[REF_SIM2]))):
            t[f"partial_crps_ladder_4.5_to_7.5_{nm}"] = float(lv[m].mean())
        for nm, lv in (("incumbent_V1", ladder(refs[REF_V1])), ("shadow_SIM2", ladder(refs[REF_SIM2]))):
            b2 = paired_cluster_bootstrap((lad_c - lv)[m], gid[m])
            t[f"partial_crps_diff_vs_{nm}"] = {"diff": b2["mean"], "ci95": [b2["lo"], b2["hi"]], "p_raw": b2["p_two_sided"]}
        totals[co] = t
        em = mk["exp_margin"][m]; om = y["margin"][m].astype(float)
        A = np.column_stack([np.ones(m.sum()), em]); coef = np.linalg.lstsq(A, om, rcond=None)[0]
        v1m = (v1["expected_margin"].values)[m]; coef1 = np.linalg.lstsq(np.column_stack([np.ones(m.sum()), v1m]), om, rcond=None)[0]
        off_ = mk["margin_offset"]; dd = np.arange(-off_, off_ + 1)
        buckets = {}
        for nm, sel, osel in (("home_by_3plus", dd >= 3, om >= 3), ("home_by_2", dd == 2, om == 2), ("home_by_1", dd == 1, om == 1),
                              ("away_by_1", dd == -1, om == -1), ("away_by_2", dd == -2, om == -2), ("away_by_3plus", dd <= -3, om <= -3)):
            buckets[nm] = {"predicted": float(mk["margin_pmf"][m][:, sel].sum(1).mean()), "observed": float(osel.mean())}
        margin[co] = {"n": int(m.sum()), "mean_expected_margin": float(em.mean()), "observed_mean_margin": float(om.mean()),
                      "ols_observed_on_expected": {"intercept": float(coef[0]), "slope": float(coef[1])},
                      "incumbent_V1_ols_observed_on_expected": {"intercept": float(coef1[0]), "slope": float(coef1[1])},
                      "rmse_expected_margin": float(np.sqrt(((em - om) ** 2).mean())), "incumbent_V1_rmse_expected_margin": float(np.sqrt(((v1m - om) ** 2).mean())),
                      "final_margin_buckets": buckets}
        tie[co] = {"n": int(m.sum()), "observed_tie_rate": float(y["ot"][m].mean()), "challenger_mean_p_tie": float(mk["p_reg_tie"][m].mean()),
                   "incumbent_V1_mean_p_tie": float(v2["V1_p_overtime"].values[m].mean()), "shadow_SIM2_mean_p_tie": float(v2["SIM2_p_overtime"].values[m].mean()),
                   "independent_poisson_mean_p_tie": float(variants["no_tie_inflation_or_correlation"].markets(ti)["p_reg_tie"][m].mean()),
                   "observed_home_win_given_tie": float(y["home_win"][m][y["ot"][m] == 1].mean()),
                   "challenger_mean_p_home_given_tie": float(ot_home_prob(full.lam_h[ti], full.lam_a[ti], full.k_ot)[m][y["ot"][m] == 1].mean())}
    train_tie_rate = float(G["extra"][train_g].mean())

    # coherence of the single joint distribution (asserted, and recorded)
    coh_err = max(float(np.abs(mk["final"].sum((1, 2)) - 1).max()), float(np.abs(mk["total_pmf"].sum(1) - 1).max()),
                  float(np.abs(p_margin_over(mk, 1.5, "home") + p_margin_over(mk, -1.5, "away") - 1).max()),
                  float(np.abs(mk["exp_total"] - (mk["exp_reg_total"] + mk["p_reg_tie"])).max()))
    assert coh_err < 1e-9
    lam_tot = full.lam_h[ti] + full.lam_a[ti]
    model_checks = [
        check("joint_distribution_coherence", coh_err < 1e-9, f"max abs error {coh_err:.1e} over: final pmf sums to 1, total pmf sums to 1, "
              "P(home -1.5) + P(away +1.5) = 1, E[final total] = E[regulation total] + P(tie)"),
        check("lambda_plausibility", bool(lam_tot.min() > 3.5 and lam_tot.max() < 9), f"test regulation lambda sum min/mean/max {lam_tot.min():.2f}/{lam_tot.mean():.2f}/{lam_tot.max():.2f}"),
        check("truncation_mass", True, f"regulation support 0..{K - 1} per team; observed max regulation goals in all seasons {int(max(G['rh'].max(), G['ra'].max()))}"),
    ]

    # ---------------------------------------------------------------- documents
    games_first, games_last = str(games["game_date"].min()), str(games["game_date"].max())
    data = [
        {"dataset_id": "nhl_games", "repo": REPO, "path": "data/history/nhl/games_{2008..2025}.parquet", "rows": int(len(games)), "first": games_first,
         "last": games_last, "sha256": None, "files": len(gfiles), "files_digest_sha256": files_digest(gfiles), "kind": "HISTORICAL_BACKFILL",
         "rights_tier": "UNRESOLVED_INTERNAL_ONLY", "rows_used": int(len(reg_games)), "note": "final regular-season games only; season = start year"},
        {"dataset_id": "moneypuck_team_games", "repo": REPO, "path": "data/history/moneypuck/team_games_{2008..2025}.parquet", "rows": int(len(mp)),
         "first": str(mp["game_date"].min()), "last": str(mp["game_date"].max()), "sha256": None, "files": len(mfiles), "files_digest_sha256": files_digest(mfiles),
         "kind": "HISTORICAL_BACKFILL", "rights_tier": "CLEARED_NONCOMMERCIAL_RESEARCH (owner-reported; MoneyPuck listed downloads, attribution required)",
         "rows_used": int((mp["game_type"] == 2).sum())},
        {"dataset_id": "nhl_goalie_games", "repo": REPO, "path": "data/history/players/goalies_{2021..2026}.parquet", "rows": int(len(gl)),
         "first": str(gl["game_date"].min()), "last": str(gl["game_date"].max()), "sha256": None, "files": len(glfiles), "files_digest_sha256": files_digest(glfiles),
         "kind": "HISTORICAL_BACKFILL", "rights_tier": "UNRESOLVED_INTERNAL_ONLY", "note": "regular-season rows; used ONLY by the ORACLE_NOT_PIT ablation (d)"},
        {"dataset_id": "incumbent_walk_forward_v1", "repo": REPO, "path": "docs/research/walk_forward_36570274279_games.csv", "rows": int(len(v1)),
         "first": str(v1["game_date"].min()), "last": str(v1["game_date"].max()), "sha256": sha256_file(docs / "walk_forward_36570274279_games.csv"),
         "kind": "WALK_FORWARD_REPRODUCTION", "rights_tier": "UNRESOLVED_INTERNAL_ONLY"},
        {"dataset_id": "incumbent_walk_forward_v2_sim2", "repo": REPO, "path": "docs/research/walk_forward_v2_wf2_20260929_games.csv", "rows": int(len(v2)),
         "first": str(v2["game_date"].min()), "last": str(v2["game_date"].max()), "sha256": sha256_file(docs / "walk_forward_v2_wf2_20260929_games.csv"),
         "kind": "WALK_FORWARD_REPRODUCTION", "rights_tier": "UNRESOLVED_INTERNAL_ONLY"},
    ] + k_entries
    beta = dict(zip(["intercept"] + FEATS["full"], full.beta.tolist()))
    test_rows = np.repeat(False, len(tg)); test_rows[np.concatenate([2 * ti, 2 * ti + 1])] = True
    fstats = {n: {"mean": round(float(F["f"][n][test_rows].mean()), 4), "sd": round(float(F["f"][n][test_rows].std()), 4),
                  "min": round(float(F["f"][n][test_rows].min()), 4), "max": round(float(F["f"][n][test_rows].max()), 4)} for n in FEATS["full"] + ["offall", "defall"]}
    rng_ok = lambda n, lim: bool(abs(fstats[n]["min"]) < lim and abs(fstats[n]["max"]) < lim)
    pit = "state read before the game's own update; only the team's games with an earlier game_date; league reference = trailing 365 days of strictly earlier dates"
    features = [
        {"feature_id": "team_xg_5v5_off_def", "catalog_inputs": ["NHL:nhl.xg_for", "NHL:nhl.xg_against"],
         "description": f"log ratio to league of exponentially weighted (half-life {hp['hl']:g} games), shrunk ({hp['k_prior']:g} pseudo-games of league average), "
                        f"season-carried ({hp['carry']:g}) 5v5 xG for/against per 60 ({hp['xg']} MoneyPuck xG column); offset = trailing league regulation goals per team-game",
         "pit_rule": pit, "summary_test": {k: fstats[k] for k in ("off5", "def5")},
         "checks": data_checks + leak_checks + [check("feature_range", rng_ok("off5", 0.5) and rng_ok("def5", 0.5), f"log-ratio range on test rows {fstats['off5']} / {fstats['def5']}")]},
        {"feature_id": "special_teams_pp_pk", "catalog_inputs": ["NHL:nhl.special_teams", "NHL:nhl.penalty_rates"],
         "description": "log ratio to league of power-play xG for per game (5on4 xG rate x power-play time, i.e. penalty-time weighted) for the team and "
                        "penalty-kill xG against per game (4on5) for the opponent; same weighting/shrinkage as 5v5",
         "pit_rule": pit, "summary_test": {k: fstats[k] for k in ("pp", "pk")},
         "checks": [check("feature_range", rng_ok("pp", 1.0) and rng_ok("pk", 1.0), f"log-ratio range on test rows {fstats['pp']} / {fstats['pk']}"),
                    check("pp_rate_plausible", bool(4 < np.nanmean(F["pp_rate60"][test_rows]) < 10), f"mean shrunk 5on4 xG per 60 on test rows {float(np.nanmean(F['pp_rate60'][test_rows])):.2f}"),
                    data_checks[4], leak_checks[0]]},
        {"feature_id": "finishing_goals_vs_xg", "catalog_inputs": ["NHL:nhl.finishing"],
         "description": f"regressed all-situations goals / xG for (team finishing) and against (team goaltending+defence finishing): half-life {hp['hl_fin']:g} games, "
                        f"{hp['m_fin']:g} pseudo-xG at the league ratio. MoneyPuck all-situations goals include empty-net goals and exclude the shootout winner goal",
         "pit_rule": pit, "summary_test": {k: fstats[k] for k in ("fin_o", "fin_d")},
         "checks": [check("feature_range", rng_ok("fin_o", 0.4) and rng_ok("fin_d", 0.4), f"log-ratio range on test rows {fstats['fin_o']} / {fstats['fin_d']}"), data_checks[5], leak_checks[0]]},
        {"feature_id": "home_ice_and_back_to_back", "catalog_inputs": ["NHL:nhl.venue", "NHL:nhl.rest_travel"],
         "description": "fitted home-ice coefficient (not hard-coded) and fitted back-to-back flags for the team and the opponent (team played on the previous calendar day)",
         "pit_rule": "schedule facts known before the game (previous game date of the team)",
         "checks": [check("b2b_rate_plausible", bool(0.1 < tg["b2b"].values[test_rows].mean() < 0.25), f"back-to-back share of test team-games {tg['b2b'].values[test_rows].mean():.4f}"),
                    check("b2b_matches_incumbent_flag", bool((v1["home_b2b"].values == (tg["b2b"].values[2 * ti + 1] == 1)).mean() > 0.99),
                          f"home back-to-back flag equals the incumbent CSV's home_b2b in {(v1['home_b2b'].values == (tg['b2b'].values[2 * ti + 1] == 1)).mean():.4%} of test games"),
                    data_checks[8]]},
        {"feature_id": "joint_regulation_score_and_ot", "catalog_inputs": ["NHL:nhl.stat_dist", "NHL:nhl.ot_so", "NHL:nhl.empty_net"],
         "description": "bivariate Poisson regulation score with shared component, tie inflation and one-goal-margin weight; OT/SO resolution 0.5 + k*log(lam_h/lam_a); "
                        "all markets are sums over this one pmf. Empty-net goals are NOT modelled explicitly: they are inside the regulation-goal target, and the "
                        "pulled-goalie endgame (one-goal games becoming ties or two-goal games) is absorbed by the tie and one-goal margin weights",
         "pit_rule": "parameters frozen from seasons <= 2023; per-game inputs are the PIT lambdas",
         "checks": model_checks + [data_checks[2], leak_checks[2]]},
        {"feature_id": "oracle_as_played_starting_goalie", "catalog_inputs": ["NHL:nhl.goalie_start", "NHL:nhl.goalie_quality"],
         "description": "ORACLE_NOT_PIT upper bound (ablation d only): walk-forward shrunk save% of the goalie who actually started, as a multiplier on the opponent's goal rate",
         "pit_rule": "goalie rating is PIT (earlier games only) but the STARTER IDENTITY is as-played, hence oracle; never used in the headline challenger",
         "checks": goalie_checks},
        {"feature_id": "kalshi_pregame_mid_T-60", "catalog_inputs": ["NHL:m.quote_history", "NHL:m.settlement_truth"],
         "description": "market reference: mid of yes bid/ask of the last candle ending at or before scheduled start - 60 min, two-sided only (reference, not a model input)",
         "pit_rule": "candle end_period_ts <= start_ts - 3600 s; never a later candle", "coverage": cov, "checks": k_checks + settle_checks + inc_checks},
    ]
    head = [r for r in results if r["headline"]]
    hl = [r for r in head if r["metric"] == "logloss"]
    n_val = sum(r["verdict"] == "VALIDATED_IMPROVEMENT" for r in head); n_bad = sum(r["verdict"] == "NOT_IMPROVED" for r in head)
    n_inv = sum(r["verdict"] == "IMPROVED_NOT_VALIDATED" for r in head)
    val_fams = sorted({r["market_family"] for r in head if r["verdict"] == "VALIDATED_IMPROVEMENT"})
    bad_fams = sorted({r["market_family"] for r in head if r["verdict"] == "NOT_IMPROVED"})
    mrows = [r for r in results if r["reference"] == REF_MKT]
    m_worse = sorted({r["market_family"] for r in mrows if r["verdict"] == "NOT_IMPROVED"}); m_better = sorted({r["market_family"] for r in mrows if r["diff"] < 0 and r["ci95"][1] < 0})
    if n_val and not n_bad and all(r["verdict"] == "VALIDATED_IMPROVEMENT" for r in hl):
        overall = "VALIDATED_IMPROVEMENT"
    elif n_bad and not (n_val or n_inv):
        overall = "NOT_IMPROVED"
    elif (n_val or n_inv) and not n_bad:
        overall = "IMPROVED_NOT_VALIDATED"
    else:
        overall = "INCONCLUSIVE"
    reason = (f"Headline = pooled 2024+2025 vs {REF_V1}, {len(head)} rows (7 families x logloss/brier), Holm-adjusted. VALIDATED_IMPROVEMENT rows: {n_val} "
              f"(families {val_fams}); IMPROVED_NOT_VALIDATED: {n_inv}; NOT_IMPROVED: {n_bad} (families {bad_fams}); INCONCLUSIVE: {len(head) - n_val - n_bad - n_inv}. "
              f"Overall rule: VALIDATED_IMPROVEMENT only if every headline log-loss row is validated and none is NOT_IMPROVED; mixed or partial evidence is reported as "
              f"IMPROVED_NOT_VALIDATED (some validated/improved, none worse) or INCONCLUSIVE. Against the Kalshi T-60 mid (2025 cohort only, single cohort so never "
              f"'replicated'): challenger point estimate is worse than the market in {sum(r['diff'] > 0 for r in mrows)} of {len(mrows)} market rows; Holm-significantly "
              f"worse in families {m_worse}; CI entirely better than the market in {m_better}. The challenger does NOT beat the market.")
    abl = {a["ablation_id"]: a for a in ablations}

    def claim(inp, abl_id, what):
        a = abl[abl_id]; p = [r for r in a["rows"] if r["metric"] == "regulation_score_nll" and r["cohort"] == "pooled"][0]
        outcome = {"HELPS_SIGNIFICANT_REPLICATED": "OK", "HELPS_SIGNIFICANT_NOT_REPLICATED": "PARTIAL", "FAVOURABLE_NOT_SIGNIFICANT": "PARTIAL",
                   "NO_DETECTABLE_VALUE": "REJECTED", "HURTS_SIGNIFICANT": "REJECTED"}[a["conclusion"]]
        return {"input": inp, "stage": "EVALUATED", "outcome": outcome,
                "evidence": f"{what}; ablation {abl_id}: {a['conclusion']}, pooled regulation-score NLL diff (variant - headline) {p['diff_variant_minus_headline']:+.5f} "
                            f"CI [{p['ci95'][0]:+.5f}, {p['ci95'][1]:+.5f}]"}
    ml_head = [r for r in head if r["market_family"] == "moneyline" and r["metric"] == "logloss"][0]
    core_ev = (f"core rating inputs of the challenger (no ablation removes them); challenger vs incumbent pooled moneyline logloss diff {ml_head['diff']:+.5f} "
               f"CI [{ml_head['ci95'][0]:+.5f}, {ml_head['ci95'][1]:+.5f}] verdict {ml_head['verdict']}")
    core_outcome = "OK" if ml_head["verdict"] == "VALIDATED_IMPROVEMENT" else "PARTIAL"
    oc = claim("NHL:nhl.goalie_start", "d_oracle_as_played_starting_goalie", "ORACLE_NOT_PIT upper bound only: as-played starter, no pregame-knowable source collected")
    oc["stage"], oc["outcome"] = "FEATURE_BUILT", "BLOCKED"
    oq = claim("NHL:nhl.goalie_quality", "d_oracle_as_played_starting_goalie", "crude save%-only goalie quality (no GSAx / shot-quality adjustment), evaluated only through the ORACLE_NOT_PIT ablation on top of the team-level goals-against finishing term")
    oq["outcome"] = "PARTIAL" if oq["outcome"] != "REJECTED" else "REJECTED"
    claims = [
        {"input": "NHL:nhl.xg_for", "stage": "EVALUATED", "outcome": core_outcome, "evidence": core_ev},
        {"input": "NHL:nhl.xg_against", "stage": "EVALUATED", "outcome": core_outcome, "evidence": core_ev},
        claim("NHL:nhl.special_teams", "a_no_special_teams_split", "PP xG for / PK xG against per game split from 5v5"),
        claim("NHL:nhl.penalty_rates", "a_no_special_teams_split", "penalty time enters only as the weight inside per-game PP/PK xG (not a separate term)"),
        claim("NHL:nhl.finishing", "c_no_finishing", "regressed goals vs xG, for and against"),
        claim("NHL:nhl.rest_travel", "e_no_rest", "back-to-back flags only (no travel distance / time zones)"),
        {"input": "NHL:nhl.venue", "stage": "EVALUATED", "outcome": "PARTIAL",
         "evidence": f"single fitted league-wide home-ice coefficient {beta['home']:+.4f} (log goals); no rink-specific effects; not ablated separately"},
        claim("NHL:nhl.stat_dist", "b_no_tie_inflation_or_correlation", "bivariate Poisson + tie / one-goal margin weights vs independent Poisson"),
        claim("NHL:nhl.ot_so", "b_no_tie_inflation_or_correlation", f"regulation tie probability and OT/SO resolution (k={full.k_ot:.3f})"),
        {"input": "NHL:nhl.empty_net", "stage": "FEATURE_BUILT", "outcome": "PARTIAL",
         "evidence": "empty-net goals handled only implicitly (inside regulation-goal targets and the one-goal margin weight); no explicit pulled-goalie model, not separately ablated"},
        oc, oq,
        {"input": "NHL:m.quote_history", "stage": "EVALUATED", "outcome": "OK",
         "evidence": f"T-60 two-sided mids used as market reference on the 2025 cohort; usable markets GAME {cov.get('KXNHLGAME', {}).get('usable_two_sided')}, "
                     f"TOTAL {cov.get('KXNHLTOTAL', {}).get('usable_two_sided')}, SPREAD {cov.get('KXNHLSPREAD', {}).get('usable_two_sided')}"},
        {"input": "NHL:m.settlement_truth", "stage": "VERIFIED", "outcome": "OK" if all(c["passed"] for c in settle_checks) and settle_checks else "PARTIAL",
         "evidence": settle_checks[0]["detail"] if settle_checks else "no quoted markets"},
    ]
    design_doc = {
        "challenger": "walk-forward shrunk xG ratings -> Poisson GLM of regulation goals -> bivariate Poisson with tie/one-goal margin weights -> OT/SO resolution -> all markets from one final-score pmf",
        "season_label": "start year (2024 = 2024-25)", "population": "final regular-season games (game_type 2)",
        "train_window": {"rating_burn_in": "2008", "glm_joint_ot_fit": f"{FIT_FIRST}-{TRAIN_LAST}", "hyper_parameter_selection": f"GLM fit {FIT_FIRST}-{VAL_FIRST - 1}, validation deviance {VAL_FIRST}-{TRAIN_LAST}",
                         "train_games": int(train_g.sum())},
        "test_window": {"cohorts": {"2024": int((coh == "2024").sum()), "2025": int((coh == "2025").sum())}, "games": int(len(ti)),
                        "first": str(v1["game_date"].min()), "last": str(v1["game_date"].max()), "note": "exactly the incumbent walk-forward games; parameters frozen, ratings keep updating walk-forward"},
        "fitted_parameters": {"hyper": hp, "hyper_validation_deviance": val_dev, "hyper_configs_evaluated": n_eval, "hyper_trace": trace, "glm_beta": beta,
                              "joint": full.joint, "ot_k": full.k_ot, "train_regulation_tie_rate": train_tie_rate, "regulation_support": f"0..{K - 1}"},
        "regulation_scores": "regulation goals = final score minus 1 for the winner when last_period_type is OT or SO (verified: every OT/SO final has margin exactly 1, no REG final is tied)",
        "empty_net_handling": "implicit: empty-net goals are counted in the regulation-goal targets and in MoneyPuck all-situations goals (finishing term); the joint pmf's "
                              "tie weight and one-goal-margin weight absorb the pulled-goalie redistribution of one-goal games. No explicit empty-net rate is used.",
        "leak_guards": [c["detail"] for c in leak_checks] + ["hyper-parameters, GLM, joint and OT parameters never see a season > 2023",
                                                             "Kalshi reference uses only candles ending <= scheduled start - 60 min",
                                                             "ablation (d) uses the as-played starter and is labelled ORACLE_NOT_PIT; excluded from the headline"],
        "preregistered_metric": "paired per-row log loss and Brier score, diff = challenger - reference (negative = challenger better), game-cluster bootstrap "
                                "(contract.paired_cluster_bootstrap, n_boot=2000, seed=7)",
        "multiplicity": "Holm within each (reference, cohort) hypothesis group across families x metrics; the HEADLINE group is reference=incumbent:DATA_ONLY_V1, cohort=pooled "
                        f"({len(head)} rows). Secondary groups (per-cohort, shadow:SIM2, market) are Holm-adjusted within their own group and flagged headline=false",
        "replicated": "true only when the challenger's mean loss is lower than the reference's in BOTH the 2024 and the 2025 cohort; market rows exist for 2025 only and are never replicated",
        "promotion_rule": VERDICT_RULE,
        "overall_rule": "VALIDATED_IMPROVEMENT only if every headline log-loss row is VALIDATED_IMPROVEMENT and no headline row is NOT_IMPROVED; NOT_IMPROVED if some headline row is "
                        "NOT_IMPROVED and none is improved; IMPROVED_NOT_VALIDATED if some headline row is improved/validated and none is NOT_IMPROVED; else INCONCLUSIVE",
    }
    limitations = [
        "Fitted on NHL-API-derived outcomes (official scores, goalie game logs) whose source robots file says ai-train=no: flagged for the owner; rights tier UNRESOLVED_INTERNAL_ONLY, research only.",
        "The Kalshi reference is the T-60 mid of the last two-sided candle; a mid is not an executable fill (no spread, fee or depth is charged), so being close to or better than it is not evidence of tradable edge.",
        "Kalshi quotes cover the 2025 cohort only (one season, one cohort), so no market comparison can be 'replicated' under the pre-registered rule; totals and spreads are listed only from 2025-10-22 onward.",
        "No KXNHLOVERTIME or KXNHLTEAMTOTAL market exists for the regular-season test games (overtime markets are playoff-only in the file; the team-total file is empty), so those families have no market reference.",
        "MoneyPuck xG values come from MoneyPuck's own shot model, which is trained on history that may include later seasons; the per-game xG numbers are used as published (a mild look-ahead in the feature definition that the incumbent shares).",
        "The incumbent probabilities are Monte-Carlo estimates (4,000 simulations per game), so part of any gap in the challenger's favour is incumbent simulation noise (about 0.008 s.d. per probability), not model skill.",
        "Empty-net goals, score effects and pulled-goalie timing are handled only implicitly through the tie and one-goal-margin weights; there is no explicit endgame model.",
        "No lineup, injury, travel or pregame-knowable starting-goalie information is used; ablation (d) is an ORACLE_NOT_PIT upper bound using the as-played starter and must not be read as an achievable gain.",
        "Regular season only; playoff games (different overtime rules) are neither fitted nor evaluated. Hyper-parameters were chosen on one validation split (2019-2023), which includes the two COVID-shortened seasons.",
        "Two test cohorts (1,312 games each) give limited power: differences of a few 1e-4 in log loss cannot be resolved, so INCONCLUSIVE rows are not evidence of equality.",
        "Ablation variants are refitted with the headline hyper-parameters (not re-tuned), so ablation deltas are conditional on that choice.",
    ]
    doc = {"schema": EVAL_SCHEMA, "status": "RESEARCH_ONLY", "sport": "NHL", "challenger_id": CHALLENGER_ID, "incumbent_id": INCUMBENT_ID,
           "source_commits": {"NHL-edge-finder": SOURCE_COMMIT}, "data": data, "features": features, "design": design_doc, "results": results,
           "ablations": ablations, "calibration": calibration, "totals_distribution": totals, "margin_calibration": margin, "tie_rate": tie,
           "market_reference": {"definition": "mid of yes bid/ask of the LAST candle with end_period_ts <= scheduled start - 60 min, only if two-sided (0 < bid <= ask < 1)",
                                "coverage": cov, "incumbent_vs_market_context": market_context},
           "input_stage_claims": claims, "verdict": {"overall": overall, "reason": reason, "retain_incumbent": bool(overall != "VALIDATED_IMPROVEMENT" or bool(m_worse))},
           "limitations": limitations}
    errs = validate_evaluation(doc)
    assert not errs, errs

    # predictions summary: aggregates only
    summ = {"schema": "sift-foundation-predictions-summary/1", "status": "RESEARCH_ONLY", "challenger_id": CHALLENGER_ID, "note": "aggregates only; no per-game rows", "cohorts": {}}
    for co in ("2024", "2025", "pooled"):
        blk = {"n_games": int((coh == co).sum()) if co != "pooled" else int(len(ti)), "mean_lambda_home": float(full.lam_h[ti][(coh == co) | (co == "pooled")].mean()),
               "mean_lambda_away": float(full.lam_a[ti][(coh == co) | (co == "pooled")].mean()), "families": {}}
        for fam, (p, yy, gg, cc) in ch.items():
            m = np.ones(len(yy), bool) if co == "pooled" else cc == co
            blk["families"][fam] = {"n_rows": int(m.sum()), "mean_p_challenger": float(p[m].mean()), "mean_p_incumbent_V1": float(refs[REF_V1][fam][m].mean()),
                                    "observed_rate": float(yy[m].mean()), "sd_p_challenger": float(p[m].std()), "reliability_challenger": reliability(p[m], yy[m]),
                                    "reliability_incumbent_V1": reliability(refs[REF_V1][fam][m], yy[m])}
        m = np.ones(len(ti), bool) if co == "pooled" else coh == co
        blk["mean_total_pmf_challenger"] = mk["total_pmf"][m].mean(0)[:16].tolist()
        blk["observed_total_freq"] = (np.bincount(y["total"][m], minlength=16)[:16] / m.sum()).tolist()
        summ["cohorts"][co] = blk
    return doc, summ


def main(argv=None):
    import time
    t0 = time.time()
    doc, summ = run()
    write_json(OUT / "evaluation.json", doc); write_json(OUT / "predictions_summary.json", summ)
    print(f"wrote {OUT / 'evaluation.json'} and predictions_summary.json in {time.time() - t0:.0f}s")
    print("overall:", doc["verdict"]["overall"])
    for r in doc["results"]:
        if r["cohort"] in ("pooled",) or r["reference"] == REF_MKT:
            print(f"  {r['reference']:28s} {r['market_family']:26s} {r['metric']:8s} {r['cohort']:6s} n={r['n_rows']:5d} ch={r['challenger']:.5f} ref={r['reference_value']:.5f} "
                  f"diff={r['diff']:+.5f} [{r['ci95'][0]:+.5f},{r['ci95'][1]:+.5f}] p_holm={r['p_holm']:.3f} rep={r['replicated']} {r['verdict']}")
    for a in doc["ablations"]:
        p = [r for r in a["rows"] if r["cohort"] == "pooled"]
        print(" ", a["ablation_id"], a["conclusion"], " ".join(f"{r['metric']}={r['diff_variant_minus_headline']:+.5f}" for r in p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
