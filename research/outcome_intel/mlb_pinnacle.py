#!/usr/bin/env python3
"""MLB 2022-2026 multi-season market-first study against the ONLY archived multi-season market: sampled Pinnacle pregame prices (The Odds API historical,
every ~5th day, snapshots 18:15/21:15 ET). Kalshi has no 2022-2025 price history, so these cells are Pinnacle-baseline, NOT Kalshi-baseline.
Challenger = a strictly point-in-time proxy built from season-to-date runs scored/allowed (schedule finals strictly BEFORE first pitch); not a
reconstruction of the production model (season-aggregate production inputs are not archived historically).
Split is by SEASON: fit on 2022-2024, validate 2025, untouched holdout 2026. Holm over the cells tried. RESEARCH_ONLY.
usage: python3 -I research/outcome_intel/mlb_pinnacle.py --root <edge-finder-api checkout> --out reports/outcome_intel/mlb_pinnacle.json
"""
from __future__ import annotations
import argparse, glob, json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import incremental as I
import mlb_data as D

MAX_MIN_BEFORE = 60
MIN_PRIOR_GAMES = 20
TRAIN, VALID, HOLD = (2022, 2023, 2024), (2025,), (2026,)


def american_to_prob(p):
    return 100.0 / (p + 100.0) if p > 0 else -p / (-p + 100.0)


def devig(a, b):
    pa, pb = american_to_prob(a), american_to_prob(b)
    return pa / (pa + pb)


def load_pinnacle(root):
    """-> list of dict(game key fields, snapshot time, price time, home_ml_fair, total_line, over_fair). Hashes returned too."""
    out, hashes = [], {}
    for f in sorted(glob.glob(os.path.join(root, "data/research_cache/pinnacle_historical/*/*.json"))):
        hashes[os.path.relpath(f, root)] = D.sha256_file(f)
        d = json.load(open(f))
        for sn in d["snapshots"]:
            req = D.parse_ts(sn.get("requestedAtIso"))
            for g in sn["games"]:
                bm = [b for b in g.get("bookmakers", []) if b.get("key") == "pinnacle"]
                if not bm:
                    continue
                rec = dict(home=g["home_team"], away=g["away_team"], commence=D.parse_ts(g["commence_time"]), req=req, home_fair=None, line=None, over_fair=None, price_time=None)
                for m in bm[0]["markets"]:
                    lu = D.parse_ts(m.get("last_update"))
                    if m["key"] == "h2h":
                        o = {x["name"]: x["price"] for x in m["outcomes"]}
                        if g["home_team"] in o and g["away_team"] in o:
                            rec["home_fair"] = devig(o[g["home_team"]], o[g["away_team"]])
                            rec["price_time"] = lu
                    elif m["key"] == "totals":
                        ov = [x for x in m["outcomes"] if x["name"] == "Over"]
                        un = [x for x in m["outcomes"] if x["name"] == "Under"]
                        if ov and un and ov[0].get("point") == un[0].get("point"):
                            rec["line"], rec["over_fair"] = float(ov[0]["point"]), devig(ov[0]["price"], un[0]["price"])
                            rec["tprice_time"] = lu
                out.append(rec)
    return out, hashes


def match_games(pin, games):
    """Attach gamePk by exact (home name, away name) and nearest scheduled start within 3h. Unmatched stay unmatched (never guessed)."""
    g = games.copy()
    g["t0"] = pd.to_datetime(g["gameDate"], utc=True)
    idx = {}
    for r in g.itertuples():
        idx.setdefault((r.homeName, r.awayName), []).append((r.t0, r.gamePk))
    for p in pin:
        best = None
        for t0, pk in idx.get((p["home"], p["away"]), []):
            dt = abs((t0 - p["commence"]).total_seconds())
            if dt <= 3 * 3600 and (best is None or dt < best[0]):
                best = (dt, pk)
        p["pk"] = best[1] if best else None
    return pin


