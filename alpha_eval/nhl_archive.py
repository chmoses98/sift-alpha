"""READ-ONLY NHL adapter: ``NHL-edge-finder@data-archive`` frozen forecasts -> ``sift-alpha-eval/1`` rows (RESEARCH_ONLY).

Sources (local copies only; no network inside a run; nothing in the producer is imported or modified):
* forecasts: ``predictions`` (DATA_ONLY_V1, game families), ``predictions_v2`` (DATA_ONLY_V2, game + period families),
  ``predictions_player`` (PLAYER_SIM_V1, player props / first goal / goalie saves), ``predictions_oa`` (OA_RIDGE_V1 arms; moneyline
  and the two main totals). All four are declared sports-only by the producer (``docs/ARCHITECTURE.md``: DATA_ONLY "never sees a
  price"); the ``MARKET_ANCHORED_*`` columns are market-informed and are NOT evaluated here.
* freeze attestation: the git history of the archive branch. Every forecast file must be (a) added in exactly one commit whose
  subject names the same GitHub run id as the file name, (b) never modified or deleted afterwards, and (c) committed before the
  event's start (official NHL ``startTimeUTC``). A file that fails any check is demoted to BACKTEST. Like the NBA hash chain, the
  commit chain is tamper-evident but its clock is the producer's runner clock.
* outcomes: the OFFICIAL NHL public API (boxscore + play-by-play, fetched by ``scripts/fetch_nhl_api_outcomes.py`` into a local
  cache) -> the existing independent derivation ``research/outcome_intel/nhl_audit.derive_outcome``. Cross-checks, each from a
  different artefact: (1) the same derivation on the producer's archived ``results``/``player_events``; (2) the producer's separately
  implemented settle engine (``settlements``). Any disagreement adds a conflicting outcome row, which the standard BLOCKS. A spread/
  total whose result depends on whether the shootout goal counts (``SO_AMBIGUOUS``: Kalshi rules text is silent) gets both rows and
  is blocked. Kalshi's own ``result`` is not in the archive.
* quotes: replay of the archived Kalshi board (full checkpoints + hash-chained deltas, ``research/outcome_intel/nba_nhl_common``):
  the quote on the latest board at or before each forecast's freeze, and the last pregame board (closing quote).
* identity: every ticker's ET date / away / home is checked against the official game record; player tickers additionally against the
  player's team and sweater number in the official box score. A mismatch stamps the outcome ``event_id`` so the join blocks it.

Selection (prespecified): per (model, ticker) the LAST attested pregame capture is the frozen forecast that is graded. Earlier hourly
captures are counted, not graded (repeat captures of one market are not independent evidence).
"""
from __future__ import annotations

import glob
import gzip
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from .schema import BACKTEST, LADDER_RUNG, MAIN, PROSPECTIVE, SCHEMA_VERSION, SPORTS_ONLY

_RES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research", "outcome_intel")
if _RES not in sys.path:
    sys.path.insert(0, _RES)
import nba_nhl_common as C  # noqa: E402  (Alpha's own board replay; reused, not re-implemented)
from nhl_audit import derive_outcome  # noqa: E402  (Alpha's own independent NHL outcome derivation; reused)

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = timezone(timedelta(hours=-5))

# NHL API abbreviation -> Kalshi ticker code (only those that differ). Verified empirically by the identity check (a wrong map fails it).
KALSHI_CODE = {"LAK": "LA", "NJD": "NJ", "SJS": "SJ", "TBL": "TB"}
STREAMS = (  # (subdir, model_id, probability field)
    ("predictions", "DATA_ONLY_V1", "p_data_only"),
    ("predictions_v2", "DATA_ONLY_V2", "p_data_only_v2"),
    ("predictions_player", "PLAYER_SIM_V1", "p_player"),
)
OA_SUBDIR = "predictions_oa"
GAME_FAMS = ("game_winner", "game_spread", "game_total", "team_total")
PERIOD_FAMS = ("period_winner", "period_spread", "period_total")
PLAYER_FAMS = ("player_goals", "player_assists", "player_points", "first_goal", "goalie_saves")
LADDER_FAMS = {"game_spread", "game_total", "team_total", "period_spread", "period_total", "player_goals", "player_assists",
               "player_points", "goalie_saves"}
