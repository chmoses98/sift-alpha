"""Alpha lab: market-free guard, ledger idempotence, distribution maths, point-in-time ratings and as-of features (no look-ahead, row alignment), market scoring and the
segment search's discovery/holdout separation.  Synthetic data only."""
import json, os, sys, tempfile, unittest
from pathlib import Path
import numpy as np
import pandas as pd

from alpha_engine.lab import guard, ledger, dists, market as MK, player_lab as PL, ratings as RT, game_lab as GL


class Guard(unittest.TestCase):
    def test_market_and_postgame_columns_are_refused(self):
        for c in ("spread_line", "total_line", "home_moneyline", "over_odds", "mkt_total_level", "ix_spread_x_passrate", "kalshi_bid", "implied_prob", "home_score", "result"):
            with self.assertRaises(guard.MarketLeak, msg=c):
                guard.assert_market_free([c])
        self.assertTrue(guard.assert_market_free(["dif_epa_pass", "rest_diff", "inj_sum_qb", "ew8_rec_yds"]))

    def test_every_catalogued_game_feature_is_market_free(self):
        cols = [c for g in GL.TABLE_GROUPS.values() for c in g] + [f"{p}_{m}" for ms in GL.METRIC_GROUPS.values() for m in ms for p in ("dif", "sum")]
        self.assertTrue(guard.assert_market_free(cols))

    def test_player_feature_columns_are_market_free(self):
        lab = PL.PlayerLab.__new__(PL.PlayerLab)
        lab.ctx = pd.DataFrame(columns=["team_off_epa_pass", "team_off_epa_rush", "team_off_neutral_pass", "team_off_plays", "opp_def_epa_pass", "opp_def_epa_rush", "opp_def_sack_rate",
                                        "opp_def_sr", "team_pts_pred", "opp_pts_pred", "margin_pred_team", "total_pred", "dome", "wind_eff", "cold"])
        lab.states = pd.DataFrame(columns=[f"ew{h}_{c}" for h in (3, 8) for c in PL.STATE_COLS])
        for t in PL.SPEC:
            self.assertTrue(guard.assert_market_free(lab.columns(t, PL.OPTIONAL, "3+8")))


class LedgerTests(unittest.TestCase):
    def test_idempotent_cached_and_complete(self):
        with tempfile.TemporaryDirectory() as d:
            led = ledger.Ledger(os.path.join(d, "l.jsonl"))
            cfg = {"a": 1, "b": [1, 2]}
            led.record(cfg, {"x": 1.0}); led.record(cfg, {"x": 99.0}); led.record({"a": 2}, {"x": 2.0}, status="failed", note="nan")
            self.assertEqual(len(led), 2); self.assertEqual(led.get(cfg)["metrics"]["x"], 1.0)             # first result stands
            re = ledger.Ledger(os.path.join(d, "l.jsonl"))
            self.assertTrue(re.has(cfg)); self.assertEqual(len(re), 2)
            self.assertEqual(len(open(os.path.join(d, "l.jsonl")).read().splitlines()), 2)                 # failures are recorded too


class Dists(unittest.TestCase):
    def test_thresholds_are_monotone_and_integer_scores_normalise(self):
        mu = np.array([20.0]); sd = np.array([10.0])
        p = [float(dists.prob_gt("normal", mu, sd, f)[0]) for f in (5.5, 15.5, 25.5)]
        self.assertTrue(p[0] > p[1] > p[2])
        tot = sum(np.exp(dists.int_logscore("normal", np.array([y]), mu, sd)) for y in range(-80, 120))
        self.assertAlmostEqual(float(tot[0]), 1.0, places=3)
        nb = sum(np.exp(dists.int_logscore("nbinom", np.array([y]), np.array([60.0]), 3.0)) for y in range(0, 2000))
        self.assertAlmostEqual(float(nb[0]), 1.0, places=3)
        # P(Y >= k) for a Poisson at the half-integer floor k-0.5
        from scipy import stats
        self.assertAlmostEqual(float(dists.prob_gt("poisson", np.array([0.7]), 1.0, 0.5)[0]), 1 - stats.poisson.pmf(0, 0.7), places=9)