def pick_pregame(pin):
    """Per game: the snapshot with the smallest positive minutes-before-first-pitch within (0, 60]. Price time must also precede first pitch."""
    best = {}
    for p in pin:
        if p["pk"] is None:
            continue
        mb = (p["commence"] - p["req"]).total_seconds() / 60.0
        pt = p.get("price_time") or p.get("tprice_time")
        if not (0 < mb <= MAX_MIN_BEFORE) or pt is None or pt >= p["commence"]:
            continue
        p["mins_before"] = mb
        if p["pk"] not in best or mb < best[p["pk"]]["mins_before"]:
            best[p["pk"]] = p
    return best


# ------------------------------------------------------------------ point-in-time proxy
def team_state(games):
    """Per game, per team: runs scored/allowed per game over that team's earlier FINAL games of the same season (strictly earlier start)."""
    g = games[(games["state"] == "Final") & games["homeRuns"].notna()].copy()
    g["t0"] = pd.to_datetime(g["gameDate"], utc=True)
    g = g.sort_values("t0")
    long = pd.concat([g[["gamePk", "season", "t0", "homeId", "homeRuns", "awayRuns"]].rename(columns=dict(homeId="team", homeRuns="rs", awayRuns="ra")),
                      g[["gamePk", "season", "t0", "awayId", "awayRuns", "homeRuns"]].rename(columns=dict(awayId="team", awayRuns="rs", homeRuns="ra"))]).sort_values(["team", "season", "t0", "gamePk"])
    long["n_prior"] = long.groupby(["team", "season"]).cumcount()
    for c in ("rs", "ra"):
        long[c + "_prior"] = long.groupby(["team", "season"])[c].cumsum() - long[c]  # strictly BEFORE this game (cumulative minus own result)
    long["rs_pg"] = long["rs_prior"] / long["n_prior"].replace(0, np.nan)
    long["ra_pg"] = long["ra_prior"] / long["n_prior"].replace(0, np.nan)
    return long.set_index(["gamePk", "team"])[["n_prior", "rs_pg", "ra_pg"]]


def lg_avg(games, season, t0):
    g = games[(games["season"] == season) & (games["state"] == "Final")]
    t = pd.to_datetime(g["gameDate"], utc=True)
    g = g[t < t0]
    if len(g) < 50:
        return None
    return float((g["homeRuns"] + g["awayRuns"]).mean() / 2.0)


def poisson_pmf(lam, kmax=30):
    k = np.arange(kmax + 1)
    return np.exp(-lam + k * np.log(lam) - np.array([math.lgamma(x + 1) for x in k]))


def proxy_probs(lh, la, line):
    ph, pa = poisson_pmf(lh), poisson_pmf(la)
    joint = np.outer(ph, pa)
    win = np.tril(joint, -1).sum()  # home runs > away runs
    lose = np.triu(joint, 1).sum()
    p_home = win / (win + lose)
    tot = np.convolve(ph, pa)
    k = np.arange(len(tot))
    over = tot[k > line].sum()
    under = tot[k < line].sum()
    return float(p_home), (float(over / (over + under)) if over + under > 0 else None)


def build_rows(root, games):
    pin, hashes = load_pinnacle(root)
    pin = match_games(pin, games)
    best = pick_pregame(pin)
    st = team_state(games)
    gi = games.set_index("gamePk")
    rows_ml, rows_tot = [], []
    n_pin = len(best)
    hf = None
    for pk, p in sorted(best.items()):
        r = gi.loc[pk]
        if r["state"] != "Final" or pd.isna(r["homeRuns"]):
            continue
        try:
            sh, sa = st.loc[(pk, r["homeId"])], st.loc[(pk, r["awayId"])]
        except KeyError:
            continue
        if sh["n_prior"] < MIN_PRIOR_GAMES or sa["n_prior"] < MIN_PRIOR_GAMES:
            continue
        lg = lg_avg(games, int(r["season"]), p["commence"])
        if lg is None:
            continue
        lam_h = max(0.5, (sh["rs_pg"] + sa["ra_pg"]) / 2.0)
        lam_a = max(0.5, (sa["rs_pg"] + sh["ra_pg"]) / 2.0)
        base = dict(game=int(pk), t=p["commence"].isoformat(), season=int(r["season"]), lam_h=float(lam_h), lam_a=float(lam_a), req=p["req"].isoformat())
        if p["home_fair"] is not None:
            rows_ml.append(dict(base, mid=float(p["home_fair"]), y=int(r["homeRuns"] > r["awayRuns"]), pin_time=(p.get("price_time") or p["req"]).isoformat()))
        if p["line"] is not None and p["over_fair"] is not None:
            tot = r["homeRuns"] + r["awayRuns"]
            if tot != p["line"]:  # push -> void, excluded
                rows_tot.append(dict(base, mid=float(p["over_fair"]), y=int(tot > p["line"]), line=p["line"]))
    return rows_ml, rows_tot, hashes, n_pin, len(pin)


