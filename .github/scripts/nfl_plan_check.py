"""NFL capture-window coverage check (RESEARCH_ONLY, no LLM).

  python nfl_plan_check.py LAB_REPO WORKFLOW_YML

Loads the real 2026 schedule, derives every pre-registered decision window with the lab's own planner (alpha_engine.lab.schedule_plan), expands the capture cron lines that are
actually in the workflow file (minute 37), and fails if ANY future window has no firing overlapping it -- both for on-time starts and for a start delayed by 45 minutes (GitHub delivers
scheduled runs late).  Prints the planner's own recommended cron lines (with one extra preceding hour of margin) so the file can be regenerated, never hand-typed.
"""
import sys, io, json, urllib.request
lab, wf_path = sys.argv[1], sys.argv[2]
sys.path.insert(0, lab)
import pandas as pd, yaml
from alpha_engine.lab import schedule_plan as SP

URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
games = pd.read_csv(io.BytesIO(urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": "sift-alpha-research"}), timeout=60).read()))
now = pd.Timestamp.now(tz="UTC")
need = SP.needed_firings(games, now)
buffered = sorted(set(need) | {t - pd.Timedelta(hours=1) for t in need})
pat, exc = SP.weekly_pattern(buffered, min_weeks=1)
proposal = SP.to_cron(pat, exc)
wf = yaml.safe_load(open(wf_path))
lines = [c["cron"] for c in wf[True]["schedule"] if c["cron"].split()[0] == str(SP.FIRE_MIN)]
fired = SP.expand_cron_hours(lines, now - pd.Timedelta(hours=2), now + pd.Timedelta(days=200))
bad_on_time = SP.uncovered(games, fired, now)
bad_late = SP.uncovered(games, fired, now, fire_min=SP.FIRE_MIN + 45)
out = {"now": now.isoformat(), "future_firings_needed": len(need), "workflow_capture_crons": lines, "recommended_crons": proposal, "uncovered_on_time": bad_on_time, "uncovered_if_45min_late": bad_late}
print(json.dumps(out, indent=1))
sys.exit(1 if (bad_on_time or bad_late) else 0)
