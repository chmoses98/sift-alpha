"""usage: python3 -I audit_nhl.py <SCRATCH>   -> writes <SCRATCH>/nhl_measured.json"""
import sys, glob, json, collections, os, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

S = sys.argv[1]
ARCH = f"{S}/nhl/nhl_arch"
PROBE = f"{S}/nhl/nhl_probe"

# ---- schedule: union of last snapshot per archive day
games = {}
for f in sorted(glob.glob(f"{S}/nhl/sched/*/*.gz")):
    rows, _ = read_rows(f)
    for r in rows:
        if r.get("start_time_utc"):
            games[r["game_id"]] = {"id": str(r["game_id"]), "tip": parse_iso(r["start_time_utc"]), "home": r.get("home_abbrev"),
                                   "away": r.get("away_abbrev"), "home_id": r.get("home_team_id"), "away_id": r.get("away_team_id"),
                                   "season_type": r.get("season_type")}
games = sorted(games.values(), key=lambda g: g["tip"])
gid = {g["id"]: g for g in games}
out = {"schedule_games_loaded": len(games),
       "schedule_note": "tip = start_time_utc from the LAST schedule snapshot of each archive day (43 snapshots), latest value per game_id"}

# ---------------- GOALIES (archive) ----------------
gf = sorted(glob.glob(f"{ARCH}/context/goalie_observations/*/*.gz"))
files_rows = []
caps = []
rows_all = []
empty = 0
for f in gf:
    rows, err = read_rows(f)
    ts = fname_ts(f)
    files_rows.append((ts, rows))
    caps.append(ts)
    if not rows:
        empty += 1
    rows_all += rows
dfo = [r for r in rows_all if r["source"] == "dailyfaceoff"]
# per game: obs sets keyed by file ts
by_gt = collections.defaultdict(list)  # game -> list of (file_ts, row)
for ts, rows in files_rows:
    for r in rows:
        by_gt[str(r["game_id"])].append((ts, r))
gm = []
for g in games:
    if g["id"] not in by_gt:
        continue
    tip = g["tip"]
    obs = by_gt[g["id"]]
    pre = [(t, r) for t, r in obs if t < tip and r["source"] == "dailyfaceoff"]
    times = sorted({t for t, r in pre})
    win = [t for t in times if t >= tip - timedelta(hours=6)]
    last_by_team = {}
    for t, r in sorted(pre, key=lambda x: x[0]):
        last_by_team[r["team_id"]] = (t, r)
    first_conf = {}
    for t, r in sorted(pre, key=lambda x: x[0]):
        if r["status"] == "CONFIRMED" and r["team_id"] not in first_conf:
            first_conf[r["team_id"]] = (tip - t).total_seconds() / 60
    srcrep = [(parse_iso(r["source_reported_at_utc"])) for t, r in pre if r["source_reported_at_utc"]]
    gm.append({"game_id": g["id"], "tip": tip, "n_caps_6h": len(win), "latest_min": round((tip - times[-1]).total_seconds() / 60, 1) if times else None,
               "teams_with_obs": len(last_by_team), "both_confirmed_last_pre": len(last_by_team) == 2 and all(v[1]["status"] == "CONFIRMED" for v in last_by_team.values()),
               "final_status": sorted(v[1]["status"] for v in last_by_team.values()), "first_confirmed_min": first_conf,
               "n_obs_total": len(obs)})
caps_dfo = sorted({t for ts_rows in files_rows for t in [ts_rows[0]] if ts_rows[1]})
span_lo, span_hi = min(caps), max(caps)
covg = game_coverage(games, caps, window_h=6.0, near_cadence_min=10.0)
nogames = [g for g in games if span_lo + timedelta(hours=6) <= g["tip"] <= span_hi and g["id"] not in by_gt]
# source-publication-time lag: observed minus source_reported (dfo only, non-null)
lag = [(parse_iso(r["observed_at_utc"]) - parse_iso(r["source_reported_at_utc"])).total_seconds() / 3600 for r in dfo if r["source_reported_at_utc"]]
# stale repeats: same (game,team,status,name,source_reported) in consecutive files
last = {}
rep = tot = 0
for ts, rows in files_rows:
    for r in rows:
        if r["source"] != "dailyfaceoff":
            continue
        k = (r["game_id"], r["team_id"])
        sig = (r["status"], r["player_name"], r["source_reported_at_utc"])
        if k in last:
            tot += 1
            rep += last[k] == sig
        last[k] = sig
changes = collections.Counter()
last = {}
for ts, rows in files_rows:
    for r in rows:
        if r["source"] != "dailyfaceoff":
            continue
        k = (r["game_id"], r["team_id"])
        if k in last and last[k][0] != r["status"]:
            changes[f"{last[k][0]}->{r['status']}"] += 1
        if k in last and last[k][1] != r["player_name"]:
            changes["goalie_name_changed"] += 1
        last[k] = (r["status"], r["player_name"])
