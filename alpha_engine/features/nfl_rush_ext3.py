"""Rusher-keyed view of nfl_pbp_ext3 (nfl.rush_yardage_tail) for the generic replay harness, which reads compute(raw)["team"] and specs(). See nfl_pbp_ext3 for the definitions."""
import numpy as np
import pandas as pd

from .nfl_pbp_ext3 import CONTENT, load_raw, specs_rusher as specs, compute_rusher as compute  # noqa: F401


def perturb(raw: dict, block_ids, seed: int) -> dict:
    """Role-preserving perturbation used by every replay scramble (truncation-perturbation, own-game, non-vacuity), as for tennis: the game CONTENT this input reads is the
    per-carry yardage; who carried and against whom (rusher_player_id, posteam, defteam) are pre-game roles that define the (game, rusher) row universe, so they stay fixed.
    Non-vacuity perturbation that keeps the row universe (game, rusher) fixed: permute rushing_yards among the carries of the block's games only.
    Permuting rusher ids (the generic scramble) would change which (game, rusher) rows exist, and the non-vacuity check compares rows by position."""
    o = dict(raw); p = raw["pbp"].copy(); rng = np.random.default_rng(seed)
    m = p["game_id"].isin(block_ids) & (pd.to_numeric(p["rush_attempt"], errors="coerce") == 1) & p["rushing_yards"].notna()
    ix = np.flatnonzero(m.to_numpy()); col = p["rushing_yards"].to_numpy(copy=True); col[ix] = rng.permutation(col[ix]); p["rushing_yards"] = col
    o["pbp"] = p
    return o


perturb_nv = perturb
