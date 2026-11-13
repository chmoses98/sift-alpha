"""NFL capture-window coverage check (RESEARCH_ONLY, no LLM).

  python nfl_plan_check.py LAB_REPO WORKFLOW_YML

Loads the real 2026 schedule, derives every pre-registered decision window with the lab's own planner (alpha_engine.lab.schedule_plan), expands the capture cron lines that are
actually in the workflow file (minute 37), and fails if ANY future window has no firing overlapping it -- both for on-time starts and for a start delayed by 45 minutes (GitHub delivers
scheduled runs late).  Prints the planner's own recommended cron lines (minimal cover, on time and 45 min late) so the file can be regenerated, never hand-typed.
"""
import sys, io, json, urllib.request
lab, wf_path = sys.argv[1], sys.argv[2]
sys.path.insert(0, lab)
import pandas as pd, yaml
from alpha_engine.lab import schedule_plan as SP

URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
games = pd.read_csv(io.BytesIO(urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": "sift-alpha-research"}), timeout=60).read()))
now = pd.Timestamp.now(tz="UTC")
# Minimal cover: every future decision window (T-24h, T-6h, T-90m) needs one firing that serves it on time AND one that serves it if all deliveries are 45 min late.  The planner's own
# needed_firings() (+1 preceding hour, +weekly flattening at min_weeks=1) over-schedules ~3x, so the proposal here is a greedy hitting set over exactly those two requirements.
from alpha_engine.lab import capture_window as CW
M = pd.Timedelta(minutes=1); F, S, DELAY = SP.FIRE_MIN, SP.SPAN, 45
wins = [(dt - CW.PRE_MIN * M, dt + CW.POST_MIN * M) for _, _, dt in CW.decision_times(CW.kickoffs(games, 2026), now) if dt + CW.POST_MIN * M >= now]
def serves(t, a, b, fm):   # same predicate as SP.uncovered
    return t + (fm + S) * M >= a + 5 * M and t + fm * M <= b - 5 * M
cand = pd.date_range(min(a for a, _ in wins).floor("h") - pd.Timedelta(hours=4), max(b for _, b in wins).ceil("h"), freq="h")
items = {(i, fm): {t for t in cand if t > now and serves(t, a, b, fm)} for i, (a, b) in enumerate(wins) for fm in (F, F + DELAY)}
left, chosen = set(items), []
while left:
    best = max(cand, key=lambda t: (sum(1 for k in left if t in items[k]), -t.value))
    chosen.append(best); left = {k for k in left if best not in items[k]}
for t in list(chosen):   # prune redundancy
    rest = set(chosen) - {t}
    if all(items[k] & rest for k in items):
        chosen.remove(t)
chosen = sorted(chosen)
need = chosen
proposal = SP.to_cron({}, chosen)
wf = yaml.safe_load(open(wf_path))
lines = [c["cron"] for c in wf[True]["schedule"] if c["cron"].split()[0] == str(SP.FIRE_MIN)]
fired = SP.expand_cron_hours(lines, now - pd.Timedelta(hours=2), now + pd.Timedelta(days=200))
bad_on_time = SP.uncovered(games, fired, now)
bad_late = SP.uncovered(games, fired, now, fire_min=SP.FIRE_MIN + 45)
out = {"now": now.isoformat(), "future_firings_needed": len(need), "firings_per_week": round(len(need) / max(1, (need[-1] - need[0]).days / 7), 1), "firings_per_day_over_season": round(len(need) / max(1, (need[-1] - need[0]).days), 2), "workflow_capture_crons": lines, "recommended_crons": proposal, "uncovered_on_time": bad_on_time, "uncovered_if_45min_late": bad_late}
out["uncovered_on_time"] = {"count": len(bad_on_time), "first": bad_on_time[:5]}
out["uncovered_if_45min_late"] = {"count": len(bad_late), "first": bad_late[:5]}
out["recommended_crons"] = len(proposal)
print(json.dumps(out, indent=1))
print("RECOMMENDED_CRONS (minimal cover, on time + 45 min late):")
for l in proposal:
    print("  - cron: \"%s\"" % l)
sys.exit(1 if (bad_on_time or bad_late) else 0)
