#!/usr/bin/env python3
"""NFL 2025 equal-exposure entry study (research only).  usage: nfl_study.py --backfill DIR --games games.csv --out reports/exec_track/nfl_study.json
Reproduces/extends PR #25's timing results with: independent loader+fill replay, series-aware maker-fee scenarios, equal-exposure
maker->taker fallback, missed-fill/partial/adverse-selection accounting, determinate-only point estimates with UNCERTAIN bounds,
chronological discovery->validation->holdout selection with game-cluster bootstrap and multiple-comparison control."""
from __future__ import annotations
import argparse, json, os, pickle, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from sift_research import nfl25 as N, stats as S                    # noqa: E402
from sift_exec import fees as FE, nfl_data as D, study as ST        # noqa: E402

N_BOOT = 1000


def num(x):
    x = float(x)
    return None if (np.isnan(x) or np.isinf(x)) else round(x, 4)


def ci(vals, clus, seed=7):
    v = np.asarray(vals, float)
    if len(v) < 5:
        return None
    r = S.cluster_bootstrap(v, clus, n_boot=N_BOOT, seed=seed)
    return dict(mean=num(r["mean"]), lo=num(r["lo"]), hi=num(r["hi"]), p=num(r["p"]), n=r["n"], games=r["n_clusters"])


def load_ticks(backfill, games_csv, cache=None):
    if cache and os.path.exists(cache):
        return pickle.load(open(cache, "rb"))
    idx = N.game_index(N.load_games(games_csv))
    ticks = []
    for s in ("KXNFLGAME", "KXNFLSPREAD"):
        for m in N.load_markets(s, backfill):
            if os.path.exists(os.path.join(backfill, "candles", s, m["ticker"] + ".json")):
                t = D.load_tick(s, m, idx, backfill)
                if t:
                    ticks.append(t)
    if cache:
        pickle.dump(ticks, open(cache, "wb"))
    return ticks


