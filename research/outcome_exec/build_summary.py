#!/usr/bin/env python3
"""Assemble the dashboard-ready ``reports/outcome_exec/summary.json`` from the experiment outputs (no recomputation).
usage: build_summary.py [--reports reports/outcome_exec] [--inventory /path/inventory_raw.json]"""
import argparse, json, os, sys

def jl(p):
    return json.load(open(p)) if os.path.exists(p) else None

def pick(d, *ks):
    for k in ks:
        if d is None: return None
        d = d.get(k) if isinstance(d, dict) else None
    return d

OTHER_SPORT_ROLE = {
    ("chmoses98/NHL-edge-finder", "data-archive"): ("NHL", "Kalshi markets+orderbooks deltas, predictions, context from 2026-09-29; checkpoint+delta chains; real depth for prospective maker research", "~5 weeks; needs reconstruct_at; no outcome-model study done here"),
    ("chmoses98/nba-edge-finder", "data-archive"): ("NBA", "Kalshi markets+orderbooks deltas, boxscores from 2026-09-18", "~6 weeks; needs reconstruct_at; no outcome-model study done here"),
    ("chmoses98/nba-edge-finder", "nba-shadow-pure"): ("NBA", "shadow captures/evaluations, market listings", "~3 weeks"),
    ("chmoses98/soccer-edge-finder", "data-archive"): ("SOCCER", "odds-api claims, Kalshi captures from 2026-09-27", "~5 weeks; per-league structure not audited"),
    ("chmoses98/Tennis-Edge-Finder", "tennis-data"): ("TENNIS", "242k files incl. kalshi, firstball, processed from 2026-09-11", "not audited beyond file counts"),
    ("chmoses98/cbb-edge-finder", "kalshi-archive"): ("CBB", "Kalshi snapshots 2026-10/11", "season just started; few settlements"),
    ("chmoses98/cbb-edge-finder", "kalshi-panel-archive"): ("CBB", "Kalshi panels 2026-10/11", "season just started"),
    ("chmoses98/cbb-edge-finder", "projections-archive"): ("CBB", "projections 2027 season", "no outcomes yet"),
    ("chmoses98/edge-finder-api", "kalshi-router/backfill-MLB"): ("MLB", "edgelab snapshots/clv_quotes/postmortems 2022-04..2026-09, Statcast, Pinnacle historical", "longest history; format not audited here; best next extension candidate"),
    ("chmoses98/edge-finder-api", "main"): ("MLB", "edgelab games/markets/clv_quotes 2022-2026", "see above"),
}

def main(a):
    R = a.reports
    cfb, nfl, ex, itg = (jl(os.path.join(R, f + ".json")) for f in ("cfb_outcome", "nfl_outcome", "nfl_execution", "integration"))
    inv = jl(a.inventory)
    out = dict(status="RESEARCH_ONLY", schema="sift-outcome-exec-summary/1", sources=["cfb_outcome.json", "nfl_outcome.json", "nfl_execution.json", "integration.json"])
    # 1 coverage
    cov = dict(cfb_2026=pick(cfb, "coverage"), nfl_2025=dict(inventory_by_series_top=None, mapping=nfl and nfl.get("mapping_coverage"), price_coverage=nfl and nfl.get("price_coverage")),
               nfl_execution=pick(ex, "coverage"))
    if nfl:
        inv_s = nfl["inventory_by_series"]
        rows = sorted(inv_s, key=lambda r: -(r.get("settled_yes", 0) + r.get("settled_no", 0)))
        cov["nfl_2025"]["inventory_by_series_top"] = rows[:25]
        cov["nfl_2025"]["series_total"] = len(inv_s)
        cov["nfl_2025"]["series_with_price_history"] = sum(1 for r in inv_s if r.get("candle_files") or r.get("trade_files"))
        cov["nfl_2025"]["settled_markets_total"] = sum(r.get("settled_yes", 0) + r.get("settled_no", 0) for r in inv_s)
    others = []
    if inv:
        for repo, e in inv.items():
            for b, v in e["data_branches"].items():
                role = OTHER_SPORT_ROLE.get((repo, b))
                if role:
                    others.append(dict(sport=role[0], repo=repo, branch=b, files=v.get("files"), first_date=v.get("first_date"), last_date=v.get("last_date"), contents=role[1], usability=role[2]))
    cov["other_sports"] = others
    out["1_data_coverage_and_missingness"] = cov
    # 2 findings
    out["2_ranked_outcome_findings"] = dict(
        cfb_2026=pick(cfb, "ranked_findings"), nfl_2025=pick(nfl, "ranked_findings_by_frozen_holdout_net_ev"),
        model_vs_market=dict(cfb=pick(cfb, "calibration"), nfl_moneyline=nfl and nfl.get("moneyline_probability_accuracy"), nfl_margin=nfl and nfl.get("model_margin_total_accuracy_vs_closing_line")),
        unconditional_baselines=dict(cfb=pick(cfb, "ev"), nfl=nfl and nfl.get("unconditional_baselines_net_ev_per_contract")),
        reading="No rule has a positive net EV lower bound out of sample; see docs/OUTCOME_EXECUTION_RESEARCH.md")
    # 3 timing
    if ex:
        fh = ex["taker_entry_comparison"]["by_family_horizon"]
        timing = {}
        for k, v in fh.items():
            timing[k] = {}
            for pop in ("all_valid", "tight_spread_le_10c"):
                av = v.get(pop, {})
                timing[k][pop] = {m: av.get(m) for m in ("price_improvement_early_ask_vs_close_ask_cents", "early_taker_minus_wait_take_net_pnl", "taker_net_pnl_per_contract", "clv_vs_close_mid_cents", "n", "n_games")}
        mk = ex["maker_cells"]
        maker = {}
        for h in ("7d", "72h", "48h", "24h", "6h", "90m"):
            for rule in ("AT_BID", "ASK_MINUS_2"):
                for q in ("FRONT", "Q500", "THROUGH_ONLY"):
                    c = mk.get(f"V0|moneyline|{h}|{rule}|{q}|all")
                    if c:
                        maker[f"{h}|{rule}|{q}"] = {m: c.get(m) for m in ("fill_prob", "n_orders", "n_games", "price_improvement_vs_close_ask_cents", "profit_per_submitted_contract", "profit_per_filled_contract", "delta_vs_wait_and_take_close", "clv_vs_close_mid_cents", "adverse_selection")}
        out["3_early_limit_order_timing"] = dict(taker_entry_by_horizon=timing, maker_moneyline_V0=maker, chronological_selection=ex["chronological_selection"],
                                                  labels=ex.get("labels"), design=ex.get("design"), simulator_crosscheck=ex.get("simulator_crosscheck_vs_sift_clv"))
    out["4_net_returns_after_fees"] = dict(note="every EV is net of the Kalshi general-schedule fee (taker 0.07 / maker 0.0175 MODELLED) per cent per contract; see sections 2-3 for cells",
                                           integration=itg)
    out["5_chronological_holdout"] = dict(cfb=pick(cfb, "discovery_validation_holdout"), nfl_execution=pick(ex, "chronological_selection"))
    out["6_framework"] = dict(module="sift_research.decision", actions=["BUY_NOW", "LIMIT", "WAIT", "PASS"], integration=itg,
                              shadow_ledger="sift_research.shadow_orders")
    json.dump(out, open(os.path.join(R, "summary.json"), "w"), indent=1, sort_keys=True, allow_nan=False)
    print("wrote summary.json")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--reports", default="reports/outcome_exec"); ap.add_argument("--inventory", default="/home/user/work/inventory_raw.json")
    main(ap.parse_args())
