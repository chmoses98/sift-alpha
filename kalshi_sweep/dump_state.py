"""Print a compact, loss-free-enough summary of a sweep state file to stdout, one JSON line per series, prefixed SWEEPDATA.
Used because run artifacts cannot always be downloaded; the job log is readable through the API."""
import json, sys

st = json.load(open(sys.argv[1]))
print("SWEEPMETA", json.dumps({k: v for k, v in st.items() if k != "series"}, separators=(",", ":")))
for s, by in st.get("series", {}).items():
    row = {"s": s}
    for status, e in by.items():
        row[status] = {k: e.get(k) for k in ("complete", "markets", "event_count", "open_time_min", "open_time_max", "error")}
    smp = next((e["sample"] for e in by.values() if "sample" in e), None)
    if smp:
        row["sample"] = {"ticker": smp.get("ticker"), "title": smp.get("title"), "rules": (smp.get("rules_primary") or "")[:240]}
    print("SWEEPDATA", json.dumps(row, separators=(",", ":")))
