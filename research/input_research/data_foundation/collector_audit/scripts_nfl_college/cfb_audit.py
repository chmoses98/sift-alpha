import sys, os, glob, json, collections, statistics, datetime as dt
sys.path.insert(0, os.path.dirname(__file__))
from common import *
R = sys.argv[1]; PD = f"{R}/cfb_pd"; out = {}
games = {}
fc_n = 0
for f in glob.glob(f"{PD}/forecasts/cfb/*/*"):
    for r in jl(f):
        fc_n += 1; games[r["game_id"]] = (P(r["game_start_utc"]), r.get("team"), r.get("opponent_id"), r.get("qb_flag"))
files = sorted(glob.glob(f"{PD}/availability/cfb/*/*"))
caps = []; allrows = []; spread = []
for f in files:
    L = jl(f); t = P(L[0]["captured_utc"])
    spread.append(len({r["captured_utc"] for r in L}))
    caps.append((t, f, L)); allrows += L
times = [c[0] for c in caps]
res = gap_stats(times, None)
res["scheduled_cadence_note"] = "projection-foundation.yml (cfb) crons Tue 10:41, Wed 17:41, Thu 18:11, Fri 18:41, Sat 12:41 + 18:41 UTC (+ Sun/Mon settle); ~8 runs/week -> ~21h median spacing; no intra-day pre-kickoff refresh"
gaps_h = [(b - a).total_seconds() / 3600 for a, b in zip(sorted(times), sorted(times)[1:])]
res["gaps_gt_24h_count"] = sum(1 for g in gaps_h if g > 24); res["gaps_gt_48h_count"] = sum(1 for g in gaps_h if g > 48)
res["distinct_captured_utc_per_file_max"] = max(spread)
res["records_total"] = len(allrows); res["records_per_file"] = {"min": min(len(c[2]) for c in caps), "median": statistics.median(len(c[2]) for c in caps), "max": max(len(c[2]) for c in caps)}
srck = collections.Counter((r["source"], r["kind"], r["status"], r["certainty"]) for r in allrows)
res["by_source_kind_status_certainty"] = {"|".join(k): v for k, v in srck.items()}
fl = collections.Counter()
for r in allrows:
    for k, v in r.items(): fl[(r["source"] + ":" + k, v not in (None, ""))] += 1
    for k, v in (r.get("detail") or {}).items(): fl[(r["source"] + ":detail." + k, v not in (None, ""))] += 1
res["field_nonnull_pct_by_source"] = {k: round(100 * fl[(k, True)] / (fl[(k, True)] + fl[(k, False)]), 1) for k in sorted({k for k, _ in fl})}
# injuries staleness
inj = [r for r in allrows if r["kind"] == "injury"]
ages = [r["detail"].get("age_days") for r in inj if r["detail"].get("age_days") is not None]
res["injury_rows"] = {"n": len(inj), "stale_true": sum(1 for r in inj if r["detail"].get("stale") is True), "fresh": sum(1 for r in inj if r["detail"].get("stale") is False),
    "age_days_min": min(ages) if ages else None, "age_days_median": statistics.median(ages) if ages else None, "age_days_max": max(ages) if ages else None,
    "distinct_injury_ids": len({r["detail"].get("injury_id") for r in inj}), "distinct_athletes": len({r["entity_id"] for r in inj}),
    "record_year_counts": dict(collections.Counter((r["detail"].get("record_date") or "NA")[:4] for r in inj)),
    "status_raw": dict(collections.Counter(r["detail"].get("status_raw") for r in inj)), "entity_name_is_numeric_id_pct": round(100 * sum(1 for r in inj if str(r["entity_name"]) == str(r["entity_id"])) / max(len(inj), 1), 1),
    "certainty": dict(collections.Counter(r["certainty"] for r in inj))}
sent = [r for r in allrows if r["kind"] == "roster" and r["source"] == "espn_core_injuries"]
res["espn_team_list_sentinels"] = {"n": len(sent), "injury_list_read_true": sum(1 for r in sent if r["detail"].get("injury_list_read") is True), "with_error": sum(1 for r in sent if r["detail"].get("error")),
    "listed_gt0": sum(1 for r in sent if (r["detail"].get("listed") or 0) > 0), "pct_team_games_with_any_listed_entry": round(100 * sum(1 for r in sent if (r["detail"].get("listed") or 0) > 0) / max(len(sent), 1), 2)}
qb = [r for r in allrows if r["kind"] == "starter"]
res["passer_rows"] = {"n": len(qb), "all_certainty_PROJECTED": all(r["certainty"] == "PROJECTED" for r in qb), "official_true": sum(1 for r in qb if r["detail"].get("official")), "confirmed": sum(1 for r in qb if r["certainty"] == "CONFIRMED"),
    "changed_last_game_true": sum(1 for r in qb if r["detail"].get("changed_last_game")), "games_of_evidence_median": statistics.median(r["detail"].get("games_of_evidence", 0) for r in qb),
    "source_updated_age_days_median": round(statistics.median((P(r["captured_utc"]) - P(r["source_updated_utc"])).total_seconds() / 86400 for r in qb if r.get("source_updated_utc")), 1)}
