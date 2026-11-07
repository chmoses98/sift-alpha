"""Prospective evaluation of the declared player candidate `v3_listed_emp` -- a SEPARATE experiment from nfl_totals_v1 (RESEARCH_ONLY; no orders; no market price is a model input).

LABEL: MARKET-SELECTED POPULATION.  Two different things are kept apart:
  * inputs      every feature is market-free (usage states, role shares, opponent/team ratings, game-lab predictions, report status, shape pools) -- no price, no line, no consensus
  * population  the set of players scored is the set the exchange chose to LIST.  Listing is selection information produced by the market.  v3 additionally ASSUMES a listed player who is not
                reported Out is involved (P_inv = 1): that assumption is calibrated to this population and must not be read as a market-independent estimate of availability.
Declared model: P(YES) = 1[not reported Out] x P(stat >= k | involved); P(stat >= k | involved) = local-empirical ratio distribution for yardage families (shape chosen on 2022-24 validation) and the
negative binomial / Poisson of the player lab for receptions and any-TD.  Coefficients fitted on seasons <= 2024 (not refit); features advance with 2026 play-by-play.
Evaluation uses the same claim gate as the totals experiment but its OWN multiple-testing family (never pooled with totals); unit = game."""
from __future__ import annotations
import re
import numpy as np
import pandas as pd
from . import dists, identity as IDN, shape as SH, player_lab as PL, player_run as PR, prospective as PP

SERIES = {"KXNFLRECYDS": "rec_yds", "KXNFLREC": "receptions", "KXNFLRSHYDS": "rush_yds", "KXNFLPASSYDS": "pass_yds", "KXNFLANYTD": "td_any"}
YARDAGE = ("rec_yds", "rush_yds", "pass_yds")
LABEL = "MARKET_SELECTED_POPULATION"
PLAYER_COL = {"rec_yds": "rec_yds", "receptions": "rec", "rush_yds": "rush_yds", "pass_yds": "pass_yds", "td_any": "td_any"}
TITLE = re.compile(r"^(?P<name>.+?):\s*(?P<k>\d+)\+")


def contracts_from_book(books: dict, games: pd.DataFrame) -> pd.DataFrame:
    """books: {series: fetch_totals() result}.  One row per listed player contract with a resolvable game and team side (ticker team prefix)."""
    from . import recover as RV
    idx = RV.games_index(games); rows = []
    for series, bk in books.items():
        for pg in bk["pages"]:
            for m in pg["markets"]:
                mt = TITLE.match(m.get("title") or "")
                rec = {"ticker": m["ticker"], "game_id": None}
                RV.fill(rec, idx)
                if not mt or rec.get("game_id") is None or m.get("floor_strike") is None:
                    continue
                rows.append({"ticker": m["ticker"], "game_id": rec["game_id"], "family": SERIES[series], "team": rec.get("team"), "player": mt["name"], "floor": float(m["floor_strike"]),
                             "home": rec["home_team"], "away": rec["away_team"]})
    return pd.DataFrame(rows).drop_duplicates("ticker")


def predict_contracts(u: pd.DataFrame, lab_builder, pools: dict, avail, pg: pd.DataFrame, players: pd.DataFrame, gt: pd.DataFrame, inj: pd.DataFrame, out_lab, season: int = 2026) -> pd.DataFrame:
    """Returns one row per contract with model_p (= v3), p_cond, mu, inj_out and identity reason.  lab_builder(family) -> PlayerLab; out_lab holds the frozen per-family ledgers (selected configs)."""
    u = IDN.resolve(u.assign(season=season), players, pg)
    date = pd.to_datetime(gt.set_index("game_id")["gameday"]); wk = gt.set_index("game_id")["week"]
    ok = u.dropna(subset=["pid"]).copy(); ok = ok[ok["game_id"].isin(date.index)]
    ok["date"] = ok["game_id"].map(date); ok["week"] = ok["game_id"].map(wk).astype(int); ok["home"] = (ok["team"] == ok["home"]).astype(float)
    res = []
    for fam, x in ok.groupby("family"):
        lab = lab_builder(fam); cfg = PR.selected_config(out_lab, fam)
        c = PR.final_player_predictions(lab, fam, cfg, x[["ticker", "pid", "team", "game_id", "season", "week", "date", "home", "floor"]], avail)
        notout = (c["inj_code"].fillna(0.0) != 1.0).astype(float)
        p = c["p_cond"].to_numpy(float)
        if fam in YARDAGE and fam in pools:
            R = SH.local_ratios(pools[fam][0], pools[fam][1], c["mu"].to_numpy(float)); k = c["floor"].to_numpy(float) + 0.5
            hit = (c["mu"].to_numpy(float)[:, None] * R >= (k[:, None] - 0.5)).sum(1); p = (hit + 0.5) / (R.shape[1] + 1.0)
        c["model_p"] = notout * p
        c["inj_out"] = (c["inj_code"].fillna(0.0) == 1.0)
        res.append(c[["ticker", "pid", "model_p", "mu", "p_cond", "inj_out"]])
    out = pd.concat(res) if res else pd.DataFrame(columns=["ticker", "model_p"])
    return u.merge(out, on=["ticker", "pid"], how="left")


