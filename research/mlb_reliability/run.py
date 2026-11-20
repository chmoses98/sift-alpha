#!/usr/bin/env python3
"""MLB operating-model reliability study (RESEARCH_ONLY; no orders, no recommendations, read-only on source repos).

Stages
  python run.py build     -> contracts_noy.pkl, r0_noy.pkl, coverage.json   (NO outcome data is read)
  python run.py evaluate  -> verifies protocol.json against protocol.sha256, THEN reads official settlements and writes report.json

Sources (all read-only):
  EF = /home/user/edge-finder-api (working tree)
    data/edgelab/games/*.jsonl                         scheduled start (repo game data)
    data/edgelab/observations/*.jsonl.gz               Kalshi top-of-book bid/ask with capturedAt (cents)
    data/kalshi_registry_snapshots/*.json              raw registry snapshots still in the tree (dollars, snapshot_ts) - extra quotes
    data/edgelab/snapshots/*/pre_game_decision/*/      frozen recommendation_output (marketLedger modelProb) + frozen market_observations
    data/pipeline/<date>/recommendations.json          final daily pipeline ledger (meta.createdAt)
    data/edgelab/model_evaluations/*.jsonl.gz          pipeline_recommendations / prospective_snapshot rows (provenance.capturedAt)
    data/kalshi/discovery/<date>.json                  repo adapter fair probabilities for every supported contract (generatedAt)
    data/edgelab/recommendations/*.jsonl.gz            incumbent's archived recommendations (R0)
    data/edgelab/settlements/*.jsonl.gz                repo's own settlement (comparison only)
  VAULT restore of archives/MLB/kalshi_official_settlements/... -> WORK/settle_raw/MLB/<SERIES>.{historical,live}.jsonl (official truth)
"""
import glob, gzip, json, os, sys, hashlib, math, collections
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

WORK = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WORK)
import selection as SEL  # local copy of sift-alpha-ops alpha_engine/pipeline/selection.py (fee_order reimplemented identically)

EF = "/home/user/edge-finder-api"
D = f"{EF}/data"
ET = ZoneInfo("America/New_York")
SERIES_FAMILY = {
    "KXMLBGAME": "game_result", "KXMLBF5": "F5_result", "KXMLBF5TOTAL": "F5_total", "KXMLBF5SPREAD": "F5_margin",
    "KXMLBTOTAL": "game_total", "KXMLBTEAMTOTAL": "team_total", "KXMLBRFI": "RFI", "KXMLBSPREAD": "winning_margin",
    "KXMLBKS": "prop_pitcher_strikeouts", "KXMLBOUTS": "prop_pitcher_outs",
}
MON = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
FILES_USED = collections.Counter()


def ts(s):
    if s is None:
        return None
    s = str(s).replace("Z", "+00:00")
    try:
        t = datetime.fromisoformat(s)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc)


def series_of(ticker):
    return ticker.split("-")[0] if ticker else None


def event_key(ticker):
    p = ticker.split("-") if ticker else []
    return p[1] if len(p) > 1 else None


def ticker_start_et(ek):
    """Kalshi event key e.g. 26SEP101940PITCWS -> scheduled start (ET encoded by Kalshi) as UTC, plus ET game date."""
    try:
        yy, mon, dd, hh, mm = int(ek[0:2]), MON[ek[2:5]], int(ek[5:7]), int(ek[7:9]), int(ek[9:11])
        loc = datetime(2000 + yy, mon, dd, hh, mm, tzinfo=ET)
        return loc.astimezone(timezone.utc), loc.date().isoformat()
    except Exception:
        return None, None


