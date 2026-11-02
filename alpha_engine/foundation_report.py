"""Build input_registry.json, collection_status.json and collection_gap_report.json from the master inventory,
the input catalog, curated evidence and static code evidence. Usage: python -m alpha_engine.foundation_report"""
import json, re, collections
from datetime import datetime, timezone
from pathlib import Path
from .audit_schema import SCHEMA_VERSION
from .input_catalog import INPUTS, BP, COMMON, COMMON_BP, LADDER_BP
from .collection_curated import CUR
from .master_inventory import AUDIT, SPORTS, REPO

VCLASS = {"PIT_ARCHIVED": "VERIFIED_COLLECTION", "DERIVED": "DERIVED", "COLLECTED_NOT_PIT_ARCHIVED": "COLLECTED_UNVERIFIED_PIT", "PARTIAL_OR_STALE": "STALE_OR_PARTIAL",
          "SOURCE_AVAILABLE_NOT_COLLECTED": "MISSING", "NO_RELIABLE_SOURCE": "MISSING", "CODE_REFERENCE_ONLY": "CODE_REFERENCE_ONLY", "NO_REFERENCE_FOUND": "UNKNOWN", "UNKNOWN": "UNKNOWN"}
TIER = {"E": "ESSENTIAL", "C": "CONTEXTUAL", "X": "EXPLORATORY"}
RANK = {"E": 3, "C": 2, "X": 1}
SEV = {"SOURCE_AVAILABLE_NOT_COLLECTED": 5, "NO_REFERENCE_FOUND": 4, "PARTIAL_OR_STALE": 4, "COLLECTED_NOT_PIT_ARCHIVED": 3,
       "CODE_REFERENCE_ONLY": 2, "NO_RELIABLE_SOURCE": 2, "UNKNOWN": 2, "PIT_ARCHIVED": 0, "DERIVED": 0}


def parse(t):
    return {l.split("|")[0]: {"label": l.split("|")[1], "category": l.split("|")[2]} for l in t.splitlines()}


def bp_keys(sport, native, kind, periods):
    n = native.lower(); keys = []
    if kind in ("winner", "spread", "margin_bucket", "exact_score"): keys.append("game_side")
    if kind in ("total", "team_total", "btts", "exact_score"): keys.append("game_total")
    if kind in ("winner", "spread", "total", "team_total", "period_result") and any(p != "FULL" for p in periods):
        keys.append("period")
        if "game_side" not in keys and kind in ("winner", "spread"): keys.append("game_side")
        if "game_total" not in keys and kind in ("total", "team_total"): keys.append("game_total")
    if kind == "period_result": keys += ["period", "game_side", "game_total"]
    if kind == "player_stat":
        m = {"NFL": [("player_pass", r"pass|attempt|complet|int"), ("player_rush", r"rush|carr"), ("player_rec", r"rec|target"), ("player_td", r"td|touch")],
             "NBA": [("player_pts", r"point|pts"), ("player_reb", r"reb"), ("player_ast", r"ast|assist")],
             "NHL": [("player_shots", r"shot"), ("player_points", r"point|goal|assist"), ("goalie_saves", r"save|goalie")],
             "MLB": [("player_hit", r"hitter"), ("player_pitch", r"pitcher")]}.get(sport, [])
        keys += [k for k, rx in m if re.search(rx, n)] or ["player_other"]
    if kind in ("player_scorer", "player_h2h"): keys.append("player_td" if sport in ("NFL", "CFB") and kind == "player_scorer" and "player_td" in BP[sport] else "player_other")
    if kind == "first_event": keys.append("first_event")
    if kind in ("overtime", "team_stat", "game_stat"): keys.append("game_event")
    for k in ("lineup_role", "combo", "off_field", "season_outcome", "season_stat", "season_award"):
        if kind == k: keys.append(k)
    return [k for k in dict.fromkeys(keys) if k in BP[sport]]


