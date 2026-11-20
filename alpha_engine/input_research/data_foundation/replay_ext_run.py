"""Families: tennis, mlb_pitch, nba_team, nba_player, nhl, cbb, cfb, and Phase 15 nba_team3, nba_player3, nhl2, nhl_ev2, nhl_player2, Phase 6 nhl3, nhl_player3, Phase 7 nfl_pbp3, nfl_rush3, nfl_pbp4, nfl_player5, cbb_player6, mlb_team7, mlb_pitcher7, nfl_team8, nfl_qb8, nfl_skill8, nfl_path8, cbb_team9, nba_stint10, mlb_fi11, nfl_xtd11, cfb_drive12 (python -m ... nba_team NBA_HISTORY_DIR OUT.json).
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
    elif fam == "nfl_player5":  # batch 5 player props (rows keyed game_id + player id in `team`); args PBP_DIR GAMES.csv OUT.json. Season 2010 is warm-up history in
        # pbp_warm / games_warm (before every cut, so never truncated or permuted by a correct check); output rows start 2011, so every game in the tested tables has rows.
        from ...features import nfl_player_ext5 as X
        raw = X.load_raw(a[1], a[2]); out = a[3]
        r = G.run(X, raw, "NFL", {"pbp": ("game_id", X.CONTENT), "games": ("game_id", ["home_score"])}, games_table="games", games_date_col="gameday", quick=quick)
    elif fam == "cbb_player6":  # batch 6 CBB player props (rows keyed game_id + athlete id in `team`); args RAW_CBB_DIR OUT.json (restored vault archive with
        # espn_mens_college_basketball_player_boxscores/). Season 2012 is history only (priors for 2013); every table is the one box table.
        from ...features import cbb_player_ext6 as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "CBB", {"box": ("game_id", X.CONTENT)}, games_table="box", games_date_col="game_date", quick=quick, truncate_by_date=True)   # 2 box games (2014) have no output row
    elif fam == "nfl_skill8":  # batch 8 NFL skill availability; args PBP_DIR GAMES.csv INJURY_DIR OUT.json. Adds the required post-kickoff injury check of nfl.injuries_pit:
        # every injury row last modified after kickoff (or with no timestamp) is rewritten as an Out / WR listing of a high-usage player; no feature may move, and the check is not vacuous.
        import numpy as _np
        import pandas as pd
        from ...features import nfl_skill_ext8 as X
        raw = X.load_raw(a[1], a[2], a[3]); out = a[4]
        # precedent replay_ext (nfl.injuries_pit): own-game scrambles the game's OUTCOME data (play-by-play, score); the pre-kickoff injury report of the game itself is pregame
        # information and is checked separately: (a) reports of games dated on/after each of 3 cuts are permuted -> earlier rows unchanged; (b) post-kickoff rows -> nothing moves.
        r = G.run(X, raw, "NFL", {"pbp": ("game_id", X.CONTENT), "games": ("game_id", ["home_score"])}, games_table="games", games_date_col="gameday", quick=quick)
        base = X.compute(raw)["team"]; gd = X._all(raw, "games").drop_duplicates("game_id").set_index("game_id").gameday
        for q_, seed_ in G.CUTS:
            cut = pd.Timestamp(base.date.sort_values().reset_index(drop=True).quantile(q_)).normalize(); sel = (base.date < cut).to_numpy()
            late = (pd.to_datetime(raw["injuries"].game_id.map(gd)) >= cut).to_numpy()
            alt_ = X.compute({**raw, "injuries": G._perm(raw["injuries"], late, X.INJ_CONTENT + ["position"], _np.random.default_rng(seed_ + 7))})["team"]
            for s_ in X.specs():
                b = G._cmp(base, alt_, s_.columns, sel)
                r["inputs"][s_.catalog_id]["tests"].setdefault("pit_check_future_injury_reports", {"cuts": [], "ok": True})
                t_ = r["inputs"][s_.catalog_id]["tests"]["pit_check_future_injury_reports"]; t_["cuts"].append({"cut": str(cut.date()), "n_rows_permuted": int(late.sum()), "bad_columns": b}); t_["ok"] = t_["ok"] and not b and int(late.sum()) > 0
        post = X.post_kickoff_mask(raw); inj = raw["injuries"].copy()
        inj.loc[post, "report_status"] = "Out"; inj.loc[post, "position"] = "WR"; inj.loc[post, "gsis_id"] = inj["gsis_id"].dropna().value_counts().index[0]
        alt = X.compute({**raw, "injuries": inj})["team"]
        for s_ in X.specs():
            b = G._cmp(base, alt, s_.columns, _np.ones(len(base), bool))
            r["inputs"][s_.catalog_id]["tests"]["pit_check_post_kickoff_injuries"] = {"n_rows": int(post.sum()), "bad_columns": b, "ok": (not b) and int(post.sum()) > 0,
                                                                                        "note": "rows last modified after kickoff (or untimestamped) rewritten as Out WR listings; no feature may change"}
    elif fam == "nfl_qb8":  # batch 8 NFL quarterback rows (team = passer id); args PBP_DIR GAMES.csv OUT.json (2010-2012 warm history)
        from ...features import nfl_qb_ext8 as X
        raw = X.load_raw(a[1], a[2]); out = a[3]
        r = G.run(X, raw, "NFL", {"pbp": ("game_id", X.CONTENT), "games": ("game_id", ["home_score"])}, games_table="games", games_date_col="gameday", quick=quick)
    elif fam == "nfl_path8":  # batch 8 NFL score-path kernel frequencies; args PBP_DIR GAMES.csv OUT.json (2010-2012 warm history)
        from ...features import nfl_path_ext8 as X
        raw = X.load_raw(a[1], a[2]); out = a[3]
        r = G.run(X, raw, "NFL", {"pbp": ("game_id", X.CONTENT), "games": ("game_id", X.GAMES_CONTENT)}, games_table="games", games_date_col="gameday", quick=quick)
    elif fam == "nfl_xtd11":  # batch 11 NFL player xTD (team = player id); args PBP_DIR GAMES.csv OUT.json (2010-2012 warm history)
        from ...features import nfl_xtd_ext11 as X
        raw = X.load_raw(a[1], a[2]); out = a[3]
        r = G.run(X, raw, "NFL", {"pbp": ("game_id", X.CONTENT), "games": ("game_id", ["home_score"])}, games_table="games", games_date_col="gameday", quick=quick)
    elif fam == "nfl_team8":  # batch 8 NFL team drive-model inputs; args PBP_DIR GAMES.csv OUT.json (seasons 2010-2012 are warm history in pbp_warm / games_warm)
        from ...features import nfl_team_ext8 as X
        raw = X.load_raw(a[1], a[2]); out = a[3]
        r = G.run(X, raw, "NFL", {"pbp": ("game_id", X.CONTENT), "games": ("game_id", X.GAMES_CONTENT)}, games_table="games", games_date_col="gameday", quick=quick)
    elif fam == "nba_stint10":  # batch 10 NBA on-court inputs from stints + events; args NBA_HISTORY_DIR (nba-edge-finder data/history) OUT.json
        from ...features import nba_stint_ext10 as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "NBA", {"games": ("game_id", X.G_CONTENT), "events": ("game_id", X.EV_CONTENT), "stints": ("game_id", X.ST_CONTENT)}, games_table="games",
                  games_date_col="game_date", quick=quick, truncate_by_date=True)
    elif fam == "cfb_drive12":  # batch 12 CFB drive-clock and scoring-timeline inputs; args RAW_DIR (restored espn_summary_postgame dirs, or a cfb_drive_ext12.cache dir) OUT.json
        from ...features import cfb_drive_ext12 as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "CFB", {"games": ("game_id", []), "drives": ("game_id", X.DR_CONTENT), "scores": ("game_id", X.SC_CONTENT)}, games_table="games",
                  games_date_col="game_date", quick=quick, truncate_by_date=True)
    elif fam == "cbb_team9":  # batch 9 CBB schedule-only team inputs; args RAW_CBB_DIR OUT.json (restored espn_team_box_schedules; 2006-2012 warm history)
        from ...features import cbb_team_ext9 as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "CBB", {"sched": ("game_id", X.CONTENT)}, games_table="sched", games_date_col="game_date", quick=quick, truncate_by_date=True)
    elif fam == "mlb_fi11":  # batch 11 MLB first-inning Markov chain (team level); args RAW_DIR OUT.json; first-pitch chronology check runs
        from ...features import mlb_fi_ext11 as X, mlb_pa_core as C
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "MLB", {"games": ("game_id", C.GAME_CONTENT), "pa": ("game_id", C.PA_CONTENT)}, games_table="games", games_date_col="game_date", quick=quick, avail_col="avail_date")
    elif fam in ("mlb_team7", "mlb_pitcher7"):  # batch 7 MLB plate-appearance inputs; args RAW_DIR[,RAW_DIR...] (restored postgame_feed_compact seasons, or a mlb_pa_core.cache dir) OUT.json.
        # first-pitch chronology: the suspended-game availability check runs (avail_date = completion date).
        from ...features import mlb_pa_core as C, mlb_pitcher_ext7, mlb_team_ext7
        X = mlb_team_ext7 if fam == "mlb_team7" else mlb_pitcher_ext7
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "MLB", {"games": ("game_id", C.GAME_CONTENT), "pa": ("game_id", C.PA_CONTENT)}, games_table="games", games_date_col="game_date", quick=quick, avail_col="avail_date")
    elif fam in ("nba_derived", "cbb_derived"):  # shared NBA/CBB derived-input engine (alpha_engine.derived); args RESTORED_VAULT_DIR OUT.json
        from ...derived import ext_cbb, ext_nba
        X = ext_nba if fam == "nba_derived" else ext_cbb
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, X.SPORT, X.TABLES, games_table="box", games_date_col="game_date", quick=quick)
    elif fam in ("cfb_espn", "nhl_period", "mlb_line"):  # six-sport expansion (score_core): args RAW_DIR[,RAW_DIR...] OUT.json
        from ...features import cfb_espn_ext, mlb_line_ext, nhl_period_ext
        X = {"cfb_espn": cfb_espn_ext, "nhl_period": nhl_period_ext, "mlb_line": mlb_line_ext}[fam]
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, X.S, {"games": ("game_id", X.CONTENT)}, games_table="games", games_date_col="game_date", quick=quick,
                  avail_col="avail_date" if "avail_date" in raw["games"] else None)     # MLB: suspended games (first-pitch date vs completion date)
    else:
        raise SystemExit("unknown family " + fam)
    Path(out).write_text(json.dumps(r, default=str, indent=0)); print("replayed", len(r["inputs"]), r["seconds"], "s"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
