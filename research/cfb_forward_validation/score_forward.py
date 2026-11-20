"""Score the FROZEN CFB candidates on 2026 games after week 5 (RESEARCH_ONLY). No refitting: every number comes from frozen_specs.json.

  python research/cfb_forward_validation/score_forward.py --he-records ... --team-cache team.pkl --espn-log <cfb>/data/football/2026/team_games.jsonl \
      --kalshi RAW/kalshi --out research/cfb_forward_validation/forward_report.json

Outcomes: ESPN final and period scores (cfb-edge-finder 2026 game log); every contract that also appears in the Kalshi
official-settlement archive is checked against Kalshi's `result` and the official result is used where they differ.
"""
from __future__ import annotations

import argparse
import difflib
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contracts_multi as CM  # noqa: E402
import freeze as FZ  # noqa: E402

FIRST_UNSEEN_KICKOFF = "2026-10-05T00:00:00Z"  # PR #97/#98 records end 2026-10-04 (week 5)
SCORED_FAMILIES = ("FG_winner", "FG_spread", "FG_total", "FG_team_total", "1H_winner", "1H_spread", "1H_total", "1H_team_total", "2H_winner", "2H_spread", "2H_total", "1Q_winner", "1Q_spread", "1Q_total")
PRIORITY = ("FG_total", "FG_team_total", "1H_total", "1H_spread", "1H_team_total", "1Q_total", "1Q_spread")
EDGE = 0.05
BINS = [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1]
lg = lambda p: np.log(np.clip(p, .01, .99) / (1 - np.clip(p, .01, .99)))


def load_specs() -> dict:
    s = json.loads((HERE / "frozen_specs.json").read_text()); h = s.pop("sha256")
    if hashlib.sha256(json.dumps(s, sort_keys=True).encode()).hexdigest() != h:
        raise SystemExit("frozen_specs.json was modified after freezing")
    s["sha256"] = h
    return s


# ------------------------------------------------------------------ games and outcomes
ALIASES = {"app state": "appalachian state", "ul monroe": "louisiana monroe", "miami fl": "miami", "umass": "massachusetts", "ul lafayette": "louisiana",
           "southern miss": "southern mississippi", "uconn": "connecticut", "utsa": "ut san antonio", "fiu": "florida international", "hawaii": "hawai i"}
MATCH_MIN = 0.9  # both team names; the 0.6 threshold first tried paired FCS games with unrelated FBS games (caught by the official-settlement check)


def norm(name: str) -> str:
    import unicodedata
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().replace("&", "and").replace("st.", "state").replace("'", "")
    n = re.sub(r"\(([^)]*)\)", r" \1", n)
    n = re.sub(r"[^a-z0-9]+", " ", n).strip()
    return ALIASES.get(n, n)


def espn_games(log: Path) -> pd.DataFrame:
    """Completed 2026 games oriented by the ESPN schedule's home/away (the same orientation the projections use)."""
    sched = json.loads((log.parent / "schedule.json").read_text())["events"]
    orient = {}
    for e in sched:
        sides = {c["home_away"]: str(c["team_id"]) for c in e.get("competitors") or []}
        if set(sides) == {"home", "away"}:
            orient[str(e["id"])] = sides
    rows = [json.loads(x) for x in open(log)]
    by: dict[str, dict] = {}
    for r in rows:
        by.setdefault(str(r["game_id"]), {})[str(r["team_id"])] = r
    out = []
    for gid, teams in by.items():
        o = orient.get(gid)
        if o is None or o["home"] not in teams or o["away"] not in teams:
            continue
        h, a = teams[o["home"]], teams[o["away"]]
        if h.get("points_for") is None or a.get("points_for") is None:
            continue
        hp, ap = h.get("period_points"), a.get("period_points")
        rec = {"game_id": gid, "kick": pd.Timestamp(h["kickoff_utc"]), "week": h["week"], "home": h["team"], "away": a["team"], "neutral": h["site"] == "neutral",
               "hfg": h["points_for"], "afg": a["points_for"]}
        if hp and ap and len(hp) >= 4 and len(ap) >= 4 and abs(sum(hp) - h["points_for"]) < 1e-9 and abs(sum(ap) - a["points_for"]) < 1e-9:
            rec.update(h1q=hp[0], a1q=ap[0], h1h=hp[0] + hp[1], a1h=ap[0] + ap[1], h2h=sum(hp[2:]), a2h=sum(ap[2:]))
        out.append(rec)
    return pd.DataFrame(out)


