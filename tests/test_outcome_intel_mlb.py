"""Unit tests for the MLB outcome-intelligence audit (RESEARCH_ONLY): time-window/leakage, settlement derivation, dedup, split ordering, controls."""
import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research", "outcome_intel"))
import incremental as I  # noqa: E402
import mlb_data as D  # noqa: E402
import mlb_incremental as M  # noqa: E402
import mlb_pinnacle as P  # noqa: E402


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


class TimeWindowLeakage(unittest.TestCase):
    def test_time_valid_requires_before_decision_and_before_first_pitch(self):
        fp = utc(2026, 8, 1, 20, 0)
        self.assertTrue(D.is_time_valid(utc(2026, 8, 1, 19, 0), utc(2026, 8, 1, 19, 30), fp))
        self.assertFalse(D.is_time_valid(utc(2026, 8, 1, 19, 45), utc(2026, 8, 1, 19, 30), fp))  # observed after the decision
        self.assertFalse(D.is_time_valid(utc(2026, 8, 1, 19, 0), utc(2026, 8, 1, 20, 0), fp))  # decision at first pitch
        self.assertFalse(D.is_time_valid(utc(2026, 8, 1, 20, 1), utc(2026, 8, 1, 20, 5), fp))  # post-start capture
        self.assertFalse(D.is_time_valid(None, utc(2026, 8, 1, 19, 0), fp))

    def _panel(self, rows):
        base = dict(marketTicker="KXMLBGAME-26AUG012000AAABBB-AAA", mlbGameId=None, gameId=None, marketFamily="game_result", checkpoint="INTERMEDIATE",
                    yesBid=50.0, yesAsk=54.0, noBid=None, noAsk=None, lastPrice=None, volume=1, openInterest=1, threshold=None, comparisonOperator="OVER",
                    team="AAA", homeTeam="AAA", awayTeam="BBB", isValidPregameObservation=True, isClosingCandidate=False, marketStatus="active", title="", player=None,
                    seriesTicker="KXMLBGAME", lineupConfirmationState=None, eventTicker="e", scheduledStart=None)
        df = pd.DataFrame([dict(base, **r) for r in rows])
        df["t_cap"] = pd.to_datetime(df["capturedAt"], utc=True)
        df["t_start"] = pd.to_datetime(df["scheduledStart"], utc=True)
        return df

    def test_panel_uses_earliest_known_start_so_reschedule_only_removes_rows(self):
        games = pd.DataFrame([dict(gamePk=1, gameDate="2026-08-01T21:00:00Z", homeId=1, awayId=2, gameNumber=1)])
        obs = self._panel([dict(capturedAt="2026-08-01T19:30:00Z", scheduledStart="2026-08-01T20:00:00Z", mlbGameId=1.0),
                           dict(capturedAt="2026-08-01T20:30:00Z", scheduledStart="2026-08-01T20:00:00Z", mlbGameId=1.0)])
        P_ = D.build_panel(obs, games)
        # obs says 20:00Z, schedule 21:00Z, ticker 20:00 ET=00:00Z next day -> earliest known start 20:00Z
        self.assertEqual(P_["t_fp"].iloc[0], pd.Timestamp("2026-08-01T20:00:00Z"))
        q = D.pregame_quotes(P_)
        self.assertEqual(len(q), 1)  # the 20:30 capture is after the earliest known first pitch
        self.assertTrue((q["mins_before"] > 0).all())

    def test_mid_requires_two_sided_uncrossed_quote(self):
        self.assertAlmostEqual(D.mid_cents(40.0, 44.0), 0.42)
        self.assertIsNone(D.mid_cents(None, 44.0))
        self.assertIsNone(D.mid_cents(46.0, 44.0))

    def test_decision_quote_is_inside_window_and_latest(self):
        t0 = pd.Timestamp("2026-08-01T20:00:00Z")
        rows = []
        for m, mid in ((300, .40), (45, .50), (20, .55), (5, .90)):
            rows.append(dict(marketTicker="T1", family="moneyline", pk=1.0, gc="g", t_fp=t0, t_cap=t0 - pd.Timedelta(minutes=m), mins_before=float(m), mid=mid, two_sided_ok=True))
        Q = pd.DataFrame(rows)
        d = M.decision_quotes(Q, "NEAR")
        self.assertEqual(len(d), 1)
        self.assertEqual(float(d["mid"].iloc[0]), .55)  # not the 5-minute quote (outside 10-60 window) and not the stale one
        self.assertTrue((d["mins_before"] >= 10).all() and (d["mins_before"] <= 60).all())

    def test_trajectory_challenger_is_strictly_older_than_decision(self):
        t0 = pd.Timestamp("2026-08-01T20:00:00Z")
        rows = [dict(marketTicker="T1", family="moneyline", pk=1.0, gc="g", t_fp=t0, t_cap=t0 - pd.Timedelta(minutes=m), mins_before=float(m), mid=mid, two_sided_ok=True)
                for m, mid in ((400, .40), (40, .50))]
        Q = pd.DataFrame(rows)
        Y = pd.DataFrame({"y": [1.0]}, index=["T1"])
        base, traj = M.rows_trajectory(Q, Y, "moneyline", "NEAR")
        self.assertEqual(len(traj), 1)
        self.assertAlmostEqual(traj[0]["q"], .40)
        self.assertAlmostEqual(traj[0]["mid"], .50)
        # a decision quote only 30 minutes after the 'earlier' quote must NOT produce a trajectory row
        Q2 = pd.DataFrame([dict(r, mins_before=m, t_cap=t0 - pd.Timedelta(minutes=m)) for r, m in zip(rows, (70.0, 40.0))])
        self.assertEqual(len(M.rows_trajectory(Q2, Y, "moneyline", "NEAR")[1]), 0)

    def test_future_information_cannot_enter_challenger(self):
        # a model run AFTER the quote used as baseline is allowed (baseline is the last quote at/before the run), but never a quote AFTER the run
        t0 = pd.Timestamp("2026-08-01T20:00:00Z")
        q = pd.DataFrame([dict(marketTicker="T1", family="moneyline", pk=1.0, gc="g", team="A", homeTeam="A", t_fp=t0, two_sided_ok=True,
                               t_cap=t0 - pd.Timedelta(minutes=m), mins_before=float(m), mid=mid) for m, mid in ((90, .45), (50, .80))])
        run = t0 - pd.Timedelta(minutes=60)
        prior = q[(q["t_cap"] <= run) & (q["t_cap"] >= run - pd.Timedelta(minutes=60)) & (q["mins_before"] > 0)]
        self.assertEqual(list(prior["mid"]), [.45])


