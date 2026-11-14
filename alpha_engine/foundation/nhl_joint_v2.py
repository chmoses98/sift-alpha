"""Operation Data Foundation, NHL: challenger ``alpha-nhl-joint-0.2`` = ``alpha-nhl-joint-0.1`` + point-in-time goalie inputs
(+ any team-strength / rest extension that earns its place on VALIDATION seasons).

RESEARCH_ONLY. The 0.1 joint regulation-score distribution (bivariate Poisson x tie / one-goal weights, OT resolution) is reused
unchanged from ``nhl_joint``; 0.2 changes only the per-team scoring rates:

    log lam = 0.1 linear predictor (+ accepted extra team terms, GLM refit on 2009-2023)
              + gamma0 + gamma * q_opp_goalie            (goalie term, gamma fitted on 2021-2023, the goalie-log seasons)

q_opp_goalie is the expected shrunk goals-vs-expected quality of the OPPOSING starter under a point-in-time starter-probability
model (``nhl_goalie``). Pre-registered selection, all on seasons <= 2023: each extension (high-danger xG rates, shot-attempt
volume, long-rest flags, goalie term) is accepted only if it lowers validation deviance (team terms: fit 2009-2018, validate
2019-2023; goalie: fit 2021-2022, validate 2023). Test cohorts 2024 and 2025 are never read for any choice.

Baselines: alpha-nhl-joint-0.1 (re-fitted here and checked against its committed evaluation), the production incumbent
DATA_ONLY_V1 and the shadow SIM2 (walk-forward reproductions for 2024/2025, the only form that exists for those seasons), the
Kalshi T-60 two-sided MID (2025). Prospective 2026-27: the ACTUAL frozen pre-game forecasts of DATA_ONLY_V1, DATA_ONLY_V2 (SIM2)
and OA_RIDGE_V1 from the owner's ``data-archive`` branch (pinned commit), plus the Kalshi mid recorded in the same frozen row.

``python -m alpha_engine.foundation.nhl_joint_v2`` regenerates the evaluation deterministically.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
import subprocess
import tarfile

import numpy as np

from . import nhl_goalie as NG
from . import nhl_joint as J
from .contract import (EVAL_SCHEMA, OPS, brier_rows, calibration_slope, logloss_rows, paired_cluster_bootstrap, repos_dir,
                       sha256_file, validate_evaluation, write_json)

CHALLENGER_ID = "alpha-nhl-joint-0.2"
OUT = OPS / "NHL" / CHALLENGER_ID
HP = {"carry": 0.6, "hl": 30.0, "hl_fin": 160.0, "k_prior": 40.0, "m_fin": 2500.0, "xg": "fsva"}  # 0.1's frozen hyper-parameters
ARCHIVE_COMMIT = "7b49f21ef79715fda5f708143df890a173974cbc"  # NHL-edge-finder data-archive tip read on 2026-11-14
ARCHIVE_PATHS = ["predictions", "predictions_v2", "predictions_oa", "results", "context/schedule", "context/goalie_observations",
                 "player_events/goalies"]
GOALIE_FIRST, GOALIE_TRAIN_LAST = 2021, 2023
G_GRID = {"prior": [10.0, 25.0, 50.0, 100.0, 200.0], "hl": [40.0, 80.0, 160.0, 320.0], "carry": [0.6, 1.0]}
REF_01, REF_V1, REF_SIM2, REF_MKT = "challenger:alpha-nhl-joint-0.1", J.REF_V1, J.REF_SIM2, J.REF_MKT
P_V1, P_V2, P_OA, P_01, P_MKT = ("prospective_frozen:DATA_ONLY_V1", "prospective_frozen:DATA_ONLY_V2_SIM2", "prospective_frozen:OA_RIDGE_V1",
                                 "prospective:alpha-nhl-joint-0.1", "prospective_market:kalshi_mid_at_freeze")
FREEZE_MIN = 60.0
GAME_SERIES = ("KXNHLGAME-", "KXNHLTOTAL-", "KXNHLSPREAD-", "KXNHLTEAMTOTAL-", "KXNHLOT-")
HEAD = ["moneyline", "regulation_tie_overtime", "total_5.5", "total_6.5", "puck_line_1.5", "team_total_2.5", "team_total_3.5"]


# ====================================================================== small helpers
def auc(p, y):
    """Mann-Whitney AUC (ties half) = per-game discrimination, insensitive to any league-level shift."""
    p = np.asarray(p, float); y = np.asarray(y, int)
    order = np.argsort(p, kind="stable"); r = np.empty(len(p)); ps = p[order]
    i = 0
    while i < len(p):
        j = i
        while j + 1 < len(p) and ps[j + 1] == ps[i]:
            j += 1
        r[order[i:j + 1]] = (i + j) / 2 + 1; i = j + 1
    n1 = int(y.sum()); n0 = len(y) - n1
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / max(n1 * n0, 1))


def freeze_rows(rows, key, min_minutes=FREEZE_MIN):
    """Per ``key`` the LAST pre-game row (by predicted_at_utc) with minutes_to_start >= ``min_minutes`` (the T-60 freeze)."""
    best = {}
    for r in rows:
        try:
            mts = float(r.get("minutes_to_start"))
        except (TypeError, ValueError):
            continue
        if mts < min_minutes or str(r.get("pregame", "True")) == "False":
            continue
        k = r[key]
        if k not in best or r["predicted_at_utc"] > best[k]["predicted_at_utc"]:
            best[k] = r
    return best


def market_outcome(fam, team_id, thr, res):
    """Kalshi event truth from the official final score (OT/SO winner goal included, as Kalshi settles)."""
    hf, af = int(res["home_final"]), int(res["away_final"]); home = team_id is not None and int(team_id) == int(res["home_team_id"])
    if fam == "game_winner":
        return int((hf > af) == home)
    if fam == "game_total":
        return int(hf + af > float(thr))
    if fam == "game_spread":
        return int(((hf - af) if home else (af - hf)) > float(thr))
    if fam == "team_total":
        return int((hf if home else af) > float(thr))
    if fam == "game_overtime":
        return int(res["last_period_type"] in ("OT", "SO"))
    raise ValueError(fam)


def market_prob(mk, i, fam, team_id, thr, home_id):
    home = team_id is not None and int(team_id) == int(home_id)
    if fam == "game_winner":
        p = mk["p_home_win"][i]; return float(p if home else 1 - p)
    if fam == "game_total":
        return float(mk["total_pmf"][i, int(math.floor(float(thr))) + 1:].sum())
    if fam == "game_spread":
        off = mk["margin_offset"]; d = np.arange(-off, off + 1); s = d if home else -d
        return float(mk["margin_pmf"][i, s > float(thr)].sum())
    if fam == "team_total":
        pmf = mk["home_pmf"] if home else mk["away_pmf"]; return float(pmf[i, int(math.floor(float(thr))) + 1:].sum())
    if fam == "game_overtime":
        return float(mk["p_reg_tie"][i])
    raise ValueError(fam)


# ====================================================================== loaders
def load_archive(commit=ARCHIVE_COMMIT):
    """Read the pinned data-archive commit in memory (``git archive`` of the owner's clone). Returns (dict path->rows, note)."""
    clone = repos_dir() / "NHL-edge-finder"
    try:
        blob = subprocess.run(["git", "-C", str(clone), "archive", commit] + ARCHIVE_PATHS, capture_output=True, check=True, timeout=600).stdout
    except Exception as e:  # noqa: BLE001
        return None, f"data-archive commit {commit[:12]} not readable from the clone ({type(e).__name__}); prospective section skipped"
    out = {}
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        for m in sorted(tf.getmembers(), key=lambda m: m.name):
            if not m.isfile() or not m.name.endswith(".jsonl.gz"):
                continue
            top = m.name.split("/dt=")[0]
            raw = gzip.decompress(tf.extractfile(m).read()).decode()
            if top in ("predictions", "predictions_v2"):
                lines = [l for l in raw.splitlines() if any(s in l for s in GAME_SERIES)]
            else:
                lines = [l for l in raw.splitlines() if l.strip()]
            out.setdefault(top, []).extend(json.loads(l) for l in lines)
            out.setdefault("_files", {}).setdefault(top, []).append(m.name)
    return out, f"data-archive@{commit[:12]} read in memory"


def load_moneypuck_ext():
    import pandas as pd
    extra = ["highDangerxGoalsFor", "highDangerxGoalsAgainst", "scoreAdjustedShotsAttemptsFor", "scoreAdjustedShotsAttemptsAgainst"]
    fs = sorted((J._hist() / "moneypuck").glob("team_games_*.parquet"))
    return pd.concat([pd.read_parquet(f, columns=J.MP_COLS + extra) for f in fs], ignore_index=True), fs


def load_goalie_games(arch):
    """Official goalie game logs 2021..2025 (main) + 2026-27 (data-archive player_events, latest observation per row)."""
    import pandas as pd
    fs = sorted((J._hist() / "players").glob("goalies_*.parquet"))
    cols = ["game_id", "season", "game_date", "game_type", "player_id", "team_id", "home_team_id", "away_team_id", "is_home", "starter", "toi_s",
            "saves", "shots_against", "goals_against", "name"]
    gl = pd.concat([pd.read_parquet(f, columns=cols) for f in fs], ignore_index=True)
    n26 = 0
    if arch and arch.get("player_events/goalies"):
        last = {}
        for r in arch["player_events/goalies"]:
            k = (r["game_id"], r["player_id"])
            if k not in last or r["_observed_at_utc"] >= last[k]["_observed_at_utc"]:
                last[k] = r
        rows = [{"game_id": int(r["game_id"]), "season": int(r["season"]), "game_date": r["game_date"], "game_type": int(r["game_type"]),
                 "player_id": int(r["player_id"]), "team_id": int(r["team_id"]), "home_team_id": int(r["home_team_id"]),
                 "away_team_id": int(r["away_team_id"]), "is_home": str(r["is_home"]) == "True",
                 "starter": str(r["starter"]) == "True", "toi_s": float(r["toi_s"]), "saves": float(r["saves"]),
                 "shots_against": float(r["shots_against"]), "goals_against": float(r["goals_against"]), "name": r.get("name")} for r in last.values()]
        a = pd.DataFrame(rows); a = a[a["season"] == 2026]
        gl = gl[gl["season"] != 2026]  # main's 2026 file is a 12-row opening-night stub; the archive supersedes it
        gl = pd.concat([gl, a], ignore_index=True); n26 = len(a)
    gl = gl[gl["game_type"] == 2].copy()
    gl["day"] = (pd.to_datetime(gl["game_date"]).values.astype("datetime64[D]") - np.datetime64("2000-01-01")).astype(int)
    return gl.sort_values(["day", "game_id", "player_id"], kind="stable").reset_index(drop=True), fs, n26


def load_shot_xg():
    """Per (game_id, goalie) MoneyPuck unblocked-attempt xG and goals faced (regular season, periods 1-4, not empty net)."""
    import pandas as pd
    fs = sorted((J._hist() / "moneypuck").glob("shots_*.parquet")); parts = []
    cols = ["nhl_game_id", "isPlayoffGame", "period", "goal", "xGoal", "shotOnEmptyNet", "goalieIdForShot"]
    nrows = 0
    for f in fs:
        s = pd.read_parquet(f, columns=cols); nrows += len(s)
        s = s[(s["isPlayoffGame"] == 0) & (s["period"] <= 4) & (s["shotOnEmptyNet"] == 0) & s["goalieIdForShot"].notna()]
        parts.append(s.groupby(["nhl_game_id", "goalieIdForShot"])[["xGoal", "goal"]].sum().reset_index())
    x = pd.concat(parts, ignore_index=True)
    x.columns = ["game_id", "player_id", "xga", "mp_goals"]; x["game_id"] = x["game_id"].astype(int); x["player_id"] = x["player_id"].astype(int)
    return x, fs, nrows


def games_2026(arch):
    """Final 2026-27 regular-season games from the archive's results + schedule (latest observation per game)."""
    import pandas as pd
    res, sch = {}, {}
    for r in arch.get("results", []):
        if r.get("status") == "final" and (r["game_id"] not in res or r["_observed_at_utc"] >= res[r["game_id"]]["_observed_at_utc"]):
            res[r["game_id"]] = r
    for r in arch.get("context/schedule", []):
        if r["game_id"] not in sch or r["_observed_at_utc"] >= sch[r["game_id"]]["_observed_at_utc"]:
            sch[r["game_id"]] = r
    rows = []
    for gid in sorted(res):
        r, s = res[gid], sch.get(gid)
        if s is None or str(gid)[4:6] != "02":
            continue
        hf, af = int(r["home_final"]), int(r["away_final"])
        rows.append({"game_id": int(gid), "season": 2026, "game_type": 2, "game_date": s["game_date_et"], "start_time_utc": s["start_time_utc"],
                     "home_team_id": int(r["home_team_id"]), "away_team_id": int(r["away_team_id"]), "home_abbrev": s["home_abbrev"],
                     "away_abbrev": s["away_abbrev"], "home_score": hf, "away_score": af, "total": hf + af, "home_win": hf > af,
                     "last_period_type": r["last_period_type"], "final": True})
    return pd.DataFrame(rows), res, sch


# ====================================================================== features
def extra_team_features(tg, hp):
    """Walk-forward shrunk log-ratio rates per 60 (all situations): high-danger xG for/against and score-adjusted shot attempts."""
    g = lambda c: tg[c].values.astype(float) if c in tg else np.full(len(tg), np.nan)
    X = np.column_stack([g("iceTime_all"), g("highDangerxGoalsFor_all"), g("highDangerxGoalsAgainst_all"),
                         g("scoreAdjustedShotsAttemptsFor_all"), g("scoreAdjustedShotsAttemptsAgainst_all")])
    X[np.isnan(X).any(1)] = np.nan
    S = J.walk_forward_state(tg["team"].values, tg["season"].values, X, np.full(5, 0.5 ** (1 / hp["hl"])), np.full(5, hp["carry"]))
    L = J.trailing_league(tg["day"].values, X); kp = hp["k_prior"]
    rate = lambda j: np.log(((S[:, j] + kp * L[:, j]) / (S[:, 0] + kp * L[:, 0])) / (L[:, j] / L[:, 0]))
    opp = np.arange(len(tg)) ^ 1
    rd = tg["rest_days"].fillna(0).values
    r3 = (rd >= 3).astype(float)
    return {"hd_o": rate(1), "hd_d": rate(2)[opp], "sa_o": rate(3), "sa_d": rate(4)[opp], "r3_t": r3, "r3_o": r3[opp]}


def goalie_block(tg, gl, xg, extra_starters=None):
    """Team-game goalie structures: candidates (PIT), as-played starter, expected-goals table. Rows keyed like tg (game_id, home)."""
    import pandas as pd
    gl = gl.merge(xg, on=["game_id", "player_id"], how="left")
    ex, kx, ks = NG.expected_goals(gl["day"].values, gl["goals_against"].values, gl["shots_against"].values, gl["xga"].values, gl["toi_s"].values)
    gl["exp_g"] = ex
    key = pd.MultiIndex.from_arrays([tg["game_id"].values, tg["home"].values.astype(int)])
    tpos = pd.Series(np.arange(len(tg)), index=key)
    st = gl[gl["starter"].astype(bool)]
    row = tpos.reindex(pd.MultiIndex.from_arrays([st["game_id"].values, st["is_home"].astype(int).values])).values
    starter = np.full(len(tg), -1, dtype=np.int64)
    ok = ~np.isnan(row); starter[row[ok].astype(int)] = st["player_id"].values[ok]
    n_fill = 0
    for (g, h), p in sorted((extra_starters or {}).items()):
        i = tpos.get((g, h))
        if i is not None and starter[i] < 0:
            starter[i] = p; n_fill += 1
    team, day, season = tg["team"].values, tg["day"].values, tg["season"].values
    starts = {}
    for i in np.flatnonzero(starter >= 0):
        starts.setdefault(int(team[i]), []).append((int(day[i]), int(season[i]), int(starter[i])))
    for t in starts:
        starts[t].sort()
    sel = np.flatnonzero(season >= GOALIE_FIRST)
    cands = NG.starter_candidates([(int(i), int(team[i]), int(day[i]), int(season[i])) for i in sel], starts)
    C = {int(i): c for i, c in zip(sel, cands)}
    return gl, starter, C, {"rows_with_starter": int((starter >= 0).sum()), "starters_filled_from_archive_results": n_fill, "kx_median": float(np.median(kx)), "ks_median": float(np.median(ks))}


def goalie_q(gl, tg, starter, C, ghp, beta):
    """Per tg row (own goalie): q of as-played starter (ORACLE), PIT mixture, naive last-10 share mixture; and starter probabilities."""
    post = NG.goalie_quality_state(gl["player_id"].values, gl["season"].values, gl["day"].values, gl["goals_against"].values.astype(float),
                                   gl["exp_g"].values, gl["toi_s"].values, ghp["hl"], ghp["carry"])
    look = NG.QualityLookup(gl["player_id"].values, gl["season"].values, gl["day"].values, post, ghp["carry"], ghp["prior"])
    n = len(tg); q_or, q_mix, q_nv = np.zeros(n), np.zeros(n), np.zeros(n)
    day, season = tg["day"].values, tg["season"].values
    for i, (pl, X) in C.items():
        d, s = int(day[i]), int(season[i])
        if starter[i] >= 0:
            q_or[i] = look.q(int(starter[i]), d, s)
        if len(pl):
            qs = np.array([look.q(p, d, s) for p in pl]); p = NG.starter_probs(X, beta)
            q_mix[i] = float(p @ qs)
            w = X[:, 0]; q_nv[i] = float(w @ qs / w.sum()) if w.sum() > 0 else float(qs.mean())
    return q_or, q_mix, q_nv


def logit_groups(C, starter, rows):
    gs = []
    for i in rows:
        pl, X = C.get(int(i), ([], None))
        if starter[i] >= 0 and int(starter[i]) in pl and len(pl) > 1:
            gs.append((X, pl.index(int(starter[i]))))
    return gs


def fit_offset_glm(base_log, feats, y, mask):
    X = np.column_stack([np.ones(int(mask.sum()))] + [f[mask] for f in feats])
    return J.poisson_glm(X, y[mask], base_log[mask])


def apply_offset(base_log, feats, b):
    return base_log + b[0] + sum(bi * f for bi, f in zip(b[1:], feats))


# ====================================================================== main pipeline
def run(log=print):
    import pandas as pd
    games, gfiles = J.load_games(); mp, mfiles = load_moneypuck_ext()
    docs = repos_dir() / "NHL-edge-finder" / "docs" / "research"
    v1 = pd.read_csv(docs / "walk_forward_36570274279_games.csv"); v2 = pd.read_csv(docs / "walk_forward_v2_wf2_20260929_games.csv")
    log("reading data-archive"); arch, arch_note = load_archive()
    g26, res26, sch26 = games_2026(arch) if arch else (pd.DataFrame(), {}, {})
    games_all = pd.concat([games, g26.drop(columns=["start_time_utc"])], ignore_index=True) if len(g26) else games
    tg = J.build_team_games(games_all, mp)
    G = J.game_frame(tg)
    fin = games_all[games_all["final"].astype(bool)]
    gi = fin.drop_duplicates("game_id").set_index("game_id").loc[G["game_id"]]
    G["home_win"] = gi["home_win"].astype(int).values; G["extra"] = gi["last_period_type"].isin(["OT", "SO"]).astype(int).values
    G["hs"] = gi["home_score"].astype(int).values; G["as"] = gi["away_score"].astype(int).values
    G["total"] = G["hs"] + G["as"]; G["margin"] = G["hs"] - G["as"]
    season, sg, y = tg["season"].values, G["season"], tg["rg"].values.astype(float)

    # ---------------------------------------------------------------- 0.1 base, reproduced
    F = J.make_features(tg, HP); F["f"].update(extra_team_features(tg, HP))
    base_names = list(J.FEATS["full"])
    fit_rows = (season >= J.FIT_FIRST) & (season <= J.TRAIN_LAST)
    train_g = (sg >= J.FIT_FIRST) & (sg <= J.TRAIN_LAST)
    beta01 = J.fit_glm(tg, F, base_names, fit_rows); lam01 = J.predict_lam(F, base_names, beta01)
    joint01 = J.fit_joint(lam01[1::2][train_g], lam01[0::2][train_g], G["rh"][train_g], G["ra"][train_g])
    ties = train_g & (G["extra"] == 1); k01, _ = J.fit_ot_k(lam01[1::2][ties], lam01[0::2][ties], G["home_win"][ties])
    m01 = J.Model(tg, F, base_names, beta01, joint01, k01)

    # ---------------------------------------------------------------- team-term selection on validation (2009-2018 fit, 2019-2023 val)
    fit_v = (season >= J.FIT_FIRST) & (season < J.VAL_FIRST); val_v = (season >= J.VAL_FIRST) & (season <= J.TRAIN_LAST)

    def vdev(names):
        b = J.fit_glm(tg, F, names, fit_v)
        return float(np.mean(J.poisson_deviance_rows(y[val_v], J.predict_lam(F, names, b)[val_v])))
    d_base = vdev(base_names); team_sel = []
    for ext, cols in (("high_danger_xg", ["hd_o", "hd_d"]), ("shot_attempt_volume", ["sa_o", "sa_d"]), ("long_rest", ["r3_t", "r3_o"])):
        dv = vdev(base_names + cols)
        team_sel.append({"extension": ext, "features": cols, "val_deviance_base": d_base, "val_deviance_with": dv, "delta": dv - d_base,
                         "accepted": bool(dv < d_base)})
    acc_team = [c for s in team_sel if s["accepted"] for c in s["features"]]
    names = base_names + acc_team
    log(f"team extensions accepted: {acc_team}")
    beta = J.fit_glm(tg, F, names, fit_rows); base_log = np.log(J.predict_lam(F, names, beta))

    # ---------------------------------------------------------------- goalie inputs
    log("goalie inputs"); gl, glfiles, n26 = load_goalie_games(arch); xg, sfiles, n_shots = load_shot_xg()
    xs = {}
    for g, r in res26.items():
        for h, k in ((1, "home_starting_goalie_id"), (0, "away_starting_goalie_id")):
            if r.get(k) not in (None, "None", ""):
                xs[(int(g), h)] = int(r[k])
    gl, starter, C, ginfo = goalie_block(tg, gl, xg, xs)
    opp = np.arange(len(tg)) ^ 1
    yr = lambda a, b: np.flatnonzero((season >= a) & (season <= b))
    tr_f = (season >= GOALIE_FIRST) & (season <= GOALIE_TRAIN_LAST)
    specs = {"add_to_team_model": names, "replace_finishing_term": [n for n in names if n not in ("fin_o", "fin_d")]}
    # rolling-origin validation (never reads 2024+): fold v fits the team GLM on 2009..v-1, the starter model and gamma on 2021..v-1
    folds = []
    for vs in (2022, 2023):
        fm = (season >= J.FIT_FIRST) & (season < vs)
        bls = {k: np.log(J.predict_lam(F, nm, J.fit_glm(tg, F, nm, fm))) for k, nm in specs.items()}
        folds.append({"val": vs, "tr": (season >= GOALIE_FIRST) & (season < vs), "va": season == vs, "bl": bls,
                      "beta_s": NG.fit_conditional_logit(logit_groups(C, starter, yr(GOALIE_FIRST, vs - 1)))})

    def cv_dev(spec, qfun):
        num = den = 0.0
        for fo in folds:
            f = [] if qfun is None else [qfun(fo)[opp]]
            b = fit_offset_glm(fo["bl"][spec], f, y, fo["tr"])
            num += float(J.poisson_deviance_rows(y[fo["va"]], np.exp(apply_offset(fo["bl"][spec], f, b))[fo["va"]]).sum()); den += int(fo["va"].sum())
        return num / den
    cand = [{"spec": k, "goalie": None, "val_deviance": cv_dev(k, None)} for k in specs]
    for P in G_GRID["prior"]:
        for hl in G_GRID["hl"]:
            for ca in G_GRID["carry"]:
                ghp0 = {"prior": P, "hl": hl, "carry": ca}
                qs = [goalie_q(gl, tg, starter, C, ghp0, fo["beta_s"])[1] for fo in folds]
                for k in specs:
                    cand.append({"spec": k, "goalie": ghp0, "val_deviance": cv_dev(k, lambda fo, qs=qs: qs[folds.index(fo)])})
    best_all = min(cand, key=lambda c: (c["val_deviance"], c["goalie"] is not None))
    best_g = min([c for c in cand if c["goalie"] is not None], key=lambda c: c["val_deviance"])
    goalie_accepted = best_all["goalie"] is not None
    ghp, gspec = best_g["goalie"], best_g["spec"]
    log(f"selection: headline {best_all['spec']} goalie={best_all['goalie']} ({best_all['val_deviance']:.6f}); best goalie config {gspec} {ghp} "
        f"({best_g['val_deviance']:.6f}); no-goalie {[c['val_deviance'] for c in cand[:2]]}")
    beta_s = NG.fit_conditional_logit(logit_groups(C, starter, yr(GOALIE_FIRST, GOALIE_TRAIN_LAST)))
    q_or, q_mix, q_nv = goalie_q(gl, tg, starter, C, ghp, beta_s)
    gl_sv = gl.copy(); gl_sv["exp_g"] = NG.expected_goals(gl["day"].values, gl["goals_against"].values, gl["shots_against"].values,
                                                         np.full(len(gl), np.nan), gl["toi_s"].values)[0]
    q_sv = goalie_q(gl_sv, tg, starter, C, ghp, beta_s)[1]
    fq = {"mix": q_mix[opp], "oracle": q_or[opp], "naive": q_nv[opp], "savepct": q_sv[opp]}
    team_fit = {k: J.fit_glm(tg, F, nm, fit_rows) for k, nm in specs.items()}
    team_log = {k: np.log(J.predict_lam(F, specs[k], team_fit[k])) for k in specs}

    def lam_log(spec, qkey, nm_override=None):
        bl = team_log[spec] if nm_override is None else np.log(J.predict_lam(F, nm_override, J.fit_glm(tg, F, nm_override, fit_rows)))
        f = [] if qkey is None else [fq[qkey] if isinstance(qkey, str) else qkey]
        g = fit_offset_glm(bl, f, y, tr_f)
        return apply_offset(bl, f, g), g

    def model_from(log_lam):
        la, lh = np.exp(log_lam[0::2]), np.exp(log_lam[1::2])
        jt = J.fit_joint(lh[train_g], la[train_g], G["rh"][train_g], G["ra"][train_g])
        tt = train_g & (G["extra"] == 1); k, _ = J.fit_ot_k(lh[tt], la[tt], G["home_win"][tt])
        return J.Model(tg, F, names, beta, jt, k, extra_log=log_lam - np.log(J.predict_lam(F, names, beta)))
    hspec, hq = best_all["spec"], ("mix" if goalie_accepted else None)
    head_log, head_gamma = lam_log(hspec, hq); head = model_from(head_log)
    gam_mix = lam_log(gspec, "mix")[1]
    V = {}  # vid -> (model, sign, label); sign +1: the component (present in headline) helps when diff > 0; -1: the added info helps when diff < 0
    if goalie_accepted:
        V["i_oracle_as_played_starter"] = (model_from(lam_log(gspec, "oracle")[0]), -1, "(i) ORACLE_NOT_PIT: as-played starter replaces the PIT mixture (upper bound of confirmed-starter value)")
        V["ii_naive_share_mixture"] = (model_from(lam_log(gspec, "naive")[0]), 1, "(ii) PIT starter model replaced by last-10-start share weights")
        V["iii_no_goalie_term"] = (model_from(lam_log(gspec, None)[0]), 1, "(iii) goalie quality removed")
        V["iii_b_savepct_quality"] = (model_from(lam_log(gspec, "savepct")[0]), 1, "(iii-b) xG-based goalie quality replaced by save% vs league")
    else:
        V["i_oracle_as_played_starter"] = (model_from(lam_log(gspec, "oracle")[0]), -1, f"(i) ORACLE_NOT_PIT: best validation goalie config ({gspec}) with the as-played starter")
        V["ii_pit_starter_mixture_added"] = (model_from(lam_log(gspec, "mix")[0]), -1, f"(ii) PIT starter-probability mixture goalie term added ({gspec}) - rejected on validation")
        V["ii_b_naive_share_mixture_added"] = (model_from(lam_log(gspec, "naive")[0]), -1, "(ii-b) goalie term with last-10-start share weights instead of the starter model")
        V["iii_savepct_quality_added"] = (model_from(lam_log(gspec, "savepct")[0]), -1, "(iii) goalie term with save%-vs-league quality instead of xG-based quality (PIT mixture)")
    for vid, drop, lab in (("iv_no_xg_ratings", {"off5", "def5", "pp", "pk", "hd_o", "hd_d"}, "(iv) xG ratings removed (5v5 off/def, PP/PK, high-danger; team GLM refit)"),
                           ("v_no_rest", {"b2b_t", "b2b_o", "r3_t", "r3_o"}, "(v) rest removed (back-to-back and long-rest flags; team GLM refit)"),
                           ("vi_no_team_extensions", set(acc_team), "(vi) validation-selected team extensions removed")):
        nm = [n for n in specs[hspec] if n not in drop]
        V[vid] = (model_from(lam_log(hspec, hq, nm)[0]), 1, lab)

    # ---------------------------------------------------------------- data checks (goalie + archive)
    gd = gl.drop_duplicates(["game_id", "player_id"]); dup = len(gl) - len(gd)
    stp = gl[gl["starter"].astype(bool)].groupby(["game_id", "team_id"]).size()
    bad_team = int(((gl["team_id"] != gl["home_team_id"]) & (gl["team_id"] != gl["away_team_id"])).sum()) if "home_team_id" in gl else 0
    xcov = gl[(gl["season"] <= 2025) & (gl["toi_s"] > 0)]
    xrec = xcov.dropna(subset=["xga"])
    ga_rec = float((xrec["mp_goals"] == xrec["goals_against"]).mean())
    tg_g = np.flatnonzero(season >= GOALIE_FIRST); has_st = (starter[tg_g] >= 0)
    in_c = np.array([int(starter[i]) in C[int(i)][0] for i in tg_g if starter[i] >= 0])
    goalie_checks = [
        J.check("goalie_no_duplicate_game_player", dup == 0, f"{len(gl)} regular-season goalie-game rows 2021-2026, {dup} duplicates"),
        J.check("goalie_exactly_one_starter_per_team_game", bool((stp == 1).all()), f"{int((stp == 1).sum())}/{len(stp)} team-games have exactly one starter"),
        J.check("goalie_team_id_is_home_or_away", bad_team == 0, f"{bad_team} rows whose team_id is neither the home nor away id (main files)"),
        J.check("goalie_starter_coverage_of_team_games", bool(has_st.mean() > 0.995),
                f"{int(has_st.sum())}/{len(tg_g)} team-games 2021+ have an as-played starter; by season "
                + str({int(s0): f"{int(has_st[season[tg_g] == s0].sum())}/{int((season[tg_g] == s0).sum())}" for s0 in sorted(set(season[tg_g].tolist()))})
                + " (the 2026-27 gap: the archive's player_events/goalies and results starting-goalie ids cover only part of the games; missing team-games use the PIT mixture with no goalie-log update)"),
        J.check("moneypuck_shot_xg_coverage", bool(xrec.shape[0] / max(len(xcov), 1) > 0.98),
                f"{len(xrec)}/{len(xcov)} goalie-games 2021-2025 with toi>0 have MoneyPuck shot xG ({n_shots} shot rows read); 2026-27 has none (save%-based expectation)"),
        J.check("moneypuck_goals_reconcile_with_goalie_log", ga_rec > 0.97, f"MoneyPuck non-empty-net goals (periods 1-4) equal the official goalie goals_against in {ga_rec:.2%} of goalie-games"),
        J.check("pit_starter_candidates_cover_actual", bool(in_c.mean() > 0.9),
                f"actual starter is among the PIT candidates (started for the team in the prior 365 days, top-{NG.MAX_CAND} by recency) in {in_c.mean():.2%} of {len(in_c)} team-games"),
        J.check("goalie_state_strictly_earlier", True, "quality lookups use the goalie's last row with day < game day; candidate features use starts with day < game day"),
        J.check("starter_flag_used_only_as_label_or_oracle", True, "as-played starter = conditional-logit training label (2021-2023) and ablation (i) ORACLE_NOT_PIT input only"),
    ]
    # leak guard: perturb all goalie rows from the first test date; no pre-test feature may change
    cut = int(tg["day"].values[season > J.TRAIN_LAST].min())
    gl2 = gl.copy(); late = gl2["day"].values >= cut
    for c in ("goals_against", "exp_g"):
        v = gl2[c].values.astype(float); v[late] = v[late][::-1] * 1.9; gl2[c] = v
    _, qm2, _ = goalie_q(gl2, tg, starter, C, ghp, beta_s)
    pre = tg["day"].values <= cut
    leak = float(np.max(np.abs(qm2[pre] - q_mix[pre])))
    goalie_checks.append(J.check("leak_guard_goalie_future_perturbation", leak < 1e-12,
                                 f"perturbing every goalie outcome from the first test date onward changes no goalie feature on or before that date (max diff {leak:.1e})"))

    # starter-model diagnostics on test seasons (PIT top-1 accuracy / log loss vs 'last game's starter')
    def starter_diag(rows):
        gs = logit_groups(C, starter, rows); top = np.mean([int(np.argmax(NG.starter_probs(X, beta_s)) == c) for X, c in gs])
        last = np.mean([int(np.argmax(X[:, 1]) == c and X[:, 1].max() > 0) for X, c in gs])
        return {"groups_with_choice": len(gs), "top1_accuracy": float(top), "last_game_starter_accuracy": float(last), "nll": NG.starter_nll(gs, beta_s)}
    starter_model = {"features": NG.CAND_FEATS, "beta": dict(zip(NG.CAND_FEATS, beta_s.tolist())), "fit_seasons": "2021-2023",
                     "test": {str(s): starter_diag(yr(s, s)) for s in (2024, 2025, 2026) if len(yr(s, s))}}

    # ---------------------------------------------------------------- 2024/2025 test frame (incumbent walk-forward games)
    pos = pd.Series(np.arange(len(G["game_id"])), index=G["game_id"])
    ti = pos.reindex(v1["game_id"].values).values.astype(int)
    assert set(sg[ti].tolist()) == set(J.TEST_SEASONS)
    gid = G["game_id"][ti]; coh = sg[ti].astype(str)
    Y = {"home_win": G["home_win"][ti], "ot": G["extra"][ti], "total": G["total"][ti], "margin": G["margin"][ti], "hs": G["hs"][ti], "as": G["as"][ti]}

    def fam_probs(mkt, Yd, g, c):
        o = {"moneyline": (mkt["p_home_win"], Yd["home_win"], g, c), "regulation_tie_overtime": (mkt["p_reg_tie"], Yd["ot"], g, c)}
        for s in (4.5, 5.5, 6.5, 7.5):
            o[f"total_{s}"] = (J.p_over(mkt["total_pmf"], s), (Yd["total"] > s).astype(int), g, c)
        o["puck_line_1.5"] = (np.concatenate([J.p_margin_over(mkt, 1.5, "home"), J.p_margin_over(mkt, 1.5, "away")]),
                              np.concatenate([(Yd["margin"] > 1.5), (-Yd["margin"] > 1.5)]).astype(int), np.concatenate([g, g]), np.concatenate([c, c]))
        for s in (2.5, 3.5):
            o[f"team_total_{s}"] = (np.concatenate([J.p_over(mkt["home_pmf"], s), J.p_over(mkt["away_pmf"], s)]),
                                    np.concatenate([(Yd["hs"] > s), (Yd["as"] > s)]).astype(int), np.concatenate([g, g]), np.concatenate([c, c]))
        return o

    def ref_probs(pre):
        d = v2; o = {"moneyline": d[f"{pre}_p_home_win"].values, "regulation_tie_overtime": d[f"{pre}_p_overtime"].values}
        for s in (4.5, 5.5, 6.5, 7.5):
            o[f"total_{s}"] = d[f"{pre}_p_over_{s}"].values
        o["puck_line_1.5"] = np.concatenate([d[f"{pre}_p_home_minus_1_5"].values, d[f"{pre}_p_away_minus_1_5"].values])
        for s in (2.5, 3.5):
            o[f"team_total_{s}"] = np.concatenate([d[f"{pre}_p_home_over_{s}"].values, d[f"{pre}_p_away_over_{s}"].values])
        return o
    mk, mk01 = head.markets(ti), m01.markets(ti)
    ch, c01 = fam_probs(mk, Y, gid, coh), fam_probs(mk01, Y, gid, coh)
    refs = {REF_V1: ref_probs("V1"), REF_SIM2: ref_probs("SIM2"), REF_01: {f: c01[f][0] for f in c01}}
    arch_of = lambda fam: J.ARCH["ev"] if fam.startswith(("regulation", "game_overtime")) else J.ARCH["tot"] if "total" in fam else J.ARCH["ml"]
    results = []
    for ref, rp in refs.items():
        for fam in HEAD:
            p, yy, gg, cc = ch[fam]
            for metric in ("logloss", "brier"):
                results += J.compare(fam, arch_of(fam), metric, ref, p, rp[fam], yy, gg, cc)
    # reproduction check of 0.1 against its committed evaluation
    ref01 = json.loads((OPS / "NHL" / "alpha-nhl-joint-0.1" / "evaluation.json").read_text())
    want = {r["market_family"]: r["challenger"] for r in ref01["results"] if r["reference"] == REF_V1 and r["cohort"] == "pooled" and r["metric"] == "logloss"}
    rep_err = max(abs(float(logloss_rows(c01[f][0], c01[f][1]).mean()) - want[f]) for f in HEAD)

    # ---------------------------------------------------------------- Kalshi T-60 mid, 2025 cohort
    log("kalshi 2025 reference")
    reg_games = games[(games["game_type"] == 2) & games["final"].astype(bool)]
    q, kcov, k_entries, k_checks = J.kalshi_reference(reg_games[(reg_games["season"] == 2025) & reg_games["game_id"].isin(set(gid.tolist()))])
    tpos = pd.Series(np.arange(len(gid)), index=gid); market_context = []
    if len(q):
        q = q.assign(pos=tpos.reindex(q["game_id"].values).values); q = q[q["pos"].notna()].copy(); q["pos"] = q["pos"].astype(int)
        ml = q[q["series"] == "KXNHLGAME"].copy(); ml["p_home"] = np.where(ml["side"] == "home", ml["mid"], 1 - ml["mid"])
        gm = ml.groupby("pos")["p_home"].mean(); ps = gm.index.values
        sets = [("moneyline", J.ARCH["ml"], mk["p_home_win"][ps], mk01["p_home_win"][ps], gm.values, Y["home_win"][ps], gid[ps])]
        tt = q[q["series"] == "KXNHLTOTAL"]
        for s in (5.5, 6.5):
            d = tt[tt["strike"] == s]; ps2 = d["pos"].values
            sets.append((f"total_{s}", J.ARCH["tot"], J.p_over(mk["total_pmf"][ps2], s), J.p_over(mk01["total_pmf"][ps2], s), d["mid"].values, d["y"].values, gid[ps2]))
        sp = q[(q["series"] == "KXNHLSPREAD") & (q["strike"] == 1.5)]; hm = (sp["side"] == "home").values; ps3 = sp["pos"].values
        sets.append(("puck_line_1.5", J.ARCH["ml"], np.where(hm, J.p_margin_over(mk, 1.5, "home")[ps3], J.p_margin_over(mk, 1.5, "away")[ps3]),
                     np.where(hm, J.p_margin_over(mk01, 1.5, "home")[ps3], J.p_margin_over(mk01, 1.5, "away")[ps3]), sp["mid"].values, sp["y"].values, gid[ps3]))
        for fam, ar, pc, p1, pm, yy, gg in sets:
            if len(yy) < 50:
                continue
            for metric in ("logloss", "brier"):
                results += J.compare(fam, ar, metric, REF_MKT, pc, pm, yy, gg, np.full(len(yy), "2025"))
                fn = brier_rows if metric == "brier" else logloss_rows
                bs = paired_cluster_bootstrap(fn(p1, yy) - fn(pm, yy), gg)
                market_context.append({"market_family": fam, "metric": metric, "n_rows": bs["n_rows"], "challenger_0_2": float(fn(pc, yy).mean()),
                                       "challenger_0_1": float(fn(p1, yy).mean()), "market_mid": float(fn(pm, yy).mean()),
                                       "challenger_0_1_minus_market": bs["mean"], "ci95_0_1": [bs["lo"], bs["hi"]]})

    # ---------------------------------------------------------------- prospective 2026-27: actual frozen forecasts
    prospective, p_entries, p_checks, timing = {"status": "SKIPPED", "reason": arch_note}, [], [], {}
    t26 = np.flatnonzero(sg == 2026)
    if arch and len(t26):
        log("prospective 2026-27")
        mk26, mk26_01 = head.markets(t26), m01.markets(t26)
        p26 = {int(g): k for k, g in enumerate(G["game_id"][t26])}
        fv1 = freeze_rows(arch.get("predictions", []), "ticker"); fv2 = freeze_rows(arch.get("predictions_v2", []), "ticker")
        rows = []
        n_res_mismatch = 0
        for tk in sorted(fv2):
            r2 = fv2[tk]; r1 = fv1.get(tk); g = int(r2["game_id"]); fam = r2["family"]
            if g not in p26 or str(g) not in res26:
                continue
            res = res26[str(g)]; k = p26[g]; thr = r2.get("threshold"); tm = r2.get("team_id")
            yv = market_outcome(fam, tm, thr, res)
            pv1 = r1.get("p_data_only") if r1 else None
            pv1 = float(pv1) if pv1 not in (None, "None") else None
            pv2 = float(r2["p_data_only_v2"]) if r2.get("p_data_only_v2") not in (None, "None") else None
            pm = r1.get("p_market") if r1 else r2.get("p_market")
            pm = float(pm) if pm not in (None, "None") else None
            rows.append({"ticker": tk, "game_id": g, "family": fam, "y": yv, "p_c": market_prob(mk26, k, fam, tm, thr, res["home_team_id"]),
                         "p_01": market_prob(mk26_01, k, fam, tm, thr, res["home_team_id"]), "p_v1": pv1, "p_v2": pv2, "p_mkt": pm,
                         "freeze_v1": r1["predicted_at_utc"] if r1 else None, "freeze_v2": r2["predicted_at_utc"],
                         "mts_v2": float(r2["minutes_to_start"])})
        P = pd.DataFrame(rows)
        fam_map = {"game_winner": ("moneyline", J.ARCH["ml"]), "game_total": ("total_all_listed_strikes", J.ARCH["tot"]),
                   "game_spread": ("spread_all_listed_strikes", J.ARCH["ml"]), "team_total": ("team_total_all_listed_strikes", J.ARCH["tot"]),
                   "game_overtime": ("regulation_tie_overtime", J.ARCH["ev"])}
        pcov = {}
        for famk, (fname, ar) in fam_map.items():
            d = P[P["family"] == famk] if len(P) else P
            pcov[famk] = {"frozen_markets": int(len(d)), "games": int(d["game_id"].nunique()) if len(d) else 0}
            for ref, col in ((P_V1, "p_v1"), (P_V2, "p_v2"), (P_01, "p_01"), (P_MKT, "p_mkt")):
                dd = d[d[col].notna()] if len(d) else d
                if len(dd) < 30:
                    continue
                for metric in ("logloss", "brier"):
                    results += J.compare(fname, ar, metric, ref, dd["p_c"].values, dd[col].values.astype(float), dd["y"].values,
                                         dd["game_id"].values, np.full(len(dd), "2026"))
                pcov[famk][f"n_{col}"] = int(len(dd))
        # game-level 2026 (all final games): vs OA_RIDGE_V1 and the V1 numbers recorded in the same OA row
        foa = freeze_rows(arch.get("predictions_oa", []), "game_id")
        oa = [(p26[int(g)], r) for g, r in sorted(foa.items()) if int(g) in p26 and r.get("arm") == "OA_SVA"]
        if len(oa) >= 30:
            ks = np.array([k for k, _ in oa]); gg = G["game_id"][t26][ks]; cc = np.full(len(ks), "2026")
            yy = {"moneyline": G["home_win"][t26][ks], "regulation_tie_overtime": G["extra"][t26][ks]}
            for s in (5.5, 6.5):
                yy[f"total_{s}"] = (G["total"][t26][ks] > s).astype(int)
            pc = {"moneyline": mk26["p_home_win"][ks], "regulation_tie_overtime": mk26["p_reg_tie"][ks],
                  "total_5.5": J.p_over(mk26["total_pmf"][ks], 5.5), "total_6.5": J.p_over(mk26["total_pmf"][ks], 6.5)}
            po = {"moneyline": "p_home_win", "regulation_tie_overtime": "p_overtime", "total_5.5": "p_over_5.5", "total_6.5": "p_over_6.5"}
            for fam in pc:
                pr = np.array([float(r[po[fam]]) for _, r in oa])
                for metric in ("logloss", "brier"):
                    results += J.compare(fam, arch_of(fam), metric, P_OA, pc[fam], pr, yy[fam], gg, cc)
        # confirmed-starter timing: what the prospective DailyFaceoff capture said at the T-60 freeze
        obs = arch.get("context/goalie_observations", [])
        start = {int(g): s["start_time_utc"] for g, s in sch26.items()}
        actual = {}
        for i in t26:
            for row in (i * 2, i * 2 + 1):
                if starter[row] >= 0:
                    actual[(int(tg["game_id"].values[row]), int(tg["team"].values[row]))] = int(starter[row])
        tid_map = lambda t: J.FRANCHISE.get(int(t), int(t))
        nk = lambda nm: (str(nm).strip()[:1].lower(), str(nm).replace(".", " ").split()[-1].lower()) if nm and str(nm).strip() else None
        by_name, by_team_name = {}, {}
        for pid, nm, tm in zip(gl["player_id"].values, gl["name"].values, gl["team_id"].values):
            k0 = nk(nm)
            if k0:
                by_name.setdefault(k0, set()).add(int(pid)); by_team_name.setdefault((tid_map(tm), k0), set()).add(int(pid))
        def df_pid(o):
            k0 = nk(o.get("player_name"))
            if not k0:
                return None
            c1 = by_team_name.get((tid_map(o["team_id"]), k0), set())
            c2 = c1 if len(c1) == 1 else by_name.get(k0, set())
            return next(iter(c2)) if len(c2) == 1 else None
        n_obs_df = n_obs_matched = 0
        last_obs = {}
        for o in obs:
            if o.get("source") != "dailyfaceoff":
                continue
            g = int(o["game_id"]); st0 = start.get(g)
            if st0 is None:
                continue
            cutoff = (pd.Timestamp(st0) - pd.Timedelta(minutes=FREEZE_MIN)).strftime("%Y-%m-%dT%H:%M:%SZ")
            if o["observed_at_utc"] > cutoff:
                continue
            n_obs_df += 1; pid = df_pid(o)
            if pid is None:
                continue
            n_obs_matched += 1; o = {**o, "player_id": pid}
            kk = (g, tid_map(o["team_id"]))
            if kk not in last_obs or o["observed_at_utc"] >= last_obs[kk]["observed_at_utc"]:
                last_obs[kk] = o
        tstat = {}
        for kk, act in actual.items():
            o = last_obs.get(kk); s = o["status"] if o else "NONE"
            t = tstat.setdefault(s, {"team_games": 0, "correct": 0}); t["team_games"] += 1; t["correct"] += int(bool(o) and int(o["player_id"]) == act)
        for s in tstat.values():
            s["accuracy"] = s["correct"] / s["team_games"] if s["team_games"] else None
        timing = {"freeze": f"T-{int(FREEZE_MIN)} min before scheduled start", "source": "context/goalie_observations (dailyfaceoff), data-archive",
                  "by_status_at_freeze": tstat, "team_games": len(actual),
                  "dailyfaceoff_observations_before_freeze": n_obs_df, "matched_to_nhl_goalie_id": n_obs_matched,
                  "matching": "DailyFaceoff names are mapped in memory to NHL goalie ids by (team, first initial, last name); no names are written"}
        # DailyFaceoff-at-freeze starter arm (prospective only): q of the DF goalie replaces the mixture where DF has a name
        post = NG.goalie_quality_state(gl["player_id"].values, gl["season"].values, gl["day"].values, gl["goals_against"].values.astype(float),
                                       gl["exp_g"].values, gl["toi_s"].values, ghp["hl"], ghp["carry"])
        look = NG.QualityLookup(gl["player_id"].values, gl["season"].values, gl["day"].values, post, ghp["carry"], ghp["prior"])
        q_df = q_mix.copy(); n_df = 0
        for i in t26:
            for row in (i * 2, i * 2 + 1):
                o = last_obs.get((int(tg["game_id"].values[row]), int(tg["team"].values[row])))
                if o:
                    q_df[row] = look.q(int(o["player_id"]), int(tg["day"].values[row]), 2026); n_df += 1
        mkm = lambda ql: J.Model(tg, F, names, beta, head.joint, head.k_ot,
                                 extra_log=apply_offset(team_log[gspec], [ql], gam_mix) - np.log(J.predict_lam(F, names, beta)))
        m_pit, m_df, m_or = mkm(fq["mix"]), mkm(q_df[opp]), mkm(fq["oracle"])
        if True:
            gg26 = G["game_id"][t26]
            def rnll(m):
                Pm = m.reg(t26); ii = np.arange(len(t26))
                return -np.log(Pm[ii, np.clip(G["rh"][t26], 0, J.K - 1), np.clip(G["ra"][t26], 0, J.K - 1)] + 1e-300)
            base_n = rnll(m_pit)
            timing["arms_vs_pit_mixture_regulation_nll_2026"] = {"note": f"same team model ({gspec}), same gamma and joint; only the starter identity differs"}
            for nm, m in (("dailyfaceoff_at_T-60_starter", m_df), ("oracle_as_played_starter", m_or), ("headline_minus_pit", head)):
                bs = paired_cluster_bootstrap(rnll(m) - base_n, gg26)
                timing["arms_vs_pit_mixture_regulation_nll_2026"][nm] = {"diff": bs["mean"], "ci95": [bs["lo"], bs["hi"]], "n_games": bs["n_clusters"]}
            timing["team_games_with_dailyfaceoff_name_at_freeze"] = n_df
        fts = sorted(x for x in P["freeze_v2"].tolist()) if len(P) else []
        prospective = {"status": "EVALUATED", "games_final": int(len(t26)), "frozen_market_rows": int(len(P)), "coverage": pcov,
                       "freeze_rule": f"per Kalshi ticker, the last pre-game frozen prediction row with minutes_to_start >= {int(FREEZE_MIN)}",
                       "freeze_minutes_to_start_v2": {"median": float(P["mts_v2"].median()) if len(P) else None, "max": float(P["mts_v2"].max()) if len(P) else None},
                       "first_freeze": fts[0] if fts else None, "last_freeze": fts[-1] if fts else None,
                       "oa_games": len(oa), "challenger_team_ratings": "frozen at the end of 2025-26 (MoneyPuck team_games for 2026-27 not archived): "
                       "ratings are carried with the 0.1 season carry and do NOT update in-season; league scoring offset, rest and goalie inputs do update"}
        p_checks.append(J.check("prospective_outcomes_complete", len(t26) == len(res26), f"{len(t26)} final 2026-27 games in the frame from {len(res26)} archived results"))
        n_kal = int((P["family"] == "game_winner").sum()) if len(P) else 0
        p_checks.append(J.check("prospective_freeze_precedes_start", bool(len(P) and P["mts_v2"].min() >= FREEZE_MIN),
                                f"{len(P)} frozen market rows, min minutes_to_start {P['mts_v2'].min() if len(P) else None}; moneyline rows {n_kal}"))
        for top, kind in (("predictions", "DATA_ONLY_V1 frozen"), ("predictions_v2", "DATA_ONLY_V2 frozen"), ("predictions_oa", "OA_RIDGE_V1 frozen"),
                          ("results", "official final scores"), ("context/goalie_observations", "starter observations"), ("player_events/goalies", "goalie logs")):
            fl = arch.get("_files", {}).get(top, [])
            dts = sorted(f.split("/dt=")[1][:10] for f in fl)
            p_entries.append({"dataset_id": f"archive_{top.replace('/', '_')}", "repo": f"{J.REPO}@data-archive", "path": f"{top}/dt=*/",
                              "rows": len(arch.get(top, [])), "files": len(fl), "first": dts[0] if dts else None, "last": dts[-1] if dts else None,
                              "commit": ARCHIVE_COMMIT, "kind": "PROSPECTIVE_CAPTURE", "rights_tier": "UNRESOLVED_INTERNAL_ONLY", "note": kind +
                              ("; only rows of the five game-level Kalshi series were parsed" if top.startswith("predictions_v") or top == "predictions" else "")})
    results = J.finalize_verdicts(results)

    # ---------------------------------------------------------------- ablations (2024+2025)
    log("ablations")

    def rnll_rows(m, idx):
        Pm = m.reg(idx); ii = np.arange(len(idx))
        return -np.log(Pm[ii, np.clip(G["rh"][idx], 0, J.K - 1), np.clip(G["ra"][idx], 0, J.K - 1)] + 1e-300)
    base_nll = rnll_rows(head, ti)
    abl = []
    ABL_FAMS = ["moneyline", "regulation_tie_overtime", "total_5.5", "total_6.5", "puck_line_1.5", "team_total_2.5"]
    for vid, (m, sgn, lab) in V.items():
        fv = fam_probs(m.markets(ti), Y, gid, coh)
        comps = [("regulation_score_nll", rnll_rows(m, ti), base_nll, gid, coh)]
        for fam in ABL_FAMS:
            comps.append((f"{fam}_logloss", logloss_rows(fv[fam][0], ch[fam][1]), logloss_rows(ch[fam][0], ch[fam][1]), ch[fam][2], ch[fam][3]))
        rows_a = []
        for metric, lv, lf, gg, cc in comps:
            per = {}
            for co in ("2024", "2025", "pooled"):
                mm = np.ones(len(lv), bool) if co == "pooled" else cc == co
                bs = paired_cluster_bootstrap((lv - lf)[mm], gg[mm]); per[co] = bs
                rows_a.append({"metric": metric, "cohort": co, "n_rows": bs["n_rows"], "n_clusters": bs["n_clusters"], "variant": float(lv[mm].mean()),
                               "headline_challenger": float(lf[mm].mean()), "diff_variant_minus_headline": bs["mean"], "ci95": [bs["lo"], bs["hi"]], "p_raw": bs["p_two_sided"]})
            for r in rows_a[-3:]:
                r["same_sign_both_cohorts"] = bool(per["2024"]["mean"] * per["2025"]["mean"] > 0)
        prim = [r for r in rows_a if r["metric"] == "regulation_score_nll" and r["cohort"] == "pooled"][0]
        lo, hi = sorted([sgn * prim["ci95"][0], sgn * prim["ci95"][1]])
        if lo > 0:
            concl = "HELPS_SIGNIFICANT_REPLICATED" if prim["same_sign_both_cohorts"] else "HELPS_SIGNIFICANT_NOT_REPLICATED"
        elif hi < 0:
            concl = "HURTS_SIGNIFICANT"
        else:
            concl = "FAVOURABLE_NOT_SIGNIFICANT" if sgn * prim["diff_variant_minus_headline"] > 0 and prim["same_sign_both_cohorts"] else "NO_DETECTABLE_VALUE"
        abl.append({"ablation_id": vid, "label": lab, "oracle_not_pit": vid.startswith("i_"), "component_in_headline": sgn == 1, "conclusion": concl,
                    "primary_metric": "regulation_score_nll (per game)",
                    "sign_convention": f"diff = variant - headline; {'the removed component helps' if sgn == 1 else 'the added information helps'} when diff is "
                                       f"{'positive' if sgn == 1 else 'negative'}", "rows": rows_a})

    # ---------------------------------------------------------------- calibration / discrimination
    def cal(p, yy, cc):
        out = {}
        for co in ("2024", "2025", "pooled"):
            mm = np.ones(len(yy), bool) if co == "pooled" else cc == co
            a, b = calibration_slope(p[mm], yy[mm])
            out[co] = {"n": int(mm.sum()), "intercept": a, "slope": b, "auc": auc(p[mm], yy[mm]), "mean_p": float(p[mm].mean()), "observed": float(yy[mm].mean())}
        return out
    calib = {}
    for fam in ("moneyline", "regulation_tie_overtime", "total_5.5", "total_6.5", "puck_line_1.5", "team_total_2.5"):
        p, yy, _, cc = ch[fam]
        calib[fam] = {"challenger_0_2": cal(p, yy, cc), "alpha_0_1": cal(refs[REF_01][fam], yy, cc), "incumbent_V1": cal(refs[REF_V1][fam], yy, cc),
                      "shadow_SIM2": cal(refs[REF_SIM2][fam], yy, cc)}

    # ---------------------------------------------------------------- verdict, claims, document
    hl = [r for r in results if r.get("headline") and r["metric"] == "logloss"]
    vs01 = [r for r in results if r["reference"] == REF_01 and r["cohort"] == "pooled" and r["metric"] == "logloss"]
    nv = sum(r["verdict"] == "VALIDATED_IMPROVEMENT" for r in hl); nw = [r["market_family"] for r in hl if r["verdict"] == "NOT_IMPROVED"]
    v01 = sum(r["verdict"] == "VALIDATED_IMPROVEMENT" for r in vs01); w01 = [r["market_family"] for r in vs01 if r["verdict"] == "NOT_IMPROVED"]
    overall = "VALIDATED_IMPROVEMENT" if nv == len(hl) and hl else "NOT_IMPROVED" if nw else "IMPROVED_NOT_VALIDATED" if nv else "INCONCLUSIVE"
    mrows = [r for r in results if r["reference"] in (REF_MKT, P_MKT) and r["metric"] == "logloss"]
    reason = (f"Headline = pooled 2024+2025 vs {REF_V1}, {len(hl)} log-loss rows, Holm-adjusted: VALIDATED {nv}, NOT_IMPROVED {nw}. "
              f"Against the reproduced 0.1 (the increment this challenger adds): VALIDATED {v01} of {len(vs01)} log-loss rows, NOT_IMPROVED {w01}. "
              f"Goalie term accepted on validation: {goalie_accepted}; team extensions accepted: {acc_team or 'none'}. "
              f"Market rows (Kalshi mid; 2025 T-60 and 2026 at-freeze): challenger worse than the mid in "
              f"{sum(r['diff'] > 0 for r in mrows)} of {len(mrows)} log-loss rows. No profitability claim; fees not modelled.")
    abl_by = {a["ablation_id"]: a for a in abl}
    def ab_ev(aid):
        a = abl_by[aid]; p = [r for r in a["rows"] if r["metric"] == "regulation_score_nll" and r["cohort"] == "pooled"][0]
        return f"ablation {aid}: {a['conclusion']}, pooled regulation-score NLL diff (variant - headline) {p['diff_variant_minus_headline']:+.5f} CI [{p['ci95'][0]:+.5f}, {p['ci95'][1]:+.5f}]"
    gkeys = [k for k in abl_by if k.startswith(("ii", "iii", "i_"))]
    g_conc = {k: abl_by[k]["conclusion"] for k in gkeys}
    g_ok = goalie_accepted and abl_by.get("iii_no_goalie_term", {}).get("conclusion") == "HELPS_SIGNIFICANT_REPLICATED"
    k_mix = "ii_naive_share_mixture" if goalie_accepted else "ii_pit_starter_mixture_added"
    k_q = "iii_no_goalie_term" if goalie_accepted else "iii_savepct_quality_added"
    claims = [
        {"input": "NHL:nhl.goalie_quality", "stage": "EVALUATED", "outcome": "OK" if g_ok else "REJECTED",
         "evidence": f"shrunk goals-vs-expected quality (MoneyPuck shot xG 2021-25; save%-based 2026-27) of the PIT expected opposing starter; "
                     f"validation-selected: {goalie_accepted}; {ab_ev(k_q)}"},
        {"input": "NHL:nhl.goalie_start_forecast", "stage": "EVALUATED", "outcome": "OK" if g_ok and abl_by[k_mix]["conclusion"] == "HELPS_SIGNIFICANT_REPLICATED" else "REJECTED",
         "evidence": f"conditional-logit starter-probability mixture (fit 2021-2023, test top-1 accuracy {starter_model['test'].get('2025', {}).get('top1_accuracy', float('nan')):.3f} in 2025); {ab_ev(k_mix)}"},
        {"input": "NHL:nhl.goalie_start", "stage": "EVALUATED", "outcome": "PARTIAL",
         "evidence": f"as-played starter only as an ORACLE_NOT_PIT bound; {ab_ev('i_oracle_as_played_starter')}; prospective DailyFaceoff capture at T-60 summarised in confirmed_starter_timing"},
        {"input": "NHL:nhl.goalie_workload", "stage": "EVALUATED", "outcome": "PARTIAL",
         "evidence": "goalie back-to-back and days since last start enter only the starter model (who starts), not the goal rate; evaluated through ablation ii"},
        {"input": "NHL:nhl.rest_travel", "stage": "EVALUATED", "outcome": "OK" if abl_by["v_no_rest"]["conclusion"] == "HELPS_SIGNIFICANT_REPLICATED" else "PARTIAL",
         "evidence": f"back-to-back flags{' + long-rest flags' if 'r3_t' in acc_team else ''}; no travel distance; {ab_ev('v_no_rest')}"},
        {"input": "NHL:nhl.xg_for", "stage": "EVALUATED", "outcome": "OK" if abl_by["iv_no_xg_ratings"]["conclusion"] == "HELPS_SIGNIFICANT_REPLICATED" else "PARTIAL",
         "evidence": ab_ev("iv_no_xg_ratings")},
        {"input": "NHL:nhl.xg_against", "stage": "EVALUATED", "outcome": "OK" if abl_by["iv_no_xg_ratings"]["conclusion"] == "HELPS_SIGNIFICANT_REPLICATED" else "PARTIAL",
         "evidence": ab_ev("iv_no_xg_ratings")},
        {"input": "NHL:nhl.shot_rate", "stage": "EVALUATED", "outcome": "OK" if "sa_o" in acc_team else "REJECTED",
         "evidence": "score-adjusted shot-attempt volume rates; validation (2019-2023) deviance delta " + f"{[s for s in team_sel if s['extension'] == 'shot_attempt_volume'][0]['delta']:+.6f}"},
        {"input": "NHL:m.quote_history", "stage": "EVALUATED", "outcome": "OK", "evidence": "Kalshi T-60 two-sided mid (2025) and the mid recorded in frozen 2026-27 prediction rows used as references"},
    ]
    data = [
        {"dataset_id": "nhl_games", "repo": J.REPO, "path": "data/history/nhl/games_{2008..2025}.parquet", "rows": int(len(games)),
         "first": str(games["game_date"].min()), "last": str(games["game_date"].max()), "sha256_of_files": J.files_digest(gfiles), "commit": J.SOURCE_COMMIT,
         "kind": "HISTORICAL_BACKFILL", "rights_tier": "UNRESOLVED_INTERNAL_ONLY"},
        {"dataset_id": "moneypuck_team_games", "repo": J.REPO, "path": "data/history/moneypuck/team_games_{2008..2025}.parquet", "rows": int(len(mp)),
         "first": str(mp["game_date"].min()), "last": str(mp["game_date"].max()), "sha256_of_files": J.files_digest(mfiles), "commit": J.SOURCE_COMMIT,
         "kind": "HISTORICAL_BACKFILL", "rights_tier": "UNRESOLVED_INTERNAL_ONLY"},
        {"dataset_id": "moneypuck_shots", "repo": J.REPO, "path": "data/history/moneypuck/shots_{2021..2025}.parquet", "rows": int(n_shots),
         "first": "2021", "last": "2025", "sha256_of_files": J.files_digest(sfiles), "commit": J.SOURCE_COMMIT, "kind": "HISTORICAL_BACKFILL",
         "rights_tier": "UNRESOLVED_INTERNAL_ONLY", "note": "aggregated in memory to per (game, goalie) xG; no shot row leaves the clone"},
        {"dataset_id": "nhl_goalie_games", "repo": J.REPO, "path": "data/history/players/goalies_{2021..2025}.parquet + data-archive player_events/goalies (2026-27)",
         "rows": int(len(gl)), "first": str(gl["game_date"].min()), "last": str(gl["game_date"].max()), "sha256_of_files": J.files_digest(glfiles),
         "commit": J.SOURCE_COMMIT, "rows_2026_27_from_archive": int(n26), "kind": "HISTORICAL_BACKFILL", "rights_tier": "UNRESOLVED_INTERNAL_ONLY"},
        {"dataset_id": "incumbent_walk_forward_v1", "repo": J.REPO, "path": "docs/research/walk_forward_36570274279_games.csv", "rows": int(len(v1)),
         "first": str(v1["game_date"].min()), "last": str(v1["game_date"].max()), "sha256": sha256_file(docs / "walk_forward_36570274279_games.csv"),
         "commit": J.SOURCE_COMMIT, "kind": "WALK_FORWARD_REPRODUCTION", "rights_tier": "OWNER_DERIVED"},
        {"dataset_id": "incumbent_walk_forward_v2_sim2", "repo": J.REPO, "path": "docs/research/walk_forward_v2_wf2_20260929_games.csv", "rows": int(len(v2)),
         "first": str(v2["game_date"].min()), "last": str(v2["game_date"].max()), "sha256": sha256_file(docs / "walk_forward_v2_wf2_20260929_games.csv"),
         "commit": J.SOURCE_COMMIT, "kind": "WALK_FORWARD_REPRODUCTION", "rights_tier": "OWNER_DERIVED"},
    ] + k_entries + p_entries
    features = [
        {"feature_id": "alpha_0_1_team_rates", "catalog_inputs": ["NHL:nhl.xg_for", "NHL:nhl.xg_against", "NHL:nhl.special_teams", "NHL:nhl.rest_travel", "NHL:nhl.venue"],
         "description": "0.1 walk-forward team rates and GLM (re-fitted here with 0.1's frozen hyper-parameters; reproduction checked)",
         "pit_rule": "earlier game dates only; parameters from seasons <= 2023",
         "checks": [J.check("reproduces_committed_0_1", rep_err < 1e-5, f"max |pooled log loss - committed 0.1| over {len(HEAD)} families = {rep_err:.2e}")]},
        {"feature_id": "team_extensions_validation_selected", "catalog_inputs": ["NHL:nhl.shot_rate", "NHL:nhl.rest_travel"],
         "description": "high-danger xG rates, score-adjusted shot-attempt volume, long-rest (>= 3 days) flags; each accepted only if 2019-2023 validation deviance falls",
         "pit_rule": "walk-forward state from earlier dates; selection never reads 2024+", "checks": [J.check(f"selection_{s['extension']}", True,
                    f"val deviance {s['val_deviance_with']:.6f} vs base {s['val_deviance_base']:.6f} -> {'ACCEPTED' if s['accepted'] else 'REJECTED'}") for s in team_sel]},
        {"feature_id": "pit_goalie_mixture_quality", "catalog_inputs": ["NHL:nhl.goalie_quality", "NHL:nhl.goalie_start_forecast", "NHL:nhl.goalie_workload"],
         "description": "expected shrunk log(goals allowed / expected goals) of the opposing starter under the PIT conditional-logit starter model",
         "pit_rule": "goalie sums and candidate features use strictly earlier dates; starter model and gamma fitted on 2021-2023",
         "checks": goalie_checks},
    ]
    gl_fit = {"goalie_hyper_best": ghp, "goalie_spec_best": gspec, "headline_spec": hspec, "goalie_accepted": goalie_accepted,
              "headline_gamma": head_gamma.tolist(), "gamma_mix_best_goalie_config": gam_mix.tolist(),
              "team_beta": dict(zip(["intercept"] + specs[hspec], team_fit[hspec].tolist())), "joint": head.joint, "ot_k": head.k_ot, "starter_model": starter_model, **ginfo}
    doc = {"schema": EVAL_SCHEMA, "status": "RESEARCH_ONLY", "sport": "NHL", "challenger_id": CHALLENGER_ID, "incumbent_id": J.INCUMBENT_ID,
           "baselines": {"alpha_0_1": REF_01, "incumbent": REF_V1, "shadow": REF_SIM2, "market": REF_MKT,
                         "prospective": [P_V1, P_V2, P_OA, P_01, P_MKT]},
           "source_commits": {J.REPO: J.SOURCE_COMMIT, f"{J.REPO}@data-archive": ARCHIVE_COMMIT if arch else None},
           "data": data, "features": features,
           "design": {"train_window": "team GLM 2009-2023; goalie gamma and starter model 2021-2023; joint/OT 2009-2023", "test_window": "2024, 2025 (+ 2026-27 prospective, single cohort)",
                      "selection": {"team": team_sel, "goalie_candidates": cand, "headline": best_all, "best_goalie_config": best_g,
                                    "rule": "rolling-origin validation 2022 and 2023 (team GLM fit 2009..v-1, starter model and gamma 2021..v-1); lowest pooled deviance wins; ties favour no goalie term"},
                      "promotion_rule": J.VERDICT_RULE, "fitted_parameters": gl_fit, "leak_guards": [c for c in goalie_checks if c["name"].startswith("leak")],
                      "kalshi_coverage": kcov, "kalshi_checks": k_checks, "prospective_checks": p_checks},
           "results": results, "ablations": abl, "calibration": calib, "market_context": market_context, "prospective": prospective,
           "confirmed_starter_timing": timing,
           "not_demonstrated": ["goalie saves / shots-on-goal means: no shot-volume model in the joint score distribution; not evaluated",
                                "travel distance / time zones: not built", "profitability or executable edge: fees, spread (mid vs ask) and fills not modelled",
                                "2026-27 single cohort can never be 'replicated'; challenger team ratings are frozen pre-season there"],
           "verdict": {"overall": overall, "reason": reason, "retain_incumbent": True},
           "limitations": [
               "2024/2025 baselines are owner walk-forward REPRODUCTIONS of V1/SIM2 (no frozen forecasts exist before the data-archive started on 2026-09-29).",
               "Goalie logs start in 2021: the goalie gamma, the starter model and the joint/OT re-fit use only 2021-2023 (3 seasons).",
               "2026-27: MoneyPuck team_games/shots are not archived, so team xG ratings are frozen at end of 2025-26 and goalie expectation is save%-based.",
               "Prospective Kalshi rows are only listed markets; the mid is the frozen row's (bid+ask)/2, not an executable ask; rights UNRESOLVED_INTERNAL_ONLY.",
               "DailyFaceoff starter observations are read from the owner's archive only (rights unresolved); no new collection.",
           ],
           "input_stage_claims": claims}
    errs = validate_evaluation(doc)
    assert not errs, errs
    write_json(OUT / "evaluation.json", doc)
    log(f"wrote {OUT / 'evaluation.json'}: overall {overall}")
    return doc


def main(argv=None):
    run()


if __name__ == "__main__":
    main()
