"""Regression tests for derived game-level NBA forecasts (alpha_eval.nba_games): copula numerics, exact market semantics, event identity,
semantic-version keying, independent settle-engine cross-check, BACKTEST classing. Synthetic data only; no network."""
import gzip
import json
import math
import os
import tempfile
import unittest
from statistics import NormalDist

import numpy as np

from alpha_eval import nba_games as G
from alpha_eval.grading import grade_all

HOME, AWAY = "ORL", "BOS"


def pmf(mean, sd, lo, n):
    x = np.arange(lo, lo + n)
    p = np.exp(-0.5 * ((x - mean) / sd) ** 2)
    return p / p.sum()


PH, PA = pmf(114, 12, 54, 121), pmf(110, 12, 50, 120)


class Copula(unittest.TestCase):
    def test_normal_cdf_accuracy(self):
        xs = np.linspace(-6, 6, 241)
        err = max(abs(float(G._ndtr(x)) - NormalDist().cdf(x)) for x in xs)
        self.assertLess(err, 2e-7)

    def test_marginals_are_exact(self):
        J = G.joint_pmf(PH, PA, 0.2)
        self.assertLess(abs(J.sum(1) - PH).max(), 1e-12)
        self.assertLess(abs(J.sum(0) - PA).max(), 1e-12)
        self.assertAlmostEqual(J.sum(), 1.0, places=12)

    def test_independence_at_zero_rho_and_target_correlation(self):
        self.assertLess(abs(G.joint_pmf(PH, PA, 0.0) - np.outer(PH, PA)).max(), 1e-12)
        H, A = (54 + np.arange(121))[:, None], (50 + np.arange(120))[None, :]
        for rho in (0.2, 0.6, -0.3):
            J = G.joint_pmf(PH, PA, rho)
            m1, m2 = (J * H).sum(), (J * A).sum()
            c = (J * (H - m1) * (A - m2)).sum() / math.sqrt((J * (H - m1) ** 2).sum() * (J * (A - m2) ** 2).sum())
            self.assertAlmostEqual(c, rho, delta=0.01)

    def test_rejects_degenerate_rho(self):
        for bad in (1.0, -1.0, 1.5):
            with self.assertRaises(ValueError):
                G.joint_pmf(PH, PA, bad)

    def test_unnormalised_input_is_normalised(self):
        J = G.joint_pmf(PH * 7, PA * 3, 0.2)
        self.assertLess(abs(J.sum(1) - PH).max(), 1e-12)


