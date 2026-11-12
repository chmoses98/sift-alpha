"""READ-ONLY adapter: NBA PURE shadow store (branch ``nba-shadow-pure`` of the NBA producer) -> ``sift-alpha-eval/1`` rows.

Inputs are LOCAL directories/files; this module performs no network IO, imports no producer engine, writes nothing. It feeds
the standard's own grader; it does not score anything itself.

Emitted from the store's frozen artefacts only:
  forecasts  one CONTINUOUS (mean+quantiles, via the pure_forecast.v1 adapter) per projection row and one BINARY per ladder
             rung P(stat >= rung). A rung that matches an archived Kalshi listing (game, player, stat, as_of, rung) uses the
             Kalshi ticker as ``market_id`` (priced); otherwise ``<game>|<player>|<stat>|ge<rung>`` (accuracy only).
  outcomes   from outcomes/gate. played=False -> ``void`` (conditional-on-playing forecasts; DNP contracts void).
  quotes     archived listings (yes bid/ask cents -> dollars).
  eligible   every archived listing ticker with ``listed_by_as_of``.

Independent verification (optional auxiliary inputs; each is a DIFFERENT artefact from the one that built the join):
  * event identity: the Kalshi ticker's own date/teams/player-team are compared with the independent game record
    (``sift.game_forecast.v1`` home/away/start). A disagreement stamps the outcome's ``event_id`` with
    ``#TICKER_IDENTITY_MISMATCH`` so the standard's event-identity join BLOCKS the row. Nothing is silently re-keyed.
  * outcome value: the producer's separately implemented settle engine (``settlements``: ticker -> YES/NO from the ESPN box)
    is compared with the adapter's own ``actual >= rung``. A disagreement adds a second, conflicting outcome row, so the
    standard's conflict rule BLOCKS the row. This is NOT exchange settlement (Kalshi's own result is not in the archive).
  * absence: a projected player with no box row in a finished game is reconciled to the official NBA injury report
    (``sift.availability.v1``). Only a pre-kickoff official ``OUT`` is treated as a corroborated non-appearance (void); every
    other absent case stays unscored (overdue) and is counted by category.

Freeze evidence: the store's hash chain is verified (link = sha256(prev|path|sha256) and file bytes). A forecast file that
fails verification or is absent from the chain is demoted to BACKTEST. A forecast archived after kickoff gets ``frozen_at`` =
archive time, so the standard blocks it as not frozen before the event.
"""
from __future__ import annotations

import glob
import gzip
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional
from zoneinfo import ZoneInfo

from .adapters import from_pure_forecast_v1
from .schema import BACKTEST, LADDER_RUNG, PROSPECTIVE, SCHEMA_VERSION

ARMS = ("sim_rotation", "ewm5")
STATS = ("points", "rebounds", "assists", "threes")           # stats with Kalshi player-prop series
SERIES = {"KXNBAPTS": "points", "KXNBAREB": "rebounds", "KXNBAAST": "assists", "KXNBA3PT": "threes"}
ET = ZoneInfo("America/New_York")
_MON = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
_TICKER = re.compile(r"^(?P<series>KX[A-Z0-9]+)-(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<dd>\d{2})(?P<away>[A-Z]{3})(?P<home>[A-Z]{3})(?:-(?P<rest>.+))?$")

# absence categories for projected players missing from the box score of a finished game
ABS_OUT, ABS_DOUBTFUL = "ABSENT_OFFICIAL_OUT_PRE_KICKOFF", "ABSENT_OFFICIAL_DOUBTFUL_PRE_KICKOFF"
ABS_AVAILABLE, ABS_NO_REPORT = "ABSENT_REPORTED_AVAILABLE_OR_QUESTIONABLE", "ABSENT_NO_REPORT_INSIDE_AVAILABILITY_WINDOW"
ABS_NO_ARCHIVE = "ABSENT_BEFORE_AVAILABILITY_ARCHIVE_STARTED"
ABSENT_CATEGORIES = (ABS_OUT, ABS_DOUBTFUL, ABS_AVAILABLE, ABS_NO_REPORT, ABS_NO_ARCHIVE)


