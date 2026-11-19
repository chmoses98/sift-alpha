"""NBA derived-input builder as a foundation extension module (see alpha_engine.derived.foundation_ext). RESEARCH_ONLY."""
from . import foundation_ext as _F

SPORT = "NBA"
TABLES = {"box": ("game_id", _F.BOX_CONTENT), "sched": ("game_id", _F.SCHED_CONTENT)}


def load_raw(root) -> dict:
    return _F.load_raw(root, SPORT)


def compute(raw: dict) -> dict:
    return _F.compute(raw, SPORT)


def specs():
    return _F.make_specs(SPORT)


def perturb_nv(raw: dict, block_ids: set, seed: int) -> dict:
    return _F.perturb_nv(raw, block_ids, seed, SPORT)
