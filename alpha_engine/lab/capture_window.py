"""Kickoff-aware, durable, low-cost quote capture (RESEARCH_ONLY).  Separate from model refreshes on purpose: capturing is cheap and must be frequent; refreshing predictions is expensive and rare.

* `due_windows` derives, from the schedule alone, the instants at which the pre-registered decisions happen (kickoff -24h / -6h / -90m for every not-yet-started game) and the capture windows
  [decision-PRE, decision+POST] around them.  Capture ticks (default every 5 min) are taken only inside windows, so a session that starts for nothing exits at once.
* every tick writes ONE immutable shard: the fail-closed books of every series (each series succeeds completely or is recorded as a failure), content-hash in the file name, never edited.
  Shards are new files, so concurrent capture sessions never fork a ledger; a single writer (`ingest_shards`) turns shards into the hash-chained ledgers.
* a missed tick is a missed tick: nothing here (or anywhere) reconstructs a quote that was not observed."""
from __future__ import annotations
import gzip, hashlib, json, os, time
from pathlib import Path
import pandas as pd
from . import prospective as PP, player_prospective as PPR

PRE_MIN, POST_MIN = 35, 5                                   # a decision needs an observation <= 30 min old: capture from dt-35 to dt+5
SERIES_ALL = ("KXNFLTOTAL",) + tuple(PPR.SERIES)
KEEP = ("ticker", "title", "floor_strike", "yes_bid_dollars", "yes_ask_dollars", "status", "result", "event_ticker")        # schema 1 (kept readable: existing shards use it)
# schema 2: EVERY field of the API market object is preserved.  Dynamic fields are stored at every tick; the rest (rules text, strike metadata, creation time, ...) is stored once per contract
# version in a content-addressed registry shard (`contracts/`), referenced from each market by `static_sha`.  Each page also records the sha256 of the raw response bytes.
DYN_KEYS = ("ticker", "event_ticker", "title", "floor_strike", "status", "result", "expiration_value", "close_time", "expiration_time", "expected_expiration_time", "latest_expiration_time",
            "yes_bid_dollars", "yes_ask_dollars", "no_bid_dollars", "no_ask_dollars", "yes_bid_size_fp", "yes_ask_size_fp", "last_price_dollars", "previous_price_dollars",
            "previous_yes_bid_dollars", "previous_yes_ask_dollars", "volume_fp", "volume_24h_fp", "open_interest_fp", "updated_time")
REQUIRED = ("ticker", "yes_bid_dollars", "yes_ask_dollars")
ALLOWED_PREFIXES = ("captures/", "contracts/", "heartbeats/", "settlements/")     # the ONLY paths a capture worker may write on the data branch
MAX_FUTURE_SKEW_S = 120


def kickoffs(games: pd.DataFrame, season: int | None = None) -> pd.Series:
    g = games[games["gametime"].notna()]
    if season is not None:
        g = g[g["season"] == season]
    return pd.Series({r.game_id: PP.kickoff_utc(r) for r in g.itertuples()})


def decision_times(ko: pd.Series, now: pd.Timestamp) -> list[tuple[str, str, pd.Timestamp]]:
    out = []
    for gid, k in ko.items():
        for h, m in PP.HORIZONS_MIN.items():
            out.append((gid, h, k - pd.Timedelta(minutes=m)))
    return sorted(out, key=lambda x: x[2])


def due_windows(ko: pd.Series, now: pd.Timestamp, span_min: float = 58.0) -> list[dict]:
    """Capture windows intersecting [now, now+span]."""
    end = now + pd.Timedelta(minutes=span_min); w = []
    for gid, h, dt in decision_times(ko, now):
        a, b = dt - pd.Timedelta(minutes=PRE_MIN), dt + pd.Timedelta(minutes=POST_MIN)
        if b >= now and a <= end:
            w.append({"game_id": gid, "horizon": h, "decision_utc": dt.isoformat(), "start": a, "end": b})
    return w


