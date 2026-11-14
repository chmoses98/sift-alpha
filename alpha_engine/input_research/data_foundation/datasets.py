"""Raw-dataset registry for the data-foundation audit (RESEARCH_ONLY).

A dataset is a concrete raw data product a catalog input is computed from ("NFL play-by-play", "NBA official injury report with report timestamps"). Access status is COMPUTED by
`evidence.py` from measured evidence (probes, repo ledgers, earlier source verification); what is DECLARED here is only: which sources provide it, the history/PIT/freshness characterisation
and its evidence grade, and special cases (`kind`) where no probe can apply.

pit (point-in-time class; what a pregame model may legitimately know):
  EVENT_TIME      every record carries the time the event happened; strictly-prior features can be rebuilt for any past date (results, play-by-play, box scores)
  STATIC          fixed or slowly changing reference data known well before the game (venue, rules, schedule once published)
  WEEKLY_SNAPSHOT a periodic snapshot (depth charts, weekly designations); usable only at the snapshot cadence, final-of-period risk
  FINAL_ONLY      only the final/as-played value is stored with no publication time (lineups as played, retrieved-later ranks, final injury status): pregame use LEAKS unless vintages are captured
  PIT_NATIVE      the archive itself preserves time-stamped vintages (injury report rows with report time, historical-forecast model runs)
  LIVE_SNAPSHOT   only the current state is served; history can only be built by capturing from now on
  NONE            no usable timing at all
kind overrides (when the answer is structural, not measurable by a probe):
  None            status follows the evidence
  own_capture     no public history exists; must be recorded prospectively (cost: engineering + time, history starts at capture)
  paid            only commercial sources hold it (NOT added without the owner's permission)
  none            no known public source (catalog audit found none)
  sample_only     a free but partial sample (selected competitions / seasons), not a full history
  manual          requires human coding or reading (video, long documents)
  reference       static rules/regulation documents, read once and encoded
history: first/last are 4-digit years or ISO dates; `basis` MEASURED (ledger/probe/prior verification) or DOCUMENTED (provider docs/knowledge, not verified from this runner).
"""
from __future__ import annotations

DATASETS: dict[str, dict] = {}
PIT = ("EVENT_TIME", "STATIC", "WEEKLY_SNAPSHOT", "FINAL_ONLY", "PIT_NATIVE", "LIVE_SNAPSHOT", "NONE")
KINDS = (None, "own_capture", "paid", "none", "sample_only", "manual", "reference")


def D(id, sports, title, sources, *, ev=None, first=None, last=None, basis="DOCUMENTED", pit="EVENT_TIME", fresh="", miss="", kind=None, notes=""):
    """ev = {"ledger": (file, key) | None, "probe": probe id | None, "prior": (key, sub) | None}"""
    assert id not in DATASETS, id
    assert pit in PIT and kind in KINDS, id
    DATASETS[id] = {"id": id, "sports": [sports] if isinstance(sports, str) else list(sports), "title": title, "sources": sources, "evidence": ev or {}, "history": {"first": first, "last": last, "basis": basis},
                    "pit": pit, "freshness": fresh, "missingness": miss, "kind": kind, "notes": notes}


