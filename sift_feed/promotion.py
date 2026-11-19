"""Two-key model promotion (consumer side).

Key 1 (producer): the sport pipeline publishes the challenger block declaring itself the activated operating forecast
(NBA_PAG_OPERATING=1 / CFB_OAE_OPERATING=1). Key 2 (consumer, here): sift_feed/operating_models.json names that exact
model_version under `promoted`, a reviewed owner-approved change. A game is served from the promoted model only when
BOTH hold for that game's newest pregame block; otherwise it is served from the incumbent (or, where the incumbent publishes
nothing, not at all) and flagged. Nothing here ever relabels a block: its source_class still derives from its own declaration.
"""
import json
import math
from pathlib import Path

from .schema import PRODUCTION, classify

MANIFEST = Path(__file__).with_name("operating_models.json")
SCHEMA = "sift.operating_models.v1"
REQUIRED = ("model_version", "approved_by", "approved_at", "approval_ref")


def load(path=None):
    doc = json.loads(Path(path or MANIFEST).read_text())
    if doc.get("schema") != SCHEMA:
        raise ValueError(f"operating_models.json: schema {doc.get('schema')!r} != {SCHEMA!r}")
    for sport, entry in (doc.get("sports") or {}).items():
        p = entry.get("promoted")
        if p is not None:
            missing = [k for k in REQUIRED if not p.get(k)]
            if missing:
                raise ValueError(f"operating_models.json: {sport}.promoted lacks {missing}")
    return doc


def promoted(sport, path=None):
    """The approved promotion for `sport` ({"model_version", "approved_by", ...}) or None (incumbent only)."""
    return ((load(path).get("sports") or {}).get(sport) or {}).get("promoted")


def check_block(declaration, block_version, promo):
    """None when a block may be served as the promoted operating forecast, else the reason it may not."""
    if promo is None:
        return "no promotion configured"
    if block_version != promo["model_version"]:
        return f"block model_version {block_version!r} is not the promoted {promo['model_version']!r}"
    if classify(declaration) != PRODUCTION:
        return "producer has not activated the block as the operating forecast"
    return None


def summary(promo, served, fallback_reasons):
    """Sport-level promotion state for the feed summary."""
    if promo is None:
        return None
    state = "active" if served and not fallback_reasons else "partial" if served else "awaiting_producer_activation"
    return {"state": state, "model_version": promo["model_version"], "approved_by": promo["approved_by"],
            "approved_at": promo["approved_at"], "approval_ref": promo["approval_ref"], "games_served": served,
            "games_on_incumbent": len(fallback_reasons),
            "incumbent_reasons": sorted(set(fallback_reasons))[:5]}


# ------------------------------------------------------------------------------------------------ forecast validation
# A promoted block is served only if its numbers are a usable forecast. Anything non-finite, out of range or internally
# incoherent is never served: the game falls back to the incumbent (NBA) or is not served (CFB), with the reason flagged.
MARGIN_MAX = 80.0        # |home - away| points; beyond any real NBA/CFB model output
PROB_SUM_TOL = 2e-3


def finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def forecast_problems(p_home, margin, sd=None, p_away=None, periods=None):
    """[] when (p_home, margin, sd, p_away, periods) is a coherent, finite forecast, else the reasons it is not.

    periods: {segment: {field: value}}; fields starting with p_ must be probabilities, totals/means must be >= 0,
    every number finite (margins in a period may be negative)."""
    why = []
    if not (finite(p_home) and 0.0 < p_home < 1.0):
        why.append(f"p_home_win {p_home!r} is not a probability in (0, 1)")
    if p_away is not None and not (finite(p_away) and finite(p_home) and abs(p_home + p_away - 1.0) <= PROB_SUM_TOL):
        why.append(f"p_away_win {p_away!r} does not complement p_home_win {p_home!r}")
    if not (finite(margin) and abs(margin) <= MARGIN_MAX):
        why.append(f"margin {margin!r} is not finite within +-{MARGIN_MAX:g}")
    if sd is not None and not (finite(sd) and sd > 0):
        why.append(f"margin sd {sd!r} is not positive and finite")
    if finite(p_home) and finite(margin) and abs(margin) >= 1.0 and (p_home > 0.5) != (margin > 0):
        why.append(f"p_home_win {p_home} and margin {margin} favour different sides")
    for seg, d in (periods or {}).items():
        for k, v in (d or {}).items() if isinstance(d, dict) else ():
            if v is None or isinstance(v, (str, list, dict)):
                continue
            if not finite(v):
                why.append(f"{seg}.{k} {v!r} is not finite")
            elif k.startswith("p_") and not 0.0 <= v <= 1.0:
                why.append(f"{seg}.{k} {v} is not a probability")
            elif ("total" in k or k.endswith("_mean") or k in ("home", "away")) and "margin" not in k and v < 0:
                why.append(f"{seg}.{k} {v} is negative")
    return why
