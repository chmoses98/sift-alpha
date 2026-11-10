import sys, os, glob, json, re, collections, statistics, hashlib, datetime as dt
sys.path.insert(0, os.path.dirname(__file__))
from common import *
R = sys.argv[1]  # repos dir
out = {}
PIT = f"{R}/nef_market-data/data/pit_availability/nfl"
CTX = f"{R}/nef_market-data/data"
PD = f"{R}/nef_projection-data"
# ---------- game universe from projection-data forecasts
games = {}
for f in glob.glob(f"{PD}/forecasts/nfl/*/*"):
    for r in jl(f):
        g = r.get("game_id"); k = P(r.get("game_start_utc"))
        if g and k: games[g] = k
out["game_universe"] = {"n_games": len(games), "min_kickoff": iso(min(games.values())), "max_kickoff": iso(max(games.values())),
                        "source": "projection-data forecasts/nfl game_start_utc (weeks 6-9 forecasts only)"}
# ---------- ESPN injuries pit
def espn_series(files, tsfun):
    caps = []
    for f in files:
        d = jload(f); caps.append((tsfun(d, f), d))
    return caps
def analyze_espn(caps, label, sched_h):
    times = [t for t, _ in caps]
    res = {"series": label}
    res.update(gap_stats(times, sched_h))
    rows = 0; pathc = collections.Counter(); tot = 0; ages = []; nqb_teams = []; qbstat = collections.Counter()
    date_after_capture = 0; rowsn = 0; teamsets = []
    same_as_prev = 0; prev = None; newest_ages = []
    for t, d in caps:
        inj = d["payload"]["injuries"]
        teams_with_qb = 0
        newest = None
        for tm in inj:
            hasqb = False
            for r in tm["injuries"]:
                rowsn += 1
                for p, v in flat(r):
                    tot_p = p
                    pathc[(p, v is not None and v != "" and v != [])] += 1
                dd = P(r.get("date"))
                if dd:
                    if dd > t: date_after_capture += 1
                    ages.append((t - dd).total_seconds() / 3600)
                    if newest is None or dd > newest: newest = dd
                if (r.get("athlete", {}).get("position", {}) or {}).get("abbreviation") == "QB":
                    hasqb = True; qbstat[(r.get("status") or "")] += 1
            teams_with_qb += hasqb
        nqb_teams.append(teams_with_qb)
        if newest: newest_ages.append((t - newest).total_seconds() / 3600)
        h = hashlib.sha256(json.dumps(inj, sort_keys=True).encode()).hexdigest()
        if h == prev: same_as_prev += 1
        prev = h
    paths = sorted({p for p, _ in pathc})
    res["rows_total"] = rowsn
    res["rows_per_capture_median"] = statistics.median([sum(len(tm["injuries"]) for tm in d["payload"]["injuries"]) for _, d in caps])
    res["field_nonnull_pct"] = {p: round(100 * pathc[(p, True)] / (pathc[(p, True)] + pathc[(p, False)]), 1) for p in paths}
    res["row_date_after_capture_count"] = date_after_capture
    res["row_age_h_(capture-row.date)"] = {"median": round(statistics.median(ages), 1), "p90": round(pct(ages, .9), 1), "max": round(max(ages), 1)}
    res["newest_entry_age_h_per_capture"] = {"median": round(statistics.median(newest_ages), 2), "p90": round(pct(newest_ages, .9), 2), "max": round(max(newest_ages), 2)}
    res["teams_with_any_QB_entry_per_capture"] = {"median": statistics.median(nqb_teams), "min": min(nqb_teams), "max": max(nqb_teams), "of": 32}
    res["QB_status_counts_all_rows"] = dict(qbstat)
    res["identical_payload_to_previous_capture"] = same_as_prev
    res["separate_source_timestamp"] = "yes: row.date (ESPN note/report time) <= capture meta.retrieved_at"
    return res
pit_files = sorted(glob.glob(f"{PIT}/espn_injuries/*/*.json.gz"))
pit = espn_series(pit_files, lambda d, f: P(d["meta"]["retrieved_at"]))
out["pit_espn_injuries"] = analyze_espn(pit, "market-data data/pit_availability/nfl/espn_injuries", 6)

