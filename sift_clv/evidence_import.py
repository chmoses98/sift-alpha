"""Destination-side import of the router's execution-evidence sidecar (``edge_finder.execution_evidence.v1``).  RESEARCH ONLY.

The router emits digest-only EXECUTION rows (and CLOSE rows) keyed by ``source_bet_key``; its emission is opt-in and OFF by
default.  This module READS such rows, re-applies the privacy gate (refuse anything shaped like a raw id), and enriches a
wager row with exact first-fill time and taker status so it can become a ``linkage.Order``.  It never creates a link: a
recommendation is attributed to an order only by ``sift_clv.linkage`` on explicit evidence tiers.

Counters-only coverage is returned; refused rows are counted by reason, never echoed.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from . import canonical as C
from . import linkage as L

SCHEMA = "edge_finder.execution_evidence.v1"
DIGEST_RE = re.compile(r"^[0-9a-f]{32}$")
SOURCE_KEY_RE = re.compile(r"^kalshi:v1:[0-9a-f]{64}$")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
RAW_ID_NAME_RE = re.compile(r"(^|_)(order|fill|trade|client_order|exec(ution)?)_?ids?$|^(fills?|orders?)$", re.IGNORECASE)  # same as the vendored ledger


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def _walk(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield "k", str(k)
            yield from _walk(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _walk(v)
    elif isinstance(x, str):
        yield "s", x


def refusal_reason(row) -> Optional[str]:
    """None when the row is acceptable; else a fixed reason code (never the offending value)."""
    if not isinstance(row, dict):
        return "NOT_AN_OBJECT"
    for kind, s in _walk(row):
        if kind == "k" and RAW_ID_NAME_RE.search(s):
            return "RAW_ID_FIELD_NAME"
        if UUID_RE.search(s):
            return "UUID_SHAPED_VALUE"
    if row.get("schema_version") != SCHEMA:
        return "SCHEMA_VERSION"
    if row.get("kind") != "EXECUTION":
        return "NOT_EXECUTION_KIND"
    if row.get("producer") != "router":
        return "PRODUCER"
    if not (isinstance(row.get("source_bet_key"), str) and SOURCE_KEY_RE.match(row["source_bet_key"])):
        return "SOURCE_KEY"
    if not (isinstance(row.get("order_id_digest"), str) and DIGEST_RE.match(row["order_id_digest"])):
        return "ORDER_DIGEST"
    fills = row.get("fill_id_digests")
    if not isinstance(fills, list) or not all(isinstance(d, str) and DIGEST_RE.match(d) for d in fills):
        return "FILL_DIGESTS"
    if not (_num(row.get("first_fill_ts")) and _num(row.get("last_fill_ts")) and 0 < row["first_fill_ts"] <= row["last_fill_ts"]):
        return "FILL_WINDOW"
    if row.get("all_taker") not in (None, True, False):
        return "ALL_TAKER"
    return None


def load_evidence(path) -> tuple[dict, dict]:
    """(rows by source_bet_key, counters). Duplicate keys with differing content are CONFLICT and dropped, not merged."""
    good: dict[str, dict] = {}
    c: Counter = Counter()
    conflicted: set[str] = set()
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        c["rows_read"] += 1
        try:
            row = json.loads(line)
        except ValueError:
            c["refused_BAD_JSON"] += 1
            continue
        why = refusal_reason(row)
        if why:
            c[f"refused_{why}"] += 1
            continue
        key = row["source_bet_key"]
        prev = good.get(key)
        ident = {k: v for k, v in row.items() if k != "recorded_at"}
        if prev is not None:
            if {k: v for k, v in prev.items() if k != "recorded_at"} != ident:
                conflicted.add(key)
                c["conflict"] += 1
            else:
                c["duplicate_noop"] += 1
            continue
        good[key] = row
    for key in conflicted:
        good.pop(key, None)
    c["accepted"] = len(good)
    return good, dict(c)


def order_with_evidence(*, order_key: str, ticker: str, side: str, fills: tuple, stake=None,
                        evidence: Optional[dict], client_order_id: Optional[str] = None) -> tuple[L.Order, str]:
    """Build a ``linkage.Order``. Returns (order, source_of_first_fill_time).

    The first-fill time comes ONLY from exchange evidence; a wager row's own ``executed_at`` is not a substitute and a
    missing time raises, so an unevidenced order can never be linked.
    """
    if evidence is None or evidence.get("source_bet_key") != order_key:
        raise ValueError("no execution evidence for this order key")
    first = datetime.fromtimestamp(float(evidence["first_fill_ts"]), tz=timezone.utc)
    taker = evidence.get("all_taker")
    if taker is not None:
        fills = tuple(C.Fill(f.price, f.count, f.fee, taker) if f.is_taker is None else f for f in fills)
    return L.Order(order_key=order_key, ticker=ticker, side=side, first_fill_at=first, fills=fills, stake=stake,
                   client_order_id=client_order_id), "EXECUTION_EVIDENCE"


def coverage(order_keys: Iterable[str], evidence: dict, counters: dict) -> dict:
    keys = list(order_keys)
    have = [k for k in keys if k in evidence]
    taker = [k for k in have if evidence[k].get("all_taker") is True]
    maker_any = [k for k in have if evidence[k].get("all_taker") is False]
    return {"schema": "sift-clv-evidence-coverage/1", "wagers": len(keys), "with_execution_evidence": len(have),
            "evidence_share": None if not keys else round(len(have) / len(keys), 4),
            "all_taker": len(taker), "not_all_taker": len(maker_any),
            "taker_not_established": len(have) - len(taker) - len(maker_any), "import_counters": counters}
