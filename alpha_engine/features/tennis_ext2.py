"""Tennis builders from the Sackmann ATP/WTA match archive (RESEARCH_ONLY; data CC BY-NC-SA 4.0 per the upstream README: non-commercial research use only).

Sackmann stamps every match of a tournament with the tournament START date (``tourney_date``) and the order of matches inside it is a convention, so every builder here is date-batched: a match's features use ONLY matches whose tourney_date is
STRICTLY EARLIER than its own tourney_date (nothing from the same tournament, nothing from the same date). Player key = tour:id (ids collide across the two files). Output table ``team`` has one row per (match, player); match-level
columns (cell statistics) are identical for the two rows of a match.

Walk-forward Elo (the "pre-match rating" the catalog inputs call for): K=32, start 1500, overall rating and per-surface rating (Hard/Clay/Grass/Carpet), updated in tourney_date batches (every match of a date sees the same pre-batch ratings; walkovers
are not updated; retirements are). Combined rating r = (elo + elo_surface)/2 (elo if the surface is unknown); p = 1/(1+10^(-(rA-rB)/400)); favourite = higher r (tie: smaller player key string).
"""
from __future__ import annotations

import glob
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec

S = "TENNIS"
COLS = ["tourney_id", "tourney_name", "tourney_date", "surface", "tourney_level", "best_of", "round", "match_num", "winner_id", "loser_id", "winner_ioc", "loser_ioc", "winner_seed", "loser_seed", "score",
        "w_ace", "l_ace", "w_svpt", "l_svpt", "w_SvGms", "l_SvGms", "w_bpFaced", "w_bpSaved", "l_bpFaced", "l_bpSaved"]
CONTENT = ["score", "winner_id", "loser_id", "w_ace", "l_ace", "w_svpt", "l_svpt", "w_SvGms", "l_SvGms", "w_bpFaced", "w_bpSaved", "l_bpFaced", "l_bpSaved", "winner_seed", "loser_seed"]
SURF = ("Hard", "Clay", "Grass", "Carpet")
ROUND_IDX = {"R128": 1, "R64": 2, "R32": 3, "R16": 4, "QF": 5, "SF": 6, "F": 7}
ROUND_GROUP = {"R128": "early", "R64": "early", "R32": "early", "R16": "mid", "QF": "mid", "SF": "late", "F": "late", "RR": "late", "BR": "late"}
HOST = {"Australian Open": "AUS", "Roland Garros": "FRA", "French Open": "FRA", "Wimbledon": "GBR", "US Open": "USA"}
DAY = np.timedelta64(1, "D")


def load_raw(tennis_dir) -> dict:
    fs = sorted(glob.glob(str(Path(tennis_dir) / "[aw]t[pa]_matches_20*.csv.gz")))
    d = pd.concat([pd.read_csv(f, usecols=lambda c: c in COLS, low_memory=False).assign(tour=Path(f).name[:3]) for f in fs], ignore_index=True)
    d = d.dropna(subset=["tourney_date", "winner_id", "loser_id"]).copy()
    d["date"] = pd.to_datetime(d.tourney_date.astype(int).astype(str), format="%Y%m%d", errors="coerce"); d = d.dropna(subset=["date"])
    for c in COLS:
        if c not in d: d[c] = np.nan
    d["game_id"] = d.tour + "|" + d.tourney_id.astype(str) + "|" + d.match_num.astype(str)
    d["game_id"] = d.game_id + "|" + d.groupby("game_id").cumcount().astype(str)
    d["season"] = d.date.dt.year
    return {"matches": d[["game_id", "tour", "date", "season"] + COLS].reset_index(drop=True)}


# ------------------------------------------------------------------ score parsing
SET_RE = re.compile(r"^(\d+)-(\d+)(?:\(\d+\))?$")


def _parse(score) -> tuple:
    """-> (sets[(w,l)...] for parsable tokens, flag) flag in {'', 'RET', 'DEF', 'WO', 'BAD'}"""
    if not isinstance(score, str) or not score.strip(): return [], "BAD"
    s = score.strip()
    if "W/O" in s: return [], "WO"
    flag = ""
    if "RET" in s: flag = "RET"
    elif "DEF" in s: flag = "DEF"
    elif "ABD" in s or "UNP" in s: flag = "BAD"
    toks = [t for t in s.split() if t not in ("RET", "DEF", "ABD", "UNP")]
    sets = []
    for t in toks:
        m = SET_RE.match(t)
        if not m: return [], "BAD"
        sets.append((int(m.group(1)), int(m.group(2))))
    return sets, flag


def _complete_set(a: int, b: int) -> bool:
    hi, lo = max(a, b), min(a, b)
    return (hi >= 6 and hi - lo >= 2) or (hi == 7 and lo in (5, 6))


def _match_outcome(score, best_of) -> dict:
    sets, flag = _parse(score); out = dict(ok=False, ret=False, n_sets=np.nan, straight=np.nan, decider=np.nan, dropped=np.nan, d_w=np.nan, tb=np.nan, comp_sets=np.nan, gw=np.nan, gl=np.nan, interrupted=np.nan)
    if flag in ("WO", "BAD") or not sets: return out
    if flag in ("RET", "DEF"):
        comp = sum(_complete_set(a, b) for a, b in sets)
        gw = sum(a for a, b in sets); gl = sum(b for a, b in sets)
        out.update(ret=True, comp_sets=comp, gw=gw, gl=gl, d_w=gw - gl); return out
    need = int(best_of) // 2 + 1 if not pd.isna(best_of) else 2
    ws = sum(a > b for a, b in sets); ls = sum(b > a for a, b in sets)
    if max(ws, ls) != need or not all(_complete_set(a, b) for a, b in sets): return out
    gw = sum(a for a, b in sets); gl = sum(b for a, b in sets)
    out.update(ok=True, n_sets=len(sets), straight=float(ls == 0), decider=float(len(sets) == int(best_of)), dropped=float(ls > 0), d_w=gw - gl, tb=float(any(max(a, b) == 7 and min(a, b) == 6 for a, b in sets)), gw=gw, gl=gl)
    return out


