"""Operation Data Foundation, NBA: challenger ``alpha-nba-rate-0.3`` (per-minute rate and scoring-level diagnosis).

RESEARCH_ONLY. Follows ``alpha-nba-avail-0.2`` (``nba_frozen``), which showed the frozen production forecasts trail the
Kalshi T-60 mid and that most player error sits in the per-minute rate. This module

1. decomposes the frozen team-points / game-total bias (pace, efficiency, overtime, rest-adjustment stage, player-sum
   incoherence) and looks for structure in the per-minute rate error on three earlier seasons (walk-forward);
2. tests rate components on prior seasons against a reproduction baseline and keeps only those that pass the contract
   rule there; applies the survivors to the ACTUAL frozen ``pf`` forecasts of 2026-27 and scores them against ``pf`` and
   against the Kalshi T-60 mid by market family;
3. restores T-60 market boards for games after 2026-11-06 from the capture-worker archive (``data-archive`` branch:
   full board checkpoints plus hash-chained deltas). Only quotes observed at or before tip - 60 min are used; nothing
   is interpolated;
4. maps every frozen forecast run to its exact code revision (the ``pf-x.y.z+<sha>`` suffix) and to a digest of the
   forecast-affecting source files, so behaviour-changing commits are separated from unrelated ones.

Point-in-time rules: player and team history features use games on strictly earlier ET dates; online level corrections
use outcomes of games on strictly earlier ET dates of the same season; hyper-parameters come from 2024-25 only; the
2026-27 TRAIN window (before 2026-11-01) is used only to decide whether a history-validated component is switched on.

Raw rows never leave this process: only aggregates, counts and digests are written.
``python -m alpha_engine.foundation.nba_rate`` regenerates ``research/data_foundation_ops/NBA/alpha-nba-rate-0.3/``
and ``research/data_foundation_ops/NBA/pf_version_lineage.json``.
"""
from __future__ import annotations

import bisect
import gzip
import hashlib
import io
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import contract as C
from . import nba_availability as V1
from . import nba_frozen as F

CHALLENGER_ID = "alpha-nba-rate-0.3"
INCUMBENT_ID = F.INCUMBENT_ID
DA_BRANCH = "data-archive"
DA_COMMIT = "eeb64caad16701d28063a987f0cb3f4936f567aa"
OUT_DIR = C.OPS / "NBA" / CHALLENGER_ID
LINEAGE_PATH = C.OPS / "NBA" / "pf_version_lineage.json"

HIST_SEASONS = ["2023-24", "2024-25", "2025-26", "2026-27"]
TRAIN_H, TEST_H, H_SPLIT = "2024-25", "2025-26", "2026-01-15"      # history: tune on 2024-25, test on 2025-26 (two halves)
H1, H2, HP = "hist_2025-26_before_2026-01-15", "hist_2025-26_from_2026-01-15", "hist_2025-26_pooled"
COH1, COH2, POOLED, ALLG = F.COH1, F.COH2, F.POOLED, F.ALLG
STATS = F.STATS
HS = {"points": "pts", "rebounds": "reb", "assists": "ast", "threes": "fg3m"}
COLS = ["one", "minutes", "pts", "reb", "ast", "fg3m", "fga", "fta", "tov"]
CI = {c: i for i, c in enumerate(COLS)}
BASE_HL, BASE_K = 20.0, 30.0            # reproduction baseline: EWM-sum per-minute rate (pf rung C / the 0.1 rate method)
MPG_EDGES = [0.01, 12.0, 20.0, 28.0]
GAME_SERIES = ("KXNBAPTS", "KXNBAREB", "KXNBAAST", "KXNBA3PT", "KXNBAPRA", "KXNBASPREAD", "KXNBATOTAL", "KXNBATEAMTOTAL", "KXNBAGAME")
BOARD_FIELDS = ("event_ticker", "series_ticker", "status", "floor_strike", "strike_type", "_quote_cents", "_family", "_support")
SEED = 7
# forecast-affecting source of the production projection model (everything `nba.project` imports or reads)
MODEL_PATHS = [f"research/projection_foundation/pf_core/{f}.py" for f in ("models", "dists", "pit", "gate", "availability")] + \
              [f"research/projection_foundation/nba/{f}.py" for f in ("common", "data", "distributions", "features", "injury", "minutes", "pipeline", "project", "stats", "team")] + \
              [f"research/projection_foundation/nba/live/{f}" for f in ("availability.py", "participation.py", "participation_calibration.json", "forecasts.py",
                                                                         "reconcile.py", "sources.py", "starter_onoff.py", "run.py")] + \
              ["research/projection_foundation/nba/paper/paper_config.json", "research/projection_foundation/results/frozen_params.json"]


def _chk(name, passed, detail, basis="COMPUTED"):
    return dict(name=name, passed=bool(passed), detail=str(detail), basis=basis)


# =============================================================================================== pure helpers (tested)
def decayed_sums(X: np.ndarray, pid: np.ndarray, season: np.ndarray, halflife: float, reset_season: bool = False):
    """Pre-game and post-game exponentially decayed column sums per player (rows sorted by player then time).
    ``pre[i]`` uses rows strictly before i for the same player; ``post[i] = pre[i] * decay + X[i]``."""
    dec = 0.5 ** (1.0 / halflife) if np.isfinite(halflife) else 1.0
    pre = np.zeros_like(X, dtype=float); post = np.zeros_like(X, dtype=float)
    S = np.zeros(X.shape[1]); lp = None; ls = None
    for i in range(len(X)):
        if pid[i] != lp:
            S = np.zeros(X.shape[1]); lp = pid[i]; ls = season[i]
        elif reset_season and season[i] != ls:
            S = np.zeros(X.shape[1])
        ls = season[i]
        pre[i] = S
        S = S * dec + X[i]
        post[i] = S
    return pre, post


def shrunk_rate(num, den, prior, k):
    """(sum + k * prior) / (exposure + k): empirical-Bayes rate with k exposure units at the prior."""
    return (np.asarray(num, float) + k * np.asarray(prior, float)) / (np.asarray(den, float) + k)


def online_level(dates, groups, actual, forecast, k: float, additive: bool = False) -> np.ndarray:
    """Point-in-time level correction. For each row the statistic uses ONLY rows of the same group (season) on strictly
    earlier dates: multiplicative (sum actual + k) / (sum forecast + k), or additive sum(actual - forecast) / (n + k)."""
    df = pd.DataFrame(dict(d=pd.to_datetime(np.asarray(dates)), g=np.asarray(groups), a=np.asarray(actual, float), f=np.asarray(forecast, float)))
    ok = np.isfinite(df.a) & np.isfinite(df.f)
    agg = df[ok].groupby(["g", "d"], sort=True).agg(a=("a", "sum"), f=("f", "sum"), n=("a", "size")).reset_index()
    for c in ("a", "f", "n"):
        agg["c" + c] = agg.groupby("g")[c].cumsum() - agg[c]
    agg["v"] = (agg.ca - agg.cf) / (agg.cn + k) if additive else (agg.ca + k) / (agg.cf + k)
    out = np.full(len(df), 0.0 if additive else 1.0)
    for g, sub in agg.groupby("g"):
        mk = (df.g == g).to_numpy()
        j = np.searchsorted(sub.d.to_numpy(), df.d.to_numpy()[mk], side="left")          # first date >= row date: its prefix excludes the row date
        last = sub.iloc[-1]
        tail = (last.ca + last.a - last.cf - last.f) / (last.cn + last.n + k) if additive else (last.ca + last.a + k) / (last.cf + last.f + k)
        v = np.append(sub.v.to_numpy(), tail)
        out[mk] = v[j]
    return out


def poisson_beta(y, f, x, iters: int = 30) -> float:
    """One-parameter Poisson MLE for y ~ Poisson(f * exp(beta * x))."""
    y = np.asarray(y, float); f = np.asarray(f, float); x = np.asarray(x, float); b = 0.0
    for _ in range(iters):
        mu = f * np.exp(np.clip(b * x, -5, 5))
        g = np.sum((y - mu) * x); h = np.sum(mu * x * x)
        if h <= 0:
            break
        step = g / h; b += step
        if abs(step) < 1e-10:
            break
    return float(b)


def tilt_pmf(pmf: np.ndarray, target_mean: np.ndarray, iters: int = 50) -> np.ndarray:
    """Exponentially tilt each row pmf over 0..K so that its mean equals ``target_mean`` (shape preserved; a target
    outside (0, K) is clipped). Rows are renormalised."""
    pmf = np.asarray(pmf, float); k = np.arange(pmf.shape[1], dtype=float)
    tgt = np.clip(np.asarray(target_mean, float), 1e-6, pmf.shape[1] - 1 - 1e-6)
    lo = np.full(len(pmf), -3.0); hi = np.full(len(pmf), 3.0)
    for _ in range(iters):
        th = (lo + hi) / 2
        w = pmf * np.exp(th[:, None] * (k[None, :] - k.mean())); w /= w.sum(1, keepdims=True)
        up = (w @ k) < tgt
        lo = np.where(up, th, lo); hi = np.where(up, hi, th)
    th = (lo + hi) / 2
    w = pmf * np.exp(th[:, None] * (k[None, :] - k.mean()))
    return w / w.sum(1, keepdims=True)


def shift_pmf(lo: int, probs, delta: float):
    """Shift an integer pmf starting at ``lo`` by a real ``delta`` (mass split between the two neighbouring integers);
    the mean moves by exactly delta and the shape is otherwise unchanged. Returns (lo, probs)."""
    p = np.asarray(probs, float); p = p / p.sum()
    n = int(np.floor(delta)); f = float(delta - n)
    return int(lo) + n, (1 - f) * np.append(p, 0.0) + f * np.append(0.0, p)


def parse_board_ticker(ticker: str):
    """Kalshi NBA game-market ticker -> dict(series, date, away, home, side, code, k) or None.
    ``KXNBAPTS-26NOV10MIAUTA-UTADPETERSON22-30`` (player), ``KXNBASPREAD-26NOV01BKNIND-BKN10``, ``KXNBATOTAL-...-203``."""
    parts = str(ticker).split("-")
    if len(parts) < 3 or parts[0] not in GAME_SERIES:
        return None
    m = V1._EVENT_RE.match(parts[1])
    if not m or m.group(2) not in V1.MONTHS:
        return None
    teams = m.group(4); split = None
    for cut in range(2, len(teams) - 1):
        a, h = V1.canon_tricode(teams[:cut]), V1.canon_tricode(teams[cut:])
        if a and h:
            split = (a, h); break
    if split is None:
        return None
    out = dict(series=parts[0], date=f"20{m.group(1)}-{V1.MONTHS[m.group(2)]:02d}-{m.group(3)}", away=split[0], home=split[1], side=None, code=None, k=None)
    tail = parts[2]
    if len(parts) == 4:                                  # player prop: TEAM+code, K
        out["code"] = tail
        for n in (4, 3, 2):
            t = V1.canon_tricode(tail[:n])
            if t in split:
                out["side"] = t; break
        out["k"] = int(parts[3]) if parts[3].isdigit() else None
    else:
        mm = re.match(r"^([A-Z]*?)(\d*)$", tail)
        if not mm:
            return None
        out["side"] = V1.canon_tricode(mm.group(1)) if mm.group(1) else None
        out["k"] = int(mm.group(2)) if mm.group(2) else None
    return out


def quote_class(status, yes_bid, yes_ask) -> str:
    """Same reading as the owner's snapshots: two-sided needs an active market with both a bid and an ask."""
    if yes_bid is None and yes_ask is None:
        return "NO_QUOTE"
    if status == "active" and yes_bid is not None and yes_ask is not None:
        return "TWO_SIDED"
    return "ONE_SIDED"


def apply_board_delta(board: dict, delta: dict, keep) -> bool:
    """Apply one ``kalshi.board.delta/1`` to a filtered board in place (removed, added, changed, cleared).
    Returns False when a change refers to a kept ticker that is not on the board (broken chain: fail closed)."""
    ok = True
    for t in delta.get("removed", []):
        board.pop(t, None)
    for t, row in delta.get("added", {}).items():
        if keep(t):
            board[t] = {k: row.get(k) for k in BOARD_FIELDS}
    for t, diff in delta.get("changed", {}).items():
        if keep(t):
            if t in board:
                board[t].update({k: v for k, v in diff.items() if k in BOARD_FIELDS})
            else:
                ok = False
    for t, fields in delta.get("cleared", {}).items():
        if t in board:
            for f in fields:
                board[t].pop(f, None)
    return ok


def chain_ok(seqs, parents, boards) -> bool:
    """A delta chain is usable only if it is numbered 1..n without a gap and each delta's parent hash equals the
    previous delta's board hash."""
    for i, s in enumerate(seqs):
        if s != i + 1 or (i > 0 and parents[i] != boards[i - 1]):
            return False
    return True


