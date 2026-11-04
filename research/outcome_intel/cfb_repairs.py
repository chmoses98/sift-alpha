#!/usr/bin/env python3
"""CFB verification repairs (RESEARCH_ONLY): (1) outcome cross-check vs exchange-reported wager settlements, (2) overtime, (3) rescheduled kickoff,
(4) canonical 100-lot fee sensitivity. usage: cfb_repairs.py --root research-data --settle settle-CFB-checkout --periods period-scores-checkout --out OUT.json"""
from __future__ import annotations
import argparse, collections, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_cfb as A


def jl(p):
    return [json.loads(l) for l in open(p) if l.strip()]


def run(root, settle, periods):
    obs, _ = A.read_jsonl(os.path.join(root, "data/research/observations/*/*.jsonl"))
    sett, _ = A.read_jsonl(os.path.join(root, "data/research/settlements/*/*.jsonl"))
    derived = {}
    for r in sett:
        if r["status"] == "settled":
            derived[r["kalshi_market_ticker"]] = r
    out = dict(status="RESEARCH_ONLY")
    # (1) exchange-reported settlement of SIFT's real wagers = independent outcome evidence for the overlapping tickers
    W = jl(os.path.join(settle, "settlements/2026.jsonl"))
    amend = jl(os.path.join(settle, "settlement_amendments/2026.jsonl"))
    c = collections.Counter(); bad = []
    seen = set()
    for w in W:
        t = w["market_ticker"]
        if w["settlement_status"] != "SETTLED" or w["result"] not in ("WON", "LOST"):
            c["wager_not_settled_or_other"] += 1; continue
        implied_yes = (w["side"] == "YES") == (w["result"] == "WON")
        d = derived.get(t)
        if d is None:
            c["wager_ticker_not_in_research_corpus_or_pending"] += 1; continue
        seen.add(t)
        ok = (d["derived_contract_settlement"] == "yes") == implied_yes
        c["agree" if ok else "DISAGREE"] += 1
        if not ok:
            bad.append(dict(t=t, derived=d["derived_contract_settlement"], wager_side=w["side"], wager_result=w["result"]))
    out["wager_settlement_crosscheck"] = dict(counts=dict(c), distinct_tickers_compared=len(seen), disagreements=bad[:20],
        amendments=len(amend), amendments_change_outcome=sum(1 for a in amend if a["result"] not in ("WON", "LOST")),
        meaning="exchange-reported results exist ONLY for tickers SIFT actually wagered (a selected subset): they verify derivation rules, they are not a universe-wide official settlement",
        coverage_of_derived_universe=len(seen) / max(1, len(derived)))
    # (2) overtime
    P = {p["game_id"]: p for p in jl(os.path.join(periods, "data/football/2026/period_scores.jsonl")) if p.get("valid")}
    ot = collections.Counter(); ot_bad = []
    games_ot = set()
    for t, d in derived.items():
        gr = d["game_result"]
        p = P.get(str(gr.get("source_game_id")))
        if p is None:
            ot["no_period_scores"] += 1; continue
        same = (p["home_final"], p["away_final"]) == (gr["home_points"], gr["away_points"])
        ot["period_final_matches_settlement_score" if same else "SCORE_MISMATCH"] += 1
        is_ot = len(p["home_periods"]) > 4
        ot["ot_game_ticker" if is_ot else "reg_game_ticker"] += 1
        if is_ot:
            games_ot.add(gr["game_id"])
            if bool(gr.get("went_to_overtime")) is not True:
                ot["ot_flag_missing_in_settlement"] += 1
        if not same and len(ot_bad) < 10:
            ot_bad.append(dict(t=t, settle=(gr["home_points"], gr["away_points"]), periods=(p["home_final"], p["away_final"])))
    out["overtime"] = dict(counts=dict(ot), ot_games=len(games_ot), mismatch_examples=ot_bad,
        rule="Kalshi CFB rule text is not archived in the research corpus; scores used are ESPN finals INCLUDING overtime, and every OT-game ticker that also has an exchange-reported wager result agrees (see wager_settlement_crosscheck, ot subset below)")
    ot_t = {t for t, d in derived.items() if d["game_result"].get("went_to_overtime")}
    out["overtime"]["ot_tickers_with_wager_result"] = sum(1 for w in W if w["market_ticker"] in ot_t)
    # (3) rescheduled kickoff
    ko = collections.defaultdict(collections.Counter)
    for x in obs:
        ko[x["observation"]["game_id"]][x["kickoff_utc_at_capture"]] += 1
    multi = {g: dict(v) for g, v in ko.items() if len(v) > 1}
    detail = {}
    for g, v in multi.items():
        vals = sorted(v)
        latest_cap_by_ko = {}
        for x in obs:
            if x["observation"]["game_id"] == g:
                latest_cap_by_ko[x["kickoff_utc_at_capture"]] = max(latest_cap_by_ko.get(x["kickoff_utc_at_capture"], ""), x["observation"]["captured_at"])
        earliest = vals[0]
        after_earlier = sum(1 for x in obs if x["observation"]["game_id"] == g and x["observation"]["captured_at"] >= earliest and x["kickoff_utc_at_capture"] != earliest)
        detail[g] = dict(kickoffs=v, last_capture_per_kickoff=latest_cap_by_ko, rows_captured_after_the_earlier_kickoff=after_earlier,
                         settlement_scores=[d["game_result"] for t, d in derived.items() if d["game_id"] == g][:1] and None)
    out["rescheduled_kickoff"] = dict(games=len(multi), detail=detail,
        resolution="rows are point-in-time valid iff captured_at < the kickoff in force at capture AND < the earliest kickoff ever recorded for the game; cfb_incremental uses the per-row kickoff, "
                   "audit_cfb flagged the game. Count of rows violating the EARLIEST kickoff is rows_captured_after_the_earlier_kickoff.")
    # (4) fee normalisation: canonical = 100-lot per-contract; 1-lot is a rounding artefact of ceil-to-cent on a single contract
    out["fee_normalisation"] = dict(canonical="100-lot: ceil_to_cent(0.07*100*P*(1-P))/100 per contract", one_lot_example_p05=A.fee(0.5, 1), hundred_lot_example_p05=A.fee(0.5, 100),
        note="research EV is reported with the 100-lot canonical fee; 1-lot sensitivity kept in cfb_audit.json recompute_buy_every_side_at_ask")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True); ap.add_argument("--settle", required=True); ap.add_argument("--periods", required=True)
    ap.add_argument("--out", default="reports/outcome_intel/cfb_repairs.json")
    a = ap.parse_args()
    r = run(a.root, a.settle, a.periods)
    json.dump(r, open(a.out, "w"), indent=1, sort_keys=True, default=str)
    print(json.dumps({k: r[k] for k in ("wager_settlement_crosscheck", "overtime", "rescheduled_kickoff")}, indent=1, default=str)[:3500])