_TICK = re.compile(r"^(?P<series>[A-Z0-9]+)-(?P<yy>\d\d)(?P<mon>[A-Z]{3})(?P<dd>\d\d)(?P<teams>[A-Z]+)(?:-(?P<rest>.+))?$")
_MON = dict(JAN=1, FEB=2, MAR=3, APR=4, MAY=5, JUN=6, JUL=7, AUG=8, SEP=9, OCT=10, NOV=11, DEC=12)
_RUN = re.compile(r"_(\d{8}T\d{6}Z)_(\d+)\.jsonl\.gz$")


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dt(s) -> Optional[datetime]:
    return None if not s else datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)


def _read(root, pat):
    for f in sorted(glob.glob(os.path.join(root, pat))):
        with gzip.open(f, "rt") as fh:
            for line in fh:
                if line.strip():
                    yield f, json.loads(line)


def parse_ticker(t: str) -> Optional[dict]:
    """KXNHLGAME-26NOV12NYILA-LA -> {series, date (ET iso), teams ('NYILA'), rest}. None if not game-bound."""
    m = _TICK.match(t)
    if not m or m["mon"] not in _MON:
        return None
    try:
        d = datetime(2000 + int(m["yy"]), _MON[m["mon"]], int(m["dd"])).date().isoformat()
    except ValueError:
        return None
    return dict(series=m["series"], date=d, teams=m["teams"], rest=m["rest"] or "")


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper())


# ----------------------------------------------------------------------------- freeze attestation (git history)
def parse_git_log(text: str) -> dict:
    """Parse ``git log --no-renames --format='C %H %cI %aI %s' --name-status <ref> -- <prediction dirs>`` output.
    -> {path: dict(commit, committed_at, subject_run, n_added, n_modified, n_deleted)}."""
    out, cur = {}, None
    for line in text.splitlines():
        if line.startswith("C "):
            parts = line.split(" ", 4)
            m = re.search(r"capture: (\d+)", parts[4] if len(parts) > 4 else "")
            cur = dict(commit=parts[1], committed_at=parts[2], subject_run=m.group(1) if m else None)
        elif line[:2] in ("A\t", "M\t", "D\t") and cur:
            st, p = line.split("\t", 1)
            e = out.setdefault(p, dict(n_added=0, n_modified=0, n_deleted=0))
            e[{"A": "n_added", "M": "n_modified", "D": "n_deleted"}[st]] += 1
            if st == "A":
                e.update(commit=cur["commit"], committed_at=cur["committed_at"], subject_run=cur["subject_run"])
    return out


def attest(relpath: str, log: dict, event_start: datetime) -> str:
    """-> ATTESTED | NOT_IN_HISTORY | MODIFIED_OR_DELETED | RUN_ID_MISMATCH | COMMITTED_AT_OR_AFTER_START."""
    e = log.get(relpath)
    if e is None or not e.get("commit"):
        return "NOT_IN_HISTORY"
    if e["n_added"] != 1 or e["n_modified"] or e["n_deleted"]:
        return "MODIFIED_OR_DELETED"
    m = _RUN.search(relpath)
    if not m or m.group(2) != e["subject_run"]:
        return "RUN_ID_MISMATCH"
    if _dt(e["committed_at"]) >= event_start:
        return "COMMITTED_AT_OR_AFTER_START"
    return "ATTESTED"


# ----------------------------------------------------------------------------- official NHL API (independent outcome source)
def _toi(s) -> int:
    if not s:
        return 0
    m, sec = str(s).split(":")
    return int(m) * 60 + int(sec)


