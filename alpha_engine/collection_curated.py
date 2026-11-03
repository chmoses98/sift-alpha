"""Curated, evidence-cited collection/model statuses. Anything not listed falls back to static code evidence
(CODE_REFERENCE_ONLY / NO_REFERENCE_FOUND) - never to 'collected'.

collection: PIT_ARCHIVED | COLLECTED_NOT_PIT_ARCHIVED | PARTIAL_OR_STALE | SOURCE_AVAILABLE_NOT_COLLECTED |
            NO_RELIABLE_SOURCE | DERIVED | UNKNOWN
model_use:  USED | USED_PARTIAL | RESEARCH_ONLY | COLLECTED_UNUSED | NOT_COLLECTED | UNKNOWN | NOT_APPLICABLE
evidence tokens: "doc:<REPO>/<path>" (repo doc at audited commit) or "arch:<REPO>:<branch>:<path-prefix>" (archive tree)."""
P, M, S, N, A, D, U = ("PIT_ARCHIVED", "COLLECTED_NOT_PIT_ARCHIVED", "PARTIAL_OR_STALE", "SOURCE_AVAILABLE_NOT_COLLECTED", "NO_RELIABLE_SOURCE", "DERIVED", "UNKNOWN")
USE, UP, RO, CU, NC, UK, NA = ("USED", "USED_PARTIAL", "RESEARCH_ONLY", "COLLECTED_UNUSED", "NOT_COLLECTED", "UNKNOWN", "NOT_APPLICABLE")
NFLDOC = "doc:nfl-edge-finder/docs/DATA_SOURCE_AUDIT.md"
CUR = {
"NFL": {
 "m.ladder_structure": (D, UK, "derived from archived quotes: nfl_edge/pricing/ladder.py (ladder semantics + monotonicity checks)", ["doc:nfl-edge-finder/nfl_edge/pricing/ladder.py"]),
 "m.volume_oi": (P, UK, "quotes.jsonl (2,646 records, observed_at 2026-11-02T23:54Z): volume_fp / open_interest_fp present on 100%, non-zero on 60.6% / 60.5% (real liquidity); every 10-min capture", ["arch:nfl-edge-finder:market-data:data/kalshi/capture", "doc:sift-alpha/research/audit/lineage/market_record_fields_extra.json"]),
 "m.lifecycle": (P, UK, "quotes.jsonl: status / open_time / close_time / expected_expiration_time populated on 100% of 2,646 records, stamped observed_at; state at each capture only (no separate halt/postponement events)", ["arch:nfl-edge-finder:market-data:data/kalshi/capture", "doc:sift-alpha/research/audit/lineage/market_record_fields_extra.json"]),
 "m.fees": (M, UK, "fee_type / fee_multiplier per series in config/kalshi_nfl_series.json (392 series, static catalog, not time-stamped or vintage-archived)", ["doc:nfl-edge-finder/config/kalshi_nfl_series.json"]),
 "nfl.skill_avail": (S, USE, "pit_availability: espn_event_rosters / espn_injuries non-empty in only 25% of sampled files", ["arch:nfl-edge-finder:market-data:data/pit_availability", "doc:sift-alpha/research/audit/lineage/field_evidence.json"]),
 "m.rules_text": (S, UK, "latest open-set carries tickers only (0/161 series with rules text); settlement semantics hand-encoded in semantics/catalog.py", ["arch:nfl-edge-finder:market-data:data/kalshi", "doc:nfl-edge-finder/nfl_edge/semantics/catalog.py"]),
 "m.quote_history": (P, USE, "10-min conductor: quotes/books/trades/openset per run, 83,328 files 2026-09-04..2026-11-02 on market-data", ["arch:nfl-edge-finder:market-data:data/kalshi"]),
 "m.orderbook_depth": (P, UK, "books.jsonl captured every run", ["arch:nfl-edge-finder:market-data:data/kalshi"]),
 "m.settlement_truth": (P, USE, "settlements/outcomes archived since 2026-10-18; semantics catalog (100 family/period entries) hand-encoded", ["arch:nfl-edge-finder:projection-data:settlements/nfl", "doc:nfl-edge-finder/nfl_edge/semantics/catalog.py"]),
 "nfl.injuries_pit": (P, USE, "pit_availability 370 files 2026-10-13..11-02 + content-addressed vintage index; nflverse 2026 injury file was unpublished at audit time", ["arch:nfl-edge-finder:market-data:data/pit_availability", NFLDOC]),
 "nfl.depth_chart_pit": (S, USE, "pit_availability snapshots (370 files, retrieved_at on sampled records) carry nflverse_depth_charts non-empty in only 25% of sampled files", ["arch:nfl-edge-finder:market-data:data/pit_availability", "doc:sift-alpha/research/audit/lineage/field_evidence.json"]),
 "nfl.weather_pit": (M, CU, "Open-Meteo vintages retrieved; author states weather never alters a simulated probability", ["doc:nfl-edge-finder/nfl_edge/sim/weather_research.py"]),
 "nfl.off_epa": (M, UP, "nflverse pbp bronze (local, gitignored, rebuildable); features strictly-prior; game markets are market-centred so team-total/spread/total do not use it", [NFLDOC, "doc:nfl-edge-finder/nfl_edge/sim/prospective.py"]),
 "nfl.def_epa": (M, UP, "as off_epa", [NFLDOC]), "nfl.success_rate": (M, UP, "team features", ["doc:nfl-edge-finder/nfl_edge/sim/features.py"]),
 "nfl.pace": (M, UP, "plays model feeds player volume only", ["doc:nfl-edge-finder/nfl_edge/sim/features.py"]),
 "nfl.proe": (M, UP, "pass-rate model feeds player volume only", ["doc:nfl-edge-finder/nfl_edge/sim/features.py"]),
 "nfl.drives": (M, UP, "drives/td_per_drive in team features; not an input to team points", ["doc:nfl-edge-finder/nfl_edge/sim/features.py"]),
 "nfl.redzone": (M, UP, "rz_trips feature", ["doc:nfl-edge-finder/nfl_edge/sim/features.py"]),
 "nfl.qb": (M, UP, "qb_regimes.py; effect on game markets only via the market centre", ["doc:nfl-edge-finder/nfl_edge/sim/qb_regimes.py"]),
 "nfl.ol": (M, RO, "OL snap features for rushing only", ["doc:nfl-edge-finder/nfl_edge/sim/rushing.py"]),
 "nfl.snaps": (M, UP, "snap_counts downloaded 2012+; role features", [NFLDOC]), "nfl.routes": (M, RO, "pbp_participation downloaded 2016-2025; route features research-only", [NFLDOC]),
 "nfl.targets": (M, UP, "share model", ["doc:nfl-edge-finder/nfl_edge/sim/models.py"]), "nfl.carries": (M, UP, "share model", ["doc:nfl-edge-finder/nfl_edge/sim/models.py"]),
 "nfl.ngs": (M, RO, "nextgen_stats downloaded; research modules only", [NFLDOC]), "nfl.formation": (M, RO, "ftn_charting 2022-2025 downloaded; research only", [NFLDOC]),
 "nfl.score_resid": (D, USE, "ResidualBank, OOS reliability slope 1.01 (author-reported, 2016-2025)", ["doc:nfl-edge-finder/research/game_env/RESULTS.md"]),
 "nfl.ot_model": (D, USE, "OT/tie model; known 1-6 margin bucket under-prediction", ["doc:nfl-edge-finder/research/game_env/RESULTS.md"]),
 "nfl.script": (D, RO, "script lattice is RESEARCH_ONLY", ["doc:nfl-edge-finder/nfl_edge/sim/script_v2.py"]),
 "nfl.penalties": (M, UK, "officials.parquet downloaded 2015-2025; use unverified", [NFLDOC]),
 "nfl.news": (S, USE, "Sleeper supplement for availability", ["doc:nfl-edge-finder/nfl_edge/sim/prospective.py"]),
 "nfl.venue": (M, UK, "config/stadiums.json static", ["doc:nfl-edge-finder/config/stadiums.json"]),
},
"CFB": {
 "cfb.qb": (S, UK, "starter rows (1,040) are inferred from the prior game\u0027s passer (pf_cfb_prior_game_passer), status STARTING, not an announcement; 404 entities", ["arch:cfb-edge-finder:projection-data:availability/cfb", "doc:sift-alpha/research/audit/lineage/historical_archive_gaps.json"]),
 "m.rules_text": (M, UK, "rules_primary present on 18/19 catalog families; git-versioned on main, no dated archive branch", ["doc:cfb-edge-finder/data/live/cfb_market_catalog.json"]),
 "m.quote_history": (S, UK, "Quote history lives as git-versioned per-game shards on main (data/live/execution 1,306 files); no dedicated timestamped archive branch found in scanned branches", ["doc:cfb-edge-finder/data/live/cfb_market_catalog.json"]),
 "m.lifecycle": (S, UK, "research-signals capture/2026/quotes.jsonl (4,420 records): status + kickoff_utc + captured_at on 100%, but no close/expiration time, volume, open interest or order book in this capture", ["arch:cfb-edge-finder:research-signals:capture", "doc:sift-alpha/research/audit/lineage/market_record_fields_extra.json"]),
 "m.settlement_truth": (P, USE, "settlements/outcomes on projection-data 2026-10-20..10-31", ["arch:cfb-edge-finder:projection-data:settlements/cfb"]),
 "cfb.injuries": (S, UK, "availability/cfb: 3,085 records / 12 files / 404 entities, but only 35 are injury rows (ESPN core injuries, 1.1%); the rest are 2,010 roster and 1,040 starter rows (starter = prior-game passer inference with a source time). Not a usable injury feed", ["arch:cfb-edge-finder:projection-data:availability/cfb", "doc:sift-alpha/research/audit/lineage/historical_archive_gaps.json"]),
 "cfb.off_ppa": (U, UK, "CFBD /ppa primary; CFBD quota-recovery branch exists (quota risk)", ["doc:cfb-edge-finder/docs/DATA_SOURCES.md"]),
 "cfb.depth_chart": (U, UK, "ESPN hidden depth-chart endpoint; fragile", ["doc:cfb-edge-finder/docs/DATA_SOURCES.md"]),
 "cfb.weather_pit": (U, UK, "NWS forecast primary; Visual Crossing historical; v2_games_for_weather.csv research input only", ["doc:cfb-edge-finder/docs/DATA_SOURCES.md"]),
 "cfb.transfer_roster": (N, UK, "CFBD talent/portal endpoints identified; On3/247 need licence", ["doc:cfb-edge-finder/docs/DATA_SOURCES.md"]),
 "cfb.opening_poss": (U, UK, "Only one market shard (KXNCAAF1QTOTAL AUBMISS) pinned by Alpha so far", []),
},
"NBA": {
 "m.fees": (M, UK, "fee_type / fee_multiplier per series in data/catalog/discovery_summary.json (static catalog, not vintage-archived)", ["doc:nba-edge-finder/data/catalog/discovery_summary.json"]),
 "m.volume_oi": (P, UK, "open_interest_fp / volume_fp present on every record (non-zero on 25% of active markets = real liquidity), batch-stamped", ["arch:nba-edge-finder:data-archive:kalshi/markets", "doc:sift-alpha/research/audit/lineage/market_record_fields.json"]),
 "m.lifecycle": (P, UK, "close_time / expiration_time / status populated on 100% of records; state at each snapshot only (no separate lifecycle events)", ["arch:nba-edge-finder:data-archive:kalshi/markets", "doc:sift-alpha/research/audit/lineage/market_record_fields.json"]),
 "nba.matchup_def": (N, NC, "ROOT CAUSE (code): shadow.py sets exposures=() and home/away_scheme=None (\"no defensive-assignment source is reachable\", \"no scheme-proxy source ingested yet\")", ["doc:nba-edge-finder/src/nba_edge/matchup/shadow.py", "doc:sift-alpha/research/audit/lineage/field_evidence.json"]),
 "nba.venue": (P, UK, "schedule: arena + neutral_site populated on 100% of sampled records", ["arch:nba-edge-finder:data-archive:context/schedule", "doc:sift-alpha/research/audit/lineage/field_evidence.json"]),
 "nba.rotation": (N, NC, "CORRECTION: matchup/shadow.py fills expected_*_rotation with the FULL captured roster (provenance: \"NOT a projected rotation; no minutes model is consulted\"), so the 376/376 populated rate is not a rotation signal", ["doc:nba-edge-finder/src/nba_edge/matchup/shadow.py", "doc:sift-alpha/research/audit/lineage/field_evidence.json"]),
 "m.rules_text": (P, UK, "rules_primary present on 133/133 series in the latest archived full snapshot", ["arch:nba-edge-finder:data-archive:kalshi/markets_delta"]),
 "m.quote_history": (P, USE, "kalshi/markets (161 full) + markets_delta (3,165) on data-archive; full snapshots from 2026-09-18 (41 daily snapshots, 5 calendar days without one); one batch stamp per snapshot, 39 rows updated up to 80 s after the stamp (integrity/timestamp_integrity.json)", ["arch:nba-edge-finder:data-archive:kalshi/markets_delta"]),
 "m.orderbook_depth": (P, UK, "kalshi/orderbooks + orderbooks_delta", ["arch:nba-edge-finder:data-archive:kalshi/orderbooks_delta"]),
 "m.settlement_truth": (P, USE, "scorecards/outcomes on projection-data", ["arch:nba-edge-finder:projection-data:scorecards/nba"]),
 "nba.injuries_pit": (P, USE, "injury_pit official 69 files (10-19..11-01) + espn 108 files (10-12..11-01); context/injuries 518 files", ["arch:nba-edge-finder:data-injury-pit:injury_pit", "arch:nba-edge-finder:data-archive:context/injuries"]),
 "nba.starters_pit": (N, NC, "ROOT CAUSE (code): matchup/shadow.py deliberately sets expected_*_starters=() and lineup_confidence=UNKNOWN because \"no source reports expected starters today\"; 0 of 376 sampled records populated [Repair drafted, unverified in production: nba-edge-finder PR #87 captures ESPN starter flags before tip into context/starters; status stays MISSING until archived rows show CONFIRMED captures. Overnight 2026-11-03: unit tests pass (full suite) and context cadence in PR #87 was found too slow (55 min vs starters flagged ~19 min pre-tip); added a 6-min refresh inside 40 min of tip (commit 5fc63c3). ESPN is unreachable from the authoring sandbox, so live-runner coverage by lead time is still unmeasured.]", ["doc:nba-edge-finder/src/nba_edge/matchup/shadow.py", "doc:sift-alpha/research/audit/lineage/field_evidence.json"]),
 "nba.minutes": (P, USE, "minutes-shadow-archive: eligibility (59), jrm_v2_uniform (50)", ["arch:nba-edge-finder:minutes-shadow-archive:eligibility"]),
 "nba.tracking": (A, NC, "stats.nba.com times out from Actions; NBA CDN 403", ["doc:nba-edge-finder/docs/NBA_DATA_SOURCE_AUDIT.md"]),
 "nba.pot_ast": (A, NC, "Potential assists only on stats.nba.com tracking (blocked from Actions)", ["doc:nba-edge-finder/docs/NBA_DATA_SOURCE_AUDIT.md"]),
 "nba.onoff": (N, UK, "pbpstats API reachable (research candidate); not ingested as production", ["doc:nba-edge-finder/docs/NBA_DATA_SOURCE_AUDIT.md"]),
 "nba.shot_profile": (S, UK, "shot-ingest/shot-profile branches exist; coverage not verified", ["doc:nba-edge-finder/docs/NBA_DATA_SOURCE_AUDIT.md"]),
 "m.external_lines": (A, NC, "The Odds API needs key (free 500 req/month); never fabricated", ["doc:nba-edge-finder/docs/NBA_DATA_SOURCE_AUDIT.md"]),
 "nba.rest_travel": (P, UK, "context/schedule 518 files", ["arch:nba-edge-finder:data-archive:context/schedule"]),
},
"CBB": {
 "cbb.four_factors": (P, USE, "every archived pregame projection (363 files in pure-0.5.0, generated 2026-11-01..02) carries the ratings block with eFG/TO/ORB/FT-rate offence and defence, stamped by generated_at and freshness.info_cutoff_utc; derived from box scores, so this verifies archival of the ratings actually used, not the raw history", ["arch:cbb-edge-finder:projections-archive:projections/pure-0.5.0", "doc:sift-alpha/research/audit/lineage/cbb_projection_fields.json"]),
 "cbb.tempo": (P, USE, "every archived pregame projection (363 files in pure-0.5.0, generated 2026-11-01..02) carries the ratings block with adj_tempo, stamped by generated_at and freshness.info_cutoff_utc; derived from box scores, so this verifies archival of the ratings actually used, not the raw history", ["arch:cbb-edge-finder:projections-archive:projections/pure-0.5.0", "doc:sift-alpha/research/audit/lineage/cbb_projection_fields.json"]),
 "cbb.adj_def": (P, USE, "every archived pregame projection (363 files in pure-0.5.0, generated 2026-11-01..02) carries the ratings block with adj_def, stamped by generated_at and freshness.info_cutoff_utc; derived from box scores, so this verifies archival of the ratings actually used, not the raw history", ["arch:cbb-edge-finder:projections-archive:projections/pure-0.5.0", "doc:sift-alpha/research/audit/lineage/cbb_projection_fields.json"]),
 "m.volume_oi": (P, UK, "open_interest_fp / volume_fp present on every record (non-zero on ~12% of active markets = real liquidity), batch-stamped", ["arch:cbb-edge-finder:kalshi-archive:snapshots", "doc:sift-alpha/research/audit/lineage/market_record_fields.json"]),
 "m.lifecycle": (P, UK, "close_time / expiration_time / status populated on 100% of records; state at each snapshot only (no separate lifecycle events)", ["arch:cbb-edge-finder:kalshi-archive:snapshots", "doc:sift-alpha/research/audit/lineage/market_record_fields.json"]),
 "m.rules_text": (P, UK, "rules_primary present on 77/77 series in the latest archived snapshot", ["arch:cbb-edge-finder:kalshi-archive:snapshots"]),
 "m.quote_history": (P, USE, "kalshi-archive snapshots, 196 files 2026-10-05..11-02 (includes orderbook per record); 60 rows updated up to 70 s after the batch stamp (integrity/timestamp_integrity.json)", ["arch:cbb-edge-finder:kalshi-archive:snapshots"]),
 "m.external_lines": (S, UK, "ESPN pickcenter lines harvested 2018-2023 + 2026 (open+close in 2026); espn-lines-archive branch", ["doc:cbb-edge-finder/docs/DATA_SOURCE_AUDIT.md", "arch:cbb-edge-finder:espn-lines-archive:snapshots"]),
 "cbb.injuries": (S, UK, "CORRECTION: availability-archive rows have the injury fields but injury_status / injury_date are populated on 0 of 13,005 rows read (last 4 capture files); roster_status and native_status are 100%. Pregame checkpoints are T-24h 79%, T-6h 21%, T-90m 0.6% of rows", ["arch:cbb-edge-finder:availability-archive:captures"]),
 "cbb.roster_minutes": (P, UK, "roster-archive 1,159 files incl. official pages", ["arch:cbb-edge-finder:roster-archive:official"]),
 "cbb.lineups": (M, CU, "ncaa-mbb-hoops lineups/stints/possessions ingested 2010-2026; 'not yet modeled'", ["doc:cbb-edge-finder/docs/DATA_SOURCE_AUDIT.md"]),
 "cbb.adj_off": (P, USE, "every archived pregame projection (363 files in pure-0.5.0, generated 2026-11-01..02) carries the ratings block with adj_off, stamped by generated_at and freshness.info_cutoff_utc; derived from box scores, so this verifies archival of the ratings actually used, not the raw history", ["arch:cbb-edge-finder:projections-archive:projections/pure-0.5.0", "doc:sift-alpha/research/audit/lineage/cbb_projection_fields.json"]),
 "cbb.ratings": (A, NC, "Bart Torvik 403 from Actions; KenPom paid", ["doc:cbb-edge-finder/docs/DATA_SOURCE_AUDIT.md"]),
 "cbb.shot_zones": (N, CU, "shots 1.8 GB not downloaded; PBP shot coordinates sparse before 2025", ["doc:cbb-edge-finder/docs/DATA_SOURCE_AUDIT.md"]),
 "cbb.recruit_exp": (P, UK, "availability-archive captures (9 files 2026-10-05..11-02) carry class and class_years on 98.4%, height_in 96.8%, weight 83.6% of 13,005 rows read (last 4 files), with captured_at and checkpoint (T-24h/T-6h/T-90m)", ["arch:cbb-edge-finder:availability-archive:captures"]),
 "cbb.rest_travel": (P, UK, "schedule-archive obs/rows 59 files 2026-10-06..11-01", ["arch:cbb-edge-finder:schedule-archive:obs"]),
},
"NHL": {
 "nhl.pp_role": (P, UK, "context/lines carries power-play / penalty-kill unit membership per player (category pp/pk, unit pp1/pp2/pk1/pk2; e.g. 40 pp1 + 40 pp2 rows in one capture) with lines_updated_at_utc and record observed_at_utc; unit membership only, not PP time share", ["arch:NHL-edge-finder:data-archive:context/lines", "doc:sift-alpha/research/audit/lineage/context_probe.json"]),
 "m.fees": (M, UK, "fee_type (incl. quadratic_with_maker_fees) / fee_multiplier per series in data/catalog/discovery_summary.json (static catalog)", ["doc:NHL-edge-finder/data/catalog/discovery_summary.json"]),
 "m.orderbook_depth": (P, UK, "kalshi/orderbooks_delta 2,449 files 2026-09-30..2026-11-01 on data-archive (archive-tree listing; per-level depth fields not field-checked)", ["arch:NHL-edge-finder:data-archive:kalshi/orderbooks_delta"]),
 "m.volume_oi": (P, UK, "open_interest_fp / volume_fp present on every record (non-zero on ~40% of active markets = real liquidity), batch-stamped", ["arch:NHL-edge-finder:data-archive:kalshi/markets", "doc:sift-alpha/research/audit/lineage/market_record_fields.json"]),
 "m.lifecycle": (P, UK, "close_time / expiration_time / status populated on 100% of records; state at each snapshot only (no separate lifecycle events)", ["arch:NHL-edge-finder:data-archive:kalshi/markets", "doc:sift-alpha/research/audit/lineage/market_record_fields.json"]),
 "nhl.venue": (P, UK, "schedule: venue + neutral_site populated on 100% of sampled records", ["arch:NHL-edge-finder:data-archive:context/schedule", "doc:sift-alpha/research/audit/lineage/field_evidence.json"]),
 "nhl.opp_supp": (P, UK, "team_summary: goalsAgainstPerGame populated on 100% of sampled records", ["arch:NHL-edge-finder:data-archive:context/team_summary", "doc:sift-alpha/research/audit/lineage/field_evidence.json"]),
 "nhl.xg_against": (P, UK, "team_games: xGoalsPercentage populated on 100% of sampled records", ["arch:NHL-edge-finder:data-archive:context/team_games", "doc:sift-alpha/research/audit/lineage/field_evidence.json"]),
 "nhl.pace": (P, UK, "team_games: corsi/fenwick % populated on 100% of sampled records, record-level _observed_at_utc", ["arch:NHL-edge-finder:data-archive:context/team_games", "doc:sift-alpha/research/audit/lineage/field_evidence.json"]),
 "nhl.rest_travel": (P, UK, "context/schedule 697 files with start_time_utc; rest/back-to-back derived downstream", ["arch:NHL-edge-finder:data-archive:context/schedule", "doc:sift-alpha/research/audit/lineage/context_probe.json"]),
 "nhl.goalie_quality": (P, UK, "context/goalie_stats 691 files 2026-09-29..11-02 (NHL stats REST), batch-stamped", ["arch:NHL-edge-finder:data-archive:context/goalie_stats", "doc:sift-alpha/research/audit/lineage/context_probe.json"]),
 "m.rules_text": (P, UK, "rules_primary present on 46/46 series in the latest archived full snapshot", ["arch:NHL-edge-finder:data-archive:kalshi/markets_delta"]),
 "m.quote_history": (P, USE, "kalshi markets_delta (2,567) + orderbooks_delta (2,449) since 2026-09-30", ["arch:NHL-edge-finder:data-archive:kalshi/markets_delta"]),
 "m.settlement_truth": (P, USE, "outcomes/settlements on projection-data", ["arch:NHL-edge-finder:projection-data:scorecards/nhl"]),
 "nhl.goalie_start": (P, UK, "goalie_observations 771 files; source_reported_at_utc is present on exactly the confirmed DailyFaceoff rows (300/728, confidence 0.85-0.985) and absent on the 428 unconfirmed rows (confidence 0.70) by construction - not a defect, but confirmation-time analysis is valid only on confirmed rows; 4 post-game boxscore rows. Record time later than batch stamp: NHL-edge-finder PR #111", ["arch:NHL-edge-finder:data-archive:context/goalie_observations", "doc:sift-alpha/research/audit/lineage/field_evidence.json"]),
 "nhl.injuries_pit": (P, UK, "context/injuries 689 files (ESPN, optional enrichment)", ["arch:NHL-edge-finder:data-archive:context/injuries"]),
 "nhl.lines": (P, UK, "context/lines 670 files 2026-09-30..11-02; every record has observed_at_utc + lines_updated_at_utc (median source age ~6 h) but the file batch stamp precedes the record time by up to 29 s - use the record-level time", ["arch:NHL-edge-finder:data-archive:context/lines", "doc:sift-alpha/research/audit/integrity/record_vs_batch_timing.json"]),
 "nhl.toi": (P, UK, "player-minutes-data coverage/incumbent 2026-10-24..11-01", ["arch:NHL-edge-finder:player-minutes-data:coverage"]),
 "nhl.xg_for": (P, UK, "context/team_games 690 files carry MoneyPuck xG/Corsi/Fenwick per team-game, batch-stamped; shot-level xG still not ingested", ["arch:NHL-edge-finder:data-archive:context/team_games", "doc:sift-alpha/research/audit/lineage/context_probe.json"]),
 "nhl.shot_rate": (N, UK, "MoneyPuck skaters/shot-level available; shots-pull branches exist", ["doc:NHL-edge-finder/docs/NHL_DATA_SOURCE_AUDIT.md"]),
 "nhl.special_teams": (P, UK, "context/team_summary 697 files (PP, PK, GF/GA), batch-stamped", ["arch:NHL-edge-finder:data-archive:context/team_summary", "doc:sift-alpha/research/audit/lineage/context_probe.json"]),
},
"MLB": {
 "m.ladder_structure": (D, UK, "documented ladder semantics (docs/EDGELAB_KALSHI_TOTAL_LADDER_SEMANTICS.md); derived from quotes", ["doc:edge-finder-api/docs/EDGELAB_KALSHI_TOTAL_LADDER_SEMANTICS.md"]),
 "m.settlement_truth": (M, UK, "data/edgelab/settlements: 90 daily files 2026-08-02+, jsonl.gz on main; per-record timestamps not checked", ["doc:edge-finder-api/data/edgelab/settlements"]),
 "m.volume_oi": (U, UK, "verified gap in the only MLB market file checked: data/edgelab/markets is a contract registry (328 records 2026-10-28) with no price, volume or open-interest field; files 2026-10-29..11-02 are empty. No MLB volume/OI archive located yet", ["doc:edge-finder-api/data/edgelab/markets", "doc:sift-alpha/research/audit/lineage/market_record_fields_extra.json"]),
 "mlb.injuries_pit": (S, UK, "availability/mlb 35 files 2026-10-18..10-28 with captured_utc but 0 of 84 sampled records carry a source timestamp", ["arch:edge-finder-api:projection-data:availability/mlb", "doc:sift-alpha/research/audit/integrity/record_vs_batch_timing.json"]),
 "m.rules_text": (S, UK, "daily discovery contracts carry no rules text (0/15 families)", ["doc:edge-finder-api/data/kalshi/discovery/2026-10-28.json"]),
 "m.quote_history": (P, USE, "data/kalshi_registry_snapshots 582 files 2026-06-08..11-01; discovery daily; only 13 of 215 MLB series had counts enumerated on 2026-10-28", ["arch:edge-finder-api:main:data/kalshi_registry_snapshots", "doc:edge-finder-api/data/kalshi/discovery/2026-10-28_series_catalogue.json"]),
 "mlb.pitch_mix": (P, UK, "data/statcast_raw 643 files", ["arch:edge-finder-api:main:data/statcast_raw"]),
 "mlb.lineup_pit": (P, USE, "lineup_audit daily csv/json + lineup recheck workflow", ["doc:edge-finder-api/docs/EDGELAB_LINEUP_HITTER_FEASIBILITY_AUDIT.md"]),
 "mlb.bullpen": (M, USE, "data/bullpen.json (overwritten working copy) + bullpen workload branches", ["doc:edge-finder-api/docs/MODEL_V2_ARCHITECTURE.md"]),
 "mlb.weather_pit": (M, UK, "data/weather.json working copy", ["doc:edge-finder-api/docs/SOURCE_OF_TRUTH_MAP.md"]),
 "mlb.park": (M, USE, "data/park_geometry.json static", ["doc:edge-finder-api/data/park_geometry.json"]),
 "mlb.run_dist": (D, USE, "negative-binomial run distribution shadow research", ["doc:edge-finder-api/docs/EDGELAB_MLB_RSCH_0033_TEAM_RUN_MEAN_AUDIT.md"]),
},
"SOCCER": {
 "m.settlement_truth": (P, UK, "settlements/ 31 daily files 2026-09-28..11-02 and results/ on data-archive; per-record timestamp field not checked", ["arch:soccer-edge-finder:data-archive:settlements"]),
 "m.fees": (P, UK, "fee_type / fee_multiplier are fields of every archived capture record (data-archive snapshots/cap-*.jsonl), timestamped by captured_at", ["arch:soccer-edge-finder:data-archive:snapshots"]),
 "m.lifecycle": (P, UK, "capture snapshot (715 records, 2026-11-03): status / close_time / expected_expiration_time / captured_at populated on 100%; state at each snapshot only (no separate halt/postponement events)", ["arch:soccer-edge-finder:data-archive:snapshots", "doc:sift-alpha/research/audit/lineage/soccer_archive_and_espn_probe_evidence.json"]),
 "soc.market_odds": (S, UK, "odds_api/raw 442 files 2026-09-29..2026-11-02: Pinnacle h2h + spreads + totals per event with meta.requested_at; free-tier budget, kickoff-dispatch sampling (not continuous closing/live coverage)", ["arch:soccer-edge-finder:data-archive:odds_api", "doc:sift-alpha/research/audit/lineage/soccer_archive_and_espn_probe_evidence.json"]),
 "soc.score_state": (N, NC, "results card slots 0 of 5,729 populated (re-measured). ESPN probe run 41543056159: box score reports yellowCards/redCards for both teams in 8/8 matches; scoreboard-details cards differed from the box score in 2/8 (+1), so PR #39 marks them cards_basis=scoreboard_unreconciled and box-score cards boxscore_exact", ["arch:soccer-edge-finder:data-archive:results", "doc:sift-alpha/research/audit/lineage/field_evidence.json"]),
 "soc.set_pieces": (N, NC, "results corners slots 0 of 5,729 populated. Source verified: ESPN summary box score `wonCorners` present for both teams in 8/8 probed matches (run 41543056159); wired in soccer-edge-finder PR #39 (draft), not yet archived", ["arch:soccer-edge-finder:data-archive:results", "doc:sift-alpha/research/audit/lineage/field_evidence.json"]),
 "soc.pace_press": (N, NC, "results shots / shots_on_target slots 0 of 5,729 populated. Source verified: ESPN box score `totalShots` and `shotsOnTarget` present for both teams in 8/8 probed matches (run 41543056159); wired in soccer-edge-finder PR #39 (draft), not yet archived", ["arch:soccer-edge-finder:data-archive:results", "doc:sift-alpha/research/audit/lineage/field_evidence.json"]),
 "soc.rest_travel": (P, UK, "fixtures/ 1,184 files 2026-09-28..11-02 with as_of and kickoff_utc (rest derived downstream)", ["arch:soccer-edge-finder:data-archive:fixtures", "doc:sift-alpha/research/audit/lineage/context_probe.json"]),
 "m.quote_history": (P, USE, "snapshots/cap-*.jsonl every ~15 min since 2026-10-03 on data-archive", ["arch:soccer-edge-finder:data-archive:snapshots"]),
 "m.rules_text": (P, UK, "capture records carry rules_primary_hash (sha256) so settlement-text versions are detectable; full text not in the capture", ["arch:soccer-edge-finder:data-archive:snapshots"]),
 "m.external_lines": (S, USE, "odds_api/raw since 2026-09-29 (free tier 500 req/month); football-data.co.uk historical closing odds", ["arch:soccer-edge-finder:data-archive:odds_api", "doc:soccer-edge-finder/docs/DATA_SOURCE_AUDIT.md"]),
 "soc.lineups_pit": (P, UK, "764 lineup files 2026-09-28..11-02 (51 competitions); of 1,971 tracked fixtures only 28.3% had a pre-kickoff XI archived and 21.1% >= 20 min ahead (repo's own lead-time evaluation). Earlier doc saying LineupProvider is not wired is superseded by the archive; whether models read it is unverified", ["arch:soccer-edge-finder:data-archive:lineups", "doc:sift-alpha/research/audit/lineage/soccer_context_lineage.json"]),
 "soc.injuries": (N, NC, "no injury path in the data-archive tree (verified); InjuryProvider not wired", ["arch:soccer-edge-finder:data-archive:lineups", "doc:sift-alpha/research/audit/lineage/soccer_context_lineage.json"]),
 "soc.shots": (N, UK, "ESPN summary box score carries totalShots and shotsOnTarget for BOTH teams in 8/8 sampled matches (eng.1, esp.1, ger.1, ita.1; probe run 41543056159). Post-match statistic: usable only as a lagged historical rate, never for the same match. Archival wired in soccer-edge-finder PR #39 (unmerged, not yet verified on a runner); no archived records yet", ["doc:sift-alpha/research/audit/lineage/soccer_archive_and_espn_probe_evidence.json"]),
 "soc.corners": (N, UK, "ESPN box score statistic wonCorners present for both teams in 8/8 sampled matches (probe run 41543056159). Post-match only; wiring in soccer-edge-finder PR #39 (unmerged); no archived records yet. No Kalshi corners family observed in the 48 ambiguous series examined", ["doc:sift-alpha/research/audit/lineage/soccer_archive_and_espn_probe_evidence.json"]),
 "soc.fouls_cards": (N, UK, "ESPN box score has yellowCards, redCards (both teams 8/8) and foulsCommitted (seen); referee identity NOT in the box score (referee_in_boxscore=false). Card counts from scoreboard details wired in PR #39 (unmerged); no archived records yet", ["doc:sift-alpha/research/audit/lineage/soccer_archive_and_espn_probe_evidence.json"]),
 "soc.xg": (N, UK, "results records (31 files, 5,727 records) have home_xg/away_xg slots but 0 populated; live results are appended from scoreboards without box-score stats (the slots are only filled by football-data historical providers) [ESPN summary box score carries NO xG statistic (8/8 probed matches, run 41543056159): ESPN is not an xG source; football-data.co.uk HxG/AxG remains the only wired candidate]", ["arch:soccer-edge-finder:data-archive:results", "doc:sift-alpha/research/audit/lineage/field_evidence.json"]),
 "soc.weather": (P, UK, "Open-Meteo snapshots, 3,993 rows / 756 events 2026-09-28..11-02; 12.6% of rows were captured AFTER kickoff and must be excluded from pre-game use; 744 of 756 events have >=1 pre-kickoff snapshot", ["arch:soccer-edge-finder:data-archive:weather", "doc:sift-alpha/research/audit/lineage/soccer_context_lineage.json"]),
 "soc.ratings": (M, USE, "Dixon-Coles v2 + ClubElo columns from club dataset; ClubElo API 502 at probe", ["doc:soccer-edge-finder/docs/DATA_SOURCE_AUDIT.md"]),
 "soc.referee": (N, NC, "results record has no referee field; no referee path in the archive", ["arch:soccer-edge-finder:data-archive:results", "doc:sift-alpha/research/audit/lineage/field_evidence.json"]),
},
"TENNIS": {
 "m.orderbook_depth": (P, UK, "capture books.jsonl.gz (400 records, captured_at 2026-11-02T23:55Z): full orderbook populated on 100%", ["arch:Tennis-Edge-Finder:tennis-data:tennis-edge-finder/data/kalshi/capture", "doc:sift-alpha/research/audit/lineage/market_record_fields_extra.json"]),
 "m.volume_oi": (P, UK, "quotes.jsonl.gz (619 records): volume_fp / open_interest_fp / volume_24h_fp present on 100%, non-zero on 48.6% / 48.6% / 45.1%, stamped captured_at", ["arch:Tennis-Edge-Finder:tennis-data:tennis-edge-finder/data/kalshi/capture", "doc:sift-alpha/research/audit/lineage/market_record_fields_extra.json"]),
 "m.lifecycle": (P, UK, "quotes.jsonl.gz: status / close_time / expected_expiration_time / can_close_early / early_close_condition / settlement_timer_seconds on 100% of 619 records, stamped captured_at; state at each capture only", ["arch:Tennis-Edge-Finder:tennis-data:tennis-edge-finder/data/kalshi/capture", "doc:sift-alpha/research/audit/lineage/market_record_fields_extra.json"]),
 "m.fees": (M, UK, "fee_type / fee_multiplier per series in config/kalshi_tennis_series.json (static snapshot 2026-09-11)", ["doc:Tennis-Edge-Finder/config/kalshi_tennis_series.json"]),
 "m.rules_text": (S, UK, "config/kalshi_settlement_rules.json; 286 contract-terms PDFs listed but not parsed", ["doc:Tennis-Edge-Finder/docs/DATA_SOURCES.md"]),
 "m.quote_history": (P, USE, "tennis-data branch kalshi: 114,371 files 2026-09-11..11-02", ["arch:Tennis-Edge-Finder:tennis-data:tennis-edge-finder/data/kalshi"]),
 "ten.surface_rating": (S, USE, "Sackmann forks FROZEN: ATP to 2026-06-01, WTA to 2026-04-27. Partial replacement measured (valuebetennis odds-linked results to 2026-11-01 but odds-matched matches only, winner+score missing on part of rows, May-2026 thin) - not ingested; see sources/tennis_results_intervals.json", ["doc:Tennis-Edge-Finder/docs/DATA_SOURCES.md", "doc:sift-alpha/research/audit/sources/tennis_results_intervals.json"]),
 "ten.serve_return": (S, USE, "same frozen results sources (serve stats)", ["doc:Tennis-Edge-Finder/docs/DATA_SOURCES.md"]),
 "ten.market_odds": (M, RO, "tennis-data.co.uk bookmaker odds (historical) and Smarkets/external-market research", ["doc:Tennis-Edge-Finder/docs/DATA_SOURCES.md"]),
 "ten.court_cond": (N, NC, "'Weather / altitude / venue coordinates ... not wired'", ["doc:Tennis-Edge-Finder/docs/DATA_SOURCES.md"]),
 "ten.schedule": (P, UK, "firstball: 8,010 files 2026-09-11..11-02", ["arch:Tennis-Edge-Finder:tennis-data:tennis-edge-finder/data/firstball"]),
 "ten.fitness": (U, UK, "withdrawals/retirements: no dedicated source documented", ["doc:Tennis-Edge-Finder/docs/DATA_SOURCES.md"]),
},
}

