# Blind brief: NBA batch 10 (stints + play-by-play), five pre-game inputs (13 value columns)

You get `data/espn_pbp/pbp_games_<season>.parquet`, `pbp_events_<season>.parquet` and `stints_<season>.parquet` for seasons "2024-25" and "2025-26". Write your own implementation
from this text only and write `out.csv` with one row per (game_id, player) and the columns under Output (empty cell = missing). float64. Do not look for any other implementation.

## 1. Games, events, stints
* Games: pbp_games rows with status_completed == True (first row per game_id). date = start_time_utc converted to America/New_York, calendar date. Clubs: home_team_id, away_team_id.
  season label = the `season` column (e.g. "2024-25"); the output season = int(first four characters) + 1.
* Events: pbp_events rows of kept games. Player ids (p1, p2) are integers (negative values are normal). For an event: tt = type_text.
  - FG attempt: shooting_play true and tt does not start with "Free Throw". made: scoring_play true. made three: a made FG attempt with score_value == 3.
  - assisted made FG: a made FG attempt with p2 present (p2 = assister).
  - live FT miss: tt in {"Free Throw - 1 of 1", "Free Throw - 2 of 2", "Free Throw - 3 of 3"} and scoring_play false.
  - miss = FG attempt not made, or a live FT miss. Rebounds: tt == "Offensive Rebound" (oreb) / "Defensive Rebound" (dreb); a team rebound is one with p1 missing.
  - points of an event = score_value when scoring_play is true, else 0. Missing booleans are false.
  - the event's club = its team_id.
* Stints: an event belongs to the stint of its game with start_order <= order < end_order (stints of a game do not overlap). Only stints with certified == true are used
  for on-court quantities; events in uncertified stints (or in none) are ignored there.

## 2. Player stint games (history)
For each certified stint and each side (home, away): club = that side's team id, opponent = the other; on-court players = the side's p1..p5 that are present; poss = the side's
`*_poss`; seconds = `seconds`. Over the stint's events: tm_fgm / tm_ast_fgm = made / assisted made FG attempts whose club is the side's club; own_miss = misses of the club; opp_miss = misses of
the opponent. For each on-court player: oreb, dreb, pts = sums over the stint's events with p1 == the player; ast = number of the stint's made FG attempts with p2 == the player.
Sum everything per (game, player, club): a "stint game" with sec, poss, tm_fgm, tm_ast_fgm, own_miss, opp_miss, oreb, dreb, pts, ast.
A player's stint games are ordered by (date, game_id, club). EWM sums with half-life 25: W(x) at stint game i = sum over j <= i of 0.5 ** ((i - j) / 25) x_j; a row reads the values after his
last stint game dated strictly before the row's date (missing if none).

## 3. Rows
* Team-games: each kept game gives (club = home, opp = away) and (club = away, opp = home); a club's games are ordered by (date, game_id).
* For each team-game (g, T) dated d: prev = T's last 5 team-games dated strictly before d. Candidates = players with a stint game for club T in those games; q = the latest date of those.
  A player who is a candidate for both clubs keeps the one with the larger q (equal: smaller club id). One row per (g, player): team = player id, pteam = T, opp = the opponent.
* League ratios at a date d: over ALL stint games dated strictly before d: L_share = sum ast / sum tm_ast_fgm; L_or = sum oreb / sum own_miss; L_dr = sum dreb / sum opp_miss;
  L_pts = sum pts / sum poss; L_reb = sum (oreb + dreb) / sum poss; L_ast = sum ast / sum poss (missing if the denominator is 0).

## 4. Columns
nba.on_court_assist_share:
* ocas_share_pre = (W(ast) + 300 L_share) / (W(tm_ast_fgm) + 300).
* ocas_tm_ast_fgm_per48_pre = 2880 W(tm_ast_fgm) / W(sec) (missing if W(sec) <= 0).
* ocas_exp_ast_pre = ocas_share_pre * ocas_tm_ast_fgm_per48_pre * (W(sec) / W(1) / 60) / 48.

nba.pairing_adjusted_reb_share: prs_oreb_pct_pre = (W(oreb) + 200 L_or) / (W(own_miss) + 200); prs_dreb_pct_pre = (W(dreb) + 200 L_dr) / (W(opp_miss) + 200).

nba.lineup_conditional_component_rates: lcr_pts100_pre = 100 (W(pts) + 400 L_pts) / (W(poss) + 400); lcr_reb100_pre likewise with W(oreb) + W(dreb) and L_reb; lcr_ast100_pre with W(ast), L_ast.

nba.assisted_three_passer_map (made threes of ALL kept games' events, certified stint or not, with p1 present; shooter = p1):
* Window of a row (season label S, date d): made threes in games dated strictly before d whose game's season label is S or the label just before S (if any).
* For the row's player: tot = his made threes in the window; n_s = those with p2 present; n_sp = those assisted by passer p.
* atp_assisted3_share_pre = n_s / tot (missing if tot = 0).
* For each passer p: club_p = the club (event team_id) of the latest (by date, game_id, order) assisted made three in the window that p assisted; q_p = (assisted made threes in the window with
  club club_p and passer p) / (assisted made threes in the window with club club_p).
* atp_top_passer_share_pre = max over the player's passers p of (n_sp + 40 q_p) / (n_s + 40) (missing if tot = 0 or n_s = 0).

nba.creditable_rebound_pool (club level; every row of club T gets the same values):
* Per team-game (over ALL events of the game, any stint): misses = the club's misses; team_reb = team rebounds whose club is the club (0 if no events); g_miss = misses of both clubs; g_treb = team rebounds of
  both clubs.
* Club EWM with half-life 40 over its team-games ordered (date, game_id); a row reads the club's value after its last team-game dated strictly before d.
* crp_proj_misses_pre = W(misses)/W(1) of T + W(misses)/W(1) of the opponent.
* crp_leakage_pre = 0.5 * (W(g_treb)/W(g_miss) of T + W(g_treb)/W(g_miss) of the opponent) (each ratio missing if W(g_miss) <= 0).
* crp_pool_pre = crp_proj_misses_pre * (1 - crp_leakage_pre).

## Output
`out.csv`: game_id, team (= player id, integer), then ocas_share_pre, ocas_tm_ast_fgm_per48_pre, ocas_exp_ast_pre, prs_oreb_pct_pre, prs_dreb_pct_pre, lcr_pts100_pre, lcr_reb100_pre,
lcr_ast100_pre, atp_assisted3_share_pre, atp_top_passer_share_pre, crp_proj_misses_pre, crp_leakage_pre, crp_pool_pre. Floats '%.17g'.
Also write `notes.json` = {"ambiguities": [every place where you had to guess]}.
