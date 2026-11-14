import sys, os, glob, statistics, json
sys.path.insert(0, os.path.dirname(__file__))
from common import *
R = sys.argv[1]
pit = sorted(P(jload(f)["meta"]["retrieved_at"]) for f in glob.glob(f"{R}/nef_market-data/data/pit_availability/nfl/espn_injuries/*/*.json.gz"))
res = {}
for d in sorted({t.date() for t in pit if t.weekday() == 6}):
    ts = [t for t in pit if t.date() == d and 11 <= t.hour <= 23]
    g = [(b - a).total_seconds() / 3600 for a, b in zip(ts, ts[1:])]
    res[str(d)] = {"n_captures_11-23Z": len(ts), "expected_hourly_slots": 13, "max_gap_h": round(max(g), 2) if g else None, "captures": [t.strftime("%H:%M") for t in ts]}
json.dump(res, open(f"{os.path.dirname(os.path.dirname(__file__))}/nfl_sunday.json", "w"), indent=1); print(json.dumps(res)[:1500])