def load_nhl_api(cache_dir: str) -> dict:
    """{game_id: dict(game, res, goals, players, goalies, fetched_at)} from cached boxscore + play-by-play JSON."""
    out = {}
    for bp in sorted(glob.glob(os.path.join(cache_dir, "*_boxscore.json"))):
        gid = os.path.basename(bp).split("_")[0]
        pp = os.path.join(cache_dir, f"{gid}_play-by-play.json")
        b = json.load(open(bp))
        p = json.load(open(pp)) if os.path.exists(pp) else None
        home, away = b["homeTeam"], b["awayTeam"]
        start = _dt(b["startTimeUTC"])
        game = dict(game_id=gid, start=_iso(start), date=start.astimezone(ET).date().isoformat(), home=home["abbrev"],
                    away=away["abbrev"], home_id=home["id"], away_id=away["id"], state=b.get("gameState"),
                    game_type=b.get("gameType"))
        fin = b.get("gameState") in ("OFF", "FINAL")
        lpt = (b.get("gameOutcome") or {}).get("lastPeriodType") or (b.get("periodDescriptor") or {}).get("periodType")
        res = dict(game_id=gid, status="final" if fin else "not_final", home_team_id=home["id"], away_team_id=away["id"],
                   home_final=home.get("score"), away_final=away.get("score"), last_period_type=lpt)
        players, goalies, roster = {}, {}, {}
        for side, team in (("homeTeam", home), ("awayTeam", away)):
            st = (b.get("playerByGameStats") or {}).get(side) or {}
            for grp in ("forwards", "defense"):
                for r in st.get(grp, []):
                    players[(gid, int(r["playerId"]))] = dict(goals=r.get("goals", 0), assists=r.get("assists", 0),
                                                              points=r.get("points", 0), toi_s=_toi(r.get("toi")))
                    roster[int(r["playerId"])] = (team["abbrev"], r.get("sweaterNumber"), (r.get("name") or {}).get("default", ""))
            for r in st.get("goalies", []):
                goalies[(gid, int(r["playerId"]))] = dict(saves=r.get("saves", 0), toi_s=_toi(r.get("toi")))
                roster[int(r["playerId"])] = (team["abbrev"], r.get("sweaterNumber"), (r.get("name") or {}).get("default", ""))
        goals = None
        if p is not None:
            goals = []
            for pl in p.get("plays", []):
                pd = pl.get("periodDescriptor") or {}
                if pl.get("typeDescKey") != "goal" or pd.get("periodType") == "SO":
                    continue
                d = pl.get("details") or {}
                goals.append(dict(period=int(pd["number"]), t_s=_toi(pl.get("timeInPeriod")), team_id=d.get("eventOwnerTeamId"),
                                  scorer_id=d.get("scoringPlayerId")))
        out[gid] = dict(game=game, res=res, goals=goals, players=players, goalies=goalies, roster=roster,
                        fetched_at=_iso(datetime.fromtimestamp(os.path.getmtime(bp), timezone.utc)))
    return out


def check_identity(ticker: str, game: Optional[dict], player: Optional[tuple] = None) -> str:
    """-> IDENTITY_VERIFIED | IDENTITY_UNVERIFIABLE_NO_GAME_RECORD | IDENTITY_UNPARSEABLE_TICKER | MISMATCH_DATE | MISMATCH_TEAMS |
    MISMATCH_PLAYER (team code / sweater / surname) | PLAYER_NOT_IN_OFFICIAL_BOX (unverifiable, not a mismatch)."""
    t = parse_ticker(ticker)
    if t is None:
        return "IDENTITY_UNPARSEABLE_TICKER"
    if game is None:
        return "IDENTITY_UNVERIFIABLE_NO_GAME_RECORD"
    k = lambda a: KALSHI_CODE.get(a, a)  # noqa: E731
    if t["teams"] != k(game["away"]) + k(game["home"]):
        return "MISMATCH_TEAMS"
    if t["date"] != game["date"]:
        return "MISMATCH_DATE"
    if player is not None:
        if player == "ABSENT":
            return "PLAYER_NOT_IN_OFFICIAL_BOX"
        team, sweater, name = player
        code = t["rest"].split("-")[0]
        tc = k(team)
        m = re.match(r"^([A-Z]+?)(\d+)$", code)
        if not code.startswith(tc) or not m or str(sweater) != m.group(2):
            return "MISMATCH_PLAYER"
        surname = _norm(name.split(".", 1)[-1] if "." in name else name.split(" ")[-1])
        if surname and surname[:4] not in _norm(code[len(tc):]):
            return "MISMATCH_PLAYER"
    return "IDENTITY_VERIFIED"


