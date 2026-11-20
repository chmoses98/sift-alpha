"""Independent audit + calibration diagnostics for the PR #97 CFB bet-selection study (RESEARCH_ONLY; nothing activated or deployed).

  python research/cfb_bet_selection/audit_calibration.py --espn DIR1,DIR2 --cfb /path/to/cfb-edge-finder --kalshi RESTORED/kalshi_official_settlements [--cache team.pkl] --out research/cfb_bet_selection/audit_report_2026.json

Sections of the report:
  settlement_audit   every quoted 2026 ticker graded by evaluate.py's rule vs Kalshi's official `result` (needs --kalshi)
  traces             representative contracts, raw quote -> model probability -> official settlement
  bias / residuals   projection error by season, incumbent home-effect size, normality of standardized residuals
  calibration        all quoted contracts (not only selected bets): by probability bucket, family, entry price, model-market disagreement; Brier / log loss vs market mid
  corrections        pre-specified, walk-forward only; no threshold was tuned on 2026 (EDGE stays 0.05 from PR #97)
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import evaluate as E
import contracts as C

BINS = [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1]
SHRINK_K = 20  # pseudo-games for the walk-forward bias estimate; fixed a priori, not tuned
lg = lambda p: np.log(np.clip(p, .01, .99) / (1 - np.clip(p, .01, .99)))


def quote_table(V, d):
    """Same quote selection as evaluate.quotes (last active executable ask 15 min - 24 h before kickoff) but keeps the full market ticker."""
    jl = E.jl; keys = {x["game_key"]: int(x["game_id"]) for x in jl(V / "signal_discovery_wave2a/replay_rows_2026.jsonl.gz")}; rows = []
    for q in jl(V / "control_market_2026/quotes_2026.jsonl.gz"): rows.append((q["market_ticker"], -0.5, q["captured_at"], q["yes_ask"], q["no_ask"]))
    for q in jl(V / "signal_discovery_wave2a/spread_captures_2026.jsonl.gz"):
        ms = q.get("spread_markets") or [{"market_ticker": q["kalshi_market_ticker"], "floor_strike": q["threshold"], "yes_ask": q["executable_yes_price"], "no_ask": q["executable_no_price"], "status": q["market_status"]}]
        rows += [(m["market_ticker"], float(m["floor_strike"]), q["captured_at"], m["yes_ask"], m["no_ask"]) for m in ms if m.get("status") == "active"]
    q = pd.DataFrame(rows, columns=["ticker", "thr", "cap", "yes_ask", "no_ask"]); P = q.ticker.map(C.parse_ticker)
    for k in ("fam", "key", "abbr"): q[k] = P.map(lambda x: x[k])
    q["thr_from_ticker"] = P.map(lambda x: x["thr"]); q["game_id"] = q.key.map(keys); q = q.dropna(subset=["game_id"])
    q["side_home"] = [C.side_is_home(k, a) for k, a in zip(q.key, q.abbr)]
    q = q.dropna(subset=["side_home"]).merge(d[d.season == 2026], on="game_id"); q["side_home"] = q.side_home.astype(bool)
    q["cap"] = pd.to_datetime(q.cap, utc=True, format="ISO8601"); q["lead_min"] = (q.kick - q.cap).dt.total_seconds() / 60
    q = q[(q.lead_min >= 15) & (q.lead_min <= 1440)].sort_values("cap").groupby(["fam", "game_id", "abbr", "thr"]).tail(1).copy()
    q["mid"] = (q.yes_ask + 1 - q.no_ask) / 2; q["y"] = (np.where(q.side_home, q.mar, -q.mar) > q.thr).astype(float)
    return q


def p_yes(q, home_mar, sig): return 1 - E.cdf((np.where(q.fam == "WIN", 0.0, q.thr) - np.where(q.side_home, home_mar, -home_mar)) / sig)  # WIN uses 0, see evaluate.bets


def select(q, p, edge=E.EDGE):
    """PR #97 rule: net edge = prob - ask - fee >= edge, one bet per game per family (largest edge). Returns per-bet rows with P&L decomposition."""
    out = []
    for side, ask, mid, prob, won in (("YES", q.yes_ask, q.mid, p, q.y == 1), ("NO", q.no_ask, 1 - q.mid, 1 - p, q.y == 0)):
        a = ask.to_numpy(float); f = E.FEE * a * (1 - a)
        out.append(pd.DataFrame({"fam": q.fam.values, "game_id": q.game_id.values, "week": q.week.values, "ticker": q.ticker.values, "side": side, "thr": q.thr.values, "side_home": q.side_home.values,
                                 "ask": a, "mid": np.asarray(mid, float), "fee": f, "prob": np.asarray(prob, float), "edge": prob - a - f, "won": np.asarray(won)}))
    b = pd.concat(out); b = b[(b.ask > 0.02) & (b.ask < 0.98) & (b.edge >= edge)]
    return b.sort_values("edge").groupby(["fam", "game_id"]).tail(1).sort_values(["week", "game_id"])