# ====================================================================== NFL
NFL = "NFL"
D("nfl.schedule_results", NFL, "Schedule, final scores, venue, roof/surface, observed temp/wind, coaches, referee, rest days (nfldata games.csv)", ["nflverse"], ev={"probe": "nflverse_games"}, first="1999", last="2025", basis="DOCUMENTED", pit="STATIC", fresh="results same day; schedule known months ahead", miss="observed (not forecast) weather; spread/total columns are market data and excluded")
D("nfl.pbp", NFL, "Play-by-play with EPA/WP, personnel-free (nflfastR)", ["nflverse"], ev={"probe": "nflverse_pbp_2024", "probe2": "nflverse_pbp_2003"}, first="1999", last="2025", basis="MEASURED", pit="EVENT_TIME", fresh="updated nightly in season", miss="EPA/WP are model outputs fitted on all seasons (look-ahead risk if used as a historical feature without re-fitting); some tracking-derived fields only 2006+")
D("nfl.player_stats_weekly", NFL, "Weekly player stats (passing/rushing/receiving/defence/kicking)", ["nflverse"], ev={"prior": ("nflverse", "stats_player")}, first="2011", last="2025", basis="MEASURED", pit="EVENT_TIME", fresh="nightly in season")
D("nfl.snap_counts", NFL, "Snap counts per player-game with snap share", ["nflverse"], ev={"prior": ("nflverse", "snap_counts"), "probe": "nflverse_snaps_2024"}, first="2012", last="2025", basis="MEASURED", pit="EVENT_TIME", fresh="nightly in season")
D("nfl.injuries_weekly", NFL, "Weekly practice and game-status injury designations (final of week)", ["nflverse"], ev={"prior": ("nflverse", "injuries"), "probe": "nflverse_injuries_2024"}, first="2009", last="2025", basis="MEASURED", pit="WEEKLY_SNAPSHOT", fresh="weekly", miss="one row per player-week: intra-week vintages (Wed/Thu/Fri) are not preserved; status timing relative to kickoff unknown")
D("nfl.inactives_game_day", NFL, "Official game-day inactive lists (published ~90 minutes before kickoff)", ["nfl_official", "espn_json"], first=None, basis="DOCUMENTED", pit="FINAL_ONLY", kind="own_capture", fresh="90 minutes before kickoff", notes="nflverse carries only a derived inactive flag; the timestamped official list needs prospective capture or a game-book scrape without timing")
D("nfl.injury_report_vintages", NFL, "Official injury report vintages by day (timestamped designations)", ["espn_json"], ev={"prior": ("espn", "classification")}, pit="LIVE_SNAPSHOT", kind="own_capture", fresh="live snapshot only", notes="ESPN's injury list has no history endpoint (earlier verification 2026-11-07: SNAPSHOT_ONLY)")
D("nfl.depth_charts", NFL, "Depth charts (team-published, weekly)", ["nflverse"], ev={"prior": ("nflverse", "depth_charts"), "probe": "nflverse_depth_2024"}, first="2001", last="2025", basis="MEASURED", pit="WEEKLY_SNAPSHOT", fresh="weekly", miss="snapshot cadence coarser than lineup changes; late changes not captured")
D("nfl.rosters", NFL, "Rosters and player attributes (position, age, experience, ids)", ["nflverse"], ev={"prior": ("nflverse", "rosters"), "probe": "nflverse_rosters_2024"}, first="1999", last="2025", basis="MEASURED", pit="WEEKLY_SNAPSHOT", fresh="weekly in season")
D("nfl.participation", NFL, "Per-play participation: personnel, formation, coverage type/man-zone, pressure, time to throw", ["nflverse"], ev={"prior": ("nflverse", "pbp_participation"), "probe": "nflverse_participation_2024"}, first="2016", last="2025", basis="MEASURED", pit="EVENT_TIME", miss="2016-2022 from NFL GSIS, 2023+ from FTN/other; schema changes by season")
D("nfl.ftn_charting", NFL, "FTN play charting (play-action, RPO, blitz, routes, drops)", ["nflverse"], ev={"prior": ("nflverse", "ftn_charting"), "probe": "nflverse_ftn_2024"}, first="2022", last="2025", basis="MEASURED", pit="EVENT_TIME", miss="four seasons only")
D("nfl.nextgen_stats", NFL, "Next Gen Stats player-season/week aggregates (separation, time to throw, rush yards over expected)", ["nflverse"], ev={"prior": ("nflverse", "nextgen_stats"), "probe": "nflverse_nextgen_passing"}, first="2016", last="2023", basis="MEASURED", pit="EVENT_TIME", miss="aggregates only; no raw tracking; latest probed year 2023")
D("nfl.pfr_advstats", NFL, "PFR advanced weekly stats (pressures, targets in coverage, air yards)", ["nflverse", "pfr"], ev={"prior": ("nflverse", "pfr_advstats"), "probe": "nflverse_pfr_adv"}, first="2018", last="2025", basis="MEASURED", pit="EVENT_TIME")
D("nfl.officials", NFL, "Officiating crew per game", ["nflverse"], ev={"prior": ("nflverse", "officials"), "probe": "nflverse_officials"}, first=None, basis="MEASURED", pit="STATIC", fresh="assigned ~1 week before the game; per-game crews, not penalty-rate tables", miss="penalty tendencies must be derived from pbp")
D("nfl.contracts_cap", NFL, "Player contracts and cap tables (OverTheCap history)", ["nflverse", "overthecap"], ev={"probe": "nflverse_contracts"}, pit="STATIC", fresh="updated with signings", miss="vintage of the cap table at each past date is not preserved")
D("nfl.draft_combine", NFL, "Draft picks and combine measurements", ["nflverse", "nfl_official"], ev={"probe": "nflverse_draft"}, first="1980", basis="DOCUMENTED", pit="STATIC", fresh="annual; combine results annual")
D("nfl.ff_opportunity", NFL, "Expected fantasy points / expected TDs (ff_opportunity)", ["nflverse"], ev={"probe": "nflverse_ffopp"}, pit="EVENT_TIME", notes="Probe 404 at the guessed asset path: the file name could not be confirmed from this runner (not proof of absence)")
D("nfl.raw_tracking", NFL, "Raw player tracking (x, y, speed, orientation)", ["nflverse"], pit="EVENT_TIME", kind="sample_only", notes="Only the annual NFL Big Data Bowl samples (a few seasons/weeks, account required) are free; full tracking is NFL/AWS-licensed")
D("nfl.transactions_news", NFL, "Transactions, trades, signings, coaching changes, timestamped insider reports", ["nfl_official", "news_press"], pit="LIVE_SNAPSHOT", kind="own_capture", miss="no free, timestamped, structured archive")
D("nfl.awards_results", NFL, "Award and honor results (AP honors, Pro Bowl, All-Pro, Hall of Fame)", ["wikipedia", "pfr", "nfl_official"], pit="STATIC", fresh="annual", miss="ballot-level AP voting detail is not public")

