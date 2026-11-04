#!/usr/bin/env python3
"""Workstream A, NFL 2025: inventory, point-in-time prices, market-only mispricing, walk-forward matchup model, chronological rule selection.

RESEARCH_ONLY. Aggregates -> reports/outcome_exec/nfl_outcome.json ; per-contract rows -> $SIFT_WORK/nfl_model_probs.jsonl (gitignored, local).
Leakage rules: market features use trades/candles strictly at or before the horizon; model features use games completed in earlier WEEKS only
(2023-24 seasons as prior); outcomes are never features; nflverse spread/total/moneyline are CLOSING lines used as a benchmark only.
"""
from __future__ import annotations
import collections, glob, json, math, os, sys
from datetime import datetime, timedelta, timezone
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from sift_research import nfl25 as N
from sift_research import fees, stats

HORIZONS = {"7d": 168 * 60, "72h": 72 * 60, "48h": 48 * 60, "24h": 24 * 60, "6h": 6 * 60, "90m": 90}
STALE_CAP_MIN = {"7d": 720, "72h": 720, "48h": 720, "24h": 360, "6h": 120, "90m": 45}   # max tape age to call a last price "current"
LOTS = 100          # fee computed as if buying 100 contracts (per-contract fee; 1-lot ceil-to-cent overstates the fee)
BUCKETS = [0.0, 0.15, 0.35, 0.5, 0.65, 0.85, 1.0001]
KEYS = (3, 6, 7, 10, 14)
EXT = os.environ.get("SIFT_EXT", "/home/user/ext")
WORK = os.environ.get("SIFT_WORK", "/home/user/work")
OUT = os.path.join(os.path.dirname(__file__), "..", "..", "reports", "outcome_exec", "nfl_outcome.json")


def period(week, game_type="REG"):
    """chronological split. discovery wk1-6, validation wk7-12, holdout wk13-18 + playoffs."""
    if game_type != "REG":
        return "holdout"
    return "discovery" if week <= 6 else ("validation" if week <= 12 else "holdout")


# ---------------------------------------------------------------- point-in-time prices
def tape_last(trades, t, cap_min):
    """last trade at or before t (never after). Returns (yes_price, age_min) or None if none within cap."""
    best = None
    for tr in trades:
        if tr["ts"] <= t:
            best = tr
        else:
            break
    if best is None:
        return None
    age = (t - best["ts"]).total_seconds() / 60
    return dict(price=best["yes"], age_min=age, stale=age > cap_min)


def candle_quote(candles, t):
    """latest hourly candle whose period END is at or before t (fully observed). bid/ask close; None if one-sided/empty."""
    if not candles:
        return None
    ts = t.timestamp()
    best = None
    for c in candles.get("h60", []):
        if c["end_period_ts"] <= ts:
            best = c
        else:
            break
    if best is None:
        return None
    try:
        b, a = float(best["yes_bid"]["close"]), float(best["yes_ask"]["close"])
    except (TypeError, ValueError):
        return None
    if not (0 < b <= a < 1):
        return dict(bid=None, ask=None, age_min=(ts - best["end_period_ts"]) / 60)
    return dict(bid=b, ask=a, age_min=(ts - best["end_period_ts"]) / 60)


# ---------------------------------------------------------------- model
def ridge_team_fit(rows, t_now, y, lam, half_life=30.0):
    """rows: list of dict(team,opp,home,t,<y>). y_ij = mu + hfa*home + O_i - D_j ; weights decay with age; O,D ridge-penalised.
    Uses ONLY rows passed in (caller filters t < t_now)."""
    teams = sorted({r["team"] for r in rows} | {r["opp"] for r in rows})
    ix = {tm: i for i, tm in enumerate(teams)}
    n, k = len(rows), len(teams)
    X = np.zeros((n, 2 + 2 * k))
    X[:, 0] = 1
    yv = np.zeros(n)
    w = np.zeros(n)
    for i, r in enumerate(rows):
        X[i, 1] = r["home"]
        X[i, 2 + ix[r["team"]]] = 1
        X[i, 2 + k + ix[r["opp"]]] = -1
        yv[i] = r[y]
        w[i] = 0.5 ** ((t_now - r["t"]) / half_life)
    P = np.eye(2 + 2 * k) * lam
    P[0, 0] = P[1, 1] = 1e-6
    A = X.T @ (X * w[:, None]) + P
    beta = np.linalg.solve(A, X.T @ (w * yv))
    return dict(mu=beta[0], hfa=beta[1], O={tm: beta[2 + i] for tm, i in ix.items()}, D={tm: beta[2 + k + i] for tm, i in ix.items()})


