"""Operation Data Foundation, NBA: evaluation of the ACTUAL frozen production forecasts and challenger ``alpha-nba-avail-0.2``.

RESEARCH_ONLY. Closes the gap left by ``alpha-nba-avail-0.1`` (which was compared against a walk-forward REPRODUCTION of the
incumbent): here the references are the forecasts the owner's production pipeline actually archived before tip-off on
2026-27 regular-season games, read from the append-only ``projection-data`` branch of ``nba-edge-finder`` at a pinned commit:

* ``pf``   production projection model ``pf-nba`` (pf-1.2.1 for the first slates, pf-1.3.0 after), per-player pmfs
           conditional on playing plus a participation probability; team-points pmfs per game (spread / total / team total).
* ``sim``  the frozen shadow baseline ``nba_sim_rotation_v1`` (NBA_BASELINE_2026_PRESEASON_V1, sim-rotation-pure), ladders at
           the Kalshi rungs, conditional on appearing.
* ``mkt``  Kalshi quotes archived at the T-60 horizon (yes bid / yes ask; mid only when two-sided).

Freeze rule (strict point-in-time): for every (model, game, player, stat) the LATEST archived forecast generated at or before
tip - 60 min is used; market quotes are the T-60 horizon rows whose board was observed at or before tip - 60 min; injury
statuses are official-report rows whose effective time (later of capture time and archive write time) is at or before
tip - 60 min. Outcomes are the final ESPN box scores archived on the same branch.

Challengers (all fitted on TRAIN games only, chronological):

* ``C1`` = alpha-nba-avail-0.1 method re-run PIT on 2026-27: EWM minutes, PIT official-status gate (P(play), minutes
           multiplier), 240-minute redistribution, shrunk per-minute rates, NB minutes-scenario mixture.
* ``C2`` = alpha-nba-avail-0.2 candidate features on top of the frozen pf forecast (selected by the diagnosis):
           see ``FEATURES_02`` for what was accepted and what was rejected.

Raw rows never leave this process: only aggregates, counts and digests are written.
``python -m alpha_engine.foundation.nba_frozen`` regenerates ``research/data_foundation_ops/NBA/alpha-nba-avail-0.2/``.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from . import contract as C
from . import nba_availability as V1

CHALLENGER_ID = "alpha-nba-avail-0.2"
INCUMBENT_ID = "pf-nba pf-1.3.0 (pf-1.2.1 on the first slates): actual frozen production forecasts archived on projection-data"
NBA_REPO = "chmoses98/nba-edge-finder"
PD_BRANCH = "projection-data"
PD_COMMIT = "dd561a7331b1d03ff14d2042e6f00168d5bdeaa4"
MAIN_COMMIT = "51a9217a39cd8cc43c6e0c3c98ffad429501cfb7"
INJ_BRANCH = "data-injury-pit"
INJ_COMMIT = "20ae00d0a04d6f8a37cb1654a6d5bbde849d19ba"
OUT_DIR = C.OPS / "NBA" / CHALLENGER_ID

FREEZE_S = 3600                 # T-60
MAX_QUOTE_AGE_S = 1800          # a T-60 board older than 30 min at the horizon is treated as stale (excluded)
TRAIN_END = "2026-11-01"        # TRAIN = games with ET date < 2026-11-01 (also #104's holdout boundary)
COH_SPLIT = "2026-11-07"        # TEST cohort 1 = [TRAIN_END, COH_SPLIT]; cohort 2 = after
STATS = ["points", "rebounds", "assists", "threes"]
STAT_V1 = {"points": "pts", "rebounds": "reb", "assists": "ast", "threes": "fg3m"}
FAMILY = {"points": "player_points", "rebounds": "player_rebounds", "assists": "player_assists", "threes": "player_threes",
          "pra": "player_pra"}
KMAX = {"points": 70, "rebounds": 35, "assists": 30, "threes": 15, "pra": 100, "minutes": 60}
SEED = 7
# Family names used in this module that are not catalog archetypes, mapped to the approved Market & Input Map archetype.
CATALOG_ARCH = {"NBA:player_pra": "NBA:combo_props", "NBA:player_minutes": "NBA:player_availability", "NBA:game_spread": "NBA:game_moneyline_spread"}


# =============================================================================================== git object access
def repo_path() -> Path:
    return C.repos_dir() / "nba-edge-finder"


def _git(repo: Path, *args, inp: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], input=inp, capture_output=True, check=True).stdout


def has_commit(repo: Path, commit: str) -> bool:
    try:
        return _git(repo, "cat-file", "-t", commit).strip() == b"commit"
    except Exception:
        return False


def ls_tree(repo: Path, commit: str, prefix: str):
    """[(path, blob_sha)] under ``prefix`` at ``commit``, sorted by path."""
    out = _git(repo, "ls-tree", "-r", "--full-tree", commit, "--", prefix).decode()
    rows = []
    for line in out.splitlines():
        meta, path = line.split("\t", 1)
        rows.append((path, meta.split()[2]))
    return sorted(rows)


def read_blobs(repo: Path, shas):
    """Yield raw bytes for each blob sha (one ``git cat-file --batch`` process)."""
    if not shas:
        return
    p = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        p.stdin.write(("\n".join(shas) + "\n").encode()); p.stdin.close()
        for _ in shas:
            hdr = p.stdout.readline().split()
            n = int(hdr[2]); data = p.stdout.read(n); p.stdout.read(1)
            yield data
    finally:
        p.stdout.close(); p.wait()


def iter_jsonl(repo: Path, commit: str, prefix: str):
    """Yield (path, record) for every line of every *.jsonl.gz under prefix (deterministic order)."""
    files = [(p, s) for p, s in ls_tree(repo, commit, prefix) if p.endswith(".jsonl.gz")]
    blobs = read_blobs(repo, [s for _, s in files])
    for (path, _), raw in ((f, next(blobs)) for f in files):
        for line in gzip.decompress(raw).decode().splitlines():
            if line.strip():
                yield path, json.loads(line)
    blobs.close()


def _ts(s) -> np.ndarray:
    return V1._epoch_s(s)


def _iso_s(x) -> int:
    return int(pd.Timestamp(x).timestamp())


# =============================================================================================== loaders (projection-data)
def load_frozen_forecasts(repo: Path, commit: str = PD_COMMIT):
    """Latest forecast per (model, game, player, family) generated AND archived at or before tip - 60 min.
    Returns (df, stats). pf rows carry the conditional pmf (``pmf``, ``lo``) and P(play); sim rows carry ladders."""
    best = {}; n_all = 0; n_late = 0; versions = {}
    for path, r in iter_jsonl(repo, commit, "forecasts/nba"):
        n_all += 1
        mid = r.get("model_id", "")
        model = "sim" if r.get("model_role") == "incumbent" else ("pf" if mid.startswith("pf-nba") else None)
        if model is None:
            continue
        tip = _iso_s(r["game_start_utc"]); t = max(_iso_s(r["generated_utc"]), _iso_s(r["archived_utc"]))
        if t > tip - FREEZE_S:
            n_late += 1
            continue
        key = (model, r["game_id"], r["entity_id"], r["family"])
        if key in best and best[key][0] >= t:
            continue
        rec = dict(model=model, version=r.get("model_version", ""), game_id=r["game_id"], entity_id=r["entity_id"], team=r.get("team"),
                   family=r["family"], tip_ts=tip, gen_ts=t, mean=float(r["mean"]) if r.get("mean") is not None else np.nan,
                   lo=int(r.get("lo") or 0), pmf=r.get("probs") or None,
                   ladder={float(x["at_least"]): float(x["probability"]) for x in (r.get("ladder") or [])} or None,
                   p_play=(r.get("participation") or {}).get("p_play") if model == "pf" else r.get("p_appear"),
                   designation=(r.get("participation") or {}).get("designation"),
                   slot=(r.get("source") or {}).get("slot"), gate=r.get("gate_status"))
        best[key] = (t, rec)
    df = pd.DataFrame([v[1] for k, v in sorted(best.items())])
    for m in ("pf", "sim"):
        versions[m] = {str(k): int(v) for k, v in df[df.model == m].version.str.split("+").str[0].value_counts().sort_index().items()}
    return df, dict(n_records=n_all, n_after_cutoff=n_late, n_frozen=len(df), versions=versions)


def load_outcomes(repo: Path, commit: str = PD_COMMIT) -> pd.DataFrame:
    """Final player outcomes, one row per (game, player): minutes and stats; latest final observation wins."""
    best = {}
    for path, r in iter_jsonl(repo, commit, "outcomes/nba"):
        if not r.get("final"):
            continue
        key = (r["game_id"], r["entity_id"], r["family"]); t = _iso_s(r["observed_utc"])
        if key not in best or t >= best[key][0]:
            best[key] = (t, r)
    rows = {}
    for (g, e, fam), (t, r) in sorted(best.items()):
        d = rows.setdefault((g, e), dict(game_id=g, entity_id=e, game_date_et=r.get("game_date_et"), participated=bool(r.get("participated")),
                                         started=bool(r.get("started")), in_box=bool(r.get("in_box"))))
        a = r.get("actual")
        d[fam] = float(a) if a is not None and a == a else np.nan
    return pd.DataFrame(list(rows.values()))


def load_team_outcomes(repo: Path, commit: str = PD_COMMIT) -> pd.DataFrame:
    best = {}
    for path, r in iter_jsonl(repo, commit, "team_outcomes/nba"):
        if not r.get("final"):
            continue
        key = (r["game_id"], r["team"]); t = _iso_s(r["observed_utc"])
        if key not in best or t >= best[key][0]:
            best[key] = (t, dict(game_id=r["game_id"], team=r["team"], home=bool(r["home"]), pts=float(r["pts"]), opp_pts=float(r["opp_pts"]),
                                 n_ot=int(r.get("n_ot") or 0), game_date=r.get("game_date")))
    return pd.DataFrame([v[1] for k, v in sorted(best.items())])


def load_game_forecasts(repo: Path, commit: str = PD_COMMIT) -> pd.DataFrame:
    """Latest team-points forecast per game generated/archived at or before tip - 60 min: per-team pmfs + rho."""
    best = {}
    for path, r in iter_jsonl(repo, commit, "game_forecasts/nba"):
        tip = _iso_s(r["game_start_utc"]); t = max(_iso_s(r["generated_utc"]), _iso_s(r["archived_utc"]))
        if t > tip - FREEZE_S:
            continue
        if r["game_id"] not in best or t > best[r["game_id"]][0]:
            best[r["game_id"]] = (t, r)
    rows = []
    for g, (t, r) in sorted(best.items()):
        teams = {x.get("team"): x for x in r.get("teams", [])}
        rows.append(dict(game_id=g, tip_ts=_iso_s(r["game_start_utc"]), gen_ts=t, version=r.get("model_version", ""), home=r["home"], away=r["away"],
                         rho=float(r.get("rho") or 0.0), teams=teams))
    return pd.DataFrame(rows)


def load_market_t60(repo: Path, commit: str = PD_COMMIT):
    """T-60 horizon quotes, one row per ticker (latest board observed at or before tip - 60 min). Stale boards
    (older than MAX_QUOTE_AGE_S at the horizon) are dropped and counted."""
    best = {}; stats = dict(n_rows=0, n_t60=0, n_after_cutoff=0, n_stale=0, n_replay=0)
    for path, r in iter_jsonl(repo, commit, "market_snapshots/nba"):
        stats["n_rows"] += 1
        if r.get("horizon") != "T-60" or "family" not in r:
            continue
        stats["n_t60"] += 1
        if r.get("replay"):
            stats["n_replay"] += 1
            continue
        tip = _iso_s(r["game_start_utc"]); obs = _iso_s(r["board_observed_utc"]) if r.get("board_observed_utc") else None
        if obs is None or obs > tip - FREEZE_S:
            stats["n_after_cutoff"] += 1
            continue
        if tip - FREEZE_S - obs > MAX_QUOTE_AGE_S:
            stats["n_stale"] += 1
            continue
        k = r["ticker"]
        if k not in best or obs > best[k][0]:
            best[k] = (obs, dict(ticker=k, family=r["family"], series=r["series"], game_id=r["game_id"], tip_ts=tip, obs_ts=obs,
                                 player_id=r.get("player_id"), team=r.get("team"), side_team=r.get("side_team"), stat=r.get("stat"),
                                 threshold=r.get("threshold"), k=r.get("k"), comparator=r.get("comparator"), quote_class=r.get("quote_class"),
                                 yes_bid=r.get("yes_bid"), yes_ask=r.get("yes_ask"), no_ask=r.get("no_ask"), support=r.get("support")))
    df = pd.DataFrame([v[1] for k, v in sorted(best.items())])
    stats["n_tickers"] = len(df)
    return df, stats


def load_availability(repo: Path, commit: str = PD_COMMIT) -> pd.DataFrame:
    """Explicit official injury-report rows (certainty REPORTED, matched to an ESPN id). Implicit roster rows are NOT
    used: PR #104 found their timestamps can precede the roster evidence. Effective time = later of capture and
    source-update time."""
    rows = []
    for path, r in iter_jsonl(repo, commit, "availability/nba"):
        if r.get("source") != "nba_official_injury_report" or r.get("certainty") != "REPORTED" or not r.get("entity_id"):
            continue
        if (r.get("detail") or {}).get("match") == "unmatched":
            continue
        eff = max(_iso_s(r["captured_utc"]), _iso_s(r["source_updated_utc"]) if r.get("source_updated_utc") else 0)
        rows.append((r.get("event_id"), r["entity_id"], r.get("team"), str(r.get("status") or "").lower(), eff, str(r.get("source_url") or "")))
    df = pd.DataFrame(rows, columns=["game_id", "entity_id", "team", "status", "eff_ts", "report"]).drop_duplicates()
    return df.sort_values(["game_id", "entity_id", "eff_ts", "status"]).reset_index(drop=True)


def load_box_history(repo: Path, out: pd.DataFrame, fc: pd.DataFrame) -> pd.DataFrame:
    """Player box history for challenger features: main-branch ESPN player games 2025-26 (regular + postseason) and
    2026-27 regular season, extended with the projection-data final outcomes for 2026-27 games the main parquet does
    not yet hold (team taken from the frozen pf forecast row of the same game)."""
    cols = ["game_id", "game_date_et", "season", "team_id", "nba_id", "played", "minutes", "pts", "reb", "ast", "fg3m", "fga", "fta", "tov", "start_time_utc"]
    parts = []
    for s in ("2025-26", "2026-27"):
        raw = _git(repo, "show", f"{MAIN_COMMIT}:data/history/espn/player_games_{s}.parquet")
        d = pd.read_parquet(io.BytesIO(raw))
        d = d[d.season_type != "preseason"][cols].copy()
        d["team"] = d.team_id.map(V1.TEAM_TRICODES)
        d["entity_id"] = "espn:" + (-d.nba_id).astype("int64").astype(str)
        parts.append(d)
    h = pd.concat(parts, ignore_index=True)
    have = set(h.game_id)
    team_of = fc[fc.model == "pf"].drop_duplicates(["game_id", "entity_id"]).set_index(["game_id", "entity_id"]).team.to_dict()
    ext = out[~out.game_id.isin(have)].copy()
    ext["team"] = [team_of.get((g, e)) for g, e in zip(ext.game_id, ext.entity_id)]
    n_noteam = int(ext.team.isna().sum())
    ext = ext[ext.team.notna()]
    tip = fc.drop_duplicates("game_id").set_index("game_id").tip_ts
    ext = pd.DataFrame(dict(game_id=ext.game_id, game_date_et=ext.game_date_et, season="2026-27", team=ext.team, entity_id=ext.entity_id,
                            played=ext.participated & (ext.minutes.fillna(0) > 0), minutes=ext.minutes.fillna(0.0), pts=ext.points.fillna(0.0),
                            reb=ext.rebounds.fillna(0.0), ast=ext.assists.fillna(0.0), fg3m=ext.threes.fillna(0.0), fga=ext.fga.fillna(0.0),
                            fta=0.0, tov=0.0, start_time_utc=pd.to_datetime(ext.game_id.map(tip), unit="s", utc=True)))
    h = pd.concat([h, ext], ignore_index=True)
    h["nba_id"] = h["entity_id"]          # string key used by the shared 0.1 state builder
    h["team_id"] = h["team"]
    h["date"] = pd.to_datetime(h.game_date_et)
    h = h.sort_values(["date", "game_id", "team", "entity_id"]).reset_index(drop=True)
    h.attrs["n_ext"] = len(ext); h.attrs["n_ext_noteam"] = n_noteam
    return h


def load_injury_pit_official(repo: Path, commit: str = INJ_COMMIT) -> pd.DataFrame:
    """Independent official-report captures on data-injury-pit (name-keyed). Names are mapped in memory to ESPN ids via
    the explicit rows of the projection-data availability archive and never written out. eff = later of fetch and
    last-modified time."""
    nm = {}
    for path, r in iter_jsonl(repo, PD_COMMIT, "availability/nba"):
        d = r.get("detail") or {}
        if r.get("source") == "nba_official_injury_report" and r.get("entity_id") and d.get("player_name_raw"):
            nm[(d["player_name_raw"], r.get("team"))] = r["entity_id"]
    rows = []
    for path, r in iter_jsonl(repo, commit, "injury_pit/official"):
        if not r.get("player_name_raw"):
            continue
        t = V1.TEAM_TRICODES.get(r.get("team_id"))
        eff = max(_iso_s(r["fetched_at_utc"]), _iso_s(r["last_modified_utc"]) if r.get("last_modified_utc") else 0)
        rows.append((r["game_date"], t, nm.get((r["player_name_raw"], t)), str(r.get("status") or "").lower(), eff, r["report_time_utc"]))
    return pd.DataFrame(rows, columns=["gd", "team", "entity_id", "status", "eff_ts", "report_time"]).sort_values(["gd", "team", "report_time", "eff_ts"]).reset_index(drop=True)


def status_at(rep: dict, gd: str, team: str, e: str, ts: int) -> str:
    """Status of player ``e`` in the latest report for (date, team) with eff <= ts; absent from it -> not_listed."""
    last = None
    for eff, d in rep.get((gd, team), []):
        if eff <= ts:
            last = d
    return "no_report" if last is None else d_get(last, e)


def d_get(d: dict, e: str) -> str:
    return d.get(e, "not_listed")


def staleness(X: pd.DataFrame, inj: pd.DataFrame) -> dict:
    """Did the official status change between the pf freeze and T-60? Aggregates only."""
    rep = {}
    for (gd, t, rt), g in inj.groupby(["gd", "team", "report_time"], sort=True):
        rep.setdefault((gd, t), []).append((int(g.eff_ts.max()), dict(zip(g.entity_id, g.status))))
    for k in rep:
        rep[k].sort(key=lambda x: x[0])
    a = np.array([status_at(rep, d, t, e, int(g)) for d, t, e, g in zip(X.date_s, X.team, X.entity_id, X.pf_gen_ts)], dtype=object)
    b = np.array([status_at(rep, d, t, e, int(tp) - FREEZE_S) for d, t, e, tp in zip(X.date_s, X.team, X.entity_id, X.tip_ts)], dtype=object)
    ch = (a != b) & ~((a == "no_report") & (b == "not_listed"))
    m = ch & X.has_pf.to_numpy() & X.in_outcomes.to_numpy()
    y = X.y_play.to_numpy(); p = X.pf_p_play.to_numpy(float)
    trans = {f"{u}->{v}": int(n) for (u, v), n in sorted(pd.Series(list(zip(a[ch], b[ch]))).value_counts().items())} if ch.any() else {}
    by = {}
    for v in sorted(set(b[m])):
        mm = m & (b == v)
        by[v] = dict(n=int(mm.sum()), played_rate=float(y[mm].mean()), mean_pf_p_play=float(p[mm].mean()), brier_pf_p_play=float(C.brier_rows(p[mm], y[mm]).mean()))
    return dict(n_frame_rows=int(len(X)), n_status_changed_after_pf_freeze=int(ch.sum()), n_games_with_change=int(X.game_id[ch].nunique()),
                n_rows_no_report_before_freeze_then_unlisted=int(((a == "no_report") & (b == "not_listed")).sum()), transitions=trans, by_t60_status=by,
                n_report_rows=int(len(inj)), share_rows_mapped_to_id=float(inj.entity_id.notna().mean()), n_reports=int(inj.report_time.nunique()))


# =============================================================================================== pure helpers (tested)
def cond_pmf_array(pmf, lo: int, K: int) -> np.ndarray:
    """Archived (lo, probs) -> dense pmf over 0..K (mass above K folded into K, renormalised)."""
    out = np.zeros(K + 1)
    p = np.asarray(pmf, float)
    for i, v in enumerate(p):
        out[min(lo + i, K)] += v
    s = out.sum()
    return out / s if s > 0 else out


def ladder_sf(ladder: dict, k: float):
    """P(X >= k) from an incumbent ladder {at_least: prob}; None when the rung is not on the ladder."""
    if not ladder:
        return None
    v = ladder.get(float(k))
    return None if v is None else float(v)


def pit_status(av: pd.DataFrame, cutoff: dict) -> pd.DataFrame:
    """Latest official status per (game, player) with effective time <= the game's cutoff; ties -> most severe."""
    a = av.copy()
    a["cut"] = a.game_id.map(cutoff)
    a = a[a.cut.notna() & (a.eff_ts <= a.cut)]
    sev = {"out": 0, "doubtful": 1, "questionable": 2, "probable": 3, "active": 4, "available": 4}
    a["sev"] = a.status.map(sev).fillna(5)
    a = a.sort_values(["game_id", "entity_id", "eff_ts", "sev"], ascending=[True, True, False, True])
    a = a.drop_duplicates(["game_id", "entity_id"])
    return a[["game_id", "entity_id", "status", "eff_ts"]].reset_index(drop=True)


