"""CFB bet-selection study (RESEARCH_ONLY): do PR #96 inputs (cfbx_mar_pre / cfbx_tot_pre / pml_lead_half_pre) improve the cfb-edge-finder incumbent's bet SELECTION?

Protocol (fixed before looking at 2026): blend weights and residual sigmas are fit on 2024-2025 incumbent walk-forward records only; 2026 is unseen.
Bets use the last Kalshi executable ASK captured 15 min - 24 h before kickoff (never a mid, never a close). Fee = 0.07*p*(1-p) per contract.
Rule: bet 1 contract when model_prob - ask - fee >= EDGE; at most one bet per game per market family (largest edge). No market price enters any model.

  python research/cfb_bet_selection/evaluate.py --espn DIR1,DIR2 --cfb /path/to/cfb-edge-finder --out report.json
"""
from __future__ import annotations
import argparse, gzip, json, sys
from pathlib import Path
import numpy as np, pandas as pd
from math import erf
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from alpha_engine.features import cfb_espn_ext as X

EDGE, FEE = 0.05, 0.07
_erf = np.vectorize(erf)
cdf = lambda z: 0.5 * (1 + _erf(np.asarray(z, float) / np.sqrt(2)))
jl = lambda p: [json.loads(l) for l in gzip.open(p, "rt")]


def frame(args):
    cache = Path(args.cache) if args.cache else None
    t = pd.read_pickle(cache) if cache and cache.exists() else X.compute(X.load_raw(args.espn))["team"]
    if cache and not cache.exists(): t.to_pickle(cache)
    h = t[t.is_home == 1][["game_id", "cfbx_mar_pre", "cfbx_tot_pre", "pml_lead_half_pre"]]
    V = Path(args.cfb) / "data/scripting/validation"
    r = pd.DataFrame([x for y in (2024, 2025, 2026) for x in jl(V / f"records_{y}.jsonl.gz")])
    r = r[r.pred_home.notna() & r.actual_home.notna()].copy(); r["game_id"] = r.game_id.astype(int)
    r["inc_mar"] = r.pred_home - r.pred_away; r["inc_tot"] = r.pred_total; r["mar"] = r.actual_home - r.actual_away; r["tot"] = r.actual_total
    r["kick"] = pd.to_datetime(r.kickoff_utc, utc=True); r["pg"] = r.prior_games.map(min)
    return r.merge(h, on="game_id", how="inner").dropna(subset=["cfbx_mar_pre", "cfbx_tot_pre"]), V


def fit(d):
    tr, o = d[d.season < 2026], {}
    for k, y in (("mar", "mar"), ("tot", "tot")):
        A = np.c_[np.ones(len(tr)), tr[f"inc_{k}"], tr[f"cfbx_{k}_pre"]]; b = np.linalg.lstsq(A, tr[y], rcond=None)[0]
        o[k] = {"blend_coef": b.round(4).tolist(), "sig_inc": float((tr[y] - tr[f"inc_{k}"]).std()), "sig_new": float((tr[y] - tr[f"cfbx_{k}_pre"]).std()), "sig_blend": float((tr[y] - A @ b).std())}
        d[f"blend_{k}"] = np.c_[np.ones(len(d)), d[f"inc_{k}"], d[f"cfbx_{k}_pre"]] @ b
    return o


def accuracy(d):
    o = {}
    for s, g in d.groupby("season"):
        o[int(s)] = {"n": len(g), **{f"{m}_{k}_mae": round(float((g[k] - g[c]).abs().mean()), 3) for k in ("mar", "tot") for m, c in (("inc", f"inc_{k}"), ("new", f"cfbx_{k}_pre"), ("blend", f"blend_{k}"))},
                     **{f"{m}_winner_acc": round(float(((g[c] > 0) == (g.mar > 0)).mean()), 4) for m, c in (("inc", "inc_mar"), ("new", "cfbx_mar_pre"), ("blend", "blend_mar"))}}
    return o


def quotes(V, d):
    keys = {x["game_key"]: int(x["game_id"]) for x in jl(V / "signal_discovery_wave2a/replay_rows_2026.jsonl.gz")}
    rows = []
    for q in jl(V / "control_market_2026/quotes_2026.jsonl.gz"):
        rows.append(("WIN", q["event_ticker"].split("-", 1)[1], q["market_ticker"].rsplit("-", 1)[1], -0.5, q["captured_at"], q["yes_ask"], q["no_ask"]))
    for q in jl(V / "signal_discovery_wave2a/spread_captures_2026.jsonl.gz"):
        ms = q.get("spread_markets") or [{"event_ticker": q["kalshi_event_ticker"], "market_ticker": q["kalshi_market_ticker"], "floor_strike": q["threshold"], "yes_ask": q["executable_yes_price"], "no_ask": q["executable_no_price"], "status": q["market_status"]}]
        for m in ms:
            if m.get("status") == "active": rows.append(("SPREAD", m["event_ticker"].split("-", 1)[1], m["market_ticker"].rsplit("-", 1)[1].rstrip("0123456789"), float(m["floor_strike"]), q["captured_at"], m["yes_ask"], m["no_ask"]))
    q = pd.DataFrame(rows, columns=["fam", "key", "abbr", "thr", "cap", "yes_ask", "no_ask"]); q["game_id"] = q.key.map(keys); q = q.dropna(subset=["game_id"])
    q["side_home"] = [k[7:].endswith(a) and not k[7:].startswith(a) if k[7:].endswith(a) != k[7:].startswith(a) else None for k, a in zip(q.key, q.abbr)]
    q = q.dropna(subset=["side_home"]).merge(d[d.season == 2026], on="game_id"); q["cap"] = pd.to_datetime(q.cap, utc=True, format="ISO8601"); lead = (q.kick - q.cap).dt.total_seconds() / 60
    q = q[(lead >= 15) & (lead <= 1440)].sort_values("cap").groupby(["fam", "game_id", "abbr", "thr"]).tail(1)
    q["first_cap"] = q.cap
    return q