ctx_files = sorted(glob.glob(f"{CTX}/context/*/*espn_injuries.json"))
ctx_times = []; ctx_rows = collections.Counter(); ctx_n = 0; nonnull = collections.Counter(); qb_teams = []
for f in ctx_files:
    d = jload(f)
    t = P(d["retrieved_at"]); ctx_times.append(t)
    rows = d.get("injuries")
    if rows is None:
        rows = []
        for tm in d["payload"]["injuries"]:
            for r in tm["injuries"]:
                rows.append({"position": (r.get("athlete", {}).get("position", {}) or {}).get("abbreviation"), "team": tm["displayName"], "date": r.get("date"), "status": r.get("status"), "athlete_id": None})
    ctx_n += len(rows)
    for r in rows:
        for k, v in r.items(): nonnull[(k, v not in (None, ""))] += 1
    qb_teams.append(len({r["team"] for r in rows if r.get("position") == "QB"}))
ctx_res = gap_stats(ctx_times, 3)
ctx_res["rows_total"] = ctx_n
ctx_res["field_nonnull_pct_flat_rows"] = {k: round(100 * nonnull[(k, True)] / (nonnull[(k, True)] + nonnull[(k, False)]), 1) for k in sorted({k for k, _ in nonnull})}
ctx_res["teams_with_QB_entry_median"] = statistics.median(qb_teams)
ctx_res["note"] = "legacy context-capture.yml (cron 23 */3); last capture in market-data is the one listed in last_utc -- stopped relative to today 2026-11-10"
out["ctx_espn_injuries_legacy"] = ctx_res
# ---------- projection-data availability/nfl (sift.availability.v1)
av_files = sorted(glob.glob(f"{PD}/availability/nfl/*/*"))
av_times = []; sources = collections.Counter(); kinds = collections.Counter(); status = collections.Counter(); cert = collections.Counter()
fields = collections.Counter(); nrec = 0; lag = []; nrecs = []; ev_in_cap = []; per_cap_sources = []
prev_keys = None; new_frac = []; qb_rec = collections.Counter(); qbpos = 0; keyset_hist = collections.Counter()
for f in av_files:
    L = jl(f); t = None
    nrecs.append(len(L)); srcs = set()
    keys = set()
    for r in L:
        t = P(r["captured_utc"]); nrec += 1
        sources[r["source"]] += 1; kinds[r["kind"]] += 1; status[(r["source"], r["status"])] += 1; cert[r["certainty"]] += 1
        srcs.add(r["source"])
        for k, v in r.items(): fields[(k, v not in (None, ""))] += 1
        for k, v in (r.get("detail") or {}).items(): fields[("detail." + k, v not in (None, ""))] += 1
        su = P(r.get("source_updated_utc"))
        if su: lag.append((t - su).total_seconds() / 3600)
        keys.add((r["source"], r["entity_id"], r["event_id"], r["status"], json.dumps(r.get("detail"), sort_keys=True)))
        if (r.get("detail") or {}).get("position") == "QB": qbpos += 1; qb_rec[(r["source"], r["status"])] += 1
    av_times.append(t); per_cap_sources.append(sorted(srcs))
    if prev_keys is not None: new_frac.append(len(keys - prev_keys) / max(len(keys), 1))
    prev_keys = keys
avr = gap_stats(av_times, None)
avr["records_total"] = nrec; avr["records_per_file"] = {"min": min(nrecs), "median": statistics.median(nrecs), "max": max(nrecs)}
avr["by_source"] = dict(sources); avr["by_kind"] = dict(kinds); avr["by_source_status"] = {f"{a}|{b}": v for (a, b), v in status.items()}; avr["certainty"] = dict(cert)
avr["field_nonnull_pct"] = {k: round(100 * fields[(k, True)] / (fields[(k, True)] + fields[(k, False)]), 1) for k in sorted({k for k, _ in fields})}
if lag: avr["capture_minus_source_updated_h"] = {"n": len(lag), "median": round(statistics.median(lag), 1), "p90": round(pct(lag, .9), 1), "max": round(max(lag), 1), "negative": sum(1 for x in lag if x < 0)}
avr["qb_records"] = {"n": qbpos, "by_source_status": {f"{a}|{b}": v for (a, b), v in qb_rec.items()}}
avr["fraction_records_not_in_previous_file_median"] = round(statistics.median(new_frac), 3) if new_frac else None
avr["scheduled_cadence_note"] = "written by projection-foundation.yml: refresh slots Thu 23:03/23:15, Sun 12:20/12:32/15:52/16:04/19:02/19:14/23:12/23:24, Mon 23:03/23:15 UTC + fresh Thu/Sat 13:11, Sun 08:11; skip-if-identical (write-once, dedup)"
out["projection_data_availability_nfl"] = avr
# ---------- event rosters
ros = []
for f in sorted(glob.glob(f"{PIT}/espn_event_rosters/*/*")):
    d = jload(f); t = P(d["scoreboard_meta"]["retrieved_at"])
    for e in d["events"]:
        ros.append((t, e))
