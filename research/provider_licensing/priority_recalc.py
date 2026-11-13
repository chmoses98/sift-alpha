"""Provider priority recalculation over DISTINCT missing PRIMARY slots (RESEARCH_ONLY, read-only).

Reads only research/input_research/market_input_map/map.json (Phase 14 @ 88b0a77).
No network, no collection, no registry change. Output (when run as a script): priority_recalc.json next to this file.
Importing the module computes `res` without writing (tests/test_provider_priority_recalc.py).
A slot = (archetype, input) pair, as listed in the acquisition queue's `slots`.

Revision 2 (2026-11-13), corrections to revision 1 (c34f3df):
  * Each input need now considers every dataset the map links to that need: SATISFIED_BY *and*
    CANDIDATE_ALTERNATIVE. A candidate counts only when it passes the same rights and access gates
    ("permitted"). Rev 1 looked only at SATISFIED_BY.
  * PIT is checked at the satisfying-dataset level. A need is PIT-supported only when a permitted
    dataset that passes the gate carries a strict-PIT edge (EVENT_TIME / PIT_NATIVE / STATIC) for that exact
    (dataset, input, need). Rev 1 checked only the input's pit_verdict at need level, and at dataset level
    keyed edge pit by (dataset, input), which silently kept the last of several needs.
  * Hypothetical rights clearance is reported separately from BUILD-READY. Build-ready uses the registry as
    it is today (no hypothetical clearance), cost == "free" (no key or account), and archived or reachable access.
Rev-1 numbers are recomputed by `legacy=True` paths, so the before/after comparison is reproducible.
"""
import json, collections, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
M = json.loads((ROOT / "research/input_research/market_input_map/map.json").read_text())

PROVIDER = {  # source id -> upstream rights holder (same roll-up rule as PROVIDER_ACQUISITION_PLAN.md)
    "espn_json": "ESPN", "espn_cbb": "ESPN", "espn_nba_archive": "ESPN",
    "nflverse": "nflverse", "mlb_statsapi": "MLBAM", "savant": "MLBAM",
    "nhl_api": "NHL", "nhl_archive": "NHL", "football_data_uk": "football-data.co.uk",
    "cfbd": "CFBD", "football_data_org": "football-data.org", "kalshi_api": "Kalshi",
    "bbref": "Sports Reference", "bbref_baseball": "Sports Reference", "pfr": "Sports Reference",
    "sports_reference": "Sports Reference", "wikipedia": "Wikimedia", "rules_docs": "Rulebooks",
    "ncaa_official": "NCAA", "noaa_nws": "NOAA/NWS", "openmeteo": "Open-Meteo",
    "nba_official": "NBA", "nba_cdn": "NBA", "nba_stats_api": "NBA", "moneypuck": "MoneyPuck",
    "chadwick": "Chadwick", "retrosheet": "Retrosheet",
}
def prov(s): return PROVIDER.get(s, s)

def cleared(s):  # research-usable today: registry research_cleared AND collection_allowed
    r = M["sources"][s]["rights"]
    return r["research_cleared"] and r["collection_allowed"]

DS = M["datasets"]
inp = M["inputs"]
cat = {(e[0], e[1]): e[5] for e in M["edges"] if e[2] == "primary"}
STRICT_PIT = {"EVENT_TIME", "PIT_NATIVE", "STATIC"}

# edge pit keyed by the exact (dataset, input, need); strict only if every edge for that triple is strict
EPIT = collections.defaultdict(set)
for d, i, et, need, _t, pit, _a in M["dataset_edges"]:
    EPIT[(d, i, need)].add(pit)
def strict(d, i, need): return bool(EPIT[(d, i, need)]) and EPIT[(d, i, need)] <= STRICT_PIT

q_all = M["queue"]
q = [e for e in q_all if e["action_group"] == "RIGHTS_APPROVAL_NEEDED"]
all_slots = {tuple(s) for e in q for s in e["slots"]}
all_queue_slots = {tuple(s) for e in q_all for s in e["slots"]}
slot_group = {}
for e in q_all:
    for s in e["slots"]: slot_group.setdefault(tuple(s), set()).add(e["action_group"])

