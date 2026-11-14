"""Experiment NFL-GAME-1: does the Kalshi KXNFLGAME winner price lag the de-vigged sportsbook moneyline? (RESEARCH_ONLY, retrospective, hypothetical fills)

PRE-REGISTERED (fixed before any Kalshi price was read):
  Population  every finalized yes/no KXNFLGAME contract (one per team per game) on a 2026 regular-season game found in nflverse.
  Benchmark   p_book = de-vigged nflverse schedule-file moneyline for that team. Its timing is DOCUMENTED ONLY AS "near close": it may contain information that arrived after
              the Kalshi quote, which would flatter this test (a look-ahead in the benchmark, not in the Kalshi side). No Kalshi-side information is used to build it.
  Quote/fee   as prop_experiment (last hourly candle ending <= kickoff - H; taker fee on a 10-lot; H = 60 min primary, 24 h secondary).
  Decision    buy YES at the ask if p_book - ask - fee >= 3 cents; buy NO at 1 - bid if (1 - p_book) - (1 - bid) - fee >= 3 cents; else no trade. Hold to settlement.
  Uncertainty game-clustered bootstrap (both contracts of a game together).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import prop_experiment as PE
from .nfl_features import devig

SERIES = "KXNFLGAME"
EDGE_MIN = 0.03
HORIZONS = {"primary_T-60m": 60, "secondary_T-24h": 1440}


def build(markets, games, candles):
    g = games[(games.season == 2026) & (games.game_type == "REG")].copy()
    g["ko"] = [dt.datetime.strptime(f"{a} {b}", "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("America/New_York")).astimezone(dt.timezone.utc) for a, b in zip(g.gameday, g.gametime)]
    valid = set(g.away_team) | set(g.home_team)
    gi = {(r.gameday, frozenset((r.away_team, r.home_team))): r for r in g.itertuples()}
    rows = []
    for m in markets:
        ev = m["event_ticker"]
        mm = __import__("re").match(rf"{SERIES}-(\d\d)([A-Z]{{3}})(\d\d)([A-Z]+)$", ev)
        day = dt.datetime.strptime(f"20{mm.group(1)}{mm.group(2)}{mm.group(3)}", "%Y%b%d").date()
        pair = PE.split_teams(mm.group(4), valid)
        gm = gi.get((str(day), frozenset(pair))) if pair else None
        team = PE.KALSHI_TO_NFLVERSE.get(m["ticker"].rsplit("-", 1)[1], m["ticker"].rsplit("-", 1)[1])
        row = {"ticker": m["ticker"], "game_id": gm.game_id if gm else None, "result": m.get("result"), "team": team, "stage": "ok"}
        if gm is None or team not in (gm.home_team, gm.away_team):
            row["stage"] = "x1_no_game_or_team_match"
        elif m.get("result") not in ("yes", "no"):
            row["stage"] = "x2_not_settled_yes_no"
        elif pd.isna(gm.home_moneyline) or pd.isna(gm.away_moneyline):
            row["stage"] = "x3_no_book_line"
        else:
            ph = float(devig(gm.home_moneyline, gm.away_moneyline)); pa = 1.0 - ph
            row["p_model"] = ph if team == gm.home_team else pa    # column name shared with prop_experiment.score: here the benchmark is the sportsbook
            row["kickoff"] = gm.ko.isoformat(); row["week"] = int(gm.week); row["opened_utc"] = m["open_time"]
        rows.append(row)
    df = pd.DataFrame(rows)
    for hn, mins in HORIZONS.items():
        q = []
        for t, ko, stg in zip(df.ticker, df.get("kickoff", pd.Series([None] * len(df))), df.stage):
            ask = bid = vol = None
            if stg == "ok":
                cut = dt.datetime.fromisoformat(ko).timestamp() - mins * 60
                c = [x for x in candles.get(t, []) if x["end_period_ts"] <= cut and x.get("yes_ask", {}).get("close_dollars") is not None and x.get("yes_bid", {}).get("close_dollars") is not None]
                if c:
                    x = c[-1]; ask, bid, vol = float(x["yes_ask"]["close_dollars"]), float(x["yes_bid"]["close_dollars"]), float(x.get("volume_fp") or 0)
            q.append((ask, bid, vol))
        df[f"ask_{hn}"], df[f"bid_{hn}"], df[f"vol_{hn}"] = zip(*q)
    return df


def summarize(df):
    out = {"schema_version": "experiment-nfl-game-1.0", "status": "RESEARCH_ONLY", "label": "RETROSPECTIVE_QUOTE_REPLAY_HYPOTHETICAL_FILLS", "edge_min": EDGE_MIN,
           "benchmark": "de-vigged nflverse near-close moneyline (timing undocumented; may post-date the Kalshi quote)", "contracts_listed": int(len(df)),
           "stage_counts": df.stage.value_counts().to_dict(), "horizons": {}}
    ok = df[df.stage == "ok"]
    for hn in HORIZONS:
        d = ok[ok[f"ask_{hn}"].notna()]
        d = d[(d[f"ask_{hn}"] < 1) & (d[f"bid_{hn}"] > 0)].copy()
        wf = {"settled_with_book_line": int(len(ok)), "two_sided_quote_at_horizon": int(len(d)), "no_usable_quote": int(len(ok) - len(d)), "games": int(d.game_id.nunique())}
        if len(d) < 30:
            out["horizons"][hn] = {"waterfall": wf}; continue
        mid = ((d[f"ask_{hn}"] + d[f"bid_{hn}"]) / 2).to_numpy(); y = (d.result == "yes").to_numpy(float); pb = d.p_model.to_numpy()
        gg = d.game_id.to_numpy()
        h = {"waterfall": wf, "logloss": {k: PE.boot_mean(PE.logloss(v, y), gg)[:3] for k, v in (("book_devig", pb), ("kalshi_mid", mid))},
             "logloss_gain_book_vs_kalshi_mid": PE.boot_mean(PE.logloss(mid, y) - PE.logloss(pb, y), gg)[:3],
             "mean_kalshi_mid_minus_book_cents": round(float((mid - pb).mean() * 100), 2)}
        sc = PE.score(d, hn, edge_min=EDGE_MIN)
        q = sc[sc.qualifies]
        h["decisions"] = {"qualifying_n": int(len(q)), "of": int(len(sc)),
                          "all_best_side": {"mean_net_cents": round(float(sc.pnl.mean() * 100), 2), "ci95": [round(v * 100, 2) for v in PE.boot_mean(sc.pnl, d.game_id)[1:3]]}}
        if len(q):
            m_, lo, hi, k = PE.boot_mean(q.pnl, d.loc[q.index, "game_id"])
            h["decisions"].update({"games": k, "mean_net_cents": round(m_ * 100, 2), "ci95": [round(lo * 100, 2), round(hi * 100, 2)], "mean_gross_cents": round(float((q.pnl + q.fee).mean() * 100), 2),
                                   "mean_fee_cents": round(float(q.fee.mean() * 100), 2), "win_rate": round(float(q.won.mean()), 4), "mean_price": round(float(q.price.mean()), 4),
                                   "by_side": {s: {"n": int((q.side == s).sum()), "mean_net_cents": round(float(q[q.side == s].pnl.mean() * 100), 2)} for s in ("YES", "NO") if (q.side == s).any()}})
        bins = pd.cut(pd.Series(mid), [0, .2, .4, .6, .8, 1]).astype(str)
        h["calibration"] = pd.DataFrame({"b": bins, "mid": mid, "book": pb, "y": y}).groupby("b").agg(n=("y", "size"), kalshi_mid=("mid", "mean"), book=("book", "mean"), actual=("y", "mean")).round(4).reset_index().to_dict("records")
        out["horizons"][hn] = h
    return out


def main():
    from .phase import assert_predictive_allowed; assert_predictive_allowed('game_experiment')
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--data-dir", required=True); ap.add_argument("--cache-dir", required=True); a = ap.parse_args()
    cache = Path(a.cache_dir); cache.mkdir(parents=True, exist_ok=True)
    mf, cf = cache / "game_markets.json", cache / "game_candles.json"
    markets = json.loads(mf.read_text()) if mf.exists() else PE.fetch_markets(SERIES)
    mf.write_text(json.dumps(markets))
    games = pd.read_csv(Path(a.data_dir) / "games.csv")
    candles = json.loads(cf.read_text()) if cf.exists() else {}
    pre = build(markets, games, {})
    ks = {t: dt.datetime.fromisoformat(k).timestamp() for t, k in zip(pre.ticker, pre.get("kickoff", pd.Series([None] * len(pre)))) if isinstance(k, str)}
    need = [t for t in ks if t not in candles]
    for _, chunk in pd.Series(need).groupby(pd.Series(need).map(lambda t: int(ks[t] // (86400 * 3)))):
        lo, hi = min(ks[t] for t in chunk), max(ks[t] for t in chunk)
        candles.update(PE.fetch_candles(list(chunk), int(lo - 3 * 86400), int(hi)))
    cf.write_text(json.dumps(candles))
    df = build(markets, games, candles)
    res = summarize(df)
    res["data_vintage"] = {"retrieved_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    PE.OUT_DIR.mkdir(parents=True, exist_ok=True)
    (PE.OUT_DIR / "nfl_game_kalshi_v1.json").write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps(res["stage_counts"]))
    for hn, h in res["horizons"].items():
        print(hn, json.dumps({k: h.get(k) for k in ("waterfall", "logloss_gain_book_vs_kalshi_mid", "mean_kalshi_mid_minus_book_cents", "decisions")}))


if __name__ == "__main__":
    main()