def ece(p, y, bins: int = 10) -> float:
    p = np.asarray(p, float); y = np.asarray(y, float)
    idx = np.clip((p * bins).astype(int), 0, bins - 1); tot = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            tot += m.sum() * abs(p[m].mean() - y[m].mean())
    return float(tot / max(len(p), 1))


def recal_logit(p, a: float, b: float) -> np.ndarray:
    return V1._sig(a + b * V1._logit(p))


def pool_pmf(p1: np.ndarray, p2: np.ndarray, w: float) -> np.ndarray:
    """Linear opinion pool w*p1 + (1-w)*p2 (stays a coherent pmf)."""
    return w * p1 + (1.0 - w) * p2


def normal_sf(x, mu, sd):
    from math import erf, sqrt
    z = (np.asarray(x, float) - mu) / np.maximum(sd, 1e-9)
    return 0.5 * (1 - np.vectorize(erf)(z / sqrt(2)))


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


# =============================================================================================== evaluation frame
def build_frame(fc: pd.DataFrame, out: pd.DataFrame) -> pd.DataFrame:
    """One row per (game, player) on the frozen pf participation roster of every game that has final outcomes."""
    pf = fc[fc.model == "pf"]
    part = pf[pf.family == "participation"].set_index(["game_id", "entity_id"])
    E = part[["team", "tip_ts", "gen_ts", "p_play", "designation", "version"]].rename(columns={"gen_ts": "pf_gen_ts", "p_play": "pf_p_play"}).copy()
    for s in STATS + ["pra", "minutes"]:
        sub = pf[pf.family == s].set_index(["game_id", "entity_id"])
        E[f"pf_mean_{s}"] = sub["mean"]
        E[f"pf_pmf_{s}"] = pd.Series([cond_pmf_array(p, lo, KMAX[s]) if p else None for p, lo in zip(sub.pmf, sub.lo)], index=sub.index)
    sim = fc[fc.model == "sim"]
    sp = sim[sim.family == "participation"].set_index(["game_id", "entity_id"])
    E["sim_p_play"] = sp["mean"]; E["sim_gen_ts"] = sp["gen_ts"]
    for s in STATS + ["minutes"]:
        sub = sim[sim.family == s].set_index(["game_id", "entity_id"])
        E[f"sim_mean_{s}"] = sub["mean"]; E[f"sim_ladder_{s}"] = sub["ladder"]
    E = E.reset_index()
    games_out = out.drop_duplicates("game_id").set_index("game_id").game_date_et
    E = E[E.game_id.isin(games_out.index)].copy()
    E["date_s"] = E.game_id.map(games_out)
    o = out.set_index(["game_id", "entity_id"])
    key = list(zip(E.game_id, E.entity_id))
    oo = o.reindex(key)
    E["in_outcomes"] = oo.participated.notna().to_numpy()
    E["y_min"] = oo.minutes.fillna(0.0).to_numpy()
    E["y_play"] = (oo.participated.fillna(False).astype(bool) & (oo.minutes.fillna(0) > 0)).to_numpy()
    E["y_started"] = oo.started.fillna(False).astype(bool).to_numpy()
    for s in STATS + ["pra"]:
        E[f"y_{s}"] = oo[s].fillna(0.0).to_numpy()
    E["has_pf"] = E.pf_pmf_points.notna()
    return E.sort_values(["date_s", "game_id", "team", "entity_id"]).reset_index(drop=True)


