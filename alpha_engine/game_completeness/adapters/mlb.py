"""MLB adapter: reads the owner's edge-finder-api archive (main working tree + projection-data branch files).

roots:
  mlb       edge-finder-api checkout (data/ ...)
  mlb_pd    directory holding the projection-data branch's boxscores/mlb tree (optional; hitter box only)
  mlb_ref   directory of statsapi schedule JSON (sched_<year>.json) - expected-games denominator only

Expected games = every regular-season and postseason gamePk the league schedule lists.  A postponed gamePk that was
later played is counted once, as played.  Pregame and Kalshi datasets apply to the capture era only (CAPTURE_SEASON):
pregame vintages for earlier seasons were never capturable by this project and are not counted as gaps.
"""
import json
from collections import defaultdict
from pathlib import Path

from ..model import (CANCELLED, FINAL, POSTPONED, PROSPECTIVE_ONLY, RECOVERABLE, SCHEDULED, DatasetSpec, Game,
                     Observation, parse_ts)
from . import has, jsonl, need

SPORT = "MLB"
CAPTURE_SEASON = "2026"


def _era(g):
    return g.state == FINAL and g.season == CAPTURE_SEASON


def specs():
    S = lambda **k: DatasetSpec(sport=SPORT, **k)                                               # noqa: E731
    return [
        S(key="schedule_snapshot", category="A_GAMES", title="Game in an archived slate (id, start, venue)",
          source="MLB StatsAPI schedule via fetch-slate", recoverability=RECOVERABLE, applies=_era,
          map_datasets=("mlb.schedule_games",), required_fields=("gameId", "startTime", "venue")),
        S(key="team_box", category="A_GAMES", title="Final score + team batting totals (both teams)",
          source="MLB StatsAPI boxscore (research_cache/batting_backtest)", recoverability=RECOVERABLE,
          map_datasets=("mlb.schedule_games", "mlb.boxscore_player"), required_fields=("runs", "hits", "plateAppearances")),
        S(key="inning_linescore", category="A_GAMES", title="Inning-by-inning linescore (F3/F5/F7, RFI settlement)",
          source="MLB StatsAPI linescore", recoverability=RECOVERABLE, map_datasets=("mlb.schedule_games",),
          note="no archive path exists; settle_markets fetches the linescore live and does not persist it"),
        S(key="pitcher_box", category="B_PLAYER", title="Per-pitcher game lines (outs, BF, pitches, K, ER)",
          source="MLB StatsAPI boxscore (research_cache/starter_workload)", recoverability=RECOVERABLE,
          map_datasets=("mlb.boxscore_player",), required_fields=("outs", "battersFaced", "numberOfPitches", "strikeOuts"),
          min_records=2),
        S(key="hitter_box", category="B_PLAYER", title="Per-hitter game lines (H, TB, HR, RBI, SB, PA)",
          source="MLB StatsAPI boxscore (projection-data boxscores/mlb)", recoverability=RECOVERABLE,
          map_datasets=("mlb.boxscore_player",), min_records=18),
        S(key="pitch_events", category="C_EVENTS", title="Pitch-by-pitch with Statcast fields",
          source="statcast_raw/games (statcast-postgame-archive)", recoverability=RECOVERABLE,
          map_datasets=("mlb.pitch_pa_events", "mlb.statcast_bulk"), required_fields=("pitch_count_reconciled",),
          min_records=100, note="row count is reconciled against the archived per-pitcher pitch totals when both exist"),
        S(key="probable_pitchers_pregame", category="D_PREGAME", title="Probable starters observed before first pitch",
          source="slate snapshots (scheduled_refresh / official / recheck)", recoverability=PROSPECTIVE_ONLY,
          map_datasets=("mlb.lineup_il_vintages",), pregame=True, max_age_hours=6, applies=_era,
          required_fields=("away_pitcher", "home_pitcher")),
        S(key="confirmed_lineup_pregame", category="D_PREGAME", title="Confirmed batting order observed before first pitch",
          source="slate snapshots (lineupStatus=confirmed)", recoverability=PROSPECTIVE_ONLY,
          map_datasets=("mlb.lineup_il_vintages",), pregame=True, applies=_era),
        S(key="weather_forecast_pregame", category="D_PREGAME", title="Pregame weather forecast vintage",
          source="none archived (data/weather.json is overwritten)", recoverability=PROSPECTIVE_ONLY, pregame=True,
          applies=_era, note="roofed parks are not excluded: the archive carries no per-game roof state"),
        S(key="kalshi_contracts", category="E_MARKET", title="Kalshi contracts mapped to the game",
          source="kalshi_registry_snapshots -> edgelab/markets", recoverability=RECOVERABLE, applies=_era,
          required_fields=("marketFamily",)),
        S(key="kalshi_pregame_quotes", category="E_MARKET", title="Kalshi bid/ask observed before first pitch",
          source="edgelab/observations", recoverability=PROSPECTIVE_ONLY, pregame=True, max_age_hours=1, applies=_era,
          required_fields=("yesBid", "yesAsk"),
          note="top-of-book only; hourly candles may be recoverable from the exchange, depth is not"),
        S(key="kalshi_settlement_computed", category="E_MARKET", title="Settlement computed from the box score",
          source="edgelab/settlements (edgelab_settle_markets, StatsAPI linescore)", recoverability=RECOVERABLE,
          applies=_era, required_fields=("all_contracts_settled",)),
        S(key="kalshi_settlement_official", category="E_MARKET", title="Kalshi's own result per contract",
          source="none archived", recoverability=RECOVERABLE, applies=_era,
          note="archived settlements are self-computed; the exchange's result field is not preserved"),
        S(key="kalshi_rules_text", category="E_MARKET", title="Timestamped contract rules text",
          source="none archived (rules live in code only)", recoverability=RECOVERABLE, applies=_era),
    ]


