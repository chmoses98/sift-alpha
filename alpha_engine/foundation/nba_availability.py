"""Operation Data Foundation, NBA vertical slice: challenger ``alpha-nba-avail-0.1``.

RESEARCH_ONLY. An independent player-projection challenger centred on point-in-time (PIT) availability and
team-level minutes redistribution, evaluated on real 2025-26 box scores, the official injury-report archive and settled
Kalshi player-prop ladders read from the owner's ``nba-edge-finder`` clone under ``$SIFT_REPOS_DIR``.

Three nested arms on the SAME player-games (population: every player who appeared in >=1 of the team's last 10 games
and whose latest box-score row is with that team; players who then did not play are kept):

* A0  no-report proxy: P(play) = shrunk, recency-weighted share of the team's last 10 games played;
      minutes-if-playing = EWM of the player's recent minutes.
* A1  A0 + PIT injury gate: the player's own latest official status at tip-60min -> P(play | status, A0 share)
      and a status-specific minutes multiplier, both fitted on TRAIN only.
* A2  A1 + minutes redistribution: conditional minutes are re-allocated (weights minutes**gamma, cap 48) so that the
      expected team minutes equal the 240-minute budget (plus TRAIN overtime expectation, minus the TRAIN mean minutes
      of out-of-population players); optional points usage bump from vacated usage when TRAIN supports it.

Stat distributions (pts, reb, ast, fg3m): hurdle at 0 with mass 1-P(play), and given playing a minutes-scenario
mixture of negative binomials with mean = shrunk per-minute rate x scenario minutes.

Only aggregates, digests and row counts are written (never raw rows). ``python -m alpha_engine.foundation.nba_availability``
regenerates ``research/data_foundation_ops/NBA/alpha-nba-avail-0.1/`` deterministically.
"""
from __future__ import annotations

import gzip
import json
import re
import unicodedata
from math import lgamma
from pathlib import Path

import numpy as np
import pandas as pd

from . import contract as C

CHALLENGER_ID = "alpha-nba-avail-0.1"
INCUMBENT_ID = "nba-sim-0.1.0 (NBA_BASELINE_2026_PRESEASON_V1) walk-forward reproduction"
NBA_REPO = "chmoses98/nba-edge-finder"
NBA_COMMIT = "c9db017ceb10f30dbe298e3dbbbc3eee83d4dbe7"
OUT_DIR = C.OPS / "NBA" / CHALLENGER_ID

SEASON = "2025-26"
HIST_SEASONS = ["2023-24", "2024-25", "2025-26"]
TRAIN_END = "2026-01-15"          # TRAIN = 2025-26 games strictly before this date
TEST1_END = "2026-03-15"          # TEST cohort 1 = [TRAIN_END, TEST1_END]; cohort 2 = after
FREEZE_MIN = 60                   # T-60 freeze
MAX_REPORT_AGE_H = 30.0
WINDOW = 10
STATS = ["pts", "reb", "ast", "fg3m"]
KMAX = {"pts": 70, "reb": 35, "ast": 30, "fg3m": 15}
SERIES = {"KXNBAPTS": "pts", "KXNBAREB": "reb", "KXNBAAST": "ast", "KXNBA3PT": "fg3m"}
FAMILY = {"pts": "player_points", "reb": "player_rebounds", "ast": "player_assists", "fg3m": "player_threes"}
ARCH = {s: f"NBA:{FAMILY[s]}" for s in STATS}
ALL_PROP_ARCH = [ARCH[s] for s in STATS]
STATUS_ORDER = ["out", "doubtful", "questionable", "probable", "available", "not_listed", "team_not_submitted", "no_report"]
SEVERITY = {s: i for i, s in enumerate(["out", "doubtful", "questionable", "probable", "available"])}
RATE_HL = 40.0                    # games; pre-specified, not tuned
USAGE_HL = 10.0
N_SCEN = 9
MIN_BUCKETS = [0.0, 10.0, 18.0, 26.0, 34.0, 99.0]
CAP = 48.0

TEAM_TRICODES = {
    1610612737: "ATL", 1610612738: "BOS", 1610612739: "CLE", 1610612740: "NOP", 1610612741: "CHI", 1610612742: "DAL",
    1610612743: "DEN", 1610612744: "GSW", 1610612745: "HOU", 1610612746: "LAC", 1610612747: "LAL", 1610612748: "MIA",
    1610612749: "MIL", 1610612750: "MIN", 1610612751: "BKN", 1610612752: "NYK", 1610612753: "ORL", 1610612754: "IND",
    1610612755: "PHI", 1610612756: "PHX", 1610612757: "POR", 1610612758: "SAC", 1610612759: "SAS", 1610612760: "OKC",
    1610612761: "TOR", 1610612762: "UTA", 1610612763: "MEM", 1610612764: "WAS", 1610612765: "DET", 1610612766: "CHA",
}
TRICODE_ALIASES = {"BRK": "BKN", "NJN": "BKN", "CHO": "CHA", "PHO": "PHX", "GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP",
                   "NOH": "NOP", "UTAH": "UTA", "WSH": "WAS"}
TRICODE_TO_TEAM = {v: k for k, v in TEAM_TRICODES.items()}
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
_EVENT_RE = re.compile(r"^(\d{2})([A-Z]{3})(\d{2})([A-Z]{4,8})$")


# =============================================================================================== pure helpers (tested)
def canon_tricode(t):
    t = TRICODE_ALIASES.get(t, t)
    return t if t in TRICODE_TO_TEAM else None


def parse_prop_ticker(ticker: str):
    """``KXNBAPTS-25DEC01ATLDET-ATLDDANIELSSF-10`` -> dict(series, stat, date, away, home, team, player_code, strike).
    ``strike`` is the integer K of a "K+" contract. Returns None for anything that does not parse (never raises)."""
    parts = str(ticker).split("-")
    if len(parts) != 4 or parts[0] not in SERIES:
        return None
    m = _EVENT_RE.match(parts[1])
    if not m or m.group(2) not in MONTHS or not parts[3].isdigit():
        return None
    teams = m.group(4)
    split = None
    for cut in range(2, len(teams) - 1):
        a, h = canon_tricode(teams[:cut]), canon_tricode(teams[cut:])
        if a and h:
            split = (a, h)
            break
    if split is None:
        return None
    team, code = None, parts[2]
    for n in (4, 3, 2):
        t = canon_tricode(parts[2][:n])
        if t in split:
            team, code = t, parts[2][n:]
            break
    return dict(series=parts[0], stat=SERIES[parts[0]], date=f"20{m.group(1)}-{MONTHS[m.group(2)]:02d}-{m.group(3)}",
                away=split[0], home=split[1], team=team, player_code=code, strike=int(parts[3]))


def norm_name(s) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", "", s.replace("-", " "))
    toks = [t for t in s.split() if t not in ("jr", "sr", "ii", "iii", "iv", "v")]
    return " ".join(toks)


