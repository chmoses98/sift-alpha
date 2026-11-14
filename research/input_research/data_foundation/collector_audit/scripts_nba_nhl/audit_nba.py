"""usage: python3 -I audit_nba.py <SCRATCH>   -> writes <SCRATCH>/nba_measured.json"""
import sys, glob, json, collections, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

S = sys.argv[1]
ARCH = f"{S}/nba/nba_arch"
PIT = f"{S}/nba/nba_pit/injury_pit"


def load_games():
    games = {}
    for f in sorted(glob.glob(f"{ARCH}/context/schedule/*/*.gz")):
        rows, err = read_rows(f)
        for r in rows:
            if r.get("start_time_utc"):
                games[r["game_id"]] = {"id": r["game_id"], "tip": parse_iso(r["start_time_utc"]),
                                       "home": r.get("home_tricode"), "away": r.get("away_tricode"),
                                       "home_id": r.get("home_team_id"), "away_id": r.get("away_team_id"),
                                       "status": r.get("status")}
    return sorted(games.values(), key=lambda g: g["tip"])


games = load_games()
out = {"schedule_games_loaded": len(games),
       "schedule_note": "game start times = union of the LAST schedule snapshot of each archive day (54 snapshots), latest value per game_id; games never present in those snapshots are invisible to the coverage test"}

# ---------------- STARTERS ----------------
sf = sorted(glob.glob(f"{ARCH}/context/starters/*/*.gz"))
captured = []
rows_all = []
files_rows = []
errs = 0
empty_files = 0
for f in sf:
    rows, err = read_rows(f)
    ts = fname_ts(f)
    if err:
        errs += 1
    if not rows:
        empty_files += 1
    files_rows.append((ts, rows))
    captured.append(ts)
    rows_all += rows
by_gs = collections.defaultdict(list)  # (game, side) -> obs
for r in rows_all:
    by_gs[(r["game_id"], r["side"])].append(r)
obs_times = sorted({parse_iso(r["observed_at_utc"]) for r in rows_all})
# per game
by_g = collections.defaultdict(list)
for r in rows_all:
    by_g[r["game_id"]].append(r)
gm_rows = []
for gid, rs in by_g.items():
    tip = parse_iso(rs[0]["tip_utc"])
    pre = [r for r in rs if parse_iso(r["observed_at_utc"]) < tip]
    obs_t = sorted({parse_iso(r["observed_at_utc"]) for r in pre})
    last_by_side = {}
    for r in sorted(pre, key=lambda r: r["observed_at_utc"]):
        last_by_side[r["side"]] = r
    first_conf = {}
    for r in sorted(pre, key=lambda r: r["observed_at_utc"]):
        if r["state"] == "CONFIRMED" and r["side"] not in first_conf:
            first_conf[r["side"]] = r["minutes_to_tip"]
    gm_rows.append({"game_id": gid, "tip_utc": iso(tip), "n_pre_tip_poll_times": len(obs_t),
                    "latest_pre_tip_min": round((tip - obs_t[-1]).total_seconds() / 60, 1) if obs_t else None,
                    "earliest_pre_tip_min": round((tip - obs_t[0]).total_seconds() / 60, 1) if obs_t else None,
                    "both_sides_confirmed_at_last_poll": len(last_by_side) == 2 and all(v["state"] == "CONFIRMED" for v in last_by_side.values()),
                    "first_confirmed_min_to_tip_by_side": first_conf})
span_lo, span_hi = min(obs_times), max(obs_times)
games_in_span = [g for g in games if span_lo <= g["tip"] + timedelta(hours=0) and g["tip"] - timedelta(hours=2) <= span_hi]
# games in the schedule within the starters-capture span that have NO starters row at all
have = set(by_g)
span_games = [g for g in games if parse_iso("2026-11-06T00:00:00Z") <= g["tip"] <= span_hi + timedelta(hours=1)]
missing = [g for g in span_games if g["id"] not in have and g["tip"] < span_hi]
confirmed_first = [min(v.values()) for v in (x["first_confirmed_min_to_tip_by_side"] for x in gm_rows) if v]
cov = game_coverage([g for g in games], obs_times, window_h=2.0, near_cadence_min=5.0, lo=span_lo - timedelta(hours=2), hi=span_hi)
# repeated identical observations per (game,side)
rep = tot = 0
for k, obs in by_gs.items():
    obs = sorted(obs, key=lambda r: r["observed_at_utc"])
    for a, b in zip(obs, obs[1:]):
        tot += 1
        if (a["state"], tuple(a["starter_espn_ids"]), a["n_roster_entries"]) == (b["state"], tuple(b["starter_espn_ids"]), b["n_roster_entries"]):
            rep += 1
