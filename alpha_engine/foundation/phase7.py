"""Phase 7 acquisition + training-dataset log for the Alpha dashboard (RESEARCH_ONLY).

    python -m alpha_engine.foundation.phase7        # writes research/data_foundation_ops/phase7_acquisition.json

Joins committed evidence only: the Phase 7 replay and blind-comparison files, the full-certification record, the verified coverage matrix, the acquisition plan totals, the training-set manifests
(research/data_foundation_ops/training_sets/*.json) and the hand-written source / capture / blocker records below (each with the evidence it rests on). The BASELINE block is the state after Phase 6
(PR #77, recomputed at the start of Phase 7). Stages are never merged: probed < collected < replay-verified < blind-matched < training-ready.
"""
from __future__ import annotations

import json

from .contract import OPS, ROOT, write_json

DF = ROOT / "research/input_research/data_foundation"
VD = DF / "verification"
TS = OPS / "training_sets"
FAMILIES = {"NFL_nfl_pbp3": "features/nfl_pbp_ext3.py", "NFL_nfl_rush3": "features/nfl_rush_ext3.py (view of nfl_pbp_ext3.py)"}
BASELINE = {"as_of": "2026-11-15, Phase 6 (draft PR #77) recomputed at the start of Phase 7", "training_ready_inputs": 39, "verified_full": 60, "missing_primary_slots": 888, "missing_primary_inputs": 683}