class SettlementDerivation(unittest.TestCase):
    def test_moneyline(self):
        self.assertEqual(D.derive_from_ticker("KXMLBGAME-26AUG012000BBBAAA-AAA", "moneyline", "AAA", "BBB", 5, 3), 1)
        self.assertEqual(D.derive_from_ticker("KXMLBGAME-26AUG012000BBBAAA-BBB", "moneyline", "AAA", "BBB", 5, 3), 0)
        self.assertIsNone(D.derive_from_ticker("KXMLBGAME-26AUG012000BBBAAA-CCC", "moneyline", "AAA", "BBB", 5, 3))
        self.assertIsNone(D.derive_from_ticker("KXMLBGAME-26AUG012000BBBAAA-AAA", "moneyline", "AAA", "BBB", 3, 3))  # tie -> not derivable

    def test_total_is_at_least_N_not_strictly_over(self):
        t = "KXMLBTOTAL-26AUG012000BBBAAA-9"
        self.assertEqual(D.derive_from_ticker(t, "game_total", "AAA", "BBB", 5, 4), 1)  # total == N -> YES
        self.assertEqual(D.derive_from_ticker(t, "game_total", "AAA", "BBB", 5, 3), 0)
        self.assertEqual(D.derive_from_ticker(t, "game_total", "AAA", "BBB", 6, 4), 1)

    def test_team_total_and_run_line(self):
        self.assertEqual(D.derive_from_ticker("KXMLBTEAMTOTAL-26AUG012000BBBAAA-AAA5", "team_total", "AAA", "BBB", 5, 1), 1)
        self.assertEqual(D.derive_from_ticker("KXMLBTEAMTOTAL-26AUG012000BBBAAA-BBB2", "team_total", "AAA", "BBB", 5, 1), 0)
        self.assertEqual(D.derive_from_ticker("KXMLBSPREAD-26AUG012000BBBAAA-AAA2", "run_line", "AAA", "BBB", 5, 3), 1)  # wins by >=2
        self.assertEqual(D.derive_from_ticker("KXMLBSPREAD-26AUG012000BBBAAA-AAA3", "run_line", "AAA", "BBB", 5, 3), 0)
        self.assertEqual(D.derive_from_ticker("KXMLBSPREAD-26AUG012000BBBAAA-BBB1", "run_line", "AAA", "BBB", 5, 3), 0)

    def test_unsupported_family_and_missing_score_are_none(self):
        self.assertIsNone(D.derive_from_ticker("KXMLBF5-26AUG012000BBBAAA-AAA", "f5_result", "AAA", "BBB", 5, 3))
        self.assertIsNone(D.derive_from_ticker("KXMLBGAME-26AUG012000BBBAAA-AAA", "moneyline", "AAA", "BBB", None, 3))

    def test_suffix_parsing(self):
        self.assertEqual(D.parse_suffix("KXMLBTOTAL-26AUG012000BBBAAA-9"), (None, 9))
        self.assertEqual(D.parse_suffix("KXMLBTEAMTOTAL-26AUG012000BBBAAA-AAA10"), ("AAA", 10))
        self.assertEqual(D.parse_suffix("KXMLBGAME-26AUG012000BBBAAA-AAA"), ("AAA", None))

    def test_total_boundary_rederivation_overrides_stored_strict_over(self):
        panel = pd.DataFrame([dict(marketTicker="KXMLBTOTAL-26AUG012000BBBAAA-9", family="game_total", pk=1.0, homeTeam="AAA", awayTeam="BBB",
                                   t_fp=pd.Timestamp("2026-08-02T00:00:00Z"))])
        games = pd.DataFrame([dict(gamePk=1, state="Final", homeRuns=5.0, awayRuns=4.0)])
        settle = pd.DataFrame([dict(marketTicker="KXMLBTOTAL-26AUG012000BBBAAA-9", status="SETTLED", result="NO", updatedAt="2026-08-10T00:00:00Z")])
        Y = D.build_outcomes(panel, games, settle)
        self.assertEqual(float(Y.loc["KXMLBTOTAL-26AUG012000BBBAAA-9", "y"]), 1.0)  # total 9 >= 9 -> YES even though the stored row says NO
        self.assertEqual(float(Y.loc["KXMLBTOTAL-26AUG012000BBBAAA-9", "y_edgelab"]), 0.0)

    def test_live_schedule_record_is_not_a_final_score(self):
        panel = pd.DataFrame([dict(marketTicker="KXMLBGAME-26AUG012000BBBAAA-AAA", family="moneyline", pk=1.0, homeTeam="AAA", awayTeam="BBB", t_fp=pd.Timestamp("2026-08-02T00:00:00Z"))])
        games = pd.DataFrame([dict(gamePk=1, state="Live", homeRuns=0.0, awayRuns=0.0)])
        settle = pd.DataFrame([dict(marketTicker="KXMLBGAME-26AUG012000BBBAAA-AAA", status="SETTLED", result="YES", updatedAt="x")])
        Y = D.build_outcomes(panel, games, settle)
        self.assertTrue(np.isnan(Y["y_indep"].iloc[0]))  # 0-0 of a live game must not be used to re-derive an outcome

    def test_total_boundary_unverifiable_is_dropped_not_guessed(self):
        panel = pd.DataFrame([dict(marketTicker="KXMLBTOTAL-26AUG012000BBBAAA-9", family="game_total", pk=1.0, homeTeam="AAA", awayTeam="BBB",
                                   t_fp=pd.Timestamp("2026-08-02T00:00:00Z"))])
        games = pd.DataFrame([dict(gamePk=1, state="Final", homeRuns=np.nan, awayRuns=np.nan)])
        settle = pd.DataFrame([dict(marketTicker="KXMLBTOTAL-26AUG012000BBBAAA-9", status="SETTLED", result="NO", updatedAt="x")])
        Y = D.build_outcomes(panel, games, settle)
        self.assertTrue(np.isnan(Y.loc["KXMLBTOTAL-26AUG012000BBBAAA-9", "y"]))


