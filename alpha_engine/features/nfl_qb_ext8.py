"""NFL batch 8, quarterback rows (RESEARCH_ONLY): expected passing touchdowns, passing-TD luck, interception rate and a completion-count model, from nflverse
play-by-play only (no line or price). Rows keyed (game_id, team) where `team` holds the QB gsis id (harness convention of nfl_player_ext5); his club is `pteam`.

Source / rights as nfl_team_ext8. Codes OAK->LV, SD->LAC, STL->LA on posteam / defteam and the schedule (NFL amendment 1).

DEFINITIONS (point in time: every value for a row dated d uses only plays of games dated strictly before d)
  Games: schedule rows with home_score present, season >= 2010; date = gameday. Rows are built for seasons >= OUT_FIRST (2013) and OUTPUT for seasons >= 2014
  (qcc_rho_pre needs at least one season of built rows). 'QB' = any passer: trick-play passers with an attempt in the window are rows too.
  Attempt: a pbp row with complete_pass == 1 or incomplete_pass == 1 or interception == 1, two_point_attempt != 1, passer_player_id and posteam present. td = pass_touchdown == 1;
  int = interception == 1; comp = complete_pass == 1. A QB's attempts are ordered by (date, game_id, play_id).
  xTD model for season S: cells = yardline_100 bucket (<=5, <=10, <=20, <=40, else) x air_yards bucket (missing, < 0, < 10, < 20, else) over all attempts of seasons
  max(2010, S-3) .. max(2010, S-1); p_cell = (TD in cell + 10 p_all)/(n in cell + 10), p_all = overall TD rate of those attempts. Every attempt of season S gets p_td from the
  season-S model (for 2010 the model is fitted on 2010 itself: history only, every output row is >= 2013).
  Attempt window: weights 0.5 ** (k / 350) for the k-th most recent of the QB's last 700 attempts before d (k = 0 newest); sums Sw(x) = sum of weight x.
  Row universe: QBs with an attempt for T in T's last 4 played games dated before d; a QB qualifying for both clubs keeps the club of his latest such attempt date (ties: smaller code).
  League constants of season S from attempts of season S-1: int rate, completion rate.

nfl.qb_expected_pass_td  qbx_xtd_rate_pre = (Sw(1) q + 300 t)/(Sw(1) + 300), q = Sw(p_td)/Sw(1), t = mean p_td of the club's attempts in its last 8 played games before d;
                         qbx_ratio_reg_pre = 1 + 0.3 ((Sw(td) + 2)/(Sw(p_td) + 2) - 1) (a 2-TD prior stabilises passers with few attempts); qbx_adj_td_rate_pre = qbx_xtd_rate_pre x qbx_ratio_reg_pre.
nfl.td_luck              tdl_luck_raw_pre = (Sw(td) - Sw(p_td))/Sw(1); tdl_luck_regressed_pre = 0.2 x raw (80% regression to zero);
                         tdl_persistent_pre = season S-1 (td - p_td) sum / (n + 300) over the QB's attempts of season S-1 (0 if none).
nfl.int_rate             int_qb_rate_pre = (Sw(int) + 200 lg_int)/(Sw(1) + 200); int_opp_rel_pre = opponent defence's interceptions per attempt faced over its last 16 played games
                         (shrunk: (I + 200 lg_int)/(A + 200)) / lg_int; int_exp_rate_pre = qb rate x opp rel; int_exp_ints_pre = int_exp_rate_pre x the QB's mean attempts per game over his last
                         8 games with an attempt.
nfl.qb_completion_count_model  per QB-game: C = sum cp, N = attempts with cp present, E = sum (comp - cp) over those; over his last 16 games (half-life 8 games, weight 0.5 ** (k/8)):
                         qcc_xcomp_pre = sum w C / sum w N; qcc_cpoe_shr_pre = (sum of E over the 16 games)/(sum of N + 300); qcc_opp_factor_pre = (sum of E allowed by the opponent defence over
                         its last 12 played games)/(N faced + 250); qcc_p_pre = clip(xcomp + cpoe + opp, 0.35, 0.85);
                         qcc_rho_pre = clip(mean over rows of seasons S-3..S-1 whose QB had >= 10 attempts in that row's game of ((c - n p)^2 - n p (1-p)) / (n (n-1) p (1-p)), 0, 0.2).
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec
from .nfl_ext import TEAM_FIX

S = "NFL"
HIST_FIRST, OUT_FIRST = 2010, 2013
OUT_ROWS = OUT_FIRST + 1      # first OUTPUT season; everything before it is warm history for the replay harness
WIN, HL_ATT = 700, 350.0
PREV_TEAM_GAMES = 4
PBP_COLS = ["game_id", "play_id", "posteam", "defteam", "passer_player_id", "complete_pass", "incomplete_pass", "interception", "pass_touchdown", "two_point_attempt", "yardline_100", "air_yards", "cp"]
CONTENT = ["passer_player_id", "complete_pass", "incomplete_pass", "interception", "pass_touchdown", "yardline_100", "air_yards", "cp"]
GAMES_COLS = ["game_id", "season", "gameday", "home_team", "away_team", "home_score"]


def load_raw(pbp_dir, games_file) -> dict:
    fs = sorted(glob.glob(str(Path(pbp_dir) / "play_by_play_*.parquet"))) or sorted(glob.glob(str(Path(pbp_dir) / "pbp_*.parquet")))
    pbp = pd.concat([pd.read_parquet(f, columns=PBP_COLS) for f in fs], ignore_index=True)
    g = pd.read_csv(games_file, usecols=GAMES_COLS)
    g = g[(g.season >= HIST_FIRST) & g.home_score.notna()].drop_duplicates("game_id")
    pbp = pbp[pbp.game_id.isin(set(g.game_id))]
    warm = set(g.game_id[g.season < OUT_ROWS]); pw = pbp.game_id.isin(warm)
    return {"pbp": pbp[~pw].reset_index(drop=True), "games": g[g.season >= OUT_ROWS].reset_index(drop=True),
            "pbp_warm": pbp[pw].reset_index(drop=True), "games_warm": g[g.season < OUT_ROWS].reset_index(drop=True)}


def _all(raw, key):
    parts = [raw[k] for k in (key + "_warm", key) if raw.get(k) is not None and len(raw[k])]
    return pd.concat(parts, ignore_index=True) if parts else raw[key]


def _fix(s):
    return s.astype("object").replace(TEAM_FIX)


def _yb(y):
    y = np.asarray(y, float)
    return np.select([y <= 5, y <= 10, y <= 20, y <= 40], [0, 1, 2, 3], 4)


def _ab(a):
    a = np.asarray(a, float)
    return np.where(np.isnan(a), 0, np.select([a < 0, a < 10, a < 20], [1, 2, 3], 4))


def _attempts(raw):
    g = _all(raw, "games").drop_duplicates("game_id").copy(); g["date"] = pd.to_datetime(g.gameday)
    g["home_team"] = _fix(g.home_team); g["away_team"] = _fix(g.away_team)
    p = _all(raw, "pbp")
    num = lambda c: pd.to_numeric(p[c], errors="coerce")  # noqa: E731
    att = ((num("complete_pass") == 1) | (num("incomplete_pass") == 1) | (num("interception") == 1)) & (num("two_point_attempt").fillna(0) != 1) & p.passer_player_id.notna() & p.posteam.notna()
    a = p[att].copy()
    a = a.merge(g[["game_id", "season", "date"]], on="game_id", how="inner")
    a["T"] = _fix(a.posteam); a["D"] = _fix(a.defteam)
    for c, src in (("td", "pass_touchdown"), ("int", "interception"), ("comp", "complete_pass")):
        a[c] = (pd.to_numeric(a[src], errors="coerce") == 1).astype(float)
    a["play_id"] = pd.to_numeric(a.play_id, errors="coerce"); a["cp"] = pd.to_numeric(a.cp, errors="coerce")
    a["cell"] = _yb(a.yardline_100) * 5 + _ab(a.air_yards)
    # walk-forward xTD table per season
    a["p_td"] = np.nan
    for s_ in sorted(a.season.unique()):
        lo, hi = max(HIST_FIRST, s_ - 3), max(HIST_FIRST, s_ - 1)
        ref = a[(a.season >= lo) & (a.season <= hi)]; pall = ref.td.mean()
        tab = ref.groupby("cell").td.agg(["sum", "count"]); pc = (tab["sum"] + 10 * pall) / (tab["count"] + 10)
        m = a.season == s_; a.loc[m, "p_td"] = a.loc[m, "cell"].map(pc).fillna(pall).to_numpy()
    a = a.sort_values(["passer_player_id", "date", "game_id", "play_id"], kind="mergesort").reset_index(drop=True)
    return g, a


def _win_state(a: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Per attempt: windowed EWM sums over the QB's last WIN attempts (including this one): W_i - r^WIN W_{i-WIN}."""
    r = 0.5 ** (1.0 / HL_ATT); q = a.passer_player_id.to_numpy(); n = len(a)
    pos = a.groupby("passer_player_id", sort=False).cumcount().to_numpy()
    out = {}
    for c in ["one"] + cols:
        x = np.ones(n) if c == "one" else a[c].to_numpy(float)
        W = np.empty(n); acc = 0.0; prev = None
        for i in range(n):
            if q[i] != prev:
                acc = 0.0; prev = q[i]
            acc = acc * r + x[i]; W[i] = acc
        lag = np.where(pos >= WIN, W[np.maximum(np.arange(n) - WIN, 0)], 0.0)
        out["S_" + c] = W - (r ** WIN) * lag
    return pd.DataFrame(out)


