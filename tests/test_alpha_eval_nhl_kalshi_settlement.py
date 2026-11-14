"""Kalshi settlement as the second NHL outcome source (alpha_eval.nhl_kalshi_settlement): synthetic local fixtures only; no network.

Reconciled from PR #68's ``tests/test_alpha_eval_nhl_archive.py``. Its outcome, identity and confirmation-test cases are kept and
now run against the settlement module joined to PR #66's adapter (``alpha_eval.nhl_archive``); the new cases cover the per-market
cross-check of the official-API outcome against Kalshi's settlement. #68's forecast-selection, quote and universe-reconciliation
cases tested implementations that were NOT kept (the #66 ones are the single implementations and are covered by
``tests/test_alpha_eval_nhl_archive.py``); each is mapped below in ``RETIRED_PR68_CASES``."""
import gzip
import json
import os
import tempfile
import unittest
from collections import Counter

from alpha_eval import nhl_archive as H
from alpha_eval import nhl_kalshi_settlement as K
from alpha_eval.grading import grade_all
from alpha_eval.schema import BLOCKED, GRADED, R

START = "2026-11-10T00:00:00Z"
G = "2026020100"
T = "KXNHLGAME-26NOV09BOSLA-LA"

RETIRED_PR68_CASES = {  # #68 test -> where the same behaviour is tested on the reconciled branch
    "test_latest_attested_capture_wins_over_later_unattested": "nhl_archive.attest / select_forecasts (test_attestation_rules)",
    "test_unattested_only_is_blocked_not_frozen": "nhl_archive.attest demotes to BACKTEST (test_attestation_rules)",
    "test_capture_after_start_never_emitted": "nhl_archive.attest AFTER_START (test_attestation_rules)",
    "test_null_probability_is_counted_not_forecast": "nhl_archive.select_forecasts counts; market_not_forecast_reasons",
    "test_duplicate_file_add_keeps_earliest": "nhl_archive.parse_git_log: a file added twice fails attestation (test_attestation_rules)",
    "test_quotes_in_dollars_at_freeze_and_close": "nhl_archive.quotes_from_board (board replay) replaces embedded-capture quotes",
    "test_reconcile_partition_and_never_listed": "nba_universe.reconcile (tests/test_alpha_eval_nba_universe.py), reused by the NHL CLI",
}


def _sched(game=G, start=START, home="LAK", away="BOS", date="2026-11-09"):
    return dict(game_id=game, game_date_et=date, start_time_utc=start, home_abbrev=home, away_abbrev=away, status="final",
                _observed_at_utc="2026-11-09T12:00:00Z")


def _km(ticker, result="yes", series="KXNHLGAME"):
    return dict(ticker=ticker, event_ticker=ticker.rsplit("-", 1)[0], result=result, settlement_ts="2026-11-10T03:00:00Z", _series=series)


def _kalshi_dir(markets, series="KXNHLGAME"):
    d = tempfile.mkdtemp()
    with gzip.open(os.path.join(d, f"{series}_p0000.json.gz"), "wt") as f:
        json.dump(dict(markets=[{k: v for k, v in m.items() if k != "_series"} for m in markets], cursor=""), f)
    return d


def _official(ticker=T, value=1, state="final", event=G):
    return dict(schema="sift-alpha-eval/1", market_id=ticker, event_id=event, source="sports", observed_at="2026-11-10T07:00:00Z",
                state=state, value=value)


def _forecast(ticker=T, event=G, fam="game_winner"):
    return dict(schema="sift-alpha-eval/1", forecast_id="f|" + ticker, sport="NHL", event_id=event, market_id=ticker, model_id="m",
                model_version="v", model_independence="sports_only", frozen_at="2026-11-09T20:00:00Z", event_start=START,
                evidence_class="PROSPECTIVE", scoring_type="BINARY", payload=dict(p_yes=0.55), native_family=fam)


def _settle(markets, sched=None):
    kal = {m["ticker"]: m for m in markets}
    return K.settlement_rows(kal, {r["game_id"]: r for r in (sched or [_sched()])})


