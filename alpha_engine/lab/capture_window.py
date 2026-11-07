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
KEEP = ("ticker", "title", "floor_strike", "yes_bid_dollars", "yes_ask_dollars", "status", "result", "event_ticker")
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


def write_shard(stage: Path, shard: dict) -> Path:
    body = json.dumps(shard, sort_keys=True, separators=(",", ":")).encode()
    h = hashlib.sha256(body).hexdigest()[:16]
    ts = pd.Timestamp(shard["captured_utc"]).strftime("%Y%m%dT%H%M%SZ")
    p = Path(stage) / ts[:4] / f"{ts[:8]}" / f"{ts}__{h}.json.gz"
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


def capture_tick(clock, fetch=None, series=SERIES_ALL, run_id: str = "", forced: bool = False) -> dict:
    fetch = fetch or (lambda s: PP.fetch_totals(series=s, allow_empty=(s != "KXNFLTOTAL")))
    shard = {"kind": "capture_shard", "run_id": run_id, "captured_utc": None, "forced": forced, "books": {}, "failures": {}}
    for s in series:
        try:
            shard["books"][s] = compact(fetch(s))
        except Exception as e:
            shard["failures"][s] = repr(e)[:200]
    shard["captured_utc"] = clock().isoformat()
    return shard


def run_window_capture(games: pd.DataFrame, stage: Path, clock=None, fetch=None, sleep=time.sleep, interval_s: float = 300.0, span_min: float = 58.0, publish=None, run_id: str = "", force: bool = False) -> dict:
    """Capture at `interval_s` while inside a decision window, for at most `span_min`.  `publish(stage)` (optional) is called after every tick so data is durable immediately."""
    clock = clock or (lambda: pd.Timestamp.now(tz="UTC"))
    start = clock(); ko = kickoffs(games); ko = ko[ko > start - pd.Timedelta(hours=1)]
    res = {"start_utc": start.isoformat(), "ticks": 0, "series_failures": 0, "shards": [], "no_window": False, "published": 0, "publish_errors": []}
    while True:
        now = clock()
        w = due_windows(ko, now, span_min=0)                                    # windows containing 'now'
        if not w and not force:
            nxt = due_windows(ko, now, span_min=max(0.0, span_min - (now - start).total_seconds() / 60))
            if not nxt:
                res["no_window"] = res["ticks"] == 0; break
            sleep(max(1.0, min(60.0, (min(x["start"] for x in nxt) - now).total_seconds()))); continue
        t0 = time.time(); shard = capture_tick(clock, fetch, run_id=run_id, forced=force and not w)
        p = write_shard(stage, shard); res["ticks"] += 1; res["series_failures"] += len(shard["failures"]); res["shards"].append(p.name)
        if publish:
            r = publish(stage)
            res["published"] += int(bool(r.get("pushed"))); 
            if r.get("error"):
                res["publish_errors"].append(r["error"])
        if (clock() - start).total_seconds() / 60 + interval_s / 60 >= span_min:
            break
        sleep(max(1.0, interval_s - (time.time() - t0)))
    return res


# ---------------------------------------------------------------- single-writer ingestion of shards into the chained ledgers
def ingest_shards(shards_dir: Path, out_dir: Path, games: pd.DataFrame, now: pd.Timestamp | None = None) -> dict:
    now = now or pd.Timestamp.now(tz="UTC"); out_dir = Path(out_dir)
    done = {o["run_id"] for o in PP_read(out_dir / "observations.jsonl") if o.get("source") == PP.SOURCE_FALLBACK}
    st = {"shards_seen": 0, "ingested": 0, "observations": 0, "quotes": 0, "series_failures": 0, "rejected": {}}
    for p in sorted(Path(shards_dir).rglob("*.json.gz")):
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
