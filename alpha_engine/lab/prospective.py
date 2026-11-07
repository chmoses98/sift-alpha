"""Prospective (forward-only) evaluation of the FROZEN independent NFL totals model (RESEARCH_ONLY; no orders; no market input to the model).

Protocol (pre-registered in research/prospective/nfl_totals_v1/FREEZE.json before any 2026 game it covers):
  * model:   frozen config below, coefficients fitted on seasons <= 2025 only (season-level walk-forward: 2026 games never enter the fit); in-season information enters only through
             the rolling team ratings (state as of the last strictly earlier game) -- no weekly refitting, no tuning.
  * inputs:  strict point-in-time (roof known; no realised starter, no observed weather).
  * records: append-only, hash-chained JSONL.  A prediction counts only if `generated_utc` is BEFORE the decision time of the quote it is scored against.
  * decision: the book as of kickoff-6h (primary; also kickoff-90min and kickoff-24h, secondary) = the last quote row for the contract at or before the decision time, accepted only if the
             series was observed COMPLETE (collector manifest) no more than 30 min before the decision time.  Freshness is the age of that observation, not of the row.
  * scoring: fair P(total >= k) from (mu, sigma); executable price = ask for YES / 1-bid for NO; Kalshi taker fee; held to settlement; game-clustered bootstrap.
  * unit of analysis = the GAME (one net-EV number per game: mean over that game's selected contracts), never the contract: ladders of thresholds on one game are not independent.
  * primary hypothesis (one-sided, T-6h): mean per-game net EV > 0 over contracts whose model expected net EV exceeds TAU.  Secondary: per-game log-loss gain over the market mid > 0.
  * claim gate (`claim_gate`): >= MIN_GAMES independent games with bets AND scored, Holm over {primary, secondary}, Bonferroni over the pre-registered looks LOOKS, positive lower bound of the
    one-sided 95% interval on the primary, chains verified, and no data-quality flags.  Output is PASS_PROVISIONAL / FAIL / INSUFFICIENT_N, never "profitable"; interim output is descriptive."""
from __future__ import annotations
import hashlib, json, os, time, urllib.request
from pathlib import Path
import numpy as np
import pandas as pd
from . import dists, market as MK, recover as RV

MIN_GAMES = 60
LOOKS = (60, 120, 272)
ALPHA = 0.05
TAU = 0.02
PRIMARY_AGE_MIN = 30
SOURCE_CAPTURE = "market-data/kalshi/capture"
SOURCE_SELF = "legacy_unverified"      # the first 266 quotes (single timestamp, completeness not verified): never used for decisions
SOURCE_FALLBACK = "fallback_fail_closed"   # public REST book fetched by `capture`: accepted only as a COMPLETE book (every page fetched), observed at its last page time
FROZEN = {"model": "ridge", "dist": "normal", "target": "total", "groups": ["strength", "explosive", "schedule", "environment_dome"],
          "rating": {"half_life": 4, "carry": 0.4, "adjust": True}, "fit_seasons": "<=2025", "first_test": 2014}
KALSHI = "https://api.elections.kalshi.com/trade-api/v2/markets"


def config_id(cfg: dict = FROZEN) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]


# ------------------------------------------------------------------ hash chain
def _h(rec: dict) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in rec.items() if k != "hash"}, sort_keys=True, default=str).encode()).hexdigest()


_TAIL: dict = {}


def _tail_hash(path: Path) -> str:
    """Hash of the last record, read from the end of the file (O(1) per append); cached per path and re-validated against file size."""
    path = Path(path)
    if not path.exists() or not path.stat().st_size:
        return ""
    size = path.stat().st_size
    c = _TAIL.get(str(path))
    if c and c[0] == size:
        return c[1]
    with open(path, "rb") as f:
        f.seek(max(0, size - 65536)); last = f.read().decode().strip().splitlines()[-1]
    h = json.loads(last)["hash"]; _TAIL[str(path)] = (size, h)
    return h


