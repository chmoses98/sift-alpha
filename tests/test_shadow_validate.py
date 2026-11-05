import datetime as dt, importlib.util, json, os, tempfile, unittest
from sift_research import shadow_orders as SO

spec = importlib.util.spec_from_file_location("vso", os.path.join(os.path.dirname(__file__), "..", "research", "exec_track", "validate_shadow_output.py"))
V = importlib.util.module_from_spec(spec); spec.loader.exec_module(V)
KO = dt.datetime(2026, 11, 8, 18, 0, tzinfo=dt.timezone.utc)


def rec(placed_min_before_ko=1500, recorded_lag_s=60, ticker="KXNFLGAME-26NOV08AAABBB-AAA", **over):
    pa = KO - dt.timedelta(minutes=placed_min_before_ko)
    r = SO.placed(ticker=ticker, side="YES", action="BUY_NOW", limit=None, placed_at=pa, kickoff=KO, bid=0.48, ask=0.50, p=0.49, p_se=0.0, model_version="MARKET_MID_BENCHMARK", horizon="24h")
    ra = pa + dt.timedelta(seconds=recorded_lag_s)
    pro = recorded_lag_s <= 1800
    r.update(recorded_at=ra.isoformat(), prospective=pro, generation="PROSPECTIVE" if pro else "RETROSPECTIVE_REPLAY", game_id="g1")
    r.update(over); r["decision_id"] = SO.decision_id(r)
    return r


def write(rows):
    p = tempfile.mktemp(suffix=".jsonl")
    open(p, "w").write("\n".join(json.dumps(x) for x in rows) + ("\n" if rows else ""))
    return p


class ValidateShadow(unittest.TestCase):
    def test_valid_prospective_and_retrospective_are_counted_separately(self):
        c, e = V.validate(write([rec(), rec(placed_min_before_ko=1400, recorded_lag_s=86400)]))
        self.assertEqual(e, []); self.assertEqual((c["prospective"], c["retrospective"]), (1, 1))

    def test_tactic_rows_are_not_independent_decisions_or_games(self):
        rows = [rec(action="BUY_NOW"), rec(action="WAIT"), rec(action="PASS")]
        for r in rows: r["decision_id"] = SO.decision_id(r)
        rows.append(rec(placed_min_before_ko=1400, ticker="KXNFLGAME-26NOV08CCCDDD-CCC", game_id="g2"))
        c, e = V.validate(write(rows))
        self.assertEqual(e, [])
        self.assertEqual(c["prospective"], 4)
        self.assertEqual(c["prospective_unique_decisions"], 2)
        self.assertEqual(c["prospective_independent_games"], 2)

    def test_missing_or_empty_ledger_is_failure_not_success(self):
        self.assertIn("LEDGER_MISSING_OR_EMPTY", V.validate("/nonexistent")[1])
        self.assertIn("LEDGER_MISSING_OR_EMPTY", V.validate(write([]))[1])

    def test_rules_reject_lookahead_wrong_contract_and_mislabelled_prospective(self):
        for r, why in ((rec(placed_min_before_ko=10), "PLACED_AFTER_CLOSE_CUTOFF"), (rec(ticker="KXNFLSPREAD-26NOV08AAABBB-AAA"), "CONTRACT"),
                       (rec(recorded_lag_s=-5), "RECORDED_BEFORE_PLACED"), (rec(prospective=True, generation="PROSPECTIVE", recorded_lag_s=86400), "PROSPECTIVE_FLAG")):
            if why == "PROSPECTIVE_FLAG":
                r["recorded_at"] = (dt.datetime.fromisoformat(r["placed_at"]) + dt.timedelta(days=1)).isoformat()
            r["decision_id"] = SO.decision_id(r)
            _, e = V.validate(write([r]))
            self.assertTrue(any(why in x for x in e), (why, e))

    def test_tampered_decision_id_and_duplicates_rejected(self):
        r = rec(); r["horizon"] = "6h"
        self.assertTrue(any("DECISION_ID" in x for x in V.validate(write([r]))[1]))
        r2 = rec()
        self.assertTrue(any("DUPLICATE" in x for x in V.validate(write([r2, dict(r2)]))[1]))

    def test_observed_never_a_fill_and_inside_window(self):
        d = rec()
        ok = SO.observed(d, evidence="TAPE_FILL_BOUND_LO", observed_at=dt.datetime.fromisoformat(d["placed_at"]) + dt.timedelta(minutes=5))
        c, e = V.validate(write([d, ok])); self.assertEqual(e, []); self.assertEqual(c["observed"], 1)
        bad = dict(ok, evidence="FILLED")
        self.assertTrue(any("OBSERVED_EVIDENCE_CLASS" in x for x in V.validate(write([d, bad]))[1]))


if __name__ == "__main__":
    unittest.main()