def summ(b):
    if not len(b): return {"n": 0}
    w = b.won.to_numpy(float); gross_mid = w - b.mid; spread_cost = b.ask - b.mid; net = w - b.ask - b.fee
    fee_cent = np.array([C.fee(a, True) for a in b.ask]); g = pd.Series(net).groupby(b.game_id.values).sum()
    return {"n": int(len(b)), "games": int(b.game_id.nunique()), "win_rate": round(float(w.mean()), 4), "avg_ask": round(float(b.ask.mean()), 4), "avg_model_prob": round(float(b.prob.mean()), 4),
            "pnl_at_mid_no_fee": round(float(gross_mid.sum()), 3), "half_spread_cost": round(float(spread_cost.sum()), 3), "fee_cost": round(float(b.fee.sum()), 3), "net_pnl": round(float(net.sum()), 3),
            "net_roi": round(float(net.sum() / (b.ask + b.fee).sum()), 4), "net_pnl_se_game_clustered": round(float(g.std() * np.sqrt(len(g))) if len(g) > 1 else 0.0, 3),
            "net_pnl_fee_rounded_up_to_cent": round(float((w - b.ask - fee_cent).sum()), 3)}


def calib(g, c, by):
    t = g.groupby(by, observed=True).agg(n=("y", "size"), games=("game_id", "nunique"), pred=(c, "mean"), mkt_mid=("mid", "mean"), obs=("y", "mean"))
    return {str(k): {"n": int(r.n), "games": int(r.games), "pred": round(float(r.pred), 3), "mkt_mid": round(float(r.mkt_mid), 3), "obs": round(float(r.obs), 3)} for k, r in t.iterrows()}


def score(p, y):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4); return {"brier": round(float(((p - y) ** 2).mean()), 4), "log_loss": round(float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()), 4)}


def irls(X, y, it=40):
    b = np.zeros(X.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-X @ b)); b = b + np.linalg.solve(X.T @ (X * (p * (1 - p) + 1e-9)[:, None]) + 1e-6 * np.eye(len(b)), X.T @ (y - p))
    return b


def fit_decoupled(d):
    """Correction A (fit on 2024-2025 only): the incumbent adds its in-season home effect h to the home score and subtracts it from the away score (margin +2h).
    Strip it (inc0 = inc_mar - 2h) and let 2024-2025 decide how much home effect to keep: mar ~ 1 + inc0 + h + cfbx."""
    h = d.home_effect_applied.fillna(0).to_numpy(float); A = np.c_[np.ones(len(d)), d.inc_mar - 2 * h, h, d.cfbx_mar_pre]; tr = (d.season < 2026).to_numpy()
    b = np.linalg.lstsq(A[tr], d.mar[tr], rcond=None)[0]; d["decoup_mar"] = A @ b
    return {"coef_[1,inc_minus_2h,h,cfbx]": b.round(4).tolist(), "sigma_train": float((d.mar[tr] - d.decoup_mar[tr]).std())}


def walk_forward_bias(d26, col):
    """Correction B: for week w subtract the shrunk mean residual of 2026 games from weeks < w only: sum(resid) / (n + SHRINK_K)."""
    r = d26.mar - d26[col]; return d26.week.map(lambda w: r[d26.week < w].sum() / ((d26.week < w).sum() + SHRINK_K))


def walk_forward_market_recal(q, pcol):
    """Correction C: p = sigmoid(a + b*logit(model) + c*logit(market mid)), refit each week on contracts of earlier 2026 weeks only. Weeks without >= 2 prior weeks get NaN (no bet)."""
    out = pd.Series(np.nan, index=q.index); coefs = {}
    for w in sorted(q.week.unique()):
        tr = q[q.week < w]
        if tr.week.nunique() < 2: continue
        te = q[q.week == w]; b = irls(np.c_[np.ones(len(tr)), lg(tr[pcol]), lg(tr.mid)], tr.y.to_numpy()); coefs[int(w)] = b.round(3).tolist()
        out[te.index] = 1 / (1 + np.exp(-(np.c_[np.ones(len(te)), lg(te[pcol]), lg(te.mid)] @ b)))
    return out, coefs


