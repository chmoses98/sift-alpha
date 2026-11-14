"""Builds provider_catalog.json from provider_pricing_20261114.json plus hand-curated mappings (RESEARCH_ONLY).

    python research/provider_licensing/build_provider_catalog.py

The planning price for each provider is the tier this research would actually need (for example historical odds need a paid tier),
not the cheapest tier. Prices keep the status recorded in the pricing file: VERIFIED only when read on the provider's own page.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
P = json.loads((HERE / "provider_pricing_20261114.json").read_text())
BY = {p["provider"]: p for p in P}
C = []


def ev(name, i):
    return BY[name]["tiers"][i]["evidence"]


def price(tier, monthly=None, annual=None, status="ESTIMATE", evidence=""):
    return dict(tier=tier, monthly_usd=monthly, annual_usd=annual, status=status, evidence=evidence)


def add(id, name, sources=(), datasets=(), sports=(), fields="", plan=None, quota=None, est=None, pit="", identity="", complexity="MEDIUM", action="", role="PRIMARY"):
    p = BY[name]
    C.append(dict(id=id, name=name, source_ids=list(sources), datasets=list(datasets), sports=list(sports), fields=fields, price=plan, quota=quota,
                  est_requests=est, pit=pit, identity=identity, complexity=complexity, recommended_action=action, role=role,
                  url=p.get("url_pricing"), terms_url=p.get("url_terms"), history=p.get("historical_depth"), latency=p.get("update_latency"),
                  terms_summary=p.get("personal_research_terms"), redistribution=p.get("redistribution_allowed"),
                  commercial_license_needed=p.get("commercial_requires_separate_license"), all_tiers=p["tiers"], research_notes=p.get("notes")))


K = "KenPom"
add("kenpom", K, ["kenpom"], ["cbb.ratings_kenpom"], ["CBB"], "Adjusted efficiency, tempo, four factors; API with historical ratings snapshots",
    price("API access (web included)", annual=95.0, evidence=ev(K, 1)), "API key, personal use", "one bulk call per season-date for an archive pull",
    "Daily archive snapshots give point-in-time ratings", "KenPom team names; crosswalk to ESPN team ids needed", "LOW",
    "Buy only if Bart Torvik (free) proves insufficient on the CBB challenger")
B = "Bart Torvik (barttorvik.com) + cbbdata API"
add("barttorvik", B, ["barttorvik"], ["cbb.ratings_barttorvik"], ["CBB"], "T-Rank team/player tables, time-machine daily ratings, game-level box stats",
    price("cbbdata API key (free)", monthly=0, status="VERIFIED", evidence=ev(B, 0)), "free key", "bulk CSV per season",
    "Time-machine ratings are point-in-time by date", "Torvik team names; crosswalk needed", "LOW",
    "Acquire first for CBB ratings: free and point-in-time; host blocked from this runner, so run locally through cbbdata")
add("evanmiya", "EvanMiya", ["epm_darko"], [], ["CBB"], "CBB player/team ratings, lineup data", price("Premium", status="UNKNOWN", evidence="no pricing found"),
    None, None, "", "", "MEDIUM", "Price unknown; not needed before the KenPom/Torvik comparison", role="ALTERNATIVE")
F = "CollegeFootballData.com API (CFBD) / CollegeBasketballData"
add("cfbd", F, ["cfbd"], [], ["CFB", "CBB"], "Games, drives, plays, PPA/EPA, recruiting, betting lines, ratings, rosters; CBB API with games/plays/lines",
    price("Patreon Tier 2 (30k calls/month)", monthly=5, evidence=ev(F, 3)), "Free 1,000 calls/month; Patreon $1/5k, $5/30k, $10/75k, $15/125k",
    "10-season play backfill ≈ 15 seasons × 17 weeks ≈ 2.5k calls; lines/ratings a few hundred", "Lines are closing snapshots; plays event-time",
    "CFBD team/athlete ids", "LOW", "Start on the free tier; $5/month only if the backfill exceeds 1,000 calls")
O = "The Odds API"
add("odds_api", O, ["odds_paid"], ["mkt.external_odds"], ["NBA", "CBB", "NHL", "NFL", "CFB", "MLB", "SOCCER", "TENNIS"],
    "Sportsbook moneyline/spread/total/props snapshots; historical snapshots endpoint",
    price("20K credits/month (historical needs a paid tier)", monthly=30, evidence=ev(O, 1)), "500 free credits; historical calls cost more credits (third-party: 10×)",
    "a season of NBA closing lines ≈ 1,300 games × 10 credits ≈ 13k credits", "Timestamped snapshots: point-in-time by design", "Team names only", "MEDIUM",
    "Optional, for market benchmarks only (market prices are excluded from prediction inputs)")
S = "SportsDataIO"
add("sportsdataio", S, [], ["nba.box_history_long", "nba.pbp_history_long", "nhl.officials", "cbb.officials", "nhl.injuries"],
    ["NBA", "NFL", "NHL", "CBB", "CFB", "MLB", "SOCCER"], "Scores, box, play-by-play, projections, injuries, odds (product dependent)",
    price("Discovery Lab paid plan (personal, non-commercial)", monthly=99, annual=599, evidence=ev(S, 2)), "trial / Discovery Lab", "bulk per season",
    "Live injury/lineup feeds; historical point-in-time snapshots not confirmed", "SportsDataIO ids", "MEDIUM",
    "Hold: broad, but priced above our free archives", role="ALTERNATIVE")
R = "Sportradar"
add("sportradar", R, ["sportradar_hawkeye", "opta_commercial"], ["ten.tracking_commercial", "soc.opta_commercial", "nba.tracking"],
    ["NBA", "NFL", "NHL", "CBB", "CFB", "MLB", "SOCCER", "TENNIS"], "Official league feeds, tracking (sport dependent)",
    price("Production", status="UNKNOWN_ENTERPRISE", evidence=ev(R, 1)), "30-day trial", None, "Official live feeds", "Sportradar ids", "HIGH",
    "Defer: enterprise pricing; only after a model shows a validated gain", role="ALTERNATIVE")
D = "BALLDONTLIE API"
add("balldontlie", D, [], ["nba.box_history_long", "nba.pbp_history_long"], ["NBA", "NFL", "NHL", "MLB"],
    "Games, box scores, season averages; play-by-play, injuries and odds on higher tiers", price("ALL-STAR (per league)", monthly=9.99, evidence=ev(D, 1)),
    "60 req/min (ALL-STAR), 600 req/min (GOAT)", "NBA box history ≈ 1–2k paged calls", "Final box scores (event time); injuries live only",
    "balldontlie ids; crosswalk needed", "LOW", "Cheap fallback if ESPN/NBA archive rights or depth fall short", role="ALTERNATIVE")
add("mysportsfeeds", "MySportsFeeds", [], [], ["NBA", "NFL", "NHL", "MLB"], "Scores, box, play-by-play, lineups",
    price("Non-commercial", status="UNKNOWN", evidence="pricing not published"), None, None, "", "", "MEDIUM", "Price unknown", role="ALTERNATIVE")
E = "Evolving-Hockey"
add("evolving_hockey", E, ["nst"], ["nhl.ratings_external"], ["NHL"], "RAPM, GAR/WAR, xG models, line combinations", price("Standard", monthly=5, evidence=ev(E, 0)),
    "web/CSV", "season CSV exports", "Season-level; daily point-in-time only if snapshotted", "Player names + NHL ids", "LOW",
    "Cheap; buy only if the NHL challenger needs external ratings beyond archive xG")
add("nst", "Natural Stat Trick", ["nst"], [], ["NHL"], "On-ice shot metrics, xG, line stats by game", price("Website", monthly=0, evidence=ev("Natural Stat Trick", 0)),
    None, "game-level pages", "Game-level, event-time", "NHL ids", "MEDIUM", "Free; host blocked from this runner; terms not found", role="ALTERNATIVE")
add("moneypuck", "MoneyPuck", ["moneypuck"], ["nhl.shots_xy"], ["NHL"], "Shot-level data with xG 2007+, player/goalie/team season data",
    price("Data downloads", monthly=0, evidence=ev("MoneyPuck", 0)), None, "one CSV per season", "Event-time shots", "NHL ids", "LOW",
    "Free bulk shots; partly covered by the NHL archive")
PF = "PFF (PFF+ / Premium Stats / PFF Pro)"
add("pff", PF, ["pff_sis"], ["cfb.pff_charting"], ["NFL", "CFB"], "Player grades, charting (pressures, coverage, routes)",
    price("PFF+ annual (includes Premium Stats)", annual=99.99, evidence=ev(PF, 1)), "web only", "manual export", "Weekly grades (post-game)", "PFF ids", "MEDIUM",
    "Consumer web product, not a data licence; defer")
SH = "Stathead (Sports Reference)"
add("stathead", SH, ["sports_reference", "bbref", "pfr", "bbref_baseball"], [], ["NBA", "NFL", "NHL", "CBB", "CFB", "MLB"],
    "Query tools over Sports-Reference history (game logs, splits, coaching, awards)", price("All Sports", monthly=16, annual=160, evidence=ev(SH, 1)),
    "web queries", "manual", "Historical, event-time", "Sports-Reference ids", "MEDIUM",
    "Web tool, not a data licence; SR terms forbid building tools from scraped data. Manual lookups only", role="ALTERNATIVE")
FG = "FanGraphs membership"
add("fangraphs", FG, ["fangraphs"], ["mlb.leaderboards_external", "mlb.projections_vintages"], ["MLB"], "Leaderboards, projections, RosterResource",
    price("Yearly", annual=80, evidence=ev(FG, 1)), "web/CSV export", "season exports", "Projection vintages only via forward capture",
    "FanGraphs ids + Chadwick crosswalk", "LOW", "P2 sport; defer")
OA = "Odds archives: SportsOddsHistory / OddsPortal / Sportsbook Review"
add("odds_archives", OA, [], ["mkt.external_odds"], ["NBA", "NFL", "NHL", "CBB", "CFB", "MLB"], "Historical closing lines",
    price("SportsOddsHistory (free, attribution)", monthly=0, evidence=ev(OA, 0)), None, None, "Closing lines only", "Team names", "MEDIUM",
    "Free closing lines for benchmarks; OddsPortal terms ban scraping", role="ALTERNATIVE")
AF = "API-Football (api-sports.io)"
add("api_football", AF, ["api_football"], ["soc.player_stats_lineups"], ["SOCCER"], "Fixtures, lineups, player stats, events, odds",
    price("Pro", monthly=19, evidence=ev(AF, 1)), "100/day free; 7,500/day Pro", "one league-season ≈ 380 fixtures × 3 endpoints", "Lineups ~1h pre-match",
    "api-sports ids", "LOW", "P2; consider the $19 tier when soccer work begins")
add("football_data_org", "football-data.org", ["football_data_org"], [], ["SOCCER"], "Fixtures, results, standings",
    price("Free", monthly=0, evidence=ev("football-data.org", 0)), "10 calls/min, 12 competitions", None, "", "football-data ids", "LOW", "Free tier is enough for results")
add("statsbomb_open", "StatsBomb Open Data", ["statsbomb_open"], [], ["SOCCER"], "Event data for selected competitions",
    price("Open data", monthly=0, status="VERIFIED", evidence=ev("StatsBomb Open Data", 0)), None, "git clone", "Event-time", "StatsBomb ids", "LOW", "Free; limited competitions")
OM = "Open-Meteo / Meteostat"
add("open_meteo", OM, ["openmeteo", "noaa_nws"], [], ["NFL", "CFB", "MLB", "SOCCER"], "Historical weather; historical forecasts (past model runs)",
    price("Open-Meteo non-commercial", monthly=0, evidence=ev(OM, 0)), "10,000 calls/day non-commercial", "one call per venue-day",
    "Historical-forecast API gives forecasts as issued (point-in-time)", "Venue lat/long", "LOW", "Free for research; commercial use needs a plan")
add("kalshi_api", "Kalshi API", ["kalshi_api"], [], ["NBA", "CBB", "NHL", "NFL", "CFB", "MLB", "SOCCER", "TENNIS"], "Markets, candles, trades, settlement",
    price("API access", monthly=0, evidence=ev("Kalshi API", 0)), "rate limited", None, "Timestamped", "Kalshi tickers", "LOW",
    "Evaluation/settlement only; redistribution clause unread")
add("nflverse", "nflverse", ["nflverse"], [], ["NFL"], "Play-by-play 1999+, EPA, participation, rosters, injuries, snap counts",
    price("Open data", monthly=0, status="VERIFIED", evidence=ev("nflverse", 0)), None, "release downloads", "Event-time; injuries weekly", "gsis ids + crosswalks", "LOW",
    "Free and already used")
add("sackmann", "Jeff Sackmann tennis data", ["sackmann"], [], ["TENNIS"], "ATP/WTA match results, serve stats, rankings",
    price("Open data", monthly=0, evidence=ev("Jeff Sackmann tennis data", 0)), None, "git clone", "Event-time", "Sackmann player ids", "LOW",
    "Already archived; CC BY-NC-SA; upstream repo returned 404 on 2026-11-14")
UK = "tennis-data.co.uk / football-data.co.uk"
add("uk_data", UK, ["tennis_data_uk", "football_data_uk"], [], ["TENNIS", "SOCCER"], "Results with closing odds", price("Free downloads", monthly=0, evidence=ev(UK, 0)),
    None, "one CSV per season", "Closing odds", "Names only", "LOW", "Free; terms not found")
SY = "Synergy Sports / Second Spectrum"
add("synergy", SY, ["cleaning_the_glass"], ["nba.playtype_scheme", "nba.tracking", "cbb.shot_tracking_scheme"], ["NBA", "CBB"], "Play types, tracking",
    price("Synergy", status="UNKNOWN_ENTERPRISE", evidence=ev(SY, 0)), None, None, "", "", "HIGH", "Defer; enterprise", role="ALTERNATIVE")
add("cleaning_the_glass", "Cleaning the Glass", ["cleaning_the_glass"], ["nba.playtype_scheme"], ["NBA"], "Garbage-time-filtered team/player stats, lineup data",
    price("Membership", status="UNKNOWN", evidence="price not found"), None, None, "", "", "LOW", "Price unknown; verify before deciding")
TP = "Tennis point data: Match Charting Project / Hawk-Eye / Sportradar"
add("tennis_points", TP, ["sportradar_hawkeye"], ["ten.tracking_commercial"], ["TENNIS"], "Point-by-point charting (volunteer) / ball tracking (commercial)",
    price("Match Charting Project", monthly=0, evidence=ev(TP, 0)), None, None, "", "", "MEDIUM", "Free charting covers a sample; Hawk-Eye is enterprise", role="ALTERNATIVE")

OUT = dict(schema="sift-provider-catalog/1", status="RESEARCH_ONLY", checked_utc="2026-11-14",
           notice=("Hand-curated from provider_pricing_20261114.json. Only free open-data sources whose official pages were read are VERIFIED: provider websites "
                   "were unreachable from the research environment, so paid prices are ESTIMATE from search snippets (official-page snippet or third party, see "
                   "evidence). Re-check on the provider's page before any purchase. A subscription does not grant redistribution or commercial rights."),
           planning_price_rule="price = the tier this research would need, not the cheapest tier", providers=C)
(HERE / "provider_catalog.json").write_text(json.dumps(OUT, indent=1) + "\n")
print(len(C), "providers")
