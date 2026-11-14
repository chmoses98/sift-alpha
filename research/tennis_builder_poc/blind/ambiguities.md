# Ambiguities in blind_brief.md and choices made

1. game_id match_num formatting: integral values written as int ("1", not "1.0"); k is a per-(tour|tourney_id|match_num) cumcount in file order (after dropping rows).
2. Score tokens: flags matched exactly and case-sensitively ("W/O", "RET", "DEF", "ABD", "UNP"); a missing/empty score counts as bad (not completed). Empty tokens from double spaces ignored.
3. Completed: winner's set count = number of sets with a>b (winner-perspective score); loser set count not separately checked. A match with no sets is not completed. Missing best_of -> 3 (needed = 2).
4. Elo: only walkovers skip updates; RET/DEF/ABD/UNP/bad rows still update (literal). Elo update uses raw elo p (overall) and surface p (surface), not the combined r. Pre-match p/rating are still produced for walkovers.
5. Elo state is kept per tour (keys already contain the tour, so this is equivalent).
6. spw is defined only when sp, opp_rr and tour t are all defined (positive denominators); rows feeding sp/rr/t/neff are the valid-serve rows only. Formula used literally: spw = clip(sp + opp_rr - (1 - t)).
7. hru_neff: same valid-serve history (s_pts), window [d-730, d), hl 365. "No history" -> 0.
8. Set model: game g (0-based) is served by the set's first server when g is even; tiebreak point n (1-based) served by the first server when (n//2) is even (pattern S1,S2,S2,S1,S1,...). Tiebreak closed form applied at 6-6 within the tiebreak. pmf counts 6-6 sets as 13 games. The wmd pmf and hru p66 do not need the tiebreak; set_dist's set win uses the tiebreak with the node-level clipped A/B as point probabilities.
9. wmd per-match contribution uses spw/o_spw from the winner row (A = winner); pmf/mu/var are symmetric anyway. Cell key uses best_of with missing filled as 3. ΣSV==0 or empty window -> NaN overdisp.
10. wmd_form_sd: "fewer than 30 rows" refers to qualifying player rows in the tour window; mean() is a plain mean; variance is population-style (mean(dev^2) - mean(dev)^2 with binv subtracted).
11. pss obs_hold: NaN when SvGms <= 0 or missing, or when bpFaced/bpSaved missing. resid needs both spw and o_spw defined. Se/Ce/Sp/Cp use only rows with m defined; weighted count = Σw. cpi NaN when no event history (Ce = 0). Sp/Cp are 0 if the player has no rows at the event.
12. pss_beta uses each past row's own pre-match gx and y (y = won - p_win), window [d-730, d) unweighted, n counts rows with gx defined. adj_rating NaN if beta or cpi NaN.
13. set_dist: tau is the row's wmd_form_sd_pre (per tour, so same for both players). Best-of != 5 (incl. missing) treated as best-of-3. Calibration contribution per completed match taken from the winner row's P_k (P_k is symmetric in w/l). Empty calibration cell -> ratio 1 (cal = P). Calibration window/cell key: (tour, surface or "NA", best_of filled 3).
14. snc: favourite from Elo r (tie -> smaller key string). Features are computed per match from the favourite's perspective and given identically to both player rows (no flip for the underdog row). ebin from the match's p_fav (int truncation). Pool/cell counts are per state; f NaN if pool empty for that state; offsets NaN if either logit NaN. snc_n_pre = number of s1 contributions in the cell (0 if none), returned even when the pool is empty. s3_level offset kept for best-of-3; s4/s5 offsets NaN unless best_of == 5.
15. Window bounds everywhere: row_date - W <= d < row_date in calendar days (dates parsed from YYYYMMDD).
16. Gauss-Hermite: numpy hermegauss (probabilists'), weights normalised; product weights over 2-D grid.
