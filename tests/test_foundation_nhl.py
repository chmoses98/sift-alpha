"""NHL data-foundation slice (alpha-nhl-joint-0.1): unit tests on synthetic fixtures (numpy + pandas only, no repo data,
no pyarrow) plus a contract check of the committed evaluation document."""
import json
import math
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine.foundation import nhl_joint as nj
from alpha_engine.foundation.contract import validate_evaluation, verdict_from, VERDICTS, STAGES, OUTCOMES

EVAL = Path(__file__).resolve().parents[1] / "research" / "data_foundation_ops" / "NHL" / nj.CHALLENGER_ID / "evaluation.json"
SUMM = EVAL.with_name("predictions_summary.json")


def synth(n_days=120, teams=8, seed=3):
    """Synthetic league: `teams` teams, 4 games per day pairing, two seasons; returns (games, moneypuck) frames."""
    rng = np.random.default_rng(seed); strength = rng.normal(0, 0.15, teams)
    games, mp = [], []; gid = 0
    for d in range(n_days):
        season = 2020 + (d >= n_days // 2)
        date = str(np.datetime64("2020-10-01") + np.timedelta64(d * 2 + (200 if season == 2021 else 0), "D"))
        order = rng.permutation(teams)
        for k in range(teams // 2):
            h, a = int(order[2 * k]) + 1, int(order[2 * k + 1]) + 1; gid += 1
            lh = 3.0 * math.exp(0.08 + strength[h - 1] - strength[a - 1]); la = 3.0 * math.exp(strength[a - 1] - strength[h - 1])
            rh, ra = int(rng.poisson(lh)), int(rng.poisson(la)); lpt = "REG"; hs, as_ = rh, ra
            if rh == ra:
                lpt = "OT" if rng.random() < 0.6 else "SO"
                if rng.random() < 0.5:
                    hs += 1
                else:
                    as_ += 1
            games.append({"game_id": gid, "season": season, "game_type": 2, "game_date": date, "home_team_id": h, "away_team_id": a,
                          "home_score": hs, "away_score": as_, "home_win": hs > as_, "last_period_type": lpt, "final": True})
            for home, team, opp, lam, lam_o, g_for, g_ag in ((True, h, a, lh, la, rh, ra), (False, a, h, la, lh, ra, rh)):
                for sit, share, t in (("all", 1.0, 3600.0), ("5on5", 0.75, 2900.0), ("5on4", 0.18, 300.0), ("4on5", 0.02, 300.0)):
                    xf, xa = lam * share * rng.uniform(0.8, 1.2), lam_o * (share if sit != "5on4" else 0.02) * rng.uniform(0.8, 1.2)
                    mp.append({"season": season, "game_id": gid, "game_date": date, "game_type": 2, "team_id": team, "opp_team_id": opp, "home": home,
                               "situation": sit, "iceTime": t, "xGoalsFor": xf, "xGoalsAgainst": xa, "goalsFor": float(g_for) if sit == "all" else 0.0,
                               "goalsAgainst": float(g_ag) if sit == "all" else 0.0, "scoreVenueAdjustedxGoalsFor": xf, "scoreVenueAdjustedxGoalsAgainst": xa,
                               "flurryScoreVenueAdjustedxGoalsFor": xf, "flurryScoreVenueAdjustedxGoalsAgainst": xa})
    return pd.DataFrame(games), pd.DataFrame(mp)


class Core(unittest.TestCase):
    def test_regulation_scores(self):
        rh, ra, ex = nj.regulation_scores([3, 2, 4, 1], [2, 3, 1, 2], ["OT", "SO", "REG", "REG"])
        self.assertEqual(rh.tolist(), [2, 2, 4, 1]); self.assertEqual(ra.tolist(), [2, 2, 1, 2]); self.assertEqual(ex.tolist(), [1, 1, 0, 0])

    def test_walk_forward_state_is_strictly_pregame_and_carries(self):
        team = np.array([1, 2, 1, 2, 1]); season = np.array([1, 1, 1, 1, 2]); X = np.array([[1.0], [10.0], [2.0], [np.nan], [4.0]])
        out = nj.walk_forward_state(team, season, X, np.array([0.5]), np.array([0.25]))
        self.assertEqual(out[:, 0].tolist(), [0.0, 0.0, 1.0, 10.0, (1.0 * 0.5 + 2.0) * 0.25])
        X2 = X.copy(); X2[2:] = 99.0  # changing a game and everything after it never changes that game's or earlier pre-game state
        out2 = nj.walk_forward_state(team, season, X2, np.array([0.5]), np.array([0.25]))
        np.testing.assert_array_equal(out[:3], out2[:3])

    def test_trailing_league_uses_strictly_earlier_dates(self):
        day = np.repeat(np.arange(300), 2); M = np.arange(600, dtype=float)[:, None]
        L = nj.trailing_league(day, M, window=1000)
        self.assertAlmostEqual(L[400, 0], M[:400, 0].mean()); self.assertAlmostEqual(L[401, 0], M[:400, 0].mean())
        M2 = M.copy(); M2[400:] = -5.0
        np.testing.assert_array_equal(nj.trailing_league(day, M2, window=1000)[:402], L[:402])

    def test_poisson_glm_recovers_coefficients(self):
        rng = np.random.default_rng(0); x = rng.normal(size=20000); off = rng.normal(0, 0.1, 20000)
        y = rng.poisson(np.exp(0.3 + 0.5 * x + off))
        b = nj.poisson_glm(np.column_stack([np.ones_like(x), x]), y, off)
        self.assertAlmostEqual(b[0], 0.3, delta=0.03); self.assertAlmostEqual(b[1], 0.5, delta=0.03)
        self.assertGreaterEqual(float(nj.poisson_deviance_rows(y, np.exp(0.3 + 0.5 * x + off)).min()), 0.0)

    def test_nelder_mead(self):
        x, v = nj.nelder_mead(lambda p: (p[0] - 1) ** 2 + 3 * (p[1] + 2) ** 2, [0.0, 0.0], iters=500)
        self.assertAlmostEqual(x[0], 1, places=3); self.assertAlmostEqual(x[1], -2, places=3); self.assertLess(v, 1e-6)

    def test_joint_pmf_reduces_to_independent_poisson(self):
        lh, la = np.array([3.1, 2.4]), np.array([2.7, 3.3])
        P = nj.joint_reg_pmf(lh, la)
        np.testing.assert_allclose(P.sum((1, 2)), 1.0, atol=1e-12)
        ref = nj._pois(lh)[:, :, None] * nj._pois(la)[:, None, :]; ref /= ref.sum((1, 2), keepdims=True)
        np.testing.assert_allclose(P, ref, atol=1e-12)
        k = np.arange(nj.K)
        self.assertAlmostEqual(float((P[0].sum(1) * k).sum()), 3.1, delta=0.01)

    def test_joint_pmf_shared_component_and_tie_inflation(self):
        lh, la = np.array([3.0]), np.array([2.8]); k = np.arange(nj.K)
        P = nj.joint_reg_pmf(lh, la, c3=0.5)
        ex, ey = (P[0].sum(1) * k).sum(), (P[0].sum(0) * k).sum()
        cov = (P[0] * np.outer(k, k)).sum() - ex * ey
        self.assertAlmostEqual(ex, 3.0, delta=0.01); self.assertAlmostEqual(cov, 0.5, delta=0.02)
        tie0 = np.trace(nj.joint_reg_pmf(lh, la)[0]); tie1 = np.trace(nj.joint_reg_pmf(lh, la, th0=0.3)[0])
        self.assertAlmostEqual(tie1 / (1 - tie1), math.exp(0.3) * tie0 / (1 - tie0), places=9)
        one = lambda Q: Q[np.abs(k[:, None] - k[None, :]) == 1].sum()
        self.assertLess(one(nj.joint_reg_pmf(lh, la, th1=-0.4)[0]), one(nj.joint_reg_pmf(lh, la)[0]))

    def test_markets_are_coherent_sums_of_one_distribution(self):
        rng = np.random.default_rng(1); lh, la = rng.uniform(2, 4, 50), rng.uniform(2, 4, 50)
        reg = nj.joint_reg_pmf(lh, la, 0.1, 0.25, -0.4, 0.0); pot = nj.ot_home_prob(lh, la, 0.2)
        mk = nj.markets_from(reg, pot)
        np.testing.assert_allclose(mk["final"].sum((1, 2)), 1, atol=1e-12)
        self.assertEqual(float(np.abs(mk["final"][:, np.arange(nj.K + 1), np.arange(nj.K + 1)]).max()), 0.0)  # no tied finals
        np.testing.assert_allclose(mk["total_pmf"].sum(1), 1, atol=1e-12); np.testing.assert_allclose(mk["margin_pmf"].sum(1), 1, atol=1e-12)
        away_win = nj.p_margin_over(mk, 0, "away")
        np.testing.assert_allclose(mk["p_home_win"] + away_win, 1, atol=1e-12)
        np.testing.assert_allclose(mk["p_home_win"], mk["p_home_reg_win"] + mk["p_reg_tie"] * pot, atol=1e-12)
        np.testing.assert_allclose(nj.p_margin_over(mk, 1.5, "home") + nj.p_margin_over(mk, -1.5, "away"), 1, atol=1e-12)  # home -1.5 vs away +1.5
        np.testing.assert_allclose(mk["exp_total"], mk["exp_reg_total"] + mk["p_reg_tie"], atol=1e-10)
        o = [nj.p_over(mk["total_pmf"], s) for s in (4.5, 5.5, 6.5, 7.5)]
        for a, b in zip(o, o[1:]):
            self.assertTrue((a > b).all())
        # final total after a tie is odd: P(total = 2i+1) >= P(reg tie at i-i)
        self.assertTrue((mk["total_pmf"][:, 5] >= reg[:, 2, 2] - 1e-12).all())
        np.testing.assert_allclose(nj.p_over(mk["home_pmf"], 2.5), mk["final"][:, 3:, :].sum((1, 2)), atol=1e-12)
        self.assertTrue(((pot >= 0.02) & (pot <= 0.98)).all())

    def test_fit_joint_and_ot_recover_structure(self):
        rng = np.random.default_rng(5); n = 6000; lh, la = rng.uniform(2.4, 3.6, n), rng.uniform(2.4, 3.6, n)
        P = nj.joint_reg_pmf(lh, la, 0.0, 0.3, -0.3, 0.0).reshape(n, -1)
        cell = np.array([rng.choice(P.shape[1], p=p) for p in P]); rh, ra = cell // nj.K, cell % nj.K
        j = nj.fit_joint(lh, la, rh, ra)
        self.assertAlmostEqual(j["theta_tie"], 0.3, delta=0.12); self.assertAlmostEqual(j["theta_one_goal"], -0.3, delta=0.12)
        self.assertLess(j["train_nll"], j["train_nll_independent"])
        hw = rng.random(n) < nj.ot_home_prob(lh, la, 0.6)
        k, _ = nj.fit_ot_k(lh, la, hw)
        self.assertAlmostEqual(k, 0.6, delta=0.25)

    def test_kalshi_reference_quote(self):
        end = np.array([100.0, 200.0, 300.0, 9999.0]); bid = np.array([0.40, 0.44, 0.50, 0.90]); ask = np.array([0.46, 0.48, 0.52, 0.95])
        mid, why, age = nj.kalshi_reference_quote(end, bid, ask, start_ts=3960, lead_s=3600)  # cutoff 360: last candle <= 360 is t=300
        self.assertAlmostEqual(mid, 0.51); self.assertEqual(why, "ok"); self.assertEqual(age, 60.0)
        self.assertEqual(nj.kalshi_reference_quote(end, bid, ask, start_ts=3650)[1], "no_candle_before_cutoff")  # never a later candle
        self.assertEqual(nj.kalshi_reference_quote(end, np.array([0.4, 0.44, 0.0, 0.9]), ask, 3960)[:2], (None, "not_two_sided"))
        self.assertEqual(nj.kalshi_reference_quote(end, bid, np.array([0.46, 0.48, 1.0, 0.95]), 3960)[:2], (None, "not_two_sided"))
        mid2, _, _ = nj.kalshi_reference_quote(end, bid, ask, 3960, empty=np.array([False, False, True, False]))
        self.assertAlmostEqual(mid2, 0.46)

    def test_kalshi_ticker_parsing(self):
        self.assertEqual(nj.parse_kalshi_ticker("KXNHLSPREAD-25DEC01ANASTL-ANA1"), ("KXNHLSPREAD", "2025-12-01", "ANASTL", "ANA", "1"))
        self.assertEqual(nj.parse_kalshi_ticker("KXNHLGAME-26JAN05CBJNJ-NJ"), ("KXNHLGAME", "2026-01-05", "CBJNJ", "NJ", ""))
        self.assertEqual(nj.parse_kalshi_ticker("KXNHLTOTAL-25DEC01ANASTL-5")[3:], ("", "5"))
        self.assertIsNone(nj.parse_kalshi_ticker("garbage"))
        self.assertTrue(nj.split_teams("CBJNJ", "CBJ", "NJD")); self.assertTrue(nj.split_teams("TBNYI", "TBL", "NYI"))
        self.assertFalse(nj.split_teams("CBJNJ", "NJD", "CBJ"))

    def test_compare_and_verdicts_follow_contract(self):
        rng = np.random.default_rng(2); n = 800; p = rng.uniform(0.3, 0.7, n); y = (rng.random(n) < p).astype(int)
        gid = np.arange(n); coh = np.where(gid < n // 2, "2024", "2025")
        rows = nj.compare("moneyline", ["NHL:game_moneyline_puckline"], "logloss", nj.REF_V1, p, np.full(n, 0.5), y, gid, coh)
        rows += nj.compare("moneyline", ["NHL:game_moneyline_puckline"], "logloss", nj.REF_MKT, p[coh == "2025"], np.full(n // 2, 0.5), y[coh == "2025"],
                           gid[coh == "2025"], coh[coh == "2025"])
        rows = nj.finalize_verdicts(rows)
        self.assertEqual([r["cohort"] for r in rows], ["2024", "2025", "pooled", "2025"])
        for r in rows:
            self.assertEqual(r["verdict"], verdict_from(r["ci95"][0], r["ci95"][1], r["p_holm"], r["replicated"]))
            self.assertEqual(r["headline"], r["reference"] == nj.REF_V1 and r["cohort"] == "pooled")
        self.assertTrue(rows[2]["replicated"]); self.assertEqual(rows[2]["verdict"], "VALIDATED_IMPROVEMENT")
        self.assertFalse(rows[3]["replicated"]); self.assertNotEqual(rows[3]["verdict"], "VALIDATED_IMPROVEMENT")  # single cohort can never validate


class SyntheticPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.games, cls.mp = synth()
        cls.tg = nj.build_team_games(cls.games, cls.mp)
        cls.hp = dict(nj.HP0, hl=20.0, k_prior=5.0)

    def test_team_games_layout(self):
        tg = self.tg
        self.assertEqual(len(tg), 2 * len(self.games))
        self.assertTrue((tg["home"].values[0::2] == 0).all() and (tg["home"].values[1::2] == 1).all())
        self.assertTrue((tg["game_id"].values[0::2] == tg["game_id"].values[1::2]).all())
        self.assertTrue((np.diff(tg["day"].values) >= 0).all()); self.assertEqual(int(tg.duplicated(["team", "day"]).sum()), 0)
        g = self.games.set_index("game_id").loc[tg["game_id"].values[1::2]]
        tie = g["last_period_type"].isin(["OT", "SO"]).values
        self.assertTrue((tg["rg"].values[1::2][tie] == tg["rg"].values[0::2][tie]).all())  # regulation ties are ties
        self.assertTrue((tg["rg"].values[1::2][~tie] == g["home_score"].values[~tie]).all())

    def test_home_flag_is_repaired_from_official_ids(self):
        mp = self.mp.copy(); gid = int(mp["game_id"].iloc[0]); mp.loc[mp["game_id"] == gid, "home"] = False  # both rows flagged away
        fixed, n = nj.resolve_home(mp, self.games)
        self.assertEqual(n, 4); self.assertEqual(int(fixed.duplicated(["game_id", "home", "situation"]).sum()), 0)
        pd.testing.assert_frame_equal(nj.build_team_games(self.games, mp), self.tg)

    def test_features_have_no_lookahead(self):
        tg = self.tg; F = nj.make_features(tg, self.hp); cut = int(np.quantile(tg["day"].values, 0.6))
        early = tg["day"].values < cut; on_or_before = tg["day"].values <= cut
        F_tr = nj.make_features(tg[early].reset_index(drop=True), self.hp)
        tg2 = tg.copy(); late = tg2["day"].values >= cut
        for c in [c for c in tg2.columns if c.startswith(("xGoals", "goals", "iceTime", "scoreVenue", "flurry"))] + ["rg"]:
            v = tg2[c].values.astype(float); v[late] = v[late] * 3.0 + 1.0; tg2[c] = v
        F2 = nj.make_features(tg2, self.hp)
        for n in nj.FEATS["full"] + ["offall", "defall"]:
            np.testing.assert_allclose(F_tr["f"][n], F["f"][n][early], atol=1e-12, err_msg=n)        # truncation invariance
            np.testing.assert_array_equal(F2["f"][n][on_or_before], F["f"][n][on_or_before], err_msg=n)  # same-day and future games never leak
        np.testing.assert_array_equal(F2["offset"][on_or_before], F["offset"][on_or_before])
        self.assertTrue(all(np.isfinite(F["f"][n]).all() for n in F["f"]))
        self.assertTrue((F["f"]["off5"][:8] == 0).all())  # no history -> league average exactly

    def test_fit_and_predict_on_synthetic(self):
        tg = self.tg; F = nj.make_features(tg, self.hp); G = nj.game_frame(tg)
        g = self.games.set_index("game_id").loc[G["game_id"]]
        G["home_win"] = g["home_win"].astype(int).values; G["extra"] = g["last_period_type"].isin(["OT", "SO"]).astype(int).values
        train = np.ones(len(G["game_id"]), bool)
        old = (nj.FIT_FIRST, nj.TRAIN_LAST); nj.FIT_FIRST, nj.TRAIN_LAST = 2020, 2021
        try:
            model, _ = nj.fit_variant(tg, G, self.hp, nj.FEATS["full"], train, F=F)
            indep, _ = nj.fit_variant(tg, G, self.hp, nj.FEATS["full"], train, independent=True, F=F)
        finally:
            nj.FIT_FIRST, nj.TRAIN_LAST = old
        beta = dict(zip(["intercept"] + model.names, model.beta))
        self.assertGreater(beta["off5"], 0); self.assertGreater(beta["home"], 0)  # true home edge is +0.08 log goals
        mk = model.markets(train)
        self.assertAlmostEqual(float(mk["p_home_win"].mean()), float(G["home_win"].mean()), delta=0.06)
        self.assertAlmostEqual(float(mk["exp_reg_total"].mean()), float((G["rh"] + G["ra"]).mean()), delta=0.15)
        self.assertEqual(indep.joint, {"c3": 0.0, "theta_tie": 0.0, "theta_one_goal": 0.0, "delta": 0.0})
        self.assertGreaterEqual(float(nj.reg_nll_rows(indep, train, G).mean()), float(nj.reg_nll_rows(model, train, G).mean()) - 1e-6)


@unittest.skipUnless(EVAL.exists(), "evaluation.json not generated")
class CommittedEvaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(EVAL.read_text())

    def test_contract_valid(self):
        d = self.doc
        self.assertEqual(validate_evaluation(d), [])
        self.assertEqual((d["sport"], d["challenger_id"], d["status"]), ("NHL", nj.CHALLENGER_ID, "RESEARCH_ONLY"))
        self.assertEqual(d["source_commits"], {"NHL-edge-finder": nj.SOURCE_COMMIT})

    def test_every_verdict_is_consistent_with_its_evidence(self):
        for r in self.doc["results"]:
            self.assertIn(r["verdict"], VERDICTS)
            self.assertEqual(r["verdict"], verdict_from(r["ci95"][0], r["ci95"][1], r["p_holm"], r["replicated"]), r)
            self.assertAlmostEqual(r["diff"], r["challenger"] - r["reference_value"], places=5)
            self.assertLessEqual(r["ci95"][0], r["diff"]); self.assertLessEqual(r["diff"], r["ci95"][1])
            self.assertGreaterEqual(r["p_holm"], r["p_raw"] - 1e-9)
            self.assertGreaterEqual(r["n_rows"], r["n_clusters"])
            self.assertTrue(set(r["archetypes"]) <= {"NHL:game_moneyline_puckline", "NHL:game_total_and_team_total", "NHL:game_events"})
            if r["reference"] == nj.REF_MKT:
                self.assertEqual(r["cohort"], "2025"); self.assertFalse(r["replicated"])
            if r["cohort"] == "pooled":
                cd = r["cohort_diffs"]
                self.assertEqual(r["replicated"], cd["2024"] < 0 and cd["2025"] < 0)

    def test_headline_rows_and_overall(self):
        d = self.doc; head = [r for r in d["results"] if r["headline"]]
        fams = {r["market_family"] for r in head}
        self.assertEqual(fams, {"moneyline", "regulation_tie_overtime", "total_5.5", "total_6.5", "puck_line_1.5", "team_total_2.5", "team_total_3.5"})
        self.assertEqual(len(head), 14)
        self.assertTrue(all(r["reference"] == nj.REF_V1 and r["cohort"] == "pooled" and r["n_clusters"] == 2624 for r in head))
        val = [r for r in head if r["verdict"] == "VALIDATED_IMPROVEMENT"]; bad = [r for r in head if r["verdict"] == "NOT_IMPROVED"]
        ov = d["verdict"]["overall"]
        if ov == "VALIDATED_IMPROVEMENT":
            self.assertTrue(all(r["verdict"] == "VALIDATED_IMPROVEMENT" for r in head if r["metric"] == "logloss") and not bad)
        if ov == "IMPROVED_NOT_VALIDATED":
            self.assertTrue(not bad and (val or any(r["verdict"] == "IMPROVED_NOT_VALIDATED" for r in head)))
        self.assertIsInstance(d["verdict"]["retain_incumbent"], bool)
        if ov != "VALIDATED_IMPROVEMENT":
            self.assertTrue(d["verdict"]["retain_incumbent"])

    def test_train_test_separation_and_claims(self):
        d = self.doc; des = d["design"]
        self.assertEqual(des["train_window"]["glm_joint_ot_fit"], "2009-2023")
        self.assertEqual(des["test_window"]["cohorts"], {"2024": 1312, "2025": 1312})
        cat = json.loads((EVAL.parents[3] / "input_research" / "catalog" / "NHL.json").read_text())
        ids = {"NHL:" + i for v in cat["inputs"].values() for i in v.get("registry_ids", [])}
        for c in d["input_stage_claims"]:
            self.assertIn(c["input"], ids); self.assertIn(c["stage"], STAGES); self.assertIn(c["outcome"], OUTCOMES)
            self.assertNotIn(c["stage"], ("VALIDATED_IMPROVEMENT", "PRODUCTION_APPROVED", "PRODUCTION_ACTIVE"))
        for f in d["features"]:
            self.assertTrue(set(f["catalog_inputs"]) <= ids, f["feature_id"]); self.assertTrue(f["checks"])
        leak = [c for f in d["features"] for c in f["checks"] if c["name"].startswith("leak_guard")]
        self.assertTrue(leak and all(c["passed"] for c in leak))

    def test_oracle_ablation_is_labelled_and_separate(self):
        ab = {a["ablation_id"]: a for a in self.doc["ablations"]}
        self.assertEqual(set(ab), {"a_no_special_teams_split", "b_no_tie_inflation_or_correlation", "c_no_finishing",
                                   "d_oracle_as_played_starting_goalie", "e_no_rest"})
        self.assertIn("ORACLE_NOT_PIT upper bound", ab["d_oracle_as_played_starting_goalie"]["label"])
        self.assertTrue(ab["d_oracle_as_played_starting_goalie"]["oracle_not_pit"])
        self.assertNotIn("goalie", json.dumps(self.doc["design"]["fitted_parameters"]["glm_beta"]))

    def test_no_raw_rows_committed(self):
        txt = EVAL.read_text() + (SUMM.read_text() if SUMM.exists() else "")
        self.assertNotIn('"game_id"', txt); self.assertNotIn("KXNHLGAME-", txt)
        for d in self.doc["data"]:
            self.assertEqual(d["repo"], nj.REPO); self.assertIsInstance(d["rows"], int)
        if SUMM.exists():
            s = json.loads(SUMM.read_text())
            self.assertEqual(set(s["cohorts"]), {"2024", "2025", "pooled"})
            for blk in s["cohorts"].values():
                for fam in blk["families"].values():
                    self.assertEqual(sum(b["n"] for b in fam["reliability_challenger"]), fam["n_rows"])


if __name__ == "__main__":
    unittest.main()
