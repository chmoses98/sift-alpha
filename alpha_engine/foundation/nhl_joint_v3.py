"""Operation Data Foundation, NHL: challenger ``alpha-nhl-joint-0.3`` = ``alpha-nhl-joint-0.2`` + in-season 2026-27 team inputs
reconstructed from the owner's ``data-archive`` branch + validation-selected score-distribution / team-rate extensions.

RESEARCH_ONLY. 0.1 (``nhl_joint``) and 0.2 (``nhl_joint_v2``, ``nhl_goalie``) are reused by import; nothing in them is changed.

What 0.3 changes, each change targeting a weakness with evidence behind it:

1. **Stale 2026-27 ratings.** 0.2 froze team ratings at the end of 2025-26 because it did not find 2026-27 team games. They ARE
   archived: ``context/team_games`` (MoneyPuck all-situations rows) and ``context/team_games_st`` (5on5 / 5on4 / 4on5) hold every
   final 2026-27 game, each first captured hours after the game. 0.3 uses the FIRST captured version of each row and only
   for games whose T-60 freeze is later than that capture (``nhl_inseason.availability_masks``).
2. **Independent in-season xG.** A shot-level xG model on the official play-by-play shot events (``player_events/shots``, same
   schema as ``data/history/players/shots_*``), fitted on 2021-2023, validated against MoneyPuck team-game xG on 2024, 2025
   and 2026-27. It is an evaluated ARM and a cross-check of the archived MoneyPuck rows, not the headline input.
3. **Score distribution.** The 0.1 joint has one weight for ties and one for one-goal margins. Candidates, each accepted only if
   the 2019-2023 validation NLL falls (fit <= 2018): a two-goal-margin weight (empty-net conversion of one-goal games), a tie
   weight that depends on the expected total, a tie weight that depends on the mismatch, and a home intercept in overtime.
4. **Team rates.** Candidates on validation deviance: a trailing league home-ice term and slow (long half-life) 5v5 ratings.

Market-implied quantities are used ONLY as evaluation references and in the loss diagnosis, never as a model input.

``python -m alpha_engine.foundation.nhl_joint_v3`` regenerates the evaluation deterministically.
"""
from __future__ import annotations

import gzip
import io
import json
import math
import re
import subprocess
import tarfile

import numpy as np

from . import nhl_goalie as NG
from . import nhl_inseason as IS
from . import nhl_joint as J
from . import nhl_joint_v2 as V
from .contract import (EVAL_SCHEMA, OPS, brier_rows, calibration_slope, logloss_rows, paired_cluster_bootstrap, repos_dir,
                       sha256_file, validate_evaluation, write_json)

CHALLENGER_ID = "alpha-nhl-joint-0.3"
OUT = OPS / "NHL" / CHALLENGER_ID
ARCHIVE_COMMIT = "3dca211d06e665252a0e5e15e363c540ee8f0542"  # NHL-edge-finder data-archive tip read on 2026-11-14 (descendant of 0.2's pin)
NEW_PATHS = ["context/team_games", "context/team_games_st", "player_events/shots", "player_events/team_states"]
HP = dict(V.HP)
HL_SLOW = 110.0
XG_FIT = (2021, 2023)
REF_02, REF_01, REF_V1, REF_SIM2, REF_MKT = "challenger:alpha-nhl-joint-0.2", V.REF_01, V.REF_V1, V.REF_SIM2, V.REF_MKT
P_V1, P_V2, P_OA, P_MKT = V.P_V1, V.P_V2, V.P_OA, V.P_MKT
P_02 = "prospective:alpha-nhl-joint-0.2_frozen_ratings"
HEAD = V.HEAD
EXTRA = ["highDangerxGoalsFor", "highDangerxGoalsAgainst", "scoreAdjustedShotsAttemptsFor", "scoreAdjustedShotsAttemptsAgainst"]
ALL_COLS = ["iceTime", "xGoalsFor", "xGoalsAgainst", "goalsFor", "goalsAgainst", "scoreVenueAdjustedxGoalsFor", "scoreVenueAdjustedxGoalsAgainst",
            "flurryScoreVenueAdjustedxGoalsFor", "flurryScoreVenueAdjustedxGoalsAgainst"] + EXTRA
JOINT_KEYS = ["u_c3", "theta_tie", "theta_one_goal", "delta", "theta_two_goal", "tie_slope_total", "tie_slope_mismatch", "log_kappa"]
JOINT_CANDIDATES = {"two_goal_margin_weight": ["theta_two_goal"], "tie_weight_by_expected_total": ["tie_slope_total"],
                    "tie_weight_by_mismatch": ["tie_slope_mismatch"], "mismatch_scale": ["log_kappa"]}
POST_HOC_CANDIDATES = ("mismatch_scale",)  # added after the first read of the test cohorts (see design.selection.post_hoc_note)
LOG_TOT_REF = math.log(5.6)


def check(name, passed, detail, basis="COMPUTED"):
    """A data check. ``basis`` = COMPUTED (``passed`` is derived from data in this run) or ATTESTED (a design statement)."""
    assert basis in ("COMPUTED", "ATTESTED")
    return {"name": name, "passed": bool(passed), "detail": str(detail), "basis": basis}


# ====================================================================== score distribution (extends the 0.1 joint)
def joint_pmf3(lam_h, lam_a, jp, k=J.K):
    """0.1's bivariate-Poisson regulation pmf with margin weights: ties exp(theta_tie + tie_slope_total * (log(lh+la) - log 5.6)
    + tie_slope_mismatch * |log(lh/la)|), one-goal margins exp(theta_one_goal), two-goal margins exp(theta_two_goal). Any symmetric
    margin weight that favours large margins also moves win probability toward the favourite, so ``log_kappa`` lets the likelihood
    rescale the log rate ratio (kappa < 1 = less extreme) instead of leaving the distortion in the market probabilities."""
    lh = np.asarray(lam_h, float); la = np.asarray(lam_a, float)
    if jp.get("log_kappa", 0.0) != 0.0:  # mismatch scale: the two rates keep their geometric mean, their log ratio is multiplied by kappa
        gm = np.sqrt(lh * la); s = 0.5 * math.exp(jp["log_kappa"]) * np.log(lh / la); lh, la = gm * np.exp(s), gm * np.exp(-s)
    P = J.joint_reg_pmf(lh, la, jp.get("c3", 0.0), 0.0, 0.0, jp.get("delta", 0.0), k)
    d = np.abs(np.arange(k)[:, None] - np.arange(k)[None, :])
    ld = np.log(lh * math.exp(jp.get("delta", 0.0)) + la * math.exp(jp.get("delta", 0.0)))
    w0 = np.exp(jp.get("theta_tie", 0.0) + jp.get("tie_slope_total", 0.0) * (ld - LOG_TOT_REF)
                + jp.get("tie_slope_mismatch", 0.0) * np.abs(np.log(lh / la)))
    W = np.where(d[None] == 0, w0[:, None, None], np.where(d == 1, math.exp(jp.get("theta_one_goal", 0.0)),
                                                         np.where(d == 2, math.exp(jp.get("theta_two_goal", 0.0)), 1.0))[None])
    P = P * W
    return P / P.sum((1, 2), keepdims=True)


def fit_joint3(lam_h, lam_a, rh, ra, free=()):
    """ML fit of the base four parameters plus the ``free`` extras (others fixed at 0)."""
    rh = np.clip(rh, 0, J.K - 1); ra = np.clip(ra, 0, J.K - 1); idx = np.arange(len(rh))
    keys = JOINT_KEYS[:4] + [k for k in JOINT_KEYS[4:] if k in free]

    def unpack(x):
        jp = dict(zip(keys, x)); jp["c3"] = jp.pop("u_c3") ** 2
        return jp

    def nll(x):
        return float(-np.mean(np.log(joint_pmf3(lam_h, lam_a, unpack(x))[idx, rh, ra] + 1e-300)))
    x, v = J.nelder_mead(nll, [0.2, 0.0, 0.0, 0.0] + [0.0] * (len(keys) - 4), step=0.1, iters=600, tol=1e-9)
    jp = {k: float(val) for k, val in unpack(x).items()}; jp["train_nll"] = float(v)
    return jp


def reg_nll(lam_h, lam_a, rh, ra, jp):
    P = joint_pmf3(lam_h, lam_a, jp); i = np.arange(len(rh))
    return -np.log(P[i, np.clip(rh, 0, J.K - 1), np.clip(ra, 0, J.K - 1)] + 1e-300)


def ot_home_prob3(lam_h, lam_a, k_ot, h0=0.0):
    return np.clip(0.5 + h0 + k_ot * np.log(np.asarray(lam_h, float) / np.asarray(lam_a, float)), 0.02, 0.98)


def fit_ot3(lam_h, lam_a, home_won, with_h0):
    y = np.asarray(home_won, float); best = (1e9, 0.0, 0.0)
    for h0 in (np.linspace(-0.05, 0.08, 53) if with_h0 else [0.0]):
        for k in np.linspace(-0.5, 1.5, 201):
            v = float(np.mean(logloss_rows(ot_home_prob3(lam_h, lam_a, k, h0), y)))
            if v < best[0]:
                best = (v, float(k), float(h0))
    return best[1], best[2], best[0]


class Model3:
    """Frozen 0.3 parameters and prediction for any set of game rows (rows of the frame are (away, home) pairs)."""

    def __init__(self, log_lam, jp, k_ot, h0=0.0):
        self.jp, self.k_ot, self.h0 = jp, k_ot, h0
        lam = np.exp(log_lam); self.lam_a, self.lam_h = lam[0::2], lam[1::2]

    def reg(self, m):
        return joint_pmf3(self.lam_h[m], self.lam_a[m], self.jp)

    def markets(self, m):
        return J.markets_from(self.reg(m), ot_home_prob3(self.lam_h[m], self.lam_a[m], self.k_ot, self.h0))


# ====================================================================== features (0.1 + 0.2 terms, availability-aware)
def features_v3(tg, hp, state_ok=None, league_ok=None, hl_slow=HL_SLOW):
    """0.1 ``make_features`` + 0.2 ``extra_team_features`` recomputed with point-in-time availability masks, plus the 0.3
    candidates (slow 5v5 ratings, trailing league home-ice edge). With both masks all-True the 0.1/0.2 features are identical
    to the originals (checked in the pipeline)."""
    n = len(tg); so = np.ones(n, bool) if state_ok is None else state_ok; lo = np.ones(n, bool) if league_ok is None else league_ok
    team, season, day = tg["team"].values, tg["season"].values, tg["day"].values
    X = J.stat_matrix(tg, hp["xg"]); m = X.shape[1]
    Xs = X.copy(); Xs[~so] = np.nan; Xl = X.copy(); Xl[~lo] = np.nan
    d = np.full(m, 0.5 ** (1.0 / hp["hl"])); d[list(J.FIN_COLS)] = 0.5 ** (1.0 / hp["hl_fin"])
    S = J.walk_forward_state(team, season, Xs, d, np.full(m, hp["carry"]))
    L = J.trailing_league(day, Xl); Lreg = J.trailing_league(day, tg[["rg"]].values.astype(float))[:, 0]
    c = {nm: i for i, nm in enumerate(J.STAT_COLS)}; kp, mf = hp["k_prior"], hp["m_fin"]
    s = lambda nm: S[:, c[nm]]; l = lambda nm: L[:, c[nm]]
    rate = lambda num, den: np.log(((s(num) + kp * l(num)) / (s(den) + kp * l(den))) / (l(num) / l(den)))
    r_f, r_a = l("gf") / l("xff"), l("ga") / l("xaf")
    own = {"off5": rate("xf5", "t5"), "def5": rate("xa5", "t5"), "pp": rate("xfpp", "n"), "pk": rate("xapk", "n"),
           "fin_o": np.log((s("gf") + mf * r_f) / (r_f * (s("xff") + mf))), "fin_d": np.log((s("ga") + mf * r_a) / (r_a * (s("xaf") + mf)))}
    opp = np.arange(n) ^ 1; b2b = tg["b2b"].values.astype(float)
    f = {"home": tg["home"].values.astype(float), "off5": own["off5"], "def5": own["def5"][opp], "pp": own["pp"], "pk": own["pk"][opp],
         "fin_o": own["fin_o"], "fin_d": own["fin_d"][opp], "b2b_t": b2b, "b2b_o": b2b[opp]}
    # 0.2 extras
    g = lambda col: tg[col].values.astype(float) if col in tg else np.full(n, np.nan)
    E = np.column_stack([g("iceTime_all")] + [g(f"{col}_all") for col in EXTRA]); E[np.isnan(E).any(1)] = np.nan
    Es = E.copy(); Es[~so] = np.nan; El = E.copy(); El[~lo] = np.nan
    SE = J.walk_forward_state(team, season, Es, np.full(5, 0.5 ** (1 / hp["hl"])), np.full(5, hp["carry"])); LE = J.trailing_league(day, El)
    er = lambda j: np.log(((SE[:, j] + kp * LE[:, j]) / (SE[:, 0] + kp * LE[:, 0])) / (LE[:, j] / LE[:, 0]))
    r3 = (tg["rest_days"].fillna(0).values >= 3).astype(float)
    f.update({"hd_o": er(1), "hd_d": er(2)[opp], "sa_o": er(3), "sa_d": er(4)[opp], "r3_t": r3, "r3_o": r3[opp]})
    # 0.3 candidates
    S2 = J.walk_forward_state(team, season, Xs[:, :4], np.full(4, 0.5 ** (1.0 / hl_slow)), np.full(4, hp["carry"]))
    slow = lambda j: np.log(((S2[:, j] + kp * L[:, j]) / (S2[:, 1] + kp * L[:, 1])) / (L[:, j] / L[:, 1]))
    f["off5_slow"] = slow(2); f["def5_slow"] = slow(3)[opp]
    h = tg["home"].values.astype(float); rg = tg["rg"].values.astype(float)
    LH = J.trailing_league(day, np.column_stack([rg * h, h, rg * (1 - h), 1 - h]))
    edge = np.log((LH[:, 0] / LH[:, 1]) / (LH[:, 2] / LH[:, 3]))
    f["home_trend"] = (h - 0.5) * edge
    return {"f": f, "offset": np.log(Lreg), "games_w": S[:, 0], "league_home_edge": edge}