byev = collections.defaultdict(list)
for t, e in ros: byev[e["event_id"]].append((t, e))
act = [(e["minutes_to_kickoff"], sum(x["active"] for tm in e["teams"] for x in tm.get("entries", [])), sum(x["didNotPlay"] for tm in e["teams"] for x in tm.get("entries", [])), sum(len(tm.get("entries", [])) for tm in e["teams"])) for t, e in ros]
changing = 0
for ev, L in byev.items():
    sets = {tuple(sorted((x["athlete_id"], x["active"], x["didNotPlay"]) for tm in e["teams"] for x in tm.get("entries", []))) for t, e in L}
    changing += len(sets) > 1
noent = [(e["event_id"], tm.get("abbr")) for t, e in ros for tm in e["teams"] if not tm.get("entries")]
rr = {"team_obs_without_entries": len(noent), "n_files": len(glob.glob(f"{PIT}/espn_event_rosters/*/*")), "n_event_observations": len(ros), "distinct_games": len(byev),
      "games_with_>1_obs": sum(1 for v in byev.values() if len(v) > 1), "games_whose_roster_flags_changed_between_obs": changing,
      "obs_with_any_active_true": sum(1 for a in act if a[1] > 0), "obs_total": len(act),
      "min_to_kickoff_range": [min(a[0] for a in act), max(a[0] for a in act)],
      "obs_min_to_kickoff_lt_90": sum(1 for a in act if a[0] < 90), "obs_with_didNotPlay_gt0": sum(1 for a in act if a[2] > 0),
      "didNotPlay_per_obs_median": statistics.median(a[2] for a in act), "entries_fields": ["active", "athlete_id", "didNotPlay", "starter"]}
out["pit_espn_event_rosters"] = rr
# ---------- nflverse injuries/depth captures
nv = [jload(f) for f in sorted(glob.glob(f"{PIT}/nflverse_injuries/2026/*.capture.json"))]
nvt = [P(d["retrieved_at"]) for d in nv]
r = gap_stats(nvt, 6); r["distinct_sha256"] = len({d["sha256"] for d in nv}); r["n_parquet_files"] = len(glob.glob(f"{PIT}/nflverse_injuries/2026/*.parquet"))
r["rows_by_week_latest"] = nv[-1]["rows_by_week"]; r["file_has_row_timestamp"] = "NO (per certification doc: no date_modified in 2025+ files; vintages only); only HTTP last_modified"
r["last_modified_values_distinct"] = len({d["last_modified"] for d in nv})
out["pit_nflverse_injuries_2026"] = r
dc = [jload(f) for f in sorted(glob.glob(f"{PIT}/nflverse_depth_charts/2026/*.capture.json"))]
print("dc keys", list(dc[-1].keys()), file=sys.stderr)
dd = dc[-1]["per_dt"]; dts = sorted(P(k) for k in dd)
r = gap_stats(dts, 24); r["distinct_row_sha256_per_dt"] = len({v["sha256"] for v in dd.values()})
r["n_capture_manifests"] = len(dc); r["capture_state_note"] = "per-dt snapshots of nflverse depth_charts (row-level dt); a depth_chart row is ESPN-sourced daily snapshot ~07:00Z"
out["pit_nflverse_depth_charts_2026"] = r
# ---------- per-game pregame coverage
series = {
    "pit_espn_injuries": [t for t, _ in pit],
    "ctx_espn_injuries_legacy": ctx_times,
    "projection_availability": av_times,
}
cov = {}
for name, ts in series.items():
    rows = []
    for g, k in sorted(games.items(), key=lambda x: x[1]):
        if k > max(ts) + dt.timedelta(hours=0) and name != "x": pass
        rows.append((g, k, pregame(ts, k)))
    cov[name] = rows
