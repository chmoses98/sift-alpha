"""READ-ONLY adapter: NBA PURE shadow store (branch ``nba-shadow-pure`` of the NBA producer) -> ``sift-alpha-eval/1`` rows.

Inputs are a LOCAL checkout directory (``--root``); this module performs no network IO, imports no producer engine, writes
nothing. It feeds the standard's own grader; it does not score anything itself.

What is emitted, from the store's frozen artefacts only:
  forecasts  one CONTINUOUS (mean+quantiles, via the pure_forecast.v1 adapter) per projection row, and one BINARY per
             ladder rung P(stat >= rung). A rung whose (game, player, stat, as_of, rung) matches an archived Kalshi listing
             uses the Kalshi ticker as ``market_id`` (priced); otherwise ``<game>|<player>|<stat>|ge<rung>`` (accuracy only).
  outcomes   from outcomes/gate. played=False -> ``void`` (conditional-on-playing forecasts; DNP contracts void).
  quotes     archived listings (yes bid/ask cents -> dollars) observed at/before the forecast ``as_of``.
  eligible   the eligible-market universe: every archived listing ticker with ``listed_by_as_of`` (a listing the producer
             could have seen at forecast time). Wider board counts (``listings_status``) are reported, not guessed into rows.

Freeze evidence: the store's append-only hash chain is verified (link = sha256(prev|path|sha256) and file bytes). A forecast
file that fails verification or is absent from the chain is demoted to BACKTEST (never PROSPECTIVE). A forecast archived after
kickoff gets ``frozen_at`` = archive time, so the standard blocks it as not frozen before the event. Only conditional-on-playing
projections are used (unconditional rows are listed in the accounting, not scored: DNP markets void on Kalshi).
"""
from __future__ import annotations

import glob
import gzip
import hashlib
import json
import os
from collections import Counter, defaultdict
from typing import Iterator

from .adapters import from_pure_forecast_v1
from .schema import BACKTEST, PROSPECTIVE, SCHEMA_VERSION, LADDER_RUNG

ARMS = ("sim_rotation", "ewm5")
STATS = ("points", "rebounds", "assists", "threes")           # stats with Kalshi player-prop series
ALL_STATS = STATS + ("minutes",)                               # minutes is forecast but has no Kalshi series in the archive
SERIES = {"KXNBAPTS": "points", "KXNBAREB": "rebounds", "KXNBAAST": "assists", "KXNBA3PT": "threes"}


def _rel(root, f):
    return os.path.relpath(f, root)


def _read(root: str, pat: str) -> Iterator[tuple]:
    for f in sorted(glob.glob(os.path.join(root, pat))):
        with gzip.open(f, "rt") as fh:
            for line in fh:
                if line.strip():
                    yield _rel(root, f), json.loads(line)


def verify_chain(root: str) -> dict:
    """Recompute the hash chain and every archived file's sha256. -> {ok, n_links, verified_paths(set), failures[], unchained[]}."""
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


