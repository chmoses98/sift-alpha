#!/usr/bin/env python3
"""Validate sift_research.decision's execution predictions out of sample on the NFL 2025 backfill (research only).
The fair value p is the market-implied placement mid (zero model edge: PR #25 found no model that beats the market), so every predicted EV difference between
actions is a pure EXECUTION prediction.  ExecParams (fill table, drift, adverse selection) are fitted on discovery weeks (1-6) ONLY and scored on validation (7-12) and
holdout (13+) against the realised settlement-free close-mid mark, game-clustered.  usage: validate_decision.py --out reports/exec_track/decision_validation.json"""
import argparse, json, os, sys
import numpy as np
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from research.exec_track import nfl_study as NS            # noqa: E402
from sift_exec import fees as FE, study as ST              # noqa: E402
from sift_research import decision as D, nfl25 as N        # noqa: E402

H = "24h"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", default=N.BACKFILL); ap.add_argument("--games", default=N.GAMES_CSV); ap.add_argument("--cache", default=None)
    ap.add_argument("--out", default="reports/exec_track/decision_validation.json")
    a = ap.parse_args(argv)
    ticks = NS.load_ticks(a.backfill, a.games, a.cache)
    rows, _ = ST.build_rows(ticks, horizons={H: ST.HORIZONS[H]}, rules=[f"ASK_MINUS_{k}" for k in range(1, 6)], queues={"Q500": ST.QUEUES["Q500"]})
    rows = [r for r in rows if r["family"] == "moneyline"]
    out = dict(version="sift-exec-decision-validation/1", status="RESEARCH_ONLY", horizon=H, queue="Q500", p="placement mid (zero model edge)", maker_scenario={})
    for sc, coef in FE.SCENARIOS.items():
        ev_lo, ev_hi = ST.evaluate(rows, coef, which="lo"), ST.evaluate(rows, coef, which="hi")
        k_of = np.array([int(r["rule"].rsplit("_", 1)[1]) for r in rows]); split = np.array([r["split"] for r in rows]); game = np.array([r["game"] for r in rows])
        mid = np.array([(r["bid"] + r["ask"]) / 2 for r in rows]); ask = np.array([r["ask"] for r in rows], float); cmid = ev_lo["cmid"]
        res_ix = np.array([r["filled_lo"] == r["filled_hi"] for r in rows])
        disc = split == "discovery"
        fp, fp_lo, drift = {}, {}, float(np.mean(ev_lo["cask"][disc] - ask[disc]) / 100)
        adv_num = []
        for k in range(1, 6):
            m = disc & (k_of == k)
            r_ = m & res_ix
            if r_.sum() < 20:
                continue
            fp[k] = float((ev_lo["filled"][r_] / ST.QTY).mean()); fp_lo[k] = float((ev_lo["filled"][m] / ST.QTY).mean())
            filled = r_ & (ev_lo["filled"] > 0)
            if filled.sum() >= 10:
                adv_num.append(float(((cmid - mid)[r_].mean() - (cmid - mid)[filled].mean()) / 100))
        ep = D.ExecParams(fill_prob=fp, fill_prob_lo=fp_lo, adverse_selection=max(0.0, float(np.mean(adv_num))) if adv_num else 0.0, drift_mean=drift, drift_sd=0.02, maker_coef=coef)
        cal = {}
        for sp in ("validation", "holdout"):
            for k in sorted(fp):
                m = (split == sp) & (k_of == k); r_ = m & res_ix
                if r_.sum() < 20:
                    continue
                # predictions use only decision-time inputs (placement quote, discovery-fitted params)
                pred_fb, pred_now, real_fb, real_now, g = [], [], [], [], []
                for i in np.nonzero(r_)[0]:
                    o = D.Opportunity(p=float(mid[i]) / 100, p_se=0.02, bid=rows[i]["bid"] / 100, ask=rows[i]["ask"] / 100, hours_to_kickoff=24, contracts=ST.QTY)
                    ranked = {x["action"] + str(x["limit"]): x for x in D.decide(o, ep, include_fallback=True)["ranked"]}
                    fb = [x for x in ranked.values() if x["action"] == "LIMIT_FB" and abs(x["limit"] - (rows[i]["ask"] - k) / 100) < 1e-9]
                    bn = [x for x in ranked.values() if x["action"] == "BUY_NOW"]
                    if not fb or not bn:
                        continue
                    pred_fb.append(fb[0]["ev"] * 100); pred_now.append(bn[0]["ev"] * 100); real_fb.append(ev_lo["v_mark_fb"][i]); real_now.append(ev_lo["v_mark_now"][i]); g.append(game[i])
                if len(g) < 20:
                    continue
                pf, pn, rf, rn = map(np.array, (pred_fb, pred_now, real_fb, real_now))
                cal[f"{sp}|ask-{k}c"] = dict(n=len(g), games=len(set(g)), fill_pred=round(fp[k], 4), fill_realised_resolved=NS.num((ev_lo["filled"][r_] / ST.QTY).mean()),
                                              pred_fb_minus_now_c=NS.num((pf - pn).mean()), realised_fb_minus_now_c=NS.ci(rf - rn, g, 51),
                                              pred_ev_error_fb_c=NS.ci(rf - pf, g, 52), pred_ev_error_now_c=NS.ci(rn - pn, g, 53))
        out["maker_scenario"][sc] = dict(params=dict(fill_prob=fp, fill_prob_lo=fp_lo, adverse_selection=ep.adverse_selection, drift_mean=drift), calibration=cal)
    json.dump(out, open(a.out, "w"), indent=1)
    for sc, v in out["maker_scenario"].items():
        for k, c in list(v["calibration"].items())[:4]:
            print(sc, k, c["n"], "fill pred/real", c["fill_pred"], c["fill_realised_resolved"], "FB-NOW pred", c["pred_fb_minus_now_c"], "real", c["realised_fb_minus_now_c"]["mean"] if c["realised_fb_minus_now_c"] else None)


if __name__ == "__main__":
    main()
