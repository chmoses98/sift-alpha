#!/usr/bin/env python3
"""CFB 2026 outcome-intelligence study over the PROSPECTIVE research corpus (RESEARCH_ONLY; no orders, no promotion).

usage: python3 research/outcome_exec/cfb_outcome.py [--root DIR] [--out FILE] [--seed N]
Root = checkout of cfb-edge-finder ``research-data`` (needs data/research/{observations,settlements}); env SIFT_CFB_RESEARCH.
Rules: settled outcomes are outcomes only (never features); unsettled stay missing; one row per ticker x snapshot label
(earliest capture kept); cluster = physical game; every cell tried is counted for multiple-testing control.
"""
from __future__ import annotations
import argparse, glob, json, math, os, sys
from collections import Counter, defaultdict
from datetime import datetime
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from sift_research import fees, stats  # noqa: E402

STATUS = "RESEARCH_ONLY"
SPREAD_MAX = 0.10          # data-quality filter: yes_ask + no_ask - 1 <= 10c (two-sided, non-thin book)
MIN_N, MIN_GAMES = 30, 12
THRESHOLDS = (0.03, 0.05, 0.10, 0.15)
HBUCKETS = (("gt72h", 72, 1e9), ("6h_72h", 6, 72), ("lt6h", 0, 6))
LABEL_ORDER = ["EARLY_OPEN", "T_7D", "T_3D", "T_24H", "T_6H", "T_90", "T_60", "T_30", "CLOSING"]


