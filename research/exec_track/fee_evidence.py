#!/usr/bin/env python3
"""Series-level Kalshi fee evidence (priority 2).  Reads the exchange fee-metadata captures on market-data (``data/kalshi/fees/*.json``, weekly,
``GET /series`` fee_type + ``GET /series/fee_changes``) and the committed schedule window (nfl-edge-finder ``config/kalshi_fee_schedule.json``), grades each
series' MAKER fee evidence (sift_exec.fees.series_fee) and writes an aggregate report.  usage: fee_evidence.py --fees DIR --schedule FILE --out FILE"""
import argparse, collections, json, os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from sift_exec import fees as FE      # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fees", required=True); ap.add_argument("--schedule", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    arch, changes = FE.load_fee_archive(a.fees)
    sched_doc = json.load(open(a.schedule))
    win = sched_doc["schedules"][-1]
    sched = win["series"]
    series = sorted(arch[max(arch)])
    graded = {s: FE.series_fee(s, arch, sched) for s in series}
    stable = {s: len({v.get(s, (None,))[0] for v in arch.values()}) == 1 for s in series}
    maker_types = [s for s, g in graded.items() if g.fee_type == "quadratic_with_maker_fees"]
    focus = ["KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL", "KXNFLTEAMTOTAL", "KXNFL1HWINNER", "KXNFL1HSPREAD", "KXNFL1HTOTAL"]
    out = dict(version="sift-exec-fee-evidence/1", status="RESEARCH_ONLY",
               sources=dict(exchange_fee_type=f"market-data data/kalshi/fees/*.json ({len(arch)} weekly captures {min(arch)}..{max(arch)}; GET /series fee_type, GET /series/fee_changes)",
                            schedule_window=dict(window_id=win["window_id"], effective_from=win["effective_from"], source=win["source"], verified_by=win["verified_by"],
                                                 maker_base_coefficient=win["maker_base_coefficient"], taker_base_coefficient=win["taker_base_coefficient"],
                                                 default_maker_multiplier=win["default_maker_multiplier"], listed_series=sorted(sched)),
                            observed_taker_fees="docs/FEE_VALIDATION.md (PR #26): 643/646 real fees = ceil(0.07*C*P*(1-P)), 0 maker fills observed"),
               n_series_in_archive=len(series), fee_type_counts=dict(collections.Counter(g.fee_type for g in graded.values())),
               fee_type_stable_across_captures=all(stable.values()), series_with_maker_fee_type=maker_types,
               maker_evidence_counts=dict(collections.Counter(g.maker_evidence for g in graded.values())),
               focus={s: dict(fee_type=graded[s].fee_type, multiplier=graded[s].fee_multiplier, maker_evidence=graded[s].maker_evidence, maker_coef_supported=graded[s].maker_coef_supported,
                              first_fee_change_effective=FE.effective_from(changes, s), note=graded[s].note) for s in focus if s in graded},
               not_in_archive=dict(NBA="no fee archive for NBA series (only the NFL-family series list is captured) -> maker rate UNVERIFIED, scenarios only",
                                   NHL="same", CFB="same"),
               findings=["PR #26's statement 'third-party descriptions say most series charge makers nothing, so 0.0175 is an upper bound' is true for 367/392 archived NFL-family series "
                         "(fee_type quadratic = taker-only) but NOT for KXNFLGAME, KXNFLSPREAD, KXNFLTOTAL: the exchange itself labels them quadratic_with_maker_fees.",
                         "KXNFLGAME: maker multiplier 1.0 is listed in the attested schedule window => 0.0175 coefficient is the schedule-supported maker rate for 2026 games. "
                         "The only fee_change record for it is effective 2026-01-01T08:00Z, so for the 2025 regular season the maker fee_type is not documented in this archive.",
                         "KXNFLSPREAD / KXNFLTOTAL: maker-fee type with NO listed maker multiplier => UNVERIFIED (fail closed); report the whole M0/M25/M100 range.",
                         "Taker 0.07 is empirically confirmed; no real maker fill exists, so no maker fee is OBSERVED anywhere."])
    json.dump(out, open(a.out, "w"), indent=1, sort_keys=True)
    print(json.dumps(out["focus"], indent=1)); print(out["maker_evidence_counts"], out["fee_type_counts"])


if __name__ == "__main__":
    main()
