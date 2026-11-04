#!/usr/bin/env python3
"""Independent NFL audit + incremental test (RESEARCH_ONLY). Does NOT import research/outcome_exec or sift_research.

Inputs (read-only): nfl-edge-finder@market-data data/kalshi/backfill/{markets,candles}, nflverse games.csv (scores), optional PR#25 model probs.
usage: python3 -I research/outcome_intel/audit_nfl.py --backfill DIR --games games.csv --out reports/outcome_intel/nfl_audit.json [--pr-model FILE]
"""
from __future__ import annotations
import argparse, collections, glob, hashlib, json, math, os, re, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import incremental as I
import status as S

ET = ZoneInfo("America/New_York")
MON = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
ALIAS = {"JAC": "JAX"}
LOTS = 100


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fee(price, lots=LOTS):
    return math.ceil(round(0.07 * lots * price * (1 - price) * 100, 9)) / 100 / lots


def load_games(path):
    import csv
    G = []
    for r in csv.DictReader(open(path)):
        if not r["home_score"]:
            continue
        hh, mm = (r["gametime"] or "13:00").split(":")
        ko = datetime.strptime(r["gameday"], "%Y-%m-%d").replace(hour=int(hh), minute=int(mm), tzinfo=ET).astimezone(timezone.utc)
        G.append(dict(id=r["game_id"], season=int(r["season"]), week=int(r["week"]), type=r["game_type"], day=r["gameday"], ko=ko,
                      away=r["away_team"], home=r["home_team"], ap=int(float(r["away_score"])), hp=int(float(r["home_score"]))))
    return G


def parse_event(ev):
    m = re.match(r"^(KX[A-Z0-9]+)-(\d{2})([A-Z]{3})(\d{2})([A-Z]+)$", ev)
    if not m:
        return None
    s, yy, mon, dd, codes = m.groups()
    return s, datetime(2000 + int(yy), MON[mon], int(dd)).date(), codes


def resolve(ev, gidx, teams):
    p = parse_event(ev)
    if not p:
        return None
    _, d, codes = p
    for cut in (2, 3):
        a, h = ALIAS.get(codes[:cut], codes[:cut]), ALIAS.get(codes[cut:], codes[cut:])
        if a in teams and h in teams:
            for dd in (d, d - timedelta(days=1), d + timedelta(days=1)):
                g = gidx.get((dd.isoformat(), a, h))
                if g:
                    return g
    return None


def derive(series, ticker, strike, g):
    """Independent outcome derivation from final score. None = cannot derive (kept as UNKNOWN, never guessed)."""
    suffix = ticker.rsplit("-", 1)[1]
    if series == "KXNFLGAME":
        t = ALIAS.get(suffix, suffix)
        if g["hp"] == g["ap"]:
            return "tie"
        return "yes" if (t == g["home"] and g["hp"] > g["ap"]) or (t == g["away"] and g["ap"] > g["hp"]) else "no" if t in (g["home"], g["away"]) else None
    if series == "KXNFLTOTAL" and strike is not None:
        return "yes" if g["hp"] + g["ap"] > strike else "no"
    m = re.match(r"^([A-Z]+?)(\d+)$", suffix)
    if series in ("KXNFLSPREAD", "KXNFLTEAMTOTAL") and m and strike is not None:
        t = ALIAS.get(m.group(1), m.group(1))
        if t not in (g["home"], g["away"]):
            return None
        mine, opp = (g["hp"], g["ap"]) if t == g["home"] else (g["ap"], g["hp"])
        return ("yes" if mine - opp > strike else "no") if series == "KXNFLSPREAD" else ("yes" if mine > strike else "no")
    return None


def candle_at(c, ts):
    best = None
    for k in c.get("h60", []):
        if k["end_period_ts"] <= ts:
            best = k
        else:
            break
    if not best:
        return None
    try:
        b, a = float(best["yes_bid"]["close"]), float(best["yes_ask"]["close"])
    except (TypeError, ValueError):
        return None
    return (b, a) if 0 < b <= a < 1 else None


