#!/usr/bin/env python3
"""SOCCER market-first evidence audit + incremental-prediction test (RESEARCH_ONLY; never trades).

Inputs: chmoses98/soccer-edge-finder branch data-archive (predictions/, settlements/, results/espn/, odds_api/, reference/).
Rows: one per (ticker, horizon label, model family/engine): the LATEST pre-kickoff prediction record of that key (dedupe is by time only, never by outcome).
  mid = Kalshi yes bid/ask midpoint stored in the prediction record (market_as_of), q = model fair_probability_mean, y = settled outcome.
usage: python3 -I research/outcome_intel/soccer_audit.py --root /home/user/data/soc_data-archive --out reports/outcome_intel/soccer_audit.json
"""
from __future__ import annotations
import argparse, collections, glob, gzip, json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import cbb_common as C
import incremental as I

HORIZONS = ("T-24h", "T-12h", "T-6h", "T-2h", "T-90m", "T-60m", "T-30m", "T-15m", "T-10m", "close")
PRIMARY = "data_only.world_sim_v2|world_sim_v2"
MAX_SPREAD = 0.10


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load(root):
    P, S, files = {}, {}, {}
    for fp in sorted(glob.glob(os.path.join(root, "predictions/*/predictions.jsonl.gz"))):
        files[os.path.relpath(fp, root)] = C.sha256_file(fp)
        with gzip.open(fp, "rt") as fh:
            for line in fh:
                p = json.loads(line)
                m = p.get("market") or {}
                P[p["record_id"]] = dict(
                    rid=p["record_id"], tk=p["ticker"], ev=p["event_ticker"], fx=p["fixture_id"], comp=p["competition_id"], fam=p["family"], ko=p["kickoff_utc"],
                    as_of=p["as_of"], mod_as_of=p.get("model_as_of"), mkt_as_of=p.get("market_as_of"), eng=p["engine_version"], mf=p["model_family"],
                    q=(p.get("probability") or {}).get("fair_probability_mean"), yb=f(m.get("yes_bid")), ya=f(m.get("yes_ask")), sem=p["semantics"], lineup=p.get("lineup_state"))
    for fp in sorted(glob.glob(os.path.join(root, "settlements/*/predictions.jsonl.gz"))):
        files[os.path.relpath(fp, root)] = C.sha256_file(fp)
        with gzip.open(fp, "rt") as fh:
            for line in fh:
                s = json.loads(line)
                e = s["evidence"]
                S.setdefault(s["prediction_record_id"], []).append(dict(
                    outcome=s["outcome"], horizon=s["horizon"], ev=(e.get("period"), e.get("home"), e.get("away"), e.get("status"), e.get("source")), settled_at=s["settled_at"],
                    ref=s["reference_probability_at_prediction"], ref_obs=((s.get("close_v2") or {}).get("entry") or {}).get("reference", {}).get("observed_at"),
                    ref_book=((s.get("close_v2") or {}).get("entry") or {}).get("reference", {}).get("bookmaker")))
    return P, S, files


def load_results(root):
    R, files = {}, {}
    for fp in sorted(glob.glob(os.path.join(root, "results/espn/*.jsonl"))):
        files[os.path.relpath(fp, root)] = C.sha256_file(fp)
        for line in open(fp):
            r = json.loads(line)
            hg = r["home_goals_regulation"] if r.get("home_goals_regulation") is not None else r.get("home_goals")
            ag = r["away_goals_regulation"] if r.get("away_goals_regulation") is not None else r.get("away_goals")
            R.setdefault(r["fixture_id"], []).append(dict(h=hg, a=ag, date=r["match_date"], comp=r["competition_id"], home=r["home_team_id"], away=r["away_team_id"],
                                                          status=r.get("status_name"), ht=(r.get("home_goals_ht"), r.get("away_goals_ht")), et=r.get("extra_time_played"), pens=r.get("decided_on_penalties")))
    return R, files


def base_fixture(fx):
    parts = fx.split(":")
    return ":".join(parts[:5])


