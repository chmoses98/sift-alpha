import csv, datetime as dt, json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from research.exec_track import shadow_ledger as SL
from sift_exec import shadow_report as SR
from sift_research import shadow_orders as SO

KO = dt.datetime(2026, 11, 8, 18, 0, tzinfo=dt.timezone.utc).timestamp()
T = "KXNFLGAME-26NOV08AAABBB-AAA"


def iso(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat()


def quote(t, b, a, bs=1000, az=500, run="r"):
    return json.dumps({"run_id": run, "observed_at": iso(t), "ticker": T, "series_ticker": "KXNFLGAME", "game_id": "2026_09_AAA_BBB", "kickoff_utc": iso(KO),
                       "yes_bid_dollars": f"{b/100:.4f}", "yes_ask_dollars": f"{a/100:.4f}", "yes_bid_size_fp": f"{bs:.2f}", "yes_ask_size_fp": f"{az:.2f}"}, separators=(",", ":"))


def trade(i, t, yes, n, taker):
    return json.dumps({"run_id": "r", "trade_id": f"x{i}", "created_time": iso(t), "ticker": T, "yes_price_dollars": f"{yes/100:.4f}", "count_fp": f"{n:.2f}", "taker_side": taker}, separators=(",", ":"))


def make(d, quotes, trades):
    open(os.path.join(d, "quotes.jsonl"), "w").write("\n".join(quotes) + "\n")
    open(os.path.join(d, "trades.jsonl"), "w").write("\n".join(trades) + "\n")
    g = os.path.join(d, "games.csv")
    with open(g, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["game_id", "season", "home_team", "away_team", "home_score", "away_score"]); w.writerow(["2026_09_AAA_BBB", "2026", "BBB", "AAA", "17", "20"])
    return g


def scenario(d, record_delay=0):
    h24 = KO - 24 * 3600
    qs = [quote(h24 + 60, 40, 43, bs=1000), quote(KO - 3 * 3600, 41, 44), quote(KO - 16 * 60, 39, 42),   # last pre-close quote: close bid 39 / ask 42
          quote(KO - 5 * 60, 10, 90)]                                                                   # AFTER the deadline: must never be used as a close
    trs = [trade(1, h24 + 3600, 39, 5, "no"),                 # through our 40c bid  -> confirmed fill (size 5 of 10)
           trade(2, KO - 3600, 40, 200, "no")]                # at-level print smaller than the displayed 1000 queue -> not a central fill
    return make(d, qs, trs), KO + 3 * 3600


class Ledger(unittest.TestCase):
    def test_point_in_time_snapshot_queue_and_fill_classes(self):
        with tempfile.TemporaryDirectory() as d:
            g, now = scenario(d); led = os.path.join(d, "l.jsonl")
            SL.build(d, led, g, now=now, recorded_at=now)
            rows = [json.loads(l) for l in open(led)]
            pl = [r for r in rows if r["kind"] == "PLACED" and r["horizon_name"] == "24h"]
            self.assertTrue(pl); self.assertTrue(all(r["bid"] == 0.40 and r["ask"] == 0.43 for r in pl))
            self.assertTrue(all(r["placed_at"] == iso(KO - 24 * 3600 + 60) for r in pl))                  # first quote at/after the crossing, not a later one
            atbid = [r for r in pl if r["action"] == "LIMIT" and r["limit"] == 0.40][0]
            self.assertEqual(atbid["displayed_queue_at_limit"], 1000.0)
            ev = [r for r in rows if r["kind"] == "OBSERVED" and r["decision_id"] == atbid["decision_id"]]
            lo = [e for e in ev if e["evidence"] == "TAPE_FILL_BOUND_LO"][0]
            self.assertEqual(lo["size"], 10.0)                                                                # a print strictly below the limit fills the whole remainder
            self.assertNotIn("FILLED", {r.get("evidence") for r in rows})                                     # a shadow order is never recorded as FILLED
            self.assertTrue(all(r["status"] == "RESEARCH_ONLY" for r in rows)); self.assertTrue(all(r.get("generated") == "HYPOTHETICAL_SHADOW" for r in rows if r["kind"] == "PLACED"))
            st = [r for r in rows if r["kind"] == "SETTLED"][0]
            self.assertEqual((st["close_bid"], st["close_ask"]), (0.39, 0.42))                                # the 10/90 quote after kickoff-15m is never the close
            self.assertEqual(st["win"], 1)                                                                    # AAA (away, 20) beat BBB (home, 17)
    def test_prospective_vs_retrospective_and_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            g, now = scenario(d); led = os.path.join(d, "l.jsonl")
            n1 = SL.build(d, led, g, now=now, recorded_at=now)
            n2 = SL.build(d, led, g, now=now, recorded_at=now)
            self.assertGreater(n1["placed"], 0); self.assertNotIn("placed", n2)
            gens = {json.loads(l)["generation"] for l in open(led) if '"PLACED"' in l}
            self.assertEqual(gens, {"RETROSPECTIVE_REPLAY"})
            led2 = os.path.join(d, "l2.jsonl")
            SL.build(d, led2, g, now=KO - 23 * 3600, recorded_at=KO - 24 * 3600 + 120)                            # recorded 60 s after the snapshot
            self.assertEqual({json.loads(l)["generation"] for l in open(led2) if '"PLACED"' in l}, {"PROSPECTIVE"})

    def test_unknown_result_is_pending_not_a_loss(self):
        with tempfile.TemporaryDirectory() as d:
            g, now = scenario(d); led = os.path.join(d, "l.jsonl")
            open(g, "w").write("game_id,season,home_team,away_team,home_score,away_score\n")
            SL.build(d, led, g, now=now, recorded_at=now)
            st = [json.loads(l) for l in open(led) if '"SETTLED"' in l]
            self.assertTrue(st and all(s["win"] is None and s["win_known"] is False for s in st))
            ev = SO.evaluate(led)["by_action"]["WAIT"]
            self.assertGreater(ev["outcome_pending"], 0)

    def test_matched_report_equal_exposure_arithmetic(self):
        with tempfile.TemporaryDirectory() as d:
            g, now = scenario(d); led = os.path.join(d, "l.jsonl")
            SL.build(d, led, g, now=now, recorded_at=now)
            placed, obs, sett = SR.read(led)
            fb = [p for p in placed.values() if p["action"] == "LIMIT" and p["fallback"] == "TAKE_AT_CLOSE" and p["limit"] == 0.40 and p["horizon_name"] == "24h"][0]
            lo, cen, up = SR.fills(fb, obs[fb["decision_id"]])
            self.assertEqual((lo, up), (10.0, 10.0)); self.assertLessEqual(lo, cen); self.assertLessEqual(cen, up)
            # equal exposure: filled 10 @40c maker, close ask 42c -> saves 2c/contract before fee differences
            from sift_exec import fees as FE
            exp = 42 - 40 - (100 * FE.order_fee(40, 10, 0.0175) - 100 * FE.order_fee(42, 10, FE.TAKER_COEF)) / 10
            wait_cost = SR.cents(42, 10.0, FE.TAKER_COEF); fb_cost = SR.cents(40, 10.0, 0.0175)
            self.assertAlmostEqual((wait_cost - fb_cost) / 10, exp)


if __name__ == "__main__":
    unittest.main()
