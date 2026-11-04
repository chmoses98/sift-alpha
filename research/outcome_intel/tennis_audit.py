#!/usr/bin/env python3
"""TENNIS market-first evidence audit + incremental-prediction test (RESEARCH_ONLY; never trades).

Inputs: chmoses98/Tennis-Edge-Finder branch tennis-data: tennis-edge-finder/data/research/{ledger,settlements,sports_truth}.
Time validity: a prediction row is used ONLY if the repository's own settle job classified it STRICT_PREGAME (entry quote provably before the
first-ball LOWER bound from first-ball truth) AND this script re-checks generated_at < first_ball_lower_utc. START_UNKNOWN rows (96.5% of the
ledger) are NOT used: a scheduled start is not proof of pre-match; 299 observed POST_START rows show the contamination risk is real.
usage: python3 -I research/outcome_intel/tennis_audit.py --root /home/user/data/ten_tennis-data/tennis-edge-finder/data/research --out reports/outcome_intel/tennis_audit.json
"""
from __future__ import annotations
import argparse, collections, glob, gzip, hashlib, json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import cbb_common as C
import incremental as I

CHALLENGERS = ("ELO_DP_FAIR", "PRODUCTION", "INCUMBENT", "ELO", "STRUCTURAL")
PRIMARY = "ELO_DP_FAIR"   # DP-priced fair under the production projection; the only model value present for every family
HORIZONS = ("LAST_STRICT_PREGAME", "FIRST_STRICT_PREGAME")
MAX_SPREAD = 0.10