def find_result(R, byteams, p):
    """Exact fixture id (matchday suffix stripped), else (competition, home, away, kickoff date +-1 day)."""
    b = base_fixture(p["fx"])
    if b in R:
        rs = R[b]
        return rs[-1] if len({(x["h"], x["a"]) for x in rs}) == 1 else "CONFLICT"
    parts = p["fx"].split(":")
    key = (parts[1], parts[3], parts[4])
    from datetime import datetime, timedelta
    ko = C.pdt(p["ko"])
    c = [x for x in byteams.get(key, []) if abs((datetime.fromisoformat(x["date"]).replace(tzinfo=ko.tzinfo) - ko).days) <= 1]
    return c[-1] if len({(x["h"], x["a"]) for x in c}) == 1 else ("CONFLICT" if c else None)


def derive(p, ft, per_goals):
    """Independent outcome from goals under the contract semantics. ft=(h,a) regulation score or None; per_goals={'first_half':(h,a),'second_half':(h,a)} from settlement evidence."""
    s, fam = p["sem"], p["fam"]
    per = s.get("period")
    sc = ft if per == "regulation" else per_goals.get(per) if per in ("first_half", "second_half") else None
    if sc is None:
        return None
    h, a = sc
    side = s.get("side")
    line = f(s.get("line"))
    if fam in ("match_result_3way", "first_half_result", "second_half_result"):
        return int({"home": h > a, "away": a > h, "draw": h == a}[side]) if side in ("home", "away", "draw") else None
    if fam in ("total_goals", "first_half_total"):
        return int(h + a > line) if line is not None else None
    if fam == "team_total":
        return int((h if side == "home" else a) > line) if side in ("home", "away") and line is not None else None
    if fam in ("handicap", "first_half_handicap"):
        return int(((h - a) if side == "home" else (a - h)) > line) if side in ("home", "away") and line is not None else None
    if fam in ("btts", "first_half_btts"):
        return int(h > 0 and a > 0)
    if fam in ("exact_score", "first_half_exact_score"):
        m = re.search(r"(\d+)-(\d+)", s.get("description") or "")
        return int((h, a) == (int(m.group(1)), int(m.group(2)))) if m else None
    return None