def append(path: Path, rec: dict) -> dict:
    """Chained append, safe against concurrent writers (exclusive flock around read-tail + write)."""
    import fcntl
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            prev = _tail_hash(path)
            rec = dict(rec, prev=prev); rec["hash"] = _h(rec)
            f.write((json.dumps(rec, sort_keys=True, default=str) + "\n").encode()); f.flush()
            _TAIL[str(path)] = (path.stat().st_size, rec["hash"])
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
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
    last: dict = {}
    if Path(path).exists():
        for l in Path(path).read_text().splitlines():
            r = json.loads(l); last[r["game_id"]] = r
    g = games.set_index("game_id")
    n = 0
    for r in P[P["season"] == 2026].itertuples():
        if r.game_id not in g.index or np.isnan(r.mu):
            continue
        if r.game_id in last and abs(last[r.game_id]["mu"] - float(r.mu)) < 1e-9:
            continue                                                       # unchanged: no duplicate record
        row = g.loc[r.game_id]
        ko = kickoff_utc(type("G", (), {"gameday": row["gameday"], "gametime": row["gametime"]}))
        if ko <= now:
            continue
        append(path, {"kind": "prediction", "game_id": r.game_id, "week": int(r.week), "away": row["away_team"], "home": row["home_team"], "kickoff_utc": ko.isoformat(),
                      "dist": "normal", "mu": float(r.mu), "sigma": float(r.sigma), "mu_climatology": float(r.mu0), "config_id": config_id(), "data_sha": data_sha, "generated_utc": now.isoformat()})
        n += 1
    return n


# ------------------------------------------------------------------ quotes: fallback capture (fail closed)
class FetchError(RuntimeError):
    pass


def _get_json(url: str, tries: int, pause: float, opener=urllib.request.urlopen):
    """GET -> (parsed json, sha256 of the RAW response bytes, raw length).  The raw hash is stored with every page so the stored fields stay verifiable against what the exchange sent."""
    last = None
    for a in range(tries):
        try:
            with opener(urllib.request.Request(url, headers={"User-Agent": "sift-alpha-research"}), timeout=30) as r:
                raw = r.read()
            return json.loads(raw), hashlib.sha256(raw).hexdigest(), len(raw)
        except Exception as e:                          # network error, HTTP error (incl. 429), bad JSON
            last = e; time.sleep(pause * 2 ** a)
    raise FetchError(f"GET failed after {tries} tries: {url}: {last!r}")


def fetch_totals(base: str = KALSHI, series: str = "KXNFLTOTAL", pause: float = 1.0, tries: int = 4, max_pages: int = 20, clock=None, allow_empty: bool = False, status: str = "open", extra: str = "") -> dict:
    """Full paginated book for one series.  FAIL CLOSED: any page failing after retries, a repeated cursor, running past max_pages, or an empty result raises FetchError -- a partial or empty
    book is never returned.  Every page carries its own fetched-at timestamp (taken after the response arrives)."""
    clock = clock or (lambda: pd.Timestamp.now(tz="UTC"))
    pages, cursor, seen = [], None, set()
    for _ in range(max_pages):
        d, raw_sha, raw_len = _get_json(f"{base}?series_ticker={series}&status={status}&limit=200" + (f"&cursor={cursor}" if cursor else "") + extra, tries, pause)
        pages.append({"fetched_utc": clock().isoformat(), "raw_sha256": raw_sha, "raw_bytes": raw_len, "markets": d.get("markets", [])})
        cursor = d.get("cursor")
        if not cursor:
            break
        if cursor in seen:
            raise FetchError("pagination cursor repeated")
        seen.add(cursor); time.sleep(pause)
    else:
        raise FetchError(f"pagination did not finish within {max_pages} pages")
    n = sum(len(p["markets"]) for p in pages)
    if n == 0 and not allow_empty:
        raise FetchError("empty book")
    return {"series": series, "pages": pages, "n": n, "complete": True}


_LAST: dict = {}


def _last_state(out_dir: Path) -> dict:
    """ticker -> (bid, ask, status) of the last quote row already in the ledger (read once per process, then kept in step with appends)."""
    k = str(Path(out_dir) / "quotes.jsonl")
    if k not in _LAST:
        st = {}
        f = Path(out_dir) / "quotes.jsonl"
        if f.exists():
            for l in f.read_text().splitlines():
                r = json.loads(l)
                if r.get("source") == SOURCE_FALLBACK:
                    st[r["ticker"]] = (r["bid"], r["ask"], r.get("status"), r.get("bid_size"), r.get("ask_size"), r.get("last_price"))
        _LAST[k] = st
    return _LAST[k]