raw_keys = collections.Counter()
for r in rows_all[:400]:
    for e in r["raw_entries"]:
        raw_keys.update(e.keys())
file_ts = sorted(t for t in captured)
st_state = collections.Counter(r["state"] for r in rows_all)
poll_gaps = gap_report(obs_times, 5.0)
_pg = [(parse_iso(r["observed_at_utc"])) for r in rows_all]
out["nba_starters"] = {
    "capture_instants_active_windows": active_gap_report(obs_times, games, 5.0, pre_h=2.0),
    "source_branch_path": "data-archive:context/starters (written by capture_worker -> nba_edge/data/starters.py capture_starters)",
    "files": len(sf), "team_rows": len(rows_all), "games": len(by_g), "empty_files": empty_files, "unreadable_files": errs,
    "capture_instants_from_row_observed_at": poll_gaps,
    "file_timestamps_distinct_days": len({t.date() for t in file_ts}),
    "coverage_T-2h_window_all_games_in_span": cov,
    "design_window_minutes": 120.0,
    "design_window_note": "capture_starters() only fetches games with tip in (now, now+120min]; nothing exists T-6h..T-2h by construction",
    "games_in_schedule_within_span_without_any_starters_row": len(missing),
    "games_without_row_sample": [{"id": g["id"], "tip": iso(g["tip"]), "match": f"{g['away']}@{g['home']}", "status": g["status"]} for g in missing[:15]],
    "state_counts": dict(st_state),
    "per_game_summary": {
        "n_games": len(gm_rows),
        "pre_tip_polls_per_game": dist([x["n_pre_tip_poll_times"] for x in gm_rows]),
        "latest_pre_tip_poll_min_before_tip": dist([x["latest_pre_tip_min"] for x in gm_rows if x["latest_pre_tip_min"] is not None]),
        "earliest_pre_tip_poll_min_before_tip": dist([x["earliest_pre_tip_min"] for x in gm_rows if x["earliest_pre_tip_min"] is not None]),
        "n_games_both_sides_CONFIRMED_at_last_pre_tip_poll": sum(1 for x in gm_rows if x["both_sides_confirmed_at_last_poll"]),
        "n_games_any_side_ever_confirmed": len(confirmed_first),
        "first_confirmed_minutes_to_tip": dist(confirmed_first),
        "sample_games": sorted(gm_rows, key=lambda x: x["tip_utc"])[:30],
    },
    "completeness": completeness(rows_all),
    "raw_entry_keys_first400_rows": dict(raw_keys),
    "source_publication_timestamp_in_payload": False,
    "source_timestamp_note": "ESPN core roster entries carry no publish/update time (raw_entries keys listed above); only observed_at_utc stamped after fetch, tip_utc and minutes_to_tip. Time a flag first appears is only bounded by poll spacing.",
    "dedup_delta_only": False,
    "dedup_note": f"full snapshot of every in-window game each cycle; {rep}/{tot} consecutive same-(game,side) observations are identical in state+starter ids+roster size ({round(100*rep/max(tot,1),1)}%), so absence of change is distinguishable from absence of capture (each poll writes a row, incl. NONE_PUBLISHED)",
    "failure_modes": {"FETCH_FAILED_rows": st_state.get("FETCH_FAILED", 0),
                      "rows_with_error": sum(1 for r in rows_all if r["error"]),
                      "rows_n_roster_entries_zero": sum(1 for r in rows_all if r["n_roster_entries"] == 0),
                      "rows_raw_entries_empty": sum(1 for r in rows_all if not r["raw_entries"]),
                      "NONE_PUBLISHED_rows_with_flagged_gt0_but_not_5": sum(1 for r in rows_all if r["state"] == "NONE_PUBLISHED" and 0 < r["n_starters_flagged"] != 5)},
    "schema_timeline": schema_timeline(files_rows),
}