# Every source request made in Phase 7 (one pass each; nothing retried). Sizes are the bytes received.
SOURCES = [
    {"id": "nflverse play_by_play 1999-2025", "sport": "NFL", "result": "COLLECTED", "detail": "27 season files, 0 failures, about 466 MB parquet; 1,279,628 plays in the 17 columns the builders read",
     "rights": "nflverse WRAPPER_LICENCE_UPSTREAM_CAVEAT, collection_allowed true"},
    {"id": "nflverse play_by_play 2026 (current season)", "sport": "NFL", "result": "COLLECTED", "detail": "24,002 plays, weeks 1-10, last game 2026-11-12 (10.2 MB); 137 of 272 scheduled games completed",
     "rights": "as above"},
    {"id": "nflverse 2026 injuries, depth charts, snap counts, weekly rosters, player/team weekly stats, FTN charting, PFR passing advstats, officials, players", "sport": "NFL", "result": "REACHABLE",
     "detail": "all HTTP 200 (65 KB .. 3.5 MB each). Profiled only; the injuries/depth-chart vintages are already archived prospectively by nfl-edge-finder (pit-availability-nfl, 3,292 injury vintage files)",
     "rights": "as above"},
    {"id": "nflverse 2026 Next Gen Stats passing, pbp participation", "sport": "NFL", "result": "NOT_PUBLISHED", "detail": "HTTP 404: not released for 2026 (participation ends with 2025 upstream)", "rights": "-"},
    {"id": "ffverse ffopportunity expected-TD weekly (ep_weekly_2024.csv)", "sport": "NFL", "result": "REACHABLE_NOT_USED",
     "detail": "HTTP 200, 5.4 MB; deleted unused: ffopportunity is not in rights_registry.json, so td_luck / team_first_td_attribution (which name its xTD fields) wait for an owner rights reading", "rights": "UNRECORDED"},
    {"id": "CollegeFootballData API (api.collegefootballdata.com)", "sport": "CFB", "result": "BLOCKED",
     "detail": "proxy CONNECT 403 from this environment (one request, not retried). The owner's key lives in the college-direct GitHub environment; the call-capped probe needs the owner approval file (docs/COLLEGE_DIRECT_PROBE.md)",
     "rights": "CLEARED_PROVIDER_TERMS_DIRECT_API (owner-reported), collection_allowed false until the probe runs"},
    {"id": "cfb-edge-finder 2026 game log (data/football/2026)", "sport": "CFB", "result": "OWNER_ARCHIVE_CURRENT",
     "detail": "751 completed games / 1,502 team-game rows with play logs and box scores, 143 availability teams, fetched 2026-11-15T14:45Z by the existing script-engine workflow (ESPN scoreboard / summary / drives / injuries)",
     "rights": "espn_scoreboard_and_archives UNRESOLVED_INTERNAL_ONLY"},
    {"id": "nfl-edge-finder context capture (weather forecasts, ESPN injuries, Sleeper) on market-data", "sport": "NFL", "result": "CAPTURE_STALLED",
     "detail": "224 weather-forecast snapshots 2026-09-04 .. 2026-10-28, none since; the latest scheduled runs (2026-11-14 18:13Z, 22:31Z) failed and 2026-11-15 06:44Z was cancelled; job logs have expired (HTTP 404)",
     "rights": "open-meteo / ESPN / Sleeper as recorded in that repository"},
]
BLOCKERS = [
    {"id": "nfl_weather_capture_stalled", "sports": ["NFL"], "kind": "OPERATIONS",
     "text": "The only point-in-time NFL weather-forecast archive (nfl-edge-finder context-capture.yml -> market-data data/context) has published nothing since 2026-10-28 and its recent runs fail. "
             "Weeks 9-11 forecasts are already lost (they cannot be backfilled). Re-running it once from the Actions tab and reading the fresh log is the cheapest fix; no new workflow is needed."},
    {"id": "rights_p0_collection", "sports": ["CBB", "NBA", "NHL", "CFB"], "kind": "OWNER_DECISION",
     "text": "Unchanged from Phase 6 and not re-litigated: every free source of new CBB / NBA / NHL / CFB history reachable here is collection_allowed=false in rights_registry.json and the sportsdataverse "
             "college collector is frozen (owner decision 1). Phase 7 collected nothing from those sources."},
    {"id": "cfbd_probe", "sports": ["CFB", "CBB"], "kind": "OWNER_ACTION",
     "text": "The CFBD/CBBD direct-API path is built and tested (college-direct-probe.yml, 10-call cap) but needs the owner approval file (college_direct_*.json) on main and an owner dispatch; the API host is blocked from this environment."},
    {"id": "ffopportunity_rights", "sports": ["NFL"], "kind": "OWNER_DECISION",
     "text": "nfl.td_luck and nfl.team_first_td_attribution name ffopportunity expected-TD fields. The release is reachable but unrecorded in the rights registry; record a reading (or reject it) before it is collected."},
    {"id": "model_definitions", "sports": ["NFL", "NBA", "NHL"], "kind": "DEFINITION",
     "text": "Of the held-but-unbuilt PIT-safe inputs, most define a fitted model or simulation (copulas, GLMMs, logit lattices) as their whole content; they can be built PARTIAL but not certified FULL "
             "without fitting that model, so they do not become training-ready from a deterministic builder."},
]
CAPTURE = [
    {"feed": "NFL weather forecasts (existing context-capture.yml)", "status": "STALLED since 2026-10-28", "action": "owner re-run + log read; no new schedule",
     "requests_per_day": "unchanged (8 runs/day)", "value": "the only pregame weather vintage for NFL totals; every lost week is permanent"},
    {"feed": "NFL injuries / depth charts (existing pit-availability-nfl.yml)", "status": "RUNNING (3,292 nflverse injury vintages on market-data)", "action": "keep",
     "requests_per_day": "unchanged", "value": "PIT availability; nflverse rebuilds these files in place, so only our vintages are point-in-time"},
    {"feed": "NFL play-by-play / weekly stats (nflverse releases)", "status": "NOT NEEDED AS A SCHEDULE", "action": "re-pull on demand (the release is append-only for closed games; refresh.py already re-fetches the current season)",
     "requests_per_day": "0 (about 30 files / 500 MB per full rebuild, 1-2 files weekly)", "value": "historical replay; no prospective value beyond the game itself"},
    {"feed": "CFB 2026 game log (existing script-engine workflow)", "status": "RUNNING (751 games through 2026-11-15)", "action": "keep", "requests_per_day": "unchanged",
     "value": "current-season team-game box / drives / play logs"},
    {"feed": "NBA starters + transactions, NHL goalie confirmations, CBB availability", "status": "Phase 6 proposal stands", "action": "no change in Phase 7 (see the Phase 6 tab)",
     "requests_per_day": "under 100 combined", "value": "timestamped lineups/availability"},
]
PRIORITY_CHANGES = [
    "NFL opponent-adjusted EPA (pass/run, offence and defence) is now a certified, training-ready input from 1999; the next NFL priorities are the weather capture repair and the ffopportunity rights reading.",
    "CFB: the current season is safe in the owner archive; history is gated only by the CFBD probe approval or the sportsdataverse rights decision, not by research.",
    "CBB / NBA / NHL: no new collection is possible under the recorded rights; their next gain is an owner decision (CBB) or a fitted-model input certification, not more probing.",
]


def _j(p):
    return json.loads(p.read_text())


