"""usage: python3 -I audit_nhl_inj.py <SCRATCH> -> <SCRATCH>/nhl_injuries_measured.json (needs sched from audit_nhl.py layout)"""
import sys, glob, json, collections, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
S = sys.argv[1]
ARCH = f"{S}/nhl/nhl_arch"
games = {}
for f in sorted(glob.glob(f"{S}/nhl/sched/*/*.gz")):
    for r in read_rows(f)[0]:
        if r.get("start_time_utc"):
            games[r["game_id"]] = {"id": str(r["game_id"]), "tip": parse_iso(r["start_time_utc"]), "home_id": r.get("home_team_id"), "away_id": r.get("away_team_id")}
games = sorted(games.values(), key=lambda g: g["tip"])
fs = sorted(glob.glob(f"{ARCH}/context/injuries/*/*.gz"))
files_rows, caps, rows_all = [], [], []
empty = bad = 0
prev = None; same = cmp_ = 0
chg = collections.Counter()
age = []
for f in fs:
    rows, err = read_rows(f)
    ts = fname_ts(f)
    bad += bool(err)
    empty += not rows
    files_rows.append((ts, rows)); caps.append(ts); rows_all += rows
    sig = frozenset((r["team_id"], r["player_name"], r["status"], r["detail"], r["reported"], r["return_date"]) for r in rows)
    if prev is not None:
        cmp_ += 1; same += sig == prev
        chg["rows_added"] += len(sig - prev); chg["rows_removed"] += len(prev - sig)
    prev = sig
    for r in rows[:: max(1, len(rows) // 30)]:
        if r["reported"]:
            age.append((parse_iso(r["_observed_at_utc"]) - parse_iso(r["reported"])).total_seconds() / 3600)
# per game: captures in window + latest capture + whether either team has any injury row in last pre-tip capture
import bisect
idx = {ts: rows for ts, rows in files_rows}
ct = sorted(caps)
teams_rows = []
for g in games:
    if g["tip"] < ct[0] + timedelta(hours=6) or g["tip"] > ct[-1]:
        continue
    i = bisect.bisect_left(ct, g["tip"]) - 1
    if i < 0: continue
    rows = idx[ct[i]]
    teams_rows.append(sum(1 for r in rows if r["team_id"] in (g["home_id"], g["away_id"])))
# newest 'reported' within the last pre-tip capture for the two teams: staleness
rep_age = []
for g in games:
    if g["tip"] < ct[0] + timedelta(hours=6) or g["tip"] > ct[-1]: continue
    i = bisect.bisect_left(ct, g["tip"]) - 1
    rs = [parse_iso(r["reported"]) for r in idx[ct[i]] if r["team_id"] in (g["home_id"], g["away_id"]) and r["reported"]]
    if rs: rep_age.append((g["tip"] - max(rs)).total_seconds() / 3600)
out = {"nhl_injuries": {
    "source": "data-archive:context/injuries (ESPN injuries endpoint snapshot via capture_worker)",
    "files": len(fs), "rows": len(rows_all), "empty_files": empty, "unreadable_files": bad,
    "rows_per_file": dist([len(r) for _, r in files_rows]),
    "capture_instants": gap_report(caps, 15.0),
    "capture_instants_active_game_windows": active_gap_report(caps, games, 15.0),
    "per_game_pregame_coverage_T-6h": game_coverage(games, caps, 6.0, 10.0),
    "n_games_checked_team_rows_in_last_pre_tip_capture": len(teams_rows),
    "games_with_zero_team_rows_pct": round(100 * sum(1 for x in teams_rows if x == 0) / max(len(teams_rows), 1), 1),
    "newest_team_report_age_at_tip_hours": dist(rep_age),
    "status_counts": dict(collections.Counter(r["status"] for r in rows_all)),
    "completeness": completeness(rows_all),
    "source_publication_timestamp_in_payload": True,
    "source_timestamp_note": "'reported' (ESPN item date, minute resolution) is separate from _observed_at_utc; it is the report time of the NEWEST update for that player, not a history of status changes. The row age at observation (sampled) is in age_hours.",
    "age_hours_reported_to_observed_sampled": dist(age),
    "dedup_delta_only": False,
    "dedup_note": f"full ESPN list every capture; {same}/{cmp_} consecutive files have an identical row set; rows added/removed between consecutive files: {dict(chg)}. Absence of change is distinguishable from absence of capture (every capture writes the whole list).",
    "failure_modes": {"empty_files": empty, "unreadable_files": bad, "espn_id_null_pct": round(100 * sum(1 for r in rows_all if r["espn_id"] is None) / max(len(rows_all), 1), 1),
                      "detail_null_pct": round(100 * sum(1 for r in rows_all if r["detail"] is None) / max(len(rows_all), 1), 1),
                      "no_history_of_status_before_first_capture": True},
    "schema_timeline": schema_timeline(files_rows),
}}
json.dump(out, open(f"{S}/nhl_injuries_measured.json", "w"), indent=1, default=str)
print("nhl inj ok")
