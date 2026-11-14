"""CBB joint-periods challenger (alpha-cbb-joint-periods-0.1): point-in-time selection, walk-forward isolation,
coherence of the single joint distribution, and contract validity of the committed evaluation.
Synthetic fixtures only (numpy + pandas); no archive, repo clone or network is needed."""
import json
import math
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine.foundation import cbb_joint_periods as M
from alpha_engine.foundation import contract as C

EVAL = Path(__file__).resolve().parents[1] / "research" / "data_foundation_ops" / "CBB" / M.CHALLENGER_ID / "evaluation.json"


def synth_games(n_days=6, per_day=40, seed=3):
    """Games on consecutive slates; period scores are 'archived' 9 hours after tip (before the next slate's first tip)."""
    rng = np.random.default_rng(seed); rows = []
    for d in range(n_days):
        for j in range(per_day):
            tip = pd.Timestamp("2026-11-02T23:00:00Z") + pd.Timedelta(days=d, minutes=5 * j)
            mu_h, mu_a = 75 + rng.normal(0, 6), 70 + rng.normal(0, 6)
            common = rng.normal(0, 5)
            h1 = round(0.48 * mu_h + 0.5 * common + rng.normal(0, 6)); a1 = round(0.46 * mu_a + 0.5 * common + rng.normal(0, 6))
            h2 = round(0.52 * mu_h + 0.5 * common + rng.normal(0, 6)); a2 = round(0.54 * mu_a + 0.5 * common + rng.normal(0, 6))
            ot = 0
            if h1 + h2 == a1 + a2:
                h2 += 7; a2 += 5; ot = 1
            rows.append(dict(game_id=f"G{d:02d}{j:03d}", tip=tip, obs_at=tip + pd.Timedelta(hours=9), slate=(tip - pd.Timedelta(hours=10)).strftime("%Y-%m-%d"),
                             mu_h=mu_h, mu_a=mu_a, margin=mu_h - mu_a, total=mu_h + mu_a, msd=12.0, tsd=17.0, hw=0.6,
                             h1=float(h1), a1=float(a1), fh=float(h1 + h2), fa=float(a1 + a2), ot=float(ot)))
    return pd.DataFrame(rows)


class LatestPreTip(unittest.TestCase):
    def test_latest_run_strictly_before_tip_is_selected(self):
        t = pd.Timestamp("2026-11-05T00:00:00Z"); h = pd.Timedelta(hours=1)
        runs = pd.DataFrame([
            dict(game_id="A", as_of=t - 20 * h, tip=t, margin=1.0), dict(game_id="A", as_of=t - 3 * h, tip=t, margin=2.0),
            dict(game_id="A", as_of=t + 1 * h, tip=t, margin=99.0),                 # written after tip: never eligible
            dict(game_id="B", as_of=t, tip=t, margin=50.0),                         # as_of == tip is NOT before tip
            dict(game_id="C", as_of=t - 1 * h, tip=t, margin=3.0), dict(game_id="C", as_of=t - 5 * h, tip=t, margin=4.0),
        ])
        sel, dropped = M.select_latest_pretip(runs)
        self.assertEqual(dropped, ["B"])
        self.assertEqual(dict(zip(sel["game_id"], sel["margin"])), {"A": 2.0, "C": 3.0})
        self.assertTrue((sel["as_of"] < sel["tip"]).all())