# only games whose kickoff is within the series' observed period
def summarize(name):
    ts = series[name]; lo, hi = min(ts), max(ts)
    rows = [(g, k, p) for g, k, p in cov[name] if lo <= k <= hi]
    inw = [p["n_in_T-6h"] for _, _, p in rows]; lead = [p["latest_before_kickoff_lead_min"] for _, _, p in rows if p["latest_before_kickoff_lead_min"] is not None]
    return {"games_in_series_period": len(rows), "games_with_>=1_capture_in_T-6h": sum(1 for x in inw if x >= 1), "games_with_>=3_captures_in_T-6h": sum(1 for x in inw if x >= 3),
            "captures_in_T-6h_median": statistics.median(inw) if inw else None, "latest_before_kickoff_lead_min": {"median": round(statistics.median(lead), 1), "p90": round(pct(lead, .9), 1), "max": round(max(lead), 1)} if lead else None,
            "games_with_latest_capture_within_120min": sum(1 for x in lead if x <= 120), "games_with_latest_capture_within_30min": sum(1 for x in lead if x <= 30)}
out["pregame_coverage"] = {n: summarize(n) for n in series}
out["pregame_coverage"]["per_game_pit_espn_injuries_sample"] = [{"game": g, "kickoff": iso(k), **p} for g, k, p in cov["pit_espn_injuries"] if min(series["pit_espn_injuries"]) <= k][:60]
# roster per-game
out["pregame_coverage"]["pit_espn_event_rosters"] = {"games_with_any_obs_of_universe": sum(1 for g in games if any(g.split("_", 2)[-1] for _ in [0]) and False)}
# games with the T-90 window: closest roster observation before kickoff
rel = []
for ev, L in byev.items():
    mins = [e["minutes_to_kickoff"] for t, e in L]
    rel.append({"event": ev, "n_obs": len(L), "min_to_kickoff_obs": sorted(mins)})
out["pregame_coverage"]["pit_espn_event_rosters"] = {"games_observed": len(rel), "games_with_obs_between_T-120_and_T-0": sum(1 for r in rel if any(0 <= m <= 120 for m in r["min_to_kickoff_obs"])), "games_with_obs_between_T-95_and_T-60": sum(1 for r in rel if any(60 <= m <= 95 for m in r["min_to_kickoff_obs"])), "example": rel[:5]}
# projection-data availability per-game record coverage
perg = collections.defaultdict(list)
for f in av_files:
    for r in jl(f): perg[r["event_id"]].append(P(r["captured_utc"]))
ev_cov = []
ks = {}
for f in av_files:
    for r in jl(f): ks[r["event_id"]] = P(r["event_start_utc"])
for g, ts in perg.items():
    k = ks[g]; ts = sorted(set(ts)); b = [t for t in ts if t < k]
    ev_cov.append((g, k, len([t for t in ts if k - dt.timedelta(hours=6) <= t < k]), round((k - max(b)).total_seconds() / 60, 1) if b else None))
out["projection_availability_record_level_game_coverage"] = {"games_with_records": len(ev_cov), "of_forecast_universe": len(games), "with_>=1_capture_with_game_record_in_T-6h": sum(1 for x in ev_cov if x[2] >= 1), "latest_lead_min_median": statistics.median([x[3] for x in ev_cov if x[3] is not None]),
   "latest_lead_min_p90": pct([x[3] for x in ev_cov if x[3] is not None], .9), "per_game": [{"game": g, "kickoff": iso(k), "n_in_T-6h": n, "latest_lead_min": l} for g, k, n, l in sorted(ev_cov, key=lambda x: x[1])]}
json.dump(out, open(f"{os.path.dirname(os.path.dirname(__file__))}/nfl_partial.json", "w"), indent=1, default=str)
print("done")
