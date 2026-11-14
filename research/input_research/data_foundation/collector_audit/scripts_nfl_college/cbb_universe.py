import sys, os, glob, json, collections, statistics, datetime as dt
sys.path.insert(0, os.path.dirname(__file__))
from common import *
R = sys.argv[1]
tips = {}
for f in sorted(glob.glob(f"{R}/cbb_schedule-archive/rows/*/*/*/*.jsonl")):
    for r in jl(f):
        if r.get("start_date"): tips[r["game_id"]] = (P(r["start_date"]), r.get("status_type_state"), r.get("home_conference_id") is not None or r.get("away_conference_id") is not None)
av = collections.defaultdict(list)
for f in sorted(glob.glob(f"{R}/cbb_availability-archive/captures/*/*/*/*.jsonl")):
    for r in jl(f): av[r["game_id"]].append((P(r["captured_at"]), r["checkpoint"], r["minutes_to_tip"]))
lo = P("2026-11-02T00:00:00Z"); hi = P("2026-11-10T18:00:00Z")
U = {g: v for g, v in tips.items() if lo <= v[0] <= hi}
cov = {g: bool(av.get(g)) for g in U}
inw = {g: any(0 < m <= 360 for _, _, m in av.get(g, [])) for g in U}
t90 = {g: any(0 < m <= 120 for _, _, m in av.get(g, [])) for g in U}
by_day = collections.defaultdict(lambda: [0, 0])
for g, v in U.items(): by_day[iso(v[0])[:10]][0] += 1; by_day[iso(v[0])[:10]][1] += cov[g]
res = {"schedule_universe_games_tip_2026-11-02..2026-11-10T18:00Z": len(U), "with_any_availability_capture": sum(cov.values()), "with_capture_in_T-6h": sum(inw.values()), "with_capture_in_T-120m": sum(t90.values()),
       "by_tip_day_(games,covered)": dict(sorted(by_day.items())), "caveat": "universe = all games ever listed in schedule-archive rows (ESPN scoreboard, incl non-D-I); availability collector restricts to D-I games with both teams in universe"}
# D-I proxy: games where either side has conference id
D = {g for g, v in U.items() if v[2]}
res["conf_id_present_games"] = len(D); res["conf_games_with_any_capture"] = sum(cov[g] for g in D); res["conf_games_with_T-6h"] = sum(inw[g] for g in D); res["conf_games_with_T-120m"] = sum(t90[g] for g in D)
# availability games not in universe
res["availability_games_total"] = len(av)
json.dump(res, open(f"{os.path.dirname(os.path.dirname(__file__))}/cbb_universe.json", "w"), indent=1)
print(json.dumps(res, indent=0))