class WalkForward(unittest.TestCase):
    def setUp(self):
        self.g = synth_games()
        self.days = sorted(self.g["slate"].unique())

    def test_first_slate_is_exactly_the_documented_prior(self):
        p = M.walk_forward_params(self.g)[self.days[0]]
        self.assertEqual(p["n_train"], 0)
        self.assertAlmostEqual(p["share_h"], M.PRIOR["share_1h"]); self.assertAlmostEqual(p["kappa_ot"], 1.0)
        np.testing.assert_allclose(p["cov"], M.prior_cov())
        wH = np.array([1, 0, 1, 0.0]); wA = np.array([0, 1, 0, 1.0])
        self.assertAlmostEqual(math.sqrt(wH @ p["cov"] @ wH), M.PRIOR["sd_team"])
        self.assertAlmostEqual(wH @ p["cov"] @ wA / (wH @ p["cov"] @ wH), M.PRIOR["rho_home_away"])

    def test_parameters_for_day_d_ignore_every_game_on_day_d_or_later(self):
        base = M.walk_forward_params(self.g)
        for d in self.days[1:]:
            g2 = self.g.copy(); late = g2["slate"] >= d
            g2.loc[late, ["h1", "a1"]] = 5.0; g2.loc[late, ["fh", "fa"]] = [150.0, 20.0]; g2.loc[late, "ot"] = 3.0; g2.loc[late, ["mu_h", "mu_a"]] *= 2.0
            p2 = M.walk_forward_params(g2)[d]; p1 = base[d]
            np.testing.assert_array_equal(p1["cov"], p2["cov"])
            for k in ("share_h", "share_a", "kappa_1h", "kappa_ot", "sigma_naive", "ot_rate", "n_train"):
                self.assertEqual(p1[k], p2[k], (d, k))
            self.assertLess(p1["train_max_slate"], d)
            self.assertEqual(p1["n_train"], int((self.g["slate"] < d).sum()))

    def test_results_not_yet_archived_before_first_tip_are_excluded(self):
        g2 = self.g.copy(); d1, d2 = self.days[0], self.days[1]
        g2.loc[g2["slate"] == d1, "obs_at"] = g2.loc[g2["slate"] == d2, "tip"].min() + pd.Timedelta(minutes=1)
        p = M.walk_forward_params(g2)
        self.assertEqual(p[d2]["n_train"], 0); self.assertEqual(p[d2]["n_not_yet_archived"], int((self.g["slate"] == d1).sum()))
        np.testing.assert_allclose(p[d2]["cov"], M.prior_cov())

    def test_learning_moves_the_share_toward_the_data(self):
        p = M.walk_forward_params(self.g)[self.days[-1]]
        self.assertGreater(p["share_h"], p["share_a"]); self.assertAlmostEqual(p["share_h"], 0.48, delta=0.012); self.assertAlmostEqual(p["share_a"], 0.46, delta=0.012)


