"""tennis_ext6 builder proof of concept (RESEARCH_ONLY): synthetic fixtures only. Real-data replay and blind verification have NOT been run; nothing here promotes an input.

Adversarial checks: the generic replay harness (determinism, truncation and future perturbation at 3 cuts, own-date perturbation, non-vacuity), same-tournament isolation,
absurd-future injection, leave-player-out arithmetic, reuse equalities with the verified tennis_ext4 pieces, sensitivity to an injected match-form shock, and labelling rules."""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import tennis_synth as T  # noqa: E402
from alpha_engine.features import tennis_ext4 as X4  # noqa: E402
from alpha_engine.features import tennis_ext6 as X  # noqa: E402
from alpha_engine.input_research.data_foundation import replay_generic as G  # noqa: E402

D = T.make(years=3, seed=11)
RAW = X.prepare(D)
BASE = X.compute(RAW)["team"]
COLS = [c for s in X.specs() for c in s.columns]


def same(a, b):
    return np.isclose(a.to_numpy(float), b.to_numpy(float), rtol=1e-9, atol=1e-12, equal_nan=True).all()


def aligned(new, sel):
    n = new.set_index(["game_id", "team"]).reindex(BASE.set_index(["game_id", "team"]).index).reset_index(drop=True)
    return BASE.loc[sel].reset_index(drop=True), n.loc[sel].reset_index(drop=True)


class ReplayHarness(unittest.TestCase):
    R = G.run(X, RAW, "TENNIS", {"matches": ("game_id", X.CONTENT)}, games_table="matches", games_date_col="date")

    def test_all_replay_tests_pass(self):
        for cid, r in self.R["inputs"].items():
            t = r["tests"]
            self.assertTrue(t["determinism"]["ok"], cid)
            for k in ("truncation", "perturbation"):
                for x in t[k]:
                    self.assertTrue(x["ok"], (cid, k, x["bad_columns"]))
            self.assertTrue(t["own_game"]["ok"], (cid, t["own_game"]["bad_columns"]))
            self.assertTrue(t["pit_check_perturbation_not_vacuous"]["ok"], (cid, t["pit_check_perturbation_not_vacuous"]))

    def test_five_inputs_covered(self):
        self.assertEqual(set(self.R["inputs"]), {"ten.within_match_dependence", "ten.hold_rate_uncertainty_propagation", "ten.player_speed_slope", "ten.set_dist", "ten.set_number_calibration"})


