# Blind re-implementation brief (Phase 6): NHL pre-game features, 2 catalog inputs, two output tables

You are an independent verifier. Re-implement every column below from THIS TEXT ALONE and write the two CSV files named at the end. Use only python with pandas / numpy / the standard library.

Data (read-only) under `D = /tmp/claude-0/-home-user/32225307-99da-5b07-99a7-4e3ae00b9c7e/scratchpad/blind/nhl/data/` (concatenate all season files of each kind):
`D/players/{team_states,goals,shots,players}_<season>.parquet`, `D/moneypuck/shots_<season>.parquet` (call the MoneyPuck files `mp`).
Hard rules: do NOT read, list or search anything under `/home/user`, any git repository, or any directory other than that data directory and your own working/output directory. Do not look for an existing
implementation. Where the text is ambiguous choose the most literal reading and RECORD the choice in `notes.json`.

## Common conventions
* date = `game_date` parsed as a date; season = the integer `season` column of the row's own table.
* `W(x; key)` for a row r (window sum): the sum of x over all rows of the SAME table with the same key value and the same season as r and a date STRICTLY BEFORE r's date, PLUS the sum of x over all rows
  with the same key value whose season equals r's season minus 1 (any date). NaN values of x count as 0. `W(x; league)` is the same without a key (all rows).
* `ratio(a, b)` = a / b when b > 0, else NaN. Any formula with a NaN input gives NaN.
* All arithmetic in float64.

# TABLE A: team-game long-change table (key game_id, team) -> `blind_nhl_lce.csv`
Universe: `team_states` rows, duplicates of (game_id, team_id) dropped (keep the first). team = team_id. venue = home if `is_home` is True else away.

Per row, events FOR the team in that game:
* `g_p2` / `g_reg`: number of rows of `goals` with this game_id and team_id, `period` in {1, 2, 3} and `empty_net` not equal to True (NaN counts as not True), restricted to period == 2 for g_p2. Missing = 0.
* `x_p2` / `x_reg`: from `mp`. Let MPG = the set of `nhl_game_id` values present anywhere in `mp` (before any filter). Keep mp rows with `period` in {1, 2, 3} and `shotOnEmptyNet` (NaN treated as 0) == 0.
  A shot belongs to the home side when `isHomeTeam` == 1. x_reg = sum of `xGoal` of the kept shots of this game (nhl_game_id == game_id) on the team's side (home side for a home row, away side for an away row);
  x_p2 = the same restricted to period == 2. If the game_id is not in MPG, x_p2 = x_reg = 0. Missing = 0.

For kind in {g, x} (output name `g` for goals and `xg` for xG), with p2 = `<kind>_p2`, reg = `<kind>_reg`:
* L = ratio(W(p2; league), W(reg; league)).
* For venue v in {home, away}: let sel = 1 for rows whose venue is v, else 0. T2 = W(p2 x sel; team), TR = W(reg x sel; team) (key = team; note the window still runs over ALL of the team's rows, with sel zeroing
  the other venue). m_v = ((T2 + 250 x L) / (TR + 250)) / L.
* Columns: `lce_<name>_mult_home_pre` = m_home, `lce_<name>_mult_away_pre` = m_away, `lce_<name>_ha_diff_pre` = m_home - m_away, `lce_<name>_mult_pre` = m_home if this row's venue is home else m_away.
Output columns: game_id, team, lce_g_mult_home_pre, lce_g_mult_away_pre, lce_g_ha_diff_pre, lce_g_mult_pre, lce_xg_mult_home_pre, lce_xg_mult_away_pre, lce_xg_ha_diff_pre, lce_xg_mult_pre (all universe rows).

# TABLE B: skater-game PK-structure table (key game_id, team = SKATER id) -> `blind_nhl_pk.csv`