def record_quotes(book: dict, games: pd.DataFrame, out_dir: Path, run_id: str | None = None) -> int:
    """Append a COMPLETE fallback book: one `series_observation` (observed_at = the LAST page's fetched time, so every quote was already known then) and a `quote` row for every usable market
    whose bid/ask/status CHANGED since its last recorded row (same convention as the verified collector: an unchanged contract is covered by the observation, so volume stays bounded).
    Each quote carries its own page time.  Quotes without a verifiable bid and ask, or that cannot be tied to a game, are skipped (counted in the observation), never repaired."""
    out_dir = Path(out_dir); idx = RV.games_index(games); n = skipped = unchanged = no_quote = 0; rows = []; last = _last_state(out_dir); unmapped: dict = {}
    for pg in book["pages"]:
        for m in pg["markets"]:
            rec = {"ticker": m["ticker"], "game_id": None}
            RV.fill(rec, idx)
            if rec["game_id"] is None:                                  # cannot be tied to a game (e.g. an unknown team-code alias): VISIBLE, never silent
                skipped += 1; unmapped[m.get("event_ticker") or m["ticker"]] = unmapped.get(m.get("event_ticker") or m["ticker"], 0) + 1; continue
            if m.get("yes_bid_dollars") is None or m.get("yes_ask_dollars") is None:
                skipped += 1; no_quote += 1; continue
            key = (float(m["yes_bid_dollars"]), float(m["yes_ask_dollars"]), m.get("status"), m.get("yes_bid_size_fp"), m.get("yes_ask_size_fp"), m.get("last_price_dollars"))
            if last.get(m["ticker"]) == key:
                unchanged += 1; continue
            row = {"kind": "quote", "source": SOURCE_FALLBACK, "observed_at": pg["fetched_utc"], "ticker": m["ticker"], "game_id": rec["game_id"], "floor": m.get("floor_strike"),
                   "bid": key[0], "ask": key[1], "status": m.get("status"), "result": m.get("result") or "", "series": book["series"], "page_raw_sha256": pg.get("raw_sha256")}
            for src, dst in (("yes_bid_size_fp", "bid_size"), ("yes_ask_size_fp", "ask_size"), ("no_bid_dollars", "no_bid"), ("no_ask_dollars", "no_ask"), ("last_price_dollars", "last_price"),
                             ("volume_fp", "volume"), ("open_interest_fp", "open_interest"), ("close_time", "close_time"), ("updated_time", "exchange_updated_time"), ("static_sha", "static_sha")):
                if m.get(src) is not None:
                    row[dst] = m[src]
            rows.append((row, key))
    last_t = book["pages"][-1]["fetched_utc"]
    append(out_dir / "observations.jsonl", {"kind": "series_observation", "source": SOURCE_FALLBACK, "run_id": run_id or ("fb-" + book["series"] + "-" + last_t), "series": book["series"], "observed_at": last_t, "complete": True,
                                            "n": book["n"], "pages": len(book["pages"]), "tier": "PUBLIC_REST", "skipped_markets": skipped, "no_quote_markets": no_quote, "unmapped_markets": sum(unmapped.values()),
                                            "unmapped_events": sorted(unmapped)[:25], "unchanged_rows_not_rewritten": unchanged})
    for r, key in rows:
        append(out_dir / "quotes.jsonl", r); last[r["ticker"]] = key; n += 1
    return n


def record_failure(out_dir: Path, err: Exception, now=None) -> None:
    append(Path(out_dir) / "capture_failures.jsonl", {"kind": "capture_failure", "at": (now or pd.Timestamp.now(tz="UTC")).isoformat(), "error": repr(err)[:300]})


# ------------------------------------------------------------------ decision engine
HORIZONS_MIN = {"T-24h": 24 * 60, "T-6h": 6 * 60, "T-90m": 90}
REASONS = ("NO_PREDICTION_BEFORE_DECISION", "NO_COMPLETE_OBSERVATION_IN_WINDOW", "NO_QUOTE_ROW", "NOT_YET_DUE", "UNSETTLED", "ELIGIBLE")


def _ts(x) -> pd.Timestamp:
    return pd.Timestamp(x).tz_convert("UTC") if pd.Timestamp(x).tzinfo else pd.Timestamp(x, tz="UTC")