final_conf_goalie_change = 0
out["nhl_goalies"] = {
    "source": "data-archive:context/goalie_observations (capture_worker; dailyfaceoff + nhl_api_boxscore)",
    "files": len(gf), "rows": len(rows_all), "empty_files": empty,
    "capture_instants": gap_report(caps, 15.0),
    "capture_instants_active_game_windows": active_gap_report(caps, games, 15.0),
    "per_game_pregame_coverage_T-6h": covg,
    "games_in_schedule_within_span_without_any_goalie_row": len(nogames),
    "games_without_row_sample": [{"id": g["id"], "tip": iso(g["tip"]), "match": f"{g['away']}@{g['home']}", "type": g["season_type"]} for g in nogames[:10]],
    "per_game": {
        "n_games_with_goalie_rows": len(gm),
        "n_games_both_teams_CONFIRMED_at_last_pre_start_capture": sum(1 for x in gm if x["both_confirmed_last_pre"]),
        "n_games_with_two_team_obs": sum(1 for x in gm if x["teams_with_obs"] == 2),
        "first_confirmed_minutes_before_start": dist([min(x["first_confirmed_min"].values()) for x in gm if x["first_confirmed_min"]]),
        "first_confirmed_minutes_before_start_all_teams": dist([v for x in gm for v in x["first_confirmed_min"].values()]),
        "final_pre_start_status_counts": dict(collections.Counter(s for x in gm for s in x["final_status"])),
    },
    "status_counts": dict(collections.Counter(r["status"] for r in rows_all)),
    "source_counts": dict(collections.Counter(r["source"] for r in rows_all)),
    "completeness_all": completeness(rows_all),
    "completeness_dailyfaceoff": completeness(dfo),
    "source_publication_timestamp_in_payload": True,
    "source_timestamp_note": "source_reported_at_utc (dailyfaceoff report time) exists separately from observed_at_utc/_observed_at_utc, but is null for PROJECTED rows (see completeness) and present for CONFIRMED/PROBABLE.",
    "source_reported_to_observed_lag_hours_where_present": dist(lag),
    "dedup_delta_only": False,
    "dedup_note": f"full snapshot of all slate goalie observations each cycle; {rep}/{tot} consecutive same-(game,team) observations are identical in status+name+source_reported_at ({round(100*rep/max(tot,1),1)}%). Absence-of-change is distinguishable from absence-of-capture because each capture file lists every row.",
    "status_transitions_per_game_team": dict(changes),
    "failure_modes": {"empty_files": empty, "player_id_null_pct": round(100 * sum(1 for r in rows_all if r["player_id"] is None) / len(rows_all), 1)},
    "schema_timeline": schema_timeline(files_rows),
}

# ---------------- PROBE ----------------
pr = []
for f in sorted(glob.glob(f"{PROBE}/obs/*/*.gz")):
    rows, _ = read_rows(f)
    pr += rows
man = []
for m in glob.glob(f"{PROBE}/MANIFEST.*.jsonl"):
    man += [json.loads(l) for l in open(m) if l.strip()]
polled = [r for r in pr if r.get("polled_at_utc")]
by_ge = collections.defaultdict(list)
for r in polled:
    by_ge[(r["game_id"], r["endpoint"])].append(r)
pgames = {}
for r in polled:
    pgames.setdefault(r["game_id"], parse_iso(r["game_start_utc"]))
changes = 0
cmp_ = 0
for k, rs in by_ge.items():
    rs = sorted(rs, key=lambda r: r["polled_at_utc"])
    for a, b in zip(rs, rs[1:]):
        cmp_ += 1
        changes += a["sha256"] != b["sha256"]
ids_by_game = {}
for r in polled:
    gi = (r.get("interesting") or {}).get("matchup.goalieComparison")
    if gi:
        ids_by_game.setdefault(r["game_id"], []).append((r["lead_min"], tuple(gi["ids"])))
out["nhl_goalies_probe"] = {
    "branch": "lineup-probe-data (nhl_lineup_probe.yml; manual dispatch only; rights-ack input required)",
    "manifest_files": len(man), "obs_rows": len(pr), "polled_rows": len(polled),
    "row_kinds": {f"{k[0]}|{k[1]}": v for k, v in collections.Counter((r.get("endpoint"), r.get("status")) for r in pr).items()},
    "games": len(pgames), "game_starts_utc": sorted(iso(v) for v in pgames.values()),
    "first_poll_utc": min(r["polled_at_utc"] for r in polled), "last_poll_utc": max(r["polled_at_utc"] for r in polled),
    "distinct_poll_days_utc": len({r["polled_at_utc"][:10] for r in polled}),
    "scheduled_offsets_min_before_start": sorted({r["offset_min"] for r in polled}),
    "polls_per_game_endpoint": dist([len(v) for v in by_ge.values()]),
    "lead_min_actual_minus_offset": dist([abs(r["lead_min"] - r["offset_min"]) for r in polled]),
    "consecutive_poll_payload_changes": f"{changes}/{cmp_}",
    "fields_in_obs": sorted({k for r in polled for k in r}),
    "completeness": completeness(polled),
    "payload_stored": "raw/ files hold gzip+base64 body for a subset (17 files); obs rows keep only sha256 + 'interesting' id lists (goalieComparison ids, scratches). No explicit 'confirmed starter' field is extracted.",
    "source_publication_timestamp_in_payload": False,
    "failure_modes": {"skipped_late_rows": sum(1 for r in pr if r.get("status") == "skipped_late"),
                      "non_200": sum(1 for r in polled if r.get("status") != 200)},
    "schema_timeline_note": "single 3-run campaign on 2026-10-25/26; no schema drift measurable",
}
json.dump(out, open(f"{S}/nhl_goalies_measured.json", "w"), indent=1, default=str)
print("goalies ok")
