"""Time-travel CFB game/market record tests (not backtested profitability)."""
import copy
import unittest
from alpha_engine.cfb_game_context import assemble_cfb_game_timeline

def one_game(research="2026-10-10T19:10:00Z", quote="2026-10-10T18:20:00Z"):
    return {
        "schema": "cfb_control_prospective_settlement/1.0.0",
        "game_key": "G1", "event_id": "401001",
        "kickoff_utc": "2026-10-10T19:30:00Z",
        "teams": {"away": {"name": "A"}, "home": {"name": "B"}},
        "capture": {"status": "CAPTURE_OK", "market_ticker": "KXNCAAFGAME-G1-B",
                    "entry": {"captured_at": quote, "price": 0.65},
                    "window_opens_at": "2026-10-10T16:30:00Z",
                    "window_closes_at": "2026-10-10T18:30:00Z"},
        "final_pregame": {"recorded_at": research, "data_quality": "HIGH",
                          "claims_artifact_hash": "a" * 64},
        "settled_at": "2026-10-10T23:30:00Z",
        "settlement": {"status": "SETTLED", "control_won": True,
                       "control_points": 25, "opponent_points": 12},
    }


class GameContextTests(unittest.TestCase):
    def test_research_after_price_cannot_be_known_at_quote(self):
        x = assemble_cfb_game_timeline([one_game()])
        self.assertEqual(x["quote_coverage"]["quote_before_research"], 1)
        quote = next(z for z in x["game_examples"][0]["events"] if z["kind"] == "KALSHI_MARKET_PRICE_CAPTURE")
        self.assertEqual(quote["research_availability_at_quote"], "RESEARCH_NOT_YET_PUBLISHED")
        self.assertEqual(x["game_examples"][0]["events"][-1]["kind"], "POSTGAME_SCORE_OBSERVED")
        self.assertEqual(x["game_examples"][0]["physical_game_id_system"].startswith("ESPN"), True)

    def test_research_before_quote_is_different_asof_state(self):
        x = assemble_cfb_game_timeline([one_game(research="2026-10-10T17:45:00Z")])
        self.assertEqual(x["quote_coverage"]["research_before_or_at_quote"], 1)
        q = next(z for z in x["game_examples"][0]["events"] if z["kind"] == "KALSHI_MARKET_PRICE_CAPTURE")
        self.assertEqual(q["research_availability_at_quote"], "RESEARCH_KNOWN_AT_CAPTURE")

    def test_missing_quote_stays_in_denominator(self):
        g=one_game()
        g["capture"]["entry"]=None
        g["capture"]["status"]="PRICE_1_00"
        g["event_id"] = "401002"
        g["game_key"] = "G2"
        other = one_game()
        x = assemble_cfb_game_timeline([other, g])
        self.assertEqual(x["game_count"], 2)
        self.assertEqual(x["quote_coverage"]["unpriced_games"], 1)
        self.assertEqual(x["data_quality"]["n_excluded"], 1)
        self.assertTrue(all(event["kind"] != "KALSHI_MARKET_PRICE_CAPTURE"
                            for event in x["game_examples"][1]["events"]))

    def test_leaked_timestamp_fails_entire_context_join(self):
        g=one_game()
        g["final_pregame"]["recorded_at"]="2026-10-10T19:50:00Z"
        with self.assertRaises(ValueError):
            assemble_cfb_game_timeline([g])


if __name__ == "__main__":
    unittest.main()
