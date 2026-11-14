"""Live Kalshi sports listing vs the registry: which market types are supported, new, or out of scope (RESEARCH_ONLY).

Source: the public, unauthenticated ``GET /trade-api/v2/series?category=Sports`` listing (series-level metadata only: title, tags, fee
type/multiplier, settlement sources). It lists *series*, not contracts: it says what kinds of markets exist, not how many are open or
settled. A series is "known" if its literal ticker already appears anywhere under ``research/audit`` (registry, inventory, snapshots).
"""
from __future__ import annotations

import collections
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research/input_research/market_universe"
URL = "https://api.elections.kalshi.com/trade-api/v2/series?category=Sports"

# ticker prefix -> supported sport (the eight sports in scope). Order matters: first match wins.
SPORT_PREFIX = [
    ("KXNFL", "NFL"), ("KXNCAAF", "CFB"), ("KXNBA", "NBA"), ("KXNCAAMB", "CBB"), ("KXMARMAD", "CBB"), ("KXNHL", "NHL"),
    ("KXMLB", "MLB"), ("KXATP", "TENNIS"), ("KXWTA", "TENNIS"), ("KXTENNIS", "TENNIS"),
]
SOCCER_HINT = re.compile(r"SOCCER|BUNDES|LALIGA|SERIEA|SERIEC|LIGUE1|EPL|UCL|MLS|CLUBWC|UEFA|CONMEB|CONCAC|COPA|FIFA|WORLDCUP|BRASIL|LIGAMX|LIGAPO|EFL|DFB|ESPSUP|ITASUP|FRASUP|COUPE|FA CUP|FACUP", re.I)
OTHER_TAGS = {"Golf", "Motorsport", "Cricket", "MMA", "UFC", "Esports", "Boxing", "Rugby", "Chess", "Olympics", "Lacrosse", "Cycling",
              "Table Tennis", "Volleyball", "Squash", "Darts", "Aussie Rules", "Rowing", "Video games"}
# market "mechanism class" from ticker/title keywords (coarse, for scoping research; the registry taxonomy stays authoritative)
KIND = [
    ("player_prop", r"PASSYDS|RECYDS|RUSHYDS|PASSTD|RECTD|RUSHTD|\bREC\b|RECEPT|PTS|REB|AST|3PT|STEAL|BLOCK|SOG|SAVE|STRIKEOUT|HRD|HIT|TB|GOAL(SCORER)?|ANYTIME|SCORER|1STTD|FIRSTTD|LADDER|ESCALATOR|PRECISE|FANTASY"),
    ("total", r"TOTAL|OVER|POINTS?$"), ("spread", r"SPREAD|HANDICAP|WINMARGIN|MARGIN"), ("winner", r"GAME$|WINNER|MATCH$|H2H|MONEYLINE|ML$"),
    ("team_event", r"TEAMTD|FIRSTTDTEAM|TEAMTOTAL|1HTD|TIE|OT|SAFETY|1YD|2PT|FIRST|BTTS|CORNER|CARD|PENALT"),
    ("season_outcome", r"WINS|PLAYOFF|CHAMP|DIV|CONF|SEED|SERIES|FINAL|CUP|MVP|ROTY|ROOKIE|AWARD|DRAFT|COTY|LEADER|OROY|DROY|ALLPRO|EXACTWIN"),
]


def sport_of(s: dict) -> str:
    t, tags = s["ticker"].upper(), set(s.get("tags") or [])
    for p, sp in SPORT_PREFIX:
        if t.startswith(p):
            return sp
    if tags & {"Soccer"} or SOCCER_HINT.search(t):
        return "SOCCER"
    if tags & OTHER_TAGS:
        return "OTHER_SPORT:" + sorted(tags & OTHER_TAGS)[0]
    if tags:
        return "OTHER_LEAGUE_OR_SEASON:" + sorted(tags)[0]
    return "UNSCOPED"


def kind_of(s: dict) -> str:
    t = s["ticker"].upper().replace("KX", "", 1)
    for k, rx in KIND:
        if re.search(rx, t):
            return k
    return "other_or_unclassified"


def known_series() -> set[str]:
    known: set[str] = set()
    rx = re.compile(r'"(KX[A-Z0-9\-]{2,})"')
    for p in (ROOT / "research/audit").rglob("*.json"):
        if "input_research" in p.parts:
            continue
        known |= set(rx.findall(p.read_text(errors="ignore")))
    return known


def fetch() -> list[dict]:
    req = urllib.request.Request(URL, headers={"User-Agent": "sift-alpha-research/1"})
    return json.load(urllib.request.urlopen(req, timeout=60))["series"]


def slim(s: dict) -> dict:
    return {k: s.get(k) for k in ("ticker", "title", "tags", "frequency", "fee_type", "fee_multiplier", "settlement_sources", "contract_terms_url")}


def build(series: list[dict], known: set[str]) -> dict:
    rows = []
    for s in series:
        sp = sport_of(s)
        rows.append({"ticker": s["ticker"], "title": s.get("title"), "sport": sp, "kind": kind_of(s), "frequency": s.get("frequency"),
                     "fee_type": s.get("fee_type"), "fee_multiplier": s.get("fee_multiplier"),
                     "registry": "KNOWN" if s["ticker"] in known else "NEW"})
    by = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        sup = r["sport"] in {"NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"}
        by[r["sport"]]["series"] += 1
        by[r["sport"]]["known_in_registry"] += r["registry"] == "KNOWN"
        by[r["sport"]]["new_unregistered"] += r["registry"] == "NEW"
        by[r["sport"]]["in_scope"] += sup
        by[r["sport"]]["kind:" + r["kind"]] += 1
    new_by_kind = collections.Counter((r["sport"], r["kind"]) for r in rows
                                      if r["registry"] == "NEW" and not r["sport"].startswith(("OTHER", "UNSCOPED")))
    return {"schema_version": "market-universe-1.0", "status": "RESEARCH_ONLY", "n_series": len(rows),
            "caveat": "Series-level only: a series is a grouping, not a contract; no per-contract counts, no open/settled split, no settlement-rule review. "
                      "sport/kind are ticker-keyword heuristics for scoping, not the registry taxonomy. NEW means the literal ticker is absent from research/audit.",
            "by_sport": {k: dict(v) for k, v in sorted(by.items())},
            "new_in_scope_by_kind": [{"sport": a, "kind": b, "series": n} for (a, b), n in new_by_kind.most_common()],
            "rows": rows}


def main(argv=None):
    argv = argv or sys.argv[1:]
    series = json.load(open(argv[0]))["series"] if argv else fetch()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "live_series_snapshot.json").write_text(json.dumps([slim(s) for s in series], sort_keys=True, indent=0))
    res = build(series, known_series())
    summ = {k: res[k] for k in ("schema_version", "status", "n_series", "caveat", "by_sport", "new_in_scope_by_kind")}
    summ["snapshot_date"] = __import__("datetime").date.today().isoformat()
    (OUT / "universe_summary.json").write_text(json.dumps(summ, sort_keys=True, indent=0))
    for k, v in res["by_sport"].items():
        print(f"{k:28s} series={v['series']:5d} known={v.get('known_in_registry',0):5d} new={v.get('new_unregistered',0):5d}")
    return res


if __name__ == "__main__":
    main()