class TestLoaderAndIdentity(unittest.TestCase):
    def test_loader_reads_pages_and_keeps_later_settlement(self):
        d = _kalshi_dir([_km(T, "no")])
        with gzip.open(os.path.join(d, "KXNHLGAME_p0001.json.gz"), "wt") as f:
            json.dump(dict(markets=[dict(ticker=T, event_ticker=T.rsplit("-", 1)[0], result="yes", settlement_ts="2026-11-11T03:00:00Z")]), f)
        k = K.load_kalshi_settled(d)
        self.assertEqual((k[T]["result"], k[T]["_series"]), ("yes", "KXNHLGAME"))

    def test_kalshi_result_maps_with_alias_team_code(self):          # from #68 test_kalshi_result_grades_with_alias_team_code
        rows, ident, _ = _settle([_km(T)])
        self.assertEqual(dict(ident), {"OK": 1})
        self.assertEqual((rows[T]["event_id"], rows[T]["source"], rows[T]["state"], rows[T]["value"]), (G, "market_settlement", "final", 1))

    def test_unmatched_team_codes_are_counted_unmapped(self):          # from #68
        t = "KXNHLGAME-26NOV09ZZZQQQ-ZZZ"
        rows, ident, _ = _settle([_km(t)])
        self.assertEqual(dict(ident), {"TEAM_CODES_UNMATCHED": 1})
        self.assertTrue(rows[t]["event_id"].startswith("UNMAPPED:TEAM_CODES_UNMATCHED"))

    def test_scalar_settlement_is_void_and_non_game_series_is_skipped(self):   # from #68 test_scalar_settlement_is_void
        rows, _, info = _settle([_km(T, "scalar"), _km("KXNEXTTEAMNHL-26NOV09X-Y", "yes", series="KXNEXTTEAMNHL")])
        self.assertEqual((rows[T]["state"], rows[T]["value"]), ("void", None))
        self.assertEqual(info["kalshi.void_or_scalar.scalar"], 1); self.assertEqual(info["kalshi.non_game_series_markets"], 1)
        self.assertEqual(len(rows), 1)

    def test_confirmation_test_is_pinned(self):                          # from #68, unchanged
        self.assertEqual(K.PRIOR_AUDIT_DATA_PIN, "2026-11-04T19:38:30Z")
        self.assertEqual((K.CONFIRMATION_TEST["model_id"], K.CONFIRMATION_TEST["native_family"], K.CONFIRMATION_TEST["alpha"]),
                         ("PLAYER_SIM_V1", "goalie_saves", 0.05))