def resolve_player(ticker: str, game: dict, roster: dict) -> Optional[int]:
    """Independent player resolution: ticker player code (Kalshi team code + name letters + sweater) -> the official box-score player
    with that team and sweater whose surname matches. None if no unique match (player absent from the box, or ambiguous)."""
    t = parse_ticker(ticker)
    if t is None:
        return None
    code = t["rest"].split("-")[0]
    m = re.match(r"^([A-Z]+?)(\d+)$", code)
    if not m:
        return None
    k = lambda a: KALSHI_CODE.get(a, a)  # noqa: E731
    hits = [pid for pid, (team, sw, name) in roster.items()
            if code.startswith(k(team)) and str(sw) == m.group(2)
            and _norm(name.split(".", 1)[-1] if "." in name else name.split(" ")[-1])[:4] in _norm(code[len(k(team)):])]
    return hits[0] if len(hits) == 1 else None


# ----------------------------------------------------------------------------- producer archive (cross-check inputs)
def load_contracts(root: str) -> dict:
    cs = {}
    for _, r in _read(root, "contracts/dt=*/*.jsonl.gz"):
        cs.setdefault(r["ticker"], r)
    return cs


def load_producer_outcomes(root: str):
    res = {}
    for _, r in _read(root, "results/dt=*/*.jsonl.gz"):
        g = str(r["game_id"])
        if g not in res or r["fetched_at_utc"] >= res[g]["fetched_at_utc"]:
            res[g] = r
    goals = defaultdict(list)
    for _, r in _read(root, "player_events/goals/dt=*/*.jsonl.gz"):
        if r.get("period_type") != "SO":
            goals[str(r["game_id"])].append(r)
    players, goalies = {}, {}
    for _, r in _read(root, "player_events/players/dt=*/*.jsonl.gz"):
        players[(str(r["game_id"]), int(r["player_id"]))] = r
    for _, r in _read(root, "player_events/goalies/dt=*/*.jsonl.gz"):
        goalies[(str(r["game_id"]), int(r["player_id"]))] = r
    sett = {}
    for _, r in _read(root, "settlements/dt=*/*.jsonl.gz"):
        if r["ticker"] not in sett or r["settled_at_utc"] >= sett[r["ticker"]]["settled_at_utc"]:
            sett[r["ticker"]] = r
    return dict(results=res, goals=dict(goals), players=players, goalies=goalies, settlements=sett)


def _contract_for_derive(c: dict, ticker: str) -> dict:
    d = dict(c)
    d["ticker"] = ticker
    return d


def _y(o):
    return {"YES": 1, "NO": 0}.get(o)


def outcome_rows(ticker: str, c: dict, gid: str, api: dict, prod: Optional[dict], ident: str, xcheck: Counter) -> list:
    """Outcome rows for one market (empty = no outcome yet / not derivable; counted by the caller)."""
    g = api.get(gid)
    if g is None:
        xcheck["NO_OFFICIAL_RECORD"] += 1
        return []
    pid = c.get("player_id")
    pid = None if pid is None or (isinstance(pid, float) and pid != pid) else int(pid)
    o, v = derive_outcome(_contract_for_derive(c, ticker), g["res"], g["goals"], g["players"], g["goalies"], pid)
    if o is None:
        xcheck["NOT_DERIVABLE_OFFICIAL" if g["res"]["status"] == "final" else "NOT_FINAL_OFFICIAL"] += 1
        return []
    ev = gid + ("#TICKER_IDENTITY_MISMATCH" if ident.startswith("MISMATCH") else "")
    base = dict(schema=SCHEMA_VERSION, market_id=ticker, event_id=ev, source="sports", observed_at=g["fetched_at"])
    if o == "VOID":
        xcheck["VOID_PLAYER_DID_NOT_PLAY"] += 1
        return [dict(base, state="void", value=None)]
    if o == "SO_AMBIGUOUS":
        xcheck["SO_AMBIGUOUS_BLOCKED"] += 1
        return [dict(base, state="final", value=1), dict(base, state="final", value=0)]
    y = _y(o)
    rows = [dict(base, state="final", value=y)]
    if prod is not None:
        pr = prod["results"].get(gid)
        po, _ = derive_outcome(_contract_for_derive(c, ticker), pr, prod["goals"].get(gid), prod["players"], prod["goalies"], pid) if pr else (None, None)
        k = "ARCHIVE_" + ("AGREE" if _y(po) == y else "NOT_DERIVABLE" if _y(po) is None else "DISAGREE")
        xcheck[k] += 1
        if k == "ARCHIVE_DISAGREE":
            rows.append(dict(rows[0], value=1 - y))
        st = prod["settlements"].get(ticker)
        if st is None:
            xcheck["SETTLE_ENGINE_NO_ROW"] += 1
        elif st["outcome"] not in ("YES", "NO"):
            xcheck["SETTLE_ENGINE_UNSETTLEABLE"] += 1
        elif _y(st["outcome"]) == y:
            xcheck["SETTLE_ENGINE_AGREE"] += 1
        else:
            xcheck["SETTLE_ENGINE_DISAGREE"] += 1
            if len(rows) == 1:
                rows.append(dict(rows[0], value=1 - y))
    return rows


