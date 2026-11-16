"""Independent check of Kalshi's settlement VALUES for CFB and CBB game markets (MANUAL, RESEARCH_ONLY, read-only).

CFB and CBB keep no computed-settlement archive, so `kalshi_official compare` has nothing to join.  Kalshi's settled
market rows carry `expiration_value`: the figure the exchange settled on (total points, winning margin, winner name,
"Home: h, Away: a", overtime 0/1).  This module recomputes each figure from an independent box score and compares:

  * CFB: cfb-edge-finder `data/football/<season>/{schedule.json,team_games.jsonl}` (owner-held, ESPN-derived)
  * CBB: ESPN scoreboard JSON per day (`sb_<yyyymmdd>.json`), fetched by the operator

Join: Kalshi event suffix `<yy><MON><dd><AWAY><HOME>` to a game by Eastern date and the two ESPN abbreviations;
where Kalshi's abbreviation differs, by the official winner NAME plus one matching abbreviation.  A game that does not
resolve to exactly one candidate is left unjoined and counted, never guessed.

Second-half markets are compared under both readings (regulation only / including overtime) and the reading that
matched is reported per game date, because the exchange changed that rule mid-season (docs/KALSHI_OFFICIAL_ARCHIVE.md).

Output holds counts, event identifiers and this module's OWN computed figures only: no official row is written.

    python -m alpha_engine.game_completeness.official_values CFB --official LIVE/CFB HIST/CFB \
        --cfb-season-dir ../cfb-edge-finder/data/football/2026 --out research/game_completeness/official_values_CFB.json
    python -m alpha_engine.game_completeness.official_values CBB --official LIVE/CBB --espn-scoreboards DIR --out ...
"""
import argparse
import glob
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PREFIX = {"CFB": "KXNCAAF", "CBB": "KXNCAAMB"}
REGULATION = {"CFB": 4, "CBB": 2}
SERIES_RE = re.compile(r"^(?:(\d)([QH]))?(GAME|TOTAL|SPREAD|TEAMTOTAL|OT|)$")
EVENT_RE = re.compile(r"^(\d{2}[A-Z]{3}\d{2})([A-Z0-9&]+)$")


def classify_series(sport, series):
    """'KXNCAAF2HTOTAL' -> ('2H', 'TOTAL'); full game -> ('FG', kind); unknown -> None."""
    if not series.startswith(PREFIX[sport]):
        return None
    m = SERIES_RE.match(series[len(PREFIX[sport]):])
    if not m:
        return None
    n, unit, kind = m.groups()
    if n is None:
        return ("FG", kind) if kind else None
    return (n + unit, kind or "GAME")


def norm_name(s):
    s = re.sub(r"\s+wins\b.*$", "", s or "")                 # "Ohio St. wins 1st Half" -> "Ohio St."
    s = re.sub(r"\s*\([^)]*\)", "", s)                       # "Miami (FL)" -> "Miami"
    s = re.sub(r"\bst\.?(?=\s|$)", "state", s.lower().replace("&", "and"))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def period_points(sport, periods_away, periods_home, period, include_ot=True):
    """(away, home) points in a market period, or None when the box score lacks it."""
    reg = REGULATION[sport]
    if len(periods_away) < reg or len(periods_home) < reg or len(periods_away) != len(periods_home):
        return None
    a, h = list(periods_away), list(periods_home)
    if period == "FG":
        return sum(a), sum(h)
    n, unit = int(period[0]), period[1]
    if (unit == "Q" and sport == "CFB") or (unit == "H" and sport == "CBB"):
        lo, hi = n - 1, n
    elif unit == "H" and sport == "CFB":
        lo, hi = 2 * (n - 1), 2 * n
    else:
        return None
    if unit == "H" and n == 2 and include_ot:              # only the second HALF can carry overtime; 4Q never does
        hi = len(a)
    return sum(a[lo:hi]), sum(h[lo:hi])