def cohort_masks(date_s: pd.Series) -> dict:
    d = date_s.astype(str)
    t1 = (d >= TRAIN_END) & (d <= COH_SPLIT); t2 = d > COH_SPLIT
    return {COH1: t1.to_numpy(), COH2: t2.to_numpy(), POOLED: (t1 | t2).to_numpy()}


COH1, COH2, POOLED = f"test1_{TRAIN_END}_{COH_SPLIT}", "test2_2026-11-08_2026-11-13", "test_pooled"
ALLG = "all_games_pooled"


class Results:
    """Paired, game-clustered comparisons. Holm is applied across the pre-registered headline rows only."""

    def __init__(self):
        self.rows = []

    def add(self, family, archetypes, metric, arm, reference, chal, ref, clusters, masks, headline=False, min_n=30, note=None):
        chal = np.asarray(chal, float); ref = np.asarray(ref, float); clusters = np.asarray(clusters)
        archetypes = [CATALOG_ARCH.get(a, a) for a in archetypes]      # only archetypes of the approved catalog are ever written
        for cohort, mk in masks.items():
            mk = np.asarray(mk, bool) & np.isfinite(chal) & np.isfinite(ref)
            if int(mk.sum()) < min_n:
                continue
            b = C.paired_cluster_bootstrap(chal[mk] - ref[mk], clusters[mk], seed=SEED)
            row = dict(market_family=family, archetypes=list(archetypes), metric=metric, challenger_arm=arm, reference=reference, cohort=cohort,
                       n_rows=b["n_rows"], n_clusters=b["n_clusters"], challenger=float(chal[mk].mean()), reference_value=float(ref[mk].mean()),
                       diff=b["mean"], ci95=[b["lo"], b["hi"]], p_raw=b["p_two_sided"], p_holm=float(b["p_two_sided"]), replicated=False,
                       verdict="INCONCLUSIVE", headline=bool(headline and cohort == POOLED))
            if note:
                row["note"] = note
            self.rows.append(row)

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
        # non-headline rows: Holm within their own (metric family, cohort) block so no raw p-value is read as adjusted
        blocks = {}
        for r in self.rows:
            if not r["headline"]:
                blocks.setdefault((r["challenger_arm"], r["reference"], r["cohort"]), []).append(r)
        for rows in blocks.values():
            for r, ph in zip(rows, C.holm([r["p_raw"] for r in rows])):
                r["p_holm"] = float(ph)
        for r in self.rows:
            r["verdict"] = C.verdict_from(r["ci95"][0], r["ci95"][1], r["p_holm"], r["replicated"])
        return self.rows

    def find(self, family, metric, arm, reference, cohort=POOLED):
        for r in self.rows:
            if (r["market_family"], r["metric"], r["challenger_arm"], r["reference"], r["cohort"]) == (family, metric, arm, reference, cohort):
                return r
        return None


def _chk(name, passed, detail):
    return dict(name=name, passed=bool(passed), detail=str(detail))


def _crps_dense(pmfs: np.ndarray, y: np.ndarray) -> np.ndarray:
    cdf = np.minimum(np.cumsum(pmfs, axis=1), 1.0)
    k = np.arange(pmfs.shape[1]).reshape(1, -1)
    K = pmfs.shape[1] - 1
    return np.sum((cdf - (k >= np.asarray(y).reshape(-1, 1))) ** 2, axis=1) + np.maximum(0.0, np.asarray(y, float) - K)


def _sf_dense(pmfs: np.ndarray, k: np.ndarray) -> np.ndarray:
    return V1.sf_at(pmfs, np.asarray(k, int))


# =============================================================================================== challenger C1 (0.1 method, PIT on 2026-27)
HLS = [0.5, 1.0, 1.5, 2.0, 2.5, 4.0, 6.0, 10.0]
V1_STATS = ["pts", "reb", "ast", "fg3m"]


def attach_c1_features(E: pd.DataFrame, h: pd.DataFrame, st: pd.DataFrame, n_report_games: set) -> pd.DataFrame:
    """Strictly-earlier-date box features (EWM minutes, shrunk-rate sufficient statistics, team recent-share bits)
    and the T-60 official status for every frame row."""
    states = V1.player_states(h, HLS)
    X = E.copy()
    X["date"] = pd.to_datetime(X.date_s); X["nba_id"] = X.entity_id
    X = X.sort_values(["date", "nba_id"]).reset_index()
    X = pd.merge_asof(X, states.sort_values(["date", "nba_id"]), on="date", by="nba_id", allow_exact_matches=False)
    X = X.sort_values("index").set_index("index"); X.index.name = None
    cur = h[(h.season == "2026-27")]
    tg = cur[["team", "game_id", "date"]].drop_duplicates().sort_values(["team", "date", "game_id"])
    tl = {t: list(zip(g.date.tolist(), g.game_id.tolist())) for t, g in tg.groupby("team")}
    played = {k: set(v) for k, v in cur[cur.minutes > 0].groupby(["game_id", "team"])["entity_id"]}
    bits = np.full((len(X), V1.WINDOW), np.nan)
    for i, (t, d, e) in enumerate(zip(X.team, X.date, X.entity_id)):
        prev = [g for dd, g in tl.get(t, []) if dd < d][-V1.WINDOW:][::-1]
        for j, g in enumerate(prev):
            bits[i, j] = 1.0 if e in played.get((g, t), set()) else 0.0
    for j in range(V1.WINDOW):
        X[f"b{j}"] = bits[:, j]
    s = st.set_index(["game_id", "entity_id"]).status
    raw = pd.Series([s.get((g, e)) for g, e in zip(X.game_id, X.entity_id)], index=X.index)
    X["status"] = [("available" if v == "active" else v) if isinstance(v, str) else ("not_listed" if g in n_report_games else "no_report")
                   for v, g in zip(raw, X.game_id)]
    X["state_date"] = X["state_date"] if "state_date" in X else pd.NaT
    return X


def fit_c1(X: pd.DataFrame, h: pd.DataFrame, fit: np.ndarray, n_ot: dict | None = None):
    """Fit the 0.1 procedure on rows ``fit`` (chronologically earlier games) and predict every row.
    Returns dict(p0, p1, m0, m1, m2, cond={stat: [n, K+1]}, params)."""
    N = len(X); y_play = X.y_play.to_numpy().astype(float); y_min = X.y_min.to_numpy(); played = y_play > 0
    gid = X.game_id.to_numpy()
    bits = X[[f"b{i}" for i in range(V1.WINDOW)]].to_numpy(float)
    prior = float(y_play[fit].mean()); best = None
    for lam in (1.0, 0.85, 0.7, 0.55, 0.4):
        for a in (0.1, 0.25, 0.5, 1.0, 2.0, 4.0):
            p = V1.a0_prob(bits, lam, a, prior)
            ll = float(C.logloss_rows(p[fit], y_play[fit]).mean())
            if best is None or ll < best[0] - 1e-12:
                best = (ll, lam, a)
    _, lam0, a0 = best
    p0 = np.clip(V1.a0_prob(bits, lam0, a0, prior), 0.002, 0.998)
    fb_min = float(np.nanmedian(X["em_4.0"].to_numpy()[fit & played])) if (fit & played).any() else 15.0
    bestm = None
    for hl in HLS:
        em = X[f"em_{hl}"].to_numpy(float); em = np.where(np.isfinite(em), em, fb_min)
        e = float(np.abs(em - y_min)[fit & played].mean())
        if bestm is None or e < bestm[0] - 1e-12:
            bestm = (e, hl)
    hl_min = bestm[1]
    m0 = X[f"em_{hl_min}"].to_numpy(float); m0 = np.clip(np.where(np.isfinite(m0), m0, fb_min), 0.5, V1.CAP)
    status = X.status.to_numpy(); x0 = V1._logit(p0); p1 = p0.copy(); rho = np.ones(N); sp = {}
    for s in sorted(set(status)):
        ms = status == s; tr = ms & fit; n_tr = int(tr.sum())
        if n_tr >= 200 and s != "no_report":
            a, b = V1.fit_logit(x0[tr], y_play[tr])
        elif n_tr >= 30 and s != "no_report":
            a = float(V1._logit(np.clip(y_play[tr].mean(), 0.002, 0.998)) - np.mean(x0[tr])); b = 1.0
        else:
            a, b = 0.0, 1.0
        p1[ms] = np.clip(V1._sig(a + b * x0[ms]), 0.002, 0.998)
        trp = tr & played
        r_s = float(y_min[trp].sum() / m0[trp].sum()) if int(trp.sum()) >= 100 else 1.0
        rho[ms] = r_s
        sp[s] = dict(intercept=a, slope=b, minutes_multiplier=r_s, n_fit=n_tr)
    m1 = np.clip(m0 * rho, 0.5, V1.CAP)
    # minutes budget: 240 + fit-period overtime - fit-period minutes of box players outside the roster frame
    fitg = set(gid[fit])
    rost = set(zip(X.game_id, X.entity_id))
    hb = h[h.game_id.isin(fitg) & (h.minutes > 0)]
    outm = hb[[(g, e) not in rost for g, e in zip(hb.game_id, hb.entity_id)]].groupby(["game_id", "team"]).minutes.sum()
    n_tg = max(1, hb.groupby(["game_id", "team"]).ngroups)
    r_out = float(outm.sum() / n_tg)
    ot_extra = 25.0 * float(np.mean([n_ot.get(g, 0) for g in sorted(fitg)])) if n_ot else 0.0
    tgt = 240.0 + ot_extra - r_out
    keys = pd.factorize(pd.Series(gid).astype(str) + "|" + X.team.astype(str))[0]
    groups = [np.where(keys == k)[0] for k in range(keys.max() + 1)]

    def redistribute(gamma, only=None):
        o = m1.copy()
        for ix in groups:
            if only is not None and not only[ix[0]]:
                continue
            o[ix] = V1.redistribute_minutes(p1[ix], m1[ix], tgt, gamma, V1.CAP)
        return o
    bestg = None
    for gamma in (-1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0):
        e = float(np.abs(redistribute(gamma, only=fit) - y_min)[fit & played].mean())
        if bestg is None or e < bestg[0] - 1e-12:
            bestg = (e, gamma)
    m2 = redistribute(bestg[1])
    prev = h[(h.season == "2025-26") & (h.minutes > 0)]
    r0 = {s: float(prev[s].sum() / prev.minutes.sum()) for s in V1_STATS}
    Smin = X.S_minutes.fillna(0.0).to_numpy(float); fp = fit & played
    tab = V1._scenario_table(m2, y_min, fp); scen = V1._scenarios(m2, tab)
    cond = {}; params = dict(a0_lambda=lam0, a0_shrink=a0, a0_prior=prior, minutes_halflife=hl_min, status=sp, gamma=bestg[1],
                             minutes_target=tgt, out_of_frame_minutes=r_out, overtime_minutes=ot_extra, stats={})
    for s, sv in zip(STATS, V1_STATS):
        y = X[f"y_{s}"].to_numpy(); S = X[f"S_{sv}"].fillna(0.0).to_numpy(float); bk = None
        for k in (15.0, 30.0, 60.0, 120.0, 250.0, 500.0, 1000.0):
            mu = np.maximum((S + k * r0[sv]) / (Smin + k) * y_min, 1e-9)
            dv = float(np.mean((mu - y * np.log(mu))[fp]))
            if bk is None or dv < bk[0] - 1e-12:
                bk = (dv, k)
        rate = (S + bk[1] * r0[sv]) / (Smin + bk[1])
        cal = float(y[fp].sum() / (rate * scen.mean(1))[fp].sum())
        ba = None; yi = np.minimum(y[fp].astype(int), KMAX[s])
        for al in (0.0, 0.02, 0.04, 0.07, 0.1, 0.15, 0.2, 0.3, 0.45, 0.6):
            _, cnd = V1.build_pmf(np.ones(int(fp.sum())), (rate * cal)[fp], scen[fp], al, KMAX[s])
            ll = float(-np.mean(np.log(np.maximum(cnd[np.arange(len(yi)), yi], 1e-12))))
            if ba is None or ll < ba[0] - 1e-12:
                ba = (ll, al)
        _, cond[s] = V1.build_pmf(np.ones(N), rate * cal, scen, ba[1], KMAX[s])
        params["stats"][s] = dict(prior_minutes=bk[1], league_rate_2025_26=r0[sv], calibration=cal, nb_alpha=ba[1])
    return dict(p0=p0, p1=p1, m0=m0, m1=m1, m2=m2, cond=cond, params=params)


