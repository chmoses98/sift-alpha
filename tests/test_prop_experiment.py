"""Offline tests for the Kalshi passing-yards experiment and the market-universe audit (no network)."""
import datetime as dt
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine.input_research import market_universe as MU
from alpha_engine.input_research import prop_experiment as PE

ROOT = Path(__file__).resolve().parents[1]
EXP = json.loads((ROOT / "research/audit/input_research/experiments/nfl_passyds_kalshi_v1.json").read_text())


def candle(end_ts, ask, bid, vol=1):
    return {"end_period_ts": end_ts, "yes_ask": {"close_dollars": str(ask)}, "yes_bid": {"close_dollars": str(bid)}, "volume_fp": str(vol)}


class Quotes(unittest.TestCase):
    def setUp(self):
        self.ko = dt.datetime(2026, 10, 4, 17, 0, tzinfo=dt.timezone.utc)
        self.games = pd.DataFrame([{"game_id": "g1", "season": 2026, "game_type": "REG", "gameday": "2026-10-04", "gametime": "13:00", "away_team": "GB", "home_team": "TB", "week": 4}])
        self.players = pd.DataFrame([{"gsis_id": "p1", "display_name": "Jane Roe"}])
        self.qb = pd.DataFrame([{"game_id": "g1", "qb_id": "p1", "season": 2026}])
        self.market = {"ticker": "KXNFLPASSYDS-26OCT04GBTB-TBJROE1-200", "event_ticker": "KXNFLPASSYDS-26OCT04GBTB", "status": "finalized", "result": "yes",
                       "floor_strike": 199.5, "yes_sub_title": "Jane Roe: 200+", "open_time": "2026-10-01T00:00:00Z"}

    def test_quote_uses_only_candles_ended_before_the_cut(self):
        k = self.ko.timestamp()
        cs = [candle(k - 7200, 0.40, 0.38), candle(k - 3600, 0.45, 0.43), candle(k - 1800, 0.99, 0.01), candle(k, 1.0, 0.0)]
        df, _ = PE.build_contracts([self.market], self.games, self.players, self.qb, {self.market["ticker"]: cs})
        r = df.iloc[0]
        self.assertEqual(r["ask_primary_T-60m"], 0.45)       # candle ending exactly at kickoff-60m is allowed, later ones are not
        self.assertEqual(r["bid_primary_T-60m"], 0.43)
        self.assertTrue(pd.isna(r["ask_secondary_T-3h"]))   # nothing ended before kickoff-3h: no quote, never back-filled
        self.assertTrue(r["has_model_row"])

    def test_kickoff_is_converted_from_eastern_time(self):
        df, _ = PE.build_contracts([self.market], self.games, self.players, self.qb, {})
        self.assertEqual(df.iloc[0]["kickoff"], "2026-10-04T17:00:00+00:00")

    def test_unmatched_games_and_unsettled_are_staged_out_not_dropped(self):
        m2 = dict(self.market, event_ticker="KXNFLPASSYDS-26OCT04XXYY", ticker="t2")
        m3 = dict(self.market, ticker="t3", result="")
        df, _ = PE.build_contracts([self.market, m2, m3], self.games, self.players, self.qb, {})
        self.assertEqual(df.stage.tolist(), ["ok", "x1_no_regular_season_game_match", "x2_not_settled_yes_no"])


