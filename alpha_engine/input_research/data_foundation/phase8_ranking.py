"""Phase 8 ranking and accounting (RESEARCH_ONLY): which unbuilt inputs would unlock the most PRIMARY-role market slots, and what this phase unlocked.

    python -m alpha_engine.input_research.data_foundation.phase8_ranking [--baseline-ref be3c9f1]

Ranking keys (in order): unique missing PRIMARY slots the input would unlock (an archetype counts once per input), number of distinct archetypes it appears in (reuse), source rights (free source and low tos_risk first), then slot total.
Effort is NOT scored automatically: the audit has no reliable effort field, so the written report states effort per top candidate. Market-derived benchmark inputs are excluded. Writes market_completeness/phase8_ranking.json.
"""
from __future__ import annotations

import collections
import json
import sys

from . import market_completeness as M

OUT = M.OUT


def slots(status: dict, audit: dict) -> dict:
    """(sport, archetype, input) -> (role, category) for every non-market-excluded slot."""
    out = {}
    for a in M.archetypes():
        for iid, role in a["inputs"]:
            k = f"{a['sport']}:{iid}"
            if k not in status: continue
            c = M.category(status[k], (audit.get(k) or {}).get("full_definition_status"))
            if c != "EXCLUDED_MARKET": out[(a["sport"], a["name"], iid)] = (role, c)
    return out


def main(argv=None) -> int:
    a = argv if argv is not None else sys.argv[1:]; ref = a[a.index("--baseline-ref") + 1] if "--baseline-ref" in a else "be3c9f1"
    audit = {r["key"]: r for r in json.loads((M.DF / "input_audit.json").read_text())["rows"]}
    now, base = slots(M.load_status(None), audit), slots(M.load_status(ref), audit)
    built = lambda c: c in M.COVERED
    unlocked = [(k, now[k]) for k in now if k in base and now[k][0] == "primary" and built(now[k][1]) and not built(base[k][1])]
    by_sport = collections.Counter(k[0] for k, _ in unlocked); by_input = collections.defaultdict(list)
    for (sp, arch, iid), _ in unlocked: by_input[(sp, iid)].append(arch)
    uniq_inputs = collections.Counter(sp for sp, _ in by_input)
    cand = collections.defaultdict(list)
    for (sp, arch, iid), (role, c) in now.items():
        if role == "primary" and not built(c): cand[(sp, iid)].append((arch, c))
    rows = []
    for (sp, iid), v in cand.items():
        au = audit[f"{sp}:{iid}"]; cats = collections.Counter(c for _, c in v)
        rows.append({"sport": sp, "input": iid, "primary_slots_unlocked": len(v), "archetypes": len({x for x, _ in v}), "category": cats.most_common(1)[0][0], "bucket": au["bucket"], "status": au["status"], "cost": au["cost"], "tos_risk": au["tos_risk"],
                     "is_rules_text": iid == "m.rules_text"})
    rows.sort(key=lambda r: (-r["primary_slots_unlocked"], -r["archetypes"], r["tos_risk"] != "low", r["input"]))
    res = {"schema": "phase8-ranking-1.0", "status": "RESEARCH_ONLY", "baseline_ref": ref,
           "unlocked_primary_slots_total": len(unlocked), "unlocked_primary_slots_by_sport": dict(by_sport), "unique_inputs_with_primary_unlock_by_sport": dict(uniq_inputs),
           "unlocked_by_input": {f"{sp}:{iid}": sorted(v) for (sp, iid), v in sorted(by_input.items())},
           "top_unbuilt_by_primary_slots": rows[:60]}
    (OUT / "phase8_ranking.json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: res[k] for k in ("unlocked_primary_slots_total", "unlocked_primary_slots_by_sport", "unique_inputs_with_primary_unlock_by_sport")}, indent=1)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