# --- period-scoring verification (live ESPN backfill run 41686590798; see research/audit/period_scoring_verification.json) ---
_PSV = "doc:sift-alpha/research/audit/period_scoring_verification.json"
_PS_WHERE = "arch:sift-alpha:period-scoring-data:out/data"
_PS_CAVEAT = ("POST-GAME rows: valid only as lagged features for LATER games. observed_at is the single backfill time (2026-11-03), so an observed_at-gated as-of join would drop every "
              "historical row; availability must be game end (not recorded). Current-season only; branch is a force-pushed orphan (append-only within a run, not across runs). Not wired into any sport repo/model.")
CUR["NFL"]["nfl.q_scoring"] = (M, NC, "ESPN scoreboard linescores: 121 completed 2026 games 2026-09-09..11-02, 121/121 sums reconcile to final, 0 failed days. " + _PS_CAVEAT, [_PSV, _PS_WHERE + "/nfl"])
CUR["CFB"]["cfb.q_scoring"] = (M, NC, "ESPN scoreboard linescores: 622 completed 2026 FBS games 2026-08-29..10-31, 622/622 reconcile. " + _PS_CAVEAT, [_PSV, _PS_WHERE + "/cfb"])
CUR["CFB"]["cfb.half_split"] = (M, NC, "1H/2H points = Q1+Q2 / Q3+Q4 of the 622 reconciled ESPN linescores (derived at read time, not stored). " + _PS_CAVEAT, [_PSV, _PS_WHERE + "/cfb"])
CUR["NBA"]["nba.q_scoring"] = (M, UK, "ESPN scoreboard linescores: 107 completed 2026-27 games 2026-10-20..11-02, 107/107 reconcile (quarter scoring only; first-quarter pace and starter-minutes parts of this input are NOT collected). Local nba-edge-finder code also references quarter scoring in simulate.py (use unverified). " + _PS_CAVEAT, [_PSV, _PS_WHERE + "/nba"])
CUR["CBB"]["cbb.half_split"] = (S, NC, "ESPN scoreboard linescores: only ONE slate collected (2026-11-02, season opener): 182 games, 182/182 reconcile; no history beyond that day. " + _PS_CAVEAT, [_PSV, _PS_WHERE + "/cbb"])
CUR["NHL"]["nhl.period_split"] = (M, NC, "was DERIVED-by-assumption; now backed by direct ESPN linescores: 192 games 2026-10-06..11-02, 190 reconcile, 2 SCORE_UNRECONCILED excluded (one-goal discrepancy vs ESPN final). " + _PS_CAVEAT, [_PSV, _PS_WHERE + "/nhl"])
CUR["NHL"]["nhl.shootout_record"] = (S, NC, "Only the OT flag is derivable from the period rows (43 of 192 games had >3 periods); ESPN shootout resolution and shooter/goalie shootout talent are not stored. " + _PS_CAVEAT, [_PSV, _PS_WHERE + "/nhl"])