def bets(q, col, sig):
    tm = np.where(q.side_home.astype(bool), q[col], -q[col]); am = np.where(q.side_home.astype(bool), q.mar, -q.mar)
    # FIX (audit of PR #97): a WIN contract settles on margin > 0. Using the settlement threshold -0.5 for BOTH teams in a continuous normal gave
    # P(home)+P(away) = 1 + P(|margin| < 0.5) ~ 1.024, inflating every WIN edge by ~1.2 points. Probability now uses 0; settlement is unchanged.
    pt = np.where(q.fam == "WIN", 0.0, q.thr)
    p = 1 - cdf((pt - tm) / sig); won_yes = am > q.thr; out = []
    for side, ask, prob, won in (("YES", q.yes_ask, p, won_yes), ("NO", q.no_ask, 1 - p, ~won_yes)):
        a = ask.to_numpy(float); fee = FEE * a * (1 - a); e = prob - a - fee
        out.append(pd.DataFrame({"fam": q.fam.values, "game_id": q.game_id.values, "week": q.week.values, "pg": q.pg.values, "side": side, "thr": q.thr.values, "ask": a, "fee": fee, "prob": prob, "edge": e, "won": np.asarray(won), "absmar": np.abs(q[col].values)}))
    b = pd.concat(out); b = b[(b.ask > 0.02) & (b.ask < 0.98) & (b.edge >= EDGE)]
    return b.sort_values("edge").groupby(["fam", "game_id"]).tail(1).sort_values(["week", "game_id"])


def summ(b):
    if not len(b): return {"n": 0}
    pnl = np.where(b.won, 1 - b.ask, -b.ask) - b.fee; cum = pnl.cumsum(); cost = (b.ask + b.fee).sum()
    return {"n": int(len(b)), "win_rate": round(float(b.won.mean()), 4), "avg_ask": round(float(b.ask.mean()), 4), "avg_model_prob": round(float(b.prob.mean()), 4), "net_pnl_contracts": round(float(pnl.sum()), 3),
            "net_roi": round(float(pnl.sum() / cost), 4), "max_drawdown": round(float((np.maximum.accumulate(np.r_[0, cum]) - np.r_[0, cum]).max()), 3), "pnl_se": round(float(pnl.std() * np.sqrt(len(b))), 3)}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--espn", required=True); ap.add_argument("--cfb", required=True); ap.add_argument("--out"); ap.add_argument("--cache"); a = ap.parse_args()
    d, V = frame(a); f = fit(d); q = quotes(V, d)
    rep = {"label": "RESEARCH_ONLY", "protocol": {"edge_min": EDGE, "fee": "0.07*p*(1-p)", "fit_seasons": [2024, 2025], "test_season": 2026, "entry": "last executable ask 15min-24h pre-kickoff"}, "fit": f, "outcome_accuracy_by_season": accuracy(d),
           "quote_coverage_2026": {fam: {"games": int(g.game_id.nunique()), "contracts": len(g)} for fam, g in q.groupby("fam")}, "selection_2026": {}}
    for name, col, sk in (("incumbent", "inc_mar", "sig_inc"), ("pr96_only", "cfbx_mar_pre", "sig_new"), ("blend", "blend_mar", "sig_blend")):
        b = bets(q, col, f["mar"][sk]); r = {"ALL": summ(b)}
        for fam, g in b.groupby("fam"): r[fam] = summ(g)
        for lab, m in (("edge_05_10", b.edge < .10), ("edge_10_20", (b.edge >= .10) & (b.edge < .20)), ("edge_20p", b.edge >= .20), ("ask_lt_35", b.ask < .35), ("ask_35_65", (b.ask >= .35) & (b.ask <= .65)), ("ask_gt_65", b.ask > .65),
                       ("prior_games_le2", b.pg <= 2), ("prior_games_ge3", b.pg >= 3), ("model_absmar_lt7", b.absmar < 7), ("model_absmar_ge14", b.absmar >= 14)): r[lab] = summ(b[m])
        rep["selection_2026"][name] = r; b["model"] = name; rep.setdefault("_b", []).append(b)
    B = pd.concat(rep.pop("_b")); k = ["fam", "game_id", "side", "thr"]; inc = B[B.model == "incumbent"]; bl = B[B.model == "blend"]
    m = inc.merge(bl, on=k, how="outer", suffixes=("_i", "_b"), indicator=True)
    pick = lambda mm, s: summ(mm.rename(columns={c + s: c for c in ("ask", "fee", "prob", "won")}))
    rep["incumbent_vs_blend_2026"] = {"both": pick(m[m._merge == "both"], "_i"), "incumbent_only_dropped_by_blend": pick(m[m._merge == "left_only"], "_i"), "blend_only_added": pick(m[m._merge == "right_only"], "_b")}
    s = json.dumps(rep, indent=1); print(s)
    if a.out: Path(a.out).write_text(s + "\n")


if __name__ == "__main__":
    main()