def _rel(root, f):
    return os.path.relpath(f, root)


def _read(root: str, pat: str) -> Iterator[tuple]:
    for f in sorted(glob.glob(os.path.join(root, pat))):
        with gzip.open(f, "rt") as fh:
            for line in fh:
                if line.strip():
                    yield _rel(root, f), json.loads(line)


# ------------------------------------------------------------------ auxiliary (independent) inputs
def load_game_identity(projection_root: str) -> dict:
    """``sift.game_forecast.v1`` rows (projection-data/game_forecasts/nba) -> {game_id: {home, away, start}}."""
    out = {}
    for _, r in _read(projection_root, "game_forecasts/nba/*/*.jsonl.gz"):
        out[r["game_id"]] = dict(home=r["home"], away=r["away"], start=r["game_start_utc"])
    return out


def load_availability(projection_root: str) -> list:
    return [r for _, r in _read(projection_root, "availability/nba/*/*.jsonl.gz")]


def load_settlements(directory: str) -> dict:
    """Producer settle-engine rows (data-archive/settlements/**.jsonl.gz) -> {ticker: row}; a later duplicate wins only if identical."""
    out = {}
    for f in sorted(glob.glob(os.path.join(directory, "**", "*.jsonl.gz"), recursive=True)):
        with gzip.open(f, "rt") as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    out[r["ticker"]] = r
    return out


def parse_ticker(ticker: str) -> Optional[dict]:
    """Kalshi NBA ticker -> {series, date (ET, iso), away, home, rest}; None if it does not parse. Pure."""
    m = _TICKER.match(ticker or "")
    if not m or m["mon"] not in _MON:
        return None
    try:
        d = datetime(2000 + int(m["yy"]), _MON[m["mon"]], int(m["dd"])).date()
    except ValueError:
        return None
    return dict(series=m["series"], date=d.isoformat(), away=m["away"], home=m["home"], rest=m["rest"] or "")


def check_identity(ticker: str, game: Optional[dict]) -> str:
    """Compare a ticker with an independent game record. -> IDENTITY_VERIFIED | IDENTITY_UNVERIFIABLE_NO_GAME_RECORD |
    IDENTITY_UNPARSEABLE_TICKER | MISMATCH_TEAMS | MISMATCH_DATE | MISMATCH_PLAYER_TEAM_NOT_IN_GAME."""
    t = parse_ticker(ticker)
    if t is None:
        return "IDENTITY_UNPARSEABLE_TICKER"
    if game is None:
        return "IDENTITY_UNVERIFIABLE_NO_GAME_RECORD"
    if (t["away"], t["home"]) != (game["away"], game["home"]):
        return "MISMATCH_TEAMS"
    start = datetime.fromisoformat(game["start"].replace("Z", "+00:00")).astimezone(ET).date().isoformat()
    if t["date"] != start:
        return "MISMATCH_DATE"
    if t["series"] in SERIES:                                   # player part starts with the player's team code
        team = t["rest"].split("-")[0][:3]
        if team not in (t["away"], t["home"]):
            return "MISMATCH_PLAYER_TEAM_NOT_IN_GAME"
    return "IDENTITY_VERIFIED"


def classify_absence(kickoff: str, espn_id: str, game_id: str, avail_by_key: dict, avail_start: Optional[str]) -> str:
    """Reconcile one projected-but-absent player-game against the official injury report (latest record at or before kickoff)."""
    recs = [r for r in avail_by_key.get((game_id, espn_id), ()) if r["captured_utc"] <= kickoff]
    if recs:
        st = max(recs, key=lambda r: r["captured_utc"])["status"]
        return ABS_OUT if st == "OUT" else ABS_DOUBTFUL if st == "DOUBTFUL" else ABS_AVAILABLE
    if avail_start is None or kickoff[:10] < avail_start:
        return ABS_NO_ARCHIVE
    return ABS_NO_REPORT


