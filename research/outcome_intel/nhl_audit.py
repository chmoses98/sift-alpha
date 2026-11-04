#!/usr/bin/env python3
"""NHL market-first evidence audit + incremental-information test (RESEARCH_ONLY; no trading, no execution code).

usage: python3 -I research/outcome_intel/nhl_audit.py --root /home/user/data/nhl --out reports/outcome_intel/nhl_audit.json
Inputs (NHL-edge-finder, branch data-archive): kalshi boards, contracts, predictions (V1 p_data_only), predictions_v2 (V2), predictions_player (PLAYER_SIM_V1),
predictions_oa (OA arms), settlements, results, player_events/{goals,players,goalies}, context/{schedule,sportsbook_odds}.
Challengers per cell (family x horizon): SIFT V1, SIFT V2, PLAYER_SIM_V1, OA arms (game level), and the sportsbook consensus (an external pregame input) for the moneyline.
"""
from __future__ import annotations
import argparse, collections, json, math, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import incremental as I
import nba_nhl_common as C
from nba_audit import _jd, exchange_crosscheck

SPORT = "NHL"
MAX_SPREAD = 0.10
MID_LO, MID_HI = 0.03, 0.97
MAX_STALE_S = 30 * 60
HZ = (("T_12H", 12.0, 10.0, 14.0), ("T_6H", 6.0, 4.5, 7.5), ("T_1H", 1.0, 0.5, 1.5), ("CLOSING", 0.15, 0.0, 0.5))
GAME_FAMS = ("game_winner", "game_spread", "game_total", "team_total", "period_winner", "period_spread", "period_total")
PLAYER_FAMS = ("player_goals", "player_assists", "player_points", "first_goal", "goalie_saves")
SB_MAX_AGE_S = 3 * 3600


# ----------------------------------------------------------------------------- independent derivation
def game_scores(res, so_variant="incl"):
    """(home, away) final goals. 'incl' = NHL final (shootout winner +1, the engine's FINAL_INCL_OT_SO); 'excl' = remove the single shootout goal."""
    h, a = res["home_final"], res["away_final"]
    if so_variant == "excl" and res["last_period_type"] == "SO":
        if h > a:
            h -= 1
        elif a > h:
            a -= 1
    return h, a


def period_goals(goals, home_id, away_id, period):
    h = sum(1 for g in goals if g["period"] == period and g["team_id"] == home_id)
    a = sum(1 for g in goals if g["period"] == period and g["team_id"] == away_id)
    return h, a


def _isnan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def derive_outcome(c, res, goals=None, players=None, goalies=None, player_id=None):
    """Independent derivation from final scores / goal events / player rows. -> (outcome 'YES'|'NO'|'VOID'|'SO_AMBIGUOUS'|None, value).
    None = not derivable here. c: contract dict."""
    fam, thr = c["family"], c.get("threshold")
    if res is None or res.get("status") != "final":
        return None, None
    tid = c.get("team_id")
    if fam in ("game_winner", "game_spread", "game_total", "team_total"):
        outs = []
        # the moneyline is decided by the shootout; spreads/totals/team totals depend on whether the SO goal counts -> evaluate both and flag disagreement
        for var in (("incl",) if fam == "game_winner" else ("incl", "excl")):
            h, a = game_scores(res, var)
            if fam == "game_total":
                v = h + a
            else:
                if _isnan(tid):
                    return None, None
                mine, opp = (h, a) if int(tid) == res["home_team_id"] else (a, h) if int(tid) == res["away_team_id"] else (None, None)
                if mine is None:
                    return None, None
                v = mine if fam == "team_total" else mine - opp
            outs.append((v, (v > thr) if not _isnan(thr) else None))
        if _isnan(thr):
            return None, None
        if len(outs) > 1 and outs[0][1] != outs[1][1]:
            return "SO_AMBIGUOUS", float(outs[0][0])
        return ("YES" if outs[0][1] else "NO"), float(outs[0][0])
    if fam in ("period_winner", "period_spread", "period_total"):
        if goals is None or c.get("period") not in ("P1", "P2", "P3"):
            return None, None
        h, a = period_goals(goals, res["home_team_id"], res["away_team_id"], int(c["period"][1]))
        if fam == "period_total":
            v = h + a
        else:
            if _isnan(tid):
                if fam == "period_winner" and str(c.get("ticker", "")).endswith("-TIE"):
                    return ("YES" if h == a else "NO"), float(h - a)
                return None, None
            v = (h - a) if int(tid) == res["home_team_id"] else (a - h)
        thr = 0.0 if (fam == "period_winner" and _isnan(thr)) else thr
        return ("YES" if v > thr else "NO"), float(v)
    if fam in ("player_goals", "player_assists", "player_points"):
        if players is None or player_id is None:
            return None, None
        row = players.get((str(res["game_id"]), int(player_id)))
        if row is None or (row.get("toi_s") or 0) <= 0:
            return "VOID", None
        v = float(row[{"player_goals": "goals", "player_assists": "assists", "player_points": "points"}[fam]])
        return ("YES" if v > thr else "NO"), v
    if fam == "first_goal":
        if goals is None or players is None or player_id is None:
            return None, None
        row = players.get((str(res["game_id"]), int(player_id)))
        if row is None or (row.get("toi_s") or 0) <= 0 or not goals:
            return "VOID", None
        first = min(goals, key=lambda g: (g["period"], g["t_s"]))
        return ("YES" if first["scorer_id"] == int(player_id) else "NO"), float(first["scorer_id"] == int(player_id))
    if fam == "goalie_saves":
        if goalies is None or player_id is None:
            return None, None
        row = goalies.get((str(res["game_id"]), int(player_id)))
        if row is None or (row.get("toi_s") or 0) <= 0:
            return "VOID", None
        return ("YES" if row["saves"] > thr else "NO"), float(row["saves"])
    return None, None