def pdt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def clean(o):
    """JSON-safe: NaN/inf -> None, numpy -> python."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not math.isfinite(float(o)) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def hbucket(h):
    for name, lo, hi in HBUCKETS:
        if lo <= h < hi:
            return name
    return "lt6h"


def load(root):
    obs = []
    for f in sorted(glob.glob(os.path.join(root, "data/research/observations/*/*.jsonl"))):
        for l in open(f):
            obs.append(json.loads(l))
    sett = {}
    for f in sorted(glob.glob(os.path.join(root, "data/research/settlements/*/*.jsonl"))):
        for l in open(f):
            r = json.loads(l)
            t = r["kalshi_market_ticker"]
            if t not in sett or r["settled_at"] >= sett[t]["settled_at"]:
                sett[t] = r                        # latest row wins
    return obs, sett


def build(obs, sett):
    """Returns (rows, coverage). rows: evaluated, point-in-time-valid, deduped ticker x label."""
    cov = dict(total_obs=len(obs), by_outcome=Counter(), pit_violations=0, duplicates_dropped=0)
    bucket = defaultdict(Counter)       # (dimension, key) -> counters
    best = {}
    for x in obs:
        o = x["observation"]
        fam = o.get("family") or "unresolved"
        st = o.get("snapshot_timing") or {}
        label = st.get("label") or "NONE"
        hrs = st.get("hours_before_kickoff")
        cov["by_outcome"][o["coverage_outcome"]] += 1
        keys = [("family", fam), ("label", label), ("hours_bucket", hbucket(hrs) if hrs is not None else "none")]
        for k in keys:
            bucket[k]["total"] += 1
        if o["coverage_outcome"] != "evaluated":
            for k in keys:
                bucket[k]["ticker_unresolved" if o["coverage_outcome"] == "ticker_unresolved" else "other_unevaluated"] += 1
            continue
        t = o["kalshi_market_ticker"]
        ko, cap = x.get("kickoff_utc_at_capture"), o["captured_at"]
        if ko is None or pdt(cap) >= pdt(ko):
            cov["pit_violations"] += 1
            for k in keys:
                bucket[k]["pit_violation"] += 1
            continue
        py, ay, an = o.get("model_probability"), o.get("executable_yes_price"), o.get("executable_no_price")
        for k in keys:
            bucket[k]["evaluated"] += 1
            if o.get("pricing_status") == "model_priced" and py is not None:
                bucket[k]["priced"] += 1
            if ay is None or an is None:
                bucket[k]["missing_executable_price"] += 1
        if py is None or ay is None or an is None or o.get("market_midpoint") is None:
            continue
        key = (t, label)
        r = dict(ticker=t, game=o["game_id"], family=fam, label=label, hrs=float(hrs), kick=pdt(ko), cap=pdt(cap),
                 p=float(py), mid=float(o["market_midpoint"]), ay=float(ay), an=float(an),
                 fee_est=o.get("estimated_taker_fee"), spread=float(ay) + float(an) - 1.0)
        if key in best:
            cov["duplicates_dropped"] += 1
            if r["cap"] >= best[key]["cap"]:
                continue
        best[key] = r
    rows = sorted(best.values(), key=lambda r: (r["cap"], r["ticker"]))
    for r in rows:
        s = sett.get(r["ticker"])
        r["y"] = {"yes": 1, "no": 0}.get(s["derived_contract_settlement"]) if s and s["status"] == "settled" else None
        r["sstatus"] = s["status"] if s else "no_settlement_row"
        r["hb"] = hbucket(r["hrs"])
        r["thin"] = r["spread"] > SPREAD_MAX
        for k in (("family", r["family"]), ("label", r["label"]), ("hours_bucket", r["hb"])):
            bucket[k]["usable_priced_rows"] += 1
            bucket[k]["settled" if r["y"] is not None else "unsettled_or_no_row"] += 1
            if r["thin"]:
                bucket[k]["thin_book_gt10c_spread"] += 1
    cov["by_outcome"] = dict(cov["by_outcome"])
    cov["breakdown"] = {f"{d}:{k}": dict(v) for (d, k), v in sorted(bucket.items())}
    cov["settlement_status_of_usable_rows"] = dict(Counter(r["sstatus"] for r in rows))
    cov["ever_recommended_flag"] = "none: corpus is the full priced universe (all mapped contracts), no recommendation filter applied"
    return rows, cov


def arrays(rows):
    g = lambda k: np.array([r[k] for r in rows], dtype=float)
    return g("p"), g("mid"), g("ay"), g("an"), np.array([r["y"] for r in rows], dtype=float)


def calibration(rows):
    out = {}
    for name, sub in (("all", rows),) + tuple((f, [r for r in rows if r["family"] == f]) for f in ("moneyline", "spread", "total")):
        for filt, s2 in (("no_filter", sub), (f"spread<={SPREAD_MAX}", [r for r in sub if not r["thin"]])):
            s2 = [r for r in s2 if r["y"] is not None]
            if len(s2) < 20:
                out[f"{name}|{filt}"] = dict(n=len(s2))
                continue
            p, mid, ay, an, y = arrays(s2)
            games = len({r["game"] for r in s2})
            d = dict(n=len(s2), n_games=games, brier_model=stats.brier(p, y), brier_market=stats.brier(mid, y),
                     logloss_model=stats.logloss(p, y), logloss_market=stats.logloss(mid, y), base_rate=float(y.mean()))
            # paired brier difference (model - market): negative = model better; cluster bootstrap by game
            diff = (p - y) ** 2 - (mid - y) ** 2
            d["brier_diff_model_minus_market"] = stats.cluster_bootstrap(diff, [r["game"] for r in s2], seed=11)
            edges = [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0]
            d["reliability_model"] = stats.calibration_bins(p, y, edges)
            d["reliability_market_mid"] = stats.calibration_bins(mid, y, edges)
            out[f"{name}|{filt}"] = d
    thin = [r for r in rows if r["y"] is not None]
    out["data_quality"] = dict(settled_rows=len(thin), thin_share=float(np.mean([r["thin"] for r in thin])) if thin else None,
                               spread_quantiles=dict(zip(("p10", "p50", "p90", "p99"), map(float, np.quantile([r["spread"] for r in thin], [.1, .5, .9, .99])))) if thin else None,
                               mid_vs_ask_note="mid is (yes_bid+yes_ask)/2; thin books have mid far from either ask, so model-vs-mid 'gaps' there are not executable")
    return out


def side_pnl(r, side, role="taker"):
    price = r["ay"] if side == "yes" else r["an"]
    win = r["y"] if side == "yes" else 1 - r["y"]
    fee = float(fees.fee_per_contract(price, 1, role))
    return win - price - fee, price, fee


def candidates(rows, thr, fam, side, hb, settled_only=True, require_quality=True):
    """First qualifying snapshot per ticker x side. Signal uses gap = model - mid (known at capture)."""
    seen, out = set(), []
    for r in rows:
        if require_quality and r["thin"]:
            continue
        if fam != "all" and r["family"] != fam:
            continue
        if hb != "all" and r["hb"] != hb:
            continue
        if settled_only and r["y"] is None:
            continue
        gap = r["p"] - r["mid"]
        for s in ("yes", "no"):
            if side not in ("both", s):
                continue
            edge = gap if s == "yes" else -gap
            if edge >= thr and (r["ticker"], s) not in seen:
                seen.add((r["ticker"], s))
                out.append((r, s))
    return out


def eval_cell(items):
    if not items:
        return dict(n=0, n_games=0)
    pnl, ent, fe, win = [], [], [], []
    for r, s in items:
        v, price, fee = side_pnl(r, s)
        pnl.append(v); ent.append(price); fe.append(fee)
        win.append(r["y"] if s == "yes" else 1 - r["y"])
    d = stats.cluster_bootstrap(pnl, [r["game"] for r, _ in items], n_boot=1000, seed=3)
    d.update(mean_entry_price=float(np.mean(ent)), mean_fee=float(np.mean(fe)), win_rate=float(np.mean(win)),
             mean_est_fee_field=float(np.mean([r["fee_est"] for r, _ in items if r["fee_est"] is not None])) if any(r["fee_est"] is not None for r, _ in items) else None)
    return d


def split_games(rows):
    games = {}
    for r in rows:
        if r["y"] is not None:
            games[r["game"]] = min(games.get(r["game"], r["kick"]), r["kick"])
    order = sorted(games, key=lambda g: (games[g], g))
    n = len(order)
    a, b = n // 3, 2 * n // 3
    part = {}
    for i, g in enumerate(order):
        part[g] = "discovery" if i < a else ("validation" if i < b else "holdout")
    info = {}
    for ph in ("discovery", "validation", "holdout"):
        gs = [g for g in order if part[g] == ph]
        info[ph] = dict(n_games=len(gs), first_kickoff=games[gs[0]].isoformat() if gs else None, last_kickoff=games[gs[-1]].isoformat() if gs else None)
    return part, info


def discovery_validation_holdout(rows):
    part, info = split_games(rows)
    sets = {ph: [r for r in rows if part.get(r["game"]) == ph] for ph in ("discovery", "validation", "holdout")}
    grid = [(t, f, s, h) for t in THRESHOLDS for f in ("all", "moneyline", "spread", "total") for s in ("yes", "no", "both") for h in ("all",) + tuple(b[0] for b in HBUCKETS)]
    cells = []
    for c in grid:
        d = eval_cell(candidates(sets["discovery"], *c))
        cells.append(dict(cell=dict(zip(("thr", "family", "side", "hours"), c)), discovery=d))
    testable = [c for c in cells if c["discovery"]["n"] >= MIN_N and c["discovery"]["n_clusters"] >= MIN_GAMES]
    pv = [c["discovery"]["p"] for c in testable]
    if testable:
        bh, ho = stats.benjamini_hochberg(pv), stats.holm(pv)
        for c, a, b in zip(testable, bh, ho):
            c["discovery"]["p_bh"], c["discovery"]["p_holm"] = float(a), float(b)
    # confirmation on validation for every testable cell with positive discovery mean (exploratory tier);
    # strict tier = BH q<=0.10 on discovery.
    for c in testable:
        c["validation"] = eval_cell(candidates(sets["validation"], *c["cell"].values()))
    pos = [c for c in testable if c["discovery"]["mean"] > 0]
    strict = [c for c in pos if c["discovery"].get("p_bh", 1) <= 0.10 and c["validation"]["n"] >= MIN_N and c["validation"]["mean"] > 0]
    expl = sorted([c for c in pos if c["validation"]["n"] >= MIN_N and c["validation"]["mean"] > 0], key=lambda c: -c["discovery"]["mean"])[:5]
    frozen = {id(c): c for c in strict + expl}.values()
    for c in frozen:                                   # holdout touched exactly once, only for frozen cells
        c["holdout"] = eval_cell(candidates(sets["holdout"], *c["cell"].values()))
        c["tier"] = "strict_BH0.10" if c in strict else "exploratory_top5_by_discovery"
    # all-cell holdout-free summary
    ranked = []
    for c in frozen:
        v, h = c["validation"], c["holdout"]
        ranked.append(dict(cell=c["cell"], tier=c["tier"], discovery_mean=c["discovery"]["mean"], discovery_p_bh=c["discovery"].get("p_bh"),
                           validation=dict(mean=v["mean"], lo=v["lo"], hi=v["hi"], n=v["n"], n_games=v["n_clusters"]),
                           holdout=dict(mean=h.get("mean"), lo=h.get("lo"), hi=h.get("hi"), n=h["n"], n_games=h.get("n_clusters", 0)),
                           coverage_share_of_settled_priced_rows=None))
    ranked.sort(key=lambda d: -(d["validation"]["lo"] if d["validation"]["lo"] is not None else -9))
    tot_settled = len({r["ticker"] for r in rows if r["y"] is not None and not r["thin"]})
    for d in ranked:
        n_h = d["holdout"]["n"] + d["validation"]["n"]
        d["coverage_share_of_settled_priced_rows"] = n_h / max(1, tot_settled)
    return dict(split=info, cells_tried=len(grid), cells_testable=len(testable), cells_discovery_positive=len(pos),
                survivors_strict_bh=len(strict), survivors_exploratory=len(expl),
                min_n=MIN_N, min_games=MIN_GAMES,
                discovery_top10_by_mean=sorted([dict(cell=c["cell"], **{k: c["discovery"].get(k) for k in ("mean", "lo", "hi", "p", "p_bh", "p_holm", "n", "n_clusters")}) for c in testable], key=lambda d: -d["mean"])[:10],
                frozen_cells_ranked=ranked,
                null_statement=("no cell survived BH<=0.10 on discovery" if not strict else f"{len(strict)} cell(s) passed BH<=0.10 on discovery") +
                "; holdout evaluated only for frozen cells; 3 weeks of data is a short sample")


def descriptive_ev(rows):
    """Unconditional baseline, gap-conditional EV, favourite-longshot by price bucket (all hours, first snapshot per ticker-side)."""
    q = [r for r in rows if r["y"] is not None and not r["thin"]]
    out = {}
    for fam in ("all", "moneyline", "spread", "total"):
        items = candidates(rows, -9, fam, "both", "all")
        out[f"baseline_buy_every_side_at_ask|{fam}"] = eval_cell(items)
    for thr in (0.05, 0.10):
        for fam in ("all", "moneyline", "spread", "total"):
            for side in ("yes", "no"):
                for hb in ("all",) + tuple(b[0] for b in HBUCKETS):
                    out[f"gap>={thr}|{fam}|{side}|{hb}"] = eval_cell(candidates(rows, thr, fam, side, hb))
    # favourite-longshot: every side at ask, bucketed by entry price, per ticker-side first snapshot
    fl = defaultdict(list)
    for r, s in candidates(rows, -9, "all", "both", "all"):
        price = r["ay"] if s == "yes" else r["an"]
        b = min(int(price * 10), 9)
        fl[f"{b/10:.1f}-{(b+1)/10:.1f}"].append((r, s))
    out["favourite_longshot_by_entry_price"] = {k: eval_cell(v) for k, v in sorted(fl.items())}
    # gap bucket x side
    gb = defaultdict(list)
    for r in q:
        gap = r["p"] - r["mid"]
        gb[min(max(int((gap + 0.3) / 0.1), 0), 5)].append(r)
    out["gap_realised_vs_implied"] = {}
    for b, rs in sorted(gb.items()):
        p, mid, ay, an, y = arrays(rs)
        out["gap_realised_vs_implied"][f"gap[{-0.3+0.1*b:+.1f},{-0.2+0.1*b:+.1f})"] = dict(n=len(rs), mean_model=float(p.mean()), mean_mid=float(mid.mean()), freq_yes=float(y.mean()))
    out["fee_model_vs_field"] = dict(mean_fee_model_taker=float(np.mean([fees.fee_per_contract(r["ay"], 1) for r in q])) if q else None,
                                     mean_estimated_taker_fee_field=float(np.mean([r["fee_est"] for r in q if r["fee_est"] is not None])) if q else None)
    return out


def _mtm(pairs, big, gm):
    """Buy model's side at the EARLY ask, mark to the LATER mid, minus taker fee (a mark-to-market, not a fill or P&L)."""
    v, g = [], []
    for (a, b), bg, gg in zip(pairs, big, gm):
        if not bg:
            continue
        yes = a["p"] - a["mid"] > 0
        price = a["ay"] if yes else a["an"]
        later = b["mid"] if yes else 1 - b["mid"]
        v.append(later - price - float(fees.fee_per_contract(price, 1)))
        g.append(gg)
    return stats.cluster_bootstrap(v, g, 1000, 5) if len(v) >= 30 else dict(n=len(v))