# --- CBB Kalshi snapshot archive, all 105 files read (research/audit/lineage/cbb_archive_field_evidence.json) ---
CUR["CBB"]["m.settlement_truth"] = (P, UK, "kalshi-archive snapshots 2026-10-05..11-03 (105 files, all read): 5,623 distinct tickers observed finalized, result + settlement_value_dollars + settlement_ts populated on 5,623/5,623 (yes 2,345 / no 3,276 / scalar 2 - scalars are not YES/NO). Snapshot cadence 2-4/day, so the result is known to us only at the next snapshot", ["arch:cbb-edge-finder:kalshi-archive:snapshots", "doc:sift-alpha/research/audit/lineage/cbb_archive_field_evidence.json"])

# --- Tennis settlement: only the three pinned 2026-10-25 captures were verified (docs/TENNIS_SETTLEMENT_EVIDENCE.md); no continuous settlement archive was inspected ---
CUR["TENNIS"]["m.settlement_truth"] = (S, UK, "three pinned 2026-10-25 captures, 36 settled contracts: status/result/settlement_value_dollars/settlement_ts populated, 17 YES / 17 NO / 2 scalar (0.5000 - neither side wins); occurrence_datetime is AFTER settlement_ts for 34 of 36 so it is not an independent result clock. One day only - the 114,371-file tennis-data kalshi tree was not checked for continuous settlement coverage", ["doc:sift-alpha/docs/TENNIS_SETTLEMENT_EVIDENCE.md", "doc:sift-alpha/research/tennis_settlement_pins.json"])

