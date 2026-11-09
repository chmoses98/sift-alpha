"""Assemble the dashboard artifacts: catalog (hypotheses) x availability audit (verification engine) x tested evidence (research paths).

Outputs (research/audit/input_research/):
  index.json            sports -> families -> evidence level, counts, vintage (small; always loaded)
  sport_<SPORT>.json    per-sport detail: archetype/blueprint inputs with rationale, availability, model use, evidence; family map
  queue.json            ranked research questions (what to investigate next) + what is running now
Nothing here promotes a finding: every evidence record carries its own verdict, and untested inputs are labelled UNTESTED.

Evidence levels (strict ladder; a family sits at the highest level actually achieved):
  L0_INVENTORY_ONLY       hypotheses + availability audit only; no predictive test has been run
  L1_TESTED_VS_BASELINE   walk-forward test vs a no-market baseline (a research lead, not an edge)
  L2_TESTED_VS_MARKET     walk-forward test vs a contemporaneous near-close market line/price (sportsbook line or Kalshi)
  L3_TESTED_VS_KALSHI     as L2 against timestamped Kalshi executable prices incl. spread/fees/depth        (achieved nowhere yet)
  L4_PROSPECTIVELY_CONFIRMED  pre-registered, forward, out-of-sample, survives multiple-comparison control   (achieved nowhere yet)
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from . import catalog as C

ROOT = C.ROOT
OUT = ROOT / "research/audit/input_research"
VER = ROOT / "research/audit/verification"
LEVELS = ["L0_INVENTORY_ONLY", "L1_TESTED_VS_BASELINE", "L2_TESTED_VS_MARKET", "L3_TESTED_VS_KALSHI", "L4_PROSPECTIVELY_CONFIRMED"]
COLLECTION_RANK = ["PIT_ARCHIVED", "COLLECTED_NOT_PIT_ARCHIVED", "PARTIAL_OR_STALE", "DERIVED", "SOURCE_AVAILABLE_NOT_COLLECTED", "CODE_REFERENCE_ONLY", "NO_REFERENCE_FOUND", "UNKNOWN"]
TIER_SENT = {"E": "essential", "C": "contextual", "X": "exploratory"}


def _r(x, nd=5):
    """Round floats to significant digits recursively (keeps dashboard JSON small and diffs stable)."""
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            return None
        if x == 0:
            return 0.0
        return round(x, max(nd - int(math.floor(math.log10(abs(x)))) - 1, 0)) if abs(x) < 1e4 else round(x, 1)
    if isinstance(x, dict):
        return {str(k): _r(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_r(v, nd) for v in x]
    try:
        import numpy as np
        if isinstance(x, np.generic):
            return _r(x.item(), nd)
    except Exception:
        pass
    return x


# ------------------------------------------------------------------------------------------------------------- availability
def load_verification() -> dict:
    return {"inputs": json.loads((VER / "inputs.json").read_text())["inputs"], "families": json.loads((VER / "families.json").read_text())["families"],
            "summary": json.loads((VER / "summary.json").read_text())}


def registry_status(sport: str, rid: str, ver: dict) -> dict:
    key = f"{sport}:{rid}" if not rid.startswith("m.") else f"{sport}:{rid}"
    rec = ver["inputs"].get(key)
    if rec is None:
        return {"registry_id": rid, "collection": "NOT_IN_VERIFICATION", "model_use": "UNKNOWN"}
    return {"registry_id": rid, "status": rec.get("status") or rec.get("first_failure", {}).get("state"), "collection": rec.get("collection"), "model_use": rec.get("model_use"),
            "first_failure": (rec.get("first_failure") or {}).get("why"), "note": (rec.get("note") or "")[:300], "derived": rec.get("derived"),
            "output_visible": (rec.get("output_visibility") or {}).get("visible_in_output")}


def availability(sport: str, cat: dict, ver: dict, research: dict | None, iid: str | None = None, registry_ids: set | None = None) -> dict:
    """Availability of ONE catalog input.

    Only an EXACT registry match (catalog id == registry id) inherits the registry's collection / model-use evidence. A new candidate that merely maps to related
    registry inputs is NOT_IN_REGISTRY: the related records are shown as context and never counted as collected or used.
    """
    exact = registry_ids is None or iid in registry_ids
    regs = [registry_status(sport, r, ver) for r in cat.get("registry_ids", [])]
    out = {"pregame_knowable": cat["pregame_knowable"], "free_sources": cat["free_sources"], "exact_registry_match": exact}
    out["registry" if exact else "related_registry_context"] = regs
    best = None
    for r in (regs if exact else []):
        c = r.get("collection", "UNKNOWN")
        if c in COLLECTION_RANK and (best is None or COLLECTION_RANK.index(c) < COLLECTION_RANK.index(best)):
            best = c
    if not exact:
        out.setdefault("registry", [])
    if research:
        out["research_path"] = research
        out["overall"] = "COMPUTED_IN_RESEARCH_PATH"
        out["overall_note"] = ("Alpha computed this input for the research path from free nflverse data using only information available before kickoff; "
                               "that is NOT the same as the live model collecting it.")
    elif best:
        out["overall"] = best
    elif cat["free_sources"] == ["NONE_FOUND"]:
        out["overall"] = "NO_FREE_SOURCE_FOUND"
    else:
        out["overall"] = "NOT_IN_REGISTRY"
    uses = {r.get("model_use") for r in (regs if exact else [])}
    if "USED" in uses:
        out["model_use"] = "USED"
    elif "USED_PARTIAL" in uses:
        out["model_use"] = "USED_PARTIAL"
    elif uses == {"NOT_COLLECTED"} or uses == {"NOT_COLLECTED", "UNKNOWN"}:
        out["model_use"] = "NOT_USED (not collected)"
    elif uses and uses != {"UNKNOWN"}:
        out["model_use"] = "/".join(sorted(u for u in uses if u))
    elif not exact:
        out["model_use"] = "UNKNOWN (new candidate input, not itself in the registry; no model-use evidence)"
    else:
        out["model_use"] = "UNKNOWN (no recorded model-use evidence)"
    return out


# ------------------------------------------------------------------------------------------------------------- path evidence
def compact_continuous(res: dict, feature_meta: dict, labels: dict, links_fn, benchmark_names: dict, pit_partial: set) -> dict:
    inputs = {}
    group_of = {c: g for g, cols in res["group_members"].items() for c in cols}
    imp = res.get("importance", {})
    for c, v in res["inputs"].items():
        inc = v["gain_vs_B1"]
        w = v.get("weight", {})
        reliable = bool(w.get("ci_excludes_zero")) and v["verdict"] in ("DEMONSTRATED_INCREMENTAL", "SUGGESTIVE_UNCONFIRMED")
        inputs[c] = {"label": labels.get(c, c), "group": group_of.get(c), "catalog_ids": links_fn(c), "pit": "partial" if c in pit_partial else "yes",
                     "coverage": v["coverage"], "coverage_test": v["coverage_test"],
                     "incremental": {"mse_gain_vs_baseline": inc["mean"], "pct_of_baseline_mse": v["pct_of_base_mse"], "ci95": inc["ci_0.05"], "p": inc["p"], "q_bh": v["q_bh"], "holm_p": v["holm_p"],
                                     "seasons_positive": inc["seasons_positive"], "seasons_total": inc["seasons_total"], "verdict": v["verdict"]},
                     "corr_with_residual": v["corr_with_market_residual"], "sign_consistency": v["sign_consistency"], "season_corrs": v["season_corrs"],
                     "weight": {"per_sd": w.get("per_sd"), "ci95": w.get("ci95"), "per_unit": w.get("per_unit"), "ci_excludes_zero": w.get("ci_excludes_zero"), "unit": w.get("unit"),
                                "model": w.get("model"), "reliable": reliable,
                                "caveat": ("Descriptive ridge coefficient on the benchmark residual, conditional on the other inputs and fit on all history (including test seasons)."
                                           + ("" if reliable else " NOT a demonstrated effect: the incremental test did not clear the bar, so treat the sign and size as noise."))},
                     "permutation_importance": imp.get(c, {}).get("perm_mse_increase_mean"), "permutation_seasons_positive": imp.get(c, {}).get("seasons_positive"),
                     "partial_dependence": imp.get(c, {}).get("pdp")}
    groups = {}
    partial_set = set(res.get("partial_cols", []))
    for g, v in res["groups"].items():
        if g in ("ALL_FEATURES_RIDGE", "ALL_INCL_PARTIAL_RIDGE"):
            continue
        gg = v["gain_vs_B1"]
        entry = {"contains_partial_pit_inputs": any(c in partial_set for c in res["group_members"].get(g, [])), "ci_season_block": gg.get("ci_season_block"),
                 "members": res["group_members"].get(g, []), "mse_gain_vs_baseline": gg["mean"], "pct_of_baseline_mse": v["pct_of_base_mse"], "ci95": gg["ci_0.05"], "holm_p": v["holm_p"],
                 "halves": gg["halves"], "min_leave_one_season_out": min(gg["leave_one_season_out"].values()) if gg["leave_one_season_out"] else None,
                 "seasons_positive": gg["seasons_positive"], "seasons_total": gg["seasons_total"], "verdict": v["verdict"]}
        st = res["standalone"]["groups"].get(g)
        if st:
            entry["standalone_r2"] = st["r2_gain_vs_no_information"]; entry["standalone_r2_ci95"] = st["ci95_r2"]; entry["standalone_q_bh"] = st["q_bh"]
        dr = res["drop_one_group"].get(g)
        if dr:
            entry["necessity_mse_loss_if_removed"] = dr["mse_loss_if_removed"]; entry["necessity_ci95"] = dr["ci95"]; entry["necessity_holm_p"] = dr["holm_p"]
        groups[g] = entry
    ix = {k: {"label": v["label"], "components": v["components"], "hypothesis": v["hypothesis"], "mse_gain_vs_main_effects": v["gain_vs_main_effects"]["mean"], "pit": v.get("pit", "yes"),
              "ci95": v["gain_vs_main_effects"]["ci_0.05"], "holm_p": v["holm_p"], "verdict": v["verdict"]} for k, v in res["interactions"].items()}
    out = {"kind": res["kind"], "n_games_modeled": res["n_games_modeled"], "n_test_rows": res["n_test_games"], "test_seasons": res["test_seasons"], "n_week_clusters": res["n_week_clusters"],
           "benchmark_names": benchmark_names, "baselines": res["baselines"], "headline_models": {"gbm_all": {
               "mse_gain_vs_baseline": res["gbm"]["gain_vs_B1"]["mean"], "ci95": res["gbm"]["gain_vs_B1"]["ci_0.05"], "gain_vs_ridge": res["gbm"]["gain_vs_ridge"]["mean"],
               "gain_vs_ridge_ci95": res["gbm"]["gain_vs_ridge"]["ci_0.05"], "verdict": res["gbm"]["verdict"], "halves": res["gbm"]["gain_vs_B1"]["halves"]}},
           "standalone": {k: v for k, v in res["standalone"].items() if k != "groups"}, "groups": groups, "partial_pit_inputs": sorted(partial_set),
           "interactions": ix, "inputs": inputs}
    if "ALL_FEATURES_RIDGE" in res["groups"]:
        a = res["groups"]["ALL_FEATURES_RIDGE"]
        sens = res["groups"].get("ALL_INCL_PARTIAL_RIDGE")
        out["headline_models"]["sensitivity_incl_partial_inputs"] = ({"ridge": {"mse_gain_vs_baseline": sens["gain_vs_B1"]["mean"], "pct_of_baseline_mse": sens["pct_of_base_mse"], "ci95": sens["gain_vs_B1"]["ci_0.05"],
                                                                              "holm_p": sens["holm_p"], "verdict": sens["verdict"]},
                                                                     "gbm": {"mse_gain_vs_baseline": res["gbm"]["sensitivity_incl_partial"]["mean"], "ci95": res["gbm"]["sensitivity_incl_partial"]["ci_0.05"]},
                                                                     "note": "Adds the realised starting QB and/or observed weather. NOT a pregame claim; shown only to size what partially-knowable inputs would add."} if sens else None)
        out["headline_models"]["ridge_all"] = {"pit_strict": True, "ci_season_block": a["gain_vs_B1"].get("ci_season_block"), "mse_gain_vs_baseline": a["gain_vs_B1"]["mean"], "pct_of_baseline_mse": a["pct_of_base_mse"], "ci95": a["gain_vs_B1"]["ci_0.05"], "holm_p": a["holm_p"],
                                              "halves": a["gain_vs_B1"]["halves"], "per_season": a["gain_vs_B1"]["per_season"], "min_leave_one_season_out": min(a["gain_vs_B1"]["leave_one_season_out"].values()),
                                              "verdict": a["verdict"]}
    if res.get("probability"):
        pr = res["probability"]
        out["probability"] = {"market_price_source": pr["market_price_source"], "n_scored_non_push": pr["n_scored_non_push"], "market_calibration": pr["market_calibration"],
                              "models": {m: {k: pr[m][k] for k in ("logloss_market", "logloss_model", "logloss_gain", "brier_market", "brier_model", "calibration", "calibration_table", "hit_rate_model_side")} for m in ("ridge_all", "gbm_all")}}
    if res.get("latest_season_holdout"):
        out["latest_season_holdout"] = res["latest_season_holdout"]
    return out


def compact_moneyline(res: dict, labels: dict, links_fn, pit_partial: set) -> dict:
    group_of = {c: g for g, cols in res["group_members"].items() for c in cols}
    inputs = {}
    for c, v in res["inputs"].items():
        g = v["gain_vs_recalibrated_market"]
        inputs[c] = {"label": labels.get(c, c), "group": group_of.get(c), "catalog_ids": links_fn(c), "pit": "partial" if c in pit_partial else "yes", "coverage": v["coverage"],
                     "incremental": {"logloss_gain_vs_recalibrated_market": g["mean"], "ci95": g["ci_0.05"], "p": g["p"], "q_bh": v["q_bh"], "holm_p": v["holm_p"], "seasons_positive": g["seasons_positive"],
                                     "seasons_total": g["seasons_total"], "verdict": v["verdict"]}, "corr_with_market_miss": v["corr_with_market_miss"],
                     "weight": {"logit_per_sd": res["weights_logit_per_sd"].get(c), "unit": "log-odds of home win per +1 SD, conditional on the market logit and the other inputs (ridge-penalised logistic)"}}
    groups = {}
    for g, v in res["groups"].items():
        r = v["gain_vs_recalibrated_market"]
        groups[g] = {"members": res["group_members"].get(g, []), "logloss_gain_vs_recalibrated_market": r["mean"], "ci95": r["ci_0.05"], "holm_p": v["holm_p"], "halves": r["halves"],
                     "min_leave_one_season_out": min(r["leave_one_season_out"].values()), "seasons_positive": r["seasons_positive"], "seasons_total": r["seasons_total"], "verdict": v["verdict"]}
    a = res["all_features"]
    return {"kind": "moneyline", "n_games_modeled": res["n_games_modeled"], "n_test_rows": res["n_test_games"], "test_seasons": res["test_seasons"], "n_week_clusters": res["n_week_clusters"],
            "market_price_source": res["market_price_source"], "baselines": res["baselines"],
            "partial_pit_inputs": res["all_features"].get("partial_cols", []),
            "sensitivity_incl_partial_inputs": {"logloss_gain_vs_market": res["sensitivity_incl_partial"]["logloss_gain_vs_market"]["mean"], "ci95": res["sensitivity_incl_partial"]["logloss_gain_vs_market"]["ci_0.05"],
                                                "note": "Adds the realised starting QB and observed weather. NOT a pregame claim."},
            "headline_models": {"logit_all": {"pit_strict": True, "ci_season_block": a["logloss_gain_vs_market"].get("ci_season_block"), "logloss_model": a["logloss_model"], "brier_model": a["brier_model"], "logloss_gain_vs_market": a["logloss_gain_vs_market"]["mean"],
                                              "ci95": a["logloss_gain_vs_market"]["ci_0.05"], "halves": a["logloss_gain_vs_market"]["halves"], "calibration": a["calibration"],
                                              "calibration_table": a["calibration_table"], "per_season": a["logloss_gain_vs_market"]["per_season"],
                                              "verdict": "WORSE_THAN_BASELINE" if a["logloss_gain_vs_market"]["ci_0.05"][1] < 0 else ("SUGGESTIVE_UNCONFIRMED" if a["logloss_gain_vs_market"]["ci_0.05"][0] > 0 else "NOT_DEMONSTRATED")}},
            "groups": groups, "inputs": inputs, "market_slope_and_intercept": res["offset_slope_and_intercept"]}


# ------------------------------------------------------------------------------------------------------------- build
GENERIC_WHY_MARKERS = ("channel through which it moves", "moves the ", " price.", "for the ")


def catalog_quality(cat: dict) -> dict:
    """Disclose how many per-market `why` strings look machine-padded (formulaic tails) instead of market-specific prose."""
    whys = [i["why"] for sec in ("blueprints", "archetypes", "unregistered_archetypes") for rec in cat.get(sec, {}).values() for i in rec["inputs"]]
    tails: dict[str, int] = {}
    for w in whys:
        tails[w[-40:]] = tails.get(w[-40:], 0) + 1
    repeated = sum(n for n in tails.values() if n >= 4)
    padded = sum(1 for w in whys if any(m in w[-70:] for m in GENERIC_WHY_MARKERS) and len(w) < 140)
    return {"market_specific_why_total": len(whys), "formulaic_repeated_tail": repeated, "share_formulaic": round(repeated / max(1, len(whys)), 3),
            "note": "Per-market 'why' text was drafted by an automated pass and some entries are formulaic; input-level mechanism/rationale text is the substantive content. Treat as hypotheses to be reviewed."}


def build_sport(sport: str, paths: dict, ver: dict, vintage: dict) -> dict:
    cat = C.load(sport)
    errs = C.validate(cat, sport)
    if errs:
        raise ValueError(f"{sport} catalog invalid: {errs[:5]}")
    fams_ver = {k: v for k, v in ver["families"].items() if v.get("sport") == sport}
    reg_ids = C.registry_input_ids(sport)
    reg = C.registry_blueprints(sport)
    fam_bp = {f: b for b, fs in reg.items() for f in fs}
    arch_of: dict[str, str] = {}
    archs_of: dict[str, list[str]] = {}
    for a, rec in (cat.get("archetypes") or {}).items():
        for f in rec["families"]:
            archs_of.setdefault(f, []).append(a)
    for f, lst in archs_of.items():
        # default archetype for a family = one that has tested evidence for it, else the first listed
        tested = [a for a in lst if any(f in paths[p]["evidenced_families"] for p in paths if paths[p]["sport"] == sport and paths[p]["archetype"] == a)]
        arch_of[f] = (tested or lst)[0]
    # evidence per catalog input id, from every path whose archetype is attached
    research_cov: dict[str, dict] = {}
    path_for_arch: dict[str, list[str]] = {}
    for pid, p in paths.items():
        if p["sport"] != sport:
            continue
        path_for_arch.setdefault(p["archetype"], []).append(pid)
        for c, rec in p["result"]["inputs"].items():
            for cid in rec["catalog_ids"]:
                d = research_cov.setdefault(cid, {"features": {}, "source": p["data_source"], "latest_game": vintage.get("latest_completed_game"), "retrieved": vintage.get("retrieved_utc")})
                d["features"][f"{pid}:{c}"] = {"coverage": rec.get("coverage"), "pit": rec.get("pit")}

    def input_card(iid: str, role: str | None, why: str | None, arch: str | None):
        c = cat["inputs"][iid]
        av = availability(sport, c, ver, ({"features": research_cov[iid]["features"], "source": research_cov[iid]["source"], "latest_game": research_cov[iid]["latest_game"], "retrieved_utc": research_cov[iid]["retrieved"],
                                           "mean_coverage": round(sum(f["coverage"] or 0 for f in research_cov[iid]["features"].values()) / len(research_cov[iid]["features"]), 3)} if iid in research_cov else None))
        ev = []
        for pid in path_for_arch.get(arch, []):
            for f, rec in paths[pid]["result"]["inputs"].items():
                if iid in rec["catalog_ids"]:
                    inc = rec["incremental"]
                    w = rec.get("weight") or {}
                    ev.append({"path": pid, "feature": f, "label": rec["label"], "verdict": inc["verdict"], "q_bh": inc["q_bh"], "p": inc["p"],
                               "gain": inc.get("pct_of_baseline_mse", inc.get("logloss_gain_vs_recalibrated_market")), "weight_per_sd": w.get("per_sd", w.get("logit_per_sd")),
                               "weight_ci95": w.get("ci95"), "weight_reliable": bool(w.get("reliable")), "weight_model": w.get("model"), "pit": rec["pit"], "coverage": rec["coverage"]})
        return {"id": iid, "role": role, "why": why, "evidence": ev, "tested": bool(ev)}

    def input_def(iid: str) -> dict:
        c = cat["inputs"][iid]
        rc = research_cov.get(iid)
        rp = ({"features": rc["features"], "source": rc["source"], "latest_game": rc["latest_game"], "retrieved_utc": rc["retrieved"],
               "mean_coverage": round(sum(x["coverage"] or 0 for x in rc["features"].values()) / len(rc["features"]), 3)} if rc else None)
        return {"label": c["label"], "category": c["category"], "mechanism": c["mechanism"], "rationale": c["rationale"], "measurement": c["measurement"], "availability": availability(sport, c, ver, rp, iid, reg_ids)}

    archetypes = {}
    for a, rec in (cat.get("archetypes") or {}).items():
        pids = path_for_arch.get(a, [])
        archetypes[a] = {"label": rec["label"], "blueprint": rec["blueprint"], "families": rec["families"], "target": rec["target"], "mechanism": rec["mechanism"],
                         "inputs": [input_card(i["id"], i.get("role"), i.get("why"), a) for i in rec["inputs"]],
                         "interactions": [{"inputs": ix["inputs"], "hypothesis": ix["hypothesis"]} for ix in rec["interactions"]], "blueprint_exclusions": rec.get("blueprint_exclusions") or [], "paths": pids,
                         "level": max([paths[p]["level"] for p in pids], key=LEVELS.index) if pids else LEVELS[0]}
    unregistered = {}
    for a, rec in (cat.get("unregistered_archetypes") or {}).items():
        unregistered[a] = {"label": rec["label"], "blueprint": rec["blueprint"], "contract_types": rec["contract_types"], "target": rec["target"], "mechanism": rec["mechanism"],
                           "inputs": [input_card(i["id"], i.get("role"), i.get("why"), None) for i in rec["inputs"]],
                           "interactions": [{"inputs": ix["inputs"], "hypothesis": ix["hypothesis"]} for ix in rec["interactions"]], "blueprint_exclusions": rec.get("blueprint_exclusions") or [], "level": LEVELS[0]}
    blueprints = {}
    for b, rec in cat["blueprints"].items():
        blueprints[b] = {"mechanism": rec["mechanism"], "target": rec["target"], "families": reg.get(b, []),
                         "inputs": [{"id": i["id"], "why": i["why"], "role": i.get("role")} for i in rec["inputs"]],
                         "interactions": rec["interactions"]}
    families = {}
    all_reg = json.loads(C.REGISTRY.read_text())["sports"][sport]["families"]
    for f in sorted(all_reg):
        bp = fam_bp.get(f)            # None = the registry could not classify this family; it is shown, never hidden
        v = fams_ver.get(f, {})
        a = arch_of.get(f)
        pids = [p for aa in archs_of.get(f, []) for p in path_for_arch.get(aa, []) if f in paths[p]["evidenced_families"]]
        level = max([paths[p]["level"] for p in pids], key=LEVELS.index) if pids else LEVELS[0]
        n_inputs = len(archetypes[a]["inputs"]) if a else (len(blueprints[bp]["inputs"]) if bp else 0)
        families[f] = {"blueprint": bp, "archetype": a, "archetypes": archs_of.get(f, []), "unclassified": bp is None, "markets_now": v.get("markets_now"), "level": level, "evidence_paths": pids, "n_candidate_inputs": n_inputs,
                       "registry_essential_verified": v.get("essential_verified"), "registry_essential_total": v.get("essential_total"), "projection": (v.get("projection") or {}).get("status") if isinstance(v.get("projection"), dict) else None}
    used = {i["id"] for a in list(archetypes.values()) + list(unregistered.values()) for i in a["inputs"]} | {i["id"] for b in cat["blueprints"].values() for i in b["inputs"]}
    quality = catalog_quality(cat)
    return {"sport": sport, "catalog_quality": quality, "inputs": {i: input_def(i) for i in sorted(used)}, "families": families, "archetypes": archetypes, "unregistered_archetypes": unregistered, "blueprints": blueprints,
            "paths": {pid: {k: v for k, v in p.items() if k != "result"} | {"result": p["result"]} for pid, p in paths.items() if p["sport"] == sport},
            "catalog_stats": {"inputs": len(cat["inputs"]), "blueprints": len(cat["blueprints"]), "archetypes": len(cat.get("archetypes") or {}), "unregistered_archetypes": len(unregistered)}}


def build_index(sport_docs: dict, ver: dict, vintage: dict) -> dict:
    sports = {}
    for s, d in sport_docs.items():
        lv = {l: 0 for l in LEVELS}
        for f in d["families"].values():
            lv[f["level"]] += 1
        avail = {}
        for a in d["archetypes"].values():
            for i in a["inputs"]:
                o = d["inputs"][i["id"]]["availability"]["overall"]
                avail[o] = avail.get(o, 0) + 1
        sports[s] = {"families": len(d["families"]), "markets_now": sum(f["markets_now"] or 0 for f in d["families"].values()), "levels": lv, "catalog": d["catalog_stats"],
                     "archetype_input_availability": avail, "paths": sorted(d["paths"]), "archetypes": len(d["archetypes"])}
    return {"schema_version": "input-research-1.0", "status": "RESEARCH_ONLY", "generated_utc": vintage["generated_utc"], "vintage": vintage, "levels": LEVELS, "sports": sports,
            "notice": "Hypotheses and availability audits are not evidence. Only families at L1+ have any predictive test; L2 compares against a near-close sportsbook line; nothing is at L3/L4. "
                      "A tested input is not a bet, and no evidence here includes fees, spreads or executable depth."}


def write(obj, name):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(_r(obj), separators=(",", ":"), sort_keys=True) + "\n")


def build_all(paths: dict, vintage: dict, sports=C.SPORTS) -> dict:
    ver = load_verification()
    docs = {}
    for s in sports:
        if (C.CATALOG_DIR / f"{s}.json").exists():
            docs[s] = build_sport(s, paths, ver, vintage)
            write(docs[s], f"sport_{s}.json")
    idx = build_index(docs, ver, vintage)
    write(idx, "index.json")
    return {"index": idx, "docs": docs}