class Dedup(unittest.TestCase):
    def test_prefers_settled_then_latest_and_counts_conflicts(self):
        df = pd.DataFrame([
            dict(marketTicker="A", status="SETTLEMENT_UNRESOLVED", result=None, updatedAt="2026-08-02"),
            dict(marketTicker="A", status="SETTLED", result="YES", updatedAt="2026-08-01"),
            dict(marketTicker="B", status="SETTLED", result="YES", updatedAt="2026-08-01"),
            dict(marketTicker="B", status="SETTLED", result="NO", updatedAt="2026-08-03"),
            dict(marketTicker="C", status="SETTLEMENT_UNRESOLVED", result=None, updatedAt="2026-08-01")])
        out, conflicts = D.dedup_settlements(df)
        self.assertEqual(len(out), 3)
        self.assertEqual(out.set_index("marketTicker").loc["A", "result"], "YES")
        self.assertEqual(out.set_index("marketTicker").loc["B", "result"], "NO")  # latest wins, but flagged
        self.assertEqual(conflicts, 1)

    def test_observation_dedup_on_ticker_and_capture_time(self):
        games = pd.DataFrame([dict(gamePk=1, gameDate="2026-08-01T21:00:00Z", homeId=1, awayId=2, gameNumber=1)])
        r = dict(marketTicker="KXMLBGAME-26AUG011700AAABBB-AAA", capturedAt="2026-08-01T19:00:00Z", scheduledStart="2026-08-01T21:00:00Z", mlbGameId=1.0, gameId=None,
                 marketFamily="game_result", checkpoint="X", yesBid=50., yesAsk=52., noBid=None, noAsk=None, lastPrice=None, volume=1, openInterest=1, threshold=None,
                 comparisonOperator="OVER", team="AAA", homeTeam="AAA", awayTeam="BBB", isValidPregameObservation=None, isClosingCandidate=None, marketStatus="active",
                 title="", player=None, seriesTicker="KXMLBGAME", lineupConfirmationState=None, eventTicker="e")
        df = pd.DataFrame([r, dict(r)])
        df["t_cap"] = pd.to_datetime(df["capturedAt"], utc=True)
        df["t_start"] = pd.to_datetime(df["scheduledStart"], utc=True)
        self.assertEqual(len(D.build_panel(df, games)), 1)


