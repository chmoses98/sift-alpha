"""Unit tests for the NBA/NHL outcome-intelligence audit helpers (leakage, time windows, settlement derivation, dedup). RESEARCH_ONLY."""
import gzip
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "research", "outcome_intel"))

import numpy as np  # noqa: E402
import nba_nhl_common as C  # noqa: E402
import nba_audit as NBA  # noqa: E402
import nhl_audit as NHL  # noqa: E402


def _write_gz_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _write_gz_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt") as f:
        json.dump(obj, f)


class TestHorizonsAndSelection(unittest.TestCase):
    def test_horizon_boundaries(self):
        self.assertEqual(C.horizon_of(24.0)[0], "T_24H")
        self.assertEqual(C.horizon_of(6.0)[0], "T_6H")
        self.assertEqual(C.horizon_of(1.49)[0], "T_1H")
        self.assertEqual(C.horizon_of(0.1)[0], "CLOSING")
        self.assertIsNone(C.horizon_of(15.0)[0])          # gap between windows: no row
        self.assertIsNone(C.horizon_of(0.0 - 1e-9)[0])    # after start: no row

    def test_select_closest_and_never_after_start(self):
        start = 1_000_000.0
        mk = lambda h, q: dict(ticker="T", t=start - h * 3600, start=start, q=q)
        preds = [mk(5.0, 0.1), mk(6.2, 0.2), mk(7.4, 0.3), mk(-0.5, 0.9), mk(0.0, 0.8)]
        sel = C.select_per_horizon(preds)
        self.assertEqual(sel[("T", "T_6H")]["q"], 0.2)    # 6.2h is closest to 6h
        self.assertNotIn(0.9, [p["q"] for p in sel.values()])  # after-start prediction can never be selected
        self.assertNotIn(0.8, [p["q"] for p in sel.values()])  # hb == 0 excluded

    def test_selection_ignores_outcome(self):
        start = 5e6
        a = [dict(ticker="T", t=start - 6 * 3600, start=start, q=0.4, y=1)]
        b = [dict(ticker="T", t=start - 6 * 3600, start=start, q=0.4, y=0)]
        self.assertEqual(list(C.select_per_horizon(a)), list(C.select_per_horizon(b)))

    def test_snapshot_ts(self):
        t = C.snapshot_ts_from_path("kalshi/markets/dt=2026-10-12/kalshi_markets_20261012T120222Z_38241528661.jsonl.gz+18deltas#abc")
        self.assertEqual(C.iso(t), "2026-10-12T12:02:22Z")
        self.assertIsNone(C.snapshot_ts_from_path("0.9"))


class TestQuote(unittest.TestCase):
    def test_two_sided_and_derived_side(self):
        q = C.quote({"yes_bid_dollars": "0.4000", "yes_ask_dollars": "0.4500", "no_bid_dollars": "0.55", "no_ask_dollars": "0.60"})
        self.assertTrue(q["two_sided"])
        self.assertAlmostEqual(q["mid"], 0.425)
        q = C.quote({"yes_bid_dollars": "0.0000", "yes_ask_dollars": "0.5000", "no_bid_dollars": "0.5", "no_ask_dollars": "0.9"})
        self.assertAlmostEqual(q["yes_bid"], 0.1)          # 1 - no_ask
        q = C.quote({"yes_bid_dollars": "0.0000", "yes_ask_dollars": "0.0000", "no_bid_dollars": "0.0", "no_ask_dollars": "0.0"})
        self.assertFalse(q["two_sided"])
        self.assertIsNone(C.quote(None))