def blk(d): return {prov(s) for s in DS[d]["sources"] if not cleared(s)}
ds_block = {e["dataset"]: sorted(blk(e["dataset"])) for e in q}

# ---------------- dataset-level upper bound (rev 1 method; PIT now keyed per need) ----------------
def slot_flags(d, slot):
    a, i = slot
    st = DS[d]["access_status"]
    archived, reachable = st == "COLLECTED_ARCHIVE", st in ("FREE_REACHABLE", "COLLECTED_ARCHIVE")
    needs_here = [n for (dd, ii, n) in EPIT if dd == d and ii == i]
    pit_ok = (cat.get(slot) != "PROSPECTIVE" and inp.get(i, {}).get("pit_verdict") == "PIT_SAFE"
              and bool(needs_here) and all(strict(d, i, n) for n in needs_here))
    return archived, reachable, pit_ok

out = {}
for p in sorted({p for b in ds_block.values() for p in b}):
    touch, alone = set(), {}
    for d, b in ds_block.items():
        if p not in b: continue
        sl = {tuple(s) for s in next(e for e in q if e["dataset"] == d)["slots"]}
        touch |= sl
        if b == [p]:
            for s in sl:
                f = slot_flags(d, s)
                prev = alone.get(s, (False, False, False))
                alone[s] = tuple(x or y for x, y in zip(prev, f))
    out[p] = {
        "datasets": sorted(d for d, b in ds_block.items() if p in b),
        "datasets_alone": sorted(d for d, b in ds_block.items() if b == [p]),
        "slots_touched": len(touch),
        "unlock_alone_hypothetical": len(alone),
        "alone_archived": sum(v[0] for v in alone.values()),
        "alone_reachable_not_archived": sum(v[1] and not v[0] for v in alone.values()),
        "alone_collection_required": sum(not v[1] for v in alone.values()),
        "alone_pit_strict": sum(v[2] for v in alone.values()),
        "alone_archived_and_pit_strict": sum(v[0] and v[2] for v in alone.values()),
    }

# ---------------- need level ----------------
SB = collections.defaultdict(lambda: collections.defaultdict(set))   # input -> need -> SATISFIED_BY datasets
CA = collections.defaultdict(lambda: collections.defaultdict(set))   # input -> need -> CANDIDATE_ALTERNATIVE datasets
for d, i, et, need, *_ in M["dataset_edges"]:
    (SB if et == "SATISFIED_BY" else CA)[i][need].add(d)

def cands(i, need, legacy):
    return SB[i][need] if legacy else SB[i][need] | CA[i][need]

GATES = {
    "rights_only": lambda d: DS[d]["access_status"] not in ("PROSPECTIVE_CAPTURE_ONLY", "NO_FREE_SOURCE", "PAID_ONLY", "SAMPLE_ONLY"),
    "reachable_or_archived": lambda d: DS[d]["access_status"] in ("FREE_REACHABLE", "COLLECTED_ARCHIVE"),
    "archived_only": lambda d: DS[d]["access_status"] == "COLLECTED_ARCHIVE",
}
def usable(d, P, gate): return blk(d) <= P and gate(d)

def complete(i, P, gate, legacy=False):
    return bool(SB[i]) and all(any(usable(d, P, gate) for d in cands(i, n, legacy)) for n in SB[i])

def pit_supported(slot, P, gate, legacy=False):
    """legacy: rev-1 rule (input verdict only). New: input verdict AND every need met by a usable strict-PIT dataset."""
    a, i = slot
    if cat.get(slot) == "PROSPECTIVE" or inp.get(i, {}).get("pit_verdict") != "PIT_SAFE": return False
    if legacy: return complete(i, P, gate, legacy=True)
    return bool(SB[i]) and all(any(usable(d, P, gate) and strict(d, i, n) for d in cands(i, n, False)) for n in SB[i])

def level(P, legacy=False, universe=None):
    U = all_slots if universe is None else universe
    r = {k: {s for s in U if complete(s[1], P, g, legacy)} for k, g in GATES.items()}
    r["archived_and_pit"] = {s for s in r["archived_only"] if pit_supported(s, P, GATES["archived_only"], legacy)}
    r["reachable_and_pit"] = {s for s in r["reachable_or_archived"] if pit_supported(s, P, GATES["reachable_or_archived"], legacy)}
    return r

