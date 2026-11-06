#!/usr/bin/env python3
"""Matched before/after replay of Alpha's execution study on the recovered NFL tape (RESEARCH_ONLY; every fill is SIMULATED_FROM_TAPE, nothing is placed).

The SAME decisions (contract-side x horizon x rule x queue, identical quotes from the same candles) are evaluated twice:
  BEFORE  the archived legacy tape only (``trades/``, capped at 10,000 newest prints; a family with no archive has UNKNOWN history, never "empty")
  AFTER   the audited recovered tape (``trades_v2/`` + ``tape_meta.jsonl``; kickoff-anchored, candle-verified when complete) wherever one exists
Reported: which decisions become evaluable; fill-class transitions (supported fill / supported no-fill / uncertain); queue-dependence of supported fills; spread
paid vs resting; early entry vs waiting; limit with taker fallback; maker-fee scenarios and fee-evidence grade per series; ABSOLUTE net EV per contract held to
settlement (not savings relative to another losing tactic) with game-clustered CIs; chronological discovery -> validation -> untouched holdout selection with a
Bonferroni correction.  Population = every valid contract-side (no selection signal), so this isolates execution cost; it never claims model alpha.
Label: RETROSPECTIVE_BACKFILL_REPLAY.  It is a separate series from the PROSPECTIVE shadow ledger and must never be merged into it.

usage: recovery_replay.py --backfill DIR --games games.csv --out report.json [--series S,...] [--fees-dir DIR] [--population]"""
from __future__ import annotations
import argparse, hashlib, json, os, sys
from collections import Counter, defaultdict
import numpy as np
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from sift_research import nfl25 as N, stats as S                                   # noqa: E402
from sift_exec import fees as FE, nfl_data as D, study as ST                        # noqa: E402

N_BOOT = 1000
LABEL = "RETROSPECTIVE_BACKFILL_REPLAY"
MIN_ORDERS, MIN_GAMES = 30, 10


def num(x):
    x = float(x)
    return None if (np.isnan(x) or np.isinf(x)) else round(x, 4)


def ci(vals, clus, seed=7):
    v = np.asarray(vals, float)
    if len(v) < 5 or len(set(clus)) < 3:
        return None
    r = S.cluster_bootstrap(v, clus, n_boot=N_BOOT, seed=seed)
    return dict(mean=num(r["mean"]), lo=num(r["lo"]), hi=num(r["hi"]), p=num(r["p"]), n=int(r["n"]), games=int(r["n_clusters"]))


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


def usable_v2(backfill):
    """Tickers with an audited, kickoff-anchored, non-empty recovered tape (the cohort)."""
    out = []
    for t, m in D.v2_meta(backfill).items():
        if m.get("anchor_kind") in D.V2_ANCHORS and m.get("status") in D.V2_STATUSES and m.get("total_prints_on_disk"):
            out.append((m["series"], t))
    return sorted(out)


def load_ticks(backfill, idx, wanted, mode):
    """Ticks for ``wanted`` = {(series, ticker)}; None if the contract has no quote source or cannot be joined to a game."""
    ticks = []
    for s in sorted({s for s, _ in wanted}):
        for m in N.load_markets(s, backfill):
            if (s, m["ticker"]) in wanted:
                t = D.load_tick(s, m, idx, backfill, mode)
                if t:
                    ticks.append(t)
    return ticks


def order_class(r):
    if r["filled_lo"] == r["filled_hi"]:
        return "FILL_SUPPORTED" if r["filled_lo"] > 0 else "NO_FILL_SUPPORTED"
    return "UNCERTAIN"


def key(r):
    return (r["ticker"], r["side"], r["horizon"], r["rule"], r["queue"])


