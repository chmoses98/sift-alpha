"""CFB (FBS) adapter.

roots:
  cfb          cfb-edge-finder checkout (main): data/football/2026/{schedule.json,team_games.jsonl}
  cfb_rd       sparse checkout of cfb-edge-finder@research-data: data/research_cache/v2/<season>/*.json.gz
  cfb_periods  checkout of cfb-edge-finder@period-scores (data/football/2026/period_scores.jsonl)        optional
  cfb_raw      sparse checkout of cfb-edge-finder@cfb-espn-raw-archive (index/)                            optional
  cfb_signals  sparse checkout of cfb-edge-finder@research-signals (capture/2026/quotes.jsonl)            optional

Rights: the 2014-2025 cache is CollegeFootballData (CFBD) API output held on a branch of a PUBLIC repository; the
repository's own notes call its redistribution licence unresolved.  This adapter reads identifiers and counts only
and writes no CFBD row.  Current-season CFBD collection is pending owner authorisation, so the CFBD-only
current-season cell is RIGHTS_BLOCKED rather than MISSING.

Expected games: 2014-2025 from the CFBD games file (FBS-involved; the owner's own cache, not an independent
denominator); 2026 from data/football/2026/schedule.json (ESPN), restricted to FBS-involved games when the cache's
teams_fbs list resolves, because FCS-vs-FCS games are out of scope by design.
Not assessed in this pass (no per-game join to ESPN ids yet): pregame injuries / weather on research-sidecar and
projection-data, and Kalshi contracts keyed by Kalshi game_key (summarised in adapter_notes instead).
"""
import gzip
import json
from collections import defaultdict

from ..model import FINAL, RECOVERABLE, SCHEDULED, UNAVAILABLE, DatasetSpec, Game, Observation, parse_ts
from . import jsonl, need

SPORT = "CFB"
ERA = "2026"
CFBD = "CFBD cache on a public branch; redistribution licence unresolved (counts only read here)"


def _hist(g):
    return g.state == FINAL and g.season != ERA


def _era(g):
    return g.state == FINAL and g.season == ERA


def specs():
    S = lambda **k: DatasetSpec(sport=SPORT, **k)                                               # noqa: E731
    return [
        S(key="final_score", category="A_GAMES", title="Final score", source="CFBD games / ESPN team_games",
          recoverability=RECOVERABLE, map_datasets=("cfb.games_espn",), required_fields=("points",)),
        S(key="quarter_scores", category="A_GAMES", title="Quarter-by-quarter score",
          source="CFBD line scores / ESPN header linescores (period-scores)", recoverability=RECOVERABLE,
          map_datasets=("cfb.games_espn",), required_fields=("four_periods",)),
        S(key="team_box", category="A_GAMES", title="Team box, both teams", source="CFBD games_teams / ESPN team_games",
          recoverability=RECOVERABLE, map_datasets=("cfb.games_espn", "cfb.box_player"), min_records=2),
        S(key="player_box", category="B_PLAYER", title="Player game stats", source="none archived",
          recoverability=RECOVERABLE, map_datasets=("cfb.box_player",),
          note="no player-level game data is archived on any branch"),
        S(key="drives", category="C_EVENTS", title="Drive-level records", source="CFBD drives / ESPN raw summary index",
          recoverability=RECOVERABLE, map_datasets=("cfb.pbp_cfbd",), min_records=10, note=CFBD),
        S(key="advanced_epa", category="C_EVENTS", title="Advanced team-game stats (PPA/EPA, success rate)",
          source="CFBD advanced game stats", recoverability=RECOVERABLE, map_datasets=("cfb.pbp_cfbd",),
          min_records=2, applies=_hist, note=CFBD),
        S(key="advanced_epa_current", category="C_EVENTS", title="Advanced team-game stats, current season",
          source="CFBD (not collected: owner authorisation pending)", recoverability=RECOVERABLE,
          map_datasets=("cfb.pbp_cfbd",), min_records=2, applies=_era, rights_blocked=True),
        S(key="play_by_play", category="C_EVENTS", title="Play-by-play", source="none archived as a dataset",
          recoverability=RECOVERABLE, map_datasets=("cfb.pbp_cfbd",), min_records=80,
          note="2026 games from 2026-11-05 have plays inside the archived raw ESPN summary (counted via the index)"),
        S(key="raw_espn_summary", category="A_GAMES", title="Raw ESPN game summary payload with sha256",
          source="cfb-espn-raw-archive", recoverability=UNAVAILABLE, applies=_era, required_fields=("fetch_ok",),
          note="postgame payload; ESPN may revise or retire it, so an uncaptured game cannot be assumed recoverable"),
    ]


def _load(p):
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        d = json.load(fh)
    return d if isinstance(d, list) else d.get("data", [])


