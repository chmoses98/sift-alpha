"""Provider priority recalculation over DISTINCT missing PRIMARY slots (RESEARCH_ONLY, read-only).

Reads only research/input_research/market_input_map/map.json (Phase 14 @ 88b0a77).
No network, no collection, no registry change. Output: priority_recalc.json next to this file.
A slot = (archetype, input) pair, as listed in the acquisition queue's `slots`.
"""
import json, collections, pathlib, sys

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

cat = {(e[0], e[1]): e[5] for e in M["edges"] if e[2] == "primary"}
dpit = {(e[0], e[1]): e[5] for e in M["dataset_edges"]}
inp = M["inputs"]
STRICT_PIT_DS = {"EVENT_TIME", "PIT_NATIVE", "STATIC"}

q = [e for e in M["queue"] if e["action_group"] == "RIGHTS_APPROVAL_NEEDED"]
all_slots = {tuple(s) for e in q for s in e["slots"]}
ds_block = {}
for e in q:
    d = e["dataset"]
    ds_block[d] = sorted({prov(s) for s in M["datasets"][d]["sources"] if not cleared(s)})

def slot_flags(d, slot):
    a, i = slot
    ds = M["datasets"][d]
    archived = ds["access_status"] == "COLLECTED_ARCHIVE"
    reachable = ds["access_status"] in ("FREE_REACHABLE", "COLLECTED_ARCHIVE")
    c = cat.get(slot)
    pit_ok = (c != "PROSPECTIVE" and inp.get(i, {}).get("pit_verdict") == "PIT_SAFE"
              and dpit.get((d, i)) in STRICT_PIT_DS)
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
                alone[s] = tuple(x or y for x, y in zip(prev, f))  # best dataset per slot
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

# ---- need-level completeness (stricter): an input is complete only when EVERY data need it has in the map
# (dataset_edges SATISFIED_BY, grouped by `need`) has at least one usable dataset. A dataset is usable under a
# hypothetical clearance set P when all its non-cleared providers are in P and its access state passes the tier gate.
NEEDS = collections.defaultdict(lambda: collections.defaultdict(set))
for d, i, et, need, *_ in M["dataset_edges"]:
    if et == "SATISFIED_BY": NEEDS[i][need].add(d)
def blk(d): return {prov(s) for s in M["datasets"][d]["sources"] if not cleared(s)}
GATES = {
    "rights_only": lambda d: M["datasets"][d]["access_status"] not in ("PROSPECTIVE_CAPTURE_ONLY", "NO_FREE_SOURCE", "PAID_ONLY", "SAMPLE_ONLY"),
    "reachable_or_archived": lambda d: M["datasets"][d]["access_status"] in ("FREE_REACHABLE", "COLLECTED_ARCHIVE"),
    "archived_only": lambda d: M["datasets"][d]["access_status"] == "COLLECTED_ARCHIVE",
}
def complete(i, P, gate):
    return bool(NEEDS[i]) and all(any(blk(d) <= P and gate(d) for d in ds) for ds in NEEDS[i].values())
base = {k: {s for s in all_slots if complete(s[1], set(), g)} for k, g in GATES.items()}
need_sets = {}
for p in out:
    for k, g in GATES.items():
        need_sets[(p, k)] = {s for s in all_slots if complete(s[1], {p}, g)} - base[k]
for p in out:
    nl = need_sets[(p, "rights_only")]
    others = set().union(*[need_sets[(q2, "rights_only")] for q2 in out if q2 != p])
    out[p].update({
        "need_level_rights_only": len(nl),
        "need_level_exclusive_to_provider": len(nl - others),
        "need_level_reachable_or_archived": len(need_sets[(p, "reachable_or_archived")]),
        "need_level_archived_zero_collection": len(need_sets[(p, "archived_only")]),
        "need_level_archived_and_pit_strict": sum(1 for s in need_sets[(p, "archived_only")]
            if cat.get(s) != "PROSPECTIVE" and inp.get(s[1], {}).get("pit_verdict") == "PIT_SAFE"),
        "need_level_reachable_and_pit_strict": sum(1 for s in need_sets[(p, "reachable_or_archived")]
            if cat.get(s) != "PROSPECTIVE" and inp.get(s[1], {}).get("pit_verdict") == "PIT_SAFE"),
    })
