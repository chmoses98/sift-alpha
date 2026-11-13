"""Regression tests for the all-families NBA universe (alpha_eval.nba_universe): exact partition, honest categories, no silent drops."""
import gzip
import json
import os
import tempfile
import unittest

from alpha_eval import nba_universe as U
from alpha_eval.grading import grade_all
from alpha_eval.report import build_report

GID = {"espn:1": dict(home="ORL", away="BOS", start="2026-11-01T20:30:00Z"),
       "espn:2": dict(home="DEN", away="UTA", start="2026-11-02T00:00:00Z")}


def mk(ticker, series, family, support="MODELABLE", seen="2026-11-01T10:00:00Z", status="active"):
    return dict(ticker=ticker, series_ticker=series, _family=family, _support=support, status=status, _observed_at_utc=seen)


def board_dir(tmp, files):
    for i, rows in enumerate(files):
        with gzip.open(os.path.join(tmp, f"kalshi_markets_{i:03d}.jsonl.gz"), "wt") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    return tmp


ROWS = [
    mk("KXNBAPTS-26NOV01BOSORL-ORLJSMITH3-10", "KXNBAPTS", "player_points"),            # graded
    mk("KXNBAPTS-26NOV01BOSORL-ORLJSMITH3-15", "KXNBAPTS", "player_points"),            # game forecast, market not forecast
    mk("KXNBAPTS-26NOV01UTADEN-DENXJONES7-10", "KXNBAPTS", "player_points"),            # game has no shadow forecast
    mk("KXNBASPREAD-26NOV01BOSORL-ORL5", "KXNBASPREAD", "game_spread"),                 # frozen input exists, not evaluated
    mk("KXNBA1H-26NOV01BOSORL-BOS", "KXNBA1H", "period_winner", "BUILDABLE"),            # no frozen source
    mk("KXNBAMVP-26-JJOKIC", "KXNBAMVP", "awards", "UNMODELABLE"),                       # not game bound
    mk("KXNBAGAME-26OCT01BOSORL-BOS", "KXNBAGAME", "game_winner"),                       # before window
    mk("KXNBAGAME-26NOV20BOSORL-BOS", "KXNBAGAME", "game_winner"),                       # after horizon
    mk("KXNBAGAME-26NOV01XXXYYY-XXX", "KXNBAGAME", "game_winner"),                       # unmapped, in window
]


