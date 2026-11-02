"""Machine-readable market-family inventory + input-audit schema (stdlib only, fail-closed).

Statuses are deliberately closed enums; anything not proven is UNKNOWN. A dashboard may only display what
these validated artifacts say - it must never infer completion.
"""
from __future__ import annotations

from datetime import datetime, timezone

SCHEMA_VERSION = "audit-1.0"
SPORTS = ("NFL", "CFB", "NBA", "CBB", "NHL", "MLB", "SOCCER", "TENNIS")
COLLECTION = {"COLLECTED", "COLLECTED_STALE_OR_PARTIAL", "NOT_COLLECTED", "UNKNOWN", "NOT_APPLICABLE"}
MODEL_USE = {"USED_CORRECTLY", "USED_DEFECTIVE", "USED_DEFECT_REPAIRED", "COLLECTED_UNUSED",
             "NOT_MODELED", "UNKNOWN", "NOT_APPLICABLE"}
VALIDATION = {"NOT_VALIDATED", "VALIDATED_IN_SAMPLE_ONLY", "VALIDATED_OOS_HISTORICAL",
              "VALIDATED_PROSPECTIVE", "UNKNOWN"}
IMPORTANCE = {"ESSENTIAL", "IMPORTANT", "CANDIDATE"}
PRIORITY = {"P0", "P1", "P2", "P3", "NONE", "UNKNOWN"}
_INPUT_KEYS = {"input", "importance", "collection", "model_use", "validation", "evidence", "defect"}


def _ts(v):
    if not isinstance(v, str):
        return False
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return False
    return d.tzinfo is not None and d.utcoffset().total_seconds() == 0


def validate_inventory(inv):
    errs = []
    if inv.get("schema_version") != SCHEMA_VERSION:
        errs.append("schema_version")
    if not _ts(inv.get("last_verified_utc")):
        errs.append("last_verified_utc must be explicit UTC")
    src = inv.get("source") or {}
    for k in ("repo", "commit", "path", "sha256"):
        if not src.get(k):
            errs.append(f"source.{k} missing")
    seen = set()
    for f in inv.get("families", []):
        fam = f.get("family")
        if not fam or fam in seen:
            errs.append(f"duplicate/missing family {fam}")
        seen.add(fam)
        if not f.get("series"):
            errs.append(f"{fam}: no series")
        if f.get("snapshot_markets_seen") is not None and (type(f["snapshot_markets_seen"]) is not int or f["snapshot_markets_seen"] < 0):
            errs.append(f"{fam}: bad snapshot_markets_seen")
        if sum(s["snapshot_markets_seen"] for s in f.get("series", [])) != f.get("snapshot_markets_seen"):
            errs.append(f"{fam}: series counts do not sum to family count")
    return errs


def validate_audit(a):
    errs = []
    if a.get("schema_version") != SCHEMA_VERSION:
        errs.append("schema_version")
    for k in ("sport", "market_family", "settles_on", "distribution", "key_numbers", "freshness"):
        if not a.get(k):
            errs.append(f"{k} missing")
    if not _ts(a.get("last_verified_utc")):
        errs.append("last_verified_utc must be explicit UTC")
    if a.get("repair_priority") not in PRIORITY:
        errs.append("repair_priority")
    if not isinstance(a.get("coverage"), dict) or "snapshot_markets_seen" not in a["coverage"]:
        errs.append("coverage.snapshot_markets_seen missing")
    names = set()
    for i in a.get("inputs", []):
        n = i.get("input")
        if set(i) != _INPUT_KEYS:
            errs.append(f"{n}: keys {sorted(set(i) ^ _INPUT_KEYS)}")
            continue
        if n in names:
            errs.append(f"duplicate input {n}")
        names.add(n)
        for key, enum in (("importance", IMPORTANCE), ("collection", COLLECTION), ("model_use", MODEL_USE), ("validation", VALIDATION)):
            if i[key] not in enum:
                errs.append(f"{n}: bad {key} {i[key]!r}")
        known = i["collection"] != "UNKNOWN" or i["model_use"] != "UNKNOWN"
        if known and not i["evidence"]:
            errs.append(f"{n}: a non-UNKNOWN status needs evidence")
        if i["model_use"] in ("USED_DEFECTIVE", "USED_DEFECT_REPAIRED") and not i["defect"]:
            errs.append(f"{n}: defect status without defect text")
        if i["validation"].startswith("VALIDATED") and not i["evidence"]:
            errs.append(f"{n}: validation without evidence")
    if not names:
        errs.append("no inputs")
    return errs