def _index(preds: list[dict], quotes: list[dict], obs: list[dict]):
    byg: dict = {}
    for p in preds:
        byg.setdefault(p["game_id"], []).append(p)
    for v in byg.values():
        v.sort(key=lambda p: p["generated_utc"])
    qt: dict = {}
    for q in quotes:
        if q.get("source", SOURCE_SELF) == SOURCE_SELF or q.get("series") != "KXNFLTOTAL":
            continue                                            # legacy unverified quotes never count; the shared ledger also holds player-prop series, which are not totals
        qt.setdefault(q["ticker"], []).append(q)
    for v in qt.values():
        v.sort(key=lambda q: q["observed_at"])
    ob = sorted((o for o in obs if o.get("complete") and o.get("series") == "KXNFLTOTAL"), key=lambda o: o["observed_at"])
    return byg, qt, ob


def audit_and_frame(preds, quotes, obs, games: pd.DataFrame, now, tickers_by_game: dict | None = None, exchange_results: dict | None = None):
    """Returns (frame, audit).  audit = one row per (game, horizon) with a reason code; frame = one row per (ticker, horizon) that is ELIGIBLE (prediction, complete fresh observation and a quote row exist),
    with the realised outcome when the game has finished."""
    byg, qt, ob = _index(preds, quotes, obs)
    ob_t = [_ts(o["observed_at"]) for o in ob]
    g = games.set_index("game_id")
    by_game_tickers: dict = {}
    for tk, rows in qt.items():
        by_game_tickers.setdefault(rows[-1]["game_id"], []).append(tk)
    now = _ts(now); rows, audit = [], []
    for gid, plist in byg.items():
        ko = _ts(plist[0]["kickoff_utc"])
        for h, mins in HORIZONS_MIN.items():
            dt = ko - pd.Timedelta(minutes=mins); a = {"game_id": gid, "horizon": h, "decision_utc": dt.isoformat(), "kickoff_utc": ko.isoformat()}
            if dt > now:
                audit.append({**a, "status": "NOT_YET_DUE"}); continue
            usable = [p for p in plist if _ts(p["generated_utc"]) <= dt]
            if not usable:
                audit.append({**a, "status": "NO_PREDICTION_BEFORE_DECISION"}); continue
            p = usable[-1]
            k = max([i for i, t in enumerate(ob_t) if t <= dt], default=None)
            if k is None or (dt - ob_t[k]).total_seconds() / 60 > PRIMARY_AGE_MIN:
                audit.append({**a, "status": "NO_COMPLETE_OBSERVATION_IN_WINDOW", "last_complete_obs_utc": ob_t[k].isoformat() if k is not None else None}); continue
            age = (dt - ob_t[k]).total_seconds() / 60
            got = 0; mismatched = []
            for tk in by_game_tickers.get(gid, []):
                cand = [q for q in qt[tk] if _ts(q["observed_at"]) <= ob_t[k]]
                if not cand:
                    continue
                q = cand[-1]
                if q.get("status") not in (None, "active") or q.get("result") not in (None, ""):
                    continue
                fin = g.loc[gid] if gid in g.index else None
                settled = fin is not None and not pd.isna(fin["home_score"])
                outcome = float(fin["home_score"] + fin["away_score"] > q["floor"]) if settled and q["floor"] is not None else np.nan
                xr = (exchange_results or {}).get(tk)
                if settled and xr is not None and not np.isnan(outcome) and (xr["result"] == "yes") != bool(outcome):
                    mismatched.append(tk); continue                      # exchange and nflverse disagree about the outcome: never an eligible decision
                rows.append({"game_id": gid, "week": p["week"], "family": "total", "ticker": tk, "horizon": h, "floor": q["floor"], "bid": q["bid"], "ask": q["ask"], "age": age, "outcome": outcome,
                             "model_p": float(dists.prob_gt(p["dist"], p["mu"], p["sigma"], q["floor"])), "prediction_generated_utc": p["generated_utc"], "obs_utc": ob_t[k].isoformat(), "exchange_result": None if xr is None else xr["result"],
                             "settlement_verified": bool(xr is not None), "exchange_updated_utc": q.get("exchange_updated_time"), "bid_size": q.get("bid_size"), "ask_size": q.get("ask_size")}); got += 1
            if got == 0 and mismatched:
                audit.append({**a, "status": "SETTLEMENT_MISMATCH", "tickers": len(mismatched)}); continue
            if got == 0:
                audit.append({**a, "status": "NO_QUOTE_ROW"}); continue
            fin = g.loc[gid] if gid in g.index else None
            audit.append({**a, "status": "ELIGIBLE" if (fin is not None and not pd.isna(fin["home_score"])) else "UNSETTLED", "tickers": got, "age_min": round(age, 2)})
    return pd.DataFrame(rows), audit