# ------------------------------------------------------------------ windowed group sums (strictly earlier dates)
def _wsum(keys: pd.DataFrame, dates: np.ndarray, vals: np.ndarray, win_days: float | None, hl_days: float | None = None):
    """For each row: per-column (sum, count) of the NON-NaN values of rows with the SAME key and date strictly earlier (and, if win_days, within win_days before). hl_days: weight 0.5**(age/hl)."""
    N, V = vals.shape; S_ = np.zeros((N, V)); C_ = np.zeros((N, V))
    d = dates.astype("datetime64[D]").astype(np.int64).astype(float)
    kid = keys.groupby(list(keys.columns), sort=False, dropna=False).ngroup().to_numpy()
    order = np.lexsort((d, kid)); ks = kid[order]; bounds = np.flatnonzero(np.r_[True, ks[1:] != ks[:-1], True])
    for a, b in zip(bounds[:-1], bounds[1:]):
        idx = order[a:b]; dd = d[idx]; v = vals[idx]; ok = ~np.isnan(v); z = np.where(ok, v, 0.0)
        if hl_days:
            base = dd.min(); w = 2.0 ** ((dd - base) / hl_days); cs = np.vstack([np.zeros((1, V)), np.cumsum(z * w[:, None], axis=0)]); cc = np.vstack([np.zeros((1, V)), np.cumsum(ok * w[:, None], axis=0)])
        else:
            cs = np.vstack([np.zeros((1, V)), np.cumsum(z, axis=0)]); cc = np.vstack([np.zeros((1, V)), np.cumsum(ok.astype(float), axis=0)])
        hi = np.searchsorted(dd, dd, side="left"); lo = np.searchsorted(dd, dd - win_days, side="left") if win_days else np.zeros(len(dd), int)
        s = cs[hi] - cs[lo]; c = cc[hi] - cc[lo]
        if hl_days: sc = 2.0 ** (-(dd - base) / hl_days); s, c = s * sc[:, None], c * sc[:, None]
        S_[idx], C_[idx] = s, c
    return S_, C_


def _shrunk(cell_s, cell_c, pool_s, pool_c, k):
    """(n*cell_mean + k*pool_mean)/(n+k)  with n = cell count; NaN if the pool is empty."""
    cm = np.where(cell_c > 0, cell_s / np.where(cell_c > 0, cell_c, 1), np.nan); pm = np.where(pool_c > 0, pool_s / np.where(pool_c > 0, pool_c, 1), np.nan)
    w = cell_c / (cell_c + k)
    return np.where(np.isnan(pm), np.nan, np.where(cell_c > 0, w * cm + (1 - w) * pm, pm))


# ------------------------------------------------------------------ Elo
def _elo(m: pd.DataFrame) -> pd.DataFrame:
    m = m.sort_values(["tour", "date", "tourney_id", "match_num", "game_id"], kind="mergesort").reset_index(drop=True)
    e: dict = {}; es: dict = {}; cnt: dict = {}
    n = len(m); ew = np.full(n, np.nan); el = np.full(n, np.nan); sw = np.full(n, np.nan); sl = np.full(n, np.nan); nw = np.zeros(n); nl = np.zeros(n)
    wk = (m.tour + ":" + m.winner_id.astype(int).astype(str)).to_numpy(); lk = (m.tour + ":" + m.loser_id.astype(int).astype(str)).to_numpy(); sf = m.surface.to_numpy(); wo = m.score.astype(str).str.contains("W/O", regex=False).to_numpy()
    key = (m.tour.astype(str) + "|" + m.date.dt.strftime("%Y%m%d")).to_numpy()                 # m is sorted by (tour, date): process contiguous (tour, date) runs strictly in that order
    cuts = np.flatnonzero(np.r_[True, key[1:] != key[:-1], True])
    for a0, b0 in zip(cuts[:-1], cuts[1:]):
        ix = range(a0, b0)
        d_e: dict = {}; d_s: dict = {}; d_c: dict = {}
        for i in ix:
            a, b = wk[i], lk[i]; s = sf[i] if isinstance(sf[i], str) and sf[i] in SURF else None
            ew[i], el[i] = e.get(a, 1500.0), e.get(b, 1500.0); nw[i], nl[i] = cnt.get(a, 0), cnt.get(b, 0)
            if s: sw[i], sl[i] = es.get((a, s), 1500.0), es.get((b, s), 1500.0)
            if wo[i]: continue
            p = 1 / (1 + 10 ** (-(ew[i] - el[i]) / 400)); dl = 32 * (1 - p); d_e[a] = d_e.get(a, 0) + dl; d_e[b] = d_e.get(b, 0) - dl
            if s:
                ps = 1 / (1 + 10 ** (-(sw[i] - sl[i]) / 400)); ds = 32 * (1 - ps); d_s[(a, s)] = d_s.get((a, s), 0) + ds; d_s[(b, s)] = d_s.get((b, s), 0) - ds
            d_c[a] = d_c.get(a, 0) + 1; d_c[b] = d_c.get(b, 0) + 1
        for k, v in d_e.items(): e[k] = e.get(k, 1500.0) + v
        for k, v in d_s.items(): es[k] = es.get(k, 1500.0) + v
        for k, v in d_c.items(): cnt[k] = cnt.get(k, 0) + v
    m["elo_w"], m["elo_l"], m["selo_w"], m["selo_l"], m["n_w"], m["n_l"] = ew, el, sw, sl, nw, nl
    m["wkey"], m["lkey"] = wk, lk
    rw = np.where(np.isnan(sw), ew, 0.5 * (ew + sw)); rl = np.where(np.isnan(sl), el, 0.5 * (el + sl))
    m["p_w"] = 1 / (1 + 10 ** (-(rw - rl) / 400))                      # pre-match probability of the player who WON (outcome-free quantity: pre-match ratings only)
    fav_is_w = (rw > rl) | ((rw == rl) & (wk < lk)); m["fav_is_w"] = fav_is_w
    m["p_fav"] = np.where(fav_is_w, m.p_w, 1 - m.p_w); m["bin"] = np.minimum((m.p_fav * 20).astype(int), 19)
    m["p_win_bin"] = np.minimum((m.p_w * 20).astype(int), 19)
    return m


