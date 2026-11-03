"""Contract-equivalence audit between a base Kalshi series and a suffixed variant series (e.g. NBA *PROT).

Usage: python -m alpha_engine.variant_audit MARKETS_JSONL OUT_JSON SUFFIX BASE1,BASE2,...
Pairs markets by (event, leg) and reports which fields differ. Settlement-relevant fields (rules_primary,
rules_secondary, settlement_timer_seconds, close/expiration times, strike) decide `settlement_equivalent`; quote
and lifecycle fields never do. Variants are kept as separate identifiers either way."""
import collections, json, sys

SETTLE = ("rules_primary", "rules_secondary", "settlement_timer_seconds", "close_time", "expiration_time", "expected_expiration_time",
          "strike_type", "custom_strike", "market_type", "can_close_early", "early_close_condition", "settlement_bounds_type", "yes_sub_title", "title")


def audit(rows, suffix, bases):
    by = collections.defaultdict(dict)
    for m in rows:
        ser = m["ticker"].split("-")[0]
        base = ser[: -len(suffix)] if ser.endswith(suffix) else ser
        if base in bases:
            by[(base, "-".join(m["ticker"].split("-")[1:]))]["V" if ser.endswith(suffix) else "B"] = m
    out = {}
    for b in bases:
        keys = [k for k in by if k[0] == b]
        pairs = [by[k] for k in keys if len(by[k]) == 2]
        diff = collections.Counter(f for p in pairs for f in set(p["B"]) | set(p["V"]) if p["B"].get(f) != p["V"].get(f))
        sample = next((p for p in pairs), None)
        out[b] = {"variant_series": b + suffix, "base_markets": sum(1 for k in keys if "B" in by[k]), "variant_markets": sum(1 for k in keys if "V" in by[k]),
                  "paired": len(pairs), "base_only": sum(1 for k in keys if set(by[k]) == {"B"}), "variant_only": sum(1 for k in keys if set(by[k]) == {"V"}),
                  "fields_differing_in_all_pairs": sorted(f for f, n in diff.items() if pairs and n == len(pairs)),
                  "settlement_fields_differing": sorted(f for f in SETTLE if diff.get(f)),
                  "settlement_equivalent": not any(diff.get(f) for f in SETTLE),
                  "rules_secondary_base": sample and sample["B"].get("rules_secondary", "")[:600], "rules_secondary_variant": sample and sample["V"].get("rules_secondary", "")[:700],
                  "settlement_timer_seconds": sample and [sample["B"].get("settlement_timer_seconds"), sample["V"].get("settlement_timer_seconds")]}
    return out


if __name__ == "__main__":
    src, dst, suffix, bases = sys.argv[1:5]
    rows = [json.loads(l) for l in open(src)]
    res = audit(rows, suffix, set(bases.split(",")))
    json.dump({"schema_version": "audit-1.0", "suffix": suffix, "source_markets": len(rows), "pairs": res}, open(dst, "w"), indent=1)
    print({b: (v["paired"], v["settlement_equivalent"], v["settlement_fields_differing"]) for b, v in res.items()})