def official_events(folders, sport):
    """({event_suffix: {series: Counter(expiration_value)}}, {event_suffix: {series: [(strike, 'yes'|'no')]}})
    from kalshi_official output folders.  Strikes are kept for total ladders only (integer ticker suffix)."""
    ev = defaultdict(lambda: defaultdict(Counter))
    ladders = defaultdict(lambda: defaultdict(list))
    seen = set()  # a contract served by both the historical and the live tier is counted once
    for folder in folders:
        for f in sorted(glob.glob(str(Path(folder) / "*.jsonl"))):
            for line in open(f, encoding="utf-8"):
                r = json.loads(line)
                if r.get("result") not in ("yes", "no") or r["ticker"] in seen:
                    continue
                seen.add(r["ticker"])
                series, _, suffix = r["event_ticker"].partition("-")
                cls = classify_series(sport, series)
                if cls:
                    ev[suffix][series][r.get("expiration_value")] += 1
                    strike = r["ticker"].rsplit("-", 1)[-1]
                    if cls[1] == "TOTAL" and strike.isdigit():
                        fs = r.get("floor_strike")   # the exchange's own strike: present in vault rows
                        ladders[suffix][series].append((int(strike), r["result"], float(fs)) if isinstance(fs, (int, float))
                                                       else (int(strike), r["result"]))
    return ev, ladders


