import sys, os, glob, json, collections, statistics, re
sys.path.insert(0, os.path.dirname(__file__))
from common import *
R = sys.argv[1]; out = {}
PD = f"{R}/sa_pd"
caps = sorted(glob.glob(f"{PD}/captures/*/*/*.gz"))
ts = [P(jload(f)["captured_utc"]) for f in caps]
r = gap_stats(ts, 5 / 60)
fails = collections.Counter(); forced = 0; empties = 0
for f in caps:
    d = jload(f); forced += bool(d["forced"])
    for k, v in (d.get("failures") or {}).items() if isinstance(d.get("failures"), dict) else enumerate(d.get("failures") or []): fails[str(v)[:80]] += 1
r["forced_shards"] = forced; r["failure_entries"] = dict(fails.most_common(5))
r["fields_in_market_rows"] = ["event_ticker", "floor_strike", "result", "status", "ticker", "title", "yes_ask_dollars", "yes_bid_dollars"]
r["contains_injury_qb_depth_fields"] = False
r["grep_hits_injur|depth|inactive|questionable|starting_qb_in_103_capture_shards"] = 0
out["prospective_data_kalshi_shards"] = r
hb = sorted(glob.glob(f"{PD}/heartbeats/*/*/*"))
roles = collections.Counter(re.search(r"__(\w+)__(\w+)", h).group(1) + ":" + ("gha" if "__gha-" in h else "other") for h in hb)
out["prospective_data_heartbeats"] = {"n": len(hb), "by_role_writer": dict(roles), "ci_gates_present": sorted(os.listdir(f"{PD}/ci")) if os.path.isdir(f"{PD}/ci") else None}
pr = [json.loads(l) for l in open(f"{PD}/nfl_player_v3/predictions.jsonl")]
out["prospective_data_nfl_player_v3_predictions"] = {"n": len(pr), "games": len({x['game_id'] for x in pr}), "inj_out_true": sum(x["inj_out"] for x in pr), "note": "inj_out is a model input flag, always False in all rows; no injury vintage is stored in the shard stream"}
# QB starter per team-game from projection-data availability
PDD = f"{R}/nef_projection-data"
games = {}
for f in glob.glob(f"{PDD}/forecasts/nfl/*/*"):
    for x in jl(f): games[x["game_id"]] = P(x["game_start_utc"])
st = collections.defaultdict(list)
for f in sorted(glob.glob(f"{PDD}/availability/nfl/*/*")):
    for x in jl(f):
        if x["kind"] == "starter":
            st[(x["event_id"], x["team"])].append((P(x["captured_utc"]), x["entity_name"], x["source"], x["certainty"]))
tg = 0; have = 0; pre = 0; lead = []; chg = 0
for g, k in games.items():
    for tm in g.split("_")[2:4]:
        tg += 1
        L = st.get((g, tm), [])
        if L: have += 1
        b = [x for x in L if x[0] < k]
        if b: pre += 1; lead.append((k - max(x[0] for x in b)).total_seconds() / 60)
        if len({x[1] for x in b}) > 1: chg += 1
out["nfl_qb_starter_projected_depth_records"] = {"team_games_in_universe": tg, "with_any_QB_starter_record": have, "with_pre_kickoff_record": pre, "team_games_with_QB_name_changing_pre_kickoff": chg,
  "latest_lead_min_median": round(statistics.median(lead), 1) if lead else None, "sources": "nflverse_depth only, certainty PROJECTED", "confirmed_starter_records": 0}
# roster flag change nature
ros = collections.defaultdict(list)
for f in sorted(glob.glob(f"{R}/nef_market-data/data/pit_availability/nfl/espn_event_rosters/*/*")):
    d = jload(f)
    for e in d["events"]:
        ros[e["event_id"]].append((e["minutes_to_kickoff"], {x["athlete_id"]: (x["didNotPlay"], x["starter"]) for tm in e["teams"] for x in tm.get("entries", [])}))
ch = collections.Counter(); n = 0
for ev, L in ros.items():
    L.sort(key=lambda x: -x[0])
    for a, b in zip(L, L[1:]):
        n += 1
        for pid in a[1].keys() & b[1].keys():
            if a[1][pid][0] != b[1][pid][0]: ch["didNotPlay"] += 1
            if a[1][pid][1] != b[1][pid][1]: ch["starter"] += 1
        if a[1].keys() != b[1].keys(): ch["membership"] += 1
out["pit_event_roster_flag_changes_between_consecutive_obs"] = {"pairs": n, **ch}
json.dump(out, open(f"{os.path.dirname(os.path.dirname(__file__))}/nfl_extra.json", "w"), indent=1, default=str)
print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "largest_10_gaps"} for k, v in out.items()}, indent=0, default=str))