# ----------------------------------------------------------------------------- forecasts
def _captures(root: str, sub: str):
    for f, r in _read(root, f"{sub}/dt=*/*.jsonl.gz"):
        yield os.path.relpath(f, root), r


def select_forecasts(root: str, api: dict, log: dict, contracts: dict) -> tuple:
    """-> (candidates {(model, ticker): (pred_row, relpath, attestation)}, counts). Last attested pregame capture per (model, ticker);
    if no capture is attested, the last pregame capture, demoted to BACKTEST."""
    cnt = Counter()
    best = {}
    seen = defaultdict(set)                                  # ticker -> {"priced", "null"}: evidence for unforecast markets
    for sub, model, pk in STREAMS:
        for rel, r in _captures(root, sub):
            cnt[f"{model}.capture_rows"] += 1
            p = r.get(pk)
            seen[r["ticker"]].add("priced" if p is not None else "null")
            if p is None:
                cnt[f"{model}.null_probability(unpriced/unsupported by producer)"] += 1
                continue
            g = api.get(str(r["game_id"]))
            if g is None:
                cnt[f"{model}.game_not_in_official_cache"] += 1
                continue
            start = _dt(g["game"]["start"])
            pt = _dt(r["predicted_at_utc"])
            if pt >= start:
                cnt[f"{model}.captured_at_or_after_start"] += 1
                continue
            a = attest(rel, log, start)
            cnt[f"{model}.pregame_rows[{a}]"] += 1
            key = (model, r["ticker"])
            cur = best.get(key)
            rank = (a == "ATTESTED", r["predicted_at_utc"])
            if cur is None or rank > cur[3]:
                best[key] = (r, rel, a, rank)
    cnt["_seen"] = seen
    return {k: v[:3] for k, v in best.items()}, cnt


def oa_forecasts(root: str, api: dict, log: dict, contracts: dict) -> tuple:
    """OA arms: P(home win) -> both game_winner tickers; P(total > 5.5 / 6.5) -> the matching game_total tickers."""
    by_game = defaultdict(list)
    for t, c in contracts.items():
        if c.get("family") in ("game_winner", "game_total"):
            by_game[str(c["game_id"])].append((t, c))
    best, cnt = {}, Counter()
    for rel, r in _captures(root, OA_SUBDIR):
        cnt["OA.capture_rows"] += 1
        g = api.get(str(r["game_id"]))
        if g is None:
            cnt["OA.game_not_in_official_cache"] += 1
            continue
        start = _dt(g["game"]["start"])
        if _dt(r["predicted_at_utc"]) >= start:
            cnt["OA.captured_at_or_after_start"] += 1
            continue
        a = attest(rel, log, start)
        cnt[f"OA.pregame_rows[{a}]"] += 1
        for t, c in by_game.get(str(r["game_id"]), ()):
            if c["family"] == "game_winner":
                if c.get("team_id") == r["home_team_id"]:
                    p = r["p_home_win"]
                elif c.get("team_id") == r["away_team_id"]:
                    p = 1 - r["p_home_win"]
                else:
                    continue
            else:
                p = r.get(f"p_over_{c.get('threshold')}")
                if p is None:
                    continue
            key = (f"{r['model_version']}:{r['arm']}", t)
            rank = (a == "ATTESTED", r["predicted_at_utc"])
            if key not in best or rank > best[key][3]:
                best[key] = (dict(r, ticker=t, family=c["family"], _p=p), rel, a, rank)
    return {k: v[:3] for k, v in best.items()}, cnt