def accounting(games: pd.DataFrame, audit: list[dict], frozen_utc, season: int = 2026) -> dict:
    """Every game of the season must be accounted for at every horizon: audited (any status), or kicked off before the freeze (never eligible).  `unaccounted` must be empty."""
    fz = _ts(frozen_utc); seen = {(a["game_id"], a["horizon"]) for a in audit}
    g = games[(games["season"] == season) & games["gametime"].notna()]
    pre, unacc, n = [], [], 0
    for r in g.itertuples():
        ko = kickoff_utc(r)
        for h in HORIZONS_MIN:
            n += 1
            if ko - pd.Timedelta(minutes=HORIZONS_MIN[h]) < fz and (r.game_id, h) not in seen:
                pre.append((r.game_id, h)); continue                      # the decision time was before the freeze: structurally ineligible
            if (r.game_id, h) not in seen:
                unacc.append(f"{r.game_id}:{h}")
    return {"game_horizons": n, "ineligible_decision_before_freeze": len(pre), "audited": len(seen), "unaccounted": unacc}


def audit_summary(audit: list[dict]) -> dict:
    out: dict = {}
    for a in audit:
        out.setdefault(a["horizon"], {}).setdefault(a["status"], 0)
        out[a["horizon"]][a["status"]] += 1
    return out


# ------------------------------------------------------------------ statistics and the claim gate
def _boot_p_le0(vals: np.ndarray, n_boot: int = 4000, seed: int = 20261107) -> tuple[float, float, float]:
    """One-sided p for H0: mean <= 0 (share of bootstrap means <= 0, +1 smoothing), mean, and the 5th percentile (lower bound of the one-sided 95% interval)."""
    v = np.asarray(vals, float); rng = np.random.default_rng(seed)
    b = v[rng.integers(0, len(v), size=(n_boot, len(v)))].mean(1)
    return float((np.sum(b <= 0) + 1) / (n_boot + 1)), float(v.mean()), float(np.quantile(b, 0.05))


def holm_adjust(p: dict) -> dict:
    items = sorted(p.items(), key=lambda kv: kv[1]); m = len(items); out, run = {}, 0.0
    for i, (k, v) in enumerate(items):
        run = max(run, min(1.0, (m - i) * v)); out[k] = run
    return out


def per_game(x: pd.DataFrame) -> pd.DataFrame:
    sc = MK.score(x)
    sel = sc[sc["pred_ev"] > TAU]
    bets = sel.groupby("game_id")["real"].mean().rename("net")
    gain = (sc["ll_mkt"] - sc["ll_model"]).groupby(sc["game_id"]).mean().rename("ll_gain")
    return pd.concat([gain, bets], axis=1)