QBX = ["qbx_xtd_rate_pre", "qbx_ratio_reg_pre", "qbx_adj_td_rate_pre"]
TDL = ["tdl_luck_raw_pre", "tdl_luck_regressed_pre", "tdl_persistent_pre"]
INT = ["int_qb_rate_pre", "int_opp_rel_pre", "int_exp_rate_pre", "int_exp_ints_pre"]
QCC = ["qcc_xcomp_pre", "qcc_cpoe_shr_pre", "qcc_opp_factor_pre", "qcc_p_pre", "qcc_rho_pre"]
ALL = QBX + TDL + INT + QCC


def _team_slots(g):
    rows = [g.assign(team=g[x], opp=g[y])[["game_id", "season", "date", "team", "opp"]] for x, y in (("home_team", "away_team"), ("away_team", "home_team"))]
    return pd.concat(rows, ignore_index=True).sort_values(["team", "date", "game_id"], kind="mergesort").reset_index(drop=True)


def _last_games(slots, rows, n, key="team"):
    out = []
    for t, r in rows.groupby(key, sort=True):
        h = slots[slots.team == t]; hd = h.date.to_numpy(); hg = h.game_id.to_numpy()
        k = np.searchsorted(hd, r.date.to_numpy(), side="left")
        for o in range(1, n + 1):
            kk = k - o; ok = kk >= 0
            out.append(pd.DataFrame({"row_gid": r.game_id.to_numpy()[ok], key: t, "prev_gid": hg[kk[ok]]}))
    return pd.concat(out, ignore_index=True)