def build() -> dict:
    vc = {r["key"]: r for r in _j(DF / "verified_coverage.json")["rows"]}
    plan = _j(OPS / "acquisition_plan.json"); inputs = _j(OPS / "acquisition_inputs.json")["inputs"]
    built = []
    for fam, mod in FAMILIES.items():
        rp = _j(VD / "replay_ext" / f"{fam}.json"); ind = _j(VD / "independent" / f"{fam}.json")
        for iid, r in rp["inputs"].items():
            t = r["tests"]; key = f"{r['sport']}:{iid}"; v = vc.get(key, {}); tr = (inputs.get(key) or {}).get("tr") or {}
            replay_ok = t["determinism"]["ok"] and all(x["ok"] for x in t["truncation"] + t["perturbation"]) and t["own_game"]["ok"] and t["pit_check_perturbation_not_vacuous"]["ok"]
            cols = (ind["inputs"].get(iid) or {}).get("columns") or {}
            built.append({"input": key, "builder": "alpha_engine/" + mod, "replay_file": str((VD / "replay_ext" / f"{fam}.json").relative_to(ROOT)), "columns": r["columns"],
                          "rows": rp["raw_rows"], "span": [t["coverage_replay"]["first_new"], t["coverage_replay"]["last_new"]], "min_coverage": t["coverage_replay"]["min_coverage_new"],
                          "replay_ok": replay_ok, "blind_match": f"{sum(1 for c in cols.values() if c.get('verdict') == 'MATCH')}/{len(r['columns'])}",
                          "verified_status": v.get("verified_status"), "pit": v.get("pit_verdict"), "training_state": tr.get("state"), "training_blocker": tr.get("blocker")})
    T = plan["totals"]
    after = {"training_ready_inputs": T["training_ready_inputs"], "verified_full": sum(1 for r in vc.values() if r["verified_status"] == "VERIFIED_FULL"),
             "missing_primary_slots": T["missing_primary_slots"], "missing_primary_inputs": T["missing_primary_inputs"]}
    by_sport = {}
    for k, v in inputs.items():
        if v["tr"]["state"] == "TRAINING_READY":
            by_sport[v["s"]] = by_sport.get(v["s"], 0) + 1
    sets = []
    for f in sorted(TS.glob("*.json")) if TS.exists() else []:
        m = _j(f)
        sets.append({"sport": m["sport"], "file": str(f.relative_to(ROOT)), "unit": m["unit"], "rows": m["rows"], "rows_by_split": m["rows_by_split"], "seasons": m["seasons"],
                     "latest_game_date": m["latest_game_date"], "n_inputs": m["n_inputs"], "inputs": sorted(m["inputs"]), "n_feature_columns": m["n_feature_columns"],
                     "checks": m["checks"], "outcome_reconciliation": {k: m["outcome_reconciliation"][k] for k in ("games_with_outcome", "games_with_pbp", "outcome_mismatches")},
                     "walk_forward": {"all": m["walk_forward_home_margin"]["all_ready_inputs"]["mean"], "legacy": m["walk_forward_home_margin"]["legacy_ready_inputs_only"]["mean"]},
                     "prediction_cutoff": m["prediction_cutoff"]})
    no_set = {"CFB": "no training-ready input yet (9 PROXY_READY); one held season (2026) in the owner archive; history blocked on rights / CFBD probe approval",
              "CBB": "no training-ready input and no multi-season history held (rights freeze, owner decision 1)",
              "NBA": f"{by_sport.get('NBA', 0)} training-ready inputs on the owner archive (2023-24 .. 2026-27); dataset not assembled in Phase 7 (NFL took the session); next",
              "NHL": f"{by_sport.get('NHL', 0)} training-ready inputs on the owner archive (2021-22 .. 2026-27); dataset not assembled in Phase 7; next"}
    return {"schema": "phase7-acquisition-1.0", "status": "RESEARCH_ONLY",
            "generated_from": ["verification/replay_ext/NFL_nfl_pbp3.json, NFL_nfl_rush3.json", "verification/independent", "verification/full_certification/phase7_round1.json",
                               "verified_coverage.json", "research/data_foundation_ops/acquisition_plan.json", "research/data_foundation_ops/training_sets/*.json"],
            "notice": "Phase 7 log. Collected = rows held (outside the repository); replay-verified = leak/determinism gates passed; blind-matched = an independent re-implementation matched every column; "
                      "training-ready = all of the above plus certified FULL definition, point-in-time safe and 3+ seasons. Agent verification, not human. No rights tier changed, no schedule created.",
            "stage_order": ["RESEARCHED", "PROBED", "COLLECTED", "REPLAY_VERIFIED", "BLIND_MATCHED_FEATURE_BUILT", "TRAINING_READY"],
            "baseline": BASELINE, "after": after, "training_ready_by_sport": dict(sorted(by_sport.items())),
            "sources": SOURCES, "built": built, "training_sets": sets, "no_training_set": no_set,
            "blockers": BLOCKERS, "priority_changes": PRIORITY_CHANGES, "capture": CAPTURE,
            "capture_note": "No schedule was created or activated. Two of the five capture lines are existing jobs to keep, one is an existing job that needs a re-run, and nflverse history needs no schedule."}


def main() -> int:
    out = build(); write_json(OPS / "phase7_acquisition.json", out)
    print("phase7:", len(out["built"]), "built inputs,", len(out["training_sets"]), "training sets, training-ready", out["baseline"]["training_ready_inputs"], "->", out["after"]["training_ready_inputs"]); return 0


if __name__ == "__main__":
    raise SystemExit(main())
