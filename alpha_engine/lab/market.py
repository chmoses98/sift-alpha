"""Model-vs-Kalshi comparison layer (evaluation only: nothing here feeds a model).

Contract -> fair probability:  moneyline/spread/total/team-total from the game lab's margin, total and team-points distributions; player stats from the player lab
(P(active) x P(stat >= k | active)).  Executable price = ask for YES, 1 - bid for NO, from the point-in-time snapshot at the decision horizon (two-sided, <= 10c wide, <= 180 min old).
Net EV uses the exchange taker fee (0.07 x p x (1-p), whole-order rounding) at that price and settlement at the contract result.  Uncertainty clusters by GAME.
Segment search: segments are chosen on the DISCOVERY weeks of 2025 and evaluated once on the later HOLDOUT weeks, with Holm control over the segments carried forward; the count of
every segment examined is reported (the multiple-testing denominator)."""
from __future__ import annotations
import itertools, json
import numpy as np
import pandas as pd
from alpha_engine.input_research import stats as S
from sift_exec import fees as FE
from . import dists

HORIZONS = ("T-24h", "T-6h", "T-90m")
PRIMARY = "T-6h"
MAX_SPREAD, MAX_AGE = 0.10, 180.0
DISCOVERY_MAX_WEEK = 11
KALSHI_STAT = {"receiving_yards": "rec_yds", "receptions": "receptions", "rushing_yards": "rush_yds", "passing_yards": "pass_yds", "touchdowns": "td_any"}
K2N = {"JAC": "JAX"}


def load_contracts(horizon_files, season="2025") -> pd.DataFrame:
    rows = []
    for p in horizon_files:
        for l in open(p):
            r = json.loads(l)
            if str(r.get("season")) != season or r.get("period") != "FULL" or r.get("result") not in ("yes", "no"):
                continue
            fam = None
            if r["family"] == "GAME_WINNER": fam = "moneyline"
            elif r["family"] == "SPREAD": fam = "spread"
            elif r["family"] == "TOTAL": fam = "total"
            elif r["family"] == "TEAM_TOTAL": fam = "team_total"
            elif r["family"] == "PLAYER_STAT" and r.get("stat") in KALSHI_STAT: fam = KALSHI_STAT[r["stat"]]
            if fam is None:
                continue
            for h in HORIZONS:
                s = (r.get("snaps") or {}).get(h)
                if not s or s.get("bid") is None or s.get("ask") is None or s.get("book_empty"):
                    continue
                rows.append(dict(game_id=r["game_id"], week=int(r["week"]), family=fam, ticker=r["ticker"], team=K2N.get(r.get("team"), r.get("team")), player=r.get("player_name"),
                                 floor=(r.get("floor_strike") if r.get("floor_strike") is not None else (float(r["threshold"]) - 0.5 if r.get("threshold") is not None else None)), threshold=r.get("threshold"), outcome=1.0 if r["result"] == "yes" else 0.0, horizon=h,
                                 bid=float(s["bid"]), ask=float(s["ask"]), age=float(s.get("age_min") or 0.0), home=r.get("home_team"), away=r.get("away_team")))
    d = pd.DataFrame(rows)
    return d


def valid_quotes(d: pd.DataFrame) -> pd.DataFrame:
    m = (d["ask"] > d["bid"]) & (d["bid"] >= 0.01) & (d["ask"] <= 0.99) & ((d["ask"] - d["bid"]) <= MAX_SPREAD) & (d["age"] <= MAX_AGE)
    return d[m].copy()


def game_probs(d: pd.DataFrame, gp: pd.DataFrame) -> pd.Series:
    """Fair P(YES) for game-level contracts.  gp: columns game_id, target, dist, mu, sigma (2025 rows)."""
    t = gp.set_index(["game_id", "target"])
    out = np.full(len(d), np.nan)
    for i, r in enumerate(d.itertuples(index=False)):
        try:
            if r.family in ("moneyline", "spread"):
                m = t.loc[(r.game_id, "margin")]
                f = 0.5 if r.family == "moneyline" else float(r.floor)
                p_home = dists.prob_gt(m["dist"], m["mu"], m["sigma"], f)               # P(home margin > f)
                if r.team == r.home:
                    out[i] = p_home
                else:                                                                   # away team wins by more than f  <=>  home margin < -f
                    out[i] = 1.0 - dists.prob_gt(m["dist"], m["mu"], m["sigma"], -f)
            elif r.family == "total":
                m = t.loc[(r.game_id, "total")]; out[i] = dists.prob_gt(m["dist"], m["mu"], m["sigma"], float(r.floor))
            elif r.family == "team_total":
                m = t.loc[(r.game_id, "home_pts" if r.team == r.home else "away_pts")]; out[i] = dists.prob_gt(m["dist"], m["mu"], m["sigma"], float(r.floor))
        except KeyError:
            continue
    return pd.Series(out, index=d.index)