def match_games(q: pd.DataFrame, g: pd.DataFrame) -> tuple[dict[str, str], int]:
    """Kalshi game key -> ESPN game id: kickoff within 6 h and both names similar in the SAME orientation (Kalshi AWAY at HOME).
    A game whose best match is the swapped orientation is dropped and counted, never re-oriented by guess."""
    out, swapped = {}, 0
    for key, t in q.groupby("game_key")[["title", "kickoff"]].first().iterrows():
        parts = re.split(r" at | vs ", t.title)
        if len(parts) != 2:
            continue
        ka, kh = norm(parts[0]), norm(parts[1]); kick = pd.Timestamp(t.kickoff)
        cand = g[(g.kick - kick).abs() <= pd.Timedelta(hours=6)]
        best, score, flip = None, 0.0, False
        for _, r in cand.iterrows():
            for ea, eh, f in ((norm(r.away), norm(r.home), False), (norm(r.home), norm(r.away), True)):
                s_ = min(difflib.SequenceMatcher(None, ka, ea).ratio(), difflib.SequenceMatcher(None, kh, eh).ratio())
                if s_ > score:
                    best, score, flip = r.game_id, s_, f
        if best is not None and score >= MATCH_MIN:
            if flip:
                swapped += 1
            else:
                out[key] = best
    return out, swapped


def official_results(kdir: Path) -> dict[str, str]:
    res = {}
    for f in (kdir / "CFB").glob("KXNCAAF*.jsonl"):
        for line in open(f):
            x = json.loads(line)
            if x.get("result") in ("yes", "no"):
                res[x["ticker"]] = x["result"]
    return res


# ------------------------------------------------------------------ probabilities
def mean_for(spec: dict, proj: dict, src: str, period: str, qty: str) -> tuple[float, float, list | None]:
    d = spec["distributions"][f"{src}|{period}|{qty}"]
    m, t = proj[f"{src}_margin"], proj[f"{src}_total"]
    x = {"margin": m, "total": t, "home_pts": (t + m) / 2, "away_pts": (t - m) / 2}[qty]
    return d["alpha"] + d["beta"] * x, d["sigma"], d.get("resid_q")


def candidate_probs(q: pd.DataFrame, P: pd.DataFrame, spec: dict) -> dict[str, np.ndarray]:
    proj = P.set_index("game_id").to_dict("index"); out = {}
    variants = [(s, False) for s in FZ.SOURCES] + [(s, True) for s in FZ.EMPIRICAL_SOURCES]
    for src, emp in variants:
        name = f"{src}_{'emp' if emp else 'normal'}"; ps = []
        for c, gid in zip(q.contract, q.game_id):
            pr = proj.get(gid)
            if pr is None or pd.isna(pr.get(f"{src}_margin")) or pd.isna(pr.get(f"{src}_total")):
                ps.append(np.nan); continue
            mu, sig, rq = mean_for(spec, pr, src, c.period, CM.quantity(c))
            ps.append(CM.yes_prob(c, mu, sig, rq if emp else None))
        out[name] = np.array(ps, float)
    a, b, cc = spec["market_recalibration_C"]["coef_[1,logit_model,logit_mid]"]
    out["C_market_recal"] = 1 / (1 + np.exp(-(a + b * lg(out["frozenA98_normal"]) + cc * lg(q.mid.to_numpy()))))
    return out


