"""Families: tennis, mlb_pitch, nba_team, nba_player, nhl, cbb, cfb, and Phase 15 nba_team3, nba_player3, nhl2, nhl_ev2, nhl_player2, Phase 6 nhl3, nhl_player3, Phase 7 nfl_pbp3, nfl_rush3 (python -m ... nba_team NBA_HISTORY_DIR OUT.json).
Run the generic extension replay for one builder family and write verification/replay_ext-style JSON.

    python -m alpha_engine.input_research.data_foundation.replay_ext_run tennis RAW_DIR OUT.json [--quick]
    python -m alpha_engine.input_research.data_foundation.replay_ext_run mlb_pitch PITCH_DIR SCHEDULE.csv.gz OUT.json [--quick]
"""
import json
import sys
from pathlib import Path

from . import replay_generic as G


def main(a=None) -> int:
    a = a or sys.argv[1:]; fam = a[0]; quick = "--quick" in a
    if fam == "tennis":
        from ...features import tennis_ext as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "TENNIS", {"matches": ("game_id", ["score", "date"])}, games_table="matches", games_date_col="date", quick=quick)
    elif fam == "mlb_pitch":
        from ...features import mlb_pitch_ext as X
        raw = X.load_raw(a[1], a[2]); out = a[3]
        r = G.run(X, raw, "MLB", {"pitches": ("game_id", X.CONTENT), "games": ("game_id", ["home_score"])}, games_table="games", games_date_col="date", quick=quick)
    elif fam == "nba_team":
        from ...features import nba_ext as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "NBA", {"team_games": ("game_id", X.TG_CONTENT), "player_games": ("game_id", X.PG_CONTENT)}, games_table="team_games", games_date_col="game_date_et", quick=quick)
    elif fam == "nba_player":
        from ...features import nba_player_ext as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "NBA", {"player_games": ("game_id", X.PG_CONTENT), "shots": ("game_id", X.SH_CONTENT)}, games_table="player_games", games_date_col="game_date_et", quick=quick)
    elif fam == "tennis2":
        from ...features import tennis_ext2 as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "TENNIS", {"matches": ("game_id", X.CONTENT)}, games_table="matches", games_date_col="date", quick=quick)
    elif fam == "tennis3":
        from ...features import tennis_ext3 as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "TENNIS", {"matches": ("game_id", X.CONTENT)}, games_table="matches", games_date_col="date", quick=quick)
    elif fam == "tennis4":
        from ...features import tennis_ext4 as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "TENNIS", {"matches": ("game_id", X.CONTENT)}, games_table="matches", games_date_col="date", quick=quick)
    elif fam == "tennis5":
        from ...features import tennis_ext5 as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "TENNIS", {"matches": ("game_id", X.CONTENT)}, games_table="matches", games_date_col="date", quick=quick)
    elif fam == "tennis6":           # proof of concept (tennis_ext6); never run on real data yet
        from ...features import tennis_ext6 as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "TENNIS", {"matches": ("game_id", X.CONTENT)}, games_table="matches", games_date_col="date", quick=quick)
    elif fam == "nhl":
        from ...features import nhl_ext as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "NHL", {"games": ("game_id", X.G_CONTENT), "mp": ("game_id", X.MP_CONTENT)}, games_table="games", games_date_col="game_date", quick=quick)
    elif fam == "cbb":
        from ...features import cbb_ext as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "CBB", {"team_box": ("game_id", X.TB_CONTENT), "schedule": ("game_id", X.SC_CONTENT), "player_box": ("game_id", X.PB_CONTENT)}, games_table="schedule", games_date_col="game_date", quick=quick)
    elif fam == "soccer_of":
        from ...features import soccer_of_ext as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "SOCCER", {"matches": ("game_id", X.CONTENT)}, games_table="matches", games_date_col="game_date", quick=quick)
    elif fam == "soccer_of2":
        from ...features import soccer_of_ext2 as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "SOCCER", {"matches": ("game_id", X.CONTENT)}, games_table="matches", games_date_col="game_date", quick=quick)
    elif fam == "cfb":
        from ...features import cfb_ext as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "CFB", {"plays": ("game_id", X.PL_CONTENT), "schedule": ("game_id", X.SC_CONTENT)}, games_table="schedule", games_date_col="game_date", quick=quick)
    elif fam == "nba_team3":          # Phase 15
        from ...features import nba_ext3 as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "NBA", {"team_games": ("game_id", X.TG_CONTENT), "player_games": ("game_id", X.PG_CONTENT)}, games_table="team_games", games_date_col="game_date_et", quick=quick)
    elif fam == "nba_player3":
        from ...features import nba_player_ext3 as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "NBA", {"player_games": ("game_id", X.PG_CONTENT)}, games_table="player_games", games_date_col="game_date_et", quick=quick)
    elif fam == "nhl2":
        from ...features import nhl_ext2 as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "NHL", {"games": ("game_id", X.G_CONTENT), "mp": ("game_id", X.MP_CONTENT)}, games_table="games", games_date_col="game_date", quick=quick)
    elif fam == "nhl_ev2":
        from ...features import nhl_ev_ext2 as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "NHL", {"team_states": ("game_id", X.TS_CONTENT), "goals": ("game_id", X.GO_CONTENT), "shots": ("game_id", X.SH_CONTENT), "goalies": ("game_id", X.GL_CONTENT)}, games_table="team_states", games_date_col="game_date", quick=quick)
    elif fam == "nhl_player2":
        from ...features import nhl_player_ext2 as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "NHL", {"players": ("game_id", X.PL_CONTENT), "goals": ("game_id", X.GO_CONTENT), "mp": ("nhl_game_id", X.MP_CONTENT)}, games_table="players", games_date_col="game_date", quick=quick)
    elif fam == "nhl3":               # Phase 6 (data acquisition): nhl.long_change_effect
        from ...features import nhl_ext3 as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "NHL", {"team_states": ("game_id", []), "goals": ("game_id", X.GO_CONTENT), "mp": ("nhl_game_id", X.MP_CONTENT)}, games_table="team_states", games_date_col="game_date", quick=quick)
    elif fam == "nhl_player3":        # Phase 6 (data acquisition): nhl.pk_structure_opp
        from ...features import nhl_player_ext3 as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "NHL", {"players": ("game_id", X.PL_CONTENT), "team_states": ("game_id", X.TS_CONTENT), "shots": ("game_id", X.SH_CONTENT), "mp": ("nhl_game_id", X.MP_CONTENT)}, games_table="players", games_date_col="game_date", quick=quick)
    elif fam in ("nfl_pbp3", "nfl_rush3"):  # Phase 7 (data acquisition): nfl.pass_run_split_epa_both_sides / nfl.rush_yardage_tail; args PBP_DIR GAMES.csv PLAYERS.parquet OUT.json
        from ...features import nfl_pbp_ext3 as X3, nfl_rush_ext3 as R3
        X = X3 if fam == "nfl_pbp3" else R3
        raw = X.load_raw(a[1], a[2], a[3]); out = a[4]
        r = G.run(X, raw, "NFL", {"pbp": ("game_id", X.CONTENT), "games": ("game_id", ["home_score"])}, games_table="games", games_date_col="gameday", quick=quick)
    elif fam == "nfl_pbp4":  # batch 4: market-free rating, points for/against, PROE, kernel score / margin distributions; args PBP_DIR GAMES.csv OUT.json
        from ...features import nfl_pbp_ext4 as X
        raw = X.load_raw(a[1], a[2]); out = a[3]
        r = G.run(X, raw, "NFL", {"pbp": ("game_id", X.CONTENT), "games": ("game_id", X.GAMES_CONTENT)}, games_table="games", games_date_col="gameday", quick=quick)
    elif fam in ("nba_derived", "cbb_derived"):  # shared NBA/CBB derived-input engine (alpha_engine.derived); args RESTORED_VAULT_DIR OUT.json
        from ...derived import ext_cbb, ext_nba
        X = ext_nba if fam == "nba_derived" else ext_cbb
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, X.SPORT, X.TABLES, games_table="box", games_date_col="game_date", quick=quick)
    elif fam in ("cfb_espn", "nhl_period", "mlb_line"):  # six-sport expansion (score_core): args RAW_DIR[,RAW_DIR...] OUT.json
        from ...features import cfb_espn_ext, mlb_line_ext, nhl_period_ext
        X = {"cfb_espn": cfb_espn_ext, "nhl_period": nhl_period_ext, "mlb_line": mlb_line_ext}[fam]
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, X.S, {"games": ("game_id", X.CONTENT)}, games_table="games", games_date_col="game_date", quick=quick)
    else:
        raise SystemExit("unknown family " + fam)
    Path(out).write_text(json.dumps(r, default=str, indent=0)); print("replayed", len(r["inputs"]), r["seconds"], "s"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