class TestCrossCheckOfficialVsKalshi(unittest.TestCase):
    def _grade(self, official, markets, sched=None, forecast=None):
        settle, _, _ = _settle(markets, sched)
        x = K.cross_check(official, settle)
        g = grade_all([forecast or _forecast()], official + x["rows"])
        return x, g["rows"][0]["accuracy"]

    def test_agreement_collapses_and_grades(self):
        x, acc = self._grade([_official(value=1)], [_km(T, "yes")])
        self.assertEqual(x["counts"], {"AGREE": 1}); self.assertEqual(acc["status"], GRADED)
        self.assertEqual(x["by_family"], {"game_winner": {"AGREE": 1}}); self.assertEqual(x["disagreements"], [])

    def test_value_disagreement_blocks_market_and_is_listed(self):       # the #68 "producer disagreement blocks" rule, now official vs Kalshi
        x, acc = self._grade([_official(value=1)], [_km(T, "no")])
        self.assertEqual(x["counts"], {"DISAGREE": 1})
        self.assertEqual((acc["status"], acc["reason"]), (BLOCKED, R.OUTCOME_CONFLICT))
        self.assertEqual(x["disagreements"][0], dict(market_id=T, category="DISAGREE", native_family="game_winner", official_value=1, kalshi_value=0))

    def test_void_against_final_blocks(self):
        x, acc = self._grade([_official(value=1)], [_km(T, "scalar")])
        self.assertEqual(x["counts"], {"OFFICIAL_FINAL_KALSHI_VOID": 1}); self.assertEqual(acc["status"], BLOCKED)
        x, acc = self._grade([_official(value=None, state="void")], [_km(T, "scalar")])
        self.assertEqual(x["counts"], {"AGREE_VOID": 1}); self.assertEqual(acc["reason"], "OUTCOME_VOID_OR_POSTPONED")

    def test_event_identity_disagreement_blocks(self):                   # from #68 test_identity_mismatch_blocks
        # official/producer side says the ticker belongs to game 2026020999; the ticker's date + teams resolve to G in the schedule
        sched = [_sched(), _sched(game="2026020999", date="2026-11-08", start="2026-11-09T00:00:00Z", home="NYR", away="NJD")]
        x, acc = self._grade([_official(event="2026020999")], [_km(T)], sched, _forecast(event="2026020999"))
        self.assertEqual(x["counts"], {"EVENT_IDENTITY_DISAGREE": 1}); self.assertEqual(acc["status"], BLOCKED)

    def test_shootout_ambiguous_market_stays_blocked_and_records_kalshi_side(self):
        off = [_official(value=1), _official(value=0)]                   # nhl_archive emits both rows for SO_AMBIGUOUS
        x, acc = self._grade(off, [_km(T, "yes")])
        self.assertEqual(x["counts"], {"OFFICIAL_AMBIGUOUS_KALSHI_YES": 1}); self.assertEqual(acc["reason"], R.OUTCOME_CONFLICT)

    def test_settlement_alone_never_grades_and_missing_settlement_is_counted(self):
        other = "KXNHLGAME-26NOV09BOSLA-BOS"
        x, acc = self._grade([_official(value=1)], [_km(other, "no")])
        self.assertEqual(x["counts"], {"KALSHI_ONLY_NO_OFFICIAL_ROW": 1, "NO_KALSHI_SETTLEMENT": 1})
        self.assertEqual(x["rows"], []); self.assertEqual(acc["status"], GRADED)     # graded on the official row; nothing appended

    def test_joined_to_the_pr66_adapter_outcome_rows(self):
        # official rows produced by #66's own outcome_rows (official API record agrees with the producer archive and settle engine)
        api = {G: dict(game=dict(start=START), res=dict(game_id=G, status="final", home_team_id=26, away_team_id=6, home_final=3, away_final=2,
                                                        last_period_type="REG"), goals=[], players={}, goalies={}, roster={}, fetched_at="2026-11-10T07:00:00Z")}
        c = dict(family="game_winner", team_id=26, threshold=0.0, comparator="gt")
        off = H.outcome_rows(T, c, G, api, None, "IDENTITY_VERIFIED", Counter())
        self.assertEqual([r["value"] for r in off], [1])
        b = dict(outcomes=list(off), info={})
        x = K.apply(b, {T: _km(T, "no")}, {G: _sched()})
        self.assertEqual(x["counts"], {"DISAGREE": 1}); self.assertEqual(len(b["outcomes"]), 2)
        self.assertEqual(b["info"]["kalshi_settlement"]["cross_check_vs_official"], {"DISAGREE": 1})
        self.assertEqual(b["info"]["kalshi_settlement"]["identity"], {"OK": 1})
        self.assertEqual(grade_all([_forecast()], b["outcomes"])["rows"][0]["accuracy"]["reason"], R.OUTCOME_CONFLICT)

    def test_secondary_native_family_slice_runs_and_is_never_a_promotion_input(self):
        sec = K.native_family_cells([], [])
        self.assertEqual(sec["cells"], []); self.assertEqual(sec["confirmation_test"]["result"], "NO_PAIRED_DATA")
        self.assertIn("not a promotion input", sec["note"]); self.assertIn("Pre-specified confirmation test", K.native_family_markdown(sec))

    def test_cli_accepts_optional_kalshi_dir(self):
        import inspect
        from alpha_eval import cli
        self.assertIsNone(inspect.signature(cli.run_nhl).parameters["kalshi_dir"].default)

    def test_no_duplicate_adapter_and_retired_cases_are_mapped(self):
        for dup in ("build", "reconcile", "load_file_adds", "load_contracts", "load_producer_settlements", "ARMS"):
            self.assertFalse(hasattr(K, dup), dup + " must live only in alpha_eval.nhl_archive / nba_universe")
        self.assertEqual(len(RETIRED_PR68_CASES), 7)
        for fn in ("attest", "select_forecasts", "parse_git_log", "quotes_from_board", "market_not_forecast_reasons"):
            self.assertTrue(hasattr(H, fn), fn)


if __name__ == "__main__":
    unittest.main()