def taker_fee(price: float, qty: int = 10) -> float:
    return FE.order_fee(int(round(price * 100)), qty, FE.TAKER_COEF) / qty


def score(d: pd.DataFrame) -> pd.DataFrame:
    """Predictive scores and executable economics for rows with model_p and a valid quote."""
    d = d.copy()
    d["mid"] = (d["bid"] + d["ask"]) / 2
    d["ll_model"] = S.logloss(d["model_p"].to_numpy(), d["outcome"].to_numpy()); d["ll_mkt"] = S.logloss(d["mid"].to_numpy(), d["outcome"].to_numpy())
    d["br_model"] = S.brier(d["model_p"].to_numpy(), d["outcome"].to_numpy()); d["br_mkt"] = S.brier(d["mid"].to_numpy(), d["outcome"].to_numpy())
    fy = np.array([taker_fee(a) for a in d["ask"]]); fn = np.array([taker_fee(1 - b) for b in d["bid"]])
    d["ev_yes"] = d["model_p"] - d["ask"] - fy                       # model-expected net value per contract
    d["ev_no"] = (1 - d["model_p"]) - (1 - d["bid"]) - fn
    d["real_yes"] = d["outcome"] - d["ask"] - fy                     # realised net per contract held to settlement
    d["real_no"] = (1 - d["outcome"]) - (1 - d["bid"]) - fn
    d["side"] = np.where(d["ev_yes"] >= d["ev_no"], "YES", "NO")
    d["pred_ev"] = np.maximum(d["ev_yes"], d["ev_no"])
    d["real"] = np.where(d["side"] == "YES", d["real_yes"], d["real_no"])
    d["price"] = np.where(d["side"] == "YES", d["ask"], 1 - d["bid"])
    d["edge"] = np.where(d["side"] == "YES", d["model_p"] - d["mid"], d["mid"] - d["model_p"])    # model disagreement with the market mid, in probability
    d["fav"] = np.where(d["mid"] >= 0.5, "market_favourite", "market_underdog")
    return d


def clustered(vals: np.ndarray, clusters, n_boot=2000, seed=11):
    v = np.asarray(vals, float)
    if len(v) < 8 or len(set(clusters)) < 4:
        return None
    r = S.ClusterBoot(pd.factorize(pd.Series(clusters))[0], n_boot=n_boot, seed=seed).summarize(v)
    return dict(mean=r["mean"], ci=r["ci_0.05"], p=r["p"], n=r["n"], games=r["n_clusters"])


def predictive_table(d: pd.DataFrame) -> dict:
    """Model vs market-mid log loss / Brier (paired, game-clustered; positive = the MODEL is better) and calibration slopes, per family at the primary horizon."""
    out = {}
    for fam, x in d[d["horizon"] == PRIMARY].groupby("family"):
        g = x["game_id"].to_numpy()
        out[fam] = dict(n=int(len(x)), games=int(x["game_id"].nunique()), logloss_model=float(x["ll_model"].mean()), logloss_market=float(x["ll_mkt"].mean()),
                        logloss_gain=clustered((x["ll_mkt"] - x["ll_model"]).to_numpy(), g), brier_gain=clustered((x["br_mkt"] - x["br_model"]).to_numpy(), g),
                        calibration_slope_model=S.calibration_slope(x["model_p"].to_numpy(), x["outcome"].to_numpy()), calibration_slope_market=S.calibration_slope(x["mid"].to_numpy(), x["outcome"].to_numpy()),
                        mean_model_p=float(x["model_p"].mean()), mean_mid=float(x["mid"].mean()), base_rate=float(x["outcome"].mean()))
    return out


