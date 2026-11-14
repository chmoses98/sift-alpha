"""Prospective-capture progress and proposals (RESEARCH_ONLY): what is ALREADY being captured by the owner's authorized workflows (measured read-only from the repos' data branches) and what is
PROPOSED (inactive templates awaiting approval). Nothing here schedules, enables or pushes anything.

    python -m alpha_engine.input_research.data_foundation.capture_plan
"""
from __future__ import annotations

import json

from . import evidence as EV

DF = EV.DF
VD = DF / "verification"
OUT_JSON = DF / "capture_status.json"
OUT_DOC = EV.ROOT / "docs/CAPTURE_PROPOSAL.md"

# (priority feed, dataset ids, repo, existing capture (branch or archive prefix key), feasibility probe id, status text, proposal)
FEEDS = [
 ("NFL injuries / inactives", ["nfl.injury_report_vintages", "nfl.inactives_game_day"], "nfl-edge-finder", None, "espn_nfl_injuries", "NOT INSPECTED: nfl-edge-finder is not among the repos the owner authorized for reading. ESPN's injury list is reachable (8.8 MB per snapshot); its game summary carries injury data. Official game-day inactives were not confirmed on a public JSON feed.", "PROPOSE: hourly ESPN NFL injuries snapshots Wed-Mon in season plus the game summary at T-2h and T+0 (compact gz); inactives stay UNCONFIRMED until a permitted feed is found"),
 ("NBA transactions", ["nba.transactions_draft"], "nba-edge-finder", None, "espn_nba_transactions", "ESPN's NBA transactions endpoint exists and returned 96 KB; no transactions archive exists in the NBA data-archive (measured prefixes).", "PROPOSE: daily snapshot of the ESPN NBA transactions feed into the existing NBA data-archive worker"),
 ("NBA availability (injuries, rosters, starters)", ["nba.injury_report_vintages", "nba.starters_pregame"], "nba-edge-finder", ("nba_src:data-injury-pit", "context/injuries", "context/starters"), "espn_nba_injuries", "ALREADY CAPTURED by the owner's workflows (see measured counts below).", "KEEP; propose scheduling `starters-live-check` (currently manual: only 4 dates since 2026-11-06)"),
 ("MLB lineups / probables / injured list", ["mlb.lineup_il_vintages", "mlb.transactions"], "edge-finder-api", None, "mlb_roster_il", "NOT INSPECTED (repo not authorized). Offseason now: lineups cannot be judged until games resume; the injured-list roster and transactions endpoints work for past seasons.", "PROPOSE: from opening day, schedule+lineups+probables every 15 min on game days (10:00-20:00 ET) and IL roster + transactions daily"),
 ("College availability (CFB, CBB)", ["cfb.availability_snapshots", "cbb.availability_snapshots"], "cfb-edge-finder / cbb-edge-finder", None, "espn_cfb_injuries", "NOT INSPECTED (repos not authorized). ESPN's college-football injuries endpoint returned 28 KB of data; the college-basketball injuries endpoint returned only 149 bytes (empty) at probe time, so no CBB availability feed is promised.", "PROPOSE: daily CFB injuries snapshot (hourly Fri-Sat); CBB only after a non-empty feed is confirmed in season"),
 ("NHL injuries / goalie confirmations / lines", ["nhl.injuries", "nhl.lineup_goalie_pregame"], "NHL-edge-finder", ("nhl_src:data-archive", "context/injuries", "context/goalie_observations", "context/lines"), "espn_nhl_injuries", "ALREADY CAPTURED by the owner's capture-worker (see measured counts). The separate lineup probe is manual and stalled since 2026-10-26; `dailyfaceoff_raw` capture stopped the same day.", "KEEP the worker captures; REVIEW the Daily Faceoff capture against the no-restricted-scraping policy before it is ever resumed"),
]


def measured() -> dict:
    b = json.loads((VD / "capture_progress_by_dataset.json").read_text()); br = json.loads((VD / "capture_progress_branches.json").read_text())
    return {"by_archive_prefix": b, "branches": br}


