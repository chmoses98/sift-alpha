#!/usr/bin/env python3
"""Assemble the privacy-safe public CLV summary from the per-sport recalculation outputs.

    build_clv_public_summary.py --nfl-real a.json --cfb-real b.json --nba-real c.json --nfl-shadow d.json \
        --sources sources.json --out clv_summary.json

PUBLIC-SAFE BY CONSTRUCTION: only counts, CLV distributions, fee-per-contract and coverage reasons are copied. Stakes,
P&L, ROI, tickers, prices, order ids and per-wager rows are never read into the output (`economics` and `by_family`
of the real-wager inputs are dropped on purpose; realised ROI is reported privately, not published).
Every metric carries a definition, a denominator and a source.
"""
import argparse, json
from datetime import datetime, timezone

DEFS = {
    "selection_clv": {
        "definition": "close midpoint - recommendation/horizon-time midpoint of the SAME side (YES/NO normalised); "
                      "fee-exclusive and spread-exclusive; probability points (dollars per contract)",
        "applies_to": "hypothetical model-side selections (NFL shadow). Real wagers: unverifiable (no recommendation->order link)"},
    "quoted_execution_clv": {
        "definition": "close midpoint - contemporaneous executable ASK of the side; pre-fee; includes the entry half-spread",
        "applies_to": "hypothetical selections"},
    "actual_execution_clv": {
        "definition": "close midpoint - quantity-weighted exchange fill VWAP (fee-EXCLUSIVE); pre-fee; includes real slippage "
                      "and spread; entry fees are NOT in the price",
        "applies_to": "real owner-placed wagers with a verified pregame close"},
    "fee_adjusted_difference": {
        "definition": "actual (or quoted) execution CLV - entry fee per contract; the entry fee is subtracted exactly once; "
                      "no exit fee for positions held to settlement. Real wagers: exchange-reported fees. Shadow: a modelled "
                      "schedule fee (never a fill)",
        "applies_to": "both"},
    "close_validity": {
        "definition": "two-sided, uncrossed quote of the same ticker, observed strictly before the scheduled start, no older "
                      "than 3600 s; settlement values, last trades and one-sided books are never closes"},
    "independence": {
        "definition": "uncertainty intervals are 95% percentile bootstraps resampling whole GAMES (clusters); many tickers, "
                      "horizons and arms of one game are not independent observations"},
}


def pick(d, *keys):
    return {k: d[k] for k in keys if k in d}


def real_block(res, key, source):
    r = res[key] if key in res else res
    out = {
        "source": source,
        "denominators": {"wagers_in_ledger": r["wagers"], "pregame_entries_eligible": r["entry_eligible"],
                         "verified_clv_observations": r["verified_clv_observations"]},
        "unverifiable_by_reason": r["unverifiable_by_reason"],
        "recommendation_linked_wagers": r["recommendation_linked"],
        "selection_clv": {"verified": 0, "reason": "no recommendation->order link exists in the ledger"},
        "actual_execution_clv": r["actual_execution_clv"],
        "fee_per_contract": pick(r["fee_per_contract"], "n", "mean", "median"),
        "fee_adjusted_difference": r["fee_adjusted_difference"],
        "fee_adjustment_count_max": r["fee_adjustment_count_max"],
        "money_identity_check": r["money_identity"],
        "spread_component": "not separable: AEX includes slippage + half-spread and no contemporaneous entry quote is joined "
                            "to real fills",
    }
    for extra in ("close_proxy_states", "evidence_gaps", "reconstruction_errors", "close_source", "distinct_boards_reconstructed"):
        if extra in r:
            out[extra] = r[extra]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nfl-real", required=True)
    ap.add_argument("--cfb-real", required=True)
    ap.add_argument("--nba-real", required=True)
    ap.add_argument("--nfl-shadow", required=True)
    ap.add_argument("--sources", required=True, help="JSON: provenance + before/after notes supplied by the operator")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    nfl, cfb, nba = (json.load(open(p)) for p in (a.nfl_real, a.cfb_real, a.nba_real))
    shadow, src = json.load(open(a.nfl_shadow)), json.load(open(a.sources))
    out = {
        "schema": "sift-clv-public-summary/1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "metric_definitions": DEFS,
        "privacy": "aggregates only; no stakes, P&L, ROI, tickers, prices or per-wager rows",
        "provenance": src["provenance"],
        "real_wagers": {
            "NFL": real_block(nfl, "nfl_real_wagers", "nfl handicap-data wagers+amended settlements; market-data canonical closes"),
            "CFB": real_block(cfb, "", "cfb accounting-data wagers; main git-history catalog snapshots (closing PROXY <= 60 min)"),
            "NBA": real_block(nba, "", "nba accounting-data wagers; data-archive checkpoint+delta reconstruction (hash-verified)"),
        },
        "hypothetical_selections": {
            "NFL_shadow_v2": {
                "source": "market-data shadow/v2 clv-2.0.0 records, model-preferred side at the horizon",
                "counts": shadow["counts"], "gates": f"CLV_OK, close age <= {int(shadow['max_close_age_seconds'])}s, "
                "one record per (game,ticker,horizon,arm)",
                "before_pooled_as_published": shadow["before_pooled_as_published"],
                "after_gated_deduped": shadow["after_gated_deduped"],
                "by_horizon": shadow["by"]["horizon"], "by_price_bucket": shadow["by"]["price_bucket"],
                "by_week_chronological": shadow["by"]["week"], "by_family": shadow["by"]["family"],
                "rank_basis": shadow["rank_basis"],
                "ranked_families_by_selection": shadow["ranked_families_by_selection"],
                "ranked_families_by_fee_adjusted": shadow["ranked_families_by_fee_adjusted"],
            }},
        "before_after": src["before_after"],
        "missing_evidence": src["missing_evidence"],
        "evidence_quality": src["evidence_quality"],
        "not_measured": src["not_measured"],
    }
    json.dump(out, open(a.out, "w"), indent=1, sort_keys=True, default=str)
    print("wrote", a.out, "bytes", len(json.dumps(out)))


if __name__ == "__main__":
    main()
