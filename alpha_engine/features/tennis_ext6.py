"""Tennis builder proof of concept, five archived-data inputs (RESEARCH_ONLY; Sackmann ATP/WTA match files, CC BY-NC-SA 4.0: NON-COMMERCIAL research use only).

    ten.within_match_dependence, ten.hold_rate_uncertainty_propagation, ten.player_speed_slope, ten.set_dist, ten.set_number_calibration

Status: offline builders with synthetic-fixture tests and the generic replay harness only. NOT run on the pinned raw files (absent from this container), NOT blind-verified,
NOT promoted: every spec is PARTIAL and nothing here may be recorded as FULL or verified until a real-data replay and an independent blind re-implementation pass.

Point-in-time rule (same as tennis_ext2..5): Sackmann stamps every match of a tournament with the tournament START date and the order of matches inside it is a convention, so every
aggregate is date-batched: a match's features use ONLY matches whose tourney_date is STRICTLY EARLIER than its own (nothing from the same tournament, nothing from the same date).
Player key = tour:id (ids collide across the two files). Output table ``team``: one row per (match, player).

Reused, not re-derived: score parsing, windowed strictly-earlier sums, shrinkage and walk-forward Elo from tennis_ext2; the closed-form hold and the set dynamic programme from
tennis_ext4 (its opponent-adjusted serve-point-win estimate is reproduced exactly in ``_long`` and tested for equality with tennis_ext4's verified ``gps_hold_pre``).
Monte Carlo draws named in the catalog are replaced by deterministic Gauss-Hermite quadrature (the replay harness requires bit-for-bit determinism).
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.polynomial.hermite_e import hermegauss

from .core import FeatureSpec
from . import tennis_ext2 as X2
from . import tennis_ext4 as X4

S = "TENNIS"
COLS6 = X2.COLS + ["w_1stWon", "w_2ndWon", "l_1stWon", "l_2ndWon"]
PAIRS = [("winner_id", "loser_id"), ("winner_ioc", "loser_ioc"), ("winner_seed", "loser_seed")] + [(f"w_{c}", f"l_{c}") for c in ("ace", "svpt", "1stWon", "2ndWon", "SvGms", "bpFaced", "bpSaved")]
CONTENT = ["score", "winner_id", "loser_id", "w_ace", "l_ace", "w_svpt", "l_svpt", "w_1stWon", "l_1stWon", "w_2ndWon", "l_2ndWon", "w_SvGms", "l_SvGms", "w_bpFaced", "w_bpSaved", "l_bpFaced", "l_bpSaved"]
LN10_400 = np.log(10.0) / 400.0
SET_GAMES = np.array(X4.GAMES, float)


MANIFEST = Path(__file__).resolve().parents[2] / "research/tennis_builder_poc/required_files.json"


def verify_pinned(files) -> None:
    """Refuse any file that is not in the pinned manifest or whose SHA-256 differs, and refuse an incomplete set (all 54 pinned files are required)."""
    import hashlib
    pins = {f["file"]: f["sha256"] for f in json.loads(MANIFEST.read_text())["files"]}
    got = {Path(f).name: f for f in files}
    bad = [n for n in got if n not in pins] + [n for n, f in got.items() if n in pins and hashlib.sha256(Path(f).read_bytes()).hexdigest() != pins[n]]
    missing = sorted(set(pins) - set(got))
    if bad or missing:
        raise ValueError(f"pinned-file check failed: unpinned or hash mismatch {sorted(bad)[:5]}, missing {missing[:5]} ({len(missing)} missing)")


def load_raw(tennis_dir, verify: bool = True) -> dict:
    fs = sorted(glob.glob(str(Path(tennis_dir) / "[aw]t[pa]_matches_20*.csv.gz")))
    if not fs:
        raise FileNotFoundError(f"no pinned Sackmann match files under {tennis_dir} (see research/tennis_builder_poc/required_files.json); nothing is downloaded")
    if verify: verify_pinned(fs)
    d = pd.concat([pd.read_csv(f, usecols=lambda c: c in COLS6, low_memory=False).assign(tour=Path(f).name[:3]) for f in fs], ignore_index=True)
    return prepare(d)


def prepare(d: pd.DataFrame) -> dict:
    """Raw Sackmann rows (+ `tour`) -> the builder's raw dict. Shared by load_raw and the synthetic fixtures, so both go through the same cleaning."""
    d = d.dropna(subset=["tourney_date", "winner_id", "loser_id"]).copy()
    d["date"] = pd.to_datetime(d.tourney_date.astype(int).astype(str), format="%Y%m%d", errors="coerce"); d = d.dropna(subset=["date"])
    for c in COLS6:
        if c not in d: d[c] = np.nan
    d["game_id"] = d.tour + "|" + d.tourney_id.astype(str) + "|" + d.match_num.astype(str)
    d["game_id"] = d.game_id + "|" + d.groupby("game_id").cumcount().astype(str)
    d["season"] = d.date.dt.year
    return {"matches": d[["game_id", "tour", "date", "season"] + COLS6].reset_index(drop=True)}


