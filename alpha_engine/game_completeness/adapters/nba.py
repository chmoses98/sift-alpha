"""NBA adapter.

roots:
  nba       nba-edge-finder checkout (main): data/history/{espn,espn_pbp,injury_reports}/*.parquet
  nba_da    sparse checkout of nba-edge-finder@data-archive: boxscores/, settlements/, context/starters/,
            history/espn/*.parquet (current-season refresh), ARCHIVE_LISTING.txt (git ls-tree of the branch) and
            INJURY_PIT_LISTING.txt (git ls-tree of the data-injury-pit branch)
  nba_ref   ESPN scoreboard JSON per day (sb_<date>.json) for the current season

Expected games: the ESPN scoreboard for 2026-27 regular-season dates (fetched independently of the archive); for
2023-24..2025-26 the owner's own team_games parquet (regular season + playoffs) - not an independent denominator.
Pregame and Kalshi datasets apply to completed 2026-27 games.
"""
import json
import re
from collections import defaultdict
from datetime import timedelta

from ..model import FINAL, PROSPECTIVE_ONLY, RECOVERABLE, SCHEDULED, DatasetSpec, Game, Observation, parse_ts
from . import has, jsonl, need

SPORT = "NBA"
ERA = "2026-27"


def _era(g):
    return g.state == FINAL and g.season == ERA


def _seasons(*ss):
    return lambda g: g.state == FINAL and g.season in ss


def specs():
    S = lambda **k: DatasetSpec(sport=SPORT, **k)                                               # noqa: E731
    return [
        S(key="final_and_quarters", category="A_GAMES", title="Final score and quarter scores",
          source="ESPN summary (boxscores/, history team_games)", recoverability=RECOVERABLE,
          map_datasets=("nba.team_games", "nba.schedule_arena"), required_fields=("pts", "quarters")),
        S(key="team_box", category="A_GAMES", title="Team box (FGA, FTA, OREB, TOV, possessions), both teams",
          source="ESPN (history team_games)", recoverability=RECOVERABLE, map_datasets=("nba.team_games",),
          required_fields=("fga", "possessions"), min_records=2),
        S(key="player_box", category="B_PLAYER", title="Player box with minutes and shooting, both teams",
          source="ESPN (history player_games)", recoverability=RECOVERABLE, map_datasets=("nba.player_games",),
          required_fields=("minutes", "fga", "both_teams"), min_records=16,
          note="data-archive boxscores/ rows carry no shooting stats; the parquet refresh does"),
        S(key="play_by_play", category="C_EVENTS", title="Play-by-play events", source="ESPN (history espn_pbp)",
          recoverability=RECOVERABLE, map_datasets=("nba.pbp",), min_records=300,
          applies=_seasons("2024-25", "2025-26", ERA), note="no pbp file exists for 2023-24 or the current season"),
        S(key="lineup_stints", category="C_EVENTS", title="Five-man lineup stints", source="derived from ESPN pbp",
          recoverability=RECOVERABLE, map_datasets=("nba.lineup_stints",), min_records=10,
          applies=_seasons("2024-25", "2025-26", ERA)),
        S(key="shots_xy", category="C_EVENTS", title="Shot events with coordinates", source="ESPN (history shot_events)",
          recoverability=RECOVERABLE, map_datasets=("nba.shots_xy",), min_records=120),
        S(key="injury_report_pregame", category="D_PREGAME", title="Official injury report captured before tip",
          source="NBA official report PDF (data-injury-pit)", recoverability=PROSPECTIVE_ONLY,
          map_datasets=("nba.injury_report_vintages",), pregame=True, max_age_hours=3, applies=_era,
          note="data-injury-pit branch listing only; report rows not read"),
        S(key="starters_pregame", category="D_PREGAME", title="Starting five observed before tip, both teams",
          source="ESPN core roster (context/starters)", recoverability=PROSPECTIVE_ONLY,
          map_datasets=("nba.starters_pregame",), pregame=True, max_age_hours=2, applies=_era,
          required_fields=("both_sides", "five_starters")),
        S(key="transactions", category="D_PREGAME", title="Transactions vintage covering the game date",
          source="none archived (capture prepared in nba-edge-finder #106, no schedule)",
          recoverability=PROSPECTIVE_ONLY, map_datasets=("nba.transactions_draft",), applies=_era),
        S(key="kalshi_pregame_quotes", category="E_MARKET", title="Market board captured within 30 min of tip",
          source="kalshi/markets + markets_delta", recoverability=PROSPECTIVE_ONLY, pregame=True, max_age_hours=0.5,
          applies=_era, note="branch listing only; board files not read"),
        S(key="kalshi_orderbook_pregame", category="E_MARKET", title="Depth ladders captured within 30 min of tip",
          source="kalshi/orderbooks + orderbooks_delta", recoverability=PROSPECTIVE_ONLY, pregame=True,
          max_age_hours=0.5, applies=_era, note="branch listing only; ladders not read"),
        S(key="kalshi_settlement_computed", category="E_MARKET", title="Settlement computed from the box score",
          source="settlements/ (settle-1.0)", recoverability=RECOVERABLE, applies=_era,
          required_fields=("all_contracts_settled",)),
        S(key="kalshi_settlement_official", category="E_MARKET", title="Kalshi's own result per contract",
          source="none archived for the current season", recoverability=RECOVERABLE, applies=_era,
          note="archived market snapshots hold active markets only, so the exchange result is never captured"),
    ]