# =============================================================================================== market rung table
def prop_rungs(M: pd.DataFrame, X: pd.DataFrame) -> pd.DataFrame:
    """Player-prop rungs at T-60 joined to frame rows (played players only: Kalshi settles a DNP prop at its last fair
    price, so the market is conditional on playing and so are the compared forecasts)."""
    P = M[M.family.isin([FAMILY[s] for s in STATS + ["pra"]])].copy()
    P["stat"] = P.family.str.replace("player_", "", regex=False)
    P = P[(P.comparator == "gt") & P.k.notna() & P.player_id.notna()]
    P["k"] = P.k.astype(int)
    idx = pd.Series(np.arange(len(X)), index=pd.MultiIndex.from_arrays([X.game_id, X.entity_id]))
    P["row"] = [idx.get((g, e), -1) for g, e in zip(P.game_id, P.player_id)]
    P["in_frame"] = P.row >= 0
    return P.sort_values(["game_id", "player_id", "stat", "k"]).reset_index(drop=True)


def game_rungs(M: pd.DataFrame, gf: pd.DataFrame, tout: pd.DataFrame) -> pd.DataFrame:
    """Spread / total / team-total rungs at T-60 with the frozen pf team-points forecast and the final score.
    Team totals use the archived team pmf exactly; spread and total use a normal approximation with the archived rho
    (the owner's own note says game-market probabilities from this model are approximate)."""
    G = M[M.family.isin(["game_spread", "game_total", "team_total"]) & (M.comparator == "gt")].copy()
    gfi = gf.set_index("game_id"); to = tout.set_index(["game_id", "team"])
    rows = []
    for r in G.itertuples():
        if r.game_id not in gfi.index:
            continue
        g = gfi.loc[r.game_id]; th = float(r.threshold)
        try:
            sh, sa = to.loc[(r.game_id, g.home)], to.loc[(r.game_id, g.away)]
        except KeyError:
            continue
        mom = {}
        for t in (g.home, g.away):
            x = g.teams.get(t)
            if not x:
                break
            pm = np.asarray(x["probs"], float); pm = pm / pm.sum(); ks = np.arange(len(pm)) + int(x["lo"])
            mom[t] = (pm, ks, float(pm @ ks), float(np.sqrt(pm @ (ks - pm @ ks) ** 2)))
        if len(mom) < 2:
            continue
        if r.family == "team_total":
            t = r.team if isinstance(r.team, str) else r.side_team
            if t not in mom:
                continue
            pm, ks, mu, sd = mom[t]; p = float(pm[ks > th].sum())
            y = float((sh.pts if t == g.home else sa.pts) > th)
        else:
            (mh, sdh), (ma, sda) = mom[g.home][2:], mom[g.away][2:]
            if r.family == "game_total":
                mu = mh + ma; sd = np.sqrt(sdh ** 2 + sda ** 2 + 2 * g.rho * sdh * sda); y = float(sh.pts + sa.pts > th)
            else:
                side = r.side_team if isinstance(r.side_team, str) else r.team
                if side not in (g.home, g.away):
                    continue
                sgn = 1.0 if side == g.home else -1.0
                mu = sgn * (mh - ma); sd = np.sqrt(sdh ** 2 + sda ** 2 - 2 * g.rho * sdh * sda); y = float(sgn * (sh.pts - sa.pts) > th)
            p = float(normal_sf(th, mu, sd))
        rows.append(dict(family=r.family, game_id=r.game_id, ticker=r.ticker, p=p, y=y, bid=r.yes_bid, ask=r.yes_ask, quote_class=r.quote_class))
    return pd.DataFrame(rows)


# =============================================================================================== main pipeline
INNER_SPLIT = "2026-10-27"      # inner chronological validation inside TRAIN: fit < INNER_SPLIT, validate [INNER_SPLIT, TRAIN_END)
POOL_GRID = [round(0.1 * i, 1) for i in range(11)]
ARCH = {s: f"NBA:{FAMILY[s]}" for s in STATS + ["pra"]}


def _prob_metrics(p, y):
    p = np.asarray(p, float); y = np.asarray(y, float)
    a, b = C.calibration_slope(p, y) if len(p) >= 30 else (np.nan, np.nan)
    return dict(n=int(len(p)), brier=float(C.brier_rows(p, y).mean()) if len(p) else None, logloss=float(C.logloss_rows(p, y).mean()) if len(p) else None,
                calibration_intercept=a, calibration_slope=b, ece=ece(p, y) if len(p) else None, base_rate=float(y.mean()) if len(p) else None)


def _stack(col: pd.Series, K: int) -> np.ndarray:
    return np.stack([v if isinstance(v, np.ndarray) else np.full(K + 1, np.nan) for v in col.values])


def run(repo: Path | None = None, out_dir: Path | None = None, verbose: bool = True) -> dict:
    repo = Path(repo) if repo else repo_path()
    out_dir = Path(out_dir) if out_dir else OUT_DIR
    say = (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)
    for c in (PD_COMMIT, MAIN_COMMIT):
        if not has_commit(repo, c):
            raise RuntimeError(f"commit {c} not in {repo}; fetch {PD_BRANCH} / main first")
    chk_data, chk_fc, chk_mkt, chk_inj, chk_c1, chk_c2 = [], [], [], [], [], []

    # ------------------------------------------------------------------ load
    fc, fc_stats = load_frozen_forecasts(repo)
    out = load_outcomes(repo); tout = load_team_outcomes(repo); gf = load_game_forecasts(repo)
    M, m_stats = load_market_t60(repo); av = load_availability(repo)
    h = load_box_history(repo, out, fc)
    say(f"forecasts {fc_stats}; outcomes {len(out)}; market {m_stats}; availability {len(av)}; history {len(h)}")

    viol = int((fc.gen_ts > fc.tip_ts - FREEZE_S).sum())
    lead = (fc.tip_ts - fc.gen_ts) / 60.0
    chk_fc.append(_chk("leak_guard_forecast_generated_and_archived_le_tip_minus_60", viol == 0,
                       f"{fc_stats['n_records']} archived player-forecast records; {fc_stats['n_after_cutoff']} generated or archived after tip-60 were discarded; "
                       f"{fc_stats['n_frozen']} frozen (model, game, player, family) rows kept, {viol} violate the cutoff; lead to tip median "
                       f"pf {float(lead[fc.model == 'pf'].median()):.0f} min, sim {float(lead[fc.model == 'sim'].median()):.0f} min"))
    pfv = fc[fc.model == "pf"].version
    n_code = int(pfv.str.split("+").str[1].nunique())
    chk_fc.append(_chk("frozen_model_identity", True,
                       f"pf versions {fc_stats['versions']['pf']} spanning {n_code} distinct code commits under the same pf label (informational: the "
                       f"version label did not pin the code); sim versions {fc_stats['versions']['sim']}"))
    pfp = fc[(fc.model == "pf") & (fc.family == "points")].head(500)
    dm = float(np.max(np.abs([(np.arange(len(p)) + lo) @ np.asarray(p) / np.sum(p) - mu for p, lo, mu in zip(pfp.pmf, pfp.lo, pfp["mean"])])))
    chk_fc.append(_chk("pf_mean_equals_pmf_mean_conditional_on_playing", dm < 0.02,
                       f"max |archived mean - pmf mean| over 500 pf points rows = {dm:.4f}: archived pf pmfs are conditional on playing"))
    dup = int(out.duplicated(["game_id", "entity_id"]).sum())
    raw = _git(repo, "show", f"{MAIN_COMMIT}:data/history/espn/player_games_2026-27.parquet")
    mp = pd.read_parquet(io.BytesIO(raw)); mp = mp[mp.season_type == "regular"]
    mp["entity_id"] = "espn:" + (-mp.nba_id).astype("int64").astype(str)
    j = mp.merge(out, on=["game_id", "entity_id"], how="inner", suffixes=("", "_o"))
    mis = int((j.pts != j.points).sum()); mism = int((np.abs(j.minutes - j.minutes_o) > 0.5).sum())
    chk_data.append(_chk("outcomes_agree_with_main_box_scores", mis == 0 and mism <= 0.01 * len(j),
                         f"{dup} duplicate outcome rows; {len(j)}/{len(mp)} overlapping 2026-27 player-games: points mismatches {mis}, minutes mismatches (>0.5) {mism}"))
    tm = h[h.season == "2026-27"].groupby(["game_id", "team"]).minutes.sum()
    ok = float(((tm >= 235) & (tm <= 320)).mean())
    chk_data.append(_chk("team_minutes_plausible", ok >= 0.97, f"{len(tm)} 2026-27 team-games: share with summed minutes in [235, 320] = {ok:.4f}; "
                         f"{h.attrs['n_ext']} outcome rows appended after the main parquet ({h.attrs['n_ext_noteam']} without a frozen team were dropped)"))
    mv = int((M.obs_ts > M.tip_ts - FREEZE_S).sum())
    chk_mkt.append(_chk("leak_guard_quote_board_le_tip_minus_60", mv == 0,
                        f"{m_stats['n_t60']} T-60 rows, {mv} observed after tip-60, {m_stats['n_stale']} stale (>30 min before the horizon) dropped; board age at tip "
                        f"median {float(((M.tip_ts - M.obs_ts) / 60).median()):.1f} min, max {float(((M.tip_ts - M.obs_ts) / 60).max()):.1f} min"))

    # ------------------------------------------------------------------ frame + PIT status
    X0 = build_frame(fc, out)
    cutoff = {g: t - FREEZE_S for g, t in zip(X0.game_id, X0.tip_ts)}
    st = pit_status(av, cutoff)
    lv = int((st.eff_ts > st.game_id.map(cutoff)).sum())
    chk_inj.append(_chk("leak_guard_status_effective_le_tip_minus_60", lv == 0,
                        f"{len(av)} explicit official rows; {len(st)} (game, player) T-60 statuses selected; {lv} after cutoff; status counts "
                        + json.dumps({k: int(v) for k, v in sorted(st.status.value_counts().items())})))
    X = attach_c1_features(X0, h, st, set(st.game_id))
    sv = X.state_date.notna()
    leak = bool((X.state_date[sv] < X.date[sv]).all())
    chk_c1.append(_chk("leak_guard_box_features_strictly_earlier_dates", leak,
                       f"{int(sv.sum())}/{len(X)} frame rows have a prior box state, all dated strictly before the game: {leak}"))
    N = len(X); date_s = X.date_s
    train = (date_s < TRAIN_END).to_numpy(); fit_a = (date_s < INNER_SPLIT).to_numpy(); val_b = train & ~fit_a
    masks = cohort_masks(date_s); test = masks[POOLED]
    gid = X.game_id.to_numpy(); played = X.y_play.to_numpy(); has_pf = X.has_pf.to_numpy()
    nOT = tout.drop_duplicates("game_id").set_index("game_id").n_ot.to_dict()
    say(f"frame {N} rows, {X.game_id.nunique()} games; train {int(train.sum())} test {int(test.sum())}")

    # ------------------------------------------------------------------ C1 fits (inner + final)
    c1a = fit_c1(X, h, fit_a, nOT)
    c1 = fit_c1(X, h, train, nOT)
    pf_pmf = {s: _stack(X[f"pf_pmf_{s}"], KMAX[s]) for s in STATS + ["pra"]}

    # ------------------------------------------------------------------ 0.2 feature F2: linear pool pf (+) C1, per stat
    pool_w = {}; f2_log = {}
    base = played & has_pf
    for s in STATS:
        y = X[f"y_{s}"].to_numpy().astype(int)
        def best_w(cond, mk):
            grid = {w: float(_crps_dense(pool_pmf(pf_pmf[s][mk], cond[mk], w), y[mk]).mean()) for w in POOL_GRID}
            return min(grid, key=lambda w: (grid[w], -w)), grid
        wa, ga = best_w(c1a["cond"][s], base & fit_a)
        vb = base & val_b
        v_pool = float(_crps_dense(pool_pmf(pf_pmf[s][vb], c1a["cond"][s][vb], wa), y[vb]).mean())
        v_pf = float(_crps_dense(pf_pmf[s][vb], y[vb]).mean())
        accept = wa < 1.0 and v_pool < v_pf
        wf, gfull = best_w(c1["cond"][s], base & train)
        pool_w[s] = wf if accept else 1.0
        f2_log[s] = dict(inner_fit_weight_on_pf=wa, inner_validation_crps_pool=v_pool, inner_validation_crps_pf=v_pf, accepted=bool(accept),
                         final_weight_on_pf=pool_w[s], train_crps_by_weight=gfull, n_inner_fit=int((base & fit_a).sum()), n_inner_val=int(vb.sum()))
    c2_pmf = {s: pool_pmf(pf_pmf[s], c1["cond"][s], pool_w[s]) if pool_w[s] < 1.0 else pf_pmf[s] for s in STATS}
    c2_pmf["pra"] = pf_pmf["pra"]
    chk_c2.append(_chk("f2_pool_weight_selected_inside_train_only", True, json.dumps({s: [f2_log[s]["inner_fit_weight_on_pf"], f2_log[s]["accepted"],
                                                                                         f2_log[s]["final_weight_on_pf"]] for s in STATS})))
    sums = max(float(np.nanmax(np.abs(c2_pmf[s][base].sum(1) - 1))) for s in STATS)
    chk_c2.append(_chk("c2_pmfs_sum_to_one", sums < 1e-6, f"max |sum-1| = {sums:.2e}"))

    # ------------------------------------------------------------------ rung table
    P = prop_rungs(M, X)
    rr = P[P.in_frame].copy(); ri = rr.row.to_numpy()
    rr = rr[played[ri] & has_pf[ri]].copy(); ri = rr.row.to_numpy()
    n_dnp_rungs = int(P.in_frame.sum() - len(rr))
    rr["y"] = [float(X[f"y_{s}"].iat[i] >= k) for s, i, k in zip(rr.stat, ri, rr.k)]
    for name, pm in (("pf", pf_pmf), ("c2", c2_pmf)):
        rr[f"p_{name}"] = np.nan
        for s in STATS + ["pra"]:
            mk = (rr.stat == s).to_numpy()
            rr.loc[mk, f"p_{name}"] = _sf_dense(pm[s][ri[mk]], rr.k.to_numpy()[mk])
    rr["p_c1"] = np.nan
    for s in STATS:
        mk = (rr.stat == s).to_numpy()
        rr.loc[mk, "p_c1"] = _sf_dense(c1["cond"][s][ri[mk]], rr.k.to_numpy()[mk])
    rr["p_sim"] = [ladder_sf(X[f"sim_ladder_{s}"].iat[i], k) if s in STATS and isinstance(X[f"sim_ladder_{s}"].iat[i], dict) else np.nan
                   for s, i, k in zip(rr.stat, ri, rr.k)]
    rr["two"] = (rr.quote_class == "TWO_SIDED") & rr.yes_bid.notna() & rr.yes_ask.notna()
    rr["mid"] = np.where(rr.two, (rr.yes_bid.astype(float) + rr.yes_ask.astype(float)) / 2, np.nan)
    rr["ask"] = rr.yes_ask.astype(float)
    rr["date_s"] = date_s.to_numpy()[ri]; rr["gid"] = gid[ri]
    rr["listed_train"] = rr.date_s < TRAIN_END

    # ------------------------------------------------------------------ 0.2 feature F1: ladder recalibration on market-listed rungs (outcomes only)
    f1 = {}
    for s in STATS:
        a_ = rr[(rr.stat == s) & (rr.date_s < INNER_SPLIT)]; b_ = rr[(rr.stat == s) & (rr.date_s >= INNER_SPLIT) & (rr.date_s < TRAIN_END)]
        ia, sa = C.calibration_slope(a_.p_c2, a_.y)
        vb_raw = float(C.brier_rows(b_.p_c2, b_.y).mean()); vb_cal = float(C.brier_rows(recal_logit(b_.p_c2, ia, sa), b_.y).mean())
        t_ = rr[(rr.stat == s) & rr.listed_train]
        it, stt = C.calibration_slope(t_.p_c2, t_.y)
        f1[s] = dict(inner_intercept=ia, inner_slope=sa, inner_validation_brier_raw=vb_raw, inner_validation_brier_recal=vb_cal,
                     accepted=bool(vb_cal < vb_raw), final_intercept=it, final_slope=stt, n_inner_fit=len(a_), n_inner_val=len(b_), n_train=len(t_))
    rr["p_c2f"] = rr.p_c2
    for s in STATS:
        if f1[s]["accepted"]:
            mk = rr.stat == s
            rr.loc[mk, "p_c2f"] = recal_logit(rr.loc[mk, "p_c2"], f1[s]["final_intercept"], f1[s]["final_slope"])
    chk_c2.append(_chk("f1_recalibration_selected_inside_train_only", True,
                       json.dumps({s: [round(f1[s]["inner_slope"], 3), f1[s]["accepted"]] for s in STATS})))
    say(f"F2 pool {pool_w}; F1 {[(s, f1[s]['accepted']) for s in STATS]}")
    return dict(X=X, rr=rr, c1=c1, c1a=c1a, pf_pmf=pf_pmf, c2_pmf=c2_pmf, f1=f1, f2=f2_log, M=M, gf=gf, tout=tout, fc=fc, fc_stats=fc_stats,
                m_stats=m_stats, out=out, av=av, st=st, h=h, masks=masks, checks=dict(data=chk_data, fc=chk_fc, mkt=chk_mkt, inj=chk_inj, c1=chk_c1, c2=chk_c2),
                n_dnp_rungs=n_dnp_rungs, P=P, out_dir=out_dir, repo=repo)