# ------------------------------------------------------------------ selection and P&L
def select(q: pd.DataFrame, p: np.ndarray) -> pd.DataFrame:
    rows = []
    for side, ask, size, prob, won in (("YES", q.yes_ask, q.yes_ask_size, p, q.y == 1), ("NO", q.no_ask, q.yes_bid_size, 1 - p, q.y == 0)):
        a = ask.to_numpy(float); f = CM.FEE_RATE * a * (1 - a)
        rows.append(pd.DataFrame({"family": q.family.values, "game_id": q.game_id.values, "week": q.week.values, "ticker": q.market_ticker.values, "side": side, "ask": a, "size": size.to_numpy(float),
                                  "mid": np.where(side == "YES", q.mid, 1 - q.mid), "fee": f, "prob": prob, "edge": prob - a - f, "won": np.asarray(won), "lead_min": q.lead_min.values,
                                  "fbs": q.fbs.values, "contract_side": [c.side for c in q.contract]}))
    b = pd.concat(rows); b = b[np.isfinite(b.prob) & (b.ask > .02) & (b.ask < .98) & (b.edge >= EDGE)]
    return b.sort_values("edge").groupby(["family", "game_id"]).tail(1).sort_values(["week", "game_id"])


def summ(b: pd.DataFrame, boot: int = 0, seed: int = 0) -> dict:
    if not len(b):
        return {"n": 0}
    w = b.won.to_numpy(float); a = b.ask.to_numpy(float)
    net = w - a - b.fee.to_numpy(float)
    fee1 = np.array([CM.fee_per_order(x, 1) for x in a]); fee10 = np.array([CM.fee_per_order(x, 10) for x in a]) / 10
    qty = np.minimum(10, np.floor(np.nan_to_num(b["size"].to_numpy(float), nan=0.0))); okq = qty >= 1
    fee_q = np.array([CM.fee_per_order(x, int(k)) / k if k >= 1 else 0.0 for x, k in zip(a, qty)])
    g = pd.Series(net).groupby(b.game_id.values).sum()
    cum = np.cumsum(net)
    out = {"n": int(len(b)), "games": int(b.game_id.nunique()), "win_rate": round(float(w.mean()), 4), "avg_ask": round(float(a.mean()), 4), "avg_model_prob": round(float(b.prob.mean()), 4),
           "net_pnl_per_contract_unrounded_fee": round(float(net.sum()), 3), "net_roi": round(float(net.sum() / (a + b.fee).sum()), 4),
           "net_pnl_fee_rounded_1_contract_orders": round(float((w - a - fee1).sum()), 3), "net_pnl_fee_rounded_10_contract_orders_per_contract": round(float((w - a - fee10).sum()), 3),
           "size_capped_10": {"bets_with_displayed_size": int(okq.sum()), "contracts": int(qty[okq].sum()), "net_pnl": round(float(((w - a - fee_q) * qty)[okq].sum()), 3),
                              "roi": round(float(((w - a - fee_q) * qty)[okq].sum() / max(((a + fee_q) * qty)[okq].sum(), 1e-9)), 4)},
           "pnl_at_mid_no_fee": round(float((w - b.mid).sum()), 3), "max_drawdown": round(float((np.maximum.accumulate(np.r_[0, cum]) - np.r_[0, cum]).max()), 3),
           "net_pnl_se_game_clustered": round(float(g.std() * np.sqrt(len(g))) if len(g) > 1 else 0.0, 3)}
    if boot and len(g) > 5:
        rng = np.random.default_rng(seed); gv = g.to_numpy(); cost = (a + b.fee).sum()
        bs = np.array([rng.choice(gv, len(gv)).sum() for _ in range(boot)])
        out["net_roi_95ci_game_bootstrap"] = [round(float(np.quantile(bs, .025) / cost), 4), round(float(np.quantile(bs, .975) / cost), 4)]
    return out


def score(p, y) -> dict:
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4); y = np.asarray(y, float)
    return {"brier": round(float(((p - y) ** 2).mean()), 4), "log_loss": round(float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()), 4)}


def irls(X, y, it=40):
    b = np.zeros(X.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-X @ b)); b = b + np.linalg.solve(X.T @ (X * (p * (1 - p) + 1e-9)[:, None]) + 1e-6 * np.eye(len(b)), X.T @ (y - p))
    return b


def reliability(p, y, mid) -> dict:
    d = pd.DataFrame({"p": p, "y": y, "mid": mid}); d["bin"] = pd.cut(d.p, BINS)
    t = d.groupby("bin", observed=True).agg(n=("y", "size"), pred=("p", "mean"), mkt=("mid", "mean"), obs=("y", "mean"))
    return {str(k): {"n": int(r.n), "pred": round(float(r.pred), 3), "mkt_mid": round(float(r.mkt), 3), "obs": round(float(r.obs), 3)} for k, r in t.iterrows()}


