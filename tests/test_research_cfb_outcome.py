import json, os, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research", "outcome_exec"))
import cfb_outcome as M  # noqa: E402


def obs(ticker, game, fam, label, hrs, kick, p, mid, ay, an, cap=None, outcome="evaluated"):
    cap = cap or (kick - timedelta(hours=hrs))
    return dict(kickoff_utc_at_capture=kick.isoformat().replace("+00:00", "Z"), observation_key=f"{ticker}{label}",
                observation=dict(captured_at=cap.isoformat().replace("+00:00", "Z"), coverage_outcome=outcome, family=fam, game_id=game,
                                 kalshi_market_ticker=ticker, model_probability=p, market_midpoint=mid, executable_yes_price=ay,
                                 executable_no_price=an, estimated_taker_fee=0.02, pricing_status="model_priced",
                                 snapshot_timing=dict(label=label, hours_before_kickoff=hrs)))


def write(root, obs_rows, sett_rows):
    for sub, rows in (("observations", obs_rows), ("settlements", sett_rows)):
        d = os.path.join(root, "data/research", sub, "2026")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "a.part001.jsonl"), "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")


def sett(t, res, status="settled", at="2026-09-10T00:00:00Z"):
    return dict(kalshi_market_ticker=t, derived_contract_settlement=res, status=status, settled_at=at)


class T(unittest.TestCase):
    def synth(self):
        k0 = datetime(2026, 9, 1, 20, tzinfo=timezone.utc)
        o, s = [], []
        for i in range(60):
            kick = k0 + timedelta(days=i // 4)
            g, t = f"g{i}", f"KXNCAAFSPREAD-X{i}-A7"
            win = i % 2
            for lab, h in (("EARLY_OPEN", 100), ("CLOSING", 1)):
                o.append(obs(t, g, "spread", lab, h, kick, 0.7, 0.5, 0.52, 0.50))
            s.append(sett(t, "yes" if win else "no"))
        o.append(obs("U1", "g0", "total", "T_3D", 70, k0, 0.5, 0.5, 0.5, 0.5, outcome="ticker_unresolved"))
        o.append(obs("LEAK", "g0", "total", "T_3D", 70, k0, 0.5, 0.5, 0.5, 0.5, cap=k0 + timedelta(hours=1)))
        o.append(obs("PEND", "g1", "total", "T_3D", 70, k0, 0.5, 0.5, 0.5, 0.5))
        s.append(sett("PEND", None, "pending_not_final"))
        s.append(sett("KXNCAAFSPREAD-X0-A7", "yes", at="2026-09-01T00:00:00Z"))   # older row must lose to latest
        return o, s

    def test_pipeline(self):
        with tempfile.TemporaryDirectory() as d:
            o, s = self.synth()
            write(d, o, s)
            res = M.run(d)
        self.assertEqual(res["status"], "RESEARCH_ONLY")
        self.assertEqual(res["coverage"]["pit_violations"], 1)       # capture after kickoff is dropped
        self.assertEqual(res["coverage"]["by_outcome"]["ticker_unresolved"], 1)
        self.assertEqual(res["coverage"]["settlement_status_of_usable_rows"]["pending_not_final"], 1)
        self.assertEqual(res["settled_tickers"], 60)                 # unsettled never imputed
        json.dumps(res, allow_nan=False)                             # JSON-safe

    def test_latest_settlement_wins_and_dedupe(self):
        with tempfile.TemporaryDirectory() as d:
            o, s = self.synth()
            o.append(o[0])                                           # exact duplicate ticker x label
            write(d, o, s)
            obs_, sett_ = M.load(d)
            rows, cov = M.build(obs_, sett_)
        self.assertEqual(cov["duplicates_dropped"], 1)
        self.assertEqual({r["y"] for r in rows if r["ticker"] == "KXNCAAFSPREAD-X0-A7"}, {0})  # i=0 -> latest 'no'

    def test_pnl_includes_fee_and_no_side(self):
        r = dict(ay=0.52, an=0.50, y=0)
        v, price, fee = M.side_pnl(r, "no")
        self.assertAlmostEqual(price, 0.50); self.assertAlmostEqual(fee, 0.02)
        self.assertAlmostEqual(v, 1 - 0.50 - 0.02)
        v, _, _ = M.side_pnl(r, "yes")
        self.assertAlmostEqual(v, 0 - 0.52 - 0.02)

    def test_split_is_chronological_and_disjoint(self):
        with tempfile.TemporaryDirectory() as d:
            o, s = self.synth()
            write(d, o, s)
            rows, _ = M.build(*M.load(d))
        part, info = M.split_games(rows)
        self.assertLess(info["discovery"]["last_kickoff"], info["holdout"]["first_kickoff"] + "Z")
        self.assertEqual(sum(v["n_games"] for v in info.values()), len({r["game"] for r in rows if r["y"] is not None}))

    def test_holdout_only_for_frozen(self):
        with tempfile.TemporaryDirectory() as d:
            o, s = self.synth()
            write(d, o, s)
            rows, _ = M.build(*M.load(d))
        dv = M.discovery_validation_holdout(rows)
        self.assertEqual(dv["cells_tried"], 192)
        for c in dv["frozen_cells_ranked"]:
            self.assertIn("holdout", c)

    def test_clean_nan(self):
        self.assertEqual(M.clean({"a": float("nan"), "b": [float("inf"), 1.0]}), {"a": None, "b": [None, 1.0]})


if __name__ == "__main__":
    unittest.main()