# ------------------------------------------------------------------ small closed-form pieces
def p66(ha, hb):
    """P(a set reaches 6-6) for game-hold probabilities ha (A serving) and hb (B serving), averaged over the first server. Arrays."""
    ha = np.asarray(ha, float); hb = np.asarray(hb, float); tot = np.zeros(len(ha))
    for first_a in (True, False):
        st = {(0, 0): np.ones(len(ha))}
        for g in range(12):
            nxt = {}
            for (a, b), pr in st.items():
                pa = ha if ((g % 2 == 0) == first_a) else 1 - hb
                for na, nb, q in ((a + 1, b, pa), (a, b + 1, 1 - pa)):
                    if (max(na, nb) == 6 and min(na, nb) <= 4) or (max(na, nb) == 7 and min(na, nb) == 5): continue
                    nxt[(na, nb)] = nxt.get((na, nb), 0) + pr * q
            st = nxt
        tot += st.get((6, 6), 0)
    return tot / 2


def set_count_pmf(w, best_of):
    """iid sets with P(A wins a set) = w: pmf of the number of sets (keys 2..5) and P(A wins the match)."""
    w = np.asarray(w, float); l = 1 - w; bo5 = np.asarray(best_of, float) == 5
    p2 = np.where(bo5, 0.0, w ** 2 + l ** 2); p3_3 = 1 - (w ** 2 + l ** 2)
    p3_5 = w ** 3 + l ** 3; p4 = 3 * (w ** 3 * l + l ** 3 * w); p5 = 1 - p3_5 - p4
    win3 = w ** 2 * (1 + 2 * l); win5 = w ** 3 * (1 + 3 * l + 6 * l ** 2)
    return {2: p2, 3: np.where(bo5, p3_5, p3_3), 4: np.where(bo5, p4, 0.0), 5: np.where(bo5, p5, 0.0)}, np.where(bo5, win5, win3)


def _gh(k):
    x, w = hermegauss(k); return x, w / w.sum()


def _chunks(n, size=200_000):
    for a in range(0, n, size): yield slice(a, min(n, a + size))


