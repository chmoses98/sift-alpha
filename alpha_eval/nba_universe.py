"""READ-ONLY NBA eligible-market universe across ALL archived Kalshi NBA market families, and per-family coverage reconciliation.

The universe is every ticker that appeared on any archived full-board snapshot (``kalshi/markets`` checkpoints of the producer's
``data-archive``). It is a UNION OF SNAPSHOTS: a market that opened and closed between two snapshots is invisible, and a market that
has already left the board keeps its last-seen state. Kalshi's official ``result`` is not retained in the archive, so nothing here
claims exchange settlement. The producer's own ``_family`` / ``_support`` labels are carried as DESCRIPTION, never as evidence that a
forecast exists.

Every game-bound ticker is mapped to an ESPN ``game_id`` by (ET date, away, home) against an independent game record; unmapped
game-bound tickers are counted (``UNMAPPED_GAME``), never dropped. Season-long and other non-game markets are counted separately
(``NOT_GAME_BOUND``): they cannot be resolved inside a game window, and are reported, not hidden.
"""
from __future__ import annotations

import glob
import gzip
import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from typing import Iterable, Optional

from .nba_shadow import ET, parse_ticker
from .schema import GRADED, SCHEMA_VERSION

# which frozen source (if any) exists for a Kalshi family, independent of the producer's _support label
EVALUATED_BY_ADAPTER = {"player_points", "player_rebounds", "player_assists", "player_threes"}   # nba-shadow-pure (this PR)
FROZEN_INPUT_NOT_YET_EVALUATED = {                                                                # frozen pmfs exist; no Alpha evaluation yet
    "game_winner": "game_forecasts (frozen team-score pmfs)", "game_spread": "game_forecasts (frozen team-score pmfs)",
    "game_total": "game_forecasts (frozen team-score pmfs)", "team_total": "game_forecasts (frozen team-score pmfs)",
    "player_pra": "projection-data forecasts[pra] (frozen player pmf)",
}
GAME_LEVEL = frozenset({"game_winner", "game_spread", "game_total", "team_total"})                # evaluated by nba_games (derived forecasts)

# reconciliation categories (a partition of the universe)
GRADED_C, NOT_GRADED_C = "FORECAST_AND_GRADED", "FORECAST_NOT_GRADED"
FROZEN_NOT_EVAL, NO_SOURCE = "NO_FORECAST_FROZEN_INPUT_EXISTS_NOT_EVALUATED", "NO_FORECAST_NO_FROZEN_SOURCE"
GAME_NOT_FC, MARKET_NOT_FC = "ADAPTER_FAMILY_GAME_HAS_NO_SHADOW_FORECAST", "ADAPTER_FAMILY_GAME_FORECAST_BUT_MARKET_NOT_FORECAST"
FUTURE, BEFORE, NOT_GAME, UNMAPPED = "GAME_NOT_YET_PLAYED_OR_AFTER_HORIZON", "GAME_BEFORE_FORECAST_WINDOW", "NOT_GAME_BOUND", "UNMAPPED_GAME"
CATEGORIES = (GRADED_C, NOT_GRADED_C, GAME_NOT_FC, MARKET_NOT_FC, FROZEN_NOT_EVAL, NO_SOURCE, FUTURE, BEFORE, NOT_GAME, UNMAPPED)


def load_board(ckpt_dir: str) -> dict:
    """Stream full-board checkpoints -> {ticker: dict(series, family, support, status, first_seen, last_seen, n_snapshots)}."""
    board = {}
    n_files = 0
    for f in sorted(glob.glob(os.path.join(ckpt_dir, "*.jsonl.gz"))):
        n_files += 1
        with gzip.open(f, "rt") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                seen = r.get("_observed_at_utc") or ""
                t = r["ticker"]
                b = board.get(t)
                if b is None:
                    board[t] = dict(series=r.get("series_ticker") or t.split("-")[0], family=r.get("_family") or "unknown",
                                    support=r.get("_support") or "UNKNOWN", status=r.get("status"), first_seen=seen, last_seen=seen, n_snapshots=1)
                else:
                    if seen >= b["last_seen"]:                       # state is the LATEST snapshot's
                        b["last_seen"], b["status"] = seen, r.get("status")
                    b["first_seen"] = min(b["first_seen"], seen)
                    b["n_snapshots"] += 1
    return dict(markets=board, n_files=n_files)


def game_index(game_identity: dict) -> dict:
    """{game_id: {home, away, start}} -> {(ET date, away, home): (game_id, start)}."""
    out = {}
    for gid, g in game_identity.items():
        d = datetime.fromisoformat(g["start"].replace("Z", "+00:00")).astimezone(ET).date().isoformat()
        out[(d, g["away"], g["home"])] = (gid, g["start"])
    return out


