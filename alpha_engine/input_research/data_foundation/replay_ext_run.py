"""Families: tennis, mlb_pitch, nba_team, nba_player, nhl, cbb, cfb (python -m ... nba_team NBA_HISTORY_DIR OUT.json).
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
    else:
        raise SystemExit("unknown family " + fam)
    Path(out).write_text(json.dumps(r, default=str, indent=0)); print("replayed", len(r["inputs"]), r["seconds"], "s"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
