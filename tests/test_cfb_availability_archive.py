"""Offline, adversarial qualification tests for an existing live CFB injury archive."""
import copy
import unittest

from alpha_engine import cfb_availability_archive as cfb


def row(kind="roster", status="UNKNOWN", certainty="UNKNOWN", source="espn_core_injuries",
        entity="team:1", captured="2026-11-03T18:28:07Z", kickoff="2026-11-06T23:00:00Z",
        updated=None, detail=None):
    return {
        "schema": "sift.availability.v1", "sport": "CFB", "event_id": "40100001",
        "event_start_utc": kickoff, "entity_id": entity, "entity_name": entity,
        "team": "Example State", "kind": kind, "status": status,
        "certainty": certainty, "source": source, "captured_utc": captured,
        "source_updated_utc": updated, "detail": detail or {},
    }


class CFBArchiveAuditTest(unittest.TestCase):
    def test_fixture_never_promotes_espn_sentinel_or_projected_qb_to_confirmed(self):
        rows = [
            row(detail={"injury_list_read": True, "listed": 1}),
            row(kind="injury", entity="player-7", status="OUT", certainty="REPORTED",
                updated="2026-11-03T12:00:00Z", detail={"stale": False}),
            row(kind="starter", entity="prior-passer", status="STARTING",
                certainty="PROJECTED", source="pf_cfb_prior_game_passer"),
            row(kind="injury", entity="old-injury", status="UNKNOWN", certainty="UNKNOWN",
                updated="2022-08-01T12:00:00Z", detail={"stale": True}),
            row(kind="roster", entity="late-team", captured="2026-11-07T12:00:00Z"),
        ]
        result = cfb.audit_rows(rows)
        counts = result["counts"]
        self.assertEqual(counts["rows"], 5)
        self.assertEqual(counts["at_or_after_kickoff_excluded"], 1)
        self.assertEqual(counts["pre_kickoff_observations"], 4)
        self.assertEqual(counts["fresh_reported_injury_designations"], 1)
        self.assertEqual(counts["injury_listings_source_marked_stale"], 1)
        self.assertEqual(counts["projected_starters_not_confirmed"], 1)
        self.assertEqual(counts["espn_team_lists_read"], 1)
        self.assertEqual(counts.get("confirmed_lineup_or_starter_statements", 0), 0)
        self.assertEqual(result["player_participation_completeness"], "NOT_ESTABLISHED")
        self.assertEqual(result["trading_authority"], "NONE")

    def test_anti_leakage_and_source_provenance(self):
        bad = [
            dict(row(), captured_utc="2026-11-03T13:00:00-05:00"),
            dict(row(), source_updated_utc="2026-11-04T12:00:00Z"),
            dict(row(), schema="other"),
            dict(row(), certainty="IMPLIED_ACTIVE"),
            dict(row(), entity_id=""),
        ]
        for one in bad:
            with self.subTest(one=one):
                with self.assertRaises(ValueError):
                    cfb.audit_rows([one])
        with self.assertRaises(ValueError):
            cfb.audit_rows([row(), copy.deepcopy(row())])

    def test_only_exact_pinned_repository_revision_and_blob_are_allowed(self):
        import json
        from pathlib import Path
        p = json.loads(Path("research/audit/lineage/cfb_availability_archive_pin.json").read_text())
        self.assertEqual(cfb.validate_pin(p), p)
        for field, changed in (("source_bytes", 0), ("source_commit", "main"),
                               ("source_path", "../outside.jsonl.gz"), ("source_git_blob_sha1", "0" * 40)):
            q = dict(p)
            q[field] = changed
            with self.subTest(field=field), self.assertRaises(ValueError):
                cfb.validate_pin(q)
        with self.assertRaises(ValueError):
            cfb.load_rows(p, b"not a Git-pinned compressed blob")


if __name__ == "__main__":
    unittest.main()