# --- live source-field probe (run 41695557684; research/audit/lineage/source_field_probe.json): the FIELD EXISTS on completed games at a free public endpoint.
# That is "source available, not collected" - no sport repo archives these fields, so none of these is counted as collected. 3 games per league (MLB statsapi: 1 game, season over).
_FP = "doc:sift-alpha/research/audit/lineage/source_field_probe.json"
_NOTE = " Post-game statistic: usable only as a lagged rate for LATER games. Presence on 3 sampled completed games, not a coverage rate; not archived by any collector."
def _N(note, extra=()): return (N, NC, note + _NOTE, [_FP, *extra])
CUR["NBA"]["nba.foul_rates"] = _N("ESPN summary: team `fouls`, player PF + MIN labels (3/3 games).")
CUR["NBA"]["nba.three_volume"] = _N("ESPN summary: team threePointFieldGoalsMade-Attempted, player 3PT (3/3 games).")
CUR["NBA"]["nba.steal_block_rates"] = _N("ESPN summary: team steals/blocks/turnovers, player STL/BLK/TO (3/3 games).")
CUR["NBA"]["nba.ft_attempts"] = _N("ESPN summary: team freeThrowsMade-freeThrowsAttempted, player FT (3/3 games).")
CUR["CBB"]["cbb.three_pt_dist"] = _N("ESPN summary: team threePointFieldGoalsMade-Attempted + player 3PT (3/3 games). Single-game variance needs a multi-season history that does not exist in any archive yet.")
CUR["CBB"]["cbb.free_throw"] = _N("ESPN summary: team freeThrowsMade-Attempted, player FT (3/3 games).")
CUR["CBB"]["cbb.player_foul"] = _N("ESPN summary: team fouls/technical/flagrant, player PF + MIN (3/3 games).")
CUR["NFL"]["nfl.kicker"] = _N("ESPN summary player category `kicking`: FG, LONG, PCT, XP, PTS (3/3 games). Distance buckets / touchback rate are NOT in the box score (need play text).")
CUR["CFB"]["cfb.kicker"] = _N("ESPN summary player category `kicking`: FG, LONG, PCT, XP, PTS (3/3 games). Distance buckets are NOT in the box score.")
CUR["NFL"]["nfl.opening_script"] = _N("ESPN summary `drives` list present on 3/3 games (23-28 drives each) + scoringPlays; per-drive result/yards/plays must be parsed from it.")
CUR["CFB"]["cfb.first_drive"] = _N("ESPN summary `drives` list present on 3/3 games (16-24 drives) + scoringPlays.")
CUR["NHL"]["nhl.shots_against"] = _N("ESPN summary team `shotsTotal` for both teams (opponent's total = shots against) and goalie SA/GA/SV% labels (3/3 games).")
CUR["NHL"]["nhl.penalty_rates"] = _N("ESPN summary team penalties, penaltyMinutes, powerPlayOpportunities/Goals/Pct (3/3 games); NHL api-web play-by-play has `penalty` events (7 in one game). Referee crew was not checked.")
CUR["NHL"]["nhl.shot_location"] = _N("NHL api-web play-by-play: xCoord/yCoord on 115/115, 115/115 and 117/117 shot events (shot-on-goal, goal, missed, blocked) in 3 games.")
CUR["NHL"]["nhl.shootout_record"] = (S, NC, "Partial. Period rows (period-scoring) give only an OT flag (43/192 games). SOURCES that resolve it exist: NHL api-web play-by-play periodDescriptor.periodType = REG/OT/SO (SO events present in 1 of 3 sampled games) and ESPN team `shootoutGoals` + goalie SOS/SOSA labels. Not archived." + _NOTE, [_PSV, _FP, _PS_WHERE + "/nhl"])
CUR["MLB"]["mlb.k_rates"] = _N("MLB statsapi boxscore pitching: strikeOuts, battersFaced (1 game; MLB season over). Whiff/CSW need pitch-level data, not checked.")
CUR["MLB"]["mlb.contact_dist"] = _N("MLB statsapi boxscore batting: hits, totalBases, rbi, plateAppearances, strikeOuts (1 game).")
CUR["MLB"]["mlb.sb_context"] = _N("MLB statsapi batting stolenBases/caughtStealing (1 game). Pitcher hold time and catcher pop time were NOT found in the box score.")
CUR["MLB"]["mlb.f3_split"] = _N("MLB statsapi linescore: runs for each of 9 innings, home and away (1 game); first-three-innings split is derivable. Kalshi KXMLBF3 (first 3 innings) has 1,419 settled markets in the MLB inventory.")
CUR["TENNIS"]["ten.tiebreak"] = _N("ESPN tennis scoreboard competitor.linescores carry `tiebreak` scores (ATP sample: 7-6 set with tiebreak 7). Break points / serve statistics were NOT verified (competitor.statistics key exists, contents not inspected).")