class TestBoardReplayNoLookahead(unittest.TestCase):
    def _build(self, d):
        base = "kalshi/markets/dt=2026-10-12/kalshi_markets_20261012T000000Z_1.jsonl.gz"
        mk = lambda t, yb, ya: {"ticker": t, "yes_bid_dollars": yb, "yes_ask_dollars": ya, "no_bid_dollars": "0.1", "no_ask_dollars": "0.2", "status": "active",
                                 "_observed_at_utc": "2026-10-12T00:00:00Z", "rules_primary": "x"}
        _write_gz_jsonl(os.path.join(d, base), [mk("A", "0.40", "0.44"), mk("B", "0.10", "0.20")])
        dl = lambda seq, at, **kw: dict(schema="kalshi.board.delta/1", seq=seq, base_path=base, captured_at_utc=at, added=kw.get("added", {}), changed=kw.get("changed", {}),
                                        cleared=kw.get("cleared", {}), removed=kw.get("removed", []), n_markets_after=kw["n"], board_sha256=f"s{seq}", parent_board_sha256=kw.get("parent", f"s{seq-1}"),
                                        n_markets_before=0, base_captured_at_utc="x", base_sha256="y", run_id="1")
        _write_gz_json(os.path.join(d, "kalshi/markets_delta/dt=2026-10-12/kalshi_markets_delta_20261012T001500Z_1.json.gz"), dl(1, "2026-10-12T00:15:00Z", changed={"A": {"yes_bid_dollars": "0.50", "yes_ask_dollars": "0.54"}}, n=2, parent="root"))
        _write_gz_json(os.path.join(d, "kalshi/markets_delta/dt=2026-10-12/kalshi_markets_delta_20261012T003000Z_1.json.gz"), dl(2, "2026-10-12T00:30:00Z", changed={"A": {"yes_bid_dollars": "0.70", "yes_ask_dollars": "0.74"}}, removed=["B"], n=1))
        return base

    def test_lookup_uses_latest_board_at_or_before_t(self):
        with tempfile.TemporaryDirectory() as d:
            self._build(d)
            t = lambda s: C.ts(s)
            lookups = [("A", t("2026-10-12T00:10:00Z"), "k10"), ("A", t("2026-10-12T00:15:00Z"), "k15"), ("A", t("2026-10-12T00:29:59Z"), "k29"),
                       ("A", t("2026-10-12T00:45:00Z"), "k45"), ("A", t("2026-10-11T23:00:00Z"), "before"), ("B", t("2026-10-12T00:40:00Z"), "Bgone")]
            res, cov, integ = C.board_sweep(d, lookups, starts=None, want={"A", "B"})
            self.assertEqual(res["k10"]["slim"]["yes_bid_dollars"], "0.40")  # delta at 00:15 must NOT leak into a 00:10 decision
            self.assertEqual(res["k15"]["slim"]["yes_bid_dollars"], "0.50")  # board captured exactly at t is allowed
            self.assertEqual(res["k29"]["slim"]["yes_bid_dollars"], "0.50")  # 00:30 board is after 00:29:59
            self.assertEqual(res["k45"]["slim"]["yes_bid_dollars"], "0.70")
            self.assertIsNone(res["before"]["board_t"])                       # nothing was captured yet -> no quote, never the future one
            self.assertIsNone(res["Bgone"]["slim"])                           # removed market is absent
            self.assertEqual(integ["chain_broken"], 0)
            self.assertEqual(integ["count_mismatch"], 0)

    def test_broken_chain_and_count_detected(self):
        with tempfile.TemporaryDirectory() as d:
            base = self._build(d)
            p = os.path.join(d, "kalshi/markets_delta/dt=2026-10-12/kalshi_markets_delta_20261012T003000Z_1.json.gz")
            with gzip.open(p, "rt") as f:
                x = json.load(f)
            x["parent_board_sha256"] = "WRONG"
            x["n_markets_after"] = 99
            _write_gz_json(p, x)
            _, _, integ = C.board_sweep(d, [], starts=None, want={"A"})
            self.assertEqual(integ["chain_broken"], 1)
            self.assertEqual(integ["count_mismatch"], 1)

    def test_pregame_coverage_excludes_post_start_boards(self):
        with tempfile.TemporaryDirectory() as d:
            self._build(d)
            start = C.ts("2026-10-12T00:20:00Z")
            _, cov, _ = C.board_sweep(d, [], starts={"A": start}, want={"A"})
            self.assertEqual(C.iso(cov["A"]["last_pre_t"]), "2026-10-12T00:15:00Z")


NBA_BOX = dict(game_id="espn:1", status="final", is_final=True, home_team_id=10, away_team_id=20, home_pts=114, away_pts=108, n_ot=1,
               period_scores={"1Q": [40, 20], "2Q": [16, 30], "3Q": [24, 28], "4Q": [18, 20], "OT1": [16, 10]},
               players=[dict(nba_id=-1, team_id=10, played=True, minutes=30.0, pts=22, reb=11, ast=3, fg3m=4, stl=0, blk=1, tov=2),
                        dict(nba_id=-2, team_id=20, played=False, minutes=0.0, pts=0, reb=0, ast=0, fg3m=0, stl=0, blk=0, tov=0),
                        dict(nba_id=-3, team_id=20, played=True, minutes=36.0, pts=12, reb=10, ast=10, fg3m=0, stl=1, blk=0, tov=0)])


