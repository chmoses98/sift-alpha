"""Two-key model promotion (consumer side).

Key 1 (producer): the sport pipeline publishes the challenger block declaring itself the activated operating forecast
(NBA_PAG_OPERATING=1 / CFB_OAE_OPERATING=1). Key 2 (consumer, here): sift_feed/operating_models.json names that exact
model_version under `promoted`, a reviewed owner-approved change. A game is served from the promoted model only when
BOTH hold for that game's newest pregame block; otherwise it is served from the incumbent (or, where the incumbent publishes
nothing, not at all) and flagged. Nothing here ever relabels a block: its source_class still derives from its own declaration.
"""
import json
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