# ====================================================================== CFB
CFB = "CFB"
D("cfb.games_espn", CFB, "ESPN scoreboard: scores, period scores, venue, neutral/indoor, attendance, conference flag, ranks (retrieval-time)", ["espn_json"], ev={"ledger": ("espn_cfb_ledger.json", None)}, first="2021", last="2026", basis="MEASURED", pit="FINAL_ONLY", fresh="same day", miss="rank/records are retrieval-time values, not pregame vintages; odds fields not read")
D("cfb.pbp_cfbd", CFB, "Play-by-play, drives, team and player game stats, SP-style ratings (CollegeFootballData / cfbfastR)", ["cfbd"], ev={"probe": "cfbd_api"}, first="2001", basis="DOCUMENTED", pit="EVENT_TIME", kind=None, fresh="same day", miss="free API key required (free tier monthly quota); coverage thinner before ~2014 for pbp", notes="host blocked from the runner; needs the owner to register a free key")
D("cfb.box_player", CFB, "Player box scores / ESPN summary", ["espn_json", "cfbd"], ev={"probe": "espn_cfb_summary"}, pit="EVENT_TIME", fresh="same day", miss="not collected in the repo; ESPN summary endpoint reachable")
D("cfb.availability_snapshots", CFB, "Injury/availability reports and depth charts (team/conference)", ["espn_json", "small_ratings_sites"], pit="LIVE_SNAPSHOT", kind="own_capture", miss="no history endpoint; the earlier 2026 archive in cfb-edge-finder covers weeks only")
D("cfb.rankings_polls", CFB, "AP / coaches / CFP committee rankings by week (vintaged)", ["ap_polls", "espn_json", "ncaa_official"], pit="PIT_NATIVE", fresh="weekly", miss="published weekly with dates, so vintages are reconstructible from archives")
D("cfb.recruiting_portal", CFB, "Recruiting composites, transfer portal entries, roster continuity", ["recruiting", "cfbd"], pit="FINAL_ONLY", fresh="daily in windows", miss="free tools expose current composites; historical vintages need capture")
D("cfb.coaching_finance", CFB, "Coach contracts and salaries, athletic finance (USA Today, EADA)", ["eada_open_records"], pit="STATIC", fresh="annual", miss="public-records dependent; staggered")
D("cfb.rules_formats", CFB, "Conference formats, tiebreakers, CFP and bowl eligibility rules, APR, bowl tie-ins", ["ncaa_official", "rules_docs", "wikipedia"], pit="STATIC", kind="reference", fresh="annual")
D("cfb.pff_charting", CFB, "PFF college grades/snaps and charting", ["pff_sis"], pit="EVENT_TIME", kind="paid")
D("cfb.raw_tracking_scheme", CFB, "Tracking, formation/personnel and scheme charting for college football", ["none_found"], pit="EVENT_TIME", kind="none", notes="catalog audit: no free CFB personnel feed")

