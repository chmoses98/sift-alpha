"""Prospective (forward-only) evaluation of the FROZEN independent NFL totals model (RESEARCH_ONLY; no orders; no market input to the model).

Protocol (pre-registered in research/prospective/nfl_totals_v1/FREEZE.json before any 2026 game it covers):
  * model:   frozen config below, coefficients fitted on seasons <= 2025 only (season-level walk-forward: 2026 games never enter the fit); in-season information enters only through
             the rolling team ratings (state as of the last strictly earlier game) -- no weekly refitting, no tuning.
  * inputs:  strict point-in-time (roof known; no realised starter, no observed weather).
  * records: append-only, hash-chained JSONL.  A prediction counts only if `generated_utc` is BEFORE the decision time of the quote it is scored against.
  * decision: primary = last captured two-sided quote at or before kickoff-6h and no more than 30 min older; also kickoff-90min and kickoff-24h (secondary).
  * scoring: fair P(total >= k) from (mu, sigma); executable price = ask for YES / 1-bid for NO; Kalshi taker fee; held to settlement; game-clustered bootstrap.
  * primary hypothesis (one-sided): mean net EV per contract > 0 when model expected net EV > 2c.  Secondary: log-loss gain over the market mid > 0.  Holm over the two.
  * no inference is reported below MIN_GAMES decision games; interim output is descriptive only."""
from __future__ import annotations
import hashlib, json, time, urllib.request
from pathlib import Path
import numpy as np
import pandas as pd
from . import dists, market as MK, recover as RV

MIN_GAMES = 60
TAU = 0.02
PRIMARY_AGE_MIN = 30
FROZEN = {"model": "ridge", "dist": "normal", "target": "total", "groups": ["strength", "explosive", "schedule", "environment_dome"],
          "rating": {"half_life": 4, "carry": 0.4, "adjust": True}, "fit_seasons": "<=2025", "first_test": 2014}
KALSHI = "https://api.elections.kalshi.com/trade-api/v2/markets"


def config_id(cfg: dict = FROZEN) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]


# ------------------------------------------------------------------ hash chain
def _h(rec: dict) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in rec.items() if k != "hash"}, sort_keys=True, default=str).encode()).hexdigest()


def append(path: Path, rec: dict) -> dict:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    prev = ""
    if path.exists() and path.stat().st_size:
        prev = json.loads(path.read_text().strip().splitlines()[-1])["hash"]
    rec = dict(rec, prev=prev); rec["hash"] = _h(rec)
    with open(path, "a") as f:
        f.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
    return rec


def verify_chain(path: Path) -> dict:
    prev, n = "", 0
    for i, l in enumerate(Path(path).read_text().splitlines()):
        r = json.loads(l); n += 1
        if r.get("prev") != prev or _h(r) != r["hash"]:
            return {"ok": False, "first_bad_line": i + 1, "records": n}
        prev = r["hash"]
    return {"ok": True, "records": n}


# ------------------------------------------------------------------ predictions
def kickoff_utc(g) -> pd.Timestamp:
    return pd.Timestamp(f"{g.gameday} {g.gametime}", tz="America/New_York").tz_convert("UTC")


def predict(P: pd.DataFrame, games: pd.DataFrame, now: pd.Timestamp, path: Path, data_sha: str) -> int:
    """P: GameLab.final_predictions(total, FROZEN, last=2026).  Appends one record per not-yet-started 2026 game that has no record yet."""
    have = set()
    if Path(path).exists():
        have = {json.loads(l)["game_id"] for l in Path(path).read_text().splitlines()}
    g = games.set_index("game_id")
    n = 0
    for r in P[P["season"] == 2026].itertuples():
        if r.game_id in have or r.game_id not in g.index or np.isnan(r.mu):
            continue
        row = g.loc[r.game_id]
        ko = kickoff_utc(type("G", (), {"gameday": row["gameday"], "gametime": row["gametime"]}))
        if ko <= now:
            continue
        append(path, {"kind": "prediction", "game_id": r.game_id, "week": int(r.week), "away": row["away_team"], "home": row["home_team"], "kickoff_utc": ko.isoformat(),
                      "dist": "normal", "mu": float(r.mu), "sigma": float(r.sigma), "mu_climatology": float(r.mu0), "config_id": config_id(), "data_sha": data_sha, "generated_utc": now.isoformat()})
        n += 1
    return n


# ------------------------------------------------------------------ quotes
def fetch_totals(limit=1000, pause=1.5, tries=4) -> list[dict]:
    out, cursor = [], None
    while True:
        url = f"{KALSHI}?series_ticker=KXNFLTOTAL&status=open&limit=200" + (f"&cursor={cursor}" if cursor else "")
        for a in range(tries):
            try:
                d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "sift-alpha-research"}), timeout=30))
                break
            except Exception:
                time.sleep(pause * 2 ** a); d = None
        if d is None:
            break
        out += d.get("markets", [])
        cursor = d.get("cursor")
        if not cursor or len(out) >= limit:
            break
        time.sleep(pause)
    return out