def _epoch_s(series) -> np.ndarray:
    t = pd.to_datetime(pd.Series(series), utc=True)
    return ((t - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta("1s")).to_numpy().astype("int64")


def select_pit_status(report_rows: pd.DataFrame, games: pd.DataFrame, freeze_min: int = FREEZE_MIN,
                      max_age_h: float = MAX_REPORT_AGE_H):
    """Point-in-time injury status per (game, player).

    ``report_rows``: game_id, team_id, nba_id (NaN = unmatched / team-level), status, report_time_utc and optionally
    published_utc (when the file became public; the later of the two is the availability time).
    ``games``: game_id, tip_utc. For each game the LATEST report carrying >=1 row for that game with
    availability time <= tip - freeze_min (and not older than ``max_age_h``) is selected; later reports are ignored.
    Returns (sel, players, teams): sel[game_id, report_ts, avail_ts, cutoff_ts, lead_min] (report_ts = -1 when no report),
    players[game_id, nba_id, status] (worst status when duplicated) and teams[game_id, team_id] for
    ``not_yet_submitted`` team rows in the selected report."""
    g = games[["game_id", "tip_utc"]].drop_duplicates("game_id").copy()
    g["cutoff_ts"] = _epoch_s(g["tip_utc"]) - freeze_min * 60
    cols = ["game_id", "team_id", "nba_id", "status", "report_time_utc"] + (["published_utc"] if "published_utc" in report_rows else [])
    r = report_rows[cols].copy()
    r["report_ts"] = _epoch_s(r["report_time_utc"])
    r["avail_ts"] = np.maximum(r.report_ts, _epoch_s(r["published_utc"].fillna(r["report_time_utc"]))) if "published_utc" in r else r.report_ts
    r = r.merge(g[["game_id", "cutoff_ts"]], on="game_id", how="inner")
    r = r[(r.avail_ts <= r.cutoff_ts) & (r.cutoff_ts - r.report_ts <= max_age_h * 3600)]
    last = r.groupby("game_id").agg(sel_ts=("report_ts", "max"), sel_avail=("avail_ts", "max")).reset_index()
    r = r.merge(last, on="game_id")
    r = r[r.report_ts == r.sel_ts]
    sel = g.merge(last, on="game_id", how="left")
    sel["report_ts"] = sel["sel_ts"].fillna(-1).astype("int64")
    sel["lead_min"] = np.where(sel.report_ts >= 0, (_epoch_s(sel["tip_utc"]) - sel.report_ts) / 60.0, np.nan)
    sel["avail_ts"] = sel["sel_avail"].fillna(-1).astype("int64")
    sel = sel[["game_id", "report_ts", "avail_ts", "cutoff_ts", "lead_min"]].reset_index(drop=True)
    teams = r[r.status == "not_yet_submitted"][["game_id", "team_id"]].drop_duplicates().reset_index(drop=True)
    p = r[r.nba_id.notna() & r.status.isin(list(SEVERITY))].copy()
    p["sev"] = p.status.map(SEVERITY)
    p["nba_id"] = p.nba_id.astype("int64")
    p = p.sort_values(["game_id", "nba_id", "sev"]).drop_duplicates(["game_id", "nba_id"])
    return sel, p[["game_id", "nba_id", "status"]].reset_index(drop=True), teams


def redistribute_minutes(p, m, target: float = 240.0, gamma: float = 1.0, cap: float = CAP) -> np.ndarray:
    """Conditional minutes m'_i = clip(m_i + c * m_i**gamma, 0, cap) with the scalar c solved (bisection) so that the
    expected team minutes sum(p_i * m'_i) equal ``target``. Vacated minutes (teammates with reduced P(play)) therefore
    flow to the remaining players in proportion to m**gamma; a surplus is removed the same way. If even every player
    at the cap cannot reach the target, everybody is returned at the cap (expected total < target)."""
    p = np.asarray(p, float); m = np.asarray(m, float)
    w = np.power(np.maximum(m, 1e-9), gamma)
    if float(np.sum(p * cap)) <= target:
        return np.full_like(m, cap)
    f = lambda c: float(np.sum(p * np.clip(m + c * w, 0.0, cap)))
    lo, hi = -float(np.max(m / w)), float(np.max((cap - m) / w))
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if f(mid) < target:
            lo = mid
        else:
            hi = mid
    return np.clip(m + 0.5 * (lo + hi) * w, 0.0, cap)


_LGAMMA = np.vectorize(lgamma, otypes=[float])
_LFACT_CACHE = {}


def _lfact(K):
    if K not in _LFACT_CACHE:
        _LFACT_CACHE[K] = np.cumsum(np.log(np.maximum(np.arange(K + 1), 1.0)))
    return _LFACT_CACHE[K]


def nb_pmf(mu, alpha: float, K: int) -> np.ndarray:
    """Negative-binomial pmf over 0..K for each mean in ``mu`` (variance = mu + alpha*mu^2; alpha=0 -> Poisson).
    Mass above K is folded into K so every row sums to 1."""
    mu = np.maximum(np.asarray(mu, float).reshape(-1, 1), 1e-9)
    k = np.arange(K + 1, dtype=float).reshape(1, -1)
    if alpha <= 1e-9:
        logp = k * np.log(mu) - mu - _lfact(K).reshape(1, -1)
    else:
        r = 1.0 / alpha
        lg = _LGAMMA(np.arange(K + 1) + r) - lgamma(r) - _lfact(K)
        logp = lg.reshape(1, -1) + r * np.log(r / (r + mu)) + k * np.log(mu / (r + mu))
    pm = np.exp(logp)
    pm[:, -1] += np.maximum(0.0, 1.0 - pm.sum(1))
    return pm / pm.sum(1, keepdims=True)


def build_pmf(p_play, rate, minute_scenarios, alpha: float, K: int, weights=None):
    """Hurdle mixture pmf. Returns (unconditional, conditional-on-playing), each [n, K+1].
    conditional = sum_j w_j * NB(rate * minutes_j, alpha); unconditional = (1-p)*delta_0 + p*conditional."""
    ms = np.asarray(minute_scenarios, float)
    if ms.ndim == 1:
        ms = ms.reshape(-1, 1)
    n, J = ms.shape
    w = np.full(J, 1.0 / J) if weights is None else np.asarray(weights, float) / np.sum(weights)
    rate = np.asarray(rate, float).reshape(-1)
    cond = np.zeros((n, K + 1))
    for j in range(J):
        cond += w[j] * nb_pmf(rate * ms[:, j], alpha, K)
    p = np.asarray(p_play, float).reshape(-1, 1)
    unc = p * cond
    unc[:, 0] += (1.0 - p[:, 0])
    return unc, cond


def sf_at(pmf: np.ndarray, k) -> np.ndarray:
    """P(X >= k) per row for integer thresholds k (array) from a pmf matrix."""
    cdf = np.cumsum(pmf, axis=1)
    k = np.asarray(k, int)
    idx = np.clip(k - 1, 0, pmf.shape[1] - 1)
    out = 1.0 - cdf[np.arange(len(k)), idx]
    return np.where(k <= 0, 1.0, np.clip(out, 0.0, 1.0))


def crps_rows(pmf: np.ndarray, y) -> np.ndarray:
    return np.array([C.crps_pmf(pmf[i], int(y[i])) for i in range(len(y))])


def fit_logit(x, y, ridge: float = 1e-2, iters: int = 200):
    """Ridge-stabilised logistic y ~ a + b*x (penalty pulls (a, b) to (0, 1)); Newton with step halving. Returns (a, b)."""
    x = np.asarray(x, float); y = np.asarray(y, float)

    def nll(a, b):
        z = np.clip(a + b * x, -30, 30)
        return float(np.sum(np.log1p(np.exp(z)) - y * z) + 0.5 * ridge * (a * a + (b - 1) ** 2))
    a, b = 0.0, 1.0; cur = nll(a, b)
    for _ in range(iters):
        q = 1 / (1 + np.exp(-np.clip(a + b * x, -30, 30))); w = np.clip(q * (1 - q), 1e-9, None)
        g = np.array([np.sum(y - q) - ridge * a, np.sum((y - q) * x) - ridge * (b - 1)])
        H = np.array([[np.sum(w) + ridge, np.sum(w * x)], [np.sum(w * x), np.sum(w * x * x) + ridge]])
        step = np.linalg.solve(H, g); t = 1.0
        while t > 1e-6 and nll(a + t * step[0], b + t * step[1]) > cur:
            t *= 0.5
        if t <= 1e-6:
            break
        a += t * step[0]; b += t * step[1]; new = nll(a, b)
        if cur - new < 1e-12:
            break
        cur = new
    return float(a), float(b)


def _logit(p):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def _sig(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def a0_prob(bits: np.ndarray, lam: float, a: float, prior: float) -> np.ndarray:
    """Shrunk recency-weighted share. ``bits`` [n, WINDOW]: 1/0 played in the team's k-th most recent game, NaN = no game."""
    w = np.power(lam, np.arange(bits.shape[1])).reshape(1, -1) * ~np.isnan(bits)
    return (np.nansum(bits * w, axis=1) + a * prior) / (w.sum(1) + a)


# =============================================================================================== data loading
def _hist(repo: Path) -> Path:
    return repo / "data" / "history"


def load_box(repo: Path):
    pg = pd.concat([pd.read_parquet(_hist(repo) / "espn" / f"player_games_{s}.parquet") for s in HIST_SEASONS], ignore_index=True)
    tg = pd.concat([pd.read_parquet(_hist(repo) / "espn" / f"team_games_{s}.parquet") for s in HIST_SEASONS], ignore_index=True)
    return pg, tg


def load_kalshi_markets(repo: Path) -> pd.DataFrame:
    rows = []
    for series in SERIES:
        with gzip.open(_hist(repo) / "kalshi" / f"markets_{series}.jsonl.gz", "rt") as f:
            for line in f:
                m = json.loads(line)
                rows.append(dict(ticker=m["ticker"], series=series, result=m.get("result"), floor_strike=m.get("floor_strike"),
                                 sub=m.get("yes_sub_title") or "", close_time=m.get("close_time")))
    return pd.DataFrame(rows).sort_values("ticker").reset_index(drop=True)


def load_candle_quotes(repo: Path, tip_ts: dict) -> pd.DataFrame:
    """Last hourly candle per ticker with end_period_ts in (tip-60m-6h, tip-60m]."""
    best = {}
    n_lines = 0
    for series in SERIES:
        with gzip.open(_hist(repo) / "kalshi" / f"candles_{series}.jsonl.gz", "rt") as f:
            for line in f:
                n_lines += 1
                d = json.loads(line); t = d["ticker"]; tip = tip_ts.get(t)
                if tip is None:
                    continue
                e = int(d["end_period_ts"]); cut = tip - FREEZE_MIN * 60
                if e > cut or e <= cut - 6 * 3600:
                    continue
                if t not in best or e > best[t][0]:
                    b = (d.get("yes_bid") or {}).get("close"); a = (d.get("yes_ask") or {}).get("close")
                    best[t] = (e, float(b) if b is not None else np.nan, float(a) if a is not None else np.nan)
    q = pd.DataFrame([dict(ticker=t, candle_end=v[0], bid=v[1], ask=v[2]) for t, v in sorted(best.items())],
                     columns=["ticker", "candle_end", "bid", "ask"])
    q.attrs["n_lines"] = n_lines
    return q


# =============================================================================================== feature building
def player_states(pg: pd.DataFrame, hls) -> pd.DataFrame:
    """Per-player running state AFTER each played game (joined to later games with a strictly-earlier-date as-of merge)."""
    d = pg[pg.minutes > 0].copy()
    d["used"] = d.fga + 0.44 * d.fta + d.tov
    tot = d.groupby(["game_id", "team_id"])["used"].transform("sum")
    d["use_share"] = np.where(tot > 0, d.used / tot, 0.0)
    d = d.sort_values(["nba_id", "date", "game_id"]).reset_index(drop=True)
    g = d.groupby("nba_id", sort=False)
    out = d[["nba_id", "date"]].copy()
    for hl in hls:
        out[f"em_{hl}"] = g["minutes"].transform(lambda s, hl=hl: s.ewm(halflife=hl, adjust=True).mean())
    dec = 0.5 ** (1.0 / RATE_HL)
    n = g.cumcount().to_numpy() + 1
    W = (1 - dec ** n) / (1 - dec)
    for col in ["minutes"] + STATS:
        out[f"S_{col}"] = g[col].transform(lambda s: s.ewm(alpha=1 - dec, adjust=True).mean()).to_numpy() * W
    out["use_share"] = g["use_share"].transform(lambda s: s.ewm(halflife=USAGE_HL, adjust=True).mean())
    out["n_prior"] = n
    out["state_date"] = out["date"]
    return out.sort_values(["date", "nba_id"]).reset_index(drop=True)


def build_population(pg: pd.DataFrame, season: str = SEASON, window: int = WINDOW) -> pd.DataFrame:
    """One row per (team-game, rotation player): appeared (minutes>0) in >=1 of the team's previous ``window`` games of
    the season. The target game's own box score is NOT consulted here."""
    s = pg[pg.season == season]
    tgames = s[["team_id", "game_id", "date"]].drop_duplicates().sort_values(["team_id", "date", "game_id"])
    played = {k: set(v) for k, v in s[s.minutes > 0].groupby(["game_id", "team_id"])["nba_id"]}
    rows = []
    for team, grp in tgames.groupby("team_id", sort=True):
        gl = list(zip(grp.game_id.tolist(), grp.date.tolist()))
        for t in range(1, len(gl)):
            win = gl[max(0, t - window):t][::-1]          # most recent first
            sets = [played.get((gid, team), set()) for gid, _ in win]
            for pid in sorted(set().union(*sets)):
                bits = [1.0 if pid in st else 0.0 for st in sets] + [np.nan] * (window - len(sets))
                rows.append((gl[t][0], gl[t][1], team, pid, len(sets), *bits))
    cols = ["game_id", "date", "team_id", "nba_id", "n_win"] + [f"b{i}" for i in range(window)]
    return pd.DataFrame(rows, columns=cols)


def attach_features(pop: pd.DataFrame, pg: pd.DataFrame, states: pd.DataFrame) -> pd.DataFrame:
    pop = pop.sort_values(["date", "nba_id"]).reset_index(drop=True)
    last = pg[["nba_id", "date", "team_id"]].rename(columns={"team_id": "last_team"}).sort_values(["date", "nba_id"])
    pop = pd.merge_asof(pop, last, on="date", by="nba_id", allow_exact_matches=False)
    pop = pop[pop.last_team == pop.team_id].drop(columns=["last_team"])
    pop = pd.merge_asof(pop.sort_values(["date", "nba_id"]), states, on="date", by="nba_id", allow_exact_matches=False)
    tgt = pg[["game_id", "team_id", "nba_id", "played", "minutes"] + STATS].rename(
        columns={"played": "y_play", "minutes": "y_min", **{s: f"y_{s}" for s in STATS}})
    pop = pop.merge(tgt, on=["game_id", "team_id", "nba_id"], how="left")
    pop["in_box"] = pop.y_min.notna()
    pop["y_play"] = pop.y_play.fillna(False).astype(bool) & (pop.y_min.fillna(0) > 0)
    for c in ["y_min"] + [f"y_{s}" for s in STATS]:
        pop[c] = pop[c].fillna(0.0)
    meta = pg[["game_id", "season_type", "start_time_utc", "n_ot"]].drop_duplicates("game_id")
    pop = pop.merge(meta, on="game_id", how="left")
    return pop.sort_values(["date", "game_id", "team_id", "nba_id"]).reset_index(drop=True)


# =============================================================================================== evaluation helpers
def _cohort_masks(df: pd.DataFrame) -> dict:
    d = df["date_s"]
    t1 = (d >= TRAIN_END) & (d <= TEST1_END); t2 = d > TEST1_END
    post = df["season_type"].isin(["playoffs", "playin"])
    return {"test1_2026-01-15_2026-03-15": t1.to_numpy(), "test2_2026-03-16_end": t2.to_numpy(), "test_pooled": (t1 | t2).to_numpy(),
            "test2_regular_season": (t2 & ~post).to_numpy(), "test2_postseason": (t2 & post).to_numpy()}


COH1, COH2, POOLED = "test1_2026-01-15_2026-03-15", "test2_2026-03-16_end", "test_pooled"


class Results:
    def __init__(self):
        self.rows = []

    def add(self, family, archetypes, metric, challenger_arm, reference, chal, ref, clusters, masks, headline=False, min_n=30):
        chal = np.asarray(chal, float); ref = np.asarray(ref, float); clusters = np.asarray(clusters)
        for cohort, mk in masks.items():
            if int(mk.sum()) < min_n:
                continue
            b = C.paired_cluster_bootstrap(chal[mk] - ref[mk], clusters[mk])
            self.rows.append(dict(market_family=family, archetypes=list(archetypes), metric=metric, challenger_arm=challenger_arm,
                                  reference=reference, cohort=cohort, n_rows=b["n_rows"], n_clusters=b["n_clusters"],
                                  challenger=float(chal[mk].mean()), reference_value=float(ref[mk].mean()), diff=b["mean"],
                                  ci95=[b["lo"], b["hi"]], p_raw=b["p_two_sided"], p_holm=1.0, replicated=False, verdict="INCONCLUSIVE",
                                  headline=bool(headline and cohort == POOLED)))

    def finalize(self):
        key = lambda r: (r["market_family"], r["metric"], r["challenger_arm"], r["reference"])
        by = {}
        for r in self.rows:
            by.setdefault(key(r), {})[r["cohort"]] = r["diff"]
        for r in self.rows:
            c = by[key(r)]
            r["replicated"] = bool(COH1 in c and COH2 in c and c[COH1] < 0 and c[COH2] < 0)
        head = [r for r in self.rows if r["headline"]]
        for r, ph in zip(head, C.holm([r["p_raw"] for r in head])):
            r["p_holm"] = float(ph)
        for r in self.rows:
            r["verdict"] = C.verdict_from(r["ci95"][0], r["ci95"][1], r["p_holm"], r["replicated"])
        return self.rows

    def find(self, family, metric, arm, reference, cohort=POOLED):
        for r in self.rows:
            if (r["market_family"], r["metric"], r["challenger_arm"], r["reference"], r["cohort"]) == (family, metric, arm, reference, cohort):
                return r
        return None


def _reliability(p, y, bins=10):
    p = np.asarray(p, float); y = np.asarray(y, float); out = []
    idx = np.clip((p * bins).astype(int), 0, bins - 1)
    for b in range(bins):
        m = idx == b
        if m.any():
            out.append(dict(bin_lo=b / bins, bin_hi=(b + 1) / bins, n=int(m.sum()), mean_p=float(p[m].mean()), mean_y=float(y[m].mean())))
    return out


def _chk(name, passed, detail):
    return C.check(name, passed, detail)


def _scenario_table(m_pred, y_min, train_played):
    """TRAIN residual quantiles (actual - predicted minutes | played) per predicted-minutes bucket -> [n_bucket, N_SCEN]."""
    qs = (np.arange(N_SCEN) + 0.5) / N_SCEN
    b = np.digitize(m_pred, MIN_BUCKETS[1:-1])
    tab = np.zeros((len(MIN_BUCKETS) - 1, N_SCEN))
    allres = (y_min - m_pred)[train_played]
    for i in range(tab.shape[0]):
        r = (y_min - m_pred)[train_played & (b == i)]
        tab[i] = np.quantile(r if len(r) >= 50 else allres, qs)
    return tab


def _scenarios(m_pred, tab):
    b = np.digitize(m_pred, MIN_BUCKETS[1:-1])
    return np.clip(m_pred.reshape(-1, 1) + tab[b], 0.5, 53.0)


def _interval_cover(pmf, y, lo_q=0.1, hi_q=0.9):
    cdf = np.cumsum(pmf, axis=1)
    lo = (cdf < lo_q).sum(1); hi = np.minimum((cdf < hi_q).sum(1), pmf.shape[1] - 1)
    return float(np.mean((y >= lo) & (y <= hi)))


# =============================================================================================== main pipeline
def run(repo: Path | None = None, out_dir: Path | None = None, verbose: bool = True) -> dict:
    repo = Path(repo) if repo else C.repos_dir() / "nba-edge-finder"
    out_dir = Path(out_dir) if out_dir else OUT_DIR
    say = (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)
    checks_box, checks_inj, checks_min, checks_dist, checks_mkt = [], [], [], [], []

    # ------------------------------------------------------------------ box scores
    pg_raw, tg_raw = load_box(repo)
    dup = int(pg_raw.duplicated(["game_id", "team_id", "nba_id"]).sum())
    checks_box.append(_chk("box_no_duplicate_player_game_rows", dup == 0, f"{dup} duplicate (game_id, team_id, nba_id) rows in {len(pg_raw)} rows"))
    miss = int(pg_raw[["minutes", "pts", "reb", "ast", "fg3m", "start_time_utc"]].isna().sum().sum())
    checks_box.append(_chk("box_no_missing_core_fields", miss == 0, f"{miss} missing values in minutes/pts/reb/ast/fg3m/start_time_utc"))
    pg = pg_raw[pg_raw.season_type != "preseason"].copy()
    pg["date"] = pd.to_datetime(pg.game_date_et)
    incons = int(((pg.played) & (pg.minutes <= 0)).sum() + ((~pg.played) & (pg.minutes > 0)).sum())
    checks_box.append(_chk("box_played_flag_consistent_with_minutes", incons == 0,
                           f"{incons} non-preseason rows where played flag and minutes>0 disagree (of {len(pg)}); outcome 'played' = flag AND minutes>0"))
    ts = pg.groupby(["game_id", "team_id"]).agg(m=("minutes", "sum"), ot=("n_ot", "first"))
    dev = (ts.m - (240 + 25 * ts.ot)).abs()
    ok5 = float((dev <= 5).mean())
    checks_box.append(_chk("team_minutes_sum_240_plus_25_per_ot", ok5 >= 0.98,
                           f"{len(ts)} team-games: share within +-5 min of 240+25*n_ot is {ok5:.4f}; within +-2 is {float((dev <= 2).mean()):.4f}; "
                           f"max abs deviation {float(dev.max()):.0f} (ESPN minutes are whole-minute rounded per player)"))

    hls = [0.5, 1.0, 1.5, 2.0, 2.5, 4.0, 6.0, 10.0]
    states = player_states(pg, hls)
    pop = build_population(pg)
    n_cand = len(pop)
    pop = attach_features(pop, pg, states)
    pop["date_s"] = pop.date.dt.strftime("%Y-%m-%d")
    pop["tip_ts"] = _epoch_s(pop.start_time_utc)
    N = len(pop)
    train = (pop.date_s < TRAIN_END).to_numpy()
    masks = _cohort_masks(pop)
    test = masks[POOLED]
    y_play = pop.y_play.to_numpy().astype(float); y_min = pop.y_min.to_numpy()
    played = y_play > 0
    gid = pop.game_id.to_numpy()
    say(f"population rows {N} (candidates before latest-team filter {n_cand}); train {int(train.sum())} test {int(test.sum())}")
    leak_ok = bool((pop.state_date < pop.date).all()) and bool(pop.state_date.notna().all())
    # independent recomputation of the minutes EWM for a deterministic sample from strictly-earlier games only
    samp = pop.iloc[np.linspace(0, N - 1, 300).astype(int)]
    pl = pg[pg.minutes > 0]
    em4 = samp["em_4.0"].to_numpy()
    re4 = np.array([float(pl[(pl.nba_id == a) & (pl.date < d)].sort_values(["date", "game_id"]).minutes.ewm(halflife=4.0, adjust=True).mean().iloc[-1])
                    for a, d in zip(samp.nba_id, samp.date)])
    maxdiff = float(np.max(np.abs(em4 - re4)))
    checks_min.append(_chk("leak_guard_features_use_strictly_earlier_dates", leak_ok and maxdiff < 1e-9,
                           f"all {N} rows: latest feature-state date < game date = {leak_ok}; 300-row recomputation of the minutes EWM from "
                           f"strictly-earlier games only: max abs difference {maxdiff:.2e}"))
    box_out = pg[(pg.season == SEASON) & (pg.minutes > 0)].merge(pop[["game_id", "team_id", "nba_id"]].assign(inpop=1), on=["game_id", "team_id", "nba_id"], how="left")
    box_out = box_out[box_out.game_id.isin(set(gid))]
    tg_out = box_out.assign(outmin=np.where(box_out.inpop.isna(), box_out.minutes, 0.0)).groupby(["game_id", "team_id"]).agg(outmin=("outmin", "sum"), ot=("n_ot", "first"), date=("game_date_et", "first"))
    tr_tg = tg_out[tg_out.date < TRAIN_END]
    r_out = float(tr_tg.outmin.mean()); ot_extra = float(25 * tr_tg.ot.mean())
    target_total = 240.0 + ot_extra - r_out
    share_out = float(box_out.inpop.isna().mean())

    # ------------------------------------------------------------------ injury reports (PIT)
    rr = pd.read_parquet(_hist(repo) / "injury_reports" / f"report_rows_{SEASON}.parquet")
    reports = pd.read_parquet(_hist(repo) / "injury_reports" / f"reports_{SEASON}.parquet")
    snaps = pd.read_parquet(_hist(repo) / "injury_reports" / f"game_snapshots_{SEASON}.parquet")
    games = pop[["game_id", "start_time_utc"]].drop_duplicates("game_id").rename(columns={"start_time_utc": "tip_utc"})
    rr = rr.merge(reports[["report_time_utc", "last_modified_utc"]].drop_duplicates("report_time_utc").rename(columns={"last_modified_utc": "published_utc"}),
                  on="report_time_utc", how="left")
    n_nopub = int(rr.published_utc.isna().sum())
    sel, pstat, tstat = select_pit_status(rr, games)
    prow = rr[rr.status != "not_yet_submitted"]
    m_rate = float(prow.nba_id.notna().mean())
    checks_inj.append(_chk("injury_rows_entity_match_rate", m_rate >= 0.95,
                           f"{int(prow.nba_id.notna().sum())}/{len(prow)} player rows carry an nba_id ({m_rate:.4f}); match_method counts: "
                           + json.dumps({k: int(v) for k, v in sorted(rr.match_method.value_counts().items())})))
    boxkeys = set(zip(pg_raw.game_id, pg_raw.nba_id))
    sel_rows = pstat.merge(sel[sel.report_ts >= 0][["game_id"]], on="game_id")
    inbox = np.array([(g, i) in boxkeys for g, i in zip(sel_rows.game_id, sel_rows.nba_id)])
    checks_inj.append(_chk("selected_report_rows_found_in_box_score_ids", C.ATTESTED,
                           f"{int(inbox.sum())}/{len(inbox)} ({float(inbox.mean()):.4f}) of T-60-selected matched player rows have a box-score row (played or DNP) "
                           f"for that game; the rest are inactive players ESPN does not list. Informational."))
    drr = int(rr[rr.nba_id.notna()].duplicated(["report_time_utc", "game_id", "nba_id"]).sum())
    checks_inj.append(_chk("injury_rows_duplicates_within_report", drr == 0,
                           f"{drr} duplicate (report, game, player) rows; duplicates are resolved to the most severe status"))
    n_games = len(sel); has_rep = sel.report_ts >= 0
    viol = int((sel.avail_ts[has_rep] > sel.cutoff_ts[has_rep]).sum())
    checks_inj.append(_chk("leak_guard_report_time_le_tip_minus_60", viol == 0,
                           f"{int(has_rep.sum())}/{n_games} games have a selected report; {viol} selected reports were published (max of header time and file last-modified) later than tip-60min; "
                           f"{n_nopub} report rows lack a last-modified time and fall back to the header time; "
                           f"median lead {float(sel.lead_min.median()):.0f} min, max {float(sel.lead_min.max()):.0f} min"))
    sn = snaps[["game_id", "tip_utc", "t_minus_60_report_time_utc", "t_minus_60_pit_ok"]].merge(sel, on="game_id", how="inner")
    pit_ok_share = float(snaps[snaps.game_id.isin(set(games.game_id))].t_minus_60_pit_ok.mean())
    n_snap = int(snaps.game_id.isin(set(games.game_id)).sum())
    checks_inj.append(_chk("share_of_games_with_pit_ok_t60_snapshot", n_snap / n_games >= 0.95 and pit_ok_share >= 0.95,
                           f"{n_snap}/{n_games} evaluated games are in the owner's game_snapshots table; t_minus_60_pit_ok share among them {pit_ok_share:.4f}; "
                           f"own selection found a report for {float(has_rep.mean()):.4f} of games"))
    snok = sn[sn.t_minus_60_pit_ok & (sn.report_ts >= 0)]
    agree = float((_epoch_s(snok.t_minus_60_report_time_utc) == snok.report_ts.to_numpy()).mean()) if len(snok) else float("nan")
    tipdiff = float(np.mean(np.abs(_epoch_s(sn.tip_utc) - (sn.cutoff_ts.to_numpy() + FREEZE_MIN * 60)) <= 60)) if len(sn) else float("nan")
    checks_inj.append(_chk("own_t60_selection_agrees_with_owner_snapshot", agree >= 0.95,
                           f"selected report time equals the owner's t_minus_60_report_time_utc for {agree:.4f} of {len(snok)} pit_ok games; "
                           f"box-score tip equals snapshot tip (+-60s) for {tipdiff:.4f}"))
    hdr = float(reports.header_time_matches_slot.mean())
    checks_inj.append(_chk("report_header_time_matches_slot", C.ATTESTED,
                           f"reports table: {len(reports)} reports, header_time_matches_slot share {hdr:.4f} (report_time_utc from the PDF header is used, "
                           f"which is 30 min after the nominal slot; informational)"))

    pop = pop.merge(pstat, on=["game_id", "nba_id"], how="left")
    pop = pop.merge(tstat.assign(team_ns=True), on=["game_id", "team_id"], how="left")
    pop = pop.merge(sel[["game_id", "report_ts"]], on="game_id", how="left")
    st = pop.status.astype(object).where(pop.status.notna(), None).to_numpy()
    status = np.array([s if s is not None else ("no_report" if rt < 0 else ("team_not_submitted" if tn is True else "not_listed"))
                       for s, rt, tn in zip(st, pop.report_ts.to_numpy(), pop.team_ns.to_numpy())], dtype=object)
    pop["status"] = status
    assert len(pop) == N

    # ------------------------------------------------------------------ A0 (TRAIN fit)
    bits = pop[[f"b{i}" for i in range(WINDOW)]].to_numpy(float)
    prior = float(y_play[train].mean())
    best = None
    for lam in (1.0, 0.85, 0.7, 0.55, 0.4):
        for a in (0.1, 0.25, 0.5, 1.0, 2.0, 4.0):
            p = a0_prob(bits, lam, a, prior)
            ll = float(C.logloss_rows(p[train], y_play[train]).mean())
            if best is None or ll < best[0] - 1e-12:
                best = (ll, lam, a)
    _, lam0, a0 = best
    p0 = np.clip(a0_prob(bits, lam0, a0, prior), 0.002, 0.998)
    bestm = None
    for hl in hls:
        e = float(np.abs(pop[f"em_{hl}"].to_numpy() - y_min)[train & played].mean())
        if bestm is None or e < bestm[0] - 1e-12:
            bestm = (e, hl)
    hl_min = bestm[1]
    m0 = pop[f"em_{hl_min}"].to_numpy().astype(float)

    # ------------------------------------------------------------------ A1 (TRAIN fit): P(play | status, A0 share), minutes multiplier
    x0 = _logit(p0)
    p1 = p0.copy(); rho = np.ones(N); status_params = {}; status_table = []
    for s in STATUS_ORDER:
        ms = status == s; tr = ms & train
        n_tr = int(tr.sum())
        if n_tr >= 200 and s != "no_report":
            a, b = fit_logit(x0[tr], y_play[tr])
        elif n_tr >= 30 and s != "no_report":
            a, b = fit_logit(x0[tr], y_play[tr], ridge=1e6)   # effectively identity when the status is too rare
            a = float(_logit(np.clip(y_play[tr].mean(), 0.002, 0.998)) - np.mean(x0[tr])); b = 1.0
        else:
            a, b = 0.0, 1.0
        p1[ms] = np.clip(_sig(a + b * x0[ms]), 0.002, 0.998)
        trp = tr & played
        r_s = float(y_min[trp].sum() / m0[trp].sum()) if int(trp.sum()) >= 100 else 1.0
        rho[ms] = r_s
        status_params[s] = dict(intercept=a, slope_on_logit_a0=b, minutes_multiplier=r_s, n_train=n_tr)
        te = ms & test
        status_table.append(dict(status=s, n_train=n_tr, play_rate_train=float(y_play[tr].mean()) if n_tr else None,
                                 n_test=int(te.sum()), play_rate_test=float(y_play[te].mean()) if te.any() else None,
                                 mean_p_a0_test=float(p0[te].mean()) if te.any() else None, mean_p_a1_test=float(p1[te].mean()) if te.any() else None,
                                 mean_ewm_minutes_test=float(m0[te].mean()) if te.any() else None))
    m1 = np.clip(m0 * rho, 0.5, CAP)

    # ------------------------------------------------------------------ A2 (TRAIN fit): redistribution
    grp_key = pd.factorize(pd.Series(gid).astype(str) + "|" + pop.team_id.astype(str))[0]
    groups = [np.where(grp_key == k)[0] for k in range(grp_key.max() + 1)]

    def redistribute_all(gamma, only=None):
        out = m1.copy()
        for ix in groups:
            if only is not None and not only[ix[0]]:
                continue
            out[ix] = redistribute_minutes(p1[ix], m1[ix], target_total, gamma, CAP)
        return out

    bestg = None; gamma_grid = {}
    for gamma in (-1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0):
        mg = redistribute_all(gamma, only=train)
        e = float(np.abs(mg - y_min)[train & played].mean())
        gamma_grid[str(gamma)] = e
        if bestg is None or e < bestg[0] - 1e-12:
            bestg = (e, gamma)
    gamma = bestg[1]
    m2 = redistribute_all(gamma)
    train_cond_mae_a1 = float(np.abs(m1 - y_min)[train & played].mean())
    exp_tot = np.array([float(np.sum(p1[ix] * m2[ix])) for ix in groups])
    capped = np.array([float(np.sum(p1[ix] * CAP)) <= target_total for ix in groups])
    cons = float(np.max(np.abs(exp_tot[~capped] - target_total)))
    checks_min.append(_chk("a2_expected_team_minutes_conserved", cons < 1e-6 and float(m2.max()) <= CAP + 1e-9,
                           f"{len(groups)} team-games: max |sum(p*m') - {target_total:.3f}| = {cons:.2e} over {int((~capped).sum())} solvable team-games "
                           f"({int(capped.sum())} could not reach the target even at the cap); max conditional minutes {float(m2.max()):.2f} <= 48. "
                           f"Target = 240 + {ot_extra:.3f} (TRAIN overtime) - {r_out:.3f} (TRAIN mean minutes of out-of-population players)"))
    raw_tot = np.array([float(np.sum(p1[ix] * m1[ix])) for ix in groups])
    raw0 = np.array([float(np.sum(p0[ix] * m0[ix])) for ix in groups])
    checks_min.append(_chk("plausibility_probabilities_and_minutes", bool((p0 > 0).all() and (p1 < 1).all() and (m0 > 0).all() and (m0 <= 60).all()),
                           f"P(play) in (0,1) for all rows; EWM minutes range [{float(m0.min()):.2f}, {float(m0.max()):.2f}]; unconstrained expected team minutes "
                           f"A0 mean {float(raw0.mean()):.1f} (sd {float(raw0.std()):.1f}), A1 mean {float(raw_tot.mean()):.1f} (sd {float(raw_tot.std()):.1f}); "
                           f"{share_out:.4f} of played box rows are out-of-population (returning/new players)"))

    # vacated usage (PIT: from A1 probabilities) for the optional points bump
    us = pop.use_share.to_numpy().astype(float)
    vac = np.zeros(N); out_big = np.zeros(N, bool)
    stat_out = np.isin(status, ["out", "doubtful"])
    for ix in groups:
        v = (1 - p1[ix]) * us[ix]
        vac[ix] = v.sum() - v
        big = stat_out[ix] & (m0[ix] >= 20)
        out_big[ix] = (big.sum() - big) > 0
    vac_c = vac - float(vac[train].mean())

    # ------------------------------------------------------------------ rates, calibration, dispersion (TRAIN fit)
    prev = pg_raw[(pg_raw.season == "2024-25") & (pg_raw.season_type == "regular") & (pg_raw.minutes > 0)]
    r0 = {s: float(prev[s].sum() / prev.minutes.sum()) for s in STATS}
    Smin = pop.S_minutes.to_numpy().astype(float)
    trp = train & played; tep = test & played
    params_stat = {}; rate = {}
    for s in STATS:
        y = pop[f"y_{s}"].to_numpy(); S = pop[f"S_{s}"].to_numpy().astype(float); bestk = None
        for k in (15.0, 30.0, 60.0, 120.0, 250.0, 500.0, 1000.0):
            mu = np.maximum((S + k * r0[s]) / (Smin + k) * y_min, 1e-9)
            dv = float(np.mean((mu - y * np.log(mu))[trp]))
            if bestk is None or dv < bestk[0] - 1e-12:
                bestk = (dv, k)
        rate[s] = (S + bestk[1] * r0[s]) / (Smin + bestk[1])
        params_stat[s] = dict(prior_minutes=bestk[1], league_rate_per_min_2024_25=r0[s])

    arms_min = {"A0": m0, "A1": m1, "A2": m2}
    arms_p = {"A0": p0, "A1": p1, "A2": p1}
    scen = {}; scen_tabs = {}
    for a, mm in arms_min.items():
        tab = _scenario_table(mm, y_min, trp); scen_tabs[a] = tab; scen[a] = _scenarios(mm, tab)
    # usage bump (points only), fitted on TRAIN played rows with A2 minutes
    y_pts = pop.y_pts.to_numpy()
    base_mu = rate["pts"] * scen["A2"].mean(1)
    bestb = None; beta_grid = {}
    for beta in (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0):
        mu = base_mu * np.exp(beta * vac_c); mu = mu * (y_pts[trp].sum() / mu[trp].sum())
        dv = float(np.mean((mu - y_pts * np.log(mu))[trp])); beta_grid[str(beta)] = dv
        if bestb is None or dv < bestb[0] - 1e-12:
            bestb = (dv, beta)
    beta = bestb[1]
    # the bump is only kept when it beats beta=0 by a non-trivial TRAIN margin
    if beta > 0 and (beta_grid["0.0"] - bestb[0]) < 1e-4:
        beta = 0.0
    mult = {a: {s: np.ones(N) for s in STATS} for a in arms_min}
    mult["A2"]["pts"] = np.exp(beta * vac_c)
    cal = {a: {} for a in arms_min}; alpha = {}
    uncond = {a: {} for a in arms_min}; cond = {a: {} for a in arms_min}
    for s in STATS:
        y = pop[f"y_{s}"].to_numpy()
        for a in arms_min:
            mu = rate[s] * mult[a][s] * scen[a].mean(1)
            cal[a][s] = float(y[trp].sum() / mu[trp].sum())
        besta = None; a_grid = {}
        r_eff = rate[s] * cal["A1"][s]
        yi = y[trp].astype(int)
        for al in (0.0, 0.02, 0.04, 0.07, 0.1, 0.15, 0.2, 0.3, 0.45, 0.6):
            _, cnd = build_pmf(np.ones(int(trp.sum())), r_eff[trp], scen["A1"][trp], al, KMAX[s])
            ll = float(-np.mean(np.log(np.maximum(cnd[np.arange(len(yi)), np.minimum(yi, KMAX[s])], 1e-12)))); a_grid[str(al)] = ll
            if besta is None or ll < besta[0] - 1e-12:
                besta = (ll, al)
        alpha[s] = besta[1]
        params_stat[s].update(nb_alpha=alpha[s], train_nll_by_alpha=a_grid, calibration_multiplier={a: cal[a][s] for a in arms_min})
        for a in arms_min:
            uncond[a][s], cond[a][s] = build_pmf(arms_p[a], rate[s] * mult[a][s] * cal[a][s], scen[a], alpha[s], KMAX[s])
        sums = max(float(np.max(np.abs(uncond[a][s].sum(1) - 1))) for a in arms_min)
        checks_dist.append(_chk(f"pmf_sums_to_one_{s}", sums < 1e-9, f"max |sum(pmf)-1| over {N} rows x 3 arms = {sums:.2e}; support 0..{KMAX[s]}, "
                                f"share of actual values above support {float((y > KMAX[s]).mean()):.6f}"))
    say(f"fitted: A0 lam={lam0} a={a0} hl={hl_min} gamma={gamma} beta={beta} alpha={alpha} target={target_total:.2f}")

    # ------------------------------------------------------------------ results: participation, minutes, stats
    R = Results()
    AV = ["NBA:player_availability"]
    for metric, fn in (("brier_p_play", C.brier_rows), ("logloss_p_play", C.logloss_rows)):
        R.add("player_availability", AV, metric, "A1", "A0 no-report proxy", fn(p1, y_play), fn(p0, y_play), gid, masks, headline=(metric == "brier_p_play"))
    em = {a: arms_p[a] * arms_min[a] for a in arms_min}
    ghost = {a: ((em[a] >= 10) & ~played).astype(float) for a in em}
    R.add("player_availability", AV, "ghost_projection_rate_ge10_expected_min_but_absent", "A1", "A0 no-report proxy", ghost["A1"], ghost["A0"], gid, masks)
    R.add("player_availability", AV, "ghost_projection_rate_ge10_expected_min_but_absent", "A2", "A0 no-report proxy", ghost["A2"], ghost["A0"], gid, masks)
    MINARCH = AV + ALL_PROP_ARCH
    for (a, b, hd) in (("A1", "A0", True), ("A2", "A1", True), ("A2", "A0", False)):
        refname = "A0 no-report proxy" if b == "A0" else "A1 (A0 + PIT injury gate)"
        R.add("player_minutes", MINARCH, "abs_err_expected_minutes_unconditional", a, refname, np.abs(em[a] - y_min), np.abs(em[b] - y_min), gid, masks, headline=hd)
        R.add("player_minutes", MINARCH, "sq_err_expected_minutes_unconditional", a, refname, (em[a] - y_min) ** 2, (em[b] - y_min) ** 2, gid, masks)
    tm = played & out_big
    mk_tm = {k: v[tm] for k, v in masks.items()}
    R.add("player_minutes", MINARCH, "abs_err_minutes_given_played_teammates_of_T60_out_or_doubtful_20min_player", "A2", "A1 (A0 + PIT injury gate)",
          np.abs(m2 - y_min)[tm], np.abs(m1 - y_min)[tm], gid[tm], mk_tm, headline=True)
    mk_pl = {k: v[played] for k, v in masks.items()}
    R.add("player_minutes", MINARCH, "abs_err_minutes_given_played", "A2", "A1 (A0 + PIT injury gate)", np.abs(m2 - y_min)[played], np.abs(m1 - y_min)[played], gid[played], mk_pl)
    R.add("player_minutes", MINARCH, "abs_err_minutes_given_played", "A1", "A0 no-report proxy", np.abs(m1 - y_min)[played], np.abs(m0 - y_min)[played], gid[played], mk_pl)

    stat_summary = {}
    evalm = train | test
    for s in STATS:
        y = pop[f"y_{s}"].to_numpy(); K = KMAX[s]; ks = np.arange(K + 1)
        cr_u = {a: np.where(test, 0.0, np.nan) for a in arms_min}; cr_c = {a: np.full(N, np.nan) for a in arms_min}
        mean_u = {a: uncond[a][s] @ ks for a in arms_min}; mean_c = {a: cond[a][s] @ ks for a in arms_min}
        for a in arms_min:
            cr_u[a][test] = crps_rows(uncond[a][s][test], y[test])
            cr_c[a][tep] = crps_rows(cond[a][s][tep], y[tep])
        fam = FAMILY[s]
        A0n, A1n = "A0 no-report proxy", "A1 (A0 + PIT injury gate)"
        R.add(fam, [ARCH[s]], "crps_unconditional_all_rotation_rows", "A2", A0n, cr_u["A2"], cr_u["A0"], gid, masks, headline=True)
        R.add(fam, [ARCH[s]], "crps_unconditional_all_rotation_rows", "A1", A0n, cr_u["A1"], cr_u["A0"], gid, masks)
        R.add(fam, [ARCH[s]], "abs_err_mean_unconditional_all_rotation_rows", "A2", A0n, np.abs(mean_u["A2"] - y), np.abs(mean_u["A0"] - y), gid, masks)
        R.add(fam, [ARCH[s]], "crps_given_played", "A2", A1n, cr_c["A2"][played], cr_c["A1"][played], gid[played], mk_pl, headline=True)
        R.add(fam, [ARCH[s]], "crps_given_played", "A1", A0n, cr_c["A1"][played], cr_c["A0"][played], gid[played], mk_pl)
        R.add(fam, [ARCH[s]], "crps_given_played", "A2", A0n, cr_c["A2"][played], cr_c["A0"][played], gid[played], mk_pl)
        R.add(fam, [ARCH[s]], "abs_err_mean_given_played", "A2", A1n, np.abs(mean_c["A2"] - y)[played], np.abs(mean_c["A1"] - y)[played], gid[played], mk_pl)
        R.add(fam, [ARCH[s]], "abs_err_mean_given_played", "A2", A0n, np.abs(mean_c["A2"] - y)[played], np.abs(mean_c["A0"] - y)[played], gid[played], mk_pl)
        stat_summary[s] = {a: dict(
            crps_unconditional=float(cr_u[a][test].mean()), mae_unconditional=float(np.abs(mean_u[a] - y)[test].mean()),
            crps_given_played=float(cr_c[a][tep].mean()), mae_given_played=float(np.abs(mean_c[a] - y)[tep].mean()),
            bias_given_played=float((mean_c[a] - y)[tep].mean()),
            cover80_unconditional=_interval_cover(uncond[a][s][test], y[test]), cover80_given_played=_interval_cover(cond[a][s][tep], y[tep]),
            n_all=int(test.sum()), n_played=int(tep.sum())) for a in arms_min}

    # ------------------------------------------------------------------ Kalshi prop ladders
    mk = load_kalshi_markets(repo)
    parsed = [parse_prop_ticker(t) for t in mk.ticker]
    mk["parsed"] = [p is not None for p in parsed]
    for c in ("stat", "date", "away", "home", "team", "strike"):
        mk[c] = [p[c] if p else None for p in parsed]
    s25 = pg_raw[(pg_raw.season == SEASON)]
    home_rows = s25[s25.home][["game_id", "game_date_et", "team_id", "opp_team_id", "start_time_utc", "season_type"]].drop_duplicates("game_id")
    gkey = {(d, TEAM_TRICODES.get(o), TEAM_TRICODES.get(h)): g for g, d, h, o in zip(home_rows.game_id, home_rows.game_date_et, home_rows.team_id, home_rows.opp_team_id)}
    mk["game_id"] = [gkey.get((d, a, h)) for d, a, h in zip(mk.date, mk.away, mk.home)]
    s25n = s25.assign(nn=s25.player_name.map(norm_name))
    by_game_team = {}; by_game = {}; by_team_season = {}
    for g, t, nn, pid in zip(s25n.game_id, s25n.team_id, s25n.nn, s25n.nba_id):
        by_game_team.setdefault((g, t, nn), set()).add(pid); by_game.setdefault((g, nn), set()).add(pid); by_team_season.setdefault((t, nn), set()).add(pid)
    pid_l, how_l = [], []
    for g, team, sub in zip(mk.game_id, mk.team, mk["sub"]):
        nn = norm_name(sub.split(":")[0]); tid = TRICODE_TO_TEAM.get(team) if team else None
        c1 = by_game_team.get((g, tid, nn), set()) if g else set()
        c2 = by_game.get((g, nn), set()) if g else set()
        c3 = by_team_season.get((tid, nn), set())
        if g is None:
            pid_l.append(None); how_l.append("no_game")
        elif len(c1) == 1:
            pid_l.append(next(iter(c1))); how_l.append("game_team_name")
        elif len(c2) == 1:
            pid_l.append(next(iter(c2))); how_l.append("game_name")
        elif len(c3) == 1:
            pid_l.append(next(iter(c3))); how_l.append("team_season_name")
        else:
            pid_l.append(None); how_l.append("no_player")
    mk["nba_id"] = pd.array(pid_l, dtype="Int64"); mk["match_how"] = how_l
    mk["matched"] = mk.nba_id.notna()
    strike_ok = float((mk.strike[mk.parsed].astype(float) == (mk.floor_strike[mk.parsed].astype(float) + 0.5)).mean())
    gmeta = home_rows.set_index("game_id")
    mk["tip_ts"] = mk.game_id.map(dict(zip(home_rows.game_id, _epoch_s(home_rows.start_time_utc))))
    mk["season_type"] = mk.game_id.map(gmeta.season_type.to_dict())
    mk["date_s"] = mk.game_id.map(gmeta.game_date_et.to_dict())
    rowidx = {(g, int(i)): k for k, (g, i) in enumerate(zip(gid, pop.nba_id))}
    mk["row"] = [rowidx.get((g, int(i)), -1) if (g is not None and not pd.isna(i)) else -1 for g, i in zip(mk.game_id, mk.nba_id)]
    mk["is_test"] = mk.date_s.notna() & (mk.date_s >= TRAIN_END)
    counts_all = dict(
        markets_total=int(len(mk)), ticker_parsed=int(mk.parsed.sum()), game_matched=int(mk.game_id.notna().sum()), player_matched=int(mk.matched.sum()),
        match_rate=float(mk.matched.mean()), match_method={k: int(v) for k, v in sorted(mk.match_how.value_counts().items())},
        result={k: int(v) for k, v in sorted(mk.result.fillna("none").value_counts().items())},
        ticker_strike_equals_floor_strike_plus_half=strike_ok,
        by_series={sr: dict(total=int((mk.series == sr).sum()), matched=int(((mk.series == sr) & mk.matched).sum()),
                            scalar_dnp=int(((mk.series == sr) & (mk.result == "scalar")).sum())) for sr in SERIES})
    tt = mk[mk.is_test]
    yn = tt.result.isin(["yes", "no"])
    counts_test = dict(markets_in_test_window=int(len(tt)), yes_no=int(yn.sum()), scalar_dnp_excluded=int((tt.result == "scalar").sum()),
                       other_result_excluded=int((~yn & (tt.result != "scalar")).sum()),
                       yes_no_with_model_row=int((yn & (tt.row >= 0)).sum()), yes_no_player_not_in_rotation_population=int((yn & (tt.row < 0)).sum()),
                       scalar_dnp_with_model_row=int(((tt.result == "scalar") & (tt.row >= 0)).sum()),
                       unmatched_markets_any_window=int((~mk.matched).sum()))
    sc_rows = tt[(tt.result == "scalar") & (tt.row >= 0)].row.to_numpy()
    scalar_diag = dict(n=int(len(sc_rows)), mean_p_play_a0=float(p0[sc_rows].mean()) if len(sc_rows) else None,
                       mean_p_play_a1=float(p1[sc_rows].mean()) if len(sc_rows) else None,
                       note="markets settled 'scalar' (player did not enter the game); not scored, shown to document what the PIT gate knew")
    K = tt[yn & (tt.row >= 0)].copy().reset_index(drop=True)
    K["y"] = (K.result == "yes").astype(float)
    kr = K.row.to_numpy(); kk = K.strike.to_numpy().astype(int)
    pk = {a: np.zeros(len(K)) for a in arms_min}
    for s in STATS:
        msk = (K.stat == s).to_numpy()
        for a in arms_min:
            pk[a][msk] = sf_at(cond[a][s][kr[msk]], kk[msk])
    for a in arms_min:
        K[f"p_{a}"] = np.clip(pk[a], 1e-4, 1 - 1e-4)
    box_played = float(played[kr].mean())
    checks_mkt.append(_chk("kalshi_yes_no_markets_are_players_who_played", box_played >= 0.99,
                           f"{box_played:.4f} of {len(K)} scored yes/no markets belong to a box-score 'played' player-game (consistent with the DNP->scalar rule)"))
    # box-score truth vs Kalshi settlement
    ybox = np.array([float(pop[f"y_{s}"].to_numpy()[r] >= k) for s, r, k in zip(K.stat, kr, kk)])
    agree_y = float((ybox == K.y.to_numpy()).mean())
    checks_mkt.append(_chk("kalshi_result_agrees_with_box_score_threshold", agree_y >= 0.995,
                           f"Kalshi yes/no equals 1[box stat >= strike] for {agree_y:.5f} of {len(K)} matched markets (validates the ticker->game/player/strike mapping)"))
    mts = pd.read_parquet(repo / "data" / "research" / "market_table_scored.parquet")
    mts = mts[mts.scope == "player"][["ticker", "p_data_only", "player_id", "game_id"]].drop_duplicates("ticker")
    chk = mts.merge(mk[["ticker", "nba_id", "game_id"]], on="ticker", how="inner", suffixes=("_o", "_m"))
    both = chk[chk.nba_id.notna() & chk.player_id.notna()]
    id_agree = float((both.nba_id.astype("int64") == both.player_id.astype("int64")).mean()); g_agree = float((both.game_id_o == both.game_id_m).mean())
    checks_mkt.append(_chk("ticker_mapping_agrees_with_owner_market_table", id_agree >= 0.995 and g_agree >= 0.995,
                           f"{len(both)} overlapping tickers: own player id equals owner's player_id for {id_agree:.5f}, game_id for {g_agree:.5f}"))
    checks_mkt.append(_chk("kalshi_entity_match_rate", counts_all["match_rate"] >= 0.97,
                           f"{counts_all['player_matched']}/{counts_all['markets_total']} markets mapped to (game, player) = {counts_all['match_rate']:.4f}; "
                           f"methods {json.dumps(counts_all['match_method'])}; unmatched are counted, never dropped silently"))
    K = K.merge(mts[["ticker", "p_data_only"]], on="ticker", how="left")
    v3 = pd.read_csv(repo / "docs" / "research" / "prop_walk_forward_v3.csv")[["ticker", "p_sim"]].drop_duplicates("ticker")
    K = K.merge(v3, on="ticker", how="left")
    q = load_candle_quotes(repo, dict(zip(mk.ticker[mk.tip_ts.notna()], mk.tip_ts[mk.tip_ts.notna()].astype("int64"))))
    K = K.merge(q, on="ticker", how="left")
    two = K.bid.notna() & K.ask.notna() & (K.bid >= 0.01) & (K.ask <= 0.99) & (K.ask > K.bid)
    K["mid"] = np.where(two, (K.bid + K.ask) / 2, np.nan)
    K["spread"] = np.where(two, K.ask - K.bid, np.nan)
    assert len(K) == len(kr)
    kmasks = _cohort_masks(K)
    kg = K.game_id.to_numpy(); ky = K.y.to_numpy()
    refs = {"A0 no-report proxy": ("p_A0", np.ones(len(K), bool)),
            "incumbent nba-sim-0.1.0 market_table_scored.p_data_only": ("p_data_only", K.p_data_only.notna().to_numpy()),
            "incumbent nba-sim-0.1.0 prop_walk_forward_v3.p_sim": ("p_sim", K.p_sim.notna().to_numpy()),
            "market:kalshi_mid_T-60": ("mid", K.mid.notna().to_numpy()),
            "market:kalshi_mid_T-60 (spread<=0.10)": ("mid", (K.mid.notna() & (K.spread <= 0.10 + 1e-9)).to_numpy())}
    headline_refs = {"A0 no-report proxy", "incumbent nba-sim-0.1.0 market_table_scored.p_data_only", "market:kalshi_mid_T-60"}
    kal_summary = {}; calib = {}; reliab = {}
    for s in STATS + ["all"]:
        fm = (K.stat == s).to_numpy() if s != "all" else np.ones(len(K), bool)
        fam = FAMILY[s] if s != "all" else "player_props_all_four_families"
        arch = [ARCH[s]] if s != "all" else ALL_PROP_ARCH
        kal_summary[fam] = {}
        for rname, (col, avail) in refs.items():
            m = fm & avail
            rp = np.clip(K[col].to_numpy(float), 1e-4, 1 - 1e-4)
            mm = {c: (v & m)[m] for c, v in kmasks.items()}
            for metric, fn in (("kalshi_brier", C.brier_rows), ("kalshi_logloss", C.logloss_rows)):
                R.add(fam, arch, metric, "A2", rname, fn(K.p_A2.to_numpy()[m], ky[m]), fn(rp[m], ky[m]), kg[m], mm,
                      headline=(metric == "kalshi_brier" and s != "all" and rname in headline_refs))
            if rname == "A0 no-report proxy":
                R.add(fam, arch, "kalshi_brier", "A1", rname, C.brier_rows(K.p_A1.to_numpy()[m], ky[m]), C.brier_rows(rp[m], ky[m]), kg[m], mm)
            te = m & kmasks[POOLED]
            if te.sum() >= 30:
                a_, b_ = C.calibration_slope(rp[te], ky[te]); a2_, b2_ = C.calibration_slope(K.p_A2.to_numpy()[te], ky[te])
                kal_summary[fam][rname] = dict(n=int(te.sum()), n_games=int(len(set(kg[te]))), coverage_of_scored_markets=float(te.sum() / max(1, (fm & kmasks[POOLED]).sum())),
                                               brier_reference=float(C.brier_rows(rp[te], ky[te]).mean()), brier_a2=float(C.brier_rows(K.p_A2.to_numpy()[te], ky[te]).mean()),
                                               logloss_reference=float(C.logloss_rows(rp[te], ky[te]).mean()), logloss_a2=float(C.logloss_rows(K.p_A2.to_numpy()[te], ky[te]).mean()),
                                               calibration_reference=dict(intercept=a_, slope=b_), calibration_a2_same_rows=dict(intercept=a2_, slope=b2_),
                                               base_rate=float(ky[te].mean()), mean_p_reference=float(rp[te].mean()), mean_p_a2=float(K.p_A2.to_numpy()[te].mean()))
        te = fm & kmasks[POOLED]
        calib[fam] = {}
        for a in ("A0", "A1", "A2"):
            a_, b_ = C.calibration_slope(K[f"p_{a}"].to_numpy()[te], ky[te]); calib[fam][a] = dict(intercept=a_, slope=b_, n=int(te.sum()))
        for nm, col in (("incumbent_market_table_scored", "p_data_only"), ("incumbent_prop_walk_forward_v3", "p_sim"), ("market_mid_T-60", "mid")):
            mm_ = te & K[col].notna().to_numpy()
            if mm_.sum() >= 30:
                a_, b_ = C.calibration_slope(np.clip(K[col].to_numpy(float)[mm_], 1e-4, 1 - 1e-4), ky[mm_]); calib[fam][nm] = dict(intercept=a_, slope=b_, n=int(mm_.sum()))
        reliab[fam] = {"A2": _reliability(K.p_A2.to_numpy()[te], ky[te]), "A0": _reliability(K.p_A0.to_numpy()[te], ky[te])}
        mm_ = te & K.mid.notna().to_numpy()
        if mm_.sum() >= 30:
            reliab[fam]["market_mid_T-60"] = _reliability(K.mid.to_numpy(float)[mm_], ky[mm_])
        mm_ = te & K.p_data_only.notna().to_numpy()
        if mm_.sum() >= 30:
            reliab[fam]["incumbent_market_table_scored"] = _reliability(K.p_data_only.to_numpy(float)[mm_], ky[mm_])
    tek = kmasks[POOLED]
    quote_cov = dict(scored_test_markets=int(tek.sum()), with_any_candle_in_6h_before_T60=int((tek & K.candle_end.notna().to_numpy()).sum()),
                     two_sided=int((tek & K.mid.notna().to_numpy()).sum()), two_sided_share=float((tek & K.mid.notna().to_numpy()).sum() / max(1, tek.sum())),
                     two_sided_spread_le_10c=int((tek & (K.spread <= 0.10 + 1e-9).to_numpy()).sum()),
                     median_spread_two_sided=float(K.spread[tek & K.mid.notna().to_numpy()].median()),
                     incumbent_market_table_scored=int((tek & K.p_data_only.notna().to_numpy()).sum()),
                     incumbent_prop_walk_forward_v3=int((tek & K.p_sim.notna().to_numpy()).sum()),
                     candle_file_lines_read=int(q.attrs.get("n_lines", 0)),
                     definition="last hourly candle with end_period_ts in (tip-60m-6h, tip-60m]; two-sided = yes_bid>=0.01, yes_ask<=0.99, ask>bid; mid=(bid+ask)/2")
    checks_mkt.append(_chk("market_quote_time_le_tip_minus_60", bool((K.candle_end.dropna() <= (K.tip_ts[K.candle_end.notna()] - 3600)).all()),
                           f"{int(K.candle_end.notna().sum())} selected candles all end at or before tip-60min; two-sided coverage of scored TEST markets "
                           f"{quote_cov['two_sided_share']:.4f} (candles were archived for a sample of events only)"))

    rows = R.finalize()
    say(f"results rows {len(rows)}; headline {sum(r['headline'] for r in rows)}")

    # ------------------------------------------------------------------ ablations
    A0n, A1n = "A0 no-report proxy", "A1 (A0 + PIT injury gate)"

    def abl(step, feature, inputs, picks):
        out = []
        for fam, metric, arm, ref in picks:
            r = R.find(fam, metric, arm, ref)
            if r:
                out.append(dict(step=step, feature=feature, catalog_inputs=inputs, market_family=fam, metric=metric, cohort=r["cohort"], n_rows=r["n_rows"],
                                n_clusters=r["n_clusters"], delta=r["diff"], ci95=r["ci95"], p_raw=r["p_raw"], p_holm=r["p_holm"], replicated=r["replicated"], verdict=r["verdict"]))
        return out
    ablations = abl("A0->A1", "nba injury PIT gate (T-60 official status -> P(play), status minutes multiplier)", ["NBA:nba.injuries_pit", "NBA:nba.status_resolution_prob"],
                    [("player_availability", "brier_p_play", "A1", A0n), ("player_minutes", "abs_err_expected_minutes_unconditional", "A1", A0n)])
    ablations += abl("A1->A2", "team-level minutes redistribution to 240 expected minutes" + (" + points usage bump" if beta > 0 else ""),
                     ["NBA:nba.teammate_absence_shift", "NBA:nba.replacement_level_minutes_absorption"],
                     [("player_minutes", "abs_err_expected_minutes_unconditional", "A2", A1n),
                      ("player_minutes", "abs_err_minutes_given_played_teammates_of_T60_out_or_doubtful_20min_player", "A2", A1n)]
                     + [(FAMILY[s], "crps_given_played", "A2", A1n) for s in STATS])
    v_gate = [a["verdict"] for a in ablations if a["step"] == "A0->A1"]
    v_red = [a["verdict"] for a in ablations if a["step"] == "A1->A2"]
    v_red_min = [a["verdict"] for a in ablations if a["step"] == "A1->A2" and a["market_family"] == "player_minutes"]

    def stage_of(vs):
        if vs and all(v == "VALIDATED_IMPROVEMENT" for v in vs):
            return "VALIDATED_IMPROVEMENT", "OK"
        if any(v == "NOT_IMPROVED" for v in vs):
            return "EVALUATED", "REJECTED" if all(v in ("NOT_IMPROVED", "INCONCLUSIVE") for v in vs) else "PARTIAL"
        return "EVALUATED", "PARTIAL"
    sg, og = stage_of(v_gate); sr_, or_ = stage_of(v_red)
    ev_gate = "ablation A0->A1 (TEST pooled, Holm, both cohorts): " + "; ".join(f"{a['metric']} delta {a['delta']:.4f} CI [{a['ci95'][0]:.4f}, {a['ci95'][1]:.4f}] {a['verdict']}" for a in ablations if a["step"] == "A0->A1")
    ev_red = "ablation A1->A2 (TEST pooled, Holm, both cohorts): " + "; ".join(f"{a['market_family']}/{a['metric']} delta {a['delta']:.4f} CI [{a['ci95'][0]:.4f}, {a['ci95'][1]:.4f}] {a['verdict']}" for a in ablations if a["step"] == "A1->A2")
    claims = [
        dict(input="NBA:nba.injuries_pit", stage=sg, outcome=og, evidence=ev_gate),
        dict(input="NBA:nba.status_resolution_prob", stage=sg, outcome=og, evidence="P(play | T-60 status, recent share) fitted on TRAIN; same ablation as nba.injuries_pit. " + ev_gate),
        dict(input="NBA:nba.teammate_absence_shift", stage=sr_, outcome=or_, evidence=ev_red),
        dict(input="NBA:nba.replacement_level_minutes_absorption", stage=sr_, outcome=or_, evidence="allocation weights minutes**gamma (gamma fitted on TRAIN), cap 48. " + ev_red),
        dict(input="NBA:nba.minutes", stage="CHALLENGER_INTEGRATED", outcome="OK", evidence=f"EWM of prior minutes (halflife {hl_min} games, TRAIN-fitted) is the conditional-minutes base of all three arms; not ablated on its own"),
        dict(input="NBA:nba.rotation", stage="CHALLENGER_INTEGRATED", outcome="OK", evidence="rotation population and recent-share P(play) proxy (arm A0) built from the team's last 10 games; it is the reference arm, not ablated on its own"),
        dict(input="NBA:nba.minutes_scenario_mixture", stage="CHALLENGER_INTEGRATED", outcome="OK", evidence=f"{N_SCEN}-scenario minutes mixture from TRAIN residual quantiles per predicted-minutes bucket; integrated in all arms, not ablated on its own"),
        dict(input="NBA:nba.stat_dist", stage="CHALLENGER_INTEGRATED", outcome="OK", evidence="hurdle + negative-binomial mixture pmfs for pts/reb/ast/fg3m with TRAIN-fitted dispersion; integrated in all arms, scored by CRPS and on Kalshi ladders, not ablated on its own"),
        dict(input="NBA:nba.usage", stage="FEATURE_BUILT" if beta == 0 else "CHALLENGER_INTEGRATED", outcome="REJECTED" if beta == 0 else "PARTIAL",
             evidence=f"vacated-usage points bump exp(beta*vacated usage share): TRAIN Poisson deviance by beta {json.dumps(beta_grid)}; selected beta={beta}"
                      + ("; TRAIN did not support a bump, so it is not part of A2" if beta == 0 else "; part of A2 points, not ablated separately from redistribution")),
    ]

    # ------------------------------------------------------------------ overall verdict
    inc = [r for r in rows if r["headline"] and r["reference"].startswith("incumbent")]
    mkt = [r for r in rows if r["headline"] and r["reference"] == "market:kalshi_mid_T-60"]
    vs = [r["verdict"] for r in inc]
    vm = [r["verdict"] for r in mkt]
    a0k = [r for r in rows if r["headline"] and r["metric"] == "kalshi_brier" and r["reference"] == "A0 no-report proxy"]
    v3k = [r for r in rows if r["cohort"] == POOLED and r["metric"] == "kalshi_brier" and "prop_walk_forward_v3" in r["reference"] and r["market_family"] in FAMILY.values()]
    inc_better = bool(vs) and all(v in ("VALIDATED_IMPROVEMENT", "IMPROVED_NOT_VALIDATED") for v in vs)
    # pre-specified conservative rule: VALIDATED overall needs every incumbent row validated AND no family worse than the market
    if inc_better and all(v == "VALIDATED_IMPROVEMENT" for v in vs) and not any(v == "NOT_IMPROVED" for v in vm) and all(v == "VALIDATED_IMPROVEMENT" for v in vm):
        overall = "VALIDATED_IMPROVEMENT"
    elif inc_better:
        overall = "IMPROVED_NOT_VALIDATED"
    elif vs and all(v == "NOT_IMPROVED" for v in vs):
        overall = "NOT_IMPROVED"
    else:
        overall = "INCONCLUSIVE"
    fmt = lambda rs: "; ".join(f"{r['market_family']} {r['diff']:+.4f} [{r['ci95'][0]:+.4f}, {r['ci95'][1]:+.4f}] n={r['n_rows']} {r['verdict']}" for r in rs)
    reason = ("Overall rule (fixed in code): VALIDATED_IMPROVEMENT only if A2 is validated against the incumbent reproduction AND against the Kalshi T-60 mid in every prop family; "
              "better than the incumbent reproduction but not than the market reads IMPROVED_NOT_VALIDATED. Kalshi Brier, pooled TEST, A2 minus reference (negative = A2 better). "
              "Versus incumbent reproduction market_table_scored.p_data_only (both cohorts, about 100 games): " + fmt(inc)
              + ". Versus the later incumbent reproduction prop_walk_forward_v3.p_sim (12 dates in cohort 2 only, non-headline): " + fmt(v3k)
              + ". Versus the Kalshi T-60 candle mid: " + fmt(mkt)
              + ". Versus the own no-report proxy A0 on the same ladders: " + fmt(a0k)
              + ". On Kalshi ladders (which settle yes/no only for players who entered the game) the availability features add nothing measurable over A0, so the gain over the "
                "incumbent reproduction comes from the base rate/minutes/dispersion model and its later information cutoff, not from the injury gate. "
                "Where the features do work is on the full rotation population: PIT injury gate ablation verdicts " + ", ".join(v_gate)
              + "; redistribution ablation verdicts " + ", ".join(v_red)
              + ". The incumbent is retained: research-only evidence against reproduced references, not the live frozen forecasts, and no edge over the market mid is shown.")

    # ------------------------------------------------------------------ data manifest
    def ds(dataset_id, rel, rows_, first, last, kind):
        p = repo / rel
        return dict(dataset_id=dataset_id, repo=NBA_REPO, path=rel, rows=int(rows_), first=first, last=last, sha256=C.sha256_file(p),
                    kind=kind, rights_tier="UNRESOLVED_INTERNAL_ONLY")
    data = []
    for s in HIST_SEASONS:
        d = pg_raw[pg_raw.season == s]; t_ = tg_raw[tg_raw.season == s]
        data.append(ds(f"espn_player_games_{s}", f"data/history/espn/player_games_{s}.parquet", len(d), d.game_date_et.min(), d.game_date_et.max(), "HISTORICAL_BACKFILL"))
        data.append(ds(f"espn_team_games_{s}", f"data/history/espn/team_games_{s}.parquet", len(t_), t_.game_date_et.min(), t_.game_date_et.max(), "HISTORICAL_BACKFILL"))
    data.append(ds("nba_injury_report_rows_2025-26", f"data/history/injury_reports/report_rows_{SEASON}.parquet", len(rr), rr.report_time_utc.min(), rr.report_time_utc.max(), "HISTORICAL_BACKFILL"))
    data.append(ds("nba_injury_reports_2025-26", f"data/history/injury_reports/reports_{SEASON}.parquet", len(reports), reports.report_time_utc.min(), reports.report_time_utc.max(), "HISTORICAL_BACKFILL"))
    data.append(ds("nba_injury_game_snapshots_2025-26", f"data/history/injury_reports/game_snapshots_{SEASON}.parquet", len(snaps), snaps.game_date_et.min(), snaps.game_date_et.max(), "HISTORICAL_BACKFILL"))
    for sr in SERIES:
        d = mk[mk.series == sr]
        data.append(ds(f"kalshi_markets_{sr}", f"data/history/kalshi/markets_{sr}.jsonl.gz", len(d), d.close_time.min(), d.close_time.max(), "HISTORICAL_BACKFILL"))
        data.append(ds(f"kalshi_candles_{sr}", f"data/history/kalshi/candles_{sr}.jsonl.gz", _count_lines(repo / f"data/history/kalshi/candles_{sr}.jsonl.gz"), None, None, "HISTORICAL_BACKFILL"))
    mall = pd.read_parquet(repo / "data" / "research" / "market_table_scored.parquet", columns=["game_date_et"])
    data.append(ds("incumbent_market_table_scored", "data/research/market_table_scored.parquet", len(mall), mall.game_date_et.min(), mall.game_date_et.max(), "WALK_FORWARD_REPRODUCTION"))
    for f in ("prop_walk_forward", "prop_walk_forward_v2", "prop_walk_forward_v3"):
        d = pd.read_csv(repo / "docs" / "research" / f"{f}.csv", usecols=["date"])
        data.append(ds(f"incumbent_{f}", f"docs/research/{f}.csv", len(d), d.date.min(), d.date.max(), "WALK_FORWARD_REPRODUCTION"))

    features = [
        dict(feature_id="nba_rotation_share_and_minutes_ewm", catalog_inputs=["NBA:nba.rotation", "NBA:nba.minutes"],
             description="Rotation population (appeared in >=1 of the team's last 10 games, latest box row with this team), recency-weighted shrunk share of those games played (A0 P(play)) and EWM of prior minutes when playing.",
             pit_rule="Only box-score rows with game_date_et strictly earlier than the target game date (as-of merge without exact matches); the target game's started/played/minutes are outcomes only.",
             checks=checks_box + [checks_min[0], checks_min[2]]),
        dict(feature_id="nba_injury_status_t60", catalog_inputs=["NBA:nba.injuries_pit", "NBA:nba.status_resolution_prob"],
             description="Player's own official injury-report status in the latest report carrying the game with report_time_utc <= tip-60min; mapped to P(play | status, recent share) and a status minutes multiplier, both fitted on TRAIN (2025-26 games before 2026-01-15).",
             pit_rule="Report rows are used only when both report_time_utc and the file last-modified (publication) time are <= start_time_utc - 60 minutes and the report is not older than 30 hours; later reports are never read for that game. Parameters fitted on TRAIN only.",
             checks=checks_inj),
        dict(feature_id="nba_minutes_redistribution_240", catalog_inputs=["NBA:nba.teammate_absence_shift", "NBA:nba.replacement_level_minutes_absorption", "NBA:nba.usage"],
             description="Conditional minutes m' = clip(m + c*m**gamma, 0, 48) with c solved per team-game so that sum(P(play)*m') equals the team budget; gamma, the overtime allowance and the out-of-population allowance are fitted on TRAIN. Optional points bump from vacated usage share.",
             pit_rule="Uses only A1 probabilities (T-60 statuses) and pre-game minutes/usage EWMs of the team's rotation players; no information from the target game.",
             checks=[checks_min[1]]),
        dict(feature_id="nba_stat_hurdle_nb_mixture", catalog_inputs=["NBA:nba.stat_dist", "NBA:nba.minutes_scenario_mixture"],
             description="Per-stat pmf: mass 1-P(play) at zero plus P(play) x mixture over 9 minutes scenarios of negative binomials with mean = shrunk decayed per-minute rate x minutes x TRAIN calibration multiplier; dispersion fitted on TRAIN.",
             pit_rule="Rates use decayed sums over the player's strictly-earlier played games (2023-24 onward); league prior from the 2024-25 regular season; prior strength, calibration multiplier, scenario residual quantiles and dispersion fitted on TRAIN only.",
             checks=checks_dist),
        dict(feature_id="kalshi_prop_ladder_mapping", catalog_inputs=["NBA:m.settlement_truth", "NBA:m.quote_history", "NBA:m.ladder_structure"],
             description="Settled KXNBAPTS/REB/AST/3PT markets mapped to (game, player, integer strike) by ticker date+tricodes and the market's player name against that game's box-score names; T-60 mid from hourly candles.",
             pit_rule="Market quotes: last candle ending at or before tip-60min (within 6h). Settlement results are outcomes only. P(yes) is the model's P(stat >= strike | plays) because a DNP settles 'scalar', which is excluded from scoring and counted.",
             checks=checks_mkt),
    ]
    cat = json.loads((C.ROOT / "research" / "input_research" / "catalog" / "NBA.json").read_text())["inputs"]
    for f in features:
        f["catalog_inputs"] = [c for c in f["catalog_inputs"] if c.split(":", 1)[1] in cat]
    claims = [c for c in claims if c["input"].split(":", 1)[1] in cat]

    cohort_n = {k: dict(player_games=int(v.sum()), games=int(len(set(gid[v]))), played=int((v & played).sum())) for k, v in masks.items()}
    cohort_n["train_2025-26_before_2026-01-15"] = dict(player_games=int(train.sum()), games=int(len(set(gid[train]))), played=int(trp.sum()))
    part_summary = {a: dict(brier=float(C.brier_rows(arms_p[a], y_play)[test].mean()), logloss=float(C.logloss_rows(arms_p[a], y_play)[test].mean()),
                            mean_p=float(arms_p[a][test].mean()), play_rate=float(y_play[test].mean())) for a in ("A0", "A1")}
    min_summary = {a: dict(mae_unconditional=float(np.abs(em[a] - y_min)[test].mean()), rmse_unconditional=float(np.sqrt(((em[a] - y_min) ** 2)[test].mean())),
                           bias_unconditional=float((em[a] - y_min)[test].mean()), mae_given_played=float(np.abs(arms_min[a] - y_min)[tep].mean()),
                           mae_given_played_teammates_of_T60_out=float(np.abs(arms_min[a] - y_min)[tep & out_big].mean()), n_teammate_rows=int((tep & out_big).sum()),
                           ghost_count_ge10_expected_min_but_absent=int(ghost[a][test].sum()), absent_rows=int((test & ~played).sum()),
                           mean_expected_team_minutes=float(np.mean([np.sum(em[a][ix]) for ix in groups if test[ix[0]]]))) for a in arms_min}
    fitted = dict(a0=dict(recency_decay_lambda=lam0, shrink_pseudo_games=a0, prior_play_rate_train=prior, window_games=WINDOW),
                  minutes_ewm_halflife_games=hl_min, status_models=status_params,
                  redistribution=dict(gamma=gamma, train_cond_mae_by_gamma=gamma_grid, train_cond_mae_a1_no_redistribution=train_cond_mae_a1, cap_minutes=CAP,
                                      target_expected_population_minutes=target_total, train_overtime_minutes_per_team_game=ot_extra,
                                      train_out_of_population_minutes_per_team_game=r_out),
                  usage_bump_points=dict(beta=beta, train_poisson_deviance_by_beta=beta_grid, vacated_usage_train_mean=float(vac[train].mean())),
                  rate_decay_halflife_games_prespecified=RATE_HL, stats=params_stat,
                  minutes_scenarios=dict(n=N_SCEN, bucket_edges=MIN_BUCKETS, train_residual_quantiles={a: scen_tabs[a].tolist() for a in scen_tabs}))
    design = dict(
        population="every (team-game, player) in 2025-26 regular season / play-in / playoffs where the player appeared (minutes>0) in >=1 of the team's previous 10 games of the season and his latest box row is with that team; players who then did not play are included (outcome minutes 0).",
        arms=dict(A0="no-report proxy: shrunk recency-weighted share of the team's last 10 games played; minutes-if-playing = EWM of prior minutes",
                  A1="A0 + PIT injury gate: logistic P(play | T-60 status, logit of A0 share) per status and status minutes multiplier, TRAIN-fitted",
                  A2="A1 + minutes redistribution to the 240-minute team budget" + (" + points usage bump" if beta > 0 else " (points usage bump rejected on TRAIN, beta=0)")),
        windows=dict(history_for_rates="2023-24, 2024-25 and earlier 2025-26 box scores (preseason excluded)", train="2025-26 games before 2026-01-15 (all tunable parameters)",
                     test_cohort_1="2026-01-15..2026-03-15", test_cohort_2="2026-03-16..end of 2025-26 (regular season, play-in, playoffs)"),
        cohort_sizes=cohort_n, freeze="T-60: injury rows with report_time_utc <= tip-60min; Kalshi candle ending <= tip-60min",
        kalshi_scoring="P(yes) = P(stat >= strike | player plays) from the conditional pmf (all arms and the incumbent price conditional on playing); markets settled 'scalar' (DNP) are excluded from scoring and counted.",
        incumbent_reference="primary: data/research/market_table_scored.parquet column p_data_only (model_version nba-sim-0.1.0; the table has a single horizon label 'final'; the model probability does not depend on the quote horizon; data cutoff 00:00 ET game date, no injury report); secondary: docs/research/prop_walk_forward_v3.csv column p_sim (12 dates 2026-03-31..2026-04-12, cohort 2 only, so never 'replicated'). The table's market columns were NOT used; the market reference is rebuilt from candles.",
        market_reference=quote_cov["definition"],
        statistics="paired cluster bootstrap (cluster = game_id, 2000 resamples, seed 7) of challenger - reference per-row loss; Holm across the headline pooled-TEST rows (flag headline=true); replicated = improvement sign in BOTH test cohorts; verdict = contract.verdict_from.",
        headline_rows=int(sum(r["headline"] for r in rows)),
        fitted_parameters=fitted,
        summaries=dict(participation=part_summary, minutes=min_summary, stats=stat_summary, kalshi=kal_summary, kalshi_calibration_slope=calib,
                       kalshi_mapping=counts_all, kalshi_test_counts=counts_test, kalshi_scalar_dnp_diagnostic=scalar_diag, quote_coverage=quote_cov),
        economics="not attempted (fee-adjusted hypothetical economics were skipped rather than rushed)",
    )
    limitations = [
        "Reference A0 is a re-implemented proxy of the incumbent's documented no-report participation rule, not the live frozen pf-1.3.0 forecasts, which live on data branches and were not read.",
        "The incumbent reference on Kalshi tickers is the owner's walk-forward reproduction of nba-sim-0.1.0 (market_table_scored.p_data_only and prop_walk_forward_v3.p_sim); it has a 00:00 ET data cutoff and no injury report, so part of any challenger gain is information timing, and it uses regular-season history only.",
        "Only one season (2025-26) of injury-report history exists: TRAIN and both TEST cohorts are from the same season, so there is no cross-season replication.",
        "Kalshi candle mids are hourly candle-close quotes, not executable fills; candles were archived for a sample of events only, so the market comparison covers a minority of scored markets and may not be representative.",
        "Kalshi lists props for players the venue expects to play, and yes/no settlement requires the player to enter the game; that population is selected on information the A0 arm does not have, and availability matters there only through minutes, not through the DNP hurdle.",
        "No pregame starting-lineup data and no news feed are used; coach's-decision DNPs of unlisted players are invisible to the injury gate.",
        "Injury-report rows are matched to player ids by the owner's archive (methods include matching against the game's own box-score roster); identity, not status, comes from that step. Unmatched rows cannot be applied.",
        "Players returning from a long absence or newly acquired (not in the team's last 10 games) are outside the population; their minutes are handled only as a TRAIN-mean allowance in the 240-minute budget.",
        "ESPN minutes are rounded to whole minutes per player; team minute sums therefore deviate from 240 by a few minutes.",
        "Per-minute rates have no opponent, pace, rest or matchup adjustment; the conditional pmf treats minutes scenarios and the stat as independent given minutes.",
        "Non-headline rows carry p_holm = 1.0 by construction and therefore read INCONCLUSIVE regardless of their confidence interval.",
        "Fee-adjusted economics were not computed.",
    ]
    doc = dict(schema=C.EVAL_SCHEMA, status="RESEARCH_ONLY", sport="NBA", challenger_id=CHALLENGER_ID, incumbent_id=INCUMBENT_ID,
               source_commits={"nba-edge-finder": NBA_COMMIT}, data=data, features=features, design=design, results=rows, ablations=ablations,
               input_stage_claims=claims, verdict=dict(overall=overall, reason=reason, retain_incumbent=True), limitations=limitations)
    errs = C.validate_evaluation(json.loads(json.dumps(C._clean(doc))))
    if errs:
        raise RuntimeError(f"evaluation violates the contract: {errs}")
    C.write_json(out_dir / "evaluation.json", doc)
    summ = dict(schema="sift-foundation-nba-avail-summary/1", status="RESEARCH_ONLY", challenger_id=CHALLENGER_ID,
                note="aggregates only; no per-player rows",
                play_rate_by_t60_status=status_table,
                p_play_reliability_test={a: _reliability(arms_p[a][test], y_play[test]) for a in ("A0", "A1")},
                kalshi_reliability_bins_test=reliab, kalshi_calibration_slope_test=calib,
                expected_minutes_reliability_test={a: [dict(bucket_lo=lo, bucket_hi=hi, n=int(((em[a] >= lo) & (em[a] < hi) & test).sum()),
                                                            mean_expected=float(em[a][(em[a] >= lo) & (em[a] < hi) & test].mean()) if ((em[a] >= lo) & (em[a] < hi) & test).any() else None,
                                                            mean_actual=float(y_min[(em[a] >= lo) & (em[a] < hi) & test].mean()) if ((em[a] >= lo) & (em[a] < hi) & test).any() else None)
                                                       for lo, hi in ((0, 5), (5, 10), (10, 20), (20, 30), (30, 49))] for a in arms_min},
                kalshi_mapping=counts_all, kalshi_test_counts=counts_test, quote_coverage=quote_cov, cohort_sizes=cohort_n)
    C.write_json(out_dir / "predictions_summary.json", summ)
    say(f"wrote {out_dir / 'evaluation.json'} and predictions_summary.json; overall {overall}")
    return doc


def _count_lines(path) -> int:
    n = 0
    with gzip.open(path, "rb") as f:
        for _ in f:
            n += 1
    return n


def main(argv=None) -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
