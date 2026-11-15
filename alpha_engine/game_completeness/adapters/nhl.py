"""NHL adapter.

roots:
  nhl       NHL-edge-finder checkout (main): data/history/{nhl,players,moneypuck,shots_extension}/*.parquet
  nhl_da    sparse checkout of NHL-edge-finder@data-archive: results/, settlements/, contracts/,
            player_events/{players,goalies,shots,team_states}/, context/{goalie_observations,lines}/ and
            ARCHIVE_LISTING.txt (git ls-tree -r --name-only HEAD) for datasets that are listed but not read
  nhl_ref   api-web.nhle.com weekly schedule JSON (sched_<date>.json) for the current season

Expected games: the league schedule for 2026-27 (independent of the archive); for 2008-2025 the owner's own
data/history/nhl/games_<y>.parquet - NOT an independent denominator, so a game absent from that file is invisible
here (noted in adapter_notes).  Pregame and Kalshi datasets apply to completed 2026-27 games.
"""
import json
import re
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from ..model import FINAL, PROSPECTIVE_ONLY, RECOVERABLE, SCHEDULED, DatasetSpec, Game, Observation, parse_ts
from . import has, jsonl, need

SPORT = "NHL"
ERA = "2026"


def _era(g):
    return g.state == FINAL and g.season == ERA


def _since(y, last=9999):
    return lambda g: g.state == FINAL and y <= int(g.season) <= last


def specs():
    S = lambda **k: DatasetSpec(sport=SPORT, **k)                                               # noqa: E731
    return [
        S(key="final_result", category="A_GAMES", title="Final score, regulation score, REG/OT/SO",
          source="NHL api boxscore (results/, history/nhl/games)", recoverability=RECOVERABLE,
          map_datasets=("nhl.games",), required_fields=("home_final", "away_final", "last_period_type")),
        S(key="period_scores", category="A_GAMES", title="Period-by-period score (period markets settlement)",
          source="none archived as a field", recoverability=RECOVERABLE, map_datasets=("nhl.games",),
          applies=_since(2021),
          note="derivable from archived goal events where player_events exist; no period-score record is stored"),
        S(key="skater_games", category="B_PLAYER", title="Skater game lines with TOI splits, both teams",
          source="NHL boxscore + shift charts (player_events/players)", recoverability=RECOVERABLE,
          map_datasets=("nhl.player_games",), required_fields=("toi_s", "both_teams"), min_records=30,
          applies=_since(2021)),
        S(key="goalie_games", category="B_PLAYER", title="Goalie game lines (starter, saves, SA), both teams",
          source="NHL boxscore (player_events/goalies)", recoverability=RECOVERABLE,
          map_datasets=("nhl.goalie_games",), required_fields=("starter", "both_teams"), min_records=2,
          applies=_since(2021)),
        S(key="shots_xy", category="C_EVENTS", title="Shot attempts with location and strength",
          source="NHL play-by-play (player_events/shots; MoneyPuck 2008-2020)", recoverability=RECOVERABLE,
          map_datasets=("nhl.shots_xy",), min_records=40),
        S(key="shot_xg", category="C_EVENTS", title="Per-shot expected goals", source="MoneyPuck shots",
          recoverability=RECOVERABLE, map_datasets=("nhl.shots_xy",), min_records=40,
          note="MoneyPuck history ends with 2025-26; no per-shot xG is archived for the current season"),
        S(key="team_states", category="C_EVENTS", title="Manpower seconds (EV/PP/SH/EA/EN) per team",
          source="derived from shift charts (player_events/team_states)", recoverability=RECOVERABLE,
          map_datasets=("nhl.team_states",), required_fields=("n_seconds",), min_records=2, applies=_since(2021)),
        S(key="raw_pbp_shifts", category="C_EVENTS", title="Raw play-by-play and shift charts",
          source="none archived (only derived tables are kept)", recoverability=RECOVERABLE,
          map_datasets=("nhl.pbp_events_nonshot", "nhl.shifts_lines"), applies=_since(2021)),
        S(key="goalie_pregame", category="D_PREGAME", title="Expected / confirmed starter observed before puck drop",
          source="DailyFaceoff (context/goalie_observations)", recoverability=PROSPECTIVE_ONLY,
          map_datasets=("nhl.lineup_goalie_pregame",), pregame=True, max_age_hours=3, applies=_era,
          required_fields=("both_teams", "named")),
        S(key="lines_pregame", category="D_PREGAME", title="Line combinations observed before puck drop",
          source="DailyFaceoff (context/lines)", recoverability=PROSPECTIVE_ONLY,
          map_datasets=("nhl.lineup_goalie_pregame",), pregame=True, max_age_hours=6, applies=_era,
          required_fields=("both_teams",)),
        S(key="injuries_pregame", category="D_PREGAME", title="Injury snapshot before puck drop",
          source="ESPN (context/injuries)", recoverability=PROSPECTIVE_ONLY, map_datasets=("nhl.injuries",),
          pregame=True, max_age_hours=6, applies=_era, note="branch listing only; files not read"),
        S(key="kalshi_contracts_rules", category="E_MARKET", title="Contracts mapped to the game, with rules text",
          source="contracts/ (Kalshi market objects)", recoverability=RECOVERABLE, applies=_era,
          required_fields=("rules_primary",)),
        S(key="kalshi_pregame_quotes", category="E_MARKET", title="Market board captured within 30 min of puck drop",
          source="kalshi/markets + markets_delta", recoverability=PROSPECTIVE_ONLY, pregame=True, max_age_hours=0.5,
          applies=_era, note="branch listing only; board files not read"),
        S(key="kalshi_orderbook_pregame", category="E_MARKET", title="Depth ladder captured within 30 min of puck drop",
          source="kalshi/orderbooks + orderbooks_delta (capped at 300 tickers per capture)",
          recoverability=PROSPECTIVE_ONLY, pregame=True, max_age_hours=0.5, applies=_era,
          note="branch listing only; ladders not read"),
        S(key="kalshi_settlement_computed", category="E_MARKET", title="Settlement computed from the box score",
          source="settlements/ (nhl-settle-1.0)", recoverability=RECOVERABLE, applies=_era,
          required_fields=("all_contracts_settled",)),
        S(key="kalshi_settlement_official", category="E_MARKET", title="Kalshi's own result per contract",
          source="none archived", recoverability=RECOVERABLE, applies=_era,
          note="archived market snapshots hold active markets only, so the exchange result is never captured"),
    ]


