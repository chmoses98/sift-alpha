"""NHL archive adapter (alpha_eval.nhl_archive): synthetic local fixtures only; no network."""
import gzip
import json
import os
import tempfile
import unittest

from alpha_eval import nhl_archive as H
from alpha_eval.grading import grade_all

START = "2026-11-10T00:00:00Z"
G = "2026020100"


def _w(root, rel, rows):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with gzip.open(p, "wt") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return rel


def _sched(game=G, start=START, home="LAK", away="BOS", date="2026-11-09"):
    return dict(game_id=game, game_date_et=date, start_time_utc=start, home_abbrev=home, away_abbrev=away, status="final",
                _observed_at_utc="2026-11-09T12:00:00Z")


def _contract(ticker, fam="game_winner", game=G):
    return dict(ticker=ticker, game_id=game, family=fam, event_ticker=ticker.rsplit("-", 1)[0], series_ticker=ticker.split("-")[0],
                _observed_at_utc="2026-11-09T12:00:00Z")


def _pred(ticker, t, p, fam="game_winner", col="p_data_only", bid=40, ask=42, pid=None, game=G):
    return {"ticker": ticker, "game_id": game, "family": fam, "predicted_at_utc": t, "market_observed_at_utc": t, "market_yes_bid": bid,
            "market_yes_ask": ask, col: p, "prediction_id": pid or f"{ticker}-{t}", "model_version": "DATA_ONLY_V1", "sim_version": "s",
            "feature_version": "f", "threshold": 0.0, "horizon_label": "T-1h"}


def _kalshi(kdir, series, markets):
    os.makedirs(kdir, exist_ok=True)
    with gzip.open(os.path.join(kdir, f"{series}_p0000.json.gz"), "wt") as f:
        json.dump(dict(markets=markets, cursor=""), f)


def _km(ticker, result="yes"):
    return dict(ticker=ticker, event_ticker=ticker.rsplit("-", 1)[0], result=result, settlement_ts="2026-11-10T03:00:00Z")


class Fixture:
    def __init__(self):
        self.d = tempfile.mkdtemp()
        self.root = os.path.join(self.d, "arch")
        self.kdir = os.path.join(self.d, "kalshi")
        self.adds = []   # (commit_time, [paths])

    def add(self, rel, rows, committed):
        _w(self.root, rel, rows)
        self.adds.append((committed, [rel]))

    def adds_file(self):
        p = os.path.join(self.d, "adds.txt")
        with open(p, "w") as f:
            for i, (t, paths) in enumerate(self.adds):
                f.write(f"C {i:040d} {t}\n\n" + "\n".join(paths) + "\n\n")
        return p

    def build(self, as_of="2026-11-12T00:00:00Z"):
        return H.build(self.root, H.load_file_adds(self.adds_file()), H.load_kalshi_settled(self.kdir), as_of=as_of)


T = "KXNHLGAME-26NOV09BOSLA-LA"


def base(fx, kres="yes", psett="YES"):
    _w(fx.root, "context/schedule/dt=2026-11-09/s.jsonl.gz", [_sched()])
    _w(fx.root, "contracts/dt=2026-11-09/c.jsonl.gz", [_contract(T)])
    _w(fx.root, "settlements/dt=2026-11-10/s.jsonl.gz", [dict(ticker=T, game_id=G, outcome=psett, settled_at_utc="2026-11-10T04:00:00Z",
                                                                _observed_at_utc="2026-11-10T04:00:00Z")])
    _kalshi(fx.kdir, "KXNHLGAME", [_km(T, kres)])


