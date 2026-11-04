"""MLB data layer for the outcome-intelligence audit (RESEARCH_ONLY). Pure numpy/pandas, no network.

Reads a checkout of github.com/chmoses98/edge-finder-api (main) and exposes compact, time-explicit tables:
  games       - full MLB schedule 2022-2026 (data/research_cache/bullpen_backtest/<yr>/schedules/*.json), deduped by gamePk, with final runs
  obs         - Kalshi market observations (data/edgelab/observations)   [price history; 2026-08-01 .. corpus end only]
  settle      - EdgeLab settlements deduped by marketTicker
  evals       - EdgeLab ModelEvaluation rows (SIFT model probabilities, percent units)
Every loader returns (data, sha256_by_file).
"""
from __future__ import annotations
import glob, gzip, hashlib, json, os, re
from datetime import datetime, timezone
import numpy as np
import pandas as pd

CHECKS = "RESEARCH_ONLY"


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def opener(p):
    return gzip.open(p, "rt") if p.endswith(".gz") else open(p, "r")


def iter_jsonl(pattern):
    """yield (file, record); files sorted."""
    for f in sorted(glob.glob(pattern)):
        with opener(f) as fh:
            for line in fh:
                if line.strip():
                    yield f, json.loads(line)


def parse_ts(s):
    if s is None:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


# ----------------------------------------------------------------------------- games (schedule + final runs)
def load_schedule_games(root):
    """One row per gamePk. Final scores come from the schedule's teams.*.score where status is Final; a gamePk appearing on several
    dates (postponed then replayed) keeps the record whose abstractGameState is Final (last such by officialDate)."""
    rows, hashes = {}, {}
    for f in sorted(glob.glob(os.path.join(root, "data/research_cache/bullpen_backtest/*/schedules/*.json"))):
        hashes[os.path.relpath(f, root)] = sha256_file(f)
        d = json.load(open(f))
        for dt in d.get("dates", []):
            for g in dt.get("games", []):
                st = g.get("status", {})
                t = g.get("teams", {})
                rec = dict(gamePk=int(g["gamePk"]), season=int(g.get("season", 0) or 0), gameType=g.get("gameType"),
                           gameDate=g.get("gameDate"), officialDate=g.get("officialDate"), doubleHeader=g.get("doubleHeader"),
                           gameNumber=g.get("gameNumber"), state=st.get("abstractGameState"), detailed=st.get("detailedState"),
                           homeId=t.get("home", {}).get("team", {}).get("id"), awayId=t.get("away", {}).get("team", {}).get("id"),
                           homeName=t.get("home", {}).get("team", {}).get("name"), awayName=t.get("away", {}).get("team", {}).get("name"),
                           homeRuns=t.get("home", {}).get("score"), awayRuns=t.get("away", {}).get("score"),
                           scheduledInnings=g.get("scheduledInnings"))
                old = rows.get(rec["gamePk"])
                fin = rec["state"] == "Final" and rec["homeRuns"] is not None
                if old is None or (fin and not (old["state"] == "Final" and old["homeRuns"] is not None)) or \
                        (fin and old["state"] == "Final" and (rec["officialDate"] or "") >= (old["officialDate"] or "")):
                    rows[rec["gamePk"]] = rec
    df = pd.DataFrame(list(rows.values()))
    return df, hashes


def load_boxscore_runs(root):
    out, hashes = {}, {}
    for f in sorted(glob.glob(os.path.join(root, "data/research_cache/batting_backtest/*/boxscores.jsonl.gz"))):
        hashes[os.path.relpath(f, root)] = sha256_file(f)
        with gzip.open(f, "rt") as fh:
            for line in fh:
                r = json.loads(line)
                out[int(r["gamePk"])] = (r["homeBatting"].get("runs"), r["awayBatting"].get("runs"))
    return out, hashes


# ----------------------------------------------------------------------------- edgelab tables
OBS_COLS = ["marketTicker", "eventTicker", "gameId", "mlbGameId", "marketFamily", "marketHorizon", "checkpoint", "capturedAt", "scheduledStart",
            "yesBid", "yesAsk", "noBid", "noAsk", "lastPrice", "volume", "openInterest", "threshold", "comparisonOperator", "team", "homeTeam", "awayTeam",
            "isValidPregameObservation", "isClosingCandidate", "marketStatus", "title", "player", "seriesTicker", "lineupConfirmationState"]


def load_obs(root):
    recs, hashes = [], {}
    pat = os.path.join(root, "data/edgelab/observations/*.jsonl*")
    for f in sorted(glob.glob(pat)):
        hashes[os.path.relpath(f, root)] = sha256_file(f)
        with opener(f) as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    recs.append([r.get(c) for c in OBS_COLS])
    df = pd.DataFrame(recs, columns=OBS_COLS)
    df["t_cap"] = pd.to_datetime(df["capturedAt"], utc=True, errors="coerce")
    df["t_start"] = pd.to_datetime(df["scheduledStart"], utc=True, errors="coerce")
    return df, hashes