def build(root: str, api_cache: str, git_log_text: str, *, cross_check: bool = True) -> dict:
    api = load_nhl_api(api_cache)
    log = parse_git_log(git_log_text)
    contracts = load_contracts(root)
    prod = load_producer_outcomes(root) if cross_check else None
    sel, cnt = select_forecasts(root, api, log, contracts)
    seen = cnt.pop("_seen")
    oa, cnt_oa = oa_forecasts(root, api, log, contracts)
    cnt.update(cnt_oa)
    sel.update(oa)
    forecasts, outcomes, done, xcheck, ident_c, quote_lookups = [], [], set(), Counter(), Counter(), []
    for (model, t), (r, rel, a) in sorted(sel.items()):
        gid = str(r["game_id"])
        g = api[gid]
        c = contracts.get(t)
        if c is None:
            cnt["no_contract_definition"] += 1
            continue
        fam = c["family"]
        p = r["_p"] if "_p" in r else r[{"DATA_ONLY_V1": "p_data_only", "DATA_ONLY_V2": "p_data_only_v2", "PLAYER_SIM_V1": "p_player"}[model]]
        p = min(max(float(p), 1e-6), 1 - 1e-6)
        start = g["game"]["start"]
        ec = PROSPECTIVE if a == "ATTESTED" else BACKTEST
        cnt[f"selected[{model}][{ec}]"] += 1
        fid = f"{t}|{r['predicted_at_utc']}|{model}"
        forecasts.append(dict(
            schema=SCHEMA_VERSION, forecast_id=fid, sport="NHL", event_id=gid, group_id=gid, market_id=t, native_family=fam,
            model_id=model.split(":")[0], model_version=model, model_independence=SPORTS_ONLY, market_inputs_used=[],
            frozen_at=_iso(_dt(r["predicted_at_utc"])), event_start=start, evidence_class=ec, scoring_type="BINARY", payload=dict(p_yes=p),
            line=c.get("threshold"), line_role=LADDER_RUNG if fam in LADDER_FAMS else MAIN,
            meta=dict(archive_file=rel, freeze_attestation=a, commit=(log.get(rel) or {}).get("commit"),
                      committed_at=(log.get(rel) or {}).get("committed_at"), horizon_label=r.get("horizon_label"),
                      embedded_quote=dict(observed=r.get("market_observed_at_utc"), yes_bid=r.get("market_yes_bid"), yes_ask=r.get("market_yes_ask")))))
        quote_lookups.append((t, C.ts(forecasts[-1]["frozen_at"]), ("pit", fid)))
        if t in done:
            continue
        done.add(t)
        quote_lookups.append((t, C.ts(start) - 1, ("close", t)))
        pl = None
        if fam in PLAYER_FAMS:
            # player identity: resolved INDEPENDENTLY from the ticker against the official box; the producer's id is a cross-check
            pp = r.get("player_id")
            pid = resolve_player(t, g["game"], g["roster"])
            if pid is None:
                pl = "ABSENT"
                ident_c["player_resolution[NOT_IN_OFFICIAL_BOX_OR_AMBIGUOUS]"] += 1
                pid = int(pp) if pp is not None else None          # absent from the box -> derive_outcome returns VOID for it
            else:
                pl = g["roster"][pid]
                ident_c["player_resolution[" + ("PRODUCER_ID_AGREES" if pp is not None and int(pp) == pid else
                                                "PRODUCER_ID_MISSING" if pp is None else "PRODUCER_ID_DIFFERS") + "]"] += 1
            if pp is not None and pid is not None and int(pp) != pid:
                pl = ("MISMATCH", None, "")
            c = dict(c, player_id=pid)
        ident = check_identity(t, g["game"], pl)
        ident_c[ident] += 1
        outcomes.extend(outcome_rows(t, c, gid, api, prod, ident, xcheck))
    return dict(forecasts=forecasts, outcomes=outcomes, quote_lookups=quote_lookups, api=api, contracts=contracts, seen=seen,
                info=dict(counts=dict(cnt), outcome_xcheck=dict(xcheck), identity=dict(ident_c),
                          attestation_files=len(log), attestation_modified=sum(1 for e in log.values() if e["n_modified"] or e["n_deleted"])))


