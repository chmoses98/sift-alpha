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


# ----------------------------------------------------------------------------- game identity: Kalshi game code -> gamePk
GC_RE = re.compile(r"^(\d{2}[A-Z]{3}\d{2}\d{4})([A-Z0-9]+?)(?:G(\d))?$")


def game_code(ticker):
    parts = str(ticker).split("-")
    return parts[1] if len(parts) > 1 else None


def build_abbr_map(obs, games):
    """Kalshi team abbreviation -> MLB team id, learned only from observations that carry a numeric gamePk found in the schedule."""
    pk = pd.to_numeric(obs["mlbGameId"].where(obs["mlbGameId"].notna(), obs["gameId"]), errors="coerce")
    k = pd.DataFrame(dict(pk=pk, h=obs["homeTeam"], a=obs["awayTeam"])).dropna().drop_duplicates()
    gi = games.set_index("gamePk")
    k = k[k["pk"].isin(gi.index)]
    ab = {}
    for pkv, h, a in k.itertuples(index=False):
        ab.setdefault(h, set()).add(int(gi.loc[pkv, "homeId"]))
        ab.setdefault(a, set()).add(int(gi.loc[pkv, "awayId"]))
    return {a: sorted(v)[0] for a, v in ab.items() if len(v) == 1}


def gamecode_to_pk(codes, abbr, games):
    """Resolve 'YYMONDDHHMMAWAYHOME[Gn]' (ET local start) against the schedule. Returns dict code->gamePk for codes that resolve uniquely
    (doubleheader G1/G2 resolved by gameNumber). Unresolved codes are simply absent (never guessed)."""
    g = games.copy()
    st = pd.to_datetime(g["gameDate"], utc=True).dt.tz_convert("America/New_York")
    g["dkey"] = st.dt.strftime("%y%b%d").str.upper()
    g["tkey"] = g["dkey"] + st.dt.strftime("%H%M")
    by_t, by_d = {}, {}
    for r in g.itertuples():
        by_t.setdefault((r.tkey, r.awayId, r.homeId), []).append(r.gamePk)
        by_d.setdefault((r.dkey, r.awayId, r.homeId), []).append((r.gameNumber or 1, r.gamePk))
    out = {}
    abl = sorted(abbr, key=len, reverse=True)
    for gc in set(c for c in codes if c):
        m = GC_RE.match(gc)
        if not m:
            continue
        tkey, teams, dh = m.group(1), m.group(2), m.group(3)
        for a in abl:
            if teams.startswith(a) and teams[len(a):] in abbr:
                aid, hid = abbr[a], abbr[teams[len(a):]]
                v = by_t.get((tkey, aid, hid))
                if v and len(v) == 1:
                    out[gc] = v[0]
                elif dh:
                    w = [pk for n, pk in by_d.get((tkey[:7], aid, hid), []) if int(n) == int(dh)]
                    if len(w) == 1:
                        out[gc] = w[0]
                break
    return out


def attach_gamepk(obs, games):
    """Adds columns pk (float gamePk or NaN), pk_src in {'row','gamecode_peer','schedule_match',None}. Row-level id first, then any peer row with the
    same Kalshi game code, then ET-time schedule match."""
    o = obs.copy()
    o["pk"] = pd.to_numeric(o["mlbGameId"].where(o["mlbGameId"].notna(), o["gameId"]), errors="coerce")
    o["gc"] = o["marketTicker"].map(game_code)
    o["pk_src"] = np.where(o["pk"].notna(), "row", None)
    peer = o.dropna(subset=["pk"]).groupby("gc")["pk"].first()
    m = o["pk"].isna()
    if m.any():       # guard + explicit float cast: newer pandas rejects assigning an empty/object-typed mapped column into float64
        o.loc[m, "pk"] = pd.to_numeric(o.loc[m, "gc"].map(peer), errors="coerce").astype(float)
        o.loc[m & o["pk"].notna(), "pk_src"] = "gamecode_peer"
    m = o["pk"].isna()
    if m.any():
        ab = build_abbr_map(o, games)
        res = gamecode_to_pk(o.loc[m, "gc"].unique(), ab, games)
        o.loc[m, "pk"] = pd.to_numeric(o.loc[m, "gc"].map(res), errors="coerce").astype(float)
        o.loc[m & o["pk"].notna(), "pk_src"] = "schedule_match"
    return o


