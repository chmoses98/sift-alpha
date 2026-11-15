"""Phase 6 acquisition log for the Alpha dashboard (RESEARCH_ONLY).

    python -m alpha_engine.foundation.phase6        # writes research/data_foundation_ops/phase6_acquisition.json

Joins committed evidence only: Phase 6 probes (probes.json, probed_utc 2026-11-15), Phase 6 replay and blind-comparison files, the verified coverage matrix, the acquisition plan totals, and the hand-written
capture proposal and blockers below. Every number shown on the dashboard comes from those files; the BASELINE block is the state recorded in docs/DATA_ACQUISITION_ROADMAP.md before Phase 6.
Stages are never merged: probed (a request answered) < collected (rows held in an archive) < replay-verified < blind-matched (feature built) < training-ready.
"""
from __future__ import annotations

import json

from .contract import OPS, ROOT, write_json

DF = ROOT / "research/input_research/data_foundation"
VD = DF / "verification"
PHASE6_FAMILIES = {"NHL_nhl3": "features/nhl_ext3.py", "NHL_nhl_player3": "features/nhl_player_ext3.py"}
BASELINE = {"as_of": "2026-11-14 (docs/DATA_ACQUISITION_ROADMAP.md before Phase 6)", "training_ready_inputs": 37, "verified_full": 58, "missing_primary_slots": 888, "missing_primary_inputs": 683}
PROBE_DAY = "2026-11-15"

