#!/usr/bin/env python3
"""Blind implementation of tennis_ext6 features from blind_brief.md only."""
import re
import sys
import math
import numpy as np
import pandas as pd

SURF4 = {"Hard", "Clay", "Grass", "Carpet"}
SET_GAMES = [6, 7, 8, 9, 10, 12, 13]
TOK_RE = re.compile(r"^(\d+)-(\d+)(\(\d+\))?$")


# ----------------------------------------------------------------- helpers
def hold(p):
    p = np.asarray(p, dtype=float)
    q = 1.0 - p
    return p**4 * (1 + 4 * q + 10 * q**2) + 20 * p**3 * q**3 * p**2 / (1 - 2 * p * q)


def parse_score(score, best_of):
    """Return dict(walkover, flag, bad, sets=[(a,b),...], completed)."""
    out = dict(walkover=False, flag=False, bad=False, sets=[], completed=False)
    if not isinstance(score, str) or not score.strip():
        out["bad"] = True
        return out
    for t in score.split(" "):
        if t == "":
            continue
        if t == "W/O":
            out["walkover"] = True
            out["flag"] = True
        elif t in ("RET", "DEF"):
            out["flag"] = True
        elif t in ("ABD", "UNP"):
            out["bad"] = True
            out["flag"] = True
        else:
            m = TOK_RE.match(t)
            if not m:
                out["bad"] = True
                out["flag"] = True
            else:
                out["sets"].append((int(m.group(1)), int(m.group(2))))
    if out["flag"] or out["bad"]:
        return out
    bo = 3 if (best_of is None or (isinstance(best_of, float) and np.isnan(best_of))) else int(best_of)
    need = bo // 2 + 1
    sets = out["sets"]
    if not sets:
        return out
    wsets = sum(1 for a, b in sets if a > b)
    if wsets != need:
        return out
    for a, b in sets:
        mx, mn = max(a, b), min(a, b)
        complete = (mx >= 6 and mx - mn >= 2) or (mx == 7 and mn in (5, 6))
        if not complete or (a + b) not in SET_GAMES:
            return out
    out["completed"] = True
    return out


def set_model(hA, hB, spA=None, spB=None, want_tb=True):
    """Vectorised set model. hA/hB: hold probs of A/B. spA, spB: serve point win probs
    (for tiebreak). Returns pmf (n,7) over SET_GAMES, P(A wins set), p66 -- averaged over
    the two first-server cases."""
    hA = np.atleast_1d(np.asarray(hA, float))
    hB = np.atleast_1d(np.asarray(hB, float))
    n = hA.shape[0]
    pmf_tot = np.zeros((n, 7))
    pwin_tot = np.zeros(n)
    p66_tot = np.zeros(n)
    for first_A in (True, False):
        P = {(0, 0): np.ones(n)}
        pmf = np.zeros((n, 7))
        awin = np.zeros(n)
        p66 = np.zeros(n)
        for g in range(12):
            newP = {}
            for (i, j), pr in P.items():
                if i + j != g:
                    continue
                a_serves = (g % 2 == 0) == first_A
                pa = hA if a_serves else 1.0 - hB
                for (ni, nj, pp) in ((i + 1, j, pa), (i, j + 1, 1.0 - pa)):
                    newP[(ni, nj)] = newP.get((ni, nj), 0.0) + pr * pp
            P = {}
            for (i, j), pr in newP.items():
                tot = i + j
                if (i == 6 and j <= 4) or (i == 7 and j == 5):
                    pmf[:, SET_GAMES.index(tot)] += pr
                    awin += pr
                elif (j == 6 and i <= 4) or (j == 7 and i == 5):
                    pmf[:, SET_GAMES.index(tot)] += pr
                elif i == 6 and j == 6:
                    p66 += pr
                    pmf[:, 6] += pr
                else:
                    P[(i, j)] = pr
        if want_tb:
            tb = tiebreak(spA, spB, first_A)
            awin = awin + p66 * tb
        pmf_tot += 0.5 * pmf
        pwin_tot += 0.5 * awin
        p66_tot += 0.5 * p66
    return pmf_tot, pwin_tot, p66_tot


