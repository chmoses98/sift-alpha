"""Game-by-game data-completeness verification (RESEARCH_ONLY).

Answers, per sport / season / game / dataset: is the record that SHOULD exist actually archived, readable and
complete?  Expected games (the denominator) and observed records are produced by per-sport adapters that READ the
archives; the engine only classifies.  Nothing here collects data, changes a schedule, or scores a model.

Statuses (exactly one per game x dataset cell):
  COMPLETE        records read back, row count and required fields satisfied
  PARTIAL         records read back but rows or required fields are short
  MISSING         the game is expected to have this dataset and no record was found
  STALE           pregame dataset whose newest pre-start observation is older than the allowed age
  UNVERIFIED      evidence of existence only (file / manifest / count) - content not read back
  RIGHTS_BLOCKED  the only source is not cleared for collection or use (rights registry), so absence is by policy
  NOT_APPLICABLE  the dataset does not apply to this game (dome weather, unplayed game); excluded from denominators

Missing is never zero: a cell without an observation is MISSING (or RIGHTS_BLOCKED), never an empty-but-complete row.
"""
from .model import (CATEGORIES, COMPLETE, MISSING, NOT_APPLICABLE, PARTIAL, RIGHTS_BLOCKED, STALE, STATUSES,
                    UNVERIFIED, DatasetSpec, Game, Observation)
from .engine import classify, evaluate, rollup

__all__ = ["CATEGORIES", "COMPLETE", "MISSING", "NOT_APPLICABLE", "PARTIAL", "RIGHTS_BLOCKED", "STALE", "STATUSES",
           "UNVERIFIED", "DatasetSpec", "Game", "Observation", "classify", "evaluate", "rollup"]