def build(root: str, *, chain: dict | None = None) -> dict:
    chain = chain or verify_chain(root)
    info = Counter()
    # ---- outcomes (gate) keyed by (game, player, stat); duplicates kept so the standard's conflict logic can see them
    gate = defaultdict(list)
    for _, r in _read(root, "outcomes/gate/dt=*/*.jsonl.gz"):
        gate[(r["game_id"], str(r["player_id"]), r["statistic"])].append(r)
    info["gate_rows"] = sum(len(v) for v in gate.values())
    # ---- listings: quotes + eligible universe + per-(key, as_of, rung) lookup
    lookup, quotes, eligible, start_of = {}, {}, {}, {}
    ticker_meta = {}
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
    info["data_horizon"] = max((g["observed_at"] for v in gate.values() for g in v), default=None)   # latest outcome fetch
    status_board = Counter()
    for _, r in _read(root, "market/listings_status/dt=*/*.jsonl.gz"):
        status_board["status_rows"] += 1
        status_board["board_markets_sum"] += r.get("board_markets") or 0
        status_board["n_listings_sum"] += r.get("n_listings") or 0
        status_board["n_unresolved_player_sum"] += r.get("n_unresolved_player") or 0
    # ---- forecasts
    forecasts, outcomes_by_market, hashes = [], {}, defaultdict(set)
    key_seen_with_projection = set()
    for arm in ARMS:
        for path, r in _read(root, f"projections/{arm}/conditional/dt=*/*.jsonl.gz"):
            st = r["statistic"]
            info[f"projection_rows[{arm}]"] += 1
            start_of[r["game_id"]] = r["kickoff"]
            hashes[(arm, r["model_version"])].add(r.get("model_frozen_hash"))
            written = chain["written_at"].get(path)
            attested = path in chain["verified_paths"] and written is not None and written <= r["kickoff"]
            frozen = r["as_of"] if (written is None or written <= r["kickoff"]) else written
            ev = PROSPECTIVE if (attested and r.get("x_capture_mode") == "LIVE") else BACKTEST
            info[f"evidence[{ev}]"] += 1
            if not attested:
                info["not_attested_before_kickoff"] += 1
            base_meta = dict(arm=arm, archive_path=path, archive_written_at=written, season_phase=r.get("x_season_phase"), slot=r.get("x_slot"))
            for row in from_pure_forecast_v1(r, evidence_class=ev, model_id=arm):
                if row["scoring_type"] != "CONTINUOUS":
                    continue                                        # rungs are built below (they may map to Kalshi tickers)
                row.update(frozen_at=frozen, forecast_id=f"{row['forecast_id']}|{arm}", meta=dict(row["meta"], **base_meta))
                forecasts.append(row)
                _outcome(outcomes_by_market, gate, row["market_id"], r["game_id"], str(r["player_id"]), st, None)
            if st not in STATS:
                continue
            key_seen_with_projection.add((r["game_id"], str(r["player_id"]), st))
            for th in r["projection"]["thresholds"]:
                rung = float(th["at_least"])
                lk = lookup.get((r["game_id"], str(r["player_id"]), st, r["as_of"], rung))
                priced = bool(lk and lk.get("listed_by_as_of"))
                mid = lk["ticker"] if priced else f"{r['game_id']}|{r['player_id']}|{st}|ge{rung:g}"
                info["rungs_priced" if priced else "rungs_unpriced"] += 1
                forecasts.append(dict(
                    schema=SCHEMA_VERSION, forecast_id=f"{mid}|{r['as_of']}|{arm}", sport="NBA", event_id=r["game_id"], group_id=r["game_id"],
                    market_id=mid, native_family=f"player_{st}", model_id=arm, model_version=r["model_version"],
                    model_independence="sports_only", market_inputs_used=[], frozen_at=frozen, event_start=r["kickoff"], evidence_class=ev,
                    scoring_type="BINARY", payload=dict(p_yes=float(th["probability"])), line=rung, line_role=LADDER_RUNG,
                    meta=dict(base_meta, priced=priced)))
                _outcome(outcomes_by_market, gate, mid, r["game_id"], str(r["player_id"]), st, rung)
    # ---- eligible rows: event_start from projections where known (None -> counted in cumulative only)
    for t, e in eligible.items():
        e["event_start"] = start_of.get(e["event_id"])
    # ---- why is an eligible market uncovered? (diagnostic only; the standard's coverage does the official count)
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
    outs = [o for rows in outcomes_by_market.values() for o in rows]
    drift = {f"{a}|{v}": len(h) for (a, v), h in hashes.items()}
    return dict(forecasts=forecasts, outcomes=outs, quotes=list(quotes.values()), eligible=list(eligible.values()),
                info=dict(info), board=dict(status_board), model_hash_counts=drift, chain={k: v for k, v in chain.items() if k not in ("verified_paths", "written_at")})


def _outcome(store, gate, market_id, game, player, stat, rung):
    """One outcome row per gate row for this (game, player, stat) -> value for ``market_id`` (continuous: actual; binary: actual >= rung)."""
    if market_id in store:
        return
    rows = []
    for g in gate.get((game, player, stat), ()):
        base = dict(schema=SCHEMA_VERSION, market_id=market_id, event_id=g["game_id"], source="sports", observed_at=g["observed_at"])
        if not g.get("played"):
            rows.append(dict(base, state="void", value=None))
        else:
            a = float(g["actual"])
            rows.append(dict(base, state="final", value=a if rung is None else int(a >= rung)))
    store[market_id] = rows
