"""Collector for the college raw data used by cbb_ext / cfb_ext (RESEARCH_ONLY, $0, public release assets only).

    python -m alpha_engine.features.college_collect OUT_DIR [--cbb-years 2004-2026] [--cfb-years 2014-2025]

Sources are the same public sportsdataverse-data release assets the owner's cbb-edge-finder / cfb-edge-finder repositories already use as FREE_BULK (no CFBD/CBBD API call, no key, no scraping).
CFB play-by-play is column-allowlisted at read time: market-derived columns (spread, formatted_spread, over_under, wp_*, wpa, win-probability, pregame Elo) are NEVER loaded.
Output: OUT_DIR/cbb/{team_box,player_box,schedule}_<year>.parquet (verbatim columns we use) and OUT_DIR/cfb/plays_<year>.parquet + OUT_DIR/cfb/schedule_<year>.parquet; OUT_DIR/MANIFEST.json holds sha256 of every raw file.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

BASE = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"
CBB = {"team_box": ("espn_mens_college_basketball_team_boxscores", "team_box_{y}.parquet"), "player_box": ("espn_mens_college_basketball_player_boxscores", "player_box_{y}.parquet"),
       "schedule": ("espn_mens_college_basketball_schedules", "mbb_schedule_{y}.parquet")}
CBB_KEEP = {"team_box": ["game_id", "season", "season_type", "game_date", "game_date_time", "team_id", "team_home_away", "team_score", "opponent_team_id", "opponent_team_score", "assists", "blocks", "defensive_rebounds",
                         "field_goals_made", "field_goals_attempted", "fouls", "free_throws_made", "free_throws_attempted", "offensive_rebounds", "steals", "total_rebounds", "turnovers",
                         "three_point_field_goals_made", "three_point_field_goals_attempted", "largest_lead"],
            "player_box": ["game_id", "season", "season_type", "game_date", "athlete_id", "team_id", "minutes", "field_goals_made", "field_goals_attempted", "three_point_field_goals_made", "three_point_field_goals_attempted",
                           "free_throws_made", "free_throws_attempted", "offensive_rebounds", "defensive_rebounds", "assists", "steals", "blocks", "turnovers", "fouls", "points", "starter", "did_not_play", "team_score", "opponent_team_id"],
            "schedule": ["game_id", "season", "season_type", "game_date", "neutral_site", "conference_competition", "home_id", "away_id", "home_score", "away_score", "status_period", "status_type_completed", "status_type_description", "tournament_id"]}
CFB_PLAY_KEEP = ["game_id", "season", "week", "id_play", "game_play_number", "drive_id", "drive_number", "pos_team", "def_pos_team", "home", "away", "period", "clock_minutes", "clock_seconds", "play_type", "down", "distance", "yards_to_goal",
                 "yards_gained", "EPA", "success", "scoring", "scoring_play", "td_play", "pos_score_diff_start", "rush", "pass", "pass_attempt", "sack", "int", "fumble_vec", "turnover_vec", "penalty_flag", "penalty_no_play", "drive_start_yards_to_goal",
                 "drive_result", "drive_pts", "drive_scoring", "drive_play", "pass_breakup_player_name", "fumble_forced_player_name", "sack_player_name", "rush_td", "pass_td", "start_date", "neutral_site", "home_team_division", "away_team_division",
                 "down_end", "play_text", "ppa"]
CFB_SCHED_KEEP = ["game_id", "season", "week", "season_type", "game_date", "neutral_site", "conference_competition", "home_id", "away_id", "home_team", "away_team", "home_score", "away_score", "status"]
FORBIDDEN = ("spread", "formatted_spread", "over_under", "wp_before", "wp_after", "wpa", "home_wp_before", "away_wp_before", "pregame_elo")


def fetch(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["curl", "-sS", "-L", "--retry", "3", "--max-time", "400", "-o", str(dest), "-w", "%{http_code}", url], capture_output=True, text=True)
    ok = r.stdout.strip() == "200"
    if not ok and dest.exists(): dest.unlink()
    return ok


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def assert_no_market(cols) -> None:
    bad = [c for c in cols if c in FORBIDDEN]
    if bad: raise ValueError(f"market-derived columns requested: {bad}")


def main(a=None) -> int:
    a = a or sys.argv[1:]; out = Path(a[0]); man = {}
    yr = lambda flag, d: tuple(int(x) for x in (a[a.index(flag) + 1] if flag in a else d).split("-"))
    c0, c1 = yr("--cbb-years", "2004-2026"); f0, f1 = yr("--cfb-years", "2014-2025")
    for k, keep in CBB_KEEP.items(): assert_no_market(keep)
    assert_no_market(CFB_PLAY_KEEP)
    for y in range(c0, c1 + 1):
        for k, (tag, pat) in CBB.items():
            url = f"{BASE}/{tag}/{pat.format(y=y)}"
            with tempfile.TemporaryDirectory() as td:
                t = Path(td) / "x.parquet"
                if not fetch(url, t): print("missing", url); continue
                df = pd.read_parquet(t); man[f"cbb/{k}_{y}"] = {"url": url, "sha256": sha(t), "rows": len(df)}
                df = df[[c for c in CBB_KEEP[k] if c in df.columns]]
                (out / "cbb").mkdir(parents=True, exist_ok=True); df.to_parquet(out / "cbb" / f"{k}_{y}.parquet")
    for y in range(f0, f1 + 1):
        for k, tag, pat, keep in (("plays", "cfbfastR_cfb_pbp", "play_by_play_{y}.parquet", CFB_PLAY_KEEP), ("schedule", "espn_cfb_schedules", "cfb_schedule_{y}.parquet", CFB_SCHED_KEEP)):
            url = f"{BASE}/{tag}/{pat.format(y=y)}"
            with tempfile.TemporaryDirectory() as td:
                t = Path(td) / "x.parquet"
                if not fetch(url, t): print("missing", url); continue
                import pyarrow.parquet as pq
                have = set(pq.ParquetFile(t).schema.names); cols = [c for c in keep if c in have]
                df = pd.read_parquet(t, columns=cols); man[f"cfb/{k}_{y}"] = {"url": url, "sha256": sha(t), "rows": len(df), "columns_missing_from_release": sorted(set(keep) - have)}
                (out / "cfb").mkdir(parents=True, exist_ok=True); df.to_parquet(out / "cfb" / f"{k}_{y}.parquet")
    (out / "MANIFEST.json").write_text(json.dumps(man, indent=1, sort_keys=True)); print("files", len(man)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