# ---------------- INJURIES (archive) ----------------
inj = sorted(glob.glob(f"{ARCH}/context/injuries/*/*.gz"))
files_rows = []
caps = []
empty = 0
rows_all = []
lag = []
prev_sig = None
same_prev = 0
subset_prev = 0
comp = 0
latest_report_gap = []
src_counts = collections.Counter()
per_src = {}
for f in inj:
    rows, err = read_rows(f)
    ts = fname_ts(f)
    files_rows.append((ts, rows))
    caps.append(ts)
    if not rows:
        empty += 1
        continue
    sig = frozenset((r["source"], r["team_id"], r["player_name_raw"], r["status"], r["reason"], r["report_time_utc"], r["game_date_et"]) for r in rows)
    if prev_sig is not None:
        comp += 1
        if sig == prev_sig:
            same_prev += 1
    prev_sig = sig
    offr = [r for r in rows if r["source"] == "nba_official_pdf" and r["report_time_utc"]]
    if offr:
        rt = max(parse_iso(r["report_time_utc"]) for r in offr)
        obs = parse_iso(rows[0]["_observed_at_utc"])
        lag.append((obs - rt).total_seconds() / 60)
    for sname in ("nba_official_pdf", "espn_injuries"):
        sg = frozenset((r["team_id"], r["player_name_raw"], r["status"], r["reason"], r["report_time_utc"]) for r in rows if r["source"] == sname)
        d = per_src.setdefault(sname, {"prev": None, "same": 0, "cmp": 0, "absent": 0})
        if not sg:
            d["absent"] += 1
        else:
            if d["prev"] is not None:
                d["cmp"] += 1
                d["same"] += sg == d["prev"]
            d["prev"] = sg
    src_counts.update(r["source"] for r in rows)
    rows_all += rows
# games: pregame coverage, plus freshness of newest report visible to the capture just before tip
gcov = game_coverage(games, caps, window_h=6.0, near_cadence_min=10.0)
# newest official report_time visible at the last capture before tip, per game (team rows present?)
fr = []
fr_team = []
fr_idx = {ts: rows for ts, rows in files_rows}
ct = sorted(c for c in caps if fr_idx.get(c))
import bisect
for g in games:
    if g["tip"] < ct[0] + timedelta(hours=6) or g["tip"] > ct[-1]:
        continue
    i = bisect.bisect_left(ct, g["tip"]) - 1
    if i < 0:
        continue
    rows = fr_idx[ct[i]]
    rts = [parse_iso(r["report_time_utc"]) for r in rows if r["report_time_utc"] and r["source"] == "nba_official_pdf"]
    if not rts:
        continue
    fr.append((g["tip"] - max(rts)).total_seconds() / 60)
    hasteam = any(r["team_id"] in (g["home_id"], g["away_id"]) and r["game_date_et"] for r in rows)
    fr_team.append(hasteam)
out["nba_injuries"] = {
    "source": "data-archive:context/injuries (official NBA injury-report PDF rows; same capture_worker cycle)",
    "files": len(inj), "rows": len(rows_all), "empty_files": empty,
    "capture_instants": gap_report(caps, 15.0),
    "capture_instants_active_game_windows": active_gap_report(caps, games, 15.0),
    "per_source_repeat_stats": {k: {kk: vv for kk, vv in v.items() if kk != "prev"} for k, v in per_src.items()},
    "capture_instants_note": "scheduled cadence taken as the worker's 15-min far tier; designed tiers are 15/10/7/5 min (plan.py)",
    "per_game_pregame_coverage_T-6h": gcov,
    "newest_report_visible_before_tip_minutes_before_tip": dist(fr),
    "n_games_checked_for_report_freshness": len(fr),
    "games_where_a_team_row_present_in_last_pre_tip_capture_pct": round(100 * sum(fr_team) / max(len(fr_team), 1), 1),
    "report_time_to_observed_lag_min_per_file": dist(lag),
    "completeness": completeness(rows_all),
    "source_counts": dict(src_counts),
    "source_publication_timestamp_in_payload": True,
    "source_timestamp_note": "report_time_utc = nominal 15-min slot of the official PDF (separate from _observed_at_utc). No last_modified in the archive rows (it exists in the data-injury-pit branch).",
    "dedup_delta_only": False,
    "dedup_note": "each file holds BOTH the full latest official-PDF rows and the full ESPN injuries rows (mixed 'source' field); not delta-only. Identical-consecutive-snapshot stats per source are in per_source_repeat_stats.",
    "status_counts": dict(collections.Counter(r["status"] for r in rows_all)),
    "failure_modes": {"empty_files": empty, "game_id_null_pct": round(100 * sum(1 for r in rows_all if r["game_id"] is None) / max(len(rows_all), 1), 1),
                      "nba_id_null_pct": round(100 * sum(1 for r in rows_all if r["nba_id"] is None) / max(len(rows_all), 1), 1),
                      "status_unknown": sum(1 for r in rows_all if r["status"] == "unknown")},
    "schema_timeline": schema_timeline(files_rows),
}