# ------------------------------------------------------------------ freeze evidence
def verify_chain(root: str) -> dict:
    """Recompute the hash chain and every archived file's sha256."""
    prev, ok_paths, failures, seen = "0" * 64, set(), [], set()
    manifest = {}
    mp = os.path.join(root, "manifest.jsonl")
    if os.path.exists(mp):
        for l in open(mp):
            if l.strip():
                m = json.loads(l)
                manifest[m["path"]] = m
    n = 0
    for l in open(os.path.join(root, "chain.jsonl")):
        if not l.strip():
            continue
        n += 1
        c = json.loads(l)
        seen.add(c["path"])
        why = None
        if c["prev"] != prev:
            why = "PREV_MISMATCH"
        elif hashlib.sha256(f"{c['prev']}|{c['path']}|{c['sha256']}".encode()).hexdigest() != c["link"]:
            why = "LINK_MISMATCH"
        else:
            fp = os.path.join(root, c["path"])
            if not os.path.exists(fp):
                why = "FILE_MISSING"
            elif hashlib.sha256(open(fp, "rb").read()).hexdigest() != c["sha256"]:
                why = "FILE_SHA_MISMATCH"
            elif c["path"] in manifest and manifest[c["path"]].get("sha256") != c["sha256"]:
                why = "MANIFEST_SHA_MISMATCH"
        if why:
            failures.append(dict(seq=c.get("seq"), path=c["path"], reason=why))
        else:
            ok_paths.add(c["path"])
        prev = c["link"]
    on_disk = {_rel(root, f) for f in glob.glob(os.path.join(root, "**", "*.jsonl.gz"), recursive=True)}
    return dict(ok=not failures, n_links=n, n_verified=len(ok_paths), verified_paths=ok_paths, failures=failures[:20],
                n_failures=len(failures), unchained=sorted(on_disk - seen)[:20], n_unchained=len(on_disk - seen),
                written_at={p: m.get("written_at_utc") for p, m in manifest.items()})