def predict_matchup(fit, home, away):
    """expected (home value, away value) for a stat: mu + hfa*home + O_team - D_opp."""
    oh, da = fit["O"].get(home, 0.0), fit["D"].get(away, 0.0)
    oa, dh = fit["O"].get(away, 0.0), fit["D"].get(home, 0.0)
    return fit["mu"] + fit["hfa"] + oh - da, fit["mu"] + oa - dh


def pmf_from_residuals(pred, resid, lo=-70, hi=70):
    """integer pmf of (pred + empirical residual) rounded. returns array over lo..hi."""
    m = np.clip(np.round(pred + np.asarray(resid)).astype(int), lo, hi) - lo
    pm = np.bincount(m, minlength=hi - lo + 1).astype(float)
    return pm / pm.sum()


def key_ratios(preds, actuals, resid, lo=-70, hi=70, shrink=0.5, lo_r=0.7, hi_r=1.6):
    """empirical observed/modelled frequency of |margin| in KEYS from prior walk-forward rows; shrunk toward 1 and clipped."""
    if len(preds) < 60:
        return {k: 1.0 for k in KEYS}
    obs = collections.Counter(abs(int(a)) for a in actuals)
    mod = collections.Counter()
    for p in preds:
        pm = pmf_from_residuals(p, resid, lo, hi)
        for k in KEYS:
            mod[k] += pm[k - lo] + pm[-k - lo]
    out = {}
    for k in KEYS:
        o = obs[k] / len(actuals)
        m = mod[k] / len(preds)
        r = o / m if m > 0 else 1.0
        out[k] = float(np.clip(1 + shrink * (r - 1), lo_r, hi_r))
    return out


def apply_keys(pm, ratios, lo=-70):
    pm = pm.copy()
    for k, r in ratios.items():
        for s in (k, -k):
            pm[s - lo] *= r
    return pm / pm.sum()


def p_margin_gt(pm, thr, lo=-70):
    """P(home margin > thr). thr is x.5 for spreads; thr=0 for ML with ties split 50/50."""
    vals = np.arange(lo, lo + len(pm))
    if abs(thr - round(thr)) < 1e-9:
        return float(pm[vals > thr].sum() + 0.5 * pm[vals == thr].sum()) if thr == 0 else float(pm[vals > thr].sum())
    return float(pm[vals > thr].sum())


def p_total_gt(pm_tot, thr, lo=0):
    vals = np.arange(lo, lo + len(pm_tot))
    return float(pm_tot[vals > thr].sum())


