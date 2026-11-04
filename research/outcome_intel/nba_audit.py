#!/usr/bin/env python3
"""NBA market-first evidence audit + incremental-information test (RESEARCH_ONLY; no trading, no execution code).

usage: python3 -I research/outcome_intel/nba_audit.py --root /home/user/data/nba --out reports/outcome_intel/nba_audit.json
Inputs (nba-edge-finder, branch data-archive): kalshi/markets(+_delta) boards, kalshi/orderbooks(+_delta), contracts, predictions (SIFT nba-sim p_data_only),
settlements (engine settle-1.0 from ESPN box), boxscores, context/schedule.  Optional: --accounting <dir with wagers/settlements jsonl>.
Question per cell (family x horizon): does the SIFT model probability add logloss information beyond the calibrated contemporaneous market mid?
"""
from __future__ import annotations
import argparse, collections, json, math, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import incremental as I
import nba_nhl_common as C
import nba_shadow as SHADOW

SPORT = "NBA"
MAX_SPREAD = 0.10          # quote must be two-sided with yes_ask - yes_bid <= 10c
MID_LO, MID_HI = 0.03, 0.97  # skip already-decided tails (fixed ex ante, outcome-independent)
MAX_STALE_S = 30 * 60      # board used for the quote must be captured within 30 min before the decision time
PLAYER_STATS = {"pts": ("pts",), "reb": ("reb",), "ast": ("ast",), "fg3m": ("fg3m",), "stl": ("stl",), "blk": ("blk",), "tov": ("tov",), "pra": ("pts", "reb", "ast")}


# ----------------------------------------------------------------------------- independent settlement derivation (from final box only)
def period_points(box, period):
    """(home, away) points for FULL/1H/2H/1Q..4Q from the box's period_scores. OT is part of FULL only (2H = Q3+Q4: flagged ambiguous in OT games)."""
    ps = box["period_scores"]
    keys = {"FULL": list(ps), "1H": ["1Q", "2Q"], "2H": ["3Q", "4Q"], "1Q": ["1Q"], "2Q": ["2Q"], "3Q": ["3Q"], "4Q": ["4Q"]}.get(period)
    if keys is None or any(k not in ps for k in keys):
        return None
    return sum(ps[k][0] for k in keys), sum(ps[k][1] for k in keys)


def derive_outcome(c, box):
    """c: contract dict (stat, period, threshold, comparator, team_id, nba_id). box: final boxscore dict.
    -> ('YES'|'NO'|'VOID'|None, value). None = this module will not derive it (unproven semantics)."""
    if box is None or not box.get("is_final", box.get("status") == "final"):
        return None, None
    stat, per, thr = c.get("stat"), c.get("period"), c.get("threshold")
    if thr is None or (isinstance(thr, float) and math.isnan(thr)) or c.get("comparator") != "gt":
        return None, None
    if c.get("scope") == "player":
        pl = [p for p in box["players"] if p["nba_id"] == c["nba_id"]]
        if len(pl) != 1:
            return "VOID", None
        p = pl[0]
        if not p.get("played") or (p.get("minutes") or 0) <= 0:
            return "VOID", None
        if stat in PLAYER_STATS:
            v = float(sum(p[k] for k in PLAYER_STATS[stat]))
        elif stat in ("double_double", "triple_double"):
            n10 = sum(1 for k in ("pts", "reb", "ast", "stl", "blk") if p[k] >= 10)
            v = float(n10 >= (2 if stat == "double_double" else 3))
        else:
            return None, None
        return ("YES" if v > thr else "NO"), v
    pp = period_points(box, per)
    if pp is None:
        return None, None
    h, a = pp
    tid = c.get("team_id")
    if stat in ("winner", "margin", "team_total"):
        if tid is None or (isinstance(tid, float) and math.isnan(tid)):
            return None, None
        mine, opp = (h, a) if int(tid) == box["home_team_id"] else (a, h) if int(tid) == box["away_team_id"] else (None, None)
        if mine is None:
            return None, None
        v = float(mine if stat == "team_total" else mine - opp)
    elif stat == "total":
        v = float(h + a)
    else:
        return None, None
    return ("YES" if v > thr else "NO"), v



