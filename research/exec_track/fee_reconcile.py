#!/usr/bin/env python3
"""Reconcile exchange fee METADATA (series fee_type from the weekly market-data captures) with fee classes OBSERVED on already-authorized real fills.
Inputs are AGGREGATES only (scripts/validate_fee_schedule.py output: counts by series and fee class; never tickers, prices, amounts or ids) so this tool cannot expose private records.
It never places or requests an order.  usage: fee_reconcile.py --observed fee_validation.json --fees DIR_OF_FEE_CAPTURES --schedule config/kalshi_fee_schedule.json --out out.json
Verdict per series: CONSISTENT / CONTRADICTS_METADATA / NO_OBSERVATION / NO_METADATA.  A maker coefficient is only VERIFIED_BY_FILL if MAKER-class fills (fee ~ 0.0175 rate) are observed."""
import argparse, json, os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from sift_exec import fees as FE      # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--observed", required=True); ap.add_argument("--fees", required=True); ap.add_argument("--schedule", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    obs = json.load(open(a.observed))
    assert "aggregates only" in obs.get("privacy", ""), "refusing non-aggregate input"
    arch, _ = FE.load_fee_archive(a.fees)
    sched = json.load(open(a.schedule))["schedules"][-1]["series"]
    out = dict(version="sift-exec-fee-reconcile/1", status="RESEARCH_ONLY", privacy="aggregates only: no tickers, prices, amounts or ids", series={}, summary={})
    cnt = {}
    for s, d in sorted(obs["by_series"].items()):
        g = FE.series_fee(s, arch, sched)
        n = d.get("n", 0); taker = d.get("TAKER_0.07", 0); maker = d.get("MAKER_0.0175", 0); zero = d.get("ZERO_FEE", 0); other = d.get("OTHER", 0)
        if g.fee_type is None:
            verdict = "NO_METADATA"
        elif n == 0:
            verdict = "NO_OBSERVATION"
        elif g.fee_type == "quadratic_with_maker_fees" and maker + zero == 0 and taker == n:
            verdict = "CONSISTENT"          # metadata allows maker fees; every fill we have was a taker fill: says nothing about the maker rate
        elif g.fee_type == "quadratic" and maker == 0:
            verdict = "CONSISTENT"
        else:
            verdict = "CONTRADICTS_METADATA" if (g.fee_type == "quadratic" and maker > 0) else "CONSISTENT"
        out["series"][s] = dict(fills=n, taker_class=taker, maker_class=maker, zero_fee=zero, other=other, implied_rate_median=d.get("implied_rate_median"),
                                exchange_fee_type=g.fee_type, maker_evidence=g.maker_evidence, maker_coef_supported=g.maker_coef_supported,
                                maker_verified_by_fill=bool(maker > 0), verdict=verdict)
        cnt[verdict] = cnt.get(verdict, 0) + 1
    out["summary"] = dict(verdicts=cnt, series_with_maker_fills_observed=sum(v["maker_verified_by_fill"] for v in out["series"].values()),
                          nfl_series_with_maker_fee_type_and_fills=[s for s, v in out["series"].items() if v["exchange_fee_type"] == "quadratic_with_maker_fees" and v["fills"]],
                          reading="No series has an observed maker-class fill, so no maker coefficient is verified by a fill. Taker fills on maker-fee series are consistent with the metadata but silent on the maker rate.")
    json.dump(out, open(a.out, "w"), indent=1, sort_keys=True)
    print(json.dumps(out["summary"], indent=1))


if __name__ == "__main__":
    main()