KEYS = ["rights_only", "reachable_or_archived", "archived_only", "archived_and_pit", "reachable_and_pit"]
ALLP = sorted({prov(x) for d in DS for x in DS[d]["sources"] if not cleared(x)})
TOP8 = ["ESPN", "nflverse", "MLBAM", "NHL", "football-data.co.uk", "CFBD", "Kalshi", "football-data.org"]

def provider_table(legacy):
    base = level(set(), legacy)
    sets = {p: {k: level({p}, legacy)[k] - base[k] for k in KEYS} for p in ALLP}
    tab = {}
    for p in ALLP:
        nl = sets[p]["rights_only"]
        others = set().union(*[sets[o]["rights_only"] for o in ALLP if o != p])
        tab[p] = {"need_level_" + k: len(sets[p][k]) for k in KEYS}
        tab[p]["need_level_exclusive_to_provider"] = len(nl - others)
    jt = level(set(TOP8), legacy)
    return base, tab, {k: len(jt[k] - base[k]) for k in KEYS}, sets

base_v1, tab_v1, joint_v1, _ = provider_table(legacy=True)
base_v2, tab_v2, joint_v2, sets_v2 = provider_table(legacy=False)
for p in out:
    out[p].update(tab_v2[p])
for p in ALLP:
    if p not in out and any(tab_v2[p].values()):
        out[p] = dict(tab_v2[p], datasets=[], datasets_alone=[], slots_touched=0, unlock_alone_hypothetical=0)

def greedy(legacy, n=12):
    g_cleared, g_done, res = set(), set(), []
    b = level(set(), legacy)["rights_only"]
    for _ in range(n):
        best, bgain = None, set()
        for p in ALLP:
            if p in g_cleared: continue
            gain = {s for s in all_slots if complete(s[1], g_cleared | {p}, GATES["rights_only"], legacy)} - g_done - b
            if len(gain) > len(bgain): best, bgain = p, gain
        if not best: break
        g_cleared.add(best); g_done |= bgain
        res.append({"provider": best, "marginal": len(bgain), "cumulative": len(g_done)})
    return res

# ---------------- what changed from candidate alternatives ----------------
alt_rescues = collections.Counter()   # (input need) rescued by a CANDIDATE_ALTERNATIVE under P = TOP8, rights_only gate
for i in {s[1] for s in all_slots}:
    for n in SB[i]:
        if not any(usable(d, set(TOP8), GATES["rights_only"]) for d in SB[i][n]):
            for d in CA[i][n]:
                if usable(d, set(TOP8), GATES["rights_only"]): alt_rescues[d] += 1
# free alternatives = CANDIDATE_ALTERNATIVE edges whose dataset is cost "free" and needs no new clearance today
free_alt_edges = [(d, i, n) for i in CA for n in CA[i] for d in CA[i][n] if DS[d]["cost"] == "free" and not blk(d)]
free_alt_edges_any = [(d, i, n) for i in CA for n in CA[i] for d in CA[i][n] if DS[d]["cost"] == "free"]
pit_needs_without_strict = sum(1 for i in list(SB) if inp.get(i, {}).get("pit_verdict") == "PIT_SAFE"
                               for n in SB[i] if not any(strict(d, i, n) for d in cands(i, n, False)))
pit_downgrades = {"pit_safe_input_needs_with_no_strict_pit_dataset": pit_needs_without_strict}  # slots the rev-1 rule called PIT-strict that fail the dataset-level check (joint TOP8)
for k_new, k_old in (("archived_and_pit", "archived_and_pit"), ("reachable_and_pit", "reachable_and_pit")):
    old = level(set(TOP8), True)[k_old]; new = level(set(TOP8), False)[k_new]
    pit_downgrades[k_new] = {"rev1": len(old), "rev2": len(new), "rev1_not_rev2": len(old - new), "rev2_not_rev1": len(new - old)}

