#!/usr/bin/env python3
"""Aggregate-only payload for the SIFT Alpha dashboard's execution-research panel (no tickers, ids, orders, stakes or personal P&L).
usage: build_dashboard_summary.py [--shadow-summary shadow_summary.json] [--coverage coverage.json] --out research/audit/exec/execution_research_summary.json"""
import argparse, json, os, sys

R = "reports/exec_track/"


def L(p, default=None):
    return json.load(open(p)) if p and os.path.exists(p) else default


def g(d, *ks):
    for k in ks:
        d = (d or {}).get(k)
    return d


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--shadow-summary"); ap.add_argument("--coverage"); ap.add_argument("--out", default="research/audit/exec/execution_research_summary.json")
    a = ap.parse_args(argv)
    st, live, fee, tape = L(R + "nfl_study.json"), L(R + "nfl_live_2026.json"), L(R + "fee_evidence.json"), L(R + "tape_audit.json")
    bn, bh = L(R + "book_depth_nba.json"), L(R + "book_depth_nhl.json")
    sh, cov = L(a.shadow_summary), L(a.coverage)
    out = dict(schema="sift-exec-research-dashboard/1", status="RESEARCH_ONLY", validated_strategies=[], privacy="aggregates only: no tickers, order ids, stakes, personal fills or P&L",
               headline=dict(absolute_net_ev="NOT DEMONSTRATED", relative_execution_cost="LIMIT with taker fallback is cheaper than waiting under maker fees M0/M25 (conditional); not under M100", live_execution_authority="NONE"))
    # 1. execution cost by entry strategy (cents/contract, all-in of fees, marked at the pre-start close mid; 2026 live = displayed queue)
    ex = {}
    for h in ("24h", "6h", "90m"):
        row = {}
        for sc in ("M0", "M25", "M100"):
            c = g(live, "cells", sc, f"{h}|AT_BID|DISPLAYED")
            if c:
                row[sc] = dict(fill_prob=c["fill_prob"], limit_fb_minus_wait_cents=c["mark_fb_minus_wait_cents"], nobet_per_submitted_cents=c["mark_nobet_per_submitted_cents"])
        row["wait_cents"] = g(live, "cells", "M25", f"{h}|AT_BID|DISPLAYED", "mark_wait_cents")
        ex[h] = row
    out["execution_cost_by_strategy_2026_live"] = dict(unit="cents per contract, equal exposure, 95% CI resampling games", source="2026 live capture, displayed bid queue", by_horizon=ex)
    tk = (st or {}).get("taker_reference", {})
    out["early_taker_vs_wait_2025"] = {h: tk[f"moneyline|{h}"]["early_taker_minus_wait_taker_net_cents_mark"] for h in ("7d", "72h", "48h", "24h", "6h", "90m") if f"moneyline|{h}" in tk}
    out["preregistered_2025"] = {sc: {k: dict(selected=v["selected"], validation_holm_p=v["validation_holm_adj_p_selected"], validation_passed=v["validation_passed"], holdout=v["holdout"]) for k, v in x.items()}
                                 for sc, x in (st or {}).get("preregistered", {}).items()}
    # 2. maker-fee verification
    out["maker_fee_verification"] = dict(taker_0_07="VERIFIED (643/646 exchange-reported fees)", maker_observed_fills=0, maker_status=dict(
        KXNFLGAME="SCHEDULE_ATTESTED 0.0175 (exchange fee_type = quadratic_with_maker_fees)", KXNFLSPREAD="UNVERIFIED (maker-fee type, no listed multiplier)", KXNFLTOTAL="UNVERIFIED (maker-fee type, no listed multiplier)",
        other_nfl_series=f"{g(fee, 'fee_type_counts', 'quadratic')} series taker-only (maker 0, exchange fee_type)", NBA="UNVERIFIED", NHL="UNVERIFIED", CFB="UNVERIFIED"),
        scenarios=dict(M0=0.0, M25=0.0175, M100=0.07), evidence=g(fee, "maker_evidence_counts"))
    # 3. queue and fill-probability evidence
    out["queue_and_fill_evidence"] = dict(
        displayed_best_bid_size_2026=(live or {}).get("displayed_bid_size_at_placement"), fill_prob_2026_at_bid={h: g(live, "cells", "M25", f"{h}|AT_BID|DISPLAYED", "fill_prob") for h in ("24h", "6h", "90m")},
        assumed_queue_2025=dict(central="Q500 (UNSUPPORTED: displayed queue is 100x larger)", scenarios=["FRONT", "Q500", "Q5000", "THROUGH_ONLY"]),
        nba_nhl_displayed_best_bid=dict(NBA_game_2_6h=g(bn, "KXNBAGAME|2-6h", "best_bid_size"), NHL_game_2_6h=g(bh, "KXNHLGAME|2-6h", "best_bid_size")),
        tape=dict(capped_moneyline=g(tape, "truncation", "KXNFLGAME", "capped"), moneyline=g(tape, "truncation", "KXNFLGAME", "tickers"), candle_vs_tape=g(tape, "candle_vs_tape")))
    # 4. prospective shadow results
    if sh:
        out["shadow_orders"] = dict(provenance="HYPOTHETICAL_SHADOW (never an observed personal fill)", decisions_placed=sh["n_decisions_placed"], decisions_closed=sh["n_decisions_closed"], by_generation=sh["by_generation"],
                                    prospective_decisions=sh["by_generation"].get("PROSPECTIVE", 0), results_note="RETROSPECTIVE_REPLAY rows are not prospective validation",
                                    cells={k: v for k, v in sh["cells"].items() if k.startswith("M25|") and any(t in k for t in ("|24h|", "|6h|", "|90m|")) and ("LIMIT_FB|AT_BID|FB|central" in k or "LIMIT_FB|ASK_MINUS_2|FB|central" in k or k.endswith("|WAIT") or k.endswith("|BUY_NOW"))})
    else:
        out["shadow_orders"] = dict(provenance="HYPOTHETICAL_SHADOW", decisions_placed=0, prospective_decisions=0)
    # 5. data completeness / collector health
    out["data_completeness"] = dict(nfl_backfill_before=g(cov, "totals"), tape_cap=dict(capped_tapes=g(cov, "totals", "legacy_tape_capped_at_10000"), tapes=g(cov, "totals", "legacy_tape_files")),
                                   collector_repair="PR nfl-edge-finder#247 (not yet dispatched against the live API: after-coverage unverified)")
    out["status_labels"] = dict(entry_tactics="RESEARCH_ONLY", limit_with_fallback="RESEARCH_ONLY (conditional execution-cost improvement; no absolute EV)", outcome_models="RESEARCH_ONLY (none beats the market after fees)")
    # 6. outcome candidates (kept separate from execution)
    o = L("reports/outcome_exec/summary.json") or {}
    cand = []
    for x in (g(o, "2_ranked_outcome_findings", "cfb_2026") or []):
        h = x.get("holdout") or {}
        cand.append(dict(sport="CFB", cell="|".join(f"{k}={v}" for k, v in x["cell"].items()), holdout_mean_cents=round(100 * h.get("mean", 0), 2), holdout_ci_cents=[round(100 * h.get("lo", 0), 2), round(100 * h.get("hi", 0), 2)], n_games=h.get("n_games"), status="NOT_DEMONSTRATED"))
    out["outcome_candidates"] = dict(note="Closest-to-market cells by holdout mean; none has a positive holdout interval. Kept separate from execution evidence.", cells=sorted(cand, key=lambda r: -r["holdout_mean_cents"]))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(out, open(a.out, "w"), indent=1, sort_keys=True)
    print("wrote", a.out, os.path.getsize(a.out))


if __name__ == "__main__":
    main()
