"""Market watch: detect Kalshi sports series that the committed universe does not know yet (RESEARCH_ONLY).

    python -m alpha_engine.foundation.market_watch            # ONE public GET of the series listing, then a diff
    python -m alpha_engine.foundation.market_watch FILE.json  # offline: diff a saved listing

Reuses ``alpha_engine.input_research.market_universe`` (same endpoint, same sport/kind heuristics). It reads only the
series-level listing the existing sweep already reads: one request, no authentication, no pagination, no contracts,
no prices. The committed catalog, baseline lock and series assignment are NOT modified: a new in-scope series is
reported as UNRESOLVED until someone classifies it, never silently dropped or auto-assigned.
"""
from __future__ import annotations

import json
import sys
from collections import Counter

from ..input_research import market_universe as mu
from .contract import OPS, ROOT, write_json

ASSIGN = ROOT / "research/input_research/market_universe/series_assignment.json"
IN_SCOPE = {"NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"}


def diff(series: list, assignment: dict, observed_utc: str) -> dict:
    known = {r["ticker"]: r for r in assignment["rows"]}
    live = {s["ticker"]: s for s in series}
    new = [{"ticker": t, "title": s.get("title"), "sport": mu.sport_of(s), "kind": mu.kind_of(s), "frequency": s.get("frequency"),
            "status": "UNRESOLVED_NOT_ASSIGNED_TO_AN_ARCHETYPE"} for t, s in sorted(live.items()) if t not in known]
    new_in = [r for r in new if r["sport"] in IN_SCOPE]
    gone = sorted(t for t, r in known.items() if t not in live and r.get("scope") == "IN_SCOPE")
    return {"schema": "sift-foundation-market-watch/1", "status": "RESEARCH_ONLY", "observed_utc": observed_utc,
            "source": "GET " + mu.URL + " (public series listing; one request)", "baseline": str(ASSIGN.relative_to(ROOT)),
            "baseline_series": len(known), "live_series": len(live),
            "new_series_total": len(new), "new_series_in_scope": len(new_in),
            "new_in_scope_by_sport": dict(sorted(Counter(r["sport"] for r in new_in).items())),
            "new_in_scope_by_sport_kind": [{"sport": a, "kind": b, "series": n} for (a, b), n in sorted(Counter((r["sport"], r["kind"]) for r in new_in).items())],
            "new_in_scope": new_in, "new_out_of_scope_count": len(new) - len(new_in),
            "in_scope_series_no_longer_listed": gone,
            "caveat": "Series-level only; sport/kind are ticker/title heuristics. A new series may belong to an existing archetype; it stays UNRESOLVED until classified. "
                      "The approved catalog (170 archetypes) is not changed by this file."}


def main(argv=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    import datetime
    series = json.load(open(argv[0]))["series"] if argv else mu.fetch()
    stamp = argv[1] if len(argv) > 1 else datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    d = diff(series, json.loads(ASSIGN.read_text()), stamp)
    write_json(OPS / "market_watch.json", d)
    print(f"live {d['live_series']} | baseline {d['baseline_series']} | new {d['new_series_total']} ({d['new_series_in_scope']} in scope: {d['new_in_scope_by_sport']}) | in-scope no longer listed {len(d['in_scope_series_no_longer_listed'])}")


if __name__ == "__main__":
    main()
