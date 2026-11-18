"""Point-in-time plate-appearance rate engine (Phase 14 MLB challenger).

Walks game dates in order. For each date D it FIRST emits predictions/features from accumulators that hold only
data from dates < D, THEN adds date D's plate appearances. Time is measured in game-days (dates with games), so the
off-season does not decay information; a separate `carry` factor regresses player history at each season boundary.

Rates: batter / pitcher outcome vectors (8 classes) shrunk per outcome toward league (stabilisation constants x
`k_mult`), handed splits shrunk toward overall x league platoon ratio (`k_pl`), combined by the multinomial
odds-ratio (generalised log5) against the league rate of the same stand/throws cell, then park (team home/road
ratio, shrunk with `k_park`) and home-field multipliers on the odds scale, renormalised to sum 1.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NC = 8
# stabilisation points (PA/BF) per outcome K, BB, HBP, 1B, 2B, 3B, HR, OUT (Carleton-style, rounded)
K_BAT = np.array([60, 120, 240, 290, 1600, 1600, 170, 400], float)
K_PIT = np.array([70, 170, 640, 670, 1450, 1450, 1320, 600], float)

DEFAULTS = dict(tau=240.0, tau_lg=120.0, tau_park=900.0, carry=0.8, k_mult_bat=1.0, k_mult_pit=1.0, k_pl=250.0,
                k_park=3000.0, k_bp=800.0, k_def=1e9, tau_bf=60.0, k_bf=3.0, home_adv=True, typical_n=7)


def odds(x):
    x = np.clip(x, 1e-6, 1 - 1e-6)
    return x / (1 - x)


def combine(b, p, lg, mult):
    """Generalised log5 on odds scale; all arrays (..., 8); mult = park*home odds multipliers."""
    o = odds(b) * odds(p) / odds(lg) * mult
    q = o / (1 + o)
    return q / q.sum(-1, keepdims=True)


class Engine:
    def __init__(self, games: pd.DataFrame, pa: pd.DataFrame, params: dict | None = None):
        self.p = {**DEFAULTS, **(params or {})}
        self.G = games.reset_index(drop=True)
        self.PA = pa
        ids = pd.Index(pd.unique(np.concatenate([pa.bat.values, pa.pit.values,
                                                 np.concatenate(self.G.home_order.values),
                                                 np.concatenate(self.G.away_order.values),
                                                 self.G.home_sp.values, self.G.away_sp.values]).astype(np.int64)))
        self.ids = ids
        teams = pd.Index(sorted(set(self.G.home_id) | set(self.G.away_id)))
        self.teams = teams
        n, t = len(ids), len(teams)
        z = lambda *s: np.zeros(s)
        self.bat, self.bat_h = z(n, NC), z(n, 2, NC)   # batter counts overall / vs pitcher hand (0=R,1=L)
        self.pit, self.pit_h = z(n, NC), z(n, 2, NC)   # pitcher counts overall / vs batter stand
        self.bp, self.rel = z(t, NC), z(NC)            # team bullpen counts, league reliever counts
        self.tdef = z(t, NC)                           # all PAs vs team defence (balls-in-play mix)
        self.ph, self.pr = z(t, NC), z(t, NC)          # park: team home-game counts / road-game counts
        self.lg, self.lgc, self.lgha = z(NC), z(2, 2, NC), z(2, NC)  # league, [stand,throws], [home?]
        self.bf_s, self.bf_n, self.lg_bf = z(n), z(n), np.array([22.0, 1.0])
        self.typical: dict[int, list] = {}

    # ---------- rate snapshots (use current accumulators only) ----------
    def _lg(self):
        return (self.lg + 1e-3) / (self.lg.sum() + 8e-3)

    def _cell(self):
        c = self.lgc + 1e-3
        return c / c.sum(-1, keepdims=True)

    def rates(self, b_idx, stand, p_idx, throws, home_bat, team_def, use_bp=False):
        """Vectorised PA outcome probabilities. stand/throws 0=R 1=L arrays; home_bat bool array."""
        p = self.p
        lg = self._lg()
        cell = self._cell()[stand, throws]                  # (m,8)
        ratio = cell / lg
        kb, kp, kpl = K_BAT * p["k_mult_bat"], K_PIT * p["k_mult_pit"], p["k_pl"]
        cb = self.bat[b_idx]
        b_over = (cb + kb * lg) / (cb.sum(-1, keepdims=True) + kb)
        cbh = self.bat_h[b_idx, throws]
        b_h = (cbh + kpl * b_over * ratio) / (cbh.sum(-1, keepdims=True) + kpl)
        if use_bp:
            rel = (self.rel + 1e-3) / (self.rel.sum() + 8e-3)
            cpb = self.bp[team_def]
            p_over = (cpb + p["k_bp"] * rel) / (cpb.sum(-1, keepdims=True) + p["k_bp"])
            p_h = p_over * ratio
            p_h = p_h / p_h.sum(-1, keepdims=True)
        else:
            cp = self.pit[p_idx]
            p_over = (cp + kp * lg) / (cp.sum(-1, keepdims=True) + kp)
            cph = self.pit_h[p_idx, stand]
            p_h = (cph + kpl * p_over * ratio) / (cph.sum(-1, keepdims=True) + kpl)
        return b_h, p_h, cell

    def park_mult(self, home_team):
        lg = self._lg()
        cr = self.pr[home_team]
        road = (cr + 2000 * lg) / (cr.sum(-1, keepdims=True) + 2000)
        ch = self.ph[home_team]
        k = self.p["k_park"]
        home = (ch + k * road) / (ch.sum(-1, keepdims=True) + k)
        return odds(home) / odds(road)

    def home_mult(self, home_bat):
        lgha = (self.lgha + 1e-3) / (self.lgha.sum(-1, keepdims=True) + 8e-3)  # [away?0/home1]
        lg = self._lg()
        m = odds(lgha) / odds(lg)
        if not self.p["home_adv"]:
            m = np.ones_like(m)
        return m[home_bat.astype(int)]

    def pa_probs(self, b_idx, stand, p_idx, throws, home_bat, home_team, def_team, use_bp=None):
        b_h, p_h, cell = self.rates(b_idx, stand, p_idx, throws, home_bat, def_team)
        if use_bp is not None and use_bp.any():
            _, pb, _ = self.rates(b_idx, stand, p_idx, throws, home_bat, def_team, use_bp=True)
            p_h = np.where(use_bp[:, None], pb, p_h)
        mult = self.park_mult(home_team) * self.home_mult(home_bat) * self.def_mult(def_team)
        return combine(b_h, p_h, cell, mult)

    def def_mult(self, def_team):
        """Team defence on balls in play: shrunk team BIP outcome mix (1B,2B,3B,OUT) vs league, odds ratio."""
        bip = np.array([0, 0, 0, 1, 1, 1, 0, 1], bool)
        lg = self.lg * bip + 1e-3
        lg = lg / lg.sum()
        c = self.tdef[def_team] * bip
        k = self.p["k_def"]
        team = (c + k * lg) / (c.sum(-1, keepdims=True) + k)
        m = odds(np.where(bip, team, 0.5)) / odds(np.where(bip, lg, 0.5))
        return m

    def bf_mean(self, p_idx):
        lgm = self.lg_bf[0] / max(self.lg_bf[1], 1e-9)
        k = self.p["k_bf"]
        return (self.bf_s[p_idx] + k * lgm) / (self.bf_n[p_idx] + k)

    # ---------- updates ----------
    def decay(self, season_break: bool):
        p = self.p
        f = np.exp(-1.0 / p["tau"])
        if season_break:
            f *= p["carry"]
        for a in (self.bat, self.bat_h, self.pit, self.pit_h, self.bp, self.tdef):
            a *= f
        fl = np.exp(-1.0 / p["tau_lg"])
        for a in (self.lg, self.lgc, self.lgha, self.rel):
            a *= fl
        fp = np.exp(-1.0 / p["tau_park"])
        self.ph *= fp
        self.pr *= fp
        fb = np.exp(-1.0 / p["tau_bf"]) * (p["carry"] if season_break else 1.0)
        self.bf_s *= fb
        self.bf_n *= fb
        self.lg_bf *= fl

    def update(self, d: dict):
        """d: arrays for one date's PAs (indices pre-mapped)."""
        oh = np.eye(NC)[d["ev"]]
        np.add.at(self.bat, d["b"], oh)
        np.add.at(self.bat_h, (d["b"], d["throws"]), oh)
        np.add.at(self.pit, d["p"], oh)
        np.add.at(self.pit_h, (d["p"], d["stand"]), oh)
        rel = ~d["is_sp"]
        np.add.at(self.bp, d["def_team"][rel], oh[rel])
        np.add.at(self.tdef, d["def_team"], oh)
        self.rel += oh[rel].sum(0)
        self.lg += oh.sum(0)
        np.add.at(self.lgc, (d["stand"], d["throws"]), oh)
        np.add.at(self.lgha, d["home_bat"].astype(int), oh)
        np.add.at(self.ph, d["home_team"], oh)
        np.add.at(self.pr, d["away_team"], oh)


