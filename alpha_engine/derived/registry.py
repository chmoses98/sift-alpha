"""Registry of derived inputs built by alpha_engine.derived (RESEARCH_ONLY): what each one is, how complete it is against the catalog definition, and its lineage.

Lineage is explicit and four-hop: raw vault dataset -> derived columns -> consuming projection model (adoption) -> Kalshi market families.
Level rules (same as alpha_engine.features.core.FeatureSpec): FULL only when the WHOLE catalog definition is implemented; PARTIAL = a stated subset, with the
unimplemented parts listed in `missing`; PROXY = a different measurement of the same mechanism. `kind`: "catalog" = an existing catalog input id; "discovered" = a new
input proposed here (not in the catalog; level is judged against its own stated definition).
Evidence triples (prediction column, realised column in the team-game table, baseline column) drive the out-of-sample check; they never alter the level.
"""
from __future__ import annotations

RAW = {"NBA": ["sift-data-vault:archives/NBA/espn_pbp_boxes_schedules/2002-2027/sportsdataverse/snapshot-20261116 (espn_nba_team_boxscores, espn_nba_schedules)"],
       "CBB": ["sift-data-vault:archives/CBB/espn_team_box_schedules/2006-2027/sportsdataverse/snapshot-20261116 (team_box, schedules)"]}
FAM = {
    "NBA": {"side": ["game_winner", "game_spread", "game_win_margin"], "total": ["game_total"], "team_total": ["team_total"], "period": ["period_winner", "period_spread", "period_total", "period_team_total"],
            "ot": ["game_overtime"], "pts": ["player_points"], "reb": ["player_rebounds"], "ast": ["player_assists"], "threes": ["player_threes"], "stocks": ["player_steals", "player_blocks", "player_stocks"],
            "ft": ["player_free_throws"], "combo": ["parlay_combo", "player_pra"]},
    "CBB": {"side": ["GAME_WINNER", "SPREAD"], "total": ["TOTAL"], "team_total": ["TEAM_TOTAL"], "period": ["HALF"], "ot": [], "pts": ["PLAYER_PROP"], "reb": ["PLAYER_PROP"], "ast": ["PLAYER_PROP"],
            "threes": ["PLAYER_PROP"], "stocks": ["PLAYER_PROP"], "ft": ["PLAYER_PROP"], "combo": []},
}
FF = ["efg", "tov_pct", "orb_pct", "ftr100"]


def _s(sport, cid, level, cols, definition, done, missing, fams, evidence=(), kind="catalog", pit="pregame_rolling"):
    return dict(sport=sport, id=cid, kind=kind, level=level, columns=list(cols), definition=definition, done=list(done), missing=list(missing), raw=RAW[sport], pit=pit, families=list(fams), evidence=[list(e) for e in evidence])


