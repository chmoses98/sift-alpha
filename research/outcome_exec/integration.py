#!/usr/bin/env python3
"""Integration: market selection x execution (research only). Joins walk-forward model probabilities (nfl_outcome.py) with the
simulated order table (nfl_execution.py) and asks, per opportunity, what ``sift_research.decision.decide`` would have done
versus fixed policies -- using ONLY parameters estimated on the discovery weeks, evaluated on validation and holdout.

usage: integration.py [--probs P.jsonl] [--orders O.jsonl] [--out reports/outcome_exec/integration.json] [--horizon 24h]
All fills are SIMULATED_FROM_TAPE (queue = scenario); UNCERTAIN fills are excluded, and the excluded share is reported.
"""
import argparse, json, math, os, sys
from collections import defaultdict
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from sift_research import decision as D, fees, stats, STATUS

HORIZONS = ["7d", "72h", "48h", "24h", "6h", "90m"]
SPLIT = lambda wk: "discovery" if wk <= 6 else ("validation" if wk <= 12 else "holdout")
QUEUES = {"central": "Q500", "optimistic": "FRONT", "conservative": "THROUGH_ONLY"}
CONTRACTS = 10


def load(probs_path, orders_path, horizon):
    opps = {}
    for l in open(probs_path):
        r = json.loads(l)
        if r["family"] != "moneyline" or r.get("model_p_yes") is None or r.get("outcome_yes") is None:
            continue
        h = r["horizons"].get(horizon) or {}
        if h.get("ask_yes") is None or h.get("bid_yes") is None:
            continue
        a, b = float(h["ask_yes"]), float(h["bid_yes"])
        if a > 1.5:  # cents -> dollars if needed
            a, b = a / 100, b / 100
        opps[r["ticker"]] = dict(ticker=r["ticker"], game=r["game_id"], week=r["week"], split=SPLIT(r["week"]), p_model=float(r["model_p_yes"]),
                                 ask=a, bid=b, mid=(a + b) / 2, win=int(r["outcome_yes"]), orders={})
    for l in open(orders_path):
        r = json.loads(l)
        if r["family"] != "moneyline" or r["horizon"] != horizon or not r["rule"].startswith("ASK_MINUS") or r["ticker"] not in opps:
            continue
        k = int(r["rule"].split("_")[-1])
        opps[r["ticker"]]["orders"][(k, r["queue_assumption"])] = dict(status=r["fill_status"], filled=r["filled"], limit=r["limit"] / 100.0)
    return list(opps.values())


def fill_table(rows, queue):
    """Discovery-only: P(fill), P(fill) lower/upper over determinate orders by cents below ask; adverse selection."""
    f, n, wf, wu = defaultdict(float), defaultdict(int), [], []
    for o in rows:
        for (k, q), od in o["orders"].items():
            if q != queue or od["status"] == "UNCERTAIN":
                continue
            n[k] += 1
            fr = od["filled"] / CONTRACTS
            f[k] += fr
            (wf if fr > 0 else wu).append(o["win"])
    tab = {k: f[k] / n[k] for k in n if n[k] >= 20}
    adv = (np.mean(wu) - np.mean(wf)) if wf and wu else 0.0
    return tab, max(0.0, float(adv)), {k: n[k] for k in n}


def realised(o, action, limit_k, queue, p_cal_fn):
    """Per-contract net P&L of an action, or None if the evidence is UNCERTAIN."""
    if action == D.PASS:
        return 0.0
    if action == D.BUY_NOW:
        return float(o["win"] - o["ask"] - fees.fee_per_contract(o["ask"], CONTRACTS, "taker"))
    if action == D.WAIT:
        ask90 = o.get("ask90")
        if ask90 is None:
            return None
        take = p_cal_fn(o) - ask90 - float(fees.fee_per_contract(ask90, CONTRACTS, "taker")) > 0
        return float(o["win"] - ask90 - fees.fee_per_contract(ask90, CONTRACTS, "taker")) if take else 0.0
    od = o["orders"].get((limit_k, queue))
    if od is None or od["status"] == "UNCERTAIN":
        return None
    fr = od["filled"] / CONTRACTS
    return fr * float(o["win"] - od["limit"] - fees.fee_per_contract(od["limit"], CONTRACTS, "maker"))


def summarise(vals, games):
    v = [x for x in vals if x is not None]
    if not v:
        return dict(n=0)
    g = [gg for x, gg in zip(vals, games) if x is not None]
    r = stats.cluster_bootstrap(v, g, n_boot=1000)
    r["n_excluded_uncertain"] = sum(x is None for x in vals)
    return {k: (round(x * 100, 3) if k in ("mean", "lo", "hi") else x) for k, x in r.items()}  # cents


