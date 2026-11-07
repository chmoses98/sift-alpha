"""Sample actual Kalshi contract rules (rules_primary / rules_secondary of one market per series) so classification rests on settlement text, not title keywords (RESEARCH_ONLY).

Public API, no credentials. One market per series: enough to read the contract definition (what settles YES, which period, which stat, overtime handling), not to count contracts.
Output: research/input_research/market_universe/contract_rules_sample.json (text trimmed to 600 chars each).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research/input_research/market_universe/contract_rules_sample.json"
B = "https://api.elections.kalshi.com/trade-api/v2"


def _get(path, tries=8):
    for i in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(B + path, headers={"User-Agent": "sift-alpha-research/1"}), timeout=45))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 + 3 * i); continue
            if e.code == 404:
                return None
            raise
    return None


def sample(tickers: list[str], existing: dict | None = None, pause: float = 1.3, flush_every: int = 20) -> dict:
    out = dict(existing or {})
    for i, t in enumerate(tickers):
        if t in out:
            continue
        if i and i % flush_every == 0:
            OUT.write_text(json.dumps(out, indent=0, sort_keys=True)); print(len(out), "sampled", flush=True)
        d = _get(f"/markets?series_ticker={t}&limit=1")
        m = (d or {}).get("markets") or []
        if not m:
            out[t] = {"status": "NO_MARKETS_LISTED"}
        else:
            m = m[0]
            out[t] = {"status": m.get("status"), "market_type": m.get("market_type"), "title": m.get("title"), "yes_sub_title": m.get("yes_sub_title"), "strike_type": m.get("strike_type"),
                      "floor_strike": m.get("floor_strike"), "rules_primary": (m.get("rules_primary") or "")[:600], "rules_secondary": (m.get("rules_secondary") or "")[:600], "ticker": m.get("ticker")}
        time.sleep(pause)
    return out


def main(tickers_file: str):
    tickers = json.loads(Path(tickers_file).read_text())
    ex = json.loads(OUT.read_text()) if OUT.exists() else {}
    res = sample(tickers, ex)
    OUT.write_text(json.dumps(res, indent=0, sort_keys=True))
    print(len(res), "series sampled;", sum(1 for v in res.values() if v.get("status") == "NO_MARKETS_LISTED"), "with no market listed")


if __name__ == "__main__":
    import sys
    main(sys.argv[1])
