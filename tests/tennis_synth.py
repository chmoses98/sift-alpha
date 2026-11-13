"""Synthetic Sackmann-shaped tennis match files for offline builder tests (no real data, no network).

Point-level simulation: each player has a true serve-point-win probability; an optional match-form shock N(0, tau^2) is added to each player's spw per match.
Games, tiebreaks, set scores, svpt / 1stWon / 2ndWon / SvGms / bpFaced / bpSaved and score strings are produced consistently. Tournaments start on Mondays; every match of a
tournament carries the start date (like Sackmann), with rounds R32..F.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ROUNDS = ["R32", "R16", "QF", "SF", "F"]


def _game(rng, p):
    a = b = 0; bpf = bps = 0
    while True:
        if b >= 3 and b > a: bpf += 1; bp = True
        else: bp = False
        if rng.random() < p:
            a += 1
            if bp: bps += 1
        else: b += 1
        if a >= 4 and a - b >= 2: return True, a + b, a, bpf, bps
        if b >= 4 and b - a >= 2: return False, a + b, a, bpf, bps


def _tiebreak(rng, pa, pb, a_first):
    x = y = k = 0; sa = [0, 0]; sb = [0, 0]                      # [points served, served points won]
    while True:
        a_srv = (k == 0 and a_first) or (k > 0 and (((k - 1) // 2) % 2 == 1) == a_first)
        if a_srv:
            sa[0] += 1; w = rng.random() < pa; sa[1] += w
        else:
            sb[0] += 1; w = rng.random() >= pb; sb[1] += not w
        x, y = (x + 1, y) if w else (x, y + 1); k += 1
        if max(x, y) >= 7 and abs(x - y) >= 2: return x > y, sa, sb


def _match(rng, pa, pb, best_of):
    need = best_of // 2 + 1; sw = [0, 0]; sets = []
    st = {"a": np.zeros(5), "b": np.zeros(5)}                     # svpt, won, SvGms, bpFaced, bpSaved
    a_srv = rng.random() < 0.5
    while max(sw) < need:
        ga = gb = 0
        while True:
            if ga == 6 and gb == 6:
                aw, sa, sb = _tiebreak(rng, pa, pb, a_srv)
                st["a"][:2] += sa; st["b"][:2] += sb; ga, gb = (7, 6) if aw else (6, 7); a_srv = not a_srv; break
            p = pa if a_srv else pb; held, pts, won, bpf, bps = _game(rng, p); k = "a" if a_srv else "b"
            st[k] += [pts, won, 1, bpf, bps]
            if (held and a_srv) or (not held and not a_srv): ga += 1
            else: gb += 1
            a_srv = not a_srv
            if (max(ga, gb) >= 6 and abs(ga - gb) >= 2) or max(ga, gb) == 7: break
        sets.append((ga, gb)); sw[0 if ga > gb else 1] += 1
    return sw[0] > sw[1], sets, st


def make(n_players=48, years=4, tau=0.0, seed=7, tours=("atp", "wta"), events_per_year=24):
    rng = np.random.default_rng(seed); rows = []
    for tour in tours:
        true = rng.normal(0.62 if tour == "atp" else 0.56, 0.035, n_players)
        speed = {f"Event{e}": rng.normal(0, 0.02) for e in range(6)}
        for y in range(years):
            for e in range(events_per_year):
                date = pd.Timestamp(2015 + y, 1, 5) + pd.Timedelta(weeks=2 * e)
                ev = f"Event{e % 6}"; bo = 5 if (tour == "atp" and e % 6 == 0) else 3; surf = ["Hard", "Clay", "Grass"][e % 3]
                size = min(32, 2 ** int(np.log2(n_players))); field = list(rng.choice(n_players, size, replace=False)); mn = 0
                for r in ROUNDS[len(ROUNDS) - int(np.log2(size)):]:
                    nxt = []
                    for i in range(0, len(field), 2):
                        a, b = int(field[i]), int(field[i + 1])
                        pa = np.clip(true[a] + speed[ev] + rng.normal(0, tau), 0.35, 0.85); pb = np.clip(true[b] + speed[ev] + rng.normal(0, tau), 0.35, 0.85)
                        awin, sets, st = _match(rng, pa, pb, bo)
                        w, l = (a, b) if awin else (b, a); sw_, sl_ = (st["a"], st["b"]) if awin else (st["b"], st["a"])
                        score = " ".join(f"{x}-{z}" if awin else f"{z}-{x}" for x, z in sets)
                        mn += 1
                        rows.append(dict(tour=tour, tourney_id=f"{2015 + y}-{tour}-{e}", tourney_name=ev, tourney_date=int(date.strftime("%Y%m%d")), surface=surf, tourney_level="A", best_of=bo,
                                         round=r, match_num=mn, winner_id=1000 + w, loser_id=1000 + l, winner_ioc="XXX", loser_ioc="YYY", winner_seed=np.nan, loser_seed=np.nan, score=score,
                                         w_ace=0, l_ace=0, w_svpt=sw_[0], l_svpt=sl_[0], w_1stWon=int(sw_[1] * 0.7), w_2ndWon=sw_[1] - int(sw_[1] * 0.7), l_1stWon=int(sl_[1] * 0.7), l_2ndWon=sl_[1] - int(sl_[1] * 0.7),
                                         w_SvGms=sw_[2], l_SvGms=sl_[2], w_bpFaced=sw_[3], w_bpSaved=sw_[4], l_bpFaced=sl_[3], l_bpSaved=sl_[4]))
                        nxt.append(w)
                    field = nxt
    return pd.DataFrame(rows)