def record_quotes(markets: list[dict], games: pd.DataFrame, now: pd.Timestamp, path: Path) -> int:
    idx = RV.games_index(games); n = 0
    for m in markets:
        if m.get("yes_bid_dollars") is None or m.get("yes_ask_dollars") is None:
            continue
        rec = {"ticker": m["ticker"], "game_id": None}
        RV.fill(rec, idx)
        if rec["game_id"] is None:
            continue
        append(path, {"kind": "quote", "captured_utc": now.isoformat(), "ticker": m["ticker"], "game_id": rec["game_id"], "floor": m.get("floor_strike"),
                      "bid": float(m["yes_bid_dollars"]), "ask": float(m["yes_ask_dollars"]), "status": m.get("status")}); n += 1
    return n


# ------------------------------------------------------------------ evaluation
HORIZONS_MIN = {"T-24h": 24 * 60, "T-6h": 6 * 60, "T-90m": 90}


def decision_frame(preds: list[dict], quotes: list[dict], games: pd.DataFrame) -> pd.DataFrame:
    """One row per (ticker, horizon): the last quote captured at/before kickoff-h within PRIMARY_AGE_MIN, scored only if the prediction was generated before that decision time."""
    P = {p["game_id"]: p for p in preds}
    q = pd.DataFrame(quotes)
    if q.empty or not P:
        return pd.DataFrame()
    q["captured"] = pd.to_datetime(q["captured_utc"], utc=True)
    g = games.set_index("game_id")
    rows = []
    for gid, x in q.groupby("game_id"):
        if gid not in P:
            continue
        p = P[gid]; ko = pd.Timestamp(p["kickoff_utc"]); gen = pd.Timestamp(p["generated_utc"])
        for h, mins in HORIZONS_MIN.items():
            dt = ko - pd.Timedelta(minutes=mins)
            if gen > dt:
                continue
            c = x[(x["captured"] <= dt) & (x["captured"] >= dt - pd.Timedelta(minutes=PRIMARY_AGE_MIN))]
            for tk, y in c.groupby("ticker"):
                r = y.sort_values("captured").iloc[-1]
                fin = g.loc[gid]
                if pd.isna(fin["home_score"]) or r["floor"] is None:
                    outcome = np.nan
                else:
                    outcome = float(fin["home_score"] + fin["away_score"] > r["floor"])
                rows.append({"game_id": gid, "week": p["week"], "family": "total", "ticker": tk, "horizon": h, "floor": r["floor"], "bid": r["bid"], "ask": r["ask"],
                             "age": (dt - r["captured"]).total_seconds() / 60, "outcome": outcome, "model_p": float(dists.prob_gt(p["dist"], p["mu"], p["sigma"], r["floor"]))})
    return pd.DataFrame(rows)


def evaluate(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"status": "NO_DECISIONS_YET"}
    d = df.dropna(subset=["outcome"])
    d = d[(d["ask"] > d["bid"]) & (d["bid"] >= 0.01) & (d["ask"] <= 0.99) & ((d["ask"] - d["bid"]) <= MK.MAX_SPREAD)]
    out = {"status": "OK", "decision_rows": int(len(d)), "decision_games": int(d["game_id"].nunique()), "by_horizon": {}}
    if d.empty:
        return {"status": "NO_SETTLED_DECISIONS_YET", "decision_rows": 0}
    sc = MK.score(d)
    for h, x in sc.groupby("horizon"):
        r = {"rows": int(len(x)), "games": int(x["game_id"].nunique()), "mean_model_p": float(x["model_p"].mean()), "mean_mid": float(x["mid"].mean()), "base_rate": float(x["outcome"].mean()),
             "logloss_model": float(x["ll_model"].mean()), "logloss_market": float(x["ll_mkt"].mean())}
        if r["games"] >= MIN_GAMES:
            r["logloss_gain_vs_market"] = MK.clustered((x["ll_mkt"] - x["ll_model"]).to_numpy(), x["game_id"].to_numpy())
            z = x[x["pred_ev"] > TAU]
            r["strategy_tau0.02"] = {"n": int(len(z)), "mean_pred_ev": float(z["pred_ev"].mean()) if len(z) else None, "mean_real_net": MK.clustered(z["real"].to_numpy(), z["game_id"].to_numpy()) if len(z) else None}
        else:
            r["inference"] = f"withheld: fewer than {MIN_GAMES} decision games"
        out["by_horizon"][h] = r
    return out