class SplitOrdering(unittest.TestCase):
    def test_season_split_ordered_and_disjoint(self):
        s = np.array([2022, 2023, 2024, 2025, 2026])
        tr, va, ho = D.season_split(s, (2022, 2023, 2024), (2025,), (2026,))
        self.assertEqual((tr.sum(), va.sum(), ho.sum()), (3, 1, 1))
        with self.assertRaises(ValueError):
            D.season_split(s, (2022, 2025), (2023,), (2026,))  # train after validation
        with self.assertRaises(ValueError):
            D.season_split(s, (2022,), (2022,), (2026,))  # overlap
        with self.assertRaises(ValueError):
            D.season_split(s, (2022,), (2025,), (2024,))  # holdout before validation

    def test_game_split_holdout_strictly_later(self):
        rows = [dict(game=i, t=f"2026-08-{1 + i // 3:02d}T{i % 3:02d}:00:00+00:00", mid=.5, q=.5, y=i % 2) for i in range(60)]
        tr, te = I.split_games(rows)
        first = {}
        for r in rows:
            first[r["game"]] = r["t"]
        self.assertLessEqual(max(first[g] for g in tr), min(first[g] for g in te))
        self.assertFalse(tr & te)

    def test_pinnacle_proxy_state_excludes_own_game(self):
        g = pd.DataFrame([dict(gamePk=i, season=2024, gameDate=f"2024-04-{i + 1:02d}T20:00:00Z", state="Final", homeId=1, awayId=2, homeRuns=float(i), awayRuns=1.0) for i in range(5)])
        st = P.team_state(g)
        self.assertEqual(st.loc[(0, 1), "n_prior"], 0)
        self.assertEqual(st.loc[(3, 1), "n_prior"], 3)
        self.assertAlmostEqual(st.loc[(3, 1), "rs_pg"], (0 + 1 + 2) / 3)  # game 3's own 3 runs are not in its own prior average

    def test_pinnacle_pregame_pick_rejects_post_start(self):
        c = utc(2024, 6, 10, 23, 0)
        pin = [dict(pk=1, commence=c, req=c + timedelta(minutes=5), home_fair=.5, price_time=c - timedelta(minutes=1)),
               dict(pk=1, commence=c, req=c - timedelta(minutes=40), home_fair=.5, price_time=c - timedelta(minutes=41)),
               dict(pk=2, commence=c, req=c - timedelta(minutes=120), home_fair=.5, price_time=c - timedelta(minutes=121)),
               dict(pk=3, commence=c, req=c - timedelta(minutes=30), home_fair=.5, price_time=c + timedelta(minutes=1))]
        best = P.pick_pregame(pin)
        self.assertEqual(set(best), {1})
        self.assertAlmostEqual(best[1]["mins_before"], 40.0)