class Coherence(unittest.TestCase):
    def setUp(self):
        self.g = synth_games(); self.params = M.walk_forward_params(self.g)
        self.arr = M.model_arrays(self.g, self.params, "challenger")
        self.rows = M.synthetic_rows(self.g); self.p = M.row_probs(self.rows, self.arr)

    def _sel(self, **kw):
        m = np.ones(len(self.rows), bool)
        for k, v in kw.items():
            m &= (self.rows[k] == v).to_numpy()
        return self.rows[m], self.p[m]

    def test_means_recompose(self):
        mean = self.arr["mean"]
        np.testing.assert_allclose(mean.sum(1), self.g["total"]); np.testing.assert_allclose(mean[:, 0] + mean[:, 2], self.g["mu_h"])
        np.testing.assert_allclose(mean[:, 0] + mean[:, 2] - mean[:, 1] - mean[:, 3], self.g["margin"])
        n = len(self.g); tt = pd.DataFrame(dict(gi=np.r_[np.arange(n), np.arange(n)], mtype="TEAM_TOTAL", period="FULL", side=["home"] * n + ["away"] * n, strike=np.nan))
        m, _ = M.row_moments(tt, self.arr)
        np.testing.assert_allclose(m[:n] + m[n:], self.g["total"])           # team-total marginal means sum to the total mean

    def test_all_probabilities_are_probabilities(self):
        for v in ("challenger", "naive", "no_cross_team_corr", "share_050", "level_share", "kappa_1", "prior_only"):
            p = M.row_probs(self.rows, M.model_arrays(self.g, self.params, v))
            self.assertTrue(np.isfinite(p).all(), v); self.assertTrue(((p >= 0) & (p <= 1)).all(), v)
        half = self.rows["period"] == "1H"
        self.assertTrue(((self.p[half] >= 0) & (self.p[half] <= 1)).all()); self.assertGreater(half.sum(), 0)

    def test_first_half_three_way_sums_to_one_and_matches_the_spread_ladder(self):
        r, p = self._sel(mtype="WINNER", period="1H")
        np.testing.assert_allclose(pd.Series(p).groupby(r["gi"].to_numpy()).sum(), 1.0, atol=1e-12)
        n = len(self.g); gi = np.arange(n)
        lad = pd.DataFrame(dict(gi=np.r_[gi, gi], mtype="MARGIN", period="1H", side=["home"] * n + ["away"] * n, strike=0.5))
        pl = M.row_probs(lad, self.arr)
        home = p[(r["side"] == "home").to_numpy()]; away = p[(r["side"] == "away").to_numpy()]
        np.testing.assert_allclose(pl[:n], home, atol=1e-12); np.testing.assert_allclose(pl[n:], away, atol=1e-12)

    def test_moneyline_is_the_margin_marginal(self):
        n = len(self.g); gi = np.arange(n)
        ml = pd.DataFrame(dict(gi=np.r_[gi, gi], mtype="WINNER", period="FULL", side=["home"] * n + ["away"] * n, strike=np.nan))
        p = M.row_probs(ml, self.arr)
        np.testing.assert_allclose(p[:n] + p[n:], 1.0, atol=1e-12)            # a final cannot be tied
        sp = M.row_probs(pd.DataFrame(dict(gi=gi, mtype="MARGIN", period="FULL", side="home", strike=0.5)), self.arr)
        np.testing.assert_allclose(p[:n], sp, atol=1e-12)                     # winner == margin > 0.5 on the same distribution
        w = np.array([1, -1, 1, -1.0]); m = self.arr["mean"] @ w; s = np.sqrt(np.einsum("j,ijk,k->i", w, self.arr["cov"], w))
        np.testing.assert_allclose(m, self.g["margin"]); self.assertLess(np.abs(p[:n] - M.phi(m / s)).max(), 0.01)

    def test_ladders_are_monotone_and_complementary(self):
        gi = np.zeros(9, int); ks = np.arange(-4, 5) + 0.5
        for mt, per, side in (("MARGIN", "1H", "home"), ("MARGIN", "FULL", "away"), ("TOTAL", "1H", "none"), ("TEAM_TOTAL", "FULL", "home"), ("MARGIN", "2H", "home")):
            base = 0.0 if mt == "MARGIN" else (70.0 if mt == "TOTAL" else 75.0)
            p = M.row_probs(pd.DataFrame(dict(gi=gi, mtype=mt, period=per, side=side, strike=ks + base)), self.arr)
            self.assertTrue((np.diff(p) < 0).all(), (mt, per, side))
        for per in ("1H", "2H", "FULL"):                                      # P(home > k) + P(away > -k) = 1 at any half-integer k
            a = M.row_probs(pd.DataFrame(dict(gi=gi, mtype="MARGIN", period=per, side="home", strike=ks)), self.arr)
            b = M.row_probs(pd.DataFrame(dict(gi=gi, mtype="MARGIN", period=per, side="away", strike=-ks)), self.arr)
            np.testing.assert_allclose(a + b, 1.0, atol=1e-12)

    def test_second_half_is_the_remainder(self):
        n = len(self.g); gi = np.arange(n)
        m = {per: M.row_moments(pd.DataFrame(dict(gi=gi, mtype="TOTAL", period=per, side="none", strike=np.nan)), self.arr)[0] for per in M.PERIODS}
        np.testing.assert_allclose(m["1H"] + m["2H"], m["FULL"])

    def test_overtime_probability_is_the_scaled_regulation_tie_mass(self):
        r, p = self._sel(mtype="OVERTIME")
        self.assertTrue(((p > 0) & (p < 0.25)).all())
        k1 = M.row_probs(r, M.model_arrays(self.g, self.params, "kappa_1"))
        np.testing.assert_allclose(p, np.clip(self.arr["kot"][r["gi"].to_numpy()] * k1, 0, 1), atol=1e-12)

    def test_naive_baseline_is_uncorrelated_half_share(self):
        a = M.model_arrays(self.g, self.params, "naive")
        np.testing.assert_allclose(a["mean"][:, 0], 0.5 * self.g["mu_h"])
        off = a["cov"][:, ~np.eye(4, dtype=bool)]
        self.assertTrue((off == 0).all())
        d = self.g["slate"].iloc[-1]
        self.assertAlmostEqual(a["cov"][-1, 0, 0], self.params[d]["sigma_naive"] ** 2 / 2.0)

    def test_settlement_semantics(self):
        g = pd.DataFrame(dict(h1=[30.0], a1=[30.0], fh=[70.0], fa=[68.0], ot=[1.0]))
        r = pd.DataFrame([
            dict(gi=0, mtype="WINNER", period="1H", side="home", strike=np.nan), dict(gi=0, mtype="WINNER", period="1H", side="away", strike=np.nan),
            dict(gi=0, mtype="WINNER", period="1H", side="tie", strike=np.nan), dict(gi=0, mtype="WINNER", period="FULL", side="home", strike=np.nan),
            dict(gi=0, mtype="MARGIN", period="FULL", side="home", strike=1.5), dict(gi=0, mtype="MARGIN", period="FULL", side="away", strike=1.5),
            dict(gi=0, mtype="MARGIN", period="2H", side="home", strike=1.5), dict(gi=0, mtype="TOTAL", period="1H", side="none", strike=59.5),
            dict(gi=0, mtype="TOTAL", period="1H", side="none", strike=60.5), dict(gi=0, mtype="TEAM_TOTAL", period="FULL", side="away", strike=67.5),
            dict(gi=0, mtype="OVERTIME", period="FULL", side="none", strike=np.nan)])
        self.assertEqual(M.settle_rows(r, g).tolist(), [0, 0, 1, 1, 1, 0, 1, 1, 0, 1, 1])   # tied half: both team contracts NO