def select_rows(recs, cnt):
    """Time/quote/settlement filters and dedupe (latest as_of per key). Never looks at the outcome to choose among duplicates."""
    best = {}
    for r in recs:
        if r["y"] is None:
            cnt["no_binary_outcome"] += 1
            continue
        if r["yd"] is not None and r["yd"] != r["y"]:
            cnt["settlement_vs_derived_disagree"] += 1
            continue
        if r["yd"] is None and r["fam"] != "first_to_score":
            cnt["not_derivable_kept_on_settlement_only"] += 1
        if r["fam"] == "first_to_score":
            cnt["first_to_score_settlement_only(no_event_data)"] += 1
        if not (C.pdt(r["as_of"]) < C.pdt(r["ko"]) and r["mkt_as_of"] and C.pdt(r["mkt_as_of"]) < C.pdt(r["ko"])):
            cnt["not_pre_kickoff"] += 1
            continue
        if r["yb"] is None or r["ya"] is None or not (0.0 < r["yb"] < r["ya"] < 1.0) or r["ya"] - r["yb"] > MAX_SPREAD + 1e-9 or r["q"] is None:
            cnt["invalid_or_wide_quote_or_no_q"] += 1
            continue
        key = (r["tk"], r["hz"], r["mf"], r["eng"])
        if key not in best or r["as_of"] > best[key]["as_of"]:
            best[key] = r
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/home/user/data/soc_data-archive")
    ap.add_argument("--out", default="reports/outcome_intel/soccer_audit.json")
    a = ap.parse_args()
    P, S, files = load(a.root)
    R, rfiles = load_results(a.root)
    byteams = collections.defaultdict(list)
    for fx, rs in R.items():
        for r in rs:
            byteams[(r["comp"], r["home"], r["away"])].append(r)
    # ---- integrity
    orphan = [k for k in S if k not in P]
    multi = {k: v for k, v in S.items() if len(v) > 1}
    integ = dict(prediction_records=len(P), settlement_records=sum(len(v) for v in S.values()), settled_prediction_ids=len(S), orphan_settlements=len(orphan),
                 prediction_ids_with_multiple_settlements=len(multi),
                 conflicting_resettlements=sum(1 for v in multi.values() if len({x["outcome"] for x in v}) > 1))
    integ["asof_not_before_kickoff"] = sum(1 for p in P.values() if C.pdt(p["as_of"]) >= C.pdt(p["ko"]))
    integ["market_asof_not_before_kickoff"] = sum(1 for p in P.values() if p["mkt_as_of"] and C.pdt(p["mkt_as_of"]) >= C.pdt(p["ko"]))
    integ["model_asof_after_market_asof_gt_5min"] = sum(1 for p in P.values() if p["mkt_as_of"] and p["mod_as_of"] and (C.pdt(p["mod_as_of"]) - C.pdt(p["mkt_as_of"])).total_seconds() > 300)
    gaps = [(C.pdt(p["mkt_as_of"]) - C.pdt(p["mod_as_of"])).total_seconds() / 60 for p in P.values() if p["mkt_as_of"] and p["mod_as_of"]]
    integ["market_minus_model_asof_minutes"] = dict(zip(("p0", "p5", "p50", "p95", "p100"), [float(x) for x in np.percentile(gaps, [0, 5, 50, 95, 100])]))
    integ["lineup_state_values"] = dict(collections.Counter(p["lineup"] for p in P.values()))
    integ["duplicate_keys_ticker_horizon_modelengine"] = sum(1 for v in collections.Counter((p["tk"], S[k][0]["horizon"], p["mf"], p["eng"]) for k, p in P.items() if k in S).values() if v > 1)
    # ---- per-fixture goals from settlement evidence (cross-record consistency) + independent results/espn
    ev = collections.defaultdict(lambda: collections.defaultdict(set))
    for rid, lst in S.items():
        if rid in P:
            per, h, aw = lst[0]["ev"][:3]
            ev[P[rid]["fx"]][per].add((h, aw))
    integ["fixtures_settled"] = len(ev)
    integ["fixtures_with_conflicting_evidence_scores"] = sum(1 for d in ev.values() if any(len(v) > 1 for v in d.values()))
    fxinfo = {}
    nres = ncon = 0
    for rid, p in P.items():
        if p["fx"] in fxinfo:
            continue
        res = find_result(R, byteams, p) if p["fx"] in ev else None
        if res == "CONFLICT":
            ncon += 1
            res = None
        d = ev.get(p["fx"], {})
        evft = next(iter(d["regulation"])) if "regulation" in d and len(d["regulation"]) == 1 else None
        ft = (res["h"], res["a"]) if res and res["h"] is not None else None
        fxinfo[p["fx"]] = dict(ft_indep=ft, ft_evidence=evft, per={k: next(iter(v)) for k, v in d.items() if k in ("first_half", "second_half") and len(v) == 1},
                               et=bool(res and res.get("et")), pens=bool(res and res.get("pens")), indep_status=res and res["status"])
    integ["fixtures_with_independent_ft_result"] = sum(1 for x, v in fxinfo.items() if x in ev and v["ft_indep"] is not None)
    integ["fixtures_independent_vs_evidence_ft_disagree"] = sum(1 for x, v in fxinfo.items() if v["ft_indep"] is not None and v["ft_evidence"] is not None and v["ft_indep"] != v["ft_evidence"])
    integ["fixtures_et_or_pens_flagged"] = sum(1 for x, v in fxinfo.items() if x in ev and (v["et"] or v["pens"]))
    integ["results_fixture_conflicts"] = ncon

    # ---- settle each record, derive independently
    cov = collections.defaultdict(collections.Counter)
    recs = []
    unsettled = collections.Counter()
    for rid, p in P.items():
        fam = p["fam"]
        c = cov[fam]
        c["prediction_records"] += 1
        if rid not in S:
            unsettled[fam] += 1
            continue
        s = S[rid][0]
        y = 1 if s["outcome"] == "yes" else 0 if s["outcome"] == "no" else None
        fi = fxinfo[p["fx"]]
        ft = fi["ft_indep"]
        src = "results_espn(independent)"
        yd = derive(p, ft, fi["per"]) if (ft is not None or p["sem"].get("period") in ("first_half", "second_half")) else None
        if p["sem"].get("period") in ("first_half", "second_half"):
            src = "settlement_evidence_period_score"
        if yd is None and fi["ft_evidence"] is not None and p["sem"].get("period") == "regulation":
            yd, src = derive(p, fi["ft_evidence"], fi["per"]), "settlement_evidence_score(not independent)"
        c["settled"] += 1
        if yd is None:
            c["not_derivable"] += 1
        else:
            c["derived:" + ("independent" if src.startswith("results") else "evidence")] += 1
            c["agree" if yd == y else "disagree"] += 1
        recs.append(dict(p, y=y, yd=yd, hz=s["horizon"], ref=s["ref"], ref_obs=s["ref_obs"], ref_book=s["ref_book"], dsrc=src))
    # ---- rows
    cnt = collections.Counter()
    best = select_rows(recs, cnt)
    cnt["deduped_rows"] = len(best)
    rows_by = collections.defaultdict(list)
    ref_rows = collections.defaultdict(dict)
    for r in best.values():
        row = dict(game=r["fx"], t=C.pdt(r["ko"]).isoformat(), mid=(r["yb"] + r["ya"]) / 2, q=float(r["q"]), y=r["y"], tk=r["tk"], lead=(C.pdt(r["ko"]) - C.pdt(r["as_of"])).total_seconds() / 60)
        rows_by[(r["fam"], r["hz"], r["mf"] + "|" + r["eng"])].append(row)
        # reference (consensus bookmaker) challenger: only if its observation time precedes kickoff and is within 10 min of the Kalshi quote
        if r["ref"] is not None and r["ref_obs"] and C.pdt(r["ref_obs"]) < C.pdt(r["ko"]) and abs((C.pdt(r["ref_obs"]) - C.pdt(r["mkt_as_of"])).total_seconds()) <= 600:
            k = (r["fam"], r["tk"])
            if k not in ref_rows[r["fam"]] or r["as_of"] > ref_rows[r["fam"]][k]["as_of"]:
                ref_rows[r["fam"]][k] = dict(row, q=float(r["ref"]), as_of=r["as_of"], book=r["ref_book"])
    # ---- tests
    chal = {}
    for k, rr in rows_by.items():
        chal["%s|%s|%s" % k] = C.run_challenger(rr)
    for fam, d in ref_rows.items():
        rr = list(d.values())
        rows_by[(fam, "ANY_WITH_REFERENCE", "reference_consensus")] = rr
        chal["%s|ANY_WITH_REFERENCE|reference_consensus" % fam] = C.run_challenger(rr)
    holm_all = C.holm_over(chal)
    holm_prim = C.holm_over({k: v for k, v in chal.items() if k.split("|", 2)[2] == PRIMARY})
    cells = []
    for (fam, hz, ch), rr in sorted(rows_by.items()):
        key = "%s|%s|%s" % (fam, hz, ch)
        c = chal[key]
        st, why = C.classify(c, holm_all.get(key))
        gb = C.gain_block(c, holm_all.get(key))
        gb["holm_p_primary_challenger_only"] = holm_prim.get(key)
        nfx = len({x["game"] for x in rr})
        three = fam == "match_result_3way"
        cells.append(dict(
            sport="SOCCER", family=fam, horizon=hz, challenger=ch, is_primary_challenger=(ch == PRIMARY),
            inputs_available=dict(kalshi_quote=True, sift_model_probability=(ch != "reference_consensus"), consensus_bookmaker_reference=(ch == "reference_consensus"),
                                  lineups="NOT AVAILABLE pre-kickoff (lineup_state='unknown' on all records)", weather="captured for few events, not joined", xg_form="not in archive"),
            n_games=nfx, n_contracts=len({x["tk"] for x in rr}), n_rows=len(rr),
            price_coverage=dict(quote_source="Kalshi yes bid/ask stored in prediction record at market_as_of (top of book only; no orderbook depth)", max_quote_spread=MAX_SPREAD,
                                lead_minutes=(dict(min=float(min(x["lead"] for x in rr)), median=float(np.median([x["lead"] for x in rr])), max=float(max(x["lead"] for x in rr))) if rr else None),
                                note="3 mutually exclusive contracts per fixture (home/draw/away); clustered by fixture" if three else None),
            settlement_source="settlement_record_v1 outcome (ESPN site API scores), cross-checked by independent re-derivation from results/espn (FT) or per-period evidence scores",
            market_metrics=C.market_only(rr), model_metrics=C.model_metrics(rr), calibration_bins=C.calibration_bins(rr),
            challenger_detail={k: v for k, v in c.items() if k in ("status", "train_games", "holdout_games", "n_train", "n_holdout", "logloss", "brier", "coef_challenger",
                                                                  "negative_control_gain", "positive_control_gain", "calibration_gain_of_market_alone_logloss", "gain_vs_raw_market_logloss")},
            incremental_gain=gb, status=st, reason=why))
    # families with no testable row at all
    seen = {c["family"] for c in cells}
    allfams = sorted({p["fam"] for p in P.values()})
    for fam in allfams:
        if fam not in seen:
            cells.append(dict(sport="SOCCER", family=fam, horizon="ALL", status="MISSING_DATA", reason="no settled pre-kickoff row with a valid two-sided Kalshi quote", n_games=0, n_contracts=0,
                              incremental_gain=dict(mean=None, lo=None, hi=None, holm_p=None)))
    # leads per horizon (realized), prediction coverage
    lead = collections.defaultdict(list)
    for r in recs:
        lead[r["hz"]].append((C.pdt(r["ko"]) - C.pdt(r["as_of"])).total_seconds() / 60)
    # settled-prediction coverage by family
    fam_cov = {}
    for fam, c in cov.items():
        fam_cov[fam] = dict(c, unsettled=unsettled[fam],
                            n_tickers=len({p["tk"] for p in P.values() if p["fam"] == fam}), n_fixtures=len({p["fx"] for p in P.values() if p["fam"] == fam}),
                            n_settled_tickers=len({r["tk"] for r in recs if r["fam"] == fam and r["y"] is not None}), n_settled_fixtures=len({r["fx"] for r in recs if r["fam"] == fam}))
    max_ko_unsettled = collections.Counter(p["ko"][:10] for rid, p in P.items() if rid not in S)
    heads = {}
    try:
        heads["data-archive"] = subprocess.check_output(["git", "-C", a.root, "rev-parse", "FETCH_HEAD"], text=True).strip()
    except Exception:
        heads["data-archive"] = None
    report = dict(
        schema="sift-outcome-intel-sport-audit/1", status="RESEARCH_ONLY", sport="SOCCER",
        protocol=dict(split="chronological by kickoff: earliest 2/3 fixtures train, latest 1/3 holdout", ridge=1.0, statistic="holdout logloss gain over train-calibrated Kalshi mid (positive = challenger better)",
                      ci="fixture-cluster bootstrap 2000", multiplicity="Holm over every challenger cell tried (%d); untestable cells enter with p=1; primary-challenger-only Holm also reported" % len(chal),
                      dedup="latest pre-kickoff record per (ticker, horizon label, model family, engine); horizon label is 'at least X before kickoff' so realised lead is reported",
                      quote="Kalshi yes bid/ask mid stored in the prediction record; two-sided, spread<=0.10", primary_challenger=PRIMARY, status_rule="see cbb_common.classify"),
        provenance=dict(repo="chmoses98/soccer-edge-finder", branch="data-archive", head=heads, input_files=dict(
            predictions=C.hashlib.sha256("\n".join("%s %s" % kv for kv in sorted(files.items())).encode()).hexdigest(), n_prediction_settlement_files=len(files),
            results_espn=C.hashlib.sha256("\n".join("%s %s" % kv for kv in sorted(rfiles.items())).encode()).hexdigest(), n_results_files=len(rfiles)),
            kickoff_range=[min(p["ko"] for p in P.values()), max(p["ko"] for p in P.values())]),
        integrity=integ, coverage_by_family=fam_cov, row_selection_counters=dict(cnt), unsettled_prediction_kickoff_dates=dict(sorted(max_ko_unsettled.items())[-12:]),
        realized_lead_minutes_by_horizon_label={h: dict(n=len(v), p10=float(np.percentile(v, 10)), median=float(np.median(v)), p90=float(np.percentile(v, 90))) for h, v in lead.items()},
        reference_coverage=dict(settled_with_reference_probability=sum(1 for r in recs if r["ref"] is not None), by_book=dict(collections.Counter(r["ref_book"] for r in recs if r["ref"] is not None))),
        cells=C.normalize_cells(cells), status_counts=dict(collections.Counter(c["status"] for c in cells)), control_summary=C.neg_control_summary(chal))
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(report, open(a.out, "w"), indent=1, sort_keys=True, default=str)
    print(json.dumps(report["status_counts"]))
    print(json.dumps(integ, default=str))
    for c in cells:
        g = c["incremental_gain"]
        if g.get("mean") is not None and c.get("is_primary_challenger"):
            print(c["family"], c["horizon"], c["n_games"], c["n_contracts"], c["status"], "%.4f [%.4f,%.4f] holm=%.3f" % (g["mean"], g["lo"], g["hi"], g["holm_p"]))


if __name__ == "__main__":
    main()
