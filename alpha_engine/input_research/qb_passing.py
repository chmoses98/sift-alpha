"""NFL QB passing yards: learned input importance with opponent adjustment, pressure, game script and injuries.

MARKET COMPARISON IS BLOCKED. No free historical sportsbook/Kalshi passing-yards lines exist in any source Alpha can reach, so nothing here can claim to beat a
market. What it CAN establish: which inputs carry out-of-sample predictive information about a QB's passing yards beyond the strongest no-market baseline
(the QB's own shrunk, recency-weighted rate) and how large each effect is. A gain here is a research lead to test against real lines, never an edge.

Pregame-knowability: all QB / team / opponent features are as-of the game; the starter is the REALISED QB1 (announced before kickoff for nearly all games, but
not guaranteed at the decision time): flagged. Weather is the observed value (forecast proxy). Injuries are final-report designations x prior snap share.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import nfl_game as ng
from . import stats as S

# Partially-knowable inputs (see nfl_game.PARTIAL_PIT): every QB-own prior depends on the REALISED QB1 identity (the QB who threw the most in the game), and weather/roof is the
# OBSERVED state. The strict headline excludes them; note the baseline N1 itself is the realised QB1's rate, and the sample requires >=12 dropbacks (see run() notes).
PARTIAL_PIT = frozenset({"qb_att_prior", "qb_games_prior", "qb_epa_prior", "qb_cpoe_prior", "qb_adot_prior", "qb_sack_prior", "own_inj_qb",
                         "dome", "wind_eff", "cold", "ix_pressure_x_qbsack", "ix_wind_x_adot", "ix_dbinj_x_adot"})
MIN_DROPBACKS = 12
QB_LAM = 0.5 ** (1 / 10.0)
QB_PRIOR = 4.0   # pseudo-games


def qb_games_from_pbp(pbp: pd.DataFrame) -> pd.DataFrame:
    d = pbp[pbp["season_type"].isin(["REG", "POST"]) & (pbp["qb_dropback"] == 1) & pbp["passer_player_id"].notna() & pbp["posteam"].notna()].copy()
    d["is_pass"] = (d["pass"] == 1).astype(float)
    d["scramble"] = ((d["qb_dropback"] == 1) & (d["pass"] != 1) & (d["sack"] != 1)).astype(float)
    d["py"] = np.where(d["pass"] == 1, d["passing_yards"].fillna(0.0), 0.0)
    d["att"] = ((d["pass_attempt"] == 1) & (d["sack"] != 1)).astype(float)
    d["air"] = np.where(d["pass_attempt"] == 1, d["air_yards"], np.nan)
    g = d.groupby(["game_id", "posteam", "passer_player_id"]).agg(
        dropbacks=("epa", "size"), att=("att", "sum"), pass_yards=("py", "sum"), epa_sum=("epa", "sum"), sacks=("sack", "sum"),
        scrambles=("scramble", "sum"), cpoe=("cpoe", "mean"), adot=("air", "mean"), interceptions=("interception", "sum"),
        season=("season", "first"), week=("week", "first")).reset_index()
    g = g.sort_values(["game_id", "posteam", "dropbacks"], ascending=[True, True, False]).drop_duplicates(["game_id", "posteam"])
    return g[g["dropbacks"] >= MIN_DROPBACKS].rename(columns={"passer_player_id": "qb_id"})


def qb_rolling(qg: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Pregame per-QB rates (EWMA across that QB's own prior games, shrunk to league mean; carried across seasons)."""
    order = games.set_index("game_id")["gameday"]
    qg = qg.assign(gd=qg["game_id"].map(order)).sort_values(["gd", "game_id"]).reset_index(drop=True)
    metrics = {"yds": "pass_yards", "att": "att", "epa": None, "cpoe": "cpoe", "adot": "adot", "sack": None}
    league = {m: [0.0, 0.0] for m in metrics}
    st = {}
    rows = []
    def lg(m):
        a, b = league[m]
        return a / b if b else np.nan
    for r in qg.itertuples(index=False):
        s = st.setdefault(r.qb_id, {m: [0.0, 0.0] for m in metrics} | {"n": 0})
        rec = {"game_id": r.game_id, "posteam": r.posteam, "qb_id": r.qb_id, "qb_games_prior": s["n"]}
        for m in metrics:
            num, den = s[m]
            rec[f"qb_{m}_prior"] = (lg(m) + num / (den + QB_PRIOR)) if not np.isnan(lg(m)) else np.nan    # league mean + shrunk deviation
        rows.append(rec)
        obs = {"yds": r.pass_yards, "att": r.att, "epa": r.epa_sum / r.dropbacks, "cpoe": r.cpoe, "adot": r.adot, "sack": r.sacks / r.dropbacks}
        for m, v in obs.items():
            if v is None or np.isnan(v):
                continue
            L = lg(m)
            if not np.isnan(L):
                s[m][0] = s[m][0] * QB_LAM + (v - L); s[m][1] = s[m][1] * QB_LAM + 1.0
            league[m][0] += float(v); league[m][1] += 1.0
        s["n"] += 1
    return pd.DataFrame(rows)


