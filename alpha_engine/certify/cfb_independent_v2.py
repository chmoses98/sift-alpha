"""Independent re-implementation of the CFB v2.2 game-level feature dataset (certification, RESEARCH_ONLY).

Built only from docs/certification/CFB_FEATURE_SPEC_V2.md (which replaces the drive-points rule of
CFB_FEATURE_SPEC.md v1.1) and the blind v1 implementation `cfb_independent.py`. No production feature code was
consulted. `cfb_independent.py` is not modified: everything except the drive-points rule is reused as is.

Usage:
    python -m alpha_engine.certify.cfb_independent_v2 --cfb DIR --out FILE.parquet

How the rule is swapped without touching v1: every drive record is copied with its `driveResult` replaced by a
canonical label whose v1 score equals the v2.2 score of the original drive ("TD" -> 7, "FG" -> 3, "-" -> 0). The v1
pipeline then runs unchanged on the relabelled drives.

SPEC V2.2 READING
-----------------
* L = str(driveResult), no trimming, no case folding (a missing result becomes "None" and scores 0).
* G = endYardsToGoal is a JSON number (int/float, not bool) equal to 0; missing / non-numeric -> False.
* 7 iff L in OFFENSE_TD, or (G and L in GOAL_LINE_TD); 3 iff L in THREE; 0 otherwise.
* Fail closed: if L contains "TD" or "FG" (case-sensitive substring) and is in none of OFFENSE_TD, GOAL_LINE_TD,
  THREE, ZERO_LISTED, the build raises UnknownDriveLabel and no dataset is produced (checked before G is used).
* History (neither registered): v2.0 allow-listed END OF HALF TD / END OF GAME TD / POSSESSION (FOR OT DRIVES) TD
  as 7 and zeroed DOWNS TD / FUMBLE RETURN TD; v2.1 applied the goal-line test to every qualified TD label, which
  was wrong for INT TD / FUMBLE TD / PUNT RETURN TD. v2.2 restricts the test to DOWNS TD and FUMBLE RETURN TD.
"""
from __future__ import annotations

import argparse
import os
import time

import pandas as pd

from alpha_engine.certify import cfb_independent as v1

OFFENSE_TD = frozenset({"TD", "RUSHING TD", "PASSING TD"})
GOAL_LINE_TD = frozenset({"DOWNS TD", "FUMBLE RETURN TD"})
THREE = frozenset({"FG", "FG GOOD"})
ZERO_LISTED = frozenset({"INT TD", "FUMBLE TD", "PUNT TD", "PUNT RETURN TD", "MISSED FG TD", "FG TD", "END OF HALF TD",
                         "END OF GAME TD", "POSSESSION (FOR OT DRIVES) TD", "MISSED FG", "FG MISSED", "BLOCKED FG"})
_CANON = {7.0: "TD", 3.0: "FG", 0.0: "-"}


class UnknownDriveLabel(ValueError):
    """A drive label contains TD or FG but is not classified by the v2.2 specification."""


def at_goal(end_yards_to_goal) -> bool:
    v = end_yards_to_goal
    return (not isinstance(v, bool)) and isinstance(v, (int, float)) and v == 0


def drive_points_v2(drive_result, end_yards_to_goal=None) -> float:
    label = str(drive_result)
    if label in OFFENSE_TD:
        return 7.0
    if label in GOAL_LINE_TD:
        return 7.0 if at_goal(end_yards_to_goal) else 0.0
    if label in THREE:
        return 3.0
    if ("TD" in label or "FG" in label) and label not in ZERO_LISTED:
        raise UnknownDriveLabel(f"unclassified drive label containing TD/FG: {label!r}")
    return 0.0


def _relabel(drives) -> list:
    out = []
    for d in drives:
        c = dict(d)
        c["driveResult"] = _CANON[drive_points_v2(d.get("driveResult"), d.get("endYardsToGoal"))]
        out.append(c)
    return out


def build(raw: dict) -> pd.DataFrame:
    raw = dict(raw)
    if "drives" not in raw:
        raw["drives"] = list(raw.get("drives_regular", [])) + list(raw.get("drives_postseason", []))
    raw["drives"] = _relabel(raw["drives"])
    return v1.build(raw)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cfb", required=True, help="CFBD research cache directory (contains <season>/ folders)")
    ap.add_argument("--out", required=True, help="output parquet path")
    a = ap.parse_args(argv)
    t0 = time.time()
    df = build(v1.load_raw(a.cfb))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    df.to_parquet(a.out, index=False)
    print(f"rows={len(df)} cols={df.shape[1]} seconds={time.time() - t0:.1f} -> {a.out}")


if __name__ == "__main__":
    main()
