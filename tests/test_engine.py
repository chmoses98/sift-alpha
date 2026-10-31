"""Deliberately adversarial checks: fail closed on cost, leakage, claims."""
import json
import unittest

from alpha_engine.core import (
    audit_prediction_rows, audit_project, audit_source,
    decide_next, fingerprint, reject_cost, utc_time,
)


def validated_source(identifier="s1"):
    return {
        "id": identifier, "provider": "test verified fixture",
        "source_url": "https://example.org/free", "access_class": "public_free",
        "charge_mode": "none", "estimated_usd": 0, "cost_verified": True,
        "license_status": "reviewed", "temporal_status": "verified",
        "schema_status": "verified",
    }


def project(identifier="p1", sport="NBA"):
    return {
        "id": identifier, "sport": sport, "question": "Does a preregistered matchup improve unseen forecast?",
        "mechanism": "matchup structure", "null_hypothesis": "no held-out improvement",
        "target": "pregame count", "unit": "player-game",
        "confounders": ["minutes"], "sources": ["s1"], "priority": 90,
    }


class CoreTests(unittest.TestCase):
    def test_source_only_ready_when_every_gate_passes(self):
        good = validated_source()
        self.assertTrue(audit_source(good)["ready"])
        for key, bad in [
            ("charge_mode", "metered"), ("access_class", "unknown"),
            ("cost_verified", False), ("estimated_usd", 0.01),
            ("license_status", "needs_review"), ("temporal_status", "needs_audit"),
            ("schema_status", "needs_audit"),
        ]:
            altered = {**good, key: bad}
            self.assertFalse(audit_source(altered)["ready"], key)

    def test_no_unknown_paid_or_unreviewed_provider_passes(self):
        for value in [{"charge_mode": "none", "estimated_usd": 0},
                      {"access_class": "public_free", "charge_mode": "none", "estimated_usd": 0}]:
            self.assertTrue(reject_cost(value))

    def test_director_never_confuses_qualification_with_experiment(self):
        p, s = project(), validated_source()
        ready = decide_next({"schema_version": 1, "projects": [p]}, {"schema_version": 1, "sources": [s]})
        self.assertEqual(ready["next"]["action"], "DESIGN_PROTOCOL")
        self.assertEqual(ready["status"], "WORK_PLANNED_NOT_EXECUTED")
        uncertain = {**s, "temporal_status": "needs_audit"}
        result = decide_next({"schema_version": 1, "projects": [p]}, {"schema_version": 1, "sources": [uncertain]})
        self.assertEqual(result["next"]["action"], "QUALIFY_DATA")
        not_yet_verified = {**s, "charge_mode": "unknown", "access_class": "unverified", "cost_verified": False}
        pending = decide_next({"schema_version": 1, "projects": [p]}, {"schema_version": 1, "sources": [not_yet_verified]})
        self.assertEqual(pending["next"]["action"], "QUALIFY_COST")
        self.assertIn("never access a billable endpoint", pending["next"]["reason"])
        paid = {**s, "charge_mode": "metered"}
        blocked = decide_next({"schema_version": 1, "projects": [p]}, {"schema_version": 1, "sources": [paid]})
        self.assertEqual(blocked["status"], "NO_ELIGIBLE_WORK")

    def test_avoids_favoring_same_sport_forever(self):
        a, b = project("nba", "NBA"), project("mlb", "MLB")
        registry = {"schema_version": 1, "sources": [validated_source()]}
        queue = {"schema_version": 1, "projects": [a, b]}
        self.assertEqual(decide_next(queue, registry)["next"]["project_id"], "mlb")
        self.assertEqual(decide_next(queue, registry, {"mlb": 2})["next"]["project_id"], "nba")

    def test_pregame_timestamps_and_unique_identity(self):
        good = {"event_id": "g1", "entity_id": "p1", "cutoff_at": "2026-10-30T16:00:00Z",
                "event_start_at": "2026-10-30T17:00:00Z",
                "feature_observed_at": "2026-10-30T15:00:00Z",
                "label_observed_at": "2026-10-30T20:00:00Z"}
        self.assertTrue(audit_prediction_rows([good], 1)["passed"])
        self.assertFalse(audit_prediction_rows([good], 2)["passed"])
        self.assertFalse(audit_prediction_rows([good, good], 1)["passed"])
        future = {**good, "feature_observed_at": "2026-10-30T18:00:00Z"}
        self.assertFalse(audit_prediction_rows([future], 1)["passed"])
        nonutc = {**good, "feature_observed_at": "2026-10-30T15:00:00-04:00"}
        self.assertFalse(audit_prediction_rows([nonutc], 1)["passed"])
        postgame = {**good, "cutoff_at": "2026-10-30T17:00:00Z"}
        self.assertFalse(audit_prediction_rows([postgame], 1)["passed"])
        self.assertFalse(audit_prediction_rows(None, 1)["passed"])

    def test_deterministic_fingerprinting(self):
        self.assertEqual(fingerprint({"a": 1, "b": 2}), fingerprint({"b": 2, "a": 1}))


if __name__ == "__main__":
    unittest.main()
