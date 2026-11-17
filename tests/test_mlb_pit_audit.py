import json

import pandas as pd

from alpha_engine.certify import mlb_pit_audit as A


def _df():
    return pd.DataFrame({
        "game_id": [1, 2, 3], "season": [2026] * 3,
        "start_utc": ["2026-06-01T23:00:00.000Z", "2026-06-02T17:00:00.000Z", "2026-06-02T23:00:00.000Z"],
        "end_utc": ["2026-06-02T02:00:00.000Z", "2026-06-02T20:00:00.000Z", "2026-06-03T02:00:00.000Z"],
        "home_id": [10, 10, 30], "away_id": [20, 30, 20],
        "home_sp_id": [100, 101, 300], "away_sp_id": [200, 301, 201]})


def test_team_availability_uses_latest_prior_end_strictly_before_start():
    a = A.team_availability(_df()).set_index(["game_id", "side"])
    assert pd.isna(a.loc[(1, "home"), "avail_utc"])                      # first game: no prior
    assert a.loc[(2, "home"), "lead_h"] == 15.0                           # team 10: game 1 ended 02:00, game 2 at 17:00
    assert pd.isna(a.loc[(2, "away"), "avail_utc"])                       # team 30 has no prior game
    assert a.loc[(3, "away"), "lead_h"] == 21.0                           # team 20: game 1 ended 02:00, game 3 at 23:00


def test_starter_identity_counts_only_captures_before_first_pitch(tmp_path):
    d = tmp_path / "2026-06-02"; d.mkdir()
    g = lambda gid, st, h, a: {"gameId": gid, "startTime": st, "home": {"pitcher": {"id": str(h)}}, "away": {"pitcher": {"id": str(a)}}}
    (d / "scheduled_20260602T150000Z.json").write_text(json.dumps({"games": [g(2, "2026-06-02T17:00:00Z", 101, 999)]}))
    (d / "official_20260602T180000Z.json").write_text(json.dumps({"games": [g(2, "2026-06-02T17:00:00Z", 555, 555)]}))  # after start
    (d / "rejected_contaminated_20260602T140000Z.json").write_text(json.dumps({"games": [g(3, "2026-06-02T23:00:00Z", 1, 1)]}))
    rep = A.audit(_df(), tmp_path)
    sp = rep["starter_identity"]
    assert sp["starter_slots_with_pregame_capture"] == 2 and sp["agree"] == 1 and sp["disagree"] == 1
    assert rep["features"]["home_sp_ra9_pre"]["pregame"] == "NOT_VERIFIED_RETROSPECTIVE_IDENTITY"
    assert rep["features"]["away_rs_l10_pre"]["pregame"] == "VERIFIED_PIT"
    assert len(rep["features"]) == 22