# ====================================================================== archive (pinned commit, read in memory)
def _stamp(name):
    return re.search(r"_(\d{8}T\d{6}Z)_", name).group(1)


def load_archive3(commit=ARCHIVE_COMMIT):
    """One in-memory ``git archive`` of the pinned data-archive commit. Returns (arch, note): ``arch`` has the 0.2 keys (same
    parsing as ``nhl_joint_v2.load_archive``) plus ``_mp`` / ``_mp_st`` = {(game_id, team_code, situation): (first capture stamp,
    row)} for season 2026, ``_mp_last`` (latest captured xGoalsFor per key, to count revisions) and ``_shots`` / ``_states`` =
    {game_id: (first capture stamp, rows)}."""
    clone = repos_dir() / "NHL-edge-finder"
    try:
        blob = subprocess.run(["git", "-C", str(clone), "archive", commit] + V.ARCHIVE_PATHS + NEW_PATHS, capture_output=True, check=True, timeout=900).stdout
    except Exception as e:  # noqa: BLE001
        return None, f"data-archive commit {commit[:12]} not readable from the clone ({type(e).__name__}); 2026-27 sections skipped"
    out = {"_files": {}, "_mp": {}, "_mp_st": {}, "_mp_last": {}, "_shots": {}, "_states": {}, "_inventory": {}}
    names = subprocess.run(["git", "-C", str(clone), "ls-tree", "-r", "--name-only", commit], capture_output=True, check=True, timeout=300).stdout.decode().splitlines()
    for nm in names:   # file counts of the whole pinned tree, by dataset directory (context/x, player_events/x, kalshi/x, else top level)
        parts = nm.split("/")
        if len(parts) > 1:
            key = "/".join(parts[:2]) if parts[0] in ("context", "player_events", "kalshi") else parts[0]
            out["_inventory"][key] = out["_inventory"].get(key, 0) + 1
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        for m in sorted(tf.getmembers(), key=lambda m: m.name):
            if not m.isfile() or not m.name.endswith(".jsonl.gz"):
                continue
            top = m.name.split("/dt=")[0]; out["_files"].setdefault(top, []).append(m.name)
            raw = gzip.decompress(tf.extractfile(m).read()).decode()
            if top in ("context/team_games", "context/team_games_st"):
                dst = out["_mp"] if top == "context/team_games" else out["_mp_st"]; ts = _stamp(m.name)
                for l in raw.splitlines():
                    if '"season":2026' not in l:
                        continue
                    r = json.loads(l); k = (int(r["gameId"]), str(r["team"]), str(r["situation"]))
                    if k not in dst or ts < dst[k][0]:
                        dst[k] = (ts, r)
                    kk = (top, k)
                    if kk not in out["_mp_last"] or ts >= out["_mp_last"][kk][0]:
                        out["_mp_last"][kk] = (ts, r.get("xGoalsFor"))
            elif top in ("player_events/shots", "player_events/team_states"):
                dst = out["_shots"] if top.endswith("shots") else out["_states"]; ts = _stamp(m.name); by = {}
                for l in raw.splitlines():
                    if l.strip():
                        r = json.loads(l); by.setdefault(int(r["game_id"]), []).append(r)
                for g, rows in by.items():
                    if g not in dst or ts < dst[g][0]:
                        dst[g] = (ts, rows)
            else:
                if top in ("predictions", "predictions_v2"):
                    lines = [l for l in raw.splitlines() if any(s in l for s in V.GAME_SERIES)]
                else:
                    lines = [l for l in raw.splitlines() if l.strip()]
                out.setdefault(top, []).extend(json.loads(l) for l in lines)
    return out, f"data-archive@{commit[:12]} read in memory"


def moneypuck_2026(arch, sch):
    """MoneyPuck-format rows (the columns ``nhl_joint.build_team_games`` pivots) for 2026-27 from the FIRST archived capture of
    each team-game. 5on5 score/venue/flurry-adjusted xG is not archived per situation: it is approximated as raw 5on5 xG times the
    team-game's all-situations adjusted/raw ratio (the approximation is validated on 2021-2025 in the pipeline).
    Returns (DataFrame, avail {(game_id, home): capture stamp}, info)."""
    import pandas as pd
    rows, avail, n_code = [], {}, [0, 0]
    norm = lambda s: str(s).replace(".", "").upper()
    for (g, team, sit), (ts, r) in sorted(arch["_mp"].items()):
        s = sch.get(str(g))
        if s is None or sit != "all":
            continue
        home = str(r["home_or_away"]).upper() == "HOME"
        ab = s["home_abbrev"] if home else s["away_abbrev"]
        n_code[1] += 1; n_code[0] += int(J.KALSHI_ALIAS.get(norm(team), norm(team)) == ab or norm(team) == ab)
        st = {sit2: arch["_mp_st"].get((g, team, sit2)) for sit2 in ("5on5", "5on4", "4on5")}
        if any(v is None for v in st.values()):
            continue
        base = {"season": 2026, "game_id": g, "game_date": s["game_date_et"], "game_type": 2, "home": home,
                "team_id": int(s["home_team_id"] if home else s["away_team_id"]), "opp_team_id": int(s["away_team_id"] if home else s["home_team_id"])}
        rows.append({**base, "situation": "all", **{c: float(r[c]) for c in ALL_COLS}})
        fa = lambda side, adj: float(r[f"{adj}xGoals{side}"]) / max(float(r[f"xGoals{side}"]), 1e-9)
        for sit2, (ts2, q) in st.items():
            row = {**base, "situation": sit2, "iceTime": float(q["iceTime"]), "xGoalsFor": float(q["xGoalsFor"]), "xGoalsAgainst": float(q["xGoalsAgainst"]),
                   "goalsFor": float(q["goalsFor"]), "goalsAgainst": float(q["goalsAgainst"])}
            for adj, col in (("scoreVenueAdjusted", "scoreVenueAdjustedxGoals"), ("flurryScoreVenueAdjusted", "flurryScoreVenueAdjustedxGoals")):
                row[f"{col}For"] = row["xGoalsFor"] * fa("For", adj); row[f"{col}Against"] = row["xGoalsAgainst"] * fa("Against", adj)
            rows.append(row); ts = max(ts, ts2)
        avail[(g, int(home))] = ts
    return pd.DataFrame(rows), avail, {"team_code_matches_schedule": n_code[0], "team_games": n_code[1]}


def approx_adjusted_5on5(mp, seasons):
    """Return a copy of ``mp`` where, for ``seasons``, the 5on5 adjusted xG columns are replaced by the archive-equivalent
    approximation (raw 5on5 x all-situations adjusted/raw ratio) and the Pearson correlation with the true flurry/score/venue
    adjusted 5on5 xG-for on those rows."""
    a = mp[mp["situation"] == "all"].set_index(["game_id", "team_id"]); out = mp.copy()
    m = (out["situation"] == "5on5") & out["season"].isin(seasons)
    idx = list(zip(out.loc[m, "game_id"], out.loc[m, "team_id"])); true = out.loc[m, "flurryScoreVenueAdjustedxGoalsFor"].values.astype(float).copy()
    for adj in ("scoreVenueAdjustedxGoals", "flurryScoreVenueAdjustedxGoals"):
        for side in ("For", "Against"):
            ratio = (a[f"{adj}{side}"] / a[f"xGoals{side}"].clip(lower=1e-9)).reindex(idx).values
            out.loc[m, f"{adj}{side}"] = out.loc[m, f"xGoals{side}"].values * ratio
    ap = out.loc[m, "flurryScoreVenueAdjustedxGoalsFor"].values.astype(float); ok = np.isfinite(ap) & np.isfinite(true)
    return out, float(np.corrcoef(ap[ok], true[ok])[0, 1]), int(ok.sum())


# ====================================================================== own shot xG -> team games
SHOT_COLS = ["game_id", "season", "game_type", "period", "is_home", "kind", "x", "y", "shot_type", "zone", "strength", "since_prev_s"]


def load_shot_events(arch):
    """Official play-by-play shot events: history files 2021-2025 + first archived capture per 2026-27 game. Regular season,
    periods 1-4 (no shootout)."""
    import pandas as pd
    fs = sorted(f for f in (J._hist() / "players").glob("shots_*.parquet") if "2026" not in f.name)
    sh = pd.concat([pd.read_parquet(f, columns=SHOT_COLS) for f in fs], ignore_index=True); n_hist = len(sh); n26 = 0
    if arch and arch.get("_shots"):
        a = pd.DataFrame([{c: r.get(c) for c in SHOT_COLS} for g in sorted(arch["_shots"]) for r in arch["_shots"][g][1]])
        a = a[a["season"] == 2026]; n26 = len(a); sh = pd.concat([sh, a], ignore_index=True)
    sh = sh[(sh["game_type"] == 2) & (sh["period"] <= 4)].reset_index(drop=True)
    for c in ("kind", "shot_type", "zone", "strength"):
        sh[c] = sh[c].astype(object).where(sh[c].notna(), "none").astype(str)
    sh["is_home"] = sh["is_home"].astype(str).isin(["True", "1", "true"]) | (sh["is_home"] == True)  # noqa: E712
    return sh, fs, n_hist, n26


def load_team_states(arch):
    import pandas as pd
    cols = ["game_id", "season", "game_type", "is_home", "sec_ev", "sec_pp", "sec_sh", "n_seconds"]
    fs = sorted(f for f in (J._hist() / "players").glob("team_states_*.parquet") if "2026" not in f.name)
    ts = pd.concat([pd.read_parquet(f, columns=cols) for f in fs], ignore_index=True)
    if arch and arch.get("_states"):
        a = pd.DataFrame([{c: r.get(c) for c in cols} for g in sorted(arch["_states"]) for r in arch["_states"][g][1]])
        ts = pd.concat([ts, a[a["season"] == 2026]], ignore_index=True)
    ts = ts[ts["game_type"] == 2].copy(); ts["is_home"] = ts["is_home"].astype(str).isin(["True", "1", "true"])
    return ts.drop_duplicates(["game_id", "is_home"]).reset_index(drop=True), fs


def own_xg_team_games(sh, ts, model, games_all):
    """Team-game frame from own shot xG: one row per (game, is_home) with FOR/AGAINST xG by strength, TOI by state, volume."""
    import pandas as pd
    cols = {c: sh[c].values for c in ("kind", "x", "y", "zone", "shot_type", "strength", "since_prev_s")}
    xg = IS.shot_xg(cols, model)
    agg = IS.team_game_xg(sh["game_id"].values, sh["is_home"].values, sh["strength"].values, sh["kind"].values, xg)
    t = ts.set_index(["game_id", "is_home"]); rows = []
    ids = games_all.drop_duplicates("game_id").set_index("game_id")
    for (g, h), a in sorted(agg.items()):
        o = agg.get((g, 1 - h));
        if o is None or (g, bool(h)) not in t.index or g not in ids.index:
            continue
        st = t.loc[(g, bool(h))]; gi = ids.loc[g]
        rows.append({"game_id": g, "home": bool(h), "season": int(gi["season"]), "game_date": gi["game_date"], "game_type": 2,
                     "team_id": int(gi["home_team_id"] if h else gi["away_team_id"]), "opp_team_id": int(gi["away_team_id"] if h else gi["home_team_id"]),
                     "sec_all": float(st["n_seconds"]), "sec_ev": float(st["sec_ev"]), "sec_pp": float(st["sec_pp"]), "sec_sh": float(st["sec_sh"]),
                     "xf_all": a["xf_all"], "xa_all": o["xf_all"], "xf_ev": a["xf_ev"], "xa_ev": o["xf_ev"], "xf_pp": a["xf_pp"], "xa_sh": o["xf_pp"],
                     "hd_f": a["hd_all"], "hd_a": o["hd_all"], "att_f": a["att_all"], "att_a": o["att_all"], "gf": a["goals_all"], "ga": o["goals_all"]})
    return pd.DataFrame(rows), xg


