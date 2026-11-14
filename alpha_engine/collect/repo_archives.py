"""Profile raw historical data that ALREADY EXISTS in the project's own repositories (nba-edge-finder, nhl-edge-finder, tennis-edge-finder tennis-data branch) after pulling it with
`git show` (RESEARCH_ONLY). Reuse before new network access: this is the first source for NBA, NHL and tennis. Writes a measured ledger: rows, seasons, date span, columns, key-field
completeness, sha256 of each pulled file group, and timestamp-reliability notes. Raw files stay in the cache (size); only the ledger is committed.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import pandas as pd

from .common import now, sha256_file

OUT = Path(__file__).resolve().parents[2] / "research/input_research/data_collection/repo_archives_ledger.json"


def prof(pattern: str, key_fields, date_col=None, season_col=None, reader="parquet", note="", repo="", branch="main") -> dict:
    files = sorted(glob.glob(pattern))
    frames = []
    for f in files:
        d = pd.read_parquet(f) if reader == "parquet" else pd.read_csv(f, low_memory=False)
        d["_file"] = Path(f).name
        frames.append(d)
    if not frames:
        return {"status": "MISSING", "pattern": pattern}
    d = pd.concat(frames, ignore_index=True)
    rec = {"source_repo": repo, "branch": branch, "files": len(files), "rows": int(len(d)), "columns": [c for c in d.columns if c != "_file"], "sha256_by_file": {Path(f).name: sha256_file(Path(f)) for f in files[:60]}, "note": note}
    if season_col and season_col in d:
        rec["seasons"] = sorted(str(x) for x in d[season_col].dropna().unique())[:40]
        rec["rows_by_season"] = {str(k): int(v) for k, v in d.groupby(season_col).size().items()}
    if date_col and date_col in d:
        dd = pd.to_datetime(d[date_col].astype(str).str[:10], errors="coerce")
        rec["date_min"], rec["date_max"] = str(dd.min().date()), str(dd.max().date())
    rec["key_field_completeness"] = {f: round(float(d[f].notna().mean()), 4) for f in key_fields if f in d}
    rec["key_fields_absent"] = [f for f in key_fields if f not in d]
    return rec


def main(cache: str):
    c = Path(cache)
    N = c / "nba/data/history"; H = c / "nhl_hist/data/history"; T = c / "tennis"
    ds = {
     "nba_espn_player_games": prof(f"{N}/espn/player_games_*.parquet", ["minutes", "started", "pts", "reb", "ast", "fg3m", "stl", "blk", "tov", "fga", "fta", "plus_minus", "dnp_reason"], "game_date_et", "season", repo="nba-edge-finder", note="ESPN box scores; final post-game records; start_time_utc present"),
     "nba_espn_team_games": prof(f"{N}/espn/team_games_*.parquet", ["pts", "q1", "q2", "q3", "q4", "possessions", "fga", "fta", "oreb", "tov"], "game_date_et", "season", repo="nba-edge-finder", note="team totals, quarter scores, possessions"),
     "nba_espn_shot_events": prof(f"{N}/espn/shot_events_*.parquet", ["x", "y", "zone", "distance_ft", "shot_made", "shooter_player_id", "event_time_utc"], None, "season_type", repo="nba-edge-finder", note="shot location events; event_time_utc recorded"),
     "nba_espn_pbp_events": prof(f"{N}/espn_pbp/pbp_events_*.parquet", ["type_text", "wallclock_utc", "p1", "home_score", "away_score"], None, None, repo="nba-edge-finder", note="play-by-play with wallclock timestamps"),
     "nba_espn_stints": prof(f"{N}/espn_pbp/stints_*.parquet", ["home_p1", "away_p1", "seconds", "home_pts", "away_pts", "home_poss", "certified"], None, None, repo="nba-edge-finder", note="five-man lineup stints derived from PBP (on/off and lineup efficiency)"),
     "nba_official_injury_report_rows": prof(f"{N}/injury_reports/report_rows_*.parquet", ["status", "reason", "report_time_utc", "game_id", "nba_id"], "game_date", None, repo="nba-edge-finder", note="official NBA injury report rows WITH report_time_utc: a point-in-time vintage, 2025-26 only"),
     "nhl_games": prof(f"{H}/nhl/games_*.parquet", ["home_score", "away_score", "start_time_et", "last_period_type"], "game_date", "season", repo="NHL-edge-finder", note="game results 2008-2025"),
     "nhl_player_games": prof(f"{H}/players/players_*.parquet", ["toi_s", "sog", "goals", "assists", "pp_goals", "toi_ev_s", "toi_pp_s", "att_ev", "att_pp", "sog_pp", "a1", "a2"], "game_date", "season", repo="NHL-edge-finder", note="player-game rows with EV/PP/SH splits, 2021-2026"),
     "nhl_goalie_games": prof(f"{H}/players/goalies_*.parquet", ["starter", "toi_s", "saves", "shots_against", "decision", "ev_sa", "pp_sa"], "game_date", "season", repo="NHL-edge-finder", note="goalie-game rows with starter flag, 2021-2026"),
     "nhl_shots": prof(f"{H}/players/shots_*.parquet", ["x", "y", "shot_type", "zone", "strength", "goalie_in_net_id", "since_prev_s"], "game_date", "season", repo="NHL-edge-finder", note="shot events with coordinates, type, strength and goalie in net, 2021-2026"),
     "nhl_team_states": prof(f"{H}/players/team_states_*.parquet", ["sec_ev", "sec_pp", "sec_sh", "sec_en"], "game_date", "season", repo="NHL-edge-finder", note="seconds in each strength state per team-game"),
     "nhl_moneypuck_shots": prof(f"{H}/moneypuck/shots_*.parquet", [], None, None, repo="NHL-edge-finder", note="MoneyPuck public shot data (xG model outputs may be included: check before use as inputs)"),
     "nhl_shots_extension_2008_2020": prof(f"{H}/shots_extension/shots_*.parquet", [], None, None, repo="NHL-edge-finder", note="shot events 2008-2020"),
     "tennis_atp_matches": prof(f"{T}/atp_matches_*.csv.gz", ["w_ace", "w_svpt", "w_1stIn", "w_bpFaced", "minutes", "winner_rank", "surface", "winner_hand", "winner_age", "score"], "tourney_date", None, reader="csv", repo="Tennis-Edge-Finder", branch="tennis-data", note="Jeff Sackmann tennis_atp snapshot 2026-11-06; results 2000-2026 with serve stats"),
     "tennis_wta_matches": prof(f"{T}/wta_matches_*.csv.gz", ["w_ace", "w_svpt", "w_1stIn", "w_bpFaced", "minutes", "winner_rank", "surface", "winner_hand", "winner_age", "score"], "tourney_date", None, reader="csv", repo="Tennis-Edge-Finder", branch="tennis-data", note="Jeff Sackmann tennis_wta snapshot 2026-11-06"),
    }
    # season label for tennis from tourney_date
    out = {"schema_version": "repo-archives-1.0", "status": "RESEARCH_ONLY", "profiled_utc": now(), "datasets": ds,
           "note": "All files pulled with `git show <branch>:<path>` from the project's own public repositories; no new network host needed. Final post-game records unless a timestamp column is named."}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True, default=str))
    for k, v in ds.items():
        print(k, v.get("rows"), v.get("date_min"), v.get("date_max"), v.get("key_fields_absent"))


if __name__ == "__main__":
    main(sys.argv[1])