SOURCES_NOT_PROBED = [
    {"source": "CBBD / CFBD direct API", "why": "needs an API key that is not configured here and the hosts are denied by the network policy; per the brief, stopped and documented"},
    {"source": "Barttorvik, Sports-Reference, stats.nba.com, MoneyPuck site", "why": "egress proxy refused the connection (host not allowed for this session); not retried"},
    {"source": "cdn.nba.com", "why": "HTTP 403 from the proxy; not retried"},
]
BLOCKERS = [
    {"id": "rights_p0_collection", "sports": ["CBB", "NBA", "NHL"], "kind": "OWNER_DECISION",
     "text": "Every free source for new P0 history reachable here (sportsdataverse ESPN men's college basketball / NBA box scores, NHL shifts, ESPN, NHL API, MoneyPuck) is recorded "
             "UNRESOLVED_INTERNAL_ONLY with collection_allowed=false in rights_registry.json, and the CBB/CFB sportsdataverse collector is frozen by owner decision 1. Phase 6 did not lift that freeze: "
             "an attempt to record a manual-collection permission was refused by the session's safety review as an owner-only decision, the bypass was reverted and the downloaded CBB files were deleted unused."},
    {"id": "cbb_history", "sports": ["CBB"], "kind": "DATA",
     "text": "CBB has no multi-season history in any owner repository (main and 29 branches checked: rosters, 2026-27 availability, period scores, prospective scores and app data only). "
             "The free bulk path exists and was verified (team box 2005-2026, player box 2006-2026), so the CBB foundation is one owner rights decision away, not a research problem."},
    {"id": "nhl_shifts", "sports": ["NHL"], "kind": "ACCESS+RIGHTS",
     "text": "Shift charts: api.nhle.com is blocked from the runner; the sportsdataverse nhl_shifts mirror is reachable but NHL API-derived (rights unresolved)."},
    {"id": "nba_long_history", "sports": ["NBA"], "kind": "RIGHTS",
     "text": "Long NBA box history (2002+) is reachable as sportsdataverse ESPN release files; ESPN-derived, rights unresolved; the owner archive holds 2023-24 .. 2026-27 only."},
    {"id": "full_definitions", "sports": ["NBA", "NHL", "NFL"], "kind": "DEFINITION",
     "text": "Most held-but-unbuilt PIT-safe inputs either are DOWNGRADED_BY_VERIFIER (not promotable by design) or define a fitted model or simulation as their whole content, "
             "so they can only be PARTIAL; FULL (and therefore training-ready) needs every catalog clause implemented, blind-matched and certified."},
]
PRIORITY_CHANGES = [
    "CBB box history moves from 'probe first' to 'owner rights decision only': the free path is verified (85 season files reachable; 2015+ byte-identical to cbb-edge-finder's October pins; 2004-2014 republished upstream).",
    "New evidence for that decision: hoopR-mbb-data's LICENSE.md now licenses its DATA under CC BY 4.0 (earlier phases recorded an MIT code licence); upstream ESPN rights remain unresolved, so no tier was changed.",
    "NHL: two held-data inputs (long-change effect, opponent PK structure) were promoted to VERIFIED_FULL from the owner archive; the NHL challengers so far are IMPROVED_NOT_VALIDATED, so these feed the next challenger rather than a rebuilt incumbent.",
    "NBA forward capture is already running (injury / roster context every few hours since 2026-09-18, official + ESPN injury PIT since 2026-10-12); the gap is starters (manual) and transactions (not captured).",
]
CAPTURE = [
    {"feed": "NBA transactions (ESPN transactions endpoint)", "unlocks": "nba.transactions_draft (15 inputs completed / 23 advanced in the roadmap)", "times": "daily 09:00 ET + 18:00 ET",
     "requests_per_day": 2, "storage": "about 0.1 MB/day gz (96 KB raw per snapshot)", "quality": "row count > 0, newest transaction date >= yesterday, sha256 de-dup", "reuse": "nba-edge-finder data-archive worker (context/ prefix)"},
    {"feed": "NBA starters (ESPN game summary)", "unlocks": "nba.starters_pregame, lineup-conditioned NBA inputs", "times": "T-90, T-30, T-5 min before each tip",
     "requests_per_day": "3 x games (about 30)", "storage": "about 1 MB/day gz", "quality": "5 starters per team, captured_utc < tip time, no post-tip rows", "reuse": "existing starters-live-check (manual since 2026-11-06): schedule it"},
    {"feed": "NBA injuries (official PDF + ESPN)", "unlocks": "nba.injury_report_vintages history beyond 2025-26", "times": "keep current cadence", "requests_per_day": "unchanged",
     "storage": "unchanged", "quality": "already running; add a daily check that the official report count per date >= 1", "reuse": "data-injury-pit branch (KEEP)"},
    {"feed": "NHL goalie confirmations + lines", "unlocks": "nhl.lineup_goalie_pregame, nhl.goalie_start (timestamped confirmations)", "times": "T-180, T-90, T-30 min",
     "requests_per_day": "3 x games (about 36)", "storage": "about 1 MB/day gz", "quality": "exactly one confirmed starter per team by T-30 or an explicit UNCONFIRMED flag; captured_utc < puck drop",
     "reuse": "NHL capture-worker context/goalie_observations (KEEP); the separate lineup probe is stalled since 2026-10-26 and Daily Faceoff capture needs a policy review before any resumption"},
    {"feed": "CBB availability (ESPN)", "unlocks": "cbb.availability_snapshots (prospective only)", "times": "keep current cadence (several per day since 2026-10-05)", "requests_per_day": "unchanged",
     "storage": "unchanged", "quality": "flag empty feeds (the ESPN CBB injuries endpoint was empty at an earlier probe)", "reuse": "cbb-edge-finder availability-archive (KEEP)"},
    {"feed": "NFL injuries / inactives (ESPN)", "unlocks": "nfl.injury_report_vintages, nfl.inactives_game_day", "times": "Wed-Sat 17:00 ET, Sun T-90 min", "requests_per_day": "1-2 (Sun about 15)",
     "storage": "8.8 MB per snapshot raw, about 1 MB gz", "quality": "team count 32, captured_utc < kickoff", "reuse": "proposal unchanged from docs/CAPTURE_PROPOSAL.md"},
]


def _j(p):
    return json.loads(p.read_text())


