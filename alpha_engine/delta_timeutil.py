"""UTC-only ISO compatibility for pinned SIFT market delta reader."""
from datetime import datetime, timezone
def iso(dt):
    if dt.tzinfo is None: raise ValueError("naive datetime")
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")
def parse_iso(s):
    if not isinstance(s,str): raise ValueError("missing timestamp")
    if s.endswith("Z"): s=s[:-1]+"+00:00"
    dt=datetime.fromisoformat(s)
    if dt.tzinfo is None: raise ValueError("naive datetime")
    return dt.astimezone(timezone.utc)