def claim_gate(frame: pd.DataFrame, chains_ok: bool, flags: list[str] | None = None) -> dict:
    """The pre-registered claim gate.  Evaluated on T-6h decisions only; unit = game.  Never returns a profitability claim."""
    flags = list(flags or [])
    g = {"horizon": "T-6h", "alpha": ALPHA, "looks": list(LOOKS), "min_games": MIN_GAMES, "flags": flags}
    d = frame[(frame["horizon"] == "T-6h")].dropna(subset=["outcome"]) if not frame.empty else frame
    if not frame.empty:
        d = d[(d["ask"] > d["bid"]) & (d["bid"] >= 0.01) & (d["ask"] <= 0.99) & ((d["ask"] - d["bid"]) <= MK.MAX_SPREAD) & (d["age"] <= PRIMARY_AGE_MIN)]
    if frame.empty or d.empty:
        return {**g, "status": "INSUFFICIENT_N", "games_scored": 0, "games_with_bets": 0, "reason": "no settled eligible decisions"}
    pg = per_game(d)
    n_scored, n_bets = int(pg["ll_gain"].notna().sum()), int(pg["net"].notna().sum())
    g.update({"games_scored": n_scored, "games_with_bets": n_bets, "contracts": int(len(d))})
    reached = [l for l in LOOKS if min(n_scored, n_bets) >= l]
    if not reached:
        return {**g, "status": "INSUFFICIENT_N", "reason": f"need >= {MIN_GAMES} independent games with bets and scored (have {min(n_scored, n_bets)} / {n_scored})"}
    look = max(reached); a_look = ALPHA / len(LOOKS)
    p1, m1, lo1 = _boot_p_le0(pg["net"].dropna().to_numpy())
    p2, m2, lo2 = _boot_p_le0(pg["ll_gain"].dropna().to_numpy())
    adj = holm_adjust({"primary_after_fee_ev": p1, "secondary_logloss_gain": p2})
    g.update({"look": look, "alpha_per_look": a_look, "primary_after_fee_ev": {"mean_per_game": m1, "p_one_sided": p1, "p_holm": adj["primary_after_fee_ev"], "lower_95_one_sided": lo1},
              "secondary_logloss_gain": {"mean_per_game": m2, "p_one_sided": p2, "p_holm": adj["secondary_logloss_gain"], "lower_95_one_sided": lo2}})
    ok = chains_ok and not flags and adj["primary_after_fee_ev"] < a_look and lo1 > 0
    return {**g, "status": "PASS_PROVISIONAL" if ok else "FAIL",
            "note": "PASS_PROVISIONAL means the pre-registered statistical gate was met at this look; it is not a profitability claim and needs independent replication on later games."}


def evaluate(frame: pd.DataFrame, audit: list[dict], chains_ok: bool, flags: list[str] | None = None) -> dict:
    out = {"audit_by_horizon": audit_summary(audit), "gate": claim_gate(frame, chains_ok, flags), "descriptive": {}}
    if frame.empty:
        out["status"] = "NO_DECISIONS_YET"; return out
    d = frame.dropna(subset=["outcome"])
    d = d[(d["ask"] > d["bid"]) & (d["bid"] >= 0.01) & (d["ask"] <= 0.99) & ((d["ask"] - d["bid"]) <= MK.MAX_SPREAD) & (d["age"] <= PRIMARY_AGE_MIN)]
    out["status"] = "OK" if len(d) else "NO_SETTLED_DECISIONS_YET"
    if len(d):
        sc = MK.score(d)
        for h, x in sc.groupby("horizon"):
            out["descriptive"][h] = {"rows": int(len(x)), "games": int(x["game_id"].nunique()), "mean_model_p": float(x["model_p"].mean()), "mean_mid": float(x["mid"].mean()), "base_rate": float(x["outcome"].mean()),
                                     "logloss_model": float(x["ll_model"].mean()), "logloss_market": float(x["ll_mkt"].mean()), "mean_spread": float((x["ask"] - x["bid"]).mean()), "mean_obs_age_min": float(x["age"].mean())}
    return out