TOP8 = ["ESPN", "nflverse", "MLBAM", "NHL", "football-data.co.uk", "CFBD", "Kalshi", "football-data.org"]
joint = {k: len({s for s in all_slots if complete(s[1], set(TOP8), g)} - base[k]) for k, g in GATES.items()}

# greedy need-level (rights_only gate): which providers, cleared together, complete the most slots
ALLP = sorted({prov(x) for d in M["datasets"] for x in M["datasets"][d]["sources"] if not cleared(x)})
g_cleared, g_done, need_greedy = set(), set(), []
g_gate = GATES["rights_only"]
for _ in range(12):
    best, bgain = None, set()
    for p in ALLP:
        if p in g_cleared: continue
        gain = {s for s in all_slots if complete(s[1], g_cleared | {p}, g_gate)} - g_done - base["rights_only"]
        if len(gain) > len(bgain): best, bgain = p, gain
    if not best: break
    g_cleared.add(best); g_done |= bgain
    need_greedy.append({"provider": best, "marginal": len(bgain), "cumulative": len(g_done)})

# greedy cumulative by hypothetical unlock (datasets count only when ALL their blockers are cleared)
remaining, cleared_p, cum, order = set(out), set(), set(), []
while remaining:
    best = max(sorted(remaining), key=lambda p: len({tuple(s) for e in q if set(ds_block[e["dataset"]]) <= cleared_p | {p}
                                                     for s in e["slots"]} - cum))
    gain = {tuple(s) for e in q if set(ds_block[e["dataset"]]) <= cleared_p | {best} for s in e["slots"]} - cum
    if not gain: break
    cleared_p.add(best); cum |= gain; remaining.discard(best)
    order.append({"provider": best, "marginal": len(gain), "cumulative": len(cum)})

res = {"source": "map.json @ 88b0a77", "rights_group_datasets": len(q), "distinct_missing_primary_slots": len(all_slots),
       "pit_strict_rule": "input pit_verdict PIT_SAFE AND dataset-edge pit in EVENT_TIME/PIT_NATIVE/STATIC AND slot category != PROSPECTIVE",
       "dataset_blockers": ds_block, "need_level_baseline_complete": {k: len(v) for k, v in base.items()},
       "need_level_joint_top8": joint, "need_level_greedy_rights_only": need_greedy, "providers": out, "greedy": order}
(pathlib.Path(__file__).parent / "priority_recalc.json").write_text(json.dumps(res, indent=1, sort_keys=True))
rows = sorted(out.items(), key=lambda kv: (-kv[1]["need_level_rights_only"], -kv[1]["unlock_alone_hypothetical"]))
print(len(q), len(all_slots), "baseline", res["need_level_baseline_complete"], "joint top8", joint)
hdr = ["slots_touched", "unlock_alone_hypothetical", "alone_archived", "alone_reachable_not_archived", "alone_collection_required",
       "alone_archived_and_pit_strict", "need_level_rights_only", "need_level_exclusive_to_provider", "need_level_reachable_or_archived",
       "need_level_archived_zero_collection", "need_level_archived_and_pit_strict", "need_level_reachable_and_pit_strict"]
print("provider".ljust(20), " ".join(h[:9].rjust(9) for h in hdr))
for p, v in rows:
    if v["unlock_alone_hypothetical"] or v["need_level_rights_only"]:
        print(p.ljust(20), " ".join(str(v[h]).rjust(9) for h in hdr))
for o in order[:10]: print(o)
print("need-level greedy:"); [print(o) for o in need_greedy]