def build_qb_table(game_table: pd.DataFrame, pbp: pd.DataFrame) -> pd.DataFrame:
    games = game_table
    qg = qb_games_from_pbp(pbp)
    roll = qb_rolling(qg, games)
    qg = qg.merge(roll, on=["game_id", "posteam", "qb_id"], how="inner").drop(columns=["season", "week"])
    g = games.copy()
    rows = []
    for tag, opp, team_col in (("h", "a", "home_team"), ("a", "h", "away_team")):
        x = qg.merge(g, left_on=["game_id", "posteam"], right_on=["game_id", team_col], how="inner")
        sign = 1.0 if tag == "h" else -1.0
        f = pd.DataFrame({
            "game_id": x["game_id"], "season": x["season"], "week": x["week"], "gameday": x["gameday"], "team": x["posteam"], "qb_id": x["qb_id"],
            "side": tag, "pass_yards": x["pass_yards"], "att": x["att"], "dropbacks": x["dropbacks"], "result": x["result"],
            # --- QB own
            "qb_yds_prior": x["qb_yds_prior"], "qb_att_prior": x["qb_att_prior"], "qb_epa_prior": x["qb_epa_prior"], "qb_cpoe_prior": x["qb_cpoe_prior"],
            "qb_adot_prior": x["qb_adot_prior"], "qb_sack_prior": x["qb_sack_prior"], "qb_games_prior": x["qb_games_prior"],
            # --- team offence context (opponent-adjusted ratings)
            "team_neutral_pass": x[f"{tag}_off_neutral_pass"], "team_pass_oe": x[f"{tag}_off_pass_oe"], "team_sec_play": x[f"{tag}_off_sec_play"],
            "team_epa_pass": x[f"{tag}_off_epa_pass"], "team_sack_rate": x[f"{tag}_off_sack_rate"], "team_qbhit_rate": x[f"{tag}_off_qbhit_rate"],
            "team_expl_pass": x[f"{tag}_off_expl_pass"],
            # --- opposing defence
            "opp_epa_pass_allowed": x[f"{opp}_def_epa_pass"], "opp_expl_pass_allowed": x[f"{opp}_def_expl_pass"], "opp_sack_rate": x[f"{opp}_def_sack_rate"],
            "opp_qbhit_rate": x[f"{opp}_def_qbhit_rate"], "opp_passrate_faced": x[f"{opp}_def_neutral_pass"], "opp_plays_faced": x[f"{opp}_def_plays"],
            "opp_sr_allowed": x[f"{opp}_def_sr"],
            # --- game script from the market (pregame): positive spread_team = this team favoured
            "spread_team": sign * x["spread_line"], "total_line": x["total_line"],
            "implied_team_total": x["total_line"] / 2 + sign * x["spread_line"] / 2,
            # --- environment / schedule
            "dome": x["dome"], "wind_eff": x["wind_eff"], "cold": x["cold"], "is_home": 1.0 if tag == "h" else 0.0, "rest": x["home_rest"] if tag == "h" else x["away_rest"],
            # --- injuries (final report x prior snap share)
            "own_inj_ol": x[f"{tag}_inj_ol"], "own_inj_skill": x[f"{tag}_inj_skill"], "own_inj_qb": x[f"{tag}_inj_qb"],
            "opp_inj_dl": x[f"{opp}_inj_dl"], "opp_inj_lb": x[f"{opp}_inj_lb"], "opp_inj_db": x[f"{opp}_inj_db"],
        })
        rows.append(f)
    t = pd.concat(rows, ignore_index=True)
    # derived matchup + interactions (pre-specified from the catalog)
    t["abs_spread"] = t["spread_team"].abs()
    t["pressure_matchup"] = t["opp_qbhit_rate"] + t["team_qbhit_rate"]
    t["sack_matchup"] = t["opp_sack_rate"] + t["team_sack_rate"]
    t["pass_eff_matchup"] = t["team_epa_pass"] + t["opp_epa_pass_allowed"]
    t["ix_trailing_x_passrate"] = (-t["spread_team"]).clip(lower=0) * t["team_neutral_pass"]
    t["ix_pressure_x_qbsack"] = t["pressure_matchup"] * t["qb_sack_prior"]
    t["ix_wind_x_adot"] = t["wind_eff"] * t["qb_adot_prior"]
    t["ix_olinj_x_pressure"] = t["own_inj_ol"] * t["opp_qbhit_rate"]
    t["ix_total_x_pace"] = t["implied_team_total"] * t["team_sec_play"]
    t["ix_dbinj_x_adot"] = t["opp_inj_db"] * t["qb_adot_prior"]
    t["baseline_ypg"] = t["qb_yds_prior"]
    inj_cols = ["own_inj_ol", "own_inj_skill", "own_inj_qb", "opp_inj_dl", "opp_inj_lb", "opp_inj_db"]
    t.loc[t["season"] < 2013, inj_cols] = np.nan
    return t.sort_values(["season", "week", "gameday", "game_id", "team"]).reset_index(drop=True)