def coverage_matrix(ko: pd.Series, obs: list[dict], series: str = "KXNFLTOTAL") -> pd.DataFrame:
    """Per (game, horizon): was a COMPLETE observation of `series` taken within 30 min before the decision time?  Missing stays missing."""
    t = sorted(pd.Timestamp(o["observed_at"]) for o in obs if o.get("series") == series and o.get("complete"))
    rows = []
    for gid, h, dt in decision_times(ko, pd.Timestamp.now(tz="UTC")):
        prior = [x for x in t if x <= dt]
        age = (dt - prior[-1]).total_seconds() / 60 if prior else None
        rows.append({"game_id": gid, "horizon": h, "decision_utc": dt.isoformat(), "last_obs_age_min": None if age is None else round(age, 1), "covered": age is not None and age <= PP.PRIMARY_AGE_MIN})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- shards
def compact(book: dict) -> dict:
    return {"series": book["series"], "n": book["n"], "complete": book["complete"],
            "pages": [{"fetched_utc": p["fetched_utc"], "markets": [{k: m.get(k) for k in KEEP if k in m} for m in p["markets"]]} for p in book["pages"]]}


def static_sha(static: dict) -> str:
    return hashlib.sha256(json.dumps(static, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def compact2(book: dict, known: dict) -> tuple[dict, dict, dict]:
    """Lossless split of an API book into (dynamic book, new static registry rows, field-availability counters).  `known` = {ticker: static_sha} already registered."""
    new, miss, pages = {}, {k: 0 for k in REQUIRED}, []
    for pg in book["pages"]:
        mk = []
        for m in pg["markets"]:
            dyn = {k: m[k] for k in DYN_KEYS if k in m}
            st = {k: v for k, v in m.items() if k not in DYN_KEYS}
            sha = static_sha(st); dyn["static_sha"] = sha
            for k in REQUIRED:
                if dyn.get(k) is None:
                    miss[k] += 1
            if known.get(dyn.get("ticker")) != sha:
                new[dyn["ticker"]] = {"sha": sha, "static": st}
            mk.append(dyn)
        pages.append({"fetched_utc": pg["fetched_utc"], "raw_sha256": pg.get("raw_sha256"), "raw_bytes": pg.get("raw_bytes"), "markets": mk})
    return {"series": book["series"], "n": book["n"], "complete": book["complete"], "pages": pages}, new, miss


def write_shard(stage: Path, shard: dict, kind: str = "captures") -> Path:
    body = json.dumps(shard, sort_keys=True, separators=(",", ":")).encode()
    h = hashlib.sha256(body).hexdigest()[:16]
    ts = pd.Timestamp(shard["captured_utc"]).strftime("%Y%m%dT%H%M%SZ")
    p = Path(stage) / kind / ts[:4] / f"{ts[:8]}" / f"{ts}__{h}.json.gz"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        with gzip.GzipFile(filename="", mode="wb", fileobj=open(p, "wb"), mtime=0) as f:
            f.write(body)
    return p


def read_shard(path: Path) -> dict:
    """Verify the content hash embedded in the file name before trusting anything inside."""
    raw = gzip.decompress(Path(path).read_bytes())
    want = Path(path).name.split("__")[1].split(".")[0]
    if hashlib.sha256(raw).hexdigest()[:16] != want:
        raise ValueError(f"shard hash mismatch: {path}")
    return json.loads(raw)


def capture_tick(clock, fetch=None, series=SERIES_ALL, run_id: str = "", forced: bool = False, known: dict | None = None, schema: int = 2) -> tuple[dict, dict | None]:
    """One fail-closed tick.  Returns (shard, registry_shard or None).  A series either succeeds completely (every page) or is recorded as a failure; a book whose required fields are
    missing is still stored (nothing is dropped) but counted in `missing_fields` so the heartbeat/alerts can see it."""
    fetch = fetch or (lambda s: PP.fetch_totals(series=s, allow_empty=(s != "KXNFLTOTAL")))
    known = known if known is not None else {}
    shard = {"kind": "capture_shard", "schema": schema, "run_id": run_id, "captured_utc": None, "forced": forced, "books": {}, "failures": {}}
    new_all, missing = {}, {}
    for s in series:
        try:
            bk = fetch(s)
            if schema == 2:
                c, new, miss = compact2(bk, known); shard["books"][s] = c; new_all.update(new)
                if any(miss.values()):
                    missing[s] = miss
            else:
                shard["books"][s] = compact(bk)
        except Exception as e:
            shard["failures"][s] = repr(e)[:200]
    shard["captured_utc"] = clock().isoformat()
    if missing:
        shard["missing_fields"] = missing
    reg = None
    if new_all:
        reg = {"kind": "contract_registry", "schema": 2, "run_id": run_id, "captured_utc": shard["captured_utc"], "contracts": new_all}
        shard["registry_rows"] = len(new_all)
    return shard, reg


def next_window_start(ko: pd.Series, now: pd.Timestamp):
    ws = [dt - pd.Timedelta(minutes=PRE_MIN) for _, _, dt in decision_times(ko, now) if dt - pd.Timedelta(minutes=PRE_MIN) > now]
    return min(ws) if ws else None


def run_window_capture(games: pd.DataFrame, stage: Path, clock=None, fetch=None, sleep=time.sleep, interval_s: float = 300.0, span_min: float = 58.0, publish=None, run_id: str = "",
                       force: bool = False, known_fn=None, schema: int = 2) -> dict:
    """Capture at `interval_s` while inside a decision window, for at most `span_min`.  `publish(stage)` (optional) is called after every tick so data is durable immediately.
    `known_fn()` -> {ticker: static_sha} already in the registry (so static contract text is stored once, not every tick)."""
    clock = clock or (lambda: pd.Timestamp.now(tz="UTC"))
    start = clock(); ko = kickoffs(games); ko = ko[ko > start - pd.Timedelta(hours=1)]
    known = dict(known_fn()) if known_fn else {}
    res = {"start_utc": start.isoformat(), "ticks": 0, "series_failures": 0, "shards": [], "registry_shards": [], "registry_rows": 0, "missing_fields": {}, "no_window": False, "published": 0,
           "publish_errors": [], "first_tick_utc": None, "last_tick_utc": None, "tick_seconds": []}
    while True:
        now = clock()
        w = due_windows(ko, now, span_min=0)                                    # windows containing 'now'
        if not w and not force:
            nxt = due_windows(ko, now, span_min=max(0.0, span_min - (now - start).total_seconds() / 60))
            if not nxt:
                res["no_window"] = res["ticks"] == 0; break
            sleep(max(1.0, min(60.0, (min(x["start"] for x in nxt) - now).total_seconds()))); continue
        t0 = time.time(); shard, reg = capture_tick(clock, fetch, run_id=run_id, forced=force and not w, known=known, schema=schema)
        p = write_shard(stage, shard); res["ticks"] += 1; res["series_failures"] += len(shard["failures"]); res["shards"].append(p.name)
        res["first_tick_utc"] = res["first_tick_utc"] or shard["captured_utc"]; res["last_tick_utc"] = shard["captured_utc"]; res["tick_seconds"].append(round(time.time() - t0, 1))
        for k, v in (shard.get("missing_fields") or {}).items():
            res["missing_fields"][k] = res["missing_fields"].get(k, 0) + sum(v.values())
        if reg:
            res["registry_shards"].append(write_shard(stage, reg, kind="contracts").name); res["registry_rows"] += len(reg["contracts"])
            known.update({t: r["sha"] for t, r in reg["contracts"].items()})
        if publish:
            r = publish(stage)
            res["published"] += int(bool(r.get("pushed")))
            if r.get("error"):
                res["publish_errors"].append(r["error"])
        if (clock() - start).total_seconds() / 60 + interval_s / 60 >= span_min:
            break
        sleep(max(1.0, interval_s - (time.time() - t0)))
    nw = next_window_start(ko, clock()); res["next_window_utc"] = nw.isoformat() if nw is not None else None
    res["end_utc"] = clock().isoformat()
    return res


# ---------------------------------------------------------------- exchange-native settlement evidence (independent of nflverse)
def capture_settled(clock, fetch=None, series=SERIES_ALL, days: int = 3) -> dict:
    """Fail-closed capture of SETTLED markets closed in the last `days` days.  The market objects are stored whole (lossless; there are few of them).  Used to cross-check the nflverse-derived
    outcome of every eligible decision: a disagreement makes the decision ineligible (SETTLEMENT_MISMATCH)."""
    since = int((clock() - pd.Timedelta(days=days)).timestamp())
    fetch = fetch or (lambda s: PP.fetch_totals(series=s, allow_empty=True, status="settled", extra=f"&min_close_ts={since}"))
    shard = {"kind": "settlement_shard", "schema": 2, "captured_utc": None, "books": {}, "failures": {}}
    for s in series:
        try:
            bk = fetch(s)
            shard["books"][s] = {"series": s, "n": bk["n"], "complete": bk["complete"], "pages": [{"fetched_utc": p["fetched_utc"], "raw_sha256": p.get("raw_sha256"), "markets": p["markets"]} for p in bk["pages"]]}
        except Exception as e:
            shard["failures"][s] = repr(e)[:200]
    shard["captured_utc"] = clock().isoformat()
    return shard


def load_exchange_results(root: Path) -> tuple[dict, dict]:
    """{ticker: {'result': 'yes'|'no', 'expiration_value':..., 'captured_utc':...}} from settlement shards; tickers with CONFLICTING results across shards are returned separately (never trusted)."""
    res, conflicts = {}, {}
    base = Path(root) / "settlements" if (Path(root) / "settlements").is_dir() else Path(root)
    for p in sorted(base.rglob("*.json.gz")):
        try:
            sh = read_shard(p)
        except Exception:
            continue
        if sh.get("kind") != "settlement_shard":
            continue
        for bk in sh["books"].values():
            if not bk.get("complete"):
                continue
            for pg in bk["pages"]:
                for m in pg["markets"]:
                    r = m.get("result")
                    if r not in ("yes", "no"):
                        continue
                    t = m["ticker"]
                    if t in res and res[t]["result"] != r:
                        conflicts[t] = [res[t]["result"], r]
                    res.setdefault(t, {"result": r, "expiration_value": m.get("expiration_value"), "captured_utc": sh["captured_utc"]})
    for t in conflicts:
        res.pop(t, None)
    return res, conflicts


# ---------------------------------------------------------------- single-writer ingestion of shards into the chained ledgers
def ingest_shards(shards_dir: Path, out_dir: Path, games: pd.DataFrame, now: pd.Timestamp | None = None) -> dict:
    now = now or pd.Timestamp.now(tz="UTC"); out_dir = Path(out_dir)
    done = {o["run_id"] for o in PP_read(out_dir / "observations.jsonl") if o.get("source") == PP.SOURCE_FALLBACK}
    st = {"shards_seen": 0, "ingested": 0, "observations": 0, "quotes": 0, "series_failures": 0, "rejected": {}}
    root = Path(shards_dir); root = root / "captures" if (root / "captures").is_dir() else root          # shards only; registry/heartbeat/settlement files are not quotes
    for p in sorted(root.rglob("*.json.gz")):
        st["shards_seen"] += 1
        try:
            sh = read_shard(p)
        except Exception as e:
            st["rejected"][p.name] = f"unreadable/corrupt: {e!r}"[:100]; continue
        cap = pd.Timestamp(sh["captured_utc"])
        if (cap - now).total_seconds() > MAX_FUTURE_SKEW_S:
            st["rejected"][p.name] = "captured_utc is in the future (clock skew or tampering)"; continue
        if not p.name.startswith(cap.strftime("%Y%m%dT%H%M%SZ")):
            st["rejected"][p.name] = "file name time does not match captured_utc"; continue
        sid = "shard:" + p.name
        if sid in done:
            continue
        for s, err in sh["failures"].items():
            PP.record_failure(out_dir, RuntimeError(f"{s}: {err}"), now=cap); st["series_failures"] += 1
        for s, bk in sh["books"].items():
            if not bk.get("complete"):
                continue
            if any(pd.Timestamp(pg["fetched_utc"]) > cap + pd.Timedelta(seconds=1) for pg in bk["pages"]):
                st["rejected"][p.name + ":" + s] = "page time after shard capture time"; continue
            st["quotes"] += PP.record_quotes(bk, games, out_dir, run_id=sid); st["observations"] += 1
        st["ingested"] += 1
    return st


def PP_read(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines()] if Path(path).exists() else []