CUR["CBB"]["cbb.venue"] = (P, UK, "schedule-archive rows 2026-10-06..11-03 (35 files, all read): 10,531 rows / 6,116 games, neutral_site 100% (382 neutral games), venue name/id/city/state 99.9%, record-level observed_at 100%. NOT present: altitude, venue coordinates, travel distance (the label's 'altitude' part is uncollected)", ["arch:cbb-edge-finder:schedule-archive:rows", "doc:sift-alpha/research/audit/lineage/cbb_archive_field_evidence.json"])

# --- MLB Statcast pitch-level archive, all 643 game files read (research/audit/lineage/mlb_statcast_archive_evidence.json) ---
_SC = ["arch:edge-finder-api:main:data/statcast_raw", "doc:sift-alpha/research/audit/lineage/mlb_statcast_archive_evidence.json"]
_SCN = " RAW post-game pitch data: 643 games / 190,107 pitches, 2026-08-11..09-27 only; git-versioned on main (commit time unchecked) so PIT availability is unverified; aggregates/projections are not stored."
CUR["MLB"]["mlb.hitter_quality"] = (M, UK, "per-pitch estimatedWOBA on 99.1% of 33,032 batted-ball rows (xwOBA source), launch speed/angle, batted-ball type, batter hand." + _SCN, _SC)
CUR["MLB"]["mlb.platoon"] = (M, UK, "batterHand + pitcherHand + outcome on every pitch row; splits are derivable, none are stored." + _SCN, _SC)
CUR["MLB"]["mlb.sp_workload"] = (M, UK, "pitcher_games index + per-pitch rows give pitches thrown and batters faced per pitcher-game (derivable, not stored)." + _SCN, _SC)
CUR["MLB"]["mlb.sp_quality"] = (S, UK, "PARTIAL: raw inputs for stuff-style metrics are archived (pitch type 99.6%, release speed, spin, break, extension, plate location) but NO xFIP/SIERA/Stuff+ or projection exists." + _SCN, _SC)
CUR["MLB"]["mlb.k_rates"] = (M, NC, "whiff/CSW/K derivable from pitch `description` (swinging_strike, called_strike) and `events`; none stored." + _SCN, _SC + [_FP])

