"""Analyse an espn-sync output dir produced by the soccer PR #39 code: are box-score fields really populated in archived result rows?"""
import json, sys, glob, collections
from pathlib import Path
d = Path(sys.argv[1]); res = []
for f in sorted(glob.glob(str(d / "results" / "espn" / "*.jsonl"))):
    for ln in Path(f).read_text().splitlines():
        if ln.strip(): r = json.loads(ln); r["_file"] = Path(f).name; res.append(r)
box = [r for r in res if r.get("box_stats_source")]
fields = ["home_shots", "away_shots", "home_shots_on_target", "away_shots_on_target", "home_corners", "away_corners", "home_yellow", "away_yellow", "home_red", "away_red", "home_xg", "away_xg"]
out = {"result_rows": len(res), "rows_with_box_stats": len(box), "leagues": dict(collections.Counter(r.get("league") for r in res)),
       "populated_among_box_rows": {k: sum(1 for r in box if r.get(k) is not None) for k in fields},
       "populated_among_all_rows": {k: sum(1 for r in res if r.get(k) is not None) for k in fields},
       "cards_basis": dict(collections.Counter(r.get("cards_basis") for r in res)), "cards_source": dict(collections.Counter(r.get("cards_source") for r in res)),
       "xg_ever_populated": any(r.get("home_xg") is not None or r.get("away_xg") is not None for r in res),
       "sample_box_row": ({k: box[0].get(k) for k in ["espn_event_id", "league", "home_shots", "away_shots", "home_corners", "away_corners", "home_yellow", "away_yellow", "box_stats_source", "box_stats_captured_at"]} if box else None)}
lin = []
for f in glob.glob(str(d / "lineups" / "*" / "*.jsonl")):
    for ln in Path(f).read_text().splitlines():
        if ln.strip(): lin.append(json.loads(ln))
out["lineup_rows"] = len(lin); out["lineup_rows_with_team_stats"] = sum(1 for r in lin if r.get("team_stats"))
out["lineup_states"] = {f"{k[0]}/{k[1]}": v for k, v in collections.Counter((r.get("event_state"), r.get("lineup_state")) for r in lin).items()}
print(json.dumps(out, indent=1))
