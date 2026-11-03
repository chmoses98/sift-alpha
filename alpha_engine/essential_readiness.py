"""Essential-input readiness per market family and sport, split into the seven dimensions.

Everything is computed from research/audit (market_specs drivers x collection_status verification classes x
input_registry categories x model_validation). Nothing is hand-typed and no input is ever upgraded here.

Unit: family x input essential LINKS (a shared input counts once per family). Counting rule: an input is VERIFIED only if its verification class is VERIFIED_COLLECTION. COLLECTED_UNVERIFIED_PIT and
STALE_OR_PARTIAL count as `collected` but not verified. DERIVED inputs are reported separately (they are only as good as
their parents). CODE_REFERENCE_ONLY / MISSING / UNKNOWN count as neither. `required` = drivers tiered E (essential).

Dimensions (which essential inputs belong to each):
  definition_settlement : category settlement + m.fees / m.ladder_structure  (rules text, lifecycle, fees, ladder)
  historical_outcomes   : m.settlement_truth, m.strike_hit_rates
  matchup_player        : every sport-specific (non m.*) essential
  prices_liquidity      : m.quote_history, m.orderbook_depth, m.volume_oi, m.trade_tape, m.external_lines
  pit_validity          : verified / required over ALL essentials (strict: only VERIFIED_COLLECTION)
  model_consumption     : essentials whose model_use is USED / USED_PARTIAL
  predictive_validation : repo-reported only (NBA/NHL player families); everything else NOT_ASSESSED
A family with zero essentials in a dimension reports required=0 and is not counted as ready or unready there."""
import json
from collections import Counter, defaultdict
from pathlib import Path

A = Path(__file__).resolve().parents[1] / "research" / "audit"
DIM_OF = {"m.rules_text": "definition_settlement", "m.lifecycle": "definition_settlement", "m.fees": "definition_settlement", "m.ladder_structure": "definition_settlement",
          "m.settlement_truth": "historical_outcomes", "m.strike_hit_rates": "historical_outcomes",
          "m.quote_history": "prices_liquidity", "m.orderbook_depth": "prices_liquidity", "m.volume_oi": "prices_liquidity", "m.trade_tape": "prices_liquidity", "m.external_lines": "prices_liquidity"}
DIMS = ["definition_settlement", "historical_outcomes", "matchup_player", "prices_liquidity"]
USED = {"USED", "USED_PARTIAL"}


