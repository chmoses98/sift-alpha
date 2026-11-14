import sys, os, glob, json, datetime as dt, collections
sys.path.insert(0, os.path.dirname(__file__))
from common import *
R = sys.argv[1]
games = {}
for f in glob.glob(f"{R}/nef_projection-data/forecasts/nfl/*/*"):
    for r in jl(f): games[r["game_id"]] = P(r["game_start_utc"])
pit = [P(jload(f)["meta"]["retrieved_at"]) for f in glob.glob(f"{R}/nef_market-data/data/pit_availability/nfl/espn_injuries/*/*.json.gz")]
av = []
for f in glob.glob(f"{R}/nef_projection-data/availability/nfl/*/*"): av.append(P(jl(f)[0]["captured_utc"]))
ros = []
for f in glob.glob(f"{R}/nef_market-data/data/pit_availability/nfl/espn_event_rosters/*/*"):
    d = jload(f)
    for e in d["events"]: ros.append((e["event_id"], e["minutes_to_kickoff"]))
lo = P("2026-10-13T00:00:00Z")
G = {g: k for g, k in games.items() if k >= lo}
def win(ts, k, a, b): return any(k - dt.timedelta(minutes=a) <= t <= k - dt.timedelta(minutes=b) for t in ts)
res = {"games_kickoff_since_2026-10-13": len(G)}
for name, ts in (("pit_espn_injuries", pit), ("projection_availability", av)):
    res[name] = {"T-120..T-60": sum(win(ts, k, 120, 60) for k in G.values()), "T-95..T-60": sum(win(ts, k, 95, 60) for k in G.values()), "T-60..T-0": sum(win(ts, k, 60, 0) for k in G.values()),
                 "T-6h..T-0 >=1": sum(win(ts, k, 360, 0) for k in G.values())}
# per-game sample for pit
rows = []
for g, k in sorted(G.items(), key=lambda x: x[1]):
    b = [t for t in pit if t < k]
    rows.append({"game": g, "kickoff": iso(k), "pit_n_T-6h": sum(1 for t in pit if k - dt.timedelta(hours=6) <= t < k), "pit_latest_lead_min": round((k - max(b)).total_seconds() / 60, 1) if b else None,
                 "pa_n_T-6h": sum(1 for t in av if k - dt.timedelta(hours=6) <= t < k)})
res["per_game_pit_and_projection_counts"] = rows
res["by_kickoff_weekday_hour_uncovered_in_T-6h_pit"] = [r for r in rows if r["pit_n_T-6h"] == 0]
json.dump(res, open(f"{os.path.dirname(os.path.dirname(__file__))}/nfl_t90.json", "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "per_game_pit_and_projection_counts"}, indent=0))