# ----------------------------------------------------------------------------- loaders
def load_contracts(root):
    cs, conflicts, raw = {}, 0, 0
    keys = ("family", "scope", "stat", "period", "game_id", "team_id", "nba_id", "threshold", "comparator", "support", "semantics_confidence")
    for f, r in C.read_jsonl_gz(os.path.join(root, "contracts/dt=*/*.jsonl.gz")):
        raw += 1
        d = {k: r.get(k) for k in keys}
        cur = cs.get(r["ticker"])
        if cur is None:
            cs[r["ticker"]] = d
        elif any(cur[k] != d[k] and not (cur[k] != cur[k] and d[k] != d[k]) for k in ("family", "game_id", "team_id", "nba_id", "threshold", "comparator", "period", "stat")):
            conflicts += 1
    return cs, dict(raw_rows=raw, unique_tickers=len(cs), definition_conflicts=conflicts)


def load_settlements(root):
    rows = [r for _, r in C.read_jsonl_gz(os.path.join(root, "settlements/dt=*/*.jsonl.gz"))]
    cnt = collections.Counter(r["ticker"] for r in rows)
    by = {}
    for r in rows:
        by.setdefault(r["ticker"], []).append(r)
    conflict = sum(1 for t, v in by.items() if len({x["outcome"] for x in v}) > 1)
    latest = {t: max(v, key=lambda x: x["settled_at_utc"]) for t, v in by.items()}
    return latest, dict(rows=len(rows), unique_tickers=len(by), tickers_with_multiple_rows=sum(1 for v in cnt.values() if v > 1), conflicting_resettlements=conflict,
                        outcome_counts=dict(collections.Counter(r["outcome"] for r in latest.values())),
                        sources=dict(collections.Counter(r["box_source"] for r in latest.values())),
                        engine_versions=dict(collections.Counter(r["engine_version"] for r in latest.values())),
                        box_stat_correction_versions=dict(collections.Counter(r["box_stat_correction_version"] for r in latest.values())))


def load_boxes(root):
    rows = [r for _, r in C.read_jsonl_gz(os.path.join(root, "boxscores/dt=*/*.jsonl.gz"))]
    by = collections.defaultdict(list)
    for r in rows:
        by[r["game_id"]].append(r)
    boxes = {g: max(v, key=lambda x: x["fetched_at_utc"]) for g, v in by.items()}
    return boxes, dict(rows=len(rows), games=len(by), games_with_multiple_rows=sum(1 for v in by.values() if len(v) > 1),
                       non_final=sum(1 for b in boxes.values() if not b.get("is_final")), overtime_games=sum(1 for b in boxes.values() if b["n_ot"] > 0),
                       stat_correction_versions=dict(collections.Counter(b["stat_correction_version"] for b in boxes.values())))


def load_schedule(root):
    snaps = collections.defaultdict(list)
    n = 0
    for f, r in C.read_jsonl_gz(os.path.join(root, "context/schedule/dt=*/*.jsonl.gz")):
        n += 1
        snaps[r["game_id"]].append((C.ts(r["_observed_at_utc"]), C.ts(r["start_time_utc"]), r["status"], r.get("actual_tip_utc")))
    out = {}
    statuses = collections.Counter()
    for g, v in snaps.items():
        v.sort()
        for x in v:
            statuses[x[2]] += 1
        final = C.ts(next((x[3] for x in reversed(v) if x[3]), None)) or v[-1][1]
        starts = sorted({x[1] for x in v})
        out[g] = dict(snaps=v, start_final=final, resched=(max(starts) - min(starts)) > 15 * 60, n_distinct_starts=len(starts))
    return out, dict(snapshot_rows=n, games=len(out), status_counts=dict(statuses), games_with_changed_start=sum(1 for x in out.values() if x["resched"]))


def start_known(sch, game, t):
    """Scheduled start as published by the latest schedule snapshot observed at or before t (None if none yet)."""
    g = sch.get(game)
    if not g:
        return None
    best = None
    for obs, st, status, _ in g["snaps"]:
        if obs <= t:
            best = st
        else:
            break
    return best