QB_GROUPS = {
    "qb_own_rate_and_volume": ["qb_att_prior", "qb_games_prior"],
    "qb_efficiency": ["qb_epa_prior", "qb_cpoe_prior", "qb_adot_prior", "qb_sack_prior"],
    "team_pass_tendency_PROE_pace": ["team_neutral_pass", "team_pass_oe", "team_sec_play"],
    "team_pass_offence_quality": ["team_epa_pass", "team_expl_pass"],
    "protection_proxy": ["team_sack_rate", "team_qbhit_rate"],
    "opponent_pass_defence": ["opp_epa_pass_allowed", "opp_expl_pass_allowed", "opp_sr_allowed"],
    "opponent_pass_rush": ["opp_sack_rate", "opp_qbhit_rate", "pressure_matchup", "sack_matchup"],
    "opponent_pass_volume_faced": ["opp_passrate_faced", "opp_plays_faced"],
    "game_script_market": ["spread_team", "abs_spread", "total_line", "implied_team_total"],
    "environment": ["dome", "wind_eff", "cold", "is_home", "rest"],
    "injuries_own_line_and_receivers": ["own_inj_ol", "own_inj_skill", "own_inj_qb"],
    "injuries_opponent_defence": ["opp_inj_dl", "opp_inj_lb", "opp_inj_db"],
}
QB_LABELS = {
    "qb_att_prior": "QB's shrunk recency-weighted pass attempts per game", "qb_games_prior": "QB's prior games of evidence", "qb_epa_prior": "QB EPA/dropback (shrunk)",
    "qb_cpoe_prior": "QB completion % over expected (shrunk)", "qb_adot_prior": "QB average depth of target (shrunk)", "qb_sack_prior": "QB sack rate (shrunk)",
    "team_neutral_pass": "Team neutral-situation pass rate", "team_pass_oe": "Team pass rate over expected", "team_sec_play": "Team neutral seconds per play",
    "team_epa_pass": "Team opponent-adjusted passing EPA/dropback", "team_expl_pass": "Team explosive-pass rate", "team_sack_rate": "Team sacks allowed rate (protection proxy)",
    "team_qbhit_rate": "Team QB hits+sacks allowed rate (protection proxy)", "opp_epa_pass_allowed": "Opponent passing EPA allowed (adjusted)",
    "opp_expl_pass_allowed": "Opponent explosive passes allowed", "opp_sr_allowed": "Opponent success rate allowed", "opp_sack_rate": "Opponent sack rate generated",
    "opp_qbhit_rate": "Opponent QB hit+sack rate generated (pass rush)", "pressure_matchup": "Pressure matchup (opp rush + own protection)", "sack_matchup": "Sack matchup",
    "opp_passrate_faced": "Neutral pass rate opponents show against this defence", "opp_plays_faced": "Plays per game the defence faces",
    "spread_team": "Team spread (positive = favoured): game-script proxy", "abs_spread": "Absolute spread (blowout risk)", "total_line": "Market game total",
    "implied_team_total": "Market-implied team total", "dome": "Dome", "wind_eff": "Wind (mph)", "cold": "Cold (deg below 65F)", "is_home": "Home team", "rest": "Rest days",
    "own_inj_ol": "Own OL injury impact", "own_inj_skill": "Own WR/TE/RB injury impact", "own_inj_qb": "QB's own injury-report impact",
    "opp_inj_dl": "Opponent DL injury impact", "opp_inj_lb": "Opponent LB injury impact", "opp_inj_db": "Opponent DB injury impact",
    "ix_trailing_x_passrate": "Interaction: expected trailing x neutral pass rate", "ix_pressure_x_qbsack": "Interaction: pressure matchup x QB sack-proneness",
    "ix_wind_x_adot": "Interaction: wind x QB depth of target", "ix_olinj_x_pressure": "Interaction: OL injuries x opponent pass rush", "ix_total_x_pace": "Interaction: implied total x pace",
    "ix_dbinj_x_adot": "Interaction: opponent DB injuries x QB depth of target",
}
QB_INTERACTIONS = {
    "ix_trailing_x_passrate": ("spread_team", "team_neutral_pass", "Trailing teams (underdogs) pass more late; a high baseline pass rate amplifies the volume boost."),
    "ix_pressure_x_qbsack": ("pressure_matchup", "qb_sack_prior", "Pressure costs more yards for QBs who already take sacks / hold the ball."),
    "ix_wind_x_adot": ("wind_eff", "qb_adot_prior", "Wind suppresses downfield passing, hurting deep-throwing QBs most."),
    "ix_olinj_x_pressure": ("own_inj_ol", "opp_qbhit_rate", "A depleted line is exposed most by a strong pass rush."),
    "ix_total_x_pace": ("implied_team_total", "team_sec_play", "High implied totals add yards only if the offence's tempo creates the plays."),
    "ix_dbinj_x_adot": ("opp_inj_db", "qb_adot_prior", "Secondary injuries should help deep-throwing QBs more."),
}