def build_model(games_df, pbp_team):
    """walk-forward over 2024 wk1 .. 2025 end. returns dict game_id -> dict(pred_margin, pred_total, pmf_margin(list), pmf_total, features)."""
    import pandas as pd
    g = games_df.sort_values(["season", "week", "gameday"]).reset_index(drop=True)
    g["t"] = (g["season"] - 2023) * 22 + g["week"]
    # team-game rows (both perspectives)
    rows = []
    for r in g.itertuples():
        for team, opp, home, pf, pa in ((r.home_team, r.away_team, 1, r.home_score, r.away_score), (r.away_team, r.home_team, 0, r.away_score, r.home_score)):
            e = pbp_team.get((r.game_id, team))
            if e is None or pd.isna(pf):
                continue
            rows.append(dict(game_id=r.game_id, team=team, opp=opp, home=home, t=r.t, pts=float(pf), epa=e[0], plays=float(e[1])))
    by_t = collections.defaultdict(list)
    for x in rows:
        by_t[x["t"]].append(x)
    # starter-change flags (point in time: compare with this team's previous game's QB)
    last_qb, qbchg = {}, {}
    for r in g.itertuples():
        for team, qb in ((r.home_team, r.home_qb_id), (r.away_team, r.away_qb_id)):
            prev = last_qb.get(team)
            qbchg[(r.game_id, team)] = 1.0 if (prev is not None and isinstance(qb, str) and qb != prev) else 0.0
            if isinstance(qb, str):
                last_qb[team] = qb
    oos = []         # walk-forward rows used for the second stage and residual pools
    out = {}
    for t in sorted(g["t"].unique()):
        if t < 22 + 1:  # 2023 is prior only (t 1..22)
            continue
        cur = g[g["t"] == t]
        train = [x for tt, v in by_t.items() if tt < t for x in v]
        if len(train) < 300:
            continue
        fits = {y: ridge_team_fit(train, t, y, lam) for y, lam in (("pts", 15.0), ("epa", 15.0), ("plays", 15.0))}
        prior = [o for o in oos if o["t"] < t]
        coef_m = coef_t = None
        if len(prior) >= 100:
            Xm = np.array([[1, o["m_pts"], o["m_epa"], o["rest"], o["qb"]] for o in prior])
            coef_m = np.linalg.lstsq(Xm.T @ Xm + np.eye(5) * 1e-3 * len(prior), Xm.T @ np.array([o["margin"] for o in prior]), rcond=None)[0]
            Xt = np.array([[1, o["t_pts"], o["pace"], o["wind"], o["cold"]] for o in prior])
            coef_t = np.linalg.lstsq(Xt.T @ Xt + np.eye(5) * 1e-3 * len(prior), Xt.T @ np.array([o["total"] for o in prior]), rcond=None)[0]
        res_m = np.array([o["margin"] - o["pred_m"] for o in prior][-700:]) if len(prior) >= 100 else None
        res_t = np.array([o["total"] - o["pred_t"] for o in prior][-700:]) if len(prior) >= 100 else None
        kr = None
        if res_m is not None:
            pp = prior[-400:]
            kr = key_ratios([o["pred_m"] for o in pp], [o["margin"] for o in pp], res_m[-300:])
        for r in cur.itertuples():
            ph, pa = predict_matchup(fits["pts"], r.home_team, r.away_team)
            eh, ea = predict_matchup(fits["epa"], r.home_team, r.away_team)
            lh, la = predict_matchup(fits["plays"], r.home_team, r.away_team)
            rest = (0.0 if pd.isna(r.home_rest) or pd.isna(r.away_rest) else float(r.home_rest - r.away_rest))
            rest = float(np.clip(rest, -4, 4))
            qb = qbchg[(r.game_id, r.away_team)] - qbchg[(r.game_id, r.home_team)]
            roof = r.roof if isinstance(r.roof, str) else "outdoors"
            outdoor = roof in ("outdoors", "open")
            wind = float(r.wind) if outdoor and not pd.isna(r.wind) else 0.0
            cold = 1.0 if (outdoor and not pd.isna(r.temp) and r.temp < 35) else 0.0
            f = dict(m_pts=ph - pa, m_epa=(eh - ea) * 65.0, rest=rest, qb=qb, t_pts=ph + pa, pace=lh + la, wind=wind, cold=cold)
            pm_ = f["m_pts"] if coef_m is None else float(coef_m @ [1, f["m_pts"], f["m_epa"], f["rest"], f["qb"]])
            pt_ = f["t_pts"] if coef_t is None else float(coef_t @ [1, f["t_pts"], f["pace"], f["wind"], f["cold"]])
            rec = dict(game_id=r.game_id, season=int(r.season), week=int(r.week), pred_m=pm_, pred_t=pt_, **f)
            if res_m is not None:
                pmf = pmf_from_residuals(pm_, res_m)
                rec["pmf_m"] = apply_keys(pmf, kr)
                rec["pmf_t"] = pmf_from_residuals(pt_, res_t, 0, 120)
                rec["resid_sd_m"] = float(res_m.std())
            out[r.game_id] = rec
        # AFTER predicting the week, its actuals become available for later weeks
        for r in cur.itertuples():
            if pd.isna(r.home_score):
                continue
            rec = out.get(r.game_id)
            f = rec if rec else None
            if f is None:
                # model not yet running (shouldn't happen for t>=23) -> skip
                continue
            oos.append(dict(t=t, game_id=r.game_id, margin=float(r.home_score - r.away_score), total=float(r.home_score + r.away_score), pred_m=f["pred_m"], pred_t=f["pred_t"],
                            m_pts=f["m_pts"], m_epa=f["m_epa"], rest=f["rest"], qb=f["qb"], t_pts=f["t_pts"], pace=f["pace"], wind=f["wind"], cold=f["cold"]))
    return out


def load_pbp_team(years):
    import pandas as pd
    d = {}
    for y in years:
        df = pd.read_csv(os.path.join(EXT, f"play_by_play_{y}.csv.gz"), usecols=["game_id", "posteam", "play_type", "epa", "qb_kneel", "qb_spike"], low_memory=False)
        df = df[df["play_type"].isin(["pass", "run"]) & df["epa"].notna() & (df["qb_kneel"] != 1) & (df["qb_spike"] != 1)]
        gp = df.groupby(["game_id", "posteam"])["epa"].agg(["mean", "size"])
        for (gid, tm), r in gp.iterrows():
            d[(gid, tm)] = (float(r["mean"]), int(r["size"]))
    return d