class Ratings(unittest.TestCase):
    def _tiny(self):
        games = pd.DataFrame(dict(game_id=["g1", "g2", "g3"], season=[2020, 2020, 2020], week=[1, 2, 3], gameday=["2020-09-10", "2020-09-17", "2020-09-24"],
                                  home_team=["A", "B", "A"], away_team=["B", "C", "C"]))
        from alpha_engine.input_research import nfl_features as nf
        rows = []
        for gid, h, a in (("g1", "A", "B"), ("g2", "B", "C"), ("g3", "A", "C")):
            for t, bonus in ((h, 1.0), (a, 0.0)):
                r = {m: 0.0 for m in nf.OFF_METRICS}; r.update(game_id=gid, posteam=t, epa_pass=bonus * (5.0 if gid == "g3" else 0.1)); rows.append(r)
        return games, pd.DataFrame(rows)

    def test_ratings_for_a_game_never_use_that_game_or_later_ones(self):
        games, tg = self._tiny()
        base = RT.rolling_ratings_param(games, tg)
        tg2 = tg.copy(); tg2.loc[tg2["game_id"] == "g3", "epa_pass"] = 1e6          # corrupt the LAST game's outcome
        pert = RT.rolling_ratings_param(games, tg2)
        pd.testing.assert_frame_equal(base[base["game_id"].isin(["g1", "g2", "g3"])].reset_index(drop=True), pert.reset_index(drop=True))   # pre-game ratings unchanged

    def test_adjustment_flag_changes_ratings(self):
        games, tg = self._tiny()
        a = RT.rolling_ratings_param(games, tg, adjust=True); b = RT.rolling_ratings_param(games, tg, adjust=False)
        self.assertFalse(np.allclose(a["a_off_epa_pass"].fillna(0), b["a_off_epa_pass"].fillna(0)))


class AsOf(unittest.TestCase):
    def test_features_are_row_aligned_and_exclude_the_same_game(self):
        pg = pd.DataFrame(dict(pid=["p", "p", "p", "q"], date=pd.to_datetime(["2020-09-10", "2020-09-17", "2020-09-24", "2020-09-17"])))
        st = pd.DataFrame(dict(pid=["p", "p", "p", "q"], date=pd.to_datetime(["2020-09-10", "2020-09-17", "2020-09-24", "2020-09-17"]), ew8_rec_yds=[10.0, 20.0, 30.0, 99.0])).sort_values("date")
        tgt = pd.DataFrame(dict(pid=["q", "p", "p", "p", "p"], date=pd.to_datetime(["2020-09-18", "2020-09-24", "2020-09-10", "2020-09-30", "2020-09-17"])))     # deliberately unsorted
        f = PL.features_asof(tgt, st)
        self.assertEqual(f["ew8_rec_yds"].tolist()[0], 99.0)                                          # q's state from 09-17 (before 09-18)
        self.assertEqual(f["ew8_rec_yds"].tolist()[1], 20.0)                                          # p on 09-24 sees 09-17, NOT its own 09-24 state
        self.assertTrue(np.isnan(f["ew8_rec_yds"].tolist()[2]))                                       # debut: nothing before 09-10
        self.assertEqual(f["ew8_rec_yds"].tolist()[3], 30.0)                                          # a later date sees the latest state
        self.assertEqual(f["ew8_rec_yds"].tolist()[4], 10.0)