class Semantics(unittest.TestCase):
    J = G.joint_pmf(PH, PA, 0.2)

    def p(self, series, team=None, n=None):
        return G.market_probability(series, team, n, self.J, 54, 50, HOME, AWAY)

    def test_moneyline_sides_sum_to_one_and_symmetric_case_is_half(self):
        self.assertAlmostEqual(self.p("KXNBAGAME", HOME) + self.p("KXNBAGAME", AWAY), 1.0, places=12)
        S = pmf(110, 12, 50, 120)
        Js = G.joint_pmf(S, S, 0.2)
        self.assertAlmostEqual(G.market_probability("KXNBAGAME", HOME, None, Js, 50, 50, HOME, AWAY), 0.5, places=6)

    def test_monotone_in_strike(self):
        spreads = [self.p("KXNBASPREAD", HOME, n) for n in range(1, 20)]
        totals = [self.p("KXNBATOTAL", None, n) for n in range(200, 250, 5)]
        teamt = [self.p("KXNBATEAMTOTAL", AWAY, n) for n in range(95, 125, 3)]
        for seq in (spreads, totals, teamt):
            self.assertTrue(all(a >= b for a, b in zip(seq, seq[1:])))

    def test_spread_one_equals_moneyline_given_no_tie(self):
        # margin >= 1 for the home team IS winning (ties are conditioned out)
        self.assertAlmostEqual(self.p("KXNBASPREAD", HOME, 1), self.p("KXNBAGAME", HOME), places=12)

    def test_outcome_boundaries_are_ge_n_which_is_floor_strike_n_minus_half(self):
        sc = {HOME: 110, AWAY: 105}
        self.assertEqual(G.market_outcome("KXNBASPREAD", HOME, 5, sc, HOME, AWAY), 1)       # margin 5 >= 5 (> 4.5)
        self.assertEqual(G.market_outcome("KXNBASPREAD", HOME, 6, sc, HOME, AWAY), 0)
        self.assertEqual(G.market_outcome("KXNBASPREAD", AWAY, 1, sc, HOME, AWAY), 0)       # away lost
        self.assertEqual(G.market_outcome("KXNBATOTAL", None, 215, sc, HOME, AWAY), 1)      # total 215 >= 215
        self.assertEqual(G.market_outcome("KXNBATOTAL", None, 216, sc, HOME, AWAY), 0)
        self.assertEqual(G.market_outcome("KXNBATEAMTOTAL", AWAY, 105, sc, HOME, AWAY), 1)
        self.assertEqual(G.market_outcome("KXNBATEAMTOTAL", AWAY, 106, sc, HOME, AWAY), 0)
        self.assertEqual(G.market_outcome("KXNBAGAME", HOME, None, sc, HOME, AWAY), 1)
        self.assertEqual(G.market_outcome("KXNBAGAME", AWAY, None, sc, HOME, AWAY), 0)

    def test_probability_and_outcome_use_the_same_event_definition(self):
        # a point-mass joint at (110, 105) must give probability 1 exactly when the outcome function says YES
        P1, P2 = np.zeros(121), np.zeros(120)
        P1[110 - 54], P2[105 - 50] = 1.0, 1.0
        Jd = np.outer(P1, P2)
        for series, team, n in (("KXNBASPREAD", HOME, 5), ("KXNBASPREAD", HOME, 6), ("KXNBATOTAL", None, 215), ("KXNBATOTAL", None, 216),
                                ("KXNBATEAMTOTAL", AWAY, 105), ("KXNBATEAMTOTAL", AWAY, 106), ("KXNBAGAME", HOME, None), ("KXNBAGAME", AWAY, None)):
            self.assertEqual(round(G.market_probability(series, team, n, Jd, 54, 50, HOME, AWAY)),
                             G.market_outcome(series, team, n, {HOME: 110, AWAY: 105}, HOME, AWAY), (series, team, n))

    def test_parse_market_shapes(self):
        self.assertEqual(G.parse_market("KXNBASPREAD-26NOV12TORPHI-TOR9"), ("KXNBASPREAD", "TOR", 9))
        self.assertEqual(G.parse_market("KXNBATOTAL-26NOV12TORPHI-249"), ("KXNBATOTAL", None, 249))
        self.assertEqual(G.parse_market("KXNBATEAMTOTAL-26NOV12TORPHI-TOR99"), ("KXNBATEAMTOTAL", "TOR", 99))
        self.assertEqual(G.parse_market("KXNBAGAME-26NOV16PORMIN-POR"), ("KXNBAGAME", "POR", None))
        for bad in ("KXNBAGAME-26NOV16PORMIN-POR5", "KXNBATOTAL-26NOV12TORPHI-TOR249", "KXNBASPREAD-26NOV12TORPHI-9", "KXNBA1H-26NOV12TORPHI-TOR", "x"):
            self.assertIsNone(G.parse_market(bad), bad)


def _w(root, rel, rows):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with gzip.open(p, "wt") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


START = "2026-11-01T20:30:00Z"
GAME = "espn:7"
EV = "26NOV01BOSORL"
T_ML, T_SP, T_TOT, T_TT = f"KXNBAGAME-{EV}-ORL", f"KXNBASPREAD-{EV}-ORL5", f"KXNBATOTAL-{EV}-215", f"KXNBATEAMTOTAL-{EV}-BOS105"
CLS = {t: dict(cls="IN_WINDOW", family=f, game_id=GAME, start=START)
       for t, f in ((T_ML, "game_winner"), (T_SP, "game_spread"), (T_TOT, "game_total"), (T_TT, "team_total"))}


def gf(generated, version="pf-1.3.0+aaa111", archived=None):
    return dict(archived_utc=archived or generated, away=AWAY, home=HOME, game_forecast_id=f"gf-{generated}", game_id=GAME, game_start_utc=START,
                generated_utc=generated, model_id="pf-nba-team_points", model_version=version, rho=0.2, schema="sift.game_forecast.v1",
                teams=[dict(team=AWAY, lo=50, mean=110.0, probs=PA.tolist()), dict(team=HOME, lo=54, mean=114.0, probs=PH.tolist())])


