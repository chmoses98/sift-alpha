# Blind brief: MLB batch 11, first-inning Markov chain (one input, 2 value columns)

You get `data/feeds/<season>/<gamePk>.json` for seasons 2022-2026 (MLB Stats API game feeds, compacted). Write your own implementation from this text only and write `out.csv` with one row
per (game_id, team) and the columns under Output. float64. Do not look for any other implementation.

Sections 1-2 of the APPENDIX define games, chronology (avail), plate appearances (PAs), batting / fielding team, is_start and bf_i. Use them exactly.

## A. Outcome class of a PA (and its inning)
inn = the play's `inn` value as an integer (missing -> 0).
W = walk, intent_walk, hit_by_pitch, catcher_interf; S1 = single, field_error; XB = double, triple; HR = home_run; K = strikeout, strikeout_double_play; O = any other event.

## B. Rows and windows
* Rows: each kept game gives (team = home, opp = away) and (team = away, opp = home); output rows are those of season >= 2023. S = the row's season, d = its date.
* Window of a row: PAs with avail < d and season >= S - 1.
* Batting set of the row: window PAs with inn == 1 whose batting team is the row's team. N_b = count, n_b(c) = count of class c.
* Pitching set: window PAs with is_start true and bf_i <= 9 whose FIELDING team is the row's opponent. N_p, n_p(c).
* League shares of season S - 1: lb(c) = share of class c among ALL PAs of season S - 1 with inn == 1; lp(c) = share among ALL PAs of season S - 1 with is_start and bf_i <= 9.

## C. Probabilities
b(c) = (n_b(c) + 250 lb(c)) / (N_b + 250); p(c) = (n_p(c) + 300 lp(c)) / (N_p + 300); q(c) = b(c) p(c) / lb(c), then divide every q(c) by the sum over the six classes.

## D. Chain (half-inning of the row's team batting)
State = (outs, runners on 1st / 2nd / 3rd); start = 0 outs, bases empty. Transitions per PA:
* K or O: one more out, runners stay. Three outs ends the half-inning.
* W: batter to 1st; runners move only when forced (1st -> 2nd if 1st occupied, 2nd -> 3rd if 1st and 2nd occupied, 3rd scores if loaded).
* S1: batter to 1st and every runner moves up exactly one base (a runner on 3rd scores).
* XB: batter to 2nd and every runner scores.
* HR: batter and every runner score.
P(no run) = the probability of reaching three outs before any run scores (compute exactly; a no-run path has at most 9 PAs).

## E. Columns
* fim_p_score_pre = 1 - P(no run) of the row.
* fim_p_nrfi_pre = P(no run) of the row x P(no run) of the opponent's row in the same game.

## Output
`out.csv`: game_id, team, fim_p_score_pre, fim_p_nrfi_pre for every row of season >= 2023. Floats '%.17g'. Also write `notes.json` = {"ambiguities": [...]}.

# APPENDIX (from the batch 7 brief)
### 1. Games
* Read every file whose name does not start with "_", seasons in increasing order and files sorted by name. Keep a game only if game.type is one of R, F, D, L, W and
  status.codedGameState == "F" (and the keys used below exist). If a game_id (= pk) occurs twice keep the first.
* season = int(game.season). date = datetime.officialDate (the FIRST-PITCH date). avail = datetime.resumeDate if that key is present and non-empty, else officialDate
  (the date the result became known; later than date for suspended games).
* home = teams.home.id, away = teams.away.id. h_r = sum over linescore.innings of home.runs (missing -> 0); a_r likewise for away.
* home_sp = box.home.pitchers[0], away_sp = box.away.pitchers[0] (missing if absent): the game's actual starting pitchers. They are used ONLY for history (earlier games).
* **History rule.** A row (game g, date d) may use a game G only if avail(G) < d (strictly). Nothing of g itself is used.

### 2. Plate appearances (PAs)
* Iterate `plays` of each kept game in order. Skip a play if `event` is not a string, or starts with any of: caught_stealing, pickoff, stolen_base, wild_pitch, passed_ball,
  balk, other_advance, other_out, runner, defensive_indiff, game_advisory, ejection; or if `bat` or `pit` is missing. Every other play is a PA.
* Fields: ab (int), half ("top" means the away team bats), bat, pit, throws (pitcher hand "R"/"L"), event. Pitch codes = `code` of each element of `pitches`.
  n_pitch = number of pitch elements; called = number of code "C"; whiff = number of codes in {S, W, T, M, Q}; swing = number of codes in {S, W, T, M, Q, F, L, O, X, D, E}; csw = called + whiff.
* Batting team = away if top else home; fielding team = the other. The PA's season / date / avail are its game's.
* k = 1 if event in {strikeout, strikeout_double_play}; bb = 1 if event in {walk, intent_walk}.
* wOBA: num = 0.69 walk, 0.72 hit_by_pitch, 0.88 single, 1.25 double, 1.58 triple, 2.03 home_run, else 0; den = 1 unless event in {intent_walk, sac_bunt, catcher_interf} (then 0).
* is_start = the PA's pitcher equals the fielding team's starter of that game (home_sp when top, else away_sp).
* bf_i = 1, 2, ... = the PA's position among the PAs of the same (game, pitcher), ordered by ab. tto = min(ceil(bf_i / 9), 3).