class MarketLayer(unittest.TestCase):
    def _d(self, n=400, noisy="market", seed=1):
        """noisy='market': the model knows the true probability and the quote is noisy; noisy='model': the quote is the truth and the model is noise around it."""
        rng = np.random.default_rng(seed)
        p = rng.uniform(0.2, 0.8, n); y = (rng.uniform(size=n) < p).astype(float)
        noise = np.clip(p + rng.normal(0, 0.05, n), 0.05, 0.95)
        model_p, mid = (p, noise) if noisy == "market" else (noise, p)
        return pd.DataFrame(dict(game_id=[f"g{i // 4}" for i in range(n)], week=(np.arange(n) // 20) % 20 + 1, family="spread", horizon=MK.PRIMARY, model_p=model_p, outcome=y,
                                 bid=mid - 0.02, ask=mid + 0.02, age=10.0, ticker=[f"t{i}" for i in range(n)]))

    def test_fee_and_executable_price(self):
        d = MK.score(self._d(40))
        self.assertTrue((d["price"] > 0).all())
        i = d.index[0]
        self.assertAlmostEqual(d.loc[i, "real_yes"], d.loc[i, "outcome"] - d.loc[i, "ask"] - MK.taker_fee(d.loc[i, "ask"]), places=9)
        self.assertAlmostEqual(d.loc[i, "real_no"], (1 - d.loc[i, "outcome"]) - (1 - d.loc[i, "bid"]) - MK.taker_fee(1 - d.loc[i, "bid"]), places=9)

    def test_a_noisy_model_cannot_beat_price_plus_fee(self):
        r = MK.strategy_table(MK.score(self._d(4000, noisy="model", seed=3)), taus=(0.0,))[f"spread|{MK.PRIMARY}|tau0"]
        self.assertLess(r["mean_real"], 0.0)                           # betting on pure model noise against a correct price loses the spread and the fee

    def test_a_genuinely_better_model_is_detected(self):                # power check: the machinery must be able to see a real edge
        r = MK.strategy_table(MK.score(self._d(4000, noisy="market", seed=3)), taus=(0.0,))[f"spread|{MK.PRIMARY}|tau0"]
        self.assertGreater(r["mean_real"], 0.02); self.assertGreater(r["ci"][0], 0.0)

    def test_segment_search_chooses_on_discovery_and_reports_holdout_separately(self):
        d = MK.score(self._d(3000, noisy="model", seed=5))
        res = MK.segment_search(d, tau=-1.0, top_k=3, min_n=30, min_games=5)
        self.assertGreater(res["segments_examined"], res["segments_carried_forward"])
        for s in res["carried"]:
            self.assertEqual(s["status"], "NOT_DEMONSTRATED")           # no real edge exists: nothing may be declared positive after Holm
            self.assertIsNotNone(s["holm_p"])

    def test_holdout_outcomes_cannot_change_which_segments_are_carried(self):
        a = MK.score(self._d(3000, noisy="model", seed=9)); b = a.copy()
        b.loc[b["week"] > MK.DISCOVERY_MAX_WEEK, ["outcome"]] = 1.0 - b.loc[b["week"] > MK.DISCOVERY_MAX_WEEK, "outcome"]
        b = MK.score(b.drop(columns=[c for c in b.columns if c in ("mid", "ll_model", "ll_mkt", "br_model", "br_mkt", "ev_yes", "ev_no", "real_yes", "real_no", "side", "pred_ev", "real", "price", "edge", "fav")]))
        ka = [(s["family"], tuple(sorted(s["segment"].items()))) for s in MK.segment_search(a, tau=-1.0, top_k=3, min_n=30, min_games=5)["carried"]]
        kb = [(s["family"], tuple(sorted(s["segment"].items()))) for s in MK.segment_search(b, tau=-1.0, top_k=3, min_n=30, min_games=5)["carried"]]
        self.assertEqual(ka, kb)


if __name__ == "__main__":
    unittest.main()


def test_loop_gaps_and_priorities():
    import pandas as pd
    from alpha_engine.lab import loop
    gt = pd.DataFrame({"season": [2020, 2020, 2021, 2021], "x": [1.0, 1.0, None, None]})
    cases = loop.detect_gaps(gt, {"no_game_ids": ["g1"], "no_game_in_table": 3, "contracts": 10, "unresolved_player": 2}, {"rows_without_timestamp": 5}, ["x", "absent"])
    ids = [c["id"] for c in cases]
    assert ids[0] == "nfl:game_table_missing_postseason_2025" and "nfl:input_gap:x" in ids and "nfl:input_gap:absent" not in ids
    from alpha_engine.repair_queue import choose_next
    assert choose_next([{"id": i} for i in ids], {})["next_id"] == ids[0]
    rep = {"predictive": {"a": {"games": 100, "logloss_gain": {"mean": -0.05, "ci": [-0.08, -0.02]}}, "b": {"games": 100, "logloss_gain": {"mean": 0.0, "ci": [-0.02, 0.02]}}}}
    assert loop.next_experiments(rep)[0]["family"] == "b"


def test_exceed_platt_recovers_calibration():
    import numpy as np
    from alpha_engine.lab import exceed
    rng = np.random.default_rng(0)
    p = rng.uniform(0.05, 0.95, 20000)
    o = (rng.uniform(size=p.size) < exceed.apply((0.0, 0.5), p)).astype(float)   # truth is a flattened version of p
    a, b = exceed.fit(p, o)
    assert abs(b - 0.5) < 0.1


def _idn_tables():
    import pandas as pd
    from alpha_engine.lab import identity as I
    players = pd.DataFrame({"gsis_id": ["a", "b", "c", "d"], "display_name": ["Kenny Gainwell", "Josh Allen", "Josh Allen", "Marquise Brown"],
                            "first_name": ["Kenneth", "Joshua", "Josh", "Marquise"], "last_name": ["Gainwell", "Allen", "Allen", "Brown"],
                            "latest_team": ["TB", "BUF", "JAX", "PHI"], "last_season": [2026] * 4})
    pg = pd.DataFrame({"pid": ["a", "b", "c", "d"], "season": [2025] * 4, "team": ["PIT", "BUF", "JAX", "KC"]})
    return I, I.build_tables(players, pg)


def test_identity_season_team_and_aliases():
    I, (nm, played) = _idn_tables()
    assert I.resolve_one("Kenneth Gainwell", "PIT", 2025, nm, played) == ("a", "RESOLVED_SEASON_TEAM")      # legal first name, new team
    assert I.resolve_one("Hollywood Brown", "KC", 2025, nm, played)[0] == "d"                              # verified alias
    assert I.resolve_one("Hollywood Brown", "PHI", 2025, nm, played)[0] is None                            # alias not used when team evidence disagrees
    assert I.resolve_one("Josh Allen", "BUF", 2025, nm, played)[0] == "b" and I.resolve_one("Josh Allen", "JAX", 2025, nm, played)[0] == "c"


def test_identity_never_guesses():
    I, (nm, played) = _idn_tables()
    assert I.resolve_one("Josh Allen", "MIA", 2025, nm, played)[1] == "AMBIGUOUS"
    assert I.resolve_one("Nobody Real", "MIA", 2025, nm, played)[1] == "NO_NAME_MATCH"
    assert I.resolve_one("No Touchdown", None, 2025, nm, played)[1] == "NON_PLAYER_NO_TD"
    assert I.resolve_one("Miami Special Teams", "MIA", 2025, nm, played)[1] == "NON_PLAYER_DEFENSE"
    assert I.resolve_one("Chicago Defense", "CHI", 2025, nm, played)[1] == "NON_PLAYER_DEFENSE"


def test_repair_postseason_labels():
    import pandas as pd
    from alpha_engine.lab import repair
    g = pd.DataFrame({"game_type": ["REG", "WC", "DIV", "CON", "SB"]})
    assert repair.normalize_games(g)["game_type"].tolist() == ["REG", "POST", "POST", "POST", "POST"]


def _games():
    import pandas as pd
    return pd.DataFrame({"game_id": ["2025_21_LA_SEA", "2025_05_JAX_KC", "2025_05_LAC_LA"], "season": [2025] * 3, "week": [21, 5, 5], "gameday": ["2026-01-25", "2025-10-05", "2025-10-05"],
                         "away_team": ["LA", "JAX", "LAC"], "home_team": ["SEA", "KC", "LA"]})


def test_recover_game_and_side_from_ticker():
    from alpha_engine.lab import recover as RV
    idx = RV.games_index(_games())
    r = RV.recover({"ticker": "KXNFLTOTAL-26JAN25LASEA-74"}, idx)
    assert r["game_id"] == "2025_21_LA_SEA" and r["week"] == 21 and "team" not in r                       # total: no side
    assert RV.recover({"ticker": "KXNFLSPREAD-26JAN25LASEA-SEA14"}, idx)["team"] == "SEA"
    assert RV.recover({"ticker": "KXNFLREC-26JAN25LASEA-LATFERGUSON18-1"}, idx)["team"] == "LA"
    assert RV.recover({"ticker": "KXNFLGAME-25OCT05JACKC-JAC"}, idx)["team"] == "JAX"                    # Kalshi JAC == nflverse JAX
    assert RV.recover({"ticker": "KXNFLGAME-25OCT05LACLA-LAC"}, idx)["team"] == "LAC"                    # LAC must not be read as LA
    assert RV.recover({"ticker": "KXNFLGAME-25AUG09LASEA-LA"}, idx) is None                              # preseason: no nflverse game


def test_recover_only_fills_nulls():
    from alpha_engine.lab import recover as RV
    idx = RV.games_index(_games())
    rec = {"ticker": "KXNFLSPREAD-26JAN25LASEA-SEA14", "game_id": None, "team": "SEA", "week": None}
    assert RV.fill(rec, idx) and rec["team"] == "SEA" and rec["week"] == 21 and rec["recovered_from_ticker"]
    mapped = {"ticker": "KXNFLSPREAD-26JAN25LASEA-SEA14", "game_id": "X"}
    assert not RV.fill(mapped, idx) and mapped["game_id"] == "X"


def test_prospective_chain_detects_tampering(tmp_path):
    from alpha_engine.lab import prospective as PP
    p = tmp_path / "c.jsonl"
    for i in range(3):
        PP.append(p, {"kind": "x", "i": i})
    assert PP.verify_chain(p)["ok"]
    lines = p.read_text().splitlines(); r = json.loads(lines[1]); r["i"] = 99; lines[1] = json.dumps(r, sort_keys=True); p.write_text("\n".join(lines) + "\n")
    v = PP.verify_chain(p); assert v["ok"] is False and v["first_bad_line"] == 2


def test_prospective_decision_rules():
    import pandas as pd
    from alpha_engine.lab import prospective as PP
    games = pd.DataFrame({"game_id": ["g"], "home_score": [30.0], "away_score": [20.0], "gameday": ["2026-11-08"], "gametime": ["13:00"]})
    ko = pd.Timestamp("2026-11-08 13:00", tz="America/New_York").tz_convert("UTC")
    pred = {"game_id": "g", "week": 10, "kickoff_utc": ko.isoformat(), "generated_utc": (ko - pd.Timedelta(hours=30)).isoformat(), "dist": "normal", "mu": 45.0, "sigma": 13.0}
    def q(minutes_before, bid=0.40, ask=0.44):
        return {"game_id": "g", "ticker": "T-48", "floor": 47.5, "bid": bid, "ask": ask, "captured_utc": (ko - pd.Timedelta(minutes=minutes_before)).isoformat()}
    df = PP.decision_frame([pred], [q(365), q(500), q(100)], games)
    h6 = df[df.horizon == "T-6h"]
    assert len(h6) == 1 and abs(h6.iloc[0]["age"] - 5) < 1e-6                     # the 365-min-before capture (5 min old), not the 500-min one
    assert set(df.horizon) == {"T-6h", "T-90m"}                                    # no capture inside the T-24h window
    assert df.iloc[0]["outcome"] == 1.0                                            # 50 > 47.5
    late = dict(pred, generated_utc=(ko - pd.Timedelta(hours=5)).isoformat())      # prediction made AFTER the T-6h decision time
    late_df = PP.decision_frame([late], [q(365)], games)
    assert late_df.empty or "T-6h" not in set(late_df.horizon)
    assert PP.evaluate(df)["by_horizon"]["T-6h"]["inference"].startswith("withheld")


def test_frozen_config_equals_selected_total_config_with_pit_groups():
    """Guards against transcription drift: the frozen totals config must be the lab's selected one (rating/model/dist) with only the partial-PIT groups replaced."""
    from alpha_engine.lab import prospective as PP
    rep = json.load(open(Path(__file__).resolve().parents[1] / "research/audit/lab/game_lab_report.json"))["targets"]["total"]["selected"]["config"]
    for k in ("rating", "model", "dist"):
        assert PP.FROZEN[k] == rep[k]
    assert PP.FROZEN["groups"] == [g for g in rep["groups"] if g not in ("qb", "environment")] + ["environment_dome"]
