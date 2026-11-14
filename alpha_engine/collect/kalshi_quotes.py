"""Kalshi timestamped quote history (candlesticks) for SETTLED markets of the evaluated families (RESEARCH_ONLY, $0, anonymous, manual only).

Why: grading a decision needs the price that was actually available at the decision time, not the close. The public Trade API serves
OHLC candlesticks of the YES bid, YES ask and trade price per market after settlement: ``/series/{s}/markets/{t}/candlesticks`` for markets
settled after the exchange's ``/historical/cutoff`` and ``/historical/markets/{t}/candlesticks`` before it (field names differ:
``close_dollars`` vs ``close``; both are normalised here). This module samples settled markets (from the settlement cache written by
``kalshi_settlements``), pulls hourly candles over each market's life and measures how much of it carries a two-sided quote.

    python -m alpha_engine.collect.kalshi_quotes fetch --settlements-cache /tmp/k --cache-dir /tmp/q --series KXNBAGAME --per-month 3 --max-calls 60
    python -m alpha_engine.collect.kalshi_quotes ledger --cache-dir /tmp/q --out digest.json

Rules: same as ``kalshi_settlements`` (no key/account/orders; <= 200 calls/invocation; >= 2 s apart; 429 back-off then stop; any other non-200
stops; raw pages only outside the repository). Point in time: a candle is known at its ``end_period_ts``; join features as-of (<=) that
timestamp, never to a later candle. Market-derived: these are evaluation/execution prices, never model inputs (catalog marks the m.* quote
inputs EXCLUDED_MARKET for prediction). Rights: Kalshi terms unread here -> UNRESOLVED_INTERNAL_ONLY. Not scheduled anywhere.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from .kalshi_settlements import BACKOFF_429, HARD_MAX_CALLS, HOST, MAX_429, MIN_PAUSE, SERIES_RE, UA, _outside_repo, load_rows

INTERVAL_MIN = 60


def iso_ts(s: str) -> int:
    return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def candle_url(series: str, ticker: str, start: int, end: int, historical: bool, interval: int = INTERVAL_MIN) -> str:
    if not SERIES_RE.match(series or "") or not ticker.startswith(series + "-"):
        raise ValueError("invalid series/ticker")
    q = urllib.parse.urlencode({"start_ts": int(start), "end_ts": int(end), "period_interval": int(interval)})
    t = urllib.parse.quote(ticker, safe="")
    if historical:
        return f"{HOST}/historical/markets/{t}/candlesticks?{q}"
    return f"{HOST}/series/{series}/markets/{t}/candlesticks?{q}"


def _px(block: dict | None, key: str):
    if not block:
        return None
    v = block.get(f"{key}_dollars", block.get(key))
    return float(v) if v not in (None, "") else None


def norm_candle(c: dict) -> dict:
    """Both schemas -> {ts, bid, ask, last, volume} using the period CLOSE values (pure)."""
    vol = c.get("volume_fp", c.get("volume"))
    return {"ts": int(c["end_period_ts"]), "bid": _px(c.get("yes_bid"), "close"), "ask": _px(c.get("yes_ask"), "close"),
            "last": _px(c.get("price"), "close"), "volume": float(vol) if vol not in (None, "") else None}


def two_sided(c: dict) -> bool:
    return c["bid"] is not None and c["ask"] is not None and 0.0 < c["bid"] < c["ask"] < 1.0


def market_quote_stats(candles: list[dict], open_ts: int, close_ts: int) -> dict:
    """Coverage of hourly two-sided quotes over the market's life and in the 24 h before close (pure)."""
    cs = sorted((norm_candle(c) for c in candles), key=lambda x: x["ts"])
    life_h = max(1, (close_ts - open_ts) // 3600)
    two = [c for c in cs if two_sided(c)]
    last24 = [c for c in two if close_ts - 86400 < c["ts"] <= close_ts]
    spreads = [round(c["ask"] - c["bid"], 4) for c in two]
    return {"candles": len(cs), "two_sided": len(two), "life_hours": int(life_h), "two_sided_share_of_life": round(len(two) / life_h, 4),
            "two_sided_hours_last24": len(last24), "median_spread": statistics.median(spreads) if spreads else None,
            "first_ts": cs[0]["ts"] if cs else None, "last_ts": cs[-1]["ts"] if cs else None,
            "ts_monotonic": all(a["ts"] < b["ts"] for a, b in zip(cs, cs[1:])), "traded_hours": sum(1 for c in cs if (c["volume"] or 0) > 0)}


def sample_markets(rows: list[dict], per_month: int) -> list[dict]:
    """Deterministic stratified sample: up to ``per_month`` settled yes/no markets per close month, chosen by sha256(ticker) order (pure)."""
    by = defaultdict(list)
    for r in rows:
        if r.get("result") in ("yes", "no") and r.get("open_time") and r.get("close_time"):
            by[r["close_time"][:7]].append(r)
    out = []
    for m in sorted(by):
        out += sorted(by[m], key=lambda r: hashlib.sha256(r["ticker"].encode()).hexdigest())[:per_month]
    return out


def fetch(settlements_cache: Path, cache_dir: Path, series: str, per_month: int, max_calls: int = 60, pause: float = 3.0,
          cutoff_ts: int | None = None, opener=urllib.request.urlopen, sleep=time.sleep) -> dict:
    if not 1 <= max_calls <= HARD_MAX_CALLS:
        raise ValueError(f"max_calls must be in 1..{HARD_MAX_CALLS}")
    pause = max(float(pause), MIN_PAUSE)
    out = _outside_repo(cache_dir) / series
    out.mkdir(parents=True, exist_ok=True)
    picks = sample_markets(load_rows(settlements_cache, series), per_month)
    calls, log = 0, []
    for r in picks:
        p = out / f"{r['ticker']}.json.gz"
        if p.exists():
            continue
        if calls >= max_calls:
            log.append({"stop": "max_calls_reached"}); break
        hist = r.get("source") == "historical" if cutoff_ts is None else iso_ts(r["close_time"]) < cutoff_ts
        url = candle_url(series, r["ticker"], iso_ts(r["open_time"]) - 3600, iso_ts(r["close_time"]) + 3600, hist)
        n429, body = 0, None
        while True:
            calls += 1
            try:
                with opener(urllib.request.Request(url, headers=UA), timeout=60) as resp:
                    body = resp.read()
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and n429 < MAX_429:
                    log.append({"status": 429, "backoff_s": BACKOFF_429[n429]}); sleep(BACKOFF_429[n429]); n429 += 1; continue
                log.append({"ticker": r["ticker"], "status": e.code, "stop": "http_error"}); body = None; break
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                log.append({"ticker": r["ticker"], "stop": f"transport:{type(e).__name__}"}); body = None; break
        if body is None:
            break
        meta = {"ticker": r["ticker"], "open_time": r["open_time"], "close_time": r["close_time"], "result": r.get("result"), "historical": hist}
        p.write_bytes(gzip.compress(json.dumps({"meta": meta, "payload": json.loads(body)}).encode(), mtime=0))
        log.append({"ticker": r["ticker"], "status": 200, "sha256": hashlib.sha256(body).hexdigest()})
        sleep(pause)
    meta = {"series": series, "picked": len(picks), "calls": calls, "retrieved_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "log": log}
    with open(out / "calls.jsonl", "a") as f:
        f.write(json.dumps(meta) + "\n")
    return meta


def ledger(cache_dir: Path) -> dict:
    res = {}
    for d in sorted(p for p in Path(cache_dir).iterdir() if p.is_dir() and SERIES_RE.match(p.name)):
        per = []
        for f in sorted(d.glob("*.json.gz")):
            js = json.loads(gzip.decompress(f.read_bytes()))
            m = js["meta"]
            s = market_quote_stats(js["payload"].get("candlesticks") or [], iso_ts(m["open_time"]), iso_ts(m["close_time"]))
            per.append(m | s | {"file_sha256": hashlib.sha256(f.read_bytes()).hexdigest()})
        if not per:
            continue
        def med(k):
            v = [x[k] for x in per if x[k] is not None]
            return statistics.median(v) if v else None
        res[d.name] = {"markets_sampled": len(per), "with_any_candle": sum(x["candles"] > 0 for x in per),
                       "with_two_sided_quote": sum(x["two_sided"] > 0 for x in per), "with_two_sided_in_last24h": sum(x["two_sided_hours_last24"] > 0 for x in per),
                       "historical_endpoint": sum(x["historical"] for x in per), "ts_monotonic": sum(x["ts_monotonic"] for x in per),
                       "median_two_sided_share_of_life": med("two_sided_share_of_life"), "median_two_sided_hours_last24": med("two_sided_hours_last24"),
                       "median_spread": med("median_spread"), "close_month_span": [min(x["close_time"][:7] for x in per), max(x["close_time"][:7] for x in per)],
                       "per_market": [{k: x[k] for k in ("ticker", "close_time", "historical", "candles", "two_sided", "two_sided_hours_last24", "median_spread", "file_sha256")} for x in per]}
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch"); f.add_argument("--settlements-cache", required=True); f.add_argument("--cache-dir", required=True)
    f.add_argument("--series", required=True); f.add_argument("--per-month", type=int, default=3); f.add_argument("--max-calls", type=int, default=60)
    f.add_argument("--pause", type=float, default=3.0); f.add_argument("--cutoff-ts", type=int)
    l = sub.add_parser("ledger"); l.add_argument("--cache-dir", required=True); l.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        m = fetch(Path(a.settlements_cache), Path(a.cache_dir), a.series, a.per_month, a.max_calls, a.pause, a.cutoff_ts)
        print(json.dumps({k: m[k] for k in ("series", "picked", "calls")} | {"last": m["log"][-1] if m["log"] else None})); return 0
    Path(a.out).write_text(json.dumps(ledger(Path(a.cache_dir)), indent=1, sort_keys=True)); return 0


if __name__ == "__main__":
    sys.exit(main())
