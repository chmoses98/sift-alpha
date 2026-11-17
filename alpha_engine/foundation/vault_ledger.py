"""Measured ledger of what the private vault holds, per data-foundation dataset (RESEARCH_ONLY).

    python -m alpha_engine.foundation.vault_ledger --restored ROOT --catalog ../sift-data-vault/CATALOG.json

ROOT holds vault restores as ROOT/<SPORT>/<dataset>/<season>/... (`tools/vault.py restore --path <archive> --to ROOT/<SPORT>/<dataset>/<season>`).
Every figure is COUNTED from the restored bytes (rows, distinct games, first/last game date, per-season games, completeness of the key
fields); nothing is copied from a manifest note. Output: `research/input_research/data_collection/vault_ledger.json`
(counts, dates and archive hashes only, never provider rows). `data_foundation.evidence` reads `*_ledger.json`, so a dataset whose
definition points at a key of this file resolves to COLLECTED_ARCHIVE with a MEASURED history.

What an entry does and does not claim:
  * it proves the raw bytes are durably archived (vault archive sha256) and how many games / seasons they cover;
  * it does NOT claim a feature is built, verified or point-in-time safe: those stay separate readiness checks;
  * `scope_note` states what part of the catalog dataset the archive does NOT cover (e.g. player boxes held, play-by-play not).
An archive that is not restored under ROOT is skipped and listed in `not_measured` (never guessed).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research/input_research/data_collection/vault_ledger.json"


def _pq(files, cols, date_col, game_col="game_id"):
    """Rows, distinct games, date range, per-season games over parquet files (column-pruned read)."""
    import pandas as pd
    rows = 0; games = set(); dmin = dmax = None; per = Counter(); present = Counter()
    for f in files:
        d = pd.read_parquet(f, columns=[c for c in {game_col, date_col, "season", *cols}])
        rows += len(d)
        g = d.drop_duplicates(game_col)
        games.update(g[game_col].astype(str))
        dt = pd.to_datetime(d[date_col], errors="coerce", utc=True).dropna()
        if len(dt):
            a, b = str(dt.min().date()), str(dt.max().date())
            dmin = a if dmin is None or a < dmin else dmin; dmax = b if dmax is None or b > dmax else dmax
        for s, n in g["season"].value_counts().items():
            per[str(int(s))] += int(n)
        for c in cols:
            present[c] += int(d[c].notna().sum())
    return {"rows": rows, "games": len(games), "date_min": dmin, "date_max": dmax, "games_by_season": dict(sorted(per.items())),
            "key_field_completeness": {c: round(present[c] / rows, 4) for c in cols} if rows else {}}


def _files(root, sport, dataset, pattern):
    return sorted(glob.glob(str(root / sport / dataset / "**" / pattern), recursive=True))


def mlb_feeds(root):
    """MLB compact postgame feeds: games, plate appearances, pitches (with pitch-type and coordinates), player box rows, probables, weather."""
    fs = [f for f in _files(root, "MLB", "postgame_feed_compact", "*.json") if not os.path.basename(f).startswith("_")]
    if not fs:
        return None
    n = Counter(); per = Counter(); dmin = dmax = None; keys = Counter()
    for f in fs:
        g = json.load(open(f))
        if (g.get("game") or {}).get("type") != "R" or (g.get("status") or {}).get("abstractGameState") != "Final":
            n["non_regular_or_not_final"] += 1
            continue
        d = (g.get("datetime") or {}).get("officialDate"); n["games"] += 1; per[d[:4]] += 1
        dmin = d if dmin is None or d < dmin else dmin; dmax = d if dmax is None or d > dmax else dmax
        plays = g.get("plays") or []; n["plate_appearances"] += len(plays); n["games_with_plays"] += bool(plays)
        for p in plays:
            for x in p.get("pitches") or []:
                n["pitches"] += 1
                for k in x:
                    keys[k] += 1
        for side in ("away", "home"):
            b = (g.get("box") or {}).get(side) or {}
            n["player_box_rows"] += len(b.get("players") or [])
        pr = g.get("probables") or {}
        n["games_with_both_probables"] += bool(pr.get("away") and pr.get("home"))
        n["games_with_weather"] += bool((g.get("weather") or {}).get("temp"))
        n["games_with_officials"] += bool(g.get("officials"))
        n["games_with_linescore"] += bool((g.get("linescore") or {}).get("innings"))
    base = {"games": n["games"], "date_min": dmin, "date_max": dmax, "games_by_season": dict(sorted(per.items())), "files": len(fs),
            "excluded_non_regular_or_not_final": n["non_regular_or_not_final"]}
    top = {k: round(v / max(n["pitches"], 1), 4) for k, v in keys.most_common(14)}
    return {
        "mlb_feed_pitch_pa": {**base, "rows": n["pitches"], "plate_appearances": n["plate_appearances"], "games_with_plays": n["games_with_plays"], "pitch_field_completeness": top,
                              "scope_note": "MLB Stats API feed only (pitch type / location / result as the feed records them); no Statcast bulk export, no seasons before 2022"},
        "mlb_feed_player_box": {**base, "rows": n["player_box_rows"], "scope_note": "final box rows; a later MLB stat correction is not vintaged"},
        "mlb_feed_games": {**base, "rows": n["games"], "games_with_linescore": n["games_with_linescore"], "games_with_weather": n["games_with_weather"],
                           "games_with_officials": n["games_with_officials"], "games_with_both_probables": n["games_with_both_probables"],
                           "scope_note": "probables / weather are the values in the POSTGAME feed (no posting timestamp): not a pregame vintage"},
    }


def nhl(root):
    out = {}
    f = _files(root, "NHL", "shifts", "shifts_*.parquet")
    if f:
        out["nhl_sdv_shifts"] = {**_pq(f, ["ids_on", "ids_off", "game_seconds"], "game_date"), "files": len(f),
                                 "scope_note": "shift on/off change events (player ids) per game; no pregame line-combination announcements (dailyfaceoff not held)"}
    for key, pat, cols, note in [
        ("nhl_sdv_player_box", "player_box_*.parquet", ["toi", "shots_on_goal", "starter"], "skater and goalie game rows incl. TOI and goalie starter flag"),
        ("nhl_sdv_team_box", "team_box_*.parquet", ["shots_on_goal", "goals"], "team game totals"),
    ]:
        f = _files(root, "NHL", "pbp_boxes_schedules", pat)
        if f:
            out[key] = {**_pq(f, cols, "game_date"), "files": len(f), "scope_note": note}
    f = [x for x in _files(root, "NHL", "pbp_boxes_schedules", "play_by_play_*.parquet") if "lite" not in x]
    if f:
        import pandas as pd
        rows = 0; games = set(); per = Counter()
        for x in f:
            d = pd.read_parquet(x, columns=["game_id", "season", "event_type"]); rows += len(d)
            g = d.drop_duplicates("game_id"); games.update(g.game_id.astype(str))
            for s, k in g.season.value_counts().items():
                per[str(int(s))] += int(k)
        out["nhl_sdv_pbp"] = {"rows": rows, "games": len(games), "games_by_season": dict(sorted(per.items())), "files": len(f), "date_min": str(int(min(per)) - 1), "date_max": str(int(max(per)) - 1),
                              "scope_note": f"full play-by-play held for {len(per)} season file(s) only ({', '.join(sorted(per))}); earlier seasons are NOT in the vault"}
    return out


def nba(root):
    out = {}
    for key, pat, cols, dc, note in [
        ("nba_sdv_team_box", "team_box_*.parquet", ["field_goals_attempted", "offensive_rebounds", "turnovers"], "game_date", "team box totals (four-factor source fields)"),
        ("nba_sdv_player_box", "player_box_*.parquet", ["minutes", "starter", "did_not_play"], "game_date", "player box rows incl. minutes, starter and DNP flags (postgame; no pregame injury vintage)"),
        ("nba_sdv_schedule", "nba_schedule_*.parquet", ["venue_id", "home_score", "neutral_site"], "date", "schedule with venue id / city, scores and line scores"),
        ("nba_sdv_pbp", "play_by_play_*.parquet", ["wallclock", "athlete_id_1"], "game_date", "play-by-play; ONLY the listed seasons are in the vault"),
    ]:
        f = _files(root, "NBA", "espn_pbp_boxes_schedules", pat)
        if f:
            out[key] = {**_pq(f, cols, dc), "files": len(f), "scope_note": note}
    return out


def cbb(root):
    out = {}
    f = _files(root, "CBB", "espn_player_box_pbp_early_seasons", "player_box_*.parquet")
    if f:
        out["cbb_sdv_player_box"] = {**_pq(f, ["minutes", "starter", "points"], "game_date"), "files": len(f),
                                     "scope_note": "player box rows only; play-by-play is held for the 2027 season file alone, so play-level inputs are NOT covered historically"}
    f = _files(root, "CBB", "espn_team_box_schedules", "team_box_*.parquet") + _files(root, "CBB", "espn_player_box_pbp_early_seasons", "team_box_*.parquet")
    if f:
        out["cbb_sdv_team_box"] = {**_pq(f, ["field_goals_attempted", "offensive_rebounds", "total_turnovers"], "game_date"), "files": len(f), "scope_note": "team box totals"}
    f = _files(root, "CBB", "espn_team_box_schedules", "mbb_schedule_*.parquet") + _files(root, "CBB", "espn_player_box_pbp_early_seasons", "mbb_schedule_*.parquet")
    if f:
        out["cbb_sdv_schedule"] = {**_pq(f, ["venue_id", "neutral_site", "home_score"], "date"), "files": len(f), "scope_note": "schedule, venue, neutral flag, scores"}
    return out


def cfb(root):
    """CFBD cache: per-season endpoint files. Counted per endpoint: seasons present and records."""
    import gzip
    base = root / "CFB" / "cfbd_api_cache"
    fs = sorted(glob.glob(str(base / "**" / "*.json.gz"), recursive=True))
    if not fs:
        return {}
    by = {}
    for f in fs:
        ep = os.path.basename(f)[:-8]; season = os.path.basename(os.path.dirname(f))
        try:
            d = json.load(gzip.open(f, "rt"))
        except (OSError, ValueError):
            continue
        n = len(d) if isinstance(d, list) else 1
        e = by.setdefault(ep, {"rows": 0, "seasons": {}}); e["rows"] += n; e["seasons"][season] = n
    def pack(eps, note):
        have = [e for e in eps if e in by]
        if not have:
            return None
        ss = sorted({s for e in have for s in by[e]["seasons"]})
        return {"rows": sum(by[e]["rows"] for e in have), "date_min": ss[0], "date_max": ss[-1], "endpoints": {e: {"rows": by[e]["rows"], "seasons": len(by[e]["seasons"])} for e in have},
                "scope_note": note}
    out = {
        "cfb_cfbd_drives_games": pack(["games", "games_teams", "drives_regular", "drives_postseason", "advanced_regular", "advanced_postseason", "season_advanced", "ratings_sp"],
                                      "games, team game stats, drives, advanced box and SP+ ratings; NO play-level records in this cache (plays live only in the ESPN summaries archive)"),
        "cfb_cfbd_rankings": pack(["rankings"], "weekly poll rankings as CFBD serves them (poll week labels, not release timestamps)"),
        "cfb_cfbd_recruiting_portal": pack(["recruiting_teams", "portal", "returning_production", "talent"], "team recruiting composites, portal entries, returning production, talent composite (season-level, final values)"),
        "cfb_cfbd_coaches": pack(["coaches"], "head-coach seasons and records; no hire/exit dates, no coordinators"),
        "cfb_cfbd_lines": pack(["lines_regular", "lines_postseason"], "sportsbook lines as CFBD aggregates them (provider-labelled, no quote timestamps)"),
    }
    return {k: v for k, v in out.items() if v}


def cfb_summaries(root):
    """ESPN postgame summaries: games with player boxes, drives and plays (one JSON per game)."""
    fs = [f for f in _files(root, "CFB", "espn_summary_postgame", "*.json") if not os.path.basename(f).startswith("_")]
    if not fs:
        return {}
    n = Counter(); per = Counter()
    for f in fs:
        try:
            g = json.load(open(f))
        except ValueError:
            n["unreadable"] += 1
            continue
        n["games"] += 1
        season = str(((g.get("header") or {}).get("season") or {}).get("year") or "")
        per[season] += 1
        bp = (g.get("boxscore") or {}).get("players") or []
        n["games_with_player_box"] += bool(bp)
        n["player_stat_groups"] += sum(len(t.get("statistics") or []) for t in bp)
        dr = ((g.get("drives") or {}).get("previous")) or []
        n["games_with_drives"] += bool(dr); n["drives"] += len(dr); n["plays"] += sum(len(x.get("plays") or []) for x in dr)
    ss = sorted(s for s in per if s)
    base = {"games": n["games"], "date_min": ss[0] if ss else None, "date_max": ss[-1] if ss else None, "games_by_season": dict(sorted(per.items())), "files": len(fs)}
    return {"cfb_espn_player_box": {**base, "rows": n["player_stat_groups"], "games_with_player_box": n["games_with_player_box"],
                                    "scope_note": "player stat groups inside ESPN postgame summaries (FBS-involved finals); games without a box are counted, not filled"},
            "cfb_espn_drives_plays": {**base, "rows": n["plays"], "drives": n["drives"], "games_with_drives": n["games_with_drives"],
                                      "scope_note": "drive and play records inside ESPN postgame summaries; games_with_drives < games are missing play-by-play at the source"}}


def nfl(root):
    """nflverse in-season files held in the vault that the catalog still lists as merely reachable."""
    import pandas as pd
    out = {}
    base = "inseason_player_team"
    f = _files(root, "NFL", base, "officials.parquet")
    if f:
        d = pd.read_parquet(f[0]); gc = "game_id" if "game_id" in d.columns else d.columns[0]
        ss = sorted(d["season"].dropna().astype(int).unique()) if "season" in d.columns else []
        out["nfl_officials"] = {"rows": len(d), "games": int(d[gc].nunique()), "date_min": str(ss[0]) if ss else None, "date_max": str(ss[-1]) if ss else None,
                                "scope_note": "crew per game as recorded after the game; the assignment announcement time is not held"}
    f = _files(root, "NFL", base, "roster_weekly_*.parquet")
    if f:
        ys = sorted(os.path.basename(x).split("_")[-1][:4] for x in f)
        import pyarrow.parquet as pq
        out["nfl_rosters_weekly"] = {"rows": sum(pq.ParquetFile(x).metadata.num_rows for x in f), "files": len(f), "date_min": ys[0], "date_max": ys[-1], "scope_note": "weekly roster snapshots by season/week"}
    f = _files(root, "NFL", base, "historical_contracts.parquet")
    if f:
        import pyarrow.parquet as pq
        out["nfl_contracts"] = {"rows": pq.ParquetFile(f[0]).metadata.num_rows, "files": 1, "date_min": None, "date_max": None,
                                "scope_note": "OverTheCap contract history table as of the snapshot; the cap table vintage at each past date is not preserved"}
    return out


MEASURES = [mlb_feeds, nhl, nba, cbb, cfb, cfb_summaries, nfl]


def archive_hashes(catalog: Path) -> dict:
    c = json.loads(catalog.read_text())
    return {f"{a['sport']}/{a['dataset']}/{a['season']}": {"archive_sha256": a["archive_sha256"], "version": a["version"], "source": a["source"], "kind": a["kind"]} for a in c["archives"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--restored", required=True); ap.add_argument("--catalog", required=True)
    ap.add_argument("--keep", action="store_true", help="keep entries of the committed ledger that this run could not measure (archive not restored)")
    a = ap.parse_args(argv)
    root = Path(a.restored); ds = {}
    for m in MEASURES:
        r = m(root) or {}
        ds.update(r); print(m.__name__, {k: (v.get("games"), v.get("rows")) for k, v in r.items()}, flush=True)
    prev = json.loads(OUT.read_text())["datasets"] if (a.keep and OUT.exists()) else {}
    for k, v in prev.items():
        ds.setdefault(k, v)
    out = {"schema_version": "vault-ledger-1.0", "status": "RESEARCH_ONLY",
           "note": "Counts measured from restored private-vault archives (sift-data-vault). Identifiers, counts, dates and hashes only; no provider rows. "
                   "Holding bytes is not permission: rights stay in rights_registry.json and the vault POLICY.md (private internal research only).",
           "vault_archives": archive_hashes(Path(a.catalog)), "datasets": dict(sorted(ds.items()))}
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print("wrote", OUT, len(ds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