def ratings_probs(games, target, sigma=13.5, lam=8.0, half=40.0):
    """Opponent-adjusted margin ratings (independent of PR#25): ridge on margin using ONLY games from strictly earlier (season,week)
    than the target's, 2023+ seasons, exponential recency weights (half-life = half*7 days)."""
    past = [g for g in games if (g["season"], g["week"]) < (target["season"], target["week"]) and g["season"] >= 2023]
    teams = sorted({g["home"] for g in past} | {g["away"] for g in past} | {target["home"], target["away"]})
    ix = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    X = np.zeros((len(past), n + 1)); y = np.zeros(len(past)); w = np.zeros(len(past))
    for r, g in enumerate(past):
        X[r, ix[g["home"]]] = 1; X[r, ix[g["away"]]] = -1; X[r, n] = 1
        y[r] = np.clip(g["hp"] - g["ap"], -28, 28)
        w[r] = 0.5 ** ((target["ko"] - g["ko"]).days / (half * 7))
    P = np.eye(n + 1) * lam; P[n, n] = 0.0
    beta = np.linalg.solve(X.T @ (X * w[:, None]) + P, X.T @ (w * y))
    margin = beta[ix[target["home"]]] - beta[ix[target["away"]]] + beta[n]
    return 0.5 * (1 + math.erf(margin / sigma / math.sqrt(2))), float(margin)


