# Blind brief: NHL period inputs from daily score files (16 value columns)

Data: `/tmp/raw/NHL/*.json` (one file per date; ignore names starting with "_"), processed in file-name order. Each has a `games` list.

## Games
Keep a game x if x.gameType is 2 or 3, x.gameState is "OFF" or "FINAL", and x has a `goals` list. If a game id occurs twice keep the first. game_id = int(x.id); season = the first four digits of x.season as an integer;
date = x.gameDate; team = x.home.abbrev / x.away.abbrev (strings, used as-is); ne = 0 if x.neutralSite is true else 1.
Period goals: for each goal with periodDescriptor.periodType == "REG" and period in (1, 2, 3), add one to that period for the home team if goal.teamAbbrev == x.home.abbrev, otherwise for the away team.
p1, p2, p3 = own goals by period; o1, o2, o3 = opponent's; c_k = p_k + o_k.

## Ridge target (Method R with LAM = 8, HL = 20)
g = regulation goals = p1 + p2 + p3. For a team row T against O: x_g = ep(T); x_mar = ep(T) - ep(O); x_tot = ep(T) + ep(O).
Standard error (one value per game, same for both rows): over the fitted observations, r = y - fitted value, s2 = sum(w r^2) / sum(w). c = (design row of the game's home observation) + (design row of its away
observation), i.e. 2 on b0, 1 on each of a[H], d[V], a[V], d[H], and ne on h. se = sqrt(s2 * c' (Z'WZ + P)^-1 c). (Teams absent from the pool keep their penalty-only diagonal LAM.)

## Columns
spu_total_pre = x_tot;  spu_se_pre = se.
Kernel on x_mar, bw 0.35:  pes_lead_p2_pre = P(p1 > o1);  pes_tie_p2_pre = P(p1 == o1);  pes_lead_p3_pre = P(p1 + p2 > o1 + o2);  pes_tie_p3_pre = P(p1 + p2 == o1 + o2).
Kernel on x_g, bw 0.25, with a condition:  pes_p3_gf_lead_pre = E[p3], condition p1 + p2 > o1 + o2;  pes_p3_gf_tie_pre = E[p3], condition equal;  pes_p3_gf_trail_pre = E[p3], condition p1 + p2 < o1 + o2.
Kernel on x_g, bw 0.25:  ppc_mu_p{k}_pre = E[p_k] for k = 1, 2, 3.
Kernel on x_tot, bw 0.35:  ppc_tot_ge2_p{k}_pre = P(c_k >= 2) for k = 1, 2, 3;  ppc_cov_p12_pre = E[c_1 * c_2] - E[c_1] * E[c_2].

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
