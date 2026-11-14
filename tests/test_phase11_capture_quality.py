"""Phase 11 capture-quality helper tests (synthetic fixtures plus real archived samples under docs/capture_workflows/phase11/samples)."""
import gzip
import json
import unittest
from pathlib import Path

from alpha_engine.capture_quality import (build_status_history, classify_availability_capture, classify_lineup_status,
                                          diff_status_snapshots, is_placeholder_availability_row)

S = Path(__file__).resolve().parent.parent / "docs" / "capture_workflows" / "phase11" / "samples"


def _jl(p):
    op = gzip.open if str(p).endswith(".gz") else open
    with op(p, "rt") as f:
        return [json.loads(x) for x in f if x.strip()]


PLACEHOLDER = {"status": "available", "native_status": "Active", "confidence": "no_report", "injury_status": None,
               "injury_comment": None, "injury_type": None, "injury_date": None, "status_changed": False}


class CbbAvailability(unittest.TestCase):
    def test_empty_capture_unusable(self):
        self.assertEqual(classify_availability_capture([])["reason"], "EMPTY_CAPTURE")

    def test_placeholder_only_unusable(self):
        r = classify_availability_capture([dict(PLACEHOLDER)] * 5)
        self.assertFalse(r["usable"]); self.assertEqual(r["reason"], "PLACEHOLDER_ONLY")

    def test_empty_payload_reason(self):
        r = classify_availability_capture([dict(PLACEHOLDER)], {"injuries": []})
        self.assertFalse(r["usable"]); self.assertEqual(r["reason"], "EMPTY_SOURCE_PAYLOAD")

    def test_injury_row_makes_usable(self):
        row = dict(PLACEHOLDER, injury_status="Out", native_status="Out", confidence="reported")
        r = classify_availability_capture([dict(PLACEHOLDER), row])
        self.assertTrue(r["usable"]); self.assertEqual(r["evidence_rows"], 1)

    def test_non_default_native_status_is_evidence(self):
        self.assertFalse(is_placeholder_availability_row(dict(PLACEHOLDER, native_status="Questionable")))

    def test_real_archived_cbb_capture_is_unusable(self):
        rows = _jl(S / "cbb_availability_rows_20261110T194051Z_head4.jsonl")
        payload = json.loads((S / "cbb_league_injuries_20261110T194051Z.json").read_text())
        self.assertEqual(len(rows), 4)
        r = classify_availability_capture(rows, payload)
        self.assertFalse(r["usable"]); self.assertEqual(r["reason"], "EMPTY_SOURCE_PAYLOAD")


