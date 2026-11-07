"""Offline tests: exact series ledger, rules-text classification, collectors' parsers, data-readiness model, and the ledgers of data actually collected."""
import collections
import json
import unittest
from pathlib import Path

from alpha_engine.collect import espn_scoreboard as ES, mlb_boxscores as MB, mlb_schedule as MS, nhl_boxscores as NB
from alpha_engine.input_research import data_readiness as DR, rules_classifier as RC, series_ledger as SL

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "research/input_research"
LEDGER = json.loads((IN / "market_universe/series_ledger.json").read_text())
READY = json.loads((IN / "data_readiness.json").read_text())
STATUSES = {"OUT_OF_SCOPE_SPORT", "EXCLUDED_TEST", "EXCLUDED_COMBO", "EXCLUDED_NONSPORT", "NO_LISTED_MARKETS", "COVERED_REGISTERED", "COVERED_UNREGISTERED", "CLASSIFIED_NO_ARCHETYPE", "UNCLASSIFIED"}


class ExactLedger(unittest.TestCase):
    def test_every_series_has_exactly_one_status_and_totals_reconcile(self):
        rows = LEDGER["rows"]
        self.assertEqual(len(rows), LEDGER["total_series"])
        self.assertEqual(len({r["ticker"] for r in rows}), len(rows), "duplicate series")
        self.assertTrue(all(r["status"] in STATUSES for r in rows))
        self.assertEqual(LEDGER["in_scope"] + LEDGER["out_of_scope"], LEDGER["total_series"])
        self.assertEqual(sum(v["total"] for v in LEDGER["by_sport"].values()), LEDGER["in_scope"])
        for s, v in LEDGER["by_sport"].items():
            self.assertEqual(v["total"], sum(n for k, n in v.items() if k != "total"), s)
            self.assertEqual(v["total"], sum(1 for r in rows if r["sport"] == s), s)

    def test_snapshot_total_matches_the_published_universe_summary(self):
        u = json.loads((IN / "market_universe/universe_summary.json").read_text())
        self.assertEqual(LEDGER["total_series"], u["n_series"])

    def test_exclusions_have_reasons_and_unresolved_are_few_and_explicit(self):
        for r in LEDGER["rows"]:
            if r["status"] in ("EXCLUDED_NONSPORT", "EXCLUDED_COMBO"):
                self.assertTrue(r.get("override_reason"), r["ticker"])
        unresolved = [r for r in LEDGER["rows"] if r["status"] in ("UNCLASSIFIED", "CLASSIFIED_NO_ARCHETYPE")]
        self.assertLessEqual(len(unresolved), 5, [r["ticker"] for r in unresolved])
        self.assertIn(set(r["evidence"] for r in LEDGER["rows"]), [{"RULES_TEXT", "NO_LISTING", "TITLE_ONLY"}])

    def test_no_listed_market_is_never_reported_as_covered(self):
        for r in LEDGER["rows"]:
            if r["evidence"] == "NO_LISTING" and r["sport"] in LEDGER["by_sport"]:
                self.assertIn(r["status"], ("NO_LISTED_MARKETS", "EXCLUDED_TEST"), r["ticker"])

    def test_the_nine_series_difference_is_the_explicitly_excluded_test_series(self):
        # The first accounting printed 2,358 covered + 193 unregistered-archetype + 212 "no archetype" = 2,763 of 2,772: its "no archetype" column was computed as total - covered - excluded and the
        # nine test/placeholder series (7 soccer, 2 tennis) were subtracted without being shown. The ledger shows every one of them.
        ex = [r for r in LEDGER["rows"] if r["status"] == "EXCLUDED_TEST"]
        self.assertEqual(len(ex), 9)
        self.assertEqual(collections.Counter(r["sport"] for r in ex), {"SOCCER": 7, "TENNIS": 2})

    def test_adjudication_count_equals_flag_count(self):
        a = json.loads((IN / "gap_adjudication.json").read_text())
        self.assertEqual(a["n_flags"], a["n_adjudications"])
        keys = [(x["sport"], x["archetype"], x["category"]) for x in a["adjudications"]]
        self.assertEqual(len(keys), len(set(keys)))


