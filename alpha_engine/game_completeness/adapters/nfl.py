"""NFL adapter.

roots:
  nfl_ref   local mirror of nflverse release files (games.csv, pbp_<y>.parquet, stats_player_week_<y>.parquet,
            snap_counts_<y>.parquet, participation_<y>.parquet, injuries_<y>.parquet, ftn_<y>.parquet).
            nfl-edge-finder does NOT archive these on any branch (data/raw/nflverse is gitignored), so the game /
            player / play datasets below are verified against the upstream mirror and flagged
            archive="UPSTREAM_MIRROR_ONLY": complete content, but no durable owner-held copy.
  nfl_md    sparse checkout of nfl-edge-finder@market-data holding data/context/**/{manifest.json,weather.jsonl},
            data/pit_availability/nfl/espn_injuries/**, the capture quote files from the 90 minutes before each
            kickoff, and ARCHIVE_LISTING.txt (git ls-tree -r --name-only of data/kalshi/capture ...), which tells
            the adapter what exists on the branch even when it is not checked out (-> UNVERIFIED, never MISSING).

Pregame and Kalshi datasets apply to completed 2026 games (the capture era).
"""
import csv
import gzip
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ..model import FINAL, PROSPECTIVE_ONLY, RECOVERABLE, SCHEDULED, DatasetSpec, Game, Observation, parse_ts
from . import need

SPORT = "NFL"
ERA = "2026"
ET = ZoneInfo("America/New_York")
MIRROR = "UPSTREAM_MIRROR_ONLY: verified against nflverse; not archived on any owner branch"


def _era(g):
    return g.state == FINAL and g.season == ERA


def _since(y, last=9999):
    return lambda g: g.state == FINAL and y <= int(g.season) <= last


def _outdoor(g):
    return _era(g) and g.meta.get("roof") in ("outdoors", "open")


def specs():
    S = lambda **k: DatasetSpec(sport=SPORT, **k)                                               # noqa: E731
    return [
        S(key="play_by_play", category="C_EVENTS", title="Play-by-play with EPA, all quarters",
          source="nflverse pbp", recoverability=RECOVERABLE, map_datasets=("nfl.pbp",),
          required_fields=("epa", "four_quarters"), min_records=100, note=MIRROR),
        S(key="player_stats", category="B_PLAYER", title="Player game stats, both teams",
          source="nflverse stats_player (week)", recoverability=RECOVERABLE, map_datasets=("nfl.player_stats_weekly",),
          required_fields=("both_teams",), min_records=20, note=MIRROR),
        S(key="snap_counts", category="B_PLAYER", title="Snap counts, both teams", source="nflverse snap_counts (PFR)",
          recoverability=RECOVERABLE, map_datasets=("nfl.snap_counts",), required_fields=("both_teams",),
          min_records=40, applies=_since(2013), note=MIRROR + "; the upstream 2012 file is empty"),
        S(key="participation", category="C_EVENTS", title="Play-level personnel / players on field",
          source="nflverse pbp_participation", recoverability=RECOVERABLE, map_datasets=("nfl.participation",),
          min_records=100, applies=_since(2016), note=MIRROR + "; the current season is published after it ends"),
        S(key="ftn_charting", category="C_EVENTS", title="FTN charting (play-action, pressure flags)",
          source="nflverse ftn_charting", recoverability=RECOVERABLE, map_datasets=("nfl.ftn_charting",),
          min_records=100, applies=_since(2022), note=MIRROR),
        S(key="injury_report_final", category="D_PREGAME", title="Final weekly injury report, both teams",
          source="nflverse injuries (no intra-week timestamps)", recoverability=RECOVERABLE,
          map_datasets=("nfl.injuries_weekly",), required_fields=("both_teams",), applies=_since(2009),
          note=MIRROR + "; a weekly final, not a point-in-time vintage"),
        S(key="injuries_pregame_vintage", category="D_PREGAME", title="League injury snapshot observed before kickoff",
          source="ESPN injuries (pit_availability store; context-capture)", recoverability=PROSPECTIVE_ONLY,
          map_datasets=("nfl.injury_report_vintages",), pregame=True, max_age_hours=6, applies=_era,
          required_fields=("teams",)),
        S(key="weather_forecast_pregame", category="D_PREGAME", title="Kickoff forecast retrieved before kickoff",
          source="NWS / Open-Meteo via context-capture", recoverability=PROSPECTIVE_ONLY, pregame=True,
          max_age_hours=12, applies=_outdoor, required_fields=("forecast",),
          note="open-air and open-roof games only; games without venue coordinates are expected and counted"),
        S(key="kalshi_pregame_quotes", category="E_MARKET", title="Kalshi bid/ask within 90 min before kickoff",
          source="kalshi-conductor capture (.quotes.jsonl)", recoverability=PROSPECTIVE_ONLY, pregame=True,
          max_age_hours=0.5, applies=_era, required_fields=("two_sided",),
          note="change-suppressed capture: a game with no quote change in the window reads as STALE or MISSING"),
        S(key="kalshi_orderbook_pregame", category="E_MARKET", title="Kalshi depth ladder within 90 min before kickoff",
          source="kalshi-conductor capture (.books.jsonl)", recoverability=PROSPECTIVE_ONLY, pregame=True, applies=_era,
          note="existence from the branch listing only (files not read) -> UNVERIFIED at best"),
    ]