# ---------------- BUILD-READY today (no hypothetical clearance, zero cost, no account) ----------------
FREE = lambda d: DS[d]["cost"] == "free"
BUILD_GATES = {
    "build_ready_archived": lambda d: FREE(d) and DS[d]["access_status"] == "COLLECTED_ARCHIVE",
    "build_ready_after_free_collection": lambda d: FREE(d) and DS[d]["access_status"] in ("FREE_REACHABLE", "COLLECTED_ARCHIVE"),
}
build = {}
for k, g in BUILD_GATES.items():
    sl = {s for s in all_queue_slots if complete(s[1], set(), g)}
    build[k] = {"slots": len(sl), "inputs": len({s[1] for s in sl}),
                "pit_supported_slots": sum(pit_supported(s, set(), g) for s in sl),
                "by_queue_group": dict(collections.Counter(gname for s in sl for gname in slot_group[s]))}

def need_report(i):
    """Per need: best dataset today, its blockers, access, cost, pit."""
    rows = []
    for n in sorted(SB[i]):
        opts = []
        for d in sorted(cands(i, n, False)):
            opts.append({"dataset": d, "edge": "SATISFIED_BY" if d in SB[i][n] else "CANDIDATE_ALTERNATIVE",
                         "access": DS[d]["access_status"], "cost": DS[d]["cost"], "blockers": sorted(blk(d)),
                         "pit": sorted(EPIT[(d, i, n)]), "strict_pit": strict(d, i, n)})
        rank = lambda o: (bool(o["blockers"]), o["cost"] != "free",
                          {"COLLECTED_ARCHIVE": 0, "FREE_REACHABLE": 1}.get(o["access"], 2), not o["strict_pit"])
        opts.sort(key=rank)
        rows.append({"need": n, "best": opts[0], "n_options": len(opts)})
    return rows

def input_readiness(i):
    nr = need_report(i)
    bests = [r["best"] for r in nr]
    if any(b["blockers"] for b in bests): tier = "RIGHTS_BLOCKED"
    elif any(b["cost"] != "free" for b in bests): tier = "NOT_ZERO_COST"
    elif all(b["access"] == "COLLECTED_ARCHIVE" for b in bests): tier = "BUILD_READY_ARCHIVED"
    elif all(b["access"] in ("COLLECTED_ARCHIVE", "FREE_REACHABLE") for b in bests): tier = "BUILD_READY_AFTER_FREE_COLLECTION"
    else: tier = "ACCESS_UNCONFIRMED"
    return tier, nr

cand_inputs = sorted({s[1] for s in all_queue_slots})
slots_per_input = collections.Counter(s[1] for s in all_queue_slots)
TIER_ORDER = ["BUILD_READY_ARCHIVED", "BUILD_READY_AFTER_FREE_COLLECTION", "ACCESS_UNCONFIRMED", "NOT_ZERO_COST", "RIGHTS_BLOCKED"]
ranked = []
for i in cand_inputs:
    tier, nr = input_readiness(i)
    blockers = sorted({b for r in nr for b in r["best"]["blockers"]})
    pit_ok = inp[i]["pit_verdict"] == "PIT_SAFE" and all(r["best"]["strict_pit"] for r in nr)
    ranked.append({"input": i, "tier": tier, "missing_primary_slots": slots_per_input[i],
                   "queue_groups": sorted({gname for s in all_queue_slots if s[1] == i for gname in slot_group[s]}),
                   "input_pit_verdict": inp[i]["pit_verdict"], "pit_supported_by_best_datasets": pit_ok,
                   "rights_blockers_of_best_path": blockers, "n_blocking_providers": len(blockers),
                   "built": inp[i].get("built"), "vstatus": inp[i].get("vstatus"),
                   "needs": [{"need": r["need"], "dataset": r["best"]["dataset"], "edge": r["best"]["edge"],
                              "access": r["best"]["access"], "cost": r["best"]["cost"],
                              "blockers": r["best"]["blockers"], "pit": r["best"]["pit"]} for r in nr]})