# ------------------------------------------------------------------ build
def build(root: str, *, chain: Optional[dict] = None, game_identity: Optional[dict] = None, availability: Optional[list] = None,
          settlements: Optional[dict] = None) -> dict:
    chain = chain or verify_chain(root)
    info = Counter()
    gate = defaultdict(list)
    for _, r in _read(root, "outcomes/gate/dt=*/*.jsonl.gz"):
        gate[(r["game_id"], str(r["player_id"]), r["statistic"])].append(r)
    info["gate_rows"] = sum(len(v) for v in gate.values())
    games_with_outcomes = {k[0] for k in gate}
    game_last_obs = {}
    for (g, _, _), rows in gate.items():
        game_last_obs[g] = max(game_last_obs.get(g, ""), max(x["observed_at"] for x in rows))
    box_present = {(k[0], k[1]) for k in gate}                  # (game, player) that have any box row

    lookup, quotes, eligible, start_of, ticker_meta = {}, {}, {}, {}, {}
    for _, r in _read(root, "market/listings/dt=*/*.jsonl.gz"):
        if r.get("record") != "market_listing":
            continue
        info["listing_rows"] += 1
        stat = r["statistic"]
        lookup[(r["game_id"], str(r["player_id"]), stat, r["pure_as_of"], float(r["at_least"]))] = r
        yb, ya = r.get("yes_bid_cents"), r.get("yes_ask_cents")
        quotes[(r["ticker"], r["board_observed_at"])] = dict(
            schema=SCHEMA_VERSION, market_id=r["ticker"], observed_at=r["board_observed_at"],
            yes_bid=None if yb in (None, 0) else yb / 100.0, yes_ask=None if ya in (None, 0) else ya / 100.0, source="kalshi_listing_archive")
        if r.get("listed_by_as_of"):
            eligible.setdefault(r["ticker"], dict(schema=SCHEMA_VERSION, market_id=r["ticker"], event_id=r["game_id"], sport="NBA",
                                                  native_family=f"player_{stat}", event_start=None))
            ticker_meta[r["ticker"]] = (r["game_id"], str(r["player_id"]), stat, float(r["at_least"]), r["series"])
    info["eligible_tickers"] = len(eligible)
    info["data_horizon"] = max((g["observed_at"] for v in gate.values() for g in v), default=None)
    status_board = Counter()
    for _, r in _read(root, "market/listings_status/dt=*/*.jsonl.gz"):
        status_board["status_rows"] += 1
        status_board["n_listings_sum"] += r.get("n_listings") or 0
        status_board["n_unresolved_player_sum"] += r.get("n_unresolved_player") or 0

    avail_by_key, avail_start = defaultdict(list), None
    if availability is not None:
        for a in availability:
            avail_by_key[(a["event_id"], a["entity_id"])].append(a)
        avail_start = min((a["captured_utc"][:10] for a in availability), default=None)

    forecasts, outcomes_by_market, hashes = [], {}, defaultdict(set)
    key_seen_with_projection, absent_seen, identity = set(), {}, {}
    xcheck, seen_x = Counter(), set()

    def ident(ticker, game_id):
        if ticker not in identity:
            identity[ticker] = check_identity(ticker, (game_identity or {}).get(game_id)) if game_identity is not None else "IDENTITY_NOT_CHECKED"
        return identity[ticker]

    for arm in ARMS:
        for path, r in _read(root, f"projections/{arm}/conditional/dt=*/*.jsonl.gz"):
            st, gid, pid = r["statistic"], r["game_id"], str(r["player_id"])
            info[f"projection_rows[{arm}]"] += 1
            start_of[gid] = r["kickoff"]
            hashes[(arm, r["model_version"])].add(r.get("model_frozen_hash"))
            written = chain["written_at"].get(path)
            attested = path in chain["verified_paths"] and written is not None and written <= r["kickoff"]
            frozen = r["as_of"] if (written is None or written <= r["kickoff"]) else written
            ev = PROSPECTIVE if (attested and r.get("x_capture_mode") == "LIVE") else BACKTEST
            info[f"evidence[{ev}]"] += 1
            if not attested:
                info["not_attested_before_kickoff"] += 1
            if gid in games_with_outcomes and (gid, pid) not in box_present and (gid, pid) not in absent_seen:
                absent_seen[(gid, pid)] = classify_absence(r["kickoff"], "espn:" + pid.lstrip("-"), gid, avail_by_key, avail_start) \
                    if availability is not None else "ABSENT_AVAILABILITY_NOT_SUPPLIED"
            base_meta = dict(arm=arm, archive_path=path, archive_written_at=written, season_phase=r.get("x_season_phase"), slot=r.get("x_slot"))
            for row in from_pure_forecast_v1(r, evidence_class=ev, model_id=arm):
                if row["scoring_type"] != "CONTINUOUS":
                    continue
                row.update(frozen_at=frozen, forecast_id=f"{row['forecast_id']}|{arm}", meta=dict(row["meta"], **base_meta))
                forecasts.append(row)
                _outcome(outcomes_by_market, gate, row["market_id"], gid, pid, st, None, absent_seen, game_last_obs, None, None, xcheck)
            if st not in STATS:
                continue
            key_seen_with_projection.add((gid, pid, st))
            for th in r["projection"]["thresholds"]:
                rung = float(th["at_least"])
                lk = lookup.get((gid, pid, st, r["as_of"], rung))
                priced = bool(lk and lk.get("listed_by_as_of"))
                mid = lk["ticker"] if priced else f"{gid}|{pid}|{st}|ge{rung:g}"
                info["rungs_priced" if priced else "rungs_unpriced"] += 1
                forecasts.append(dict(
                    schema=SCHEMA_VERSION, forecast_id=f"{mid}|{r['as_of']}|{arm}", sport="NBA", event_id=gid, group_id=gid,
                    market_id=mid, native_family=f"player_{st}", model_id=arm, model_version=r["model_version"],
                    model_independence="sports_only", market_inputs_used=[], frozen_at=frozen, event_start=r["kickoff"], evidence_class=ev,
                    scoring_type="BINARY", payload=dict(p_yes=float(th["probability"])), line=rung, line_role=LADDER_RUNG,
                    meta=dict(base_meta, priced=priced)))
                _outcome(outcomes_by_market, gate, mid, gid, pid, st, rung, absent_seen, game_last_obs,
                         ident(mid, gid) if priced else None, settlements.get(mid) if (priced and settlements is not None) else None, xcheck)
                if priced and mid not in seen_x:
                    seen_x.add(mid)
                    info[f"identity[{ident(mid, gid)}]"] += 1
    for t, e in eligible.items():
        e["event_start"] = start_of.get(e["event_id"])

    covered = {f["market_id"] for f in forecasts if f["scoring_type"] == "BINARY"}
    why = Counter()
    for t in set(eligible) - covered:
        g, p, st, rung, series = ticker_meta[t]
        if series not in SERIES:
            why["SERIES_NOT_MODELLED"] += 1
        elif (g, p, st) not in key_seen_with_projection:
            why["NO_PROJECTION_FOR_PLAYER_GAME_STAT"] += 1
        else:
            why["RUNG_NOT_ON_FORECAST_GRID_OR_NOT_LISTED_AT_AS_OF"] += 1
    info.update({f"uncovered_eligible[{k}]": v for k, v in why.items()})
    # absence reconciliation: player-games (not rows), partitioned exactly
    info.update({f"absent_player_games[{k}]": v for k, v in Counter(absent_seen.values()).items()})
    info["absent_player_games_total"] = len(absent_seen)
    info.update({f"outcome_xcheck[{k}]": v for k, v in xcheck.items()})
    outs = [o for rows in outcomes_by_market.values() for o in rows]
    drift = {f"{a}|{v}": len(h) for (a, v), h in hashes.items()}
    return dict(forecasts=forecasts, outcomes=outs, quotes=list(quotes.values()), eligible=list(eligible.values()),
                info=dict(info), board=dict(status_board), model_hash_counts=drift,
                chain={k: v for k, v in chain.items() if k not in ("verified_paths", "written_at")})


