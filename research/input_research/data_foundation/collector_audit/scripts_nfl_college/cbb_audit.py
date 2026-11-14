import sys, os, glob, json, gzip, collections, statistics, datetime as dt
sys.path.insert(0, os.path.dirname(__file__))
from common import *
R = sys.argv[1]; A = f"{R}/cbb_availability-archive"; out = {}
files = sorted(glob.glob(f"{A}/captures/*/*/*/*.jsonl"))
names = [os.path.basename(f)[:-6] for f in files]
ftimes = [dt.datetime.strptime(n, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC) for n in names]
res = gap_stats(ftimes, 0.5)
res["scheduled_cadence_note"] = "availability-capture.yml cron '4,34 * * 1-4,11,12 *' every 30 min (Nov-Apr); per-game rows only when a game is inside a checkpoint window"
nrows = []; allr = []; empty_files = []
for f, n in zip(files, names):
    L = jl(f); nrows.append(len(L)); allr += L
    if not L: empty_files.append(n)
res["files"] = len(files); res["empty_capture_files"] = len(empty_files); res["empty_capture_files_names"] = empty_files
res["rows_total"] = len(allr); res["rows_per_file"] = {"min": min(nrows), "median": statistics.median(nrows), "max": max(nrows)}
res["schemas"] = dict(collections.Counter(r["schema"] for r in allr))
res["keys_sets"] = len({tuple(sorted(r)) for r in allr})
fl = collections.Counter()
for r in allr:
    for k, v in r.items(): fl[(k, v not in (None, ""))] += 1
res["field_nonnull_pct"] = {k: round(100 * fl[(k, True)] / (fl[(k, True)] + fl[(k, False)]), 2) for k in sorted({k for k, _ in fl})}
res["status_counts"] = dict(collections.Counter(r["status"] for r in allr)); res["native_status"] = dict(collections.Counter(r["native_status"] for r in allr).most_common(10))
res["source_counts"] = dict(collections.Counter(r["source"] for r in allr)); res["confidence_counts"] = dict(collections.Counter(r["confidence"] for r in allr))
res["checkpoint_counts_rows"] = dict(collections.Counter(r["checkpoint"] for r in allr))
res["rows_with_injury_status"] = sum(1 for r in allr if r["injury_status"]); res["rows_with_injury_comment"] = sum(1 for r in allr if r["injury_comment"])
res["rows_status_not_available"] = sum(1 for r in allr if r["status"] != "available")
res["rows_status_changed_true"] = sum(1 for r in allr if r["status_changed"]); res["rows_first_capture_for_game_true"] = sum(1 for r in allr if r["first_capture_for_game"])
bad = sum(1 for r in allr if abs((P(r["tip_utc"]) - P(r["captured_at"])).total_seconds() / 60 - r["minutes_to_tip"]) > 1)
res["minutes_to_tip_inconsistent_rows"] = bad
res["source_timestamp_present"] = "NO separate source publication time: only injury_date (null) ; captured_at is our retrieval time"
# per-game
g = collections.defaultdict(lambda: collections.defaultdict(set)); tips = {}; gp = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.Counter()))
caps_game = collections.defaultdict(dict)
for r in allr:
    gid = r["game_id"]; tips[gid] = P(r["tip_utc"]); caps_game[gid][r["captured_at"]] = (r["checkpoint"], r["minutes_to_tip"])
    gp[gid][r["captured_at"]][r["side"]] += 1
rows = []
CP = ["T-24h", "T-6h", "T-90m", "T-30m", "latest"]
for gid, cs in caps_game.items():
    ks = sorted(cs.items())
    cps = {c for _, (c, m) in ks}
    mins = [m for _, (c, m) in ks]
    pre = [m for m in mins if m > 0]
    both = sum(1 for t, sd in gp[gid].items() if len(sd) == 2)
    rows.append({"game_id": gid, "tip": iso(tips[gid]), "n_captures": len(cs), "checkpoints": sorted(cps), "n_in_T-6h": sum(1 for m in mins if 0 < m <= 360), "latest_lead_min": round(min(pre), 1) if pre else None, "earliest_lead_h": round(max(mins) / 60, 1), "captures_with_both_sides": both})
res["per_game"] = {"games": len(rows), "with_>=1_capture_in_T-6h": sum(1 for r in rows if r["n_in_T-6h"] >= 1), "games_having_each_checkpoint": {c: sum(1 for r in rows if c in r["checkpoints"]) for c in CP},
   "games_with_all_5_checkpoints": sum(1 for r in rows if len(set(CP) & set(r["checkpoints"])) == 5), "n_captures_per_game_median": statistics.median(r["n_captures"] for r in rows),
   "latest_lead_min": {"median": round(statistics.median(r["latest_lead_min"] for r in rows if r["latest_lead_min"] is not None), 1), "p90": round(pct([r["latest_lead_min"] for r in rows if r["latest_lead_min"] is not None], .9), 1), "max": max(r["latest_lead_min"] for r in rows if r["latest_lead_min"] is not None)},
   "games_latest_within_30min": sum(1 for r in rows if r["latest_lead_min"] is not None and r["latest_lead_min"] <= 30), "games_latest_within_120min": sum(1 for r in rows if r["latest_lead_min"] is not None and r["latest_lead_min"] <= 120), "sample": sorted(rows, key=lambda r: r["tip"])}
# roster size / teams
teams = {(r["game_id"], r["espn_team_id"]) for r in allr}
res["distinct_games"] = len({r["game_id"] for r in allr}); res["distinct_game_teams"] = len(teams); res["distinct_players"] = len({r["player_id"] for r in allr})
res["players_per_game_team_median"] = statistics.median(collections.Counter((r["game_id"], r["espn_team_id"], r["captured_at"]) for r in allr).values())
# raw league injuries
raws = sorted(glob.glob(f"{A}/raw/*/*/*/*/league_injuries.json.gz"))
ne = 0; byts = []; tstamps = []; cnt = []
for f in raws:
    d = jload(f); n = len(d.get("injuries", [])) if isinstance(d, dict) else -1
    cnt.append(n); ne += n > 0; tstamps.append(d.get("timestamp"))
res["raw_league_injuries"] = {"files": len(raws), "nonempty": ne, "max_items": max(cnt), "payload_has_source_timestamp": all(t for t in tstamps), "keys": ["injuries", "season", "status", "timestamp"]}
# delta semantics: do consecutive captures of same game contain identical rows?
chg = sum(1 for r in allr if r["status_changed"])
res["delta_semantics"] = "full roster per (game, side) at each in-window capture (not delta); status_changed flag vs previous capture; state file keeps last status per team|player"
# dedup: repeated full rosters
by = collections.defaultdict(list)
for r in allr: by[(r["game_id"], r["espn_athlete_id"])].append(r["captured_at"])
res["rows_per_game_player_median"] = statistics.median(len(v) for v in by.values())
# per-file gaps only where files non-empty
ne_times = [t for t, n in zip(ftimes, nrows) if n]
res["nonempty_files_cadence"] = gap_stats(ne_times, 0.5)
out["cbb_availability_archive"] = res
json.dump(out, open(f"{os.path.dirname(os.path.dirname(__file__))}/cbb_partial.json", "w"), indent=1, default=str)
x = dict(res); x["per_game"] = {k: v for k, v in res["per_game"].items() if k != "sample"}; x.pop("field_nonnull_pct"); x["nonempty_files_cadence"].pop("largest_10_gaps"); x["largest_10_gaps"] = x["largest_10_gaps"][:4]
print(json.dumps(x, indent=0, default=str)[:6000])