def settle(contracts: pd.DataFrame, pg: pd.DataFrame, games: pd.DataFrame) -> dict:
    """ticker -> 1.0/0.0 once the game is final (stat >= threshold; no recorded involvement = stat 0); None while unfinished.  Uses post-game play-by-play only for the OUTCOME."""
    fin = games.set_index("game_id")["home_score"].notna().to_dict()
    key = pg.set_index(["game_id", "pid"])
    out = {}
    for r in contracts.itertuples():
        if not fin.get(r.game_id, False) or not isinstance(r.pid, str):
            out[r.ticker] = None; continue
        col = PLAYER_COL[r.family]
        try:
            stat = float(key.loc[(r.game_id, r.pid), col])
        except KeyError:
            stat = 0.0
        out[r.ticker] = float(stat >= r.floor + 0.5)
    return out


def audit_and_frame(preds: list[dict], quotes: list[dict], obs: list[dict], outcomes: dict, now) -> tuple[pd.DataFrame, list[dict]]:
    """Same decision rules as the totals engine (latest prediction generated before the decision; complete observation of the contract's series within PRIMARY_AGE_MIN; carry-forward of the
    last quote row), one record per (ticker, horizon).  Fallback-book and collector sources are accepted; legacy_unverified never."""
    byt: dict = {}
    for p in preds:
        byt.setdefault(p["ticker"], []).append(p)
    for v in byt.values():
        v.sort(key=lambda p: p["generated_utc"])
    q: dict = {}
    for r in quotes:
        if r.get("source", PP.SOURCE_SELF) != PP.SOURCE_SELF:
            q.setdefault(r["ticker"], []).append(r)
    for v in q.values():
        v.sort(key=lambda r: r["observed_at"])
    ob: dict = {}
    for o in obs:
        if o.get("complete"):
            ob.setdefault(o["series"], []).append(PP._ts(o["observed_at"]))
    for v in ob.values():
        v.sort()
    now = PP._ts(now); rows, audit = [], []
    for tk, plist in byt.items():
        ko = PP._ts(plist[0]["kickoff_utc"]); series = plist[0]["series"]
        for h, mins in PP.HORIZONS_MIN.items():
            dt = ko - pd.Timedelta(minutes=mins); a = {"ticker_hash": hash(tk) & 0xffff, "game_id": plist[0]["game_id"], "horizon": h}
            if dt > now:
                audit.append({**a, "status": "NOT_YET_DUE"}); continue
            use = [p for p in plist if PP._ts(p["generated_utc"]) <= dt]
            if not use:
                audit.append({**a, "status": "NO_PREDICTION_BEFORE_DECISION"}); continue
            o = [t for t in ob.get(series, []) if t <= dt]
            if not o or (dt - o[-1]).total_seconds() / 60 > PP.PRIMARY_AGE_MIN:
                audit.append({**a, "status": "NO_COMPLETE_OBSERVATION_IN_WINDOW"}); continue
            cand = [r for r in q.get(tk, []) if PP._ts(r["observed_at"]) <= o[-1] and r.get("status") in (None, "active") and r.get("result") in (None, "")]
            if not cand:
                audit.append({**a, "status": "NO_QUOTE_ROW"}); continue
            r = cand[-1]; p = use[-1]; y = outcomes.get(tk)
            rows.append({"game_id": p["game_id"], "week": p.get("week", 0), "family": p["family"], "ticker": tk, "horizon": h, "floor": r["floor"], "bid": r["bid"], "ask": r["ask"],
                         "age": (dt - o[-1]).total_seconds() / 60, "outcome": np.nan if y is None else y, "model_p": p["model_p"]})
            audit.append({**a, "status": "ELIGIBLE" if y is not None else "UNSETTLED"})
    return pd.DataFrame(rows), audit