class TestNbaDerivation(unittest.TestCase):
    def d(self, **c):
        base = dict(scope="game", comparator="gt", period="FULL", team_id=None, nba_id=None)
        base.update(c)
        return NBA.derive_outcome(base, NBA_BOX)

    def test_winner_spread_total_includes_ot_in_full(self):
        self.assertEqual(self.d(stat="winner", team_id=10, threshold=0.0), ("YES", 6.0))
        self.assertEqual(self.d(stat="winner", team_id=20, threshold=0.0)[0], "NO")
        self.assertEqual(self.d(stat="margin", team_id=10, threshold=5.5)[0], "YES")
        self.assertEqual(self.d(stat="margin", team_id=10, threshold=6.5)[0], "NO")          # value 6 is not > 6.5
        self.assertEqual(self.d(stat="total", threshold=221.5), ("YES", 222.0))
        self.assertEqual(self.d(stat="team_total", team_id=20, threshold=108.5)[0], "NO")

    def test_periods(self):
        self.assertEqual(self.d(stat="margin", period="1H", team_id=10, threshold=5.5), ("YES", 6.0))   # 1H: (40+16) - (20+30) = 6
        self.assertEqual(self.d(stat="margin", period="1H", team_id=10, threshold=6.5)[0], "NO")
        self.assertEqual(self.d(stat="total", period="1Q", threshold=59.5), ("YES", 60.0))

    def test_period_values(self):
        self.assertEqual(NBA.period_points(NBA_BOX, "1H"), (56, 50))
        self.assertEqual(NBA.period_points(NBA_BOX, "FULL"), (114, 108))
        self.assertEqual(NBA.period_points(NBA_BOX, "2H"), (42, 48))     # OT excluded from 2H (flagged ambiguity, not hidden)
        self.assertIsNone(NBA.period_points(NBA_BOX, "9Q"))

    def test_player_props_and_void(self):
        p = lambda **c: NBA.derive_outcome(dict(scope="player", comparator="gt", period="FULL", **c), NBA_BOX)
        self.assertEqual(p(stat="pts", nba_id=-1, threshold=21.5)[0], "YES")
        self.assertEqual(p(stat="pra", nba_id=-1, threshold=36.5)[0], "NO")                 # 22+11+3 = 36 is not > 36.5
        self.assertEqual(p(stat="pra", nba_id=-1, threshold=35.5)[0], "YES")
        self.assertEqual(p(stat="double_double", nba_id=-1, threshold=0.5)[0], "YES")
        self.assertEqual(p(stat="triple_double", nba_id=-3, threshold=0.5)[0], "YES")       # 12/10/10: pts, reb, ast all >= 10
        self.assertEqual(p(stat="pts", nba_id=-2, threshold=0.5)[0], "VOID")                # DNP
        self.assertEqual(p(stat="pts", nba_id=-99, threshold=0.5)[0], "VOID")               # not in box
        self.assertEqual(p(stat="stocks", nba_id=-1, threshold=0.5)[0], None)               # unsupported stat is never invented

    def test_non_final_and_unproven_semantics(self):
        nf = dict(NBA_BOX, is_final=False, status="live")
        self.assertEqual(NBA.derive_outcome(dict(scope="game", stat="total", period="FULL", threshold=1.5, comparator="gt"), nf), (None, None))
        self.assertEqual(self.d(stat="overtime", threshold=None)[0], None)


class TestNbaTripleDoubleRealCheck(unittest.TestCase):
    def test_triple_double_true(self):
        box = dict(NBA_BOX)
        box["players"] = [dict(nba_id=-3, team_id=20, played=True, minutes=36.0, pts=12, reb=10, ast=10, fg3m=0, stl=1, blk=0, tov=0)]
        o = NBA.derive_outcome(dict(scope="player", comparator="gt", period="FULL", stat="triple_double", nba_id=-3, threshold=0.5), box)
        self.assertEqual(o[0], "YES")


