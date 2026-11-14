"""Input -> raw-data-class dependency model and measured readiness (RESEARCH_ONLY).

Each candidate input is mapped (regex over id/label/mechanism/measurement; auditable, with the matched triggers stored) to the RAW DATA CLASSES it needs. Related inputs that derive from
the same raw class are NOT counted as separate missing sources: one raw class unlocks all of them. Each (sport, class) cell is graded from MEASURED ledgers:
  2 = available: collected or pulled, populated, with usable historical depth
  1 = partial: short depth, final-only, aggregate-only or reachable-but-not-yet-collected
  0 = missing: no source reached (a blocked host is NOT proof the data does not exist)
An input is AVAILABLE if every class it needs is graded 2, PARTIAL if any is 1 and none 0, MISSING otherwise; benchmark-only (market-derived) inputs are EXCLUDED, never counted.
Specialised classes (tracking, scheme charting, lineup stints, point-in-time availability, officials, forecast vintages, news/off-field, award voting) must each be present; generic classes
(results, team box, player box, event data) are satisfied by any sport that has them.
The grading is an ESTIMATE from keyword rules: use it to prioritise acquisition; `unmapped` inputs are listed for manual review.
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from . import market_dependency as MD

ROOT = Path(__file__).resolve().parents[2]
IN = ROOT / "research/input_research"
DC = IN / "data_collection"
OUT = IN / "data_readiness.json"
SPORTS = ["NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"]
CLASSES = ["RESULTS", "TEAM_BOX", "PLAYER_BOX", "EVENT_DATA", "LINEUP_STINTS", "TRACKING", "SCHEME_CHARTING", "AVAILABILITY_PIT", "OFFICIALS", "ENV_OBSERVED", "ENV_FORECAST_PIT", "NEWS_OFFFIELD", "AWARD_VOTING"]
SPECIAL = {"LINEUP_STINTS", "TRACKING", "SCHEME_CHARTING", "AVAILABILITY_PIT", "OFFICIALS", "ENV_FORECAST_PIT", "NEWS_OFFFIELD", "AWARD_VOTING"}
TRIG = [
    ("TRACKING", r"tracking|separation|defender distance|sprint speed|bat speed|swing length|time to throw|cushion|ngs|next gen|speed and|rim protection|player tracking|spin|movement"),
    ("SCHEME_CHARTING", r"coverage|formation|personnel|man/zone|shell|route|motion|play.?action|blitz|pitch mix|pitch.?type|whiff|chase|zone rate|scheme|press|shot (quality|location|profile|zone)|danger|expected goals|\bxg\b|drop|switch|style|tactic|set.?piece|play type"),
    ("LINEUP_STINTS", r"lineup|on/off|combination|linemate|stint|pairing|rotation|minutes distribution|line combin|with/without"),
    ("AVAILABILITY_PIT", r"injur|availab|inactive|questionable|scratch|confirmed|starter status|starting (lineup|goalie|pitcher|qb)|load management|return from|suspension|withdraw|retire|participation|status"),
    ("OFFICIALS", r"referee|umpire|official|crew|chair"),
    ("ENV_FORECAST_PIT", r"forecast"),
    ("NEWS_OFFFIELD", r"news|rumou?r|transaction|trade|hire|fire|coach(ing)? (change|hot)|manager change|contract|cap\b|draft|combine|host|announce|ownership|mention|broadcast|calendar|narrative"),
    ("AWARD_VOTING", r"award|voting|voter|ballot|mvp|rookie of|heisman|naismith|ballon"),
    ("ENV_OBSERVED", r"weather|wind|temp|altitude|venue|park\b|roof|dome|surface|court speed|humidity|crowd|home.?(court|field|ice) advantage|home advantage|rink|neutral"),
    ("EVENT_DATA", r"play.?by.?play|possession|epa|win probability|drive|first (basket|goal|score|td)|hazard|score state|game state|late.?game|foul|free.?throw|empty.?net|tempo|pace|shot|pitch|plate appearance|inning|power.?play|penalt|timeout"),
    ("PLAYER_BOX", r"usage|minutes|touches|rebound|assist|steal|block|three|points|per 90|share|target|carry|snap|toi|time on ice|strikeout|walk|hit\b|home run|rbi|ace|double fault|break point|player|goalie|pitcher|hitter|batter|quarterback|\bqb\b|receiver|stat"),
    ("TEAM_BOX", r"team|rating|efficiency|offen|defen|scoring|goals|total|margin|elo|form|strength|record|standings"),
    ("RESULTS", r"schedule|rest|travel|back.to.back|bye|season|series|round|draw|bracket|simulation|streak|playoff|seed|tiebreak|clinch|result|win"),
]
# (sport, class) -> (level, evidence ledger file, note). Levels are graded from the measured ledgers; see module docstring.
C = {
 "NFL": {"RESULTS": (2, "source_verification.json", "nflverse games 2010-2026"), "TEAM_BOX": (2, "source_verification.json", "nflverse pbp 2010-2026"), "PLAYER_BOX": (2, "source_verification.json", "nflverse stats_player 2011+, snap counts 2012+"),
         "EVENT_DATA": (2, "source_verification.json", "nflverse pbp"), "LINEUP_STINTS": (1, "source_verification.json", "participation personnel 2016+, no stints"), "TRACKING": (1, "source_verification.json", "Next Gen Stats aggregates 2016+, no raw tracking"),
         "SCHEME_CHARTING": (2, "source_verification.json", "participation 2016+, FTN 2022+"), "AVAILABILITY_PIT": (1, "source_verification.json", "weekly injury designations 2009+ (final), depth charts 2001+; no inactive-list vintages"),
         "OFFICIALS": (2, "source_verification.json", "nflverse officials"), "ENV_OBSERVED": (2, "source_verification.json", "observed roof/temp/wind in games file"), "ENV_FORECAST_PIT": (0, None, "no forecast archive"),
         "NEWS_OFFFIELD": (0, None, "no transactions/news feed (draft, combine, contracts releases exist but are not collected)"), "AWARD_VOTING": (0, None, "none")},
 "NBA": {"RESULTS": (2, "repo_archives_ledger.json", "ESPN team games 2023-24 to 2026-27"), "TEAM_BOX": (2, "repo_archives_ledger.json", "team totals, quarter scores, possessions"), "PLAYER_BOX": (2, "repo_archives_ledger.json", "ESPN player games: minutes, counting stats, started flag"),
         "EVENT_DATA": (2, "repo_archives_ledger.json", "PBP 2024-26 with wall-clock times; shots with x,y 2023-26"), "LINEUP_STINTS": (2, "repo_archives_ledger.json", "five-man stints 2024-26"), "TRACKING": (0, None, "no speed/defender-distance data found free"),
         "SCHEME_CHARTING": (0, None, "no play-type/coverage data found free"), "AVAILABILITY_PIT": (1, "repo_archives_ledger.json", "official injury report rows with report_time_utc: true vintages but 2025-26 only"),
         "OFFICIALS": (0, None, "referee assignments not in the pulled archives"), "ENV_OBSERVED": (1, "repo_archives_ledger.json", "home/away only; no altitude/arena table"), "ENV_FORECAST_PIT": (0, None, "n/a"),
         "NEWS_OFFFIELD": (0, None, "none"), "AWARD_VOTING": (0, None, "none")},
 "NHL": {"RESULTS": (2, "repo_archives_ledger.json", "games 2008-2026"), "TEAM_BOX": (2, "repo_archives_ledger.json", "team states by strength 2021-26, scores, shots"), "PLAYER_BOX": (2, "repo_archives_ledger.json", "player games with EV/PP/SH splits 2021-26, goalie starter flag"),
         "EVENT_DATA": (2, "repo_archives_ledger.json", "825k shots with x,y, type, strength, goalie in net 2021-26 (+2008-2020 extension, MoneyPuck)"), "LINEUP_STINTS": (1, "repo_archives_ledger.json", "no shift/line data; goalie-in-net per shot only"),
         "TRACKING": (0, None, "none"), "SCHEME_CHARTING": (1, "repo_archives_ledger.json", "shot type/location/strength only"), "AVAILABILITY_PIT": (1, "repo_archives_ledger.json", "starter flag final; pregame lineup-probe archive exists from 2026-10 only"),
         "OFFICIALS": (0, None, "none in pulled data"), "ENV_OBSERVED": (1, "repo_archives_ledger.json", "venue only"), "ENV_FORECAST_PIT": (0, None, "n/a"), "NEWS_OFFFIELD": (0, None, "none"), "AWARD_VOTING": (0, None, "none")},
 "MLB": {"RESULTS": (2, "mlb_schedule_ledger.json", "25,202 games 2015-2025"), "TEAM_BOX": (2, "mlb_schedule_ledger.json", "scores and runs by inning"), "PLAYER_BOX": (1, "mlb_boxscores_ledger.json", "boxscores collected for 2 seasons only"),
         "EVENT_DATA": (1, "source_verification.json", "pitch/PA feed reachable (2008+) but not collected"), "LINEUP_STINTS": (1, "mlb_schedule_ledger.json", "as-played batting orders, no vintages"), "TRACKING": (1, "source_verification.json", "pitchData/hitData in the feed (reachable, not collected)"),
         "SCHEME_CHARTING": (1, "source_verification.json", "pitch types in the feed (reachable, not collected)"), "AVAILABILITY_PIT": (1, "mlb_schedule_ledger.json", "final probable pitchers; no IL/scratch vintages"), "OFFICIALS": (2, "mlb_schedule_ledger.json", "home-plate umpire id per game"),
         "ENV_OBSERVED": (2, "mlb_schedule_ledger.json", "recorded weather, venue, day/night"), "ENV_FORECAST_PIT": (0, None, "none"), "NEWS_OFFFIELD": (0, None, "transactions endpoint not collected"), "AWARD_VOTING": (0, None, "none")},
 "TENNIS": {"RESULTS": (2, "repo_archives_ledger.json", "ATP 2000-2026 and WTA 2000-2026 match results"), "TEAM_BOX": (2, "repo_archives_ledger.json", "scores and match length"), "PLAYER_BOX": (2, "repo_archives_ledger.json", "per-match serve stats: aces, DF, svpt, 1st in/won, bp saved/faced"),
            "EVENT_DATA": (1, "repo_archives_ledger.json", "MatchChartingProject subset (point-level, selected matches)"), "LINEUP_STINTS": (2, None, "n/a for singles"), "TRACKING": (0, None, "none"), "SCHEME_CHARTING": (1, "repo_archives_ledger.json", "charting subset only"),
            "AVAILABILITY_PIT": (0, None, "no withdrawal/injury vintages (retirements only as 'RET' in the score)"), "OFFICIALS": (0, None, "none"), "ENV_OBSERVED": (1, "repo_archives_ledger.json", "surface, level; no court speed/weather"),
            "ENV_FORECAST_PIT": (0, None, "none"), "NEWS_OFFFIELD": (0, None, "none"), "AWARD_VOTING": (0, None, "n/a")},
 "SOCCER": {"RESULTS": (2, "source_verification.json", "five leagues 2015/16-2025/26; Kalshi lists ~40 leagues"), "TEAM_BOX": (2, "source_verification.json", "shots, SOT, corners, fouls, cards (99.9-100%)"), "PLAYER_BOX": (0, None, "no player-level data (FBref blocked from the runner)"),
            "EVENT_DATA": (0, None, "no event/xG data"), "LINEUP_STINTS": (0, None, "none"), "TRACKING": (0, None, "none"), "SCHEME_CHARTING": (0, None, "no xG/formation data"), "AVAILABILITY_PIT": (0, None, "none"),
            "OFFICIALS": (1, "source_verification.json", "referee name only for the Premier League"), "ENV_OBSERVED": (0, None, "none"), "ENV_FORECAST_PIT": (0, None, "none"), "NEWS_OFFFIELD": (0, None, "none"), "AWARD_VOTING": (0, None, "none")},
 "CBB": {"RESULTS": (2, "espn_cbb_ledger.json", "ESPN scoreboards"), "TEAM_BOX": (1, "espn_cbb_ledger.json", "scores and half scores only"), "PLAYER_BOX": (0, None, "box scores not collected (ESPN summary endpoint reachable)"), "EVENT_DATA": (0, None, "none"), "LINEUP_STINTS": (0, None, "none"),
         "TRACKING": (0, None, "none"), "SCHEME_CHARTING": (0, None, "none"), "AVAILABILITY_PIT": (1, None, "2026 roster/availability archives in cbb-edge-finder (weeks, not seasons)"), "OFFICIALS": (0, None, "none"),
         "ENV_OBSERVED": (1, "espn_cbb_ledger.json", "venue, neutral site, attendance"), "ENV_FORECAST_PIT": (0, None, "n/a"), "NEWS_OFFFIELD": (0, None, "none"), "AWARD_VOTING": (0, None, "none")},
 "CFB": {"RESULTS": (2, "espn_cfb_ledger.json", "ESPN scoreboards"), "TEAM_BOX": (1, "espn_cfb_ledger.json", "scores and quarter scores only"), "PLAYER_BOX": (0, None, "box scores not collected (raw ESPN archive covers 2026-11 only)"), "EVENT_DATA": (0, None, "no play-by-play collected"),
         "LINEUP_STINTS": (0, None, "none"), "TRACKING": (0, None, "none"), "SCHEME_CHARTING": (0, None, "none"), "AVAILABILITY_PIT": (1, None, "2026 availability archive in cfb-edge-finder (weeks)"), "OFFICIALS": (0, None, "none"),
         "ENV_OBSERVED": (1, "espn_cfb_ledger.json", "venue, indoor, neutral site, attendance"), "ENV_FORECAST_PIT": (0, None, "none"), "NEWS_OFFFIELD": (0, None, "none"), "AWARD_VOTING": (0, None, "none")},
}


def classes_for(text: str, iid: str):
    t = (text + " " + iid).lower()
    hits = [(c, m.group(0)) for c, rx in TRIG for m in [re.search(rx, t)] if m]
    return hits


def grade(sport: str, hits) -> tuple[str, list]:
    need = [c for c, _ in hits]
    if not need:
        return "UNMAPPED", []
    spec = [c for c in need if c in SPECIAL]
    lv = {c: C[sport][c][0] for c in set(spec)}
    if not spec:
        generic = [c for c in need if c not in SPECIAL]
        lv = {c: C[sport][c][0] for c in set(generic)}
        # generic: satisfied if ANY triggered generic class is available (an input can usually be built from the best available one)
        best = max(lv.values())
        return ("AVAILABLE" if best == 2 else "PARTIAL" if best == 1 else "MISSING"), sorted(lv.items())
    worst = min(lv.values())
    return ("AVAILABLE" if worst == 2 else "PARTIAL" if worst == 1 else "MISSING"), sorted(lv.items())


def build() -> dict:
    res = {"schema_version": "data-readiness-1.0", "status": "RESEARCH_ONLY", "classes": CLASSES, "matrix": {s: {c: {"level": v[0], "evidence": v[1], "note": v[2]} for c, v in C[s].items()} for s in SPORTS}, "by_sport": {}, "inputs": {}}
    unlock = collections.defaultdict(lambda: collections.Counter())
    for sp in SPORTS:
        cat = json.loads((IN / f"catalog/{sp}.json").read_text())
        arch_of = collections.defaultdict(list)
        for sec in ("archetypes", "unregistered_archetypes"):
            for a, rec in (cat.get(sec) or {}).items():
                for i in rec["inputs"]:
                    arch_of[i["id"]].append(a)
        cnt = collections.Counter()
        for iid, r in cat["inputs"].items():
            if MD.kind(iid) == "benchmark_only":
                res["inputs"][f"{sp}:{iid}"] = {"sport": sp, "status": "EXCLUDED_BENCHMARK_ONLY", "classes": []}; cnt["EXCLUDED_BENCHMARK_ONLY"] += 1; continue
            hits = classes_for(r["label"] + " " + r["mechanism"] + " " + r["measurement"], iid)
            st, lv = grade(sp, hits)
            res["inputs"][f"{sp}:{iid}"] = {"sport": sp, "status": st, "classes": [c for c, _ in hits], "levels": lv, "triggers": hits[:6], "archetypes": len(arch_of.get(iid, []))}
            cnt[st] += 1
            if st in ("PARTIAL", "MISSING"):
                # which single class upgrade (to 2) would make it AVAILABLE?
                for c in {c for c, _ in hits if c in SPECIAL and C[sp][c][0] < 2}:
                    rest = [x for x in {c2 for c2, _ in hits if c2 in SPECIAL} if x != c]
                    if all(C[sp][x][0] == 2 for x in rest):
                        unlock[(sp, c)]["inputs"] += 1; unlock[(sp, c)]["archetype_links"] += len(arch_of.get(iid, []))
        res["by_sport"][sp] = {"inputs": len(cat["inputs"]), **dict(cnt), "strictly_available_or_partial": cnt["AVAILABLE"] + cnt["PARTIAL"]}
    # per-archetype readiness: share of PRIMARY inputs (excluding benchmark-only) that are AVAILABLE; FULL = >=70% of primary inputs AVAILABLE; EXPERIMENTABLE = >=40% (enough to enter the market-free search with the available subset, remaining inputs listed as blocked); PARTIAL = >=50% available-or-partial; else BLOCKED
    arch = {}
    for sp in SPORTS:
        cat = json.loads((IN / f"catalog/{sp}.json").read_text())
        for sec, label in (("archetypes", "registered"), ("unregistered_archetypes", "unregistered")):
            for a, rec in (cat.get(sec) or {}).items():
                ins = [i for i in rec["inputs"] if res["inputs"][f"{sp}:{i['id']}"]["status"] != "EXCLUDED_BENCHMARK_ONLY"]
                prim = [i for i in ins if i.get("role") in ("primary", None)] or ins
                cnt = collections.Counter(res["inputs"][f"{sp}:{i['id']}"]["status"] for i in ins)
                pcnt = collections.Counter(res["inputs"][f"{sp}:{i['id']}"]["status"] for i in prim)
                share = pcnt["AVAILABLE"] / max(1, len(prim))
                share_ap = (pcnt["AVAILABLE"] + pcnt["PARTIAL"]) / max(1, len(prim))
                blocking = sorted({c for i in prim for c, lv in res["inputs"][f"{sp}:{i['id']}"].get("levels", []) if lv == 0 and c in SPECIAL})
                arch[f"{sp}:{a}"] = {"sport": sp, "archetype": a, "kind": label, "inputs_model_eligible": len(ins), "available": cnt["AVAILABLE"], "partial": cnt["PARTIAL"], "missing": cnt["MISSING"], "primary_inputs": len(prim),
                                     "primary_available_share": round(share, 3), "primary_available_or_partial_share": round(share_ap, 3), "blocking_missing_classes": blocking,
                                     "readiness": "FULL" if share >= 0.7 else ("EXPERIMENTABLE" if share >= 0.4 else ("PARTIAL" if share_ap >= 0.5 else "BLOCKED"))}
    res["archetype_readiness"] = arch
    res["unlock_ranking"] = sorted(({"sport": s, "class": c, "inputs_unlocked_by_upgrading_to_full": v["inputs"], "archetype_links": v["archetype_links"], "current_level": C[s][c][0], "current_note": C[s][c][2]} for (s, c), v in unlock.items()),
                                   key=lambda x: (-x["inputs_unlocked_by_upgrading_to_full"], -x["archetype_links"]))
    # inputs newly unlocked: AVAILABLE/PARTIAL now but without a measured free source before this round (coverage_audit.json 'with_measured_free_source')
    audit = json.loads((ROOT / "research/audit/input_research/coverage_audit.json").read_text())
    before = {f"{sp}:{i}" for sp, v in audit["readiness"].items() for i in v["with_measured_free_source"]}
    now_ok = {i for i, r in res["inputs"].items() if r["status"] in ("AVAILABLE", "PARTIAL")}
    res["before_after"] = {"before_inputs_with_measured_free_source": len(before), "after_available": sum(1 for r in res["inputs"].values() if r["status"] == "AVAILABLE"), "after_available_or_partial": len(now_ok),
                           "newly_unlocked_inputs": len(now_ok - before), "previously_counted_but_not_available_or_partial_now": sorted(before - now_ok),
                           "newly_unlocked_by_sport": {sp: len([i for i in now_ok - before if res["inputs"][i]["sport"] == sp]) for sp in SPORTS},
                           "note": "'before' counted inputs whose named source was measured reachable; 'after' grades whether the RAW DATA CLASSES an input needs are in hand. Not the same yardstick: use both numbers, and treat 'after' as an upper-bound estimate until each input is actually computed."}
    res["totals"] = {k: sum(v.get(k, 0) for v in res["by_sport"].values()) for k in ("AVAILABLE", "PARTIAL", "MISSING", "UNMAPPED", "EXCLUDED_BENCHMARK_ONLY")} | {"inputs": sum(v["inputs"] for v in res["by_sport"].values())}
    return res


def summary(r: dict) -> dict:
    """Dashboard-sized view (no per-input triggers)."""
    return {k: r[k] for k in ("schema_version", "status", "classes", "matrix", "by_sport", "archetype_readiness", "unlock_ranking", "totals", "before_after")}


if __name__ == "__main__":
    r = build()
    OUT.write_text(json.dumps(r, indent=0, sort_keys=True, default=str))
    (IN / "data_readiness_summary.json").write_text(json.dumps(summary(r), indent=0, sort_keys=True, default=str))
    print(r["totals"])
    for s, v in r["by_sport"].items(): print(s, v)
    for u in r["unlock_ranking"][:14]: print(u)