class Results(F.Results):
    """``nba_frozen.Results`` with configurable replication cohorts (history rows replicate across the two halves of 2025-26)."""

    def __init__(self):
        super().__init__(); self.pairs = {}

    def add(self, *a, cohorts=(COH1, COH2, POOLED), **kw):
        n0 = len(self.rows)
        super().add(*a, **kw)
        for r in self.rows[n0:]:
            r["_pair"] = cohorts[:2]; r["headline"] = bool(kw.get("headline") and r["cohort"] == cohorts[2])

    def finalize(self):
        rows = super().finalize()
        key = lambda r: (r["market_family"], r["metric"], r["challenger_arm"], r["reference"])
        by = {}
        for r in rows:
            by.setdefault(key(r), {})[r["cohort"]] = r["diff"]
        for r in rows:
            a, b = r.pop("_pair"); c = by[key(r)]
            r["replicated"] = bool(a in c and b in c and c[a] < 0 and c[b] < 0)
            r["verdict"] = C.verdict_from(r["ci95"][0], r["ci95"][1], r["p_holm"], r["replicated"])
        return rows


# =============================================================================================== history (owner archive)
def load_history(repo: Path):
    """ESPN player and team games, 2023-24..2025-26 from main and 2026-27 from the capture-worker archive (which holds
    the complete box through the last finished slate). Preseason is dropped. Returns (player_games, team_games)."""
    def rd(commit, path):
        return pd.read_parquet(io.BytesIO(F._git(repo, "show", f"{commit}:{path}")))
    pgs, tgs = [], []
    for s in HIST_SEASONS:
        c, base = (DA_COMMIT, "history/espn") if s == "2026-27" else (F.MAIN_COMMIT, "data/history/espn")
        pgs.append(rd(c, f"{base}/player_games_{s}.parquet")); tgs.append(rd(c, f"{base}/team_games_{s}.parquet"))
    pg = pd.concat(pgs, ignore_index=True); tg = pd.concat(tgs, ignore_index=True)
    pg = pg[pg.season_type != "preseason"].copy(); tg = tg[tg.season_type != "preseason"].copy()
    for d in (pg, tg):
        d["date"] = pd.to_datetime(d.game_date_et); d["sidx"] = d.season.map({s: i for i, s in enumerate(HIST_SEASONS)})
        d["team"] = d.team_id.map(V1.TEAM_TRICODES)
    pg["entity_id"] = "espn:" + (-pg.nba_id).astype("int64").astype(str)
    pg["one"] = 1.0
    return pg, tg.sort_values(["date", "game_id", "team_id"]).reset_index(drop=True)


def rate_states(pg: pd.DataFrame) -> dict:
    """Played rows sorted by player/time with pre-game and post-game decayed sums at half-lives 8, 20 and 80 games,
    plus within-season sums and previous-season totals (for the structured-prior ablation)."""
    d = pg[pg.minutes > 0].sort_values(["nba_id", "date", "game_id"]).reset_index(drop=True)
    X = d[COLS].to_numpy(float); pid = d.nba_id.to_numpy(); si = d.sidx.to_numpy()
    st = dict(d=d)
    for hl in (8, 20, 80):
        st[f"pre{hl}"], st[f"post{hl}"] = decayed_sums(X, pid, si, hl)
    st["cur20"], _ = decayed_sums(X, pid, si, 20, reset_season=True)
    tot = d.groupby(["nba_id", "sidx"])[COLS].sum()
    st["prev"] = np.nan_to_num(tot.reindex(pd.MultiIndex.from_arrays([d.nba_id, d.sidx - 1])).to_numpy(float))
    return st


def bucket_priors(d: pd.DataFrame, mpg_now: np.ndarray):
    """League per-minute priors by minutes-per-game bucket, taken from the COMPLETE previous season (point-in-time for
    every row of the current season). Returns (table {(season_idx, bucket): {col: sum}}, bucket per row)."""
    bk = np.digitize(mpg_now, MPG_EDGES)
    g = d.assign(bk=bk).groupby(["sidx", "bk"])[COLS].sum()
    return {k: v.to_dict() for k, v in g.iterrows()}, bk


def prior_rate(tab: dict, sidx, bk, num, den="minutes") -> np.ndarray:
    """Prior num/den for each row from season sidx-1 (season 0 falls back to itself: burn-in only, never evaluated)."""
    out = np.zeros(len(sidx))
    for i, (s, b) in enumerate(zip(sidx, bk)):
        t = tab.get((s - 1, b)) or tab.get((max(s - 1, 0), 0)) or tab.get((s, b))
        n = sum(w * t[c] for c, w in num) if isinstance(num, list) else t[num]
        dn = sum(w * t[c] for c, w in den) if isinstance(den, list) else t[den]
        out[i] = n / dn if dn > 0 else 0.0
    return out


TSA = [("fga", 1.0), ("fta", 0.44)]


def _tsa(S):
    return S[:, CI["fga"]] + 0.44 * S[:, CI["fta"]]


def rates_from_states(S8, S20, S80, tab, sidx) -> dict:
    """Per-minute rates from decayed sums. ``base_*`` = reproduction baseline; ``ue_points`` = usage (true-shot attempts
    per minute, half-life 8) x efficiency (points per true-shot attempt, half-life 80, shrunk by 100 attempts)."""
    mpg = np.where(S20[:, 0] > 0, S20[:, 1] / np.maximum(S20[:, 0], 1e-9), 0.0)
    bk = np.digitize(mpg, MPG_EDGES)
    out = dict(mpg=mpg, bk=bk)
    for s, c in HS.items():
        out[f"base_{s}"] = shrunk_rate(S20[:, CI[c]], S20[:, 1], prior_rate(tab, sidx, bk, c), BASE_K)
    u = shrunk_rate(_tsa(S8), S8[:, 1], prior_rate(tab, sidx, bk, TSA), BASE_K)
    e = shrunk_rate(S80[:, CI["pts"]], _tsa(S80), prior_rate(tab, sidx, bk, "pts", TSA), 100.0)
    out["ue_points"] = u * e
    out["use"] = shrunk_rate(_tsa(S20) + S20[:, CI["tov"]], S20[:, 1], prior_rate(tab, sidx, bk, TSA), BASE_K)
    return out


def vacated_usage(d: pd.DataFrame, post8: np.ndarray, post20: np.ndarray, window: int = 10) -> np.ndarray:
    """Per played row: expected possessions-used per game of the team's recent-rotation players (appeared in the previous
    ``window`` team games of the season) who do NOT appear in this game, from their last earlier state. In history this
    is retrospective (who actually sat), an upper bound on what a T-60 injury report can know."""
    st = pd.DataFrame(dict(nba_id=d.nba_id.to_numpy(), date=d.date.to_numpy(), last_team=d.team_id.to_numpy(),
                           w=post8[:, 1] / np.maximum(post8[:, 0], 1e-9),
                           u=(_tsa(post20) + post20[:, CI["tov"]]) / np.maximum(post20[:, 1], 1e-9))).sort_values(["date", "nba_id"])
    tg = d[["game_id", "team_id", "season", "date"]].drop_duplicates().sort_values(["team_id", "season", "date", "game_id"])
    played = {k: set(v) for k, v in d.groupby(["game_id", "team_id"]).nba_id}
    rows = []
    for (team, _), g in tg.groupby(["team_id", "season"], sort=False):
        gl = list(zip(g.game_id, g.date))
        for t in range(1, len(gl)):
            sets = [played[(gid, team)] for gid, _ in gl[max(0, t - window):t]]
            cnt = {}
            for s in sets:
                for p in s:
                    cnt[p] = cnt.get(p, 0) + 1
            cur = played[(gl[t][0], team)]
            rows += [(gl[t][0], gl[t][1], team, p, c / len(sets)) for p, c in cnt.items() if p not in cur]
    ab = pd.DataFrame(rows, columns=["game_id", "date", "team_id", "nba_id", "frac"]).sort_values(["date", "nba_id"])
    ab = pd.merge_asof(ab, st, on="date", by="nba_id", allow_exact_matches=False)
    ab = ab[ab.last_team == ab.team_id]
    v = (ab.w * ab.frac * ab.u).groupby([ab.game_id, ab.team_id]).sum()
    return pd.MultiIndex.from_arrays([d.game_id, d.team_id]).map(v).to_numpy(float)


def opponent_table(d: pd.DataFrame, y: np.ndarray, f: np.ndarray, halflife: float = 20.0, k_games: float = 10.0) -> pd.DataFrame:
    """Defence "allowed / expected" ratio per opponent AFTER each of its game dates (decayed over games, shrunk toward 1
    by ``k_games``). Look it up with ``opponent_lookup`` (strictly earlier dates only)."""
    g = pd.DataFrame(dict(opp=d.opp_team_id.to_numpy(), date=d.date.to_numpy(), a=y, e=f)).groupby(["opp", "date"]).sum().reset_index().sort_values(["opp", "date"])
    grp = g.groupby("opp", sort=False)
    ea = grp.a.transform(lambda s: s.ewm(halflife=halflife).mean()); ee = grp.e.transform(lambda s: s.ewm(halflife=halflife).mean())
    n = grp.cumcount().to_numpy(float) + 1.0
    g["r"] = (n * (ea / ee).to_numpy() + k_games) / (n + k_games)
    return g[["opp", "date", "r"]].sort_values(["date", "opp"]).reset_index(drop=True)


def opponent_lookup(tab: pd.DataFrame, opp, date) -> np.ndarray:
    """Ratio from the opponent's latest game dated strictly before ``date`` (1.0 when it has none)."""
    q = pd.DataFrame(dict(opp=np.asarray(opp), date=pd.to_datetime(np.asarray(date)), i=np.arange(len(opp)))).sort_values(["date", "opp"])
    q["opp"] = q.opp.astype(tab.opp.dtype)
    m = pd.merge_asof(q, tab, on="date", by="opp", allow_exact_matches=False).sort_values("i")
    return m.r.fillna(1.0).to_numpy(float)