def _pq(path, cols):
    import pyarrow.parquet as pq
    names = pq.ParquetFile(path).schema.names
    cols = [c for c in cols if c in names]
    t = pq.read_table(path, columns=cols)
    return cols, zip(*[t.column(c).to_pylist() for c in cols])


def _count(files, key, obs, root):
    for f in files:
        n = defaultdict(int)
        _, rows = _pq(f, ["game_id"])
        for (gid,) in rows:
            n[gid] += 1
        for gid, k in n.items():
            obs[(gid, key)] = Observation(k, evidence=str(f.relative_to(root)))


def load(roots):
    root, da, ref = need(roots, "nba"), need(roots, "nba_da"), need(roots, "nba_ref")
    hist = root / "data" / "history"
    games, obs, notes = {}, {}, {}

    for f in sorted(ref.glob("sb_*.json")):
        for e in json.loads(f.read_text()).get("events", []):
            if (e.get("season") or {}).get("type") != 2:
                continue
            comp = {c["homeAway"]: c["team"]["abbreviation"] for c in e["competitions"][0]["competitors"]}
            st = e["status"]["type"]["name"]
            gid = "espn:" + str(e["id"])
            games[gid] = Game(SPORT, ERA, gid, f.stem[3:], parse_ts(e["date"]), comp.get("home", ""), comp.get("away", ""),
                              FINAL if st == "STATUS_FINAL" else SCHEDULED, {"espn_status": st})
    n_league = len(games)

    team_files = sorted((hist / "espn").glob("team_games_*.parquet")) + sorted(da.glob("history/espn/team_games_*.parquet"))
    for f in team_files:
        cols, rows = _pq(f, ["game_id", "game_date_et", "start_time_utc", "season", "season_type", "pts", "q1", "q4",
                             "fga", "possessions"])
        acc = defaultdict(list)
        for r in rows:
            acc[r[0]].append(dict(zip(cols, r)))
        for gid, rs in acc.items():
            r0 = rs[0]
            if r0.get("season_type") == "preseason":
                continue
            if gid not in games:
                if r0["season"] == ERA:
                    notes.setdefault("archive_games_absent_from_league_scoreboard", []).append(gid)
                    continue
                games[gid] = Game(SPORT, r0["season"], gid, str(r0["game_date_et"]), parse_ts(r0.get("start_time_utc")))
            ev = f.name
            fq = set()
            if all(r.get("pts") is not None for r in rs):
                fq.add("pts")
            if all(r.get("q1") is not None and r.get("q4") is not None for r in rs):
                fq.add("quarters")
            obs[(gid, "final_and_quarters")] = Observation(len(rs), frozenset(fq), evidence=ev)
            fb = {k for k in ("fga", "possessions") if all(r.get(k) is not None for r in rs)}
            obs[(gid, "team_box")] = Observation(len(rs), frozenset(fb), evidence=ev)
    notes["expected_games_source"] = {"league_scoreboard_2026_27": n_league,
                                      "owner_history_file_not_independent": len(games) - n_league}

    for f in sorted((hist / "espn").glob("player_games_*.parquet")) + sorted(da.glob("history/espn/player_games_*.parquet")):
        cols, rows = _pq(f, ["game_id", "team_id", "played", "minutes", "fga"])
        n, teams, okm, okf = defaultdict(int), defaultdict(set), defaultdict(lambda: True), defaultdict(lambda: True)
        for r in rows:
            d = dict(zip(cols, r))
            g = d["game_id"]
            n[g] += 1
            teams[g].add(d["team_id"])
            if d.get("played"):
                okm[g] = okm[g] and d.get("minutes") is not None
                okf[g] = okf[g] and d.get("fga") is not None
        for g in n:
            fp = ({"minutes"} if okm[g] else set()) | ({"fga"} if okf[g] else set()) | ({"both_teams"} if len(teams[g]) >= 2 else set())
            obs[(g, "player_box")] = Observation(n[g], frozenset(fp), evidence=f.name)

    # current-season box scores on data-archive (finals + quarters even where the parquet refresh lags)
    for f in sorted(da.glob("boxscores/*/*.jsonl.gz")):
        for r in jsonl(f):
            gid = r.get("game_id")
            if r.get("status") != "final" or (gid, "final_and_quarters") in obs:
                continue
            fq = ({"pts"} if has(r, "home_pts", "away_pts") == {"home_pts", "away_pts"} else set())
            if len(r.get("period_scores") or {}) >= 4:
                fq.add("quarters")
            obs[(gid, "final_and_quarters")] = Observation(1, frozenset(fq), evidence=str(f.relative_to(da)))

    _count(sorted((hist / "espn_pbp").glob("pbp_events_*.parquet")), "play_by_play", obs, root)
    _count(sorted((hist / "espn_pbp").glob("stints_*.parquet")), "lineup_stints", obs, root)
    _count(sorted((hist / "espn").glob("shot_events_*.parquet")), "shots_xy", obs, root)

    era = [g for g in games.values() if _era(g) and g.start_utc]

    # --- D: starters ------------------------------------------------------------------------------------------
    st, st_post = {}, set()
    for f in sorted(da.glob("context/starters/*/*.jsonl.gz")):
        for r in jsonl(f):
            g = games.get(r.get("game_id"))
            ts = parse_ts(r.get("observed_at_utc"))
            if not g or ts is None or g.start_utc is None:
                continue
            if ts >= g.start_utc:
                st_post.add(g.game_id); continue
            cur = st.setdefault(g.game_id, {})
            if r.get("side") not in cur or ts > cur[r["side"]][0]:
                cur[r["side"]] = (ts, r.get("n_starters_flagged") == 5)
    for gid, cur in st.items():
        fp = ({"both_sides"} if len(cur) >= 2 else set()) | ({"five_starters"} if all(v[1] for v in cur.values()) else set())
        obs[(gid, "starters_pregame")] = Observation(len(cur), frozenset(fp), min(v[0] for v in cur.values()),
                                                     evidence="context/starters")
    for gid in st_post - set(st):
        obs[(gid, "starters_pregame")] = Observation(0, post_start_only=True)

    # --- listing-only datasets --------------------------------------------------------------------------------
    listed = defaultdict(list)
    pat = re.compile(r"(kalshi/markets|kalshi/markets_delta|kalshi/orderbooks|kalshi/orderbooks_delta)/dt=[\d-]+/\S*?(\d{8}T\d{6}Z)")
    if (da / "ARCHIVE_LISTING.txt").exists():
        for line in (da / "ARCHIVE_LISTING.txt").read_text().splitlines():
            m = pat.match(line)
            if m:
                listed[m[1].replace("_delta", "")].append((parse_ts(m[2]), line.strip()))
    pit = re.compile(r"injury_pit/official/dt=[\d-]+/report_\S*?captured_(\d{8}T\d{6}Z)")
    if (da / "INJURY_PIT_LISTING.txt").exists():
        for line in (da / "INJURY_PIT_LISTING.txt").read_text().splitlines():
            m = pit.match(line)
            if m:
                listed["injury_pit"].append((parse_ts(m[1]), line.strip()))
    for k in listed:
        listed[k].sort()
    notes["listed_files"] = {k: len(v) for k, v in listed.items()}
    for g in era:
        for src, key in (("injury_pit", "injury_report_pregame"), ("kalshi/markets", "kalshi_pregame_quotes"),
                         ("kalshi/orderbooks", "kalshi_orderbook_pregame")):
            before = [x for x in listed.get(src, ()) if g.start_utc - timedelta(hours=48) <= x[0] < g.start_utc]
            if before:
                obs[(g.game_id, key)] = Observation(len(before), observed_at=before[-1][0], verified=False,
                                                    evidence=before[-1][1])

    # --- E: computed settlements ------------------------------------------------------------------------------
    out = defaultdict(dict)
    for f in sorted(da.glob("settlements/*/*.jsonl.gz")):
        for r in jsonl(f):
            out[r.get("game_id")][r["ticker"]] = r.get("outcome")
    tot = bad_tot = 0
    for gid, d in out.items():
        bad = sum(v not in ("YES", "NO") for v in d.values())
        tot += len(d); bad_tot += bad
        obs[(gid, "kalshi_settlement_computed")] = Observation(
            len(d) - bad, frozenset({"all_contracts_settled"} if bad == 0 else ()), evidence="settlements/",
            note=f"{bad} UNSETTLEABLE of {len(d)}")
    notes["settlement_contracts"] = {"total": tot, "unsettleable": bad_tot}
    return list(games.values()), obs, notes