class Build(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.root = self.t.name
        _w(self.root, "game_forecasts/nba/2026-11-01/a.jsonl.gz", [gf("2026-11-01T10:00:00Z"), gf("2026-11-01T16:00:00Z", version="pf-1.3.0+bbb222")])
        _w(self.root, "team_outcomes/nba/2026-11-01/o.jsonl.gz", [
            dict(game_id=GAME, team=HOME, pts=110, final=True, observed_utc="2026-11-01T23:30:00Z"),
            dict(game_id=GAME, team=AWAY, pts=105, final=True, observed_utc="2026-11-01T23:31:00Z")])
        _w(self.root, "market_snapshots/nba/2026-11-01/s.jsonl.gz", [
            dict(ticker=T_ML, series="KXNBAGAME", board_observed_utc="2026-11-01T15:00:00Z", yes_bid=0.60, yes_ask=0.64),
            dict(ticker=None, board_observed_utc=None, series=None, status="MISSING")])
        self.gid = {GAME: dict(home=HOME, away=AWAY, start=START)}

    def tearDown(self):
        self.t.cleanup()

    def test_rows_identity_version_and_evidence_class(self):
        b = G.build(self.root, CLS, game_identity=self.gid)
        self.assertEqual(len(b["forecasts"]), 8)                                   # 2 forecasts x 4 markets
        self.assertTrue(all(f["event_id"] == GAME and f["group_id"] == GAME for f in b["forecasts"]))
        self.assertTrue(all(f["evidence_class"] == "BACKTEST" for f in b["forecasts"]))
        self.assertEqual({f["model_version"] for f in b["forecasts"]}, {"pf-1.3.0|alpha-derive:gauss-copula-notie-v1"})   # builds collapse
        self.assertEqual({f["meta"]["model_build"] for f in b["forecasts"]}, {"pf-1.3.0+aaa111", "pf-1.3.0+bbb222"})
        self.assertEqual((b["info"]["model_builds"], b["info"]["model_versions_semantic"]), (2, 1))
        self.assertEqual(b["info"]["identity[IDENTITY_VERIFIED]"], 4)
        self.assertTrue(all(0 < f["payload"]["p_yes"] < 1 for f in b["forecasts"]))

    def test_outcomes_follow_final_scores_and_grade_with_a_pit_quote(self):
        b = G.build(self.root, CLS, game_identity=self.gid)
        y = {o["market_id"]: o["value"] for o in b["outcomes"]}
        self.assertEqual(y, {T_ML: 1, T_SP: 1, T_TOT: 1, T_TT: 1})
        g = grade_all(b["forecasts"], b["outcomes"], b["quotes"], [])
        ml = [r for r in g["rows"] if r["market_id"] == T_ML]
        self.assertTrue(all(r["accuracy"]["status"] == "GRADED" for r in ml))
        self.assertEqual({r["market"]["status"] for r in ml}, {"GRADED", "BLOCKED"})        # 16:00 forecast: quote is 1h old -> still within limit or stale
        self.assertTrue(all(q["observed_at"] <= "2026-11-01T16:00:00Z" for q in b["quotes"]))

    def test_settle_engine_agreement_and_disagreement(self):
        agree = {T_SP: dict(ticker=T_SP, outcome="YES", reason="x")}
        b = G.build(self.root, CLS, settlements=agree, game_identity=self.gid)
        self.assertEqual(b["info"]["outcome_xcheck[AGREE]"], 1)
        bad = {T_SP: dict(ticker=T_SP, outcome="NO", reason="x")}
        b = G.build(self.root, CLS, settlements=bad, game_identity=self.gid)
        g = grade_all(b["forecasts"], b["outcomes"], b["quotes"], [])
        self.assertEqual({r["accuracy"]["reason"] for r in g["rows"] if r["market_id"] == T_SP}, {"CONFLICTING_OUTCOME_ROWS_FOR_MARKET"})

    def test_ticker_identity_mismatch_blocks_via_the_event_join(self):
        b = G.build(self.root, CLS, game_identity={GAME: dict(home=AWAY, away=HOME, start=START)})
        g = grade_all(b["forecasts"], b["outcomes"], b["quotes"], [])
        self.assertEqual({r["accuracy"]["reason"] for r in g["rows"]}, {"OUTCOME_EVENT_ID_DOES_NOT_MATCH_FORECAST"})
        self.assertTrue(all(f["event_id"] == GAME for f in b["forecasts"]))

    def test_archived_after_start_is_not_frozen(self):
        _w(self.root, "game_forecasts/nba/2026-11-01/late.jsonl.gz", [gf("2026-11-01T20:00:00Z", archived="2026-11-01T21:00:00Z")])
        b = G.build(self.root, CLS, game_identity=self.gid)
        late = [f for f in b["forecasts"] if f["meta"]["archived_utc"] == "2026-11-01T21:00:00Z"]
        self.assertTrue(late and all(f["frozen_at"] == "2026-11-01T21:00:00Z" for f in late))
        g = grade_all(b["forecasts"], b["outcomes"], b["quotes"], [])
        self.assertIn("FORECAST_NOT_FROZEN_BEFORE_EVENT_START", {r["accuracy"]["reason"] for r in g["rows"]})

    def test_markets_outside_the_universe_get_no_forecast(self):
        cls = {T_ML: CLS[T_ML], "KXNBASPREAD-26NOV01BOSORL-ORL5": dict(CLS[T_SP], cls="GAME_BEFORE_FORECAST_WINDOW")}
        b = G.build(self.root, cls, game_identity=self.gid)
        self.assertEqual({f["market_id"] for f in b["forecasts"]}, {T_ML})

    def test_unparseable_market_shape_is_counted(self):
        cls = dict(CLS)
        cls["KXNBAGAME-26NOV01BOSORL-ORL5"] = dict(cls="IN_WINDOW", family="game_winner", game_id=GAME, start=START)
        self.assertEqual(G.build(self.root, cls, game_identity=self.gid)["info"]["unparseable_market_shape"], 1)


if __name__ == "__main__":
    unittest.main()