def compare(before, after):
    """Transition counts over IDENTICAL decision keys."""
    b, a = {key(r): r for r in before}, {key(r): r for r in after}
    ks = sorted(set(b) & set(a))
    out = dict(orders_before=len(b), orders_after=len(a), identical_order_ids=len(ks), only_before=len(set(b) - set(a)), only_after=len(set(a) - set(b)))
    tr = Counter((order_class(b[k]), order_class(a[k])) for k in ks)
    out["transitions"] = {f"{x}->{y}": n for (x, y), n in sorted(tr.items())}
    dec_b = {k[:3]: b[k]["determinate"] for k in ks}
    dec_a = {k[:3]: a[k]["determinate"] for k in ks}
    out["decisions"] = len(dec_b)
    out["decisions_determinate_before"] = int(sum(dec_b.values()))
    out["decisions_determinate_after"] = int(sum(dec_a.values()))
    out["decisions_newly_evaluable"] = int(sum(1 for k in dec_b if not dec_b[k] and dec_a[k]))
    out["decisions_lost_evaluability"] = int(sum(1 for k in dec_b if dec_b[k] and not dec_a[k]))
    unc_b = sum(1 for k in ks if order_class(b[k]) == "UNCERTAIN")
    unc_a = sum(1 for k in ks if order_class(a[k]) == "UNCERTAIN")
    out["orders_uncertain_before"], out["orders_uncertain_after"] = unc_b, unc_a
    out["uncertainty_resolved_share"] = num((unc_b - unc_a) / unc_b) if unc_b else None
    # a supported fill is queue-INDEPENDENT only if it came from a print THROUGH our price
    ev = Counter()
    for k in ks:
        r = a[k]
        if order_class(r) == "FILL_SUPPORTED" and r["determinate"]:
            tags = {f[2] for f in r["fills"]}
            ev["through_only" if tags <= {"THROUGH"} else "needs_queue_to_drain"] += 1
    out["supported_fills_after_by_evidence"] = dict(ev)
    changed = [k for k in ks if order_class(b[k]) != order_class(a[k])]
    out["orders_changed_class"] = len(changed)
    # direction of each change for orders that were uncertain before
    fl = Counter()
    for k in ks:
        if order_class(b[k]) == "UNCERTAIN":
            fl[order_class(a[k])] += 1
    out["previously_uncertain_now"] = dict(fl)
    return out


def tactic_values(rows, ev, ix):
    """Absolute per-contract values (cents) of every equal-exposure tactic on orders ``ix`` for one fee scenario."""
    return {"BUY_NOW": ev["v_settle_now"][ix], "WAIT": ev["v_settle_wait"][ix], "LIMIT_FB": ev["v_settle_fb"][ix], "LIMIT_NB_per_submitted": ev["v_settle_nb"][ix],
            "mark_BUY_NOW": ev["v_mark_now"][ix], "mark_WAIT": ev["v_mark_wait"][ix], "mark_LIMIT_FB": ev["v_mark_fb"][ix]}


def economics(rows, det_ix):
    """family|horizon|rule|queue -> absolute EV under M0/M25/M100 (determinate orders only)."""
    evs = {n: ST.evaluate(rows, c) for n, c in FE.SCENARIOS.items()}
    groups = defaultdict(list)
    for i in det_ix:
        r = rows[i]
        groups[(r["family"], r["horizon"], r["rule"], r["queue"])].append(i)
    out = {}
    for (fam, hn, rule, qn), ix in sorted(groups.items()):
        ix = np.array(ix); g = [rows[i]["game"] for i in ix]
        if len(ix) < 5:
            continue
        f = evs["M25"]["filled"][ix]
        cell = dict(n_orders=len(ix), n_games=len(set(g)), fill_prob=num((f > 0).mean()), full_fill=num((f >= ST.QTY - 1e-9).mean()),
                    half_spread_c=num(np.mean([(rows[i]["ask"] - rows[i]["bid"]) / 2.0 for i in ix])),
                    taker_fee_per_contract_c=num(np.mean(evs["M25"]["tk_now"][ix] / ST.QTY - evs["M25"]["ask"][ix])))
        for sc, ev in evs.items():
            tv = tactic_values(rows, ev, ix)
            cell[sc] = {k: ci(v, g, 11 + j) for j, (k, v) in enumerate(tv.items())}
            cell[sc]["LIMIT_FB_minus_WAIT"] = ci(tv["LIMIT_FB"] - tv["WAIT"], g, 31)
            cell[sc]["BUY_NOW_minus_WAIT"] = ci(tv["BUY_NOW"] - tv["WAIT"], g, 32)
        out[f"{fam}|{hn}|{rule}|{qn}"] = cell
    return out