def load_settlements(root):
    rows, hashes = [], {}
    for f in sorted(glob.glob(os.path.join(root, "data/edgelab/settlements/*.jsonl*"))):
        hashes[os.path.relpath(f, root)] = sha256_file(f)
        with opener(f) as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    ev = r.get("settlementEvidence") or {}
                    rows.append(dict(marketTicker=r["marketTicker"], gameId=r.get("gameId"), family=r.get("marketFamily"), status=r["settlementStatus"],
                                     result=r.get("result"), outcome=r.get("outcome"), settledAt=r.get("settledAt"), updatedAt=r.get("updatedAt"),
                                     source=r.get("settlementSource"), evSource=ev.get("sourceSystem"), officialKalshi=ev.get("kalshiOfficialResult"),
                                     gamePk=ev.get("gamePk"), gameStatus=ev.get("gameStatus"), file=os.path.basename(f), unavailable=r.get("unavailableReason")))
    return pd.DataFrame(rows), hashes


EVAL_COLS = ["modelEvaluationId", "marketTicker", "eventTicker", "gameId", "marketFamily", "selection", "threshold", "evaluationStatus", "checkpoint",
             "modelFairProbability", "marketImpliedProbability", "pipelineRunId", "runId", "createdAt", "source", "artifactSource", "lineupConfirmationState",
             "dataQuality", "modelCommitSha", "modelSource", "inputFreshnessNote", "seriesTicker", "side"]


def load_evals(root):
    recs, hashes = [], {}
    for f in sorted(glob.glob(os.path.join(root, "data/edgelab/model_evaluations/*.jsonl*"))):
        hashes[os.path.relpath(f, root)] = sha256_file(f)
        with opener(f) as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    recs.append([r.get(c) for c in EVAL_COLS] + [(r.get("provenance") or {}).get("capturedAt")])
    return pd.DataFrame(recs, columns=EVAL_COLS + ["provCapturedAt"]), hashes


# ----------------------------------------------------------------------------- pure helpers (unit-tested)
def mid_cents(yes_bid, yes_ask):
    """Quote midpoint in probability units; None when either side missing or crossed. Prices are cents (0-100)."""
    if yes_bid is None or yes_ask is None or (isinstance(yes_bid, float) and np.isnan(yes_bid)) or (isinstance(yes_ask, float) and np.isnan(yes_ask)):
        return None
    if yes_ask < yes_bid:
        return None
    return (yes_bid + yes_ask) / 200.0


def is_time_valid(t_cap, t_decision, t_start):
    """A price/input is usable for a decision at t_decision only if observed at or before the decision and strictly before first pitch."""
    if t_cap is None or t_decision is None or t_start is None:
        return False
    return t_cap <= t_decision < t_start


def derive_binary_outcome(family, ticker_team, home_abbr, away_abbr, home_runs, away_runs, threshold=None, operator="AT_LEAST"):
    """Independent settlement from final full-game runs. Returns 1/0/None (None = cannot derive: unsupported family or missing score).
    game_result: YES iff the ticker team won. game_total: YES iff total >= threshold (AT_LEAST). team_total: ticker team runs >= threshold.
    winning_margin (run line, 'wins by over X'): YES iff ticker team margin >= threshold."""
    if home_runs is None or away_runs is None:
        return None
    hr, ar = float(home_runs), float(away_runs)
    if family == "game_result":
        if hr == ar:
            return None
        if ticker_team == home_abbr:
            return int(hr > ar)
        if ticker_team == away_abbr:
            return int(ar > hr)
        return None
    if threshold is None or operator != "AT_LEAST":
        return None
    if family == "game_total":
        return int(hr + ar >= threshold)
    if family == "team_total":
        r = hr if ticker_team == home_abbr else ar if ticker_team == away_abbr else None
        return None if r is None else int(r >= threshold)
    if family == "winning_margin":
        if ticker_team == home_abbr:
            m = hr - ar
        elif ticker_team == away_abbr:
            m = ar - hr
        else:
            return None
        return int(m >= threshold)
    return None


def dedup_settlements(df):
    """One row per marketTicker. Prefers SETTLED over unresolved, then the latest updatedAt. Returns (deduped, n_conflicts) where a conflict
    is a ticker with >1 SETTLED rows disagreeing on result."""
    d = df.copy()
    d["_s"] = (d["status"] == "SETTLED").astype(int)
    d["_u"] = d["updatedAt"].fillna("")
    sett = d[d["_s"] == 1]
    nres = sett.groupby("marketTicker")["result"].nunique()
    conflicts = int((nres > 1).sum())
    d = d.sort_values(["marketTicker", "_s", "_u"]).drop_duplicates("marketTicker", keep="last")
    return d.drop(columns=["_s", "_u"]), conflicts


def season_split(seasons, train, valid, holdout):
    """Chronological season split: returns index masks for disjoint, strictly ordered season groups. Raises if groups overlap or are not ordered."""
    seasons = np.asarray(seasons)
    tr, va, ho = set(train), set(valid), set(holdout)
    if tr & va or tr & ho or va & ho:
        raise ValueError("overlapping season groups")
    if train and valid and max(train) >= min(valid) or valid and holdout and max(valid) >= min(holdout) or (not valid and train and holdout and max(train) >= min(holdout)):
        raise ValueError("seasons not chronologically ordered")
    return np.isin(seasons, list(tr)), np.isin(seasons, list(va)), np.isin(seasons, list(ho))