# ====================================================================== NBA
NBA = "NBA"
D("nba.team_games", NBA, "Team game results, quarter scores, totals, possessions (ESPN, repo archive)", ["espn_nba_archive"], ev={"ledger": ("repo_archives_ledger.json", "nba_espn_team_games")}, first="2023-10-05", last="2026-11-01", basis="MEASURED", pit="EVENT_TIME", fresh="same day", miss="three full seasons plus the current one; pre-2023 not collected (ESPN scoreboard history exists)")
D("nba.player_games", NBA, "Player box scores: minutes, counting stats, started flag", ["espn_nba_archive"], ev={"ledger": ("repo_archives_ledger.json", "nba_espn_player_games")}, first="2023-10-05", last="2026-11-01", basis="MEASURED", pit="EVENT_TIME", fresh="same day")
D("nba.pbp", NBA, "Play-by-play with wall-clock times", ["espn_nba_archive"], ev={"ledger": ("repo_archives_ledger.json", "nba_espn_pbp_events")}, first="2024", last="2026", basis="MEASURED", pit="EVENT_TIME")
D("nba.shots_xy", NBA, "Shot events with x,y locations", ["espn_nba_archive"], ev={"ledger": ("repo_archives_ledger.json", "nba_espn_shot_events")}, first="2023", last="2026", basis="MEASURED", pit="EVENT_TIME")
D("nba.lineup_stints", NBA, "Five-man lineup stints", ["espn_nba_archive"], ev={"ledger": ("repo_archives_ledger.json", "nba_espn_stints")}, first="2024", last="2026", basis="MEASURED", pit="EVENT_TIME")
D("nba.injury_report_vintages", NBA, "Official NBA injury report rows with report timestamps", ["espn_nba_archive", "nba_official"], ev={"ledger": ("repo_archives_ledger.json", "nba_official_injury_report_rows"), "probe": "nba_injury_report_pdf"}, first="2025-10-21", last="2026-06-13", basis="MEASURED", pit="PIT_NATIVE", fresh="published several times daily; PDF archive", miss="2025-26 season only (167k rows); earlier seasons exist as PDFs on the official site but are not collected")
D("nba.referees", NBA, "Referee assignments (announced pregame) and per-game crews", ["nba_official"], pit="STATIC", kind=None, fresh="published the morning of the game", miss="not in the pulled archives; official.nba.com host not probed")
D("nba.schedule_arena", NBA, "Schedule, arena, altitude, travel/rest derived inputs", ["nba_cdn", "espn_json"], ev={"probe": "espn_nba_scoreboard"}, pit="STATIC", miss="cdn.nba.com returned 403 (policy); ESPN scoreboard reachable")
D("nba.tracking", NBA, "Player tracking (speed, defender distance, touches, Second Spectrum)", ["nba_stats_api", "none_found"], pit="EVENT_TIME", kind="none", notes="stats.nba.com tracking dashboards are unofficial and blocked from cloud IPs; raw Second Spectrum tracking is not public")
D("nba.playtype_scheme", NBA, "Synergy-style play types, coverages, hustle stats, matchup data", ["nba_stats_api", "cleaning_the_glass"], pit="EVENT_TIME", kind="paid", miss="the free unofficial tracking dashboards are blocked/unstable; Synergy and Cleaning the Glass are paid")
D("nba.advanced_ratings", NBA, "Public advanced ratings (EPM, DARKO, RAPM) with historical vintages", ["epm_darko"], pit="FINAL_ONLY", miss="current values free; historical as-of-date vintages need capture")
D("nba.on_off_lineup_external", NBA, "PBPStats on/off and lineup tables", ["pbpstats"], pit="EVENT_TIME", miss="free tier limited; reproducible from own PBP stints instead")
D("nba.transactions_draft", NBA, "Transactions, draft order, lottery odds, pick ownership, draft boards", ["nba_transactions", "draft_boards", "nba_official"], pit="LIVE_SNAPSHOT", kind="own_capture", miss="final outcomes are public; time-stamped boards/rumours are not archived")
D("nba.awards_allstar", NBA, "Awards, All-Star voting, All-NBA, Shooting Stars/contest rules and results", ["bbref", "nba_official", "wikipedia", "rules_docs"], pit="STATIC", fresh="annual / seasonal", miss="fan/player/media vote tallies partly published; ballots not public")

# ====================================================================== CBB
CBB = "CBB"
D("cbb.games_espn", CBB, "ESPN scoreboard: scores, half scores, venue, neutral site, attendance, ranks (retrieval-time)", ["espn_cbb", "espn_json"], ev={"ledger": ("espn_cbb_ledger.json", None)}, first="2021-11-09", last="2026-04-07", basis="MEASURED", pit="FINAL_ONLY", fresh="same day", miss="rank/records are retrieval-time values; 31,039 games over 5 seasons")
D("cbb.box_player", CBB, "Player box scores and play-by-play (hoopR / ESPN summary / NCAA)", ["espn_cbb", "ncaa_official", "sports_reference"], ev={"probe": "espn_cbb_summary"}, pit="EVENT_TIME", miss="not collected in the repo; the probe 404 was a guessed event id, ESPN summary reachable in principle")
D("cbb.ratings_barttorvik", CBB, "Bart Torvik T-Rank team/player tables and daily time-machine ratings", ["barttorvik"], ev={"probe": "barttorvik"}, pit="PIT_NATIVE", fresh="daily", miss="host blocked from the runner; time-machine pages give as-of-date ratings")
D("cbb.ratings_kenpom", CBB, "KenPom ratings, game logs, snapshots", ["kenpom"], ev={"probe": "kenpom"}, pit="PIT_NATIVE", kind="paid")
D("cbb.net_bracket", CBB, "NET rankings, quadrant records, team sheets, bracketology consensus", ["massey", "ncaa_official"], pit="PIT_NATIVE", fresh="daily in season", miss="daily NET snapshots must be captured; history via Wayback only")
D("cbb.polls", CBB, "AP / coaches poll by week", ["ap_polls", "sports_reference"], pit="PIT_NATIVE", fresh="weekly")
D("cbb.availability_snapshots", CBB, "Injury/availability and roster status", ["espn_json"], ev={"prior": ("espn", "classification")}, pit="LIVE_SNAPSHOT", kind="own_capture", miss="2026 archive in cbb-edge-finder covers weeks only")
D("cbb.recruiting_portal", CBB, "Recruiting classes, transfer portal, returning production", ["recruiting", "sports_reference"], pit="FINAL_ONLY")
D("cbb.coaching_finance", CBB, "Coach contracts/salaries, athletic finance, vacancies", ["eada_open_records", "news_press"], pit="STATIC", fresh="annual / event-driven")
D("cbb.rules_formats", CBB, "Tournament formats, selection principles, conference tiebreakers, eligibility rules", ["ncaa_official", "rules_docs"], pit="STATIC", kind="reference")
D("cbb.shot_tracking_scheme", CBB, "Shot-location splits, lineup data, play types for college basketball", ["hoop_math", "none_found"], pit="EVENT_TIME", kind="none", miss="hoop-math partial; full Synergy/TrackMan is paid")