# ------------------------------------------------------------------ long table (one row per match x player), pre-match serve estimates exactly as tennis_ext4
def _long(m: pd.DataFrame) -> pd.DataFrame:
    wo = m.score.astype(str).str.contains("W/O", regex=False)
    ok = ~wo & (m.w_svpt > 0) & (m.l_svpt > 0) & m[["w_1stWon", "w_2ndWon", "l_1stWon", "l_2ndWon"]].notna().all(axis=1)
    ws, ls = m.w_1stWon + m.w_2ndWon, m.l_1stWon + m.l_2ndWon
    rw = np.where(np.isnan(m.selo_w), m.elo_w, 0.5 * (m.elo_w + m.selo_w)); rl = np.where(np.isnan(m.selo_l), m.elo_l, 0.5 * (m.elo_l + m.selo_l))
    rows = []
    for me in ("w", "l"):
        op = "l" if me == "w" else "w"; sv, ov = m[f"{me}_svpt"], m[f"{op}_svpt"]; sw, ow = (ws, ls) if me == "w" else (ls, ws)
        rows.append(pd.DataFrame({"game_id": m.game_id, "team": m.wkey if me == "w" else m.lkey, "opp": m.lkey if me == "w" else m.wkey, "tour": m.tour, "date": m.date, "season": m.season,
                                  "best_of": m.best_of, "surface": m.surface.fillna("NA"), "event": m.tour + "|" + m.tourney_name.astype(str).str.strip().str.lower(),
                                  "won": 1.0 if me == "w" else 0.0, "p_win": m.p_w if me == "w" else 1 - m.p_w, "rating": rw if me == "w" else rl,
                                  "s_won": np.where(ok, sw, np.nan), "s_pts": np.where(ok, sv, np.nan), "r_won": np.where(ok, ov - ow, np.nan), "r_pts": np.where(ok, ov, np.nan),
                                  "svgms": m[f"{me}_SvGms"], "bpf": m[f"{me}_bpFaced"], "bps": m[f"{me}_bpSaved"], "score": m.score, "fav_is_me": m.fav_is_w if me == "w" else ~m.fav_is_w,
                                  "p_fav": m.p_fav, "is_w": me == "w"}))
    L = pd.concat(rows, ignore_index=True); dd = L.date.to_numpy()
    V = L[["s_won", "s_pts", "r_won", "r_pts"]].to_numpy(float)
    ps, _ = X2._wsum(L[["team"]], dd, V, 1095, hl_days=365.0)
    ts, _ = X2._wsum(L[["tour"]], dd, V[:, :2], 1095)
    with np.errstate(all="ignore"):
        L["sp"] = ps[:, 0] / ps[:, 1]; L["rr"] = ps[:, 2] / ps[:, 3]; L["t"] = ts[:, 0] / ts[:, 1]
    o = L[["game_id", "team", "sp", "rr"]].rename(columns={"team": "opp", "sp": "o_sp", "rr": "o_rr"})
    L = L.merge(o, on=["game_id", "opp"], how="left")
    L["spw_pre"] = (L.sp + (L.o_rr - (1 - L.t))).clip(0.30, 0.90)
    L["o_spw"] = (L.o_sp + (L.rr - (1 - L.t))).clip(0.30, 0.90)
    L["hold_pre"] = X4.hold(L.spw_pre); L["o_hold"] = X4.hold(L.o_spw)
    return L


def _sets_ok(score, best_of):
    """Completed-match set list [(row player's winner-view games)...] or None (RET/DEF/W-O/unparsable/advantage final sets/match tiebreaks)."""
    o = X2._match_outcome(score, best_of)
    if not o["ok"]: return None
    sets, _ = X2._parse(score)
    if any(a + b not in X4.GAMES for a, b in sets): return None
    return sets


