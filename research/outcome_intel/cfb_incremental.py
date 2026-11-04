#!/usr/bin/env python3
"""CFB 2026: does the SIFT model add information beyond the contemporaneous market mid? (RESEARCH_ONLY; chronological holdout by game.)
usage: python3 -I research/outcome_intel/cfb_incremental.py --root <cfb research-data checkout> --out reports/outcome_intel/cfb_incremental.json
Cells = family x snapshot label (12, all reported); Holm over all 12; negative control per cell (game-shuffled challenger)."""
from __future__ import annotations
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import audit_cfb as A
import incremental as I

LABELS = ("T_3D", "T_24H", "T_6H", "CLOSING")
FAMS = ("moneyline", "spread", "total")


def load_rows(root):
    obs, _ = A.read_jsonl(os.path.join(root, "data/research/observations/*/*.jsonl"))
    sett, _ = A.read_jsonl(os.path.join(root, "data/research/settlements/*/*.jsonl"))
    st = {}
    for r in sett:
        if r["status"] == "settled" and (r["kalshi_market_ticker"] not in st or r["settled_at"] >= st[r["kalshi_market_ticker"]]["settled_at"]):
            st[r["kalshi_market_ticker"]] = r
    out, seen = [], set()
    for x in sorted(obs, key=lambda x: x["observation"]["captured_at"]):
        o = x["observation"]
        if o["coverage_outcome"] != "evaluated" or o.get("model_probability") is None or o.get("market_midpoint") is None:
            continue
        s = st.get(o["kalshi_market_ticker"])
        if not s or A.pdt(o["captured_at"]) >= A.pdt(x["kickoff_utc_at_capture"]):
            continue
        key = (o["kalshi_market_ticker"], o["snapshot_timing"]["label"])
        if key in seen:
            continue
        seen.add(key)
        ay, an = o["executable_yes_price"], o["executable_no_price"]
        if ay is None or an is None or ay + an - 1 > 0.10:
            continue
        out.append(dict(game=o["game_id"], t=x["kickoff_utc_at_capture"], mid=o["market_midpoint"], q=o["model_probability"],
                        y=1 if s["derived_contract_settlement"] == "yes" else 0, fam=o["family"], label=o["snapshot_timing"]["label"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", default="reports/outcome_intel/cfb_incremental.json")
    a = ap.parse_args()
    rows = load_rows(a.root)
    cells = {}
    for f in FAMS:
        for lab in LABELS:
            sub = [r for r in rows if r["fam"] == f and r["label"] == lab]
            c = I.incremental_test(sub)
            c["negative_control_gain_vs_calibrated"] = (I.negative_control(sub).get("gain_vs_calibrated_market_logloss") if c["status"] == "OK" else None)
            cells[f"{f}|{lab}"] = c
    ok = [k for k, c in cells.items() if c["status"] == "OK"]
    adj = I.holm([cells[k]["gain_vs_calibrated_market_logloss"]["p"] for k in ok])
    for k, p in zip(ok, adj):
        cells[k]["holm_p_gain_vs_calibrated"] = float(p)
    res = dict(status="RESEARCH_ONLY", schema="sift-outcome-intel-cfb-incremental/1", rows=len(rows), cells_tried=len(cells), cells_ok=len(ok),
               protocol="train = earliest 2/3 of games by kickoff; holdout = latest 1/3; ridge=1 fixed; one pass; positive gain = challenger better",
               validated_gain_cells=[k for k in ok if cells[k]["holm_p_gain_vs_calibrated"] <= 0.05 and cells[k]["gain_vs_calibrated_market_logloss"]["lo"] > 0],
               cells=cells)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(res, open(a.out, "w"), indent=1, sort_keys=True)
    for k, c in cells.items():
        g = c.get("gain_vs_calibrated_market_logloss")
        print(k, c["status"], c.get("holdout_games"), c.get("n_holdout"), g and "gain %.4f [%.4f, %.4f] holm=%.3f" % (g["mean"], g["lo"], g["hi"], c["holm_p_gain_vs_calibrated"]),
              "| mkt-cal gain %.4f" % c["calibration_gain_of_market_alone_logloss"]["mean"] if g else "")
    print("validated:", res["validated_gain_cells"])


if __name__ == "__main__":
    main()
