"""Prioritised, INACTIVE prospective-capture plan (RESEARCH_ONLY).

    python -m alpha_engine.input_research.data_foundation.prospective_plan

Ranks the predictive slots that only forward capture can fill (completeness category PROSPECTIVE) by feed, using PRIMARY-role slots first, and maps every feed to an EXISTING sport workflow where one was measured.
Nothing here schedules, enables, or modifies a workflow, permission, credential or collector. A feed whose supplier already exists is never given a second collector: the action is to verify field coverage or to ask the owner to extend the existing one.
Evidence classes: MEASURED_PHASE9 (read in this phase), MEASURED_EARLIER (prior-phase record), UNINSPECTED.
"""
from __future__ import annotations

import collections
import json

from . import market_completeness as M

OUT_JSON = M.DF / "prospective_capture_plan.json"
OUT_DOC = M.ROOT / "docs/PROSPECTIVE_CAPTURE_PLAN.md"

# dataset id -> (feed name, existing supplier, evidence class, what the existing supplier lacks, action, owner prerequisite, rights note)
SUPPLY = {
 "mlb.lineup_il_vintages": ("MLB confirmed lineups, probable pitchers, injured list", "chmoses98/edge-finder-api PIT slate captures (lineup status/time, probable pitchers, bullpen aggregates; 2026-06-15..2026-10-28 in Phase 8)", "MEASURED_EARLIER",
        "one season only, mixed with market prices; offseason now; IL roster/transactions history not captured; MLB Stats API bulk terms unverified", "VERIFY_THEN_EXTEND_EXISTING: confirm the slate capture resumes at opening day and stores lineup status, time and IL per snapshot; do not add a second collector",
        "owner confirms the edge-finder-api capture is scheduled for the 2027 season; MLB Stats API terms decision", "MLB Stats API terms UNRESOLVED"),
 "nfl.injury_report_vintages": ("NFL injury report vintages and QB status", "none observed: the prospective-data branch holds contracts/captures/settlements/heartbeats and projection shards, no injury or depth-chart vintages", "MEASURED_PHASE9",
        "no intra-week practice-status vintages; nflverse injuries keep only the last status per week", "EXTEND_EXISTING: add an injuries + game-summary feed to the capture windows of nfl-prospective-ops (the lab code pinned by RELEASE.json decides the feeds); reuse docs/capture_workflows/capture_snapshot.py.proposed, which is inactive",
        "owner changes the lab code / RELEASE pin; no schedule change is made here", "ESPN terms UNRESOLVED (injury feed); nflverse injuries are CC BY wrapper only"),
 "cfb.availability_snapshots": ("CFB availability and QB status", "chmoses98/cfb-edge-finder projection-data availability/cfb/<date>/*.jsonl.gz (ESPN team injury listing + PROJECTED previous-game passer), pinned sample audited by alpha_engine/cfb_availability_archive.py", "MEASURED_EARLIER",
        "ESPN CFB injuries are sparse and can be years stale; passer is projected, not confirmed; completeness unproven", "VERIFY_EXISTING: run the existing pinned audit over a full week before building anything; a confirmed-starter source needs a permitted feed that does not yet exist", "none for the audit", "ESPN terms UNRESOLVED"),
 "cbb.availability_snapshots": ("CBB availability, starters and minutes", "none", "MEASURED_EARLIER",
        "ESPN CBB injuries endpoint returned an empty body at the Phase 7 probe", "DEFER: probe the endpoint in season; capture only once a non-empty permitted feed is confirmed (no collector exists to duplicate)", "in-season probe", "ESPN terms UNRESOLVED"),
 "nhl.injuries": ("NHL injuries, scratches and goalie confirmations", "chmoses98/NHL-edge-finder capture-worker (context/injuries, context/goalie_observations; 911 goalie-observation files 2026-09-29..2026-11-09)", "MEASURED_PHASE9",
        "nhl_lineup_probe is manual and stalled since 2026-10-26; Daily Faceoff capture stopped and needs a policy review before any resume", "VERIFY_EXISTING: measure field coverage and capture-time distribution of the worker archives; do not add a collector", "owner reviews Daily Faceoff against the no-restricted-scraping policy", "NHL API terms UNRESOLVED"),
 "nhl.lineup_goalie_pregame": ("NHL confirmed starting goalie", "same capture-worker (goalie_observations) plus manual nhl_lineup_probe", "MEASURED_PHASE9", "confirmation timestamps relative to puck drop not yet audited", "VERIFY_EXISTING", "none", "NHL API terms UNRESOLVED"),
 "soc.lineups_pregame": ("Soccer confirmed lineups and injuries", "chmoses98/soccer-edge-finder data-archive branch exists (listing only; contents not inspected)", "UNINSPECTED", "unknown", "INSPECT_THEN_DECIDE: read the branch's file layout first; propose the inactive template only if no lineup vintages are present", "owner authorises reading the archive contents", "provider terms unverified"),
 "soc.injuries_suspensions": ("Soccer injuries and suspensions", "same soccer-edge-finder archive (uninspected)", "UNINSPECTED", "unknown", "INSPECT_THEN_DECIDE", "same", "provider terms unverified"),
 "nba.starters_pregame": ("NBA starters", "chmoses98/nba-edge-finder capture_worker context/starters (45 files 2026-11-06..2026-11-09; starters-live-check is manual)", "MEASURED_PHASE9", "starters-live-check is manual so only 4 dates were captured; the hourly pit_injuries workflow already runs", "OWNER_SCHEDULE_EXISTING: schedule the existing starters-live-check workflow (a schedule change, not made here)", "owner decides", "ESPN terms UNRESOLVED"),
 "nba.injury_report_vintages": ("NBA injury report vintages", "nba-edge-finder pit_injuries hourly -> data-injury-pit and capture_worker context/injuries (652 files 2026-09-18..2026-11-09)", "MEASURED_PHASE9", "none known; history starts 2026-09-18 (about one season-start)", "KEEP_EXISTING: nothing to add; wait for history to accumulate", "none", "official report terms unverified"),
 "ten.withdrawals_injuries": ("Tennis withdrawals, draws and order of play", "chmoses98/Tennis-Edge-Finder tennis-data branch (kalshi tennis capture, first-ball truth/window plans); no withdrawal feed seen", "MEASURED_PHASE9", "withdrawal and draw vintages not captured", "INSPECT_THEN_DECIDE: confirm whether first-ball/draw captures include withdrawals before proposing anything", "none", "Sackmann NC licence covers results only"),
 "xx.news_timestamped": ("Timestamped news (beat writers, transactions)", "none", "MEASURED_EARLIER", "needs scraping of third-party sites", "NOT_PLANNED: conflicts with the no-restricted-scraping policy", "owner policy decision", "UNRESOLVED"),
}
FALLBACK = ("other prospective feeds", "none identified", "UNINSPECTED", "per-input need", "TRIAGE_LATER", "none", "unknown")


