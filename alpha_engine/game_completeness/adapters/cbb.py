"""CBB (men's D-I) adapter.

roots:
  cbb_ref    local re-materialisation of the files named in cbb-edge-finder/manifests/bronze/
             sportsdataverse_releases.jsonl (mbb_schedule_<y>, team_box_<y>, player_box_<y>, play_by_play_<y>
             .parquet) plus ESPN scoreboard JSON per day for the current season (sb_<date>.json).
             cbb-edge-finder commits only the manifest (the parquet is gitignored), so these datasets are
             UPSTREAM_MIRROR_ONLY: content verified against the release, no durable owner-held copy.
  cbb_periods       checkout of cbb-edge-finder@period-scores-archive
  cbb_availability  checkout of cbb-edge-finder@availability-archive (captures/)
  cbb_panels        checkout of cbb-edge-finder@kalshi-panel-archive (panels/)

Season label is the ESPN one (2027 = 2026-27).  Expected games come from the SportsDataverse ESPN schedule; for
the current season the independently fetched ESPN scoreboard is unioned in and disagreements are reported.
Rights: the source `sportsdataverse_espn_mbb_cfb` is UNRESOLVED_INTERNAL_ONLY in the rights registry; this adapter
reads identifiers and counts only and writes no provider row.
"""
import gzip
import json
import re
from collections import defaultdict

from ..model import FINAL, PROSPECTIVE_ONLY, RECOVERABLE, SCHEDULED, DatasetSpec, Game, Observation, parse_ts
from . import jsonl, need

SPORT = "CBB"
ERA = "2027"
MIRROR = "UPSTREAM_MIRROR_ONLY: verified against the sportsdataverse release; only a manifest is committed"


def _era(g):
    return g.state == FINAL and g.season == ERA


def _since(y):
    return lambda g: g.state == FINAL and int(g.season) >= y


def _listed(g):
    return _era(g) and g.meta.get("kalshi_listed")


def specs():
    S = lambda **k: DatasetSpec(sport=SPORT, **k)                                               # noqa: E731
    return [
        S(key="final_score", category="A_GAMES", title="Final score in the schedule record",
          source="ESPN schedule (sportsdataverse)", recoverability=RECOVERABLE, map_datasets=("cbb.games_espn",),
          required_fields=("home_score", "away_score"), note=MIRROR),
        S(key="team_box", category="A_GAMES", title="Team box (FGA, FTA, OREB, TOV), both teams",
          source="ESPN team box (sportsdataverse)", recoverability=RECOVERABLE,
          map_datasets=("cbb.games_espn", "cbb.box_player"), required_fields=("four_factor_counts",), min_records=2,
          note=MIRROR + "; games ESPN never boxed (mostly non-D-I opponents, early seasons) read as MISSING"),
        S(key="half_scores", category="A_GAMES", title="Half / regulation / overtime scores",
          source="ESPN scoreboard linescores (period-scores-archive)", recoverability=RECOVERABLE,
          map_datasets=("cbb.games_espn",), required_fields=("first_half", "regulation"), applies=_since(2010),
          note="archived for the current season only; earlier seasons are derivable from play-by-play"),
        S(key="player_box", category="B_PLAYER", title="Player box with minutes, both teams",
          source="ESPN player box (sportsdataverse)", recoverability=RECOVERABLE, map_datasets=("cbb.box_player",),
          required_fields=("minutes", "both_teams"), min_records=10, applies=_since(2006), note=MIRROR),
        S(key="play_by_play", category="C_EVENTS", title="Play-by-play", source="ESPN pbp (sportsdataverse)",
          recoverability=RECOVERABLE, map_datasets=("cbb.box_player",), min_records=150, applies=_since(2010),
          note=MIRROR),
        S(key="availability_pregame", category="D_PREGAME", title="Roster / injury status captured before tip, both teams",
          source="ESPN team roster + league injuries (availability-archive)", recoverability=PROSPECTIVE_ONLY,
          map_datasets=("cbb.availability_snapshots",), pregame=True, max_age_hours=2, applies=_era,
          required_fields=("both_sides",)),
        S(key="kalshi_pregame_panel", category="E_MARKET", title="Kalshi quotes mapped to the game within 30 min of tip",
          source="kalshi-panel-archive (PRETIP rows)", recoverability=PROSPECTIVE_ONLY, pregame=True,
          max_age_hours=0.5, applies=_listed,
          note="denominator = completed games that any archived panel maps a Kalshi contract to"),
    ]