class TestSelectionAndFreeze(unittest.TestCase):
    def test_latest_attested_capture_wins_over_later_unattested(self):
        fx = Fixture(); base(fx)
        fx.add("predictions/dt=2026-11-09/a.jsonl.gz", [_pred(T, "2026-11-09T20:00:00Z", 0.55)], "2026-11-09T20:01:00+00:00")
        fx.add("predictions/dt=2026-11-09/b.jsonl.gz", [_pred(T, "2026-11-09T23:55:00Z", 0.60)], "2026-11-10T00:20:00+00:00")  # committed after start
        b = fx.build()
        f = [x for x in b["forecasts"] if x["model_id"] == "DATA_ONLY_V1"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["payload"]["p_yes"], 0.55)
        self.assertEqual(f[0]["evidence_class"], "PROSPECTIVE")
        self.assertEqual(f[0]["frozen_at"], "2026-11-09T20:00:00Z")

    def test_unattested_only_is_blocked_not_frozen(self):
        fx = Fixture(); base(fx)
        fx.add("predictions/dt=2026-11-09/b.jsonl.gz", [_pred(T, "2026-11-09T23:55:00Z", 0.60)], "2026-11-10T00:20:00+00:00")
        b = fx.build()
        f = b["forecasts"][0]
        self.assertEqual(f["evidence_class"], "BACKTEST")
        self.assertEqual(f["frozen_at"], "2026-11-10T00:20:00Z")
        g = grade_all(b["forecasts"], b["outcomes"], b["quotes"], [], eligible_rows=b["eligible"], as_of=b["as_of"])
        self.assertEqual(g["rows"][0]["accuracy"]["reason"], "FORECAST_NOT_FROZEN_BEFORE_EVENT_START")

    def test_capture_after_start_never_emitted(self):
        fx = Fixture(); base(fx)
        fx.add("predictions/dt=2026-11-10/a.jsonl.gz", [_pred(T, "2026-11-10T00:05:00Z", 0.9)], "2026-11-10T00:06:00+00:00")
        b = fx.build()
        self.assertEqual(b["forecasts"], [])
        self.assertEqual(b["info"]["DATA_ONLY_V1.captured_after_start"], 1)

    def test_null_probability_is_counted_not_forecast(self):
        fx = Fixture(); base(fx)
        fx.add("predictions/dt=2026-11-09/a.jsonl.gz", [_pred(T, "2026-11-09T20:00:00Z", None)], "2026-11-09T20:01:00+00:00")
        b = fx.build()
        self.assertEqual(b["forecasts"], [])
        self.assertEqual(b["market_not_forecast_reasons"]["game_winner"], {"LISTED_PROBABILITY_ALWAYS_NULL": 1})

    def test_duplicate_file_add_keeps_earliest(self):
        fx = Fixture()
        fx.adds = [("2026-11-09T21:00:00+00:00", ["x"]), ("2026-11-09T20:00:00+00:00", ["x"])]
        a = H.load_file_adds(fx.adds_file())
        self.assertEqual(a["adds"]["x"][1].isoformat(), "2026-11-09T20:00:00+00:00")
        self.assertEqual(a["duplicate_adds"], ["x"])


class TestOutcomes(unittest.TestCase):
    def _graded(self, fx):
        fx.add("predictions/dt=2026-11-09/a.jsonl.gz", [_pred(T, "2026-11-09T20:00:00Z", 0.55)], "2026-11-09T20:01:00+00:00")
        b = fx.build()
        return b, grade_all(b["forecasts"], b["outcomes"], b["quotes"], [], eligible_rows=b["eligible"], as_of=b["as_of"])

    def test_kalshi_result_grades_with_alias_team_code(self):
        fx = Fixture(); base(fx)
        b, g = self._graded(fx)
        self.assertEqual(b["identity"], {"OK": 1})
        self.assertEqual(g["rows"][0]["accuracy"]["status"], "GRADED")
        self.assertEqual(b["outcomes"][0]["source"], "market_settlement")

    def test_producer_disagreement_blocks_market(self):
        fx = Fixture(); base(fx, kres="yes", psett="NO")
        b, g = self._graded(fx)
        self.assertEqual(b["producer_crosscheck"], {"DISAGREE": 1})
        self.assertEqual(g["rows"][0]["accuracy"]["reason"], "CONFLICTING_OUTCOME_ROWS_FOR_MARKET")

    def test_scalar_settlement_is_void(self):
        fx = Fixture(); base(fx, kres="scalar")
        b, g = self._graded(fx)
        self.assertEqual(b["outcomes"][0]["state"], "void")
        self.assertEqual(g["rows"][0]["accuracy"]["reason"], "OUTCOME_VOID_OR_POSTPONED")

    def test_identity_mismatch_blocks(self):
        fx = Fixture(); base(fx)
        # producer says the ticker belongs to another game id than the Kalshi ticker's date/teams resolve to
        _w(fx.root, "contracts/dt=2026-11-09/c.jsonl.gz", [_contract(T, game="2026020999")])
        _w(fx.root, "context/schedule/dt=2026-11-09/s.jsonl.gz", [_sched(), _sched(game="2026020999", date="2026-11-08",
                                                                                   start="2026-11-09T00:00:00Z", home="NYR", away="NJD")])
        fx.add("predictions/dt=2026-11-08/a.jsonl.gz", [_pred(T, "2026-11-08T20:00:00Z", 0.55, game="2026020999")], "2026-11-08T20:01:00+00:00")
        b = fx.build()
        g = grade_all(b["forecasts"], b["outcomes"], b["quotes"], [], eligible_rows=b["eligible"], as_of=b["as_of"])
        self.assertEqual(g["rows"][0]["accuracy"]["reason"], "OUTCOME_EVENT_ID_DOES_NOT_MATCH_FORECAST")

    def test_unmatched_team_codes_are_counted_unmapped(self):
        fx = Fixture(); base(fx)
        _kalshi(fx.kdir, "KXNHLGAME", [_km("KXNHLGAME-26NOV09ZZZQQQ-ZZZ")])
        b = fx.build()
        self.assertEqual(b["identity"], {"TEAM_CODES_UNMATCHED": 1})
        e = [x for x in b["eligible"] if x["market_id"].startswith("KXNHLGAME-26NOV09ZZZ")][0]
        self.assertTrue(e["event_id"].startswith("UNMAPPED:TEAM_CODES_UNMATCHED"))