def classify(board: dict, gindex: dict, *, window_start: str, horizon: str) -> dict:
    """Place every board ticker in exactly one pre-forecast class: NOT_GAME_BOUND | UNMAPPED_GAME | BEFORE | FUTURE | IN_WINDOW(+game).
    ``window_start`` / ``horizon`` are ET dates (iso)."""
    rows = {}
    for t, b in board["markets"].items():
        p = parse_ticker(t)
        if p is None:
            rows[t] = dict(b, cls=NOT_GAME, game_id=None, start=None, date=None)
            continue
        g = gindex.get((p["date"], p["away"], p["home"]))
        if g is None:
            cls = BEFORE if p["date"] < window_start else FUTURE if p["date"] > horizon else UNMAPPED
            rows[t] = dict(b, cls=cls, game_id=None, start=None, date=p["date"])
            continue
        gid, start = g
        cls = BEFORE if p["date"] < window_start else FUTURE if p["date"] > horizon else "IN_WINDOW"
        rows[t] = dict(b, cls=cls, game_id=gid, start=start, date=p["date"])
    return rows


def eligible_rows(classified: dict) -> list:
    """Rows for the standard's ``--eligible``: in-window, mapped game-bound markets (the markets that could be forecast and graded)."""
    return [dict(schema=SCHEMA_VERSION, market_id=t, event_id=r["game_id"], sport="NBA", event_start=r["start"], native_family=r["family"])
            for t, r in classified.items() if r["cls"] == "IN_WINDOW"]


def reconcile(classified: dict, graded_rows: Iterable[dict], forecast_market_ids: set, forecast_family_games: set,
              evaluated_families: frozenset = frozenset(EVALUATED_BY_ADAPTER), frozen_not_evaluated: Optional[dict] = None) -> dict:
    """Partition EVERY board ticker into exactly one category; returns totals, per-family and per-series tables.
    ``evaluated_families``: families for which Alpha has a forecast source wired in THIS run (a family not in it is never counted as covered).
    ``graded_rows``: grade_all()["rows"] (accuracy status per forecast row). ``forecast_family_games``: {(native_family, game_id)} that have ANY forecast, so a game forecast for one family never excuses another."""
    fne = FROZEN_INPUT_NOT_YET_EVALUATED if frozen_not_evaluated is None else frozen_not_evaluated   # sport-specific (NHL passes its own)
    graded_markets, forecast_markets = set(), set(forecast_market_ids)
    for r in graded_rows:
        if r["accuracy"]["status"] == GRADED:
            graded_markets.add(r["market_id"])
    by_family, by_series, totals = defaultdict(Counter), defaultdict(Counter), Counter()
    detail = {}
    for t, r in classified.items():
        if r["cls"] == "IN_WINDOW":
            if t in graded_markets:
                c = GRADED_C
            elif t in forecast_markets:
                c = NOT_GRADED_C
            elif r["family"] in evaluated_families:
                c = MARKET_NOT_FC if (r["family"], r["game_id"]) in forecast_family_games else GAME_NOT_FC
            elif r["family"] in fne:
                c = FROZEN_NOT_EVAL
            else:
                c = NO_SOURCE
        else:
            c = r["cls"]
        detail[t] = c
        totals[c] += 1
        by_family[r["family"]][c] += 1
        by_series[r["series"]][c] += 1
    assert sum(totals.values()) == len(classified)           # exact partition, asserted at runtime too
    fam_tbl = {f: dict(n=sum(c.values()), support=Counter(r["support"] for r in classified.values() if r["family"] == f).most_common(1)[0][0],
                       counts=dict(c)) for f, c in sorted(by_family.items(), key=lambda kv: -sum(kv[1].values()))}
    return dict(n_board_tickers=len(classified), totals={k: totals.get(k, 0) for k in CATEGORIES}, by_family=fam_tbl,
                n_series=len(by_series), detail=detail)


# why an adapter-family market has no forecast although its game was forecast (measured, never assumed)
R_NO_LISTING_CAPTURE = "GAME_HAS_NO_LISTING_CAPTURE_SO_TICKER_NOT_LINKED_TO_A_PLAYER"
R_TICKER_ABSENT = "GAME_HAS_LISTINGS_BUT_THIS_TICKER_ABSENT"
R_LISTED_NOT_FORECAST = "LISTED_TICKER_BUT_NO_PROJECTION_FOR_PLAYER_OR_RUNG"


def market_not_forecast_reasons(classified: dict, forecast_market_ids: set, listing_tickers: set, listing_games: set,
                                forecast_family_games: set, families=EVALUATED_BY_ADAPTER) -> dict:
    """Break the MARKET_NOT_FC category into exactly three reasons. A ticker can only be linked to a player (and so priced) if the
    producer's listing archive saw it, which needs a listing capture for its game."""
    out = Counter()
    for t, r in classified.items():
        if r["cls"] != "IN_WINDOW" or r["family"] not in families or t in forecast_market_ids:
            continue
        if (r["family"], r["game_id"]) not in forecast_family_games:
            continue                                            # that is the GAME_NOT_FC category
        out[R_LISTED_NOT_FORECAST if t in listing_tickers else R_TICKER_ABSENT if r["game_id"] in listing_games else R_NO_LISTING_CAPTURE] += 1
    return dict(out)