def holdout_protocol(rows, det_ix, scenario="M25"):
    """Per family: pick the (horizon, tactic) with the best ABSOLUTE mean value on discovery+validation (weeks 1-12), then evaluate it ONCE on the untouched
    holdout (weeks >= 13), Bonferroni-corrected over the candidates.  Positive absolute net EV is claimed only if the holdout CI excludes 0 after correction."""
    ev = ST.evaluate(rows, FE.SCENARIOS[scenario])
    by = defaultdict(list)
    for i in det_ix:
        by[rows[i]["family"]].append(i)
    out = {}
    for fam, ix in sorted(by.items()):
        ix = np.array(ix)
        sp = np.array([rows[i]["split"] or "" for i in ix])
        sel_ix, ho_ix = ix[(sp == "discovery") | (sp == "validation")], ix[sp == "holdout"]
        cands = defaultdict(list)
        for i in sel_ix:
            r = rows[i]
            cands[(r["horizon"], r["rule"], r["queue"], "LIMIT_FB")].append(i)
            if r["rule"] == "AT_BID" and r["queue"] == "FRONT":
                cands[(r["horizon"], "-", "-", "BUY_NOW")].append(i)
                cands[(r["horizon"], "-", "-", "WAIT")].append(i)
        col = {"LIMIT_FB": "v_settle_fb", "BUY_NOW": "v_settle_now", "WAIT": "v_settle_wait"}
        best, bv = None, -1e9
        usable = 0
        for k, v in cands.items():
            gs = {rows[i]["game"] for i in v}
            if len(v) < MIN_ORDERS or len(gs) < MIN_GAMES:
                continue
            usable += 1
            m = float(np.mean(ev[col[k[3]]][np.array(v)]))
            if m > bv:
                best, bv = k, m
        res = dict(selection_orders=int(len(sel_ix)), selection_games=len({rows[i]["game"] for i in sel_ix}), holdout_orders=int(len(ho_ix)),
                   holdout_games=len({rows[i]["game"] for i in ho_ix}), candidates_evaluable=usable)
        if best is None:
            res["status"] = "INSUFFICIENT_SELECTION_SAMPLE"
        else:
            hz, rule, qn, tac = best
            hv = [i for i in ho_ix if rows[i]["horizon"] == hz and (tac != "LIMIT_FB" or (rows[i]["rule"] == rule and rows[i]["queue"] == qn))
                  and (tac == "LIMIT_FB" or (rows[i]["rule"] == "AT_BID" and rows[i]["queue"] == "FRONT"))]
            res.update(selected=dict(horizon=hz, rule=rule, queue=qn, tactic=tac), selection_mean_cents=num(bv))
            hg = {rows[i]["game"] for i in hv}
            if len(hv) < MIN_ORDERS or len(hg) < MIN_GAMES:
                res["status"] = "INSUFFICIENT_HOLDOUT_SAMPLE"; res["holdout_n"] = len(hv); res["holdout_games"] = len(hg)
            else:
                c = ci(ev[col[tac]][np.array(hv)], [rows[i]["game"] for i in hv], 41)
                p_adj = min(1.0, (c["p"] or 1.0) * max(usable, 1))
                res.update(holdout=c, p_bonferroni=num(p_adj),
                           status="POSITIVE_ABSOLUTE_NET_EV_OUT_OF_SAMPLE" if (c["lo"] is not None and c["lo"] > 0 and p_adj < 0.05) else "NOT_POSITIVE_AFTER_FEES")
        out[fam] = res
    return out


