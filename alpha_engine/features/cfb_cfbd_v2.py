"""CFB CFBD builder v2: corrected drive-points attribution (RESEARCH_ONLY).

v1 (`cfb_cfbd`, certified dataset a73a3e14...) credits 7 points to the drive's OFFENSE for any `driveResult` containing "TD" unless it
contains DEF / "INT TD" / "FUMBLE TD" / "PUNT TD". Labels such as "FUMBLE RETURN TD", "PUNT RETURN TD", "MISSED FG TD", "DOWNS TD" and
"FG TD" are scores by the DEFENDING team but were credited to the offense. v1 and its dataset are immutable; this module is a NEW builder
version producing a NEW dataset hash. Only `ppd_o` / `ppd_d` (hence `ppd_o_pre` / `ppd_d_pre`) can differ from v1.

v2 rule (spec: docs/certification/CFB_FEATURE_SPEC_V2.md v2.2):
  * 7 points if `driveResult` is exactly one of OFFENSE_TD;
  * 7 points if it is one of GOAL_LINE_TD (`DOWNS TD`, `FUMBLE RETURN TD`: mixed classes) AND the drive ended on the opponent's
    goal line (`endYardsToGoal == 0`), i.e. the offense itself reached the end zone (e.g. recovered its own fumble for the score);
  * 3 points if it is exactly one of FIELD_GOAL;
  * 0 points otherwise.
Labels are an exact allowlist. A label containing "TD" or "FG" that is in none of the known sets raises (fail closed).
v2.2 follows the independent verifier's evidence (research/certification/evidence/cfb_v2_compare.json): END OF HALF TD / END OF GAME TD are
defensive scores and DOWNS TD / FUMBLE RETURN TD are mixed classes separated by whether the drive reached the goal line.
Known limitation (unchanged from v1, not addressed here): the `scoring` flag is ignored.
"""
from __future__ import annotations

import numpy as np

from . import cfb_cfbd as V1
from .cfb_cfbd import PRE, PRIOR, WIN, FIRST, LAST  # noqa: F401  (same columns and season range as v1)

BUILDER_VERSION = "cfb_cfbd_v2"
OFFENSE_TD = frozenset({"TD", "RUSHING TD", "PASSING TD"})
GOAL_LINE_TD = frozenset({"DOWNS TD", "FUMBLE RETURN TD"})   # offense's score only when the drive ended on the goal line
DEFENSE_TD = frozenset({"INT TD", "FUMBLE TD", "PUNT TD", "PUNT RETURN TD", "MISSED FG TD", "FG TD", "END OF HALF TD", "END OF GAME TD",
                        "POSSESSION (FOR OT DRIVES) TD"})         # never the offense's score
QUALIFIED_TD = GOAL_LINE_TD | DEFENSE_TD
FIELD_GOAL = frozenset({"FG", "FG GOOD"})
ZERO_KNOWN = frozenset({"MISSED FG", "FG MISSED", "BLOCKED FG"})


def drive_points(dr) -> np.ndarray:
    """dr: drives frame with `driveResult` and `endYardsToGoal`."""
    lab = np.asarray([str(x) for x in dr["driveResult"]], dtype=object)
    unknown = sorted({x for x in set(lab.tolist()) if ("TD" in x or "FG" in x) and x not in OFFENSE_TD | QUALIFIED_TD | FIELD_GOAL | ZERO_KNOWN})
    if unknown:
        raise ValueError(f"cfb_cfbd_v2: unreviewed scoring-like driveResult labels: {unknown}")
    import pandas as pd
    at_goal = (pd.to_numeric(dr["endYardsToGoal"], errors="coerce") == 0).to_numpy() if "endYardsToGoal" in dr else np.zeros(len(lab), bool)
    td = np.isin(lab, list(OFFENSE_TD)) | (np.isin(lab, list(GOAL_LINE_TD)) & at_goal)
    return np.where(td, 7.0, np.where(np.isin(lab, list(FIELD_GOAL)), 3.0, 0.0))


def load_raw(cache):
    return V1.load_raw(cache)


def compute(raw: dict) -> dict:
    return V1.compute(raw, drive_points)
