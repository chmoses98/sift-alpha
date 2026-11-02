"""Resumable, rate-limited Kalshi public-market sweep for a queue of series tickers.

Only aggregates are persisted (counts by status, event count, open-time range, sample ticker/title/rules) - never
fabricated: a (series, status) pair is `complete` only when pagination reached an empty cursor. HTTP 429 honours
Retry-After with bounded backoff; when retries are exhausted or the request budget is spent the run stops and the
state file resumes exactly at the saved cursor.  Usage:
  python -m alpha_engine.series_sweep QUEUE.json STATE.json [--max-requests N] [--min-interval S]
QUEUE.json: {"series": ["KXMLBGAME", ...]}   Exit codes: 0 all complete, 3 stopped early (resume later)."""
import argparse, json, sys, time
import urllib.error, urllib.parse, urllib.request

BASE = "https://api.elections.kalshi.com/trade-api/v2/markets"
STATUSES = ("open", "unopened", "closed", "settled")


def http_fetch(series, status, cursor):
    q = {"series_ticker": series, "status": status, "limit": 1000}
    if cursor:
        q["cursor"] = cursor
    req = urllib.request.Request(BASE + "?" + urllib.parse.urlencode(q), headers={"User-Agent": "SIFT-Alpha-sweep/1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.load(r), {}
    except urllib.error.HTTPError as e:
        return e.code, {}, {"Retry-After": e.headers.get("Retry-After")}


class Sweeper:
    def __init__(self, fetch, state, *, sleep=time.sleep, max_requests=500, min_interval=0.25, retries=4, max_wait=60):
        self.fetch, self.state, self.sleep = fetch, state, sleep
        self.max_requests, self.min_interval, self.retries, self.max_wait = max_requests, min_interval, retries, max_wait
        self.used = 0

    def _get(self, s, st, cur):
        for attempt in range(self.retries + 1):
            if self.used >= self.max_requests:
                return None
            self.used += 1; self.state["requests_total"] = self.state.get("requests_total", 0) + 1
            code, body, hdr = self.fetch(s, st, cur)
            if code == 200:
                self.sleep(self.min_interval); return body
            if code == 429:
                self.state.setdefault("rate_limited", 0); self.state["rate_limited"] += 1
                ra = hdr.get("Retry-After")
                self.sleep(min(self.max_wait, float(ra) if ra else 2 ** attempt)); continue
            self.state.setdefault("errors", []).append({"series": s, "status": st, "http": code}); return {"_error": code}
        return None

    def run(self, queue):
        res = self.state.setdefault("series", {})
        for s in queue:
            for st in STATUSES:
                e = res.setdefault(s, {}).setdefault(st, {"complete": False, "markets": 0, "cursor": None, "events": [], "open_time_min": None, "open_time_max": None})
                if e["complete"]:
                    continue
                while True:
                    body = self._get(s, st, e["cursor"])
                    if body is None:
                        return False
                    if "_error" in body:
                        e["error"] = body["_error"]; break
                    ms = body.get("markets", [])
                    e["markets"] += len(ms)
                    evs = set(e["events"]) | {m.get("event_ticker") for m in ms if m.get("event_ticker")}
                    e["events"] = sorted(evs)[:50]; e["event_count"] = len(evs) if len(evs) < 50 else max(e.get("event_count", 0), 50)
                    for m in ms:
                        ot = m.get("open_time")
                        if ot:
                            e["open_time_min"] = min(filter(None, [e["open_time_min"], ot])); e["open_time_max"] = max(filter(None, [e["open_time_max"], ot]))
                        if "sample" not in e:
                            e["sample"] = {"ticker": m.get("ticker"), "title": m.get("title"), "rules_primary": (m.get("rules_primary") or "")[:300]}
                    e["cursor"] = body.get("cursor") or None
                    if not e["cursor"]:
                        e["complete"] = True; e.pop("error", None); break
        return True


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("queue"); ap.add_argument("state")
    ap.add_argument("--max-requests", type=int, default=500, choices=range(1, 1001), metavar="1-1000"); ap.add_argument("--min-interval", type=float, default=0.25)
    a = ap.parse_args(argv)
    q = json.load(open(a.queue))["series"]
    try:
        state = json.load(open(a.state))
    except FileNotFoundError:
        state = {"queue": a.queue}
    done = Sweeper(http_fetch, state, max_requests=a.max_requests, min_interval=a.min_interval).run(q)
    json.dump(state, open(a.state, "w"), indent=1)
    print("complete" if done else "stopped early; rerun to resume", "requests", state.get("requests_total"))
    return 0 if done else 3


if __name__ == "__main__":
    sys.exit(main())