# ====================================================================== NHL
NHL = "NHL"
D("nhl.games", NHL, "Games, scores, schedule (repo archive 2008-2026)", ["nhl_archive", "nhl_api"], ev={"ledger": ("repo_archives_ledger.json", "nhl_games")}, first="2008-10-04", last="2026-06-17", basis="MEASURED", pit="EVENT_TIME", fresh="same day")
D("nhl.shots_xy", NHL, "Shot events with x,y, type, strength, goalie in net, xG (NHL API + MoneyPuck)", ["nhl_archive", "moneypuck", "nhl_api"], ev={"ledger": ("repo_archives_ledger.json", "nhl_shots"), "probe": "nhl_web_pbp"}, first="2021-10-12", last="2026-09-29", basis="MEASURED", pit="EVENT_TIME", miss="2008-2020 extension from MoneyPuck (1.37M rows); NHL API coordinates reachable")
D("nhl.player_games", NHL, "Player game rows with EV/PP/SH splits and TOI", ["nhl_archive"], ev={"ledger": ("repo_archives_ledger.json", "nhl_player_games")}, first="2021-10-12", last="2026-09-29", basis="MEASURED", pit="EVENT_TIME")
D("nhl.goalie_games", NHL, "Goalie game rows with starter flag", ["nhl_archive"], ev={"ledger": ("repo_archives_ledger.json", "nhl_goalie_games")}, first="2021-10-12", last="2026-09-29", basis="MEASURED", pit="FINAL_ONLY", miss="starter flag is final; the pregame confirmation time is not recorded")
D("nhl.team_states", NHL, "Team stats by game state/strength", ["nhl_archive"], ev={"ledger": ("repo_archives_ledger.json", "nhl_team_states")}, first="2021-10-12", last="2026-09-29", basis="MEASURED", pit="EVENT_TIME")
D("nhl.shifts_lines", NHL, "Shift charts and line combinations", ["nhl_api", "dailyfaceoff"], ev={"probe": "nhl_shiftcharts"}, pit="EVENT_TIME", miss="api.nhle.com shift-chart host blocked from the runner; earlier verification also flagged it unreachable")
D("nhl.lineup_goalie_pregame", NHL, "Projected/confirmed starting goalies and lines, timestamped", ["dailyfaceoff"], ev={"probe": "dailyfaceoff"}, pit="LIVE_SNAPSHOT", kind="own_capture", miss="a pregame-lineup probe archive exists from 2026-10 only (earlier audit)")
D("nhl.ratings_external", NHL, "Natural Stat Trick / Evolving-Hockey / Hockey-Reference tables", ["nst"], pit="EVENT_TIME", miss="scrape-only, ToS-restricted; reproducible from own shots data (xG available via MoneyPuck)")
D("nhl.officials", NHL, "Referee/linesman assignments and penalty tendencies", ["none_found"], pit="STATIC", kind="none", miss="not in pulled data; Scouting the Refs lists crews on a scraped page")
D("nhl.transactions_draft", NHL, "Transactions, draft order/lottery, prospect rankings, contracts/cap", ["nhl_api", "overthecap", "draft_boards"], pit="LIVE_SNAPSHOT", kind="own_capture", miss="PuckPedia / CapWages history limited; ranking vintages not archived")
D("nhl.injuries", NHL, "Injury and availability reports", ["espn_json", "nst"], pit="LIVE_SNAPSHOT", kind="own_capture", miss="no history endpoint")
D("nhl.awards", NHL, "Awards, All-Star, Hart/Norris/Vezina voting results", ["wikipedia", "nhl_api"], pit="STATIC", fresh="annual")

