# Blind re-implementation brief: ten.tiebreak_sweep_joint_table (1 catalog input, 7 columns)

Data (read-only): `BLIND_DIR/tennis/atp_matches_<year>.csv.gz`, `wta_matches_<year>.csv.gz` (2000-2026; Sackmann) and `BLIND_DIR/holds.csv` (columns game_id, team, gps_hold_pre, gps_opp_hold_pre: the pre-match hold probabilities of the row's player and of the opponent, already verified; NaN where unavailable; two rows per match, 302,906 rows). Use only pandas/numpy. Do NOT read anything under /home/user or any repository clone. Implement from this text alone; RECORD every ambiguity you resolve.

## Universe and keys
Read every match file (sorted names, rows in file order), tour = file-name prefix. Drop rows with null tourney_date, winner_id or loser_id. date = tourney_date as YYYYMMDD (tournament START date). game_id = `"{tour}|{tourney_id}|{match_num}|{k}"` (match_num as integer; k = number of EARLIER rows (read order) with the same `"{tour}|{tourney_id}|{match_num}"` string). Player key `"{tour}:{id}"` (id as integer). Output two rows per match, (game_id, winner key) and (game_id, loser key); both rows of a match carry identical column values.
## Per-match quantities
mean_hold = (gps_hold_pre + gps_opp_hold_pre)/2 and gap = |gps_hold_pre - gps_opp_hold_pre| (from holds.csv; same for both rows; if either is NaN the match has no bin). A match has a bin only if mean_hold is not NaN and best_of is not null. bin = (floor(mean_hold/0.05 + 1e-9), floor(gap/0.05 + 1e-9), best_of as integer).
Outcome from `score` (the winner's games are listed first in every set): tokens split on spaces. The match is EXCLUDED from the counts (outcome undefined) if score contains any of RET, W/O, DEF, ABD, UNF, Default, '[' or 'nan', if there are no tokens, or if any token is not of the form `a-b` or `a-b(c)` (digits). Otherwise tb = 1 if any token carries a parenthesised tiebreak score `(c)`, else 0; sweep = 1 if in every token a > b (the winner won every set), else 0. A match that is excluded from the counts STILL receives table columns (it has a bin if its holds exist).
## Table as of a match
For a match m with a bin, N-counts n11 (tb=1,sweep=1), n10 (tb=1,sweep=0), n01 (tb=0,sweep=1), n00 (tb=0,sweep=0) are taken over matches with the SAME bin, a valid (non-excluded) outcome, and date STRICTLY EARLIER than m's date (same-date matches never count, in either tour order). Both tours are pooled (the tour is not part of the bin). N = n11+n10+n01+n00.
p_ij = (n_ij + 0.5)/(N + 2). pt = p_10 + p_11 (P(tiebreak)), ps = p_01 + p_11 (P(sweep)). w = N/(N+80). Shrunk cells: s11 = w p_11 + (1-w) pt ps; s10 = w p_10 + (1-w) pt (1-ps); s01 = w p_01 + (1-w) (1-pt) ps; s00 = w p_00 + (1-w) (1-pt)(1-ps). OR = s11 s00 / (s10 s01). se = sqrt(1/(n11+0.5)+1/(n10+0.5)+1/(n01+0.5)+1/(n00+0.5)).
## Columns
tbs_n = N; tbs_p_tiebreak = s10 + s11; tbs_p_sweep = s01 + s11; tbs_p_both = s11; tbs_odds_ratio = OR; tbs_or_lo = exp(ln OR - 1.96 se); tbs_or_hi = exp(ln OR + 1.96 se). When N = 0 (empty table) the last six columns are NaN (tbs_n = 0). Matches without a bin: all seven columns NaN.
NUMERICAL REQUIREMENT: 1e-9 relative, float64.
## Output
`BLIND_DIR/out/blind_tennis_tiebreak_sweep.csv` with game_id, team and the 7 columns (302,906 rows) and `BLIND_DIR/out/blind_tennis_tiebreak_sweep_notes.json` = {"ambiguities":[...]}. Report the ambiguities you resolved.
