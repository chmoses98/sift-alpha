#!/usr/bin/env python3
"""Assemble the privacy-safe EXECUTION summary (sift-clv-executable/1 + sift-clv-limit/1).  Aggregates only.

    build_exec_public_summary.py --nfl a.json --cfb b.json --nba c.json --nhl d.json --shadow e.json \
        --limitsim results.json --notes notes.json --out execution_summary.json

Dropped on purpose: real-wager per-family blocks (owner trading behaviour), stakes, P&L, ROI, tickers, contract counts,
order ids. Every block says whether it reflects VERIFIED ACTUAL trades or HYPOTHETICAL selections/orders.
"""
import argparse, json
from datetime import datetime, timezone

DEFS = {
    "executable_purchase_clv": "closing ASK of the held side - our actual fee-exclusive fill VWAP (cents). >0: we paid LESS than someone buying at the close. 0: the executable price did not change. <0: waiting would have been cheaper. Never uses a bid as a purchase price.",
    "midpoint_execution_clv": "closing midpoint - our actual fill VWAP (cents). The traditional mark-to-market measure; kept unchanged. Equals executable_purchase_clv - closing half-spread.",
    "liquidation_clv": "closing BID of the held side - our actual fill VWAP (cents): what we could sell for at the close versus what we paid. Equals midpoint_execution_clv - closing half-spread.",
    "fee_adjusted": "each measure minus the exchange-reported entry fee per contract, subtracted exactly once. A hypothetical liquidation also shows a MODELLED sale fee separately; a position held to settlement has no sale fee.",
    "size_adjusted_purchase_clv": "depth-walked ask VWAP for OUR quantity at an archived closing order book minus our fill VWAP. Reported only where a same-ticker book observed before the start exists; otherwise unavailable, never approximated.",
    "early_entry_taker_advantage": "HYPOTHETICAL: closing ask - horizon ask on the model side. >0 means an immediate early taker paid less than a closing buyer. Equals selection CLV + (closing half-spread - entry half-spread): a widened closing spread inflates it without any change in fair value.",
    "limit_order_fill": "HYPOTHETICAL: a resting buy fills only when the historical trade tape shows an aggressor selling that side into it. Reported as LOWER (back of queue, no cancellation credit) and UPPER (front of queue) bounds; 'uncertain' where evidence is missing; never assumed.",
    "independence": "95% intervals resample whole games (clusters).",
}
SPORTS = ("NFL", "CFB", "NBA", "NHL")


def real_block(res, source):
    o = res["overall"]
    keep = ("executable_purchase_clv", "liquidation_clv", "midpoint_execution_clv", "executable_purchase_net_of_entry_fee",
            "midpoint_execution_net_of_entry_fee", "liquidation_net_of_entry_fee", "liquidation_net_all_fees")
    out = {"evidence": "VERIFIED ACTUAL TRADES (owner-placed; no verified recommendation link)", "source": source,
           "denominators": {"wagers_in_ledger": res["wagers"], "pregame_entries_eligible": res["entry_eligible"],
                            "verified_fills": res["verified"], "games": res["verified_games"]},
           "unverifiable_by_reason": res["unverifiable_by_reason"],
           "measures_cents": {k: o[k] for k in keep},
           "closing_spread_cents_mean": o["closing_spread_cents_mean"],
           "closing_half_spread_cents_mean": o["closing_half_spread_cents_mean"],
           "entry_fee_cents_mean": o["entry_fee_cents_mean"],
           "cost_decomposition_cents_vs_close_mid": o["cost_decomposition_cents_vs_close_mid"],
           "depth": res["depth"],
           "by_entry_hours_before_start": {k: {"n": v["n"], "games": v["games"],
                                               "executable_purchase_clv": v["executable_purchase_clv"],
                                               "midpoint_execution_clv": v["midpoint_execution_clv"]}
                                           for k, v in res["by_entry_hours_before_start"].items()}}
    return out