def jl(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def jload(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt") as f:
        return json.load(f)


# ----------------------------------------------------------------------------------------------------------------- schedule
def build_schedule(obs_sched):
    """event_key -> (start_utc, source).  Priority: repo games file (canonical scheduledStartTime) > observation scheduledStart > Kalshi ticker time."""
    rows = [r for f in sorted(glob.glob(f"{D}/edgelab/games/*.jsonl")) for r in jl(f)]
    canon = {str(r["gameId"]): r for r in rows if r.get("scheduledStartTime")}
    by_key = {}
    for r in rows:
        tgt = None
        if r.get("scheduledStartTime"):
            tgt = r
        elif r.get("supersededBy") and str(r["supersededBy"].get("canonicalGameId")) in canon:
            tgt = canon[str(r["supersededBy"]["canonicalGameId"])]
        if tgt is None:
            continue
        st = ts(tgt["scheduledStartTime"])
        gid = str(r["gameId"])
        if "_" in gid:  # string id 2026-08-10_KC_LAD_2210 -> event key built from date+time+teams
            d, a, h, hm = gid.split("_")[:4]
            dt = datetime.fromisoformat(d)
            ek = f"{dt.strftime('%y')}{dt.strftime('%b').upper()}{dt.day:02d}{hm}{a}{h}"
            by_key[ek] = st
        if r.get("kalshiKey") and st:
            loc = st.astimezone(ET)
            ek = f"{loc.strftime('%y')}{loc.strftime('%b').upper()}{loc.day:02d}{loc.strftime('%H%M')}{r['kalshiKey']}"
            by_key.setdefault(ek, st)
    return by_key


def resolve_start(ek, games_sched, obs_sched, stats):
    tk, gdate = ticker_start_et(ek)
    g = games_sched.get(ek)
    o = obs_sched.get(ek)
    # Conservative: the EARLIEST of the available scheduled starts (repo games file, observation scheduledStart, Kalshi ticker ET time),
    # so no entry quote or model value can fall after any recorded first-pitch time (covers rescheduled/postseason TBD-time games).
    cands = [(v, k) for k, v in (("games_file", g), ("observation_scheduledStart", o), ("kalshi_ticker_ET", tk)) if v is not None]
    if not cands:
        stats["source"]["none"] += 1
        return None, gdate, None
    st, src = min(cands)
    if g is not None and st < g:
        stats["earlier_than_games_file"]["n"] += 1
    stats["source"][src] += 1
    for name, alt in (("games_vs_ticker", g), ("obs_vs_ticker", o)):
        if alt is not None and tk is not None:
            stats[name]["n"] += 1
            if abs((alt - tk).total_seconds()) > 120:
                stats[name]["disagree_gt_2min"] += 1
    return st, gdate, src


# ----------------------------------------------------------------------------------------------------------------- quotes
def load_quotes():
    q = collections.defaultdict(dict)  # ticker -> {ts: (bid, ask, started, src)}
    obs_sched = {}
    n = collections.Counter()
    # AMENDMENT A1 (data-unit fix): observation prices are cents up to 2026-09-10 and dollars afterwards (switch inside 2026-09-10).
    # Unit is decided per ingest run (provenance.sourceFile, runId): any bid/ask > 1.0 in the run -> cents, else dollars.
    raw = []
    runmax = collections.defaultdict(float)
    paths = [("observations", p) for p in sorted(glob.glob(f"{D}/edgelab/observations/*.jsonl.gz"))] + \
            [("snapshot_obs", p) for p in sorted(glob.glob(f"{D}/edgelab/snapshots/*/pre_game_decision/*/frozen/market_observations.jsonl.gz"))]
    for kind, f in paths:
        FILES_USED["observations" if kind == "observations" else "snapshot_market_observations"] += 1
        for r in jl(f):
            key = ((r.get("provenance") or {}).get("sourceFile"), r.get("runId"))
            for v in (r.get("yesBid"), r.get("yesAsk")):
                if v is not None:
                    runmax[key] = max(runmax[key], float(v))
            t = r["marketTicker"]
            if series_of(t) not in SERIES_FAMILY:
                continue
            c = ts(r.get("capturedAt"))
            if r.get("yesBid") is None or r.get("yesAsk") is None or c is None:
                continue
            raw.append((kind, key, t, c, float(r["yesBid"]), float(r["yesAsk"]),
                        r.get("gameStartedAtCapture") is True or r.get("checkpoint") == "POST_START", r.get("scheduledStart")))
    for kind, key, t, c, b, a, started, sch in raw:
        scale = 100.0 if runmax[key] > 1.0 else 1.0
        n[f"unit_{'cents' if scale == 100.0 else 'dollars'}"] += 1
        if c in q[t]:
            continue
        q[t][c] = (b / scale, a / scale, started, kind)
        n[kind] += 1
        if sch:
            ek = event_key(t)
            if ek and ek not in obs_sched:
                obs_sched[ek] = ts(sch)
    for f in sorted(glob.glob(f"{D}/kalshi_registry_snapshots/kalshi_search_2026-*.json")):
        if os.path.basename(f) < "kalshi_search_2026-07-30":
            continue
        try:
            d = jload(f)
        except Exception:
            continue
        FILES_USED["kalshi_registry_snapshots"] += 1
        ms = d.get("markets") or []
        fscale = 100.0 if any((m.get("unit") == "cents") for m in ms) or max([float(m.get("yes_ask") or 0) for m in ms] or [0]) > 1.0 else 1.0
        for m in ms:
            t = m.get("market_ticker")
            c = ts(m.get("snapshot_ts"))
            if series_of(t) not in SERIES_FAMILY or c is None or m.get("yes_bid") is None or m.get("yes_ask") is None:
                continue
            if c not in q[t]:
                q[t][c] = (float(m["yes_bid"]) / fscale, float(m["yes_ask"]) / fscale, False, "registry_file")
                n["registry_new"] += 1
    return q, obs_sched, n


# ----------------------------------------------------------------------------------------------------------------- model values
LEDGER_MAP = {  # ledger market -> (YES-axis orientation): +1 modelProb is P(YES of marketTicker); -1 modelProb is P(NO)
    "YRFI": 1, "NRFI": -1, "ML_Home": 1, "ML_Away": 1, "F5_ML_Home": 1, "F5_ML_Away": 1,
    "TT_Home_Over": 1, "TT_Away_Over": 1, "Game_Total": 1,
    # RL_Home / RL_Away excluded: both rows point at the same KXMLBSPREAD ticker and the side orientation is not recorded.
}
EXPECTED_SERIES = {"YRFI": "KXMLBRFI", "NRFI": "KXMLBRFI", "ML_Home": "KXMLBGAME", "ML_Away": "KXMLBGAME", "F5_ML_Home": "KXMLBF5",
                   "F5_ML_Away": "KXMLBF5", "TT_Home_Over": "KXMLBTEAMTOTAL", "TT_Away_Over": "KXMLBTEAMTOTAL", "Game_Total": "KXMLBTOTAL"}


def add_model(models, ticker, t, p_sel, orient, src, n):
    if ticker is None or t is None or p_sel is None:
        return
    p = float(p_sel) / 100.0
    if not (0.0 <= p <= 1.0):
        n["bad_prob"] += 1
        return
    py = p if orient == 1 else 1 - p
    models[ticker].append((t, py, src))
    n[src] += 1


def ledger_rows(doc):
    data = doc.get("data", doc)
    for g in data.get("games") or []:
        for m in g.get("marketLedger") or []:
            yield m


ACCEPTED = []  # (time, ticker, market, modelProb_sel, archived executable price, source) for every ledger row with status Accepted


def load_models():
    models = collections.defaultdict(list)
    n = collections.Counter()
    # (1) frozen pre-game-decision snapshots (multiple intraday runs); time = snapshot manifest capturedAt
    for man in sorted(glob.glob(f"{D}/edgelab/snapshots/*/pre_game_decision/*/manifest.json")):
        ro = os.path.join(os.path.dirname(man), "frozen", "recommendation_output.json.gz")
        if not os.path.exists(ro):
            continue
        t = ts(jload(man).get("capturedAt"))
        FILES_USED["snapshot_recommendation_output"] += 1
        for m in ledger_rows(jload(ro)):
            o = LEDGER_MAP.get(m.get("market"))
            tk = m.get("marketTicker")
            if o is None or not tk or series_of(tk) != EXPECTED_SERIES[m["market"]]:
                continue
            add_model(models, tk, t, m.get("modelProb"), o, "ledger_snapshot", n)
            if m.get("status") == "Accepted":
                ACCEPTED.append((t, tk, m["market"], m.get("modelProb"), m.get("executableMarketProb"), "snapshot"))
    # (2) final daily pipeline ledger; time = meta.createdAt
    for f in sorted(glob.glob(f"{D}/pipeline/*/recommendations.json")):
        doc = jload(f)
        t = ts((doc.get("meta") or {}).get("createdAt"))
        FILES_USED["pipeline_recommendations_json"] += 1
        for m in ledger_rows(doc):
            o = LEDGER_MAP.get(m.get("market"))
            tk = m.get("marketTicker")
            if o is None or not tk or series_of(tk) != EXPECTED_SERIES[m["market"]]:
                continue
            add_model(models, tk, t, m.get("modelProb"), o, "ledger_pipeline_final", n)
            if m.get("status") == "Accepted":
                ACCEPTED.append((t, tk, m["market"], m.get("modelProb"), m.get("executableMarketProb"), "pipeline_final"))
    # (3) model_evaluations rows of the pipeline itself (pipeline_recommendations / prospective_snapshot); time = provenance.capturedAt
    for f in sorted(glob.glob(f"{D}/edgelab/model_evaluations/*.jsonl.gz")):
        FILES_USED["model_evaluations"] += 1
        for r in jl(f):
            if r.get("source") not in ("pipeline_recommendations", "prospective_snapshot"):
                continue
            sel = r.get("selection"); tk = r.get("marketTicker")
            o = LEDGER_MAP.get(sel)
            if o is None or not tk or ":" in tk or series_of(tk) != EXPECTED_SERIES[sel]:
                continue
            add_model(models, tk, ts((r.get("provenance") or {}).get("capturedAt")), r.get("modelFairProbability"), o, "model_eval_" + r["source"], n)
    # (4) repo adapter fair probabilities for every supported contract; time = file generatedAt (only the last run per date survives)
    for f in sorted(glob.glob(f"{D}/kalshi/discovery/2026-*.json")):
        if "_" in os.path.basename(f):
            continue
        doc = jload(f)
        t = ts(doc.get("generatedAt"))
        FILES_USED["kalshi_discovery"] += 1
        for c in doc.get("contracts") or []:
            if c.get("modelSupportStatus") != "SUPPORTED" or c.get("fairProbabilityPct") is None:
                continue
            if series_of(c.get("ticker")) not in SERIES_FAMILY:
                continue
            add_model(models, c["ticker"], t, c["fairProbabilityPct"], 1, "discovery_adapter", n)
    for k in models:
        models[k].sort(key=lambda x: (x[0], 0 if x[2].startswith(("ledger", "model_eval")) else 1))
    return models, n


# ----------------------------------------------------------------------------------------------------------------- R0 (archived recommendations)
R0_SIDE = {"YRFI": "YES", "NRFI": "NO", "ML_Home": "YES", "ML_Away": "YES", "F5_ML_Home": "YES", "F5_ML_Away": "YES",
           "TT_Home_Over": "YES", "TT_Away_Over": "YES", "Game_Total": "YES"}


def load_r0():
    out = []
    for f in sorted(glob.glob(f"{D}/edgelab/recommendations/*.jsonl.gz")):
        FILES_USED["recommendations"] += 1
        for r in jl(f):
            if r.get("source") != "pipeline_recommendations" or r.get("status") not in ("RECOMMENDED", "BET_PLACED", "RECOMMENDED_NOT_BET"):
                continue
            out.append({"recommendationId": r["recommendationId"], "status": r["status"], "marketName": r.get("marketName"),
                        "ticker": r.get("marketTicker"), "rec_time": ts((r.get("provenance") or {}).get("capturedAt")),
                        "model_sel": None if r.get("modelFairProbability") is None else r["modelFairProbability"] / 100.0,
                        "archived_price": None if r.get("marketImpliedProbability") is None else r["marketImpliedProbability"] / 100.0})
    return out


# ----------------------------------------------------------------------------------------------------------------- build
def pick_quote(qs, cutoff, strict=False):
    """latest two-sided, uncrossed, pre-start quote with ts <= cutoff (ts < cutoff if strict)."""
    best = None
    for t, (b, a, started, src) in qs:
        if started or (t >= cutoff if strict else t > cutoff):
            continue
        if b is None or a is None or not (0.0 < b < a < 1.0):
            continue
        best = (t, b, a, src)
    return best


def build():
    quotes, obs_sched, qn = load_quotes()
    games_sched = build_schedule(obs_sched)
    models, mn = load_models()
    sstats = {"source": collections.Counter(), "games_vs_ticker": collections.Counter(), "obs_vs_ticker": collections.Counter(), "earlier_than_games_file": collections.Counter()}
    start_cache = {}
    rows = []
    drop = collections.Counter()
    for tk, qd in quotes.items():
        ek = event_key(tk)
        if ek is None:
            continue
        if ek not in start_cache:
            start_cache[ek] = resolve_start(ek, games_sched, obs_sched, sstats)
        start, gdate, ssrc = start_cache[ek]
        if start is None:
            drop["no_start"] += 1
            continue
        qs = sorted(qd.items())
        e = pick_quote(qs, start - timedelta(minutes=10))
        if e is None:
            drop["no_two_sided_quote_ge10min_prestart"] += 1
            continue
        ml = [m for m in models.get(tk, []) if m[0] <= e[0] and m[0] < start]
        if not ml:
            drop["no_model_before_entry_quote" if models.get(tk) else "no_model_value_at_all"] += 1
            continue
        mt, mp, msrc = ml[-1]
        cl = pick_quote(qs, start, strict=True)
        rows.append({"game_id": ek, "contract_id": tk, "series": series_of(tk), "family": SERIES_FAMILY[series_of(tk)],
                     "yes_bid": e[1], "yes_ask": e[2], "quote_ts": e[0], "quote_src": e[3], "model_p": mp, "model_ts": mt, "model_src": msrc,
                     "close_yes_bid": cl[1] if cl else np.nan, "close_yes_ask": cl[2] if cl else np.nan, "close_ts": cl[0] if cl else None,
                     "start": start, "start_src": ssrc, "date": gdate})
    c = pd.DataFrame(rows)
    c["min_quote_to_start"] = (c.start - c.quote_ts).dt.total_seconds() / 60
    c["min_model_to_quote"] = (c.quote_ts - c.model_ts).dt.total_seconds() / 60
    assert (c.quote_ts <= c.start - timedelta(minutes=10)).all() and (c.model_ts <= c.quote_ts).all() and (c.model_ts < c.start).all()
    c.to_pickle(f"{WORK}/contracts_noy.pkl")

    # R0
    r0 = load_r0()
    r0rows = []
    r0drop = collections.Counter()
    for r in r0:
        tk = r["ticker"]; side = R0_SIDE.get(r["marketName"])
        if not tk or side is None or series_of(tk) not in SERIES_FAMILY:
            r0drop["unmapped_selection_or_ticker"] += 1; continue
        ek = event_key(tk)
        if ek not in start_cache:
            start_cache[ek] = resolve_start(ek, games_sched, obs_sched, sstats)
        start, gdate, ssrc = start_cache[ek]
        if r["rec_time"] is None or start is None or r["rec_time"] >= start:
            r0drop["rec_time_not_before_scheduled_start"] += 1; continue
        qs = sorted(quotes.get(tk, {}).items())
        e = pick_quote(qs, min(r["rec_time"], start - timedelta(minutes=10)))
        cl = pick_quote(qs, start, strict=True)
        r0rows.append({**r, "side": side, "game_id": ek, "contract_id": tk, "family": SERIES_FAMILY[series_of(tk)], "date": gdate, "start": start,
                       "yes_bid": e[1] if e else np.nan, "yes_ask": e[2] if e else np.nan, "quote_ts": e[0] if e else None,
                       "close_yes_bid": cl[1] if cl else np.nan, "close_yes_ask": cl[2] if cl else np.nan, "close_ts": cl[0] if cl else None})
        if e is None:
            r0drop["no_quote_at_or_before_rec_time"] += 1
    r0df = pd.DataFrame(r0rows)
    r0df.to_pickle(f"{WORK}/r0_noy.pkl")

    # R0b (supplementary): every intraday ledger decision with status Accepted, first pre-start occurrence per (ticker, side)
    r0b, seen = [], set()
    r0bdrop = collections.Counter()
    for t, tk, mk, mp, ap, src in sorted(ACCEPTED, key=lambda x: (x[0], x[1])):
        side = R0_SIDE.get(mk)
        ek = event_key(tk)
        if ek not in start_cache:
            start_cache[ek] = resolve_start(ek, games_sched, obs_sched, sstats)
        start, gdate, ssrc = start_cache[ek]
        if t is None or start is None or t >= start:
            r0bdrop["decision_not_before_start"] += 1; continue
        if (tk, side) in seen:
            continue
        seen.add((tk, side))
        qs = sorted(quotes.get(tk, {}).items())
        e = pick_quote(qs, min(t, start - timedelta(minutes=10)))
        cl = pick_quote(qs, start, strict=True)
        r0b.append({"recommendationId": None, "status": "LEDGER_ACCEPTED_" + src, "marketName": mk, "ticker": tk, "rec_time": t,
                    "model_sel": None if mp is None else mp / 100.0, "archived_price": None if ap is None else ap / 100.0,
                    "side": side, "game_id": ek, "contract_id": tk, "family": SERIES_FAMILY[series_of(tk)], "date": gdate, "start": start,
                    "yes_bid": e[1] if e else np.nan, "yes_ask": e[2] if e else np.nan, "quote_ts": e[0] if e else None,
                    "close_yes_bid": cl[1] if cl else np.nan, "close_yes_ask": cl[2] if cl else np.nan, "close_ts": cl[0] if cl else None})
        if e is None:
            r0bdrop["no_quote_at_or_before_decision"] += 1
    r0bdf = pd.DataFrame(r0b)
    r0bdf.to_pickle(f"{WORK}/r0b_noy.pkl")

    def split(dates):
        return np.where(pd.Series(dates) < "2026-09-15", "EXPLORE", "CONFIRM")
    c["split"] = split(c.date)
    cov = {"quotes_loaded": dict(qn), "model_values_loaded": dict(mn), "tickers_with_quotes": len(quotes),
           "schedule": {k: dict(v) for k, v in sstats.items()}, "contract_drop_reasons": dict(drop),
           "contracts": int(len(c)), "games": int(c.game_id.nunique()),
           "by_family_split": {f"{f}|{s}": {"contracts": int(len(g)), "games": int(g.game_id.nunique())} for (f, s), g in c.groupby(["family", "split"])},
           "model_src_counts": c.model_src.value_counts().to_dict(), "quote_src_counts": c.quote_src.value_counts().to_dict(),
           "minutes_quote_to_start_quantiles": c.min_quote_to_start.quantile([.1, .25, .5, .75, .9]).round(1).to_dict(),
           "minutes_model_to_quote_quantiles": c.min_model_to_quote.quantile([.1, .25, .5, .75, .9]).round(1).to_dict(),
           "close_after_entry_share": float((c.close_ts.notna() & (c.close_ts > c.quote_ts)).mean()),
           "date_range": [c.date.min(), c.date.max()],
           "unit_sanity_median_spread_by_month": c.assign(m=c.date.str[:7], sp=c.yes_ask - c.yes_bid).groupby("m").sp.median().round(4).to_dict(),
           "unit_sanity_median_mid_by_month": c.assign(m=c.date.str[:7], mid=(c.yes_ask + c.yes_bid) / 2).groupby("m").mid.median().round(4).to_dict(),
           "r0": {"archived_rows": len(r0), "kept": int(len(r0df)), "with_quote": int(r0df.yes_bid.notna().sum()) if len(r0df) else 0, "drops": dict(r0drop),
                  "by_family": r0df.family.value_counts().to_dict() if len(r0df) else {}},
           "r0b_ledger_accepted": {"accepted_rows": len(ACCEPTED), "first_prestart_per_ticker_side": int(len(r0bdf)),
                                   "with_quote": int(r0bdf.yes_bid.notna().sum()) if len(r0bdf) else 0, "drops": dict(r0bdrop),
                                   "by_family": r0bdf.family.value_counts().to_dict() if len(r0bdf) else {}},
           "files_used_counts": dict(FILES_USED)}
    json.dump(cov, open(f"{WORK}/coverage.json", "w"), indent=1, default=str)
    print(json.dumps(cov, indent=1, default=str))


# ----------------------------------------------------------------------------------------------------------------- evaluate
def load_official(series_list):
    res = {}
    meta = collections.Counter()
    for s in series_list:
        for tier in ("historical", "live"):
            p = f"{WORK}/settle_raw/MLB/{s}.{tier}.jsonl"
            if not os.path.exists(p):
                continue
            for r in jl(p):
                rr = r.get("result")
                if rr in ("yes", "no"):
                    res[r["ticker"]] = 1 if rr == "yes" else 0
                else:
                    meta[f"non_binary_{rr}"] += 1
    return res, meta


def load_repo_settlements():
    res = {}
    for f in sorted(glob.glob(f"{D}/edgelab/settlements/*.jsonl.gz")):
        for r in jl(f):
            o = r.get("outcome") or r.get("result")
            if o in ("YES", "NO"):
                res[r["marketTicker"]] = 1 if o == "YES" else 0
    return res


def logit(p):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4); return np.log(p / (1 - p))


def logreg(X, y, iters=50):
    X = np.column_stack([np.ones(len(y)), X]); b = np.zeros(X.shape[1])
    for _ in range(iters):
        eta = X @ b; mu = 1 / (1 + np.exp(-eta)); W = mu * (1 - mu) + 1e-12
        H = X.T @ (X * W[:, None]); g = X.T @ (y - mu)
        step = np.linalg.solve(H, g); b += step
        if np.max(np.abs(step)) < 1e-9:
            break
    cov = np.linalg.inv(H); se = np.sqrt(np.diag(cov))
    return [round(float(v), 4) for v in b], [round(float(v), 4) for v in se]


def diag_block(c):
    out = SEL.diagnostics(c)
    y = c.y.to_numpy(float)
    mid = ((c.yes_bid + c.yes_ask) / 2).to_numpy(float)
    if len(c) >= 30 and 0 < y.mean() < 1:
        b, se = logreg(logit(c.model_p)[:, None], y); out["calibration_model"] = {"intercept": b[0], "slope": b[1], "slope_se": se[1]}
        b, se = logreg(logit(mid)[:, None], y); out["calibration_mid"] = {"intercept": b[0], "slope": b[1], "slope_se": se[1]}
        try:
            b, se = logreg(np.column_stack([logit(c.model_p), logit(mid)]), y)
            out["joint_logit_y_on_model_and_mid"] = {"intercept": b[0], "b_model": b[1], "se_model": se[1], "b_mid": b[2], "se_mid": se[2],
                                                     "note": "b_model: weight on the model's logit given the mid's logit (0 = no information beyond the mid; compare with se)"}
        except np.linalg.LinAlgError:
            out["joint_logit_y_on_model_and_mid"] = "singular"
    out["mean_model_p"] = round(float(c.model_p.mean()), 4); out["mean_mid"] = round(float(mid.mean()), 4); out["mean_y"] = round(float(y.mean()), 4)
    return out


def rule_block(c, rule, boot=2000):
    b = SEL.select(c, rule)
    return {"rule": rule, "rule_sha256": SEL.freeze(rule), "all": SEL.summarize(b, boot, 7), "by_family": {k: SEL.summarize(v, boot=0) for k, v in b.groupby("family")},
            "by_price_bucket": SEL.buckets(b), "by_side": {k: SEL.summarize(v, boot=0) for k, v in b.groupby("side")}}


def evaluate():
    proto_txt = open(f"{WORK}/protocol.json", "rb").read()
    sha = hashlib.sha256(proto_txt).hexdigest()
    if open(f"{WORK}/protocol.sha256").read().split()[0] != sha:
        raise SystemExit("protocol.json changed after freezing; record an amendment instead")
    P = json.loads(proto_txt)
    am_txt = open(f"{WORK}/protocol_amendments.json", "rb").read()
    am_sha = hashlib.sha256(am_txt).hexdigest()
    if open(f"{WORK}/protocol_amendments.sha256").read().split()[0] != am_sha:
        raise SystemExit("protocol_amendments.json changed after freezing")
    c = pd.read_pickle(f"{WORK}/contracts_noy.pkl")
    r0 = pd.read_pickle(f"{WORK}/r0_noy.pkl")
    r0b = pd.read_pickle(f"{WORK}/r0b_noy.pkl")
    # CLV: a close is informative only if it was observed strictly after the entry quote (otherwise close == entry by construction)
    for df in (c, r0, r0b):
        stale = ~(pd.to_datetime(df.close_ts, utc=True) > pd.to_datetime(df.quote_ts, utc=True))
        df.loc[stale, ["close_yes_bid", "close_yes_ask"]] = np.nan
    off, offmeta = load_official(sorted(SERIES_FAMILY))
    repo = load_repo_settlements()
    c["y"] = c.contract_id.map(off)
    both = c[c.y.notna() & c.contract_id.isin(repo)]
    settle_cmp = {"contracts": int(len(c)), "with_official_result": int(c.y.notna().sum()), "with_repo_result": int(c.contract_id.isin(repo).sum()),
                  "both": int(len(both)), "disagree_official_vs_repo": int((both.y != both.contract_id.map(repo)).sum()), "official_non_binary": dict(offmeta)}
    c = c[c.y.notna()].copy(); c["y"] = c.y.astype(int)
    c["split"] = np.where(c.date < P["split"]["confirm_from"], "EXPLORE", "CONFIRM")
    c["regular_season"] = c.date <= P["split"]["regular_season_last_date"]
    fams = P["families_in_rules"]
    cr = c[c.family.isin(fams)]
    rep = {"protocol_sha256": sha, "amendments_sha256": am_sha, "amendments": json.loads(am_txt), "settlement_check": settle_cmp, "coverage_after_settlement": {}, "diagnostics": {}, "rules": {}, "reliability_map": {}}
    for s in ("EXPLORE", "CONFIRM"):
        g = c[c.split == s]
        rep["coverage_after_settlement"][s] = {"contracts": int(len(g)), "games": int(g.game_id.nunique()), "dates": [g.date.min(), g.date.max()],
                                               "by_family": g.family.value_counts().to_dict()}
    # diagnostics
    for s, g in [("EXPLORE", c[c.split == "EXPLORE"]), ("CONFIRM", c[c.split == "CONFIRM"]), ("ALL", c)]:
        rep["diagnostics"][s] = {"all_families": diag_block(g[g.family.isin(fams)]),
                                 "by_family": {f: diag_block(gg) for f, gg in g.groupby("family")},
                                 "by_model_source": {m: diag_block(gg) for m, gg in g[g.family.isin(fams)].groupby("model_src")}}
    # rules R1-R3
    subsets = {"EXPLORE": cr[cr.split == "EXPLORE"], "CONFIRM": cr[cr.split == "CONFIRM"],
               "CONFIRM_regular_season_only": cr[(cr.split == "CONFIRM") & cr.regular_season], "CONFIRM_postseason_only": cr[(cr.split == "CONFIRM") & ~cr.regular_season]}
    for rule in P["rules"]:
        rep["rules"][rule["name"]] = {k: rule_block(v, rule) for k, v in subsets.items()}
    # R0
    rep["rules"]["R0_incumbent_actual"] = r0_eval(r0, off, repo, P)
    rep["rules"]["R0b_ledger_accepted_supplementary"] = r0_eval(r0b, off, repo, P)
    # props / other families: same frozen rules, separate block
    oth = c[c.family.isin(P["families_other_block"])]
    rep["rules_other_families"] = {rule["name"]: {"EXPLORE": rule_block(oth[oth.split == "EXPLORE"], rule), "CONFIRM": rule_block(oth[oth.split == "CONFIRM"], rule)}
                                   for rule in P["rules"]}
    # reliability map
    rep["reliability_map"] = reliability(cr, P)
    json.dump(rep, open(f"{WORK}/report.json", "w"), indent=1, default=str)
    c.to_pickle(f"{WORK}/contracts_with_y.pkl")
    print(json.dumps({k: rep[k] for k in ("settlement_check", "coverage_after_settlement")}, indent=1, default=str))


def side_table(r):
    """R0 rows -> selection-style rows on the recommended side at the observed quote."""
    yes = r.side == "YES"
    mid = (r.yes_bid + r.yes_ask) / 2
    out = pd.DataFrame({"game_id": r.game_id, "contract_id": r.contract_id, "family": r.family, "date": r.date, "side": r.side,
                        "entry": np.where(yes, r.yes_ask, 1 - r.yes_bid), "entry_mid": np.where(yes, mid, 1 - mid), "prob": r.model_sel,
                        "won": np.where(yes, r.y == 1, r.y == 0)})
    cm = (r.close_yes_bid + r.close_yes_ask) / 2
    out["close_mid"] = np.where(yes, cm, 1 - cm)
    out["fee"] = SEL.fee_unrounded(out.entry); out["net_edge"] = out.prob - out.entry - out.fee
    return out


def r0_eval(r0, off, repo, P):
    r = r0.copy()
    r["y"] = r.contract_id.map(off)
    info = {"archived_recommendations_kept": int(len(r)), "with_official_result": int(r.y.notna().sum()), "with_quote": int(r.yes_bid.notna().sum())}
    r = r[r.y.notna()].copy()
    r["split"] = np.where(r.date < P["split"]["confirm_from"], "EXPLORE", "CONFIRM")
    r["regular_season"] = r.date <= P["split"]["regular_season_last_date"]
    # dedupe: one archived recommendation per (ticker, side)
    r = r.sort_values("rec_time").drop_duplicates(["contract_id", "side"])
    q = r[r.yes_bid.notna() & r.model_sel.notna()].copy()
    st = side_table(q)
    st["split"] = q.split.values; st["regular_season"] = q.regular_season.values
    st = st[(st.entry > 0) & (st.entry < 1)]
    out = {"info": info, "integrity": {
        "archived_model_le_archived_price": int((r.model_sel <= r.archived_price).sum()),
        "archived_price_vs_observed_side_mid_abs_gt_0.05": int((np.abs(st.entry_mid.to_numpy(float) - q.loc[st.index, "archived_price"].to_numpy(float)) > 0.05).sum()) if len(st) else 0,
        "rows_compared": int(len(st))}}
    for name, g in (("EXPLORE", st[st.split == "EXPLORE"]), ("CONFIRM", st[st.split == "CONFIRM"]),
                    ("CONFIRM_regular_season_only", st[(st.split == "CONFIRM") & st.regular_season]), ("ALL", st)):
        out[name] = {"all": SEL.summarize(g, 2000, 7), "by_family": {k: SEL.summarize(v, boot=0) for k, v in g.groupby("family")},
                     "by_price_bucket": SEL.buckets(g)}
    # R0 at the archived price (incumbent's own executable price field), as a sensitivity
    a = r[r.archived_price.notna() & r.model_sel.notna()].copy()
    if len(a):
        ap = pd.DataFrame({"game_id": a.game_id, "contract_id": a.contract_id, "family": a.family, "side": a.side, "entry": a.archived_price,
                           "entry_mid": a.archived_price, "prob": a.model_sel, "won": np.where(a.side == "YES", a.y == 1, a.y == 0), "split": a.split})
        ap = ap[(ap.entry > 0) & (ap.entry < 1)]; ap["fee"] = SEL.fee_unrounded(ap.entry)
        out["sensitivity_at_archived_price"] = {s: SEL.summarize(ap[ap.split == s], 2000, 7) for s in ("EXPLORE", "CONFIRM")}
    # which R0 bets would R3 have avoided (at the same quote, with the incumbent's archived model prob)
    st["r3_ok"] = (st.net_edge >= 0.05) & ((st.prob - st.entry_mid).abs() <= 0.10)
    st["fail_disagreement"] = (st.prob - st.entry_mid).abs() > 0.10
    st["fail_net_edge"] = st.net_edge < 0.05
    out["r3_filter_on_r0"] = {s: {"kept_by_r3": SEL.summarize(g[g.r3_ok], 2000, 7), "avoided_by_r3": SEL.summarize(g[~g.r3_ok], 2000, 7),
                                  "avoided_reason_counts": {"disagreement_gt_0.10": int(g[~g.r3_ok].fail_disagreement.sum()),
                                                            "net_edge_lt_0.05": int(g[~g.r3_ok].fail_net_edge.sum())}}
                              for s, g in (("EXPLORE", st[st.split == "EXPLORE"]), ("CONFIRM", st[st.split == "CONFIRM"]), ("ALL", st))}
    return out


def reliability(cr, P):
    RM = P["reliability_map"]
    s = SEL.sides(cr)
    s["split"] = np.concatenate([cr.split.values, cr.split.values])
    s = s[(s.entry >= RM["bucket_edges"][0]) & (s.entry <= RM["bucket_edges"][-1])]
    e = RM["bucket_edges"]
    s["bucket"] = pd.cut(s.entry, e, right=False, include_lowest=True).astype(str)
    s.loc[s.entry >= e[-2], "bucket"] = f"[{e[-2]}, {e[-1]}]"  # protocol: last bucket [0.75,0.95] is closed on the right
    cells = []
    ex = s[s.split == "EXPLORE"]; cf = s[s.split == "CONFIRM"]
    for (fam, bk, sd), g in ex.groupby(["family", "bucket", "side"]):
        n = len(g); wr = float(g.won.mean()); mp = float(g.prob.mean()); be = float((g.entry + g.fee).mean())
        cand = n >= RM["min_n"] and (wr - be) >= RM["min_excess_over_breakeven"] and abs(mp - wr) <= RM["max_model_vs_observed"]
        cell = {"family": fam, "bucket": bk, "side": sd, "EXPLORE": {"n": n, "games": int(g.game_id.nunique()), "win_rate": round(wr, 4),
                "win_rate_95ci": SEL.wilson(int(g.won.sum()), n), "mean_model_p": round(mp, 4), "mean_breakeven": round(be, 4), "excess": round(wr - be, 4)},
                "candidate": bool(cand)}
        if cand:
            h = cf[(cf.family == fam) & (cf.bucket == bk) & (cf.side == sd)]
            sm = SEL.summarize(h, 2000, 7)
            survived = sm.get("bets", 0) >= RM["confirm_min_n"] and sm.get("net_roi", -1) > 0 and sm.get("win_rate", 0) >= sm.get("breakeven_win_prob", 1)
            cell["CONFIRM"] = sm
            cell["confirm_verdict"] = "survived one forward split - not validated" if survived else "did not survive CONFIRM"
        cells.append(cell)
    return {"cells": cells, "n_cells": len(cells), "n_candidates": sum(c["candidate"] for c in cells),
            "note": "population = every quoted contract side (YES at yes_ask, NO at 1-yes_bid) with a point-in-time model value; ladder rungs of one game are not independent"}


if __name__ == "__main__":
    {"build": build, "evaluate": evaluate}[sys.argv[1]]()