# ---------------------------------------------------------------- market side
def collect_market(games, idx):
    """per ticker (GAME, SPREAD): horizon prices from candles + tape. Streams the tape once."""
    rows = []
    for series in ("KXNFLGAME", "KXNFLSPREAD"):
        for m in N.load_markets(series):
            g = N.resolve_event(m["event_ticker"], idx)
            if g is None:
                continue
            y = N.outcome_yes(m)
            tk = m["ticker"]
            cand = N.load_candles(series, tk)
            tr = N.load_trades(series, tk)
            row = dict(ticker=tk, event_ticker=m["event_ticker"], series=series, family=N.FAMILY[series], game=g, outcome=y,
                       strike=m.get("floor_strike"), team=tk.split("-")[-1] if series == "KXNFLGAME" else None, has_candles=cand is not None, has_trades=tr is not None,
                       n_trades=len(tr) if tr else 0, hz={})
            if series == "KXNFLSPREAD":
                suffix = tk.split("-")[-1]
                row["team"] = "".join(c for c in suffix if c.isalpha())
            ko = g["kickoff"]
            for h, mins in HORIZONS.items():
                t = ko - timedelta(minutes=mins)
                q = candle_quote(cand, t)
                tp = tape_last(tr, t, STALE_CAP_MIN[h]) if tr else None
                row["hz"][h] = dict(bid=q and q["bid"], ask=q and q["ask"], cq_age=q and q["age_min"], tape=tp and tp["price"], tape_age=tp and tp["age_min"], tape_stale=tp and tp["stale"])
            rows.append(row)
    return rows


def team_is_home(row):
    t = N.K2N.get(row["team"], row["team"])
    return 1 if t == row["game"]["home"] else (0 if t == row["game"]["away"] else None)


def yes_prob_model(row, rec):
    """model P(YES) for a market row, or None."""
    if rec is None or "pmf_m" not in rec:
        return None
    home = team_is_home(row)
    if home is None:
        return None
    pm = rec["pmf_m"]
    if row["series"] == "KXNFLGAME":
        p_home = p_margin_gt(pm, 0.0)
        return p_home if home else 1 - p_home          # ties split 50/50 (Kalshi settles ties 50/50; ~0.3% of games)
    k = row["strike"]
    if k is None:
        return None
    return p_margin_gt(pm, k) if home else p_margin_gt(pm[::-1], k)


def entry_rows(mrows, models, h):
    """one record per (ticker, side) with executable ask at horizon h from candles. outcome-for-side win flag."""
    out = []
    for r in mrows:
        z = r["hz"][h]
        if r["outcome"] is None or z["ask"] is None or z["bid"] is None:
            continue
        home = team_is_home(r)
        mid = (z["ask"] + z["bid"]) / 2
        rec = models.get(r["game"]["game_id"])
        py = yes_prob_model(r, rec)
        base = dict(ticker=r["ticker"], gid=r["game"]["game_id"], family=r["family"], week=r["game"]["week"], per=period(r["game"]["week"], r["game"]["game_type"]),
                    home=home, mid=mid, spread=z["ask"] - z["bid"], py=py)
        for side in ("YES", "NO"):
            ask = z["ask"] if side == "YES" else 1 - z["bid"]
            win = r["outcome"] if side == "YES" else 1 - r["outcome"]
            fee = float(fees.fee_per_contract(ask, LOTS))
            out.append(dict(base, side=side, ask=ask, win=win, net=win - ask - fee, fee=fee, p_side=None if py is None else (py if side == "YES" else 1 - py),
                            fav=1 if (mid if side == "YES" else 1 - mid) > 0.5 else 0))
    return out


def summarize(recs, key="net"):
    if not recs:
        return dict(n=0)
    v = np.array([r[key] for r in recs])
    c = [r["gid"] for r in recs]
    s = stats.cluster_bootstrap(v, c, n_boot=1000)
    return dict(n=s["n"], n_games=s["n_clusters"], mean=round(s["mean"], 5), lo=round(s["lo"], 5), hi=round(s["hi"], 5), p=round(s["p"], 4),
                win=round(float(np.mean([r["win"] for r in recs])), 4), avg_ask=round(float(np.mean([r["ask"] for r in recs])), 4), avg_fee=round(float(np.mean([r["fee"] for r in recs])), 4))


def bucket_of(p):
    for i in range(len(BUCKETS) - 1):
        if BUCKETS[i] <= p < BUCKETS[i + 1]:
            return i
    return len(BUCKETS) - 2