def load(roots):
    root, rd = need(roots, "cfb"), need(roots, "cfb_rd")
    v2 = rd / "data" / "research_cache" / "v2"
    games, obs, notes = {}, {}, {}

    for sd in sorted(p for p in v2.iterdir() if p.is_dir() and p.name != ERA):
        gf = sd / "games.json.gz"
        if not gf.exists():
            continue
        for g in _load(gf):
            gid = str(g["id"])
            done = bool(g.get("completed"))
            games[gid] = Game(SPORT, str(g.get("season") or sd.name), gid, str(g.get("startDate"))[:10],
                              parse_ts(g.get("startDate")), str(g.get("homeId")), str(g.get("awayId")),
                              FINAL if done else SCHEDULED)
            if done:
                ev = f"research-data:v2/{sd.name}/games.json.gz"
                pts = g.get("homePoints") is not None and g.get("awayPoints") is not None
                obs[(gid, "final_score")] = Observation(1, frozenset({"points"} if pts else ()), evidence=ev)
                h, a = g.get("homeLineScores") or [], g.get("awayLineScores") or []
                if h or a:
                    obs[(gid, "quarter_scores")] = Observation(1, frozenset({"four_periods"} if len(h) >= 4 and len(a) >= 4 else ()),
                                                               evidence=ev)
        for name, key in (("games_teams.json.gz", "team_box"),):
            if (sd / name).exists():
                for r in _load(sd / name):
                    obs[(str(r["id"]), key)] = Observation(len(r.get("teams") or []), evidence=f"research-data:v2/{sd.name}/{name}")
        for pat, key in (("drives_*.json.gz", "drives"), ("advanced_regular.json.gz", "advanced_epa"),
                         ("advanced_postseason.json.gz", "advanced_epa")):
            for f in sorted(sd.glob(pat)):
                n = defaultdict(int)
                for r in _load(f):
                    n[str(r.get("gameId"))] += 1
                for gid, k in n.items():
                    prev = obs.get((gid, key))
                    obs[(gid, key)] = Observation(k + (prev.n_records if prev else 0), evidence=f"research-data:v2/{sd.name}/{f.name}")

    # --- 2026 (ESPN) --------------------------------------------------------------------------------------
    fbs = set()
    tf = v2 / ERA / "teams_fbs.json.gz"
    if tf.exists():
        fbs = {str(t.get("id")) for t in _load(tf)}
    sched = json.loads((root / "data/football/2026/schedule.json").read_text())["events"]
    hit = sum(1 for e in sched if any(str(c.get("team_id")) in fbs for c in e.get("competitors", [])))
    use_fbs = hit >= 0.3 * len(sched)
    n26 = 0
    for e in sched:
        comp = {c.get("home_away"): str(c.get("team_id")) for c in e.get("competitors", [])}
        if use_fbs and not (set(comp.values()) & fbs):
            continue
        n26 += 1
        gid = str(e["id"])
        games[gid] = Game(SPORT, ERA, gid, str(e["date"])[:10], parse_ts(e["date"]), comp.get("home", ""),
                          comp.get("away", ""), FINAL if e.get("completed") else SCHEDULED)
    notes["season_2026_scope"] = {"schedule_events": len(sched), "fbs_involved_expected": n26,
                                  "fbs_filter": "teams_fbs ids" if use_fbs else "NOT APPLIED (ids did not resolve)"}
    tg = defaultdict(list)
    for r in jsonl(root / "data/football/2026/team_games.jsonl"):
        tg[str(r.get("game_id"))].append(r)
    for gid, rs in tg.items():
        ev = "data/football/2026/team_games.jsonl"
        obs[(gid, "final_score")] = Observation(len(rs), frozenset({"points"} if all(r.get("points_for") is not None for r in rs) else ()), evidence=ev)
        obs[(gid, "team_box")] = Observation(sum(1 for r in rs if r.get("box")), evidence=ev)
        if all(len(r.get("period_points") or []) >= 4 for r in rs) and len(rs) >= 2:
            obs[(gid, "quarter_scores")] = Observation(1, frozenset({"four_periods"}), evidence=ev)
    if roots.get("cfb_periods"):
        f = need(roots, "cfb_periods") / "data/football/2026/period_scores.jsonl"
        for r in jsonl(f):
            ok = r.get("valid") and len(r.get("home_periods") or []) >= 4 and len(r.get("away_periods") or []) >= 4
            gid = str(r.get("game_id"))
            if ok or (gid, "quarter_scores") not in obs:
                obs[(gid, "quarter_scores")] = Observation(1, frozenset({"four_periods"} if ok else ()),
                                                           evidence="period-scores:period_scores.jsonl")
    if roots.get("cfb_raw"):
        for f in sorted(need(roots, "cfb_raw").glob("index/*/*.jsonl")):
            for r in jsonl(f):
                gid = str(r.get("event_id"))
                ok = bool(r.get("fetch_ok")) and bool(r.get("sha256"))
                obs[(gid, "raw_espn_summary")] = Observation(1, frozenset({"fetch_ok"} if ok else ()),
                                                             parse_ts(r.get("fetched_at")), evidence="cfb-espn-raw-archive:" + f.name)
                if r.get("n_drives"):
                    obs[(gid, "drives")] = Observation(int(r["n_drives"]), evidence="cfb-espn-raw-archive:" + f.name)
                if r.get("n_plays_logged"):
                    obs[(gid, "play_by_play")] = Observation(int(r["n_plays_logged"]), verified=False,
                                                             evidence="cfb-espn-raw-archive:" + f.name,
                                                             note="count from the index; plays are inside the raw payload")
    if roots.get("cfb_signals"):
        keys, ok = set(), set()
        f = need(roots, "cfb_signals") / "capture/2026/quotes.jsonl"
        for r in jsonl(f):
            keys.add(r.get("game_key"))
            ts, ko = parse_ts(r.get("captured_at")), parse_ts(r.get("kickoff_utc"))
            if ts and ko and 0 < (ko - ts).total_seconds() <= 5400 and r.get("yes_bid") is not None and r.get("yes_ask") is not None:
                ok.add(r.get("game_key"))
        notes["kalshi_game_winner_quotes_not_joined_to_espn_ids"] = {
            "game_keys_with_any_quote": len(keys), "game_keys_with_two_sided_quote_within_90m_of_kickoff": len(ok)}
    return list(games.values()), obs, notes