def timing(rows):
    byt = defaultdict(dict)
    for r in rows:
        if not r["thin"]:
            byt[r["ticker"]][r["label"]] = r
    out = {}
    for fam in ("all", "moneyline", "spread", "total"):
        res = {}
        for lab in LABEL_ORDER[1:]:
            pairs = [(d["EARLY_OPEN"], d[lab]) for d in byt.values() if "EARLY_OPEN" in d and lab in d and (fam == "all" or d[lab]["family"] == fam)]
            if len(pairs) < 30:
                res[lab] = dict(n=len(pairs)); continue
            gm = [a["game"] for a, _ in pairs]
            # improvement of waiting = early ask - later ask (cents>0: waiting was cheaper), YES and NO sides, fee-exclusive
            iy = [a["ay"] - b["ay"] for a, b in pairs]; in_ = [a["an"] - b["an"] for a, b in pairs]
            dmid = np.array([b["mid"] - a["mid"] for a, b in pairs])
            gap = np.array([a["p"] - a["mid"] for a, _ in pairs])
            clv = np.sign(gap) * dmid                 # CLV-like: did the mid move toward the model's side after early open?
            big = np.abs(gap) >= 0.05
            res[lab] = dict(n=len(pairs), n_games=len(set(gm)), wait_improvement_yes_ask=stats.cluster_bootstrap(iy, gm, 1000, 5),
                            wait_improvement_no_ask=stats.cluster_bootstrap(in_, gm, 1000, 5),
                            mid_drift=stats.cluster_bootstrap(dmid, gm, 1000, 5),
                            model_side_clv_all=stats.cluster_bootstrap(clv, gm, 1000, 5),
                            model_side_clv_gap_ge_5c=stats.cluster_bootstrap(clv[big], np.array(gm)[big], 1000, 5) if big.sum() >= 30 else dict(n=int(big.sum())),
                            model_side_buy_early_ask_mark_to_later_mid_net_fee_gap_ge_5c=_mtm(pairs, big, gm),
                            corr_gap_drift=float(np.corrcoef(gap, dmid)[0, 1]) if gap.std() > 0 and dmid.std() > 0 else None)
        out[fam] = res
    out["note"] = "observation-level price comparisons from ONE snapshot per label; no fills, queue or maker mechanics. Thin-book rows excluded."
    return out


