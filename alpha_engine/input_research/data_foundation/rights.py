"""Source-use rights, tracked separately from verification status (RESEARCH_ONLY).

The registry (`rights_registry.json`) maps a builder's raw-source names to a rights tier. An input's tier is the WEAKEST tier over all its raw sources; a raw source that matches no registry token is UNRESOLVED (fail closed).
A repository CODE licence is never evidence about upstream data. Rights never change a verification status; they are reported as a separate dimension.
"""
from __future__ import annotations

import glob
import json
from functools import lru_cache
from pathlib import Path

DF = Path(__file__).resolve().parents[3] / "research/input_research/data_foundation"
REG = DF / "rights_registry.json"


class RightsFrozen(RuntimeError):
    """Raised when a collector for a rights-unresolved source is asked to run."""


@lru_cache(maxsize=1)
def registry() -> dict:
    return json.loads(REG.read_text())


def tier_of_source(raw_name: str) -> str:
    reg = registry(); order = reg["tier_order"]; name = raw_name.lower()
    matched = [s for s in reg["sources"] if any(t in name for t in s["tokens"])]
    superseded = {x for s in matched for x in s.get("supersedes", [])}      # a more specific entry (e.g. MoneyPuck listed downloads) replaces only the entries it names
    hits = [order.index(s["tier"]) for s in matched if s["id"] not in superseded]
    return order[min(hits)] if hits else order[0]


def tier_of_sources(raw: list[str]) -> str:
    order = registry()["tier_order"]
    return order[min((order.index(tier_of_source(r)) for r in raw), default=0)]


def is_cleared(tier: str) -> bool:
    """Research-cleared (explicit data licence permits internal non-commercial research use)."""
    return tier in registry()["rights_cleared_tiers"]


is_research_cleared = is_cleared


def is_commercial_cleared(tier: str) -> bool:
    """Commercial-use cleared (explicit open licence only; CC BY-NC-SA and wrapper-only licences never qualify)."""
    return tier in registry().get("commercial_cleared_tiers", [])


@lru_cache(maxsize=1)
def raw_sources_by_key() -> dict:
    """key (SPORT:input id) -> raw sources claimed by its replayed builder (extension replays override the earlier replays)."""
    out: dict = {}
    for sub in ("replay", "replay_ext"):
        for f in sorted(glob.glob(str(DF / "verification" / sub / "*.json"))):
            for iid, x in json.loads(Path(f).read_text())["inputs"].items():
                out[f"{x['sport']}:{iid}"] = list(x.get("raw_claimed") or [])
    return out


def input_tier(key: str) -> str:
    raw = raw_sources_by_key().get(key)
    return tier_of_sources(raw) if raw else registry()["tier_order"][0]


def assert_collection_permitted(collector: str) -> None:
    """Refuse to run a collector whose sources are rights-UNRESOLVED (owner decision 1: no new collection)."""
    frozen = registry().get("frozen_collectors", {}).get(collector)
    if frozen:
        raise RightsFrozen(f"{collector} is frozen: sources {frozen} are RIGHTS_UNRESOLVED / INTERNAL_RESEARCH_ONLY (see research/input_research/data_foundation/rights_registry.json); an owner rights decision must be recorded first")
