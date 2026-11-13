"""Regression tests for the REAL NBA PURE shadow-store adapter (alpha_eval.nba_shadow): event identity is preserved, outcome joins are
verified by independent artefacts, absences are reconciled to exact categories, and freeze evidence is checked. Builds a small but
structurally real store (gzip JSONL + a valid hash chain + manifest) in a temp dir; no network, no producer code."""
import gzip
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from alpha_eval import nba_shadow as N
from alpha_eval.grading import grade_all
from alpha_eval.report import build_report

KICK = "2026-11-01T20:30:00Z"
AS_OF = "2026-11-01T14:00:00Z"
GAME = "espn:1"
TK = "KXNBAPTS-26NOV01BOSORL-ORLJSMITH3-10"       # BOS at ORL, 2026-11-01 (ET), player code = ORL + J + SMITH + 3, rung 10
GID = {GAME: dict(home="ORL", away="BOS", start=KICK)}


def _write(root, rel, rows):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with gzip.open(p, "wt") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return p


def proj_row(pid, *, stat="points", game=GAME, probs=((10, .9), (20, .4)), as_of=AS_OF, kick=KICK):
    return dict(as_of=as_of, conditional_on_playing=True, game_id=game, kickoff=kick, model_frozen_hash="sha256:aa", model_version="V1",
                player_id=pid, statistic=stat, sport="NBA", source_max_observed_at=as_of, x_capture_mode="LIVE", x_slot="morning",
                x_season_phase="REGULAR_SEASON", feature_lineage=[dict(**{"class": "sports_only"}, name="x")],
                projection=dict(mean=14.0, median=14.0, p10=6.0, p90=22.0, thresholds=[dict(at_least=a, probability=p) for a, p in probs]))


def make_store(root, *, rows=None, written_at="2026-11-01T14:00:05Z", listing=True, gate=None, tamper=False):
    rows = rows or [proj_row("-100"), proj_row("-200"), proj_row("-300")]
    paths = {"proj": _write(root, "projections/sim_rotation/conditional/dt=2026-11-01/p.jsonl.gz", rows)}
    if listing:
        paths["lst"] = _write(root, "market/listings/dt=2026-11-01/l.jsonl.gz", [dict(
            record="market_listing", game_id=GAME, player_id="-100", statistic="points", pure_as_of=AS_OF, at_least=10.0, ticker=TK,
            board_observed_at="2026-11-01T13:50:00Z", yes_bid_cents=60, yes_ask_cents=64, listed_by_as_of=True, series="KXNBAPTS")])
    gate = gate if gate is not None else [dict(game_id=GAME, player_id="-100", statistic="points", actual=12.0, played=True,
                                              observed_at="2026-11-01T23:30:00Z")]
    paths["gate"] = _write(root, "outcomes/gate/dt=2026-11-01/g.jsonl.gz", gate)
    prev, chain, man = "0" * 64, [], []
    for i, (k, p) in enumerate(sorted(paths.items()), 1):
        rel = os.path.relpath(p, root)
        sha = hashlib.sha256(open(p, "rb").read()).hexdigest()
        link = hashlib.sha256(f"{prev}|{rel}|{sha}".encode()).hexdigest()
        chain.append(dict(seq=i, path=rel, prev=prev, sha256=sha, link=link))
        man.append(dict(path=rel, sha256=sha, written_at_utc=written_at))
        prev = link
    with open(os.path.join(root, "chain.jsonl"), "w") as f:
        f.write("\n".join(json.dumps(c) for c in chain) + "\n")
    with open(os.path.join(root, "manifest.jsonl"), "w") as f:
        f.write("\n".join(json.dumps(m) for m in man) + "\n")
    if tamper:                                                      # change the projection bytes AFTER the chain was written
        _write(root, "projections/sim_rotation/conditional/dt=2026-11-01/p.jsonl.gz", [proj_row("-100", probs=((10, .99),))])
    return paths


def avail(pid, status, *, captured="2026-11-01T13:00:00Z"):
    return dict(captured_utc=captured, entity_id="espn:" + pid.lstrip("-"), event_id=GAME, status=status, kind="injury",
                source="nba_official_injury_report")


class NbaShadowAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def grade(self, b):
        return grade_all(b["forecasts"], b["outcomes"], b["quotes"], [], eligible_rows=b["eligible"], as_of=b["info"]["data_horizon"])

    def priced(self, g):
        return [r for r in g["rows"] if r["market_id"] == TK]

    # -- pure helpers
    def test_ticker_parse_and_identity_unit(self):
        t = N.parse_ticker(TK)
        self.assertEqual((t["series"], t["date"], t["away"], t["home"]), ("KXNBAPTS", "2026-11-01", "BOS", "ORL"))
        self.assertEqual(N.check_identity(TK, GID[GAME]), "IDENTITY_VERIFIED")
        self.assertEqual(N.check_identity(TK, dict(home="BOS", away="ORL", start=KICK)), "MISMATCH_TEAMS")
        self.assertEqual(N.check_identity(TK, dict(home="ORL", away="BOS", start="2026-11-03T20:30:00Z")), "MISMATCH_DATE")
        self.assertEqual(N.check_identity(TK.replace("ORLJSMITH3", "NYKJSMITH3"), GID[GAME]), "MISMATCH_PLAYER_TEAM_NOT_IN_GAME")
        self.assertEqual(N.check_identity(TK, None), "IDENTITY_UNVERIFIABLE_NO_GAME_RECORD")
        self.assertEqual(N.check_identity("garbage", GID[GAME]), "IDENTITY_UNPARSEABLE_TICKER")
        self.assertIsNone(N.parse_ticker("KXNBAPTS-26FOO01BOSORL-X"))

    def test_et_date_uses_local_calendar_not_utc(self):
        late = dict(home="ORL", away="BOS", start="2026-11-02T01:30:00Z")        # 20:30 ET on Nov 1
        self.assertEqual(N.check_identity(TK, late), "IDENTITY_VERIFIED")

    # -- event identity preserved through the whole pipeline
    def test_event_identity_is_preserved_from_projection_and_gate(self):
        make_store(self.root)
        b = N.build(self.root, game_identity=GID)
        self.assertTrue(all(f["event_id"] == GAME and f["group_id"] == GAME for f in b["forecasts"]))
        self.assertTrue(all(o["event_id"] == GAME for o in b["outcomes"]))
        g = self.grade(b)
        r = self.priced(g)[0]
        self.assertEqual((r["accuracy"]["status"], r["accuracy"]["y"]), ("GRADED", 1))
        self.assertEqual(r["market"]["status"], "GRADED")
        self.assertEqual(b["info"]["identity[IDENTITY_VERIFIED]"], 1)

    def test_ticker_identity_mismatch_blocks_via_the_standards_event_join(self):
        make_store(self.root)
        for bad in (dict(home="BOS", away="ORL", start=KICK), dict(home="ORL", away="BOS", start="2026-11-04T20:30:00Z")):
            b = N.build(self.root, game_identity={GAME: bad})
            self.assertTrue(all(o["event_id"] == GAME + "#TICKER_IDENTITY_MISMATCH" for o in b["outcomes"] if o["market_id"] == TK))
            r = self.priced(self.grade(b))[0]
            self.assertEqual((r["accuracy"]["status"], r["accuracy"]["reason"]), ("BLOCKED", "OUTCOME_EVENT_ID_DOES_NOT_MATCH_FORECAST"))
            self.assertEqual(r["market"]["status"], "BLOCKED")

    def test_forecast_event_id_never_rewritten_on_mismatch(self):
        make_store(self.root)
        b = N.build(self.root, game_identity={GAME: dict(home="BOS", away="ORL", start=KICK)})
        self.assertTrue(all(f["event_id"] == GAME for f in b["forecasts"]))

    def test_without_independent_game_record_identity_is_reported_not_assumed(self):
        make_store(self.root)
        self.assertEqual(N.build(self.root)["info"]["identity[IDENTITY_NOT_CHECKED]"], 1)
        self.assertEqual(N.build(self.root, game_identity={})["info"]["identity[IDENTITY_UNVERIFIABLE_NO_GAME_RECORD]"], 1)

    # -- independent outcome-value verification (separately implemented settle engine)
    def test_settlement_agreement_grades_and_disagreement_blocks(self):
        make_store(self.root)
        yes = {TK: dict(ticker=TK, outcome="YES", reason="x")}
        b = N.build(self.root, game_identity=GID, settlements=yes)
        self.assertEqual(b["info"]["outcome_xcheck[AGREE]"], 1)
        self.assertEqual(self.priced(self.grade(b))[0]["accuracy"]["status"], "GRADED")
        no = {TK: dict(ticker=TK, outcome="NO", reason="corrected box")}
        b = N.build(self.root, game_identity=GID, settlements=no)
        self.assertEqual(b["info"]["outcome_xcheck[DISAGREE]"], 1)
        r = self.priced(self.grade(b))[0]
        self.assertEqual((r["accuracy"]["status"], r["accuracy"]["reason"]), ("BLOCKED", "CONFLICTING_OUTCOME_ROWS_FOR_MARKET"))

    def test_settlement_rung_semantics_match_ticker_threshold(self):
        # actual 12 vs rung 10: YES; if the box said 9, adapter says NO and a YES settlement must conflict
        make_store(self.root, gate=[dict(game_id=GAME, player_id="-100", statistic="points", actual=9.0, played=True, observed_at="2026-11-01T23:30:00Z")])
        b = N.build(self.root, game_identity=GID, settlements={TK: dict(ticker=TK, outcome="NO", reason="x")})
        self.assertEqual(b["info"]["outcome_xcheck[AGREE]"], 1)

    def test_unsettleable_settlement_is_counted_never_overridden(self):
        make_store(self.root)
        b = N.build(self.root, game_identity=GID, settlements={TK: dict(ticker=TK, outcome="UNSETTLEABLE", reason="DNP: consult Kalshi rules/result")})
        self.assertEqual(sum(v for k, v in b["info"].items() if k.startswith("outcome_xcheck[SETTLEMENT_UNSETTLEABLE")), 1)
        self.assertEqual(self.priced(self.grade(b))[0]["accuracy"]["status"], "GRADED")       # adapter's own outcome stands

    # -- absence reconciliation
    def test_absent_players_are_partitioned_exactly_and_only_official_out_is_void(self):
        later = dict(game_id="espn:later", player_id="-9", statistic="points", actual=1.0, played=True, observed_at="2026-11-03T00:00:00Z")
        make_store(self.root, gate=[dict(game_id=GAME, player_id="-100", statistic="points", actual=12.0, played=True,
                                         observed_at="2026-11-01T23:30:00Z"), later])        # data horizon > kickoff + 24h grace
        av = [avail("-200", "OUT"), avail("-300", "QUESTIONABLE")]
        b = N.build(self.root, game_identity=GID, availability=av)
        i = b["info"]
        self.assertEqual(i["absent_player_games_total"], 2)
        self.assertEqual(i["absent_player_games[ABSENT_OFFICIAL_OUT_PRE_KICKOFF]"], 1)
        self.assertEqual(i["absent_player_games[ABSENT_REPORTED_AVAILABLE_OR_QUESTIONABLE]"], 1)
        self.assertEqual(sum(v for k, v in i.items() if k.startswith("absent_player_games[")), i["absent_player_games_total"])
        g = self.grade(b)
        s = {r["market_id"].split("|")[1]: r["accuracy"] for r in g["rows"] if r["scoring_type"] == "BINARY" and "|" in r["market_id"]}
        self.assertEqual(s["-200"]["reason"], "OUTCOME_VOID_OR_POSTPONED")                    # corroborated non-appearance
        self.assertEqual(s["-300"]["reason"], "NO_OUTCOME_ROW_EVENT_OVERDUE")                 # unexplained: not scored, not hidden

    def test_absence_inside_the_grace_window_stays_pending(self):
        make_store(self.root)                                                                  # horizon = kickoff + 3h < 24h grace
        g = self.grade(N.build(self.root, game_identity=GID, availability=[avail("-300", "ACTIVE")]))
        s = {r["market_id"].split("|")[1]: r["accuracy"] for r in g["rows"] if r["scoring_type"] == "BINARY" and "|" in r["market_id"]}
        self.assertEqual((s["-300"]["status"], s["-300"]["reason"]), ("PENDING", "NO_OUTCOME_ROW"))

    def test_availability_after_kickoff_never_corroborates(self):
        make_store(self.root)
        b = N.build(self.root, game_identity=GID, availability=[avail("-200", "OUT", captured="2026-11-01T22:00:00Z"), avail("-100", "ACTIVE")])
        cats = {k: v for k, v in b["info"].items() if k.startswith("absent_player_games[")}
        self.assertEqual(cats, {"absent_player_games[ABSENT_NO_REPORT_INSIDE_AVAILABILITY_WINDOW]": 2})   # a post-kickoff OUT is not evidence

    def test_archive_window_boundary_is_explicit(self):
        make_store(self.root)
        b = N.build(self.root, game_identity=GID, availability=[avail("-100", "ACTIVE", captured="2026-11-05T00:00:00Z")])
        self.assertEqual(b["info"]["absent_player_games[ABSENT_BEFORE_AVAILABILITY_ARCHIVE_STARTED]"], 2)

    def test_absence_not_evaluated_for_games_without_outcomes(self):
        make_store(self.root, gate=[dict(game_id="espn:other", player_id="-1", statistic="points", actual=1.0, played=True, observed_at="2026-11-01T23:30:00Z")])
        b = N.build(self.root, game_identity=GID, availability=[])
        self.assertEqual(b["info"]["absent_player_games_total"], 0)                             # our game is not final: PENDING, not absent

    # -- freeze evidence
    def test_verified_chain_and_early_archive_are_prospective(self):
        make_store(self.root)
        b = N.build(self.root, game_identity=GID)
        self.assertTrue(b["chain"]["ok"])
        self.assertTrue(all(f["evidence_class"] == "PROSPECTIVE" for f in b["forecasts"]))

    def test_tampered_file_is_demoted_to_backtest(self):
        make_store(self.root, tamper=True)
        b = N.build(self.root, game_identity=GID)
        self.assertFalse(b["chain"]["ok"])
        self.assertTrue(b["chain"]["n_failures"] >= 1)
        self.assertTrue(all(f["evidence_class"] == "BACKTEST" for f in b["forecasts"]))

    def test_forecast_archived_after_kickoff_is_blocked_not_frozen(self):
        make_store(self.root, written_at="2026-11-01T22:00:00Z")
        b = N.build(self.root, game_identity=GID)
        self.assertTrue(all(f["frozen_at"] == "2026-11-01T22:00:00Z" for f in b["forecasts"]))
        self.assertEqual(self.priced(self.grade(b))[0]["accuracy"]["reason"], "FORECAST_NOT_FROZEN_BEFORE_EVENT_START")

    # -- priced vs unpriced, universe
    def test_unlisted_rungs_are_unpriced_and_outside_the_eligible_universe(self):
        make_store(self.root)
        b = N.build(self.root, game_identity=GID)
        ids = {f["market_id"] for f in b["forecasts"] if f["scoring_type"] == "BINARY"}
        self.assertIn(TK, ids)
        self.assertIn(f"{GAME}|-200|points|ge10", ids)
        self.assertEqual({e["market_id"] for e in b["eligible"]}, {TK})
        cv = build_report(self.grade(b))["coverage"]
        self.assertEqual(cv["n_eligible_markets"], 1)
        self.assertEqual(cv["status_counts"], {"FORECAST_AND_GRADED": 1})
        self.assertGreater(cv["n_forecast_markets_outside_universe"], 0)

    def test_pre_quote_never_after_as_of(self):
        make_store(self.root)
        b = N.build(self.root, game_identity=GID)
        self.assertTrue(all(q["observed_at"] <= AS_OF for q in b["quotes"]))


if __name__ == "__main__":
    unittest.main()