class RulesClassifier(unittest.TestCase):
    def test_real_contract_texts(self):
        c = lambda sp, t: RC.classify(sp, t)[0]
        self.assertEqual(c("SOCCER", "If Tie is the result of the Austin vs Portland professional MLS soccer game originally scheduled for Nov 7, 2026 after 90 minutes"), "soccer_game")
        self.assertEqual(c("SOCCER", "If Tottenham finishes in last place in the league table in the 2026-27 EPL season, then the market resolves to Yes."), "league_last")
        self.assertEqual(c("SOCCER", "If Venezia is the 2026-2027 Serie A champion, then the market resolves to Yes."), "outright_champion")
        self.assertEqual(c("CFB", "If West Virginia is ranked #1 on the College Football AP Poll Final Rankings"), "poll_rank")
        self.assertEqual(c("NFL", "If Trey McBride records at least 34 full-PPR fantasy points in any individual game"), "fantasy_points")
        self.assertEqual(c("SOCCER", "If Instituto Cordoba and Newell's Old Boys both score a goal in the match"), "soccer_btts")
        self.assertEqual(c("NFL", "If Over 56.5 points scored wins against Over 35.5 points scored, Over 35.5 points"), "combo_mve")

    def test_secondary_boilerplate_does_not_override_the_contract_definition(self):
        t, hit = RC.classify("SOCCER", "If Vasco da Gama is the 2026 CONMEBOL Sudamericana champion, then the market resolves to Yes.", "This contract concerns the American continent")
        self.assertEqual(t, "outright_champion")

    def test_override_never_replaces_a_title_based_archetype(self):
        over = json.loads((IN / "market_universe/classification_overrides.json").read_text())
        base = {r["ticker"]: r for r in SL.build(use_overrides=False)["rows"]}
        for t, o in over.items():
            if base[t]["status"].startswith("COVERED"):
                self.assertIn(o["type"], ("no_listed_market", "basketball_misassigned", "rules_review_correction"), t)


class CollectorParsers(unittest.TestCase):
    def test_mlb_schedule_row_extracts_lineups_umpire_weather_and_inning_runs(self):
        day = {"games": [{"gamePk": 1, "officialDate": "2025-06-01", "season": "2025", "gameNumber": 1, "doubleHeader": "N", "status": {"abstractGameState": "Final"}, "venue": {"id": 5}, "dayNight": "night",
                          "gameDate": "2025-06-02T00:00:00Z", "weather": {"condition": "Clear", "temp": "71", "wind": "5 mph"}, "officials": [{"officialType": "Home Plate", "official": {"id": 9}}],
                          "linescore": {"innings": [{"home": {"runs": 1}, "away": {"runs": 0}}, {"home": {"runs": 0}, "away": {"runs": 2}}]},
                          "lineups": {"homePlayers": [{"id": 11}, {"id": 12}], "awayPlayers": [{"id": 21}]},
                          "teams": {"home": {"team": {"id": 1}, "score": 1, "probablePitcher": {"id": 100}}, "away": {"team": {"id": 2}, "score": 2, "probablePitcher": {"id": 200}}}}]}
        r = list(MS.rows_from(day))[0]
        self.assertEqual((r["home_plate_ump_id"], r["home_sp_id"], r["innings_played"], r["temp"]), (9, 100, 2, 71))
        self.assertEqual(json.loads(r["home_lineup"]), [11, 12])

    def test_unfinished_games_are_skipped(self):
        self.assertEqual(list(MS.rows_from({"games": [{"status": {"abstractGameState": "Live"}}]})), [])

    def test_mlb_boxscore_player_rows(self):
        x = {"teams": {s: {"team": {"id": i}, "players": {"ID1": {"person": {"id": 7}, "position": {"abbreviation": "P"}, "stats": {"pitching": {"outs": 18, "numberOfPitches": 90, "earnedRuns": 2, "strikeOuts": 7, "gamesStarted": 1}}},
                                                         "ID2": {"person": {"id": 8}, "battingOrder": "300", "stats": {"batting": {"plateAppearances": 4, "hits": 2, "homeRuns": 1}}}, "ID3": {"person": {"id": 9}, "stats": {}}}}
                           for s, i in (("home", 1), ("away", 2))}}
        rows = MB.parse(55, x)
        self.assertEqual(len(rows), 4)
        self.assertEqual([r for r in rows if r["player_id"] == 7][0]["outs"], 18)
        self.assertEqual([r for r in rows if r["player_id"] == 8][0]["bat_order"], 300)

    def test_nhl_boxscore_parse_has_goalie_starter_and_final_only(self):
        x = {"id": 1, "gameState": "OFF", "gameType": 2, "season": 20242025, "gameDate": "2025-01-06", "startTimeUTC": "2025-01-07T00:00:00Z", "homeTeam": {"abbrev": "BUF", "score": 4, "sog": 30}, "awayTeam": {"abbrev": "WSH", "score": 3, "sog": 25},
             "gameOutcome": {"lastPeriodType": "SO"}, "venue": {"default": "KeyBank"},
             "playerByGameStats": {"homeTeam": {"forwards": [{"playerId": 1, "position": "C", "toi": "15:30", "sog": 4, "goals": 1}], "defense": [], "goalies": [{"playerId": 2, "toi": "60:00", "starter": True, "saves": 22, "shotsAgainst": 25}]},
                                   "awayTeam": {"forwards": [], "defense": [], "goalies": []}}}
        g, ps = NB.parse(x)
        self.assertEqual((g["home_goals"], g["last_period"]), (4, "SO"))
        self.assertAlmostEqual(ps[0]["toi"], 15.5)
        self.assertTrue([p for p in ps if p["pos"] is None or "starter" in p][0]["starter"])
        self.assertEqual(NB.parse({**x, "gameState": "LIVE"}), (None, []))

    def test_espn_scoreboard_never_reads_odds(self):
        ev = {"id": "1", "date": "2025-02-15T21:00Z", "status": {"type": {"completed": True}}, "competitions": [{"neutralSite": False, "odds": [{"details": "LAL -3"}], "competitors": [
              {"homeAway": "home", "team": {"id": "1", "displayName": "A"}, "score": "80", "linescores": [{"value": 40}, {"value": 40}]}, {"homeAway": "away", "team": {"id": "2", "displayName": "B"}, "score": "70", "linescores": [{"value": 30}, {"value": 40}]}]}]}
        r = ES.parse(ev, "CBB")
        self.assertEqual((r["home_score"], r["n_periods"]), (80, 2))
        self.assertFalse([k for k in r if "odds" in k or "line" in k.replace("linescore", "")])