NHL_RES = dict(game_id="g1", status="final", home_team_id=1, away_team_id=2, home_final=4, away_final=3, home_reg=3, away_reg=3, last_period_type="SO")
# regulation 3-3: P1 2-1, P2 0-1, P3 1-1; home wins the shootout (final 4-3 includes the single shootout goal)
GOALS = [dict(period=1, team_id=1, t_s=100, scorer_id=11), dict(period=1, team_id=1, t_s=200, scorer_id=14), dict(period=1, team_id=2, t_s=300, scorer_id=21),
         dict(period=2, team_id=2, t_s=800, scorer_id=22), dict(period=3, team_id=1, t_s=10, scorer_id=13), dict(period=3, team_id=2, t_s=1100, scorer_id=23)]
PLAYERS = {("g1", 11): dict(goals=1, assists=0, points=1, toi_s=900), ("g1", 12): dict(goals=0, assists=2, points=2, toi_s=0)}
GOALIES = {("g1", 31): dict(saves=25, toi_s=3600)}


class TestNhlDerivation(unittest.TestCase):
    def d(self, **c):
        base = dict(scope="game", comparator="gt", period="FULL", team_id=None, threshold=None)
        base.update(c)
        return NHL.derive_outcome(base, NHL_RES, GOALS, PLAYERS, GOALIES, None)

    def test_shootout_goal_ambiguity_is_flagged_not_guessed(self):
        # incl SO: total 7; excl SO: total 6 -> a 6.5 line is ambiguous
        self.assertEqual(self.d(family="game_total", threshold=6.5)[0], "SO_AMBIGUOUS")
        self.assertEqual(self.d(family="game_total", threshold=7.5)[0], "NO")
        self.assertEqual(self.d(family="game_total", threshold=5.5)[0], "YES")
        # moneyline includes the shootout: home wins
        self.assertEqual(self.d(family="game_winner", team_id=1, threshold=0.0)[0], "YES")
        self.assertEqual(self.d(family="game_winner", team_id=2, threshold=0.0)[0], "NO")
        self.assertEqual(self.d(family="game_spread", team_id=1, threshold=0.5)[0], "SO_AMBIGUOUS")  # margin 1 incl SO, 0 excl SO
        self.assertEqual(self.d(family="team_total", team_id=1, threshold=3.5)[0], "SO_AMBIGUOUS")   # 4 incl SO, 3 excl

    def test_period_markets_from_goal_events(self):
        self.assertEqual(self.d(family="period_total", period="P1", threshold=2.5)[0], "YES")
        self.assertEqual(self.d(family="period_total", period="P1", threshold=3.5)[0], "NO")
        self.assertEqual(self.d(family="period_winner", period="P2", team_id=1, threshold=0.0)[0], "NO")
        self.assertEqual(self.d(family="period_winner", period="P2", team_id=2, threshold=0.0)[0], "YES")
        self.assertEqual(self.d(family="period_spread", period="P1", team_id=1, threshold=0.5)[0], "YES")
        self.assertEqual(self.d(family="period_spread", period="P1", team_id=1, threshold=1.5)[0], "NO")
        self.assertEqual(self.d(family="period_total", period="OT", threshold=0.5)[0], None)          # only P1-P3 are derived

    def test_player_props(self):
        o = lambda fam, pid, thr: NHL.derive_outcome(dict(family=fam, threshold=thr, comparator="gt"), NHL_RES, GOALS, PLAYERS, GOALIES, pid)
        self.assertEqual(o("player_goals", 11, 0.5)[0], "YES")
        self.assertEqual(o("player_goals", 11, 1.5)[0], "NO")
        self.assertEqual(o("player_goals", 12, 0.5)[0], "VOID")      # toi 0 = did not play
        self.assertEqual(o("player_goals", 99, 0.5)[0], "VOID")      # not in box
        self.assertEqual(o("first_goal", 11, None)[0], "YES")        # earliest by (period, t_s)
        self.assertEqual(o("goalie_saves", 31, 24.5)[0], "YES")
        self.assertEqual(o("goalie_saves", 31, 25.5)[0], "NO")

    def test_not_final_is_not_derived(self):
        r = dict(NHL_RES, status="live")
        self.assertEqual(NHL.derive_outcome(dict(family="game_winner", team_id=1, threshold=0.0), r)[0], None)