# ------------------------------------------------------------------ builders
def compute(raw: dict) -> dict:
    m = X2._elo(raw["matches"].copy())
    L = _long(m); n = len(L); dd = L.date.to_numpy()
    good = (L.spw_pre.notna() & L.o_spw.notna()).to_numpy()
    sets = [(_sets_ok(s, b) if w else None) for s, b, w in zip(L.score, L.best_of, L.is_w)]   # parsed once per match (winner row); outcome data, used only in strictly-earlier sums
    sets_by_game = {g: s for g, s, w in zip(L.game_id, sets, L.is_w) if w}
    L["sets"] = L.game_id.map(sets_by_game)

    # ---- ten.within_match_dependence: games-per-set overdispersion vs the iid hold model; random match-form effect on spw (method of moments)
    pmf = np.full((n, len(X4.GAMES)), np.nan)
    if good.any():
        for sl in _chunks(int(good.sum())):
            ix = np.flatnonzero(good)[sl]; pa, pb = L.spw_pre.to_numpy()[ix], L.o_spw.to_numpy()[ix]
            r = X4.set_dp(X4.hold(pa), X4.hold(pb), pa, pb); pmf[ix] = np.column_stack([r[f"g{g}"] for g in X4.GAMES]) / np.column_stack([r[f"g{g}"] for g in X4.GAMES]).sum(1, keepdims=True)
    mu = (pmf * SET_GAMES).sum(1); var = (pmf * SET_GAMES ** 2).sum(1) - mu ** 2
    ssr = np.full(n, np.nan); sv = np.full(n, np.nan); nst = np.full(n, np.nan)
    for i, s in enumerate(L.sets):
        if isinstance(s, list) and good[i] and L.is_w.iat[i]:                      # one contribution per match (winner row); keyed by tour x best_of
            g = np.array([a + b for a, b in s], float); ssr[i] = ((g - mu[i]) ** 2).sum(); sv[i] = len(g) * var[i]; nst[i] = len(g)
    s_, _ = X2._wsum(L[["tour", "best_of"]], dd, np.column_stack([ssr, sv, nst]), 1095)
    with np.errstate(all="ignore"):
        L["wmd_overdisp_pre"] = np.where(s_[:, 1] > 0, s_[:, 0] / s_[:, 1], np.nan)
    L["wmd_n_sets_pre"] = s_[:, 2]
    with np.errstate(all="ignore"):
        act = L.s_won / L.s_pts; dev = act - L.spw_pre; binv = L.spw_pre * (1 - L.spw_pre) / L.s_pts
    fv = np.column_stack([(dev ** 2 - binv).to_numpy(float), dev.to_numpy(float)])
    fs_, fc_ = X2._wsum(L[["tour"]], dd, fv, 1095)
    with np.errstate(all="ignore"):
        tau2 = fs_[:, 0] / fc_[:, 0] - (fs_[:, 1] / fc_[:, 1]) ** 2
    L["wmd_form_sd_pre"] = np.sqrt(np.clip(tau2, 0, None)); L.loc[fc_[:, 0] < 30, "wmd_form_sd_pre"] = np.nan

    # ---- ten.hold_rate_uncertainty_propagation: Beta-posterior spw (normal approx.) + day shock N(0, 0.02^2), E[p66] by 7x7 Gauss-Hermite quadrature
    ns_, _ = X2._wsum(L[["team"]], dd, L[["s_pts"]].to_numpy(float), 730, hl_days=365.0)
    L["hru_neff_pre"] = np.minimum(ns_[:, 0], 4000.0)
    L = L.merge(L[["game_id", "team", "hru_neff_pre"]].rename(columns={"team": "opp", "hru_neff_pre": "hru_opp_neff_pre"}), on=["game_id", "opp"], how="left")
    x, w = _gh(7); cols = {k: np.full(n, np.nan) for k in ("hru_p66_mean_pre", "hru_p66_point_pre")}
    gi = np.flatnonzero(good & (L.hru_neff_pre > 0).to_numpy() & (L.hru_opp_neff_pre > 0).to_numpy())
    for sl in _chunks(len(gi), 20_000):
        ix = gi[sl]; pa, pb = L.spw_pre.to_numpy()[ix], L.o_spw.to_numpy()[ix]
        sa = np.sqrt(pa * (1 - pa) / (L.hru_neff_pre.to_numpy()[ix] + 1) + 0.02 ** 2); sb = np.sqrt(pb * (1 - pb) / (L.hru_opp_neff_pre.to_numpy()[ix] + 1) + 0.02 ** 2)
        A = np.clip(pa[:, None, None] + sa[:, None, None] * x[None, :, None], 0.30, 0.90); B = np.clip(pb[:, None, None] + sb[:, None, None] * x[None, None, :], 0.30, 0.90)
        A, B = np.broadcast_arrays(A, B); W = (w[:, None] * w[None, :]).ravel()
        cols["hru_p66_mean_pre"][ix] = (p66(X4.hold(A.ravel()), X4.hold(B.ravel())).reshape(len(ix), -1) * W).sum(1)
        cols["hru_p66_point_pre"][ix] = p66(X4.hold(pa), X4.hold(pb))
    for k, v in cols.items(): L[k] = v
    L["hru_jensen_pre"] = L.hru_p66_mean_pre - L.hru_p66_point_pre

    # ---- ten.player_speed_slope: leave-player-out event pace index (hold residuals over ~3 editions) and a ridge slope of the player's results on it
    with np.errstate(all="ignore"):
        obs_h = 1 - (L.bpf - L.bps) / L.svgms.replace(0, np.nan)
    resid = (obs_h - L.hold_pre).where(good)
    L["_res"] = resid; mres = L.groupby("game_id")["_res"].transform("mean")             # match-level residual (both players' holds vs their own pre-match holds); outcome data
    Se, Ce = X2._wsum(L[["event"]], dd, mres.to_numpy(float)[:, None], 1155, hl_days=365.0)
    Sp, Cp = X2._wsum(L[["event", "team"]], dd, mres.to_numpy(float)[:, None], 1155, hl_days=365.0)
    num = Se[:, 0] - 2 * Sp[:, 0]; den = Ce[:, 0] - 2 * Cp[:, 0]                          # each match sits twice in the event key (two rows) and once in the player's key
    L["pss_cpi_pre"] = np.where(Ce[:, 0] > 0, num / (np.clip(den, 0, None) + 20.0), np.nan)
    gx = (L.p_win * (1 - L.p_win) * LN10_400 * L.pss_cpi_pre).to_numpy(float); y = (L.won - L.p_win).to_numpy(float)
    rv = np.column_stack([gx * y, gx * gx]); rv[np.isnan(gx)] = np.nan
    Rs, Rc = X2._wsum(L[["team"]], dd, rv, 730)
    with np.errstate(all="ignore"):
        # linearised logistic posterior mean with prior beta ~ N(0, 500^2) (Elo points per unit index): kappa = Var(y)/500^2 with Var(y) ~ 0.25; the identifying signal is weak, so this shrinks hard
        L["pss_beta_pre"] = np.where(Rc[:, 1] >= 10, Rs[:, 0] / (Rs[:, 1] + 0.25 / 500.0 ** 2), np.nan)
    L["pss_n_pre"] = Rc[:, 1]
    L["pss_adj_rating_pre"] = L.rating + L.pss_beta_pre * L.pss_cpi_pre

    # ---- ten.set_dist: set-count pmf with a latent match-form shock (tau = wmd_form_sd_pre), 5x5 Gauss-Hermite, calibrated by tour x surface x best_of observed/expected
    xs, ws = _gh(5); P = {k: np.full(n, np.nan) for k in (2, 3, 4, 5)}; win = np.full(n, np.nan)
    gi = np.flatnonzero(good & L.wmd_form_sd_pre.notna().to_numpy())
    for sl in _chunks(len(gi), 20_000):
        ix = gi[sl]; tau = L.wmd_form_sd_pre.to_numpy()[ix]; pa, pb = L.spw_pre.to_numpy()[ix], L.o_spw.to_numpy()[ix]
        A = np.clip(pa[:, None, None] + tau[:, None, None] * xs[None, :, None], 0.30, 0.90); B = np.clip(pb[:, None, None] + tau[:, None, None] * xs[None, None, :], 0.30, 0.90)
        A, B = np.broadcast_arrays(A, B); W = (ws[:, None] * ws[None, :]).ravel()
        sw = X4.set_dp(X4.hold(A.ravel()), X4.hold(B.ravel()), A.ravel(), B.ravel())["win"]
        pk, mw = set_count_pmf(sw, np.repeat(L.best_of.to_numpy(float)[ix], len(W)))
        for k in P: P[k][ix] = (pk[k].reshape(len(ix), -1) * W).sum(1)
        win[ix] = (mw.reshape(len(ix), -1) * W).sum(1)
    for k in P: L[f"sd_p{k}_pre"] = P[k]
    L["sd_match_win_pre"] = win
    nset = L.sets.map(lambda s: len(s) if isinstance(s, list) else np.nan).to_numpy(float)
    oe = np.column_stack([np.where(np.isnan(nset) | np.isnan(P[2]) | ~L.is_w.to_numpy(), np.nan, (nset == k).astype(float)) for k in (2, 3, 4, 5)]
                         + [np.where(np.isnan(nset) | ~L.is_w.to_numpy(), np.nan, P[k]) for k in (2, 3, 4, 5)])
    Os, _ = X2._wsum(L[["tour", "surface", "best_of"]], dd, oe, 3650)
    with np.errstate(all="ignore"):
        ratio = np.column_stack([(Os[:, j] + 200 * 1.0) / (Os[:, 4 + j] + 200) for j in range(4)])
        cal = np.column_stack([P[k] for k in (2, 3, 4, 5)]) * ratio; cal = cal / cal.sum(1, keepdims=True)
    for j, k in enumerate((2, 3, 4, 5)): L[f"sd_cal_p{k}_pre"] = cal[:, j]

    # ---- ten.set_number_calibration: favourite's set-win frequency by set index and prior-set state, by edge bin; logit offsets vs set 1, shrunk n/(n+50) to the edge-pooled cell
    STATES = [("s1", 1, 0), ("s2_won1", 2, 1), ("s2_lost1", 2, -1), ("s3_level", 3, 0), ("s4_up", 4, 1), ("s4_down", 4, -1), ("s5_level", 5, 0)]
    sv_ = np.full((n, len(STATES)), np.nan)
    for i in np.flatnonzero(L.is_w.to_numpy()):
        s = L.sets.iat[i]
        if not isinstance(s, list): continue
        fav_w = bool(L.fav_is_me.iat[i]); diff = 0
        for k, (a, b) in enumerate(s, start=1):
            fw = (a > b) if fav_w else (b > a)
            for j, (_, idx, st) in enumerate(STATES):
                if idx == k and st == diff: sv_[i, j] = float(fw)
            diff += 1 if fw else -1
    L["ebin"] = np.minimum(((L.p_fav - 0.5) * 20).astype(int), 4)
    cs, cc = X2._wsum(L[["tour", "best_of", "ebin"]], dd, sv_, 3650); ps_, pc = X2._wsum(L[["tour", "best_of"]], dd, sv_, 3650)
    with np.errstate(all="ignore"):
        f = np.column_stack([X2._shrunk(cs[:, j], cc[:, j], ps_[:, j], pc[:, j], 50) for j in range(len(STATES))])
        lg = np.log(np.clip(f, 1e-4, 1 - 1e-4) / (1 - np.clip(f, 1e-4, 1 - 1e-4)))
    L["snc_logit_s1_pre"] = lg[:, 0]
    for j, (nm, _, _) in enumerate(STATES[1:], start=1): L[f"snc_off_{nm}_pre"] = lg[:, j] - lg[:, 0]
    bo3 = (L.best_of != 5).to_numpy()
    for nm in ("s4_up", "s4_down", "s5_level"): L.loc[bo3, f"snc_off_{nm}_pre"] = np.nan
    L["snc_n_pre"] = cc[:, 0]

    keep = ["game_id", "team", "date", "season"] + [c for s in specs() for c in s.columns] + ["pss_n_pre"]   # pss_n_pre: diagnostic count, not an input column
    return {"team": L[keep].sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


# ------------------------------------------------------------------ replay perturbations (role-preserving: the (game_id, player) universe never changes)
def perturb(raw: dict, ids, seed: int, content=None) -> dict:
    rng = np.random.default_rng(seed); m = raw["matches"].copy(); ix = np.flatnonzero(m.game_id.isin(ids).to_numpy()); fl = ix[rng.random(len(ix)) < 0.5]
    for a, b in PAIRS:
        if a in m and b in m:
            va, vb = m[a].to_numpy(dtype=object, copy=True), m[b].to_numpy(dtype=object, copy=True); va[fl], vb[fl] = vb[fl].copy(), va[fl].copy()
            for c, v in ((a, va), (b, vb)):
                try: m[c] = pd.Series(v, index=m.index).astype(raw["matches"][c].dtype)
                except (TypeError, ValueError): m[c] = pd.Series(v, index=m.index)
    for c in (content if content is not None else [c for c in CONTENT if c not in ("winner_id", "loser_id")]):
        if c in m:
            v = m[c].to_numpy(dtype=object, copy=True); v[ix] = rng.permutation(v[ix])
            try: m[c] = pd.Series(v, index=m.index).astype(raw["matches"][c].dtype)
            except (TypeError, ValueError): m[c] = pd.Series(v, index=m.index)
    return {**raw, "matches": m}


def perturb_nv(raw: dict, ids, seed: int) -> dict:
    """Non-vacuity only: also shuffles the block's surface, event name and format (never used by the leak tests: it changes the match's own cell)."""
    return perturb(raw, ids, seed, [c for c in CONTENT if c not in ("winner_id", "loser_id")] + ["surface", "tourney_name", "best_of"])


def specs() -> list[FeatureSpec]:
    R = ["sackmann_atp_wta_matches"]
    return [
        FeatureSpec(S, "ten.within_match_dependence", "team", ["wmd_overdisp_pre", "wmd_form_sd_pre", "wmd_n_sets_pre"], "PARTIAL",
                    "ratio of observed games-per-set squared deviation to the iid hold-model variance (tour x best_of, completed matches over the previous 1095 days, strictly earlier dates) and the SD of a match-form shock on serve-point-win estimated by method of moments (observed minus pre-match spw, binomial variance removed, by tour)",
                    ["observed vs iid games-per-set variance", "random match-form effect on spw (moment estimate)"], ["likelihood-based random-effect fit", "separating the form shock from pre-match estimation error (the moment estimate is an UPPER BOUND: it also absorbs error in spw_pre)", "calibration of the effect by surface and level", "point-level momentum (not identifiable from score strings)"], R),
        FeatureSpec(S, "ten.hold_rate_uncertainty_propagation", "team", ["hru_p66_mean_pre", "hru_p66_point_pre", "hru_jensen_pre", "hru_neff_pre", "hru_opp_neff_pre"], "PARTIAL",
                    "E[P(6-6)] over a normal approximation of the Beta posterior of each player's opponent-adjusted spw (n_eff = half-life-365 weighted serve points over 730 days, cap 4000) plus a N(0, 0.02^2) day shock, by 7x7 Gauss-Hermite quadrature; the point value at the mean spw and the difference",
                    ["opponent-adjusted spw (tennis_ext4 definition)", "n_eff 24 months half-life 1 year cap 4000", "day shock 0.02", "closed-form hold", "P(6-6) set DP", "E[p66] - p66(mean)"],
                    ["2000 Monte Carlo draws (replaced by deterministic quadrature)", "exact Beta draws (normal approximation used)"], R),
        FeatureSpec(S, "ten.player_speed_slope", "team", ["pss_cpi_pre", "pss_beta_pre", "pss_adj_rating_pre"], "PARTIAL",
                    "leave-player-out event pace index = mean match hold residual (observed hold minus both players' own pre-match hold) over the event's matches in the previous 1155 days (half-life 1 year) excluding every match of the player, shrunk to 0 by +20 rows; slope of the player's result residual (won - Elo p) on the index over the previous 730 days (linearised logistic, Gaussian prior mean 0, SD 500 Elo per unit index); adjusted rating = walk-forward Elo rating + slope x index",
                    ["leave-player-out event index", "own-baseline residuals", "ridge slope", "speed-adjusted rating"],
                    ["ace-rate component of the index", "last ~120 matches window (730 days used)", "ridge lambda ~20 matches (Gaussian prior SD 500 used)", "serve-profile prior mean for the slope (prior mean 0 used)", "field-composition correction"], R),
        FeatureSpec(S, "ten.set_dist", "team", ["sd_p2_pre", "sd_p3_pre", "sd_p4_pre", "sd_p5_pre", "sd_match_win_pre", "sd_cal_p2_pre", "sd_cal_p3_pre", "sd_cal_p4_pre", "sd_cal_p5_pre"], "PARTIAL",
                    "pmf of the number of sets and P(win) from the set DP with a latent match-form shock on each player's spw (SD = wmd_form_sd_pre, 5x5 Gauss-Hermite), and the pmf calibrated by the observed/expected ratio per tour x surface x best_of over the previous 3650 days, shrunk with 200 pseudo-matches",
                    ["Markov set model", "latent match-form shock", "calibration by tour and surface"], ["set-score (not only set-count) distribution", "calibration of match length in games", "an identified form-shock SD (wmd_form_sd_pre is an upper bound, so the shock is overstated before calibration)"], R),
        FeatureSpec(S, "ten.set_number_calibration", "team", ["snc_logit_s1_pre", "snc_off_s2_won1_pre", "snc_off_s2_lost1_pre", "snc_off_s3_level_pre", "snc_off_s4_up_pre", "snc_off_s4_down_pre", "snc_off_s5_level_pre", "snc_n_pre"], "PARTIAL",
                    "favourite's empirical set-win frequency by set index and prior-set state, per tour x best_of x 5-point edge bin of the walk-forward Elo win probability (previous 3650 days), shrunk n/(n+50) to the tour x best_of pool; logit offsets of each state vs set 1 (favourite's view)",
                    ["set index and prior-set state from score strings", "edge bins from walk-forward Elo", "n/(n+50) shrink", "offsets in logit units"], ["logistic fit with edge as a continuous term (binned frequencies used)"], R),
    ]