def quotes_from_board(root: str, lookups: list) -> tuple:
    """Replay the archived board once; each lookup -> the quote on the latest board at or before its time (two-sided only)."""
    resolved, _, integ = C.board_sweep(root, lookups)
    out, n_emb = {}, Counter()
    for key, v in resolved.items():
        if v["board_t"] is None or not v["slim"]:
            n_emb["no_board_quote"] += 1
            continue
        q = C.quote(v["slim"]) or {}
        st = (v["slim"].get("status") or "active")
        tk = key[1] if key[0] == "close" else key[1].split("|")[0]
        obs = C.iso(v["board_t"])
        if q.get("two_sided") and st in ("active", "open"):
            yb, ya = q["yes_bid"], q["yes_ask"]
            n_emb["two_sided"] += 1
        else:                                   # present on the board but not quotable: emitted so the standard counts it ONE_SIDED
            yb = q.get("yes_bid") if st in ("active", "open") and (q.get("yes_bid") or 0) > 0 else None
            ya = q.get("yes_ask") if st in ("active", "open") and (q.get("yes_ask") or 0) > 0 else None
            if yb is not None and ya is not None:   # crossed / inverted book: never usable as a two-sided quote
                yb = None
            n_emb["one_sided_crossed_or_inactive[" + str(st) + "]"] += 1
        out[(tk, obs)] = dict(schema=SCHEMA_VERSION, market_id=tk, observed_at=obs, yes_bid=yb, yes_ask=ya, source="kalshi_board_replay")
    return list(out.values()), dict(n_emb), integ


def embedded_quote_agreement(forecasts: list, quotes: list) -> dict:
    """Do the quotes embedded in the producer's forecast rows equal the independently replayed board at the same instant?"""
    q = {(r["market_id"], r["observed_at"]): r for r in quotes}
    c = Counter()
    for f in forecasts:
        e = f["meta"].get("embedded_quote") or {}
        if not e.get("observed") or e.get("yes_bid") is None or e.get("yes_ask") is None:
            c["no_embedded_quote"] += 1
            continue
        b = q.get((f["market_id"], _iso(_dt(e["observed"]))))
        if b is None:
            c["no_board_quote_at_same_instant"] += 1
        elif b["yes_bid"] is None or b["yes_ask"] is None:
            c["board_not_two_sided_at_same_instant"] += 1
        elif abs(b["yes_bid"] - e["yes_bid"] / 100) < 1e-9 and abs(b["yes_ask"] - e["yes_ask"] / 100) < 1e-9:
            c["agree"] += 1
        else:
            c["disagree"] += 1
    return dict(c)


# ----------------------------------------------------------------------------- eligible universe (all archived NHL board tickers)
def load_board_universe(root: str) -> dict:
    """Union of every ticker on any full-board checkpoint or added by any chained delta -> {ticker: dict(series, family, support)}."""
    board = {}
    for _, r in _read(root, "kalshi/markets/dt=*/*.jsonl.gz"):
        board.setdefault(r["ticker"], dict(series=r.get("series_ticker") or r["ticker"].split("-")[0], family=r.get("_family") or "unknown",
                                           support=r.get("_support") or "UNKNOWN", status=r.get("status")))
    for f in sorted(glob.glob(os.path.join(root, "kalshi/markets_delta/dt=*/*.json.gz"))):
        with gzip.open(f, "rt") as fh:
            d = json.load(fh)
        for t, r in d.get("added", {}).items():
            board.setdefault(t, dict(series=r.get("series_ticker") or t.split("-")[0], family=r.get("_family") or "unknown",
                                     support=r.get("_support") or "UNKNOWN", status=r.get("status")))
    return board