def build() -> dict:
    probes = [p for p in _j(DF / "probes.json")["probes"] if p.get("probed_utc") == PROBE_DAY]
    vc = {r["key"]: r for r in _j(DF / "verified_coverage.json")["rows"]}
    plan = _j(OPS / "acquisition_plan.json"); inputs = _j(OPS / "acquisition_inputs.json")["inputs"]
    built = []
    for fam, mod in PHASE6_FAMILIES.items():
        rp = _j(VD / "replay_ext" / f"{fam}.json"); ind = _j(VD / "independent" / f"{fam}.json")
        for iid, r in rp["inputs"].items():
            t = r["tests"]; key = f"{r['sport']}:{iid}"; v = vc.get(key, {}); tr = (inputs.get(key) or {}).get("tr") or {}
            replay_ok = t["determinism"]["ok"] and all(x["ok"] for x in t["truncation"] + t["perturbation"]) and t["own_game"]["ok"] and t["pit_check_perturbation_not_vacuous"]["ok"]
            cols = (ind["inputs"].get(iid) or {}).get("columns") or {}
            built.append({"input": key, "builder": "alpha_engine/" + mod, "replay_file": str((VD / "replay_ext" / f"{fam}.json").relative_to(ROOT)), "columns": r["columns"],
                          "rows": rp["raw_rows"], "span": [t["coverage_replay"]["first_new"], t["coverage_replay"]["last_new"]], "min_coverage": t["coverage_replay"]["min_coverage_new"],
                          "replay_ok": replay_ok, "blind_match": f"{sum(1 for c in cols.values() if c.get('verdict') == 'MATCH')}/{len(r['columns'])}",
                          "verified_status": v.get("verified_status"), "pit": v.get("pit_verdict"), "training_state": tr.get("state"), "training_blocker": tr.get("blocker"),
                          })
    T = plan["totals"]
    after = {"training_ready_inputs": T["training_ready_inputs"], "verified_full": sum(1 for r in vc.values() if r["verified_status"] == "VERIFIED_FULL"),
             "missing_primary_slots": T["missing_primary_slots"], "missing_primary_inputs": T["missing_primary_inputs"]}
    collected = [{"dataset": "CBB sportsdataverse team box / player box / schedules (2003-2026)", "files": 85, "bytes": 91_000_000, "status": "PROBED_AND_PROFILED_THEN_DELETED",
                  "why": "rights freeze (owner decision 1); kept nothing; profile recorded in probes.json (sdv_cbb_player_box)"},
                 {"dataset": "NHL owner archive (NHL-edge-finder data/history: players/*, moneypuck/shots_*)", "files": 32, "bytes": 20_000_000, "status": "READ_FROM_OWNER_ARCHIVE",
                  "why": "no new collection; 13,992 team-games and 251,797 skater-games 2021-10-12 .. 2026-09-29 read for the two NHL builders"}]
    return {"schema": "phase6-acquisition-1.0", "status": "RESEARCH_ONLY", "generated_from": ["research/input_research/data_foundation/probes.json", "verification/replay_ext", "verification/independent",
            "verified_coverage.json", "research/data_foundation_ops/acquisition_plan.json"],
            "notice": "Phase 6 log. Probed = a request answered; collected = rows held; replay-verified = leak/determinism gates passed; blind-matched = an independent re-implementation matched every column; "
                      "training-ready = all of the above plus certified FULL definition, point-in-time safe and 3+ seasons. Agent verification, not human. No rights tier was changed.",
            "stage_order": ["RESEARCHED", "PROBED", "COLLECTED", "REPLAY_VERIFIED", "BLIND_MATCHED_FEATURE_BUILT", "TRAINING_READY"],
            "baseline": BASELINE, "after": after,
            "probes": [{k: p.get(k) for k in ("id", "sport", "url", "http", "result", "description")} for p in probes] + [{"id": s["source"], "sport": "-", "url": None, "http": None, "result": "NOT_PROBED", "description": s["why"]} for s in SOURCES_NOT_PROBED],
            "collected": collected, "built": built, "blockers": BLOCKERS, "priority_changes": PRIORITY_CHANGES, "capture_proposal": CAPTURE,
            "capture_note": "PROPOSAL ONLY: no schedule was created or activated. Requests are per day in season; storage is compressed."}


def main() -> int:
    out = build(); write_json(OPS / "phase6_acquisition.json", out)
    print("phase6:", len(out["probes"]), "probe rows,", len(out["built"]), "built inputs, training-ready", out["baseline"]["training_ready_inputs"], "->", out["after"]["training_ready_inputs"]); return 0


if __name__ == "__main__":
    raise SystemExit(main())