def chash(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def load_ledger(root):
    rows, viol, files = {}, [], {}
    dup = 0
    for fp in sorted(glob.glob(os.path.join(root, "ledger/*.jsonl"))):
        files[os.path.basename(fp)] = C.sha256_file(fp)
        prev = "GENESIS"
        with open(fp) as fh:
            for i, line in enumerate(fh):
                if not line.strip():
                    continue
                r = json.loads(line)
                body = {k: v for k, v in r.items() if k != "row_hash"}
                if r.get("prev_hash") != prev:
                    viol.append("%s:%d prev_hash" % (os.path.basename(fp), i))
                if chash(body) != r.get("row_hash"):
                    viol.append("%s:%d row_hash" % (os.path.basename(fp), i))
                prev = r.get("row_hash")
                if r["prediction_id"] in rows:
                    dup += 1
                mq = r.get("market_quote") or {}
                rows[r["prediction_id"]] = dict(
                    pid=r["prediction_id"], tk=r["ticker"], fam=r["family"], mid_=r["match_id"], ev=r["event_ticker"], gen=r["generated_at_utc"], sched=r.get("scheduled_start"),
                    models=r.get("models") or {}, mq=dict(yb=mq.get("yes_bid"), ya=mq.get("yes_ask"), ts=mq.get("quote_ts"), priced=mq.get("priced_at"), fresh=mq.get("quote_freshness")),
                    subject=r.get("subject"), pa=r.get("player_a"), pa_id=r.get("player_a_id"), pb_id=r.get("player_b_id"), line=r.get("line"), tour=r.get("tour"), level=r.get("level"),
                    mv=r.get("model_version"), prod=r.get("production_model"), ratings_as_of=r.get("ratings_as_of"), set_index=r.get("set_index"))
    return rows, viol, dup, files


def load_settlements(root):
    S, n, files = {}, 0, {}
    conflicts = 0
    for fp in sorted(glob.glob(os.path.join(root, "settlements/*.jsonl"))):
        files[os.path.basename(fp)] = C.sha256_file(fp)
        for line in open(fp):
            r = json.loads(line)
            n += 1
            old = S.get(r["prediction_id"])
            if old and (old["exchange"] or {}).get("result") != (r["exchange"] or {}).get("result"):
                conflicts += 1
            S[r["prediction_id"]] = r
    return S, n, conflicts, files


def load_truth(root):
    fps = sorted(glob.glob(os.path.join(root, "sports_truth/2026*.jsonl.gz")))
    fp = fps[-1]
    T = {}
    with gzip.open(fp, "rt") as fh:
        for line in fh:
            r = json.loads(line)
            T[r["prediction_id"]] = r
    return T, os.path.basename(fp), C.sha256_file(fp)


def timing_class(s):
    return s.get("timing_class") or (s.get("clv") or {}).get("timing_class")


def independent_y(L, t):
    """Outcome from the independent results (Sackmann/TML/ESPN merged by the repo's canonical match table). None if not resolved.
    MATCH_WINNER: winner id == subject id. TOTAL_GAMES / GAME_SPREAD: only for COMPLETED matches with game counts."""
    ind = (t or {}).get("independent") or {}
    if ind.get("status") != "RESOLVED" or not ind.get("winner_id"):
        return None
    subj_id = L["pa_id"] if L["subject"] == L["pa"] else L["pb_id"]
    if L["fam"] == "MATCH_WINNER":
        return int(str(ind["winner_id"]) == str(subj_id))
    gw, gl = ind.get("games_w"), ind.get("games_l")
    if ind.get("outcome_type") != "COMPLETED" or gw is None or gl is None or L["line"] is None:
        return None
    line = float(L["line"])
    if L["fam"] == "TOTAL_GAMES":
        return int(gw + gl > line)
    if L["fam"] == "GAME_SPREAD":
        won = str(ind["winner_id"]) == str(subj_id)
        return int(((gw - gl) if won else (gl - gw)) > line)
    return None


def build_rows(L, S, T, cnt):
    """Strict pre-game rows with a valid two-sided entry quote, binary exchange outcome, model probability. Every exclusion is counted."""
    out = []
    for pid, s in S.items():
        l = L.get(pid)
        if l is None:
            cnt["settlement_without_ledger_row"] += 1
            continue
        if timing_class(s) != "STRICT_PREGAME":
            cnt["not_strict_pregame:" + str(timing_class(s))] += 1
            continue
        clv = s.get("clv") or {}
        lo = clv.get("first_ball_lower_utc")
        if not lo or not (C.pdt(l["gen"]) < C.pdt(lo)):
            cnt["strict_label_but_no_verifiable_first_ball_lower_bound_or_gen_not_before_it(excluded)"] += 1
            continue
        if not s.get("gradeable"):
            cnt["not_gradeable"] += 1
            continue
        res = (s.get("exchange") or {}).get("result")
        if res not in ("yes", "no"):
            cnt["exchange_result_not_binary:" + str(res)] += 1
            continue
        q = l["models"].get(PRIMARY)
        yb, ya = l["mq"]["yb"], l["mq"]["ya"]
        if yb is None or ya is None or not (0.0 < yb < ya < 1.0) or ya - yb > MAX_SPREAD + 1e-9:
            cnt["no_valid_two_sided_entry_quote_spread<=0.10"] += 1
            continue
        if l["mq"]["ts"] and C.pdt(l["mq"]["ts"]) > C.pdt(l["gen"]):
            cnt["LEAK_quote_after_generated_at"] += 1
            continue
        if l["fam"] == "MATCH_WINNER" and l["subject"] != l["pa"]:
            cnt["match_winner_complement_side_dropped"] += 1
            continue
        y = 1 if res == "yes" else 0
        yi = independent_y(l, T.get(pid))
        if yi is not None and yi != y:
            cnt["exchange_vs_independent_disagree_dropped"] += 1
            continue
        out.append(dict(pid=pid, game=l["mid_"], t=C.pdt(clv.get("first_ball_lower_utc")).isoformat(), gen=l["gen"], mid=(yb + ya) / 2, y=y, tk=l["tk"], fam=l["fam"], models=l["models"],
                        sec_to_fb=clv.get("seconds_entry_to_first_ball"), indep=yi, tour=l["tour"], level=l["level"], conf=clv.get("truth_confidence")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/home/user/data/ten_tennis-data/tennis-edge-finder/data/research")
    ap.add_argument("--out", default="reports/outcome_intel/tennis_audit.json")
    a = ap.parse_args()
    L, viol, dup, lfiles = load_ledger(a.root)
    S, nset, conflicts, sfiles = load_settlements(a.root)
    T, tname, tsha = load_truth(a.root)
    integ = dict(ledger_rows=len(L), ledger_files=len(lfiles), ledger_hash_chain_violations=len(viol), ledger_duplicate_prediction_ids=dup, settlement_rows=nset, unique_settled_prediction_ids=len(S),
                 resettlement_conflicts=conflicts, settlements_without_ledger_row=sum(1 for p in S if p not in L),
                 ledger_rows_unsettled=sum(1 for p in L if p not in S))
    integ["ledger_by_family"] = dict(collections.Counter(l["fam"] for l in L.values()))
    integ["ledger_unique_tickers"] = len({l["tk"] for l in L.values()})
    integ["ledger_unique_matches"] = len({l["mid_"] for l in L.values()})
    integ["timing_class_counts_settled"] = dict(collections.Counter(str(timing_class(s)) for s in S.values()))
    integ["exchange_result_counts"] = dict(collections.Counter(str((s.get("exchange") or {}).get("result")) for s in S.values()))
    integ["outcome_type_counts"] = dict(collections.Counter(str((s.get("sports") or {}).get("outcome_type")) for s in S.values()))
    integ["sports_truth_independent_status"] = dict(collections.Counter(str((t.get("independent") or {}).get("status")) for t in T.values()))
    integ["sports_truth_reconciliation"] = dict(collections.Counter(str((t.get("reconciliation") or {}).get("status")) for t in T.values()))
    # independent vs exchange outcomes over ALL settled+resolved match winners (not only strict rows)
    ag = dis = 0
    for pid, s in S.items():
        l = L.get(pid)
        if not l or l["fam"] != "MATCH_WINNER" or (s.get("exchange") or {}).get("result") not in ("yes", "no"):
            continue
        yi = independent_y(l, T.get(pid))
        if yi is None:
            continue
        if yi == (1 if s["exchange"]["result"] == "yes" else 0):
            ag += 1
        else:
            dis += 1
    integ["match_winner_independent_vs_exchange_all_settled"] = dict(agree=ag, disagree=dis)
    # quote-vs-settlement entry cross check
    mism = chk = 0
    for pid, s in S.items():
        l = L.get(pid)
        c = (s.get("clv") or {})
        if l and c.get("entry_yes_bid") is not None:
            chk += 1
            mism += (c["entry_yes_bid"] != l["mq"]["yb"]) or (c.get("entry_yes_ask") != l["mq"]["ya"])
    integ["entry_quote_ledger_vs_settlement_clv"] = dict(checked=chk, mismatches=int(mism))
    integ["models_available_by_family"] = {f: {m: sum(1 for l in L.values() if l["fam"] == f and l["models"].get(m) is not None) for m in CHALLENGERS} | dict(rows=sum(1 for l in L.values() if l["fam"] == f)) for f in sorted({l["fam"] for l in L.values()})}
    integ["production_model_versions"] = dict(collections.Counter(str(l["mv"]) for l in L.values()))

    cnt = collections.Counter()
    rows = build_rows(L, S, T, cnt)
    # strict rows per family: dedupe per ticker by time (earliest / latest strict pregame observation)
    by_tk = collections.defaultdict(list)
    for r in rows:
        by_tk[(r["fam"], r["tk"])].append(r)
    sel = {h: [] for h in HORIZONS}
    for (fam, tk), lst in by_tk.items():
        lst.sort(key=lambda r: r["gen"])
        sel["FIRST_STRICT_PREGAME"].append(lst[0])
        sel["LAST_STRICT_PREGAME"].append(lst[-1])
    families = sorted({r["fam"] for r in rows} | {l["fam"] for l in L.values()})
    cells_rows = {}
    for h in HORIZONS:
        for fam in families:
            base = [r for r in sel[h] if r["fam"] == fam]
            for ch in CHALLENGERS:
                rr = [dict(game=r["game"], t=r["t"], mid=r["mid"], q=float(r["models"][ch]), y=r["y"], tk=r["tk"], indep=r["indep"], sec=r["sec_to_fb"]) for r in base if r["models"].get(ch) is not None]
                cells_rows[(fam, h, ch)] = (base, rr)
    chal = {"%s|%s|%s" % k: C.run_challenger(v[1]) if v[1] else dict(status="NO_ROWS") for k, v in cells_rows.items()}
    holm_all = C.holm_over(chal)
    holm_prim = C.holm_over({k: v for k, v in chal.items() if k.endswith("|" + PRIMARY)})
    cells = []
    for (fam, h, ch), (base, rr) in sorted(cells_rows.items()):
        key = "%s|%s|%s" % (fam, h, ch)
        c = chal[key]
        nm = len({r["game"] for r in rr})
        if not rr:
            avail = integ["models_available_by_family"].get(fam, {})
            cells.append(dict(sport="TENNIS", family=fam, horizon=h, challenger=ch, is_primary_challenger=(ch == PRIMARY), n_games=len({r["game"] for r in base}), n_contracts=len(base),
                              inputs_available=dict(kalshi_quote=True, model_probability="%s present on %s of %s ledger rows" % (ch, avail.get(ch), avail.get("rows"))),
                              market_metrics=C.market_only([dict(game=r["game"], t=r["t"], mid=r["mid"], y=r["y"]) for r in base]) if base else None,
                              incremental_gain=dict(mean=None, lo=None, hi=None, holm_p=None),
                              status="MISSING_DATA" if base or avail.get("rows") else "MISSING_DATA",
                              reason=("no strict-pregame settled rows with a two-sided quote and a %s probability for this family" % ch) +
                                     ("; family has %s strict rows but no model value" % len(base) if base else "; repair: capture first-ball truth (A/B) before the entry quote so rows become STRICT_PREGAME, and price this family")))
            continue
        st, why = C.classify(c, holm_all.get(key))
        gb = C.gain_block(c, holm_all.get(key))
        gb["holm_p_primary_challenger_only"] = holm_prim.get(key)
        ind = [r["indep"] for r in rr if r["indep"] is not None]
        cells.append(dict(
            sport="TENNIS", family=fam, horizon=h, challenger=ch, is_primary_challenger=(ch == PRIMARY),
            inputs_available=dict(kalshi_quote=True, sift_model_probability=True, first_ball_truth="required and enforced: STRICT_PREGAME rows only",
                                  player_ratings="ratings_as_of date stored on each ledger row (before generation time)", injuries_weather_lineups="not captured"),
            n_games=nm, n_contracts=len({r["tk"] for r in rr}),
            price_coverage=dict(quote_source="ledger market_quote (open_snapshot / capture board) at generated_at; top of book bid/ask only", max_quote_spread=MAX_SPREAD,
                                seconds_to_first_ball_median=float(np.median([r["sec"] for r in rr if r["sec"] is not None])) if any(r["sec"] is not None for r in rr) else None),
            settlement_source="Kalshi exchange result (yes/no; scalar excluded); independent re-derivation from merged Sackmann/TML/ESPN results where RESOLVED (%d of %d rows)" % (len(ind), len(rr)),
            independent_agree=int(sum(1 for x in ind)),  # disagreeing rows were dropped (counted in row_selection_counters)
            market_metrics=C.market_only(rr), model_metrics=C.model_metrics(rr), calibration_bins=C.calibration_bins(rr),
            challenger_detail={k: v for k, v in c.items() if k in ("status", "train_games", "holdout_games", "n_train", "n_holdout", "logloss", "brier", "coef_challenger",
                                                                  "negative_control_gain", "positive_control_gain", "calibration_gain_of_market_alone_logloss", "gain_vs_raw_market_logloss")},
            incremental_gain=gb, status=st, reason=why))
    heads = None
    try:
        heads = subprocess.check_output(["git", "-C", os.path.join(a.root, "..", "..", ".."), "rev-parse", "FETCH_HEAD"], text=True).strip()
    except Exception:
        pass
    report = dict(
        schema="sift-outcome-intel-sport-audit/1", status="RESEARCH_ONLY", sport="TENNIS",
        protocol=dict(rows="STRICT_PREGAME observations only (first-ball lower-bound truth); per-ticker FIRST and LAST strict-pregame observation; MATCH_WINNER keeps the player_a contract only (the two sides are exact complements)",
                      split="chronological by first-ball lower bound: earliest 2/3 matches train, latest 1/3 holdout", ridge=1.0, statistic="holdout logloss gain over train-calibrated market mid (positive = better)",
                      ci="match-cluster bootstrap 2000", multiplicity="Holm over every challenger cell tried (%d); untestable cells enter with p=1; primary-only Holm also reported" % len(chal),
                      primary_challenger=PRIMARY, quote="ledger yes bid/ask mid, two-sided, spread<=0.10", status_rule="see cbb_common.classify"),
        provenance=dict(repo="chmoses98/Tennis-Edge-Finder", branch="tennis-data", head=heads, sports_truth_file=tname, sports_truth_sha256=tsha,
                        ledger_files_sha256=hashlib.sha256("\n".join("%s %s" % kv for kv in sorted(lfiles.items())).encode()).hexdigest(), n_ledger_files=len(lfiles),
                        settlements_sha256=hashlib.sha256("\n".join("%s %s" % kv for kv in sorted(sfiles.items())).encode()).hexdigest(), n_settlement_files=len(sfiles),
                        ledger_range=[min(l["gen"] for l in L.values()), max(l["gen"] for l in L.values())]),
        integrity=integ, row_selection_counters=dict(cnt), strict_rows=len(rows), strict_unique_matches=len({r["game"] for r in rows}),
        strict_by_family={f: dict(rows=sum(1 for r in rows if r["fam"] == f), tickers=len({r["tk"] for r in rows if r["fam"] == f}), matches=len({r["game"] for r in rows if r["fam"] == f})) for f in families},
        cells=C.normalize_cells(cells), status_counts=dict(collections.Counter(c["status"] for c in cells)), control_summary=C.neg_control_summary(chal))
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(report, open(a.out, "w"), indent=1, sort_keys=True, default=str)
    print(json.dumps(report["status_counts"]), report["control_summary"])
    print(json.dumps(integ, default=str)[:3000])
    print(dict(cnt))
    for c in cells:
        g = c["incremental_gain"]
        if g.get("mean") is not None and c["is_primary_challenger"]:
            print(c["family"], c["horizon"], c["n_games"], c["n_contracts"], c["status"], "%.4f [%.4f,%.4f] holm=%.3f" % (g["mean"], g["lo"], g["hi"], g["holm_p"]))


if __name__ == "__main__":
    main()