_STATE = {"Final": FINAL, "Completed Early": FINAL, "Game Over": FINAL, "Postponed": POSTPONED, "Cancelled": CANCELLED}


def expected_games(ref):
    best = {}
    for f in sorted(Path(ref).glob("sched_*.json")):
        for day in json.loads(f.read_text())["dates"]:
            for g in day["games"]:
                st = _STATE.get(g["status"]["detailedState"], SCHEDULED)
                pk = str(g["gamePk"])
                if pk in best and (best[pk].state == FINAL or st != FINAL):
                    continue
                best[pk] = Game(SPORT, str(g["season"]), pk, g["officialDate"], parse_ts(g["gameDate"]),
                                g["teams"]["home"]["team"]["name"], g["teams"]["away"]["team"]["name"], st,
                                {"game_type": g["gameType"], "venue": g.get("venue", {}).get("name"),
                                 "home_score": g["teams"]["home"].get("score"), "away_score": g["teams"]["away"].get("score")})
    return best


def load(roots):
    root, ref = need(roots, "mlb"), need(roots, "mlb_ref")
    data = root / "data"
    games = expected_games(ref)
    obs, notes = {}, {}

    # --- A/B: research_cache box scores -------------------------------------------------------------------
    pitches = {}
    for f in sorted(data.glob("research_cache/batting_backtest/*/*boxscores.jsonl.gz")):
        for r in jsonl(f):
            a, h = r.get("awayBatting") or {}, r.get("homeBatting") or {}
            fp = has(a, "runs", "hits", "plateAppearances") & has(h, "runs", "hits", "plateAppearances")
            g = games.get(str(r.get("gamePk")))
            note = ""
            if g and g.meta.get("home_score") is not None and "runs" in fp:
                if (h["runs"], a["runs"]) != (g.meta["home_score"], g.meta["away_score"]):
                    fp = fp - {"runs"}; note = "archived runs disagree with the league schedule final"
            obs[(str(r.get("gamePk")), "team_box")] = Observation(2, frozenset(fp), evidence=str(f.relative_to(root)), note=note)
    for f in sorted(data.glob("research_cache/starter_workload/*/*boxscores.jsonl.gz")):
        for r in jsonl(f):
            ps = (r.get("awayPitchers") or []) + (r.get("homePitchers") or [])
            req = ("outs", "battersFaced", "numberOfPitches", "strikeOuts")
            fp = set(req)
            for p in ps:
                fp &= has(p, *req)
            pk = str(r.get("gamePk"))
            both = bool(r.get("awayPitchers")) and bool(r.get("homePitchers"))
            obs[(pk, "pitcher_box")] = Observation(len(ps) if both else 1, frozenset(fp if ps else ()),
                                                   evidence=str(f.relative_to(root)))
            if "numberOfPitches" in fp:
                pitches[pk] = sum(p["numberOfPitches"] for p in ps)

    # --- B: hitter box (projection-data branch) ------------------------------------------------------------
    pd = roots.get("mlb_pd")
    notes["hitter_box_root"] = "provided" if pd and Path(pd).exists() else "NOT PROVIDED: hitter_box cells are unread, not absent"
    if pd and Path(pd).exists():
        for f in sorted(Path(pd).rglob("*.jsonl.gz")):
            for r in jsonl(f):
                pk = str(r.get("game_pk") or r.get("gamePk") or "")
                bat = r.get("batters") or {}
                sides = [bat.get("away") or [], bat.get("home") or []] if isinstance(bat, dict) else [bat]
                n = sum(len(x) for x in sides) if all(sides) else 0          # both teams required
                if pk and n >= obs.get((pk, "hitter_box"), Observation()).n_records:
                    obs[(pk, "hitter_box")] = Observation(n, evidence="projection-data:" + f.name)

    # --- C: pitch events, reconciled to the archived pitch totals ------------------------------------------
    recon = {"games": 0, "with_pitch_total": 0, "short": 0}
    for f in sorted(data.glob("statcast_raw/games/*.jsonl")):
        pk, n, typed = f.stem, 0, 0
        for r in jsonl(f):
            n += 1
            typed += r.get("pitchType") is not None
        fp = set()
        recon["games"] += 1
        if pk in pitches:
            recon["with_pitch_total"] += 1
            if n >= 0.98 * pitches[pk]:
                fp.add("pitch_count_reconciled")
            else:
                recon["short"] += 1
        obs[(pk, "pitch_events")] = Observation(n, frozenset(fp), verified=pk in pitches,
                                                evidence=f"data/statcast_raw/games/{pk}.jsonl",
                                                note=f"{n} rows vs {pitches.get(pk)} boxscore pitches; {typed} typed")
    notes["pitch_reconciliation"] = recon

    # --- A/D: slate snapshots ------------------------------------------------------------------------------
    best_prob, best_lu, post_prob = {}, {}, set()
    for f in sorted(data.glob("slates/*/*.json")):
        name = f.name
        if name.startswith("rejected_") or name == "game_state.json":
            continue
        try:
            d = json.loads(f.read_text())
        except ValueError:
            continue
        ts = parse_ts(name.rsplit("_", 1)[-1].split(".")[0]) if name != "authoritative.json" else None
        for g in d.get("games") or []:
            pk = str(g.get("gameId"))
            if name == "authoritative.json":
                obs[(pk, "schedule_snapshot")] = Observation(1, frozenset(has(g, "gameId", "startTime", "venue")),
                                                             evidence=str(f.relative_to(root)))
                continue
            gm = games.get(pk)
            if not gm or ts is None or gm.start_utc is None:
                continue
            fp = set()
            for side in ("away", "home"):
                if ((g.get(side) or {}).get("pitcher") or {}).get("id"):
                    fp.add(side + "_pitcher")
            if ts >= gm.start_utc:
                post_prob.add(pk); continue
            if fp and (pk not in best_prob or ts > best_prob[pk][0]):
                best_prob[pk] = (ts, fp, str(f.relative_to(root)))
            if g.get("lineupStatus") == "confirmed" and g.get("lineupConfirmed") is not False:
                if pk not in best_lu or ts > best_lu[pk][0]:
                    best_lu[pk] = (ts, str(f.relative_to(root)))
    for pk, (ts, fp, ev) in best_prob.items():
        obs[(pk, "probable_pitchers_pregame")] = Observation(1, frozenset(fp), ts, evidence=ev)
    for pk in post_prob - set(best_prob):
        obs[(pk, "probable_pitchers_pregame")] = Observation(0, post_start_only=True)
    for pk, (ts, ev) in best_lu.items():
        obs[(pk, "confirmed_lineup_pregame")] = Observation(1, observed_at=ts, evidence=ev)

    # --- E: Kalshi ------------------------------------------------------------------------------------------
    alias = {}
    for f in sorted(data.glob("edgelab/games/*.jsonl")):
        for r in jsonl(f):
            pk = r.get("mlbGamePk") or (r.get("supersededBy") or {}).get("canonicalGameId")
            if pk:
                alias[str(r["gameId"])] = str(pk)
    unmapped = defaultdict(int)

    def pk_of(gid, kind):
        gid = str(gid)
        if gid in games:
            return gid
        if alias.get(gid) in games:
            return alias[gid]
        unmapped[kind] += 1
        return None

    tickers, fam_ok = defaultdict(set), defaultdict(lambda: True)
    for f in sorted(data.glob("edgelab/markets/*.jsonl.gz")):
        for r in jsonl(f):
            pk = pk_of(r.get("gameId"), "markets")
            if pk:
                tickers[pk].add(r["marketTicker"])
                fam_ok[pk] = fam_ok[pk] and bool(r.get("marketFamily")) and r.get("parserStatus") == "parsed"
    for pk, t in tickers.items():
        obs[(pk, "kalshi_contracts")] = Observation(len(t), frozenset({"marketFamily"} if fam_ok[pk] else ()),
                                                    evidence="data/edgelab/markets")
    quote, post_q = {}, set()
    for f in sorted(data.glob("edgelab/observations/*.jsonl.gz")):
        for r in jsonl(f):
            pk = pk_of(r.get("gameId"), "observations")
            ts = parse_ts(r.get("capturedAt"))
            if not pk or ts is None or games[pk].start_utc is None:
                continue
            if ts >= games[pk].start_utc:
                post_q.add(pk); continue
            two_sided = r.get("yesBid") is not None and r.get("yesAsk") is not None
            cur = quote.get(pk)
            if cur is None or ts > cur[0]:
                quote[pk] = [ts, two_sided, 1 if cur is None else cur[2] + 1]
            else:
                cur[2] += 1
                if ts == cur[0]:
                    cur[1] = cur[1] or two_sided
    for pk, (ts, two, n) in quote.items():
        obs[(pk, "kalshi_pregame_quotes")] = Observation(n, frozenset({"yesBid", "yesAsk"} if two else ()), ts,
                                                         evidence="data/edgelab/observations")
    for pk in post_q - set(quote):
        obs[(pk, "kalshi_pregame_quotes")] = Observation(0, post_start_only=True)
    settled = defaultdict(set)
    for f in sorted(data.glob("edgelab/settlements/*.jsonl.gz")):
        for r in jsonl(f):
            pk = pk_of(r.get("gameId"), "settlements")
            if pk and r.get("settlementStatus") == "SETTLED" and r.get("result") in ("YES", "NO"):
                settled[pk].add(r["marketTicker"])
    for pk, t in settled.items():
        full = tickers.get(pk) and tickers[pk] <= t
        obs[(pk, "kalshi_settlement_computed")] = Observation(
            len(t), frozenset({"all_contracts_settled"} if full else ()), evidence="data/edgelab/settlements",
            note=f"{len(t)} settled of {len(tickers.get(pk, ()))} mapped contracts")
    notes["kalshi_rows_not_mapped_to_a_schedule_game"] = dict(unmapped)
    return list(games.values()), obs, notes
