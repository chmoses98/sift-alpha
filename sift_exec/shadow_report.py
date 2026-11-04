"""Matched, equal-exposure comparison of BUY_NOW / WAIT / LIMIT / LIMIT_FB / PASS from a shadow-order ledger (research only).

Decisions are MATCHED: one decision snapshot (contract, horizon) carries every tactic, so differences are execution, not selection.  Fill status is a range:
  lo = confirmed through-print (queue-independent), central = behind the DISPLAYED queue, up = front-of-queue possible.  Unfilled LIMIT_FB remainder is taken at the close ask
  (equal exposure); plain LIMIT exposure is the fill only (reported per submitted contract and per acquired contract).  Values are cents per contract, all-in of fees
  (taker 0.07 always; maker scenarios M0/M25/M100), marked at the close mid (settlement-free) and, when the result is known, held to settlement.
"""
from __future__ import annotations
import collections, json
import numpy as np
from . import fees as FE
from sift_research import stats as S

QTY = 10.0


def read(path):
    placed, obs, sett = {}, collections.defaultdict(list), {}
    for l in open(path):
        r = json.loads(l)
        if r["kind"] == "PLACED":
            placed[r["decision_id"]] = r
        elif r["kind"] == "OBSERVED":
            obs[r["decision_id"]].append(r)
        elif r["kind"] == "SETTLED":
            sett[r["decision_id"]] = r
    return placed, obs, sett


def fills(rec, ev):
    lo = max([float(e["size"] or QTY) for e in ev if e["evidence"] == "TAPE_FILL_BOUND_LO"] or [0.0])
    up = max([float(e["size"] or QTY) for e in ev if e["evidence"] in ("TAPE_FILL_BOUND_UP", "TAPE_FILL_BOUND_LO")] or [0.0])
    cen = max([float(e["size"] or 0) for e in ev if e["evidence"] == "TAPE_TOUCH"] + [lo])
    return lo, min(cen, up) if up else lo, max(up, lo)


def cents(price_c, qty, coef):
    return price_c * qty + 100.0 * FE.order_fee(int(price_c), qty, coef) if qty > 1e-9 else 0.0


def table(path, ci_boot=1000):
    placed, obs, sett = read(path)
    groups = collections.defaultdict(dict)      # (ticker, horizon_name) -> tag -> decision
    for did, p in placed.items():
        if did in sett:
            key = (p["ticker"], p["horizon_name"], p["generation"])
            groups[key][(p["action"], p["horizon"].split("|", 1)[1] if "|" in p["horizon"] else "", p["fallback"])] = did
    out = {"n_decisions_placed": len(placed), "n_decisions_closed": sum(1 for d in placed if d in sett),
           "by_generation": dict(collections.Counter(p["generation"] for p in placed.values())),
           "n_win_known": sum(1 for s in sett.values() if s.get("win") is not None), "cells": {}}
    for sc, coef in FE.SCENARIOS.items():
        agg = collections.defaultdict(lambda: collections.defaultdict(list))
        for (tk, hn, gen), d in groups.items():
            w = d.get(("WAIT", "", "NONE"))
            if not w:
                continue
            ps, ss = placed[w], sett[w]
            ca, cb = round(ss["close_ask"] * 100), round(ss["close_bid"] * 100)
            cmid = (ca + cb) / 2.0
            wait_cost = cents(ca, QTY, FE.TAKER_COEF)
            game = ps["game_id"]
            win = ss.get("win")
            bn = d.get(("BUY_NOW", "", "NONE"))
            row = {"WAIT": (cmid * QTY - wait_cost) / QTY}
            if bn:
                a0 = round(placed[bn]["ask"] * 100); row["BUY_NOW"] = (cmid * QTY - cents(a0, QTY, FE.TAKER_COEF)) / QTY
            for (act, rule, fb), did in d.items():
                if act != "LIMIT":
                    continue
                p = placed[did]; lim = round(p["limit"] * 100)
                lo, cen, up = fills(p, obs.get(did, []))
                for nm, f in (("lo", lo), ("central", cen), ("up", up)):
                    mk = cents(lim, f, coef)
                    if fb == "TAKE_AT_CLOSE":
                        row[f"LIMIT_FB|{rule}|{nm}"] = (cmid * QTY - mk - cents(ca, QTY - f, FE.TAKER_COEF)) / QTY
                    else:
                        row[f"LIMIT_NOBET|{rule}|{nm}"] = (cmid * f - mk) / QTY
                        row[f"LIMIT_NOBET_FILLRATE|{rule}|{nm}"] = f / QTY
            row["PASS"] = 0.0
            for k, v in row.items():
                agg[(hn, gen)][k].append((game, v, row["WAIT"]))
        for (hn, gen), kv in sorted(agg.items()):
            for k, L in sorted(kv.items()):
                g = [x[0] for x in L]; v = np.array([x[1] for x in L]); w = np.array([x[2] for x in L])
                if "FILLRATE" in k:
                    out["cells"][f"{sc}|{gen}|{hn}|{k}"] = dict(n=len(L), mean=round(float(v.mean()), 4))
                    continue
                r = S.cluster_bootstrap(v - w, g, ci_boot, 5) if len(set(g)) >= 5 else None
                rv = S.cluster_bootstrap(v, g, ci_boot, 6) if len(set(g)) >= 5 else None
                out["cells"][f"{sc}|{gen}|{hn}|{k}"] = dict(n=len(L), games=len(set(g)), mark_cents=None if rv is None else round(rv["mean"], 4),
                                                           vs_wait_cents=None if r is None else dict(mean=round(r["mean"], 4), ci95=[round(r["lo"], 4), round(r["hi"], 4)]))
    return out