class LineupStatus(unittest.TestCase):
    START = "2026-11-10T01:00:00Z"

    def test_confirmed_pregame_verified(self):
        r = classify_lineup_status({"source": "dailyfaceoff", "status": "CONFIRMED", "observed_at_utc": "2026-11-09T22:38:45Z",
                                    "source_reported_at_utc": "2026-11-09T16:43:56Z"}, self.START)
        self.assertEqual(r["class"], "VERIFIED_PREGAME"); self.assertEqual(r["minutes_to_start"], 141.2)

    def test_probable_is_projected(self):
        self.assertEqual(classify_lineup_status({"source": "dailyfaceoff", "status": "PROBABLE", "observed_at_utc": "2026-11-09T22:38:45Z"}, self.START)["class"], "PROJECTED")

    def test_cfb_prior_game_passer_never_verified(self):
        r = classify_lineup_status({"source": "pf_cfb_prior_game_passer", "status": "STARTING", "certainty": "PROJECTED",
                                    "observed_at_utc": "2026-11-09T22:38:45Z"}, self.START)
        self.assertEqual(r["class"], "PROJECTED")

    def test_confirmed_after_start_is_postgame(self):
        r = classify_lineup_status({"source": "dailyfaceoff", "status": "CONFIRMED", "observed_at_utc": "2026-11-10T01:05:00Z"}, self.START)
        self.assertEqual(r["class"], "POSTGAME_ACTUAL")

    def test_boxscore_pregame_not_a_report(self):
        self.assertEqual(classify_lineup_status({"source": "nhl_api_boxscore", "status": "CONFIRMED", "observed_at_utc": "2026-11-09T20:00:00Z"}, self.START)["class"], "UNKNOWN")

    def test_generic_active_nfl_unknown(self):
        self.assertEqual(classify_lineup_status({"source": "espn_injuries", "status": "Active", "observed_at_utc": "2026-11-09T20:00:00Z"}, self.START)["class"], "UNKNOWN")

    def test_missing_time_unknown(self):
        self.assertEqual(classify_lineup_status({"status": "CONFIRMED"}, self.START)["class"], "UNKNOWN")

    def test_clock_anomaly_not_verified(self):
        r = classify_lineup_status({"source": "dailyfaceoff", "status": "CONFIRMED", "observed_at_utc": "2026-11-09T20:00:00Z",
                                    "source_reported_at_utc": "2026-11-09T21:00:00Z"}, self.START)
        self.assertEqual(r["class"], "UNKNOWN")

    def test_real_nhl_rows(self):
        rows = _jl(S / "nhl_20261109T223826Z.jsonl.gz")
        classes = {}
        for r in rows:
            c = classify_lineup_status(r, r["note"].split("game_time_gmt=")[1])["class"]
            classes[c] = classes.get(c, 0) + 1
        self.assertEqual(classes, {"VERIFIED_PREGAME": 4, "PROJECTED": 16})


class History(unittest.TestCase):
    def test_diff_upgrade_downgrade_player_change(self):
        a = [{"game_id": 1, "team_id": 1, "player_name": "A", "status": "PROJECTED"},
             {"game_id": 2, "team_id": 2, "player_name": "B", "status": "CONFIRMED"},
             {"game_id": 3, "team_id": 3, "player_name": "C", "status": "PROBABLE"},
             {"game_id": 4, "team_id": 4, "player_name": "D", "status": "PROBABLE"}]
        b = [{"game_id": 1, "team_id": 1, "player_name": "A", "status": "CONFIRMED"},
             {"game_id": 2, "team_id": 2, "player_name": "B", "status": "PROBABLE"},
             {"game_id": 3, "team_id": 3, "player_name": "E", "status": "CONFIRMED"},
             {"game_id": 5, "team_id": 5, "player_name": "F", "status": "PROJECTED"}]
        t = sorted(e["type"] for e in diff_status_snapshots(a, b))
        self.assertEqual(t, ["DISAPPEARED", "FIRST_SEEN", "PLAYER_CHANGE", "STATUS_DOWNGRADE", "STATUS_UPGRADE"])

    def test_history_orders_by_time(self):
        obs = [{"game_id": 1, "team_id": 1, "player_name": "A", "status": "CONFIRMED", "observed_at_utc": "2026-01-01T02:00:00Z"},
               {"game_id": 1, "team_id": 1, "player_name": "B", "status": "PROJECTED", "observed_at_utc": "2026-01-01T01:00:00Z"}]
        h = build_status_history(obs)[("1", "1")]
        self.assertEqual([e["type"] for e in h["events"]], ["FIRST_SEEN", "PLAYER_CHANGE"])
        self.assertEqual(h["final_player"], "A"); self.assertTrue(h["changed_after_first"])

    def test_real_nhl_consecutive_snapshots(self):
        a = _jl(S / "nhl_20261109T223826Z.jsonl.gz"); b = _jl(S / "nhl_20261109T230827Z.jsonl.gz")
        ev = diff_status_snapshots(a, b)
        self.assertTrue(all(e["type"] in {"STATUS_UPGRADE", "STATUS_DOWNGRADE", "PLAYER_CHANGE", "FIRST_SEEN", "DISAPPEARED"} for e in ev))
        # the archive holds 2 sources per team in some files: sanity that the diff is deterministic and keyed per game/team
        self.assertEqual(ev, diff_status_snapshots(a, b))


if __name__ == "__main__":
    unittest.main()