def run(qb: pd.DataFrame, n_boot: int = S.BOOT, quick: bool = False) -> dict:
    d = qb[(qb["season"] >= ng.FIRST_MODEL_SEASON) & qb["pass_yards"].notna() & qb["baseline_ypg"].notna()].reset_index(drop=True)
    ts = ng._test_seasons(d)
    raw = d["pass_yards"].to_numpy(float)
    base = d["baseline_ypg"].to_numpy(float)
    resid = raw - base
    res = ng.study(d, ts, resid, raw, base, QB_GROUPS, QB_INTERACTIONS, n_boot, quick, prob_kind=None, standalone_exclude_prefix=("ix_", "qb_yds"), standalone_skip_groups=(),
                   partial_cols=PARTIAL_PIT)
    res["kind"] = "qb_passing_yards"
    res["baseline_definition"] = ("N1 = the QB's own shrunk recency-weighted passing yards per game (half-life 10 games, 4 pseudo-games toward the league mean): the "
                                  "'historical average' model. B0/B1 in this study refer to N1 / N1+past-mean-residual, NOT to a market.")
    res["sample_note"] = ("Sample = the team's QB1 (most dropbacks) with >=12 dropbacks. QB1 identity and the participation threshold are REALISED: games where the starter left early or "
                          "was benched are excluded or recorded under the backup, so yardage here is conditional on the QB playing most of the game. The same sample defines the baseline, "
                          "so incremental gains are comparable, but a prop priced before kickoff also carries the early-exit risk this sample removes.")
    res["market_comparison"] = {"status": "BLOCKED", "reason": "no free historical passing-yards prop lines (sportsbook or Kalshi) are reachable; archives hold only recent Kalshi tape"}
    # predictive-interval coverage: scale sd with the prediction (yards are heteroskedastic); walk-forward
    return res