def compute(raw: dict) -> dict:
    g, a = _attempts(raw)
    a["e"] = np.where(a.cp.notna(), a.comp - a.cp.fillna(0.0), 0.0); a["has_cp"] = a.cp.notna().astype(float); a["cp0"] = a.cp.fillna(0.0)
    st = pd.concat([a[["passer_player_id", "date", "game_id", "play_id"]], _win_state(a, ["td", "p_td", "int"])], axis=1)
    slots = _team_slots(g)
    out_rows = slots[slots.season >= OUT_FIRST]
    # universe
    prev = _last_games(slots, out_rows, PREV_TEAM_GAMES)
    qa = a.groupby(["game_id", "T", "passer_player_id"]).date.first().reset_index().rename(columns={"game_id": "prev_gid", "T": "team", "date": "qd"})
    u = prev.merge(qa, on=["prev_gid", "team"], how="inner").groupby(["row_gid", "team", "passer_player_id"], sort=True).qd.max().reset_index()
    u = u.sort_values(["row_gid", "passer_player_id", "qd", "team"], ascending=[True, True, False, True], kind="mergesort").drop_duplicates(["row_gid", "passer_player_id"])
    u = u.drop(columns="qd").rename(columns={"row_gid": "game_id"}).merge(out_rows, on=["game_id", "team"], how="left")
    u = u.sort_values(["date", "game_id", "passer_player_id"], kind="mergesort").reset_index(drop=True)
    f = pd.merge_asof(u, st.drop(columns=["game_id", "play_id"]).sort_values("date", kind="mergesort"), on="date", by="passer_player_id", allow_exact_matches=False, direction="backward")
    f = f.sort_values(["date", "game_id", "passer_player_id"], kind="mergesort").reset_index(drop=True)
    lg = {s_ + 1: {"int": q.int.mean(), "comp": q.comp.mean()} for s_, q in a.groupby("season")}
    lgi = f.season.map(lambda s_: lg[s_]["int"]).to_numpy(float)
    # team / opponent game aggregates
    tgm = a.groupby(["game_id", "T"]).agg(ptd=("p_td", "sum"), n=("p_td", "size")).reset_index()
    dgm = a.groupby(["game_id", "D"]).agg(I=("int", "sum"), A=("int", "size"), E=("e", "sum"), N=("has_cp", "sum")).reset_index()
    def _sum_last(rows_key, n, agg, key_col, cols):
        pv = _last_games(slots, f.rename(columns={rows_key: "team"})[["game_id", "team", "date"]].drop_duplicates(["game_id", "team"]), n)
        m = pv.merge(agg.rename(columns={key_col: "team", "game_id": "prev_gid"}), on=["prev_gid", "team"], how="left").fillna({c: 0.0 for c in cols})
        return m.groupby(["row_gid", "team"])[cols].sum().reset_index().rename(columns={"row_gid": "game_id", "team": rows_key})
    f = f.rename(columns={"team": "pteam"})
    t8 = _sum_last("pteam", 8, tgm, "T", ["ptd", "n"]); f = f.merge(t8, on=["game_id", "pteam"], how="left")
    d16 = _sum_last("opp", 16, dgm, "D", ["I", "A"]); f = f.merge(d16, on=["game_id", "opp"], how="left")
    d12 = _sum_last("opp", 12, dgm, "D", ["E", "N"]).rename(columns={"E": "E12", "N": "N12"}); f = f.merge(d12, on=["game_id", "opp"], how="left")
    S1 = f.S_one.to_numpy(); q = f.S_p_td / f.S_one; t = np.where(f.n > 0, f.ptd / f.n.where(f.n > 0), q)
    f["qbx_xtd_rate_pre"] = (S1 * q + 300 * t) / (S1 + 300)
    f["qbx_ratio_reg_pre"] = 1 + 0.3 * ((f.S_td + 2.0) / (f.S_p_td + 2.0) - 1)
    f["qbx_adj_td_rate_pre"] = f.qbx_xtd_rate_pre * f.qbx_ratio_reg_pre
    f["tdl_luck_raw_pre"] = (f.S_td - f.S_p_td) / f.S_one; f["tdl_luck_regressed_pre"] = 0.2 * f.tdl_luck_raw_pre
    ps = a.assign(d=a.td - a.p_td).groupby(["passer_player_id", "season"]).agg(ds=("d", "sum"), dn=("d", "size")).reset_index()
    ps["season"] = ps.season + 1
    f = f.merge(ps, on=["passer_player_id", "season"], how="left")
    f["tdl_persistent_pre"] = (f.ds.fillna(0.0) / (f.dn.fillna(0.0) + 300)).to_numpy()
    f["int_qb_rate_pre"] = (f.S_int + 200 * lgi) / (f.S_one + 200)
    f["int_opp_rel_pre"] = (f.I.fillna(0.0) + 200 * lgi) / (f.A.fillna(0.0) + 200) / lgi
    f["int_exp_rate_pre"] = f.int_qb_rate_pre * f.int_opp_rel_pre
    # QB-game aggregates for per-game windows
    qg = a.groupby(["passer_player_id", "game_id"]).agg(date=("date", "first"), att=("int", "size"), C=("cp0", "sum"), N=("has_cp", "sum"), E=("e", "sum"), comp=("comp", "sum")).reset_index()
    qg = qg.sort_values(["passer_player_id", "date", "game_id"], kind="mergesort").reset_index(drop=True)
    key = qg.passer_player_id.to_numpy(); pos = qg.groupby("passer_player_id", sort=False).cumcount().to_numpy()
    def _lastk(x, k, w):
        """sum over the QB's last k games (this one included) of weight_j x_j with weight 0.5 ** (j / w) (w = None: unweighted), j = 0 newest."""
        x = np.asarray(x, float); outv = np.zeros(len(x))
        for j in range(k):
            idx = np.arange(len(x)) - j; ok = (pos >= j)
            wj = 1.0 if w is None else 0.5 ** (j / w)
            outv[ok] += wj * x[idx[ok]]
        return outv
    qg["att8"] = _lastk(qg.att, 8, None); qg["g8"] = np.minimum(pos + 1, 8)
    qg["wC"] = _lastk(qg.C, 16, 8.0); qg["wN"] = _lastk(qg.N, 16, 8.0); qg["E16"] = _lastk(qg.E, 16, None); qg["N16"] = _lastk(qg.N, 16, None)
    qs = qg[["passer_player_id", "date", "att8", "g8", "wC", "wN", "E16", "N16"]].sort_values("date", kind="mergesort")
    f = pd.merge_asof(f.sort_values("date", kind="mergesort"), qs, on="date", by="passer_player_id", allow_exact_matches=False, direction="backward")
    f["int_exp_ints_pre"] = f.int_exp_rate_pre * f.att8 / f.g8
    f["qcc_xcomp_pre"] = f.wC / f.wN.where(f.wN > 0)
    f["qcc_cpoe_shr_pre"] = f.E16 / (f.N16 + 300)
    f["qcc_opp_factor_pre"] = f.E12.fillna(0.0) / (f.N12.fillna(0.0) + 250)
    f["qcc_p_pre"] = np.clip(f.qcc_xcomp_pre + f.qcc_cpoe_shr_pre + f.qcc_opp_factor_pre, 0.35, 0.85)
    # rho from earlier seasons' rows (outcome of the row's own game used only for seasons < S)
    own = qg[["passer_player_id", "game_id", "att", "comp"]]
    f = f.merge(own, on=["passer_player_id", "game_id"], how="left")
    f["qcc_rho_pre"] = np.nan
    # rows of seasons < OUT_FIRST are not built; rho for seasons with < 1 reference season uses what exists (seasons >= OUT_FIRST only)
    for s_ in sorted(f.season.unique()):
        ref = f[(f.season >= s_ - 3) & (f.season <= s_ - 1) & (f.att >= 10) & f.qcc_p_pre.notna()]
        if len(ref) == 0:
            continue
        n = ref.att.to_numpy(float); c = ref.comp.to_numpy(float); p = ref.qcc_p_pre.to_numpy(float)
        v = ((c - n * p) ** 2 - n * p * (1 - p)) / (n * (n - 1) * p * (1 - p))
        f.loc[f.season == s_, "qcc_rho_pre"] = float(np.clip(v.mean(), 0.0, 0.2))
    f = f[f.season >= OUT_ROWS].rename(columns={"passer_player_id": "team"})
    out = f[["game_id", "team", "pteam", "opp", "season", "date"] + ALL].copy()
    for c in ALL:
        out[c] = out[c].astype("float64")
    return {"team": out.sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)}