def attach_q(rows, kind, hfa):
    out = []
    for r in rows:
        lh, la = r["lam_h"] + hfa / 2, r["lam_a"] - hfa / 2
        ph, po = proxy_probs(max(lh, 0.5), max(la, 0.5), r.get("line", 0))
        q = ph if kind == "ml" else po
        if q is None:
            continue
        out.append(dict(r, q=float(np.clip(q, 0.02, 0.98))))
    return out


def season_test(rows, ridge=1.0, seed=17):
    tr = [r for r in rows if r["season"] in TRAIN]
    va = [r for r in rows if r["season"] in VALID]
    ho = [r for r in rows if r["season"] in HOLD]
    out = dict(train_games=len({r["game"] for r in tr}), valid_games=len({r["game"] for r in va}), holdout_games=len({r["game"] for r in ho}),
               n_train=len(tr), n_valid=len(va), n_holdout=len(ho))
    if len(tr) < 100 or len(ho) < 30:
        out["status"] = "UNDERPOWERED"
        return out
    ytr = np.array([r["y"] for r in tr], float)
    wB, wC = I.fit_logistic(I._X(tr, False), ytr, ridge), I.fit_logistic(I._X(tr, True), ytr, ridge)
    out.update(status="OK", coef_baseline=[float(x) for x in wB], coef_challenger=[float(x) for x in wC])
    for name, part in (("validation_2025", va), ("holdout_2026", ho)):
        if not part:
            continue
        y = np.array([r["y"] for r in part], float)
        raw = np.clip(np.array([r["mid"] for r in part], float), 1e-6, 1 - 1e-6)
        pB, pC = I.sigmoid(I._X(part, False) @ wB), I.sigmoid(I._X(part, True) @ wC)
        qraw = np.clip(np.array([r["q"] for r in part], float), 1e-6, 1 - 1e-6)
        g = [r["game"] for r in part]
        out[name] = dict(n=len(part), logloss=dict(raw_market=float(I.ll(raw, y).mean()), calibrated_market=float(I.ll(pB, y).mean()), challenger=float(I.ll(pC, y).mean()),
                                                     raw_proxy=float(I.ll(qraw, y).mean())),
                         brier=dict(raw_market=float(((raw - y) ** 2).mean()), calibrated_market=float(((pB - y) ** 2).mean()), challenger=float(((pC - y) ** 2).mean())),
                         gain_vs_calibrated_market_logloss=I.cluster_ci(I.ll(pB, y) - I.ll(pC, y), g, seed=seed))
    # negative control: game-shuffled proxy, same fit/eval
    rng = np.random.default_rng(0)
    qs = np.array([r["q"] for r in rows])
    sh = [dict(r, q=float(qs[i])) for r, i in zip(rows, rng.permutation(len(rows)))]
    neg = season_test_inner(sh)
    out["negative_control_holdout_gain"] = neg
    return out