# ----------------------------------------------------------------------------- loaders
def load_contracts(root):
    keys = ("family", "scope", "stat", "period", "game_id", "team_id", "player_id", "threshold", "comparator", "support", "semantics_confidence", "settles_on")
    cs, conflicts, raw = {}, 0, 0
    for f, r in C.read_jsonl_gz(os.path.join(root, "contracts/dt=*/*.jsonl.gz")):
        raw += 1
        d = {k: r.get(k) for k in keys}
        cur = cs.get(r["ticker"])
        if cur is None:
            cs[r["ticker"]] = d
        elif any(cur[k] != d[k] and not (_isnan(cur[k]) and _isnan(d[k])) for k in ("family", "game_id", "team_id", "threshold", "comparator", "period", "stat")):
            conflicts += 1
    return cs, dict(raw_rows=raw, unique_tickers=len(cs), definition_conflicts=conflicts)


def load_settlements(root):
    rows = [r for _, r in C.read_jsonl_gz(os.path.join(root, "settlements/dt=*/*.jsonl.gz"))]
    by = collections.defaultdict(list)
    for r in rows:
        by[r["ticker"]].append(r)
    latest = {t: max(v, key=lambda x: x["settled_at_utc"]) for t, v in by.items()}
    multi = {t: v for t, v in by.items() if len(v) > 1}
    changed = [t for t, v in multi.items() if len({x["outcome"] for x in v}) > 1]
    ex = {t: [(x["outcome"], x["settled_at_utc"], x["engine_version"]) for x in multi[t]] for t in changed[:10]}
    return latest, dict(rows=len(rows), unique_tickers=len(by), tickers_with_multiple_rows=len(multi), resettled_with_changed_outcome=len(changed), resettled_examples=ex,
                        outcome_counts=dict(collections.Counter(r["outcome"] for r in latest.values())), engines=dict(collections.Counter(r["engine_version"] for r in latest.values())),
                        sources=dict(collections.Counter(r["result_source"] for r in latest.values())),
                        stat_correction_versions=dict(collections.Counter(r["stat_correction_version"] for r in latest.values())))


def load_results(root):
    rows = [r for _, r in C.read_jsonl_gz(os.path.join(root, "results/dt=*/*.jsonl.gz"))]
    by = collections.defaultdict(list)
    for r in rows:
        by[r["game_id"]].append(r)
    res = {g: max(v, key=lambda x: x["fetched_at_utc"]) for g, v in by.items()}
    return res, dict(rows=len(rows), games=len(res), games_with_multiple_rows=sum(1 for v in by.values() if len(v) > 1), non_final=sum(1 for r in res.values() if r["status"] != "final"),
                     last_period_types=dict(collections.Counter(r["last_period_type"] for r in res.values())), stat_correction_versions=dict(collections.Counter(r["stat_correction_version"] for r in res.values())))


def load_events(root):
    goals = collections.defaultdict(list)
    for f, r in C.read_jsonl_gz(os.path.join(root, "player_events/goals/dt=*/*.jsonl.gz")):
        goals[str(r["game_id"])].append(r)
    players, goalies = {}, {}
    for f, r in C.read_jsonl_gz(os.path.join(root, "player_events/players/dt=*/*.jsonl.gz")):
        players[(str(r["game_id"]), int(r["player_id"]))] = r
    for f, r in C.read_jsonl_gz(os.path.join(root, "player_events/goalies/dt=*/*.jsonl.gz")):
        goalies[(str(r["game_id"]), int(r["player_id"]))] = r
    return goals, players, goalies