def fee_grades(series, fees_dir, schedule_path):
    if not fees_dir or not os.path.isdir(fees_dir):
        return {s: dict(maker_evidence="UNVERIFIED", note="no fee archive supplied to this replay") for s in series}
    arch, _ = FE.load_fee_archive(fees_dir)
    sched = json.load(open(schedule_path)).get("series", {}) if schedule_path and os.path.exists(schedule_path) else {}
    return {s: {k: v for k, v in FE.series_fee(s, arch, sched).__dict__.items()} for s in series}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", default=N.BACKFILL); ap.add_argument("--games", default=N.GAMES_CSV)
    ap.add_argument("--out", default="reports/exec_track/recovery_replay.json")
    ap.add_argument("--fees-dir"); ap.add_argument("--fee-schedule")
    ap.add_argument("--alpha-sha", default=""); ap.add_argument("--edge-sha", default="")
    ap.add_argument("--population", action="store_true", help="also report, for the whole legacy moneyline/spread population, how many decisions the legacy tape could evaluate")
    a = ap.parse_args(argv)
    idx = N.game_index(N.load_games(a.games))
    cohort = set(usable_v2(a.backfill))
    before_t, after_t = load_ticks(a.backfill, idx, cohort, "legacy"), load_ticks(a.backfill, idx, cohort, "auto")
    rows_b, aud_b = ST.build_rows(before_t)
    rows_a, aud_a = ST.build_rows(after_t)
    fams = sorted({r["family"] for r in rows_a})
    rep = dict(version="sift-exec-recovery-replay/1", status="RESEARCH_ONLY", label=LABEL, fills="SIMULATED_FROM_TAPE (never an execution)",
               pinned=dict(alpha_sha=a.alpha_sha, edge_finder_sha=a.edge_sha, games_csv_sha256=sha(a.games),
                           tape_meta_sha256=sha(os.path.join(a.backfill, "tape_meta.jsonl")),
                           cohort_tapes={t: dict(series=s, sha256=sha(os.path.join(a.backfill, "trades_v2", s, t + ".jsonl")),
                                                 anchor_ts=D.v2_meta(a.backfill)[t]["anchor_ts"], anchor_kind=D.v2_meta(a.backfill)[t]["anchor_kind"],
                                                 status=D.v2_meta(a.backfill)[t]["status"], prints=D.v2_meta(a.backfill)[t]["total_prints_on_disk"]) for s, t in sorted(cohort)}),
               design=dict(qty=ST.QTY, horizons_min=ST.HORIZONS, rules=ST.RULES, queues={k: list(v) for k, v in ST.QUEUES.items()}, splits=ST.SPLITS,
                           maker_fee_scenarios=FE.SCENARIOS, taker_coef=FE.TAKER_COEF, n_boot=N_BOOT, cluster="game",
                           min_orders=MIN_ORDERS, min_games=MIN_GAMES, queue_depth="the 2025 backfill has NO displayed book sizes: queue is a scenario (FRONT/Q500/Q5000/THROUGH_ONLY), not an observation"),
               cohort=dict(tapes=len(cohort), ticks_before=len(before_t), ticks_after=len(after_t), games=len({t.game["game_id"] for t in after_t}), families=fams,
                           by_family={f: dict(tickers=len({r["ticker"] for r in rows_a if r["family"] == f}), games=len({r["game"] for r in rows_a if r["family"] == f}),
                                              orders=sum(1 for r in rows_a if r["family"] == f)) for f in fams},
                           not_joined=sorted(t for _, t in cohort if t not in {x.ticker for x in after_t})),
               audit_before={"|".join(k): v for k, v in sorted(aud_b.items())}, audit_after={"|".join(k): v for k, v in sorted(aud_a.items())})
    rep["comparison"] = compare(rows_b, rows_a)
    rep["comparison_by_family"] = {f: compare([r for r in rows_b if r["family"] == f], [r for r in rows_a if r["family"] == f]) for f in fams}
    for tag, rows in (("before", rows_b), ("after", rows_a)):
        det = [i for i, r in enumerate(rows) if r["determinate"]]
        rep[f"economics_{tag}"] = economics(rows, det)
        rep[f"holdout_{tag}"] = holdout_protocol(rows, det)
    rep["fee_evidence"] = fee_grades(sorted({s for s, _ in cohort}), a.fees_dir, a.fee_schedule)
    if a.population:
        pt = []
        for s in ("KXNFLGAME", "KXNFLSPREAD"):
            for m in N.load_markets(s, a.backfill):
                t = D.load_tick(s, m, idx, a.backfill, "legacy")
                if t:
                    pt.append(t)
        pr, _ = ST.build_rows(pt)
        rep["population_legacy"] = dict(ticks=len(pt), capped=sum(t.capped for t in pt), orders=len(pr), orders_determinate=sum(r["determinate"] for r in pr),
                                        orders_uncertain=sum(not r["determinate"] for r in pr))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(rep, open(a.out, "w"), indent=1, sort_keys=True, default=str)
    print(json.dumps({k: rep[k] for k in ("cohort", "comparison")}, default=str)[:2000])


if __name__ == "__main__":
    main()