# Evidence class per blocking provider, from docs/PROVIDER_LICENSING_EVIDENCE.md (rev 2). Used only to order near misses;
# it never clears anything. PROHIBITED = a primary text read in this repo bars the use; RESTRICTIVE = indexed/secondary text
# is restrictive; PERMISSIVE_UNVERIFIED = indexed text permissive, primary unread; UPSTREAM_UNRESOLVED = wrapper licence read,
# upstream rights open; UNREVIEWED = nothing read.
EVIDENCE = {"Kalshi": "PROHIBITED", "football-data.co.uk": "PROHIBITED", "ESPN": "RESTRICTIVE", "MLBAM": "RESTRICTIVE",
            "NHL": "RESTRICTIVE", "CFBD": "PERMISSIVE_UNVERIFIED", "nflverse": "UPSTREAM_UNRESOLVED"}
EV_ORDER = ["UNREVIEWED", "PERMISSIVE_UNVERIFIED", "UPSTREAM_UNRESOLVED", "RESTRICTIVE", "PROHIBITED"]
def ev_rank(bs): return max((EV_ORDER.index(EVIDENCE.get(b, "UNREVIEWED")) for b in bs), default=-1)
# Known open-licence split routes not modelled as datasets in map.json (documentation only; not in the catalog or registry).
SPLIT_ROUTES = {"soc.fixtures_intl": "openfootball/worldcup (CC0 1.0, LICENSE.md read verbatim 2026-11-13) for World Cup "
                                     "tournaments only; needs a catalog split, a registry entry for that repo, and a clone",
                "ten.rankings_history": "Sackmann tennis_atp/tennis_wta ranking files (registry sackmann_tennis, CC BY-NC-SA) "
                                        "could replace the tennis_official co-source; ranking files not verified in the archive"}
def caveats(i):
    c = []
    if inp[i].get("vstatus") == "DOWNGRADED_BY_VERIFIER" or inp[i].get("bucket") == "FAILED":
        c.append("previous build downgraded by verifier (bucket FAILED)")
    if inp[i].get("bucket") == "REQUIRES_COLLECTION" and inp[i].get("audit_status") == "DATA_IN_HAND":
        c.append("map bucket says REQUIRES_COLLECTION while audit says DATA_IN_HAND: reconcile before building")
    if not inp[i].get("built"): c.append("builder not written; blind verification pending")
    if inp[i]["rights"].get("tier") == "CLEARED_NONCOMMERCIAL_RESEARCH": c.append("non-commercial research only (CC BY-NC-SA)")
    return c
for r in ranked:
    r["build_caveats"] = caveats(r["input"])
    r["blocker_evidence"] = {b: EVIDENCE.get(b, "UNREVIEWED") for b in r["rights_blockers_of_best_path"]}
    r["split_routes"] = {n["dataset"]: SPLIT_ROUTES[n["dataset"]] for n in r["needs"] if n["dataset"] in SPLIT_ROUTES}
    for n in r["needs"]:  # also look at every option per need for split routes
        for d in cands(r["input"], n["need"], False):
            if d in SPLIT_ROUTES: r["split_routes"][d] = SPLIT_ROUTES[d]
ranked.sort(key=lambda r: (TIER_ORDER.index(r["tier"]), r["n_blocking_providers"], ev_rank(r["rights_blockers_of_best_path"]),
                           not r["pit_supported_by_best_datasets"], -len(r["split_routes"]),
                           len([c for c in r["build_caveats"] if "verifier" in c or "reconcile" in c]),
                           -r["missing_primary_slots"], r["input"]))
tier_counts = dict(collections.Counter(r["tier"] for r in ranked))
# First 10 zero-cost inputs: build-ready first; any remaining places go to near misses (single, non-PROHIBITED/RESTRICTIVE
# blocker, zero cost incl. key-needed, PIT-supported), which are labelled NOT build-ready.
ready = [r for r in ranked if r["tier"].startswith("BUILD_READY")]
near = [r for r in ranked if r["tier"] == "RIGHTS_BLOCKED" and r["n_blocking_providers"] == 1
        and ev_rank(r["rights_blockers_of_best_path"]) <= EV_ORDER.index("PERMISSIVE_UNVERIFIED")
        and all(n["cost"] in ("free", "free (key needed)") for n in r["needs"]) and r["pit_supported_by_best_datasets"]]
