"""Eligible-market universe and coverage accounting.

Forecast-only accounting answers "of the forecasts we were handed, how many graded?". It CANNOT say how much of the
tradable surface was forecast at all: a market nobody forecast simply never appears. Complete coverage needs an
independently sourced list of eligible markets (e.g. the archived Kalshi catalog/quotes for the window). This module
keeps the two claims apart:

  basis FORECAST_ONLY       no eligible universe supplied -> coverage of the market surface is NOT ESTABLISHED
  basis ELIGIBLE_UNIVERSE   every eligible market is accounted: forecast+graded / forecast-not-graded / NO_FORECAST /
                            event-identity mismatch; forecasts on markets outside the universe are counted separately

Eligible rows: ``{schema, market_id, event_id, sport, event_start[, native_family]}``. Duplicate rows for one market with
different event identity make that market CONFLICTING (counted, never graded as covered).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable, Optional

from .schema import GRADED, SCHEMA_VERSION, SPORTS, SchemaError, opt_ts

FORECAST_ONLY, ELIGIBLE_UNIVERSE = "FORECAST_ONLY", "ELIGIBLE_UNIVERSE"
NO_FORECAST, ID_CONFLICT = "NO_FORECAST_FOR_ELIGIBLE_MARKET", "ELIGIBLE_MARKET_EVENT_ID_CONFLICT"


def normalise_eligible(rows: Optional[Iterable[dict]]) -> Optional[dict]:
    """-> None (no universe supplied) or {markets: {market_id: row}, conflicts: {market_id}, rejects: [...]}."""
    if rows is None:
        return None
    markets, conflicts, rejects = {}, set(), []
    for r in rows:
        try:
            if r.get("schema") != SCHEMA_VERSION:
                raise SchemaError(f"eligible: schema {r.get('schema')!r}")
            if not r.get("market_id") or not r.get("event_id"):
                raise SchemaError("eligible: market_id and event_id required")
            if r.get("sport") not in SPORTS:
                raise SchemaError(f"eligible: sport {r.get('sport')!r}")
            start = opt_ts(r.get("event_start"), "event_start")
        except SchemaError as e:
            rejects.append(str(e))
            continue
        row = dict(market_id=str(r["market_id"]), event_id=str(r["event_id"]), sport=r["sport"],
                   event_date=start.date().isoformat() if start else None, native_family=str(r.get("native_family") or ""))
        prev = markets.get(row["market_id"])
        if prev and prev["event_id"] != row["event_id"]:
            conflicts.add(row["market_id"])
        markets.setdefault(row["market_id"], row)
    return dict(markets=markets, conflicts=conflicts, rejects=rejects)


def coverage(eligible: Optional[dict], rows: list, *, date: Optional[str] = None, kind: str = "cumulative") -> dict:
    """Coverage of ``rows`` (graded forecast rows in the report window) against the eligible universe."""
    n_fc_markets = len({r["market_id"] for r in rows})
    if eligible is None:
        return dict(basis=FORECAST_ONLY, n_forecast_rows=len(rows), n_forecast_markets=n_fc_markets,
                    complete_eligible_market_coverage="NOT_ESTABLISHED",
                    note="no eligible-market universe supplied: this accounts for forecasts only and says nothing about "
                         "how many eligible markets were never forecast")
    def in_window(d):
        if d is None:
            return kind != "daily" or date is None
        return date is None or (d == date if kind == "daily" else d <= date)
    el = {m: e for m, e in eligible["markets"].items() if in_window(e["event_date"])}
    by_m = defaultdict(list)
    for r in rows:
        by_m[r["market_id"]].append(r)
    status = Counter()
    uncovered = []
    per_sport = defaultdict(Counter)
    for m, e in sorted(el.items()):
        rs = by_m.get(m)
        if m in eligible["conflicts"]:
            st = ID_CONFLICT
        elif not rs:
            st = NO_FORECAST
        elif any(r["event_id"] != e["event_id"] for r in rs):
            st = "FORECAST_EVENT_ID_MISMATCH"
        elif any(r["accuracy"]["status"] == GRADED for r in rs):
            st = "FORECAST_AND_GRADED"
        else:
            st = "FORECAST_NOT_GRADED"
        status[st] += 1
        per_sport[e["sport"]][st] += 1
        if st in (NO_FORECAST, ID_CONFLICT) and len(uncovered) < 25:
            uncovered.append(m)
    out_of_universe = sorted(m for m in by_m if m not in eligible["markets"])
    n = len(el)
    fc = n - status[NO_FORECAST] - status[ID_CONFLICT]
    graded = status["FORECAST_AND_GRADED"]
    complete = n > 0 and status[NO_FORECAST] == 0 and status[ID_CONFLICT] == 0 and status["FORECAST_EVENT_ID_MISMATCH"] == 0
    return dict(basis=ELIGIBLE_UNIVERSE, n_eligible_markets=n, n_forecast_rows=len(rows), n_forecast_markets=n_fc_markets,
                status_counts=dict(status), by_sport={k: dict(v) for k, v in sorted(per_sport.items())},
                forecast_coverage_of_eligible=round(fc / n, 6) if n else None,
                graded_coverage_of_eligible=round(graded / n, 6) if n else None,
                complete_eligible_market_coverage="COMPLETE" if complete else "INCOMPLETE",
                uncovered_examples=uncovered, n_forecast_markets_outside_universe=len(out_of_universe),
                outside_universe_examples=out_of_universe[:25], eligible_input_rejects=len(eligible["rejects"]))