def hand01(s):
    return (np.asarray(s) == "L").astype(np.int64)


def prepare_pa(eng: Engine, pa: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    g = games.set_index("game_pk")
    pa = pa.copy()
    pa["b"] = eng.ids.get_indexer(pa.bat.values)
    pa["p"] = eng.ids.get_indexer(pa.pit.values)
    pa["stand01"] = hand01(pa.stand)
    pa["throws01"] = hand01(pa.throws)
    pa["home_bat"] = ~pa.top.values
    ht = g.loc[pa.game_pk, "home_id"].values
    at = g.loc[pa.game_pk, "away_id"].values
    pa["home_team"] = eng.teams.get_indexer(ht)
    pa["away_team"] = eng.teams.get_indexer(at)
    pa["def_team"] = eng.teams.get_indexer(pa.pit_team.values)
    pa["off_team"] = eng.teams.get_indexer(pa.bat_team.values)
    return pa


def bat_side(bats: str, throws01: int) -> int:
    if bats == "S":
        return 1 - throws01  # switch hitter bats opposite the pitcher's hand
    return 1 if bats == "L" else 0


def run(games: pd.DataFrame, pa: pd.DataFrame, params: dict | None = None, want_pa_probs: bool = True,
        want_game_inputs: bool = True, bats_lookup: dict | None = None):
    """Single chronological pass. Returns (pa_prob array aligned to `pa` rows or None, game_inputs dict per game_pk)."""
    eng = Engine(games, pa, params)
    P = prepare_pa(eng, pa, games)
    G = eng.G
    dates = np.array(sorted(set(G.date)))
    pa_by_date = {k: v.index.values for k, v in P.groupby("date")}
    g_by_date = {k: v.index.values for k, v in G.groupby("date")}
    out_probs = np.full((len(P), NC), np.nan) if want_pa_probs else None
    cols = {c: P[c].values for c in ("b", "p", "stand01", "throws01", "home_bat", "home_team", "away_team",
                                     "def_team", "ev", "is_sp")}
    inputs = {}
    sp_tab = {}
    prev_season = None
    for d in dates:
        season = int(d[:4])
        eng.decay(season_break=(prev_season is not None and season != prev_season))
        prev_season = season
        ix = pa_by_date.get(d, np.array([], int))
        # ----- predictions from strictly-earlier data -----
        if want_pa_probs and len(ix):
            out_probs[ix] = eng.pa_probs(cols["b"][ix], cols["stand01"][ix], cols["p"][ix], cols["throws01"][ix],
                                         cols["home_bat"][ix], cols["home_team"][ix], cols["def_team"][ix],
                                         use_bp=None)
        if want_game_inputs:
            for gi in g_by_date[d]:
                inputs[G.game_pk[gi]] = game_inputs(eng, G.iloc[gi], bats_lookup or {})
        # ----- then learn from date d -----
        if len(ix):
            eng.update({"b": cols["b"][ix], "p": cols["p"][ix], "stand": cols["stand01"][ix],
                        "throws": cols["throws01"][ix], "home_bat": cols["home_bat"][ix],
                        "home_team": cols["home_team"][ix], "away_team": cols["away_team"][ix],
                        "def_team": cols["def_team"][ix], "ev": cols["ev"][ix], "is_sp": cols["is_sp"][ix]})
        for gi in g_by_date[d]:
            row = G.iloc[gi]
            for side in ("home", "away"):
                eng.typical.setdefault(int(row[f"{side}_id"]), []).append(list(row[f"{side}_order"]))
                bf = row.get(f"{side}_sp_bf")
                if bf is not None and not np.isnan(bf):
                    pi = eng.ids.get_loc(int(row[f"{side}_sp"]))
                    eng.bf_s[pi] += bf
                    eng.bf_n[pi] += 1
                    eng.lg_bf += np.array([bf, 1.0])
    return out_probs, inputs, eng


def typical_lineup(history: list, n: int) -> list:
    """Pregame-safe lineup: 9 batters with most starts over the team's last n games, ordered by mean slot."""
    recent = history[-n:]
    if not recent:
        return []
    cnt, slot = {}, {}
    for j, order in enumerate(recent):
        w = 1.0 + 0.01 * j  # tie-break toward recent
        for s, pid in enumerate(order):
            cnt[pid] = cnt.get(pid, 0) + w
            slot.setdefault(pid, []).append(s)
    top = sorted(cnt, key=lambda x: -cnt[x])[:9]
    return sorted(top, key=lambda x: np.mean(slot[x]))


def game_inputs(eng: Engine, row, bats_lookup: dict) -> dict:
    """Per-side 9x8 PA probabilities vs starter and vs bullpen, for posted and pregame-typical lineups."""
    out = {}
    home_team = eng.teams.get_loc(int(row.home_id))
    for side, opp in (("home", "away"), ("away", "home")):
        sp = int(row[f"{opp}_sp"])
        thr = 1 if row[f"thr_{opp}_sp"] == "L" else 0
        def_team = eng.teams.get_loc(int(row[f"{opp}_id"]))
        res = {"bf_mu": float(eng.bf_mean(np.array([eng.ids.get_loc(sp)]))[0]), "sp": sp}
        posted = list(row[f"{side}_order"])
        typ = typical_lineup(eng.typical.get(int(row[f"{side}_id"]), []), eng.p["typical_n"]) or posted
        for name, lineup in (("posted", posted), ("typical", typ)):
            bi = eng.ids.get_indexer(lineup)
            bi = np.where(bi < 0, 0, bi)
            stand = np.array([bat_side(bats_lookup.get(pid, "R"), thr) for pid in lineup])
            m = len(lineup)
            hb = np.full(m, side == "home")
            pi = np.full(m, eng.ids.get_loc(sp))
            ht = np.full(m, home_team)
            dt = np.full(m, def_team)
            thr_a = np.full(m, thr)
            vs_sp = eng.pa_probs(bi, stand, pi, thr_a, hb, ht, dt)
            vs_bp = eng.pa_probs(bi, stand, pi, thr_a, hb, ht, dt, use_bp=np.ones(m, bool))
            res[name] = {"lineup": lineup, "sp": vs_sp.astype(np.float32), "bp": vs_bp.astype(np.float32)}
        out[side] = res
    return out
