#!/usr/bin/env python3
"""Independent reproduction check of PR #25's NFL execution cells (``reports/outcome_exec/nfl_execution.json``).
Re-derives, with sift_exec (independent loader + fill replay + fee code), every moneyline/spread 'all-split' maker cell of variant V0
(rest to KICKOFF, unfilled = 0, maker fee 0.0175) and the taker early-vs-close comparison, and reports agreement.
usage: repro_pr25.py --pr25 reports/outcome_exec/nfl_execution.json --out reports/exec_track/repro_pr25.json [--cache ticks.pkl]"""
import argparse, json, os, sys
import numpy as np
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from research.exec_track import nfl_study as NS            # noqa: E402
from sift_exec import fees as FE, study as ST              # noqa: E402
from sift_research import nfl25 as N                       # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pr25", default="reports/outcome_exec/nfl_execution.json"); ap.add_argument("--out", default="reports/exec_track/repro_pr25.json")
    ap.add_argument("--backfill", default=N.BACKFILL); ap.add_argument("--games", default=N.GAMES_CSV); ap.add_argument("--cache", default=None)
    a = ap.parse_args(argv)
    ref = json.load(open(a.pr25))
    ticks = NS.load_ticks(a.backfill, a.games, a.cache)
    rows, audit = ST.build_rows(ticks, expiry_min=0, through_any_side=False)        # PR #25 parity: rests to kickoff, qualifying-side prints only
    ev = ST.evaluate(rows, FE.MAKER_COEF)
    det = {}
    for i, r in enumerate(rows):
        if r["determinate"]:
            det.setdefault((r["family"], r["horizon"], r["rule"], r["queue"]), []).append(i)
    res = []
    for k, ix in det.items():
        key = "V0|%s|%s|%s|%s|all" % k
        p = ref["maker_cells"].get(key)
        if not p:
            continue
        ix = np.array(ix); f = ev["filled"][ix]
        mine_fill = float((f > 0).mean()); mine_profit = float(ev["v_settle_nb"][ix].mean())
        mine_vs_wait = float((ev["v_settle_nb"][ix] - ev["v_settle_wait"][ix]).mean())
        res.append(dict(cell=key, n_mine=len(ix), n_ref=p["n_orders"], fill_ref=p["fill_prob"], fill_mine=round(mine_fill, 6),
                        profit_ref_c=round(100 * p["profit_per_submitted_contract"]["mean"], 4), profit_mine_c=round(mine_profit, 4),
                        vs_wait_ref_c=round(100 * p["delta_vs_wait_and_take_close"]["mean"], 4), vs_wait_mine_c=round(mine_vs_wait, 4)))
    def agree(f, tol):
        return sum(1 for r in res if r["n_mine"] == r["n_ref"] and abs(f(r)) <= tol)
    summary = dict(cells_compared=len(res), n_orders_equal=sum(r["n_mine"] == r["n_ref"] for r in res),
                   fill_prob_within_1em6=agree(lambda r: r["fill_mine"] - r["fill_ref"], 1e-6),
                   profit_within_0p01c=agree(lambda r: r["profit_mine_c"] - r["profit_ref_c"], 0.01),
                   profit_within_0p25c=agree(lambda r: r["profit_mine_c"] - r["profit_ref_c"], 0.25),
                   vs_wait_within_0p25c=agree(lambda r: r["vs_wait_mine_c"] - r["vs_wait_ref_c"], 0.25),
                   max_abs_profit_diff_c=round(max(abs(r["profit_mine_c"] - r["profit_ref_c"]) for r in res), 4) if res else None,
                   max_abs_fill_diff=round(max(abs(r["fill_mine"] - r["fill_ref"]) for r in res), 6) if res else None)
    worst = sorted(res, key=lambda r: -abs(r["profit_mine_c"] - r["profit_ref_c"]))[:8]
    json.dump(dict(version="sift-exec-repro/1", status="RESEARCH_ONLY", summary=summary, worst_profit_differences=worst,
                   note="expiry=kickoff, unfilled=0, maker 0.0175, whole-order fee on the filled quantity (PR #25 rounds the fee quantity to an integer for fractional partial fills; sift_exec does not)"),
              open(a.out, "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