def select_and_confirm(cells, min_n_disc=25, min_n_val=15):
    """cells: {cell_id: {period: [recs]}}. Choose on DISCOVERY only (mean>0, n>=min), confirm on VALIDATION (mean>0, n>=min), then report HOLDOUT once.
    Multiple testing: BH and Holm over the discovery p-values of ALL cells tried."""
    ids = sorted(cells)
    disc = {c: summarize(cells[c].get("discovery", [])) for c in ids}
    pvals = [disc[c].get("p", 1.0) if disc[c]["n"] else 1.0 for c in ids]
    bh, hm = stats.benjamini_hochberg(pvals), stats.holm(pvals)
    res = []
    for c, qb, qh in zip(ids, bh, hm):
        d = disc[c]
        row = dict(cell=c, discovery=d, bh_q=round(float(qb), 4), holm_p=round(float(qh), 4))
        sel = d["n"] >= min_n_disc and d["mean"] > 0
        row["selected_on_discovery"] = bool(sel)
        if sel:
            v = summarize(cells[c].get("validation", []))
            row["validation"] = v
            conf = v["n"] >= min_n_val and v["mean"] > 0
            row["confirmed_on_validation"] = bool(conf)
            if conf:
                row["holdout_frozen"] = summarize(cells[c].get("holdout", []))
        res.append(row)
    return dict(cells_tried=len(ids), selected=sum(r["selected_on_discovery"] for r in res), confirmed=sum(r.get("confirmed_on_validation", False) for r in res), rows=res)


# ---------------------------------------------------------------- main
def inventory(idx):
    inv = []
    root = N.BACKFILL
    for p in sorted(glob.glob(os.path.join(root, "markets", "*.jsonl"))):
        s = os.path.basename(p)[:-6]
        c = collections.Counter()
        ev = set()
        mapped_ev = set()
        for l in open(p):
            m = json.loads(l)
            c[m.get("result") or "none"] += 1
            ev.add(m["event_ticker"])
        inv.append(dict(series=s, family=N.FAMILY.get(s), markets=sum(c.values()), events=len(ev), settled_yes=c["yes"], settled_no=c["no"], scalar_or_other=sum(v for k, v in c.items() if k not in ("yes", "no")),
                        candle_files=len(glob.glob(os.path.join(root, "candles", s, "*.json"))), trade_files=len(glob.glob(os.path.join(root, "trades", s, "*.jsonl")))))
    return inv