def own_to_moneypuck_format(own, scale):
    """Own team-game xG as MoneyPuck-format situation rows, each stat scaled to MoneyPuck's level with ``scale`` (ratios of sums
    fitted on 2021-2023). No score/venue adjustment exists for own xG: the adjusted columns carry the raw values."""
    import pandas as pd
    base = own[["season", "game_id", "game_date", "game_type", "team_id", "opp_team_id", "home"]]
    def blk(sit, sec, xf, xa, gf=None, ga=None, extra=False):
        d = base.copy(); d["situation"] = sit; d["iceTime"] = own[sec].values
        d["xGoalsFor"] = own[xf].values * scale[xf] if xf else 0.0; d["xGoalsAgainst"] = own[xa].values * scale[xa] if xa else 0.0
        d["goalsFor"] = own[gf].values if gf else np.nan; d["goalsAgainst"] = own[ga].values if ga else np.nan
        for adj in ("scoreVenueAdjustedxGoals", "flurryScoreVenueAdjustedxGoals"):
            d[f"{adj}For"] = d["xGoalsFor"]; d[f"{adj}Against"] = d["xGoalsAgainst"]
        if extra:
            d["highDangerxGoalsFor"] = own["hd_f"].values * scale["hd_f"]; d["highDangerxGoalsAgainst"] = own["hd_a"].values * scale["hd_a"]
            d["scoreAdjustedShotsAttemptsFor"] = own["att_f"].values * scale["att_f"]; d["scoreAdjustedShotsAttemptsAgainst"] = own["att_a"].values * scale["att_a"]
        return d
    return pd.concat([blk("all", "sec_all", "xf_all", "xa_all", "gf", "ga", True), blk("5on5", "sec_ev", "xf_ev", "xa_ev"),
                      blk("5on4", "sec_pp", "xf_pp", None), blk("4on5", "sec_sh", None, "xa_sh")], ignore_index=True)


def reconstruct_starters(gl, shots26):
    """As-played starter for team-games whose archived goalie log has NO starter flag (2026-27): the only goalie with ice time,
    else the goalie in net for the first shot the team faced. Returns ({(game_id, is_home): goalie id}, validation info) where the
    same rule is scored on every team-game that DOES carry a flag (all seasons)."""
    first_net = {}
    for g, (ts, rows) in shots26.items():
        for r in sorted(rows, key=lambda r: (r["period"], r["t_s"])):
            if r.get("goalie_in_net_id") is None or r["goalie_in_net_id"] != r["goalie_in_net_id"]:
                continue
            k = (int(g), int(not bool(r["is_home"])))          # the DEFENDING side's goalie
            first_net.setdefault(k, int(r["goalie_in_net_id"]))
    out = {}; n_flag = n_ok = n_single = n_shot = n_none = 0
    for (g, h), d in gl.groupby(["game_id", "is_home"], sort=True):
        played = d[d["toi_s"] > 0]; flag = d[d["starter"].astype(bool)]
        guess = int(played["player_id"].iloc[0]) if len(played) == 1 else first_net.get((int(g), int(bool(h))))
        if len(flag) == 1:
            if guess is not None:
                n_flag += 1; n_ok += int(guess == int(flag["player_id"].iloc[0]))
            continue
        if guess is None:
            n_none += 1; continue
        out[(int(g), int(bool(h)))] = guess; n_single += int(len(played) == 1); n_shot += int(len(played) != 1)
    return out, {"reconstructed": len(out), "by_single_goalie_with_ice_time": n_single, "by_first_shot_faced": n_shot, "unresolved": n_none,
                 "rule_checked_on_flagged_team_games": n_flag, "rule_agrees_with_flag": n_ok}


# ====================================================================== evaluation helpers
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


def ref_probs(d, pre):
    o = {"moneyline": d[f"{pre}_p_home_win"].values, "regulation_tie_overtime": d[f"{pre}_p_overtime"].values}
    for s in (4.5, 5.5, 6.5, 7.5):
        o[f"total_{s}"] = d[f"{pre}_p_over_{s}"].values
    o["puck_line_1.5"] = np.concatenate([d[f"{pre}_p_home_minus_1_5"].values, d[f"{pre}_p_away_minus_1_5"].values])
    for s in (2.5, 3.5):
        o[f"team_total_{s}"] = np.concatenate([d[f"{pre}_p_home_over_{s}"].values, d[f"{pre}_p_away_over_{s}"].values])
    return o


def logit(p):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def logistic_fit(X, y, iters=60):
    """Unpenalised logistic regression (Newton). X without intercept; returns coefficients [intercept, ...]."""
    X = np.column_stack([np.ones(len(y)), np.asarray(X, float)]); y = np.asarray(y, float); b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(X @ b, -30, 30))); w = np.clip(p * (1 - p), 1e-9, None)
        step = np.linalg.solve(X.T @ (X * w[:, None]) + 1e-9 * np.eye(X.shape[1]), X.T @ (y - p)); b += step
        if np.max(np.abs(step)) < 1e-10:
            break
    return b


def encompassing(p_model, p_market, y, gid, n_boot=500, seed=11):
    """y ~ a + b_model * logit(p_model) + b_market * logit(p_market), with a game-cluster bootstrap of the two slopes.
    b_market ~ 1 and b_model ~ 0 means the market already contains the model's information."""
    X = np.column_stack([logit(p_model), logit(p_market)]); y = np.asarray(y, float); b = logistic_fit(X, y)
    ug, inv = np.unique(np.asarray(gid), return_inverse=True); rows = [np.flatnonzero(inv == i) for i in range(len(ug))]
    rng = np.random.default_rng(seed); bs = []
    for _ in range(n_boot):
        ii = np.concatenate([rows[j] for j in rng.integers(0, len(ug), len(ug))]); bs.append(logistic_fit(X[ii], y[ii])[1:])
    bs = np.array(bs)
    return {"n": int(len(y)), "b_model": float(b[1]), "b_model_ci95": [float(np.quantile(bs[:, 0], .025)), float(np.quantile(bs[:, 0], .975))],
            "b_market": float(b[2]), "b_market_ci95": [float(np.quantile(bs[:, 1], .025)), float(np.quantile(bs[:, 1], .975))]}


def ols(X, y):
    X = np.column_stack([np.ones(len(y)), np.asarray(X, float)]); y = np.asarray(y, float)
    b, *_ = np.linalg.lstsq(X, y, rcond=None); res = y - X @ b
    return b, float(1 - res.var() / max(y.var(), 1e-12))