def load_schedule(root):
    snaps = collections.defaultdict(list)
    n = 0
    for f, r in C.read_jsonl_gz(os.path.join(root, "context/schedule/dt=*/*.jsonl.gz")):
        n += 1
        snaps[r["game_id"]].append((C.ts(r["_observed_at_utc"]), C.ts(r["start_time_utc"]), r["status"]))
    out = {}
    for g, v in snaps.items():
        v.sort()
        starts = sorted({x[1] for x in v})
        out[g] = dict(snaps=v, start_final=v[-1][1], resched=(starts[-1] - starts[0]) > 15 * 60, n_distinct_starts=len(starts))
    return out, dict(snapshot_rows=n, games=len(out), games_with_changed_start=sum(1 for x in out.values() if x["resched"]),
                     status_counts=dict(collections.Counter(x[2] for v in snaps.values() for x in v)))


def start_known(sch, game, t):
    g = sch.get(game)
    best = None
    if g:
        for obs, st, _ in g["snaps"]:
            if obs <= t:
                best = st
            else:
                break
    return best


def load_sportsbook(root):
    """-> {game_id: {provider: [(obs_t, side, decimal_odds)]}}"""
    out = collections.defaultdict(lambda: collections.defaultdict(list))
    n = 0
    for f, r in C.read_jsonl_gz(os.path.join(root, "context/sportsbook_odds/dt=*/*.jsonl.gz")):
        n += 1
        try:
            v = float(r["value"])
        except (TypeError, ValueError):
            continue
        if v > 1.0:
            out[str(r["game_id"])][r["provider"]].append((C.ts(r["_observed_at_utc"]), r["side"], v))
    return out, n


def sportsbook_home_prob(sb, game, t):
    """Mean over providers of the de-vigged home win probability from each provider's latest home+away pair observed at or before t (and within 3h)."""
    ps = []
    for prov, obs in sb.get(game, {}).items():
        last = {}
        for ot, side, v in obs:
            if ot <= t and t - ot <= SB_MAX_AGE_S:
                if side not in last or ot >= last[side][0]:
                    last[side] = (ot, v)
        if "home" in last and "away" in last and abs(last["home"][0] - last["away"][0]) <= 1800:
            ih, ia = 1 / last["home"][1], 1 / last["away"][1]
            ps.append(ih / (ih + ia))
    return (float(np.mean(ps)), len(ps)) if ps else (None, 0)