def main():
    import pandas as pd
    gdf = pd.read_csv(os.path.join(EXT, "games.csv"))
    gdf = gdf[(gdf.season >= 2023) & (gdf.season <= 2025)].copy()
    games = N.load_games()
    idx = N.game_index(games)
    report = dict(version="sift-nfl-outcome/1", status="RESEARCH_ONLY",
                  notes=["nflverse spread_line/total_line/moneylines are CLOSING lines: used only as a benchmark, never as a feature",
                         f"fees: taker 0.07*P*(1-P) per contract at {LOTS}-lot (ceil to cent on the order); maker not used here",
                         "period split: discovery wk1-6, validation wk7-12, holdout wk13-18+playoffs; rules chosen on discovery, confirmed on validation, holdout evaluated once",
                         "Total / team-total / half / quarter / props series have settled outcomes but NO price history in the backfill: not priced here (coverage-limited)"])
    inv = inventory(idx)
    report["inventory_by_series"] = inv
    nfl_game_series = {r["series"]: r for r in inv if r["series"] in ("KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL", "KXNFLTEAMTOTAL")}
    report["inventory_note"] = f"{len(inv)} NFL-prefixed series in backfill; {sum(r['settled_yes']+r['settled_no'] for r in inv)} settled yes/no markets total"
    # mapping coverage for the game-level series
    mapcov = {}
    for s in ("KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL", "KXNFLTEAMTOTAL"):
        ms = N.load_markets(s)
        per_week = collections.Counter()
        unm = 0
        for m in ms:
            g = N.resolve_event(m["event_ticker"], idx)
            if g is None:
                unm += 1
            else:
                per_week[g["week"] if g["game_type"] == "REG" else 19] += 1
        mapcov[s] = dict(markets=len(ms), unmapped_to_regular_or_postseason_game=unm, mapped_by_week={str(k): v for k, v in sorted(per_week.items())})
    report["mapping_coverage"] = mapcov

    print("model...", flush=True)
    pbp = load_pbp_team((2023, 2024, 2025))
    models = build_model(gdf, pbp)
    gid_week = {g["game_id"]: g for g in games}
    print("market...", flush=True)
    mrows = collect_market(games, idx)
    # price coverage per horizon
    cov = {}
    for s in ("KXNFLGAME", "KXNFLSPREAD"):
        rs = [r for r in mrows if r["series"] == s]
        cov[s] = dict(tickers=len(rs), with_candles=sum(r["has_candles"] for r in rs), with_trades=sum(r["has_trades"] for r in rs), settled=sum(r["outcome"] is not None for r in rs),
                      by_horizon={h: dict(two_sided_candle_quote=sum(r["hz"][h]["ask"] is not None for r in rs),
                                          tape_price=sum(r["hz"][h]["tape"] is not None for r in rs),
                                          tape_fresh=sum(1 for r in rs if r["hz"][h]["tape"] is not None and not r["hz"][h]["tape_stale"]),
                                          median_candle_spread=(float(np.median([r["hz"][h]["ask"] - r["hz"][h]["bid"] for r in rs if r["hz"][h]["ask"] is not None])) if any(r["hz"][h]["ask"] is not None for r in rs) else None))
                                  for h in HORIZONS})
    report["price_coverage"] = cov
    # sanity: market result vs nflverse winner
    bad = tot = 0
    for r in mrows:
        if r["series"] == "KXNFLGAME" and r["outcome"] is not None and r["game"]["home_score"] is not None and r["game"]["home_score"] != r["game"]["away_score"]:
            home = team_is_home(r)
            if home is None:
                continue
            won = (r["game"]["home_score"] > r["game"]["away_score"]) == bool(home)
            tot += 1
            bad += int(won != bool(r["outcome"]))
    report["settlement_vs_nflverse_moneyline_mismatches"] = dict(checked=tot, mismatches=bad)

    # ---- market-only analysis
    ent = {h: entry_rows(mrows, models, h) for h in HORIZONS}
    base = {}
    for h in HORIZONS:
        for fam in ("moneyline", "spread"):
            for side in ("YES", "NO"):
                rs = [e for e in ent[h] if e["family"] == fam and e["side"] == side]
                if rs:
                    base.setdefault(fam, {}).setdefault(h, {})[side] = dict(all=summarize(rs), **{p: summarize([e for e in rs if e["per"] == p]) for p in ("discovery", "validation", "holdout")})
    report["unconditional_baselines_net_ev_per_contract"] = base
    # calibration by horizon x family x bucket (mid-implied YES prob vs outcome)
    calib = {}
    for h in HORIZONS:
        for fam in ("moneyline", "spread"):
            rs = [e for e in ent[h] if e["family"] == fam and e["side"] == "YES"]
            if not rs:
                continue
            p = np.array([e["mid"] for e in rs]); y = np.array([e["win"] for e in rs])
            calib.setdefault(fam, {})[h] = dict(n=len(rs), brier=round(stats.brier(p, y), 5), logloss=round(stats.logloss(p, y), 5),
                                                bins=[dict(b, mean_p=round(b["mean_p"], 4), freq=round(b["freq"], 4)) for b in stats.calibration_bins(p, y, BUCKETS)])
    report["market_calibration_yes_mid"] = calib

    # ---- rule cells
    cells = {}
    def add(cid, e):
        cells.setdefault(cid, {}).setdefault(e["per"], []).append(e)
    for h in HORIZONS:
        for e in ent[h]:
            b = bucket_of(e["ask"])
            add(f"MKT|{e['family']}|{h}|{e['side']}|ask_bucket{b}[{BUCKETS[b]:.2f},{min(BUCKETS[b+1],1):.2f})", e)
            if e["family"] == "moneyline":
                add(f"MKT|moneyline|{h}|{e['side']}|{'fav' if e['fav'] else 'dog'}", e)
                add(f"MKT|moneyline|{h}|{e['side']}|{'home' if e['home'] == (1 if e['side']=='YES' else 0) else 'away'}", e) if e["home"] is not None else None
    market_sel = select_and_confirm(cells)
    # ---- model-vs-ask rules: buy the side with the larger positive gap
    mcells = {}
    for h in ("24h", "6h"):
        for e in ent[h]:
            if e["p_side"] is None:
                continue
            gap = e["p_side"] - e["ask"]
            for thr in (0.02, 0.04, 0.06, 0.08, 0.10):
                if gap >= thr:
                    mcells.setdefault(f"MODEL|{e['family']}|{h}|gap>={thr:.2f}", {}).setdefault(e["per"], []).append(e)
    model_sel = select_and_confirm(mcells)
    report["market_only_rules"] = dict(cells_tried=market_sel["cells_tried"], selected_on_discovery=market_sel["selected"], confirmed_on_validation=market_sel["confirmed"],
                                       ranked_confirmed=sorted([r for r in market_sel["rows"] if r.get("confirmed_on_validation")], key=lambda r: -r["holdout_frozen"].get("mean", -9)),
                                       top_discovery_unconfirmed=sorted([r for r in market_sel["rows"] if r["selected_on_discovery"] and not r.get("confirmed_on_validation")], key=lambda r: -r["discovery"]["mean"])[:8],
                                       min_bh_q=min(r["bh_q"] for r in market_sel["rows"]), min_holm_p=min(r["holm_p"] for r in market_sel["rows"]))
    report["model_vs_ask_rules"] = dict(cells_tried=model_sel["cells_tried"], selected_on_discovery=model_sel["selected"], confirmed_on_validation=model_sel["confirmed"], rows=model_sel["rows"],
                                        min_bh_q=min(r["bh_q"] for r in model_sel["rows"]), min_holm_p=min(r["holm_p"] for r in model_sel["rows"]))

    # ---- model accuracy vs market vs closing line (games with model probs)
    def devig(r):
        try:
            a, h = float(r.away_moneyline), float(r.home_moneyline)
        except (TypeError, ValueError):
            return None
        def imp(m): return 100 / (m + 100) if m > 0 else -m / (-m + 100)
        ia, ih = imp(a), imp(h)
        return ih / (ia + ih)
    gm = {r.game_id: r for r in gdf[gdf.season == 2025].itertuples()}
    comp = []
    for h in ("24h", "6h"):
        for e in ent[h]:
            if e["family"] != "moneyline" or e["side"] != "YES" or e["py"] is None:
                continue
            gr = gm.get(e["gid"])
            if gr is None or e["home"] is None:
                continue
            ph = devig(gr)
            comp.append(dict(h=h, gid=e["gid"], per=e["per"], y=e["win"], model=e["py"], mkt=e["mid"], close=(None if ph is None else (ph if e["home"] else 1 - ph))))
    acc = {}
    for h in ("24h", "6h"):
        for per in ("discovery", "validation", "holdout", "all"):
            rs = [c for c in comp if c["h"] == h and (per == "all" or c["per"] == per) and c["close"] is not None]
            if len(rs) < 10:
                continue
            y = np.array([c["y"] for c in rs])
            d = {}
            for nm in ("model", "mkt", "close"):
                p = np.array([c[nm] for c in rs]); d[nm] = dict(brier=round(stats.brier(p, y), 5), logloss=round(stats.logloss(p, y), 5))
            diff = np.array([(c["model"] - c["y"]) ** 2 - (c["mkt"] - c["y"]) ** 2 for c in rs])
            cb = stats.cluster_bootstrap(diff, [c["gid"] for c in rs], n_boot=1000)
            d["brier_model_minus_market"] = dict(mean=round(cb["mean"], 5), lo=round(cb["lo"], 5), hi=round(cb["hi"], 5))
            d["n_tickers"] = len(rs)
            acc.setdefault(h, {})[per] = d
    report["moneyline_probability_accuracy"] = acc
    # margin / total accuracy of model vs closing lines (all 2025 games with model)
    mm = []
    for gid, rec in models.items():
        gr = gm.get(gid)
        if gr is None or "pmf_m" not in rec or pd.isna(gr.home_score):
            continue
        mm.append(dict(per=period(int(gr.week), gr.game_type), margin=gr.home_score - gr.away_score, total=gr.home_score + gr.away_score, pm=rec["pred_m"], pt=rec["pred_t"],
                       cl_m=gr.spread_line, cl_t=gr.total_line, week=int(gr.week)))
    macc = {}
    for per in ("discovery", "validation", "holdout", "all"):
        rs = [r for r in mm if per == "all" or r["per"] == per]
        rs = [r for r in rs if not (pd.isna(r["cl_m"]) or pd.isna(r["cl_t"]))]
        if rs:
            macc[per] = dict(n_games=len(rs), margin_mae_model=round(float(np.mean([abs(r["margin"] - r["pm"]) for r in rs])), 3), margin_mae_closing_line=round(float(np.mean([abs(r["margin"] - r["cl_m"]) for r in rs])), 3),
                             total_mae_model=round(float(np.mean([abs(r["total"] - r["pt"]) for r in rs])), 3), total_mae_closing_line=round(float(np.mean([abs(r["total"] - r["cl_t"]) for r in rs])), 3))
    report["model_margin_total_accuracy_vs_closing_line"] = macc
    report["model_walk_forward_spec"] = dict(prior_seasons=[2023, 2024], features=["opp-adjusted EPA/play (ridge O/D)", "opp-adjusted points (ridge O/D)", "plays/game pace", "rest diff", "QB-change flag (starter != team's previous starter)", "wind (outdoor)", "cold (<35F outdoor)", "home field"],
                                             ridge_lambda=15, half_life_weeks=30, second_stage="OLS on prior out-of-sample predictions (>=100 rows)", residuals="empirical walk-forward residuals only, key-number reweight for |margin| in 3,6,7,10,14 (shrunk, clipped)",
                                             games_with_probabilities=sum("pmf_m" in r for r in models.values()), injuries="not used (no point-in-time injury source wired); starter info limited to the QB-change flag from games.csv, which reflects the game's actual starter and is therefore NOT strictly pre-kickoff known — flag is a known approximate leak and is reported as such")
    # ---- per-contract jsonl for integration
    os.makedirs(WORK, exist_ok=True)
    with open(os.path.join(WORK, "nfl_model_probs.jsonl"), "w") as f:
        for r in mrows:
            g = r["game"]
            rec = models.get(g["game_id"])
            py = yes_prob_model(r, rec)
            hz = {h: dict(ask_yes=r["hz"][h]["ask"], bid_yes=r["hz"][h]["bid"], mid_yes=(None if r["hz"][h]["ask"] is None else (r["hz"][h]["ask"] + r["hz"][h]["bid"]) / 2),
                          last_trade_yes=r["hz"][h]["tape"], last_trade_age_min=r["hz"][h]["tape_age"]) for h in HORIZONS}
            side = (f"{r['team']} wins" if r["series"] == "KXNFLGAME" else f"{r['team']} wins by over {r['strike']}")
            f.write(json.dumps(dict(ticker=r["ticker"], event_ticker=r["event_ticker"], game_id=g["game_id"], family=r["family"], side_of_yes=side, week=g["week"], game_type=g["game_type"],
                                    kickoff_utc=g["kickoff"].isoformat(), period=period(g["week"], g["game_type"]), model_p_yes=py, horizons=hz, outcome_yes=r["outcome"])) + "\n")
    # ---- spread: priced only for the 22 playoff games (all holdout) -> descriptive, NOT selectable
    sp = [e for e in ent["24h"] if e["family"] == "spread" and e["side"] == "YES" and e["py"] is not None]
    if sp:
        y = np.array([e["win"] for e in sp]); pm_ = np.array([e["py"] for e in sp]); mk = np.array([e["mid"] for e in sp])
        d = np.array([(a - b) ** 2 for a, b in zip(pm_, y)]) - np.array([(a - b) ** 2 for a, b in zip(mk, y)])
        cb = stats.cluster_bootstrap(d, [e["gid"] for e in sp], n_boot=1000)
        report["spread_playoff_descriptive_24h"] = dict(n_tickers=len(sp), n_games=cb["n_clusters"], brier_model=round(stats.brier(pm_, y), 5), brier_market_mid=round(stats.brier(mk, y), 5),
                                                         brier_model_minus_market=dict(mean=round(cb["mean"], 5), lo=round(cb["lo"], 5), hi=round(cb["hi"], 5)),
                                                         note="all 22 priced spread games are playoff/holdout; no discovery/validation split possible, so nothing is selected here")
    # ---- ranked findings
    ranked = []
    for src, sel in (("market_only", market_sel), ("model_vs_ask", model_sel)):
        for r in sel["rows"]:
            if r.get("confirmed_on_validation"):
                h = r["holdout_frozen"]
                ranked.append(dict(source=src, cell=r["cell"], discovery_mean=r["discovery"]["mean"], validation_mean=r["validation"]["mean"], holdout_net_ev=h.get("mean"), holdout_ci=[h.get("lo"), h.get("hi")],
                                   holdout_n=h.get("n"), holdout_games=h.get("n_games"), bh_q_discovery=r["bh_q"], holm_p_discovery=r["holm_p"]))
    ranked.sort(key=lambda r: -(r["holdout_net_ev"] if r["holdout_net_ev"] is not None else -9))
    report["ranked_findings_by_frozen_holdout_net_ev"] = ranked
    report["ranking_note"] = "Ranked by frozen-holdout net EV per contract (dollars). A finding counts only if its holdout CI excludes 0 AND discovery BH q is small; everything else is a null."
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(report, open(OUT, "w"), indent=1, sort_keys=True, default=lambda o: None if isinstance(o, float) and math.isnan(o) else float(o))
    print("done", len(ranked), "confirmed cells")


if __name__ == "__main__":
    main()