def cell(rows_idx, ev, rows, key):
    """Aggregate one (family,horizon,rule,queue) cell of DETERMINATE orders under one maker coefficient."""
    ix = np.array(rows_idx)
    g = [rows[i]["game"] for i in ix]
    f = ev["filled"][ix]
    filled = f > 0
    out = dict(n_orders=len(ix), n_games=len(set(g)), fill_prob=num(filled.mean()), full_fill=num((f >= ST.QTY - 1e-9).mean()),
               partial_fill=num(((f > 0) & (f < ST.QTY - 1e-9)).mean()), mean_filled_fraction=num((f / ST.QTY).mean()))
    for v in ("mark", "settle"):
        wait, fb, now, nb = ev[f"v_{v}_wait"][ix], ev[f"v_{v}_fb"][ix], ev[f"v_{v}_now"][ix], ev[f"v_{v}_nb"][ix]
        out[f"{v}_fb_minus_wait"] = ci(fb - wait, g, 11)
        out[f"{v}_fb_minus_now"] = ci(fb - now, g, 12)
        out[f"{v}_nobet_per_submitted"] = ci(nb, g, 13)
        out[f"{v}_wait"] = ci(wait, g, 14)
    if filled.sum() >= 5:
        gf = [x for x, k in zip(g, filled) if k]
        # adverse selection: what the SAME fill would have been worth at close mark, filled vs unfilled
        edge = ev["cmid"][ix] - ev["lim"][ix]           # close_mid - limit (cents/contract) if filled at limit
        out["mark_edge_if_filled_cents_filled"] = ci(edge[filled], gf, 15)
        if (~filled).sum() >= 5:
            gu = [x for x, k in zip(g, filled) if not k]
            out["mark_edge_if_filled_cents_unfilled"] = ci(edge[~filled], gu, 16)
            out["adverse_selection_filled_minus_unfilled_cents"] = num(edge[filled].mean() - edge[~filled].mean())
        out["mark_nobet_per_filled_contract_cents"] = num(((ev["cmid"][ix] * f - ev["mk_cost"][ix])[filled]).sum() / f[filled].sum())
        out["settle_nobet_per_filled_contract_cents"] = num(((ev["win"][ix] * 100 * f - ev["mk_cost"][ix])[filled]).sum() / f[filled].sum())
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", default=N.BACKFILL); ap.add_argument("--games", default=N.GAMES_CSV)
    ap.add_argument("--cache", default=None); ap.add_argument("--out", default="reports/exec_track/nfl_study.json")
    a = ap.parse_args(argv)
    ticks = load_ticks(a.backfill, a.games, a.cache)
    rows, audit = ST.build_rows(ticks)
    print("ticks", len(ticks), "rows", len(rows), file=sys.stderr)
    det = [i for i, r in enumerate(rows) if r["determinate"]]
    unc = [i for i, r in enumerate(rows) if not r["determinate"]]
    rep = dict(version="sift-exec-nfl-study/1", status="RESEARCH_ONLY",
               labels=dict(fills="SIMULATED_FROM_TAPE", fees="SCENARIO: taker 0.07 confirmed; maker M0/M25/M100", queue="SCENARIO"),
               design=dict(qty=ST.QTY, horizons_min=ST.HORIZONS, rules=ST.RULES, queues={k: list(v) for k, v in ST.QUEUES.items()},
                           close="last valid quote at/before kickoff-15m (fallback taker price and expiry)", max_spread_c=ST.MAX_SPREAD, splits=ST.SPLITS,
                           maker_fee_scenarios=FE.SCENARIOS, n_boot=N_BOOT, cluster="game"),
               audit={"|".join(k): v for k, v in sorted(audit.items())}, n_rows=len(rows), n_determinate=len(det), n_uncertain=len(unc))
    evs = {name: ST.evaluate(rows, coef) for name, coef in FE.SCENARIOS.items()}
    evs_ub = {"M25_per_fill_ceil": ST.evaluate(rows, FE.MAKER_COEF, "per_fill")}
    groups = defaultdict(list)
    for i in det:
        r = rows[i]
        groups[(r["family"], r["horizon"], r["rule"], r["queue"])].append(i)
    rep["cells"] = {}
    for sc, ev in {**evs, **evs_ub}.items():
        sub = {}
        for (fam, hn, rule, qn), ix in sorted(groups.items()):
            if fam != "moneyline" and sc not in ("M25",):
                continue
            c = cell(ix, ev, rows, None)
            by = defaultdict(list)
            for i in ix:
                by[rows[i]["split"]].append(i)
            c["by_split"] = {sp: cell(v, ev, rows, None) for sp, v in by.items() if sp and len(v) >= 30}
            sub[f"{fam}|{hn}|{rule}|{qn}"] = c
        rep["cells"][sc] = sub
    # taker-only reference cells (no maker fee involved): early taker vs wait, per family/horizon, determinate not required
    tk = {}
    ev = evs["M25"]
    by = defaultdict(list)
    for i, r in enumerate(rows):
        if r["rule"] == "AT_BID" and r["queue"] == "FRONT":
            by[(r["family"], r["horizon"])].append(i)
    for (fam, hn), ix in sorted(by.items()):
        ix = np.array(ix); g = [rows[i]["game"] for i in ix]
        cask = ev["cask"][ix]; ask = ev["ask"][ix]
        tk[f"{fam}|{hn}"] = dict(n=len(ix), games=len(set(g)),
                                 close_ask_minus_early_ask_cents=ci(cask - ask, g, 21),
                                 early_taker_minus_wait_taker_net_cents_mark=ci(ev["v_mark_now"][ix] - ev["v_mark_wait"][ix], g, 22),
                                 early_taker_minus_wait_taker_net_cents_settle=ci(ev["v_settle_now"][ix] - ev["v_settle_wait"][ix], g, 23),
                                 early_taker_net_settle_cents=ci(ev["v_settle_now"][ix], g, 24), wait_taker_net_settle_cents=ci(ev["v_settle_wait"][ix], g, 25))
    rep["taker_reference"] = tk
    # UNCERTAIN bounds on the equal-exposure fallback tactic: all uncertain orders unfilled (=WAIT) vs fully filled at limit
    bnd = {}
    for sc in ("M0", "M25"):
        ev = evs[sc]
        for key in (("moneyline", "24h", "AT_BID", "Q500"), ("moneyline", "24h", "ASK_MINUS_1", "Q500"), ("moneyline", "90m", "ASK_MINUS_1", "Q500")):
            d_ix = groups.get(key, []); u_ix = [i for i in unc if (rows[i]["family"], rows[i]["horizon"], rows[i]["rule"], rows[i]["queue"]) == key]
            if not d_ix and not u_ix:
                continue
            allix = np.array(d_ix + u_ix)
            wait = ev["v_mark_wait"][allix]
            fb_point = ev["v_mark_fb"][allix].copy()
            is_u = np.array([False] * len(d_ix) + [True] * len(u_ix))
            lo = np.where(is_u, wait, fb_point)          # uncertain orders assumed unfilled -> identical to WAIT
            full_cost = np.array([ST.cost_cents(rows[i]["limit"], ST.QTY, sc_coef(sc)) for i in allix])
            hi = np.where(is_u, (ev["cmid"][allix] * ST.QTY - full_cost) / ST.QTY, fb_point)  # assumed fully filled at limit
            bnd["|".join(key) + "|" + sc] = dict(n_determinate=len(d_ix), n_uncertain=len(u_ix),
                                                  delta_vs_wait_lower_bound=num((lo - wait).mean()), delta_vs_wait_upper_bound=num((hi - wait).mean()),
                                                  delta_vs_wait_determinate_only=num((fb_point[~is_u] - wait[~is_u]).mean()) if (~is_u).any() else None)
    rep["uncertain_bounds_naive_no_candle_evidence"] = bnd
    # whole-population bounds (tape-uncertain orders resolved by candle evidence where possible; the rest bracketed 0..QTY)
    pb = {}
    allg = defaultdict(list)
    for i, r in enumerate(rows):
        allg[(r["family"], r["horizon"], r["rule"], r["queue"])].append(i)
    for sc in ("M0", "M25"):
        lo_ev, hi_ev = ST.evaluate(rows, FE.SCENARIOS[sc], which="lo"), ST.evaluate(rows, FE.SCENARIOS[sc], which="hi")
        for key, ix in sorted(allg.items()):
            if key[0] != "moneyline" or key[3] not in ("FRONT", "Q500", "Q5000", "THROUGH_ONLY"):
                continue
            ix = np.array(ix); wait = evs[sc]["v_mark_wait"][ix]
            g = [rows[i]["game"] for i in ix]
            lo = lo_ev["v_mark_fb"][ix] - wait; hi = hi_ev["v_mark_fb"][ix] - wait
            res = np.array([rows[i]["filled_lo"] == rows[i]["filled_hi"] for i in ix])
            cls = defaultdict(int)
            for i in ix:
                cls[rows[i]["candle_class"] if not rows[i]["determinate"] else "TAPE_DETERMINATE"] += 1
            pb[sc + "|" + "|".join(key)] = dict(n=len(ix), games=len(set(g)), resolved_share=num(res.mean()), classes=dict(cls),
                                                 fb_minus_wait_lower=ci(lo, g, 31), fb_minus_wait_upper=ci(hi, g, 32))
    rep["population_bounds"] = pb
    rep["preregistered"] = {sc: prereg(rows, allg, c) for sc, c in FE.SCENARIOS.items()}
    # simulator evidence-class mix
    mix = defaultdict(int)
    for i in det:
        r = rows[i]
        if r["family"] == "moneyline" and r["queue"] == "Q500":
            for _, q, e in r["fills"]:
                mix[e] += 1
    rep["fill_evidence_counts_moneyline_Q500"] = dict(mix)
    json.dump(rep, open(a.out, "w"), indent=1, sort_keys=True)
    print("wrote", a.out, file=sys.stderr)
    return rows, evs


