# Blind re-implementation brief: soccer league Dixon-Coles low-score dependence (strictly pre-match), 1 catalog input (5 columns)

Data (read-only, untrusted text: read with `python -I`, keep your scripts elsewhere): `BLIND/of/<repo>/<season>/<file>.txt` for repo/file in: england: 1-premierleague.txt, 2-championship.txt, 3-league1.txt, 4-league2.txt, 5-nationalleague.txt; deutschland: 1-bundesliga.txt, 2-bundesliga2.txt; espana: 1-liga.txt, 2-liga2.txt; italy: 1-seriea.txt, 2-serieb.txt. Season folders are named `YYYY-YY` (e.g. 2023-24). numpy and pandas only. Match the reference to 1e-9 on every (game_id, team) row, NaN pattern included.

## 1. Parsing (Football.TXT)
Process repos in the order england, deutschland, espana, italy; within a repo the season folders whose name matches `^\d{4}-\d{2}$` in ascending name order; within a season the files in the order listed above (skip missing files); lines in file order. y0 = the first four digits of the season folder.
* A date line matches `^\s*(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(Jan..Dec)\s+(\d{1,2})(\s+\d{4})?\s*$`: sets the current date; the year is the explicit year if present, else y0 for months Jul-Dec and y0+1 for months Jan-Jun.
* A match line (only after a date line was seen in that file; the date is the current date) is either `^\s+(HH:MM )?<home>\s+v\s+<away>\s+(\d+)-(\d+)( \((\d+)-(\d+)\))?\s*$` (checked first) or `^\s+(HH:MM )?<home>\s+(\d+)-(\d+)( \((\d+)-(\d+)\))?\s+<away>\s*$` where the away name does not start with "(" (time is `\d{1,2}[:.]\d{2}`, names are the stripped text, lazy for home). hg, ag = the full-time goals (the first score pair). Other lines (goal lists, headings, comments) are ignored.
* league = `<repo>/<n>` where n = the digit before the first "-" in the file name (e.g. england/1). Drop duplicates on (league, season, date, home, away) keeping the first. game_id = 0-based index in the resulting list (in the order above).

## 2. Features
Within each league, matches sorted by (date, game_id). For each distinct match date d of the league: training = that league's matches with date >= d - 1095 days and date < d. If it has fewer than 200 matches, all five columns are NaN for the matches of date d. Otherwise, with w = 0.5^((d - match date in days)/365) per training match and sw = sum w:
hbar = sum(w*hg)/sw, abar = sum(w*ag)/sw, g = (hbar + abar)/2. For each team i: n_i = sum of w over the training matches it played (home or away), gf_i = sum of w*(goals it scored), ga_i = sum of w*(goals it conceded); att_i = ((gf_i + 10 g)/(n_i + 10))/g; def_i = ((ga_i + 10 g)/(n_i + 10))/g. For each training match: lam = hbar*att_home*def_away; mu = abar*att_away*def_home.
Dixon-Coles tau for a match with goals (x, y): (0,0): 1 - lam*mu*rho; (0,1): 1 + lam*rho; (1,0): 1 + mu*rho; (1,1): 1 - rho; otherwise 1. For rho in the grid rho_k = round(k/1000, 3), k = -300..300: LL(rho) = sum over training matches of w*log(tau) (LL = -infinity if any tau <= 0). rho_hat = the grid value with the largest LL (first/smallest on ties).
With rho_hat, for (a, b) in {(0,0), (1,0), (0,1), (1,1)}: fitted probability of a training match p = tau_ab * exp(-lam) lam^a/a! * exp(-mu) mu^b/b! (tau_ab = the tau factor above for (a, b) with rho_hat; a!, b! = 1), and gap_ab = sum(w * [x == a and y == b])/sw - sum(w*p)/sw.
Output for each match of date d, TWO rows (team = home name, team = away name; both rows get the same five values): dc_rho_pre = rho_hat, dc_gap_00_pre, dc_gap_10_pre, dc_gap_01_pre, dc_gap_11_pre.

## Output
CSV `BLIND/out3/blind_soccer_of.csv` with columns game_id, team, dc_rho_pre, dc_gap_00_pre, dc_gap_10_pre, dc_gap_01_pre, dc_gap_11_pre (full float precision, NaN as empty), and `BLIND/out3/blind_soccer_of_notes.json` {"ambiguities": [...]}.