FEATURE_CATALOG = {
    "qb_att_prior": ["nfl.proe", "nfl.pace", "nfl.qb"], "qb_games_prior": ["nfl.qb"], "qb_epa_prior": ["nfl.qb_efficiency"], "qb_cpoe_prior": ["nfl.qb_efficiency", "nfl.catch_rate_oe"],
    "qb_adot_prior": ["nfl.air_yards_adot"], "qb_sack_prior": ["nfl.pressure_qb"], "team_neutral_pass": ["nfl.proe", "nfl.script"], "team_pass_oe": ["nfl.proe"], "team_sec_play": ["nfl.pace"],
    "team_epa_pass": ["nfl.pass_efficiency"], "team_expl_pass": ["nfl.explosive"], "team_sack_rate": ["nfl.ol"], "team_qbhit_rate": ["nfl.ol", "nfl.pressure_qb"],
    "opp_epa_pass_allowed": ["nfl.def_epa"], "opp_expl_pass_allowed": ["nfl.def_epa"], "opp_sr_allowed": ["nfl.def_epa"], "opp_sack_rate": ["nfl.pass_rush"], "opp_qbhit_rate": ["nfl.pass_rush"],
    "pressure_matchup": ["nfl.pressure_qb", "nfl.pass_rush", "nfl.ol"], "sack_matchup": ["nfl.pressure_qb", "nfl.ol"], "opp_passrate_faced": ["nfl.def_epa", "nfl.script"],
    "opp_plays_faced": ["nfl.pace"], "spread_team": ["nfl.script"], "abs_spread": ["nfl.script", "nfl.garbage_time"], "total_line": ["nfl.script", "m.external_lines"],
    "implied_team_total": ["nfl.script", "m.external_lines"], "dome": ["nfl.weather_pit", "nfl.venue"], "wind_eff": ["nfl.weather_pit"], "cold": ["nfl.weather_pit"], "is_home": ["nfl.venue"],
    "rest": ["nfl.rest_travel"], "own_inj_ol": ["nfl.injuries_pit", "nfl.ol"], "own_inj_skill": ["nfl.injuries_pit", "nfl.skill_avail"], "own_inj_qb": ["nfl.injuries_pit", "nfl.qb"],
    "opp_inj_dl": ["nfl.injuries_pit", "nfl.pass_rush"], "opp_inj_lb": ["nfl.injuries_pit", "nfl.def_personnel"], "opp_inj_db": ["nfl.injuries_pit", "nfl.def_personnel"],
    "ix_trailing_x_passrate": ["nfl.script", "nfl.proe"], "ix_pressure_x_qbsack": ["nfl.pressure_qb", "nfl.pass_rush"], "ix_wind_x_adot": ["nfl.weather_pit", "nfl.air_yards_adot"],
    "ix_olinj_x_pressure": ["nfl.ol", "nfl.pass_rush"], "ix_total_x_pace": ["nfl.pace", "nfl.script"], "ix_dbinj_x_adot": ["nfl.def_personnel", "nfl.air_yards_adot"],
}