def compute(raw: dict) -> dict:
    m = _elo(raw["matches"].copy())
    oc = pd.DataFrame([_match_outcome(s, b) for s, b in zip(m.score, m.best_of)], index=m.index); m = pd.concat([m, oc], axis=1)
    m["fav_won"] = m.fav_is_w.astype(float); dd = m.date.to_numpy()
    # ---- fav-view margin (completed matches only)
    m["d_fav"] = np.where(m.fav_is_w, m.d_w, -m.d_w); m["ok_f"] = m.ok.astype(float).where(m.ok)
    ok = m.ok.to_numpy()
    def mask(cols):
        return np.column_stack([np.where(ok, m[c].to_numpy(float), np.nan) for c in cols])
    # straight_set_share_curve: cell = tour,best_of,surface,bin ; pool = tour,best_of,surface ; window 10 years ; shrink n/(n+40)
    base_keys = ["tour", "best_of", "surface"]
    sv = np.column_stack([mask(["straight", "decider"]), np.where(ok & m.fav_is_w.to_numpy(), m.straight.to_numpy(float), np.nan)])
    cs, cc = _wsum(m[base_keys + ["bin"]], dd, sv, 3650); ps_, pc = _wsum(m[base_keys], dd, sv, 3650)
    for j, nm in enumerate(["ssc_straight_pre", "ssc_decider_pre", "ssc_straight_given_favwin_pre"]):
        m[nm] = _shrunk(cs[:, j], cc[:, j], ps_[:, j], pc[:, j], 40)
    m["ssc_n_pre"] = cc[:, 0]
    # set_count_distribution_by_edge: pmf of the number of sets
    nsv = np.column_stack([np.where(ok, (m.n_sets.to_numpy(float) == k).astype(float), np.nan) for k in (2, 3, 4, 5)] + [mask(["n_sets"])[:, 0]])
    cs, cc = _wsum(m[base_keys + ["bin"]], dd, nsv, 3650); ps_, pc = _wsum(m[base_keys], dd, nsv, 3650)
    for j, nm in enumerate(["scd_p2_pre", "scd_p3_pre", "scd_p4_pre", "scd_p5_pre", "scd_mean_sets_pre"]): m[nm] = _shrunk(cs[:, j], cc[:, j], ps_[:, j], pc[:, j], 40)
    # game_margin_pmf_calibration: D from the FAVOURITE's view
    d_ = np.where(ok, m.d_fav.to_numpy(float), np.nan)
    gv = np.column_stack([d_] + [np.where(ok, (m.d_fav.to_numpy(float) > k).astype(float), np.nan) for k in (1.5, 3.5, 5.5, 7.5)])
    cs, cc = _wsum(m[base_keys + ["bin"]], dd, gv, 3650); ps_, pc = _wsum(m[base_keys], dd, gv, 3650)
    for j, nm in enumerate(["gmc_mean_d_pre", "gmc_p_gt15_pre", "gmc_p_gt35_pre", "gmc_p_gt55_pre", "gmc_p_gt75_pre"]): m[nm] = _shrunk(cs[:, j], cc[:, j], ps_[:, j], pc[:, j], 50)
    # win_margin_conversion_curve: given the WINNER, cell = tour,best_of,bin ; pool = tour,best_of ; shrink n/(n+60)
    dw = m.d_w.to_numpy(float)
    wv = np.column_stack([np.where(ok, (dw > k).astype(float), np.nan) for k in (1.5, 3.5, 5.5)] + [np.where(ok, (dw < 0).astype(float), np.nan)])
    cs, cc = _wsum(m[["tour", "best_of", "bin"]], dd, wv, 3650); ps_, pc = _wsum(m[["tour", "best_of"]], dd, wv, 3650)
    for j, nm in enumerate(["wmc_p_gt15_pre", "wmc_p_gt35_pre", "wmc_p_gt55_pre", "wmc_p_neg_pre"]): m[nm] = _shrunk(cs[:, j], cc[:, j], ps_[:, j], pc[:, j], 60)
    # ---- retirements
    ret = m.ret.to_numpy(bool); rg = m["round"].map(ROUND_GROUP).fillna("late"); m["rgroup"] = rg
    trail = np.where(ret, (m.gl.to_numpy(float) < m.gw.to_numpy(float)).astype(float), np.nan)        # retiring player = loser: trailing means loser games < winner games
    cs_ = m.comp_sets.to_numpy(float)
    rv = np.column_stack([np.where(ret, (cs_ == 0).astype(float), np.nan), np.where(ret, (cs_ <= 1).astype(float), np.nan), np.where(ret, (cs_ <= 2).astype(float), np.nan), trail,
                          np.where(ret, (m.gw + m.gl).to_numpy(float), np.nan), np.where(ret, (m.d_w.to_numpy(float) > 1.5).astype(float), np.nan)])
    cs, cc = _wsum(m[["tour", "best_of", "rgroup"]], dd, rv, None); ps_, pc = _wsum(m[["tour"]], dd, rv, None)
    for j, nm in enumerate(["rtp_p_before_set1_pre", "rtp_p_before_set2_pre", "rtp_p_before_set3_pre", "rtp_p_retiree_trailing_pre", "rtp_mean_games_pre", "rtp_p_d_gt15_pre"]): m[nm] = _shrunk(cs[:, j], cc[:, j], ps_[:, j], pc[:, j], 30)
    # retirement_margin_state: D (non-retiring minus retiring player) at stoppage by tour and by WHICH player retired (the favourite or the underdog); retiring player = loser
    ret_fav = np.where(ret, (~m.fav_is_w.to_numpy()).astype(float), np.nan)                        # loser is the favourite iff the winner is not
    dv = m.d_w.to_numpy(float)
    rm = np.column_stack([np.where(ret & (ret_fav == 1), (dv > 1.5).astype(float), np.nan), np.where(ret & (ret_fav == 0), (dv > 1.5).astype(float), np.nan), np.where(ret & (ret_fav == 1), dv, np.nan), np.where(ret & (ret_fav == 0), dv, np.nan),
                          np.where(ret, (dv > 1.5).astype(float), np.nan)])
    cs, cc = _wsum(m[["tour"]], dd, rm, None)
    for j, nm in enumerate(["rms_p_gt15_fav_retires_pre", "rms_p_gt15_dog_retires_pre", "rms_mean_d_fav_retires_pre", "rms_mean_d_dog_retires_pre"]):
        pool_s, pool_c = cs[:, 4], cc[:, 4]                                                         # pooled tour value of P(D>1.5 | retirement)
        m[nm] = _shrunk(cs[:, j], cc[:, j], pool_s, pool_c, 30) if "gt15" in nm else np.where(cc[:, j] > 0, cs[:, j] / np.where(cc[:, j] > 0, cc[:, j], 1), np.nan)
    # ---- event-level: tiebreak_base_rate_by_event (3 editions ~ 1095 days, half-life 18 months ~ 548 days, shrink n_eff/(n_eff+60) to the tour+best_of rate over the same window unweighted)
    ev = np.column_stack([mask(["tb"])[:, 0], np.where(ok, m.straight.to_numpy(float), np.nan)])
    es_, ec = _wsum(m[["tour", "tourney_name"]], dd, ev, 1095, hl_days=548.0); ts, tc = _wsum(m[["tour", "best_of"]], dd, ev, 1095)
    tr = np.where(tc > 0, ts / np.where(tc > 0, tc, 1), np.nan)
    for j, nm in enumerate(["tbe_tb_rate_pre", "tbe_ss_rate_pre"]):
        ne = ec[:, j]; er = np.where(ne > 0, es_[:, j] / np.where(ne > 0, ne, 1), np.nan)
        m[nm] = np.where(ne > 0, (ne * er + 60 * tr[:, j]) / (ne + 60), tr[:, j])
    m["tbe_n_eff_pre"] = ec[:, 0]
    # venue_speed_history: event vs tour-surface over the previous 3 years (window 1095 days, unweighted), shrunk n/(n+100) to 0
    aces = (m.w_ace + m.l_ace).to_numpy(float); svpt = (m.w_svpt + m.l_svpt).to_numpy(float); svg = (m.w_SvGms + m.l_SvGms).to_numpy(float)
    bpl = (m.w_bpFaced - m.w_bpSaved + m.l_bpFaced - m.l_bpSaved).to_numpy(float)
    gok = ok & ~np.isnan(m.gw.to_numpy(float)); tg = np.where(gok, (m.gw + m.gl).to_numpy(float), np.nan)
    sv = np.column_stack([np.where(svpt > 0, aces, np.nan), np.where(svpt > 0, svpt, np.nan), np.where(svg > 0, bpl, np.nan), np.where(svg > 0, svg, np.nan), mask(["tb"])[:, 0], tg])
    es_, ec = _wsum(m[["tour", "tourney_name"]], dd, sv, 1095); ts, tc = _wsum(m[["tour", "surface"]], dd, sv, 1095)
    def ratio(s, c): return np.where((c[:, 1] > 0), s[:, 0] / np.where(c[:, 1] > 0, s[:, 1], 1), np.nan)
    ev_ace = np.where(es_[:, 1] > 0, es_[:, 0] / np.where(es_[:, 1] > 0, es_[:, 1], 1), np.nan); ts_ace = np.where(ts[:, 1] > 0, ts[:, 0] / np.where(ts[:, 1] > 0, ts[:, 1], 1), np.nan)
    ev_hold = np.where(es_[:, 3] > 0, 1 - es_[:, 2] / np.where(es_[:, 3] > 0, es_[:, 3], 1), np.nan); ts_hold = np.where(ts[:, 3] > 0, 1 - ts[:, 2] / np.where(ts[:, 3] > 0, ts[:, 3], 1), np.nan)
    ev_tb = np.where(ec[:, 4] > 0, es_[:, 4] / np.where(ec[:, 4] > 0, ec[:, 4], 1), np.nan); ts_tb = np.where(tc[:, 4] > 0, ts[:, 4] / np.where(tc[:, 4] > 0, tc[:, 4], 1), np.nan)
    ev_g = np.where(ec[:, 5] > 0, es_[:, 5] / np.where(ec[:, 5] > 0, ec[:, 5], 1), np.nan); ts_g = np.where(tc[:, 5] > 0, ts[:, 5] / np.where(tc[:, 5] > 0, tc[:, 5], 1), np.nan)
    nsv = ec[:, 1] / 1.0                                                                          # event serve points in window (n for the shrink weights below uses matches)
    n_m = ec[:, 4]
    w = n_m / (n_m + 100)
    m["vsh_ace_dev_pre"] = w * (ev_ace - ts_ace); m["vsh_hold_dev_pre"] = w * (ev_hold - ts_hold); m["vsh_tb_dev_pre"] = w * (ev_tb - ts_tb); m["vsh_games_dev_pre"] = w * (ev_g - ts_g); m["vsh_n_pre"] = n_m
    # ---- majors
    m = _majors(m)
    # ---- player_set_drop_propensity and round_upset_calibration
    m = _drop_upset(m)
    # ---- to team rows
    rows = []
    cols = [c for sp in specs() for c in sp.columns]
    for side, key in (("w", "wkey"), ("l", "lkey")):
        r = m[["game_id", "date", "season"] + [c for c in cols if c in m.columns]].copy(); r["team"] = m[key]
        for c in PLAYER_COLS:
            if f"{c}_{side}" in m: r[c] = m[f"{c}_{side}"]
        rows.append(r)
    out = pd.concat(rows, ignore_index=True)
    out = out[["game_id", "team", "date", "season"] + cols]
    out = out.loc[:, ~out.columns.duplicated()]
    return {"team": out.loc[:, ~out.columns.duplicated()].sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


PLAYER_COLS = ["mwc_player_share_pre", "s2s_prev_champ", "hsdp_home", "psd_resid_pre", "psd_n_pre"] + [f"hsdp_nat_{x}_pre" for x in ("r16", "qf", "sf", "f")]


def _majors(m: pd.DataFrame) -> pd.DataFrame:
    g = m[m.tourney_level == "G"]
    ed = g.groupby(["tour", "tourney_id"]).agg(start=("date", "first"), name=("tourney_name", "first"), surface=("surface", "first")).reset_index().sort_values(["tour", "start", "tourney_id"], kind="mergesort")
    fin = g[g["round"] == "F"].drop_duplicates(["tour", "tourney_id"]).set_index(["tour", "tourney_id"])
    ed["champ"] = [fin.wkey.get((t, i), None) if (t, i) in fin.index else None for t, i in zip(ed.tour, ed.tourney_id)]
    ed["done"] = ed.start + pd.Timedelta(days=15)
    # round reached per (edition, nation): max round index of any player of the nation (round of loss, 8 = champion)
    reach: dict = {}
    for r in g.itertuples():
        ri = ROUND_IDX.get(r._asdict()["round"], 0)
        for ioc, idx in ((r.winner_ioc, ri + (1 if r._asdict()["round"] == "F" else 0)), (r.loser_ioc, ri)):
            if isinstance(ioc, str): k = (r.tour, r.tourney_id, ioc); reach[k] = max(reach.get(k, 0), idx)
    n = len(m); hhi = np.full(n, np.nan); top2 = np.full(n, np.nan); nmaj = np.zeros(n); share_w = np.zeros(n); share_l = np.zeros(n)
    prev_w = np.zeros(n); prev_l = np.zeros(n); rep = np.full(n, np.nan); repn = np.zeros(n); gapb = np.full(n, np.nan); schg = np.full(n, np.nan)
    hs = {k: np.full(n, np.nan) for k in ("r16", "qf", "sf", "f")}; hs_l = {k: np.full(n, np.nan) for k in ("r16", "qf", "sf", "f")}; home_w = np.zeros(n); home_l = np.zeros(n)
    THR = {"r16": 4, "qf": 5, "sf": 6, "f": 7}
    byt = {t: d.reset_index(drop=True) for t, d in ed.groupby("tour")}
    for t, idx in m.groupby("tour").indices.items():
        e = byt.get(t)
        if e is None: continue
        done = e.done.to_numpy(); starts = e.start.to_numpy()
        for dte in np.unique(m.date.to_numpy()[idx]):
            sel = idx[m.date.to_numpy()[idx] == dte]; k = int(np.searchsorted(done, dte, side="left"))     # majors with done < date
            last = e.iloc[max(0, k - 12):k][::-1]
            if len(last):
                w = 0.9 ** np.arange(len(last)); sh: dict = {}
                for c, wi in zip(last.champ, w):
                    if isinstance(c, str): sh[c] = sh.get(c, 0) + wi
                tot = w.sum(); shares = {c: v / tot for c, v in sh.items()}; v = sorted(shares.values(), reverse=True)
                hhi[sel] = sum(x * x for x in v); top2[sel] = sum(v[:2]); nmaj[sel] = len(last)
                share_w[sel] = [shares.get(x, 0.0) for x in m.wkey.to_numpy()[sel]]; share_l[sel] = [shares.get(x, 0.0) for x in m.lkey.to_numpy()[sel]]
            # carry-over (matches at a major): previous major's champion, gap bucket, surface change, historical repeat rate by gap bucket over pairs completed before this date
            if k >= 1:
                pv = e.iloc[k - 1]
                prev_w[sel] = (m.wkey.to_numpy()[sel] == pv.champ).astype(float); prev_l[sel] = (m.lkey.to_numpy()[sel] == pv.champ).astype(float)
                # pairs (e_i-1, e_i) with e_i complete before date
                reps = {1: [0, 0], 2: [0, 0], 3: [0, 0]}
                for i in range(1, k):
                    gap = (e.start.iloc[i] - (e.start.iloc[i - 1] + pd.Timedelta(days=13))).days; b = 1 if gap <= 21 else (2 if gap <= 42 else 3)
                    reps[b][0] += int(e.champ.iloc[i] is not None and e.champ.iloc[i] == e.champ.iloc[i - 1]); reps[b][1] += 1
                allr = sum(v[0] for v in reps.values()); alln = sum(v[1] for v in reps.values())
                is_major = (m.tourney_level.to_numpy()[sel] == "G")
                # gap bucket of THIS event relative to the previous major: only meaningful for matches at a major whose start == date
                cur = np.flatnonzero(starts == dte)
                if len(cur) and cur[0] >= 1:
                    j = int(cur[0]); gap = (e.start.iloc[j] - (e.start.iloc[j - 1] + pd.Timedelta(days=13))).days; b = 1 if gap <= 21 else (2 if gap <= 42 else 3)
                    pv = e.iloc[j - 1]; prev_w[sel] = (m.wkey.to_numpy()[sel] == pv.champ).astype(float); prev_l[sel] = (m.lkey.to_numpy()[sel] == pv.champ).astype(float)
                    n_b, r_b = reps[b][1], reps[b][0]; pooled = (allr / alln) if alln else np.nan
                    val = (r_b + 8 * pooled) / (n_b + 8) if alln else np.nan
                    rep[sel] = np.where(is_major, val, np.nan); repn[sel] = np.where(is_major, n_b, 0); gapb[sel] = np.where(is_major, b, np.nan); schg[sel] = np.where(is_major, float(e.surface.iloc[j] != e.surface.iloc[j - 1]), np.nan)
                else:
                    prev_w[sel] = 0; prev_l[sel] = 0
            # home-slam depth: only for matches at a major
            cur = np.flatnonzero(starts == dte)
            if len(cur):
                j = int(cur[0]); name = e.name.iloc[j]; host = next((v for kk, v in HOST.items() if kk in str(name)), None)
                past = [i for i in range(j) if next((v for kk, v in HOST.items() if kk in str(e.name.iloc[i])), None) == host and done[i] < dte][-15:] if host else []
                if past:
                    ages = np.array([(dte - starts[i]) / np.timedelta64(365, "D") for i in past], float); wt = 0.5 ** (ages / 6.0)
                    def freq(nat, thr): return float((wt * np.array([float(reach.get((t, e.tourney_id.iloc[i], nat), 0) >= thr) for i in past])).sum() / wt.sum())
                    for side, ioc_arr, dst in (("w", m.winner_ioc.to_numpy()[sel], hs), ("l", m.loser_ioc.to_numpy()[sel], hs_l)):
                        for kk, thr in THR.items():
                            vals = np.array([freq(x, thr) if isinstance(x, str) else np.nan for x in ioc_arr]); dst[kk][sel] = vals
                if host:
                    home_w[sel] = (m.winner_ioc.to_numpy()[sel] == host).astype(float); home_l[sel] = (m.loser_ioc.to_numpy()[sel] == host).astype(float)
    m["mwc_hhi_pre"], m["mwc_top2_pre"], m["mwc_n_pre"], m["mwc_player_share_pre_w"], m["mwc_player_share_pre_l"] = hhi, top2, nmaj, share_w, share_l
    m["s2s_prev_champ_w"], m["s2s_prev_champ_l"] = prev_w, prev_l
    m["s2s_repeat_rate_pre"], m["s2s_n_pairs_pre"], m["s2s_gap_bucket"], m["s2s_surface_change"] = rep, repn, gapb, schg
    for kk in THR: m[f"hsdp_nat_{kk}_pre_w"], m[f"hsdp_nat_{kk}_pre_l"] = hs[kk], hs_l[kk]
    m["hsdp_home_w"], m["hsdp_home_l"] = home_w, home_l
    return m


def _drop_upset(m: pd.DataFrame) -> pd.DataFrame:
    dd = m.date.to_numpy(); ok = m.ok.to_numpy()
    # expected straight-set win given the winner's pre-match win-probability bin (tour, best_of, bin), 10-year window, over completed matches
    v = np.where(ok, m.straight.to_numpy(float), np.nan)[:, None]
    s_, c_ = _wsum(m[["tour", "best_of", "p_win_bin"]], dd, v, 3650)
    m["exp_ss"] = np.where(c_[:, 0] > 0, s_[:, 0] / np.where(c_[:, 0] > 0, c_[:, 0], 1), np.nan)
    m["res_ss"] = np.where(ok, m.straight.to_numpy(float) - m.exp_ss.to_numpy(float), np.nan)
    # per player: last 60 wins strictly before this tourney_date, weights 0.5**(age/365), shrink n/(n+25) to 0
    wk = m.wkey.to_numpy(); dn = m.date.to_numpy().astype("datetime64[D]").astype(np.int64).astype(float); res = m.res_ss.to_numpy(float)
    order = np.lexsort((np.arange(len(m)), dn)); psd = {}
    pre = {}; npre = {}
    by_p: dict = {}
    for i in order:
        if not np.isnan(res[i]): by_p.setdefault(wk[i], []).append((dn[i], res[i]))
    out_v = np.full(len(m), np.nan); out_n = np.full(len(m), np.nan)
    def lookup(key, d):
        L = by_p.get(key)
        if not L: return np.nan, 0
        ds = np.array([x[0] for x in L]); rs = np.array([x[1] for x in L]); hi = np.searchsorted(ds, d, side="left"); lo = max(0, hi - 60)
        if hi - lo == 0: return np.nan, 0
        w = 0.5 ** ((d - ds[lo:hi]) / 365.0); n = hi - lo
        return float((w * rs[lo:hi]).sum() / w.sum()) * n / (n + 25), n
    ps_w = [lookup(k, d) for k, d in zip(wk, dn)]; lk = m.lkey.to_numpy(); ps_l = [lookup(k, d) for k, d in zip(lk, dn)]
    m["psd_resid_pre_w"] = [x[0] for x in ps_w]; m["psd_n_pre_w"] = [x[1] for x in ps_w]; m["psd_resid_pre_l"] = [x[0] for x in ps_l]; m["psd_n_pre_l"] = [x[1] for x in ps_l]
    # round_upset_calibration: favourite's win frequency minus Elo-implied p, by (tour, round, seed-difference bin), 10-year window, shrink n/(n+100) to 0
    sw = pd.to_numeric(m.winner_seed, errors="coerce"); sl = pd.to_numeric(m.loser_seed, errors="coerce")
    diff = (sw - sl).abs(); sb = np.where(sw.notna() & sl.notna(), np.where(diff <= 3, "d1-3", np.where(diff <= 8, "d4-8", "d9+")), np.where(sw.notna() | sl.notna(), "one", "none")); m["seed_bin"] = sb
    r = np.where(ok | m.ret.to_numpy(bool), (m.fav_is_w.astype(float) - m.p_fav).to_numpy(float), np.nan)[:, None]
    s_, c_ = _wsum(m[["tour", "round", "seed_bin"]].astype(str), dd, r, 3650)
    m["rup_resid_pre"] = np.where(c_[:, 0] > 0, s_[:, 0] / np.where(c_[:, 0] > 0, c_[:, 0], 1) * c_[:, 0] / (c_[:, 0] + 100), np.nan); m["rup_n_pre"] = c_[:, 0]
    return m


def perturb(raw: dict, ids, seed: int, content=None) -> dict:
    """Replay perturbation for tennis: on the games in `ids` flip the winner/loser roles of a random half (all paired winner_/loser_ and w_/l_ columns swap, so the SET of players of each match is unchanged and the row universe stays identical),
    then permute the remaining content columns (score, serve statistics) among those games."""
    rng = np.random.default_rng(seed); m = raw["matches"].copy(); ix = np.flatnonzero(m.game_id.isin(ids).to_numpy())
    fl = ix[rng.random(len(ix)) < 0.5]
    pairs = [("winner_id", "loser_id"), ("winner_ioc", "loser_ioc"), ("winner_seed", "loser_seed")] + [(f"w_{c}", f"l_{c}") for c in ("ace", "svpt", "1stIn", "2ndWon", "SvGms", "bpFaced", "bpSaved")]
    for a, b in pairs:
        if a in m and b in m:
            va, vb = m[a].to_numpy(dtype=object, copy=True), m[b].to_numpy(dtype=object, copy=True); va[fl], vb[fl] = vb[fl].copy(), va[fl].copy()
            for c, v in ((a, va), (b, vb)):
                try: m[c] = pd.Series(v, index=m.index).astype(raw["matches"][c].dtype)
                except (TypeError, ValueError): m[c] = pd.Series(v, index=m.index)
    for c in (content if content is not None else ["score", "w_ace", "l_ace", "w_svpt", "l_svpt", "w_SvGms", "l_SvGms", "w_bpFaced", "w_bpSaved", "l_bpFaced", "l_bpSaved"]):
        if c in m:
            v = m[c].to_numpy(dtype=object, copy=True); v[ix] = rng.permutation(v[ix])
            try: m[c] = pd.Series(v, index=m.index).astype(raw["matches"][c].dtype)
            except (TypeError, ValueError): m[c] = pd.Series(v, index=m.index)
    return {**raw, "matches": m}


def perturb_nv(raw: dict, ids, seed: int) -> dict:
    """Stronger perturbation used ONLY by the non-vacuity check (do the features respond to data of an early block at all?): additionally shuffles the pre-match KEY columns (round, nations, surface, level) of the block's games. It is never used by the leak tests,
    because permuting a match's own key columns changes its own cell, which is not a leak."""
    return perturb(raw, ids, seed, ["score", "round", "winner_ioc", "loser_ioc", "surface", "tourney_level", "w_ace", "l_ace", "w_svpt", "l_svpt", "w_SvGms", "l_SvGms", "w_bpFaced", "w_bpSaved", "l_bpFaced", "l_bpSaved"])


def specs() -> list[FeatureSpec]:
    F = lambda cid, cols, lvl, d, done, miss: FeatureSpec(S, cid, "team", cols, lvl, d, done, miss, ["sackmann_atp_wta_matches"], "pregame_rolling")
    return [
        F("ten.straight_set_share_curve", ["ssc_straight_pre", "ssc_decider_pre", "ssc_straight_given_favwin_pre", "ssc_n_pre"], "PARTIAL", "share of matches won in straight sets / reaching a decider, and P(straight | favourite wins), by 5-point bin of the favourite's walk-forward Elo win probability x tour x best_of x surface over the previous 10 years, shrunk n/(n+40) to the tour x best_of x surface pool",
          ["5-point bins by tour, best_of, surface", "10-year history", "n/(n+40) shrink", "P(2-0|A wins) and P(decider)"], ["logistic-fit shrink target (pooled share used instead)"]),
        F("ten.set_count_distribution_by_edge", ["scd_p2_pre", "scd_p3_pre", "scd_p4_pre", "scd_p5_pre", "scd_mean_sets_pre"], "PARTIAL", "pmf of number of sets by the same bins, shrunk n/(n+40) to the pool; retirements excluded",
          ["empirical P(N sets) per bin", "n/(n+40) shrink", "retirements excluded"], ["monotone logistic fit in logit(p) as the shrink target"]),
        F("ten.game_margin_pmf_calibration", ["gmc_mean_d_pre", "gmc_p_gt15_pre", "gmc_p_gt35_pre", "gmc_p_gt55_pre", "gmc_p_gt75_pre"], "PARTIAL", "mean and P(D>k) for k=1.5,3.5,5.5,7.5 of the favourite's game margin D by bin x tour x best_of x surface, shrunk n/(n+50) to the pool",
          ["D from the favourite's view", "walk-forward Elo bins", "half-integer P(D>k)", "n/(n+50) shrink"], ["Gaussian kernel over adjacent bins", "discretised-normal fit on logit(p) as the shrink target", "full pmf at every integer"]),
        F("ten.win_margin_conversion_curve", ["wmc_p_gt15_pre", "wmc_p_gt35_pre", "wmc_p_gt55_pre", "wmc_p_neg_pre"], "PARTIAL", "P(D>k | winner) for k=1.5,3.5,5.5 and P(D<0 | winner) by edge bin x tour x best_of, shrunk n/(n+60) to the tour x best_of pool",
          ["P(D>k|winner)", "P(D<0|winner)", "edge bins from walk-forward Elo", "n/(n+60) shrink"], ["logistic fit in edge", "surface- and pace-adjusted Elo variant of the edge", "combination with the match-winner model"]),
        F("ten.retirement_timing_profile", ["rtp_p_before_set1_pre", "rtp_p_before_set2_pre", "rtp_p_before_set3_pre", "rtp_p_retiree_trailing_pre", "rtp_mean_games_pre", "rtp_p_d_gt15_pre"], "PARTIAL", "RET/DEF matches by tour x best_of x round group (early/mid/late): P(retire before completing set 1/2/3), P(retiring player trailing in games), mean total games completed, P(D>1.5), shrunk n/(n+30) to the tour pool",
          ["completed sets", "retiring player = loser", "set-completion probabilities", "trailing share", "games distribution mean", "P(D>1.5)", "n/(n+30) shrink"], ["P(count>k) for every strike k", "explicit censoring flag for missing interrupted-set scores"]),
        F("ten.retirement_margin_state", ["rms_p_gt15_fav_retires_pre", "rms_p_gt15_dog_retires_pre", "rms_mean_d_fav_retires_pre", "rms_mean_d_dog_retires_pre"], "PARTIAL", "game margin at retirement (non-retiring minus retiring player) by tour and by whether the favourite or the underdog retired, P(D>1.5 | retirement) shrunk n/(n+30) to the tour pool",
          ["D at retirement", "by tour and which player retired", "P(D>1.5|retirement)", "n/(n+30) shrink"], ["censoring of rows without a partial score"]),
        F("ten.tiebreak_base_rate_by_event", ["tbe_tb_rate_pre", "tbe_ss_rate_pre", "tbe_n_eff_pre"], "PARTIAL", "event tiebreak share and straight-set win share over the previous 3 editions (1095 days) with half-life 18 months, shrunk n_eff/(n_eff+60) to the tour x best_of rate",
          ["last three editions", "half-life 18 months", "n/(n+60) shrink to tour rate"], ["split by round and best_of (best_of enters only the tour-rate prior)"]),
        F("ten.venue_speed_history", ["vsh_ace_dev_pre", "vsh_hold_dev_pre", "vsh_tb_dev_pre", "vsh_games_dev_pre", "vsh_n_pre"], "PARTIAL", "event ace%, hold%, tiebreak% and mean total games over the previous 3 years minus the tour-surface averages over the same window, shrunk n/(n+100) toward 0",
          ["event vs tour-surface deviations", "ace%, hold%, tiebreak%, mean total games"], ["shrink toward the previous-year event effect", "continuous speed index"]),
        F("ten.major_winner_concentration", ["mwc_hhi_pre", "mwc_top2_pre", "mwc_player_share_pre"], "FULL", "Herfindahl index and top-2 share of the last 12 majors' champions per tour with edition weights 0.9^k (k=0 most recent), a major counting only once 15 days after its start date have passed, and the player's own history-implied share",
          ["HHI", "top-2 share", "last 12 majors", "edition decay", "history-implied player shares", "update after each major"], []),
        F("ten.slam_to_slam_carryover", ["s2s_repeat_rate_pre", "s2s_n_pairs_pre", "s2s_gap_bucket", "s2s_surface_change", "s2s_prev_champ"], "PARTIAL", "for matches at a major: gap bucket (<=21, 22-42, >42 days between the previous major's final day and this start), surface change, whether the row's player won the previous major, and the earlier same-tour repeat-title rate for that bucket shrunk n/(n+8) to the pooled repeat rate",
          ["consecutive-major pairs", "gap buckets", "surface change", "n/(n+8) shrink"], ["ratio to the product of marginal title probabilities", "shrink toward the model-implied ratio"]),
        F("ten.home_slam_depth_prior", ["hsdp_nat_r16_pre", "hsdp_nat_qf_pre", "hsdp_nat_sf_pre", "hsdp_nat_f_pre", "hsdp_home"], "FULL", "for matches at a major: frequency over the last 15 editions of that major (same tour) with half-life 6 years that at least one player of the row player's nation reached R16/QF/SF/F, plus host-nation flag",
          ["R16/QF/SF/F frequencies", "last 15 editions", "half-life 6 years", "by tour and major"], []),
        F("ten.player_set_drop_propensity", ["psd_resid_pre", "psd_n_pre"], "PARTIAL", "player's straight-set-win share minus the expectation given the win-probability bin of the win (tour x best_of, 10 years), over the last 60 wins with half-life 365 days, shrunk n/(n+25) to 0",
          ["last 60 wins", "half-life 12 months", "n/(n+25) shrink", "expectation given opponent rating"], ["split-sample persistence test", "round and format terms"]),
        F("ten.round_upset_calibration", ["rup_resid_pre", "rup_n_pre"], "PARTIAL", "favourite's win frequency minus Elo-implied probability by tour x round x seed-difference bin over 10 years, shrunk n/(n+100) to 0",
          ["round and seed bins", "favourite residual vs Elo", "n/(n+100) shrink"], ["logistic correction with round dummies"]),
    ]