class TestSettlementDedup(unittest.TestCase):
    def test_latest_wins_and_conflicts_counted(self):
        with tempfile.TemporaryDirectory() as d:
            rows = [dict(ticker="X", outcome="YES", settled_at_utc="2026-10-01T00:00:00Z", box_source="s", engine_version="e", box_stat_correction_version=0),
                    dict(ticker="X", outcome="NO", settled_at_utc="2026-10-02T00:00:00Z", box_source="s", engine_version="e", box_stat_correction_version=1),
                    dict(ticker="Y", outcome="YES", settled_at_utc="2026-10-01T00:00:00Z", box_source="s", engine_version="e", box_stat_correction_version=0),
                    dict(ticker="Y", outcome="YES", settled_at_utc="2026-10-03T00:00:00Z", box_source="s", engine_version="e", box_stat_correction_version=0)]
            _write_gz_jsonl(os.path.join(d, "settlements/dt=2026-10-02/a.jsonl.gz"), rows)
            latest, info = NBA.load_settlements(d)
            self.assertEqual(latest["X"]["outcome"], "NO")
            self.assertEqual(info["tickers_with_multiple_rows"], 2)
            self.assertEqual(info["conflicting_resettlements"], 1)
            self.assertEqual(info["unique_tickers"], 2)

    def test_exchange_crosscheck_flags_disagreement(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "wagers.jsonl"), "w") as f0:
                f0.write("")
            with open(os.path.join(d, "settlements.jsonl"), "w") as f:
                f.write(json.dumps(dict(market_ticker="A", side="YES", result="WON", settlement_status="SETTLED")) + "\n")   # exchange: YES won
                f.write(json.dumps(dict(market_ticker="B", side="NO", result="WON", settlement_status="SETTLED")) + "\n")    # exchange: NO won -> YES false
                f.write(json.dumps(dict(market_ticker="C", side="YES", result="LOST", settlement_status="SETTLED")) + "\n")
            r = NBA.exchange_crosscheck(d, {"A": "YES", "B": "YES", "C": "NO"})
            self.assertEqual((r["exchange_settled_wagers_compared"], r["agree"], r["disagree"]), (3, 2, 1))
            self.assertEqual(r["disagree_tickers"], ["B"])


class TestSportsbook(unittest.TestCase):
    def test_devig_and_staleness(self):
        sb = {"g": {"P1": [(100.0, "home", 2.0), (100.0, "away", 2.0)], "P2": [(100.0, "home", 1.5), (100.0, "away", 3.0)]}}
        p, n = NHL.sportsbook_home_prob(sb, "g", 200.0)
        self.assertEqual(n, 2)
        self.assertAlmostEqual(p, (0.5 + (1 / 1.5) / (1 / 1.5 + 1 / 3.0)) / 2)
        self.assertEqual(NHL.sportsbook_home_prob(sb, "g", 50.0)[0], None)                      # quotes observed after t are invisible
        self.assertEqual(NHL.sportsbook_home_prob(sb, "g", 100.0 + 4 * 3600)[0], None)          # too stale
        sb2 = {"g": {"P1": [(100.0, "home", 2.0), (100.0 + 7200, "away", 2.0)]}}
        self.assertEqual(NHL.sportsbook_home_prob(sb2, "g", 100.0 + 7300)[1], 0)                # sides observed >30 min apart are not paired