class TestQuotesAndReconcile(unittest.TestCase):
    def test_quotes_in_dollars_at_freeze_and_close(self):
        fx = Fixture(); base(fx)
        fx.add("predictions/dt=2026-11-09/a.jsonl.gz", [_pred(T, "2026-11-09T20:00:00Z", 0.55, bid=40, ask=42),
                                                        _pred(T, "2026-11-09T21:00:00Z", None, bid=44, ask=46),
                                                        _pred(T, "2026-11-09T23:50:00Z", None, bid=47, ask=49)], "2026-11-09T23:51:00+00:00")
        b = fx.build()
        q = sorted((x["observed_at"], x["yes_bid"], x["yes_ask"]) for x in b["quotes"])
        # the 21:00 observation is neither the last at/before the emitted freeze nor the last before start
        self.assertEqual(q, [("2026-11-09T20:00:00Z", 0.40, 0.42), ("2026-11-09T23:50:00Z", 0.47, 0.49)])
        self.assertEqual(b["forecasts"][0]["payload"]["p_yes"], 0.55)

    def test_reconcile_partition_and_never_listed(self):
        fx = Fixture(); base(fx)
        _kalshi(fx.kdir, "KXNHLGAME", [_km(T), _km("KXNHLGAME-26NOV09BOSLA-BOS", "no")])
        fx.add("predictions/dt=2026-11-09/a.jsonl.gz", [_pred(T, "2026-11-09T20:00:00Z", 0.55)], "2026-11-09T20:01:00+00:00")
        b = fx.build()
        g = grade_all(b["forecasts"], b["outcomes"], b["quotes"], [], eligible_rows=b["eligible"], as_of=b["as_of"])
        r = H.reconcile(b["eligible"], g["rows"], b["forecasts"])
        self.assertEqual(r["n_eligible"], 2)
        self.assertEqual(sum(r["total"].values()), 2)
        self.assertEqual(r["total"], {"FORECAST_AND_GRADED": 1, "NOT_FORECAST_MODELLED_FAMILY": 1})
        self.assertEqual(b["market_not_forecast_reasons"]["game_winner"], {"NEVER_LISTED_BY_PRODUCER": 1})

    def test_confirmation_test_is_pinned(self):
        self.assertEqual(H.PRIOR_AUDIT_DATA_PIN, "2026-11-04T19:38:30Z")
        self.assertEqual((H.CONFIRMATION_TEST["model_id"], H.CONFIRMATION_TEST["native_family"], H.CONFIRMATION_TEST["alpha"]),
                         ("PLAYER_SIM_V1", "goalie_saves", 0.05))


if __name__ == "__main__":
    unittest.main()