# ====================================================================== MLB
MLB = "MLB"
D("mlb.schedule_games", MLB, "Schedule, results, linescores, probable pitchers, lineups, umpire, weather (as played), venue", ["mlb_statsapi"], ev={"ledger": ("mlb_schedule_ledger.json", None)}, first="2015-04-05", last="2025-09-28", basis="MEASURED", pit="FINAL_ONLY", fresh="same day", miss="lineups, umpires and weather are the as-played / retrieval-time values, not pregame vintages; 98-99% lineup coverage; 2020 has 900 games")
D("mlb.boxscore_player", MLB, "Player game box scores (hitters and pitchers)", ["mlb_statsapi"], ev={"ledger": ("mlb_boxscores_ledger.json", None)}, first="2024", last="2025", basis="MEASURED", pit="EVENT_TIME", miss="only 2 seasons collected (142,822 rows); source covers many more seasons; role fields 71% hitters / 29% pitchers by design")
D("mlb.pitch_pa_events", MLB, "Pitch- and plate-appearance-level events with pitch data, hit data, coordinates", ["mlb_statsapi", "savant"], ev={"prior": ("mlb_statsapi", "sampled_games"), "probe": "mlb_statsapi_feed"}, first="2008", last="2025", basis="MEASURED", pit="EVENT_TIME", miss="reachable, not collected; pitchData keys vary by era (extension, plateTime added 2020+)")
D("mlb.statcast_bulk", MLB, "Statcast search exports (exit velocity, launch angle, spin, bat tracking)", ["savant"], ev={"probe": "mlb_savant_csv"}, first="2015", basis="DOCUMENTED", pit="EVENT_TIME", miss="Savant host denied by the egress policy; pitch-level equivalents are in the MLB feed")
D("mlb.retrosheet", MLB, "Retrosheet event files and game logs (long history)", ["retrosheet"], ev={"probe": "retrosheet"}, first="1901", basis="DOCUMENTED", pit="EVENT_TIME", miss="host denied by the egress policy; static annual releases")
D("mlb.lineup_il_vintages", MLB, "Pregame lineup, probable pitcher and injured-list vintages with posting times", ["mlb_statsapi"], ev={"probe": "mlb_statsapi_sched"}, pit="LIVE_SNAPSHOT", kind="own_capture", miss="the schedule hydrate returns the current posted lineup with no posting timestamp")
D("mlb.transactions", MLB, "Transactions (IL, call-ups, trades, signings, DFA)", ["mlb_statsapi", "nba_transactions"], ev={"probe": "mlb_statsapi_trans"}, pit="EVENT_TIME", fresh="same day", miss="dated transactions endpoint reachable; time-of-day unknown")
D("mlb.projections_vintages", MLB, "Preseason and rest-of-season projections (ZiPS/Steamer/PECOTA/ATC) by date", ["fangraphs", "bbref_baseball"], pit="LIVE_SNAPSHOT", kind="own_capture", miss="only current vintages are public; historical vintages need own capture; PECOTA archives are paid")
D("mlb.leaderboards_external", MLB, "FanGraphs / Baseball-Reference leaderboards, park factors, splits", ["fangraphs", "bbref_baseball"], ev={"probe": "fangraphs"}, pit="FINAL_ONLY", miss="FanGraphs host denied; park factors and splits reproducible from own data")
D("mlb.player_ids", MLB, "Player id crosswalk and bio (Chadwick register)", ["chadwick"], ev={"probe": "chadwick_register"}, pit="STATIC")
D("mlb.draft_prospects", MLB, "Draft order, bonus slots, prospect rankings/boards (MLB Pipeline, BA, FanGraphs)", ["mlb_statsapi", "draft_boards"], pit="LIVE_SNAPSHOT", kind="own_capture", miss="MLB draft endpoint gives results; rankings vintages are not archived")
D("mlb.contracts_labor", MLB, "Contracts, payrolls, CBA/labour-dispute reporting", ["overthecap", "news_press"], pit="LIVE_SNAPSHOT", kind="own_capture", fresh="event-driven")
D("mlb.awards_allstar_derby", MLB, "Awards voting, All-Star and Derby rosters and results (BBWAA, MLB.com)", ["wikipedia", "mlb_statsapi", "bbref_baseball"], pit="STATIC", fresh="annual", miss="BBWAA ballots are published after voting; Derby tracking is Statcast")
D("mlb.umpire_stats", MLB, "Umpire strike-zone tendencies (UmpScorecards) and crew assignments", ["small_ratings_sites", "mlb_statsapi"], pit="STATIC", miss="home-plate umpire id per game is in the schedule hydrate")
D("mlb.paid_projections", MLB, "Paid draft/prospect/projection products (BA, PECOTA, The Athletic, Synergy/TrackMan)", ["bbref_baseball"], pit="FINAL_ONLY", kind="paid")