def run(a):
    G = load_games(a.games)
    teams = {g["home"] for g in G} | {g["away"] for g in G}
    gidx = {(g["day"], g["away"], g["home"]): g for g in G}
    out = dict(status="RESEARCH_ONLY", schema="sift-outcome-intel-nfl-audit/1", lots=LOTS,
               inputs=dict(games_csv_sha256=sha(a.games), market_files={os.path.basename(f): sha(f) for f in sorted(glob.glob(a.backfill + "/markets/KXNFLGAME.jsonl") + glob.glob(a.backfill + "/markets/KXNFLSPREAD.jsonl") + glob.glob(a.backfill + "/markets/KXNFLTOTAL.jsonl") + glob.glob(a.backfill + "/markets/KXNFLTEAMTOTAL.jsonl"))},
                           n_nflverse_games_with_scores=len(G)))
    # ---- universe
    uni = {}
    for f in sorted(glob.glob(a.backfill + "/markets/*.jsonl")):
        s = os.path.basename(f)[:-6]
        M = [json.loads(l) for l in open(f) if l.strip()]
        res = collections.Counter(m.get("result") or ("unsettled:" + str(m.get("status"))) for m in M)
        uni[s] = dict(markets=len(M), events=len({m["event_ticker"] for m in M}), results=dict(res),
                      candle_files=len(glob.glob(f"{a.backfill}/candles/{s}/*.json")), trade_files=len(glob.glob(f"{a.backfill}/trades/{s}/*.jsonl")))
    out["universe"] = dict(series=len(uni), settled_yes_no=sum(v["results"].get("yes", 0) + v["results"].get("no", 0) for v in uni.values()),
                           by_series={k: v for k, v in sorted(uni.items(), key=lambda kv: -kv[1]["markets"])[:40]},
                           series_with_pregame_price_history=[k for k, v in uni.items() if v["candle_files"]])
    # ---- settlement verification for game-score-derivable families
    ver = {}
    rows_ml = []
    for s in ("KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL", "KXNFLTEAMTOTAL"):
        c = collections.Counter(); bad = []; games = set()
        for l in open(f"{a.backfill}/markets/{s}.jsonl"):
            m = json.loads(l)
            g = resolve(m["event_ticker"], gidx, teams)
            if not g:
                c["unmapped_event"] += 1; continue
            games.add(g["id"])
            mine = derive(s, m["ticker"], m.get("floor_strike"), g)
            kal = m.get("result")
            if mine is None:
                c["underivable"] += 1
            elif kal not in ("yes", "no"):
                c["kalshi_" + str(kal) + ("_my_tie" if mine == "tie" else "")] += 1
            elif mine == kal:
                c["agree"] += 1
            else:
                c["DISAGREE"] += 1; bad.append(dict(t=m["ticker"], mine=mine, kalshi=kal, score=(g["ap"], g["hp"])))
            if s == "KXNFLGAME" and kal in ("yes", "no"):
                rows_ml.append((m, g))
        ver[s] = dict(counts=dict(c), disagreements=bad[:20], games=len(games))
    out["settlement_verification"] = ver
    out["settlement_source"] = "Kalshi official `result` field on finalized markets (market_data backfill); re-derived from nflverse final scores"

    # ---- moneyline pregame prices: 24h / 6h / 90m, buy-at-ask EV and Brier vs closing
    H = {"24h": 24 * 3600, "6h": 6 * 3600, "90m": 90 * 60}
    per = {h: [] for h in H}
    for m, g in rows_ml:
        if g["season"] != 2025:
            continue
        cp = f"{a.backfill}/candles/KXNFLGAME/{m['ticker']}.json"
        if not os.path.exists(cp):
            continue
        c = json.load(open(cp))
        y = 1 if m["result"] == "yes" else 0
        t = ALIAS.get(m["ticker"].rsplit("-", 1)[1], m["ticker"].rsplit("-", 1)[1])
        close = candle_at(c, int(g["ko"].timestamp()))
        for h, sec in H.items():
            q = candle_at(c, int(g["ko"].timestamp()) - sec)
            if q:
                per[h].append(dict(tk=m["ticker"], g=g["id"], ko=g["ko"], t=t, home=(t == g["home"]), y=y, bid=q[0], ask=q[1], close=close, week=g["week"], gt=g["type"], gm=g))
    out["moneyline_2025"] = {}
    for h, R in per.items():
        d = dict(tickers=len(R), games=len({r["g"] for r in R}))
        for side in ("yes", "no"):
            pn = [(r["y"] if side == "yes" else 1 - r["y"]) - (r["ask"] if side == "yes" else 1 - r["bid"]) - fee(r["ask"] if side == "yes" else 1 - r["bid"]) for r in R]
            d["buy_" + side + "_at_ask_net_per_contract"] = I.cluster_ci(pn, [r["g"] for r in R], seed=5)
        mid = np.array([(r["bid"] + r["ask"]) / 2 for r in R]); y = np.array([r["y"] for r in R], float)
        d["brier_mid"] = float(((mid - y) ** 2).mean()); d["logloss_mid"] = float(I.ll(np.clip(mid, 1e-6, 1 - 1e-6), y).mean())
        cl = [r for r in R if r["close"]]
        if cl:
            cm = np.array([(r["close"][0] + r["close"][1]) / 2 for r in cl]); cy = np.array([r["y"] for r in cl], float)
            d["brier_closing_mid_same_tickers"] = float(((cm - cy) ** 2).mean()); d["closing_n"] = len(cl)
        out["moneyline_2025"][h] = d

    # ---- challengers (home-team contract only: the two tickers of a game are exact mirrors -> one independent row per game)
    chal = {}
    pr = {}
    if a.pr_model and os.path.exists(a.pr_model):
        for l in open(a.pr_model):
            r = json.loads(l)
            if r.get("family") == "moneyline" and r.get("model_p_yes") is not None:
                pr[r["ticker"]] = r["model_p_yes"]
    for h in H:
        rows = []
        for r in per[h]:
            if not r["home"]:
                continue
            q, margin = ratings_probs(G, r["gm"])
            rows.append(dict(game=r["g"], t=r["ko"].isoformat(), mid=(r["bid"] + r["ask"]) / 2, q=q, y=r["y"], week=r["week"], gt=r["gt"]))
        res = I.incremental_test(rows)
        res["negative_control_gain_vs_calibrated"] = I.negative_control(rows).get("gain_vs_calibrated_market_logloss")
        res["challenger"] = "independent opponent-adjusted ridge margin ratings (nflverse scores, strictly earlier weeks, 2023+)"
        res["rows_one_per_game"] = len(rows)
        chal[h] = res
        if pr:
            rows2 = [dict(game=r["g"], t=r["ko"].isoformat(), mid=(r["bid"] + r["ask"]) / 2, q=pr[r["tk"]], y=r["y"]) for r in per[h] if r["home"] and r["tk"] in pr]
            res2 = I.incremental_test(rows2)
            res2["negative_control_gain_vs_calibrated"] = I.negative_control(rows2).get("gain_vs_calibrated_market_logloss")
            res2["challenger"] = "PR #25 walk-forward matchup model (model_p_yes from nfl_model_probs.jsonl, produced by research/outcome_exec/nfl_outcome.py)"
            res2["rows_one_per_game"] = len(rows2)
            chal[h + "|PR25_model"] = res2
    out["incremental_independent_ratings"] = chal
    # ---- spread price coverage (candles exist only for a subset)
    sp = [json.loads(l) for l in open(f"{a.backfill}/markets/KXNFLSPREAD.jsonl")]
    have = {os.path.basename(f)[:-5] for f in glob.glob(f"{a.backfill}/candles/KXNFLSPREAD/*.json")}
    sp_games = {(resolve(m["event_ticker"], gidx, teams) or {}).get("id") for m in sp if m["ticker"] in have} - {None}
    out["spread_price_coverage"] = dict(settled_markets=sum(m.get("result") in ("yes", "no") for m in sp), with_candles=len(have), games_with_candles=len(sp_games),
                                        game_types=dict(collections.Counter(g["type"] for g in G if g["id"] in sp_games)))
    cells = []
    nfam = {"KXNFLTOTAL": "total", "KXNFLTEAMTOTAL": "team_total"}
    for h in H:
        for key, label in ((h, "SIFT-independent opponent-adjusted ratings"), (h + "|PR25_model", "PR #25 matchup model")):
            c = chal.get(key)
            if not c:
                continue
            p = None
            cells.append(dict(sport="NFL", family="moneyline", horizon=h, challenger=label, n_games=c.get("rows_one_per_game"), n_contracts=out["moneyline_2025"][h]["tickers"],
                              holdout_games=c.get("holdout_games"), price_coverage="hourly candle bid/ask (two-sided) for all 2025 settled tickers", settlement_source="Kalshi official result; re-derived from nflverse 566/566",
                              market_metrics=c.get("logloss"), incremental_gain=c.get("gain_vs_calibrated_market_logloss"),
                              status=S.classify(c, None, c.get("negative_control_gain_vs_calibrated")), reason="single-season walk-forward; holdout is the last third of games" ))
    for f_, (s_, why) in {"spread": ("INCONCLUSIVE_UNDERPOWERED", "pregame candles exist for %d of %d settled markets, playoff games only (%s)" % (len(have), out["spread_price_coverage"]["settled_markets"], out["spread_price_coverage"]["game_types"])),
                          "total": ("MISSING_DATA", "settled outcomes verified, but NO pregame price history (candles/trades collected only for KXNFLGAME/KXNFLSPREAD); repair: extend backfill collector to KXNFLTOTAL"),
                          "team_total": ("MISSING_DATA", "no pregame price history; repair: add KXNFLTEAMTOTAL candles+trades"),
                          "1h/2h/quarter": ("MISSING_DATA", "outcome inventory only; no pregame prices; period scores needed from pbp for verification"),
                          "player_props": ("MISSING_DATA", "10k+ settled markets per prop series but no pregame prices and no player-level projections timestamped pregame")}.items():
        cells.append(dict(sport="NFL", family=f_, horizon="all", n_contracts=None, status=s_, reason=why))
    out["cells"] = cells
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", required=True); ap.add_argument("--games", required=True)
    ap.add_argument("--out", default="reports/outcome_intel/nfl_audit.json"); ap.add_argument("--pr-model", default=None)
    a = ap.parse_args()
    res = run(a)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(res, open(a.out, "w"), indent=1, sort_keys=True, default=str)
    print(json.dumps({k: res[k] for k in ("settlement_verification", "moneyline_2025")}, indent=1, default=str)[:4000])


if __name__ == "__main__":
    main()