def load_predictions(root, settled_tickers):
    """Stream predictions; keep only rows whose ticker has a settlement row. Lineage = latest snapshot timestamp referenced by input_snapshot_ids."""
    rows, n_raw, lineage_viol, nulls = [], 0, 0, collections.Counter()
    models = collections.Counter()
    fam_gate = collections.Counter()
    for f, r in C.read_jsonl_gz(os.path.join(root, "predictions/dt=*/*.jsonl.gz")):
        n_raw += 1
        models[r["model_version"]] += 1
        if r["ticker"] not in settled_tickers:
            continue
        t = C.ts(r["predicted_at_utc"])
        lin = max([C.snapshot_ts_from_path(v) or 0 for k, v in (r.get("input_snapshot_ids") or {}).items() if isinstance(v, str)] or [0]) or None
        rows.append((r["ticker"], r["game_id"], t, C.ts(r["data_cutoff_utc"]), r["p_data_only"], lin, r["gate"], bool(r.get("pregame")),
                     C.ts(r.get("market_observed_at_utc")), r.get("p_market"), r.get("market_yes_bid"), r.get("market_yes_ask")))
        nulls["p_data_only_null" if r["p_data_only"] is None else "p_data_only_present"] += 1
        fam_gate[r["gate"]] += 1
    df = pd.DataFrame(rows, columns=["ticker", "game", "t", "cutoff", "q", "lineage_ts", "gate", "pregame", "mkt_obs", "p_market", "yb", "ya"])
    return df, dict(raw_rows=n_raw, kept_rows=len(df), models=dict(models), p_data_only=dict(nulls), gate_counts=dict(fam_gate),
                    p_market_non_null=int(df.p_market.notna().sum()), embedded_quote_non_null=int(df.yb.notna().sum()))