def expand(sport, keys, ladder):
    best = {}
    for k in keys:
        for tok in BP[sport][k].split():
            i, t = tok.rsplit(":", 1)
            if RANK[t] > RANK.get(best.get(i, "X"), 0) if i in best else True: best[i] = t
    for tok in (COMMON_BP + (" " + LADDER_BP if ladder else "")).split():
        i, t = tok.rsplit(":", 1); best.setdefault(i, t)
    return best


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    master = json.loads((AUDIT / "master_inventory.json").read_text())
    ce = json.loads((AUDIT / "code_evidence.json").read_text())
    arch = json.loads((AUDIT / "snapshots" / "archive_trees.json").read_text())
    reg = {"schema_version": SCHEMA_VERSION, "generated_utc": now,
           "note": "Candidate inputs are hypotheses. Tier = ESSENTIAL/CONTEXTUAL/EXPLORATORY relevance, not validated predictive value.",
           "common_inputs": parse(COMMON), "sports": {}}
    cs = {"schema_version": SCHEMA_VERSION, "generated_utc": now, "sports": {}}
    for sp in SPORTS:
        inputs = parse(INPUTS[sp]); allin = {**inputs, **reg["common_inputs"]}
        fams = {}
        for f in master["families"]:
            if f["sport"] != sp: continue
            keys = bp_keys(sp, f["native_family"], f["canonical"]["kind"], f["canonical"]["periods"])
            ladder = f["canonical"]["kind"] in ("spread", "total", "team_total", "player_stat", "period_result", "season_outcome")
            fams[f["id"]] = {"blueprints": keys, "inputs": expand(sp, keys, ladder) if keys else {i: t for i, t in (tok.rsplit(":", 1) for tok in COMMON_BP.split())}}
        reg["sports"][sp] = {"inputs": inputs, "families": fams}
        # collection status
        ev = ce["sports"][sp]; rows = {}
        for iid, meta in allin.items():
            cur = CUR[sp].get(iid) or CUR[sp].get(iid)
            code = ev["inputs"][iid]
            if cur:
                coll, use, note, evid = cur
            elif meta["category"] == "distribution":
                coll, use, note, evid = "DERIVED", "UNKNOWN", "derived from archived results/prices; model implementation not verified in this pass", []
            else:
                coll = "CODE_REFERENCE_ONLY" if code["collect_files"] else ("NO_REFERENCE_FOUND" if not code["files_total"] else "CODE_REFERENCE_ONLY")
                use, note, evid = "UNKNOWN", ("keyword hits only in " + ("collection" if code["collect_files"] else "non-collection") + " code; archival and correct use unverified") if code["files_total"] else "no code reference matched the recorded regex", []
            rows[iid] = {"label": meta["label"], "collection": coll, "verification_class": VCLASS[coll], "model_use": use, "curated": bool(cur), "note": note, "evidence": evid,
                         "code": {"regex": code["regex"], "collect_files": code["collect_files"], "model_files": code["model_files"], "examples": code["collect_examples"] + code["model_examples"][:2]}}
        cs["sports"][sp] = {"repo": ev["repo"], "commit": ev["commit"], "inputs": rows,
                            "archives": [{"key": k, "repo": v.get("repo"), "branch": v.get("branch"), "commit": v.get("commit"), "total_files": v.get("total_files")} for k, v in arch.items() if k.split(":")[0].lower().startswith(REPO[sp].lower().split("-")[0])]}
    # gap report
    gap = {"schema_version": SCHEMA_VERSION, "generated_utc": now, "method": "score = (severity + 1 if essential input is collected-but-unused/not collected) x share of the sport's own observed markets in families where the input is ESSENTIAL; shares are within-sport so sports with different denominators are comparable, raw counts are never summed across sports", "sports": {}, "cross_sport": []}
    for sp in SPORTS:
        mk = {f["id"]: ((f["observed"]["markets_now"] or 0) or (f.get("markets_prior_snapshot") or f.get("markets_prior_registry_snapshot") or f.get("markets_historical_archived_tier") or 0)) for f in master["families"] if f["sport"] == sp}
        agg = collections.defaultdict(lambda: {"fams": 0, "markets": 0})
        for fid, fr in reg["sports"][sp]["families"].items():
            for iid, t in fr["inputs"].items():
                if t == "E": agg[iid]["fams"] += 1; agg[iid]["markets"] += mk.get(fid, 0)
        rows = []; tot = max(1, sum(mk.values()))
        for iid, a in agg.items():
            r = cs["sports"][sp]["inputs"][iid]
            sev = SEV.get(r["collection"], 2)
            use_gap = r["model_use"] in ("COLLECTED_UNUSED", "NOT_COLLECTED") and r["collection"] not in ("DERIVED",)
            if sev == 0 and not use_gap: continue
            rows.append({"input": iid, "label": r["label"], "collection": r["collection"], "model_use": r["model_use"], "essential_for_families": a["fams"], "essential_markets": a["markets"],
                         "severity": sev, "share_of_sport_markets": round(a["markets"] / tot, 4), "score": round((sev + (1 if use_gap else 0)) * a["markets"] / tot, 4), "note": r["note"], "curated": r["curated"]})
        rows.sort(key=lambda r: -r["score"])
        cnt = collections.Counter(r["collection"] for r in cs["sports"][sp]["inputs"].values())
        vcnt = collections.Counter(r["verification_class"] for r in cs["sports"][sp]["inputs"].values())
        gap["sports"][sp] = {"status_counts": dict(cnt), "verification_counts": dict(vcnt), "top_gaps": rows[:15], "curated_inputs": sum(r["curated"] for r in cs["sports"][sp]["inputs"].values()), "inputs": len(cs["sports"][sp]["inputs"])}
        for r in rows[:5]: gap["cross_sport"].append({"sport": sp, **{k: r[k] for k in ("input", "collection", "model_use", "essential_markets", "share_of_sport_markets", "score", "note")}})
    gap["cross_sport"].sort(key=lambda r: -r["score"])
    for n, o in (("input_registry", reg), ("collection_status", cs), ("collection_gap_report", gap)):
        (AUDIT / f"{n}.json").write_text(json.dumps(o, indent=1))
    for sp in SPORTS: print(sp, gap["sports"][sp]["status_counts"], "curated", gap["sports"][sp]["curated_inputs"], "/", gap["sports"][sp]["inputs"])


if __name__ == "__main__":
    main()