def pred_source_rows(root, subdir, tickers, fields, qfield, extra=None):
    out, raw, qnull = [], 0, 0
    for f, r in C.read_jsonl_gz(os.path.join(root, subdir, "dt=*/*.jsonl.gz")):
        raw += 1
        if r["ticker"] not in tickers:
            continue
        q = r.get(qfield)
        if q is None:
            qnull += 1
            continue
        lin = max([C.snapshot_ts_from_path(v) or 0 for v in (r.get("input_snapshot_ids") or {}).values() if isinstance(v, str)] or [0]) or None
        out.append(dict(ticker=r["ticker"], game=str(r["game_id"]), t=C.ts(r["predicted_at_utc"]), cutoff=C.ts(r.get("data_cutoff_utc")), q=float(q), lineage_ts=lin,
                        emb_bid=r.get("market_yes_bid"), emb_ask=r.get("market_yes_ask"), emb_mid=r.get("p_market"), mins=r.get("minutes_to_start"), pregame=bool(r.get("pregame", True))))  # V2 rows carry no flag: pregame-ness is enforced by predicted_at < scheduled start below
    return out, dict(raw_rows=raw, rows_for_verified_tickers_with_q=len(out), q_null_for_verified_tickers=qnull)


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/home/user/data/nhl")
    ap.add_argument("--out", default="reports/outcome_intel/nhl_audit.json")
    ap.add_argument("--repo-sha", default=None)
    ap.add_argument("--accounting", default=None, help="dir with exchange wagers.jsonl/settlements.jsonl (kalshi-router/settle-NHL data/accounting)")
    a = ap.parse_args()
    t0 = time.time()
    root = a.root
    contracts, cinfo = load_contracts(root)
    sett, sinfo = load_settlements(root)
    results, rinfo = load_results(root)
    goals, players, goalies = load_events(root)
    sch, schinfo = load_schedule(root)
    sb, sb_n = load_sportsbook(root)
    print("loaded base", time.time() - t0, flush=True)

    # player_id per player ticker from the player-model archive (contracts carry none)
    pid = {}
    for f, r in C.read_jsonl_gz(os.path.join(root, "predictions_player/dt=*/*.jsonl.gz")):
        if r.get("player_id") is not None:
            pid.setdefault(r["ticker"], int(r["player_id"]))
    print("player ids", len(pid), time.time() - t0, flush=True)

    # goal-event completeness: only games whose goal rows add up to the final score (minus the shootout goal) may be used for period / first-goal derivations
    goals_ok = {g for g, r in results.items() if len(goals.get(g, [])) == r["home_final"] + r["away_final"] - (1 if r["last_period_type"] == "SO" else 0)}

    # --- derivation vs engine
    derived, cmp = {}, collections.defaultdict(collections.Counter)
    for tk, s in sett.items():
        c = contracts.get(tk)
        if c is None:
            cmp["_no_contract"]["n"] += 1
            continue
        g = str(c["game_id"])
        d, v = derive_outcome(dict(c, ticker=tk), results.get(g), goals.get(g) if g in goals_ok else None, players, goalies, pid.get(tk))
        derived[tk] = d
        e = s["outcome"]
        fam = c["family"]
        if e == "UNSETTLEABLE":
            cmp[fam]["engine_unsettleable_derived_" + str(d)] += 1
        elif d is None:
            cmp[fam]["engine_settled_not_derivable"] += 1
        elif d in ("VOID", "SO_AMBIGUOUS"):
            cmp[fam]["engine_settled_derived_" + d.lower()] += 1
        else:
            cmp[fam]["agree" if d == e else "DISAGREE"] += 1
    disagree = [tk for tk, s in sett.items() if s["outcome"] in ("YES", "NO") and derived.get(tk) in ("YES", "NO") and derived[tk] != s["outcome"]]
    y_of = {tk: (1 if s["outcome"] == "YES" else 0) for tk, s in sett.items() if s["outcome"] in ("YES", "NO") and derived.get(tk) == s["outcome"]}
    print("derived", len(derived), "disagree", len(disagree), "verified", len(y_of), flush=True)
    fam_of = {tk: contracts[tk]["family"] for tk in y_of}
    tickers = set(y_of)

    # --- candidate rows per challenger
    cand = collections.defaultdict(list)
    srcinfo = {}
    for name, sub, qf in (("SIFT_V1", "predictions", "p_data_only"), ("SIFT_V2", "predictions_v2", "p_data_only_v2"), ("PLAYER_SIM_V1", "predictions_player", "p_player")):
        rows, inf = pred_source_rows(root, sub, tickers, None, qf)
        cand[name] = rows
        srcinfo[name] = inf
        print(name, len(rows), time.time() - t0, flush=True)
    # OA arms (game-level): map to winner / total contracts
    oa_rows, oa_raw = [], 0
    teams_of_game = {}
    for tk in tickers:
        c = contracts[tk]
        if c["family"] == "game_winner":
            teams_of_game.setdefault(str(c["game_id"]), {})[int(c["team_id"])] = tk
    for f, r in C.read_jsonl_gz(os.path.join(root, "predictions_oa/dt=*/*.jsonl.gz")):
        oa_raw += 1
        g = str(r["game_id"])
        lin_t = C.ts(r["predicted_at_utc"])
        for tid, tk in teams_of_game.get(g, {}).items():
            q = r["p_home_win"] if tid == r["home_team_id"] else 1 - r["p_home_win"]
            oa_rows.append(dict(arm=r["arm"], ticker=tk, game=g, t=lin_t, cutoff=C.ts(r["data_cutoff_utc"]), q=float(q), lineage_ts=None, mins=r["minutes_to_start"], pregame=bool(r["pregame"]),
                                emb_bid=None, emb_ask=None, emb_mid=None, fam="game_winner"))
    srcinfo["OA"] = dict(raw_rows=oa_raw, rows_mapped_to_winner_tickers=len(oa_rows), arms=dict(collections.Counter(r["arm"] for r in oa_rows)))
    oa_arms = sorted({r["arm"] for r in oa_rows})
    for arm in oa_arms:
        cand["OA:" + arm] = [r for r in oa_rows if r["arm"] == arm]

    # --- time validity + selection
    tv = {}
    sel_all = {}
    for name, rows in cand.items():
        keep, cnt = [], collections.Counter()
        for r in rows:
            g = r["game"]
            st = sch.get(g, {}).get("start_final")
            if st is None:
                cnt["no_schedule"] += 1
                continue
            if not r["pregame"]:
                cnt["pregame_flag_false"] += 1
                continue
            if r["t"] >= st:
                cnt["predicted_at_or_after_start"] += 1
                continue
            if r.get("cutoff") is not None and r["cutoff"] > r["t"] + 1:
                cnt["cutoff_after_prediction"] += 1
                continue
            if r.get("lineage_ts") is not None and r["lineage_ts"] > r["t"] + 1:
                cnt["lineage_after_prediction"] += 1
                continue
            sk = start_known(sch, g, r["t"])
            if sk is None or abs(sk - st) > 15 * 60:
                cnt["start_not_known_or_rescheduled"] += 1
                continue
            keep.append(dict(r, start=st, family=r.get("fam") or fam_of[r["ticker"]]))
        tv[name] = dict(rows_in=len(rows), rows_kept=len(keep), dropped=dict(cnt))
        for k, p in C.select_per_horizon(keep, HZ).items():
            sel_all[(name,) + k] = p
    print("selected", len(sel_all), time.time() - t0, flush=True)

    # --- sportsbook challenger: decision times fixed at horizon targets (no model needed); both sides need a board quote
    sb_items = {}
    for tk in tickers:
        c = contracts[tk]
        if c["family"] != "game_winner":
            continue
        g = str(c["game_id"])
        st = sch.get(g, {}).get("start_final")
        res = results.get(g)
        if st is None or res is None or g not in sb:
            continue
        for lab, tgt, lo, hi in HZ:
            t = st - tgt * 3600
            ph, nprov = sportsbook_home_prob(sb, g, t)
            if ph is None:
                continue
            q = ph if int(c["team_id"]) == res["home_team_id"] else 1 - ph
            sb_items[("SPORTSBOOK", tk, lab)] = dict(ticker=tk, game=g, t=t, q=q, start=st, family="game_winner", nprov=nprov)

    starts = {tk: sch[str(contracts[tk]["game_id"])]["start_final"] for tk in contracts if str(contracts[tk]["game_id"]) in sch}
    all_sel = dict(sel_all)
    all_sel.update(sb_items)
    lookups = [(p["ticker"], p["t"], k) for k, p in all_sel.items()]
    resolved, cov, integ = C.board_sweep(root, lookups, starts=starts, want=tickers)
    print("swept", time.time() - t0, integ, flush=True)
    ob, n_ob_delta = C.orderbook_coverage(root, tickers)
    print("orderbooks", len(ob), time.time() - t0, flush=True)

    # --- rows
    rows, drops, emb_cmp = [], collections.Counter(), collections.defaultdict(list)
    for k, p in all_sel.items():
        name, tk, lab = k
        rs = resolved[k]
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
        if not (0 < p["q"] < 1):
            drops["bad_prob"] += 1
            continue
        if p.get("emb_bid") is not None and p.get("emb_ask") is not None:
            emb_cmp[name].append(abs((p["emb_bid"] + p["emb_ask"]) / 200 - q["mid"]))
        rows.append(dict(game=p["game"], t=p["t"], mid=q["mid"], q=float(p["q"]), y=y_of[tk], fam=p["family"], hor=lab, ticker=tk, src=name, spread=q["spread"],
                         bid_size=q["bid_size"], ask_size=q["ask_size"], stale=p["t"] - rs["board_t"], hb=(p["start"] - p["t"]) / 3600))
    print("rows", len(rows), dict(drops), flush=True)

    # --- families ledger
    fam_all = {}
    for fam in sorted({c["family"] for c in contracts.values()}):
        tks = [tk for tk, c in contracts.items() if c["family"] == fam]
        used = [tk for tk in tks if tk in y_of]
        fam_all[fam] = dict(contracts_observed=len(tks), games_observed=len({contracts[tk]["game_id"] for tk in tks}),
                            engine_outcomes=dict(collections.Counter(sett[tk]["outcome"] if tk in sett else "NOT_SETTLED" for tk in tks)),
                            settled_yes_no_rederived_agree=len(used), games_settled=len({contracts[tk]["game_id"] for tk in used}),
                            derivation_vs_engine=dict(cmp.get(fam, {})), support=dict(collections.Counter(contracts[tk]["support"] for tk in tks)))

    # --- cells
    srcs = sorted({r["src"] for r in rows} | set(cand))
    fams = sorted(fam_all)
    cell_rows = {}
    for r in rows:
        cell_rows.setdefault((r["src"], r["fam"], r["hor"]), []).append(r)
    for r in rows:  # pooled game-level exploratory cells per source
        cell_rows.setdefault((r["src"], "ALL_MODELLED(pooled, exploratory)", r["hor"]), []).append(r)
    results_c = {k: C.run_cell(v) for k, v in cell_rows.items()}
    okk = [k for k, r in results_c.items() if r["status"] == "OK"]
    holm_of = dict(zip(okk, I.holm([results_c[k]["gain_vs_calibrated_market_logloss"]["p"] for k in okk]))) if okk else {}

    out_cells = []
    for src in srcs:
        fams_src = sorted({k[1] for k in cell_rows if k[0] == src} | ({f for f in fams if (src in ("SIFT_V1", "SIFT_V2") and f in GAME_FAMS) or (src == "PLAYER_SIM_V1" and f in PLAYER_FAMS) or (src.startswith("OA:") and f == "game_winner") or (src == "SPORTSBOOK" and f == "game_winner")}))
        for fam in fams_src:
            for lab, tgt, lo, hi in HZ:
                k = (src, fam, lab)
                sub = cell_rows.get(k, [])
                cell = dict(sport=SPORT, challenger=src, family=fam, horizon=lab, horizon_window_hours_before_start=[lo, hi])
                fi = fam_all.get(fam)
                if not sub:
                    if fi and fi["settled_yes_no_rederived_agree"] == 0:
                        reason = f"no contract of this family has a settlement verified against independent derivation (engine outcomes {fi['engine_outcomes']}). Repair: prove semantics and settle it, then re-run."
                    else:
                        npr = len([r for r in cand.get(src, []) if (r.get('fam') or fam_of.get(r['ticker'])) == fam])
                        if npr == 0:
                            reason = (f"challenger {src} archives no non-null probability for verified {fam} contracts (gate UNSUPPORTED / not priced). Repair: price this family and archive the probability with its timestamp.")
                        else:
                            reason = (f"challenger {src} has {npr} pregame probability rows for verified {fam} contracts but none gives a usable (two-sided, spread<=10c, mid in [0.03,0.97], board<=30 min old) "
                                      f"Kalshi quote at this horizon. Repair: capture the quote (with depth) at the same instant as the model at this horizon.")
                    cell.update(inputs_available=[], n_games=0, n_contracts=0, price_coverage=None, settlement_source=_ss(fam), market_metrics=None, model_metrics=None, incremental_gain=None,
                                status="MISSING_DATA", reason=reason)
                    out_cells.append(cell)
                    continue
                res = results_c[k]
                tks = {r["ticker"] for r in sub}
                cov_f = [cov[tk] for tk in y_of if fam_of.get(tk) == fam and tk in cov]
                sp = np.array([r["spread"] for r in sub])
                pc = dict(family_settled_contracts=sum(1 for tk in y_of if fam_of[tk] == fam), family_contracts_with_pregame_two_sided_board=sum(1 for c in cov_f if c["n_two_sided"] > 0),
                          cell_contracts_with_quote_at_decision=len(tks), median_spread_at_decision=float(np.median(sp)), median_staleness_s=float(np.median([r["stale"] for r in sub])),
                          median_hours_before_start=float(np.median([r["hb"] for r in sub])),
                          median_bid_size=float(np.nanmedian([r["bid_size"] if r["bid_size"] is not None else np.nan for r in sub])),
                          median_ask_size=float(np.nanmedian([r["ask_size"] if r["ask_size"] is not None else np.nan for r in sub])),
                          contracts_in_orderbook_archive=sum(1 for tk in tks if tk in ob), quote_source="Kalshi board checkpoints+chained deltas; full ladder for <=300 tickers/capture")
                cell.update(inputs_available=_inputs(src), n_games=len({r["game"] for r in sub}), n_contracts=len(tks), n_rows=len(sub), price_coverage=pc, settlement_source=_ss(fam))
                if res["status"] == "OK":
                    g = res["gain_vs_calibrated_market_logloss"]
                    st, why = C.classify(res, holm_of[k], n_tested=len(okk))
                    cell.update(market_metrics=dict(holdout_logloss_raw_market=res["logloss"]["raw_market"], holdout_logloss_calibrated_market=res["logloss"]["calibrated_market"],
                                                    holdout_brier_raw_market=res["brier"]["raw_market"], holdout_brier_calibrated_market=res["brier"]["calibrated_market"],
                                                    calibration_gain_of_market_alone=res["calibration_gain_of_market_alone_logloss"]),
                                model_metrics=dict(holdout_alone=res["q_alone_holdout"], q_vs_mid=res["q_vs_mid"], holdout_logloss_challenger=res["logloss"]["challenger"], holdout_brier_challenger=res["brier"]["challenger"],
                                                   coef_challenger=res["coef_challenger"], train_games=res["train_games"], holdout_games=res["holdout_games"], n_holdout_rows=res["n_holdout"]),
                                incremental_gain=dict(mean=g["mean"], lo=g["lo"], hi=g["hi"], holm_p=holm_of[k], p_uncorrected=g["p"], n_holdout_games=g["n_games"], gain_vs_raw_market=res["gain_vs_raw_market_logloss"],
                                                      negative_control=res["negative_control"], positive_control=res["positive_control"]), status=st, reason=why)
                else:
                    st, why = C.classify(res, None)
                    cell.update(market_metrics=None, model_metrics=dict(train_games=res["train_games"], holdout_games=res["holdout_games"], n_train_rows=res["n_train"], n_holdout_rows=res["n_holdout"]),
                                incremental_gain=None, status=st, reason=why)
                out_cells.append(cell)
    for fam, fi in fam_all.items():
        if fi["settled_yes_no_rederived_agree"] == 0:
            out_cells.append(dict(sport=SPORT, challenger="ANY", family=fam, horizon="ALL", inputs_available=[], n_games=0, n_contracts=0, price_coverage=None, settlement_source=_ss(fam), market_metrics=None,
                                  model_metrics=None, incremental_gain=None, status="MISSING_DATA",
                                  reason=f"no settled YES/NO contract verified by independent derivation (contracts observed {fi['contracts_observed']}, engine outcomes {fi['engine_outcomes']}); "
                                         "semantics not proven in the settlement engine. Repair: prove the rule text against the exchange result, implement settlement, capture the Kalshi result."))
    # pooled cells
    for k, sub in cell_rows.items():
        if k[1].startswith("ALL_MODELLED"):
            res = results_c[k]
            cell = dict(sport=SPORT, challenger=k[0], family=k[1], horizon=k[2], inputs_available=_inputs(k[0]), n_games=len({r["game"] for r in sub}), n_contracts=len({r["ticker"] for r in sub}), n_rows=len(sub),
                        price_coverage=None, settlement_source="see per-family cells")
            if res["status"] == "OK":
                g = res["gain_vs_calibrated_market_logloss"]
                st, why = C.classify(res, holm_of[k], n_tested=len(okk))
                cell.update(market_metrics=dict(holdout_logloss_raw_market=res["logloss"]["raw_market"], holdout_logloss_calibrated_market=res["logloss"]["calibrated_market"]),
                            model_metrics=dict(holdout_alone=res["q_alone_holdout"], q_vs_mid=res["q_vs_mid"], holdout_logloss_challenger=res["logloss"]["challenger"], holdout_games=res["holdout_games"]),
                            incremental_gain=dict(mean=g["mean"], lo=g["lo"], hi=g["hi"], holm_p=holm_of[k], p_uncorrected=g["p"], negative_control=res["negative_control"], positive_control=res["positive_control"]), status=st, reason=why)
            else:
                st, why = C.classify(res, None)
                cell.update(market_metrics=None, model_metrics=None, incremental_gain=None, status=st, reason=why)
            out_cells.append(cell)

    digests, roll = C.file_digests(root, ["manifest.jsonl", "STATUS_*.json", "predictions/*/*.gz", "predictions_v2/*/*.gz", "predictions_player/*/*.gz", "predictions_oa/*/*.gz", "settlements/*/*.gz",
                                          "contracts/*/*.gz", "results/*/*.gz", "player_events/goals/*/*.gz", "player_events/players/*/*.gz", "player_events/goalies/*/*.gz", "context/schedule/*/*.gz",
                                          "context/sportsbook_odds/*/*.gz", "kalshi/markets/*/*.gz", "kalshi/markets_delta/*/*.gz", "kalshi/orderbooks/*/*.gz", "kalshi/orderbooks_delta/*/*.gz"])
    # derived start vs prediction minutes_to_start consistency
    diffs = [abs((p["start"] - p["t"]) / 60 - p["mins"]) for p in all_sel.values() if p.get("mins") is not None]
    report = dict(
        schema="sift-outcome-intel-nhl-audit/1", status="RESEARCH_ONLY", sport=SPORT,
        inputs=dict(repo="chmoses98/NHL-edge-finder", branch="data-archive", commit_sha=a.repo_sha, input_rollup_sha256=roll, n_input_files=len(digests), file_sha256_path="reports/outcome_intel/nhl_input_sha256.json"),
        protocol=dict(question="does a SIFT model (V1/V2/PLAYER_SIM_V1/OA) or the sportsbook consensus add logloss info beyond the calibrated contemporaneous Kalshi mid?",
                      split="earliest 2/3 of games by first decision time = train; latest 1/3 = holdout; ridge=1 fixed; one pass", horizons=[list(h) for h in HZ],
                      row_filters=dict(max_yes_spread=MAX_SPREAD, mid_range=[MID_LO, MID_HI], max_board_staleness_s=MAX_STALE_S, one_row_per_contract_horizon_challenger="closest to horizon target"),
                      multiplicity="Holm over every cell with enough data (challenger x family x horizon + pooled)", n_cells_total=len(out_cells), n_cells_tested=len(okk), status_rule="see nba_nhl_common.classify"),
        independent_events=dict(games_with_final_result=rinfo["games"], games_with_any_contract=len({c["game_id"] for c in contracts.values()}), games_with_verified_settled_contract=len({str(contracts[tk]["game_id"]) for tk in y_of}),
                                games_in_tested_rows=len({r["game"] for r in rows}), note="the game is the independent unit; every interval resamples games"),
        data_quality=dict(contracts=cinfo, settlements=sinfo, results=rinfo, schedule=schinfo, sportsbook=dict(rows=sb_n, games=len(sb)), prediction_sources=srcinfo, time_validity=tv,
                          board_integrity=integ, orderbook_archive=dict(tickers_covered_of_verified=len(ob), verified_tickers=len(tickers), orderbook_delta_files=n_ob_delta), row_drops=dict(drops),
                          embedded_quote_vs_board_mid_abs_diff={k: dict(n=len(v), median=float(np.median(v)), p90=float(np.quantile(v, .9)), share_within_2c=float(np.mean(np.array(v) <= 0.02))) for k, v in emb_cmp.items() if v},
                          start_time_vs_prediction_minutes_to_start=dict(n=len(diffs), median_abs_diff_min=float(np.median(diffs)) if diffs else None, p95=float(np.quantile(diffs, .95)) if diffs else None),
                          goal_events=dict(games_with_goal_rows=len(goals), mismatch_with_final_score=[g for g, r in results.items() if len(goals.get(g, [])) != r["home_final"] + r["away_final"] - (1 if r["last_period_type"] == "SO" else 0)]),
                          engine_vs_independent_derivation=dict(engine_yes_no=sum(1 for s in sett.values() if s["outcome"] in ("YES", "NO")), derivable_and_compared=sum(1 for tk, s in sett.items() if s["outcome"] in ("YES", "NO") and derived.get(tk) in ("YES", "NO")),
                                                                disagreements=len(disagree), disagreement_tickers=disagree[:30], by_family={f: dict(v) for f, v in cmp.items()}),
                          kalshi_official_result=dict(in_archive=False, reason="board `result` empty on every captured market (resolved markets leave the board); no Kalshi settlement values in the archive; settlements are derived by nhl-settle/period-settle/player-settle from the NHL API boxscore/PBP")),
        exchange_crosscheck=exchange_crosscheck(a.accounting, derived),
        families=fam_all, status_counts=dict(collections.Counter(c["status"] for c in out_cells)), cells=out_cells, elapsed_s=time.time() - t0)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(report, open(a.out, "w"), indent=1, sort_keys=True, default=_jd)
    json.dump(digests, open(os.path.join(os.path.dirname(a.out) or ".", "nhl_input_sha256.json"), "w"), indent=0, sort_keys=True)
    print(report["status_counts"])
    for c in out_cells:
        g = c.get("incremental_gain")
        if g:
            print(c["challenger"], c["family"], c["horizon"], c["n_games"], c.get("n_rows"), "gain %.4f [%.4f,%.4f] holm=%.3f" % (g["mean"], g["lo"], g["hi"], g["holm_p"]), c["status"])


def _ss(fam):
    if fam in ("game_winner", "game_spread", "game_total", "team_total"):
        return "engine nhl-settle-1.0 from NHL API boxscore final (incl OT/SO); independently re-derived from results; not Kalshi's result; SO-ambiguous contracts excluded"
    if fam.startswith("period"):
        return "engine nhl-period-settle-1.0 (PBP); independently re-derived from player_events/goals; not Kalshi's result"
    return "engine nhl-player-settle-1.0 (boxscore+pbp, player matched by team+jersey+name); independently re-derived from player_events tables; not Kalshi's result"


def _inputs(src):
    base = [dict(name="Kalshi board quote (bid/ask/size)", availability_time="board captured_at_utc <= decision time", established=True)]
    if src == "SPORTSBOOK":
        return base + [dict(name="sportsbook decimal odds (6 providers, devigged consensus)", availability_time="_observed_at_utc <= decision time, <=3h old", established=True)]
    return base + [dict(name=f"SIFT model {src}", availability_time="predicted_at_utc; data_cutoff_utc <= predicted_at; lineage snapshots <= predicted_at; scheduled start known at that time", established=True)]


if __name__ == "__main__":
    main()