class TestIncrementalControls(unittest.TestCase):
    def _rows(self, informative, n_games=150, per=4, seed=1):
        rng = np.random.default_rng(seed)
        rows = []
        for g in range(n_games):
            for j in range(per):
                p = float(rng.uniform(0.2, 0.8))
                y = int(rng.random() < p)
                mid = p
                q = float(np.clip(0.5 * p + 0.5 * y, 0.03, 0.97)) if informative else float(np.clip(rng.uniform(0.2, 0.8), 0.03, 0.97))
                rows.append(dict(game=f"g{g}", t=float(g), mid=mid, q=q, y=y))
        return rows

    def test_planted_signal_detected_and_noise_not(self):
        res = C.run_cell(self._rows(True))
        self.assertEqual(res["status"], "OK")
        self.assertGreater(res["gain_vs_calibrated_market_logloss"]["lo"], 0)
        res0 = C.run_cell(self._rows(False))
        self.assertLessEqual(res0["gain_vs_calibrated_market_logloss"]["mean"], 0.005)
        self.assertGreater(res["positive_control"]["lo"], 0)                                   # look-ahead control is caught
        st, _ = C.classify(res0, 1.0, n_tested=10)
        self.assertNotEqual(st, "VALIDATED_IMPROVEMENT")

    def test_underpowered_is_not_a_negative(self):
        res = C.run_cell(self._rows(False, n_games=10))
        self.assertEqual(res["status"], "UNDERPOWERED")
        self.assertEqual(C.classify(res, None)[0], "INCONCLUSIVE_UNDERPOWERED")

    def test_chronological_split_never_trains_on_future(self):
        rows = self._rows(True)
        import incremental as I
        tr, te = I.split_games(rows)
        self.assertLess(max(r["t"] for r in rows if r["game"] in tr), min(r["t"] for r in rows if r["game"] in te) + 1e-9)

    def test_validated_requires_holm(self):
        res = C.run_cell(self._rows(True))
        self.assertEqual(C.classify(res, 0.001, n_tested=5)[0], "VALIDATED_IMPROVEMENT")
        self.assertEqual(C.classify(res, 0.4, n_tested=5)[0], "PROMISING_INSUFFICIENT")


class TestClassifyRules(unittest.TestCase):
    def _res(self, mean, lo, hi, games=60, status="OK", pc_lo=0.3, nc_lo=-0.01, nc_hi=0.01):
        g = dict(mean=mean, lo=lo, hi=hi, p=0.01, n=100, n_games=games)
        return dict(status=status, holdout_games=games, train_games=games * 2, n_holdout=100, n_train=200, gain_vs_calibrated_market_logloss=g,
                    positive_control=dict(lo=pc_lo, hi=1.0, mean=0.5), negative_control=dict(lo=nc_lo, hi=nc_hi, mean=0.0))

    def test_negligible_positive_gain_is_not_promising(self):
        st, why = C.classify(self._res(0.0005, 0.00002, 0.001), 1.0, n_tested=50)
        self.assertEqual(st, "NO_DEMONSTRATED_IMPROVEMENT")
        self.assertIn("materiality", why)

    def test_reliably_worse_model_is_no_improvement_even_with_few_games(self):
        st, _ = C.classify(self._res(-0.02, -0.04, -0.005, games=15), 0.5, n_tested=50)
        self.assertEqual(st, "NO_DEMONSTRATED_IMPROVEMENT")

    def test_wide_interval_small_holdout_is_underpowered_not_negative(self):
        st, _ = C.classify(self._res(-0.01, -0.08, 0.06, games=15), 1.0, n_tested=50)
        self.assertEqual(st, "INCONCLUSIVE_UNDERPOWERED")

    def test_positive_but_tiny_holdout_is_not_a_finding(self):
        st, _ = C.classify(self._res(0.03, 0.005, 0.06, games=13), 1.0, n_tested=50)
        self.assertEqual(st, "INCONCLUSIVE_UNDERPOWERED")

    def test_validated_blocked_when_positive_control_fails(self):
        st, _ = C.classify(self._res(0.02, 0.01, 0.03, pc_lo=-0.1), 0.001, n_tested=50)
        self.assertEqual(st, "PROMISING_INSUFFICIENT")

    def test_negative_control_gain_invalidates_positive_cell(self):
        st, why = C.classify(self._res(0.02, 0.01, 0.03, nc_lo=0.002, nc_hi=0.03), 0.01, n_tested=50)
        self.assertEqual(st, "INVALID_EVIDENCE")
        self.assertIn("negative control", why)

    def test_q_vs_mid_diagnostic(self):
        rows = [dict(game=f"g{i}", t=float(i), mid=0.3 + 0.004 * (i % 100), q=0.3 + 0.004 * (i % 100), y=i % 2) for i in range(400)]
        res = C.run_cell(rows)
        self.assertLess(res["q_vs_mid"]["mean_abs_diff"], 1e-9)   # challenger identical to the market -> flagged as not independent
        self.assertGreater(res["q_vs_mid"]["corr_logit"], 0.999)


if __name__ == "__main__":
    unittest.main()