# ------------------------------------------------------------------ main
def build_quotes(args, games: pd.DataFrame, official: dict) -> tuple[pd.DataFrame, dict]:
    q = pd.DataFrame(FZ.jl(HERE / "quotes_2026_wk6plus.jsonl.gz"))
    q = q[pd.to_datetime(q.kickoff, utc=True) >= pd.Timestamp(FIRST_UNSEEN_KICKOFF)]
    q["contract"] = [CM.parse(t, fs) for t, fs in zip(q.market_ticker, q.floor_strike)]
    audit = {"quotes_after_week5": int(len(q)), "unparsed_or_unscored_series": int(q.contract.isna().sum())}
    q = q[q.contract.notna()].copy(); q["family"] = q.contract.map(lambda c: c.family); q = q[q.family.isin(SCORED_FAMILIES)]
    m, swapped = match_games(q, games); q["game_id"] = q.game_key.map(m)
    audit.update(games_dropped_orientation_mismatch=swapped, games_quoted=int(q.game_key.nunique()), games_matched_to_espn=int(len({k for k in q.game_key.unique() if k in m})))
    q = q.dropna(subset=["game_id"]).merge(games, on="game_id")
    need = q.contract.map(lambda c: c.period != "FG"); has = q.h1q.notna() if "h1q" in q else False
    audit["period_contracts_without_period_scores"] = int((need & ~has).sum()); q = q[~need | has].copy()
    col = {"FG": ("hfg", "afg"), "1H": ("h1h", "a1h"), "2H": ("h2h", "a2h"), "1Q": ("h1q", "a1q")}
    q["y_espn"] = [CM.settle(c, r[col[c.period][0]], r[col[c.period][1]]) for c, (_, r) in zip(q.contract, q.iterrows())]
    q["official"] = q.market_ticker.map(official)
    chk = q[q.official.notna()]; agree = (chk.y_espn == (chk.official == "yes"))
    audit.update(contracts_with_official_result=int(len(chk)), official_agree=int(agree.sum()), official_disagree=int((~agree).sum()),
                 disagree_examples=chk.loc[~agree, ["market_ticker", "official"]].head(10).to_dict("records"))
    q["y"] = np.where(q.official.notna(), q.official == "yes", q.y_espn).astype(float)
    q["mid"] = (q.yes_ask + 1 - q.no_ask) / 2; q["fbs"] = q.division == "FBS"
    audit["scored_contracts"] = int(len(q)); audit["scored_games"] = int(q.game_id.nunique())
    audit["scored_contracts_by_family"] = q.family.value_counts().to_dict()
    audit["quote_lead_minutes"] = {"min": float(q.lead_min.min()), "median": float(q.lead_min.median()), "max": float(q.lead_min.max())}
    return q, audit


