#!/usr/bin/env python3
"""Per sport/family coverage ledger for the outcome-intelligence track. Statuses separate COVERAGE GAPS from NEGATIVE FINDINGS:
TESTED_NULL (sufficient data, no demonstrated gain) | UNPOWERED (data exists, too few independent games) | OUTCOMES_ONLY (no prior prices)
| NOT_REPRODUCED (access blocked in this session; PR #25 numbers carried forward, unverified) | NOT_AUDITED (access blocked) | NO_DATA.
usage: coverage_ledger.py AUDIT.json INCREMENTAL.json OUT.json"""
import json, sys

audit, inc = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
d = audit["denominators"]["by_family"]
L = []
for fam in ("moneyline", "spread", "total"):
    L.append(dict(sport="CFB", family=fam, status="TESTED_NULL", independent_games=d[fam]["games"], settled_tickers=d[fam]["tickers"], settled_rows=d[fam]["rows"],
                  source="cfb-edge-finder@research-data (prospective capture)", settlement="DERIVED from ESPN-fallback final score; re-derived independently 4552/4552; official Kalshi settlement absent",
                  note="3 weeks; holdout 1/3 of games; see cfb_incremental.json"))
for fam in ("team_total", "1h/2h/quarter markets", "player props"):
    L.append(dict(sport="CFB", family=fam, status="NO_DATA", note="not in the research corpus (only KXNCAAFGAME/SPREAD/TOTAL are captured)"))
BLOCK = "access to this repo was denied by the session permission classifier (add_repo); nothing in it was read"
for sport, repo in (("NFL", "nfl-edge-finder@market-data"), ("MLB", "edge-finder-api"), ("NBA", "nba-edge-finder"), ("NHL", "NHL-edge-finder"),
                    ("CBB", "cbb-edge-finder"), ("SOCCER", "soccer-edge-finder"), ("TENNIS", "Tennis-Edge-Finder")):
    st = "NOT_REPRODUCED" if sport == "NFL" else "NOT_AUDITED"
    L.append(dict(sport=sport, family="all", status=st, source=repo, blocker=BLOCK,
                  note=("PR #25 reports 566 settled moneyline tickers / 284 games, 0 outcome mismatches, matchup model worse than market; carried forward UNVERIFIED" if sport == "NFL" else "unknown")))
out = dict(status="RESEARCH_ONLY", schema="sift-outcome-intel-coverage/1", ledger=L,
           inputs=audit["inputs"], cfb_incremental_cells=inc["cells_tried"], cfb_validated_gain_cells=inc["validated_gain_cells"])
json.dump(out, open(sys.argv[3], "w"), indent=1, sort_keys=True)
print(len(L), "ledger rows")