class Universe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.board = U.load_board(board_dir(self.tmp.name, [ROWS[:5], ROWS[3:] + [mk(ROWS[0]["ticker"], "KXNBAPTS", "player_points", status="finalized", seen="2026-11-03T00:00:00Z")]]))
        self.gx = U.game_index(GID)

    def tearDown(self):
        self.tmp.cleanup()

    def classify(self):
        return U.classify(self.board, self.gx, window_start="2026-10-20", horizon="2026-11-12")

    def test_board_is_a_union_of_snapshots_with_latest_state(self):
        m = self.board["markets"]
        self.assertEqual(len(m), len(ROWS))
        b = m[ROWS[0]["ticker"]]
        self.assertEqual((b["n_snapshots"], b["status"], b["first_seen"], b["last_seen"]), (2, "finalized", "2026-11-01T10:00:00Z", "2026-11-03T00:00:00Z"))

    def test_every_ticker_gets_exactly_one_class(self):
        cl = self.classify()
        self.assertEqual(len(cl), len(ROWS))
        self.assertEqual({t: r["cls"] for t, r in cl.items()}, {
            ROWS[0]["ticker"]: "IN_WINDOW", ROWS[1]["ticker"]: "IN_WINDOW", ROWS[2]["ticker"]: "IN_WINDOW", ROWS[3]["ticker"]: "IN_WINDOW",
            ROWS[4]["ticker"]: "IN_WINDOW", ROWS[5]["ticker"]: U.NOT_GAME, ROWS[6]["ticker"]: U.BEFORE, ROWS[7]["ticker"]: U.FUTURE,
            ROWS[8]["ticker"]: U.UNMAPPED})

    def test_game_id_comes_from_the_independent_game_record(self):
        cl = self.classify()
        self.assertEqual(cl[ROWS[0]["ticker"]]["game_id"], "espn:1")
        self.assertEqual(cl[ROWS[2]["ticker"]]["game_id"], "espn:2")
        self.assertEqual(cl[ROWS[2]["ticker"]]["start"], "2026-11-02T00:00:00Z")

    def test_reconcile_is_an_exact_partition_with_honest_reasons(self):
        cl = self.classify()
        T = {r["ticker"]: r for r in ROWS}
        F = [dict(forecast_id="f1", sport="NBA", event_id="espn:1", market_id=ROWS[0]["ticker"], accuracy=dict(status="GRADED", reason="OK"))]
        rec = U.reconcile(cl, F, {ROWS[0]["ticker"]}, {("player_points", "espn:1")})
        self.assertEqual(sum(rec["totals"].values()), rec["n_board_tickers"], "partition must be exact")
        self.assertEqual(rec["totals"][U.GRADED_C], 1)
        self.assertEqual(rec["totals"][U.MARKET_NOT_FC], 1)                 # espn:1 has a forecast, the -15 rung does not
        self.assertEqual(rec["totals"][U.GAME_NOT_FC], 1)                   # espn:2 has none
        self.assertEqual(rec["totals"][U.FROZEN_NOT_EVAL], 1)               # game_spread: frozen input exists, not evaluated
        self.assertEqual(rec["totals"][U.NO_SOURCE], 1)                     # period_winner
        self.assertEqual((rec["totals"][U.NOT_GAME], rec["totals"][U.BEFORE], rec["totals"][U.FUTURE], rec["totals"][U.UNMAPPED]), (1, 1, 1, 1))

    def test_support_label_is_description_not_evidence(self):
        cl = self.classify()
        rec = U.reconcile(cl, [], set(), set())
        # game_spread is labelled MODELABLE by the producer, yet it is NOT counted as forecast
        self.assertEqual(rec["by_family"]["game_spread"]["counts"], {U.FROZEN_NOT_EVAL: 1})
        self.assertEqual(rec["by_family"]["game_spread"]["support"], "MODELABLE")

    def test_a_forecast_for_one_family_never_excuses_another_family_in_the_same_game(self):
        cl = self.classify()
        # espn:1 has a game-level forecast only; its player_points markets must be GAME_HAS_NO forecast, not "market not forecast"
        rec = U.reconcile(cl, [], set(), {("game_spread", "espn:1")})
        self.assertEqual(rec["by_family"]["player_points"]["counts"].get(U.GAME_NOT_FC), 3)
        self.assertNotIn(U.MARKET_NOT_FC, rec["by_family"]["player_points"]["counts"])

    def test_market_not_forecast_is_split_into_three_measured_reasons(self):
        cl = self.classify()
        ffg = {("player_points", "espn:1")}
        out = U.market_not_forecast_reasons(cl, {ROWS[0]["ticker"]}, {ROWS[1]["ticker"]}, {"espn:1"}, ffg)
        self.assertEqual(out, {U.R_LISTED_NOT_FORECAST: 1})                      # -15 rung was listed but not forecast
        out = U.market_not_forecast_reasons(cl, {ROWS[0]["ticker"]}, set(), {"espn:1"}, ffg)
        self.assertEqual(out, {U.R_TICKER_ABSENT: 1})                            # game has listings, ticker absent
        out = U.market_not_forecast_reasons(cl, {ROWS[0]["ticker"]}, set(), set(), ffg)
        self.assertEqual(out, {U.R_NO_LISTING_CAPTURE: 1})                       # game never listing-captured
        self.assertEqual(U.market_not_forecast_reasons(cl, set(), set(), set(), set()), {})   # no forecast game -> a different category

    def test_forecast_not_graded_is_distinct_from_no_forecast(self):
        cl = self.classify()
        F = [dict(forecast_id="f1", sport="NBA", event_id="espn:1", market_id=ROWS[0]["ticker"], accuracy=dict(status="BLOCKED", reason="X"))]
        rec = U.reconcile(cl, F, {ROWS[0]["ticker"]}, {("player_points", "espn:1")})
        self.assertEqual((rec["totals"][U.NOT_GRADED_C], rec["totals"][U.GRADED_C]), (1, 0))

    def test_eligible_rows_feed_the_standards_coverage_and_cover_only_in_window_games(self):
        cl = self.classify()
        el = U.eligible_rows(cl)
        self.assertEqual(len(el), 5)
        self.assertTrue(all(e["sport"] == "NBA" and e["event_id"].startswith("espn:") for e in el))
        g = grade_all([], [], [], [], eligible_rows=el)
        cv = build_report(g)["coverage"]
        self.assertEqual((cv["n_eligible_markets"], cv["status_counts"]), (5, {"NO_FORECAST_FOR_ELIGIBLE_MARKET": 5}))
        self.assertEqual(cv["complete_eligible_market_coverage"], "INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
