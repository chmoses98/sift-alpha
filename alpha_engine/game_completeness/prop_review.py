"""Independent review of player-prop settlement disagreements (MANUAL, RESEARCH_ONLY, read-only).

Input: a sport's computed settlements (ticker, game_id, outcome, value, reason) and Kalshi's official results.
For every contract where the engine's YES/NO differs from the exchange's, the league's CURRENT box score is read
again and the disagreement is classified:

  league_corrected_after_engine_read   the league figure changed since the engine read it, and the current figure
                                       gives the exchange's result: the engine read early, the exchange is right
  exchange_differs_from_league         the league still shows the engine's figure: the exchange settled on a
                                       different number than the league's box score
  league_changed_but_still_disagrees   the league figure changed, yet the current figure still gives the engine's result
  not_reviewable                       player / stat / threshold could not be resolved (reason recorded)

NHL only for now (api-web.nhle.com boxscore, matched by team abbreviation + sweater number from the ticker).
Output: counts and contract identifiers with the engine's and the league's figures.  No official row is written;
the exchange's side appears only as the classification.

    python -m alpha_engine.game_completeness.prop_review NHL --official LIVE/NHL HIST/NHL \
        --computed 'DA/settlements/*/*.jsonl.gz' --cache CACHE --as-of <ts> --out research/game_completeness/prop_review_NHL.json
"""
import argparse
import json
import re
import time
import urllib.request
from collections import Counter
from pathlib import Path

from .kalshi_official import _computed_rows, load_official

NHL_BOX = "https://api-web.nhle.com/v1/gamecenter/{}/boxscore"
REASON_RE = re.compile(r"^(\w+)=(-?\d+(?:\.\d+)?) (gt|ge|lt|le) (-?\d+(?:\.\d+)?)")
PLAYER_RE = re.compile(r"^([A-Z]{2,3})[A-Z'.]+?(\d{1,2})$")
OPS = {"gt": lambda v, t: v > t, "ge": lambda v, t: v >= t, "lt": lambda v, t: v < t, "le": lambda v, t: v <= t}


def parse_reason(reason):
    """'saves=27 gt 25.5 (team+jersey+name)' -> ('saves', 27.0, 'gt', 25.5) or None."""
    m = REASON_RE.match(reason or "")
    return (m[1], float(m[2]), m[3], float(m[4])) if m else None


def parse_player(ticker):
    """'KXNHLSAVE-26NOV14WPGCHI-CHISKNIGHT30-26' -> ('CHI', 30) or None."""
    parts = ticker.split("-")
    m = PLAYER_RE.match(parts[2]) if len(parts) >= 3 else None
    if not m:
        return None
    teams = parts[1][7:]
    for n in (3, 2):                                     # the team prefix must be one of the two teams in the event
        if teams.startswith(m[0][:n]) or teams.endswith(m[0][:n]):
            return m[0][:n], int(m[2])
    return None


def nhl_stat(box, team, sweater, stat):
    """Current league figure for one player, or (None, reason)."""
    for side in ("awayTeam", "homeTeam"):
        if not ((box.get(side) or {}).get("abbrev") or "").startswith(team):   # exchange 'LA' / league 'LAK'
            continue
        groups = (box.get("playerByGameStats") or {}).get(side) or {}
        hits = [p for g in ("forwards", "defense", "goalies") for p in groups.get(g, [])
                if p.get("sweaterNumber") == sweater and stat in p]
        if len(hits) != 1:
            return None, f"{len(hits)} players with sweater {sweater} carrying '{stat}'"
        return float(hits[0][stat]), None
    return None, f"team {team} not in box score"


def fetch_box(game_id, cache, opener=urllib.request.urlopen, pause=0.5):
    f = Path(cache) / f"nhl_box_{game_id}.json"
    if f.exists():
        return json.loads(f.read_text())
    req = urllib.request.Request(NHL_BOX.format(game_id), headers={"User-Agent": "research-readonly"})
    with opener(req, timeout=60) as r:
        box = json.loads(r.read())
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(box))
    time.sleep(pause)
    return box


def classify(row, official_result, league_value):
    """row: computed settlement; official_result: 'yes'|'no'; league_value: current league figure."""
    stat, engine_value, op, threshold = parse_reason(row["reason"])
    league_outcome = "yes" if OPS[op](league_value, threshold) else "no"
    if league_value == engine_value:
        return "exchange_differs_from_league"
    return "league_corrected_after_engine_read" if league_outcome == official_result else "league_changed_but_still_disagrees"


def review(official, computed_rows, box_for):
    """official: {ticker: row}; computed_rows: {ticker: latest computed row}; box_for: game_id -> box score."""
    counts, items = Counter(), []
    for t in sorted(computed_rows):
        row = computed_rows[t]
        res = ((official.get(t) or {}).get("result") or "").lower()
        if row.get("outcome") not in ("YES", "NO") or res not in ("yes", "no") or res == row["outcome"].lower():
            continue
        item = {"ticker": t, "game_id": row.get("game_id"), "engine_value": row.get("value")}
        parsed, player = parse_reason(row.get("reason")), parse_player(t)
        if not parsed or not player:
            item["class"], item["why"] = "not_reviewable", "reason or player not parseable"
        else:
            value, why = nhl_stat(box_for(row["game_id"]), player[0], player[1], parsed[0])
            if value is None:
                item["class"], item["why"] = "not_reviewable", why
            else:
                item["league_value_now"], item["class"] = value, classify(row, res, value)
        counts[item["class"]] += 1
        counts[f"{t.split('-')[0]}:{item['class']}"] += 1
        items.append(item)
    return {"disagreements": len(items), "counts": dict(sorted(counts.items())), "items": items}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sport", choices=["NHL"])
    ap.add_argument("--official", nargs="+", required=True)
    ap.add_argument("--computed", required=True)
    ap.add_argument("--cache", required=True, help="scratch folder for re-fetched box scores")
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    official = {}
    for folder in a.official:
        official.update(load_official(folder))
    doc = {"schema": "prop-settlement-review-1.0", "sport": a.sport, "as_of": a.as_of,
           "notice": "Agent-run, not human verified. Identifiers, engine figures and current league figures only.",
           **review(official, _computed_rows(a.computed), lambda gid: fetch_box(gid, a.cache))}
    Path(a.out).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"disagreements": doc["disagreements"], "counts": doc["counts"]}, indent=1))


if __name__ == "__main__":
    main()