def build() -> dict:
    m = measured(); P = {p["id"]: p for p in json.loads((DF / "probes_capture_feasibility.json").read_text())["probes"]}
    items = []
    for name, dss, repo, ex, pid, status, proposal in FEEDS:
        prog = None
        if ex:
            key = ex[0]; d = key.split(":")[0]; prog = {}
            for pref in ex[1:]:
                v = (m["by_archive_prefix"].get(d) or {}).get(pref)
                if v:
                    prog[pref] = v
            if key.endswith("data-injury-pit") and key in m["branches"]:
                prog["data-injury-pit branch"] = {k: m["branches"][key][k] for k in ("files", "first_date", "last_date", "distinct_dates", "last_commit")}
        pr = P.get(pid)
        items.append({"feed": name, "datasets": dss, "repo": repo, "measured_progress": prog or None, "feasibility_probe": ({"id": pid, "http": pr["http"], "bytes": pr["bytes"]} if pr else None), "status": status, "proposal": proposal})
    return {"schema_version": "capture-status-1.0", "status": "RESEARCH_ONLY", "nothing_scheduled_or_enabled": True, "measured_from": "read-only listing of the owner's data branches on 2026-11-09 (names only; no write access used)", "items": items,
            "existing_workflows_seen": {"nba-edge-finder": ["capture_worker (every 5 min -> data-archive)", "pit_injuries (hourly -> data-injury-pit)", "starters-live-check (manual)", "nba-injury-correctness", "nba-ticker", "nba-watchdog"],
                                        "NHL-edge-finder": ["capture_worker (every 5 min -> data-archive)", "nhl_lineup_probe (manual -> lineup-probe-data)", "slate_watch (schedule)", "player_minutes", "projection-foundation"]},
            "templates": ["docs/capture_workflows/capture-vintage.yml.proposed", "docs/capture_workflows/capture_snapshot.py.proposed"]}


def render(p: dict) -> str:
    L = ["# SIFT Alpha prospective capture: real progress and proposals (RESEARCH_ONLY)", "",
         "Generated by `python -m alpha_engine.input_research.data_foundation.capture_plan`; do not edit by hand. **Nothing here schedules, enables or pushes anything.** Progress was measured read-only from the owner's `nba-edge-finder` and `NHL-edge-finder` data branches (file and date partitions only). "
         "The other sibling repos were not authorized for reading and are marked NOT INSPECTED. New workflows exist only as inactive templates under `docs/capture_workflows/` (`*.proposed`) awaiting the owner's approval, one repo at a time. Vintage history cannot be backfilled: every day without capture is lost.", "",
         "| Priority feed | Datasets | Repo | Status | Proposal |", "|---|---|---|---|---|"]
    for x in p["items"]:
        L.append(f"| {x['feed']} | {', '.join('`'+d+'`' for d in x['datasets'])} | {x['repo']} | {x['status']} | {x['proposal']} |")
    L += ["", "## Measured capture progress (owner's existing workflows)", "", "| Archive | Dataset | Files | Dates captured | First | Last |", "|---|---|---|---|---|---|"]
    for x in p["items"]:
        for k, v in (x["measured_progress"] or {}).items():
            L.append(f"| {x['repo']} | `{k}` | {v['files']} | {v['dates'] if 'dates' in v else v.get('distinct_dates')} | {v.get('first') or v.get('first_date')} | {v.get('last') or v.get('last_date')} |")
    L += ["", "The NHL `lineup-probe-data` branch holds only 2 dates (2026-10-25/26; manual dispatch) and the `dailyfaceoff_raw` archive stopped on 2026-10-26. Kalshi market and order-book captures in the same archives are benchmark-only data (market-derived), excluded from market-free inputs.", "",
          "## Feasibility probes (already-reachable hosts only, no credentials)", "", "| Feed | HTTP | Bytes |", "|---|---|---|"]
    for x in p["items"]:
        if x["feasibility_probe"]:
            L.append(f"| `{x['feasibility_probe']['id']}` | {x['feasibility_probe']['http']} | {x['feasibility_probe']['bytes']} |")
    L += ["", "## Templates (inactive)", "", "* `docs/capture_workflows/capture_snapshot.py.proposed`: stdlib-only, append-only collector (generic User-Agent, one request per feed, no retries on 403/429, 30 MB cap, SHA-256 manifest). Dry-run once locally against two ESPN feeds; wrote only to a scratch directory.",
          "* `docs/capture_workflows/capture-vintage.yml.proposed`: hourly orphan-branch capture modelled on the owner's `pit-injury-reports` workflow; default token only; concurrency-grouped; edit `FEEDS` per repo.", ""]
    return "\n".join(L)


def main() -> int:
    p = build(); OUT_JSON.write_text(json.dumps(p, indent=0, sort_keys=True, ensure_ascii=False) + "\n"); OUT_DOC.write_text(render(p)); print("wrote", OUT_DOC.name); return 0


if __name__ == "__main__":
    raise SystemExit(main())