# ---------------- PIT branch ----------------
man = [json.loads(l) for l in open(f"{PIT}/MANIFEST.jsonl") if l.strip()]
off = [m for m in man if m["kind"] == "official"]
esp = [m for m in man if m["kind"] == "espn"]
cap_off = [parse_iso(m["captured_at_utc"]) for m in off]
cap_esp = [parse_iso(m["captured_at_utc"]) for m in esp]
cap_all = cap_off + cap_esp
# fresh read of each official file for last_modified etc
off_rows = []
lm_lag = []
cap_lag = []
slot_to_cap = []
for m in off:
    rows, err = read_rows(f"{PIT}/{m['path']}")
    off_rows += rows
    if rows:
        lm = rows[0].get("last_modified_utc")
        rt = rows[0]["report_time_utc"]
        if lm:
            lm_lag.append((parse_iso(m["captured_at_utc"]) - parse_iso(lm)).total_seconds() / 60)
        cap_lag.append((parse_iso(m["captured_at_utc"]) - parse_iso(rt)).total_seconds() / 60)
esp_rows = []
esp_n = []
esp_age = []
for m in esp:
    rows, err = read_rows(f"{PIT}/{m['path']}")
    esp_n.append(len(rows))
    esp_rows += rows
    if rows:
        fa = parse_iso(rows[0]["fetched_at_utc"])
        ages = [(fa - parse_iso(r["entry_date_utc"])).total_seconds() / 3600 for r in rows if r.get("entry_date_utc")]
        esp_age.append(pct(ages, .5))
slots = sorted({m["slot_et"] for m in off})
pit_games = [g for g in games]
cov_off = game_coverage(pit_games, cap_off, window_h=6.0, near_cadence_min=60.0, lo=min(cap_off), hi=max(cap_off))
cov_esp = game_coverage(pit_games, cap_esp, window_h=6.0, near_cadence_min=60.0, lo=min(cap_esp), hi=max(cap_esp))
out["nba_injuries_pit"] = {
    "branch": "data-injury-pit (pit_injuries.yml cron 41 * * * *; append-only hash chain)",
    "manifest_lines": len(man), "official_files": len(off), "espn_files": len(esp),
    "official_captures": gap_report(cap_off, 60.0), "espn_captures": gap_report(cap_esp, 60.0),
    "all_captures": gap_report(cap_all, 60.0),
    "expected_hourly_runs_since_first_capture": int((max(cap_all) - min(cap_all)).total_seconds() // 3600),
    "delivery_ratio_espn_vs_hourly_cron": round(len(esp) / max((max(cap_all) - min(cap_all)).total_seconds() / 3600, 1), 3),
    "official_distinct_report_slots": len(slots), "official_first_slot_et": slots[0], "official_last_slot_et": slots[-1],
    "official_captured_minus_report_slot_min": dist(cap_lag),
    "official_captured_minus_last_modified_min": dist(lm_lag),
    "official_rows": len(off_rows), "official_completeness": completeness(off_rows),
    "official_status_counts": dict(collections.Counter(r["status"] for r in off_rows)),
    "espn_rows": len(esp_rows), "espn_rows_per_file": dist(esp_n), "espn_completeness": completeness(esp_rows),
    "espn_median_age_of_entry_hours_at_fetch_per_file": dist([x for x in esp_age if x is not None]),
    "per_game_pregame_coverage_official_T-6h": cov_off,
    "per_game_pregame_coverage_espn_T-6h": cov_esp,
    "dedup_note": "official: skipped when (slot,sha256) already captured -> delta-only by report; a skipped run leaves NO trace, so absence of a new file is NOT distinguishable from a missed cron run. espn: full snapshot every run that executes (no dedupe).",
    "source_publication_timestamp_in_payload": {"official": "report_time_utc (slot) and last_modified_utc (HTTP upload instant) separate from fetched_at_utc", "espn": "entry_date_utc per row (ESPN item update time) separate from fetched_at_utc"},
}
json.dump(out, open(f"{S}/nba_measured.json", "w"), indent=1, default=str)
print("ok")