def limit_block(ls):
    rows = {}
    for key, cell in ls["cells"].items():
        _, rule, win = key.split("|")
        r = {}
        for b in ("lo", "up"):
            p = cell[b]["point"]
            ci = cell[b].get("ci95", {})
            r[b] = {"decisions": p["n"], "fully_filled": p["full"], "partial": p["partial"], "unfilled": p["unfilled"],
                    "uncertain_or_unknown": p["uncertain_or_unknown"], "full_fill_rate_of_determinate": p.get("full_rate_det"),
                    "full_fill_rate_ci95": ci.get("full_rate_det"),
                    "price_improvement_vs_closing_ask_filled_cents": p.get("imp_close_filled_mean"),   # already in cents
                    "price_improvement_ci95": ci.get("imp_close_filled_mean"),
                    "mid_drift_after_fill_cents": p.get("drift_filled_mid_to_close"),
                    "mid_drift_if_unfilled_cents": p.get("drift_unfilled_mid_to_close"),
                    "value_per_decision_unfilled_zero_cents": p.get("value_per_decision_unfilled_zero"),
                    "value_per_decision_unfilled_cross_1h_cents": p.get("value_per_decision_unfilled_cross1h"),
                    "breakeven_edge_cents": p.get("breakeven_edge_cents"), "breakeven_edge_ci95": ci.get("breakeven_edge_cents"),
                    "baseline_buy_closing_ask_value_cents": p.get("baseline_close_ask_value"),
                    "baseline_owner_actual_value_cents": p.get("baseline_owner_actual_value")}
        rows.setdefault(rule, {})[win] = r
    return {"evidence": "HYPOTHETICAL (simulated resting orders over the archived trade tape; not real orders)",
            "scope": ls["meta"], "coverage": ls["coverage"], "orientation_check": ls["orientation_check"], "by_rule": rows}


def main():
    ap = argparse.ArgumentParser()
    for k in ("nfl", "cfb", "nba", "nhl", "shadow", "limitsim", "notes", "out"):
        ap.add_argument("--" + k, required=True)
    a = ap.parse_args()
    notes = json.load(open(a.notes))
    shadow = json.load(open(a.shadow))
    out = {"schema": "sift-clv-execution-summary/1", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "metric_definitions": DEFS,
           "privacy": "aggregates only; no stakes, P&L, ROI, tickers, prices, contract counts, order ids or per-wager rows",
           "provenance": notes["provenance"],
           "real_wagers": {s: real_block(json.load(open(getattr(a, s.lower()))), notes["sources"][s]) for s in SPORTS},
           "hypothetical_early_taker_nfl": {
               "evidence": "HYPOTHETICAL model-side selections (NFL shadow v2); not bets",
               "counts": shadow["counts"], "overall": shadow["overall"],
               "by_horizon": shadow["by"]["horizon"], "by_price_bucket": shadow["by"]["price_bucket"],
               "by_chronological_split": shadow["by"]["split"], "by_week": shadow["by"]["week"],
               "by_family": shadow["by"]["family"], "rank_basis": shadow["rank_basis"],
               "ranked_families_by_early_advantage": shadow["ranked_families_by_early_advantage"],
               "horizons_present": ["CYCLE", "T-24h", "T-6h", "T-90m", "T-30m"],
               "horizons_absent": ["T-48h", "T-12h", "T-1h"]},
           "limit_order_simulation_nfl": limit_block(json.load(open(a.limitsim))),
           "before_after": notes["before_after"], "answers": notes["answers"], "evidence_quality": notes["evidence_quality"],
           "missing_evidence": notes["missing_evidence"], "not_measured": notes["not_measured"]}
    json.dump(out, open(a.out, "w"), indent=1, sort_keys=True, default=str)
    print("wrote", a.out, len(json.dumps(out)) // 1024, "KB")


if __name__ == "__main__":
    main()