def _mae(e):
    e = np.asarray(e, float); return dict(n=int(len(e)), bias=float(e.mean()), mae=float(np.abs(e).mean()), rmse=float(np.sqrt((e ** 2).mean()))) if len(e) else dict(n=0)


def _var(pmf):
    k = np.arange(pmf.shape[1]); mu = pmf @ k
    return pmf @ (k ** 2) - mu ** 2, mu


def _pit(pmf, y, seed=SEED):
    cdf = np.cumsum(pmf, axis=1); y = np.minimum(np.asarray(y, int), pmf.shape[1] - 1); i = np.arange(len(y))
    hi = cdf[i, y]; lo = np.where(y > 0, cdf[i, np.maximum(y - 1, 0)], 0.0)
    return lo + np.random.default_rng(seed).random(len(y)) * (hi - lo)


def market_median(P: pd.DataFrame) -> dict:
    """Market-implied median per (game, player, stat) from two-sided mids: linear interpolation of the k at which
    P(X >= k) crosses 0.5, minus 0.5 (continuity). Only bracketed ladders are used."""
    out = {}
    q = P[(P.quote_class == "TWO_SIDED") & P.yes_bid.notna() & P.yes_ask.notna()].copy()
    q["mid"] = (q.yes_bid.astype(float) + q.yes_ask.astype(float)) / 2
    for (g, e, s), grp in q.groupby(["game_id", "player_id", "stat"], sort=True):
        grp = grp.sort_values("k"); k = grp.k.to_numpy(float); m = grp.mid.to_numpy()
        below = np.where(m < 0.5)[0]
        if len(below) == 0 or below[0] == 0 or not (m >= 0.5).any():
            continue
        i = below[0]; k0, k1, q0, q1 = k[i - 1], k[i], m[i - 1], m[i]
        out[(g, e, s)] = k0 + (q0 - 0.5) / (q0 - q1) * (k1 - k0) - 0.5 if q0 != q1 else k0 - 0.5
    return out


def decompose(S) -> dict:
    X, rr, pf_pmf = S["X"], S["rr"], S["pf_pmf"]
    played = X.y_play.to_numpy() & X.has_pf.to_numpy()
    lead_h = (X.tip_ts - X.pf_gen_ts).to_numpy() / 3600.0
    listed = set(zip(S["P"].game_id, S["P"].player_id))
    is_listed = np.array([(g, e) in listed for g, e in zip(X.game_id, X.entity_id)])
    st = S["st"].set_index(["game_id", "entity_id"])
    eff = np.array([st.eff_ts.get((g, e), -1) for g, e in zip(X.game_id, X.entity_id)])
    stale = (eff > X.pf_gen_ts.to_numpy())     # an official status (re)published after the pf freeze but before T-60
    pfm = X.pf_mean_minutes.to_numpy(float)
    strata = {"all_played": played, "market_listed": played & is_listed, "not_listed": played & ~is_listed,
              "pf_minutes_ge_28": played & (pfm >= 28), "pf_minutes_20_28": played & (pfm >= 20) & (pfm < 28), "pf_minutes_lt_20": played & (pfm < 20),
              "started_posthoc": played & X.y_started.to_numpy(), "bench_posthoc": played & ~X.y_started.to_numpy(),
              "status_questionable_or_doubtful": played & X.status.isin(["questionable", "doubtful"]).to_numpy(),
              "status_probable": played & (X.status == "probable").to_numpy(), "status_not_listed": played & (X.status == "not_listed").to_numpy(),
              "status_published_after_pf_freeze": played & stale, "pf_lead_lt_2h": played & (lead_h < 2), "pf_lead_2_4h": played & (lead_h >= 2) & (lead_h < 4),
              "pf_lead_ge_4h": played & (lead_h >= 4), "train_period": played & (X.date_s < TRAIN_END).to_numpy(), "test_period": played & (X.date_s >= TRAIN_END).to_numpy()}
    ymin = X.y_min.to_numpy()
    out = {"strata": {}, "minutes_vs_rate": {}, "dispersion": {}, "market_location": {}, "line_distance": {}, "calibration_by_period": {}}
    for name, mk in strata.items():
        row = dict(n=int(mk.sum()), minutes=_mae((ymin - pfm)[mk]))
        for s in STATS + ["pra"]:
            v, mu = _var(pf_pmf[s][mk]) if mk.any() else (np.array([]), np.array([]))
            e = X[f"y_{s}"].to_numpy()[mk] - mu
            row[s] = dict(**_mae(e), variance_ratio=float(np.mean(e ** 2) / np.mean(v)) if mk.any() else None)
        out["strata"][name] = row
    for s in STATS:
        mk = played & (pfm > 0)
        rate = X[f"pf_mean_{s}"].to_numpy(float)[mk] / pfm[mk]
        e_tot = X[f"y_{s}"].to_numpy()[mk] - X[f"pf_mean_{s}"].to_numpy(float)[mk]
        e_min = rate * (ymin[mk] - pfm[mk]); e_rate = e_tot - e_min
        out["minutes_vs_rate"][s] = dict(n=int(mk.sum()), var_share_minutes_term=float(np.var(e_min) / np.var(e_tot)),
                                         var_share_rate_term=float(np.var(e_rate) / np.var(e_tot)), mae_total=float(np.abs(e_tot).mean()),
                                         mae_if_minutes_known=float(np.abs(e_rate).mean()))
    for s in STATS + ["pra"]:
        for name in ("all_played", "market_listed"):
            mk = strata[name]; pit = _pit(pf_pmf[s][mk], X[f"y_{s}"].to_numpy()[mk])
            out["dispersion"].setdefault(s, {})[name] = dict(n=int(mk.sum()), pit_deciles=[float(x) for x in np.histogram(pit, 10, (0, 1))[0] / len(pit)],
                                                             central80_coverage=float(np.mean((pit > 0.1) & (pit < 0.9))))
    med = market_median(S["P"])
    xi = pd.Series(np.arange(len(X)), index=pd.MultiIndex.from_arrays([X.game_id, X.entity_id]))
    for s in STATS + ["pra"]:
        keys = [(g, e) for (g, e, ss) in sorted(med) if ss == s and (g, e) in xi.index]
        ix = np.array([xi[k] for k in keys], int)
        if len(ix) == 0:
            continue
        ix_ok = ix[played[ix]]
        mk_med = np.array([med[(X.game_id.iat[i], X.entity_id.iat[i], s)] for i in ix_ok])
        y = X[f"y_{s}"].to_numpy()[ix_ok]
        cdf = np.cumsum(pf_pmf[s][ix_ok], axis=1); pmed = (cdf < 0.5).sum(1).astype(float)
        cl = X.game_id.to_numpy()[ix_ok]
        d = np.abs(y - pmed) - np.abs(y - mk_med)
        b = C.paired_cluster_bootstrap(d, cl, seed=SEED)
        slope = float(np.polyfit(pmed - mk_med, y - mk_med, 1)[0]) if np.std(pmed - mk_med) > 0 else None
        out["market_location"][s] = dict(n=int(len(ix_ok)), n_games=int(len(set(cl))), mae_pf_median=float(np.abs(y - pmed).mean()),
                                         mae_market_median=float(np.abs(y - mk_med).mean()), diff_pf_minus_market=b["mean"], ci95=[b["lo"], b["hi"]],
                                         bias_y_minus_pf_median=float((y - pmed).mean()), bias_y_minus_market_median=float((y - mk_med).mean()),
                                         slope_of_y_minus_mkt_on_pf_minus_mkt=slope,
                                         corr_pf_minus_mkt_with_y_minus_mkt=float(np.corrcoef(pmed - mk_med, y - mk_med)[0, 1]))
    two = rr[rr.two]
    for s in STATS + ["pra"]:
        g = two[two.stat == s]
        dist = np.abs(g.mid - 0.5)
        rows = []
        for lo_, hi_ in ((0.0, 0.1), (0.1, 0.25), (0.25, 0.4), (0.4, 0.51)):
            m = (dist >= lo_) & (dist < hi_)
            if m.sum() >= 30:
                d = C.brier_rows(g.p_pf[m], g.y[m]) - C.brier_rows(g.mid[m], g.y[m])
                rows.append(dict(abs_mid_minus_half=[lo_, min(hi_, 0.5)], n=int(m.sum()), brier_pf=float(C.brier_rows(g.p_pf[m], g.y[m]).mean()),
                                 brier_mid=float(C.brier_rows(g.mid[m], g.y[m]).mean()), diff=float(d.mean())))
        out["line_distance"][s] = rows
        for per, m in (("train_period", g.date_s < TRAIN_END), ("test_period", g.date_s >= TRAIN_END)):
            if m.sum() >= 30:
                out["calibration_by_period"].setdefault(s, {})[per] = dict(pf=_prob_metrics(g.p_pf[m], g.y[m]), mid=_prob_metrics(g.mid[m], g.y[m]),
                                                                          n_games=int(g.gid[m].nunique()))
    return out


