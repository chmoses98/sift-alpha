import json, os, tempfile, unittest
from research.outcome_exec import integration as I
from sift_research import decision as D


class Integration(unittest.TestCase):
    def test_realised_pnl_conventions(self):
        o = dict(win=1, ask=0.5, ask90=0.45, mid=0.5, orders={(2, "Q500"): dict(status="FILLED", filled=10.0, limit=0.48),
                                                              (3, "Q500"): dict(status="UNFILLED", filled=0.0, limit=0.47),
                                                              (4, "Q500"): dict(status="UNCERTAIN", filled=0.0, limit=0.46)})
        pc = lambda x: 0.6
        buy = I.realised(o, D.BUY_NOW, None, "Q500", pc)
        self.assertAlmostEqual(buy, 1 - 0.5 - 0.018, places=6)                     # taker fee, 10 lots at 50c: ceil(0.175)=0.18 -> 0.018/contract
        self.assertEqual(I.realised(o, D.PASS, None, "Q500", pc), 0.0)
        self.assertAlmostEqual(I.realised(o, D.LIMIT, 2, "Q500", pc), 1 - 0.48 - 0.005, places=6)   # maker 0.0175*10*.2496=.044->.05 -> .005/contract
        self.assertGreater(I.realised(o, D.LIMIT, 2, "Q500", pc), 0.5)
        self.assertEqual(I.realised(o, D.LIMIT, 3, "Q500", pc), 0.0)               # unfilled = nothing happened
        self.assertIsNone(I.realised(o, D.LIMIT, 4, "Q500", pc))                    # uncertain evidence is excluded, never guessed
        self.assertIsNone(I.realised(o, D.LIMIT, 9, "Q500", pc))

    def test_fill_table_uses_only_determinate_orders(self):
        rows = [dict(win=i % 2, orders={(1, "Q500"): dict(status="FILLED" if i % 2 else "UNFILLED", filled=10.0 if i % 2 else 0.0, limit=0.5)}) for i in range(40)]
        rows += [dict(win=1, orders={(1, "Q500"): dict(status="UNCERTAIN", filled=0.0, limit=0.5)}) for _ in range(40)]
        tab, adv, n = I.fill_table(rows, "Q500")
        self.assertAlmostEqual(tab[1], 0.5); self.assertEqual(n[1], 40)
        self.assertGreaterEqual(adv, 0.0)


if __name__ == "__main__":
    unittest.main()
