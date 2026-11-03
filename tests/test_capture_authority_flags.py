"""Fail-closed authority regression for immutable public-series capture manifests."""
import unittest
from tempfile import TemporaryDirectory

from alpha_engine.series_pagination import verify_capture


class CaptureAuthorityTests(unittest.TestCase):
    def test_forged_authority_flags_rejected_before_source_read(self):
        baseline = {
            "schema_version": 2,
            "authority": "RESEARCH_ONLY_NO_EXECUTION",
            "source_scope": "PUBLIC_OPEN_MARKETS_ONLY",
            "complete_series_or_market_tape": False,
            "actual_start_or_settlement_verified": False,
            "pregame_or_forecast_join_verified": False,
        }
        with TemporaryDirectory() as root:
            for field in (
                "actual_start_or_settlement_verified",
                "pregame_or_forecast_join_verified",
            ):
                forged = dict(baseline, **{field: True})
                with self.subTest(field=field):
                    with self.assertRaisesRegex(ValueError, "Untrusted capture manifest"):
                        verify_capture(root, forged)

    def test_missing_authority_flags_fail_closed(self):
        baseline = {
            "schema_version": 2,
            "authority": "RESEARCH_ONLY_NO_EXECUTION",
            "source_scope": "PUBLIC_OPEN_MARKETS_ONLY",
            "complete_series_or_market_tape": False,
        }
        with TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "Untrusted capture manifest"):
                verify_capture(root, baseline)


if __name__ == "__main__":
    unittest.main()