def exchange_crosscheck(acc_dir, derived):
    """Compare the owner's exchange-settled wagers (kalshi-router accounting branch: result WON/LOST from the exchange) to our derived YES/NO."""
    if not acc_dir or not os.path.exists(os.path.join(acc_dir, "settlements.jsonl")):
        return dict(available=False)
    W = {}
    with open(os.path.join(acc_dir, "wagers.jsonl")) as fw:
        for l in fw:
            if l.strip():
                d = json.loads(l)
                W[d["source_bet_key"]] = d
    n = agree = 0
    miss, dis = [], []
    with open(os.path.join(acc_dir, "settlements.jsonl")) as fs:
        lines = fs.readlines()
    for l in lines:
        if not l.strip():
            continue
        s = json.loads(l)
        if s.get("settlement_status") != "SETTLED":
            continue
        tk = s["market_ticker"]
        d = derived.get(tk)
        if d not in ("YES", "NO"):
            miss.append(tk)
            continue
        side = s["side"]
        exch_yes = (s["result"] == "WON") == (side == "YES")
        n += 1
        if exch_yes == (d == "YES"):
            agree += 1
        else:
            dis.append(tk)
    return dict(available=True, exchange_settled_wagers_compared=n, agree=agree, disagree=len(dis), disagree_tickers=dis[:20], not_derivable=len(miss), not_derivable_tickers=miss[:20])


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/home/user/data/nba")
    ap.add_argument("--accounting", default=None, help="dir holding exchange wagers.jsonl/settlements.jsonl (kalshi-router/settle-NBA data/accounting)")
    ap.add_argument("--out", default="reports/outcome_intel/nba_audit.json")
    ap.add_argument("--repo-sha", default=None)
    ap.add_argument("--shadow", default=None, help="checkout of branch nba-shadow-pure (player-prop forecasts vs Kalshi listings)")
    ap.add_argument("--shadow-sha", default=None)
    a = ap.parse_args()
    t0 = time.time()
    root = a.root

    contracts, cinfo = load_contracts(root)
    sett, sinfo = load_settlements(root)
    boxes, binfo = load_boxes(root)
    sch, schinfo = load_schedule(root)
    print("loaded base", time.time() - t0, flush=True)

    # --- independent re-derivation vs engine
    derived, val = {}, {}
    cmp = collections.defaultdict(collections.Counter)
    for tk, s in sett.items():
        c = contracts.get(tk)
        if c is None:
            cmp["_no_contract"]["n"] += 1
            continue
        box = boxes.get(c["game_id"])
        d, v = derive_outcome(c, box)
        derived[tk] = d
        val[tk] = v
        e = s["outcome"]
        if e == "UNSETTLEABLE":
            cmp[c["family"]]["engine_unsettleable_derived_" + str(d)] += 1
        elif d is None:
            cmp[c["family"]]["engine_settled_not_derivable"] += 1
        elif d == "VOID":
            cmp[c["family"]]["engine_settled_derived_void"] += 1
        else:
            cmp[c["family"]]["agree" if d == e else "DISAGREE"] += 1
    disagree = [tk for tk, s in sett.items() if s["outcome"] in ("YES", "NO") and derived.get(tk) in ("YES", "NO") and derived[tk] != s["outcome"]]
    print("derived", len(derived), "disagree", len(disagree), flush=True)

    # final outcome = engine outcome ONLY where independently re-derived value agrees
    y_of = {tk: (1 if s["outcome"] == "YES" else 0) for tk, s in sett.items() if s["outcome"] in ("YES", "NO") and derived.get(tk) == s["outcome"]}
    settled_games = {contracts[tk]["game_id"] for tk in y_of}

    P, pinfo = load_predictions(root, set(y_of))
    print("preds", len(P), time.time() - t0, flush=True)

    # --- time validity of every prediction row that could be used
    fam_of = {tk: contracts[tk]["family"] for tk in y_of}
    P["family"] = P.ticker.map(fam_of)
    P["start_final"] = P.game.map(lambda g: sch.get(g, {}).get("start_final"))
    tv = dict(rows=len(P), pregame_flag_false=int((~P.pregame).sum()), predicted_after_start=int((P.t >= P.start_final).sum()), no_schedule=int(P.start_final.isna().sum()),
              cutoff_after_prediction=int((P.cutoff > P.t + 1).sum()), lineage_after_prediction=int((P.lineage_ts > P.t + 1).sum()), lineage_missing=int(P.lineage_ts.isna().sum()))
    ok = P[(P.pregame) & P.start_final.notna() & (P.t < P.start_final) & (P.cutoff <= P.t + 1) & (P.lineage_ts.isna() | (P.lineage_ts <= P.t + 1))]
    ok = ok[ok.q.notna()]
    # rescheduled games: scheduled start at decision time must match the final start (within 15 min)
    sk = [start_known(sch, g, t) for g, t in zip(ok.game.values, ok.t.values)]
    ok = ok.assign(start_known=sk)
    resched_drop = ok[(ok.start_known.isna()) | ((ok.start_known - ok.start_final).abs() > 15 * 60)]
    ok = ok.drop(resched_drop.index)
    tv["rows_usable_with_model_time_valid"] = len(ok)
    tv["dropped_rescheduled_or_no_schedule_known"] = len(resched_drop)

    # --- horizon selection
    cand = [dict(ticker=r.ticker, game=r.game, t=r.t, start=r.start_final, q=r.q, family=r.family) for r in ok.itertuples()]
    sel = C.select_per_horizon(cand)
    print("selected", len(sel), time.time() - t0, flush=True)

    # --- boards: quote lookups at each selected decision time + pregame coverage for every settled/derivable ticker
    starts = {tk: sch[contracts[tk]["game_id"]]["start_final"] for tk in contracts if contracts[tk]["game_id"] in sch}
    want = set(y_of)
    lookups = [(p["ticker"], p["t"], (p["ticker"], lab)) for (tk, lab), p in sel.items()]
    resolved, cov, integ = C.board_sweep(root, lookups, starts=starts, want=want)
    print("swept", time.time() - t0, integ, flush=True)
    ob, n_ob_delta = C.orderbook_coverage(root, want)
    print("orderbooks", len(ob), time.time() - t0, flush=True)

    # --- floor_strike vs parsed contract threshold (independent check of the contract parser)
    fs_n = fs_bad = 0
    for tk, c in cov.items():
        if "floor_strike" in c and contracts[tk].get("threshold") is not None and contracts[tk]["threshold"] == contracts[tk]["threshold"] and contracts[tk]["scope"] != "other":
            fs_n += 1
            if abs(float(c["floor_strike"]) - contracts[tk]["threshold"]) > 1e-9:
                fs_bad += 1

    # --- build rows
    rows, drops = [], collections.Counter()
    for (tk, lab), p in sel.items():
        rs = resolved[(tk, lab)]
        q = C.quote(rs["slim"])
        if rs["board_t"] is None or q is None:
            drops["no_board_quote"] += 1
            continue
        if p["t"] - rs["board_t"] > MAX_STALE_S:
            drops["stale_board"] += 1
            continue
        if not q["two_sided"] or q["spread"] > MAX_SPREAD:
            drops["not_two_sided_or_wide"] += 1
            continue
        if not (MID_LO <= q["mid"] <= MID_HI):
            drops["mid_in_decided_tail"] += 1
            continue
        if q["mid"] is None or not (0 < p["q"] < 1):
            drops["bad_prob"] += 1
            continue
        rows.append(dict(game=p["game"], t=p["t"], mid=q["mid"], q=float(p["q"]), y=y_of[tk], fam=p["family"], hor=lab, ticker=tk, spread=q["spread"],
                         bid_size=q["bid_size"], ask_size=q["ask_size"], stale=p["t"] - rs["board_t"], hb=(p["start"] - p["t"]) / 3600))
    print("rows", len(rows), dict(drops), flush=True)

    # --- family-level ledger (every observed family, tested or not)
    fam_all = collections.defaultdict(dict)
    for fam in sorted({c["family"] for c in contracts.values()}):
        tks = [tk for tk, c in contracts.items() if c["family"] == fam]
        eng = collections.Counter(sett[tk]["outcome"] if tk in sett else "NOT_SETTLED" for tk in tks)
        used = [tk for tk in tks if tk in y_of]
        fam_all[fam] = dict(contracts_observed=len(tks), games_observed=len({contracts[tk]["game_id"] for tk in tks}), engine_outcomes=dict(eng),
                            settled_yes_no_rederived_agree=len(used), games_settled=len({contracts[tk]["game_id"] for tk in used}),
                            derivation_vs_engine=dict(cmp.get(fam, {})), support=dict(collections.Counter(contracts[tk]["support"] for tk in tks)))

    # --- cells
    R = pd.DataFrame(rows)
    cells, cell_rows = {}, {}
    fams = sorted(fam_all)
    for fam in fams:
        for lab, _, _, _ in C.HORIZONS:
            sub = [r for r in rows if r["fam"] == fam and r["hor"] == lab]
            cell_rows[(fam, lab)] = sub
    for lab, _, _, _ in C.HORIZONS:  # pooled across game-level and player families (exploratory, included in Holm)
        cell_rows[("ALL_MODELLED", lab)] = [r for r in rows if r["hor"] == lab]
    shadow_rows, shadow_info = ([], {})
    if a.shadow:
        shadow_rows, shadow_info = SHADOW.build(a.shadow)
        for r in shadow_rows:
            cell_rows.setdefault((r["fam"], r["hor"]), []).append(r)
    shadow_keys = sorted(k for k in cell_rows if "[shadow:" in k[0])
    results = {}
    for k, sub in cell_rows.items():
        if len(sub) == 0:
            continue
        results[k] = C.run_cell(sub)
    okk = [k for k, r in results.items() if r["status"] == "OK"]
    adj = I.holm([results[k]["gain_vs_calibrated_market_logloss"]["p"] for k in okk]) if okk else []
    holm_of = dict(zip(okk, adj))

    # --- schema output
    out_cells = []
    tick_set = lambda fam: [tk for tk in y_of if fam_of[tk] == fam]
    for fam in fams:
        fi = fam_all[fam]
        for lab, tgt, lo, hi in C.HORIZONS:
            k = (fam, lab)
            sub = cell_rows[k]
            res = results.get(k)
            cell = dict(sport=SPORT, family=fam, horizon=lab, horizon_window_hours_before_start=[lo, hi])
            tks = tick_set(fam)
            cov_f = [cov[tk] for tk in tks if tk in cov]
            if not sub:
                reason, status = None, "MISSING_DATA"
                if fi["settled_yes_no_rederived_agree"] == 0:
                    eng = fi["engine_outcomes"]
                    reason = (f"no contract of this family has a settlement we can verify: engine outcomes {eng}; the settlement engine marks them UNSETTLEABLE (semantics not proven / unsupported stat). "
                              "Repair: prove contract semantics against the Kalshi rules text and add the stat to the settlement engine (and capture the exchange result).")
                else:
                    n_pred = int(((P.family == fam)).sum())
                    reason = (f"{fi['settled_yes_no_rederived_agree']} settled contracts exist but none has a time-valid model probability AND a two-sided pregame quote within {MAX_STALE_S//60} min inside this horizon window "
                              f"(model rows for family in archive: {n_pred}). Repair: capture the model at this horizon for every listed contract and keep quotes (depth) at the same time.")
                cell.update(inputs_available=[], n_games=0, n_contracts=0, price_coverage=None, settlement_source=_ss(fi), market_metrics=None, model_metrics=None,
                            incremental_gain=None, status=status, reason=reason)
                out_cells.append(cell)
                continue
            n_games = len({r["game"] for r in sub})
            g = None
            if res["status"] == "OK":
                g = dict(res["gain_vs_calibrated_market_logloss"])
                g["holm_p"] = holm_of[k]
                gain = dict(mean=g["mean"], lo=g["lo"], hi=g["hi"], holm_p=g["holm_p"], p_uncorrected=g["p"], n_holdout_rows=g["n"], n_holdout_games=g["n_games"],
                            gain_vs_raw_market=res["gain_vs_raw_market_logloss"], negative_control=res["negative_control"], positive_control=res["positive_control"])
                st, why = C.classify(res, holm_of[k], n_tested=len(okk))
                mm = dict(holdout_logloss_raw_market=res["logloss"]["raw_market"], holdout_logloss_calibrated_market=res["logloss"]["calibrated_market"],
                          holdout_brier_raw_market=res["brier"]["raw_market"], holdout_brier_calibrated_market=res["brier"]["calibrated_market"],
                          calibration_gain_of_market_alone=res["calibration_gain_of_market_alone_logloss"], coef_calibration=res["coef_baseline"])
                md = dict(model="nba-sim-0.1.0 p_data_only (market-independent)", holdout_alone=res["q_alone_holdout"], holdout_logloss_challenger=res["logloss"]["challenger"],
                          holdout_brier_challenger=res["brier"]["challenger"], coef_challenger=res["coef_challenger"], train_games=res["train_games"], holdout_games=res["holdout_games"],
                          n_train_rows=res["n_train"], n_holdout_rows=res["n_holdout"])
            else:
                gain, mm, md = None, None, dict(train_games=res["train_games"], holdout_games=res["holdout_games"], n_train_rows=res["n_train"], n_holdout_rows=res["n_holdout"])
                st, why = C.classify(res, None)
            sp = np.array([r["spread"] for r in sub])
            cell.update(
                inputs_available=_inputs(fi, sub),
                n_games=n_games, n_contracts=len({r["ticker"] for r in sub}), n_rows=len(sub),
                price_coverage=dict(
                    family_settled_contracts=len(tks), family_contracts_with_pregame_two_sided_board=sum(1 for c in cov_f if c["n_two_sided"] > 0),
                    cell_contracts_with_quote_at_decision=len({r["ticker"] for r in sub}), median_spread_at_decision=float(np.median(sp)),
                    median_staleness_s=float(np.median([r["stale"] for r in sub])), median_hours_before_start=float(np.median([r["hb"] for r in sub])),
                    median_bid_size=float(np.nanmedian([r["bid_size"] if r["bid_size"] is not None else np.nan for r in sub])),
                    median_ask_size=float(np.nanmedian([r["ask_size"] if r["ask_size"] is not None else np.nan for r in sub])),
                    contracts_in_orderbook_archive=sum(1 for r in {r2["ticker"] for r2 in sub} if r in ob), quote_source="Kalshi board checkpoints+chained deltas (bid/ask/size); full-depth ladder only for <=300 tickers per capture"),
                settlement_source=_ss(fi), market_metrics=mm, model_metrics=md, incremental_gain=gain, status=st, reason=why)
            out_cells.append(cell)
    for lab, tgt, lo, hi in C.HORIZONS:
        k = ("ALL_MODELLED", lab)
        sub = cell_rows[k]
        res = results.get(k)
        if not sub or res is None:
            continue
        cell = dict(sport=SPORT, family="ALL_MODELLED(pooled, exploratory)", horizon=lab, horizon_window_hours_before_start=[lo, hi], inputs_available=["SIFT p_data_only", "Kalshi board quote"],
                    n_games=len({r["game"] for r in sub}), n_contracts=len({r["ticker"] for r in sub}), n_rows=len(sub), price_coverage=None,
                    settlement_source="engine settle-1.0 (ESPN box), independently re-derived; not the Kalshi result")
        if res["status"] == "OK":
            g = res["gain_vs_calibrated_market_logloss"]
            st, why = C.classify(res, holm_of[k], n_tested=len(okk))
            cell.update(market_metrics=dict(holdout_logloss_raw_market=res["logloss"]["raw_market"], holdout_logloss_calibrated_market=res["logloss"]["calibrated_market"]),
                        model_metrics=dict(holdout_alone=res["q_alone_holdout"], holdout_logloss_challenger=res["logloss"]["challenger"], holdout_games=res["holdout_games"]),
                        incremental_gain=dict(mean=g["mean"], lo=g["lo"], hi=g["hi"], holm_p=holm_of[k], p_uncorrected=g["p"], negative_control=res["negative_control"], positive_control=res["positive_control"]),
                        status=st, reason=why)
        else:
            st, why = C.classify(res, None)
            cell.update(market_metrics=None, model_metrics=None, incremental_gain=None, status=st, reason=why)
        out_cells.append(cell)

    for k in shadow_keys:
        sub, res = cell_rows[k], results.get(k)
        cell = dict(sport=SPORT, family=k[0], horizon=k[1], challenger="PURE shadow forecast (nba-shadow-pure)", n_games=len({r["game"] for r in sub}), n_contracts=len({r["ticker"] for r in sub}), n_rows=len(sub),
                    inputs_available=[dict(name="pure_forecast.v1 ladder P(stat>=rung|plays)", availability_time="as_of; source_max_observed_at <= as_of (checked per row)", established=True),
                                      dict(name="Kalshi listing quote (bid/ask cents)", availability_time="board_observed_at <= as_of (checked per row), listed_by_as_of", established=True)],
                    price_coverage=dict(median_spread_at_decision=float(np.median([r["spread"] for r in sub])), median_staleness_s=float(np.median([r["stale"] for r in sub])),
                                        median_hours_before_start=float(np.median([r["hb"] for r in sub])), depth="not archived in the listing rows (bid/ask only)"),
                    settlement_source="ESPN summary box stat from shadow outcomes/gate (independent of the data-archive settlement engine); DNP rows void and excluded; not the Kalshi result")
        if res and res["status"] == "OK":
            g = res["gain_vs_calibrated_market_logloss"]
            st, why = C.classify(res, holm_of[k], n_tested=len(okk))
            cell.update(market_metrics=dict(holdout_logloss_raw_market=res["logloss"]["raw_market"], holdout_logloss_calibrated_market=res["logloss"]["calibrated_market"],
                                            holdout_brier_raw_market=res["brier"]["raw_market"], holdout_brier_calibrated_market=res["brier"]["calibrated_market"]),
                        model_metrics=dict(holdout_alone=res["q_alone_holdout"], holdout_logloss_challenger=res["logloss"]["challenger"], holdout_games=res["holdout_games"]),
                        incremental_gain=dict(mean=g["mean"], lo=g["lo"], hi=g["hi"], holm_p=holm_of[k], p_uncorrected=g["p"], negative_control=res["negative_control"], positive_control=res["positive_control"]),
                        status=st, reason=why)
        else:
            st, why = C.classify(res, None)
            cell.update(market_metrics=None, model_metrics=None, incremental_gain=None, status=st, reason=why)
        out_cells.append(cell)

    cx = exchange_crosscheck(a.accounting, derived)
    digests, roll = C.file_digests(root, ["manifest.jsonl", "EVIDENCE_HEALTH.json", "STATUS_*.json", "predictions/*/*.gz", "settlements/*/*.gz", "contracts/*/*.gz",
                                          "boxscores/*/*.gz", "context/schedule/*/*.gz", "kalshi/markets/*/*.gz", "kalshi/markets_delta/*/*.gz",
                                          "kalshi/orderbooks/*/*.gz", "kalshi/orderbooks_delta/*/*.gz"])
    if a.shadow:
        d2, roll2 = C.file_digests(a.shadow, ["manifest.jsonl", "chain.jsonl", "projections/*/conditional/*/*.gz", "market/listings/*/*.gz", "outcomes/gate/*/*.gz", "captures/*/*.gz"])
        digests.update({"nba-shadow-pure/" + k: v for k, v in d2.items()})
        roll = C.hashlib.sha256((roll + roll2).encode()).hexdigest()
    status_counts = collections.Counter(c["status"] for c in out_cells)
    report = dict(
        schema="sift-outcome-intel-nba-audit/1", status="RESEARCH_ONLY", sport=SPORT, generated_note="deterministic given inputs; seeds fixed in incremental.py",
        inputs=dict(repo="chmoses98/nba-edge-finder", branch="data-archive", commit_sha=a.repo_sha, input_rollup_sha256=roll, n_input_files=len(digests),
                    file_sha256_sample=dict(list(digests.items())[:5]), file_sha256_path="reports/outcome_intel/nba_input_sha256.json"),
        protocol=dict(question="does SIFT nba-sim p_data_only add logloss info beyond the calibrated contemporaneous Kalshi mid?",
                      split="earliest 2/3 of games by first decision time = train; latest 1/3 = holdout; ridge=1 fixed; one pass", horizons=[list(h) for h in C.HORIZONS],
                      row_filters=dict(max_yes_spread=MAX_SPREAD, mid_range=[MID_LO, MID_HI], max_board_staleness_s=MAX_STALE_S, one_prediction_per_contract_horizon="closest to horizon target"),
                      multiplicity="Holm over every cell with enough data (family x horizon + pooled)", n_cells_total=len(out_cells), n_cells_tested=len(okk),
                      status_rule="see nba_nhl_common.classify"),
        independent_events=dict(games_with_final_box=binfo["games"], games_with_any_contract=len({c["game_id"] for c in contracts.values()}), games_with_verified_settled_contract=len(settled_games),
                                games_in_tested_rows=len({r["game"] for r in rows}), note="the game is the independent unit; every interval resamples games"),
        data_quality=dict(contracts=cinfo, settlements=sinfo, boxscores=binfo, schedule=schinfo, predictions=pinfo, time_validity=tv, board_integrity=integ,
                          orderbook_archive=dict(tickers_covered_of_settled=len(ob), settled_yes_no_tickers=len(want), orderbook_delta_files=n_ob_delta),
                          floor_strike_vs_parsed_threshold=dict(compared=fs_n, mismatched=fs_bad), row_drops=dict(drops),
                          engine_vs_independent_derivation=dict(engine_yes_no=sum(1 for s in sett.values() if s["outcome"] in ("YES", "NO")), derivable_and_compared=sum(1 for tk, s in sett.items() if s["outcome"] in ("YES", "NO") and derived.get(tk) in ("YES", "NO")),
                                                                disagreements=len(disagree), disagreement_tickers=disagree[:30], by_family={f: dict(v) for f, v in cmp.items()}),
                          kalshi_official_result=dict(in_archive=False, reason="board `result` field is empty on every captured market (resolved markets leave the board); the archive contains no Kalshi settlement values. Only exchange evidence = owner wagers on branch kalshi-router/settle-NBA (cross-check below)"),
                          exchange_crosscheck=cx, shadow_pure=dict(commit_sha=a.shadow_sha, **shadow_info)),
        families=fam_all, status_counts=dict(status_counts), cells=out_cells, elapsed_s=time.time() - t0)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(report, open(a.out, "w"), indent=1, sort_keys=True, default=_jd)
    json.dump(digests, open(os.path.join(os.path.dirname(a.out) or ".", "nba_input_sha256.json"), "w"), indent=0, sort_keys=True)
    print(dict(status_counts))
    for c in out_cells:
        g = c.get("incremental_gain")
        if g:
            print(c["family"], c["horizon"], c["n_games"], c["n_rows"], "gain %.4f [%.4f,%.4f] holm=%.3f" % (g["mean"], g["lo"], g["hi"], g["holm_p"]), c["status"])


def _ss(fi):
    return "engine settle-1.0 outcome from ESPN summary box (derived, not Kalshi's result); independently re-derived from final box scores here; exchange cross-check on owner wagers only"


def _inputs(fi, sub):
    return [dict(name="SIFT nba-sim p_data_only", availability_time="predicted_at_utc (pregame; data_cutoff_utc <= predicted_at; lineage snapshot timestamps <= predicted_at)", established=True),
            dict(name="Kalshi board quote (bid/ask/size)", availability_time="board captured_at_utc <= decision time", established=True),
            dict(name="injury/roster/schedule context snapshots", availability_time="file timestamp in input_snapshot_ids", established=True, used_directly_as_challenger=False)]


def _jd(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (set,)):
        return sorted(o)
    return str(o)


if __name__ == "__main__":
    main()