# team coverage: per capture teams covered / event_teams per capture
percap = []
for t, f, L in caps:
    ev = {r["event_id"] for r in L}; tm = {(r["event_id"], r["team"]) for r in L}
    qbt = {(r["event_id"], r["team"]) for r in L if r["kind"] == "starter"}
    injt = {(r["event_id"], r["team"]) for r in L if r["kind"] == "injury"}
    ks = [P(r["event_start_utc"]) for r in L]
    percap.append({"captured": iso(t), "events": len(ev), "event_teams": len(tm), "with_passer": len(qbt), "with_any_injury_entry": len(injt), "min_hours_to_kickoff": round((min(ks) - t).total_seconds() / 3600, 1), "max_hours_to_kickoff": round((max(ks) - t).total_seconds() / 3600, 1)})
res["per_capture"] = percap
res["fraction_event_teams_with_passer"] = round(sum(p["with_passer"] for p in percap) / sum(p["event_teams"] for p in percap), 3)
res["fraction_event_teams_with_any_injury_entry_incl_stale"] = round(sum(p["with_any_injury_entry"] for p in percap) / sum(p["event_teams"] for p in percap), 3)
res["fraction_event_teams_with_FRESH_injury_entry"] = round(sum(1 for r in inj if r["detail"].get("stale") is False) / sum(p["event_teams"] for p in percap), 4)
# per game pregame coverage
ev_start = {}
ev_caps = collections.defaultdict(set)
for t, f, L in caps:
    for r in L:
        ev_start[r["event_id"]] = P(r["event_start_utc"]); ev_caps[r["event_id"]].add(t)
rows = []
for e, k in ev_start.items():
    ts = sorted(ev_caps[e]); b = [t for t in ts if t < k]
    rows.append({"event": e, "kickoff": iso(k), "n_caps_with_game": len(ts), "n_in_T-6h": len([t for t in ts if k - dt.timedelta(hours=6) <= t < k]), "n_in_T-24h": len([t for t in ts if k - dt.timedelta(hours=24) <= t < k]), "latest_lead_h": round((k - max(b)).total_seconds() / 3600, 2) if b else None})
res["per_game"] = {"games_with_records": len(rows), "games_in_forecast_universe(all weeks)": len(games), "n_in_T-6h_>=1": sum(1 for r in rows if r["n_in_T-6h"] >= 1), "n_in_T-24h_>=1": sum(1 for r in rows if r["n_in_T-24h"] >= 1), "games_with_pregame_capture": sum(1 for r in rows if r["latest_lead_h"] is not None),
  "latest_lead_h": {"median": round(statistics.median(r["latest_lead_h"] for r in rows if r["latest_lead_h"] is not None), 2), "p90": round(pct([r["latest_lead_h"] for r in rows if r["latest_lead_h"] is not None], .9), 2), "max": max(r["latest_lead_h"] for r in rows if r["latest_lead_h"] is not None), "min": min(r["latest_lead_h"] for r in rows if r["latest_lead_h"] is not None)},
  "n_caps_per_game_median": statistics.median(r["n_caps_with_game"] for r in rows), "sample": sorted(rows, key=lambda r: r["kickoff"])}
# games in forecast universe lacking any availability record
univ = {g: v[0] for g, v in games.items() if v[0] >= min(times)}
res["forecast_universe_since_first_capture"] = {"n_games": len(univ), "with_availability_record": sum(1 for g in univ if g in ev_start), "without": sum(1 for g in univ if g not in ev_start)}
res["games_in_forecast_universe_by_kickoff_day_without_record"] = dict(collections.Counter(iso(v)[:10] for g, v in univ.items() if g not in ev_start))
# dedup / delta: duplicate observation identity across files
ident = collections.Counter((r["event_id"], r["entity_id"], r["kind"], r["source"], r["status"], json.dumps(r.get("detail"), sort_keys=True, default=str).replace(r["captured_utc"], "")) for r in allrows)
res["dedup"] = {"records": len(allrows), "distinct_content_identities": len(ident), "records_repeating_prior_identical_content": len(allrows) - len(ident), "write_once_file_naming": "availability/cfb/<date>/<HHMMSS>Z_<hash>.jsonl.gz; each file full snapshot of all upcoming events in horizon, not delta"}
out["cfb_projection_data_availability"] = res
json.dump(out, open(f"{os.path.dirname(os.path.dirname(__file__))}/cfb_partial.json", "w"), indent=1, default=str)
x = dict(res); x.pop("per_capture"); x["per_game"] = {k: v for k, v in res["per_game"].items() if k != "sample"}; x.pop("field_nonnull_pct_by_source")
print(json.dumps(x, indent=0, default=str)[:7000])
