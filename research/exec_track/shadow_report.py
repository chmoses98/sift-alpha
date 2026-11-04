#!/usr/bin/env python3
"""Matched, equal-exposure summary of a shadow-order ledger -> JSON (aggregates only).  usage: shadow_report.py --ledger L --out OUT"""
import argparse, json, os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from sift_exec import shadow_report as SR          # noqa: E402
from sift_research import shadow_orders as SO      # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    t = SR.table(a.ledger)
    t.update(version="sift-exec-shadow-report/1", status="RESEARCH_ONLY", provenance="HYPOTHETICAL_SHADOW", evaluator=SO.evaluate(a.ledger))
    json.dump(t, open(a.out, "w"), indent=1, sort_keys=True)
    print(json.dumps({k: t[k] for k in ("n_decisions_placed", "n_decisions_closed", "by_generation", "n_win_known")}))


if __name__ == "__main__":
    main()