class Scoring(unittest.TestCase):
    def frame(self, p, ask, bid, result):
        return pd.DataFrame({"p_model": [p], "ask_primary_T-60m": [ask], "bid_primary_T-60m": [bid], "result": [result]})

    def test_yes_bet_pnl_and_fee(self):
        s = PE.score(self.frame(0.60, 0.40, 0.38, "yes"), "primary_T-60m")
        r = s.iloc[0]
        self.assertEqual(r.side, "YES"); self.assertTrue(r.qualifies)
        fee = PE.fee_c(0.40)
        self.assertAlmostEqual(r.pnl, 1 - 0.40 - fee)
        self.assertAlmostEqual(fee, 0.017)   # ceil(0.07*10*0.4*0.6=0.168 -> 0.17) / 10 contracts

    def test_no_bet_uses_one_minus_bid_and_loses_when_yes_happens(self):
        s = PE.score(self.frame(0.10, 0.40, 0.38, "yes"), "primary_T-60m")
        r = s.iloc[0]
        self.assertEqual(r.side, "NO"); self.assertAlmostEqual(r.price, 0.62)
        self.assertAlmostEqual(r.pnl, 0 - 0.62 - PE.fee_c(0.62))

    def test_one_sided_book_cannot_be_bought(self):
        s = PE.score(self.frame(0.99, 1.0, 0.98, "yes"), "primary_T-60m")       # no YES offered
        self.assertEqual(s.iloc[0].side, "NO") if s.iloc[0].qualifies else None
        s2 = PE.score(self.frame(0.99, 1.0, 0.0, "yes"), "primary_T-60m")       # nothing executable
        self.assertFalse(s2.iloc[0].qualifies)

    def test_edge_must_clear_the_fee_and_threshold(self):
        s = PE.score(self.frame(0.43, 0.40, 0.38, "yes"), "primary_T-60m")
        self.assertFalse(s.iloc[0].qualifies)