# ====================================================================== main pipeline
def run(log=print, arch_pre=None):
    import pandas as pd
    games, gfiles = J.load_games(); mp, mfiles = V.load_moneypuck_ext()
    docs = repos_dir() / "NHL-edge-finder" / "docs" / "research"
    v1 = pd.read_csv(docs / "walk_forward_36570274279_games.csv"); v2 = pd.read_csv(docs / "walk_forward_v2_wf2_20260929_games.csv")
    log("reading data-archive"); arch, arch_note = arch_pre if arch_pre is not None else load_archive3()
    assert arch is not None, arch_note
    g26, res26, sch26 = V.games_2026(arch)
    games_all = pd.concat([games, g26.drop(columns=["start_time_utc"])], ignore_index=True)
    mp26, avail26, mp26_info = moneypuck_2026(arch, sch26)
    start_h = {int(g): IS.stamp_hours(s["start_time_utc"]) for g, s in sch26.items()}

    # ---------------------------------------------------------------- frames: frozen (0.2), in-season MoneyPuck (headline)
    tg0 = J.build_team_games(games_all, mp)                                            # 2026-27 rows have no stats: frozen ratings
    tg = J.build_team_games(games_all, pd.concat([mp, mp26], ignore_index=True))       # 2026-27 rows from the archive
    assert (tg0["game_id"].values == tg["game_id"].values).all() and (tg0["home"].values == tg["home"].values).all()
    G = J.game_frame(tg)
    fin = games_all[games_all["final"].astype(bool)]
    gi = fin.drop_duplicates("game_id").set_index("game_id").loc[G["game_id"]]
    G["home_win"] = gi["home_win"].astype(int).values; G["extra"] = gi["last_period_type"].isin(["OT", "SO"]).astype(int).values
    G["hs"] = gi["home_score"].astype(int).values; G["as"] = gi["away_score"].astype(int).values
    G["total"] = G["hs"] + G["as"]; G["margin"] = G["hs"] - G["as"]
    season, sg, y = tg["season"].values, G["season"], tg["rg"].values.astype(float)
    n = len(tg); opp = np.arange(n) ^ 1
    is26 = season == 2026
    freeze_h = np.array([start_h.get(int(g), np.nan) - V.FREEZE_MIN / 60.0 if s == 2026 else np.nan for g, s in zip(tg["game_id"].values, season)])
    avail_h = np.array([IS.stamp_hours(avail26[(int(g), int(h))]) if s == 2026 and (int(g), int(h)) in avail26 else np.nan
                        for g, h, s in zip(tg["game_id"].values, tg["home"].values, season)])
    state_ok, league_ok = IS.availability_masks(tg["team"].values, tg["day"].values, avail_h, freeze_h)
    has26 = is26 & tg["xGoalsFor_all"].notna().values & tg["iceTime_5on5"].notna().values

    log("features")
    F0 = features_v3(tg0, HP)                       # frozen 2026-27 ratings (0.2 reference; identical to F on <= 2025)
    F = features_v3(tg, HP, state_ok, league_ok)    # in-season, availability-aware (headline)
    Fj = J.make_features(tg0, HP); Fj["f"].update(V.extra_team_features(tg0, HP))
    feat_err = max(float(np.nanmax(np.abs(F0["f"][k] - Fj["f"][k]))) for k in Fj["f"] if k in F0["f"])
    off_err = float(np.nanmax(np.abs(F0["offset"] - Fj["offset"])))
    pre26_err = max(float(np.nanmax(np.abs(F["f"][k][~is26] - F0["f"][k][~is26]))) for k in F["f"])

    base_names = list(J.FEATS["full"]); names02 = base_names + ["hd_o", "hd_d", "sa_o", "sa_d", "r3_t", "r3_o"]
    fit_rows = (season >= J.FIT_FIRST) & (season <= J.TRAIN_LAST); train_g = (sg >= J.FIT_FIRST) & (sg <= J.TRAIN_LAST)
    fit_v = (season >= J.FIT_FIRST) & (season < J.VAL_FIRST); val_v = (season >= J.VAL_FIRST) & (season <= J.TRAIN_LAST)
    fitg_v = (sg >= J.FIT_FIRST) & (sg < J.VAL_FIRST); valg_v = (sg >= J.VAL_FIRST) & (sg <= J.TRAIN_LAST)

    # ---------------------------------------------------------------- 0.1 and 0.2 references (re-fitted; reproduction checked)
    beta01 = J.fit_glm(tg, F0, base_names, fit_rows); lam01 = J.predict_lam(F0, base_names, beta01)
    joint01 = J.fit_joint(lam01[1::2][train_g], lam01[0::2][train_g], G["rh"][train_g], G["ra"][train_g])
    ties = train_g & (G["extra"] == 1); k01, _ = J.fit_ot_k(lam01[1::2][ties], lam01[0::2][ties], G["home_win"][ties])
    m01 = J.Model(tg, F0, base_names, beta01, joint01, k01)

    log("goalie inputs (0.2's frozen selection)")
    doc02 = json.loads((OPS / "NHL" / "alpha-nhl-joint-0.2" / "evaluation.json").read_text())
    ghp = doc02["design"]["fitted_parameters"]["goalie_hyper_best"]
    gl, glfiles, n26g = V.load_goalie_games(arch); xgs, sfiles, n_shots_mp = V.load_shot_xg()
    xs = {}
    for g, r in res26.items():
        for h, k in ((1, "home_starting_goalie_id"), (0, "away_starting_goalie_id")):
            if r.get(k) not in (None, "None", ""):
                xs[(int(g), h)] = int(r[k])
    rec, rec_info = reconstruct_starters(gl, arch["_shots"])
    xs.update({k: v for k, v in rec.items() if k not in xs})
    gl, starter, C, ginfo = V.goalie_block(tg, gl, xgs, xs)
    yr = lambda a, b: np.flatnonzero((season >= a) & (season <= b))
    tr_f = (season >= V.GOALIE_FIRST) & (season <= V.GOALIE_TRAIN_LAST)
    beta_s = NG.fit_conditional_logit(V.logit_groups(C, starter, yr(V.GOALIE_FIRST, V.GOALIE_TRAIN_LAST)))
    q_or, q_mix, _ = V.goalie_q(gl, tg, starter, C, ghp, beta_s)
    g26_cov = int((starter[is26] >= 0).sum())

    def team_log(Fx, names, mask=fit_rows):
        return np.log(J.predict_lam(Fx, names, J.fit_glm(tg, F, names, mask)))  # betas always fitted on <= 2023 rows (F == F0 there)

    def with_goalie(bl, q=q_mix):
        gam = V.fit_offset_glm(bl, [q[opp]], y, tr_f)
        return V.apply_offset(bl, [q[opp]], gam), gam
    log02, gam02 = with_goalie(team_log(F0, names02))
    la, lh = np.exp(log02[0::2]), np.exp(log02[1::2])
    jt02 = J.fit_joint(lh[train_g], la[train_g], G["rh"][train_g], G["ra"][train_g]); k02, _ = J.fit_ot_k(lh[ties], la[ties], G["home_win"][ties])
    m02 = Model3(log02, {"c3": jt02["c3"], "theta_tie": jt02["theta_tie"], "theta_one_goal": jt02["theta_one_goal"], "delta": jt02["delta"]}, k02)

    # ---------------------------------------------------------------- 0.3 selection on validation seasons (fit <= 2018, validate 2019-2023)
    log("validation selection")
    def vdev(names):
        b = J.fit_glm(tg, F, names, fit_v)
        return float(np.mean(J.poisson_deviance_rows(y[val_v], J.predict_lam(F, names, b)[val_v])))
    d_base = vdev(names02); team_sel = []
    for ext, cols in (("league_home_ice_trend", ["home_trend"]), ("slow_5v5_ratings", ["off5_slow", "def5_slow"])):
        dv = vdev(names02 + cols)
        team_sel.append({"extension": ext, "features": cols, "val_deviance_base": d_base, "val_deviance_with": dv, "delta": dv - d_base, "accepted": bool(dv < d_base)})
    acc_team = [c for s in team_sel if s["accepted"] for c in s["features"]]
    names03 = names02 + acc_team
    lam_v = J.predict_lam(F, names03, J.fit_glm(tg, F, names03, fit_v)); lvh, lva = lam_v[1::2], lam_v[0::2]
    jbase = fit_joint3(lvh[fitg_v], lva[fitg_v], G["rh"][fitg_v], G["ra"][fitg_v])
    vn = lambda jp: float(reg_nll(lvh[valg_v], lva[valg_v], G["rh"][valg_v], G["ra"][valg_v], jp).mean())
    n_base = vn(jbase); joint_sel = []
    for cid, free in JOINT_CANDIDATES.items():
        jp = fit_joint3(lvh[fitg_v], lva[fitg_v], G["rh"][fitg_v], G["ra"][fitg_v], free); nv = vn(jp)
        bs = paired_cluster_bootstrap(reg_nll(lvh[valg_v], lva[valg_v], G["rh"][valg_v], G["ra"][valg_v], jp)
                                      - reg_nll(lvh[valg_v], lva[valg_v], G["rh"][valg_v], G["ra"][valg_v], jbase), G["game_id"][valg_v])
        joint_sel.append({"candidate": cid, "post_hoc": cid in POST_HOC_CANDIDATES, "free": free, "fitted": {k: jp[k] for k in free}, "val_nll_base": n_base, "val_nll_with": nv, "delta": nv - n_base,
                          "delta_ci95": [bs["lo"], bs["hi"]], "accepted": bool(nv < n_base)})
    acc_joint = [k for s in joint_sel if s["accepted"] for k in s["free"]]
    jcomb = fit_joint3(lvh[fitg_v], lva[fitg_v], G["rh"][fitg_v], G["ra"][fitg_v], acc_joint); n_comb = vn(jcomb)
    best_single = min([s for s in joint_sel if s["accepted"]], key=lambda s: s["val_nll_with"], default=None)
    if best_single is not None and n_comb > best_single["val_nll_with"]:   # the accepted set must not be worse on validation than its best member
        acc_joint = list(best_single["free"]); n_comb = best_single["val_nll_with"]
    joint_combined = {"accepted_parameters": acc_joint, "val_nll_combined": n_comb, "val_nll_base": n_base, "delta": n_comb - n_base}
    tv_fit = fitg_v & (G["extra"] == 1); tv_val = valg_v & (G["extra"] == 1)
    k_a, _, _ = fit_ot3(lvh[tv_fit], lva[tv_fit], G["home_win"][tv_fit], False); k_b, h_b, _ = fit_ot3(lvh[tv_fit], lva[tv_fit], G["home_win"][tv_fit], True)
    ot_a = float(np.mean(logloss_rows(ot_home_prob3(lvh[tv_val], lva[tv_val], k_a), G["home_win"][tv_val])))
    ot_b = float(np.mean(logloss_rows(ot_home_prob3(lvh[tv_val], lva[tv_val], k_b, h_b), G["home_win"][tv_val])))
    ot_sel = {"candidate": "overtime_home_intercept", "val_logloss_base": ot_a, "val_logloss_with": ot_b, "delta": ot_b - ot_a, "fitted_h0_on_fit_window": h_b,
              "n_val_ties": int(tv_val.sum()), "observed_home_win_in_val_ties": float(G["home_win"][tv_val].mean()), "accepted": bool(ot_b < ot_a)}
    log(f"accepted: team {acc_team}, joint {acc_joint}, ot_h0 {ot_sel['accepted']}")

    # ---------------------------------------------------------------- 0.3 final fit (<= 2023) and arms
    def model03(Fx, names=None, free=None, h0=None, q=q_mix, jp=None):
        names = names03 if names is None else names; free = acc_joint if free is None else free; h0 = ot_sel["accepted"] if h0 is None else h0
        ll, gam = with_goalie(team_log(Fx, names), q)
        a_, h_ = np.exp(ll[0::2]), np.exp(ll[1::2])
        jp = fit_joint3(h_[train_g], a_[train_g], G["rh"][train_g], G["ra"][train_g], free) if jp is None else jp
        k, h0v, _ = fit_ot3(h_[ties], a_[ties], G["home_win"][ties], h0)
        return Model3(ll, jp, k, h0v), gam
    head, gam03 = model03(F)
    arms = {}
    if acc_team:
        arms["a_no_team_extensions"] = (model03(F, names=names02)[0], "0.3 team-rate extensions removed (0.2 team terms only)")
    for i, par in enumerate(acc_joint):
        arms[f"b{i + 1}_without_{par}"] = (model03(F, free=[k for k in acc_joint if k != par])[0], f"score-distribution parameter {par} removed (joint re-fitted)")
    if ot_sel["accepted"]:
        arms["c_no_overtime_home_intercept"] = (model03(F, h0=False, jp=head.jp)[0], "overtime home intercept removed")

    # ---------------------------------------------------------------- own shot xG (fit 2021-2023) and cross-checks
    log("own shot xG")
    sh, shfiles, n_sh_hist, n_sh26 = load_shot_events(arch); tstates, tsfiles = load_team_states(arch)
    shc = {c: sh[c].values for c in ("kind", "x", "y", "zone", "shot_type", "strength", "since_prev_s")}
    ssn = sh["season"].values
    xgm = IS.fit_shot_xg(shc, (ssn >= XG_FIT[0]) & (ssn <= XG_FIT[1]))
    own, xg_rows = own_xg_team_games(sh, tstates, xgm, games_all)
    mpa = pd.concat([mp, mp26], ignore_index=True); mpa = mpa[mpa["game_type"] == 2]
    hid = games_all.drop_duplicates("game_id").set_index("game_id")
    mpa_home = J.resolve_home(mpa, games_all)[0]
    wide = mpa_home.pivot_table(index=["game_id", "home"], columns="situation", values=["xGoalsFor", "xGoalsAgainst", "highDangerxGoalsFor", "scoreAdjustedShotsAttemptsFor", "goalsFor"], aggfunc="first")
    wide.columns = [f"{a}_{b}" for a, b in wide.columns]
    cmp_ = own.merge(wide.reset_index().assign(home=lambda d: d["home"].astype(bool)), on=["game_id", "home"], how="inner")
    tr = (cmp_["season"] >= XG_FIT[0]) & (cmp_["season"] <= XG_FIT[1])
    pairs = {"xf_all": "xGoalsFor_all", "xa_all": "xGoalsAgainst_all", "xf_ev": "xGoalsFor_5on5", "xa_ev": "xGoalsAgainst_5on5", "xf_pp": "xGoalsFor_5on4",
             "xa_sh": "xGoalsAgainst_4on5", "hd_f": "highDangerxGoalsFor_all", "att_f": "scoreAdjustedShotsAttemptsFor_all"}
    scale = {k: float(cmp_.loc[tr, v].sum() / cmp_.loc[tr, k].sum()) for k, v in pairs.items()}
    scale["hd_a"] = scale["hd_f"]; scale["att_a"] = scale["att_f"]
    unb = np.isin(shc["kind"], IS.UNBLOCKED); en = shc["strength"] == "EN"; yg = (shc["kind"] == "GOAL").astype(float)
    xg_val = {}
    for s0 in (2024, 2025, 2026):
        mm = (ssn == s0) & unb & ~en; cs = cmp_[cmp_["season"] == s0]
        if not mm.any() or not len(cs):
            continue
        base_p = float(yg[(ssn >= XG_FIT[0]) & (ssn <= XG_FIT[1]) & unb & ~en].mean())
        xg_val[str(s0)] = {"unblocked_attempts_on_goalie": int(mm.sum()), "goals": int(yg[mm].sum()), "sum_xg": float(xg_rows[mm].sum()),
                           "shot_logloss": float(logloss_rows(xg_rows[mm], yg[mm]).mean()), "shot_logloss_base_rate": float(logloss_rows(np.full(int(mm.sum()), base_p), yg[mm]).mean()),
                           "shot_auc": V.auc(xg_rows[mm], yg[mm]), "team_games_compared": int(len(cs)),
                           "corr_team_game_xg_all_vs_moneypuck": float(np.corrcoef(cs["xf_all"], cs["xGoalsFor_all"])[0, 1]),
                           "corr_team_game_xg_5v5_vs_moneypuck": float(np.corrcoef(cs["xf_ev"], cs["xGoalsFor_5on5"])[0, 1]),
                           "ratio_scaled_own_to_moneypuck_xg_all": float(cs["xf_all"].sum() * scale["xf_all"] / cs["xGoalsFor_all"].sum()),
                           "corr_team_game_own_xg_vs_goals": float(np.corrcoef(cs["xf_all"], cs["gf"])[0, 1]),
                           "corr_team_game_moneypuck_xg_vs_goals": float(np.corrcoef(cs["xGoalsFor_all"], cs["gf"])[0, 1]),
                           "own_goal_count_equals_moneypuck_goals_share": float((cs["gf"] == cs["goalsFor_all"]).mean())}
    own_mp = own_to_moneypuck_format(own, scale)
    mp_own_test = pd.concat([mp[mp["season"] < 2024], own_mp[own_mp["season"] >= 2024]], ignore_index=True)    # own xG replaces MoneyPuck from 2024 on
    mp_own_26 = pd.concat([mp, own_mp[own_mp["season"] == 2026]], ignore_index=True)                            # own xG only in 2026-27
    mp_apx, apx_corr, apx_n = approx_adjusted_5on5(mp, [2024, 2025])
    shot_h = {int(g): IS.stamp_hours(ts) for g, (ts, _) in arch["_shots"].items()}

    def arm_features(mp_variant, avail_map=None):
        t = J.build_team_games(games_all, mp_variant)
        assert (t["game_id"].values == tg["game_id"].values).all()
        if avail_map is None:
            return features_v3(t, HP)
        av = np.array([avail_map.get(int(g), np.nan) if s == 2026 else np.nan for g, s in zip(t["game_id"].values, season)])
        so, lo = IS.availability_masks(t["team"].values, t["day"].values, av, freeze_h)
        return features_v3(t, HP, so, lo), so, lo
    F_own_test = arm_features(mp_own_test); F_apx = arm_features(mp_apx)
    F_own26, so_own, lo_own = arm_features(mp_own_26, shot_h)
    like_head = lambda Fx: Model3(V.apply_offset(np.log(J.predict_lam(Fx, names03, J.fit_glm(tg, F, names03, fit_rows))), [q_mix[opp]], gam03), head.jp, head.k_ot, head.h0)
    arms_data = {"own_xg_replaces_moneypuck_from_2024": like_head(F_own_test), "approx_adjusted_5on5_from_2024": like_head(F_apx)}
    head_frozen = like_head(F0)   # identical parameters; 2026-27 ratings frozen pre-season (no 2026-27 stat row enters)
    arm26 = {"frozen_pre_season_ratings": head_frozen, "own_shot_xg_in_season": like_head(F_own26)}

    # ---------------------------------------------------------------- 2024/2025 test frame
    pos = pd.Series(np.arange(len(G["game_id"])), index=G["game_id"])
    ti = pos.reindex(v1["game_id"].values).values.astype(int)
    assert set(sg[ti].tolist()) == set(J.TEST_SEASONS)
    gid = G["game_id"][ti]; coh = sg[ti].astype(str)
    Y = {"home_win": G["home_win"][ti], "ot": G["extra"][ti], "total": G["total"][ti], "margin": G["margin"][ti], "hs": G["hs"][ti], "as": G["as"][ti]}
    mk, mk02, mk01 = head.markets(ti), m02.markets(ti), m01.markets(ti)
    ch, c02, c01 = fam_probs(mk, Y, gid, coh), fam_probs(mk02, Y, gid, coh), fam_probs(mk01, Y, gid, coh)
    refs = {REF_V1: ref_probs(v2, "V1"), REF_SIM2: ref_probs(v2, "SIM2"), REF_01: {f: c01[f][0] for f in c01}, REF_02: {f: c02[f][0] for f in c02}}
    arch_of = lambda fam: J.ARCH["ev"] if fam.startswith(("regulation", "game_overtime")) else J.ARCH["tot"] if "total" in fam else J.ARCH["ml"]
    results = []
    for ref, rp in refs.items():
        for fam in HEAD:
            p, yy, gg, cc = ch[fam]
            for metric in ("logloss", "brier"):
                results += J.compare(fam, arch_of(fam), metric, ref, p, rp[fam], yy, gg, cc)
    want = lambda d, ref: {r["market_family"]: r["challenger" if ref is None else "reference_value"] for r in d["results"]
                           if r["reference"] == (REF_V1 if ref is None else ref) and r["cohort"] == "pooled" and r["metric"] == "logloss"}
    w02 = want(doc02, None); rep02 = max(abs(float(logloss_rows(c02[f][0], c02[f][1]).mean()) - w02[f]) for f in HEAD)
    w01 = want(doc02, REF_01); rep01 = max(abs(float(logloss_rows(c01[f][0], c01[f][1]).mean()) - w01[f]) for f in HEAD)

    # ---------------------------------------------------------------- Kalshi T-60 mid, 2025 cohort (evaluation reference only)
    log("kalshi 2025 reference")
    reg_games = games[(games["game_type"] == 2) & games["final"].astype(bool)]
    q, kcov, k_entries, k_checks = J.kalshi_reference(reg_games[(reg_games["season"] == 2025) & reg_games["game_id"].isin(set(gid.tolist()))])
    k_checks = [dict(c, basis="COMPUTED") for c in k_checks]
    tpos = pd.Series(np.arange(len(gid)), index=gid); market_context = []; diag = {}
    q = q.assign(pos=tpos.reindex(q["game_id"].values).values); q = q[q["pos"].notna()].copy(); q["pos"] = q["pos"].astype(int)
    ml = q[q["series"] == "KXNHLGAME"].copy(); ml["p_home"] = np.where(ml["side"] == "home", ml["mid"], 1 - ml["mid"])
    gm = ml.groupby("pos")["p_home"].mean(); ps = gm.index.values
    sets = [("moneyline", J.ARCH["ml"], mk["p_home_win"][ps], mk02["p_home_win"][ps], gm.values, Y["home_win"][ps], gid[ps])]
    tt = q[q["series"] == "KXNHLTOTAL"]
    for s in (5.5, 6.5):
        dq = tt[tt["strike"] == s]; ps2 = dq["pos"].values
        sets.append((f"total_{s}", J.ARCH["tot"], J.p_over(mk["total_pmf"][ps2], s), J.p_over(mk02["total_pmf"][ps2], s), dq["mid"].values, dq["y"].values, gid[ps2]))
    sp = q[(q["series"] == "KXNHLSPREAD") & (q["strike"] == 1.5)]; hm = (sp["side"] == "home").values; ps3 = sp["pos"].values
    sets.append(("puck_line_1.5", J.ARCH["ml"], np.where(hm, J.p_margin_over(mk, 1.5, "home")[ps3], J.p_margin_over(mk, 1.5, "away")[ps3]),
                 np.where(hm, J.p_margin_over(mk02, 1.5, "home")[ps3], J.p_margin_over(mk02, 1.5, "away")[ps3]), sp["mid"].values, sp["y"].values, gid[ps3]))
    for fam, ar, pc, p2, pm, yy, gg in sets:
        if len(yy) < 50:
            continue
        for metric in ("logloss", "brier"):
            results += J.compare(fam, ar, metric, REF_MKT, pc, pm, yy, gg, np.full(len(yy), "2025"))
        a_c, b_c = calibration_slope(pc, yy); a_m, b_m = calibration_slope(pm, yy)
        rec = 1 / (1 + np.exp(-(a_c + b_c * logit(pc))))  # IN-SAMPLE recalibration: the most favourable possible slope/intercept fix
        bs = paired_cluster_bootstrap(logloss_rows(rec, yy) - logloss_rows(pm, yy), gg)
        market_context.append({"market_family": fam, "cohort": "2025", "n_rows": int(len(yy)), "n_games": bs["n_clusters"], "challenger_logloss": float(logloss_rows(pc, yy).mean()),
                               "alpha_0_2_logloss": float(logloss_rows(p2, yy).mean()), "market_mid_logloss": float(logloss_rows(pm, yy).mean()),
                               "challenger_slope": b_c, "market_slope": b_m, "challenger_auc": V.auc(pc, yy), "market_auc": V.auc(pm, yy),
                               "challenger_recalibrated_in_sample_minus_market": bs["mean"], "recalibrated_ci95": [bs["lo"], bs["hi"]],
                               "encompassing": encompassing(pc, pm, yy, gg)})
    # information-gap diagnosis on the 2025 moneyline: what does (market - model) load on?
    rows_h = ti[ps] * 2 + 1; rows_a = ti[ps] * 2
    gap = logit(gm.values) - logit(mk["p_home_win"][ps])
    goalie_news = (q_or[rows_a] - q_mix[rows_a]) - (q_or[rows_h] - q_mix[rows_h])       # + = away starter worse than expected -> home favoured
    Fs = features_v3(tg, dict(HP, hl=8.0), state_ok, league_ok)["f"]
    form = lambda Fx: (Fx["off5"][rows_h] - Fx["def5"][rows_h]) - (Fx["off5"][rows_a] - Fx["def5"][rows_a])
    recent_form = form(Fs) - form(F["f"])                                                # short-memory minus model-memory rating edge
    gw = F["games_w"][rows_h]
    for nm, X in (("goalie_starter_news_only", goalie_news[:, None]), ("recent_form_only", recent_form[:, None]),
                  ("both", np.column_stack([goalie_news, recent_form]))):
        b, r2 = ols(X, gap); diag[nm] = {"coef": b[1:].tolist(), "r2": r2}
    yy_h = Y["home_win"][ps]
    diag.update({"n_games": int(len(ps)), "gap": "logit(market home) - logit(model home), Kalshi T-60 mid, 2025 moneyline",
                 "gap_sd": float(gap.std()), "gap_mean": float(gap.mean()), "corr_gap_goalie_news": float(np.corrcoef(gap, goalie_news)[0, 1]),
                 "corr_gap_recent_form": float(np.corrcoef(gap, recent_form)[0, 1]),
                 "outcome_on_model_plus_gap": dict(zip(["intercept", "b_model_logit", "b_gap"], logistic_fit(np.column_stack([logit(mk["p_home_win"][ps]), gap]), yy_h).tolist())),
                 "oracle_starter_model_minus_market": None, "note": "goalie_starter_news = as-played starter quality minus the PIT mixture (an ORACLE quantity, used "
                 "only to explain the gap, never as a model input); recent_form = half-life-8 rating edge minus the model's half-life-30 edge"})
    m_or, _ = model03(F, q=q_or); p_or = m_or.markets(ti)["p_home_win"][ps]
    bs = paired_cluster_bootstrap(logloss_rows(p_or, yy_h) - logloss_rows(gm.values, yy_h), gid[ps])
    diag["oracle_starter_model_minus_market"] = {"diff": bs["mean"], "ci95": [bs["lo"], bs["hi"]], "oracle_not_pit": True}
    half = np.argsort(gid[ps]) < len(ps) // 2
    diag["by_season_half"] = {nm: {"n": int(mm.sum()), "model_minus_market_logloss": float((logloss_rows(mk["p_home_win"][ps], yy_h) - logloss_rows(gm.values, yy_h))[mm].mean())}
                              for nm, mm in (("first_half", half), ("second_half", ~half))}

    # ---------------------------------------------------------------- prospective 2026-27: actual frozen forecasts
    log("prospective 2026-27")
    t26 = np.flatnonzero(sg == 2026); p26 = {int(g): k for k, g in enumerate(G["game_id"][t26])}
    mk26 = {"c": head.markets(t26), "02": m02.markets(t26), "fz": head_frozen.markets(t26), "own": arm26["own_shot_xg_in_season"].markets(t26)}
    fv1 = V.freeze_rows(arch.get("predictions", []), "ticker"); fv2 = V.freeze_rows(arch.get("predictions_v2", []), "ticker")
    rows = []
    fl = lambda v: float(v) if v not in (None, "None") else None
    for tk in sorted(fv2):
        r2 = fv2[tk]; r1 = fv1.get(tk); g = int(r2["game_id"]); fam = r2["family"]
        if g not in p26 or str(g) not in res26:
            continue
        res = res26[str(g)]; k = p26[g]; thr = r2.get("threshold"); tm = r2.get("team_id")
        rows.append({"game_id": g, "family": fam, "y": V.market_outcome(fam, tm, thr, res), "mts": float(r2["minutes_to_start"]),
                     **{f"p_{a}": V.market_prob(mk26[a], k, fam, tm, thr, res["home_team_id"]) for a in mk26},
                     "p_v1": fl(r1.get("p_data_only")) if r1 else None, "p_v2": fl(r2.get("p_data_only_v2")), "p_mkt": fl(r1.get("p_market") if r1 else r2.get("p_market")),
                     "freeze": r2["predicted_at_utc"]})
    P = pd.DataFrame(rows)
    fam_map = {"game_winner": ("moneyline", J.ARCH["ml"]), "game_total": ("total_all_listed_strikes", J.ARCH["tot"]),
               "game_spread": ("spread_all_listed_strikes", J.ARCH["ml"]), "team_total": ("team_total_all_listed_strikes", J.ARCH["tot"]),
               "game_overtime": ("regulation_tie_overtime", J.ARCH["ev"])}
    pcov, inseason_rows, mkt26 = {}, [], []
    for famk, (fname, ar) in fam_map.items():
        d = P[P["family"] == famk]
        pcov[famk] = {"frozen_markets": int(len(d)), "games": int(d["game_id"].nunique())}
        for ref, col in ((P_V1, "p_v1"), (P_V2, "p_v2"), (P_02, "p_02"), (P_MKT, "p_mkt")):
            dd = d[d[col].notna()]
            if len(dd) < 30:
                continue
            for metric in ("logloss", "brier"):
                results += J.compare(fname, ar, metric, ref, dd["p_c"].values, dd[col].values.astype(float), dd["y"].values, dd["game_id"].values, np.full(len(dd), "2026"))
            pcov[famk][f"n_{col}"] = int(len(dd))
        if len(d) >= 30:
            for arm, col in (("frozen_pre_season_ratings", "p_fz"), ("own_shot_xg_in_season", "p_own")):
                bs = paired_cluster_bootstrap(logloss_rows(d["p_c"].values, d["y"].values) - logloss_rows(d[col].values, d["y"].values), d["game_id"].values)
                inseason_rows.append({"market_family": fname, "arm": arm, "metric": "logloss", "n_rows": bs["n_rows"], "n_games": bs["n_clusters"],
                                      "headline_in_season_moneypuck": float(logloss_rows(d["p_c"].values, d["y"].values).mean()),
                                      "arm_value": float(logloss_rows(d[col].values, d["y"].values).mean()), "diff_headline_minus_arm": bs["mean"], "ci95": [bs["lo"], bs["hi"]]})
            dm = d[d["p_mkt"].notna()]
            if len(dm) >= 30 and famk == "game_winner":
                pc, pm, yy, gg = dm["p_c"].values, dm["p_mkt"].values.astype(float), dm["y"].values, dm["game_id"].values
                a_c, b_c = calibration_slope(pc, yy); a_m, b_m = calibration_slope(pm, yy)
                bsf = paired_cluster_bootstrap(logloss_rows(dm["p_fz"].values, yy) - logloss_rows(pm, yy), gg)
                bsc = paired_cluster_bootstrap(logloss_rows(pc, yy) - logloss_rows(pm, yy), gg)
                mkt26.append({"market_family": fname, "cohort": "2026", "n_rows": int(len(dm)), "n_games": bsc["n_clusters"], "challenger_slope": b_c, "market_slope": b_m,
                              "challenger_auc": V.auc(pc, yy), "market_auc": V.auc(pm, yy),
                              "in_season_minus_market": bsc["mean"], "in_season_ci95": [bsc["lo"], bsc["hi"]],
                              "frozen_ratings_minus_market": bsf["mean"], "frozen_ci95": [bsf["lo"], bsf["hi"]],
                              "share_of_frozen_gap_closed_by_in_season_ratings": float(1 - bsc["mean"] / bsf["mean"]) if bsf["mean"] > 0 else None,
                              "encompassing": encompassing(pc, pm, yy, gg)})
    foa = V.freeze_rows(arch.get("predictions_oa", []), "game_id")
    oa = [(p26[int(g)], r) for g, r in sorted(foa.items()) if int(g) in p26 and r.get("arm") == "OA_SVA"]
    if len(oa) >= 30:
        ks = np.array([k for k, _ in oa]); gg = G["game_id"][t26][ks]; cc = np.full(len(ks), "2026")
        yy = {"moneyline": G["home_win"][t26][ks], "regulation_tie_overtime": G["extra"][t26][ks]}
        pc = {"moneyline": mk26["c"]["p_home_win"][ks], "regulation_tie_overtime": mk26["c"]["p_reg_tie"][ks]}
        for s in (5.5, 6.5):
            yy[f"total_{s}"] = (G["total"][t26][ks] > s).astype(int); pc[f"total_{s}"] = J.p_over(mk26["c"]["total_pmf"][ks], s)
        po = {"moneyline": "p_home_win", "regulation_tie_overtime": "p_overtime", "total_5.5": "p_over_5.5", "total_6.5": "p_over_6.5"}
        for fam in pc:
            pr = np.array([float(r[po[fam]]) for _, r in oa])
            for metric in ("logloss", "brier"):
                results += J.compare(fam, arch_of(fam), metric, P_OA, pc[fam], pr, yy[fam], gg, cc)
    rn = lambda m, idx: -np.log(m.reg(idx)[np.arange(len(idx)), np.clip(G["rh"][idx], 0, J.K - 1), np.clip(G["ra"][idx], 0, J.K - 1)] + 1e-300)
    base26 = rn(head, t26)
    for arm, m in (("frozen_pre_season_ratings", head_frozen), ("own_shot_xg_in_season", arm26["own_shot_xg_in_season"]), ("alpha_0_2_frozen_ratings", m02)):
        bs = paired_cluster_bootstrap(base26 - rn(m, t26), G["game_id"][t26])
        inseason_rows.append({"market_family": "regulation_score", "arm": arm, "metric": "regulation_score_nll", "n_rows": bs["n_rows"], "n_games": bs["n_clusters"],
                              "headline_in_season_moneypuck": float(base26.mean()), "arm_value": float(rn(m, t26).mean()), "diff_headline_minus_arm": bs["mean"], "ci95": [bs["lo"], bs["hi"]]})
    results = J.finalize_verdicts(results)

    # ---------------------------------------------------------------- ablations on 2024+2025 (variant - headline)
    log("ablations")
    base_nll = rn(head, ti); abl = []
    ABL = [(vid, m, lab) for vid, (m, lab) in arms.items()] + [
           ("d_own_xg_replaces_moneypuck", arms_data["own_xg_replaces_moneypuck_from_2024"], "own shot-xG team stats replace MoneyPuck from 2024 on (same parameters): cost of the fallback input"),
           ("e_approx_adjusted_5on5", arms_data["approx_adjusted_5on5_from_2024"], "archive-equivalent 5on5 adjusted xG (raw x all-situations ratio) from 2024 on: cost of the 2026-27 construction"),
           ("f_alpha_0_2", m02, "alpha-nhl-joint-0.2 (re-fitted)")]
    for vid, m, lab in ABL:
        fv = fam_probs(m.markets(ti), Y, gid, coh)
        comps = [("regulation_score_nll", rn(m, ti), base_nll, gid, coh)]
        for fam in ("moneyline", "regulation_tie_overtime", "total_5.5", "puck_line_1.5", "team_total_2.5"):
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
        concl = ("HEADLINE_BETTER_SIGNIFICANT" + ("_REPLICATED" if prim["same_sign_both_cohorts"] else "_NOT_REPLICATED")) if prim["ci95"][0] > 0 else \
            "HEADLINE_WORSE_SIGNIFICANT" if prim["ci95"][1] < 0 else "NO_DETECTABLE_DIFFERENCE"
        abl.append({"ablation_id": vid, "label": lab, "conclusion": concl, "primary_metric": "regulation_score_nll (per game)",
                    "sign_convention": "diff = variant - headline; positive = the headline is better", "rows": rows_a})

    # ---------------------------------------------------------------- calibration by family + margin distribution
    def cal(p, yy, cc):
        out = {}
        for co in sorted(set(cc.tolist())) + ["pooled"]:
            mm = np.ones(len(yy), bool) if co == "pooled" else cc == co
            a, b = calibration_slope(p[mm], yy[mm])
            out[co] = {"n": int(mm.sum()), "intercept": a, "slope": b, "auc": V.auc(p[mm], yy[mm]), "mean_p": float(p[mm].mean()), "observed": float(yy[mm].mean())}
        return out
    calib = {fam: {"challenger_0_3": cal(ch[fam][0], ch[fam][1], ch[fam][3]), "alpha_0_2": cal(refs[REF_02][fam], ch[fam][1], ch[fam][3]),
                   "incumbent_V1": cal(refs[REF_V1][fam], ch[fam][1], ch[fam][3]), "shadow_SIM2": cal(refs[REF_SIM2][fam], ch[fam][1], ch[fam][3])} for fam in HEAD}
    def margin_table(m, idx):
        Pm = m.reg(idx); k = J.K; d = np.abs(np.arange(k)[:, None] - np.arange(k)[None, :]); ad = np.abs(G["rh"][idx] - G["ra"][idx])
        return {lab: {"predicted": float(Pm[:, msk].sum(1).mean()), "observed": float(obs.mean())}
                for lab, msk, obs in (("tie", d == 0, ad == 0), ("one_goal", d == 1, ad == 1), ("two_goal", d == 2, ad == 2), ("three_plus", d >= 3, ad >= 3))}
    # empty-net evidence from the official goal events (2021-2025): share of regulation two-goal results that ended on an empty-net goal
    gfs = sorted(f for f in (J._hist() / "players").glob("goals_*.parquet") if "2026" not in f.name)
    gls = pd.concat([pd.read_parquet(f, columns=["game_id", "game_type", "period", "t_s", "empty_net", "season"]) for f in gfs], ignore_index=True)
    gls = gls[(gls["game_type"] == 2) & (gls["period"] <= 3)]
    en_by = gls.groupby("game_id")["empty_net"].sum(); last_en = gls.sort_values(["game_id", "period", "t_s"]).groupby("game_id")["empty_net"].last()
    gsel = np.flatnonzero((sg >= 2021) & (sg <= 2025)); ad = np.abs(G["rh"][gsel] - G["ra"][gsel]); gids = G["game_id"][gsel]
    en_cnt = en_by.reindex(gids).fillna(0).values; en_last = last_en.reindex(gids).fillna(False).astype(bool).values
    scoring = {"regulation_margin_distribution_2024_2025": {"challenger_0_3": margin_table(head, ti), "alpha_0_2": margin_table(m02, ti)},
               "regulation_margin_distribution_2026": {"challenger_0_3": margin_table(head, t26), "alpha_0_2": margin_table(m02, t26)},
               "empty_net_2021_2025": {"games": int(len(gsel)), "games_with_empty_net_goal": int((en_cnt > 0).sum()),
                                       "share_of_two_goal_regulation_results_ending_on_empty_net_goal": float(en_last[ad == 2].mean()),
                                       "share_of_three_goal_regulation_results_with_empty_net_goal": float((en_cnt[ad == 3] > 0).mean()),
                                       "empty_net_goals_per_game": float(en_cnt.mean()),
                                       "note": "official goal events; an empty-net goal turns a one-goal regulation result into a two-goal one, which is what the two-goal weight absorbs"},
               "overtime": {"train_ties": int(ties.sum()), "observed_home_win_in_train_ties": float(G["home_win"][ties].mean()),
                            "test_ties": int((Y["ot"] == 1).sum()), "observed_home_win_in_test_ties": float(Y["home_win"][Y["ot"] == 1].mean()),
                            "shootout_share_of_test_extra_time_games": float((gi["last_period_type"].values[ti][Y["ot"] == 1] == "SO").mean())}}

    # ---------------------------------------------------------------- data checks (every one computed in this run)
    rev = sum(1 for (top, k), (ts, v) in arch["_mp_last"].items() if top == "context/team_games" and k in arch["_mp"] and v is not None
              and abs(float(v) - float(arch["_mp"][k][1]["xGoalsFor"])) > 1e-9)
    hkey = {(int(g), int(h)): float(v) for g, h, v in zip(tg.loc[is26, "game_id"].values, tg.loc[is26, "home"].values, tg.loc[is26, "xGoalsFor_all"].values)}
    first_x, last_x = {}, {}
    for (g, team, sit), (ts, r) in arch["_mp"].items():
        hh = int(str(r["home_or_away"]).upper() == "HOME"); first_x[(g, hh)] = float(r["xGoalsFor"]); last_x[(g, hh)] = float(arch["_mp_last"][("context/team_games", (g, team, sit))][1])
    used_first = sum(1 for k, v in first_x.items() if k in hkey and abs(hkey[k] - v) < 1e-9)
    used_last_on_revised = sum(1 for k, v in first_x.items() if abs(last_x[k] - v) > 1e-9 and k in hkey and abs(hkey[k] - last_x[k]) < 1e-9)
    lag = np.array([IS.stamp_hours(ts) - start_h[g] for (g, h), ts in avail26.items() if g in start_h])
    lag_s = np.array([shot_h[g] - start_h[g] for g in shot_h if g in start_h])
    n26 = int((sg == 2026).sum()); n_tg26 = int(is26.sum())
    a26 = tg[is26]; all_vs_st = None
    stall = {(g, t): r for (g, t, s), (ts, r) in arch["_mp_st"].items() if s == "all"}
    both = [(float(r["xGoalsFor"]), float(stall[(g, t)]["xGoalsFor"])) for (g, t, s), (ts, r) in arch["_mp"].items() if (g, t) in stall]
    all_vs_st = float(np.mean([abs(a - b) < 0.02 for a, b in both])) if both else None
    gf_mp = pd.Series(a26["goalsFor_all"].values, index=pd.MultiIndex.from_arrays([a26["game_id"].values, a26["home"].values]))
    fin26 = fin[fin["season"] == 2026].drop_duplicates("game_id").set_index("game_id")
    fs_ = np.array([float(fin26.loc[g, "home_score" if h else "away_score"]) - (1.0 if (fin26.loc[g, "last_period_type"] == "SO" and bool(fin26.loc[g, "home_win"]) == bool(h)) else 0.0)
                    for g, h in gf_mp.index])
    goals_ok = float((gf_mp.values == fs_).mean())
    sh26 = own[own["season"] == 2026]; own_goals = sh26.set_index(["game_id", "home"])["gf"]
    fs_own = np.array([float(fin26.loc[g, "home_score" if h else "away_score"]) - (1.0 if (fin26.loc[g, "last_period_type"] == "SO" and bool(fin26.loc[g, "home_win"]) == bool(h)) else 0.0)
                       for g, h in own_goals.index])
    own_goals_ok = float((own_goals.values == fs_own).mean()) if len(own_goals) else 0.0
    # leak guard: perturb every 2026-27 archive stat row captured after a cut date; no feature of an earlier-frozen game may change
    cut_day = int(np.median(tg["day"].values[is26])); tgp = tg.copy(); late = is26 & (tg["day"].values >= cut_day)
    statc = [c for c in tgp.columns if c.endswith(("_all", "_5on5", "_5on4", "_4on5"))]
    tgp.loc[late, statc] = tgp.loc[late, statc].values[::-1] * 1.7 + 0.3
    Fp = features_v3(tgp, HP, state_ok, league_ok); early = tg["day"].values <= cut_day
    leak = max(float(np.nanmax(np.abs(Fp["f"][k][early] - F["f"][k][early]))) for k in F["f"])
    moved = max(float(np.nanmax(np.abs(F["f"][k][is26] - F0["f"][k][is26]))) for k in ("off5", "def5"))
    inseason_checks = [
        check("archive_moneypuck_team_games_cover_final_games", int(has26.sum()) == n_tg26, f"{int(has26.sum())}/{n_tg26} final 2026-27 team-games ({n26} games) have archived MoneyPuck all-situations AND 5on5/5on4/4on5 rows"),
        check("archive_moneypuck_team_code_matches_schedule", mp26_info["team_code_matches_schedule"] == mp26_info["team_games"],
              f"{mp26_info['team_code_matches_schedule']}/{mp26_info['team_games']} rows: MoneyPuck team code equals the official schedule abbreviation for the row's home/away side"),
        check("archive_moneypuck_goals_equal_official_score", goals_ok > 0.99, f"MoneyPuck goalsFor (all situations) equals the official final score less the shootout goal in {goals_ok:.2%} of {len(fs_)} team-games"),
        check("archive_all_situation_rows_agree_between_two_captures", all_vs_st is not None and all_vs_st > 0.95,
              f"xGoalsFor of the all-situations row in context/team_games and in context/team_games_st (first captures) agree within 0.02 in {all_vs_st:.2%} of {len(both)} team-games"),
        check("first_capture_used_not_latest_revision", used_first == len(first_x) and (rev == 0 or used_last_on_revised < rev),
              f"{used_first}/{len(first_x)} 2026-27 team-game rows in the model frame carry the FIRST captured all-situations xGoalsFor; {rev} rows were revised later and "
              f"{used_last_on_revised} of those coincide with the latest value"),
        check("capture_precedes_next_game_freeze", bool((~state_ok[is26]).sum() <= 0.02 * n_tg26),
              f"{int((~state_ok[is26]).sum())}/{n_tg26} team-game rows were captured after the same team's next T-60 freeze and are EXCLUDED from that team's state; "
              f"{int((~league_ok[is26]).sum())} rows were captured after the earliest freeze of a later day and are EXCLUDED from league means; "
              f"capture lag after puck drop: median {np.median(lag):.1f} h, max {lag.max():.1f} h"),
        check("shot_events_cover_final_games", int((sh26["game_id"].nunique())) == n26, f"{sh26['game_id'].nunique()}/{n26} final 2026-27 games have archived play-by-play shot events ({n_sh26} event rows); "
              f"capture lag median {np.median(lag_s):.1f} h, max {lag_s.max():.1f} h; {int((~so_own[is26]).sum())} team-game rows excluded as captured after the next freeze"),
        check("shot_event_goals_equal_official_score", own_goals_ok > 0.99, f"goal events (periods 1-4) per team equal the official final score less the shootout goal in {own_goals_ok:.2%} of {len(fs_own)} team-games"),
        check("in_season_ratings_actually_update", moved > 0.01, f"max |5v5 rating - frozen pre-season rating| over 2026-27 team-games = {moved:.3f} log units"),
        check("pre_2026_features_unchanged_by_archive_rows", pre26_err < 1e-12, f"max feature difference on <= 2025 rows between the frozen and in-season frames = {pre26_err:.1e}"),
        check("leak_guard_future_archive_rows", leak < 1e-12, f"perturbing every archived 2026-27 stat row from day index {cut_day} on changes no feature of a game on or before that day (max diff {leak:.1e})"),
    ]
    rep_checks = [check("features_v3_equal_0_1_and_0_2_features", feat_err < 1e-12 and off_err < 1e-12, f"max |features_v3 - (nhl_joint.make_features + nhl_joint_v2.extra_team_features)| = {feat_err:.1e}; offset {off_err:.1e}"),
                  check("reproduces_committed_0_2", rep02 < 1e-4, f"max |pooled log loss of re-fitted 0.2 - committed 0.2| over {len(HEAD)} families = {rep02:.2e}"),
                  check("reproduces_committed_0_1", rep01 < 1e-4, f"max |pooled log loss of re-fitted 0.1 - the 0.1 value recorded in the 0.2 evaluation| = {rep01:.2e}")]
    v24 = xg_val.get("2024", {}); v25 = xg_val.get("2025", {}); v26 = xg_val.get("2026", {})
    xg_checks = [check("shot_xg_beats_base_rate_out_of_sample", all(v["shot_logloss"] < v["shot_logloss_base_rate"] for v in xg_val.values()),
                       "; ".join(f"{s}: log loss {v['shot_logloss']:.4f} vs base rate {v['shot_logloss_base_rate']:.4f}, AUC {v['shot_auc']:.3f}" for s, v in xg_val.items())),
                 check("shot_xg_team_game_correlation_with_moneypuck", all(v["corr_team_game_xg_all_vs_moneypuck"] > 0.8 for v in xg_val.values()),
                       "; ".join(f"{s}: r(all) {v['corr_team_game_xg_all_vs_moneypuck']:.3f}, r(5v5) {v['corr_team_game_xg_5v5_vs_moneypuck']:.3f} over {v['team_games_compared']} team-games" for s, v in xg_val.items())),
                 check("shot_xg_level_stable_out_of_sample", all(abs(v["ratio_scaled_own_to_moneypuck_xg_all"] - 1) < 0.05 for v in xg_val.values()),
                       "; ".join(f"{s}: scaled own / MoneyPuck total xG {v['ratio_scaled_own_to_moneypuck_xg_all']:.3f}" for s, v in xg_val.items())
                       + " (tolerance 5%; a season-level drift cancels in the model because every rating is a ratio to the trailing league mean of the same input)"),
                 check("shot_xg_calibrated_to_goals_out_of_sample", all(abs(v["sum_xg"] / v["goals"] - 1) < 0.08 for v in xg_val.values()),
                       "; ".join(f"{s}: sum xG / goals {v['sum_xg'] / v['goals']:.3f}" for s, v in xg_val.items())),
                 check("approx_adjusted_5on5_matches_true", apx_corr > 0.97, f"Pearson r between raw 5on5 xG x (all-situations adjusted / raw) and MoneyPuck's own adjusted 5on5 xG = {apx_corr:.4f} over {apx_n} team-games (2024-2025)")]
    sel_checks = [check(f"selection_{s['extension']}", s["accepted"] == (s["val_deviance_with"] < s["val_deviance_base"]),
                        f"val deviance {s['val_deviance_with']:.6f} vs base {s['val_deviance_base']:.6f} -> {'ACCEPTED' if s['accepted'] else 'REJECTED'}") for s in team_sel]
    sel_checks += [check(f"selection_{s['candidate']}", s["accepted"] == (s["val_nll_with"] < s["val_nll_base"]),
                         f"val regulation NLL {s['val_nll_with']:.6f} vs base {s['val_nll_base']:.6f} -> {'ACCEPTED' if s['accepted'] else 'REJECTED'}") for s in joint_sel]
    sel_checks.append(check("selection_overtime_home_intercept", ot_sel["accepted"] == (ot_b < ot_a), f"val log loss on {ot_sel['n_val_ties']} ties {ot_b:.6f} vs {ot_a:.6f} -> {'ACCEPTED' if ot_sel['accepted'] else 'REJECTED'}"))
    sel_checks.append(check("selection_reads_no_test_season", int(season[fit_v | val_v].max()) <= J.TRAIN_LAST and int(sg[fitg_v | valg_v].max()) <= J.TRAIN_LAST,
                            f"latest season in any selection fit or validation row = {int(season[fit_v | val_v].max())}"))
    fts = sorted(P["freeze"].tolist())
    p_checks = [check("prospective_outcomes_complete", len(t26) == len(res26), f"{len(t26)} final 2026-27 games in the frame from {len(res26)} archived results"),
                check("prospective_freeze_precedes_start", bool(len(P) and P["mts"].min() >= V.FREEZE_MIN), f"{len(P)} frozen market rows, min minutes_to_start {P['mts'].min()}"),
                check("goalie_starters_cover_2026_27", g26_cov >= 0.99 * n_tg26, f"{g26_cov}/{n_tg26} 2026-27 team-games have an as-played starter ({n26g} archived goalie rows): "
                      f"{g26_cov - rec_info['reconstructed']} flagged in the log, {rec_info['by_single_goalie_with_ice_time']} reconstructed as the only goalie with ice time, "
                      f"{rec_info['by_first_shot_faced']} as the goalie in net for the first shot faced, {rec_info['unresolved']} unresolved"),
                check("starter_reconstruction_rule_agrees_with_flag", rec_info["rule_checked_on_flagged_team_games"] > 0 and rec_info["rule_agrees_with_flag"] / max(rec_info["rule_checked_on_flagged_team_games"], 1) > 0.99,
                      f"the reconstruction rule names the flagged starter in {rec_info['rule_agrees_with_flag']}/{rec_info['rule_checked_on_flagged_team_games']} flagged team-games where the rule applies (2021-2026)")]

    # ---------------------------------------------------------------- verdict, claims, document
    pooled = lambda ref: [r for r in results if r["reference"] == ref and r["cohort"] == "pooled" and r["metric"] == "logloss"]
    hl_rows = pooled(REF_V1); nv = sum(r["verdict"] == "VALIDATED_IMPROVEMENT" for r in hl_rows); nw = [r["market_family"] for r in hl_rows if r["verdict"] == "NOT_IMPROVED"]
    strongest = {ref: {"validated": sum(r["verdict"] == "VALIDATED_IMPROVEMENT" for r in pooled(ref)), "not_improved": sum(r["verdict"] == "NOT_IMPROVED" for r in pooled(ref)),
                       "rows": len(pooled(ref)), "mean_diff": float(np.mean([r["diff"] for r in pooled(ref)]))} for ref in (REF_02, REF_SIM2, REF_01, REF_V1)}
    v_strong = strongest[REF_02]["validated"] + strongest[REF_SIM2]["validated"]
    overall = "VALIDATED_IMPROVEMENT" if hl_rows and nv == len(hl_rows) else "NOT_IMPROVED" if nw else "IMPROVED_NOT_VALIDATED" if nv else "INCONCLUSIVE"
    mrows = [r for r in results if r["reference"] in (REF_MKT, P_MKT) and r["metric"] == "logloss"]
    ins = {(r["market_family"], r["arm"]): r for r in inseason_rows}
    rs = ins[("regulation_score", "frozen_pre_season_ratings")]
    reason = (f"Headline = pooled 2024+2025 vs {REF_V1}, {len(hl_rows)} log-loss rows, Holm-adjusted: VALIDATED {nv}, NOT_IMPROVED {nw}. Against the strongest references "
              f"(re-fitted alpha-nhl-joint-0.2 and shadow SIM2): VALIDATED {v_strong} of {strongest[REF_02]['rows'] + strongest[REF_SIM2]['rows']} log-loss rows. "
              f"Validation-accepted extensions: team {acc_team or 'none'}, score distribution {acc_joint or 'none'}, overtime home intercept {ot_sel['accepted']}. "
              f"2026-27 in-season ratings vs frozen pre-season ratings (same parameters): regulation-score NLL diff {rs['diff_headline_minus_arm']:+.5f} "
              f"CI [{rs['ci95'][0]:+.5f}, {rs['ci95'][1]:+.5f}] over {rs['n_games']} games (single cohort, cannot be 'validated'). "
              f"Market rows (Kalshi mid; 2025 T-60 and 2026 at-freeze): challenger worse than the mid in {sum(r['diff'] > 0 for r in mrows)} of {len(mrows)} log-loss rows. "
              "No profitability claim; fees not modelled.")
    ab = {a["ablation_id"]: a for a in abl}
    def ab_ev(aid):
        p = [r for r in ab[aid]["rows"] if r["metric"] == "regulation_score_nll" and r["cohort"] == "pooled"][0]
        return f"{aid}: {ab[aid]['conclusion']}, pooled regulation-score NLL (variant - headline) {p['diff_variant_minus_headline']:+.5f} CI [{p['ci95'][0]:+.5f}, {p['ci95'][1]:+.5f}]"
    ins_ev = f"2026-27 in-season vs frozen ratings: regulation-score NLL {rs['diff_headline_minus_arm']:+.5f} CI [{rs['ci95'][0]:+.5f}, {rs['ci95'][1]:+.5f}], {rs['n_games']} games"
    claims = [
        {"input": "NHL:nhl.xg_for", "stage": "EVALUATED", "outcome": "PARTIAL", "evidence": f"in-season 2026-27 MoneyPuck team games recovered from data-archive ({int(has26.sum())}/{n_tg26} team-games, first capture, PIT); {ins_ev}"},
        {"input": "NHL:nhl.xg_against", "stage": "EVALUATED", "outcome": "PARTIAL", "evidence": ins_ev},
        {"input": "NHL:nhl.shot_rate", "stage": "EVALUATED", "outcome": "PARTIAL",
         "evidence": f"own shot-level xG from official play-by-play events (fit 2021-2023): team-game r vs MoneyPuck {v25.get('corr_team_game_xg_all_vs_moneypuck', float('nan')):.3f} (2025), "
                     f"{v26.get('corr_team_game_xg_all_vs_moneypuck', float('nan')):.3f} (2026-27); as a replacement input: {ab_ev('d_own_xg_replaces_moneypuck')}"},
        {"input": "NHL:nhl.special_teams", "stage": "EVALUATED", "outcome": "PARTIAL", "evidence": "5on4 / 4on5 xG rates carried from 0.1 and now updated in-season from context/team_games_st; no new special-teams term tested"},
        {"input": "NHL:nhl.venue", "stage": "EVALUATED", "outcome": "OK" if "home_trend" in acc_team else "REJECTED",
         "evidence": f"trailing league home-ice term: validation deviance delta {team_sel[0]['delta']:+.6f} ({'accepted' if team_sel[0]['accepted'] else 'rejected'}); "
                     f"overtime home intercept: validation log-loss delta {ot_sel['delta']:+.6f} ({'accepted' if ot_sel['accepted'] else 'rejected'})"},
        {"input": "NHL:nhl.goalie_quality", "stage": "EVALUATED", "outcome": "REJECTED", "evidence": "0.2's goalie term is carried unchanged (its own ablation showed no detectable value); "
         f"in the 2025 market diagnosis the ORACLE starter-news term explains R2 = {diag['goalie_starter_news_only']['r2']:.4f} of the model-to-market gap"},
        {"input": "NHL:m.quote_history", "stage": "EVALUATED", "outcome": "OK", "evidence": "Kalshi T-60 mid (2025) and the mid in frozen 2026-27 rows used as evaluation references and for the loss diagnosis only; never a model input"},
    ]
    dts = lambda top: sorted(f.split("/dt=")[1][:10] for f in arch["_files"].get(top, []))
    data = [
        {"dataset_id": "nhl_games", "repo": J.REPO, "path": "data/history/nhl/games_{2008..2025}.parquet", "rows": int(len(games)), "first": str(games["game_date"].min()),
         "last": str(games["game_date"].max()), "sha256_of_files": J.files_digest(gfiles), "commit": J.SOURCE_COMMIT, "kind": "HISTORICAL_BACKFILL", "rights_tier": "UNRESOLVED_INTERNAL_ONLY"},
        {"dataset_id": "moneypuck_team_games", "repo": J.REPO, "path": "data/history/moneypuck/team_games_{2008..2025}.parquet", "rows": int(len(mp)), "first": str(mp["game_date"].min()),
         "last": str(mp["game_date"].max()), "sha256_of_files": J.files_digest(mfiles), "commit": J.SOURCE_COMMIT, "kind": "HISTORICAL_BACKFILL", "rights_tier": "UNRESOLVED_INTERNAL_ONLY"},
        {"dataset_id": "nhl_shot_events", "repo": J.REPO, "path": "data/history/players/shots_{2021..2025}.parquet", "rows": int(n_sh_hist), "first": "2021", "last": "2025",
         "sha256_of_files": J.files_digest(shfiles), "commit": J.SOURCE_COMMIT, "kind": "HISTORICAL_BACKFILL", "rights_tier": "UNRESOLVED_INTERNAL_ONLY",
         "note": "official play-by-play shot events; aggregated in memory to team-game xG; no event row leaves the clone"},
        {"dataset_id": "nhl_team_states", "repo": J.REPO, "path": "data/history/players/team_states_{2021..2025}.parquet", "rows": int((tstates["season"] < 2026).sum()), "first": "2021", "last": "2025",
         "sha256_of_files": J.files_digest(tsfiles), "commit": J.SOURCE_COMMIT, "kind": "HISTORICAL_BACKFILL", "rights_tier": "UNRESOLVED_INTERNAL_ONLY"},
        {"dataset_id": "nhl_goal_events", "repo": J.REPO, "path": "data/history/players/goals_{2021..2025}.parquet", "rows": int(len(gls)), "first": "2021", "last": "2025",
         "sha256_of_files": J.files_digest(gfs), "commit": J.SOURCE_COMMIT, "kind": "HISTORICAL_BACKFILL", "rights_tier": "UNRESOLVED_INTERNAL_ONLY", "note": "empty-net diagnostics only"},
        {"dataset_id": "moneypuck_shots", "repo": J.REPO, "path": "data/history/moneypuck/shots_{2021..2025}.parquet", "rows": int(n_shots_mp), "first": "2021", "last": "2025",
         "sha256_of_files": J.files_digest(sfiles), "commit": J.SOURCE_COMMIT, "kind": "HISTORICAL_BACKFILL", "rights_tier": "UNRESOLVED_INTERNAL_ONLY", "note": "0.2 goalie expectation only"},
        {"dataset_id": "nhl_goalie_games", "repo": J.REPO, "path": "data/history/players/goalies_{2021..2025}.parquet + data-archive player_events/goalies (2026-27)", "rows": int(len(gl)),
         "first": str(gl["game_date"].min()), "last": str(gl["game_date"].max()), "sha256_of_files": J.files_digest(glfiles), "commit": J.SOURCE_COMMIT, "kind": "HISTORICAL_BACKFILL",
         "rights_tier": "UNRESOLVED_INTERNAL_ONLY"},
        {"dataset_id": "incumbent_walk_forward_v1", "repo": J.REPO, "path": "docs/research/walk_forward_36570274279_games.csv", "rows": int(len(v1)), "first": str(v1["game_date"].min()),
         "last": str(v1["game_date"].max()), "sha256": sha256_file(docs / "walk_forward_36570274279_games.csv"), "commit": J.SOURCE_COMMIT, "kind": "WALK_FORWARD_REPRODUCTION", "rights_tier": "OWNER_DERIVED"},
        {"dataset_id": "incumbent_walk_forward_v2_sim2", "repo": J.REPO, "path": "docs/research/walk_forward_v2_wf2_20260929_games.csv", "rows": int(len(v2)), "first": str(v2["game_date"].min()),
         "last": str(v2["game_date"].max()), "sha256": sha256_file(docs / "walk_forward_v2_wf2_20260929_games.csv"), "commit": J.SOURCE_COMMIT, "kind": "WALK_FORWARD_REPRODUCTION", "rights_tier": "OWNER_DERIVED"},
    ] + k_entries
    arch_rows = {"context/team_games": len(arch["_mp"]), "context/team_games_st": len(arch["_mp_st"]), "player_events/shots": int(n_sh26), "player_events/team_states": int(sum(len(v[1]) for v in arch["_states"].values()))}
    notes = {"predictions": "DATA_ONLY_V1 frozen forecasts", "predictions_v2": "DATA_ONLY_V2 (SIM2) frozen forecasts", "predictions_oa": "OA_RIDGE_V1 frozen forecasts",
             "results": "official final scores", "context/schedule": "official schedule", "context/goalie_observations": "starter observations (read, not used by 0.3)",
             "player_events/goalies": "goalie game logs", "context/team_games": "MoneyPuck all-situations team games, 2026-27 rows, first capture per row",
             "context/team_games_st": "MoneyPuck team games by situation, 2026-27 rows, first capture per row", "player_events/shots": "official play-by-play shot events, first capture per game",
             "player_events/team_states": "time on ice by manpower state, first capture per game"}
    for top in V.ARCHIVE_PATHS + NEW_PATHS:
        dd = dts(top)
        data.append({"dataset_id": f"archive_{top.replace('/', '_')}", "repo": f"{J.REPO}@data-archive", "path": f"{top}/dt=*/", "rows": int(arch_rows.get(top, len(arch.get(top, [])))),
                     "files": len(arch["_files"].get(top, [])), "first": dd[0] if dd else None, "last": dd[-1] if dd else None, "commit": ARCHIVE_COMMIT, "kind": "PROSPECTIVE_CAPTURE",
                     "rights_tier": "UNRESOLVED_INTERNAL_ONLY", "note": notes[top]})
    features = [
        {"feature_id": "alpha_0_2_reference_models", "catalog_inputs": ["NHL:nhl.xg_for", "NHL:nhl.xg_against", "NHL:nhl.special_teams", "NHL:nhl.rest_travel", "NHL:nhl.goalie_quality"],
         "description": "0.1 and 0.2 re-fitted by import with their frozen hyper-parameters (0.2's goalie configuration is read from its committed evaluation, not re-searched)",
         "pit_rule": "earlier game dates only; parameters from seasons <= 2023", "checks": rep_checks},
        {"feature_id": "in_season_team_ratings_2026_27", "catalog_inputs": ["NHL:nhl.xg_for", "NHL:nhl.xg_against", "NHL:nhl.special_teams", "NHL:nhl.shot_rate"],
         "description": "2026-27 MoneyPuck team-game rows recovered from data-archive (context/team_games + context/team_games_st) feed the same walk-forward ratings as 2008-2025",
         "pit_rule": "the FIRST captured version of each row; a row updates a team state only for games whose T-60 freeze is after its capture, and a league mean only for later days whose earliest freeze is after its capture",
         "checks": inseason_checks},
        {"feature_id": "own_shot_xg_model", "catalog_inputs": ["NHL:nhl.xg_for", "NHL:nhl.xg_against", "NHL:nhl.shot_rate"],
         "description": "logistic shot xG (distance, angle, shot type, strength, rebound, zone; separate empty-net model) on official play-by-play events, aggregated to team games; evaluated arm and cross-check, not the headline input",
         "pit_rule": f"fitted on {XG_FIT[0]}-{XG_FIT[1]} shots only; scaling to MoneyPuck level fitted on the same seasons; applied to later seasons", "checks": xg_checks},
        {"feature_id": "validation_selected_extensions", "catalog_inputs": ["NHL:nhl.venue"],
         "description": "team-rate candidates (league home-ice trend, slow 5v5 ratings) and score-distribution candidates (two-goal weight, tie weight by expected total / mismatch, overtime home intercept)",
         "pit_rule": "each accepted only if the 2019-2023 validation loss falls with parameters fitted on 2009-2018; test seasons never read", "checks": sel_checks},
    ]
    fitted = {"team_names": names03, "team_beta": dict(zip(["intercept"] + names03, J.fit_glm(tg, F, names03, fit_rows).tolist())), "goalie_gamma": gam03.tolist(), "goalie_hyper_from_0_2": ghp,
              "joint": head.jp, "ot_k": head.k_ot, "ot_home_intercept": head.h0, "joint_0_2_refit": m02.jp, "ot_k_0_2_refit": k02,
              "shot_xg": {"features": IS.XG_FEATS, "beta": dict(zip(IS.XG_FEATS, xgm["beta"].tolist())), "beta_empty_net": xgm["beta_empty_net"].tolist(), "n_fit": xgm["n_fit"],
                          "n_fit_empty_net": xgm["n_fit_empty_net"], "scale_to_moneypuck": scale}}
    coverage = {"final_games": n26, "team_games": n_tg26, "moneypuck_team_games_archived": int(has26.sum()), "moneypuck_usable_for_team_state": int((state_ok & has26).sum()),
                "moneypuck_usable_for_league_mean": int((league_ok & has26).sum()), "moneypuck_rows_revised_after_first_capture": int(rev),
                "moneypuck_capture_lag_hours": {"median": float(np.median(lag)), "p90": float(np.quantile(lag, .9)), "max": float(lag.max())},
                "shot_event_games": int(sh26["game_id"].nunique()), "shot_event_rows": int(n_sh26), "shot_capture_lag_hours": {"median": float(np.median(lag_s)), "max": float(lag_s.max())},
                "archive_file_inventory": dict(sorted(arch["_inventory"].items())),
                "archived_not_modelled": ["context/lines (line combinations)", "context/injuries", "context/rosters", "context/dailyfaceoff_raw", "context/sportsbook_odds (market input: never a feature)",
                                          "player_events/players", "player_events/coice (shared ice time)", "player_events/goals"],
                "goalie_starter_team_games": g26_cov, "goalie_starter_reconstruction": rec_info, "first_game": str(g26["game_date"].min()), "last_game": str(g26["game_date"].max()),
                "correction_to_0_2": "0.2 recorded that 2026-27 MoneyPuck team games were not archived; they are archived under context/team_games and context/team_games_st"}
    prospective = {"status": "EVALUATED", "games_final": int(len(t26)), "frozen_market_rows": int(len(P)), "coverage": pcov,
                   "freeze_rule": f"per Kalshi ticker, the last pre-game frozen prediction row with minutes_to_start >= {int(V.FREEZE_MIN)}",
                   "first_freeze": fts[0] if fts else None, "last_freeze": fts[-1] if fts else None, "oa_games": len(oa),
                   "in_season_vs_arms": inseason_rows, "market_diagnosis_2026": mkt26}
    doc = {"schema": EVAL_SCHEMA, "status": "RESEARCH_ONLY", "sport": "NHL", "challenger_id": CHALLENGER_ID, "incumbent_id": J.INCUMBENT_ID,
           "baselines": {"alpha_0_2": REF_02, "alpha_0_1": REF_01, "incumbent": REF_V1, "shadow": REF_SIM2, "market": REF_MKT, "prospective": [P_V1, P_V2, P_OA, P_02, P_MKT],
                         "strongest_reference_summary_pooled_logloss": strongest},
           "source_commits": {J.REPO: J.SOURCE_COMMIT, f"{J.REPO}@data-archive": ARCHIVE_COMMIT},
           "data": data, "features": features,
           "design": {"train_window": "team GLM 2009-2023; goalie gamma and starter model 2021-2023; joint/OT 2009-2023; shot xG 2021-2023",
                      "test_window": "2024, 2025 (+ 2026-27 prospective, single cohort)",
                      "selection": {"team": team_sel, "joint": joint_sel, "joint_combined": joint_combined, "overtime": ot_sel,
                                    "post_hoc_note": "the mismatch_scale candidate was added AFTER a first read of the 2024/2025 test cohorts showed that the two-goal weight, although it "
                                    "lowered regulation-score NLL, lowered the moneyline calibration slope (0.89 -> 0.81). Its acceptance and its value are still decided on the 2019-2023 "
                                    "validation seasons only, but the decision to test it was informed by test data and it is flagged post_hoc in the candidate list.",
                                    "rule": "fit 2009-2018, validate 2019-2023; a candidate is accepted only if the validation loss falls; test seasons never read"},
                      "promotion_rule": J.VERDICT_RULE, "fitted_parameters": fitted, "kalshi_coverage": kcov, "kalshi_checks": k_checks, "prospective_checks": p_checks,
                      "check_basis": "every check carries basis COMPUTED (passed is derived from data in this run) or ATTESTED (design statement); this document has no ATTESTED check"},
           "results": results, "ablations": abl, "calibration": calib, "scoring_distribution": scoring, "market_context": market_context, "market_loss_diagnosis_2025": diag,
           "inseason_2026_27_coverage": coverage, "own_shot_xg_validation": xg_val, "prospective": prospective,
           "not_demonstrated": ["travel distance / time zones: not built", "lineup / injury news as a model input: archived (context/lines, context/injuries) but not modelled",
                                "profitability or executable edge: fees, spread (mid vs ask) and fills not modelled", "2026-27 is a single cohort and can never be 'replicated'"],
           "verdict": {"overall": overall, "reason": reason, "retain_incumbent": True},
           "limitations": [
               "2024/2025 baselines are owner walk-forward REPRODUCTIONS of V1/SIM2 (no frozen forecasts exist before the data-archive started on 2026-09-29).",
               "The 0.2 reference is re-fitted here (reproduction checked against its committed evaluation); on 2026-27 it keeps its frozen pre-season ratings.",
               "2026-27 5on5 adjusted xG is an approximation (raw 5on5 x all-situations adjusted/raw ratio); its cost is measured on 2024-2025 (ablation e).",
               "The 2026-27 MoneyPuck rows were captured 9-38 hours after puck drop; rows captured after a later freeze are dropped, not delayed.",
               "The market-loss diagnosis uses ORACLE starter identity and the market mid as explanatory variables for the gap only; neither enters the model.",
               "Prospective Kalshi rows are only listed markets; the mid is the frozen row's (bid+ask)/2, not an executable ask; rights UNRESOLVED_INTERNAL_ONLY.",
               "MoneyPuck and NHL play-by-play rows are read from the owner's clone only (rights unresolved); no new collection was made.",
           ],
           "input_stage_claims": claims}
    for f_ in doc["features"]:
        for c_ in f_["checks"]:
            assert c_.get("basis") in ("COMPUTED", "ATTESTED"), c_
    errs = validate_evaluation(doc)
    assert not errs, errs
    write_json(OUT / "evaluation.json", doc)
    log(f"wrote {OUT / 'evaluation.json'}: overall {overall}")
    return doc


def main(argv=None):
    run()


if __name__ == "__main__":
    main()