def ranked_findings(dv, desc):
    out = []
    for i, d in enumerate(dv["frozen_cells_ranked"], 1):
        out.append(dict(rank=i, kind="rule(frozen)", **{k: d[k] for k in ("cell", "tier", "validation", "holdout", "coverage_share_of_settled_priced_rows")},
                        reading=("holdout CI includes 0 -> not demonstrated" if d["holdout"]["lo"] is None or d["holdout"]["lo"] <= 0 else "holdout lower bound > 0")))
    return out


def run(root, seed=7):
    np.random.seed(seed)
    obs, sett = load(root)
    rows, cov = build(obs, sett)
    s = [r for r in rows if r["y"] is not None]
    res = dict(status=STATUS, schema="sift-research/cfb-outcome/1", source="cfb-edge-finder research-data (PROSPECTIVE capture)",
               window=dict(first_capture=min(r["cap"] for r in rows).isoformat() if rows else None, last_capture=max(r["cap"] for r in rows).isoformat() if rows else None),
               coverage=cov, settlement_rows=len(sett), usable_rows=len(rows), settled_rows=len(s),
               settled_games=len({r["game"] for r in s}), settled_tickers=len({r["ticker"] for r in s}),
               parameters=dict(spread_filter=SPREAD_MAX, thresholds=THRESHOLDS, min_n=MIN_N, min_games=MIN_GAMES, seed=seed),
               calibration=calibration(rows), ev=descriptive_ev(rows))
    res["discovery_validation_holdout"] = discovery_validation_holdout(rows)
    res["timing"] = timing(rows)
    res["ranked_findings"] = ranked_findings(res["discovery_validation_holdout"], res["ev"])
    res["limitations"] = ["~3 weeks (weeks 1-3 of 2026), few hundred settled games: wide intervals; nulls are not proof of no edge",
                          "same ticker appears at up to 9 snapshot labels; rules use the first qualifying snapshot per ticker-side, clusters are games",
                          "acquisition price = executable ask in the snapshot; real fills (queue, size, slippage) not modelled",
                          "gap uses model - midpoint; thin books (spread>10c) excluded from EV/selection but shown in calibration without filter",
                          "unsettled markets (pending_not_final) are excluded from outcomes, never imputed",
                          "taker fee modelled 0.07*P*(1-P) ceil-to-cent per contract; estimated_taker_fee field compared in ev.fee_model_vs_field"]
    return clean(res)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("SIFT_CFB_RESEARCH", "/home/user/data_cfb_rd"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "reports", "outcome_exec", "cfb_outcome.json"))
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    res = run(a.root, a.seed)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(res, open(a.out, "w"), indent=1, allow_nan=False)
    print("wrote", a.out, "usable", res["usable_rows"], "settled", res["settled_rows"])


if __name__ == "__main__":
    main()