def specs() -> list[dict]:
    S = []
    # ------------------------------------------------------------------ shared, both sports (catalog id where the sport has one, otherwise a discovered input)
    for sp in ("NBA", "CBB"):
        p = sp.lower()
        ff_cols = [f"{a}_{m}_pre" for a in ("off", "def") for m in FF] + [f"mx_{m}_pre" for m in FF] + ["ff_edge_pre"]
        ff_def = ("Offensive and defensive four factors (eFG%, TOV per own possession, ORB%, FTA per 100 possessions), each game's value net of venue edge and of the opponent's pre-game tendency, EWMA shrunk to the team's prior season "
                  "(defensive eFG shrunk more heavily); matchup interaction = team offence + opponent defence - league, and a weighted four-factor edge (eFG 0.4, TOV 0.25, ORB 0.2, FT 0.15).")
        ff_ev = [("mx_efg_pre", "efg", "off_efg_pre"), ("mx_tov_pct_pre", "tov_pct", "off_tov_pct_pre"), ("mx_orb_pct_pre", "orb_pct", "off_orb_pct_pre")]
        if sp == "CBB":
            S.append(_s(sp, "cbb.four_factors", "FULL", ff_cols, ff_def, ["opponent adjustment (two-stage)", "venue adjustment (annual-refit home/away gap)", "stability-weighted shrinkage incl. heavy eFG-defence shrink",
                                                                        "offence-vs-defence matchup interactions relative to league"], [], ["side", "total", "team_total"], ff_ev))
        else:
            S.append(_s(sp, "nba.four_factors_matchup", "PARTIAL", ff_cols, ff_def, ["offensive and defensive four factors per 100 possessions", "opponent adjustment", "expected factor = league + (own offence - league) + (opponent defence - league)",
                                                                                 "shrinkage with prior weight 20 games", "combination with weights 0.4 / 0.25 / 0.2 / 0.15"],
                        ["25-game window with half-life 12 (an untruncated 20-game half-life EWMA is used)", "iterative opponent adjustment (one-pass two-stage is used)", "lineup adjustment for absentees"], ["side", "total", "team_total"], ff_ev))
        S.append(_s(sp, f"{p}.fundamental_expectation", "FULL", ["exp_pts_pre", "opp_exp_pts_pre", "exp_margin_pre", "exp_total_pre", "hca_pts_pre", "net_rtg_pre"],
                    "Market-free expected team points, margin and total: (team adjusted offence + opponent adjusted defence - league) per 100 possessions x expected possessions, plus an annually refit home edge (mean rating-residual home margin of earlier seasons; zero at neutral sites).",
                    ["per-possession opponent/venue-adjusted ratings", "expected possessions", "home edge refit on earlier seasons only", "neutral-site handling"], [],
                    ["side", "total", "team_total", "period"], [("exp_margin_pre", "margin", "ZERO"), ("exp_total_pre", "total", "LEAGUE_MEAN"), ("exp_pts_pre", "pts", "LEAGUE_MEAN")], kind="discovered"))
        S.append(_s(sp, f"{p}.opportunity_environment", "FULL", ["exp_ast_pre", "exp_stl_pre", "exp_blk_pre", "exp_reb_pool_pre", "exp_oreb_pre", "exp_dreb_pre", "exp_fg2a_pre"],
                    "Team-level opportunity pools for counting-stat props: expected assists, steals, blocks (team rate + opponent allowed rate - league, x expected possessions), expected missed field goals (rebound pool) and its offensive/defensive split from matchup ORB%.",
                    ["opponent-allowed rates", "expected possessions scaling", "rebound pool from expected attempts and shrunk accuracy"], [],
                    ["ast", "reb", "stocks", "combo"], [("exp_ast_pre", "ast", "LEAGUE_MEAN"), ("exp_oreb_pre", "oreb", "LEAGUE_MEAN"), ("exp_stl_pre", "stl", "LEAGUE_MEAN"), ("exp_blk_pre", "blk", "LEAGUE_MEAN")], kind="discovered"))
    # ------------------------------------------------------------------ CBB catalog inputs
    S += [
        _s("CBB", "cbb.tempo", "PARTIAL", ["pace_pre", "exp_poss_add_pre", "exp_poss_pre"],
           "Opponent-adjusted possessions per 40 minutes (possessions = FGA - OREB + TOV + 0.44 FTA, both teams averaged, overtime-normalised); expected game pace = league + (A - league) + (B - league) and a walk-forward regression giving the slower team its own weight.",
           ["true possessions (was a points proxy)", "opponent adjustment", "league-additive expected pace", "tempo-control weight for the slower team (estimated, annual refit)"], ["garbage-time filter (needs play-by-play)"],
           ["total", "team_total", "period", "side"], [("exp_poss_pre", "pace", "exp_poss_add_pre"), ("exp_poss_add_pre", "pace", "LEAGUE_MEAN")]),
        _s("CBB", "cbb.adj_off", "PARTIAL", ["off_ortg_pre", "exp_pts_pre"],
           "Points per 100 possessions, each game net of opponent pre-game defence and venue, EWMA (half-life 8 games) shrunk toward the team's prior-season value with weight falling as games are played.",
           ["per-possession efficiency (was points per game)", "opponent adjustment", "home/away/neutral adjustment", "recency decay", "shrink to prior with weight rising with games played"],
           ["ridge / iterative solve (a one-pass two-stage adjustment is used)", "garbage-time filter (needs play-by-play)"], ["side", "total", "team_total"], [("exp_pts_pre", "pts", "LEAGUE_MEAN")]),
        _s("CBB", "cbb.adj_def", "PARTIAL", ["def_ortg_pre", "opp_exp_pts_pre"],
           "Points allowed per 100 possessions with the same opponent / venue / recency / shrink treatment as offence.",
           ["per-possession efficiency (was points allowed per game)", "same adjustment as offence", "early-season shrink", "recency"],
           ["blend with expected defence from opponent shot quality (needs shot locations)", "availability adjustment"], ["side", "total", "team_total"], [("opp_exp_pts_pre", "opp_pts", "LEAGUE_MEAN")]),
        _s("CBB", "cbb.pace_elasticity_to_opponent", "PARTIAL", ["exp_poss_elastic_pre"],
           "poss = league + b_own (T_own - league) + b_opp (T_opp - league), coefficients fitted on the five earlier seasons, applied to both teams' adjusted tempos.",
           ["elasticity regression on own and opponent adjusted tempo", "league-centred", "as-of prior games"], ["per-team ridge coefficients (pooled league coefficients are used)", "inverse-variance averaging of the two teams' models"],
           ["total", "period"], [("exp_poss_elastic_pre", "pace", "exp_poss_add_pre")]),
        _s("CBB", "cbb.opp_foul_propensity_ft_points", "PARTIAL", ["exp_fta_pre", "exp_ft_pts_pre"],
           "expected FTA = possessions x [0.5 team FTA/100 + 0.5 opponent FTA/100 allowed], both opponent-adjusted with half-life 8 and shrinkage n/(n+10); expected FT points = expected FTA x shrunk FT%.",
           ["expected FTA formula", "opponent-adjusted rates, half-life 8, shrink n/(n+10)", "expected FT points"], ["officiating-crew effect (needs pre-game crew assignment)", "20-game window truncation (EWMA is untruncated)"],
           ["team_total", "total", "ft", "pts"], [("exp_fta_pre", "fta", "LEAGUE_MEAN"), ("exp_ft_pts_pre", "ftm", "LEAGUE_MEAN")]),
        _s("CBB", "cbb.opp_three_defense_persistence_split", "PARTIAL", ["opp_fg3a_allowed_z_pre", "opp_fg3pct_allowed_z_pre", "fg3a_matchup_adj_pre", "fg3pct_matchup_adj_pre"],
           "Opponent three-point defence split: z-score of 3PA allowed per 100 possessions (persistent; shrunk n/(n+10) to prior season) and of 3P% allowed (noisy; shrunk heavily), z against the league distribution on earlier dates; matchup adjustments 0.6 x att_z x 0.8 attempts and 0.1 x pct_z x 1.5 points.",
           ["attempts-conceded z", "accuracy-conceded z with heavy shrink", "matchup adjustment constants from the catalog"], ["15-game window truncation (EWMA is untruncated)", "3P%-allowed shrink is n/(n+90) rather than a fixed 0.1 weight"],
           ["threes", "total", "team_total"], []),
        _s("CBB", "cbb.total_variance_by_style", "PARTIAL", ["sd_total_style_pre", "fg3_share_sum_pre", "ftr_sum_pre"],
           "log var(total - model expected total) = a + b log(expected possessions) + c (sum of 3PA shares) + d (sum of FT rates), fitted on the five earlier seasons, expected total from the model (no market).",
           ["variance regression on tempo and shot mix", "model-based expected total", "annual refit on >= 3 earlier seasons (5 when available)", "per-game sd"], ["right-tail skew parameter (overtime-conditioned)"],
           ["total", "team_total", "period"], [("sd_total_style_pre", "ABS_TOTAL_RES", "CONST_SD")]),
        _s("CBB", "cbb.margin_total_covariance", "PARTIAL", ["rho_margin_total_pre"],
           "corr(standardised margin residual, standardised total residual) by favourite-size bucket (0-5, 5-10, 10-20, 20+) and tempo tercile, shrunk to the pooled correlation with weight n/(n+200), from earlier seasons; signed for the row's team.",
           ["standardised residuals from the model", "favourite-size x tempo-tercile buckets", "shrinkage n/(n+200)", "as-of prior seasons"], ["bivariate-copula application with the regime mixture (cbb.margin_regime_mixture not built)"],
           ["side", "total", "combo"], []),
        _s("CBB", "cbb.team_points_margin_coupling", "PARTIAL", ["k_pts_margin_pre"],
           "k = cov(team points residual, margin residual) / var(margin residual) by role (favourite / underdog) and expected-margin bucket, shrunk with weight n/(n+250), from up to 8 earlier seasons; expected margin from fundamentals (no market).",
           ["coupling by role and bucket", "shrinkage n/(n+250)", "fundamentals-based expected margin"], ["simulation of own points from the regime mixture and quantiles at the strike"], ["team_total"], []),
    ]
    # ------------------------------------------------------------------ NBA catalog inputs
    S += [
        _s("NBA", "nba.joint_pace_interaction", "PARTIAL", ["exp_poss_joint_pre", "poss_sd_pre", "pace_slow_pre", "pace_inter_pre"],
           "Game possessions regressed on both teams' opponent-adjusted paces: mean pace, the slower team's pace (free weight) and the interaction, fitted on the five earlier seasons; residual sd by matchup type (fast-fast, mixed, slow-slow).",
           ["five-season regression", "slower-team weight estimated", "interaction", "residual sd by matchup type", "expected possessions and sd"], ["style flags (transition / post-up share)", "lineup adjustment from projected starters", "home adjustment of pace"],
           ["total", "team_total", "period"], [("exp_poss_joint_pre", "pace", "exp_poss_add_pre")]),
        _s("NBA", "nba.game_pace_composition", "PARTIAL", ["exp_poss_comp_pre", "pace_mean_pre", "pace_absdiff_pre", "tov_sum_pre", "fb_sum_pre", "rest_min_pre"],
           "Game possessions regressed on (paceA + paceB)/2, |paceA - paceB|, both teams' turnover rates, fast-break points per 100 (transition proxy) and rest, on five earlier seasons with opponent-adjusted paces (20-game half-life).",
           ["mean and absolute-difference terms", "turnover rate", "rest", "opponent-adjusted paces, 20-game half-life", "five-season fit"], ["transition frequency (fast-break points used as a proxy)", "active-set adjustment (nba.absence_pace_efficiency_decomposition)"],
           ["total", "team_total", "period"], [("exp_poss_comp_pre", "pace", "exp_poss_add_pre")]),
        _s("NBA", "nba.team_three_attempt_matchup", "PARTIAL", ["exp_fg3a_pre", "fg3a_index_pre", "off_fg3a100_pre"],
           "Team 3PA per 100 possessions (EWMA half-life 15, shrunk to prior season with weight 20) x opponent 3PA-allowed index (allowed per 100 / league, half-life 20, weight 25) x projected possessions / 100.",
           ["team rate with stated half-life and shrink", "opponent allowed index with stated half-life and shrink", "possession scaling"], ["missing high-volume shooter adjustment via player 3PA shares", "make rate from nba.three_pt_luck expectation"],
           ["threes", "total", "team_total"], [("exp_fg3a_pre", "fg3a", "OWN_RATE_FG3A")]),
        _s("NBA", "nba.three_point_variance_load", "PARTIAL", ["total_var_load_pre", "sd_total_load_pre", "shot_var_pre"],
           "Var(total) = Var(possessions) x ppp^2 + sum over both teams of E[3PA] x 9 p3(1-p3) + E[2PA] x 4 p2(1-p2) + E[FTA] pft(1-pft), from opponent-adjusted attempts and shrunk rates; scalar lambda calibrated on the two previous seasons so predicted variance matches realised squared total residual.",
           ["shot-count variance components", "possession variance from pace residuals by matchup type", "rolling two-season lambda calibration", "sd per game"], ["possession-ppp covariance term", "FT dispersion factor", "skew from third moment"],
           ["total", "team_total", "threes"], [("sd_total_load_pre", "ABS_TOTAL_RES", "CONST_SD")]),
        _s("NBA", "nba.margin_heteroscedasticity", "PARTIAL", ["sd_margin_pre"],
           "sd_margin = a + b sqrt(own-model possessions) + c |own-model mean margin|, fitted on five earlier seasons of own predictions (no closing lines).",
           ["sd regression on sqrt(possessions) and |mean margin|", "own predictions only", "five-season fit"], ["quantile curves (10/25/50/75/90)", "skew parameter for heavy favourites", "PIT validation per bucket"],
           ["side", "period"], [("sd_margin_pre", "ABS_MARGIN_RES", "CONST_SD")]),
        _s("NBA", "nba.ot_prob_ratings_margin", "PARTIAL", ["p_ot_pre", "p_ot2_given_ot_pre"],
           "P(regulation tie) by logistic regression on |fundamental expected margin| and expected total over five earlier seasons; P(2+ OT | OT) = pooled empirical rate with prior weight 200 OT games.",
           ["step 2 logistic P(regulation tie) on |mu|", "step 4 pooled repeat-overtime rate with prior weight 200", "ratings, pace and results only"], ["step 1 confirmed-inactive adjustment of mu", "step 3 per-team overtime points distribution", "1-point bin smoothing"],
           ["ot", "total", "team_total", "side"], [("p_ot_pre", "ot", "BASE_RATE")]),
        _s("NBA", "nba.team_points_variance_by_style", "PARTIAL", ["sd_pts_style_pre"],
           "Residual sd of team points (actual minus rating-based expectation) regressed on three-point attempt share, pace and |expected margin|, five earlier seasons.",
           ["rating-based residuals (no market)", "regression on 3PA rate and pace", "opponent style via expected margin"], ["shrink to league sd with weight 25 games per team", "skew-normal shape", "tail quantiles and P(points >= strike)", "regulation-only vs overtime-included versions"],
           ["team_total", "pts"], [("sd_pts_style_pre", "ABS_PTS_RES", "CONST_SD")]),
        _s("NBA", "nba.ft_points_matchup", "FULL", ["exp_fta_pre", "exp_ft_pts_pre"],
           "expected FTA = possessions x [0.5 team FTA/100 + 0.5 opponent FTA/100 allowed] (opponent- and venue-adjusted, shrunk); expected FT points = expected FTA x shrunk FT%. NBA mirror of cbb.opp_foul_propensity_ft_points without the crew term.",
           ["expected FTA", "expected FT points"], [], ["ft", "pts", "team_total"], [("exp_fta_pre", "fta", "LEAGUE_MEAN")], kind="discovered"),
        _s("NBA", "nba.opp_three_defense_persistence_split", "FULL", ["opp_fg3a_allowed_z_pre", "opp_fg3pct_allowed_z_pre", "fg3a_matchup_adj_pre", "fg3pct_matchup_adj_pre"],
           "NBA mirror of the CBB split: z of opponent 3PA allowed per 100 (persistent) and of 3P% allowed (heavily shrunk, weight n/(n+200)) against the league distribution on earlier dates, with the same matchup adjustments.",
           ["attempt z", "accuracy z", "matchup adjustments"], [], ["threes"], [], kind="discovered"),
        _s("NBA", "nba.margin_total_covariance", "FULL", ["rho_margin_total_pre", "k_pts_margin_pre"],
           "NBA mirror of the CBB joint-structure tables: margin-total residual correlation by favourite bucket x pace tercile (shrink n/(n+200)) and team-points-to-margin coupling by role x bucket (shrink n/(n+250)), from earlier seasons.",
           ["correlation table", "coupling table"], [], ["combo", "team_total", "side", "total"], [], kind="discovered"),
        _s("CBB", "cbb.ot_prob_fundamental", "FULL", ["p_ot_pre"],
           "P(overtime) by logistic regression of the regulation-tie indicator on |fundamental expected margin| and expected total, fitted on earlier seasons with linescores. CBB mirror of nba.ot_prob_ratings_margin step 2.",
           ["logistic on |mu| and expected total", "annual refit"], [], ["total", "side", "period"], [("p_ot_pre", "ot", "BASE_RATE")], kind="discovered"),
        _s("CBB", "cbb.margin_sd_fundamental", "FULL", ["sd_margin_pre", "sd_pts_style_pre"],
           "Per-game margin sd = a + b sqrt(expected possessions) + c |expected margin| and team-points sd on 3PA share, pace and |expected margin|, fitted on earlier seasons of own predictions. CBB mirror of nba.margin_heteroscedasticity.",
           ["margin sd regression", "team points sd regression"], [], ["side", "team_total", "period"], [("sd_margin_pre", "ABS_MARGIN_RES", "CONST_SD")], kind="discovered"),
        _s("CBB", "cbb.team_three_attempt_matchup", "FULL", ["exp_fg3a_pre", "fg3a_index_pre"],
           "Team 3PA per 100 possessions x opponent 3PA-allowed index x expected possessions / 100. CBB mirror of nba.team_three_attempt_matchup (team level only).",
           ["team rate", "opponent index", "possession scaling"], [], ["threes", "total"], [("exp_fg3a_pre", "fg3a", "OWN_RATE_FG3A")], kind="discovered"),
    ]
    return S


CATALOG_IDS: set = set()


def load_catalog_ids(root) -> set:
    import json
    from pathlib import Path
    out = set()
    for sp in ("NBA", "CBB"):
        out |= {(sp, k) for k in json.loads((Path(root) / f"research/input_research/catalog/{sp}.json").read_text())["inputs"]}
    CATALOG_IDS.clear(); CATALOG_IDS.update(out)
    return out