# ----------------------------------------------------------------------------- panel: pregame price observations joined to settlement
SERIES_FAMILY = {  # Kalshi series -> (family key, horizon). Resolved from the series ticker, not the (sometimes None) marketHorizon.
    "KXMLBGAME": ("moneyline", "FULL"), "KXMLBF3": ("f3_result", "F3"), "KXMLBF5": ("f5_result", "F5"), "KXMLBF7": ("f7_result", "F7"),
    "KXMLBSPREAD": ("run_line", "FULL"), "KXMLBTOTAL": ("game_total", "FULL"), "KXMLBTEAMTOTAL": ("team_total", "FULL"),
    "KXMLBF5TOTAL": ("f5_total", "F5"), "KXMLBF3TOTAL": ("f3_total", "F3"), "KXMLBF7TOTAL": ("f7_total", "F7"),
    "KXMLBF5SPREAD": ("f5_run_line", "F5"), "KXMLBF3SPREAD": ("f3_run_line", "F3"), "KXMLBF7SPREAD": ("f7_run_line", "F7"),
    "KXMLBRFI": ("nrfi_yrfi", "F1"), "KXMLBKS": ("pitcher_strikeouts", "FULL"), "KXMLBOUTS": ("pitcher_outs", "FULL"),
    "KXMLBHIT": ("hitter_hits", "FULL"), "KXMLBTB": ("hitter_total_bases", "FULL"), "KXMLBHRR": ("hitter_hits_runs_rbis", "FULL"),
    "KXMLBRBI": ("hitter_rbis", "FULL"), "KXMLBSB": ("hitter_stolen_bases", "FULL"),
}


def series_of(ticker):
    return str(ticker).split("-")[0]


def family_of(ticker, market_family=None):
    s = series_of(ticker)
    if s in SERIES_FAMILY:
        return SERIES_FAMILY[s][0]
    return "other:" + (str(market_family) if market_family else s)


def ticker_start_utc(gc):
    m = re.match(r"^(\d{2})([A-Z]{3})(\d{2})(\d{2})(\d{2})", gc or "")
    if not m:
        return pd.NaT
    try:
        return pd.Timestamp(f"20{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}:{m.group(5)}", tz="America/New_York").tz_convert("UTC")
    except Exception:
        return pd.NaT


def build_panel(obs, games):
    """Pregame, two-sided-quote observations only. t_first_pitch = MIN over every known start (obs scheduledStart, schedule gameDate, ticker ET time)
    so a postponement/reschedule can only make an observation *less* eligible. Pregame = t_cap < t_first_pitch. Duplicate (ticker, capturedAt) dropped."""
    o = attach_gamepk(obs, games)
    gi = games.set_index("gamePk")
    o["t_sched"] = pd.to_datetime(gi["gameDate"].reindex(o["pk"]).values, utc=True)
    gcs = o["gc"].dropna().unique()
    tk = {c: ticker_start_utc(c) for c in gcs}
    o["t_tick"] = pd.to_datetime(o["gc"].map(tk), utc=True)
    o["t_fp"] = o[["t_start", "t_sched", "t_tick"]].min(axis=1)
    o["season"] = o["t_cap"].dt.year
    o["series"] = o["marketTicker"].map(series_of)
    o["family"] = [family_of(t, f) for t, f in zip(o["marketTicker"], o["marketFamily"])]
    o["mins_before"] = (o["t_fp"] - o["t_cap"]).dt.total_seconds() / 60.0
    o = o.drop_duplicates(["marketTicker", "capturedAt"])
    return o


def pregame_quotes(panel, max_spread=0.10):
    p = panel[(panel["mins_before"] > 0)].copy()
    yb, ya = p["yesBid"].astype(float), p["yesAsk"].astype(float)
    ok = yb.notna() & ya.notna() & (ya >= yb) & (ya > 0)
    p = p[ok].copy()
    p["mid"] = (p["yesBid"].astype(float) + p["yesAsk"].astype(float)) / 200.0
    p["spread"] = (p["yesAsk"].astype(float) - p["yesBid"].astype(float)) / 100.0
    p["two_sided_ok"] = p["spread"] <= max_spread
    return p


def parse_suffix(ticker):
    """Kalshi ticker 'SERIES-GAMECODE-SUFFIX' -> (team or None, n or None). TOTAL: ('',N). TEAMTOTAL/SPREAD: ('PIT',8). GAME/F-series: ('LAD',None)."""
    p = str(ticker).split("-")
    if len(p) < 3:
        return None, None
    suf = p[2]
    if suf.isdigit():
        return None, int(suf)
    m = re.match(r"^([A-Z]+?)(\d+)$", suf)
    if m and series_of(ticker) in ("KXMLBTEAMTOTAL", "KXMLBSPREAD", "KXMLBF5SPREAD", "KXMLBF3SPREAD", "KXMLBF7SPREAD"):
        return m.group(1), int(m.group(2))
    return suf, None


FULLGAME_FAMILY = {"moneyline": "game_result", "game_total": "game_total", "team_total": "team_total", "run_line": "winning_margin"}


def derive_from_ticker(ticker, family, home_abbr, away_abbr, home_runs, away_runs):
    """Independent settlement of one full-game contract from final runs. Uses ticker suffix N: YES iff stat >= N (Kalshi ladder rule)."""
    if family not in FULLGAME_FAMILY:
        return None
    team, n = parse_suffix(ticker)
    if family == "moneyline":
        return derive_binary_outcome("game_result", team, home_abbr, away_abbr, home_runs, away_runs)
    if n is None:
        return None
    return derive_binary_outcome(FULLGAME_FAMILY[family], team, home_abbr, away_abbr, home_runs, away_runs, threshold=n)