def market_margin(q):
    """Market-implied median home margin per game: where the ladder's mid P(home margin > x) crosses 0.5."""
    rows = []
    for gid, g in q[q.fam == "SPREAD"].assign(hthr=lambda x: np.where(x.side_home, x.thr, -x.thr), hp=lambda x: np.where(x.side_home, x.mid, 1 - x.mid)).groupby("game_id"):
        g = g.sort_values("hthr")
        if g.hp.max() >= .5 >= g.hp.min(): rows.append((gid, float(np.interp(.5, g.hp.values[::-1], g.hthr.values[::-1]))))
    return pd.DataFrame(rows, columns=["game_id", "mkt_mar"])


def settlement_audit(q, kdir):
    off = {}
    for p in sorted(Path(kdir).rglob("KXNCAAF*.jsonl")):
        if p.name.split(".")[0] in ("KXNCAAFGAME", "KXNCAAFSPREAD"):
            for l in open(p):
                m = json.loads(l); off[m["ticker"]] = m
    k = q[q.ticker.isin(off)].copy(); o = k.ticker.map(off.get)
    k["off_yes"] = o.map(lambda m: m["result"] == "yes"); k["off_strike"] = o.map(lambda m: m.get("floor_strike")); k["rules"] = o.map(lambda m: m["rules_primary"]); k["close"] = pd.to_datetime(o.map(lambda m: m["close_time"]), utc=True)
    sp = k[k.fam == "SPREAD"]; name_ok = [(h if s else a).split(" ")[0] in r for h, a, s, r in zip(k.home, k.away, k.side_home, k.rules)]
    return {"quoted_tickers": int(len(q)), "with_official_settlement": int(len(k)), "result_agrees_with_evaluate_rule": int(((k.y == 1) == k.off_yes).sum()), "result_disagrees": int(((k.y == 1) != k.off_yes).sum()),
            "spread_strike_equals_official_floor_strike": int((sp.thr == sp.off_strike).sum()), "spread_strike_mismatch": int((sp.thr != sp.off_strike).sum()), "spread_strike_equals_ticker_suffix_minus_half": int((sp.thr == sp.thr_from_ticker).sum()),
            "contract_team_name_found_in_official_rules": int(sum(name_ok)), "quote_after_official_close": int((k.cap >= k.close).sum()), "min_lead_minutes": round(float(q.lead_min.min()), 1), "median_lead_minutes": round(float(q.lead_min.median()), 1),
            "max_overround_yes_ask_plus_no_ask_minus_1": round(float((q.yes_ask + q.no_ask - 1).max()), 3)}, off