# ====================================================================== SOCCER
SOC = "SOCCER"
D("soc.results_shots_cards", SOC, "Match results, shots, SOT, corners, fouls, cards, referee name (football-data.co.uk, major leagues)", ["football_data_uk"], ev={"probe": "fd_epl_2425", "prior": ("football_data", "files")}, first="2015", last="2026", basis="MEASURED", pit="EVENT_TIME", miss="99.9-100% completeness for core columns (2015-16 to 2025-26); Referee column ~20% mean across league files (EPL only); five/ten leagues, Kalshi lists ~40")
D("soc.fixtures_intl", SOC, "Fixtures/results for many leagues and internationals (openfootball, martj42, football-data.org)", ["openfootball", "football_data_org"], ev={"probe": "openfootball"}, pit="STATIC", miss="results only; no stats")
D("soc.xg_events", SOC, "Shot-level xG and match events (Understat, StatsBomb open, FBref/Opta)", ["understat", "statsbomb_open", "fbref"], ev={"probe": "statsbomb_open", "probe2": "understat"}, pit="EVENT_TIME", kind="sample_only", miss="StatsBomb open data covers selected competitions/seasons only; Understat and FBref hosts are denied from the runner; FBref advanced Opta data is marked unavailable_public in the catalog")
D("soc.player_stats_lineups", SOC, "Player-level stats, starting lineups and minutes", ["fbref", "understat", "api_football"], ev={"probe": "fbref"}, pit="EVENT_TIME", kind="none", miss="no free full-coverage player-level feed identified (FBref unavailable_public; API-Football free tier is request-limited)")
D("soc.espn_scoreboard", SOC, "ESPN soccer scoreboards (results, lineups where present)", ["espn_json"], ev={"probe": "espn_soccer_scoreboard"}, pit="FINAL_ONLY", miss="coverage varies by league")
D("soc.ratings_elo", SOC, "Club Elo / national-team Elo ratings by date", ["clubelo"], ev={"probe": "clubelo"}, pit="PIT_NATIVE", miss="DNS did not resolve from this runner (api.clubelo.com); daily time series by date is the documented product")
D("soc.injuries_suspensions", SOC, "Injuries, suspensions and availability (Transfermarkt, PhysioRoom, Premier Injuries, team news)", ["transfermarkt", "api_football"], ev={"probe": "transfermarkt"}, pit="LIVE_SNAPSHOT", kind="own_capture", miss="current lists only; ToS restricts scraping")
D("soc.lineups_pregame", SOC, "Confirmed lineups (~60 minutes before kickoff) with timestamps", ["espn_json", "api_football"], pit="LIVE_SNAPSHOT", kind="own_capture")
D("soc.transfers_values", SOC, "Transfers, market values, contracts, manager changes", ["transfermarkt", "wikipedia"], pit="LIVE_SNAPSHOT", kind="own_capture", miss="market values as of past dates only via archives")
D("soc.competition_rules", SOC, "Competition formats, tiebreakers, coefficients, qualification slots, draws, regulations", ["uefa_fifa_official", "worldfootball", "rules_docs", "wikipedia"], pit="STATIC", kind="reference", fresh="seasonal")
D("soc.awards_history", SOC, "Awards (Ballon d'Or, PFA, golden boot) and historical results (RSSSF/worldfootball)", ["wikipedia", "worldfootball", "uefa_fifa_official"], pit="STATIC")
D("soc.referee_stats", SOC, "Referee assignments and tendencies", ["football_data_uk", "transfermarkt"], pit="STATIC", miss="football-data referee name only for the Premier League; assignment announced ~days ahead")
D("soc.opta_commercial", SOC, "Opta / StatsBomb commercial event and tracking feeds", ["opta_commercial"], pit="EVENT_TIME", kind="paid")

# ====================================================================== TENNIS
TEN = "TENNIS"
D("ten.matches", TEN, "ATP/WTA match results with serve stats, score, surface, round, ranks (Sackmann, repo archive)", ["sackmann"], ev={"ledger": ("repo_archives_ledger.json", "tennis_atp_matches"), "ledger2": ("repo_archives_ledger.json", "tennis_wta_matches")}, first="2000-01-03", last="2026-04-22", basis="MEASURED", pit="EVENT_TIME", miss="main-tour level; qualifying/challenger/ITF in separate files; retirements appear only as RET in the score; collected from the sibling Tennis-Edge-Finder archive (Sackmann repos are not attachable to this session: raw paths 404 here)")
D("ten.point_charting", TEN, "Point-by-point and shot-level charting (MatchChartingProject, slam point-by-point)", ["sackmann"], ev={"probe": "sackmann_charting"}, pit="EVENT_TIME", kind="sample_only", miss="charted subset of matches only (volunteer-coded)")
D("ten.results_odds_sheets", TEN, "tennis-data.co.uk results and odds spreadsheets", ["tennis_data_uk"], ev={"probe": "tennis_data_uk"}, pit="EVENT_TIME", miss="HTTP 403 for the .xlsx path from this runner; odds columns are market data (excluded)")
D("ten.draws_order_of_play", TEN, "Draws, seedings, entry lists, order of play, scheduled times (official sites; vintaged)", ["tennis_official", "wikipedia"], ev={"probe": "atp_site"}, pit="LIVE_SNAPSHOT", kind="own_capture", fresh="live during events", miss="official sites denied from the runner; published draws are on Wikipedia (static), schedule changes are not archived")
D("ten.rankings_history", TEN, "ATP/WTA rankings and race by week", ["sackmann", "tennis_official"], pit="PIT_NATIVE", fresh="weekly", miss="Sackmann rankings files are weekly with dates")
D("ten.withdrawals_injuries", TEN, "Withdrawals, retirements, injury news (timestamped)", ["tennis_official", "news_press"], pit="LIVE_SNAPSHOT", kind="own_capture", miss="only 'RET'/'W/O' in the final score; no vintaged withdrawal feed")
D("ten.court_speed_env", TEN, "Court speed index, weather, altitude, tournament conditions", ["tennis_abstract", "openmeteo", "noaa_nws"], pit="STATIC", miss="court-speed indices on scraped pages; weather via env datasets")
D("ten.tracking_commercial", TEN, "Hawk-Eye / Sportradar tracking and serve-speed feeds", ["sportradar_hawkeye"], pit="EVENT_TIME", kind="paid")
D("ten.rules_formats_awards", TEN, "Tour rules, formats, prize/ranking rules, awards and records", ["tennis_official", "wikipedia", "rules_docs"], pit="STATIC", kind="reference")
D("ten.elo_external", TEN, "Tennis Abstract / Ultimate Tennis Statistics Elo and surface splits", ["tennis_abstract"], ev={"probe": "tennis_abstract"}, pit="FINAL_ONLY", miss="host denied from the runner; reproducible from match results")