def strategy_table(d: pd.DataFrame, taus=(0.0, 0.02, 0.05, 0.10)) -> dict:
    """'Bet whenever the model expects at least tau net per contract' per family and horizon: n, mean realised net per contract (after fees), game-clustered CI."""
    out = {}
    for (fam, h), x in d.groupby(["family", "horizon"]):
        for tau in taus:
            y = x[x["pred_ev"] > tau]
            c = clustered(y["real"].to_numpy(), y["game_id"].to_numpy()) if len(y) else None
            out[f"{fam}|{h}|tau{tau:g}"] = dict(n=int(len(y)), games=int(y["game_id"].nunique()) if len(y) else 0, mean_pred_ev=float(y["pred_ev"].mean()) if len(y) else None,
                                              mean_real=float(y["real"].mean()) if len(y) else None, ci=c["ci"] if c else None, p=c["p"] if c else None)
    return out


def _bins(d):
    d = d.copy()
    d["b_prob"] = pd.cut(d["model_p"], [0, .1, .25, .5, .75, .9, 1.0], include_lowest=True).astype(str)
    d["b_edge"] = pd.cut(d["edge"], [-1, 0, .03, .06, .10, 1.0]).astype(str)
    d["b_price"] = pd.cut(d["price"], [0, .1, .25, .5, .75, .9, 1.0], include_lowest=True).astype(str)
    d["b_week"] = np.where(d["week"] <= 9, "wk1-9", np.where(d["week"] <= 18, "wk10-18", "post"))
    return d


SEG_DIMS = ["side", "b_prob", "b_edge", "b_price", "fav"]


def segment_search(d: pd.DataFrame, tau=0.0, top_k=5, min_n=60, min_games=15) -> dict:
    """Discovery -> holdout inside 2025 at the PRIMARY horizon.  Segments = family x (1 or 2 dims); bets only where pred_ev > tau.  The top_k by discovery t-stat per family
    (n and games above the floors) go to ONE holdout evaluation; Holm over all carried-forward segments."""
    x = _bins(d[(d["horizon"] == PRIMARY) & (d["pred_ev"] > tau)])
    disc, hold = x[x["week"] <= DISCOVERY_MAX_WEEK], x[x["week"] > DISCOVERY_MAX_WEEK]
    tested, carried = 0, []
    for fam in sorted(x["family"].unique()):
        cands = []
        df, hf = disc[disc["family"] == fam], hold[hold["family"] == fam]
        for k in (1, 2):
            for dims in itertools.combinations(SEG_DIMS, k):
                for key, g in df.groupby(list(dims)):
                    tested += 1
                    if len(g) < min_n or g["game_id"].nunique() < min_games:
                        continue
                    t = g["real"].mean() / (g["real"].std(ddof=1) / np.sqrt(len(g)) + 1e-12)
                    cands.append((t, dims, key if isinstance(key, tuple) else (key,), g))
        cands.sort(key=lambda z: -z[0])
        for t, dims, key, g in cands[:top_k]:
            m = hf
            for dname, v in zip(dims, key):
                m = m[m[dname] == v]
            c = clustered(m["real"].to_numpy(), m["game_id"].to_numpy()) if len(m) >= 10 else None
            carried.append(dict(family=fam, segment=dict(zip(dims, map(str, key))), discovery=dict(n=int(len(g)), games=int(g["game_id"].nunique()), mean=float(g["real"].mean()), t=float(t)),
                                holdout=dict(n=int(len(m)), games=int(m["game_id"].nunique()) if len(m) else 0, mean=float(m["real"].mean()) if len(m) else None,
                                             ci=c["ci"] if c else None, p_one=(c["p"] / 2 if c and c["mean"] > 0 else (1 - c["p"] / 2 if c else None)))))
    ps = {str(i): (r["holdout"]["p_one"] if r["holdout"]["p_one"] is not None else 1.0) for i, r in enumerate(carried)}
    adj = S.holm(ps) if ps else {}
    for i, r in enumerate(carried):
        r["holm_p"] = adj.get(str(i)); r["status"] = ("POSITIVE_HOLDOUT_AFTER_FEES" if (r["holdout"]["ci"] and r["holdout"]["ci"][0] > 0 and r["holm_p"] is not None and r["holm_p"] < 0.05)
                                                      else "NOT_DEMONSTRATED")
    return dict(tau=tau, discovery_weeks=f"<= {DISCOVERY_MAX_WEEK}", holdout_weeks=f"> {DISCOVERY_MAX_WEEK}", segments_examined=tested, segments_carried_forward=len(carried),
                n_positive_after_holm=sum(r["status"] == "POSITIVE_HOLDOUT_AFTER_FEES" for r in carried), carried=carried)