def traces(q, off, tickers_like):
    out = []
    for fam, home_side, thr_sign in tickers_like:
        g = q[(q.fam == fam) & (q.side_home == home_side) & (q.ticker.isin(off))]; g = g[g.thr > 10] if thr_sign > 0 else g
        r = g.sort_values("ticker").iloc[len(g) // 2]; m = off[r.ticker]
        out.append({"ticker": r.ticker, "official_rule": m["rules_primary"], "away": r.away, "home": r.home, "final_away": r.actual_away, "final_home": r.actual_home, "contract_team_is_home": bool(r.side_home), "threshold": r.thr,
                    "quote_captured_at": r.cap.isoformat(), "kickoff_utc": r.kick.isoformat(), "yes_ask": r.yes_ask, "no_ask": r.no_ask, "blend_home_margin": round(float(r.blend_mar), 2), "p_yes_blend": round(float(r.p_blend), 4),
                    "edge_yes": round(float(r.p_blend - r.yes_ask - C.fee(r.yes_ask)), 4), "edge_no": round(float(1 - r.p_blend - r.no_ask - C.fee(r.no_ask)), 4), "evaluate_yes_wins": bool(r.y), "official_result": m["result"], "official_expiration_value": m.get("expiration_value")})
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--espn", default=""); ap.add_argument("--cfb", required=True); ap.add_argument("--kalshi"); ap.add_argument("--out"); ap.add_argument("--cache"); a = ap.parse_args()
    d, V = E.frame(a); f = E.fit(d); dec = fit_decoupled(d); q = quote_table(V, d); sb = f["mar"]["sig_blend"]
    assert len(q) == len(E.quotes(V, d)), "quote selection diverged from evaluate.quotes"
    q["p_blend"] = p_yes(q, q.blend_mar, sb); q["p_inc"] = p_yes(q, q.inc_mar, f["mar"]["sig_inc"]); base = select(q, q.p_blend)
    ref = E.summ(E.bets(E.quotes(V, d), "blend_mar", sb)); assert len(base) == ref["n"] and abs(summ(base)["net_pnl"] - ref["net_pnl_contracts"]) < 1e-6, "audit selection diverged from evaluate.bets"
    prev = json.loads((Path(__file__).parent / "report_2026.json").read_text())["selection_2026"]["blend"]
    rep = {"label": "RESEARCH_ONLY", "baseline_reproduces_evaluate_blend": True, "previously_reported_pr97_blend_uncorrected": {k: prev[k] for k in ("ALL", "SPREAD", "WIN", "edge_05_10", "edge_20p")}, "protocol": {"edge_min": E.EDGE, "fit_seasons": [2024, 2025], "test_season": 2026, "weeks_2026": sorted(int(w) for w in d[d.season == 2026].week.unique()), "note": "EDGE unchanged from PR #97; corrections fixed before scoring; one 2026 pass each"}}
    if a.kalshi:
        rep["settlement_audit"], off = settlement_audit(q, a.kalshi); rep["traces"] = traces(q, off, [("WIN", True, 0), ("WIN", False, 0), ("SPREAD", True, 1), ("SPREAD", False, 1), ("SPREAD", False, 0)])
    # --- projection bias and residual shape
    z = (d.mar - d.blend_mar) / sb; mk = market_margin(q).merge(d, on="game_id")
    rep["projection_error_by_season"] = {int(s): {"n": len(g), "actual_home_margin_mean": round(float(g.mar.mean()), 2), "incumbent_home_effect_h_mean": round(float(g.home_effect_applied.mean()), 2), "incumbent_margin_from_home_effect_2h": round(float(2 * g.home_effect_applied.mean()), 2),
                                                 **{f"{n}_bias": round(float((g[c] - g.mar).mean()), 2) for n, c in (("incumbent", "inc_mar"), ("pr96", "cfbx_mar_pre"), ("blend", "blend_mar"), ("decoupled", "decoup_mar"))},
                                                 **{f"{n}_mae": round(float((g[c] - g.mar).abs().mean()), 2) for n, c in (("blend", "blend_mar"), ("decoupled", "decoup_mar"))},
                                                 "blend_resid_sd": round(float((g.mar - g.blend_mar).std()), 2), "z_sd": round(float(z[g.index].std()), 3), "share_abs_z_gt_1.5(normal=.134)": round(float((z[g.index].abs() > 1.5).mean()), 3),
                                                 "share_abs_z_gt_2(normal=.046)": round(float((z[g.index].abs() > 2).mean()), 3), "excess_kurtosis": round(float(z[g.index].kurt()), 2)} for s, g in d.groupby("season")}
    rep["decoupled_fit_2024_2025"] = dec
    rep["vs_market_margin_2026"] = {"games": len(mk), **{n: {"mae": round(float((mk.mar - mk[c]).abs().mean()), 2), "bias": round(float((mk[c] - mk.mar).mean()), 2), "winner_acc": round(float(((mk[c] > 0) == (mk.mar > 0)).mean()), 4)} for n, c in (("market", "mkt_mar"), ("incumbent", "inc_mar"), ("pr96", "cfbx_mar_pre"), ("blend", "blend_mar"), ("decoupled", "decoup_mar"))},
                                    "ols_actual~1+market+blend": np.linalg.lstsq(np.c_[np.ones(len(mk)), mk.mkt_mar, mk.blend_mar], mk.mar, rcond=None)[0].round(3).tolist(), "corr_blend_market": round(float(np.corrcoef(mk.blend_mar, mk.mkt_mar)[0, 1]), 3), "mean_blend_minus_market": round(float((mk.blend_mar - mk.mkt_mar).mean()), 2)}
    # --- calibration over ALL quoted contracts
    q["dis"] = q.p_blend - q.mid; cal = {}
    for fam, g in q.groupby("fam"):
        cal[fam] = {"contracts": len(g), "games": int(g.game_id.nunique()), "scores": {"market_mid": score(g.mid, g.y), "blend": score(g.p_blend, g.y), "incumbent": score(g.p_inc, g.y)},
                    "logit_y~1+model+market": irls(np.c_[np.ones(len(g)), lg(g.p_blend), lg(g.mid)], g.y.to_numpy()).round(3).tolist(), "logit_y~1+model": irls(np.c_[np.ones(len(g)), lg(g.p_blend)], g.y.to_numpy()).round(3).tolist(),
                    "by_model_prob": calib(g, "p_blend", pd.cut(g.p_blend, BINS)), "by_market_mid": calib(g, "p_blend", pd.cut(g.mid, BINS)), "by_model_minus_market": calib(g, "p_blend", pd.cut(g.dis, [-1, -.2, -.1, -.05, .05, .1, .2, 1])),
                    "by_contract_team": calib(g, "p_blend", g.side_home.map({True: "home", False: "away"}))}
    rep["calibration_all_quoted_contracts"] = cal
    b = base.assign(y=base.won.astype(float))
    rep["calibration_selected_bets_blend"] = {"by_edge": calib(b, "prob", pd.cut(b.edge, [.05, .1, .2, .3, 1], right=False)), "by_ask": calib(b, "prob", pd.cut(b.ask, [0, .2, .35, .5, .65, 1])), "by_family": calib(b, "prob", b.fam),
                                              "by_bet_backs": calib(b, "prob", np.where(b.side_home == (b.side == "YES"), "home_team", "away_team")), "scores": {"model": score(b.prob, b.y), "ask_as_prob": score(b.ask, b.y)}}
    # --- corrections (walk-forward)
    d26 = d[d.season == 2026]; q["bias_wf"] = q.game_id.map(dict(zip(d26.game_id, walk_forward_bias(d26, "blend_mar")))); q["bias_wf_dec"] = q.game_id.map(dict(zip(d26.game_id, walk_forward_bias(d26, "decoup_mar"))))
    q["p_dec"] = p_yes(q, q.decoup_mar, dec["sigma_train"]); q["p_wfb"] = p_yes(q, q.blend_mar + q.bias_wf, sb); q["p_dec_wfb"] = p_yes(q, q.decoup_mar + q.bias_wf_dec, dec["sigma_train"])
    q["p_mkt_recal"], coefs = walk_forward_market_recal(q, "p_dec"); main_line = q.assign(_d=(q.mid - .5).abs()).sort_values("_d").groupby(["fam", "game_id"]).head(1).index
    cor = {}
    for name, p, sub in (("0_pr97_blend_win_prob_fixed", q.p_blend, q), ("A_home_effect_decoupled", q.p_dec, q), ("B_blend_plus_walkforward_bias", q.p_wfb, q), ("AB_decoupled_plus_walkforward_bias", q.p_dec_wfb, q),
                         ("A_main_line_only", q.p_dec[main_line], q.loc[main_line]), ("C_walkforward_market_recalibration", q.p_mkt_recal.dropna(), q.loc[q.p_mkt_recal.dropna().index])):
        s = select(sub, p); cor[name] = {"contract_scores": {fam: score(p[g.index], g.y) for fam, g in sub.groupby("fam")}, "ALL": summ(s), **{fam: summ(g) for fam, g in s.groupby("fam")}, "edge_ge_20": summ(s[s.edge >= .2]), "edge_05_10": summ(s[s.edge < .1])}
    cor["C_walkforward_market_recalibration"]["weekly_coef_[1,model,market]"] = coefs; rep["corrections_2026"] = cor
    frozen = {"label": "RESEARCH_ONLY_FROZEN_FORWARD_CANDIDATE", "model": "A_home_effect_decoupled", "coef": dec, "edge_min": E.EDGE, "entry": "last active executable ask 15min-24h pre-kickoff", "fee": "0.07*p*(1-p), report cent-rounded too",
              "trained_through_season": 2025, "scored_2026_weeks_already_seen": rep["protocol"]["weeks_2026"], "forward_rule": "score only games in 2026 weeks after the last seen week; do not refit, do not change edge_min"}
    frozen["sha256"] = hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest(); rep["frozen_forward_candidate"] = frozen
    s = json.dumps(rep, indent=1, default=float); print(s)
    if a.out: Path(a.out).write_text(s + "\n")


if __name__ == "__main__":
    main()