def season_test_inner(rows, ridge=1.0):
    tr = [r for r in rows if r["season"] in TRAIN]
    ho = [r for r in rows if r["season"] in HOLD]
    ytr = np.array([r["y"] for r in tr], float)
    wB, wC = I.fit_logistic(I._X(tr, False), ytr, ridge), I.fit_logistic(I._X(tr, True), ytr, ridge)
    y = np.array([r["y"] for r in ho], float)
    return I.cluster_ci(I.ll(I.sigmoid(I._X(ho, False) @ wB), y) - I.ll(I.sigmoid(I._X(ho, True) @ wC), y), [r["game"] for r in ho])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", default="reports/outcome_intel/mlb_pinnacle.json")
    a = ap.parse_args()
    games, ghash = D.load_schedule_games(a.root)
    rows_ml, rows_tot, phash, n_pin, n_raw = build_rows(a.root, games)
    # home-field adjustment fitted on TRAIN seasons only (closed form), then frozen
    tr_ml = [r for r in rows_ml if r["season"] in TRAIN]
    gi = games.set_index("gamePk")
    resid = [float((gi.loc[r["game"], "homeRuns"] - gi.loc[r["game"], "awayRuns"]) - (r["lam_h"] - r["lam_a"])) for r in tr_ml]
    hfa = float(np.mean(resid)) if resid else 0.0
    cells = []
    for name, rows, kind in (("moneyline", rows_ml, "ml"), ("game_total", rows_tot, "tot")):
        rq = attach_q(rows, kind, hfa)
        c = season_test(rq) if rq else dict(status="UNDERPOWERED")
        c.update(sport="MLB", family=name, horizon="<=60min_before_first_pitch", challenger="proxy_season_to_date_runs", baseline="pinnacle_devig_pregame_sampled",
                 market="PINNACLE (not Kalshi)", n_games=len({r["game"] for r in rq}), n_contracts=len(rq),
                 per_season_games={str(s): len({r["game"] for r in rq if r["season"] == s}) for s in (2022, 2023, 2024, 2025, 2026)},
                 inputs_available=["season-to-date runs scored/allowed from schedule finals strictly before first pitch (PIT-safe)",
                                   "home-field runs constant fit on 2022-2024 only"],
                 settlement_source="final runs from MLB schedule (independent of any Kalshi settlement)", home_field_adj_runs=hfa)
        cells.append(c)
    ok = [c for c in cells if c["status"] == "OK" and "holdout_2026" in c]
    adj = I.holm([c["holdout_2026"]["gain_vs_calibrated_market_logloss"]["p"] for c in ok]) if ok else []
    for c, p in zip(ok, adj):
        c["holm_p"] = float(p)
        g = c["holdout_2026"]["gain_vs_calibrated_market_logloss"]
        se = (g["hi"] - g["lo"]) / 3.92
        c["mde_logloss_80pct_power"] = 2.8 * se
        if g["lo"] > 0 and c["holm_p"] <= 0.05:
            c["status_final"], c["reason"] = "VALIDATED_IMPROVEMENT", "holdout CI > 0 and Holm p <= .05"
        elif g["mean"] > 0 and g["p"] <= 0.05:
            c["status_final"], c["reason"] = "PROMISING_INSUFFICIENT", "nominal p<=.05, Holm p=%.3f" % c["holm_p"]
        else:
            c["status_final"] = "NO_DEMONSTRATED_IMPROVEMENT" if (c["holdout_games"] >= 150 or g["hi"] < 0) else "INCONCLUSIVE_UNDERPOWERED"
            c["reason"] = ("holdout %d games (sampled Pinnacle days only), gain %+.4f [%+.4f,%+.4f], MDE~%.3f logloss" %
                           (c["holdout_games"], g["mean"], g["lo"], g["hi"], c["mde_logloss_80pct_power"]))
        c["incremental_gain"] = dict(mean=g["mean"], lo=g["lo"], hi=g["hi"], holm_p=c["holm_p"])
        c["market_logloss"] = c["holdout_2026"]["logloss"]
        c["market_brier"] = c["holdout_2026"]["brier"]
    for c in cells:
        if "status_final" not in c:
            c["status_final"], c["reason"] = "INCONCLUSIVE_UNDERPOWERED", "too few matched games for a season split"
    res = dict(status="RESEARCH_ONLY", schema="sift-outcome-intel-mlb-pinnacle/1", pinnacle_games_with_pregame_snapshot=n_pin, pinnacle_game_snapshots_raw=n_raw,
               games_in_rows=dict(moneyline=len(rows_ml), game_total=len(rows_tot)), cells=cells, inputs=dict(schedule_sha256=ghash, pinnacle_sha256=phash), protocol=__doc__)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(res, open(a.out, "w"), indent=1, sort_keys=True, default=str)
    for c in cells:
        print(c["family"], c["status_final"], c.get("per_season_games"), c.get("incremental_gain"), c["reason"])


if __name__ == "__main__":
    main()
