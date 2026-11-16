"""Vault overlay: a cell is upgraded only from a parsed record that passes its content check; never downgraded."""
import csv
import gzip
import json

from alpha_engine.game_completeness import vault_overlay as V
from alpha_engine.game_completeness.adapters import cbb


def mlb(final=(3, 1), innings=((1, 0), (2, 1)), state="Final", last=(3, 1)):
    side = lambda i: {"team_stats": {"batting": {"runs": 1}, "pitching": {"outs": 27}}, "batting_order": list(range(i, i + 9)),  # noqa: E731
                      "pitchers": [i + 50], "players": [{"id": k, "bat": {"atBats": 1}, "pit": None} for k in range(i, i + 9)]
                      + [{"id": i + 50, "bat": None, "pit": {"outs": 27}}]}
    return {"pk": 1, "status": {"abstractGameState": state},
            "linescore": {"innings": [{"away": {"runs": a}, "home": {"runs": h}} for a, h in innings],
                          "teams": {"away": {"runs": final[0]}, "home": {"runs": final[1]}}},
            "box": {"away": side(100), "home": side(200)},
            "plays": [{"away": last[0], "home": last[1], "pitches": [{"i": 0}]}]}


def test_mlb_game_content_checks():
    assert V.mlb_game(mlb()) == {"inning_linescore": "C", "team_box": "C", "hitter_box": "C", "pitcher_box": "C", "pitch_events": "C"}
    assert V.mlb_game(mlb(final=(4, 1)))["inning_linescore"] == "P"          # innings do not add up to the final
    assert V.mlb_game(mlb(last=(2, 1)))["pitch_events"] == "P"              # event stream stops short of the final
    assert V.mlb_game(mlb(state="Preview")) == {}                           # a file for an unplayed game verifies nothing
    j = mlb()
    j["box"]["away"]["players"] = j["box"]["away"]["players"][:5]
    assert V.mlb_game(j)["hitter_box"] == "P"


def test_cfb_game_needs_a_completed_game_and_both_teams():
    comp = {"status": {"type": {"completed": True}}, "competitors": [
        {"score": "21", "linescores": [{"displayValue": "7"}, {"displayValue": "0"}, {"displayValue": "7"}, {"displayValue": "7"}]},
        {"score": "10", "linescores": [{"displayValue": "3"}, {"displayValue": "0"}, {"displayValue": "7"}, {"displayValue": "0"}]}]}
    j = {"header": {"competitions": [comp]}, "boxscore": {"teams": [{"statistics": [1]}, {"statistics": [1]}],
                                                         "players": [{"statistics": [{"athletes": [1]}]}]},
         "drives": {"previous": [{"plays": [1]}, {"plays": []}]}}
    got = V.cfb_game(j)
    assert got == {"raw_espn_summary": "C", "quarter_scores": "C", "team_box": "C", "player_box": "P", "drives": "C", "play_by_play": "P"}
    comp["status"]["type"]["completed"] = False
    assert V.cfb_game(j) == {}


def test_apply_only_upgrades_and_keeps_not_applicable(tmp_path):
    d = tmp_path / "MLB"
    d.mkdir()
    with gzip.open(d / "games.csv.gz", "wt") as fh:
        w = csv.writer(fh)
        w.writerow(["season", "date", "game_id", "state", "overall", "team_box", "inning_linescore", "pitch_events"])
        w.writerow(["2026", "2026-04-01", "1", "FINAL", "M", "C", "M", "-"])
        w.writerow(["2026", "2026-04-01", "2", "FINAL", "M", "M", "M", "U"])
    obs = {"1": {"team_box": "P", "inning_linescore": "C", "pitch_events": "C"}, "2": {"pitch_events": "P"}, "9": {"team_box": "C"}}
    raw, summ = V.apply("MLB", obs, tmp_path)
    rows = list(csv.DictReader(raw.decode().splitlines()))
    assert (rows[0]["team_box"], rows[0]["inning_linescore"], rows[0]["pitch_events"]) == ("C", "C", "-")   # no downgrade, '-' untouched
    assert rows[1]["pitch_events"] == "P" and rows[1]["team_box"] == "M"
    assert summ["datasets_changed"]["inning_linescore"]["upgraded_vault_verified"] == {"M->C": 1}
    assert summ["vault_games_not_in_ledger"]["n"] == 1 and rows[0]["overall"] == "M"


def test_official_per_game_needs_an_official_row_for_every_archived_contract(tmp_path):
    off = tmp_path / "official" / "NBA" / "NBA"
    off.mkdir(parents=True)
    (off / "KXA.live.jsonl").write_text("".join(json.dumps({"ticker": t, "result": "yes", "expiration_value": "1"}) + "\n" for t in ("KXA-1-A", "KXA-1-B", "KXA-2-A")))
    comp = tmp_path / "c.jsonl"
    comp.write_text("".join(json.dumps(r) + "\n" for r in [
        {"ticker": "KXA-1-A", "game_id": "g1"}, {"ticker": "KXA-1-B", "game_id": "g1"},
        {"ticker": "KXA-2-A", "game_id": "g2"}, {"ticker": "KXA-2-B", "game_id": "g2"}, {"ticker": "KXA-3-A", "game_id": "g3"}]))
    got = V.read_official_by_game(tmp_path / "official", "NBA", str(comp))
    assert got == {"g1": {"kalshi_settlement_official": "C"}, "g2": {"kalshi_settlement_official": "P"}}


def test_cbb_zero_filled_team_box_is_not_a_box():
    assert cbb._positive(55) and not cbb._positive(0) and not cbb._positive(None)