def _outcome(store, gate, market_id, game, player, stat, rung, absent, game_last_obs, identity, settlement, xcheck):
    """Outcome rows for ``market_id`` (continuous: actual; binary: actual >= rung); one row per gate row. See module docstring for
    how identity / settlement / absence evidence is expressed so that the STANDARD (not this adapter) blocks the row."""
    if market_id in store:
        return
    rows, ev_id_suffix = [], ""
    if identity is not None and identity.startswith("MISMATCH"):
        ev_id_suffix = "#TICKER_IDENTITY_MISMATCH"
    for g in gate.get((game, player, stat), ()):
        base = dict(schema=SCHEMA_VERSION, market_id=market_id, event_id=g["game_id"] + ev_id_suffix, source="sports", observed_at=g["observed_at"])
        if not g.get("played"):
            rows.append(dict(base, state="void", value=None))
        else:
            a = float(g["actual"])
            rows.append(dict(base, state="final", value=a if rung is None else int(a >= rung)))
    if not rows and absent.get((game, player)) == ABS_OUT and game in game_last_obs:
        # corroborated non-appearance (official pre-kickoff OUT): void, exactly as a box-score DNP would be
        rows.append(dict(schema=SCHEMA_VERSION, market_id=market_id, event_id=game + ev_id_suffix, source="sports",
                         observed_at=game_last_obs[game], state="void", value=None))
    if settlement is not None and rung is not None:
        xcheck[_cross(rows, settlement)] += 1
        if rows and rows[0]["state"] == "final" and settlement["outcome"] in ("YES", "NO"):
            sv = 1 if settlement["outcome"] == "YES" else 0
            if sv != rows[0]["value"]:                          # independent implementation disagrees -> conflicting row
                rows.append(dict(rows[0], value=sv))
    store[market_id] = rows


def _cross(rows, settlement) -> str:
    o = settlement["outcome"]
    if o not in ("YES", "NO"):
        return "SETTLEMENT_" + ("UNSETTLEABLE_" + re.sub(r"[^A-Z]+", "_", settlement.get("reason", "").upper())[:30] if o == "UNSETTLEABLE" else o)
    if not rows or rows[0]["state"] != "final":
        return "SETTLEMENT_HAS_OUTCOME_ADAPTER_DOES_NOT"
    return "AGREE" if (1 if o == "YES" else 0) == rows[0]["value"] else "DISAGREE"

