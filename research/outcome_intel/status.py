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


def classify(cell, holm_p=None, negative_control=None):
    """cell: dict from incremental.incremental_test. negative_control: its 'gain_vs_calibrated_market_logloss' dict (or None)."""
    if not cell or cell.get("status") == "MISSING":
        return "MISSING_DATA"
    if cell.get("status") != "OK":
        return "INCONCLUSIVE_UNDERPOWERED"
    g = cell["gain_vs_calibrated_market_logloss"]
    nc_clean = negative_control is None or (negative_control["lo"] <= 0 <= negative_control["hi"] or abs(negative_control["mean"]) < 0.002)
    if cell["holdout_games"] < MIN_GAMES:
        return "INCONCLUSIVE_UNDERPOWERED"
    if g["lo"] > 0 and (holm_p is not None and holm_p <= 0.05) and nc_clean:
        return "VALIDATED_IMPROVEMENT"
    if g["lo"] > 0 and g["mean"] > 0:
        return "PROMISING_INSUFFICIENT"
    half = (g["hi"] - g["lo"]) / 2
    if half <= POWER_HALFWIDTH and g["hi"] < MEANINGFUL:
        return "NO_DEMONSTRATED_IMPROVEMENT"
    return "INCONCLUSIVE_UNDERPOWERED"