def ridge_team_reproduction(tg: pd.DataFrame, alpha: float = 8.0, halflife_days: float = 120.0, prior_season_decay: float = 0.35) -> pd.DataFrame:
    """Walk-forward reproduction of the production team model's rung C: weekly-refit schedule-adjusted ridge ratings
    for pace (per 48 min) and points per 100 possessions, expected points = pace x efficiency (regulation only, as the
    production code computes it). Uses only games in strictly earlier weekly blocks."""
    from sklearn.linear_model import Ridge
    t = tg.copy()
    t["pace48"] = t.possessions * 48.0 / (48.0 + 5.0 * t.n_ot); t["ortg"] = 100.0 * t.pts / t.possessions
    t["block"] = (t.sidx * 100 + ((t.date - t.groupby("sidx").date.transform("min")).dt.days // 7)).astype(int)
    teams = np.sort(pd.unique(np.concatenate([t.team_id.to_numpy(), t.opp_team_id.to_numpy()]))); T = len(teams)
    oi = np.searchsorted(teams, t.team_id.to_numpy()); di = np.searchsorted(teams, t.opp_team_id.to_numpy())
    home = t.home.to_numpy(float); blk = t.block.to_numpy(); sidx = t.sidx.to_numpy(); dt = t.date.to_numpy()
    exp_pace = np.full(len(t), np.nan); exp_ortg = np.full(len(t), np.nan)
    for b in np.unique(blk):
        m = blk < b; cur = blk == b
        if m.sum() < 20:
            continue
        w = prior_season_decay ** np.clip(sidx[cur][0] - sidx[m], 0, None) * 0.5 ** ((dt[cur].min() - dt[m]) / np.timedelta64(1, "D") / halflife_days)
        n = int(m.sum()); Xo = np.zeros((n, 2 * T + 1)); Xo[np.arange(n), oi[m]] = 1.0; Xo[np.arange(n), T + di[m]] = 1.0; Xo[:, -1] = home[m]
        rp = Ridge(alpha=alpha).fit(Xo[:, :-1], t.pace48.to_numpy()[m], sample_weight=w)
        re_ = Ridge(alpha=alpha).fit(Xo, t.ortg.to_numpy()[m], sample_weight=w)
        po, pd_ = rp.coef_[:T], rp.coef_[T:]
        exp_pace[cur] = rp.intercept_ + po[oi[cur]] + pd_[oi[cur]] + po[di[cur]] + pd_[di[cur]]
        exp_ortg[cur] = re_.intercept_ + re_.coef_[:T][oi[cur]] + re_.coef_[T:2 * T][di[cur]] + re_.coef_[-1] * home[cur]
    t["exp_pace"] = exp_pace; t["exp_ortg"] = exp_ortg; t["exp_pts"] = exp_pace * exp_ortg / 100.0
    return t


# =============================================================================================== restored T-60 boards (data-archive)
_TS_RE = re.compile(r"_(\d{8}T\d{6}Z)_")
_STAT_OF = {"KXNBAPTS": "points", "KXNBAREB": "rebounds", "KXNBAAST": "assists", "KXNBA3PT": "threes", "KXNBAPRA": "pra",
            "KXNBASPREAD": "spread", "KXNBATOTAL": "total", "KXNBATEAMTOTAL": "team_total", "KXNBAGAME": "winner"}


def _keep(t: str) -> bool:
    return t.split("-", 1)[0] in GAME_SERIES


def et_date(ts) -> str:
    return pd.Timestamp(int(ts), unit="s", tz="UTC").tz_convert("America/New_York").strftime("%Y-%m-%d")


def restore_boards_t60(repo: Path, games: pd.DataFrame, code_to_pid: dict, commit: str = DA_COMMIT):
    """Rebuild, for every game in ``games`` (game_id, tip_ts, home, away), the Kalshi board as it stood at the latest
    capture at or before tip - 60 min: newest full checkpoint at or before the cutoff plus that checkpoint's own delta
    chain up to the cutoff (the owner's ``archive.reconstruct`` rule). A chain with a gap or a parent-hash mismatch is
    refused (no board for that game). Returns (rows in the ``load_market_t60`` shape with ``source``, stats)."""
    ck = sorted((F._iso_s(_TS_RE.search(p).group(1)), p, s) for p, s in F.ls_tree(repo, commit, "kalshi/markets/") if p.endswith(".jsonl.gz"))
    dl = sorted((F._iso_s(_TS_RE.search(p).group(1)), p, s) for p, s in F.ls_tree(repo, commit, "kalshi/markets_delta/") if p.endswith(".json.gz"))
    ckt = [c[0] for c in ck]
    gkey = {(et_date(t), frozenset((h, a))): g for g, t, h, a in zip(games.game_id, games.tip_ts, games.home, games.away)}
    tip = dict(zip(games.game_id, games.tip_ts.astype(int)))
    plan = {}; stats = dict(n_checkpoints=len(ck), n_deltas=len(dl), n_games=len(games), no_checkpoint=0, chain_refused=0, deltas_applied=0, stale=0,
                            n_player_tickers_unmapped=0)
    for g, t in tip.items():
        i = bisect.bisect_right(ckt, t - F.FREEZE_S) - 1
        if i < 0:
            stats["no_checkpoint"] += 1
        else:
            plan.setdefault(i, []).append((t - F.FREEZE_S, g))
    rows = []
    for i, need in sorted(plan.items()):
        ct, cp, cs = ck[i]; need = sorted(need); board = {}
        for line in gzip.decompress(next(F.read_blobs(repo, [cs]))).decode().splitlines():
            if '"KXNBA' in line:
                r = json.loads(line)
                if _keep(r["ticker"]):
                    board[r["ticker"]] = {k: r.get(k) for k in BOARD_FIELDS}
        cand = [d for d in dl if ct < d[0] <= need[-1][0]]
        chain = []
        for d, raw in zip(cand, F.read_blobs(repo, [d[2] for d in cand])):
            j = json.loads(gzip.decompress(raw))
            if j.get("base_path") == cp:
                chain.append((int(j["seq"]), d[0], j))
        chain.sort(key=lambda x: x[0])
        good = chain_ok([c[0] for c in chain], [c[2].get("parent_board_sha256") for c in chain], [c[2].get("board_sha256") for c in chain])
        ni = 0; obs = ct; applied = 0

        def emit(upto):
            nonlocal ni
            while ni < len(need) and need[ni][0] < upto:
                cut, g = need[ni]; ni += 1
                if not good:
                    stats["chain_refused"] += 1; continue
                if cut - obs > F.MAX_QUOTE_AGE_S:
                    stats["stale"] += 1; continue
                for tk, r in board.items():
                    pz = parse_board_ticker(tk)
                    if pz is None or gkey.get((pz["date"], frozenset((pz["home"], pz["away"])))) != g:
                        continue
                    q = r.get("_quote_cents") or {}; yb, ya = q.get("yes_bid"), q.get("yes_ask"); fs = r.get("floor_strike")
                    pid = code_to_pid.get(pz["code"]) if pz["code"] else None
                    if pz["code"] and pid is None:
                        stats["n_player_tickers_unmapped"] += 1
                    rows.append(dict(ticker=tk, family=r.get("_family"), series=pz["series"], game_id=g, tip_ts=tip[g], obs_ts=obs, player_id=pid,
                                     team=pz["side"], side_team=pz["side"], stat=_STAT_OF[pz["series"]], threshold=float(fs) if fs is not None else np.nan,
                                     k=float(pz["k"]) if pz["k"] is not None else np.nan,
                                     comparator="gt" if r.get("strike_type") == "greater" else ("winner" if pz["series"] == "KXNBAGAME" else None),
                                     quote_class=quote_class(r.get("status"), yb, ya), yes_bid=None if yb is None else yb / 100.0,
                                     yes_ask=None if ya is None else ya / 100.0, no_ask=None if q.get("no_ask") is None else q["no_ask"] / 100.0,
                                     support=r.get("_support"), source="data-archive_restored", n_deltas=applied))

        for seq, dts, j in chain:
            emit(dts)                                   # cutoffs strictly before this delta's capture time see the board before it
            if ni >= len(need):
                break
            good = apply_board_delta(board, j, _keep) and good
            obs = dts; applied += 1; stats["deltas_applied"] += 1
        emit(10 ** 12)
    df = pd.DataFrame(rows)
    stats["n_tickers"] = len(df); stats["n_games_with_board"] = int(df.game_id.nunique()) if len(df) else 0
    return df, stats


def unify_market(M_pd: pd.DataFrame, M_da: pd.DataFrame) -> pd.DataFrame:
    """projection-data T-60 rows where the game has any; restored data-archive rows only for games with none."""
    a = M_pd.assign(source="projection-data_T-60")
    b = M_da[~M_da.game_id.isin(set(M_pd.game_id))] if len(M_da) else M_da
    return pd.concat([a, b[[c for c in a.columns if c in b.columns]]], ignore_index=True)


def restore_checks(M_pd: pd.DataFrame, M_da: pd.DataFrame, stats: dict):
    """Computed agreement of the restored boards with the owner's own T-60 snapshots on the games that have both."""
    j = M_da.merge(M_pd, on="ticker", suffixes=("", "_pd"))
    same = j[j.obs_ts == j.obs_ts_pd]
    two = same[(same.quote_class_pd == "TWO_SIDED")]
    c = lambda s: (s.astype(float) * 100).round()
    px = float(((c(two.yes_bid) == c(two.yes_bid_pd)) & (c(two.yes_ask) == c(two.yes_ask_pd))).mean()) if len(two) else np.nan
    cls = float((same.quote_class.eq("TWO_SIDED") == same.quote_class_pd.eq("TWO_SIDED")).mean()) if len(same) else np.nan
    eqn = lambda a, b: (a.astype(float).fillna(-9) == b.astype(float).fillna(-9))
    eqs = lambda a, b: (a.fillna("") == b.fillna(""))
    par = float((eqn(j.threshold, j.threshold_pd) & eqn(j.k, j.k_pd) & eqs(j.family, j.family_pd) & eqs(j.game_id, j.game_id_pd)
                 & (eqs(j.side_team, j.side_team_pd) | j.side_team_pd.isna())).mean()) if len(j) else np.nan
    pl = j[j.player_id_pd.notna()]
    pm = float((pl.player_id == pl.player_id_pd).mean()) if len(pl) else np.nan
    leak = int((M_da.obs_ts > M_da.tip_ts - F.FREEZE_S).sum()); age = (M_da.tip_ts - F.FREEZE_S - M_da.obs_ts) / 60.0
    return [
        _chk("restored_boards_delta_chains_contiguous_and_hash_linked", stats["chain_refused"] == 0 and stats["n_games_with_board"] > 0,
             f"{stats['n_checkpoints']} checkpoints and {stats['n_deltas']} deltas on {DA_BRANCH}@{DA_COMMIT[:7]}; {stats['deltas_applied']} deltas applied; games refused for a "
             f"sequence gap or parent-hash mismatch: {stats['chain_refused']}; games with no checkpoint at or before the cutoff: {stats['no_checkpoint']}; "
             f"games whose latest board was older than {F.MAX_QUOTE_AGE_S // 60} min at the cutoff (dropped): {stats['stale']}"),
        _chk("leak_guard_restored_board_le_tip_minus_60", leak == 0 and len(M_da) > 0,
             f"{len(M_da)} restored ticker rows in {stats['n_games_with_board']} games; {leak} observed after tip-60; board age at the cutoff median "
             f"{float(age.median()):.1f} min, max {float(age.max()):.1f} min"),
        _chk("restored_prices_equal_owner_t60_snapshot_same_capture", len(two) > 1000 and px >= 0.995,
             f"{len(j)} tickers present in both sources; {len(same)} share the same capture instant; on the {len(two)} two-sided of those, bid and ask are equal to "
             f"the cent in {px:.4f}; two-sided class agrees in {cls:.4f}"),
        _chk("restored_ticker_parse_equals_owner_mapping", len(j) > 1000 and par >= 0.999 and pm >= 0.999,
             f"family, game, side, threshold and K parsed from the ticker equal the owner's mapping on {par:.4f} of {len(j)} overlapping tickers; player id via the "
             f"ticker player code equals the owner's on {pm:.4f} of {len(pl)}; restored player tickers with a code never seen on projection-data (left unmapped, "
             f"not scored): {stats['n_player_tickers_unmapped']}"),
    ]


# =============================================================================================== history walk-forward
def pois_dev(y, mu):
    y = np.asarray(y, float); mu = np.maximum(np.asarray(mu, float), 1e-6)
    return 2.0 * (np.where(y > 0, y * np.log(np.maximum(y, 1e-12) / mu), 0.0) - (y - mu))


ONLINE_K_GRID = [250, 1000, 4000]            # shrinkage of the online level ratio, in player-games (x mean stat)
TEAM_K_GRID = [20, 60, 150]                  # shrinkage of the additive team level correction, in team-games


def history_walkforward(pg: pd.DataFrame, RH: Results) -> dict:
    """Rate components on prior seasons. Target: stat given ACTUAL minutes (isolates the per-minute rate). Metric: Poisson
    deviance (proper for the mean; absolute error rewards under-forecasting a skewed count and is reported only in the
    summary). Every coefficient is fitted on 2024-25; 2025-26 is the test season (two halves)."""
    st = rate_states(pg); d = st["d"]; si = d.sidx.to_numpy(); m = d.minutes.to_numpy(float)
    reg = (d.season_type == "regular").to_numpy()
    mpg = np.where(st["pre20"][:, 0] > 0, st["pre20"][:, 1] / np.maximum(st["pre20"][:, 0], 1e-9), 0.0)
    tab, bk = bucket_priors(d, mpg)
    r = rates_from_states(st["pre8"], st["pre20"], st["pre80"], tab, si)
    tr = reg & (si == HIST_SEASONS.index(TRAIN_H)); te = reg & (si == HIST_SEASONS.index(TEST_H))
    ds = d.game_date_et.to_numpy()
    masks = {H1: te & (ds < H_SPLIT), H2: te & (ds >= H_SPLIT), HP: te}
    gid = d.game_id.to_numpy(); home = d.home.to_numpy(float) - 0.5
    vac = np.nan_to_num(vacated_usage(d, st["post8"], st["post20"])); vz = (vac - vac[tr].mean()) / vac[tr].std()
    ref = "repro_rate_ewm_hl20_k30"; prm = {}; opp_tabs = {}; summ = {}
    for s, c in HS.items():
        y = d[c].to_numpy(float); f = r[f"base_{s}"] * m; dv0 = pois_dev(y, f); arch = [F.ARCH[s]]; fam = F.FAMILY[s]
        cands = {}
        if s == "points":
            cands["usage_x_efficiency"] = r["ue_points"] * m
        kbest = min(ONLINE_K_GRID, key=lambda K: pois_dev(y, f * online_level(d.date, si, np.where(reg, y, np.nan), np.where(reg, f, np.nan), K * y[tr].mean()))[tr].mean())
        cands["online_level"] = f * online_level(d.date, si, np.where(reg, y, np.nan), np.where(reg, f, np.nan), kbest * y[tr].mean())
        bh = poisson_beta(y[tr], f[tr], home[tr]); cands["home_factor"] = f * np.exp(bh * home)
        bv = poisson_beta(y[tr], f[tr], vz[tr]); cands["teammate_out_usage_retrospective"] = f * np.exp(bv * vz)
        ot = opponent_table(d, y, f); lo = np.log(opponent_lookup(ot, d.opp_team_id.to_numpy(), d.date.to_numpy()))
        bo = poisson_beta(y[tr], f[tr], lo[tr]); cands["opponent_factor"] = f * np.exp(bo * lo); opp_tabs[s] = ot
        pw = 300.0 * np.minimum(1.0, st["prev"][:, 1] / 500.0); pr = prior_rate(tab, si, bk, c)
        cands["structured_prior_season_prior"] = shrunk_rate(st["cur20"][:, CI[c]] + pw * shrunk_rate(st["prev"][:, CI[c]], st["prev"][:, 1], pr, 300.0),
                                                             st["cur20"][:, 1] + pw, pr, BASE_K) * m
        for name, p in cands.items():
            RH.add(fam, arch, "poisson_deviance_given_actual_minutes", f"H_{name}", ref, pois_dev(y, p), dv0, gid, masks, cohorts=(H1, H2, HP))
        prm[s] = dict(online_k_player_games=kbest, home_beta=bh, vacated_usage_beta_per_sd=bv, opponent_beta=bo, mean_stat_train=float(y[tr].mean()))
        summ[s] = dict(n_train=int(tr.sum()), n_test=int(te.sum()), baseline_mae_test=float(np.abs(y - f)[te].mean()),
                       baseline_actual_over_expected={"train_2024-25": float(y[tr].sum() / f[tr].sum()), "test_2025-26": float(y[te].sum() / f[te].sum())},
                       mae_diff_test={k: float(np.abs(y - p)[te].mean() - np.abs(y - f)[te].mean()) for k, p in cands.items()})
        if s == "points":
            res = y - f; z = np.abs(res) / np.sqrt(np.maximum(f, 0.5))
            gwt = d.groupby(["nba_id", "team_id"]).cumcount().to_numpy(); moved = (d.groupby("nba_id").team_id.transform("nunique") > 1).to_numpy()
            ps = d.groupby("nba_id").started.shift(1); tgn = d.groupby(["team_id", "season"]).game_id.transform(lambda x: pd.factorize(x)[0]).to_numpy()
            prevd = d.groupby("nba_id").date.shift(1); gap = (d.date - prevd).dt.days.to_numpy()
            sl = {"all": te, "first_10_games_with_a_new_team": te & moved & (gwt < 10) & (st["pre80"][:, 0] > 0),
                  "fewer_than_3_prior_games": te & (st["pre80"][:, 0] < 3), "starting_role_changed_vs_previous_game": te & ps.notna().to_numpy() & (d.started.to_numpy() != ps.fillna(False).to_numpy().astype(bool)),
                  "team_game_1_to_10": te & (tgn < 10), "top_decile_vacated_teammate_usage": te & (vac > np.quantile(vac[tr], 0.9)),
                  "home": te & (home > 0), "away": te & (home < 0), "second_night_of_back_to_back": te & (gap == 1),
                  "minutes_8_plus_above_recent_average": te & (m - mpg >= 8) & (st["pre20"][:, 0] > 3), "minutes_8_plus_below_recent_average": te & (mpg - m >= 8) & (st["pre20"][:, 0] > 3)}
            summ["points_error_slices_test_2025-26"] = {k: dict(n=int(v.sum()), actual_over_expected=float(y[v].sum() / f[v].sum()), mae=float(np.abs(res)[v].mean()),
                                                                 mean_abs_error_over_sqrt_expected=float(z[v].mean())) for k, v in sl.items()}
    return dict(state=st, tab=tab, params=prm, opp_tabs=opp_tabs, summary=summ, reference=ref)


def team_walkforward(tg: pd.DataFrame, RH: Results) -> dict:
    """Team points on prior seasons: reproduction of the production pace x efficiency ridge vs (a) an overtime uplift
    (point-in-time league mean of (48 + 5 OT) / 48) and (b) an additive online league-level correction on top."""
    t = ridge_team_reproduction(tg); t = t[t.exp_pts.notna()].copy()
    reg = (t.season_type == "regular").to_numpy(); otf = ((48.0 + 5.0 * t.n_ot) / 48.0).to_numpy()
    g = pd.DataFrame(dict(d=t.date.to_numpy(), o=np.where(reg, otf, np.nan))).groupby("d").o.agg(["sum", "count"]).sort_index()
    pit = ((g["sum"].cumsum() - g["sum"]) / (g["count"].cumsum() - g["count"]).replace(0, np.nan)).fillna(1.0)
    A = t.exp_pts.to_numpy() * t.date.map(pit).to_numpy(); y = t.pts.to_numpy(float); si = t.sidx.to_numpy(); ds = t.game_date_et.to_numpy()
    tr = reg & (si == HIST_SEASONS.index(TRAIN_H)); te = reg & (si == HIST_SEASONS.index(TEST_H))
    lev = lambda K: online_level(t.date, si, np.where(reg, y, np.nan), np.where(reg, A, np.nan), K, additive=True)
    kbest = min(TEAM_K_GRID, key=lambda K: np.abs(y - A - lev(K))[tr].mean())
    B = A + lev(kbest); masks = {H1: te & (ds < H_SPLIT), H2: te & (ds >= H_SPLIT), HP: te}
    ref = "repro_ridge_pace_x_efficiency"; e0 = np.abs(y - t.exp_pts.to_numpy()); gid = t.game_id.to_numpy()
    RH.add("team_total", ["NBA:team_total"], "abs_error_team_points", "H_overtime_uplift", ref, np.abs(y - A), e0, gid, masks, cohorts=(H1, H2, HP))
    RH.add("team_total", ["NBA:team_total"], "abs_error_team_points", "H_overtime_uplift_plus_online_level", ref, np.abs(y - B), e0, gid, masks, cohorts=(H1, H2, HP))
    dec = {}
    for s in HIST_SEASONS[1:]:
        x = t[reg & (t.season == s).to_numpy()]
        if len(x):
            o = (48.0 + 5.0 * x.n_ot) / 48.0; pace48 = x.possessions * 48.0 / (48.0 + 5.0 * x.n_ot); ortg = 100.0 * x.pts / x.possessions
            dec[s] = dict(n_team_games=int(len(x)), forecast_minus_actual=float((x.exp_pts - x.pts).mean()), overtime_part=float(-(x.pts * (1 - 1 / o)).mean()),
                          pace_part=float(((x.exp_pace - pace48) * ortg / 100).mean()), efficiency_part=float(((x.exp_ortg - ortg) * x.exp_pace / 100).mean()),
                          mae=float((x.exp_pts - x.pts).abs().mean()), league_points=float(x.pts.mean()), league_pace48=float(pace48.mean()), league_ortg=float(ortg.mean()),
                          share_of_points_scored_in_overtime=float(x.ot_pts.sum() / x.pts.sum()))
    return dict(k_team_games=kbest, reproduction_bias_decomposition=dec, reference=ref)


# =============================================================================================== 2026-27: frozen forecasts
W_GRID = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
ARM = "C3_" + CHALLENGER_ID


def load_game_context(repo: Path, commit: str = F.PD_COMMIT) -> dict:
    """The team model's own archived context (expected pace, expected efficiency, rest) of the latest game forecast
    generated and archived at or before tip - 60 min. {game_id: {home_exp_pace: ..}}"""
    best = {}
    for _, r in F.iter_jsonl(repo, commit, "game_forecasts/nba"):
        tip = F._iso_s(r["game_start_utc"]); t = max(F._iso_s(r["generated_utc"]), F._iso_s(r["archived_utc"]))
        if t <= tip - F.FREEZE_S and (r["game_id"] not in best or t > best[r["game_id"]][0]):
            best[r["game_id"]] = (t, r.get("context") or {})
    return {g: v[1] for g, v in best.items()}


def frame_states(X: pd.DataFrame, hist: dict) -> dict:
    """Independent per-minute rates for every frame row from the player's last played game dated strictly before the
    frame game (no state -> the league prior). Returns the rates dict plus ``state_date`` and ``j`` (state row or -1)."""
    st = hist["state"]; d = st["d"]
    post = pd.DataFrame(dict(entity_id=d.entity_id.to_numpy(), date=d.date.to_numpy(), j=np.arange(len(d)))).sort_values(["date", "entity_id"])
    q = pd.DataFrame(dict(entity_id=X.entity_id.to_numpy(), date=pd.to_datetime(X.date_s.to_numpy()), i=np.arange(len(X)))).sort_values(["date", "entity_id"])
    q["date"] = q.date.astype(post.date.dtype)
    j = pd.merge_asof(q, post, on="date", by="entity_id", allow_exact_matches=False).sort_values("i").j.fillna(-1).to_numpy(int)
    pick = lambda a: np.where((j >= 0)[:, None], a[np.maximum(j, 0)], 0.0)
    r = rates_from_states(pick(st["post8"]), pick(st["post20"]), pick(st["post80"]), hist["tab"], np.full(len(X), HIST_SEASONS.index("2026-27")))
    r["j"] = j; r["state_date"] = pd.Series(d.date.to_numpy()[np.maximum(j, 0)]).where(j >= 0).to_numpy()
    r["n_prior_games"] = pick(st["post80"])[:, 0]
    return r


def _crps(pmf, y):
    return F._crps_dense(pmf, np.asarray(y).astype(int))


def run(repo: Path | None = None, verbose: bool = True) -> dict:
    repo = Path(repo) if repo else F.repo_path()
    say = (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)
    for c in (F.PD_COMMIT, F.MAIN_COMMIT, DA_COMMIT):
        if not F.has_commit(repo, c):
            raise RuntimeError(f"commit {c} not in {repo}; fetch projection-data / main / data-archive first")
    chk = dict(hist=[], level=[], mkt=[], coh=[], lin=[])

    # ------------------------------------------------------------------ history walk-forward (prior seasons)
    pg, tg = load_history(repo)
    RH = Results()
    hist = history_walkforward(pg, RH); thist = team_walkforward(tg, RH)
    hrows = RH.finalize()
    hv = {(r["market_family"], r["challenger_arm"]): r["verdict"] for r in hrows if r["cohort"] == HP}
    ok_h = lambda s, name: hv.get((F.FAMILY[s] if s in F.FAMILY else s, f"H_{name}")) == "VALIDATED_IMPROVEMENT"
    d = hist["state"]["d"]
    lead = int((d.groupby("nba_id").date.diff().dt.days.dropna() <= 0).sum())
    chk["hist"].append(_chk("history_one_row_per_player_date_sorted", lead == 0 and not d.duplicated(["nba_id", "game_id"]).any(),
                            f"{len(d)} played player-games {d.game_date_et.min()}..{d.game_date_et.max()} in {d.game_id.nunique()} games; players with two rows on one "
                            f"date or out of order: {lead}; pre-game sums use earlier rows only (unit-tested)"))
    tm = pg[pg.minutes > 0].groupby(["game_id", "team_id"]).minutes.sum()
    okm = float(((tm >= 235) & (tm <= 345)).mean())
    chk["hist"].append(_chk("history_team_minutes_plausible", okm >= 0.99, f"{len(tm)} team-games: share with summed minutes in [235, 345] = {okm:.4f}"))
    j27 = pg[(pg.season == "2026-27") & (pg.season_type == "regular")]
    say(f"history {len(pg)} rows; validated on 2025-26: {sorted(k for k, v in hv.items() if v == 'VALIDATED_IMPROVEMENT')}")

    # ------------------------------------------------------------------ frozen 2026-27 forecasts, outcomes, markets
    fc, fc_stats = F.load_frozen_forecasts(repo); out = F.load_outcomes(repo); tout = F.load_team_outcomes(repo); gf = F.load_game_forecasts(repo)
    M_pd, m_stats = F.load_market_t60(repo)
    code_to_pid = {t.split("-")[2]: p for t, p in zip(M_pd.ticker, M_pd.player_id) if isinstance(p, str) and t.count("-") == 3}
    M_da, r_stats = restore_boards_t60(repo, gf[["game_id", "tip_ts", "home", "away"]], code_to_pid)
    chk["mkt"] += restore_checks(M_pd, M_da, r_stats)
    M = unify_market(M_pd, M_da)
    X = F.build_frame(fc, out)
    N = len(X); date_s = X.date_s; gid = X.game_id.to_numpy()
    train = (date_s < F.TRAIN_END).to_numpy(); masks = F.cohort_masks(date_s)
    base = (X.has_pf & X.y_play & X.pf_mean_minutes.notna()).to_numpy()
    jo = j27.merge(out, on=["game_id", "entity_id"], how="inner")
    mis = int((jo.pts != jo.points).sum())
    chk["hist"].append(_chk("archive_box_2026-27_equals_projection_data_outcomes", mis == 0 and len(jo) > 3000,
                            f"{len(jo)} player-games present in both the {DA_BRANCH} ESPN box and the projection-data outcomes: points mismatches {mis}"))
    fs = frame_states(X, hist)
    sv = fs["j"] >= 0
    leak = int((fs["state_date"][sv] >= pd.to_datetime(date_s.to_numpy()[sv]).to_numpy()).sum())
    chk["hist"].append(_chk("leak_guard_rate_state_strictly_before_game_date", leak == 0 and sv.sum() > 0,
                            f"{int(sv.sum())}/{N} frame rows have a prior rate state; states dated on or after the game date: {leak}"))
    home_of = dict(zip(gf.game_id, gf.home)); away_of = dict(zip(gf.game_id, gf.away))
    opp = np.array([away_of.get(g) if home_of.get(g) == t else home_of.get(g) for g, t in zip(gid, X.team)], dtype=object)
    opp_id = np.array([V1.TRICODE_TO_TEAM.get(o, -1) if o else -1 for o in opp])
    pfmin = X.pf_mean_minutes.to_numpy(float)
    pf_pmf = {s: F._stack(X[f"pf_pmf_{s}"], F.KMAX[s]) for s in STATS + ["pra"]}
    kk = {s: np.arange(F.KMAX[s] + 1, dtype=float) for s in STATS + ["pra"]}
    c_pmf = {}; mu_c = {}; sel = {}; R = Results()
    for s in STATS:
        y = X[f"y_{s}"].to_numpy(float); pm = pf_pmf[s]; pmean = np.where(base, np.nan_to_num(pm) @ kk[s], np.nan)
        pfm = X[f"pf_mean_{s}"].to_numpy(float)
        rate = fs["ue_points"] if (s == "points" and ok_h(s, "usage_x_efficiency")) else fs[f"base_{s}"]
        use_opp = ok_h(s, "opponent_factor")
        of = opponent_lookup(hist["opp_tabs"][s], opp_id, pd.to_datetime(date_s.to_numpy())) ** hist["params"][s]["opponent_beta"] if use_opp else 1.0
        ind = rate * pfmin * of
        bt = base & train

        def crps_at(mu, mk):
            return float(_crps(tilt_pmf(pm[mk], pmean[mk] * mu[mk] / pfm[mk]), y[mk]).mean())
        grid = {w: crps_at((1 - w) * pfm + w * ind, bt) for w in W_GRID}
        w = min(grid, key=lambda q: (grid[q], q)); blend = (1 - w) * pfm + w * ind
        K = hist["params"][s]["online_k_player_games"] * hist["params"][s]["mean_stat_train"]
        L = online_level(date_s.to_numpy(), np.zeros(N), np.where(base, y, np.nan), np.where(base, blend, np.nan), K)
        c_on = crps_at(blend * L, bt); use_l = c_on < grid[w]
        mu = blend * (L if use_l else 1.0); mu_c[s] = mu
        c_pmf[s] = pm.copy(); c_pmf[s][base] = tilt_pmf(pm[base], pmean[base] * mu[base] / pfm[base])
        sel[s] = dict(independent_rate="usage_x_efficiency" if rate is fs.get("ue_points") else "ewm_hl20", opponent_factor_in_independent_rate=bool(use_opp),
                      weight_on_independent_rate=w, train_crps_by_weight=grid, online_level_k=K, online_level_train_crps=c_on, online_level_on=bool(use_l),
                      online_level_ratio_first_test_day=float(L[masks[POOLED]][0]) if masks[POOLED].any() else None,
                      online_level_ratio_last_day=float(L[-1]), n_train_rows=int(bt.sum()))
        R.add(F.FAMILY[s], [F.ARCH[s]], "crps_given_played", ARM, "pf_frozen", _crps(c_pmf[s], y), _crps(pm, y), gid, {k: v & base for k, v in masks.items()}, headline=True)
        R.add(F.FAMILY[s], [F.ARCH[s]], "abs_error_mean_given_played", ARM, "pf_frozen", np.abs(y - mu), np.abs(y - pfm), gid, {k: v & base for k, v in masks.items()})
        R.add(F.FAMILY[s], [F.ARCH[s]], "abs_error_given_actual_minutes", "independent_rate_x_actual_minutes", "pf_rate_x_actual_minutes",
              np.abs(y - rate * of * X.y_min.to_numpy(float)), np.abs(y - pfm / np.maximum(pfmin, 1.0) * X.y_min.to_numpy(float)), gid,
              {**{k: v & base for k, v in masks.items()}, ALLG: base}, note="rate isolated: both use the minutes actually played")
    pra_mu = X.pf_mean_pra.to_numpy(float) + sum(mu_c[s] - X[f"pf_mean_{s}"].to_numpy(float) for s in ("points", "rebounds", "assists"))
    bp = base & X.pf_pmf_pra.notna().to_numpy()
    c_pmf["pra"] = pf_pmf["pra"].copy(); pmean = np.nan_to_num(pf_pmf["pra"]) @ kk["pra"]
    c_pmf["pra"][bp] = tilt_pmf(pf_pmf["pra"][bp], pmean[bp] * pra_mu[bp] / X.pf_mean_pra.to_numpy(float)[bp])
    ypra = X.y_pra.to_numpy(float)
    R.add("player_pra", ["NBA:player_pra"], "crps_given_played", ARM, "pf_frozen", _crps(c_pmf["pra"], ypra), _crps(pf_pmf["pra"], ypra), gid,
          {k: v & bp for k, v in masks.items()}, headline=True)
    sums = max(float(np.nanmax(np.abs(c_pmf[s][base].sum(1) - 1))) for s in STATS)
    idem = max(float(np.nanmax(np.abs(tilt_pmf(pf_pmf[s][base][:200], (np.nan_to_num(pf_pmf[s][base][:200]) @ kk[s])) - pf_pmf[s][base][:200]))) for s in STATS)
    chk["level"].append(_chk("challenger_pmfs_sum_to_one_and_tilt_is_identity_at_ratio_one", sums < 1e-6 and idem < 1e-6,
                             f"max |sum-1| = {sums:.2e}; max |tilt(pf, own mean) - pf| on 200 rows per stat = {idem:.2e}"))
    Lchk = online_level(date_s.to_numpy(), np.zeros(N), np.where(base, X.y_points, np.nan), np.where(base, X.pf_mean_points, np.nan), 1.0)
    first = date_s.to_numpy() == date_s.min()
    d2 = np.sort(date_s.unique())[1]; m1 = base & first
    exp2 = (X.y_points[m1].sum() + 1.0) / (X.pf_mean_points[m1].sum() + 1.0)
    chk["level"].append(_chk("leak_guard_online_level_uses_strictly_earlier_dates", bool(np.all(Lchk[first] == 1.0)) and abs(Lchk[date_s.to_numpy() == d2][0] - exp2) < 1e-9,
                             f"first slate ratio is exactly 1 (no earlier outcomes): {bool(np.all(Lchk[first] == 1.0))}; second slate ratio equals the first slate's "
                             f"(sum actual + k) / (sum forecast + k) recomputed independently: {Lchk[date_s.to_numpy() == d2][0]:.6f} vs {exp2:.6f}"))
    chk["level"].append(_chk("component_switches_decided_on_train_window_only", int((train & masks[POOLED]).sum()) == 0,
                             f"TRAIN rows {int(train.sum())} (dates < {F.TRAIN_END}) and TEST rows {int(masks[POOLED].sum())} overlap: {int((train & masks[POOLED]).sum())}; "
                             + json.dumps({s: [sel[s]["weight_on_independent_rate"], sel[s]["online_level_on"]] for s in STATS})))

    # ------------------------------------------------------------------ prop rungs vs pf and vs the T-60 mid
    P = F.prop_rungs(M, X); rr = P[P.in_frame].copy(); ri = rr.row.to_numpy()
    rr = rr[base[ri]].copy(); ri = rr.row.to_numpy()
    rr["y"] = [float(X[f"y_{s}"].iat[i] >= k) for s, i, k in zip(rr.stat, ri, rr.k)]
    rr["p_pf"] = np.nan; rr["p_c"] = np.nan
    for s in STATS + ["pra"]:
        mk = (rr.stat == s).to_numpy()
        rr.loc[mk, "p_pf"] = F._sf_dense(pf_pmf[s][ri[mk]], rr.k.to_numpy()[mk]); rr.loc[mk, "p_c"] = F._sf_dense(c_pmf[s][ri[mk]], rr.k.to_numpy()[mk])
    rr["two"] = (rr.quote_class == "TWO_SIDED") & rr.yes_bid.notna() & rr.yes_ask.notna()
    rr["mid"] = np.where(rr.two, (rr.yes_bid.astype(float) + rr.yes_ask.astype(float)) / 2, np.nan)
    rr["date_s"] = date_s.to_numpy()[ri]; rr["gid"] = gid[ri]
    mkt_counts = {}
    for s in STATS + ["pra"]:
        g = rr[(rr.stat == s) & rr.two & rr.p_pf.notna()].reset_index(drop=True); fam = F.FAMILY[s]; arch = [f"NBA:{fam}"]
        rm = F.cohort_masks(g.date_s); cl = g.gid.to_numpy(); al = {**rm, ALLG: np.ones(len(g), bool)}
        b = lambda p: C.brier_rows(p, g.y)
        R.add(fam, arch, "brier_ladder_given_played_two_sided", ARM, "pf_frozen", b(g.p_c), b(g.p_pf), cl, rm)
        R.add(fam, arch, "brier_ladder_given_played_two_sided", ARM, "kalshi_t60_mid", b(g.p_c), b(g.mid), cl, rm)
        R.add(fam, arch, "brier_ladder_given_played_two_sided", "pf_frozen", "kalshi_t60_mid", b(g.p_pf), b(g.mid), cl, al, note="incumbent vs market, descriptive")
        mkt_counts[fam] = {c: dict(n_rungs=int(v.sum()), n_games=int(g.gid[v].nunique()), n_rungs_restored=int((v & (g.source != "projection-data_T-60").to_numpy()).sum()))
                           for c, v in al.items()}

    # ------------------------------------------------------------------ team points: level, player-sum coherence
    gdate = {g: et_date(t) for g, t in zip(gf.game_id, gf.tip_ts)}
    to = tout.set_index(["game_id", "team"])
    Xp = X[X.has_pf.to_numpy()]; ep = np.nan_to_num(Xp.pf_p_play.to_numpy(float))
    agg = pd.DataFrame(dict(game_id=Xp.game_id.to_numpy(), team=Xp.team.to_numpy(), e_pf=ep * np.nan_to_num(Xp.pf_mean_points.to_numpy(float)),
                            e_c=ep * np.nan_to_num(mu_c["points"][X.has_pf.to_numpy()]), e_min=ep * np.nan_to_num(Xp.pf_mean_minutes.to_numpy(float)))).groupby(["game_id", "team"]).sum()
    trows = []
    for r in gf.itertuples():
        for t in (r.home, r.away):
            x = r.teams.get(t)
            if x and (r.game_id, t) in to.index and (r.game_id, t) in agg.index:
                p = np.asarray(x["probs"], float); p = p / p.sum(); a = agg.loc[(r.game_id, t)]
                trows.append(dict(game_id=r.game_id, team=t, home=t == r.home, date_s=gdate[r.game_id], pf=float(p @ (np.arange(len(p)) + int(x["lo"]))),
                                  y=float(to.loc[(r.game_id, t)].pts), n_ot=int(to.loc[(r.game_id, t)].n_ot), sum_pf=float(a.e_pf), sum_min=float(a.e_min),
                                  sum240=float(a.e_c * 240.0 / a.e_min) if a.e_min > 0 else np.nan, version=r.version))
    T = pd.DataFrame(trows).sort_values(["date_s", "game_id", "team"]).reset_index(drop=True)
    both = T.groupby("game_id").team.transform("size") == 2; T = T[both].reset_index(drop=True)
    xd = X.drop_duplicates("game_id").set_index("game_id").date_s
    same_d = float(np.mean([gdate[g] == d_ for g, d_ in xd.items()]))
    chk["coh"].append(_chk("game_date_from_tip_equals_outcome_game_date", same_d == 1.0, f"{len(xd)} games: ET date derived from the tip time equals the archived outcome date in {same_d:.4f}"))
    ttrain = (T.date_s < F.TRAIN_END).to_numpy(); tmasks = F.cohort_masks(T.date_s); Kt = float(thist["k_team_games"])
    tgrid = {}
    for w in W_GRID:
        b0 = (1 - w) * T.pf.to_numpy() + w * T.sum240.to_numpy()
        for on in (False, True):
            dl = online_level(T.date_s.to_numpy(), np.zeros(len(T)), T.y.to_numpy(), b0, Kt, additive=True) if on else 0.0
            tgrid[(w, on)] = float(np.abs(T.y.to_numpy() - b0 - dl)[ttrain].mean())
    wT, onT = min(tgrid, key=lambda q: (tgrid[q], q[0], q[1]))
    b0 = (1 - wT) * T.pf.to_numpy() + wT * T.sum240.to_numpy()
    delta = online_level(T.date_s.to_numpy(), np.zeros(len(T)), T.y.to_numpy(), b0, Kt, additive=True) if onT else np.zeros(len(T))
    T["c"] = b0 + delta; T["delta"] = delta
    sel["team_points"] = dict(weight_on_normalised_player_sum=wT, online_level_on=bool(onT), online_level_k_team_games=Kt,
                              train_abs_error_grid={f"w{w}_level{int(o)}": v for (w, o), v in tgrid.items()}, n_train_team_games=int(ttrain.sum()),
                              level_correction_first_test_day=float(T.delta[tmasks[POOLED]].iloc[0]) if tmasks[POOLED].any() else None, level_correction_last_day=float(T.delta.iloc[-1]))
    R.add("team_total", ["NBA:team_total"], "abs_error_team_points", ARM, "pf_frozen", np.abs(T.y - T.c), np.abs(T.y - T.pf), T.game_id.to_numpy(), tmasks, headline=True)
    Gm = T.groupby("game_id", sort=False).agg(date_s=("date_s", "first"), y=("y", "sum"), pf=("pf", "sum"), c=("c", "sum")).reset_index()
    hm = T[T.home].set_index("game_id"); aw = T[~T.home].set_index("game_id")
    Gm["ym"] = Gm.game_id.map(hm.y - aw.y); Gm["pfm"] = Gm.game_id.map(hm.pf - aw.pf); Gm["cm"] = Gm.game_id.map(hm.c - aw.c)
    gmasks = F.cohort_masks(Gm.date_s)
    R.add("game_total", ["NBA:game_total"], "abs_error_total", ARM, "pf_frozen", np.abs(Gm.y - Gm.c), np.abs(Gm.y - Gm.pf), Gm.game_id.to_numpy(), gmasks, headline=True)
    R.add("game_spread", ["NBA:game_spread"], "abs_error_home_margin", ARM, "pf_frozen", np.abs(Gm.ym - Gm.cm), np.abs(Gm.ym - Gm.pfm), Gm.game_id.to_numpy(), gmasks)
    cmean = {(g, t): c for g, t, c in zip(T.game_id, T.team, T.c)}
    gf2 = gf.copy(); new = []
    for r in gf.itertuples():
        tt = {}
        for t, x in r.teams.items():
            if (r.game_id, t) in cmean:
                p = np.asarray(x["probs"], float); mu0 = float(p / p.sum() @ (np.arange(len(p)) + int(x["lo"])))
                lo, pr = shift_pmf(int(x["lo"]), p, cmean[(r.game_id, t)] - mu0); tt[t] = dict(x, lo=lo, probs=list(pr), mean=cmean[(r.game_id, t)])
            else:
                tt[t] = x
        new.append(tt)
    gf2["teams"] = new
    G0 = F.game_rungs(M, gf, tout); G1 = F.game_rungs(M, gf2, tout)
    aligned = bool(len(G0) == len(G1) and (G0.ticker.to_numpy() == G1.ticker.to_numpy()).all())
    G0["p_c"] = G1.p.to_numpy() if aligned else np.nan; G0["date_s"] = G0.game_id.map(gdate); G0["source"] = G0.ticker.map(M.drop_duplicates("ticker").set_index("ticker").source)
    sh = max(abs(float(np.asarray(a["probs"]) @ (np.arange(len(a["probs"])) + a["lo"]) - a["mean"])) for tt in new for a in tt.values() if "mean" in a)
    chk["coh"].append(_chk("shifted_team_pmf_mean_equals_target_and_rungs_aligned", sh < 0.02 and aligned,
                           f"max |shifted pmf mean - challenger team mean| = {sh:.4f} (archived means are rounded to 0.01); incumbent and challenger game-rung tables aligned ticker by ticker: {aligned} ({len(G0)} rungs)"))
    for fam in ("game_spread", "game_total", "team_total"):
        g = G0[(G0.family == fam) & (G0.quote_class == "TWO_SIDED") & G0.bid.notna() & G0.ask.notna()].reset_index(drop=True)
        g["mid"] = (g.bid.astype(float) + g.ask.astype(float)) / 2
        rm = F.cohort_masks(g.date_s); al = {**rm, ALLG: np.ones(len(g), bool)}; cl = g.game_id.to_numpy(); b = lambda p: C.brier_rows(p, g.y)
        R.add(fam, [f"NBA:{fam}"], "brier_two_sided", ARM, "pf_frozen", b(g.p_c), b(g.p), cl, rm)
        R.add(fam, [f"NBA:{fam}"], "brier_two_sided", ARM, "kalshi_t60_mid", b(g.p_c), b(g.mid), cl, rm)
        R.add(fam, [f"NBA:{fam}"], "brier_two_sided", "pf_frozen", "kalshi_t60_mid", b(g.p), b(g.mid), cl, al, note="incumbent vs market, descriptive")
        mkt_counts[fam] = {c: dict(n_rungs=int(v.sum()), n_games=int(g.game_id[v].nunique()), n_rungs_restored=int((v & (g.source != "projection-data_T-60").to_numpy()).sum()))
                           for c, v in al.items()}
    rows = R.finalize()
    return dict(repo=repo, pg=pg, tg=tg, hist=hist, thist=thist, hrows=hrows, hv=hv, fc=fc, fc_stats=fc_stats, out=out, tout=tout, gf=gf, M_pd=M_pd, m_stats=m_stats,
                M_da=M_da, r_stats=r_stats, M=M, X=X, fs=fs, base=base, masks=masks, train=train, sel=sel, mu_c=mu_c, rr=rr, T=T, Gm=Gm, G0=G0, rows=rows, R=R, chk=chk,
                mkt_counts=mkt_counts, j27=j27, opp=opp)


# =============================================================================================== diagnosis of the frozen forecasts
def _wk(d: str) -> str:
    return "1_2026-10-19..26" if d < "2026-10-27" else ("2_2026-10-27..31" if d < F.TRAIN_END else ("3_test1_2026-11-01..07" if d <= F.COH_SPLIT else "4_test2_2026-11-08..13"))


def diagnose(S: dict) -> dict:
    """Where the frozen forecasts' level error comes from. Forecast minus actual throughout (positive = over-forecast)."""
    X, T, base, repo = S["X"], S["T"], S["base"], S["repo"]
    ctx = load_game_context(repo); j = S["j27"]
    b = j.groupby(["game_id", "team"]).agg(fga=("fga", "sum"), fta=("fta", "sum"), oreb=("oreb", "sum"), tov=("tov", "sum"), mins=("minutes", "sum")).reset_index()
    b["n_ot_box"] = np.clip(np.round((b.mins / 5.0 - 48.0) / 5.0), 0, 6)
    b["poss_raw"] = 0.96 * (b.fga + 0.44 * b.fta - b.oreb + b.tov)                 # the production formula (nba/data.py)
    b["poss"] = b.groupby("game_id").poss_raw.transform("mean")
    D = T.merge(b, on=["game_id", "team"], how="inner")
    D["pace48"] = D.poss * 48.0 / (48.0 + 5.0 * D.n_ot_box); D["ortg"] = 100.0 * D.y / D.poss; D["otf"] = (48.0 + 5.0 * D.n_ot_box) / 48.0
    side = np.where(D.home, "home", "away")
    D["exp_pace"] = [ctx.get(g, {}).get(f"{s}_exp_pace", np.nan) for g, s in zip(D.game_id, side)]
    D["exp_ortg"] = [ctx.get(g, {}).get(f"{s}_exp_ortg", np.nan) for g, s in zip(D.game_id, side)]
    D = D[D.exp_pace.notna() & D.exp_ortg.notna()].copy(); D["wk"] = D.date_s.map(_wk)

    def dec(x):
        parts = dict(overtime_not_in_pace_x_efficiency=float(-(x.y * (1 - 1 / x.otf)).mean()), pace=float(((x.exp_pace - x.pace48) * x.ortg / 100).mean()),
                     efficiency=float(((x.exp_ortg - x.ortg) * x.exp_pace / 100).mean()), rest_adjustment_stage_added_to_pace_x_efficiency=float((x.pf - x.exp_pace * x.exp_ortg / 100).mean()))
        tot = float((x.pf - x.y).mean())
        return dict(n_team_games=int(len(x)), forecast_minus_actual=tot, parts=parts, parts_sum=float(sum(parts.values())), mean_forecast=float(x.pf.mean()), mean_actual=float(x.y.mean()),
                    actual_pace48=float(x.pace48.mean()), expected_pace48=float(x.exp_pace.mean()), actual_points_per_100=float(x.ortg.mean()), expected_points_per_100=float(x.exp_ortg.mean()),
                    player_sum_minus_actual=float((x.sum_pf - x.y).mean()), player_sum_expected_minutes=float(x.sum_min.mean()),
                    player_sum_normalised_to_240_minus_actual=float((x.sum_pf * 240.0 / x.sum_min - x.y).mean()))
    team = dict(all=dec(D), by_week={k: dec(v) for k, v in D.groupby("wk")})
    gt = D.groupby("game_id").apply(lambda x: (x.pf - x.y).sum(), include_groups=False)
    team["game_total_forecast_minus_actual"] = dict(n_games=int(len(gt)), mean=float(gt.mean()), se=float(gt.std() / np.sqrt(len(gt))))
    ident = float(np.abs(sum(team["all"]["parts"].values()) - team["all"]["forecast_minus_actual"]))
    env = {}
    tgr = S["tg"][S["tg"].season_type == "regular"]
    for s in HIST_SEASONS:
        x = tgr[tgr.season == s]; e = x[(x.game_date_et.str[5:] >= "10-01") & (x.game_date_et.str[5:] <= "11-13")]
        env[s] = dict(team_games=int(len(x)), points=float(x.pts.mean()), possessions=float(x.possessions.mean()), points_per_100=float(100 * x.pts.sum() / x.possessions.sum()),
                      through_nov13=dict(team_games=int(len(e)), points=float(e.pts.mean()), possessions=float(e.possessions.mean()),
                                         points_per_100=float(100 * e.pts.sum() / e.possessions.sum())) if len(e) else None)
    # players (played, conditional forecasts)
    P = X[base]; ym = P.y_min.to_numpy(float); fm = P.pf_mean_minutes.to_numpy(float); pl = {}
    for s in STATS:
        y = P[f"y_{s}"].to_numpy(float); f = P[f"pf_mean_{s}"].to_numpy(float); rate = f / np.maximum(fm, 1.0)
        pl[s] = dict(n=int(len(P)), forecast_over_actual=float(f.sum() / y.sum()), rate_only_forecast_over_actual=float((rate * ym).sum() / y.sum()),
                     minutes_only_forecast_over_actual=float(fm.sum() / ym.sum()), mae=float(np.abs(y - f).mean()), mae_given_actual_minutes=float(np.abs(y - rate * ym).mean()),
                     by_week={k: float(f[(P.date_s.map(_wk) == k).to_numpy()].sum() / y[(P.date_s.map(_wk) == k).to_numpy()].sum()) for k in sorted(P.date_s.map(_wk).unique())})
    fs = S["fs"]; y = P.y_points.to_numpy(float); f = P.pf_mean_points.to_numpy(float); rate = f / np.maximum(fm, 1.0); res = y - rate * ym
    mpg = fs["mpg"][base]; npg = fs["n_prior_games"][base]; z = np.abs(res) / np.sqrt(np.maximum(rate * ym, 0.5))
    ishome = np.array([S["gf"].set_index("game_id").home.get(g) == t for g, t in zip(P.game_id, P.team)])
    sl = {"all": np.ones(len(P), bool), "fewer_than_10_prior_games_in_archive": npg < 10, "forecast_minutes_4_plus_above_recent_average": (fm - mpg >= 4) & (npg >= 10),
          "forecast_minutes_4_plus_below_recent_average": (mpg - fm >= 4) & (npg >= 10), "home": ishome, "away": ~ishome,
          "listed_questionable_or_probable": P.designation.fillna("").str.upper().isin(["QUESTIONABLE", "PROBABLE", "DOUBTFUL"]).to_numpy(),
          "recent_average_28_plus_minutes": mpg >= 28, "recent_average_under_20_minutes": (mpg < 20) & (npg >= 10)}
    slices = {k: dict(n=int(v.sum()), forecast_over_actual_given_actual_minutes=float((rate * ym)[v].sum() / max(y[v].sum(), 1e-9)), mae_given_actual_minutes=float(np.abs(res)[v].mean()),
                      mean_abs_error_over_sqrt_expected=float(z[v].mean())) for k, v in sl.items() if v.sum() >= 30}
    return dict(sign_convention="forecast minus actual; positive = the model forecast too many points", team_points=team, decomposition_identity_abs_error=ident,
                scoring_environment_by_season=env, players_conditional_on_playing=pl, points_rate_error_slices_all_games=slices)


# =============================================================================================== model-version lineage
def version_lineage(S: dict) -> dict:
    """Map every frozen pf forecast run to the exact code revision in its own ``model_version`` suffix, to a digest of the
    forecast-affecting source tree at that revision, and to accuracy per constant-code segment."""
    repo, fc, X, base, T, rr = S["repo"], S["fc"], S["X"], S["base"], S["T"], S["rr"]
    pf = fc[fc.model == "pf"]
    v = pf.groupby("version").agg(n_rows=("game_id", "size"), n_games=("game_id", "nunique"), first=("gen_ts", "min"), last=("gen_ts", "max")).sort_values("first").reset_index()
    gt = lambda *a: F._git(repo, *a).decode().strip()
    rows = []; prev = None; seg = 0; prev_dig = None
    for r in v.itertuples():
        label, sha = r.version.split("+")[0], r.version.split("+")[1]
        try:
            full = gt("rev-parse", sha + "^{commit}"); found = True
        except Exception:
            full, found = None, False
        row = dict(model_version=r.version, label=label, short_sha=sha, commit=full, commit_found=found, n_frozen_rows=int(r.n_rows), n_games=int(r.n_games),
                   first_generated_utc=F._iso(r.first), last_generated_utc=F._iso(r.last))
        if found:
            row["commit_time_utc"] = pd.Timestamp(gt("log", "-1", "--format=%cI", full)).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
            row["subject"] = gt("log", "-1", "--format=%s", full)[:140]
            try:
                F._git(repo, "merge-base", "--is-ancestor", full, F.MAIN_COMMIT); row["on_main"] = True
            except Exception:
                row["on_main"] = False
            dig = hashlib.sha256(F._git(repo, "ls-tree", "-r", full, "--", *MODEL_PATHS)).hexdigest()[:16]
            row["model_source_digest"] = dig
            row["generated_after_commit"] = bool(r.first >= F._iso_s(row["commit_time_utc"]))
            if prev:
                row["commits_since_previous_run_revision"] = int(gt("rev-list", "--count", f"{prev}..{full}"))
                ch = [x for x in gt("diff", "--name-only", prev, full, "--", *MODEL_PATHS).splitlines() if x]
                row["model_files_changed_since_previous"] = [c.replace("research/projection_foundation/", "") for c in ch]
                row["commits_touching_model_source"] = [x[:120] for x in gt("log", "--no-merges", "--abbrev=11", "--format=%h %s", f"{prev}..{full}", "--", *MODEL_PATHS).splitlines()]
            else:
                row["commits_since_previous_run_revision"] = None; row["model_files_changed_since_previous"] = []; row["commits_touching_model_source"] = []
            row["forecast_code_changed"] = bool(prev_dig is not None and dig != prev_dig)
            if row["forecast_code_changed"]:
                seg += 1
            prev, prev_dig = full, dig
        row["segment"] = seg
        rows.append(row)
    seg_of = {r["model_version"]: r["segment"] for r in rows}
    P = X[base].copy(); P["seg"] = P.version.map(seg_of)
    Tt = T.copy(); Tt["seg"] = Tt.version.map(seg_of)
    g2 = rr[rr.two & (rr.stat == "points")].copy(); g2["seg"] = X.version.map(seg_of).to_numpy()[g2.row.to_numpy()]
    segs = []
    for s in sorted(set(seg_of.values())):
        p = P[P.seg == s]; t = Tt[Tt.seg == s]; q = g2[g2.seg == s]; vs = [r for r in rows if r["segment"] == s]
        e = dict(segment=s, model_versions=[r["model_version"] for r in vs], model_source_digest=vs[0].get("model_source_digest"), first_generated_utc=vs[0]["first_generated_utc"],
                 last_generated_utc=vs[-1]["last_generated_utc"], n_games=int(p.game_id.nunique()), n_played_rows=int(len(p)), n_team_games=int(len(t)))
        if len(p) >= 100:
            e.update(points_mae=float(np.abs(p.y_points - p.pf_mean_points).mean()), points_forecast_over_actual=float(p.pf_mean_points.sum() / p.y_points.sum()),
                     minutes_mae=float(np.abs(p.y_min - p.pf_mean_minutes).mean()), rebounds_mae=float(np.abs(p.y_rebounds - p.pf_mean_rebounds).mean()),
                     assists_mae=float(np.abs(p.y_assists - p.pf_mean_assists).mean()))
        if len(t) >= 20:
            e["team_points_forecast_minus_actual"] = float((t.pf - t.y).mean()); e["team_points_mae"] = float(np.abs(t.pf - t.y).mean())
        if q.gid.nunique() >= 20:
            bb = C.paired_cluster_bootstrap(C.brier_rows(q.p_pf, q.y) - C.brier_rows(q.mid, q.y), q.gid.to_numpy(), seed=SEED)
            e["points_brier_pf_minus_kalshi_t60_mid"] = dict(diff=bb["mean"], ci95=[bb["lo"], bb["hi"]], n_rungs=bb["n_rows"], n_games=bb["n_clusters"])
        e["evaluated"] = bool(len(p) >= 100)
        segs.append(e)
    return dict(schema="sift-nba-pf-version-lineage/1", status="RESEARCH_ONLY", repo=F.NBA_REPO, projection_data_commit=F.PD_COMMIT, main_commit=F.MAIN_COMMIT,
                rule="A run's code revision is the git short sha the production writer appended to model_version (pf-<pf_core version>+<git rev-parse --short HEAD>). "
                     "forecast_code_changed compares a digest of the forecast-affecting source tree (model_paths) with the previous run revision; a run whose digest is "
                     "unchanged ran byte-identical model source. The LightGBM rungs are refitted from the then-current box-score history on every run, so identical "
                     "source does not mean identical fitted model.",
                model_paths=MODEL_PATHS, n_model_versions=len(rows), n_labels=int(v.version.str.split("+").str[0].nunique()),
                n_revisions_found_in_repo=int(sum(r["commit_found"] for r in rows)), n_forecast_code_changes=int(sum(bool(r.get("forecast_code_changed")) for r in rows)),
                n_segments=len(segs), runs=rows, segments=segs)


# =============================================================================================== evaluation document
def _fmt(r):
    return f"{r['diff']:+.4f} [{r['ci95'][0]:+.4f}, {r['ci95'][1]:+.4f}] {r['verdict']}"


def build_document(S: dict) -> tuple:
    X, rr, fc, gf, out, tout, M, M_pd, M_da, T, base, masks, sel = (S[k] for k in ("X", "rr", "fc", "gf", "out", "tout", "M", "M_pd", "M_da", "T", "base", "masks", "sel"))
    rows = S["hrows"] + S["rows"]; chk = S["chk"]; hv = S["hv"]
    diag = diagnose(S); lin = version_lineage(S)
    find = lambda fam, metric, arm, ref, coh: next((r for r in rows if (r["market_family"], r["metric"], r["challenger_arm"], r["reference"], r["cohort"]) == (fam, metric, arm, ref, coh)), None)
    fams_p = [F.FAMILY[s] for s in STATS + ["pra"]]; fams_g = ["game_spread", "game_total", "team_total"]
    bm = lambda f: "brier_two_sided" if f in fams_g else "brier_ladder_given_played_two_sided"
    chk["lin"].append(_chk("every_frozen_run_revision_resolves_and_precedes_its_forecasts", lin["n_revisions_found_in_repo"] == lin["n_model_versions"]
                           and all(r.get("generated_after_commit") for r in lin["runs"]),
                           f"{lin['n_model_versions']} distinct model_version strings under {lin['n_labels']} labels; {lin['n_revisions_found_in_repo']} resolve to a commit of "
                           f"{F.NBA_REPO}; runs whose first forecast predates their commit time: {sum(not r.get('generated_after_commit') for r in lin['runs'])}; "
                           f"runs on main: {sum(bool(r.get('on_main')) for r in lin['runs'])}; forecast-source changes: {lin['n_forecast_code_changes']}"))
    late = sorted(g for g, t in zip(gf.game_id, gf.tip_ts) if et_date(t) > "2026-11-06")
    late_board = sorted(set(M_da.game_id) & set(late)); late_pd = sorted(set(M_pd.game_id) & set(late))
    two = rr[rr.two]
    restore = dict(source=f"{F.NBA_REPO}@{DA_BRANCH} {DA_COMMIT[:12]}: kalshi/markets (full board checkpoints) + kalshi/markets_delta (kalshi.board.delta/1, hash-chained)",
                   rule="latest capture at or before tip - 60 min, at most 30 min old; newest checkpoint at or before the cutoff plus its own contiguous delta chain; nothing interpolated",
                   stats=S["r_stats"], games_after_2026_11_06=len(late), of_those_with_projection_data_t60_rows=len(late_pd), of_those_with_restored_board=len(late_board),
                   of_those_without_any_board=len(late) - len(set(late_board) | set(late_pd)),
                   restored_tickers_used=int((M.source != "projection-data_T-60").sum()), projection_data_tickers_used=int((M.source == "projection-data_T-60").sum()),
                   test_games_with_two_sided_prop_quotes={c: int(two[F.cohort_masks(two.date_s)[c]].gid.nunique()) for c in (COH1, COH2, POOLED)},
                   policy="projection-data T-60 rows are used wherever a game has them (same reference as alpha-nba-avail-0.2); restored boards fill only games with none")
    pfvm = {f: find(f, bm(f), "pf_frozen", "kalshi_t60_mid", ALLG) for f in fams_p + fams_g}
    c3vm = {f: find(f, bm(f), ARM, "kalshi_t60_mid", POOLED) for f in fams_p + fams_g}
    c3vp = {f: find(f, bm(f), ARM, "pf_frozen", POOLED) for f in fams_p + fams_g}
    rank = sorted(((f, r["diff"], r["diff"] / r["reference_value"]) for f, r in pfvm.items() if r), key=lambda x: -x[2])
    head = [r for r in S["rows"] if r["headline"]]
    hv_c = {r["market_family"] + ":" + r["metric"]: r["verdict"] for r in head}
    n_val = sum(v == "VALIDATED_IMPROVEMENT" for v in hv_c.values()); worse_mkt = [f for f, r in c3vm.items() if r and r["verdict"] == "NOT_IMPROVED"]
    any_bad = any(v == "NOT_IMPROVED" for v in hv_c.values())
    overall = ("VALIDATED_IMPROVEMENT" if n_val == len(hv_c) and not worse_mkt else "IMPROVED_NOT_VALIDATED" if n_val else "NOT_IMPROVED" if any_bad else "INCONCLUSIVE")
    verdict = dict(
        overall=overall, retain_incumbent=True,
        rule="contract.verdict_from on every row: validated = 95% game-clustered bootstrap CI below zero, Holm p < 0.05, same sign in both chronological cohorts. Overall is "
             "VALIDATED_IMPROVEMENT only if every headline row is validated AND the challenger is not significantly worse than the Kalshi T-60 mid on any family.",
        headline_c3_vs_pf_frozen=hv_c,
        c3_vs_pf_frozen_market_rungs={f: _fmt(r) for f, r in c3vp.items() if r}, c3_vs_kalshi_t60_mid={f: _fmt(r) for f, r in c3vm.items() if r},
        incumbent_pf_vs_kalshi_t60_mid_all_games={f: [r["verdict"], round(r["diff"], 4), [round(x, 4) for x in r["ci95"]], r["n_rows"], r["n_clusters"]] for f, r in pfvm.items() if r},
        weakest_families_incumbent_vs_market=[dict(market_family=f, brier_gap=round(dv, 5), gap_relative_to_market_brier=round(rel, 4)) for f, dv, rel in rank],
        history_components_validated_2025_26=sorted(f"{k[0]}:{k[1]}" for k, v in hv.items() if v == "VALIDATED_IMPROVEMENT"),
        history_components_not_validated=sorted(f"{k[0]}:{k[1]}={v}" for k, v in hv.items() if v != "VALIDATED_IMPROVEMENT"),
        reason=f"{n_val} of {len(hv_c)} headline rows validated against the frozen production forecasts (player distributions); team points and totals are inconclusive; "
               f"the challenger is still not better than the Kalshi T-60 mid on any family and significantly worse on {worse_mkt or 'none'}",
        evidence_sufficiency=dict(
            challenger_vs_incumbent=f"{int(X[masks[POOLED]].game_id.nunique())} TEST games in two cohorts of about one week; one month of one season",
            challenger_vs_market=f"{restore['test_games_with_two_sided_prop_quotes'][POOLED]} TEST games with two-sided T-60 prop quotes "
                                 f"({restore['test_games_with_two_sided_prop_quotes'][COH1]} in cohort 1, {restore['test_games_with_two_sided_prop_quotes'][COH2]} in cohort 2 after restoring data-archive boards)",
            history="one tuning season (2024-25) and one test season (2025-26); components are scored given actual minutes against a reproduction of the rate rung, not against the production stack"))
    cat = {"usage_x_efficiency": ["NBA:nba.usage", "NBA:nba.stat_rate_posterior"], "online_level": ["NBA:nba.own_game_environment"], "home_factor": ["NBA:nba.venue"],
           "teammate_out_usage_retrospective": ["NBA:nba.teammate_absence_shift"], "opponent_factor": ["NBA:nba.matchup_def"],
           "structured_prior_season_prior": ["NBA:nba.stat_rate_posterior"], "overtime_uplift": ["NBA:nba.ot_model"], "overtime_uplift_plus_online_level": ["NBA:nba.own_model_team_totals"]}
    abl = []
    for r in S["hrows"]:
        if r["cohort"] == HP:
            name = r["challenger_arm"][2:]
            abl.append(dict(feature=name, step=f"{S['hist']['reference'] if r['market_family'] != 'team_total' else S['thist']['reference']} -> + {name} (2025-26 walk-forward)",
                            catalog_inputs=cat.get(name, []), market_family=r["market_family"], metric=r["metric"], cohort=r["cohort"], delta=r["diff"], ci95=r["ci95"],
                            n_rows=r["n_rows"], n_clusters=r["n_clusters"], p_raw=r["p_raw"], p_holm=r["p_holm"], replicated=r["replicated"], verdict=r["verdict"],
                            decision="eligible for the 2026-27 challenger" if r["verdict"] == "VALIDATED_IMPROVEMENT" else "rejected: not validated on prior seasons"))
    hp = S["hist"]["params"]
    features = [
        dict(feature_id="independent_per_minute_rate_usage_x_efficiency_x_opponent", catalog_inputs=["NBA:nba.stat_rate_posterior", "NBA:nba.usage", "NBA:nba.matchup_def"],
             description="Per-minute rate from the owner's ESPN box archive: exponentially decayed sums (half-life 20 games) shrunk by 30 minutes toward the previous "
                         "season's league rate for the player's minutes bucket; for points, usage (true-shot attempts per minute, half-life 8) x efficiency (points per "
                         "true-shot attempt, half-life 80, shrunk by 100 attempts); times the opponent's allowed/expected ratio raised to a 2024-25 exponent. Blended into "
                         "the frozen pf mean with a weight chosen on the 2026-27 TRAIN window; the pf pmf is exponentially tilted to the new mean.",
             pit_rule="player state = last played game dated strictly before the game's ET date; opponent ratio from the opponent's strictly earlier games; priors from the "
                      "complete previous season; exponents fitted on 2024-25; blend weight fitted on 2026-27 games before 2026-11-01",
             parameters={s: dict(opponent_beta=hp[s]["opponent_beta"], weight_on_independent_rate=sel[s]["weight_on_independent_rate"], independent_rate=sel[s]["independent_rate"]) for s in STATS},
             checks=chk["hist"]),
        dict(feature_id="online_scoring_level_correction", catalog_inputs=["NBA:nba.own_game_environment"],
             description="Multiplicative league-level ratio per stat, (sum actual + k) / (sum forecast + k) over played players of the same season's earlier slates; k from "
                         "2024-25. Switched on per stat only if it lowers TRAIN-window CRPS. For team points an additive version was offered and switched OFF by the TRAIN window.",
             pit_rule="uses outcomes of games on strictly earlier ET dates of the same season only; first slate ratio is exactly 1",
             parameters={s: dict(k=sel[s]["online_level_k"], on=sel[s]["online_level_on"], ratio_last_day=sel[s]["online_level_ratio_last_day"]) for s in STATS},
             checks=chk["level"]),
        dict(feature_id="team_points_blend_with_normalised_player_sum", catalog_inputs=["NBA:nba.own_model_team_totals"],
             description="Team points = (1 - w) x frozen pf team mean + w x (sum of P(play) x challenger player points, rescaled to 240 expected team minutes); the frozen team "
                         "pmf is shifted to the new mean (shape unchanged). w chosen on the TRAIN window.",
             pit_rule="inputs are the frozen pf forecasts (generated and archived at or before tip - 60 min) and the challenger player means; w fitted before 2026-11-01",
             parameters=sel["team_points"], checks=chk["coh"]),
        dict(feature_id="restored_kalshi_t60_boards_from_capture_archive", catalog_inputs=["NBA:m.quote_history"],
             description="T-60 boards rebuilt from the capture-worker archive for games whose projection-data T-60 snapshot is missing (every game after 2026-11-06).",
             pit_rule="latest capture at or before tip - 60 min and at most 30 min old; checkpoint + contiguous hash-linked deltas; no interpolation, no later capture",
             checks=chk["mkt"]),
        dict(feature_id="pf_model_version_lineage", catalog_inputs=[],
             description="Each frozen run mapped to the code revision in its model_version suffix and to a digest of the forecast-affecting source files.",
             pit_rule="uses only the archived model_version strings and the repository history; no outcome data", checks=chk["lin"]),
    ]
    ds = lambda *a, **k: F._ds(*a, **k)
    pfr = fc[fc.model == "pf"]; d = S["hist"]["state"]["d"]
    data = [
        ds("pf_frozen_player_forecasts", "forecasts/nba/", len(pfr), F._iso(pfr.gen_ts.min()), F._iso(pfr.gen_ts.max()), "PROSPECTIVE_CAPTURE", F.PD_COMMIT, F.PD_BRANCH),
        ds("pf_frozen_team_points_forecasts", "game_forecasts/nba/", len(gf), F._iso(gf.gen_ts.min()), F._iso(gf.gen_ts.max()), "PROSPECTIVE_CAPTURE", F.PD_COMMIT, F.PD_BRANCH),
        ds("final_player_outcomes", "outcomes/nba/", len(out), str(out.game_date_et.min()), str(out.game_date_et.max()), "PROSPECTIVE_CAPTURE", F.PD_COMMIT, F.PD_BRANCH),
        ds("final_team_outcomes", "team_outcomes/nba/", len(tout), str(X.date_s.min()), str(X.date_s.max()), "PROSPECTIVE_CAPTURE", F.PD_COMMIT, F.PD_BRANCH),
        ds("kalshi_t60_snapshots_projection_data", "market_snapshots/nba/", len(M_pd), F._iso(M_pd.obs_ts.min()), F._iso(M_pd.obs_ts.max()), "PROSPECTIVE_CAPTURE", F.PD_COMMIT, F.PD_BRANCH),
        ds("kalshi_boards_capture_archive_restored_t60", "kalshi/markets/ + kalshi/markets_delta/", len(M_da), F._iso(M_da.obs_ts.min()), F._iso(M_da.obs_ts.max()),
           "PROSPECTIVE_CAPTURE", DA_COMMIT, DA_BRANCH, F.digest(sorted(M_da.ticker.tolist()))),
        ds("espn_player_and_team_games_2023-24_to_2025-26", "data/history/espn/", int((S["pg"].season != "2026-27").sum()), str(S["pg"].game_date_et.min()),
           str(S["pg"][S["pg"].season != "2026-27"].game_date_et.max()), "HISTORICAL_BACKFILL", F.MAIN_COMMIT, "main"),
        ds("espn_player_and_team_games_2026-27_capture_archive", "history/espn/", int((S["pg"].season == "2026-27").sum()), str(S["j27"].game_date_et.min()),
           str(S["j27"].game_date_et.max()), "PROSPECTIVE_CAPTURE", DA_COMMIT, DA_BRANCH),
    ]
    cs = {c: dict(games=int(X[m].game_id.nunique()), played_rows=int((m & base).sum())) for c, m in masks.items()}
    cs["train"] = dict(games=int(X[S["train"]].game_id.nunique()), played_rows=int((S["train"] & base).sum()))
    design = dict(
        incumbent_reference="ACTUAL frozen production forecasts (pf-nba) as archived on projection-data; history rows use a walk-forward reproduction of the rate rung "
                            "(EWM per-minute rate) and of the team pace x efficiency ridge",
        freeze=dict(rule="T-60", forecast="latest per (game, player, stat) with max(generated, archived) <= tip - 60 min", market=restore["rule"],
                    box_history="games on strictly earlier ET dates"),
        windows=dict(history_tune=TRAIN_H, history_test=f"{TEST_H} split at {H_SPLIT}", train_2026_27=f"< {F.TRAIN_END}", test_cohort_1=f"[{F.TRAIN_END}, {F.COH_SPLIT}]",
                     test_cohort_2=f"> {F.COH_SPLIT}"),
        arms={ARM: "frozen pf mean x (blend with the independent rate) x (online level where switched on); pf pmf tilted to the new mean; team points blended with the "
                   "normalised player sum", "pf_frozen": "production forecasts as archived", "kalshi_t60_mid": "(yes_bid + yes_ask) / 2 on two-sided T-60 quotes",
              "H_*": "one component added to the reproduction baseline on prior seasons, scored given actual minutes"},
        statistics=f"paired game-clustered bootstrap (2000 draws, seed {SEED}); Holm across the {len(head)} headline rows ({ARM} vs pf_frozen, TEST pooled); other rows Holm "
                   "within (arm, reference, cohort); history rows replicate across the two halves of 2025-26",
        metric_note="History components are judged on Poisson deviance: absolute error rewards a forecast below the mean of a skewed count, so it cannot judge a level "
                    "correction. 2026-27 player rows are judged on CRPS of the full pmf.",
        economics="fees, spreads and execution are out of scope; nothing here is a profitability claim",
        cohort_sizes=cs, headline_rows=len(head), diagnosis=diag, history=dict(players=S["hist"]["summary"], parameters_fitted_2024_25=hp, team=S["thist"]),
        selection_on_train_window=sel, market_restoration=restore, market_counts=S["mkt_counts"],
        model_version_lineage=dict(artifact="research/data_foundation_ops/NBA/pf_version_lineage.json", n_model_versions=lin["n_model_versions"], n_labels=lin["n_labels"],
                                   n_forecast_code_changes=lin["n_forecast_code_changes"], n_segments=lin["n_segments"],
                                   behaviour_changing_revisions=[dict(model_version=r["model_version"], files=r["model_files_changed_since_previous"],
                                                                      commits=r["commits_touching_model_source"]) for r in lin["runs"] if r.get("forecast_code_changed")],
                                   segments=[{k: v for k, v in s.items() if k != "model_versions"} for s in lin["segments"] if s["evaluated"]]))
    tp = diag["team_points"]["all"]
    limitations = [
        "One month of 2026-27 (176 games with outcomes); TEST is 88 games in two cohorts of about a week. A validated row here means the contract rule passed on this window, not that the gain will persist.",
        "History components are tested against a reproduction of the rate rung given ACTUAL minutes, not against the production LightGBM stack, which has no archived forecasts before 2026-10-19. "
        "Only one tuning season and one test season are used.",
        f"The blend weight on the independent rate reached the upper edge of its pre-set grid (0.5) for {[s for s in STATS if sel[s]['weight_on_independent_rate'] == max(W_GRID)]}; the grid was not widened after seeing this.",
        "Teammate-out usage was tested with retrospective absences (who actually sat), an upper bound on a T-60 report; it still failed to replicate and is not in the challenger.",
        f"Restored boards exist for {restore['of_those_with_restored_board']} of {restore['games_after_2026_11_06']} games after 2026-11-06; the rest had no capture within 30 minutes before T-60. "
        f"{S['r_stats']['n_player_tickers_unmapped']} restored player tickers carry a player code never seen on projection-data and are not scored.",
        "Team-points and total rows are inconclusive: about 10 points of irreducible error per team-game against corrections of 1 to 3 points.",
        f"Sign correction to the alpha-nba-avail-0.2 write-up: its bias fields are actual minus forecast, so -2.40 / -4.80 mean the frozen model OVER-forecasts team points by {tp['forecast_minus_actual']:.2f} "
        f"and game totals by {diag['team_points']['game_total_forecast_minus_actual']['mean']:.2f}; the 0.2 limitation text and ops-doc sentence say 'under-forecast'. The committed 0.2 numbers are unchanged.",
        "Spread and total probabilities use the same normal approximation with the archived rho as alpha-nba-avail-0.2; a common shift of both teams leaves spreads unchanged, so spread rows move only through the player-sum blend.",
        "2026-27 box history is read from the capture-worker archive as of its pinned commit; a strictly-earlier-date rule is assumed to be available at T-60 (the production model makes the same assumption).",
        "No new external data was collected. No fees, no execution, no profitability claim.",
    ]
    hrow = lambda fam, name: next((r for r in S["hrows"] if r["market_family"] == fam and r["challenger_arm"] == f"H_{name}" and r["cohort"] == HP), None)
    hd = lambda s: find(F.FAMILY[s], "crps_given_played", ARM, "pf_frozen", POOLED)
    claims = [
        dict(input="NBA:nba.stat_rate_posterior", stage="EVALUATED", outcome="OK",
             evidence="C3 vs frozen pf, TEST crps_given_played: " + "; ".join(f"{s} {_fmt(hd(s))}" for s in STATS)),
        dict(input="NBA:nba.usage", stage="EVALUATED", outcome="OK", evidence="usage x efficiency points rate vs EWM rate, 2025-26 Poisson deviance given minutes: " + _fmt(hrow("player_points", "usage_x_efficiency"))),
        dict(input="NBA:nba.matchup_def", stage="EVALUATED", outcome="OK",
             evidence="opponent allowed/expected factor, 2025-26: " + "; ".join(f"{s} {_fmt(hrow(F.FAMILY[s], 'opponent_factor'))}" for s in STATS)),
        dict(input="NBA:nba.teammate_absence_shift", stage="EVALUATED", outcome="REJECTED",
             evidence="retrospective vacated-usage factor, 2025-26: " + "; ".join(f"{s} {_fmt(hrow(F.FAMILY[s], 'teammate_out_usage_retrospective'))}" for s in STATS)),
        dict(input="NBA:nba.own_model_team_totals", stage="EVALUATED", outcome="PARTIAL",
             evidence="team points blended with the normalised player sum vs frozen pf, TEST abs error: " + _fmt(find("team_total", "abs_error_team_points", ARM, "pf_frozen", POOLED))
                      + "; game total " + _fmt(find("game_total", "abs_error_total", ARM, "pf_frozen", POOLED))),
        dict(input="NBA:nba.ot_model", stage="EVALUATED", outcome="PARTIAL", evidence="overtime uplift on the reproduced pace x efficiency team model, 2025-26: " + _fmt(hrow("team_total", "overtime_uplift"))),
        dict(input="NBA:m.quote_history", stage="VERIFIED", outcome="PARTIAL",
             evidence=f"T-60 boards restored from data-archive for {restore['of_those_with_restored_board']} of {restore['games_after_2026_11_06']} games after 2026-11-06; prices equal the owner's "
                      "own T-60 snapshots to the cent on every overlapping two-sided ticker captured at the same instant"),
    ]
    doc = dict(schema=C.EVAL_SCHEMA, status="RESEARCH_ONLY", sport="NBA", challenger_id=CHALLENGER_ID, incumbent_id=INCUMBENT_ID, data=data, features=features, design=design,
               results=rows, ablations=abl, verdict=verdict, limitations=limitations, input_stage_claims=claims,
               source_commits={f"nba-edge-finder@{F.PD_BRANCH}": F.PD_COMMIT, "nba-edge-finder@main": F.MAIN_COMMIT, f"nba-edge-finder@{DA_BRANCH}": DA_COMMIT})
    by_date = X.groupby("date_s").agg(games=("game_id", "nunique"), player_games=("entity_id", "size"), played=("y_play", "sum")).reset_index()
    mk_d = two.groupby("date_s").agg(prop_rungs_two_sided=("ticker", "size"), market_games=("gid", "nunique"),
                                     restored_rungs=("source", lambda s: int((s != "projection-data_T-60").sum()))).reset_index()
    summ = dict(challenger_id=CHALLENGER_ID, by_date=by_date.merge(mk_d, on="date_s", how="left").fillna(0).to_dict("records"),
                frame_digest=F.digest(sorted(zip(X.game_id, X.entity_id))), rung_digest=F.digest(sorted(rr.ticker.tolist())), cohort_sizes=cs)
    return doc, summ, lin


def evaluate(repo: Path | None = None, out_dir: Path | None = None, lineage_path: Path | None = None, verbose: bool = True) -> dict:
    S = run(repo, verbose)
    doc, summ, lin = build_document(S)
    errs = C.validate_evaluation(doc)
    if errs:
        raise RuntimeError(f"evaluation violates the contract: {errs}")
    od = Path(out_dir) if out_dir else OUT_DIR
    C.write_json(od / "evaluation.json", doc)
    C.write_json(od / "predictions_summary.json", summ)
    C.write_json(Path(lineage_path) if lineage_path else (LINEAGE_PATH if out_dir is None else od / "pf_version_lineage.json"), lin)
    return doc


def main(argv=None) -> int:
    doc = evaluate()
    print(f"{CHALLENGER_ID}: overall {doc['verdict']['overall']}; {len(doc['results'])} result rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
