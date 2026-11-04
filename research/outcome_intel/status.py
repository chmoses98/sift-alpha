"""Evidence-status classification shared by every sport/family/horizon cell (RESEARCH_ONLY).

Statuses (a cell gets exactly one):
  VALIDATED_IMPROVEMENT       challenger beats calibrated market-only baseline on the untouched holdout: CI lower bound > 0 AND Holm-adjusted p <= 0.05
                              AND the negative control stayed null AND holdout games >= MIN_GAMES
  PROMISING_INSUFFICIENT      point estimate > 0 and CI lower bound > 0 but multiplicity-adjusted p > 0.05 (or negative control not clean)
  NO_DEMONSTRATED_IMPROVEMENT enough power: the CI is tight enough (half-width <= POWER_HALFWIDTH) that a gain >= MEANINGFUL would have been seen, and none is
  INCONCLUSIVE_UNDERPOWERED   too few holdout games / CI too wide to exclude a meaningful gain (NOT evidence of no effect)
  MISSING_DATA                no usable pregame prices / outcomes / challenger input (reason + repair recorded by the caller)
  INVALID_EVIDENCE            data fails integrity checks (leakage, unverifiable settlement, duplicated outcomes)
"""
MIN_GAMES = 30            # holdout independent games for any verdict other than INCONCLUSIVE
POWER_HALFWIDTH = 0.01    # logloss units: CI half-width needed to call a null a null
MEANINGFUL = 0.005        # logloss improvement that would matter economically (~0.5% of a coin-flip's 0.693)

ALL = ("VALIDATED_IMPROVEMENT", "PROMISING_INSUFFICIENT", "NO_DEMONSTRATED_IMPROVEMENT", "INCONCLUSIVE_UNDERPOWERED", "MISSING_DATA", "INVALID_EVIDENCE")


def nc_clean(nc):
    """Negative control must have been RUN and its CI must contain 0. None = not run = not clean (blocks VALIDATED)."""
    return nc is not None and nc.get("lo") is not None and nc["lo"] <= 0 <= nc["hi"]


def classify_gain(gain, holdout_games, holm_p, nc):
    """Single authority for sport/family/horizon cells that have a gain estimate (dict mean/lo/hi). holdout_games None -> INCONCLUSIVE (loud, never silent)."""
    if not gain or gain.get("mean") is None or gain.get("lo") is None:
        return "MISSING_DATA"
    if holdout_games is None or holdout_games < MIN_GAMES:
        return "INCONCLUSIVE_UNDERPOWERED"
    if gain["lo"] > 0:
        return "VALIDATED_IMPROVEMENT" if (holm_p is not None and holm_p <= 0.05 and nc_clean(nc)) else "PROMISING_INSUFFICIENT"
    if gain["hi"] < 0 or ((gain["hi"] - gain["lo"]) / 2 <= POWER_HALFWIDTH and gain["hi"] < MEANINGFUL):
        return "NO_DEMONSTRATED_IMPROVEMENT"      # CI excludes any gain (challenger reliably worse) or is tight enough to exclude a meaningful one
    return "INCONCLUSIVE_UNDERPOWERED"


def classify(cell, holm_p=None, negative_control=None):
    """cell: dict from incremental.incremental_test."""
    if not cell or cell.get("status") == "MISSING":
        return "MISSING_DATA"
    if cell.get("status") != "OK":
        return "INCONCLUSIVE_UNDERPOWERED"
    return classify_gain(cell["gain_vs_calibrated_market_logloss"], cell["holdout_games"], holm_p, negative_control)