# ====================================================================== cross-cutting
D("env.weather_observed", ["NFL", "CFB", "MLB", "SOCCER", "TENNIS"], "Observed weather by venue and time (Open-Meteo archive, NOAA ISD, Meteostat)", ["openmeteo", "noaa_nws"], ev={"probe": "openmeteo_archive"}, first="1940", basis="DOCUMENTED", pit="EVENT_TIME", miss="hosts denied by the egress policy; observations are known after the fact (not a forecast)")
D("env.weather_forecast_pit", ["NFL", "CFB", "MLB", "SOCCER", "TENNIS"], "Weather FORECAST as issued before the game (point-in-time)", ["openmeteo", "noaa_nws"], ev={"probe": "openmeteo_histfc"}, first="2022", basis="DOCUMENTED", pit="PIT_NATIVE", miss="Open-Meteo's historical-forecast API reconstructs past model runs (documented from ~2022); NWS serves only the live forecast; host blocked from the runner so unverified")
D("env.venue_geo", ["NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"], "Venue coordinates, altitude, orientation, roof, surface, dimensions, time zone", ["wikipedia", "noaa_nws", "chadwick"], pit="STATIC", miss="hand-curated tables; Open-Elevation/SRTM for altitude")
D("mkt.kalshi_rules", ["NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"], "Kalshi contract rules text, series metadata, settlement sources", ["kalshi_api"], ev={"probe": "kalshi_public"}, pit="STATIC", fresh="live; rules text per market", miss="rules text for settled/old series may be truncated or absent (see the contract-rule samples)")
D("mkt.kalshi_prices", ["NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"], "Kalshi market prices, candlesticks, trades, order book", ["kalshi_api", "own_capture"], ev={"probe": "kalshi_public"}, pit="PIT_NATIVE", kind=None, miss="BENCHMARK ONLY: market-derived, excluded from market-free inputs")
D("mkt.external_odds", ["NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"], "Sportsbook/exchange odds and closing lines (The Odds API, football-data odds columns, Betfair)", ["odds_paid"], ev={"probe": "theoddsapi"}, pit="PIT_NATIVE", kind="paid", miss="BENCHMARK ONLY: market-derived; history is paid")
D("xx.id_crosswalk", ["NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"], "Player/team id crosswalks and entity resolution across sources", ["chadwick", "nflverse"], ev={"probe": "chadwick_register", "probe2": "nflverse_players"}, pit="STATIC")
D("xx.derived_upstream", ["NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"], "Derived from other catalog inputs (own model, simulation, ratings)", ["derived"], pit="EVENT_TIME", kind="reference", notes="no raw data of its own: availability = availability of its upstream inputs (recorded as depends_on where the catalog names them)")
_ALL = ["NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS"]
D("xx.rules_reference", _ALL, "Rules, formats, regulations, tiebreakers, CBA text, qualification and eligibility documents (read once, encode by hand)", ["rules_docs", "wikipedia", "uefa_fifa_official", "ncaa_official"], pit="STATIC", kind="reference", fresh="seasonal/annual; changes announced", miss="manual reading and encoding; wording changes by season")
D("xx.news_timestamped", _ALL, "Timestamped news, insider/beat reports, announcements, hires/fires, rumours, social posts, poll vintages", ["news_press", "own_capture"], pit="LIVE_SNAPSHOT", kind="own_capture", fresh="live", miss="no free structured archive with publication timestamps; Wayback is sparse")
D("xx.awards_results", _ALL, "Awards, honours, All-Star/Pro Bowl/Derby/contest results and public voting history (final results)", ["wikipedia", "bbref", "nfl_official", "nba_official", "mlb_statsapi"], pit="STATIC", fresh="annual", miss="final results public; ballot-level data public only for some awards (e.g., BBWAA)")
D("xx.draft_boards_vintaged", _ALL, "Draft boards, mocks, prospect rankings and lottery/order, with publication dates", ["draft_boards", "own_capture"], pit="LIVE_SNAPSHOT", kind="own_capture", miss="final picks are public; dated boards must be captured or taken from Wayback")
D("xx.contracts_finance", _ALL, "Contracts, cap/payroll tables, valuations, finance filings", ["overthecap", "eada_open_records"], pit="STATIC", fresh="event-driven", miss="free scrape pages show current values; as-of-date vintages are not preserved")
D("xx.projection_vintages", _ALL, "Projection systems (ZiPS/Steamer/PECOTA/ATC, preseason ratings) as published at each date", ["fangraphs", "own_capture"], pit="LIVE_SNAPSHOT", kind="own_capture", miss="only the current vintage is public; PECOTA archives are paid")