## B1. Team-game PK table (internal)
Universe: `team_states`, duplicates of (game_id, team_id) dropped (keep first); opp = the other team_id of the same game_id. sec_sh = `sec_sh` as float.
From `shots` keep rows with `strength` == "PP" (the SHOOTING team is on the power play). Per shot: sog = 1 if `kind` in {SOG, GOAL}; att = 1 if kind in {SOG, GOAL, MISS}; ax = |x|;
pt = att x 1[zone == "O" and ax <= 54]; slot = att x 1[ax >= 69 and |y| <= 22] (no zone condition for slot; NaN coordinates make the condition false).
For a team-game row (team T, opponent O): sog, att, pt, slot = sums of those per-shot values over shots of this game whose `team_id` == O (shots the PK team T conceded). Missing = 0.
xga: let MPG = set of `nhl_game_id` values in `mp` (before filtering). PP shots in mp: rows where (isHomeTeam == 1 and homeSkatersOnIce > awaySkatersOnIce) or (isHomeTeam != 1 and awaySkatersOnIce > homeSkatersOnIce),
and shotOnEmptyNet (NaN -> 0) == 0 (compare skater counts as floats; a NaN comparison is false). For row T: xga = sum of xGoal of those PP shots in this game taken by the side that is NOT T's side
(T home -> shots with isHomeTeam != 1, i.e. away-side shooters; T away -> home-side shooters). If game_id not in MPG, xga = 0. Missing = 0. sh_mp = sec_sh if game_id in MPG else 0.
Window sums over this table, key = team (T): W(c; team) and W(c; league) for c in {sec_sh, sog, att, pt, slot, xga, sh_mp}. With Lx = W(x; league):
* lg_soga = 3600 x ratio(L_sog, L_sec_sh); lg_xga = 3600 x ratio(L_xga, L_sh_mp); lg_pt = ratio(L_pt, L_att); lg_slot = ratio(L_slot, L_att).
* pko_soga60 = 3600 x (W_sog + 7200 x lg_soga / 3600) / (W_sec_sh + 7200)
* pko_xga60 = 3600 x (W_xga + 7200 x lg_xga / 3600) / (W_sh_mp + 7200)
* pko_point_share = (W_pt + 150 x lg_pt) / (W_att + 150); pko_slot_share = (W_slot + 150 x lg_slot) / (W_att + 150)

## B2. Skater rows
Universe: `players` rows with `position` != "G", duplicates of (game_id, player_id) dropped (keep first). team (output key) = player_id. grp = "D" if position == "D" else "F".
toi_pp = `toi_pp_s` (NaN -> 0), sog_pp = `sog_pp` (NaN -> 0).
From `shots` keep strength == "PP" and kind in {SOG, GOAL, MISS}; per shot att = 1, pt = 1[zone == "O" and |x| <= 54]; per (game_id, shooter_id) sum att and pt; join to the skater row on (game_id, player_id); missing = 0.
Window sums over the skater table: P_c = W(c; key = player_id), G_c = W(c; key = grp) for c in {toi_pp, sog_pp, att, pt}.
* g_rate = ratio(G_sog_pp, G_toi_pp); g_pt = ratio(G_pt, G_att)
* `pp_sog60_pre` = 3600 x (P_sog_pp + 3600 x g_rate) / (P_toi_pp + 3600)
* `pp_point_share_pre` = (P_pt + 20 x g_pt) / (P_att + 20)
Join the opponent's B1 values: the skater's opponent in that game is the other team of the game (B1 row with game_id and team_id == the skater's opponent, i.e. the opp of the skater's own team row).
* `pko_soga60_pre`, `pko_xga60_pre`, `pko_point_share_pre`, `pko_slot_share_pre` = the opponent's pko_soga60, pko_xga60, pko_point_share, pko_slot_share; and take lg_soga, lg_pt from that same opponent row.
* `pko_combo_pp_sog60_pre` = pp_sog60 x (pko_soga60 / lg_soga) x [pp_point_share x (pko_point_share / lg_pt) + (1 - pp_point_share) x ((1 - pko_point_share) / (1 - lg_pt))]
Output columns: game_id, team, pko_soga60_pre, pko_xga60_pre, pko_point_share_pre, pko_slot_share_pre, pp_sog60_pre, pp_point_share_pre, pko_combo_pp_sog60_pre (all skater rows).

## Deliverables (in your working directory)
`blind_nhl_lce.csv`, `blind_nhl_pk.csv` (full float precision, e.g. `float_format="%.17g"`), `blind_impl.py` (your implementation), `notes.json` (every interpretation choice).