def run_predict(data_dir, work, out_lab, out_dir, gt_path, now: pd.Timestamp, books: dict | None = None, pg_old=None, season: int = 2026) -> dict:
    """Fetch the listed player contracts (fail-closed), build 2026 state, predict, append `contract_prediction` records (only when model_p changed), return counts."""
    from pathlib import Path
    from . import game_lab as GL
    data_dir, work, out_lab, out_dir = Path(data_dir), Path(work), Path(out_lab), Path(out_dir); work.mkdir(parents=True, exist_ok=True)
    games = pd.read_csv(data_dir / "games.csv")
    books = books or {s: PP.fetch_totals(series=s, allow_empty=True) for s in SERIES}      # a series with no listings yet is a valid COMPLETE empty book
    u = contracts_from_book(books, games)
    gt = pd.read_parquet(gt_path); tg = pd.read_parquet(Path(gt_path).with_name("tg.parquet"))
    import json
    rep = json.loads((out_lab / "game_lab_report.json").read_text())["targets"]
    gl = GL.GameLab(gt, tg, work / "_gl.jsonl", work / "cache")
    gpred = pd.concat([gl.final_predictions(t, rep[t]["selected"]["config"], last=season).assign(target=t) for t in ("margin", "total", "home_pts", "away_pts")])
    pbp = PL.load_pbp_players(data_dir / "pbp", range(2010, season + 1)); pg = PL.player_games(pbp); st = PL.build_states(pg)
    players = pd.read_csv(data_dir / "players.csv", low_memory=False)
    inj = PL.injury_status(data_dir / "inj", PR.kickoffs(gt)); ctx = PR.build_game_ctx(gt, gpred); av = PR.Availability(pg)
    builder = lambda fam: PL.PlayerLab(pg, st, ctx, inj, out_lab / f"ledger_player_{fam}.jsonl")
    pools = {}
    for t in YARDAGE:
        lab = builder(t); cfg = PR.selected_config(out_lab, t); f = lab.frame(t)
        X = f[lab.columns(t, cfg["groups"], cfg["hl"])].to_numpy(float); y = f["y"].to_numpy(float); s = f["season"].to_numpy(int)
        mu = np.maximum(lab.wf(X, y, s, list(range(2017, 2025)), cfg["model"]), 0.05); k = ~np.isnan(mu); pools[t] = (mu[k], y[k])
    now_ko = games.set_index("game_id")
    pred = predict_contracts(u, builder, pools, av, pg, players, gt, inj, out_lab, season)
    last = {}
    path = out_dir / "predictions.jsonl"
    if path.exists():
        for l in path.read_text().splitlines():
            r = json.loads(l); last[r["ticker"]] = r
    n = 0
    for r in pred.dropna(subset=["model_p"]).itertuples():
        g = now_ko.loc[r.game_id]; ko = PP.kickoff_utc(type("G", (), {"gameday": g["gameday"], "gametime": g["gametime"]}))
        if ko <= now or (r.ticker in last and abs(last[r.ticker]["model_p"] - float(r.model_p)) < 1e-12):
            continue
        PP.append(path, {"kind": "contract_prediction", "label": LABEL, "experiment": "nfl_player_v3_listed_emp", "ticker": r.ticker, "game_id": r.game_id, "family": r.family,
                         "series": next(s for s, f in SERIES.items() if f == r.family), "kickoff_utc": ko.isoformat(), "generated_utc": now.isoformat(), "model_p": float(r.model_p),
                         "mu": float(r.mu), "p_cond": float(r.p_cond), "inj_out": bool(r.inj_out), "pid": r.pid})
        n += 1
    return {"listed_contracts": int(len(u)), "identity": IDN.report(pred) if len(pred) else {}, "predicted": int(pred["model_p"].notna().sum()), "appended": n, "label": LABEL}