class Controls(unittest.TestCase):
    def _rows(self, n=400, seed=0, plant=False):
        rng = np.random.default_rng(seed)
        out = []
        for i in range(n):
            mid = float(rng.uniform(.3, .7))
            y = int(rng.random() < mid)
            q = float(I.sigmoid(I.logit([mid])[0] + (0.8 * (2 * y - 1) if plant else rng.normal(0, .3))))
            out.append(dict(game=i, t=f"2026-08-{1 + i // 20:02d}T{i % 20:02d}:00:00+00:00", mid=mid, q=q, y=y))
        return out

    def test_positive_control_detected_and_negative_control_clean(self):
        planted = M.positive_control(self._rows())
        self.assertEqual(planted["status"], "OK")
        self.assertGreater(planted["gain_vs_calibrated_market_logloss"]["lo"], 0)
        rows = self._rows()
        nc = I.negative_control(rows)
        g = nc["gain_vs_calibrated_market_logloss"]
        self.assertTrue(g["lo"] <= 0 <= g["hi"])

    def test_noise_challenger_is_not_validated(self):
        res = I.incremental_test(self._rows(plant=False))
        self.assertEqual(res["status"], "OK")
        self.assertLessEqual(res["gain_vs_calibrated_market_logloss"]["mean"], 0.005)

    def test_classification_never_validates_without_holm(self):
        c = dict(status="OK", holdout_games=200, gain_vs_calibrated_market_logloss=dict(mean=.01, lo=.001, hi=.02, p=.03), holm_p=.4, negative_control_ok=True, _n_cells=30,
                 positive_control_detected=True, challenger="sift_model")
        st, _ = M.classify(c, 500, 300)
        self.assertEqual(st, "PROMISING_INSUFFICIENT")
        c["holm_p"] = .01
        self.assertEqual(M.classify(c, 500, 300)[0], "VALIDATED_IMPROVEMENT")
        c["negative_control_ok"] = False
        self.assertNotEqual(M.classify(c, 500, 300)[0], "VALIDATED_IMPROVEMENT")

    def test_underpowered_is_not_a_negative_result(self):
        c = dict(status="OK", holdout_games=30, gain_vs_calibrated_market_logloss=dict(mean=-.001, lo=-.05, hi=.05, p=.9), holm_p=1., negative_control_ok=True, _n_cells=30,
                 positive_control_detected=True, challenger="sift_model")
        self.assertEqual(M.classify(c, 80, 40)[0], "INCONCLUSIVE_UNDERPOWERED")


if __name__ == "__main__":
    unittest.main()