# --- soccer PR #39 live probe (run 41706413941; research/audit/lineage/soccer_pr39_live_probe.json): populated values verified on a runner, but the PR is an unmerged draft and
# nothing archives these fields in production, so the class stays SOURCE_AVAILABLE_NOT_COLLECTED. Values are post-match: lagged inputs only.
_SP = "doc:sift-alpha/research/audit/lineage/soccer_pr39_live_probe.json"
_SPN = " LIVE RUN 41706413941 (PR #39 code, unmerged): 153 of 164 finished matches (19 leagues, 2026-10-29..11-03) carry populated shots, shots on target, corners, yellow and red for both sides with box_stats_captured_at and source; 0 impossible values (SOT<=shots always); 11 finished matches (bra.1, ita.1, ksa.1, league_cup) got no box stats - cause not yet determined; second run appended 0 rows and rewrote 0 timestamps (idempotent). Only a 5-day window; not production-archived; post-match (lagged) use only."
CUR["SOCCER"]["soc.shots"] = (N, UK, "shots + shots on target." + _SPN, [_SP, "doc:sift-alpha/research/audit/lineage/soccer_archive_and_espn_probe_evidence.json"])
CUR["SOCCER"]["soc.corners"] = (N, UK, "corners." + _SPN, [_SP, "doc:sift-alpha/research/audit/lineage/soccer_archive_and_espn_probe_evidence.json"])
CUR["SOCCER"]["soc.fouls_cards"] = (N, UK, "yellow/red cards (153 exact box-score, 11 scoreboard-only 'unreconciled'). Fouls and referee not examined in the live run." + _SPN, [_SP, "doc:sift-alpha/research/audit/lineage/soccer_archive_and_espn_probe_evidence.json"])
