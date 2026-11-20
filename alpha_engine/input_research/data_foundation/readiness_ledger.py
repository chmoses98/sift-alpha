"""Actionable readiness ledger for the missing PRIMARY slots (RESEARCH_ONLY; no collection, no purchase, no schedule change).

    python -m alpha_engine.input_research.data_foundation.readiness_ledger          # writes research/input_research/readiness/*
    python -m alpha_engine.input_research.data_foundation.readiness_ledger --check  # fails if the committed files would change

Why: the completeness inventory counts missing PRIMARY *slots* (input x market archetype), sorted by whether a free source exists. That does not say
what to DO next. This ledger gives every missing slot exactly one action class, reconciled exactly with market_completeness.json:

  A  DATA_MISSING            we do not hold the data: a free source is identified but not collected (A_FREE_NOT_COLLECTED), none is known
                             (A_NO_FREE_SOURCE), or blind rounds disagree that a permitted source exists (A_SOURCE_CONTESTED)
  B  DATA_IN_HAND_NO_BUILDER every dataset the input lists is already held (sift-data-vault archive or a repo archive), but no certified builder exists
  C  CALCULATED_NOT_CERTIFIED a builder computed it but certification failed or was downgraded (formal resolution needed; never overridden here)
  E  PROSPECTIVE_CAPTURE     needs timestamped capture from now on (no backfillable point-in-time history), incl. point-in-time quarantined builds
  G  LEGAL_POLICY_BLOCKED    the only source is blocked by provider policy / terms (needs clearance, not engineering)
and two orthogonal flags on every slot:
  F  (priority_tier)         P1 = markets SIFT intends to price first (moneyline/spread/win prob, game and team totals, 1H/1Q/periods, MLB F5 and
                             first inning, NFL/NBA/CBB core player props); P2 = other game-level markets; F = optional / low value (futures, awards,
                             draft, off-field, all-star, parlays built from other legs, ...)
  rights_unresolved          a dataset the slot depends on has rights tier UNRESOLVED_INTERNAL_ONLY (free to access is NOT licensed for every use)
D (certified inputs not consumed by an operating model) is a property of CERTIFIED inputs, not of missing slots: see adoption.py / adoption_registry.json.

Holdings: `VAULT_HOLDINGS` is a curated map dataset_id -> vault archive, written from the vault manifests (each entry cites the manifest note). A
dataset is "held" if it is COLLECTED_ARCHIVE in the acquisition queue or listed here. This corrects the queue, which still shows several datasets as
FREE_REACHABLE although the 2026-11-16 vault collection archived them.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
IR = ROOT / "research/input_research"
OUT = IR / "readiness"

# dataset_id -> (vault archive path(s), coverage note from the manifest). Only datasets whose manifest names the required tables are listed.
VAULT_HOLDINGS = {
    "nfl.pbp": (["archives/NFL/pbp/1999-2009", "archives/NFL/pbp/2010-2026"], "nflverse play-by-play 1999-2026 (manifest: replay range of the certified NFL builder)"),
    "nfl.player_stats_weekly": (["archives/NFL/inseason_player_team/1999-2026"], "stats_player_week / stats_team_week 1999-2026"),
    "nfl.participation": (["archives/NFL/inseason_player_team/1999-2026"], "pbp_participation 2016-2025 (2026 not available upstream at retrieval)"),
    "nfl.schedule_results": (["archives/NFL/inseason_player_team/1999-2026"], "games / schedules"),
    "nfl.ftn_charting": (["archives/NFL/inseason_player_team/1999-2026"], "FTN charting 2026 only"),
    "nfl.snap_counts": (["archives/NFL/inseason_player_team/1999-2026"], "snap counts 2012-2026"),
    "nfl.nextgen_stats": (["archives/NFL/inseason_player_team/1999-2026"], "NGS 2016-2024 (+ partial 2025-26; passing 2025-26 missing upstream)"),
    "nfl.injuries_weekly": (["archives/NFL/inseason_player_team/1999-2026"], "injuries 2009-2026 (final-of-week designations)"),
    "nfl.depth_charts": (["archives/NFL/inseason_player_team/1999-2026"], "weekly depth charts"),
    "nfl.contracts_cap": (["archives/NFL/inseason_player_team/1999-2026"], "contracts table"),
    "mlb.pitch_pa_events": (["archives/MLB/postgame_feed_compact/2022..2026"], "every plate appearance with pitch-level events and batted-ball data, 2022-2026"),
    "cbb.box_player": (["archives/CBB/espn_player_box_pbp_early_seasons/2003-2027"], "player box scores 2003-2027 (play-by-play only for 2027)"),
    "cfb.box_player": (["archives/CFB/espn_summary_postgame/2014-2025", "archives/CFB/espn_summary_postgame/2026"], "ESPN summary: team box, player box, drives, play-by-play"),
    "nhl.shifts_lines": (["archives/NHL/shifts/2011-2027"], "shift charts 2011-2027 (line combinations are derived, not provided)"),
}

# P1: markets the operating plan prices first. Everything not P1 and not low-value is P2.
P1 = {
    "NBA": {"game_moneyline_spread", "game_win_margin", "game_total", "team_total", "quarter_and_half_markets", "player_points", "player_rebounds", "player_assists", "player_threes", "combo_props", "player_free_throws"},
    "CBB": {"game_moneyline_spread", "game_total", "team_total", "first_half", "player_points", "player_props", "player_threes", "player_rebounds_assists"},
    "NFL": {"game_moneyline_spread", "game_total", "team_total", "first_half_and_quarter_totals", "score_path_functionals", "rushing_yards", "qb_passing_yards", "receiving_yards_and_receptions", "qb_passing_tds_and_ints", "anytime_first_td_scorer"},
    "CFB": {"game_moneyline_spread", "game_total", "team_total", "quarter_and_half_totals", "quarter_and_half_sides", "half_full_double_result"},
    "MLB": {"game_moneyline", "game_total_and_team_total", "first5_markets", "first_inning_and_inning_markets", "pitcher_strikeouts", "pitcher_outs"},
    "NHL": {"game_moneyline_puckline", "game_total_and_team_total", "period_markets"},
    "SOCCER": {"match_result_3way", "total_goals", "first_half_and_period", "handicap_and_exact_score", "btts_and_clean_sheet"},
    "TENNIS": {"match_winner", "total_games_and_sets", "set_and_game_spreads"},
}
LOW_VALUE_WORDS = ("futures", "award", "draft", "off_field", "offfield", "off_court", "all_star", "announcer", "labour", "coaching", "polls", "transactions", "summer_league",
                   "combine", "leader", "parlay", "combo_tournament", "nationality", "season_ranking", "mvp", "squad_selection", "host", "bracket", "governance", "kenpom")

SHORT = {"A_FREE_NOT_COLLECTED": "A-free", "A_NO_FREE_SOURCE": "A-none", "A_SOURCE_CONTESTED": "A-contested", "B_DATA_IN_HAND_NO_BUILDER": "B",
         "C_CALCULATED_NOT_CERTIFIED": "C", "E_PROSPECTIVE_CAPTURE": "E", "G_LEGAL_POLICY_BLOCKED": "G"}
CLASSES = ("A_FREE_NOT_COLLECTED", "A_NO_FREE_SOURCE", "A_SOURCE_CONTESTED", "B_DATA_IN_HAND_NO_BUILDER", "C_CALCULATED_NOT_CERTIFIED", "E_PROSPECTIVE_CAPTURE", "G_LEGAL_POLICY_BLOCKED")


def tier(sport: str, arche: str) -> str:
    if arche in P1.get(sport, ()):
        return "P1"
    return "F" if any(w in arche for w in LOW_VALUE_WORDS) else "P2"


def load():
    mc = json.loads((IR / "market_completeness/market_completeness.json").read_text())
    inp = {r["input_key"]: r for r in csv.DictReader((IR / "market_input_map/distinct_inputs.csv").open())}
    q = {r["dataset_id"]: r for r in csv.DictReader((IR / "market_input_map/acquisition_queue.csv").open())}
    return mc, inp, q


def held(ds: str, q: dict) -> bool:
    return ds in VAULT_HOLDINGS or (q.get(ds) or {}).get("access_status") == "COLLECTED_ARCHIVE"


def classify(cat: str, x: dict, q: dict) -> tuple[str, list[str]]:
    vs = x["verified_status"]; dss = [d for d in x["free_source_datasets"].split("|") if d]
    if vs == "DOWNGRADED_BY_VERIFIER":
        return "C_CALCULATED_NOT_CERTIFIED", dss
    if vs == "BLOCKED_BY_POLICY":
        return "G_LEGAL_POLICY_BLOCKED", dss
    if cat == "PROSPECTIVE":
        return "E_PROSPECTIVE_CAPTURE", dss
    if cat == "CONTESTED":
        return "A_SOURCE_CONTESTED", dss
    if cat == "NO_FREE_SOURCE":
        return "A_NO_FREE_SOURCE", dss
    if cat == "DATA_IN_HAND" or (dss and all(held(d, q) for d in dss)):
        return "B_DATA_IN_HAND_NO_BUILDER", dss
    return "A_FREE_NOT_COLLECTED", dss


def build() -> dict:
    mc, inp, q = load(); slots = []
    for r in mc["rows"]:
        for iid in r["missing_critical_ids"]:
            x = inp[f"{r['sport']}:{iid}"]; cat = r["input_categories"][iid]; cls, dss = classify(cat, x, q)
            rights = sorted({(q.get(d) or {}).get("rights_tier") or x["rights_tier"] for d in dss} or {x["rights_tier"]})
            slots.append({"sport": r["sport"], "archetype": r["archetype"], "input_id": iid, "inventory_category": cat, "verified_status": x["verified_status"], "class": cls,
                          "priority_tier": tier(r["sport"], r["archetype"]), "datasets": dss, "datasets_held": [d for d in dss if held(d, q)],
                          "rights_unresolved": any(t == "UNRESOLVED_INTERNAL_ONLY" for t in rights), "rights_tiers": rights})
    n_inventory = sum(r["primary_missing_critical"] for r in mc["rows"])
    by = lambda keyf: dict(sorted(Counter(keyf(s) for s in slots).items()))
    # shared work: group slots by the ONE action that would address them
    groups: dict = defaultdict(lambda: {"slots": 0, "P1_slots": 0, "inputs": set(), "archetypes": set()})
    for s in slots:
        key = (s["class"], "+".join(sorted(s["datasets"])) or "(no dataset listed)")
        g = groups[key]; g["slots"] += 1; g["P1_slots"] += s["priority_tier"] == "P1"; g["inputs"].add(f"{s['sport']}:{s['input_id']}"); g["archetypes"].add(f"{s['sport']}:{s['archetype']}")
    shared = sorted(({"class": k[0], "datasets": k[1], "slots": v["slots"], "P1_slots": v["P1_slots"], "distinct_inputs": len(v["inputs"]), "archetypes": len(v["archetypes"]),
                      "inputs": sorted(v["inputs"])} for k, v in groups.items()), key=lambda d: (-d["P1_slots"], -d["slots"], d["class"], d["datasets"]))
    # readiness of the P1 operating markets: certified share of their PRIMARY inputs (from the same completeness rows)
    p1 = []
    for r in mc["rows"]:
        if tier(r["sport"], r["archetype"]) != "P1":
            continue
        cov = r["primary_FULL"] + r["primary_PARTIAL"] + r["primary_PROXY"]
        mine = [s for s in slots if s["sport"] == r["sport"] and s["archetype"] == r["archetype"]]
        p1.append({"sport": r["sport"], "archetype": r["archetype"], "label": r["label"], "primary_inputs": r["n_primary"], "primary_certified": cov,
                   "primary_FULL": r["primary_FULL"], "primary_PARTIAL": r["primary_PARTIAL"], "primary_PROXY": r["primary_PROXY"], "primary_missing": r["primary_missing_critical"],
                   "missing_by_class": dict(sorted(Counter(s["class"] for s in mine).items())), "critical_score": round(r["critical_score"], 4)})
    p1.sort(key=lambda d: (d["sport"], d["archetype"]))
    tot = {"slots": len(slots), "inventory_primary_missing_critical": n_inventory, "reconciles": len(slots) == n_inventory}
    return {"schema": "readiness-ledger-1.0", "status": "RESEARCH_ONLY",
            "note": "Action classes for every missing PRIMARY slot (input x archetype); reconciled exactly with market_completeness.json. Slots are market requirements, not datasets: many share one dataset or one builder.",
            "totals": tot, "by_class": by(lambda s: s["class"]), "by_tier": by(lambda s: s["priority_tier"]), "by_class_and_tier": by(lambda s: f"{s['class']}|{s['priority_tier']}"),
            "by_inventory_category_and_class": by(lambda s: f"{s['inventory_category']}->{s['class']}"),
            "by_sport_class": by(lambda s: f"{s['sport']}|{s['class']}"), "rights_unresolved_slots": sum(s["rights_unresolved"] for s in slots),
            "distinct_inputs_by_class": {c: len({(s["sport"], s["input_id"]) for s in slots if s["class"] == c}) for c in CLASSES},
            "vault_holdings_used": {k: {"vault": v[0], "coverage": v[1]} for k, v in VAULT_HOLDINGS.items()},
            "queue_corrections": sorted(d for d in VAULT_HOLDINGS if d in q and q[d]["access_status"] != "COLLECTED_ARCHIVE"),
            "shared_work": shared, "p1_market_readiness": p1, "slots": slots}


def write(d: dict, root: Path = OUT) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    full = root / "readiness_ledger.json"; full.write_text(json.dumps(d, indent=1) + "\n")
    lines = ["# Readiness ledger: what to do about the missing PRIMARY slots (generated; RESEARCH_ONLY)", "",
             f"{d['totals']['slots']} missing PRIMARY slots, reconciled with market_completeness.json ({d['totals']['inventory_primary_missing_critical']}): {d['totals']['reconciles']}. "
             "A slot is one input required by one market archetype; slots are not datasets.", "",
             "| Class | Meaning | Slots | P1 slots | Distinct inputs |", "|---|---|---|---|---|"]
    mean = {"A_FREE_NOT_COLLECTED": "free source known, not collected", "A_NO_FREE_SOURCE": "no permitted free source known", "A_SOURCE_CONTESTED": "blind rounds disagree a source exists",
            "B_DATA_IN_HAND_NO_BUILDER": "data already held; needs builder + certification", "C_CALCULATED_NOT_CERTIFIED": "built, certification failed/downgraded",
            "E_PROSPECTIVE_CAPTURE": "needs timestamped capture from now on", "G_LEGAL_POLICY_BLOCKED": "source blocked by provider policy/terms"}
    for c in CLASSES:
        lines.append(f"| {c} | {mean[c]} | {d['by_class'].get(c, 0)} | {d['by_class_and_tier'].get(c + '|P1', 0)} | {d['distinct_inputs_by_class'][c]} |")
    lines += ["", f"Priority tiers: {d['by_tier']}. Slots depending on a dataset whose rights are UNRESOLVED_INTERNAL_ONLY: {d['rights_unresolved_slots']}.",
              f"Queue corrections (archived in sift-data-vault but still FREE_REACHABLE in the acquisition queue): {', '.join(d['queue_corrections'])}.", "",
              "## Highest-value shared work (one dataset / one builder closes many P1 slots)", "", "| Class | Datasets | P1 slots | All slots | Distinct inputs |", "|---|---|---|---|---|"]
    for g in d["shared_work"][:25]:
        lines.append(f"| {g['class']} | {g['datasets']} | {g['P1_slots']} | {g['slots']} | {g['distinct_inputs']} |")
    lines += ["", "## P1 operating-market readiness (certified share of PRIMARY inputs)", "", "| Sport | Market | Certified / primary | Missing by class |", "|---|---|---|---|"]
    for p in d["p1_market_readiness"]:
        lines.append(f"| {p['sport']} | {p['archetype']} | {p['primary_certified']}/{p['primary_inputs']} | {', '.join(f'{SHORT[k]}:{v}' for k, v in p['missing_by_class'].items()) or '-'} |")
    md = root / "README.md"; md.write_text("\n".join(lines) + "\n")
    dash = root / "dashboard.json"        # compact copy for the dashboard (no per-slot rows)
    dash.write_text(json.dumps({k: d[k] for k in ("schema", "status", "note", "totals", "by_class", "by_tier", "by_class_and_tier", "distinct_inputs_by_class", "rights_unresolved_slots", "queue_corrections", "p1_market_readiness")}
                               | {"shared_work": [{k: v for k, v in g.items() if k != "inputs"} for g in d["shared_work"][:15]], "classes": list(CLASSES), "short": SHORT}, indent=1) + "\n")
    return [full, md, dash]


def main(a=None) -> int:
    a = a or sys.argv[1:]; d = build()
    if not d["totals"]["reconciles"]:
        raise SystemExit(f"readiness ledger does not reconcile: {d['totals']}")
    if "--check" in a:
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            new = write(d, Path(t)); bad = [p.name for p in new if (OUT / p.name).read_text() != p.read_text()] if OUT.exists() else ["(missing)"]
        if bad:
            raise SystemExit(f"readiness ledger out of date: {bad}")
        print("readiness ledger up to date"); return 0
    for p in write(d):
        print("wrote", p.relative_to(ROOT))
    print(d["by_class"], d["by_tier"]); return 0


if __name__ == "__main__":
    raise SystemExit(main())