def _kick(r):
    try:
        d = datetime.fromisoformat(r["gameday"] + "T" + (r["gametime"] or "13:00"))
    except ValueError:
        return None
    return d.replace(tzinfo=ET).astimezone(timezone.utc)


def expected_games(ref):
    out = {}
    with open(Path(ref) / "games.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            done = r["result"] not in ("", "NA")
            out[r["game_id"]] = Game(SPORT, r["season"], r["game_id"], r["gameday"], _kick(r), r["home_team"],
                                     r["away_team"], FINAL if done else SCHEDULED,
                                     {"roof": r["roof"], "week": r["week"], "game_type": r["game_type"]})
    return out


def _col(path, cols):
    import pyarrow.parquet as pq
    t = pq.read_table(path, columns=cols)
    return [t.column(c).to_pylist() for c in cols]


def load(roots):
    ref, md = need(roots, "nfl_ref"), need(roots, "nfl_md")
    games = expected_games(ref)
    obs, notes = {}, {}
    by_key = {(g.season, g.meta["week"], t): g.game_id for g in games.values() for t in (g.home, g.away)}

    # --- C: play-by-play ------------------------------------------------------------------------------------
    for f in sorted(ref.glob("pbp_*.parquet")):
        gid, epa, qtr = _col(f, ["game_id", "epa", "qtr"])
        n, e, q = defaultdict(int), defaultdict(int), defaultdict(int)
        for g, x, k in zip(gid, epa, qtr):
            n[g] += 1
            e[g] += x is not None
            q[g] = max(q[g], k or 0)
        for g in n:
            fp = set()
            if e[g] >= 0.5 * n[g]:
                fp.add("epa")
            if q[g] >= 4:
                fp.add("four_quarters")
            obs[(g, "play_by_play")] = Observation(n[g], frozenset(fp), evidence=f.name)

    # --- B: player stats / snaps ------------------------------------------------------------------------------
    def team_rows(pattern, key, id_col, team_col):
        for f in sorted(ref.glob(pattern)):
            gid, team = _col(f, [id_col, team_col])
            n, t = defaultdict(int), defaultdict(set)
            for g, tm in zip(gid, team):
                n[g] += 1
                t[g].add(tm)
            for g in n:
                obs[(g, key)] = Observation(n[g], frozenset({"both_teams"} if len(t[g]) >= 2 else ()), evidence=f.name)

    team_rows("stats_player_week_*.parquet", "player_stats", "game_id", "team")
    team_rows("snap_counts_*.parquet", "snap_counts", "game_id", "team")
    for pattern, key in (("participation_*.parquet", "participation"), ("ftn_*.parquet", "ftn_charting")):
        for f in sorted(ref.glob(pattern)):
            (gid,) = _col(f, ["nflverse_game_id"])
            n = defaultdict(int)
            for g in gid:
                n[g] += 1
            for g, k in n.items():
                obs[(g, key)] = Observation(k, evidence=f.name)

    # --- D: weekly injury report (final) ----------------------------------------------------------------------
    teams_seen = defaultdict(set)
    for f in sorted(ref.glob("injuries_*.parquet")):
        season, week, team = _col(f, ["season", "week", "team"])
        for s, w, t in zip(season, week, team):
            if s is None or w is None:
                continue
            g = by_key.get((str(int(s)), str(int(w)), t))        # older files store season / week as floats
            if g:
                teams_seen[g].add(t)
        del season, week, team
    for g, t in teams_seen.items():
        obs[(g, "injury_report_final")] = Observation(len(t), frozenset({"both_teams"} if len(t) >= 2 else ()),
                                                      evidence="injuries_<season>.parquet")

    era = sorted((g for g in games.values() if _era(g) and g.start_utc), key=lambda g: g.start_utc)

    # --- D: pregame injury vintages (league-wide snapshots) ---------------------------------------------------
    runs = []                                                     # (ts, verified, n_teams, evidence)
    for f in sorted(md.glob("data/pit_availability/nfl/espn_injuries/*/*.json.gz")):
        try:
            d = json.loads(gzip.open(f, "rt").read())
            teams = len([t for t in d["payload"]["injuries"] if t.get("injuries") is not None])
            ts = parse_ts(d["meta"]["retrieved_at"])
        except (ValueError, KeyError, OSError, TypeError):
            continue
        if ts:
            runs.append((ts, True, teams, str(f.relative_to(md))))
    for f in sorted(md.glob("data/context/*/*.manifest.json")):
        try:
            src = json.loads(f.read_text())["sources"].get("espn_injuries") or {}
        except (ValueError, KeyError):
            continue
        ts = parse_ts(src.get("retrieved_at"))
        if ts and src.get("status") == 200:
            runs.append((ts, False, None, str(f.relative_to(md))))
    runs.sort(key=lambda r: r[0])
    notes["injury_runs"] = {"verified_pit_store": sum(r[1] for r in runs), "context_manifest_only": sum(not r[1] for r in runs)}
    for g in era:
        before = [r for r in runs if r[0] < g.start_utc]
        if not before:
            continue
        ts, ver, teams, ev = before[-1]
        if not ver:                                               # prefer a read-back run if one is almost as fresh
            alt = [r for r in before if r[1] and (ts - r[0]) <= timedelta(hours=3)]
            if alt:
                ts, ver, teams, ev = alt[-1]
        obs[(g.game_id, "injuries_pregame_vintage")] = Observation(
            1, frozenset({"teams"} if (teams is None or teams >= 28) else ()), ts, verified=ver, evidence=ev)

    # --- D: weather forecasts ---------------------------------------------------------------------------------
    wx, wx_post, wx_rows = {}, set(), 0
    for f in sorted(md.glob("data/context/*/*.weather.jsonl")):
        ts = parse_ts(f.name.split(".")[0])
        for line in f.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            wx_rows += 1
            g = games.get(r.get("game_id"))
            if not g or ts is None or g.start_utc is None:
                continue
            nws, om = r.get("nws") or {}, r.get("open_meteo") or {}
            fc = bool(isinstance(nws, dict) and nws.get("periods")) or bool(isinstance(om, dict) and (om.get("hourly") or {}).get("time"))
            if ts >= g.start_utc:
                wx_post.add(g.game_id); continue
            cur = wx.get(g.game_id)
            if fc and (cur is None or ts > cur[0]):
                wx[g.game_id] = (ts, str(f.relative_to(md)))
            elif not fc and cur is None:
                wx.setdefault(g.game_id + "|nofc", (ts, str(f.relative_to(md))))
    for g in era:
        if g.game_id in wx:
            ts, ev = wx[g.game_id]
            obs[(g.game_id, "weather_forecast_pregame")] = Observation(1, frozenset({"forecast"}), ts, evidence=ev)
        elif g.game_id + "|nofc" in wx:
            ts, ev = wx[g.game_id + "|nofc"]
            obs[(g.game_id, "weather_forecast_pregame")] = Observation(1, frozenset(), ts, evidence=ev,
                                                                       note="row holds provider errors only")
        elif g.game_id in wx_post:
            obs[(g.game_id, "weather_forecast_pregame")] = Observation(0, post_start_only=True)
    notes["weather_rows_read"] = wx_rows
    days = sorted(p.name for p in (md / "data/context").iterdir() if p.is_dir())
    gaps = []
    for a, b in zip(days, days[1:]):
        d = (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days
        if d > 1:
            gaps.append({"after": a, "before": b, "days_without_capture": d - 1})
    notes["context_capture_day_gaps"] = gaps

    # --- E: Kalshi pregame quotes / books ---------------------------------------------------------------------
    listed = defaultdict(list)                                    # kind -> [(ts, path)]
    lst = md / "ARCHIVE_LISTING.txt"
    pat = re.compile(r"data/kalshi/capture/[\d-]+/(\d{8}T\d{6}Z)\.(quotes|books)\.jsonl$")
    if lst.exists():
        for line in lst.read_text().splitlines():
            m = pat.match(line.strip())
            if m:
                listed[m[2]].append((parse_ts(m[1]), line.strip()))
    for k in listed:
        listed[k].sort()
    notes["capture_listing"] = {k: len(v) for k, v in listed.items()} or "ARCHIVE_LISTING.txt not provided"
    best = {}
    files_read = 0
    for f in sorted(md.glob("data/kalshi/capture/*/*.quotes.jsonl")):
        files_read += 1
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                if '"game_id": null' in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                g = games.get(r.get("game_id"))
                ts = parse_ts(r.get("observed_at"))
                if not g or ts is None or g.start_utc is None or ts >= g.start_utc:
                    continue
                two = r.get("yes_bid_dollars") not in (None, "") and r.get("yes_ask_dollars") not in (None, "")
                cur = best.setdefault(g.game_id, [ts, False, set()])
                cur[0] = max(cur[0], ts)
                cur[1] = cur[1] or two
                cur[2].add(r.get("ticker"))
    notes["quote_files_read"] = files_read
    for g in era:
        lo = g.start_utc - timedelta(minutes=90)
        for kind, key in (("quotes", "kalshi_pregame_quotes"), ("books", "kalshi_orderbook_pregame")):
            win = [(ts, p) for ts, p in listed.get(kind, ()) if lo <= ts < g.start_utc]
            if kind == "quotes" and g.game_id in best:
                ts, two, tick = best[g.game_id]
                obs[(g.game_id, key)] = Observation(len(tick), frozenset({"two_sided"} if two else ()), ts,
                                                    evidence="data/kalshi/capture (pre-kickoff runs)")
            elif win:
                local = kind == "quotes" and all((md / p).exists() for _, p in win[-4:])
                if local:
                    continue          # the window's files were read and hold no row for this game -> MISSING
                obs[(g.game_id, key)] = Observation(len(win), observed_at=win[-1][0], verified=False,
                                                    evidence=win[-1][1], note="run files listed on the branch; not read")
    return list(games.values()), obs, notes