RAW = ["nflverse play_by_play 2010-2026 (passer, completion / interception / TD flags, yardline_100, air_yards, cp)", "nflverse schedule"]
CAND = "starting-QB identity (nfl.qb: prospective): rows are every QB with an attempt for the club in its last 4 games"


def specs() -> list[FeatureSpec]:
    F = lambda cid, cols, lvl, d, done, miss: FeatureSpec(S, cid, "team", cols, lvl, d, done, miss + [CAND], RAW)  # noqa: E731
    return [
        F("nfl.qb_expected_pass_td", QBX, "PARTIAL", "QB expected passing TDs per attempt from a walk-forward league table P(TD | yardline bucket, air-yards bucket) (previous 3 seasons), averaged over his last 700 "
          "attempts (half-life 350), shrunk to the club's recent rate with 300 attempts, and the actual/expected ratio regressed 70% to 1",
          ["league P(pass TD | field position, air yards)", "last 700 attempts, half-life 350", "shrink to team rate k = 300", "actual/expected ratio regressed 70% to 1"],
          ["down, distance and pass location in the TD model", "participation-era personnel and box count upgrade", "logistic model (smoothed cell table used)"]),
        F("nfl.td_luck", TDL, "PARTIAL", "QB passing touchdowns over expected per attempt (recent 700-attempt window), its 80% regression toward zero, and the previous season's TD over expected per attempt "
          "shrunk with 300 attempts as the persistent residual", ["TD over expected from location", "regression of luck toward zero", "persistent residual across seasons"],
          ["rushing and receiving TD luck (passing only)", "ff_opportunity expected-TD fields"]),
        F("nfl.int_rate", INT, "PARTIAL", "QB interceptions per attempt (700-attempt window, half-life 350) shrunk to the S-1 league with 200 attempts, opponent interception rate relative to league "
          "(last 16 games, shrunk), and expected interceptions = rate x opponent factor x his recent attempts per game", ["INT per attempt shrunk with prior", "opponent adjustment", "expected INTs = attempts x rate"],
          ["turnover-worthy throw rate / pressure (PFR advanced stats not held)", "tipped-INT share", "pressure adjustment"]),
        F("nfl.qb_completion_count_model", QCC, "PARTIAL", "QB completion probability = recent mean nflfastR cp (last 16 games, half-life 8) + completion over expected shrunk (k = 300) + opponent completion "
          "over expected allowed (last 12 games, k = 250), clipped to [0.35, 0.85], with a beta-binomial intra-game correlation estimated from the previous 3 seasons",
          ["xComp from cp", "CPOE shrunk to 0", "opponent factor", "clip to [0.35, 0.85]", "beta-binomial rho from history"],
          ["wind adjustment (no weather forecasts)", "mixture over an attempts forecast"]),
    ]