NEWS_ONLY = "xx.news_timestamped"   # inputs whose only vintage need is timestamped news/transactions (award hazards, coaching moves, draft items): lowest priority, scraping/policy gated
NON_VINTAGE = "NON_VINTAGE"   # model/simulation/rules/draft/award inputs: prospective only because their upstream inputs are, not a capturable pregame vintage


ALIAS = {"mlb.transactions": "mlb.lineup_il_vintages", "nfl.injuries_weekly": "nfl.injury_report_vintages", "nfl.inactives_game_day": "nfl.injury_report_vintages", "nfl.depth_charts": "nfl.injury_report_vintages"}   # same underlying capture


def feed_of(audit_row: dict) -> str:
    f = _feed_of(audit_row)
    return ALIAS.get(f, f)


def _feed_of(audit_row: dict) -> str:
    """The vintage feed an input needs: AVAIL/LINEUP first, then NEWS; anything else is not a capturable pregame vintage."""
    reqs = audit_row.get("requirements") or []
    for need in ("AVAIL", "LINEUP"):
        for r in reqs:
            if r.get("need") == need:
                return (r.get("satisfied_by") or (r.get("candidates") or ["?"])[0])
    return NEWS_ONLY if any(r.get("need") == "NEWS" for r in reqs) else NON_VINTAGE