def main() -> None:
    ap = argparse.ArgumentParser()
    for k in ("--he-records", "--team-cache", "--espn-log", "--kalshi", "--out"):
        ap.add_argument(k, required=True)
    a = ap.parse_args()
    spec = load_specs()
    games = espn_games(Path(a.espn_log)); official = official_results(Path(a.kalshi))
    q, audit = build_quotes(a, games, official)
    P = FZ.add_he_blend(FZ.projections(Path(a.he_records), Path(a.team_cache)), spec["he_blend_coef_[1,he,cfbx]"])
    P = P[P.season == 2026]
    probs = candidate_probs(q, P, spec)
    for k, v in probs.items():
        q[f"p_{k}"] = v
    rep = {"label": "RESEARCH_ONLY", "frozen_specs_sha256": spec["sha256"], "rule": spec["selection_rule"], "data_audit": audit, "calibration": {}, "selection": {}}
    # probability integrity on the real ladder
    integ = {}
    for name in probs:
        pv = q[f"p_{name}"]; ok = pv.notna()
        fg = q[ok & (q.family == "FG_winner")].groupby("game_id")[f"p_{name}"].agg(["sum", "size"])
        integ[name] = {"fg_winner_pairs": int((fg["size"] == 2).sum()), "fg_winner_max_abs_sum_minus_1": round(float((fg[fg["size"] == 2]["sum"] - 1).abs().max()), 6) if (fg["size"] == 2).any() else None}
    rep["probability_integrity"] = integ
    for fam, g in q.groupby("family"):
        c = {"contracts": int(len(g)), "games": int(g.game_id.nunique()), "market_mid": score(g.mid, g.y), "obs_rate": round(float(g.y.mean()), 4)}
        for name in probs:
            ok = g[f"p_{name}"].notna()
            if ok.sum() < 50:
                continue
            gg = g[ok]; c[name] = {**score(gg[f"p_{name}"], gg.y), "n": int(ok.sum()), "market_mid_same_rows": score(gg.mid, gg.y),
                                   "logit_y~1+model": irls(np.c_[np.ones(len(gg)), lg(gg[f"p_{name}"])], gg.y.to_numpy()).round(3).tolist(),
                                   "logit_y~1+model+market": irls(np.c_[np.ones(len(gg)), lg(gg[f"p_{name}"]), lg(gg.mid)], gg.y.to_numpy()).round(3).tolist()}
            if name in ("blend97_normal", "he_normal", "he_emp"):
                c[name]["reliability"] = reliability(gg[f"p_{name}"], gg.y, gg.mid)
        rep["calibration"][fam] = c
    base = None
    for name in probs:
        b = select(q, q[f"p_{name}"].to_numpy(float))
        r = {"ALL": summ(b, boot=2000), "PRIORITY_FAMILIES": summ(b[b.family.isin(PRIORITY)], boot=2000)}
        for fam, g in b.groupby("family"):
            r[fam] = summ(g)
        for lab, msk in (("edge_05_10", b.edge < .10), ("edge_10_20", (b.edge >= .10) & (b.edge < .20)), ("edge_20p", b.edge >= .20), ("ask_lt_35", b.ask < .35), ("ask_35_65", (b.ask >= .35) & (b.ask <= .65)),
                         ("ask_gt_65", b.ask > .65), ("fbs_only", b.fbs), ("lead_le_120min", b.lead_min <= 120), ("lead_gt_120min", b.lead_min > 120), ("backs_home", b.contract_side.eq("home") == b.side.eq("YES"))):
            r[lab] = summ(b[msk])
        r["by_week"] = {int(w): summ(g) for w, g in b.groupby("week")}
        rep["selection"][name] = r
        if name == "blend97_normal":
            base = b
    # existing recommendation process (#97 blend, WIN fix) restricted to its original families
    rep["existing_process_blend97_FG_winner_spread"] = summ(base[base.family.isin(["FG_winner", "FG_spread"])], boot=2000)
    # why large claimed edges lose: model - market disagreement vs outcome (blend97 and he_emp)
    dis = {}
    for name in ("blend97_normal", "he_emp", "he_normal"):
        g = q[q[f"p_{name}"].notna()].copy(); g["d"] = g[f"p_{name}"] - g.mid
        t = g.groupby(pd.cut(g.d.abs(), [0, .05, .1, .2, .3, 1]), observed=True).apply(lambda x: pd.Series({"n": len(x), "model_on_model_side": float(np.where(x.d > 0, x[f"p_{name}"], 1 - x[f"p_{name}"]).mean()),
                                                                                                         "market_on_model_side": float(np.where(x.d > 0, x.mid, 1 - x.mid).mean()), "obs_on_model_side": float(np.where(x.d > 0, x.y, 1 - x.y).mean())}))
        dis[name] = {str(k): {kk: round(float(vv), 3) for kk, vv in v.items()} for k, v in t.iterrows()}
    rep["model_vs_market_disagreement"] = dis
    Path(a.out).write_text(json.dumps(rep, indent=1, default=float) + "\n")
    print(json.dumps({"data_audit": audit, "existing": rep["existing_process_blend97_FG_winner_spread"],
                      "all": {k: {kk: v[kk] for kk in ("ALL", "PRIORITY_FAMILIES")} for k, v in rep["selection"].items()}}, indent=1, default=float))


if __name__ == "__main__":
    main()
