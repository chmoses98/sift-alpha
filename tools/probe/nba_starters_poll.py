"""Live probe (runner only): poll ESPN core-roster starter flags for tonight's NBA games using the PR #87 code unchanged.
Measures, per game/team, when `starter: true` x5 first appears relative to tip. Writes the raw ledger + a coverage report.
Nothing is projected; rows are exactly what nba_edge.data.starters.capture_starters produces."""
import json, sys, time
from datetime import timedelta
from pathlib import Path
from nba_edge.archive.ledger import Ledger
from nba_edge.data.schedule import fetch_espn_scoreboard
from nba_edge.data.starters import STARTERS_KIND, capture_starters, coverage_by_lead_time
from nba_edge.timeutil import parse_iso, utcnow

out = Path(sys.argv[1]); poll_s = float(sys.argv[2]); deadline_h = float(sys.argv[3])
led = Ledger(out / "archive")
t0 = utcnow(); log = []


def slate():
    games = []
    for d in range(2):
        try:
            gs, _ = fetch_espn_scoreboard(utcnow() + timedelta(days=d), ttl_s=0)
            games += [g.model_dump(mode="json") for g in gs]
        except Exception as e:  # noqa: BLE001
            log.append({"at": utcnow().isoformat(), "slate_error": str(e)[:150]})
    seen, uniq = set(), []
    for g in games:
        if g["game_id"] not in seen:
            seen.add(g["game_id"]); uniq.append(g)
    return uniq


games = slate()
tips = sorted(parse_iso(g["start_time_utc"]) for g in games if g.get("status") in (None, "scheduled", "SCHEDULED") and parse_iso(g["start_time_utc"]) > utcnow())
print("scheduled games in view:", len(tips), "first tip:", tips[:1], flush=True)
if tips:
    wait = (tips[0] - timedelta(minutes=125) - utcnow()).total_seconds()
    if wait > 0:
        print("sleeping", round(wait / 60), "min until first window", flush=True); time.sleep(wait)
while (utcnow() - t0).total_seconds() < deadline_h * 3600:
    now = utcnow()
    games = slate()
    live = [g for g in games if g.get("status") in (None, "scheduled", "SCHEDULED") and parse_iso(g["start_time_utc"]) > now]
    if not live:
        print("no future scheduled games; stopping", flush=True); break
    st = capture_starters(led, games)
    log.append({"at": now.isoformat(), "future_games": len(live), **{k: st[k] for k in ("games_fetched", "rows", "confirmed_teams")}, "failures": st["failures"][:3]})
    print(json.dumps(log[-1]), flush=True)
    time.sleep(poll_s)
rows = list(led.iter_rows(STARTERS_KIND))
(out / "coverage.json").write_text(json.dumps({"rows": len(rows), "coverage": coverage_by_lead_time(rows), "poll_s": poll_s}, indent=1))
(out / "poll_log.json").write_text(json.dumps(log, indent=1))
(out / "rows.jsonl").write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows))
print("rows", len(rows))