def build() -> dict:
    audit = {r["key"]: r for r in json.loads((M.DF / "input_audit.json").read_text())["rows"]}; st = M.load_status(None)
    feeds: dict = collections.defaultdict(lambda: {"primary": 0, "secondary": 0, "context": 0, "archetypes": set(), "inputs": collections.Counter(), "sports": set()})
    for a in M.archetypes():
        for iid, role in a["inputs"]:
            if iid in M.SEMANTIC_IDS: continue
            k = f"{a['sport']}:{iid}"
            if k not in st or M.category(st[k], (audit.get(k) or {}).get("full_definition_status")) != "PROSPECTIVE": continue
            f = feeds[feed_of(audit[k])]; f[role] += 1; f["archetypes"].add((a["sport"], a["name"])); f["inputs"][iid] += 1 if role == "primary" else 0; f["sports"].add(a["sport"])
    rows = []
    for ds, f in feeds.items():
        sup = SUPPLY.get(ds, ("model / simulation / rules / draft / award inputs (not a capturable vintage)", "not applicable", "n/a", "depend on other inputs being built or on rules references", "NOT_A_CAPTURE_TARGET: fill by completing upstream inputs", "none", "n/a") if ds == NON_VINTAGE else FALLBACK)
        rows.append({"feed_dataset": ds, "feed": sup[0], "sports": sorted(f["sports"]), "primary_slots": f["primary"], "secondary_slots": f["secondary"], "context_slots": f["context"], "archetypes": len(f["archetypes"]),
                     "top_inputs_by_primary_slots": [[i, n] for i, n in f["inputs"].most_common(5) if n], "existing_supplier": sup[1], "evidence_class": sup[2], "supplier_gap": sup[3], "action": sup[4], "owner_prerequisite": sup[5], "rights": sup[6],
                     "planned": ds in SUPPLY, "vintage_feed": ds not in (NON_VINTAGE, NEWS_ONLY)})
    rows.sort(key=lambda r: (not r["vintage_feed"], -r["primary_slots"], -r["archetypes"], r["feed_dataset"]))
    for i, r in enumerate(rows, 1): r["priority"] = i
    tot_p = sum(r["primary_slots"] for r in rows if r["vintage_feed"]); planned_p = sum(r["primary_slots"] for r in rows if r["planned"] and r["vintage_feed"])
    nonv = sum(r["primary_slots"] for r in rows if r["feed_dataset"] == NON_VINTAGE); news = sum(r["primary_slots"] for r in rows if r["feed_dataset"] == NEWS_ONLY)
    return {"schema": "prospective-capture-plan-1.0", "status": "RESEARCH_ONLY", "ACTIVE": False, "nothing_scheduled_enabled_or_changed": True,
            "primary_prospective_slots_total": tot_p + nonv + news, "primary_vintage_feed_slots": tot_p, "primary_non_vintage_slots": nonv, "primary_news_only_slots": news, "primary_prospective_slots_in_planned_feeds": planned_p, "feeds": rows,
            "rules_text_plan": {"note": "market semantics, separate from the predictive feeds above; NBA and NHL already capture timestamped Kalshi market objects, NFL captures 5 series; the other five sports have no archive of timestamped rules text",
                                "existing": "see semantics_capture_evidence.json", "action": "reuse the NBA/NHL archive pattern (full market snapshot plus delta, text hashed, updated_time kept) for sports without it, as an extension of each sport's existing Kalshi capture, not a new collector; owner decision per repository",
                                "must_preserve": ["rules_primary", "rules_secondary", "early_close_condition", "settlement_timer_seconds", "created_time", "updated_time", "capture timestamp", "text sha256"]}}