def prereg(rows, allg, coef=FE.MAKER_COEF):
    """Pre-specified protocol (frozen BEFORE looking at validation/holdout; mirrored in docs/EXECUTION_RESEARCH.md):
      population = ALL valid moneyline contract-sides (tape-uncertain orders included; their fill status is bounded by candle evidence), central queue Q500,
                   maker scenario M25 (the schedule-supported coefficient), 6 horizons x 8 rules = 48 cells
      claim R    = equal-exposure maker->taker fallback beats WAIT:  fb - wait > 0          (judged on the CONSERVATIVE fill lower bound)
      claim A    = absolute net value of the don't-bet-if-unfilled tactic per submitted contract > 0  (must be > 0 under BOTH fill bounds)
      metric     = settlement-free close-mid mark, cents/contract, all-in of fees
      selection  = top discovery mean per claim;  tests = ONE validation test, then ONE holdout test only if validation passes (one-sided p<0.05, game-cluster
                   bootstrap);  Holm and BH over the 48 validation tests are reported.
    """
    lo_ev, hi_ev = ST.evaluate(rows, coef, which="lo"), ST.evaluate(rows, coef, which="hi")
    cells = {k: v for k, v in allg.items() if k[0] == "moneyline" and k[3] == "Q500"}
    claims = {"R_fb_minus_wait_lower_bound": lambda i: lo_ev["v_mark_fb"][i] - lo_ev["v_mark_wait"][i],
              "A_nobet_per_submitted_lower_fill_bound": lambda i: lo_ev["v_mark_nb"][i],
              "A_nobet_per_submitted_upper_fill_bound": lambda i: hi_ev["v_mark_nb"][i]}
    out = {}
    for claim, series in claims.items():
        per = {}
        for k, ix in cells.items():
            by = defaultdict(list)
            for i in ix:
                by[rows[i]["split"]].append(i)
            if all(len(by[sp]) >= 30 for sp in ("discovery", "validation", "holdout")):
                per[k] = {sp: (series(np.array(by[sp])), [rows[i]["game"] for i in by[sp]]) for sp in ("discovery", "validation", "holdout")}
        disc = {k: float(np.mean(v["discovery"][0])) for k, v in per.items()}
        best = max(disc, key=disc.get)
        ks = list(per)

        def one_sided(k, sp):
            """H1: mean > 0.  p = half the two-sided SHIFT-method bootstrap p (resampling games; floor 1/(B+1)) when the mean is positive, else 1 - p/2.
            ``ci95`` is the two-sided percentile interval; one-sided p < 0.05 corresponds to the lower end of the 90% interval (``ci90``) exceeding 0,
            so a holdout can have ci95 lower < 0 and p_one_sided < 0.05 without contradiction."""
            r = S.cluster_bootstrap(per[k][sp][0], per[k][sp][1], N_BOOT, 42)
            r90 = S.cluster_bootstrap(per[k][sp][0], per[k][sp][1], N_BOOT, 42, alpha=0.10)
            return r, r90, (r["p"] / 2 if r["mean"] > 0 else 1 - r["p"] / 2)
        p1 = [one_sided(k, "validation")[2] for k in ks]            # ONE-sided p for every cell, so Holm/BH match the test applied to the selected cell
        holm, bh = S.holm(p1), S.benjamini_hochberg(p1)
        rv, rv90, pv1 = one_sided(best, "validation")
        rh, rh90, ph1 = one_sided(best, "holdout")
        out[claim] = dict(cells_in_family=len(per), selected=dict(horizon=best[1], rule=best[2]), discovery_mean=num(disc[best]),
                          validation=dict(mean=num(rv["mean"]), ci95=[num(rv["lo"]), num(rv["hi"])], ci90=[num(rv90["lo"]), num(rv90["hi"])], p_one_sided=num(pv1), n=rv["n"], games=rv["n_clusters"]),
                          validation_holm_adj_p_selected=num(holm[ks.index(best)]), validation_bh_q_selected=num(bh[ks.index(best)]),
                          cells_passing_validation_holm_0p05=int((holm < 0.05).sum()), cells_with_positive_validation_mean=int(sum(float(np.mean(v["validation"][0])) > 0 for v in per.values())),
                          validation_passed=bool(holm[ks.index(best)] < 0.05 and rv["mean"] > 0),
                          holdout=dict(mean=num(rh["mean"]), ci95=[num(rh["lo"]), num(rh["hi"])], ci90=[num(rh90["lo"]), num(rh90["hi"])], p_one_sided=num(ph1), n=rh["n"], games=rh["n_clusters"],
                                       tested_under_protocol=bool(holm[ks.index(best)] < 0.05 and rv["mean"] > 0), passed=bool(holm[ks.index(best)] < 0.05 and rv["mean"] > 0 and ph1 < 0.05 and rh["mean"] > 0)))
    return out


def sc_coef(name):
    return FE.SCENARIOS[name]


if __name__ == "__main__":
    main()