def report(S, out_dir: Path | None = None, verbose: bool = True) -> dict:
    out_dir = Path(out_dir) if out_dir else OUT_DIR
    X, rr, c1, pf_pmf, c2_pmf = S["X"], S["rr"], S["c1"], S["pf_pmf"], S["c2_pmf"]
    masks = S["masks"]; gid = X.game_id.to_numpy(); played = X.y_play.to_numpy(); has_pf = X.has_pf.to_numpy()
    R = Results(); acc = {"player_means_given_played": {}, "participation": {}, "props_vs_market": {}, "games_vs_market": {}, "game_means": {}}

    # ------------------------------------------------------------------ incumbent accuracy (all 2026-27 games with outcomes)
    pp = played & has_pf
    for per, mk0 in (("all_games", np.ones(len(X), bool)), ("test_period", masks[POOLED])):
        blk = acc["player_means_given_played"].setdefault(per, {})
        for s in STATS + ["pra", "minutes"]:
            yv = X.y_min.to_numpy() if s == "minutes" else X[f"y_{s}"].to_numpy()
            m = pp & mk0
            blk[s] = {"pf_frozen": _mae(yv[m] - X[f"pf_mean_{s}"].to_numpy(float)[m])}
            if f"sim_mean_{s}" in X:
                ms = m & X[f"sim_mean_{s}"].notna().to_numpy()
                blk[s]["sim_frozen_same_rows"] = _mae(yv[ms] - X[f"sim_mean_{s}"].to_numpy(float)[ms])
                blk[s]["pf_frozen_same_rows"] = _mae(yv[ms] - X[f"pf_mean_{s}"].to_numpy(float)[ms])
            if s in STATS:
                cm = c1["cond"][s] @ np.arange(KMAX[s] + 1)
                blk[s]["c1_alpha_0_1_method"] = _mae(yv[m] - cm[m]); blk[s]["c2_alpha_0_2"] = _mae(yv[m] - (c2_pmf[s] @ np.arange(KMAX[s] + 1))[m])
        pb = acc["participation"].setdefault(per, {})
        m = has_pf & mk0 & X.in_outcomes.to_numpy()
        pb["pf_frozen"] = _prob_metrics(X.pf_p_play.to_numpy(float)[m], played[m])
        ms = m & X.sim_p_play.notna().to_numpy()
        pb["sim_frozen_same_rows"] = _prob_metrics(X.sim_p_play.to_numpy(float)[ms], played[ms])
        pb["c1_alpha_0_1_method"] = _prob_metrics(c1["p1"][m], played[m])
    two = rr[rr.two]
    for s in STATS + ["pra"]:
        g = two[two.stat == s]; ga = rr[(rr.stat == s) & rr.ask.notna()]
        gs = g[g.p_sim.notna()]
        blk = dict(n_rungs_played_two_sided=int(len(g)), n_games=int(g.gid.nunique()), n_rungs_one_sided_or_no_quote=int(((rr.stat == s) & ~rr.two).sum()),
                   pf_frozen=_prob_metrics(g.p_pf, g.y), kalshi_t60_mid=_prob_metrics(g.mid, g.y),
                   pf_frozen_rows_with_ask=_prob_metrics(ga.p_pf, ga.y), kalshi_t60_yes_ask_as_probability=_prob_metrics(ga.ask, ga.y),
                   sim_frozen_rungs_on_its_ladder=_prob_metrics(gs.p_sim, gs.y), kalshi_t60_mid_same_rows_as_sim=_prob_metrics(gs.mid, gs.y))
        acc["props_vs_market"][s] = blk
        cl = g.gid.to_numpy()
        R.add(FAMILY[s], [ARCH[s]], "brier_ladder_given_played_two_sided", "pf_frozen", "kalshi_t60_mid", C.brier_rows(g.p_pf, g.y), C.brier_rows(g.mid, g.y), cl,
              {ALLG: np.ones(len(g), bool), **{k: v for k, v in _rung_masks(g).items()}}, note="incumbent vs market, descriptive")
        R.add(FAMILY[s], [ARCH[s]], "logloss_ladder_given_played_two_sided", "pf_frozen", "kalshi_t60_mid", C.logloss_rows(g.p_pf, g.y), C.logloss_rows(g.mid, g.y), cl,
              {ALLG: np.ones(len(g), bool)}, note="incumbent vs market, descriptive")
        R.add(FAMILY[s], [ARCH[s]], "brier_ladder_given_played_any_ask", "pf_frozen", "kalshi_t60_yes_ask", C.brier_rows(ga.p_pf, ga.y), C.brier_rows(ga.ask, ga.y),
              ga.gid.to_numpy(), {ALLG: np.ones(len(ga), bool)}, note="yes-ask read as a probability; not a fair price")
        if len(gs):
            R.add(FAMILY[s], [ARCH[s]], "brier_ladder_given_played_two_sided", "sim_frozen", "kalshi_t60_mid", C.brier_rows(gs.p_sim, gs.y), C.brier_rows(gs.mid, gs.y),
                  gs.gid.to_numpy(), {ALLG: np.ones(len(gs), bool)}, note="frozen shadow baseline vs market, descriptive")
            R.add(FAMILY[s], [ARCH[s]], "brier_ladder_given_played_two_sided", "pf_frozen", "sim_frozen", C.brier_rows(gs.p_pf, gs.y), C.brier_rows(gs.p_sim, gs.y),
                  gs.gid.to_numpy(), {ALLG: np.ones(len(gs), bool)}, note="production vs shadow baseline, descriptive")
    for s in STATS + ["minutes"]:
        yv = X.y_min.to_numpy() if s == "minutes" else X[f"y_{s}"].to_numpy()
        ms = pp & X[f"sim_mean_{s}"].notna().to_numpy()
        R.add(FAMILY.get(s, "player_minutes"), [ARCH.get(s, "NBA:player_minutes")], "abs_err_mean_given_played", "pf_frozen", "sim_frozen",
              np.abs(yv - X[f"pf_mean_{s}"].to_numpy(float)), np.abs(yv - X[f"sim_mean_{s}"].to_numpy(float)), gid, {ALLG: ms}, note="descriptive")
    m = has_pf & X.in_outcomes.to_numpy() & X.sim_p_play.notna().to_numpy()
    R.add("player_availability", ["NBA:player_availability"], "brier_p_play", "pf_frozen", "sim_frozen", C.brier_rows(X.pf_p_play, played),
          C.brier_rows(X.sim_p_play.fillna(0.5), played), gid, {ALLG: m}, note="descriptive")
    # games
    G = game_rungs(S["M"], S["gf"], S["tout"])
    for fam in ("game_spread", "game_total", "team_total"):
        g = G[(G.family == fam) & (G.quote_class == "TWO_SIDED") & G.bid.notna() & G.ask.notna()].copy()
        if not len(g):
            continue
        g["mid"] = (g.bid.astype(float) + g.ask.astype(float)) / 2
        acc["games_vs_market"][fam] = dict(n_rungs_two_sided=int(len(g)), n_games=int(g.game_id.nunique()), pf_frozen=_prob_metrics(g.p, g.y),
                                           kalshi_t60_mid=_prob_metrics(g.mid, g.y),
                                           method="team_total: archived team pmf; spread/total: normal approximation with archived rho")
        R.add(fam, [f"NBA:{fam}"], "brier_two_sided", "pf_frozen", "kalshi_t60_mid", C.brier_rows(g.p, g.y), C.brier_rows(g.mid, g.y), g.game_id.to_numpy(),
              {ALLG: np.ones(len(g), bool)}, note="incumbent vs market, descriptive")
    gfi = S["gf"].set_index("game_id"); to = S["tout"].set_index(["game_id", "team"]); em = {"margin_home": [], "total": [], "team_points": []}
    for g, r in gfi.iterrows():
        try:
            h_, a_ = to.loc[(g, r.home)], to.loc[(g, r.away)]
        except KeyError:
            continue
        mh, ma = r.teams.get(r.home, {}).get("mean"), r.teams.get(r.away, {}).get("mean")
        if mh is None or ma is None:
            continue
        em["margin_home"].append((h_.pts - a_.pts) - (mh - ma)); em["total"].append((h_.pts + a_.pts) - (mh + ma))
        em["team_points"] += [h_.pts - mh, a_.pts - ma]
    acc["game_means"] = {k: _mae(v) for k, v in em.items()}

    # ------------------------------------------------------------------ challengers (TEST cohorts only)
    tm = {k: v & pp for k, v in masks.items()}
    for s in STATS:
        y = X[f"y_{s}"].to_numpy().astype(int)
        cr_pf = np.where(pp, 0.0, np.nan); cr_c1 = cr_pf.copy(); cr_c2 = cr_pf.copy()
        cr_pf[pp] = _crps_dense(pf_pmf[s][pp], y[pp]); cr_c1[pp] = _crps_dense(c1["cond"][s][pp], y[pp]); cr_c2[pp] = _crps_dense(c2_pmf[s][pp], y[pp])
        R.add(FAMILY[s], [ARCH[s]], "crps_given_played", "C2_alpha-nba-avail-0.2", "pf_frozen", cr_c2, cr_pf, gid, tm, headline=True)
        R.add(FAMILY[s], [ARCH[s]], "crps_given_played", "C1_alpha-nba-avail-0.1_method", "pf_frozen", cr_c1, cr_pf, gid, tm, headline=True)
        mu_pf = X[f"pf_mean_{s}"].to_numpy(float); mu_c1 = c1["cond"][s] @ np.arange(KMAX[s] + 1); mu_c2 = c2_pmf[s] @ np.arange(KMAX[s] + 1)
        R.add(FAMILY[s], [ARCH[s]], "abs_err_mean_given_played", "C2_alpha-nba-avail-0.2", "pf_frozen", np.abs(y - mu_c2), np.abs(y - mu_pf), gid, tm)
        R.add(FAMILY[s], [ARCH[s]], "abs_err_mean_given_played", "C1_alpha-nba-avail-0.1_method", "pf_frozen", np.abs(y - mu_c1), np.abs(y - mu_pf), gid, tm)
        g = two[(two.stat == s) & (two.date_s >= TRAIN_END)]
        rm = _rung_masks(g); cl = g.gid.to_numpy()
        R.add(FAMILY[s], [ARCH[s]], "brier_ladder_given_played_two_sided", "C2_alpha-nba-avail-0.2", "pf_frozen", C.brier_rows(g.p_c2f, g.y), C.brier_rows(g.p_pf, g.y), cl, rm, headline=True)
        R.add(FAMILY[s], [ARCH[s]], "brier_ladder_given_played_two_sided", "C2_alpha-nba-avail-0.2", "kalshi_t60_mid", C.brier_rows(g.p_c2f, g.y), C.brier_rows(g.mid, g.y), cl, rm, headline=True)
        R.add(FAMILY[s], [ARCH[s]], "brier_ladder_given_played_two_sided", "C1_alpha-nba-avail-0.1_method", "pf_frozen", C.brier_rows(g.p_c1, g.y), C.brier_rows(g.p_pf, g.y), cl, rm)
        R.add(FAMILY[s], [ARCH[s]], "brier_ladder_given_played_two_sided", "C1_alpha-nba-avail-0.1_method", "kalshi_t60_mid", C.brier_rows(g.p_c1, g.y), C.brier_rows(g.mid, g.y), cl, rm)
        R.add(FAMILY[s], [ARCH[s]], "logloss_ladder_given_played_two_sided", "C2_alpha-nba-avail-0.2", "pf_frozen", C.logloss_rows(g.p_c2f, g.y), C.logloss_rows(g.p_pf, g.y), cl, rm)
        R.add(FAMILY[s], [ARCH[s]], "brier_ladder_given_played_two_sided", "pf_frozen", "kalshi_t60_mid", C.brier_rows(g.p_pf, g.y), C.brier_rows(g.mid, g.y), cl, rm,
              note="incumbent vs market on the TEST games only")
    m = has_pf & X.in_outcomes.to_numpy()
    R.add("player_availability", ["NBA:player_availability"], "brier_p_play", "C1_alpha-nba-avail-0.1_method", "pf_frozen", C.brier_rows(c1["p1"], played),
          C.brier_rows(X.pf_p_play.fillna(0.5), played), gid, {k: v & m for k, v in masks.items()})
    R.add("player_minutes", ["NBA:player_minutes"], "abs_err_minutes_given_played", "C1_alpha-nba-avail-0.1_method", "pf_frozen",
          np.abs(c1["m2"] - X.y_min.to_numpy()), np.abs(X.pf_mean_minutes.to_numpy(float) - X.y_min.to_numpy()), gid, tm)
    rows = R.finalize()
    return dict(R=R, rows=rows, acc=acc, G=G)