def perturb_nv(raw: dict, block_ids, seed: int) -> dict:
    """Role-preserving non-vacuity perturbation (precedent nfl_player_ext5.perturb): within the block's games, the outcome vectors of ATTEMPT rows (completion, incompletion,
    interception, TD, yardline, air yards, cp) are permuted jointly across attempts, so every attempt stays an attempt by the same passer (the QB row universe is unchanged) while
    every rate, expectation and luck value of later rows must move."""
    o = dict(raw); p = raw["pbp"].copy(); rng = np.random.default_rng(seed)
    num = lambda c: pd.to_numeric(p[c], errors="coerce")  # noqa: E731
    att = ((num("complete_pass") == 1) | (num("incomplete_pass") == 1) | (num("interception") == 1)) & (num("two_point_attempt").fillna(0) != 1) & p.passer_player_id.notna() & p.posteam.notna()
    ix = np.flatnonzero((att & p.game_id.isin(block_ids)).to_numpy())
    cols = ["complete_pass", "incomplete_pass", "interception", "pass_touchdown", "yardline_100", "air_yards", "cp"]
    perm = rng.permutation(ix)
    for c in cols:
        v = p[c].to_numpy(copy=True); v[ix] = v[perm]; p[c] = v
    o["pbp"] = p
    return o