def _pq(path, cols):
    import pyarrow.parquet as pq
    t = pq.read_table(path, columns=cols)
    return zip(*[t.column(c).to_pylist() for c in cols])


def load(roots):
    root, da, ref = need(roots, "nhl"), need(roots, "nhl_da"), need(roots, "nhl_ref")
    hist = root / "data" / "history"
    games, obs, notes = {}, {}, {}

    # --- expected games ------------------------------------------------------------------------------------
    for f in sorted(ref.glob("sched_*.json")):
        for day in json.loads(f.read_text())["gameWeek"]:
            for g in day["games"]:
                if g.get("gameType") not in (2, 3):
                    continue
                gid = str(g["id"])
                games[gid] = Game(SPORT, gid[:4], gid, day["date"], parse_ts(g.get("startTimeUTC")),
                                  str(g["homeTeam"]["id"]), str(g["awayTeam"]["id"]),
                                  FINAL if g.get("gameState") in ("OFF", "FINAL") else SCHEDULED,
                                  {"home_abbrev": g["homeTeam"].get("abbrev"), "away_abbrev": g["awayTeam"].get("abbrev")})
    n_league = len(games)
    cols = ["game_id", "season", "game_type", "game_date", "home_team_id", "away_team_id", "home_score", "away_score",
            "last_period_type", "final"]
    for f in sorted((hist / "nhl").glob("games_*.parquet")):
        for gid, season, gt, date, h, a, hs, as_, lpt, fin in _pq(f, cols):
            gid = str(gid)
            if gid in games or gt not in (2, 3):
                continue
            games[gid] = Game(SPORT, str(season), gid, str(date), None, str(h), str(a), FINAL if fin else SCHEDULED)
            if fin:
                fp = {k for k, v in (("home_final", hs), ("away_final", as_), ("last_period_type", lpt)) if v is not None}
                obs[(gid, "final_result")] = Observation(1, frozenset(fp), evidence=f"data/history/nhl/{f.name}")
    notes["expected_games_source"] = {"league_schedule_2026_27": n_league,
                                      "owner_history_file_not_independent": len(games) - n_league}

    # --- history parquet (2021+ player events, shots) ---------------------------------------------------------
    def per_game(pattern, key, extra, both_field=True):
        for f in sorted(hist.glob(pattern)):
            n, teams, ok = defaultdict(int), defaultdict(set), defaultdict(lambda: True)
            for gid, tid, v in _pq(f, ["game_id", "team_id", extra]):
                gid = str(gid)
                n[gid] += 1
                teams[gid].add(tid)
                ok[gid] = ok[gid] and v is not None
            for gid in n:
                fp = set()
                if ok[gid]:
                    fp.add(extra)
                if both_field and len(teams[gid]) >= 2:
                    fp.add("both_teams")
                obs[(gid, key)] = Observation(n[gid], frozenset(fp), evidence=str(f.relative_to(root)))

    per_game("players/players_*.parquet", "skater_games", "toi_s")
    per_game("players/goalies_*.parquet", "goalie_games", "starter")
    per_game("players/team_states_*.parquet", "team_states", "n_seconds", both_field=False)
    per_game("players/shots_*.parquet", "shots_xy", "x", both_field=False)
    for sub in ("shots_extension", "moneypuck"):
        for f in sorted((hist / sub).glob("shots_*.parquet")):
            n = defaultdict(int)
            for season, gid in _pq(f, ["season", "game_id"]):
                gid = int(gid)
                n[str(gid if gid > 10 ** 9 else int(season) * 1_000_000 + gid)] += 1
            for gid, k in n.items():
                ev = str(f.relative_to(root))
                obs[(gid, "shot_xg")] = Observation(k, evidence=ev)
                if (gid, "shots_xy") not in obs:
                    obs[(gid, "shots_xy")] = Observation(k, evidence=ev)

    # --- data-archive: results and player events (current season) -------------------------------------------
    for f in sorted(da.glob("results/*/*.jsonl.gz")):
        for r in jsonl(f):
            if r.get("status") == "final":
                obs[(str(r["game_id"]), "final_result")] = Observation(
                    1, frozenset(has(r, "home_final", "away_final", "last_period_type")), evidence=str(f.relative_to(da)))
    for kind, key, extra, both in (("players", "skater_games", "toi_s", True), ("goalies", "goalie_games", "starter", True),
                                   ("team_states", "team_states", "n_seconds", False), ("shots", "shots_xy", "x", False)):
        acc = {}
        for f in sorted(da.glob(f"player_events/{kind}/*/*.jsonl.gz")):
            for r in jsonl(f):
                gid = str(r.get("game_id"))
                a = acc.setdefault(gid, [0, set(), True, str(f.relative_to(da)), f.name])
                if a[4] != f.name:                               # a later file for the same game replaces the earlier
                    a[0], a[1], a[2], a[3], a[4] = 0, set(), True, str(f.relative_to(da)), f.name
                a[0] += 1
                a[1].add(r.get("team_id"))
                a[2] = a[2] and r.get(extra) is not None
        for gid, (n, teams, ok, ev, _) in acc.items():
            fp = ({extra} if ok else set()) | ({"both_teams"} if both and len(teams) >= 2 else set())
            obs[(gid, key)] = Observation(n, frozenset(fp), evidence=ev)

    era = [g for g in games.values() if _era(g) and g.start_utc]

    # --- D: goalie observations and lines ---------------------------------------------------------------------
    gk, gk_post = {}, set()
    for f in sorted(da.glob("context/goalie_observations/*/*.jsonl.gz")):
        for r in jsonl(f):
            g = games.get(str(r.get("game_id")))
            ts = parse_ts(r.get("observed_at_utc") or r.get("_observed_at_utc"))
            if not g or g.start_utc is None or ts is None:
                continue
            if ts >= g.start_utc:
                gk_post.add(g.game_id); continue
            if r.get("status") in (None, "UNKNOWN"):
                continue
            cur = gk.setdefault(g.game_id, {})
            t = r.get("team_id")
            if t not in cur or ts > cur[t][0]:
                cur[t] = (ts, bool(r.get("player_name") or r.get("player_id")))
    for gid, cur in gk.items():
        fp = set()
        if len(cur) >= 2:
            fp.add("both_teams")
        if all(v[1] for v in cur.values()):
            fp.add("named")
        obs[(gid, "goalie_pregame")] = Observation(len(cur), frozenset(fp), min(v[0] for v in cur.values()),
                                                   evidence="context/goalie_observations")
    for gid in gk_post - set(gk):
        obs[(gid, "goalie_pregame")] = Observation(0, post_start_only=True)
    line_runs = []                                                # (ts, team ids present)
    for f in sorted(da.glob("context/lines/*/*.jsonl.gz")):
        ts, teams = None, set()
        for r in jsonl(f):
            ts = ts or parse_ts(r.get("observed_at_utc") or r.get("_observed_at_utc"))
            teams.add(str(r.get("team_id")))
        if ts:
            line_runs.append((ts, teams))
    line_runs.sort(key=lambda x: x[0])
    for g in era:
        best = {}
        for ts, teams in line_runs:
            if ts >= g.start_utc:
                break
            for t in (g.home, g.away):
                if t in teams:
                    best[t] = ts
        if best:
            obs[(g.game_id, "lines_pregame")] = Observation(len(best), frozenset({"both_teams"} if len(best) == 2 else ()),
                                                            min(best.values()), evidence="context/lines")

    # --- listing-only datasets (existence evidence -> UNVERIFIED) ---------------------------------------------
    listed = defaultdict(list)
    lst = da / "ARCHIVE_LISTING.txt"
    pat = re.compile(r"(context/injuries|kalshi/markets|kalshi/markets_delta|kalshi/orderbooks|kalshi/orderbooks_delta)/"
                     r"dt=[\d-]+/\S*?(\d{8}T\d{6}Z)")
    if lst.exists():
        for line in lst.read_text().splitlines():
            m = pat.match(line)
            if m:
                listed[m[1].replace("_delta", "")].append((parse_ts(m[2]), line.strip()))
    for k in listed:
        listed[k].sort()
    notes["listed_files"] = {k: len(v) for k, v in listed.items()} or "ARCHIVE_LISTING.txt not provided"
    for g in era:
        for src, key, look in (("context/injuries", "injuries_pregame", 48), ("kalshi/markets", "kalshi_pregame_quotes", 48),
                               ("kalshi/orderbooks", "kalshi_orderbook_pregame", 48)):
            before = [x for x in listed.get(src, ()) if g.start_utc - timedelta(hours=look) <= x[0] < g.start_utc]
            if before:
                obs[(g.game_id, key)] = Observation(len(before), observed_at=before[-1][0], verified=False,
                                                    evidence=before[-1][1])

    # --- E: contracts (rules) and computed settlements --------------------------------------------------------
    tick, rules = defaultdict(set), defaultdict(lambda: True)
    for f in sorted(da.glob("contracts/*/*.jsonl.gz")):
        for r in jsonl(f):
            gid = str(r.get("game_id"))
            if gid in games:
                tick[gid].add(r["ticker"])
                rules[gid] = rules[gid] and bool(r.get("rules_primary"))
    for gid, t in tick.items():
        obs[(gid, "kalshi_contracts_rules")] = Observation(len(t), frozenset({"rules_primary"} if rules[gid] else ()),
                                                           evidence="contracts/")
    out = defaultdict(dict)
    for f in sorted(da.glob("settlements/*/*.jsonl.gz")):
        for r in jsonl(f):
            out[str(r.get("game_id"))][r["ticker"]] = r.get("outcome")
    unsett = 0
    for gid, d in out.items():
        bad = sum(v not in ("YES", "NO") for v in d.values())
        unsett += bad
        full = bad == 0 and tick.get(gid, set()) <= set(d)
        obs[(gid, "kalshi_settlement_computed")] = Observation(
            len(d) - bad, frozenset({"all_contracts_settled"} if full else ()), evidence="settlements/",
            note=f"{bad} UNSETTLEABLE of {len(d)}; {len(tick.get(gid, ()))} mapped contracts")
    notes["settlement_rows_unsettleable"] = unsett
    return list(games.values()), obs, notes
