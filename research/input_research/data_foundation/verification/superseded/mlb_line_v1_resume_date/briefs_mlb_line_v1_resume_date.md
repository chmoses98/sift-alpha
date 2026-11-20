# Blind brief: MLB linescore and starter-workload inputs (20 value columns)

Data: `/tmp/raw/MLB2022`, `/tmp/raw/MLB2023`, `/tmp/raw/MLB24`, `/tmp/raw/MLB2025`, `/tmp/raw/MLB2026` (`*.json`, one compact game feed per game; ignore names starting with "_"). If a game id occurs twice keep the first.

## Games (parse per file j)
Keep the game only if j.game.type is one of R, F, D, L, W, j.status.codedGameState == "F", and j.linescore.innings has at least 5 entries. game_id = int(j.pk); season = int(j.game.season);
date = j.datetime.resumeDate if that key is present and non-empty, else j.datetime.officialDate; team id = int(j.teams.home.id) / int(j.teams.away.id); ne = 1 always.
Runs by inning: for inning entry x, home runs = x.home.runs and away runs = x.away.runs (a missing side or missing/null runs = 0). Per side: r1 = runs in the first entry; r5 = runs in the first five entries;
r = runs over all entries; late = r - r5. n_inn = number of inning entries. walkoff = 1 if (home r > away r) and (home r minus home runs in the LAST entry <= away r), else 0.
Starter line per side (side = home / away): pid = j.box[side].pitchers[0]; pit = the `pit` object of the entry of j.box[side].players whose id == pid; outs = pit.outs, bf = pit.battersFaced, np = pit.numberOfPitches.
If any of this is unavailable for either side, outs, bf and np are missing for both sides.

## Ridge targets (Method R with LAM = 10, HL = 30); for the starter targets the "offence" side is the team whose starter it is
run = r; r1; r5; late; outs; bf; np.
For a team row T against O: x_tot = ep_run(T) + ep_run(O); x_hmar = ep_run(home team of the game) - ep_run(away team of the game) (same value on both rows of a game).

## Columns (own = the row's team, opp = its opponent)
Direct ridge columns: fi_exp_pre = ep_r1(T); f5_exp_pre = ep_r5(T); f5_late_exp_pre = ep_late(T); spw_outs_pre = ep_outs(T); spw_bf_pre = ep_bf(T); spw_np_pre = ep_np(T).
Kernel on fi_exp_pre, bw 0.04:  fi_score_pre = P(own r1 > 0).
Kernel on ep_r1(T) + ep_r1(O), bw 0.06:  fi_nrfi_pre = P(own r1 + opp r1 == 0).
Kernel on ep_r5(T) - ep_r5(O), bw 0.25:  f5_lead_pre = P(own r5 > opp r5);  f5_tie_pre = P(own r5 == opp r5).
Kernel on two dimensions (x_hmar with bw 0.4, x_tot with bw 0.5):  wo_walkoff_pre = P(walkoff == 1);  wo_extras_pre = P(n_inn > 9).
Kernel on spw_bf_pre, bw 0.5:  hook_ge{k}_pre = P(own starter bf >= k) for k = 18, 21, 24, 27  (event missing when bf is missing).
Kernel on spw_outs_pre, bw 0.4:  exb_ge{k}_pre = P(own starter outs >= k) for k = 15, 16, 18, 19  (event missing when outs is missing).

## Method R: walk-forward ridge (used for every "ridge target" below)
Order the Games by (date, game_id). Teams = every team id appearing in the Games. All games on the same date d share one fit:
* S = the largest season among the games on d. Pool = every game dated strictly before d with season >= S-1, in (date, game_id) order. If the pool has fewer than 16 games, every ridge value is missing for games on d.
* rank(team, pool game) = the number of LATER pool games (later in pool order) in which that team plays (0 = the team's most recent pool game). rk = min(rank of home team, rank of away team).
  Ranks are always counted over the whole pool, also when a target is missing in some pool games. Weight w = 0.5 ** (rk / HL).
* For a target with per-side values (y_home, y_away): keep the pool games where both values are present (if fewer than 16 are kept, that target is missing on d). Each kept game gives two observations with
  weight w: (offence = home team, defence = away team, y = y_home, I = ne) and (offence = away team, defence = home team, y = y_away, I = 0). ne = 0 for a neutral-site game, else 1.
* Weighted ridge y ~ b0 + a[offence] + d[defence] + h * I. Penalty: add LAM to the diagonal for every a and every d coefficient; nothing for b0 and h. Solve (Z'WZ + P) b = Z'Wy.
* For a game on d with home team H and away team V: ep(H) = b0 + a[H] + d[V] + ne * h;  ep(V) = b0 + a[V] + d[H];  off(X) = b0 + a[X];  def(X) = b0 + d[X].

## Method K: season-walk-forward kernel (used for every "kernel" column below)
Team rows = two rows per game (one per team). For a team row of season s with conditioning values x (one or more dimensions, each with a bandwidth bw):
* The reference rows are the team rows of seasons strictly earlier than s whose conditioning values are all present, further limited to rows where the event value v is present
  (and, where a condition is stated, where the condition is true). If there are fewer than MIN_REF such rows (150 where a condition is stated, else 500) the column is missing for season s.
* k_i = exp(-0.5 * sum over dimensions of ((x_i - x) / bw) ** 2);  value = sum(k_i * v_i) / sum(k_i)  (missing if the row's own x is missing or sum(k_i) is 0).
* "P(event)" means v = 1 if the event is true else 0; "E[quantity]" means v = the quantity.

Use float64 throughout. Write `out.csv` with one row per (game_id, team), columns game_id, team and exactly the value columns named below (empty cell = missing). Also write `notes.json` =
{"ambiguities": [every place where you had to guess]}. Write your own implementation from this text only. Do not look for or read any other implementation or repository.
