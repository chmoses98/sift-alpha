"""Experiment NFL-PASSYDS-1: frozen QB passing-yards model vs authentic Kalshi KXNFLPASSYDS quotes (RESEARCH_ONLY, retrospective).

PRE-REGISTERED DESIGN (constants below were fixed before any Kalshi price was read; the model never receives a price):
  Population   every finalized yes/no KXNFLPASSYDS ("player X: k+ passing yards") contract on a 2026 regular-season game found in nflverse.
  Model        ridge on (yards - QB shrunk historical rate) with the strict pregame inputs of qb_passing (no realised-QB/weather inputs), trained on
               2013-2025 only; predictive spread from walk-forward out-of-sample standardized residuals (2017-2025); P(yards > floor_strike).
  Quote        last hourly candle ending <= kickoff - H; executable YES price = yes_ask.close, NO price = 1 - yes_bid.close (taker, one contract at the
               quoted top of book; depth NOT observed -> every fill is HYPOTHETICAL). H=60 min is primary; 3h and 24h are secondary (3 horizons -> Bonferroni).
  Decision     buy the side with the larger (model prob - price - taker fee), only if that net edge >= EDGE_MIN (5 cents). One side per contract, hold to settlement.
  Fees         Kalshi taker fee ceil(0.07*C*p*(1-p)) on a 10-lot (sift_exec.fees), per contract.
  Uncertainty  95% intervals resample GAMES (contracts within a game are strongly dependent).
KNOWN LIMITATION (not removable here): the model exists only for the realised QB1 with >=12 dropbacks, so eligibility uses information not known at the quote time.
Contracts for players who did not meet that bar are counted and shown (exclusion waterfall) but cannot be priced, which flatters YES-side results.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import marketfree as MF
from . import qb_passing as qp
from sift_exec.fees import order_fee

B = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = "KXNFLPASSYDS"
EDGE_MIN = 0.05
HORIZONS_MIN = {"primary_T-60m": 60, "secondary_T-3h": 180, "secondary_T-24h": 1440}
TRAIN_LAST, WF_FIRST = 2025, 2017
MIN_CELL_N, MIN_CELL_GAMES = 30, 10
KALSHI_TO_NFLVERSE = {"JAC": "JAX", "LAR": "LA", "WSH": "WAS"}
ALPHAS = [1, 10, 30, 100, 300, 1000, 3000, 10000]
OUT_DIR = Path(__file__).resolve().parents[2] / "research/audit/input_research/experiments"


def _get(path: str, tries: int = 8):
    for i in range(tries):
        try:
            req = urllib.request.Request(B + path, headers={"User-Agent": "sift-alpha-research/1"})
            return json.load(urllib.request.urlopen(req, timeout=60))
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(2 + 3 * i)
    raise RuntimeError("rate limited: " + path)


def fetch_markets(series: str = SERIES) -> list[dict]:
    rows, cur = [], None
    while True:
        d = _get(f"/markets?series_ticker={series}&limit=1000" + (f"&cursor={cur}" if cur else ""))
        rows += d["markets"]
        cur = d.get("cursor")
        if not cur or not d["markets"]:
            return rows
        time.sleep(0.5)


def fetch_candles(tickers: list[str], start_ts: int, end_ts: int) -> dict[str, list]:
    out = {}
    for i in range(0, len(tickers), 30):
        chunk = tickers[i:i + 30]
        d = _get("/markets/candlesticks?market_tickers=" + ",".join(chunk) + f"&start_ts={start_ts}&end_ts={end_ts}&period_interval=60")
        for m in d["markets"]:
            out[m["market_ticker"]] = m["candlesticks"]
        time.sleep(0.4)
    return out


# ---------------------------------------------------------------- model
def _feat_cols(groups=None):
    """Strict-pregame, MARKET-FREE input columns (no line, price or derived feature; see marketfree.py)."""
    if groups is None:
        from . import search_nfl_qb as SQ
        groups = SQ.GROUPS_CACHE["groups"]
    cols = [c for g in groups.values() for c in g]
    MF.assert_market_free(cols)
    return cols


class Ridge:
    def __init__(self, alpha):
        self.alpha = alpha

    def fit(self, X, y):
        self.med = np.nanmedian(X, axis=0)
        X = np.where(np.isnan(X), self.med, X)
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        Z = (X - self.mu) / self.sd
        self.ym = y.mean()
        self.w = np.linalg.solve(Z.T @ Z + self.alpha * np.eye(Z.shape[1]), Z.T @ (y - self.ym))
        return self

    def predict(self, X):
        X = np.where(np.isnan(X), self.med, X)
        return self.ym + ((X - self.mu) / self.sd) @ self.w


def fit_models(qb: pd.DataFrame, cols: list[str], drop_group: list[str] | None = None):
    """Returns predictor f(df)->(mu, sd) for the 2026 season, plus walk-forward OOS diagnostics. Uses only seasons <= TRAIN_LAST."""
    cols = [c for c in cols if not drop_group or c not in drop_group]
    d = qb[(qb.season >= 2013) & (qb.season <= TRAIN_LAST) & qb.pass_yards.notna() & qb.baseline_ypg.notna()].reset_index(drop=True)
    X, y = d[cols].to_numpy(float), (d.pass_yards - d.baseline_ypg).to_numpy(float)
    # alpha chosen on the last season only, training strictly before it
    tr, va = d.season < TRAIN_LAST, d.season == TRAIN_LAST
    best = min(ALPHAS, key=lambda a: float(np.mean((y[va] - Ridge(a).fit(X[tr], y[tr]).predict(X[va])) ** 2)))
    # walk-forward OOS residuals for the spread model
    mus, ys = [], []
    for s in range(WF_FIRST, TRAIN_LAST + 1):
        m = d.season < s
        t = d.season == s
        r = Ridge(best).fit(X[m], y[m])
        mus.append(d.baseline_ypg[t].to_numpy() + r.predict(X[t])); ys.append(d.pass_yards[t].to_numpy())
    mu_o, y_o = np.concatenate(mus), np.concatenate(ys)
    A = np.vstack([np.ones_like(mu_o), mu_o]).T
    coef = np.linalg.lstsq(A, np.abs(y_o - mu_o) * math.sqrt(math.pi / 2), rcond=None)[0]
    sdf = lambda m: np.maximum(coef[0] + coef[1] * m, 25.0)
    z = np.sort((y_o - mu_o) / sdf(mu_o))
    final = Ridge(best).fit(X, y)

    def predict(df):
        mu = df.baseline_ypg.to_numpy(float) + final.predict(df[cols].to_numpy(float))
        return mu, sdf(mu)

    def p_over(mu, sd, floor):  # P(yards > floor) from the empirical standardized-residual CDF
        t = (floor - mu) / sd
        return 1.0 - np.searchsorted(z, t, side="right") / (len(z) + 1.0)

    diag = {"alpha": best, "n_train": int(len(d)), "n_walkforward_oos": int(len(z)), "sd_fit": [float(coef[0]), float(coef[1])],
            "oos_mse_model": float(np.mean((y_o - mu_o) ** 2)),
            "oos_mse_history_only": float(np.mean((y_o - d.baseline_ypg[d.season >= WF_FIRST].to_numpy()) ** 2))}
    return predict, p_over, diag, dict(zip(cols, final.w.round(4).tolist()))


def history_only(qb: pd.DataFrame):
    d = qb[(qb.season >= WF_FIRST) & (qb.season <= TRAIN_LAST) & qb.pass_yards.notna() & qb.baseline_ypg.notna()]
    r = (d.pass_yards - d.baseline_ypg).to_numpy()
    sd = np.sqrt(np.mean(r ** 2))
    z = np.sort(r / sd)
    return lambda df, floor: 1.0 - np.searchsorted(z, (floor - df.baseline_ypg.to_numpy(float)) / sd, side="right") / (len(z) + 1.0)


# ---------------------------------------------------------------- contracts
def parse_event(e: str):
    m = re.match(rf"{SERIES}-(\d\d)([A-Z]{{3}})(\d\d)([A-Z]+)$", e)
    return dt.datetime.strptime(f"20{m.group(1)}{m.group(2)}{m.group(3)}", "%Y%b%d").date(), m.group(4)


def split_teams(code: str, valid: set[str]):
    """Kalshi event codes concatenate AWAY+HOME with 2- or 3-letter codes (GBTB, JACBAL, KCNE): split on the unique valid pair, else None."""
    out = []
    for i in (2, 3):
        a, h = code[:i], code[i:]
        a, h = KALSHI_TO_NFLVERSE.get(a, a), KALSHI_TO_NFLVERSE.get(h, h)
        if a in valid and h in valid:
            out.append((a, h))
    return out[0] if len(out) == 1 else None


def build_contracts(markets, games, players, qb, candles, horizons=HORIZONS_MIN):
    g26 = games[(games.season == 2026) & (games.game_type == "REG")].copy()
    g26["ko"] = [dt.datetime.strptime(f"{a} {b}", "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("America/New_York")).astimezone(dt.timezone.utc)
                 for a, b in zip(g26.gameday, g26.gametime)]
    valid = set(games.away_team) | set(games.home_team)
    gidx = {(r.gameday, frozenset((r.away_team, r.home_team))): r for r in g26.itertuples()}
    names = {n: gid for gid, n in zip(players.gsis_id, players.display_name) if isinstance(n, str)}
    qbi = qb[qb.season == 2026].set_index(["game_id", "qb_id"])
    rows = []
    for m in markets:
        row = {"ticker": m["ticker"], "event": m["event_ticker"], "status": m["status"], "result": m.get("result")}
        day, code = parse_event(m["event_ticker"])
        pair = split_teams(code, valid)
        gm = gidx.get((str(day), frozenset(pair))) if pair else None
        row["game_id"] = gm.game_id if gm else None
        row["floor"] = m.get("floor_strike")
        row["player"] = m["yes_sub_title"].split(":")[0] if m.get("yes_sub_title") else None
        if gm:
            row["kickoff"] = gm.ko.isoformat()
            row["week"] = int(gm.week)
            row["opened_utc"] = m["open_time"]
        rows.append(row)
    df = pd.DataFrame(rows)
    df["stage"] = "ok"
    df.loc[df.game_id.isna(), "stage"] = "x1_no_regular_season_game_match"
    df.loc[(df.stage == "ok") & ~df.result.isin(["yes", "no"]), "stage"] = "x2_not_settled_yes_no"
    # quotes
    for hn, mins in horizons.items():
        ys, no = [], []
        for t, ko, stg in zip(df.ticker, df.kickoff, df.stage):
            ask = bid = vol = None
            if stg == "ok":
                cut = dt.datetime.fromisoformat(ko).timestamp() - mins * 60
                c = [x for x in candles.get(t, []) if x["end_period_ts"] <= cut and x.get("yes_ask", {}).get("close_dollars") is not None
                     and x.get("yes_bid", {}).get("close_dollars") is not None]
                if c:
                    x = c[-1]
                    ask, bid, vol = float(x["yes_ask"]["close_dollars"]), float(x["yes_bid"]["close_dollars"]), float(x.get("volume_fp") or 0)
            ys.append((ask, bid, vol))
        df[f"ask_{hn}"], df[f"bid_{hn}"], df[f"vol_{hn}"] = zip(*ys)
    pn = df.player.map(names)
    df["qb_id"] = pn
    key = list(zip(df.game_id, df.qb_id))
    df["has_model_row"] = [k in qbi.index for k in key]
    return df, qbi


def fee_c(price: float) -> float:
    return order_fee(int(round(price * 100)), 10, 0.07) / 10.0


def score(df, hn, p_col="p_model", edge_min=EDGE_MIN):
    ask, bid = df[f"ask_{hn}"], df[f"bid_{hn}"]
    yes_ok = ask.notna() & (ask < 1.0) & (ask > 0.0)
    no_ok = bid.notna() & (bid > 0.0) & (bid < 1.0)
    p = df[p_col]
    ey = np.where(yes_ok, p - ask - ask.map(lambda a: fee_c(a) if a == a and 0 < a < 1 else 0), -9)
    en = np.where(no_ok, (1 - p) - (1 - bid) - bid.map(lambda b: fee_c(1 - b) if b == b and 0 < b < 1 else 0), -9)
    side = np.where(ey >= en, "YES", "NO")
    edge = np.maximum(ey, en)
    yes_won = (df.result == "yes").to_numpy()
    price = np.where(side == "YES", ask, 1 - bid)
    won = np.where(side == "YES", yes_won, ~yes_won)
    fee = np.array([fee_c(x) if x == x and 0 < x < 1 else 0 for x in price])
    pnl = np.where(won, 1.0, 0.0) - price - fee
    return pd.DataFrame({"side": side, "edge": edge, "price": price, "won": won, "fee": fee, "pnl": pnl, "qualifies": (edge >= edge_min) & (yes_ok | no_ok)}, index=df.index)


def boot_mean(vals, groups, n=4000, seed=7):
    vals = np.asarray(vals, float)
    g = pd.Series(groups).astype("category").cat.codes.to_numpy()
    k = g.max() + 1
    sums = np.bincount(g, vals, k)
    cnt = np.bincount(g, minlength=k)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, k, (n, k))
    bs = sums[idx].sum(1) / np.maximum(cnt[idx].sum(1), 1)
    return float(vals.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5)), int(k)


def logloss(p, y):
    p = np.clip(p, 0.01, 0.99)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def run(data_dir: Path, cache_dir: Path, refresh: bool = False):
    from . import nfl_features as nf
    cache_dir.mkdir(parents=True, exist_ok=True)
    mf, cf = cache_dir / "passyds_markets.json", cache_dir / "passyds_candles.json"
    markets = json.loads(mf.read_text()) if mf.exists() and not refresh else fetch_markets()
    mf.write_text(json.dumps(markets))
    gm = nf.market_columns(nf.add_matchup_features(nf.build_game_table(data_dir)))
    from . import search_nfl_qb as SQ
    qb, groups = SQ.build_table(data_dir)
    SQ.GROUPS_CACHE["groups"] = groups
    games = pd.read_csv(data_dir / "games.csv")
    players = pd.read_csv(data_dir / "players.csv")
    candles = json.loads(cf.read_text()) if cf.exists() and not refresh else {}
    # candles only for contracts that could be eligible: settled yes/no, matched game, opened before the earliest horizon cut
    pre, _ = build_contracts(markets, games, players, qb, {})
    need = [t for t, k, s, o in zip(pre.ticker, pre.kickoff, pre.stage, pre.opened_utc) if s == "ok"
            and dt.datetime.fromisoformat(o.replace("Z", "+00:00")) < dt.datetime.fromisoformat(k) - dt.timedelta(minutes=60) and t not in candles]
    if need:
        ks = {t: dt.datetime.fromisoformat(k).timestamp() for t, k in zip(pre.ticker, pre.kickoff) if isinstance(k, str)}
        for wk, chunk in pd.Series(need).groupby(pd.Series(need).map(lambda t: int(ks[t] // (86400 * 3)))):
            lo, hi = min(ks[t] for t in chunk), max(ks[t] for t in chunk)
            candles.update(fetch_candles(list(chunk), int(lo - 3 * 86400), int(hi)))
        cf.write_text(json.dumps(candles))
    df, qbi = build_contracts(markets, games, players, qb, candles)
    cols = _feat_cols(groups)
    predict, p_over, diag, weights = fit_models(qb, cols)
    groups_used = groups
    hist_p = history_only(qb)
    q26 = qb[qb.season == 2026].set_index(["game_id", "qb_id"])
    mu = np.full(len(df), np.nan); sd = np.full(len(df), np.nan)
    rows = q26.reindex(list(zip(df.game_id, df.qb_id)))
    ok = df.has_model_row.to_numpy()
    m_, s_ = predict(rows[ok].reset_index(drop=True))
    mu[ok], sd[ok] = m_, s_
    df["mu"], df["sd"] = mu, sd
    fl = df.floor.astype(float).to_numpy()
    df["p_model"] = np.where(ok, p_over(mu, sd, fl), np.nan)
    df["p_history"] = np.nan
    r2 = rows[ok].reset_index(drop=True)
    df.loc[ok, "p_history"] = hist_p(r2, fl[ok])
    df["actual_yards"] = rows["pass_yards"].to_numpy()
    df["p_ridge"] = df["p_model"]
    # PRIMARY independent model = the market-free nested search (search_nfl_qb): OOS predictions for 2019-2025, selected-config forward predictions for 2026.
    sp = pd.read_csv(OUT_DIR / "search_nfl_qb_passing_v1_predictions.csv")
    sp["mu"] = sp.baseline_ypg + sp.resid_pred
    oos = sp[(sp.season <= TRAIN_LAST) & sp.resid_pred.notna() & sp.pass_yards.notna()]
    A = np.vstack([np.ones(len(oos)), oos.mu]).T
    coef = np.linalg.lstsq(A, np.abs(oos.pass_yards - oos.mu).to_numpy() * math.sqrt(math.pi / 2), rcond=None)[0]
    sdf = lambda m: np.maximum(coef[0] + coef[1] * m, 25.0)
    zs = np.sort(((oos.pass_yards - oos.mu) / sdf(oos.mu)).to_numpy())
    fwd = sp[sp.season == 2026].set_index(["game_id", "qb_id"]).mu
    mu_s = pd.Series(list(zip(df.game_id, df.qb_id))).map(lambda k: fwd.get(k, np.nan)).to_numpy(float)
    df["mu_search"] = mu_s
    df["p_model"] = np.where(~np.isnan(mu_s), 1.0 - np.searchsorted(zs, (fl - mu_s) / sdf(mu_s), side="right") / (len(zs) + 1.0), np.nan)
    diag["primary_model"] = "market-free nested search (search_nfl_qb)"; diag["search_oos_n"] = int(len(oos)); diag["search_sd_fit"] = [float(coef[0]), float(coef[1])]
    return df, diag, weights, qb, cols, candles, groups_used


def summarize(df, diag, weights, cols):
    elig = df[(df.stage == "ok")]
    out = {"schema_version": "experiment-nfl-passyds-1.0", "status": "RESEARCH_ONLY", "label": "RETROSPECTIVE_QUOTE_REPLAY_HYPOTHETICAL_FILLS",
           "edge_min": EDGE_MIN, "model": diag, "model_inputs": cols, "ridge_weights_standardized": weights,
           "contracts_listed": int(len(df)), "stage_counts": df.stage.value_counts().to_dict(), "horizons": {}}
    for hn, mins in HORIZONS_MIN.items():
        d = elig.copy()
        quoted = d[f"ask_{hn}"].notna()
        d2 = d[quoted]
        wf = {"settled_regular_season": int(len(d)), "have_quote_at_horizon": int(quoted.sum()),
              "no_quote_yes_rate": float((d[~quoted].result == "yes").mean()) if (~quoted).any() else None, "no_quote_n": int((~quoted).sum()),
              "no_model_row_n": int((~d2.has_model_row).sum()), "no_model_row_yes_rate": float((d2[~d2.has_model_row].result == "yes").mean()) if (~d2.has_model_row).any() else None}
        bq = d2[(d2[f"ask_{hn}"] < 1) & (d2[f"bid_{hn}"] > 0)]
        bmid = (bq[f"ask_{hn}"] + bq[f"bid_{hn}"]) / 2
        by = (bq.result == "yes").astype(float)
        wf["market_bias_check_actual_minus_mid"] = {
            "all_two_sided_quoted": [int(len(bq)), round(float((by - bmid).mean()), 4)],
            "eligible_with_model_row": [int(bq.has_model_row.sum()), round(float((by - bmid)[bq.has_model_row].mean()), 4)],
            "excluded_no_model_row": [int((~bq.has_model_row).sum()), round(float((by - bmid)[~bq.has_model_row].mean()), 4)]}
        e = d2[d2.has_model_row & d2.p_model.notna()].copy()
        wf["eligible_priced"] = int(len(e)); wf["games"] = int(e.game_id.nunique())
        if len(e) == 0:
            out["horizons"][hn] = {"waterfall": wf}; continue
        mid = (e[f"ask_{hn}"] + e[f"bid_{hn}"]) / 2
        two = (e[f"ask_{hn}"] < 1) & (e[f"bid_{hn}"] > 0)
        y = (e.result == "yes").to_numpy().astype(float)
        h = {"waterfall": wf}
        t = two.to_numpy()
        if t.sum() > 30:
            ll = {"model": logloss(e.p_model.to_numpy()[t], y[t]), "fixed_ridge_secondary": logloss(e.p_ridge.to_numpy()[t], y[t]), "history_only": logloss(e.p_history.to_numpy()[t], y[t]), "market_mid": logloss(mid.to_numpy()[t], y[t])}
            br = {"model": (e.p_model.to_numpy()[t] - y[t]) ** 2, "fixed_ridge_secondary": (e.p_ridge.to_numpy()[t] - y[t]) ** 2, "history_only": (e.p_history.to_numpy()[t] - y[t]) ** 2, "market_mid": (mid.to_numpy()[t] - y[t]) ** 2}
            gg = e.game_id.to_numpy()[t]
            h["two_sided_n"] = int(t.sum())
            h["logloss"] = {k: boot_mean(v, gg)[:3] for k, v in ll.items()}
            h["brier"] = {k: boot_mean(v, gg)[:3] for k, v in br.items()}
            h["logloss_gain_model_vs_market"] = boot_mean(ll["market_mid"] - ll["model"], gg)[:3]
            h["logloss_gain_model_vs_history"] = boot_mean(ll["history_only"] - ll["model"], gg)[:3]
            bins = pd.cut(mid[t], [0, .1, .2, .35, .5, .65, .8, .9, 1])
            cal = pd.DataFrame({"b": bins.astype(str).to_numpy(), "mid": mid.to_numpy()[t], "pm": e.p_model.to_numpy()[t], "y": y[t]}).groupby("b").agg(n=("y", "size"), market=("mid", "mean"), model=("pm", "mean"), actual=("y", "mean"))
            h["calibration_by_market_price"] = cal.round(4).reset_index().to_dict("records")
        sc = score(e, hn)
        q = sc[sc.qualifies]
        allm = {"n": int(len(sc))}
        h["decisions"] = {"qualifying_n": int(len(q)), "qualifying_share": float(len(q) / len(sc)),
                          "all_eligible_if_always_buy_best_side": {"n": int(len(sc)), "mean_net_cents": round(float(sc.pnl.mean() * 100), 2),
                                                                     "ci95": [round(v * 100, 2) for v in boot_mean(sc.pnl, e.game_id)[1:3]]}}
        if len(q):
            m_, lo, hi, k = boot_mean(q.pnl, e.loc[q.index, "game_id"])
            h["decisions"].update({"qualifying_games": k, "mean_net_cents": round(m_ * 100, 2), "ci95": [round(lo * 100, 2), round(hi * 100, 2)],
                                   "mean_gross_cents": round(float((q.pnl + q.fee).mean() * 100), 2), "mean_fee_cents": round(float(q.fee.mean() * 100), 2),
                                   "win_rate": round(float(q.won.mean()), 4), "mean_price": round(float(q.price.mean()), 4), "total_net_dollars_1lot": round(float(q.pnl.sum()), 2),
                                   "by_side": {s: {"n": int((q.side == s).sum()), "mean_net_cents": round(float(q[q.side == s].pnl.mean() * 100), 2),
                                                   "win_rate": round(float(q[q.side == s].won.mean()), 4)} for s in ("YES", "NO") if (q.side == s).any()},
                                   "entry_candle_traded_share": round(float((e.loc[q.index, f"vol_{hn}"] > 0).mean()), 3)})
        for thr in (0.0, 0.03, 0.08, 0.12):
            qq = score(e, hn, edge_min=thr); qq = qq[qq.qualifies]
            h.setdefault("edge_threshold_sensitivity", []).append({"edge_min": thr, "n": int(len(qq)), "mean_net_cents": round(float(qq.pnl.mean() * 100), 2) if len(qq) else None})
        # model-vs-market disagreement deciles without any decision rule
        e = e.assign(gap=e.p_model - mid)
        e["gapbin"] = pd.qcut(e.gap, 5, duplicates="drop").astype(str)
        h["outcome_by_model_minus_market_quintile"] = e.groupby("gapbin").agg(n=("gap", "size"), gap=("gap", "mean"), actual_yes=("result", lambda s: (s == "yes").mean())).round(4).reset_index().to_dict("records")
        out["horizons"][hn] = h
    return out


def structure_test(df, hn="primary_T-60m"):
    """Model-free test of a structural price bias (favourite-longshot) on EVERY two-sided quoted contract: no QB1 eligibility filter, so no realised-participation
    bias. Pre-specified cells: price bins of the YES mid x side bought (taker, fee included), held to settlement. 16 cells -> Holm-adjusted one-sided p (H0: net EV = 0,
    simulated exactly). A cell counts only if Holm p < 0.05 AND the game-clustered bootstrap CI is above 0 AND it has >= MIN_CELL_N contracts from >= MIN_CELL_GAMES games."""
    d = df[(df.stage == "ok") & (df[f"ask_{hn}"] < 1) & (df[f"bid_{hn}"] > 0) & (df[f"ask_{hn}"] > 0)].copy()
    d["mid"] = (d[f"ask_{hn}"] + d[f"bid_{hn}"]) / 2
    d["bin"] = pd.cut(d.mid, [0, .1, .2, .35, .5, .65, .8, .9, 1]).astype(str)
    yes = (d.result == "yes").to_numpy()
    cells = []
    for b, g in d.groupby("bin"):
        for side in ("YES", "NO"):
            price = g[f"ask_{hn}"] if side == "YES" else 1 - g[f"bid_{hn}"]
            won = (g.result == "yes") if side == "YES" else (g.result == "no")
            fee = price.map(lambda x: fee_c(x) if 0 < x < 1 else 0)
            pnl = won.astype(float) - price - fee
            m, lo, hi, k = boot_mean(pnl, g.game_id)
            # H0: net EV = 0, i.e. each contract wins with probability price+fee. Exact by simulation, so an all-win cell cannot get a zero-variance p-value.
            be = np.clip((price + fee).to_numpy(float), 0, 1)
            sims = (np.random.default_rng(11).random((20000, len(be))) < be).astype(float) - be
            p1 = float((sims.mean(1) >= float((won.astype(float) - be).mean()) - 1e-12).mean())
            enough = len(g) >= MIN_CELL_N and k >= MIN_CELL_GAMES
            cells.append({"mid_bin": b, "side": side, "n": int(len(g)), "games": k, "mean_net_cents": round(m * 100, 2), "ci95": [round(lo * 100, 2), round(hi * 100, 2)], "p_one_sided": p1, "enough_sample": bool(enough)})
    order = sorted(range(len(cells)), key=lambda i: cells[i]["p_one_sided"])
    m_ = len(cells)   # Holm over all 16 pre-specified cells, including the under-sampled ones
    run = 0.0
    for r, i in enumerate(order):
        run = max(run, min(1.0, cells[i]["p_one_sided"] * (m_ - r)))
        cells[i]["holm_p"] = round(run, 4)
        cells[i]["p_one_sided"] = round(cells[i]["p_one_sided"], 4)
    cal = d.groupby("bin").agg(n=("mid", "size"), mid=("mid", "mean")).join(d.assign(y=yes).groupby("bin").y.mean().rename("actual")).round(4).reset_index()
    return {"n_contracts": int(len(d)), "games": int(d.game_id.nunique()), "cells": cells, "calibration": cal.to_dict("records"),
            "min_cell": [MIN_CELL_N, MIN_CELL_GAMES],
            "cells_passing_all_gates": int(sum(c["holm_p"] < 0.05 and c["ci95"][0] > 0 and c["enough_sample"] for c in cells))}


def drift_test(df, move_min=0.05):
    """Model-free 'slow incorporation' test. Contracts with a two-sided quote at BOTH T-24h and T-3h. Signal = mid(T-3h) - mid(T-24h). If |signal| >= move_min, MOMENTUM buys
    the direction of the move at T-60m (YES at the ask after an up-move, NO at 1-bid after a down-move); FADE buys the opposite side. Taker fees. Holm over the two rules,
    exact H0 simulation (win prob = price + fee), game-clustered bootstrap. Quotes from candles that ended before each horizon only."""
    a, b, c = "secondary_T-24h", "secondary_T-3h", "primary_T-60m"
    ok = df.stage == "ok"
    for h in (a, b, c):
        ok &= (df[f"ask_{h}"] < 1) & (df[f"bid_{h}"] > 0) & (df[f"ask_{h}"] > 0) & (df[f"bid_{h}"] < 1)
    d = df[ok].copy()
    sig = (d[f"ask_{b}"] + d[f"bid_{b}"]) / 2 - (d[f"ask_{a}"] + d[f"bid_{a}"]) / 2
    qs = {str(q): round(float(sig.abs().quantile(q)), 4) for q in (0.5, 0.75, 0.9, 0.99)}
    d = d[sig.abs() >= move_min]
    sig = sig[d.index]
    out = {"move_min": move_min, "two_sided_at_all_three_horizons": int(ok.sum()), "with_move": int(len(d)), "games": int(d.game_id.nunique()), "abs_move_quantiles": qs,
           "enough_sample": bool(len(d) >= MIN_CELL_N and d.game_id.nunique() >= MIN_CELL_GAMES), "rules": {}}
    pv = {}
    for name, flip in (("momentum", 1), ("fade", -1)):
        up = (sig * flip) > 0
        price = np.where(up, d[f"ask_{c}"], 1 - d[f"bid_{c}"])
        won = np.where(up, d.result == "yes", d.result == "no")
        fee = np.array([fee_c(x) for x in price])
        pnl = won.astype(float) - price - fee
        be = np.clip(price + fee, 0, 1)
        sims = (np.random.default_rng(13).random((20000, len(be))) < be).astype(float) - be
        p1 = float((sims.mean(1) >= float((won.astype(float) - be).mean()) - 1e-12).mean())
        m, lo, hi, k = boot_mean(pnl, d.game_id)
        out["rules"][name] = {"n": int(len(pnl)), "games": k, "mean_net_cents": round(m * 100, 2), "ci95": [round(lo * 100, 2), round(hi * 100, 2)], "win_rate": round(float(won.mean()), 4), "p_one_sided": p1}
    ps = sorted(out["rules"].items(), key=lambda kv: kv[1]["p_one_sided"])
    run = 0.0
    for r, (k, v) in enumerate(ps):
        run = max(run, min(1.0, v["p_one_sided"] * (2 - r)))
        out["rules"][k]["holm_p"] = round(run, 4); out["rules"][k]["p_one_sided"] = round(v["p_one_sided"], 4)
    return out


def ablate(df, qb, cols, groups, hn="primary_T-60m"):
    """Descriptive group-drop ablation on the eligible contracts: refit WITHOUT each input group (training <=2025 only), log-loss change on the same contracts.
    Exploratory: 12 groups -> not multiplicity-controlled, small independent sample (games), no promotion."""
    e = df[(df.stage == "ok") & df.has_model_row & df.p_model.notna() & (df[f"ask_{hn}"] < 1) & (df[f"bid_{hn}"] > 0)].reset_index(drop=True)
    q26 = qb[qb.season == 2026].set_index(["game_id", "qb_id"])
    rows = q26.reindex(list(zip(e.game_id, e.qb_id))).reset_index(drop=True)
    y = (e.result == "yes").to_numpy(float)
    fl = e.floor.astype(float).to_numpy()
    # ablation refits the FIXED ridge (not the full search) without each group and compares with the fixed ridge on the same contracts
    e = e[e.p_ridge.notna()].reset_index(drop=True)
    rows = q26.reindex(list(zip(e.game_id, e.qb_id))).reset_index(drop=True)
    y = (e.result == "yes").to_numpy(float); fl = e.floor.astype(float).to_numpy()
    base = logloss(e.p_ridge.to_numpy(), y)
    out = []
    for gname, gcols in groups.items():
        gc = [c for c in gcols if c in cols]
        if not gc:
            continue
        predict, p_over, _, _ = fit_models(qb, cols, drop_group=gc)
        mu, sd = predict(rows)
        ll = logloss(p_over(mu, sd, fl), y)
        d, lo, hi, k = boot_mean(ll - base, e.game_id)
        out.append({"group": gname, "inputs": gc, "logloss_increase_when_dropped": round(d, 5), "ci95": [round(lo, 5), round(hi, 5)], "games": k})
    return sorted(out, key=lambda r: -r["logloss_increase_when_dropped"])


def main():
    from .phase import assert_predictive_allowed; assert_predictive_allowed('prop_experiment')
    import argparse, sys
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True); ap.add_argument("--cache-dir", required=True); ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    df, diag, weights, qb, cols, _, groups = run(Path(a.data_dir), Path(a.cache_dir), a.refresh)
    res = summarize(df, diag, weights, cols)
    res["group_ablation_primary_T-60m_exploratory"] = ablate(df, qb, cols, groups)
    res["structure_test_primary_T-60m"] = structure_test(df)
    res["drift_test_T-24h_to_T-3h_entry_T-60m"] = drift_test(df)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    keep = ["ticker", "game_id", "week", "player", "floor", "result", "kickoff", "stage", "has_model_row", "mu", "sd", "p_model", "p_ridge", "p_history", "actual_yards"] + [f"{p}_{h}" for h in HORIZONS_MIN for p in ("ask", "bid", "vol")]
    res["data_vintage"] = {"markets_listed_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "latest_completed_game": str(qb[qb.pass_yards.notna()].gameday.max())}
    (OUT_DIR / "nfl_passyds_kalshi_v1.json").write_text(json.dumps(res, indent=1, default=float))
    df[df.stage == "ok"][keep].round(4).to_csv(OUT_DIR / "nfl_passyds_kalshi_v1_contracts.csv", index=False)
    print(json.dumps(res["stage_counts"]), json.dumps(res["model"]))
    for hn, h in res["horizons"].items():
        print(hn, json.dumps(h.get("waterfall")), json.dumps(h.get("decisions")))


if __name__ == "__main__":
    main()