# ----------------------------------------------------------------------------- outcomes with the total-ladder boundary correction
TOTAL_FIX_DATE = "2026-09-01"  # first game date whose stored game_total settlements follow Kalshi's '>= N' rule (empirically verified, see audit)
TOTAL_FAMILIES = ("game_total", "f3_total", "f5_total", "f7_total")


def pin_team_runs(panel, y_by_ticker):
    """Exact team runs per (gamePk, team) from settled team_total ladders: runs = max N with YES, valid only when N+1 settled NO and every lower rung YES /
    every higher rung NO. Team-total settlements were verified 100% against final scores, so this reproduces game totals in games the schedule lacks."""
    T = panel.drop_duplicates("marketTicker")
    T = T[T["family"] == "team_total"][["marketTicker", "pk"]].copy()
    T["y"] = T["marketTicker"].map(y_by_ticker)
    T["team"] = [parse_suffix(t)[0] for t in T["marketTicker"]]
    T["n"] = [parse_suffix(t)[1] for t in T["marketTicker"]]
    T = T.dropna(subset=["y", "pk", "n"])
    pins = {}
    for (pk, tm), g in T.groupby(["pk", "team"]):
        ys = g.set_index("n")["y"].sort_index()
        if (ys == 1).any() and (ys == 0).any():
            hi, lo = ys[ys == 1].index.max(), ys[ys == 0].index.min()
            if lo == hi + 1 and (ys[ys.index <= hi] == 1).all() and (ys[ys.index >= lo] == 0).all():
                pins[(pk, tm)] = int(hi)
    return pins


def build_outcomes(panel, games, settle):
    """Returns DataFrame indexed by marketTicker: y (0/1/NaN), y_src, y_edgelab, flags. Policy:
      * edgelab SETTLED YES/NO is the base outcome (Kalshi's official result is NOT archived: kalshiOfficialResult is null on every row);
      * game_total with game date < TOTAL_FIX_DATE: stored result used strict '>' at total == N, so it is RE-DERIVED from final runs (schedule, else
        team-total pins) with '>= N'; if no total is derivable the contract is DROPPED (y NaN, y_src='dropped_total_boundary_unverifiable');
      * f3/f5/f7 totals before the fix date: same defect, no period scores archived -> DROPPED;
      * full-game moneyline/run line/team total: independent derivation from schedule runs compared, stored value kept (it agrees 100%)."""
    sd, _ = dedup_settlements(settle)
    base = sd[sd["status"] == "SETTLED"].set_index("marketTicker")["result"].map({"YES": 1, "NO": 0})
    T = panel.drop_duplicates("marketTicker")[["marketTicker", "family", "pk", "homeTeam", "awayTeam", "t_fp"]].set_index("marketTicker")
    T["y_edgelab"] = base.reindex(T.index)
    gi = games.set_index("gamePk")
    final = (gi["state"] == "Final")
    T["hr"] = gi["homeRuns"].where(final).reindex(T["pk"]).values  # runs only from FINAL schedule records (cache snapshots of live games carry 0-0)
    T["ar"] = gi["awayRuns"].where(final).reindex(T["pk"]).values
    pins = pin_team_runs(panel, base.to_dict())
    T["gdate"] = T["t_fp"].dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    T["y"] = T["y_edgelab"]
    T["y_src"] = np.where(T["y_edgelab"].notna(), "edgelab_settlement(MLB_STATS_API)", None)
    T["y_indep"] = np.nan
    for t, r in zip(T.index, T.itertuples()):
        if r.family in FULLGAME_FAMILY and pd.notna(r.hr) and pd.notna(r.ar):
            d = derive_from_ticker(t, r.family, r.homeTeam, r.awayTeam, r.hr, r.ar)
            if d is not None:
                T.at[t, "y_indep"] = d
    pre_fix = T["gdate"] < TOTAL_FIX_DATE
    for t in T.index[(T["family"] == "game_total") & pre_fix & T["y_edgelab"].notna()]:
        r = T.loc[t]
        n = parse_suffix(t)[1]
        tot = None
        if pd.notna(r.hr) and pd.notna(r.ar):
            tot = r.hr + r.ar
        else:
            h, a = pins.get((r.pk, r.homeTeam)), pins.get((r.pk, r.awayTeam))
            tot = None if h is None or a is None else h + a
        if tot is None or n is None:
            T.at[t, "y"], T.at[t, "y_src"] = np.nan, "dropped_total_boundary_unverifiable"
        else:
            T.at[t, "y"], T.at[t, "y_src"] = float(tot >= n), "rederived_ge_N(schedule_or_team_total_pins)"
            T.at[t, "y_indep"] = float(tot >= n)
    for t in T.index[T["family"].isin(["f3_total", "f5_total", "f7_total"]) & pre_fix & T["y_edgelab"].notna()]:
        T.at[t, "y"], T.at[t, "y_src"] = np.nan, "dropped_total_boundary_unverifiable"
    return T