# ------------------------------------------------------------------ CLI
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Frozen nfl_totals_v1 prospective experiment (RESEARCH_ONLY)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture", help="FALLBACK fail-closed fetch of the public KXNFLTOTAL book; exits non-zero on any partial/empty result")
    c.add_argument("--games", required=True); c.add_argument("--dir", required=True); c.add_argument("--api", default=KALSHI)
    c.add_argument("--series", default="KXNFLTOTAL", help="comma-separated; only KXNFLTOTAL may not be empty"); c.add_argument("--loop-minutes", type=float, default=0.0); c.add_argument("--interval", type=float, default=300.0)
    i = sub.add_parser("ingest", help="append the verified collector's runs from a market-data clone")
    i.add_argument("--md-repo", required=True); i.add_argument("--dir", required=True)
    y = sub.add_parser("cycle", help="refresh nflverse, append predictions, ingest, evaluate")
    y.add_argument("--data-dir", required=True); y.add_argument("--md-repo", required=True); y.add_argument("--dir", required=True); y.add_argument("--work", required=True); y.add_argument("--no-download", action="store_true"); y.add_argument("--md-ref", default="origin/market-data"); y.add_argument("--player-dir")
    w = sub.add_parser("capture-window", help="kickoff-aware capture: ticks only inside decision windows, writes immutable shards, publishes each tick (new files only)")
    w.add_argument("--stage", required=True); w.add_argument("--repo", required=True); w.add_argument("--span", type=float, default=58.0); w.add_argument("--interval", type=float, default=300.0)
    w.add_argument("--games", help="schedule CSV (default: download the free nflverse schedule)"); w.add_argument("--no-publish", action="store_true"); w.add_argument("--force", action="store_true", help="capture outside decision windows (proof runs); the shard is marked forced")
    r = sub.add_parser("refresh", help="single writer: fetch published state, ingest shards, frozen-model check, predictions, report, append-only publish")
    r.add_argument("--repo", required=True); r.add_argument("--work", required=True); r.add_argument("--data-dir", required=True)
    q = sub.add_parser("publish", help="append-only push of the ledgers to the data branch")
    q.add_argument("--repo", required=True); q.add_argument("--dir", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "capture":
        games = pd.read_csv(a.games); end = time.time() + 60 * a.loop_minutes; fails = 0
        while True:
            t0 = time.time()
            try:
                for ser in a.series.split(","):
                    book = fetch_totals(base=a.api, series=ser, allow_empty=(ser != "KXNFLTOTAL"))      # raises FetchError on any partial/failed result
                    n = record_quotes(book, games, Path(a.dir)); print(f"{ser}: {book['n']} markets, {n} changed rows over {len(book['pages'])} pages", flush=True)
            except FetchError as e:
                fails += 1; record_failure(Path(a.dir), e); print(f"capture FAILED: {e}", flush=True)
                if a.loop_minutes <= 0:
                    raise SystemExit(1)
            if time.time() + a.interval >= end:
                break
            time.sleep(max(0.0, a.interval - (time.time() - t0)))
        if fails and a.loop_minutes > 0:
            print(f"{fails} failed capture(s) recorded in capture_failures.jsonl")
    elif a.cmd == "capture-window":
        from . import capture_window as CW, prospective_cycle as PC
        gp = a.games
        if not gp:
            import urllib.request as U
            gp = str(Path(a.stage) / "_games.csv"); Path(a.stage).mkdir(parents=True, exist_ok=True)
            Path(gp).write_bytes(U.urlopen(U.Request("https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv", headers={"User-Agent": "sift-alpha-research"}), timeout=60).read())
        res = CW.run_window_capture(pd.read_csv(gp), Path(a.stage), span_min=a.span, interval_s=a.interval, run_id=os.environ.get("CAPTURE_RUN_ID", ""), force=a.force,
                                    publish=None if a.no_publish else (lambda st: PC.publish_captures(Path(a.repo), st)))
        print(json.dumps(res, default=str))
        if res["ticks"] and (res["publish_errors"] or res["published"] == 0) and not a.no_publish:
            raise SystemExit(4)
    elif a.cmd == "refresh":
        from . import prospective_cycle as PC
        print(json.dumps(PC.run_refresh(Path(a.repo), Path(a.work), Path(a.data_dir)), indent=1, default=str))
    elif a.cmd == "ingest":
        from . import capture_ingest as CI
        print(json.dumps(CI.ingest(CI.GitSource(Path(a.md_repo)), Path(a.dir)), indent=1))
    elif a.cmd == "cycle":
        from . import prospective_cycle as PC
        r = PC.run_cycle(Path(a.data_dir), Path(a.md_repo), Path(a.dir), Path(a.work), download=not a.no_download, md_ref=a.md_ref)
        print(json.dumps({k: r.get(k) for k in ("cycle_utc", "steps", "counts", "eligible_decision_games", "aborted")}, indent=1, default=str))
        if a.player_dir and Path(a.player_dir, "predictions.jsonl").exists():
            print(json.dumps(PC.run_player_report(Path(a.player_dir), Path(a.dir), Path(a.data_dir)).get("gate"), default=str))
        if r.get("aborted"):
            raise SystemExit(2)
    else:
        from . import prospective_cycle as PC
        r = PC.publish(Path(a.repo), Path(a.dir)); print(json.dumps(r))
        if r.get("error"):
            raise SystemExit(3)


if __name__ == "__main__":
    main()