def render(p: dict) -> str:
    L = ["# Prospective capture plan (INACTIVE, RESEARCH_ONLY)", "",
         "Generated by `python -m alpha_engine.input_research.data_foundation.prospective_plan`. **Nothing here is active: no schedule, permission, credential, workflow or collector is created or changed.** Vintage history cannot be backfilled, so each unavailable pregame vintage is ranked by the PRIMARY-role predictive slots it would unlock; "
         "every feed is mapped to the existing sport workflow that can supply it, and a feed with an existing supplier is NEVER given a second collector (actions are verify / extend / owner-schedule). The only new-collector artefacts that exist are the older inactive templates in `docs/capture_workflows/*.proposed`.", "",
         f"{p['primary_prospective_slots_total']} PRIMARY predictive slots are in the PROSPECTIVE category: {p['primary_vintage_feed_slots']} need a capturable availability or lineup vintage, {p['primary_news_only_slots']} depend only on timestamped news/transactions (award, coaching, draft items; scraping and policy gated, not planned) and {p['primary_non_vintage_slots']} are model/simulation/rules inputs that are prospective only through their upstream inputs. The planned availability/lineup feeds below carry {p['primary_prospective_slots_in_planned_feeds']} of the {p['primary_vintage_feed_slots']} vintage slots. Evidence classes: MEASURED_PHASE9 (read this phase), MEASURED_EARLIER (earlier phase record), UNINSPECTED.", "",
         "| # | Feed (dataset) | Sports | PRIMARY slots | Archetypes | Top inputs (primary slots) | Existing supplier | Evidence | What the supplier lacks | Action | Owner prerequisite | Rights |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in [x for x in p["feeds"] if x["vintage_feed"]][:14]:
        L.append(f"| {r['priority']} | {r['feed']} (`{r['feed_dataset']}`) | {', '.join(r['sports'])} | {r['primary_slots']} | {r['archetypes']} | {', '.join(f'`{i}` {n}' for i, n in r['top_inputs_by_primary_slots'][:3])} | {r['existing_supplier']} | {r['evidence_class']} | {r['supplier_gap']} | {r['action']} | {r['owner_prerequisite']} | {r['rights']} |")
    vint = [x for x in p["feeds"] if x["vintage_feed"]]; rest = vint[14:]
    L += ["", f"{len(rest)} further availability/lineup feeds carry {sum(r['primary_slots'] for r in rest)} PRIMARY slots (mostly one or two each) ; the news-only and non-vintage slots are not capture targets; all are in `prospective_capture_plan.json`.", "",
          "## Rules text (market semantics)", "", p["rules_text_plan"]["note"] + ".", "", "* Action: " + p["rules_text_plan"]["action"] + ".", "* Must preserve: " + ", ".join(f"`{x}`" for x in p["rules_text_plan"]["must_preserve"]) + ".", "",
          "## Activation (none done)", "", "Everything above needs an owner action in the owning repository (extend or schedule an existing workflow, authorise a read, or decide a rights question). Activation order by expected gain: (1) confirm the MLB slate capture resumes at opening day, (2) add injury/QB-status vintages to the NFL capture windows, "
          "(3) schedule the NBA starters check, (4) audit NHL goalie and injury archives for field coverage, (5) inspect the soccer archive, (6) extend Kalshi market-object capture to the sports without rules-text history."]
    return "\n".join(L) + "\n"


def main() -> int:
    p = build(); OUT_JSON.write_text(json.dumps(p, indent=1, sort_keys=True, ensure_ascii=False) + "\n"); OUT_DOC.write_text(render(p)); print("wrote", OUT_DOC.name, p["primary_prospective_slots_total"], p["primary_prospective_slots_in_planned_feeds"]); return 0


if __name__ == "__main__":
    raise SystemExit(main())