def classify_universe(board: dict, api: dict, schedule_dates: dict, *, window_start: str, horizon: str) -> dict:
    """Same partition contract as ``nba_universe.classify``: NOT_GAME_BOUND | UNMAPPED_GAME | BEFORE | FUTURE | IN_WINDOW (+game).
    ``schedule_dates``: {(ET date, away code+home code): game_id} for every scheduled game (producer schedule, used only to tell
    a not-yet-played game from an unmapped ticker); in-window games must be in the official cache to be IN_WINDOW."""
    from .nba_universe import BEFORE, FUTURE, NOT_GAME, UNMAPPED
    k = lambda a: KALSHI_CODE.get(a, a)  # noqa: E731
    official = {(g["game"]["date"], k(g["game"]["away"]) + k(g["game"]["home"])): gid for gid, g in api.items()}
    rows = {}
    for t, b in board.items():
        p = parse_ticker(t)
        if p is None:
            rows[t] = dict(b, cls=NOT_GAME, game_id=None, start=None, date=None)
            continue
        key = (p["date"], p["teams"])
        gid = official.get(key)
        if p["date"] < window_start:
            cls = BEFORE
        elif p["date"] > horizon:
            cls = FUTURE
        elif gid is not None and api[gid]["res"]["status"] == "final":
            cls = "IN_WINDOW"
        elif gid is not None or key in schedule_dates:
            cls = FUTURE                                     # scheduled but not final in the official record at the horizon
        else:
            cls = UNMAPPED
        rows[t] = dict(b, cls=cls, game_id=gid, start=api[gid]["game"]["start"] if gid else None, date=p["date"])
    return rows


def schedule_index(root: str) -> dict:
    out = {}
    for _, r in _read(root, "context/schedule/dt=*/*.jsonl.gz"):
        try:
            st = _dt(r["start_time_utc"]).astimezone(ET).date().isoformat()
            k = lambda a: KALSHI_CODE.get(a, a)  # noqa: E731
            out[(st, k(r["away_abbrev"]) + k(r["home_abbrev"]))] = str(r["game_id"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def eligible_rows(classified: dict) -> list:
    return [dict(schema=SCHEMA_VERSION, market_id=t, event_id=r["game_id"], sport="NHL", event_start=r["start"], native_family=r["family"])
            for t, r in classified.items() if r["cls"] == "IN_WINDOW"]


R_NEVER_IN_FORECAST_FILES = "TICKER_NEVER_IN_ANY_FORECAST_FILE"
R_PRODUCER_NULL_ONLY = "PRODUCER_LISTED_TICKER_BUT_NEVER_PRICED_IT (null probability: unsupported strike/player)"
R_PRICED_NOT_PREGAME_ATTESTED = "PRICED_ONLY_AT_OR_AFTER_START_OR_GAME_UNOFFICIAL"


def market_not_forecast_reasons(classified: dict, forecast_market_ids: set, seen: dict) -> dict:
    """Break every in-window, evaluated-family, unforecast market into exactly one measured reason, per family."""
    out = defaultdict(Counter)
    for t, r in classified.items():
        if r["cls"] != "IN_WINDOW" or r["family"] not in EVALUATED or t in forecast_market_ids:
            continue
        s = seen.get(t, set())
        out[r["family"]][R_NEVER_IN_FORECAST_FILES if not s else R_PRODUCER_NULL_ONLY if s == {"null"} else R_PRICED_NOT_PREGAME_ATTESTED] += 1
    return {f: dict(c) for f, c in out.items()}


# families with a frozen producer probability that this adapter does NOT evaluate (counted, not hidden)
FROZEN_NOT_EVALUATED = {"game_overtime": "predictions_oa p_overtime (frozen game-level probability; not mapped to KXNHLOT in this PR)"}
EVALUATED = frozenset(GAME_FAMS + PERIOD_FAMS + PLAYER_FAMS)