class PointInTime(unittest.TestCase):
    def test_same_tournament_isolation(self):
        # rewrite every LATER-round match of one tournament (outcomes, scores, stats): no row of that tournament may change, because the start date is shared
        tid = D.tourney_id.iloc[len(D) // 2]; g = RAW["matches"].tourney_id == tid
        later = set(RAW["matches"].loc[g & RAW["matches"]["round"].isin(["QF", "SF", "F"]), "game_id"])
        new = X.compute(X.perturb(RAW, later, 5))["team"]
        sel = BASE.game_id.isin(set(RAW["matches"].loc[g, "game_id"])).to_numpy()
        a, b = aligned(new, sel)
        for c in COLS: self.assertTrue(same(a[c], b[c]), c)

    def test_absurd_future_injection(self):
        # every match on/after a cut becomes a 7-6 7-6 7-6 bagel-free marathon with impossible serve stats: no earlier row may move
        cut = BASE.date.quantile(0.6); m = RAW["matches"].copy(); fut = m.date >= cut
        m.loc[fut, "score"] = "7-6 7-6 7-6"; m.loc[fut, ["w_svpt", "l_svpt"]] = 999; m.loc[fut, ["w_1stWon", "l_1stWon"]] = 900
        m.loc[fut, ["w_SvGms", "l_SvGms"]] = 1; m.loc[fut, ["w_bpFaced", "l_bpFaced"]] = 50; m.loc[fut, ["w_bpSaved", "l_bpSaved"]] = 0
        new = X.compute({**RAW, "matches": m})["team"]; a, b = aligned(new, (BASE.date < cut).to_numpy())
        for c in COLS: self.assertTrue(same(a[c], b[c]), c)

    def test_first_date_has_no_history(self):
        first = BASE[BASE.date == BASE.date.min()]
        for c in ["wmd_overdisp_pre", "wmd_form_sd_pre", "hru_p66_mean_pre", "pss_cpi_pre", "pss_beta_pre", "sd_p2_pre", "snc_logit_s1_pre"]:
            self.assertTrue(first[c].isna().all(), c)


class Arithmetic(unittest.TestCase):
    def test_holds_equal_verified_ext4(self):
        r4 = X4.compute(X4.prepare(D) if hasattr(X4, "prepare") else {"matches": RAW["matches"][["game_id", "tour", "date", "season"] + [c for c in X4.COLS4 if c != "tourney_date"]]})["team"]
        m = X.compute.__globals__["X2"]._elo(RAW["matches"].copy()); L = X._long(m)
        j = L.merge(r4, on=["game_id", "team"], how="inner")
        self.assertGreater(len(j), 1000)
        self.assertTrue(np.allclose(j.hold_pre, j.gps_hold_pre, equal_nan=True)); self.assertTrue(np.allclose(j.o_hold, j.gps_opp_hold_pre, equal_nan=True))

    def test_p66_matches_set_dp(self):
        rng = np.random.default_rng(1); pa = rng.uniform(0.5, 0.75, 200); pb = rng.uniform(0.5, 0.75, 200)
        self.assertTrue(np.allclose(X.p66(X4.hold(pa), X4.hold(pb)), X4.set_dp(X4.hold(pa), X4.hold(pb), pa, pb)["tb"]))

    def test_set_count_pmf_sums_to_one(self):
        w = np.linspace(0.05, 0.95, 19)
        for bo in (3, 5):
            pk, win = X.set_count_pmf(w, np.full(19, bo)); self.assertTrue(np.allclose(sum(pk.values()), 1)); self.assertTrue(np.all(np.diff(win) > 0))

    def test_quadrature_jensen_sign_reasonable(self):
        self.assertLess(BASE.hru_jensen_pre.abs().max(), 0.05)
        v = BASE.hru_p66_mean_pre.dropna(); self.assertTrue(len(v) > 1000 and ((v >= 0) & (v <= 1)).all())

    def test_leave_player_out_empty_event_is_zero(self):
        # a player's own matches are removed from the pace index: in an event where the player played ALL prior matches the index is 0 (only the shrink remains)
        d = T.make(n_players=2, years=2, seed=3, tours=("atp",), events_per_year=6)
        out = X.compute(X.prepare(d))["team"]
        v = out.pss_cpi_pre.dropna()
        self.assertTrue(len(v) > 0 and np.allclose(v, 0.0))


class Sensitivity(unittest.TestCase):
    def test_form_shock_is_detected(self):
        lo = X.compute(X.prepare(T.make(years=3, seed=5, tau=0.0)))["team"]; hi = X.compute(X.prepare(T.make(years=3, seed=5, tau=0.06)))["team"]
        late = lambda o: o[o.date >= o.date.quantile(0.8)]
        self.assertGreater(late(hi).wmd_form_sd_pre.mean(), late(lo).wmd_form_sd_pre.mean() + 0.015)
        self.assertGreater(late(hi).wmd_overdisp_pre.mean(), late(lo).wmd_overdisp_pre.mean())


class RealDataAnomalies(unittest.TestCase):
    def test_dirty_rows_do_not_crash_and_stay_pit(self):
        # found by the blind dirty-fixture run: a missing best_of crashed the builder (tennis_ext2._match_outcome int(NaN))
        d = D.copy(); rng = np.random.default_rng(3); ix = rng.choice(len(d), 300, replace=False)
        d.loc[ix[:30], "best_of"] = np.nan; d.loc[ix[30:60], "score"] = "W/O"; d.loc[ix[60:90], "score"] = "6-4 3-6 12-10"
        d.loc[ix[90:120], "score"] = "6-3 2-1 RET"; d.loc[ix[120:150], ["w_svpt", "w_1stWon"]] = np.nan; d.loc[ix[150:180], "l_SvGms"] = 0; d.loc[ix[180:210], "surface"] = np.nan
        raw = X.prepare(d); out = X.compute(raw)["team"]
        self.assertEqual(len(out), 2 * len(d))
        r = G.run(X, raw, "TENNIS", {"matches": ("game_id", X.CONTENT)}, games_table="matches", games_date_col="date", quick=True)
        for cid, v in r["inputs"].items():
            self.assertTrue(all(x["ok"] for x in v["tests"]["truncation"] + v["tests"]["perturbation"]), cid); self.assertTrue(v["tests"]["own_game"]["ok"], cid)


class Labelling(unittest.TestCase):
    def test_never_full_and_rights_stated(self):
        for s in X.specs():
            self.assertEqual(s.level, "PARTIAL"); self.assertEqual(s.raw, ["sackmann_atp_wta_matches"]); self.assertTrue(s.missing)
        self.assertIn("NON-COMMERCIAL", X.__doc__); self.assertIn("NOT blind-verified", X.__doc__)

    def test_load_raw_refuses_unpinned_or_tampered_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            D[D.tour == "atp"].drop(columns="tour").to_csv(Path(t) / "atp_matches_2000.csv.gz", index=False)   # right name, wrong bytes
            with self.assertRaises(ValueError): X.load_raw(t)

    def test_manifest_lists_54_pinned_files(self):
        import json
        m = json.loads(X.MANIFEST.read_text()); self.assertEqual(m["n_files"], 54)
        self.assertTrue(all(len(f["sha256"]) == 64 for f in m["files"]))

    def test_load_raw_refuses_missing_data(self):
        with self.assertRaises(FileNotFoundError): X.load_raw("/nonexistent_dir_for_test")


if __name__ == "__main__":
    unittest.main()