near.sort(key=lambda r: (-len(r["split_routes"]), all(n["cost"] == "free" for n in r["needs"]) is False, -r["missing_primary_slots"], r["input"]))
first10 = [dict(r, rank=k + 1, build_ready=r["tier"].startswith("BUILD_READY")) for k, r in enumerate((ready + near)[:10])]

res = {
    "source": "map.json @ 88b0a77", "revision": 2,
    "rights_group_datasets": len(q), "distinct_missing_primary_slots": len(all_slots),
    "distinct_missing_primary_slots_all_queue_groups": len(all_queue_slots),
    "pit_strict_rule": ("slot category != PROSPECTIVE AND input pit_verdict PIT_SAFE AND every need is met by a usable dataset "
                        "whose edge pit for that exact (dataset, input, need) is EVENT_TIME/PIT_NATIVE/STATIC"),
    "candidate_rule": "need met by any SATISFIED_BY or CANDIDATE_ALTERNATIVE dataset that passes the same rights + access gate",
    "dataset_blockers": ds_block,
    "need_level_baseline_complete": {k: len(v) for k, v in base_v2.items()},
    "need_level_joint_top8": joint_v2,
    "need_level_greedy_rights_only": greedy(False),
    "before_after": {
        "rev1_satisfied_by_only": {"baseline": {k: len(v) for k, v in base_v1.items()}, "joint_top8": joint_v1,
                                    "per_provider": {p: tab_v1[p] for p in ALLP if any(tab_v1[p].values())},
                                    "greedy": greedy(True)},
        "rev2_with_candidate_alternatives": {"baseline": {k: len(v) for k, v in base_v2.items()}, "joint_top8": joint_v2,
                                              "per_provider": {p: tab_v2[p] for p in ALLP if any(tab_v2[p].values())}},
        "pit_rule_change_joint_top8": pit_downgrades,
    },
    "candidate_alternatives": {
        "needs_with_alternatives": sum(1 for i in CA for v in CA[i].values() if v),
        "alternative_edges": sum(len(v) for i in CA for v in CA[i].values()),
        "free_alternative_edges_any_rights": len(free_alt_edges_any),
        "free_alternative_edges_cleared_today": len(free_alt_edges),
        "free_alternative_datasets_cleared_today": sorted({d for d, _, _ in free_alt_edges}),
        "needs_rescued_by_alternative_under_top8": dict(alt_rescues.most_common()),
    },
    "build_ready_today": build,
    "input_readiness_tiers": tier_counts,
    "first_10_zero_cost_inputs": first10,
    "build_ready_input_count": len(ready), "near_miss_candidates": len(near),
    "providers": out,
}
OUT = pathlib.Path(__file__).parent / "priority_recalc.json"
def render(): return json.dumps(res, indent=1, sort_keys=True)

if __name__ == "__main__":
    OUT.write_text(render())
    print(len(q), "rights datasets;", len(all_slots), "missing PRIMARY slots (rights group);", len(all_queue_slots), "(all queue groups)")
    print("joint top8  rev1:", joint_v1, "\n            rev2:", joint_v2)
    print("PIT rule change (joint top8):", pit_downgrades)
    print("build-ready today:", build)
    print("input readiness tiers:", tier_counts)
    hdr = KEYS + ["exclusive_to_provider"]
    print("provider".ljust(22), " ".join(h[:11].rjust(11) for h in hdr), "   (rev1 rights_only)")
    for p, v in sorted(tab_v2.items(), key=lambda kv: -kv[1]["need_level_rights_only"]):
        if v["need_level_rights_only"] or tab_v1[p]["need_level_rights_only"]:
            print(p.ljust(22), " ".join(str(v["need_level_" + h]).rjust(11) for h in hdr), "  ", tab_v1[p]["need_level_rights_only"])
    print("greedy rev2:", res["need_level_greedy_rights_only"])
    print("build-ready inputs:", len(ready), "near misses:", len(near))
    for r in first10:
        print(r["rank"], r["tier"], r["input"], r["missing_primary_slots"], r["input_pit_verdict"], r["pit_supported_by_best_datasets"],
              r["blocker_evidence"], [(n["need"], n["dataset"], n["access"], n["cost"]) for n in r["needs"]], r["build_caveats"], list(r["split_routes"]))