def _game(gid, date_utc, away, home):
    t = datetime.fromisoformat(date_utc.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return {"id": str(gid), "start": t, "away": away, "home": home}


def load_cfb(season_dir):
    """Final games with per-period points for both teams from the owner's committed season files."""
    d = Path(season_dir)
    tg = defaultdict(dict)
    for line in open(d / "team_games.jsonl", encoding="utf-8"):
        r = json.loads(line)
        tg[str(r["game_id"])][str(r["team_id"])] = r
    out = []
    for e in json.loads((d / "schedule.json").read_text())["events"]:
        if not e.get("completed"):
            continue
        side = {}
        for c in e["competitors"]:
            row = tg.get(str(e["id"]), {}).get(str(c["team_id"]))
            pp = (row or {}).get("period_points")
            side[c["home_away"]] = {"abbr": (c.get("abbreviation") or "").upper(), "score": int(float(c["score"])),
                                    "names": {norm_name(n) for n in [c.get("location")] + list(c.get("names") or [])},
                                    "periods": [int(x) for x in pp] if pp else []}
        if set(side) == {"home", "away"}:
            out.append(_game(e["id"], e["date"], side["away"], side["home"]))
    return out


def load_espn_scoreboards(folder):
    out = {}
    for f in sorted(glob.glob(str(Path(folder) / "sb_*.json"))):
        for e in json.loads(Path(f).read_text()).get("events", []):
            if not ((e.get("status") or {}).get("type") or {}).get("completed"):
                continue
            side = {}
            for c in e["competitions"][0]["competitors"]:
                t = c["team"]
                names = [t.get("location"), t.get("displayName"), t.get("shortDisplayName"), t.get("name")]
                side[c["homeAway"]] = {"abbr": (t.get("abbreviation") or "").upper(), "score": int(c["score"]),
                                       "names": {norm_name(n) for n in names if n},
                                       "periods": [int(x["value"]) for x in c.get("linescores") or []]}
            if set(side) == {"home", "away"}:
                out[str(e["id"])] = _game(e["id"], e["date"], side["away"], side["home"])
    return list(out.values())


def load_espn_summaries(folders, since="2025-07-01"):
    """Final games from archived ESPN game summaries (private vault `espn_summary_postgame`), one JSON per game.
    Same fields as the scoreboard loader, read from `header.competitions[0]`.  `since` skips games that predate
    the exchange's first contracts so a decade of files is not parsed for nothing."""
    out = {}
    for folder in folders:
        for f in sorted(glob.glob(str(Path(folder) / "*.json"))):
            try:
                comp = json.loads(Path(f).read_text())["header"]["competitions"][0]
            except (ValueError, KeyError, IndexError, TypeError):
                continue
            if (comp.get("date") or "") < since or not ((comp.get("status") or {}).get("type") or {}).get("completed"):
                continue
            side = {}
            for c in comp.get("competitors") or []:
                t = c.get("team") or {}
                names = [t.get("location"), t.get("displayName"), t.get("shortDisplayName"), t.get("name"), t.get("nickname")]
                try:
                    side[c["homeAway"]] = {"abbr": (t.get("abbreviation") or "").upper(), "score": int(c["score"]),
                                           "names": {norm_name(n) for n in names if n},
                                           "periods": [int(x["displayValue"]) for x in c.get("linescores") or []]}
                except (KeyError, TypeError, ValueError):
                    side = {}
                    break
            if set(side) == {"home", "away"}:
                out[str(comp["id"])] = _game(comp["id"], comp["date"], side["away"], side["home"])
    return list(out.values())


_LINESCORE_RE = re.compile(r"'value':\s*([0-9.]+)")


def load_sdv_schedules(folder, since="2025-01-01"):
    """Final games from SportsDataverse ESPN schedule parquet files (private vault `espn_team_box_schedules`).
    Period scores come from the schedule's own linescore column; a game without one keeps its final score and
    its period markets are counted as `no_period_scores`, never guessed."""
    import pandas as pd
    cols = ["game_id", "date", "status_type_completed", "home_score", "away_score", "home_linescores", "away_linescores"] + [
        f"{s}_{k}" for s in ("home", "away") for k in ("abbreviation", "location", "display_name", "short_display_name", "name")]
    out = {}
    for f in sorted(glob.glob(str(Path(folder) / "**" / "*schedule*.parquet"), recursive=True)):
        d = pd.read_parquet(f)
        d = d[[c for c in cols if c in d.columns]]
        d = d[(d["date"].astype(str) >= since) & (d["status_type_completed"] == True)]  # noqa: E712
        for r in d.to_dict("records"):
            side = {}
            for s in ("home", "away"):
                try:
                    score = int(r[f"{s}_score"])
                except (TypeError, ValueError):
                    break
                ls = r.get(f"{s}_linescores")
                names = [r.get(f"{s}_{k}") for k in ("location", "display_name", "short_display_name", "name")]
                side[s] = {"abbr": str(r.get(f"{s}_abbreviation") or "").upper(), "score": score,
                           "names": {norm_name(n) for n in names if isinstance(n, str) and n},
                           "periods": [int(float(x)) for x in _LINESCORE_RE.findall(ls)] if isinstance(ls, str) else []}
            if set(side) == {"home", "away"}:
                out[str(r["game_id"])] = _game(r["game_id"], str(r["date"]), side["away"], side["home"])
    return list(out.values())


def _key(day):
    return day.strftime("%y%b%d").upper()


def join(events, games):
    """{suffix: (game, method)}.  Methods: 'abbr' (date + both ESPN abbreviations), 'name' (date + official winner
    name + one abbreviation).  Ambiguous or absent candidates are not joined."""
    by_abbr, by_day = defaultdict(list), defaultdict(list)
    for g in games:
        day = g["start"].astimezone(ET).date()
        by_abbr[_key(day) + g["away"]["abbr"] + g["home"]["abbr"]].append(g)
        by_day[_key(day)].append(g)
    out = {}
    for suffix, series in events.items():
        if len(by_abbr.get(suffix, [])) == 1:
            out[suffix] = (by_abbr[suffix][0], "abbr")
            continue
        m = EVENT_RE.match(suffix)
        if not m:
            continue
        day, teams = m.groups()
        winners = {norm_name(v) for s, c in series.items() if s.endswith("GAME") for v in c if v}
        cands = []
        for g in by_day.get(day, []):
            named = any(w in g[s]["names"] for w in winners for s in ("away", "home"))
            ab = teams.startswith(g["away"]["abbr"]) or teams.endswith(g["home"]["abbr"])
            if named and ab and g["away"]["abbr"] and g["home"]["abbr"]:
                cands.append(g)
        if len(cands) == 1:
            out[suffix] = (cands[0], "name")
    return out


def _bound(text):
    """'28' -> (28, exact); 'at least 28' -> (28, lower bound: the market settled early); else None."""
    m = re.match(r"^(at least )?(\d+)$", (text or "").strip())
    return (int(m[2]), not m[1]) if m else None


def _meets(bound, x):
    return x == bound[0] if bound[1] else x >= bound[0]


def ladder_mismatches(ladder, total):
    """Total-ladder contracts whose official result differs from the rung's rule.  A row that carries the
    exchange's own `floor_strike` is graded on it (YES iff total > floor_strike); only a row without one falls
    back to 'ticker rung N pays YES iff total >= N'.  The ticker rule holds for 2026 (floor = N - 0.5) but NOT
    for the 2025 seasons, whose rungs were 'over N' (floor = N + 0.5): grading those by ticker is wrong exactly
    when the total lands on the rung."""
    return sum(1 for n, res, *fs in ladder if (res == "yes") != ((total > fs[0]) if fs else (total >= n)))


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def judge(kind, value, pts, game):
    """Compare one official value with computed (away, home) points -> 'agree' | 'disagree' | reason string."""
    a, h = pts
    if kind == "TOTAL":
        v = _int(value)
        return "official_value_unparsed" if v is None else ("agree" if v == a + h else "disagree")
    if kind == "GAME" and re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", value or ""):
        return "official_value_opaque_id"                       # CBB half winners carry an internal id, not a name
    if kind == "SPREAD":
        v = _int(value)
        return "official_value_unparsed" if v is None else ("agree" if abs(v) == abs(a - h) else "disagree")
    if kind == "TEAMTOTAL":
        m = re.match(r"^Home: (.+), Away: (.+)$", value or "")
        bh, ba = (_bound(m[1]), _bound(m[2])) if m else (None, None)
        if not (bh and ba):
            return "official_value_unparsed"
        return "agree" if _meets(bh, h) and _meets(ba, a) else "disagree"
    if kind == "GAME":
        n = norm_name(value)
        if n.startswith("tie"):
            return "agree" if a == h else "disagree"
        side = "away" if n in game["away"]["names"] else "home" if n in game["home"]["names"] else None
        if side is None:
            return "official_winner_name_unresolved"
        return "agree" if side == ("away" if a > h else "home") else "disagree"
    return "not_checked"


def check(sport, events, games, ladders=None):
    ladders = ladders or {}
    joined = join(events, games)
    reg = REGULATION[sport]
    counts = defaultdict(Counter)
    disagreements, second_half = [], defaultdict(Counter)
    methods = Counter(m for _, m in joined.values())
    for suffix, series in sorted(events.items()):
        if suffix not in joined:
            for s in series:
                counts[s]["event_not_joined"] += 1
            continue
        g, _ = joined[suffix]
        pa, ph = g["away"]["periods"], g["home"]["periods"]
        ot = len(pa) > reg
        scores_ok = bool(pa) and (sum(pa), sum(ph)) == (g["away"]["score"], g["home"]["score"])
        for s, vals in sorted(series.items()):
            period, kind = classify_series(sport, s)
            if kind == "OT":
                if not scores_ok:
                    counts[s]["no_period_scores"] += 1
                    continue
                bounds = [_bound(v) for v in vals]
                r = ("official_value_unparsed" if None in bounds
                     else "agree" if all(_meets(b, len(pa) - reg) for b in bounds) else "disagree")
                counts[s][r] += 1
                if r == "disagree":
                    disagreements.append({"event": suffix, "series": s, "game_id": g["id"], "computed": len(pa) - reg})
                continue
            if kind == "SPREAD":                                   # some series quote the margin signed per team
                vals = Counter({str(abs(_int(v))) if _int(v) is not None else v: n for v, n in vals.items()})
            if kind == "TEAMTOTAL" and (period == "FG" or scores_ok):
                pts = ((g["away"]["score"], g["home"]["score"]) if period == "FG"
                       else period_points(sport, pa, ph, period))
                if all(_int(v) is not None for v in vals):         # one figure per team market: each must be a team's points
                    rs = {"agree" if _int(v) in pts else "disagree" for v in vals}
                else:
                    rs = {judge(kind, v, pts, g) for v in vals}
                r = "disagree" if "disagree" in rs else "agree" if rs == {"agree"} else "official_value_unparsed"
                counts[s][r] += 1
                if r == "disagree":
                    disagreements.append({"event": suffix, "series": s, "game_id": g["id"], "computed": list(pts)})
                continue
            if len(vals) != 1:
                counts[s]["official_values_differ_within_event"] += 1
                continue
            value = next(iter(vals))
            if period == "FG":
                pts = (g["away"]["score"], g["home"]["score"])
                r = judge(kind, value, pts, g)
            elif not scores_ok:
                counts[s]["no_period_scores"] += 1
                continue
            else:
                pts = period_points(sport, pa, ph, period, include_ot=True)
                r = judge(kind, value, pts, g)
                if period == "2H" and ot:
                    alt = period_points(sport, pa, ph, period, include_ot=False)
                    r_alt = judge(kind, value, alt, g)
                    both = (r == "agree", r_alt == "agree")
                    label = {(True, True): "either", (True, False): "including_ot", (False, True): "regulation_only",
                             (False, False): "neither"}[both]
                    second_half[g["start"].astimezone(ET).date().isoformat()][label] += 1
                    if r_alt == "agree":
                        r = "agree"
            counts[s][r] += 1
            if r == "disagree":
                disagreements.append({"event": suffix, "series": s, "game_id": g["id"], "computed": list(pts)})
            lad = (ladders.get(suffix) or {}).get(s)
            if kind == "TOTAL" and lad:
                bad = ladder_mismatches(lad, sum(pts))
                if period == "2H" and ot:                          # same two readings as the value check
                    bad = min(bad, ladder_mismatches(lad, sum(period_points(sport, pa, ph, period, include_ot=False))))
                counts[s]["contracts_agree"] += len(lad) - bad
                counts[s]["contracts_disagree"] += bad
                if bad and r != "disagree":
                    disagreements.append({"event": suffix, "series": s, "game_id": g["id"], "computed": list(pts),
                                          "contracts": bad})
    total = Counter()
    for c in counts.values():
        total.update(c)
    return {"events_official": len(events), "events_joined": len(joined), "join_methods": dict(methods),
            "games_available": len(games), "totals": dict(total),
            "by_series": {s: dict(c) for s, c in sorted(counts.items())},
            "second_half_in_overtime_games_by_date": {d: dict(c) for d, c in sorted(second_half.items())},
            "unjoined_events": sorted(set(events) - set(joined)), "disagreements": disagreements}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sport", choices=sorted(PREFIX))
    ap.add_argument("--official", nargs="+", required=True, help="kalshi_official output folder(s) for the sport")
    ap.add_argument("--cfb-season-dir", nargs="*", default=[])
    ap.add_argument("--espn-scoreboards")
    ap.add_argument("--espn-summaries", nargs="*", default=[], help="restored vault espn_summary_postgame folder(s)")
    ap.add_argument("--sdv-schedules", help="restored vault espn_team_box_schedules folder (SportsDataverse parquet)")
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    games = [g for d in a.cfb_season_dir for g in load_cfb(d)]
    if a.espn_scoreboards:
        games += load_espn_scoreboards(a.espn_scoreboards)
    if a.espn_summaries or a.sdv_schedules:
        have = {g["id"] for g in games}            # the owner-held / scoreboard source wins where both carry a game
        extra = load_espn_summaries(a.espn_summaries) if a.espn_summaries else []
        extra += load_sdv_schedules(a.sdv_schedules) if a.sdv_schedules else []
        games += [g for g in extra if g["id"] not in have and not have.add(g["id"])]
    events, ladders = official_events(a.official, a.sport)
    if games:                                   # only events inside the box-score window are in the denominator
        lo = min(g["start"] for g in games).astimezone(ET).date() - timedelta(days=1)
        hi = max(g["start"] for g in games).astimezone(ET).date() + timedelta(days=1)
        inside = {}
        for k, v in events.items():
            m = EVENT_RE.match(k)
            try:
                day = datetime.strptime(m.group(1), "%y%b%d").date() if m else None
            except ValueError:
                day = None
            if day and lo <= day <= hi:
                inside[k] = v
        outside, events = len(events) - len(inside), inside
    else:
        outside = 0
    doc = {"schema": "kalshi-official-values-check-1.0", "sport": a.sport, "as_of": a.as_of,
           "notice": "Agent-run, not human verified. Counts, identifiers and own computed figures only.",
           "events_outside_box_score_window": outside, **check(a.sport, events, games, ladders)}
    Path(a.out).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: doc[k] for k in ("events_official", "events_joined", "join_methods", "totals")}, indent=1))


if __name__ == "__main__":
    main()
