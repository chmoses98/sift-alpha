"""Canonical data-source registry for the data-foundation audit (RESEARCH_ONLY).

Every source the catalog names (provenance / free_sources) is normalised to one canonical id here. Facts carry an evidence grade:
  MEASURED    probed from the research runner on 2026-11-09 (`probes.json`) or profiled in a repo ledger (`data_collection/*_ledger.json`) / `source_verification.json`
  DOCUMENTED  the provider's own documentation or well-known public behaviour, NOT verified from this runner (the egress policy blocks many hosts)
  CATALOG     only what the catalog's own provenance says (access class), nothing further known
A host the runner cannot reach (HTTP 403 from the egress proxy) is `BLOCKED_FROM_RUNNER`: that is not evidence the data does not exist.

kind:  free_download | free_api | free_scrape | free_key (free account/key needed: needs the owner's registration, not a purchase) | own_capture (no usable history: record prospectively) |
       paid | unavailable (no public source) | derived (own computation) | reference (rules/regulations/announcements, static documents)
tos:   low | medium (scraping tolerated with rate limits / unofficial API) | high (terms restrict automated access or bulk reuse)
"""
from __future__ import annotations

import re

# id: (name, kind, cost, tos, probe_id, regex over the lower-cased catalog source string)
_S = [
 # -- NFL / American football
 ("nflverse", "nflverse data releases (nflreadr / nfl_data_py): pbp, games, player stats, snaps, injuries, depth charts, rosters, participation, FTN, NGS, PFR, draft, combine, contracts", "free_download", "free", "low", "nflverse_pbp_2024", r"nflverse|nflfastr|nflreadr|nfl_data_py|nfldata|ftn charting|ff_opportunity|pbp_participation"),
 ("pfr", "Pro-Football-Reference", "free_scrape", "free", "high", "pfr", r"pro-football-reference|\bpfr\b|pro football reference"),
 ("overthecap", "OverTheCap / Spotrac / CapWages / Capology / Cot's / PuckPedia (contracts and cap)", "free_scrape", "free", "medium", "overthecap", r"overthecap|spotrac|capwages|capology|puckpedia|cot's|cots baseball"),
 ("cfbd", "CollegeFootballData API (api.collegefootballdata.com)", "free_key", "free (key)", "low", "cfbd_api", r"collegefootballdata|cfbd|sportsdataverse cfbfastr|cfbfastr"),
 ("espn_json", "ESPN public JSON (site.api.espn.com scoreboard, summary, injuries, rankings, odds)", "free_api", "free", "medium", "espn_nfl_scoreboard", r"espn public json|site\.api\.espn|espn.*json|espn fantasy|espn draft|espn/pff"),
 ("sports_reference", "Sports-Reference family (CBB, CFB, College basketball)", "free_scrape", "free", "high", None, r"sports-reference|sports reference"),
 ("nfl_official", "NFL.com / league official pages (draft order, combine, Pro Bowl, transactions, game books, GameCenter)", "free_scrape", "free", "medium", None, r"nfl\.com|nfl gamecenter|nfl game ?books?|nfl operations|nfl rulebook|nfl network|nfl t100|nfl competition|nfl schedule|nfl official|official league super bowl|pro football hall|nfl early-entry|nfl mock draft|nfl-elo|fivethirtyeight"),
 ("pff_sis", "PFF / Sports Info Solutions / The Athletic Freaks (charting, grades)", "paid", "paid", "high", None, r"\bpff\b|sports info solutions|athletic freaks|pass-rush win rate"),
 ("sp_plus", "Bill Connelly SP+ / ESPN+ (archived)", "paid", "paid", "high", None, r"sp\+|bill connelly"),
 ("recruiting", "247Sports / On3 composites and transfer-portal trackers", "free_scrape", "free", "high", None, r"247sports|on3\b|perfect game"),
 ("massey", "Massey Ratings / WarrenNolan / Bracket Matrix / NCAA NET team sheets", "free_scrape", "free", "medium", None, r"massey|warrennolan|bracket matrix|net rankings|team sheets|ncaa\.com net"),
 ("ncaa_official", "NCAA.com / stats.ncaa.org / conference and CFP sites (box scores, brackets, rules, APR, announcements)", "free_scrape", "free", "medium", None, r"stats\.ncaa|ncaa\.com|ncaa statistics|ncaa transfer|ncaa eligibility|ncaa bowl|conference (and cfp )?(official )?(websites|sites)|conference websites|tournament handbooks|cfp official|d3football|ncaa women|her hoop|tfrrs|naismith|wooden|hoophall"),
 ("ap_polls", "AP Top 25 / coaches poll archive", "free_scrape", "free", "medium", None, r"ap top 25|ap poll|ap and conference award|apnews"),
 ("eada_open_records", "US Dept of Education EADA, USA Today salary database, Knight Commission, public-records/FOIA, court dockets, NLRB, state records", "free_scrape", "free", "low", None, r"eada|usa today|knight commission|open-records|foia|court dockets|nlrb|state open|public records|pacer"),
 # -- NBA / CBB
 ("espn_nba_archive", "Repo archive of ESPN NBA data (nba-edge-finder): team games, player games, PBP, shots, five-man stints, official injury-report rows", "own_capture", "free", "medium", None, r"nba-edge-finder"),
 ("nba_stats_api", "stats.nba.com / nba_api (unofficial, rate-limited, blocks cloud IPs)", "free_scrape", "free", "medium", "nba_stats_api", r"stats\.nba\.com|nba_api|nba api|nba tracking|second spectrum|hustle stats"),
 ("nba_cdn", "cdn.nba.com liveData and static JSON (unofficial)", "free_api", "free", "medium", "nba_cdn_boxscore", r"cdn\.nba\.com|nba schedule json|nba cdn"),
 ("nba_official", "NBA.com / official.nba.com (injury report PDFs, referee assignments, announcements, rules)", "free_scrape", "free", "low", "nba_injury_report_pdf", r"official\.nba|nba\.com|nba injury report|nba official injury|g league stats|emirates nba cup"),
 ("bbref", "Basketball-Reference", "free_scrape", "free", "high", "bbref", r"basketball-reference|basketball reference"),
 ("pbpstats", "PBPStats.com (lineups, on/off, possession data)", "free_scrape", "free", "medium", None, r"pbpstats"),
 ("cleaning_the_glass", "Cleaning the Glass", "paid", "paid", "high", None, r"cleaning the glass"),
 ("epm_darko", "Dunks & Threes EPM / DARKO / EvanMiya", "free_scrape", "free", "medium", None, r"dunks ?& ?threes|darko|evanmiya|\bepm\b"),
 ("hoop_math", "hoop-math.com", "free_scrape", "free", "medium", None, r"hoop-math"),
 ("nba_transactions", "RealGM / ProSportsTransactions / league transaction wires", "free_scrape", "free", "medium", None, r"realgm|pro ?sports ?transactions|transaction wires|league transactions|pro sports transactions"),
 ("draft_boards", "Public draft boards and mocks (Tankathon, NBADraft.net, NFL Mock Draft Database, MLB Pipeline, ESPN/Athletic/BA boards, FanGraphs The Board)", "free_scrape", "free", "medium", None, r"tankathon|nbadraft|mock draft|big board|draft board|mlb pipeline|baseball america|the board|draft rankings|draft top 250|draft combine|draft lottery|draft endpoint|draft order"),
 ("espn_cbb", "ESPN men's college basketball / hoopR / sportsdataverse", "free_api", "free", "medium", "espn_cbb_scoreboard", r"hoopr|sportsdataverse|mens-college-basketball"),
 ("barttorvik", "Bart Torvik T-Rank / cbbdata", "free_scrape", "free", "medium", "barttorvik", r"barttorvik|bart torvik|cbbdata"),
 ("kenpom", "KenPom", "paid", "paid", "high", "kenpom", r"kenpom"),
 # -- NHL
 ("nhl_api", "NHL web API (api-web.nhle.com: schedule, boxscore, play-by-play with coordinates; api.nhle.com stats REST and shift charts)", "free_api", "free", "medium", "nhl_web_pbp", r"nhl web api|api-web\.nhle|api\.nhle|nhl\.com|nhl central scouting|tsn|mckenzie"),
 ("moneypuck", "MoneyPuck data downloads (shots with xG, players, goalies, teams)", "free_download", "free", "low", "moneypuck", r"moneypuck"),
 ("nst", "Natural Stat Trick / Evolving-Hockey / Hockey-Reference / Elite Prospects", "free_scrape", "free", "high", None, r"natural stat trick|evolving-hockey|hockey-reference|elite prospects|elite ?prospects"),
 ("dailyfaceoff", "Daily Faceoff (line combinations, projected and confirmed goalies)", "free_scrape", "free", "high", "dailyfaceoff", r"daily faceoff|dailyfaceoff"),
 ("nhl_archive", "Repo archive of NHL data (NHL-edge-finder): games, player/goalie games, shots with xy, team strength states, MoneyPuck shots", "own_capture", "free", "low", None, r"nhl-edge-finder"),
 # -- MLB
 ("mlb_statsapi", "MLB Stats API (statsapi.mlb.com: schedule, boxscore, live feed with pitch/hit data, transactions, draft, lineups, probable pitchers)", "free_api", "free", "medium", "mlb_statsapi_feed", r"mlb stats api|statsapi\.mlb|mlb\.com|milb stats|mlb lineups|mlb schedule|mlb official|mlb press|mlb postseason|mlb published|mlb trade rumors|mlbtr|mlb work stoppage|mlbpa|cba text"),
 ("savant", "Baseball Savant / Statcast search CSV / pybaseball", "free_download", "free", "medium", "mlb_savant_csv", r"baseball savant|statcast|pybaseball|savant"),
 ("retrosheet", "Retrosheet event files and game logs", "free_download", "free", "low", "retrosheet", r"retrosheet"),
 ("fangraphs", "FanGraphs (leaderboards, projections, park factors, RosterResource, The Board)", "free_scrape", "free", "high", "fangraphs", r"fangraphs|steamer|zips|\batc\b"),
 ("bbref_baseball", "Baseball-Reference / Baseball Prospectus / PECOTA", "free_scrape", "free", "high", None, r"baseball-reference|baseball reference|baseball prospectus|pecota|jon roegele|d1baseball|cape cod|npb|kbo"),
 ("chadwick", "Chadwick Bureau register / Lahman database (player ID crosswalk and history)", "free_download", "free", "low", "chadwick_register", r"chadwick|lahman|baseballdatabank"),
 # -- Soccer
 ("football_data_uk", "football-data.co.uk (results, shots, corners, cards, referee, odds columns)", "free_download", "free", "low", "fd_epl_2425", r"football-data\.co\.uk"),
 ("football_data_org", "football-data.org v4 free tier", "free_key", "free (key)", "low", None, r"football-data\.org"),
 ("openfootball", "openfootball (fixtures, results) / martj42 international results / league fixture lists", "free_download", "free", "low", "openfootball", r"openfootball|martj42|league fixture|fixture lists|fifa match schedule|league (official )?tables|league and federation"),
 ("fbref", "FBref (Opta-sourced) match, team and player tables", "unavailable", "unavailable", "high", "fbref", r"fbref"),
 ("understat", "Understat (shot-level xG, xGChain)", "free_scrape", "free", "high", "understat", r"understat|whoscored|american soccer analysis"),
 ("statsbomb_open", "StatsBomb open data (selected competitions only)", "free_download", "free", "low", "statsbomb_open", r"statsbomb open"),
 ("opta_commercial", "Opta / StatsBomb commercial feeds", "paid", "paid", "high", None, r"opta / statsbomb|^statsbomb$|opta commercial|statsbomb commercial"),
 ("clubelo", "clubelo.com / eloratings.net", "free_api", "free", "low", "clubelo", r"clubelo|eloratings"),
 ("transfermarkt", "Transfermarkt / PhysioRoom / Premier Injuries / CAS / club accounts (injuries, values, transfers)", "free_scrape", "free", "high", "transfermarkt", r"transfermarkt|physioroom|premier injuries|club annual accounts|cas database"),
 ("uefa_fifa_official", "UEFA / FIFA / IFAB / federation official sites (regulations, draws, coefficients, squad lists, awards)", "free_scrape", "free", "low", None, r"uefa|fifa|ifab|federation|france football|governing-body|competition regulations|mls all-star|premier league / fa"),
 ("worldfootball", "worldfootball.net / RSSSF / Wikipedia competition pages", "free_scrape", "free", "low", None, r"worldfootball|rsssf"),
 # -- Tennis
 ("sackmann", "Jeff Sackmann tennis_atp / tennis_wta / MatchChartingProject / slam point-by-point", "free_download", "free (CC BY-NC-SA)", "low", "sackmann_charting", r"sackmann|matchchartingproject|slam_pointbypoint|tennis_atp|tennis_wta"),
 ("tennis_data_uk", "tennis-data.co.uk results and odds spreadsheets", "free_download", "free", "low", "tennis_data_uk", r"tennis-data\.co\.uk"),
 ("tennis_official", "ATP / WTA / ITF / Grand Slam official sites and rulebooks (draws, order of play, rankings, stats)", "free_scrape", "free", "high", "atp_site", r"atp/wta|atp and wta|atptour|wtatennis|itf|grand slam|slam official|slamtracker|itia|promoter announcements|atp/wta/itf"),
 ("tennis_abstract", "Tennis Abstract / Ultimate Tennis Statistics / Tennis Explorer", "free_scrape", "free", "medium", "tennis_abstract", r"tennis abstract|ultimate tennis|tennis explorer"),
 ("sportradar_hawkeye", "Sportradar / Hawk-Eye tennis feeds", "paid", "paid", "high", None, r"sportradar|hawk-eye"),
 # -- environment / geo
 ("openmeteo", "Open-Meteo (historical archive; historical-forecast API of past model runs)", "free_api", "free", "low", "openmeteo_histfc", r"open-meteo"),
 ("noaa_nws", "NOAA / NWS / Meteostat / ISD / GOES-R GLM / Open-Elevation / SRTM (observations and live forecasts)", "free_api", "free", "low", "nws_forecast", r"noaa|nws|national weather service|api\.weather\.gov|meteostat|goes-r|open-elevation|srtm|isd|arena coordinates|geodata"),
 ("weather_paid", "Commercial weather vendors (Tomorrow.io, NLDN/Vaisala)", "paid", "paid", "high", None, r"tomorrow\.io|vaisala|nldn|weather api vendors"),
 # -- markets / meta
 ("kalshi_api", "Kalshi public market-data API (markets, candles, trades, rules text)", "free_api", "free", "low", "kalshi_public", r"kalshi"),
 ("odds_paid", "Sportsbook odds history (The Odds API, SportsOddsHistory, vendor feeds, Betfair historical)", "paid", "paid", "high", "theoddsapi", r"the odds api|sportsodds|sportsbook|betfair|vendor feeds|odds columns|odds spreadsheets|prizepicks"),
 ("api_football", "API-Football / Fantasy Premier League API / Sleeper API (free tiers, request-limited)", "free_key", "free (key, request-limited)", "medium", None, r"api-football|fantasy premier league|fantasy\.premierleague|sleeper|rotowire|fantasylabs"),
 ("small_ratings_sites", "Haslametrics / UmpScorecards / other small free ratings sites", "free_scrape", "free", "medium", None, r"haslametrics|umpscorecards|team athletics sites|official team sites|team official|college position|college rosters|depth charts"),
 ("none_found", "NONE_FOUND: the catalog's own audit found no free source", "unavailable", "unavailable", "low", None, r"none_found|no free (cfb )?(personnel )?(feed|source)|not freely published|no free"),
 # -- generic
 ("wikipedia", "Wikipedia / Wikidata / league histories (awards, champions, draws, formats, manager lists)", "free_api", "free", "low", "wikipedia_api", r"wikipedia|wikidata|liquipedia|internet archive|wayback|league histories|hand-curated history|schedule archives"),
 ("news_press", "Press releases, news archives, beat reports, social posts, broadcaster archives, team websites, media-contract reporting", "free_scrape", "free", "medium", None, r"press|news|beat|insider|social|x/twitter|x and|ap/espn|ap coverage|nfl honors|coaching-change|public coaching|heisman trust|cfp committee|cfp ranking|college football playoff|ncaa football rules|ncaa/conference|conference availability|broadcast|team websites|media contract|manager press|forbes|sportico|straw polls|local .* press|network ad|closed captions|contestants|video"),
 ("own_capture", "Own timestamped capture (scrapers, feeds, polling) from now on", "own_capture", "free", "low", None, r"own (timestamped )?(point-in-time )?capture|own timestamped|own capture|own point-in-time|own-capture|hand-coded|hand coded|manual coding|contest video"),
 ("derived", "Derived from other catalog inputs / own model output", "derived", "free", "low", None, r"own computation|own model|derived from|own simulat|own rating|own season|from other catalog|upstream catalog|simulator output"),
 ("rules_docs", "Official rulebooks, regulations and static rule documents", "reference", "free", "low", None, r"rulebook|rules text|rules and glossary|official baseball rules|regulations|rule table|nba .* rules|official rules|format rules|tiebreaker|selection principles|league announcements|league press|public geography|market-size|fee schedule|help center"),
]

SOURCES = {}
for sid, name, kind, cost, tos, probe, rx in _S:
    SOURCES[sid] = {"id": sid, "name": name, "kind": kind, "cost": cost, "tos_risk": tos, "probe": probe, "_rx": re.compile(rx, re.I)}


def resolve(text: str) -> list[str]:
    """Canonical source ids named in a free-text catalog source string. Order of the registry is the priority; every match is returned."""
    t = (text or "").lower()
    hits = [sid for sid, s in SOURCES.items() if s["_rx"].search(t)]
    return hits


def public(sid: str) -> dict:
    return {k: v for k, v in SOURCES[sid].items() if not k.startswith("_")}
