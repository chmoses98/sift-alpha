"""Review MLB player-prop disagreements (official Kalshi vs edge-finder-api computed) against the vault box score.

RESEARCH_ONLY, read-only. Three layers are reported side by side and never merged:
  official  - Kalshi `result` / `expiration_value` (vault kalshi_official_settlements)
  computed  - edge-finder-api `data/edgelab/settlements` (`settlementEvidence.actualValue`, fetched at settle time)
  box_final - the vault's MLB Stats API postgame feed (collected 2026-11-16, i.e. after any stat correction)

Usage:
  python scripts/research/mlb_prop_review.py --tickers research/settlement_reconcile/MLB.json \
      --official <restored vault MLB official dir> --computed <edge-finder-api>/data/edgelab/settlements \
      --feed <restored vault MLB postgame_feed_compact 2026 dir> --out research/settlement_reconcile/mlb_prop_review.json
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import re

STAT = {"KXMLBHIT": ("hits",), "KXMLBRBI": ("rbi",), "KXMLBSB": ("stolenBases",), "KXMLBTB": ("totalBases",),
        "KXMLBHRR": ("hits", "runs", "rbi")}


def _official(root, tickers):
    out = {}
    for path in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
        series = os.path.basename(path).split(".")[0]
        if series not in STAT:
            continue
        with open(path) as fh:
            for line in fh:
                if not any(t in line for t in tickers):
                    continue
                r = json.loads(line)
                if r.get("ticker") in tickers:
                    out[r["ticker"]] = r
    return out


def _computed(root, tickers):
    out = {}
    for path in sorted(glob.glob(os.path.join(root, "*.jsonl.gz"))):
        with gzip.open(path, "rt") as fh:
            for line in fh:
                if any(t in line for t in tickers):
                    r = json.loads(line)
                    if r.get("marketTicker") in tickers:
                        out[r["marketTicker"]] = r       # latest file wins (append-only by date)
    return out


def _box_value(feed_dir, game_pk, player_id, stats):
    path = os.path.join(feed_dir, f"{game_pk}.json")
    if not os.path.exists(path):
        return None, "feed missing"
    d = json.load(open(path))
    for side in ("home", "away"):
        for p in d["box"][side]["players"]:
            if p["id"] == int(player_id):
                bat = p.get("bat") or {}
                if not bat:
                    return None, "player has no batting line"
                return sum(int(bat.get(s, 0)) for s in stats), None
    return None, "player not in box"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", required=True)
    ap.add_argument("--official", required=True)
    ap.add_argument("--computed", required=True)
    ap.add_argument("--feed", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    tickers = set(json.load(open(a.tickers))["with_overlay"]["remaining_tickers"])
    off, comp = _official(a.official, tickers), _computed(a.computed, tickers)
    rows, causes = [], {}
    for t in sorted(tickers):
        series = t.split("-")[0]
        o, c = off.get(t, {}), comp.get(t, {})
        ev = c.get("settlementEvidence") or {}
        m = re.search(r":\s*(-?\d+)", o.get("expiration_value") or "")
        ex_val = int(m.group(1)) if m else None
        box, why = (None, "no computed gamePk/playerId")
        if ev.get("gamePk") and ev.get("playerId"):
            box, why = _box_value(a.feed, ev["gamePk"], ev["playerId"], STAT[series])
        strike = o.get("floor_strike")
        box_side = None if box is None or strike is None else ("yes" if box > strike else "no")
        if box is None:
            cause = "UNRESOLVED_" + why.upper().replace(" ", "_")
        elif ex_val is not None and box == ex_val and ev.get("actualValue") != box:
            cause = "ENGINE_STALE_STAT_CORRECTED_AFTER_SETTLE"     # box changed after the engine fetched it
        elif box_side == o.get("result") and ev.get("actualValue") == box:
            cause = "ENGINE_SIDE_DEFECT"
        elif box_side != o.get("result"):
            cause = "EXCHANGE_DIFFERS_FROM_FINAL_BOX"
        else:
            cause = "OTHER"
        causes[cause] = causes.get(cause, 0) + 1
        rows.append({"ticker": t, "series": series, "official_result": o.get("result"),
                     "official_expiration_value": o.get("expiration_value"), "floor_strike": strike,
                     "computed_outcome": c.get("outcome"), "computed_value": ev.get("actualValue"),
                     "computed_fetched_at": ev.get("fetchedAt"), "gamePk": ev.get("gamePk"), "playerId": ev.get("playerId"),
                     "box_final_value": box, "box_final_side": box_side, "cause": cause})
    out = {"schema": "mlb-prop-review-1.0", "status": "RESEARCH_ONLY",
           "notice": "Agent-run, not human verified. Layers kept separate; no record rewritten.",
           "box_source": "vault MLB postgame_feed_compact 2026 collected-20261116", "n": len(rows), "causes": causes, "rows": rows}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(out, open(a.out, "w"), indent=1, sort_keys=True)
    print(json.dumps(causes))


if __name__ == "__main__":
    main()