class CommittedEvaluation(unittest.TestCase):
    def test_evaluation_is_contract_valid_and_verdicts_follow_the_rule(self):
        doc = json.loads(EVAL.read_text())
        self.assertEqual(C.validate_evaluation(doc), [])
        self.assertEqual((doc["challenger_id"], doc["incumbent_id"], doc["sport"], doc["status"]), (M.CHALLENGER_ID, "pure-0.2.0", "CBB", "RESEARCH_ONLY"))
        self.assertGreater(len(doc["results"]), 0)
        for r in doc["results"]:
            self.assertEqual(r["verdict"], C.verdict_from(r["ci95"][0], r["ci95"][1], r["p_holm"], r["replicated"]), r)
            self.assertTrue(set(r["archetypes"]) <= {"CBB:first_half", "CBB:team_total", "CBB:overtime_periods", "CBB:game_moneyline_spread", "CBB:game_total"})
            self.assertAlmostEqual(r["diff"], r["challenger"] - r["reference_value"], places=5)
            self.assertLessEqual(r["ci95"][0], r["ci95"][1])
            if not r["headline"]:
                self.assertEqual(r["p_holm"], 1.0)
        hl = [r for r in doc["results"] if r["headline"]]
        self.assertTrue(all(r["cohort"] == "pooled" and r["metric"] == "brier" for r in hl))
        for r, ph in zip(hl, C.holm([r["p_raw"] for r in hl])):
            self.assertAlmostEqual(r["p_holm"], ph, places=5)
        validated = any(r["verdict"] == "VALIDATED_IMPROVEMENT" for r in hl)
        for c in doc["input_stage_claims"]:
            if c["stage"] == "VALIDATED_IMPROVEMENT":
                self.assertTrue(validated)
        if doc["verdict"]["overall"] == "VALIDATED_IMPROVEMENT":
            self.assertTrue(validated)
        for d in doc["data"]:
            self.assertEqual(d["rights_tier"], "UNRESOLVED_INTERNAL_ONLY")
        pit_checks = {c["name"]: c["passed"] for c in doc["features"][0]["checks"]}
        self.assertTrue(pit_checks["as_of_before_scheduled_tip_for_every_used_projection"])
        self.assertTrue(pit_checks["walk_forward_training_strictly_before_slate"])

    def test_no_raw_rows_are_committed(self):
        txt = EVAL.read_text() + (EVAL.parent / "predictions_summary.json").read_text()
        self.assertNotRegex(txt, r"G40\d{7}")            # no canonical game ids
        self.assertNotRegex(txt, r"KXNCAAMB[A-Z0-9]*-")  # no contract tickers (series names only)


if __name__ == "__main__":
    unittest.main()
