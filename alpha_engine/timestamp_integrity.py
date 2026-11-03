"""Timestamp-integrity checks on an archived full-market snapshot (rows = Kalshi market dicts + an observation stamp).

A pre-game feature/quote is only point-in-time if the archive stamp is not earlier than the data it labels. Reports:
  stamp_distinct        distinct observation stamps (1 => one batch stamp for the whole snapshot)
  updated_after_stamp   rows whose exchange updated_time is later than the observation stamp (+ max lag seconds)
  open_before_created   rows with open_time < created_time
  settled_without_result
These are measurements of the archive, not claims about the exchange."""
import json
from datetime import datetime


def _p(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def check(rows, stamp_key="_observed_at_utc", stamp_default=None):
    stamps = {r.get(stamp_key) or stamp_default for r in rows}
    stamp = max(s for s in stamps if s)
    late = [(_p(r["updated_time"]) - _p(stamp)).total_seconds() for r in rows if r.get("updated_time") and _p(r["updated_time"]) > _p(stamp)]
    return {"rows": len(rows), "stamp_distinct": len(stamps), "stamp": stamp, "updated_after_stamp": len(late), "max_lag_seconds": max(late) if late else 0,
            "open_before_created": sum(1 for r in rows if r.get("open_time") and r.get("created_time") and r["open_time"] < r["created_time"]),
            "settled_without_result": sum(1 for r in rows if r.get("status") in ("settled", "finalized") and not r.get("result"))}