def build():
    specs = json.loads((A / "market_specs.json").read_text())["families"]
    cs = json.loads((A / "collection_status.json").read_text())["sports"]
    mv = json.loads((A / "model_validation.json").read_text()).get("sports", {})
    common = json.loads((A / "input_registry.json").read_text())["common_inputs"]
    cls = {}
    for s, v in cs.items():
        for i, x in v["inputs"].items():
            cls[(s, i)] = x
    unclassified = Counter()
    def info(s, i):
        x = cls.get((s, i))           # strict: never borrow another sport's classification
        if x is None: unclassified[(s, i)] += 1
        return x
    fams, per_sport = {}, defaultdict(lambda: defaultdict(Counter))
    for key, f in specs.items():
        s = f["sport"]
        ess = [i for i, t in f.get("drivers", {}).items() if t == "E"]
        row = {"sport": s, "family": f["native_family"], "markets_now": f.get("markets_now"), "status": f["status"], "required": len(ess), "dims": {}, "gaps": []}
        dim_items = defaultdict(list)
        for i in ess:
            x = info(s, i) or {}
            vc, mu = x.get("verification_class", "UNKNOWN"), x.get("model_use", "UNKNOWN")
            dim = DIM_OF.get(i, "matchup_player")
            dim_items[dim].append((i, vc, mu))
            if vc != "VERIFIED_COLLECTION": row["gaps"].append({"input": i, "class": vc, "dimension": dim})
        for d in DIMS:
            it = dim_items.get(d, [])
            row["dims"][d] = {"required": len(it), "verified": sum(1 for _, v, _ in it if v == "VERIFIED_COLLECTION"),
                              "collected": sum(1 for _, v, _ in it if v in ("VERIFIED_COLLECTION", "COLLECTED_UNVERIFIED_PIT", "STALE_OR_PARTIAL")),
                              "derived": sum(1 for _, v, _ in it if v == "DERIVED")}
        allit = [t for v in dim_items.values() for t in v]
        row["verified"] = sum(1 for _, v, _ in allit if v == "VERIFIED_COLLECTION")
        row["collected"] = sum(1 for _, v, _ in allit if v in ("VERIFIED_COLLECTION", "COLLECTED_UNVERIFIED_PIT", "STALE_OR_PARTIAL"))
        row["derived"] = sum(1 for _, v, _ in allit if v == "DERIVED")
        row["model_used"] = sum(1 for _, _, m in allit if m in USED)
        row["predictive_validation"] = "NOT_ASSESSED"
        fams[key] = row
        for d in DIMS:
            for k, n in row["dims"][d].items(): per_sport[s][d][k] += n
        per_sport[s]["ALL"]["required"] += row["required"]; per_sport[s]["ALL"]["verified"] += row["verified"]
        per_sport[s]["ALL"]["collected"] += row["collected"]; per_sport[s]["ALL"]["derived"] += row["derived"]; per_sport[s]["ALL"]["model_used"] += row["model_used"]
        per_sport[s]["FAMILIES"]["n"] += 1; per_sport[s]["FAMILIES"]["n_with_essentials"] += bool(row["required"])
        per_sport[s]["FAMILIES"]["fully_verified"] += bool(row["required"] and row["verified"] == row["required"])
        per_sport[s]["FAMILIES"]["markets_now"] += row["markets_now"] or 0
        per_sport[s]["FAMILIES"]["markets_in_fully_verified"] += (row["markets_now"] or 0) if row["required"] and row["verified"] == row["required"] else 0
    for s, v in mv.items():
        if isinstance(v, dict): per_sport[s]["PREDICTIVE_REPO_REPORTED"] = {k: x["readiness"] for k, x in v.get("families", {}).items()}
    gaps = sorted(({"family": k, "sport": r["sport"], "markets_now": r["markets_now"], "required": r["required"], "verified": r["verified"], "missing": r["required"] - r["verified"],
                    "unverified_inputs": [g["input"] for g in r["gaps"]]} for k, r in fams.items() if r["required"] > r["verified"]),
                   key=lambda g: (-(g["markets_now"] or 0) * (g["missing"] / max(g["required"], 1)), g["family"]))
    inp_gap = Counter()
    for r in fams.values():
        for g in r["gaps"]: inp_gap[(r["sport"], g["input"], g["class"])] += r["markets_now"] or 0
    return {"schema_version": "readiness-1.0", "rule": __doc__, "sports": {s: {k: dict(v) if not isinstance(v, dict) else v for k, v in d.items()} for s, d in per_sport.items()},
            "unit": "family x input ESSENTIAL LINKS (an input shared by many families is counted once per family), not distinct inputs",
            "unclassified_links": {f"{a}:{b}": n for (a, b), n in unclassified.items()}, "families": fams, "top_gaps_by_market_weighted_missing_share": gaps[:40],
            "top_missing_inputs_by_markets_affected": [{"sport": s, "input": i, "class": c, "markets_affected": n} for (s, i, c), n in inp_gap.most_common(40)]}


if __name__ == "__main__":
    out = build()
    (A / "essential_readiness.json").write_text(json.dumps(out, indent=1, sort_keys=True))
    for s, d in out["sports"].items():
        a, f = d["ALL"], d["FAMILIES"]
        print(f"{s:7} essentials verified {a['verified']}/{a['required']} collected {a['collected']} derived {a['derived']} used {a['model_used']} | families fully verified {f['fully_verified']}/{f['n_with_essentials']} | markets in fully verified {f['markets_in_fully_verified']}/{f['markets_now']}")
