"""Compact per-series rows from a sweep state (shared by the job-log dump and the Alpha ingest)."""
import json, sys


def compact_rows(state):
    for s, by in state.get("series", {}).items():
        row = {"s": s}
        for status, e in by.items():
            row[status] = {k: e.get(k) for k in ("complete", "markets", "event_count", "open_time_min", "open_time_max", "error")}
        smp = next((e["sample"] for e in by.values() if "sample" in e), None)
        if smp:
            row["sample"] = {"ticker": smp.get("ticker"), "title": smp.get("title"), "rules": (smp.get("rules_primary") or "")[:240]}
        yield row


if __name__ == "__main__":
    st = json.load(open(sys.argv[1]))
    print("SWEEPMETA", json.dumps({k: v for k, v in st.items() if k != "series"}, separators=(",", ":")))
    for r in compact_rows(st):
        print("SWEEPDATA", json.dumps(r, separators=(",", ":")))