def tiebreak(spA, spB, first_A):
    spA = np.atleast_1d(np.asarray(spA, float))
    spB = np.atleast_1d(np.asarray(spB, float))
    n = spA.shape[0]
    P = {(0, 0): np.ones(n)}
    win = np.zeros(n)
    at66 = np.zeros(n)
    for _ in range(12):
        newP = {}
        for (a, b), pr in P.items():
            k = a + b + 1  # 1-based point number
            first_serves = ((k // 2) % 2) == 0
            a_serves = first_serves == first_A
            pa = spA if a_serves else 1.0 - spB
            for (na, nb, pp) in ((a + 1, b, pa), (a, b + 1, 1.0 - pa)):
                newP[(na, nb)] = newP.get((na, nb), 0.0) + pr * pp
        P = {}
        for (a, b), pr in newP.items():
            if a == 7 and b <= 5:
                win += pr
            elif b == 7 and a <= 5:
                pass
            elif a == 6 and b == 6:
                at66 += pr
            else:
                P[(a, b)] = pr
    x = spA * (1 - spB)
    y = (1 - spA) * spB
    return win + at66 * x / (x + y)


class Window:
    """Point-in-time windowed sums over records keyed by a hashable key."""

    def __init__(self, keys, days, vals):
        self.idx = {}
        df = pd.DataFrame({"k": list(keys), "d": np.asarray(days, float)})
        vals = [np.asarray(v, float) for v in vals]
        for k, sub in df.groupby("k", sort=False).indices.items():
            order = sub[np.argsort(df["d"].values[sub], kind="stable")]
            self.idx[k] = (df["d"].values[order], [v[order] for v in vals])

    def query(self, key, day, W, hl=None):
        if key not in self.idx:
            return None
        d, vs = self.idx[key]
        lo = np.searchsorted(d, day - W, side="left")
        hi = np.searchsorted(d, day, side="left")
        if hi <= lo:
            return None
        dd = d[lo:hi]
        if hl is None:
            w = np.ones(hi - lo)
        else:
            w = 0.5 ** ((day - dd) / hl)
        return w, [v[lo:hi] for v in vs]


# ----------------------------------------------------------------- main
def build(df):
    df = df.copy()
    df = df[df["tourney_date"].notna() & df["winner_id"].notna() & df["loser_id"].notna()].reset_index(drop=True)
    df["date"] = pd.to_datetime(df["tourney_date"].astype(np.int64).astype(str), format="%Y%m%d")
    origin = df["date"].min()
    df["day"] = (df["date"] - origin).dt.days.astype(float)
    df["tour"] = df["tour"].astype(str)

    def mn_str(x):
        try:
            fx = float(x)
            if fx.is_integer():
                return str(int(fx))
        except Exception:
            pass
        return str(x)

    base = df["tour"] + "|" + df["tourney_id"].astype(str) + "|" + df["match_num"].map(mn_str)
    k = base.groupby(base).cumcount()
    df["game_id"] = base + "|" + k.astype(str)
    df["wkey"] = df["tour"] + ":" + df["winner_id"].astype(float).astype(np.int64).astype(str)
    df["lkey"] = df["tour"] + ":" + df["loser_id"].astype(float).astype(np.int64).astype(str)

    parsed = [parse_score(s, b) for s, b in zip(df["score"], df["best_of"])]
    df["walkover"] = [p["walkover"] for p in parsed]
    df["completed"] = [p["completed"] for p in parsed]
    df["sets"] = [p["sets"] for p in parsed]
    df["n_sets"] = [len(p["sets"]) for p in parsed]
    df["bo"] = df["best_of"].fillna(3).astype(int)

    def num(c):
        return pd.to_numeric(df[c], errors="coerce")

    vs = (~df["walkover"]) & (num("w_svpt") > 0) & (num("l_svpt") > 0)
    for c in ("w_1stWon", "w_2ndWon", "l_1stWon", "l_2ndWon"):
        vs &= num(c).notna()
    df["valid_serve"] = vs.values

    # ------------------------------------------------------------- Elo
    M = len(df)
    p_w = np.full(M, np.nan)
    r_w = np.full(M, np.nan)
    r_l = np.full(M, np.nan)
    for tour, g in df.groupby("tour", sort=False):
        elo = {}
        selo = {}
        for day, gd in g.groupby("day", sort=True):
            upd_e = {}
            upd_s = {}
            for i in gd.index:
                wk, lk, surf = df.at[i, "wkey"], df.at[i, "lkey"], df.at[i, "surface"]
                ew, el = elo.get(wk, 1500.0), elo.get(lk, 1500.0)
                has_s = isinstance(surf, str) and surf in SURF4
                if has_s:
                    sw, sl = selo.get((wk, surf), 1500.0), selo.get((lk, surf), 1500.0)
                    rw, rl = (ew + sw) / 2, (el + sl) / 2
                else:
                    rw, rl = ew, el
                r_w[i], r_l[i] = rw, rl
                p_w[i] = 1 / (1 + 10 ** (-(rw - rl) / 400))
                if df.at[i, "walkover"]:
                    continue
                pe = 1 / (1 + 10 ** (-(ew - el) / 400))
                upd_e[wk] = upd_e.get(wk, 0.0) + 32 * (1 - pe)
                upd_e[lk] = upd_e.get(lk, 0.0) - 32 * (1 - pe)
                if has_s:
                    ps = 1 / (1 + 10 ** (-(sw - sl) / 400))
                    upd_s[(wk, surf)] = upd_s.get((wk, surf), 0.0) + 32 * (1 - ps)
                    upd_s[(lk, surf)] = upd_s.get((lk, surf), 0.0) - 32 * (1 - ps)
            for kk, v in upd_e.items():
                elo[kk] = elo.get(kk, 1500.0) + v
            for kk, v in upd_s.items():
                selo[kk] = selo.get(kk, 1500.0) + v
    df["p_w"] = p_w
    fav_is_w = (r_w > r_l) | ((r_w == r_l) & (df["wkey"].values < df["lkey"].values))
    df["fav_is_w"] = fav_is_w
    df["p_fav"] = np.where(fav_is_w, p_w, 1 - p_w)

    # ------------------------------------------------------------- long table
    rows = []
    for side in ("w", "l"):
        o = "l" if side == "w" else "w"
        t = pd.DataFrame({
            "mi": np.arange(M),
            "game_id": df["game_id"].values,
            "team": df[side + "key"].values,
            "opp": df[o + "key"].values,
            "tour": df["tour"].values,
            "day": df["day"].values,
            "won": 1.0 if side == "w" else 0.0,
            "p_win": p_w if side == "w" else 1 - p_w,
            "rating": r_w if side == "w" else r_l,
            "valid_serve": df["valid_serve"].values,
            "svpt": num(side + "_svpt").values,
            "sw": (num(side + "_1stWon") + num(side + "_2ndWon")).values,
            "o_svpt": num(o + "_svpt").values,
            "o_sw": (num(o + "_1stWon") + num(o + "_2ndWon")).values,
            "SvGms": num(side + "_SvGms").values,
            "bpF": num(side + "_bpFaced").values,
            "bpS": num(side + "_bpSaved").values,
        })
        rows.append(t)
    L = pd.concat(rows, ignore_index=True)
    # order: per match, winner row then loser row
    L = L.sort_values(["mi", "won"], ascending=[True, False], kind="stable").reset_index(drop=True)
    N = len(L)
    L["s_won"] = np.where(L.valid_serve, L.sw, np.nan)
    L["s_pts"] = np.where(L.valid_serve, L.svpt, np.nan)
    L["r_won"] = np.where(L.valid_serve, L.o_svpt - L.o_sw, np.nan)
    L["r_pts"] = np.where(L.valid_serve, L.o_svpt, np.nan)
    V = L[L.valid_serve]

    # ------------------------------------------------------------- spw
    wp = Window(V.team, V.day, [V.s_won, V.s_pts, V.r_won, V.r_pts])
    wt = Window(V.tour, V.day, [V.s_won, V.s_pts])
    sp = np.full(N, np.nan)
    rr = np.full(N, np.nan)
    tt = np.full(N, np.nan)
    neff = np.zeros(N)
    cache_t = {}
    for i in range(N):
        team, day, tour = L.team.iat[i], L.day.iat[i], L.tour.iat[i]
        q = wp.query(team, day, 1095, 365)
        if q is not None:
            w, (a, b, c, d) = q
            if (w * b).sum() > 0:
                sp[i] = (w * a).sum() / (w * b).sum()
            if (w * d).sum() > 0:
                rr[i] = (w * c).sum() / (w * d).sum()
        q = wp.query(team, day, 730, 365)
        if q is not None:
            w, (a, b, c, d) = q
            neff[i] = min((w * b).sum(), 4000.0)
        kt = (tour, day)
        if kt not in cache_t:
            q = wt.query(tour, day, 1095)
            v = np.nan
            if q is not None:
                _, (a, b) = q
                if b.sum() > 0:
                    v = a.sum() / b.sum()
            cache_t[kt] = v
        tt[i] = cache_t[kt]
    L["sp"], L["rr"], L["t"], L["hru_neff_pre"] = sp, rr, tt, neff
    # opponent = the other row of the same match
    partner = np.arange(N) ^ 1  # rows are paired (2m, 2m+1)
    assert (L.mi.values[partner] == L.mi.values).all()
    opp_rr = rr[partner]
    spw = np.clip(sp + (opp_rr - (1 - tt)), 0.30, 0.90)
    L["spw"] = spw
    L["o_spw"] = spw[partner]
    L["hru_opp_neff_pre"] = neff[partner]
    both = ~np.isnan(L.spw.values) & ~np.isnan(L.o_spw.values)

    # ------------------------------------------------------------- 1. wmd
    win_rows = np.where(L.won.values == 1)[0]  # one per match
    mi_of = L.mi.values
    # match-level contributions
    mrec = []
    wr_both = win_rows[both[win_rows]]
    if len(wr_both):
        sA = L.spw.values[wr_both]
        sB = L.o_spw.values[wr_both]
        pmf, _, _ = set_model(hold(sA), hold(sB), want_tb=False)
        pmf = pmf / pmf.sum(1, keepdims=True)
        g = np.array(SET_GAMES, float)
        mu = (pmf * g).sum(1)
        var = (pmf * (g - mu[:, None]) ** 2).sum(1)
        for j, r in enumerate(wr_both):
            m = mi_of[r]
            if not df.at[m, "completed"]:
                continue
            games = np.array([a + b for a, b in df.at[m, "sets"]], float)
            mrec.append(((df.at[m, "tour"], df.at[m, "bo"]), df.at[m, "day"],
                         ((games - mu[j]) ** 2).sum(), len(games) * var[j], len(games)))
    if mrec:
        ww = Window([r[0] for r in mrec], [r[1] for r in mrec],
                    [[r[2] for r in mrec], [r[3] for r in mrec], [r[4] for r in mrec]])
    od = np.full(N, np.nan)
    ns = np.zeros(N)
    for i in range(N):
        m = mi_of[i]
        q = ww.query((df.at[m, "tour"], df.at[m, "bo"]), L.day.iat[i], 1095) if mrec else None
        if q is not None:
            _, (ssr, sv, nn) = q
            ns[i] = nn.sum()
            if sv.sum() != 0:
                od[i] = ssr.sum() / sv.sum()
    L["wmd_overdisp_pre"], L["wmd_n_sets_pre"] = od, ns

    fmask = L.valid_serve.values & ~np.isnan(L.spw.values)
    F = L[fmask]
    dev = F.s_won / F.s_pts - F.spw
    binv = F.spw * (1 - F.spw) / F.s_pts
    wf = Window(F.tour, F.day, [dev, binv])
    fsd = np.full(N, np.nan)
    cache = {}
    for i in range(N):
        kt = (L.tour.iat[i], L.day.iat[i])
        if kt not in cache:
            q = wf.query(kt[0], kt[1], 1095)
            v = np.nan
            if q is not None:
                _, (dv, bv) = q
                if len(dv) >= 30:
                    tau2 = np.mean(dv**2 - bv) - np.mean(dv) ** 2
                    v = math.sqrt(max(tau2, 0.0))
            cache[kt] = v
        fsd[i] = cache[kt]
    L["wmd_form_sd_pre"] = fsd

    # ------------------------------------------------------------- 2. hru
    x7, w7 = np.polynomial.hermite_e.hermegauss(7)
    w7 = w7 / w7.sum()
    neffA = L.hru_neff_pre.values
    neffB = L.hru_opp_neff_pre.values
    dmask = both & (neffA > 0) & (neffB > 0)
    idx = np.where(dmask)[0]
    L["hru_p66_mean_pre"] = np.nan
    L["hru_p66_point_pre"] = np.nan
    L["hru_jensen_pre"] = np.nan
    if len(idx):
        sA, sB = L.spw.values[idx], L.o_spw.values[idx]
        sdA = np.sqrt(sA * (1 - sA) / (neffA[idx] + 1) + 0.02**2)
        sdB = np.sqrt(sB * (1 - sB) / (neffB[idx] + 1) + 0.02**2)
        mean = np.zeros(len(idx))
        for xi, wi in zip(x7, w7):
            for xj, wj in zip(x7, w7):
                A = np.clip(sA + sdA * xi, 0.30, 0.90)
                B = np.clip(sB + sdB * xj, 0.30, 0.90)
                _, _, p66 = set_model(hold(A), hold(B), want_tb=False)
                mean += wi * wj * p66
        _, _, point = set_model(hold(sA), hold(sB), want_tb=False)
        L.loc[idx, "hru_p66_mean_pre"] = mean
        L.loc[idx, "hru_p66_point_pre"] = point
        L.loc[idx, "hru_jensen_pre"] = mean - point

    # ------------------------------------------------------------- 3. pss
    with np.errstate(divide="ignore", invalid="ignore"):
        obs = 1 - (L.bpF.values - L.bpS.values) / L.SvGms.values
    obs[~(L.SvGms.values > 0)] = np.nan  # 0 or missing SvGms -> NaN
    resid = np.where(both, obs - hold(L.spw.values), np.nan)
    pair = np.stack([resid, resid[partner]], 1)
    cnt = (~np.isnan(pair)).sum(1)
    msum = np.nansum(pair, 1)
    m_res = np.where(cnt > 0, msum / np.maximum(cnt, 1), np.nan)
    L["m_res"] = m_res
    ev = (df["tour"] + "|" + df["tourney_name"].astype(str).str.strip().str.lower()).values
    L["event"] = ev[mi_of]
    R = L[~np.isnan(m_res)]
    we = Window(R.event, R.day, [R.m_res])
    wpe = Window(list(zip(R.event, R.team)), R.day, [R.m_res])
    cpi = np.full(N, np.nan)
    for i in range(N):
        e, day, team = L.event.iat[i], L.day.iat[i], L.team.iat[i]
        q = we.query(e, day, 1155, 365)
        if q is None:
            continue
        w, (mm,) = q
        Se, Ce = (w * mm).sum(), w.sum()
        if Ce == 0:
            continue
        q = wpe.query((e, team), day, 1155, 365)
        Sp = Cp = 0.0
        if q is not None:
            w2, (m2,) = q
            Sp, Cp = (w2 * m2).sum(), w2.sum()
        cpi[i] = (Se - 2 * Sp) / (max(Ce - 2 * Cp, 0.0) + 20)
    L["pss_cpi_pre"] = cpi
    pw = L.p_win.values
    gx = pw * (1 - pw) * math.log(10) / 400 * cpi
    y = L.won.values - pw
    G = ~np.isnan(gx)
    wb = Window(L.team.values[G], L.day.values[G], [gx[G], y[G]])
    beta = np.full(N, np.nan)
    for i in range(N):
        q = wb.query(L.team.iat[i], L.day.iat[i], 730)
        if q is None:
            continue
        _, (gg, yy) = q
        if len(gg) >= 10:
            beta[i] = (gg * yy).sum() / ((gg**2).sum() + 0.25 / 500**2)
    L["pss_beta_pre"] = beta
    L["pss_adj_rating_pre"] = L.rating.values + beta * cpi

    # ------------------------------------------------------------- 4. set_dist
    x5, w5 = np.polynomial.hermite_e.hermegauss(5)
    w5 = w5 / w5.sum()
    tau = L.wmd_form_sd_pre.values
    bo_row = df["bo"].values[mi_of]
    sdcols = ["sd_p2_pre", "sd_p3_pre", "sd_p4_pre", "sd_p5_pre", "sd_match_win_pre"]
    for c in sdcols:
        L[c] = np.nan
    smask = both & ~np.isnan(tau)
    idx = np.where(smask)[0]
    Pk = np.full((N, 4), np.nan)
    if len(idx):
        sA, sB, tu, bo = L.spw.values[idx], L.o_spw.values[idx], tau[idx], bo_row[idx]
        acc = np.zeros((len(idx), 5))
        for xi, wi in zip(x5, w5):
            for xj, wj in zip(x5, w5):
                A = np.clip(sA + tu * xi, 0.30, 0.90)
                B = np.clip(sB + tu * xj, 0.30, 0.90)
                _, w, _ = set_model(hold(A), hold(B), A, B, want_tb=True)
                l = 1 - w
                P = np.zeros((len(idx), 5))
                b3 = bo != 5
                P[b3, 0] = w[b3] ** 2 + l[b3] ** 2
                P[b3, 1] = 1 - P[b3, 0]
                P[b3, 4] = w[b3] ** 2 * (1 + 2 * l[b3])
                b5 = bo == 5
                P[b5, 1] = w[b5] ** 3 + l[b5] ** 3
                P[b5, 2] = 3 * (w[b5] ** 3 * l[b5] + l[b5] ** 3 * w[b5])
                P[b5, 3] = 1 - P[b5, 1] - P[b5, 2]
                P[b5, 4] = w[b5] ** 3 * (1 + 3 * l[b5] + 6 * l[b5] ** 2)
                acc += wi * wj * P
        for c_i, c in enumerate(sdcols):
            L.loc[idx, c] = acc[:, c_i]
        Pk[idx] = acc[:, :4]
    surf = df["surface"].fillna("NA").astype(str).values
    crec = []
    for r in win_rows:
        m = mi_of[r]
        if not df.at[m, "completed"] or np.isnan(Pk[r, 0]):
            continue
        n_s = df.at[m, "n_sets"]
        O = [1.0 if n_s == kk else 0.0 for kk in (2, 3, 4, 5)]
        crec.append(((df.at[m, "tour"], surf[m], df.at[m, "bo"]), df.at[m, "day"], O, Pk[r]))
    if crec:
        wc = Window([c[0] for c in crec], [c[1] for c in crec],
                    [[c[2][j] for c in crec] for j in range(4)] + [[c[3][j] for c in crec] for j in range(4)])
    cal = np.full((N, 4), np.nan)
    for i in idx:
        m = mi_of[i]
        O = np.zeros(4)
        E = np.zeros(4)
        q = wc.query((df.at[m, "tour"], surf[m], df.at[m, "bo"]), L.day.iat[i], 3650) if crec else None
        if q is not None:
            _, vals = q
            O = np.array([v.sum() for v in vals[:4]])
            E = np.array([v.sum() for v in vals[4:]])
        ratio = (O + 200) / (E + 200)
        c = Pk[i] * ratio
        cal[i] = c / c.sum()
    for j, kk in enumerate((2, 3, 4, 5)):
        L[f"sd_cal_p{kk}_pre"] = cal[:, j]

    # ------------------------------------------------------------- 5. snc
    states = [(1, 0), (2, 1), (2, -1), (3, 0), (4, 1), (4, -1), (5, 0)]
    snames = ["s1", "s2_won1", "s2_lost1", "s3_level", "s4_up", "s4_down", "s5_level"]
    ebin = np.minimum(((df["p_fav"].values - 0.5) * 20).astype(int), 4)
    df["ebin"] = ebin
    srec = {s: [] for s in states}  # list of (cellkey, poolkey, day, indicator)
    for m in range(M):
        if not df.at[m, "completed"]:
            continue
        fw = df.at[m, "fav_is_w"]
        diff = 0
        for sn, (a, b) in enumerate(df.at[m, "sets"], start=1):
            fav_won = (a > b) if fw else (b > a)
            st = (sn, diff)
            if st in srec:
                tb = (df.at[m, "tour"], df.at[m, "bo"])
                srec[st].append((tb + (ebin[m],), tb, df.at[m, "day"], 1.0 if fav_won else 0.0))
            diff += 1 if fav_won else -1
    wcell, wpool = {}, {}
    for s in states:
        recs = srec[s]
        if recs:
            wcell[s] = Window([r[0] for r in recs], [r[2] for r in recs], [[r[3] for r in recs]])
            wpool[s] = Window([r[1] for r in recs], [r[2] for r in recs], [[r[3] for r in recs]])
    # compute per match (same for both rows)
    mf = np.full((M, len(states)), np.nan)
    mn1 = np.zeros(M)
    for m in range(M):
        tb = (df.at[m, "tour"], df.at[m, "bo"])
        ck = tb + (ebin[m],)
        day = df.at[m, "day"]
        for si, s in enumerate(states):
            if s not in wcell:
                continue
            qp = wpool[s].query(tb, day, 3650)
            if qp is None:
                if si == 0:
                    qc = wcell[s].query(ck, day, 3650)
                    mn1[m] = 0 if qc is None else len(qc[0])
                continue
            pool_mean = qp[1][0].mean()
            qc = wcell[s].query(ck, day, 3650)
            n = 0 if qc is None else len(qc[0])
            if si == 0:
                mn1[m] = n
            if n > 0:
                f = (n / (n + 50)) * qc[1][0].mean() + (50 / (n + 50)) * pool_mean
            else:
                f = pool_mean
            f = min(max(f, 1e-4), 1 - 1e-4)
            mf[m, si] = math.log(f / (1 - f))
    lg = mf[mi_of]
    L["snc_logit_s1_pre"] = lg[:, 0]
    for si in range(1, len(states)):
        v = lg[:, si] - lg[:, 0]
        if snames[si] in ("s4_up", "s4_down", "s5_level"):
            v = np.where(bo_row == 5, v, np.nan)
        L[f"snc_off_{snames[si]}_pre"] = v
    L["snc_n_pre"] = mn1[mi_of]

    cols = ["game_id", "team",
            "wmd_overdisp_pre", "wmd_form_sd_pre", "wmd_n_sets_pre",
            "hru_p66_mean_pre", "hru_p66_point_pre", "hru_jensen_pre", "hru_neff_pre", "hru_opp_neff_pre",
            "pss_cpi_pre", "pss_beta_pre", "pss_adj_rating_pre",
            "sd_p2_pre", "sd_p3_pre", "sd_p4_pre", "sd_p5_pre", "sd_match_win_pre",
            "sd_cal_p2_pre", "sd_cal_p3_pre", "sd_cal_p4_pre", "sd_cal_p5_pre",
            "snc_logit_s1_pre"] + [f"snc_off_{s}_pre" for s in snames[1:]] + ["snc_n_pre"]
    return L[cols]


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    out = build(pd.read_csv(src))
    out.to_csv(dst, index=False)
    print(len(out))
    print(out.notna().sum().to_string())