def main(a):
    rows = load(a.probs, a.orders, a.horizon)
    disc = [o for o in rows if o["split"] == "discovery"]
    # asks at 90m for the WAIT action come from the probs file horizon "90m"
    ask90 = {}
    for l in open(a.probs):
        r = json.loads(l)
        h = (r.get("horizons") or {}).get("90m") or {}
        if r["family"] == "moneyline" and h.get("ask_yes") is not None:
            v = float(h["ask_yes"]); ask90[r["ticker"]] = v / 100 if v > 1.5 else v
    for o in rows:
        o["ask90"] = ask90.get(o["ticker"])
    # calibration of the model against the market on discovery: outcome - mid = beta * (model - mid)
    x = np.array([o["p_model"] - o["mid"] for o in disc]); y = np.array([o["win"] - o["mid"] for o in disc])
    beta = float(np.clip((x @ y) / (x @ x), 0, 1)) if len(x) and (x @ x) > 0 else 0.0
    rms_gap = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.05
    out = dict(status=STATUS, horizon=a.horizon, n_opportunities=len(rows), by_split={s: sum(o["split"] == s for o in rows) for s in ("discovery", "validation", "holdout")},
               discovery_calibration=dict(shrink_beta=round(beta, 4), rms_model_minus_mid=round(rms_gap, 4), n=len(disc),
                                          note="p_cal = mid + beta*(model-mid); beta fitted on discovery only (OLS through origin, clipped to [0,1])"),
               scenarios={})
    for name, queue in QUEUES.items():
        tab, adv, ncell = fill_table(disc, queue)
        ep = D.ExecParams(fill_prob=tab, fill_prob_lo={k: v * 0.5 for k, v in tab.items()}, adverse_selection=adv,
                          drift_mean=0.0, drift_sd=0.02, risk_aversion=0.5, min_lcb=0.0)
        pcal = lambda o: o["mid"] + beta * (o["p_model"] - o["mid"])
        sc = dict(queue_assumption=queue, fill_table=tab, adverse_selection=round(adv, 4), fill_cells_n=ncell, policies={})
        for split in ("validation", "holdout"):
            ev = [o for o in rows if o["split"] == split]
            games = [o["game"] for o in ev]
            pol = defaultdict(list)
            dec_counts = defaultdict(int)
            for o in ev:
                opp = D.Opportunity(p=pcal(o), p_se=max(rms_gap, 0.01), bid=o["bid"], ask=o["ask"], hours_to_kickoff=0)
                dd = D.decide(opp, ep)
                act = dd["recommended"]
                dec_counts[act] += 1
                k = None
                if act == D.LIMIT:
                    k = int(round((o["ask"] - dd["limit"]) * 100))
                pol["FRAMEWORK"].append(realised(o, act, k, queue, pcal))
                pol["ALWAYS_BUY_NOW"].append(realised(o, D.BUY_NOW, None, queue, pcal))
                pol["ALWAYS_LIMIT_ASK_MINUS_2"].append(realised(o, D.LIMIT, 2, queue, pcal))
                pol["ALWAYS_WAIT_TO_90M"].append(realised(o, D.WAIT, None, queue, pcal))
                gate = pcal(o) - o["ask"] - float(fees.fee_per_contract(o["ask"], CONTRACTS, "taker")) > 0
                pol["MODEL_GATED_BUY_NOW"].append(realised(o, D.BUY_NOW, None, queue, pcal) if gate else 0.0)
                raw = o["p_model"] - o["ask"] - float(fees.fee_per_contract(o["ask"], CONTRACTS, "taker")) > 0.02
                pol["RAW_MODEL_GAP_GT_2C_BUY_NOW"].append(realised(o, D.BUY_NOW, None, queue, pcal) if raw else 0.0)
                pol["PASS"].append(0.0)
            sc["policies"][split] = dict(decisions=dict(dec_counts), **{p: summarise(v, games) for p, v in pol.items()})
        out["scenarios"][name] = sc
    out["reading"] = ("Per-contract net P&L in cents after modelled fees; 95% CI by game cluster. The framework is judged on whether it avoids the "
                      "loss of unconditional buying and on any positive net EV of the actions it does take; a PASS-heavy result with mean ~0 means "
                      "no validated edge was found, not that the framework made money. Nothing here is a promotion decision.")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(out, open(a.out, "w"), indent=1, sort_keys=True, allow_nan=False)
    print("wrote", a.out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--probs", default="/home/user/work/nfl_model_probs.jsonl")
    ap.add_argument("--orders", default="/home/user/work/nfl_exec_orders.jsonl")
    ap.add_argument("--out", default="reports/outcome_exec/integration.json")
    ap.add_argument("--horizon", default="24h")
    main(ap.parse_args())