class DataReadiness(unittest.TestCase):
    def test_grading_rules(self):
        hits = [("SCHEME_CHARTING", "coverage")]
        self.assertEqual(DR.grade("NFL", hits)[0], "AVAILABLE")                      # participation/FTN in hand
        self.assertEqual(DR.grade("NBA", hits)[0], "MISSING")                        # no play-type data found
        self.assertEqual(DR.grade("NHL", [("SCHEME_CHARTING", "shot")])[0], "PARTIAL")
        self.assertEqual(DR.grade("SOCCER", [("TEAM_BOX", "team")])[0], "AVAILABLE")
        self.assertEqual(DR.grade("NBA", [])[0], "UNMAPPED")

    def test_benchmark_only_inputs_are_excluded_never_counted(self):
        t = READY["totals"]
        self.assertEqual(t["AVAILABLE"] + t["PARTIAL"] + t["MISSING"] + t["UNMAPPED"] + t["EXCLUDED_BENCHMARK_ONLY"], t["inputs"])
        self.assertGreater(t["EXCLUDED_BENCHMARK_ONLY"], 0)
        self.assertEqual(t["UNMAPPED"], 0)

    def test_every_matrix_evidence_file_exists(self):
        for sp, row in DR.C.items():
            for cls, (lv, ev, note) in row.items():
                if ev:
                    self.assertTrue((IN / "data_collection" / ev).exists() or (IN / ev).exists(), (sp, cls, ev))

    def test_every_archetype_has_a_readiness_record(self):
        n = sum(len(json.loads((IN / f"catalog/{s}.json").read_text())["archetypes"]) + len(json.loads((IN / f"catalog/{s}.json").read_text()).get("unregistered_archetypes") or {}) for s in DR.SPORTS)
        self.assertEqual(len(READY["archetype_readiness"]), n)
        self.assertTrue(all(v["readiness"] in ("FULL", "EXPERIMENTABLE", "PARTIAL", "BLOCKED") for v in READY["archetype_readiness"].values()))

    def test_before_after_is_reported_with_both_yardsticks(self):
        b = READY["before_after"]
        self.assertEqual(b["before_inputs_with_measured_free_source"], 39)
        self.assertGreater(b["after_available_or_partial"], b["before_inputs_with_measured_free_source"])
        self.assertIn("Not the same yardstick", b["note"])


class CollectedDataLedgers(unittest.TestCase):
    def test_repo_archive_ledger_has_the_data_the_matrix_claims(self):
        d = json.loads((IN / "data_collection/repo_archives_ledger.json").read_text())["datasets"]
        self.assertGreater(d["nba_espn_player_games"]["rows"], 100000)
        self.assertEqual(d["nba_official_injury_report_rows"]["key_field_completeness"]["report_time_utc"], 1.0)    # true point-in-time vintages
        self.assertGreater(d["nhl_shots"]["rows"], 500000)
        self.assertGreater(d["tennis_atp_matches"]["key_field_completeness"]["w_ace"], 0.5)
        self.assertEqual(d["tennis_atp_matches"]["key_fields_absent"], [])

    def test_api_collector_ledgers_record_hash_and_timestamp_reliability(self):
        for f in (IN / "data_collection").glob("*_ledger.json"):
            if f.name == "repo_archives_ledger.json":
                continue
            L = json.loads(f.read_text())
            self.assertTrue(L.get("sha256") or L.get("cache_files"), f.name)
            self.assertIn("timestamp_reliability", L, f.name)
            self.assertGreater(L.get("games") or L.get("player_game_rows") or 0, 100, f.name)

    def test_cross_sport_search_runs_are_market_free_and_have_a_null(self):
        s = json.loads((ROOT / "research/audit/input_research/experiments/search_crosssport_v1.json").read_text())
        self.assertTrue(s["market_free"])
        for k, v in s["studies"].items():
            if "error" in v:
                continue
            self.assertTrue(v["permutation_null"], k)
            from alpha_engine.input_research import marketfree as MF
            MF.assert_market_free([c for g in v["groups"].values() for c in g])


if __name__ == "__main__":
    unittest.main()