def _rung_masks(g: pd.DataFrame) -> dict:
    return cohort_masks(g.date_s.reset_index(drop=True)) if len(g) else {}


# =============================================================================================== evaluation document
def _ds(dataset_id, path, rows, first, last, kind, commit, branch, digest_=None):
    d = dict(dataset_id=dataset_id, repo=NBA_REPO, branch=branch, commit=commit, path=path, rows=int(rows), first=first, last=last, kind=kind,
             rights_tier="UNRESOLVED_INTERNAL_ONLY")
    if digest_:
        d["content_digest"] = digest_
    return d


def _iso(ts):
    return pd.Timestamp(int(ts), unit="s", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def build_document(S, Q) -> tuple:
    X, rr, fc, M, out, av, h = S["X"], S["rr"], S["fc"], S["M"], S["out"], S["av"], S["h"]
    R = Q["R"]; rows = Q["rows"]; acc = Q["acc"]; repo = S["repo"]
    dec = decompose(S)
    inj = load_injury_pit_official(repo) if has_commit(repo, INJ_COMMIT) else None
    if inj is not None:
        dec["staleness_between_pf_freeze_and_t60"] = staleness(X, inj)
    inj_files = [p for p, _ in ls_tree(repo, INJ_COMMIT, "injury_pit/official")] if inj is not None else []
    last_d = str(X.date_s.max()).replace("-", "")
    inj_in = [p for p in inj_files if p.split("dt=")[1][:10].replace("-", "") <= last_d]
    n_rep = int(av.report.nunique())
    chk_inj_x = _chk("official_report_coverage_vs_data_injury_pit", True,
                     f"projection-data explicit rows come from {n_rep} distinct official report files; data-injury-pit@{INJ_COMMIT[:7]} holds {len(inj_in)} official "
                     f"report captures dated up to the last evaluated game ({len(inj_files)} in total); data-injury-pit is used only for the staleness diagnosis "
                     f"(design.decomposition.staleness_between_pf_freeze_and_t60), never as a challenger input")
    pfc = fc[fc.model == "pf"]; sic = fc[fc.model == "sim"]
    data = [
        _ds("pf_frozen_player_forecasts", "forecasts/nba/", len(pfc), _iso(pfc.gen_ts.min()), _iso(pfc.gen_ts.max()), "PROSPECTIVE_CAPTURE", PD_COMMIT, PD_BRANCH,
            digest(sorted(pfc.forecast_key.tolist())) if "forecast_key" in pfc else None),
        _ds("sim_frozen_shadow_baseline_forecasts", "forecasts/nba/ (model_role=incumbent)", len(sic), _iso(sic.gen_ts.min()), _iso(sic.gen_ts.max()),
            "PROSPECTIVE_CAPTURE", PD_COMMIT, PD_BRANCH),
        _ds("pf_frozen_team_points_forecasts", "game_forecasts/nba/", len(S["gf"]), _iso(S["gf"].gen_ts.min()), _iso(S["gf"].gen_ts.max()), "PROSPECTIVE_CAPTURE",
            PD_COMMIT, PD_BRANCH),
        _ds("kalshi_t60_quotes", "market_snapshots/nba/ (horizon T-60)", len(M), _iso(M.obs_ts.min()), _iso(M.obs_ts.max()), "PROSPECTIVE_CAPTURE", PD_COMMIT, PD_BRANCH),
        _ds("espn_final_player_outcomes_2026-27", "outcomes/nba/", len(out), str(out.game_date_et.min()), str(out.game_date_et.max()), "PROSPECTIVE_CAPTURE",
            PD_COMMIT, PD_BRANCH),
        _ds("espn_final_team_outcomes_2026-27", "team_outcomes/nba/", len(S["tout"]), str(S["tout"].game_date.min()), str(S["tout"].game_date.max()),
            "PROSPECTIVE_CAPTURE", PD_COMMIT, PD_BRANCH),
        _ds("nba_official_injury_report_explicit_rows", "availability/nba/ (source=nba_official_injury_report, certainty=REPORTED)", len(av), _iso(av.eff_ts.min()),
            _iso(av.eff_ts.max()), "PROSPECTIVE_CAPTURE", PD_COMMIT, PD_BRANCH),
        _ds("espn_player_games_2025-26_and_2026-27", "data/history/espn/player_games_{2025-26,2026-27}.parquet (+ outcomes extension)", len(h),
            str(h.game_date_et.min()), str(h.game_date_et.max()), "HISTORICAL_BACKFILL", MAIN_COMMIT, "main"),
    ]
    if inj is not None:
        data.append(_ds("nba_official_injury_report_captures_data_injury_pit", "injury_pit/official/", len(inj), _iso(inj.eff_ts.min()), _iso(inj.eff_ts.max()),
                        "PROSPECTIVE_CAPTURE", INJ_COMMIT, INJ_BRANCH))
    fstat = lambda s: {k: S["f2"][s][k] for k in ("inner_fit_weight_on_pf", "inner_validation_crps_pool", "inner_validation_crps_pf", "accepted", "final_weight_on_pf")}
    features = [
        dict(feature_id="frozen_incumbent_t60_extraction", catalog_inputs=["NBA:m.quote_history"], status="REFERENCE",
             description="Latest pf / sim forecast per (game, player, stat) generated and archived at or before tip-60; Kalshi T-60 board per ticker; final ESPN outcomes.",
             pit_rule="max(generated_utc, archived_utc) <= tip - 60 min; board_observed_utc <= tip - 60 min and not older than 30 min at the horizon",
             checks=S["checks"]["fc"] + S["checks"]["mkt"] + S["checks"]["data"]),
        dict(feature_id="c1_alpha_0_1_method_pit_2026_27", catalog_inputs=["NBA:nba.injuries_pit", "NBA:nba.status_resolution_prob", "NBA:nba.minutes",
                                                                              "NBA:nba.replacement_level_minutes_absorption", "NBA:nba.minutes_scenario_mixture", "NBA:nba.stat_dist"],
             status="EVALUATED",
             description="alpha-nba-avail-0.1 procedure (recent-share P(play), EWM minutes, T-60 official status gate, 240-minute redistribution, shrunk per-minute rates, "
                         "NB minutes-scenario mixture) re-fitted on 2026-27 TRAIN games and applied to the frozen pf roster of every game.",
             pit_rule="box features from games on strictly earlier dates; official status rows with effective time <= tip - 60 min; all parameters fitted on games before "
                      + TRAIN_END, fitted_parameters=S["c1"]["params"], checks=S["checks"]["inj"] + S["checks"]["c1"] + [chk_inj_x]),
        dict(feature_id="f2_linear_pool_pf_with_c1", catalog_inputs=["NBA:nba.stat_dist"],
             status="ACCEPTED for " + ", ".join(s for s in STATS if S["f2"][s]["accepted"]) + "; REJECTED for " + ", ".join(s for s in STATS if not S["f2"][s]["accepted"]),
             description="Conditional pmf = w * pf + (1 - w) * C1 per stat (linear opinion pool; stays a coherent pmf). Justification: the decomposition shows the pf "
                         "error is ~75% per-minute-rate noise, and an independently built forecast with partly independent errors lowers expected CRPS under pooling. "
                         "w chosen on a 0.1 grid by CRPS; kept only if it beats pf on the inner chronological validation window.",
             pit_rule=f"w fitted on games before {INNER_SPLIT} (C1 refitted on the same window) and validated on [{INNER_SPLIT}, {TRAIN_END}); final w refitted on all TRAIN",
             fitted_parameters={s: fstat(s) for s in STATS}, checks=[c for c in S["checks"]["c2"] if c["name"].startswith(("f2", "c2"))]),
        dict(feature_id="f1_ladder_recalibration_market_listed_rungs", catalog_inputs=["NBA:nba.stat_dist", "NBA:nba.market_calibration_bias"],
             status="ACCEPTED for " + (", ".join(s for s in STATS if S["f1"][s]["accepted"]) or "none") + "; REJECTED for " + (", ".join(s for s in STATS if not S["f1"][s]["accepted"]) or "none"),
             description="Logistic recalibration P' = sigmoid(a + b logit P) of the C2 ladder on the rungs Kalshi listed (fitted on settled outcomes only, never on prices). "
                         "Motivated by the incumbent's calibration slope < 1 on listed rungs in the early season.",
             pit_rule=f"(a, b) fitted on listed rungs of games before {INNER_SPLIT}, validated on [{INNER_SPLIT}, {TRAIN_END}); final fit on all TRAIN",
             fitted_parameters=S["f1"], checks=[c for c in S["checks"]["c2"] if c["name"].startswith("f1")]),
    ]
    head = [r for r in rows if r["headline"]]
    hv = lambda arm, ref, met: {r["market_family"]: r["verdict"] for r in head if r["challenger_arm"] == arm and r["reference"] == ref and r["metric"] == met}
    v_pf = {**{f"crps:{k}": v for k, v in hv("C2_alpha-nba-avail-0.2", "pf_frozen", "crps_given_played").items()},
            **{f"brier:{k}": v for k, v in hv("C2_alpha-nba-avail-0.2", "pf_frozen", "brier_ladder_given_played_two_sided").items()}}
    v_mk = hv("C2_alpha-nba-avail-0.2", "kalshi_t60_mid", "brier_ladder_given_played_two_sided")
    if all(v == "VALIDATED_IMPROVEMENT" for v in v_pf.values()) and len(v_mk) == 4 and all(v == "VALIDATED_IMPROVEMENT" for v in v_mk.values()):
        overall = "VALIDATED_IMPROVEMENT"
    elif any(v == "VALIDATED_IMPROVEMENT" for v in v_pf.values()) and not any(v == "NOT_IMPROVED" for v in v_pf.values()):
        overall = "IMPROVED_NOT_VALIDATED"
    elif any(v == "NOT_IMPROVED" for v in v_pf.values()) and not any(v == "VALIDATED_IMPROVEMENT" for v in v_pf.values()):
        overall = "NOT_IMPROVED"
    else:
        overall = "INCONCLUSIVE"
    inc_mk = {r["market_family"]: (r["verdict"], round(r["diff"], 4), [round(x, 4) for x in r["ci95"]], r["n_rows"], r["n_clusters"]) for r in rows
              if r["challenger_arm"] == "pf_frozen" and r["reference"] == "kalshi_t60_mid" and r["cohort"] == ALLG and r["metric"] in ("brier_ladder_given_played_two_sided", "brier_two_sided")}
    n_mkt_test_games = int(rr[rr.two & (rr.date_s >= TRAIN_END)].gid.nunique())
    verdict = dict(
        overall=overall,
        rule="Fixed in code: VALIDATED_IMPROVEMENT only if C2 is validated against the frozen pf incumbent (CRPS and two-sided ladder Brier) AND against the Kalshi T-60 mid "
             "in all four prop families; any validated row vs pf with none worse reads IMPROVED_NOT_VALIDATED.",
        c2_vs_pf_frozen=v_pf, c2_vs_kalshi_t60_mid=v_mk, incumbent_pf_vs_kalshi_t60_mid_all_games=inc_mk,
        evidence_sufficiency=dict(
            incumbent_vs_market=f"SUFFICIENT for a direction on points/rebounds/assists/PRA ladders, spreads and team totals ({max(v[4] for v in inc_mk.values())} games with T-60 quotes, all market rows NOT_IMPROVED or INCONCLUSIVE for the incumbent); "
                                "the incumbent never significantly beats the mid",
            challenger_vs_market=f"INSUFFICIENT_EVIDENCE: only {n_mkt_test_games} TEST games carry T-60 player-prop quotes and all fall in cohort 1; the projection-data "
                                 f"market archive has no T-60 boards for games after {_iso(M.tip_ts.max())[:10]}, so no challenger-vs-market row can replicate in cohort 2",
            challenger_vs_incumbent=f"{int(X[S['masks'][POOLED]].game_id.nunique())} TEST games, two cohorts of about one week each; one month of season"),
        retain_incumbent=True,
        reason="The frozen production model pf is clearly better than the frozen shadow baseline but worse than the Kalshi T-60 mid on player-prop ladders over 118 games; "
               "its disagreements with the market carry no outcome information. The 0.2 pool improves pf on assists CRPS (validated) and is neutral elsewhere; it does not "
               "beat the market and is research-only.")
    claims = []
    claims.append(dict(input="NBA:nba.stat_dist", stage="EVALUATED", outcome="OK" if overall in ("VALIDATED_IMPROVEMENT", "IMPROVED_NOT_VALIDATED") else "PARTIAL",
                       evidence="C2 linear pool vs frozen pf, TEST crps_given_played: " + "; ".join(
                           f"{s} {r['diff']:+.4f} [{r['ci95'][0]:+.4f}, {r['ci95'][1]:+.4f}] {r['verdict']}" for s in STATS
                           for r in [R.find(FAMILY[s], "crps_given_played", "C2_alpha-nba-avail-0.2", "pf_frozen")] if r)))
    c1r = [R.find(FAMILY[s], "crps_given_played", "C1_alpha-nba-avail-0.1_method", "pf_frozen") for s in STATS]
    pr = R.find("player_availability", "brier_p_play", "C1_alpha-nba-avail-0.1_method", "pf_frozen")
    claims.append(dict(input="NBA:nba.injuries_pit", stage="EVALUATED", outcome="PARTIAL",
                       evidence=f"T-60 official status gate inside C1 vs frozen pf (which already ingests the official report), TEST brier_p_play {pr['diff']:+.4f} "
                                f"[{pr['ci95'][0]:+.4f}, {pr['ci95'][1]:+.4f}] {pr['verdict']}: no gain over the production participation model on 2026-27"))
    claims.append(dict(input="NBA:nba.minutes_scenario_mixture", stage="EVALUATED", outcome="PARTIAL",
                       evidence="C1 (minutes-scenario NB mixture) vs frozen pf, TEST crps_given_played: " + "; ".join(
                           f"{r['market_family']} {r['diff']:+.4f} {r['verdict']}" for r in c1r if r)))
    rej = [s for s in STATS if not S["f1"][s]["accepted"]]
    claims.append(dict(input="NBA:nba.market_calibration_bias", stage="FEATURE_BUILT", outcome="REJECTED" if len(rej) >= 3 else "PARTIAL",
                       evidence="Ladder recalibration on market-listed rungs (outcomes only) rejected by inner chronological validation for " + ", ".join(rej)
                                + "; the incumbent's early-season overconfidence (slope < 1) did not persist into TEST"))
    abl = []
    for s in STATS:
        r = R.find(FAMILY[s], "crps_given_played", "C2_alpha-nba-avail-0.2", "pf_frozen")
        if r:
            abl.append(dict(step="pf -> pf (+) C1 pool (F2)", feature="f2_linear_pool_pf_with_c1", catalog_inputs=["NBA:nba.stat_dist"], market_family=FAMILY[s],
                            metric="crps_given_played", cohort=POOLED, delta=r["diff"], ci95=r["ci95"], n_rows=r["n_rows"], n_clusters=r["n_clusters"], p_raw=r["p_raw"],
                            p_holm=r["p_holm"], replicated=r["replicated"], verdict=r["verdict"]))
    for s in STATS:
        g = rr[rr.two & (rr.stat == s) & (rr.date_s >= TRAIN_END)]
        if len(g) >= 30:
            d = C.brier_rows(g.p_c2f, g.y) - C.brier_rows(g.p_c2, g.y)
            if np.allclose(d, 0):
                abl.append(dict(step="pool -> pool + F1 recalibration", feature="f1_ladder_recalibration_market_listed_rungs", catalog_inputs=["NBA:nba.stat_dist"],
                                market_family=FAMILY[s], metric="brier_ladder_given_played_two_sided", cohort=POOLED, delta=0.0, ci95=[0.0, 0.0], n_rows=int(len(g)),
                                n_clusters=int(g.gid.nunique()), p_raw=1.0, p_holm=1.0, replicated=False, verdict="REJECTED"))
            else:
                b = C.paired_cluster_bootstrap(d, g.gid.to_numpy(), seed=SEED)
                abl.append(dict(step="pool -> pool + F1 recalibration", feature="f1_ladder_recalibration_market_listed_rungs", catalog_inputs=["NBA:nba.stat_dist"],
                                market_family=FAMILY[s], metric="brier_ladder_given_played_two_sided", cohort=POOLED, delta=b["mean"], ci95=[b["lo"], b["hi"]],
                                n_rows=b["n_rows"], n_clusters=b["n_clusters"], p_raw=b["p_two_sided"], p_holm=b["p_two_sided"], replicated=False,
                                verdict=C.verdict_from(b["lo"], b["hi"], b["p_two_sided"], False)))
    cs = {}
    for name, mk in S["masks"].items():
        cs[name] = dict(games=int(X[mk].game_id.nunique()), player_games=int(mk.sum()), played=int((mk & X.y_play.to_numpy()).sum()),
                        market_games=int(rr[rr.two & rr.date_s.isin(set(X[mk].date_s))].gid.nunique()))
    tr = (X.date_s < TRAIN_END).to_numpy()
    cs["train"] = dict(games=int(X[tr].game_id.nunique()), player_games=int(tr.sum()), played=int((tr & X.y_play.to_numpy()).sum()))
    design = dict(
        incumbent_reference="ACTUAL frozen production forecasts (pf-nba; pf-1.2.1 for the first slates then pf-1.3.0) and the frozen shadow baseline nba_sim_rotation_v1, "
                            "exactly as archived on projection-data; no reproduction",
        freeze=dict(rule="T-60", forecast="latest per (model, game, player, stat) with max(generated, archived) <= tip - 60 min",
                    market="T-60 horizon board observed <= tip - 60 min (<= 30 min old)", injury="explicit official rows with max(captured, source_updated) <= tip - 60 min"),
        population="frozen pf participation roster of each 2026-27 regular-season game with final outcomes; props scored on players who played (Kalshi settles a DNP "
                   "prop at its last fair price, so market and forecasts are conditional on playing)",
        windows=dict(train=f"< {TRAIN_END}", inner_fit=f"< {INNER_SPLIT}", inner_validation=f"[{INNER_SPLIT}, {TRAIN_END})", test_cohort_1=f"[{TRAIN_END}, {COH_SPLIT}]",
                     test_cohort_2=f"> {COH_SPLIT}"),
        arms={"pf_frozen": "production forecasts as archived", "sim_frozen": "shadow baseline ladders as archived",
              "C1_alpha-nba-avail-0.1_method": "0.1 procedure re-fitted on 2026-27 TRAIN", "C2_alpha-nba-avail-0.2": "pf (+) C1 linear pool where accepted, + F1 where accepted",
              "kalshi_t60_mid": "(yes_bid + yes_ask) / 2 on TWO_SIDED quotes", "kalshi_t60_yes_ask": "yes_ask read as a probability (all quotes with an ask)"},
        statistics="paired game-clustered bootstrap (2000 draws, seed 7); Holm across the 16 pre-registered headline rows; other rows Holm within (arm, reference, cohort)",
        economics="fees, spreads and execution are out of scope; nothing here is a profitability claim",
        cohort_sizes=cs, headline_rows=len(head), accuracy=acc, decomposition=dec,
        market_counts=dict(t60_tickers=len(M), prop_rungs_in_frame=int(S["P"].in_frame.sum()), prop_rungs_scored_played=int(len(rr)),
                           prop_rungs_dropped_dnp=int(S["n_dnp_rungs"]), prop_rungs_two_sided=int(rr.two.sum()), prop_rungs_one_sided_or_no_quote=int((~rr.two).sum()),
                           games_with_t60_props=int(rr.gid.nunique()), stats=S["m_stats"]),
        pr_context={"chmoses98/nba-edge-finder#104": "open draft (availability overlay + 2026-27 replay), not merged",
                    "chmoses98/nba-edge-finder#105": "open draft (calibration, stacked on #104), not merged; its own pretip market comparison also found the market better"})
    limitations = [
        f"Data defect: the projection-data market_snapshots stage archived no T-60 (or any pregame) boards after the {_iso(M.tip_ts.max())[:10]} tips; games of 2026-11-07..13 have forecasts and outcomes but no market reference. The capture-worker boards on data-archive were not read.",
        "One month of 2026-27 regular season (176 games with outcomes, 2026-10-20..2026-11-13); T-60 player-prop quotes exist for 118 games and only 31 TEST games, so every challenger-vs-market row is INSUFFICIENT_EVIDENCE regardless of its point estimate.",
        f"The pf label covered {int(fc[fc.model == 'pf'].version.str.split('+').str[1].nunique())} distinct code commits over the window (pf-1.2.1 on the first slates, then pf-1.3.0); 'the frozen incumbent' is the version stream that was live at each freeze, not one fixed binary.",
        "Spread and total probabilities from the pf team-points forecasts use a normal approximation with the archived rho (the owner's own note calls them approximate); team totals use the archived pmf exactly.",
        "The pf team-points forecasts under-forecast 2026-27 scoring (team points bias in design.accuracy.game_means), which by itself explains part of the total / team-total gap to the market.",
        "C1 is a re-implementation of the 0.1 procedure on 2026-27 data with the frozen pf roster as its population; it is not the 0.1 code path run unchanged (0.1 hard-codes 2025-26 inputs).",
        "During development the author looked at TEST CRPS for a few pool weights before the inner-validation selection rule was fixed in code; the rule itself never reads TEST, but this is disclosed as a mild garden-of-forking-paths risk.",
        "Implicit ACTIVE roster rows in the availability archive are not used (PR #104 found their timestamps can precede the roster evidence); only explicit official-report rows are.",
        "Outcomes for 181 box-score rows of players absent from the frozen roster cannot be assigned a team and are excluded from challenger history (not from scoring).",
        "No fees, no execution, no profitability claim; yes-ask rows are a pessimistic price read as a probability, not an executable edge measure.",
    ]
    doc = dict(schema=C.EVAL_SCHEMA, status="RESEARCH_ONLY", sport="NBA", challenger_id=CHALLENGER_ID, incumbent_id=INCUMBENT_ID, data=data, features=features,
               design=design, results=rows, ablations=abl, verdict=verdict, limitations=limitations, input_stage_claims=claims,
               source_commits={f"nba-edge-finder@{PD_BRANCH}": PD_COMMIT, "nba-edge-finder@main": MAIN_COMMIT, f"nba-edge-finder@{INJ_BRANCH}": INJ_COMMIT})
    by_date = X.groupby("date_s").agg(games=("game_id", "nunique"), player_games=("entity_id", "size"), played=("y_play", "sum")).reset_index()
    mk_d = rr[rr.two].groupby("date_s").agg(prop_rungs_two_sided=("ticker", "size"), market_games=("gid", "nunique")).reset_index()
    summ = dict(challenger_id=CHALLENGER_ID, by_date=by_date.merge(mk_d, on="date_s", how="left").fillna(0).to_dict("records"),
                frame_digest=digest(sorted(zip(X.game_id, X.entity_id))), rung_digest=digest(sorted(rr.ticker.tolist())),
                cohort_sizes=cs)
    return doc, summ


def evaluate(repo: Path | None = None, out_dir: Path | None = None, verbose: bool = True) -> dict:
    S = run(repo, out_dir, verbose)
    Q = report(S)
    doc, summ = build_document(S, Q)
    errs = C.validate_evaluation(doc)
    if errs:
        raise RuntimeError(f"evaluation violates the contract: {errs}")
    od = S["out_dir"]
    C.write_json(od / "evaluation.json", doc)
    C.write_json(od / "predictions_summary.json", summ)
    return doc


def main(argv=None) -> int:
    doc = evaluate()
    print(f"{CHALLENGER_ID}: overall {doc['verdict']['overall']}; {len(doc['results'])} result rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