def _positive(v):
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False


def _pq(path, cols):
    import pyarrow.parquet as pq
    names = pq.ParquetFile(path).schema.names
    cols = [c for c in cols if c in names]
    t = pq.read_table(path, columns=cols)
    return cols, zip(*[t.column(c).to_pylist() for c in cols])


def load(roots):
    ref = need(roots, "cbb_ref")
    games, obs, notes = {}, {}, {}

    for f in sorted(ref.glob("mbb_schedule_*.parquet")):
        cols, rows = _pq(f, ["game_id", "season", "season_type", "date", "game_date", "status_type_completed",
                             "home_id", "away_id", "home_score", "away_score", "neutral_site"])
        for r in rows:
            d = dict(zip(cols, r))
            gid = str(d["game_id"])
            done = bool(d.get("status_type_completed"))
            games[gid] = Game(SPORT, str(d["season"]), gid, str(d.get("game_date") or d.get("date"))[:10],
                              parse_ts(d.get("date")), str(d.get("home_id")), str(d.get("away_id")),
                              FINAL if done else SCHEDULED, {"neutral": d.get("neutral_site")})
            if done:
                fp = {k for k in ("home_score", "away_score") if d.get(k) is not None}
                obs[(gid, "final_score")] = Observation(1, frozenset(fp), evidence=f.name)
    sb_final, sb_only = 0, []
    for f in sorted(ref.glob("sb_*.json")):
        for e in json.loads(f.read_text()).get("events", []):
            if e["status"]["type"]["name"] != "STATUS_FINAL":
                continue
            sb_final += 1
            gid = str(e["id"])
            g = games.get(gid)
            if g is None or g.state != FINAL:
                sb_only.append(gid)
                comp = {c["homeAway"]: c["team"]["id"] for c in e["competitions"][0]["competitors"]}
                games[gid] = Game(SPORT, ERA, gid, f.stem[3:], parse_ts(e["date"]), str(comp.get("home")),
                                  str(comp.get("away")), FINAL, {"source": "espn_scoreboard_only"})
    notes["scoreboard_check_current_season"] = {
        "final_on_independent_scoreboard": sb_final,
        "of_which_not_final_in_sdv_schedule": len(sb_only), "examples": sb_only[:10]}

    for f in sorted(ref.glob("team_box_*.parquet")):
        cols, rows = _pq(f, ["game_id", "team_id", "field_goals_attempted", "free_throws_attempted",
                             "offensive_rebounds", "turnovers"])
        n, ok = defaultdict(int), defaultdict(lambda: True)
        for r in rows:
            g = str(r[0])
            n[g] += 1
            # A row of zeros is not a box score: ESPN serves an all-zero team box for some games (e.g. 310573129,
            # final 78-76).  A team that attempted no field goal did not have its box recorded.
            ok[g] = ok[g] and all(v is not None for v in r[2:]) and _positive(r[2])
        for g in n:
            obs[(g, "team_box")] = Observation(n[g], frozenset({"four_factor_counts"} if ok[g] else ()), evidence=f.name)
    for f in sorted(ref.glob("player_box_*.parquet")):
        cols, rows = _pq(f, ["game_id", "team_id", "minutes", "did_not_play"])
        n, teams, ok = defaultdict(int), defaultdict(set), defaultdict(lambda: True)
        for r in rows:
            d = dict(zip(cols, r))
            g = str(d["game_id"])
            n[g] += 1
            teams[g].add(d["team_id"])
            if not d.get("did_not_play"):
                ok[g] = ok[g] and d.get("minutes") is not None
        for g in n:
            fp = ({"minutes"} if ok[g] else set()) | ({"both_teams"} if len(teams[g]) >= 2 else set())
            obs[(g, "player_box")] = Observation(n[g], frozenset(fp), evidence=f.name)
    for f in sorted(ref.glob("play_by_play_*.parquet")):
        _, rows = _pq(f, ["game_id"])
        n = defaultdict(int)
        for (g,) in rows:
            n[str(g)] += 1
        for g, k in n.items():
            obs[(g, "play_by_play")] = Observation(k, evidence=f.name)

    if roots.get("cbb_periods"):
        for f in sorted(need(roots, "cbb_periods").glob("periods/*/*/*/*.jsonl")):
            for r in jsonl(f):
                if not r.get("completed"):
                    continue
                fp = set()
                if r.get("first_half_home") is not None and r.get("first_half_away") is not None:
                    fp.add("first_half")
                if r.get("regulation_home") is not None and r.get("regulation_away") is not None:
                    fp.add("regulation")
                obs[(str(r["espn_game_id"]), "half_scores")] = Observation(1, frozenset(fp), verified=bool(r.get("verified")),
                                                                           evidence="period-scores-archive:" + f.name)

    if roots.get("cbb_availability"):
        av, post = {}, set()
        for f in sorted(need(roots, "cbb_availability").glob("captures/*/*/*/*.jsonl")):
            for r in jsonl(f):
                gid = str(r.get("game_id"))
                ts, tip = parse_ts(r.get("captured_at")), parse_ts(r.get("tip_utc"))
                if gid not in games or ts is None or tip is None:
                    continue
                if ts >= tip:
                    post.add(gid); continue
                cur = av.setdefault(gid, {})
                if r.get("side") not in cur or ts > cur[r.get("side")]:
                    cur[r.get("side")] = ts
        for gid, cur in av.items():
            obs[(gid, "availability_pregame")] = Observation(len(cur), frozenset({"both_sides"} if len(cur) >= 2 else ()),
                                                             min(cur.values()), evidence="availability-archive:captures")
        for gid in post - set(av):
            obs[(gid, "availability_pregame")] = Observation(0, post_start_only=True)

    if roots.get("cbb_panels"):
        rx_gid = re.compile(r'"espn_game_id": (\d+)')
        rx_cap = re.compile(r'"captured_at": "([^"]+)"')
        best, files = {}, 0
        for f in sorted(need(roots, "cbb_panels").glob("panels/*/*/*/*.panel.jsonl.gz")):
            files += 1
            ts = None
            per = defaultdict(int)
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                for line in fh:
                    m = rx_gid.search(line)
                    if not m:
                        continue
                    gid = m[1]
                    if gid in games:
                        games[gid].meta["kalshi_listed"] = True
                    if '"market_phase": "PRETIP"' not in line:
                        continue
                    if ts is None:
                        c = rx_cap.search(line)
                        ts = parse_ts(c[1]) if c else None
                    per[gid] += 1
            if ts is None:
                continue
            for gid, n in per.items():
                g = games.get(gid)
                if g and g.start_utc and ts < g.start_utc and (gid not in best or ts > best[gid][0]):
                    best[gid] = (ts, n, f.name)
        for gid, (ts, n, ev) in best.items():
            obs[(gid, "kalshi_pregame_panel")] = Observation(n, observed_at=ts, evidence="kalshi-panel-archive:" + ev)
        notes["panel_files_read"] = files
        notes["kalshi_listed_completed_games"] = sum(1 for g in games.values() if _listed(g))
    return list(games.values()), obs, notes
