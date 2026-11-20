"""Adapter that exposes the shared NBA/CBB derived-input engine to the data foundation's certification gates (RESEARCH_ONLY).

The foundation replay (data_foundation/replay_generic.py via replay_ext_run families `nba_derived` / `cbb_derived`) and the blind exact-match comparison
(data_foundation/compare_independent.py, modules `derived.ext_nba` / `derived.ext_cbb`) need a builder module with load_raw(root), compute(raw) -> {"team": df} and specs().
Only catalog inputs that NO earlier foundation replay already covers are declared here: verified_coverage.load_ext_replays rejects a duplicate input id, and
nba.four_factors_matchup, nba.team_three_attempt_matchup, nba.three_point_variance_load (features/nba_ext) and cbb.tempo / adj_off / adj_def (features/cbb_ext, replay/CBB)
are already certified from those builders. Columns are the content-bearing columns of each input; the schedule-only rest term of nba.game_pace_composition enters
exp_poss_comp_pre and is not certified as a column of its own (it cannot move under an outcome perturbation). Nothing here writes the ledger.
"""
from __future__ import annotations

from ..features.core import FeatureSpec
from . import basketball as B
from . import registry as R

# outcome-bearing raw columns per game (what the foundation truncates and permutes); team ids, dates, venue and season type are pre-game facts
BOX_CONTENT = ["team_score", "opponent_team_score", "field_goals_made", "field_goals_attempted", "three_point_field_goals_made", "three_point_field_goals_attempted", "free_throws_made",
               "free_throws_attempted", "offensive_rebounds", "defensive_rebounds", "assists", "steals", "blocks", "fouls", "fast_break_points", "total_turnovers", "turnovers", "team_winner"]
SCHED_CONTENT = ["home_linescores", "away_linescores", "status_period"]
NOT_CERTIFIED_COLUMNS = {"rest_min_pre"}
ALREADY_CERTIFIED_ELSEWHERE = {"nba.four_factors_matchup", "nba.team_three_attempt_matchup", "nba.three_point_variance_load", "nba.margin_heteroscedasticity", "cbb.tempo", "cbb.adj_off", "cbb.adj_def"}
# graded BLOCKED_CONTESTED in the ledger: not promotable (verified_coverage.PROMOTABLE), and the extension gate forbids extension evidence on a blocked row. They pass the same replay and blind
# match (kept for the owner's decision in verification/blind_briefs/derived_bball_blind_runs/not_promotable_evidence.json); re-grading them is an owner decision, not this builder's.
NOT_PROMOTABLE = {"nba.joint_pace_interaction", "nba.game_pace_composition"}


def foundation_ids(sport: str) -> list[str]:
    return [s["id"] for s in R.specs() if s["sport"] == sport and s["kind"] == "catalog" and s["id"] not in ALREADY_CERTIFIED_ELSEWHERE | NOT_PROMOTABLE]


def make_specs(sport: str) -> list[FeatureSpec]:
    out = []
    for s in R.specs():
        if s["sport"] != sport or s["kind"] != "catalog" or s["id"] in ALREADY_CERTIFIED_ELSEWHERE | NOT_PROMOTABLE:
            continue
        out.append(FeatureSpec(sport=sport, catalog_id=s["id"], table="team", columns=[c for c in s["columns"] if c not in NOT_CERTIFIED_COLUMNS], level=s["level"], definition=s["definition"],
                               done=s["done"], missing=s["missing"], raw=s["raw"], pit=s["pit"]))
    return out


def load_raw(root, sport: str) -> dict:
    raw = B.load_raw(root, sport)
    return {"box": raw["box"], "sched": raw["sched"]}


def compute(raw: dict, sport: str) -> dict:
    t = B.team_games(raw, sport); f = B.features(t, sport)
    cols = sorted({c for s in make_specs(sport) for c in s.columns})
    return {"team": f[["game_id", "team", "date", "season"] + cols].reset_index(drop=True)}


def perturb_nv(raw: dict, block_ids: set, seed: int, sport: str) -> dict:
    """Non-vacuity perturbation (foundation replay only, same precedent as nhl_player_ext2.perturb_nv): the standard content scramble of the block's games, plus 30% of the
    block's schedule rows marked as a double-overtime game. A within-season permutation cannot move a pooled seasonal RATE (the repeat-overtime rate of
    nba.ot_prob_ratings_margin counts overtimes per season, which a permutation preserves); changing the overtime count is the smallest perturbation that can."""
    import numpy as np

    from ..input_research.data_foundation import replay_generic as G
    rng = np.random.default_rng(seed); o = dict(raw)
    o["box"] = G._perm(raw["box"], raw["box"].game_id.isin(block_ids).to_numpy(), BOX_CONTENT, rng)
    s = G._perm(raw["sched"], raw["sched"].game_id.isin(block_ids).to_numpy(), SCHED_CONTENT, rng)
    ix = np.flatnonzero(s.game_id.isin(block_ids).to_numpy()); pick = ix[rng.random(len(ix)) < 0.3]
    sp = s["status_period"].to_numpy(dtype=float, copy=True); sp[pick] = B.CFG[sport]["periods"] + 2; s["status_period"] = sp
    o["sched"] = s
    return o
