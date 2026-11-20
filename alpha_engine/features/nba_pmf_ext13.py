"""NBA batch 13, second family (RESEARCH_ONLY): nba.period_margin_pmf from nba_dist_ext13.compute (definition there); its `period` table is exposed as `team` so the
generic replay (one table per family) checks it. Rows: every team-row of seasons whose fit window holds five linescore seasons (2025+)."""
from __future__ import annotations

from . import nba_dist_ext13 as D
from .core import FeatureSpec

S = D.S
BOX_CONTENT, SCHED_CONTENT, load_raw = D.BOX_CONTENT, D.SCHED_CONTENT, D.load_raw


def compute(raw: dict) -> dict:
    return {"team": D.compute(raw)["period"]}


def specs() -> list[FeatureSpec]:
    src = D.specs()[0].raw
    return [FeatureSpec(S, "nba.period_margin_pmf", "team", D.PM, "FULL",
                        "Discrete two-component normal-mixture pmf of period margin and total for Q1-Q4, 1H and 2H-with-OT around rating-based expectations (no lines), pace- and team-pair-"
                        "dependent scale, fitted by exact grid maximum likelihood on the five earlier linescore seasons; tie probability, pace tercile",
                        ["period types Q1, Q2, Q3, Q4, 1H, 2H-with-OT", "rating-based expectation, no market lines", "discrete mixture with pace-dependent variance and excess-kurtosis component",
                         "maximum likelihood with team-pair variance covariate", "pmf at integer margins within +/-25 (pmf())", "tie probability by expected pace tercile"], [], src)]