class Model(unittest.TestCase):
    def test_model_never_trains_on_2026_or_uses_prices(self):
        rng = np.random.default_rng(0)
        n = 4000
        cols = PE._feat_cols()
        d = pd.DataFrame(rng.normal(size=(n, len(cols))), columns=cols)
        d["season"] = np.repeat(np.arange(2013, 2027), n // 14 + 1)[:n]
        d["baseline_ypg"] = 240 + 10 * rng.normal(size=n)
        d["pass_yards"] = d.baseline_ypg + 15 * d[cols[0]] + 55 * rng.normal(size=n)
        d.loc[d.season == 2026, "pass_yards"] = 1e6          # poison: must have no influence
        predict, p_over, diag, w = PE.fit_models(d, cols)
        self.assertEqual(diag["n_train"], int((d.season.between(2013, 2025)).sum()))
        mu, sd = predict(d[d.season == 2026].head(5))
        self.assertTrue(np.all(np.abs(mu - 240) < 200))
        p = p_over(mu, sd, np.full(5, 240.0))
        self.assertTrue(np.all((p > 0) & (p < 1)))
        self.assertAlmostEqual(float(p_over(np.array([240.0]), np.array([60.0]), np.array([1e9]))[0]), 0.0, places=3)

    def test_bootstrap_is_clustered_and_deterministic(self):
        v = [1, 1, 1, -1, -1, -1]; g = ["a", "a", "a", "b", "b", "b"]
        m, lo, hi, k = PE.boot_mean(v, g)
        self.assertEqual(k, 2); self.assertEqual(m, 0.0); self.assertLess(lo, -0.9); self.assertGreater(hi, 0.9)
        self.assertEqual(PE.boot_mean(v, g), PE.boot_mean(v, g))


class PublishedExperiment(unittest.TestCase):
    def test_research_only_and_honest_labels(self):
        self.assertEqual(EXP["status"], "RESEARCH_ONLY")
        self.assertIn("HYPOTHETICAL", EXP["label"])
        self.assertEqual(EXP["edge_min"], 0.05)

    def test_waterfall_is_internally_consistent(self):
        sc = EXP["stage_counts"]
        self.assertEqual(sum(sc.values()), EXP["contracts_listed"])
        for h in EXP["horizons"].values():
            w = h["waterfall"]
            self.assertEqual(w["have_quote_at_horizon"] + w["no_quote_n"], w["settled_regular_season"])
            self.assertEqual(w["eligible_priced"] + w["no_model_row_n"], w["have_quote_at_horizon"])

    def test_nothing_is_promoted_without_review(self):
        # If a re-run ever shows a net-positive interval above zero at any horizon, a human must review it before the dashboard is changed.
        for k, h in EXP["horizons"].items():
            d = h["decisions"]
            self.assertLessEqual(d["ci95"][0], 0, f"{k}: positive lower bound — review as a candidate, do not promote automatically")

    def test_structure_test_gates_and_degenerate_cells(self):
        st = EXP["structure_test_primary_T-60m"]
        self.assertEqual(len(st["cells"]), 16)
        self.assertEqual(st["cells_passing_all_gates"], 0, "a passing cell must be reviewed by a human before anything is promoted")
        for c in st["cells"]:
            if not c["enough_sample"]:
                self.assertLess(c["n"], st["min_cell"][0] + 1 if c["games"] >= st["min_cell"][1] else 10**9)
            self.assertGreaterEqual(c["holm_p"], c["p_one_sided"])
        # the all-win 0.9+ YES cell has a near-zero-width bootstrap interval; the exact test must still say it is not significant
        top = [c for c in st["cells"] if c["mid_bin"].startswith("(0.9") and c["side"] == "YES"][0]
        self.assertGreater(top["p_one_sided"], 0.05)

    def test_contract_csv_matches_summary(self):
        df = pd.read_csv(ROOT / "research/audit/input_research/experiments/nfl_passyds_kalshi_v1_contracts.csv")
        w = EXP["horizons"]["primary_T-60m"]["waterfall"]
        self.assertEqual(len(df), w["settled_regular_season"])
        self.assertEqual(int(df["p_model"].notna().sum() - df[df["ask_primary_T-60m"].isna()]["p_model"].notna().sum()), w["eligible_priced"])


class Universe(unittest.TestCase):
    def test_sport_assignment_and_scope(self):
        mk = lambda t, tags=(): {"ticker": t, "tags": list(tags)}
        self.assertEqual(MU.sport_of(mk("KXNFLPASSYDS")), "NFL")
        self.assertEqual(MU.sport_of(mk("KXNCAAFGAME")), "CFB")
        self.assertEqual(MU.sport_of(mk("KXNCAAMBGAME")), "CBB")
        self.assertEqual(MU.sport_of(mk("KXPGAWIN", ["Golf"])), "OTHER_SPORT:Golf")
        self.assertEqual(MU.sport_of(mk("KXBUNDESLIGAGAME", ["Soccer"])), "SOCCER")

    def test_published_summary_has_every_sport_and_unsupported_groups(self):
        s = json.loads((ROOT / "research/input_research/market_universe/universe_summary.json").read_text())
        for sp in ("NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"):
            self.assertIn(sp, s["by_sport"])
        self.assertTrue(any(k.startswith("OTHER_SPORT:Golf") for k in s["by_sport"]))
        self.assertEqual(sum(v["series"] for v in s["by_sport"].values()), s["n_series"])


if __name__ == "__main__":
    unittest.main()


GEXP = json.loads((ROOT / "research/audit/input_research/experiments/nfl_game_kalshi_v1.json").read_text())


class PublishedGameExperiment(unittest.TestCase):
    def test_waterfall_and_labels(self):
        self.assertEqual(GEXP["status"], "RESEARCH_ONLY"); self.assertIn("HYPOTHETICAL", GEXP["label"])
        self.assertEqual(sum(GEXP["stage_counts"].values()), GEXP["contracts_listed"])
        for h in GEXP["horizons"].values():
            w = h["waterfall"]
            self.assertEqual(w["two_sided_quote_at_horizon"] + w["no_usable_quote"], w["settled_with_book_line"])

    def test_no_promotion_without_review(self):
        d = GEXP["horizons"]["primary_T-60m"]["decisions"]
        if d["qualifying_n"] >= 30:
            self.assertLessEqual(d["ci95"][0], 0, "positive interval at the primary horizon: human review required before any change to the dashboard")


class TeamSplit(unittest.TestCase):
    def test_two_and_three_letter_codes(self):
        valid = {"GB", "TB", "JAX", "BAL", "KC", "NE", "LA", "NO", "SF", "LV", "LAC"}
        self.assertEqual(PE.split_teams("GBTB", valid), ("GB", "TB"))
        self.assertEqual(PE.split_teams("JACBAL", valid), ("JAX", "BAL"))
        self.assertEqual(PE.split_teams("KCNE", valid), ("KC", "NE"))
        self.assertEqual(PE.split_teams("LARSF", valid), ("LA", "SF"))
        self.assertEqual(PE.split_teams("LVLAC", valid), ("LV", "LAC"))
        self.assertIsNone(PE.split_teams("XXYY", valid))
