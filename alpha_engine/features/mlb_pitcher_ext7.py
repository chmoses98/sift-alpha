"""MLB batch 7, ROTATION-CANDIDATE pitcher rows (RESEARCH_ONLY): times-through-the-order rates and expected batters faced, and regressed strikeout / CSW / whiff rates combined
with the opposing recent lineup's K% vs the pitcher's hand (log5). Built from the archived Stats API post-game feeds via mlb_pa_core (chronology, rights, tables there).

Why candidate rows: the archive has NO pre-game probable-pitcher vintages, and the game's actual starter is an as-played fact. So rows are keyed (game_id, pitcher) for every
pitcher who STARTED for the team in one of its last ROTATION_GAMES games completed before the row date (avail_date < d); the announced probable must be matched to a
candidate by a consumer once probables are captured prospectively (mlb.lineup_pit / mlb.f5_starter_change_risk). Nothing here says which candidate starts.
`team` holds the PITCHER id; his club is `pteam` and the opponent `opp`. A pitcher who is a candidate for both clubs keeps the club of his latest start (ties: lower club id).

Windows: the pitcher's PAs (as pitcher) in seasons S-1..S with avail < d. League constants of season S from season S-1 (mlb_pa_core.league).
mlb.tto       for t = 1, 2, 3 (BF 1-9, 10-18, 19+ of a START; relief PAs excluded): tto_k_{t}_pre = (K_t + 100 lgK_t)/(PA_t + 100); tto_bb_{t}_pre = (BB_t + 100 lgBB_t)/(PA_t + 100)
              (BB includes intentional walks); tto_woba_{t}_pre = (num_t + 200 lgW_t)/(den_t + 200); tto_exp_bf_{t}_pre = (sum over starts of min(max(BF - 9(t-1), 0), 9) + 8 lgBF_t)/(starts + 8).
mlb.k_rates   kr_pit_k_pre = (K + 100 lgK)/(PA + 100) over all his PAs; kr_pit_csw_pre = (called + whiffs + 300 lgCSW)/(pitches + 300); kr_pit_whiff_pre = (whiffs + 150 lgWhiff)/(swings + 150);
              kr_opp_lineup_k_pre = opponent's recent-lineup K% vs the pitcher's hand (mlb_team_ext7.lineup_vs_hand; hand = `throws` on his latest PA before d);
              kr_log5_k_pre = log5(kr_pit_k_pre, kr_opp_lineup_k_pre, lgK) = (p l / g) / (p l / g + (1 - p)(1 - l)/(1 - g)).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import mlb_pa_core as C
from . import mlb_team_ext7 as T
from .core import FeatureSpec

S = "MLB"
OUT_FIRST = T.OUT_FIRST
ROTATION_GAMES = 5
CONTENT = C.PA_CONTENT
load_raw = C.load_raw


def _candidates(g: pd.DataFrame, tg: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    prev = C.last_n_games(tg, rows, ROTATION_GAMES)
    sp = pd.concat([g[["game_id", "home", "home_sp", "date"]].rename(columns={"home": "team", "home_sp": "pit"}), g[["game_id", "away", "away_sp", "date"]].rename(columns={"away": "team", "away_sp": "pit"})])
    sp = sp[sp.pit.notna()].rename(columns={"game_id": "prev_gid", "date": "prev_date"})
    u = prev.merge(sp, on=["prev_gid", "team"], how="inner").groupby(["game_id", "team", "pit"], sort=True).prev_date.max().reset_index()
    u = u.sort_values(["game_id", "pit", "prev_date", "team"], ascending=[True, True, False, True], kind="mergesort").drop_duplicates(["game_id", "pit"])
    return u.drop(columns="prev_date").merge(rows, on=["game_id", "team"], how="left")


TTO_COLS = [f"tto_{m}_{t}_pre" for m in ("k", "bb", "woba", "exp_bf") for t in (1, 2, 3)]
KR_COLS = ["kr_pit_k_pre", "kr_pit_csw_pre", "kr_pit_whiff_pre", "kr_opp_lineup_k_pre", "kr_log5_k_pre"]
ALL = TTO_COLS + KR_COLS


def compute(raw: dict) -> dict:
    g, p = C.prepared(raw)
    lg = {s: C.league(p, s) for s in sorted(p.season.unique())}
    tg = C.team_games(g)
    rows = tg[tg.season >= OUT_FIRST][["game_id", "team", "opp", "date", "season"]].sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)
    u = _candidates(g, tg, rows).sort_values(["date", "game_id", "pit"], kind="mergesort").reset_index(drop=True)
    u["row_id"] = np.arange(len(u)); u["pit"] = u.pit.astype("int64")
    # per-PA indicator columns for the windows
    tto = np.minimum((p.bf_i + 8) // 9, 3); st = p.is_start.to_numpy()
    q = p.assign(one=1.0)
    for t in (1, 2, 3):
        m = (st & (tto == t)).astype(float)
        q[f"n{t}"] = m; q[f"k{t}"] = m * p.k; q[f"b{t}"] = m * p.bb; q[f"wn{t}"] = m * p.woba_num; q[f"wd{t}"] = m * p.woba_den
        q[f"bf{t}"] = (st & (p.bf_i > 9 * (t - 1)) & (p.bf_i <= 9 * t)).astype(float)
    q["starts"] = (st & (p.bf_i == 1)).astype(float)
    cols = ["one", "k", "n_pitch", "csw", "n_whiff", "n_swing", "starts"] + [f"{c}{t}" for t in (1, 2, 3) for c in ("n", "k", "b", "wn", "wd", "bf")]
    w = C.window_sums(q, "pit", u[["row_id", "pit", "date", "season"]], cols).loc[u.row_id]
    L = lambda name: np.array([lg[s - 1][name] for s in u.season])  # noqa: E731
    f = u.copy()
    for t in (1, 2, 3):
        n = w[f"n{t}"].to_numpy()
        f[f"tto_k_{t}_pre"] = (w[f"k{t}"].to_numpy() + 100 * L(f"tto_k_{t}")) / (n + 100)
        f[f"tto_bb_{t}_pre"] = (w[f"b{t}"].to_numpy() + 100 * L(f"tto_bb_{t}")) / (n + 100)
        f[f"tto_woba_{t}_pre"] = (w[f"wn{t}"].to_numpy() + 200 * L(f"tto_woba_{t}")) / (w[f"wd{t}"].to_numpy() + 200)
        f[f"tto_exp_bf_{t}_pre"] = (w[f"bf{t}"].to_numpy() + 8 * L(f"tto_bf_{t}")) / (w.starts.to_numpy() + 8)
    lgk = L("k")
    f["kr_pit_k_pre"] = (w.k.to_numpy() + 100 * lgk) / (w.one.to_numpy() + 100)
    f["kr_pit_csw_pre"] = (w.csw.to_numpy() + 300 * L("csw")) / (w.n_pitch.to_numpy() + 300)
    f["kr_pit_whiff_pre"] = (w.n_whiff.to_numpy() + 150 * L("whiff")) / (w.n_swing.to_numpy() + 150)
    # pitcher hand from his latest PA (avail < d), ordered (avail, game_id, ab)
    hp = p[["pit", "avail", "game_id", "ab", "throws"]].sort_values(["avail", "game_id", "ab"], kind="mergesort")
    hh = pd.merge_asof(u[["row_id", "pit", "date"]].sort_values("date"), hp.rename(columns={"avail": "date"})[["date", "pit", "throws"]], on="date", by="pit",
                       allow_exact_matches=False, direction="backward").set_index("row_id").sort_index()
    f["hand"] = hh.throws.to_numpy()
    lv = T.lineup_vs_hand(tg, p, rows.rename(columns={"team": "tm"}).rename(columns={"opp": "team"}).rename(columns={"tm": "opp"})[["game_id", "team", "date", "season"]], lg)
    lv = lv.rename(columns={"team": "opp"})
    f = f.merge(lv, on=["game_id", "opp"], how="left")
    f["kr_opp_lineup_k_pre"] = np.where(f.hand == "R", f.k_R, np.where(f.hand == "L", f.k_L, np.nan))
    pk = f.kr_pit_k_pre.to_numpy(); lk = f.kr_opp_lineup_k_pre.to_numpy(); gk = np.array([lg[s - 1]["k"] for s in f.season])
    a = pk * lk / gk; b = (1 - pk) * (1 - lk) / (1 - gk)
    f["kr_log5_k_pre"] = a / (a + b)
    f = f.rename(columns={"team": "pteam"}).rename(columns={"pit": "team"})
    out = f[["game_id", "team", "pteam", "opp", "date", "season"] + ALL].copy()
    for c in ALL:
        out[c] = out[c].astype("float64")
    return {"team": out.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


RAW = T.RAW
CAND = "no pre-game probable-pitcher vintages: rows are rotation candidates (starters of the club's last 5 completed games); the announced starter is not identified (prospective capture)"


def specs() -> list[FeatureSpec]:
    return [
        FeatureSpec(S, "mlb.tto", "team", TTO_COLS, "PARTIAL",
                    "Per rotation-candidate pitcher: K%, BB% and wOBA allowed by times through the order (BF 1-9, 10-18, 19+ of his starts, seasons S-1..S) shrunk to the S-1 league TTO curve "
                    "(100 / 100 / 200 PA), and expected batters faced in each trip (his starts shrunk to the league with 8 starts)",
                    ["pitcher-specific K%, BB%, wOBA by TTO with shrinkage toward the league curve", "expected BF by TTO from exit behaviour"],
                    [CAND, "multilevel model (fixed-strength shrinkage used)", "manager hook model (the pitcher's own trip-survival history used)"], RAW),
        FeatureSpec(S, "mlb.k_rates", "team", KR_COLS, "PARTIAL",
                    "Per rotation-candidate pitcher: K% (100 BF), CSW% (300 pitches) and whiff% (150 swings) regressed to the S-1 league, the opponent's recent-lineup K% vs his hand, and the log5 "
                    "combination with the league K%",
                    ["pitcher K% / CSW% / whiff% regressed", "opposing lineup K% vs the pitcher's hand", "log5 combination with league K%"],
                    [CAND, "confirmed batting order and slot weights (recent-lineup PA share used)", "TTO, umpire and park adjustments"], RAW),
    ]


def perturb_nv(raw: dict, block_ids, seed: int) -> dict:
    """Role-preserving non-vacuity perturbation: within the block's games (1) PA outcome vectors (event and pitch counts) are permuted jointly across PAs and (2) within each
    fielding club the (pitcher, hand) pair is permuted across that club's block PAs (all its block games). The games' recorded starters are untouched, so the rotation-candidate universe of later rows is
    unchanged, while every rate, trip count and batters-faced total of later rows must move."""
    o = dict(raw); p = raw["pa"].copy(); rng = np.random.default_rng(seed)
    blk = p.game_id.isin(block_ids).to_numpy(); ix = np.flatnonzero(blk); perm = rng.permutation(ix)
    for c in ("event", "n_pitch", "n_called", "n_whiff", "n_swing"):
        v = p[c].to_numpy(copy=True); v[ix] = v[perm]; p[c] = v
    gm = C._all(raw, "games").drop_duplicates("game_id").set_index("game_id")
    fld = np.where(p["top"].astype(bool).to_numpy(), p.game_id.map(gm.home).to_numpy(), p.game_id.map(gm.away).to_numpy())
    key = pd.Series(fld).astype(str).to_numpy()     # fielding club: pitchers move between that club's block games, so batters faced per start change
    codes = pd.factorize(key[ix])[0]
    a = ix[np.lexsort((ix, codes))]; b = ix[np.lexsort((rng.random(len(ix)), codes))]
    for c in ("pit", "throws"):
        v = p[c].to_numpy(copy=True); w = v.copy(); w[a] = v[b]; p[c] = w
    o["pa"] = p
    return o
